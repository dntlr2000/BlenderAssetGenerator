"""Exact optional fidelity review terminals, separate from IQ and human acceptance."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..autonomy.worker import autonomy_session_lock
from ..reference_fidelity.models import FidelityArtifact, FidelityEvaluationV01
from ..reference_fidelity.service import publish, read_artifact
from .models import AQV2Artifact, AutonomyPlanV2, AutonomyStateV2
from .quality_revision_models import FidelityReviewBundleV01, FidelityReviewTerminalV01
from .quality_revision_service import (
    _attempts,
    _fidelity_root,
    load_optional_loop,
    quality_revision_boundary,
)

BUNDLE_KIND = "reference_fidelity_review_bundle_v01"
TERMINAL_KIND = "reference_fidelity_review_terminal_v01"


def _best_attempt(root: Path, attempts: list) -> FidelityArtifact:
    """Choose preserved evidence by fewer major defects then more satisfied observations."""

    ranked = []
    for attempt, artifact in attempts:
        evaluation = FidelityEvaluationV01.model_validate_json(
            read_artifact(root, attempt.fidelity_evaluation)
        )
        rank = (
            sum(item.severity != "minor" for item in evaluation.findings),
            -evaluation.satisfied_features,
            len(evaluation.findings),
            -attempt.round_index,
        )
        ranked.append((rank, artifact))
    return min(ranked, key=lambda item: item[0])[1]


def validate_fidelity_review_bundle(
    root: Path, artifact: FidelityArtifact
) -> FidelityReviewBundleV01:
    """Recompute a non-production stop from the exact original live state and attempt ledger."""

    bundle = FidelityReviewBundleV01.model_validate_json(read_artifact(root, artifact))
    binding = load_optional_loop(root, bundle.session_id)
    if binding is None or binding[1] != bundle.loop or binding[0].job_id != bundle.job_id:
        raise ValueError("fidelity review has no exact session companion")
    state = AutonomyStateV2.model_validate_json(read_artifact(root, bundle.source_state))
    if state.next_action != "run_integrated_quality" or state.quality_terminal is not None:
        raise ValueError("fidelity review cannot reopen an old terminal")
    plan = AutonomyPlanV2.model_validate_json(
        read_artifact(root, FidelityArtifact(path=state.plan.path, sha256=state.plan.sha256))
    )
    if (state.job_id, state.session_id, plan.job_id, plan.session_id) != (
        bundle.job_id,
        bundle.session_id,
        bundle.job_id,
        bundle.session_id,
    ):
        raise ValueError("fidelity review identities differ")
    boundary = quality_revision_boundary(root, plan, state)
    if boundary is None or boundary["next_action"] != "review_required":
        raise ValueError("fidelity review does not have a diagnosed bounded stop")
    attempts = _attempts(root, bundle.session_id, bundle.loop)
    if bundle.attempts != [item[1] for item in attempts]:
        raise ValueError("fidelity review omits or substitutes a quality round")
    if bundle.best_known_attempt != _best_attempt(root, attempts):
        raise ValueError("fidelity review changed the best-known evidence selection")
    if bundle.reason != boundary["reason"]:
        raise ValueError("fidelity review changed the host stop reason")
    return bundle


def validate_fidelity_terminal(root: Path, artifact: AQV2Artifact) -> FidelityReviewTerminalV01:
    """Validate the typed terminal without treating it as a legacy IQ non-pass or approval."""

    if artifact.kind != TERMINAL_KIND:
        raise ValueError("fidelity terminal requires its exact companion artifact kind")
    terminal = FidelityReviewTerminalV01.model_validate_json(
        read_artifact(root, FidelityArtifact(path=artifact.path, sha256=artifact.sha256))
    )
    bundle = validate_fidelity_review_bundle(root, terminal.review_bundle)
    for key in ("job_id", "session_id", "loop", "source_state", "reason"):
        if getattr(terminal, key) != getattr(bundle, key):
            raise ValueError("fidelity terminal differs from its exact review bundle")
    return terminal


def publish_fidelity_review_terminal(job_id: str, session_id: str) -> dict[str, object]:
    """Publish one policy-backed bounded review stop; never synthesize human disposition."""

    from .approval_models import ApprovalArtifact
    from .approval_supervisor_service import _ensure_review_terminal_policy_decision
    from .controller_bridge import _session_bundle
    from .delivery_service import artifact_for_v2
    from .supervisor_service import _write_next_state
    from .transitions import transition_state

    root, session, plan, budget, state, state_artifact = _session_bundle(job_id, session_id)
    if state.quality_terminal is not None and state.quality_terminal.kind == TERMINAL_KIND:
        validate_fidelity_terminal(root, state.quality_terminal)
        return {"status": "existing", "state": state.model_dump(mode="json")}
    with autonomy_session_lock(root, session, owner_id="fidelity-review-terminal"):
        if _session_bundle(job_id, session_id)[4] != state:
            raise ValueError("AQ state changed before review publication")
        boundary = quality_revision_boundary(root, plan, state)
        if boundary is None or boundary["next_action"] != "review_required":
            raise PermissionError("current fidelity evidence does not require bounded termination")
        binding = load_optional_loop(root, session_id)
        if binding is None:
            raise PermissionError("fidelity terminal needs an explicitly bound loop")
        attempts = _attempts(root, session_id, binding[1])
        if (
            state.budget_usage.total_quality_evaluations + 1 > budget.total_quality_evaluations
            or state.budget_usage.total_actions + 1
            > min(budget.global_action_limit, plan.action_limit)
        ):
            raise PermissionError("remaining AQ budget cannot publish the final assessment")
        base = _fidelity_root(root, session_id)
        source = FidelityArtifact(path=state_artifact.path, sha256=state_artifact.sha256)
        bundle = FidelityReviewBundleV01(
            job_id=job_id,
            session_id=session_id,
            loop=binding[1],
            source_state=source,
            attempts=[item[1] for item in attempts],
            best_known_attempt=_best_attempt(root, attempts),
            reason=str(boundary["reason"]),
        )
        bundle_ref = publish(root, base / "review_bundle.json", bundle)
        validate_fidelity_review_bundle(root, bundle_ref)
        terminal = FidelityReviewTerminalV01(
            job_id=job_id,
            session_id=session_id,
            loop=binding[1],
            source_state=source,
            review_bundle=bundle_ref,
            reason=bundle.reason,
        )
        terminal_ref = publish(root, base / "terminal.json", terminal)
        terminal_artifact = artifact_for_v2(
            root,
            root / terminal_ref.path,
            artifact_id="fidelity-review-terminal",
            kind=TERMINAL_KIND,
        )
        review_artifact = artifact_for_v2(
            root, root / bundle_ref.path, artifact_id="fidelity-review-bundle", kind=BUNDLE_KIND
        )
        # Record the single-use routine review policy while the base state is still live.
        _ensure_review_terminal_policy_decision(
            job_id,
            session_id,
            review_bundle=ApprovalArtifact.model_validate(review_artifact.model_dump()),
            quality_terminal=ApprovalArtifact.model_validate(terminal_artifact.model_dump()),
        )
        usage = state.budget_usage.model_copy(
            update={
                "total_quality_evaluations": state.budget_usage.total_quality_evaluations + 1,
                "total_actions": state.budget_usage.total_actions + 1,
            }
        )
        next_state = transition_state(
            state,
            event="fidelity_review_required",
            evidence=terminal_artifact,
            quality_terminal=terminal_artifact,
            reason=bundle.reason,
            created_at=datetime.now(UTC),
            budget_usage=usage,
        )
        artifact = _write_next_state(root, session, next_state)
        return {
            "status": "review_required",
            "state": next_state.model_dump(mode="json"),
            "state_artifact": artifact.model_dump(mode="json"),
            "human_quality_disposition": "not_recorded",
        }
