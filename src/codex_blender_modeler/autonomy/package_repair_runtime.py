"""Fail-closed runtime for one derived-only portable-package repair."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..blender_artifacts import sha256_file
from ..optimization.models import OptimizationPlan
from ..optimization.provenance import require_unchanged_source
from ..orchestration.models import WorkflowAttempt, WorkflowPlan
from ..packaging.models import ExportPackageManifest, RoundTripValidation
from ..packaging.service import package_asset, validate_asset_package
from .authorization import artifact_for, canonical_digest
from .io import ensure_autonomy_path, write_immutable_json
from .models import AutonomyArtifact, AutonomyBudget, AutonomyState
from .production_budget import (
    PackageRepairDecision,
    PackageRepairFailure,
    PackageRepairPlan,
    PackageRepairReceipt,
    classify_package_repair,
)


@dataclass(frozen=True)
class PreparedPackageRepair:
    """Return exact normalized failure evidence and its bounded policy decision."""

    failure: PackageRepairFailure
    failure_artifact: AutonomyArtifact
    decision: PackageRepairDecision
    plan_artifact: AutonomyArtifact | None


@dataclass(frozen=True)
class ExecutedPackageRepair:
    """Return one immutable repair receipt and any accepted package evidence."""

    receipt: PackageRepairReceipt
    receipt_artifact: AutonomyArtifact
    package_artifact: AutonomyArtifact | None
    roundtrip_artifact: AutonomyArtifact | None


def _utc_now() -> datetime:
    """Return one timezone-aware timestamp for repair evidence."""

    return datetime.now(UTC)


def _workflow_step(plan: WorkflowPlan, step_id: str):
    """Resolve one exact portable workflow step without guessing aliases."""

    matches = [step for step in plan.steps if step.step_id == step_id]
    if len(matches) != 1:
        raise ValueError(f"portable repair step is missing or ambiguous: {step_id}")
    return matches[0]


def _latest_failed_attempt(
    root: Path, workflow_id: str, step_id: str
) -> tuple[WorkflowAttempt, Path]:
    """Load the newest exact failed V0.8 attempt for the reported portable step."""

    attempt_root = ensure_autonomy_path(
        root,
        root / "workflows" / workflow_id / "attempts" / step_id,
        must_exist=True,
    )
    candidates: list[tuple[WorkflowAttempt, Path]] = []
    for path in sorted(attempt_root.glob("*.json")):
        attempt = WorkflowAttempt.model_validate_json(path.read_text(encoding="utf-8"))
        if attempt.step_id == step_id and attempt.status == "failed":
            candidates.append((attempt, path))
    if not candidates:
        raise FileNotFoundError(f"failed portable attempt is missing: {step_id}")
    return candidates[-1]


def _canonical_source(
    root: Path,
    state: AutonomyState,
    workflow: WorkflowPlan,
) -> tuple[OptimizationPlan, Path]:
    """Verify the exact V0.7 source snapshot before classifying any repair."""

    package_step = _workflow_step(workflow, "portable.package")
    run_id = str(package_step.parameters.get("run_id", ""))
    plan_path = ensure_autonomy_path(
        root,
        root / "optimization" / "runs" / run_id / "optimization_plan.json",
        must_exist=True,
    )
    plan = OptimizationPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    expected_profile_id = str(package_step.parameters.get("profile_id", ""))
    if plan.job_id != state.job_id or plan.profile_id != expected_profile_id:
        raise ValueError("portable repair optimization plan identity mismatch")
    require_unchanged_source(plan.source, root, state.job_id)
    return plan, plan_path


def _repair_package_id(original: str, repair_index: int) -> str:
    """Derive a fresh bounded package ID while retaining the source package identity."""

    suffix = f"-aqr{repair_index:02d}"
    return f"{original[: max(1, 127 - len(suffix))]}{suffix}"


def _machine_error_code(
    root: Path,
    workflow: WorkflowPlan,
    step_id: str,
    attempt: WorkflowAttempt,
) -> tuple[str, bool, list[str]]:
    """Classify only exact derived collisions or format-only round-trip reports."""

    if step_id == "portable.package" and attempt.error_type == "FileExistsError":
        package_step = _workflow_step(workflow, step_id)
        profile_id = str(package_step.parameters.get("profile_id", ""))
        package_id = str(package_step.parameters.get("package_id", ""))
        manifest = root / "exports" / "packages" / profile_id / package_id / "package_manifest.json"
        if manifest.is_file():
            return (
                "stale_derived_package",
                True,
                ["The planned immutable package ID already exists; a fresh derived ID is safe."],
            )
    if step_id == "portable.roundtrip":
        roundtrip_step = _workflow_step(workflow, step_id)
        package_step = _workflow_step(workflow, "portable.package")
        run_id = str(package_step.parameters.get("run_id", ""))
        package_id = str(roundtrip_step.parameters.get("package_id", ""))
        report_path = (
            root
            / "optimization"
            / "runs"
            / run_id
            / "roundtrip"
            / package_id
            / "roundtrip_validation.json"
        )
        if report_path.is_file():
            report = RoundTripValidation.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
            failed_categories = {item.category for item in report.checks if item.status == "failed"}
            if not report.ok and failed_categories and failed_categories <= {"format"}:
                return (
                    "export_metadata_mismatch",
                    True,
                    ["The exact round-trip report contains only format-class failures."],
                )
    return (
        "unclassified_package_failure",
        False,
        [
            "The portable failure is not an exact whitelisted derived collision or "
            "format-only round-trip failure."
        ],
    )


def prepare_package_repair(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    budget: AutonomyBudget,
    workflow: WorkflowPlan,
    *,
    failed_step_id: str,
) -> PreparedPackageRepair:
    """Normalize one failed portable step and reserve at most one exact repair."""

    if failed_step_id not in {"portable.package", "portable.roundtrip"}:
        raise ValueError("package repair accepts only portable.package or portable.roundtrip")
    attempt, attempt_path = _latest_failed_attempt(root, state.workflow_id, failed_step_id)
    source, source_path = _canonical_source(root, state, workflow)
    error_code, deterministic, details = _machine_error_code(
        root, workflow, failed_step_id, attempt
    )
    repair_index = state.budget_usage.package_repairs + 1
    evidence_root = session_root / "package_repairs" / f"r{repair_index:02d}-{attempt.attempt_id}"
    failure_path = evidence_root / "failure.json"
    attempt_artifact = artifact_for(root, attempt_path)
    source_artifact = artifact_for(root, source_path)
    failure = PackageRepairFailure(
        contract_id=f"package-repair-failure-{repair_index:02d}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        input_sha256=attempt.input_fingerprint,
        source_fingerprint=canonical_digest(
            {
                "attempt": attempt_artifact.sha256,
                "source": source.source.source_fingerprint,
            }
        ),
        producer="codex_blender_modeler.autonomy.package_repair_runtime",
        producer_version="0.1.0",
        provenance=[attempt_artifact, source_artifact],
        created_at=_utc_now(),
        session_id=state.session_id,
        phase="package" if failed_step_id == "portable.package" else "roundtrip",
        error_code=error_code,
        failure_evidence=attempt_artifact,
        deterministic=deterministic,
        canonical_inputs_current=True,
        canonical_input_fingerprint=source.source.source_fingerprint,
        details=details,
    )
    if failure_path.is_file():
        stored = PackageRepairFailure.model_validate_json(failure_path.read_text(encoding="utf-8"))
        if stored != failure:
            raise ValueError("existing package repair failure differs from current evidence")
    else:
        write_immutable_json(root, failure_path, failure.model_dump(mode="json"))
    failure_artifact = artifact_for(root, failure_path)
    package_step = _workflow_step(workflow, "portable.package")
    original_package_id = str(package_step.parameters.get("package_id", ""))
    decision = classify_package_repair(
        failure=failure,
        budget=budget,
        usage=state.budget_usage,
        contract_id=f"package-repair-plan-{repair_index:02d}",
        profile_id=str(package_step.parameters.get("profile_id", "")),
        package_id=_repair_package_id(original_package_id, repair_index),
        repair_index=repair_index,
        provenance=[failure_artifact, source_artifact],
        created_at=_utc_now(),
        failure_contract_artifact=failure_artifact,
    )
    plan_artifact = None
    if decision.repair_plan is not None:
        plan_path = evidence_root / "plan.json"
        write_immutable_json(root, plan_path, decision.repair_plan.model_dump(mode="json"))
        plan_artifact = artifact_for(root, plan_path)
    return PreparedPackageRepair(
        failure=failure,
        failure_artifact=failure_artifact,
        decision=decision,
        plan_artifact=plan_artifact,
    )


def _action_attempt(
    root: Path,
    path: Path,
    *,
    plan: PackageRepairPlan,
    status: str,
    outputs: list[AutonomyArtifact],
    error: Exception | None = None,
) -> AutonomyArtifact:
    """Publish one immutable repair-owned host-attempt record."""

    payload: dict[str, Any] = {
        "schema_version": "0.1.0",
        "session_id": plan.session_id,
        "package_id": plan.package_id,
        "status": status,
        "outputs": [item.model_dump(mode="json") for item in outputs],
        "error_type": type(error).__name__ if error else None,
        "error_message": str(error)[:4000] if error else None,
        "recorded_at": _utc_now().isoformat(),
    }
    write_immutable_json(root, path, payload)
    return artifact_for(root, path)


def execute_package_repair(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    workflow: WorkflowPlan,
    *,
    plan_artifact: AutonomyArtifact,
) -> ExecutedPackageRepair:
    """Build a fresh derived package ID and require a fresh passed clean import."""

    plan_path = ensure_autonomy_path(root, root / plan_artifact.path, must_exist=True)
    if sha256_file(plan_path) != plan_artifact.sha256:
        raise ValueError("package repair plan is stale or tampered")
    plan = PackageRepairPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    if plan.session_id != state.session_id or plan.failure.path == plan_artifact.path:
        raise ValueError("package repair plan identity or failure binding is invalid")
    source, _source_path = _canonical_source(root, state, workflow)
    if source.source.source_fingerprint != plan.canonical_input_fingerprint:
        raise ValueError("package repair canonical source changed after planning")
    package_step = _workflow_step(workflow, "portable.package")
    run_id = str(package_step.parameters.get("run_id", ""))
    conversion_id = str(package_step.parameters.get("conversion_id", "")) or None
    receipt_path = plan_path.parent / "receipt.json"
    if receipt_path.is_file():
        receipt = PackageRepairReceipt.model_validate_json(receipt_path.read_text(encoding="utf-8"))
        package_artifact = receipt.package_manifest_after
        roundtrip_artifact = receipt.roundtrip_validation_after
        return ExecutedPackageRepair(
            receipt, artifact_for(root, receipt_path), package_artifact, roundtrip_artifact
        )
    package_path = (
        root / "exports" / "packages" / plan.profile_id / plan.package_id / "package_manifest.json"
    )
    roundtrip_path = (
        root
        / "optimization"
        / "runs"
        / run_id
        / "roundtrip"
        / plan.package_id
        / "roundtrip_validation.json"
    )
    outputs: list[AutonomyArtifact] = []
    error: Exception | None = None
    package_artifact: AutonomyArtifact | None = None
    roundtrip_artifact: AutonomyArtifact | None = None
    roundtrip_passed = False
    try:
        if not package_path.is_file():
            package_asset(
                state.job_id,
                profile_id=plan.profile_id,
                run_id=run_id,
                package_id=plan.package_id,
                material_conversion_id=conversion_id,
            )
        package = ExportPackageManifest.model_validate_json(
            package_path.read_text(encoding="utf-8")
        )
        if package.package_id != plan.package_id or package.run_id != run_id:
            raise ValueError("repair-owned package identity mismatch")
        package_artifact = artifact_for(root, package_path)
        outputs.append(package_artifact)
        if not roundtrip_path.is_file():
            validate_asset_package(
                state.job_id,
                plan.package_id,
                profile_id=plan.profile_id,
            )
        roundtrip = RoundTripValidation.model_validate_json(
            roundtrip_path.read_text(encoding="utf-8")
        )
        roundtrip_artifact = artifact_for(root, roundtrip_path)
        outputs.append(roundtrip_artifact)
        roundtrip_passed = bool(
            roundtrip.ok
            and roundtrip.status == "passed"
            and roundtrip.package_manifest.path == package_artifact.path
            and roundtrip.package_manifest.sha256 == package_artifact.sha256
        )
        if not roundtrip_passed:
            raise RuntimeError("repair-owned clean-import round trip did not pass")
    except Exception as exc:  # exact failure is preserved below; acceptance stays false.
        error = exc
    attempt_artifact = _action_attempt(
        root,
        plan_path.parent / "attempt.json",
        plan=plan,
        status="succeeded" if roundtrip_passed else "failed",
        outputs=outputs,
        error=error,
    )
    source_after, _ = _canonical_source(root, state, workflow)
    repaired = roundtrip_passed and error is None
    receipt = PackageRepairReceipt(
        contract_id=f"package-repair-receipt-{plan.repair_index:02d}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        input_sha256=plan_artifact.sha256,
        source_fingerprint=canonical_digest(
            {"plan": plan_artifact.sha256, "attempt": attempt_artifact.sha256}
        ),
        producer="codex_blender_modeler.autonomy.package_repair_runtime",
        producer_version="0.1.0",
        provenance=[plan_artifact, plan.failure, attempt_artifact],
        created_at=_utc_now(),
        session_id=state.session_id,
        repair_plan=plan_artifact,
        failure=plan.failure,
        host_attempts=[attempt_artifact],
        canonical_input_fingerprint_before=plan.canonical_input_fingerprint,
        canonical_input_fingerprint_after=source_after.source.source_fingerprint,
        package_manifest_after=package_artifact,
        roundtrip_validation_after=roundtrip_artifact,
        roundtrip_package_manifest_sha256=(
            package_artifact.sha256 if repaired and package_artifact is not None else None
        ),
        reserved_delta=plan.delta,
        budget_before=plan.budget_before,
        budget_after=plan.budget_after,
        outcome="repaired" if repaired else "failed",
        roundtrip_passed=repaired,
        package_accepted=repaired,
        completed_at=_utc_now(),
        notes=[
            "Repair used a fresh derived package ID and did not mutate canonical inputs."
            if repaired
            else f"Repair failed closed: {type(error).__name__}: {error}"
        ],
    )
    write_immutable_json(root, receipt_path, receipt.model_dump(mode="json"))
    return ExecutedPackageRepair(
        receipt,
        artifact_for(root, receipt_path),
        package_artifact if repaired else None,
        roundtrip_artifact if repaired else None,
    )


def latest_accepted_package_repair(
    root: Path,
    session_root: Path,
    state: AutonomyState,
    workflow: WorkflowPlan,
) -> ExecutedPackageRepair | None:
    """Recover the newest exact accepted repair without consulting mutable pointers."""

    repair_root = session_root / "package_repairs"
    if not repair_root.is_dir():
        return None
    for receipt_path in sorted(repair_root.glob("*/receipt.json"), reverse=True):
        receipt = PackageRepairReceipt.model_validate_json(receipt_path.read_text(encoding="utf-8"))
        if receipt.session_id != state.session_id or not receipt.package_accepted:
            continue
        plan_path = ensure_autonomy_path(root, root / receipt.repair_plan.path, must_exist=True)
        plan = PackageRepairPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        source, _ = _canonical_source(root, state, workflow)
        if source.source.source_fingerprint != plan.canonical_input_fingerprint:
            raise ValueError("accepted package repair canonical source is stale")
        for artifact in (receipt.package_manifest_after, receipt.roundtrip_validation_after):
            if artifact is None:
                raise ValueError("accepted package repair lacks exact output artifacts")
            path = ensure_autonomy_path(root, root / artifact.path, must_exist=True)
            if sha256_file(path) != artifact.sha256:
                raise ValueError("accepted package repair output is stale or tampered")
        return ExecutedPackageRepair(
            receipt,
            artifact_for(root, receipt_path),
            receipt.package_manifest_after,
            receipt.roundtrip_validation_after,
        )
    return None
