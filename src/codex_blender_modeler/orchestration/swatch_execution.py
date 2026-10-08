"""Exact opt-in render-backend selection for one native material swatch attempt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..blender_artifacts import sha256_directory, write_json_atomic
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..production.validation import ensure_contained_production_path
from ..workspace import sha256_file
from .models import (
    JobId,
    JobRelativePath,
    Sha256,
    WorkflowAttempt,
    WorkflowId,
    _validate_job_relative_path,
)

SwatchBackend = Literal["eevee_auto", "cycles_cpu"]
BACKENDS = {"eevee_auto": ("eevee", "auto"), "cycles_cpu": ("cycles", "cpu")}


class MaterialSwatchExecution(BaseModel):
    """Bind one explicit backend choice to exact native workflow and build evidence."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["0.1.0"] = "0.1.0"
    job_id: JobId
    workflow_id: WorkflowId
    step_id: Literal["material.swatches"] = "material.swatches"
    attempt_id: str = Field(pattern=r"^attempt-[0-9]{4}-[a-f0-9]{8}$")
    backend: SwatchBackend
    plan_sha256: Sha256
    request_sha256: Sha256
    input_fingerprint: Sha256
    blend_sha256: Sha256
    build_fingerprint: Sha256
    source_sha256: dict[JobRelativePath, Sha256]
    dependency_sha256: dict[JobRelativePath, Sha256]
    material_ids: list[str] = Field(min_length=1)
    failed_attempt_path: JobRelativePath | None = None
    failed_attempt_sha256: Sha256 | None = None
    no_engine_parity_claim: Literal[True] = True

    @model_validator(mode="after")
    def validate_binding(self) -> MaterialSwatchExecution:
        """Require complete failed-receipt bindings and unique full material coverage."""

        if (self.failed_attempt_path is None) != (self.failed_attempt_sha256 is None):
            raise ValueError("failed attempt path and SHA-256 must be supplied together")
        if len(set(self.material_ids)) != len(self.material_ids):
            raise ValueError("material IDs must be unique")
        return self


def safe_path(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    """Resolve a contained evidence path while rejecting links and junctions."""

    _validate_job_relative_path(relative)
    return ensure_contained_production_path(root, root / relative, must_exist=must_exist)


def artifact_digest(root: Path, relative: str) -> str:
    """Hash one safe dependency file or complete directory without following links."""

    path = safe_path(root, relative)
    return sha256_directory(path) if path.is_dir() else sha256_file(path)


def source_evidence(root: Path) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Collect current recursive build inputs and exact canonical file bindings."""

    provenance = collect_build_provenance(root, root.name)
    paths = {"job.json", "analysis/scene_spec.json", "analysis/material_plan.json",
             "blender/scene.blend"}
    if (root / "analysis/modeling_plan.json").is_file():
        paths.add("analysis/modeling_plan.json")

    def collect(value: Any) -> None:
        """Collect every path declared by the canonical recursive build fingerprint."""

        if isinstance(value, dict):
            for key, item in value.items():
                if (key == "path" or key.endswith("_path")) and isinstance(item, str):
                    paths.add(item)
                elif key == "geometry_payloads_sha256" and isinstance(item, dict):
                    paths.update(item)
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(provenance)
    hashes = {path: sha256_file(safe_path(root, path)) for path in sorted(paths)}
    spec = json.loads(safe_path(root, "analysis/scene_spec.json").read_bytes())
    ids = sorted(material["id"] for material in spec["materials"])
    return provenance, hashes, ids


def validate_selection(
    root: Path, workflow_root: Path, plan: Any, previous: Any, state: Any, *,
    backend: str | None, input_fingerprint: str | None, failed_attempt_sha256: str | None,
    retry_failed: bool,
) -> dict[str, Any] | None:
    """Allow a bound ready step or an explicit exact-failure retry, never stale adoption."""

    if backend is None:
        if input_fingerprint is not None or failed_attempt_sha256 is not None:
            raise ValueError("material swatch binding requires an explicit backend")
        return None
    if backend not in BACKENDS:
        raise ValueError("material swatch backend must be eevee_auto or cycles_cpu")
    if state.current_step_id != "material.swatches":
        raise ValueError("backend selection requires the exact current material.swatches step")
    step = next(item for item in plan.steps if item.step_id == state.current_step_id)
    current = next(item for item in state.steps if item.step_id == state.current_step_id)
    if (step.tool_name != "render_material_swatches" or step.execution_mode != "host"
            or current.status != "ready" or input_fingerprint != current.input_fingerprint):
        raise ValueError("material swatch step is not ready with the exact input fingerprint")
    failed_path = None
    attempts = sorted((workflow_root / "attempts" / step.step_id).glob("*.json"))
    if attempts:
        latest_path = safe_path(root, attempts[-1].relative_to(root).as_posix())
        latest = WorkflowAttempt.model_validate_json(latest_path.read_bytes())
        if (not retry_failed or failed_attempt_sha256 != sha256_file(latest_path)
                or latest.status != "failed" or latest.reason_code not in {None, "host_failure"}
                or latest.error_type in {
                    "OrchestrationArtifactConflict", "RequiresStandardWorkflow"
                }
                or latest.job_id != root.name or latest.workflow_id != plan.workflow_id
                or latest.step_id != step.step_id or latest.plan_sha256 != state.plan_sha256
                or latest.input_fingerprint != input_fingerprint
                or previous is None or previous.status != "failed"
                or previous.current_step_id != step.step_id):
            raise ValueError("backend retry requires the exact latest failed host attempt")
        failed_path = latest_path.relative_to(root).as_posix()
    elif retry_failed or failed_attempt_sha256 is not None:
        raise ValueError("fresh swatch selection cannot claim failed retry evidence")
    step_map = {item.step_id: item for item in plan.steps}
    dependencies: set[str] = set()
    pending = list(step.depends_on)
    while pending:
        dependency = pending.pop()
        if dependency not in dependencies:
            dependencies.add(dependency)
            pending.extend(step_map[dependency].depends_on)
    dependency_paths = {
        path for item in plan.steps if item.step_id in dependencies
        for output in item.outputs for path in (output.path, output.source_path) if path is not None
    }
    dependency_hashes = {path: artifact_digest(root, path) for path in sorted(dependency_paths)}
    provenance, hashes, ids = source_evidence(root)
    return dict(backend=backend, input_fingerprint=input_fingerprint,
                plan_sha256=state.plan_sha256, request_sha256=plan.request_sha256,
                blend_sha256=hashes["blender/scene.blend"],
                build_fingerprint=provenance["fingerprint"], source_sha256=hashes,
                material_ids=ids, dependency_sha256=dependency_hashes,
                failed_attempt_path=failed_path,
                failed_attempt_sha256=failed_attempt_sha256)


def require_current_sources(root: Path, selection: MaterialSwatchExecution) -> None:
    """Recheck exact current source bytes, recursive provenance, plan and failed receipt."""

    provenance, hashes, ids = source_evidence(root)
    if (hashes != selection.source_sha256 or ids != selection.material_ids
            or provenance["fingerprint"] != selection.build_fingerprint):
        raise ValueError("material swatch execution source changed")
    if any(artifact_digest(root, path) != digest
           for path, digest in selection.dependency_sha256.items()):
        raise ValueError("material swatch predecessor evidence changed")
    workflow = f"workflows/{selection.workflow_id}"
    for path, expected in ((f"{workflow}/plan.json", selection.plan_sha256),
                           (f"{workflow}/request.json", selection.request_sha256),
                           (selection.failed_attempt_path, selection.failed_attempt_sha256)):
        if path is not None and sha256_file(safe_path(root, path)) != expected:
            raise ValueError("material swatch execution authority changed")


def validate_manifest(root: Path, manifest: dict[str, Any]) -> None:
    """Verify selected-backend evidence and every run-owned PNG without staling history."""

    binding = manifest.get("workflow_swatch_execution")
    if binding is None:
        return
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise ValueError("invalid material swatch execution binding")
    path = safe_path(root, binding["path"])
    if sha256_file(path) != binding["sha256"]:
        raise ValueError("material swatch execution selection hash changed")
    selection = MaterialSwatchExecution.model_validate_json(path.read_bytes())
    expected_path = (f"workflows/{selection.workflow_id}/swatch_executions/"
                     f"{selection.attempt_id}/selection.json")
    if selection.job_id != root.name or binding["path"] != expected_path:
        raise ValueError("material swatch execution identity mismatch")
    for relative, expected in (
        (f"workflows/{selection.workflow_id}/plan.json", selection.plan_sha256),
        (f"workflows/{selection.workflow_id}/request.json", selection.request_sha256),
        (selection.failed_attempt_path, selection.failed_attempt_sha256),
    ):
        if relative is not None and sha256_file(safe_path(root, relative)) != expected:
            raise ValueError("material swatch immutable authority changed")
    engine = manifest.get("render_engine")
    device = manifest.get("render_device")
    if ((selection.backend == "cycles_cpu" and (engine, device) != ("CYCLES", "CPU"))
            or (selection.backend == "eevee_auto"
                and (engine not in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}
                     or device != "DEFAULT"))):
        raise ValueError("material swatch actual backend differs from the selection")
    if manifest.get("build_fingerprint") != selection.build_fingerprint:
        raise ValueError("material swatch Blender build binding differs from the selection")
    if manifest.get("job_id") != selection.job_id or manifest.get("resolution") != [512, 512]:
        raise ValueError("material swatch job or resolution differs from selection")
    records = manifest.get("swatches", [])
    if not isinstance(records, list) or any(
        not isinstance(record, dict) or any(not isinstance(record.get(key), str)
                                           for key in ("material_id", "path", "sha256"))
        for record in records
    ):
        raise ValueError("material swatch records are malformed")
    if (sorted(record["material_id"] for record in records) != selection.material_ids
            or manifest.get("material_count") != len(selection.material_ids)
            or manifest.get("source_material_count") != len(selection.material_ids)):
        raise ValueError("material swatch coverage differs from exact source materials")
    output_root = path.parent / "swatches"
    if len({record["path"] for record in records}) != len(records):
        raise ValueError("material swatch output paths must be unique")
    for record in records:
        image = safe_path(root, record["path"])
        if not image.is_relative_to(output_root) or sha256_file(image) != record["sha256"]:
            raise ValueError("material swatch PNG is stale or outside this execution")
        if (record.get("width"), record.get("height"), record.get("encoding")) != (
            512, 512, "png-rgba8"
        ):
            raise ValueError("material swatch encoding metadata differs from fixed render")
        with Image.open(image) as decoded:
            if decoded.format != "PNG" or decoded.size != (512, 512) or decoded.mode != "RGBA":
                raise ValueError("material swatch bytes do not match PNG RGBA 512 contract")
            decoded.verify()


def execute_selection(root: Path, selection: MaterialSwatchExecution) -> None:
    """Render a fresh attempt-owned set and publish only after exact source verification."""

    require_current_sources(root, selection)
    relative = (f"workflows/{selection.workflow_id}/swatch_executions/"
                f"{selection.attempt_id}")
    directory = safe_path(root, relative, must_exist=False)
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "selection.json"
    write_json_atomic(path, selection.model_dump(mode="json"))
    render_manifest = directory / "render_manifest.json"
    engine, device = BACKENDS[selection.backend]
    run_blender("render_material_swatches.py", [
        "--output-dir", str(directory / "swatches"), "--manifest", str(render_manifest),
        "--render-engine", engine, "--render-device", device, "--size", "512",
        "--build-fingerprint", selection.build_fingerprint,
    ], blend_file=safe_path(root, "blender/scene.blend"))
    manifest = json.loads(render_manifest.read_bytes())
    # Blender's local manifest paths become portable owning-job paths in workflow evidence.
    for record in manifest.get("swatches", []):
        local = Path(record["path"])
        candidate = local if local.is_absolute() else directory / local
        record["path"] = candidate.relative_to(root).as_posix()
    manifest["workflow_swatch_execution"] = {
        "path": path.relative_to(root).as_posix(), "sha256": sha256_file(path),
    }
    require_current_sources(root, selection)
    validate_manifest(root, manifest)
    write_json_atomic(directory / "manifest.json", manifest)
    canonical = safe_path(root, "reports/material_swatches.json", must_exist=False)
    if canonical.exists():
        # Preserve the previous derived manifest; failed partial PNGs are never overwritten.
        (directory / "previous_material_swatches.json").write_bytes(canonical.read_bytes())
    write_json_atomic(canonical, manifest)
