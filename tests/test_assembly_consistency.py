from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from codex_blender_modeler.analysis.assembly import (
    AssemblyBounds,
    evaluate_assembly_bounds,
    validate_assembly_prebuild_contract,
    validate_job_assembly,
)
from codex_blender_modeler.analysis.models import AssemblyValidationReport, ModelingPlan
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.validation import load_scene_spec


def _scene(object_ids: list[str] | None = None) -> SceneSpec:
    """Create one compact SceneSpec for assembly-contract unit tests."""

    ids = object_ids or [
        "asset.root",
        "asset.trigger",
        "asset.barrel",
        "asset.guard",
        "asset.sight",
        "asset.control",
        "asset.left",
        "asset.right",
    ]
    return SceneSpec.model_validate(
        {
            "job_id": "assembly_test",
            "mode": "concept",
            "nominal_scene_size": [10.0, 2.0, 2.0],
            "sources": [
                {
                    "id": "reference",
                    "path": "input/reference.png",
                    "kind": "reference",
                }
            ],
            "materials": [
                {
                    "id": "mat.test",
                    "name": "Test",
                    "base_color": [0.5, 0.5, 0.5, 1.0],
                    "roughness": 0.5,
                    "metallic": 0.0,
                }
            ],
            "objects": [
                {
                    "id": object_id,
                    "name": object_id,
                    "geometry": {
                        "kind": "primitive",
                        "primitive": "cube",
                        "dimensions": [1.0, 1.0, 1.0],
                    },
                    "material_id": "mat.test",
                }
                for object_id in ids
            ],
            "camera": {
                "projection": "PERSP",
                "location": [5.0, -8.0, 5.0],
                "target": [0.0, 0.0, 0.0],
                "focal_length_mm": 50.0,
                "ortho_scale": 10.0,
                "resolution": [320, 240],
            },
        }
    )


def _spatial_plan() -> ModelingPlan:
    """Create one generic manufactured-asset assembly contract covering every relation kind."""

    object_ids = [
        "asset.root",
        "asset.trigger",
        "asset.barrel",
        "asset.guard",
        "asset.sight",
        "asset.control",
        "asset.left",
        "asset.right",
    ]
    objects = [
        {
            "id": object_id,
            "label": object_id,
            "source_ids": ["reference"],
            "assembly_role": "root" if object_id == "asset.root" else "attached",
        }
        for object_id in object_ids
    ]
    return ModelingPlan.model_validate(
        {
            "job_id": "assembly_test",
            "reference_analysis_path": "analysis/reference_analysis.json",
            "camera_solution_path": "analysis/camera_solution.json",
            "stage": "authored",
            "objects": objects,
            "assembly_consistency_policy": "spatial_v1",
            "assembly_frame": {
                "root_object_id": "asset.root",
                "longitudinal_axis": "X",
                "lateral_axis": "Y",
                "vertical_axis": "Z",
                "symmetry": "bilateral",
                "evidence_status": "inferred",
            },
            "assembly_relationships": [
                {
                    "id": "center.trigger",
                    "kind": "center_plane",
                    "subject_id": "asset.trigger",
                    "reference_id": "asset.root",
                    "axis": "Y",
                },
                {
                    "id": "axis.barrel",
                    "kind": "coaxial",
                    "subject_id": "asset.barrel",
                    "reference_id": "asset.root",
                    "axes": ["Y", "Z"],
                },
                {
                    "id": "contain.guard",
                    "kind": "bbox_containment",
                    "subject_id": "asset.guard",
                    "reference_id": "asset.root",
                    "axes": ["X", "Y", "Z"],
                },
                {
                    "id": "contact.sight",
                    "kind": "surface_contact",
                    "subject_id": "asset.sight",
                    "reference_id": "asset.root",
                    "axis": "Z",
                    "subject_side": "MIN",
                    "reference_side": "MAX",
                },
                {
                    "id": "side.control",
                    "kind": "side_specific",
                    "subject_id": "asset.control",
                    "reference_id": "asset.root",
                    "axis": "Y",
                    "side": "MIN",
                    "evidence_status": "authored",
                    "tolerance": {"mode": "relative", "value": 0.1},
                },
                {
                    "id": "pair.left",
                    "kind": "bilateral_pair",
                    "subject_id": "asset.left",
                    "reference_id": "asset.root",
                    "peer_id": "asset.right",
                    "axis": "Y",
                },
                {
                    "id": "pair.right",
                    "kind": "bilateral_pair",
                    "subject_id": "asset.right",
                    "reference_id": "asset.root",
                    "peer_id": "asset.left",
                    "axis": "Y",
                },
            ],
        }
    )


def _bounds(*, side_trigger: bool = False) -> dict[str, list[AssemblyBounds]]:
    """Return assembly-frame bounds with an optional visible-side trigger error."""

    trigger_y = -0.8 if side_trigger else 0.0
    return {
        "asset.root": [AssemblyBounds(0, (-5.0, -1.0, -1.0), (5.0, 1.0, 1.0))],
        "asset.trigger": [
            AssemblyBounds(0, (-0.5, trigger_y - 0.1, -0.8), (0.5, trigger_y + 0.1, -0.2))
        ],
        "asset.barrel": [AssemblyBounds(0, (4.0, -0.2, -0.2), (6.0, 0.2, 0.2))],
        "asset.guard": [AssemblyBounds(0, (-1.0, -0.2, -0.9), (1.0, 0.2, 0.1))],
        "asset.sight": [AssemblyBounds(0, (-1.0, -0.2, 1.0), (0.0, 0.2, 1.4))],
        "asset.control": [AssemblyBounds(0, (0.0, -0.9, 0.0), (0.4, -0.7, 0.4))],
        "asset.left": [AssemblyBounds(0, (-1.0, -0.8, 0.0), (0.0, -0.6, 0.4))],
        "asset.right": [AssemblyBounds(0, (-1.0, 0.6, 0.0), (0.0, 0.8, 0.4))],
    }


def _orientation_and_clearance_plan() -> ModelingPlan:
    """Add explicit trigger position, full orientation, and broad clearance duties."""

    payload = _spatial_plan().model_dump(mode="json")
    trigger = next(item for item in payload["objects"] if item["id"] == "asset.trigger")
    trigger["required_assembly_checks"] = [
        "position",
        "axis",
        "orientation",
        "clearance",
    ]
    payload["assembly_relationships"].extend(
        [
            {
                "id": "orientation.trigger.x",
                "kind": "axis_alignment",
                "subject_id": "asset.trigger",
                "reference_id": "asset.root",
                "subject_axis": "+X",
                "target_direction": [1.0, 0.0, 0.0],
                "target_space": "assembly_frame",
                "angular_tolerance_deg": 5.0,
            },
            {
                "id": "orientation.trigger.z",
                "kind": "axis_alignment",
                "subject_id": "asset.trigger",
                "reference_id": "asset.root",
                "subject_axis": "+Z",
                "target_direction": [0.0, 0.0, 1.0],
                "target_space": "assembly_frame",
                "angular_tolerance_deg": 5.0,
            },
            {
                "id": "clearance.trigger.guard",
                "kind": "axis_clearance",
                "subject_id": "asset.trigger",
                "reference_id": "asset.guard",
                "axis": "X",
                "direction": "POSITIVE",
                "minimum_gap": {"mode": "meters", "value": 0.25},
                "maximum_gap": {"mode": "meters", "value": 0.75},
                "tolerance": {"mode": "meters", "value": 0.01},
            },
        ]
    )
    return ModelingPlan.model_validate(payload)


def test_legacy_modeling_plan_remains_unbound_and_loadable() -> None:
    """Legacy authored plans preserve their old defaults without spatial assertions."""

    plan = ModelingPlan.model_validate(
        {
            "job_id": "legacy_asset",
            "reference_analysis_path": "analysis/reference_analysis.json",
            "camera_solution_path": "analysis/camera_solution.json",
            "stage": "authored",
            "objects": [{"id": "asset.body", "label": "Body"}],
        }
    )
    assert plan.assembly_consistency_policy == "legacy_unbound"
    assert plan.objects[0].assembly_role == "unclassified"
    assert plan.objects[0].required_assembly_checks == []
    assert plan.assembly_frame is None
    assert plan.assembly_relationships == []

    payload = plan.model_dump(mode="json")
    payload["objects"][0]["required_assembly_checks"] = ["orientation"]
    with pytest.raises(ValidationError, match="legacy_unbound"):
        ModelingPlan.model_validate(payload)


def test_assembly_schemas_match_strict_host_contracts() -> None:
    """Keep generated ModelingPlan and assembly-report schemas current and valid."""

    root = Path(__file__).resolve().parents[1]
    contracts = {
        "modeling_plan.schema.json": ModelingPlan,
        "assembly_validation.schema.json": AssemblyValidationReport,
    }
    for filename, model in contracts.items():
        schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema == model.model_json_schema()


def test_spatial_plan_rejects_unclassified_or_unrelated_attached_objects() -> None:
    """Spatial authored plans fail closed when assembly classification is incomplete."""

    payload = _spatial_plan().model_dump(mode="json")
    payload["objects"][1]["assembly_role"] = "unclassified"
    with pytest.raises(ValidationError, match="assembly_role classification"):
        ModelingPlan.model_validate(payload)

    payload = _spatial_plan().model_dump(mode="json")
    payload["assembly_relationships"] = [
        item
        for item in payload["assembly_relationships"]
        if item["subject_id"] != "asset.trigger"
    ]
    with pytest.raises(ValidationError, match="subject relationship"):
        ModelingPlan.model_validate(payload)


def test_side_specific_requires_non_inferred_evidence() -> None:
    """A one-sided placement cannot be authorized by an inferred-only relationship."""

    payload = _spatial_plan().model_dump(mode="json")
    side = next(
        item for item in payload["assembly_relationships"] if item["kind"] == "side_specific"
    )
    side["evidence_status"] = "inferred"
    with pytest.raises(ValidationError, match="side_specific"):
        ModelingPlan.model_validate(payload)


def test_required_orientation_and_clearance_checks_are_explicit_and_complete() -> None:
    """Critical attached parts need two orientation axes and one clearance relation."""

    plan = _orientation_and_clearance_plan()
    trigger = next(item for item in plan.objects if item.id == "asset.trigger")
    assert trigger.required_assembly_checks == [
        "position",
        "axis",
        "orientation",
        "clearance",
    ]

    payload = plan.model_dump(mode="json")
    payload["assembly_relationships"] = [
        item
        for item in payload["assembly_relationships"]
        if item["id"] != "orientation.trigger.z"
    ]
    with pytest.raises(ValidationError, match="asset.trigger:orientation"):
        ModelingPlan.model_validate(payload)

    payload = plan.model_dump(mode="json")
    alignment = next(
        item
        for item in payload["assembly_relationships"]
        if item["id"] == "orientation.trigger.x"
    )
    alignment["target_direction"] = [0.0, 0.0, 0.0]
    with pytest.raises(ValidationError, match="target_direction must be nonzero"):
        ModelingPlan.model_validate(payload)

    payload = plan.model_dump(mode="json")
    clearance = next(
        item
        for item in payload["assembly_relationships"]
        if item["id"] == "clearance.trigger.guard"
    )
    clearance["maximum_gap"]["value"] = 0.1
    with pytest.raises(ValidationError, match="maximum_gap"):
        ModelingPlan.model_validate(payload)


def test_required_orientation_rejects_collinear_or_incomparable_axes() -> None:
    """Two labels do not prove orientation unless directed targets share one frame."""

    payload = _orientation_and_clearance_plan().model_dump(mode="json")
    second = next(
        item
        for item in payload["assembly_relationships"]
        if item["id"] == "orientation.trigger.z"
    )
    second["target_direction"] = [2.0, 0.0, 0.0]
    with pytest.raises(ValidationError, match="asset.trigger:orientation"):
        ModelingPlan.model_validate(payload)

    payload = _orientation_and_clearance_plan().model_dump(mode="json")
    second = next(
        item
        for item in payload["assembly_relationships"]
        if item["id"] == "orientation.trigger.z"
    )
    second["target_direction"] = [0.9961947, 0.0871557, 0.0]
    with pytest.raises(ValidationError, match="asset.trigger:orientation"):
        ModelingPlan.model_validate(payload)

    payload = _orientation_and_clearance_plan().model_dump(mode="json")
    second = next(
        item
        for item in payload["assembly_relationships"]
        if item["id"] == "orientation.trigger.z"
    )
    second["target_direction"] = [0.3420201, 0.0, 0.9396926]
    for item in payload["assembly_relationships"]:
        if item["id"] in {"orientation.trigger.x", "orientation.trigger.z"}:
            item["angular_tolerance_deg"] = 10.0
    assert ModelingPlan.model_validate(payload)

    payload = _orientation_and_clearance_plan().model_dump(mode="json")
    alignments = [
        item
        for item in payload["assembly_relationships"]
        if item["id"] in {"orientation.trigger.x", "orientation.trigger.z"}
    ]
    alignments[0]["target_space"] = "reference_local"
    alignments[0]["reference_id"] = "asset.root"
    alignments[1]["target_space"] = "reference_local"
    alignments[1]["reference_id"] = "asset.guard"
    with pytest.raises(ValidationError, match="asset.trigger:orientation"):
        ModelingPlan.model_validate(payload)

    payload = _orientation_and_clearance_plan().model_dump(mode="json")
    for item in payload["assembly_relationships"]:
        if item["id"] in {"orientation.trigger.x", "orientation.trigger.z"}:
            item["directionality"] = "undirected"
    with pytest.raises(ValidationError, match="asset.trigger:orientation"):
        ModelingPlan.model_validate(payload)


def test_axis_alignment_and_clearance_use_evaluated_3d_evidence() -> None:
    """Detect a rotated or intersecting trigger even when its lateral center is valid."""

    plan = _orientation_and_clearance_plan()
    bounds = _bounds()
    identity = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    bounds["asset.root"][0] = AssemblyBounds(
        0,
        (-5.0, -1.0, -1.0),
        (5.0, 1.0, 1.0),
        identity,
    )
    bounds["asset.trigger"][0] = AssemblyBounds(
        0,
        (-2.0, -0.1, -0.8),
        (-1.5, 0.1, -0.2),
        identity,
    )
    passed = evaluate_assembly_bounds(plan, _scene(), bounds)
    assert passed.ok is True
    alignment = next(
        item
        for item in passed.checks
        if item.relation_id == "orientation.trigger.x"
        and item.id.startswith("assembly.bounds")
    )
    clearance = next(
        item
        for item in passed.checks
        if item.relation_id == "clearance.trigger.guard"
        and item.id.startswith("assembly.bounds")
    )
    assert alignment.tolerance_mode == "degrees"
    assert alignment.residual == pytest.approx(0.0)
    assert clearance.residual == pytest.approx(0.0)
    assert clearance.metrics["evaluated_gap"] == pytest.approx(0.5)

    bounds["asset.trigger"][0] = AssemblyBounds(
        0,
        (-1.4, -0.1, -0.8),
        (-0.9, 0.1, -0.2),
        (
            (0.0, 1.0, 0.0),
            (-1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
    )
    failed = evaluate_assembly_bounds(plan, _scene(), bounds)
    alignment = next(
        item
        for item in failed.checks
        if item.relation_id == "orientation.trigger.x"
        and item.id.startswith("assembly.bounds")
    )
    clearance = next(
        item
        for item in failed.checks
        if item.relation_id == "clearance.trigger.guard"
        and item.id.startswith("assembly.bounds")
    )
    assert failed.ok is False
    assert alignment.status == "failed"
    assert alignment.residual == pytest.approx(90.0)
    assert clearance.status == "failed"
    assert clearance.metrics["signed_axis_gap_m"] < 0

    bounds["asset.trigger"][0] = AssemblyBounds(
        0,
        (-2.0, -0.1, -0.8),
        (-1.5, 0.1, -0.2),
    )
    unscorable = evaluate_assembly_bounds(plan, _scene(), bounds)
    alignment = next(
        item
        for item in unscorable.checks
        if item.relation_id == "orientation.trigger.x"
        and item.id.startswith("assembly.bounds")
    )
    assert alignment.status == "failed"
    assert alignment.metrics["scorable"] is False
    assert "basis is unavailable" in alignment.message


def test_prebuild_contract_requires_exact_scene_identity_and_sources() -> None:
    """Assembly relationships cannot silently bind missing SceneSpec objects or evidence."""

    plan = _spatial_plan()
    report = validate_assembly_prebuild_contract(plan, _scene())
    assert report.ok is True

    incomplete = _scene([item.id for item in plan.objects if item.id != "asset.trigger"])
    report = validate_assembly_prebuild_contract(plan, incomplete)
    assert report.ok is False
    assert any("asset.trigger" in item.message for item in report.checks)


def test_bounds_evaluator_detects_visible_side_trigger_but_accepts_explicit_side_part() -> None:
    """Evaluated geometry, not a zero transform, exposes a side-mounted centerline part."""

    plan = _spatial_plan()
    centered = evaluate_assembly_bounds(plan, _scene(), _bounds())
    assert centered.ok is True
    assert all(item.status == "passed" for item in centered.checks)

    displaced = evaluate_assembly_bounds(
        plan,
        _scene(),
        _bounds(side_trigger=True),
    )
    trigger = next(
        item
        for item in displaced.checks
        if item.relation_id == "center.trigger" and item.id.startswith("assembly.bounds")
    )
    side_control = next(
        item
        for item in displaced.checks
        if item.relation_id == "side.control" and item.id.startswith("assembly.bounds")
    )
    assert trigger.status == "failed"
    assert trigger.residual == pytest.approx(0.4)
    assert side_control.status == "passed"
    assert trigger.evidence_status == "inferred"
    assert trigger.source_ids == []


def test_bounds_evaluator_rejects_contact_without_transverse_overlap() -> None:
    """A matching contact height alone cannot validate a detached side-floating part."""

    plan = _spatial_plan()
    bounds = _bounds()
    bounds["asset.sight"] = [
        AssemblyBounds(0, (6.0, -0.2, 1.0), (7.0, 0.2, 1.4))
    ]

    report = evaluate_assembly_bounds(plan, _scene(), bounds)
    contact = next(
        item
        for item in report.checks
        if item.relation_id == "contact.sight"
        and item.id.startswith("assembly.bounds")
    )

    assert contact.status == "failed"
    assert contact.residual == pytest.approx(0.0)
    assert contact.metrics["transverse_overlap_ok"] is False


def test_job_wrapper_does_not_treat_world_aabb_as_intrinsic_assembly_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rotated object's world AABB remains unscorable without explicit frame-local bounds."""

    root = tmp_path / "assembly_test"
    (root / "analysis").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "analysis" / "modeling_plan.json").write_text(
        _spatial_plan().model_dump_json(indent=2),
        encoding="utf-8",
    )
    (root / "analysis" / "scene_spec.json").write_text(
        _scene().model_dump_json(indent=2),
        encoding="utf-8",
    )
    inventory = {
        "objects": [
            {
                "cbm_id": "asset.trigger",
                "instance_index": 0,
                "bbox_world": {"min": [-0.5, -0.1, -0.8], "max": [0.5, 0.1, -0.2]},
            }
        ]
    }
    inventory_path = root / "reports" / "scene_inventory.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    monkeypatch.setattr(
        "codex_blender_modeler.analysis.assembly.job_dir",
        lambda _job_id: root,
    )

    report = validate_job_assembly(
        "assembly_test",
        inventory_path=inventory_path,
        write_report=False,
        raise_on_error=True,
    )

    assert report.phase == "prebuild"
    warning = next(
        item for item in report.checks if item.id == "assembly.bounds.inventory_unscorable"
    )
    assert warning.status == "warning"
    assert "world-space AABBs" in warning.message


def test_pairwise_instance_policy_fails_closed_on_cardinality_mismatch() -> None:
    """Pairwise relationships reject a silent generator-instance broadcast."""

    payload = _spatial_plan().model_dump(mode="json")
    center = next(
        item for item in payload["assembly_relationships"] if item["id"] == "center.trigger"
    )
    center["instance_policy"] = "pairwise"
    plan = ModelingPlan.model_validate(payload)
    bounds = _bounds()
    bounds["asset.trigger"].append(
        AssemblyBounds(1, (0.5, -0.1, -0.8), (1.0, 0.1, -0.2))
    )
    report = evaluate_assembly_bounds(plan, _scene(), bounds)
    check = next(
        item for item in report.checks if item.id == "assembly.bounds.center.trigger"
    )
    assert check.status == "failed"
    assert "counts differ" in check.message


def test_spatial_assembly_contract_is_hash_bound_but_legacy_payload_is_unchanged(
    tmp_path: Path,
) -> None:
    """Every spatial frame is bound while legacy plans retain historical fingerprints."""

    root = tmp_path / "job"
    (root / "analysis").mkdir(parents=True)
    scene_path = root / "analysis" / "scene_spec.json"
    scene_path.write_text(_scene().model_dump_json(indent=2), encoding="utf-8")

    legacy = collect_build_provenance(
        root,
        "assembly_test",
        validate_contracts=False,
    )
    legacy_plan = ModelingPlan(
        job_id="assembly_test",
        reference_analysis_path="analysis/reference_analysis.json",
        camera_solution_path="analysis/camera_solution.json",
    )
    plan_path = root / "analysis" / "modeling_plan.json"
    plan_path.write_text(legacy_plan.model_dump_json(indent=2), encoding="utf-8")
    with_legacy_plan = collect_build_provenance(
        root,
        "assembly_test",
        validate_contracts=False,
    )
    assert with_legacy_plan == legacy
    assert "assembly_contracts" not in with_legacy_plan

    plan = _spatial_plan()
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    spatial = collect_build_provenance(
        root,
        "assembly_test",
        validate_contracts=False,
    )
    assert spatial["assembly_contracts"]["relationship_ids"] == sorted(
        item.id for item in plan.assembly_relationships
    )
    original_fingerprint = spatial["fingerprint"]
    raw = json.loads(plan_path.read_text(encoding="utf-8"))
    raw["assembly_relationships"][0]["confidence"] = 0.4
    plan_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    changed = collect_build_provenance(
        root,
        "assembly_test",
        validate_contracts=False,
    )
    assert changed["fingerprint"] != original_fingerprint

    frame_only = ModelingPlan.model_validate(
        {
            "job_id": "assembly_test",
            "reference_analysis_path": "analysis/reference_analysis.json",
            "camera_solution_path": "analysis/camera_solution.json",
            "stage": "authored",
            "objects": [
                {
                    "id": "asset.root",
                    "label": "Root",
                    "source_ids": ["reference"],
                    "assembly_role": "root",
                }
            ],
            "assembly_consistency_policy": "spatial_v1",
            "assembly_frame": {
                "root_object_id": "asset.root",
                "longitudinal_axis": "X",
                "lateral_axis": "Y",
                "vertical_axis": "Z",
                "evidence_status": "inferred",
            },
        }
    )
    plan_path.write_text(frame_only.model_dump_json(indent=2), encoding="utf-8")
    frame_bound = collect_build_provenance(
        root,
        "assembly_test",
        validate_contracts=False,
    )
    assert frame_bound["assembly_contracts"]["relationship_ids"] == []
    assert frame_bound["assembly_contracts"]["modeling_plan_sha256"]


def test_load_scene_spec_enforces_job_local_assembly_contract(tmp_path: Path) -> None:
    """The canonical SceneSpec loader rejects a stale spatial ModelingPlan identity map."""

    analysis = tmp_path / "workspaces" / "assembly_test" / "analysis"
    analysis.mkdir(parents=True)
    plan = _spatial_plan()
    (analysis / "modeling_plan.json").write_text(
        plan.model_dump_json(indent=2),
        encoding="utf-8",
    )
    incomplete = _scene([item.id for item in plan.objects if item.id != "asset.trigger"])
    scene_path = analysis / "scene_spec.json"
    scene_path.write_text(incomplete.model_dump_json(indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="Assembly consistency contract failed"):
        load_scene_spec(scene_path)
