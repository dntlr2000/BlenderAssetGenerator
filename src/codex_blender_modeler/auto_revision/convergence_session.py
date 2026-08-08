"""Bounded, exact-hash V0.6 visual-convergence sessions for standard jobs."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from ..architecture import list_interior_objects
from ..blender_artifacts import write_json_atomic
from ..build_provenance import canonical_json_sha256, collect_build_provenance
from ..constraints.models import ConstraintResult
from ..models import SceneSpec
from ..orchestration.locks import workflow_write_lock
from ..orchestration.models import WorkflowAttempt, WorkflowPlan, WorkflowStepCompletion
from ..qa.hashing import canonical_model_sha256
from ..qa.models import RenderPassManifest, VisualQAReport, VisualQARequest
from ..qa.multiview_sanity import (
    plan_job_assembly_multiview_sanity,
    run_job_assembly_multiview_sanity,
)
from ..qa.structural_regression import (
    AssemblySanityTerminalEvidence,
    StructuralRegressionReport,
    compare_assembly_sanity_terminals,
    terminal_evidence_from_run_result,
    validate_terminal_evidence,
)
from ..revision import load_revision_plan
from ..workspace import (
    current_job_write_lock_owner,
    job_dir,
    replace_scene_spec_if_current,
    sha256_file,
    validate_job_id,
)
from .convergence import (
    _authored_spatial_multiview_required,
    compare_constraint_results,
    evaluate_convergence,
)
from .convergence_policy import (
    ConvergenceCandidateSelection,
    select_convergence_candidates,
    validate_convergence_activation,
    validate_iteration_receipt_chain,
)
from .convergence_reporting import generate_visual_convergence_pdf_report
from .convergence_session_models import (
    ConvergencePathLimit,
    ConvergenceTerminationReason,
    HashBoundConvergenceArtifact,
    VisualConvergenceApproval,
    VisualConvergenceCancellation,
    VisualConvergenceHostSafetyEnvelope,
    VisualConvergenceIteration,
    VisualConvergenceIterationAuthorization,
    VisualConvergencePlan,
    VisualConvergenceReport,
    VisualConvergenceReportManifest,
    convergence_manual_review_required,
)
from .guard import apply_hash_bound_revision, compile_revision_plan
from .models import RevisionCandidates
from .service import (
    _baseline_constraint_state,
    _input_hashes,
    _load_candidates,
    _require_input_hashes,
    _restore_latest,
    _rollback_job,
    _run_job_pipeline,
    _run_post_visual_qa,
    _semantic_change_sets,
    _snapshot_latest,
    _validate_render_selection,
)

_SESSION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_QA_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_TERMINAL_REPORT = "convergence_report.json"
_CANCELLATION_RECEIPT = "cancellation_receipt.json"
_INITIAL_SCENE_SNAPSHOT = "initial_scene_spec.json"
_INITIAL_BUILD_PROVENANCE = "initial_build_provenance.json"
_FINAL_BUILD_PROVENANCE = "final_build_provenance.json"
_INITIAL_CONSTRAINTS_SNAPSHOT = "initial_constraints.json"
_HOST_SAFETY_ENVELOPE = "host_safety_envelope.json"
_ITERATION_STAGING_DIR = "staging"
_INTERRUPTED_ATTEMPTS_DIR = "interrupted_attempts"
_ITERATION_ATTEMPT = "attempt.json"
_ITERATION_PREPARED = "prepared.json"
_STRUCTURAL_COMPARISON = "structural_regression.json"
_LATEST_POINTER_SNAPSHOT = "latest_pointer.before.json"
_RECOVERY_RECEIPT = "recovery_receipt.json"
_TERMINAL_DERIVED_ARTIFACTS = (
    _CANCELLATION_RECEIPT,
    "final_scene_spec.json",
    _FINAL_BUILD_PROVENANCE,
    "convergence_report.pdf",
    "convergence_report.manifest.json",
)


def _utc_now() -> str:
    """Return one timezone-aware UTC timestamp for immutable session evidence."""

    return datetime.now(UTC).isoformat()


def _structural_multiview_policy(
    job_id: str,
) -> Literal["not_applicable", "spatial_v1_required"]:
    """Select exact five-view non-regression only for authored spatial-v1 assets."""

    return (
        "spatial_v1_required"
        if _authored_spatial_multiview_required(job_id)
        else "not_applicable"
    )


def _capture_convergence_structural_terminal(
    job_id: str,
    root: Path,
    *,
    session_id: str,
    phase: str,
    render_engine: str,
    render_device: str,
) -> AssemblySanityTerminalEvidence:
    """Create and validate one immutable five-view convergence terminal."""

    session_digest = hashlib.sha256(session_id.encode()).hexdigest()[:10]
    run_id = f"conv-{session_digest}-{phase}-{uuid4().hex[:8]}"
    planned = plan_job_assembly_multiview_sanity(job_id, run_id=run_id)
    rendered = run_job_assembly_multiview_sanity(
        job_id,
        run_id,
        plan_sha256=str(planned["plan_sha256"]),
        render_engine=render_engine,
        render_device=render_device,
    )
    evidence = terminal_evidence_from_run_result(root, rendered)
    validate_terminal_evidence(root, evidence, expected_job_id=job_id)
    return evidence


def _structural_terminal_artifacts(
    root: Path,
    evidence: AssemblySanityTerminalEvidence,
    *,
    expected_job_id: str,
    expected_scene_spec_sha256: str,
) -> list[HashBoundConvergenceArtifact]:
    """Validate and flatten one exact five-view terminal into hash-bound artifacts."""

    plan, _manifest, _report = validate_terminal_evidence(
        root,
        evidence,
        expected_job_id=expected_job_id,
    )
    if plan.scene_spec_sha256 != expected_scene_spec_sha256:
        raise ValueError(
            "five-view structural terminal does not bind the expected SceneSpec"
        )
    records = (
        (evidence.plan_path, evidence.plan_sha256, "five-view plan"),
        (
            evidence.render_manifest_path,
            evidence.render_manifest_sha256,
            "five-view render manifest",
        ),
        (evidence.report_path, evidence.report_sha256, "five-view report"),
    )
    return [
        _bind_existing_artifact(
            root,
            root / Path(*relative_path.split("/")),
            expected_sha256,
            label=label,
        )
        for relative_path, expected_sha256, label in records
    ]


def _current_structural_evidence(
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> AssemblySanityTerminalEvidence | None:
    """Recover the five-view baseline owned by the accepted receipt chain."""

    current = plan.initial_structural_evidence
    for receipt, _receipt_sha256, _receipt_path in receipts:
        if receipt.status == "accepted":
            if (
                plan.structural_multiview_policy == "spatial_v1_required"
                and receipt.result_structural_evidence is None
            ):
                raise ValueError(
                    "accepted spatial convergence receipt lacks result five-view evidence"
                )
            if receipt.result_structural_evidence is not None:
                current = receipt.result_structural_evidence
    return current


def _canonical_sha256(value: Any) -> str:
    """Hash one JSON-compatible value with stable serialization."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_artifact_sha256(payload: dict[str, Any]) -> str:
    """Predict the exact SHA-256 written by the repository JSON artifact writer."""

    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    # Path.write_text uses platform newline translation, so mirror the exact bytes
    # emitted by write_json_atomic on both Windows and POSIX hosts.
    if os.linesep != "\n":
        serialized = serialized.replace("\n", os.linesep)
    encoded = serialized.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_build_provenance_payload(
    payload: dict[str, Any],
    *,
    expected_fingerprint: str,
) -> None:
    """Reject build provenance whose embedded or recomputed fingerprint changed."""

    declared = payload.get("fingerprint")
    unsigned = dict(payload)
    unsigned.pop("fingerprint", None)
    recomputed = canonical_json_sha256(unsigned)
    if declared != recomputed or recomputed != expected_fingerprint:
        raise ValueError(
            "visual convergence build provenance fingerprint is stale or tampered"
        )


def _current_build_provenance(root: Path, job_id: str) -> dict[str, Any]:
    """Collect and internally verify the current canonical Blender-build inputs."""

    payload = collect_build_provenance(root, job_id)
    fingerprint = str(payload.get("fingerprint", ""))
    _validate_build_provenance_payload(
        payload,
        expected_fingerprint=fingerprint,
    )
    return payload


def _constraint_contract_binding(root: Path) -> tuple[bool, str | None]:
    """Return the exact measured-constraint presence and hash for one job."""

    path = root / "constraints" / "constraints.json"
    return (path.is_file(), sha256_file(path) if path.is_file() else None)


def _require_constraint_contract(
    root: Path,
    plan: VisualConvergencePlan,
) -> None:
    """Reject active-session constraint replacement, deletion, or unexpected creation."""

    if plan.initial_constraints_present is None:
        return
    present, digest = _constraint_contract_binding(root)
    if (
        present != plan.initial_constraints_present
        or digest != plan.initial_constraints_sha256
    ):
        raise ValueError(
            "measured constraint contract changed after convergence planning"
        )


def _executable_plan_binding_gaps(plan: VisualConvergencePlan) -> list[str]:
    """List exact evidence bindings missing from one executable session plan."""

    required = {
        "initial_candidates_sha256": plan.initial_candidates_sha256,
        "initial_build_fingerprint": plan.initial_build_fingerprint,
        "initial_build_provenance_sha256": plan.initial_build_provenance_sha256,
        "host_safety_envelope_sha256": plan.host_safety_envelope_sha256,
        "initial_constraints_present": plan.initial_constraints_present,
    }
    missing = sorted(label for label, value in required.items() if value is None)
    if not plan.initial_input_hashes:
        missing.append("initial_input_hashes")
    return sorted(missing)


def _require_executable_plan_bindings(plan: VisualConvergencePlan) -> None:
    """Keep historical partial plans inspectable but prohibit their execution."""

    missing = _executable_plan_binding_gaps(plan)
    if missing:
        raise ValueError(
            "legacy convergence plans are status-only because they lack exact "
            f"execution bindings: {missing}"
        )


def _validate_constraint_evidence_payload(payload: dict[str, Any]) -> None:
    """Validate one immutable before/after constraint result snapshot."""

    failures = payload.get("failures")
    results = payload.get("results")
    if not isinstance(failures, int) or isinstance(failures, bool) or failures < 0:
        raise ValueError("constraint evidence failures must be a non-negative integer")
    if not isinstance(results, list):
        raise ValueError("constraint evidence results must be an array")
    validated = [ConstraintResult.model_validate(item) for item in results]
    expected_failures = sum(
        result.status in {"failed", "missing"} for result in validated
    )
    if failures != expected_failures:
        raise ValueError(
            "constraint evidence failure count does not match failed/missing results"
        )
    # Reuse duplicate-ID detection and normalized result semantics.
    compare_constraint_results(results, results)


def _write_constraint_evidence(path: Path, payload: dict[str, Any]) -> str:
    """Persist one validated immutable constraint snapshot and return its file hash."""

    _validate_constraint_evidence_payload(payload)
    _write_immutable_json(path, payload)
    return sha256_file(path)


def _load_constraint_evidence(
    path: Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    """Load one exact immutable constraint snapshot for acceptance revalidation."""

    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ValueError(f"convergence constraint evidence changed: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("convergence constraint evidence must be a JSON object")
    _validate_constraint_evidence_payload(payload)
    return payload


def _validate_result_build_transition(
    source: dict[str, Any],
    result: dict[str, Any],
    *,
    expected_source_scene_spec_sha256: str,
    expected_result_scene_spec_sha256: str,
) -> None:
    """Allow only the approved SceneSpec hash to change between canonical builds."""

    if source.get("scene_spec_sha256") != expected_source_scene_spec_sha256:
        raise ValueError("source build provenance does not bind the iteration base")
    if result.get("scene_spec_sha256") != expected_result_scene_spec_sha256:
        raise ValueError("result build provenance does not bind the promoted SceneSpec")
    source_contracts = dict(source)
    result_contracts = dict(result)
    for payload in (source_contracts, result_contracts):
        payload.pop("fingerprint", None)
        payload.pop("scene_spec_sha256", None)
    if source_contracts != result_contracts:
        raise ValueError(
            "geometry, material, shader, texture, camera, interior, or reference-scope "
            "build inputs changed outside the approved convergence SceneSpec edit"
        )


def _validate_initial_session_snapshots(
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
) -> list[HashBoundConvergenceArtifact]:
    """Verify immutable initial SceneSpec, build, and optional constraint snapshots."""

    if (
        plan.initial_build_fingerprint is None
        or plan.initial_build_provenance_sha256 is None
        or plan.initial_candidates_sha256 is None
    ):
        return []
    scene_artifact = _bind_existing_artifact(
        root,
        session_root / _INITIAL_SCENE_SNAPSHOT,
        plan.initial_scene_spec_sha256,
        label="initial convergence SceneSpec snapshot",
    )
    build_artifact = _bind_build_provenance_snapshot(
        root,
        session_root / _INITIAL_BUILD_PROVENANCE,
        expected_file_sha256=plan.initial_build_provenance_sha256,
        expected_fingerprint=plan.initial_build_fingerprint,
        expected_scene_spec_sha256=plan.initial_scene_spec_sha256,
        expected_camera_fingerprint=plan.camera_fingerprint,
    )
    artifacts = [scene_artifact, build_artifact]
    if plan.host_safety_envelope_sha256 is not None:
        artifacts.append(
            _bind_existing_artifact(
                root,
                session_root / _HOST_SAFETY_ENVELOPE,
                plan.host_safety_envelope_sha256,
                label="visual convergence host safety envelope",
            )
        )
    constraints_path = session_root / _INITIAL_CONSTRAINTS_SNAPSHOT
    if plan.initial_constraints_present:
        if plan.initial_constraints_sha256 is None:
            raise ValueError("initial convergence constraint hash is missing")
        artifacts.append(
            _bind_existing_artifact(
                root,
                constraints_path,
                plan.initial_constraints_sha256,
                label="initial convergence constraint snapshot",
            )
        )
    elif constraints_path.exists():
        raise ValueError(
            "unexpected initial convergence constraint snapshot exists for an absent contract"
        )
    if plan.structural_multiview_policy == "spatial_v1_required":
        if plan.initial_structural_evidence is None:
            raise ValueError("spatial convergence plan lacks initial five-view evidence")
        artifacts.extend(
            _structural_terminal_artifacts(
                root,
                plan.initial_structural_evidence,
                expected_job_id=plan.job_id,
                expected_scene_spec_sha256=plan.initial_scene_spec_sha256,
            )
        )
    elif plan.initial_structural_evidence is not None:
        raise ValueError("non-spatial convergence plan carries five-view evidence")
    return artifacts


def _input_fingerprint(root: Path) -> str:
    """Bind a session to the complete immutable input-file hash map."""

    return _canonical_sha256(_input_hashes(root))


def _validate_plan_input_binding(plan: VisualConvergencePlan) -> None:
    """Verify that a new-style exact input manifest matches its aggregate fingerprint."""

    if (
        plan.initial_input_hashes
        and _canonical_sha256(plan.initial_input_hashes) != plan.input_fingerprint
    ):
        raise ValueError(
            "visual convergence initial_input_hashes do not match input_fingerprint"
        )


def _validate_terminal_input_manifest(
    root: Path,
    plan: VisualConvergencePlan,
) -> list[str]:
    """Verify original input files after terminal completion while allowing later additions."""

    _validate_plan_input_binding(plan)
    if not plan.initial_input_hashes:
        if _input_fingerprint(root) != plan.input_fingerprint:
            return [
                "historical_input_set_unverifiable: this legacy convergence plan has no "
                "exact initial_input_hashes map, so later input additions cannot be "
                "distinguished from changes to original evidence"
            ]
        return []
    input_root = root / "input"
    for relative_path, expected_sha256 in sorted(plan.initial_input_hashes.items()):
        candidate = input_root / Path(*relative_path.split("/"))
        if not candidate.is_file():
            raise ValueError(
                f"original convergence input is missing: {relative_path}"
            )
        if sha256_file(candidate) != expected_sha256:
            raise ValueError(
                f"original convergence input changed: {relative_path}"
            )
    return []


def _new_session_id() -> str:
    """Create one portable collision-resistant convergence session identifier."""

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ").lower()
    return f"conv-{stamp}-{uuid4().hex[:8]}"


def _validate_session_id(session_id: str) -> str:
    """Reject convergence session IDs that could escape the job-owned directory."""

    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(
            "session_id must match [a-z0-9][a-z0-9._-]{0,95}: "
            f"{session_id!r}"
        )
    return session_id


def _session_paths(job_id: str, session_id: str) -> tuple[Path, Path]:
    """Resolve one job and contained convergence directory without creating it."""

    validate_job_id(job_id)
    selected = _validate_session_id(session_id)
    root = job_dir(job_id)
    if not (root / "job.json").is_file():
        raise FileNotFoundError(f"Job does not exist: {job_id}")
    return root, root / "qa" / "convergence" / selected


def _write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    """Write one JSON artifact exactly once and refuse replacement."""

    if path.exists():
        raise FileExistsError(f"Immutable convergence artifact already exists: {path}")
    write_json_atomic(path, payload)


def _write_immutable_copy(source: Path, destination: Path) -> str:
    """Preserve one exact workflow-owned file snapshot and return its SHA-256."""

    if destination.exists():
        raise FileExistsError(
            f"Immutable convergence artifact already exists: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    return sha256_file(destination)


def _bind_build_provenance_snapshot(
    root: Path,
    path: Path,
    *,
    expected_file_sha256: str,
    expected_fingerprint: str,
    expected_scene_spec_sha256: str,
    expected_camera_fingerprint: str,
) -> HashBoundConvergenceArtifact:
    """Validate one exact provenance snapshot and return its job-relative hash binding."""

    if not path.is_file() or sha256_file(path) != expected_file_sha256:
        raise ValueError(f"visual convergence build provenance snapshot changed: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("visual convergence build provenance snapshot must be an object")
    _validate_build_provenance_payload(
        payload,
        expected_fingerprint=expected_fingerprint,
    )
    if (
        payload.get("scene_spec_sha256") != expected_scene_spec_sha256
        or payload.get("camera_fingerprint") != expected_camera_fingerprint
    ):
        raise ValueError(
            "visual convergence build provenance SceneSpec or camera binding changed"
        )
    return _bind_existing_artifact(
        root,
        path,
        expected_file_sha256,
        label="visual convergence build provenance snapshot",
    )


def _load_plan(path: Path) -> VisualConvergencePlan:
    """Load one strict bounded-convergence plan."""

    return VisualConvergencePlan.model_validate_json(path.read_text(encoding="utf-8"))


def _load_approval(path: Path) -> VisualConvergenceApproval:
    """Load one strict immutable convergence approval."""

    return VisualConvergenceApproval.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def _load_authoritative_activation(
    session_root: Path,
    *,
    job_id: str,
    session_id: str,
    expected_plan_sha256: str | None = None,
    expected_approval_sha256: str | None = None,
) -> tuple[
    VisualConvergencePlan,
    VisualConvergenceApproval,
    str,
    str,
]:
    """Load and verify the exact plan/approval bytes at an authority boundary."""

    plan_path = session_root / "plan.json"
    approval_path = session_root / "approval.json"
    for required in (plan_path, approval_path):
        if not required.is_file():
            raise FileNotFoundError(
                f"Convergence activation artifact is missing: {required}"
            )
    plan_bytes = plan_path.read_bytes()
    approval_bytes = approval_path.read_bytes()
    plan_sha256 = hashlib.sha256(plan_bytes).hexdigest()
    approval_sha256 = hashlib.sha256(approval_bytes).hexdigest()
    if (
        expected_plan_sha256 is not None
        and plan_sha256 != expected_plan_sha256
    ):
        raise ValueError(
            "visual convergence plan changed after authority was established"
        )
    if (
        expected_approval_sha256 is not None
        and approval_sha256 != expected_approval_sha256
    ):
        raise ValueError(
            "visual convergence approval changed after authority was established"
        )
    plan = VisualConvergencePlan.model_validate_json(plan_bytes)
    approval = VisualConvergenceApproval.model_validate_json(approval_bytes)
    if (
        plan.job_id != job_id
        or plan.session_id != session_id
        or approval.job_id != job_id
        or approval.session_id != session_id
    ):
        raise ValueError(
            "visual convergence activation identity does not match the requested session"
        )
    _require_executable_plan_bindings(plan)
    validate_convergence_activation(plan, approval, plan_sha256=plan_sha256)
    return plan, approval, plan_sha256, approval_sha256


def _load_cancellation(path: Path) -> VisualConvergenceCancellation:
    """Load one strict approval-consuming cancellation receipt."""

    return VisualConvergenceCancellation.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def _load_selection(path: Path) -> ConvergenceCandidateSelection:
    """Load one strict workflow-owned candidate selection artifact."""

    return ConvergenceCandidateSelection.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def _load_iteration_authorization(
    path: Path,
) -> VisualConvergenceIterationAuthorization:
    """Load one strict host-issued iteration authorization artifact."""

    return VisualConvergenceIterationAuthorization.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def _load_report(path: Path) -> VisualQAReport:
    """Load one exact machine-readable V0.6 visual QA report."""

    return VisualQAReport.model_validate_json(path.read_text(encoding="utf-8"))


def _qa_evidence(
    root: Path,
    job_id: str,
    run_id: str,
    *,
    require_current_spec: bool,
) -> tuple[Path, Path, VisualQAReport, RevisionCandidates]:
    """Load one exact QA run and verify its report/candidate hash bindings."""

    if not _QA_RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"QA run_id is not portable for convergence: {run_id!r}")
    run_dir = root / "qa" / "runs" / run_id
    report_path = run_dir / "visual_qa_report.json"
    candidates_path = run_dir / "revision_candidates.json"
    for required in (report_path, candidates_path):
        if not required.is_file():
            raise FileNotFoundError(f"Convergence QA evidence is missing: {required}")
    report = _load_report(report_path)
    candidates = _load_candidates(candidates_path, job_id)
    if report.job_id != job_id or report.run_id != run_id:
        raise ValueError("QA report identity does not match the requested convergence run")
    if candidates.source_report_sha256 != sha256_file(report_path):
        raise ValueError("QA candidates are stale relative to their source report")
    if candidates.camera_fingerprint != report.camera_fingerprint:
        raise ValueError("QA report and candidates use different camera fingerprints")
    if require_current_spec:
        scene_spec_path = root / "analysis" / "scene_spec.json"
        if candidates.base_spec_sha256 != sha256_file(scene_spec_path):
            raise ValueError("initial QA candidates are stale relative to SceneSpec")
    return report_path, candidates_path, report, candidates


def _default_path_limits(spec: SceneSpec) -> list[ConvergencePathLimit]:
    """Derive conservative per-iteration edit limits from nominal scene scale."""

    scene_scale = max(float(value) for value in spec.nominal_scene_size)
    position_delta = max(scene_scale * 0.05, 0.01)
    size_delta = max(scene_scale * 0.05, 0.01)
    detail_delta = max(scene_scale * 0.01, 0.001)
    return [
        ConvergencePathLimit(
            path_family="transform.location",
            allowed_operations=["set", "add"],
            max_absolute_delta=position_delta,
        ),
        ConvergencePathLimit(
            path_family="transform.scale",
            allowed_operations=["set", "multiply"],
            max_absolute_delta=0.25,
            max_relative_delta=0.1,
        ),
        ConvergencePathLimit(
            path_family="geometry.dimensions",
            allowed_operations=["set", "multiply"],
            max_absolute_delta=size_delta,
            max_relative_delta=0.1,
        ),
        ConvergencePathLimit(
            path_family="geometry.depth",
            allowed_operations=["set", "multiply"],
            max_absolute_delta=size_delta,
            max_relative_delta=0.1,
        ),
        ConvergencePathLimit(
            path_family="geometry.size",
            allowed_operations=["set", "multiply"],
            max_absolute_delta=size_delta,
            max_relative_delta=0.1,
        ),
        ConvergencePathLimit(
            path_family="geometry.bevel_depth",
            allowed_operations=["set", "multiply"],
            max_absolute_delta=detail_delta,
            max_relative_delta=0.25,
        ),
        ConvergencePathLimit(
            path_family="geometry.skirt_depth",
            allowed_operations=["set", "multiply"],
            max_absolute_delta=detail_delta,
            max_relative_delta=0.25,
        ),
    ]


def _bounded_path_limits(
    spec: SceneSpec,
    requested: list[ConvergencePathLimit] | None,
) -> list[ConvergencePathLimit]:
    """Normalize caller limits and reject any rule broader than the host defaults."""

    defaults = {
        item.path_family: item for item in _default_path_limits(spec)
    }
    selected = requested if requested is not None else list(defaults.values())
    if not selected:
        raise ValueError("visual convergence requires at least one bounded path rule")
    normalized = sorted(selected, key=lambda item: item.path_family)
    for limit in normalized:
        host = defaults.get(limit.path_family)
        if host is None:
            raise ValueError(
                f"convergence path family is not host-authorized: {limit.path_family}"
            )
        if not set(limit.allowed_operations).issubset(host.allowed_operations):
            raise ValueError(
                f"convergence operations exceed the host rule: {limit.path_family}"
            )
        for label in ("max_absolute_delta", "max_relative_delta"):
            requested_value = getattr(limit, label)
            host_value = getattr(host, label)
            if host_value is not None and (
                requested_value is None or requested_value > host_value + 1e-12
            ):
                raise ValueError(
                    f"{limit.path_family}.{label} exceeds the host safety envelope"
                )
    return normalized


def _object_sets(
    spec: SceneSpec,
    requested_target_ids: list[str] | None,
) -> tuple[list[str], list[str], list[str]]:
    """Resolve editable IDs while always locking InteriorScope-classified objects."""

    object_ids = {item.id for item in spec.objects}
    material_ids = {item.id for item in spec.materials}
    interior_ids = {item.id for item in list_interior_objects(spec)}
    eligible_ids = object_ids - interior_ids
    requested = set(requested_target_ids) if requested_target_ids is not None else eligible_ids
    forbidden_interiors = sorted(requested.intersection(interior_ids))
    if forbidden_interiors:
        raise ValueError(
            "visual convergence never edits InteriorScope-classified objects; "
            f"interior={forbidden_interiors}"
        )
    allowed = sorted(requested)
    missing = sorted(set(allowed) - object_ids)
    if missing:
        raise ValueError(
            "visual convergence targets must be existing object IDs; "
            f"unknown={missing}"
        )
    if not allowed:
        raise ValueError(
            "visual convergence requires at least one non-interior allowed object ID"
        )
    locked = sorted((object_ids - set(allowed)) | material_ids | interior_ids)
    custom_mesh = sorted(
        item.id for item in spec.objects if item.geometry.kind == "custom_mesh"
    )
    return allowed, locked, custom_mesh


def _host_safety_envelope_payload(
    *,
    session_id: str,
    job_id: str,
    spec: SceneSpec,
    report: VisualQAReport,
    candidates: RevisionCandidates,
    initial_scene_spec_sha256: str,
    initial_qa_report_sha256: str,
    initial_candidates_sha256: str,
    target_direct_score: float,
    target_silhouette_iou: float,
    minimum_iteration_gain: float,
    minimum_candidate_confidence: float,
    max_iterations: int,
    max_candidate_groups_per_iteration: int,
    max_candidates_per_iteration: int,
    max_changed_ids_per_iteration: int,
    allowed_target_ids: list[str],
    path_limits: list[ConvergencePathLimit],
    structural_multiview_policy: Literal[
        "not_applicable", "spatial_v1_required"
    ],
    initial_structural_evidence: AssemblySanityTerminalEvidence | None,
) -> dict[str, Any]:
    """Derive the exact immutable automatic-edit boundary from initial evidence."""

    allowed, locked, custom_mesh = _object_sets(spec, allowed_target_ids)
    bounded_limits = _bounded_path_limits(spec, path_limits)
    envelope = VisualConvergenceHostSafetyEnvelope(
        session_id=session_id,
        job_id=job_id,
        initial_scene_spec_sha256=initial_scene_spec_sha256,
        initial_qa_report_sha256=initial_qa_report_sha256,
        initial_candidates_sha256=initial_candidates_sha256,
        camera_fingerprint=report.camera_fingerprint,
        scoring_version=report.direct_metrics.scoring_version,
        initial_direct_score=report.direct_metrics.overall_direct_score,
        initial_silhouette_iou=report.direct_metrics.silhouette_iou,
        target_direct_score=target_direct_score,
        target_silhouette_iou=target_silhouette_iou,
        minimum_iteration_gain=minimum_iteration_gain,
        minimum_candidate_confidence=minimum_candidate_confidence,
        max_iterations=max_iterations,
        max_candidate_groups_per_iteration=max_candidate_groups_per_iteration,
        max_candidates_per_iteration=max_candidates_per_iteration,
        max_changed_ids_per_iteration=max_changed_ids_per_iteration,
        allowed_target_ids=allowed,
        locked_target_ids=locked,
        custom_mesh_target_ids=custom_mesh,
        interior_target_ids=sorted(
            item.id for item in list_interior_objects(spec)
        ),
        manual_candidate_ids=sorted(
            item.id
            for item in candidates.candidates
            if item.applicability == "manual_required"
        ),
        path_limits=bounded_limits,
        allow_material_edits=False,
        camera_locked=True,
        generated_target_policy="advisory_only",
        constraint_regression_policy="forbid",
        structural_multiview_policy=structural_multiview_policy,
        initial_structural_evidence=initial_structural_evidence,
    )
    return envelope.model_dump(mode="json")


def _require_host_safety_envelope(
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
) -> None:
    """Re-derive and compare every host safety field before approval or execution."""

    expected_hash = plan.host_safety_envelope_sha256
    if expected_hash is None:
        raise ValueError("legacy convergence plan has no executable host safety envelope")
    envelope_path = session_root / _HOST_SAFETY_ENVELOPE
    if not envelope_path.is_file() or sha256_file(envelope_path) != expected_hash:
        raise ValueError("visual convergence host safety envelope is stale or tampered")
    try:
        envelope = VisualConvergenceHostSafetyEnvelope.model_validate_json(
            envelope_path.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        raise ValueError(
            "invalid visual convergence host safety envelope"
        ) from exc
    raw = envelope.model_dump(mode="json")
    snapshot_path = session_root / _INITIAL_SCENE_SNAPSHOT
    spec = SceneSpec.model_validate_json(snapshot_path.read_text(encoding="utf-8"))
    report_path, candidates_path, report, candidates = _qa_evidence(
        root,
        plan.job_id,
        plan.initial_qa_run_id,
        require_current_spec=False,
    )
    if sha256_file(report_path) != plan.initial_qa_report_sha256:
        raise ValueError(
            "initial QA report changed before host policy re-derivation"
        )
    if (
        plan.initial_candidates_sha256 is None
        or sha256_file(candidates_path) != plan.initial_candidates_sha256
    ):
        raise ValueError(
            "initial QA candidates changed before host policy re-derivation"
        )
    limits = list(envelope.path_limits)
    allowed_ids = list(envelope.allowed_target_ids)
    recomputed = _host_safety_envelope_payload(
        session_id=plan.session_id,
        job_id=plan.job_id,
        spec=spec,
        report=report,
        candidates=candidates,
        initial_scene_spec_sha256=plan.initial_scene_spec_sha256,
        initial_qa_report_sha256=plan.initial_qa_report_sha256,
        initial_candidates_sha256=plan.initial_candidates_sha256,
        target_direct_score=float(raw["target_direct_score"]),
        target_silhouette_iou=float(raw["target_silhouette_iou"]),
        minimum_iteration_gain=float(raw["minimum_iteration_gain"]),
        minimum_candidate_confidence=float(raw["minimum_candidate_confidence"]),
        max_iterations=int(raw["max_iterations"]),
        max_candidate_groups_per_iteration=int(
            raw["max_candidate_groups_per_iteration"]
        ),
        max_candidates_per_iteration=int(raw["max_candidates_per_iteration"]),
        max_changed_ids_per_iteration=int(raw["max_changed_ids_per_iteration"]),
        allowed_target_ids=allowed_ids,
        path_limits=limits,
        structural_multiview_policy=plan.structural_multiview_policy,
        initial_structural_evidence=plan.initial_structural_evidence,
    )
    if raw != recomputed:
        raise ValueError(
            "visual convergence host safety envelope no longer matches initial evidence"
        )
    plan_safety = {
        key: getattr(plan, key)
        for key in (
            "target_direct_score",
            "target_silhouette_iou",
            "minimum_iteration_gain",
            "minimum_candidate_confidence",
            "max_iterations",
            "max_candidate_groups_per_iteration",
            "max_candidates_per_iteration",
            "max_changed_ids_per_iteration",
            "allowed_target_ids",
            "locked_target_ids",
            "custom_mesh_target_ids",
            "allow_material_edits",
            "camera_locked",
            "generated_target_policy",
            "constraint_regression_policy",
            "structural_multiview_policy",
            "initial_structural_evidence",
        )
    }
    plan_safety["path_limits"] = [
        item.model_dump(mode="json") for item in plan.path_limits
    ]
    plan_safety["initial_structural_evidence"] = (
        plan.initial_structural_evidence.model_dump(mode="json")
        if plan.initial_structural_evidence is not None
        else None
    )
    expected_safety = {
        key: recomputed[key] for key in plan_safety
    }
    if plan_safety != expected_safety:
        raise ValueError(
            "visual convergence plan safety fields differ from the host-derived envelope"
        )


def _target_reached(
    plan: VisualConvergencePlan,
    report: VisualQAReport,
) -> bool:
    """Return whether both approved direct-reference targets are satisfied."""

    metrics = report.direct_metrics
    return (
        metrics.overall_direct_score >= plan.target_direct_score
        and metrics.silhouette_iou >= plan.target_silhouette_iou
    )


def _remaining_high_findings(report: VisualQAReport) -> list[str]:
    """List unresolved high direct-reference findings from the final exact run."""

    return sorted(
        finding.id
        for finding in report.findings
        if finding.severity == "high"
        and "direct_reference" in finding.evidence_sources
    )


def _path_value(record: dict[str, Any], path: list[str | int]) -> Any:
    """Read one candidate path from a raw object or material record."""

    current: Any = record
    for part in path:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                raise ValueError(f"candidate path index is unavailable: {path}")
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                raise ValueError(f"candidate path is unavailable: {path}")
            current = current[part]
    return current


def _candidate_baselines(
    scene_spec_path: Path,
    candidates: RevisionCandidates,
) -> dict[str, Any]:
    """Read exact current numeric values for candidate-envelope delta checks."""

    raw = json.loads(scene_spec_path.read_text(encoding="utf-8"))
    objects = {str(item["id"]): item for item in raw["objects"]}
    materials = {str(item["id"]): item for item in raw["materials"]}
    baselines: dict[str, Any] = {}
    for candidate in candidates.candidates:
        records = objects if candidate.target_type == "object" else materials
        if candidate.target_type not in {"object", "material"}:
            continue
        record = records.get(str(candidate.target_id))
        if record is None:
            continue
        try:
            baselines[candidate.id] = _path_value(record, candidate.path)
        except ValueError:
            continue
    return baselines


def _selection_requires_manual(
    selection: ConvergenceCandidateSelection,
) -> bool:
    """Classify an empty selection as manual when safe automation rejected useful edits."""

    manual_codes = {
        "manual_required",
        "generated_target_only",
        "custom_mesh_geometry",
        "target_type_not_allowed",
        "material_edits_disabled",
        "path_not_allowed",
        "operation_not_allowed",
        "target_not_allowed",
        "target_locked",
        "partial_group_selection",
        "candidate_conflict",
    }
    return any(item.code in manual_codes for item in selection.rejected)


def _load_receipts(
    session_root: Path,
) -> list[tuple[VisualConvergenceIteration, str, Path]]:
    """Load the exact contiguous iteration directory set and immutable receipts."""

    iterations_root = session_root / "iterations"
    if not iterations_root.is_dir():
        return []
    receipts: list[tuple[VisualConvergenceIteration, str, Path]] = []
    iteration_dirs = sorted(iterations_root.iterdir(), key=lambda path: path.name)
    unexpected = [
        path.name
        for path in iteration_dirs
        if not path.is_dir() or re.fullmatch(r"[0-9]{3}", path.name) is None
    ]
    if unexpected:
        raise ValueError(
            f"unexpected convergence iteration entries: {unexpected}"
        )
    for expected_index, iteration_root in enumerate(iteration_dirs, start=1):
        if iteration_root.name != f"{expected_index:03d}":
            raise ValueError(
                "convergence iteration directories must be exactly contiguous "
                f"001..N; expected {expected_index:03d}, found {iteration_root.name}"
            )
        path = iteration_root / "receipt.json"
        if not path.is_file():
            raise ValueError(
                f"convergence iteration receipt is missing: {path}"
            )
        receipt = VisualConvergenceIteration.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        receipts.append((receipt, sha256_file(path), path))
    return receipts


def _iteration_staging_dirs(session_root: Path) -> list[Path]:
    """Return at most one numeric receipt-less iteration staging directory."""

    staging_root = session_root / _ITERATION_STAGING_DIR
    if not staging_root.is_dir():
        return []
    entries = sorted(staging_root.iterdir(), key=lambda path: path.name)
    unexpected = [
        path.name
        for path in entries
        if not path.is_dir() or re.fullmatch(r"[0-9]{3}", path.name) is None
    ]
    if unexpected:
        raise ValueError(
            f"unexpected convergence staging entries: {unexpected}"
        )
    if len(entries) > 1:
        raise ValueError(
            "more than one incomplete convergence iteration staging directory exists"
        )
    return entries


def _require_no_incomplete_iteration_before_terminal(session_root: Path) -> None:
    """Refuse terminal evidence while a receipt-less iteration still needs recovery."""

    stages = _iteration_staging_dirs(session_root)
    if stages:
        raise RuntimeError(
            "receipt-less convergence staging exists; invoke the convergence run "
            "once to recover the interrupted iteration before cancellation or "
            "terminalization"
        )


def _iteration_attempt_payload(
    *,
    plan: VisualConvergencePlan,
    plan_sha256: str,
    approval_sha256: str,
    iteration_index: int,
    previous_receipt_sha256: str | None,
    base_scene_spec_sha256: str,
    base_scene_spec_snapshot_sha256: str,
    source_qa_run_id: str,
    source_qa_report_sha256: str,
    candidates_sha256: str,
    source_build_fingerprint: str,
    latest_pointer_snapshot: bytes | None,
) -> dict[str, Any]:
    """Build the immutable recovery contract written before one long iteration."""

    return {
        "schema_version": "0.6.0",
        "session_id": plan.session_id,
        "job_id": plan.job_id,
        "iteration_index": iteration_index,
        "plan_sha256": plan_sha256,
        "approval_sha256": approval_sha256,
        "previous_iteration_receipt_sha256": previous_receipt_sha256,
        "input_fingerprint": plan.input_fingerprint,
        "base_scene_spec_sha256": base_scene_spec_sha256,
        "base_scene_spec_snapshot_sha256": base_scene_spec_snapshot_sha256,
        "source_qa_run_id": source_qa_run_id,
        "source_qa_report_sha256": source_qa_report_sha256,
        "candidates_sha256": candidates_sha256,
        "source_build_fingerprint": source_build_fingerprint,
        "latest_pointer_present": latest_pointer_snapshot is not None,
        "latest_pointer_sha256": (
            hashlib.sha256(latest_pointer_snapshot).hexdigest()
            if latest_pointer_snapshot is not None
            else None
        ),
        "started_at": _utc_now(),
    }


def _validate_iteration_attempt(
    *,
    stage_root: Path,
    plan: VisualConvergencePlan,
    plan_sha256: str,
    approval_sha256: str,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> tuple[dict[str, Any] | None, bytes | None]:
    """Validate one incomplete attempt against the exact active receipt chain."""

    expected_index = len(receipts) + 1
    if stage_root.name != f"{expected_index:03d}":
        raise ValueError(
            "incomplete convergence staging index does not follow the receipt chain"
        )
    expected_base_sha256 = (
        receipts[-1][0].canonical_scene_spec_sha256
        if receipts
        else plan.initial_scene_spec_sha256
    )
    attempt_path = stage_root / _ITERATION_ATTEMPT
    if not attempt_path.is_file():
        return None, None
    payload = json.loads(attempt_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("convergence iteration attempt must be a JSON object")
    current_run, current_report_sha256 = _current_qa_identity(plan, receipts)
    expected_candidates_sha256 = _current_candidates_sha256(plan, receipts)
    expected_build_fingerprint = _current_build_fingerprint(plan, receipts)
    expected = {
        "schema_version": "0.6.0",
        "session_id": plan.session_id,
        "job_id": plan.job_id,
        "iteration_index": expected_index,
        "plan_sha256": plan_sha256,
        "approval_sha256": approval_sha256,
        "previous_iteration_receipt_sha256": (
            receipts[-1][1] if receipts else None
        ),
        "input_fingerprint": plan.input_fingerprint,
        "base_scene_spec_sha256": expected_base_sha256,
        "source_qa_run_id": current_run,
        "source_qa_report_sha256": current_report_sha256,
        "candidates_sha256": expected_candidates_sha256,
        "source_build_fingerprint": expected_build_fingerprint,
    }
    mismatches = {
        key: {"actual": payload.get(key), "expected": value}
        for key, value in expected.items()
        if payload.get(key) != value
    }
    if mismatches:
        raise ValueError(
            "incomplete convergence attempt no longer matches its active chain: "
            f"{mismatches}"
        )
    base_snapshot = stage_root / "base_scene_spec.json"
    base_snapshot_sha256 = payload.get("base_scene_spec_snapshot_sha256")
    if (
        not isinstance(base_snapshot_sha256, str)
        or base_snapshot_sha256 != expected_base_sha256
        or not base_snapshot.is_file()
        or sha256_file(base_snapshot) != expected_base_sha256
    ):
        raise ValueError("incomplete convergence base SceneSpec snapshot changed")
    latest_present = payload.get("latest_pointer_present")
    latest_sha256 = payload.get("latest_pointer_sha256")
    latest_path = stage_root / _LATEST_POINTER_SNAPSHOT
    latest_snapshot: bytes | None = None
    if latest_present is True:
        if (
            not isinstance(latest_sha256, str)
            or not latest_path.is_file()
            or sha256_file(latest_path) != latest_sha256
        ):
            raise ValueError("incomplete convergence latest-pointer snapshot changed")
        latest_snapshot = latest_path.read_bytes()
    elif latest_present is False:
        if latest_sha256 is not None or latest_path.exists():
            raise ValueError(
                "incomplete convergence latest-pointer absence binding changed"
            )
    else:
        raise ValueError(
            "incomplete convergence latest-pointer presence flag is invalid"
        )
    return payload, latest_snapshot


def _prepared_iteration_result_hash(
    stage_root: Path,
    *,
    attempt_sha256: str,
) -> str | None:
    """Validate the optional pre-promotion result binding for recovery."""

    prepared_path = stage_root / _ITERATION_PREPARED
    if not prepared_path.is_file():
        return None
    payload = json.loads(prepared_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("convergence prepared iteration must be a JSON object")
    result_sha256 = payload.get("result_scene_spec_sha256")
    if (
        payload.get("attempt_sha256") != attempt_sha256
        or not isinstance(result_sha256, str)
    ):
        raise ValueError("convergence prepared iteration binding changed")
    result_snapshot = stage_root / "result_scene_spec.json"
    if (
        not result_snapshot.is_file()
        or sha256_file(result_snapshot) != result_sha256
        or payload.get("result_scene_spec_snapshot_sha256") != result_sha256
    ):
        raise ValueError("convergence prepared result SceneSpec snapshot changed")
    return result_sha256


def _archive_recovered_staging(
    session_root: Path,
    stage_root: Path,
    *,
    recovery_payload: dict[str, Any],
) -> Path:
    """Preserve a recovered receipt-less attempt outside the active staging path."""

    receipt_path = stage_root / _RECOVERY_RECEIPT
    if not receipt_path.is_file():
        _write_immutable_json(receipt_path, recovery_payload)
    archive_root = session_root / _INTERRUPTED_ATTEMPTS_DIR
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_path = archive_root / (
        f"{stage_root.name}-{sha256_file(receipt_path)[:12]}"
    )
    if archive_path.exists():
        raise FileExistsError(
            f"Recovered convergence attempt archive already exists: {archive_path}"
        )
    stage_root.rename(archive_path)
    return archive_path


def _recover_incomplete_iteration(
    *,
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    plan_sha256: str,
    approval: VisualConvergenceApproval,
    approval_sha256: str,
    render_engine: str,
    render_device: str,
) -> dict[str, Any] | None:
    """Restore one interrupted receipt-less iteration and preserve its exact staging evidence."""

    stages = _iteration_staging_dirs(session_root)
    if not stages:
        return None
    _require_executable_plan_bindings(plan)
    validate_convergence_activation(plan, approval, plan_sha256=plan_sha256)
    _require_original_input_hashes(root, plan)
    _validate_initial_session_snapshots(root, session_root, plan)
    _require_host_safety_envelope(root, session_root, plan)
    _require_constraint_contract(root, plan)
    receipts = _load_receipts(session_root)
    validate_iteration_receipt_chain(
        plan,
        approval,
        plan_sha256=plan_sha256,
        approval_sha256=approval_sha256,
        receipts=[
            (receipt, receipt_sha256)
            for receipt, receipt_sha256, _path in receipts
        ],
    )
    _audit_receipt_evidence(
        root=root,
        session_root=session_root,
        plan=plan,
        receipts=receipts,
    )
    stage_root = stages[0]
    expected_base_sha256 = (
        receipts[-1][0].canonical_scene_spec_sha256
        if receipts
        else plan.initial_scene_spec_sha256
    )
    expected_build_fingerprint = _current_build_fingerprint(plan, receipts)
    attempt, latest_snapshot = _validate_iteration_attempt(
        stage_root=stage_root,
        plan=plan,
        plan_sha256=plan_sha256,
        approval_sha256=approval_sha256,
        receipts=receipts,
    )
    current_run, current_report_sha256 = _current_qa_identity(plan, receipts)
    _audit_qa_authoritative_evidence(
        root=root,
        job_id=plan.job_id,
        run_id=current_run,
        expected_scene_spec_sha256=expected_base_sha256,
        expected_report_sha256=current_report_sha256,
        expected_candidates_sha256=_current_candidates_sha256(plan, receipts),
        expected_build_fingerprint=expected_build_fingerprint,
    )
    attempt_path = stage_root / _ITERATION_ATTEMPT
    result_sha256 = (
        _prepared_iteration_result_hash(
            stage_root,
            attempt_sha256=sha256_file(attempt_path),
        )
        if attempt is not None
        else None
    )
    canonical_path = root / "analysis" / "scene_spec.json"
    current_sha256 = sha256_file(canonical_path)
    allowed_hashes = {expected_base_sha256}
    if result_sha256 is not None:
        allowed_hashes.add(result_sha256)
    if current_sha256 not in allowed_hashes:
        raise ValueError(
            "receipt-less convergence attempt cannot be recovered because canonical "
            "SceneSpec is neither its exact base nor prepared result"
        )
    canonical_restored = current_sha256 == expected_base_sha256
    rebuild_required = False
    if current_sha256 != expected_base_sha256:
        _load_authoritative_activation(
            session_root,
            job_id=plan.job_id,
            session_id=plan.session_id,
            expected_plan_sha256=plan_sha256,
            expected_approval_sha256=approval_sha256,
        )
        replace_scene_spec_if_current(
            plan.job_id,
            stage_root / "base_scene_spec.json",
            expected_current_sha256=current_sha256,
            expected_candidate_sha256=expected_base_sha256,
            lock_owner_id=current_job_write_lock_owner(plan.job_id),
            archive_current=True,
        )
        canonical_restored = True
        rebuild_required = True
    try:
        current_build = _current_build_provenance(root, plan.job_id)
    except (FileNotFoundError, ValueError):
        rebuild_required = True
    else:
        rebuild_required = (
            rebuild_required
            or current_build["fingerprint"] != expected_build_fingerprint
        )
    rebuild = (
        _run_job_pipeline(
            plan.job_id,
            root,
            render_engine,
            render_device,
        )
        if rebuild_required
        else None
    )
    if attempt is not None:
        _restore_latest(root, latest_snapshot)
    restored_build = _current_build_provenance(root, plan.job_id)
    if (
        sha256_file(canonical_path) != expected_base_sha256
        or restored_build["fingerprint"] != expected_build_fingerprint
    ):
        raise RuntimeError(
            "interrupted convergence recovery did not restore exact canonical/build state"
        )
    recovery_payload = {
        "schema_version": "0.6.0",
        "session_id": plan.session_id,
        "job_id": plan.job_id,
        "iteration_index": len(receipts) + 1,
        "plan_sha256": plan_sha256,
        "approval_sha256": approval_sha256,
        "attempt_sha256": (
            sha256_file(attempt_path) if attempt_path.is_file() else None
        ),
        "prepared_result_scene_spec_sha256": result_sha256,
        "restored_scene_spec_sha256": expected_base_sha256,
        "restored_build_fingerprint": expected_build_fingerprint,
        "canonical_restored": canonical_restored,
        "rebuild_performed": rebuild is not None,
        "status": "recovered_interrupted_before_receipt",
        "completed_at": _utc_now(),
    }
    archive_path = _archive_recovered_staging(
        session_root,
        stage_root,
        recovery_payload=recovery_payload,
    )
    return {
        "execution_outcome": "interrupted_attempt_recovered",
        "recovered_iteration_index": len(receipts) + 1,
        "recovered_attempt": str(archive_path),
        "canonical_scene_spec_sha256": expected_base_sha256,
        "build_fingerprint": expected_build_fingerprint,
        "next_action": "invoke_run_again",
    }


def _commit_iteration_receipt(
    session_root: Path,
    stage_root: Path,
    receipt: VisualConvergenceIteration,
) -> tuple[VisualConvergenceIteration, str, Path]:
    """Atomically expose one completed iteration only after its receipt exists."""

    receipt_path = stage_root / "receipt.json"
    _write_iteration_receipt(receipt_path, receipt)
    final_root = session_root / "iterations" / f"{receipt.iteration_index:03d}"
    final_root.parent.mkdir(parents=True, exist_ok=True)
    if final_root.exists():
        raise FileExistsError(
            f"Immutable convergence iteration already exists: {final_root}"
        )
    stage_root.rename(final_root)
    final_receipt = final_root / "receipt.json"
    return receipt, sha256_file(final_receipt), final_receipt


def _execution_response(
    payload: dict[str, Any],
    *,
    outcome: str,
    iterations_executed: int,
    next_action: str | None,
) -> dict[str, Any]:
    """Add per-invocation host-step semantics without changing immutable reports."""

    return {
        **payload,
        "host_step_iteration_limit": 1,
        "execution_outcome": outcome,
        "iterations_executed_this_invocation": iterations_executed,
        "next_action": next_action,
    }


def _bind_existing_artifact(
    root: Path,
    path: Path,
    expected_sha256: str,
    *,
    label: str,
) -> HashBoundConvergenceArtifact:
    """Verify one contained evidence file and return its exact terminal binding."""

    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    actual_sha256 = sha256_file(resolved_path)
    if actual_sha256 != expected_sha256:
        raise ValueError(f"{label} hash changed: {path}")
    try:
        relative_path = resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} escapes the job workspace: {path}") from exc
    return HashBoundConvergenceArtifact(
        relative_path=relative_path,
        sha256=actual_sha256,
    )


def _audit_structural_comparison_evidence(
    *,
    root: Path,
    iteration_root: Path,
    plan: VisualConvergencePlan,
    receipt: VisualConvergenceIteration,
) -> tuple[list[HashBoundConvergenceArtifact], bool]:
    """Recompute one exact five-view comparison and return its non-regression result."""

    if plan.structural_multiview_policy == "not_applicable":
        if receipt.structural_multiview_status != "not_applicable":
            raise ValueError("non-spatial convergence receipt carries five-view evidence")
        return [], True
    if receipt.structural_multiview_status == "not_applicable":
        if receipt.status in {"accepted", "rolled_back"}:
            raise ValueError(
                "executed spatial receipt lacks a five-view structural comparison"
            )
        return [], True
    source = receipt.source_structural_evidence
    result = receipt.result_structural_evidence
    comparison_hash = receipt.structural_comparison_sha256
    comparison_relative = receipt.structural_comparison_path
    if (
        source is None
        or result is None
        or comparison_hash is None
        or comparison_relative is None
        or receipt.result_scene_spec_sha256 is None
    ):
        raise ValueError("executed spatial receipt lacks complete five-view evidence")
    expected_comparison_path = iteration_root / _STRUCTURAL_COMPARISON
    expected_relative = expected_comparison_path.resolve().relative_to(root.resolve()).as_posix()
    if comparison_relative != expected_relative:
        raise ValueError("structural comparison moved outside its iteration-owned path")
    artifacts = [
        *_structural_terminal_artifacts(
            root,
            source,
            expected_job_id=plan.job_id,
            expected_scene_spec_sha256=receipt.base_scene_spec_sha256,
        ),
        *_structural_terminal_artifacts(
            root,
            result,
            expected_job_id=plan.job_id,
            expected_scene_spec_sha256=receipt.result_scene_spec_sha256,
        ),
        _bind_existing_artifact(
            root,
            expected_comparison_path,
            comparison_hash,
            label="iteration five-view structural comparison",
        ),
    ]
    recorded = StructuralRegressionReport.model_validate_json(
        expected_comparison_path.read_text(encoding="utf-8")
    )
    recomputed = compare_assembly_sanity_terminals(
        root,
        baseline=source,
        result=result,
        expected_job_id=plan.job_id,
        generated_at=recorded.generated_at,
    )
    if recorded != recomputed:
        raise ValueError("five-view structural comparison differs from exact evidence")
    regression_ids = [finding.id for finding in recomputed.regressions]
    if (
        receipt.structural_multiview_status != recomputed.status
        or receipt.structural_regression_ids != regression_ids
    ):
        raise ValueError("five-view receipt summary differs from recomputed comparison")
    return _deduplicate_artifacts(artifacts), recomputed.status == "passed"


def _deduplicate_artifacts(
    artifacts: list[HashBoundConvergenceArtifact],
) -> list[HashBoundConvergenceArtifact]:
    """Return one stable path-unique evidence list and reject hash disagreement."""

    by_path: dict[str, HashBoundConvergenceArtifact] = {}
    for artifact in artifacts:
        previous = by_path.get(artifact.relative_path)
        if previous is not None and previous.sha256 != artifact.sha256:
            raise ValueError(
                "convergence evidence path has conflicting hashes: "
                f"{artifact.relative_path}"
            )
        by_path[artifact.relative_path] = artifact
    return [by_path[path] for path in sorted(by_path)]


def _resolve_qa_artifact(
    *,
    root: Path,
    owner: Path,
    value: str,
    label: str,
) -> Path:
    """Resolve one historical QA path while rejecting missing or escaping evidence."""

    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = owner / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes the job workspace: {value}") from exc
    if not resolved.is_file():
        raise ValueError(f"{label} is missing: {resolved}")
    return resolved


def _audit_qa_authoritative_evidence(
    *,
    root: Path,
    job_id: str,
    run_id: str,
    expected_scene_spec_sha256: str,
    expected_report_sha256: str,
    expected_candidates_sha256: str,
    expected_build_fingerprint: str | None,
) -> tuple[
    Path,
    Path,
    VisualQAReport,
    RevisionCandidates,
    list[HashBoundConvergenceArtifact],
]:
    """Audit a QA report, request, exact seven-pass manifest, pass files, and candidates."""

    report_path, candidates_path, report, candidates = _qa_evidence(
        root,
        job_id,
        run_id,
        require_current_spec=False,
    )
    run_root = report_path.parent
    request_path = run_root / "request.json"
    request = VisualQARequest.model_validate_json(request_path.read_text(encoding="utf-8"))
    request_file_sha256 = sha256_file(request_path)
    if report.request_sha256 not in {
        canonical_model_sha256(request),
        request_file_sha256,
    }:
        raise ValueError("visual QA request semantic hash changed")
    request_artifact = _bind_existing_artifact(
        root,
        request_path,
        request_file_sha256,
        label="visual QA request",
    )
    if (
        request.job_id != job_id
        or request.run_id != run_id
        or request.scene_spec_sha256 != expected_scene_spec_sha256
        or request.camera_fingerprint != report.camera_fingerprint
    ):
        raise ValueError("visual QA request identity or SceneSpec binding changed")

    manifest_path = _resolve_qa_artifact(
        root=root,
        owner=run_root,
        value=request.render_pass_manifest_path,
        label="visual QA render-pass manifest",
    )
    manifest_artifact = _bind_existing_artifact(
        root,
        manifest_path,
        request.render_pass_manifest_sha256,
        label="visual QA render-pass manifest",
    )
    manifest = RenderPassManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if (
        manifest.job_id != job_id
        or manifest.run_id not in {None, run_id}
        or manifest.scene_spec_sha256 != expected_scene_spec_sha256
        or manifest.camera_fingerprint != report.camera_fingerprint
        or (
            expected_build_fingerprint is not None
            and manifest.build_fingerprint != expected_build_fingerprint
        )
    ):
        raise ValueError(
            "visual QA render-pass manifest identity, camera, or build binding changed"
        )

    artifacts = [
        _bind_existing_artifact(
            root,
            report_path,
            expected_report_sha256,
            label="visual QA report",
        ),
        _bind_existing_artifact(
            root,
            candidates_path,
            expected_candidates_sha256,
            label="visual QA candidates",
        ),
        request_artifact,
        manifest_artifact,
    ]
    request_sources = (
        ("reference", request.reference_path, request.reference_sha256),
        ("reference mask", request.reference_mask_path, request.reference_mask_sha256),
        ("preview", request.preview_path, request.preview_sha256),
    )
    resolved_request_sources: dict[str, Path] = {}
    for label, value, expected_hash in request_sources:
        resolved = _resolve_qa_artifact(
            root=root,
            owner=run_root,
            value=value,
            label=f"visual QA {label}",
        )
        resolved_request_sources[label] = resolved
        artifacts.append(
            _bind_existing_artifact(
                root,
                resolved,
                expected_hash,
                label=f"visual QA {label}",
            )
        )
    beauty_path: Path | None = None
    for record in manifest.passes:
        pass_path = _resolve_qa_artifact(
            root=root,
            owner=manifest_path.parent,
            value=record.path,
            label=f"visual QA {record.kind} pass",
        )
        artifacts.append(
            _bind_existing_artifact(
                root,
                pass_path,
                record.sha256,
                label=f"visual QA {record.kind} pass",
            )
        )
        if record.kind == "beauty":
            beauty_path = pass_path
    if beauty_path != resolved_request_sources["preview"]:
        raise ValueError("visual QA preview is not the exact beauty pass")
    return (
        report_path,
        candidates_path,
        report,
        candidates,
        _deduplicate_artifacts(artifacts),
    )


def _validate_iteration_authorization_bundle(
    *,
    session_id: str,
    job_id: str,
    iteration_index: int,
    plan_sha256: str,
    approval_sha256: str,
    base_scene_spec_sha256: str,
    source_qa_report_sha256: str,
    source_build_fingerprint: str | None,
    candidates_path: Path,
    candidates_sha256: str,
    selection_path: Path,
    selection_sha256: str,
    selected_candidate_ids: list[str],
    compiled_plan_path: Path,
    compiled_plan_sha256: str,
    authorization_path: Path,
    authorization_sha256: str,
) -> VisualConvergenceIterationAuthorization:
    """Load and cross-check the exact selection, plan, and authorization files."""

    actual_candidates_sha256 = sha256_file(candidates_path)
    actual_selection_sha256 = sha256_file(selection_path)
    actual_compiled_plan_sha256 = sha256_file(compiled_plan_path)
    actual_authorization_sha256 = sha256_file(authorization_path)
    actual_hashes = {
        "candidates_sha256": (actual_candidates_sha256, candidates_sha256),
        "selection_sha256": (actual_selection_sha256, selection_sha256),
        "compiled_plan_sha256": (
            actual_compiled_plan_sha256,
            compiled_plan_sha256,
        ),
        "authorization_sha256": (
            actual_authorization_sha256,
            authorization_sha256,
        ),
    }
    changed = sorted(
        label for label, (actual, expected) in actual_hashes.items() if actual != expected
    )
    if changed:
        raise ValueError(
            f"iteration authorization evidence hash mismatch: {changed}"
        )
    selection = _load_selection(selection_path)
    authorization = _load_iteration_authorization(authorization_path)
    compiled = load_revision_plan(compiled_plan_path)
    selection_checks = {
        "session_id": (selection.session_id, session_id),
        "job_id": (selection.job_id, job_id),
        "candidates_sha256": (selection.candidates_sha256, candidates_sha256),
        "base_scene_spec_sha256": (
            selection.base_scene_spec_sha256,
            base_scene_spec_sha256,
        ),
        "source_qa_report_sha256": (
            selection.source_qa_report_sha256,
            source_qa_report_sha256,
        ),
        "selected_candidate_ids": (
            selection.selected_candidate_ids,
            selected_candidate_ids,
        ),
    }
    selection_mismatches = sorted(
        label
        for label, (actual, expected) in selection_checks.items()
        if actual != expected
    )
    if selection_mismatches:
        raise ValueError(
            "iteration selection binding mismatch: "
            f"{selection_mismatches}"
        )
    authorization_checks = {
        "session_id": (authorization.session_id, session_id),
        "job_id": (authorization.job_id, job_id),
        "iteration_index": (authorization.iteration_index, iteration_index),
        "plan_sha256": (authorization.plan_sha256, plan_sha256),
        "approval_sha256": (authorization.approval_sha256, approval_sha256),
        "base_scene_spec_sha256": (
            authorization.base_scene_spec_sha256,
            base_scene_spec_sha256,
        ),
        "source_qa_report_sha256": (
            authorization.source_qa_report_sha256,
            source_qa_report_sha256,
        ),
        "source_build_fingerprint": (
            authorization.source_build_fingerprint,
            source_build_fingerprint,
        ),
        "candidates_sha256": (
            authorization.candidates_sha256,
            candidates_sha256,
        ),
        "selection_sha256": (
            authorization.selection_sha256,
            selection_sha256,
        ),
        "compiled_plan_sha256": (
            authorization.compiled_plan_sha256,
            compiled_plan_sha256,
        ),
        "selected_candidate_ids": (
            authorization.selected_candidate_ids,
            selected_candidate_ids,
        ),
    }
    authorization_mismatches = sorted(
        label
        for label, (actual, expected) in authorization_checks.items()
        if actual != expected
    )
    if authorization_mismatches:
        raise ValueError(
            "iteration authorization binding mismatch: "
            f"{authorization_mismatches}"
        )
    if compiled.job_id != job_id or compiled.base_spec_sha256 != base_scene_spec_sha256:
        raise ValueError("compiled iteration plan identity or base hash changed")
    return authorization


def _apply_iteration_authorization(
    *,
    scene_spec_path: Path,
    candidates_path: Path,
    selection_path: Path,
    compiled_plan_path: Path,
    authorization_path: Path,
    session_id: str,
    job_id: str,
    iteration_index: int,
    plan_sha256: str,
    approval_sha256: str,
    base_scene_spec_sha256: str,
    source_qa_report_sha256: str,
    source_build_fingerprint: str | None,
    candidates_sha256: str,
    selection_sha256: str,
    compiled_plan_sha256: str,
    authorization_sha256: str,
    selected_candidate_ids: list[str],
    output_path: Path,
) -> dict[str, Any]:
    """Validate one on-disk iteration authorization before applying its exact bundle."""

    authorization = _validate_iteration_authorization_bundle(
        session_id=session_id,
        job_id=job_id,
        iteration_index=iteration_index,
        plan_sha256=plan_sha256,
        approval_sha256=approval_sha256,
        base_scene_spec_sha256=base_scene_spec_sha256,
        source_qa_report_sha256=source_qa_report_sha256,
        source_build_fingerprint=source_build_fingerprint,
        candidates_path=candidates_path,
        candidates_sha256=candidates_sha256,
        selection_path=selection_path,
        selection_sha256=selection_sha256,
        selected_candidate_ids=selected_candidate_ids,
        compiled_plan_path=compiled_plan_path,
        compiled_plan_sha256=compiled_plan_sha256,
        authorization_path=authorization_path,
        authorization_sha256=authorization_sha256,
    )
    return apply_hash_bound_revision(
        scene_spec_path=scene_spec_path,
        candidates_path=candidates_path,
        plan_path=compiled_plan_path,
        selected_candidate_ids=authorization.selected_candidate_ids,
        expected_candidates_sha256=authorization.candidates_sha256,
        expected_plan_sha256=authorization.compiled_plan_sha256,
        expected_base_spec_sha256=authorization.base_scene_spec_sha256,
        authorization_id=authorization.authorization_id,
        output_path=output_path,
    )


def _audit_iteration_receipt_evidence(
    *,
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    receipt: VisualConvergenceIteration,
    previous_receipt: VisualConvergenceIteration | None,
    receipt_sha256: str,
    receipt_path: Path,
) -> list[HashBoundConvergenceArtifact]:
    """Verify every file hash referenced by one immutable iteration receipt."""

    iteration_root = session_root / "iterations" / f"{receipt.iteration_index:03d}"
    artifacts = [
        _bind_existing_artifact(
            root,
            receipt_path,
            receipt_sha256,
            label="iteration receipt",
        )
    ]
    new_bound_receipt = plan.initial_build_fingerprint is not None
    if new_bound_receipt and (
        receipt.base_scene_spec_snapshot_sha256 != receipt.base_scene_spec_sha256
        or receipt.source_build_fingerprint is None
    ):
        raise ValueError(
            "new convergence receipts require the exact base snapshot and source build"
        )
    if receipt.base_scene_spec_snapshot_sha256 is not None:
        artifacts.append(
            _bind_existing_artifact(
                root,
                iteration_root / "base_scene_spec.json",
                receipt.base_scene_spec_snapshot_sha256,
                label="iteration base SceneSpec snapshot",
            )
        )
    source_build_payload: dict[str, Any] | None = None
    if receipt.source_build_fingerprint is not None:
        if previous_receipt is None:
            source_build_path = session_root / _INITIAL_BUILD_PROVENANCE
            source_build_sha256 = plan.initial_build_provenance_sha256
            source_scene_sha256 = plan.initial_scene_spec_sha256
        else:
            source_build_path = (
                session_root
                / "iterations"
                / f"{previous_receipt.iteration_index:03d}"
                / "result_build_provenance.json"
            )
            source_build_sha256 = previous_receipt.result_build_provenance_sha256
            source_scene_sha256 = previous_receipt.result_scene_spec_sha256
        if source_build_sha256 is None or source_scene_sha256 is None:
            raise ValueError("iteration source build snapshot chain is incomplete")
        artifacts.append(
            _bind_build_provenance_snapshot(
                root,
                source_build_path,
                expected_file_sha256=source_build_sha256,
                expected_fingerprint=receipt.source_build_fingerprint,
                expected_scene_spec_sha256=source_scene_sha256,
                expected_camera_fingerprint=plan.camera_fingerprint,
            )
        )
        source_build_payload = json.loads(
            source_build_path.read_text(encoding="utf-8")
        )
    (
        source_report_path,
        source_candidates_path,
        source_report,
        source_candidates,
        source_qa_artifacts,
    ) = _audit_qa_authoritative_evidence(
        root=root,
        job_id=plan.job_id,
        run_id=receipt.source_qa_run_id,
        expected_scene_spec_sha256=receipt.base_scene_spec_sha256,
        expected_report_sha256=receipt.source_qa_report_sha256,
        expected_candidates_sha256=receipt.candidates_sha256,
        expected_build_fingerprint=(
            receipt.source_build_fingerprint
            or plan.initial_build_fingerprint
        ),
    )
    artifacts.extend(source_qa_artifacts)
    if source_candidates.base_spec_sha256 != receipt.base_scene_spec_sha256:
        raise ValueError("iteration source candidates use a different base SceneSpec")
    if (
        source_report.direct_metrics.overall_direct_score
        != receipt.before_direct_score
        or source_report.direct_metrics.silhouette_iou
        != receipt.before_silhouette_iou
    ):
        raise ValueError("iteration source QA metrics changed relative to receipt")
    selection_path = iteration_root / "selection.json"
    artifacts.append(
        _bind_existing_artifact(
            root,
            selection_path,
            receipt.selection_sha256,
            label="iteration selection",
        )
    )
    selection = _load_selection(selection_path)
    if (
        selection.session_id != receipt.session_id
        or selection.job_id != receipt.job_id
        or selection.candidates_sha256 != receipt.candidates_sha256
        or selection.base_scene_spec_sha256 != receipt.base_scene_spec_sha256
        or selection.source_qa_report_sha256 != receipt.source_qa_report_sha256
        or selection.selected_candidate_ids != receipt.selected_candidate_ids
    ):
        raise ValueError("iteration selection content does not match its receipt")

    plan_hash = receipt.compiled_plan_sha256
    authorization_hash = receipt.execution_authorization_sha256
    if (plan_hash is None) != (authorization_hash is None):
        raise ValueError("iteration plan and authorization hashes must appear together")
    if plan_hash is not None and authorization_hash is not None:
        compiled_plan_path = iteration_root / "revision_plan.json"
        authorization_path = iteration_root / "authorization.json"
        artifacts.extend(
            [
                _bind_existing_artifact(
                    root,
                    compiled_plan_path,
                    plan_hash,
                    label="iteration compiled revision plan",
                ),
                _bind_existing_artifact(
                    root,
                    authorization_path,
                    authorization_hash,
                    label="iteration execution authorization",
                ),
            ]
        )
        _validate_iteration_authorization_bundle(
            session_id=receipt.session_id,
            job_id=receipt.job_id,
            iteration_index=receipt.iteration_index,
            plan_sha256=receipt.plan_sha256,
            approval_sha256=receipt.approval_sha256,
            base_scene_spec_sha256=receipt.base_scene_spec_sha256,
            source_qa_report_sha256=receipt.source_qa_report_sha256,
            source_build_fingerprint=receipt.source_build_fingerprint,
            candidates_path=source_candidates_path,
            candidates_sha256=receipt.candidates_sha256,
            selection_path=selection_path,
            selection_sha256=receipt.selection_sha256,
            selected_candidate_ids=receipt.selected_candidate_ids,
            compiled_plan_path=compiled_plan_path,
            compiled_plan_sha256=plan_hash,
            authorization_path=authorization_path,
            authorization_sha256=authorization_hash,
        )

    if receipt.result_scene_spec_sha256 is not None:
        artifacts.append(
            _bind_existing_artifact(
                root,
                iteration_root / "result_scene_spec.json",
                receipt.result_scene_spec_sha256,
                label="iteration result SceneSpec snapshot",
            )
        )
    result_build_payload: dict[str, Any] | None = None
    if receipt.result_build_fingerprint is not None:
        if receipt.result_build_provenance_sha256 is None:
            raise ValueError("iteration result build provenance hash is missing")
        result_build_path = iteration_root / "result_build_provenance.json"
        artifacts.append(
            _bind_build_provenance_snapshot(
                root,
                result_build_path,
                expected_file_sha256=receipt.result_build_provenance_sha256,
                expected_fingerprint=receipt.result_build_fingerprint,
                expected_scene_spec_sha256=receipt.result_scene_spec_sha256
                or receipt.base_scene_spec_sha256,
                expected_camera_fingerprint=plan.camera_fingerprint,
            )
        )
        result_build_payload = json.loads(
            result_build_path.read_text(encoding="utf-8")
        )
        if source_build_payload is not None and receipt.result_scene_spec_sha256:
            _validate_result_build_transition(
                source_build_payload,
                result_build_payload,
                expected_source_scene_spec_sha256=receipt.base_scene_spec_sha256,
                expected_result_scene_spec_sha256=receipt.result_scene_spec_sha256,
            )
    before_constraint_evidence: dict[str, Any] | None = None
    after_constraint_evidence: dict[str, Any] | None = None
    if receipt.before_constraints_sha256 is not None:
        before_path = iteration_root / "before_constraints.json"
        before_constraint_evidence = _load_constraint_evidence(
            before_path,
            expected_sha256=receipt.before_constraints_sha256,
        )
        artifacts.append(
            _bind_existing_artifact(
                root,
                before_path,
                receipt.before_constraints_sha256,
                label="iteration before-constraint evidence",
            )
        )
    if receipt.after_constraints_sha256 is not None:
        after_path = iteration_root / "after_constraints.json"
        after_constraint_evidence = _load_constraint_evidence(
            after_path,
            expected_sha256=receipt.after_constraints_sha256,
        )
        artifacts.append(
            _bind_existing_artifact(
                root,
                after_path,
                receipt.after_constraints_sha256,
                label="iteration after-constraint evidence",
            )
        )
    if new_bound_receipt and receipt.status in {"accepted", "rolled_back"} and (
        before_constraint_evidence is None or after_constraint_evidence is None
    ):
        raise ValueError(
            "new executed convergence receipts lack exact constraint evidence"
        )
    structural_non_regression = True
    if (
        plan.structural_multiview_policy == "spatial_v1_required"
        and receipt.structural_multiview_status != "not_applicable"
    ):
        expected_source_structural = (
            previous_receipt.result_structural_evidence
            if previous_receipt is not None
            else plan.initial_structural_evidence
        )
        if (
            expected_source_structural is None
            or receipt.source_structural_evidence != expected_source_structural
        ):
            raise ValueError(
                "iteration source five-view evidence is outside the accepted receipt chain"
            )
    structural_artifacts, structural_non_regression = (
        _audit_structural_comparison_evidence(
            root=root,
            iteration_root=iteration_root,
            plan=plan,
            receipt=receipt,
        )
    )
    artifacts.extend(structural_artifacts)
    if receipt.result_qa_run_id is not None:
        if (
            receipt.result_qa_report_sha256 is None
            or receipt.result_candidates_sha256 is None
            or receipt.result_scene_spec_sha256 is None
        ):
            raise ValueError("iteration result QA identity is incomplete")
        (
            _result_report_path,
            _result_candidates_path,
            result_report,
            result_candidates,
            result_qa_artifacts,
        ) = _audit_qa_authoritative_evidence(
            root=root,
            job_id=plan.job_id,
            run_id=receipt.result_qa_run_id,
            expected_scene_spec_sha256=receipt.result_scene_spec_sha256,
            expected_report_sha256=receipt.result_qa_report_sha256,
            expected_candidates_sha256=receipt.result_candidates_sha256,
            expected_build_fingerprint=(
                receipt.result_build_fingerprint
                or receipt.source_build_fingerprint
                or plan.initial_build_fingerprint
            ),
        )
        artifacts.extend(result_qa_artifacts)
        if result_candidates.base_spec_sha256 != receipt.result_scene_spec_sha256:
            raise ValueError("iteration result candidates use a different result SceneSpec")
        if (
            receipt.after_direct_score is not None
            and result_report.direct_metrics.overall_direct_score
            != receipt.after_direct_score
        ) or (
            receipt.after_silhouette_iou is not None
            and result_report.direct_metrics.silhouette_iou
            != receipt.after_silhouette_iou
        ):
            raise ValueError("iteration result QA metrics changed relative to receipt")
        if receipt.status in {"accepted", "rolled_back"}:
            before_evidence = before_constraint_evidence or {
                "failures": 0,
                "results": [],
            }
            after_evidence = after_constraint_evidence or {
                "failures": 0,
                "results": [],
            }
            recomputed = evaluate_convergence(
                before_report_path=source_report_path,
                after_report_path=_result_report_path,
                changed_ids=receipt.changed_ids,
                preserved_ids=[],
                before_failed_constraints=int(before_evidence["failures"]),
                after_failed_constraints=int(after_evidence["failures"]),
                before_constraint_results=list(before_evidence["results"]),
                after_constraint_results=list(after_evidence["results"]),
                multiview_comparison_path=(
                    iteration_root / _STRUCTURAL_COMPARISON
                    if receipt.structural_multiview_status != "not_applicable"
                    else None
                ),
                minimum_improvement=plan.minimum_iteration_gain,
            )
            constraint_regressions = compare_constraint_results(
                list(before_evidence["results"]),
                list(after_evidence["results"]),
            )
            iou_non_regression = (
                result_report.direct_metrics.silhouette_iou + 1e-9
                >= source_report.direct_metrics.silhouette_iou
            )
            if receipt.constraint_regression_count != len(constraint_regressions):
                raise ValueError(
                    "iteration constraint-regression count changed relative to evidence"
                )
            should_accept = (
                recomputed.accepted
                and iou_non_regression
                and not constraint_regressions
                and structural_non_regression
            )
            if (receipt.status == "accepted") != should_accept:
                raise ValueError(
                    "iteration accepted/rolled-back status contradicts recomputed "
                    "score, silhouette, or constraint predicates"
                )
    elif (
        receipt.result_qa_report_sha256 is not None
        or receipt.result_candidates_sha256 is not None
    ):
        raise ValueError("iteration result QA hashes require a result run ID")
    return _deduplicate_artifacts(artifacts)


def _audit_receipt_evidence(
    *,
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> list[HashBoundConvergenceArtifact]:
    """Verify and flatten all receipt-owned source, authorization, and result evidence."""

    artifacts: list[HashBoundConvergenceArtifact] = []
    previous_receipt: VisualConvergenceIteration | None = None
    for receipt, receipt_sha256, receipt_path in receipts:
        artifacts.extend(
            _audit_iteration_receipt_evidence(
                root=root,
                session_root=session_root,
                plan=plan,
                receipt=receipt,
                previous_receipt=previous_receipt,
                receipt_sha256=receipt_sha256,
                receipt_path=receipt_path,
            )
        )
        previous_receipt = receipt
    return _deduplicate_artifacts(artifacts)


def _current_qa_identity(
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> tuple[str, str]:
    """Recover the exact current QA run/report hash from the accepted receipt chain."""

    current_run = plan.initial_qa_run_id
    current_report_hash = plan.initial_qa_report_sha256
    for receipt, _receipt_hash, _path in receipts:
        if receipt.status == "accepted":
            if receipt.result_qa_run_id is None or receipt.result_qa_report_sha256 is None:
                raise ValueError("accepted convergence receipt lacks result QA evidence")
            current_run = receipt.result_qa_run_id
            current_report_hash = receipt.result_qa_report_sha256
    return current_run, current_report_hash


def _current_candidates_sha256(
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> str:
    """Recover the exact candidate hash approved for the current QA run."""

    current = plan.initial_candidates_sha256
    for receipt, _receipt_hash, _path in receipts:
        if receipt.status == "accepted":
            if receipt.result_candidates_sha256 is None:
                raise ValueError("accepted convergence receipt lacks result candidates")
            current = receipt.result_candidates_sha256
    if current is None:
        raise ValueError(
            "legacy convergence plan lacks an exact initial candidate binding"
        )
    return current


def _current_build_fingerprint(
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> str:
    """Recover the exact canonical build fingerprint from the accepted receipt chain."""

    current = plan.initial_build_fingerprint
    for receipt, _receipt_hash, _path in receipts:
        if receipt.status == "accepted":
            if receipt.result_build_fingerprint is None:
                raise ValueError("accepted convergence receipt lacks result build provenance")
            current = receipt.result_build_fingerprint
    if current is None:
        raise ValueError(
            "legacy convergence plan lacks an exact initial build fingerprint"
        )
    return current


def _require_original_input_hashes(root: Path, plan: VisualConvergencePlan) -> None:
    """Revalidate the exact planning-time input set during an active session."""

    _validate_plan_input_binding(plan)
    if plan.initial_input_hashes:
        _require_input_hashes(root, plan.initial_input_hashes)
    elif _input_fingerprint(root) != plan.input_fingerprint:
        raise ValueError("immutable input evidence changed during convergence")


def _terminal_scene_snapshot(
    *,
    root: Path,
    session_root: Path,
    expected_scene_spec_sha256: str,
) -> HashBoundConvergenceArtifact:
    """Create or verify the immutable canonical SceneSpec snapshot at session termination."""

    destination = session_root / "final_scene_spec.json"
    if destination.exists():
        snapshot_sha256 = sha256_file(destination)
        if snapshot_sha256 != expected_scene_spec_sha256:
            raise ValueError("terminal final SceneSpec snapshot changed")
    else:
        source = root / "analysis" / "scene_spec.json"
        if not source.is_file() or sha256_file(source) != expected_scene_spec_sha256:
            raise ValueError("terminal canonical SceneSpec does not match the receipt chain")
        snapshot_sha256 = _write_immutable_copy(source, destination)
        if snapshot_sha256 != expected_scene_spec_sha256:
            raise RuntimeError("terminal final SceneSpec snapshot changed during copy")
    return _bind_existing_artifact(
        root,
        destination,
        expected_scene_spec_sha256,
        label="terminal final SceneSpec snapshot",
    )


def _terminal_build_provenance_snapshot(
    *,
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> tuple[
    HashBoundConvergenceArtifact | None,
    HashBoundConvergenceArtifact | None,
    str | None,
]:
    """Verify the initial build snapshot and preserve the exact terminal build inputs."""

    if (
        plan.initial_build_fingerprint is None
        or plan.initial_build_provenance_sha256 is None
    ):
        return None, None, None
    initial = _bind_build_provenance_snapshot(
        root,
        session_root / _INITIAL_BUILD_PROVENANCE,
        expected_file_sha256=plan.initial_build_provenance_sha256,
        expected_fingerprint=plan.initial_build_fingerprint,
        expected_scene_spec_sha256=plan.initial_scene_spec_sha256,
        expected_camera_fingerprint=plan.camera_fingerprint,
    )
    final_fingerprint = _current_build_fingerprint(plan, receipts)
    current = _current_build_provenance(root, plan.job_id)
    if current["fingerprint"] != final_fingerprint:
        raise ValueError(
            "terminal canonical build inputs do not match the convergence receipt chain"
        )
    destination = session_root / _FINAL_BUILD_PROVENANCE
    expected_file_sha256 = _json_artifact_sha256(current)
    if destination.exists():
        if sha256_file(destination) != expected_file_sha256:
            raise ValueError("terminal build provenance snapshot changed")
    else:
        _write_immutable_json(destination, current)
    final = _bind_build_provenance_snapshot(
        root,
        destination,
        expected_file_sha256=expected_file_sha256,
        expected_fingerprint=final_fingerprint,
        expected_scene_spec_sha256=(
            receipts[-1][0].canonical_scene_spec_sha256
            if receipts
            else plan.initial_scene_spec_sha256
        ),
        expected_camera_fingerprint=plan.camera_fingerprint,
    )
    return initial, final, final_fingerprint


def _terminal_iteration_evidence(
    *,
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> tuple[list[HashBoundConvergenceArtifact], Path, VisualQAReport]:
    """Audit receipt evidence plus the exact final QA request and seven-pass sources."""

    artifacts = _audit_receipt_evidence(
        root=root,
        session_root=session_root,
        plan=plan,
        receipts=receipts,
    )
    current_run, current_report_hash = _current_qa_identity(plan, receipts)
    expected_scene_spec_sha256 = (
        receipts[-1][0].canonical_scene_spec_sha256
        if receipts
        else plan.initial_scene_spec_sha256
    )
    candidate_path = root / "qa" / "runs" / current_run / "revision_candidates.json"
    if not candidate_path.is_file():
        raise ValueError(f"terminal QA candidates are missing: {candidate_path}")
    (
        current_report_path,
        _current_candidates_path,
        current_report,
        _current_candidates,
        current_artifacts,
    ) = _audit_qa_authoritative_evidence(
        root=root,
        job_id=plan.job_id,
        run_id=current_run,
        expected_scene_spec_sha256=expected_scene_spec_sha256,
        expected_report_sha256=current_report_hash,
        expected_candidates_sha256=(
            _current_candidates_sha256(plan, receipts)
            if plan.initial_candidates_sha256 is not None
            else sha256_file(candidate_path)
        ),
        expected_build_fingerprint=(
            _current_build_fingerprint(plan, receipts)
            if plan.initial_build_fingerprint is not None
            else None
        ),
    )
    return (
        _deduplicate_artifacts([*artifacts, *current_artifacts]),
        current_report_path,
        current_report,
    )


def _expected_manual_review(
    termination_reason: ConvergenceTerminationReason,
) -> bool:
    """Return the review requirement implied by one terminal reason."""

    return convergence_manual_review_required(termination_reason)


def _validate_terminal_report_bindings(
    *,
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    plan_sha256: str,
    approval_sha256: str,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
    terminal: VisualConvergenceReport,
) -> list[HashBoundConvergenceArtifact]:
    """Cross-check one terminal summary against plan, receipts, QA, and SceneSpec evidence."""

    iteration_evidence, final_report_path, final_report = _terminal_iteration_evidence(
        root=root,
        session_root=session_root,
        plan=plan,
        receipts=receipts,
    )
    iteration_evidence = _deduplicate_artifacts(
        [
            *_validate_initial_session_snapshots(root, session_root, plan),
            *iteration_evidence,
        ]
    )
    expected_receipts = [
        HashBoundConvergenceArtifact(
            relative_path=path.resolve().relative_to(root.resolve()).as_posix(),
            sha256=receipt_sha256,
        )
        for _receipt, receipt_sha256, path in receipts
    ]
    expected_final_scene_sha256 = (
        receipts[-1][0].canonical_scene_spec_sha256
        if receipts
        else plan.initial_scene_spec_sha256
    )
    exact_checks = {
        "session_id": (terminal.session_id, plan.session_id),
        "job_id": (terminal.job_id, plan.job_id),
        "plan_sha256": (terminal.plan_sha256, plan_sha256),
        "approval_sha256": (terminal.approval_sha256, approval_sha256),
        "input_fingerprint": (terminal.input_fingerprint, plan.input_fingerprint),
        "camera_fingerprint": (terminal.camera_fingerprint, plan.camera_fingerprint),
        "scoring_version": (terminal.scoring_version, plan.scoring_version),
        "initial_scene_spec_sha256": (
            terminal.initial_scene_spec_sha256,
            plan.initial_scene_spec_sha256,
        ),
        "final_scene_spec_sha256": (
            terminal.final_scene_spec_sha256,
            expected_final_scene_sha256,
        ),
        "initial_qa_report_sha256": (
            terminal.initial_qa_report_sha256,
            plan.initial_qa_report_sha256,
        ),
        "initial_candidates_sha256": (
            terminal.initial_candidates_sha256,
            plan.initial_candidates_sha256,
        ),
        "initial_build_fingerprint": (
            terminal.initial_build_fingerprint,
            plan.initial_build_fingerprint,
        ),
        "initial_constraints_present": (
            terminal.initial_constraints_present,
            plan.initial_constraints_present,
        ),
        "initial_constraints_sha256": (
            terminal.initial_constraints_sha256,
            plan.initial_constraints_sha256,
        ),
        "structural_multiview_policy": (
            terminal.structural_multiview_policy,
            plan.structural_multiview_policy,
        ),
        "initial_structural_evidence": (
            terminal.initial_structural_evidence,
            plan.initial_structural_evidence,
        ),
        "final_structural_evidence": (
            terminal.final_structural_evidence,
            _current_structural_evidence(plan, receipts),
        ),
        "structural_regression_iteration_count": (
            terminal.structural_regression_iteration_count,
            sum(
                receipt.structural_multiview_status == "regressed"
                for receipt, _hash, _path in receipts
            ),
        ),
        "final_qa_report_sha256": (
            terminal.final_qa_report_sha256,
            sha256_file(final_report_path),
        ),
        "initial_direct_score": (
            terminal.initial_direct_score,
            plan.initial_direct_score,
        ),
        "final_direct_score": (
            terminal.final_direct_score,
            final_report.direct_metrics.overall_direct_score,
        ),
        "target_direct_score": (
            terminal.target_direct_score,
            plan.target_direct_score,
        ),
        "initial_silhouette_iou": (
            terminal.initial_silhouette_iou,
            plan.initial_silhouette_iou,
        ),
        "final_silhouette_iou": (
            terminal.final_silhouette_iou,
            final_report.direct_metrics.silhouette_iou,
        ),
        "target_silhouette_iou": (
            terminal.target_silhouette_iou,
            plan.target_silhouette_iou,
        ),
        "accepted_iterations": (
            terminal.accepted_iterations,
            sum(receipt.status == "accepted" for receipt, _hash, _path in receipts),
        ),
        "rolled_back_iterations": (
            terminal.rolled_back_iterations,
            sum(receipt.status == "rolled_back" for receipt, _hash, _path in receipts),
        ),
        "iteration_receipts": (terminal.iteration_receipts, expected_receipts),
        "iteration_evidence": (terminal.iteration_evidence, iteration_evidence),
        "remaining_high_finding_ids": (
            terminal.remaining_high_finding_ids,
            _remaining_high_findings(final_report),
        ),
        "manual_review_required": (
            terminal.manual_review_required,
            _expected_manual_review(terminal.termination_reason),
        ),
        "started_at": (terminal.started_at, plan.created_at),
    }
    mismatches = sorted(
        label for label, (actual, expected) in exact_checks.items() if actual != expected
    )
    if mismatches:
        raise ValueError(f"terminal convergence summary mismatch: {mismatches}")
    if terminal.target_reached != (
        terminal.termination_reason == "target_reached"
    ):
        raise ValueError(
            "target_reached and terminal reason identify different outcomes"
        )
    if receipts:
        last_status = receipts[-1][0].status
        allowed_reasons = {
            "accepted": {"target_reached", "iteration_budget_exhausted", "cancelled"},
            "rolled_back": {
                "plateau",
                "constraint_regression",
                "structural_regression",
            },
            "manual_review_required": {
                "manual_review_required",
                "no_eligible_candidates",
            },
            "failed": {"failed", "stale_or_tampered"},
        }[last_status]
        if terminal.termination_reason not in allowed_reasons:
            raise ValueError(
                "terminal reason is inconsistent with the final iteration receipt"
            )
    snapshot = terminal.final_scene_spec_snapshot
    if snapshot is None:
        if plan.initial_input_hashes:
            raise ValueError("new convergence terminal report lacks final SceneSpec snapshot")
    else:
        expected_snapshot_path = (
            session_root / "final_scene_spec.json"
        ).resolve().relative_to(root.resolve()).as_posix()
        if (
            snapshot.relative_path != expected_snapshot_path
            or snapshot.sha256 != expected_final_scene_sha256
        ):
            raise ValueError("terminal final SceneSpec snapshot binding changed")
        _bind_existing_artifact(
            root,
            root / Path(*snapshot.relative_path.split("/")),
            snapshot.sha256,
            label="terminal final SceneSpec snapshot",
        )
    initial_snapshot = terminal.initial_scene_spec_snapshot
    if plan.initial_build_fingerprint is not None:
        expected_initial_path = (
            session_root / _INITIAL_SCENE_SNAPSHOT
        ).resolve().relative_to(root.resolve()).as_posix()
        if (
            initial_snapshot is None
            or initial_snapshot.relative_path != expected_initial_path
            or initial_snapshot.sha256 != plan.initial_scene_spec_sha256
        ):
            raise ValueError("terminal initial SceneSpec snapshot binding changed")
        _bind_existing_artifact(
            root,
            root / Path(*initial_snapshot.relative_path.split("/")),
            initial_snapshot.sha256,
            label="terminal initial SceneSpec snapshot",
        )
        if (
            terminal.initial_build_provenance_snapshot is None
            or terminal.final_build_provenance_snapshot is None
            or terminal.final_build_fingerprint is None
        ):
            raise ValueError("terminal build provenance bindings are incomplete")
        expected_initial_build_path = (
            session_root / _INITIAL_BUILD_PROVENANCE
        ).resolve().relative_to(root.resolve()).as_posix()
        expected_final_build_path = (
            session_root / _FINAL_BUILD_PROVENANCE
        ).resolve().relative_to(root.resolve()).as_posix()
        if (
            terminal.initial_build_provenance_snapshot.relative_path
            != expected_initial_build_path
            or terminal.final_build_provenance_snapshot.relative_path
            != expected_final_build_path
        ):
            raise ValueError(
                "terminal build provenance snapshots moved outside their fixed "
                "session-owned paths"
            )
        _bind_build_provenance_snapshot(
            root,
            root
            / Path(
                *terminal.initial_build_provenance_snapshot.relative_path.split("/")
            ),
            expected_file_sha256=terminal.initial_build_provenance_snapshot.sha256,
            expected_fingerprint=plan.initial_build_fingerprint,
            expected_scene_spec_sha256=plan.initial_scene_spec_sha256,
            expected_camera_fingerprint=plan.camera_fingerprint,
        )
        _bind_build_provenance_snapshot(
            root,
            root
            / Path(
                *terminal.final_build_provenance_snapshot.relative_path.split("/")
            ),
            expected_file_sha256=terminal.final_build_provenance_snapshot.sha256,
            expected_fingerprint=terminal.final_build_fingerprint,
            expected_scene_spec_sha256=expected_final_scene_sha256,
            expected_camera_fingerprint=plan.camera_fingerprint,
        )
        expected_final_build = _current_build_fingerprint(plan, receipts)
        if terminal.final_build_fingerprint != expected_final_build:
            raise ValueError("terminal final build fingerprint changed")
    cancellation = _cancellation_artifact(
        root=root,
        session_root=session_root,
        plan=plan,
        plan_sha256=plan_sha256,
        approval_sha256=approval_sha256,
        receipts=receipts,
    )
    if terminal.cancellation_receipt != cancellation:
        raise ValueError("terminal cancellation receipt binding changed")
    return iteration_evidence


def _session_lock_id(session_id: str) -> str:
    """Map any valid session ID to the existing bounded V0.8 job-lock namespace."""

    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
    return f"conv-{digest}"


def _planned_qa_run_id(parameters: dict[str, Any]) -> str | None:
    """Read the current QA run parameter while accepting one legacy key."""

    current = parameters.get("run_id")
    legacy = parameters.get("qa_run_id")
    if current is not None and legacy is not None and current != legacy:
        raise ValueError(
            "workflow QA step has conflicting run_id and legacy qa_run_id values"
        )
    selected = current if current is not None else legacy
    return selected if isinstance(selected, str) and selected else None


def _qa_step_owns_run(step: dict[str, Any], run_id: str) -> bool:
    """Identify one raw fixed-camera QA step bound to the requested run."""

    parameters = step.get("parameters")
    return (
        step.get("step_id") == "qa.run"
        and step.get("phase") == "qa"
        and step.get("tool_name") == "run_visual_qa"
        and isinstance(parameters, dict)
        and _planned_qa_run_id(parameters) == run_id
    )


def _workflow_receipt_plan_hashes(
    workflow_root: Path,
    *,
    job_id: str,
    run_id: str,
) -> set[str]:
    """Recover immutable V0.8 plan hashes that emitted one exact QA run path."""

    expected_path = f"qa/runs/{run_id}"
    plan_hashes: set[str] = set()
    candidate_paths = [
        workflow_root / "completions" / "qa.run.json",
        *(
            sorted((workflow_root / "attempts" / "qa.run").glob("*.json"))
            if (workflow_root / "attempts" / "qa.run").is_dir()
            else []
        ),
    ]
    for path in candidate_paths:
        if not path.is_file():
            continue
        raw_text = path.read_text(encoding="utf-8")
        try:
            if path.parent.name == "completions":
                receipt = WorkflowStepCompletion.model_validate_json(raw_text)
                artifacts = receipt.output_artifacts
            else:
                attempt = WorkflowAttempt.model_validate_json(raw_text)
                if attempt.status != "succeeded":
                    continue
                receipt = attempt
                artifacts = attempt.outputs
        except ValueError as exc:
            if run_id in raw_text:
                raise ValueError(
                    "workflow QA ownership receipt is malformed or tampered"
                ) from exc
            continue
        if not any(artifact.path == expected_path for artifact in artifacts):
            continue
        if (
            receipt.workflow_id != workflow_root.name
            or receipt.job_id != job_id
            or receipt.step_id != "qa.run"
        ):
            raise ValueError("workflow QA ownership receipt identity changed")
        plan_hashes.add(receipt.plan_sha256)
    return plan_hashes


def _background_fast_qa_owner(
    root: Path,
    job_id: str,
    run_id: str,
) -> str | None:
    """Return the immutable fast workflow that explicitly planned one QA run."""

    workflows_root = root / "workflows"
    if not workflows_root.is_dir():
        return None
    resolved_root = root.resolve()
    for workflow_root in sorted(workflows_root.iterdir()):
        plan_path = workflow_root / "plan.json"
        if not workflow_root.is_dir():
            continue
        receipt_plan_hashes = _workflow_receipt_plan_hashes(
            workflow_root,
            job_id=job_id,
            run_id=run_id,
        )
        if not plan_path.is_file():
            if receipt_plan_hashes:
                raise ValueError(
                    "workflow plan owning the selected initial QA run is missing"
                )
            continue
        resolved_plan = plan_path.resolve()
        try:
            resolved_plan.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(
                "workflow plan escapes the job while checking initial QA ownership"
            ) from exc
        raw = json.loads(resolved_plan.read_text(encoding="utf-8"))
        actual_plan_sha256 = sha256_file(resolved_plan)
        if receipt_plan_hashes and receipt_plan_hashes != {actual_plan_sha256}:
            raise ValueError(
                "workflow plan hash changed after emitting the selected initial QA run"
            )
        matching_raw_step = any(
            _qa_step_owns_run(step, run_id)
            for step in raw.get("steps", [])
            if isinstance(step, dict)
        )
        try:
            workflow_plan = WorkflowPlan.model_validate(raw)
        except ValueError as exc:
            if receipt_plan_hashes or (
                raw.get("execution_policy") == "background_exterior"
                and matching_raw_step
            ):
                raise ValueError(
                    "the workflow that owns the selected initial QA run is malformed"
                ) from exc
            continue
        matching_model_step = any(
            step.step_id == "qa.run"
            and step.phase == "qa"
            and step.tool_name == "run_visual_qa"
            and _planned_qa_run_id(step.parameters) == run_id
            for step in workflow_plan.steps
        )
        if receipt_plan_hashes and not matching_model_step:
            raise ValueError(
                "workflow QA owner step changed after the run was emitted"
            )
        if (
            workflow_plan.execution_policy != "background_exterior"
            or workflow_plan.workflow_id != workflow_root.name
            or workflow_plan.job_id != job_id
        ):
            if receipt_plan_hashes and (
                workflow_plan.workflow_id != workflow_root.name
                or workflow_plan.job_id != job_id
            ):
                raise ValueError("workflow QA owner identity changed after execution")
            continue
        if matching_model_step:
            return workflow_root.name
    return None


def plan_job_visual_convergence(
    job_id: str,
    initial_qa_run_id: str,
    *,
    target_direct_score: float,
    target_silhouette_iou: float,
    allowed_target_ids: list[str] | None = None,
    session_id: str | None = None,
    minimum_iteration_gain: float = 0.001,
    minimum_candidate_confidence: float = 0.8,
    max_iterations: int = 3,
    max_candidate_groups_per_iteration: int = 3,
    max_candidates_per_iteration: int = 12,
    max_changed_ids_per_iteration: int = 6,
    path_limits: list[ConvergencePathLimit] | None = None,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict[str, Any]:
    """Create an exact plan and optional five-view baseline for one user approval."""

    _validate_render_selection(render_engine, render_device)
    selected_session = _validate_session_id(session_id or _new_session_id())
    root, session_root = _session_paths(job_id, selected_session)
    if session_root.exists():
        raise FileExistsError(f"Visual convergence session already exists: {session_root}")
    scene_spec_path = root / "analysis" / "scene_spec.json"
    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    if spec.job_id != job_id:
        raise ValueError("SceneSpec belongs to another job")
    report_path, candidates_path, report, candidates = _qa_evidence(
        root,
        job_id,
        initial_qa_run_id,
        require_current_spec=True,
    )
    fast_owner = _background_fast_qa_owner(root, job_id, initial_qa_run_id)
    if fast_owner is not None:
        raise ValueError(
            "bounded standard convergence cannot consume the canonical QA run owned by "
            f"background_exterior workflow {fast_owner}; run a separate standard/manual "
            "direct-reference QA first"
        )
    if report.generated_target_status not in {"not_requested", "failed"}:
        # Generated evidence may remain in the report, but can never authorize a candidate.
        generated_policy_note = "advisory_generated_evidence_present"
    else:
        generated_policy_note = "direct_reference_only"
    allowed, locked, custom_mesh = _object_sets(spec, allowed_target_ids)
    resolved_path_limits = _bounded_path_limits(spec, path_limits)
    initial_input_hashes = _input_hashes(root)
    initial_build_provenance = _current_build_provenance(root, job_id)
    initial_build_fingerprint = str(initial_build_provenance["fingerprint"])
    initial_build_provenance_sha256 = _json_artifact_sha256(
        initial_build_provenance
    )
    initial_candidates_sha256 = sha256_file(candidates_path)
    constraints_present, constraints_sha256 = _constraint_contract_binding(root)
    _audit_qa_authoritative_evidence(
        root=root,
        job_id=job_id,
        run_id=initial_qa_run_id,
        expected_scene_spec_sha256=sha256_file(scene_spec_path),
        expected_report_sha256=sha256_file(report_path),
        expected_candidates_sha256=initial_candidates_sha256,
        expected_build_fingerprint=initial_build_fingerprint,
    )
    structural_policy = _structural_multiview_policy(job_id)
    initial_structural_evidence = (
        _capture_convergence_structural_terminal(
            job_id,
            root,
            session_id=selected_session,
            phase="initial",
            render_engine=render_engine,
            render_device=render_device,
        )
        if structural_policy == "spatial_v1_required"
        else None
    )
    host_safety_envelope = _host_safety_envelope_payload(
        session_id=selected_session,
        job_id=job_id,
        spec=spec,
        report=report,
        candidates=candidates,
        initial_scene_spec_sha256=sha256_file(scene_spec_path),
        initial_qa_report_sha256=sha256_file(report_path),
        initial_candidates_sha256=initial_candidates_sha256,
        target_direct_score=target_direct_score,
        target_silhouette_iou=target_silhouette_iou,
        minimum_iteration_gain=minimum_iteration_gain,
        minimum_candidate_confidence=minimum_candidate_confidence,
        max_iterations=max_iterations,
        max_candidate_groups_per_iteration=max_candidate_groups_per_iteration,
        max_candidates_per_iteration=max_candidates_per_iteration,
        max_changed_ids_per_iteration=max_changed_ids_per_iteration,
        allowed_target_ids=allowed,
        path_limits=resolved_path_limits,
        structural_multiview_policy=structural_policy,
        initial_structural_evidence=initial_structural_evidence,
    )
    host_safety_envelope_sha256 = _json_artifact_sha256(host_safety_envelope)
    plan = VisualConvergencePlan(
        session_id=selected_session,
        job_id=job_id,
        input_fingerprint=_canonical_sha256(initial_input_hashes),
        initial_input_hashes=initial_input_hashes,
        initial_scene_spec_sha256=sha256_file(scene_spec_path),
        initial_qa_run_id=initial_qa_run_id,
        initial_qa_report_sha256=sha256_file(report_path),
        initial_candidates_sha256=initial_candidates_sha256,
        initial_build_fingerprint=initial_build_fingerprint,
        initial_build_provenance_sha256=initial_build_provenance_sha256,
        host_safety_envelope_sha256=host_safety_envelope_sha256,
        initial_constraints_present=constraints_present,
        initial_constraints_sha256=constraints_sha256,
        camera_fingerprint=report.camera_fingerprint,
        scoring_version=report.direct_metrics.scoring_version,
        initial_direct_score=report.direct_metrics.overall_direct_score,
        initial_silhouette_iou=report.direct_metrics.silhouette_iou,
        target_direct_score=target_direct_score,
        target_silhouette_iou=target_silhouette_iou,
        minimum_iteration_gain=minimum_iteration_gain,
        minimum_candidate_confidence=minimum_candidate_confidence,
        max_iterations=max_iterations,
        max_candidate_groups_per_iteration=max_candidate_groups_per_iteration,
        max_candidates_per_iteration=max_candidates_per_iteration,
        max_changed_ids_per_iteration=max_changed_ids_per_iteration,
        allowed_target_ids=allowed,
        locked_target_ids=locked,
        custom_mesh_target_ids=custom_mesh,
        path_limits=resolved_path_limits,
        allow_material_edits=False,
        structural_multiview_policy=structural_policy,
        initial_structural_evidence=initial_structural_evidence,
        created_at=_utc_now(),
    )
    _validate_plan_input_binding(plan)
    if candidates.base_spec_sha256 != plan.initial_scene_spec_sha256:
        raise ValueError("initial candidates do not bind to the planned SceneSpec")
    session_root.mkdir(parents=True, exist_ok=False)
    host_safety_path = session_root / _HOST_SAFETY_ENVELOPE
    _write_immutable_json(host_safety_path, host_safety_envelope)
    if sha256_file(host_safety_path) != plan.host_safety_envelope_sha256:
        raise RuntimeError(
            "host safety envelope changed while creating convergence plan"
        )
    initial_scene_snapshot_sha256 = _write_immutable_copy(
        scene_spec_path,
        session_root / _INITIAL_SCENE_SNAPSHOT,
    )
    if initial_scene_snapshot_sha256 != plan.initial_scene_spec_sha256:
        raise RuntimeError("initial SceneSpec changed while creating convergence plan")
    initial_build_path = session_root / _INITIAL_BUILD_PROVENANCE
    _write_immutable_json(initial_build_path, initial_build_provenance)
    if sha256_file(initial_build_path) != plan.initial_build_provenance_sha256:
        raise RuntimeError(
            "initial build provenance changed while creating convergence plan"
        )
    if constraints_present:
        constraints_path = root / "constraints" / "constraints.json"
        snapshot_sha256 = _write_immutable_copy(
            constraints_path,
            session_root / _INITIAL_CONSTRAINTS_SNAPSHOT,
        )
        if snapshot_sha256 != constraints_sha256:
            raise RuntimeError(
                "constraint contract changed while creating convergence plan"
            )
    plan_path = session_root / "plan.json"
    _write_immutable_json(plan_path, plan.model_dump(mode="json"))
    return {
        "ok": True,
        "status": "waiting_for_exact_approval",
        "job_id": job_id,
        "session_id": selected_session,
        "plan": str(plan_path),
        "plan_sha256": sha256_file(plan_path),
        "initial_qa_run_id": initial_qa_run_id,
        "initial_direct_score": plan.initial_direct_score,
        "initial_silhouette_iou": plan.initial_silhouette_iou,
        "target_direct_score": plan.target_direct_score,
        "target_silhouette_iou": plan.target_silhouette_iou,
        "max_iterations": plan.max_iterations,
        "minimum_iteration_gain": plan.minimum_iteration_gain,
        "minimum_candidate_confidence": plan.minimum_candidate_confidence,
        "max_candidate_groups_per_iteration": (
            plan.max_candidate_groups_per_iteration
        ),
        "max_candidates_per_iteration": plan.max_candidates_per_iteration,
        "max_changed_ids_per_iteration": plan.max_changed_ids_per_iteration,
        "allowed_target_ids": plan.allowed_target_ids,
        "locked_target_ids": plan.locked_target_ids,
        "path_limits": [
            item.model_dump(mode="json") for item in plan.path_limits
        ],
        "host_safety_envelope": str(host_safety_path),
        "host_safety_envelope_sha256": plan.host_safety_envelope_sha256,
        "generated_target_policy": generated_policy_note,
        "structural_multiview_policy": plan.structural_multiview_policy,
        "initial_structural_evidence": (
            plan.initial_structural_evidence.model_dump(mode="json")
            if plan.initial_structural_evidence is not None
            else None
        ),
        "canonical_modified": False,
        "approval_required": True,
    }


def approve_job_visual_convergence(
    job_id: str,
    session_id: str,
    *,
    plan_sha256: str,
    approval_note: str,
) -> dict[str, Any]:
    """Record one explicit immutable approval for the exact bounded session plan."""

    root, session_root = _session_paths(job_id, session_id)
    plan_path = session_root / "plan.json"
    approval_path = session_root / "approval.json"
    if not plan_path.is_file():
        raise FileNotFoundError(f"Visual convergence plan is missing: {plan_path}")
    if approval_path.exists():
        raise FileExistsError(f"Visual convergence approval already exists: {approval_path}")
    actual_plan_sha256 = sha256_file(plan_path)
    if actual_plan_sha256 != plan_sha256:
        raise ValueError("visual convergence approval does not match the exact plan SHA-256")
    plan = _load_plan(plan_path)
    if plan.job_id != job_id or plan.session_id != session_id:
        raise ValueError("visual convergence plan identity mismatch")
    _require_executable_plan_bindings(plan)
    _validate_plan_input_binding(plan)
    _validate_initial_session_snapshots(root, session_root, plan)
    _require_host_safety_envelope(root, session_root, plan)
    scene_spec_path = root / "analysis" / "scene_spec.json"
    if sha256_file(scene_spec_path) != plan.initial_scene_spec_sha256:
        raise ValueError("SceneSpec changed after visual convergence planning")
    if _input_fingerprint(root) != plan.input_fingerprint:
        raise ValueError("immutable input evidence changed after convergence planning")
    _require_constraint_contract(root, plan)
    current_build = _current_build_provenance(root, job_id)
    if current_build["fingerprint"] != plan.initial_build_fingerprint:
        raise ValueError("canonical build inputs changed after convergence planning")
    report_path, candidate_path, report, _candidates = _qa_evidence(
        root,
        job_id,
        plan.initial_qa_run_id,
        require_current_spec=True,
    )
    if sha256_file(report_path) != plan.initial_qa_report_sha256:
        raise ValueError("initial QA report changed after convergence planning")
    if report.camera_fingerprint != plan.camera_fingerprint:
        raise ValueError("comparison camera changed after convergence planning")
    if (
        plan.initial_candidates_sha256 is None
        or sha256_file(candidate_path) != plan.initial_candidates_sha256
    ):
        raise ValueError("initial QA candidates changed after convergence planning")
    _audit_qa_authoritative_evidence(
        root=root,
        job_id=job_id,
        run_id=plan.initial_qa_run_id,
        expected_scene_spec_sha256=plan.initial_scene_spec_sha256,
        expected_report_sha256=plan.initial_qa_report_sha256,
        expected_candidates_sha256=plan.initial_candidates_sha256,
        expected_build_fingerprint=str(plan.initial_build_fingerprint),
    )
    approval = VisualConvergenceApproval(
        approval_id=f"approval-{uuid4().hex}",
        session_id=session_id,
        job_id=job_id,
        plan_sha256=actual_plan_sha256,
        input_fingerprint=plan.input_fingerprint,
        initial_scene_spec_sha256=plan.initial_scene_spec_sha256,
        initial_qa_report_sha256=plan.initial_qa_report_sha256,
        initial_candidates_sha256=plan.initial_candidates_sha256,
        initial_build_fingerprint=plan.initial_build_fingerprint,
        initial_build_provenance_sha256=plan.initial_build_provenance_sha256,
        host_safety_envelope_sha256=plan.host_safety_envelope_sha256,
        initial_constraints_present=plan.initial_constraints_present,
        initial_constraints_sha256=plan.initial_constraints_sha256,
        camera_fingerprint=plan.camera_fingerprint,
        structural_multiview_policy=plan.structural_multiview_policy,
        initial_structural_evidence=plan.initial_structural_evidence,
        approval_note=approval_note,
        approved_at=_utc_now(),
    )
    validate_convergence_activation(
        plan,
        approval,
        plan_sha256=actual_plan_sha256,
    )
    _write_immutable_json(approval_path, approval.model_dump(mode="json"))
    return {
        "ok": True,
        "status": "approved_bounded_session",
        "job_id": job_id,
        "session_id": session_id,
        "plan_sha256": actual_plan_sha256,
        "approval": str(approval_path),
        "approval_sha256": sha256_file(approval_path),
        "max_iterations": plan.max_iterations,
        "authorization_scope": approval.authorization_scope,
    }


def _write_iteration_receipt(
    path: Path,
    receipt: VisualConvergenceIteration,
) -> tuple[VisualConvergenceIteration, str, Path]:
    """Persist one immutable iteration receipt and return its exact hash tuple."""

    _write_immutable_json(path, receipt.model_dump(mode="json"))
    return receipt, sha256_file(path), path


def _cancellation_artifact(
    *,
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    plan_sha256: str,
    approval_sha256: str,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> HashBoundConvergenceArtifact | None:
    """Validate and bind the immutable cancellation marker when one exists."""

    path = session_root / _CANCELLATION_RECEIPT
    if not path.is_file():
        return None
    cancellation = _load_cancellation(path)
    current_run, current_report_sha256 = _current_qa_identity(plan, receipts)
    current_candidates_sha256 = (
        _current_candidates_sha256(plan, receipts)
        if plan.initial_candidates_sha256 is not None
        else cancellation.current_candidates_sha256
    )
    current_build_fingerprint = (
        _current_build_fingerprint(plan, receipts)
        if plan.initial_build_fingerprint is not None
        else cancellation.current_build_fingerprint
    )
    expected_previous = receipts[-1][1] if receipts else None
    expected_scene_sha256 = (
        receipts[-1][0].canonical_scene_spec_sha256
        if receipts
        else plan.initial_scene_spec_sha256
    )
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
            expected_scene_sha256,
        ),
        "current_qa_run_id": (cancellation.current_qa_run_id, current_run),
        "current_qa_report_sha256": (
            cancellation.current_qa_report_sha256,
            current_report_sha256,
        ),
        "current_candidates_sha256": (
            cancellation.current_candidates_sha256,
            current_candidates_sha256,
        ),
        "current_build_fingerprint": (
            cancellation.current_build_fingerprint,
            current_build_fingerprint,
        ),
        "previous_iteration_receipt_sha256": (
            cancellation.previous_iteration_receipt_sha256,
            expected_previous,
        ),
    }
    mismatches = sorted(
        key for key, (actual, expected) in checks.items() if actual != expected
    )
    if mismatches:
        raise ValueError(
            f"visual convergence cancellation binding mismatch: {mismatches}"
        )
    return _bind_existing_artifact(
        root,
        path,
        sha256_file(path),
        label="visual convergence cancellation receipt",
    )


def _terminal_report(
    *,
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    plan_sha256: str,
    approval_sha256: str,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
    final_report_path: Path,
    termination_reason: Literal[
        "target_reached",
        "plateau",
        "no_eligible_candidates",
        "manual_review_required",
        "iteration_budget_exhausted",
        "constraint_regression",
        "structural_regression",
        "stale_or_tampered",
        "cancelled",
        "failed",
    ],
    reasons: list[str],
) -> dict[str, Any]:
    """Write terminal JSON/PDF evidence without mutating the immutable approval."""

    output_path = session_root / _TERMINAL_REPORT
    if output_path.exists():
        raise RuntimeError(
            "immutable convergence terminal report already exists; use status instead"
        )
    _require_no_incomplete_iteration_before_terminal(session_root)
    _load_authoritative_activation(
        session_root,
        job_id=plan.job_id,
        session_id=plan.session_id,
        expected_plan_sha256=plan_sha256,
        expected_approval_sha256=approval_sha256,
    )
    _require_original_input_hashes(root, plan)
    _require_constraint_contract(root, plan)
    initial_session_artifacts = _validate_initial_session_snapshots(
        root,
        session_root,
        plan,
    )
    expected_final_scene_sha256 = (
        receipts[-1][0].canonical_scene_spec_sha256
        if receipts
        else plan.initial_scene_spec_sha256
    )
    final_scene_snapshot = _terminal_scene_snapshot(
        root=root,
        session_root=session_root,
        expected_scene_spec_sha256=expected_final_scene_sha256,
    )
    initial_scene_snapshot = next(
        (
            artifact
            for artifact in initial_session_artifacts
            if artifact.relative_path.endswith(f"/{_INITIAL_SCENE_SNAPSHOT}")
        ),
        None,
    )
    (
        initial_build_snapshot,
        final_build_snapshot,
        final_build_fingerprint,
    ) = _terminal_build_provenance_snapshot(
        root=root,
        session_root=session_root,
        plan=plan,
        receipts=receipts,
    )
    iteration_evidence, audited_final_report_path, final = (
        _terminal_iteration_evidence(
            root=root,
            session_root=session_root,
            plan=plan,
            receipts=receipts,
        )
    )
    if final_report_path.resolve() != audited_final_report_path.resolve():
        raise ValueError("terminal QA report is not the current exact convergence run")
    target_reached = _target_reached(plan, final)
    if target_reached:
        termination_reason = "target_reached"
    cancellation_artifact = _cancellation_artifact(
        root=root,
        session_root=session_root,
        plan=plan,
        plan_sha256=plan_sha256,
        approval_sha256=approval_sha256,
        receipts=receipts,
    )
    if termination_reason == "cancelled" and cancellation_artifact is None:
        raise ValueError("cancelled convergence session lacks a durable cancellation receipt")
    if termination_reason != "cancelled" and cancellation_artifact is not None:
        raise ValueError(
            "a cancellation receipt exists for a non-cancelled convergence outcome"
        )
    iteration_evidence = _deduplicate_artifacts(
        [*initial_session_artifacts, *iteration_evidence]
    )
    receipt_artifacts = [
        HashBoundConvergenceArtifact(
            relative_path=path.relative_to(root).as_posix(),
            sha256=receipt_sha256,
        )
        for _receipt, receipt_sha256, path in receipts
    ]
    final_structural_evidence = _current_structural_evidence(plan, receipts)
    report = VisualConvergenceReport(
        session_id=plan.session_id,
        job_id=plan.job_id,
        plan_sha256=plan_sha256,
        approval_sha256=approval_sha256,
        input_fingerprint=plan.input_fingerprint,
        camera_fingerprint=plan.camera_fingerprint,
        scoring_version=plan.scoring_version,
        initial_scene_spec_sha256=plan.initial_scene_spec_sha256,
        initial_scene_spec_snapshot=initial_scene_snapshot,
        final_scene_spec_sha256=expected_final_scene_sha256,
        final_scene_spec_snapshot=final_scene_snapshot,
        initial_qa_report_sha256=plan.initial_qa_report_sha256,
        initial_candidates_sha256=plan.initial_candidates_sha256,
        final_qa_report_sha256=sha256_file(final_report_path),
        initial_build_fingerprint=plan.initial_build_fingerprint,
        final_build_fingerprint=final_build_fingerprint,
        initial_build_provenance_snapshot=initial_build_snapshot,
        final_build_provenance_snapshot=final_build_snapshot,
        initial_constraints_present=plan.initial_constraints_present,
        initial_constraints_sha256=plan.initial_constraints_sha256,
        structural_multiview_policy=plan.structural_multiview_policy,
        initial_structural_evidence=plan.initial_structural_evidence,
        final_structural_evidence=final_structural_evidence,
        structural_regression_iteration_count=sum(
            receipt.structural_multiview_status == "regressed"
            for receipt, _hash, _path in receipts
        ),
        cancellation_receipt=cancellation_artifact,
        initial_direct_score=plan.initial_direct_score,
        final_direct_score=final.direct_metrics.overall_direct_score,
        target_direct_score=plan.target_direct_score,
        initial_silhouette_iou=plan.initial_silhouette_iou,
        final_silhouette_iou=final.direct_metrics.silhouette_iou,
        target_silhouette_iou=plan.target_silhouette_iou,
        iteration_receipts=receipt_artifacts,
        iteration_evidence=iteration_evidence,
        accepted_iterations=sum(
            receipt.status == "accepted" for receipt, _hash, _path in receipts
        ),
        rolled_back_iterations=sum(
            receipt.status == "rolled_back" for receipt, _hash, _path in receipts
        ),
        termination_reason=termination_reason,
        target_reached=target_reached,
        manual_review_required=_expected_manual_review(termination_reason),
        remaining_high_finding_ids=_remaining_high_findings(final),
        reasons=reasons or [f"Session ended with {termination_reason}."],
        started_at=plan.created_at,
        completed_at=_utc_now(),
    )
    _require_original_input_hashes(root, plan)
    _load_authoritative_activation(
        session_root,
        job_id=plan.job_id,
        session_id=plan.session_id,
        expected_plan_sha256=plan_sha256,
        expected_approval_sha256=approval_sha256,
    )
    _write_immutable_json(output_path, report.model_dump(mode="json"))
    relative_sources = sorted(
        {
        (session_root / "plan.json").relative_to(root).as_posix(),
        (session_root / "approval.json").relative_to(root).as_posix(),
        *[artifact.relative_path for artifact in iteration_evidence],
        final_scene_snapshot.relative_path,
        *(
            [final_build_snapshot.relative_path]
            if final_build_snapshot is not None
            else []
        ),
        final_report_path.relative_to(root).as_posix(),
        *(
            [cancellation_artifact.relative_path]
            if cancellation_artifact is not None
            else []
        ),
        }
    )
    pdf = generate_visual_convergence_pdf_report(
        plan.job_id,
        plan.session_id,
        source_relative_paths=relative_sources,
    )
    return {
        "ok": True,
        "status": "terminal",
        "job_id": plan.job_id,
        "session_id": plan.session_id,
        "termination_reason": report.termination_reason,
        "target_reached": report.target_reached,
        "manual_review_required": report.manual_review_required,
        "final_direct_score": report.final_direct_score,
        "final_silhouette_iou": report.final_silhouette_iou,
        "accepted_iterations": report.accepted_iterations,
        "rolled_back_iterations": report.rolled_back_iterations,
        "report": str(output_path),
        "report_sha256": sha256_file(output_path),
        "pdf": pdf["pdf"],
        "pdf_manifest": pdf["manifest"],
    }


def _ensure_terminal_pdf(
    *,
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    receipts: list[tuple[VisualConvergenceIteration, str, Path]],
) -> None:
    """Regenerate only a missing derived PDF pair for an existing terminal JSON report."""

    pdf_path = session_root / "convergence_report.pdf"
    manifest_path = session_root / "convergence_report.manifest.json"
    if pdf_path.is_file() and manifest_path.is_file():
        return
    if pdf_path.exists() or manifest_path.exists():
        raise RuntimeError(
            "Visual convergence PDF pair is incomplete; refusing to overwrite evidence"
        )
    terminal_path = session_root / _TERMINAL_REPORT
    terminal = VisualConvergenceReport.model_validate_json(
        terminal_path.read_text(encoding="utf-8")
    )
    initial_session_artifacts = _validate_initial_session_snapshots(
        root,
        session_root,
        plan,
    )
    iteration_evidence, current_report_path, _current_report = (
        _terminal_iteration_evidence(
            root=root,
            session_root=session_root,
            plan=plan,
            receipts=receipts,
        )
    )
    final_scene_sha256 = (
        receipts[-1][0].canonical_scene_spec_sha256
        if receipts
        else plan.initial_scene_spec_sha256
    )
    final_scene_snapshot = _terminal_scene_snapshot(
        root=root,
        session_root=session_root,
        expected_scene_spec_sha256=final_scene_sha256,
    )
    source_paths = sorted(
        {
        (session_root / "plan.json").relative_to(root).as_posix(),
        (session_root / "approval.json").relative_to(root).as_posix(),
        *[artifact.relative_path for artifact in initial_session_artifacts],
        *[artifact.relative_path for artifact in iteration_evidence],
        final_scene_snapshot.relative_path,
        current_report_path.relative_to(root).as_posix(),
        *(
            [terminal.final_build_provenance_snapshot.relative_path]
            if terminal.final_build_provenance_snapshot is not None
            else []
        ),
        *(
            [terminal.cancellation_receipt.relative_path]
            if terminal.cancellation_receipt is not None
            else []
        ),
        }
    )
    generate_visual_convergence_pdf_report(
        plan.job_id,
        plan.session_id,
        source_relative_paths=source_paths,
    )


def _validate_active_state(
    root: Path,
    session_root: Path,
    plan: VisualConvergencePlan,
    plan_sha256: str,
    approval: VisualConvergenceApproval,
    approval_sha256: str,
) -> list[tuple[VisualConvergenceIteration, str, Path]]:
    """Reconstruct active state from immutable receipts and reject stale sources."""

    consumed_artifacts = sorted(
        name
        for name in _TERMINAL_DERIVED_ARTIFACTS
        if (session_root / name).exists()
    )
    if consumed_artifacts:
        raise RuntimeError(
            "visual convergence approval already has terminal convergence receipt "
            "or cancellation receipt evidence and cannot resume: "
            f"{consumed_artifacts}"
        )
    _require_executable_plan_bindings(plan)
    validate_convergence_activation(plan, approval, plan_sha256=plan_sha256)
    _require_original_input_hashes(root, plan)
    _validate_initial_session_snapshots(root, session_root, plan)
    _require_host_safety_envelope(root, session_root, plan)
    _require_constraint_contract(root, plan)
    receipt_records = _load_receipts(session_root)
    validate_iteration_receipt_chain(
        plan,
        approval,
        plan_sha256=plan_sha256,
        approval_sha256=approval_sha256,
        receipts=[(receipt, receipt_hash) for receipt, receipt_hash, _path in receipt_records],
    )
    _audit_receipt_evidence(
        root=root,
        session_root=session_root,
        plan=plan,
        receipts=receipt_records,
    )
    if receipt_records and receipt_records[-1][0].status != "accepted":
        raise RuntimeError(
            "a terminal convergence receipt exists without its terminal report; "
            "refusing to resume or consume further approval authority"
        )
    expected_spec_hash = (
        receipt_records[-1][0].canonical_scene_spec_sha256
        if receipt_records
        else plan.initial_scene_spec_sha256
    )
    if sha256_file(root / "analysis" / "scene_spec.json") != expected_spec_hash:
        raise ValueError(
            "canonical SceneSpec does not match the immutable convergence receipt chain"
        )
    current_run, current_report_hash = _current_qa_identity(plan, receipt_records)
    report_path, candidate_path, report, _candidates = _qa_evidence(
        root,
        plan.job_id,
        current_run,
        require_current_spec=True,
    )
    if sha256_file(report_path) != current_report_hash:
        raise ValueError("current exact QA report changed after convergence receipt")
    if (
        report.camera_fingerprint != plan.camera_fingerprint
        or report.direct_metrics.scoring_version != plan.scoring_version
    ):
        raise ValueError("camera or direct scoring contract changed during convergence")
    expected_candidates_sha256 = (
        _current_candidates_sha256(plan, receipt_records)
        if plan.initial_candidates_sha256 is not None
        else sha256_file(candidate_path)
    )
    if sha256_file(candidate_path) != expected_candidates_sha256:
        raise ValueError("current exact QA candidates changed after convergence receipt")
    expected_build_fingerprint = (
        _current_build_fingerprint(plan, receipt_records)
        if plan.initial_build_fingerprint is not None
        else None
    )
    if expected_build_fingerprint is not None:
        current_build = _current_build_provenance(root, plan.job_id)
        if current_build["fingerprint"] != expected_build_fingerprint:
            raise ValueError(
                "canonical build inputs changed after convergence receipt"
            )
    _audit_qa_authoritative_evidence(
        root=root,
        job_id=plan.job_id,
        run_id=current_run,
        expected_scene_spec_sha256=expected_spec_hash,
        expected_report_sha256=current_report_hash,
        expected_candidates_sha256=expected_candidates_sha256,
        expected_build_fingerprint=expected_build_fingerprint,
    )
    return receipt_records


def run_job_visual_convergence(
    job_id: str,
    session_id: str,
    *,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict[str, Any]:
    """Run or resume at most one approved full iteration per host invocation."""

    _validate_render_selection(render_engine, render_device)
    root, session_root = _session_paths(job_id, session_id)
    plan_path = session_root / "plan.json"
    approval_path = session_root / "approval.json"
    for required in (plan_path, approval_path):
        if not required.is_file():
            raise FileNotFoundError(f"Convergence activation artifact is missing: {required}")
    lock_id = _session_lock_id(session_id)
    with workflow_write_lock(
        root,
        job_id,
        lock_id,
        ttl_seconds=86400,
    ):
        (
            plan,
            approval,
            plan_sha256,
            approval_sha256,
        ) = _load_authoritative_activation(
            session_root,
            job_id=job_id,
            session_id=session_id,
        )
        if (session_root / _TERMINAL_REPORT).is_file():
            terminal_status = get_job_visual_convergence_status(job_id, session_id)
            if not terminal_status["ok"]:
                raise ValueError(
                    "terminal convergence evidence is stale or tampered; "
                    f"refusing derived PDF recovery: {terminal_status['integrity_error']}"
                )
            receipts = _load_receipts(session_root)
            _ensure_terminal_pdf(
                root=root,
                session_root=session_root,
                plan=plan,
                receipts=receipts,
            )
            return _execution_response(
                get_job_visual_convergence_status(job_id, session_id),
                outcome="already_terminal",
                iterations_executed=0,
                next_action=None,
            )
        recovered = _recover_incomplete_iteration(
            root=root,
            session_root=session_root,
            plan=plan,
            plan_sha256=plan_sha256,
            approval=approval,
            approval_sha256=approval_sha256,
            render_engine=render_engine,
            render_device=render_device,
        )
        if recovered is not None:
            status = get_job_visual_convergence_status(job_id, session_id)
            return _execution_response(
                {**status, **recovered},
                outcome="interrupted_attempt_recovered",
                iterations_executed=0,
                next_action="invoke_run_again",
            )
        receipts = _validate_active_state(
            root,
            session_root,
            plan,
            plan_sha256,
            approval,
            approval_sha256,
        )
        current_run, current_report_hash = _current_qa_identity(plan, receipts)
        current_report_path, current_candidates_path, current_report, candidates = (
            _qa_evidence(
                root,
                job_id,
                current_run,
                require_current_spec=True,
            )
        )
        if sha256_file(current_report_path) != current_report_hash:
            raise ValueError("active QA report changed before convergence execution")
        expected_current_candidates_sha256 = (
            _current_candidates_sha256(plan, receipts)
            if plan.initial_candidates_sha256 is not None
            else sha256_file(current_candidates_path)
        )
        if sha256_file(current_candidates_path) != expected_current_candidates_sha256:
            raise ValueError("active QA candidates changed before convergence execution")
        if _target_reached(plan, current_report):
            return _execution_response(
                _terminal_report(
                    root=root,
                    session_root=session_root,
                    plan=plan,
                    plan_sha256=plan_sha256,
                    approval_sha256=approval_sha256,
                    receipts=receipts,
                    final_report_path=current_report_path,
                    termination_reason="target_reached",
                    reasons=[
                        "The approved direct-score and silhouette targets were reached."
                    ],
                ),
                outcome="target_already_reached",
                iterations_executed=0,
                next_action=None,
            )

        while len(receipts) < plan.max_iterations:
            _require_original_input_hashes(root, plan)
            iteration_index = len(receipts) + 1
            committed_root = (
                session_root / "iterations" / f"{iteration_index:03d}"
            )
            iteration_root = (
                session_root / _ITERATION_STAGING_DIR / f"{iteration_index:03d}"
            )
            if committed_root.exists() or iteration_root.exists():
                raise RuntimeError(
                    "Incomplete or unexpected convergence iteration evidence exists: "
                    f"{committed_root if committed_root.exists() else iteration_root}"
                )
            iteration_root.mkdir(parents=True, exist_ok=False)
            scene_spec_path = root / "analysis" / "scene_spec.json"
            base_spec_sha256 = sha256_file(scene_spec_path)
            base_snapshot_sha256 = _write_immutable_copy(
                scene_spec_path,
                iteration_root / "base_scene_spec.json",
            )
            if base_snapshot_sha256 != base_spec_sha256:
                raise RuntimeError("iteration base SceneSpec changed during snapshot")
            latest_snapshot = _snapshot_latest(root)
            if latest_snapshot is not None:
                latest_snapshot_path = iteration_root / _LATEST_POINTER_SNAPSHOT
                latest_snapshot_path.write_bytes(latest_snapshot)
            candidates_sha256 = sha256_file(current_candidates_path)
            expected_candidates_sha256 = (
                _current_candidates_sha256(plan, receipts)
                if plan.initial_candidates_sha256 is not None
                else candidates_sha256
            )
            if candidates_sha256 != expected_candidates_sha256:
                raise ValueError(
                    "iteration candidates changed outside the approved receipt chain"
                )
            source_build_fingerprint = (
                _current_build_fingerprint(plan, receipts)
                if plan.initial_build_fingerprint is not None
                else None
            )
            source_build: dict[str, Any] | None = None
            if source_build_fingerprint is not None:
                source_build = _current_build_provenance(root, job_id)
                if source_build["fingerprint"] != source_build_fingerprint:
                    raise ValueError(
                        "iteration build inputs changed outside the approved receipt chain"
                    )
            if source_build_fingerprint is None:
                raise RuntimeError(
                    "executable convergence iteration lacks source build provenance"
                )
            source_structural_evidence = _current_structural_evidence(plan, receipts)
            if plan.structural_multiview_policy == "spatial_v1_required":
                if source_structural_evidence is None:
                    raise ValueError(
                        "spatial convergence iteration lacks an exact five-view baseline"
                    )
                _structural_terminal_artifacts(
                    root,
                    source_structural_evidence,
                    expected_job_id=job_id,
                    expected_scene_spec_sha256=base_spec_sha256,
                )
            attempt_payload = _iteration_attempt_payload(
                plan=plan,
                plan_sha256=plan_sha256,
                approval_sha256=approval_sha256,
                iteration_index=iteration_index,
                previous_receipt_sha256=(
                    receipts[-1][1] if receipts else None
                ),
                base_scene_spec_sha256=base_spec_sha256,
                base_scene_spec_snapshot_sha256=base_snapshot_sha256,
                source_qa_run_id=current_run,
                source_qa_report_sha256=sha256_file(current_report_path),
                candidates_sha256=candidates_sha256,
                source_build_fingerprint=source_build_fingerprint,
                latest_pointer_snapshot=latest_snapshot,
            )
            _write_immutable_json(
                iteration_root / _ITERATION_ATTEMPT,
                attempt_payload,
            )
            _require_constraint_contract(root, plan)
            report_sha256 = sha256_file(current_report_path)
            selection = select_convergence_candidates(
                plan,
                candidates,
                candidates_sha256=candidates_sha256,
                expected_base_scene_spec_sha256=base_spec_sha256,
                expected_source_qa_report_sha256=report_sha256,
                baseline_values=_candidate_baselines(scene_spec_path, candidates),
            )
            selection_path = iteration_root / "selection.json"
            _write_immutable_json(selection_path, selection.model_dump(mode="json"))
            selection_file_sha256 = sha256_file(selection_path)
            previous_hash = receipts[-1][1] if receipts else None
            before_score = current_report.direct_metrics.overall_direct_score
            before_iou = current_report.direct_metrics.silhouette_iou
            if not selection.selected_candidate_ids:
                manual = _selection_requires_manual(selection)
                receipt = VisualConvergenceIteration(
                    session_id=session_id,
                    job_id=job_id,
                    iteration_index=iteration_index,
                    plan_sha256=plan_sha256,
                    approval_sha256=approval_sha256,
                    previous_iteration_receipt_sha256=previous_hash,
                    input_fingerprint=plan.input_fingerprint,
                    base_scene_spec_sha256=base_spec_sha256,
                    base_scene_spec_snapshot_sha256=base_snapshot_sha256,
                    source_qa_run_id=current_run,
                    source_qa_report_sha256=report_sha256,
                    candidates_sha256=candidates_sha256,
                    source_build_fingerprint=source_build_fingerprint,
                    selection_sha256=selection_file_sha256,
                    selected_candidate_ids=[],
                    before_direct_score=before_score,
                    before_silhouette_iou=before_iou,
                    canonical_scene_spec_sha256=base_spec_sha256,
                    status="manual_review_required",
                    reason_codes=[
                        "manual_review_required"
                        if manual
                        else "no_eligible_candidates"
                    ],
                    completed_at=_utc_now(),
                )
                receipts.append(
                    _commit_iteration_receipt(session_root, iteration_root, receipt)
                )
                return _execution_response(
                    _terminal_report(
                        root=root,
                        session_root=session_root,
                        plan=plan,
                        plan_sha256=plan_sha256,
                        approval_sha256=approval_sha256,
                        receipts=receipts,
                        final_report_path=current_report_path,
                        termination_reason=(
                            "manual_review_required"
                            if manual
                            else "no_eligible_candidates"
                        ),
                        reasons=[
                            "No candidate remained inside the approved automatic-edit "
                            "envelope.",
                            "Rejected candidates remain available for the manual guarded "
                            "flow.",
                        ],
                    ),
                    outcome="iteration_completed_terminal",
                    iterations_executed=1,
                    next_action=None,
                )

            compiled_plan_path = iteration_root / "revision_plan.json"
            compiled = compile_revision_plan(
                candidates_path=current_candidates_path,
                scene_spec_path=scene_spec_path,
                selected_candidate_ids=selection.selected_candidate_ids,
                request=(
                    f"Bounded visual convergence session {session_id}, "
                    f"iteration {iteration_index}."
                ),
                output_path=compiled_plan_path,
                authorization_assumption=(
                    "Only host-policy candidates selected inside the exact user-approved "
                    "bounded visual-convergence envelope may be applied."
                ),
            )
            compiled_plan_sha256 = sha256_file(compiled_plan_path)
            authorization = VisualConvergenceIterationAuthorization(
                authorization_id=f"iter-auth-{uuid4().hex}",
                session_id=session_id,
                job_id=job_id,
                iteration_index=iteration_index,
                plan_sha256=plan_sha256,
                approval_sha256=approval_sha256,
                base_scene_spec_sha256=base_spec_sha256,
                source_qa_report_sha256=report_sha256,
                candidates_sha256=candidates_sha256,
                source_build_fingerprint=source_build_fingerprint,
                selection_sha256=selection_file_sha256,
                compiled_plan_sha256=compiled_plan_sha256,
                selected_candidate_ids=selection.selected_candidate_ids,
                created_at=_utc_now(),
            )
            authorization_path = iteration_root / "authorization.json"
            _write_immutable_json(
                authorization_path,
                authorization.model_dump(mode="json"),
            )
            authorization_sha256 = sha256_file(authorization_path)
            changed_ids, preserved_ids = _semantic_change_sets(
                scene_spec_path,
                candidates,
                selection.selected_candidate_ids,
            )
            expected_input_hashes = (
                dict(plan.initial_input_hashes)
                if plan.initial_input_hashes
                else _input_hashes(root)
            )
            archived: Path | None = None
            before_constraints: dict[str, Any] = {"failures": 0, "results": []}
            next_spec_path = iteration_root / "scene_spec.next.json"
            result_spec_sha256: str | None = None
            result_run: str | None = None
            result_report_path: Path | None = None
            result_candidates_path: Path | None = None
            result_build_fingerprint: str | None = None
            result_build_provenance_sha256: str | None = None
            result_structural_evidence: AssemblySanityTerminalEvidence | None = None
            structural_comparison: StructuralRegressionReport | None = None
            structural_comparison_path: Path | None = None
            structural_comparison_relative_path: str | None = None
            structural_comparison_sha256: str | None = None
            before_constraints_sha256: str | None = None
            after_constraints_sha256: str | None = None
            pipeline: dict[str, Any] | None = None
            try:
                before_constraints = _baseline_constraint_state(
                    job_id,
                    root,
                    render_engine,
                    render_device,
                )
                before_constraints_sha256 = _write_constraint_evidence(
                    iteration_root / "before_constraints.json",
                    before_constraints,
                )
                _require_input_hashes(root, expected_input_hashes)
                application = _apply_iteration_authorization(
                    scene_spec_path=scene_spec_path,
                    candidates_path=current_candidates_path,
                    selection_path=selection_path,
                    compiled_plan_path=compiled_plan_path,
                    authorization_path=authorization_path,
                    session_id=session_id,
                    job_id=job_id,
                    iteration_index=iteration_index,
                    plan_sha256=plan_sha256,
                    approval_sha256=approval_sha256,
                    base_scene_spec_sha256=base_spec_sha256,
                    source_qa_report_sha256=report_sha256,
                    source_build_fingerprint=source_build_fingerprint,
                    candidates_sha256=candidates_sha256,
                    selection_sha256=selection_file_sha256,
                    compiled_plan_sha256=compiled_plan_sha256,
                    authorization_sha256=authorization_sha256,
                    selected_candidate_ids=selection.selected_candidate_ids,
                    output_path=next_spec_path,
                )
                if compiled.job_id != job_id or application["authorization_id"] != (
                    authorization.authorization_id
                ):
                    raise ValueError("compiled iteration plan authorization mismatch")
                _require_input_hashes(root, expected_input_hashes)
                result_spec_sha256 = sha256_file(next_spec_path)
                result_snapshot_sha256 = _write_immutable_copy(
                    next_spec_path,
                    iteration_root / "result_scene_spec.json",
                )
                if result_snapshot_sha256 != result_spec_sha256:
                    raise RuntimeError(
                        "iteration result SceneSpec snapshot hash changed during copy"
                    )
                _write_immutable_json(
                    iteration_root / _ITERATION_PREPARED,
                    {
                        "schema_version": "0.6.0",
                        "session_id": session_id,
                        "job_id": job_id,
                        "iteration_index": iteration_index,
                        "attempt_sha256": sha256_file(
                            iteration_root / _ITERATION_ATTEMPT
                        ),
                        "result_scene_spec_sha256": result_spec_sha256,
                        "result_scene_spec_snapshot_sha256": (
                            result_snapshot_sha256
                        ),
                        "prepared_at": _utc_now(),
                    },
                )
                if source_build is None or source_build_fingerprint is None:
                    raise RuntimeError(
                        "executable convergence iteration lacks source build provenance"
                    )
                live_source_build = _current_build_provenance(root, job_id)
                if live_source_build["fingerprint"] != source_build_fingerprint:
                    raise ValueError(
                        "canonical build inputs changed immediately before "
                        "convergence promotion"
                    )
                _require_input_hashes(root, expected_input_hashes)
                _require_constraint_contract(root, plan)
                _load_authoritative_activation(
                    session_root,
                    job_id=job_id,
                    session_id=session_id,
                    expected_plan_sha256=plan_sha256,
                    expected_approval_sha256=approval_sha256,
                )
                promotion = replace_scene_spec_if_current(
                    job_id,
                    next_spec_path,
                    expected_current_sha256=base_spec_sha256,
                    expected_candidate_sha256=result_spec_sha256,
                    lock_owner_id=current_job_write_lock_owner(job_id),
                    archive_current=True,
                )
                archived_value = promotion.get("archived_scene_spec")
                if not isinstance(archived_value, str) or not archived_value:
                    raise RuntimeError(
                        "convergence SceneSpec promotion did not preserve its baseline"
                    )
                archived = Path(archived_value)
                pipeline = _run_job_pipeline(
                    job_id,
                    root,
                    render_engine,
                    render_device,
                )
                _require_constraint_contract(root, plan)
                result_build_provenance = _current_build_provenance(root, job_id)
                result_build_fingerprint = str(
                    result_build_provenance["fingerprint"]
                )
                _validate_result_build_transition(
                    source_build,
                    result_build_provenance,
                    expected_source_scene_spec_sha256=base_spec_sha256,
                    expected_result_scene_spec_sha256=result_spec_sha256,
                )
                result_build_path = iteration_root / "result_build_provenance.json"
                _write_immutable_json(result_build_path, result_build_provenance)
                result_build_provenance_sha256 = sha256_file(result_build_path)
                after_constraints = {
                    "failures": int(pipeline["constraint_failures"]),
                    "results": list(pipeline.get("constraint_results", [])),
                }
                after_constraints_sha256 = _write_constraint_evidence(
                    iteration_root / "after_constraints.json",
                    after_constraints,
                )
                if source_structural_evidence is not None:
                    result_structural_evidence = (
                        _capture_convergence_structural_terminal(
                            job_id,
                            root,
                            session_id=session_id,
                            phase=f"result-i{iteration_index:02d}",
                            render_engine=render_engine,
                            render_device=render_device,
                        )
                    )
                    structural_comparison = compare_assembly_sanity_terminals(
                        root,
                        baseline=source_structural_evidence,
                        result=result_structural_evidence,
                        expected_job_id=job_id,
                    )
                    structural_comparison_path = (
                        iteration_root / _STRUCTURAL_COMPARISON
                    )
                    _write_immutable_json(
                        structural_comparison_path,
                        structural_comparison.model_dump(mode="json"),
                    )
                    structural_comparison_sha256 = sha256_file(
                        structural_comparison_path
                    )
                    structural_comparison_relative_path = (
                        session_root
                        / "iterations"
                        / f"{iteration_index:03d}"
                        / _STRUCTURAL_COMPARISON
                    ).resolve().relative_to(root.resolve()).as_posix()
                session_digest = hashlib.sha256(session_id.encode()).hexdigest()[:10]
                result_run = f"conv-{session_digest}-i{iteration_index:02d}"
                post_qa = _run_post_visual_qa(
                    job_id,
                    render_engine,
                    render_device,
                    run_id=result_run,
                )
                result_report_path = Path(post_qa["visual_qa_report"])
                result_candidates_path = Path(post_qa["revision_candidates"])
                _require_original_input_hashes(root, plan)
                _require_constraint_contract(root, plan)
                result_report = _load_report(result_report_path)
                _audit_qa_authoritative_evidence(
                    root=root,
                    job_id=job_id,
                    run_id=result_run,
                    expected_scene_spec_sha256=result_spec_sha256,
                    expected_report_sha256=sha256_file(result_report_path),
                    expected_candidates_sha256=sha256_file(result_candidates_path),
                    expected_build_fingerprint=result_build_fingerprint,
                )
                convergence = evaluate_convergence(
                    before_report_path=current_report_path,
                    after_report_path=result_report_path,
                    changed_ids=changed_ids,
                    preserved_ids=preserved_ids,
                    before_failed_constraints=int(before_constraints["failures"]),
                    after_failed_constraints=int(pipeline["constraint_failures"]),
                    before_constraint_results=list(before_constraints["results"]),
                    after_constraint_results=list(pipeline.get("constraint_results", [])),
                    multiview_comparison_path=structural_comparison_path,
                    minimum_improvement=plan.minimum_iteration_gain,
                )
                iou_non_regression = (
                    result_report.direct_metrics.silhouette_iou + 1e-9 >= before_iou
                )
                accepted = convergence.accepted and iou_non_regression
                structural_non_regression = (
                    structural_comparison is None
                    or structural_comparison.status == "passed"
                )
                accepted = accepted and structural_non_regression
                constraint_regression_count = len(convergence.constraint_regressions)
                result_report_sha256 = sha256_file(result_report_path)
                if accepted:
                    receipt = VisualConvergenceIteration(
                        session_id=session_id,
                        job_id=job_id,
                        iteration_index=iteration_index,
                        plan_sha256=plan_sha256,
                        approval_sha256=approval_sha256,
                        previous_iteration_receipt_sha256=previous_hash,
                        input_fingerprint=plan.input_fingerprint,
                        base_scene_spec_sha256=base_spec_sha256,
                        base_scene_spec_snapshot_sha256=base_snapshot_sha256,
                        source_qa_run_id=current_run,
                        source_qa_report_sha256=report_sha256,
                        candidates_sha256=candidates_sha256,
                        source_build_fingerprint=source_build_fingerprint,
                        selection_sha256=selection_file_sha256,
                        selected_candidate_ids=selection.selected_candidate_ids,
                        compiled_plan_sha256=compiled_plan_sha256,
                        execution_authorization_sha256=authorization_sha256,
                        result_scene_spec_sha256=result_spec_sha256,
                        result_qa_run_id=result_run,
                        result_qa_report_sha256=result_report_sha256,
                        result_candidates_sha256=sha256_file(result_candidates_path),
                        result_build_fingerprint=result_build_fingerprint,
                        result_build_provenance_sha256=(
                            result_build_provenance_sha256
                        ),
                        before_constraints_sha256=before_constraints_sha256,
                        after_constraints_sha256=after_constraints_sha256,
                        before_direct_score=before_score,
                        after_direct_score=result_report.direct_metrics.overall_direct_score,
                        before_silhouette_iou=before_iou,
                        after_silhouette_iou=result_report.direct_metrics.silhouette_iou,
                        score_delta=(
                            result_report.direct_metrics.overall_direct_score
                            - before_score
                        ),
                        changed_ids=changed_ids,
                        constraint_regression_count=0,
                        structural_multiview_status=(
                            structural_comparison.status
                            if structural_comparison is not None
                            else "not_applicable"
                        ),
                        source_structural_evidence=source_structural_evidence,
                        result_structural_evidence=result_structural_evidence,
                        structural_comparison_path=(
                            structural_comparison_relative_path
                        ),
                        structural_comparison_sha256=structural_comparison_sha256,
                        structural_regression_ids=(
                            [item.id for item in structural_comparison.regressions]
                            if structural_comparison is not None
                            else []
                        ),
                        canonical_scene_spec_sha256=result_spec_sha256,
                        status="accepted",
                        reason_codes=[
                            "direct_score_improved",
                            "constraints_preserved",
                            *(
                                ["five_view_structure_preserved"]
                                if structural_comparison is not None
                                else []
                            ),
                        ],
                        completed_at=_utc_now(),
                    )
                    receipts.append(
                        _commit_iteration_receipt(
                            session_root,
                            iteration_root,
                            receipt,
                        )
                    )
                    current_run = result_run
                    current_report_path = result_report_path
                    current_report = result_report
                    current_candidates_path = Path(post_qa["revision_candidates"])
                    candidates = _load_candidates(current_candidates_path, job_id)
                    if _target_reached(plan, current_report):
                        return _execution_response(
                            _terminal_report(
                                root=root,
                                session_root=session_root,
                                plan=plan,
                                plan_sha256=plan_sha256,
                                approval_sha256=approval_sha256,
                                receipts=receipts,
                                final_report_path=current_report_path,
                                termination_reason="target_reached",
                                reasons=[
                                    "The bounded session reached both approved direct "
                                    "targets."
                                ],
                            ),
                            outcome="iteration_completed_terminal",
                            iterations_executed=1,
                            next_action=None,
                        )
                    if len(receipts) >= plan.max_iterations:
                        return _execution_response(
                            _terminal_report(
                                root=root,
                                session_root=session_root,
                                plan=plan,
                                plan_sha256=plan_sha256,
                                approval_sha256=approval_sha256,
                                receipts=receipts,
                                final_report_path=current_report_path,
                                termination_reason="iteration_budget_exhausted",
                                reasons=[
                                    "The approved iteration budget was exhausted before "
                                    "both targets were reached."
                                ],
                            ),
                            outcome="iteration_completed_terminal",
                            iterations_executed=1,
                            next_action=None,
                        )
                    status = get_job_visual_convergence_status(
                        job_id,
                        session_id,
                    )
                    return {
                        **status,
                        "execution_outcome": "iteration_completed",
                        "iterations_executed_this_invocation": 1,
                        "last_iteration_index": iteration_index,
                        "last_iteration_status": "accepted",
                        "next_action": "invoke_run_again",
                    }

                rollback_reason = (
                    "five-view structural regression"
                    if not structural_non_regression
                    else (
                        "measured constraint regression"
                        if constraint_regression_count
                        else (
                            "silhouette IoU regressed"
                            if not iou_non_regression
                            else "direct-score gain did not reach the approved minimum"
                        )
                    )
                )
                _load_authoritative_activation(
                    session_root,
                    job_id=job_id,
                    session_id=session_id,
                    expected_plan_sha256=plan_sha256,
                    expected_approval_sha256=approval_sha256,
                )
                _rollback_job(
                    job_id=job_id,
                    root=root,
                    run_dir=iteration_root,
                    scene_spec_path=scene_spec_path,
                    archived=archived,
                    expected_spec_sha256=base_spec_sha256,
                    expected_current_spec_sha256=result_spec_sha256,
                    expected_input_hashes=expected_input_hashes,
                    latest_snapshot=latest_snapshot,
                    render_engine=render_engine,
                    render_device=render_device,
                    reason=rollback_reason,
                )
                _require_constraint_contract(root, plan)
                if source_build_fingerprint is not None:
                    restored_build = _current_build_provenance(root, job_id)
                    if restored_build["fingerprint"] != source_build_fingerprint:
                        raise RuntimeError(
                            "rollback did not restore the source build provenance"
                        )
                receipt = VisualConvergenceIteration(
                    session_id=session_id,
                    job_id=job_id,
                    iteration_index=iteration_index,
                    plan_sha256=plan_sha256,
                    approval_sha256=approval_sha256,
                    previous_iteration_receipt_sha256=previous_hash,
                    input_fingerprint=plan.input_fingerprint,
                    base_scene_spec_sha256=base_spec_sha256,
                    base_scene_spec_snapshot_sha256=base_snapshot_sha256,
                    source_qa_run_id=current_run,
                    source_qa_report_sha256=report_sha256,
                    candidates_sha256=candidates_sha256,
                    source_build_fingerprint=source_build_fingerprint,
                    selection_sha256=selection_file_sha256,
                    selected_candidate_ids=selection.selected_candidate_ids,
                    compiled_plan_sha256=compiled_plan_sha256,
                    execution_authorization_sha256=authorization_sha256,
                    result_scene_spec_sha256=result_spec_sha256,
                    result_qa_run_id=result_run,
                    result_qa_report_sha256=result_report_sha256,
                    result_candidates_sha256=sha256_file(result_candidates_path),
                    result_build_fingerprint=(
                        result_build_fingerprint
                        if result_build_provenance_sha256 is not None
                        else None
                    ),
                    result_build_provenance_sha256=result_build_provenance_sha256,
                    before_constraints_sha256=before_constraints_sha256,
                    after_constraints_sha256=after_constraints_sha256,
                    before_direct_score=before_score,
                    after_direct_score=result_report.direct_metrics.overall_direct_score,
                    before_silhouette_iou=before_iou,
                    after_silhouette_iou=result_report.direct_metrics.silhouette_iou,
                    score_delta=(
                        result_report.direct_metrics.overall_direct_score - before_score
                    ),
                    changed_ids=changed_ids,
                    constraint_regression_count=constraint_regression_count,
                    structural_multiview_status=(
                        structural_comparison.status
                        if structural_comparison is not None
                        else "not_applicable"
                    ),
                    source_structural_evidence=source_structural_evidence,
                    result_structural_evidence=result_structural_evidence,
                    structural_comparison_path=structural_comparison_relative_path,
                    structural_comparison_sha256=structural_comparison_sha256,
                    structural_regression_ids=(
                        [item.id for item in structural_comparison.regressions]
                        if structural_comparison is not None
                        else []
                    ),
                    canonical_scene_spec_sha256=base_spec_sha256,
                    status="rolled_back",
                    reason_codes=[rollback_reason.replace(" ", "_")],
                    completed_at=_utc_now(),
                )
                receipts.append(
                    _commit_iteration_receipt(session_root, iteration_root, receipt)
                )
                return _execution_response(
                    _terminal_report(
                        root=root,
                        session_root=session_root,
                        plan=plan,
                        plan_sha256=plan_sha256,
                        approval_sha256=approval_sha256,
                        receipts=receipts,
                        final_report_path=current_report_path,
                        termination_reason=(
                            "structural_regression"
                            if not structural_non_regression
                            else (
                                "constraint_regression"
                                if constraint_regression_count
                                else "plateau"
                            )
                        ),
                        reasons=[
                            f"Iteration {iteration_index} was rolled back: "
                            f"{rollback_reason}.",
                            (
                                "The prior canonical SceneSpec and fixed-camera QA "
                                "evidence remain current."
                            ),
                        ],
                    ),
                    outcome="iteration_completed_terminal",
                    iterations_executed=1,
                    next_action=None,
                )
            except Exception as exc:
                # A committed receipt is immutable evidence; never mask a later
                # terminalization failure by attempting to publish the same index again.
                if committed_root.is_dir():
                    raise RuntimeError(
                        "convergence iteration was committed but post-commit "
                        "terminalization failed; invoke the session again to recover"
                    ) from exc
                current_canonical_hash = (
                    sha256_file(scene_spec_path) if scene_spec_path.is_file() else None
                )
                expected_session_hashes = {base_spec_sha256}
                if result_spec_sha256 is not None:
                    expected_session_hashes.add(result_spec_sha256)
                if current_canonical_hash not in expected_session_hashes:
                    raise RuntimeError(
                        "canonical SceneSpec changed outside the convergence-owned "
                        "base/result hashes; refusing rollback overwrite and marking "
                        "the session stale_or_tampered"
                    ) from exc
                canonical_changed = current_canonical_hash != base_spec_sha256
                if canonical_changed and archived is not None:
                    _load_authoritative_activation(
                        session_root,
                        job_id=job_id,
                        session_id=session_id,
                        expected_plan_sha256=plan_sha256,
                        expected_approval_sha256=approval_sha256,
                    )
                    _rollback_job(
                        job_id=job_id,
                        root=root,
                        run_dir=iteration_root,
                        scene_spec_path=scene_spec_path,
                        archived=archived,
                        expected_spec_sha256=base_spec_sha256,
                        expected_current_spec_sha256=result_spec_sha256 or "",
                        expected_input_hashes=expected_input_hashes,
                        latest_snapshot=latest_snapshot,
                        render_engine=render_engine,
                        render_device=render_device,
                        reason=f"convergence host failure: {type(exc).__name__}: {exc}",
                    )
                _require_constraint_contract(root, plan)
                if source_build_fingerprint is not None:
                    restored_build = _current_build_provenance(root, job_id)
                    if restored_build["fingerprint"] != source_build_fingerprint:
                        raise RuntimeError(
                            "host-failure rollback did not restore source build provenance"
                        ) from exc
                failure_result_run: str | None = None
                failure_result_report_sha256: str | None = None
                failure_result_candidates_sha256: str | None = None
                failure_after_direct_score: float | None = None
                failure_after_silhouette_iou: float | None = None
                failure_score_delta: float | None = None
                if (
                    result_run is not None
                    and result_spec_sha256 is not None
                    and result_report_path is not None
                    and result_report_path.is_file()
                    and result_candidates_path is not None
                    and result_candidates_path.is_file()
                ):
                    try:
                        (
                            _failure_report_path,
                            _failure_candidates_path,
                            failure_report,
                            _failure_candidates,
                            _failure_artifacts,
                        ) = _audit_qa_authoritative_evidence(
                            root=root,
                            job_id=job_id,
                            run_id=result_run,
                            expected_scene_spec_sha256=result_spec_sha256,
                            expected_report_sha256=sha256_file(result_report_path),
                            expected_candidates_sha256=sha256_file(
                                result_candidates_path
                            ),
                            expected_build_fingerprint=result_build_fingerprint,
                        )
                    except (ValueError, OSError):
                        pass
                    else:
                        failure_result_run = result_run
                        failure_result_report_sha256 = sha256_file(result_report_path)
                        failure_result_candidates_sha256 = sha256_file(
                            result_candidates_path
                        )
                        failure_after_direct_score = (
                            failure_report.direct_metrics.overall_direct_score
                        )
                        failure_after_silhouette_iou = (
                            failure_report.direct_metrics.silhouette_iou
                        )
                        failure_score_delta = (
                            failure_after_direct_score - before_score
                        )
                receipt = VisualConvergenceIteration(
                    session_id=session_id,
                    job_id=job_id,
                    iteration_index=iteration_index,
                    plan_sha256=plan_sha256,
                    approval_sha256=approval_sha256,
                    previous_iteration_receipt_sha256=previous_hash,
                    input_fingerprint=plan.input_fingerprint,
                    base_scene_spec_sha256=base_spec_sha256,
                    base_scene_spec_snapshot_sha256=base_snapshot_sha256,
                    source_qa_run_id=current_run,
                    source_qa_report_sha256=report_sha256,
                    candidates_sha256=candidates_sha256,
                    source_build_fingerprint=source_build_fingerprint,
                    selection_sha256=selection_file_sha256,
                    selected_candidate_ids=selection.selected_candidate_ids,
                    compiled_plan_sha256=compiled_plan_sha256,
                    execution_authorization_sha256=authorization_sha256,
                    result_scene_spec_sha256=result_spec_sha256,
                    result_qa_run_id=failure_result_run,
                    result_qa_report_sha256=failure_result_report_sha256,
                    result_candidates_sha256=failure_result_candidates_sha256,
                    result_build_fingerprint=(
                        result_build_fingerprint
                        if result_build_provenance_sha256 is not None
                        else None
                    ),
                    result_build_provenance_sha256=result_build_provenance_sha256,
                    before_constraints_sha256=before_constraints_sha256,
                    after_constraints_sha256=after_constraints_sha256,
                    before_direct_score=before_score,
                    after_direct_score=failure_after_direct_score,
                    before_silhouette_iou=before_iou,
                    after_silhouette_iou=failure_after_silhouette_iou,
                    score_delta=failure_score_delta,
                    changed_ids=changed_ids,
                    structural_multiview_status=(
                        structural_comparison.status
                        if structural_comparison is not None
                        else "not_applicable"
                    ),
                    source_structural_evidence=(
                        source_structural_evidence
                        if structural_comparison is not None
                        else None
                    ),
                    result_structural_evidence=(
                        result_structural_evidence
                        if structural_comparison is not None
                        else None
                    ),
                    structural_comparison_path=structural_comparison_relative_path,
                    structural_comparison_sha256=structural_comparison_sha256,
                    structural_regression_ids=(
                        [item.id for item in structural_comparison.regressions]
                        if structural_comparison is not None
                        else []
                    ),
                    canonical_scene_spec_sha256=base_spec_sha256,
                    status="failed",
                    reason_codes=[f"host_failure:{type(exc).__name__}"],
                    completed_at=_utc_now(),
                )
                receipts.append(
                    _commit_iteration_receipt(session_root, iteration_root, receipt)
                )
                return _execution_response(
                    _terminal_report(
                        root=root,
                        session_root=session_root,
                        plan=plan,
                        plan_sha256=plan_sha256,
                        approval_sha256=approval_sha256,
                        receipts=receipts,
                        final_report_path=current_report_path,
                        termination_reason="failed",
                        reasons=[
                            "Host execution failed and canonical data was preserved: "
                            f"{type(exc).__name__}: {exc}"
                        ],
                    ),
                    outcome="iteration_completed_terminal",
                    iterations_executed=1,
                    next_action=None,
                )

        return _execution_response(
            _terminal_report(
                root=root,
                session_root=session_root,
                plan=plan,
                plan_sha256=plan_sha256,
                approval_sha256=approval_sha256,
                receipts=receipts,
                final_report_path=current_report_path,
                termination_reason="iteration_budget_exhausted",
                reasons=[
                    "The approved iteration budget was exhausted before both targets "
                    "were reached."
                ],
            ),
            outcome="budget_already_exhausted",
            iterations_executed=0,
            next_action=None,
        )


def get_job_visual_convergence_status(
    job_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Inspect one session from exact immutable files without changing any artifact."""

    root, session_root = _session_paths(job_id, session_id)
    plan_path = session_root / "plan.json"
    if not plan_path.is_file():
        raise FileNotFoundError(f"Visual convergence plan is missing: {plan_path}")
    plan = _load_plan(plan_path)
    execution_binding_gaps = _executable_plan_binding_gaps(plan)
    status_only_legacy = bool(execution_binding_gaps)
    plan_sha256 = sha256_file(plan_path)
    approval_path = session_root / "approval.json"
    report_path = session_root / _TERMINAL_REPORT
    approval: VisualConvergenceApproval | None = None
    approval_sha256: str | None = None
    terminal: VisualConvergenceReport | None = None
    receipts: list[tuple[VisualConvergenceIteration, str, Path]] = []
    iteration_evidence: list[HashBoundConvergenceArtifact] = []
    integrity = "current"
    integrity_error: str | None = None
    integrity_warnings: list[str] = []
    staging_root: Path | None = None
    staging_result_sha256: str | None = None
    try:
        _validate_plan_input_binding(plan)
        _validate_initial_session_snapshots(root, session_root, plan)
        if report_path.is_file():
            integrity_warnings.extend(_validate_terminal_input_manifest(root, plan))
        elif _input_fingerprint(root) != plan.input_fingerprint:
            raise ValueError("immutable input fingerprint changed after session planning")
        if not report_path.is_file():
            _require_constraint_contract(root, plan)
        initial_report_path = (
            root
            / "qa"
            / "runs"
            / plan.initial_qa_run_id
            / "visual_qa_report.json"
        )
        if (
            not initial_report_path.is_file()
            or sha256_file(initial_report_path) != plan.initial_qa_report_sha256
        ):
            raise ValueError("initial QA report changed after session planning")
        initial_candidates_path = initial_report_path.with_name(
            "revision_candidates.json"
        )
        if not initial_candidates_path.is_file():
            raise ValueError("initial QA candidates are missing")
        expected_initial_candidates_sha256 = (
            plan.initial_candidates_sha256
            if plan.initial_candidates_sha256 is not None
            else sha256_file(initial_candidates_path)
        )
        (
            _initial_report_path,
            _initial_candidates_path,
            _initial_report,
            _initial_candidates,
            initial_qa_evidence,
        ) = _audit_qa_authoritative_evidence(
            root=root,
            job_id=plan.job_id,
            run_id=plan.initial_qa_run_id,
            expected_scene_spec_sha256=plan.initial_scene_spec_sha256,
            expected_report_sha256=plan.initial_qa_report_sha256,
            expected_candidates_sha256=expected_initial_candidates_sha256,
            expected_build_fingerprint=plan.initial_build_fingerprint,
        )
        iteration_evidence = _deduplicate_artifacts(
            [*iteration_evidence, *initial_qa_evidence]
        )
    except (ValueError, OSError) as exc:
        integrity = "stale_or_tampered"
        integrity_error = str(exc)
    try:
        receipts = _load_receipts(session_root)
    except (ValueError, OSError) as exc:
        integrity = "stale_or_tampered"
        integrity_error = str(exc)
    orphaned_terminal_artifacts = sorted(
        name
        for name in _TERMINAL_DERIVED_ARTIFACTS
        if (session_root / name).exists()
    )
    if orphaned_terminal_artifacts and not report_path.is_file():
        integrity = "stale_or_tampered"
        integrity_error = (
            "terminal or cancellation receipt evidence exists without "
            "convergence_report.json; the consumed approval cannot resume: "
            f"{orphaned_terminal_artifacts}"
        )
    if approval_path.is_file():
        try:
            approval = _load_approval(approval_path)
            approval_sha256 = sha256_file(approval_path)
            validate_iteration_receipt_chain(
                plan,
                approval,
                plan_sha256=plan_sha256,
                approval_sha256=approval_sha256,
                receipts=[
                    (receipt, receipt_hash)
                    for receipt, receipt_hash, _path in receipts
                ],
            )
            iteration_evidence = _audit_receipt_evidence(
                root=root,
                session_root=session_root,
                plan=plan,
                receipts=receipts,
            )
            stages = _iteration_staging_dirs(session_root)
            if stages:
                staging_root = stages[0]
                attempt, _latest_snapshot = _validate_iteration_attempt(
                    stage_root=staging_root,
                    plan=plan,
                    plan_sha256=plan_sha256,
                    approval_sha256=approval_sha256,
                    receipts=receipts,
                )
                if attempt is not None:
                    staging_result_sha256 = _prepared_iteration_result_hash(
                        staging_root,
                        attempt_sha256=sha256_file(
                            staging_root / _ITERATION_ATTEMPT
                        ),
                    )
            if not receipts:
                current_candidates_path = (
                    root
                    / "qa"
                    / "runs"
                    / plan.initial_qa_run_id
                    / "revision_candidates.json"
                )
                (
                    _current_report_path,
                    _current_candidates_path,
                    _current_report,
                    _current_candidates,
                    current_qa_evidence,
                ) = _audit_qa_authoritative_evidence(
                    root=root,
                    job_id=plan.job_id,
                    run_id=plan.initial_qa_run_id,
                    expected_scene_spec_sha256=plan.initial_scene_spec_sha256,
                    expected_report_sha256=plan.initial_qa_report_sha256,
                    expected_candidates_sha256=(
                        plan.initial_candidates_sha256
                        if plan.initial_candidates_sha256 is not None
                        else sha256_file(current_candidates_path)
                    ),
                    expected_build_fingerprint=plan.initial_build_fingerprint,
                )
                iteration_evidence = _deduplicate_artifacts(
                    [*iteration_evidence, *current_qa_evidence]
                )
        except (ValueError, OSError) as exc:
            integrity = "stale_or_tampered"
            integrity_error = str(exc)
    elif receipts:
        integrity = "stale_or_tampered"
        integrity_error = "convergence receipts exist without an exact approval"

    if report_path.is_file():
        try:
            terminal_candidate = VisualConvergenceReport.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
            if approval_sha256 is None:
                raise ValueError(
                    "terminal convergence report exists without exact approval"
                )
            iteration_evidence = _validate_terminal_report_bindings(
                root=root,
                session_root=session_root,
                plan=plan,
                plan_sha256=plan_sha256,
                approval_sha256=approval_sha256,
                receipts=receipts,
                terminal=terminal_candidate,
            )
            terminal = terminal_candidate
            current_run, _current_report_hash = _current_qa_identity(
                plan,
                receipts,
            )
            current_report_path = (
                root / "qa" / "runs" / current_run / "visual_qa_report.json"
            )
            pdf_path = session_root / "convergence_report.pdf"
            pdf_manifest_path = session_root / "convergence_report.manifest.json"
            if pdf_path.is_file() != pdf_manifest_path.is_file():
                raise ValueError("terminal PDF and sidecar must exist as one pair")
            if pdf_manifest_path.is_file():
                pdf_manifest = VisualConvergenceReportManifest.model_validate_json(
                    pdf_manifest_path.read_text(encoding="utf-8")
                )
                if (
                    pdf_manifest.job_id != job_id
                    or pdf_manifest.session_id != session_id
                    or pdf_manifest.report_json.relative_path
                    != report_path.resolve().relative_to(root.resolve()).as_posix()
                    or pdf_manifest.report_json.sha256 != sha256_file(report_path)
                    or pdf_manifest.pdf.relative_path
                    != pdf_path.resolve().relative_to(root.resolve()).as_posix()
                    or pdf_manifest.pdf.sha256 != sha256_file(pdf_path)
                ):
                    raise ValueError("terminal PDF sidecar hash binding changed")
                for artifact in pdf_manifest.sources:
                    _bind_existing_artifact(
                        root,
                        root / Path(*artifact.relative_path.split("/")),
                        artifact.sha256,
                        label="terminal PDF source",
                    )
                expected_source_fingerprint = _canonical_sha256(
                    [
                        {
                            "relative_path": artifact.relative_path,
                            "sha256": artifact.sha256,
                        }
                        for artifact in pdf_manifest.sources
                    ]
                )
                if pdf_manifest.source_fingerprint != expected_source_fingerprint:
                    raise ValueError(
                        "terminal PDF sidecar source fingerprint changed"
                    )
                required_pdf_sources = {
                    (session_root / "plan.json")
                    .resolve()
                    .relative_to(root.resolve())
                    .as_posix(),
                    (session_root / "approval.json")
                    .resolve()
                    .relative_to(root.resolve())
                    .as_posix(),
                    report_path.resolve().relative_to(root.resolve()).as_posix(),
                    current_report_path.resolve()
                    .relative_to(root.resolve())
                    .as_posix(),
                    *[
                        artifact.relative_path
                        for artifact in iteration_evidence
                    ],
                }
                if terminal.final_scene_spec_snapshot is not None:
                    required_pdf_sources.add(
                        terminal.final_scene_spec_snapshot.relative_path
                    )
                if terminal.final_build_provenance_snapshot is not None:
                    required_pdf_sources.add(
                        terminal.final_build_provenance_snapshot.relative_path
                    )
                if terminal.cancellation_receipt is not None:
                    required_pdf_sources.add(
                        terminal.cancellation_receipt.relative_path
                    )
                manifest_source_paths = {
                    artifact.relative_path for artifact in pdf_manifest.sources
                }
                missing_sources = sorted(
                    required_pdf_sources - manifest_source_paths
                )
                if missing_sources:
                    raise ValueError(
                        "terminal PDF sidecar lacks exact convergence sources: "
                        f"{missing_sources}"
                    )
        except (ValueError, OSError) as exc:
            integrity = "stale_or_tampered"
            integrity_error = str(exc)
    elif receipts and receipts[-1][0].status != "accepted":
        integrity = "stale_or_tampered"
        integrity_error = (
            "terminal convergence receipt exists without convergence_report.json; "
            "the session cannot resume"
        )
    if report_path.is_file() and staging_root is not None:
        integrity = "stale_or_tampered"
        integrity_error = (
            "terminal convergence evidence conflicts with receipt-less iteration "
            "staging; the terminal session is invalid and cannot recover that attempt"
        )

    active_expected_hash = (
        receipts[-1][0].canonical_scene_spec_sha256
        if receipts
        else plan.initial_scene_spec_sha256
    )
    current_scene_spec_path = root / "analysis" / "scene_spec.json"
    current_canonical_hash = (
        sha256_file(current_scene_spec_path)
        if current_scene_spec_path.is_file()
        else None
    )
    active_allowed_hashes = {active_expected_hash}
    if staging_result_sha256 is not None:
        active_allowed_hashes.add(staging_result_sha256)
    if terminal is None and current_canonical_hash not in active_allowed_hashes:
        integrity = "stale_or_tampered"
        integrity_error = (
            "active canonical SceneSpec does not match the receipt chain"
        )
    if (
        terminal is None
        and staging_root is None
        and integrity == "current"
        and plan.initial_build_fingerprint
    ):
        try:
            expected_active_build = _current_build_fingerprint(plan, receipts)
            active_build = _current_build_provenance(root, plan.job_id)
            if active_build["fingerprint"] != expected_active_build:
                raise ValueError(
                    "active canonical build inputs do not match the receipt chain"
                )
        except (ValueError, OSError) as exc:
            integrity = "stale_or_tampered"
            integrity_error = str(exc)
    if integrity != "current":
        canonical_relation = "unknown_invalid"
    elif terminal is None:
        if current_canonical_hash == active_expected_hash:
            canonical_relation = "current"
        elif (
            staging_root is not None
            and current_canonical_hash == staging_result_sha256
        ):
            canonical_relation = "recoverable_staged_result"
        else:
            canonical_relation = "diverged_active"
    elif current_canonical_hash == terminal.final_scene_spec_sha256:
        canonical_relation = "current"
    else:
        canonical_relation = "superseded_after_terminal"
    execution_eligible = (
        not status_only_legacy
        and integrity == "current"
        and terminal is None
    )
    if status_only_legacy:
        execution_block_reason = (
            "legacy_status_only_missing_bindings:"
            + ",".join(execution_binding_gaps)
        )
    elif integrity != "current":
        execution_block_reason = integrity_error or "session_integrity_not_current"
    elif terminal is not None:
        execution_block_reason = "terminal_session"
    else:
        execution_block_reason = None
    if staging_root is not None and terminal is None and execution_eligible:
        next_action = "invoke_run_to_recover"
    elif approval is None and execution_eligible:
        next_action = "approve_exact_plan"
    elif approval is not None and execution_eligible:
        next_action = (
            "invoke_run_again"
            if len(receipts) < plan.max_iterations
            else "invoke_run_to_finalize"
        )
    else:
        next_action = None
    return {
        "ok": integrity == "current",
        "job_id": job_id,
        "session_id": session_id,
        "status": (
            "invalid_terminal"
            if report_path.is_file() and integrity != "current"
            else (
                "terminal"
                if terminal is not None
                else (
                    "recovery_required"
                    if staging_root is not None
                    else (
                        "approved"
                        if approval is not None
                        else "waiting_for_exact_approval"
                    )
                )
            )
        ),
        "integrity": integrity,
        "integrity_error": integrity_error,
        "integrity_warnings": integrity_warnings,
        "execution_eligible": execution_eligible,
        "status_only_legacy": status_only_legacy,
        "execution_block_reason": execution_block_reason,
        "execution_binding_gaps": execution_binding_gaps,
        "plan": str(plan_path),
        "plan_sha256": plan_sha256,
        "approval": str(approval_path) if approval_path.is_file() else None,
        "approval_sha256": approval_sha256,
        "iteration_count": len(receipts),
        "max_iterations": plan.max_iterations,
        "host_step_iteration_limit": 1,
        "recovery_required": staging_root is not None,
        "incomplete_iteration_index": (
            int(staging_root.name) if staging_root is not None else None
        ),
        "next_action": next_action,
        "current_canonical_scene_spec_sha256": current_canonical_hash,
        "canonical_relation": canonical_relation,
        "terminal_report": str(report_path) if report_path.is_file() else None,
        "terminal_report_sha256": (
            sha256_file(report_path) if report_path.is_file() else None
        ),
        "termination_reason": (
            terminal.termination_reason if terminal is not None else None
        ),
        "target_reached": terminal.target_reached if terminal is not None else None,
        "manual_review_required": (
            terminal.manual_review_required if terminal is not None else None
        ),
        "pdf": (
            str(session_root / "convergence_report.pdf")
            if (session_root / "convergence_report.pdf").is_file()
            else None
        ),
    }


def cancel_job_visual_convergence(
    job_id: str,
    session_id: str,
    *,
    reason: str,
) -> dict[str, Any]:
    """Close an approved inactive session without changing canonical authoring data."""

    if not reason.strip():
        raise ValueError("convergence cancellation reason must not be empty")
    root, session_root = _session_paths(job_id, session_id)
    if (session_root / _TERMINAL_REPORT).exists():
        raise ValueError("terminal convergence sessions cannot be cancelled")
    cancellation_path = session_root / _CANCELLATION_RECEIPT
    if cancellation_path.exists():
        raise ValueError(
            "visual convergence approval was already consumed by cancellation"
        )
    plan_path = session_root / "plan.json"
    approval_path = session_root / "approval.json"
    if not approval_path.is_file():
        raise ValueError(
            "an unapproved plan grants no authority and does not require cancellation"
        )
    plan = _load_plan(plan_path)
    approval = _load_approval(approval_path)
    plan_sha256 = sha256_file(plan_path)
    approval_sha256 = sha256_file(approval_path)
    with workflow_write_lock(
        root,
        job_id,
        _session_lock_id(session_id),
        ttl_seconds=86400,
    ):
        _require_no_incomplete_iteration_before_terminal(session_root)
        receipts = _validate_active_state(
            root,
            session_root,
            plan,
            plan_sha256,
            approval,
            approval_sha256,
        )
        current_run, current_report_hash = _current_qa_identity(plan, receipts)
        current_report_path, candidate_path, current_report, _candidates = _qa_evidence(
            root,
            job_id,
            current_run,
            require_current_spec=True,
        )
        if sha256_file(current_report_path) != current_report_hash:
            raise ValueError("current QA evidence changed before cancellation")
        current_candidates_sha256 = (
            _current_candidates_sha256(plan, receipts)
            if plan.initial_candidates_sha256 is not None
            else sha256_file(candidate_path)
        )
        if sha256_file(candidate_path) != current_candidates_sha256:
            raise ValueError("current QA candidates changed before cancellation")
        if _target_reached(plan, current_report):
            return _terminal_report(
                root=root,
                session_root=session_root,
                plan=plan,
                plan_sha256=plan_sha256,
                approval_sha256=approval_sha256,
                receipts=receipts,
                final_report_path=current_report_path,
                termination_reason="target_reached",
                reasons=[
                    "The approved targets were already reached before cancellation."
                ],
            )
        current_build_fingerprint = (
            _current_build_fingerprint(plan, receipts)
            if plan.initial_build_fingerprint is not None
            else None
        )
        cancellation = VisualConvergenceCancellation(
            cancellation_id=f"cancel-{uuid4().hex}",
            session_id=session_id,
            job_id=job_id,
            plan_sha256=plan_sha256,
            approval_sha256=approval_sha256,
            input_fingerprint=plan.input_fingerprint,
            canonical_scene_spec_sha256=sha256_file(
                root / "analysis" / "scene_spec.json"
            ),
            current_qa_run_id=current_run,
            current_qa_report_sha256=current_report_hash,
            current_candidates_sha256=current_candidates_sha256,
            current_build_fingerprint=current_build_fingerprint,
            previous_iteration_receipt_sha256=(
                receipts[-1][1] if receipts else None
            ),
            reason=reason.strip(),
            cancelled_at=_utc_now(),
        )
        _write_immutable_json(
            cancellation_path,
            cancellation.model_dump(mode="json"),
        )
        return _terminal_report(
            root=root,
            session_root=session_root,
            plan=plan,
            plan_sha256=plan_sha256,
            approval_sha256=approval_sha256,
            receipts=receipts,
            final_report_path=current_report_path,
            termination_reason="cancelled",
            reasons=[f"User cancelled the bounded convergence session: {reason.strip()}"],
        )


__all__ = [
    "approve_job_visual_convergence",
    "cancel_job_visual_convergence",
    "get_job_visual_convergence_status",
    "plan_job_visual_convergence",
    "run_job_visual_convergence",
]
