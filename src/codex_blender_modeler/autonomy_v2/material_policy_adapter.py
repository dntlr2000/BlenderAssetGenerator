"""Additive host adapter for non-user AQ material promotion policy authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ..blender_artifacts import native_io_path
from ..material_closure.models import (
    ExactArtifact,
    MaterialDependencyClosure,
    MaterialNeutralPreviewManifest,
    MaterialPromotionPreflightReport,
    MaterialPromotionPreflightRequest,
    MaterialStateConsistencyReport,
)
from ..production.validation import ensure_contained_production_path
from ..workspace import job_dir
from .approval_models import ApprovalArtifact, AQV2RoutinePolicyAuthorization
from .approval_policy_service import (
    _stable_id,
    validate_routine_policy_authorization,
)
from .controller_bridge import get_autonomy_v2_status
from .delivery_service import artifact_for_v2, validate_v2_artifact, write_immutable_v2_model
from .material_phase_models import MaterialClosurePolicyPromotionBoundaryV03
from .material_phase_service import validate_material_closure_promotion_boundary_v2
from .models import AQV2Artifact, AutonomyPlanV2

_PRODUCER = "codex_blender_modeler.autonomy_v2.material_policy_adapter"


def _read_exact_json(root: Path, artifact: AQV2Artifact, model: type[object]) -> object:
    """Rehash and strict-parse one supported material policy input artifact."""

    path = validate_v2_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return model.model_validate_json(handle.read())  # type: ignore[attr-defined,no-any-return]


def _aq_from_exact(root: Path, exact: ExactArtifact, *, kind: str) -> AQV2Artifact:
    """Rebind a generic closure artifact to the AQ exact-artifact shape."""

    return artifact_for_v2(
        root,
        root / exact.path,
        artifact_id=exact.artifact_id,
        kind=kind,
    )


def _aq_from_path(
    root: Path,
    path: str | Path,
    *,
    artifact_id: str,
    kind: str,
) -> AQV2Artifact:
    """Bind one caller-selected contained path to freshly observed AQ bytes."""

    candidate = Path(path) if Path(path).is_absolute() else root / path
    return artifact_for_v2(
        root,
        ensure_contained_production_path(root, candidate, must_exist=True),
        artifact_id=artifact_id,
        kind=kind,
    )


def publish_material_policy_promotion_boundary_v03(
    job_id: str,
    session_id: str,
    *,
    policy_authorization_path: str | Path,
    preflight_report_path: str | Path,
    state_consistency_report_path: str | Path,
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Publish one exact policy boundary from passed material closure evidence."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ material policy promotion remains disabled_experimental")
    root = ensure_contained_production_path(job_dir(job_id), job_dir(job_id), must_exist=True)
    status = get_autonomy_v2_status(job_id, session_id)
    plan_path = root / "production" / "autonomy_v2" / session_id / "plan.json"
    with open(native_io_path(plan_path), "rb") as handle:
        plan = AutonomyPlanV2.model_validate_json(handle.read())
    if plan.job_id != job_id or plan.session_id != session_id:
        raise PermissionError("material policy boundary resolved another AQ session")
    preflight_artifact = _aq_from_path(
        root,
        preflight_report_path,
        artifact_id=_stable_id("material-preflight", str(preflight_report_path)),
        kind="material-promotion-preflight-report",
    )
    authorization_result = validate_routine_policy_authorization(
        job_id,
        session_id,
        policy_authorization_path=policy_authorization_path,
        expected_gate_kind="material_candidate_promotion",
        expected_target_path=preflight_artifact.path,
    )
    authorization = AQV2RoutinePolicyAuthorization.model_validate_json(
        json.dumps(authorization_result["authorization"])
    )
    authorization_artifact = ApprovalArtifact.model_validate(
        authorization_result["authorization_artifact"]
    )
    preflight = _read_exact_json(
        root,
        preflight_artifact,
        MaterialPromotionPreflightReport,
    )
    if not isinstance(preflight, MaterialPromotionPreflightReport):
        raise TypeError("material preflight parser returned another contract")
    closure_artifact = _aq_from_exact(
        root,
        preflight.closure,
        kind="material-dependency-closure",
    )
    closure = _read_exact_json(root, closure_artifact, MaterialDependencyClosure)
    if not isinstance(closure, MaterialDependencyClosure):
        raise TypeError("material closure parser returned another contract")
    closure_receipt = _aq_from_exact(
        root,
        preflight.closure_receipt,
        kind="material-dependency-closure-receipt",
    )
    rebinding = _aq_from_exact(
        root,
        preflight.graph_rebinding_receipt,
        kind="material-graph-rebinding-receipt",
    )
    shadow = _aq_from_exact(
        root,
        preflight.shadow_compile_receipt,
        kind="material-shadow-compile-receipt",
    )
    preview_artifact = _aq_from_exact(
        root,
        preflight.neutral_preview_manifest,
        kind="material-neutral-preview-manifest",
    )
    preview = _read_exact_json(
        root,
        preview_artifact,
        MaterialNeutralPreviewManifest,
    )
    if not isinstance(preview, MaterialNeutralPreviewManifest):
        raise TypeError("material preview parser returned another contract")
    candidate = _aq_from_exact(
        root,
        preview.candidate_material_plan,
        kind="candidate-material-plan",
    )
    rebound = _aq_from_exact(
        root,
        preview.rebound_material_graph,
        kind="rebound-material-graph",
    )
    consistency_artifact = _aq_from_path(
        root,
        state_consistency_report_path,
        artifact_id=_stable_id("material-consistency", str(state_consistency_report_path)),
        kind="material-state-consistency-report",
    )
    consistency = _read_exact_json(
        root,
        consistency_artifact,
        MaterialStateConsistencyReport,
    )
    if not isinstance(consistency, MaterialStateConsistencyReport):
        raise TypeError("material consistency parser returned another contract")
    request_artifact = _aq_from_exact(
        root,
        preflight.request,
        kind="material-promotion-preflight-request",
    )
    request = _read_exact_json(
        root,
        request_artifact,
        MaterialPromotionPreflightRequest,
    )
    if not isinstance(request, MaterialPromotionPreflightRequest):
        raise TypeError("material preflight request parser returned another contract")
    state_artifact = AQV2Artifact.model_validate(status["state_artifact"])
    policy_as_aq = AQV2Artifact.model_validate(
        authorization_artifact.model_dump(mode="python")
    )
    named = [
        state_artifact,
        closure_artifact,
        closure_receipt,
        rebinding,
        preflight_artifact,
        shadow,
        preview_artifact,
        policy_as_aq,
        consistency_artifact,
        candidate,
        rebound,
    ]
    boundary_id = _stable_id(
        "material-policy-boundary",
        {
            "authorization": authorization_artifact.sha256,
            "preflight": preflight_artifact.sha256,
            "state": state_artifact.sha256,
            "consistency": consistency_artifact.sha256,
        },
    )
    boundary = MaterialClosurePolicyPromotionBoundaryV03(
        contract_id=boundary_id,
        boundary_id=boundary_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=authorization.root_authorization,
        producer=_PRODUCER,
        created_at=created_at or datetime.now(UTC),
        approval_count_effect="reduces",
        approval_count_justification=(
            "Passed closure evidence uses one exact host policy authorization without "
            "creating or reclassifying user approval."
        ),
        policy_profile=authorization.policy_profile,
        approval_envelope=authorization.approval_envelope,
        approval_budget=authorization.approval_budget,
        policy_authorization=authorization_artifact,
        current_state=state_artifact,
        dependency_closure=closure_artifact,
        dependency_closure_receipt=closure_receipt,
        graph_rebinding_receipt=rebinding,
        preflight_report=preflight_artifact,
        shadow_compile_receipt=shadow,
        neutral_preview_manifest=preview_artifact,
        state_consistency_report=consistency_artifact,
        candidate_material_plan=candidate,
        rebound_material_graph=rebound,
        provenance=named,
        immutable_input_sha256=closure.project_immutable_input_map(),
        planned_output_sha256=closure.project_planned_output_map(),
        canonical_scene_spec_sha256=consistency.observed_snapshot.scene_spec.sha256,
        canonical_blend_sha256=consistency.observed_snapshot.blend.sha256,
        uv_layout_fingerprint=request.uv_layout_fingerprint,
    )
    path = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "material_closure"
        / "policy_boundaries"
        / f"{authorization.authorization_id}.json"
    )
    boundary_artifact = write_immutable_v2_model(root, path, boundary).model_copy(
        update={
            "artifact_id": boundary.boundary_id,
            "kind": "material-policy-promotion-boundary",
        }
    )
    validated, _closure = validate_material_closure_promotion_boundary_v2(
        root,
        plan,
        boundary_artifact,
        require_current_canonical=True,
    )
    if validated != boundary:
        raise RuntimeError("published material policy boundary replay differs")
    return {
        "status": "published",
        "boundary": boundary.model_dump(mode="json"),
        "boundary_artifact": boundary_artifact.model_dump(mode="json"),
        "policy_authorization": authorization.model_dump(mode="json"),
        "is_user_approval": False,
        "user_approval_created": False,
    }
