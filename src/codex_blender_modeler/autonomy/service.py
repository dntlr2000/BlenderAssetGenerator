"""Bounded Autonomous Quality supervisor over an unchanged standard workflow."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter

from ..analysis import analyze_job_reference, validate_job_assembly
from ..blender_artifacts import (
    native_io_path,
    sha256_file,
    stable_json_digest,
    write_json_atomic,
)
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..handoff.models import DestinationHandoffManifest
from ..handoff.service import generate_destination_handoff, validate_destination_handoff
from ..integrated_quality import (
    EvidenceAvailability,
    HardGateEvidencePaths,
    HardGateRequirements,
    IntegratedQualityReport,
    ProducerIdentity,
    QualityArtifact,
    QualityGateProfile,
    QualityProvenance,
    apply_hard_gate_evidence,
    build_integrated_quality_report,
    discover_hard_gate_evidence_paths,
    write_integrated_quality_evidence,
)
from ..integrated_quality.blender_companion_service import (
    inspect_static_prop_authoring_companions,
)
from ..integrated_quality.candidate_ranking import rank_quality_candidates
from ..integrated_quality.models import (
    IntegratedQualityReportManifest,
    RankableQualityCandidate,
)
from ..materials.fidelity_models import MaterialFidelityReport
from ..materials.models import MaterialValidationReport
from ..optimization.models import MeshPreflightReport
from ..optimization.provenance import require_unchanged_source
from ..orchestration.models import WorkflowPlan, WorkflowState
from ..packaging.models import ExportPackageManifest, RoundTripValidation
from ..packaging.service import _verify_package_receipts
from ..production import (
    advance_delegated_production_controller,
    bind_asset_production_task,
    get_asset_production_dispatch_status,
    record_delegated_production_step,
)
from ..production.models import DelegatedWorkAssignment
from ..production.validation import production_artifact_digest
from ..qa.models import RenderPassManifest, VisualQAReport
from ..reference_evidence import run_reference_evidence
from ..reference_evidence.models import ReferenceEvidenceRunResult
from ..stabilization.models import PortableId
from ..workspace import (
    canonical_scene_spec_write_lock,
    job_dir,
    replace_scene_spec_if_current,
    validate_job_id,
)
from .authorization import (
    artifact_for,
    authorize_policy_gate,
    canonical_digest,
    persist_and_validate_policy_authorization,
    validate_policy_authorization,
)
from .budget import consume_budget, remaining_budget
from .candidate_evaluator import evaluate_structural_candidate
from .candidate_search import candidate_directory, preserve_best_known
from .cycle_detection import detect_state_cycle
from .failure_recovery import (
    HostAttemptFailure,
    HostAttemptIntent,
    HostFailureTerminalReceipt,
    begin_host_attempt,
    publish_failure_terminal_receipt,
    record_host_attempt_failure,
)
from .io import ensure_autonomy_path, load_json, write_immutable_json, write_mutable_projection
from .material_models import MaterialCandidatePromotionReceipt
from .material_rounds import (
    create_material_candidate_policy_target,
    prepare_material_candidate_round,
    promote_material_candidate_to_workflow_authored,
)
from .models import (
    AutonomyArtifact,
    AutonomyBudget,
    AutonomyControllerBinding,
    AutonomyIterationReceipt,
    AutonomyPlan,
    AutonomyProfile,
    AutonomyState,
    AutonomyTerminal,
    AutonomyTerminalIntent,
    BudgetUsage,
    CandidateAuthoringAssignment,
    CandidateCompletionMarker,
    CandidateEvaluation,
    CandidatePromotionReceipt,
    PolicyAuthorization,
    PolicyGateKind,
    PolicyGateTarget,
    ReviewBundleManifest,
    RootAuthorization,
    StateFingerprint,
    StructuralCandidateManifest,
    StructuralCandidatePlan,
    TerminalReason,
)
from .package_repair_runtime import (
    execute_package_repair,
    latest_accepted_package_repair,
    prepare_package_repair,
)
from .production_budget import (
    ProductionReservationDecision,
    ProductionResourceReceipt,
    reserve_production_step_resources,
)
from .transitions import build_transition_receipt, build_transition_state
from .worker import autonomy_session_lock, bounded_action_limit


def _utc_now() -> datetime:
    """Return one timezone-aware timestamp for immutable AQ evidence."""

    return datetime.now(UTC)


def _native_is_file(path: Path) -> bool:
    """Test one AQ file through a Windows extended-length path."""

    return os.path.isfile(native_io_path(path))


def _native_read_text(path: Path) -> str:
    """Read one AQ text artifact through a Windows extended-length path."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        return handle.read()


def _write_or_adopt_immutable_json(
    root: Path,
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Publish JSON once or adopt only the exact bytes left by an interrupted action."""

    expected_text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if os.linesep != "\n":
        expected_text = expected_text.replace("\n", os.linesep)
    expected = expected_text.encode("utf-8")
    if _native_is_file(path):
        if sha256_file(path) != hashlib.sha256(expected).hexdigest():
            raise ValueError(f"interrupted immutable evidence differs from current input: {path}")
        return
    write_immutable_json(root, path, payload)


def _portable_id(value: str, *, label: str) -> str:
    """Validate public autonomy identifiers before using them in filesystem paths."""

    try:
        return TypeAdapter(PortableId).validate_python(value)
    except ValueError as exc:
        raise ValueError(f"invalid {label}: {value}") from exc


def _session_root(job_root: Path, session_id: str, *, must_exist: bool = True) -> Path:
    """Resolve one session below its fixed production/autonomy ownership root."""

    checked = _portable_id(session_id, label="session_id")
    return ensure_autonomy_path(
        job_root,
        job_root / "production" / "autonomy" / checked,
        must_exist=must_exist,
    )


def _artifact_from_bytes(root: Path, relative_path: str, payload: bytes) -> AutonomyArtifact:
    """Create an exact artifact descriptor before an atomic directory publication."""

    path = (root / relative_path).resolve()
    try:
        normalized = path.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("autonomy artifact path escaped its job") from exc
    return AutonomyArtifact(
        path=normalized,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _verify_artifact(root: Path, artifact: AutonomyArtifact) -> Path:
    """Verify a contained file or deterministic directory against its exact digest."""

    path = ensure_autonomy_path(root, root / artifact.path, must_exist=True)
    if production_artifact_digest(path, containment_root=root) != artifact.sha256:
        raise ValueError(f"autonomy artifact is stale or tampered: {artifact.path}")
    return path


def _load_contracts(
    root: Path,
    session_root: Path,
) -> tuple[AutonomyPlan, AutonomyProfile, AutonomyBudget, RootAuthorization]:
    """Load and cross-check immutable plan, profile, budget, and root authorization."""

    plan = AutonomyPlan.model_validate_json(
        (session_root / "plan.json").read_text(encoding="utf-8")
    )
    profile = AutonomyProfile.model_validate_json(
        (session_root / "profile.json").read_text(encoding="utf-8")
    )
    budget = AutonomyBudget.model_validate_json(
        (session_root / "budget.json").read_text(encoding="utf-8")
    )
    authorization = RootAuthorization.model_validate_json(
        (session_root / "root_authorization.json").read_text(encoding="utf-8")
    )
    identities = {
        (item.job_id, item.workflow_id, item.dispatch_id)
        for item in (plan, profile, budget, authorization)
    }
    if len(identities) != 1:
        raise ValueError("autonomy contracts have mismatched production identities")
    if profile.profile_id != "autonomous_static_prop_v1" or profile.status != "verified_active":
        raise PermissionError("only autonomous_static_prop_v1 is executable")
    if plan.profile.sha256 != sha256_file(session_root / "profile.json"):
        raise ValueError("autonomy plan profile binding is stale")
    if plan.budget.sha256 != sha256_file(session_root / "budget.json"):
        raise ValueError("autonomy plan budget binding is stale")
    if plan.root_authorization.sha256 != sha256_file(
        session_root / "root_authorization.json"
    ):
        raise ValueError("autonomy plan root-authorization binding is stale")
    if profile.default_budget != budget:
        raise ValueError("autonomy profile embedded budget differs from the exact budget")
    if authorization.autonomy_profile != plan.profile or authorization.budget != plan.budget:
        raise ValueError("root authorization support bindings differ from the plan")
    if authorization.allowed_gate_kinds != profile.allowed_gate_kinds:
        raise ValueError("root authorization gate scope differs from the profile")
    if authorization.prohibited_scopes != profile.prohibited_capabilities:
        raise ValueError("root authorization prohibited scope differs from the profile")
    if (
        plan.reference_content_scope != authorization.reference_content_scope
        or plan.reference_content_scope != profile.reference_content_scope
        or plan.target_subject != authorization.target_subject
        or plan.output_profile != authorization.output_profile
        or plan.output_profile != profile.output_profile
        or plan.initial_candidate_limit > budget.initial_candidates
        or plan.action_limit > budget.global_action_limit
    ):
        raise ValueError("autonomy plan broadens its immutable root/profile scope")
    expected_plan_inputs = {
        "dispatch_plan": plan.production_dispatch_plan.sha256,
        "profile": plan.profile.sha256,
        "budget": plan.budget.sha256,
        "root_authorization": plan.root_authorization.sha256,
    }
    if plan.input_sha256 != stable_json_digest(expected_plan_inputs) or (
        plan.source_fingerprint
        != stable_json_digest({**expected_plan_inputs, "target_subject": plan.target_subject})
    ):
        raise ValueError("autonomy plan digest is stale or self-inconsistent")
    expected_root_source = canonical_digest(
        {
            "request_sha256": authorization.original_request_sha256,
            "launch_sha256": authorization.production_launch_or_binding.sha256,
            "reference_sha256": authorization.primary_reference.sha256,
            "profile_sha256": authorization.autonomy_profile.sha256,
            "budget_sha256": authorization.budget.sha256,
            "target_subject": authorization.target_subject,
        }
    )
    if (
        authorization.input_sha256 != authorization.original_request_sha256
        or authorization.source_fingerprint != expected_root_source
    ):
        raise ValueError("root authorization digest is stale or self-inconsistent")
    for artifact in (
        plan.production_dispatch_plan,
        plan.production_controller_plan,
        authorization.production_launch_or_binding,
        authorization.primary_reference,
        profile.quality_gate_profile,
    ):
        _verify_artifact(root, artifact)
    if authorization.status != "active":
        raise PermissionError("root authorization is not active")
    if authorization.expires_at is not None and authorization.expires_at <= _utc_now():
        raise PermissionError("root authorization has expired")
    return plan, profile, budget, authorization


def _recover_transition_staging(root: Path, session_root: Path) -> list[str]:
    """Recover complete atomic stages and quarantine incomplete receipt-less stages."""

    transitions = session_root / "transitions"
    transitions.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    for stage in sorted(transitions.glob(".staging-*")):
        if not stage.is_dir():
            raise ValueError("autonomy transition staging entry is not a directory")
        marker = stage / "publish.json"
        complete_stage = (
            marker.is_file()
            and (stage / "state.json").is_file()
            and (stage / "receipt.json").is_file()
        )
        if complete_stage:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            target_name = str(payload.get("target", ""))
            target = transitions / target_name
            if not target_name.isdigit() or len(target_name) != 4 or target.exists():
                raise ValueError("completed autonomy staging cannot be published safely")
            os.replace(stage, target)
            warnings.append(f"Recovered completed autonomy transition {target_name}.")
            continue
        quarantine = session_root / "interrupted_staging"
        quarantine.mkdir(parents=True, exist_ok=True)
        destination = quarantine / stage.name.removeprefix(".")
        if destination.exists():
            raise ValueError("duplicate interrupted autonomy staging evidence")
        os.replace(stage, destination)
        relative = destination.relative_to(root).as_posix()
        warnings.append(f"Preserved incomplete receipt-less staging at {relative}.")
    return warnings


def _load_state_chain(
    root: Path,
    session_root: Path,
) -> tuple[AutonomyState, AutonomyArtifact | None, list[str]]:
    """Reconstruct authoritative state only from atomic transition directories."""

    warnings = _recover_transition_staging(root, session_root)
    transitions = ensure_autonomy_path(
        root,
        session_root / "transitions",
        must_exist=True,
    )
    directories = sorted(path for path in transitions.iterdir() if path.name.isdigit())
    if not directories or directories[0].name != "0000":
        raise ValueError("autonomy transition chain has no initial state")
    previous_state_artifact: AutonomyArtifact | None = None
    previous_receipt_artifact: AutonomyArtifact | None = None
    previous_state: AutonomyState | None = None
    previous_policy_sha256: str | None = None
    latest_promotion: CandidatePromotionReceipt | None = None
    current: AutonomyState | None = None
    for index, directory in enumerate(directories):
        if directory.name != f"{index:04d}":
            raise ValueError("autonomy transition sequence contains a gap")
        state_path = directory / "state.json"
        state_artifact = artifact_for(root, state_path)
        state = AutonomyState.model_validate_json(state_path.read_text(encoding="utf-8"))
        if state.action_sequence != index:
            raise ValueError("autonomy state sequence does not match its directory")
        if current is not None and (
            state.job_id != current.job_id
            or state.workflow_id != current.workflow_id
            or state.dispatch_id != current.dispatch_id
            or state.session_id != current.session_id
        ):
            raise ValueError("autonomy transition state identity changed")
        if state.best_known_candidate is not None:
            _verify_artifact(root, state.best_known_candidate)
        if state.round_baseline_candidate is not None:
            _verify_artifact(root, state.round_baseline_candidate)
        if state.last_quality_report is not None:
            _verify_artifact(root, state.last_quality_report)
        if index == 0:
            if (directory / "receipt.json").exists():
                raise ValueError("initial autonomy state must not contain a transition receipt")
        else:
            receipt_path = directory / "receipt.json"
            receipt_artifact = artifact_for(root, receipt_path)
            receipt = AutonomyIterationReceipt.model_validate_json(
                receipt_path.read_text(encoding="utf-8")
            )
            if (
                receipt.job_id != state.job_id
                or receipt.workflow_id != state.workflow_id
                or receipt.dispatch_id != state.dispatch_id
                or receipt.session_id != state.session_id
                or receipt.sequence != index
                or receipt.state_before != previous_state_artifact
                or receipt.state_after != state_artifact
                or receipt.budget_before != previous_state.budget_usage
                or receipt.budget_after != state.budget_usage
                or receipt.previous_receipt_sha256
                != (previous_receipt_artifact.sha256 if previous_receipt_artifact else None)
                or state.receipt_chain_head_before_state_sha256
                != (previous_receipt_artifact.sha256 if previous_receipt_artifact else None)
            ):
                raise ValueError("autonomy transition receipt chain is stale or spliced")
            if receipt.policy_authorization is not None:
                policy_path = _verify_artifact(root, receipt.policy_authorization)
                policy = PolicyAuthorization.model_validate_json(
                    policy_path.read_text(encoding="utf-8")
                )
                if (
                    policy.previous_authorization_sha256 != previous_policy_sha256
                    or policy.budget_before != receipt.budget_before
                    or policy.budget_after != receipt.budget_after
                ):
                    raise ValueError("autonomy policy authorization chain is stale or spliced")
                validate_policy_authorization(
                    root,
                    policy,
                    expected_job_id=state.job_id,
                    expected_workflow_id=state.workflow_id,
                    expected_step_id=policy.workflow_step_id,
                    expected_gate_kind=policy.gate_kind,
                    expected_input_fingerprint=policy.workflow_input_fingerprint,
                )
                previous_policy_sha256 = receipt.policy_authorization.sha256
            if receipt.candidate_evaluation is not None:
                _verify_artifact(root, receipt.candidate_evaluation)
            if receipt.candidate_promotion_receipt is not None:
                promotion_path = _verify_artifact(
                    root,
                    receipt.candidate_promotion_receipt,
                )
                promotion = CandidatePromotionReceipt.model_validate_json(
                    promotion_path.read_text(encoding="utf-8")
                )
                if (
                    promotion.job_id != state.job_id
                    or promotion.workflow_id != state.workflow_id
                    or promotion.dispatch_id != state.dispatch_id
                    or promotion.policy_authorization != receipt.policy_authorization
                ):
                    raise ValueError("candidate promotion receipt identity is stale")
                for artifact in (
                    promotion.candidate_evaluation,
                    promotion.candidate_manifest,
                    promotion.candidate_modeling_plan,
                    promotion.candidate_scene_spec,
                    promotion.policy_authorization,
                ):
                    _verify_artifact(root, artifact)
                for relative_path, expected_sha256 in (
                    (
                        promotion.archived_modeling_plan_path,
                        promotion.previous_modeling_plan_sha256,
                    ),
                    (
                        promotion.archived_scene_spec_path,
                        promotion.previous_scene_spec_sha256,
                    ),
                ):
                    if relative_path is None:
                        continue
                    archived_path = ensure_autonomy_path(
                        root,
                        root / relative_path,
                        must_exist=True,
                    )
                    if (
                        not archived_path.is_file()
                        or expected_sha256 is None
                        or sha256_file(archived_path) != expected_sha256
                    ):
                        raise ValueError("candidate promotion archive is stale or tampered")
                latest_promotion = promotion
            if receipt.material_promotion_receipt is not None:
                material_receipt_path = _verify_artifact(
                    root,
                    receipt.material_promotion_receipt,
                )
                material_receipt = MaterialCandidatePromotionReceipt.model_validate_json(
                    material_receipt_path.read_text(encoding="utf-8")
                )
                if (
                    material_receipt.job_id != state.job_id
                    or material_receipt.workflow_id != state.workflow_id
                    or material_receipt.dispatch_id != state.dispatch_id
                    or material_receipt.session_id != state.session_id
                    or material_receipt.policy_authorization
                    != receipt.policy_authorization
                ):
                    raise ValueError("material promotion receipt identity is stale")
                for artifact in (
                    material_receipt.ranking,
                    material_receipt.selected_evaluation,
                    material_receipt.selected_material_plan,
                    material_receipt.policy_authorization,
                    material_receipt.production_assignment,
                    material_receipt.previous_authored_plan,
                ):
                    _verify_artifact(root, artifact)
                authored_path = ensure_autonomy_path(
                    root,
                    root / material_receipt.workflow_authored_plan_path,
                    must_exist=True,
                )
                if (
                    not authored_path.is_file()
                    or sha256_file(authored_path)
                    != material_receipt.workflow_authored_plan_sha256
                ):
                    raise ValueError("workflow-authored material candidate is stale")
            for artifact in receipt.host_attempt_evidence:
                _verify_artifact(root, artifact)
            previous_receipt_artifact = receipt_artifact
        previous_state_artifact = state_artifact
        previous_state = state
        current = state
    if current is None:
        raise RuntimeError("autonomy state reconstruction failed")
    if latest_promotion is not None:
        _verify_artifact(root, latest_promotion.canonical_modeling_plan)
        _verify_artifact(root, latest_promotion.canonical_scene_spec)
    return current, previous_receipt_artifact, warnings


def _transition(
    root: Path,
    session_root: Path,
    before: AutonomyState,
    previous_receipt: AutonomyArtifact | None,
    *,
    action: str,
    budget_usage: BudgetUsage,
    update: dict[str, Any],
    candidate_evaluation: AutonomyArtifact | None = None,
    policy_authorization: AutonomyArtifact | None = None,
    candidate_promotion_receipt: AutonomyArtifact | None = None,
    material_promotion_receipt: AutonomyArtifact | None = None,
    host_attempt_evidence: list[AutonomyArtifact] | None = None,
    canonical_changed: bool = False,
    rollback_performed: bool = False,
    outcome: str = "advanced",
    failure_fingerprint: str | None = None,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Atomically publish one state/receipt pair and refresh the non-authoritative pointer."""

    sequence = before.action_sequence + 1
    target_name = f"{sequence:04d}"
    target_dir = session_root / "transitions" / target_name
    if target_dir.exists():
        raise FileExistsError(target_dir)
    stage_dir = session_root / "transitions" / f".staging-{target_name}-{uuid4().hex}"
    stage_dir.mkdir(parents=True, exist_ok=False)
    now = _utc_now()
    before_artifact = artifact_for(
        root,
        session_root / "transitions" / f"{before.action_sequence:04d}" / "state.json",
    )
    state = build_transition_state(
        before,
        before_artifact=before_artifact,
        previous_receipt=previous_receipt,
        action=action,
        sequence=sequence,
        budget_usage=budget_usage,
        update=update,
        observed_at=now,
    )
    state_bytes = (state.model_dump_json(indent=2) + "\n").encode("utf-8")
    state_relative = (target_dir / "state.json").relative_to(root).as_posix()
    state_artifact = _artifact_from_bytes(root, state_relative, state_bytes)
    receipt = build_transition_receipt(
        before,
        state,
        before_artifact=before_artifact,
        state_artifact=state_artifact,
        previous_receipt=previous_receipt,
        action=action,
        sequence=sequence,
        budget_usage=budget_usage,
        created_at=now,
        candidate_evaluation=candidate_evaluation,
        policy_authorization=policy_authorization,
        candidate_promotion_receipt=candidate_promotion_receipt,
        material_promotion_receipt=material_promotion_receipt,
        host_attempt_evidence=host_attempt_evidence,
        canonical_changed=canonical_changed,
        rollback_performed=rollback_performed,
        outcome=outcome,
        failure_fingerprint=failure_fingerprint,
    )
    receipt_bytes = (receipt.model_dump_json(indent=2) + "\n").encode("utf-8")
    (stage_dir / "state.json").write_bytes(state_bytes)
    (stage_dir / "receipt.json").write_bytes(receipt_bytes)
    (stage_dir / "publish.json").write_text(
        json.dumps({"target": target_name}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(stage_dir, target_dir)
    write_mutable_projection(root, session_root / "state.json", state.model_dump(mode="json"))
    return state, receipt


def _consume_action(
    budget: AutonomyBudget,
    usage: BudgetUsage,
    **increments: int,
) -> BudgetUsage:
    """Consume one supervisor action plus its explicit bounded resource dimensions."""

    decision = consume_budget(
        budget,
        usage,
        total_actions=1,
        **increments,
    )
    if not decision.allowed:
        raise PermissionError(
            f"autonomy budget exhausted: {decision.exhausted_dimension}"
        )
    return decision.usage


_BUDGET_TERMINAL_REASONS: dict[str, TerminalReason] = {
    "initial_candidates": "no_eligible_candidates",
    "structural_rounds": "structural_budget_exhausted",
    "candidates_per_structural_round": "structural_budget_exhausted",
    "parametric_convergence_iterations": "parametric_budget_exhausted",
    "material_rounds": "material_budget_exhausted",
    "package_repairs": "package_repair_budget_exhausted",
    "total_blender_builds": "global_budget_exhausted",
    "total_quality_evaluations": "global_budget_exhausted",
    "canonical_promotions": "structural_budget_exhausted",
    "total_actions": "global_budget_exhausted",
}


def _budget_terminal_reason(dimension: str | None) -> TerminalReason:
    """Map one exhausted immutable budget dimension to a stable terminal reason."""

    if dimension is None:
        return "global_budget_exhausted"
    return _BUDGET_TERMINAL_REASONS.get(dimension, "global_budget_exhausted")


def _best_known_review_evidence(
    root: Path,
    state: AutonomyState,
) -> tuple[
    CandidateEvaluation,
    StructuralCandidateManifest,
    IntegratedQualityReport,
    AutonomyArtifact,
] | None:
    """Return exact candidate-owned review evidence when no canonical QA exists yet."""

    if state.best_known_candidate is None:
        return None
    evaluation = CandidateEvaluation.model_validate_json(
        _verify_artifact(root, state.best_known_candidate).read_text(encoding="utf-8")
    )
    manifest = StructuralCandidateManifest.model_validate_json(
        _verify_artifact(root, evaluation.candidate_manifest).read_text(encoding="utf-8")
    )
    if manifest.status != "evaluated":
        return None
    quality_path = _verify_artifact(root, manifest.integrated_quality_report)
    report = IntegratedQualityReport.model_validate_json(
        quality_path.read_text(encoding="utf-8")
    )
    _verify_integrated_quality_inputs(root, state, report)
    return evaluation, manifest, report, manifest.integrated_quality_report


def _review_termination_reason(
    state: AutonomyState,
    report: IntegratedQualityReport,
) -> str:
    """Prefer an exact bounded-search stop reason over a generic quality outcome."""

    if state.pending_terminal_reason is not None:
        return state.pending_terminal_reason
    return (
        "unscorable_evidence"
        if report.outcome == "unscorable"
        else "completed_review_bundle"
    )


def _next_action_exhausted_dimension(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    budget: AutonomyBudget,
) -> str | None:
    """Detect a known exhausted dimension before starting the next AQ action."""

    usage = state.budget_usage
    if usage.total_actions >= budget.global_action_limit:
        return "total_actions"
    if (
        state.next_action == "run_structural_round"
        and usage.structural_rounds >= budget.structural_rounds
    ):
        return "structural_rounds"
    if (
        state.next_action == "run_parametric_iteration"
        and usage.parametric_convergence_iterations
        >= budget.parametric_convergence_iterations
    ):
        return "parametric_convergence_iterations"
    if (
        state.next_action == "run_material_round"
        and usage.material_rounds >= budget.material_rounds
    ):
        return "material_rounds"
    if (
        state.next_action == "promote_best_candidate"
        and usage.canonical_promotions >= budget.canonical_promotions
    ):
        return "canonical_promotions"
    if (
        state.next_action == "run_integrated_quality"
        and usage.total_quality_evaluations >= budget.total_quality_evaluations
    ):
        return "total_quality_evaluations"
    if (
        state.next_action == "await_controller_output"
        and state.phase
        in {"initial_candidates", "structural_authoring", "parametric_convergence"}
        and state.current_candidate_id is not None
    ):
        _assignment_path, ready = _candidate_ready(root, session_root, state)
        if not ready:
            return None
        if usage.total_blender_builds >= budget.total_blender_builds:
            return "total_blender_builds"
        if usage.total_quality_evaluations >= budget.total_quality_evaluations:
            return "total_quality_evaluations"
        if state.phase == "initial_candidates" and (
            usage.initial_candidates >= budget.initial_candidates
        ):
            return "initial_candidates"
        if state.phase == "structural_authoring" and (
            usage.structural_rounds >= budget.structural_rounds
        ):
            return "structural_rounds"
        if state.phase == "parametric_convergence" and (
            usage.parametric_convergence_iterations
            >= budget.parametric_convergence_iterations
        ):
            return "parametric_convergence_iterations"
    return None


def _latest_reference_result(root: Path, session_root: Path) -> ReferenceEvidenceRunResult:
    """Load the exact session-owned reference run result."""

    path = session_root / "reference_evidence_run.json"
    return ReferenceEvidenceRunResult.model_validate_json(path.read_text(encoding="utf-8"))


def _collect_reference_action(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    plan: AutonomyPlan,
    budget: AutonomyBudget,
    previous_receipt: AutonomyArtifact | None,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Generate V0.4 diagnostics plus bounded companion masks and camera hypotheses."""

    usage = _consume_action(budget, state.budget_usage)
    reference = _verify_artifact(root, _load_contracts(root, session_root)[3].primary_reference)
    analyze_job_reference(state.job_id, provider="auto")
    run_id = f"{state.session_id[:96]}-ref"
    result = run_reference_evidence(
        root,
        job_id=state.job_id,
        run_id=run_id,
        source_image_path=reference.relative_to(root).as_posix(),
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
    )
    result_path = session_root / "reference_evidence_run.json"
    if result_path.is_file():
        stored = ReferenceEvidenceRunResult.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
        if stored != result:
            raise ValueError(
                "existing session reference result differs from recovered exact evidence"
            )
    else:
        write_immutable_json(root, result_path, result.model_dump(mode="json"))
    return _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="collect_reference_evidence",
        budget_usage=usage,
        update={
            "status": "running",
            "phase": "initial_candidates",
            "next_action": "author_initial_candidate",
            "warnings": [*state.warnings, *result.provenance.parameters.get("warnings", [])]
            if isinstance(result.provenance.parameters.get("warnings"), list)
            else state.warnings,
        },
    )


def _recover_candidate_assignment_root(
    root: Path,
    session_root: Path,
    candidate_root: Path,
    *,
    candidate_id: str,
) -> CandidateAuthoringAssignment | None:
    """Adopt a complete assignment or preserve an interrupted partial directory."""

    if not candidate_root.exists():
        return None
    assignment_path = candidate_root / "assignment.json"
    if assignment_path.is_file():
        assignment = CandidateAuthoringAssignment.model_validate_json(
            assignment_path.read_text(encoding="utf-8")
        )
        prompt_path = candidate_root / "authoring_prompt.md"
        if (
            assignment.candidate_id != candidate_id
            or assignment.output_root != candidate_root.relative_to(root).as_posix()
            or not prompt_path.is_file()
            or sha256_file(prompt_path) != assignment.authoring_prompt_sha256
        ):
            raise ValueError("existing candidate assignment is stale or self-inconsistent")
        return assignment
    quarantine_root = session_root / "interrupted_staging" / "candidate_assignments"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    quarantine = quarantine_root / f"{candidate_id}-{uuid4().hex[:8]}"
    os.replace(candidate_root, quarantine)
    ensure_autonomy_path(root, quarantine, must_exist=True)
    return None


def _candidate_prompt(
    plan: AutonomyPlan,
    reference_result: ReferenceEvidenceRunResult,
    candidate_id: str,
    *,
    candidate_phase: str = "initial",
    round_index: int = 0,
    baseline_modeling_plan: AutonomyArtifact | None = None,
    baseline_scene_spec: AutonomyArtifact | None = None,
) -> str:
    """Build one exact controller-only candidate prompt for a bounded AQ phase."""

    phase_rules = {
        "initial": (
            "Author an independent initial interpretation from the evidence."
        ),
        "structural": (
            "Improve major silhouette, part orientation, semantic structure, or assembly. "
            "Preserve all existing primary semantic IDs and every material identity."
        ),
        "parametric": (
            "Copy ModelingPlan bytes exactly. Keep semantic IDs, hierarchy, materials, "
            "modifiers, and geometry kinds unchanged. Adjust only camera framing, object "
            "transforms, primitive dimensions, or profile-extrude depth."
        ),
    }[candidate_phase]
    structural_rule = (
        "You may additionally author `scene_spec_v03.json` when a whitelisted loft, sweep, "
        "boolean_tree, multi_loop_extrude, or geometry_nodes_template recipe is necessary. "
        "It must mirror the required SceneSpec 0.2 IDs, materials, transforms, hierarchy, "
        "camera, and non-structural geometry exactly. The host will materialize every "
        "structural object and compile one path-backed SceneSpec 0.2 candidate."
        if candidate_phase in {"initial", "structural"}
        else "Do not author SceneSpecV03 or structural recipes for a parametric candidate."
    )
    return f"""# Autonomous {candidate_phase} candidate {candidate_id}

Author exactly three required workflow-owned files below the assigned candidate directory:
`modeling_plan.json`, `camera_hypothesis.json`, and `scene_spec.json`.

- Job: `{plan.job_id}`
- Workflow: `{plan.workflow_id}`
- Dispatch: `{plan.dispatch_id}`
- Target subject: `{plan.target_subject}`
- Candidate phase / round: `{candidate_phase}` / `{round_index}`
- Reference evidence: `{reference_result.reference_evidence_path}`
- Camera hypotheses: `{reference_result.camera_hypothesis_set_path}`
- Baseline ModelingPlan: `{baseline_modeling_plan.path if baseline_modeling_plan else 'none'}`
- Baseline SceneSpec: `{baseline_scene_spec.path if baseline_scene_spec else 'none'}`

{phase_rules}

{structural_rule}

Use ModelingPlan 0.4.0 and SceneSpec 0.2.0 unless an explicit 0.3 structural recipe is
materialized to a path-backed 0.2 custom_mesh before evaluation. Keep the scope strictly
`primary_object_only`; exclude independent terrain, vegetation, props, backdrops, atmosphere,
interiors, rigs, animation, gameplay, external providers, and engine-specific data. Choose one
camera hypothesis for staging, but do not claim hidden geometry or absolute scale as observed.
Every object needs a stable semantic ID and primary/supporting QA role. Surface-attached marks
that do not affect silhouette or structure belong in ModelingPlan.surface_details, not one mesh
per mark. The controller is the only writer; advisory subagents are read-only.
"""


def _author_candidate_assignment(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    plan: AutonomyPlan,
    budget: AutonomyBudget,
    previous_receipt: AutonomyArtifact | None,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Publish one immutable candidate assignment and stop for controller authoring."""

    usage = _consume_action(budget, state.budget_usage)
    index = state.budget_usage.initial_candidates + 1
    if index > plan.initial_candidate_limit:
        raise PermissionError("initial candidate limit is exhausted")
    candidate_id = f"initial-{index:02d}"
    candidate_root = candidate_directory(session_root, candidate_id)
    reference_result = _latest_reference_result(root, session_root)
    evidence_artifact = artifact_for(root, root / reference_result.reference_evidence_path)
    camera_artifact = artifact_for(root, root / reference_result.camera_hypothesis_set_path)
    recovered = _recover_candidate_assignment_root(
        root,
        session_root,
        candidate_root,
        candidate_id=candidate_id,
    )
    if recovered is not None:
        if (
            recovered.job_id != state.job_id
            or recovered.workflow_id != state.workflow_id
            or recovered.dispatch_id != state.dispatch_id
            or recovered.session_id != state.session_id
            or recovered.candidate_phase != "initial"
            or recovered.candidate_index != index
            or recovered.reference_evidence != evidence_artifact
            or recovered.camera_hypothesis_set != camera_artifact
        ):
            raise ValueError("recovered initial-candidate assignment changed its authority")
        return _transition(
            root,
            session_root,
            state,
            previous_receipt,
            action="author_initial_candidate",
            budget_usage=usage,
            update={
                "status": "waiting_for_controller",
                "phase": "initial_candidates",
                "next_action": "await_controller_output",
                "current_candidate_id": candidate_id,
                "warnings": [
                    *state.warnings,
                    "Recovered a complete receipt-less initial candidate assignment.",
                ],
            },
        )
    candidate_root.mkdir(parents=True, exist_ok=False)
    prompt = _candidate_prompt(plan, reference_result, candidate_id)
    prompt_path = candidate_root / "authoring_prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    prompt_artifact = artifact_for(root, prompt_path)
    workflow_modeling_plan = artifact_for(root, root / "analysis" / "modeling_plan.json")
    scene_path = root / "analysis" / "scene_spec.json"
    workflow_scene_spec = artifact_for(root, scene_path) if scene_path.is_file() else None
    output_root = candidate_root.relative_to(root).as_posix()
    required_outputs = [
        f"{output_root}/modeling_plan.json",
        f"{output_root}/camera_hypothesis.json",
        f"{output_root}/scene_spec.json",
    ]
    assignment = CandidateAuthoringAssignment(
        contract_id=f"assignment-{state.session_id}-{candidate_id}",
        assignment_id=f"assignment-{state.session_id}-{candidate_id}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        input_sha256=canonical_digest(
            {
                "reference": evidence_artifact.sha256,
                "cameras": camera_artifact.sha256,
                "prompt": prompt_artifact.sha256,
                "modeling_plan": workflow_modeling_plan.sha256,
                "scene_spec": (
                    workflow_scene_spec.sha256 if workflow_scene_spec else None
                ),
            }
        ),
        source_fingerprint=reference_result.source_fingerprint,
        producer="codex_blender_modeler.autonomy.service",
        producer_version="0.1.0",
        provenance=[evidence_artifact, camera_artifact, prompt_artifact],
        created_at=_utc_now(),
        session_id=state.session_id,
        candidate_id=candidate_id,
        candidate_index=index,
        reference_evidence=evidence_artifact,
        camera_hypothesis_set=camera_artifact,
        workflow_modeling_plan=workflow_modeling_plan,
        workflow_scene_spec=workflow_scene_spec,
        output_root=output_root,
        required_outputs=required_outputs,
        scene_spec_v03_output=f"{output_root}/scene_spec_v03.json",
        authoring_prompt_sha256=prompt_artifact.sha256,
    )
    assignment_path = candidate_root / "assignment.json"
    write_immutable_json(root, assignment_path, assignment.model_dump(mode="json"))
    return _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="author_initial_candidate",
        budget_usage=usage,
        update={
            "status": "waiting_for_controller",
            "phase": "initial_candidates",
            "next_action": "await_controller_output",
            "current_candidate_id": candidate_id,
        },
    )


def _author_refinement_assignment(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    plan: AutonomyPlan,
    profile: AutonomyProfile,
    budget: AutonomyBudget,
    authorization: RootAuthorization,
    previous_receipt: AutonomyArtifact | None,
    *,
    candidate_phase: str,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Publish one exact structural or parametric candidate assignment."""

    if candidate_phase not in {"structural", "parametric"}:
        raise ValueError("refinement phase must be structural or parametric")
    if state.best_known_candidate is None:
        raise RuntimeError("refinement requires a best-known baseline evaluation")
    usage = _consume_action(budget, state.budget_usage)
    if candidate_phase == "structural":
        round_index = state.current_round_index or state.budget_usage.structural_rounds + 1
        candidate_index = state.current_round_candidate_index + 1
        if round_index > budget.structural_rounds:
            raise PermissionError("structural round budget is exhausted")
        if candidate_index > budget.candidates_per_structural_round:
            raise PermissionError("structural candidate-per-round budget is exhausted")
        candidate_id = f"structural-r{round_index:02d}-c{candidate_index:02d}"
        round_baseline = state.round_baseline_candidate or state.best_known_candidate
    else:
        round_index = state.budget_usage.parametric_convergence_iterations + 1
        candidate_index = 1
        if round_index > budget.parametric_convergence_iterations:
            raise PermissionError("parametric convergence budget is exhausted")
        candidate_id = f"parametric-i{round_index:02d}"
        round_baseline = state.best_known_candidate
    candidate_root = candidate_directory(session_root, candidate_id)
    reference_result = _latest_reference_result(root, session_root)
    evidence_artifact = artifact_for(root, root / reference_result.reference_evidence_path)
    camera_artifact = artifact_for(root, root / reference_result.camera_hypothesis_set_path)
    modeling_artifact = artifact_for(root, root / "analysis" / "modeling_plan.json")
    scene_artifact = artifact_for(root, root / "analysis" / "scene_spec.json")
    _verify_artifact(root, round_baseline)
    recovered = _recover_candidate_assignment_root(
        root,
        session_root,
        candidate_root,
        candidate_id=candidate_id,
    )
    if recovered is not None:
        if (
            recovered.job_id != state.job_id
            or recovered.workflow_id != state.workflow_id
            or recovered.dispatch_id != state.dispatch_id
            or recovered.session_id != state.session_id
            or recovered.candidate_phase != candidate_phase
            or recovered.candidate_index != candidate_index
            or recovered.round_index != round_index
            or recovered.reference_evidence != evidence_artifact
            or recovered.camera_hypothesis_set != camera_artifact
            or recovered.workflow_modeling_plan != modeling_artifact
            or recovered.workflow_scene_spec != scene_artifact
            or recovered.baseline_evaluation != round_baseline
        ):
            raise ValueError("recovered refinement assignment changed its authority")
        recovered_assignment_artifact = artifact_for(
            root,
            candidate_root / "assignment.json",
        )
        recovered_policy = (
            _authorize_parametric_assignment(
                root,
                session_root,
                state,
                profile,
                budget,
                authorization,
                usage,
                recovered,
                recovered_assignment_artifact,
            )
            if candidate_phase == "parametric"
            else None
        )
        return _transition(
            root,
            session_root,
            state,
            previous_receipt,
            action=(
                "run_structural_round"
                if candidate_phase == "structural"
                else "run_parametric_iteration"
            ),
            budget_usage=usage,
            update={
                "status": "waiting_for_controller",
                "phase": (
                    "structural_authoring"
                    if candidate_phase == "structural"
                    else "parametric_convergence"
                ),
                "next_action": "await_controller_output",
                "current_candidate_id": candidate_id,
                "current_round_index": round_index,
                "current_round_candidate_index": candidate_index,
                "round_baseline_candidate": round_baseline,
                "warnings": [
                    *state.warnings,
                    "Recovered a complete receipt-less refinement assignment.",
                ],
            },
            policy_authorization=recovered_policy,
        )
    candidate_root.mkdir(parents=True, exist_ok=False)
    prompt = _candidate_prompt(
        plan,
        reference_result,
        candidate_id,
        candidate_phase=candidate_phase,
        round_index=round_index,
        baseline_modeling_plan=modeling_artifact,
        baseline_scene_spec=scene_artifact,
    )
    prompt += (
        "\nBaseline evaluation: "
        f"`{round_baseline.path}`. Improve its exact direct evidence without regression.\n"
    )
    prompt_path = candidate_root / "authoring_prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    prompt_artifact = artifact_for(root, prompt_path)
    output_root = candidate_root.relative_to(root).as_posix()
    required_outputs = [
        f"{output_root}/modeling_plan.json",
        f"{output_root}/camera_hypothesis.json",
        f"{output_root}/scene_spec.json",
    ]
    assignment = CandidateAuthoringAssignment(
        contract_id=f"assignment-{state.session_id}-{candidate_id}",
        assignment_id=f"assignment-{state.session_id}-{candidate_id}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        input_sha256=canonical_digest(
            {
                "reference": evidence_artifact.sha256,
                "cameras": camera_artifact.sha256,
                "prompt": prompt_artifact.sha256,
                "modeling_plan": modeling_artifact.sha256,
                "scene_spec": scene_artifact.sha256,
                "baseline_evaluation": round_baseline.sha256,
            }
        ),
        source_fingerprint=reference_result.source_fingerprint,
        producer="codex_blender_modeler.autonomy.service",
        producer_version="0.1.0",
        provenance=[
            evidence_artifact,
            camera_artifact,
            modeling_artifact,
            scene_artifact,
            round_baseline,
            prompt_artifact,
        ],
        created_at=_utc_now(),
        session_id=state.session_id,
        candidate_id=candidate_id,
        candidate_index=candidate_index,
        candidate_phase=candidate_phase,  # type: ignore[arg-type]
        round_index=round_index,
        reference_evidence=evidence_artifact,
        camera_hypothesis_set=camera_artifact,
        workflow_modeling_plan=modeling_artifact,
        workflow_scene_spec=scene_artifact,
        baseline_evaluation=round_baseline,
        output_root=output_root,
        required_outputs=required_outputs,
        scene_spec_v03_output=(
            f"{output_root}/scene_spec_v03.json"
            if candidate_phase == "structural"
            else None
        ),
        authoring_prompt_sha256=prompt_artifact.sha256,
    )
    assignment_path = candidate_root / "assignment.json"
    write_immutable_json(root, assignment_path, assignment.model_dump(mode="json"))
    assignment_artifact = artifact_for(root, assignment_path)
    policy_artifact = (
        _authorize_parametric_assignment(
            root,
            session_root,
            state,
            profile,
            budget,
            authorization,
            usage,
            assignment,
            assignment_artifact,
        )
        if candidate_phase == "parametric"
        else None
    )
    return _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action=(
            "run_structural_round"
            if candidate_phase == "structural"
            else "run_parametric_iteration"
        ),
        budget_usage=usage,
        update={
            "status": "waiting_for_controller",
            "phase": (
                "structural_authoring"
                if candidate_phase == "structural"
                else "parametric_convergence"
            ),
            "next_action": "await_controller_output",
            "current_candidate_id": candidate_id,
            "current_round_index": round_index,
            "current_round_candidate_index": candidate_index,
            "round_baseline_candidate": round_baseline,
        },
        policy_authorization=policy_artifact,
    )


def _candidate_ready(root: Path, session_root: Path, state: AutonomyState) -> tuple[Path, bool]:
    """Return the exact current assignment and whether all controller outputs exist."""

    if state.current_candidate_id is None:
        raise ValueError("candidate wait state has no candidate identity")
    candidate_root = candidate_directory(session_root, state.current_candidate_id)
    assignment_path = candidate_root / "assignment.json"
    assignment = CandidateAuthoringAssignment.model_validate_json(
        assignment_path.read_text(encoding="utf-8")
    )
    ready = all((root / relative).is_file() for relative in assignment.required_outputs)
    return assignment_path, ready


def _candidate_structural_evidence(
    value: CandidateCompletionMarker
    | CandidateEvaluation
    | StructuralCandidateManifest
    | StructuralCandidatePlan,
) -> tuple[
    AutonomyArtifact | None,
    AutonomyArtifact | None,
    tuple[AutonomyArtifact, ...],
    tuple[AutonomyArtifact, ...],
    tuple[AutonomyArtifact, ...],
]:
    """Normalize one candidate contract's optional structural evidence for comparison."""

    return (
        value.scene_spec_v03_candidate,
        value.compiled_scene_spec_candidate,
        tuple(value.structural_recipes),
        tuple(value.structural_mesh_payloads),
        tuple(value.structural_materialization_receipts),
    )


def _verify_structural_candidate_bundle(
    root: Path,
    manifest: StructuralCandidateManifest,
    *,
    plan: StructuralCandidatePlan,
    completion: CandidateCompletionMarker,
    evaluation: CandidateEvaluation,
) -> None:
    """Re-hash one complete structural bundle and require every contract to bind it."""

    expected = _candidate_structural_evidence(manifest)
    for label, value in (
        ("candidate plan", plan),
        ("candidate completion", completion),
        ("candidate evaluation", evaluation),
    ):
        if _candidate_structural_evidence(value) != expected:
            raise ValueError(f"{label} changed structural evidence bindings")
    artifacts = [
        item
        for item in (
            manifest.scene_spec_v03_candidate,
            manifest.compiled_scene_spec_candidate,
            *manifest.structural_recipes,
            *manifest.structural_mesh_payloads,
            *manifest.structural_materialization_receipts,
        )
        if item is not None
    ]
    for artifact in artifacts:
        _verify_artifact(root, artifact)
        if plan.exact_input_map.get(artifact.path) != artifact.sha256:
            raise ValueError(
                "candidate plan omitted or changed structural input binding: "
                f"{artifact.path}"
            )


def _adopt_completed_candidate_evaluation(
    root: Path,
    assignment: CandidateAuthoringAssignment,
    candidate_root: Path,
) -> AutonomyArtifact | None:
    """Adopt only a fully published exact candidate evaluation after an interrupted transition."""

    evaluation_path = candidate_root / "candidate_evaluation.json"
    if not evaluation_path.is_file():
        return None
    evaluation_artifact = artifact_for(root, evaluation_path)
    evaluation = CandidateEvaluation.model_validate_json(
        evaluation_path.read_text(encoding="utf-8")
    )
    if (
        evaluation.job_id != assignment.job_id
        or evaluation.workflow_id != assignment.workflow_id
        or evaluation.dispatch_id != assignment.dispatch_id
        or evaluation.candidate_id != assignment.candidate_id
        or evaluation.baseline_evaluation != assignment.baseline_evaluation
    ):
        raise ValueError("published candidate evaluation differs from its assignment")
    manifest = StructuralCandidateManifest.model_validate_json(
        _verify_artifact(root, evaluation.candidate_manifest).read_text(encoding="utf-8")
    )
    if manifest.candidate_id != assignment.candidate_id:
        raise ValueError("published candidate manifest belongs to another assignment")
    candidate_plan = StructuralCandidatePlan.model_validate_json(
        _verify_artifact(root, manifest.plan).read_text(encoding="utf-8")
    )
    completion = CandidateCompletionMarker.model_validate_json(
        _verify_artifact(root, manifest.completion_marker).read_text(encoding="utf-8")
    )
    _verify_structural_candidate_bundle(
        root,
        manifest,
        plan=candidate_plan,
        completion=completion,
        evaluation=evaluation,
    )
    for artifact in (
        manifest.plan,
        manifest.scene_spec,
        manifest.completion_marker,
        manifest.blend,
        manifest.inventory,
        manifest.validation,
        manifest.integrated_quality_report,
        *manifest.structural_recipes,
        *manifest.structural_mesh_payloads,
        *manifest.structural_materialization_receipts,
        *manifest.low_resolution_renders,
    ):
        _verify_artifact(root, artifact)
    for artifact in (
        manifest.scene_spec_v03_candidate,
        manifest.compiled_scene_spec_candidate,
    ):
        if artifact is not None:
            _verify_artifact(root, artifact)
    return evaluation_artifact


def _rankable_candidate(
    root: Path,
    evaluation: CandidateEvaluation,
) -> RankableQualityCandidate:
    """Adapt one AQ candidate to the authoritative lexicographic/Pareto ranker."""

    manifest = StructuralCandidateManifest.model_validate_json(
        _verify_artifact(root, evaluation.candidate_manifest).read_text(encoding="utf-8")
    )
    baseline = (
        CandidateEvaluation.model_validate_json(
            _verify_artifact(root, evaluation.baseline_evaluation).read_text(
                encoding="utf-8"
            )
        )
        if evaluation.baseline_evaluation is not None
        else None
    )
    axis_values = {
        "reference_alignment": evaluation.metrics.reference_fidelity,
        "structural_integrity": evaluation.metrics.structural_quality,
        "material_fidelity": evaluation.metrics.material_quality,
        "production_readiness": evaluation.metrics.production_quality,
    }
    baseline_values = {
        "reference_alignment": (
            baseline.metrics.reference_fidelity if baseline is not None else None
        ),
        "structural_integrity": (
            baseline.metrics.structural_quality if baseline is not None else None
        ),
        "material_fidelity": (
            baseline.metrics.material_quality if baseline is not None else None
        ),
        "production_readiness": (
            baseline.metrics.production_quality if baseline is not None else None
        ),
    }
    gains = {
        axis: float(value - baseline_values[axis])
        if baseline_values[axis] is not None
        else float(value)
        for axis, value in axis_values.items()
        if value is not None
    }
    if not gains:
        gains = {"reference_alignment": 0.0}
    gate_status = (
        "failed"
        if evaluation.metrics.hard_gate_failures
        else "unscorable"
        if evaluation.evidence_status != "scored"
        else "passed"
    )
    report = manifest.integrated_quality_report
    return RankableQualityCandidate(
        candidate_id=evaluation.candidate_id,
        candidate_sha256=evaluation.candidate_manifest.sha256,
        report_path=report.path,
        report_sha256=report.sha256,
        gate_status=gate_status,
        critical_regressions=sorted(set(evaluation.regression_findings)),
        meaningful_gain=(
            evaluation.eligible_for_promotion
            and max(gains.values()) >= evaluation.minimum_meaningful_gain
        ),
        gains=gains,  # type: ignore[arg-type]
        changed_path_count=(1 if evaluation.metrics.change_magnitude > 0 else 0),
        change_magnitude=evaluation.metrics.change_magnitude,
    )


def _better_candidate(
    root: Path,
    left: CandidateEvaluation,
    right: CandidateEvaluation,
) -> bool:
    """Compare two candidates with the shared hard-gate/Pareto/minimum-change policy."""

    pair_fingerprint = canonical_digest(
        {
            left.candidate_id: left.source_fingerprint,
            right.candidate_id: right.source_fingerprint,
        }
    )
    if (
        left.job_id,
        left.workflow_id,
        left.dispatch_id,
    ) != (
        right.job_id,
        right.workflow_id,
        right.dispatch_id,
    ):
        raise ValueError("candidate ranking inputs belong to different AQ identities")
    created_at = _utc_now()
    rankable = [_rankable_candidate(root, left), _rankable_candidate(root, right)]
    artifacts = [
        QualityArtifact(
            artifact_id=candidate.candidate_id,
            kind="integrated-quality-report",
            relative_path=candidate.report_path,
            sha256=candidate.report_sha256,
            producer=ProducerIdentity(
                name=evaluation.producer,
                version=evaluation.producer_version,
            ),
            produced_at=evaluation.created_at,
        )
        for candidate, evaluation in zip(rankable, (left, right), strict=True)
    ]
    provenance = QualityProvenance(
        job_id=left.job_id,
        workflow_id=left.workflow_id,
        dispatch_id=left.dispatch_id,
        input_sha256=stable_json_digest(
            [item.model_dump(mode="json") for item in artifacts]
        ),
        source_fingerprint=pair_fingerprint,
        artifacts=artifacts,
    )
    ranking = rank_quality_candidates(
        rankable,
        ranking_id=f"pair-{pair_fingerprint[:20]}",
        provenance=provenance,
        producer=ProducerIdentity(name="autonomy-supervisor", version="0.1.0"),
        created_at=created_at,
    )
    return ranking.selected_candidate_id == left.candidate_id


def _candidate_state_fingerprint(
    root: Path,
    evaluation: CandidateEvaluation,
    assignment: CandidateAuthoringAssignment,
) -> StateFingerprint:
    """Derive one exact candidate state for duplicate and oscillation detection."""

    manifest = StructuralCandidateManifest.model_validate_json(
        _verify_artifact(root, evaluation.candidate_manifest).read_text(encoding="utf-8")
    )
    candidate_plan = StructuralCandidatePlan.model_validate_json(
        _verify_artifact(root, manifest.plan).read_text(encoding="utf-8")
    )
    material_path = root / "analysis" / "material_plan.json"
    return StateFingerprint(
        modeling_plan_sha256=candidate_plan.modeling_plan.sha256,
        scene_spec_sha256=manifest.scene_spec.sha256,
        material_plan_or_graph_sha256=(
            sha256_file(material_path) if material_path.is_file() else None
        ),
        camera_fingerprint=candidate_plan.camera_hypothesis.sha256,
        normalized_metric_vector_sha256=canonical_digest(
            evaluation.metrics.model_dump(mode="json")
        ),
        build_fingerprint=manifest.blend.sha256,
        canonical_source_fingerprint=evaluation.source_fingerprint,
        change_direction=assignment.candidate_phase,
    )


def _candidate_attempt_operation_id(assignment_artifact: AutonomyArtifact) -> str:
    """Derive one bounded portable host-operation ID from the exact assignment hash."""

    return f"candidate-{assignment_artifact.sha256[:20]}"


def _load_host_attempt_artifact(
    root: Path,
    path: Path,
    model_type: type[HostAttemptIntent] | type[HostAttemptFailure],
) -> tuple[HostAttemptIntent | HostAttemptFailure, AutonomyArtifact] | None:
    """Load one optional exact attempt artifact without accepting a stale byte stream."""

    if not path.is_file():
        return None
    artifact = artifact_for(root, path)
    model = model_type.model_validate_json(path.read_text(encoding="utf-8"))
    return model, artifact


def _quarantine_incomplete_candidate_evaluation(
    root: Path,
    session_root: Path,
    candidate_root: Path,
    operation_id: str,
) -> None:
    """Preserve receipt-less derived candidate outputs before the only allowed retry."""

    retained = {
        "assignment.json",
        "modeling_plan.json",
        "camera_hypothesis.json",
        "scene_spec.json",
    }
    movable = [item for item in candidate_root.iterdir() if item.name not in retained]
    if not movable:
        return
    quarantine = (
        session_root
        / "interrupted_staging"
        / operation_id
        / "attempt-01"
    )
    if quarantine.exists():
        raise ValueError("candidate retry quarantine already exists")
    quarantine.mkdir(parents=True, exist_ok=False)
    for item in movable:
        destination = quarantine / item.name
        os.replace(item, destination)
    ensure_autonomy_path(root, quarantine, must_exist=True)


def _terminalize_host_attempt_failure(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    previous_receipt: AutonomyArtifact | None,
    failure: HostAttemptFailure,
    failure_artifact: AutonomyArtifact,
    intent_artifact: AutonomyArtifact,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Publish one fail-closed AQ terminal from an immutable non-retryable host failure."""

    terminal_path = (root / failure_artifact.path).parent.parent / "terminal_failure.json"
    if _native_is_file(terminal_path):
        terminal = HostFailureTerminalReceipt.model_validate_json(
            _native_read_text(terminal_path)
        )
        terminal_artifact = artifact_for(root, terminal_path)
        if terminal.final_failure != failure_artifact:
            raise ValueError("existing host terminal is bound to another failure")
    else:
        terminal, terminal_artifact = publish_failure_terminal_receipt(
            root=root,
            failure_artifact=failure_artifact,
        )
    _write_terminal_intent(
        root,
        session_root,
        state,
        status="failed",
        reason=terminal.reason,
    )
    after, receipt = _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="terminalize",
        budget_usage=terminal.budget_usage,
        update={
            "status": "failed",
            "phase": "terminal",
            "next_action": "none",
            "terminal_reason": terminal.reason,
        },
        host_attempt_evidence=[intent_artifact, failure_artifact, terminal_artifact],
        outcome="failed",
        failure_fingerprint=failure.failure_fingerprint,
    )
    _terminal_contract(
        root,
        session_root,
        after,
        status="failed",
        reason=terminal.reason,
    )
    return after, receipt


def _record_candidate_host_failure(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    previous_receipt: AutonomyArtifact | None,
    intent: HostAttemptIntent,
    intent_artifact: AutonomyArtifact,
    error: Exception,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Record one failed candidate host attempt and either expose retry or terminalize."""

    failure, failure_artifact = record_host_attempt_failure(
        root=root,
        intent_artifact=intent_artifact,
        error=error,
    )
    if not failure.retry_allowed:
        return _terminalize_host_attempt_failure(
            root,
            session_root,
            state,
            previous_receipt,
            failure,
            failure_artifact,
            intent_artifact,
        )
    return _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="evaluate_candidate",
        budget_usage=failure.budget_after,
        update={
            "status": "waiting_for_controller",
            "next_action": "await_controller_output",
            "warnings": [
                *state.warnings,
                "Transient candidate host failure recorded; one exact retry remains.",
            ],
        },
        host_attempt_evidence=[intent_artifact, failure_artifact],
        outcome="failed",
        failure_fingerprint=failure.failure_fingerprint,
    )


def _adopt_candidate_host_failure(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    previous_receipt: AutonomyArtifact | None,
    intent: HostAttemptIntent,
    intent_artifact: AutonomyArtifact,
    failure: HostAttemptFailure,
    failure_artifact: AutonomyArtifact,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Adopt a complete failure written before a process interruption."""

    if failure.attempt_intent != intent_artifact or failure.budget_after != intent.budget_after:
        raise ValueError("candidate failure does not match its exact attempt intent")
    if not failure.retry_allowed:
        return _terminalize_host_attempt_failure(
            root,
            session_root,
            state,
            previous_receipt,
            failure,
            failure_artifact,
            intent_artifact,
        )
    if state.budget_usage != intent.budget_before:
        raise ValueError("retryable candidate failure does not follow current AQ budget")
    return _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="evaluate_candidate",
        budget_usage=failure.budget_after,
        update={
            "status": "waiting_for_controller",
            "next_action": "await_controller_output",
            "warnings": [
                *state.warnings,
                "Recovered a transient candidate host failure; one exact retry remains.",
            ],
        },
        host_attempt_evidence=[intent_artifact, failure_artifact],
        outcome="failed",
        failure_fingerprint=failure.failure_fingerprint,
    )


def _evaluate_candidate_action(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    plan: AutonomyPlan,
    budget: AutonomyBudget,
    previous_receipt: AutonomyArtifact | None,
) -> tuple[AutonomyState, AutonomyIterationReceipt] | None:
    """Evaluate ready controller outputs in isolation and retain the best exact candidate."""

    assignment_path, ready = _candidate_ready(root, session_root, state)
    if not ready:
        return None
    assignment = CandidateAuthoringAssignment.model_validate_json(
        assignment_path.read_text(encoding="utf-8")
    )
    assignment_artifact = artifact_for(root, assignment_path)
    increments = {
        "total_blender_builds": 1,
        "total_quality_evaluations": 1,
    }
    if assignment.candidate_phase == "initial":
        increments["initial_candidates"] = 1
    elif assignment.candidate_phase == "structural" and (
        assignment.candidate_index == budget.candidates_per_structural_round
    ):
        increments["structural_rounds"] = 1
    elif assignment.candidate_phase == "parametric":
        increments["parametric_convergence_iterations"] = 1
    candidate_root = candidate_directory(session_root, assignment.candidate_id)
    evaluation_artifact = _adopt_completed_candidate_evaluation(
        root,
        assignment,
        candidate_root,
    )
    host_attempt_evidence: list[AutonomyArtifact] = []
    operation_id = _candidate_attempt_operation_id(assignment_artifact)
    operation_root = session_root / "host_attempts" / operation_id
    attempt_1_intent = _load_host_attempt_artifact(
        root,
        operation_root / "attempt-01" / "intent.json",
        HostAttemptIntent,
    )
    attempt_1_failure = _load_host_attempt_artifact(
        root,
        operation_root / "attempt-01" / "failure.json",
        HostAttemptFailure,
    )
    attempt_2_intent = _load_host_attempt_artifact(
        root,
        operation_root / "attempt-02" / "intent.json",
        HostAttemptIntent,
    )
    attempt_2_failure = _load_host_attempt_artifact(
        root,
        operation_root / "attempt-02" / "failure.json",
        HostAttemptFailure,
    )
    if evaluation_artifact is not None:
        selected_attempt = attempt_2_intent or attempt_1_intent
        if selected_attempt is None:
            usage = _consume_action(budget, state.budget_usage, **increments)
        else:
            intent, intent_artifact = selected_attempt
            if not isinstance(intent, HostAttemptIntent):
                raise TypeError("candidate host intent has an unexpected contract type")
            if state.budget_usage != intent.budget_before:
                raise ValueError("completed candidate host attempt has a stale budget chain")
            usage = intent.budget_after
            if attempt_1_failure is not None:
                host_attempt_evidence.extend(
                    [attempt_1_failure[1], intent_artifact]
                )
            else:
                host_attempt_evidence.append(intent_artifact)
    if evaluation_artifact is None:
        if attempt_2_failure is not None:
            intent_pair = attempt_2_intent
            if intent_pair is None:
                raise ValueError("second candidate failure is missing its attempt intent")
            intent, intent_artifact = intent_pair
            failure, failure_artifact = attempt_2_failure
            if not isinstance(intent, HostAttemptIntent) or not isinstance(
                failure, HostAttemptFailure
            ):
                raise TypeError("candidate retry evidence has an unexpected contract type")
            return _adopt_candidate_host_failure(
                root,
                session_root,
                state,
                previous_receipt,
                intent,
                intent_artifact,
                failure,
                failure_artifact,
            )
        if attempt_2_intent is not None:
            intent, intent_artifact = attempt_2_intent
            if not isinstance(intent, HostAttemptIntent):
                raise TypeError("candidate retry intent has an unexpected contract type")
            return _record_candidate_host_failure(
                root,
                session_root,
                state,
                previous_receipt,
                intent,
                intent_artifact,
                TimeoutError("interrupted candidate retry before completion"),
            )
        if attempt_1_failure is not None:
            intent_pair = attempt_1_intent
            if intent_pair is None:
                raise ValueError("candidate failure is missing its attempt intent")
            intent, intent_artifact = intent_pair
            failure, failure_artifact = attempt_1_failure
            if not isinstance(intent, HostAttemptIntent) or not isinstance(
                failure, HostAttemptFailure
            ):
                raise TypeError("candidate failure evidence has an unexpected contract type")
            if state.budget_usage == intent.budget_before:
                return _adopt_candidate_host_failure(
                    root,
                    session_root,
                    state,
                    previous_receipt,
                    intent,
                    intent_artifact,
                    failure,
                    failure_artifact,
                )
            if state.budget_usage != failure.budget_after:
                raise ValueError("candidate retry budget does not follow the first failure")
            if not failure.retry_allowed:
                return _terminalize_host_attempt_failure(
                    root,
                    session_root,
                    state,
                    previous_receipt,
                    failure,
                    failure_artifact,
                    intent_artifact,
                )
            _quarantine_incomplete_candidate_evaluation(
                root,
                session_root,
                candidate_root,
                operation_id,
            )
            active_intent, active_intent_artifact = begin_host_attempt(
                root=root,
                session_root=session_root,
                job_id=state.job_id,
                workflow_id=state.workflow_id,
                dispatch_id=state.dispatch_id,
                session_id=state.session_id,
                operation_id=operation_id,
                action="evaluate_candidate",
                operation_kind="host_execution",
                attempt_index=2,
                budget=budget,
                budget_before=state.budget_usage,
                canonical_inputs=[
                    assignment_artifact,
                    artifact_for(root, session_root / "quality_gate_profile.json"),
                ],
                budget_increments=increments,
                previous_failure=failure_artifact,
            )
            host_attempt_evidence.extend(
                [failure_artifact, active_intent_artifact]
            )
        elif attempt_1_intent is not None:
            intent, intent_artifact = attempt_1_intent
            if not isinstance(intent, HostAttemptIntent):
                raise TypeError("candidate attempt intent has an unexpected contract type")
            return _record_candidate_host_failure(
                root,
                session_root,
                state,
                previous_receipt,
                intent,
                intent_artifact,
                TimeoutError("interrupted candidate attempt before completion"),
            )
        else:
            active_intent, active_intent_artifact = begin_host_attempt(
                root=root,
                session_root=session_root,
                job_id=state.job_id,
                workflow_id=state.workflow_id,
                dispatch_id=state.dispatch_id,
                session_id=state.session_id,
                operation_id=operation_id,
                action="evaluate_candidate",
                operation_kind="host_execution",
                attempt_index=1,
                budget=budget,
                budget_before=state.budget_usage,
                canonical_inputs=[
                    assignment_artifact,
                    artifact_for(root, session_root / "quality_gate_profile.json"),
                ],
                budget_increments=increments,
            )
            host_attempt_evidence.append(active_intent_artifact)
        try:
            result = evaluate_structural_candidate(
                root,
                assignment_path=assignment_path,
                quality_profile_path=session_root / "quality_gate_profile.json",
            )
        except Exception as exc:
            return _record_candidate_host_failure(
                root,
                session_root,
                state,
                previous_receipt,
                active_intent,
                active_intent_artifact,
                exc,
            )
        evaluation_artifact = AutonomyArtifact.model_validate(
            result["candidate_evaluation"]
        )
        usage = active_intent.budget_after
    evaluation_path = _verify_artifact(root, evaluation_artifact)
    evaluation = CandidateEvaluation.model_validate_json(
        evaluation_path.read_text(encoding="utf-8")
    )
    fingerprint = _candidate_state_fingerprint(root, evaluation, assignment)
    history = [*state.state_history, fingerprint]
    cycle = detect_state_cycle(history)
    best_artifact = state.best_known_candidate
    if not evaluation.eligible_for_promotion or cycle is not None:
        selected = False
    elif best_artifact is None:
        selected = True
    else:
        best = CandidateEvaluation.model_validate_json(
            _verify_artifact(root, best_artifact).read_text(encoding="utf-8")
        )
        selected = _better_candidate(root, evaluation, best)
    if selected:
        preserve_best_known(session_root, evaluation, evaluation_path)
        best_artifact = evaluation_artifact
    warnings = list(state.warnings)
    pending_terminal_reason = state.pending_terminal_reason
    if cycle is not None:
        warnings.append(f"{cycle.kind}: {cycle.reason}")
        pending_terminal_reason = cycle.kind  # type: ignore[assignment]
    plateau_count = state.plateau_count
    if assignment.candidate_phase == "initial":
        more = usage.initial_candidates < plan.initial_candidate_limit
        if cycle is not None:
            next_action = (
                "promote_best_candidate" if best_artifact is not None else "terminalize"
            )
        elif more:
            next_action = "author_initial_candidate"
        elif best_artifact is not None:
            next_action = "promote_best_candidate"
        else:
            next_action = "terminalize"
            pending_terminal_reason = "no_eligible_candidates"
        next_phase = "initial_candidates"
        next_round_index = 0
        next_round_candidate = 0
        round_baseline = None
    elif assignment.candidate_phase == "structural":
        more_in_round = (
            assignment.candidate_index < budget.candidates_per_structural_round
        )
        if more_in_round:
            next_action = "run_structural_round"
            next_phase = "structural_authoring"
            next_round_index = assignment.round_index
            next_round_candidate = assignment.candidate_index
            round_baseline = state.round_baseline_candidate
        else:
            improved = (
                best_artifact is not None
                and state.round_baseline_candidate is not None
                and best_artifact.sha256 != state.round_baseline_candidate.sha256
            )
            if improved:
                next_action = "promote_best_candidate"
                plateau_count = 0
            else:
                plateau_count = min(budget.plateau_patience, plateau_count + 1)
                if usage.structural_rounds < budget.structural_rounds and (
                    plateau_count < budget.plateau_patience
                ):
                    next_action = "run_structural_round"
                elif (
                    usage.parametric_convergence_iterations
                    < budget.parametric_convergence_iterations
                ):
                    next_action = "run_parametric_iteration"
                else:
                    next_action = "advance_production"
                if plateau_count >= budget.plateau_patience:
                    pending_terminal_reason = "plateau"
                    next_action = "advance_production"
            next_phase = (
                "parametric_convergence"
                if next_action == "run_parametric_iteration"
                else "structural_authoring"
            )
            next_round_index = 0
            next_round_candidate = 0
            round_baseline = best_artifact
    else:
        improved = selected
        if improved:
            next_action = "promote_best_candidate"
            plateau_count = 0
        else:
            plateau_count = min(budget.plateau_patience, plateau_count + 1)
            next_action = (
                "run_parametric_iteration"
                if usage.parametric_convergence_iterations
                < budget.parametric_convergence_iterations
                and plateau_count < budget.plateau_patience
                else "advance_production"
            )
            if plateau_count >= budget.plateau_patience:
                pending_terminal_reason = "plateau"
                next_action = "advance_production"
    if cycle is not None and assignment.candidate_phase != "initial":
        next_action = "advance_production"
        next_phase = "parametric_convergence"
        next_round_index = 0
        next_round_candidate = 0
        round_baseline = best_artifact
    return _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="await_controller_output",
        budget_usage=usage,
        update={
            "status": "running",
            "phase": next_phase,
            "next_action": next_action,
            "best_known_candidate": best_artifact,
            "current_candidate_id": None,
            "current_round_index": next_round_index,
            "current_round_candidate_index": next_round_candidate,
            "round_baseline_candidate": round_baseline,
            "plateau_count": plateau_count,
            "state_history": history,
            "pending_terminal_reason": pending_terminal_reason,
            "warnings": warnings,
        },
        candidate_evaluation=evaluation_artifact,
        host_attempt_evidence=host_attempt_evidence,
    )


def _write_canonical_modeling_plan(
    root: Path,
    candidate: Path,
    *,
    expected_current_sha256: str,
) -> tuple[AutonomyArtifact, Path | None]:
    """Replace one exact scaffold with an authored plan and archive its previous bytes."""

    target = root / "analysis" / "modeling_plan.json"
    candidate_bytes = candidate.read_bytes()
    candidate_hash = hashlib.sha256(candidate_bytes).hexdigest()
    if not target.is_file():
        raise RuntimeError("canonical ModelingPlan scaffold disappeared before promotion")
    current_hash = sha256_file(target)
    if current_hash == candidate_hash:
        return artifact_for(root, target), None
    if current_hash != expected_current_sha256:
        raise RuntimeError("canonical ModelingPlan changed before candidate promotion")
    stamp = _utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    archived = root / "history" / f"{stamp}_{uuid4().hex[:8]}_modeling_plan.json"
    archived.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, archived)
    if sha256_file(archived) != expected_current_sha256:
        raise RuntimeError("archived ModelingPlan hash does not match the scaffold")
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(candidate_bytes)
    if sha256_file(temporary) != candidate_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("ModelingPlan promotion staging hash changed")
    os.replace(temporary, target)
    return artifact_for(root, target), archived


def _restore_archived_modeling_plan(
    root: Path,
    archived: Path,
    *,
    expected_promoted_sha256: str,
    expected_archived_sha256: str,
) -> None:
    """Restore the exact scaffold when paired SceneSpec promotion fails."""

    target = root / "analysis" / "modeling_plan.json"
    if not target.is_file() or sha256_file(target) != expected_promoted_sha256:
        raise RuntimeError(
            "cannot roll back ModelingPlan because the promoted canonical changed"
        )
    if not archived.is_file() or sha256_file(archived) != expected_archived_sha256:
        raise RuntimeError("archived ModelingPlan is missing or changed during rollback")
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.rollback.tmp")
    shutil.copy2(archived, temporary)
    if sha256_file(temporary) != expected_archived_sha256:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("ModelingPlan rollback staging hash changed")
    os.replace(temporary, target)


def _find_exact_history_file(
    root: Path,
    *,
    expected_sha256: str | None,
    filename_suffix: str,
) -> Path | None:
    """Find one unique immutable history file needed to recover a promotion receipt."""

    if expected_sha256 is None:
        return None
    history_root = root / "history"
    if not history_root.is_dir():
        return None
    history_root = ensure_autonomy_path(root, history_root, must_exist=True)
    matches = [
        path
        for path in history_root.glob(f"*{filename_suffix}")
        if path.is_file() and sha256_file(path) == expected_sha256
    ]
    if len(matches) > 1:
        raise ValueError("candidate promotion recovery found ambiguous history evidence")
    return matches[0] if matches else None


def _latest_transition_policy_sha256(root: Path, session_root: Path) -> str | None:
    """Return only the latest policy grant already committed in the receipt chain."""

    transitions = session_root / "transitions"
    latest: str | None = None
    for directory in sorted(path for path in transitions.iterdir() if path.name.isdigit()):
        receipt_path = directory / "receipt.json"
        if not receipt_path.is_file():
            continue
        receipt = AutonomyIterationReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        if receipt.policy_authorization is not None:
            _verify_artifact(root, receipt.policy_authorization)
            latest = receipt.policy_authorization.sha256
    return latest


def _authorize_parametric_assignment(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    profile: AutonomyProfile,
    budget: AutonomyBudget,
    authorization: RootAuthorization,
    usage_after: BudgetUsage,
    assignment: CandidateAuthoringAssignment,
    assignment_artifact: AutonomyArtifact,
) -> AutonomyArtifact:
    """Authorize one exact bounded parametric assignment before controller authoring."""

    if assignment.candidate_phase != "parametric":
        raise ValueError("bounded convergence plan authorization needs a parametric assignment")
    if (
        assignment.baseline_evaluation is None
        or assignment.workflow_modeling_plan is None
        or assignment.workflow_scene_spec is None
    ):
        raise ValueError("parametric assignment lacks exact baseline or canonical bindings")
    workflow_plan_artifact = artifact_for(
        root,
        root / "workflows" / state.workflow_id / "plan.json",
    )
    dependencies = {
        "parametric.assignment": assignment_artifact.sha256,
        "baseline_evaluation": assignment.baseline_evaluation.sha256,
        "canonical_modeling_plan": assignment.workflow_modeling_plan.sha256,
        "canonical_scene_spec": assignment.workflow_scene_spec.sha256,
    }
    step_id = f"autonomy.bounded_convergence_plan.{assignment.candidate_id}"
    target = PolicyGateTarget(
        contract_id=f"gate-target-{state.session_id}-{assignment.candidate_id}",
        target_id=f"gate-target-{state.session_id}-{assignment.candidate_id}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        input_sha256=assignment_artifact.sha256,
        source_fingerprint=canonical_digest(
            {
                "workflow_plan": workflow_plan_artifact.sha256,
                "input_fingerprint": assignment_artifact.sha256,
                "dependencies": dependencies,
            }
        ),
        producer="codex_blender_modeler.autonomy.service",
        producer_version="0.1.0",
        provenance=[
            workflow_plan_artifact,
            assignment_artifact,
            assignment.baseline_evaluation,
            assignment.workflow_modeling_plan,
            assignment.workflow_scene_spec,
        ],
        created_at=_utc_now(),
        session_id=state.session_id,
        workflow_step_id=step_id,
        workflow_input_fingerprint=assignment_artifact.sha256,
        gate_kind="bounded_convergence_plan",
        workflow_plan=workflow_plan_artifact,
        dependency_completion_fingerprints=dependencies,
        dependency_artifacts=[
            assignment_artifact,
            assignment.baseline_evaluation,
            assignment.workflow_modeling_plan,
            assignment.workflow_scene_spec,
        ],
    )
    target_path = (
        session_root
        / "policy_targets"
        / f"parametric-plan-{assignment.candidate_id}.json"
    )
    if target_path.is_file():
        stored_target = PolicyGateTarget.model_validate_json(
            target_path.read_text(encoding="utf-8")
        )
        if stored_target.model_copy(update={"created_at": target.created_at}) != target:
            raise ValueError("existing parametric plan target differs from the assignment")
    else:
        write_immutable_json(root, target_path, target.model_dump(mode="json"))
    target_artifact = artifact_for(root, target_path)
    root_artifact = artifact_for(root, session_root / "root_authorization.json")
    profile_artifact = artifact_for(root, session_root / "profile.json")
    budget_artifact = artifact_for(root, session_root / "budget.json")
    previous_sha = _latest_transition_policy_sha256(root, session_root)
    grant = authorize_policy_gate(
        root_authorization=authorization,
        root_authorization_artifact=root_artifact,
        root_authorization_sha256=root_artifact.sha256,
        profile=profile,
        profile_artifact=profile_artifact,
        profile_sha256=profile_artifact.sha256,
        budget=budget,
        budget_artifact=budget_artifact,
        budget_sha256=budget_artifact.sha256,
        gate_kind="bounded_convergence_plan",
        step_id=step_id,
        workflow_input_fingerprint=assignment_artifact.sha256,
        gate_target=target_artifact,
        target_artifact=assignment_artifact,
        budget_before=state.budget_usage,
        budget_after=usage_after,
        previous_authorization_sha256=previous_sha,
    )
    grant_path = (
        session_root
        / "policy_authorizations"
        / f"parametric-plan-{assignment.candidate_id}.json"
    )
    return persist_and_validate_policy_authorization(root, grant_path, grant)


def _authorize_candidate_promotion(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    profile: AutonomyProfile,
    budget: AutonomyBudget,
    authorization: RootAuthorization,
    usage_after: BudgetUsage,
    evaluation: CandidateEvaluation,
    assignment: CandidateAuthoringAssignment,
) -> AutonomyArtifact:
    """Authorize one exact best-candidate promotion without forging user approval."""

    workflow_plan_artifact = artifact_for(
        root,
        root / "workflows" / state.workflow_id / "plan.json",
    )
    evaluation_artifact = state.best_known_candidate
    if evaluation_artifact is None:
        raise RuntimeError("candidate promotion has no exact evaluation artifact")
    gate_kind: PolicyGateKind = (
        "bounded_convergence_candidate"
        if assignment.candidate_phase == "parametric"
        else "structural_candidate_promotion"
    )
    step_id = (
        f"autonomy.bounded_convergence_candidate.{evaluation.candidate_id}"
        if assignment.candidate_phase == "parametric"
        else f"autonomy.structural_candidate_promotion.{evaluation.candidate_id}"
    )
    target = PolicyGateTarget(
        contract_id=f"gate-target-{state.session_id}-{evaluation.candidate_id}",
        target_id=f"gate-target-{state.session_id}-{evaluation.candidate_id}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        input_sha256=evaluation_artifact.sha256,
        source_fingerprint=canonical_digest(
            {
                "workflow_plan": workflow_plan_artifact.sha256,
                "evaluation": evaluation_artifact.sha256,
                "candidate_manifest": evaluation.candidate_manifest.sha256,
            }
        ),
        producer="codex_blender_modeler.autonomy.service",
        producer_version="0.1.0",
        provenance=[workflow_plan_artifact, evaluation_artifact],
        created_at=_utc_now(),
        session_id=state.session_id,
        workflow_step_id=step_id,
        workflow_input_fingerprint=evaluation_artifact.sha256,
        gate_kind=gate_kind,
        workflow_plan=workflow_plan_artifact,
        dependency_completion_fingerprints={
            "candidate_evaluation": evaluation_artifact.sha256,
            "candidate_manifest": evaluation.candidate_manifest.sha256,
        },
        dependency_artifacts=[evaluation.candidate_manifest],
    )
    target_path = (
        session_root
        / "policy_targets"
        / f"structural-{evaluation.candidate_id}.json"
    )
    if target_path.is_file():
        stored_target = PolicyGateTarget.model_validate_json(
            target_path.read_text(encoding="utf-8")
        )
        if stored_target.model_copy(update={"created_at": target.created_at}) != target:
            raise ValueError("existing candidate gate target differs from current evidence")
    else:
        write_immutable_json(root, target_path, target.model_dump(mode="json"))
    target_artifact = artifact_for(root, target_path)
    root_artifact = artifact_for(root, session_root / "root_authorization.json")
    profile_artifact = artifact_for(root, session_root / "profile.json")
    budget_artifact = artifact_for(root, session_root / "budget.json")
    grant = authorize_policy_gate(
        root_authorization=authorization,
        root_authorization_artifact=root_artifact,
        root_authorization_sha256=root_artifact.sha256,
        profile=profile,
        profile_artifact=profile_artifact,
        profile_sha256=profile_artifact.sha256,
        budget=budget,
        budget_artifact=budget_artifact,
        budget_sha256=budget_artifact.sha256,
        gate_kind=gate_kind,
        step_id=step_id,
        workflow_input_fingerprint=evaluation_artifact.sha256,
        gate_target=target_artifact,
        target_artifact=evaluation_artifact,
        budget_before=state.budget_usage,
        budget_after=usage_after,
        previous_authorization_sha256=_latest_transition_policy_sha256(
            root,
            session_root,
        ),
    )
    grant_path = (
        session_root
        / "policy_authorizations"
        / f"structural-{evaluation.candidate_id}.json"
    )
    return persist_and_validate_policy_authorization(root, grant_path, grant)


def _promote_best_action(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    profile: AutonomyProfile,
    budget: AutonomyBudget,
    authorization: RootAuthorization,
    previous_receipt: AutonomyArtifact | None,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Atomically promote the best isolated candidate with an exact immutable receipt."""

    if state.best_known_candidate is None:
        raise RuntimeError("no eligible best-known candidate exists")
    usage = _consume_action(
        budget,
        state.budget_usage,
        canonical_promotions=1,
    )
    evaluation = CandidateEvaluation.model_validate_json(
        _verify_artifact(root, state.best_known_candidate).read_text(encoding="utf-8")
    )
    if not evaluation.eligible_for_promotion:
        raise PermissionError("best-known candidate is not eligible for promotion")
    manifest = StructuralCandidateManifest.model_validate_json(
        _verify_artifact(root, evaluation.candidate_manifest).read_text(encoding="utf-8")
    )
    manifest_artifact = evaluation.candidate_manifest
    plan_path = _verify_artifact(root, manifest.plan)
    candidate_plan = StructuralCandidatePlan.model_validate_json(
        plan_path.read_text(encoding="utf-8")
    )
    modeling_artifact = candidate_plan.modeling_plan
    candidate_modeling_path = _verify_artifact(root, modeling_artifact)
    scene_path = _verify_artifact(root, manifest.scene_spec)
    completion = CandidateCompletionMarker.model_validate_json(
        _verify_artifact(root, manifest.completion_marker).read_text(encoding="utf-8")
    )
    _verify_structural_candidate_bundle(
        root,
        manifest,
        plan=candidate_plan,
        completion=completion,
        evaluation=evaluation,
    )
    assignment = CandidateAuthoringAssignment.model_validate_json(
        _verify_artifact(root, completion.assignment).read_text(encoding="utf-8")
    )
    scaffold = assignment.workflow_modeling_plan
    if scaffold is None:
        raise RuntimeError("candidate assignment did not bind the V0.4 ModelingPlan scaffold")
    if candidate_plan.exact_input_map.get(scaffold.path) != scaffold.sha256:
        raise RuntimeError("candidate plan is not bound to the exact ModelingPlan scaffold")
    policy_artifact = _authorize_candidate_promotion(
        root,
        session_root,
        state,
        profile,
        budget,
        authorization,
        usage,
        evaluation,
        assignment,
    )
    existing_scene = root / "analysis" / "scene_spec.json"
    owner_id = f"autonomy-{state.session_id}"
    with canonical_scene_spec_write_lock(state.job_id, owner_id):
        canonical_modeling, archived_modeling = _write_canonical_modeling_plan(
            root,
            candidate_modeling_path,
            expected_current_sha256=scaffold.sha256,
        )
        try:
            if (
                existing_scene.is_file()
                and sha256_file(existing_scene) == manifest.scene_spec.sha256
            ):
                promotion = {
                    "previous_scene_spec_sha256": (
                        assignment.workflow_scene_spec.sha256
                        if assignment.workflow_scene_spec is not None
                        else None
                    ),
                    "archived_scene_spec": None,
                }
            else:
                promotion = replace_scene_spec_if_current(
                    state.job_id,
                    scene_path,
                    expected_candidate_sha256=manifest.scene_spec.sha256,
                    expected_current_sha256=(
                        assignment.workflow_scene_spec.sha256
                        if assignment.workflow_scene_spec is not None
                        else None
                    ),
                    lock_owner_id=owner_id,
                )
        except Exception:
            if archived_modeling is not None:
                _restore_archived_modeling_plan(
                    root,
                    archived_modeling,
                    expected_promoted_sha256=modeling_artifact.sha256,
                    expected_archived_sha256=scaffold.sha256,
                )
            raise
    canonical_scene = artifact_for(root, root / "analysis" / "scene_spec.json")
    archived = promotion.get("archived_scene_spec")
    if archived_modeling is None and scaffold.sha256 != canonical_modeling.sha256:
        archived_modeling = _find_exact_history_file(
            root,
            expected_sha256=scaffold.sha256,
            filename_suffix="_modeling_plan.json",
        )
        if archived_modeling is None:
            raise RuntimeError("promoted ModelingPlan has no recoverable archive evidence")
    if (
        archived is None
        and promotion.get("previous_scene_spec_sha256") is not None
        and promotion.get("previous_scene_spec_sha256") != canonical_scene.sha256
    ):
        recovered_scene_archive = _find_exact_history_file(
            root,
            expected_sha256=promotion.get("previous_scene_spec_sha256"),
            filename_suffix="_scene_spec.json",
        )
        if recovered_scene_archive is None:
            raise RuntimeError("promoted SceneSpec has no recoverable archive evidence")
        archived = str(recovered_scene_archive)
    archived_relative = (
        Path(str(archived)).resolve().relative_to(root.resolve()).as_posix()
        if archived
        else None
    )
    archived_modeling_relative = (
        archived_modeling.resolve().relative_to(root.resolve()).as_posix()
        if archived_modeling is not None
        else None
    )
    receipt = CandidatePromotionReceipt(
        contract_id=f"promotion-{state.session_id}-{evaluation.candidate_id}",
        receipt_id=f"promotion-{state.session_id}-{evaluation.candidate_id}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        input_sha256=state.best_known_candidate.sha256,
        source_fingerprint=canonical_digest(
            {
                "candidate": manifest.scene_spec.sha256,
                "canonical": canonical_scene.sha256,
                "previous_scene": promotion.get("previous_scene_spec_sha256"),
                "previous_modeling": scaffold.sha256,
            }
        ),
        producer="codex_blender_modeler.autonomy.service",
        producer_version="0.1.0",
        provenance=[state.best_known_candidate, manifest_artifact, manifest.scene_spec],
        created_at=_utc_now(),
        session_id=state.session_id,
        candidate_id=evaluation.candidate_id,
        candidate_evaluation=state.best_known_candidate,
        candidate_manifest=manifest_artifact,
        candidate_modeling_plan=modeling_artifact,
        candidate_scene_spec=manifest.scene_spec,
        policy_authorization=policy_artifact,
        previous_modeling_plan_sha256=scaffold.sha256,
        previous_scene_spec_sha256=promotion.get("previous_scene_spec_sha256"),
        canonical_modeling_plan=canonical_modeling,
        canonical_scene_spec=canonical_scene,
        archived_modeling_plan_path=archived_modeling_relative,
        archived_scene_spec_path=archived_relative,
    )
    receipt_path = session_root / "promotions" / f"{evaluation.candidate_id}.json"
    if receipt_path.is_file():
        stored_receipt = CandidatePromotionReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        if stored_receipt.model_copy(update={"created_at": receipt.created_at}) != receipt:
            raise ValueError("existing candidate promotion receipt differs from recovery")
    else:
        write_immutable_json(root, receipt_path, receipt.model_dump(mode="json"))
    promotion_artifact = artifact_for(root, receipt_path)
    quality_profile = QualityGateProfile.model_validate_json(
        (session_root / "quality_gate_profile.json").read_text(encoding="utf-8")
    )
    threshold = quality_profile.threshold_for("reference_alignment")
    target_reached = (
        threshold is not None
        and evaluation.metrics.reference_fidelity is not None
        and evaluation.metrics.reference_fidelity >= threshold.pass_score
    )
    pending_terminal_reason = state.pending_terminal_reason
    if target_reached:
        next_action = "advance_production"
        next_phase = "structural_authoring"
    elif pending_terminal_reason in {
        "plateau",
        "duplicate_candidate_state",
        "oscillation_detected",
    }:
        next_action = "advance_production"
        next_phase = "structural_authoring"
    elif usage.structural_rounds < budget.structural_rounds:
        next_action = "run_structural_round"
        next_phase = "structural_authoring"
    elif (
        usage.parametric_convergence_iterations
        < budget.parametric_convergence_iterations
    ):
        next_action = "run_parametric_iteration"
        next_phase = "parametric_convergence"
    else:
        next_action = "advance_production"
        next_phase = "structural_authoring"
        pending_terminal_reason = (
            "parametric_budget_exhausted"
            if budget.parametric_convergence_iterations > 0
            else "structural_budget_exhausted"
        )
    return _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="promote_best_candidate",
        budget_usage=usage,
        update={
            "status": "running",
            "phase": next_phase,
            "next_action": next_action,
            "current_round_index": 0,
            "current_round_candidate_index": 0,
            "round_baseline_candidate": state.best_known_candidate,
            "pending_terminal_reason": pending_terminal_reason,
        },
        candidate_evaluation=state.best_known_candidate,
        policy_authorization=policy_artifact,
        candidate_promotion_receipt=promotion_artifact,
        canonical_changed=True,
    )


def _workflow_plan(root: Path, workflow_id: str) -> tuple[Path, WorkflowPlan]:
    """Load the immutable V0.8 plan bound to the production dispatch."""

    path = root / "workflows" / workflow_id / "plan.json"
    return path, WorkflowPlan.model_validate_json(path.read_text(encoding="utf-8"))


def _reserve_production_host_step(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    budget: AutonomyBudget,
    production_state: dict[str, Any],
) -> tuple[ProductionReservationDecision, AutonomyArtifact | None, str]:
    """Reserve exact AQ build/quality resources before one V0.8 host execution."""

    current_step_id = str(production_state.get("current_step_id") or "")
    if not current_step_id:
        raise ValueError("production host boundary has no current workflow step")
    workflow_path, workflow = _workflow_plan(root, state.workflow_id)
    step = next((item for item in workflow.steps if item.step_id == current_step_id), None)
    if step is None:
        raise ValueError("production host boundary references an unknown workflow step")
    workflow_state_path = root / "workflows" / state.workflow_id / "state.json"
    workflow_state = WorkflowState.model_validate_json(
        workflow_state_path.read_text(encoding="utf-8")
    )
    step_state = next(
        (item for item in workflow_state.steps if item.step_id == current_step_id),
        None,
    )
    if step_state is None or step_state.input_fingerprint is None:
        raise ValueError("production host step has no exact input fingerprint")
    workflow_artifact = artifact_for(root, workflow_path)
    budget_artifact = artifact_for(root, session_root / "budget.json")
    input_payload = {
        "workflow_plan": workflow_artifact.model_dump(mode="json"),
        "workflow_step_id": current_step_id,
        "workflow_input_fingerprint": step_state.input_fingerprint,
        "budget_before": state.budget_usage.model_dump(mode="json"),
    }
    decision = reserve_production_step_resources(
        step=step,
        budget=budget,
        usage=state.budget_usage,
        contract_id=f"production-reservation-{state.action_sequence + 1:04d}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        session_id=state.session_id,
        input_sha256=canonical_digest(input_payload),
        source_fingerprint=canonical_digest(
            {
                "input": input_payload,
                "workflow_state": sha256_file(workflow_state_path),
            }
        ),
        provenance=[workflow_artifact, budget_artifact],
        workflow_plan=workflow_artifact,
        budget_authority=budget_artifact,
        workflow_input_fingerprint=step_state.input_fingerprint,
        created_at=_utc_now(),
    )
    if not decision.allowed or decision.reservation is None:
        return decision, None, step_state.input_fingerprint
    evidence_root = (
        session_root
        / "production_resources"
        / f"{state.action_sequence + 1:04d}-{current_step_id}"
    )
    reservation_path = evidence_root / "reservation.json"
    write_immutable_json(
        root,
        reservation_path,
        decision.reservation.model_dump(mode="json"),
    )
    return decision, artifact_for(root, reservation_path), step_state.input_fingerprint


def _record_production_resource_receipt(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    decision: ProductionReservationDecision,
    reservation_artifact: AutonomyArtifact,
    workflow_input_fingerprint: str,
    controller_result: dict[str, Any],
) -> list[AutonomyArtifact]:
    """Bind a reservation to exact completion outputs or an exact failure after-state."""

    reservation = decision.reservation
    if reservation is None:
        raise ValueError("production resource receipt requires an allowed reservation")
    advance = dict(controller_result.get("advance_receipt") or {})
    sequence = int(advance.get("sequence", 0))
    receipt_id = str(advance.get("receipt_id", ""))
    if sequence < 1 or not receipt_id:
        raise ValueError("production controller returned no exact advance receipt")
    advance_path = (
        root
        / "production"
        / "dispatches"
        / state.dispatch_id
        / "advances"
        / f"{sequence:04d}-{receipt_id}.json"
    )
    advance_artifact = artifact_for(root, advance_path)
    after_payload = advance.get("workflow_state_after")
    if not isinstance(after_payload, dict):
        raise ValueError("production advance omitted its exact after-state artifact")
    after_artifact = AutonomyArtifact(
        path=str(after_payload["path"]),
        sha256=str(after_payload["sha256"]),
    )
    after_path = _verify_artifact(root, after_artifact)
    after_workflow = WorkflowState.model_validate_json(
        after_path.read_text(encoding="utf-8")
    )
    after_controller = dict(controller_result.get("state") or {})
    controller_status = str(after_controller.get("status") or "")
    if controller_status in {"failed", "blocked"}:
        outcome = "failed"
    elif controller_status == "cancelled":
        outcome = "interrupted"
    else:
        outcome = "completed"
    step_state = next(
        (
            item
            for item in after_workflow.steps
            if item.step_id == reservation.workflow_step_id
        ),
        None,
    )
    exact_outputs: list[AutonomyArtifact] = [after_artifact]
    if outcome == "completed":
        if (
            step_state is None
            or step_state.status != "complete"
            or step_state.completion_fingerprint is None
        ):
            raise ValueError(
                "completed production resource receipt lacks exact step completion evidence"
            )
        for observed in step_state.artifacts:
            if (
                observed.integrity != "valid"
                or observed.currency != "current"
            ):
                raise ValueError(
                    "completed production resource receipt has non-current output evidence"
                )
            if observed.sha256 is None:
                continue
            output = AutonomyArtifact(path=observed.path, sha256=observed.sha256)
            _verify_artifact(root, output)
            exact_outputs.append(output)
    evidence_root = (
        session_root
        / "production_resources"
        / f"{state.action_sequence + 1:04d}-{reservation.workflow_step_id}"
    )
    receipt_path = evidence_root / "receipt.json"
    input_payload = {
        "reservation": reservation_artifact.model_dump(mode="json"),
        "advance": advance_artifact.model_dump(mode="json"),
        "after": after_artifact.model_dump(mode="json"),
    }
    receipt = ProductionResourceReceipt(
        contract_id=f"production-resource-{state.action_sequence + 1:04d}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        input_sha256=canonical_digest(input_payload),
        source_fingerprint=canonical_digest(
            {"input": input_payload, "reservation": reservation.source_fingerprint}
        ),
        producer="codex_blender_modeler.autonomy.service",
        producer_version="0.1.0",
        provenance=[reservation_artifact, advance_artifact, after_artifact],
        created_at=_utc_now(),
        session_id=state.session_id,
        reservation=reservation_artifact,
        workflow_step_id=reservation.workflow_step_id,
        workflow_input_fingerprint=workflow_input_fingerprint,
        host_attempt=advance_artifact,
        outputs=exact_outputs,
        reserved_delta=reservation.classification.delta,
        budget_before=reservation.budget_before,
        budget_after=reservation.budget_after,
        outcome=outcome,
        finished_at=_utc_now(),
    )
    write_immutable_json(root, receipt_path, receipt.model_dump(mode="json"))
    return [
        reservation_artifact,
        advance_artifact,
        after_artifact,
        artifact_for(root, receipt_path),
    ]


def _workflow_output_path(
    root: Path,
    workflow: WorkflowPlan,
    artifact_id: str,
) -> Path | None:
    """Resolve one planned exact workflow output by stable artifact identity."""

    matches = [
        root / output.path
        for step in workflow.steps
        for output in step.outputs
        if output.artifact_id == artifact_id
    ]
    if len(matches) > 1:
        raise ValueError(f"workflow artifact ID is ambiguous: {artifact_id}")
    return matches[0] if matches else None


def _quality_artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    created_at: datetime,
) -> QualityArtifact:
    """Convert one exact job artifact into Integrated Quality provenance."""

    resolved = path.resolve(strict=True)
    relative = resolved.relative_to(root.resolve()).as_posix()
    return QualityArtifact(
        artifact_id=artifact_id,
        kind=kind,
        relative_path=relative,
        sha256=sha256_file(resolved),
        producer=ProducerIdentity(name="autonomy-quality-gate", version="0.1.0"),
        produced_at=created_at,
    )


def _preproduction_profile(profile: QualityGateProfile) -> QualityGateProfile:
    """Derive an authoring gate where only the not-yet-built package axis is optional."""

    thresholds = [
        item.model_copy(update={"required": False})
        if item.axis == "production_readiness"
        else item
        for item in profile.axis_thresholds
    ]
    return profile.model_copy(
        update={
            "profile_id": f"{profile.profile_id}-preproduction",
            "axis_thresholds": thresholds,
            "gate_rules": [
                item for item in profile.gate_rules if item.axis != "production_readiness"
            ],
        }
    )


def _verify_integrated_quality_inputs(
    root: Path,
    state: AutonomyState,
    report: IntegratedQualityReport,
) -> None:
    """Re-hash every authoritative input before adopting an interrupted quality result."""

    if (
        report.job_id != state.job_id
        or report.workflow_id != state.workflow_id
        or report.dispatch_id != state.dispatch_id
    ):
        raise ValueError("integrated quality report belongs to another autonomy session")
    exact_inputs: dict[str, str] = {}
    for artifact in report.provenance.artifacts:
        path = ensure_autonomy_path(root, root / artifact.relative_path, must_exist=True)
        if not path.is_file() or sha256_file(path) != artifact.sha256:
            raise ValueError(
                f"integrated quality provenance changed: {artifact.relative_path}"
            )
        exact_inputs[artifact.relative_path] = artifact.sha256
    if report.provenance.input_sha256 != stable_json_digest(exact_inputs):
        raise ValueError("integrated quality provenance input digest is stale")


def _run_integrated_quality(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    *,
    stage: str,
) -> tuple[IntegratedQualityReport, AutonomyArtifact]:
    """Compose exact current V0.4-V0.7 evidence into one immutable four-axis report."""

    workflow_path, workflow = _workflow_plan(root, state.workflow_id)
    created_at = _utc_now()
    source_profile_path = session_root / "quality_gate_profile.json"
    source_profile = QualityGateProfile.model_validate_json(
        source_profile_path.read_text(encoding="utf-8")
    )
    profile = _preproduction_profile(source_profile) if stage == "preproduction" else source_profile
    profile_path = session_root / f"quality_gate_profile.{stage}.json"
    if not profile_path.exists():
        write_immutable_json(root, profile_path, profile.model_dump(mode="json"))
    elif sha256_file(profile_path) != hashlib.sha256(
        (profile.model_dump_json(indent=2) + "\n").encode("utf-8")
    ).hexdigest():
        stored = QualityGateProfile.model_validate_json(
            profile_path.read_text(encoding="utf-8")
        )
        if stored != profile:
            raise ValueError("integrated quality stage profile changed")

    qa_path = _workflow_output_path(root, workflow, "qa.run.visual_report")
    assembly = validate_job_assembly(
        state.job_id,
        write_report=False,
        raise_on_error=False,
    )
    validation_path = (
        session_root / "integrated_quality_inputs" / stage / "assembly_validation.json"
    )
    _write_or_adopt_immutable_json(
        root,
        validation_path,
        assembly.model_dump(mode="json"),
    )
    material_validation_path = _workflow_output_path(
        root, workflow, "material.contract_report"
    )
    material_fidelity_path = _workflow_output_path(
        root, workflow, "material.fidelity_report"
    )
    preflight_path = _workflow_output_path(root, workflow, "portable.preflight.report")
    package_path = _workflow_output_path(root, workflow, "portable.package_manifest")
    roundtrip_path = _workflow_output_path(root, workflow, "portable.roundtrip_report")
    accepted_repair = latest_accepted_package_repair(
        root, session_root, state, workflow
    )
    if accepted_repair is not None:
        if (
            accepted_repair.package_artifact is None
            or accepted_repair.roundtrip_artifact is None
        ):
            raise ValueError("accepted package repair has incomplete output evidence")
        package_path = root / accepted_repair.package_artifact.path
        roundtrip_path = root / accepted_repair.roundtrip_artifact.path
    hard_gate_root = session_root / "integrated_quality_inputs" / stage
    companion_root = hard_gate_root / "companions"
    if stage == "final" and not companion_root.exists():
        inspect_static_prop_authoring_companions(
            job_root=root,
            workflow_id=state.workflow_id,
            dispatch_id=state.dispatch_id,
            output_root_relative=companion_root.relative_to(root).as_posix(),
        )
    hard_gate_paths = HardGateEvidencePaths(
        blend=root / "blender" / "scene.blend",
        inventory=root / "reports" / "scene_inventory.json",
        validation=root / "reports" / "validation.json",
        modeling_plan=root / "analysis" / "modeling_plan.json",
        scene_spec=root / "analysis" / "scene_spec.json",
        assembly_companion=(
            companion_root / "assembly_companion_report.json"
            if (companion_root / "assembly_companion_report.json").is_file()
            else None
        ),
        topology_companion=(
            companion_root / "topology_companion_report.json"
            if (companion_root / "topology_companion_report.json").is_file()
            else None
        ),
        material_plan=root / "analysis" / "material_plan.json",
        package_manifest=(
            package_path if package_path is not None and package_path.is_file() else None
        ),
        roundtrip_validation=(
            roundtrip_path
            if roundtrip_path is not None and roundtrip_path.is_file()
            else None
        ),
    )

    visual = (
        VisualQAReport.model_validate_json(qa_path.read_text(encoding="utf-8"))
        if qa_path is not None and qa_path.is_file()
        else None
    )
    material_validation = (
        MaterialValidationReport.model_validate_json(
            material_validation_path.read_text(encoding="utf-8")
        )
        if material_validation_path is not None and material_validation_path.is_file()
        else None
    )
    material_fidelity = (
        MaterialFidelityReport.model_validate_json(
            material_fidelity_path.read_text(encoding="utf-8")
        )
        if material_fidelity_path is not None and material_fidelity_path.is_file()
        else None
    )
    preflight = (
        MeshPreflightReport.model_validate_json(preflight_path.read_text(encoding="utf-8"))
        if preflight_path is not None and preflight_path.is_file()
        else None
    )
    roundtrip = (
        RoundTripValidation.model_validate_json(roundtrip_path.read_text(encoding="utf-8"))
        if roundtrip_path is not None and roundtrip_path.is_file()
        else None
    )
    inputs: list[tuple[str, str, Path]] = [
        ("assembly", "assembly-validation", validation_path),
        ("workflow-plan", "workflow-plan", workflow_path),
    ]
    for identifier, kind, path in (
        ("visual-qa", "visual-qa", qa_path),
        ("material-contract", "material-validation", material_validation_path),
        ("material-fidelity", "material-fidelity", material_fidelity_path),
        ("mesh-preflight", "mesh-preflight", preflight_path),
        ("package-manifest", "portable-package", package_path),
        ("roundtrip", "clean-import-roundtrip", roundtrip_path),
    ):
        if path is not None and path.is_file():
            inputs.append((identifier, kind, path))
    known_paths = {path.resolve() for _identifier, _kind, path in inputs}
    for index, path in enumerate(
        discover_hard_gate_evidence_paths(root, hard_gate_paths),
        start=1,
    ):
        if path.resolve() in known_paths:
            continue
        inputs.append((f"hard-gate-{index:02d}", "hard-gate-evidence", path))
        known_paths.add(path.resolve())
    artifacts = [
        _quality_artifact(
            root,
            path,
            artifact_id=identifier,
            kind=kind,
            created_at=created_at,
        )
        for identifier, kind, path in inputs
    ]
    provenance = QualityProvenance(
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        source_fingerprint=profile.source_fingerprint,
        input_sha256=stable_json_digest(
            {item.relative_path: item.sha256 for item in artifacts}
        ),
        artifacts=artifacts,
    )
    availability = [
        EvidenceAvailability(
            evidence_id="reference-current",
            axis="reference_alignment",
            status="available" if visual is not None else "unavailable",
            artifact_id="visual-qa" if visual is not None else None,
            confidence=1.0 if visual is not None else 0,
            reason=(
                "Exact canonical V0.6 direct QA is available."
                if visual is not None
                else "Canonical V0.6 direct QA is not available."
            ),
        ),
        EvidenceAvailability(
            evidence_id="structural-current",
            axis="structural_integrity",
            status="available",
            artifact_id="assembly",
            confidence=1.0,
            reason="Exact current V0.4 assembly validation is available.",
        ),
        EvidenceAvailability(
            evidence_id="material-current",
            axis="material_fidelity",
            status=(
                "available"
                if material_validation is not None and material_fidelity is not None
                else "unavailable"
            ),
            artifact_id=(
                "material-fidelity"
                if material_validation is not None and material_fidelity is not None
                else None
            ),
            confidence=(
                1.0
                if material_validation is not None and material_fidelity is not None
                else 0
            ),
            reason=(
                "Exact V0.5 contract and raster fidelity reports are available."
                if material_validation is not None and material_fidelity is not None
                else "Complete V0.5 material evidence is unavailable."
            ),
        ),
        EvidenceAvailability(
            evidence_id="production-current",
            axis="production_readiness",
            status=("available" if roundtrip is not None else "unavailable"),
            artifact_id="roundtrip" if roundtrip is not None else None,
            confidence=1.0 if roundtrip is not None else 0,
            reason=(
                "Exact V0.7 clean-import round trip is available."
                if roundtrip is not None
                else "V0.7 clean-import round trip has not run yet."
            ),
        ),
    ]
    report = build_integrated_quality_report(
        report_id=f"{state.session_id}-{stage}",
        provenance=provenance,
        gate_profile=profile,
        gate_profile_sha256=sha256_file(profile_path),
        producer=ProducerIdentity(name="autonomy-quality-gate", version="0.1.0"),
        created_at=created_at,
        evidence_availability=availability,
        reference_evidence_id="reference-current",
        structural_evidence_id="structural-current",
        material_evidence_id="material-current",
        production_evidence_id="production-current",
        visual_qa=visual,
        assembly_reports=[assembly],
        material_validation=material_validation,
        material_fidelity=material_fidelity,
        mesh_preflight=preflight,
        roundtrip=roundtrip,
        notes=[
            "Quality acceptance is independent from workflow execution completion.",
            "Destination runtime parity is not evaluated by this engine-neutral report.",
        ],
    )
    report = apply_hard_gate_evidence(
        report,
        job_root=root,
        paths=hard_gate_paths,
        requirements=HardGateRequirements(
            require_build=True,
            require_assembly=stage == "final",
            require_topology=stage == "final",
            require_material_pbr=True,
            require_package=stage == "final",
            topology_profile="static_prop_closed",
        ),
    )
    output_dir = session_root / "integrated_quality" / stage
    write_integrated_quality_evidence(root, report, output_dir=output_dir)
    return report, artifact_for(root, output_dir / "integrated_quality_report.json")


_POLICY_GATE_MAP: dict[str, PolicyGateKind] = {
    "proxy_geometry": "generic_proxy_review",
    "detailed_geometry": "generic_detail_review",
    "material_swatches": "material_swatch_acknowledgement",
    "qa_review": "qa_review_acknowledgement",
    "optimization_plan": "optimization_plan",
    "final_package": "final_package_acknowledgement",
    "destination_handoff_plan": "destination_handoff_envelope_plan",
}


_POLICY_GATE_EXACT_OUTPUT_IDS: dict[PolicyGateKind, str] = {
    "material_swatch_acknowledgement": "material.report.manifest",
    "qa_review_acknowledgement": "qa.report.manifest",
    "optimization_plan": "portable.review_plan",
    "final_package_acknowledgement": "portable.report.manifest",
}


def _policy_gate_exact_output_path(
    root: Path,
    workflow: WorkflowPlan,
    *,
    boundary_step_id: str,
    gate_kind: PolicyGateKind,
) -> tuple[str, Path | None] | None:
    """Resolve exact gate evidence only from the boundary's prerequisite closure."""

    exact_output_id = _POLICY_GATE_EXACT_OUTPUT_IDS.get(gate_kind)
    if exact_output_id is None:
        return None
    steps = {step.step_id: step for step in workflow.steps}
    boundary = steps.get(boundary_step_id)
    if boundary is None:
        raise ValueError(f"policy gate boundary step is missing: {boundary_step_id}")
    prerequisites: set[str] = set()
    pending = list(boundary.depends_on)
    while pending:
        dependency_id = pending.pop()
        if dependency_id in prerequisites:
            continue
        dependency = steps.get(dependency_id)
        if dependency is None:
            raise ValueError(f"policy gate dependency is missing: {dependency_id}")
        prerequisites.add(dependency_id)
        pending.extend(dependency.depends_on)
    producers = [
        step.step_id
        for step in workflow.steps
        for output in step.outputs
        if output.artifact_id == exact_output_id
    ]
    if len(producers) > 1:
        raise ValueError(f"workflow artifact ID is ambiguous: {exact_output_id}")
    if not producers:
        return exact_output_id, None
    if producers[0] not in prerequisites:
        raise ValueError(
            f"routine-gate evidence is not a prerequisite of {boundary_step_id}: "
            f"{exact_output_id}"
        )
    exact_output_path = _workflow_output_path(root, workflow, exact_output_id)
    if exact_output_path is None:
        raise ValueError(f"workflow output disappeared: {exact_output_id}")
    return exact_output_id, exact_output_path


def _grant_policy_gate(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    profile: AutonomyProfile,
    budget: AutonomyBudget,
    authorization: RootAuthorization,
    production_state: dict[str, Any],
    usage_after: BudgetUsage,
) -> AutonomyArtifact:
    """Issue one exact consumed policy grant for an eligible routine workflow gate."""

    boundary = production_state.get("approval_boundary")
    if not isinstance(boundary, dict):
        raise ValueError("production approval state has no exact boundary")
    step_id = str(boundary["step_id"])
    gate = str(boundary["gate"])
    input_fingerprint = str(boundary["exact_fingerprint"])
    gate_kind = _POLICY_GATE_MAP.get(gate)
    if gate_kind is None:
        raise PermissionError(f"autonomy profile cannot authorize gate: {gate}")
    workflow_root = root / "workflows" / state.workflow_id
    workflow_plan_artifact = artifact_for(root, workflow_root / "plan.json")
    _workflow_path, workflow = _workflow_plan(root, state.workflow_id)
    dependencies: dict[str, str] = {}
    workflow_state_path = workflow_root / "state.json"
    if workflow_state_path.is_file():
        payload = json.loads(workflow_state_path.read_text(encoding="utf-8"))
        for item in payload.get("steps", []):
            if isinstance(item, dict) and item.get("completion_fingerprint"):
                dependencies[str(item.get("step_id"))] = str(
                    item["completion_fingerprint"]
                )
    exact_target_artifact = workflow_plan_artifact
    if gate_kind == "destination_handoff_envelope_plan":
        handoff_step = next(
            (item for item in workflow.steps if item.step_id == "destination.handoff"),
            None,
        )
        if handoff_step is None:
            raise ValueError("destination handoff gate has no workflow step")
        handoff_id = str(handoff_step.parameters.get("handoff_id", ""))
        handoff_plan_path = root / "handoffs" / handoff_id / "handoff_plan.json"
        if not handoff_plan_path.is_file():
            raise FileNotFoundError("exact destination handoff plan is missing")
        exact_target_artifact = artifact_for(root, handoff_plan_path)
        if exact_target_artifact.sha256 != input_fingerprint:
            raise ValueError("destination handoff plan differs from approval boundary")
        dependencies["destination.handoff.plan"] = exact_target_artifact.sha256
    exact_output = _policy_gate_exact_output_path(
        root,
        workflow,
        boundary_step_id=step_id,
        gate_kind=gate_kind,
    )
    if exact_output is not None:
        exact_output_id, exact_output_path = exact_output
        if exact_output_path is None or not exact_output_path.is_file():
            raise FileNotFoundError(
                f"exact routine-gate evidence is missing: {exact_output_id}"
            )
        exact_target_artifact = artifact_for(root, exact_output_path)
        dependencies["policy.exact_target"] = exact_target_artifact.sha256
    target_provenance = [workflow_plan_artifact]
    target_dependencies: list[AutonomyArtifact] = []
    if exact_target_artifact != workflow_plan_artifact:
        target_provenance.append(exact_target_artifact)
        target_dependencies.append(exact_target_artifact)
    target = PolicyGateTarget(
        contract_id=f"gate-target-{state.session_id}-{step_id.replace('.', '-')}",
        target_id=f"gate-target-{state.session_id}-{step_id.replace('.', '-')}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        input_sha256=input_fingerprint,
        source_fingerprint=canonical_digest(
            {
                "workflow_plan": workflow_plan_artifact.sha256,
                "input_fingerprint": input_fingerprint,
                "dependencies": dependencies,
            }
        ),
        producer="codex_blender_modeler.autonomy.service",
        producer_version="0.1.0",
        provenance=target_provenance,
        created_at=_utc_now(),
        session_id=state.session_id,
        workflow_step_id=step_id,
        workflow_input_fingerprint=input_fingerprint,
        gate_kind=gate_kind,
        workflow_plan=workflow_plan_artifact,
        dependency_completion_fingerprints=dependencies,
        dependency_artifacts=target_dependencies,
    )
    target_path = workflow_root / "policy_targets" / f"{step_id}.json"
    if target_path.is_file():
        stored_target = PolicyGateTarget.model_validate_json(
            target_path.read_text(encoding="utf-8")
        )
        if stored_target.model_copy(update={"created_at": target.created_at}) != target:
            raise ValueError("existing policy gate target differs from the current boundary")
    else:
        write_immutable_json(root, target_path, target.model_dump(mode="json"))
    target_artifact = artifact_for(root, target_path)
    root_artifact = artifact_for(root, session_root / "root_authorization.json")
    profile_artifact = artifact_for(root, session_root / "profile.json")
    budget_artifact = artifact_for(root, session_root / "budget.json")
    previous_sha = _latest_transition_policy_sha256(root, session_root)
    grant = authorize_policy_gate(
        root_authorization=authorization,
        root_authorization_artifact=root_artifact,
        root_authorization_sha256=root_artifact.sha256,
        profile=profile,
        profile_artifact=profile_artifact,
        profile_sha256=profile_artifact.sha256,
        budget=budget,
        budget_artifact=budget_artifact,
        budget_sha256=budget_artifact.sha256,
        gate_kind=gate_kind,
        step_id=step_id,
        workflow_input_fingerprint=input_fingerprint,
        gate_target=target_artifact,
        target_artifact=exact_target_artifact,
        budget_before=state.budget_usage,
        budget_after=usage_after,
        previous_authorization_sha256=previous_sha,
    )
    authorization_path = workflow_root / "policy_authorizations" / f"{step_id}.json"
    return persist_and_validate_policy_authorization(
        root,
        authorization_path,
        grant,
    )


def _record_preselected_controller_output(
    root: Path,
    state: AutonomyState,
    production: dict[str, Any],
) -> dict[str, Any] | None:
    """Complete only geometry steps whose exact output was already promoted by AQ."""

    production_state = production["state"]
    assignment_artifact = production_state.get("current_assignment")
    if not isinstance(assignment_artifact, dict):
        return None
    assignment_path = root / str(assignment_artifact["path"])
    assignment = DelegatedWorkAssignment.model_validate_json(
        assignment_path.read_text(encoding="utf-8")
    )
    if assignment.step_id not in {
        "reference.analyze",
        "geometry.modeling_plan",
        "geometry.proxy_author",
        "geometry.detail_author",
    }:
        return None
    for relative in assignment.controller_expected_outputs:
        if not (root / relative).is_file():
            return None
    return record_delegated_production_step(
        state.job_id,
        state.dispatch_id,
        production_state["controller_id"],
        step_id=assignment.step_id,
        input_fingerprint=assignment.input_fingerprint,
        note=(
            "Autonomous Quality controller recorded exact locally generated reference "
            "evidence or pre-evaluated promoted geometry; no advisory subagent wrote "
            "canonical data."
        ),
    )


def _authorize_material_candidate_promotion(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    profile: AutonomyProfile,
    budget: AutonomyBudget,
    authorization: RootAuthorization,
    usage_after: BudgetUsage,
    ranking_artifact: AutonomyArtifact,
    production_assignment: AutonomyArtifact,
) -> AutonomyArtifact:
    """Issue or recover one exact policy grant for a bounded V0.5 material ranking."""

    target_artifact = create_material_candidate_policy_target(
        root,
        session_root,
        ranking_artifact=ranking_artifact,
        production_assignment=production_assignment,
    )
    root_artifact = artifact_for(root, session_root / "root_authorization.json")
    profile_artifact = artifact_for(root, session_root / "profile.json")
    budget_artifact = artifact_for(root, session_root / "budget.json")
    previous_sha256 = _latest_transition_policy_sha256(root, session_root)
    grant = authorize_policy_gate(
        root_authorization=authorization,
        root_authorization_artifact=root_artifact,
        root_authorization_sha256=root_artifact.sha256,
        profile=profile,
        profile_artifact=profile_artifact,
        profile_sha256=profile_artifact.sha256,
        budget=budget,
        budget_artifact=budget_artifact,
        budget_sha256=budget_artifact.sha256,
        gate_kind="material_candidate_promotion",
        step_id="autonomy.material_candidate_promotion",
        workflow_input_fingerprint=ranking_artifact.sha256,
        gate_target=target_artifact,
        target_artifact=ranking_artifact,
        budget_before=state.budget_usage,
        budget_after=usage_after,
        previous_authorization_sha256=previous_sha256,
    )
    round_index = state.budget_usage.material_rounds + 1
    grant_path = (
        session_root
        / "policy_authorizations"
        / f"material-r{round_index:02d}.json"
    )
    if grant_path.is_file():
        stored = PolicyAuthorization.model_validate_json(
            grant_path.read_text(encoding="utf-8")
        )
        validate_policy_authorization(
            root,
            stored,
            expected_job_id=state.job_id,
            expected_workflow_id=state.workflow_id,
            expected_step_id="autonomy.material_candidate_promotion",
            expected_gate_kind="material_candidate_promotion",
            expected_input_fingerprint=ranking_artifact.sha256,
            expected_previous_authorization_sha256=previous_sha256,
        )
        if (
            stored.target_artifact != ranking_artifact
            or stored.budget_before != state.budget_usage
            or stored.budget_after != usage_after
        ):
            raise ValueError("existing material policy grant differs from this round")
    else:
        write_immutable_json(root, grant_path, grant.model_dump(mode="json"))
    return artifact_for(root, grant_path)


def _material_round_receipt_path(
    session_root: Path,
    state: AutonomyState,
) -> Path:
    """Return the immutable receipt path for the next uncommitted material round."""

    return (
        session_root
        / "mr"
        / f"r{state.budget_usage.material_rounds + 1:02d}"
        / "promotion_receipt.json"
    )


def _adopt_completed_material_round(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    budget: AutonomyBudget,
    previous_receipt: AutonomyArtifact | None,
    production_state: dict[str, Any],
) -> tuple[AutonomyState, AutonomyIterationReceipt] | None:
    """Recover a material promotion recorded before its AQ transition was published."""

    receipt_path = _material_round_receipt_path(session_root, state)
    if not receipt_path.is_file() or production_state.get("next_action") == "controller_author":
        return None
    receipt_artifact = artifact_for(root, receipt_path)
    receipt = MaterialCandidatePromotionReceipt.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    if (
        receipt.job_id != state.job_id
        or receipt.workflow_id != state.workflow_id
        or receipt.dispatch_id != state.dispatch_id
        or receipt.session_id != state.session_id
    ):
        raise ValueError("orphan material promotion belongs to another autonomy session")
    policy_path = _verify_artifact(root, receipt.policy_authorization)
    policy = PolicyAuthorization.model_validate_json(
        policy_path.read_text(encoding="utf-8")
    )
    usage = _consume_action(
        budget,
        state.budget_usage,
        material_rounds=1,
    )
    validate_policy_authorization(
        root,
        policy,
        expected_job_id=state.job_id,
        expected_workflow_id=state.workflow_id,
        expected_step_id="autonomy.material_candidate_promotion",
        expected_gate_kind="material_candidate_promotion",
        expected_input_fingerprint=receipt.ranking.sha256,
        expected_previous_authorization_sha256=_latest_transition_policy_sha256(
            root,
            session_root,
        ),
    )
    if policy.budget_before != state.budget_usage or policy.budget_after != usage:
        raise ValueError("orphan material policy budget does not match current AQ state")
    authored_path = ensure_autonomy_path(
        root,
        root / receipt.workflow_authored_plan_path,
        must_exist=True,
    )
    if sha256_file(authored_path) != receipt.workflow_authored_plan_sha256:
        raise ValueError("orphan material promotion output is stale")
    return _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="run_material_round",
        budget_usage=usage,
        update={"status": "running", "next_action": "advance_production"},
        policy_authorization=receipt.policy_authorization,
        material_promotion_receipt=receipt_artifact,
    )


def _run_material_round(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    profile: AutonomyProfile,
    budget: AutonomyBudget,
    authorization: RootAuthorization,
    previous_receipt: AutonomyArtifact | None,
    production_state: dict[str, Any],
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Evaluate one bounded V0.5 round and promote only the final selected plan."""

    production_assignment = AutonomyArtifact.model_validate(
        production_state.get("current_assignment")
    )
    assignment_path = _verify_artifact(root, production_assignment)
    assignment = DelegatedWorkAssignment.model_validate_json(
        assignment_path.read_text(encoding="utf-8")
    )
    if assignment.step_id != "material.author":
        raise ValueError("material round called outside material.author")
    round_index = state.budget_usage.material_rounds + 1
    usage = _consume_action(
        budget,
        state.budget_usage,
        material_rounds=1,
    )
    previous_ranking = None
    if round_index > 1:
        previous_path = session_root / "mr" / f"r{round_index - 1:02d}" / "ranking.json"
        if not previous_path.is_file():
            raise FileNotFoundError("previous material-round ranking is missing")
        previous_ranking = artifact_for(root, previous_path)
    _ranking, ranking_artifact = prepare_material_candidate_round(
        root,
        session_root,
        production_assignment=production_assignment,
        candidate_limit=2,
        round_index=round_index,
        previous_ranking=previous_ranking,
    )
    if round_index < budget.material_rounds:
        return _transition(
            root,
            session_root,
            state,
            previous_receipt,
            action="run_material_round",
            budget_usage=usage,
            update={
                "status": "running",
                "phase": "material_authoring",
                "next_action": "run_material_round",
            },
            host_attempt_evidence=[ranking_artifact],
        )
    policy_artifact = _authorize_material_candidate_promotion(
        root,
        session_root,
        state,
        profile,
        budget,
        authorization,
        usage,
        ranking_artifact,
        production_assignment,
    )
    _receipt, receipt_artifact = promote_material_candidate_to_workflow_authored(
        root,
        session_root,
        ranking_artifact=ranking_artifact,
        production_assignment=production_assignment,
        policy_authorization_artifact=policy_artifact,
    )
    record_delegated_production_step(
        state.job_id,
        state.dispatch_id,
        production_state["controller_id"],
        step_id=assignment.step_id,
        input_fingerprint=assignment.input_fingerprint,
        note=(
            "Autonomous Quality selected a bounded local V0.5 candidate; the existing "
            "V0.8 material promotion remains authoritative."
        ),
    )
    return _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="run_material_round",
        budget_usage=usage,
        update={"status": "running", "next_action": "advance_production"},
        policy_authorization=policy_artifact,
        material_promotion_receipt=receipt_artifact,
    )


def _advance_production_action(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    profile: AutonomyProfile,
    budget: AutonomyBudget,
    authorization: RootAuthorization,
    previous_receipt: AutonomyArtifact | None,
) -> tuple[AutonomyState, AutonomyIterationReceipt] | None:
    """Advance one existing production-controller boundary without bypassing exclusions."""

    production = get_asset_production_dispatch_status(state.job_id, state.dispatch_id)
    production_state = production["state"]
    next_action = str(production_state["next_action"])
    recovered_material = _adopt_completed_material_round(
        root,
        session_root,
        state,
        budget,
        previous_receipt,
        production_state,
    )
    if recovered_material is not None:
        return recovered_material
    if next_action == "bind_client_task":
        return _transition(
            root,
            session_root,
            state,
            previous_receipt,
            action="advance_production",
            budget_usage=_consume_action(budget, state.budget_usage),
            update={
                "status": "waiting_for_controller",
                "next_action": "await_controller_output",
                "warnings": [
                    *state.warnings,
                    "Client-mediated production requires an exact restricted task binding.",
                ],
            },
        )
    if next_action == "controller_author":
        current_assignment = production_state.get("current_assignment")
        if current_assignment is not None:
            assignment_artifact = AutonomyArtifact.model_validate(current_assignment)
            assignment = DelegatedWorkAssignment.model_validate_json(
                _verify_artifact(root, assignment_artifact).read_text(encoding="utf-8")
            )
            if assignment.step_id == "material.author":
                if state.budget_usage.material_rounds >= budget.material_rounds:
                    return _route_budget_exhaustion(
                        root,
                        session_root,
                        state,
                        budget,
                        previous_receipt,
                        exhausted_dimension="material_rounds",
                    )
                return _run_material_round(
                    root,
                    session_root,
                    state,
                    profile,
                    budget,
                    authorization,
                    previous_receipt,
                    production_state,
                )
        recorded = _record_preselected_controller_output(root, state, production)
        if recorded is None:
            if state.status == "waiting_for_controller":
                return None
            return _transition(
                root,
                session_root,
                state,
                previous_receipt,
                action="advance_production",
                budget_usage=_consume_action(budget, state.budget_usage),
                update={
                    "status": "waiting_for_controller",
                    "next_action": "await_controller_output",
                    "warnings": [
                        *state.warnings,
                        "The controller must author only the exact current production assignment.",
                    ],
                },
            )
        return _transition(
            root,
            session_root,
            state,
            previous_receipt,
            action="advance_production",
            budget_usage=_consume_action(budget, state.budget_usage),
            update={"status": "running", "next_action": "advance_production"},
        )
    if next_action in {"request_generic_approval", "request_specialized_approval"}:
        boundary = production_state.get("approval_boundary") or {}
        if boundary.get("gate") not in _POLICY_GATE_MAP:
            raise PermissionError(
                f"restricted approval remains interactive: {boundary.get('gate')}"
            )
        if boundary.get("gate") == "qa_review":
            quality_path = (
                session_root
                / "integrated_quality"
                / "preproduction"
                / "integrated_quality_report.json"
            )
            if quality_path.is_file():
                report = IntegratedQualityReport.model_validate_json(
                    quality_path.read_text(encoding="utf-8")
                )
                quality_artifact = artifact_for(root, quality_path)
            else:
                report, quality_artifact = _run_integrated_quality(
                    root,
                    session_root,
                    state,
                    stage="preproduction",
                )
            _verify_integrated_quality_inputs(root, state, report)
            usage = _consume_action(
                budget,
                state.budget_usage,
                total_quality_evaluations=1,
            )
            if not report.quality_accepted:
                reason = _review_termination_reason(state, report)
                return _transition(
                    root,
                    session_root,
                    state,
                    previous_receipt,
                    action="run_integrated_quality",
                    budget_usage=usage,
                    update={
                        "status": "running",
                        "phase": "review_bundle",
                        "next_action": "build_review_bundle",
                        "last_quality_report": quality_artifact,
                        "pending_terminal_reason": reason,
                        "warnings": [
                            *state.warnings,
                            f"Preproduction quality requires review: {reason}.",
                        ],
                    },
                )
        else:
            usage = _consume_action(budget, state.budget_usage)
            quality_artifact = state.last_quality_report
        grant_artifact = _grant_policy_gate(
            root,
            session_root,
            state,
            profile,
            budget,
            authorization,
            production_state,
            usage,
        )
        if boundary.get("gate") == "destination_handoff_plan":
            _workflow_path, workflow = _workflow_plan(root, state.workflow_id)
            handoff_step = next(
                (item for item in workflow.steps if item.step_id == "destination.handoff"),
                None,
            )
            if handoff_step is None:
                raise ValueError("destination handoff approval has no workflow step")
            handoff_id = str(handoff_step.parameters.get("handoff_id", ""))
            profile_id = str(handoff_step.parameters.get("profile_id", ""))
            package_id = str(handoff_step.parameters.get("package_id", ""))
            validation_path = (
                root
                / "exports"
                / "destination_handoffs"
                / profile_id
                / package_id
                / handoff_id
                / "destination_handoff_validation.json"
            )
            if validation_path.is_file():
                existing_handoff = validate_destination_handoff(
                    state.job_id,
                    profile_id=profile_id,
                    package_id=package_id,
                    handoff_id=handoff_id,
                )
                if not existing_handoff.ok:
                    raise RuntimeError("existing destination handoff is invalid")
            else:
                generate_destination_handoff(
                    state.job_id,
                    handoff_id,
                    approved_plan_sha256=str(boundary["exact_fingerprint"]),
                )
        advance_delegated_production_controller(
            state.job_id,
            state.dispatch_id,
            production_state["controller_id"],
            max_host_steps=1,
        )
        return _transition(
            root,
            session_root,
            state,
            previous_receipt,
            action="authorize_routine_gate",
            budget_usage=usage,
            update={
                "status": "running",
                "next_action": "advance_production",
                "last_quality_report": quality_artifact,
            },
            policy_authorization=grant_artifact,
        )
    if next_action == "resume_host":
        decision, reservation_artifact, input_fingerprint = (
            _reserve_production_host_step(
                root,
                session_root,
                state,
                budget,
                production_state,
            )
        )
        if not decision.allowed or reservation_artifact is None:
            return _route_budget_exhaustion(
                root,
                session_root,
                state,
                budget,
                previous_receipt,
                exhausted_dimension=decision.exhausted_dimension,
            )
        result = advance_delegated_production_controller(
            state.job_id,
            state.dispatch_id,
            production_state["controller_id"],
            max_host_steps=1,
        )
        resource_evidence = _record_production_resource_receipt(
            root,
            session_root,
            state,
            decision,
            reservation_artifact,
            input_fingerprint,
            result,
        )
        after_action = str(result["state"]["next_action"])
        return _transition(
            root,
            session_root,
            state,
            previous_receipt,
            action="advance_production",
            budget_usage=decision.usage,
            update={
                "status": (
                    "waiting_for_controller"
                    if after_action == "controller_author"
                    else "running"
                ),
                "next_action": (
                    "await_controller_output"
                    if after_action == "controller_author"
                    else "advance_production"
                ),
            },
            host_attempt_evidence=resource_evidence,
        )
    if next_action in {
        "delegate_read_only",
        "run_postflight_audit",
        "plan_destination_handoff",
    }:
        usage = _consume_action(budget, state.budget_usage)
        result = advance_delegated_production_controller(
            state.job_id,
            state.dispatch_id,
            production_state["controller_id"],
            max_host_steps=1,
        )
        after_action = str(result["state"]["next_action"])
        return _transition(
            root,
            session_root,
            state,
            previous_receipt,
            action="advance_production",
            budget_usage=usage,
            update={
                "status": (
                    "waiting_for_controller"
                    if after_action == "controller_author"
                    else "running"
                ),
                "next_action": (
                    "await_controller_output"
                    if after_action == "controller_author"
                    else "advance_production"
                ),
            },
        )
    if next_action == "completed":
        return _transition(
            root,
            session_root,
            state,
            previous_receipt,
            action="advance_production",
            budget_usage=_consume_action(budget, state.budget_usage),
            update={
                "status": "running",
                "phase": "integrated_quality",
                "next_action": "run_integrated_quality",
            },
        )
    if next_action == "failed" and production_state.get("current_step_id") in {
        "portable.package",
        "portable.roundtrip",
    }:
        _workflow_path, workflow = _workflow_plan(root, state.workflow_id)
        failed_step_id = str(production_state["current_step_id"])
        try:
            prepared = prepare_package_repair(
                root,
                session_root,
                state,
                budget,
                workflow,
                failed_step_id=failed_step_id,
            )
        except (FileNotFoundError, PermissionError, ValueError):
            return _terminal_without_bundle(
                root,
                session_root,
                state,
                budget,
                previous_receipt,
                status="blocked",
                reason="stale_or_tampered",
            )
        if prepared.decision.disposition == "repair":
            if prepared.plan_artifact is None or prepared.decision.repair_plan is None:
                raise ValueError("repair decision lacks its exact immutable plan")
            executed = execute_package_repair(
                root,
                session_root,
                state,
                workflow,
                plan_artifact=prepared.plan_artifact,
            )
            evidence = [
                prepared.failure_artifact,
                prepared.plan_artifact,
                executed.receipt_artifact,
            ]
            if executed.package_artifact is not None:
                evidence.append(executed.package_artifact)
            if executed.roundtrip_artifact is not None:
                evidence.append(executed.roundtrip_artifact)
            if executed.receipt.package_accepted:
                return _transition(
                    root,
                    session_root,
                    state,
                    previous_receipt,
                    action="advance_production",
                    budget_usage=prepared.decision.budget_after,
                    update={
                        "status": "running",
                        "phase": "integrated_quality",
                        "next_action": "run_integrated_quality",
                        "warnings": [
                            *state.warnings,
                            (
                                "One derived-only package repair produced a fresh passed "
                                "clean-import round trip."
                            ),
                        ],
                    },
                    host_attempt_evidence=evidence,
                )
            return _transition(
                root,
                session_root,
                state,
                previous_receipt,
                action="advance_production",
                budget_usage=prepared.decision.budget_after,
                update={
                    "status": "running",
                    "phase": "production_repair",
                    "next_action": "terminalize",
                    "pending_terminal_reason": "host_failure",
                    "warnings": [
                        *state.warnings,
                        "The one reserved package repair failed; no package was accepted.",
                    ],
                },
                host_attempt_evidence=evidence,
            )
        if prepared.decision.reason_code == "package_repair_budget_exhausted":
            return _route_budget_exhaustion(
                root,
                session_root,
                state,
                budget,
                previous_receipt,
                exhausted_dimension="package_repairs",
            )
        return _terminal_without_bundle(
            root,
            session_root,
            state,
            budget,
            previous_receipt,
            status="blocked",
            reason="host_failure",
        )
    if next_action == "failed" and state.last_quality_report is not None:
        prior_quality = IntegratedQualityReport.model_validate_json(
            _verify_artifact(root, state.last_quality_report).read_text(encoding="utf-8")
        )
        if not prior_quality.quality_accepted:
            return _transition(
                root,
                session_root,
                state,
                previous_receipt,
                action="advance_production",
                budget_usage=_consume_action(budget, state.budget_usage),
                update={
                    "status": "running",
                    "phase": "review_bundle",
                    "next_action": "build_review_bundle",
                    "pending_terminal_reason": "host_failure",
                    "warnings": [
                        *state.warnings,
                        (
                            "Production failed after non-passing review evidence; "
                            "preserving the best-known asset in a review bundle."
                        ),
                    ],
                },
            )
    if next_action in {"blocked", "failed", "cancelled"}:
        terminal_reason = {
            "blocked": "restricted_scope_required",
            "failed": "host_failure",
            "cancelled": "cancelled",
        }[next_action]
        return _terminal_without_bundle(
            root,
            session_root,
            state,
            budget,
            previous_receipt,
            status=("cancelled" if next_action == "cancelled" else "blocked"),
            reason=terminal_reason,
        )
    if next_action in {"plan_visual_convergence", "run_visual_convergence"}:
        raise PermissionError(
            f"{next_action} is outside the verified autonomous_static_prop_v1 route"
        )
    raise RuntimeError(f"unsupported production controller action: {next_action}")


def _write_terminal_intent(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    *,
    status: str,
    reason: str,
    quality: AutonomyArtifact | None = None,
    package: AutonomyArtifact | None = None,
    roundtrip: AutonomyArtifact | None = None,
    review_bundle: AutonomyArtifact | None = None,
    destination_handoff: AutonomyArtifact | None = None,
) -> AutonomyTerminalIntent:
    """Publish exact recoverable terminal inputs before changing the authoritative state."""

    _verify_terminal_outputs(
        root,
        session_root,
        state,
        status=status,
        reason=reason,
        quality=quality,
        package=package,
        roundtrip=roundtrip,
        review_bundle=review_bundle,
        destination_handoff=destination_handoff,
    )

    state_before = artifact_for(
        root,
        session_root / "transitions" / f"{state.action_sequence:04d}" / "state.json",
    )
    artifacts = [
        state_before,
        *([quality] if quality else []),
        *([package] if package else []),
        *([roundtrip] if roundtrip else []),
        *([review_bundle] if review_bundle else []),
        *([destination_handoff] if destination_handoff else []),
    ]
    payload = {
        "state_before": state_before.sha256,
        "status": status,
        "reason": reason,
        "quality": quality.sha256 if quality else None,
        "package": package.sha256 if package else None,
        "roundtrip": roundtrip.sha256 if roundtrip else None,
        "review": review_bundle.sha256 if review_bundle else None,
        "destination_handoff": (
            destination_handoff.sha256 if destination_handoff else None
        ),
    }
    intent = AutonomyTerminalIntent(
        contract_id=f"terminal-intent-{state.session_id}",
        intent_id=f"terminal-intent-{state.session_id}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        input_sha256=state_before.sha256,
        source_fingerprint=canonical_digest(payload),
        producer="codex_blender_modeler.autonomy.service",
        producer_version="0.1.0",
        provenance=artifacts,
        created_at=_utc_now(),
        session_id=state.session_id,
        status=status,  # type: ignore[arg-type]
        reason=reason,  # type: ignore[arg-type]
        state_before=state_before,
        integrated_quality_report=quality,
        package_manifest=package,
        roundtrip_validation=roundtrip,
        review_bundle_manifest=review_bundle,
        destination_handoff_envelope=destination_handoff,
    )
    intent_path = session_root / "terminal_intent.json"
    if _native_is_file(intent_path):
        stored = AutonomyTerminalIntent.model_validate_json(
            _native_read_text(intent_path)
        )
        if stored.model_copy(update={"created_at": intent.created_at}) != intent:
            raise ValueError("existing terminal intent differs from the current terminal action")
    else:
        write_immutable_json(root, intent_path, intent.model_dump(mode="json"))
    return intent


def _verify_integrated_quality_terminal_artifact(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    artifact: AutonomyArtifact,
) -> IntegratedQualityReport:
    """Verify one exact AQ report, sidecar manifest, profile, and source map."""

    report_path = _verify_artifact(root, artifact)
    report = IntegratedQualityReport.model_validate_json(
        _native_read_text(report_path)
    )
    _verify_integrated_quality_inputs(root, state, report)
    manifest_path = report_path.with_name("integrated_quality_report.manifest.json")
    if not _native_is_file(manifest_path):
        raise FileNotFoundError("terminal integrated quality manifest is missing")
    manifest = IntegratedQualityReportManifest.model_validate_json(
        _native_read_text(manifest_path)
    )
    expected_identity = (state.job_id, state.workflow_id, state.dispatch_id)
    if (
        (report.job_id, report.workflow_id, report.dispatch_id) != expected_identity
        or (manifest.job_id, manifest.workflow_id, manifest.dispatch_id)
        != expected_identity
        or manifest.report_id != report.report_id
        or manifest.json_path != artifact.path
        or manifest.json_sha256 != artifact.sha256
        or manifest.source_fingerprint != report.provenance.source_fingerprint
        or manifest.producer != report.producer
        or manifest.created_at != report.created_at
    ):
        raise ValueError("terminal integrated quality manifest binding is stale")
    if manifest.pdf_path is not None:
        pdf_path = ensure_autonomy_path(root, root / manifest.pdf_path, must_exist=True)
        if not _native_is_file(pdf_path) or sha256_file(pdf_path) != manifest.pdf_sha256:
            raise ValueError("terminal integrated quality PDF binding is stale")

    matching_profiles: list[QualityGateProfile] = []
    for profile_path in (
        session_root / "quality_gate_profile.json",
        session_root / "quality_gate_profile.preproduction.json",
        session_root / "quality_gate_profile.final.json",
    ):
        if (
            not _native_is_file(profile_path)
            or sha256_file(profile_path) != report.gate_profile_sha256
        ):
            continue
        matching_profiles.append(
            QualityGateProfile.model_validate_json(
                _native_read_text(profile_path)
            )
        )
    if not matching_profiles:
        raise ValueError("terminal integrated quality profile binding is missing")
    if not any(
        profile.profile_id == report.gate_profile_id
        and (profile.job_id, profile.workflow_id, profile.dispatch_id) == expected_identity
        and profile.source_fingerprint == report.provenance.source_fingerprint
        for profile in matching_profiles
    ):
        raise ValueError("terminal integrated quality profile or source binding is stale")
    return report


def _verify_v07_hashed_artifact(root: Path, artifact: Any, *, label: str) -> Path:
    """Verify one contained V0.7 hashed artifact without changing package evidence."""

    path = ensure_autonomy_path(root, root / artifact.path, must_exist=True)
    if not _native_is_file(path) or sha256_file(path) != artifact.sha256:
        raise ValueError(f"terminal {label} is stale or tampered: {artifact.path}")
    return path


def _verify_quality_passed_package(
    root: Path,
    terminal_job_id: str,
    package_artifact: AutonomyArtifact,
    roundtrip_artifact: AutonomyArtifact,
) -> tuple[ExportPackageManifest, RoundTripValidation]:
    """Revalidate immutable V0.7 package receipts and clean-import dependencies."""

    package_path = _verify_artifact(root, package_artifact)
    package = ExportPackageManifest.model_validate_json(
        _native_read_text(package_path)
    )
    if package.job_id != terminal_job_id or package.status != "complete":
        raise ValueError("terminal package identity or completion status is invalid")
    package_root = ensure_autonomy_path(
        root,
        root / package.package_root,
        must_exist=True,
    )
    if not package_root.is_dir() or package_path != package_root / "package_manifest.json":
        raise ValueError("terminal package manifest is outside its declared package root")
    _verify_package_receipts(root, package_root, package, package_path)
    require_unchanged_source(package.source, root, terminal_job_id)

    roundtrip_path = _verify_artifact(root, roundtrip_artifact)
    roundtrip = RoundTripValidation.model_validate_json(
        _native_read_text(roundtrip_path)
    )
    if (
        roundtrip.job_id != terminal_job_id
        or roundtrip.package_id != package.package_id
        or roundtrip.profile_id != package.profile_id
        or roundtrip.run_id != package.run_id
        or roundtrip.status != "passed"
        or not roundtrip.ok
        or set(roundtrip.expected_semantic_ids) != set(package.semantic_ids)
        or set(roundtrip.expected_material_ids) != set(package.material_ids)
        or roundtrip.package_manifest.path != package_artifact.path
        or roundtrip.package_manifest.sha256 != package_artifact.sha256
    ):
        raise ValueError("terminal roundtrip is not bound to the accepted package")
    _verify_v07_hashed_artifact(
        root,
        roundtrip.package_manifest,
        label="roundtrip package manifest",
    )
    _verify_v07_hashed_artifact(
        root,
        roundtrip.imported_inventory,
        label="roundtrip inventory",
    )
    return package, roundtrip


def _verify_review_terminal_bundle(
    root: Path,
    state: AutonomyState,
    reason: str,
    quality_artifact: AutonomyArtifact,
    review_artifact: AutonomyArtifact,
) -> ReviewBundleManifest:
    """Validate the exact non-production review bundle and its quality binding."""

    from .reporting import validate_review_bundle

    review_path = _verify_artifact(root, review_artifact)
    declared = ReviewBundleManifest.model_validate_json(
        _native_read_text(review_path)
    )
    validated, _receipt = validate_review_bundle(root, declared.bundle_id)
    if (
        validated != declared
        or (validated.job_id, validated.workflow_id, validated.dispatch_id)
        != (state.job_id, state.workflow_id, state.dispatch_id)
        or validated.session_id != state.session_id
        or validated.termination_reason != reason
        or validated.integrated_quality_report.sha256 != quality_artifact.sha256
    ):
        raise ValueError("terminal review bundle binding is stale")
    return validated


def _verify_destination_handoff_terminal(
    root: Path,
    state: AutonomyState,
    handoff_artifact: AutonomyArtifact,
) -> None:
    """Revalidate every nested destination-handoff receipt at terminal status time."""

    manifest_path = _verify_artifact(root, handoff_artifact)
    manifest = DestinationHandoffManifest.model_validate_json(
        _native_read_text(manifest_path)
    )
    if manifest.job_id != state.job_id:
        raise ValueError("terminal destination handoff belongs to another job")
    validation = validate_destination_handoff(
        state.job_id,
        profile_id=manifest.profile_id,
        package_id=manifest.package_id,
        handoff_id=manifest.handoff_id,
    )
    if (
        not validation.ok
        or validation.status not in {"passed", "warning"}
        or validation.handoff_manifest_sha256 != handoff_artifact.sha256
    ):
        raise ValueError("terminal destination handoff validation is stale or failed")


def _verify_terminal_outputs(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    *,
    status: str,
    reason: str,
    quality: AutonomyArtifact | None,
    package: AutonomyArtifact | None,
    roundtrip: AutonomyArtifact | None,
    review_bundle: AutonomyArtifact | None,
    destination_handoff: AutonomyArtifact | None,
) -> None:
    """Verify mutually exclusive terminal deliveries before state publication or recovery."""

    delivery = [package, roundtrip, review_bundle, destination_handoff]
    report = (
        _verify_integrated_quality_terminal_artifact(
            root,
            session_root,
            state,
            quality,
        )
        if quality is not None
        else None
    )
    if status == "quality_passed":
        if reason != "quality_target_reached":
            raise ValueError("quality-passed terminal has an invalid reason")
        if report is None or not report.quality_accepted or report.outcome != "passed":
            raise ValueError("quality-passed terminal requires accepted integrated quality")
        if package is None or roundtrip is None or review_bundle is not None:
            raise ValueError("quality-passed terminal has incomplete or conflicting delivery")
        _verify_quality_passed_package(root, state.job_id, package, roundtrip)
        if destination_handoff is not None:
            _verify_destination_handoff_terminal(root, state, destination_handoff)
        return
    if status == "review_required":
        if reason == "quality_target_reached":
            raise ValueError("review-required terminal cannot claim the quality target")
        if report is None or report.quality_accepted or report.outcome == "passed":
            raise ValueError("review-required terminal requires non-passing integrated quality")
        if review_bundle is None or any(
            item is not None for item in (package, roundtrip, destination_handoff)
        ):
            raise ValueError("review-required terminal has incomplete or conflicting delivery")
        _verify_review_terminal_bundle(root, state, reason, quality, review_bundle)
        return
    if quality is not None or any(item is not None for item in delivery):
        raise ValueError("non-delivery terminal cannot carry quality or delivery artifacts")


def _verify_terminal_evidence(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    terminal: AutonomyTerminal,
) -> None:
    """Reconstruct and verify one terminal identity, state, provenance, and delivery graph."""

    if (
        terminal.job_id != state.job_id
        or terminal.workflow_id != state.workflow_id
        or terminal.dispatch_id != state.dispatch_id
        or terminal.session_id != state.session_id
        or terminal.reason != state.terminal_reason
    ):
        raise ValueError("autonomy terminal identity or reason differs from final state")
    expected_state_status = (
        "completed"
        if terminal.status in {"quality_passed", "review_required"}
        else terminal.status
    )
    if (
        state.status != expected_state_status
        or state.phase != "terminal"
        or state.next_action != "none"
        or terminal.best_known_candidate != state.best_known_candidate
    ):
        raise ValueError("autonomy terminal status differs from final state")
    current_state_path = (
        session_root
        / "transitions"
        / f"{state.action_sequence:04d}"
        / "state.json"
    )
    current_state = artifact_for(root, current_state_path)
    stored_state = AutonomyState.model_validate_json(
        current_state_path.read_text(encoding="utf-8")
    )
    if (
        stored_state != state
        or terminal.final_state != current_state
        or terminal.input_sha256 != current_state.sha256
    ):
        raise ValueError("autonomy terminal final-state binding is stale")
    expected_provenance = [
        current_state,
        *(
            [terminal.integrated_quality_report]
            if terminal.integrated_quality_report is not None
            else []
        ),
        *([terminal.package_manifest] if terminal.package_manifest is not None else []),
        *(
            [terminal.roundtrip_validation]
            if terminal.roundtrip_validation is not None
            else []
        ),
        *(
            [terminal.review_bundle_manifest]
            if terminal.review_bundle_manifest is not None
            else []
        ),
        *(
            [terminal.destination_handoff_envelope]
            if terminal.destination_handoff_envelope is not None
            else []
        ),
    ]
    expected_source = canonical_digest(
        {
            "state": current_state.sha256,
            "quality": (
                terminal.integrated_quality_report.sha256
                if terminal.integrated_quality_report
                else None
            ),
            "package": (
                terminal.package_manifest.sha256 if terminal.package_manifest else None
            ),
            "roundtrip": (
                terminal.roundtrip_validation.sha256
                if terminal.roundtrip_validation
                else None
            ),
            "review": (
                terminal.review_bundle_manifest.sha256
                if terminal.review_bundle_manifest
                else None
            ),
            "destination_handoff": (
                terminal.destination_handoff_envelope.sha256
                if terminal.destination_handoff_envelope
                else None
            ),
        }
    )
    if terminal.provenance != expected_provenance or terminal.source_fingerprint != expected_source:
        raise ValueError("autonomy terminal provenance is stale or self-inconsistent")
    for artifact in expected_provenance:
        _verify_artifact(root, artifact)
    _verify_terminal_outputs(
        root,
        session_root,
        state,
        status=terminal.status,
        reason=terminal.reason,
        quality=terminal.integrated_quality_report,
        package=terminal.package_manifest,
        roundtrip=terminal.roundtrip_validation,
        review_bundle=terminal.review_bundle_manifest,
        destination_handoff=terminal.destination_handoff_envelope,
    )


def _terminal_contract(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    *,
    status: str,
    reason: str,
    quality: AutonomyArtifact | None = None,
    package: AutonomyArtifact | None = None,
    roundtrip: AutonomyArtifact | None = None,
    review_bundle: AutonomyArtifact | None = None,
    destination_handoff: AutonomyArtifact | None = None,
) -> AutonomyTerminal:
    """Publish one immutable terminal contract after the final state transition exists."""

    final_state = artifact_for(
        root,
        session_root / "transitions" / f"{state.action_sequence:04d}" / "state.json",
    )
    terminal = AutonomyTerminal(
        contract_id=f"terminal-{state.session_id}",
        terminal_id=f"terminal-{state.session_id}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        input_sha256=final_state.sha256,
        source_fingerprint=canonical_digest(
            {
                "state": final_state.sha256,
                "quality": quality.sha256 if quality else None,
                "package": package.sha256 if package else None,
                "roundtrip": roundtrip.sha256 if roundtrip else None,
                "review": review_bundle.sha256 if review_bundle else None,
                "destination_handoff": (
                    destination_handoff.sha256 if destination_handoff else None
                ),
            }
        ),
        producer="codex_blender_modeler.autonomy.service",
        producer_version="0.1.0",
        provenance=[
            final_state,
            *([quality] if quality else []),
            *([package] if package else []),
            *([roundtrip] if roundtrip else []),
            *([review_bundle] if review_bundle else []),
            *([destination_handoff] if destination_handoff else []),
        ],
        created_at=_utc_now(),
        session_id=state.session_id,
        status=status,  # type: ignore[arg-type]
        reason=reason,  # type: ignore[arg-type]
        final_state=final_state,
        best_known_candidate=state.best_known_candidate,
        integrated_quality_report=quality,
        package_manifest=package,
        roundtrip_validation=roundtrip,
        review_bundle_manifest=review_bundle,
        destination_handoff_envelope=destination_handoff,
    )
    terminal_path = session_root / "terminal.json"
    if _native_is_file(terminal_path):
        stored = AutonomyTerminal.model_validate_json(
            _native_read_text(terminal_path)
        )
        if stored.model_copy(update={"created_at": terminal.created_at}) != terminal:
            raise ValueError("existing terminal contract differs from recovery evidence")
        _verify_terminal_evidence(root, session_root, state, stored)
        return stored
    _verify_terminal_evidence(root, session_root, state, terminal)
    write_immutable_json(root, terminal_path, terminal.model_dump(mode="json"))
    return terminal


def _recover_terminal_contract(
    root: Path,
    session_root: Path,
    state: AutonomyState,
) -> AutonomyTerminal:
    """Recover a missing terminal contract only from exact pre-transition intent evidence."""

    intent_path = session_root / "terminal_intent.json"
    if not _native_is_file(intent_path):
        raise ValueError("terminal autonomy state has no recoverable terminal intent")
    intent = AutonomyTerminalIntent.model_validate_json(
        _native_read_text(intent_path)
    )
    if (
        intent.job_id != state.job_id
        or intent.workflow_id != state.workflow_id
        or intent.dispatch_id != state.dispatch_id
        or intent.session_id != state.session_id
        or intent.reason != state.terminal_reason
    ):
        raise ValueError("terminal intent identity or reason differs from final state")
    for artifact in intent.provenance:
        _verify_artifact(root, artifact)
    expected_intent_source = canonical_digest(
        {
            "state_before": intent.state_before.sha256,
            "status": intent.status,
            "reason": intent.reason,
            "quality": (
                intent.integrated_quality_report.sha256
                if intent.integrated_quality_report
                else None
            ),
            "package": (
                intent.package_manifest.sha256 if intent.package_manifest else None
            ),
            "roundtrip": (
                intent.roundtrip_validation.sha256
                if intent.roundtrip_validation
                else None
            ),
            "review": (
                intent.review_bundle_manifest.sha256
                if intent.review_bundle_manifest
                else None
            ),
            "destination_handoff": (
                intent.destination_handoff_envelope.sha256
                if intent.destination_handoff_envelope
                else None
            ),
        }
    )
    if (
        intent.input_sha256 != intent.state_before.sha256
        or intent.source_fingerprint != expected_intent_source
    ):
        raise ValueError("terminal intent digest is stale or self-inconsistent")
    return _terminal_contract(
        root,
        session_root,
        state,
        status=intent.status,
        reason=intent.reason,
        quality=intent.integrated_quality_report,
        package=intent.package_manifest,
        roundtrip=intent.roundtrip_validation,
        review_bundle=intent.review_bundle_manifest,
        destination_handoff=intent.destination_handoff_envelope,
    )


def _terminal_without_bundle(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    budget: AutonomyBudget,
    previous_receipt: AutonomyArtifact | None,
    *,
    status: str,
    reason: str,
    consume_terminal_action: bool = True,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Terminate without production, optionally exempting hard-cap terminal publication."""

    usage = (
        _consume_action(budget, state.budget_usage)
        if consume_terminal_action
        else state.budget_usage
    )
    _write_terminal_intent(
        root,
        session_root,
        state,
        status=status,
        reason=reason,
    )
    after, receipt = _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="terminalize",
        budget_usage=usage,
        update={
            "status": status,
            "phase": "terminal",
            "next_action": "none",
            "terminal_reason": reason,
        },
        outcome="terminal",
    )
    _terminal_contract(root, session_root, after, status=status, reason=reason)
    return after, receipt


def _terminal_budget_exhausted(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    previous_receipt: AutonomyArtifact | None,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Publish a fail-closed terminal without attempting one action beyond the hard cap."""

    _write_terminal_intent(
        root,
        session_root,
        state,
        status="blocked",
        reason="global_budget_exhausted",
    )
    after, receipt = _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="terminalize",
        budget_usage=state.budget_usage,
        update={
            "status": "blocked",
            "phase": "terminal",
            "next_action": "none",
            "terminal_reason": "global_budget_exhausted",
        },
        outcome="terminal",
    )
    _terminal_contract(
        root,
        session_root,
        after,
        status="blocked",
        reason="global_budget_exhausted",
    )
    return after, receipt


def _terminal_review(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    budget: AutonomyBudget,
    previous_receipt: AutonomyArtifact | None,
    report: IntegratedQualityReport,
    *,
    reason: str,
    consume_terminal_action: bool = True,
    quality_artifact_override: AutonomyArtifact | None = None,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Create a review bundle from canonical QA or exact best-candidate evidence."""

    from .reporting import build_review_bundle, validate_review_bundle

    _verify_integrated_quality_inputs(root, state, report)

    if state.best_known_candidate is None:
        raise RuntimeError("review bundle requires a best-known evaluated candidate")
    evaluation = CandidateEvaluation.model_validate_json(
        _verify_artifact(root, state.best_known_candidate).read_text(encoding="utf-8")
    )
    manifest = StructuralCandidateManifest.model_validate_json(
        _verify_artifact(root, evaluation.candidate_manifest).read_text(encoding="utf-8")
    )
    candidate_quality_path = _verify_artifact(root, manifest.integrated_quality_report)
    quality_path = (
        _verify_artifact(root, quality_artifact_override)
        if quality_artifact_override is not None
        else _verify_artifact(root, state.last_quality_report)
        if state.last_quality_report is not None
        else candidate_quality_path
    )
    candidate_evidence_mode = quality_path.resolve() == candidate_quality_path.resolve()
    bundle_id = f"{state.session_id[:96]}-review"
    published_manifest_path = (
        root
        / "exports"
        / "review_bundles"
        / bundle_id
        / "review_bundle_manifest.json"
    )
    if published_manifest_path.is_file():
        published_manifest, _published_receipt = validate_review_bundle(root, bundle_id)
        quality_artifact = artifact_for(root, quality_path)
        if (
            published_manifest.integrated_quality_report.sha256
            != quality_artifact.sha256
            or published_manifest.termination_reason != reason
            or published_manifest.session_id != state.session_id
        ):
            raise ValueError("existing review bundle differs from terminal recovery inputs")
        manifest_artifact = artifact_for(root, published_manifest_path)
        usage = (
            _consume_action(budget, state.budget_usage)
            if consume_terminal_action
            else state.budget_usage
        )
        _write_terminal_intent(
            root,
            session_root,
            state,
            status="review_required",
            reason=reason,
            quality=quality_artifact,
            review_bundle=manifest_artifact,
        )
        after, receipt = _transition(
            root,
            session_root,
            state,
            previous_receipt,
            action="build_review_bundle",
            budget_usage=usage,
            update={
                "status": "completed",
                "phase": "terminal",
                "next_action": "none",
                "terminal_reason": reason,
            },
            outcome="terminal",
        )
        _terminal_contract(
            root,
            session_root,
            after,
            status="review_required",
            reason=reason,
            quality=quality_artifact,
            review_bundle=manifest_artifact,
        )
        return after, receipt
    input_root = session_root / "review_inputs" / bundle_id
    if input_root.exists():
        interrupted_root = session_root / "interrupted_staging" / "review_inputs"
        interrupted_root.mkdir(parents=True, exist_ok=True)
        interrupted = interrupted_root / f"{bundle_id}-{uuid4().hex[:8]}"
        os.replace(input_root, interrupted)
    input_root.mkdir(parents=True, exist_ok=False)
    preview_glb = input_root / "preview.glb"
    if candidate_evidence_mode:
        if not manifest.low_resolution_renders:
            raise FileNotFoundError("candidate review evidence has no exact render")
        beauty_path = _verify_artifact(root, manifest.low_resolution_renders[0])
        best_blend = _verify_artifact(root, manifest.blend)
    else:
        _workflow_path, workflow = _workflow_plan(root, state.workflow_id)
        render_manifest_path = _workflow_output_path(
            root,
            workflow,
            "qa.run.render_pass_manifest",
        )
        beauty_path = _workflow_output_path(root, workflow, "qa.run.pass.beauty")
        if (
            render_manifest_path is None
            or not render_manifest_path.is_file()
            or beauty_path is None
            or not beauty_path.is_file()
        ):
            raise FileNotFoundError("review delivery requires exact current QA render evidence")
        render_manifest = RenderPassManifest.model_validate_json(
            render_manifest_path.read_text(encoding="utf-8")
        )
        current_build = collect_build_provenance(root, state.job_id)
        if (
            render_manifest.scene_spec_sha256
            != sha256_file(root / "analysis" / "scene_spec.json")
            or render_manifest.build_fingerprint != current_build["fingerprint"]
        ):
            raise ValueError("review delivery QA is stale against the current canonical build")
        best_blend = root / "blender" / "scene.blend"
        if not best_blend.is_file():
            raise FileNotFoundError("current authoring Blender file is missing")
    run_blender(
        "export_scene.py",
        ["--format", "glb", "--output", str(preview_glb)],
        blend_file=best_blend,
    )
    unresolved_path = input_root / "unresolved_findings.json"
    write_json_atomic(
        unresolved_path,
        {
            "schema_version": "0.1.0",
            "quality_outcome": report.outcome,
            "blocking_reasons": report.blocking_reasons,
            "reentry": [item.model_dump(mode="json") for item in report.reentry],
            "axes": [item.model_dump(mode="json") for item in report.axes],
        },
    )
    history_path = input_root / "iteration_history.json"
    transition_rows = []
    for transition in sorted((session_root / "transitions").glob("[0-9][0-9][0-9][0-9]")):
        receipt_path = transition / "receipt.json"
        if receipt_path.is_file():
            receipt_payload = load_json(root, receipt_path)
            transition_rows.append(
                {
                    "sequence": receipt_payload["sequence"],
                    "action": receipt_payload["action"],
                    "outcome": receipt_payload["outcome"],
                    "receipt_sha256": sha256_file(receipt_path),
                }
            )
    write_json_atomic(
        history_path,
        {"schema_version": "0.1.0", "transitions": transition_rows},
    )
    comparison_path = input_root / "candidate_comparison.json"
    comparisons = []
    for candidate_path in sorted(
        (session_root / "candidates").glob("*/candidate_evaluation.json")
    ):
        candidate = CandidateEvaluation.model_validate_json(
            candidate_path.read_text(encoding="utf-8")
        )
        comparisons.append(
            {
                "candidate_id": candidate.candidate_id,
                "evaluation_sha256": sha256_file(candidate_path),
                "metrics": candidate.metrics.model_dump(mode="json"),
                "selected": candidate.candidate_id == evaluation.candidate_id,
            }
        )
    write_json_atomic(
        comparison_path,
        {
            "schema_version": "0.1.0",
            "best_candidate_id": evaluation.candidate_id,
            "candidates": comparisons,
        },
    )
    representative = [beauty_path]
    _manifest, _bundle_receipt = build_review_bundle(
        root,
        bundle_id=bundle_id,
        session_id=state.session_id,
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        termination_reason=reason,  # type: ignore[arg-type]
        best_candidate_blend=best_blend,
        preview_glb=preview_glb,
        representative_renders=representative,
        integrated_quality_report=quality_path,
        unresolved_findings=unresolved_path,
        iteration_history=history_path,
        candidate_comparison=comparison_path,
        next_manual_actions=[
            "Review the exact integrated-quality findings and candidate comparison.",
            "Return to the recommended V0.4/V0.5/V0.7 phase with a new reviewed plan.",
            "Do not use this review-only bundle as a production package or handoff source.",
        ],
    )
    manifest_artifact = artifact_for(
        root,
        root / "exports" / "review_bundles" / bundle_id / "review_bundle_manifest.json",
    )
    usage = (
        _consume_action(budget, state.budget_usage)
        if consume_terminal_action
        else state.budget_usage
    )
    quality_artifact = artifact_for(root, quality_path)
    _write_terminal_intent(
        root,
        session_root,
        state,
        status="review_required",
        reason=reason,
        quality=quality_artifact,
        review_bundle=manifest_artifact,
    )
    after, receipt = _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="build_review_bundle",
        budget_usage=usage,
        update={
            "status": "completed",
            "phase": "terminal",
            "next_action": "none",
            "terminal_reason": reason,
        },
        outcome="terminal",
    )
    _terminal_contract(
        root,
        session_root,
        after,
        status="review_required",
        reason=reason,
        quality=quality_artifact,
        review_bundle=manifest_artifact,
    )
    return after, receipt


def _route_budget_exhaustion(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    budget: AutonomyBudget,
    previous_receipt: AutonomyArtifact | None,
    *,
    exhausted_dimension: str | None,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Publish the best exact review evidence instead of dropping it at a budget cap."""

    reason = _budget_terminal_reason(exhausted_dimension)
    report: IntegratedQualityReport | None = None
    quality_artifact: AutonomyArtifact | None = None
    if state.best_known_candidate is not None and state.last_quality_report is not None:
        candidate = IntegratedQualityReport.model_validate_json(
            _verify_artifact(root, state.last_quality_report).read_text(encoding="utf-8")
        )
        _verify_integrated_quality_inputs(root, state, candidate)
        if not candidate.quality_accepted:
            report = candidate
            quality_artifact = state.last_quality_report
    if report is None:
        best_known = _best_known_review_evidence(root, state)
        if best_known is not None:
            _evaluation, _manifest, candidate_report, candidate_artifact = best_known
            if not candidate_report.quality_accepted:
                report = candidate_report
                quality_artifact = candidate_artifact
    consume_terminal_action = (
        state.budget_usage.total_actions < budget.global_action_limit
    )
    if report is not None and quality_artifact is not None:
        return _terminal_review(
            root,
            session_root,
            state,
            budget,
            previous_receipt,
            report,
            reason=reason,
            consume_terminal_action=consume_terminal_action,
            quality_artifact_override=quality_artifact,
        )
    if exhausted_dimension == "total_actions":
        return _terminal_budget_exhausted(
            root,
            session_root,
            state,
            previous_receipt,
        )
    return _terminal_without_bundle(
        root,
        session_root,
        state,
        budget,
        previous_receipt,
        status="blocked",
        reason=reason,
        consume_terminal_action=consume_terminal_action,
    )


def _final_quality_action(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    budget: AutonomyBudget,
    previous_receipt: AutonomyArtifact | None,
) -> tuple[AutonomyState, AutonomyIterationReceipt]:
    """Evaluate final package evidence and select package acceptance or review-only delivery."""

    usage = _consume_action(
        budget,
        state.budget_usage,
        total_quality_evaluations=1,
    )
    quality_path = (
        session_root / "integrated_quality" / "final" / "integrated_quality_report.json"
    )
    if quality_path.is_file():
        report = IntegratedQualityReport.model_validate_json(
            quality_path.read_text(encoding="utf-8")
        )
        quality_artifact = artifact_for(root, quality_path)
    else:
        report, quality_artifact = _run_integrated_quality(
            root,
            session_root,
            state,
            stage="final",
        )
    _verify_integrated_quality_inputs(root, state, report)
    if not report.quality_accepted:
        reason = _review_termination_reason(state, report)
        return _transition(
            root,
            session_root,
            state,
            previous_receipt,
            action="run_integrated_quality",
            budget_usage=usage,
            update={
                "status": "running",
                "phase": "review_bundle",
                "next_action": "build_review_bundle",
                "last_quality_report": quality_artifact,
                "pending_terminal_reason": reason,
                "warnings": [
                    *state.warnings,
                    f"Final integrated quality requires review: {reason}.",
                ],
            },
        )
    _workflow_path, workflow = _workflow_plan(root, state.workflow_id)
    package_path = _workflow_output_path(root, workflow, "portable.package_manifest")
    roundtrip_path = _workflow_output_path(root, workflow, "portable.roundtrip_report")
    accepted_repair = latest_accepted_package_repair(
        root, session_root, state, workflow
    )
    if accepted_repair is not None:
        if (
            accepted_repair.package_artifact is None
            or accepted_repair.roundtrip_artifact is None
        ):
            raise ValueError("accepted package repair has incomplete output evidence")
        package_path = root / accepted_repair.package_artifact.path
        roundtrip_path = root / accepted_repair.roundtrip_artifact.path
    if package_path is None or roundtrip_path is None:
        raise FileNotFoundError("quality-passed production has no package or roundtrip artifact")
    package_artifact = artifact_for(root, package_path)
    roundtrip_artifact = artifact_for(root, roundtrip_path)
    handoff_path = _workflow_output_path(root, workflow, "destination.handoff.manifest")
    handoff_artifact = (
        artifact_for(root, handoff_path)
        if handoff_path is not None and handoff_path.is_file()
        else None
    )
    _write_terminal_intent(
        root,
        session_root,
        state,
        status="quality_passed",
        reason="quality_target_reached",
        quality=quality_artifact,
        package=package_artifact,
        roundtrip=roundtrip_artifact,
        destination_handoff=handoff_artifact,
    )
    after, receipt = _transition(
        root,
        session_root,
        state,
        previous_receipt,
        action="run_integrated_quality",
        budget_usage=usage,
        update={
            "status": "completed",
            "phase": "terminal",
            "next_action": "none",
            "terminal_reason": "quality_target_reached",
            "last_quality_report": quality_artifact,
        },
        outcome="terminal",
    )
    _terminal_contract(
        root,
        session_root,
        after,
        status="quality_passed",
        reason="quality_target_reached",
        quality=quality_artifact,
        package=package_artifact,
        roundtrip=roundtrip_artifact,
        destination_handoff=handoff_artifact,
    )
    return after, receipt


def bind_autonomy_controller(
    job_id: str,
    session_id: str,
    *,
    external_task_id: str,
    external_host_id: str | None = None,
    enforced_controller_tool_profile_sha256: str | None = None,
) -> dict[str, Any]:
    """Bind a client-mediated controller and publish the exact AQ companion binding."""

    root = job_dir(validate_job_id(job_id))
    session_root = _session_root(root, session_id)
    plan, _profile, _budget, _authorization = _load_contracts(root, session_root)
    if (session_root / "controller_binding.json").is_file():
        raise FileExistsError("autonomy controller is already bound")
    status = get_asset_production_dispatch_status(job_id, plan.dispatch_id)
    if status["controller_execution_mode"] != "client_mediated":
        raise ValueError("desktop_in_session autonomy does not accept a client binding")
    if not enforced_controller_tool_profile_sha256:
        raise PermissionError("exact enforced controller tool-profile SHA-256 is required")
    production_state = status["state"]
    binding = bind_asset_production_task(
        job_id,
        plan.dispatch_id,
        production_state["controller_id"],
        external_task_id=external_task_id,
        external_host_id=external_host_id,
        client_tool_policy_enforced=True,
        enforced_controller_tool_profile_sha256=enforced_controller_tool_profile_sha256,
    )
    production_binding = artifact_for(
        root,
        root
        / "production"
        / "dispatches"
        / plan.dispatch_id
        / "task_binding_receipt.json",
    )
    controller_plan = plan.production_controller_plan
    now = _utc_now()
    aq_binding = AutonomyControllerBinding(
        contract_id=f"binding-{session_id}",
        binding_id=f"binding-{session_id}",
        job_id=job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        input_sha256=production_binding.sha256,
        source_fingerprint=canonical_digest(
            {
                "production_binding": production_binding.sha256,
                "controller_plan": controller_plan.sha256,
            }
        ),
        producer="codex_blender_modeler.autonomy.service",
        producer_version="0.1.0",
        provenance=[production_binding, controller_plan],
        created_at=now,
        session_id=session_id,
        controller_id=production_state["controller_id"],
        production_launch=production_binding,
        production_controller_plan=controller_plan,
        execution_mode="client_mediated",
        bound_at=now,
    )
    write_immutable_json(
        root,
        session_root / "controller_binding.json",
        aq_binding.model_dump(mode="json"),
    )
    return {
        "binding": aq_binding.model_dump(mode="json"),
        "production_binding": binding.model_dump(mode="json"),
    }


def get_autonomy_status(job_id: str, session_id: str) -> dict[str, Any]:
    """Reconstruct one AQ session without mutating workflow or derived evidence."""

    root = job_dir(validate_job_id(job_id))
    session_root = _session_root(root, session_id)
    plan, profile, budget, authorization = _load_contracts(root, session_root)
    state, receipt, recovery_warnings = _load_state_chain(root, session_root)
    if state.job_id != job_id or state.session_id != session_id:
        raise ValueError("autonomy state belongs to another session")
    terminal = None
    terminal_path = session_root / "terminal.json"
    if _native_is_file(terminal_path):
        terminal = AutonomyTerminal.model_validate_json(
            _native_read_text(terminal_path)
        )
        _verify_terminal_evidence(root, session_root, state, terminal)
    elif state.status in {"completed", "blocked", "cancelled", "failed"}:
        raise ValueError("terminal autonomy state is missing terminal.json evidence")
    candidate_assignment = None
    if state.phase in {
        "initial_candidates",
        "structural_authoring",
        "parametric_convergence",
    } and state.current_candidate_id:
        assignment_path = (
            candidate_directory(session_root, state.current_candidate_id) / "assignment.json"
        )
        if _native_is_file(assignment_path):
            candidate_assignment = {
                "artifact": artifact_for(root, assignment_path).model_dump(mode="json"),
                "assignment": load_json(root, assignment_path),
            }
    production = get_asset_production_dispatch_status(job_id, plan.dispatch_id)
    return {
        "session_id": session_id,
        "profile_id": profile.profile_id,
        "root_authorization_status": authorization.status,
        "state": state.model_dump(mode="json"),
        "receipt_chain_head_sha256": receipt.sha256 if receipt else None,
        "remaining_budget": remaining_budget(budget, state.budget_usage),
        "candidate_assignment": candidate_assignment,
        "production": production,
        "terminal": terminal.model_dump(mode="json") if terminal else None,
        "recovery_warnings": recovery_warnings,
    }


def advance_autonomy(job_id: str, session_id: str) -> dict[str, Any]:
    """Execute at most one exact AQ state-machine action under a non-stealable lock."""

    root = job_dir(validate_job_id(job_id))
    session_root = _session_root(root, session_id)
    owner_id = f"aq-advance-{uuid4().hex}"
    with autonomy_session_lock(root, session_root, owner_id=owner_id):
        plan, profile, budget, authorization = _load_contracts(root, session_root)
        state, previous_receipt, _warnings = _load_state_chain(root, session_root)
        if state.status in {"completed", "blocked", "cancelled", "failed"}:
            if not _native_is_file(session_root / "terminal.json"):
                _recover_terminal_contract(root, session_root, state)
            return get_autonomy_status(job_id, session_id)
        exhausted_dimension = _next_action_exhausted_dimension(
            root,
            session_root,
            state,
            budget,
        )
        if exhausted_dimension is not None:
            _route_budget_exhaustion(
                root,
                session_root,
                state,
                budget,
                previous_receipt,
                exhausted_dimension=exhausted_dimension,
            )
            return get_autonomy_status(job_id, session_id)
        if state.next_action == "collect_reference_evidence":
            _collect_reference_action(
                root, session_root, state, plan, budget, previous_receipt
            )
        elif state.next_action == "author_initial_candidate":
            _author_candidate_assignment(
                root, session_root, state, plan, budget, previous_receipt
            )
        elif state.next_action == "run_structural_round":
            _author_refinement_assignment(
                root,
                session_root,
                state,
                plan,
                profile,
                budget,
                authorization,
                previous_receipt,
                candidate_phase="structural",
            )
        elif state.next_action == "run_parametric_iteration":
            _author_refinement_assignment(
                root,
                session_root,
                state,
                plan,
                profile,
                budget,
                authorization,
                previous_receipt,
                candidate_phase="parametric",
            )
        elif state.next_action == "await_controller_output":
            if state.phase in {
                "initial_candidates",
                "structural_authoring",
                "parametric_convergence",
            } and state.current_candidate_id is not None:
                evaluated = _evaluate_candidate_action(
                    root, session_root, state, plan, budget, previous_receipt
                )
                if evaluated is None:
                    return get_autonomy_status(job_id, session_id)
            else:
                advanced = _advance_production_action(
                    root,
                    session_root,
                    state,
                    profile,
                    budget,
                    authorization,
                    previous_receipt,
                )
                if advanced is None:
                    return get_autonomy_status(job_id, session_id)
        elif state.next_action == "promote_best_candidate":
            _promote_best_action(
                root,
                session_root,
                state,
                profile,
                budget,
                authorization,
                previous_receipt,
            )
        elif state.next_action == "advance_production":
            _advance_production_action(
                root,
                session_root,
                state,
                profile,
                budget,
                authorization,
                previous_receipt,
            )
        elif state.next_action == "run_material_round":
            _advance_production_action(
                root,
                session_root,
                state,
                profile,
                budget,
                authorization,
                previous_receipt,
            )
        elif state.next_action == "run_integrated_quality":
            _final_quality_action(root, session_root, state, budget, previous_receipt)
        elif state.next_action == "build_review_bundle":
            if state.last_quality_report is None:
                raise FileNotFoundError("review-bundle quality evidence is missing")
            quality_path = _verify_artifact(root, state.last_quality_report)
            report = IntegratedQualityReport.model_validate_json(
                quality_path.read_text(encoding="utf-8")
            )
            _terminal_review(
                root,
                session_root,
                state,
                budget,
                previous_receipt,
                report,
                reason=_review_termination_reason(state, report),
            )
        elif state.next_action == "terminalize":
            if state.pending_terminal_reason is None:
                raise RuntimeError("terminalize action has no exact termination reason")
            _terminal_without_bundle(
                root,
                session_root,
                state,
                budget,
                previous_receipt,
                status="blocked",
                reason=state.pending_terminal_reason,
            )
        else:
            raise RuntimeError(f"unsupported autonomy action: {state.next_action}")
    return get_autonomy_status(job_id, session_id)


def run_autonomy(
    job_id: str,
    session_id: str,
    *,
    max_actions: int = 8,
) -> dict[str, Any]:
    """Repeat bounded single-action advances and stop at controller or terminal boundaries."""

    root = job_dir(validate_job_id(job_id))
    session_root = _session_root(root, session_id)
    status = (
        advance_autonomy(job_id, session_id)
        if _native_is_file(session_root / "terminal_intent.json")
        and not _native_is_file(session_root / "terminal.json")
        else get_autonomy_status(job_id, session_id)
    )
    authorized = int(status["remaining_budget"]["total_actions"])
    limit = bounded_action_limit(max_actions, max(1, authorized))
    executed = 0
    for _ in range(limit):
        before = status["state"]
        if before["status"] in {"completed", "blocked", "cancelled", "failed"}:
            break
        status = advance_autonomy(job_id, session_id)
        executed += 1
        after = status["state"]
        if after["action_sequence"] == before["action_sequence"]:
            break
        if after["status"] == "waiting_for_controller":
            break
    return {**status, "actions_executed": executed, "action_limit": limit}


def resume_autonomy(
    job_id: str,
    session_id: str,
    *,
    max_actions: int = 8,
) -> dict[str, Any]:
    """Recover safe transition staging and continue without replaying completed receipts."""

    root = job_dir(validate_job_id(job_id))
    session_root = _session_root(root, session_id)
    if _native_is_file(session_root / "terminal_intent.json") and not _native_is_file(
        session_root / "terminal.json"
    ):
        return advance_autonomy(job_id, session_id)
    status = get_autonomy_status(job_id, session_id)
    if status["state"]["status"] in {"completed", "blocked", "cancelled", "failed"}:
        raise RuntimeError("terminal autonomy sessions cannot be resumed")
    return run_autonomy(job_id, session_id, max_actions=max_actions)


def cancel_autonomy(job_id: str, session_id: str, *, reason: str) -> dict[str, Any]:
    """Cancel future AQ actions without deleting canonical or immutable session evidence."""

    normalized = reason.strip()
    if not normalized:
        raise ValueError("autonomy cancellation reason is required")
    root = job_dir(validate_job_id(job_id))
    session_root = _session_root(root, session_id)
    with autonomy_session_lock(
        root,
        session_root,
        owner_id=f"aq-cancel-{uuid4().hex}",
    ):
        _plan, _profile, budget, _authorization = _load_contracts(root, session_root)
        state, previous_receipt, _warnings = _load_state_chain(root, session_root)
        if state.status in {"completed", "blocked", "cancelled", "failed"}:
            raise RuntimeError("terminal autonomy session cannot be cancelled again")
        cancellation = {
            "schema_version": "0.1.0",
            "session_id": session_id,
            "job_id": job_id,
            "reason": normalized,
            "previous_state_sha256": artifact_for(
                root,
                session_root
                / "transitions"
                / f"{state.action_sequence:04d}"
                / "state.json",
            ).sha256,
            "cancelled_at": _utc_now().isoformat(),
        }
        write_immutable_json(root, session_root / "cancellation.json", cancellation)
        _terminal_without_bundle(
            root,
            session_root,
            state,
            budget,
            previous_receipt,
            status="cancelled",
            reason="cancelled",
        )
    return get_autonomy_status(job_id, session_id)


__all__ = [
    "advance_autonomy",
    "bind_autonomy_controller",
    "cancel_autonomy",
    "get_autonomy_status",
    "resume_autonomy",
    "run_autonomy",
]
