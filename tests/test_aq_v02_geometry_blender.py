"""Opt-in Blender 5 smoke for the isolated MeshPayload 0.2 compiler hook."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from codex_blender_modeler.structural_geometry.mesh_payload_compiler_v02 import (
    compile_mesh_payload_v02,
)
from codex_blender_modeler.structural_geometry.mesh_payload_io_v02 import file_sha256
from codex_blender_modeler.structural_geometry.mesh_payload_v02 import (
    MeshPayloadSourceHashV02,
    MeshPayloadV02,
    canonical_json_sha256,
    normalized_source_intent_sha256,
    source_hash_fingerprint,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AQ_V02_GEOMETRY_SMOKE") != "1",
    reason="set CBM_RUN_AQ_V02_GEOMETRY_SMOKE=1 for Blender smoke tests",
)


def _write_payload(
    job_root: Path,
    *,
    modifiers: bool = False,
    angle_smoothing: bool = False,
) -> Path:
    """Write one exact-source-bound cube exercising every v2 mesh-data channel."""

    if modifiers and angle_smoothing:
        raise ValueError("test fixture selects only one smoothing modifier mode")

    source_path = job_root / "evidence" / "structural_candidate.json"
    source_path.parent.mkdir(parents=True)
    source_path.write_text('{"candidate":"v03-fixture"}\n', encoding="utf-8")
    vertices = [
        [-1.0, -1.0, -1.0],
        [1.0, -1.0, -1.0],
        [1.0, 1.0, -1.0],
        [-1.0, 1.0, -1.0],
        [-1.0, -1.0, 1.0],
        [1.0, -1.0, 1.0],
        [1.0, 1.0, 1.0],
        [-1.0, 1.0, 1.0],
    ]
    faces = [
        [0, 3, 2, 1],
        [4, 5, 6, 7],
        [0, 1, 5, 4],
        [1, 2, 6, 5],
        [2, 3, 7, 6],
        [3, 0, 4, 7],
    ]
    face_uv = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    face_groups = [
        {"id": "body", "face_indices": [0, 1, 2]},
        {"id": "accent", "face_indices": [3, 4, 5]},
    ]
    weighted = {
        "enabled": modifiers,
        "keep_sharp": True,
        "weight_mode": "FACE_AREA_WITH_ANGLE",
        "disposition": "recreate_in_compiled_build" if modifiers else "reject",
    }
    subdivision = {
        "enabled": modifiers,
        "levels": 1 if modifiers else 0,
        "render_levels": 1 if modifiers else 0,
        "subdivision_type": "CATMULL_CLARK",
        "boundary_smoothing": "PRESERVE_CORNERS",
        "disposition": "recreate_in_compiled_build" if modifiers else "reject",
    }
    source_intent = {
        "face_groups": face_groups,
        "material_assignments": [
            {"face_group_id": "body", "material_id": "mat.body"},
            {"face_group_id": "accent", "material_id": "mat.accent"},
        ],
        "sharp_edges": [{"vertices": [0, 1]}, {"vertices": [4, 5]}],
        "uv_seams": [{"vertices": [0, 3]}],
        "edge_creases": [{"vertices": [0, 1], "weight": 0.5}],
        "bevel_weights": [{"vertices": [4, 5], "weight": 0.25}],
        "smoothing_policy": {
            "mode": (
                "weighted_normals"
                if modifiers
                else "smooth_by_angle"
                if angle_smoothing
                else "flat"
            ),
            "angle_degrees": 30.0 if angle_smoothing else None,
            "keep_explicit_sharp": True,
        },
        "topology_profile": "static_prop_closed",
        "weighted_normal_intent": weighted,
        "subdivision_intent": subdivision,
    }
    source = MeshPayloadSourceHashV02(
        role="structural_candidate",
        path="evidence/structural_candidate.json",
        sha256=file_sha256(source_path),
    )
    values = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    policy = []
    if modifiers:
        policy = [
            {
                "effect": "weighted_normal",
                "disposition": "recreate_in_compiled_build",
                "source_id": "intent.smoothing",
                "details_sha256": canonical_json_sha256(weighted),
            },
            {
                "effect": "subdivision",
                "disposition": "recreate_in_compiled_build",
                "source_id": "intent.subdivision",
                "details_sha256": canonical_json_sha256(subdivision),
            },
        ]
    raw = {
        "schema_version": "0.2.0",
        "semantic_id": "asset.cube",
        "builder_kind": "fixture",
        "vertices": vertices,
        "faces": faces,
        "loop_count": 24,
        "loop_uvs": face_uv * 6,
        "material_slots": [
            {"slot_index": 0, "material_id": "mat.body"},
            {"slot_index": 1, "material_id": "mat.accent"},
        ],
        "polygon_material_indices": [0, 0, 0, 1, 1, 1],
        "sharp_edges": source_intent["sharp_edges"],
        "uv_seams": source_intent["uv_seams"],
        "edge_creases": source_intent["edge_creases"],
        "bevel_weights": source_intent["bevel_weights"],
        "face_groups": face_groups,
        "smooth_polygon_flags": [modifiers or angle_smoothing] * 6,
        "smoothing_policy": source_intent["smoothing_policy"],
        "custom_attribute_manifest": [
            {
                "name": "wear_mask",
                "domain": "FACE",
                "data_type": "FLOAT",
                "value_count": 6,
                "values": values,
                "values_sha256": canonical_json_sha256(values),
            },
            {
                "name": "variant_id",
                "domain": "OBJECT",
                "data_type": "INT",
                "value_count": 1,
                "values": [7],
                "values_sha256": canonical_json_sha256([7]),
            },
        ],
        "modifier_materialization_policy": policy,
        "weighted_normal_intent": weighted,
        "subdivision_intent": subdivision,
        "source_geometry_intent": {
            "source_intent_sha256": normalized_source_intent_sha256(source_intent),
            **source_intent,
        },
        "findings": [],
        "source_hashes": [source.model_dump(mode="json")],
        "source_fingerprint_sha256": source_hash_fingerprint([source]),
    }
    payload = MeshPayloadV02.model_validate_json(json.dumps(raw))
    path = job_root / "candidate" / "mesh_payload_v02.json"
    path.parent.mkdir(parents=True)
    path.write_text(payload.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def test_mesh_payload_v02_compiles_all_data_channels_in_blender(tmp_path: Path) -> None:
    """Compile UV, material, smoothing, edge intent, and custom attributes in Blender 5."""

    _write_payload(tmp_path)
    report = compile_mesh_payload_v02(
        job_root=tmp_path,
        payload_relative_path="candidate/mesh_payload_v02.json",
        output_blend_relative_path="compiled/candidate.blend",
        report_relative_path="compiled/compile_report.json",
    )
    snapshot = report.snapshot
    assert snapshot.vertex_count == 8
    assert snapshot.face_count == 6
    assert snapshot.loop_count == 24
    assert snapshot.uv_fingerprint.status == "available"
    assert snapshot.polygon_material_fingerprint.status == "available"
    assert snapshot.sharp_edge_fingerprint.status == "available"
    assert snapshot.uv_seam_fingerprint.status == "available"
    assert snapshot.crease_fingerprint.status == "available"
    assert snapshot.bevel_fingerprint.status == "available"
    assert snapshot.custom_attribute_fingerprint.status == "available"


def test_mesh_payload_v02_recreates_bounded_modifiers_in_blender(tmp_path: Path) -> None:
    """Compile one idempotently named weighted-normal and subdivision intent stack."""

    _write_payload(tmp_path, modifiers=True)
    report = compile_mesh_payload_v02(
        job_root=tmp_path,
        payload_relative_path="candidate/mesh_payload_v02.json",
        output_blend_relative_path="compiled/candidate.blend",
        report_relative_path="compiled/compile_report.json",
    )
    assert report.snapshot.modifier_fingerprint.status == "available"


def test_mesh_payload_v02_keeps_explicit_and_angle_sharp_edges(tmp_path: Path) -> None:
    """Apply angle-derived sharp edges without erasing explicit source declarations."""

    _write_payload(tmp_path, angle_smoothing=True)
    report = compile_mesh_payload_v02(
        job_root=tmp_path,
        payload_relative_path="candidate/mesh_payload_v02.json",
        output_blend_relative_path="compiled/candidate.blend",
        report_relative_path="compiled/compile_report.json",
    )
    sharp = report.snapshot.sharp_edge_fingerprint
    assert sharp.status == "available"
    assert sharp.sha256 == canonical_json_sha256(
        sorted(
            [
                (0, 1),
                (0, 3),
                (0, 4),
                (1, 2),
                (1, 5),
                (2, 3),
                (2, 6),
                (3, 7),
                (4, 5),
                (4, 7),
                (5, 6),
                (6, 7),
            ]
        )
    )
