from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..workspace import job_dir, sha256_file
from .io import load_bake_manifest

BakeProfile = Literal[
    "blender_eevee",
    "blender_cycles",
    "gltf_pbr",
]


class BakeJobError(RuntimeError):
    """Expose a validated failed bake report without hiding successful material outputs."""

    def __init__(self, message: str, report: dict[str, Any]) -> None:
        """Store the aggregate report alongside the human-readable failure message."""

        super().__init__(message)
        self.report = report


def _resolve_inside(root: Path, value: str, label: str) -> Path:
    """Resolve a bake artifact while rejecting traversal outside the job workspace."""

    path = (root / value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise BakeJobError(f"{label} is outside the job workspace: {path}", {}) from exc
    return path


def _validate_report_artifacts(
    root: Path,
    report: dict[str, Any],
    build_provenance: dict[str, Any],
    source_blend_sha256: str,
) -> list[dict[str, Any]]:
    """Validate every bake output and bind its manifest to current build inputs."""

    manifests: list[dict[str, Any]] = []
    paths = report.get("manifest_paths", [])
    if not isinstance(paths, list):
        raise BakeJobError("Bake report manifest_paths must be an array", report)
    for value in paths:
        if not isinstance(value, str):
            raise BakeJobError("Bake report manifest paths must be strings", report)
        path = _resolve_inside(root, value, "bake manifest")
        if not path.is_file():
            raise BakeJobError(f"Bake manifest was not written: {path}", report)
        manifest = load_bake_manifest(path)
        payload = manifest.model_dump(mode="json")
        if manifest.job_id != report.get("job_id"):
            raise BakeJobError(f"Bake manifest job mismatch: {path}", report)
        material_source = build_provenance["materials"].get(manifest.material_id)
        if not isinstance(material_source, dict):
            raise BakeJobError(
                f"Bake manifest material lacks current build provenance: {manifest.material_id}",
                report,
            )
        expected = {
            "source_scene_spec_sha256": build_provenance["scene_spec_sha256"],
            "source_geometry_payloads_sha256": build_provenance[
                "geometry_payloads_sha256"
            ],
            "source_camera_fingerprint": build_provenance["camera_fingerprint"],
            "source_material_plan_sha256": build_provenance["material_plan_sha256"],
            "source_shader_recipe": material_source["shader_recipe_path"],
            "source_shader_recipe_sha256": material_source["shader_recipe_sha256"],
            "source_texture_manifest": material_source["texture_manifest_path"],
            "source_texture_manifest_sha256": material_source["texture_manifest_sha256"],
            "source_texture_channels_sha256": {
                channel: record["sha256"]
                for channel, record in material_source["texture_channels"].items()
            },
            "source_blend_sha256": source_blend_sha256,
            "source_build_fingerprint": build_provenance["fingerprint"],
            "source_material_fingerprint": material_source["fingerprint"],
        }
        for field, expected_value in expected.items():
            actual_value = getattr(manifest, field)
            if actual_value != expected_value:
                raise BakeJobError(
                    f"Bake manifest provenance mismatch for {manifest.material_id}.{field}: "
                    f"expected={expected_value!r} actual={actual_value!r}",
                    report,
                )
        for output in manifest.outputs:
            artifact = _resolve_inside(root, output.path, "bake output")
            if not artifact.is_file():
                raise BakeJobError(f"Baked output was not written: {artifact}", report)
            actual = sha256_file(artifact)
            if output.sha256 != actual:
                raise BakeJobError(
                    f"Baked output hash mismatch: {artifact} "
                    f"expected={output.sha256} actual={actual}",
                    report,
                )
        manifests.append(payload)
    return manifests


def bake_job_materials(
    job_id: str,
    *,
    profile: BakeProfile = "gltf_pbr",
    resolution: int = 1024,
    margin_px: int = 16,
    render_device: Literal["auto", "cpu", "gpu"] = "auto",
    material_ids: list[str] | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Bake five portable PBR channels from an approved built scene using Cycles."""

    if profile not in {"blender_eevee", "blender_cycles", "gltf_pbr"}:
        raise ValueError(
            "Implemented bake profiles are blender_eevee, blender_cycles, and gltf_pbr; "
            "runtime-specific channel packing is deferred until a target adapter is selected"
        )
    if resolution < 1 or resolution > 8192:
        raise ValueError("resolution must be in [1, 8192]")
    if margin_px < 0:
        raise ValueError("margin_px must be non-negative")
    root = job_dir(job_id)
    blend = root / "blender" / "scene.blend"
    if not blend.is_file():
        raise FileNotFoundError(f"Built Blender scene does not exist: {blend}")
    build_provenance = collect_build_provenance(root, job_id)
    if build_provenance["material_plan_sha256"] is None:
        raise BakeJobError("Material baking requires an authored MaterialPlan", {})
    source_blend_sha256 = sha256_file(blend)
    report_path = root / "reports" / "material_bakes.json"
    args = [
        "--job-root",
        str(root),
        "--report",
        str(report_path),
        "--profile",
        profile,
        "--resolution",
        str(resolution),
        "--margin",
        str(margin_px),
        "--render-device",
        render_device,
        "--expected-build-fingerprint",
        str(build_provenance["fingerprint"]),
        "--source-blend-sha256",
        source_blend_sha256,
    ]
    for material_id in material_ids or []:
        args.extend(["--material-id", material_id])
    run_blender("bake_materials.py", args, blend_file=blend)
    if not report_path.is_file():
        raise BakeJobError(f"Blender did not write the bake report: {report_path}", {})
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise BakeJobError("Bake report root must be an object", {})
    if report.get("source_build_fingerprint") != build_provenance["fingerprint"]:
        raise BakeJobError("Bake report build fingerprint does not match current contracts", report)
    if report.get("source_blend_sha256") != source_blend_sha256:
        raise BakeJobError("Bake report source blend hash does not match the opened scene", report)
    report["manifests"] = _validate_report_artifacts(
        root,
        report,
        build_provenance,
        source_blend_sha256,
    )
    if strict and not bool(report.get("ok")):
        failed = ", ".join(str(value) for value in report.get("failed_material_ids", []))
        raise BakeJobError(f"Material baking failed for: {failed or 'unknown material'}", report)
    return report
