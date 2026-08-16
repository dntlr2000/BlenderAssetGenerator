"""Host-owned execution of exact-approved AQ v2 portable delivery reviews."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ..blender_artifacts import native_io_path, sha256_file
from ..optimization import optimize_asset
from ..optimization.models import (
    OptimizationApproval,
    OptimizationPlan,
    OptimizationReview,
)
from ..optimization.preflight import load_asset_profile
from ..packaging import (
    convert_portable_materials,
    load_portable_material_conversion,
    package_asset,
    validate_asset_package,
)
from ..packaging.models import ExportPackageManifest, RoundTripValidation
from ..production.validation import ensure_contained_production_path
from ..structural_geometry.geometry_delivery_inspector_v02 import (
    inspect_delivery_geometry_stage_v02,
)
from ..structural_geometry.geometry_survival_v02 import (
    GeometryIntentSurvivalReportV02,
    GeometryStageSnapshotV02,
    compare_geometry_stage_snapshots_v02,
    publish_geometry_survival_report_v02,
    verify_geometry_stage_snapshot_artifact_v02,
)
from ..workspace import job_dir
from .delivery_service import (
    _validate_package_result,
    artifact_for_v2,
    validate_delivery_plan_authority_v2,
    validate_quality_source_freeze,
    validate_v2_artifact,
)
from .models import (
    AQV2Artifact,
    DeliveryPlan,
    DeliveryRequest,
    DeliveryResult,
    DeliveryReviewBinding,
    DeliveryReviewEntry,
    QualityApprovedSourceFreeze,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def _load_bound_model(
    root: Path,
    artifact: AQV2Artifact,
    model: type[ModelT],
) -> ModelT:
    """Rehash and strict-parse one immutable AQ v2 artifact."""

    path = validate_v2_artifact(root, artifact)
    return model.model_validate_json(Path(native_io_path(path)).read_bytes())


def _validate_execution_binding(
    plan: DeliveryPlan,
    plan_artifact: AQV2Artifact,
    review: DeliveryReviewBinding,
) -> dict[str, DeliveryReviewEntry]:
    """Validate exact plan/review identity and return a complete portable entry map."""

    if (
        review.job_id != plan.job_id
        or review.workflow_id != plan.workflow_id
        or review.dispatch_id != plan.dispatch_id
        or review.session_id != plan.session_id
        or review.delivery_plan != plan_artifact
        or review.source_freeze != plan.source_freeze
    ):
        raise ValueError("delivery review does not match the immutable delivery plan")
    portable = [
        request
        for request in plan.requests
        if request.profile.profile_id != "review_only"
    ]
    entries = {entry.delivery_id: entry for entry in review.entries}
    if set(entries) != {request.delivery_id for request in portable}:
        raise ValueError("delivery review does not exactly cover portable requests")
    for request in portable:
        entry = entries[request.delivery_id]
        if (
            request.run_id is None
            or request.package_id is None
            or entry.profile_id != request.profile.profile_id
            or entry.asset_profile_id != request.profile.asset_profile_id
            or entry.run_id != request.run_id
            or entry.package_id != request.package_id
        ):
            raise ValueError("delivery review entry does not match its immutable request")
    return entries


def _validate_unused_exact_approval(
    *,
    root: Path,
    freeze: QualityApprovedSourceFreeze,
    request: DeliveryRequest,
    review: DeliveryReviewEntry,
) -> OptimizationApproval:
    """Require one existing unused user approval matching the exact V0.7 review."""

    reviewed_plan, current_plan, approval = _load_exact_approval_context(
        root=root,
        freeze=freeze,
        request=request,
        review=review,
    )
    expected_approved = OptimizationPlan.model_validate(
        reviewed_plan.model_copy(
            update={"status": "approved", "approved_at": approval.approved_at}
        ).model_dump(mode="json")
    )
    if current_plan != expected_approved or approval.used:
        raise RuntimeError("existing OptimizationApproval does not match the exact review")
    return approval


def _load_exact_approval_context(
    *,
    root: Path,
    freeze: QualityApprovedSourceFreeze,
    request: DeliveryRequest,
    review: DeliveryReviewEntry,
) -> tuple[OptimizationPlan, OptimizationPlan, OptimizationApproval]:
    """Load and validate approval identity independently of unused/consumed lifecycle."""

    if request.run_id is None or request.profile.asset_profile_id is None:
        raise ValueError("portable delivery request is incomplete")
    run_root = ensure_contained_production_path(
        root,
        root / "optimization" / "runs" / request.run_id,
        must_exist=True,
    )
    review_plan_path = validate_v2_artifact(root, review.optimization_plan)
    review_path = validate_v2_artifact(root, review.optimization_review)
    validate_v2_artifact(root, review.asset_profile)
    approval_path = ensure_contained_production_path(
        root,
        run_root / "optimization_approval.json",
        must_exist=True,
    )
    policy_path = ensure_contained_production_path(
        root,
        run_root / "optimization_policy_authorization.json",
        must_exist=False,
    )
    if os.path.exists(native_io_path(policy_path)):
        raise RuntimeError("AQ v2 portable delivery requires a user OptimizationApproval")
    current_plan_path = ensure_contained_production_path(
        root,
        run_root / "optimization_plan.json",
        must_exist=True,
    )
    reviewed_plan = OptimizationPlan.model_validate_json(
        Path(native_io_path(review_plan_path)).read_bytes()
    )
    current_plan = OptimizationPlan.model_validate_json(
        Path(native_io_path(current_plan_path)).read_bytes()
    )
    parsed_review = OptimizationReview.model_validate_json(
        Path(native_io_path(review_path)).read_bytes()
    )
    approval = OptimizationApproval.model_validate_json(
        Path(native_io_path(approval_path)).read_bytes()
    )
    if (
        reviewed_plan.status != "draft"
        or review.exact_plan_sha256 != review.optimization_plan.sha256
        or sha256_file(review_plan_path) != review.exact_plan_sha256
        or parsed_review.plan_sha256 != review.exact_plan_sha256
        or parsed_review.job_id != freeze.job_id
        or parsed_review.run_id != request.run_id
        or parsed_review.profile_id != request.profile.asset_profile_id
        or parsed_review.source.source_fingerprint != freeze.v07_source_fingerprint
        or parsed_review.profile_artifact.path != review.asset_profile.path
        or parsed_review.profile_artifact.sha256 != review.asset_profile.sha256
        or parsed_review.preflight_report != reviewed_plan.preflight_report
        or reviewed_plan.job_id != freeze.job_id
        or reviewed_plan.profile_id != request.profile.asset_profile_id
        or reviewed_plan.source.source_fingerprint != freeze.v07_source_fingerprint
        or reviewed_plan.profile_artifact.path != review.asset_profile.path
        or reviewed_plan.profile_artifact.sha256 != review.asset_profile.sha256
        or approval.job_id != freeze.job_id
        or approval.run_id != request.run_id
        or approval.profile_id != request.profile.asset_profile_id
        or approval.plan_sha256 != review.exact_plan_sha256
        or approval.review_sha256 != review.optimization_review.sha256
        or approval.profile_sha256 != review.asset_profile.sha256
        or approval.preflight_sha256 != reviewed_plan.preflight_report.sha256
        or approval.source_fingerprint != freeze.v07_source_fingerprint
    ):
        raise RuntimeError("existing OptimizationApproval does not match the exact review")
    return reviewed_plan, current_plan, approval


def _validate_consumed_exact_approval(
    *,
    root: Path,
    freeze: QualityApprovedSourceFreeze,
    request: DeliveryRequest,
    review: DeliveryReviewEntry,
) -> tuple[OptimizationPlan, OptimizationApproval]:
    """Validate one consumed approval and its immutable completed optimization outputs."""

    reviewed_plan, completed_plan, approval = _load_exact_approval_context(
        root=root,
        freeze=freeze,
        request=request,
        review=review,
    )
    stable_fields = (
        "plan_id",
        "job_id",
        "profile_id",
        "profile_artifact",
        "preflight_report",
        "source",
        "source_quality",
        "directives",
    )
    if (
        not approval.used
        or completed_plan.status != "complete"
        or completed_plan.approved_at != approval.approved_at
        or completed_plan.completed_at is None
        or completed_plan.errors
        or any(
            getattr(completed_plan, field) != getattr(reviewed_plan, field)
            for field in stable_fields
        )
        or completed_plan.notes[: len(reviewed_plan.notes)] != reviewed_plan.notes
    ):
        raise RuntimeError("consumed OptimizationApproval has no exact completed run")
    for artifact in completed_plan.output_manifests:
        path = ensure_contained_production_path(
            root,
            root / artifact.path,
            must_exist=True,
        )
        if not os.path.isfile(native_io_path(path)) or sha256_file(path) != artifact.sha256:
            raise RuntimeError("completed optimization output no longer matches its receipt")
    return completed_plan, approval


def _validate_completed_exact_policy_authorization(
    *,
    root: Path,
    freeze: QualityApprovedSourceFreeze,
    request: DeliveryRequest,
    review: DeliveryReviewEntry,
    policy_authorization: AQV2Artifact,
) -> OptimizationPlan:
    """Validate a completed optimization run bound only to AQ v2 policy authority."""

    from .approval_models import AQV2RoutinePolicyAuthorization
    from .approval_policy_service import validate_routine_policy_authorization

    if request.run_id is None:
        raise ValueError("portable delivery request has no optimization run")
    run_root = ensure_contained_production_path(
        root,
        root / "optimization" / "runs" / request.run_id,
        must_exist=True,
    )
    authorization_path = validate_v2_artifact(root, policy_authorization)
    authorization = AQV2RoutinePolicyAuthorization.model_validate_json(
        Path(native_io_path(authorization_path)).read_bytes()
    )
    validate_routine_policy_authorization(
        freeze.job_id,
        freeze.session_id,
        policy_authorization_path=authorization_path,
        expected_gate_kind="optimization_plan_authorization",
        expected_target_path=root / review.optimization_plan.path,
    )
    snapshot_path = ensure_contained_production_path(
        root,
        run_root / "optimization_policy_authorization.json",
        must_exist=True,
    )
    if Path(native_io_path(snapshot_path)).read_bytes() != Path(
        native_io_path(authorization_path)
    ).read_bytes():
        raise RuntimeError("optimization policy snapshot differs from issued authority")
    reviewed_plan = _load_bound_model(root, review.optimization_plan, OptimizationPlan)
    completed_plan = OptimizationPlan.model_validate_json(
        Path(native_io_path(run_root / "optimization_plan.json")).read_bytes()
    )
    stable_fields = (
        "plan_id",
        "job_id",
        "profile_id",
        "profile_artifact",
        "preflight_report",
        "source",
        "source_quality",
        "directives",
    )
    if (
        completed_plan.status != "complete"
        or completed_plan.approved_at != authorization.created_at
        or completed_plan.completed_at is None
        or completed_plan.errors
        or any(
            getattr(completed_plan, field) != getattr(reviewed_plan, field)
            for field in stable_fields
        )
        or completed_plan.notes[: len(reviewed_plan.notes)] != reviewed_plan.notes
    ):
        raise RuntimeError("AQ v2 policy authority has no exact completed optimization run")
    for artifact in completed_plan.output_manifests:
        path = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
        if not os.path.isfile(native_io_path(path)) or sha256_file(path) != artifact.sha256:
            raise RuntimeError("completed optimization output changed after policy execution")
    return completed_plan


def _primary_package_artifact_path(
    root: Path,
    package: BaseModel,
) -> str:
    """Resolve the exact primary GLB or FBX receipt from one completed package."""

    primary_id = getattr(package, "primary_file_id", None)
    files = getattr(package, "files", [])
    primary = next(
        (item for item in files if item.id == primary_id and item.kind == "primary_asset"),
        None,
    )
    if primary is None:
        raise RuntimeError("completed package has no primary asset receipt")
    path = ensure_contained_production_path(root, root / primary.path, must_exist=True)
    if (
        not os.path.isfile(native_io_path(path))
        or os.path.getsize(native_io_path(path)) != primary.byte_size
        or sha256_file(path) != primary.sha256
    ):
        raise RuntimeError("package primary asset no longer matches its receipt")
    return primary.path


def _safe_delivery_error(root: Path, error: Exception) -> str:
    """Remove host-absolute paths while retaining a useful deterministic failure reason."""

    message = str(error).replace(str(root), "<job_root>")
    message = message.replace(str(root).replace("\\", "/"), "<job_root>")
    message = re.sub(r"(?i)\b[a-z]:[\\/][^\s;,\])}]+", "<absolute-path>", message)
    return f"{type(error).__name__}: {message or 'delivery execution failed'}"


def _partial_artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
) -> AQV2Artifact | None:
    """Bind one already-published partial artifact without masking the original failure."""

    try:
        if not os.path.isfile(native_io_path(path)):
            return None
        return artifact_for_v2(
            root,
            path,
            artifact_id=artifact_id,
            kind=kind,
        )
    except Exception:
        return None


def _load_job_model(path: Path, model: type[ModelT]) -> ModelT:
    """Strict-parse one expected job-owned model after its caller validates containment."""

    return model.model_validate_json(Path(native_io_path(path)).read_bytes())


def _adopt_completed_portable_request(
    *,
    root: Path,
    freeze: QualityApprovedSourceFreeze,
    source_freeze_artifact: AQV2Artifact,
    request: DeliveryRequest,
    review: DeliveryReviewEntry,
    policy_authorization: AQV2Artifact | None = None,
) -> DeliveryResult:
    """Adopt exact completed delivery without reusing either authority kind."""

    if (
        request.run_id is None
        or request.package_id is None
        or request.profile.asset_profile_id is None
    ):
        raise ValueError("portable delivery request is incomplete")
    if policy_authorization is None:
        completed_plan, _approval = _validate_consumed_exact_approval(
            root=root,
            freeze=freeze,
            request=request,
            review=review,
        )
    else:
        completed_plan = _validate_completed_exact_policy_authorization(
            root=root,
            freeze=freeze,
            request=request,
            review=review,
            policy_authorization=policy_authorization,
        )
    validate_quality_source_freeze(root, freeze)
    run_root = ensure_contained_production_path(
        root,
        root / "optimization" / "runs" / request.run_id,
        must_exist=True,
    )
    conversion_id = f"{request.delivery_id}-materials"
    profile = load_asset_profile(root, request.profile.asset_profile_id)
    conversion = load_portable_material_conversion(
        root,
        request.run_id,
        conversion_id,
        profile=profile,
        optimization=completed_plan,
    )
    package_path = ensure_contained_production_path(
        root,
        root
        / "exports"
        / "packages"
        / request.profile.asset_profile_id
        / request.package_id
        / "package_manifest.json",
        must_exist=True,
    )
    package = _load_job_model(package_path, ExportPackageManifest)
    roundtrip_path = ensure_contained_production_path(
        root,
        run_root
        / "roundtrip"
        / request.package_id
        / "roundtrip_validation.json",
        must_exist=True,
    )
    _load_job_model(roundtrip_path, RoundTripValidation)
    geometry_root = run_root / "aq_v2" / "geometry"
    optimized_snapshot_path = ensure_contained_production_path(
        root,
        geometry_root / "optimized_lod0_snapshot.json",
        must_exist=True,
    )
    imported_stage = (
        "clean_import_glb"
        if request.profile.profile_id == "portable_gltf"
        else "clean_import_fbx"
    )
    imported_snapshot_path = ensure_contained_production_path(
        root,
        geometry_root / f"{imported_stage}_snapshot.json",
        must_exist=True,
    )
    survival_path = ensure_contained_production_path(
        root,
        geometry_root / "optimized_to_clean_import_report.json",
        must_exist=True,
    )
    optimized_snapshot = _load_job_model(
        optimized_snapshot_path,
        GeometryStageSnapshotV02,
    )
    imported_snapshot = _load_job_model(
        imported_snapshot_path,
        GeometryStageSnapshotV02,
    )
    survival = _load_job_model(
        survival_path,
        GeometryIntentSurvivalReportV02,
    )
    verify_geometry_stage_snapshot_artifact_v02(optimized_snapshot, job_root=root)
    verify_geometry_stage_snapshot_artifact_v02(imported_snapshot, job_root=root)
    primary_path = _primary_package_artifact_path(root, package)
    expected_optimized_path = conversion.portable_blend.relative_to(root).as_posix()
    expected_build = completed_plan.source.build_fingerprint
    if (
        optimized_snapshot.stage != "optimized_lod0"
        or optimized_snapshot.artifact_path != expected_optimized_path
        or optimized_snapshot.source_fingerprint_sha256
        != freeze.v07_source_fingerprint
        or optimized_snapshot.build_fingerprint_sha256 != expected_build
        or imported_snapshot.stage != imported_stage
        or imported_snapshot.artifact_path != primary_path
        or imported_snapshot.source_fingerprint_sha256
        != freeze.v07_source_fingerprint
        or imported_snapshot.build_fingerprint_sha256 != expected_build
    ):
        raise RuntimeError("delivery geometry snapshots do not match the completed run")
    package_format = (
        "GLB" if request.profile.profile_id == "portable_gltf" else "FBX"
    )
    recomputed_survival = compare_geometry_stage_snapshots_v02(
        report_id=f"survival-{request.delivery_id}-optimized-clean-import",
        relation="optimized_to_clean_import",
        source=optimized_snapshot,
        target=imported_snapshot,
        package_format=package_format,
    )
    if survival != recomputed_survival:
        raise RuntimeError("geometry survival report does not match its exact snapshots")
    approval_artifact = None
    if policy_authorization is None:
        approval_artifact = artifact_for_v2(
            root,
            run_root / "optimization_approval.json",
            artifact_id=f"{request.delivery_id}-optimization-approval-used",
            kind="optimization_approval",
        )
    package_artifact = artifact_for_v2(
        root,
        package_path,
        artifact_id=f"{request.delivery_id}-package-manifest",
        kind="package_manifest",
    )
    roundtrip_artifact = artifact_for_v2(
        root,
        roundtrip_path,
        artifact_id=f"{request.delivery_id}-roundtrip-validation",
        kind="roundtrip_validation",
    )
    if package.material_conversion is None:
        raise RuntimeError("completed AQ v2 package has no material conversion snapshot")
    material_artifact = artifact_for_v2(
        root,
        root / package.material_conversion.path,
        artifact_id=f"{request.delivery_id}-packaged-material-conversion",
        kind="portable_material_conversion_manifest",
    )
    survival_artifact = artifact_for_v2(
        root,
        survival_path,
        artifact_id=f"{request.delivery_id}-geometry-survival",
        kind="geometry_survival_report",
    )
    result = DeliveryResult(
        delivery_id=request.delivery_id,
        profile_id=request.profile.profile_id,
        status="completed",
        source_freeze_sha256=source_freeze_artifact.sha256,
        optimization_plan=review.optimization_plan,
        optimization_approval=approval_artifact,
        optimization_policy_authorization=policy_authorization,
        package_manifest=package_artifact,
        roundtrip_validation=roundtrip_artifact,
        material_loss_report=material_artifact,
        geometry_survival_report=survival_artifact,
        production_ready=True,
        known_losses=list(
            dict.fromkeys([*package.known_losses, *survival.known_losses])
        ),
    )
    _validate_package_result(root, freeze, request, review, result)
    validate_quality_source_freeze(root, freeze)
    return result


def _execute_portable_request(
    *,
    root: Path,
    freeze: QualityApprovedSourceFreeze,
    source_freeze_artifact: AQV2Artifact,
    request: DeliveryRequest,
    review: DeliveryReviewEntry,
    policy_authorization: AQV2Artifact | None = None,
) -> DeliveryResult:
    """Execute one format from the freeze under exactly one authority kind."""

    if (
        request.run_id is None
        or request.package_id is None
        or request.profile.asset_profile_id is None
    ):
        raise ValueError("portable delivery request is incomplete")
    run_root = root / "optimization" / "runs" / request.run_id
    conversion_id = f"{request.delivery_id}-materials"
    conversion_path = (
        root
        / "optimization"
        / "material_conversions"
        / request.run_id
        / conversion_id
        / "conversion_manifest.json"
    )
    package_path = (
        root
        / "exports"
        / "packages"
        / request.profile.asset_profile_id
        / request.package_id
        / "package_manifest.json"
    )
    roundtrip_path = (
        run_root
        / "roundtrip"
        / request.package_id
        / "roundtrip_validation.json"
    )
    approval_path = run_root / "optimization_approval.json"
    policy_snapshot_path = run_root / "optimization_policy_authorization.json"
    geometry_root = run_root / "aq_v2" / "geometry"
    optimized_snapshot_path = geometry_root / "optimized_lod0_snapshot.json"
    imported_stage = (
        "clean_import_glb"
        if request.profile.profile_id == "portable_gltf"
        else "clean_import_fbx"
    )
    imported_snapshot_path = geometry_root / f"{imported_stage}_snapshot.json"
    survival_path = geometry_root / "optimized_to_clean_import_report.json"
    collected: dict[str, AQV2Artifact | None] = {
        "optimization_plan": None,
        "optimization_approval": None,
        "optimization_policy_authorization": policy_authorization,
        "package_manifest": None,
        "roundtrip_validation": None,
        "material_loss_report": None,
        "geometry_survival_report": None,
    }
    try:
        validate_quality_source_freeze(root, freeze)
        if policy_authorization is None:
            if os.path.isfile(native_io_path(policy_snapshot_path)):
                raise RuntimeError(
                    "delivery run mixes AQ v2 policy and user approval authority"
                )
            if os.path.isfile(native_io_path(approval_path)):
                existing_approval = OptimizationApproval.model_validate_json(
                    Path(native_io_path(approval_path)).read_bytes()
                )
                if existing_approval.used:
                    return _adopt_completed_portable_request(
                        root=root,
                        freeze=freeze,
                        source_freeze_artifact=source_freeze_artifact,
                        request=request,
                        review=review,
                    )
            _validate_unused_exact_approval(
                root=root,
                freeze=freeze,
                request=request,
                review=review,
            )
            collected["optimization_plan"] = review.optimization_plan
            optimized = optimize_asset(
                freeze.job_id,
                profile_id=request.profile.asset_profile_id,
                run_id=request.run_id,
                approved_plan_sha256=review.exact_plan_sha256,
            )
            collected["optimization_approval"] = artifact_for_v2(
                root,
                approval_path,
                artifact_id=f"{request.delivery_id}-optimization-approval-used",
                kind="optimization_approval",
            )
        else:
            if os.path.isfile(native_io_path(approval_path)):
                raise RuntimeError(
                    "delivery run mixes user approval and AQ v2 policy authority"
                )
            collected["optimization_plan"] = review.optimization_plan
            if os.path.isfile(native_io_path(policy_snapshot_path)):
                completed_path = run_root / "optimization_plan.json"
                completed = OptimizationPlan.model_validate_json(
                    Path(native_io_path(completed_path)).read_bytes()
                )
                if completed.status == "complete" and os.path.isfile(
                    native_io_path(package_path)
                ):
                    return _adopt_completed_portable_request(
                        root=root,
                        freeze=freeze,
                        source_freeze_artifact=source_freeze_artifact,
                        request=request,
                        review=review,
                        policy_authorization=policy_authorization,
                    )
                optimized = _validate_completed_exact_policy_authorization(
                    root=root,
                    freeze=freeze,
                    request=request,
                    review=review,
                    policy_authorization=policy_authorization,
                )
            else:
                from .approval_policy_service import (
                    validate_routine_policy_authorization,
                )

                policy_path = validate_v2_artifact(root, policy_authorization)
                validate_routine_policy_authorization(
                    freeze.job_id,
                    freeze.session_id,
                    policy_authorization_path=policy_path,
                    expected_gate_kind="optimization_plan_authorization",
                    expected_target_path=root / review.optimization_plan.path,
                )
                optimized = optimize_asset(
                    freeze.job_id,
                    profile_id=request.profile.asset_profile_id,
                    run_id=request.run_id,
                    approved_plan_sha256=review.exact_plan_sha256,
                    policy_authorization_path=policy_path,
                    workflow_id=freeze.workflow_id,
                    workflow_step_id=f"aqv2-delivery-{request.run_id}",
                    workflow_input_fingerprint=review.exact_plan_sha256,
                )
            collected["optimization_policy_authorization"] = policy_authorization
        if (
            optimized.status != "complete"
            or optimized.job_id != freeze.job_id
            or optimized.profile_id != request.profile.asset_profile_id
            or optimized.source.source_fingerprint != freeze.v07_source_fingerprint
        ):
            raise RuntimeError("V0.7 optimizer returned inconsistent completion evidence")
        validate_quality_source_freeze(root, freeze)
        conversion = convert_portable_materials(
            freeze.job_id,
            profile_id=request.profile.asset_profile_id,
            run_id=request.run_id,
            conversion_id=conversion_id,
        )
        if (
            conversion.status != "complete"
            or conversion.job_id != freeze.job_id
            or conversion.run_id != request.run_id
            or conversion.profile_id != request.profile.asset_profile_id
            or conversion.source.source_fingerprint != freeze.v07_source_fingerprint
            or conversion.missing_material_ids
            or conversion.portable_blend is None
        ):
            raise RuntimeError("portable material conversion is incomplete or stale")
        collected["material_loss_report"] = artifact_for_v2(
            root,
            conversion_path,
            artifact_id=f"{request.delivery_id}-material-conversion",
            kind="portable_material_conversion_manifest",
        )
        validate_quality_source_freeze(root, freeze)
        optimized_snapshot = inspect_delivery_geometry_stage_v02(
            job_root=root,
            artifact_relative_path=conversion.portable_blend.path,
            stage="optimized_lod0",
            output_relative_path=optimized_snapshot_path.relative_to(root).as_posix(),
            source_fingerprint_sha256=freeze.v07_source_fingerprint,
            build_fingerprint_sha256=optimized.source.build_fingerprint,
        )
        package = package_asset(
            freeze.job_id,
            profile_id=request.profile.asset_profile_id,
            run_id=request.run_id,
            package_id=request.package_id,
            material_conversion_id=conversion_id,
        )
        if (
            package.status != "complete"
            or package.job_id != freeze.job_id
            or package.run_id != request.run_id
            or package.package_id != request.package_id
            or package.profile_id != request.profile.asset_profile_id
            or package.source.source_fingerprint != freeze.v07_source_fingerprint
            or package.material_conversion is None
        ):
            raise RuntimeError("portable package returned inconsistent completion evidence")
        package_manifest_artifact = artifact_for_v2(
            root,
            package_path,
            artifact_id=f"{request.delivery_id}-package-manifest",
            kind="package_manifest",
        )
        collected["package_manifest"] = package_manifest_artifact
        packaged_material_artifact = artifact_for_v2(
            root,
            root / package.material_conversion.path,
            artifact_id=f"{request.delivery_id}-packaged-material-conversion",
            kind="portable_material_conversion_manifest",
        )
        collected["material_loss_report"] = packaged_material_artifact
        if packaged_material_artifact.sha256 != package.material_conversion.sha256:
            raise RuntimeError("packaged material conversion receipt is inconsistent")
        primary_path = _primary_package_artifact_path(root, package)
        roundtrip = validate_asset_package(
            freeze.job_id,
            request.package_id,
            profile_id=request.profile.asset_profile_id,
        )
        if (
            roundtrip.status != "passed"
            or not roundtrip.ok
            or roundtrip.job_id != freeze.job_id
            or roundtrip.run_id != request.run_id
            or roundtrip.package_id != request.package_id
            or roundtrip.profile_id != request.profile.asset_profile_id
            or roundtrip.package_manifest.path != package_manifest_artifact.path
            or roundtrip.package_manifest.sha256 != package_manifest_artifact.sha256
        ):
            raise RuntimeError("clean-import roundtrip did not pass for this format")
        collected["roundtrip_validation"] = artifact_for_v2(
            root,
            roundtrip_path,
            artifact_id=f"{request.delivery_id}-roundtrip-validation",
            kind="roundtrip_validation",
        )
        validate_quality_source_freeze(root, freeze)
        imported_snapshot = inspect_delivery_geometry_stage_v02(
            job_root=root,
            artifact_relative_path=primary_path,
            stage=imported_stage,
            output_relative_path=imported_snapshot_path.relative_to(root).as_posix(),
            source_fingerprint_sha256=freeze.v07_source_fingerprint,
            build_fingerprint_sha256=optimized.source.build_fingerprint,
        )
        survival = compare_geometry_stage_snapshots_v02(
            report_id=f"survival-{request.delivery_id}-optimized-clean-import",
            relation="optimized_to_clean_import",
            source=optimized_snapshot,
            target=imported_snapshot,
            package_format=(
                "GLB"
                if request.profile.profile_id == "portable_gltf"
                else "FBX"
            ),
        )
        publish_geometry_survival_report_v02(survival_path, survival)
        collected["geometry_survival_report"] = artifact_for_v2(
            root,
            survival_path,
            artifact_id=f"{request.delivery_id}-geometry-survival",
            kind="geometry_survival_report",
        )
        if survival.overall_status in {"failed", "unscorable"}:
            raise RuntimeError(
                "optimized-to-clean-import geometry survival was not proven"
            )
        validate_quality_source_freeze(root, freeze)
        losses = list(dict.fromkeys([*package.known_losses, *survival.known_losses]))
        return DeliveryResult(
            delivery_id=request.delivery_id,
            profile_id=request.profile.profile_id,
            status="completed",
            source_freeze_sha256=source_freeze_artifact.sha256,
            optimization_plan=review.optimization_plan,
            optimization_approval=collected["optimization_approval"],
            optimization_policy_authorization=collected[
                "optimization_policy_authorization"
            ],
            package_manifest=collected["package_manifest"],
            roundtrip_validation=collected["roundtrip_validation"],
            material_loss_report=collected["material_loss_report"],
            geometry_survival_report=collected["geometry_survival_report"],
            production_ready=True,
            known_losses=losses,
        )
    except Exception as error:
        collected["optimization_approval"] = collected[
            "optimization_approval"
        ] or _partial_artifact(
            root,
            approval_path,
            artifact_id=f"{request.delivery_id}-optimization-approval",
            kind="optimization_approval",
        )
        collected["material_loss_report"] = collected[
            "material_loss_report"
        ] or _partial_artifact(
            root,
            conversion_path,
            artifact_id=f"{request.delivery_id}-material-conversion",
            kind="portable_material_conversion_manifest",
        )
        collected["package_manifest"] = collected[
            "package_manifest"
        ] or _partial_artifact(
            root,
            package_path,
            artifact_id=f"{request.delivery_id}-package-manifest",
            kind="package_manifest",
        )
        collected["roundtrip_validation"] = collected[
            "roundtrip_validation"
        ] or _partial_artifact(
            root,
            roundtrip_path,
            artifact_id=f"{request.delivery_id}-roundtrip-validation",
            kind="roundtrip_validation",
        )
        collected["geometry_survival_report"] = collected[
            "geometry_survival_report"
        ] or _partial_artifact(
            root,
            survival_path,
            artifact_id=f"{request.delivery_id}-geometry-survival",
            kind="geometry_survival_report",
        )
        return DeliveryResult(
            delivery_id=request.delivery_id,
            profile_id=request.profile.profile_id,
            status="failed",
            source_freeze_sha256=source_freeze_artifact.sha256,
            optimization_plan=collected["optimization_plan"],
            optimization_approval=collected["optimization_approval"],
            optimization_policy_authorization=collected[
                "optimization_policy_authorization"
            ],
            package_manifest=collected["package_manifest"],
            roundtrip_validation=collected["roundtrip_validation"],
            material_loss_report=collected["material_loss_report"],
            geometry_survival_report=collected["geometry_survival_report"],
            production_ready=False,
            errors=[_safe_delivery_error(root, error)],
        )


def execute_approved_delivery_plan_v2(
    *,
    job_root: Path,
    delivery_plan_artifact: AQV2Artifact,
    delivery_review_artifact: AQV2Artifact,
) -> list[DeliveryResult]:
    """Execute exact-approved formats sequentially and preserve independent results."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    plan = _load_bound_model(root, delivery_plan_artifact, DeliveryPlan)
    validate_delivery_plan_authority_v2(root, plan, delivery_plan_artifact)
    configured_root = Path(job_dir(plan.job_id)).resolve()
    if configured_root != root.resolve():
        raise ValueError("job_root does not match the configured job workspace")
    freeze = _load_bound_model(root, plan.source_freeze, QualityApprovedSourceFreeze)
    review = _load_bound_model(root, delivery_review_artifact, DeliveryReviewBinding)
    if (
        freeze.job_id != plan.job_id
        or freeze.workflow_id != plan.workflow_id
        or freeze.dispatch_id != plan.dispatch_id
        or freeze.session_id != plan.session_id
    ):
        raise ValueError("quality freeze does not match the immutable delivery plan")
    validate_quality_source_freeze(root, freeze)
    entries = _validate_execution_binding(plan, delivery_plan_artifact, review)
    results: list[DeliveryResult] = []
    for request in plan.requests:
        if request.profile.profile_id == "review_only":
            results.append(
                DeliveryResult(
                    delivery_id=request.delivery_id,
                    profile_id="review_only",
                    status="review_only",
                    source_freeze_sha256=plan.source_freeze.sha256,
                    production_ready=False,
                )
            )
            continue
        results.append(
            _execute_portable_request(
                root=root,
                freeze=freeze,
                source_freeze_artifact=plan.source_freeze,
                request=request,
                review=entries[request.delivery_id],
            )
        )
    return results


def execute_policy_authorized_delivery_plan_v2(
    *,
    job_root: Path,
    delivery_plan_artifact: AQV2Artifact,
    delivery_review_artifact: AQV2Artifact,
    policy_authorizations: dict[str, AQV2Artifact],
) -> list[DeliveryResult]:
    """Execute exact AQ policy-authorized formats without creating V0.7 approvals."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    plan = _load_bound_model(root, delivery_plan_artifact, DeliveryPlan)
    validate_delivery_plan_authority_v2(root, plan, delivery_plan_artifact)
    configured_root = Path(job_dir(plan.job_id)).resolve()
    if configured_root != root.resolve():
        raise ValueError("job_root does not match the configured job workspace")
    freeze = _load_bound_model(root, plan.source_freeze, QualityApprovedSourceFreeze)
    review = _load_bound_model(root, delivery_review_artifact, DeliveryReviewBinding)
    if (
        freeze.job_id != plan.job_id
        or freeze.workflow_id != plan.workflow_id
        or freeze.dispatch_id != plan.dispatch_id
        or freeze.session_id != plan.session_id
    ):
        raise ValueError("quality freeze does not match the immutable delivery plan")
    validate_quality_source_freeze(root, freeze)
    entries = _validate_execution_binding(plan, delivery_plan_artifact, review)
    portable_ids = {
        request.delivery_id
        for request in plan.requests
        if request.profile.profile_id != "review_only"
    }
    if set(policy_authorizations) != portable_ids:
        raise ValueError("policy authorizations must exactly cover portable deliveries")
    results: list[DeliveryResult] = []
    for request in plan.requests:
        if request.profile.profile_id == "review_only":
            results.append(
                DeliveryResult(
                    delivery_id=request.delivery_id,
                    profile_id="review_only",
                    status="review_only",
                    source_freeze_sha256=plan.source_freeze.sha256,
                    production_ready=False,
                )
            )
            continue
        results.append(
            _execute_portable_request(
                root=root,
                freeze=freeze,
                source_freeze_artifact=plan.source_freeze,
                request=request,
                review=entries[request.delivery_id],
                policy_authorization=policy_authorizations[request.delivery_id],
            )
        )
    return results


def execute_policy_authorized_delivery_request_v2(
    *,
    job_root: Path,
    delivery_plan_artifact: AQV2Artifact,
    delivery_review_artifact: AQV2Artifact,
    delivery_id: str,
    policy_authorization: AQV2Artifact,
) -> DeliveryResult:
    """Execute one exact portable request so policy budgets can advance sequentially."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    plan = _load_bound_model(root, delivery_plan_artifact, DeliveryPlan)
    validate_delivery_plan_authority_v2(root, plan, delivery_plan_artifact)
    freeze = _load_bound_model(root, plan.source_freeze, QualityApprovedSourceFreeze)
    review = _load_bound_model(root, delivery_review_artifact, DeliveryReviewBinding)
    entries = _validate_execution_binding(plan, delivery_plan_artifact, review)
    requests = [item for item in plan.requests if item.delivery_id == delivery_id]
    if len(requests) != 1 or requests[0].profile.profile_id == "review_only":
        raise ValueError("policy delivery ID must select one exact portable request")
    request = requests[0]
    validate_quality_source_freeze(root, freeze)
    return _execute_portable_request(
        root=root,
        freeze=freeze,
        source_freeze_artifact=plan.source_freeze,
        request=request,
        review=entries[delivery_id],
        policy_authorization=policy_authorization,
    )
