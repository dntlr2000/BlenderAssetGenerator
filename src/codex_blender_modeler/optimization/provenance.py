"""Canonical-source provenance collection for V0.7 derived asset runs."""

from __future__ import annotations

from pathlib import Path

from ..blender_artifacts import stable_json_digest
from ..build_provenance import collect_build_provenance
from ..workspace import sha256_file
from .io import job_relative
from .models import HashedArtifact, SourceProvenance


def _artifact(
    root: Path,
    artifact_id: str,
    kind: str,
    path: Path,
    digest: str | None = None,
) -> HashedArtifact:
    """Create one contained hashed-artifact record from a canonical job file."""

    if not path.is_file():
        raise FileNotFoundError(path)
    return HashedArtifact(
        id=artifact_id,
        kind=kind,
        path=job_relative(root, path),
        sha256=digest or sha256_file(path),
    )


def collect_source_provenance(job_root: Path, job_id: str) -> SourceProvenance:
    """Freeze every canonical geometry and material input plus the built scene hash."""

    root = job_root.expanduser().resolve()
    scene_spec = root / "analysis" / "scene_spec.json"
    blend = root / "blender" / "scene.blend"
    if not blend.is_file():
        raise FileNotFoundError(f"Built Blender scene does not exist: {blend}")
    build = collect_build_provenance(root, job_id, scene_spec_path=scene_spec)
    geometry_payloads = [
        _artifact(
            root,
            f"source.geometry.{index}",
            "geometry_payload",
            root / relative,
            str(digest),
        )
        for index, (relative, digest) in enumerate(
            sorted(build["geometry_payloads_sha256"].items()),
            start=1,
        )
    ]
    material_plan = None
    material_plan_path = build.get("material_plan_path")
    if material_plan_path:
        material_plan = _artifact(
            root,
            "source.material_plan",
            "material_plan",
            root / str(material_plan_path),
            str(build["material_plan_sha256"]),
        )
    manifest_paths = sorted(
        {
            str(record["texture_manifest_path"])
            for record in build.get("materials", {}).values()
            if isinstance(record, dict) and record.get("texture_manifest_path")
        }
    )
    texture_manifests = [
        _artifact(
            root,
            f"source.texture_manifest.{index}",
            "texture_manifest",
            root / relative,
        )
        for index, relative in enumerate(manifest_paths, start=1)
    ]
    scene_artifact = _artifact(
        root,
        "source.scene_spec",
        "scene_spec",
        scene_spec,
        str(build["scene_spec_sha256"]),
    )
    blend_artifact = _artifact(root, "source.blend", "blend", blend)
    fingerprint_payload = {
        "scene_spec": scene_artifact.model_dump(mode="json"),
        "blend": blend_artifact.model_dump(mode="json"),
        "build_fingerprint": str(build["fingerprint"]),
        "geometry_payloads": [
            item.model_dump(mode="json") for item in geometry_payloads
        ],
        "material_plan": (
            material_plan.model_dump(mode="json") if material_plan is not None else None
        ),
        "texture_manifests": [
            item.model_dump(mode="json") for item in texture_manifests
        ],
    }
    return SourceProvenance(
        scene_spec=scene_artifact,
        blend=blend_artifact,
        source_fingerprint=stable_json_digest(fingerprint_payload),
        build_fingerprint=str(build["fingerprint"]),
        geometry_payloads=geometry_payloads,
        material_plan=material_plan,
        texture_manifests=texture_manifests,
    )


def require_unchanged_source(
    expected: SourceProvenance,
    job_root: Path,
    job_id: str,
) -> SourceProvenance:
    """Reject a run if any canonical input or source blend changed during derivation."""

    current = collect_source_provenance(job_root, job_id)
    if current != expected:
        raise RuntimeError(
            "Canonical source changed during V0.7 derivation; discard the derived run and rebuild."
        )
    return current
