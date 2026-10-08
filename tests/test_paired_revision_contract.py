"""Paired revisions may refine representation without rewriting observation contracts."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from codex_blender_modeler.analysis.models import ModelingPlan
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.orchestration.paired_revision import (
    validate_modeling_change,
    validate_pair,
)


def _plan_payload() -> dict[str, Any]:
    """Return a valid spatial plan whose redundant checks expose weakening attempts."""

    return {
        "job_id": "paired_asset",
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
        "stage": "authored",
        "assembly_consistency_policy": "spatial_v1",
        "assembly_frame": {
            "root_object_id": "asset.body",
            "longitudinal_axis": "Y",
            "lateral_axis": "X",
            "vertical_axis": "Z",
            "source_ids": ["reference"],
            "evidence_status": "observed",
        },
        "objects": [
            {
                "id": "asset.body",
                "label": "Body",
                "recommended_geometry": "primitive",
                "source_ids": ["reference"],
                "bbox_norm": [0.1, 0.1, 0.9, 0.9],
                "observed": True,
                "confidence": 0.9,
                "scope_role": "primary",
                "assembly_role": "root",
            },
            {
                "id": "asset.trim",
                "label": "Trim",
                "recommended_geometry": "primitive",
                "source_ids": ["reference"],
                "bbox_norm": [0.3, 0.3, 0.6, 0.6],
                "scope_role": "supporting",
                "assembly_role": "free_standing",
                "required_assembly_checks": ["position"],
            },
        ],
        "assembly_relationships": [
            {
                "id": f"relation.trim.{axis.lower()}",
                "kind": "center_plane",
                "subject_id": "asset.trim",
                "reference_id": "asset.body",
                "axis": axis,
                "source_ids": ["reference"],
                "evidence_status": "observed",
            }
            for axis in ("X", "Y")
        ],
        "surface_detail_policy": {
            "mode": "explicit",
            "geometry_required_conditions": ["silhouette", "structural"],
        },
        "surface_details": [
            {
                "id": "detail.body.mark",
                "label": "Body mark",
                "parent_object_id": "asset.body",
                "representation": "texture_channels",
                "source_ids": ["reference"],
                "bbox_norm": [0.3, 0.3, 0.4, 0.4],
                "target_material_id": "mat.body",
                "channels": ["base_color"],
                "uv_strategy": "existing_uv",
            }
        ],
    }


def _scene_payload() -> dict[str, Any]:
    """Build two semantic objects and materials with explicit bounded subject roles."""

    return {
        "job_id": "paired_asset",
        "mode": "concept",
        "nominal_scene_size": [1.0, 1.0, 1.0],
        "sources": [{"id": "reference", "path": "input/reference.png", "kind": "reference"}],
        "materials": [
            {
                "id": f"mat.{name}",
                "name": name.title(),
                "base_color": [0.5, 0.5, 0.5, 1.0],
                "roughness": 0.4,
                "metallic": 0.0,
            }
            for name in ("body", "trim")
        ],
        "objects": [
            {
                "id": f"asset.{name}",
                "name": name.title(),
                "geometry": {"kind": "primitive", "primitive": "cube", "dimensions": [1, 1, 1]},
                "material_id": f"mat.{name}",
                "tags": [f"qa_role:{role}"],
                "evidence": [
                    {
                        "source_id": "reference",
                        "bbox_norm": [0.1, 0.1, 0.9, 0.9],
                        "status": "observed",
                        "confidence": 0.8,
                    }
                ],
            }
            for name, role in (("body", "primary"), ("trim", "supporting"))
        ],
        "camera": {
            "projection": "ORTHO",
            "location": [3.0, -4.0, 3.0],
            "target": [0.0, 0.0, 0.0],
            "focal_length_mm": 50.0,
            "ortho_scale": 2.0,
            "resolution": [256, 256],
        },
    }


def _root(tmp_path: Path) -> Path:
    """Write only an isolated metadata fixture carrying an immutable object-only scope."""

    root = tmp_path / "paired_asset"
    root.mkdir()
    (root / "job.json").write_text(
        json.dumps(
            {
                "job_id": root.name,
                "mode": "concept",
                "reference_content_scope": "primary_object_only",
                "target_subject": "fixture body and trim",
            }
        ),
        encoding="utf-8",
    )
    return root


def _set(payload: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    """Replace one nested value while retaining a fully independently validated model."""

    parent: Any = payload
    for component in path[:-1]:
        parent = parent[component]
    parent[path[-1]] = value


def test_identical_pair_is_a_read_only_noop(tmp_path: Path) -> None:
    """An unchanged pair yields no semantic diff and writes no controller artifacts."""

    root = _root(tmp_path)
    before = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    plan = ModelingPlan.model_validate(_plan_payload())
    scene = SceneSpec.model_validate(_scene_payload())
    assert validate_modeling_change(plan, plan) == []
    assert validate_pair(root, scene, scene, plan, plan) == []
    after = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    assert after == before


def test_representation_notes_and_additive_obligations_are_allowed() -> None:
    """Keep evidence fixed while refining geometry and adding verifiable obligations."""

    old = ModelingPlan.model_validate(_plan_payload())
    new = old.model_dump(mode="json")
    new["objects"][0]["recommended_geometry"] = "custom_mesh"
    new["objects"][0]["notes"] = ["Refine the silhouette from the existing evidence."]
    new["global_notes"] = ["Representation revision only."]
    new["assembly_relationships"].append(
        {
            "id": "relation.trim.axis",
            "kind": "axis_alignment",
            "subject_id": "asset.trim",
            "reference_id": "asset.body",
            "source_ids": ["reference"],
            "subject_axis": "+Z",
            "target_direction": [0.0, 0.0, 1.0],
        }
    )
    new["objects"][1]["required_assembly_checks"].append("axis")
    new["surface_detail_policy"]["geometry_required_conditions"].append("gameplay")
    new["surface_detail_policy"]["notes"] = ["Preserve geometric features."]
    new["surface_details"][0]["notes"] = ["Retain the existing mark."]
    new["surface_details"].append({**new["surface_details"][0], "id": "detail.body.second"})
    candidate = ModelingPlan.model_validate(new)
    snapshot = old.model_dump(mode="json")
    changes = validate_modeling_change(old, candidate)
    assert changes
    assert all(isinstance(change, dict) for change in changes)
    assert changes == validate_modeling_change(old, candidate)
    assert old.model_dump(mode="json") == snapshot


def test_absent_surface_policy_can_become_explicit() -> None:
    """Legacy plans can acquire an explicit surface contract without changing observations."""

    old_payload = _plan_payload()
    old_payload["surface_detail_policy"] = None
    old_payload["surface_details"] = []
    old = ModelingPlan.model_validate(old_payload)
    assert validate_modeling_change(old, ModelingPlan.model_validate(_plan_payload()))


def test_diff_records_exact_before_and_after_values() -> None:
    """The reviewable diff records normalized field paths and both exact values."""

    old = ModelingPlan.model_validate(_plan_payload())
    payload = old.model_dump(mode="json")
    payload["global_notes"] = ["Representation refinement."]
    candidate = ModelingPlan.model_validate(payload)
    assert validate_modeling_change(old, candidate) == [
        {
            "path": "/global_notes",
            "before": [],
            "after": ["Representation refinement."],
        }
    ]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("job_id",), "foreign_job"),
        (("reference_analysis_path",), "analysis/other_reference.json"),
        (("camera_solution_path",), "analysis/other_camera.json"),
        (("stage",), "scaffold"),
        (("assembly_frame", "symmetry"), "bilateral"),
        (("assembly_frame", "confidence"), 0.2),
        (("assembly_frame", "notes"), ["New frame claim"]),
        (("objects", 0, "label"), "Different observed subject"),
        (("objects", 0, "source_ids"), ["reference", "new_evidence"]),
        (("objects", 0, "bbox_norm"), [0.2, 0.2, 0.7, 0.8]),
        (("objects", 0, "observed"), False),
        (("objects", 0, "confidence"), 0.2),
        (("objects", 0, "scope_role"), "context"),
        (("objects", 1, "assembly_role"), "attached"),
        (("objects", 1, "required_assembly_checks"), []),
        (("assembly_relationships", 0, "required"), False),
        (("assembly_relationships", 0, "confidence"), 0.1),
        (("assembly_relationships", 0, "source_ids"), []),
        (("assembly_relationships", 0, "axis"), "Z"),
        (("assembly_relationships", 0, "tolerance"), {"mode": "relative", "value": 0.3}),
        (("assembly_relationships", 0, "notes"), ["Replaced relationship evidence"]),
        (("surface_detail_policy", "mode"), "geometry_preferred"),
        (("surface_detail_policy", "default_representation"), "omit"),
        (("surface_detail_policy", "prefer_texture_for_repeated_details"), False),
        (("surface_detail_policy", "max_texture_projected_size_px"), 256),
        (("surface_detail_policy", "max_texture_relief_m"), 0.02),
        (("surface_detail_policy", "geometry_required_conditions"), ["silhouette"]),
        (("surface_details", 0, "representation"), "baked_decal"),
        (("surface_details", 0, "source_ids"), []),
        (("surface_details", 0, "parent_object_id"), "asset.trim"),
        (("surface_details", 0, "target_material_id"), "mat.trim"),
        (("surface_details", 0, "bbox_norm"), [0.1, 0.1, 0.2, 0.2]),
        (("surface_details", 0, "confidence"), 0.1),
    ],
)
def test_modeling_contract_rejects_observation_and_obligation_changes(
    path: tuple[str | int, ...],
    value: Any,
) -> None:
    """Reject forbidden edits even when most of the candidate remains unchanged."""

    old = ModelingPlan.model_validate(_plan_payload())
    payload = old.model_dump(mode="json")
    _set(payload, path, value)
    with pytest.raises(ValueError):
        validate_modeling_change(old, ModelingPlan.model_validate(payload))


@pytest.mark.parametrize(
    "change", ["objects", "relationships", "details", "policy", "policy_downgrade"]
)
def test_modeling_contract_rejects_removal_or_reordering(change: str) -> None:
    """Do not disguise removals, role changes, or reordered identities as additive edits."""

    old = ModelingPlan.model_validate(_plan_payload())
    payload = old.model_dump(mode="json")
    if change == "objects":
        payload["objects"].reverse()
    elif change == "relationships":
        payload["assembly_relationships"].pop(0)
    elif change == "details":
        payload["surface_details"] = []
    elif change == "policy":
        payload["surface_details"] = []
        payload["surface_detail_policy"] = None
    else:
        payload["assembly_consistency_policy"] = "legacy_unbound"
        payload["assembly_frame"] = None
        payload["assembly_relationships"] = []
        payload["objects"][1]["required_assembly_checks"] = []
    candidate = ModelingPlan.model_validate(payload)
    with pytest.raises(ValueError):
        validate_modeling_change(old, candidate)


@pytest.mark.parametrize("field", ["source_ids", "subject_id", "reference_id"])
def test_added_relationship_cannot_introduce_evidence_or_semantic_identity(field: str) -> None:
    """New relationships remain inside the existing object and reference identity sets."""

    old = ModelingPlan.model_validate(_plan_payload())
    payload = old.model_dump(mode="json")
    extra = {**payload["assembly_relationships"][0], "id": "relation.added"}
    extra[field] = ["foreign_source"] if field == "source_ids" else "asset.foreign"
    payload["assembly_relationships"].append(extra)
    with pytest.raises(ValueError):
        validate_modeling_change(old, ModelingPlan.model_validate(payload))


@pytest.mark.parametrize("change", ["rename", "remove", "add"])
def test_modeling_objects_keep_the_exact_identity_inventory(change: str) -> None:
    """Model-valid additions, removals, and coordinated renames still exceed the revision scope."""

    old = ModelingPlan.model_validate(_plan_payload())
    payload = old.model_dump(mode="json")
    if change == "rename":
        payload["objects"][1]["id"] = "asset.replacement"
        for relationship in payload["assembly_relationships"]:
            relationship["subject_id"] = "asset.replacement"
    elif change == "remove":
        payload["objects"].pop()
        payload["assembly_relationships"] = []
    else:
        payload["objects"].append(
            {
                **payload["objects"][1],
                "id": "asset.extra",
                "required_assembly_checks": [],
            }
        )
    candidate = ModelingPlan.model_validate(payload)
    with pytest.raises(ValueError):
        validate_modeling_change(old, candidate)


@pytest.mark.parametrize("collection", ["assembly_relationships", "surface_details"])
@pytest.mark.parametrize("change", ["reorder", "prepend"])
def test_append_only_collections_preserve_existing_order(collection: str, change: str) -> None:
    """Append-only evidence lists cannot reorder or insert ahead of their immutable prefix."""

    payload = _plan_payload()
    if collection == "surface_details":
        payload[collection].append({**payload[collection][0], "id": "detail.body.other"})
    old = ModelingPlan.model_validate(payload)
    updated = old.model_dump(mode="json")
    if change == "reorder":
        updated[collection].reverse()
    else:
        updated[collection].insert(0, {**updated[collection][0], "id": "new.entry"})
    candidate = ModelingPlan.model_validate(updated)
    with pytest.raises(ValueError):
        validate_modeling_change(old, candidate)


def test_added_detail_cannot_claim_an_unknown_observation_source() -> None:
    """Schema-valid detail additions cannot expand the existing evidence-source inventory."""

    old = ModelingPlan.model_validate(_plan_payload())
    payload = old.model_dump(mode="json")
    payload["surface_details"].append(
        {
            **payload["surface_details"][0],
            "id": "detail.foreign",
            "source_ids": ["foreign_source"],
        }
    )
    candidate = ModelingPlan.model_validate(payload)
    with pytest.raises(ValueError):
        validate_modeling_change(old, candidate)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("job_id",), "foreign_job"),
        (("mode",), "measured"),
        (("sources", 0, "path"), "input/replacement.png"),
        (("sources", 0, "id"), "foreign_source"),
        (("sources", 0, "immutable"), False),
        (("objects", 0, "id"), "asset.replacement"),
        (("objects", 0, "material_id"), "mat.trim"),
        (("objects", 0, "evidence", 0, "confidence"), 0.1),
        (("objects", 0, "tags"), ["qa_role:background"]),
    ],
)
def test_pair_rejects_scene_source_identity_assignment_and_scope_drift(
    tmp_path: Path,
    path: tuple[str | int, ...],
    value: Any,
) -> None:
    """Candidate geometry cannot substitute a different subject, material, or evidence."""

    root = _root(tmp_path)
    old = ModelingPlan.model_validate(_plan_payload())
    scene = SceneSpec.model_validate(_scene_payload())
    payload = scene.model_dump(mode="json")
    _set(payload, path, value)
    candidate = SceneSpec.model_validate(payload)
    with pytest.raises(ValueError):
        validate_pair(root, scene, candidate, old, old)


def test_pair_rejects_material_identity_replacement_even_if_assignment_matches(
    tmp_path: Path,
) -> None:
    """Changing both material identity and its use cannot hide a semantic split."""

    root = _root(tmp_path)
    old = ModelingPlan.model_validate(_plan_payload())
    scene = SceneSpec.model_validate(_scene_payload())
    payload = scene.model_dump(mode="json")
    payload["materials"][0]["id"] = "mat.replacement"
    payload["objects"][0]["material_id"] = "mat.replacement"
    with pytest.raises(ValueError):
        validate_pair(root, scene, SceneSpec.model_validate(payload), old, old)


def test_pair_accepts_geometry_changes_with_stable_evidence(tmp_path: Path) -> None:
    """The bounded contract permits scene modeling edits and preserves all source claims."""

    root = _root(tmp_path)
    old = ModelingPlan.model_validate(_plan_payload())
    scene = SceneSpec.model_validate(_scene_payload())
    payload = scene.model_dump(mode="json")
    payload["objects"][0]["geometry"]["dimensions"] = [1.1, 1.0, 1.0]
    payload["revision_notes"] = ["Refine the existing body silhouette."]
    new_plan = old.model_dump(mode="json")
    new_plan["objects"][0]["notes"] = ["Refine the existing body silhouette."]
    assert validate_pair(
        root, scene, SceneSpec.model_validate(payload), old, ModelingPlan.model_validate(new_plan)
    )


@pytest.mark.parametrize("model", ["plan", "scene"])
def test_paired_inputs_reject_unknown_fields(model: str) -> None:
    """Strict candidate parsing rejects undeclared authority-bearing fields."""

    payload = _plan_payload() if model == "plan" else _scene_payload()
    payload["approval_override"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        (ModelingPlan if model == "plan" else SceneSpec).model_validate(payload)


@pytest.mark.parametrize("model", ["plan", "scene"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_pair_rejects_nonfinite_values_before_diffing(
    tmp_path: Path,
    model: str,
    value: float,
) -> None:
    """Unbounded vectors and policy numbers cannot bypass checks through NaN comparison."""

    root = _root(tmp_path)
    old = ModelingPlan.model_validate(_plan_payload())
    scene = SceneSpec.model_validate(_scene_payload())
    candidate_plan = deepcopy(old)
    candidate_scene = deepcopy(scene)
    if model == "plan":
        old.surface_detail_policy = None
        old.surface_details = []
        candidate_plan.surface_details = []
        candidate_plan.surface_detail_policy.max_texture_relief_m = value
    else:
        candidate_scene.objects[0].geometry.dimensions = (value, 1.0, 1.0)
    with pytest.raises(ValueError):
        validate_pair(root, scene, candidate_scene, old, candidate_plan)
