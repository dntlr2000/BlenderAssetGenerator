"""Canonical-source provenance collection for V0.7 derived asset runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..blender_artifacts import stable_json_digest
from ..build_provenance import collect_build_provenance
from ..external_intake.models import ExternalAssetManifest
from ..external_intake.service import collect_external_build_provenance
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
    """Create one contained artifact and verify any contract-supplied digest."""

    if not path.is_file():
        raise FileNotFoundError(path)
    actual_digest = sha256_file(path)
    if digest is not None and actual_digest != digest:
        raise RuntimeError(
            f"Canonical source artifact hash mismatch: {job_relative(root, path)}"
        )
    return HashedArtifact(
        id=artifact_id,
        kind=kind,
        path=job_relative(root, path),
        sha256=actual_digest,
    )


def _collect_scene_spec_source(root: Path, job_id: str) -> SourceProvenance:
    """Collect the legacy SceneSpec-backed V0.7 source without changing its contract."""

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
        source_kind="scene_spec",
        scene_spec=scene_artifact,
        blend=blend_artifact,
        source_fingerprint=stable_json_digest(fingerprint_payload),
        build_fingerprint=str(build["fingerprint"]),
        geometry_payloads=geometry_payloads,
        material_plan=material_plan,
        texture_manifests=texture_manifests,
    )


def _external_artifact(
    root: Path,
    artifact_id: str,
    kind: str,
    relative_path: str,
    digest: str,
) -> HashedArtifact:
    """Convert one external-intake artifact into the shared V0.7 provenance shape."""

    return _artifact(root, artifact_id, kind, root / relative_path, digest)


def _collect_external_source(root: Path, job_id: str) -> SourceProvenance:
    """Collect a validated External Static Asset Intake as an alternate V0.7 source."""

    manifest_path = root / "intake" / "external_asset_manifest.json"
    manifest = ExternalAssetManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if manifest.job_id != job_id:
        raise RuntimeError("External asset manifest job_id does not match the V0.7 job")
    build = collect_external_build_provenance(root, job_id)
    manifest_artifact = _artifact(
        root,
        "source.external_asset_manifest",
        "external_asset_manifest",
        manifest_path,
    )
    blend_artifact = _external_artifact(
        root,
        "source.blend",
        "blend",
        manifest.normalized_blend.path,
        manifest.normalized_blend.sha256,
    )
    source_artifacts = [
        _external_artifact(
            root,
            "source.external.primary",
            "external_source",
            manifest.source.path,
            manifest.source.sha256,
        ),
        *[
            _external_artifact(
                root,
                f"source.external.dependency.{index}",
                "external_dependency",
                artifact.path,
                artifact.sha256,
            )
            for index, artifact in enumerate(manifest.dependencies, start=1)
        ],
        _external_artifact(
            root,
            "source.external.intake_plan",
            "external_intake_plan",
            manifest.intake_plan.path,
            manifest.intake_plan.sha256,
        ),
        _external_artifact(
            root,
            "source.external.intake_approval",
            "external_intake_approval",
            manifest.intake_approval.path,
            manifest.intake_approval.sha256,
        ),
        _external_artifact(
            root,
            "source.external.normalization_evidence",
            "external_normalization_evidence",
            manifest.normalization_evidence.path,
            manifest.normalization_evidence.sha256,
        ),
    ]
    material_plan = _external_artifact(
        root,
        "source.material_plan",
        "material_plan",
        manifest.material_plan.path,
        manifest.material_plan.sha256,
    )
    fingerprint_payload = {
        "source_kind": "external_static_asset",
        "external_asset_manifest": manifest_artifact.model_dump(mode="json"),
        "external_source_artifacts": [
            item.model_dump(mode="json") for item in source_artifacts
        ],
        "blend": blend_artifact.model_dump(mode="json"),
        "material_plan": material_plan.model_dump(mode="json"),
        "build_fingerprint": str(build["fingerprint"]),
    }
    return SourceProvenance(
        source_kind="external_static_asset",
        external_asset_manifest=manifest_artifact,
        external_source_artifacts=source_artifacts,
        blend=blend_artifact,
        source_fingerprint=stable_json_digest(fingerprint_payload),
        build_fingerprint=str(build["fingerprint"]),
        material_plan=material_plan,
    )


def collect_source_build_provenance(job_root: Path, job_id: str) -> dict[str, Any]:
    """Collect the current build contract for either canonical source kind."""

    root = job_root.expanduser().resolve()
    scene_spec = root / "analysis" / "scene_spec.json"
    external_manifest = root / "intake" / "external_asset_manifest.json"
    if scene_spec.is_file() and external_manifest.is_file():
        raise RuntimeError("A V0.7 job cannot have both SceneSpec and external canonical sources")
    if external_manifest.is_file():
        return collect_external_build_provenance(root, job_id)
    return collect_build_provenance(root, job_id, scene_spec_path=scene_spec)


def collect_source_provenance(job_root: Path, job_id: str) -> SourceProvenance:
    """Freeze either SceneSpec or external-static canonical inputs plus the built scene."""

    root = job_root.expanduser().resolve()
    scene_spec = root / "analysis" / "scene_spec.json"
    external_manifest = root / "intake" / "external_asset_manifest.json"
    if scene_spec.is_file() and external_manifest.is_file():
        raise RuntimeError("A V0.7 job cannot have both SceneSpec and external canonical sources")
    if external_manifest.is_file():
        return _collect_external_source(root, job_id)
    return _collect_scene_spec_source(root, job_id)


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
