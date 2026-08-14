"""Generic orchestration facade for canonical-write-free Material Closure preflight."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from .collector import (
    MaterialClosureCollectionError,
    replay_host_graph_derived_closure,
    validate_material_plan_absence_evidence,
)
from .models import (
    ExactArtifact,
    MaterialAppearanceApproval,
    MaterialCanonicalMaterialPlanAbsence,
    MaterialCanonicalSnapshot,
    MaterialClosureBoundContract,
    MaterialClosureIssue,
    MaterialClosureSourceBindingArtifact,
    MaterialDependencyClosure,
    MaterialDependencyClosureReceipt,
    MaterialFrameworkFailureReport,
    MaterialGraphRebindingReceipt,
    MaterialNeutralPreviewManifest,
    MaterialPreflightBudget,
    MaterialPreflightCheck,
    MaterialPreflightResourceReceipt,
    MaterialPromotionPreflightFailure,
    MaterialPromotionPreflightReport,
    MaterialPromotionPreflightRequest,
    MaterialResourceCounters,
    MaterialShadowCompileReceipt,
)
from .preflight import (
    MaterialPreflightValidationError,
    _is_link_like,
    collect_current_uv_layout_fingerprint,
    resolve_contained_path,
    validate_candidate_material_contracts,
    validate_declared_surface_detail_completeness,
    validate_dependency_closure,
    validate_exact_artifact,
    validate_preflight_budget,
    validate_preflight_for_approval,
    validate_surface_details,
)
from .shadow_compile import (
    SHADOW_BLENDER_RUN_COUNT,
    build_neutral_preview_manifest,
)
from .shadow_compile import (
    run_material_shadow_compile as _run_material_shadow_compile,
)
from .surface_detail_preflight import validate_preflight_uv_source_binding

_PRODUCER = "material_closure_service"
_PRODUCER_VERSION = "0.1.0"
ModelT = TypeVar("ModelT", bound=BaseModel)
AnyBoundContract = MaterialClosureBoundContract


@dataclass(frozen=True)
class MaterialPromotionPreflightResult:
    """Return either a complete approval-eligible bundle or one fail-closed result."""

    report: MaterialPromotionPreflightReport | None
    report_artifact: ExactArtifact | None
    failure: MaterialPromotionPreflightFailure | None
    failure_artifact: ExactArtifact | None
    framework_failure_report: MaterialFrameworkFailureReport | None
    framework_failure_report_artifact: ExactArtifact | None
    shadow_receipt: MaterialShadowCompileReceipt | None
    shadow_receipt_artifact: ExactArtifact | None
    neutral_preview: MaterialNeutralPreviewManifest | None
    neutral_preview_artifact: ExactArtifact | None
    resource_receipt: MaterialPreflightResourceReceipt | None
    resource_receipt_artifact: ExactArtifact | None

    @property
    def approval_plan_eligible(self) -> bool:
        """Expose eligibility only for a fully passed preflight report."""

        return self.report is not None and self.failure is None

    @property
    def status(self) -> Literal["complete_preflight_passed", "complete_preflight_failed"]:
        """Label the result as a complete preflight, never as standalone shadow evidence."""

        if self.approval_plan_eligible:
            return "complete_preflight_passed"
        return "complete_preflight_failed"

    @property
    def execution_scope(self) -> Literal["complete_preflight_with_shadow_compile"]:
        """Declare that the public shadow facade always executes every preflight gate."""

        return "complete_preflight_with_shadow_compile"


@dataclass(frozen=True)
class MaterialAppearanceApprovalPublication:
    """Return an exact caller-authored approval published after current preflight replay."""

    approval: MaterialAppearanceApproval
    approval_artifact: ExactArtifact
    preflight_report: MaterialPromotionPreflightReport


def _canonical_json_bytes(value: object) -> bytes:
    """Serialize one strict evidence payload deterministically for immutable publication."""

    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_bytes_exclusive(path: Path, content: bytes) -> None:
    """Publish one immutable file or adopt only identical existing bytes."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    if os.path.exists(native_io_path(path)):
        if not os.path.isfile(native_io_path(path)):
            raise FileExistsError(path)
        with open(native_io_path(path), "rb") as handle:
            if handle.read() != content:
                raise FileExistsError(f"existing immutable evidence differs: {path.name}")
        return
    with open(native_io_path(path), "xb") as handle:
        handle.write(content)


def _artifact(
    job_root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
) -> ExactArtifact:
    """Create one exact JSON artifact binding below the owning job root."""

    root = job_root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise MaterialPreflightValidationError("preflight output escapes the owning job") from exc
    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=relative,
        sha256=sha256_file(resolved),
        byte_size=os.path.getsize(native_io_path(resolved)),
        media_type="application/json",
    )


def _write_model(
    job_root: Path,
    path: Path,
    model: BaseModel,
    *,
    artifact_id: str,
    kind: str,
) -> ExactArtifact:
    """Write or byte-adopt one strict model and return its exact artifact contract."""

    _write_bytes_exclusive(path, _canonical_json_bytes(model))
    return _artifact(job_root, path, artifact_id=artifact_id, kind=kind)


def _load_model(job_root: Path, artifact: ExactArtifact, model: type[ModelT]) -> ModelT:
    """Load one exact strict model after replaying its path, size, and digest."""

    path = validate_exact_artifact(job_root, artifact)
    try:
        return model.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise MaterialPreflightValidationError(
            f"{artifact.kind} artifact is not valid {model.__name__} evidence"
        ) from exc


def _same_artifact(left: ExactArtifact, right: ExactArtifact) -> bool:
    """Compare exact artifact identity without depending on descriptive labels."""

    return (left.path, left.sha256, left.byte_size) == (
        right.path,
        right.sha256,
        right.byte_size,
    )


def _read_exact_json_object(job_root: Path, artifact: ExactArtifact) -> dict[str, Any]:
    """Load one exact UTF-8 JSON object for host identity and discriminator checks."""

    path = validate_exact_artifact(job_root, artifact)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaterialPreflightValidationError(
            f"{artifact.kind} is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise MaterialPreflightValidationError(f"{artifact.kind} is not a JSON object")
    return payload


def _require_json_scope(
    payload: dict[str, Any],
    request: MaterialPromotionPreflightRequest,
    *,
    label: str,
) -> None:
    """Require one generic host evidence object to carry the exact request identity."""

    observed = tuple(
        payload.get(name)
        for name in ("job_id", "workflow_id", "dispatch_id", "session_id")
    )
    if observed != _binding_tuple(request):
        raise MaterialPreflightValidationError(f"{label} targets another workflow session")


def _validate_current_state_context(
    job_root: Path,
    request: MaterialPromotionPreflightRequest,
) -> None:
    """Strict-parse AQ/attempt state or the documented minimal Standard state envelope."""

    artifact = request.framework_failure_context.current_state
    payload = _read_exact_json_object(job_root, artifact)
    sequence: object
    if payload.get("kind") == "standard_workflow_state":
        expected_keys = {
            "kind",
            "schema_version",
            "job_id",
            "workflow_id",
            "dispatch_id",
            "session_id",
            "sequence",
            "status",
        }
        if (
            set(payload) != expected_keys
            or payload.get("schema_version") != "0.1.0"
            or not isinstance(payload.get("sequence"), int)
            or not isinstance(payload.get("status"), str)
        ):
            raise MaterialPreflightValidationError(
                "generic Standard current state has an invalid strict envelope"
            )
        _require_json_scope(payload, request, label="generic Standard current state")
        sequence = payload["sequence"]
    elif "attempt_id" in payload:
        from .models import MaterialAttemptState

        try:
            state = MaterialAttemptState.model_validate(payload)
        except ValidationError as exc:
            raise MaterialPreflightValidationError(
                "current MaterialAttemptState is invalid"
            ) from exc
        if _binding_tuple(state) != _binding_tuple(request):
            raise MaterialPreflightValidationError(
                "current MaterialAttemptState targets another workflow session"
            )
        sequence = state.sequence
    elif payload.get("schema_version") == "0.2.0" and "state_id" in payload:
        from ..autonomy_v2.models import AutonomyStateV2

        try:
            state_v2 = AutonomyStateV2.model_validate(payload)
        except ValidationError as exc:
            raise MaterialPreflightValidationError("current AQ v2 state is invalid") from exc
        if _binding_tuple(state_v2) != _binding_tuple(request):
            raise MaterialPreflightValidationError(
                "current AQ v2 state targets another workflow session"
            )
        sequence = state_v2.sequence
    else:
        raise MaterialPreflightValidationError(
            "current state has no recognized AQ v2, MaterialAttempt, or Standard "
            "discriminator"
        )
    if sequence != request.framework_failure_context.state_sequence:
        raise MaterialPreflightValidationError(
            "current state sequence differs from strict framework failure context"
        )


def _binding_tuple(value: Any) -> tuple[str, str, str, str]:
    """Project the common job/workflow/dispatch/session binding from one contract."""

    return (
        str(value.job_id),
        str(value.workflow_id),
        str(value.dispatch_id),
        str(value.session_id),
    )


def _capture_canonical_state(
    job_root: Path,
    snapshot: MaterialCanonicalSnapshot,
) -> dict[str, tuple[str, int] | None]:
    """Capture live canonical geometry and material bytes for shadow isolation checks."""

    paths = {
        snapshot.scene_spec.path,
        snapshot.modeling_plan.path,
        snapshot.blend.path,
        "analysis/material_plan.json",
    }
    state: dict[str, tuple[str, int] | None] = {}
    for relative_path in sorted(paths):
        path = resolve_contained_path(job_root, relative_path, must_exist=False)
        if not os.path.exists(native_io_path(path)):
            state[relative_path] = None
            continue
        if not os.path.isfile(native_io_path(path)):
            raise MaterialPreflightValidationError(
                f"canonical path is not a regular file: {relative_path}"
            )
        state[relative_path] = (
            sha256_file(path),
            os.path.getsize(native_io_path(path)),
        )
    return state


def _validate_live_material_baseline(
    job_root: Path,
    snapshot: MaterialCanonicalSnapshot,
    *,
    source_binding: MaterialClosureSourceBindingArtifact,
    observation_state: ExactArtifact,
) -> None:
    """Require the embedded MaterialPlan artifact or absence to match the live canonical path."""

    canonical_path = resolve_contained_path(
        job_root,
        "analysis/material_plan.json",
        must_exist=False,
    )
    if snapshot.material_plan is None:
        if os.path.exists(native_io_path(canonical_path)):
            raise MaterialPreflightValidationError(
                "canonical MaterialPlan exists despite the bound absence baseline"
            )
        assert snapshot.material_plan_absence is not None
        absence = _load_model(
            job_root,
            snapshot.material_plan_absence,
            MaterialCanonicalMaterialPlanAbsence,
        )
        try:
            validate_material_plan_absence_evidence(
                job_root,
                absence,
                source_binding=source_binding,
            )
        except MaterialClosureCollectionError as exc:
            raise MaterialPreflightValidationError(
                f"canonical MaterialPlan absence is stale: {exc}"
            ) from exc
        if not _same_artifact(absence.observation_state, observation_state):
            raise MaterialPreflightValidationError(
                "canonical MaterialPlan absence observation state is inconsistent"
            )
        if (
            not _same_artifact(absence.canonical_scene_spec, snapshot.scene_spec)
            or not _same_artifact(absence.canonical_blend, snapshot.blend)
        ):
            raise MaterialPreflightValidationError(
                "canonical MaterialPlan absence targets another canonical snapshot"
            )
        return
    if snapshot.material_plan.path != "analysis/material_plan.json":
        raise MaterialPreflightValidationError(
            "canonical MaterialPlan snapshot targets a noncanonical path"
        )
    validate_exact_artifact(job_root, snapshot.material_plan)


def _validate_request_dependencies(
    job_root: Path,
    request: MaterialPromotionPreflightRequest,
    *,
    require_current_canonical: bool = True,
) -> tuple[
    MaterialDependencyClosure,
    MaterialDependencyClosureReceipt,
    MaterialGraphRebindingReceipt,
    MaterialCanonicalSnapshot,
    MaterialPreflightBudget,
    list[MaterialPreflightCheck],
]:
    """Replay every strict request dependency before any Blender process can start."""

    closure = _load_model(job_root, request.closure, MaterialDependencyClosure)
    closure_receipt = _load_model(
        job_root,
        request.closure_receipt,
        MaterialDependencyClosureReceipt,
    )
    rebinding = _load_model(
        job_root,
        request.graph_rebinding_receipt,
        MaterialGraphRebindingReceipt,
    )
    snapshot = _load_model(job_root, request.canonical_snapshot, MaterialCanonicalSnapshot)
    budget = _load_model(job_root, request.budget, MaterialPreflightBudget)
    expected_binding = _binding_tuple(request)
    for contract in (closure, closure_receipt, rebinding, snapshot, budget):
        if _binding_tuple(contract) != expected_binding:
            raise MaterialPreflightValidationError(
                f"{type(contract).__name__} targets another material session"
            )
    if snapshot != request.framework_failure_context.canonical_snapshot:
        raise MaterialPreflightValidationError(
            "preflight canonical snapshot differs from its strict failure context"
        )
    if not _same_artifact(closure_receipt.closure, request.closure):
        raise MaterialPreflightValidationError("closure receipt targets another closure file")
    if not _same_artifact(rebinding.source_binding, closure.source_binding):
        raise MaterialPreflightValidationError(
            "graph rebinding targets another closure source binding"
        )
    if rebinding.status != "passed" or rebinding.rebound_graph is None:
        raise MaterialPreflightValidationError("MaterialGraph rebinding did not pass")
    if not _same_artifact(rebinding.rebound_graph, request.rebound_material_graph):
        raise MaterialPreflightValidationError("preflight request targets another rebound graph")
    entries_by_role = {item.role: item for item in closure.entries}
    rebound_entry = entries_by_role.get("rebound_material_graph")
    rebinding_receipt_entry = entries_by_role.get("material_graph_rebinding_receipt")
    if (
        rebound_entry is None
        or (
            rebound_entry.path,
            rebound_entry.sha256,
            rebound_entry.byte_size,
        )
        != (
            request.rebound_material_graph.path,
            request.rebound_material_graph.sha256,
            request.rebound_material_graph.byte_size,
        )
    ):
        raise MaterialPreflightValidationError(
            "exact rebound MaterialGraph is absent from dependency closure"
        )
    if (
        rebinding_receipt_entry is None
        or (
            rebinding_receipt_entry.path,
            rebinding_receipt_entry.sha256,
            rebinding_receipt_entry.byte_size,
        )
        != (
            request.graph_rebinding_receipt.path,
            request.graph_rebinding_receipt.sha256,
            request.graph_rebinding_receipt.byte_size,
        )
    ):
        raise MaterialPreflightValidationError(
            "exact graph rebinding receipt is absent from dependency closure"
        )
    validate_exact_artifact(job_root, closure.source_binding)
    source_binding = _load_model(
        job_root,
        closure.source_binding,
        MaterialClosureSourceBindingArtifact,
    )
    validate_preflight_uv_source_binding(request, source_binding)
    inventory_entry = next(
        (
            item
            for item in closure.entries
            if item.path == source_binding.canonical_scene_inventory_path
        ),
        None,
    )
    if inventory_entry is None:
        raise MaterialPreflightValidationError(
            "dependency closure omits the canonical scene inventory used for UV identity"
        )
    inventory_artifact = ExactArtifact(
        artifact_id="canonical-scene-inventory",
        kind="scene_inventory",
        path=inventory_entry.path,
        sha256=inventory_entry.sha256,
        byte_size=inventory_entry.byte_size,
        media_type="application/json",
    )
    if collect_current_uv_layout_fingerprint(
        job_root,
        inventory_artifact,
        expected_job_id=request.job_id,
    ) != request.uv_layout_fingerprint:
        raise MaterialPreflightValidationError(
            "request UV fingerprint differs from current canonical scene inventory"
        )
    if require_current_canonical:
        try:
            replayed_closure = replay_host_graph_derived_closure(job_root, closure)
        except MaterialClosureCollectionError as exc:
            raise MaterialPreflightValidationError(
                f"closure dependency replay failed: {exc}"
            ) from exc
        if replayed_closure != closure:
            raise MaterialPreflightValidationError(
                "dependency closure differs from host recursive source-root collection"
            )
    immutable_projection, planned_projection = validate_dependency_closure(
        job_root,
        closure,
        receipt=closure_receipt,
        require_current_canonical=require_current_canonical,
        historical_mutable_paths=(
            set()
            if require_current_canonical
            else {
                snapshot.blend.path,
                *(
                    []
                    if snapshot.material_plan is None
                    else [snapshot.material_plan.path]
                ),
            }
        ),
    )
    if planned_projection != request.planned_output_projection:
        raise MaterialPreflightValidationError("preflight planned output projection changed")
    planned_by_kind = {item.output_kind: item for item in closure.planned_outputs}
    if (
        planned_by_kind["material_plan"].sha256
        != request.candidate_material_plan.sha256
        or planned_by_kind["material_graph"].sha256
        != request.rebound_material_graph.sha256
    ):
        raise MaterialPreflightValidationError(
            "planned material outputs differ from the exact preflight candidate"
        )
    if require_current_canonical:
        validate_exact_artifact(job_root, snapshot.scene_spec)
        validate_exact_artifact(job_root, snapshot.modeling_plan)
        validate_exact_artifact(job_root, snapshot.blend)
        validate_exact_artifact(
            job_root,
            snapshot.material_plan or snapshot.material_plan_absence,
        )
        _validate_live_material_baseline(
            job_root,
            snapshot,
            source_binding=source_binding,
            observation_state=request.framework_failure_context.current_state,
        )
    closure_projection = closure.project_immutable_input_map()
    for artifact in (
        snapshot.scene_spec,
        snapshot.modeling_plan,
        snapshot.blend,
        snapshot.material_plan or snapshot.material_plan_absence,
    ):
        assert artifact is not None
        if closure_projection.get(artifact.path) != artifact.sha256:
            raise MaterialPreflightValidationError(
                f"canonical snapshot is absent from dependency closure: {artifact.path}"
            )
    candidate_plan, _graph, material_checks = validate_candidate_material_contracts(
        job_root,
        candidate_material_plan=request.candidate_material_plan,
        rebound_material_graph=request.rebound_material_graph,
        scene_spec=snapshot.scene_spec,
    )
    scene_payload = json.loads(
        validate_exact_artifact(job_root, snapshot.scene_spec).read_text(encoding="utf-8")
    )
    scene_object_ids = {
        str(item.get("id"))
        for item in scene_payload.get("objects", [])
        if isinstance(item, dict) and item.get("id")
    }
    scene_material_ids = {
        str(item.get("id"))
        for item in scene_payload.get("materials", [])
        if isinstance(item, dict) and item.get("id")
    }
    planned_surface_detail_count = validate_declared_surface_detail_completeness(
        job_root,
        modeling_plan_artifact=snapshot.modeling_plan,
        scene_spec_artifact=snapshot.scene_spec,
        inventory_artifact=inventory_artifact,
        material_plan=candidate_plan,
        requirements=request.surface_details,
        bindings=request.surface_bindings,
        uv_layout_fingerprint=request.uv_layout_fingerprint,
    )
    surface_result = validate_surface_details(
        job_root,
        requirements=request.surface_details,
        bindings=request.surface_bindings,
        scene_object_ids=scene_object_ids,
        scene_material_ids=scene_material_ids,
    )
    if surface_result.status != "passed":
        messages = "; ".join(item.message for item in surface_result.issues)
        raise MaterialPreflightValidationError(f"surface-detail preflight failed: {messages}")
    validate_preflight_budget(budget, required_blender_runs=SHADOW_BLENDER_RUN_COUNT)
    checks = [
        MaterialPreflightCheck(
            check_id="dependency_closure",
            category="dependency",
            status="passed",
            message=(
                f"Closure replayed {len(immutable_projection)} immutable inputs and "
                f"{len(planned_projection)} exact planned outputs."
            ),
            evidence=[request.closure, request.closure_receipt],
        ),
        MaterialPreflightCheck(
            check_id="graph_rebinding",
            category="contract",
            status="passed",
            message="Host-owned graph provenance rebinding passed without semantic changes.",
            evidence=[request.graph_rebinding_receipt, request.rebound_material_graph],
        ),
        MaterialPreflightCheck(
            check_id="material_contracts",
            category="contract",
            status="passed",
            message=f"Candidate MaterialPlan passed {len(material_checks)} strict checks.",
            evidence=[request.candidate_material_plan],
        ),
        MaterialPreflightCheck(
            check_id="surface_details",
            category="surface_detail",
            status="passed" if planned_surface_detail_count else "not_applicable",
            message=(
                f"Validated {planned_surface_detail_count} ModelingPlan surface-detail bindings."
                if planned_surface_detail_count
                else "ModelingPlan declares no material-owned localized surface detail."
            ),
        ),
        MaterialPreflightCheck(
            check_id="preflight_budget",
            category="budget",
            status="passed",
            message=(
                f"At least {SHADOW_BLENDER_RUN_COUNT} isolated Blender runs remain without "
                "borrowing controller, promotion, or appearance budget."
            ),
            evidence=[request.budget],
        ),
        MaterialPreflightCheck(
            check_id="rollback_baseline",
            category="rollback",
            status="passed",
            message="Exact rollback baseline and canonical snapshot are current.",
            evidence=[closure.rollback_baseline, request.canonical_snapshot],
        ),
    ]
    return closure, closure_receipt, rebinding, snapshot, budget, checks


def _resource_receipt(
    *,
    request: MaterialPromotionPreflightRequest,
    closure: MaterialDependencyClosure,
    budget: MaterialPreflightBudget,
    before: MaterialResourceCounters,
    blender_runs: int,
    created_at: datetime,
) -> MaterialPreflightResourceReceipt:
    """Account only actually attempted shadow Blender processes in the preflight category."""

    event = MaterialResourceCounters(
        preflight_blender_runs=blender_runs,
        controller_invocations=0,
        canonical_promotions=0,
        appearance_revisions=0,
        transient_controller_retries=0,
    )
    after = MaterialResourceCounters(
        **{
            name: getattr(before, name) + getattr(event, name)
            for name in type(event).model_fields
        }
    )
    if after.preflight_blender_runs > budget.limits.preflight_blender_runs:
        raise MaterialPreflightValidationError("shadow execution exceeded preflight budget")
    return MaterialPreflightResourceReceipt(
        receipt_id=f"resource-{request.request_id}",
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        dispatch_id=request.dispatch_id,
        session_id=request.session_id,
        producer=_PRODUCER,
        producer_version=_PRODUCER_VERSION,
        created_at=created_at,
        budget=request.budget,
        closure_sha256=closure.closure_sha256,
        preflight_input_sha256=stable_json_digest(
            {
                "request": request.model_dump(mode="json"),
                "closure_sha256": closure.closure_sha256,
            }
        ),
        action="executed",
        before=before,
        consumed_by_event=event,
        after=after,
        cache_hash_reverified=False,
    )


def _resource_chain_head(
    job_root: Path,
    request: MaterialPromotionPreflightRequest,
    budget: MaterialPreflightBudget,
) -> MaterialResourceCounters:
    """Replay this session's immutable budget receipts and return the sole current head."""

    preflights_root = resolve_contained_path(
        job_root,
        f"production/material_closure/{request.session_id}/preflights",
        must_exist=False,
    )
    if not preflights_root.exists():
        return budget.consumed
    if not preflights_root.is_dir() or _is_link_like(preflights_root):
        raise MaterialPreflightValidationError("preflight resource root is not a safe directory")
    records: list[tuple[str, MaterialPreflightResourceReceipt]] = []
    request_ids: set[str] = set()
    receipt_ids: set[str] = set()
    for request_root in sorted(preflights_root.iterdir(), key=lambda item: item.name):
        if request_root.name == ".resource_chain.lock" and request_root.is_file():
            continue
        if _is_link_like(request_root) or not request_root.is_dir():
            raise MaterialPreflightValidationError(
                "preflight resource root contains an unsafe entry"
            )
        receipt_path = request_root / "preflight_resource_receipt.json"
        if not receipt_path.exists():
            continue
        if _is_link_like(receipt_path):
            raise MaterialPreflightValidationError(
                "preflight resource receipt cannot be a link"
            )
        relative = receipt_path.relative_to(job_root).as_posix()
        artifact = _artifact(
            job_root,
            receipt_path,
            artifact_id=f"resource-chain-{request_root.name}",
            kind="material_preflight_resource_receipt",
        )
        receipt = _load_model(
            job_root,
            artifact,
            MaterialPreflightResourceReceipt,
        )
        observed_request_id = request_root.name
        request_path = request_root / "preflight_request.json"
        request_artifact = _artifact(
            job_root,
            request_path,
            artifact_id=observed_request_id,
            kind="material_preflight_request",
        )
        prior_request = _load_model(
            job_root,
            request_artifact,
            MaterialPromotionPreflightRequest,
        )
        if prior_request.request_id != observed_request_id:
            raise MaterialPreflightValidationError(
                "resource receipt directory differs from its immutable request"
            )
        prior_closure = _load_model(
            job_root,
            prior_request.closure,
            MaterialDependencyClosure,
        )
        if (
            _binding_tuple(receipt) != _binding_tuple(request)
            or _binding_tuple(prior_request) != _binding_tuple(request)
            or not _same_artifact(receipt.budget, request.budget)
            or not _same_artifact(prior_request.budget, request.budget)
            or receipt.closure_sha256 != prior_closure.closure_sha256
            or receipt.preflight_input_sha256
            != stable_json_digest(
                {
                    "request": prior_request.model_dump(mode="json"),
                    "closure_sha256": prior_closure.closure_sha256,
                }
            )
        ):
            raise MaterialPreflightValidationError(
                f"resource receipt targets another session or budget: {relative}"
            )
        report_path = request_root / "preflight_report.json"
        failure_path = request_root / "preflight_failure.json"
        if report_path.is_file() == failure_path.is_file():
            raise MaterialPreflightValidationError(
                "resource receipt has no unique immutable preflight terminal"
            )
        if report_path.is_file():
            report_artifact = _artifact(
                job_root,
                report_path,
                artifact_id=f"resource-report-{observed_request_id}",
                kind="material_preflight_report",
            )
            report = _load_model(
                job_root,
                report_artifact,
                MaterialPromotionPreflightReport,
            )
            if (
                not _same_artifact(report.request, request_artifact)
                or not _same_artifact(report.resource_receipt, artifact)
            ):
                raise MaterialPreflightValidationError(
                    "preflight terminal does not bind its exact resource receipt"
                )
        else:
            failure_artifact = _artifact(
                job_root,
                failure_path,
                artifact_id=f"resource-failure-{observed_request_id}",
                kind="material_preflight_failure",
            )
            failure = _load_model(
                job_root,
                failure_artifact,
                MaterialPromotionPreflightFailure,
            )
            if not _same_artifact(failure.request, request_artifact):
                raise MaterialPreflightValidationError(
                    "preflight failure does not bind its immutable request"
                )
        shadow_path = request_root / "shadow_compile_receipt.json"
        shadow_artifact = _artifact(
            job_root,
            shadow_path,
            artifact_id=f"resource-shadow-{observed_request_id}",
            kind="material_shadow_compile_receipt",
        )
        shadow = _load_model(
            job_root,
            shadow_artifact,
            MaterialShadowCompileReceipt,
        )
        blender_runs = receipt.consumed_by_event.preflight_blender_runs
        if (
            receipt.action != "executed"
            or any(
                getattr(receipt.consumed_by_event, name) != 0
                for name in type(receipt.consumed_by_event).model_fields
                if name != "preflight_blender_runs"
            )
            or (
                blender_runs != SHADOW_BLENDER_RUN_COUNT
                if shadow.status == "passed"
                else not 0 <= blender_runs <= SHADOW_BLENDER_RUN_COUNT
            )
        ):
            raise MaterialPreflightValidationError(
                "resource receipt counters differ from shadow execution evidence"
            )
        if (
            observed_request_id in request_ids
            or receipt.receipt_id in receipt_ids
            or receipt.receipt_id != f"resource-{observed_request_id}"
        ):
            raise MaterialPreflightValidationError("resource receipt identity is duplicated")
        request_ids.add(observed_request_id)
        receipt_ids.add(receipt.receipt_id)
        records.append((observed_request_id, receipt))
    head = budget.consumed
    remaining = list(records)
    while remaining:
        successors = [item for item in remaining if item[1].before == head]
        if len(successors) != 1:
            raise MaterialPreflightValidationError(
                "preflight resource receipt chain has a gap or fork"
            )
        selected = successors[0]
        remaining.remove(selected)
        receipt = selected[1]
        head = receipt.after
        if any(
            getattr(head, name) > getattr(budget.limits, name)
            for name in type(head).model_fields
        ):
            raise MaterialPreflightValidationError("preflight resource chain exceeds budget")
    return head


def _acquire_resource_chain_lock(
    job_root: Path,
    request: MaterialPromotionPreflightRequest,
) -> tuple[Path, bytes]:
    """Serialize session budget replay and receipt publication across distinct requests."""

    lock_path = resolve_contained_path(
        job_root,
        f"production/material_closure/{request.session_id}/preflights/.resource_chain.lock",
        must_exist=False,
    )
    os.makedirs(native_io_path(lock_path.parent), exist_ok=True)
    content = _canonical_json_bytes(
        {
            "request_id": request.request_id,
            "budget_sha256": request.budget.sha256,
        }
    )
    try:
        with open(native_io_path(lock_path), "xb") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise MaterialPreflightValidationError(
            "material preflight resource chain is already locked"
        ) from exc
    return lock_path, content


def _release_resource_chain_lock(lock: tuple[Path, bytes] | None) -> None:
    """Release only the exact lock bytes created by this service invocation."""

    if lock is None:
        return
    path, expected = lock
    try:
        observed = path.read_bytes()
    except OSError as exc:
        raise MaterialPreflightValidationError(
            "material preflight resource lock disappeared"
        ) from exc
    if observed != expected or _is_link_like(path):
        raise MaterialPreflightValidationError(
            "material preflight resource lock changed unexpectedly"
        )
    os.unlink(native_io_path(path))


def _failure_issue(exc: Exception) -> MaterialClosureIssue:
    """Normalize an exception into one deterministic privacy-safe preflight issue."""

    if isinstance(exc, MaterialPreflightValidationError):
        code = "MATERIAL_PREFLIGHT_INVALID"
    elif isinstance(exc, FileExistsError):
        code = "MATERIAL_PREFLIGHT_CONFLICT"
    else:
        code = "MATERIAL_PREFLIGHT_FAILED"
    return MaterialClosureIssue(code=code, message=(str(exc)[:1800] or type(exc).__name__))


def _framework_failure_report(
    *,
    request: MaterialPromotionPreflightRequest,
    issue: MaterialClosureIssue,
    created_at: datetime,
    resource: MaterialPreflightResourceReceipt | None,
) -> MaterialFrameworkFailureReport:
    """Construct strict framework failure evidence from the request-bound exact context."""

    context = request.framework_failure_context
    return MaterialFrameworkFailureReport(
        report_id=f"framework-{request.request_id}",
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        dispatch_id=request.dispatch_id,
        session_id=request.session_id,
        producer=_PRODUCER,
        producer_version=_PRODUCER_VERSION,
        created_at=created_at,
        state_sequence=context.state_sequence,
        current_state=context.current_state,
        canonical_snapshot=context.canonical_snapshot,
        latest_successful_rollback_receipt=context.latest_successful_rollback_receipt,
        pending_retry_plan=context.pending_retry_plan,
        pending_retry_approval=context.pending_retry_approval,
        controller_execution_count=context.controller_execution_count,
        rollback_count=context.rollback_count,
        budget_usage=resource.after if resource is not None else context.budget_usage,
        aq_budget_observation=context.aq_budget_observation,
        neutral_preview_present=context.neutral_preview_present,
        material_phase_receipt_present=context.material_phase_receipt_present,
        integrated_quality_entered=context.integrated_quality_entered,
        failure_categories=["material_preflight_framework"],
        missing_or_invalid_dependencies=[issue],
        asset_quality_failure="unknown",
        recommended_action=(
            "Repair host-owned closure, rebinding, budget, or shadow inputs; then create a new "
            "immutable preflight request without requesting technical user approval."
        ),
        retry_forbidden_reason=(
            "This request failed before approval eligibility and cannot authorize an existing "
            "technical retry or controller execution."
        ),
    )


class MaterialClosureService:
    """Run deterministic material preflight without approval, controller, or canonical authority."""

    def __init__(self, job_root: Path) -> None:
        """Bind the facade to one existing job root."""

        self.job_root = job_root.expanduser().resolve()
        if not self.job_root.is_dir():
            raise FileNotFoundError(self.job_root)

    def _preflight_root(self, request: MaterialPromotionPreflightRequest) -> Path:
        """Derive the sole run-owned publication root from immutable request identity."""

        relative = (
            f"production/material_closure/{request.session_id}/preflights/"
            f"{request.request_id}"
        )
        return resolve_contained_path(self.job_root, relative, must_exist=False)

    def _validate_failure_context(
        self,
        request: MaterialPromotionPreflightRequest,
    ) -> None:
        """Require complete current failure context before publishing any preflight file."""

        context = request.framework_failure_context
        _validate_current_state_context(self.job_root, request)
        for artifact in (
            context.canonical_snapshot.scene_spec,
            context.canonical_snapshot.modeling_plan,
            context.canonical_snapshot.blend,
            context.canonical_snapshot.material_plan
            or context.canonical_snapshot.material_plan_absence,
            context.latest_successful_rollback_receipt,
            context.pending_retry_plan,
            context.pending_retry_approval,
        ):
            if artifact is not None:
                validate_exact_artifact(self.job_root, artifact)
        typed_context_artifacts = (
            (
                context.latest_successful_rollback_receipt,
                "rollback",
                "latest rollback receipt",
            ),
            (context.pending_retry_plan, "retry", "pending retry plan"),
            (context.pending_retry_approval, "approval", "pending retry approval"),
        )
        for artifact, required_kind_fragment, label in typed_context_artifacts:
            if artifact is None:
                continue
            if required_kind_fragment not in artifact.kind:
                raise MaterialPreflightValidationError(
                    f"{label} artifact kind is not recognized"
                )
            payload = _read_exact_json_object(self.job_root, artifact)
            _require_json_scope(payload, request, label=label)

    def _adopt_terminal_result(
        self,
        root_path: Path,
    ) -> MaterialPromotionPreflightResult | None:
        """Crash-adopt one complete immutable success or failure without rerunning Blender."""

        report_path = root_path / "preflight_report.json"
        failure_path = root_path / "preflight_failure.json"
        if report_path.is_file() and failure_path.exists():
            raise MaterialPreflightValidationError(
                "preflight root contains conflicting success and failure terminals"
            )
        if report_path.is_file():
            report_artifact = _artifact(
                self.job_root,
                report_path,
                artifact_id="adopted-preflight-report",
                kind="material_preflight_report",
            )
            report = self.validate_preflight_for_approval(report_artifact)
            report_artifact = report_artifact.model_copy(
                update={"artifact_id": report.report_id}
            )
            shadow = _load_model(
                self.job_root,
                report.shadow_compile_receipt,
                MaterialShadowCompileReceipt,
            )
            preview = _load_model(
                self.job_root,
                report.neutral_preview_manifest,
                MaterialNeutralPreviewManifest,
            )
            resource = _load_model(
                self.job_root,
                report.resource_receipt,
                MaterialPreflightResourceReceipt,
            )
            return MaterialPromotionPreflightResult(
                report=report,
                report_artifact=report_artifact,
                failure=None,
                failure_artifact=None,
                framework_failure_report=None,
                framework_failure_report_artifact=None,
                shadow_receipt=shadow,
                shadow_receipt_artifact=report.shadow_compile_receipt,
                neutral_preview=preview,
                neutral_preview_artifact=report.neutral_preview_manifest,
                resource_receipt=resource,
                resource_receipt_artifact=report.resource_receipt,
            )
        if not failure_path.is_file():
            return None
        failure_artifact = _artifact(
            self.job_root,
            failure_path,
            artifact_id="adopted-preflight-failure",
            kind="material_preflight_failure",
        )
        failure = _load_model(
            self.job_root,
            failure_artifact,
            MaterialPromotionPreflightFailure,
        )
        failure_artifact = failure_artifact.model_copy(
            update={"artifact_id": failure.failure_id}
        )
        framework_path = resolve_contained_path(
            self.job_root,
            failure.framework_failure_report_path,
            must_exist=True,
        )
        framework_artifact = _artifact(
            self.job_root,
            framework_path,
            artifact_id="adopted-framework-failure",
            kind="material_framework_failure_report",
        )
        framework = _load_model(
            self.job_root,
            framework_artifact,
            MaterialFrameworkFailureReport,
        )
        framework_artifact = framework_artifact.model_copy(
            update={"artifact_id": framework.report_id}
        )
        shadow_path = root_path / "shadow_compile_receipt.json"
        resource_path = root_path / "preflight_resource_receipt.json"
        shadow_artifact = (
            _artifact(
                self.job_root,
                shadow_path,
                artifact_id="adopted-shadow-receipt",
                kind="material_shadow_compile_receipt",
            )
            if shadow_path.is_file()
            else None
        )
        resource_artifact = (
            _artifact(
                self.job_root,
                resource_path,
                artifact_id="adopted-resource-receipt",
                kind="material_preflight_resource_receipt",
            )
            if resource_path.is_file()
            else None
        )
        shadow = (
            _load_model(self.job_root, shadow_artifact, MaterialShadowCompileReceipt)
            if shadow_artifact is not None
            else None
        )
        resource = (
            _load_model(self.job_root, resource_artifact, MaterialPreflightResourceReceipt)
            if resource_artifact is not None
            else None
        )
        return MaterialPromotionPreflightResult(
            report=None,
            report_artifact=None,
            failure=failure,
            failure_artifact=failure_artifact,
            framework_failure_report=framework,
            framework_failure_report_artifact=framework_artifact,
            shadow_receipt=shadow,
            shadow_receipt_artifact=shadow_artifact,
            neutral_preview=None,
            neutral_preview_artifact=None,
            resource_receipt=resource,
            resource_receipt_artifact=resource_artifact,
        )

    def run_preflight(
        self,
        request: MaterialPromotionPreflightRequest,
        *,
        output_root: str | None = None,
        preview_size: int = 512,
        created_at: datetime | None = None,
    ) -> MaterialPromotionPreflightResult:
        """Publish a passed approval boundary or a canonical-write-free framework failure."""

        now = created_at or datetime.now(UTC)
        self._validate_failure_context(request)
        root_path = self._preflight_root(request)
        expected_output_root = root_path.relative_to(self.job_root).as_posix()
        if output_root is not None and output_root != expected_output_root:
            raise MaterialPreflightValidationError(
                f"output_root must equal the run-owned path {expected_output_root}"
            )
        os.makedirs(native_io_path(root_path), exist_ok=True)
        request_path = root_path / "preflight_request.json"
        request_artifact = _write_model(
            self.job_root,
            request_path,
            request,
            artifact_id=request.request_id,
            kind="material_preflight_request",
        )
        adopted = self._adopt_terminal_result(root_path)
        if adopted is not None:
            return adopted
        shadow_receipt: MaterialShadowCompileReceipt | None = None
        shadow_artifact: ExactArtifact | None = None
        preview: MaterialNeutralPreviewManifest | None = None
        preview_artifact: ExactArtifact | None = None
        resource: MaterialPreflightResourceReceipt | None = None
        resource_artifact: ExactArtifact | None = None
        resource_lock: tuple[Path, bytes] | None = None
        try:
            resource_lock = _acquire_resource_chain_lock(self.job_root, request)
            closure, closure_receipt, rebinding, snapshot, budget, checks = (
                _validate_request_dependencies(self.job_root, request)
            )
            resource_before = _resource_chain_head(self.job_root, request, budget)
            validate_preflight_budget(
                budget.model_copy(update={"consumed": resource_before}),
                required_blender_runs=SHADOW_BLENDER_RUN_COUNT,
            )
            canonical_before = _capture_canonical_state(self.job_root, snapshot)
            try:
                shadow_result = _run_material_shadow_compile(
                    self.job_root,
                    request=request,
                    request_artifact=request_artifact,
                    closure=closure,
                    closure_artifact=request.closure,
                    shadow_root_path=(root_path / "shadow_job").relative_to(
                        self.job_root
                    ).as_posix(),
                    preview_size=preview_size,
                    created_at=now,
                )
            finally:
                if _capture_canonical_state(self.job_root, snapshot) != canonical_before:
                    raise MaterialPreflightValidationError(
                        "canonical state changed during isolated material shadow compilation"
                    )
            shadow_receipt = shadow_result.receipt
            shadow_artifact = _write_model(
                self.job_root,
                root_path / "shadow_compile_receipt.json",
                shadow_receipt,
                artifact_id=shadow_receipt.receipt_id,
                kind="material_shadow_compile_receipt",
            )
            resource = _resource_receipt(
                request=request,
                closure=closure,
                budget=budget,
                before=resource_before,
                blender_runs=shadow_result.blender_runs_attempted,
                created_at=now,
            )
            resource_artifact = _write_model(
                self.job_root,
                root_path / "preflight_resource_receipt.json",
                resource,
                artifact_id=resource.receipt_id,
                kind="material_preflight_resource_receipt",
            )
            if shadow_receipt.status != "passed":
                message = "; ".join(item.message for item in shadow_receipt.issues)
                raise MaterialPreflightValidationError(
                    message or "material shadow compilation did not pass"
                )
            preview = build_neutral_preview_manifest(
                request=request,
                request_artifact=request_artifact,
                closure_artifact=request.closure,
                shadow_receipt_artifact=shadow_artifact,
                shadow_result=shadow_result,
                created_at=now,
            )
            preview_artifact = _write_model(
                self.job_root,
                root_path / "neutral_preview_manifest.json",
                preview,
                artifact_id=preview.manifest_id,
                kind="material_neutral_preview_manifest",
            )
            checks.extend(shadow_receipt.checks)
            report = MaterialPromotionPreflightReport(
                report_id=f"preflight-{request.request_id}",
                job_id=request.job_id,
                workflow_id=request.workflow_id,
                dispatch_id=request.dispatch_id,
                session_id=request.session_id,
                producer=_PRODUCER,
                producer_version=_PRODUCER_VERSION,
                created_at=now,
                request=request_artifact,
                closure=request.closure,
                closure_receipt=request.closure_receipt,
                graph_rebinding_receipt=request.graph_rebinding_receipt,
                shadow_compile_receipt=shadow_artifact,
                neutral_preview_manifest=preview_artifact,
                resource_receipt=resource_artifact,
                checks=checks,
                immutable_input_projection=closure.project_immutable_input_map(),
                planned_output_projection=closure.project_planned_output_map(),
            )
            report_artifact = _write_model(
                self.job_root,
                root_path / "preflight_report.json",
                report,
                artifact_id=report.report_id,
                kind="material_preflight_report",
            )
            validate_preflight_for_approval(
                report=report,
                closure_receipt=closure_receipt,
                rebinding_receipt=rebinding,
                shadow_receipt=shadow_receipt,
                neutral_preview=preview,
            )
            return MaterialPromotionPreflightResult(
                report=report,
                report_artifact=report_artifact,
                failure=None,
                failure_artifact=None,
                framework_failure_report=None,
                framework_failure_report_artifact=None,
                shadow_receipt=shadow_receipt,
                shadow_receipt_artifact=shadow_artifact,
                neutral_preview=preview,
                neutral_preview_artifact=preview_artifact,
                resource_receipt=resource,
                resource_receipt_artifact=resource_artifact,
            )
        except Exception as exc:
            issue = _failure_issue(exc)
            framework = _framework_failure_report(
                request=request,
                issue=issue,
                created_at=now,
                resource=resource,
            )
            framework_path = root_path / "framework_failure_report.json"
            framework_artifact = _write_model(
                self.job_root,
                framework_path,
                framework,
                artifact_id=framework.report_id,
                kind="material_framework_failure_report",
            )
            failure = MaterialPromotionPreflightFailure(
                failure_id=f"failure-{request.request_id}",
                job_id=request.job_id,
                workflow_id=request.workflow_id,
                dispatch_id=request.dispatch_id,
                session_id=request.session_id,
                producer=_PRODUCER,
                producer_version=_PRODUCER_VERSION,
                created_at=now,
                request=request_artifact,
                closure=request.closure,
                issues=[issue],
                framework_failure_report_path=framework_path.relative_to(
                    self.job_root
                ).as_posix(),
                recommendations=[
                    "Repair only host-owned framework dependencies and submit a new preflight."
                ],
            )
            failure_artifact = _write_model(
                self.job_root,
                root_path / "preflight_failure.json",
                failure,
                artifact_id=failure.failure_id,
                kind="material_preflight_failure",
            )
            return MaterialPromotionPreflightResult(
                report=None,
                report_artifact=None,
                failure=failure,
                failure_artifact=failure_artifact,
                framework_failure_report=framework,
                framework_failure_report_artifact=framework_artifact,
                shadow_receipt=shadow_receipt,
                shadow_receipt_artifact=shadow_artifact,
                neutral_preview=None,
                neutral_preview_artifact=None,
                resource_receipt=resource,
                resource_receipt_artifact=resource_artifact,
            )
        finally:
            _release_resource_chain_lock(resource_lock)

    def run_material_shadow_compile(
        self,
        request: MaterialPromotionPreflightRequest,
        *,
        preview_size: int = 512,
        created_at: datetime | None = None,
    ) -> MaterialPromotionPreflightResult:
        """Run the complete preflight; never expose a raw shadow-only approval bypass."""

        return self.run_preflight(
            request,
            preview_size=preview_size,
            created_at=created_at,
        )

    def publish_appearance_approval(
        self,
        *,
        report_artifact: ExactArtifact,
        approval: MaterialAppearanceApproval,
        explicit_user_decision_observed: bool,
    ) -> MaterialAppearanceApprovalPublication:
        """Publish one complete caller-authored user decision after exact current-state replay."""

        if explicit_user_decision_observed is not True:
            raise PermissionError(
                "appearance approval publication requires an explicit observed user decision"
            )
        if approval.approved_by != "user":
            raise PermissionError("appearance approval must be authored from a user decision")
        report = self.validate_preflight_for_approval(report_artifact)
        request = _load_model(
            self.job_root,
            report.request,
            MaterialPromotionPreflightRequest,
        )
        closure = _load_model(
            self.job_root,
            report.closure,
            MaterialDependencyClosure,
        )
        preview = _load_model(
            self.job_root,
            report.neutral_preview_manifest,
            MaterialNeutralPreviewManifest,
        )
        snapshot = _load_model(
            self.job_root,
            request.canonical_snapshot,
            MaterialCanonicalSnapshot,
        )
        expected_bindings = {
            "candidate_material_plan_sha256": request.candidate_material_plan.sha256,
            "rebound_material_graph_sha256": request.rebound_material_graph.sha256,
            "closure_sha256": closure.closure_sha256,
            "preflight_report_sha256": report_artifact.sha256,
            "neutral_preview_sha256": preview.preview_image.sha256,
            "canonical_scene_spec_sha256": snapshot.scene_spec.sha256,
            "canonical_blend_sha256": snapshot.blend.sha256,
            "uv_layout_fingerprint": request.uv_layout_fingerprint,
        }
        actual_bindings = {
            key: getattr(approval, key)
            for key in expected_bindings
        }
        if actual_bindings != expected_bindings:
            raise PermissionError(
                "caller-authored appearance approval differs from current exact preflight bindings"
            )
        if _binding_tuple(approval) != _binding_tuple(request):
            raise PermissionError("appearance approval targets another workflow session")
        approval_path = resolve_contained_path(
            self.job_root,
            (
                f"production/material_closure/{request.session_id}/"
                f"appearance_approvals/{approval.approval_id}.json"
            ),
            must_exist=False,
        )
        approval_artifact = _write_model(
            self.job_root,
            approval_path,
            approval,
            artifact_id=approval.approval_id,
            kind="material_appearance_approval",
        )
        return MaterialAppearanceApprovalPublication(
            approval=approval,
            approval_artifact=approval_artifact,
            preflight_report=report,
        )

    def validate_published_preflight(
        self,
        report_artifact: ExactArtifact,
        *,
        require_current_canonical: bool = False,
    ) -> MaterialPromotionPreflightReport:
        """Replay immutable evidence without treating expected canonical promotion as tampering."""

        report = _load_model(
            self.job_root,
            report_artifact,
            MaterialPromotionPreflightReport,
        )
        request = _load_model(
            self.job_root,
            report.request,
            MaterialPromotionPreflightRequest,
        )
        closure, closure_receipt, rebinding, _snapshot, _budget, _checks = (
            _validate_request_dependencies(
                self.job_root,
                request,
                require_current_canonical=require_current_canonical,
            )
        )
        shadow = _load_model(
            self.job_root,
            report.shadow_compile_receipt,
            MaterialShadowCompileReceipt,
        )
        preview = _load_model(
            self.job_root,
            report.neutral_preview_manifest,
            MaterialNeutralPreviewManifest,
        )
        resource = _load_model(
            self.job_root,
            report.resource_receipt,
            MaterialPreflightResourceReceipt,
        )
        for output in shadow.outputs:
            validate_exact_artifact(self.job_root, output)
        validate_exact_artifact(self.job_root, preview.preview_image)
        if (
            report.immutable_input_projection != closure.project_immutable_input_map()
            or report.planned_output_projection != closure.project_planned_output_map()
            or resource.closure_sha256 != closure.closure_sha256
        ):
            raise MaterialPreflightValidationError("published preflight projections changed")
        validate_preflight_for_approval(
            report=report,
            closure_receipt=closure_receipt,
            rebinding_receipt=rebinding,
            shadow_receipt=shadow,
            neutral_preview=preview,
        )
        return report

    def validate_preflight_for_approval(
        self,
        report_artifact: ExactArtifact,
    ) -> MaterialPromotionPreflightReport:
        """Replay a preflight with current canonical hashes before requesting approval."""

        return self.validate_published_preflight(
            report_artifact,
            require_current_canonical=True,
        )


def material_shadow_compile(
    job_root: Path,
    request: MaterialPromotionPreflightRequest,
    *,
    preview_size: int = 512,
    created_at: datetime | None = None,
) -> MaterialPromotionPreflightResult:
    """Run the named shadow facade as a complete preflight, never a raw Blender bypass."""

    return MaterialClosureService(job_root).run_material_shadow_compile(
        request,
        preview_size=preview_size,
        created_at=created_at,
    )


def publish_material_appearance_approval(
    job_root: Path,
    *,
    report_artifact: ExactArtifact,
    approval: MaterialAppearanceApproval,
    explicit_user_decision_observed: bool,
) -> MaterialAppearanceApprovalPublication:
    """Publish an immutable caller-authored decision through the strict service facade."""

    return MaterialClosureService(job_root).publish_appearance_approval(
        report_artifact=report_artifact,
        approval=approval,
        explicit_user_decision_observed=explicit_user_decision_observed,
    )


__all__ = [
    "MaterialAppearanceApprovalPublication",
    "MaterialClosureService",
    "MaterialPromotionPreflightResult",
    "material_shadow_compile",
    "publish_material_appearance_approval",
]
