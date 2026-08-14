from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import pytest
from pydantic import ValidationError

from codex_blender_modeler.blender_scripts.standard_custom_mesh_runtime import (
    ordered_corner_topology_sha256 as runtime_ordered_corner_topology_sha256,
)
from codex_blender_modeler.blender_scripts.standard_custom_mesh_runtime import (
    uv_coordinate_fingerprint as runtime_uv_coordinate_fingerprint,
)
from codex_blender_modeler.blender_scripts.standard_custom_mesh_runtime import (
    validate_standard_custom_mesh_payload,
)
from codex_blender_modeler.build_provenance import (
    BuildProvenanceError,
    _geometry_payload_hashes,
)
from codex_blender_modeler.standard_custom_mesh import (
    StandardCustomMeshPayload,
    ordered_corner_topology_sha256,
    uv_coordinate_fingerprint,
)
from codex_blender_modeler.standard_custom_mesh_candidate import (
    StandardCustomMeshCandidateError,
    prepare_standard_uv_candidate,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    """Hash one test fixture with the same byte semantics as production evidence."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    """Write one deterministic JSON fixture below the pytest temporary workspace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _fixture_payload(root: Path) -> tuple[dict[str, object], dict[str, object]]:
    """Create one exact source closure and return its Standard payload and SceneSpec."""

    vertices = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    faces = [[0, 1, 2]]
    loop_uvs = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    source_spec = {
        "job_id": "standard_test",
        "objects": [
            {
                "id": "asset.body",
                "geometry": {
                    "kind": "custom_mesh",
                    "vertices": vertices,
                    "faces": faces,
                    "recalculate_normals": True,
                },
            }
        ],
    }
    source_spec_path = root / "history" / "base_scene_spec.json"
    source_blend_path = root / "history" / "base_scene.blend"
    _write_json(source_spec_path, source_spec)
    source_blend_path.write_bytes(b"fixture blend bytes")
    payload = {
        "payload_kind": "standard_custom_mesh",
        "schema_version": "0.1.0",
        "job_id": "standard_test",
        "object_id": "asset.body",
        "source_scene_spec_path": "history/base_scene_spec.json",
        "source_scene_spec_sha256": _sha256(source_spec_path),
        "source_blend_path": "history/base_scene.blend",
        "source_blend_sha256": _sha256(source_blend_path),
        "vertices": vertices,
        "faces": faces,
        "loop_uvs": loop_uvs,
        "uv_set": "UVMap",
        "source_coordinate_fingerprint": uv_coordinate_fingerprint(loop_uvs),
        "source_vertex_uv_binding_fingerprint": "3" * 64,
        "ordered_corner_topology_sha256": ordered_corner_topology_sha256(faces),
    }
    scene_spec = {
        "job_id": "standard_test",
        "objects": [
            {
                "id": "asset.body",
                "geometry": {
                    "kind": "custom_mesh",
                    "path": "geometry/asset.body/standard.json",
                },
            }
        ],
    }
    return payload, scene_spec


def test_standard_payload_requires_exact_corner_topology_and_uv_fingerprint(
    tmp_path: Path,
) -> None:
    """Reject reordered topology, missing corners, and stale approved UV identity."""

    payload, _scene_spec = _fixture_payload(tmp_path)
    assert StandardCustomMeshPayload.model_validate(payload).object_id == "asset.body"
    assert validate_standard_custom_mesh_payload(payload) == payload
    assert runtime_ordered_corner_topology_sha256(payload["faces"]) == (
        payload["ordered_corner_topology_sha256"]
    )
    assert runtime_uv_coordinate_fingerprint(payload["loop_uvs"]) == (
        payload["source_coordinate_fingerprint"]
    )

    stale_topology = dict(payload)
    stale_topology["ordered_corner_topology_sha256"] = "4" * 64
    with pytest.raises(ValidationError, match="ordered_corner_topology_sha256"):
        StandardCustomMeshPayload.model_validate(stale_topology)

    missing_corner = dict(payload)
    missing_corner["loop_uvs"] = [*payload["loop_uvs"], [0.5, 0.5]]
    with pytest.raises(ValidationError, match="one pair per ordered polygon corner"):
        StandardCustomMeshPayload.model_validate(missing_corner)

    stale_coordinates = dict(payload)
    stale_coordinates["source_coordinate_fingerprint"] = "5" * 64
    with pytest.raises(ValidationError, match="source_coordinate_fingerprint"):
        StandardCustomMeshPayload.model_validate(stale_coordinates)


def test_standard_payload_rejects_escape_unknown_fields_and_vertex_uv_dialect(
    tmp_path: Path,
) -> None:
    """Keep Standard dependencies contained and prohibit ambiguous UV dialects."""

    payload, _scene_spec = _fixture_payload(tmp_path)
    escaped = dict(payload)
    escaped["source_blend_path"] = "../base.blend"
    with pytest.raises(ValidationError, match="unsafe segment"):
        StandardCustomMeshPayload.model_validate(escaped)

    ambiguous = dict(payload)
    ambiguous["vertex_uvs"] = payload["loop_uvs"]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StandardCustomMeshPayload.model_validate(ambiguous)


def test_build_provenance_binds_standard_payload_identity_and_source_bytes(
    tmp_path: Path,
) -> None:
    """Include the payload hash only when job, object, topology, and sources match."""

    payload, scene_spec = _fixture_payload(tmp_path)
    payload_path = tmp_path / "geometry" / "asset.body" / "standard.json"
    _write_json(payload_path, payload)
    assert _geometry_payload_hashes(tmp_path, scene_spec) == {
        "geometry/asset.body/standard.json": _sha256(payload_path)
    }

    wrong_object = json.loads(json.dumps(scene_spec))
    wrong_object["objects"][0]["id"] = "asset.other"
    with pytest.raises(BuildProvenanceError, match="identity differs"):
        _geometry_payload_hashes(tmp_path, wrong_object)

    (tmp_path / "history" / "base_scene.blend").write_bytes(b"tampered")
    with pytest.raises(BuildProvenanceError, match="source Blend hash is stale"):
        _geometry_payload_hashes(tmp_path, scene_spec)


def test_standard_candidate_is_history_only_hash_bound_and_immutable(
    tmp_path: Path,
) -> None:
    """Prepare one scaled transport candidate without changing its canonical source."""

    root = tmp_path / "standard_test"
    payload, _scene_spec = _fixture_payload(root)
    payload_path = root / "geometry" / "asset.body" / "standard.json"
    _write_json(payload_path, payload)
    base = {
        "job_id": "standard_test",
        "mode": "concept",
        "nominal_scene_size": [1.0, 1.0, 1.0],
        "sources": [],
        "camera": {
            "projection": "ORTHO",
            "location": [3.0, -4.0, 2.0],
            "target": [0.0, 0.0, 0.0],
            "focal_length_mm": 50.0,
            "ortho_scale": 5.0,
            "resolution": [64, 64],
        },
        "materials": [
            {
                "id": "mat.test",
                "name": "Test",
                "base_color": [0.5, 0.4, 0.3, 1.0],
                "roughness": 0.5,
                "metallic": 0.0,
            }
        ],
        "objects": [
            {
                "id": "asset.body",
                "name": "Body",
                "material_id": "mat.test",
                "transform": {
                    "location": [0.0, 0.0, 0.0],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                },
                "geometry": {
                    "kind": "custom_mesh",
                    "vertices": payload["vertices"],
                    "faces": payload["faces"],
                    "recalculate_normals": True,
                },
            }
        ],
    }
    base_path = root / "analysis" / "scene_spec.json"
    _write_json(base_path, base)
    base_bytes = base_path.read_bytes()
    output_dir = (
        root
        / "history"
        / "geometry_revision_plans"
        / "revision-r002"
        / "candidates"
        / "scaled"
    )

    receipt = prepare_standard_uv_candidate(
        job_root=root,
        job_id="standard_test",
        base_scene_spec_path=base_path,
        expected_base_scene_spec_sha256=_sha256(base_path),
        mesh_payload_path=payload_path,
        expected_mesh_payload_sha256=_sha256(payload_path),
        target_object_id="asset.body",
        uniform_scale=1.1,
        output_dir=output_dir,
    )

    candidate = json.loads((output_dir / "scene_spec.json").read_text(encoding="utf-8"))
    target = candidate["objects"][0]
    assert base_path.read_bytes() == base_bytes
    assert target["geometry"]["path"] == "geometry/asset.body/standard.json"
    assert target["geometry"]["vertices"] is None
    assert target["geometry"]["faces"] is None
    assert target["transform"]["scale"] == [1.1, 1.1, 1.1]
    assert receipt["status"] == "prepared_not_promoted"
    assert receipt["canonical_write_performed"] is False
    with pytest.raises(StandardCustomMeshCandidateError, match="immutable"):
        prepare_standard_uv_candidate(
            job_root=root,
            job_id="standard_test",
            base_scene_spec_path=base_path,
            expected_base_scene_spec_sha256=_sha256(base_path),
            mesh_payload_path=payload_path,
            expected_mesh_payload_sha256=_sha256(payload_path),
            target_object_id="asset.body",
            uniform_scale=1.1,
            output_dir=output_dir,
        )


def test_standard_payload_schema_and_fixed_blender_dispatch_are_registered() -> None:
    """Keep schema parity and explicit fixed-script dispatch visible to CI."""

    schema_path = ROOT / "schemas" / "standard_custom_mesh_payload.schema.json"
    assert json.loads(schema_path.read_text(encoding="utf-8")) == (
        StandardCustomMeshPayload.model_json_schema()
    )
    registry = runpy.run_path(str(ROOT / "scripts" / "generate_schemas.py"))["SCHEMAS"]
    assert registry["standard_custom_mesh_payload.schema.json"] is (
        StandardCustomMeshPayload
    )
    builder = (
        ROOT
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "builders"
        / "custom_mesh.py"
    ).read_text(encoding="utf-8")
    extractor = (
        ROOT
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "extract_standard_custom_mesh.py"
    ).read_text(encoding="utf-8")
    assert 'payload_kind == "standard_custom_mesh"' in builder
    assert "validate_standard_custom_mesh_payload" in builder
    assert "validate_standard_custom_mesh_payload" in extractor
    assert 'with path.open("x"' in extractor


def test_mesh_payload_v02_dispatch_precedes_standard_loop_uv_guard() -> None:
    """Keep historical MeshPayload 0.2 loop UV evidence readable by its strict builder."""

    builder = (
        ROOT
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "builders"
        / "custom_mesh.py"
    ).read_text(encoding="utf-8")
    v02_dispatch = builder.index('if version == "0.2.0":')
    standard_guard = builder.index('if "loop_uvs" in payload:')
    assert v02_dispatch < standard_guard
