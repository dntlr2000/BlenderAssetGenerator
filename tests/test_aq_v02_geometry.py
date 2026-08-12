"""Focused host contracts for the opt-in AQ v2 geometry vertical slice."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from codex_blender_modeler.structural_geometry.geometry_intent_runtime_v02 import (
    classify_geometry_intent_v02,
)
from codex_blender_modeler.structural_geometry.geometry_survival_v02 import (
    GeometryEvidenceFingerprintV02,
    GeometryIntentSurvivalReportV02,
    GeometryStageSnapshotV02,
    compare_geometry_stage_snapshots_v02,
    validate_geometry_survival_chain_v02,
    verify_geometry_stage_snapshot_artifact_v02,
)
from codex_blender_modeler.structural_geometry.mesh_payload_compiler_v02 import (
    MeshPayloadV02CompileReport,
)
from codex_blender_modeler.structural_geometry.mesh_payload_io_v02 import (
    LegacyVertexUvMeshPayload,
    file_sha256,
    load_compatible_mesh_payload,
    verify_mesh_payload_v02_source_hashes,
)
from codex_blender_modeler.structural_geometry.mesh_payload_migration_v02 import (
    MeshPayloadV02MigrationPlan,
    MeshPayloadV02MigrationReceipt,
    apply_mesh_payload_v02_migration,
    plan_mesh_payload_v02_migration,
)
from codex_blender_modeler.structural_geometry.mesh_payload_v02 import (
    MeshPayloadSourceHashV02,
    MeshPayloadV02,
    canonical_json_sha256,
    normalized_source_intent_sha256,
    source_hash_fingerprint,
)
from codex_blender_modeler.structural_geometry.models import (
    GeometryIntent,
    StructuralMeshPayload,
)
from codex_blender_modeler.structural_geometry.v02 import (
    MESH_PAYLOAD_V02_VERSION,
    compile_mesh_payload_v02,
)


def _cube_geometry() -> tuple[list[list[float]], list[list[int]], list[list[float]]]:
    """Return one closed cube and a deterministic per-face loop UV layout."""

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
    return vertices, faces, face_uv * len(faces)


def _write_source(job_root: Path, relative_path: str, payload: object) -> Path:
    """Write one immutable-like test input and return its exact path."""

    path = job_root / Path(*relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _payload_dict(
    job_root: Path,
    *,
    source_relative_path: str = "evidence/source.json",
    builder_kind: str = "fixture",
) -> dict:
    """Construct one fully bound two-material MeshPayload 0.2 cube fixture."""

    source_path = job_root / Path(*source_relative_path.split("/"))
    if not source_path.is_file():
        _write_source(job_root, source_relative_path, {"source": "fixture"})
    vertices, faces, loop_uvs = _cube_geometry()
    face_groups = [
        {"id": "body", "face_indices": [0, 1, 2]},
        {"id": "accent", "face_indices": [3, 4, 5]},
    ]
    weighted = {
        "enabled": False,
        "keep_sharp": True,
        "weight_mode": "FACE_AREA_WITH_ANGLE",
        "disposition": "reject",
    }
    subdivision = {
        "enabled": False,
        "levels": 0,
        "render_levels": 0,
        "subdivision_type": "CATMULL_CLARK",
        "boundary_smoothing": "PRESERVE_CORNERS",
        "disposition": "reject",
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
            "mode": "flat",
            "angle_degrees": None,
            "keep_explicit_sharp": True,
        },
        "topology_profile": "static_prop_closed",
        "weighted_normal_intent": weighted,
        "subdivision_intent": subdivision,
    }
    source_entry = {
        "role": "source_mesh_payload" if builder_kind == "loft" else "structural_candidate",
        "path": source_relative_path,
        "sha256": file_sha256(source_path),
    }
    custom_values = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    return {
        "schema_version": "0.2.0",
        "semantic_id": "asset.cube",
        "builder_kind": builder_kind,
        "vertices": vertices,
        "faces": faces,
        "loop_count": 24,
        "loop_uvs": loop_uvs,
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
        "smooth_polygon_flags": [False] * 6,
        "smoothing_policy": source_intent["smoothing_policy"],
        "custom_attribute_manifest": [
            {
                "name": "wear_mask",
                "domain": "FACE",
                "data_type": "FLOAT",
                "value_count": 6,
                "values": custom_values,
                "values_sha256": canonical_json_sha256(custom_values),
            }
        ],
        "modifier_materialization_policy": [],
        "weighted_normal_intent": weighted,
        "subdivision_intent": subdivision,
        "source_geometry_intent": {
            "source_intent_sha256": normalized_source_intent_sha256(source_intent),
            **source_intent,
        },
        "findings": [],
        "source_hashes": [source_entry],
        "source_fingerprint_sha256": source_hash_fingerprint(
            [MeshPayloadSourceHashV02.model_validate(source_entry)]
        ),
    }


def _available(seed: str) -> GeometryEvidenceFingerprintV02:
    """Return one available deterministic fingerprint for survival fixtures."""

    return GeometryEvidenceFingerprintV02(
        status="available",
        sha256=canonical_json_sha256(seed),
        reason=None,
    )


def _validate_payload(raw: dict) -> MeshPayloadV02:
    """Validate a JSON-shaped payload through the strict JSON contract path."""

    return MeshPayloadV02.model_validate_json(json.dumps(raw))


def _snapshot(stage: str, *, material_seed: str = "same") -> GeometryStageSnapshotV02:
    """Return one fully evidenced stage snapshot with stable surface channels."""

    shared = _available("shared")
    return GeometryStageSnapshotV02.model_validate(
        {
            "schema_version": "0.1.0",
            "stage": stage,
            "artifact_path": f"evidence/{stage}.blend",
            "artifact_sha256": canonical_json_sha256(stage),
            "source_fingerprint_sha256": canonical_json_sha256("source"),
            "build_fingerprint_sha256": canonical_json_sha256("build"),
            "semantic_id": "asset.cube",
            "topology_profile": "static_prop_closed",
            "vertex_count": 8,
            "face_count": 6,
            "loop_count": 24,
            "evaluated_triangle_count": 12,
            "topology_fingerprint": shared,
            "surface_equivalence_fingerprint": shared,
            "uv_fingerprint": shared,
            "material_slots_fingerprint": _available(material_seed),
            "polygon_material_fingerprint": _available(material_seed),
            "split_normal_fingerprint": shared,
            "sharp_edge_fingerprint": shared,
            "uv_seam_fingerprint": shared,
            "crease_fingerprint": shared,
            "bevel_fingerprint": shared,
            "smoothing_fingerprint": shared,
            "modifier_fingerprint": shared,
            "custom_attribute_fingerprint": shared,
        }
    )


def test_mesh_payload_v02_preserves_all_strict_channels(tmp_path: Path) -> None:
    """Accept a closed, hash-bound, per-loop UV and multi-material payload."""

    payload = _validate_payload(_payload_dict(tmp_path))
    payload.assert_compilable()
    verify_mesh_payload_v02_source_hashes(payload, job_root=tmp_path)
    assert payload.loop_count == 24
    assert [slot.material_id for slot in payload.material_slots] == [
        "mat.body",
        "mat.accent",
    ]
    assert MESH_PAYLOAD_V02_VERSION == "0.2.0"
    assert callable(compile_mesh_payload_v02)


def test_mesh_payload_v02_rejects_unknown_nonfinite_and_bad_source_map(
    tmp_path: Path,
) -> None:
    """Enforce strict unknown-field, finite-number, and source-fingerprint rules."""

    unknown = _payload_dict(tmp_path)
    unknown["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _validate_payload(unknown)
    nonfinite = _payload_dict(tmp_path)
    nonfinite["vertices"][0][0] = float("inf")
    with pytest.raises(ValidationError, match="finite number"):
        _validate_payload(nonfinite)
    stale_map = _payload_dict(tmp_path)
    stale_map["source_fingerprint_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="does not match source_hashes"):
        _validate_payload(stale_map)


def test_mesh_payload_v02_error_finding_is_not_compilable(tmp_path: Path) -> None:
    """Represent diagnostic failure evidence but refuse to send it to Blender."""

    raw = _payload_dict(tmp_path)
    raw["findings"] = [
        {"code": "nonmanifold", "severity": "error", "message": "blocked fixture"}
    ]
    payload = _validate_payload(raw)
    with pytest.raises(ValueError, match="blocking findings"):
        payload.assert_compilable()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["loop_uvs"].pop(), "loop_count and loop_uvs"),
        (
            lambda value: value.__setitem__(
                "sharp_edges",
                [*value["sharp_edges"], {"vertices": [0, 6]}],
            ),
            "missing mesh edges",
        ),
        (
            lambda value: value["polygon_material_indices"].__setitem__(3, 0),
            "differs from source assignment",
        ),
        (
            lambda value: value["modifier_materialization_policy"].extend(
                [
                    {
                        "effect": "bevel",
                        "disposition": "bake_into_mesh",
                        "source_id": "one",
                        "details_sha256": "a" * 64,
                    },
                    {
                        "effect": "bevel",
                        "disposition": "recreate_in_compiled_build",
                        "source_id": "two",
                        "details_sha256": "b" * 64,
                    },
                ]
            ),
            "repeats one effect",
        ),
    ],
)
def test_mesh_payload_v02_fails_closed_on_contract_conflicts(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    """Reject malformed loops, topology references, materials, and duplicate effects."""

    raw = _payload_dict(tmp_path)
    mutate(raw)
    with pytest.raises(ValidationError, match=message):
        _validate_payload(raw)


def test_mesh_payload_v02_rejects_degenerate_and_nonmanifold_faces(tmp_path: Path) -> None:
    """Reject zero-area and over-shared edges before Blender compilation."""

    degenerate = _payload_dict(tmp_path)
    degenerate["faces"][0] = [0, 1, 2, 3]
    degenerate["vertices"][2] = [2.0, -1.0, -1.0]
    degenerate["vertices"][3] = [3.0, -1.0, -1.0]
    with pytest.raises(ValidationError, match="zero geometric area"):
        _validate_payload(degenerate)

    nonmanifold = _payload_dict(tmp_path)
    nonmanifold["faces"].append([0, 1, 6])
    nonmanifold["loop_count"] += 3
    nonmanifold["loop_uvs"].extend([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]])
    nonmanifold["polygon_material_indices"].append(0)
    nonmanifold["smooth_polygon_flags"].append(False)
    with pytest.raises(ValidationError, match="non-manifold"):
        _validate_payload(nonmanifold)


def test_version_dispatch_preserves_legacy_payloads() -> None:
    """Continue reading existing 0.1 and unversioned vertex-UV dialects."""

    vertices, faces, loop_uvs = _cube_geometry()
    legacy = load_compatible_mesh_payload(
        {
            "vertices": vertices,
            "faces": faces,
            "vertex_uvs": [[0.0, 0.0]] * len(vertices),
        }
    )
    assert isinstance(legacy, LegacyVertexUvMeshPayload)
    v01 = load_compatible_mesh_payload(
        {
            "schema_version": "0.1.0",
            "semantic_id": "asset.cube",
            "builder_kind": "loft",
            "vertices": vertices,
            "faces": faces,
            "loop_uvs": [loop_uvs[index : index + 4] for index in range(0, 24, 4)],
            "geometry_intent": None,
            "findings": [],
        }
    )
    assert isinstance(v01, StructuralMeshPayload)


def test_source_hash_verification_detects_stale_input(tmp_path: Path) -> None:
    """Detect external source mutation even when the payload file itself is unchanged."""

    payload = _validate_payload(_payload_dict(tmp_path))
    (tmp_path / "evidence" / "source.json").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash is stale"):
        verify_mesh_payload_v02_source_hashes(payload, job_root=tmp_path)


def test_explicit_mesh_payload_migration_requires_exact_plan_hash(tmp_path: Path) -> None:
    """Publish only a derived v2 copy after exact plan and source revalidation."""

    vertices, faces, loop_uvs = _cube_geometry()
    source_relative = "evidence/source_v01.json"
    source = {
        "schema_version": "0.1.0",
        "semantic_id": "asset.cube",
        "builder_kind": "loft",
        "vertices": vertices,
        "faces": faces,
        "loop_uvs": [loop_uvs[index : index + 4] for index in range(0, 24, 4)],
        "geometry_intent": None,
        "findings": [],
    }
    _write_source(tmp_path, source_relative, source)
    candidate_relative = "candidate/payload_v02.json"
    candidate = _payload_dict(
        tmp_path,
        source_relative_path=source_relative,
        builder_kind="loft",
    )
    _write_source(tmp_path, candidate_relative, candidate)
    result = plan_mesh_payload_v02_migration(
        job_root=tmp_path,
        migration_id="migrate_payload_01",
        source_relative_path=source_relative,
        candidate_relative_path=candidate_relative,
    )
    with pytest.raises(ValueError, match="does not match"):
        apply_mesh_payload_v02_migration(
            job_root=tmp_path,
            migration_id="migrate_payload_01",
            exact_plan_sha256="0" * 64,
        )
    applied = apply_mesh_payload_v02_migration(
        job_root=tmp_path,
        migration_id="migrate_payload_01",
        exact_plan_sha256=str(result["plan_file_sha256"]),
    )
    assert applied["canonical_mutated"] is False
    assert (tmp_path / str(applied["derived_payload_path"])).is_file()
    assert (tmp_path / source_relative).read_text(encoding="utf-8") == (
        json.dumps(source, indent=2) + "\n"
    )


def test_geometry_intent_classification_separates_recreate_and_bake() -> None:
    """Classify non-destructive modifiers and evaluated Boolean topology once."""

    intent = GeometryIntent.model_validate(
        {
            "smoothing_policy": {"mode": "weighted_normals", "keep_sharp": True},
            "subdivision_intent": {
                "enabled": True,
                "levels": 2,
                "boundary_smoothing": "preserve_corners",
            },
        }
    )
    source, policy = classify_geometry_intent_v02(
        intent,
        builder_kind="boolean_tree",
    )
    assert source.weighted_normal_intent.enabled is True
    assert {item.effect: item.disposition for item in policy} == {
        "boolean": "bake_into_mesh",
        "weighted_normal": "recreate_in_compiled_build",
        "subdivision": "recreate_in_compiled_build",
    }
    with pytest.raises(ValueError, match="duplicated"):
        classify_geometry_intent_v02(
            intent,
            builder_kind="boolean_tree",
            legacy_modifier_kinds=["subdivision"],
        )
    _source, rejected = classify_geometry_intent_v02(
        GeometryIntent.model_validate({"smoothing_policy": {"mode": "flat"}}),
        builder_kind="fixture",
        legacy_modifier_kinds=["future_modifier"],
    )
    assert rejected[0].effect == "unsupported"
    assert rejected[0].disposition == "reject"


def test_geometry_survival_reports_exact_chain_and_material_failure() -> None:
    """Bind candidate-to-optimized continuity and fail closed on material drift."""

    materialized = _snapshot("structural_materialization")
    compiled = _snapshot("compiled_candidate")
    canonical = _snapshot("promoted_canonical")
    optimized = _snapshot("optimized_lod0")
    reports = [
        compare_geometry_stage_snapshots_v02(
            report_id="survival.materialized.candidate",
            relation="materialization_to_candidate",
            source=materialized,
            target=compiled,
        ),
        compare_geometry_stage_snapshots_v02(
            report_id="survival.candidate.canonical",
            relation="candidate_to_canonical",
            source=compiled,
            target=canonical,
        ),
        compare_geometry_stage_snapshots_v02(
            report_id="survival.canonical.optimized",
            relation="canonical_to_optimized_lod0",
            source=canonical,
            target=optimized,
        ),
    ]
    assert validate_geometry_survival_chain_v02(reports) == "exact"
    changed = _snapshot("compiled_candidate", material_seed="changed")
    failed = compare_geometry_stage_snapshots_v02(
        report_id="survival.material.failure",
        relation="materialization_to_candidate",
        source=materialized,
        target=changed,
    )
    assert failed.overall_status == "failed"


def test_geometry_stage_snapshot_rehash_detects_tampering(tmp_path: Path) -> None:
    """Require exact contained stage bytes before a survival report trusts a snapshot."""

    artifact = tmp_path / "evidence" / "compiled.blend"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"compiled-evidence")
    raw = _snapshot("compiled_candidate").model_dump(mode="json")
    raw["artifact_path"] = "evidence/compiled.blend"
    raw["artifact_sha256"] = file_sha256(artifact)
    snapshot = GeometryStageSnapshotV02.model_validate(raw)
    verify_geometry_stage_snapshot_artifact_v02(snapshot, job_root=tmp_path)
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash is stale"):
        verify_geometry_stage_snapshot_artifact_v02(snapshot, job_root=tmp_path)


@pytest.mark.parametrize(
    ("package_format", "target_stage"),
    [("GLB", "clean_import_glb"), ("FBX", "clean_import_fbx")],
)
def test_clean_import_allows_metadata_loss_but_requires_surface_channels(
    package_format: str,
    target_stage: str,
) -> None:
    """Classify format metadata loss separately from UV/normal/surface equivalence."""

    source = _snapshot("optimized_lod0")
    target_raw = _snapshot(target_stage).model_dump(mode="json")
    unavailable = {
        "status": "unavailable",
        "sha256": None,
        "reason": "GLB importer does not expose authoring metadata",
    }
    for field in (
        "sharp_edge_fingerprint",
        "uv_seam_fingerprint",
        "crease_fingerprint",
        "bevel_fingerprint",
        "smoothing_fingerprint",
        "modifier_fingerprint",
        "custom_attribute_fingerprint",
    ):
        target_raw[field] = unavailable
    target = GeometryStageSnapshotV02.model_validate(target_raw)
    report = compare_geometry_stage_snapshots_v02(
        report_id=f"survival.clean.{package_format.lower()}",
        relation="optimized_to_clean_import",
        source=source,
        target=target,
        package_format=package_format,
    )
    assert report.overall_status == "known_loss"
    assert report.known_losses


@pytest.mark.parametrize(
    ("package_format", "target_stage"),
    [("GLB", "clean_import_glb"), ("FBX", "clean_import_fbx")],
)
def test_clean_import_rejects_split_normal_drift(
    package_format: str,
    target_stage: str,
) -> None:
    """Reject visible normal drift even when clean-import metadata loss is allowed."""

    source = _snapshot("optimized_lod0")
    target_raw = _snapshot(target_stage).model_dump(mode="json")
    target_raw["split_normal_fingerprint"] = {
        "status": "available",
        "sha256": canonical_json_sha256("gross-normal-drift"),
        "reason": None,
    }
    target = GeometryStageSnapshotV02.model_validate(target_raw)
    report = compare_geometry_stage_snapshots_v02(
        report_id=f"survival.clean.{package_format.lower()}.normal-drift",
        relation="optimized_to_clean_import",
        source=source,
        target=target,
        package_format=package_format,
    )
    split_normals = next(
        item for item in report.checks if item.check_id == "split_normals"
    )
    assert split_normals.status == "failed"
    assert report.overall_status == "failed"


def test_delivery_normal_quantizer_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absorb serializer noise while preserving visible drift and flipped normals."""

    monkeypatch.setitem(sys.modules, "bpy", types.ModuleType("bpy"))
    script_path = (
        Path("src")
        / "codex_blender_modeler"
        / "blender_scripts"
        / "inspect_geometry_delivery_v02.py"
    ).resolve()
    spec = importlib.util.spec_from_file_location(
        "test_inspect_geometry_delivery_v02",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    baseline = module._normal_vector((0.3, -0.4, 0.8660254))
    serializer_noise = module._normal_vector((0.3002, -0.4002, 0.8662254))
    visible_drift = module._normal_vector((0.302, -0.4, 0.8653))
    flipped = module._normal_vector((-0.3, 0.4, -0.8660254))
    assert serializer_noise == baseline
    assert visible_drift != baseline
    assert flipped != baseline


@pytest.mark.parametrize(
    ("schema_name", "model"),
    [
        ("mesh_payload_v02.schema.json", MeshPayloadV02),
        ("mesh_payload_v02_migration_plan.schema.json", MeshPayloadV02MigrationPlan),
        (
            "mesh_payload_v02_migration_receipt.schema.json",
            MeshPayloadV02MigrationReceipt,
        ),
        ("geometry_stage_snapshot_v02.schema.json", GeometryStageSnapshotV02),
        (
            "geometry_intent_survival_report.schema.json",
            GeometryIntentSurvivalReportV02,
        ),
        ("mesh_payload_v02_compile_report.schema.json", MeshPayloadV02CompileReport),
    ],
)
def test_aq_v02_geometry_schema_parity(schema_name: str, model) -> None:
    """Keep each checked-in v2 geometry schema byte-semantically equal to Pydantic."""

    checked_in = json.loads((Path("schemas") / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(checked_in)
    assert checked_in == model.model_json_schema()
