"""Self-contained validation of sealed delegated technical packages after relocation."""

from __future__ import annotations

import json
from pathlib import Path

from ..optimization.delegated import (
    AUTHORIZATION_FILE,
    CLAIM_SNAPSHOT,
    CONFIRMATION_SNAPSHOT,
    CONSUMPTION_FILE,
    PROFILE_SNAPSHOT,
    QUALITY_SNAPSHOT,
    SCOPE_SNAPSHOT,
    TASK_BINDING_SNAPSHOT,
    TEXT_SNAPSHOT,
    _safe_path,
    _write_contract_once,
)
from ..optimization.delegated_models import (
    DelegatedOptimizationAuthorizationV01,
    DelegatedOptimizationConsumptionV01,
    DelegatedOptimizationScopeV01,
    DelegatedOptimizationWorkflowBindingV01,
    DelegatedPackageAuthorityV01,
)
from ..optimization.io import load_model, utc_now
from ..optimization.models import (
    AssetProfile,
    MeshPreflightReport,
    OptimizationPlan,
    OptimizationReview,
)
from ..workspace import sha256_file
from .models import ExportPackageManifest

MANIFEST_FILE = "delegated_package_authority_manifest.json"
REQUIRED_EVIDENCE = frozenset(
    {
        AUTHORIZATION_FILE,
        CONSUMPTION_FILE,
        SCOPE_SNAPSHOT,
        TEXT_SNAPSHOT,
        CONFIRMATION_SNAPSHOT,
        CLAIM_SNAPSHOT,
        TASK_BINDING_SNAPSHOT,
        PROFILE_SNAPSHOT,
        "asset_profile.json",
        "mesh_preflight_report.json",
        "review_plan.json",
        "optimization_review.json",
        "optimization_plan.json",
        "execution_plan.json",
    }
)


def write_delegated_package_authority(
    package_root: Path,
    *,
    job_id: str,
    run_id: str,
    package_id: str,
) -> Path:
    """Seal the complete copied authority evidence before immutable package publication."""

    metadata = package_root / "metadata"
    grant = load_model(metadata / AUTHORIZATION_FILE, DelegatedOptimizationAuthorizationV01)
    scope = load_model(metadata / SCOPE_SNAPSHOT, DelegatedOptimizationScopeV01)
    if utc_now() >= scope.expires_at:
        raise ValueError("delegated technical scope expired before package publication")
    names = set(REQUIRED_EVIDENCE)
    workflow_binding = "optimization_delegated_workflow_binding.json"
    if (metadata / workflow_binding).exists():
        names.update(
            {
                workflow_binding,
                "optimization_delegated_workflow_plan.json",
                "optimization_delegated_workflow_request.json",
            }
        )
    if (metadata / QUALITY_SNAPSHOT).exists():
        names.add(QUALITY_SNAPSHOT)
    manifest = DelegatedPackageAuthorityV01(
        job_id=job_id,
        run_id=run_id,
        package_id=package_id,
        source_fingerprint=grant.source.source_fingerprint,
        evidence_sha256={
            name: sha256_file(_safe_path(package_root, metadata / name)) for name in sorted(names)
        },
        created_at=utc_now(),
    )
    target = metadata / MANIFEST_FILE
    _write_contract_once(target, manifest)
    return target


def validate_delegated_package_authority(package_directory: str | Path) -> dict:
    """Validate a relocated bundle using only its own immutable bytes, without execution."""

    root = Path(package_directory).absolute()
    metadata = _safe_path(root, root / "metadata")
    package = load_model(_safe_path(root, root / "package_manifest.json"), ExportPackageManifest)
    manifest = load_model(_safe_path(root, metadata / MANIFEST_FILE), DelegatedPackageAuthorityV01)
    if (
        package.status != "complete"
        or package.content_mode != "full_evidence"
        or package.profile_id != "portable_gltf"
        or manifest.job_id != package.job_id
        or manifest.run_id != package.run_id
        or manifest.package_id != package.package_id
        or manifest.source_fingerprint != package.source.source_fingerprint
        or not REQUIRED_EVIDENCE <= manifest.evidence_sha256.keys()
        or bool(
            set(manifest.evidence_sha256)
            - REQUIRED_EVIDENCE
            - {
                "optimization_delegated_workflow_binding.json",
                "optimization_delegated_workflow_plan.json",
                "optimization_delegated_workflow_request.json",
                QUALITY_SNAPSHOT,
            }
        )
    ):
        raise ValueError("delegated package authority manifest is incomplete or foreign")
    prefix = Path("exports") / "packages" / package.profile_id / package.package_id
    tracked = set()
    for receipt in package.files:
        try:
            relative = Path(receipt.path).relative_to(prefix)
        except ValueError as exc:
            raise ValueError("portable receipt escaped its exact package identity") from exc
        path = _safe_path(root, root / relative)
        if (
            not path.is_file()
            or path.stat().st_size != receipt.byte_size
            or sha256_file(path) != receipt.sha256
        ):
            raise ValueError("portable package file receipt changed")
        tracked.add(relative.as_posix())
    actual = set()
    for path in root.rglob("*"):
        _safe_path(root, path)
        if path.is_file() and path != root / "package_manifest.json":
            actual.add(path.relative_to(root).as_posix())
    if actual != tracked:
        raise ValueError("portable delegated package contains missing or untracked files")
    for name, digest in manifest.evidence_sha256.items():
        if "/" in name or "\\" in name or sha256_file(_safe_path(root, metadata / name)) != digest:
            raise ValueError("portable delegated evidence snapshot changed")
    if any(
        (metadata / name).exists() or (metadata / name).is_symlink()
        for name in ("optimization_approval.json", "optimization_policy_authorization.json")
    ):
        raise ValueError("portable package mixes delegated and other authority")
    grant = load_model(metadata / AUTHORIZATION_FILE, DelegatedOptimizationAuthorizationV01)
    scope = load_model(metadata / SCOPE_SNAPSHOT, DelegatedOptimizationScopeV01)
    consumed = load_model(metadata / CONSUMPTION_FILE, DelegatedOptimizationConsumptionV01)
    reviewed = load_model(metadata / "review_plan.json", OptimizationPlan)
    review = load_model(metadata / "optimization_review.json", OptimizationReview)
    plan = load_model(metadata / "optimization_plan.json", OptimizationPlan)
    profile = load_model(metadata / "asset_profile.json", AssetProfile)
    preflight = load_model(metadata / "mesh_preflight_report.json", MeshPreflightReport)
    claim = json.loads((metadata / CLAIM_SNAPSHOT).read_text(encoding="utf-8"))
    binding = json.loads((metadata / TASK_BINDING_SNAPSHOT).read_text(encoding="utf-8"))
    if plan.source_quality is not None:
        if (
            QUALITY_SNAPSHOT not in manifest.evidence_sha256
            or sha256_file(metadata / QUALITY_SNAPSHOT)
            != plan.source_quality.report_artifact.sha256
        ):
            raise ValueError("portable source-quality snapshot changed")
    elif QUALITY_SNAPSHOT in manifest.evidence_sha256:
        raise ValueError("portable package has unexpected source-quality snapshot")
    execution = load_model(metadata / "execution_plan.json", OptimizationPlan)
    expected_execution = plan.model_copy(
        update={"status": "running", "completed_at": None, "output_manifests": [], "errors": []}
    )
    if execution != expected_execution:
        raise ValueError("portable execution plan differs from its exact completed plan")
    execution_artifacts = [
        artifact
        for artifact in plan.output_manifests
        if artifact.path == f"optimization/runs/{grant.run_id}/execution_plan.json"
    ]
    if (
        len(execution_artifacts) != 1
        or execution_artifacts[0].kind != "optimization_plan"
        or execution_artifacts[0].sha256 != sha256_file(metadata / "execution_plan.json")
    ):
        raise ValueError("portable execution plan output hash is not exactly bound")
    for artifact in plan.output_manifests:
        if not artifact.path.startswith(f"optimization/runs/{grant.run_id}/"):
            raise ValueError("portable optimization output is outside its exact run")
        name = Path(artifact.path).name
        if name in {
            "lod_manifest.json",
            "collision_manifest.json",
            "uv_manifest.json",
            "asset_cost_report.json",
            "optimized_asset_evidence.json",
        }:
            if sha256_file(_safe_path(root, metadata / name)) != artifact.sha256:
                raise ValueError("portable optimization output hash changed")
    optimized_evidence = metadata / "optimized_asset_evidence.json"
    if optimized_evidence.exists():
        raw = json.loads(optimized_evidence.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or raw.get("ok") is not True
            or raw.get("plan_sha256") != sha256_file(metadata / "execution_plan.json")
            or not isinstance(raw.get("source"), dict)
            or raw["source"].get("build_fingerprint") != grant.source.build_fingerprint
        ):
            raise ValueError("portable optimized evidence differs from exact execution")
    workflow_names = {
        "optimization_delegated_workflow_binding.json",
        "optimization_delegated_workflow_plan.json",
        "optimization_delegated_workflow_request.json",
    }
    included_workflow = workflow_names.intersection(manifest.evidence_sha256)
    if included_workflow:
        from ..orchestration.models import WorkflowPlan, WorkflowRequest

        if included_workflow != workflow_names:
            raise ValueError("portable workflow binding snapshots are incomplete")
        wf_binding = load_model(
            metadata / "optimization_delegated_workflow_binding.json",
            DelegatedOptimizationWorkflowBindingV01,
        )
        wf_plan_path = metadata / "optimization_delegated_workflow_plan.json"
        wf_request_path = metadata / "optimization_delegated_workflow_request.json"
        wf_plan = load_model(wf_plan_path, WorkflowPlan)
        wf_request = load_model(wf_request_path, WorkflowRequest)
        gates = [step for step in wf_plan.steps if step.approval_gate == "optimization_plan"]
        if (
            wf_binding.job_id != grant.job_id
            or wf_binding.run_id != grant.run_id
            or wf_binding.authorization != consumed.authorization
            or wf_binding.workflow_plan.sha256 != sha256_file(wf_plan_path)
            or wf_binding.workflow_plan.path != f"workflows/{wf_binding.workflow_id}/plan.json"
            or wf_plan.workflow_id != wf_binding.workflow_id
            or wf_request.workflow_id != wf_binding.workflow_id
            or wf_plan.job_id != grant.job_id
            or wf_request.job_id != grant.job_id
            or wf_plan.execution_policy != "standard"
            or wf_request.execution_policy != "standard"
            or wf_plan.request_sha256 != sha256_file(wf_request_path)
            or len(gates) != 1
            or gates[0].step_id != "portable.plan_approval"
            or gates[0].parameters.get("run_id") != grant.run_id
            or gates[0].parameters.get("profile_id") != "portable_gltf"
        ):
            raise ValueError("portable workflow binding differs from exact authority")
    grant_hash = sha256_file(metadata / AUTHORIZATION_FILE)
    run_prefix = f"optimization/runs/{grant.run_id}"
    if (
        grant.job_id != package.job_id
        or grant.run_id != package.run_id
        or grant.source != package.source
        or grant.source != plan.source
        or grant.source != reviewed.source
        or grant.source != review.source
        or grant.source != preflight.source
        or plan.job_id != grant.job_id
        or reviewed.job_id != grant.job_id
        or plan.plan_id != reviewed.plan_id
        or plan.directives != reviewed.directives
        or plan.profile_artifact != reviewed.profile_artifact
        or plan.preflight_report != reviewed.preflight_report
        or plan.source_quality != reviewed.source_quality
        or review.source_quality != reviewed.source_quality
        or review.job_id != grant.job_id
        or review.run_id != grant.run_id
        or preflight.job_id != grant.job_id
        or profile.job_id != grant.job_id
        or plan.status != "complete"
        or reviewed.status != "draft"
        or not preflight.ok
        or profile.profile_id != "portable_gltf"
        or profile.primary_format != "glb"
        or any(
            value != "portable_gltf"
            for value in (
                plan.profile_id,
                reviewed.profile_id,
                review.profile_id,
                preflight.profile_id,
            )
        )
        or plan.completed_at is None
        or plan.completed_at > manifest.created_at
        or package.optimization_plan.path != f"{prefix.as_posix()}/metadata/optimization_plan.json"
        or package.optimization_plan.sha256 != sha256_file(metadata / "optimization_plan.json")
        or grant.plan_sha256 != sha256_file(metadata / "review_plan.json")
        or review.plan_sha256 != grant.plan_sha256
        or grant.review_sha256 != sha256_file(metadata / "optimization_review.json")
        or grant.profile_sha256 != sha256_file(metadata / "asset_profile.json")
        or grant.profile_sha256 != sha256_file(metadata / PROFILE_SNAPSHOT)
        or grant.preflight_sha256 != sha256_file(metadata / "mesh_preflight_report.json")
        or grant.scope.sha256 != sha256_file(metadata / SCOPE_SNAPSHOT)
        or scope.job_id != grant.job_id
        or scope.delegation_text.sha256 != sha256_file(metadata / TEXT_SNAPSHOT)
        or grant.delegation_text_sha256 != scope.delegation_text.sha256
        or scope.extension_confirmation_text.sha256 != sha256_file(metadata / CONFIRMATION_SNAPSHOT)
        or not any(
            item.job_id == grant.job_id and item.reference_sha256 == grant.reference_sha256
            for item in scope.allowed_assets
        )
        or consumed.job_id != grant.job_id
        or consumed.run_id != grant.run_id
        or consumed.authorization.sha256 != grant_hash
        or consumed.authorization.path != f"{run_prefix}/{AUTHORIZATION_FILE}"
        or consumed.authorization.id != grant.authorization_id
        or consumed.authorization.kind != "other"
        or consumed.source_fingerprint != grant.source.source_fingerprint
        or consumed.plan_sha256 != grant.plan_sha256
        or plan.approved_at != grant.authorized_at
        or not scope.created_at
        <= grant.authorized_at
        <= consumed.consumed_at
        <= manifest.created_at
        < scope.expires_at
        or claim
        != {
            "run_id": grant.run_id,
            "scope_sha256": grant.scope.sha256,
            "grant_ordinal": grant.grant_ordinal,
            "authorization_path": f"{run_prefix}/{AUTHORIZATION_FILE}",
            "authorization_sha256": grant_hash,
        }
        or binding != {"scope_path": grant.scope.path, "scope_sha256": grant.scope.sha256}
    ):
        raise ValueError("portable delegated authority cross-file binding differs")
    return {
        "schema_version": "0.1.0",
        "job_id": grant.job_id,
        "run_id": grant.run_id,
        "package_id": package.package_id,
        "ok": True,
        "actor": "delegated_assistant",
        "final_human_acceptance": False,
        "grants_execution_authority": False,
        "validation_scope": "self_contained_authority_integrity_only",
        "clean_import_validated": False,
    }
