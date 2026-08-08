"""V0.9 release evidence, read-only workspace audits, and bounded queue services."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..auto_revision.convergence import compare_constraint_results
from ..auto_revision.convergence_policy import (
    ConvergenceCandidateSelection,
    select_convergence_candidates,
    validate_convergence_activation,
    validate_iteration_receipt_chain,
)
from ..auto_revision.convergence_session import (
    _audit_qa_authoritative_evidence,
    _candidate_baselines,
    _require_host_safety_envelope,
)
from ..auto_revision.convergence_session_models import (
    HashBoundConvergenceArtifact,
    VisualConvergenceApproval,
    VisualConvergenceCancellation,
    VisualConvergenceIteration,
    VisualConvergenceIterationAuthorization,
    VisualConvergencePlan,
    VisualConvergenceReport,
    VisualConvergenceReportManifest,
)
from ..auto_revision.models import RevisionCandidates
from ..blender_artifacts import (
    native_io_path,
    sha256_file,
    write_json_atomic,
)
from ..config import get_settings, load_feature_config
from ..constraints.models import ConstraintResult
from ..external_intake.models import (
    ExternalAssetIntakeApproval,
    ExternalAssetIntakePlan,
    ExternalAssetIntakeValidation,
    ExternalAssetManifest,
    ExternalNormalizationReceipt,
)
from ..external_intake.service import collect_external_build_provenance
from ..handoff import get_destination_handoff_status
from ..handoff.models import (
    AssemblyManifest,
    DestinationContext,
    DestinationHandoffManifest,
    DestinationHandoffPlan,
    DestinationHandoffValidation,
    HandoffReportManifest,
    ImportChecklist,
    MaterialMappingManifest,
)
from ..interior_qa.models import (
    InteriorQALatest,
    InteriorQAPlan,
    InteriorQAPlanApproval,
    InteriorQARenderManifest,
    InteriorQAReport,
    InteriorQARevisionCandidates,
    InteriorQASourceInventory,
)
from ..optimization.io import resolve_inside
from ..orchestration import get_workflow_status, resume_workflow
from ..orchestration.models import (
    WorkflowAttempt,
    WorkflowLock,
    WorkflowPlan,
    WorkflowRequest,
    WorkflowState,
)
from ..qa.models import VisualQAReport
from ..revision import RevisionPlan
from ..versioning import (
    CONSTRAINT_SCHEMA_VERSION,
    DESTINATION_HANDOFF_SCHEMA_VERSION,
    EXTERNAL_STATIC_ASSET_SCHEMA_VERSION,
    INTERIOR_SCOPE_SCHEMA_VERSION,
    MATERIAL_SCHEMA_VERSION,
    PORTABLE_ASSET_SCHEMA_VERSION,
    PROJECT_VERSION,
    REFERENCE_SCHEMA_VERSION,
    SCENE_SPEC_VERSION,
    STABILIZATION_SCHEMA_VERSION,
    VISUAL_QA_SCHEMA_VERSION,
    WORKFLOW_SCHEMA_VERSION,
)
from .locks import queue_write_lock
from .models import (
    AuditFinding,
    ContractVersionRecord,
    EnvironmentProbeReport,
    EvidenceReference,
    JobAudit,
    LocalWorkflowQueue,
    QueueAttemptReceipt,
    QueueEntry,
    WorkspaceAuditReport,
)

_PORTABLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for V0.9 evidence."""

    return datetime.now(UTC)


def _portable_id(prefix: str) -> str:
    """Create a sortable portable identifier for immutable V0.9 artifacts."""

    stamp = _utc_now().strftime("%Y%m%dT%H%M%S%fZ").lower()
    return f"{prefix}-{stamp}-{uuid4().hex[:8]}"


def _validate_portable_id(value: str, label: str) -> str:
    """Reject caller-controlled identifiers that could escape their storage root."""

    if not _PORTABLE_ID_RE.fullmatch(value):
        raise ValueError(f"{label} must match [a-z0-9][a-z0-9._-]{{0,127}}")
    return value


def _require_stabilization() -> tuple[int, int, int]:
    """Require the V0.9 feature and return audit, lock, and lease bounds."""

    config = load_feature_config()
    if not config.features.stabilization_core:
        raise RuntimeError("stabilization_core is disabled in cbm.toml")
    return (
        config.stabilization.audit_scan_limit,
        config.stabilization.queue_lock_ttl_seconds,
        config.stabilization.queue_lease_seconds,
    )


def _workspace_mode() -> str:
    """Describe whether the workspace uses the repository default without exposing paths."""

    settings = get_settings()
    default_root = (settings.repo_root / "workspaces").resolve()
    return (
        "repository_default"
        if settings.workspace_root.resolve() == default_root
        else "external_configured"
    )


def _contract_versions() -> list[ContractVersionRecord]:
    """List every stable contract boundary preserved by project V0.9."""

    values = [
        ("scene_spec", SCENE_SPEC_VERSION),
        ("reference_analysis", REFERENCE_SCHEMA_VERSION),
        ("constraints", CONSTRAINT_SCHEMA_VERSION),
        ("interior_scope", INTERIOR_SCOPE_SCHEMA_VERSION),
        ("materials", MATERIAL_SCHEMA_VERSION),
        ("visual_qa", VISUAL_QA_SCHEMA_VERSION),
        ("portable_asset", PORTABLE_ASSET_SCHEMA_VERSION),
        ("workflow", WORKFLOW_SCHEMA_VERSION),
        ("stabilization", STABILIZATION_SCHEMA_VERSION),
        ("destination_handoff", DESTINATION_HANDOFF_SCHEMA_VERSION),
        ("external_static_asset", EXTERNAL_STATIC_ASSET_SCHEMA_VERSION),
    ]
    return [ContractVersionRecord(contract=name, version=version) for name, version in values]


def _repo_relative(path: Path) -> str:
    """Convert one repository-contained path into a privacy-safe POSIX path."""

    settings = get_settings()
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(settings.repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("V0.9 release evidence must remain inside the repository") from exc


def _read_blender_compatibility() -> tuple[
    str,
    str | None,
    bool | None,
    list[EvidenceReference],
    list[str],
]:
    """Read existing Blender evidence without rerunning Blender or copying absolute paths."""

    settings = get_settings()
    path = settings.repo_root / "reports" / "blender_compatibility.json"
    if not path.is_file():
        return (
            "missing",
            None,
            None,
            [],
            ["Blender compatibility evidence is missing; run cbm blender-compat."],
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        blender_version = payload.get("blender_version")
        ok = payload.get("ok")
        if not isinstance(blender_version, str) or not isinstance(ok, bool):
            raise ValueError("compatibility report lacks blender_version or boolean ok")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return (
            "invalid",
            None,
            None,
            [],
            [f"Blender compatibility evidence is invalid: {type(exc).__name__}."],
        )
    evidence = EvidenceReference(
        evidence_id="blender-compatibility",
        kind="blender_compatibility",
        path=_repo_relative(path),
        sha256=sha256_file(path),
    )
    return "valid", blender_version, ok, [evidence], []


def probe_release_environment(
    *,
    probe_id: str | None = None,
) -> EnvironmentProbeReport:
    """Persist a privacy-safe host snapshot backed by existing compatibility evidence."""

    _require_stabilization()
    selected_id = _validate_portable_id(
        probe_id or _portable_id("probe"),
        "probe_id",
    )
    status, blender_version, blender_ok, evidence, warnings = (
        _read_blender_compatibility()
    )
    settings = get_settings()
    feature_config = load_feature_config()
    executable_name = Path(settings.blender_bin).name or settings.blender_bin
    report = EnvironmentProbeReport(
        probe_id=selected_id,
        project_version=PROJECT_VERSION,
        platform_system=platform.system() or "unknown",
        platform_release=platform.release() or "unknown",
        architecture=platform.machine() or "unknown",
        python_version=platform.python_version(),
        blender_executable_name=executable_name,
        workspace_mode=_workspace_mode(),  # type: ignore[arg-type]
        blender_report_status=status,  # type: ignore[arg-type]
        blender_version=blender_version,
        blender_compatibility_ok=blender_ok,
        contracts=_contract_versions(),
        evidence=evidence,
        feature_flags=asdict(feature_config.features),
        warnings=warnings,
        limitations=[
            "Detected environment data is not a cross-platform support claim.",
            "Unity, Unreal, and custom destination adapters remain unsupported.",
            "Codex Destination Handoff plans imports but does not validate runtime parity.",
            "Blender evidence is reused by hash; this command does not execute Blender.",
        ],
        generated_at=_utc_now(),
    )
    output = (
        settings.repo_root
        / "reports"
        / "v09"
        / "environment"
        / selected_id
        / "environment_probe.json"
    )
    if output.exists():
        raise FileExistsError(f"Environment probe already exists: {selected_id}")
    write_json_atomic(output, report.model_dump(mode="json"))
    return report


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    job_id: str | None = None,
    path: str | None = None,
    remediation: str | None = None,
) -> AuditFinding:
    """Create a deterministic, privacy-safe audit finding identifier."""

    seed = json.dumps(
        [code, severity, job_id, path, message],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    import hashlib

    suffix = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    identifier = f"{code.casefold().replace('_', '-')}-{suffix}"
    return AuditFinding(
        finding_id=identifier,
        severity=severity,  # type: ignore[arg-type]
        code=code,
        job_id=job_id,
        path=path,
        message=message,
        remediation=remediation,
    )


def _workspace_relative(path: Path) -> str:
    """Express one contained workspace path without exposing the configured root."""

    workspace = get_settings().workspace_root.resolve()
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(workspace).as_posix()
    except ValueError as exc:
        raise ValueError("Audited path escapes the configured workspace") from exc
    return f"workspace/{relative}" if relative else "workspace"


def _workspace_relative_lexical(path: Path) -> str:
    """Report a link entry by lexical location without resolving its external target."""

    workspace = get_settings().workspace_root.absolute()
    candidate = path.expanduser().absolute()
    try:
        relative = candidate.relative_to(workspace).as_posix()
    except ValueError as exc:
        raise ValueError("Audited lexical path escapes the configured workspace") from exc
    return f"workspace/{relative}" if relative else "workspace"


def _is_link_like(path: Path) -> bool:
    """Detect symbolic links and Windows junctions before bounded traversal."""

    native = native_io_path(path)
    if os.path.islink(native):
        return True
    junction_test = getattr(os.path, "isjunction", None)
    return bool(junction_test(native)) if callable(junction_test) else False


def _read_text(path: Path) -> str:
    """Read UTF-8 audit evidence through a Windows extended-length filename."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        return handle.read()


def _parse_version(value: str | None) -> tuple[int, int, int] | None:
    """Parse a strict semantic version for migration compatibility classification."""

    if value is None:
        return None
    match = _VERSION_RE.fullmatch(value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _resolve_source_path(value: str, *, job_root: Path | None = None) -> Path:
    """Resolve legacy source metadata and recover its exact contained job-input suffix."""

    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    repository_candidate = (get_settings().repo_root / candidate).resolve()
    if job_root is None:
        return repository_candidate
    input_root = (job_root / "input").resolve()
    try:
        repository_candidate.relative_to(input_root)
    except ValueError:
        parts = candidate.parts
        workspace_name = get_settings().workspace_root.name
        for index in range(2, len(parts)):
            if (
                parts[index] == "input"
                and parts[index - 1] == job_root.name
                and parts[index - 2] == workspace_name
            ):
                suffix = parts[index + 1 :]
                if suffix and all(part not in {"", ".", ".."} for part in suffix):
                    return (input_root.joinpath(*suffix)).resolve()
        return repository_candidate
    return repository_candidate


def _validate_workflow_contract(path: Path) -> None:
    """Validate recognized V0.8 contracts and only exact attempt-receipt paths."""

    model_by_name: dict[str, type[Any]] = {
        "request.json": WorkflowRequest,
        "plan.json": WorkflowPlan,
        "state.json": WorkflowState,
        ".lock.json": WorkflowLock,
    }
    model = model_by_name.get(path.name)
    attempts_root = path.parent.parent
    workflow_root = attempts_root.parent
    if (
        model is None
        and attempts_root.name == "attempts"
        and workflow_root.parent.name == "workflows"
    ):
        model = WorkflowAttempt
    if model is not None:
        model.model_validate_json(_read_text(path))


def _validate_handoff_contract(path: Path) -> None:
    """Validate recognized V0.9 handoff JSON while leaving copied package JSON untouched."""

    model_by_name: dict[str, type[Any]] = {
        "handoff_plan.json": DestinationHandoffPlan,
        "handoff_manifest.json": DestinationHandoffManifest,
        "destination_context.json": DestinationContext,
        "assembly_manifest.json": AssemblyManifest,
        "material_mapping.json": MaterialMappingManifest,
        "import_checklist.json": ImportChecklist,
        "destination_handoff_validation.json": DestinationHandoffValidation,
        "handoff_report.manifest.json": HandoffReportManifest,
    }
    model = model_by_name.get(path.name)
    if model is not None:
        model.model_validate_json(_read_text(path))


def _validate_external_intake_contract(path: Path) -> None:
    """Validate recognized external-intake contracts without normalizing or repairing them."""

    model: type[Any] | None = None
    if "plans" in path.parts:
        model_by_name: dict[str, type[Any]] = {
            "plan.json": ExternalAssetIntakePlan,
            "approval.json": ExternalAssetIntakeApproval,
        }
        model = model_by_name.get(path.name)
    else:
        model_by_name = {
            "external_asset_manifest.json": ExternalAssetManifest,
            "normalization_receipt.json": ExternalNormalizationReceipt,
            "validation.json": ExternalAssetIntakeValidation,
        }
        model = model_by_name.get(path.name)
    if model is not None:
        model.model_validate_json(_read_text(path))


def _validate_interior_qa_contract(path: Path) -> None:
    """Validate recognized multi-view interior QA JSON during read-only audit."""

    model_by_name: dict[str, type[Any]] = {
        "source_inventory.json": InteriorQASourceInventory,
        "plan.json": InteriorQAPlan,
        "plan_approval.json": InteriorQAPlanApproval,
        "render_manifest.json": InteriorQARenderManifest,
        "interior_qa_report.json": InteriorQAReport,
        "revision_candidates.json": InteriorQARevisionCandidates,
        "latest.json": InteriorQALatest,
    }
    model = model_by_name.get(path.name)
    if model is not None:
        model.model_validate_json(_read_text(path))


def _validate_visual_convergence_contract(path: Path) -> None:
    """Validate recognized bounded-convergence JSON without changing session evidence."""

    model_by_name: dict[str, type[Any]] = {
        "plan.json": VisualConvergencePlan,
        "approval.json": VisualConvergenceApproval,
        "selection.json": ConvergenceCandidateSelection,
        "execution_authorization.json": VisualConvergenceIterationAuthorization,
        "authorization.json": VisualConvergenceIterationAuthorization,
        "receipt.json": VisualConvergenceIteration,
        "cancellation_receipt.json": VisualConvergenceCancellation,
        "convergence_report.json": VisualConvergenceReport,
        "convergence_report.manifest.json": VisualConvergenceReportManifest,
    }
    model = model_by_name.get(path.name)
    if model is not None:
        model.model_validate_json(_read_text(path))


def _scan_job_files(
    root: Path,
    job_id: str,
    scan_counter: list[int],
    scan_limit: int,
) -> list[AuditFinding]:
    """Bound file traversal, reject link escapes, and parse every job-owned JSON artifact."""

    findings: list[AuditFinding] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        safe_directories: list[str] = []
        for name in sorted(directories):
            child = current_path / name
            if _is_link_like(child):
                findings.append(
                    _finding(
                        "LINK_ESCAPE_RISK",
                        "error",
                        "Link-like directories are not followed during release audit.",
                        job_id=job_id,
                        path=_workspace_relative_lexical(child),
                        remediation="Replace the link with contained files or audit it manually.",
                    )
                )
            else:
                safe_directories.append(name)
        directories[:] = safe_directories
        for name in sorted(filenames):
            path = current_path / name
            scan_counter[0] += 1
            if scan_counter[0] > scan_limit:
                findings.append(
                    _finding(
                        "SCAN_LIMIT_EXCEEDED",
                        "error",
                        f"Workspace audit exceeded its {scan_limit} file bound.",
                        job_id=job_id,
                        remediation="Increase stabilization.audit_scan_limit explicitly.",
                    )
                )
                return findings
            if _is_link_like(path):
                findings.append(
                    _finding(
                        "LINK_ESCAPE_RISK",
                        "error",
                        "Link-like files are not read during release audit.",
                        job_id=job_id,
                        path=_workspace_relative_lexical(path),
                    )
                )
                continue
            relative = _workspace_relative(path)
            if name.endswith(".tmp") or ".creating-" in name:
                findings.append(
                    _finding(
                        "INTERRUPTED_TEMP_ARTIFACT",
                        "warning",
                        "A temporary artifact may indicate an interrupted atomic write.",
                        job_id=job_id,
                        path=relative,
                        remediation="Inspect the owning operation before removing the file.",
                    )
                )
            if path.suffix.casefold() != ".json":
                continue
            try:
                json.loads(_read_text(path))
                if "workflows" in path.parts:
                    _validate_workflow_contract(path)
                if "handoffs" in path.parts or "destination_handoffs" in path.parts:
                    _validate_handoff_contract(path)
                if "intake" in path.parts:
                    _validate_external_intake_contract(path)
                if "qa" in path.parts and "interior" in path.parts:
                    _validate_interior_qa_contract(path)
                if "qa" in path.parts and "convergence" in path.parts:
                    _validate_visual_convergence_contract(path)
                if "production" in path.parts:
                    from ..production.validation import validate_production_contract_file

                    validate_production_contract_file(path)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                findings.append(
                    _finding(
                        "INVALID_JSON_CONTRACT",
                        "error",
                        "JSON evidence is unreadable or violates its known "
                        f"contract: {type(exc).__name__}.",
                        job_id=job_id,
                        path=relative,
                        remediation=(
                            "Restore this artifact from immutable history or rerun its "
                            "owning stage."
                        ),
                    )
                )
    return findings


def _audit_external_static_asset_intake(
    root: Path,
    job_id: str,
    metadata: dict[str, Any],
) -> list[AuditFinding]:
    """Verify exact intake hashes and source provenance without repairing evidence."""

    findings: list[AuditFinding] = []
    manifest_path = root / "intake" / "external_asset_manifest.json"
    is_external_job = metadata.get("job_kind") == "external_static_asset"
    if not manifest_path.is_file():
        if is_external_job:
            findings.append(
                _finding(
                    "EXTERNAL_INTAKE_INCOMPLETE",
                    "warning",
                    "External static-asset intake has not published a normalized manifest.",
                    job_id=job_id,
                    path=_workspace_relative(root / "intake"),
                    remediation=(
                        "Review the exact intake plan and normalize only after its SHA-256 "
                        "approval."
                    ),
                )
            )
        return findings
    if not is_external_job:
        findings.append(
            _finding(
                "EXTERNAL_INTAKE_KIND_MISMATCH",
                "error",
                "An external manifest exists but job.json does not declare external_static_asset.",
                job_id=job_id,
                path=_workspace_relative(manifest_path),
            )
        )
        return findings
    try:
        manifest = ExternalAssetManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if manifest.job_id != job_id:
            raise ValueError("external manifest job_id differs from its directory")
        artifacts = [
            manifest.source,
            *manifest.dependencies,
            manifest.intake_plan,
            manifest.intake_approval,
            manifest.normalized_blend,
            manifest.normalization_evidence,
            manifest.material_plan,
            *manifest.shader_recipes,
        ]
        for artifact in artifacts:
            artifact_path = resolve_inside(root, artifact.path, artifact.kind)
            if (
                _is_link_like(artifact_path)
                or not artifact_path.is_file()
                or sha256_file(artifact_path) != artifact.sha256
            ):
                raise ValueError(f"stale or missing manifest artifact: {artifact.path}")
        receipt_path = root / "intake" / "normalization_receipt.json"
        receipt = ExternalNormalizationReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        if (
            receipt.job_id != job_id
            or receipt.manifest_sha256 != sha256_file(manifest_path)
            or receipt.plan_sha256 != manifest.intake_plan.sha256
            or receipt.approval_sha256 != manifest.intake_approval.sha256
            or receipt.source_sha256 != manifest.source.sha256
            or receipt.normalized_blend_sha256 != manifest.normalized_blend.sha256
            or receipt.build_fingerprint != manifest.build_fingerprint
            or receipt.source_contract_fingerprint
            != manifest.source_contract_fingerprint
        ):
            raise ValueError("normalization receipt does not match the external manifest")
        approval_path = resolve_inside(
            root,
            manifest.intake_approval.path,
            "external intake approval",
        )
        approval = ExternalAssetIntakeApproval.model_validate_json(
            approval_path.read_text(encoding="utf-8")
        )
        if not approval.used or approval.plan_sha256 != manifest.intake_plan.sha256:
            raise ValueError("external intake approval was not consumed by this exact plan")
        provenance = collect_external_build_provenance(root, job_id)
        if provenance.get("fingerprint") != manifest.build_fingerprint:
            raise ValueError("external build fingerprint differs from the manifest")
        validation_path = root / "intake" / "validation.json"
        validation = ExternalAssetIntakeValidation.model_validate_json(
            validation_path.read_text(encoding="utf-8")
        )
        if not validation.ok or validation.plan_id != approval.plan_id:
            raise ValueError("external intake validation is absent, failed, or mismatched")
    except (OSError, ValueError, RuntimeError) as exc:
        findings.append(
            _finding(
                "EXTERNAL_INTAKE_STALE_OR_TAMPERED",
                "error",
                f"External static-asset intake evidence is not current: {exc}",
                job_id=job_id,
                path=_workspace_relative(manifest_path),
                remediation=(
                    "Restore the immutable intake evidence or create a new intake job; do "
                    "not repair hashes in place."
                ),
            )
        )
    return findings


def _audit_production_dispatches(root: Path, job_id: str) -> list[AuditFinding]:
    """Verify V0.9 production bundles and their exact workflow/prompt receipt bindings."""

    dispatches_root = root / "production" / "dispatches"
    if not dispatches_root.exists():
        return []
    if not dispatches_root.is_dir() or _is_link_like(dispatches_root):
        return [
            _finding(
                "PRODUCTION_DISPATCH_ROOT_INVALID",
                "error",
                "Production dispatch root is not a contained directory.",
                job_id=job_id,
                path=_workspace_relative_lexical(dispatches_root),
            )
        ]
    from ..production.validation import validate_dispatch_bundle

    findings: list[AuditFinding] = []
    for dispatch_root in sorted(dispatches_root.iterdir(), key=lambda item: item.name):
        if not dispatch_root.is_dir() or _is_link_like(dispatch_root):
            findings.append(
                _finding(
                    "PRODUCTION_DISPATCH_DIRECTORY_INVALID",
                    "error",
                    "Production dispatch entry is missing, non-directory, or link-like.",
                    job_id=job_id,
                    path=_workspace_relative_lexical(dispatch_root),
                )
            )
            continue
        try:
            validate_dispatch_bundle(root, dispatch_root.name)
        except (OSError, RuntimeError, ValueError) as exc:
            findings.append(
                _finding(
                    "PRODUCTION_DISPATCH_INTEGRITY_FAILED",
                    "error",
                    "Production dispatch hashes or immutable receipt links are invalid: "
                    f"{type(exc).__name__}.",
                    job_id=job_id,
                    path=_workspace_relative(dispatch_root),
                    remediation=(
                        "Preserve the evidence and create a new dispatch from current canonical "
                        "inputs; never rewrite the damaged dispatch in place."
                    ),
                )
            )
    return findings


def _audit_latest_workflow(root: Path, job_id: str) -> list[AuditFinding]:
    """Verify that a latest-workflow pointer resolves to an existing workflow directory."""

    latest = root / "workflows" / "latest.json"
    if not latest.is_file():
        return []
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
        workflow_id = payload.get("workflow_id")
        if not isinstance(workflow_id, str) or not _PORTABLE_ID_RE.fullmatch(workflow_id):
            raise ValueError("latest workflow_id is missing or invalid")
        target = root / "workflows" / workflow_id
        if not (target / "request.json").is_file() or not (target / "plan.json").is_file():
            raise FileNotFoundError("latest workflow contract directory is incomplete")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [
            _finding(
                "DANGLING_WORKFLOW_POINTER",
                "error",
                f"Latest workflow pointer is invalid: {type(exc).__name__}.",
                job_id=job_id,
                path=_workspace_relative(latest),
                remediation="Restore latest.json from the current workflow state.",
            )
        ]
    return []


def _audit_latest_interior_qa(root: Path, job_id: str) -> list[AuditFinding]:
    """Verify the latest interior QA pointer, hashes, and contained dependencies."""

    latest_path = root / "qa" / "interior" / "latest.json"
    if not latest_path.is_file():
        return []
    try:
        latest = InteriorQALatest.model_validate_json(
            latest_path.read_text(encoding="utf-8")
        )
        if latest.job_id != job_id:
            raise ValueError("interior QA latest pointer job_id mismatch")
        relative_paths = [
            latest.plan,
            latest.approval,
            latest.source_inventory,
            latest.render_manifest,
            latest.report,
            latest.revision_candidates,
            *latest.contact_sheets,
        ]
        resolved: dict[str, Path] = {}
        for relative in relative_paths:
            path = (root / relative).resolve()
            path.relative_to(root.resolve())
            if not path.is_file():
                raise FileNotFoundError(relative)
            resolved[relative] = path
        if sha256_file(resolved[latest.plan]) != latest.plan_sha256:
            raise ValueError("latest interior QA plan hash is stale")
        if sha256_file(resolved[latest.approval]) != latest.approval_sha256:
            raise ValueError("latest interior QA approval hash is stale")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [
            _finding(
                "INTERIOR_QA_LATEST_INVALID",
                "error",
                "Latest interior QA pointer or dependency is invalid: "
                f"{type(exc).__name__}.",
                job_id=job_id,
                path=_workspace_relative(latest_path),
                remediation="Restore the immutable run evidence or select a current run.",
            )
        ]
    return []


def _resolve_convergence_artifact(
    root: Path,
    artifact: HashBoundConvergenceArtifact,
) -> Path:
    """Resolve and verify one hash-bound convergence artifact inside its owning job."""

    path = (root / artifact.relative_path).resolve()
    path.relative_to(root.resolve())
    if _is_link_like(path) or not path.is_file():
        raise FileNotFoundError(artifact.relative_path)
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"visual convergence artifact hash mismatch: {artifact.relative_path}")
    return path


def _canonical_json_sha256(value: Any) -> str:
    """Hash JSON-compatible convergence evidence with deterministic serialization."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _current_convergence_input_fingerprint(root: Path) -> str:
    """Recreate the bounded-session fingerprint over immutable input-file hashes."""

    input_root = root / "input"
    if not input_root.is_dir() or _is_link_like(input_root):
        raise FileNotFoundError("input")
    hashes = {
        path.relative_to(input_root).as_posix(): sha256_file(path)
        for path in sorted(input_root.rglob("*"))
        if path.is_file() and not _is_link_like(path)
    }
    return _canonical_json_sha256(hashes)


def _convergence_qa_report(
    root: Path,
    run_id: str,
    expected_sha256: str,
) -> tuple[Path, VisualQAReport]:
    """Verify one exact immutable QA report referenced by a convergence contract."""

    path = root / "qa" / "runs" / run_id / "visual_qa_report.json"
    if _is_link_like(path) or not path.is_file():
        raise FileNotFoundError(f"qa/runs/{run_id}/visual_qa_report.json")
    if sha256_file(path) != expected_sha256:
        raise ValueError(f"visual convergence QA report hash mismatch: {run_id}")
    report = VisualQAReport.model_validate_json(path.read_text(encoding="utf-8"))
    if report.run_id != run_id:
        raise ValueError(f"visual convergence QA report run_id mismatch: {run_id}")
    return path, report


def _audit_complete_convergence_qa(
    root: Path,
    *,
    job_id: str,
    run_id: str,
    scene_spec_sha256: str,
    report_sha256: str,
    candidates_sha256: str,
    build_fingerprint: str | None = None,
) -> dict[str, str]:
    """Verify one convergence QA request, exact seven passes, sources, report, and candidates."""

    (
        _report_path,
        _candidates_path,
        _report,
        _candidates,
        artifacts,
    ) = _audit_qa_authoritative_evidence(
        root=root,
        job_id=job_id,
        run_id=run_id,
        expected_scene_spec_sha256=scene_spec_sha256,
        expected_report_sha256=report_sha256,
        expected_candidates_sha256=candidates_sha256,
        expected_build_fingerprint=build_fingerprint,
    )
    return {
        artifact.relative_path: artifact.sha256
        for artifact in artifacts
    }


def _collect_complete_convergence_qa_artifacts(
    root: Path,
    *,
    job_id: str,
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> dict[str, str]:
    """Collect complete provenance for every QA run referenced by one session."""

    initial_candidates_path = (
        root
        / "qa"
        / "runs"
        / plan.initial_qa_run_id
        / "revision_candidates.json"
    )
    if not initial_candidates_path.is_file():
        raise ValueError("terminal visual convergence initial candidates are missing")
    artifacts = _audit_complete_convergence_qa(
        root,
        job_id=job_id,
        run_id=plan.initial_qa_run_id,
        scene_spec_sha256=plan.initial_scene_spec_sha256,
        report_sha256=plan.initial_qa_report_sha256,
        candidates_sha256=(
            plan.initial_candidates_sha256 or sha256_file(initial_candidates_path)
        ),
        build_fingerprint=plan.initial_build_fingerprint,
    )
    for receipt, _receipt_sha256, _receipt_path in receipts:
        artifacts.update(
            _audit_complete_convergence_qa(
                root,
                job_id=job_id,
                run_id=receipt.source_qa_run_id,
                scene_spec_sha256=receipt.base_scene_spec_sha256,
                report_sha256=receipt.source_qa_report_sha256,
                candidates_sha256=receipt.candidates_sha256,
                build_fingerprint=receipt.source_build_fingerprint,
            )
        )
        result_qa_fields = (
            receipt.result_qa_run_id,
            receipt.result_qa_report_sha256,
            receipt.result_candidates_sha256,
        )
        if all(value is not None for value in result_qa_fields):
            if receipt.result_scene_spec_sha256 is None:
                raise ValueError(
                    "terminal visual convergence result QA lacks a SceneSpec snapshot"
                )
            artifacts.update(
                _audit_complete_convergence_qa(
                    root,
                    job_id=job_id,
                    run_id=receipt.result_qa_run_id or "",
                    scene_spec_sha256=receipt.result_scene_spec_sha256,
                    report_sha256=receipt.result_qa_report_sha256 or "",
                    candidates_sha256=receipt.result_candidates_sha256 or "",
                    build_fingerprint=receipt.result_build_fingerprint,
                )
            )
        elif any(value is not None for value in result_qa_fields):
            raise ValueError(
                "terminal visual convergence result QA evidence is partial"
            )
    return artifacts


def _load_convergence_receipts(
    root: Path,
    session_root: Path,
) -> list[tuple[VisualConvergenceIteration, str, Path]]:
    """Load contiguous iteration directories and reject incomplete receipt evidence."""

    receipts: list[tuple[VisualConvergenceIteration, str, Path]] = []
    iterations_root = session_root / "iterations"
    if not iterations_root.exists():
        return receipts
    if not iterations_root.is_dir() or _is_link_like(iterations_root):
        raise ValueError("visual convergence iterations path is not a contained directory")
    iteration_dirs: list[Path] = []
    for child in sorted(iterations_root.iterdir()):
        if _is_link_like(child) or not child.is_dir():
            raise ValueError("visual convergence iterations contain an unexpected entry")
        iteration_dirs.append(child)
    for expected_index, iteration_root in enumerate(iteration_dirs, start=1):
        if iteration_root.name != f"{expected_index:03d}":
            raise ValueError("visual convergence iteration directories are not contiguous")
        path = iteration_root / "receipt.json"
        if not path.is_file():
            raise ValueError("visual convergence iteration directory has no receipt")
        if _is_link_like(path):
            raise ValueError("visual convergence receipt is link-like")
        receipt = VisualConvergenceIteration.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if iteration_root.name != f"{receipt.iteration_index:03d}":
            raise ValueError("visual convergence receipt directory/index mismatch")
        receipts.append((receipt, sha256_file(path), path))
    return receipts


def _verify_terminal_convergence_inputs(
    root: Path,
    plan: VisualConvergencePlan,
    *,
    current_fingerprint_matches: bool,
) -> str | None:
    """Verify historical input evidence while permitting later additive job views."""

    initial_hashes = getattr(plan, "initial_input_hashes", None)
    if not initial_hashes:
        return "legacy_unverifiable"
    input_root = (root / "input").resolve()
    for relative_path, expected_sha256 in sorted(initial_hashes.items()):
        path = (input_root / relative_path).resolve()
        try:
            path.relative_to(input_root)
        except ValueError as exc:
            raise ValueError("historical convergence input path escapes input root") from exc
        if not path.is_file() or _is_link_like(path):
            raise FileNotFoundError(f"input/{relative_path}")
        if sha256_file(path) != expected_sha256:
            raise ValueError(
                f"historical convergence input hash mismatch: {relative_path}"
            )
    return None if current_fingerprint_matches else "verified_additions"


def _verify_current_convergence_candidates(
    root: Path,
    plan: VisualConvergencePlan,
    *,
    qa_run_id: str,
    qa_report_sha256: str,
    canonical_scene_spec_sha256: str,
) -> str:
    """Validate and return the candidate hash required to resume an active session."""

    candidates_path = (
        root / "qa" / "runs" / qa_run_id / "revision_candidates.json"
    )
    if not candidates_path.is_file() or _is_link_like(candidates_path):
        raise FileNotFoundError(f"qa/runs/{qa_run_id}/revision_candidates.json")
    candidates = RevisionCandidates.model_validate_json(
        candidates_path.read_text(encoding="utf-8")
    )
    if (
        candidates.job_id != plan.job_id
        or candidates.base_spec_sha256 != canonical_scene_spec_sha256
        or candidates.camera_fingerprint != plan.camera_fingerprint
        or candidates.source_report_sha256 != qa_report_sha256
    ):
        raise ValueError("active visual convergence candidates are stale or misbound")
    return sha256_file(candidates_path)


def _audit_convergence_build_snapshot(
    root: Path,
    path: Path,
    *,
    expected_file_sha256: str,
    expected_fingerprint: str,
    expected_scene_spec_sha256: str | None = None,
    expected_camera_fingerprint: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Verify one immutable build snapshot, its fingerprint, and direct contract bindings."""

    if _is_link_like(path) or not path.is_file():
        raise FileNotFoundError(path.resolve().relative_to(root.resolve()).as_posix())
    if sha256_file(path) != expected_file_sha256:
        raise ValueError("visual convergence build-provenance snapshot hash mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("visual convergence build provenance must be a JSON object")
    declared_fingerprint = payload.get("fingerprint")
    unsigned = dict(payload)
    unsigned.pop("fingerprint", None)
    if (
        declared_fingerprint != expected_fingerprint
        or _canonical_json_sha256(unsigned) != expected_fingerprint
    ):
        raise ValueError("visual convergence build-provenance fingerprint mismatch")
    if (
        expected_scene_spec_sha256 is not None
        and payload.get("scene_spec_sha256") != expected_scene_spec_sha256
    ):
        raise ValueError("visual convergence build provenance SceneSpec binding mismatch")
    if (
        expected_camera_fingerprint is not None
        and payload.get("camera_fingerprint") != expected_camera_fingerprint
    ):
        raise ValueError("visual convergence build provenance camera binding mismatch")
    return path.resolve().relative_to(root.resolve()).as_posix(), payload


def _validate_convergence_build_transition(
    source: dict[str, Any],
    result: dict[str, Any],
    *,
    expected_source_scene_spec_sha256: str,
    expected_result_scene_spec_sha256: str,
    expected_camera_fingerprint: str,
) -> None:
    """Allow only the approved SceneSpec hash to change between two build snapshots."""

    if (
        source.get("scene_spec_sha256")
        != expected_source_scene_spec_sha256
        or result.get("scene_spec_sha256")
        != expected_result_scene_spec_sha256
    ):
        raise ValueError("visual convergence build transition SceneSpec binding mismatch")
    if (
        source.get("camera_fingerprint") != expected_camera_fingerprint
        or result.get("camera_fingerprint") != expected_camera_fingerprint
    ):
        raise ValueError("visual convergence build transition camera binding mismatch")
    source_contracts = dict(source)
    result_contracts = dict(result)
    for payload in (source_contracts, result_contracts):
        payload.pop("fingerprint", None)
        payload.pop("scene_spec_sha256", None)
    if source_contracts != result_contracts:
        raise ValueError(
            "visual convergence build transition changed geometry, material, shader, "
            "texture, camera, interior, or reference-scope provenance"
        )


def _load_convergence_constraint_evidence(
    path: Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    """Load and validate one exact before/after measured-constraint snapshot."""

    if _is_link_like(path) or not path.is_file():
        raise FileNotFoundError(path)
    if sha256_file(path) != expected_sha256:
        raise ValueError("visual convergence constraint evidence hash mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("visual convergence constraint evidence must be an object")
    failures = payload.get("failures")
    results = payload.get("results")
    if (
        not isinstance(failures, int)
        or isinstance(failures, bool)
        or failures < 0
        or not isinstance(results, list)
    ):
        raise ValueError("visual convergence constraint evidence is malformed")
    validated = [ConstraintResult.model_validate(item) for item in results]
    expected_failures = sum(
        result.status in {"failed", "missing"} for result in validated
    )
    if failures != expected_failures:
        raise ValueError(
            "visual convergence constraint failure count differs from its results"
        )
    compare_constraint_results(results, results)
    return payload


def _audit_initial_convergence_snapshots(
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
) -> dict[str, str]:
    """Verify new-plan SceneSpec, build, candidates, and constraint baseline evidence."""

    if plan.initial_candidates_sha256 is None:
        return {}
    required_values = (
        plan.initial_build_fingerprint,
        plan.initial_build_provenance_sha256,
        plan.initial_constraints_present,
    )
    if any(value is None for value in required_values):
        raise ValueError("new visual convergence plan has partial baseline bindings")
    scene_path = session_root / "initial_scene_spec.json"
    if (
        _is_link_like(scene_path)
        or not scene_path.is_file()
        or sha256_file(scene_path) != plan.initial_scene_spec_sha256
    ):
        raise ValueError("visual convergence initial SceneSpec snapshot mismatch")
    build_path = session_root / "initial_build_provenance.json"
    build_relative, _build_payload = _audit_convergence_build_snapshot(
        root,
        build_path,
        expected_file_sha256=plan.initial_build_provenance_sha256 or "",
        expected_fingerprint=plan.initial_build_fingerprint or "",
        expected_scene_spec_sha256=plan.initial_scene_spec_sha256,
        expected_camera_fingerprint=plan.camera_fingerprint,
    )
    candidates_path = (
        root
        / "qa"
        / "runs"
        / plan.initial_qa_run_id
        / "revision_candidates.json"
    )
    if (
        _is_link_like(candidates_path)
        or not candidates_path.is_file()
        or sha256_file(candidates_path) != plan.initial_candidates_sha256
    ):
        raise ValueError("visual convergence initial candidate bundle mismatch")
    artifacts = {
        scene_path.resolve().relative_to(root.resolve()).as_posix(): (
            plan.initial_scene_spec_sha256
        ),
        build_relative: plan.initial_build_provenance_sha256 or "",
        candidates_path.resolve().relative_to(root.resolve()).as_posix(): (
            plan.initial_candidates_sha256
        ),
    }
    if plan.host_safety_envelope_sha256 is not None:
        _require_host_safety_envelope(root, session_root, plan)
        host_safety_path = session_root / "host_safety_envelope.json"
        artifacts[
            host_safety_path.resolve().relative_to(root.resolve()).as_posix()
        ] = plan.host_safety_envelope_sha256
    constraints_path = session_root / "initial_constraints.json"
    if plan.initial_constraints_present:
        if (
            plan.initial_constraints_sha256 is None
            or _is_link_like(constraints_path)
            or not constraints_path.is_file()
            or sha256_file(constraints_path) != plan.initial_constraints_sha256
        ):
            raise ValueError("visual convergence initial constraint snapshot mismatch")
        artifacts[
            constraints_path.resolve().relative_to(root.resolve()).as_posix()
        ] = plan.initial_constraints_sha256
    elif constraints_path.exists():
        raise ValueError("unexpected visual convergence constraint snapshot")
    return artifacts


def _recompute_convergence_selection(
    plan: VisualConvergencePlan,
    candidates: RevisionCandidates,
    selection: ConvergenceCandidateSelection,
    *,
    candidates_sha256: str,
    base_scene_spec_path: Path,
) -> None:
    """Recompute host candidate selection from the exact approved policy and base spec."""

    expected = select_convergence_candidates(
        plan,
        candidates,
        candidates_sha256=candidates_sha256,
        expected_base_scene_spec_sha256=selection.base_scene_spec_sha256,
        expected_source_qa_report_sha256=selection.source_qa_report_sha256,
        baseline_values=_candidate_baselines(base_scene_spec_path, candidates),
    )
    if selection.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise ValueError(
            "visual convergence candidate selection exceeds or differs from "
            "the exact approved envelope"
        )


def _validate_convergence_iteration_outcome(
    plan: VisualConvergencePlan,
    receipt: VisualConvergenceIteration,
    *,
    recomputed_constraint_regression_count: int | None = None,
) -> None:
    """Re-evaluate runtime predicates, preferring independently derived constraints."""

    if receipt.status not in {"accepted", "rolled_back"}:
        return
    if (
        receipt.after_direct_score is None
        or receipt.after_silhouette_iou is None
        or receipt.score_delta is None
    ):
        raise ValueError("executed visual convergence receipt lacks result metrics")
    gain_satisfied = (
        receipt.score_delta + 1e-9 >= plan.minimum_iteration_gain
    )
    silhouette_preserved = (
        receipt.after_silhouette_iou + 1e-9
        >= receipt.before_silhouette_iou
    )
    effective_regression_count = (
        receipt.constraint_regression_count
        if recomputed_constraint_regression_count is None
        else recomputed_constraint_regression_count
    )
    if (
        recomputed_constraint_regression_count is not None
        and receipt.constraint_regression_count
        != recomputed_constraint_regression_count
    ):
        raise ValueError(
            "visual convergence constraint-regression count differs from exact evidence"
        )
    constraints_preserved = effective_regression_count == 0
    predicates_accepted = (
        gain_satisfied and silhouette_preserved and constraints_preserved
    )
    if receipt.status == "accepted" and not predicates_accepted:
        raise ValueError(
            "accepted visual convergence receipt violates runtime acceptance predicates"
        )
    if receipt.status == "rolled_back" and predicates_accepted:
        raise ValueError(
            "rolled-back visual convergence receipt falsely reports all predicates passing"
        )
    constraint_reason = "measured_constraint_regression"
    if effective_regression_count and constraint_reason not in receipt.reason_codes:
        raise ValueError(
            "visual convergence constraint regression lacks explicit receipt evidence"
        )
    if (
        not effective_regression_count
        and constraint_reason in receipt.reason_codes
    ):
        raise ValueError(
            "visual convergence receipt claims a constraint regression without evidence"
        )


def _receipt_chain_requires_terminal_report(
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
    session_root: Path,
) -> bool:
    """Identify receipt or cancellation evidence that has already consumed the session."""

    if any(
        (session_root / name).exists()
        for name in (
            "cancellation_receipt.json",
            "convergence_report.manifest.json",
            "convergence_report.pdf",
            "final_scene_spec.json",
            "final_build_provenance.json",
        )
    ):
        return True
    if not receipts:
        return False
    final = receipts[-1][0]
    if final.status != "accepted" or len(receipts) >= plan.max_iterations:
        return True
    return (
        final.after_direct_score is not None
        and final.after_silhouette_iou is not None
        and final.after_direct_score >= plan.target_direct_score
        and final.after_silhouette_iou >= plan.target_silhouette_iou
    )


def _uses_complete_convergence_terminal_contract(
    plan: VisualConvergencePlan,
) -> bool:
    """Use immutable plan input bindings as the discriminator for new terminals."""

    return bool(plan.initial_input_hashes)


def _validate_terminal_convergence_semantics(
    report: VisualConvergenceReport,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> None:
    """Cross-check target, reason, review, and final-receipt terminal semantics."""

    scores_reached = (
        report.final_direct_score >= report.target_direct_score
        and report.final_silhouette_iou >= report.target_silhouette_iou
    )
    if report.target_reached != scores_reached:
        raise ValueError("terminal visual convergence target flag is false")
    if (report.termination_reason == "target_reached") != report.target_reached:
        raise ValueError("terminal visual convergence target reason is inconsistent")
    manual_review_reasons = {
        "plateau",
        "no_eligible_candidates",
        "manual_review_required",
        "iteration_budget_exhausted",
        "constraint_regression",
        "stale_or_tampered",
        "failed",
    }
    if report.manual_review_required != (
        report.termination_reason in manual_review_reasons
    ):
        raise ValueError(
            "terminal visual convergence manual-review semantics are inconsistent"
        )
    if not receipts:
        if report.termination_reason not in {"target_reached", "cancelled"}:
            raise ValueError(
                "empty visual convergence terminal has an impossible reason"
            )
        return
    final_status = receipts[-1][0].status
    allowed_reasons = {
        "accepted": {"target_reached", "iteration_budget_exhausted", "cancelled"},
        "rolled_back": {"plateau", "constraint_regression"},
        "manual_review_required": {
            "manual_review_required",
            "no_eligible_candidates",
        },
        "failed": {"failed", "stale_or_tampered"},
    }[final_status]
    if report.termination_reason not in allowed_reasons:
        raise ValueError(
            "terminal visual convergence reason conflicts with final receipt"
        )


def _current_convergence_qa_identity(
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> tuple[str, str]:
    """Recover the current QA run and report hash from accepted iteration receipts."""

    run_id = plan.initial_qa_run_id
    report_sha256 = plan.initial_qa_report_sha256
    for receipt, _receipt_sha256, _receipt_path in receipts:
        if receipt.status == "accepted":
            if (
                receipt.result_qa_run_id is None
                or receipt.result_qa_report_sha256 is None
            ):
                raise ValueError("accepted convergence receipt lacks result QA evidence")
            run_id = receipt.result_qa_run_id
            report_sha256 = receipt.result_qa_report_sha256
    return run_id, report_sha256


def _current_convergence_build_fingerprint(
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> str | None:
    """Recover the build fingerprint that corresponds to the accepted canonical chain."""

    fingerprint = plan.initial_build_fingerprint
    for receipt, _receipt_sha256, _receipt_path in receipts:
        if receipt.status == "accepted":
            if receipt.result_build_fingerprint is None and fingerprint is not None:
                raise ValueError(
                    "accepted visual convergence receipt lacks result build provenance"
                )
            fingerprint = receipt.result_build_fingerprint
    return fingerprint


def _audit_terminal_convergence_build_snapshots(
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    report: VisualConvergenceReport,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> dict[str, str]:
    """Verify fixed initial/final build snapshots referenced by a new terminal report."""

    if plan.initial_build_fingerprint is None:
        return {}
    if (
        report.initial_build_provenance_snapshot is None
        or report.final_build_provenance_snapshot is None
        or report.initial_build_fingerprint != plan.initial_build_fingerprint
    ):
        raise ValueError("terminal visual convergence build snapshot bindings are incomplete")
    expected_final_fingerprint = _current_convergence_build_fingerprint(
        plan,
        receipts,
    )
    if report.final_build_fingerprint != expected_final_fingerprint:
        raise ValueError("terminal visual convergence final build fingerprint mismatch")
    initial_path = _resolve_convergence_artifact(
        root,
        report.initial_build_provenance_snapshot,
    )
    final_path = _resolve_convergence_artifact(
        root,
        report.final_build_provenance_snapshot,
    )
    if initial_path != (session_root / "initial_build_provenance.json").resolve():
        raise ValueError("terminal convergence initial build snapshot path mismatch")
    if final_path != (session_root / "final_build_provenance.json").resolve():
        raise ValueError("terminal convergence final build snapshot path mismatch")
    _initial_relative, initial_payload = _audit_convergence_build_snapshot(
        root,
        initial_path,
        expected_file_sha256=report.initial_build_provenance_snapshot.sha256,
        expected_fingerprint=plan.initial_build_fingerprint,
        expected_scene_spec_sha256=plan.initial_scene_spec_sha256,
        expected_camera_fingerprint=plan.camera_fingerprint,
    )
    _final_relative, final_payload = _audit_convergence_build_snapshot(
        root,
        final_path,
        expected_file_sha256=report.final_build_provenance_snapshot.sha256,
        expected_fingerprint=expected_final_fingerprint or "",
        expected_scene_spec_sha256=report.final_scene_spec_sha256,
        expected_camera_fingerprint=plan.camera_fingerprint,
    )
    _validate_convergence_build_transition(
        initial_payload,
        final_payload,
        expected_source_scene_spec_sha256=plan.initial_scene_spec_sha256,
        expected_result_scene_spec_sha256=report.final_scene_spec_sha256,
        expected_camera_fingerprint=plan.camera_fingerprint,
    )
    return {
        report.initial_build_provenance_snapshot.relative_path: (
            report.initial_build_provenance_snapshot.sha256
        ),
        report.final_build_provenance_snapshot.relative_path: (
            report.final_build_provenance_snapshot.sha256
        ),
    }


def _audit_terminal_convergence_cancellation(
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    report: VisualConvergenceReport,
    *,
    plan_sha256: str,
    approval_sha256: str,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> dict[str, str]:
    """Verify a user cancellation receipt against the exact current session chain."""

    cancellation_path = session_root / "cancellation_receipt.json"
    if report.termination_reason != "cancelled":
        if cancellation_path.exists() or report.cancellation_receipt is not None:
            raise ValueError("non-cancelled convergence terminal carries cancellation evidence")
        return {}
    if report.cancellation_receipt is None:
        raise ValueError("cancelled convergence terminal lacks cancellation evidence")
    resolved = _resolve_convergence_artifact(root, report.cancellation_receipt)
    if resolved != cancellation_path.resolve():
        raise ValueError("visual convergence cancellation receipt path mismatch")
    cancellation = VisualConvergenceCancellation.model_validate_json(
        cancellation_path.read_text(encoding="utf-8")
    )
    current_qa_run_id, current_qa_sha256 = _current_convergence_qa_identity(
        plan,
        receipts,
    )
    current_candidates_path = (
        root
        / "qa"
        / "runs"
        / current_qa_run_id
        / "revision_candidates.json"
    )
    expected_previous = receipts[-1][1] if receipts else None
    checks = {
        "session_id": (cancellation.session_id, plan.session_id),
        "job_id": (cancellation.job_id, plan.job_id),
        "plan_sha256": (cancellation.plan_sha256, plan_sha256),
        "approval_sha256": (cancellation.approval_sha256, approval_sha256),
        "input_fingerprint": (
            cancellation.input_fingerprint,
            plan.input_fingerprint,
        ),
        "canonical_scene_spec_sha256": (
            cancellation.canonical_scene_spec_sha256,
            report.final_scene_spec_sha256,
        ),
        "current_qa_run_id": (
            cancellation.current_qa_run_id,
            current_qa_run_id,
        ),
        "current_qa_report_sha256": (
            cancellation.current_qa_report_sha256,
            current_qa_sha256,
        ),
        "current_candidates_sha256": (
            cancellation.current_candidates_sha256,
            sha256_file(current_candidates_path),
        ),
        "current_build_fingerprint": (
            cancellation.current_build_fingerprint,
            _current_convergence_build_fingerprint(plan, receipts),
        ),
        "previous_iteration_receipt_sha256": (
            cancellation.previous_iteration_receipt_sha256,
            expected_previous,
        ),
    }
    mismatches = sorted(
        label for label, (actual, expected) in checks.items() if actual != expected
    )
    if mismatches:
        raise ValueError(
            f"visual convergence cancellation binding mismatch: {mismatches}"
        )
    return {
        report.cancellation_receipt.relative_path: (
            report.cancellation_receipt.sha256
        )
    }


def _verify_convergence_iteration_artifacts(
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    receipt: VisualConvergenceIteration,
    receipt_sha256: str,
    previous_receipt: VisualConvergenceIteration | None = None,
) -> dict[str, str]:
    """Verify one receipt's immutable support files and return their exact hash map."""

    iteration_root = session_root / "iterations" / f"{receipt.iteration_index:03d}"
    receipt_path = iteration_root / "receipt.json"
    artifacts = {
        receipt_path.resolve().relative_to(root.resolve()).as_posix(): receipt_sha256,
    }
    base_scene_path = iteration_root / "base_scene_spec.json"
    exact_base_snapshot = receipt.base_scene_spec_snapshot_sha256 is not None
    if exact_base_snapshot or plan.initial_candidates_sha256 is not None:
        expected_base_snapshot_sha256 = (
            receipt.base_scene_spec_snapshot_sha256
            or receipt.base_scene_spec_sha256
        )
        if (
            _is_link_like(base_scene_path)
            or not base_scene_path.is_file()
            or sha256_file(base_scene_path) != expected_base_snapshot_sha256
            or expected_base_snapshot_sha256 != receipt.base_scene_spec_sha256
        ):
            raise ValueError("visual convergence base SceneSpec snapshot mismatch")
        artifacts[
            base_scene_path.resolve().relative_to(root.resolve()).as_posix()
        ] = expected_base_snapshot_sha256
    elif base_scene_path.exists():
        if (
            _is_link_like(base_scene_path)
            or not base_scene_path.is_file()
            or sha256_file(base_scene_path) != receipt.base_scene_spec_sha256
        ):
            raise ValueError("legacy visual convergence base SceneSpec snapshot mismatch")
        artifacts[
            base_scene_path.resolve().relative_to(root.resolve()).as_posix()
        ] = receipt.base_scene_spec_sha256
    new_bound_receipt = plan.initial_build_fingerprint is not None
    if new_bound_receipt and (
        receipt.base_scene_spec_snapshot_sha256
        != receipt.base_scene_spec_sha256
        or receipt.source_build_fingerprint is None
    ):
        raise ValueError(
            "new visual convergence receipt lacks its exact base or source build"
        )
    source_build_payload: dict[str, Any] | None = None
    if receipt.source_build_fingerprint is not None:
        if previous_receipt is None:
            source_build_path = session_root / "initial_build_provenance.json"
            source_build_sha256 = plan.initial_build_provenance_sha256
            source_scene_spec_sha256 = plan.initial_scene_spec_sha256
        else:
            source_build_path = (
                session_root
                / "iterations"
                / f"{previous_receipt.iteration_index:03d}"
                / "result_build_provenance.json"
            )
            source_build_sha256 = previous_receipt.result_build_provenance_sha256
            source_scene_spec_sha256 = previous_receipt.result_scene_spec_sha256
        if (
            source_build_sha256 is None
            or source_scene_spec_sha256 is None
            or source_scene_spec_sha256 != receipt.base_scene_spec_sha256
        ):
            raise ValueError("visual convergence source build receipt chain is incomplete")
        source_build_relative, source_build_payload = (
            _audit_convergence_build_snapshot(
                root,
                source_build_path,
                expected_file_sha256=source_build_sha256,
                expected_fingerprint=receipt.source_build_fingerprint,
                expected_scene_spec_sha256=receipt.base_scene_spec_sha256,
                expected_camera_fingerprint=plan.camera_fingerprint,
            )
        )
        artifacts[source_build_relative] = source_build_sha256
    selection_path = iteration_root / "selection.json"
    selection = ConvergenceCandidateSelection.model_validate_json(
        selection_path.read_text(encoding="utf-8")
    )
    selection_file_sha256 = sha256_file(selection_path)
    artifacts[
        selection_path.resolve().relative_to(root.resolve()).as_posix()
    ] = selection_file_sha256
    selection_payload = {
        "schema_version": selection.schema_version,
        "session_id": selection.session_id,
        "job_id": selection.job_id,
        "candidates_sha256": selection.candidates_sha256,
        "selected_candidate_ids": selection.selected_candidate_ids,
        "rejected": [
            item.model_dump(mode="json")
            for item in sorted(
                selection.rejected,
                key=lambda record: record.candidate_id,
            )
        ],
    }
    if (
        selection.session_id != receipt.session_id
        or selection.job_id != receipt.job_id
        or selection_file_sha256 != receipt.selection_sha256
        or selection.candidates_sha256 != receipt.candidates_sha256
        or selection.base_scene_spec_sha256 != receipt.base_scene_spec_sha256
        or selection.source_qa_report_sha256
        != receipt.source_qa_report_sha256
        or selection.selected_candidate_ids != receipt.selected_candidate_ids
    ):
        raise ValueError("visual convergence selection does not match its receipt")
    if selection.selection_sha256 != _canonical_json_sha256(selection_payload):
        raise ValueError("visual convergence selection internal hash mismatch")

    candidates_path = (
        root
        / "qa"
        / "runs"
        / receipt.source_qa_run_id
        / "revision_candidates.json"
    )
    if not candidates_path.is_file() or _is_link_like(candidates_path):
        raise FileNotFoundError(
            f"qa/runs/{receipt.source_qa_run_id}/revision_candidates.json"
        )
    if sha256_file(candidates_path) != receipt.candidates_sha256:
        raise ValueError("visual convergence candidates hash mismatch")
    artifacts[
        candidates_path.resolve().relative_to(root.resolve()).as_posix()
    ] = receipt.candidates_sha256
    candidates = RevisionCandidates.model_validate_json(
        candidates_path.read_text(encoding="utf-8")
    )
    if (
        candidates.job_id != receipt.job_id
        or candidates.base_spec_sha256 != receipt.base_scene_spec_sha256
        or candidates.source_report_sha256 != receipt.source_qa_report_sha256
        or candidates.camera_fingerprint != plan.camera_fingerprint
    ):
        raise ValueError("visual convergence candidates binding mismatch")
    if base_scene_path.is_file():
        _recompute_convergence_selection(
            plan,
            candidates,
            selection,
            candidates_sha256=receipt.candidates_sha256,
            base_scene_spec_path=base_scene_path,
        )
    candidate_ids = {candidate.id for candidate in candidates.candidates}
    decided_ids = set(selection.selected_candidate_ids) | {
        item.candidate_id for item in selection.rejected
    }
    if decided_ids != candidate_ids:
        raise ValueError(
            "visual convergence selection does not cover the exact candidate bundle"
        )
    source_qa_path, source_qa = _convergence_qa_report(
        root,
        receipt.source_qa_run_id,
        receipt.source_qa_report_sha256,
    )
    artifacts[
        source_qa_path.resolve().relative_to(root.resolve()).as_posix()
    ] = receipt.source_qa_report_sha256
    if (
        source_qa.job_id != receipt.job_id
        or source_qa.camera_fingerprint != plan.camera_fingerprint
        or source_qa.direct_metrics.scoring_version != plan.scoring_version
        or source_qa.direct_metrics.overall_direct_score
        != receipt.before_direct_score
        or source_qa.direct_metrics.silhouette_iou
        != receipt.before_silhouette_iou
    ):
        raise ValueError("visual convergence source QA binding mismatch")
    if receipt.source_build_fingerprint is not None:
        artifacts.update(
            _audit_complete_convergence_qa(
                root,
                job_id=receipt.job_id,
                run_id=receipt.source_qa_run_id,
                scene_spec_sha256=receipt.base_scene_spec_sha256,
                report_sha256=receipt.source_qa_report_sha256,
                candidates_sha256=receipt.candidates_sha256,
                build_fingerprint=receipt.source_build_fingerprint,
            )
        )

    if receipt.compiled_plan_sha256 is not None:
        compiled_path = iteration_root / "revision_plan.json"
        if not compiled_path.is_file() or _is_link_like(compiled_path):
            raise FileNotFoundError(
                f"qa/convergence/{receipt.session_id}/iterations/"
                f"{receipt.iteration_index:03d}/revision_plan.json"
            )
        if sha256_file(compiled_path) != receipt.compiled_plan_sha256:
            raise ValueError("visual convergence compiled plan hash mismatch")
        artifacts[
            compiled_path.resolve().relative_to(root.resolve()).as_posix()
        ] = receipt.compiled_plan_sha256
        compiled = RevisionPlan.model_validate_json(
            compiled_path.read_text(encoding="utf-8")
        )
        selected_candidates = {
            candidate.id: candidate
            for candidate in candidates.candidates
            if candidate.id in set(selection.selected_candidate_ids)
        }
        expected_operations = [
            {
                "op": selected_candidates[candidate_id].op,
                "target_type": selected_candidates[candidate_id].target_type,
                "target_id": selected_candidates[candidate_id].target_id,
                "path": selected_candidates[candidate_id].path,
                "value": selected_candidates[candidate_id].value,
                "reason": selected_candidates[candidate_id].reason,
            }
            for candidate_id in selection.selected_candidate_ids
        ]
        actual_operations = [
            operation.model_dump(mode="json") for operation in compiled.operations
        ]
        if (
            compiled.job_id != receipt.job_id
            or compiled.base_spec_sha256 != receipt.base_scene_spec_sha256
            or actual_operations != expected_operations
        ):
            raise ValueError(
                "visual convergence revision plan does not match selected candidates"
            )

    if receipt.execution_authorization_sha256 is not None:
        authorization_path = iteration_root / "authorization.json"
        if not authorization_path.is_file():
            authorization_path = iteration_root / "execution_authorization.json"
        authorization = VisualConvergenceIterationAuthorization.model_validate_json(
            authorization_path.read_text(encoding="utf-8")
        )
        if sha256_file(authorization_path) != receipt.execution_authorization_sha256:
            raise ValueError("visual convergence authorization hash mismatch")
        artifacts[
            authorization_path.resolve().relative_to(root.resolve()).as_posix()
        ] = receipt.execution_authorization_sha256
        if (
            authorization.session_id != receipt.session_id
            or authorization.job_id != receipt.job_id
            or authorization.iteration_index != receipt.iteration_index
            or authorization.plan_sha256 != receipt.plan_sha256
            or authorization.approval_sha256 != receipt.approval_sha256
            or authorization.base_scene_spec_sha256
            != receipt.base_scene_spec_sha256
            or authorization.source_qa_report_sha256
            != receipt.source_qa_report_sha256
            or authorization.candidates_sha256 != receipt.candidates_sha256
            or authorization.source_build_fingerprint
            != receipt.source_build_fingerprint
            or authorization.selection_sha256 != receipt.selection_sha256
            or authorization.compiled_plan_sha256 != receipt.compiled_plan_sha256
            or authorization.selected_candidate_ids
            != receipt.selected_candidate_ids
        ):
            raise ValueError(
                "visual convergence authorization does not match its receipt"
            )

    if receipt.result_scene_spec_sha256 is not None:
        result_scene_path = iteration_root / "result_scene_spec.json"
        if not result_scene_path.is_file() or _is_link_like(result_scene_path):
            raise FileNotFoundError(
                f"qa/convergence/{receipt.session_id}/iterations/"
                f"{receipt.iteration_index:03d}/result_scene_spec.json"
            )
        if sha256_file(result_scene_path) != receipt.result_scene_spec_sha256:
            raise ValueError("visual convergence result SceneSpec snapshot hash mismatch")
        artifacts[
            result_scene_path.resolve().relative_to(root.resolve()).as_posix()
        ] = receipt.result_scene_spec_sha256

    before_constraint_evidence: dict[str, Any] | None = None
    after_constraint_evidence: dict[str, Any] | None = None
    if receipt.before_constraints_sha256 is not None:
        before_constraints_path = iteration_root / "before_constraints.json"
        before_constraint_evidence = _load_convergence_constraint_evidence(
            before_constraints_path,
            expected_sha256=receipt.before_constraints_sha256,
        )
        artifacts[
            before_constraints_path.resolve().relative_to(root.resolve()).as_posix()
        ] = receipt.before_constraints_sha256
    if receipt.after_constraints_sha256 is not None:
        after_constraints_path = iteration_root / "after_constraints.json"
        after_constraint_evidence = _load_convergence_constraint_evidence(
            after_constraints_path,
            expected_sha256=receipt.after_constraints_sha256,
        )
        artifacts[
            after_constraints_path.resolve().relative_to(root.resolve()).as_posix()
        ] = receipt.after_constraints_sha256
    if new_bound_receipt and receipt.status in {"accepted", "rolled_back"} and (
        before_constraint_evidence is None or after_constraint_evidence is None
    ):
        raise ValueError(
            "new executed visual convergence receipt lacks exact constraint evidence"
        )
    recomputed_constraint_regression_count: int | None = None
    if (
        before_constraint_evidence is not None
        and after_constraint_evidence is not None
    ):
        recomputed_constraint_regression_count = len(
            compare_constraint_results(
                list(before_constraint_evidence["results"]),
                list(after_constraint_evidence["results"]),
            )
        )

    result_build_fields = (
        receipt.result_build_fingerprint,
        receipt.result_build_provenance_sha256,
    )
    if any(item is not None for item in result_build_fields) and any(
        item is None for item in result_build_fields
    ):
        raise ValueError("visual convergence result build evidence is incomplete")
    if all(item is not None for item in result_build_fields):
        if receipt.result_scene_spec_sha256 is None:
            raise ValueError(
                "visual convergence result build lacks its result SceneSpec binding"
            )
        result_build_path = iteration_root / "result_build_provenance.json"
        result_build_relative, result_build_payload = (
            _audit_convergence_build_snapshot(
                root,
                result_build_path,
                expected_file_sha256=receipt.result_build_provenance_sha256,
                expected_fingerprint=receipt.result_build_fingerprint,
                expected_scene_spec_sha256=receipt.result_scene_spec_sha256,
                expected_camera_fingerprint=plan.camera_fingerprint,
            )
        )
        artifacts[result_build_relative] = receipt.result_build_provenance_sha256
        if source_build_payload is not None:
            _validate_convergence_build_transition(
                source_build_payload,
                result_build_payload,
                expected_source_scene_spec_sha256=receipt.base_scene_spec_sha256,
                expected_result_scene_spec_sha256=receipt.result_scene_spec_sha256,
                expected_camera_fingerprint=plan.camera_fingerprint,
            )

    result_qa_fields = (
        receipt.result_qa_run_id,
        receipt.result_qa_report_sha256,
        receipt.result_candidates_sha256,
        receipt.after_direct_score,
        receipt.after_silhouette_iou,
        receipt.score_delta,
    )
    if any(item is not None for item in result_qa_fields) and any(
        item is None for item in result_qa_fields
    ):
        raise ValueError("visual convergence result QA evidence is incomplete")
    if all(item is not None for item in result_qa_fields):
        result_qa_path, result_qa = _convergence_qa_report(
            root,
            receipt.result_qa_run_id,
            receipt.result_qa_report_sha256,
        )
        artifacts[
            result_qa_path.resolve().relative_to(root.resolve()).as_posix()
        ] = receipt.result_qa_report_sha256
        if (
            result_qa.job_id != receipt.job_id
            or result_qa.camera_fingerprint != plan.camera_fingerprint
            or result_qa.direct_metrics.scoring_version != plan.scoring_version
            or (
                receipt.after_direct_score is not None
                and result_qa.direct_metrics.overall_direct_score
                != receipt.after_direct_score
            )
            or (
                receipt.after_silhouette_iou is not None
                and result_qa.direct_metrics.silhouette_iou
                != receipt.after_silhouette_iou
            )
        ):
            raise ValueError("visual convergence result QA binding mismatch")
        result_candidates_path = (
            root
            / "qa"
            / "runs"
            / receipt.result_qa_run_id
            / "revision_candidates.json"
        )
        result_candidates_sha256 = receipt.result_candidates_sha256
        if (
            not result_candidates_path.is_file()
            or _is_link_like(result_candidates_path)
            or sha256_file(result_candidates_path) != result_candidates_sha256
        ):
            raise ValueError("visual convergence result candidates hash mismatch")
        result_candidates = RevisionCandidates.model_validate_json(
            result_candidates_path.read_text(encoding="utf-8")
        )
        if (
            result_candidates.job_id != receipt.job_id
            or result_candidates.base_spec_sha256
            != receipt.result_scene_spec_sha256
            or result_candidates.source_report_sha256
            != receipt.result_qa_report_sha256
            or result_candidates.camera_fingerprint != plan.camera_fingerprint
        ):
            raise ValueError("visual convergence result candidates binding mismatch")
        artifacts[
            result_candidates_path.resolve().relative_to(root.resolve()).as_posix()
        ] = result_candidates_sha256
        if receipt.result_build_fingerprint is not None:
            artifacts.update(
                _audit_complete_convergence_qa(
                    root,
                    job_id=receipt.job_id,
                    run_id=receipt.result_qa_run_id,
                    scene_spec_sha256=receipt.result_scene_spec_sha256,
                    report_sha256=receipt.result_qa_report_sha256,
                    candidates_sha256=result_candidates_sha256,
                    build_fingerprint=receipt.result_build_fingerprint,
                )
            )
    _validate_convergence_iteration_outcome(
        plan,
        receipt,
        recomputed_constraint_regression_count=(
            recomputed_constraint_regression_count
        ),
    )
    return artifacts


def _audit_one_visual_convergence_session(
    root: Path,
    job_id: str,
    session_root: Path,
) -> tuple[bool, str | None]:
    """Validate one session and return terminal state plus any historical limitation."""

    session_id = session_root.name
    if not _PORTABLE_ID_RE.fullmatch(session_id):
        raise ValueError("visual convergence session_id is invalid")
    plan_path = session_root / "plan.json"
    plan = VisualConvergencePlan.model_validate_json(
        plan_path.read_text(encoding="utf-8")
    )
    if plan.job_id != job_id or plan.session_id != session_id:
        raise ValueError("visual convergence plan identity mismatch")
    if (
        plan.initial_input_hashes
        and _canonical_json_sha256(plan.initial_input_hashes)
        != plan.input_fingerprint
    ):
        raise ValueError("visual convergence initial input map binding mismatch")
    current_input_matches = (
        plan.input_fingerprint == _current_convergence_input_fingerprint(root)
    )
    plan_sha256 = sha256_file(plan_path)
    initial_snapshot_artifacts = _audit_initial_convergence_snapshots(
        root,
        session_root,
        plan,
    )
    _initial_qa_path, initial_qa = _convergence_qa_report(
        root,
        plan.initial_qa_run_id,
        plan.initial_qa_report_sha256,
    )
    if (
        initial_qa.job_id != job_id
        or initial_qa.camera_fingerprint != plan.camera_fingerprint
        or initial_qa.direct_metrics.scoring_version != plan.scoring_version
        or initial_qa.direct_metrics.overall_direct_score
        != plan.initial_direct_score
        or initial_qa.direct_metrics.silhouette_iou
        != plan.initial_silhouette_iou
    ):
        raise ValueError("visual convergence initial QA binding mismatch")

    approval_path = session_root / "approval.json"
    approval: VisualConvergenceApproval | None = None
    approval_sha256: str | None = None
    if approval_path.is_file():
        approval = VisualConvergenceApproval.model_validate_json(
            approval_path.read_text(encoding="utf-8")
        )
        approval_sha256 = sha256_file(approval_path)
        validate_convergence_activation(
            plan,
            approval,
            plan_sha256=plan_sha256,
        )

    receipts_with_paths = _load_convergence_receipts(root, session_root)
    if receipts_with_paths and (approval is None or approval_sha256 is None):
        raise ValueError("visual convergence receipts require an exact approval")
    if approval is not None and approval_sha256 is not None:
        validate_iteration_receipt_chain(
            plan,
            approval,
            plan_sha256=plan_sha256,
            approval_sha256=approval_sha256,
            receipts=[
                (receipt, receipt_sha256)
                for receipt, receipt_sha256, _path in receipts_with_paths
            ],
        )
    iteration_artifacts: dict[str, str] = dict(initial_snapshot_artifacts)
    previous_receipt: VisualConvergenceIteration | None = None
    for receipt, receipt_sha256, _path in receipts_with_paths:
        verified_artifacts = _verify_convergence_iteration_artifacts(
            root,
            session_root,
            plan,
            receipt,
            receipt_sha256,
            previous_receipt,
        )
        for relative_path, artifact_sha256 in verified_artifacts.items():
            existing_sha256 = iteration_artifacts.get(relative_path)
            if existing_sha256 is not None and existing_sha256 != artifact_sha256:
                raise ValueError(
                    "visual convergence support artifact has conflicting hashes"
                )
            iteration_artifacts[relative_path] = artifact_sha256
        previous_receipt = receipt

    report_path = session_root / "convergence_report.json"
    staging_root = session_root / "staging"
    if report_path.is_file() and staging_root.exists():
        if _is_link_like(staging_root) or not staging_root.is_dir():
            raise ValueError(
                "terminal visual convergence staging root is not a safe directory"
            )
        staged_entries = sorted(path.name for path in staging_root.iterdir())
        if staged_entries:
            raise ValueError(
                "terminal visual convergence session conflicts with receipt-less "
                f"iteration staging: {staged_entries}"
            )
    if not report_path.is_file():
        if _receipt_chain_requires_terminal_report(
            plan,
            receipts_with_paths,
            session_root,
        ):
            raise ValueError(
                "terminal visual convergence receipt exists without terminal JSON"
            )
        if not current_input_matches:
            raise ValueError("active visual convergence immutable input changed")
        expected_sha256 = (
            receipts_with_paths[-1][0].canonical_scene_spec_sha256
            if receipts_with_paths
            else plan.initial_scene_spec_sha256
        )
        canonical_path = root / "analysis" / "scene_spec.json"
        if not canonical_path.is_file() or sha256_file(canonical_path) != expected_sha256:
            raise ValueError("active visual convergence canonical SceneSpec is stale")
        current_qa_run_id, current_qa_report_sha256 = (
            _current_convergence_qa_identity(plan, receipts_with_paths)
        )
        _current_qa_path, current_qa = _convergence_qa_report(
            root,
            current_qa_run_id,
            current_qa_report_sha256,
        )
        if (
            current_qa.job_id != job_id
            or current_qa.camera_fingerprint != plan.camera_fingerprint
            or current_qa.direct_metrics.scoring_version != plan.scoring_version
        ):
            raise ValueError("active visual convergence current QA binding mismatch")
        current_candidates_sha256 = _verify_current_convergence_candidates(
            root,
            plan,
            qa_run_id=current_qa_run_id,
            qa_report_sha256=current_qa_report_sha256,
            canonical_scene_spec_sha256=expected_sha256,
        )
        _audit_complete_convergence_qa(
            root,
            job_id=job_id,
            run_id=current_qa_run_id,
            scene_spec_sha256=expected_sha256,
            report_sha256=current_qa_report_sha256,
            candidates_sha256=current_candidates_sha256,
            build_fingerprint=(
                receipts_with_paths[-1][0].result_build_fingerprint
                if receipts_with_paths
                else plan.initial_build_fingerprint
            ),
        )
        return False, None

    if approval is None or approval_sha256 is None:
        raise ValueError("terminal visual convergence report requires an approval")
    historical_input_limitation = _verify_terminal_convergence_inputs(
        root,
        plan,
        current_fingerprint_matches=current_input_matches,
    )
    report = VisualConvergenceReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    if (
        report.job_id != job_id
        or report.session_id != session_id
        or report.plan_sha256 != plan_sha256
        or report.approval_sha256 != approval_sha256
        or report.input_fingerprint != plan.input_fingerprint
        or report.camera_fingerprint != plan.camera_fingerprint
        or report.scoring_version != plan.scoring_version
        or report.initial_scene_spec_sha256 != plan.initial_scene_spec_sha256
        or report.initial_qa_report_sha256 != plan.initial_qa_report_sha256
        or report.initial_candidates_sha256 != plan.initial_candidates_sha256
        or report.initial_build_fingerprint != plan.initial_build_fingerprint
        or report.initial_constraints_present != plan.initial_constraints_present
        or report.initial_constraints_sha256 != plan.initial_constraints_sha256
        or report.initial_direct_score != plan.initial_direct_score
        or report.initial_silhouette_iou != plan.initial_silhouette_iou
        or report.target_direct_score != plan.target_direct_score
        or report.target_silhouette_iou != plan.target_silhouette_iou
    ):
        raise ValueError("terminal visual convergence report binding mismatch")
    if plan.initial_candidates_sha256 is not None:
        if report.initial_scene_spec_snapshot is None:
            raise ValueError(
                "terminal visual convergence omits its initial SceneSpec snapshot"
            )
        initial_scene_snapshot_path = _resolve_convergence_artifact(
            root,
            report.initial_scene_spec_snapshot,
        )
        if (
            initial_scene_snapshot_path
            != (session_root / "initial_scene_spec.json").resolve()
            or report.initial_scene_spec_snapshot.sha256
            != plan.initial_scene_spec_sha256
        ):
            raise ValueError(
                "terminal visual convergence initial SceneSpec snapshot mismatch"
            )

    receipt_artifacts = {
        path.resolve().relative_to(root.resolve()).as_posix(): receipt_sha256
        for _receipt, receipt_sha256, path in receipts_with_paths
    }
    report_receipts = {
        item.relative_path: item.sha256 for item in report.iteration_receipts
    }
    if report_receipts != receipt_artifacts:
        raise ValueError("terminal visual convergence receipt set is incomplete or stale")
    report_iteration_evidence = {
        item.relative_path: item.sha256 for item in report.iteration_evidence
    }
    expected_iteration_artifacts = dict(iteration_artifacts)
    terminal_build_artifacts = _audit_terminal_convergence_build_snapshots(
        root,
        session_root,
        plan,
        report,
        receipts_with_paths,
    )
    cancellation_artifacts = _audit_terminal_convergence_cancellation(
        root,
        session_root,
        plan,
        report,
        plan_sha256=plan_sha256,
        approval_sha256=approval_sha256,
        receipts=receipts_with_paths,
    )
    complete_contract = _uses_complete_convergence_terminal_contract(plan)
    if complete_contract:
        if report.final_scene_spec_snapshot is None:
            raise ValueError(
                "new visual convergence terminal was downgraded to legacy evidence"
            )
        expected_iteration_artifacts.update(
            _collect_complete_convergence_qa_artifacts(
                root,
                job_id=job_id,
                plan=plan,
                receipts=receipts_with_paths,
            )
        )
        if report_iteration_evidence != expected_iteration_artifacts:
            missing = sorted(
                set(expected_iteration_artifacts) - set(report_iteration_evidence)
            )
            extra = sorted(
                set(report_iteration_evidence) - set(expected_iteration_artifacts)
            )
            changed = sorted(
                path
                for path in set(report_iteration_evidence).intersection(
                    expected_iteration_artifacts
                )
                if report_iteration_evidence[path]
                != expected_iteration_artifacts[path]
            )
            raise ValueError(
                "terminal visual convergence support evidence set is incomplete or "
                f"stale: missing={missing}, extra={extra}, changed={changed}"
            )
    elif report_iteration_evidence != expected_iteration_artifacts:
        optional_complete_artifacts = dict(iteration_artifacts)
        optional_complete_artifacts.update(
            _collect_complete_convergence_qa_artifacts(
                root,
                job_id=job_id,
                plan=plan,
                receipts=receipts_with_paths,
            )
        )
        if report_iteration_evidence != optional_complete_artifacts:
            raise ValueError(
                "legacy visual convergence support evidence set is incomplete or stale"
            )
        expected_iteration_artifacts = optional_complete_artifacts
    if report.final_scene_spec_snapshot is not None:
        snapshot_path = _resolve_convergence_artifact(
            root,
            report.final_scene_spec_snapshot,
        )
        expected_snapshot_path = (session_root / "final_scene_spec.json").resolve()
        if (
            snapshot_path != expected_snapshot_path
            or report.final_scene_spec_snapshot.sha256
            != report.final_scene_spec_sha256
        ):
            raise ValueError(
                "terminal visual convergence final SceneSpec snapshot mismatch"
            )
    if receipts_with_paths:
        final_receipt = receipts_with_paths[-1][0]
        if report.final_scene_spec_sha256 != final_receipt.canonical_scene_spec_sha256:
            raise ValueError("terminal visual convergence final SceneSpec hash mismatch")
        known_final_qa_hashes = {
            value
            for value in (
                final_receipt.source_qa_report_sha256,
                final_receipt.result_qa_report_sha256,
            )
            if value is not None
        }
    else:
        if report.final_scene_spec_sha256 != plan.initial_scene_spec_sha256:
            raise ValueError("empty visual convergence session changed the SceneSpec")
        known_final_qa_hashes = {plan.initial_qa_report_sha256}
    if report.final_qa_report_sha256 not in known_final_qa_hashes:
        raise ValueError("terminal visual convergence final QA hash is not evidenced")
    accepted_count = sum(
        receipt.status == "accepted"
        for receipt, _receipt_sha256, _path in receipts_with_paths
    )
    rolled_back_count = sum(
        receipt.status == "rolled_back"
        for receipt, _receipt_sha256, _path in receipts_with_paths
    )
    if (
        report.accepted_iterations != accepted_count
        or report.rolled_back_iterations != rolled_back_count
    ):
        raise ValueError("terminal visual convergence iteration counts mismatch")
    _validate_terminal_convergence_semantics(report, receipts_with_paths)

    manifest_path = session_root / "convergence_report.manifest.json"
    manifest = VisualConvergenceReportManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if manifest.job_id != job_id or manifest.session_id != session_id:
        raise ValueError("visual convergence PDF manifest identity mismatch")
    report_artifact_path = _resolve_convergence_artifact(root, manifest.report_json)
    if report_artifact_path != report_path.resolve():
        raise ValueError("visual convergence manifest references another terminal report")
    pdf_artifact_path = _resolve_convergence_artifact(root, manifest.pdf)
    expected_pdf_path = (session_root / "convergence_report.pdf").resolve()
    if pdf_artifact_path != expected_pdf_path:
        raise ValueError("visual convergence manifest references a noncanonical PDF path")
    for artifact in manifest.sources:
        _resolve_convergence_artifact(root, artifact)
    expected_manifest_fingerprint = _canonical_json_sha256(
        [
            {
                "relative_path": artifact.relative_path,
                "sha256": artifact.sha256,
            }
            for artifact in manifest.sources
        ]
    )
    if manifest.source_fingerprint != expected_manifest_fingerprint:
        raise ValueError("visual convergence PDF source fingerprint mismatch")
    final_qa_run_id = next(
        (
            receipt.result_qa_run_id
            for receipt, _receipt_sha256, _path in reversed(receipts_with_paths)
            if receipt.status == "accepted" and receipt.result_qa_run_id is not None
        ),
        plan.initial_qa_run_id,
    )
    final_qa_path, final_qa = _convergence_qa_report(
        root,
        final_qa_run_id,
        report.final_qa_report_sha256,
    )
    if (
        final_qa.job_id != job_id
        or final_qa.camera_fingerprint != plan.camera_fingerprint
        or final_qa.direct_metrics.scoring_version != plan.scoring_version
        or final_qa.direct_metrics.overall_direct_score != report.final_direct_score
        or final_qa.direct_metrics.silhouette_iou != report.final_silhouette_iou
    ):
        raise ValueError("terminal visual convergence final QA metrics mismatch")
    remaining_high_findings = sorted(
        finding.id
        for finding in final_qa.findings
        if finding.severity == "high"
        and "direct_reference" in finding.evidence_sources
    )
    if report.remaining_high_finding_ids != remaining_high_findings:
        raise ValueError("terminal visual convergence high-finding summary mismatch")
    final_qa_relative = final_qa_path.resolve().relative_to(root.resolve()).as_posix()
    required_source_pairs = {
        (
            plan_path.resolve().relative_to(root.resolve()).as_posix(),
            plan_sha256,
        ),
        (
            approval_path.resolve().relative_to(root.resolve()).as_posix(),
            approval_sha256,
        ),
        (
            report_path.resolve().relative_to(root.resolve()).as_posix(),
            sha256_file(report_path),
        ),
        *expected_iteration_artifacts.items(),
        *terminal_build_artifacts.items(),
        *cancellation_artifacts.items(),
        (final_qa_relative, report.final_qa_report_sha256),
    }
    if report.final_scene_spec_snapshot is not None:
        required_source_pairs.add(
            (
                report.final_scene_spec_snapshot.relative_path,
                report.final_scene_spec_snapshot.sha256,
            )
        )
    actual_source_pairs = {
        (artifact.relative_path, artifact.sha256) for artifact in manifest.sources
    }
    if not required_source_pairs.issubset(actual_source_pairs):
        raise ValueError("visual convergence PDF manifest omits authoritative sources")
    return True, historical_input_limitation


def _audit_visual_convergence_sessions(
    root: Path,
    job_id: str,
) -> tuple[int, int, str, list[AuditFinding]]:
    """Classify bounded convergence sessions without invalidating historical results."""

    sessions_root = root / "qa" / "convergence"
    if not sessions_root.is_dir():
        return 0, 0, "not_requested", []
    sessions = [
        child
        for child in sorted(sessions_root.iterdir())
        if child.is_dir() and not _is_link_like(child)
    ]
    if not sessions:
        return 0, 0, "not_requested", []

    valid_count = 0
    active_count = 0
    findings: list[AuditFinding] = []
    for session_root in sessions:
        try:
            terminal, historical_limitation = _audit_one_visual_convergence_session(
                root,
                job_id,
                session_root,
            )
            if terminal:
                valid_count += 1
                if historical_limitation == "verified_additions":
                    findings.append(
                        _finding(
                            "VISUAL_CONVERGENCE_HISTORICAL_INPUT_ADDITIONS",
                            "info",
                            "Completed visual convergence evidence remains valid; "
                            "the job now contains additional input files that were not "
                            "part of the approved historical session.",
                            job_id=job_id,
                            path=_workspace_relative(session_root),
                        )
                    )
                elif historical_limitation == "legacy_unverifiable":
                    findings.append(
                        _finding(
                            "VISUAL_CONVERGENCE_HISTORICAL_INPUT_SET_UNVERIFIABLE",
                            "warning",
                            "Completed legacy visual convergence evidence remains "
                            "historically readable, but its aggregate input fingerprint "
                            "cannot distinguish later additions from original-file changes.",
                            job_id=job_id,
                            path=_workspace_relative(session_root),
                            remediation=(
                                "Preserve the terminal evidence. Use a new convergence "
                                "session for the current input set; do not rewrite the "
                                "legacy session."
                            ),
                        )
                    )
            else:
                active_count += 1
                findings.append(
                    _finding(
                        "VISUAL_CONVERGENCE_ACTIVE",
                        "info",
                        f"Visual convergence session {session_root.name} is active.",
                        job_id=job_id,
                        path=_workspace_relative(session_root),
                    )
                )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            findings.append(
                _finding(
                    "VISUAL_CONVERGENCE_INVALID",
                    "error",
                    "Visual convergence session failed contract or hash-chain "
                    f"validation: {type(exc).__name__}.",
                    job_id=job_id,
                    path=_workspace_relative(session_root),
                    remediation=(
                        "Preserve the session, inspect its immutable plan, approval, "
                        "iteration receipts, QA evidence, and PDF sidecar, then start "
                        "a new session if repair would rewrite history."
                    ),
                )
            )
    status = (
        "invalid"
        if any(item.severity == "error" for item in findings)
        else "active"
        if active_count
        else "valid"
    )
    return len(sessions), valid_count, status, findings


def _audit_destination_handoffs(
    root: Path,
    job_id: str,
) -> tuple[int, int, str, list[AuditFinding]]:
    """Classify handoff integrity and stale package bindings without repairing evidence."""

    if not load_feature_config().features.destination_handoff:
        return 0, 0, "not_requested", []
    try:
        payload = get_destination_handoff_status(job_id)
    except Exception as exc:
        return (
            1,
            0,
            "invalid",
            [
                _finding(
                    "HANDOFF_STATUS_INVALID",
                    "error",
                    "Destination handoff status could not be reconstructed: "
                    f"{type(exc).__name__}.",
                    job_id=job_id,
                    path=f"workspace/{job_id}/exports/destination_handoffs",
                    remediation="Restore the immutable handoff plan and validation evidence.",
                )
            ],
        )
    records = payload.get("handoffs", [])
    records = records if isinstance(records, list) else []
    count = len(records)
    valid = sum(
        isinstance(item, dict) and item.get("status") == "valid" for item in records
    )
    raw_status = str(payload.get("status", "not_requested"))
    status = "generated" if raw_status in {"planned", "generated"} else raw_status
    if status not in {"not_requested", "generated", "valid", "invalid", "stale"}:
        status = "invalid"
    findings: list[AuditFinding] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        item_status = str(item.get("status", "invalid"))
        handoff_id = str(item.get("handoff_id", "unknown"))
        output_root = item.get("output_root")
        path = (
            f"workspace/{job_id}/{output_root}"
            if isinstance(output_root, str)
            else f"workspace/{job_id}/exports/destination_handoffs"
        )
        if item_status == "stale":
            findings.append(
                _finding(
                    "HANDOFF_STALE_BINDING",
                    "error",
                    f"Destination handoff {handoff_id} is stale for its source package.",
                    job_id=job_id,
                    path=path,
                    remediation="Generate a new handoff from the current passed round trip.",
                )
            )
        elif item_status == "invalid":
            findings.append(
                _finding(
                    "HANDOFF_INVALID",
                    "error",
                    f"Destination handoff {handoff_id} failed receipt or contract validation.",
                    job_id=job_id,
                    path=path,
                    remediation="Restore the handoff or regenerate it under a new ID.",
                )
            )
        elif item_status in {"planned", "generated"}:
            findings.append(
                _finding(
                    "HANDOFF_INCOMPLETE",
                    "warning",
                    f"Destination handoff {handoff_id} is planned but not fully validated.",
                    job_id=job_id,
                    path=path,
                    remediation="Generate and validate the handoff before moving it.",
                )
            )
    return count, valid, status, findings


def _audit_job(
    root: Path,
    scan_counter: list[int],
    scan_limit: int,
) -> JobAudit:
    """Audit one job's identity, immutable sources, JSON contracts, and migration boundary."""

    job_id = root.name
    findings: list[AuditFinding] = []
    metadata_path = root / "job.json"
    metadata: dict[str, Any] = {}
    if not metadata_path.is_file():
        findings.append(
            _finding(
                "MISSING_JOB_METADATA",
                "error",
                "Job directory does not contain job.json.",
                job_id=job_id,
                path=_workspace_relative(root),
            )
        )
    else:
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("job.json must contain an object")
            metadata = payload
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            findings.append(
                _finding(
                    "INVALID_JOB_METADATA",
                    "error",
                    f"job.json is unreadable: {type(exc).__name__}.",
                    job_id=job_id,
                    path=_workspace_relative(metadata_path),
                )
            )
    if metadata and metadata.get("job_id") != job_id:
        findings.append(
            _finding(
                "JOB_ID_MISMATCH",
                "error",
                "Directory name and job.json job_id do not match exactly.",
                job_id=job_id,
                path=_workspace_relative(metadata_path),
            )
        )
    created_version = metadata.get("project_version_created")
    created_version = created_version if isinstance(created_version, str) else None
    parsed = _parse_version(created_version)
    current = _parse_version(PROJECT_VERSION) or (0, 9, 0)
    if created_version is None:
        migration_status = "compatible_legacy"
        findings.append(
            _finding(
                "LEGACY_VERSION_UNRECORDED",
                "info",
                "Job predates explicit project-version metadata; no migration was applied.",
                job_id=job_id,
            )
        )
    elif parsed is None:
        migration_status = "corrupt"
        findings.append(
            _finding(
                "INVALID_CREATED_VERSION",
                "error",
                "project_version_created is not a semantic version.",
                job_id=job_id,
                path=_workspace_relative(metadata_path),
            )
        )
    elif parsed > current:
        migration_status = "unsupported_future"
        findings.append(
            _finding(
                "FUTURE_JOB_VERSION",
                "error",
                "Job was created by a newer project version and was not migrated.",
                job_id=job_id,
            )
        )
    elif parsed < current:
        migration_status = "compatible_legacy"
        findings.append(
            _finding(
                "COMPATIBLE_LEGACY_JOB",
                "info",
                "Earlier project metadata is retained under preserved contract versions.",
                job_id=job_id,
            )
        )
    else:
        migration_status = "current"

    raw_sources = metadata.get("sources", []) if metadata else []
    sources = raw_sources if isinstance(raw_sources, list) else []
    if metadata and not isinstance(raw_sources, list):
        findings.append(
            _finding(
                "INVALID_SOURCE_LIST",
                "error",
                "job.json sources must be a list.",
                job_id=job_id,
                path=_workspace_relative(metadata_path),
            )
        )
    source_count = len(sources)
    verified_sources = 0
    input_root = (root / "input").resolve()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            findings.append(
                _finding(
                    "INVALID_SOURCE_RECORD",
                    "error",
                    f"Source record {index} is not an object.",
                    job_id=job_id,
                )
            )
            continue
        value = source.get("path")
        expected = source.get("sha256")
        if not isinstance(value, str) or not isinstance(expected, str):
            findings.append(
                _finding(
                    "INVALID_SOURCE_RECORD",
                    "error",
                    f"Source record {index} lacks path or SHA-256.",
                    job_id=job_id,
                )
            )
            continue
        path = _resolve_source_path(value, job_root=root)
        try:
            path.relative_to(input_root)
        except ValueError:
            findings.append(
                _finding(
                    "SOURCE_PATH_ESCAPE",
                    "error",
                    f"Source record {index} does not resolve inside the job input directory.",
                    job_id=job_id,
                )
            )
            continue
        if _is_link_like(path) or not path.is_file():
            findings.append(
                _finding(
                    "SOURCE_MISSING_OR_LINKED",
                    "error",
                    f"Source record {index} is missing or link-like.",
                    job_id=job_id,
                    path=_workspace_relative(path),
                )
            )
            continue
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected) or (
            sha256_file(path).casefold() != expected.casefold()
        ):
            findings.append(
                _finding(
                    "SOURCE_HASH_MISMATCH",
                    "error",
                    f"Source record {index} no longer matches its immutable SHA-256.",
                    job_id=job_id,
                    path=_workspace_relative(path),
                )
            )
            continue
        verified_sources += 1

    findings.extend(_scan_job_files(root, job_id, scan_counter, scan_limit))
    findings.extend(_audit_external_static_asset_intake(root, job_id, metadata))
    if scan_counter[0] <= scan_limit:
        findings.extend(_audit_production_dispatches(root, job_id))
    findings.extend(_audit_latest_workflow(root, job_id))
    findings.extend(_audit_latest_interior_qa(root, job_id))
    (
        visual_convergence_session_count,
        valid_visual_convergence_session_count,
        visual_convergence_status,
        visual_convergence_findings,
    ) = _audit_visual_convergence_sessions(root, job_id)
    findings.extend(visual_convergence_findings)
    handoff_count, valid_handoff_count, handoff_status, handoff_findings = (
        _audit_destination_handoffs(root, job_id)
    )
    findings.extend(handoff_findings)
    workflows_root = root / "workflows"
    workflow_count = 0
    if workflows_root.is_dir():
        workflow_count = sum(
            1
            for child in workflows_root.iterdir()
            if child.is_dir()
            and not _is_link_like(child)
            and (child / "request.json").is_file()
        )
    if any(item.severity == "error" for item in findings):
        status = "failed"
        if migration_status not in {"unsupported_future"}:
            migration_status = "corrupt"
    elif any(item.severity == "warning" for item in findings):
        status = "warning"
    else:
        status = "passed"
    return JobAudit(
        job_id=job_id,
        status=status,  # type: ignore[arg-type]
        migration_status=migration_status,  # type: ignore[arg-type]
        project_version_created=created_version,
        source_count=source_count,
        verified_source_count=verified_sources,
        workflow_count=workflow_count,
        handoff_count=handoff_count,
        valid_handoff_count=valid_handoff_count,
        handoff_status=handoff_status,  # type: ignore[arg-type]
        visual_convergence_session_count=visual_convergence_session_count,
        valid_visual_convergence_session_count=(
            valid_visual_convergence_session_count
        ),
        visual_convergence_status=visual_convergence_status,  # type: ignore[arg-type]
        findings=findings,
    )


def audit_workspace_state(
    *,
    job_id: str | None = None,
    audit_id: str | None = None,
    scan_limit: int | None = None,
) -> WorkspaceAuditReport:
    """Run a bounded read-only workspace audit and persist only a derived report."""

    configured_limit, _lock_ttl, _lease_seconds = _require_stabilization()
    selected_limit = scan_limit or configured_limit
    if selected_limit < 100 or selected_limit > 1_000_000:
        raise ValueError("scan_limit must be within [100, 1000000]")
    selected_id = _validate_portable_id(audit_id or _portable_id("audit"), "audit_id")
    if job_id is not None and not _JOB_ID_RE.fullmatch(job_id):
        raise ValueError("job_id is invalid")
    started = _utc_now()
    workspace = get_settings().workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    global_findings: list[AuditFinding] = []
    roots: list[Path] = []
    if job_id is not None:
        selected = workspace / job_id
        if not selected.is_dir() or _is_link_like(selected):
            global_findings.append(
                _finding(
                    "JOB_NOT_AUDITABLE",
                    "error",
                    "Selected job is missing, not a directory, or link-like.",
                    job_id=job_id,
                    path=f"workspace/{job_id}",
                )
            )
        else:
            roots = [selected]
    else:
        for child in sorted(workspace.iterdir(), key=lambda item: item.name.casefold()):
            if child.name.startswith("."):
                continue
            if _is_link_like(child):
                global_findings.append(
                    _finding(
                        "LINKED_JOB_DIRECTORY",
                        "error",
                        "Link-like workspace entries are not audited as jobs.",
                        path=f"workspace/{child.name}",
                    )
                )
                continue
            if child.is_dir() and _JOB_ID_RE.fullmatch(child.name):
                roots.append(child)
    counter = [0]
    jobs = [_audit_job(root, counter, selected_limit) for root in roots]
    passed = sum(item.status == "passed" for item in jobs)
    warnings = sum(item.status == "warning" for item in jobs)
    failed = sum(item.status == "failed" for item in jobs)
    all_findings = global_findings + [item for job in jobs for item in job.findings]
    status = (
        "failed"
        if any(item.severity == "error" for item in all_findings)
        else "warning"
        if any(item.severity == "warning" for item in all_findings)
        else "passed"
    )
    report = WorkspaceAuditReport(
        audit_id=selected_id,
        project_version=PROJECT_VERSION,
        workspace_mode=_workspace_mode(),  # type: ignore[arg-type]
        job_filter=job_id,
        scan_limit=selected_limit,
        scanned_file_count=counter[0],
        scanned_job_count=len(jobs),
        passed_job_count=passed,
        warning_job_count=warnings,
        failed_job_count=failed,
        handoff_count=sum(item.handoff_count for item in jobs),
        valid_handoff_count=sum(item.valid_handoff_count for item in jobs),
        visual_convergence_session_count=sum(
            item.visual_convergence_session_count for item in jobs
        ),
        valid_visual_convergence_session_count=sum(
            item.valid_visual_convergence_session_count for item in jobs
        ),
        status=status,  # type: ignore[arg-type]
        jobs=jobs,
        findings=global_findings,
        started_at=started,
        completed_at=_utc_now(),
    )
    output = (
        get_settings().repo_root
        / "reports"
        / "v09"
        / "audits"
        / selected_id
        / "workspace_audit.json"
    )
    if output.exists():
        raise FileExistsError(f"Workspace audit already exists: {selected_id}")
    write_json_atomic(output, report.model_dump(mode="json"))
    return report


def _queue_root() -> Path:
    """Resolve the non-canonical workspace-local V0.9 queue directory."""

    return get_settings().workspace_root / ".cbm" / "queue"


def _queue_path() -> Path:
    """Resolve the mutable local queue state file."""

    return _queue_root() / "local_queue.json"


def _load_queue() -> LocalWorkflowQueue:
    """Load strict queue state or initialize an empty in-memory queue."""

    path = _queue_path()
    if not path.is_file():
        return LocalWorkflowQueue(updated_at=_utc_now())
    return LocalWorkflowQueue.model_validate_json(path.read_text(encoding="utf-8"))


def _save_queue(queue: LocalWorkflowQueue) -> LocalWorkflowQueue:
    """Atomically persist one incremented queue revision."""

    updated = queue.model_copy(
        update={"revision": queue.revision + 1, "updated_at": _utc_now()}
    )
    write_json_atomic(_queue_path(), updated.model_dump(mode="json"))
    return updated


def get_local_workflow_queue() -> LocalWorkflowQueue:
    """Read local queue state without resuming workflows or changing evidence."""

    _require_stabilization()
    return _load_queue()


def enqueue_short_workflow(
    job_id: str,
    workflow_id: str,
    *,
    priority: int = 50,
    max_attempts: int = 3,
) -> LocalWorkflowQueue:
    """Queue one existing non-terminal V0.8 workflow without creating authority."""

    _scan_limit, lock_ttl, _lease_seconds = _require_stabilization()
    if priority < 0 or priority > 100:
        raise ValueError("priority must be within [0, 100]")
    if max_attempts < 1 or max_attempts > 10:
        raise ValueError("max_attempts must be within [1, 10]")
    status_payload = get_workflow_status(job_id, workflow_id)
    workflow_state = status_payload.get("state", {})
    workflow_status = str(workflow_state.get("status", "unknown"))
    if workflow_status in {"completed", "cancelled"}:
        raise RuntimeError(f"Terminal workflow cannot be queued: {workflow_status}")
    queue_root = _queue_root()
    with queue_write_lock(queue_root, ttl_seconds=lock_ttl):
        queue = _load_queue()
        active = {
            "queued",
            "running",
            "waiting",
            "failed",
        }
        if any(
            item.status in active
            and (item.job_id.casefold() == job_id.casefold() or item.workflow_id == workflow_id)
            for item in queue.entries
        ):
            raise FileExistsError("Job or workflow already has an active local queue entry")
        now = _utc_now()
        entry = QueueEntry(
            entry_id=f"queue-{uuid4().hex}",
            job_id=job_id,
            workflow_id=workflow_id,
            priority=priority,
            max_attempts=max_attempts,
            enqueued_at=now,
            updated_at=now,
            last_workflow_status=workflow_status,
        )
        return _save_queue(queue.model_copy(update={"entries": [*queue.entries, entry]}))


def _workflow_status_value(job_id: str, workflow_id: str) -> str:
    """Read one persisted workflow status from the public V0.8 status surface."""

    payload = get_workflow_status(job_id, workflow_id)
    state = payload.get("state")
    if not isinstance(state, dict):
        raise RuntimeError("Workflow status response lacks state")
    return str(state.get("status", "unknown"))


def _queue_attempt_receipt_exists(entry_id: str, attempt_number: int) -> bool:
    """Detect an already-recorded attempt before recovering an expired lease."""

    root = _queue_root() / "receipts" / entry_id
    if not root.is_dir():
        return False
    for path in sorted(root.glob("*.json")):
        receipt = QueueAttemptReceipt.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if receipt.attempt_number == attempt_number:
            return True
    return False


def _recover_expired_queue_leases(
    queue: LocalWorkflowQueue,
) -> LocalWorkflowQueue:
    """Fail closed on interrupted queue workers only after their exact lease expires."""

    now = _utc_now()
    entries: list[QueueEntry] = []
    for item in queue.entries:
        if (
            item.status == "running"
            and item.lease_expires_at is not None
            and item.lease_expires_at <= now
        ):
            if not _queue_attempt_receipt_exists(item.entry_id, item.attempt_count):
                _write_queue_receipt(
                    QueueAttemptReceipt(
                        receipt_id=f"receipt-{uuid4().hex}",
                        entry_id=item.entry_id,
                        job_id=item.job_id,
                        workflow_id=item.workflow_id,
                        attempt_number=item.attempt_count,
                        retry_failed=item.retry_failed_once,
                        workflow_status_before=item.last_workflow_status,
                        workflow_status_after=None,
                        outcome="failed",
                        error_type="InterruptedQueueAttempt",
                        error_message=(
                            "Execution lease expired before queue finalization."
                        ),
                        started_at=item.started_at or item.updated_at,
                        completed_at=now,
                    )
                )
            entries.append(
                item.model_copy(
                    update={
                        "status": "failed",
                        "lease_id": None,
                        "lease_expires_at": None,
                        "updated_at": now,
                        "last_error": (
                            "InterruptedQueueAttempt: execution lease expired before finalization"
                        ),
                    }
                )
            )
        else:
            entries.append(item)
    return queue.model_copy(update={"entries": entries})


def _select_queue_entry(queue: LocalWorkflowQueue) -> QueueEntry | None:
    """Choose the highest-priority eligible entry without polling unchanged approvals."""

    candidates: list[QueueEntry] = []
    for item in queue.entries:
        if item.status == "queued":
            candidates.append(item)
        elif item.status == "waiting":
            current = _workflow_status_value(item.job_id, item.workflow_id)
            if current not in {"waiting_for_agent", "waiting_for_approval", "blocked"}:
                candidates.append(item)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-item.priority, item.enqueued_at))[0]


def _claim_queue_entry(
    queue: LocalWorkflowQueue,
    selected: QueueEntry,
    lease_seconds: int,
) -> tuple[LocalWorkflowQueue, QueueEntry]:
    """Persist one execution lease before leaving the short queue-lock boundary."""

    now = _utc_now()
    lease_id = uuid4().hex
    claimed = selected.model_copy(
        update={
            "status": "running",
            "attempt_count": selected.attempt_count + 1,
            "started_at": now,
            "updated_at": now,
            "lease_id": lease_id,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
            "last_error": None,
        }
    )
    entries = [claimed if item.entry_id == selected.entry_id else item for item in queue.entries]
    return _save_queue(queue.model_copy(update={"entries": entries})), claimed


def _queue_outcome(workflow_status: str) -> tuple[str, str]:
    """Map V0.8 workflow state into the smaller V0.9 queue lifecycle."""

    if workflow_status == "completed":
        return "completed", "completed"
    if workflow_status == "cancelled":
        return "cancelled", "cancelled"
    if workflow_status == "failed":
        return "failed", "failed"
    if workflow_status in {"waiting_for_agent", "waiting_for_approval", "blocked"}:
        return "waiting", "waiting"
    return "queued", "advanced"


def _write_queue_receipt(receipt: QueueAttemptReceipt) -> None:
    """Persist one immutable local-queue receipt without overwriting prior attempts."""

    path = _queue_root() / "receipts" / receipt.entry_id / f"{receipt.receipt_id}.json"
    if path.exists():
        raise FileExistsError("Queue attempt receipt already exists")
    write_json_atomic(path, receipt.model_dump(mode="json"))


def _finalize_queue_entry(
    claimed: QueueEntry,
    *,
    workflow_status_before: str | None,
    workflow_status_after: str | None,
    error: Exception | None,
    started_at: datetime,
    lock_ttl: int,
) -> LocalWorkflowQueue:
    """Finalize only the exact leased queue entry and write one immutable receipt."""

    completed_at = _utc_now()
    if error is None:
        entry_status, outcome = _queue_outcome(workflow_status_after or "unknown")
        if workflow_status_after == "failed":
            error_type = "WorkflowFailed"
            error_message = "V0.8 workflow reported a failed deterministic host step."
        else:
            error_type = None
            error_message = None
    else:
        entry_status, outcome = "failed", "failed"
        error_type = type(error).__name__
        error_message = str(error)[:4000]
    receipt = QueueAttemptReceipt(
        receipt_id=f"receipt-{uuid4().hex}",
        entry_id=claimed.entry_id,
        job_id=claimed.job_id,
        workflow_id=claimed.workflow_id,
        attempt_number=claimed.attempt_count,
        retry_failed=claimed.retry_failed_once,
        workflow_status_before=workflow_status_before,
        workflow_status_after=workflow_status_after,
        outcome=outcome,  # type: ignore[arg-type]
        error_type=error_type,
        error_message=error_message,
        started_at=started_at,
        completed_at=completed_at,
    )
    queue_root = _queue_root()
    with queue_write_lock(queue_root, ttl_seconds=lock_ttl):
        queue = _load_queue()
        current = next(
            (item for item in queue.entries if item.entry_id == claimed.entry_id),
            None,
        )
        if current is None or current.status != "running":
            raise RuntimeError("Claimed queue entry disappeared or is no longer running")
        if current.lease_id != claimed.lease_id:
            raise RuntimeError("Queue execution lease changed before finalization")
        completed_marker = completed_at if entry_status in {"completed", "cancelled"} else None
        finalized = current.model_copy(
            update={
                "status": entry_status,
                "retry_failed_once": False,
                "updated_at": completed_at,
                "completed_at": completed_marker,
                "lease_id": None,
                "lease_expires_at": None,
                "last_workflow_status": workflow_status_after or workflow_status_before,
                "last_error": error_message,
            }
        )
        entries = [
            finalized if item.entry_id == claimed.entry_id else item
            for item in queue.entries
        ]
        _write_queue_receipt(receipt)
        return _save_queue(queue.model_copy(update={"entries": entries}))


def run_local_workflow_queue(
    *,
    max_entries: int = 1,
    max_host_steps: int | None = None,
) -> LocalWorkflowQueue:
    """Dispatch bounded existing workflows sequentially and stop at every V0.8 boundary."""

    _scan_limit, lock_ttl, lease_seconds = _require_stabilization()
    if max_entries < 1 or max_entries > 64:
        raise ValueError("max_entries must be within [1, 64]")
    processed = 0
    while processed < max_entries:
        queue_root = _queue_root()
        with queue_write_lock(queue_root, ttl_seconds=lock_ttl):
            queue = _recover_expired_queue_leases(_load_queue())
            selected = _select_queue_entry(queue)
            if selected is None:
                return _save_queue(queue) if queue != _load_queue() else queue
            queue, claimed = _claim_queue_entry(queue, selected, lease_seconds)
        started = _utc_now()
        before: str | None = None
        after: str | None = None
        failure: Exception | None = None
        try:
            before = _workflow_status_value(claimed.job_id, claimed.workflow_id)
            state = resume_workflow(
                claimed.job_id,
                claimed.workflow_id,
                max_host_steps=max_host_steps,
                retry_failed=claimed.retry_failed_once,
            )
            after = state.status
        except Exception as exc:  # Queue evidence must retain deterministic host failures.
            failure = exc
        queue = _finalize_queue_entry(
            claimed,
            workflow_status_before=before,
            workflow_status_after=after,
            error=failure,
            started_at=started,
            lock_ttl=lock_ttl,
        )
        processed += 1
    return queue


def requeue_local_workflow(
    entry_id: str,
    *,
    retry_failed: bool,
) -> LocalWorkflowQueue:
    """Requeue one failed entry only with an explicit V0.8 failed-step retry decision."""

    _validate_portable_id(entry_id, "entry_id")
    if not retry_failed:
        raise PermissionError("Failed workflow requeue requires retry_failed=True")
    _scan_limit, lock_ttl, _lease_seconds = _require_stabilization()
    queue_root = _queue_root()
    with queue_write_lock(queue_root, ttl_seconds=lock_ttl):
        queue = _load_queue()
        current = next((item for item in queue.entries if item.entry_id == entry_id), None)
        if current is None:
            raise FileNotFoundError(f"Queue entry does not exist: {entry_id}")
        if current.status != "failed":
            raise RuntimeError("Only a failed queue entry can be requeued")
        if current.attempt_count >= current.max_attempts:
            raise RuntimeError("Queue entry exhausted its explicit maximum attempts")
        now = _utc_now()
        workflow_status = _workflow_status_value(current.job_id, current.workflow_id)
        updated = current.model_copy(
            update={
                "status": "queued",
                "retry_failed_once": workflow_status == "failed",
                "updated_at": now,
                "last_error": None,
                "last_workflow_status": workflow_status,
            }
        )
        entries = [updated if item.entry_id == entry_id else item for item in queue.entries]
        return _save_queue(queue.model_copy(update={"entries": entries}))


def cancel_local_workflow_queue_entry(
    entry_id: str,
    *,
    reason: str,
) -> LocalWorkflowQueue:
    """Cancel future queue dispatch without cancelling or deleting the V0.8 workflow."""

    _validate_portable_id(entry_id, "entry_id")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("queue cancellation reason must not be empty")
    _scan_limit, lock_ttl, _lease_seconds = _require_stabilization()
    queue_root = _queue_root()
    with queue_write_lock(queue_root, ttl_seconds=lock_ttl):
        queue = _load_queue()
        current = next((item for item in queue.entries if item.entry_id == entry_id), None)
        if current is None:
            raise FileNotFoundError(f"Queue entry does not exist: {entry_id}")
        if current.status == "running":
            raise RuntimeError("Running queue entry cannot be cancelled until it finalizes")
        if current.status in {"completed", "cancelled"}:
            raise RuntimeError("Terminal queue entry cannot be cancelled again")
        now = _utc_now()
        updated = current.model_copy(
            update={
                "status": "cancelled",
                "updated_at": now,
                "completed_at": now,
                "last_error": f"Cancelled: {normalized_reason}"[:4000],
                "retry_failed_once": False,
            }
        )
        entries = [updated if item.entry_id == entry_id else item for item in queue.entries]
        return _save_queue(queue.model_copy(update={"entries": entries}))


__all__ = [
    "audit_workspace_state",
    "cancel_local_workflow_queue_entry",
    "enqueue_short_workflow",
    "get_local_workflow_queue",
    "probe_release_environment",
    "requeue_local_workflow",
    "run_local_workflow_queue",
]
