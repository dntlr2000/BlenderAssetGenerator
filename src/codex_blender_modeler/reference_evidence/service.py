"""Run-owned service for immutable Autonomous Quality reference evidence."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from PIL import Image
from pydantic import BaseModel, TypeAdapter

from ..qa.hashing import canonical_json_sha256
from .camera_hypotheses import build_camera_hypothesis_set
from .models import (
    AdvisoryObservation,
    CameraHypothesisSet,
    EvidenceArtifact,
    EvidenceProvenance,
    JobId,
    PortableId,
    ReferenceEvidence,
    ReferenceEvidenceRunResult,
    RelativePath,
)
from .reporting import render_reference_evidence_markdown
from .segmentation import generate_foreground_mask_candidates

_RUN_RESULT_NAME = "run_result.json"
_RUN_MANIFEST_NAME = "run_manifest.json"


class AdvisoryReferenceProvider(Protocol):
    """Describe an optional read-only provider that may return observations only."""

    provider_name: str
    provider_version: str

    def observe(self, image_path: Path) -> list[tuple[str, str, float]]:
        """Return category, message, and confidence without writing or selecting evidence."""


def _sha256_file(path: Path) -> str:
    """Hash one source or generated artifact using exact file bytes."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_contained(root: Path, relative_path: str) -> Path:
    """Validate a job-relative path and prove that it remains inside the job root."""

    # Pydantic validates the public contract; this explicit path check protects host I/O.
    checked = TypeAdapter(RelativePath).validate_python(relative_path)
    resolved_root = root.expanduser().resolve()
    resolved = (resolved_root / Path(*checked.split("/"))).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("path escapes the job workspace") from error
    return resolved


def _relative_posix(root: Path, path: Path) -> str:
    """Convert a proven contained path into normalized POSIX job-relative syntax."""

    return path.resolve().relative_to(root.resolve()).as_posix()


def _write_model(path: Path, value: BaseModel) -> None:
    """Publish one validated JSON model atomically inside a new immutable run."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_json(path: Path, value: dict[str, object]) -> None:
    """Write one host-owned JSON receipt atomically inside an unpublished stage."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _advisory_provider_binding(
    provider: AdvisoryReferenceProvider | None,
) -> dict[str, str] | None:
    """Bind an optional advisory producer identity without granting it authority."""

    if provider is None:
        return None
    return {
        "provider_name": provider.provider_name,
        "provider_version": provider.provider_version,
    }


def _request_binding(
    *,
    job_id: str,
    run_id: str,
    workflow_id: str | None,
    dispatch_id: str | None,
    source_path: str,
    source_sha256: str,
    source_byte_size: int,
    source_media_type: str,
    source_fingerprint: str,
    provider: str,
    advisory_provider: AdvisoryReferenceProvider | None,
) -> dict[str, object]:
    """Describe the exact invocation that may adopt or publish one immutable run."""

    return {
        "job_id": job_id,
        "run_id": run_id,
        "workflow_id": workflow_id,
        "dispatch_id": dispatch_id,
        "source_path": source_path,
        "source_sha256": source_sha256,
        "source_byte_size": source_byte_size,
        "source_media_type": source_media_type,
        "source_fingerprint": source_fingerprint,
        "requested_provider": provider,
        "advisory_provider": _advisory_provider_binding(advisory_provider),
    }


def _compatible_existing_binding(
    run_root: Path,
    *,
    current: dict[str, object],
    legacy: dict[str, object] | None,
) -> dict[str, object]:
    """Select an exact legacy request only when an existing manifest proves that binding."""

    if legacy is None:
        return current
    manifest_path = run_root / _RUN_MANIFEST_NAME
    if not manifest_path.is_file():
        return current
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("request_binding") == legacy:
        return legacy
    return current


def _logical_run_path(run_relative: str, name: str) -> str:
    """Return one normalized logical artifact path independent of staging location."""

    return f"{run_relative}/{name}"


def _physical_run_artifact(
    run_root: Path,
    *,
    run_relative: str,
    artifact_path: str,
) -> Path:
    """Map a bound logical run path to a physical final or staging directory."""

    checked = TypeAdapter(RelativePath).validate_python(artifact_path)
    prefix = f"{run_relative}/"
    if not checked.startswith(prefix):
        raise ValueError(f"reference-evidence artifact escaped its run: {checked}")
    suffix = checked.removeprefix(prefix)
    candidate = (run_root / Path(*suffix.split("/"))).resolve()
    try:
        candidate.relative_to(run_root.resolve())
    except ValueError as error:
        raise ValueError("reference-evidence artifact escaped its physical run") from error
    return candidate


def _artifact_record(
    run_root: Path,
    *,
    run_relative: str,
    artifact_path: str,
) -> dict[str, object]:
    """Create an exact path, size, and hash record for one staged run artifact."""

    path = _physical_run_artifact(
        run_root,
        run_relative=run_relative,
        artifact_path=artifact_path,
    )
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": artifact_path,
        "sha256": _sha256_file(path),
        "byte_size": path.stat().st_size,
    }


def _validate_artifact_record(
    run_root: Path,
    *,
    run_relative: str,
    record: object,
) -> str:
    """Validate one manifest artifact against exact contained file bytes."""

    if not isinstance(record, dict) or set(record) != {"path", "sha256", "byte_size"}:
        raise ValueError("reference-evidence manifest artifact has invalid fields")
    artifact_path = TypeAdapter(RelativePath).validate_python(record["path"])
    sha256 = record["sha256"]
    byte_size = record["byte_size"]
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise ValueError("reference-evidence manifest artifact has invalid SHA-256")
    if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0:
        raise ValueError("reference-evidence manifest artifact has invalid byte size")
    physical = _physical_run_artifact(
        run_root,
        run_relative=run_relative,
        artifact_path=artifact_path,
    )
    if (
        not physical.is_file()
        or physical.stat().st_size != byte_size
        or _sha256_file(physical) != sha256
    ):
        raise ValueError(f"reference-evidence artifact is missing or stale: {artifact_path}")
    return artifact_path


def _load_complete_run(
    run_root: Path,
    *,
    run_relative: str,
    expected_binding: dict[str, object],
) -> ReferenceEvidenceRunResult:
    """Adopt only a complete run whose identities, paths, and hashes remain exact."""

    manifest_path = run_root / _RUN_MANIFEST_NAME
    result_path = run_root / _RUN_RESULT_NAME
    if not manifest_path.is_file() or not result_path.is_file():
        raise ValueError("reference-evidence run is incomplete: manifest/result missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_keys = {
        "schema_version",
        "status",
        "request_binding",
        "artifacts",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise ValueError("reference-evidence run manifest has invalid fields")
    if manifest["schema_version"] != "0.1.0" or manifest["status"] != "complete":
        raise ValueError("reference-evidence run manifest is not complete")
    if manifest["request_binding"] != expected_binding:
        raise ValueError("reference-evidence run belongs to a different exact request")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("reference-evidence run manifest has no artifacts")
    recorded_paths = [
        _validate_artifact_record(
            run_root,
            run_relative=run_relative,
            record=record,
        )
        for record in artifacts
    ]
    if len(recorded_paths) != len(set(recorded_paths)):
        raise ValueError("reference-evidence run manifest repeats an artifact path")
    physical_paths: set[str] = set()
    for path in run_root.rglob("*"):
        if path.is_symlink():
            raise ValueError("reference-evidence run must not contain symbolic links")
        if path.is_file():
            suffix = path.relative_to(run_root).as_posix()
            physical_paths.add(_logical_run_path(run_relative, suffix))
    expected_physical_paths = {
        *recorded_paths,
        _logical_run_path(run_relative, _RUN_MANIFEST_NAME),
    }
    if physical_paths != expected_physical_paths:
        raise ValueError("reference-evidence run contains unrecorded or missing files")

    result = ReferenceEvidenceRunResult.model_validate_json(
        result_path.read_text(encoding="utf-8")
    )
    expected_identity = (
        expected_binding["run_id"],
        expected_binding["job_id"],
        expected_binding["workflow_id"],
        expected_binding["dispatch_id"],
    )
    if (result.run_id, result.job_id, result.workflow_id, result.dispatch_id) != expected_identity:
        raise ValueError("reference-evidence result identity differs from its request")
    if (
        result.source_image.path != expected_binding["source_path"]
        or result.source_image.sha256 != expected_binding["source_sha256"]
        or result.source_image.byte_size != expected_binding["source_byte_size"]
        or result.source_image.media_type != expected_binding["source_media_type"]
        or result.source_fingerprint != expected_binding["source_fingerprint"]
        or result.provenance.parameters.get("requested_provider")
        != expected_binding["requested_provider"]
    ):
        raise ValueError("reference-evidence result source/provider binding is stale")

    evidence_path = _physical_run_artifact(
        run_root,
        run_relative=run_relative,
        artifact_path=result.reference_evidence_path,
    )
    cameras_path = _physical_run_artifact(
        run_root,
        run_relative=run_relative,
        artifact_path=result.camera_hypothesis_set_path,
    )
    summary_path = _physical_run_artifact(
        run_root,
        run_relative=run_relative,
        artifact_path=result.summary_path,
    )
    if (
        _sha256_file(evidence_path) != result.reference_evidence_sha256
        or _sha256_file(cameras_path) != result.camera_hypothesis_set_sha256
        or _sha256_file(summary_path) != result.summary_sha256
    ):
        raise ValueError("reference-evidence result artifact binding is stale")
    evidence = load_reference_evidence(evidence_path)
    cameras = load_camera_hypothesis_set(cameras_path)
    if (
        (evidence.run_id, evidence.job_id, evidence.workflow_id, evidence.dispatch_id)
        != expected_identity
        or evidence.source_image != result.source_image
        or evidence.source_fingerprint != result.source_fingerprint
        or evidence.provenance.parameters.get("requested_provider")
        != expected_binding["requested_provider"]
    ):
        raise ValueError("reference-evidence document identity/source binding is stale")
    expected_evidence_input = canonical_json_sha256(expected_binding)
    if (
        result.input_sha256 != expected_evidence_input
        or evidence.input_sha256 != expected_evidence_input
    ):
        raise ValueError("reference-evidence document input binding is stale")
    expected_camera_input = canonical_json_sha256(
        {
            "reference_evidence_path": result.reference_evidence_path,
            "reference_evidence_sha256": result.reference_evidence_sha256,
            "source_image_sha256": evidence.source_image.sha256,
            "source_fingerprint": evidence.source_fingerprint,
        }
    )
    if (
        (cameras.run_id, cameras.job_id, cameras.workflow_id, cameras.dispatch_id)
        != expected_identity
        or cameras.source_fingerprint != result.source_fingerprint
        or cameras.reference_evidence_path != result.reference_evidence_path
        or cameras.reference_evidence_sha256 != result.reference_evidence_sha256
        or cameras.input_sha256 != expected_camera_input
    ):
        raise ValueError("camera-hypothesis binding is stale")

    expected_paths = {
        _logical_run_path(run_relative, _RUN_RESULT_NAME),
        result.reference_evidence_path,
        result.camera_hypothesis_set_path,
        result.summary_path,
        *(candidate.artifact.path for candidate in evidence.mask_candidates),
    }
    if set(recorded_paths) != expected_paths:
        raise ValueError("reference-evidence run manifest artifact set is incomplete")
    for candidate in evidence.mask_candidates:
        mask_path = _physical_run_artifact(
            run_root,
            run_relative=run_relative,
            artifact_path=candidate.artifact.path,
        )
        if (
            _sha256_file(mask_path) != candidate.artifact.sha256
            or mask_path.stat().st_size != candidate.artifact.byte_size
        ):
            raise ValueError(
                f"reference-evidence mask binding is stale: {candidate.artifact.path}"
            )
    return result


def _quarantine_interrupted_stage(root: Path, stage_root: Path, run_id: str) -> Path:
    """Preserve a non-adoptable staging directory under interrupted evidence."""

    quarantine_root = _resolve_contained(root, "reference_evidence/interrupted_staging")
    quarantine_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = quarantine_root / f"{run_id}-{timestamp}-{uuid4().hex[:8]}"
    os.replace(stage_root, destination)
    return destination


def _advisory_observations(
    provider: AdvisoryReferenceProvider | None,
    image_path: Path,
) -> list[AdvisoryObservation]:
    """Normalize optional provider advice while withholding artifact-selection authority."""

    if provider is None:
        return []
    allowed = {"foreground", "camera", "occlusion", "uncertainty"}
    output: list[AdvisoryObservation] = []
    for index, item in enumerate(provider.observe(image_path), start=1):
        category, message, confidence = item
        if category not in allowed:
            raise ValueError(f"unsupported advisory category: {category}")
        output.append(
            AdvisoryObservation(
                observation_id=f"advisory-{index:02d}",
                category=category,
                message=message,
                confidence=confidence,
                provenance=EvidenceProvenance(
                    producer=provider.provider_name,
                    producer_version=provider.provider_version,
                    provider="advisory",
                    method="read_only_observation",
                    deterministic=False,
                    advisory_only=True,
                ),
            )
        )
    return output


def _build_staged_run(
    root: Path,
    stage_root: Path,
    *,
    run_relative: str,
    request_binding: dict[str, object],
    source: Path,
    provider: Literal["auto", "pillow", "opencv"],
    advisory_provider: AdvisoryReferenceProvider | None,
) -> ReferenceEvidenceRunResult:
    """Build a complete logical run inside a contained unpublished directory."""

    run_id = str(request_binding["run_id"])
    job_id = str(request_binding["job_id"])
    workflow_id = request_binding["workflow_id"]
    dispatch_id = request_binding["dispatch_id"]
    masks_relative = _logical_run_path(run_relative, "masks")
    masks_root = stage_root / "masks"
    masks_root.mkdir(parents=True, exist_ok=False)
    created_at = datetime.now(UTC)
    candidates, warnings = generate_foreground_mask_candidates(
        source,
        masks_root,
        masks_relative,
        provider=provider,
    )
    selected = candidates[0]
    status: Literal["ready", "underconstrained", "unscorable"]
    status = "ready" if selected.status == "usable" else "underconstrained"
    providers = {item.provenance.provider for item in candidates}
    aggregate_provider: Literal["pillow", "opencv", "mixed", "advisory"] = (
        "mixed" if len(providers) > 1 else next(iter(providers))
    )
    request_input_sha256 = canonical_json_sha256(request_binding)
    evidence = ReferenceEvidence(
        schema_version="0.1.0",
        evidence_id=f"{run_id}-reference",
        run_id=run_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        input_sha256=request_input_sha256,
        source_image=EvidenceArtifact(
            artifact_id="source-image",
            path=str(request_binding["source_path"]),
            sha256=str(request_binding["source_sha256"]),
            media_type=str(request_binding["source_media_type"]),
            byte_size=int(request_binding["source_byte_size"]),
        ),
        source_fingerprint=str(request_binding["source_fingerprint"]),
        mask_candidates=candidates,
        selected_candidate_id=selected.candidate_id,
        status=status,
        advisory_observations=_advisory_observations(advisory_provider, source),
        provenance=EvidenceProvenance(
            producer="codex_blender_modeler.reference_evidence.service",
            producer_version="0.1.0",
            provider=aggregate_provider,
            method="bounded_foreground_evidence_v1",
            deterministic=True,
            parameters={"requested_provider": provider, "maximum_mask_candidates": 3},
        ),
        assumptions=[
            "Foreground candidates are diagnostic hypotheses, not segmentation ground truth."
        ],
        warnings=warnings,
        limitations=[
            "Single-image evidence cannot recover hidden geometry or absolute scale.",
            "Shadow and reflection likelihoods are bounded image heuristics.",
        ],
        created_at=created_at,
    )
    evidence_path = stage_root / "reference_evidence.json"
    evidence_relative = _logical_run_path(run_relative, evidence_path.name)
    _write_model(evidence_path, evidence)
    evidence_sha256 = _sha256_file(evidence_path)
    camera_input_sha256 = canonical_json_sha256(
        {
            "reference_evidence_path": evidence_relative,
            "reference_evidence_sha256": evidence_sha256,
            "source_image_sha256": evidence.source_image.sha256,
            "source_fingerprint": evidence.source_fingerprint,
        }
    )
    cameras = build_camera_hypothesis_set(
        evidence,
        source,
        reference_evidence_path=evidence_relative,
        reference_evidence_sha256=evidence_sha256,
        input_sha256=camera_input_sha256,
        created_at=created_at,
    )
    cameras_path = stage_root / "camera_hypothesis_set.json"
    cameras_relative = _logical_run_path(run_relative, cameras_path.name)
    _write_model(cameras_path, cameras)
    summary_path = stage_root / "reference_evidence_summary.md"
    summary_relative = _logical_run_path(run_relative, summary_path.name)
    summary_path.write_text(
        render_reference_evidence_markdown(evidence, cameras),
        encoding="utf-8",
    )
    result = ReferenceEvidenceRunResult(
        schema_version="0.1.0",
        run_id=run_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        input_sha256=request_input_sha256,
        source_image=evidence.source_image,
        reference_evidence_path=evidence_relative,
        reference_evidence_sha256=evidence_sha256,
        camera_hypothesis_set_path=cameras_relative,
        camera_hypothesis_set_sha256=_sha256_file(cameras_path),
        summary_path=summary_relative,
        summary_sha256=_sha256_file(summary_path),
        source_fingerprint=evidence.source_fingerprint,
        provenance=EvidenceProvenance(
            producer="codex_blender_modeler.reference_evidence.service",
            producer_version="0.1.0",
            provider=aggregate_provider,
            method="immutable_reference_evidence_run_v1",
            deterministic=True,
            parameters={"requested_provider": provider},
        ),
        created_at=created_at,
    )
    result_path = stage_root / _RUN_RESULT_NAME
    result_relative = _logical_run_path(run_relative, result_path.name)
    _write_model(result_path, result)
    artifact_paths = [
        result_relative,
        result.reference_evidence_path,
        result.camera_hypothesis_set_path,
        result.summary_path,
        *(candidate.artifact.path for candidate in evidence.mask_candidates),
    ]
    manifest = {
        "schema_version": "0.1.0",
        "status": "complete",
        "request_binding": request_binding,
        "artifacts": [
            _artifact_record(
                stage_root,
                run_relative=run_relative,
                artifact_path=artifact_path,
            )
            for artifact_path in artifact_paths
        ],
    }
    _write_json(stage_root / _RUN_MANIFEST_NAME, manifest)
    return result


def run_reference_evidence(
    job_root: Path,
    *,
    job_id: str,
    run_id: str,
    source_image_path: str,
    workflow_id: str | None = None,
    dispatch_id: str | None = None,
    provider: Literal["auto", "pillow", "opencv"] = "auto",
    advisory_provider: AdvisoryReferenceProvider | None = None,
) -> ReferenceEvidenceRunResult:
    """Atomically publish or safely adopt one exact immutable evidence/camera run."""

    root = job_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    TypeAdapter(JobId).validate_python(job_id)
    TypeAdapter(PortableId).validate_python(run_id)
    if workflow_id is not None:
        TypeAdapter(PortableId).validate_python(workflow_id)
    if dispatch_id is not None:
        TypeAdapter(PortableId).validate_python(dispatch_id)
    if provider not in {"auto", "pillow", "opencv"}:
        raise ValueError(f"unsupported reference-evidence provider: {provider}")
    source = _resolve_contained(root, source_image_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    source_media_type = ImageMediaType.from_path(source)
    with Image.open(source) as opened:
        opened.verify()
    run_relative = f"reference_evidence/runs/{run_id}"
    run_root = _resolve_contained(root, run_relative)
    source_sha256 = _sha256_file(source)
    source_relative = _relative_posix(root, source)
    requested_workflow_id = workflow_id
    requested_dispatch_id = dispatch_id
    workflow_id = workflow_id or "reference-standalone"
    dispatch_id = dispatch_id or "reference-standalone"
    source_fingerprint = canonical_json_sha256(
        {
            "schema_version": "0.1.0",
            "job_id": job_id,
            "workflow_id": workflow_id,
            "dispatch_id": dispatch_id,
            "source_path": source_relative,
            "source_sha256": source_sha256,
        }
    )
    binding = _request_binding(
        job_id=job_id,
        run_id=run_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        source_path=source_relative,
        source_sha256=source_sha256,
        source_byte_size=source.stat().st_size,
        source_media_type=source_media_type,
        source_fingerprint=source_fingerprint,
        provider=provider,
        advisory_provider=advisory_provider,
    )
    legacy_binding: dict[str, object] | None = None
    if (
        requested_workflow_id != workflow_id
        or requested_dispatch_id != dispatch_id
    ):
        legacy_source_fingerprint = canonical_json_sha256(
            {
                "schema_version": "0.1.0",
                "job_id": job_id,
                "workflow_id": requested_workflow_id,
                "dispatch_id": requested_dispatch_id,
                "source_path": source_relative,
                "source_sha256": source_sha256,
            }
        )
        legacy_binding = _request_binding(
            job_id=job_id,
            run_id=run_id,
            workflow_id=requested_workflow_id,
            dispatch_id=requested_dispatch_id,
            source_path=source_relative,
            source_sha256=source_sha256,
            source_byte_size=source.stat().st_size,
            source_media_type=source_media_type,
            source_fingerprint=legacy_source_fingerprint,
            provider=provider,
            advisory_provider=advisory_provider,
        )
    if run_root.exists():
        if not run_root.is_dir():
            raise ValueError("reference-evidence final run path is not a directory")
        return _load_complete_run(
            run_root,
            run_relative=run_relative,
            expected_binding=_compatible_existing_binding(
                run_root,
                current=binding,
                legacy=legacy_binding,
            ),
        )

    runs_root = run_root.parent
    runs_root.mkdir(parents=True, exist_ok=True)
    stage_root = _resolve_contained(
        root,
        f"reference_evidence/runs/.{run_id}.staging",
    )
    if stage_root.exists():
        if not stage_root.is_dir():
            raise ValueError("reference-evidence staging path is not a directory")
        staged_binding = _compatible_existing_binding(
            stage_root,
            current=binding,
            legacy=legacy_binding,
        )
        try:
            _load_complete_run(
                stage_root,
                run_relative=run_relative,
                expected_binding=staged_binding,
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            quarantine = _quarantine_interrupted_stage(root, stage_root, run_id)
            relative = _relative_posix(root, quarantine)
            raise RuntimeError(
                "reference-evidence staging was incomplete or stale; "
                f"preserved at {relative}"
            ) from error
        os.replace(stage_root, run_root)
        return _load_complete_run(
            run_root,
            run_relative=run_relative,
            expected_binding=staged_binding,
        )

    stage_root.mkdir(parents=False, exist_ok=False)
    _build_staged_run(
        root,
        stage_root,
        run_relative=run_relative,
        request_binding=binding,
        source=source,
        provider=provider,
        advisory_provider=advisory_provider,
    )
    _load_complete_run(
        stage_root,
        run_relative=run_relative,
        expected_binding=binding,
    )
    os.replace(stage_root, run_root)
    return _load_complete_run(
        run_root,
        run_relative=run_relative,
        expected_binding=binding,
    )


class ImageMediaType:
    """Map supported raster extensions to stable evidence media types."""

    _TYPES = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }

    @classmethod
    def from_path(cls, path: Path) -> str:
        """Return a stable media type and reject unsupported source formats."""

        try:
            return cls._TYPES[path.suffix.lower()]
        except KeyError as error:
            raise ValueError(f"unsupported reference image format: {path.suffix}") from error


def load_reference_evidence(path: Path) -> ReferenceEvidence:
    """Load and strictly validate one immutable reference-evidence JSON document."""

    return ReferenceEvidence.model_validate_json(path.read_text(encoding="utf-8"))


def load_camera_hypothesis_set(path: Path) -> CameraHypothesisSet:
    """Load and strictly validate one immutable camera-hypothesis JSON document."""

    return CameraHypothesisSet.model_validate_json(path.read_text(encoding="utf-8"))


def reference_evidence_schema_payload() -> dict[str, object]:
    """Expose the strict model schema for checked-in schema parity integration."""

    return json.loads(json.dumps(ReferenceEvidence.model_json_schema()))
