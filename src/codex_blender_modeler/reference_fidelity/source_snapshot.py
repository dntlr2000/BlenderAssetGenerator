"""Append-only build input snapshots without changing the meaning of legacy fingerprints."""

from __future__ import annotations

import json
from pathlib import Path

from ..autonomy.io import write_immutable_json
from ..blender_artifacts import publish_bytes_create_once
from ..build_provenance import canonical_json_sha256, collect_build_provenance
from ..models import SceneSpec
from .models import BuildSourceSnapshotV01, FidelityArtifact, RenderEvidenceV01


def _bound_inputs(value: object) -> dict[str, str]:
    """Extract the path/hash pairs explicitly covered by a V0.5 build fingerprint."""

    result: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and (key == "path" or key.endswith("_path")):
                hash_key = "sha256" if key == "path" else key[:-5] + "_sha256"
                if isinstance(value.get(hash_key), str):
                    result[item] = value[hash_key]
            if key == "geometry_payloads_sha256" and isinstance(item, dict):
                result.update(item)
            else:
                for path, digest in _bound_inputs(item).items():
                    if path in result and result[path] != digest:
                        raise ValueError("build provenance has conflicting source hashes")
                    result[path] = digest
    elif isinstance(value, list):
        for item in value:
            result.update(_bound_inputs(item))
    return result


def _copy_source(root: Path, source: FidelityArtifact, output: Path) -> FidelityArtifact:
    """Copy exact bytes into a contained immutable content-addressed snapshot."""

    from ..production.validation import ensure_contained_production_path
    from .service import artifact_at, read_artifact

    output = ensure_contained_production_path(root, output, must_exist=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    publish_bytes_create_once(output, read_artifact(root, source))
    return artifact_at(root, output)


def capture_build_sources(
    root: Path, scene_path: Path, *, expected_fingerprint: str, output: Path
) -> BuildSourceSnapshotV01:
    """Match actual build identity before snapshotting current mutable authoring inputs."""

    from ..build_provenance import _material_binding_override_paths
    from ..material_manifest import load_material_manifest
    from .service import artifact_at, read_artifact

    scene_artifact = artifact_at(root, scene_path)
    scene = SceneSpec.model_validate_json(read_artifact(root, scene_artifact))
    provenance = collect_build_provenance(root, scene.job_id, scene_spec_path=scene_path)
    if provenance["fingerprint"] != expected_fingerprint:
        provenance = collect_build_provenance(
            root, scene.job_id, scene_spec_path=scene_path, material_plan_mode="scene_spec_only"
        )
    if provenance["fingerprint"] != expected_fingerprint:
        raise ValueError("current build inputs do not match the actual rendered build")
    overrides = _material_binding_override_paths(root, scene.model_dump(mode="json"))
    files = {}
    for name, digest in sorted(_bound_inputs(provenance).items()):
        source = artifact_at(root, overrides.get(name, root / name))
        if source.sha256 != digest:
            raise ValueError("build source changed while its snapshot was captured")
        files[name] = _copy_source(root, source, output / "files" / digest)
    extras = {}
    for material in scene.materials:
        manifest, path = load_material_manifest(material.model_dump(mode="json"), root)
        if manifest is None:
            continue
        sources = [path] + [
            Path(channel["resolved_path"])
            for channel in manifest["channels"].values()
            if channel.get("source") == "image"
        ]
        for path in sources:
            source = artifact_at(root, path)
            extras[source.path] = _copy_source(root, source, output / "files" / source.sha256)
    path = output / "build_provenance.json"
    write_immutable_json(root, path, provenance)
    return BuildSourceSnapshotV01(
        provenance=artifact_at(root, path), files=files, supplemental_scene_materials=extras
    )


def validate_build_sources(root: Path, evidence: RenderEvidenceV01) -> None:
    """Rehash immutable material/source snapshots, never current mutable canonical inputs."""

    from .service import read_artifact

    snapshot = evidence.build_sources
    if snapshot is None:
        return
    payload = json.loads(read_artifact(root, snapshot.provenance))
    declared = payload.pop("fingerprint", None)
    if declared != canonical_json_sha256(payload) or declared != evidence.build_fingerprint:
        raise ValueError("source snapshots do not match the actual build fingerprint")
    if payload.get("scene_spec_sha256") != evidence.scene_spec.sha256:
        raise ValueError("build provenance snapshots belong to a different scene")
    expected = _bound_inputs(payload)
    if set(expected) != set(snapshot.files):
        raise ValueError("build source snapshot omits or adds a dependency")
    for name, artifact in snapshot.files.items():
        read_artifact(root, artifact)
        if expected[name] != artifact.sha256:
            raise ValueError("source snapshot differs from the rendered build input")
    for artifact in snapshot.supplemental_scene_materials.values():
        read_artifact(root, artifact)
