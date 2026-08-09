from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .blender_runner import run_blender
from .build_provenance import collect_build_provenance
from .interior_qa.models import (
    InteriorQAPlan,
    InteriorQARenderManifest,
    InteriorQASourceInventory,
)
from .qa.models import RenderPassManifest
from .workspace import job_dir, sha256_file


def _blend_path(job_id: str) -> tuple[Path, Path]:
    """Resolve one job root and require its generated Blender scene."""

    root = job_dir(job_id)
    blend = root / "blender" / "scene.blend"
    if not blend.is_file():
        raise FileNotFoundError(f"Built Blender scene does not exist: {blend}")
    return root, blend


def inspect_job_materials(job_id: str) -> dict[str, Any]:
    """Inspect applied material graphs and evaluated mesh UV statistics in Blender."""

    root, blend = _blend_path(job_id)
    output = root / "reports" / "material_validation.json"
    run_blender("inspect_materials.py", ["--output", str(output)], blend_file=blend)
    return json.loads(output.read_text(encoding="utf-8"))


def render_job_material_swatches(
    job_id: str,
    *,
    render_engine: str = "eevee",
    render_device: str = "auto",
    size: int = 512,
    material_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Render fixed sphere/plane swatches for all or selected stable material IDs."""

    root, blend = _blend_path(job_id)
    output_dir = root / "renders" / "materials"
    manifest = root / "reports" / "material_swatches.json"
    args = [
        "--output-dir",
        str(output_dir),
        "--manifest",
        str(manifest),
        "--render-engine",
        render_engine,
        "--render-device",
        render_device,
        "--size",
        str(size),
    ]
    for material_id in material_ids or []:
        args.extend(["--material-id", material_id])
    run_blender("render_material_swatches.py", args, blend_file=blend)
    return json.loads(manifest.read_text(encoding="utf-8"))


def render_job_qa_passes(
    job_id: str,
    *,
    render_engine: str = "eevee",
    render_device: str = "auto",
    run_id: str | None = None,
    camera_fingerprint: str | None = None,
    scene_spec_sha256: str | None = None,
) -> RenderPassManifest:
    """Render seven passes only when the blend matches current canonical build inputs."""

    root, blend = _blend_path(job_id)
    scene_spec = root / "analysis" / "scene_spec.json"
    return render_scene_qa_passes(
        job_id,
        scene_spec_path=scene_spec,
        blend_path=blend,
        output_dir=root / "renders" / "passes",
        manifest_path=root / "reports" / "qa_pass_manifest.json",
        render_engine=render_engine,
        render_device=render_device,
        run_id=run_id,
        camera_fingerprint=camera_fingerprint,
        scene_spec_sha256=scene_spec_sha256,
    )


def render_scene_qa_passes(
    job_id: str,
    *,
    scene_spec_path: Path,
    blend_path: Path,
    output_dir: Path,
    manifest_path: Path,
    render_engine: str = "eevee",
    render_device: str = "auto",
    run_id: str | None = None,
    camera_fingerprint: str | None = None,
    scene_spec_sha256: str | None = None,
    surface_detail_inventory_path: Path | None = None,
) -> RenderPassManifest:
    """Render seven-pass QA against canonical or isolated inventory evidence."""

    root = job_dir(job_id).resolve()
    scene_spec = scene_spec_path.expanduser().resolve()
    blend = blend_path.expanduser().resolve()
    resolved_output_dir = output_dir.expanduser().resolve()
    resolved_manifest = manifest_path.expanduser().resolve()
    for label, path in (
        ("SceneSpec", scene_spec),
        ("Blender scene", blend),
        ("QA output", resolved_output_dir),
        ("QA manifest", resolved_manifest),
    ):
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"{label} must stay inside the owning job") from exc
    if not scene_spec.is_file():
        raise FileNotFoundError(f"SceneSpec does not exist: {scene_spec}")
    if not blend.is_file():
        raise FileNotFoundError(f"Blender scene does not exist: {blend}")
    provenance = collect_build_provenance(
        root,
        job_id,
        scene_spec_path=scene_spec,
        surface_detail_inventory_path=surface_detail_inventory_path,
    )
    current_scene_hash = str(provenance["scene_spec_sha256"])
    current_camera_fingerprint = str(provenance["camera_fingerprint"])
    if scene_spec_sha256 is not None and scene_spec_sha256 != current_scene_hash:
        raise ValueError("requested QA SceneSpec hash does not match the selected SceneSpec")
    if camera_fingerprint is not None and camera_fingerprint != current_camera_fingerprint:
        raise ValueError("requested QA camera fingerprint does not match the selected camera")
    args = [
        "--output-dir",
        str(resolved_output_dir),
        "--manifest",
        str(resolved_manifest),
        "--render-engine",
        render_engine,
        "--render-device",
        render_device,
        "--scene-spec",
        str(scene_spec),
        "--build-fingerprint",
        str(provenance["fingerprint"]),
    ]
    optional = {
        "--run-id": run_id,
        "--camera-fingerprint": current_camera_fingerprint,
        "--scene-spec-sha256": current_scene_hash,
    }
    for flag, value in optional.items():
        if value is not None:
            args.extend([flag, value])
    run_blender("render_qa_passes.py", args, blend_file=blend)
    return RenderPassManifest.model_validate_json(resolved_manifest.read_text(encoding="utf-8"))


def inspect_job_interior_qa_source(
    job_id: str,
    *,
    run_id: str,
    target_ids: list[str],
    output_path: Path,
    scene_spec_sha256: str,
    build_fingerprint: str,
    interior_scope_sha256: str,
    interior_scope_approval_sha256: str,
) -> InteriorQASourceInventory:
    """Inspect fresh interior bounds and topology against exact canonical build hashes."""

    root, blend = _blend_path(job_id)
    scene_spec = root / "analysis" / "scene_spec.json"
    scope = root / "architecture" / "interior_scope.json"
    approval = root / "architecture" / "interior_scope.approval.json"
    args = [
        "--output",
        str(output_path),
        "--scene-spec",
        str(scene_spec),
        "--build-fingerprint",
        build_fingerprint,
        "--scene-spec-sha256",
        scene_spec_sha256,
        "--scope",
        str(scope),
        "--scope-sha256",
        interior_scope_sha256,
        "--scope-approval",
        str(approval),
        "--scope-approval-sha256",
        interior_scope_approval_sha256,
        "--run-id",
        run_id,
    ]
    for target_id in target_ids:
        args.extend(["--target-id", target_id])
    run_blender("inspect_interior_qa_source.py", args, blend_file=blend)
    return InteriorQASourceInventory.model_validate_json(output_path.read_text(encoding="utf-8"))


def render_job_interior_qa(
    job_id: str,
    *,
    plan_path: Path,
    approval_path: Path,
    output_dir: Path,
    manifest_path: Path,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> InteriorQARenderManifest:
    """Render every approved interior view without saving changes to the authoring blend."""

    root, blend = _blend_path(job_id)
    plan = InteriorQAPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    provenance = collect_build_provenance(
        root,
        job_id,
        scene_spec_path=root / "analysis" / "scene_spec.json",
    )
    args = [
        "--plan",
        str(plan_path),
        "--plan-sha256",
        sha256_file(plan_path),
        "--approval",
        str(approval_path),
        "--approval-sha256",
        sha256_file(approval_path),
        "--manifest",
        str(manifest_path),
        "--output-dir",
        str(output_dir),
        "--scene-spec",
        str(root / "analysis" / "scene_spec.json"),
        "--build-fingerprint",
        str(provenance["fingerprint"]),
        "--scope",
        str(root / "architecture" / "interior_scope.json"),
        "--scope-approval",
        str(root / "architecture" / "interior_scope.approval.json"),
        "--render-engine",
        render_engine,
        "--render-device",
        render_device,
    ]
    if str(provenance["fingerprint"]) != plan.build_fingerprint:
        raise ValueError("interior QA plan is stale for the current canonical build")
    run_blender("render_interior_qa.py", args, blend_file=blend)
    return InteriorQARenderManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
