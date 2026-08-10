"""Job-facing Integrated Quality runner and immutable status inspection."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from ..analysis.models import AssemblyValidationReport
from ..blender_artifacts import sha256_file, stable_json_digest, write_json_atomic
from ..constraints.models import ConstraintSolution
from ..materials.fidelity_models import MaterialFidelityReport
from ..materials.models import MaterialValidationReport
from ..optimization.models import MeshPreflightReport
from ..packaging.models import RoundTripValidation
from ..qa.models import VisualQAReport
from ..workspace import job_dir
from .hard_gates import build_default_quality_gate_profile
from .models import (
    EvidenceAvailability,
    IntegratedQualityReport,
    IntegratedQualityReportManifest,
    ProducerIdentity,
    QualityArtifact,
    QualityGateProfile,
    QualityProvenance,
    quality_artifact_input_sha256,
)
from .reporting import write_integrated_quality_evidence
from .service import build_integrated_quality_report

_RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_T = TypeVar("_T", bound=BaseModel)


def _new_run_id() -> str:
    """Create a sortable job-local run identity that is safe as one path segment."""

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ").lower()
    return f"iq-{stamp}-{uuid4().hex[:8]}"


def _validate_run_id(run_id: str) -> str:
    """Reject path-like or otherwise non-portable integrated-quality run IDs."""

    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must match [a-z0-9][a-z0-9_-]{0,63}")
    return run_id


def _resolve_job_evidence(root: Path, value: str | Path | None) -> Path | None:
    """Resolve one supplied evidence path inside the job without permitting escape."""

    if value is None:
        return None
    supplied = Path(value)
    candidate = supplied if supplied.is_absolute() else root / supplied
    resolved = candidate.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"integrated quality evidence escaped the job: {value}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"integrated quality evidence does not exist: {value}")
    return resolved


def _load_model(path: Path | None, model: type[_T]) -> _T | None:
    """Load one strict evidence contract when its job-contained path was supplied."""

    if path is None:
        return None
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _load_structural_validation(
    path: Path | None,
) -> tuple[ConstraintSolution | None, list[AssemblyValidationReport]]:
    """Accept either measured-constraint or assembly validation at the public input slot."""

    if path is None:
        return None, []
    payload = path.read_text(encoding="utf-8")
    try:
        return ConstraintSolution.model_validate_json(payload), []
    except ValueError:
        return None, [AssemblyValidationReport.model_validate_json(payload)]


def _artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    producer: ProducerIdentity,
) -> QualityArtifact:
    """Bind one exact job-contained evidence file into report provenance."""

    resolved = path.resolve()
    relative = resolved.relative_to(root.resolve()).as_posix()
    produced_at = datetime.fromtimestamp(resolved.stat().st_mtime, tz=UTC)
    return QualityArtifact(
        artifact_id=artifact_id,
        kind=kind,
        relative_path=relative,
        sha256=sha256_file(resolved),
        producer=producer,
        produced_at=produced_at,
    )


def _availability(
    *,
    evidence_id: str,
    axis: str,
    artifact_id: str | None,
    reason: str,
) -> EvidenceAvailability:
    """Represent missing inputs as unavailable instead of synthesizing a quality score."""

    return EvidenceAvailability(
        evidence_id=evidence_id,
        axis=axis,  # type: ignore[arg-type]
        status="available" if artifact_id is not None else "unavailable",
        artifact_id=artifact_id,
        confidence=1.0 if artifact_id is not None else 0.0,
        reason=reason,
    )


def _load_or_create_default_profile(
    root: Path,
    *,
    job_id: str,
    run_id: str,
    source_fingerprint: str,
    producer: ProducerIdentity,
    provenance: list[QualityArtifact],
    created_at: datetime,
) -> tuple[QualityGateProfile, Path]:
    """Create once or safely reuse the exact default profile after an interrupted publish."""

    profile_path = (
        root
        / "reports"
        / "integrated_quality"
        / "profiles"
        / f"{run_id}.json"
    )
    if profile_path.is_file():
        profile = QualityGateProfile.model_validate_json(
            profile_path.read_text(encoding="utf-8")
        )
        expected_identity = (job_id, f"iq-{run_id}", f"iq-{run_id}")
        actual_identity = (profile.job_id, profile.workflow_id, profile.dispatch_id)
        if actual_identity != expected_identity:
            raise ValueError("existing default quality profile identity is stale")
        if profile.source_fingerprint != source_fingerprint:
            raise ValueError("existing default quality profile source is stale")
        expected_input = quality_artifact_input_sha256(provenance)
        if profile.input_sha256 is not None and profile.input_sha256 != expected_input:
            raise ValueError("existing default quality profile provenance is stale")
        return profile, profile_path
    profile = build_default_quality_gate_profile(
        profile_id="autonomous-static-prop-v1",
        job_id=job_id,
        workflow_id=f"iq-{run_id}",
        dispatch_id=f"iq-{run_id}",
        source_fingerprint=source_fingerprint,
        producer=producer,
        provenance=provenance,
        created_at=created_at,
    )
    write_json_atomic(profile_path, profile.model_dump(mode="json"))
    return profile, profile_path


def _bound_artifact_path(root: Path, relative_path: str) -> Path:
    """Resolve a provenance path while rejecting missing files, escapes, and symlink escapes."""

    candidate = (root / Path(relative_path)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"bound artifact escaped the job: {relative_path}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"bound artifact is missing: {relative_path}")
    return candidate


def _provenance_errors(
    root: Path,
    report: IntegratedQualityReport,
    manifest: IntegratedQualityReportManifest,
) -> list[str]:
    """Re-hash every provenance input and re-derive public source/profile bindings."""

    errors: list[str] = []
    provenance = report.provenance
    if manifest.source_fingerprint != provenance.source_fingerprint:
        errors.append("manifest source fingerprint mismatch")
    expected_input = stable_json_digest(
        [item.model_dump(mode="json") for item in provenance.artifacts]
    )
    if provenance.input_sha256 != expected_input:
        errors.append("provenance input SHA-256 mismatch")

    artifact_by_id = {item.artifact_id: item for item in provenance.artifacts}
    for artifact in provenance.artifacts:
        try:
            artifact_path = _bound_artifact_path(root, artifact.relative_path)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(str(exc))
            continue
        if sha256_file(artifact_path) != artifact.sha256:
            errors.append(f"provenance artifact SHA-256 mismatch: {artifact.artifact_id}")

    profile_artifact = artifact_by_id.get("quality_profile")
    if profile_artifact is None:
        errors.append("quality profile provenance artifact is missing")
        return errors
    if profile_artifact.sha256 != report.gate_profile_sha256:
        errors.append("quality profile report binding mismatch")
    try:
        profile_path = _bound_artifact_path(root, profile_artifact.relative_path)
        profile = QualityGateProfile.model_validate_json(
            profile_path.read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ValueError) as exc:
        errors.append(f"quality profile is invalid: {exc}")
        return errors
    profile_identity = (profile.job_id, profile.workflow_id, profile.dispatch_id)
    report_identity = (report.job_id, report.workflow_id, report.dispatch_id)
    if profile_identity != report_identity:
        errors.append("quality profile identity mismatch")
    if profile.profile_id != report.gate_profile_id:
        errors.append("quality profile ID mismatch")
    if profile.source_fingerprint != provenance.source_fingerprint:
        errors.append("quality profile source fingerprint mismatch")

    evidence_artifacts = [
        item for item in provenance.artifacts if item.artifact_id != "quality_profile"
    ]
    expected_profile_input = quality_artifact_input_sha256(evidence_artifacts)
    if profile.input_sha256 is not None and profile.input_sha256 != expected_profile_input:
        errors.append("quality profile provenance input SHA-256 mismatch")
    expected_source = stable_json_digest(
        {
            "job_id": report.job_id,
            "evidence": [item.model_dump(mode="json") for item in evidence_artifacts],
        }
    )
    if provenance.source_fingerprint != expected_source:
        errors.append("public evidence source fingerprint mismatch")
    return errors


def run_integrated_quality(
    job_id: str,
    *,
    run_id: str | None = None,
    quality_profile_path: str | Path | None = None,
    qa_report_path: str | Path | None = None,
    validation_path: str | Path | None = None,
    material_validation_path: str | Path | None = None,
    material_fidelity_path: str | Path | None = None,
    mesh_preflight_path: str | Path | None = None,
    roundtrip_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compose one immutable companion report from explicitly supplied existing evidence."""

    root = job_dir(job_id).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"job does not exist: {job_id}")
    selected_run_id = _validate_run_id(run_id or _new_run_id())
    output_dir = root / "reports" / "integrated_quality" / "runs" / selected_run_id
    if output_dir.exists():
        raise FileExistsError(f"integrated quality run already exists: {selected_run_id}")

    paths = {
        "quality_profile": _resolve_job_evidence(root, quality_profile_path),
        "visual_qa": _resolve_job_evidence(root, qa_report_path),
        "validation": _resolve_job_evidence(root, validation_path),
        "material_validation": _resolve_job_evidence(root, material_validation_path),
        "material_fidelity": _resolve_job_evidence(root, material_fidelity_path),
        "mesh_preflight": _resolve_job_evidence(root, mesh_preflight_path),
        "roundtrip": _resolve_job_evidence(root, roundtrip_path),
    }
    producer = ProducerIdentity(
        name="integrated-quality-public-service",
        version="0.1.0",
    )
    evidence_artifacts = [
        _artifact(root, path, artifact_id=key, kind=key, producer=producer)
        for key, path in paths.items()
        if key != "quality_profile" and path is not None
    ]
    evidence_fingerprint = stable_json_digest(
        {
            "job_id": job_id,
            "evidence": [item.model_dump(mode="json") for item in evidence_artifacts],
        }
    )
    now = datetime.now(UTC)
    profile_path = paths["quality_profile"]
    if profile_path is None:
        profile, profile_path = _load_or_create_default_profile(
            root,
            job_id=job_id,
            run_id=selected_run_id,
            source_fingerprint=evidence_fingerprint,
            producer=producer,
            provenance=evidence_artifacts,
            created_at=now,
        )
    else:
        profile = QualityGateProfile.model_validate_json(
            profile_path.read_text(encoding="utf-8")
        )
        if profile.job_id != job_id:
            raise ValueError("quality profile belongs to a different job")
        if profile.source_fingerprint != evidence_fingerprint:
            raise ValueError("quality profile source fingerprint is stale")
        expected_profile_input = quality_artifact_input_sha256(evidence_artifacts)
        if (
            profile.input_sha256 is not None
            and profile.input_sha256 != expected_profile_input
        ):
            raise ValueError("quality profile provenance is stale")

    profile_artifact = _artifact(
        root,
        profile_path,
        artifact_id="quality_profile",
        kind="quality_gate_profile",
        producer=profile.producer,
    )
    artifacts = [profile_artifact, *evidence_artifacts]
    artifact_ids = {item.artifact_id for item in evidence_artifacts}
    provenance = QualityProvenance(
        job_id=job_id,
        workflow_id=profile.workflow_id,
        dispatch_id=profile.dispatch_id,
        source_fingerprint=profile.source_fingerprint,
        input_sha256=stable_json_digest(
            [item.model_dump(mode="json") for item in artifacts]
        ),
        artifacts=artifacts,
    )
    visual_qa = _load_model(paths["visual_qa"], VisualQAReport)
    constraints, assembly_reports = _load_structural_validation(paths["validation"])
    material_validation = _load_model(
        paths["material_validation"], MaterialValidationReport
    )
    material_fidelity = _load_model(
        paths["material_fidelity"], MaterialFidelityReport
    )
    mesh_preflight = _load_model(paths["mesh_preflight"], MeshPreflightReport)
    roundtrip = _load_model(paths["roundtrip"], RoundTripValidation)
    availability = [
        _availability(
            evidence_id="reference-evidence",
            axis="reference_alignment",
            artifact_id="visual_qa" if "visual_qa" in artifact_ids else None,
            reason=(
                "Exact V0.6 report supplied."
                if visual_qa is not None
                else "No V0.6 report was supplied; reference alignment is unscorable."
            ),
        ),
        _availability(
            evidence_id="structural-evidence",
            axis="structural_integrity",
            artifact_id=(
                "validation"
                if "validation" in artifact_ids
                else "mesh_preflight"
                if "mesh_preflight" in artifact_ids
                else None
            ),
            reason=(
                "Explicit validation evidence supplied."
                if constraints is not None or assembly_reports or mesh_preflight is not None
                else "No structural validation was supplied; the axis is unscorable."
            ),
        ),
        _availability(
            evidence_id="material-evidence",
            axis="material_fidelity",
            artifact_id=(
                "material_fidelity"
                if "material_fidelity" in artifact_ids
                else "material_validation"
                if "material_validation" in artifact_ids
                else None
            ),
            reason=(
                "Explicit material evidence supplied."
                if material_validation is not None or material_fidelity is not None
                else "No V0.5 material evidence was supplied; the axis is unscorable."
            ),
        ),
        _availability(
            evidence_id="production-evidence",
            axis="production_readiness",
            artifact_id=(
                "roundtrip"
                if "roundtrip" in artifact_ids
                else "mesh_preflight"
                if "mesh_preflight" in artifact_ids
                else None
            ),
            reason=(
                "Explicit V0.7 evidence supplied."
                if mesh_preflight is not None or roundtrip is not None
                else "No V0.7 clean-import evidence was supplied; the axis is unscorable."
            ),
        ),
    ]
    report = build_integrated_quality_report(
        report_id=f"report-{selected_run_id}",
        provenance=provenance,
        gate_profile=profile,
        gate_profile_sha256=profile_artifact.sha256,
        producer=producer,
        created_at=now,
        evidence_availability=availability,
        reference_evidence_id="reference-evidence",
        structural_evidence_id="structural-evidence",
        material_evidence_id="material-evidence",
        production_evidence_id="production-evidence",
        visual_qa=visual_qa,
        constraints=constraints,
        assembly_reports=assembly_reports,
        material_validation=material_validation,
        material_fidelity=material_fidelity,
        mesh_preflight=mesh_preflight,
        roundtrip=roundtrip,
        notes=[
            "Omitted evidence remains unscorable and is never replaced with an inferred score."
        ],
    )
    manifest = write_integrated_quality_evidence(
        root,
        report,
        output_dir=output_dir,
        include_pdf=True,
    )
    latest_path = root / "reports" / "integrated_quality" / "latest.json"
    write_json_atomic(
        latest_path,
        {
            "schema_version": "0.1.0",
            "job_id": job_id,
            "run_id": selected_run_id,
            "report_path": manifest.json_path,
            "report_sha256": manifest.json_sha256,
            "manifest_path": (
                output_dir / "integrated_quality_report.manifest.json"
            ).relative_to(root).as_posix(),
        },
    )
    return {
        "run_id": selected_run_id,
        "report": report.model_dump(mode="json"),
        "manifest": manifest.model_dump(mode="json"),
        "latest_path": latest_path.relative_to(root).as_posix(),
    }


def get_integrated_quality_status(
    job_id: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Verify one exact integrated-quality run without treating latest.json as authority."""

    root = job_dir(job_id).resolve()
    if run_id is None:
        latest_path = root / "reports" / "integrated_quality" / "latest.json"
        if not latest_path.is_file():
            return {"job_id": job_id, "status": "absent", "run_id": None}
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        selected_run_id = _validate_run_id(str(latest["run_id"]))
    else:
        selected_run_id = _validate_run_id(run_id)
    run_root = root / "reports" / "integrated_quality" / "runs" / selected_run_id
    report_path = run_root / "integrated_quality_report.json"
    manifest_path = run_root / "integrated_quality_report.manifest.json"
    if not report_path.is_file() or not manifest_path.is_file():
        return {"job_id": job_id, "status": "absent", "run_id": selected_run_id}
    report_relative = report_path.relative_to(root).as_posix()
    manifest_relative = manifest_path.relative_to(root).as_posix()
    try:
        report_path = _bound_artifact_path(root, report_relative)
        manifest_path = _bound_artifact_path(root, manifest_relative)
    except (FileNotFoundError, ValueError) as exc:
        return {
            "job_id": job_id,
            "run_id": selected_run_id,
            "status": "invalid",
            "outcome": None,
            "quality_accepted": False,
            "report_path": report_relative,
            "manifest_path": manifest_relative,
            "errors": [str(exc)],
        }
    try:
        manifest = IntegratedQualityReportManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        report = IntegratedQualityReport.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        return {
            "job_id": job_id,
            "run_id": selected_run_id,
            "status": "invalid",
            "outcome": None,
            "quality_accepted": False,
            "report_path": report_relative,
            "manifest_path": manifest_relative,
            "errors": [f"integrated quality contract is invalid: {exc}"],
        }
    errors: list[str] = []
    if manifest.job_id != job_id or report.job_id != job_id:
        errors.append("job identity mismatch")
    if manifest.report_id != report.report_id:
        errors.append("report identity mismatch")
    if (manifest.workflow_id, manifest.dispatch_id) != (
        report.workflow_id,
        report.dispatch_id,
    ):
        errors.append("workflow or dispatch identity mismatch")
    if manifest.json_path != report_relative:
        errors.append("report path mismatch")
    if sha256_file(report_path) != manifest.json_sha256:
        errors.append("report SHA-256 mismatch")
    errors.extend(_provenance_errors(root, report, manifest))
    if manifest.pdf_path is not None:
        try:
            pdf_path = _bound_artifact_path(root, manifest.pdf_path)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(str(exc).replace("bound artifact", "derived PDF"))
        else:
            if sha256_file(pdf_path) != manifest.pdf_sha256:
                errors.append("derived PDF SHA-256 mismatch")
    return {
        "job_id": job_id,
        "run_id": selected_run_id,
        "status": "invalid" if errors else "current",
        "outcome": report.outcome,
        "quality_accepted": report.quality_accepted,
        "report_path": report_relative,
        "manifest_path": manifest_relative,
        "errors": errors,
    }
