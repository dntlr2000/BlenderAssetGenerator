from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from PIL import Image, ImageDraw
from pydantic import ValidationError

from codex_blender_modeler.analysis import (
    analyze_job_reference,
    load_camera_solution,
    load_modeling_plan,
)
from codex_blender_modeler.analysis.models import ModelingPlan, ModelingPlanObject
from codex_blender_modeler.workspace import create_job


def test_basic_reference_analysis_writes_diagnostics(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    image_path = tmp_path / "building.png"
    image = Image.new("RGB", (320, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 40, 260, 180), fill=(80, 120, 180))
    draw.polygon([(60, 40), (160, 10), (260, 40)], fill=(90, 60, 40))
    image.save(image_path)
    create_job("building_001", image_path, "concept", [])

    outputs = analyze_job_reference("building_001", provider="basic")
    analysis_path = Path(outputs["reference_analysis"])
    raw = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "0.4.0"
    assert raw["images"][0]["width"] == 320
    assert 0 <= raw["images"][0]["edge_density"] <= 1
    edge_path = Path(raw["images"][0]["diagnostics"]["edge_map"])
    if not edge_path.is_absolute():
        edge_path = Path(__file__).resolve().parents[1] / edge_path
    assert edge_path.exists()
    camera = load_camera_solution("building_001")
    assert camera.projection == "PERSP"


def test_authored_modeling_plan_requires_unique_nonempty_objects(tmp_path: Path) -> None:
    """Verify authored plans preserve observed/inferred objects and reject weak contracts."""

    plan = ModelingPlan(
        job_id="measured_box",
        reference_analysis_path="workspaces/measured_box/analysis/reference_analysis.json",
        camera_solution_path="workspaces/measured_box/analysis/camera_solution.json",
        stage="authored",
        objects=[
            ModelingPlanObject(
                id="asset.box",
                label="Measured box",
                recommended_geometry="primitive",
                source_ids=["reference"],
                observed=True,
                confidence=0.95,
            ),
            ModelingPlanObject(
                id="asset.box.hidden_backface",
                label="Inferred hidden back face",
                recommended_geometry="undecided",
                source_ids=["reference"],
                observed=False,
                confidence=0.3,
            ),
        ],
    )
    plan_path = tmp_path / "modeling_plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    loaded = load_modeling_plan(plan_path)
    assert loaded.stage == "authored"
    assert {item.observed for item in loaded.objects} == {True, False}

    with pytest.raises(ValidationError, match="at least one object"):
        ModelingPlan(
            job_id="empty_plan",
            reference_analysis_path="reference_analysis.json",
            camera_solution_path="camera_solution.json",
            stage="authored",
        )

    duplicate = ModelingPlanObject(id="asset.duplicate", label="Duplicate")
    with pytest.raises(ValidationError, match="must be unique"):
        ModelingPlan(
            job_id="duplicate_plan",
            reference_analysis_path="reference_analysis.json",
            camera_solution_path="camera_solution.json",
            stage="authored",
            objects=[duplicate, duplicate],
        )


def test_modeling_plan_schema_rejects_empty_authored_plan() -> None:
    """Verify the exported Codex output schema also enforces authored plan content."""

    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas" / "modeling_plan.schema.json").read_text())
    validator = Draft202012Validator(schema)
    empty_authored = {
        "schema_version": "0.4.0",
        "job_id": "empty_plan",
        "reference_analysis_path": "reference_analysis.json",
        "camera_solution_path": "camera_solution.json",
        "stage": "authored",
        "objects": [],
        "global_notes": [],
    }
    errors = list(validator.iter_errors(empty_authored))
    assert errors
    assert any("should be non-empty" in error.message for error in errors)
