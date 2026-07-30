"""Pure contract and policy tests for bounded V0.6 visual convergence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from codex_blender_modeler.auto_revision.convergence_policy import (
    ConvergenceCandidateSelection,
    select_convergence_candidates,
    validate_convergence_activation,
    validate_iteration_receipt_chain,
)
from codex_blender_modeler.auto_revision.convergence_session_models import (
    ConvergencePathLimit,
    HashBoundConvergenceArtifact,
    VisualConvergenceApproval,
    VisualConvergenceCancellation,
    VisualConvergenceHostSafetyEnvelope,
    VisualConvergenceIteration,
    VisualConvergenceIterationAuthorization,
    VisualConvergencePlan,
    VisualConvergenceReport,
    VisualConvergenceReportManifest,
)
from codex_blender_modeler.auto_revision.models import (
    RevisionCandidate,
    RevisionCandidates,
)

H0 = "0" * 64
H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64
H6 = "6" * 64
H7 = "7" * 64
H8 = "8" * 64
H9 = "9" * 64


def _plan(**updates: Any) -> VisualConvergencePlan:
    """Build a compact valid geometry-only convergence plan."""

    payload: dict[str, Any] = {
        "session_id": "session-001",
        "job_id": "asset-001",
        "input_fingerprint": H0,
        "initial_input_hashes": {"reference.png": H9},
        "initial_scene_spec_sha256": H1,
        "initial_qa_run_id": "run-001",
        "initial_qa_report_sha256": H2,
        "initial_candidates_sha256": H5,
        "initial_build_fingerprint": H6,
        "initial_build_provenance_sha256": H7,
        "host_safety_envelope_sha256": H8,
        "initial_constraints_present": False,
        "initial_constraints_sha256": None,
        "camera_fingerprint": H3,
        "scoring_version": "semantic_bbox_v2",
        "initial_direct_score": 0.6,
        "initial_silhouette_iou": 0.55,
        "target_direct_score": 0.8,
        "target_silhouette_iou": 0.75,
        "minimum_iteration_gain": 0.005,
        "minimum_candidate_confidence": 0.75,
        "max_iterations": 3,
        "max_candidate_groups_per_iteration": 3,
        "max_candidates_per_iteration": 6,
        "max_changed_ids_per_iteration": 4,
        "allowed_target_ids": ["asset.body", "asset.trim", "asset.custom", "mat.body"],
        "locked_target_ids": [],
        "custom_mesh_target_ids": ["asset.custom"],
        "path_limits": [
            ConvergencePathLimit(
                path_family="transform.location",
                allowed_operations=["set", "add"],
                max_absolute_delta=0.5,
            ),
            ConvergencePathLimit(
                path_family="geometry.dimensions",
                allowed_operations=["set", "add", "multiply"],
                max_absolute_delta=1.0,
                max_relative_delta=0.25,
            ),
        ],
        "created_at": "2026-07-30T00:00:00+00:00",
    }
    payload.update(updates)
    return VisualConvergencePlan.model_validate(payload)


def _approval(plan: VisualConvergencePlan, **updates: Any) -> VisualConvergenceApproval:
    """Build one immutable activation bound to the fixture plan."""

    payload: dict[str, Any] = {
        "approval_id": "approval-001",
        "session_id": plan.session_id,
        "job_id": plan.job_id,
        "plan_sha256": H4,
        "input_fingerprint": plan.input_fingerprint,
        "initial_scene_spec_sha256": plan.initial_scene_spec_sha256,
        "initial_qa_report_sha256": plan.initial_qa_report_sha256,
        "initial_candidates_sha256": plan.initial_candidates_sha256,
        "initial_build_fingerprint": plan.initial_build_fingerprint,
        "initial_build_provenance_sha256": plan.initial_build_provenance_sha256,
        "host_safety_envelope_sha256": plan.host_safety_envelope_sha256,
        "initial_constraints_present": plan.initial_constraints_present,
        "initial_constraints_sha256": plan.initial_constraints_sha256,
        "camera_fingerprint": plan.camera_fingerprint,
        "approval_note": "Approve the exact bounded geometry envelope.",
        "approved_at": "2026-07-30T00:01:00+00:00",
    }
    payload.update(updates)
    return VisualConvergenceApproval.model_validate(payload)


def _terminal_report(**updates: Any) -> VisualConvergenceReport:
    """Build one compact valid target-reached terminal report."""

    payload: dict[str, Any] = {
        "session_id": "session-001",
        "job_id": "asset-001",
        "plan_sha256": H4,
        "approval_sha256": H5,
        "input_fingerprint": H0,
        "camera_fingerprint": H3,
        "scoring_version": "semantic_bbox_v2",
        "initial_scene_spec_sha256": H1,
        "initial_scene_spec_snapshot": {
            "relative_path": "qa/convergence/session-001/initial_scene_spec.json",
            "sha256": H1,
        },
        "final_scene_spec_sha256": H6,
        "final_scene_spec_snapshot": {
            "relative_path": "qa/convergence/session-001/final_scene_spec.json",
            "sha256": H6,
        },
        "initial_qa_report_sha256": H2,
        "initial_candidates_sha256": H5,
        "final_qa_report_sha256": H9,
        "initial_build_fingerprint": H6,
        "final_build_fingerprint": H7,
        "initial_build_provenance_snapshot": {
            "relative_path": (
                "qa/convergence/session-001/initial_build_provenance.json"
            ),
            "sha256": H7,
        },
        "final_build_provenance_snapshot": {
            "relative_path": "qa/convergence/session-001/final_build_provenance.json",
            "sha256": H8,
        },
        "initial_constraints_present": False,
        "initial_constraints_sha256": None,
        "initial_direct_score": 0.6,
        "final_direct_score": 0.82,
        "target_direct_score": 0.8,
        "initial_silhouette_iou": 0.55,
        "final_silhouette_iou": 0.76,
        "target_silhouette_iou": 0.75,
        "iteration_receipts": [],
        "accepted_iterations": 0,
        "rolled_back_iterations": 0,
        "termination_reason": "target_reached",
        "target_reached": True,
        "manual_review_required": False,
        "reasons": ["Fixture terminal outcome."],
        "started_at": "2026-07-30T00:00:00+00:00",
        "completed_at": "2026-07-30T00:03:00+00:00",
    }
    payload.update(updates)
    return VisualConvergenceReport.model_validate(payload)


def _candidate(
    candidate_id: str,
    *,
    target_type: str = "object",
    target_id: str | None = "asset.body",
    path: list[str | int] | None = None,
    op: str = "add",
    value: Any = 0.1,
    confidence: float = 0.9,
    applicability: str = "approval_required",
    evidence_sources: list[str] | None = None,
    finding_id: str | None = None,
) -> RevisionCandidate:
    """Build one strict revision candidate with configurable policy attributes."""

    return RevisionCandidate.model_validate(
        {
            "id": candidate_id,
            "finding_id": finding_id or f"finding.{candidate_id}",
            "target_type": target_type,
            "target_id": target_id,
            "path": path or ["transform", "location", 0],
            "op": op,
            "value": value,
            "reason": "fixture candidate",
            "evidence_sources": evidence_sources or ["direct_reference"],
            "confidence": confidence,
            "applicability": applicability,
            "acceptance_criteria": ["Improve direct fixed-camera evidence."],
        }
    )


def _bundle(items: list[RevisionCandidate]) -> RevisionCandidates:
    """Bind candidate fixtures to the exact current SceneSpec and QA report."""

    return RevisionCandidates(
        job_id="asset-001",
        base_spec_sha256=H1,
        camera_fingerprint=H3,
        source_report_sha256=H2,
        candidates=items,
    )


def _select(
    plan: VisualConvergencePlan,
    items: list[RevisionCandidate],
    baselines: dict[str, Any],
):
    """Run deterministic selection with exact fixture hashes."""

    return select_convergence_candidates(
        plan,
        _bundle(items),
        candidates_sha256=H5,
        expected_base_scene_spec_sha256=H1,
        expected_source_qa_report_sha256=H2,
        baseline_values=baselines,
    )


def test_plan_is_strict_bounded_and_requires_explicit_material_authority() -> None:
    """Plans fail closed on extra data, oversized budgets, and implicit material paths."""

    with pytest.raises(ValidationError, match="Extra inputs"):
        _plan(unknown_permission=True)
    with pytest.raises(ValidationError, match="less than or equal to 5"):
        _plan(max_iterations=6)
    with pytest.raises(ValidationError, match="allow_material_edits"):
        _plan(
            path_limits=[
                ConvergencePathLimit(
                    path_family="material.roughness",
                    allowed_operations=["set"],
                    max_absolute_delta=0.1,
                )
            ]
        )
    with pytest.raises(ValidationError, match="cannot be lower"):
        _plan(target_direct_score=0.5)


def test_plan_accepts_canonical_timestamp_qa_run_ids() -> None:
    """Accept the uppercase T/Z format emitted by the V0.6 QA service."""

    plan = _plan(initial_qa_run_id="20260730T104338.814082Z-0cc1d59d53c9")
    assert plan.initial_qa_run_id == "20260730T104338.814082Z-0cc1d59d53c9"


def test_host_safety_envelope_is_strict_and_never_authorizes_materials() -> None:
    """Reject extra authority, unlocked interiors, duplicate paths, and material edits."""

    payload: dict[str, Any] = {
        "session_id": "session-001",
        "job_id": "asset-001",
        "initial_scene_spec_sha256": H1,
        "initial_qa_report_sha256": H2,
        "initial_candidates_sha256": H3,
        "camera_fingerprint": H4,
        "scoring_version": "semantic_bbox_v2",
        "initial_direct_score": 0.6,
        "initial_silhouette_iou": 0.55,
        "target_direct_score": 0.8,
        "target_silhouette_iou": 0.75,
        "minimum_iteration_gain": 0.005,
        "minimum_candidate_confidence": 0.8,
        "max_iterations": 3,
        "max_candidate_groups_per_iteration": 3,
        "max_candidates_per_iteration": 12,
        "max_changed_ids_per_iteration": 6,
        "allowed_target_ids": ["asset.body"],
        "locked_target_ids": ["asset.interior.room"],
        "custom_mesh_target_ids": [],
        "interior_target_ids": ["asset.interior.room"],
        "manual_candidate_ids": [],
        "path_limits": [
            {
                "path_family": "transform.location",
                "allowed_operations": ["add"],
                "max_absolute_delta": 0.5,
            }
        ],
        "allow_material_edits": False,
        "camera_locked": True,
        "generated_target_policy": "advisory_only",
        "constraint_regression_policy": "forbid",
    }
    envelope = VisualConvergenceHostSafetyEnvelope.model_validate(payload)
    assert envelope.allowed_target_ids == ["asset.body"]

    with pytest.raises(ValidationError, match="Extra inputs"):
        VisualConvergenceHostSafetyEnvelope.model_validate(
            {**payload, "unexpected_authority": True}
        )
    with pytest.raises(ValidationError, match="must remain locked"):
        VisualConvergenceHostSafetyEnvelope.model_validate(
            {**payload, "locked_target_ids": []}
        )
    with pytest.raises(ValidationError, match="cannot authorize material paths"):
        VisualConvergenceHostSafetyEnvelope.model_validate(
            {
                **payload,
                "path_limits": [
                    {
                        "path_family": "material.roughness",
                        "allowed_operations": ["set"],
                        "max_absolute_delta": 0.1,
                    }
                ],
            }
        )


def test_activation_is_immutable_and_exact_plan_hash_bound() -> None:
    """One activation authorizes only its exact plan and immutable initial evidence."""

    plan = _plan()
    approval = _approval(plan)
    validate_convergence_activation(plan, approval, plan_sha256=H4)
    with pytest.raises(ValueError, match="plan_sha256"):
        validate_convergence_activation(plan, approval, plan_sha256=H5)
    with pytest.raises(ValidationError, match="Input should be 'active'"):
        _approval(plan, status="closed")


def test_policy_rejects_every_candidate_outside_the_geometry_envelope() -> None:
    """Manual, advisory, camera, material, custom-mesh, path, and delta edits fail closed."""

    candidates = [
        _candidate("manual", applicability="manual_required"),
        _candidate(
            "generated",
            applicability="manual_required",
            evidence_sources=["generated_target"],
        ),
        _candidate("camera", target_type="camera", target_id=None, path=["location"]),
        _candidate(
            "material",
            target_type="material",
            target_id="mat.body",
            path=["roughness"],
            op="set",
            value=0.5,
        ),
        _candidate(
            "custom",
            target_id="asset.custom",
            path=["geometry", "dimensions", 0],
        ),
        _candidate("unknown-target", target_id="asset.unknown"),
        _candidate("unknown-path", path=["geometry", "profile", 0, 0]),
        _candidate("large-delta", value=0.75),
        _candidate("low-confidence", confidence=0.5),
    ]
    baselines = {item.id: 0.0 for item in candidates}
    selection = _select(_plan(), candidates, baselines)
    assert selection.selected_candidate_ids == []
    assert {item.candidate_id: item.code for item in selection.rejected} == {
        "camera": "target_type_not_allowed",
        "custom": "custom_mesh_geometry",
        "generated": "generated_target_only",
        "large-delta": "absolute_delta_exceeded",
        "low-confidence": "confidence_below_threshold",
        "manual": "manual_required",
        "material": "material_edits_disabled",
        "unknown-path": "path_not_allowed",
        "unknown-target": "target_not_allowed",
    }


def test_policy_selects_deterministically_and_resolves_path_conflicts() -> None:
    """Candidate order cannot change priority, conflict resolution, or selection hash."""

    lower = _candidate("lower", confidence=0.8, value=0.1)
    higher = _candidate("higher", confidence=0.95, value=0.2)
    independent = _candidate(
        "independent",
        target_id="asset.trim",
        path=["transform", "location", 1],
        value=-0.15,
        confidence=0.85,
    )
    candidates = [lower, higher, independent]
    baselines = {item.id: 0.0 for item in candidates}
    forward = _select(_plan(), candidates, baselines)
    backward = _select(_plan(), list(reversed(candidates)), baselines)
    assert forward.selected_candidate_ids == ["higher", "independent"]
    assert forward.selection_sha256 == backward.selection_sha256
    assert {item.candidate_id: item.code for item in forward.rejected} == {
        "lower": "candidate_conflict"
    }


def test_policy_never_partially_selects_a_coherent_group() -> None:
    """One invalid member rejects every member of a direct group-position candidate set."""

    group_id = "direct.group_position.vehicle"
    first = _candidate(
        "group-a",
        target_id="asset.body",
        finding_id=group_id,
        value=0.1,
    )
    second = _candidate(
        "group-b",
        target_id="asset.trim",
        finding_id=group_id,
        value=0.1,
    )
    selection = _select(_plan(), [first, second], {"group-a": 0.0})
    assert selection.selected_candidate_ids == []
    assert {item.code for item in selection.rejected} == {"partial_group_selection"}


def test_iteration_authorization_binds_exact_host_policy_selection() -> None:
    """The host authorization cannot omit exact selection and compiled-plan hashes."""

    authorization = VisualConvergenceIterationAuthorization(
        authorization_id="authorization-001",
        session_id="session-001",
        job_id="asset-001",
        iteration_index=1,
        plan_sha256=H4,
        approval_sha256=H5,
        base_scene_spec_sha256=H1,
        source_qa_report_sha256=H2,
        candidates_sha256=H3,
        source_build_fingerprint=H8,
        selection_sha256=H6,
        compiled_plan_sha256=H7,
        selected_candidate_ids=["candidate-001"],
        created_at="2026-07-30T00:02:00+00:00",
    )
    assert authorization.issued_by == "host_policy"
    with pytest.raises(ValidationError, match="must be unique"):
        authorization.model_copy(
            update={"selected_candidate_ids": ["candidate-001", "candidate-001"]}
        ).model_validate(
            authorization.model_copy(
                update={"selected_candidate_ids": ["candidate-001", "candidate-001"]}
            ).model_dump()
        )


def _accepted_iteration(
    *,
    index: int,
    base_hash: str,
    result_hash: str,
    previous_hash: str | None,
    source_qa_run_id: str | None = None,
    source_qa_report_sha256: str | None = None,
    source_candidates_sha256: str | None = None,
    source_build_fingerprint: str | None = None,
) -> VisualConvergenceIteration:
    """Build one accepted immutable iteration receipt."""

    if index == 1:
        source_qa_run_id = source_qa_run_id or "run-001"
        source_qa_report_sha256 = source_qa_report_sha256 or H2
        source_candidates_sha256 = source_candidates_sha256 or H5
        source_build_fingerprint = source_build_fingerprint or H6
    else:
        source_qa_run_id = source_qa_run_id or f"run-result-{index - 1}"
        source_qa_report_sha256 = source_qa_report_sha256 or H9
        source_candidates_sha256 = source_candidates_sha256 or H0
        source_build_fingerprint = source_build_fingerprint or H9
    return VisualConvergenceIteration(
        session_id="session-001",
        job_id="asset-001",
        iteration_index=index,
        plan_sha256=H4,
        approval_sha256=H5,
        previous_iteration_receipt_sha256=previous_hash,
        input_fingerprint=H0,
        base_scene_spec_sha256=base_hash,
        base_scene_spec_snapshot_sha256=base_hash,
        source_qa_run_id=source_qa_run_id,
        source_qa_report_sha256=source_qa_report_sha256,
        candidates_sha256=source_candidates_sha256,
        source_build_fingerprint=source_build_fingerprint,
        selection_sha256=H6,
        selected_candidate_ids=[f"candidate-{index}"],
        compiled_plan_sha256=H7,
        execution_authorization_sha256=H8,
        result_scene_spec_sha256=result_hash,
        result_qa_run_id=f"run-result-{index}",
        result_qa_report_sha256=H9,
        result_candidates_sha256=H0,
        result_build_fingerprint=H9,
        result_build_provenance_sha256=H5,
        before_constraints_sha256=H3,
        after_constraints_sha256=H4,
        before_direct_score=0.6,
        after_direct_score=0.7,
        before_silhouette_iou=0.55,
        after_silhouette_iou=0.65,
        score_delta=0.1,
        changed_ids=["asset.body"],
        canonical_scene_spec_sha256=result_hash,
        status="accepted",
        reason_codes=["improved"],
        completed_at="2026-07-30T00:03:00+00:00",
    )


def test_iteration_receipts_form_an_exact_hash_chain() -> None:
    """Receipt order must preserve plan, approval, predecessor, and canonical base hashes."""

    plan = _plan()
    approval = _approval(plan, plan_sha256=H4)
    first = _accepted_iteration(index=1, base_hash=H1, result_hash=H6, previous_hash=None)
    second = _accepted_iteration(index=2, base_hash=H6, result_hash=H7, previous_hash=H8)
    validate_iteration_receipt_chain(
        plan,
        approval,
        plan_sha256=H4,
        approval_sha256=H5,
        receipts=[(first, H8), (second, H9)],
    )
    broken = second.model_copy(update={"previous_iteration_receipt_sha256": H7})
    with pytest.raises(ValueError, match="predecessor"):
        validate_iteration_receipt_chain(
            plan,
            approval,
            plan_sha256=H4,
            approval_sha256=H5,
            receipts=[(first, H8), (broken, H9)],
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("source_qa_run_id", "run-spliced", "source QA chain"),
        ("source_qa_report_sha256", H8, "source QA chain"),
        ("candidates_sha256", H8, "source candidates chain"),
        ("source_build_fingerprint", H8, "source build chain"),
    ],
)
def test_iteration_receipt_chain_rejects_qa_candidate_and_build_splices(
    field: str,
    replacement: str,
    message: str,
) -> None:
    """A later receipt cannot splice another QA, candidate, or build lineage."""

    plan = _plan()
    approval = _approval(plan, plan_sha256=H4)
    first = _accepted_iteration(
        index=1,
        base_hash=H1,
        result_hash=H6,
        previous_hash=None,
    )
    second = _accepted_iteration(
        index=2,
        base_hash=H6,
        result_hash=H7,
        previous_hash=H8,
    )
    spliced = second.model_copy(update={field: replacement})
    with pytest.raises(ValueError, match=message):
        validate_iteration_receipt_chain(
            plan,
            approval,
            plan_sha256=H4,
            approval_sha256=H5,
            receipts=[(first, H8), (spliced, H9)],
        )


def test_new_executed_receipts_require_exact_base_and_constraint_snapshots() -> None:
    """New executed receipts reject a mismatched base or omitted constraint evidence."""

    valid = _accepted_iteration(
        index=1,
        base_hash=H1,
        result_hash=H6,
        previous_hash=None,
    )
    mismatched_base = valid.model_dump(mode="json")
    mismatched_base["base_scene_spec_snapshot_sha256"] = H2
    with pytest.raises(ValidationError, match="base SceneSpec snapshot must equal"):
        VisualConvergenceIteration.model_validate(mismatched_base)

    missing_constraints = valid.model_dump(mode="json")
    missing_constraints["before_constraints_sha256"] = None
    missing_constraints["after_constraints_sha256"] = None
    with pytest.raises(ValidationError, match="before/after constraint evidence"):
        VisualConvergenceIteration.model_validate(missing_constraints)


def test_accepted_receipt_cannot_claim_constraint_regressions_are_safe() -> None:
    """Changing only the regression counter cannot turn a regression into acceptance."""

    payload = _accepted_iteration(
        index=1,
        base_hash=H1,
        result_hash=H6,
        previous_hash=None,
    ).model_dump(mode="json")
    payload["constraint_regression_count"] = 1
    with pytest.raises(ValidationError, match="cannot contain regressions"):
        VisualConvergenceIteration.model_validate(payload)


def test_non_accepted_receipt_must_end_the_chain() -> None:
    """A rollback, failure, or manual stop cannot be followed by another iteration."""

    plan = _plan()
    approval = _approval(plan, plan_sha256=H4)
    first_payload = _accepted_iteration(
        index=1,
        base_hash=H1,
        result_hash=H6,
        previous_hash=None,
    ).model_dump(mode="json")
    first_payload.update(
        {
            "status": "rolled_back",
            "canonical_scene_spec_sha256": H1,
            "reason_codes": ["plateau"],
        }
    )
    first = VisualConvergenceIteration.model_validate(first_payload)
    second = _accepted_iteration(
        index=2,
        base_hash=H1,
        result_hash=H7,
        previous_hash=H5,
    )

    with pytest.raises(ValueError, match="must terminate"):
        validate_iteration_receipt_chain(
            plan,
            approval,
            plan_sha256=H4,
            approval_sha256=H5,
            receipts=[(first, H5), (second, H8)],
        )


def test_terminal_report_and_pdf_manifest_keep_json_authoritative() -> None:
    """Terminal and PDF contracts bind safe relative paths to exact immutable hashes."""

    report_artifact = HashBoundConvergenceArtifact(
        relative_path="qa/convergence/session-001/convergence_report.json",
        sha256=H6,
    )
    receipt_artifact = HashBoundConvergenceArtifact(
        relative_path="qa/convergence/session-001/iterations/001/receipt.json",
        sha256=H7,
    )
    report = VisualConvergenceReport(
        session_id="session-001",
        job_id="asset-001",
        plan_sha256=H4,
        approval_sha256=H5,
        input_fingerprint=H0,
        camera_fingerprint=H3,
        scoring_version="semantic_bbox_v2",
        initial_scene_spec_sha256=H1,
        initial_scene_spec_snapshot=HashBoundConvergenceArtifact(
            relative_path="qa/convergence/session-001/initial_scene_spec.json",
            sha256=H1,
        ),
        final_scene_spec_sha256=H6,
        final_scene_spec_snapshot=HashBoundConvergenceArtifact(
            relative_path="qa/convergence/session-001/final_scene_spec.json",
            sha256=H6,
        ),
        initial_qa_report_sha256=H2,
        initial_candidates_sha256=H3,
        final_qa_report_sha256=H9,
        initial_build_fingerprint=H4,
        final_build_fingerprint=H5,
        initial_build_provenance_snapshot=HashBoundConvergenceArtifact(
            relative_path=(
                "qa/convergence/session-001/initial_build_provenance.json"
            ),
            sha256=H7,
        ),
        final_build_provenance_snapshot=HashBoundConvergenceArtifact(
            relative_path="qa/convergence/session-001/final_build_provenance.json",
            sha256=H8,
        ),
        initial_constraints_present=False,
        initial_direct_score=0.6,
        final_direct_score=0.82,
        target_direct_score=0.8,
        initial_silhouette_iou=0.55,
        final_silhouette_iou=0.76,
        target_silhouette_iou=0.75,
        iteration_receipts=[receipt_artifact],
        accepted_iterations=1,
        rolled_back_iterations=0,
        termination_reason="target_reached",
        target_reached=True,
        manual_review_required=False,
        reasons=["Both direct-reference targets were reached."],
        started_at="2026-07-30T00:00:00+00:00",
        completed_at="2026-07-30T00:03:00+00:00",
    )
    assert report.target_reached is True
    manifest = VisualConvergenceReportManifest(
        session_id="session-001",
        job_id="asset-001",
        source_fingerprint=H0,
        report_json=report_artifact,
        pdf=HashBoundConvergenceArtifact(
            relative_path="qa/convergence/session-001/convergence_report.pdf",
            sha256=H8,
        ),
        sources=[report_artifact, receipt_artifact],
        generated_at="2026-07-30T00:04:00+00:00",
    )
    assert manifest.report_json.sha256 == H6
    with pytest.raises(ValidationError, match="parent segments"):
        HashBoundConvergenceArtifact(relative_path="../escape.json", sha256=H9)


def test_terminal_reason_and_target_reached_are_bidirectional() -> None:
    """Reject a target reason without reached scores and a reached target with another reason."""

    with pytest.raises(
        ValidationError,
        match="termination_reason must identify the same outcome",
    ):
        _terminal_report(
            final_direct_score=0.7,
            final_silhouette_iou=0.7,
            termination_reason="target_reached",
            target_reached=False,
        )
    with pytest.raises(
        ValidationError,
        match="termination_reason must identify the same outcome",
    ):
        _terminal_report(
            termination_reason="plateau",
            target_reached=True,
            manual_review_required=True,
        )


def test_terminal_manual_review_flag_matches_reason_semantics() -> None:
    """Reject a terminal report whose review flag contradicts its reason."""

    with pytest.raises(
        ValidationError,
        match="manual_review_required does not match",
    ):
        _terminal_report(
            final_direct_score=0.7,
            final_silhouette_iou=0.7,
            termination_reason="plateau",
            target_reached=False,
            manual_review_required=False,
        )
    report = _terminal_report(
        final_direct_score=0.7,
        final_silhouette_iou=0.7,
        termination_reason="cancelled",
        target_reached=False,
        manual_review_required=False,
        cancellation_receipt={
            "relative_path": "qa/convergence/session-001/cancellation_receipt.json",
            "sha256": H4,
        },
    )
    assert report.manual_review_required is False


def test_generated_convergence_schemas_match_strict_host_models() -> None:
    """Generated Draft 2020-12 schemas stay in parity with every public session model."""

    root = Path(__file__).resolve().parents[1]
    models = {
        "visual_convergence_plan.schema.json": VisualConvergencePlan,
        "visual_convergence_approval.schema.json": VisualConvergenceApproval,
        "visual_convergence_cancellation.schema.json": VisualConvergenceCancellation,
        "visual_convergence_host_safety_envelope.schema.json": (
            VisualConvergenceHostSafetyEnvelope
        ),
        "visual_convergence_selection.schema.json": ConvergenceCandidateSelection,
        "visual_convergence_iteration.schema.json": VisualConvergenceIteration,
        "visual_convergence_iteration_authorization.schema.json": (
            VisualConvergenceIterationAuthorization
        ),
        "visual_convergence_report.schema.json": VisualConvergenceReport,
        "visual_convergence_report_manifest.schema.json": (
            VisualConvergenceReportManifest
        ),
    }
    for filename, model in models.items():
        schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema == model.model_json_schema()
