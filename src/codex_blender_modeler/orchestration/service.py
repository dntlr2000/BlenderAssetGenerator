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
from ..architecture import (
    list_interior_objects,
    load_interior_scope,
    validate_job_interior_scope,
)
from ..auto_revision.candidate_review_models import CandidateReviewPromotionReceipt
from ..auto_revision.candidate_review_reporting import (
    generate_candidate_review_pdf,
    validate_candidate_review_pdf_manifest,
)
from ..auto_revision.candidate_review_service import (
    CandidateReviewConflict,
    evaluate_candidate_review,
    promote_candidate_review,
    validate_candidate_review_approval,
    validate_candidate_review_decision,
)
from ..background_quality import (
    BackgroundFitConflict,
    BackgroundQualityConflict,
    BackgroundQualityReport,
    evaluate_background_quality,
    run_background_pre_qa_fit,
)
from ..blender_artifact_runner import inspect_job_materials, render_job_material_swatches
from ..blender_artifacts import (
    native_io_path,
    sha256_directory,
    stable_json_digest,
    write_json_atomic,
)
from ..blender_runner import run_blender
from ..config import load_feature_config
from ..interior_qa import plan_job_interior_qa, run_job_interior_qa
from ..materials import (
    create_material_scaffold,
    create_workflow_material_candidates,
    promote_workflow_material_candidate,
    validate_job_material_contracts,
    validate_job_material_fidelity,
)
from ..optimization import (
    initialize_asset_profile,
    optimize_asset,
    plan_asset_optimization,
    preflight_asset,
)
from ..optimization.io import validate_filesystem_id
from ..optimization.preflight import load_asset_profile, profile_path
from ..optimization.provenance import collect_source_provenance
from ..packaging import package_asset, validate_asset_package
from ..packaging.material_conversion import convert_portable_materials
from ..qa import run_job_visual_qa
from ..qa.diagnostic_service import (
    run_job_visual_diagnostics,
    validate_qa_diagnostic_bundle,
)
from ..qa.multiview_sanity import (
    AssemblySanityPlan,
    AssemblySanityRenderManifest,
    AssemblySanityReport,
    plan_job_assembly_multiview_sanity,
    recover_incomplete_job_assembly_multiview_sanity,
    recover_unpublished_job_assembly_multiview_plan,
    run_job_assembly_multiview_sanity,
    validate_assembly_sanity_terminal,
    validate_geometry_multiview_visual_review,
)
from ..reference_scope import (
    normalize_reference_content_scope,
    reference_content_scope_from_metadata,
    validate_modeling_plan_content_scope,
    validate_scene_content_scope,
)
from ..reporting import generate_job_pdf_report
from ..revision import apply_revision_plan
from ..validation import load_scene_spec
from ..workspace import (
    add_job_view,
    create_job,
    ensure_job_dirs,
    find_reference,
    job_dir,
    load_job,
    replace_scene_spec_if_current,
    sha256_file,
    validate_job_id,
    validate_new_job_id,
)
from .locks import workflow_write_lock
from .models import (
    ArtifactFreshness,
    ArtifactRequirement,
    BackgroundPreviewBinding,
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


class RequiresStandardWorkflow(RuntimeError):
    """Signal that a bounded fast-lane workflow must stop without being retried."""


class OrchestrationArtifactConflict(RuntimeError):
    """Signal unexpected mutation of workflow-owned evidence or its current source."""


def _ensure_workflow_asset_profile(
    root: Path,
    job_id: str,
    profile_id: str,
) -> None:
    """Reuse a valid job-owned profile or initialize it when none exists."""

    existing_path = profile_path(root, profile_id)
    if not existing_path.is_file():
        initialize_asset_profile(job_id, profile_id=profile_id)
        return
    existing = load_asset_profile(root, profile_id)
    if existing.job_id != job_id or existing.profile_id != profile_id:
        raise OrchestrationArtifactConflict(
            "orchestration_artifact_conflict: existing asset profile identity "
            "does not match the workflow job and profile"
        )


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
        "interior_visual_qa": "qa_only",
        "material_authoring": "material_only",
        "visual_qa": "qa_only",
        "portable_package": "portable_only",
    }[intent]


def _normalize_execution_budgets(
    execution_policy: str,
    budgets: WorkflowBudgets | None,
) -> WorkflowBudgets:
    """Apply conservative non-expanding budgets to the background fast lane."""

    selected = budgets or WorkflowBudgets()
    if execution_policy != "background_exterior":
        return selected
    if selected.external_provider_budget != 0:
        raise ValueError("background_exterior does not permit external provider calls")
    return selected.model_copy(
        update={
            "max_qa_iterations": 1,
            "max_texture_resolution": min(
                selected.max_texture_resolution,
                512,
            ),
            "external_provider_budget": 0,
        }
    )


def _current_background_preview_binding(
    root: Path,
    job_id: str,
) -> BackgroundPreviewBinding | None:
    """Return an exact binding for one current completed fast-preview workflow."""

    workflows_root = root / "workflows"
    if not workflows_root.is_dir():
        return False
    for workflow_root in sorted(workflows_root.glob("wf-*"), reverse=True):
        request_path = workflow_root / "request.json"
        plan_path = workflow_root / "plan.json"
        state_path = workflow_root / "state.json"
        if not all(path.is_file() for path in (request_path, plan_path, state_path)):
            continue
        try:
            request = _load_model(request_path, WorkflowRequest)
            plan = _load_model(plan_path, WorkflowPlan)
            previous = _load_model(state_path, WorkflowState)
            if (
                request.execution_policy != "background_exterior"
                or request.delivery_scope != "preview_only"
                or plan.execution_policy != "background_exterior"
                or plan.delivery_scope != "preview_only"
            ):
                continue
            reconstructed = _reconcile_locked(
                root,
                workflow_root,
                plan,
                request,
                previous=previous,
            )
        except (OSError, RuntimeError, ValueError):
            continue
        if (
            reconstructed.status == "completed"
            and reconstructed.milestone == "delivered_for_review"
        ):
            terminal = next(
                (item for item in reconstructed.steps if item.step_id == plan.terminal_step_id),
                None,
            )
            qa_step = next(
                (item for item in plan.steps if item.step_id == "qa.run"),
                None,
            )
            qa_run_id = qa_step.parameters.get("run_id") if qa_step is not None else None
            if not isinstance(qa_run_id, str) or not qa_run_id:
                latest_path = root / "qa" / "latest.json"
                if not latest_path.is_file():
                    continue
                try:
                    latest = json.loads(latest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                qa_run_id = latest.get("run_id")
            if (
                terminal is None
                or terminal.completion_fingerprint is None
                or not isinstance(qa_run_id, str)
                or not qa_run_id
            ):
                continue
            try:
                source = collect_source_provenance(root, job_id)
            except (OSError, RuntimeError, ValueError):
                continue
            eligibility_step = next(
                (item for item in plan.steps if item.step_id == "background.eligibility"),
                None,
            )
            quality_status = None
            standard_workflow_recommended = None
            quality_report_path = None
            quality_report_sha256 = None
            if eligibility_step is not None and eligibility_step.outputs:
                eligibility_path = _resolve_job_path(
                    root,
                    eligibility_step.outputs[0].path,
                )
                try:
                    eligibility = json.loads(eligibility_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                recorded_source = eligibility.get("source_fingerprint")
                recorded_build = eligibility.get("build_fingerprint")
                if recorded_source is not None and (
                    recorded_source != source.source_fingerprint
                    or recorded_build != source.build_fingerprint
                ):
                    continue
                if eligibility_step.parameters.get("quality_policy") == "review_delivery_v2":
                    try:
                        quality = BackgroundQualityReport.model_validate(eligibility)
                    except ValueError:
                        continue
                    quality_status = quality.quality_status
                    standard_workflow_recommended = quality.standard_workflow_recommended
                    quality_report_path = _job_relative(root, eligibility_path)
                    quality_report_sha256 = sha256_file(eligibility_path)
            return BackgroundPreviewBinding(
                workflow_id=plan.workflow_id,
                plan_sha256=reconstructed.plan_sha256,
                terminal_step_id=plan.terminal_step_id,
                terminal_completion_fingerprint=terminal.completion_fingerprint,
                qa_run_id=qa_run_id,
                source_fingerprint=source.source_fingerprint,
                build_fingerprint=source.build_fingerprint,
                quality_status=quality_status,
                standard_workflow_recommended=standard_workflow_recommended,
                quality_report_path=quality_report_path,
                quality_report_sha256=quality_report_sha256,
                bound_at=_utc_now(),
            )
    return None


def _validate_background_execution(
    *,
    routing: IntentRouting,
    request_text: str,
    new_job: bool,
    mode: str,
    scope: str,
    view_kind: str | None,
    replace_view: bool,
    scale_anchors: list[str],
    destination_kind: str,
    include_destination_handoff: bool,
) -> BackgroundPreviewBinding | None:
    """Reject fast-lane inputs that require measured, interior, or runtime work."""

    scope_risks = _background_request_scope_risks(request_text)
    if scope_risks:
        raise ValueError(
            "requires_standard_workflow: background_exterior request contains "
            f"excluded scope: {', '.join(scope_risks)}"
        )
    if new_job and routing.intent != "new_asset":
        raise ValueError("a new background_exterior workflow requires intent=new_asset")
    if not new_job and (
        routing.intent != "portable_package" or routing.delivery_scope != "portable_package"
    ):
        raise ValueError(
            "an existing background_exterior job can only start portable_package delivery"
        )
    if mode != "concept":
        raise ValueError(
            "background_exterior supports concept mode only; use standard for measured input"
        )
    if scope not in {"auto", "full"}:
        raise ValueError(
            "background_exterior controls its own bounded full scope; use --scope auto"
        )
    if view_kind is not None or replace_view or scale_anchors:
        raise ValueError(
            "background_exterior cannot contain measured views, replacement, or scale anchors"
        )
    resolved_destination = routing.destination.requested.kind
    if destination_kind not in {"unspecified", "engine_neutral"} or resolved_destination not in {
        "unspecified",
        "engine_neutral",
    }:
        raise ValueError(
            "requires_standard_workflow: background_exterior stops at an "
            "engine-neutral preview or package"
        )
    if include_destination_handoff:
        raise ValueError("background_exterior cannot include a destination handoff")
    if not new_job:
        metadata = load_job(routing.job_id)
        root = job_dir(routing.job_id)
        if metadata.get("mode") != "concept":
            raise ValueError("existing background_exterior package delivery requires a concept job")
        if metadata.get("scale_anchors"):
            raise ValueError("existing measured scale anchors require the standard workflow")
        sources = metadata.get("sources", [])
        if (
            not isinstance(sources, list)
            or len(sources) != 1
            or any(not isinstance(item, dict) for item in sources)
            or sources[0].get("kind") != "reference"
        ):
            raise ValueError(
                "background package continuation requires exactly one primary reference"
            )
        scope_contract = load_interior_scope(root)
        if scope_contract is not None and scope_contract.policy != "disabled":
            raise ValueError("an enabled InteriorScope requires the standard workflow")
        scene_spec = load_scene_spec(root / "analysis" / "scene_spec.json")
        if list_interior_objects(scene_spec):
            raise ValueError("interior semantic geometry requires the standard workflow")
        if (root / "constraints" / "constraints.json").is_file():
            raise ValueError("measured constraints require the standard workflow")
        binding = _current_background_preview_binding(root, routing.job_id)
        if binding is None:
            raise ValueError(
                "background package continuation requires one current completed "
                "background_exterior preview workflow"
            )
        return binding
    return None


def _background_request_scope_risks(request_text: str) -> list[str]:
    """Detect explicit fast-lane exclusions without treating negative limits as requests."""

    normalized = request_text.casefold()
    negative_patterns = (
        r"\bwithout\b[^.?!]*",
        r"\bdo\s+not\b[^.?!]*",
        r"\b(?:no|without)\s+(?:an?\s+)?(?:interior|rig|rigging|skinning|animation|gameplay)\b",
        r"\bdo\s+not\s+(?:create|include|add|use)\s+(?:an?\s+)?"
        r"(?:interior|rig|rigging|skinning|animation|gameplay)\b",
        r"(?:실내|인테리어).{0,12}(?:필요\s*없|만들지|생성하지|제외|비활성)",
        r"(?:리그|리깅|스키닝|애니메이션|게임플레이).{0,12}(?:없이|제외|하지\s*마)",
    )
    for pattern in negative_patterns:
        normalized = re.sub(pattern, " ", normalized)
    categories = {
        "interior": (
            r"\b(?:interior|room|corridor|furnishing)\b",
            r"(?:실내|인테리어|방\s*(?:을|도)?|복도)",
        ),
        "rig_or_skinning": (
            r"\b(?:rig|rigged|rigging|skin|skinned|skinning)\b",
            r"(?:리그|리깅|스키닝|본\s*세팅)",
        ),
        "animation": (
            r"\b(?:animation|animate|animated)\b",
            r"(?:애니메이션|움직이게)",
        ),
        "gameplay": (
            r"\b(?:gameplay|interactive|interaction)\b",
            r"(?:게임플레이|상호작용|인터랙션)",
        ),
        "engine_specific": (
            r"\b(?:unity|unreal(?:\s+engine)?|engine-specific)\b",
            r"(?:유니티|언리얼|엔진\s*전용)",
        ),
    }
    return [
        category
        for category, patterns in categories.items()
        if any(re.search(pattern, normalized) for pattern in patterns)
    ]


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
    execution_policy: str,
    delivery_scope: str | None,
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
        execution_policy=execution_policy,
        delivery_scope=delivery_scope,
    )


def _revision_modeling_plan_contract(root: Path) -> tuple[str, str]:
    """Return the exact authored ModelingPlan hash and assembly policy.

    Missing, malformed, or scaffold plans fail before a revision workflow is
    persisted.  Old authored plans that omit the policy parse to the explicit
    backward-compatible ``legacy_unbound`` model default.
    """

    from ..analysis.models import ModelingPlan

    path = root / "analysis" / "modeling_plan.json"
    if not path.is_file():
        raise FileNotFoundError("revise_asset requires analysis/modeling_plan.json before planning")
    plan = ModelingPlan.model_validate_json(path.read_text(encoding="utf-8"))
    if plan.stage != "authored":
        raise ValueError("revise_asset requires an authored ModelingPlan")
    return sha256_file(path), plan.assembly_consistency_policy


def plan_workflow(
    request_text: str,
    *,
    job_id: str | None = None,
    reference_path: str | Path | None = None,
    intent: str = "auto",
    scope: str = "auto",
    reference_content_scope: str | None = None,
    target_subject: str | None = None,
    execution_policy: str = "standard",
    revision_strategy: str = "candidate_review",
    delivery_scope: str | None = None,
    mode: str = "concept",
    view_kind: str | None = None,
    replace_view: bool = False,
    scale_anchors: list[str] | None = None,
    profile_id: str = "portable_gltf",
    destination_kind: str = "unspecified",
    destination_name: str | None = None,
    destination_version: str | None = None,
    include_destination_handoff: bool = False,
    budgets: WorkflowBudgets | None = None,
) -> WorkflowState:
    """Create one immutable workflow with explicit content and revision boundaries."""

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
        "interior_visual_qa",
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
    if execution_policy not in {"standard", "background_exterior"}:
        raise ValueError("execution_policy must be standard or background_exterior")
    if revision_strategy not in {"candidate_review", "manual_guarded"}:
        raise ValueError("revision_strategy must be candidate_review or manual_guarded")
    if delivery_scope not in {None, "preview_only", "portable_package"}:
        raise ValueError("delivery_scope must be preview_only or portable_package")
    if profile_id not in {"portable_gltf", "fbx_interchange", "obj_legacy"}:
        raise ValueError("unsupported portable profile")
    if execution_policy == "standard" and delivery_scope == "portable_package":
        raise ValueError(
            "explicit portable_package remains implicit for standard full workflows; "
            "only preview_only may be selected explicitly"
        )
    resolved_profile = _profile_from_request(normalized_request, profile_id)
    if include_destination_handoff and resolved_profile == "obj_legacy":
        raise ValueError("destination handoff supports GLB and FBX packages only")
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
        resolved_content_scope, resolved_target_subject = normalize_reference_content_scope(
            reference_content_scope,
            target_subject,
        )
    else:
        validate_job_id(selected_job_id)
        stored_content_scope, stored_target_subject = reference_content_scope_from_metadata(
            load_job(selected_job_id)
        )
        resolved_content_scope, resolved_target_subject = normalize_reference_content_scope(
            reference_content_scope or stored_content_scope,
            target_subject if target_subject is not None else stored_target_subject,
        )
        if (
            resolved_content_scope != stored_content_scope
            or resolved_target_subject != stored_target_subject
        ):
            raise ValueError(
                "An existing job's reference content scope is immutable. "
                "Create a new job to change primary_object_only/full_reference "
                "or target_subject."
            )
    workflow_id = _new_workflow_id()
    destination = DestinationRequest(
        kind=destination_kind,  # type: ignore[arg-type]
        name=destination_name,
        version=destination_version,
    )
    initial_delivery = (
        delivery_scope
        if delivery_scope is not None
        else ("preview_only" if execution_policy == "background_exterior" else None)
    )
    routing = _initial_intent(
        intent,
        new_job=new_job,
        view_kind=normalized_view,
        request_text=normalized_request,
        job_id=selected_job_id,
        workflow_id=workflow_id,
        destination=destination,
        execution_policy=execution_policy,
        delivery_scope=initial_delivery,
    )
    normalized_anchors = scale_anchors or []
    background_preview_binding = None
    if execution_policy == "background_exterior":
        background_preview_binding = _validate_background_execution(
            routing=routing,
            request_text=normalized_request,
            new_job=new_job,
            mode=mode,
            scope=scope,
            view_kind=normalized_view,
            replace_view=replace_view,
            scale_anchors=normalized_anchors,
            destination_kind=destination_kind,
            include_destination_handoff=include_destination_handoff,
        )
        selected_scope = "full"
        resolved_delivery = initial_delivery
    else:
        selected_scope = _default_scope(routing.intent, scope)
        resolved_delivery = (
            delivery_scope
            if delivery_scope is not None
            else (
                "portable_package"
                if routing.intent == "portable_package" or selected_scope == "full"
                else "preview_only"
            )
        )
        routing = routing.model_copy(update={"delivery_scope": resolved_delivery})
    selected_budgets = _normalize_execution_budgets(
        execution_policy,
        budgets,
    )
    if new_job:
        create_job(
            selected_job_id,
            reference or Path(),
            mode,
            normalized_anchors,
            reference_content_scope=resolved_content_scope,
            target_subject=resolved_target_subject,
        )
    root = ensure_job_dirs(selected_job_id)
    workflow_root = _workflow_dir(root, workflow_id)
    with workflow_write_lock(
        root,
        selected_job_id,
        workflow_id,
        ttl_seconds=lock_ttl,
    ):
        existing_modeling_plan_sha256 = None
        existing_assembly_consistency_policy = None
        if routing.intent == "revise_asset":
            (
                existing_modeling_plan_sha256,
                existing_assembly_consistency_policy,
            ) = _revision_modeling_plan_contract(root)
        if execution_policy == "background_exterior" and not new_job:
            background_preview_binding = _validate_background_execution(
                routing=routing,
                request_text=normalized_request,
                new_job=False,
                mode=mode,
                scope=scope,
                view_kind=normalized_view,
                replace_view=replace_view,
                scale_anchors=normalized_anchors,
                destination_kind=destination_kind,
                include_destination_handoff=include_destination_handoff,
            )
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
            reference_content_scope=resolved_content_scope,
            target_subject=resolved_target_subject,
            execution_policy=execution_policy,  # type: ignore[arg-type]
            revision_strategy=(
                revision_strategy  # type: ignore[arg-type]
                if routing.intent == "revise_asset" and execution_policy == "standard"
                else None
            ),
            delivery_scope=resolved_delivery,  # type: ignore[arg-type]
            fast_quality_policy=(
                "review_delivery_v2" if execution_policy == "background_exterior" else None
            ),
            background_preview_binding=background_preview_binding,
            mode=mode,  # type: ignore[arg-type]
            primary_reference=primary,
            staged_view=staged_view,
            replace_existing_view=replace_view,
            scale_anchors=normalized_anchors,
            profile_id=resolved_profile,  # type: ignore[arg-type]
            destination=routing.destination.requested,
            include_destination_handoff=include_destination_handoff,
            budgets=selected_budgets,
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
            existing_modeling_plan_sha256=existing_modeling_plan_sha256,
            existing_assembly_consistency_policy=(existing_assembly_consistency_policy),
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

    if os.path.isfile(native_io_path(path)):
        return sha256_file(path)
    if os.path.isdir(native_io_path(path)):
        return sha256_directory(path)
    raise FileNotFoundError(path)


def _copy_artifact_immutable(source: Path, destination: Path) -> None:
    """Snapshot one file or directory without permitting evidence replacement."""

    if destination.exists():
        raise OrchestrationArtifactConflict(
            f"Immutable workflow snapshot already exists: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    if source.is_file():
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        return
    if source.is_dir():
        shutil.copytree(source, temporary)
        os.replace(temporary, destination)
        return
    raise FileNotFoundError(source)


def _materialize_step_snapshots(root: Path, step: WorkflowStep) -> None:
    """Copy mutable host outputs into their exact workflow-owned evidence paths."""

    for requirement in step.outputs:
        if requirement.lifecycle != "workflow_snapshot":
            continue
        if requirement.source_path is None:
            raise RuntimeError("workflow snapshot has no mutable source path")
        source = _resolve_job_path(root, requirement.source_path)
        destination = _resolve_job_path(root, requirement.path)
        _copy_artifact_immutable(source, destination)


def _transitive_dependencies(
    plan: WorkflowPlan,
    step: WorkflowStep,
) -> set[str]:
    """Return all direct and indirect prerequisite step IDs for one plan step."""

    step_map = {item.step_id: item for item in plan.steps}
    pending = list(step.depends_on)
    dependencies: set[str] = set()
    while pending:
        dependency = pending.pop()
        if dependency in dependencies:
            continue
        dependencies.add(dependency)
        pending.extend(step_map[dependency].depends_on)
    return dependencies


def _verify_dependency_sources(
    root: Path,
    workflow_root: Path,
    plan: WorkflowPlan,
    step: WorkflowStep,
) -> None:
    """Reject sources that differ from their latest successfully published snapshot."""

    dependencies = _transitive_dependencies(plan, step)
    latest: dict[str, ArtifactRequirement] = {}
    for candidate_step in plan.steps:
        if candidate_step.step_id == step.step_id:
            break
        for requirement in candidate_step.outputs:
            if requirement.lifecycle != "workflow_snapshot":
                continue
            if requirement.source_path is None:
                continue
            is_dependency_source = candidate_step.step_id in dependencies
            supersedes_known_source = requirement.source_path in latest
            snapshot = _resolve_job_path(root, requirement.path)
            attempt_root = workflow_root / "attempts" / candidate_step.step_id
            was_published = snapshot.exists() and attempt_root.is_dir()
            # A successful earlier sibling may intentionally replace a shared mutable
            # source before the current step, such as detail.render before detail.inspect.
            if is_dependency_source or (supersedes_known_source and was_published):
                latest[requirement.source_path] = requirement
    for source_relative, requirement in latest.items():
        source = _resolve_job_path(root, source_relative)
        snapshot = _resolve_job_path(root, requirement.path)
        if not source.exists() or not snapshot.exists():
            raise OrchestrationArtifactConflict(
                "orchestration_artifact_conflict: planned source or snapshot is missing "
                f"for {source_relative}"
            )
        if _artifact_digest(source) != _artifact_digest(snapshot):
            raise OrchestrationArtifactConflict(
                "orchestration_artifact_conflict: current source differs from the "
                f"latest planned snapshot for {source_relative}"
            )


def _validate_known_json_contract(
    root: Path,
    requirement: ArtifactRequirement,
    payload: dict[str, Any],
) -> None:
    """Validate agent-authored canonical JSON with its existing strict host contract."""

    relative_path = requirement.source_path or requirement.path
    if relative_path == "analysis/modeling_plan.json":
        from ..analysis.models import ModelingPlan

        ModelingPlan.model_validate(payload)
    elif relative_path == "analysis/scene_spec.json":
        from ..models import SceneSpec

        SceneSpec.model_validate(payload)
    elif relative_path == "analysis/revision_plan.json":
        from ..revision import RevisionPlan

        RevisionPlan.model_validate(payload)
    elif requirement.artifact_id == "revision.candidate_plan":
        from ..revision import RevisionPlan

        RevisionPlan.model_validate(payload)
    elif requirement.artifact_id == "revision.candidate_decision":
        validate_candidate_review_decision(
            root,
            _resolve_job_path(root, requirement.path),
            require_current_sources=False,
        )
    elif requirement.artifact_id == "revision.candidate_approval":
        from ..auto_revision.candidate_review_models import CandidateReviewApproval

        CandidateReviewApproval.model_validate(payload)
    elif requirement.artifact_id == "revision.candidate_report_manifest":
        from ..auto_revision.candidate_review_models import CandidateReviewReportManifest

        CandidateReviewReportManifest.model_validate(payload)
    elif requirement.artifact_id == "revision.promotion_receipt":
        CandidateReviewPromotionReceipt.model_validate(payload)
    elif relative_path == "architecture/interior_scope.json":
        from ..architecture.models import InteriorScope

        InteriorScope.model_validate(payload)
    elif relative_path == "analysis/material_plan.json":
        from ..materials.models import MaterialPlan

        MaterialPlan.model_validate(payload)
    elif requirement.artifact_id == "material.plan.promotion_receipt":
        from ..materials.models import MaterialPromotionReceipt

        MaterialPromotionReceipt.model_validate(payload)
    elif requirement.artifact_id == "qa.diagnostics.bundle":
        from ..qa.diagnostic_service import validate_qa_diagnostic_bundle

        validate_qa_diagnostic_bundle(
            root,
            _resolve_job_path(root, requirement.path),
        )
    elif requirement.artifact_id.endswith(".geometry_multiview.plan"):
        AssemblySanityPlan.model_validate(payload)
    elif requirement.artifact_id.endswith(".geometry_multiview.manifest"):
        AssemblySanityRenderManifest.model_validate(payload)
    elif requirement.artifact_id.endswith(".geometry_multiview.report"):
        AssemblySanityReport.model_validate(payload)
    elif requirement.artifact_id.endswith(".geometry_multiview.visual_review"):
        validate_geometry_multiview_visual_review(
            root,
            _resolve_job_path(root, requirement.path),
            expected_job_id=root.name,
            expected_run_id=str(payload.get("run_id", "")),
        )
    elif requirement.artifact_id == "background.delivery_eligibility" and relative_path.endswith(
        "_quality.json"
    ):
        BackgroundQualityReport.model_validate(payload)
    elif relative_path.endswith("/codex_handoff/handoff_manifest.json"):
        from ..handoff.models import DestinationHandoffManifest

        DestinationHandoffManifest.model_validate(payload)
    elif relative_path.endswith("/destination_handoff_validation.json"):
        from ..handoff.models import DestinationHandoffValidation

        DestinationHandoffValidation.model_validate(payload)
    elif relative_path.endswith("/codex_handoff/handoff_report.manifest.json"):
        from ..handoff.models import HandoffReportManifest

        HandoffReportManifest.model_validate(payload)


def _validate_authored_material_plan(
    root: Path,
    path: Path,
    request: WorkflowRequest,
    *,
    require_spatial_surface_details: bool = False,
) -> None:
    """Require authored material semantics and bounded fast-lane texture providers."""

    from ..materials.models import MaterialPlan

    plan = MaterialPlan.model_validate_json(path.read_text(encoding="utf-8"))
    if plan.stage != "authored":
        raise RuntimeError("agent completion requires material_plan stage=authored")
    if require_spatial_surface_details and plan.surface_detail_binding_policy != "spatial_v1":
        raise RuntimeError(
            "new material authoring requires surface_detail_binding_policy=spatial_v1"
        )
    modeling_plan_path = root / "analysis" / "modeling_plan.json"
    if modeling_plan_path.is_file():
        from ..analysis.models import ModelingPlan
        from ..analysis.surface_details import validate_surface_detail_contract
        from ..models import SceneSpec

        modeling_plan = ModelingPlan.model_validate_json(
            modeling_plan_path.read_text(encoding="utf-8")
        )
        scene_spec = SceneSpec.model_validate_json(
            (root / "analysis" / "scene_spec.json").read_text(encoding="utf-8")
        )
        detail_report = validate_surface_detail_contract(
            modeling_plan,
            scene_spec,
            root,
            material_plan=plan,
            require_materials=True,
        )
        if not detail_report.ok:
            failures = "; ".join(
                item.message for item in detail_report.checks if item.status == "failed"
            )
            raise RuntimeError(
                f"agent material completion fails surface-detail coverage: {failures}"
            )
    if request.execution_policy != "background_exterior":
        return
    from ..texturing.models import TextureManifest

    unsupported: list[str] = []
    for item in plan.materials:
        if item.texture_strategy in {"none", "procedural"}:
            continue
        if item.texture_strategy != "image" or not item.texture_manifest:
            unsupported.append(item.material_id)
            continue
        manifest_path = _resolve_job_path(root, item.texture_manifest)
        manifest = TextureManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        provider = manifest.provenance.provider if manifest.provenance is not None else None
        if provider != "cbm_pillow_procedural" or max(manifest.resolution) > 512:
            unsupported.append(item.material_id)
    if unsupported:
        raise RuntimeError(
            "background_exterior permits only node-procedural materials or "
            "512px local cbm_pillow_procedural maps: "
            f"{unsupported}"
        )


def _validate_agent_completion_semantics(
    root: Path,
    step: WorkflowStep,
    request: WorkflowRequest,
) -> None:
    """Require authored semantics and enforce fast-lane material restrictions."""

    _verify_revision_modeling_plan_binding(root, step)
    if step.step_id == "material.author" and "candidate_plan_path" in step.parameters:
        candidate = _resolve_job_path(
            root,
            str(step.parameters["candidate_plan_path"]),
        )
        _validate_authored_material_plan(
            root,
            candidate,
            request,
            require_spatial_surface_details=bool(
                step.parameters.get("require_spatial_surface_details", False)
            ),
        )
    for requirement in step.outputs:
        path = _resolve_job_path(root, requirement.path)
        if (
            requirement.lifecycle == "workflow_snapshot"
            and not path.exists()
            and requirement.source_path is not None
        ):
            path = _resolve_job_path(root, requirement.source_path)
        contract_path = requirement.source_path or requirement.path
        if contract_path == "analysis/modeling_plan.json":
            from ..analysis.models import ModelingPlan

            plan = ModelingPlan.model_validate_json(path.read_text(encoding="utf-8"))
            if "modeling_plan.output" in requirement.artifact_id and plan.stage != "authored":
                raise RuntimeError("agent completion requires modeling_plan stage=authored")
            if (
                bool(step.parameters.get("require_surface_detail_policy", False))
                and plan.surface_detail_policy is None
            ):
                raise RuntimeError("new modeling-plan completion requires surface_detail_policy")
            if (
                bool(
                    step.parameters.get(
                        "require_assembly_consistency_policy",
                        False,
                    )
                )
                and plan.assembly_consistency_policy != "spatial_v1"
            ):
                raise RuntimeError(
                    "new modeling-plan completion requires assembly_consistency_policy=spatial_v1"
                )
            validate_modeling_plan_content_scope(
                plan,
                scope=request.reference_content_scope,
                target_subject=request.target_subject,
            )
        elif contract_path == "analysis/scene_spec.json":
            scene_spec = load_scene_spec(path)
            modeling_plan_path = root / "analysis" / "modeling_plan.json"
            if modeling_plan_path.is_file():
                from ..analysis.assembly import validate_assembly_prebuild_contract
                from ..analysis.models import ModelingPlan
                from ..analysis.surface_details import validate_surface_detail_contract

                modeling_plan = ModelingPlan.model_validate_json(
                    modeling_plan_path.read_text(encoding="utf-8")
                )
                if modeling_plan.assembly_consistency_policy == "spatial_v1":
                    assembly_report = validate_assembly_prebuild_contract(
                        modeling_plan,
                        scene_spec,
                    )
                    if not assembly_report.ok:
                        failures = "; ".join(
                            item.message
                            for item in assembly_report.checks
                            if item.status == "failed"
                        )
                        raise RuntimeError(
                            "agent SceneSpec completion violates spatial-v1 assembly "
                            f"consistency: {failures}"
                        )
                detail_report = validate_surface_detail_contract(
                    modeling_plan,
                    scene_spec,
                    root,
                    require_materials=False,
                )
                structural_failures = [
                    item
                    for item in detail_report.checks
                    if item.status == "failed" and item.phase != "material"
                ]
                if structural_failures:
                    failures = "; ".join(item.message for item in structural_failures)
                    raise RuntimeError(
                        f"agent SceneSpec completion violates surface-detail routing: {failures}"
                    )
            validate_scene_content_scope(
                scene_spec,
                scope=request.reference_content_scope,
                target_subject=request.target_subject,
            )
            if request.execution_policy == "background_exterior" and list_interior_objects(
                scene_spec
            ):
                raise RuntimeError(
                    "background_exterior cannot complete with interior semantic geometry"
                )
        elif contract_path == "analysis/material_plan.json":
            _validate_authored_material_plan(root, path, request)
    if step.step_id == "destination.handoff":
        from ..handoff import validate_destination_handoff

        validation = validate_destination_handoff(
            root.name,
            profile_id=str(step.parameters["profile_id"]),
            package_id=str(step.parameters["package_id"]),
            handoff_id=str(step.parameters["handoff_id"]),
        )
        if not validation.ok:
            raise RuntimeError("destination handoff validation did not report ok=true")


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
                    _validate_known_json_contract(root, requirement, payload)
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


def _archived_scene_spec_matches(
    root: Path,
    requirement: ArtifactRequirement,
    expected_sha256: str | None,
) -> bool:
    """Verify that an expected canonical SceneSpec predecessor remains archived."""

    if requirement.path != "analysis/scene_spec.json" or expected_sha256 is None:
        return False
    history = root / "history"
    if not history.is_dir():
        return False
    # A later authoring stage may supersede only a predecessor whose exact bytes remain.
    return any(
        path.is_file() and sha256_file(path) == expected_sha256
        for path in history.glob("*_scene_spec.json")
    )


def _later_canonical_agent_owner_was_reached(
    workflow_root: Path,
    plan: WorkflowPlan,
    step: WorkflowStep,
    requirement: ArtifactRequirement,
    previous: WorkflowState | None,
) -> bool:
    """Return whether workflow progress reached a later agent owner of one canonical path."""

    if previous is None:
        return False
    step_indexes = {item.step_id: index for index, item in enumerate(plan.steps)}
    current_index = step_indexes[step.step_id]
    previous_index = (
        step_indexes.get(previous.current_step_id, -1)
        if previous.current_step_id is not None
        else -1
    )
    for candidate in plan.steps[current_index + 1 :]:
        owns_path = any(
            output.lifecycle == "canonical" and output.path == requirement.path
            for output in candidate.outputs
        )
        if candidate.execution_mode != "agent" or not owns_path:
            continue
        if previous_index >= step_indexes[candidate.step_id]:
            return True
        if _completion_path(workflow_root, candidate.step_id).is_file():
            return True
    return False


def _expected_superseded_agent_artifacts(
    root: Path,
    workflow_root: Path,
    plan: WorkflowPlan,
    step: WorkflowStep,
    completion: WorkflowStepCompletion,
    live_artifacts: list[ArtifactFreshness],
    previous: WorkflowState | None,
) -> list[ArtifactFreshness] | None:
    """Recover exact prior agent evidence after an authorized canonical replacement."""

    recorded = {item.artifact_id: item for item in completion.output_artifacts}
    recovered: list[ArtifactFreshness] = []
    for requirement, live in zip(step.outputs, live_artifacts, strict=True):
        prior = recorded.get(requirement.artifact_id)
        if prior is None or prior.path != requirement.path or prior.integrity != "valid":
            return None
        if live.sha256 == prior.sha256:
            recovered.append(live)
            continue
        expected_replacement = (
            requirement.lifecycle == "canonical"
            and _later_canonical_agent_owner_was_reached(
                workflow_root,
                plan,
                step,
                requirement,
                previous,
            )
            and _archived_scene_spec_matches(root, requirement, prior.sha256)
        )
        if not expected_replacement:
            return None
        recovered.append(
            prior.model_copy(
                update={
                    "currency": "superseded",
                    "reason": (
                        "Exact predecessor is preserved in history after the workflow "
                        "reached a later canonical SceneSpec authoring step."
                    ),
                }
            )
        )
    return recovered


def _step_input_fingerprint(
    plan: WorkflowPlan,
    request: WorkflowRequest,
    step: WorkflowStep,
    states: dict[str, WorkflowStepState],
) -> str:
    """Hash the plan, request, and exact dependency completion fingerprints."""

    payload: dict[str, Any] = {
        "plan_sha256": sha256_file(
            _workflow_dir(job_dir(plan.job_id), plan.workflow_id) / "plan.json"
        ),
        "request_sha256": plan.request_sha256,
        "step_id": step.step_id,
        "parameters": step.parameters,
        "dependencies": {
            dependency: states[dependency].completion_fingerprint for dependency in step.depends_on
        },
        "primary_reference_sha256": (
            request.primary_reference.sha256 if request.primary_reference else None
        ),
    }
    expected_hash = step.parameters.get("expected_modeling_plan_sha256")
    expected_policy = step.parameters.get("expected_assembly_consistency_policy")
    if expected_hash is not None or expected_policy is not None:
        modeling_plan_path = job_dir(plan.job_id) / "analysis" / "modeling_plan.json"
        if not modeling_plan_path.is_file():
            payload["current_modeling_plan_sha256"] = "missing"
        else:
            try:
                payload["current_modeling_plan_sha256"] = sha256_file(modeling_plan_path)
            except OSError:
                payload["current_modeling_plan_sha256"] = "unreadable"
    return stable_json_digest(payload)


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


_POLICY_GATE_BY_WORKFLOW_GATE = {
    "proxy_geometry": "generic_proxy_review",
    "detailed_geometry": "generic_detail_review",
    "material_swatches": "material_swatch_acknowledgement",
    "qa_review": "qa_review_acknowledgement",
    "final_package": "final_package_acknowledgement",
    "optimization_plan": "optimization_plan",
}


def _load_policy_authorization(
    root: Path,
    workflow_root: Path,
    plan: WorkflowPlan,
    step: WorkflowStep,
    *,
    input_fingerprint: str,
    actual_plan_hash: str,
):
    """Load an optional exact autonomy policy grant without synthesizing user approval."""

    gate_kind = _POLICY_GATE_BY_WORKFLOW_GATE.get(str(step.approval_gate))
    if gate_kind is None:
        return None
    path = workflow_root / "policy_authorizations" / f"{step.step_id}.json"
    if not path.is_file():
        return None
    from ..autonomy.authorization import validate_policy_authorization
    from ..autonomy.models import PolicyAuthorization, PolicyGateTarget

    authorization = _load_model(path, PolicyAuthorization)
    validate_policy_authorization(
        root,
        authorization,
        expected_job_id=plan.job_id,
        expected_workflow_id=plan.workflow_id,
        expected_step_id=step.step_id,
        expected_gate_kind=gate_kind,
        expected_input_fingerprint=input_fingerprint,
    )
    target_path = _resolve_job_path(root, authorization.gate_target.path)
    target = _load_model(target_path, PolicyGateTarget)
    if (
        target.job_id != plan.job_id
        or target.workflow_id != plan.workflow_id
        or target.dispatch_id != authorization.dispatch_id
        or target.workflow_step_id != step.step_id
        or target.workflow_input_fingerprint != input_fingerprint
        or target.gate_kind != gate_kind
        or target.workflow_plan.sha256 != actual_plan_hash
    ):
        raise ValueError("Policy gate target is stale or bound to another workflow boundary")
    return authorization


def _matching_succeeded_attempt(
    workflow_root: Path,
    step: WorkflowStep,
    *,
    plan_sha256: str,
    input_fingerprint: str,
    output_fingerprint: str,
) -> WorkflowAttempt | None:
    """Find the immutable host receipt matching the exact current lifecycle evidence."""

    attempt_root = workflow_root / "attempts" / step.step_id
    if not attempt_root.is_dir():
        return None
    for path in sorted(attempt_root.glob("*.json"), reverse=True):
        try:
            attempt = _load_model(path, WorkflowAttempt)
        except (OSError, ValueError):
            continue
        if (
            attempt.status == "succeeded"
            and attempt.plan_sha256 == plan_sha256
            and attempt.input_fingerprint == input_fingerprint
            and attempt.output_fingerprint == output_fingerprint
        ):
            return attempt
    return None


def _matching_interrupted_attempt(
    workflow_root: Path,
    step: WorkflowStep,
    *,
    workflow_id: str,
    job_id: str,
    plan_sha256: str,
    input_fingerprint: str,
) -> WorkflowAttempt | None:
    """Find an exact recovered interruption that may authorize terminal adoption."""

    attempt_root = workflow_root / "attempts" / step.step_id
    if not attempt_root.is_dir():
        return None
    for path in sorted(attempt_root.glob("*.json"), reverse=True):
        try:
            attempt = _load_model(path, WorkflowAttempt)
        except (OSError, ValueError):
            continue
        if (
            attempt.status == "failed"
            and attempt.error_type == "InterruptedAttempt"
            and attempt.workflow_id == workflow_id
            and attempt.job_id == job_id
            and attempt.step_id == step.step_id
            and attempt.plan_sha256 == plan_sha256
            and attempt.input_fingerprint == input_fingerprint
        ):
            return attempt
    return None


def _matching_geometry_multiview_recovery_attempt(
    workflow_root: Path,
    step: WorkflowStep,
    *,
    workflow_id: str,
    job_id: str,
    plan_sha256: str,
    input_fingerprint: str,
) -> WorkflowAttempt | None:
    """Find exact prior host-failure evidence that may own a multi-view run.

    Interrupted attempts qualify explicitly.  Current host failures and legacy
    failed receipts without a reason code also qualify so an explicit failed-step
    retry can reuse or recover run-owned evidence.  Artifact-conflict and scope
    boundary receipts never establish ownership of a pre-existing run.
    """

    attempt_root = workflow_root / "attempts" / step.step_id
    if not attempt_root.is_dir():
        return None
    for path in sorted(attempt_root.glob("*.json"), reverse=True):
        try:
            attempt = _load_model(path, WorkflowAttempt)
        except (OSError, ValueError):
            continue
        ownership_blocked = attempt.error_type in {
            "OrchestrationArtifactConflict",
            "RequiresStandardWorkflow",
        }
        owns_failed_run = not ownership_blocked and (
            attempt.error_type == "InterruptedAttempt"
            or attempt.reason_code in {None, "host_failure"}
        )
        if (
            attempt.status == "failed"
            and owns_failed_run
            and attempt.workflow_id == workflow_id
            and attempt.job_id == job_id
            and attempt.step_id == step.step_id
            and attempt.plan_sha256 == plan_sha256
            and attempt.input_fingerprint == input_fingerprint
        ):
            return attempt
    return None


def _step_uses_immutable_lifecycle(step: WorkflowStep) -> bool:
    """Return whether one step opts into snapshot/run-owned V0.8 evidence."""

    return any(output.lifecycle != "canonical" for output in step.outputs)


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
        from ..optimization.models import OptimizationApproval

        run_id = str(step.parameters["run_id"])
        directory = root / "optimization" / "runs" / run_id
        plan_path = directory / "review_plan.json"
        approval_path = directory / "optimization_approval.json"
        if not plan_path.is_file() or not approval_path.is_file():
            return False
        try:
            approval = OptimizationApproval.model_validate_json(
                approval_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return False
        return bool(
            approval.job_id == root.name
            and approval.run_id == run_id
            and approval.profile_id
            == step.parameters.get(
                "profile_id",
                approval.profile_id,
            )
            and approval.plan_sha256 == sha256_file(plan_path)
        )
    if step.approval_gate == "interior_qa_plan":
        run_id = str(step.parameters["run_id"])
        directory = root / "qa" / "interior" / "runs" / run_id
        plan_path = directory / "plan.json"
        approval_path = directory / "plan_approval.json"
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
        trial_id = str(step.parameters.get("trial_id", ""))
        trial_root = root / "qa" / "candidate_reviews" / trial_id
        receipt_path = trial_root / "promotion_receipt.json"
        try:
            decision, approval = validate_candidate_review_approval(
                root,
                trial_id,
                require_current_sources=not receipt_path.is_file(),
            )
            if receipt_path.is_file():
                receipt = CandidateReviewPromotionReceipt.model_validate_json(
                    receipt_path.read_text(encoding="utf-8")
                )
                return bool(
                    approval.used
                    and receipt.job_id == decision.job_id
                    and receipt.trial_id == trial_id
                    and receipt.decision_sha256
                    == sha256_file(trial_root / "decision_manifest.json")
                )
            return bool(not approval.used and decision.promotable)
        except (OSError, RuntimeError, ValueError):
            return False
    return False


def _specialized_approval_identity(
    root: Path,
    step: WorkflowStep,
    artifact_fingerprint: str,
) -> str:
    """Keep specialized approval identity stable across expected single-use consumption."""

    run_id = str(step.parameters.get("run_id", step.parameters.get("trial_id", "")))
    if step.approval_gate == "optimization_plan":
        approval_path = root / "optimization" / "runs" / run_id / "optimization_approval.json"
        payload = json.loads(approval_path.read_text(encoding="utf-8"))
        payload.pop("used", None)
        payload.pop("used_at", None)
        return stable_json_digest(payload)
    if step.approval_gate == "interior_qa_plan":
        approval_path = root / "qa" / "interior" / "runs" / run_id / "plan_approval.json"
        payload = json.loads(approval_path.read_text(encoding="utf-8"))
        payload.pop("status", None)
        payload.pop("consumed_at", None)
        return stable_json_digest(payload)
    if step.approval_gate == "visual_revision":
        approval_path = root / "qa" / "candidate_reviews" / run_id / "promotion_approval.json"
        payload = json.loads(approval_path.read_text(encoding="utf-8"))
        payload.pop("used", None)
        payload.pop("used_at", None)
        return stable_json_digest(payload)
    return artifact_fingerprint


def _step_milestone(
    completed_ids: set[str],
    execution_policy: str,
) -> str:
    """Map completed standard or fast-lane evidence onto V0.8 milestones."""

    if "portable.final_approval" in completed_ids:
        return "portable_ready"
    if execution_policy == "background_exterior" and "portable.report" in completed_ids:
        return "portable_ready"
    if "qa.review" in completed_ids:
        return "qa_review"
    if execution_policy == "background_exterior" and "qa.report" in completed_ids:
        return "qa_review"
    if "interior_qa.review" in completed_ids:
        return "qa_review"
    if "material.approval" in completed_ids:
        return "material_ready"
    if execution_policy == "background_exterior" and "material.report" in completed_ids:
        return "material_ready"
    if "interior.scope_approval" in completed_ids:
        return "interior_scope_approved"
    if "interior.scope_author" in completed_ids:
        return "interior_scope_waiting"
    if "geometry.detail_approval" in completed_ids or "revision.validate" in completed_ids:
        return "geometry_approved"
    if "revision.promote" in completed_ids:
        return "geometry_approved"
    if "geometry.proxy_approval" in completed_ids:
        return "geometry_approved"
    if "proxy.validate" in completed_ids:
        return "proxy_ready"
    if "background_geometry.validate" in completed_ids:
        return "proxy_ready"
    if "reference.analyze" in completed_ids:
        return "analyzed"
    return "created"


def _background_quality_state_summary(
    root: Path,
    plan: WorkflowPlan,
    states: list[WorkflowStepState],
) -> tuple[str | None, bool | None, str | None, str | None]:
    """Load a completed new-policy quality report into the workflow state projection."""

    completed = {item.step_id for item in states if item.status == "complete"}
    step = next(
        (
            item
            for item in plan.steps
            if item.step_id == "background.eligibility"
            and item.parameters.get("quality_policy") == "review_delivery_v2"
        ),
        None,
    )
    if step is None or step.step_id not in completed or not step.outputs:
        return None, None, None, None
    path = _resolve_job_path(root, step.outputs[0].path)
    report = BackgroundQualityReport.model_validate_json(path.read_text(encoding="utf-8"))
    if report.workflow_id != plan.workflow_id or report.job_id != plan.job_id:
        raise OrchestrationArtifactConflict(
            "orchestration_artifact_conflict: quality report identity changed"
        )
    return (
        report.quality_status,
        report.standard_workflow_recommended,
        _job_relative(root, path),
        sha256_file(path),
    )


def _next_action(
    step: WorkflowStep,
    input_fingerprint: str,
    step_status: str,
) -> str:
    """Describe the next exact tool or approval action without executing agent judgment."""

    if step_status == "blocked" and step.tool_name in {
        "evaluate_background_delivery",
        "verify_background_preview_prerequisite",
    }:
        return (
            "Create a new immutable standard workflow for this job; "
            "do not retry or reinterpret the blocked background_exterior plan."
        )
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
    if step.execution_mode == "specialized_approval" and step.approval_gate == "optimization_plan":
        return (
            "Inspect optimization_review.json and choose approve, revise_asset, "
            "revise_profile, or cancel. Use revise_asset for geometry or visual-quality "
            "corrections through a new standard workflow planned with intent=revise_asset "
            "and execution_policy=standard; no choice is automatic and only approve may "
            "create the exact hash-bound optimization approval."
        )
    if step.execution_mode == "specialized_approval" and step.approval_gate == "visual_revision":
        return (
            "Inspect the candidate-review before/after decision, then approve only its exact "
            "decision_manifest.json SHA-256 with approve_candidate_review_promotion. "
            "This is the single user-facing promotion gate; internal fingerprints remain "
            "machine-verified."
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
    if (
        request.reference_content_scope != plan.reference_content_scope
        or request.target_subject != plan.target_subject
    ):
        raise RuntimeError("Workflow request and plan reference-content scopes do not match")
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
        reason_code = None
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
                if (
                    completion.plan_sha256 == actual_plan_hash
                    and completion.input_fingerprint == input_fingerprint
                ):
                    recovered = _expected_superseded_agent_artifacts(
                        root,
                        workflow_root,
                        plan,
                        step,
                        completion,
                        artifacts,
                        previous,
                    )
                    if recovered is not None:
                        artifacts = recovered
                        artifact_fingerprint = _artifact_fingerprint(artifacts)
                        artifacts_valid = all(item.integrity == "valid" for item in artifacts)
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
                    reason_code = "orchestration_artifact_conflict"
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
                    reason_code = "orchestration_artifact_conflict"
            else:
                try:
                    policy_authorization = _load_policy_authorization(
                        root,
                        workflow_root,
                        plan,
                        step,
                        input_fingerprint=input_fingerprint,
                        actual_plan_hash=actual_plan_hash,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    status = "stale"
                    error = f"Autonomy policy authorization is stale: {exc}"
                    reason_code = "orchestration_artifact_conflict"
                else:
                    if policy_authorization is None:
                        status = "waiting_for_approval"
                    else:
                        status = "complete"
                        approval_id = policy_authorization.authorization_id
                        completion_fingerprint = stable_json_digest(
                            {
                                "input": input_fingerprint,
                                "policy_authorization": (
                                    policy_authorization.authorization_id
                                ),
                            }
                        )
                        completed_at = policy_authorization.consumed_at
        elif step.execution_mode == "specialized_approval":
            if _specialized_approval_valid(root, step, artifacts):
                status = "complete"
                approval_identity = _specialized_approval_identity(
                    root,
                    step,
                    artifact_fingerprint,
                )
                completion_fingerprint = stable_json_digest(
                    {"input": input_fingerprint, "approval": approval_identity}
                )
                completed_at = _utc_now()
            else:
                try:
                    policy_authorization = _load_policy_authorization(
                        root,
                        workflow_root,
                        plan,
                        step,
                        input_fingerprint=input_fingerprint,
                        actual_plan_hash=actual_plan_hash,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    status = "stale"
                    error = f"Autonomy policy authorization is stale: {exc}"
                    reason_code = "orchestration_artifact_conflict"
                else:
                    if policy_authorization is None:
                        status = "waiting_for_approval"
                    else:
                        status = "complete"
                        approval_id = policy_authorization.authorization_id
                        completion_fingerprint = stable_json_digest(
                            {
                                "input": input_fingerprint,
                                "policy_authorization": (
                                    policy_authorization.authorization_id
                                ),
                            }
                        )
                        completed_at = policy_authorization.consumed_at
        elif step.execution_mode == "manual":
            status = "blocked"
            error = "No validated destination adapter is available."
            reason_code = "host_failure"
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
            immutable_lifecycle = _step_uses_immutable_lifecycle(step)
            matching_attempt = (
                _matching_succeeded_attempt(
                    workflow_root,
                    step,
                    plan_sha256=actual_plan_hash,
                    input_fingerprint=input_fingerprint,
                    output_fingerprint=artifact_fingerprint,
                )
                if immutable_lifecycle and artifacts_valid
                else None
            )
            if immutable_lifecycle and matching_attempt is not None:
                status = "complete"
                completion_fingerprint = stable_json_digest(
                    {
                        "input": input_fingerprint,
                        "output": artifact_fingerprint,
                        "attempt_id": matching_attempt.attempt_id,
                    }
                )
                completed_at = matching_attempt.completed_at
            elif (
                immutable_lifecycle
                and prior is not None
                and prior.status == "complete"
                and (not same_input or not same_outputs)
            ):
                status = "blocked"
                error = "Immutable workflow evidence changed after its successful host attempt."
                reason_code = "orchestration_artifact_conflict"
            elif (
                not immutable_lifecycle
                and artifacts_valid
                and (
                    (
                        prior is not None
                        and prior.status == "complete"
                        and same_input
                        and same_outputs
                    )
                    or can_adopt
                    or (prior is not None and not same_outputs)
                    or step.tool_name in {"create_job", "verify_geometry_prerequisite"}
                )
            ):
                status = "complete"
                completion_fingerprint = stable_json_digest(
                    {"input": input_fingerprint, "output": artifact_fingerprint}
                )
                completed_at = completed_at or _utc_now()
            elif prior is not None and prior.status == "failed" and same_input:
                status = "failed"
                error = prior.error
                reason_code = prior.reason_code or "host_failure"
            elif artifacts and any(item.integrity == "corrupt" for item in artifacts):
                status = "blocked"
                error = "One or more host-step outputs are corrupt."
                reason_code = (
                    "orchestration_artifact_conflict" if immutable_lifecycle else "host_failure"
                )
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
            reason_code=reason_code,  # type: ignore[arg-type]
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
    milestone = _step_milestone(completed_ids, plan.execution_policy)
    if aggregate_status == "completed":
        milestone = (
            "delivered_for_review"
            if plan.execution_policy == "background_exterior"
            and plan.delivery_scope == "preview_only"
            else "completed"
        )
    if plan.destination.status == "unsupported":
        warnings.append(plan.destination.reason)
    (
        quality_status,
        standard_workflow_recommended,
        quality_report_path,
        quality_report_sha256,
    ) = _background_quality_state_summary(root, plan, ordered_states)
    if quality_status == "needs_revision":
        warnings.append(
            "Preview execution completed, but visual quality needs a standard revision."
        )
    elif quality_status == "unscorable":
        warnings.append("Preview execution completed, but quality evidence was unscorable.")
    now = _utc_now()
    state = WorkflowState(
        workflow_id=plan.workflow_id,
        job_id=plan.job_id,
        plan_sha256=actual_plan_hash,
        request_sha256=actual_request_hash,
        reference_content_scope=plan.reference_content_scope,
        target_subject=plan.target_subject,
        execution_policy=plan.execution_policy,
        delivery_scope=plan.delivery_scope,
        status=aggregate_status,  # type: ignore[arg-type]
        milestone=milestone,  # type: ignore[arg-type]
        current_step_id=current_step.step_id if current_step else None,
        steps=ordered_states,
        next_action=(
            (
                "Inspect the immutable workflow evidence and mutable source ownership "
                "conflict; do not classify it as a standard-workflow quality risk."
                if states[current_step.step_id].reason_code == "orchestration_artifact_conflict"
                else _next_action(
                    current_step,
                    states[current_step.step_id].input_fingerprint or stable_json_digest({}),
                    states[current_step.step_id].status,
                )
            )
            if current_step
            else None
        ),
        waiting_gate=waiting_gate,  # type: ignore[arg-type]
        warnings=warnings,
        reason_code=(
            states[current_step.step_id].reason_code if current_step is not None else None
        ),
        quality_status=quality_status,  # type: ignore[arg-type]
        standard_workflow_recommended=standard_workflow_recommended,
        quality_report_path=quality_report_path,
        quality_report_sha256=quality_report_sha256,
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
        _verify_dependency_sources(root, workflow_root, plan, step)
        step_state = next(item for item in state.steps if item.step_id == step_id)
        if step_state.input_fingerprint != input_fingerprint:
            raise ValueError("Completion input fingerprint does not match current workflow state")
        if any(
            output.lifecycle == "workflow_snapshot"
            and not _resolve_job_path(root, output.path).exists()
            for output in step.outputs
        ):
            _validate_agent_completion_semantics(root, step, request)
            _materialize_step_snapshots(root, step)
            state = _reconcile_locked(
                root,
                workflow_root,
                plan,
                request,
                previous=state,
            )
            step_state = next(item for item in state.steps if item.step_id == step_id)
            if step_state.input_fingerprint != input_fingerprint:
                raise OrchestrationArtifactConflict(
                    "orchestration_artifact_conflict: input changed while materializing "
                    "the agent-owned workflow snapshot"
                )
        if not step_state.artifacts or any(
            item.integrity != "valid" for item in step_state.artifacts
        ):
            raise RuntimeError("Completion outputs are missing or invalid")
        _validate_agent_completion_semantics(root, step, request)
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


def _verify_background_preview_prerequisite(
    root: Path,
    request: WorkflowRequest,
    step: WorkflowStep,
) -> None:
    """Verify a package continuation against its exact completed preview and source."""

    binding = request.background_preview_binding
    if binding is None:
        raise RequiresStandardWorkflow(
            "requires_standard_workflow: package continuation has no preview binding"
        )
    conflict_reasons: list[str] = []
    scope_reasons: list[str] = []
    expected_parameters = {
        "preview_workflow_id": binding.workflow_id,
        "preview_plan_sha256": binding.plan_sha256,
        "preview_terminal_fingerprint": binding.terminal_completion_fingerprint,
        "source_fingerprint": binding.source_fingerprint,
        "build_fingerprint": binding.build_fingerprint,
    }
    if binding.quality_report_path is not None:
        expected_parameters.update(
            {
                "quality_status": binding.quality_status,
                "standard_workflow_recommended": (binding.standard_workflow_recommended),
                "quality_report_path": binding.quality_report_path,
                "quality_report_sha256": binding.quality_report_sha256,
            }
        )
    for name, expected in expected_parameters.items():
        if step.parameters.get(name) != expected:
            conflict_reasons.append(f"immutable plan parameter mismatch: {name}")
    preview_root = _workflow_dir(root, binding.workflow_id)
    try:
        preview_request = _load_model(
            preview_root / "request.json",
            WorkflowRequest,
        )
        preview_plan = _load_model(
            preview_root / "plan.json",
            WorkflowPlan,
        )
        preview_state = _load_model(
            preview_root / "state.json",
            WorkflowState,
        )
        reconstructed = _reconcile_locked(
            root,
            preview_root,
            preview_plan,
            preview_request,
            previous=preview_state,
        )
        terminal = next(
            (item for item in reconstructed.steps if item.step_id == preview_plan.terminal_step_id),
            None,
        )
        preview_content_scope = getattr(
            preview_request,
            "reference_content_scope",
            "full_reference",
        )
        preview_target_subject = getattr(preview_request, "target_subject", None)
        if (
            preview_request.execution_policy != "background_exterior"
            or preview_request.delivery_scope != "preview_only"
            or preview_content_scope != request.reference_content_scope
            or preview_target_subject != request.target_subject
            or reconstructed.status != "completed"
            or reconstructed.milestone != "delivered_for_review"
        ):
            conflict_reasons.append("bound preview workflow is no longer current and completed")
        if reconstructed.plan_sha256 != binding.plan_sha256:
            conflict_reasons.append("bound preview plan SHA-256 changed")
        if (
            terminal is None
            or terminal.completion_fingerprint != binding.terminal_completion_fingerprint
        ):
            conflict_reasons.append("bound preview terminal completion fingerprint changed")
    except (OSError, RuntimeError, ValueError) as exc:
        conflict_reasons.append(
            f"bound preview workflow cannot be reconstructed: {type(exc).__name__}"
        )
    try:
        source = collect_source_provenance(root, request.job_id)
        if source.source_fingerprint != binding.source_fingerprint:
            conflict_reasons.append("canonical source fingerprint changed after preview")
        if source.build_fingerprint != binding.build_fingerprint:
            conflict_reasons.append("embedded build fingerprint changed after preview")
    except (OSError, RuntimeError, ValueError) as exc:
        conflict_reasons.append(f"current source provenance is unavailable: {type(exc).__name__}")
    if binding.quality_report_path is not None:
        quality_path = _resolve_job_path(root, binding.quality_report_path)
        if not quality_path.is_file() or sha256_file(quality_path) != binding.quality_report_sha256:
            conflict_reasons.append("bound background quality report changed")
    scope_contract = load_interior_scope(root)
    if scope_contract is not None and scope_contract.policy != "disabled":
        scope_reasons.append("InteriorScope became enabled after preview")
    try:
        scene_spec = load_scene_spec(root / "analysis" / "scene_spec.json")
        if list_interior_objects(scene_spec):
            scope_reasons.append("interior semantic geometry appeared after preview")
    except (OSError, RuntimeError, ValueError) as exc:
        conflict_reasons.append(f"current SceneSpec cannot be validated: {type(exc).__name__}")
    if (root / "constraints" / "constraints.json").is_file():
        scope_reasons.append("measured constraints appeared after preview")
    output_path = _resolve_job_path(root, str(step.parameters["output_path"]))
    reasons = [*conflict_reasons, *scope_reasons]
    passed = not reasons
    status = (
        "passed"
        if passed
        else "orchestration_artifact_conflict"
        if conflict_reasons
        else "requires_standard_workflow"
    )
    payload = {
        "schema_version": "0.8.0",
        "job_id": request.job_id,
        "workflow_id": request.workflow_id,
        "status": status,
        "ok": passed,
        "preview_binding": binding.model_dump(mode="json"),
        "blocking_reasons": reasons,
        "verified_at": _utc_now().isoformat(),
    }
    preserve_existing = False
    if passed and output_path.is_file():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            preserve_existing = (
                existing.get("ok") is True
                and existing.get("job_id") == request.job_id
                and existing.get("workflow_id") == request.workflow_id
                and existing.get("preview_binding") == binding.model_dump(mode="json")
                and existing.get("blocking_reasons") == []
            )
        except (OSError, json.JSONDecodeError):
            preserve_existing = False
    if not preserve_existing:
        write_json_atomic(output_path, payload)
    if conflict_reasons:
        raise OrchestrationArtifactConflict(
            "orchestration_artifact_conflict: bound background preview evidence changed"
        )
    if scope_reasons:
        raise RequiresStandardWorkflow(
            "requires_standard_workflow: bound background preview or canonical source changed"
        )


def _evaluate_background_delivery(
    root: Path,
    request: WorkflowRequest,
    step: WorkflowStep,
) -> None:
    """Classify new review delivery while retaining the legacy fail-closed policy."""

    if step.parameters.get("quality_policy") == "review_delivery_v2":
        try:
            evaluate_background_quality(
                root,
                job_id=request.job_id,
                workflow_id=request.workflow_id,
                qa_run_id=str(step.parameters["qa_run_id"]),
                role_map_path=_resolve_job_path(
                    root,
                    str(step.parameters["role_map_path"]),
                ),
                fit_report_path=_resolve_job_path(
                    root,
                    str(step.parameters["fit_report_path"]),
                ),
                output_path=_resolve_job_path(
                    root,
                    str(step.parameters["output_path"]),
                ),
            )
        except BackgroundQualityConflict as exc:
            raise OrchestrationArtifactConflict(f"orchestration_artifact_conflict: {exc}") from exc
        return

    from ..qa import VisualQAReport

    exact_run_id = step.parameters.get("qa_run_id")
    if exact_run_id is None:
        latest_path = root / "qa" / "latest.json"
        if not latest_path.is_file():
            raise RuntimeError("background delivery requires QA evidence")
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        report_relative = latest.get("visual_qa_report")
        if not isinstance(report_relative, str) or not report_relative:
            raise RuntimeError("Legacy QA latest pointer has no visual_qa_report")
        report_path = _resolve_job_path(root, report_relative)
        qa_run_root = report_path.parent
        qa_run_id = str(latest.get("run_id") or qa_run_root.name)
    else:
        qa_run_id = str(exact_run_id)
        qa_run_root = root / "qa" / "runs" / qa_run_id
        report_path = qa_run_root / "visual_qa_report.json"
    report_path = qa_run_root / "visual_qa_report.json"
    request_path = qa_run_root / "request.json"
    pass_manifest_path = qa_run_root / "render_pass_manifest.json"
    if not report_path.is_file() or (
        exact_run_id is not None
        and not all(path.is_file() for path in (request_path, pass_manifest_path))
    ):
        raise RuntimeError("background delivery requires the exact planned QA run evidence")
    report = VisualQAReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    blocking = [
        finding
        for finding in report.findings
        if (
            finding.severity == "high"
            and set(finding.evidence_sources) & {"direct_reference", "constraint"}
        )
    ]
    reasons = [
        {
            "finding_id": finding.id,
            "issue_type": finding.issue_type,
            "description": finding.description,
            "target_ids": finding.target_ids,
        }
        for finding in blocking
    ]
    if report.generated_target_status != "not_requested":
        reasons.append(
            {
                "finding_id": "generated_target_not_disabled",
                "issue_type": "other",
                "description": (
                    "background_exterior requires direct-reference QA without a generated target"
                ),
                "target_ids": [],
            }
        )
    passed = not reasons
    output_path = _resolve_job_path(root, str(step.parameters["output_path"]))
    source = collect_source_provenance(root, request.job_id) if exact_run_id is not None else None
    qa_evidence = {
        "qa_run_id": qa_run_id,
        "visual_qa_report_path": _job_relative(root, report_path),
        "visual_qa_report_sha256": sha256_file(report_path),
    }
    if request_path.is_file():
        qa_evidence.update(
            {
                "qa_request_path": _job_relative(root, request_path),
                "qa_request_sha256": sha256_file(request_path),
            }
        )
    if pass_manifest_path.is_file():
        qa_evidence.update(
            {
                "render_pass_manifest_path": _job_relative(
                    root,
                    pass_manifest_path,
                ),
                "render_pass_manifest_sha256": sha256_file(pass_manifest_path),
            }
        )
    write_json_atomic(
        output_path,
        {
            "schema_version": "0.8.0",
            "job_id": request.job_id,
            "workflow_id": request.workflow_id,
            "execution_policy": request.execution_policy,
            "delivery_scope": request.delivery_scope,
            "status": "passed" if passed else "requires_standard_workflow",
            "ok": passed,
            **qa_evidence,
            "direct_score": report.direct_metrics.overall_direct_score,
            "blocking_findings": reasons,
            "source_fingerprint": (source.source_fingerprint if source is not None else None),
            "build_fingerprint": (source.build_fingerprint if source is not None else None),
            "evaluated_at": _utc_now().isoformat(),
        },
    )
    if not passed:
        raise RequiresStandardWorkflow(
            "requires_standard_workflow: direct QA contains high-severity direct, "
            "constraint, or generated-target evidence"
        )


def _apply_guarded_revision(job_id: str, workflow_id: str) -> None:
    """Promote a validated RevisionPlan atomically after archiving the prior SceneSpec."""

    root = job_dir(job_id)
    current = root / "analysis" / "scene_spec.json"
    plan = root / "analysis" / "revision_plan.json"
    candidate = root / "analysis" / f".scene_spec.workflow-{workflow_id}-{uuid4().hex}.next.json"
    _validated, report = apply_revision_plan(
        scene_spec_path=current,
        plan_path=plan,
        output_path=candidate,
    )
    replace_scene_spec_if_current(
        job_id,
        candidate,
        expected_current_sha256=report["base_spec_sha256"],
        expected_candidate_sha256=report["result_spec_sha256"],
        lock_owner_id=workflow_id,
    )
    candidate.unlink(missing_ok=True)
    write_json_atomic(root / "reports" / "revision_diff.json", report)


def _verify_revision_modeling_plan_binding(root: Path, step: WorkflowStep) -> None:
    """Reject a changed ModelingPlan before a guarded revision mutates SceneSpec.

    Historical workflow plans have neither parameter and retain their former
    behavior.  Newly planned revisions must provide both values and match the
    exact current authored contract.
    """

    expected_hash = step.parameters.get("expected_modeling_plan_sha256")
    expected_policy = step.parameters.get("expected_assembly_consistency_policy")
    if expected_hash is None and expected_policy is None:
        return
    if not isinstance(expected_hash, str) or not isinstance(expected_policy, str):
        raise OrchestrationArtifactConflict(
            "orchestration_artifact_conflict: revision ModelingPlan binding is incomplete"
        )
    from ..analysis.models import ModelingPlan

    path = root / "analysis" / "modeling_plan.json"
    if not path.is_file() or sha256_file(path) != expected_hash:
        raise OrchestrationArtifactConflict(
            "orchestration_artifact_conflict: revision ModelingPlan hash changed"
        )
    plan = ModelingPlan.model_validate_json(path.read_text(encoding="utf-8"))
    if plan.stage != "authored" or plan.assembly_consistency_policy != expected_policy:
        raise OrchestrationArtifactConflict(
            "orchestration_artifact_conflict: revision ModelingPlan policy changed"
        )


def _execute_host_tool(
    root: Path,
    workflow_root: Path,
    request: WorkflowRequest,
    step: WorkflowStep,
    *,
    input_fingerprint: str,
) -> None:
    """Execute one whitelisted deterministic host step with explicit parameters."""

    _verify_revision_modeling_plan_binding(root, step)
    tool = step.tool_name
    if tool in {"create_job", "verify_geometry_prerequisite"}:
        return
    if tool == "verify_background_preview_prerequisite":
        _verify_background_preview_prerequisite(root, request, step)
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
    if tool == "fit_background_exterior":
        try:
            run_background_pre_qa_fit(
                request.job_id,
                workflow_id=request.workflow_id,
                input_fingerprint=input_fingerprint,
                initial_candidate_path=_resolve_job_path(
                    root,
                    str(step.parameters["initial_candidate_path"]),
                ),
                fit_root=_resolve_job_path(
                    root,
                    str(step.parameters["fit_root"]),
                ),
                max_attempts=int(step.parameters["max_attempts"]),
            )
        except BackgroundFitConflict as exc:
            raise OrchestrationArtifactConflict(f"orchestration_artifact_conflict: {exc}") from exc
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
        _apply_guarded_revision(request.job_id, request.workflow_id)
        return
    if tool == "evaluate_candidate_revision":
        trial_id = str(step.parameters["trial_id"])
        trial_root = root / "qa" / "candidate_reviews" / trial_id
        decision_path = trial_root / "decision_manifest.json"
        report_path = trial_root / "candidate_review_report.pdf"
        report_manifest_path = trial_root / "candidate_review_report.manifest.json"
        try:
            if decision_path.is_file():
                validate_candidate_review_decision(
                    root,
                    decision_path,
                    require_current_sources=True,
                )
            else:
                evaluate_candidate_review(
                    request.job_id,
                    trial_id=trial_id,
                    revision_plan_path=str(step.parameters["revision_plan_path"]),
                    input_fingerprint=input_fingerprint,
                    workflow_id=request.workflow_id,
                    minimum_improvement=float(
                        step.parameters.get("minimum_improvement", 0.001)
                    ),
                )
                validate_candidate_review_decision(
                    root,
                    decision_path,
                    require_current_sources=True,
                )
            if report_path.is_file() != report_manifest_path.is_file():
                raise CandidateReviewConflict(
                    "candidate-review PDF evidence is only partially published"
                )
            if report_manifest_path.is_file():
                validate_candidate_review_pdf_manifest(root, report_manifest_path)
            else:
                generate_candidate_review_pdf(request.job_id, trial_id)
        except (CandidateReviewConflict, FileExistsError) as exc:
            raise OrchestrationArtifactConflict(
                f"orchestration_artifact_conflict: {exc}"
            ) from exc
        return
    if tool == "promote_candidate_revision":
        try:
            promote_candidate_review(
                request.job_id,
                str(step.parameters["trial_id"]),
                workflow_id=request.workflow_id,
            )
        except CandidateReviewConflict as exc:
            raise OrchestrationArtifactConflict(
                f"orchestration_artifact_conflict: {exc}"
            ) from exc
        return
    if tool == "material_scaffold":
        create_material_scaffold(request.job_id, overwrite=False)
        return
    if tool == "material_scaffold_candidate":
        created = create_workflow_material_candidates(
            request.job_id,
            request.workflow_id,
        )
        if created["scaffold_root"] != step.parameters.get("scaffold_root") or created[
            "authored_root"
        ] != step.parameters.get("authored_root"):
            raise RuntimeError("Workflow material scaffold paths do not match the plan")
        return
    if tool == "promote_material_contracts":
        promote_workflow_material_candidate(
            request.job_id,
            request.workflow_id,
            candidate_plan_path=str(step.parameters["candidate_plan_path"]),
            receipt_path=str(step.parameters["promotion_receipt_path"]),
            input_fingerprint=input_fingerprint,
        )
        return
    if tool == "validate_material_contracts":
        result = validate_job_material_contracts(request.job_id)
        if result.get("ok") is not True:
            raise RuntimeError("Material contract validation did not report ok=true")
        return
    if tool == "validate_material_fidelity":
        result = validate_job_material_fidelity(request.job_id)
        if result.get("ok") is not True:
            raise RuntimeError("Material fidelity validation did not report ok=true")
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
            run_id=(str(step.parameters["run_id"]) if "run_id" in step.parameters else None),
        )
        return
    if tool == "run_visual_diagnostics":
        qa_run_id = str(step.parameters["qa_run_id"])
        diagnostic_id = str(step.parameters["diagnostic_id"])
        terminal_bundle = (
            root
            / "qa"
            / "runs"
            / qa_run_id
            / "diagnostics"
            / diagnostic_id
            / "bundle_manifest.json"
        )
        if terminal_bundle.is_file():
            # A published terminal bundle is reusable only when this exact step and
            # input have a recovered interruption proving the prior host call died
            # after publication but before its success receipt was finalized.
            plan_path = workflow_root / "plan.json"
            interrupted_attempt = _matching_interrupted_attempt(
                workflow_root,
                step,
                workflow_id=request.workflow_id,
                job_id=request.job_id,
                plan_sha256=sha256_file(plan_path),
                input_fingerprint=input_fingerprint,
            )
            if interrupted_attempt is None:
                raise OrchestrationArtifactConflict(
                    "orchestration_artifact_conflict: existing QA diagnostic bundle "
                    "has no exact recovered InterruptedAttempt receipt for this "
                    "workflow step, plan, and input fingerprint"
                )
            try:
                bundle, _diagnostic_request, _diagnostic_report = validate_qa_diagnostic_bundle(
                    root, terminal_bundle
                )
            except (OSError, ValueError) as exc:
                raise OrchestrationArtifactConflict(
                    "orchestration_artifact_conflict: existing QA diagnostic bundle "
                    "cannot be adopted because its exact evidence is stale or invalid"
                ) from exc
            if bundle.qa_run_id != qa_run_id or bundle.diagnostic_id != diagnostic_id:
                raise OrchestrationArtifactConflict(
                    "orchestration_artifact_conflict: existing QA diagnostic bundle "
                    "does not match the planned identity"
                )
            return
        run_job_visual_diagnostics(
            request.job_id,
            qa_run_id,
            diagnostic_id=diagnostic_id,
            max_camera_probes=int(step.parameters.get("max_camera_probes", 12)),
            include_multiview_sanity=bool(step.parameters.get("include_multiview_sanity", True)),
        )
        return
    if tool == "run_geometry_multiview_review":
        run_id = str(step.parameters["run_id"])
        run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
        plan_path = run_root / "plan.json"
        manifest_path = run_root / "render_manifest.json"
        report_path = run_root / "report.json"
        views_path = run_root / "views"
        if plan_path.is_file():
            prior_attempt = _matching_geometry_multiview_recovery_attempt(
                workflow_root,
                step,
                workflow_id=request.workflow_id,
                job_id=request.job_id,
                plan_sha256=sha256_file(workflow_root / "plan.json"),
                input_fingerprint=input_fingerprint,
            )
            if prior_attempt is None:
                raise OrchestrationArtifactConflict(
                    "orchestration_artifact_conflict: pre-existing geometry multi-view "
                    "plan has no exact prior interrupted or failed host-attempt receipt"
                )
            partial_plan = AssemblySanityPlan.model_validate_json(
                plan_path.read_text(encoding="utf-8")
            )
            if (
                partial_plan.job_id != request.job_id
                or partial_plan.run_id != run_id
                or partial_plan.review_policy != step.parameters.get("review_policy")
                or partial_plan.resolution
                != (
                    int(step.parameters.get("resolution", 384)),
                    int(step.parameters.get("resolution", 384)),
                )
            ):
                raise OrchestrationArtifactConflict(
                    "orchestration_artifact_conflict: partial geometry multi-view "
                    "plan differs from the exact workflow contract"
                )
            exact_plan_sha256 = sha256_file(plan_path)
            terminal_exists = manifest_path.is_file() and report_path.is_file()
            if terminal_exists:
                try:
                    adopted_plan, _adopted_manifest, adopted_report = (
                        validate_assembly_sanity_terminal(
                            root,
                            plan_path=plan_path,
                            plan_sha256=exact_plan_sha256,
                            manifest_path=manifest_path,
                            manifest_sha256=sha256_file(manifest_path),
                            report_path=report_path,
                            report_sha256=sha256_file(report_path),
                            expected_job_id=request.job_id,
                            expected_run_id=run_id,
                        )
                    )
                except (OSError, RuntimeError, ValueError):
                    try:
                        recover_incomplete_job_assembly_multiview_sanity(
                            request.job_id,
                            run_id,
                            plan_sha256=exact_plan_sha256,
                            recovery_authorized=True,
                        )
                    except (OSError, RuntimeError, ValueError) as recovery_exc:
                        raise OrchestrationArtifactConflict(
                            "orchestration_artifact_conflict: invalid prior-failed geometry "
                            "multi-view terminal could not be safely recovered"
                        ) from recovery_exc
                else:
                    if adopted_plan.review_policy != step.parameters.get(
                        "review_policy"
                    ) or adopted_report.review_policy != step.parameters.get("review_policy"):
                        raise OrchestrationArtifactConflict(
                            "orchestration_artifact_conflict: recovered geometry multi-view "
                            "policy differs from the workflow plan"
                        )
                    return
            if manifest_path.exists() or report_path.exists() or views_path.exists():
                try:
                    recover_incomplete_job_assembly_multiview_sanity(
                        request.job_id,
                        run_id,
                        plan_sha256=exact_plan_sha256,
                        recovery_authorized=True,
                    )
                except (OSError, RuntimeError, ValueError) as recovery_exc:
                    raise OrchestrationArtifactConflict(
                        "orchestration_artifact_conflict: prior-failed geometry multi-view "
                        "evidence could not be safely recovered"
                    ) from recovery_exc
            result = run_job_assembly_multiview_sanity(
                request.job_id,
                run_id,
                plan_sha256=exact_plan_sha256,
            )
            if (
                Path(str(result["render_manifest"])).resolve() != manifest_path.resolve()
                or Path(str(result["report"])).resolve() != report_path.resolve()
                or result.get("review_policy") != step.parameters.get("review_policy")
            ):
                raise RuntimeError(
                    "geometry multi-view recovery output differs from workflow paths"
                )
            return
        if run_root.exists() or run_root.is_symlink():
            prior_attempt = _matching_geometry_multiview_recovery_attempt(
                workflow_root,
                step,
                workflow_id=request.workflow_id,
                job_id=request.job_id,
                plan_sha256=sha256_file(workflow_root / "plan.json"),
                input_fingerprint=input_fingerprint,
            )
            if prior_attempt is None:
                raise OrchestrationArtifactConflict(
                    "orchestration_artifact_conflict: unpublished geometry multi-view run "
                    "has no exact prior interrupted or failed host-attempt receipt"
                )
            try:
                recover_unpublished_job_assembly_multiview_plan(
                    request.job_id,
                    run_id,
                    recovery_authorized=True,
                )
            except (OSError, RuntimeError, ValueError) as recovery_exc:
                raise OrchestrationArtifactConflict(
                    "orchestration_artifact_conflict: unpublished geometry multi-view run "
                    "could not be safely recovered"
                ) from recovery_exc
        if manifest_path.exists() or report_path.exists() or views_path.exists():
            raise OrchestrationArtifactConflict(
                "orchestration_artifact_conflict: geometry multi-view derived evidence "
                "exists without its immutable plan"
            )
        planned = plan_job_assembly_multiview_sanity(
            request.job_id,
            run_id=run_id,
            resolution=int(step.parameters.get("resolution", 384)),
        )
        if Path(str(planned["plan"])).resolve() != plan_path.resolve() or planned.get(
            "review_policy"
        ) != step.parameters.get("review_policy"):
            raise RuntimeError("geometry multi-view plan differs from workflow parameters")
        result = run_job_assembly_multiview_sanity(
            request.job_id,
            run_id,
            plan_sha256=str(planned["plan_sha256"]),
        )
        if (
            Path(str(result["render_manifest"])).resolve() != manifest_path.resolve()
            or Path(str(result["report"])).resolve() != report_path.resolve()
            or result.get("review_policy") != step.parameters.get("review_policy")
        ):
            raise RuntimeError("geometry multi-view output differs from workflow paths")
        return
    if tool == "evaluate_background_delivery":
        _evaluate_background_delivery(root, request, step)
        return
    if tool == "validate_interior_scope":
        report = validate_job_interior_scope(request.job_id, write_report=True)
        if not report.ok:
            raise RuntimeError("InteriorScope validation did not report ok=true")
        return
    if tool == "plan_interior_qa":
        plan_job_interior_qa(
            request.job_id,
            profile=str(step.parameters.get("profile", "standard")),
            run_id=str(step.parameters["run_id"]),
        )
        return
    if tool == "run_interior_qa":
        run_id = str(step.parameters["run_id"])
        plan_path = root / "qa" / "interior" / "runs" / run_id / "plan.json"
        run_job_interior_qa(
            request.job_id,
            run_id,
            approved_plan_sha256=sha256_file(plan_path),
        )
        return
    if tool == "generate_pdf_report":
        output_path = _resolve_job_path(root, str(step.parameters["output_path"]))
        generate_job_pdf_report(
            request.job_id,
            str(step.parameters["scope"]),  # type: ignore[arg-type]
            qa_run_id=str(step.parameters.get("qa_run_id", "latest")),
            interior_qa_run_id=str(step.parameters.get("interior_qa_run_id", "latest")),
            optimization_run_id=str(step.parameters.get("optimization_run_id", "latest")),
            package_id=str(step.parameters.get("package_id", "latest")),
            background_quality_report_path=(
                str(step.parameters["background_quality_report_path"])
                if "background_quality_report_path" in step.parameters
                else None
            ),
            assembly_sanity_run_id=(
                str(step.parameters["assembly_sanity_run_id"])
                if "assembly_sanity_run_id" in step.parameters
                else None
            ),
            output_path=output_path,
        )
        return
    if tool == "initialize_asset_profile":
        _ensure_workflow_asset_profile(
            root,
            request.job_id,
            str(step.parameters["profile_id"]),
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
            source_quality_path=(
                str(step.parameters["source_quality_path"])
                if "source_quality_path" in step.parameters
                else None
            ),
        )
        return
    if tool == "optimize_portable_asset":
        run_id = str(step.parameters["run_id"])
        approved_hash = sha256_file(root / "optimization" / "runs" / run_id / "review_plan.json")
        policy_path = (
            workflow_root
            / "policy_authorizations"
            / "portable.plan_approval.json"
        )
        policy_input_fingerprint = None
        if policy_path.is_file():
            from ..autonomy.models import PolicyAuthorization

            policy_input_fingerprint = _load_model(
                policy_path,
                PolicyAuthorization,
            ).workflow_input_fingerprint
        optimize_asset(
            request.job_id,
            profile_id=str(step.parameters["profile_id"]),
            run_id=run_id,
            approved_plan_sha256=approved_hash,
            policy_authorization_path=(policy_path if policy_path.is_file() else None),
            workflow_id=(request.workflow_id if policy_path.is_file() else None),
            workflow_step_id=(
                "portable.plan_approval" if policy_path.is_file() else None
            ),
            workflow_input_fingerprint=policy_input_fingerprint,
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
    workflow_root: Path,
    previous: WorkflowState | None,
    *,
    retry_failed: bool,
) -> WorkflowState | None:
    """Reset only an explicitly authorized host step with an exact failed receipt."""

    if not retry_failed:
        return previous
    if previous is None or previous.current_step_id is None:
        raise RuntimeError("No current failed workflow step is available for retry")
    current = next(
        (item for item in previous.steps if item.step_id == previous.current_step_id),
        None,
    )
    retryable_blocked_conflict = False
    if (
        previous.status == "blocked"
        and current is not None
        and current.status == "blocked"
        and current.reason_code == "orchestration_artifact_conflict"
        and current.input_fingerprint is not None
    ):
        attempt_root = workflow_root / "attempts" / current.step_id
        retryable_blocked_conflict = (
            any(
                attempt.status == "failed"
                and attempt.input_fingerprint == current.input_fingerprint
                and attempt.reason_code == "orchestration_artifact_conflict"
                for attempt in (
                    _load_model(path, WorkflowAttempt)
                    for path in sorted(attempt_root.glob("*.json"), reverse=True)
                )
            )
            if attempt_root.is_dir()
            else False
        )
    retryable_failed = bool(
        previous.status == "failed" and current is not None and current.status == "failed"
    )
    if not retryable_failed and not retryable_blocked_conflict:
        raise RuntimeError("No current failed workflow step is available for retry")
    found = False
    steps: list[WorkflowStepState] = []
    for item in previous.steps:
        if item.step_id == previous.current_step_id and item.status in {"failed", "blocked"}:
            found = True
            steps.append(
                item.model_copy(
                    update={
                        "status": "ready",
                        "error": None,
                        "reason_code": None,
                    }
                )
            )
        else:
            steps.append(item)
    if not found:
        raise RuntimeError("Current workflow step is not a failed retryable step")
    return previous.model_copy(
        update={
            "status": "running",
            "steps": steps,
            "reason_code": None,
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
        _verify_dependency_sources(root, workflow_root, plan, step)
        _execute_host_tool(
            root,
            workflow_root,
            request,
            step,
            input_fingerprint=current.input_fingerprint,
        )
        _verify_revision_modeling_plan_binding(root, step)
        _materialize_step_snapshots(root, step)
        outputs = [_inspect_artifact(root, output, None) for output in step.outputs]
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
        reason_code = (
            "requires_standard_workflow"
            if isinstance(exc, RequiresStandardWorkflow)
            else "orchestration_artifact_conflict"
            if isinstance(exc, OrchestrationArtifactConflict)
            else "host_failure"
        )
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
            reason_code=reason_code,  # type: ignore[arg-type]
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
        if request.background_preview_binding is not None and previous is not None:
            prerequisite_state = next(
                (item for item in previous.steps if item.step_id == "geometry.prerequisite"),
                None,
            )
            if prerequisite_state is not None and prerequisite_state.status == "complete":
                prerequisite = next(
                    item for item in plan.steps if item.step_id == "geometry.prerequisite"
                )
                try:
                    _verify_background_preview_prerequisite(
                        root,
                        request,
                        prerequisite,
                    )
                except RequiresStandardWorkflow:
                    blocked = _reconcile_locked(
                        root,
                        workflow_root,
                        plan,
                        request,
                        previous=previous,
                    )
                    blocked = blocked.model_copy(
                        update={
                            "status": "blocked",
                            "next_action": (
                                "Create a new immutable standard workflow for this job; "
                                "do not retry the blocked background_exterior plan."
                            ),
                            "updated_at": _utc_now(),
                        }
                    )
                    _write_state(root, workflow_root, blocked)
                    return blocked
        previous = _prepare_failed_step_retry(
            workflow_root,
            previous,
            retry_failed=retry_failed,
        )
        limit = max_host_steps or request.budgets.max_host_steps_per_resume
        if limit < 1 or limit > 64:
            raise ValueError("max_host_steps must be within [1, 64]")
        state = _reconcile_locked(root, workflow_root, plan, request, previous=previous)
        executed = 0
        while executed < limit and state.current_step_id is not None:
            step = next(item for item in plan.steps if item.step_id == state.current_step_id)
            step_state = next(item for item in state.steps if item.step_id == state.current_step_id)
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
                requires_standard = isinstance(exc, RequiresStandardWorkflow)
                artifact_conflict = isinstance(exc, OrchestrationArtifactConflict)
                failure_status = "blocked" if requires_standard or artifact_conflict else "failed"
                reason_code = (
                    "requires_standard_workflow"
                    if requires_standard
                    else "orchestration_artifact_conflict"
                    if artifact_conflict
                    else "host_failure"
                )
                failed_steps = []
                for item in state.steps:
                    if item.step_id == step.step_id:
                        failed_steps.append(
                            item.model_copy(
                                update={
                                    "status": failure_status,
                                    "attempt_count": item.attempt_count + 1,
                                    "error": f"{type(exc).__name__}: {exc}",
                                    "reason_code": reason_code,
                                }
                            )
                        )
                    else:
                        failed_steps.append(item)
                state = state.model_copy(
                    update={
                        "status": failure_status,
                        "steps": failed_steps,
                        "reason_code": reason_code,
                        "next_action": (
                            (
                                "Create a new immutable standard workflow for this job; "
                                "do not retry the blocked background_exterior plan."
                            )
                            if requires_standard
                            else (
                                "Inspect the reported orchestration artifact ownership or "
                                "fingerprint conflict. Do not reinterpret it as a quality "
                                "risk or auto-switch workflow policy."
                            )
                            if artifact_conflict
                            else (
                                f"Resolve {type(exc).__name__} in step {step.step_id}, then resume."
                            )
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
                                "reason_code": None,
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
            item if item.status == "complete" else item.model_copy(update={"status": "cancelled"})
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
