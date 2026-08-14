"""Pure material-attempt versus canonical-snapshot consistency projection."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from ..build_provenance import collect_build_provenance
from .collector import (
    MaterialClosureCollectionError,
    validate_exact_artifact_current,
    validate_material_plan_absence_evidence,
)
from .models import (
    AQV2StatusProjection,
    ExactArtifact,
    MaterialAttemptState,
    MaterialCanonicalMaterialPlanAbsence,
    MaterialCanonicalSnapshot,
    MaterialClosureIssue,
    MaterialStateConsistencyReport,
    MaterialStateDifference,
)


def _derive_aq_v2_combined_status(
    *,
    top_level_status: str,
    state_consistent: bool,
    material_attempt_state: str | None,
    blocking_companion_present: bool,
) -> str:
    """Derive one fail-closed status without hiding raw terminal or companion failure."""

    if not state_consistent:
        return "inconsistent"
    if blocking_companion_present:
        return "blocked"
    if top_level_status in {
        "review_required",
        "completed",
        "partial",
        "failed",
        "blocked",
        "cancelled",
    }:
        return top_level_status
    if material_attempt_state == "cancelled":
        return "cancelled"
    if material_attempt_state in {
        "closure_failed",
        "preflight_failed",
        "rollback_failed",
        "blocked",
    }:
        return "blocked"
    if material_attempt_state == "approval_pending":
        return "approval_pending"
    return "current"


def canonical_build_provenance_artifact_fingerprint(
    *,
    job_root: Path,
    build_provenance: ExactArtifact,
    expected_job_id: str,
) -> str:
    """Return the exact provenance-file digest after proving its payload is current."""

    validate_exact_artifact_current(
        job_root,
        build_provenance,
        role="build_provenance",
    )
    provenance_path = job_root.joinpath(*build_provenance.path.split("/"))
    try:
        stored = json.loads(provenance_path.read_text(encoding="utf-8"))
        current = collect_build_provenance(
            job_root,
            expected_job_id,
            validate_surface_details=False,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_CANONICAL_BUILD_PROVENANCE",
                    message=str(exc)[:1800],
                    path=build_provenance.path,
                )
            ]
        ) from exc
    if not isinstance(stored, dict) or stored != current:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="STALE_CANONICAL_BUILD_PROVENANCE",
                    message=(
                        "canonical build provenance payload differs from current "
                        "SceneSpec, ModelingPlan, material, or geometry inputs"
                    ),
                    path=build_provenance.path,
                )
            ]
        )
    return build_provenance.sha256


def build_material_canonical_snapshot(
    *,
    job_root: Path,
    snapshot_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    producer: str,
    producer_version: str,
    created_at: datetime,
    scene_spec: ExactArtifact,
    modeling_plan: ExactArtifact,
    blend: ExactArtifact,
    build_provenance: ExactArtifact,
    material_plan: ExactArtifact | None = None,
    material_plan_absence: ExactArtifact | None = None,
    latest_material_promotion_receipt: ExactArtifact | None = None,
    latest_rollback_receipt: ExactArtifact | None = None,
    active_candidate_closure: ExactArtifact | None = None,
) -> MaterialCanonicalSnapshot:
    """Observe exact host canonical bytes and strict MaterialPlan presence or absence."""

    expected_kinds = (
        (scene_spec, "scene_spec", "analysis/scene_spec.json"),
        (modeling_plan, "modeling_plan", "analysis/modeling_plan.json"),
        (blend, "canonical_blend", "blender/scene.blend"),
        (build_provenance, "build_provenance", None),
    )
    for artifact, kind, canonical_path in expected_kinds:
        if artifact.kind != kind:
            raise ValueError(f"canonical snapshot {kind} artifact uses the wrong kind")
        if canonical_path is not None and artifact.path != canonical_path:
            raise ValueError(f"canonical snapshot {kind} path is not canonical")
        validate_exact_artifact_current(job_root, artifact, role=kind)
    if (material_plan is None) == (material_plan_absence is None):
        raise ValueError("canonical snapshot requires MaterialPlan bytes or strict absence")
    if material_plan is not None:
        if (
            material_plan.kind != "material_plan"
            or material_plan.path != "analysis/material_plan.json"
        ):
            raise ValueError("canonical MaterialPlan artifact kind or path is invalid")
        validate_exact_artifact_current(
            job_root,
            material_plan,
            role="canonical_material_plan",
        )
    else:
        assert material_plan_absence is not None
        if material_plan_absence.kind != "material_plan_absence":
            raise ValueError("canonical snapshot requires strict MaterialPlan absence kind")
        validate_exact_artifact_current(
            job_root,
            material_plan_absence,
            role="material_plan_absence",
        )
        absence_path = job_root.joinpath(*material_plan_absence.path.split("/"))
        try:
            absence = MaterialCanonicalMaterialPlanAbsence.model_validate_json(
                absence_path.read_bytes()
            )
        except (OSError, ValidationError) as exc:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="INVALID_MATERIAL_PLAN_ABSENCE_EVIDENCE",
                        message=str(exc)[:1800],
                        path=material_plan_absence.path,
                    )
                ]
            ) from exc
        if (
            absence.job_id,
            absence.workflow_id,
            absence.dispatch_id,
            absence.session_id,
        ) != (job_id, workflow_id, dispatch_id, session_id):
            raise ValueError("canonical MaterialPlan absence belongs to another session")
        if absence.canonical_scene_spec != scene_spec or absence.canonical_blend != blend:
            raise ValueError("canonical MaterialPlan absence binds another scene or blend")
        validate_material_plan_absence_evidence(job_root, absence)
    for role, artifact in (
        ("latest_material_promotion_receipt", latest_material_promotion_receipt),
        ("latest_rollback_receipt", latest_rollback_receipt),
        ("active_candidate_closure", active_candidate_closure),
    ):
        if artifact is not None:
            validate_exact_artifact_current(job_root, artifact, role=role)
    build_fingerprint = canonical_build_provenance_artifact_fingerprint(
        job_root=job_root,
        build_provenance=build_provenance,
        expected_job_id=job_id,
    )
    return MaterialCanonicalSnapshot(
        snapshot_id=snapshot_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        producer=producer,
        producer_version=producer_version,
        created_at=created_at,
        scene_spec=scene_spec,
        modeling_plan=modeling_plan,
        material_plan=material_plan,
        material_plan_absence=material_plan_absence,
        blend=blend,
        build_provenance=build_provenance,
        build_provenance_fingerprint=build_fingerprint,
        latest_material_promotion_receipt=latest_material_promotion_receipt,
        latest_rollback_receipt=latest_rollback_receipt,
        active_candidate_closure=active_candidate_closure,
    )


def _artifact_identity(artifact: ExactArtifact | None) -> str | None:
    """Return a compact path/hash identity suitable for a consistency difference."""

    return None if artifact is None else f"{artifact.path}@{artifact.sha256}"


def _artifact_content_identity(artifact: ExactArtifact | None) -> str | None:
    """Compare versioned observations by immutable content rather than leaf path."""

    return None if artifact is None else f"{artifact.sha256}@{artifact.byte_size}"


def _material_absence_identity(artifact: ExactArtifact | None) -> str | None:
    """Represent a freshly validated absence record as the same canonical absent state."""

    return None if artifact is None else "absent"


def compare_canonical_snapshots(
    expected: MaterialCanonicalSnapshot,
    observed: MaterialCanonicalSnapshot,
) -> list[MaterialStateDifference]:
    """Compare all canonical identity fields while ignoring observation metadata."""

    comparisons: dict[str, tuple[str | None, str | None]] = {
        "scene_spec": (
            _artifact_identity(expected.scene_spec),
            _artifact_identity(observed.scene_spec),
        ),
        "modeling_plan": (
            _artifact_identity(expected.modeling_plan),
            _artifact_identity(observed.modeling_plan),
        ),
        "material_plan": (
            _artifact_identity(expected.material_plan),
            _artifact_identity(observed.material_plan),
        ),
        "material_plan_absence": (
            _material_absence_identity(expected.material_plan_absence),
            _material_absence_identity(observed.material_plan_absence),
        ),
        "blend": (_artifact_identity(expected.blend), _artifact_identity(observed.blend)),
        "build_provenance": (
            _artifact_content_identity(expected.build_provenance),
            _artifact_content_identity(observed.build_provenance),
        ),
        "latest_material_promotion_receipt": (
            _artifact_identity(expected.latest_material_promotion_receipt),
            _artifact_identity(observed.latest_material_promotion_receipt),
        ),
        "latest_rollback_receipt": (
            _artifact_identity(expected.latest_rollback_receipt),
            _artifact_identity(observed.latest_rollback_receipt),
        ),
        "active_candidate_closure": (
            _artifact_identity(expected.active_candidate_closure),
            _artifact_identity(observed.active_candidate_closure),
        ),
    }
    return [
        MaterialStateDifference(
            field=field,
            expected=expected_value,
            observed=observed_value,
            code="CANONICAL_SNAPSHOT_MISMATCH",
        )
        for field, (expected_value, observed_value) in comparisons.items()
        if expected_value != observed_value
    ]


def compare_material_state_to_canonical(
    *,
    report_id: str,
    attempt: MaterialAttemptState,
    attempt_artifact: ExactArtifact,
    top_level_state: ExactArtifact,
    expected_snapshot_artifact: ExactArtifact,
    observed_snapshot: MaterialCanonicalSnapshot,
    producer: str,
    producer_version: str,
    created_at: datetime,
) -> MaterialStateConsistencyReport:
    """Build a strict report from a material attempt and freshly observed canonical state."""

    differences = compare_canonical_snapshots(
        attempt.canonical_snapshot,
        observed_snapshot,
    )
    return MaterialStateConsistencyReport(
        report_id=report_id,
        job_id=attempt.job_id,
        workflow_id=attempt.workflow_id,
        dispatch_id=attempt.dispatch_id,
        session_id=attempt.session_id,
        producer=producer,
        producer_version=producer_version,
        created_at=created_at,
        attempt_state=attempt_artifact,
        top_level_state=top_level_state,
        expected_snapshot=expected_snapshot_artifact,
        observed_snapshot=observed_snapshot,
        consistent=not differences,
        differences=differences,
    )


def build_aq_v2_status_projection(
    *,
    projection_id: str,
    top_level_state: ExactArtifact,
    top_level_phase: str,
    top_level_status: str,
    top_level_next_action: str,
    canonical_snapshot: MaterialCanonicalSnapshot,
    consistency_report: ExactArtifact,
    state_consistent: bool,
    producer: str,
    producer_version: str,
    created_at: datetime,
    controller_invocation_count: int,
    canonical_promotion_count: int,
    rollback_count: int,
    blocked_retry: ExactArtifact | None = None,
    retry_supersession_receipt: ExactArtifact | None = None,
    attempt: MaterialAttemptState | None = None,
    attempt_artifact: ExactArtifact | None = None,
    blocking_companion_present: bool = False,
) -> AQV2StatusProjection:
    """Combine raw AQ state with companion state while preserving failure precedence."""

    if (attempt is None) != (attempt_artifact is None):
        raise ValueError("attempt value and artifact must be supplied together")
    combined_status = _derive_aq_v2_combined_status(
        top_level_status=top_level_status,
        state_consistent=state_consistent,
        material_attempt_state=None if attempt is None else attempt.state,
        blocking_companion_present=blocking_companion_present,
    )
    common = attempt or canonical_snapshot
    return AQV2StatusProjection(
        projection_id=projection_id,
        job_id=common.job_id,
        workflow_id=common.workflow_id,
        dispatch_id=common.dispatch_id,
        session_id=common.session_id,
        producer=producer,
        producer_version=producer_version,
        created_at=created_at,
        top_level_state=top_level_state,
        top_level_phase=top_level_phase,
        top_level_status=top_level_status,
        top_level_next_action=top_level_next_action,
        material_attempt=attempt_artifact,
        material_attempt_state=None if attempt is None else attempt.state,
        canonical_snapshot=canonical_snapshot,
        active_closure=None if attempt is None else attempt.active_closure,
        latest_preflight=None if attempt is None else attempt.latest_preflight,
        pending_approval=None if attempt is None else attempt.pending_approval,
        latest_controller_result=(
            None if attempt is None else attempt.latest_controller_result
        ),
        latest_promotion_receipt=(
            None if attempt is None else attempt.latest_promotion_receipt
        ),
        latest_rollback_receipt=(
            None if attempt is None else attempt.latest_rollback_receipt
        ),
        blocked_retry=blocked_retry,
        retry_supersession_receipt=retry_supersession_receipt,
        controller_invocation_count=controller_invocation_count,
        canonical_promotion_count=canonical_promotion_count,
        rollback_count=rollback_count,
        consistency_report=consistency_report,
        state_consistent=state_consistent,
        combined_status=combined_status,
    )


__all__ = [
    "build_aq_v2_status_projection",
    "build_material_canonical_snapshot",
    "canonical_build_provenance_artifact_fingerprint",
    "compare_canonical_snapshots",
    "compare_material_state_to_canonical",
]
