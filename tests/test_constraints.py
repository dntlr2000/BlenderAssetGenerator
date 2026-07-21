from __future__ import annotations

import json
from pathlib import Path

from codex_blender_modeler.constraints import evaluate_job_constraints
from codex_blender_modeler.constraints.models import ConstraintSet, DimensionConstraint
from codex_blender_modeler.workspace import create_job, job_dir


def test_constraint_evaluation_distinguishes_pass_and_fail(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify that the same inventory reports both an exact pass and a residual failure."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference")
    create_job("measured_asset", reference, "measured", [])
    root = job_dir("measured_asset")
    constraint_set = ConstraintSet(
        job_id="measured_asset",
        constraints=[
            DimensionConstraint(
                id="box.width.pass",
                target_id="asset.box",
                axis="X",
                value_m=2.0,
                tolerance_m=0.001,
            ),
            DimensionConstraint(
                id="box.width.fail",
                target_id="asset.box",
                axis="X",
                value_m=2.25,
                tolerance_m=0.001,
            ),
        ],
    )
    (root / "constraints" / "constraints.json").write_text(
        constraint_set.model_dump_json(indent=2), encoding="utf-8"
    )
    inventory = {
        "families": [
            {
                "cbm_id": "asset.box",
                "bbox_world": {"min": [-1.0, -0.5, 0.0], "max": [1.0, 0.5, 1.0]},
            }
        ],
        "objects": [],
    }
    (root / "reports" / "scene_inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    solution = evaluate_job_constraints("measured_asset")
    assert solution.ok is False
    assert solution.passed == 1
    assert solution.failed == 1
    assert solution.results[0].residual_m == 0
    assert solution.results[0].status == "passed"
    assert solution.results[1].residual_m == 0.25
    assert solution.results[1].status == "failed"
    assert "exceeds tolerance" in solution.results[1].message
