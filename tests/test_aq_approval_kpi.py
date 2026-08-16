"""Deterministic validation for representative AQ approval-minimization fixtures."""

from __future__ import annotations

import json
from pathlib import Path

BENCHMARK_PATH = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "aq_approval_kpi"
    / "representative_asset_runs.json"
)

REQUIRED_ASSET_TYPES = {
    "procedural_only_metal_plastic",
    "localized_decal_signage",
    "detailed_wood",
    "crystal_emission_alpha",
    "shared_material_bounded_identity_split",
}


def _benchmark() -> dict[str, object]:
    """Load the repository-owned machine-readable KPI fixture."""

    return json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))


def test_kpi_fixture_is_honestly_labeled_and_covers_six_asset_types() -> None:
    """Require representative coverage without claiming real asset or activation proof."""

    benchmark = _benchmark()
    runs = benchmark["runs"]
    assert isinstance(runs, list)
    asset_types = {run["asset_type"] for run in runs}

    assert benchmark["fixture_kind"] == "representative_contract_fixture"
    assert benchmark["measurement_method"] == "deterministic_contract_validation"
    assert benchmark["actual_asset_e2e_verified"] is False
    assert benchmark["real_blender_execution_verified"] is False
    assert benchmark["human_review_performed"] is False
    assert benchmark["activation_evidence"] is False
    assert benchmark["profile_status"] == "disabled_experimental"
    assert benchmark["asset_count"] == len(asset_types) == 6
    assert benchmark["run_count"] == len(runs) == 7
    assert REQUIRED_ASSET_TYPES <= asset_types


def test_autonomous_kpi_runs_need_no_extra_or_technical_user_decisions() -> None:
    """Enforce the zero-additional-decision autonomous acceptance invariant."""

    runs = _benchmark()["runs"]
    autonomous = [run for run in runs if run["approval_mode"] == "autonomous"]
    assert len(autonomous) == 6
    for run in autonomous:
        assert run["initial_user_requests"] == 1
        assert run["additional_user_decisions"] == 0
        assert run["technical_user_approval_requests"] == 0
        assert run["terminal_type"] in {"production_delivery", "review_bundle"}
        assert run["canonical_corruption_count"] == 0


def test_checkpointed_kpi_run_caps_decisions_and_never_requests_technical_approval() -> None:
    """Enforce at most three checkpoint decisions and zero technical approvals."""

    runs = _benchmark()["runs"]
    checkpointed = [run for run in runs if run["approval_mode"] == "checkpointed"]
    assert len(checkpointed) == 1
    assert checkpointed[0]["additional_user_decisions"] <= 3
    assert checkpointed[0]["technical_user_approval_requests"] == 0
    assert checkpointed[0]["canonical_corruption_count"] == 0


def test_kpi_run_counters_are_bounded_machine_readable_values() -> None:
    """Reject missing, negative, or non-integer benchmark counter values."""

    counters = {
        "initial_user_requests",
        "additional_user_decisions",
        "technical_user_approval_requests",
        "policy_authorizations",
        "technical_repairs",
        "controller_invocations",
        "promotions",
        "rollbacks",
        "blender_builds",
        "quality_evaluations",
        "imagegen_generations",
        "delivery_runs",
        "elapsed_actions",
        "canonical_corruption_count",
    }
    for run in _benchmark()["runs"]:
        assert counters <= run.keys()
        assert all(isinstance(run[name], int) and run[name] >= 0 for name in counters)
