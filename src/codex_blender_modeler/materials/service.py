from __future__ import annotations

import json
from typing import Any

from ..analysis import validate_job_surface_details
from ..validation import load_scene_spec
from ..workspace import job_dir
from .io import load_material_plan
from .models import MaterialValidationCheck
from .validation import validate_material_contracts, write_material_validation_report


def validate_job_material_contracts(job_id: str) -> dict[str, Any]:
    """Validate one job's V0.5 plan, recipes, manifests, and SceneSpec material IDs."""

    root = job_dir(job_id)
    scene_spec_path = root / "analysis" / "scene_spec.json"
    material_plan_path = root / "analysis" / "material_plan.json"
    scene_spec = load_scene_spec(scene_spec_path).model_dump(mode="json")
    plan = load_material_plan(material_plan_path)
    report = validate_material_contracts(plan, scene_spec, root)
    surface_report = validate_job_surface_details(
        job_id,
        require_materials=True,
        write_report=True,
    )
    if surface_report.total:
        surface_checks = [
            MaterialValidationCheck(
                id=f"surface_detail:{item.id}",
                status=item.status,
                message=item.message,
                material_id=item.material_id,
            )
            for item in surface_report.checks
        ]
        checks = [*report.checks, *surface_checks]
        counts = {
            status: sum(item.status == status for item in checks)
            for status in ("passed", "warning", "failed")
        }
        report = report.model_copy(
            update={
                "ok": counts["failed"] == 0,
                "passed": counts["passed"],
                "warnings": counts["warning"],
                "failed": counts["failed"],
                "checks": checks,
                "notes": [
                    *report.notes,
                    (
                        "SurfaceDetailPlan bindings are validated separately and folded "
                        "into this material gate."
                    ),
                ],
            }
        )
    output = root / "reports" / "material_contract_validation.json"
    write_material_validation_report(report, output)
    result = report.model_dump(mode="json")
    result["path"] = str(output)
    return result


def load_job_material_contract_report(job_id: str) -> dict[str, Any]:
    """Load the latest host-side material contract report for one job."""

    path = job_dir(job_id) / "reports" / "material_contract_validation.json"
    if not path.is_file():
        raise FileNotFoundError(f"Material contract report does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
