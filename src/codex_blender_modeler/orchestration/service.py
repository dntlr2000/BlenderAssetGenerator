"""Shared V0.8 planning, reconciliation, approval, and resumable host execution."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..analysis import analyze_job_reference
from ..architecture import validate_job_interior_scope
from ..blender_artifact_runner import inspect_job_materials, render_job_material_swatches
from ..blender_artifacts import stable_json_digest, write_json_atomic
from ..blender_runner import run_blender
from ..config import load_feature_config
from ..materials import create_material_scaffold, validate_job_material_contracts
from ..optimization import (
    initialize_asset_profile,
    optimize_asset,
    plan_asset_optimization,
    preflight_asset,
)
from ..optimization.io import validate_filesystem_id
from ..packaging import package_asset, validate_asset_package
from ..packaging.material_conversion import convert_portable_materials
from ..qa import run_job_visual_qa
from ..reporting import generate_job_pdf_report
from ..revision import apply_revision_plan
from ..validation import load_scene_spec
from ..workspace import (
    add_job_view,
    archive_scene_spec,
    create_job,
    ensure_job_dirs,
    find_reference,
    job_dir,
    load_job,
    sha256_file,
    validate_job_id,
    validate_new_job_id,
)
from .locks import workflow_write_lock
from .models import (
    ArtifactFreshness,
    ArtifactRequirement,
    DestinationRequest,
    IntentRouting,
    WorkflowApproval,
    WorkflowAttempt,
    WorkflowBudgets,
    WorkflowInputArtifact,
    WorkflowPlan,
    WorkflowRequest,
    WorkflowState,
    WorkflowStep,
    WorkflowStepCompletion,
    WorkflowStepState,
)
from .planner import build_workflow_plan
from .router import destination_adapters, route_intent

_GENERIC_GATES = {
    "proxy_geometry",
    "detailed_geometry",
    "material_swatches",
    "qa_review",
    "final_package",
}
_VIEW_KINDS = {"front", "right", "top", "blueprint", "cad"}


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for workflow receipts."""

    return datetime.now(UTC)


def _require_orchestration() -> int:
    """Require the V0.8 feature flag and return its configured lock TTL."""

    config = load_feature_config()
    if not config.features.workflow_orchestration:
        raise RuntimeError("workflow_orchestration is disabled in cbm.toml")
    return config.orchestration.lock_ttl_seconds


def _new_workflow_id() -> str:
    """Create a portable sortable workflow identifier."""

    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ").lower()
    return f"wf-{stamp}-{uuid4().hex[:8]}"


def _slugify_job_id(reference_path: Path) -> str:
    """Derive a safe lowercase job prefix without depending on non-ASCII filenames."""

    stem = reference_path.stem.casefold()
    stem = re.sub(r"[^a-z0-9_-]+", "-", stem).strip("-_") or "asset"
    suffix = _utc_now().strftime("%y%m%d%H%M%S").lower() + uuid4().hex[:4]
    return f"{stem[:44]}-{suffix}"[:64]


def _workflow_dir(root: Path, workflow_id: str) -> Path:
    """Resolve one contained workflow directory from a portable identifier."""

    validate_filesystem_id(workflow_id, "workflow_id")
    parent = (root / "workflows").resolve()
    candidate = (parent / workflow_id).resolve()
    try:
        candidate.relative_to(parent)
    except ValueError as exc:
        raise ValueError("workflow directory must stay inside the job workspace") from exc
    return candidate


def _job_relative(root: Path, path: Path) -> str:
    """Convert one contained path to normalized POSIX job-relative syntax."""

    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"Workflow artifact is outside the job workspace: {resolved}") from exc


def _resolve_job_path(root: Path, relative: str) -> Path:
    """Resolve a validated relative artifact path without following an escape."""

    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Workflow artifact escapes the job workspace: {relative}") from exc
    return candidate


def _write_immutable(path: Path, payload: dict[str, Any]) -> None:
    """Write one immutable workflow contract and reject accidental overwrite."""

    if path.exists():
        raise FileExistsError(f"Immutable workflow artifact already exists: {path}")
    write_json_atomic(path, payload)


def _load_model(path: Path, model_type: type[Any]) -> Any:
    """Load one required strict workflow model from UTF-8 JSON."""

    if not path.is_file():
        raise FileNotFoundError(path)
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def _profile_from_request(request_text: str, profile_id: str) -> str:
    """Honor an explicitly named interchange format without guessing a destination engine."""

    normalized = request_text.casefold()
    if profile_id != "portable_gltf":
        return profile_id
    if re.search(r"\bfbx\b", normalized):
        return "fbx_interchange"
    if re.search(r"\bobj\b", normalized):
        return "obj_legacy"
    return "portable_gltf"


def _default_scope(intent: str, scope: str) -> str:
    """Apply conservative stage boundaries only when the caller leaves scope automatic."""

    if scope != "auto":
        return scope
    return {
        "new_asset": "proxy_only",
        "revise_asset": "geometry_only",
        "add_measured_view": "analysis_only",
        "interior_scope": "interior_only",
        "material_authoring": "material_only",
        "visual_qa": "qa_only",
        "portable_package": "portable_only",
    }[intent]


def _source_artifact(root: Path, path: Path, kind: str) -> WorkflowInputArtifact:
    """Record one already copied job-local source without exposing its original absolute path."""

    return WorkflowInputArtifact(
        kind=kind,  # type: ignore[arg-type]
        path=_job_relative(root, path),
        sha256=sha256_file(path),
    )


def _stage_auxiliary_view(
    root: Path,
    workflow_root: Path,
    source_path: Path,
    view_kind: str,
) -> WorkflowInputArtifact:
    """Copy an auxiliary view into workflow-owned staging before canonical promotion."""

    source = source_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    if view_kind != "cad" and suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Measured image view must use PNG, JPEG, or WEBP")
    destination = workflow_root / "inputs" / f"{view_kind}{suffix or '.dat'}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)
    return _source_artifact(root, destination, view_kind)


def _matching_primary_reference(job_id: str, candidate: Path) -> bool:
    """Return whether an existing-job reference argument matches immutable primary evidence."""

    source = candidate.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    return sha256_file(source) == sha256_file(find_reference(job_id))


def _initial_intent(
    intent: str,
    *,
    new_job: bool,
    view_kind: str | None,
    request_text: str,
    job_id: str,
    workflow_id: str,
    destination: DestinationRequest,
) -> IntentRouting:
    """Route early so the normalized scope can be persisted in the immutable request."""

    return route_intent(
        workflow_id=workflow_id,
        job_id=job_id,
        request_text=request_text,
        intent_hint=intent,
        new_job=new_job,
        has_staged_view=view_kind is not None,
        destination=destination,
    )


def plan_workflow(
    request_text: str,
    *,
    job_id: str | None = None,
    reference_path: str | Path | None = None,
    intent: str = "auto",
    scope: str = "auto",
    mode: str = "concept",
    view_kind: str | None = None,
    replace_view: bool = False,
    scale_anchors: list[str] | None = None,
    profile_id: str = "portable_gltf",
    destination_kind: str = "unspecified",
    destination_name: str | None = None,
    destination_version: str | None = None,
    budgets: WorkflowBudgets | None = None,
) -> WorkflowState:
    """Create one isolated routed plan without bypassing any downstream approval gate."""

    lock_ttl = _require_orchestration()
    normalized_request = request_text.strip()
    if not normalized_request:
        raise ValueError("workflow request must not be empty")
    if mode not in {"concept", "measured"}:
        raise ValueError("mode must be concept or measured")
    if intent not in {
        "auto",
        "new_asset",
        "revise_asset",
        "add_measured_view",
        "interior_scope",
        "material_authoring",
        "visual_qa",
        "portable_package",
    }:
        raise ValueError("unsupported workflow intent")
    if scope not in {
        "auto",
        "analysis_only",
        "proxy_only",
        "geometry_only",
        "interior_only",
        "material_only",
        "qa_only",
        "portable_only",
        "full",
    }:
        raise ValueError("unsupported workflow scope")
    if profile_id not in {"portable_gltf", "fbx_interchange", "obj_legacy"}:
        raise ValueError("unsupported portable profile")
    normalized_view = view_kind.strip().lower() if view_kind else None
    if normalized_view is not None and normalized_view not in _VIEW_KINDS:
        raise ValueError("view_kind must be front, right, top, blueprint, or cad")
    reference = Path(reference_path).expanduser().resolve() if reference_path else None
    existing = bool(job_id and (job_dir(validate_job_id(job_id)) / "job.json").is_file())
    if existing and intent == "new_asset":
        raise FileExistsError(
            "Existing job cannot start a new_asset workflow, even when the reference "
            "matches. Use revise_asset for the current asset or choose a new job_id."
        )
    if existing and reference is not None and normalized_view is None:
        if not _matching_primary_reference(str(job_id), reference):
            raise FileExistsError(
                "Existing job ID cannot be reused for a different reference. Use a new job ID "
                "or provide an explicit auxiliary view kind."
            )
    new_job = not existing
    if new_job and reference is None:
        raise ValueError("new asset workflow requires reference_path")
    if new_job and normalized_view is not None:
        raise ValueError(
            "A new job requires a primary reference first; add auxiliary views in a later "
            "add_measured_view workflow."
        )
    selected_job_id = job_id or _slugify_job_id(reference or Path("asset.png"))
    if new_job:
        validate_new_job_id(selected_job_id)
        if intent not in {"auto", "new_asset"}:
            raise ValueError("a missing job can only start with new_asset intent")
    else:
        validate_job_id(selected_job_id)
    workflow_id = _new_workflow_id()
    destination = DestinationRequest(
        kind=destination_kind,  # type: ignore[arg-type]
        name=destination_name,
        version=destination_version,
    )
    routing = _initial_intent(
        intent,
        new_job=new_job,
        view_kind=normalized_view,
        request_text=normalized_request,
        job_id=selected_job_id,
        workflow_id=workflow_id,
        destination=destination,
    )
    selected_scope = _default_scope(routing.intent, scope)
    if new_job:
        create_job(
            selected_job_id,
            reference or Path(),
            mode,
            scale_anchors or [],
        )
    root = ensure_job_dirs(selected_job_id)
    workflow_root = _workflow_dir(root, workflow_id)
    with workflow_write_lock(
        root,
        selected_job_id,
        workflow_id,
        ttl_seconds=lock_ttl,
    ):
        workflow_root.mkdir(parents=True, exist_ok=False)
        staged_view = None
        if normalized_view is not None:
            if reference is None:
                raise ValueError("add_measured_view requires reference_path for the new view")
            staged_view = _stage_auxiliary_view(
                root,
                workflow_root,
                reference,
                normalized_view,
            )
        primary = _source_artifact(root, find_reference(selected_job_id), "reference")
        request = WorkflowRequest(
            workflow_id=workflow_id,
            job_id=selected_job_id,
            raw_request=normalized_request,
            intent_hint=intent,  # type: ignore[arg-type]
            requested_scope=selected_scope,  # type: ignore[arg-type]
            mode=mode,  # type: ignore[arg-type]
            primary_reference=primary,
            staged_view=staged_view,
            replace_existing_view=replace_view,
            scale_anchors=scale_anchors or [],
            profile_id=_profile_from_request(normalized_request, profile_id),  # type: ignore[arg-type]
            destination=routing.destination.requested,
            budgets=budgets or WorkflowBudgets(),
            created_at=_utc_now(),
        )
        request_path = workflow_root / "request.json"
        routing_path = workflow_root / "routing.json"
        _write_immutable(request_path, request.model_dump(mode="json"))
        _write_immutable(routing_path, routing.model_dump(mode="json"))
        plan = build_workflow_plan(
            request,
            routing,
            request_sha256=sha256_file(request_path),
            routing_sha256=sha256_file(routing_path),
        )
        _write_immutable(
            workflow_root / "plan.json",
            plan.model_dump(mode="json"),
        )
        state = _reconcile_locked(root, workflow_root, plan, request, previous=None)
        write_json_atomic(workflow_root / "state.json", state.model_dump(mode="json"))
        write_json_atomic(
            root / "workflows" / "latest.json",
            {
                "schema_version": "0.8.0",
                "job_id": selected_job_id,
                "workflow_id": workflow_id,
                "status": state.status,
                "updated_at": state.updated_at.isoformat(),
            },
        )
        return state


def _artifact_digest(path: Path) -> str:
    """Hash one file or deterministic directory listing for state reconstruction."""

    if path.is_file():
        return sha256_file(path)
    records = [
        {
            "path": item.relative_to(path).as_posix(),
            "sha256": sha256_file(item),
        }
        for item in sorted(path.rglob("*"))
        if item.is_file()
    ]
    return stable_json_digest(records)


def _validate_known_json_contract(
    requirement: ArtifactRequirement,
    payload: dict[str, Any],
) -> None:
    """Validate agent-authored canonical JSON with its existing strict host contract."""

    relative_path = requirement.path
    if relative_path == "analysis/modeling_plan.json":
        from ..analysis.models import ModelingPlan

        ModelingPlan.model_validate(payload)
    elif relative_path == "analysis/scene_spec.json":
        from ..models import SceneSpec

        SceneSpec.model_validate(payload)
    elif relative_path == "analysis/revision_plan.json":
        from ..revision import RevisionPlan

        RevisionPlan.model_validate(payload)
    elif relative_path == "architecture/interior_scope.json":
        from ..architecture.models import InteriorScope

        InteriorScope.model_validate(payload)
    elif relative_path == "analysis/material_plan.json":
        from ..materials.models import MaterialPlan

        MaterialPlan.model_validate(payload)


def _validate_agent_completion_semantics(root: Path, step: WorkflowStep) -> None:
    """Require authored-stage semantics only when an agent records completion."""

    for requirement in step.outputs:
        path = _resolve_job_path(root, requirement.path)
        if requirement.path == "analysis/modeling_plan.json":
            from ..analysis.models import ModelingPlan

            plan = ModelingPlan.model_validate_json(path.read_text(encoding="utf-8"))
            if "modeling_plan.output" in requirement.artifact_id and plan.stage != "authored":
                raise RuntimeError("agent completion requires modeling_plan stage=authored")
        elif requirement.path == "analysis/material_plan.json":
            from ..materials.models import MaterialPlan

            plan = MaterialPlan.model_validate_json(path.read_text(encoding="utf-8"))
            if "plan.authored" in requirement.artifact_id and plan.stage != "authored":
                raise RuntimeError("agent completion requires material_plan stage=authored")


def _inspect_artifact(
    root: Path,
    requirement: ArtifactRequirement,
    previous: ArtifactFreshness | None,
) -> ArtifactFreshness:
    """Inspect artifact integrity independently from currency and semantic verification."""

    path = _resolve_job_path(root, requirement.path)
    if not path.exists():
        return ArtifactFreshness(
            artifact_id=requirement.artifact_id,
            path=requirement.path,
            integrity="missing",
            currency="unknown",
            verification="unverified",
            reason="Required artifact does not exist.",
        )
    if requirement.acceptance == "nonempty_directory":
        valid = path.is_dir() and any(path.iterdir())
        payload = None
    else:
        valid = path.is_file()
        payload = None
        if valid and requirement.acceptance in {"valid_json", "json_ok"}:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                valid = isinstance(payload, dict)
                if valid:
                    _validate_known_json_contract(requirement, payload)
            except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
                valid = False
        if valid and requirement.acceptance == "json_ok":
            valid = bool(
                isinstance(payload, dict)
                and (
                    payload.get("ok") is True
                    or payload.get("status") in {"passed", "complete", "approved"}
                )
            )
    if not valid:
        return ArtifactFreshness(
            artifact_id=requirement.artifact_id,
            path=requirement.path,
            sha256=_artifact_digest(path) if path.is_file() else None,
            integrity="corrupt",
            currency="unknown",
            verification="unverified",
            reason=f"Artifact failed acceptance rule {requirement.acceptance}.",
        )
    digest = _artifact_digest(path)
    currency = (
        "superseded"
        if previous is not None and previous.sha256 is not None and previous.sha256 != digest
        else "current"
    )
    verification = (
        "verified"
        if requirement.acceptance == "json_ok"
        else "partially_verified"
        if requirement.acceptance == "valid_json"
        else "unverified"
    )
    return ArtifactFreshness(
        artifact_id=requirement.artifact_id,
        path=requirement.path,
        sha256=digest,
        integrity="valid",
        currency=currency,
        verification=verification,
        reason=(
            "Artifact changed since the previous state snapshot."
            if currency == "superseded"
            else "Artifact is structurally available for the current state snapshot."
        ),
    )


def _artifact_fingerprint(artifacts: list[ArtifactFreshness]) -> str:
    """Hash exact artifact identities and bytes for completion and approval binding."""

    return stable_json_digest(
        [
            {
                "artifact_id": item.artifact_id,
                "path": item.path,
                "sha256": item.sha256,
                "integrity": item.integrity,
            }
            for item in artifacts
        ]
    )


def _step_input_fingerprint(
    plan: WorkflowPlan,
    request: WorkflowRequest,
    step: WorkflowStep,
    states: dict[str, WorkflowStepState],
) -> str:
    """Hash the plan, request, and exact dependency completion fingerprints."""

    return stable_json_digest(
        {
            "plan_sha256": sha256_file(
                _workflow_dir(job_dir(plan.job_id), plan.workflow_id) / "plan.json"
            ),
            "request_sha256": plan.request_sha256,
            "step_id": step.step_id,
            "parameters": step.parameters,
            "dependencies": {
                dependency: states[dependency].completion_fingerprint
                for dependency in step.depends_on
            },
            "primary_reference_sha256": (
                request.primary_reference.sha256 if request.primary_reference else None
            ),
        }
    )


def _completion_path(workflow_root: Path, step_id: str) -> Path:
    """Resolve one fixed completion-marker path from a validated step identifier."""

    return workflow_root / "completions" / f"{step_id}.json"


def _approval_path(workflow_root: Path, step_id: str) -> Path:
    """Resolve one fixed generic-approval path from a validated step identifier."""

    return workflow_root / "approvals" / f"{step_id}.json"


def _load_completion(
    workflow_root: Path,
    step: WorkflowStep,
) -> WorkflowStepCompletion | None:
    """Load an optional agent/manual completion marker without accepting alternate paths."""

    path = _completion_path(workflow_root, step.step_id)
    return _load_model(path, WorkflowStepCompletion) if path.is_file() else None


def _load_approval(
    workflow_root: Path,
    step: WorkflowStep,
) -> WorkflowApproval | None:
    """Load an optional exact generic-gate approval receipt."""

    path = _approval_path(workflow_root, step.step_id)
    return _load_model(path, WorkflowApproval) if path.is_file() else None


def _specialized_approval_valid(
    root: Path,
    step: WorkflowStep,
    artifacts: list[ArtifactFreshness],
) -> bool:
    """Validate specialized approvals against their exact current source hashes."""

    if not artifacts or any(item.integrity != "valid" for item in artifacts):
        return False
    if step.approval_gate == "interior_scope":
        scope = root / "architecture" / "interior_scope.json"
        approval = root / "architecture" / "interior_scope.approval.json"
        if not scope.is_file() or not approval.is_file():
            return False
        try:
            payload = json.loads(approval.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(
            isinstance(payload, dict)
            and payload.get("status") == "approved"
            and payload.get("scope_sha256") == sha256_file(scope)
        )
    if step.approval_gate == "optimization_plan":
        run_id = str(step.parameters["run_id"])
        directory = root / "optimization" / "runs" / run_id
        plan_path = directory / "review_plan.json"
        approval_path = directory / "optimization_approval.json"
        if not plan_path.is_file() or not approval_path.is_file():
            return False
        try:
            payload = json.loads(approval_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(
            isinstance(payload, dict)
            and payload.get("status") in {"approved", "consumed"}
            and payload.get("plan_sha256") == sha256_file(plan_path)
        )
    if step.approval_gate == "visual_revision":
        return False
    return False


def _step_milestone(completed_ids: set[str]) -> str:
    """Map completed checkpoint steps onto the documented V0.8 milestone vocabulary."""

    if "portable.final_approval" in completed_ids:
        return "portable_ready"
    if "qa.review" in completed_ids:
        return "qa_review"
    if "material.approval" in completed_ids:
        return "material_ready"
    if "interior.scope_approval" in completed_ids:
        return "interior_scope_approved"
    if "interior.scope_author" in completed_ids:
        return "interior_scope_waiting"
    if "geometry.detail_approval" in completed_ids or "revision.validate" in completed_ids:
        return "geometry_approved"
    if "geometry.proxy_approval" in completed_ids:
        return "geometry_approved"
    if "proxy.validate" in completed_ids:
        return "proxy_ready"
    if "reference.analyze" in completed_ids:
        return "analyzed"
    return "created"


def _next_action(step: WorkflowStep, input_fingerprint: str) -> str:
    """Describe the next exact tool or approval action without executing agent judgment."""

    if step.execution_mode == "host":
        return f"Resume to execute host tool {step.tool_name} for step {step.step_id}."
    if step.execution_mode == "agent":
        return (
            f"Use {step.tool_name} for step {step.step_id}, then record completion with "
            f"input fingerprint {input_fingerprint}."
        )
    if step.execution_mode == "approval":
        return (
            f"Review gate {step.approval_gate} and approve only artifact fingerprint "
            f"{input_fingerprint}."
        )
    if step.execution_mode == "specialized_approval":
        return (
            f"Complete the specialized {step.approval_gate} approval flow for step "
            f"{step.step_id}; generic workflow approval cannot substitute for it."
        )
    return "A validated destination adapter is unavailable; retain the portable package."


def _reconcile_locked(
    root: Path,
    workflow_root: Path,
    plan: WorkflowPlan,
    request: WorkflowRequest,
    *,
    previous: WorkflowState | None,
) -> WorkflowState:
    """Reconstruct workflow state from immutable artifacts, markers, and exact approvals."""

    plan_path = workflow_root / "plan.json"
    request_path = workflow_root / "request.json"
    actual_plan_hash = sha256_file(plan_path)
    actual_request_hash = sha256_file(request_path)
    if actual_request_hash != plan.request_sha256:
        raise RuntimeError("Workflow request changed after plan creation")
    if request.job_id != plan.job_id or request.workflow_id != plan.workflow_id:
        raise RuntimeError("Workflow request and plan identities do not match")
    previous_states = {item.step_id: item for item in previous.steps} if previous else {}
    states: dict[str, WorkflowStepState] = {}
    current_step: WorkflowStep | None = None
    waiting_gate = None
    aggregate_status = "planned"
    warnings: list[str] = []
    for step in plan.steps:
        prior = previous_states.get(step.step_id)
        prior_artifacts = {item.artifact_id: item for item in prior.artifacts} if prior else {}
        artifacts = [
            _inspect_artifact(root, output, prior_artifacts.get(output.artifact_id))
            for output in step.outputs
        ]
        dependencies_complete = all(
            states[dependency].status == "complete" for dependency in step.depends_on
        )
        input_fingerprint = _step_input_fingerprint(plan, request, step, states)
        artifact_fingerprint = _artifact_fingerprint(artifacts)
        artifacts_valid = all(item.integrity == "valid" for item in artifacts)
        status = "pending"
        completion_fingerprint = None
        approval_id = None
        error = None
        started_at = prior.started_at if prior else None
        completed_at = prior.completed_at if prior else None
        attempt_count = prior.attempt_count if prior else 0
        if previous is not None and previous.status == "cancelled":
            status = "cancelled"
        elif not dependencies_complete:
            status = "pending"
        elif step.execution_mode == "agent":
            completion = _load_completion(workflow_root, step)
            if completion is not None:
                valid_completion = (
                    completion.plan_sha256 == actual_plan_hash
                    and completion.input_fingerprint == input_fingerprint
                    and completion.output_fingerprint == artifact_fingerprint
                    and artifacts_valid
                )
                if valid_completion:
                    status = "complete"
                    completion_fingerprint = stable_json_digest(
                        {
                            "input": input_fingerprint,
                            "output": artifact_fingerprint,
                            "completion_id": completion.completion_id,
                        }
                    )
                    completed_at = completion.recorded_at
                else:
                    status = "stale"
                    error = "Agent completion marker is stale relative to current inputs/outputs."
            else:
                status = "waiting_for_agent"
        elif step.execution_mode == "approval":
            approval = _load_approval(workflow_root, step)
            if approval is not None:
                valid_approval = (
                    approval.plan_sha256 == actual_plan_hash
                    and approval.artifact_fingerprint == input_fingerprint
                    and approval.step_id == step.step_id
                    and artifacts_valid
                )
                if valid_approval:
                    status = "complete"
                    approval_id = approval.approval_id
                    completion_fingerprint = stable_json_digest(
                        {"input": input_fingerprint, "approval_id": approval.approval_id}
                    )
                    completed_at = approval.approved_at
                else:
                    status = "stale"
                    error = "Workflow approval is stale relative to current evidence."
            else:
                status = "waiting_for_approval"
        elif step.execution_mode == "specialized_approval":
            if _specialized_approval_valid(root, step, artifacts):
                status = "complete"
                completion_fingerprint = stable_json_digest(
                    {"input": input_fingerprint, "output": artifact_fingerprint}
                )
                completed_at = _utc_now()
            else:
                status = "waiting_for_approval"
        elif step.execution_mode == "manual":
            status = "blocked"
            error = "No validated destination adapter is available."
        else:
            same_input = prior is not None and prior.input_fingerprint == input_fingerprint
            same_outputs = bool(
                prior
                and artifacts
                and len(prior.artifacts) == len(artifacts)
                and all(
                    old.sha256 == new.sha256
                    for old, new in zip(prior.artifacts, artifacts, strict=True)
                )
            )
            require_new = bool(step.parameters.get("require_new_output", False))
            can_adopt = previous is None and not require_new
            if artifacts_valid and (
                (prior is not None and prior.status == "complete" and same_input and same_outputs)
                or can_adopt
                or (prior is not None and not same_outputs)
                or step.tool_name in {"create_job", "verify_geometry_prerequisite"}
            ):
                status = "complete"
                completion_fingerprint = stable_json_digest(
                    {"input": input_fingerprint, "output": artifact_fingerprint}
                )
                completed_at = completed_at or _utc_now()
            elif prior is not None and prior.status == "failed" and same_input:
                status = "failed"
                error = prior.error
            elif artifacts and any(item.integrity == "corrupt" for item in artifacts):
                status = "blocked"
                error = "One or more host-step outputs are corrupt."
            else:
                status = "ready"
        state = WorkflowStepState(
            step_id=step.step_id,
            status=status,  # type: ignore[arg-type]
            input_fingerprint=input_fingerprint,
            completion_fingerprint=completion_fingerprint,
            attempt_count=attempt_count,
            artifacts=artifacts,
            approval_id=approval_id,
            started_at=started_at,
            completed_at=completed_at,
            error=error,
        )
        states[step.step_id] = state
        if step.step_id == plan.terminal_step_id and status == "complete":
            break
        if current_step is None and status != "complete":
            current_step = step
            if status == "waiting_for_agent":
                aggregate_status = "waiting_for_agent"
            elif status == "waiting_for_approval":
                aggregate_status = "waiting_for_approval"
                waiting_gate = step.approval_gate
            elif status in {"blocked", "stale"}:
                aggregate_status = "blocked"
            elif status == "failed":
                aggregate_status = "failed"
            else:
                aggregate_status = "running" if previous else "planned"
    ordered_states = [states[step.step_id] for step in plan.steps if step.step_id in states]
    completed_ids = {item.step_id for item in ordered_states if item.status == "complete"}
    terminal_state = states.get(
        plan.terminal_step_id,
        WorkflowStepState(step_id="missing"),
    )
    terminal_complete = terminal_state.status == "complete"
    if previous is not None and previous.status == "cancelled":
        aggregate_status = "cancelled"
        current_step = None
    elif terminal_complete:
        aggregate_status = "completed"
        current_step = None
    milestone = _step_milestone(completed_ids)
    if aggregate_status == "completed":
        milestone = "completed"
    if plan.destination.status == "unsupported":
        warnings.append(plan.destination.reason)
    now = _utc_now()
    state = WorkflowState(
        workflow_id=plan.workflow_id,
        job_id=plan.job_id,
        plan_sha256=actual_plan_hash,
        request_sha256=actual_request_hash,
        status=aggregate_status,  # type: ignore[arg-type]
        milestone=milestone,  # type: ignore[arg-type]
        current_step_id=current_step.step_id if current_step else None,
        steps=ordered_states,
        next_action=(
            _next_action(
                current_step,
                states[current_step.step_id].input_fingerprint or stable_json_digest({}),
            )
            if current_step
            else None
        ),
        waiting_gate=waiting_gate,  # type: ignore[arg-type]
        warnings=warnings,
        cancelled_reason=previous.cancelled_reason if previous else None,
        created_at=previous.created_at if previous else now,
        updated_at=now,
    )
    return state


def _load_workflow(
    job_id: str,
    workflow_id: str,
) -> tuple[Path, Path, WorkflowRequest, WorkflowPlan, WorkflowState | None]:
    """Load one workflow's immutable request/plan and optional mutable state."""

    root = job_dir(job_id)
    load_job(job_id)
    workflow_root = _workflow_dir(root, workflow_id)
    request = _load_model(workflow_root / "request.json", WorkflowRequest)
    plan = _load_model(workflow_root / "plan.json", WorkflowPlan)
    state_path = workflow_root / "state.json"
    previous = _load_model(state_path, WorkflowState) if state_path.is_file() else None
    if request.job_id != job_id or plan.job_id != job_id:
        raise ValueError("workflow belongs to another job")
    return root, workflow_root, request, plan, previous


def _write_state(root: Path, workflow_root: Path, state: WorkflowState) -> None:
    """Atomically persist state and the job's latest-workflow pointer."""

    write_json_atomic(workflow_root / "state.json", state.model_dump(mode="json"))
    write_json_atomic(
        root / "workflows" / "latest.json",
        {
            "schema_version": "0.8.0",
            "job_id": state.job_id,
            "workflow_id": state.workflow_id,
            "status": state.status,
            "updated_at": state.updated_at.isoformat(),
        },
    )


def reconcile_workflow(job_id: str, workflow_id: str) -> WorkflowState:
    """Rebuild current state from files and exact receipts without executing a step."""

    lock_ttl = _require_orchestration()
    root, workflow_root, request, plan, previous = _load_workflow(job_id, workflow_id)
    with workflow_write_lock(root, job_id, workflow_id, ttl_seconds=lock_ttl):
        state = _reconcile_locked(root, workflow_root, plan, request, previous=previous)
        _write_state(root, workflow_root, state)
        return state


def get_workflow_status(job_id: str, workflow_id: str | None = None) -> dict[str, Any]:
    """Read the latest persisted state without mutating or implicitly resuming work."""

    root = job_dir(job_id)
    load_job(job_id)
    selected = workflow_id
    if selected is None:
        latest = root / "workflows" / "latest.json"
        if not latest.is_file():
            return {"job_id": job_id, "workflow": None, "status": "not_started"}
        payload = json.loads(latest.read_text(encoding="utf-8"))
        selected = str(payload.get("workflow_id", ""))
    workflow_root = _workflow_dir(root, selected)
    state = _load_model(workflow_root / "state.json", WorkflowState)
    return {
        "job_id": job_id,
        "workflow_id": selected,
        "workflow_root": _job_relative(root, workflow_root),
        "state": state.model_dump(mode="json"),
    }


def complete_workflow_step(
    job_id: str,
    workflow_id: str,
    step_id: str,
    *,
    input_fingerprint: str,
    note: str,
) -> WorkflowState:
    """Record an exact agent/manual completion marker after validating current outputs."""

    lock_ttl = _require_orchestration()
    root, workflow_root, request, plan, previous = _load_workflow(job_id, workflow_id)
    with workflow_write_lock(root, job_id, workflow_id, ttl_seconds=lock_ttl):
        state = _reconcile_locked(root, workflow_root, plan, request, previous=previous)
        step = next((item for item in plan.steps if item.step_id == step_id), None)
        if step is None:
            raise ValueError(f"Unknown workflow step: {step_id}")
        if step.execution_mode not in {"agent", "manual"}:
            raise ValueError("Only agent/manual steps accept completion markers")
        step_state = next(item for item in state.steps if item.step_id == step_id)
        if step_state.input_fingerprint != input_fingerprint:
            raise ValueError("Completion input fingerprint does not match current workflow state")
        if not step_state.artifacts or any(
            item.integrity != "valid" for item in step_state.artifacts
        ):
            raise RuntimeError("Completion outputs are missing or invalid")
        _validate_agent_completion_semantics(root, step)
        marker = WorkflowStepCompletion(
            completion_id=f"completion-{uuid4().hex}",
            workflow_id=workflow_id,
            job_id=job_id,
            step_id=step_id,
            plan_sha256=sha256_file(workflow_root / "plan.json"),
            input_fingerprint=input_fingerprint,
            output_fingerprint=_artifact_fingerprint(step_state.artifacts),
            output_artifacts=step_state.artifacts,
            note=note,
            recorded_at=_utc_now(),
        )
        _write_immutable(
            _completion_path(workflow_root, step_id),
            marker.model_dump(mode="json"),
        )
        updated = _reconcile_locked(root, workflow_root, plan, request, previous=state)
        _write_state(root, workflow_root, updated)
        return updated


def approve_workflow_gate(
    job_id: str,
    workflow_id: str,
    step_id: str,
    *,
    artifact_fingerprint: str,
    approval_note: str,
) -> WorkflowState:
    """Approve one exact generic checkpoint without authorizing specialized/future gates."""

    lock_ttl = _require_orchestration()
    root, workflow_root, request, plan, previous = _load_workflow(job_id, workflow_id)
    with workflow_write_lock(root, job_id, workflow_id, ttl_seconds=lock_ttl):
        state = _reconcile_locked(root, workflow_root, plan, request, previous=previous)
        step = next((item for item in plan.steps if item.step_id == step_id), None)
        if step is None:
            raise ValueError(f"Unknown workflow step: {step_id}")
        if step.execution_mode != "approval" or step.approval_gate not in _GENERIC_GATES:
            raise PermissionError("Generic approval cannot substitute for specialized approval")
        step_state = next(item for item in state.steps if item.step_id == step_id)
        if step_state.status != "waiting_for_approval":
            raise RuntimeError("Workflow step is not waiting for approval")
        if step_state.input_fingerprint != artifact_fingerprint:
            raise ValueError("Approval fingerprint does not match current workflow evidence")
        approval = WorkflowApproval(
            approval_id=f"approval-{uuid4().hex}",
            workflow_id=workflow_id,
            job_id=job_id,
            step_id=step_id,
            gate=step.approval_gate,  # type: ignore[arg-type]
            plan_sha256=sha256_file(workflow_root / "plan.json"),
            artifact_fingerprint=artifact_fingerprint,
            approval_note=approval_note,
            approved_at=_utc_now(),
        )
        _write_immutable(
            _approval_path(workflow_root, step_id),
            approval.model_dump(mode="json"),
        )
        updated = _reconcile_locked(root, workflow_root, plan, request, previous=state)
        _write_state(root, workflow_root, updated)
        return updated


def _build_scene(job_id: str) -> None:
    """Build canonical scene through the same deterministic Blender entry point as CLI/MCP."""

    root = job_dir(job_id)
    spec = root / "analysis" / "scene_spec.json"
    load_scene_spec(spec)
    validate_job_interior_scope(job_id, write_report=True)
    run_blender(
        "build_scene.py",
        ["--spec", str(spec), "--output", str(root / "blender" / "scene.blend")],
    )


def _render_preview(job_id: str) -> None:
    """Render the canonical comparison camera through the shared Blender runner."""

    root = job_dir(job_id)
    run_blender(
        "render_preview.py",
        ["--output", str(root / "renders" / "preview.png")],
        blend_file=root / "blender" / "scene.blend",
    )


def _inspect_scene(job_id: str) -> None:
    """Write the standard semantic scene inventory from the current Blender scene."""

    root = job_dir(job_id)
    run_blender(
        "inspect_scene.py",
        ["--output", str(root / "reports" / "scene_inventory.json")],
        blend_file=root / "blender" / "scene.blend",
    )


def _validate_scene(job_id: str) -> None:
    """Run structural validation and fail the workflow when its report is not OK."""

    root = job_dir(job_id)
    spec = root / "analysis" / "scene_spec.json"
    load_scene_spec(spec)
    validate_job_interior_scope(job_id, write_report=True)
    output = root / "reports" / "validation.json"
    run_blender(
        "validate_scene.py",
        ["--spec", str(spec), "--output", str(output)],
        blend_file=root / "blender" / "scene.blend",
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("Scene validation did not report ok=true")


def _apply_guarded_revision(job_id: str) -> None:
    """Promote a validated RevisionPlan atomically after archiving the prior SceneSpec."""

    root = job_dir(job_id)
    current = root / "analysis" / "scene_spec.json"
    plan = root / "analysis" / "revision_plan.json"
    candidate = root / "analysis" / "scene_spec.next.json"
    _validated, report = apply_revision_plan(
        scene_spec_path=current,
        plan_path=plan,
        output_path=candidate,
    )
    archive_scene_spec(job_id)
    os.replace(candidate, current)
    write_json_atomic(root / "reports" / "revision_diff.json", report)


def _execute_host_tool(
    root: Path,
    workflow_root: Path,
    request: WorkflowRequest,
    step: WorkflowStep,
) -> None:
    """Execute one whitelisted deterministic host step with explicit parameters."""

    tool = step.tool_name
    if tool in {"create_job", "verify_geometry_prerequisite"}:
        return
    if tool == "add_view":
        if request.staged_view is None:
            raise RuntimeError("add_view workflow has no staged input")
        add_job_view(
            request.job_id,
            request.staged_view.kind,
            _resolve_job_path(root, request.staged_view.path),
            replace=request.replace_existing_view,
            scale_anchors=request.scale_anchors,
        )
        return
    if tool == "analyze_reference":
        analyze_job_reference(request.job_id, provider="auto")
        return
    if tool == "build_scene":
        _build_scene(request.job_id)
        return
    if tool == "render_preview":
        _render_preview(request.job_id)
        return
    if tool == "inspect_scene":
        _inspect_scene(request.job_id)
        return
    if tool == "validate_scene":
        _validate_scene(request.job_id)
        return
    if tool == "apply_revision_plan":
        _apply_guarded_revision(request.job_id)
        return
    if tool == "material_scaffold":
        create_material_scaffold(request.job_id, overwrite=False)
        return
    if tool == "validate_material_contracts":
        result = validate_job_material_contracts(request.job_id)
        if result.get("ok") is not True:
            raise RuntimeError("Material contract validation did not report ok=true")
        return
    if tool == "inspect_materials":
        result = inspect_job_materials(request.job_id)
        if result.get("ok") is not True:
            raise RuntimeError("Blender material inspection did not report ok=true")
        return
    if tool == "render_material_swatches":
        render_job_material_swatches(request.job_id)
        return
    if tool == "run_visual_qa":
        run_job_visual_qa(
            request.job_id,
            include_generated_target=bool(step.parameters.get("include_generated_target", False)),
        )
        return
    if tool == "generate_pdf_report":
        output_path = _resolve_job_path(root, str(step.parameters["output_path"]))
        generate_job_pdf_report(
            request.job_id,
            str(step.parameters["scope"]),  # type: ignore[arg-type]
            qa_run_id=str(step.parameters.get("qa_run_id", "latest")),
            optimization_run_id=str(
                step.parameters.get("optimization_run_id", "latest")
            ),
            package_id=str(step.parameters.get("package_id", "latest")),
            output_path=output_path,
        )
        return
    if tool == "initialize_asset_profile":
        initialize_asset_profile(
            request.job_id,
            profile_id=str(step.parameters["profile_id"]),
        )
        return
    if tool == "run_asset_preflight":
        result = preflight_asset(
            request.job_id,
            profile_id=str(step.parameters["profile_id"]),
            run_id=str(step.parameters["run_id"]),
        )
        if not result.ok:
            raise RuntimeError("Portable preflight contains failed findings")
        return
    if tool == "plan_portable_asset_optimization":
        plan_asset_optimization(
            request.job_id,
            profile_id=str(step.parameters["profile_id"]),
            run_id=str(step.parameters["run_id"]),
        )
        return
    if tool == "optimize_portable_asset":
        run_id = str(step.parameters["run_id"])
        approved_hash = sha256_file(
            root / "optimization" / "runs" / run_id / "review_plan.json"
        )
        optimize_asset(
            request.job_id,
            profile_id=str(step.parameters["profile_id"]),
            run_id=run_id,
            approved_plan_sha256=approved_hash,
        )
        return
    if tool == "convert_portable_materials":
        convert_portable_materials(
            request.job_id,
            profile_id=str(step.parameters["profile_id"]),
            run_id=str(step.parameters["run_id"]),
            conversion_id=str(step.parameters["conversion_id"]),
            resolution=int(step.parameters["resolution"]),
        )
        return
    if tool == "build_portable_package":
        package_asset(
            request.job_id,
            profile_id=str(step.parameters["profile_id"]),
            run_id=str(step.parameters["run_id"]),
            package_id=str(step.parameters["package_id"]),
            material_conversion_id=str(step.parameters["conversion_id"]),
        )
        return
    if tool == "validate_portable_package":
        result = validate_asset_package(
            request.job_id,
            str(step.parameters["package_id"]),
            profile_id=str(step.parameters["profile_id"]),
        )
        if not result.ok:
            raise RuntimeError("Portable package round trip did not report ok=true")
        return
    raise ValueError(f"Unsupported V0.8 host tool: {tool}")


def _attempt_path(workflow_root: Path, step_id: str, attempt_id: str) -> Path:
    """Resolve one unique attempt receipt path without overwriting earlier attempts."""

    return workflow_root / "attempts" / step_id / f"{attempt_id}.json"


def _recover_interrupted_attempts(
    workflow_root: Path,
    plan: WorkflowPlan,
) -> list[str]:
    """Finalize abandoned running receipts before a later process resumes the workflow."""

    recovered: list[str] = []
    attempts_root = workflow_root / "attempts"
    if not attempts_root.is_dir():
        return recovered
    for path in sorted(attempts_root.glob("*/*.json")):
        attempt = _load_model(path, WorkflowAttempt)
        if attempt.status != "running":
            continue
        if attempt.workflow_id != plan.workflow_id or attempt.job_id != plan.job_id:
            raise RuntimeError(f"Attempt receipt identity mismatch: {path}")
        interrupted = attempt.model_copy(
            update={
                "status": "failed",
                "error_type": "InterruptedAttempt",
                "error_message": (
                    "A previous workflow process stopped before this attempt finalized."
                ),
                "completed_at": _utc_now(),
            }
        )
        write_json_atomic(path, interrupted.model_dump(mode="json"))
        recovered.append(attempt.attempt_id)
    return recovered


def _prepare_failed_step_retry(
    previous: WorkflowState | None,
    *,
    retry_failed: bool,
) -> WorkflowState | None:
    """Reset only the current failed host step when retry is explicitly requested."""

    if not retry_failed:
        return previous
    if previous is None or previous.status != "failed" or previous.current_step_id is None:
        raise RuntimeError("No current failed workflow step is available for retry")
    found = False
    steps: list[WorkflowStepState] = []
    for item in previous.steps:
        if item.step_id == previous.current_step_id and item.status == "failed":
            found = True
            steps.append(item.model_copy(update={"status": "ready", "error": None}))
        else:
            steps.append(item)
    if not found:
        raise RuntimeError("Current workflow step is not a failed retryable step")
    return previous.model_copy(
        update={
            "status": "running",
            "steps": steps,
            "next_action": (
                f"Explicit retry requested for failed step {previous.current_step_id}."
            ),
            "updated_at": _utc_now(),
        }
    )


def _execute_ready_host_step(
    root: Path,
    workflow_root: Path,
    request: WorkflowRequest,
    plan: WorkflowPlan,
    state: WorkflowState,
    step: WorkflowStep,
) -> WorkflowAttempt:
    """Execute one ready host step and finalize its unique attempt receipt."""

    current = next(item for item in state.steps if item.step_id == step.step_id)
    if current.status != "ready" or current.input_fingerprint is None:
        raise RuntimeError("Host step is not ready for execution")
    attempt_id = f"attempt-{current.attempt_count + 1:04d}-{uuid4().hex[:8]}"
    attempt_path = _attempt_path(workflow_root, step.step_id, attempt_id)
    started = _utc_now()
    running = WorkflowAttempt(
        attempt_id=attempt_id,
        workflow_id=plan.workflow_id,
        job_id=plan.job_id,
        step_id=step.step_id,
        plan_sha256=state.plan_sha256,
        input_fingerprint=current.input_fingerprint,
        status="running",
        started_at=started,
    )
    _write_immutable(attempt_path, running.model_dump(mode="json"))
    try:
        _execute_host_tool(root, workflow_root, request, step)
        outputs = [
            _inspect_artifact(root, output, None)
            for output in step.outputs
        ]
        if any(item.integrity != "valid" for item in outputs):
            raise RuntimeError("Host step completed without all required valid outputs")
        completed = WorkflowAttempt(
            attempt_id=attempt_id,
            workflow_id=plan.workflow_id,
            job_id=plan.job_id,
            step_id=step.step_id,
            plan_sha256=state.plan_sha256,
            input_fingerprint=current.input_fingerprint,
            status="succeeded",
            output_fingerprint=_artifact_fingerprint(outputs),
            outputs=outputs,
            started_at=started,
            completed_at=_utc_now(),
        )
    except Exception as exc:
        failed = WorkflowAttempt(
            attempt_id=attempt_id,
            workflow_id=plan.workflow_id,
            job_id=plan.job_id,
            step_id=step.step_id,
            plan_sha256=state.plan_sha256,
            input_fingerprint=current.input_fingerprint,
            status="failed",
            error_type=type(exc).__name__,
            error_message=str(exc)[:4000],
            started_at=started,
            completed_at=_utc_now(),
        )
        write_json_atomic(attempt_path, failed.model_dump(mode="json"))
        raise
    write_json_atomic(attempt_path, completed.model_dump(mode="json"))
    return completed


def resume_workflow(
    job_id: str,
    workflow_id: str,
    *,
    max_host_steps: int | None = None,
    retry_failed: bool = False,
) -> WorkflowState:
    """Resume ready host steps and retry one failed step only with explicit consent."""

    lock_ttl = _require_orchestration()
    root, workflow_root, request, plan, previous = _load_workflow(job_id, workflow_id)
    with workflow_write_lock(root, job_id, workflow_id, ttl_seconds=lock_ttl):
        if previous is not None and previous.status == "cancelled":
            raise RuntimeError("Cancelled workflow cannot be resumed")
        _recover_interrupted_attempts(workflow_root, plan)
        previous = _prepare_failed_step_retry(previous, retry_failed=retry_failed)
        limit = max_host_steps or request.budgets.max_host_steps_per_resume
        if limit < 1 or limit > 64:
            raise ValueError("max_host_steps must be within [1, 64]")
        state = _reconcile_locked(root, workflow_root, plan, request, previous=previous)
        executed = 0
        while executed < limit and state.current_step_id is not None:
            step = next(item for item in plan.steps if item.step_id == state.current_step_id)
            step_state = next(
                item for item in state.steps if item.step_id == state.current_step_id
            )
            if step.execution_mode != "host" or step_state.status != "ready":
                break
            try:
                attempt = _execute_ready_host_step(
                    root,
                    workflow_root,
                    request,
                    plan,
                    state,
                    step,
                )
            except Exception as exc:
                failed_steps = []
                for item in state.steps:
                    if item.step_id == step.step_id:
                        failed_steps.append(
                            item.model_copy(
                                update={
                                    "status": "failed",
                                    "attempt_count": item.attempt_count + 1,
                                    "error": f"{type(exc).__name__}: {exc}",
                                }
                            )
                        )
                    else:
                        failed_steps.append(item)
                state = state.model_copy(
                    update={
                        "status": "failed",
                        "steps": failed_steps,
                        "next_action": (
                            f"Resolve {type(exc).__name__} in step {step.step_id}, then resume."
                        ),
                        "updated_at": _utc_now(),
                    }
                )
                _write_state(root, workflow_root, state)
                return state
            executed += 1
            prior_states = []
            for item in state.steps:
                if item.step_id == step.step_id:
                    prior_states.append(
                        item.model_copy(
                            update={
                                "status": "complete",
                                "attempt_count": item.attempt_count + 1,
                                "artifacts": attempt.outputs,
                                "completion_fingerprint": stable_json_digest(
                                    {
                                        "input": attempt.input_fingerprint,
                                        "output": attempt.output_fingerprint,
                                        "attempt_id": attempt.attempt_id,
                                    }
                                ),
                                "completed_at": attempt.completed_at,
                                "error": None,
                            }
                        )
                    )
                else:
                    prior_states.append(item)
            state = state.model_copy(update={"steps": prior_states})
            state = _reconcile_locked(root, workflow_root, plan, request, previous=state)
        _write_state(root, workflow_root, state)
        return state


def cancel_workflow(
    job_id: str,
    workflow_id: str,
    *,
    reason: str,
) -> WorkflowState:
    """Cancel future orchestration without deleting canonical or derived artifacts."""

    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("cancellation reason must not be empty")
    lock_ttl = _require_orchestration()
    root, workflow_root, request, plan, previous = _load_workflow(job_id, workflow_id)
    with workflow_write_lock(root, job_id, workflow_id, ttl_seconds=lock_ttl):
        current = _reconcile_locked(root, workflow_root, plan, request, previous=previous)
        if current.status == "completed":
            raise RuntimeError("Completed workflow cannot be cancelled")
        steps = [
            item
            if item.status == "complete"
            else item.model_copy(update={"status": "cancelled"})
            for item in current.steps
        ]
        cancelled = current.model_copy(
            update={
                "status": "cancelled",
                "current_step_id": None,
                "steps": steps,
                "next_action": None,
                "waiting_gate": None,
                "cancelled_reason": normalized_reason,
                "updated_at": _utc_now(),
            }
        )
        _write_state(root, workflow_root, cancelled)
        return cancelled


__all__ = [
    "approve_workflow_gate",
    "cancel_workflow",
    "complete_workflow_step",
    "destination_adapters",
    "get_workflow_status",
    "plan_workflow",
    "reconcile_workflow",
    "resume_workflow",
]
