"""Regression contracts extracted from the first real AQ v2 canary failure."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codex_blender_modeler.autonomy_v2 import (
    approval_supervisor_service,
    candidate_validation_service,
)


def test_workspace_qualified_diagnostic_paths_fail_before_candidate_promotion() -> None:
    """Reject Windows workspace paths while accepting only canonical analysis-relative paths."""

    invalid = SimpleNamespace(
        reference_analysis_path=(
            "workspaces\\item_metal_plastic_aq_canary_01\\"
            "analysis\\reference_analysis.json"
        ),
        camera_solution_path=(
            "workspaces\\item_metal_plastic_aq_canary_01\\"
            "analysis\\camera_solution.json"
        ),
    )
    with pytest.raises(ValueError, match="canonical reference diagnostics"):
        candidate_validation_service._validate_modeling_diagnostic_bindings(invalid)

    corrected = SimpleNamespace(
        reference_analysis_path="analysis/reference_analysis.json",
        camera_solution_path="analysis/camera_solution.json",
    )
    candidate_validation_service._validate_modeling_diagnostic_bindings(corrected)


def test_telemetry_separates_promotion_authorization_from_executed_promotion() -> None:
    """Do not report a consumed promotion authorization as a canonical state mutation."""

    authorization_count, executed_count = (
        approval_supervisor_service._telemetry_promotion_counts(
            SimpleNamespace(canonical_promotions=1),
            SimpleNamespace(
                budget_usage=SimpleNamespace(canonical_promotions=0),
            ),
        )
    )

    assert authorization_count == 1
    assert executed_count == 0


def test_repeated_framework_failure_is_not_classified_as_job_local() -> None:
    """Keep a repeated framework terminal semantically distinct from one bad candidate."""

    assert (
        approval_supervisor_service._framework_classification_for_failure(
            "repeated_framework_failure"
        )
        == "reusable_missing_capability"
    )
