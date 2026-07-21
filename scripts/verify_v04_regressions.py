from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from codex_blender_modeler.analysis import load_modeling_plan
from codex_blender_modeler.config import get_settings
from codex_blender_modeler.constraints import evaluate_constraint_set
from codex_blender_modeler.constraints.models import ConstraintSet, DimensionConstraint
from codex_blender_modeler.validation import load_scene_spec
from codex_blender_modeler.workspace import job_dir

EXPECTED_MODIFIERS = {
    "array",
    "bevel",
    "boolean",
    "decimate",
    "mirror",
    "remesh",
    "solidify",
    "subdivision",
}


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regression input or contract file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    """Load one required JSON artifact for a regression assertion."""

    return json.loads(path.read_text(encoding="utf-8"))


def geometry_payload_digest(directory: Path) -> tuple[int, str]:
    """Hash geometry payload names and contents in a stable cross-platform order."""

    files = sorted(path for path in directory.iterdir() if path.is_file())
    records = [f"{path.name}:{sha256_file(path)}" for path in files]
    digest = hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()
    return len(files), digest


def require(condition: bool, message: str, failures: list[str]) -> None:
    """Append a human-readable failure while allowing every gate to be reported."""

    if not condition:
        failures.append(message)


def check_modifier_coverage(failures: list[str]) -> dict[str, Any]:
    """Verify Blender validation observed all eight supported modifier families."""

    validation_path = job_dir("geometry_showcase") / "reports" / "validation.json"
    validation = load_json(validation_path)
    metrics = validation.get("metrics", {})
    declared = set(metrics.get("declared_modifier_kinds", []))
    applied = set(metrics.get("applied_modifier_kinds", []))
    require(validation.get("ok") is True, "geometry_showcase validation is not ok", failures)
    require(
        declared == EXPECTED_MODIFIERS,
        f"Declared modifier coverage mismatch: {sorted(declared)}",
        failures,
    )
    require(
        applied == EXPECTED_MODIFIERS,
        f"Applied modifier coverage mismatch: {sorted(applied)}",
        failures,
    )
    return {
        "validation_path": str(validation_path),
        "declared": sorted(declared),
        "applied": sorted(applied),
        "ok": validation.get("ok") is True and declared == applied == EXPECTED_MODIFIERS,
    }


def check_constraint_outcomes(failures: list[str]) -> dict[str, Any]:
    """Prove the measured evaluator distinguishes a passing and failing residual."""

    inventory_path = job_dir("measured_box") / "reports" / "scene_inventory.json"
    inventory = load_json(inventory_path)
    family = next(
        (item for item in inventory.get("families", []) if item.get("cbm_id") == "asset.box"),
        None,
    )
    if family is None:
        failures.append("measured_box inventory is missing asset.box")
        return {"inventory_path": str(inventory_path), "ok": False}
    actual_width = float(family["dimensions"][0])
    constraint_set = ConstraintSet(
        job_id="measured_box",
        constraints=[
            DimensionConstraint(
                id="regression.width.pass",
                target_id="asset.box",
                axis="X",
                value_m=actual_width,
                tolerance_m=0.001,
                source="v0.4 regression gate",
            ),
            DimensionConstraint(
                id="regression.width.fail",
                target_id="asset.box",
                axis="X",
                value_m=actual_width + 0.25,
                tolerance_m=0.001,
                source="v0.4 regression gate",
            ),
        ],
        notes=["This in-memory gate must report one pass and one intentional failure."],
    )
    solution = evaluate_constraint_set(constraint_set, inventory)
    pass_result, fail_result = solution.results
    require(solution.ok is False, "Intentional failing constraint reported ok=true", failures)
    require(
        solution.passed == 1,
        f"Expected one passing constraint, got {solution.passed}",
        failures,
    )
    require(
        solution.failed == 1,
        f"Expected one failing constraint, got {solution.failed}",
        failures,
    )
    require(
        pass_result.status == "passed",
        "Passing constraint was not classified passed",
        failures,
    )
    require(
        fail_result.status == "failed",
        "Failing constraint was not classified failed",
        failures,
    )
    require(
        abs(float(fail_result.residual_m or 0.0) - 0.25) <= 1e-9,
        f"Intentional failing residual was {fail_result.residual_m}, expected 0.25",
        failures,
    )
    output = get_settings().repo_root / "reports" / "v04_regression_constraint_outcomes.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(solution.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return {
        "inventory_path": str(inventory_path),
        "report_path": str(output),
        "actual_width_m": actual_width,
        "passed": solution.passed,
        "failed": solution.failed,
        "intentional_failure_residual_m": fail_result.residual_m,
        "ok": (
            not solution.ok
            and solution.passed == 1
            and solution.failed == 1
            and fail_result.status == "failed"
        ),
    }


def check_authored_modeling_plan(failures: list[str]) -> dict[str, Any]:
    """Verify the measured fixture retains a non-empty observed/inferred authored plan."""

    plan_path = job_dir("measured_box") / "analysis" / "modeling_plan.json"
    plan = load_modeling_plan(plan_path)
    observed = [item.id for item in plan.objects if item.observed]
    inferred = [item.id for item in plan.objects if not item.observed]
    require(plan.stage == "authored", f"Modeling plan stage is {plan.stage!r}", failures)
    require(bool(plan.objects), "Authored modeling plan is empty", failures)
    require(bool(observed), "Authored modeling plan has no observed object", failures)
    require(bool(inferred), "Authored modeling plan has no inferred object", failures)
    return {
        "path": str(plan_path),
        "stage": plan.stage,
        "object_count": len(plan.objects),
        "observed_ids": observed,
        "inferred_ids": inferred,
        "ok": plan.stage == "authored" and bool(observed) and bool(inferred),
    }


def check_first_reference_regression(failures: list[str]) -> dict[str, Any]:
    """Compare the approved reference workspace against immutable fixture baselines."""

    settings = get_settings()
    baseline_path = (
        settings.repo_root
        / "examples"
        / "first_reference_test"
        / "regression_baseline.json"
    )
    baseline = load_json(baseline_path)
    root = job_dir("first_reference_test")
    reference_path = root / "input" / "reference.png"
    spec_path = root / "analysis" / "scene_spec.json"
    validation_path = root / "reports" / "validation.json"
    spec = load_scene_spec(spec_path)
    validation = load_json(validation_path)
    ids = sorted(item.id for item in spec.objects)
    semantic_digest = hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()
    expected_instances = sum(item.generator.count if item.generator else 1 for item in spec.objects)
    payload_count, payload_digest = geometry_payload_digest(root / "geometry")

    require(
        sha256_file(reference_path) == baseline["reference_sha256"],
        "Reference hash changed",
        failures,
    )
    require(
        sha256_file(spec_path) == baseline["scene_spec_sha256"],
        "SceneSpec hash changed",
        failures,
    )
    require(
        spec.schema_version == baseline["scene_spec_version"],
        "SceneSpec version changed",
        failures,
    )
    require(
        len(ids) == baseline["semantic_object_families"],
        "Semantic family count changed",
        failures,
    )
    require(semantic_digest == baseline["semantic_ids_sha256"], "Semantic ID set changed", failures)
    require(
        expected_instances == baseline["expected_instances"],
        "Generated instance contract changed",
        failures,
    )
    require(
        payload_count == baseline["geometry_payload_count"],
        "Geometry payload count changed",
        failures,
    )
    require(
        payload_digest == baseline["geometry_payload_sha256"],
        "Geometry payload hash changed",
        failures,
    )
    require(
        list(spec.nominal_scene_size) == baseline["nominal_scene_size"],
        "Nominal size changed",
        failures,
    )
    camera = spec.camera.model_dump(mode="json")
    require(camera == baseline["camera"], "Comparison camera contract changed", failures)
    require(validation.get("ok") is True, "first_reference_test validation is not ok", failures)
    actual_metrics = validation.get("metrics", {})
    for key, expected in baseline["validation_metrics"].items():
        require(
            actual_metrics.get(key) == expected,
            f"first_reference_test metric {key} changed: {actual_metrics.get(key)} != {expected}",
            failures,
        )
    return {
        "baseline_path": str(baseline_path),
        "workspace": str(root),
        "reference_sha256": sha256_file(reference_path),
        "scene_spec_sha256": sha256_file(spec_path),
        "geometry_payload_count": payload_count,
        "geometry_payload_sha256": payload_digest,
        "semantic_object_families": len(ids),
        "expected_instances": expected_instances,
        "validation_ok": validation.get("ok"),
        "validation_metrics": actual_metrics,
    }


def main() -> None:
    """Run the four completion regressions and emit one machine-readable gate report."""

    failures: list[str] = []
    sections = {
        "modifier_coverage": check_modifier_coverage(failures),
        "constraint_outcomes": check_constraint_outcomes(failures),
        "authored_modeling_plan": check_authored_modeling_plan(failures),
        "first_reference_regression": check_first_reference_regression(failures),
    }
    report = {
        "schema_version": "0.1.0",
        "project_version": "0.4.0",
        "ok": not failures,
        "failures": failures,
        "sections": sections,
    }
    output = get_settings().repo_root / "reports" / "v04_completion_regression.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
