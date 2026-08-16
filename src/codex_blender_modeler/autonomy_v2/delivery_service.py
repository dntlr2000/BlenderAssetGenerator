"""Host-owned AQ v2 quality-freeze delivery planning and terminal validation."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ..blender_artifacts import (
    native_io_path,
    native_json_bytes,
    publish_bytes_create_once,
    sha256_file,
    stable_json_digest,
)
from ..integrated_quality.v02_contour_metrics import compare_contours_v02
from ..integrated_quality.v02_models import (
    ContourEvidenceBindingV02,
    IntegratedQualityPolicyV02,
    IntegratedQualityReportV02,
)
from ..integrated_quality.v02_semantic_metrics import compare_semantic_masks_v02
from ..integrated_quality.v02_service import build_integrated_quality_report_v02
from ..optimization import initialize_asset_profile, plan_asset_optimization
from ..optimization.models import (
    OptimizationApproval,
    OptimizationPlan,
    OptimizationReview,
    PortableMaterialConversionManifest,
    SourceProvenance,
)
from ..optimization.provenance import collect_source_provenance
from ..packaging.models import ExportPackageManifest, RoundTripValidation
from ..production.validation import ensure_contained_production_path
from ..structural_geometry.geometry_survival_v02 import (
    GeometryIntentSurvivalReportV02,
    GeometryStageSnapshotV02,
    compare_geometry_stage_snapshots_v02,
)
from .candidate_validation_models import GeometryCandidateValidationReceiptV2
from .material_phase_models import MaterialPhaseReceiptV2
from .models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyProfileV2,
    DeliveryPlan,
    DeliveryRequest,
    DeliveryResult,
    DeliveryReviewBinding,
    DeliveryReviewEntry,
    DeliveryTerminalV2,
    QualityApprovedSourceFreeze,
    RootAuthorizationV2,
)
from .profiles import PROFILE_STATUS, delivery_profile

ModelT = TypeVar("ModelT", bound=BaseModel)

_PRODUCER = "codex_blender_modeler.autonomy_v2.delivery_service"


def artifact_for_v2(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
) -> AQV2Artifact:
    """Bind one contained non-empty regular file to exact AQ v2 evidence."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    if not os.path.isfile(native_io_path(safe)):
        raise ValueError(f"AQ v2 artifact must be a regular file: {safe.name}")
    size = os.path.getsize(native_io_path(safe))
    if size <= 0:
        raise ValueError(f"AQ v2 artifact must be non-empty: {safe.name}")
    return AQV2Artifact(
        artifact_id=artifact_id,
        kind=kind,
        path=safe.relative_to(root).as_posix(),
        sha256=sha256_file(safe),
        byte_size=size,
    )


def validate_v2_artifact(root: Path, artifact: AQV2Artifact) -> Path:
    """Reject a missing, linked, resized, or rehashed AQ v2 artifact."""

    path = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
    if not os.path.isfile(native_io_path(path)):
        raise ValueError(f"AQ v2 artifact is not a regular file: {artifact.path}")
    if os.path.getsize(native_io_path(path)) != artifact.byte_size:
        raise ValueError(f"AQ v2 artifact size changed: {artifact.path}")
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"AQ v2 artifact hash changed: {artifact.path}")
    return path


def _load_model(root: Path, artifact: AQV2Artifact, model: type[ModelT]) -> ModelT:
    """Rehash and strict-parse one exact AQ v2 model artifact."""

    path = validate_v2_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return model.model_validate_json(handle.read())


def _load_current_plan_v2(
    root: Path,
    session_id: str,
) -> tuple[AutonomyPlanV2, AQV2Artifact]:
    """Load and bind the one canonical immutable AQ v2 plan for a session."""

    path = ensure_contained_production_path(
        root,
        root / "production" / "autonomy_v2" / session_id / "plan.json",
        must_exist=True,
    )
    with open(native_io_path(path), "rb") as handle:
        plan = AutonomyPlanV2.model_validate_json(handle.read())
    artifact = artifact_for_v2(
        root,
        path,
        artifact_id=plan.contract_id,
        kind="plan",
    )
    return plan, artifact


def validate_root_authorization_boundary_v2(
    *,
    job_root: Path,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    root_authorization_artifact: AQV2Artifact | None = None,
    now: datetime | None = None,
) -> tuple[RootAuthorizationV2, AutonomyPlanV2, AutonomyProfileV2, AutonomyBudgetV2]:
    """Rebuild the exact active plan/profile/budget authorization boundary from disk."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    plan, plan_artifact = _load_current_plan_v2(root, session_id)
    authorization_artifact = root_authorization_artifact or plan.root_authorization
    authorization = _load_model(root, authorization_artifact, RootAuthorizationV2)
    profile = _load_model(root, authorization.profile, AutonomyProfileV2)
    budget = _load_model(root, authorization.budget, AutonomyBudgetV2)
    identity = (job_id, workflow_id, dispatch_id, session_id)
    for label, evidence in (
        ("plan", plan),
        ("root authorization", authorization),
        ("profile", profile),
        ("budget", budget),
    ):
        if (
            evidence.job_id,
            evidence.workflow_id,
            evidence.dispatch_id,
            evidence.session_id,
        ) != identity:
            raise ValueError(f"AQ v2 {label} identity differs from the delivery boundary")
    if (
        root_authorization_artifact is not None
        and plan.root_authorization != root_authorization_artifact
    ):
        raise ValueError("AQ v2 root authorization is not the exact immutable plan binding")
    expected_session_root = f"production/autonomy_v2/{session_id}"
    expected_paths = {
        "plan": f"{expected_session_root}/plan.json",
        "authorization": f"{expected_session_root}/root_authorization.json",
        "profile": f"{expected_session_root}/profile.json",
        "budget": f"{expected_session_root}/budget.json",
    }
    if (
        plan_artifact.path != expected_paths["plan"]
        or authorization_artifact.path != expected_paths["authorization"]
        or authorization.profile.path != expected_paths["profile"]
        or authorization.budget.path != expected_paths["budget"]
    ):
        raise ValueError("AQ v2 authorization artifacts are outside their canonical session paths")
    if (
        plan.producer != "codex_blender_modeler.autonomy_v2.planner"
        or authorization.producer != "codex_blender_modeler.autonomy_v2.planner"
        or profile.producer != "codex_blender_modeler.autonomy_v2.planner"
        or budget.producer != "codex_blender_modeler.autonomy_v2.planner"
    ):
        raise ValueError("AQ v2 authorization boundary was not published by the host planner")
    if authorization.status != "active":
        raise PermissionError("AQ v2 root authorization is not active")
    current = now or datetime.now(UTC)
    if authorization.expires_at is not None:
        if authorization.expires_at.tzinfo is None:
            raise ValueError("AQ v2 root authorization expiry must be timezone-aware")
        if authorization.expires_at <= current:
            raise PermissionError("AQ v2 root authorization has expired")
    if (
        plan.profile != authorization.profile
        or plan.budget != authorization.budget
        or plan.root_authorization != authorization_artifact
        or plan.phase_tool_profiles != authorization.phase_tool_profiles
        or plan.requested_delivery_profiles != authorization.requested_delivery_profiles
        or plan.action_limit != budget.global_action_limit
        or profile.profile_id != "autonomous_static_prop_v2"
        or not set(authorization.allowed_delivery_profiles).issubset(
            profile.allowed_delivery_profiles
        )
        or budget.delivery_runs
        < sum(
            item != "review_only"
            for item in authorization.requested_delivery_profiles
        )
    ):
        raise ValueError("AQ v2 plan, profile, budget, and authorization bindings differ")
    authorization_named = [
        authorization.primary_reference,
        authorization.profile,
        authorization.budget,
        authorization.production_launch_or_binding,
        authorization.quality_profile,
        *authorization.phase_tool_profiles,
    ]
    if any(item not in authorization.provenance for item in authorization_named):
        raise ValueError("AQ v2 root authorization omits named immutable provenance")
    plan_named = [
        plan.profile,
        plan.root_authorization,
        plan.budget,
        plan.production_dispatch_plan,
        plan.production_controller_plan,
        *plan.phase_tool_profiles,
    ]
    if any(item not in plan.provenance for item in plan_named):
        raise ValueError("AQ v2 plan omits named immutable provenance")
    for artifact in [*authorization_named, *plan_named]:
        validate_v2_artifact(root, artifact)

    budget_input = {
        "dispatch_plan": plan.production_dispatch_plan.sha256,
        "quality_policy": authorization.quality_profile.sha256,
        "phase_profiles": [item.sha256 for item in authorization.phase_tool_profiles],
    }
    profile_input = {
        "budget": authorization.budget.sha256,
        "quality_policy": authorization.quality_profile.sha256,
        "phase_profiles": [item.sha256 for item in authorization.phase_tool_profiles],
    }
    authorization_inputs = {
        "request": authorization.original_request_sha256,
        "primary_reference": authorization.primary_reference.sha256,
        "profile": authorization.profile.sha256,
        "budget": authorization.budget.sha256,
        "launch": authorization.production_launch_or_binding.sha256,
        "quality_policy": authorization.quality_profile.sha256,
        "phase_profiles": [item.sha256 for item in authorization.phase_tool_profiles],
        "requested_deliveries": authorization.requested_delivery_profiles,
        "target_subject": authorization.target_subject,
    }
    plan_inputs = {
        "profile": plan.profile.sha256,
        "authorization": plan.root_authorization.sha256,
        "budget": plan.budget.sha256,
        "dispatch": plan.production_dispatch_plan.sha256,
        "controller": plan.production_controller_plan.sha256,
        "phase_profiles": [item.sha256 for item in plan.phase_tool_profiles],
    }
    if (
        budget.input_sha256 != stable_json_digest(budget_input)
        or budget.source_fingerprint
        != stable_json_digest({**budget_input, "profile": "autonomous_static_prop_v2"})
        or profile.input_sha256 != stable_json_digest(profile_input)
        or profile.source_fingerprint
        != stable_json_digest({**profile_input, "status": profile.status})
        or authorization.input_sha256 != stable_json_digest(authorization_inputs)
        or authorization.source_fingerprint
        != stable_json_digest(
            {**authorization_inputs, "destination_hint": authorization.destination_hint}
        )
        or plan.input_sha256 != stable_json_digest(plan_inputs)
        or plan.source_fingerprint
        != stable_json_digest(
            {
                **plan_inputs,
                "requested_deliveries": plan.requested_delivery_profiles,
            }
        )
    ):
        raise ValueError("AQ v2 authorization boundary digest is inconsistent")
    return authorization, plan, profile, budget


def write_immutable_v2_model(root: Path, path: Path, model: BaseModel) -> AQV2Artifact:
    """Create or exact-adopt deterministic AQ v2 bytes without replacing history."""

    destination = ensure_contained_production_path(root, path, must_exist=False)
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    ensure_contained_production_path(root, destination.parent, must_exist=True)
    publish_bytes_create_once(
        destination,
        native_json_bytes(model.model_dump(mode="json")),
    )
    return artifact_for_v2(
        root,
        destination,
        artifact_id=str(getattr(model, "contract_id", destination.stem)),
        kind=destination.stem.replace("_", "-"),
    )


def _artifact_binding_payload(artifact: AQV2Artifact) -> dict[str, object]:
    """Return the complete deterministic identity of one exact AQ v2 artifact."""

    return artifact.model_dump(mode="json")


def _ordered_artifact_payloads(
    artifacts: list[AQV2Artifact],
) -> list[dict[str, object]]:
    """Canonicalize an unordered artifact role without weakening each exact binding."""

    return [
        _artifact_binding_payload(item)
        for item in sorted(
            artifacts,
            key=lambda item: (item.path, item.sha256, item.artifact_id, item.kind),
        )
    ]


def _unique_quality_artifact(
    artifacts: list[AQV2Artifact],
    *,
    sha256: str,
    label: str,
    path: str | None = None,
    kind: str | None = None,
) -> AQV2Artifact:
    """Resolve one exact submitted quality artifact without hash-only ambiguity."""

    matches = [
        item
        for item in artifacts
        if item.sha256 == sha256
        and (path is None or item.path == path)
        and (kind is None or item.kind == kind)
    ]
    if len(matches) != 1:
        raise ValueError(f"IQ 0.2 {label} evidence is missing or ambiguous")
    return matches[0]


def _top_level_contour_origin(report: IntegratedQualityReportV02) -> str:
    """Map the report's constrained authority to a non-escalating contour origin."""

    return {
        "authoritative": "observed",
        "advisory": "generated",
        "unavailable": "unavailable",
    }[report.contour.authority]


def validate_host_recomputed_quality_report_v2(
    *,
    job_root: Path,
    report: IntegratedQualityReportV02,
    quality_evidence: list[AQV2Artifact],
    camera_artifact: AQV2Artifact,
    expected_policy: IntegratedQualityPolicyV02,
) -> IntegratedQualityReportV02:
    """Recompute mask metrics and every derived IQ decision from exact submitted bytes."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    if report.policy != expected_policy:
        raise ValueError("IQ 0.2 report policy differs from the exact root authorization")
    if camera_artifact.kind != "camera" or camera_artifact.sha256 != report.camera_sha256:
        raise ValueError("IQ 0.2 report camera differs from the exact camera artifact")
    for artifact in quality_evidence:
        validate_v2_artifact(root, artifact)
    if sum(item == camera_artifact for item in quality_evidence) != 1:
        raise ValueError("IQ 0.2 fixed camera evidence is missing or ambiguous")
    if len(report.contour.evidence_ids) != 2:
        raise ValueError("IQ 0.2 contour requires exact reference and candidate evidence IDs")

    candidate = _unique_quality_artifact(
        quality_evidence,
        sha256=report.contour.candidate_mask_sha256,
        label="global candidate mask",
        kind="candidate_mask",
    )
    candidate_path = validate_v2_artifact(root, candidate)
    reference_path = candidate_path
    reference_artifact: AQV2Artifact | None = None
    if report.contour.reference_mask_sha256 is not None:
        reference_artifact = _unique_quality_artifact(
            quality_evidence,
            sha256=report.contour.reference_mask_sha256,
            label="global reference mask",
            kind="reference_mask",
        )
        reference_path = validate_v2_artifact(root, reference_artifact)
    contour_binding = ContourEvidenceBindingV02(
        evidence_id=report.contour.evidence_ids[0],
        origin=_top_level_contour_origin(report),  # type: ignore[arg-type]
        authority=report.contour.authority,
        artifact_path=(reference_artifact.path if reference_artifact is not None else None),
        artifact_sha256=(
            reference_artifact.sha256 if reference_artifact is not None else None
        ),
        camera_sha256=camera_artifact.sha256,
    )
    recomputed_contour = compare_contours_v02(
        reference_path,
        candidate_path,
        reference_evidence=contour_binding,
        candidate_evidence_id=report.contour.evidence_ids[1],
        candidate_artifact_sha256=candidate.sha256,
        candidate_camera_sha256=camera_artifact.sha256,
    )

    recomputed_semantics = []
    for semantic in report.semantics:
        binding = semantic.reference_evidence
        if binding.artifact_path is None or binding.artifact_sha256 is None:
            reference_semantic_path = candidate_path
        else:
            reference_semantic = _unique_quality_artifact(
                quality_evidence,
                sha256=binding.artifact_sha256,
                path=binding.artifact_path,
                label=f"semantic {semantic.semantic_id} reference mask",
                kind="reference_mask",
            )
            reference_semantic_path = validate_v2_artifact(root, reference_semantic)
        if binding.registration_receipt_sha256 is not None:
            _unique_quality_artifact(
                quality_evidence,
                sha256=binding.registration_receipt_sha256,
                label=f"semantic {semantic.semantic_id} registration receipt",
                kind="registration_receipt",
            )
        semantic_candidate = _unique_quality_artifact(
            quality_evidence,
            sha256=semantic.contour.candidate_mask_sha256,
            label=f"semantic {semantic.semantic_id} candidate mask",
            kind="candidate_mask",
        )
        recomputed_semantics.append(
            compare_semantic_masks_v02(
                reference_semantic_path,
                validate_v2_artifact(root, semantic_candidate),
                reference_evidence=binding,
                candidate_evidence_id=semantic.candidate_evidence_id,
                candidate_artifact_sha256=semantic_candidate.sha256,
                candidate_camera_sha256=camera_artifact.sha256,
                critical=semantic.critical,
            )
        )

    required_landmarks = set(report.policy.required_landmark_ids)
    if any(
        item.landmark_id in required_landmarks
        and item.authority == "authoritative"
        and item.status == "scored"
        for item in report.landmarks
    ):
        raise ValueError(
            "required landmark pass authority needs a host-verifiable typed input receipt"
        )
    if report.policy.require_multiview and report.multiview.status == "scored":
        raise ValueError(
            "required multiview pass authority needs a host-verifiable typed input receipt"
        )

    base = build_integrated_quality_report_v02(
        report_id=report.report_id,
        job_id=report.job_id,
        workflow_id=report.workflow_id,
        dispatch_id=report.dispatch_id,
        source_fingerprint=report.source_fingerprint,
        camera_sha256=report.camera_sha256,
        input_sha256=report.input_sha256,
        policy=expected_policy,
        contour=recomputed_contour,
        semantics=recomputed_semantics,
        landmarks=report.landmarks,
        multiview=report.multiview,
        advisory_metrics=report.advisory_metrics,
        producer=report.producer,
        created_at=report.created_at,
        legacy_v06_report_sha256=report.legacy_v06_report_sha256,
        legacy_v06_direct_score=report.legacy_v06_direct_score,
    )
    base_finding_ids = {item.finding_id for item in base.findings}
    additional_findings = [
        item for item in report.findings if item.finding_id not in base_finding_ids
    ]
    recomputed = build_integrated_quality_report_v02(
        report_id=report.report_id,
        job_id=report.job_id,
        workflow_id=report.workflow_id,
        dispatch_id=report.dispatch_id,
        source_fingerprint=report.source_fingerprint,
        camera_sha256=report.camera_sha256,
        input_sha256=report.input_sha256,
        policy=expected_policy,
        contour=recomputed_contour,
        semantics=recomputed_semantics,
        landmarks=report.landmarks,
        multiview=report.multiview,
        advisory_metrics=report.advisory_metrics,
        producer=report.producer,
        created_at=report.created_at,
        legacy_v06_report_sha256=report.legacy_v06_report_sha256,
        legacy_v06_direct_score=report.legacy_v06_direct_score,
        additional_findings=additional_findings,
    )
    if recomputed != report:
        raise ValueError(
            "IQ 0.2 report differs from host-recomputed masks, gates, findings, or outcome"
        )
    return recomputed


def _quality_source_payload(
    root: Path,
    job_id: str,
) -> tuple[SourceProvenance, dict[str, object]]:
    """Rehash the current SceneSpec source plus its otherwise-optional ModelingPlan."""

    source = collect_source_provenance(root, job_id)
    if source.source_kind != "scene_spec" or source.scene_spec is None:
        raise ValueError("AQ v2 quality requires the canonical SceneSpec source kind")
    if source.material_plan is None:
        raise ValueError("AQ v2 quality requires canonical material provenance")
    modeling_plan = artifact_for_v2(
        root,
        root / "analysis" / "modeling_plan.json",
        artifact_id="quality-source-modeling-plan",
        kind="modeling_plan",
    )
    payload: dict[str, object] = {
        "v07_source_fingerprint": source.source_fingerprint,
        "build_fingerprint": source.build_fingerprint,
        "modeling_plan": {
            "path": modeling_plan.path,
            "sha256": modeling_plan.sha256,
            "byte_size": modeling_plan.byte_size,
        },
        "scene_spec": {
            "path": source.scene_spec.path,
            "sha256": source.scene_spec.sha256,
        },
        "authoring_blend": {
            "path": source.blend.path,
            "sha256": source.blend.sha256,
        },
        "material_plan": {
            "path": source.material_plan.path,
            "sha256": source.material_plan.sha256,
        },
        "geometry_payloads": sorted((item.path, item.sha256) for item in source.geometry_payloads),
        "texture_manifests": sorted((item.path, item.sha256) for item in source.texture_manifests),
    }
    return source, payload


def quality_source_fingerprint_v2(job_root: Path, job_id: str) -> str:
    """Compute the AQ v2 IQ fingerprint from the current canonical authoring source."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    _source, payload = _quality_source_payload(root, job_id)
    return stable_json_digest(payload)


def quality_submission_input_sha256_v2(
    *,
    source_fingerprint: str,
    camera_artifact: AQV2Artifact,
    quality_evidence: list[AQV2Artifact],
    scene_spec: AQV2Artifact | None = None,
    authoring_blend: AQV2Artifact | None = None,
    build_provenance: AQV2Artifact | None = None,
    material_plan: AQV2Artifact | None = None,
    shader_recipes: list[AQV2Artifact] | None = None,
    texture_manifests: list[AQV2Artifact] | None = None,
    geometry_payloads: list[AQV2Artifact] | None = None,
    geometry_intent_survival: AQV2Artifact | None = None,
    geometry_candidate_validation_receipt: AQV2Artifact | None = None,
    material_phase_receipt: AQV2Artifact | None = None,
) -> str:
    """Hash the exact canonical, QA, camera, and promotion inputs consumed by IQ 0.2."""

    payload = {
        "quality_source_fingerprint": source_fingerprint,
        "camera_artifact": _artifact_binding_payload(camera_artifact),
        "quality_evidence": _ordered_artifact_payloads(quality_evidence),
        "canonical_source": {
            "scene_spec": (
                _artifact_binding_payload(scene_spec) if scene_spec is not None else None
            ),
            "authoring_blend": (
                _artifact_binding_payload(authoring_blend) if authoring_blend is not None else None
            ),
            "build_provenance": (
                _artifact_binding_payload(build_provenance)
                if build_provenance is not None
                else None
            ),
            "material_plan": (
                _artifact_binding_payload(material_plan) if material_plan is not None else None
            ),
            "shader_recipes": _ordered_artifact_payloads(shader_recipes or []),
            "texture_manifests": _ordered_artifact_payloads(texture_manifests or []),
            "geometry_payloads": _ordered_artifact_payloads(geometry_payloads or []),
        },
        "promotion_evidence": {
            "geometry_intent_survival": (
                _artifact_binding_payload(geometry_intent_survival)
                if geometry_intent_survival is not None
                else None
            ),
            "geometry_candidate_validation_receipt": (
                _artifact_binding_payload(geometry_candidate_validation_receipt)
                if geometry_candidate_validation_receipt is not None
                else None
            ),
            "material_phase_receipt": (
                _artifact_binding_payload(material_phase_receipt)
                if material_phase_receipt is not None
                else None
            ),
        },
    }
    return stable_json_digest(payload)


def _load_build_snapshot(root: Path, artifact: AQV2Artifact) -> dict[str, object]:
    """Rehash and verify the self-digest of one material-phase build snapshot."""

    path = validate_v2_artifact(root, artifact)
    try:
        value = json.loads(Path(native_io_path(path)).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("AQ v2 build provenance snapshot is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("AQ v2 build provenance snapshot must be an object")
    fingerprint = value.get("fingerprint")
    unsigned = dict(value)
    unsigned.pop("fingerprint", None)
    if not isinstance(fingerprint, str) or stable_json_digest(unsigned) != fingerprint:
        raise ValueError("AQ v2 build provenance snapshot self-digest is inconsistent")
    return value


def _build_shader_bindings(build: dict[str, object]) -> set[tuple[str, str]]:
    """Extract the exact shader-recipe set declared by a verified build snapshot."""

    materials = build.get("materials")
    if not isinstance(materials, dict):
        raise ValueError("AQ v2 build provenance omits its material records")
    bindings: set[tuple[str, str]] = set()
    for value in materials.values():
        if not isinstance(value, dict):
            raise ValueError("AQ v2 build material provenance is malformed")
        path = value.get("shader_recipe_path")
        digest = value.get("shader_recipe_sha256")
        if (path is None) != (digest is None):
            raise ValueError("AQ v2 shader recipe provenance is partial")
        if path is not None:
            if not isinstance(path, str) or not isinstance(digest, str):
                raise ValueError("AQ v2 shader recipe provenance is malformed")
            bindings.add((path, digest))
    return bindings


def validate_quality_source_inputs_v2(
    *,
    job_root: Path,
    job_id: str,
    scene_spec: AQV2Artifact,
    authoring_blend: AQV2Artifact,
    build_provenance: AQV2Artifact,
    material_plan: AQV2Artifact,
    shader_recipes: list[AQV2Artifact],
    texture_manifests: list[AQV2Artifact],
    geometry_payloads: list[AQV2Artifact],
) -> str:
    """Cross-bind submitted freeze artifacts to freshly collected canonical provenance."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    source, source_payload = _quality_source_payload(root, job_id)
    for artifact in [
        scene_spec,
        authoring_blend,
        build_provenance,
        material_plan,
        *shader_recipes,
        *texture_manifests,
        *geometry_payloads,
    ]:
        validate_v2_artifact(root, artifact)
    assert source.scene_spec is not None
    assert source.material_plan is not None
    expected_sources = {
        "scene": (source.scene_spec.path, source.scene_spec.sha256),
        "blend": (source.blend.path, source.blend.sha256),
        "material": (source.material_plan.path, source.material_plan.sha256),
    }
    supplied_sources = {
        "scene": (scene_spec.path, scene_spec.sha256),
        "blend": (authoring_blend.path, authoring_blend.sha256),
        "material": (material_plan.path, material_plan.sha256),
    }
    if supplied_sources != expected_sources:
        raise ValueError("AQ v2 freeze artifacts do not match current canonical provenance")
    expected_geometry = {(item.path, item.sha256) for item in source.geometry_payloads}
    expected_textures = {(item.path, item.sha256) for item in source.texture_manifests}
    if {(item.path, item.sha256) for item in geometry_payloads} != expected_geometry:
        raise ValueError("AQ v2 geometry payload set does not match canonical provenance")
    if {(item.path, item.sha256) for item in texture_manifests} != expected_textures:
        raise ValueError("AQ v2 texture manifest set does not match canonical provenance")
    build = _load_build_snapshot(root, build_provenance)
    if build.get("fingerprint") != source.build_fingerprint:
        raise ValueError("AQ v2 build snapshot differs from current canonical provenance")
    supplied_shaders = {(item.path, item.sha256) for item in shader_recipes}
    if supplied_shaders != _build_shader_bindings(build):
        raise ValueError("AQ v2 shader recipe set does not match build provenance")
    return stable_json_digest(source_payload)


def validate_quality_promotion_evidence_v2(
    *,
    job_root: Path,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    geometry_candidate_validation_receipt: AQV2Artifact,
    material_phase_receipt: AQV2Artifact,
    geometry_intent_survival: AQV2Artifact,
    scene_spec: AQV2Artifact,
    authoring_blend: AQV2Artifact,
    build_provenance: AQV2Artifact,
    material_plan: AQV2Artifact,
) -> tuple[GeometryCandidateValidationReceiptV2, MaterialPhaseReceiptV2]:
    """Revalidate accepted geometry and material promotions against the current source."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    if geometry_candidate_validation_receipt.kind != "geometry_candidate_validation_receipt":
        raise ValueError("AQ v2 quality requires the exact geometry validation receipt")
    if material_phase_receipt.kind != "material_phase_receipt":
        raise ValueError("AQ v2 quality requires the exact material phase receipt")
    geometry = _load_model(
        root,
        geometry_candidate_validation_receipt,
        GeometryCandidateValidationReceiptV2,
    )
    identity = (job_id, workflow_id, dispatch_id, session_id)
    if (
        geometry.job_id,
        geometry.workflow_id,
        geometry.dispatch_id,
        geometry.session_id,
    ) != identity:
        raise ValueError("AQ v2 promotion evidence belongs to another session")
    if geometry.geometry_intent_survival != geometry_intent_survival:
        raise ValueError("submitted geometry survival is not the accepted promotion evidence")
    _authorization, plan, _profile, _budget = validate_root_authorization_boundary_v2(
        job_root=root,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
    )
    if geometry.root_authorization != plan.root_authorization:
        raise ValueError("accepted geometry promotion uses a different root authorization")

    from .material_phase_service import validate_material_phase_receipt_v2

    material = validate_material_phase_receipt_v2(
        root,
        material_phase_receipt,
        require_current=True,
    )
    if (
        material.job_id,
        material.workflow_id,
        material.dispatch_id,
        material.session_id,
    ) != identity:
        raise ValueError("AQ v2 promotion evidence belongs to another session")
    if (
        geometry_candidate_validation_receipt.artifact_id != geometry.contract_id
        or geometry.contract_id != f"geometry-validation-{session_id}"
        or geometry.receipt_id != geometry.contract_id
        or geometry.producer != "codex_blender_modeler.autonomy_v2.candidate_validation_service"
        or not geometry_candidate_validation_receipt.path.startswith("aq2/")
        or not geometry_candidate_validation_receipt.path.endswith("/receipt.json")
    ):
        raise ValueError("AQ v2 geometry promotion receipt is not host-published evidence")
    expected_material_path = f"production/autonomy_v2/{session_id}/material_phase/"
    if (
        material_phase_receipt.artifact_id != material.contract_id
        or material.receipt_id != material.contract_id
        or material.producer != "codex_blender_modeler.autonomy_v2.material_phase_service"
        or not material_phase_receipt.path.startswith(expected_material_path)
        or not material_phase_receipt.path.endswith("/promotion_receipt.json")
    ):
        raise ValueError("AQ v2 material promotion receipt is not host-published evidence")

    # Material authoring legitimately supersedes only the old canonical blend bytes.
    for artifact in geometry.provenance:
        if artifact == geometry.canonical_blend:
            continue
        validate_v2_artifact(root, artifact)
    for artifact in material.provenance:
        validate_v2_artifact(root, artifact)
    source_snapshot = _load_model(
        root,
        geometry.candidate_geometry_snapshot,
        GeometryStageSnapshotV02,
    )
    target_snapshot = _load_model(
        root,
        geometry.canonical_geometry_snapshot,
        GeometryStageSnapshotV02,
    )
    survival = _load_model(
        root,
        geometry.geometry_intent_survival,
        GeometryIntentSurvivalReportV02,
    )
    recomputed = compare_geometry_stage_snapshots_v02(
        report_id=survival.report_id,
        relation="candidate_to_canonical",
        source=source_snapshot,
        target=target_snapshot,
    )
    if survival != recomputed or survival.overall_status != "exact":
        raise ValueError("accepted candidate-to-canonical geometry survival is stale")
    current_modeling_plan = artifact_for_v2(
        root,
        root / "analysis" / "modeling_plan.json",
        artifact_id=geometry.canonical_modeling_plan.artifact_id,
        kind=geometry.canonical_modeling_plan.kind,
    )
    if (
        current_modeling_plan != geometry.canonical_modeling_plan
        or scene_spec != geometry.canonical_scene_spec
        or material.canonical_scene_spec_sha256 != scene_spec.sha256
        or material.canonical_material_plan_sha256 != material_plan.sha256
        or material.authoring_blend_snapshot.sha256 != authoring_blend.sha256
        or material.build_provenance_snapshot != build_provenance
    ):
        raise ValueError("AQ v2 promotion evidence differs from the current canonical source")
    build = _load_build_snapshot(root, build_provenance)
    if build.get("fingerprint") != material.build_fingerprint:
        raise ValueError("material promotion build provenance is stale")
    return geometry, material


def validate_quality_source_freeze(
    root: Path,
    freeze: QualityApprovedSourceFreeze,
) -> None:
    """Revalidate authorization, promotions, canonical inputs, and host-recomputed IQ."""

    authorization, _plan, _profile, _budget = validate_root_authorization_boundary_v2(
        job_root=root,
        job_id=freeze.job_id,
        workflow_id=freeze.workflow_id,
        dispatch_id=freeze.dispatch_id,
        session_id=freeze.session_id,
    )
    named = [
        freeze.scene_spec,
        freeze.authoring_blend,
        freeze.build_provenance,
        freeze.integrated_quality_report,
        *freeze.quality_evidence,
        freeze.material_plan,
        *freeze.shader_recipes,
        *freeze.texture_manifests,
        *freeze.geometry_payloads,
        freeze.geometry_intent_survival,
        freeze.geometry_candidate_validation_receipt,
        freeze.material_phase_receipt,
    ]
    if freeze.provenance != named:
        raise ValueError("AQ v2 quality freeze provenance differs from its named sources")
    for artifact in named:
        validate_v2_artifact(root, artifact)
    report = _load_model(
        root,
        freeze.integrated_quality_report,
        IntegratedQualityReportV02,
    )
    camera_matches = [
        item for item in freeze.quality_evidence if item.sha256 == report.camera_sha256
    ]
    if len(camera_matches) != 1:
        raise ValueError("AQ v2 quality freeze camera evidence is ambiguous")
    policy = _load_model(root, authorization.quality_profile, IntegratedQualityPolicyV02)
    validate_host_recomputed_quality_report_v2(
        job_root=root,
        report=report,
        quality_evidence=freeze.quality_evidence,
        camera_artifact=camera_matches[0],
        expected_policy=policy,
    )
    if (
        report.job_id != freeze.job_id
        or report.workflow_id != freeze.workflow_id
        or report.dispatch_id != freeze.dispatch_id
        or report.outcome != "passed"
        or not report.quality_accepted
        or not report.hard_gates
        or any(gate.required and gate.status != "passed" for gate in report.hard_gates)
    ):
        raise ValueError("AQ v2 quality freeze does not bind an accepted IQ 0.2 report")
    evidence_hashes = {item.sha256 for item in freeze.quality_evidence}
    if _quality_report_evidence_hashes(report) - evidence_hashes:
        raise ValueError("IQ 0.2 report references evidence outside the quality freeze")
    quality_source_fingerprint = validate_quality_source_inputs_v2(
        job_root=root,
        job_id=freeze.job_id,
        scene_spec=freeze.scene_spec,
        authoring_blend=freeze.authoring_blend,
        build_provenance=freeze.build_provenance,
        material_plan=freeze.material_plan,
        shader_recipes=freeze.shader_recipes,
        texture_manifests=freeze.texture_manifests,
        geometry_payloads=freeze.geometry_payloads,
    )
    validate_quality_promotion_evidence_v2(
        job_root=root,
        job_id=freeze.job_id,
        workflow_id=freeze.workflow_id,
        dispatch_id=freeze.dispatch_id,
        session_id=freeze.session_id,
        geometry_candidate_validation_receipt=(
            freeze.geometry_candidate_validation_receipt
        ),
        material_phase_receipt=freeze.material_phase_receipt,
        geometry_intent_survival=freeze.geometry_intent_survival,
        scene_spec=freeze.scene_spec,
        authoring_blend=freeze.authoring_blend,
        build_provenance=freeze.build_provenance,
        material_plan=freeze.material_plan,
    )
    quality_input_sha256 = quality_submission_input_sha256_v2(
        source_fingerprint=quality_source_fingerprint,
        camera_artifact=camera_matches[0],
        quality_evidence=freeze.quality_evidence,
        scene_spec=freeze.scene_spec,
        authoring_blend=freeze.authoring_blend,
        build_provenance=freeze.build_provenance,
        material_plan=freeze.material_plan,
        shader_recipes=freeze.shader_recipes,
        texture_manifests=freeze.texture_manifests,
        geometry_payloads=freeze.geometry_payloads,
        geometry_intent_survival=freeze.geometry_intent_survival,
        geometry_candidate_validation_receipt=(
            freeze.geometry_candidate_validation_receipt
        ),
        material_phase_receipt=freeze.material_phase_receipt,
    )
    if (
        report.source_fingerprint != quality_source_fingerprint
        or report.input_sha256 != quality_input_sha256
    ):
        raise ValueError("AQ v2 quality freeze report is stale for its canonical source")
    source = collect_source_provenance(root, freeze.job_id)
    if source.source_fingerprint != freeze.v07_source_fingerprint:
        raise ValueError("canonical source changed after AQ v2 quality freeze")
    frozen_payload: dict[str, object] = {
        "scene_spec": freeze.scene_spec.sha256,
        "authoring_blend": freeze.authoring_blend.sha256,
        "build_provenance": freeze.build_provenance.sha256,
        "integrated_quality_report": freeze.integrated_quality_report.sha256,
        "quality_evidence": [item.sha256 for item in freeze.quality_evidence],
        "material_plan": freeze.material_plan.sha256,
        "shader_recipes": [item.sha256 for item in freeze.shader_recipes],
        "texture_manifests": [item.sha256 for item in freeze.texture_manifests],
        "geometry_payloads": [item.sha256 for item in freeze.geometry_payloads],
        "geometry_intent_survival": freeze.geometry_intent_survival.sha256,
        "geometry_candidate_validation_receipt": (
            freeze.geometry_candidate_validation_receipt.sha256
        ),
        "material_phase_receipt": freeze.material_phase_receipt.sha256,
        "quality_source_fingerprint": quality_source_fingerprint,
        "quality_input_sha256": quality_input_sha256,
        "v07_source_fingerprint": freeze.v07_source_fingerprint,
    }
    frozen_digest = stable_json_digest(frozen_payload)
    if frozen_digest != freeze.frozen_source_sha256 or freeze.source_fingerprint != frozen_digest:
        raise ValueError("AQ v2 frozen source digest is inconsistent")
    expected_input = stable_json_digest(
        {
            "quality_report": freeze.integrated_quality_report.sha256,
            "quality_input": report.input_sha256,
            "camera": report.camera_sha256,
        }
    )
    if freeze.input_sha256 != expected_input:
        raise ValueError("AQ v2 quality freeze input digest is inconsistent")


def _quality_report_evidence_hashes(report: IntegratedQualityReportV02) -> set[str]:
    """Collect exact file hashes named by IQ 0.2 without treating identity digests as files."""

    hashes: set[str] = set()
    if report.legacy_v06_report_sha256 is not None:
        hashes.add(report.legacy_v06_report_sha256)
    for value in (
        report.contour.reference_mask_sha256,
        report.contour.candidate_mask_sha256,
    ):
        if value is not None:
            hashes.add(value)
    for semantic in report.semantics:
        binding = semantic.reference_evidence
        for value in (
            binding.artifact_sha256,
            binding.registration_receipt_sha256,
            semantic.contour.reference_mask_sha256,
            semantic.contour.candidate_mask_sha256,
        ):
            if value is not None:
                hashes.add(value)
    for landmark in report.landmarks:
        for value in (
            landmark.source_artifact_sha256,
            landmark.candidate_artifact_sha256,
        ):
            if value is not None:
                hashes.add(value)
    for observation in report.multiview.observations:
        if observation.artifact_sha256 is not None:
            hashes.add(observation.artifact_sha256)
    for metric in report.advisory_metrics:
        if metric.artifact_sha256 is not None:
            hashes.add(metric.artifact_sha256)
    return hashes


def publish_quality_source_freeze(
    *,
    job_root: Path,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    integrated_quality_report: AQV2Artifact,
    quality_evidence: list[AQV2Artifact],
    scene_spec: AQV2Artifact,
    authoring_blend: AQV2Artifact,
    build_provenance: AQV2Artifact,
    material_plan: AQV2Artifact,
    shader_recipes: list[AQV2Artifact],
    texture_manifests: list[AQV2Artifact],
    geometry_payloads: list[AQV2Artifact],
    geometry_intent_survival: AQV2Artifact,
    geometry_candidate_validation_receipt: AQV2Artifact,
    material_phase_receipt: AQV2Artifact,
    camera_artifact: AQV2Artifact,
    created_at: datetime | None = None,
) -> tuple[QualityApprovedSourceFreeze, AQV2Artifact]:
    """Publish a freeze only after revalidating a passed IQ 0.2 report and canonical source."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    authorization, _plan, _profile, _budget = validate_root_authorization_boundary_v2(
        job_root=root,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
    )
    all_artifacts = [
        scene_spec,
        authoring_blend,
        build_provenance,
        integrated_quality_report,
        *quality_evidence,
        material_plan,
        *shader_recipes,
        *texture_manifests,
        *geometry_payloads,
        geometry_intent_survival,
        geometry_candidate_validation_receipt,
        material_phase_receipt,
    ]
    for artifact in all_artifacts:
        validate_v2_artifact(root, artifact)
    if camera_artifact not in quality_evidence:
        raise ValueError("AQ v2 quality evidence must include the fixed camera artifact")
    report_path = validate_v2_artifact(root, integrated_quality_report)
    report = IntegratedQualityReportV02.model_validate_json(
        Path(native_io_path(report_path)).read_bytes()
    )
    policy = _load_model(root, authorization.quality_profile, IntegratedQualityPolicyV02)
    validate_host_recomputed_quality_report_v2(
        job_root=root,
        report=report,
        quality_evidence=quality_evidence,
        camera_artifact=camera_artifact,
        expected_policy=policy,
    )
    quality_source_fingerprint = validate_quality_source_inputs_v2(
        job_root=root,
        job_id=job_id,
        scene_spec=scene_spec,
        authoring_blend=authoring_blend,
        build_provenance=build_provenance,
        material_plan=material_plan,
        shader_recipes=shader_recipes,
        texture_manifests=texture_manifests,
        geometry_payloads=geometry_payloads,
    )
    validate_quality_promotion_evidence_v2(
        job_root=root,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        geometry_candidate_validation_receipt=geometry_candidate_validation_receipt,
        material_phase_receipt=material_phase_receipt,
        geometry_intent_survival=geometry_intent_survival,
        scene_spec=scene_spec,
        authoring_blend=authoring_blend,
        build_provenance=build_provenance,
        material_plan=material_plan,
    )
    quality_input_sha256 = quality_submission_input_sha256_v2(
        source_fingerprint=quality_source_fingerprint,
        camera_artifact=camera_artifact,
        quality_evidence=quality_evidence,
        scene_spec=scene_spec,
        authoring_blend=authoring_blend,
        build_provenance=build_provenance,
        material_plan=material_plan,
        shader_recipes=shader_recipes,
        texture_manifests=texture_manifests,
        geometry_payloads=geometry_payloads,
        geometry_intent_survival=geometry_intent_survival,
        geometry_candidate_validation_receipt=geometry_candidate_validation_receipt,
        material_phase_receipt=material_phase_receipt,
    )
    if (
        report.job_id != job_id
        or report.workflow_id != workflow_id
        or report.dispatch_id != dispatch_id
        or report.outcome != "passed"
        or not report.quality_accepted
        or report.input_sha256 != quality_input_sha256
        or report.source_fingerprint != quality_source_fingerprint
        or report.camera_sha256 != camera_artifact.sha256
    ):
        raise ValueError("IQ 0.2 report is not an exact accepted source-freeze input")
    if not report.hard_gates or any(
        gate.required and gate.status != "passed" for gate in report.hard_gates
    ):
        raise ValueError("AQ v2 source freeze requires every required hard gate to pass")
    evidence_hashes = {item.sha256 for item in quality_evidence}
    evidence_hashes.add(camera_artifact.sha256)
    missing_hashes = _quality_report_evidence_hashes(report) - evidence_hashes
    if missing_hashes:
        raise ValueError("IQ 0.2 report references quality evidence outside the freeze")

    source = collect_source_provenance(root, job_id)
    if source.scene_spec is None or source.material_plan is None:
        raise ValueError("AQ v2 quality freeze requires SceneSpec and material provenance")
    if quality_source_fingerprint_v2(root, job_id) != quality_source_fingerprint:
        raise ValueError("canonical source changed during AQ v2 quality freeze")
    frozen_payload = {
        "scene_spec": scene_spec.sha256,
        "authoring_blend": authoring_blend.sha256,
        "build_provenance": build_provenance.sha256,
        "integrated_quality_report": integrated_quality_report.sha256,
        "quality_evidence": [item.sha256 for item in quality_evidence],
        "material_plan": material_plan.sha256,
        "shader_recipes": [item.sha256 for item in shader_recipes],
        "texture_manifests": [item.sha256 for item in texture_manifests],
        "geometry_payloads": [item.sha256 for item in geometry_payloads],
        "geometry_intent_survival": geometry_intent_survival.sha256,
        "geometry_candidate_validation_receipt": (geometry_candidate_validation_receipt.sha256),
        "material_phase_receipt": material_phase_receipt.sha256,
        "quality_source_fingerprint": quality_source_fingerprint,
        "quality_input_sha256": quality_input_sha256,
        "v07_source_fingerprint": source.source_fingerprint,
    }
    freeze = QualityApprovedSourceFreeze(
        contract_id=f"quality-freeze-{session_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(
            {
                "quality_report": integrated_quality_report.sha256,
                "quality_input": report.input_sha256,
                "camera": report.camera_sha256,
            }
        ),
        source_fingerprint=stable_json_digest(frozen_payload),
        producer=_PRODUCER,
        provenance=all_artifacts,
        created_at=created_at or datetime.now(UTC),
        freeze_id=f"quality-freeze-{session_id}",
        scene_spec=scene_spec,
        authoring_blend=authoring_blend,
        build_provenance=build_provenance,
        integrated_quality_report=integrated_quality_report,
        quality_evidence=quality_evidence,
        material_plan=material_plan,
        shader_recipes=shader_recipes,
        texture_manifests=texture_manifests,
        geometry_payloads=geometry_payloads,
        geometry_intent_survival=geometry_intent_survival,
        geometry_candidate_validation_receipt=(
            geometry_candidate_validation_receipt
        ),
        material_phase_receipt=material_phase_receipt,
        v07_source_fingerprint=source.source_fingerprint,
        frozen_source_sha256=stable_json_digest(frozen_payload),
    )
    validate_quality_source_freeze(root, freeze)
    path = root / "production" / "autonomy_v2" / session_id / "source_freeze.json"
    return freeze, write_immutable_v2_model(root, path, freeze)


def _delivery_requests_for_authorization(
    authorization: RootAuthorizationV2,
    source_freeze_artifact: AQV2Artifact,
    plan_id: str,
) -> list[DeliveryRequest]:
    """Derive the only delivery requests permitted by one exact root authorization."""

    requests: list[DeliveryRequest] = []
    for index, profile_id in enumerate(authorization.requested_delivery_profiles, start=1):
        profile = delivery_profile(profile_id)
        portable = profile_id != "review_only"
        suffix = profile_id.replace("portable_", "")
        requests.append(
            DeliveryRequest(
                delivery_id=f"delivery-{index:02d}-{suffix}",
                profile=profile,
                source_freeze=source_freeze_artifact,
                run_id=f"{plan_id}-{suffix}-run" if portable else None,
                package_id=f"{plan_id}-{suffix}-package" if portable else None,
                status="planned" if portable else "review_only",
            )
        )
    return requests


def validate_delivery_plan_authority_v2(
    root: Path,
    plan: DeliveryPlan,
    plan_artifact: AQV2Artifact | None = None,
) -> RootAuthorizationV2:
    """Revalidate one delivery plan against its live exact root authorization boundary."""

    authorization, _autonomy_plan, _profile, _budget = (
        validate_root_authorization_boundary_v2(
            job_root=root,
            job_id=plan.job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            session_id=plan.session_id,
            root_authorization_artifact=plan.root_authorization,
        )
    )
    if plan_artifact is not None:
        expected_path = (
            f"production/autonomy_v2/{plan.session_id}/delivery_plan.json"
        )
        if (
            plan_artifact.path != expected_path
            or plan_artifact.artifact_id != plan.contract_id
            or plan_artifact.kind != "delivery-plan"
        ):
            raise ValueError("AQ v2 delivery plan is outside its immutable host path")
    expected_requests = _delivery_requests_for_authorization(
        authorization,
        plan.source_freeze,
        plan.plan_id,
    )
    input_payload = {
        "root_authorization": plan.root_authorization.sha256,
        "source_freeze": plan.source_freeze.sha256,
        "profiles": authorization.requested_delivery_profiles,
    }
    if (
        plan.requests != expected_requests
        or plan.provenance != [plan.root_authorization, plan.source_freeze]
        or plan.input_sha256 != stable_json_digest(input_payload)
        or plan.source_fingerprint
        != stable_json_digest(
            {**input_payload, "frozen_source": _load_model(
                root,
                plan.source_freeze,
                QualityApprovedSourceFreeze,
            ).frozen_source_sha256}
        )
    ):
        raise ValueError("AQ v2 delivery plan exceeds or differs from root authorization")
    return authorization


def create_delivery_plan(
    *,
    job_root: Path,
    root_authorization_artifact: AQV2Artifact,
    source_freeze_artifact: AQV2Artifact,
    plan_id: str,
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> tuple[DeliveryPlan, AQV2Artifact]:
    """Create one immutable multi-format plan without optimizing, approving, or packaging."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    submitted_authorization = _load_model(
        root,
        root_authorization_artifact,
        RootAuthorizationV2,
    )
    authorization, _plan, profile, _budget = validate_root_authorization_boundary_v2(
        job_root=root,
        job_id=submitted_authorization.job_id,
        workflow_id=submitted_authorization.workflow_id,
        dispatch_id=submitted_authorization.dispatch_id,
        session_id=submitted_authorization.session_id,
        root_authorization_artifact=root_authorization_artifact,
    )
    freeze = _load_model(root, source_freeze_artifact, QualityApprovedSourceFreeze)
    if (
        PROFILE_STATUS != "verified_active" or profile.status != "verified_active"
    ) and not allow_disabled_experimental:
        raise PermissionError("autonomous_static_prop_v2 is disabled_experimental")
    if (
        authorization.job_id != freeze.job_id
        or authorization.workflow_id != freeze.workflow_id
        or authorization.dispatch_id != freeze.dispatch_id
        or authorization.session_id != freeze.session_id
    ):
        raise ValueError("quality freeze identity does not match root authorization")
    validate_quality_source_freeze(root, freeze)
    requests = _delivery_requests_for_authorization(
        authorization,
        source_freeze_artifact,
        plan_id,
    )
    input_payload = {
        "root_authorization": root_authorization_artifact.sha256,
        "source_freeze": source_freeze_artifact.sha256,
        "profiles": authorization.requested_delivery_profiles,
    }
    plan = DeliveryPlan(
        contract_id=plan_id,
        job_id=freeze.job_id,
        workflow_id=freeze.workflow_id,
        dispatch_id=freeze.dispatch_id,
        session_id=freeze.session_id,
        input_sha256=stable_json_digest(input_payload),
        source_fingerprint=stable_json_digest(
            {**input_payload, "frozen_source": freeze.frozen_source_sha256}
        ),
        producer="codex_blender_modeler.autonomy_v2.delivery_service",
        provenance=[root_authorization_artifact, source_freeze_artifact],
        created_at=created_at or datetime.now(UTC),
        plan_id=plan_id,
        root_authorization=root_authorization_artifact,
        source_freeze=source_freeze_artifact,
        requests=requests,
    )
    path = root / "production" / "autonomy_v2" / freeze.session_id / "delivery_plan.json"
    return plan, write_immutable_v2_model(root, path, plan)


def prepare_v07_delivery_reviews(
    *,
    job_root: Path,
    delivery_plan_artifact: AQV2Artifact,
    created_at: datetime | None = None,
) -> tuple[DeliveryReviewBinding, AQV2Artifact]:
    """Create independent V0.7 reviews and stop at each exact plan-hash approval boundary."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    plan = _load_model(root, delivery_plan_artifact, DeliveryPlan)
    validate_delivery_plan_authority_v2(root, plan, delivery_plan_artifact)
    freeze = _load_model(root, plan.source_freeze, QualityApprovedSourceFreeze)
    validate_quality_source_freeze(root, freeze)
    entries: list[DeliveryReviewEntry] = []
    for request in plan.requests:
        if request.profile.profile_id == "review_only":
            continue
        asset_profile_id = request.profile.asset_profile_id
        if asset_profile_id is None or request.run_id is None or request.package_id is None:
            raise ValueError("portable delivery request is incomplete")
        initialize_asset_profile(
            plan.job_id,
            profile_id=asset_profile_id,
            asset_kind="static_prop",
            overwrite=False,
        )
        review = plan_asset_optimization(
            plan.job_id,
            profile_id=asset_profile_id,
            run_id=request.run_id,
        )
        run_root = root / "optimization" / "runs" / request.run_id
        plan_path = run_root / "review_plan.json"
        review_path = run_root / "optimization_review.json"
        plan_artifact = artifact_for_v2(
            root,
            plan_path,
            artifact_id=f"{request.delivery_id}-optimization-plan",
            kind="optimization_plan",
        )
        review_artifact = artifact_for_v2(
            root,
            review_path,
            artifact_id=f"{request.delivery_id}-optimization-review",
            kind="optimization_review",
        )
        parsed_plan = OptimizationPlan.model_validate_json(
            Path(native_io_path(plan_path)).read_bytes()
        )
        parsed_review = OptimizationReview.model_validate_json(
            Path(native_io_path(review_path)).read_bytes()
        )
        if (
            parsed_plan.status != "draft"
            or parsed_review.plan_sha256 != plan_artifact.sha256
            or review.plan_sha256 != plan_artifact.sha256
            or parsed_plan.source.source_fingerprint != freeze.v07_source_fingerprint
        ):
            raise ValueError("V0.7 delivery review is stale for the quality freeze")
        profile_path = root / "asset_profiles" / f"{asset_profile_id}.json"
        entries.append(
            DeliveryReviewEntry(
                delivery_id=request.delivery_id,
                profile_id=request.profile.profile_id,
                asset_profile_id=asset_profile_id,
                run_id=request.run_id,
                package_id=request.package_id,
                asset_profile=artifact_for_v2(
                    root,
                    profile_path,
                    artifact_id=f"{request.delivery_id}-asset-profile",
                    kind="asset_profile",
                ),
                optimization_plan=plan_artifact,
                optimization_review=review_artifact,
                exact_plan_sha256=plan_artifact.sha256,
            )
        )
    if not entries:
        raise ValueError("review_only delivery has no V0.7 optimization boundary")
    input_payload = {
        "delivery_plan": delivery_plan_artifact.sha256,
        "source_freeze": plan.source_freeze.sha256,
        "entries": [item.model_dump(mode="json") for item in entries],
    }
    binding = DeliveryReviewBinding(
        contract_id=f"review-binding-{plan.plan_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=stable_json_digest(input_payload),
        source_fingerprint=stable_json_digest(
            {**input_payload, "frozen_source": freeze.frozen_source_sha256}
        ),
        producer="codex_blender_modeler.autonomy_v2.delivery_service",
        provenance=[
            delivery_plan_artifact,
            plan.source_freeze,
            *[entry.asset_profile for entry in entries],
            *[entry.optimization_plan for entry in entries],
            *[entry.optimization_review for entry in entries],
        ],
        created_at=created_at or datetime.now(UTC),
        binding_id=f"review-binding-{plan.plan_id}",
        delivery_plan=delivery_plan_artifact,
        source_freeze=plan.source_freeze,
        entries=entries,
    )
    path = root / "production" / "autonomy_v2" / plan.session_id / "delivery_reviews.json"
    return binding, write_immutable_v2_model(root, path, binding)


def _validate_package_result(
    root: Path,
    freeze: QualityApprovedSourceFreeze,
    request: DeliveryRequest,
    review: DeliveryReviewEntry,
    result: DeliveryResult,
) -> None:
    """Revalidate one completed result against its exact request and V0.7 review."""

    if result.delivery_id != request.delivery_id or result.profile_id != request.profile.profile_id:
        raise ValueError("delivery result identity does not match its immutable request")
    if result.status != "completed":
        return
    assert result.optimization_plan is not None
    assert result.package_manifest is not None
    assert result.roundtrip_validation is not None
    assert result.material_loss_report is not None
    assert result.geometry_survival_report is not None
    plan_path = validate_v2_artifact(root, result.optimization_plan)
    package_path = validate_v2_artifact(root, result.package_manifest)
    roundtrip_path = validate_v2_artifact(root, result.roundtrip_validation)
    approval = None
    policy_authorization = None
    if result.optimization_approval is not None:
        approval_path = validate_v2_artifact(root, result.optimization_approval)
        approval = OptimizationApproval.model_validate_json(
            Path(native_io_path(approval_path)).read_bytes()
        )
    elif result.optimization_policy_authorization is not None:
        from .approval_models import AQV2RoutinePolicyAuthorization

        policy_path = validate_v2_artifact(
            root,
            result.optimization_policy_authorization,
        )
        policy_authorization = AQV2RoutinePolicyAuthorization.model_validate_json(
            Path(native_io_path(policy_path)).read_bytes()
        )
    else:
        raise ValueError("completed delivery has no exact user or policy authority")
    package = ExportPackageManifest.model_validate_json(
        Path(native_io_path(package_path)).read_bytes()
    )
    roundtrip = RoundTripValidation.model_validate_json(
        Path(native_io_path(roundtrip_path)).read_bytes()
    )
    expected_profile = {
        "portable_gltf": "portable_gltf",
        "portable_fbx": "fbx_interchange",
    }[result.profile_id]
    plan = OptimizationPlan.model_validate_json(Path(native_io_path(plan_path)).read_bytes())
    review_path = validate_v2_artifact(root, review.optimization_review)
    parsed_review = OptimizationReview.model_validate_json(
        Path(native_io_path(review_path)).read_bytes()
    )
    if (
        request.run_id is None
        or request.package_id is None
        or review.delivery_id != request.delivery_id
        or review.profile_id != request.profile.profile_id
        or review.run_id != request.run_id
        or review.package_id != request.package_id
        or result.optimization_plan != review.optimization_plan
        or plan.status != "draft"
        or plan.job_id != freeze.job_id
        or plan.profile_id != expected_profile
        or plan.source.source_fingerprint != freeze.v07_source_fingerprint
        or (
            approval is not None
            and (
                not approval.used
                or approval.plan_sha256 != sha256_file(plan_path)
                or approval.review_sha256 != review.optimization_review.sha256
                or approval.job_id != freeze.job_id
                or approval.run_id != request.run_id
                or approval.profile_id != expected_profile
                or approval.profile_sha256 != review.asset_profile.sha256
                or approval.preflight_sha256 != plan.preflight_report.sha256
                or approval.source_fingerprint != freeze.v07_source_fingerprint
            )
        )
        or (
            policy_authorization is not None
            and (
                policy_authorization.job_id != freeze.job_id
                or policy_authorization.workflow_id != freeze.workflow_id
                or policy_authorization.dispatch_id != freeze.dispatch_id
                or policy_authorization.session_id != freeze.session_id
                or policy_authorization.gate_kind
                != "optimization_plan_authorization"
                or policy_authorization.exact_target_artifact.path
                != review.optimization_plan.path
                or policy_authorization.exact_target_artifact.sha256
                != review.exact_plan_sha256
                or policy_authorization.current_canonical_snapshot.path
                != request.source_freeze.path
                or policy_authorization.current_canonical_snapshot.sha256
                != request.source_freeze.sha256
            )
        )
        or parsed_review.run_id != request.run_id
        or parsed_review.profile_id != expected_profile
        or parsed_review.plan_sha256 != review.exact_plan_sha256
        or package.status != "complete"
        or package.profile_id != expected_profile
        or package.job_id != freeze.job_id
        or package.run_id != request.run_id
        or package.package_id != request.package_id
        or package.source.source_fingerprint != freeze.v07_source_fingerprint
        or roundtrip.status != "passed"
        or not roundtrip.ok
        or roundtrip.package_id != package.package_id
        or roundtrip.run_id != package.run_id
        or roundtrip.profile_id != package.profile_id
        or roundtrip.package_manifest.sha256 != result.package_manifest.sha256
    ):
        raise ValueError("completed delivery evidence is stale or inconsistent")
    for file_receipt in package.files:
        path = ensure_contained_production_path(
            root,
            root / file_receipt.path,
            must_exist=True,
        )
        if (
            not os.path.isfile(native_io_path(path))
            or os.path.getsize(native_io_path(path)) != file_receipt.byte_size
            or sha256_file(path) != file_receipt.sha256
        ):
            raise ValueError("package file changed after delivery completion")
    imported = ensure_contained_production_path(
        root,
        root / roundtrip.imported_inventory.path,
        must_exist=True,
    )
    if sha256_file(imported) != roundtrip.imported_inventory.sha256:
        raise ValueError("roundtrip imported inventory changed")
    if (
        package.material_conversion is None
        or result.material_loss_report.path != package.material_conversion.path
        or result.material_loss_report.sha256 != package.material_conversion.sha256
    ):
        raise ValueError("completed delivery must bind the package material conversion")
    material_path = validate_v2_artifact(root, result.material_loss_report)
    material = PortableMaterialConversionManifest.model_validate_json(
        Path(native_io_path(material_path)).read_bytes()
    )
    if (
        material.status != "complete"
        or material.job_id != freeze.job_id
        or material.run_id != request.run_id
        or material.profile_id != expected_profile
        or material.source.source_fingerprint != freeze.v07_source_fingerprint
        or material.missing_material_ids
    ):
        raise ValueError("material-loss evidence is stale or incomplete")
    survival_path = validate_v2_artifact(root, result.geometry_survival_report)
    survival = GeometryIntentSurvivalReportV02.model_validate_json(
        Path(native_io_path(survival_path)).read_bytes()
    )
    expected_format = "GLB" if result.profile_id == "portable_gltf" else "FBX"
    expected_stage = (
        "clean_import_glb" if result.profile_id == "portable_gltf" else "clean_import_fbx"
    )
    if (
        survival.relation != "optimized_to_clean_import"
        or survival.package_format != expected_format
        or survival.target_stage != expected_stage
        or survival.overall_status in {"failed", "unscorable"}
    ):
        raise ValueError("geometry-survival evidence is not delivery-equivalent")


def publish_delivery_terminal(
    *,
    job_root: Path,
    quality_terminal_artifact: AQV2Artifact,
    delivery_plan_artifact: AQV2Artifact,
    delivery_review_artifact: AQV2Artifact | None,
    results: list[DeliveryResult],
    created_at: datetime | None = None,
) -> tuple[DeliveryTerminalV2, AQV2Artifact]:
    """Publish an aggregate terminal while retaining every format-specific result."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    # Import locally because the quality-terminal validator reuses this module's
    # exact artifact and source-freeze helpers.
    from .quality_terminal_service import validate_quality_terminal_v2

    quality_terminal = validate_quality_terminal_v2(
        root,
        quality_terminal_artifact,
    )
    plan = _load_model(root, delivery_plan_artifact, DeliveryPlan)
    validate_delivery_plan_authority_v2(root, plan, delivery_plan_artifact)
    freeze = _load_model(root, plan.source_freeze, QualityApprovedSourceFreeze)
    if quality_terminal.status != "quality_approved":
        raise ValueError("portable delivery requires a quality-approved terminal")
    if quality_terminal.source_freeze != plan.source_freeze:
        raise ValueError("quality terminal and delivery plan use different source freezes")
    validate_quality_source_freeze(root, freeze)
    portable_requests = [
        request for request in plan.requests if request.profile.profile_id != "review_only"
    ]
    review_binding: DeliveryReviewBinding | None = None
    if portable_requests:
        if delivery_review_artifact is None:
            raise ValueError("portable delivery terminal requires an exact review binding")
        review_binding = _load_model(
            root,
            delivery_review_artifact,
            DeliveryReviewBinding,
        )
        if (
            review_binding.job_id != plan.job_id
            or review_binding.workflow_id != plan.workflow_id
            or review_binding.dispatch_id != plan.dispatch_id
            or review_binding.session_id != plan.session_id
            or review_binding.delivery_plan != delivery_plan_artifact
            or review_binding.source_freeze != plan.source_freeze
            or len(review_binding.entries) != len(portable_requests)
        ):
            raise ValueError("delivery review does not match the immutable delivery plan")
    elif delivery_review_artifact is not None:
        raise ValueError("review_only terminal cannot claim a V0.7 review binding")
    expected_ids = [item.delivery_id for item in plan.requests]
    if [item.delivery_id for item in results] != expected_ids:
        raise ValueError("delivery results do not match the immutable plan order")
    review_by_delivery = {
        entry.delivery_id: entry
        for entry in (review_binding.entries if review_binding is not None else [])
    }
    for request, result in zip(plan.requests, results, strict=True):
        if (
            result.delivery_id != request.delivery_id
            or result.profile_id != request.profile.profile_id
        ):
            raise ValueError("delivery result does not match its planned profile")
        if result.source_freeze_sha256 != plan.source_freeze.sha256:
            raise ValueError("delivery result is bound to the wrong quality freeze")
        for artifact in (
            result.optimization_plan,
            result.optimization_approval,
            result.optimization_policy_authorization,
            result.package_manifest,
            result.roundtrip_validation,
            result.material_loss_report,
            result.geometry_survival_report,
            result.handoff_manifest,
        ):
            if artifact is not None:
                validate_v2_artifact(root, artifact)
        if request.profile.profile_id == "review_only":
            if result.status != "review_only":
                raise ValueError("review_only request requires a review_only result")
        else:
            review = review_by_delivery.get(request.delivery_id)
            if review is None:
                raise ValueError("portable delivery result has no exact review entry")
            _validate_package_result(root, freeze, request, review, result)
    statuses = [item.status for item in results]
    if statuses == ["review_only"]:
        outcome = "review_only"
    elif all(status == "completed" for status in statuses):
        outcome = "completed"
    elif any(status == "completed" for status in statuses):
        outcome = "partial"
    else:
        outcome = "failed"
    evidence = [quality_terminal_artifact, delivery_plan_artifact, plan.source_freeze]
    if delivery_review_artifact is not None:
        evidence.append(delivery_review_artifact)
    for result in results:
        evidence.extend(
            artifact
            for artifact in (
                result.optimization_plan,
                result.optimization_approval,
                result.optimization_policy_authorization,
                result.package_manifest,
                result.roundtrip_validation,
                result.material_loss_report,
                result.geometry_survival_report,
                result.handoff_manifest,
            )
            if artifact is not None
        )
    input_payload = {
        "quality_terminal": quality_terminal_artifact.sha256,
        "delivery_plan": delivery_plan_artifact.sha256,
        "delivery_review": (
            delivery_review_artifact.sha256 if delivery_review_artifact is not None else None
        ),
        "results": [item.model_dump(mode="json") for item in results],
    }
    terminal = DeliveryTerminalV2(
        contract_id=f"delivery-terminal-{plan.session_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=stable_json_digest(input_payload),
        source_fingerprint=stable_json_digest(
            {**input_payload, "frozen_source": freeze.frozen_source_sha256}
        ),
        producer="codex_blender_modeler.autonomy_v2.delivery_service",
        provenance=evidence,
        created_at=created_at or datetime.now(UTC),
        terminal_id=f"delivery-terminal-{plan.session_id}",
        quality_terminal=quality_terminal_artifact,
        source_freeze=plan.source_freeze,
        delivery_plan=delivery_plan_artifact,
        delivery_review=delivery_review_artifact,
        outcome=outcome,
        results=results,
    )
    path = root / "production" / "autonomy_v2" / plan.session_id / "delivery_terminal.json"
    return terminal, write_immutable_v2_model(root, path, terminal)


def validate_delivery_terminal_v2(
    job_root: Path,
    terminal_artifact: AQV2Artifact,
) -> DeliveryTerminalV2:
    """Revalidate one terminal and every nested package, roundtrip, and loss artifact."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    # Keep the import local to avoid a module cycle while still reconstructing
    # the complete quality-approval boundary before trusting delivery evidence.
    from .quality_terminal_service import validate_quality_terminal_v2

    terminal = _load_model(root, terminal_artifact, DeliveryTerminalV2)
    plan = _load_model(root, terminal.delivery_plan, DeliveryPlan)
    validate_delivery_plan_authority_v2(root, plan, terminal.delivery_plan)
    freeze = _load_model(root, terminal.source_freeze, QualityApprovedSourceFreeze)
    quality_terminal = validate_quality_terminal_v2(
        root,
        terminal.quality_terminal,
    )
    if (
        terminal.job_id != plan.job_id
        or terminal.workflow_id != plan.workflow_id
        or terminal.dispatch_id != plan.dispatch_id
        or terminal.session_id != plan.session_id
        or terminal.source_freeze != plan.source_freeze
        or quality_terminal.status != "quality_approved"
        or quality_terminal.source_freeze != terminal.source_freeze
    ):
        raise ValueError("delivery terminal identity or quality boundary is inconsistent")
    validate_quality_source_freeze(root, freeze)

    portable_requests = [
        request for request in plan.requests if request.profile.profile_id != "review_only"
    ]
    review_binding: DeliveryReviewBinding | None = None
    if portable_requests:
        if terminal.delivery_review is None:
            raise ValueError("portable delivery terminal has no exact review binding")
        review_binding = _load_model(
            root,
            terminal.delivery_review,
            DeliveryReviewBinding,
        )
        if (
            review_binding.delivery_plan != terminal.delivery_plan
            or review_binding.source_freeze != terminal.source_freeze
            or review_binding.job_id != terminal.job_id
            or review_binding.workflow_id != terminal.workflow_id
            or review_binding.dispatch_id != terminal.dispatch_id
            or review_binding.session_id != terminal.session_id
        ):
            raise ValueError("delivery terminal review binding is inconsistent")
    elif terminal.delivery_review is not None:
        raise ValueError("review-only delivery terminal cannot bind a V0.7 review")

    if [item.delivery_id for item in terminal.results] != [
        item.delivery_id for item in plan.requests
    ]:
        raise ValueError("delivery terminal result order differs from its plan")
    review_by_delivery = {
        entry.delivery_id: entry
        for entry in (review_binding.entries if review_binding is not None else [])
    }
    for request, result in zip(plan.requests, terminal.results, strict=True):
        if (
            result.delivery_id != request.delivery_id
            or result.profile_id != request.profile.profile_id
            or result.source_freeze_sha256 != terminal.source_freeze.sha256
        ):
            raise ValueError("delivery terminal result identity is inconsistent")
        for artifact in (
            result.optimization_plan,
            result.optimization_approval,
            result.optimization_policy_authorization,
            result.package_manifest,
            result.roundtrip_validation,
            result.material_loss_report,
            result.geometry_survival_report,
            result.handoff_manifest,
        ):
            if artifact is not None:
                validate_v2_artifact(root, artifact)
        if request.profile.profile_id == "review_only":
            if result.status != "review_only":
                raise ValueError("review-only terminal contains a portable result")
            continue
        review = review_by_delivery.get(request.delivery_id)
        if review is None:
            raise ValueError("portable terminal result has no exact review entry")
        _validate_package_result(root, freeze, request, review, result)

    statuses = [item.status for item in terminal.results]
    expected_outcome = (
        "review_only"
        if statuses == ["review_only"]
        else (
            "completed"
            if all(status == "completed" for status in statuses)
            else ("partial" if any(status == "completed" for status in statuses) else "failed")
        )
    )
    if terminal.outcome != expected_outcome:
        raise ValueError("delivery terminal outcome differs from its exact results")
    input_payload = {
        "quality_terminal": terminal.quality_terminal.sha256,
        "delivery_plan": terminal.delivery_plan.sha256,
        "delivery_review": (
            terminal.delivery_review.sha256 if terminal.delivery_review is not None else None
        ),
        "results": [item.model_dump(mode="json") for item in terminal.results],
    }
    if terminal.input_sha256 != stable_json_digest(
        input_payload
    ) or terminal.source_fingerprint != stable_json_digest(
        {**input_payload, "frozen_source": freeze.frozen_source_sha256}
    ):
        raise ValueError("delivery terminal fingerprint is inconsistent")
    expected_provenance = [
        terminal.quality_terminal,
        terminal.delivery_plan,
        terminal.source_freeze,
    ]
    if terminal.delivery_review is not None:
        expected_provenance.append(terminal.delivery_review)
    for result in terminal.results:
        expected_provenance.extend(
            artifact
            for artifact in (
                result.optimization_plan,
                result.optimization_approval,
                result.optimization_policy_authorization,
                result.package_manifest,
                result.roundtrip_validation,
                result.material_loss_report,
                result.geometry_survival_report,
                result.handoff_manifest,
            )
            if artifact is not None
        )
    if terminal.provenance != expected_provenance:
        raise ValueError("delivery terminal provenance differs from its exact results")
    return terminal
