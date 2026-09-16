"""Host-owned nonterminal quality attempts and exact bounded V0.4 reentry boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..autonomy.worker import autonomy_session_lock
from ..blender_artifacts import publish_bytes_create_once, sha256_file
from ..integrated_quality.v02_models import IntegratedQualityReportV02, ReentryDecisionV02
from ..reference_fidelity.models import (
    FidelityArtifact,
    FidelityEvaluationV01,
    ModelingHypothesisV01,
    VisualFindingSetV01,
)
from ..reference_fidelity.service import (
    artifact_at,
    compare_evaluation_files,
    evaluate_review,
    publish,
    read_artifact,
    validate_review_evidence,
)
from .models import (
    AQV2Artifact,
    AutonomyBudgetV03,
    AutonomyPlanV2,
    AutonomyStateV2,
    parse_autonomy_budget,
)
from .quality_revision_budget import (
    funded_route_usage,
    require_strategy_change,
    reserve_revision,
    select_revision_route,
)
from .quality_revision_models import (
    AQQualityRevisionLoop,
    AQQualityRevisionLoopV02,
    AQQualityRevisionLoopV03,
    QualityAttemptV01,
    QualityRenderReservationV01,
    RevisionCostV01,
    RevisionLedgerEntryV01,
    StructuralReentryPlanV01,
    parse_quality_revision_loop,
)

REENTRY_KIND = "reference_fidelity_reentry_v01"

_ROUTE_PRIORITY = (
    "review_required",
    "technical_recovery",
    "calibration",
    "evidence_required",
    "structural_reentry",
    "parametric_revision",
    "material_revision",
)


def _quality_submission_report(
    root: Path, submission_artifact: FidelityArtifact
) -> IntegratedQualityReportV02:
    """Load the exact IQ report named by one immutable quality submission."""

    from .supervisor_service import QualitySubmissionV2

    submission = QualitySubmissionV2.model_validate_json(
        read_artifact(root, submission_artifact)
    )
    report_artifact = FidelityArtifact(
        path=submission.integrated_quality_report.path,
        sha256=submission.integrated_quality_report.sha256,
    )
    return IntegratedQualityReportV02.model_validate_json(
        read_artifact(root, report_artifact)
    )


def _iq_reentry_route(decision: ReentryDecisionV02) -> str:
    """Preserve the exact V0.1 IQ-to-loop route mapping for historical companions."""

    if decision.destination == "v0.4_structural_authoring":
        return "calibration" if decision.category == "camera" else "structural_reentry"
    return {
        "v0.6_parametric_convergence": "parametric_revision",
        "v0.7_production_repair": "technical_recovery",
        "manual_evidence_review": "evidence_required",
        "restricted_scope_required": "review_required",
    }[decision.destination]


def _contour_is_bounded_parametric(report: IntegratedQualityReportV02) -> bool:
    """Recognize a small boundary-only miss when distance agreement already passes policy."""

    contour = report.contour
    policy = report.policy
    if (
        contour.status != "scored"
        or contour.boundary_f_score is None
        or contour.edge_distance_transform_chamfer_norm is None
    ):
        return False
    deficit = policy.minimum_boundary_f_score - contour.boundary_f_score
    return (
        0.0 < deficit <= policy.meaningful_gain_min + 1.0e-12
        and contour.edge_distance_transform_chamfer_norm
        <= policy.maximum_edge_distance_transform_chamfer_norm
    )


def _iq_reentry_route_for_loop(
    decision: ReentryDecisionV02,
    evaluation: FidelityEvaluationV01,
    report: IntegratedQualityReportV02,
    loop: AQQualityRevisionLoop | None,
) -> str:
    """Use causal V0.2 routing only when the exact bound loop selected that policy."""

    if not isinstance(loop, AQQualityRevisionLoopV02):
        return _iq_reentry_route(decision)
    if decision.destination != "v0.4_structural_authoring":
        return _iq_reentry_route(decision)
    if decision.category == "camera":
        return "calibration"
    if decision.finding_id == "finding.reference.fixed_camera_visibility_v02":
        if evaluation.next_action in {
            "calibration",
            "evidence_required",
            "structural_reentry",
            "parametric_revision",
            "material_revision",
        }:
            return evaluation.next_action
        return "evidence_required"
    if decision.finding_id == "finding.reference.contour_v02":
        if evaluation.next_action == "structural_reentry":
            return "structural_reentry"
        if _contour_is_bounded_parametric(report):
            return "parametric_revision"
    return _iq_reentry_route(decision)


def _combined_attempt_routing(
    evaluation: FidelityEvaluationV01,
    report: IntegratedQualityReportV02,
    *,
    loop: AQQualityRevisionLoop | None = None,
) -> tuple[str, list[str]]:
    """Combine exact visual and IQ routes under the bound versioned routing policy."""

    visual_ids = [item.feature_id for item in evaluation.findings]
    iq_ids = (
        [f"iq:{item.finding_id}" for item in report.findings]
        if not report.quality_accepted
        else []
    )
    routes = [] if evaluation.next_action == "quality_ready" else [evaluation.next_action]
    if not report.quality_accepted:
        routes.extend(
            _iq_reentry_route_for_loop(item, evaluation, report, loop)
            for item in report.reentry
        )
        if not report.findings:
            iq_ids = ["iq:unclassified_nonpass"]
            routes.append("review_required")
    selected = next((route for route in _ROUTE_PRIORITY if route in routes), "quality_ready")
    unresolved = list(dict.fromkeys([*visual_ids, *iq_ids]))
    return selected, unresolved


def _uses_integrated_attempt_routing(attempt: QualityAttemptV01) -> bool:
    """Distinguish new combined attempts while preserving exact historical V0.1 bytes."""

    return any(item.startswith("iq:") for item in attempt.unresolved_features)


def _snapshot_source(root: Path, source: Path, destination: Path) -> FidelityArtifact:
    """Preserve current source bytes before a round; never point history at mutable canonical."""

    artifact = artifact_at(root, source)
    payload = read_artifact(root, artifact)
    from ..production.validation import ensure_contained_production_path

    destination = ensure_contained_production_path(root, destination, must_exist=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    publish_bytes_create_once(destination, payload)
    return artifact_at(root, destination)


def _fidelity_root(root: Path, session_id: str) -> Path:
    """Select the single session-owned companion location, never a new child budget."""

    from ..production.validation import ensure_contained_production_path

    return ensure_contained_production_path(
        root,
        root / "production/autonomy_v2" / session_id / "fidelity",
        must_exist=False,
    )


def load_optional_loop(
    root: Path, session_id: str
) -> tuple[AQQualityRevisionLoop, FidelityArtifact] | None:
    """Load only an explicitly bound exact companion; absence preserves legacy behavior."""

    path = _fidelity_root(root, session_id) / "plan.json"
    if not path.exists():
        return None
    artifact = artifact_at(root, path)
    loop = parse_quality_revision_loop(read_artifact(root, artifact))
    if loop.session_id != session_id:
        raise ValueError("quality revision companion belongs to another session")
    for item in (
        loop.root_authorization,
        loop.approval_envelope,
        loop.hypothesis,
        loop.initial_state,
    ):
        read_artifact(root, item)
    return loop, artifact


def bind_quality_revision_loop(job_id: str, session_id: str, plan_path: Path) -> FidelityArtifact:
    """Bind new-loop authority before the first geometry candidate; never reopen a terminal."""

    from .approval_policy_service import _load_approval_boundary
    from .controller_bridge import _session_bundle

    root, session, plan, budget, state, state_artifact = _session_bundle(job_id, session_id)
    source = artifact_at(root, plan_path if plan_path.is_absolute() else root / plan_path)
    loop = parse_quality_revision_loop(read_artifact(root, source))
    with autonomy_session_lock(root, session, owner_id="reference-fidelity-bind"):
        _root, _session, current_plan, _budget, current, current_artifact = _session_bundle(
            job_id,
            session_id,
        )
        if current != state or current_plan != plan:
            raise ValueError("AQ state changed before companion binding")
        if state.next_action == "none" or state.budget_usage.initial_candidates != 0:
            raise PermissionError("quality revision loop must bind before initial geometry")
        if (loop.job_id, loop.session_id) != (job_id, session_id):
            raise ValueError("loop identity differs from AQ root")
        if isinstance(loop, AQQualityRevisionLoopV03) != isinstance(budget, AutonomyBudgetV03):
            raise ValueError("funded root and loop versions must be selected together")
        if isinstance(loop, AQQualityRevisionLoopV03) and loop.funding != budget.funding:
            raise ValueError("loop funding differs from the exact root budget epoch")
        if loop.initial_state != FidelityArtifact(
            path=current_artifact.path, sha256=current_artifact.sha256
        ):
            raise ValueError("loop does not bind the exact initial AQ state")
        if loop.root_authorization != FidelityArtifact(
            path=plan.root_authorization.path, sha256=plan.root_authorization.sha256
        ):
            raise PermissionError("loop names another root authorization")
        boundary = _load_approval_boundary(job_id, session_id)
        envelope, envelope_artifact = boundary[8:10]
        if envelope.approval_mode != "autonomous":
            raise PermissionError("quality revision loop requires an explicit autonomous envelope")
        if loop.approval_envelope != FidelityArtifact(
            path=envelope_artifact.path, sha256=envelope_artifact.sha256
        ):
            raise PermissionError("loop names another Approval Envelope")
        if "structural_candidate_promotion" not in envelope.allowed_routine_gate_kinds:
            raise PermissionError("envelope does not authorize bounded structural promotion")
        if loop.structural_revision_limit > budget.structural_rounds:
            raise PermissionError("loop structural limit exceeds the frozen AQ root budget")
        if loop.local_revision_limit > budget.parametric_convergence_iterations:
            raise PermissionError("loop local limit exceeds the frozen AQ root budget")
        if loop.cost_limit.builds + loop.cost_limit.materializations > budget.total_blender_builds:
            raise PermissionError("loop build costs exceed the frozen AQ root budget")
        if loop.cost_limit.promotions > budget.canonical_promotions:
            raise PermissionError("loop promotion costs exceed the frozen AQ root budget")
        if loop.cost_limit.qa_runs > budget.total_quality_evaluations:
            raise PermissionError("loop quality costs exceed the frozen AQ root budget")
        if isinstance(loop, AQQualityRevisionLoopV02):
            reserve = loop.initial_pipeline_reserve
            required = {
                "total_blender_builds": (
                    reserve.materializations
                    + reserve.builds
                    + loop.cost_limit.materializations
                    + loop.cost_limit.builds
                ),
                "material_rounds": reserve.closure_runs + loop.cost_limit.closure_runs,
                "canonical_promotions": reserve.promotions + loop.cost_limit.promotions,
                "total_quality_evaluations": reserve.qa_runs + loop.cost_limit.qa_runs,
            }
            for field, amount in required.items():
                if amount > getattr(budget, field):
                    raise PermissionError(
                        "loop initial-plus-revision "
                        f"{field} reserve exceeds the frozen AQ root budget"
                    )
        hypothesis = ModelingHypothesisV01.model_validate_json(read_artifact(root, loop.hypothesis))
        if not any(
            item.required and item.applicability == "applicable"
            for item in hypothesis.requirements
        ):
            raise ValueError("AQ loop needs at least one applicable observed requirement")
        authorization = boundary[2]
        if (
            hypothesis.job_id != job_id
            or hypothesis.reference.sha256 != authorization.primary_reference.sha256
        ):
            raise ValueError("hypothesis differs from the authorized reference")
        return publish(root, _fidelity_root(root, session_id) / "plan.json", loop)


def _load_ledger(
    root: Path, session_id: str, loop: AQQualityRevisionLoop, loop_artifact: FidelityArtifact
) -> list[tuple[RevisionLedgerEntryV01, FidelityArtifact]]:
    """Recompute the entire reservation chain so renamed children cannot reset consumption."""

    paths = sorted((_fidelity_root(root, session_id) / "reservations").glob("*.json"))
    entries = []
    for index, path in enumerate(paths, start=1):
        artifact = artifact_at(root, path)
        entry = RevisionLedgerEntryV01.model_validate_json(read_artifact(root, artifact))
        plan = StructuralReentryPlanV01.model_validate_json(read_artifact(root, entry.plan))
        previous, previous_artifact = entries[-1] if entries else (None, None)
        expected = reserve_revision(
            loop,
            plan,
            loop_artifact=loop_artifact,
            plan_artifact=entry.plan,
            previous=previous,
            previous_artifact=previous_artifact,
        )
        if path.stem != f"{index:04d}" or entry != expected:
            raise ValueError("quality revision ledger changed or skipped a reservation")
        entries.append((entry, artifact))
    return entries


def _attempts(
    root: Path, session_id: str, loop_artifact: FidelityArtifact
) -> list[tuple[QualityAttemptV01, FidelityArtifact]]:
    """Read contiguous rounds and at most one immutable missing-evidence supplement per round."""

    result = []
    for index, path in enumerate(
        sorted((_fidelity_root(root, session_id) / "attempts").glob("*.json"))
    ):
        artifact = artifact_at(root, path)
        attempt = QualityAttemptV01.model_validate_json(read_artifact(root, artifact))
        if (
            path.stem != f"{index:04d}"
            or attempt.round_index != index
            or attempt.loop != loop_artifact
            or attempt.previous_attempt != (result[-1][1] if result else None)
            or attempt.supplements_attempt is not None
        ):
            raise ValueError("quality attempt chain changed or reset")
        _validate_attempt_artifacts(root, attempt)
        supplement_path = _fidelity_root(root, session_id) / "evidence_supplements" / path.name
        if supplement_path.exists():
            supplement_artifact = artifact_at(root, supplement_path)
            supplement = QualityAttemptV01.model_validate_json(
                read_artifact(root, supplement_artifact)
            )
            _validate_attempt_artifacts(root, supplement)
            _validate_evidence_supplement(root, attempt, artifact, supplement)
            attempt, artifact = supplement, supplement_artifact
        result.append((attempt, artifact))
    return result


def _validate_attempt_artifacts(root: Path, attempt: QualityAttemptV01) -> None:
    """Rehash each receipt/source and require paired comparison for every revised geometry round."""

    if (attempt.round_index == 0) != (attempt.paired_comparison is None):
        raise ValueError("revised quality round must preserve its paired comparison")
    for item in (
        attempt.scene_spec,
        attempt.source_state,
        attempt.geometry_receipt,
        attempt.material_receipt,
        attempt.quality_submission,
        attempt.visual_review,
        attempt.fidelity_evaluation,
        *([attempt.paired_comparison] if attempt.paired_comparison is not None else []),
        *([attempt.supplements_attempt] if attempt.supplements_attempt is not None else []),
    ):
        read_artifact(root, item)
    evaluation = FidelityEvaluationV01.model_validate_json(
        read_artifact(root, attempt.fidelity_evaluation)
    )
    review = VisualFindingSetV01.model_validate_json(read_artifact(root, attempt.visual_review))
    identity_changed = (
        evaluation.visual_review != attempt.visual_review
        or evaluation.hypothesis != review.hypothesis
        or review.evidence.scene_spec != attempt.scene_spec
    )
    visual_only = (
        attempt.unresolved_features == [item.feature_id for item in evaluation.findings]
        and attempt.next_action == evaluation.next_action
    )
    if identity_changed:
        raise ValueError("quality attempt differs from its exact evaluated findings or source")
    if visual_only:
        # Historical V0.1 attempts intentionally retain their original visual-only route.
        return
    if not _uses_integrated_attempt_routing(attempt):
        raise ValueError("quality attempt differs from its exact evaluated findings or source")
    loop = parse_quality_revision_loop(read_artifact(root, attempt.loop))
    report = _quality_submission_report(root, attempt.quality_submission)
    route, unresolved = _combined_attempt_routing(evaluation, report, loop=loop)
    if attempt.next_action != route or attempt.unresolved_features != unresolved:
        raise ValueError("quality attempt differs from its exact visual and IQ findings")


def _validate_evidence_supplement(
    root: Path,
    original: QualityAttemptV01,
    original_artifact: FidelityArtifact,
    supplement: QualityAttemptV01,
) -> None:
    """Allow missing judgments on identical rendered source, never defect erasure."""

    mutable = {
        "visual_review",
        "fidelity_evaluation",
        "unresolved_features",
        "next_action",
        "paired_comparison",
        "supplements_attempt",
    }
    if (
        supplement.supplements_attempt != original_artifact
        or original.supplements_attempt is not None
        or original.next_action != "evidence_required"
        or original.model_dump(exclude=mutable) != supplement.model_dump(exclude=mutable)
    ):
        raise ValueError("evidence supplement changed source, authority or non-missing findings")
    old_review = VisualFindingSetV01.model_validate_json(
        read_artifact(root, original.visual_review)
    )
    new_review = VisualFindingSetV01.model_validate_json(
        read_artifact(root, supplement.visual_review)
    )
    old_evaluation = FidelityEvaluationV01.model_validate_json(
        read_artifact(root, original.fidelity_evaluation)
    )
    hypothesis = ModelingHypothesisV01.model_validate_json(
        read_artifact(root, old_review.hypothesis)
    )
    qa = validate_review_evidence(root, hypothesis, old_review)
    if old_evaluation != evaluate_review(
        hypothesis,
        old_review,
        review_artifact=original.visual_review,
        legacy_direct_score=qa.direct_metrics.overall_direct_score,
    ):
        raise ValueError("original missing-evidence evaluation does not match its observations")
    allowed = {
        item.feature_id for item in old_evaluation.findings if item.kind == "missing_evidence"
    }
    if old_review.model_dump(exclude={"assessments", "review_id"}) != new_review.model_dump(
        exclude={"assessments", "review_id"}
    ):
        raise ValueError("evidence supplement cannot substitute camera, source or rendered passes")
    before = {
        item.feature_id: item for item in old_review.assessments if item.feature_id not in allowed
    }
    after = {
        item.feature_id: item for item in new_review.assessments if item.feature_id not in allowed
    }
    if before != after:
        raise ValueError("evidence supplement cannot erase or rerate an already observed defect")


def current_round_receipts(
    root: Path, plan: AutonomyPlanV2, state: AutonomyStateV2
) -> tuple[AQV2Artifact, AQV2Artifact]:
    """Select only the ordered geometry/material pair after the latest exact reentry marker."""

    binding = load_optional_loop(root, plan.session_id)
    if binding is None:
        raise PermissionError("round receipt selection requires an explicit fidelity companion")
    markers = [index for index, item in enumerate(state.provenance) if item.kind == REENTRY_KIND]
    start = markers[-1] + 1 if markers else 0
    geometry = [
        item
        for item in state.provenance[start:]
        if item.kind == "geometry_candidate_validation_receipt"
    ]
    reentry = active_reentry(root, plan, state) if markers else None
    carried_geometry = False
    if reentry is not None and reentry.route == "material_revision":
        if geometry:
            raise ValueError("material-only revision cannot introduce a geometry promotion")
        previous_attempt = QualityAttemptV01.model_validate_json(
            read_artifact(root, reentry.attempt)
        )
        geometry = [
            item
            for item in state.provenance[:start]
            if (item.path, item.sha256)
            == (previous_attempt.geometry_receipt.path, previous_attempt.geometry_receipt.sha256)
            and item.kind == "geometry_candidate_validation_receipt"
        ]
        carried_geometry = True
    material = [item for item in state.provenance[start:] if item.kind == "material_phase_receipt"]
    if len(geometry) != 1 or len(material) != 1:
        raise ValueError("current round requires exactly one geometry/material receipt tuple")
    if state.provenance[-1] != material[0] or (
        not carried_geometry
        and state.provenance.index(geometry[0]) >= state.provenance.index(material[0])
    ):
        raise ValueError("current round receipt tuple is stale or mixed")
    return geometry[0], material[0]


def fidelity_authoring_inputs(
    root: Path, plan: AutonomyPlanV2, state: AutonomyStateV2, inputs: list[AQV2Artifact]
) -> list[AQV2Artifact]:
    """Bind observations and diagnosed renders to either bounded authoring controller."""

    from .delivery_service import artifact_for_v2

    binding = load_optional_loop(root, plan.session_id)
    if binding is None:
        return inputs
    loop, loop_artifact = binding
    required = [loop_artifact, loop.hypothesis]
    markers = [item for item in state.provenance if item.kind == REENTRY_KIND]
    if markers:
        marker = FidelityArtifact(path=markers[-1].path, sha256=markers[-1].sha256)
        reentry = StructuralReentryPlanV01.model_validate_json(read_artifact(root, marker))
        if reentry.loop != loop_artifact:
            raise ValueError("geometry context belongs to a different revision loop")
        attempt = QualityAttemptV01.model_validate_json(read_artifact(root, reentry.attempt))
        review = VisualFindingSetV01.model_validate_json(read_artifact(root, attempt.visual_review))
        required += [marker, reentry.attempt, attempt.visual_review, attempt.fidelity_evaluation]
        if _uses_integrated_attempt_routing(attempt):
            submission = attempt.quality_submission
            report = _quality_submission_report(root, submission)
            from .supervisor_service import QualitySubmissionV2

            quality_submission = QualitySubmissionV2.model_validate_json(
                read_artifact(root, submission)
            )
            required.extend(
                [
                    submission,
                    FidelityArtifact(
                        path=quality_submission.integrated_quality_report.path,
                        sha256=quality_submission.integrated_quality_report.sha256,
                    ),
                ]
            )
            if report.quality_accepted:
                raise ValueError("combined reentry context cannot name an accepted IQ report")
        required += list(review.evidence.passes.values())
    result = list(inputs)
    for index, artifact in enumerate(required):
        read_artifact(root, artifact)
        matches = [item for item in result if item.path == artifact.path]
        if matches:
            if len(matches) != 1 or matches[0].sha256 != artifact.sha256:
                raise ValueError("controller substitutes a different observation or finding")
            continue
        result.append(
            artifact_for_v2(
                root,
                root / artifact.path,
                artifact_id=f"fidelity-context-{index}",
                kind="assignment",
            )
        )
    return result


def fidelity_geometry_inputs(
    root: Path, plan: AutonomyPlanV2, state: AutonomyStateV2, inputs: list[AQV2Artifact]
) -> list[AQV2Artifact]:
    """Preserve the original geometry helper while delegating to common authoring context."""

    return fidelity_authoring_inputs(root, plan, state, inputs)


def submit_quality_attempt(
    job_id: str, session_id: str, *, review_path: Path, quality_submission_path: Path
) -> FidelityArtifact:
    """Evaluate exact IQ plus visual findings without freezing, terminalizing or approving."""

    from .controller_bridge import _session_bundle
    from .supervisor_service import (
        QualitySubmissionV2,
        _load_authorization,
        _validate_quality_submission,
    )

    root, session, plan, budget, state, state_artifact = _session_bundle(job_id, session_id)
    with autonomy_session_lock(root, session, owner_id="reference-fidelity-attempt"):
        binding = load_optional_loop(root, session_id)
        if binding is None:
            raise PermissionError("quality attempt requires an explicitly bound loop")
        loop, loop_artifact = binding
        if _session_bundle(job_id, session_id)[4] != state:
            raise ValueError("AQ state changed before quality evaluation")
        if state.next_action != "run_integrated_quality" or state.quality_terminal is not None:
            raise PermissionError("quality attempt requires a live nonterminal quality boundary")
        review_artifact = artifact_at(root, root / review_path)
        review = VisualFindingSetV01.model_validate_json(read_artifact(root, review_artifact))
        if review.hypothesis != loop.hypothesis:
            raise ValueError("review changed frozen observation requirements")
        if review.evidence.build_sources is None:
            raise ValueError("new-loop visual attempts require immutable build source snapshots")
        if review.evidence.geometry_payloads and not review.evidence.geometry_snapshots:
            raise ValueError("new-loop attempts require immutable geometry payload snapshots")
        if review.evidence.comparison_conditions is None:
            raise ValueError("new-loop visual attempts require actual fixed render conditions")
        if review.evidence.scene_spec.sha256 != sha256_file(root / "analysis/scene_spec.json"):
            raise ValueError("visual review does not evaluate current canonical geometry")
        hypothesis = ModelingHypothesisV01.model_validate_json(read_artifact(root, loop.hypothesis))
        qa = validate_review_evidence(root, hypothesis, review)
        submission_artifact = artifact_at(root, root / quality_submission_path)
        submission = QualitySubmissionV2.model_validate_json(
            read_artifact(root, submission_artifact)
        )
        validated = _validate_quality_submission(
            root, plan, state, _load_authorization(root, plan), submission
        )
        if validated.report.legacy_v06_report_sha256 != review.evidence.qa_report.sha256:
            raise ValueError("IQ and visual assessment name different QA runs")
        geometry, material = current_round_receipts(root, plan, state)
        entries = _load_ledger(root, session_id, loop, loop_artifact)
        round_index = sum(item.kind == REENTRY_KIND for item in state.provenance)
        matching_renders = [
            entry
            for entry, _artifact in _render_reservations(root, session_id, loop_artifact)
            if entry.run_id == qa.run_id and entry.round_index == round_index
        ]
        if (
            len(matching_renders) != 1
            or matching_renders[0].source.sha256 != review.evidence.scene_spec.sha256
            or matching_renders[0].build_fingerprint != review.evidence.build_fingerprint
            or matching_renders[0].source_state
            != FidelityArtifact(path=state_artifact.path, sha256=state_artifact.sha256)
        ):
            raise ValueError(
                "visual attempt has no exact pre-reserved render for this source round"
            )
        if len(entries) not in {round_index, round_index + 1}:
            raise ValueError("round count and reservation chain differ")
        previous = _attempts(root, session_id, loop_artifact)
        if len(previous) > round_index:
            existing, artifact = previous[round_index]
            if (
                existing.visual_review != review_artifact
                or existing.quality_submission != submission_artifact
            ):
                raise ValueError("cannot replace an already recorded quality attempt")
            return artifact
        if len(previous) != round_index:
            raise ValueError("earlier round quality evidence is missing")
        if state.budget_usage.total_quality_evaluations + 1 > budget.total_quality_evaluations:
            raise PermissionError("AQ quality evaluation budget exhausted")
        evaluation = evaluate_review(
            hypothesis,
            review,
            review_artifact=review_artifact,
            legacy_direct_score=qa.direct_metrics.overall_direct_score,
        )
        next_action, unresolved = _combined_attempt_routing(
            evaluation,
            validated.report,
            loop=loop,
        )
        base = _fidelity_root(root, session_id)
        evaluation_artifact = publish(
            root, base / "evaluations" / f"{round_index:04d}.json", evaluation
        )
        comparison = None
        if previous:
            comparison = compare_evaluation_files(
                root,
                before_path=root / previous[-1][0].fidelity_evaluation.path,
                after_path=root / evaluation_artifact.path,
                output=base / "comparisons" / f"{round_index:04d}.json",
            )
        strategy = hypothesis.authoring_strategy
        if round_index:
            reentry = StructuralReentryPlanV01.model_validate_json(
                read_artifact(root, entries[round_index - 1][0].plan)
            )
            strategy = reentry.strategy
        attempt = QualityAttemptV01(
            loop=loop_artifact,
            round_index=round_index,
            source_state=FidelityArtifact(path=state_artifact.path, sha256=state_artifact.sha256),
            scene_spec=review.evidence.scene_spec,
            geometry_receipt=FidelityArtifact(path=geometry.path, sha256=geometry.sha256),
            material_receipt=FidelityArtifact(path=material.path, sha256=material.sha256),
            quality_submission=submission_artifact,
            visual_review=review_artifact,
            fidelity_evaluation=evaluation_artifact,
            strategy=strategy,
            unresolved_features=unresolved,
            next_action=next_action,
            previous_attempt=previous[-1][1] if previous else None,
            paired_comparison=comparison,
        )
        return publish(root, base / "attempts" / f"{round_index:04d}.json", attempt)


def supplement_quality_evidence(
    job_id: str, session_id: str, *, review_path: Path
) -> FidelityArtifact:
    """Fill missing observations once without replacing history, rerendering or budget reset."""

    from .controller_bridge import _session_bundle

    root, session, plan, _budget, state, state_artifact = _session_bundle(job_id, session_id)
    with autonomy_session_lock(root, session, owner_id="reference-fidelity-evidence-supplement"):
        if _session_bundle(job_id, session_id)[4] != state:
            raise ValueError("AQ state changed before evidence supplementation")
        binding = load_optional_loop(root, session_id)
        if binding is None or state.next_action != "run_integrated_quality":
            raise PermissionError("evidence supplementation requires a live bound quality session")
        loop, loop_artifact = binding
        attempts = _attempts(root, session_id, loop_artifact)
        round_index = sum(item.kind == REENTRY_KIND for item in state.provenance)
        if len(attempts) != round_index + 1:
            raise PermissionError("current round has no missing-evidence attempt to supplement")
        original, original_artifact = attempts[-1]
        review_artifact = artifact_at(root, root / review_path)
        if original.supplements_attempt is not None:
            if original.visual_review == review_artifact:
                return original_artifact
            raise PermissionError(
                "one evidence supplement was already used; preserve all judgments"
            )
        if original.next_action != "evidence_required":
            raise PermissionError("only missing-evidence judgments may be supplemented")
        if len(_load_ledger(root, session_id, loop, loop_artifact)) != round_index:
            raise PermissionError("a reserved correction cannot change its diagnosed findings")
        if original.source_state != FidelityArtifact(
            path=state_artifact.path, sha256=state_artifact.sha256
        ):
            raise ValueError("supplement would replace a different source state")
        # Revalidate current source/receipt bindings before publishing any new evidence.
        quality_revision_boundary(root, plan, state)
        review = VisualFindingSetV01.model_validate_json(read_artifact(root, review_artifact))
        hypothesis = ModelingHypothesisV01.model_validate_json(read_artifact(root, loop.hypothesis))
        qa = validate_review_evidence(root, hypothesis, review)
        evaluation = evaluate_review(
            hypothesis,
            review,
            review_artifact=review_artifact,
            legacy_direct_score=qa.direct_metrics.overall_direct_score,
        )
        if _uses_integrated_attempt_routing(original):
            next_action, unresolved = _combined_attempt_routing(
                evaluation,
                _quality_submission_report(root, original.quality_submission),
                loop=loop,
            )
        else:
            next_action = evaluation.next_action
            unresolved = [item.feature_id for item in evaluation.findings]
        proposed = original.model_copy(
            update={
                "visual_review": review_artifact,
                "unresolved_features": unresolved,
                "next_action": next_action,
                "supplements_attempt": original_artifact,
            }
        )
        _validate_evidence_supplement(root, original, original_artifact, proposed)
        base = _fidelity_root(root, session_id)
        evaluation_artifact = publish(
            root, base / "supplement_evaluations" / f"{round_index:04d}.json", evaluation
        )
        comparison = None
        if round_index:
            comparison = compare_evaluation_files(
                root,
                before_path=root / attempts[-2][0].fidelity_evaluation.path,
                after_path=root / evaluation_artifact.path,
                output=base / "supplement_comparisons" / f"{round_index:04d}.json",
            )
        proposed = proposed.model_copy(
            update={
                "fidelity_evaluation": evaluation_artifact,
                "paired_comparison": comparison,
            }
        )
        return publish(root, base / "evidence_supplements" / f"{round_index:04d}.json", proposed)


def render_quality_evidence(job_id: str, session_id: str, *, run_id: str) -> dict[str, object]:
    """Validate explicit observation seeds, reserve bounded QA, and capture immutable inputs."""

    from ..build_provenance import collect_build_provenance
    from ..qa.service import _validate_run_id, run_scene_spec_visual_qa_snapshot
    from ..reference_fidelity.service import capture_render_evidence
    from .controller_bridge import _session_bundle

    _validate_run_id(run_id)
    root, session, plan, budget, state, state_artifact = _session_bundle(job_id, session_id)
    with autonomy_session_lock(root, session, owner_id="reference-fidelity-render"):
        if _session_bundle(job_id, session_id)[4] != state:
            raise ValueError("AQ state changed before the quality render")
        binding = load_optional_loop(root, session_id)
        if binding is None or state.next_action != "run_integrated_quality":
            raise PermissionError("fidelity rendering requires a live bound quality session")
        loop, loop_artifact = binding
        current_round_receipts(root, plan, state)
        entries = _load_ledger(root, session_id, loop, loop_artifact)
        round_index = sum(item.kind == REENTRY_KIND for item in state.provenance)
        limit = 1 + loop.same_input_technical_retries
        if round_index:
            reentry = StructuralReentryPlanV01.model_validate_json(
                read_artifact(root, entries[round_index - 1][0].plan)
            )
            limit = reentry.cost.qa_runs
        reservations = _fidelity_root(root, session_id) / "render_reservations"
        records = _render_reservations(root, session_id, loop_artifact)
        source = artifact_at(root, root / "analysis/scene_spec.json")
        hypothesis = ModelingHypothesisV01.model_validate_json(read_artifact(root, loop.hypothesis))
        seed_evidence = hypothesis.reference_mask_seed_evidence
        if seed_evidence is not None:
            from ..models import SceneSpec
            from ..qa.reference_mask import validate_explicit_reference_seeds
            from ..reference_scope import subject_object_ids
            from ..workspace import find_reference, load_job

            scene = SceneSpec.model_validate_json(read_artifact(root, source))
            selected = (
                subject_object_ids(scene)
                if load_job(job_id).get("reference_content_scope") == "primary_object_only"
                else None
            )
            validate_explicit_reference_seeds(
                root, find_reference(job_id), scene, seed_evidence, allowed_object_ids=selected
            )
        build = collect_build_provenance(root, job_id)["fingerprint"]
        existing = [entry for entry, _artifact in records if entry.run_id == run_id]
        if existing:
            if (
                len(existing) != 1
                or existing[0].round_index != round_index
                or existing[0].source != source
                or existing[0].build_fingerprint != build
                or existing[0].source_state
                != FidelityArtifact(path=state_artifact.path, sha256=state_artifact.sha256)
            ):
                raise ValueError("reserved QA adoption names a different source or state")
            report_path = root / "qa/runs" / run_id / "visual_qa_report.json"
            if not report_path.exists():
                raise PermissionError(
                    "reserved QA is incomplete; preserve it and use the bounded technical retry"
                )
            evidence = capture_render_evidence(
                root, qa_run_id=run_id, output_dir=root / "fidelity/render_evidence" / run_id
            )
            return {
                "status": "existing",
                "qa_report": artifact_at(root, report_path).model_dump(mode="json"),
                "render_evidence": evidence.model_dump(mode="json"),
            }
        current = [entry for entry, _artifact in records if entry.round_index == round_index]
        used = len(current)
        if used >= limit or used >= loop.same_input_technical_retries + 1:
            raise PermissionError("reserved QA render budget exhausted; preserve failed attempts")
        if state.budget_usage.total_quality_evaluations + len(records) + 2 > (
            budget.total_quality_evaluations
        ):
            raise PermissionError("root quality budget cannot cover render and IQ evaluation")
        if used:
            previous = current[0]
            if previous.source != source or previous.build_fingerprint != build:
                raise ValueError("technical render retry changed its source")
            if (root / "qa/runs" / previous.run_id / "visual_qa_report.json").exists():
                raise PermissionError(
                    "a successful QA render cannot be retried as a technical failure"
                )
        run_dir = root / "qa/runs" / run_id
        if run_dir.exists():
            raise FileExistsError("QA run already exists; never replace its evidence")
        reservation = QualityRenderReservationV01(
            loop=loop_artifact,
            sequence=len(records) + 1,
            previous=records[-1][1] if records else None,
            round_index=round_index,
            attempt_index=used,
            source_state=FidelityArtifact(path=state_artifact.path, sha256=state_artifact.sha256),
            source=source,
            build_fingerprint=build,
            run_id=run_id,
        )
        publish(root, reservations / f"{round_index:04d}-{used:04d}.json", reservation)
        result = run_scene_spec_visual_qa_snapshot(
            job_id,
            scene_spec_path=root / source.path,
            blend_path=root / "blender/scene.blend",
            run_dir=run_dir,
            run_id=run_id,
            record_fidelity_conditions=True,
            **({"reference_mask_seed_evidence": seed_evidence}
               if seed_evidence is not None else {}),
        )
        read_artifact(root, source)
        evidence = capture_render_evidence(
            root, qa_run_id=run_id, output_dir=root / "fidelity/render_evidence" / run_id
        )
        return {"qa": result, "render_evidence": evidence.model_dump(mode="json")}


def _render_reservations(
    root: Path, session_id: str, loop_artifact: FidelityArtifact
) -> list[tuple[QualityRenderReservationV01, FidelityArtifact]]:
    """Validate the non-resettable render ledger separately from IQ-attempt counters."""

    records = []
    counts: dict[int, int] = {}
    for path in sorted((_fidelity_root(root, session_id) / "render_reservations").glob("*.json")):
        artifact = artifact_at(root, path)
        entry = QualityRenderReservationV01.model_validate_json(read_artifact(root, artifact))
        expected_index = counts.get(entry.round_index, 0)
        if (
            entry.loop != loop_artifact
            or entry.sequence != len(records) + 1
            or entry.previous != (records[-1][1] if records else None)
            or entry.attempt_index != expected_index
            or path.stem != f"{entry.round_index:04d}-{expected_index:04d}"
        ):
            raise ValueError("QA reservation ledger changed, skipped or reset")
        source_state = AutonomyStateV2.model_validate_json(read_artifact(root, entry.source_state))
        if (
            source_state.session_id != session_id
            or source_state.next_action != "run_integrated_quality"
            or sum(item.kind == REENTRY_KIND for item in source_state.provenance)
            != entry.round_index
        ):
            raise ValueError("QA reservation belongs to another state or source round")
        counts[entry.round_index] = expected_index + 1
        records.append((entry, artifact))
    return records


def quality_revision_boundary(
    root: Path, plan: AutonomyPlanV2, state: AutonomyStateV2
) -> dict[str, object] | None:
    """Block legacy terminal publication until the current exact visual attempt is satisfied."""

    binding = load_optional_loop(root, plan.session_id)
    if binding is None:
        return None
    loop, loop_artifact = binding
    entries = _load_ledger(root, plan.session_id, loop, loop_artifact)
    attempts = _attempts(root, plan.session_id, loop_artifact)
    current_round = sum(item.kind == REENTRY_KIND for item in state.provenance)
    if len(entries) not in {current_round, current_round + 1}:
        raise ValueError("round count and reservation chain differ")
    if not attempts or attempts[-1][0].round_index != current_round:
        return {
            "status": "waiting_for_reference_fidelity_review",
            "next_action": "submit_quality_attempt",
        }
    attempt, artifact = attempts[-1]
    if attempt.scene_spec.sha256 != sha256_file(root / "analysis/scene_spec.json"):
        raise ValueError("quality attempt source has changed")
    geometry, material = current_round_receipts(root, plan, state)
    if (geometry.sha256, material.sha256) != (
        attempt.geometry_receipt.sha256,
        attempt.material_receipt.sha256,
    ):
        raise ValueError("quality attempt borrows a different round's promotion receipts")
    evaluation = FidelityEvaluationV01.model_validate_json(
        read_artifact(root, attempt.fidelity_evaluation)
    )
    review = VisualFindingSetV01.model_validate_json(read_artifact(root, attempt.visual_review))
    hypothesis = ModelingHypothesisV01.model_validate_json(read_artifact(root, loop.hypothesis))
    qa = validate_review_evidence(root, hypothesis, review)
    expected = evaluate_review(
        hypothesis,
        review,
        review_artifact=attempt.visual_review,
        legacy_direct_score=qa.direct_metrics.overall_direct_score,
    )
    if expected != evaluation:
        raise ValueError("fidelity evaluation differs from recomputed observation coverage")
    routed_evaluation = evaluation.model_copy(update={"next_action": attempt.next_action})
    # A crash-surviving next reservation is adopted by begin_reentry, not charged twice.
    completed = entries[:current_round]
    last = completed[-1][0] if completed else None
    route, reason = select_revision_route(
        routed_evaluation,
        [item[0] for item in attempts],
        loop=loop,
        structural_used=last.structural_used if last else 0,
        local_used=last.local_used if last else 0,
        strategy_switches_used=last.strategy_switches_used if last else 0,
    )
    if route in {"structural_reentry", "parametric_revision", "material_revision"}:
        from ..models import SceneSpec

        budget = parse_autonomy_budget(
            read_artifact(root, FidelityArtifact(path=plan.budget.path, sha256=plan.budget.sha256))
        )
        minimum = 1 if route == "material_revision" else 2
        promotions = minimum
        scene = SceneSpec.model_validate_json(read_artifact(root, attempt.scene_spec))
        materializations = len(scene.objects) if route != "material_revision" else 0
        funded_insufficient = False
        if isinstance(loop, AQQualityRevisionLoopV03):
            costs = loop.funding.route_cost(route)
            minimum, promotions = costs["builds"], costs["promotions"]
            funded_insufficient = (
                funded_route_usage(last)[route] >= loop.funding.route_limits()[route]
                or materializations > costs["materializations"]
            )
            materializations = costs["materializations"]
        renders = len(_render_reservations(root, plan.session_id, loop_artifact))
        used = last.cost_used if last else RevisionCostV01()
        insufficient = (
            funded_insufficient
            or state.budget_usage.material_rounds >= budget.material_rounds
            or state.budget_usage.total_blender_builds + minimum + materializations
            > budget.total_blender_builds
            or state.budget_usage.canonical_promotions + promotions > budget.canonical_promotions
            or state.budget_usage.total_quality_evaluations + renders
            + (4 if isinstance(loop, AQQualityRevisionLoopV03) else 3)
            > budget.total_quality_evaluations
            or used.builds + minimum > loop.cost_limit.builds
            or used.materializations + materializations > loop.cost_limit.materializations
            or used.promotions + promotions > loop.cost_limit.promotions
            or used.closure_runs + 1 > loop.cost_limit.closure_runs
            or used.qa_runs + (3 if isinstance(loop, AQQualityRevisionLoopV03) else 1)
            > loop.cost_limit.qa_runs
        )
        if insufficient:
            route = "review_required"
            reason = "Frozen root or companion cost budget cannot cover another correction."
    return {
        "status": route,
        "next_action": route,
        "reason": reason,
        "attempt": artifact.model_dump(mode="json"),
        "human_quality_disposition": "not_recorded",
    }


def validate_final_quality_submission(
    root: Path, plan: AutonomyPlanV2, state: AutonomyStateV2, submission: object
) -> None:
    """Prevent substituting a different IQ/source tuple after the visual gate was satisfied."""

    from .supervisor_service import QualitySubmissionV2

    binding = load_optional_loop(root, plan.session_id)
    if binding is None:
        return
    boundary = quality_revision_boundary(root, plan, state)
    if boundary is None or boundary["next_action"] != "quality_ready":
        raise PermissionError("exact current visual findings do not permit quality publication")
    attempt = _attempts(root, plan.session_id, binding[1])[-1][0]
    expected = QualitySubmissionV2.model_validate_json(
        read_artifact(root, attempt.quality_submission)
    )
    actual = (
        submission
        if isinstance(submission, QualitySubmissionV2)
        else (QualitySubmissionV2.model_validate(submission))
    )
    if actual != expected:
        raise ValueError("final quality submission differs from the evaluated round")


def begin_quality_reentry(
    job_id: str,
    session_id: str,
    *,
    strategy: str,
    cost: RevisionCostV01,
    required_route: str | None = None,
) -> dict[str, object]:
    """Reserve the diagnosed structural/scalar/material route before returning to its controller."""

    from .controller_bridge import _session_bundle
    from .delivery_service import artifact_for_v2
    from .supervisor_service import _write_next_state
    from .transitions import transition_state

    root, session, plan, budget, state, state_artifact = _session_bundle(job_id, session_id)
    with autonomy_session_lock(root, session, owner_id="reference-fidelity-reentry"):
        if _session_bundle(job_id, session_id)[4] != state:
            raise ValueError("AQ state changed before structural reentry")
        if state.next_action != "run_integrated_quality" or state.quality_terminal is not None:
            raise PermissionError("structural reentry cannot reopen a terminal or accepted freeze")
        boundary = quality_revision_boundary(root, plan, state)
        if boundary is None or boundary["next_action"] not in {
            "structural_reentry",
            "parametric_revision",
            "material_revision",
        }:
            raise PermissionError("current exact findings do not authorize a correction")
        route = str(boundary["next_action"])
        if required_route is not None and required_route != route:
            raise PermissionError("requested correction route differs from the exact findings")
        loop, loop_artifact = load_optional_loop(root, session_id)
        attempts = _attempts(root, session_id, loop_artifact)
        attempt, attempt_artifact = attempts[-1]
        evaluation = FidelityEvaluationV01.model_validate_json(
            read_artifact(root, attempt.fidelity_evaluation)
        )
        previous_entries = _load_ledger(root, session_id, loop, loop_artifact)
        if len(previous_entries) not in {attempt.round_index, attempt.round_index + 1}:
            raise ValueError("this quality attempt differs from the reserved round")
        strategy_changed = strategy != attempt.strategy
        # Strategy may change within a material/scalar route, but never expands its
        # geometry authority or converts surface defects into structural reauthoring.
        if require_strategy_change([item[0] for item in attempts]) and not strategy_changed:
            raise PermissionError("repeated defect requires a new representation strategy")
        if (
            state.budget_usage.total_blender_builds + cost.builds + cost.materializations
            > budget.total_blender_builds
        ):
            raise PermissionError("remaining AQ build budget cannot cover the correction")
        if state.budget_usage.canonical_promotions + cost.promotions > budget.canonical_promotions:
            raise PermissionError("remaining AQ promotion budget cannot cover the correction")
        minimum_promotions = 1 if route == "material_revision" else 2
        minimum_builds = 1 if route == "material_revision" else 2
        if isinstance(loop, AQQualityRevisionLoopV03):
            if cost.model_dump() != loop.funding.route_cost(route):
                raise PermissionError("correction must reserve its exact funded route cost")
            minimum_builds += 1
        if cost.promotions < minimum_promotions or cost.builds < minimum_builds:
            raise PermissionError(
                "correction must reserve every geometry/material rebuild and promotion"
            )
        if route != "material_revision":
            from ..models import SceneSpec

            current_scene = SceneSpec.model_validate_json(read_artifact(root, attempt.scene_spec))
            if cost.materializations < len(current_scene.objects):
                raise PermissionError(
                    "reserve all current object materializations before correction"
                )
        if cost.closure_runs < 1 or state.budget_usage.material_rounds >= budget.material_rounds:
            raise PermissionError("correction needs an available material-closure round")
        if (
            state.budget_usage.total_quality_evaluations
            + len(_render_reservations(root, session_id, loop_artifact))
            + (1 if isinstance(loop, AQQualityRevisionLoopV03) else 2)
            + cost.qa_runs
            > budget.total_quality_evaluations
        ):
            raise PermissionError("remaining AQ quality budget cannot cover the correction")
        if state.budget_usage.total_actions + 1 >= min(
            budget.global_action_limit, plan.action_limit
        ):
            raise PermissionError("remaining AQ action budget cannot cover structural reentry")
        hypothesis = ModelingHypothesisV01.model_validate_json(read_artifact(root, loop.hypothesis))
        selected = [item for item in evaluation.findings if item.route == route]
        if not selected and strategy_changed:
            selected = [
                item
                for item in evaluation.findings
                if item.route in {"parametric_revision", "material_revision"}
            ]
        feature_ids = [item.feature_id for item in selected]
        targets = {key for finding in selected for key in finding.target_ids}
        if _uses_integrated_attempt_routing(attempt):
            report = _quality_submission_report(root, attempt.quality_submission)
            findings_by_id = {item.finding_id: item for item in report.findings}
            for decision in report.reentry:
                if _iq_reentry_route_for_loop(decision, evaluation, report, loop) != route:
                    continue
                finding = findings_by_id[decision.finding_id]
                feature_ids.append(f"iq:{finding.finding_id}")
                targets.update(finding.target_ids)
        if not targets:
            targets.update(
                target
                for requirement in hypothesis.requirements
                if requirement.required and requirement.applicability == "applicable"
                for target in requirement.target_ids
            )
        feature_ids = list(dict.fromkeys(feature_ids))
        target_ids = sorted(targets)
        if not feature_ids or not target_ids:
            raise ValueError("correction route has no exact finding or affected target")
        base = _fidelity_root(root, session_id)
        snapshot = base / "sources" / f"{attempt.round_index + 1:04d}"
        sources = (
            (root / "analysis/scene_spec.json", snapshot / "scene.json"),
            (root / "analysis/modeling_plan.json", snapshot / "modeling.json"),
            (root / "blender/scene.blend", snapshot / "scene.blend"),
        )
        planned_sources = [
            FidelityArtifact(
                path=destination.relative_to(root).as_posix(),
                sha256=artifact_at(root, source).sha256,
            )
            for source, destination in sources
        ]
        reentry = StructuralReentryPlanV01(
            loop=loop_artifact,
            attempt=attempt_artifact,
            round_index=attempt.round_index + 1,
            source_scene=planned_sources[0],
            source_modeling_plan=planned_sources[1],
            source_blend=planned_sources[2],
            feature_ids=feature_ids,
            target_ids=target_ids,
            route=route,
            strategy=strategy,
            change_strategy=strategy_changed,
            cost=cost,
            comparison_camera_sha256=hypothesis.camera.camera_fingerprint,
            policy_gate={
                "structural_reentry": "structural_candidate_promotion",
                "parametric_revision": "bounded_parametric_revision",
                "material_revision": "material_candidate_promotion",
            }[route],
        )
        completed_entries = previous_entries[: attempt.round_index]
        previous, previous_artifact = completed_entries[-1] if completed_entries else (None, None)
        reentry_path = base / "reentries" / f"{reentry.round_index:04d}.json"
        # Run pure limits before copying even a potentially large Blender snapshot.
        # The provisional hash is never published or used as execution authority.
        reserve_revision(
            loop,
            reentry,
            loop_artifact=loop_artifact,
            plan_artifact=FidelityArtifact(
                path=reentry_path.relative_to(root).as_posix(), sha256="0" * 64
            ),
            previous=previous,
            previous_artifact=previous_artifact,
        )
        for (source, destination), expected in zip(sources, planned_sources, strict=True):
            if _snapshot_source(root, source, destination) != expected:
                raise ValueError("canonical source changed while reserving its revision")
        reentry_artifact = publish(root, reentry_path, reentry)
        reservation = reserve_revision(
            loop,
            reentry,
            loop_artifact=loop_artifact,
            plan_artifact=reentry_artifact,
            previous=previous,
            previous_artifact=previous_artifact,
        )
        publish(root, base / "reservations" / f"{reservation.sequence:04d}.json", reservation)
        marker = artifact_for_v2(
            root,
            root / reentry_artifact.path,
            artifact_id=f"fidelity-reentry-{reservation.sequence}",
            kind=REENTRY_KIND,
        )
        # Quality assessment was nonterminal. Count it once when leaving that round.
        usage = state.budget_usage.model_copy(
            update={
                "total_quality_evaluations": state.budget_usage.total_quality_evaluations + 1,
                "total_actions": state.budget_usage.total_actions + 1,
            }
        )
        next_state = transition_state(
            state,
            event="quality_revision_requested",
            evidence=marker,
            created_at=datetime.now(UTC),
            budget_usage=usage,
        )
        state_after = _write_next_state(root, session, next_state)
        return {
            "status": route,
            "reentry": reentry_artifact.model_dump(mode="json"),
            "state": next_state.model_dump(mode="json"),
            "state_artifact": state_after.model_dump(mode="json"),
        }


def begin_structural_reentry(
    job_id: str, session_id: str, *, strategy: str, cost: RevisionCostV01
) -> dict[str, object]:
    """Retain the explicit structural-only boundary; it cannot silently select a local route."""

    return begin_quality_reentry(
        job_id, session_id, strategy=strategy, cost=cost, required_route="structural_reentry"
    )


def active_reentry(
    root: Path, plan: AutonomyPlanV2, state: AutonomyStateV2
) -> StructuralReentryPlanV01 | None:
    """Validate the reserved exact round before any structural policy or host promotion."""

    markers = [item for item in state.provenance if item.kind == REENTRY_KIND]
    if not markers:
        return None
    binding = load_optional_loop(root, plan.session_id)
    if binding is None:
        raise PermissionError("structural reentry lacks its explicitly bound companion")
    loop, loop_artifact = binding
    entries = _load_ledger(root, plan.session_id, loop, loop_artifact)
    marker = FidelityArtifact(path=markers[-1].path, sha256=markers[-1].sha256)
    # A next-round reservation can survive a crash at the quality boundary. It does
    # not replace the active round until its own transition has been committed.
    allowed_lengths = {len(markers)}
    if state.next_action == "run_integrated_quality" and state.quality_terminal is None:
        allowed_lengths.add(len(markers) + 1)
    if len(entries) not in allowed_lengths or entries[len(markers) - 1][0].plan != marker:
        raise ValueError("structural reentry is not the current reserved round")
    reentry = StructuralReentryPlanV01.model_validate_json(read_artifact(root, marker))
    if reentry.loop != loop_artifact:
        raise ValueError("structural plan belongs to another loop")
    read_artifact(root, reentry.attempt)
    return reentry


def validate_reentry_transition(
    root: Path, previous: AutonomyStateV2, current: AutonomyStateV2
) -> None:
    """Verify every historical reentry against its reserved round and pre-transition attempt."""

    binding = load_optional_loop(root, current.session_id)
    if binding is None:
        raise PermissionError("quality reentry has no explicitly bound companion")
    loop, loop_artifact = binding
    base_plan = AutonomyPlanV2.model_validate_json(
        read_artifact(root, FidelityArtifact(path=previous.plan.path, sha256=previous.plan.sha256))
    )
    if (
        loop.root_authorization
        != FidelityArtifact(
            path=base_plan.root_authorization.path, sha256=base_plan.root_authorization.sha256
        )
        or loop.job_id != current.job_id
    ):
        raise ValueError("quality reentry differs from the exact base root")
    marker = FidelityArtifact(
        path=current.provenance[-1].path, sha256=current.provenance[-1].sha256
    )
    reentry = StructuralReentryPlanV01.model_validate_json(read_artifact(root, marker))
    entries = _load_ledger(root, current.session_id, loop, loop_artifact)
    round_index = sum(item.kind == REENTRY_KIND for item in current.provenance)
    if (
        reentry.loop != loop_artifact
        or reentry.round_index != round_index
        or round_index > len(entries)
        or entries[round_index - 1][0].plan != marker
    ):
        raise ValueError("reentry marker has no exact non-resettable round reservation")
    attempts = _attempts(root, current.session_id, loop_artifact)
    if round_index > len(attempts) or reentry.attempt != attempts[round_index - 1][1]:
        raise ValueError("reentry borrows another round's findings")
    attempt = attempts[round_index - 1][0]
    before = AutonomyStateV2.model_validate_json(read_artifact(root, attempt.source_state))
    if before != previous or reentry.source_scene.sha256 != attempt.scene_spec.sha256:
        raise ValueError("reentry does not bind the exact previous state/source")
    for item in (reentry.source_scene, reentry.source_modeling_plan, reentry.source_blend):
        read_artifact(root, item)
    expected_usage = previous.budget_usage.model_copy(
        update={
            "total_actions": previous.budget_usage.total_actions + 1,
            "total_quality_evaluations": previous.budget_usage.total_quality_evaluations + 1,
        }
    )
    if current.budget_usage != expected_usage:
        raise ValueError(
            "quality reentry changed unrelated counters or skipped its evaluation cost"
        )
