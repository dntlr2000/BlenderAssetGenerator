import json
from pathlib import Path

from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.revision import apply_revision_plan, sha256_file


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
