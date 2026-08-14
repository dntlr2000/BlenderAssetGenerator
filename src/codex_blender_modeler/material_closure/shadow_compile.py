"""Isolated Blender 5 material shadow build, inspection, and neutral preview runtime."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from ..blender_artifacts import native_io_path, safe_artifact_name, sha256_file, stable_json_digest
from ..blender_runner import run_blender
from ..config import get_settings
from ..material_graph.compiler_service import MaterialGraphCompilerService
from ..material_graph.models import MaterialGraphSpec
from .models import (
    ExactArtifact,
    MaterialClosureIssue,
    MaterialDependencyClosure,
    MaterialNeutralPreviewManifest,
    MaterialPreflightCheck,
    MaterialPromotionPreflightRequest,
    MaterialShadowCompileReceipt,
)
from .preflight import (
    MaterialPreflightValidationError,
    collect_current_uv_layout_fingerprint,
    resolve_contained_path,
    validate_exact_artifact,
)

_PRODUCER = "material_closure_service"
_PRODUCER_VERSION = "0.1.0"
SHADOW_BLENDER_RUN_COUNT = 6


@dataclass(frozen=True)
class MaterialShadowCompileResult:
    """Return strict shadow evidence plus the exact raw neutral preview inputs."""

    receipt: MaterialShadowCompileReceipt
    preview_image: ExactArtifact | None
    preview_renderer_manifest: ExactArtifact | None
    color_management_fingerprint: str | None
    blender_runs_attempted: int


def _artifact(
    job_root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    media_type: str,
) -> ExactArtifact:
    """Bind one contained regular output file to its exact bytes."""

    root = job_root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise MaterialPreflightValidationError("shadow output escapes the owning job") from exc
    if not os.path.isfile(native_io_path(resolved)):
        raise MaterialPreflightValidationError(f"shadow output is missing: {relative}")
    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=relative,
        sha256=sha256_file(resolved),
        byte_size=os.path.getsize(native_io_path(resolved)),
        media_type=media_type,
    )


def _copy_exact(source: Path, destination: Path, expected_sha256: str) -> None:
    """Copy or adopt one exact immutable input inside the isolated shadow job."""

    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    if os.path.exists(native_io_path(destination)):
        if not os.path.isfile(native_io_path(destination)):
            raise MaterialPreflightValidationError("shadow input destination is not a file")
        if sha256_file(destination) != expected_sha256:
            raise MaterialPreflightValidationError("existing shadow input has different bytes")
        return
    with open(native_io_path(source), "rb") as source_handle:
        with open(native_io_path(destination), "xb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
    if sha256_file(destination) != expected_sha256:
        raise MaterialPreflightValidationError("shadow input copy digest mismatch")


def _replace_shadow_copy(source: Path, destination: Path, expected_sha256: str) -> None:
    """Place approved candidate bytes at a shadow-only canonical or planned-output path."""

    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.candidate.tmp")
    if os.path.exists(native_io_path(temporary)):
        raise MaterialPreflightValidationError("partial shadow candidate copy already exists")
    with open(native_io_path(source), "rb") as source_handle:
        with open(native_io_path(temporary), "xb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
    if sha256_file(temporary) != expected_sha256:
        raise MaterialPreflightValidationError("shadow candidate copy digest mismatch")
    os.replace(native_io_path(temporary), native_io_path(destination))


def _canonical_snapshot(job_root: Path, closure: MaterialDependencyClosure) -> dict[str, str]:
    """Hash every closure-declared canonical input to prove shadow isolation."""

    snapshot: dict[str, str] = {}
    for entry in closure.entries:
        if entry.ownership != "canonical":
            continue
        source = resolve_contained_path(job_root, entry.path, must_exist=True)
        snapshot[entry.path] = sha256_file(source)
    return dict(sorted(snapshot.items()))


def _publish_shadow_inputs(
    job_root: Path,
    shadow_root: Path,
    *,
    request: MaterialPromotionPreflightRequest,
    closure: MaterialDependencyClosure,
) -> tuple[Path, Path, MaterialGraphSpec]:
    """Mirror closure inputs and adopt candidate bytes only inside the shadow workspace."""

    for entry in closure.entries:
        source = resolve_contained_path(job_root, entry.path, must_exist=True)
        destination = shadow_root.joinpath(*entry.path.split("/"))
        _copy_exact(source, destination, entry.sha256)

    candidate_plan_source = validate_exact_artifact(job_root, request.candidate_material_plan)
    graph_source = validate_exact_artifact(job_root, request.rebound_material_graph)
    graph = MaterialGraphSpec.model_validate_json(graph_source.read_bytes())
    graph_shadow_path = shadow_root.joinpath(*request.rebound_material_graph.path.split("/"))
    _copy_exact(graph_source, graph_shadow_path, request.rebound_material_graph.sha256)

    material_inputs = [item for item in graph.provenance.inputs if item.role == "material_plan"]
    if len(material_inputs) != 1:
        raise MaterialPreflightValidationError(
            "rebound MaterialGraph requires one planned MaterialPlan provenance input"
        )
    graph_material_input = material_inputs[0]
    if graph_material_input.sha256 != request.candidate_material_plan.sha256:
        raise MaterialPreflightValidationError(
            "rebound MaterialGraph targets different candidate MaterialPlan bytes"
        )
    if (
        request.planned_output_projection.get(graph_material_input.path)
        != request.candidate_material_plan.sha256
    ):
        raise MaterialPreflightValidationError(
            "rebound MaterialGraph material path is not a planned controller output"
        )
    _replace_shadow_copy(
        candidate_plan_source,
        shadow_root.joinpath(*graph_material_input.path.split("/")),
        request.candidate_material_plan.sha256,
    )
    shadow_material_plan = shadow_root / "analysis" / "material_plan.json"
    _replace_shadow_copy(
        candidate_plan_source,
        shadow_material_plan,
        request.candidate_material_plan.sha256,
    )
    scene_spec = shadow_root / "analysis" / "scene_spec.json"
    if not os.path.isfile(native_io_path(scene_spec)):
        raise MaterialPreflightValidationError("closure did not populate canonical SceneSpec")
    return scene_spec, graph_shadow_path, graph


def _read_passed_json(path: Path, *, label: str) -> dict[str, Any]:
    """Load a Blender report and require its explicit ok=true result."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterialPreflightValidationError(f"{label} report is invalid") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise MaterialPreflightValidationError(f"{label} did not report ok=true")
    return payload


def _validate_preview(
    job_root: Path,
    manifest_path: Path,
    *,
    expected_material_id: str,
    expected_size: int,
) -> tuple[ExactArtifact, ExactArtifact, str]:
    """Verify one actual fixed neutral swatch and its renderer/color-management evidence."""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterialPreflightValidationError("neutral preview manifest is invalid") from exc
    swatches = payload.get("swatches")
    if (
        not isinstance(swatches, list)
        or len(swatches) != 1
        or swatches[0].get("material_id") != expected_material_id
        or payload.get("resolution") != [expected_size, expected_size]
    ):
        raise MaterialPreflightValidationError("neutral preview targets another material or size")
    relative_image = swatches[0].get("path")
    if not isinstance(relative_image, str):
        raise MaterialPreflightValidationError("neutral preview image path is missing")
    image_path = (manifest_path.parent / relative_image).resolve()
    try:
        image_path.relative_to(manifest_path.parent.resolve())
    except ValueError as exc:
        raise MaterialPreflightValidationError("neutral preview image escapes its run") from exc
    if sha256_file(image_path) != swatches[0].get("sha256"):
        raise MaterialPreflightValidationError("neutral preview image digest changed")
    with Image.open(native_io_path(image_path)) as image:
        image.load()
        if image.format != "PNG" or image.size != (expected_size, expected_size):
            raise MaterialPreflightValidationError("neutral preview is not the expected PNG")
    image_artifact = _artifact(
        job_root,
        image_path,
        artifact_id=f"neutral-preview-{safe_artifact_name(expected_material_id)}",
        kind="neutral_preview_image",
        media_type="image/png",
    )
    renderer_artifact = _artifact(
        job_root,
        manifest_path,
        artifact_id=f"neutral-renderer-{safe_artifact_name(expected_material_id)}",
        kind="neutral_preview_renderer_manifest",
        media_type="application/json",
    )
    color_fingerprint = stable_json_digest(
        {
            "render_engine": payload.get("render_engine"),
            "render_device": payload.get("render_device"),
            "color_management_look": payload.get("color_management_look"),
            "resolution": payload.get("resolution"),
        }
    )
    return image_artifact, renderer_artifact, color_fingerprint


def _safe_issue_message(job_root: Path, exc: Exception) -> str:
    """Remove host-local roots from one persisted shadow failure explanation."""

    message = str(exc).replace(str(job_root.resolve()), "<job_root>")
    message = message.replace(str(get_settings().repo_root.resolve()), "<repo_root>")
    return message[:1800] or type(exc).__name__


def run_material_shadow_compile(
    job_root: Path,
    *,
    request: MaterialPromotionPreflightRequest,
    request_artifact: ExactArtifact,
    closure: MaterialDependencyClosure,
    closure_artifact: ExactArtifact,
    shadow_root_path: str,
    preview_size: int = 512,
    created_at: datetime | None = None,
) -> MaterialShadowCompileResult:
    """Build, inspect, validate, graph-compile, and render in one isolated job mirror."""

    root = job_root.expanduser().resolve()
    validate_exact_artifact(root, request_artifact)
    validate_exact_artifact(root, closure_artifact)
    shadow_root = resolve_contained_path(root, shadow_root_path, must_exist=False)
    if os.path.exists(native_io_path(shadow_root)):
        raise FileExistsError("shadow compile root already exists and cannot be overwritten")
    os.makedirs(native_io_path(shadow_root), exist_ok=False)
    before = _canonical_snapshot(root, closure)
    checks: list[MaterialPreflightCheck] = []
    outputs: list[ExactArtifact] = []
    preview_image: ExactArtifact | None = None
    renderer_manifest: ExactArtifact | None = None
    color_fingerprint: str | None = None
    blender_runs = 0
    blender_version: str | None = None
    blender_executable_sha256: str | None = None
    issue: MaterialClosureIssue | None = None
    try:
        scene_spec, graph_path, graph = _publish_shadow_inputs(
            root,
            shadow_root,
            request=request,
            closure=closure,
        )
        checks.append(
            MaterialPreflightCheck(
                check_id="shadow_inputs",
                category="dependency",
                status="passed",
                message="Every closure input was copied and re-hashed in the isolated job.",
            )
        )

        blender_runs += 1
        bundle = MaterialGraphCompilerService(shadow_root).compile_run(
            graph_spec_path=graph_path.relative_to(shadow_root).as_posix(),
            run_root="graph_compile",
            run_id=request.request_id,
        )
        blender_version = bundle.report.blender_version
        if blender_version != "5.0.1":
            raise MaterialPreflightValidationError(
                "material shadow compile requires exact Blender 5.0.1"
            )
        checks.append(
            MaterialPreflightCheck(
                check_id="graph_compile",
                category="blender",
                status="passed",
                message="Registry-backed MaterialGraph compiled and reopened successfully.",
            )
        )
        outputs.append(
            _artifact(
                root,
                shadow_root / "graph_compile" / "compile_report.json",
                artifact_id=f"shadow-graph-report-{request.request_id}",
                kind="shadow_graph_compile_report",
                media_type="application/json",
            )
        )

        full_scene = shadow_root / "full_scene" / "scene.blend"
        os.makedirs(native_io_path(full_scene.parent), exist_ok=True)
        blender_runs += 1
        run_blender(
            "build_scene.py",
            [
                "--spec",
                str(scene_spec),
                "--job-root",
                str(shadow_root),
                "--output",
                str(full_scene),
            ],
            factory_startup=True,
            disable_autoexec=True,
        )
        checks.append(
            MaterialPreflightCheck(
                check_id="scene_build",
                category="blender",
                status="passed",
                message="Candidate MaterialPlan was applied to an isolated full-scene build.",
            )
        )

        reports = shadow_root / "reports"
        os.makedirs(native_io_path(reports), exist_ok=True)
        inventory = reports / "scene_inventory.json"
        blender_runs += 1
        run_blender(
            "inspect_scene.py",
            ["--output", str(inventory)],
            blend_file=full_scene,
            disable_autoexec=True,
        )
        inventory_artifact = _artifact(
            root,
            inventory,
            artifact_id=f"shadow-inventory-{request.request_id}",
            kind="shadow_scene_inventory",
            media_type="application/json",
        )
        if collect_current_uv_layout_fingerprint(
            root,
            inventory_artifact,
            expected_job_id=request.job_id,
        ) != request.uv_layout_fingerprint:
            raise MaterialPreflightValidationError(
                "shadow scene UV layout differs from the preflight-bound canonical fingerprint"
            )
        checks.append(
            MaterialPreflightCheck(
                check_id="scene_inspect",
                category="blender",
                status="passed",
                message="Isolated full scene was reopened and inventoried.",
            )
        )

        validation = reports / "scene_validation.json"
        blender_runs += 1
        run_blender(
            "validate_scene.py",
            [
                "--spec",
                str(scene_spec),
                "--job-root",
                str(shadow_root),
                "--output",
                str(validation),
            ],
            blend_file=full_scene,
            disable_autoexec=True,
        )
        _read_passed_json(validation, label="shadow scene validation")
        checks.append(
            MaterialPreflightCheck(
                check_id="scene_validate",
                category="blender",
                status="passed",
                message="Isolated full scene passed deterministic scene validation.",
            )
        )

        material_inventory = reports / "material_inventory.json"
        blender_runs += 1
        run_blender(
            "inspect_materials.py",
            ["--output", str(material_inventory)],
            blend_file=full_scene,
            disable_autoexec=True,
        )
        _read_passed_json(material_inventory, label="shadow material inspection")
        checks.append(
            MaterialPreflightCheck(
                check_id="material_inspect",
                category="blender",
                status="passed",
                message="Material assignment, UV, image, and node inventory checks passed.",
            )
        )

        preview_root = shadow_root / "neutral_preview"
        preview_manifest = preview_root / "renderer_manifest.json"
        blender_runs += 1
        run_blender(
            "render_material_swatches.py",
            [
                "--output-dir",
                str(preview_root / "renders"),
                "--manifest",
                str(preview_manifest),
                "--render-engine",
                "eevee",
                "--render-device",
                "auto",
                "--size",
                str(preview_size),
                "--material-id",
                graph.material_id,
            ],
            blend_file=full_scene,
            disable_autoexec=True,
        )
        preview_image, renderer_manifest, color_fingerprint = _validate_preview(
            root,
            preview_manifest,
            expected_material_id=graph.material_id,
            expected_size=preview_size,
        )
        checks.append(
            MaterialPreflightCheck(
                check_id="neutral_preview",
                category="blender",
                status="passed",
                message="An actual fixed neutral-studio PNG was rendered from the shadow scene.",
                evidence=[preview_image, renderer_manifest],
            )
        )

        outputs.extend(
            [
                _artifact(
                    root,
                    full_scene,
                    artifact_id=f"shadow-scene-{request.request_id}",
                    kind="shadow_scene_blend",
                    media_type="application/x-blender",
                ),
                inventory_artifact,
                _artifact(
                    root,
                    validation,
                    artifact_id=f"shadow-validation-{request.request_id}",
                    kind="shadow_scene_validation",
                    media_type="application/json",
                ),
                _artifact(
                    root,
                    material_inventory,
                    artifact_id=f"shadow-materials-{request.request_id}",
                    kind="shadow_material_inventory",
                    media_type="application/json",
                ),
                renderer_manifest,
                preview_image,
            ]
        )
        executable = Path(get_settings().blender_bin).expanduser().resolve()
        blender_executable_sha256 = sha256_file(executable)
    except Exception as exc:
        issue = MaterialClosureIssue(
            code="SHADOW_COMPILE_FAILED",
            message=_safe_issue_message(root, exc),
        )
        checks.append(
            MaterialPreflightCheck(
                check_id="shadow_failure",
                category="blender",
                status="failed",
                message=issue.message,
            )
        )

    if _canonical_snapshot(root, closure) != before:
        raise MaterialPreflightValidationError(
            "canonical input changed during isolated material shadow compilation"
        )
    receipt = MaterialShadowCompileReceipt(
        receipt_id=f"shadow-{request.request_id}",
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        dispatch_id=request.dispatch_id,
        session_id=request.session_id,
        producer=_PRODUCER,
        producer_version=_PRODUCER_VERSION,
        created_at=created_at or datetime.now(UTC),
        preflight_request=request_artifact,
        closure=closure_artifact,
        status="failed" if issue is not None else "passed",
        blender_version=blender_version,
        blender_executable_sha256=blender_executable_sha256,
        shadow_root=shadow_root.relative_to(root).as_posix(),
        checks=checks,
        outputs=outputs,
        issues=[issue] if issue is not None else [],
    )
    return MaterialShadowCompileResult(
        receipt=receipt,
        preview_image=preview_image,
        preview_renderer_manifest=renderer_manifest,
        color_management_fingerprint=color_fingerprint,
        blender_runs_attempted=blender_runs,
    )


def build_neutral_preview_manifest(
    *,
    request: MaterialPromotionPreflightRequest,
    request_artifact: ExactArtifact,
    closure_artifact: ExactArtifact,
    shadow_receipt_artifact: ExactArtifact,
    shadow_result: MaterialShadowCompileResult,
    created_at: datetime | None = None,
) -> MaterialNeutralPreviewManifest:
    """Promote only an actually rendered shadow swatch into pre-approval preview evidence."""

    if (
        shadow_result.receipt.status != "passed"
        or shadow_result.preview_image is None
        or shadow_result.preview_renderer_manifest is None
        or shadow_result.color_management_fingerprint is None
    ):
        raise MaterialPreflightValidationError(
            "neutral preview manifest requires a passed actual shadow render"
        )
    return MaterialNeutralPreviewManifest(
        manifest_id=f"neutral-{request.request_id}",
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        dispatch_id=request.dispatch_id,
        session_id=request.session_id,
        producer=_PRODUCER,
        producer_version=_PRODUCER_VERSION,
        created_at=created_at or datetime.now(UTC),
        closure=closure_artifact,
        preflight_request=request_artifact,
        shadow_compile_receipt=shadow_receipt_artifact,
        candidate_material_plan=request.candidate_material_plan,
        rebound_material_graph=request.rebound_material_graph,
        preview_image=shadow_result.preview_image,
        camera_id="neutral_swatch_camera_v1",
        lighting_profile_id="neutral_three_point_v1",
        color_management_fingerprint=shadow_result.color_management_fingerprint,
    )


__all__ = [
    "SHADOW_BLENDER_RUN_COUNT",
    "MaterialShadowCompileResult",
    "build_neutral_preview_manifest",
    "run_material_shadow_compile",
]
