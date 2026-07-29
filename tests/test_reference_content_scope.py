from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_blender_modeler.analysis.models import ModelingPlan, ModelingPlanObject
from codex_blender_modeler.build_provenance import (
    BuildProvenanceError,
    collect_build_provenance,
)
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.reference_scope import (
    validate_modeling_plan_content_scope,
    validate_scene_content_scope,
)

ROOT = Path(__file__).resolve().parents[1]


def _subject_scene() -> SceneSpec:
    """Load a valid example and label every object as part of one selected subject."""

    raw = json.loads(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    raw["job_id"] = "subject_asset"
    for index, item in enumerate(raw["objects"]):
        item["tags"] = [
            "qa_role:primary" if index == 0 else "qa_role:supporting"
        ]
    return SceneSpec.model_validate(raw)


def test_primary_object_plan_requires_explicit_subject_roles() -> None:
    """Reject context or unclassified objects before object-only SceneSpec authoring."""

    plan = ModelingPlan(
        job_id="subject_asset",
        reference_analysis_path="analysis/reference_analysis.json",
        camera_solution_path="analysis/camera_solution.json",
        stage="authored",
        objects=[
            ModelingPlanObject(
                id="vehicle.body",
                label="body",
                scope_role="primary",
            ),
            ModelingPlanObject(
                id="environment.rock",
                label="rock",
                scope_role="context",
            ),
        ],
    )
    with pytest.raises(ValueError, match="scope_role"):
        validate_modeling_plan_content_scope(
            plan,
            scope="primary_object_only",
            target_subject="vehicle",
        )

    selected = plan.model_copy(
        update={"objects": [plan.objects[0]]},
    )
    validate_modeling_plan_content_scope(
        selected,
        scope="primary_object_only",
        target_subject="vehicle",
    )


def test_primary_object_scene_rejects_context_and_binds_build_provenance(
    tmp_path: Path,
) -> None:
    """Enforce object-only geometry at build time and hash the scope into provenance."""

    spec = _subject_scene()
    validate_scene_content_scope(
        spec,
        scope="primary_object_only",
        target_subject="showcase object",
    )

    root = tmp_path / "subject_asset"
    (root / "analysis").mkdir(parents=True)
    (root / "job.json").write_text(
        json.dumps(
            {
                "job_id": "subject_asset",
                "reference_content_scope": "primary_object_only",
                "target_subject": "showcase object",
            }
        ),
        encoding="utf-8",
    )
    scene_path = root / "analysis" / "scene_spec.json"
    scene_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    provenance = collect_build_provenance(root, "subject_asset")
    assert provenance["reference_content_scope"] == {
        "reference_content_scope": "primary_object_only",
        "target_subject": "showcase object",
    }
    blender_provenance = collect_build_provenance(
        root,
        "subject_asset",
        validate_contracts=False,
    )
    assert blender_provenance == provenance

    changed = spec.model_dump(mode="json")
    changed["objects"][-1]["tags"] = ["qa_role:decorative"]
    scene_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(BuildProvenanceError, match="forbids independent terrain"):
        collect_build_provenance(root, "subject_asset")
