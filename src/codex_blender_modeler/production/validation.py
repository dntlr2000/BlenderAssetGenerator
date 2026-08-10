"""Structural and hash-link validation for V0.9 production-dispatch evidence."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

from ..auto_revision.convergence_session_models import VisualConvergencePlan
from ..blender_artifacts import (
    deterministic_directory_files,
    native_io_path,
    sha256_directory,
    sha256_file,
    stable_json_digest,
)
from ..orchestration.models import WorkflowState
from .models import (
    AssetProductionDispatchPlan,
    AssetProductionDispatchRequest,
    CodexTaskBinding,
    CodexTaskBindingReceipt,
    CodexTaskLaunchManifest,
    DelegatedProductionAdvanceReceipt,
    DelegatedProductionControllerPlan,
    DelegatedProductionState,
    DelegatedWorkAssignment,
    ProductionArtifact,
    ProductionConvergenceBinding,
    ProductionPostflightAuditReceipt,
)

_PORTABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def validate_production_id(value: str, label: str = "production id") -> str:
    """Reject absolute, traversal, device-like, or non-portable production identifiers."""

    if _PORTABLE_ID.fullmatch(value) is None or value.endswith("."):
        raise ValueError(f"{label} is not a portable lowercase identifier")
    stem = value.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", stem):
        raise ValueError(f"{label} uses a reserved Windows device name")
    return value


def _is_link_like(path: Path) -> bool:
    """Detect symbolic links and Windows junctions before production path traversal."""

    native = native_io_path(path)
    if os.path.islink(native):
        return True
    try:
        metadata = os.lstat(native)
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _path_exists(path: Path) -> bool:
    """Check a production path through the extended-length Windows filename."""

    return os.path.exists(native_io_path(path))


def _path_is_file(path: Path) -> bool:
    """Check a regular production file without the Windows MAX_PATH limit."""

    return os.path.isfile(native_io_path(path))


def _path_is_dir(path: Path) -> bool:
    """Check a production directory without the Windows MAX_PATH limit."""

    return os.path.isdir(native_io_path(path))


def ensure_contained_production_path(
    root: Path,
    path: Path,
    *,
    must_exist: bool,
) -> Path:
    """Reject lexical escapes and every existing symlink or junction below a job root."""

    lexical_root = Path(os.path.abspath(os.fspath(root)))
    lexical_path = Path(os.path.abspath(os.fspath(path)))
    if not _path_is_dir(lexical_root):
        raise FileNotFoundError(lexical_root)
    try:
        relative = lexical_path.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError("production path escapes its owning job workspace") from exc
    current = lexical_root
    for component in (Path(), *[Path(part) for part in relative.parts]):
        if component != Path():
            current /= component
        if _is_link_like(current):
            raise ValueError(
                f"production path cannot traverse a symlink or junction: {current.name}"
            )
    resolved_root = lexical_root.resolve(strict=True)
    resolved_path = lexical_path.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("production path resolves outside its owning job workspace") from exc
    if must_exist and not _path_exists(lexical_path):
        raise FileNotFoundError(lexical_path)
    return lexical_path


def resolve_job_relative(root: Path, relative: str) -> Path:
    """Resolve one validated job-relative path without traversing link-like components."""

    return ensure_contained_production_path(
        root,
        root / relative,
        must_exist=False,
    )


def validate_artifact(root: Path, artifact: ProductionArtifact) -> Path:
    """Verify one exact file-or-directory artifact and its SHA-256 binding."""

    path = resolve_job_relative(root, artifact.path)
    if not _path_exists(path):
        raise FileNotFoundError(f"production artifact is missing: {artifact.path}")
    if production_artifact_digest(path, containment_root=root) != artifact.sha256:
        raise ValueError(f"production artifact hash mismatch: {artifact.path}")
    return path


def _safe_directory_files(root: Path, directory: Path) -> list[Path]:
    """Collect regular files recursively while refusing linked or special entries."""

    safe_directory = ensure_contained_production_path(
        root,
        directory,
        must_exist=True,
    )
    files = deterministic_directory_files(safe_directory)
    return [
        ensure_contained_production_path(root, member, must_exist=True)
        for member in files
    ]


def production_artifact_digest(
    path: Path,
    *,
    containment_root: Path | None = None,
) -> str:
    """Match V0.8's digest while rejecting linked or escaping directory members."""

    root = containment_root or (path if _path_is_dir(path) else path.parent)
    safe_path = ensure_contained_production_path(root, path, must_exist=True)
    if _path_is_file(safe_path):
        return sha256_file(safe_path)
    if _path_is_dir(safe_path):
        return sha256_directory(
            safe_path,
            files=_safe_directory_files(root, safe_path),
        )
    raise FileNotFoundError(safe_path)


def collect_workflow_authority_artifacts(
    root: Path,
    workflow_id: str,
) -> list[ProductionArtifact]:
    """Inventory exact V0.8 approval, completion, and attempt authority receipts."""

    artifacts: dict[str, ProductionArtifact] = {}
    for family in (
        "approvals",
        "completions",
        "attempts",
        "policy_targets",
        "policy_authorizations",
    ):
        family_root = resolve_job_relative(root, f"workflows/{workflow_id}/{family}")
        if not family_root.exists():
            continue
        if not family_root.is_dir():
            raise ValueError(f"workflow authority path is not a directory: {family}")
        for path in _safe_directory_files(root, family_root):
            if path.suffix.casefold() != ".json":
                continue
            relative = path.relative_to(root).as_posix()
            artifacts[relative] = ProductionArtifact(
                path=relative,
                sha256=production_artifact_digest(path, containment_root=root),
            )
    return [artifacts[key] for key in sorted(artifacts)]


def validate_workflow_authority_artifacts(
    root: Path,
    workflow_id: str,
    expected: list[ProductionArtifact],
) -> None:
    """Reject changed hashes or membership in terminal V0.8 authority evidence."""

    current = collect_workflow_authority_artifacts(root, workflow_id)
    if [item.model_dump(mode="json") for item in current] != [
        item.model_dump(mode="json") for item in expected
    ]:
        raise ValueError("production workflow authority artifacts are stale or mismatched")
    for artifact in expected:
        validate_artifact(root, artifact)


def workflow_state_fingerprint(
    path: Path,
    *,
    containment_root: Path | None = None,
) -> str:
    """Hash stable V0.8 workflow semantics while ignoring volatile timestamps."""

    safe_path = ensure_contained_production_path(
        containment_root or path.parent,
        path,
        must_exist=True,
    )
    state = WorkflowState.model_validate_json(safe_path.read_text(encoding="utf-8"))
    return stable_json_digest(_without_temporal_fields(state.model_dump(mode="json")))


def controller_tool_profile_digest(launch: CodexTaskLaunchManifest) -> str:
    """Hash every client capability and tool-policy promise required by a launch."""

    return stable_json_digest(
        {
            "controller_tool_policy": launch.controller_tool_policy,
            "controller_mcp_allowlist": launch.controller_mcp_allowlist,
            "controller_forbidden_mcp_tools": launch.controller_forbidden_mcp_tools,
            "controller_shell_policy": launch.controller_shell_policy,
            "client_tool_policy_enforcement_required": (
                launch.client_tool_policy_enforcement_required
            ),
            "required_client_capabilities": launch.required_client_capabilities,
        }
    )


def _without_temporal_fields(value: Any) -> Any:
    """Recursively remove reconciliation-owned timestamp fields from state evidence."""

    if isinstance(value, dict):
        return {
            key: _without_temporal_fields(item)
            for key, item in value.items()
            if not key.endswith("_at")
        }
    if isinstance(value, list):
        return [_without_temporal_fields(item) for item in value]
    return value


def _load_model(root: Path, path: Path, model_type: type[Any]) -> Any:
    """Load one contained strict production model from UTF-8 JSON."""

    safe_path = ensure_contained_production_path(root, path, must_exist=True)
    if not safe_path.is_file():
        raise FileNotFoundError(safe_path)
    return model_type.model_validate_json(safe_path.read_text(encoding="utf-8"))


def _contract_containment_root(path: Path) -> Path:
    """Infer the owning job root for one production contract found by an audit scan."""

    for parent in path.parents:
        if parent.name == "production":
            return parent.parent
    return path.parent


def validate_production_contract_file(path: Path) -> None:
    """Validate a known production JSON file during bounded V0.9 workspace scans."""

    root = _contract_containment_root(path)
    name = path.name
    if name == "dispatch_request.json":
        _load_model(root, path, AssetProductionDispatchRequest)
    elif name == "controller_plan.json":
        _load_model(root, path, DelegatedProductionControllerPlan)
    elif name == "task_launch_manifest.json":
        _load_model(root, path, CodexTaskLaunchManifest)
    elif name == "dispatch_plan.json":
        _load_model(root, path, AssetProductionDispatchPlan)
    elif name == "task_binding.json":
        _load_model(root, path, CodexTaskBinding)
    elif name == "task_binding_receipt.json":
        _load_model(root, path, CodexTaskBindingReceipt)
    elif name == "controller_state.json":
        _load_model(root, path, DelegatedProductionState)
    elif name == "postflight_audit_receipt.json":
        _load_model(root, path, ProductionPostflightAuditReceipt)
    elif name == "convergence_binding.json":
        _load_model(root, path, ProductionConvergenceBinding)
    elif "assignments" in path.parts:
        _load_model(root, path, DelegatedWorkAssignment)
    elif "advances" in path.parts:
        _load_model(root, path, DelegatedProductionAdvanceReceipt)


def validate_dispatch_bundle(
    root: Path,
    dispatch_id: str,
) -> tuple[
    Path,
    AssetProductionDispatchRequest,
    DelegatedProductionControllerPlan,
    CodexTaskLaunchManifest,
    AssetProductionDispatchPlan,
]:
    """Validate one complete dispatch bundle and every immutable cross-file hash."""

    validated_dispatch_id = validate_production_id(dispatch_id, "dispatch_id")
    dispatch_parent = ensure_contained_production_path(
        root,
        root / "production" / "dispatches",
        must_exist=True,
    )
    dispatch_root = ensure_contained_production_path(
        root,
        dispatch_parent / validated_dispatch_id,
        must_exist=True,
    )
    if not dispatch_root.is_dir():
        raise ValueError("production dispatch path is not a directory")
    for directory_name in ("assignments", "advances", "advance_states", "locks"):
        operational = ensure_contained_production_path(
            root,
            dispatch_root / directory_name,
            must_exist=False,
        )
        if operational.exists():
            if not operational.is_dir():
                raise ValueError(
                    f"production operational path is not a directory: {directory_name}"
                )
            production_artifact_digest(operational, containment_root=root)
    ensure_contained_production_path(
        root,
        dispatch_root / ".controller.lock.json",
        must_exist=False,
    )
    request = _load_model(
        root,
        dispatch_root / "dispatch_request.json",
        AssetProductionDispatchRequest,
    )
    controller = _load_model(
        root,
        dispatch_root / "controller_plan.json",
        DelegatedProductionControllerPlan,
    )
    launch = _load_model(
        root,
        dispatch_root / "task_launch_manifest.json",
        CodexTaskLaunchManifest,
    )
    plan = _load_model(
        root,
        dispatch_root / "dispatch_plan.json",
        AssetProductionDispatchPlan,
    )
    identities = {
        (request.dispatch_id, request.controller_id, request.job_id, request.workflow_id),
        (
            controller.dispatch_id,
            controller.controller_id,
            controller.job_id,
            controller.workflow_id,
        ),
        (launch.dispatch_id, launch.controller_id, launch.job_id, launch.workflow_id),
        (plan.dispatch_id, plan.controller_id, plan.job_id, plan.workflow_id),
    }
    if identities != {(dispatch_id, request.controller_id, root.name, request.workflow_id)}:
        raise ValueError("production dispatch identity mismatch")
    if not (
        request.controller_execution_mode
        == launch.launch_mode
        == plan.task_creation_boundary
    ):
        raise ValueError("production controller execution mode mismatch")
    validate_artifact(root, plan.dispatch_request)
    validate_artifact(root, plan.workflow_request)
    validate_artifact(root, plan.workflow_routing)
    workflow_plan_path = validate_artifact(root, plan.workflow_plan)
    validate_artifact(root, plan.controller_plan)
    validate_artifact(root, plan.launch_manifest)
    validate_artifact(root, plan.task_prompt)
    validate_artifact(root, request.primary_reference)
    if controller.workflow_plan.path != plan.workflow_plan.path:
        raise ValueError("controller and dispatch workflow-plan paths differ")
    if controller.workflow_plan.sha256 != sha256_file(workflow_plan_path):
        raise ValueError("controller workflow-plan hash is stale")
    if launch.controller_plan != plan.controller_plan or launch.task_prompt != plan.task_prompt:
        raise ValueError("launch manifest does not match dispatch plan")
    binding_receipt_path = ensure_contained_production_path(
        root,
        dispatch_root / "task_binding_receipt.json",
        must_exist=False,
    )
    if binding_receipt_path.is_file():
        if launch.launch_mode != "client_mediated":
            raise ValueError(
                "desktop_in_session dispatch cannot contain a client task binding"
            )
        if (
            (
                receipt := _load_model(
                    root,
                    binding_receipt_path,
                    CodexTaskBindingReceipt,
                )
            ).dispatch_id
            != dispatch_id
            or receipt.controller_id != request.controller_id
            or receipt.job_id != root.name
            or receipt.workflow_id != request.workflow_id
            or receipt.task_binding.dispatch_id != dispatch_id
            or receipt.task_binding.controller_id != request.controller_id
            or receipt.task_binding.job_id != root.name
            or receipt.task_binding.workflow_id != request.workflow_id
            or receipt.dispatch_plan_sha256
            != sha256_file(dispatch_root / "dispatch_plan.json")
            or receipt.launch_manifest_sha256 != plan.launch_manifest.sha256
            or receipt.task_prompt_sha256 != plan.task_prompt.sha256
            or receipt.task_binding.launch_manifest_sha256
            != plan.launch_manifest.sha256
            or receipt.task_binding.task_prompt_sha256 != plan.task_prompt.sha256
            or receipt.task_binding.controller_tool_profile_sha256
            != controller_tool_profile_digest(launch)
            or receipt.task_binding.client_tool_policy_enforced is not True
        ):
            raise ValueError("Codex task binding receipt is stale or mismatched")
    convergence_binding_path = ensure_contained_production_path(
        root,
        dispatch_root / "convergence_binding.json",
        must_exist=False,
    )
    if convergence_binding_path.is_file():
        if request.convergence.mode != "bounded_after_v06":
            raise ValueError(
                "production convergence binding exists for a disabled dispatch"
            )
        convergence_binding = _load_model(
            root,
            convergence_binding_path,
            ProductionConvergenceBinding,
        )
        current_state_path = ensure_contained_production_path(
            root,
            root / "workflows" / request.workflow_id / "state.json",
            must_exist=True,
        )
        convergence_plan_path = validate_artifact(
            root,
            convergence_binding.convergence_plan,
        )
        convergence_plan = VisualConvergencePlan.model_validate_json(
            convergence_plan_path.read_text(encoding="utf-8")
        )
        validate_artifact(root, convergence_binding.initial_qa_report)
        if (
            convergence_binding.dispatch_id != dispatch_id
            or convergence_binding.controller_id != request.controller_id
            or convergence_binding.job_id != root.name
            or convergence_binding.workflow_id != request.workflow_id
            or convergence_binding.workflow_state_fingerprint
            != workflow_state_fingerprint(current_state_path, containment_root=root)
            or convergence_binding.convergence_session_id
            != convergence_plan.session_id
            or convergence_binding.initial_qa_run_id
            != convergence_plan.initial_qa_run_id
            or convergence_binding.initial_qa_report.sha256
            != convergence_plan.initial_qa_report_sha256
            or convergence_plan.job_id != root.name
        ):
            raise ValueError("production convergence binding is stale or mismatched")
    postflight_path = ensure_contained_production_path(
        root,
        dispatch_root / "postflight_audit_receipt.json",
        must_exist=False,
    )
    if postflight_path.is_file():
        postflight = _load_model(
            root,
            postflight_path,
            ProductionPostflightAuditReceipt,
        )
        current_state_path = ensure_contained_production_path(
            root,
            root / "workflows" / request.workflow_id / "state.json",
            must_exist=True,
        )
        if (
            postflight.dispatch_id != dispatch_id
            or postflight.controller_id != request.controller_id
            or postflight.job_id != root.name
            or postflight.workflow_id != request.workflow_id
            or postflight.dispatch_plan_sha256
            != sha256_file(dispatch_root / "dispatch_plan.json")
            or postflight.workflow_state_fingerprint
            != workflow_state_fingerprint(current_state_path, containment_root=root)
            or postflight.audit_report.job_filter != root.name
        ):
            raise ValueError("production postflight audit receipt is stale or mismatched")
        for artifact in postflight.terminal_artifacts:
            validate_artifact(root, artifact)
        validate_workflow_authority_artifacts(
            root,
            request.workflow_id,
            postflight.workflow_authority_artifacts,
        )
    previous_hash: str | None = None
    advances = ensure_contained_production_path(
        root,
        dispatch_root / "advances",
        must_exist=False,
    )
    if advances.is_dir():
        receipts = sorted(advances.glob("*.json"))
        for expected_sequence, receipt_path in enumerate(receipts, start=1):
            receipt = _load_model(
                root,
                receipt_path,
                DelegatedProductionAdvanceReceipt,
            )
            if receipt.sequence != expected_sequence:
                raise ValueError("production advance receipt sequence is not contiguous")
            if receipt.previous_receipt_sha256 != previous_hash:
                raise ValueError("production advance receipt hash chain is broken")
            if (
                receipt.dispatch_id != dispatch_id
                or receipt.controller_id != request.controller_id
                or receipt.job_id != root.name
                or receipt.workflow_id != request.workflow_id
                or receipt.dispatch_plan_sha256 != sha256_file(
                    dispatch_root / "dispatch_plan.json"
                )
            ):
                raise ValueError("production advance receipt identity mismatch")
            if receipt.assignment is not None:
                validate_artifact(root, receipt.assignment)
            if receipt.task_binding is not None:
                validate_artifact(root, receipt.task_binding)
            if receipt.postflight_audit is not None:
                validate_artifact(root, receipt.postflight_audit)
            if receipt.convergence_artifact is not None:
                validate_artifact(root, receipt.convergence_artifact)
            before_state = validate_artifact(root, receipt.workflow_state_before)
            after_state = validate_artifact(root, receipt.workflow_state_after)
            WorkflowState.model_validate_json(before_state.read_text(encoding="utf-8"))
            WorkflowState.model_validate_json(after_state.read_text(encoding="utf-8"))
            if (
                receipt.workflow_state_before_sha256 != sha256_file(before_state)
                or receipt.workflow_state_after_sha256 != sha256_file(after_state)
            ):
                raise ValueError("production advance workflow-state snapshot mismatch")
            previous_hash = sha256_file(receipt_path)
    controller_state_path = ensure_contained_production_path(
        root,
        dispatch_root / "controller_state.json",
        must_exist=False,
    )
    if controller_state_path.is_file():
        _load_model(root, controller_state_path, DelegatedProductionState)
    return dispatch_root, request, controller, launch, plan
