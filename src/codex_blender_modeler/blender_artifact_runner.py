from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .blender_runner import run_blender
from .build_provenance import collect_build_provenance
from .qa.models import RenderPassManifest
from .workspace import job_dir


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
    provenance = collect_build_provenance(root, job_id, scene_spec_path=scene_spec)
    current_scene_hash = str(provenance["scene_spec_sha256"])
    current_camera_fingerprint = str(provenance["camera_fingerprint"])
    if scene_spec_sha256 is not None and scene_spec_sha256 != current_scene_hash:
        raise ValueError("requested QA SceneSpec hash does not match the canonical SceneSpec")
    if (
        camera_fingerprint is not None
        and camera_fingerprint != current_camera_fingerprint
    ):
        raise ValueError("requested QA camera fingerprint does not match the canonical camera")
    output_dir = root / "renders" / "passes"
    manifest = root / "reports" / "qa_pass_manifest.json"
    args = [
        "--output-dir",
        str(output_dir),
        "--manifest",
        str(manifest),
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
    return RenderPassManifest.model_validate_json(manifest.read_text(encoding="utf-8"))
