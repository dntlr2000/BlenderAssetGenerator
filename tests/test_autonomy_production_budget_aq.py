"""Focused tests for exact V0.8 production accounting and package repair."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from codex_blender_modeler.autonomy import package_repair_runtime as repair_runtime
from codex_blender_modeler.autonomy.authorization import artifact_for
from codex_blender_modeler.autonomy.models import (
    AutonomyArtifact,
    AutonomyBudget,
    BudgetUsage,
)
from codex_blender_modeler.autonomy.package_repair_runtime import (
    execute_package_repair,
    prepare_package_repair,
)
from codex_blender_modeler.autonomy.production_budget import (
    PackageRepairFailure,
    PackageRepairPlan,
    PackageRepairReceipt,
    ProductionResourceDelta,
    ProductionResourceReceipt,
    ProductionStepResourceClassification,
    classify_package_repair,
    classify_production_step_resources,
    reserve_production_step_resources,
)
from codex_blender_modeler.autonomy.service import _record_production_resource_receipt
from codex_blender_modeler.orchestration.models import (
    ArtifactFreshness,
    WorkflowState,
    WorkflowStep,
    WorkflowStepState,
)

ZERO = "0" * 64
ONE = "1" * 64
TWO = "2" * 64
NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _artifact(path: str, sha256: str = ZERO) -> AutonomyArtifact:
    """Create one deterministic repository-relative artifact fixture."""

    return AutonomyArtifact(path=path, sha256=sha256)


def _budget(**changes: int) -> AutonomyBudget:
    """Create one bounded autonomy budget with optional limit overrides."""

    values: dict[str, object] = {
        "budget_id": "budget-production",
        "job_id": "aq_production_budget",
        "workflow_id": "wf-production-budget",
        "dispatch_id": "dispatch-production-budget",
        "input_sha256": ZERO,
        "source_fingerprint": ONE,
        "provenance": [_artifact("input/reference.png")],
        "created_at": NOW,
    }
    values.update(changes)
    return AutonomyBudget.model_validate(values)


def _step(tool_name: str, **parameters: str | int | float | bool) -> WorkflowStep:
    """Create one minimal V0.8 host-step fixture."""

    return WorkflowStep(
        step_id=f"test.{tool_name}",
        title=f"Test {tool_name}",
        phase="portable" if "portable" in tool_name else "qa",
        execution_mode="host",
        tool_name=tool_name,
        parameters=parameters,
    )


def _failure(
    error_code: str,
    *,
    phase: str = "roundtrip",
    deterministic: bool = True,
    canonical_inputs_current: bool = True,
) -> PackageRepairFailure:
    """Create one exact normalized package-failure fixture."""

    return PackageRepairFailure(
        contract_id=f"failure-{error_code}",
        job_id="aq_production_budget",
        workflow_id="wf-production-budget",
        dispatch_id="dispatch-production-budget",
        input_sha256=ZERO,
        source_fingerprint=ONE,
        producer="test",
        producer_version="0.1.0",
        provenance=[_artifact("workflows/wf-production-budget/attempt.json")],
        created_at=NOW,
        session_id="session-production-budget",
        phase=phase,
        error_code=error_code,
        failure_evidence=_artifact("workflows/wf-production-budget/attempt.json"),
        deterministic=deterministic,
        canonical_inputs_current=canonical_inputs_current,
        canonical_input_fingerprint=TWO,
        details=["deterministic fixture"],
    )


def _classify_repair(failure: PackageRepairFailure, usage: BudgetUsage):
    """Invoke repair classification with stable identity fixtures."""

    return classify_package_repair(
        failure=failure,
        budget=_budget(),
        usage=usage,
        contract_id="repair-plan-1",
        profile_id="portable_gltf",
        package_id="package-production-budget",
        repair_index=1,
        provenance=[failure.failure_evidence],
        created_at=NOW,
    )


def test_all_current_planner_tool_names_have_explicit_accounting() -> None:
    """Fail when a newly planned V0.8 tool lacks an explicit resource classification."""

    planner = Path("src/codex_blender_modeler/orchestration/planner.py").read_text(
        encoding="utf-8"
    )
    tools = sorted(set(re.findall(r'tool="([^"]+)"', planner)))
    tools.append("verify_background_preview_prerequisite")
    assert tools
    for tool_name in tools:
        classify_production_step_resources(_step(tool_name, max_attempts=2))


@pytest.mark.parametrize(
    ("tool_name", "builds", "quality"),
    [
        ("build_scene", 1, 0),
        ("optimize_portable_asset", 1, 0),
        ("convert_portable_materials", 1, 0),
        ("run_visual_qa", 0, 1),
        ("run_geometry_multiview_review", 0, 1),
        ("validate_portable_package", 0, 1),
        ("evaluate_candidate_revision", 1, 1),
        ("build_portable_package", 0, 0),
        ("run_visual_diagnostics", 0, 0),
    ],
)
def test_v08_host_step_resource_mapping_is_exact(
    tool_name: str,
    builds: int,
    quality: int,
) -> None:
    """Map build-equivalent and authoritative quality steps without double charging companions."""

    result = classify_production_step_resources(_step(tool_name))
    assert result.delta.total_blender_builds == builds
    assert result.delta.total_quality_evaluations == quality
    assert result.charge_timing == "before_execution"


def test_background_fit_reserves_every_bounded_attempt() -> None:
    """Charge each possible low-resolution fit build/evaluation before its compound host step."""

    result = classify_production_step_resources(
        _step("fit_background_exterior", max_attempts=2)
    )
    assert result.delta.total_blender_builds == 2
    assert result.delta.total_quality_evaluations == 2
    with pytest.raises(ValueError, match="zero to two"):
        classify_production_step_resources(
            _step("fit_background_exterior", max_attempts=3)
        )


def test_unknown_or_non_host_step_fails_closed() -> None:
    """Reject unclassified future tools and non-host boundaries before execution."""

    with pytest.raises(ValueError, match="unclassified"):
        classify_production_step_resources(_step("future_expensive_tool"))
    agent_step = _step("build_scene").model_copy(update={"execution_mode": "agent"})
    with pytest.raises(ValueError, match="host workflow steps only"):
        classify_production_step_resources(agent_step)


def test_resource_reservation_consumes_before_host_execution() -> None:
    """Reserve one action and the exact build counter in a hash-bound contract."""

    result = reserve_production_step_resources(
        step=_step("build_scene"),
        budget=_budget(),
        usage=BudgetUsage(),
        contract_id="reservation-build-scene",
        job_id="aq_production_budget",
        workflow_id="wf-production-budget",
        dispatch_id="dispatch-production-budget",
        session_id="session-production-budget",
        input_sha256=ZERO,
        source_fingerprint=ONE,
        provenance=[_artifact("workflows/wf-production-budget/plan.json")],
        workflow_plan=_artifact("workflows/wf-production-budget/plan.json"),
        budget_authority=_artifact("autonomy/session-production-budget/budget.json"),
        workflow_input_fingerprint=TWO,
        created_at=NOW,
    )
    assert result.allowed is True
    assert result.reservation is not None
    assert result.usage.total_actions == 1
    assert result.usage.total_blender_builds == 1


def test_resource_reservation_routes_to_review_when_budget_is_exhausted() -> None:
    """Refuse host execution when its exact build dimension has no remaining allowance."""

    usage = BudgetUsage(total_blender_builds=1)
    result = reserve_production_step_resources(
        step=_step("build_scene"),
        budget=_budget(total_blender_builds=1),
        usage=usage,
        contract_id="reservation-exhausted",
        job_id="aq_production_budget",
        workflow_id="wf-production-budget",
        dispatch_id="dispatch-production-budget",
        session_id="session-production-budget",
        input_sha256=ZERO,
        source_fingerprint=ONE,
        provenance=[_artifact("workflows/wf-production-budget/plan.json")],
        workflow_plan=_artifact("workflows/wf-production-budget/plan.json"),
        budget_authority=_artifact("autonomy/session-production-budget/budget.json"),
        workflow_input_fingerprint=TWO,
        created_at=NOW,
    )
    assert result.allowed is False
    assert result.route_to_review is True
    assert result.exhausted_dimension == "total_blender_builds"
    assert result.usage == usage


def _production_receipt_fixture(
    tmp_path: Path,
    *,
    controller_status: str,
    step_status: str,
    completion_fingerprint: str | None = None,
    include_output: bool = False,
) -> tuple[Path, object, object, AutonomyArtifact, dict[str, object]]:
    """Create exact reservation, controller snapshot, and optional output evidence."""

    root = tmp_path / "job"
    root.mkdir()
    workflow_plan_path = root / "workflows" / "wf-production-budget" / "plan.json"
    workflow_plan_path.parent.mkdir(parents=True)
    workflow_plan_path.write_text("{}\n", encoding="utf-8")
    budget_path = root / "production" / "autonomy" / "session" / "budget.json"
    budget_path.parent.mkdir(parents=True)
    budget_path.write_text("{}\n", encoding="utf-8")
    decision = reserve_production_step_resources(
        step=_step("build_scene"),
        budget=_budget(),
        usage=BudgetUsage(),
        contract_id="reservation-receipt",
        job_id="aq_production_budget",
        workflow_id="wf-production-budget",
        dispatch_id="dispatch-production-budget",
        session_id="session-production-budget",
        input_sha256=ZERO,
        source_fingerprint=ONE,
        provenance=[artifact_for(root, workflow_plan_path)],
        workflow_plan=artifact_for(root, workflow_plan_path),
        budget_authority=artifact_for(root, budget_path),
        workflow_input_fingerprint=TWO,
        created_at=NOW,
    )
    assert decision.reservation is not None
    reservation_path = budget_path.parent / "reservation.json"
    reservation_path.write_text(
        decision.reservation.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    artifacts: list[ArtifactFreshness] = []
    if include_output:
        output_path = root / "outputs" / "scene.blend"
        output_path.parent.mkdir(parents=True)
        output_path.write_bytes(b"exact-output")
        artifacts.append(
            ArtifactFreshness(
                artifact_id="test.output",
                path="outputs/scene.blend",
                sha256=hashlib.sha256(output_path.read_bytes()).hexdigest(),
                integrity="valid",
                currency="current",
                verification="verified",
                reason="exact completed output",
            )
        )
    workflow_status = {
        "blocked": "blocked",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(controller_status, "completed")
    workflow_state = WorkflowState(
        workflow_id="wf-production-budget",
        job_id="aq_production_budget",
        plan_sha256=ONE,
        request_sha256=TWO,
        status=workflow_status,  # type: ignore[arg-type]
        milestone="completed" if workflow_status == "completed" else "created",
        current_step_id=(
            None if workflow_status == "completed" else "test.build_scene"
        ),
        steps=[
            WorkflowStepState(
                step_id="test.build_scene",
                status=step_status,  # type: ignore[arg-type]
                input_fingerprint=TWO,
                completion_fingerprint=completion_fingerprint,
                artifacts=artifacts,
            )
        ],
        cancelled_reason=("fixture cancellation" if workflow_status == "cancelled" else None),
        created_at=NOW,
        updated_at=NOW,
    )
    dispatch_root = root / "production" / "dispatches" / "dispatch-production-budget"
    after_path = dispatch_root / "advance_states" / "0001-after.json"
    after_path.parent.mkdir(parents=True)
    after_path.write_text(workflow_state.model_dump_json(indent=2) + "\n", encoding="utf-8")
    advance_path = dispatch_root / "advances" / "0001-advance-0001.json"
    advance_path.parent.mkdir(parents=True)
    advance_path.write_text(json.dumps({"exact": True}) + "\n", encoding="utf-8")
    controller_result: dict[str, object] = {
        "state": {"status": controller_status},
        "advance_receipt": {
            "sequence": 1,
            "receipt_id": "advance-0001",
            "workflow_state_after": artifact_for(root, after_path).model_dump(mode="json"),
        },
    }
    state = SimpleNamespace(
        job_id="aq_production_budget",
        workflow_id="wf-production-budget",
        dispatch_id="dispatch-production-budget",
        session_id="session-production-budget",
        action_sequence=0,
    )
    return root, state, decision, artifact_for(root, reservation_path), controller_result


def test_completed_production_resource_receipt_requires_exact_completion(
    tmp_path: Path,
) -> None:
    """Reject a nominally successful controller return without completed output evidence."""

    root, state, decision, reservation, result = _production_receipt_fixture(
        tmp_path,
        controller_status="running",
        step_status="complete",
    )
    with pytest.raises(ValueError, match="completion evidence"):
        _record_production_resource_receipt(
            root,
            root / "production" / "autonomy" / "session",
            state,  # type: ignore[arg-type]
            decision,
            reservation,
            TWO,
            result,
        )


def test_completed_production_resource_receipt_binds_current_outputs(
    tmp_path: Path,
) -> None:
    """Record a completed resource receipt only with exact state and output hashes."""

    root, state, decision, reservation, result = _production_receipt_fixture(
        tmp_path,
        controller_status="running",
        step_status="complete",
        completion_fingerprint=ONE,
        include_output=True,
    )
    evidence = _record_production_resource_receipt(
        root,
        root / "production" / "autonomy" / "session",
        state,  # type: ignore[arg-type]
        decision,
        reservation,
        TWO,
        result,
    )
    receipt = ProductionResourceReceipt.model_validate_json(
        (root / evidence[-1].path).read_text(encoding="utf-8")
    )
    assert receipt.outcome == "completed"
    assert {item.path for item in receipt.outputs} >= {
        "outputs/scene.blend",
        "production/dispatches/dispatch-production-budget/advance_states/0001-after.json",
    }


@pytest.mark.parametrize(
    ("controller_status", "step_status", "expected"),
    [
        ("failed", "failed", "failed"),
        ("blocked", "blocked", "failed"),
        ("cancelled", "cancelled", "interrupted"),
    ],
)
def test_production_resource_receipt_preserves_noncompleted_after_state(
    tmp_path: Path,
    controller_status: str,
    step_status: str,
    expected: str,
) -> None:
    """Never label a failed, blocked, or cancelled controller after-state completed."""

    root, state, decision, reservation, result = _production_receipt_fixture(
        tmp_path,
        controller_status=controller_status,
        step_status=step_status,
    )
    evidence = _record_production_resource_receipt(
        root,
        root / "production" / "autonomy" / "session",
        state,  # type: ignore[arg-type]
        decision,
        reservation,
        TWO,
        result,
    )
    receipt = ProductionResourceReceipt.model_validate_json(
        (root / evidence[-1].path).read_text(encoding="utf-8")
    )
    assert receipt.outcome == expected


@pytest.mark.parametrize(
    ("code", "expected_actions", "builds"),
    [
        (
            "stale_portable_material_conversion",
            [
                "rebuild_portable_material_conversion",
                "rebuild_package",
                "rerun_clean_import_roundtrip",
            ],
            1,
        ),
        (
            "stale_derived_package",
            ["rebuild_package", "rerun_clean_import_roundtrip"],
            0,
        ),
        (
            "export_metadata_mismatch",
            ["reexport_package", "rerun_clean_import_roundtrip"],
            0,
        ),
        ("incomplete_roundtrip_receipt", ["rerun_clean_import_roundtrip"], 0),
    ],
)
def test_whitelisted_repair_is_budgeted_before_execution(
    code: str,
    expected_actions: list[str],
    builds: int,
) -> None:
    """Authorize only a known derived repair and reserve repair/round-trip costs exactly once."""

    decision = _classify_repair(_failure(code), BudgetUsage())
    assert decision.disposition == "repair"
    assert decision.repair_plan is not None
    assert decision.repair_plan.actions == expected_actions
    assert decision.budget_after.package_repairs == 1
    assert decision.budget_after.total_blender_builds == builds
    assert decision.budget_after.total_quality_evaluations == 1
    assert decision.budget_after.total_actions == 1


@pytest.mark.parametrize(
    "failure",
    [
        _failure("topology_failure"),
        _failure("missing_source_dependency"),
        _failure("bounds_mismatch"),
        _failure("stale_derived_package", deterministic=False),
        _failure("stale_derived_package", canonical_inputs_current=False),
    ],
)
def test_unsafe_or_unknown_package_failure_routes_to_review(
    failure: PackageRepairFailure,
) -> None:
    """Keep topology, dependency, ambiguity, and stale-source failures out of auto repair."""

    decision = _classify_repair(failure, BudgetUsage())
    assert decision.disposition == "review"
    assert decision.repair_plan is None
    assert decision.budget_after == decision.budget_before


def test_exhausted_package_repair_budget_routes_to_review() -> None:
    """Never exceed the exact package repair allowance even for a whitelisted recipe."""

    usage = BudgetUsage(package_repairs=1)
    decision = _classify_repair(_failure("stale_derived_package"), usage)
    assert decision.disposition == "review"
    assert decision.reason_code == "package_repair_budget_exhausted"
    assert decision.budget_after == usage


def test_runtime_preparation_binds_fresh_repair_id_and_exact_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make the safe runtime route and its exact one-repair reservation reachable."""

    root = tmp_path / "job"
    session_root = root / "production" / "autonomy" / "session-production-budget"
    attempt_path = root / "workflows" / "wf-production-budget" / "attempt.json"
    source_path = root / "optimization" / "runs" / "run-1" / "optimization_plan.json"
    attempt_path.parent.mkdir(parents=True)
    source_path.parent.mkdir(parents=True)
    attempt_path.write_text("{}\n", encoding="utf-8")
    source_path.write_text("{}\n", encoding="utf-8")
    attempt = SimpleNamespace(
        attempt_id="attempt-0001-runtime",
        input_fingerprint=ZERO,
    )
    source = SimpleNamespace(source=SimpleNamespace(source_fingerprint=TWO))
    workflow = SimpleNamespace(
        steps=[
            SimpleNamespace(
                step_id="portable.package",
                parameters={
                    "profile_id": "portable_gltf",
                    "run_id": "run-1",
                    "conversion_id": "conversion-1",
                    "package_id": "package-production-budget",
                },
            )
        ]
    )
    state = SimpleNamespace(
        job_id="aq_production_budget",
        workflow_id="wf-production-budget",
        dispatch_id="dispatch-production-budget",
        session_id="session-production-budget",
        budget_usage=BudgetUsage(),
    )
    monkeypatch.setattr(
        repair_runtime,
        "_latest_failed_attempt",
        lambda *_args: (attempt, attempt_path),
    )
    monkeypatch.setattr(
        repair_runtime,
        "_canonical_source",
        lambda *_args: (source, source_path),
    )
    monkeypatch.setattr(
        repair_runtime,
        "_machine_error_code",
        lambda *_args: (
            "stale_derived_package",
            True,
            ["exact derived package collision"],
        ),
    )

    prepared = prepare_package_repair(
        root,
        session_root,
        state,  # type: ignore[arg-type]
        _budget(),
        workflow,  # type: ignore[arg-type]
        failed_step_id="portable.package",
    )

    assert prepared.decision.disposition == "repair"
    assert prepared.decision.repair_plan is not None
    assert prepared.decision.repair_plan.package_id.endswith("-aqr01")
    assert prepared.decision.repair_plan.failure == prepared.failure_artifact
    assert prepared.decision.budget_after.package_repairs == 1


def test_runtime_preparation_reports_exact_package_repair_exhaustion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose package_repair_budget_exhausted through the real runtime preparation path."""

    root = tmp_path / "job"
    session_root = root / "production" / "autonomy" / "session-production-budget"
    attempt_path = root / "workflows" / "wf-production-budget" / "attempt.json"
    source_path = root / "optimization" / "runs" / "run-1" / "optimization_plan.json"
    attempt_path.parent.mkdir(parents=True)
    source_path.parent.mkdir(parents=True)
    attempt_path.write_text("{}\n", encoding="utf-8")
    source_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        repair_runtime,
        "_latest_failed_attempt",
        lambda *_args: (
            SimpleNamespace(attempt_id="attempt-0002-runtime", input_fingerprint=ZERO),
            attempt_path,
        ),
    )
    monkeypatch.setattr(
        repair_runtime,
        "_canonical_source",
        lambda *_args: (
            SimpleNamespace(source=SimpleNamespace(source_fingerprint=TWO)),
            source_path,
        ),
    )
    monkeypatch.setattr(
        repair_runtime,
        "_machine_error_code",
        lambda *_args: ("stale_derived_package", True, ["exact collision"]),
    )
    workflow = SimpleNamespace(
        steps=[
            SimpleNamespace(
                step_id="portable.package",
                parameters={
                    "profile_id": "portable_gltf",
                    "run_id": "run-1",
                    "conversion_id": "conversion-1",
                    "package_id": "package-production-budget",
                },
            )
        ]
    )
    state = SimpleNamespace(
        job_id="aq_production_budget",
        workflow_id="wf-production-budget",
        dispatch_id="dispatch-production-budget",
        session_id="session-production-budget",
        budget_usage=BudgetUsage(package_repairs=1),
    )

    prepared = prepare_package_repair(
        root,
        session_root,
        state,  # type: ignore[arg-type]
        _budget(),
        workflow,  # type: ignore[arg-type]
        failed_step_id="portable.package",
    )

    assert prepared.decision.disposition == "review"
    assert prepared.decision.reason_code == "package_repair_budget_exhausted"
    assert prepared.plan_artifact is None


def test_runtime_execution_uses_fresh_package_and_passed_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept one repair only after a fresh package ID receives a passed clean import."""

    root = tmp_path / "job"
    session_root = root / "production" / "autonomy" / "session-production-budget"
    evidence_root = session_root / "package_repairs" / "r01-attempt-runtime"
    evidence_root.mkdir(parents=True)
    failure_path = evidence_root / "failure.json"
    failure_path.write_text("{}\n", encoding="utf-8")
    failure_artifact = artifact_for(root, failure_path)
    delta = ProductionResourceDelta(
        total_quality_evaluations=1,
        package_repairs=1,
    )
    budget_after = BudgetUsage(
        total_actions=1,
        total_quality_evaluations=1,
        package_repairs=1,
    )
    plan = PackageRepairPlan(
        contract_id="package-repair-plan-runtime",
        job_id="aq_production_budget",
        workflow_id="wf-production-budget",
        dispatch_id="dispatch-production-budget",
        input_sha256=ZERO,
        source_fingerprint=ONE,
        producer="test",
        producer_version="0.1.0",
        provenance=[failure_artifact],
        created_at=NOW,
        session_id="session-production-budget",
        failure=failure_artifact,
        profile_id="portable_gltf",
        package_id="package-production-budget-aqr01",
        repair_index=1,
        actions=["rebuild_package", "rerun_clean_import_roundtrip"],
        delta=delta,
        budget_before=BudgetUsage(),
        budget_after=budget_after,
        canonical_input_fingerprint=TWO,
    )
    plan_path = evidence_root / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    plan_artifact = artifact_for(root, plan_path)
    workflow = SimpleNamespace(
        steps=[
            SimpleNamespace(
                step_id="portable.package",
                parameters={
                    "profile_id": "portable_gltf",
                    "run_id": "run-1",
                    "conversion_id": "conversion-1",
                    "package_id": "package-production-budget",
                },
            )
        ]
    )
    state = SimpleNamespace(
        job_id="aq_production_budget",
        workflow_id="wf-production-budget",
        dispatch_id="dispatch-production-budget",
        session_id="session-production-budget",
    )
    source = SimpleNamespace(source=SimpleNamespace(source_fingerprint=TWO))
    monkeypatch.setattr(
        repair_runtime,
        "_canonical_source",
        lambda *_args: (source, root / "optimization_plan.json"),
    )
    package_path = (
        root
        / "exports"
        / "packages"
        / "portable_gltf"
        / plan.package_id
        / "package_manifest.json"
    )
    roundtrip_path = (
        root
        / "optimization"
        / "runs"
        / "run-1"
        / "roundtrip"
        / plan.package_id
        / "roundtrip_validation.json"
    )

    def _fake_package(*_args, **_kwargs) -> None:
        """Write one fresh repair-owned package manifest fixture."""

        package_path.parent.mkdir(parents=True)
        package_path.write_text("{}\n", encoding="utf-8")

    def _fake_roundtrip(*_args, **_kwargs) -> None:
        """Write one fresh repair-owned round-trip fixture."""

        roundtrip_path.parent.mkdir(parents=True)
        roundtrip_path.write_text("{}\n", encoding="utf-8")

    def _parsed_roundtrip(_payload: str) -> SimpleNamespace:
        """Bind the parsed round-trip fixture to the exact package hash."""

        package_artifact = artifact_for(root, package_path)
        return SimpleNamespace(
            ok=True,
            status="passed",
            package_manifest=SimpleNamespace(
                path=package_artifact.path,
                sha256=package_artifact.sha256,
            ),
        )

    monkeypatch.setattr(repair_runtime, "package_asset", _fake_package)
    monkeypatch.setattr(repair_runtime, "validate_asset_package", _fake_roundtrip)
    monkeypatch.setattr(
        repair_runtime.ExportPackageManifest,
        "model_validate_json",
        lambda _payload: SimpleNamespace(package_id=plan.package_id, run_id="run-1"),
    )
    monkeypatch.setattr(
        repair_runtime.RoundTripValidation,
        "model_validate_json",
        _parsed_roundtrip,
    )

    executed = execute_package_repair(
        root,
        session_root,
        state,  # type: ignore[arg-type]
        workflow,  # type: ignore[arg-type]
        plan_artifact=plan_artifact,
    )

    assert executed.receipt.package_accepted is True
    assert executed.receipt.roundtrip_passed is True
    assert executed.package_artifact is not None
    assert executed.roundtrip_artifact is not None
    assert executed.package_artifact.path.endswith(
        "package-production-budget-aqr01/package_manifest.json"
    )


def test_repair_receipt_cannot_fake_package_acceptance() -> None:
    """Require exact package and passed round-trip artifacts before acceptance can be true."""

    common: dict[str, object] = {
        "contract_id": "repair-receipt-1",
        "job_id": "aq_production_budget",
        "workflow_id": "wf-production-budget",
        "dispatch_id": "dispatch-production-budget",
        "input_sha256": ZERO,
        "source_fingerprint": ONE,
        "producer": "test",
        "producer_version": "0.1.0",
        "provenance": [_artifact("autonomy/session-production-budget/repair_plan.json")],
        "created_at": NOW,
        "session_id": "session-production-budget",
        "repair_plan": _artifact("autonomy/session-production-budget/repair_plan.json"),
        "failure": _artifact("workflows/wf-production-budget/attempt.json"),
        "host_attempts": [_artifact("workflows/wf-production-budget/repair_attempt.json")],
        "canonical_input_fingerprint_before": TWO,
        "canonical_input_fingerprint_after": TWO,
        "reserved_delta": ProductionResourceDelta(
            package_repairs=1,
            total_quality_evaluations=1,
        ),
        "budget_before": BudgetUsage(),
        "budget_after": BudgetUsage(
            package_repairs=1,
            total_quality_evaluations=1,
            total_actions=1,
        ),
        "outcome": "repaired",
        "roundtrip_passed": True,
        "package_accepted": True,
        "completed_at": NOW,
        "notes": ["fixture"],
    }
    with pytest.raises(ValidationError, match="package acceptance"):
        PackageRepairReceipt.model_validate(common)
    valid = PackageRepairReceipt.model_validate(
        {
            **common,
            "package_manifest_after": _artifact("exports/package/package_manifest.json"),
            "roundtrip_validation_after": _artifact(
                "optimization/runs/run-1/roundtrip/roundtrip_validation.json"
            ),
            "roundtrip_package_manifest_sha256": ZERO,
        }
    )
    assert valid.package_accepted is True
    with pytest.raises(ValidationError, match="package acceptance"):
        PackageRepairReceipt.model_validate(
            {
                **valid.model_dump(),
                "roundtrip_package_manifest_sha256": ONE,
            }
        )
    with pytest.raises(ValidationError, match="cannot change canonical"):
        PackageRepairReceipt.model_validate(
            {
                **valid.model_dump(),
                "canonical_input_fingerprint_after": ZERO,
            }
        )


def test_new_contracts_forbid_extra_fields() -> None:
    """Reject undeclared receipt fields so repair authority cannot be broadened."""

    payload = classify_production_step_resources(_step("build_scene")).model_dump()
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProductionStepResourceClassification.model_validate(
            {**payload, "unexpected": True}
        )
