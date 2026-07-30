import json
from pathlib import Path

import pytest

from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.revision import (
    RevisionOperation,
    apply_revision_plan,
    sha256_file,
)


def test_guarded_revision_changes_only_requested_path(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (root / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text()
    )
    scene_path = tmp_path / "scene_spec.json"
    scene_path.write_text(json.dumps(raw, indent=2) + "\n")
    plan = {
        "schema_version": "0.1.0",
        "job_id": "geometry_showcase",
        "base_spec_sha256": sha256_file(scene_path),
        "request": "Make the pyramid 20% taller",
        "operations": [
            {
                "op": "multiply",
                "target_type": "object",
                "target_id": "demo.custom_pyramid",
                "path": ["transform", "scale", 2],
                "value": 1.2,
                "reason": "Only change vertical scale",
            }
        ],
        "acceptance_criteria": ["Pyramid vertical scale is 1.2"],
        "assumptions": [],
    }
    plan_path = tmp_path / "revision_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    output = tmp_path / "scene_spec.next.json"

    spec, report = apply_revision_plan(
        scene_spec_path=scene_path,
        plan_path=plan_path,
        output_path=output,
    )

    assert isinstance(spec, SceneSpec)
    pyramid = next(obj for obj in spec.objects if obj.id == "demo.custom_pyramid")
    assert pyramid.transform.scale[2] == 1.2
    house = next(obj for obj in spec.objects if obj.id == "demo.profile_house")
    assert house.transform.scale == (1.0, 1.0, 1.0)
    assert len(report["changes"]) == 1


def test_guarded_revision_removes_exact_scene_object_ids(tmp_path: Path) -> None:
    """Remove only explicitly listed stable object IDs from the SceneSpec object list."""

    root = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (root / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text()
    )
    scene_path = tmp_path / "scene_spec.json"
    scene_path.write_text(json.dumps(raw, indent=2) + "\n")
    plan = {
        "schema_version": "0.1.0",
        "job_id": "geometry_showcase",
        "base_spec_sha256": sha256_file(scene_path),
        "request": "Remove one obsolete detail object",
        "operations": [
            {
                "op": "remove",
                "target_type": "scene",
                "target_id": None,
                "path": ["objects"],
                "value": ["demo.profile_house"],
                "reason": "Delete only the exact obsolete stable object ID",
            }
        ],
        "acceptance_criteria": ["Only demo.profile_house is absent"],
        "assumptions": [],
    }
    plan_path = tmp_path / "revision_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    output = tmp_path / "scene_spec.next.json"

    spec, report = apply_revision_plan(
        scene_spec_path=scene_path,
        plan_path=plan_path,
        output_path=output,
    )

    ids = {obj.id for obj in spec.objects}
    assert "demo.profile_house" not in ids
    assert "demo.custom_pyramid" in ids
    assert len(ids) == len(raw["objects"]) - 1
    assert report["changes"][0]["op"] == "remove"


def test_guarded_revision_remove_rejects_missing_or_unsafe_targets(
    tmp_path: Path,
) -> None:
    """Reject missing stable IDs and any remove operation outside scene.objects."""

    root = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (root / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text()
    )
    scene_path = tmp_path / "scene_spec.json"
    scene_path.write_text(json.dumps(raw, indent=2) + "\n")
    plan = {
        "schema_version": "0.1.0",
        "job_id": "geometry_showcase",
        "base_spec_sha256": sha256_file(scene_path),
        "request": "Attempt to remove a missing object",
        "operations": [
            {
                "op": "remove",
                "target_type": "scene",
                "target_id": None,
                "path": ["objects"],
                "value": ["demo.missing"],
                "reason": "Exercise fail-closed exact-ID removal",
            }
        ],
        "acceptance_criteria": ["Application fails closed"],
        "assumptions": [],
    }
    plan_path = tmp_path / "revision_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")

    with pytest.raises(ValueError, match="exactly one scene object"):
        apply_revision_plan(
            scene_spec_path=scene_path,
            plan_path=plan_path,
            output_path=tmp_path / "scene_spec.next.json",
        )

    with pytest.raises(ValueError, match="limited to"):
        RevisionOperation.model_validate(
            {
                "op": "remove",
                "target_type": "object",
                "target_id": "demo.custom_pyramid",
                "path": ["tags"],
                "value": ["detail"],
                "reason": "Unsafe non-object-list removal",
            }
        )
