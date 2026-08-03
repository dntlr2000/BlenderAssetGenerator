"""Orchestrate hash-bound camera, semantic-shape, and assembly QA companions."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from ..analysis.models import ModelingPlan
from ..background_quality.models import BackgroundRoleMap
from ..background_quality.roles import assignment_roles, derive_background_role_map
from ..blender_artifacts import write_json_atomic
from ..models import SceneSpec
from ..reference_scope import reference_content_scope_from_metadata
from ..workspace import file_exists, job_dir, load_job, sha256_file
from .camera_probe_service import (
    artifact_publication_lease,
    run_bounded_camera_probes,
    validate_camera_probe_terminal_evidence,
    write_json_exclusive,
)
from .diagnostic_models import (
    AssemblyDiagnosticEvidence,
    AssemblyMultiviewBundleEvidence,
    CameraProbeResult,
    QADiagnosticBundleManifest,
    QADiagnosticReport,
    QADiagnosticRequest,
    SemanticMaskBinding,
    SemanticReferenceMaskManifest,
)
from .diagnostics import build_qa_diagnostic_report, load_qa_diagnostic_request
from .hashing import canonical_model_sha256
from .image_io import copy_file_atomic, open_image, save_png_atomic
from .models import (
    REQUIRED_QA_PASS_KINDS,
    RenderPassManifest,
    VisualQAReport,
    VisualQARequest,
)
from .multiview_sanity import (
    AssemblySanityPlan,
    AssemblySanityRenderManifest,
    AssemblySanityReport,
    plan_job_assembly_multiview_sanity,
    run_job_assembly_multiview_sanity,
    validate_assembly_sanity_terminal,
)
from .request import validate_visual_qa_request
from .semantic_localizer import extract_semantic_mask

_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$")
_DEFAULT_DIAGNOSTIC_ID = "camera-geometry-v1"


def _validate_id(value: str, label: str) -> str:
    """Reject traversal and nonportable identifiers before creating evidence paths."""

    if not _RUN_ID_RE.fullmatch(value):
        raise ValueError(f"{label} must match [a-zA-Z0-9][a-zA-Z0-9._-]{{0,95}}")
    return value


def _next_diagnostic_attempt_root(diagnostic_root: Path) -> Path:
    """Create the next immutable numbered attempt below one terminal diagnostic root."""

    attempts_root = diagnostic_root / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    indexes = [
        int(match.group(1))
        for path in attempts_root.iterdir()
        if path.is_dir()
        and (match := re.fullmatch(r"attempt-([0-9]{3})", path.name)) is not None
    ]
    next_index = max(indexes, default=0) + 1
    if next_index > 999:
        raise RuntimeError("QA diagnostic attempt budget is exhausted")
    attempt_root = attempts_root / f"attempt-{next_index:03d}"
    attempt_root.mkdir(parents=False, exist_ok=False)
    return attempt_root


def _job_relative(root: Path, path: Path) -> str:
    """Serialize one artifact as a normalized path relative to its job workspace."""

    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        return resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"QA diagnostic artifact is outside the job: {resolved}") from exc


def _resolve_job_path(root: Path, relative: str) -> Path:
    """Resolve one job-relative path while rejecting parent-directory escape."""

    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"QA diagnostic path escapes the job: {relative}") from exc
    return candidate


def _require_bound_file(
    root: Path,
    relative: str,
    expected_sha256: str,
    label: str,
) -> Path:
    """Resolve one job-owned file and require its exact recorded SHA-256."""

    path = _resolve_job_path(root, relative)
    if not file_exists(path) or sha256_file(path) != expected_sha256:
        raise ValueError(f"QA diagnostic {label} is missing or changed")
    return path


def _validate_nested_pass_records(
    root: Path,
    records: Any,
    *,
    label: str,
) -> None:
    """Re-hash every path/hash pair declared by one diagnostic render manifest."""

    if not isinstance(records, list):
        raise ValueError(f"QA diagnostic {label} pass records are malformed")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f"QA diagnostic {label} contains a malformed pass record")
        relative = record.get("path")
        digest = record.get("sha256")
        if not isinstance(relative, str) or not isinstance(digest, str):
            raise ValueError(f"QA diagnostic {label} omits an exact pass path/hash")
        _require_bound_file(root, relative, digest, f"{label} pass")


def validate_qa_diagnostic_bundle(
    root: Path,
    bundle_path: Path,
) -> tuple[QADiagnosticBundleManifest, QADiagnosticRequest, QADiagnosticReport]:
    """Recursively validate a terminal companion bundle and every hash-bound child."""

    resolved_root = root.resolve()
    resolved_bundle = bundle_path.resolve()
    try:
        resolved_bundle.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("QA diagnostic bundle escapes the job workspace") from exc
    bundle = QADiagnosticBundleManifest.model_validate_json(
        resolved_bundle.read_text(encoding="utf-8")
    )
    expected_bundle = (
        resolved_root
        / "qa"
        / "runs"
        / bundle.qa_run_id
        / "diagnostics"
        / bundle.diagnostic_id
        / "bundle_manifest.json"
    ).resolve()
    if resolved_bundle != expected_bundle or bundle.job_id != resolved_root.name:
        raise ValueError("QA diagnostic bundle identity or terminal path is invalid")
    request_path = _require_bound_file(
        resolved_root,
        bundle.diagnostic_request_path,
        bundle.diagnostic_request_sha256,
        "request",
    )
    report_path = _require_bound_file(
        resolved_root,
        bundle.diagnostic_report_path,
        bundle.diagnostic_report_sha256,
        "report",
    )
    request = QADiagnosticRequest.model_validate_json(
        request_path.read_text(encoding="utf-8")
    )
    report = QADiagnosticReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    if (
        request.job_id != bundle.job_id
        or report.job_id != bundle.job_id
        or request.qa_run_id != bundle.qa_run_id
        or report.qa_run_id != bundle.qa_run_id
        or request.diagnostic_id != bundle.diagnostic_id
        or report.diagnostic_id != bundle.diagnostic_id
        or report.request_path != bundle.diagnostic_request_path
        or report.request_sha256 != bundle.diagnostic_request_sha256
    ):
        raise ValueError("QA diagnostic request/report identity differs from its bundle")
    source_bindings: list[tuple[str, str, str]] = [
        (
            request.visual_qa_request_path,
            request.visual_qa_request_sha256,
            "canonical QA request",
        ),
        (
            request.visual_qa_report_path,
            request.visual_qa_report_sha256,
            "canonical QA report",
        ),
        (
            request.render_pass_manifest_path,
            request.render_pass_manifest_sha256,
            "canonical QA pass manifest",
        ),
        (request.scene_spec_path, request.scene_spec_sha256, "SceneSpec"),
    ]
    for path, digest, label in (
        (request.modeling_plan_path, request.modeling_plan_sha256, "ModelingPlan"),
        (
            request.camera_role_map_path,
            request.camera_role_map_sha256,
            "camera role map",
        ),
        (
            request.semantic_reference_manifest_path,
            request.semantic_reference_manifest_sha256,
            "semantic-mask manifest",
        ),
        (request.assembly_report_path, request.assembly_report_sha256, "assembly report"),
        (
            request.primary_reference_mask_path,
            request.primary_reference_mask_sha256,
            "primary reference mask",
        ),
    ):
        if path is not None and digest is not None:
            source_bindings.append((path, digest, label))
    for binding in request.semantic_masks:
        source_bindings.extend(
            [
                (
                    binding.reference_mask_path,
                    binding.reference_mask_sha256,
                    f"semantic reference mask {binding.semantic_id}",
                ),
                (
                    binding.rendered_mask_path,
                    binding.rendered_mask_sha256,
                    f"semantic rendered mask {binding.semantic_id}",
                ),
            ]
        )
    for relative, digest, label in source_bindings:
        _require_bound_file(resolved_root, relative, digest, label)
    exact_sources = _load_exact_qa_sources(
        resolved_root,
        bundle.job_id,
        bundle.qa_run_id,
    )
    if (
        exact_sources[0].resolve()
        != _resolve_job_path(resolved_root, request.visual_qa_request_path)
        or exact_sources[2].resolve()
        != _resolve_job_path(resolved_root, request.visual_qa_report_path)
        or exact_sources[4].resolve()
        != _resolve_job_path(resolved_root, request.render_pass_manifest_path)
    ):
        raise ValueError("QA diagnostic bundle no longer selects the exact canonical QA run")
    if (
        bundle.visual_qa_report_path != request.visual_qa_report_path
        or bundle.visual_qa_report_sha256 != request.visual_qa_report_sha256
    ):
        raise ValueError("QA diagnostic bundle selected another canonical QA report")
    semantic_manifest_records: dict[str, tuple[str, float]] = {}
    if request.semantic_reference_manifest_path is not None:
        assert request.semantic_reference_manifest_sha256 is not None
        snapshot_path = _require_bound_file(
            resolved_root,
            request.semantic_reference_manifest_path,
            request.semantic_reference_manifest_sha256,
            "semantic-mask manifest snapshot",
        )
        semantic_manifest = SemanticReferenceMaskManifest.model_validate_json(
            snapshot_path.read_text(encoding="utf-8")
        )
        visual_request = exact_sources[1]
        if (
            semantic_manifest.job_id != bundle.job_id
            or semantic_manifest.scene_spec_path != request.scene_spec_path
            or semantic_manifest.scene_spec_sha256 != request.scene_spec_sha256
            or semantic_manifest.reference_sha256 != visual_request.reference_sha256
        ):
            raise ValueError(
                "QA diagnostic semantic-mask snapshot identity is invalid"
            )
        semantic_manifest_records = {
            item.semantic_id: (item.sha256, item.confidence)
            for item in semantic_manifest.masks
        }

    probe_plan_path = _require_bound_file(
        resolved_root,
        bundle.camera_probe_plan_path,
        bundle.camera_probe_plan_sha256,
        "camera-probe plan",
    )
    probe_manifest_path = _require_bound_file(
        resolved_root,
        bundle.camera_probe_manifest_path,
        bundle.camera_probe_manifest_sha256,
        "camera-probe manifest",
    )
    probe_plan = json.loads(probe_plan_path.read_text(encoding="utf-8"))
    probe_manifest = json.loads(probe_manifest_path.read_text(encoding="utf-8"))
    strict_probe_contract = probe_plan.get("terminal_contract") == "camera_probe_terminal_v2"
    if request.camera_role_map_path is not None:
        expected_role_map_hash = request.camera_role_map_sha256
    else:
        expected_role_map_hash = None
    if (
        probe_plan.get("diagnostic_kind") != "bounded_camera_probe"
        or probe_manifest.get("diagnostic_kind") != "bounded_camera_probe"
        or probe_plan.get("job_id") != bundle.job_id
        or probe_manifest.get("job_id") != bundle.job_id
        or probe_plan.get("qa_run_id") != bundle.qa_run_id
        or probe_manifest.get("qa_run_id") != bundle.qa_run_id
        or probe_plan.get("diagnostic_id") != bundle.diagnostic_id
        or probe_manifest.get("diagnostic_id") != bundle.diagnostic_id
        or probe_manifest.get("probe_plan_sha256") != bundle.camera_probe_plan_sha256
        or probe_plan.get("role_map_sha256") != expected_role_map_hash
        or probe_manifest.get("role_map_sha256") != expected_role_map_hash
    ):
        raise ValueError("QA diagnostic camera-probe identity or plan binding is invalid")
    semantic_probe_bindings = probe_plan.get("semantic_reference_masks", [])
    if not isinstance(semantic_probe_bindings, list):
        raise ValueError("QA diagnostic semantic camera-probe bindings are malformed")
    semantic_probe_ids: list[str] = []
    for binding in semantic_probe_bindings:
        if not isinstance(binding, dict):
            raise ValueError("QA diagnostic semantic camera-probe binding is malformed")
        semantic_id = binding.get("semantic_id")
        relative_path = binding.get("path")
        expected_sha256 = binding.get("sha256")
        if (
            not isinstance(semantic_id, str)
            or not isinstance(relative_path, str)
            or not isinstance(expected_sha256, str)
        ):
            raise ValueError("QA diagnostic semantic camera-probe binding is incomplete")
        semantic_probe_ids.append(semantic_id)
        declared = semantic_manifest_records.get(semantic_id)
        if declared is None or declared != (
            expected_sha256,
            float(binding.get("confidence", -1.0)),
        ):
            raise ValueError(
                "QA diagnostic semantic camera-probe binding differs from its "
                f"manifest snapshot: {semantic_id}"
            )
        _require_bound_file(
            resolved_root,
            relative_path,
            expected_sha256,
            f"camera-probe semantic reference mask {semantic_id}",
        )
    if len(semantic_probe_ids) != len(set(semantic_probe_ids)):
        raise ValueError("QA diagnostic semantic camera-probe IDs are duplicated")
    manifest_probes = probe_manifest.get("probes")
    if not isinstance(manifest_probes, list) or not manifest_probes:
        raise ValueError("QA diagnostic camera-probe manifest has no probe evidence")
    manifest_probe_ids: list[str] = []
    for probe in manifest_probes:
        if not isinstance(probe, dict):
            raise ValueError("QA diagnostic camera-probe entry is malformed")
        probe_id = probe.get("probe_id")
        if not isinstance(probe_id, str):
            raise ValueError("QA diagnostic camera-probe entry has no stable ID")
        manifest_probe_ids.append(probe_id)
        _validate_nested_pass_records(
            resolved_root,
            probe.get("passes"),
            label=f"camera probe {probe_id}",
        )
    plan_probe_ids = [
        item.get("probe_id")
        for item in probe_plan.get("probes", [])
        if isinstance(item, dict)
    ]
    report_probe_ids = [probe.probe_id for probe in report.camera_probes]
    if (
        len(manifest_probe_ids) != len(set(manifest_probe_ids))
        or plan_probe_ids != manifest_probe_ids
        or report_probe_ids != manifest_probe_ids
    ):
        raise ValueError("QA diagnostic camera-probe membership differs across evidence")
    for probe in report.camera_probes:
        if (
            probe.evidence_path != bundle.camera_probe_manifest_path
            or probe.evidence_sha256 != bundle.camera_probe_manifest_sha256
        ):
            raise ValueError("QA diagnostic report is not bound to its probe manifest")
    request_semantic_ids = [binding.semantic_id for binding in request.semantic_masks]
    report_semantic_ids = [metric.semantic_id for metric in report.semantic_metrics]
    if sorted(request_semantic_ids) != sorted(report_semantic_ids):
        raise ValueError("QA diagnostic semantic request/report membership differs")
    if (
        (strict_probe_contract or semantic_probe_ids)
        and sorted(semantic_probe_ids) != sorted(request_semantic_ids)
    ):
        raise ValueError("QA diagnostic semantic probe/report membership differs")
    if request.camera_role_map_path is None or request.camera_role_map_sha256 is None:
        raise ValueError("QA diagnostic camera-probe evidence requires an exact role map")
    validate_camera_probe_terminal_evidence(
        resolved_root,
        plan_path=probe_plan_path,
        plan_sha256=bundle.camera_probe_plan_sha256,
        manifest_path=probe_manifest_path,
        manifest_sha256=bundle.camera_probe_manifest_sha256,
        role_map_path=_resolve_job_path(resolved_root, request.camera_role_map_path),
        role_map_sha256=request.camera_role_map_sha256,
        expected_job_id=bundle.job_id,
        expected_qa_run_id=bundle.qa_run_id,
        expected_diagnostic_id=bundle.diagnostic_id,
        report_probes=report.camera_probes,
        report_semantic_ids=report_semantic_ids,
    )

    multiview = bundle.assembly_multiview
    if multiview.status in {"passed", "warning", "failed"}:
        assert multiview.plan_path is not None
        assert multiview.plan_sha256 is not None
        assert multiview.report_path is not None
        assert multiview.report_sha256 is not None
        assert multiview.render_manifest_path is not None
        assert multiview.render_manifest_sha256 is not None
        assembly_plan_path = _require_bound_file(
            resolved_root,
            multiview.plan_path,
            multiview.plan_sha256,
            "assembly multi-view plan",
        )
        assembly_report_path = _require_bound_file(
            resolved_root,
            multiview.report_path,
            multiview.report_sha256,
            "assembly multi-view report",
        )
        assembly_manifest_path = _require_bound_file(
            resolved_root,
            multiview.render_manifest_path,
            multiview.render_manifest_sha256,
            "assembly multi-view manifest",
        )
        assembly_plan = AssemblySanityPlan.model_validate_json(
            assembly_plan_path.read_text(encoding="utf-8")
        )
        assembly_report = AssemblySanityReport.model_validate_json(
            assembly_report_path.read_text(encoding="utf-8")
        )
        assembly_manifest = AssemblySanityRenderManifest.model_validate_json(
            assembly_manifest_path.read_text(encoding="utf-8")
        )
        if (
            assembly_plan.job_id != bundle.job_id
            or assembly_report.job_id != bundle.job_id
            or assembly_manifest.job_id != bundle.job_id
            or assembly_plan.run_id != multiview.run_id
            or assembly_report.run_id != multiview.run_id
            or assembly_manifest.run_id != multiview.run_id
            or assembly_report.plan_sha256 != multiview.plan_sha256
            or assembly_manifest.plan_sha256 != multiview.plan_sha256
            or assembly_report.render_manifest_sha256
            != multiview.render_manifest_sha256
            or assembly_plan.scene_spec_sha256 != request.scene_spec_sha256
            or assembly_report.scene_spec_sha256 != request.scene_spec_sha256
            or assembly_manifest.scene_spec_sha256 != request.scene_spec_sha256
            or request.modeling_plan_sha256 is None
            or assembly_plan.modeling_plan_sha256 != request.modeling_plan_sha256
            or assembly_report.modeling_plan_sha256 != request.modeling_plan_sha256
            or assembly_manifest.modeling_plan_sha256
            != request.modeling_plan_sha256
            or assembly_report.structural_status != multiview.status
        ):
            raise ValueError("QA diagnostic assembly multi-view identity is invalid")
        validate_assembly_sanity_terminal(
            resolved_root,
            plan_path=assembly_plan_path,
            plan_sha256=multiview.plan_sha256,
            manifest_path=assembly_manifest_path,
            manifest_sha256=multiview.render_manifest_sha256,
            report_path=assembly_report_path,
            report_sha256=multiview.report_sha256,
            expected_job_id=bundle.job_id,
            expected_run_id=str(multiview.run_id),
        )
    return bundle, request, report


def _manifest_pass(
    root: Path,
    run_dir: Path,
    manifest: RenderPassManifest,
    kind: str,
) -> Path:
    """Resolve and hash-check one exact canonical QA pass from its run manifest."""

    matches = [record for record in manifest.passes if record.kind == kind]
    if len(matches) != 1:
        raise ValueError(f"canonical QA run requires exactly one {kind} pass")
    record = matches[0]
    raw = Path(record.path)
    path = raw.resolve() if raw.is_absolute() else (run_dir / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"canonical QA {kind} pass escapes the job") from exc
    if not file_exists(path) or sha256_file(path) != record.sha256:
        raise ValueError(f"canonical QA {kind} pass is missing or changed")
    return path


def _load_exact_qa_sources(
    root: Path,
    job_id: str,
    qa_run_id: str,
) -> tuple[
    Path,
    VisualQARequest,
    Path,
    VisualQAReport,
    Path,
    RenderPassManifest,
    Path,
]:
    """Load one completed canonical QA run and verify its identity and source bindings."""

    run_dir = root / "qa" / "runs" / qa_run_id
    request_path = run_dir / "request.json"
    report_path = run_dir / "visual_qa_report.json"
    manifest_path = run_dir / "render_pass_manifest.json"
    for label, path in (
        ("VisualQARequest", request_path),
        ("VisualQAReport", report_path),
        ("RenderPassManifest", manifest_path),
    ):
        if not file_exists(path):
            raise FileNotFoundError(f"{label} is missing from QA run {qa_run_id}: {path}")
    request = VisualQARequest.model_validate_json(request_path.read_text(encoding="utf-8"))
    report = VisualQAReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    manifest = RenderPassManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    scene_spec_path = root / "analysis" / "scene_spec.json"
    validated_manifest = validate_visual_qa_request(
        request,
        scene_spec_path=scene_spec_path,
    )
    identities = {
        (request.job_id, request.run_id),
        (report.job_id, report.run_id),
        (manifest.job_id, str(manifest.run_id)),
    }
    if identities != {(job_id, qa_run_id)}:
        raise ValueError("canonical QA request, report, and manifest identities differ")
    if (
        validated_manifest != manifest
        or report.request_sha256 != canonical_model_sha256(request)
        or report.camera_fingerprint != request.camera_fingerprint
        or manifest.camera_fingerprint != request.camera_fingerprint
        or manifest.scene_spec_sha256 != request.scene_spec_sha256
    ):
        raise ValueError("canonical QA report or pass manifest is stale for its request")
    request_manifest_path = _resolve_visual_qa_path(
        root,
        request.render_pass_manifest_path,
    )
    if request_manifest_path != manifest_path.resolve():
        raise ValueError("VisualQARequest does not bind the selected run manifest")
    reference_path = _resolve_visual_qa_path(root, request.reference_path)
    reference_mask_path = _resolve_visual_qa_path(root, request.reference_mask_path)
    if reference_mask_path != (run_dir / "reference_mask.png").resolve():
        raise ValueError("VisualQARequest does not bind the selected run reference mask")
    pass_paths = {
        kind: _manifest_pass(root, run_dir, manifest, kind)
        for kind in REQUIRED_QA_PASS_KINDS
    }
    preview_path = _resolve_visual_qa_path(root, request.preview_path)
    if preview_path != pass_paths["beauty"]:
        raise ValueError("VisualQARequest preview is not the exact canonical beauty pass")
    reference_mask_manifest_path = run_dir / "reference_mask_manifest.json"
    if not file_exists(reference_mask_manifest_path):
        raise FileNotFoundError("canonical QA reference-mask manifest is missing")
    reference_mask_manifest = json.loads(
        reference_mask_manifest_path.read_text(encoding="utf-8")
    )
    if (
        reference_mask_manifest.get("reference_sha256") != request.reference_sha256
        or reference_mask_manifest.get("output_sha256")
        != request.reference_mask_sha256
        or str(reference_mask_manifest.get("output_path")) != "reference_mask.png"
    ):
        raise ValueError("canonical QA reference-mask manifest is stale for its request")
    return (
        request_path,
        request,
        report_path,
        report,
        manifest_path,
        manifest,
        reference_path,
    )


def _assembly_evidence_from_multiview(
    root: Path,
    multiview: dict[str, Any],
) -> AssemblyDiagnosticEvidence:
    """Translate exact run-owned Blender assembly evaluation into attribution evidence."""

    if multiview.get("status") not in {"passed", "warning", "failed"}:
        return AssemblyDiagnosticEvidence(
            status="not_available",
            limitations=[
                "No exact run-owned five-view Blender assembly evaluation is available."
            ],
        )
    relative = str(multiview["report_path"])
    digest = str(multiview["report_sha256"])
    path = _require_bound_file(root, relative, digest, "assembly multi-view report")
    report = AssemblySanityReport.model_validate_json(path.read_text(encoding="utf-8"))
    checks = report.assembly_evaluation.get("checks", [])
    if not isinstance(checks, list):
        raise ValueError("assembly multi-view report has malformed evaluated checks")
    check_failures = {
        str(item["id"])
        for item in checks
        if isinstance(item, dict)
        and item.get("required", True) is True
        and item.get("status") == "failed"
        and isinstance(item.get("id"), str)
    }
    check_warnings = {
        str(item["id"])
        for item in checks
        if isinstance(item, dict)
        and item.get("status") == "warning"
        and isinstance(item.get("id"), str)
    }
    finding_failures = {
        item.finding_id for item in report.findings if item.severity == "error"
    }
    finding_warnings = {
        item.finding_id for item in report.findings if item.severity == "warning"
    }
    failures = sorted(check_failures | finding_failures)
    warnings = sorted(check_warnings | finding_warnings)
    status = report.structural_status
    if status == "failed" and not failures:
        failures = ["structural_status.failed"]
    if status == "warning" and not warnings:
        warnings = ["structural_status.warning"]
    return AssemblyDiagnosticEvidence(
        status=status,
        report_path=relative,
        report_sha256=digest,
        required_failure_ids=failures,
        warning_ids=warnings,
        limitations=[
            "Five-view evaluated bounds, visibility, and declared or inferred signed "
            "axes are structural-consistency evidence, not proof of real-world facing, "
            "triangle-level clearance, or kinematics."
        ],
    )


def _semantic_role_map(path: Path) -> dict[str, str]:
    """Load workflow-owned QA roles used to label semantic shape evidence."""

    role_map = BackgroundRoleMap.model_validate_json(path.read_text(encoding="utf-8"))
    return {item.object_id: item.role for item in role_map.assignments}


def _aligned_reference_mask(source: Path, output: Path, size: tuple[int, int]) -> Path:
    """Copy or nearest-neighbor align one exact semantic mask into run-owned evidence."""

    with open_image(source) as opened:
        mask = opened.convert("L").point(lambda value: 255 if value >= 128 else 0)
        if mask.size != size:
            mask = mask.resize(size, Image.Resampling.NEAREST)
    return save_png_atomic(mask, output)


def _resolve_visual_qa_path(root: Path, value: str) -> Path:
    """Resolve an absolute or job-relative canonical QA path without allowing escape."""

    raw = Path(value).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("canonical VisualQARequest mask escapes the job") from exc
    return candidate


def _semantic_mask_filename(semantic_id: str) -> str:
    """Create a short collision-resistant filename without exposing long semantic IDs."""

    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", semantic_id).strip("._-")
    stem = slug[:48] or "semantic"
    digest = hashlib.sha256(semantic_id.encode("utf-8")).hexdigest()[:12]
    return f"{stem}-{digest}.png"


def _load_current_semantic_manifest(
    root: Path,
    *,
    job_id: str,
    scene_spec_path: Path,
    reference_path: Path,
) -> tuple[SemanticReferenceMaskManifest, SceneSpec]:
    """Strictly validate explicit semantic masks against current observed evidence."""

    manifest_path = root / "analysis" / "masks" / "semantic_manifest.json"
    manifest = SemanticReferenceMaskManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    if (
        manifest.job_id != job_id
        or spec.job_id != job_id
        or _resolve_job_path(root, manifest.scene_spec_path)
        != scene_spec_path.resolve()
        or manifest.scene_spec_sha256 != sha256_file(scene_spec_path)
        or manifest.reference_sha256 != sha256_file(reference_path)
        or _resolve_job_path(root, manifest.reference_path) != reference_path.resolve()
    ):
        raise ValueError("semantic reference mask manifest is stale for current QA inputs")
    objects = {item.id: item for item in spec.objects}
    sources = {item.id: item for item in spec.sources}
    with open_image(reference_path) as opened:
        reference_size = opened.size
    for record in manifest.masks:
        item = objects.get(record.semantic_id)
        source = sources.get(record.source_id)
        if item is None:
            raise ValueError(f"semantic mask names an unknown object: {record.semantic_id}")
        if (
            source is None
            or source.kind != "reference"
            or _resolve_job_path(root, source.path) != reference_path.resolve()
        ):
            raise ValueError(
                f"semantic mask source does not bind the primary reference: {record.source_id}"
            )
        if not any(
            evidence.source_id == record.source_id and evidence.status == "observed"
            for evidence in item.evidence
        ):
            raise ValueError(
                f"semantic mask lacks observed object evidence: {record.semantic_id}"
            )
        mask_path = _resolve_job_path(root, record.path)
        if not file_exists(mask_path) or sha256_file(mask_path) != record.sha256:
            raise ValueError(f"semantic reference mask changed: {record.semantic_id}")
        with open_image(mask_path) as opened:
            mask = opened.convert("L")
            values = set(mask.getdata())
            if mask.size != reference_size:
                raise ValueError(
                    f"semantic reference mask resolution differs: {record.semantic_id}"
                )
            if not values.issubset({0, 255}) or 255 not in values:
                raise ValueError(
                    f"semantic reference mask must be binary and nonempty: {record.semantic_id}"
                )
    return manifest, spec


def _snapshot_current_semantic_manifest(
    root: Path,
    *,
    job_id: str,
    scene_spec_path: Path,
    reference_path: Path,
    artifact_root: Path,
) -> tuple[
    SemanticReferenceMaskManifest | None,
    Path | None,
    dict[str, tuple[Path, str, float]],
]:
    """Freeze current semantic-mask source bytes inside one immutable QA attempt."""

    canonical_path = root / "analysis" / "masks" / "semantic_manifest.json"
    if not file_exists(canonical_path):
        return None, None, {}
    manifest, _spec = _load_current_semantic_manifest(
        root,
        job_id=job_id,
        scene_spec_path=scene_spec_path,
        reference_path=reference_path,
    )
    snapshot_path = artifact_root / "semantic_masks" / "source_manifest.json"
    copy_file_atomic(canonical_path, snapshot_path)
    if sha256_file(snapshot_path) != sha256_file(canonical_path):
        raise RuntimeError("semantic reference manifest snapshot differs from canonical")
    snapshots: dict[str, tuple[Path, str, float]] = {}
    for record in manifest.masks:
        source = _resolve_job_path(root, record.path)
        destination = (
            artifact_root
            / "semantic_masks"
            / "source"
            / _semantic_mask_filename(record.semantic_id)
        )
        copy_file_atomic(source, destination)
        if sha256_file(destination) != record.sha256:
            raise RuntimeError(
                f"semantic reference mask snapshot differs: {record.semantic_id}"
            )
        snapshots[record.semantic_id] = (
            destination,
            record.sha256,
            record.confidence,
        )
    return manifest, snapshot_path, snapshots


def _semantic_primary_mask_union(
    root: Path,
    *,
    subject_ids: set[str],
    artifact_root: Path,
    manifest: SemanticReferenceMaskManifest | None,
    semantic_reference_masks: dict[str, tuple[Path, str, float]],
) -> tuple[Path, str, str] | None:
    """Create one exact run-owned union from explicit primary/supporting semantic masks."""

    if manifest is None:
        return None
    selected = [record for record in manifest.masks if record.semantic_id in subject_ids]
    if not selected:
        return None
    combined: Image.Image | None = None
    for record in selected:
        snapshot = semantic_reference_masks.get(record.semantic_id)
        if snapshot is None:
            raise ValueError(f"semantic reference mask snapshot is missing: {record.semantic_id}")
        source, expected_sha256, _confidence = snapshot
        if not file_exists(source) or sha256_file(source) != expected_sha256:
            raise ValueError(f"semantic reference mask changed: {record.semantic_id}")
        with open_image(source) as opened:
            mask = opened.convert("L").point(lambda value: 255 if value >= 128 else 0)
            if combined is None:
                combined = mask.copy()
            else:
                if mask.size != combined.size:
                    mask = mask.resize(combined.size, Image.Resampling.NEAREST)
                combined = ImageChops.lighter(combined, mask)
    assert combined is not None
    output = artifact_root / "camera_probes" / "primary_reference_mask.png"
    save_png_atomic(combined, output)
    return output, sha256_file(output), "semantic_primary_supporting_union"


def _select_primary_probe_mask(
    root: Path,
    *,
    job_id: str,
    subject_ids: set[str],
    scene_spec_path: Path,
    visual_request: VisualQARequest,
    reference_path: Path,
    artifact_root: Path,
    semantic_manifest: SemanticReferenceMaskManifest | None,
    semantic_reference_masks: dict[str, tuple[Path, str, float]],
) -> tuple[Path | None, str | None, str | None, list[str]]:
    """Select only evidence-backed subject masks and preserve bbox-only legacy fallback."""

    content_scope, _target_subject = reference_content_scope_from_metadata(
        load_job(job_id)
    )
    if content_scope == "primary_object_only":
        path = _resolve_visual_qa_path(root, visual_request.reference_mask_path)
        if (
            not file_exists(path)
            or sha256_file(path) != visual_request.reference_mask_sha256
        ):
            raise ValueError("canonical primary-object reference mask is missing or stale")
        return (
            path,
            visual_request.reference_mask_sha256,
            "canonical_primary_object_reference",
            [],
        )
    union = _semantic_primary_mask_union(
        root,
        subject_ids=subject_ids,
        artifact_root=artifact_root,
        manifest=semantic_manifest,
        semantic_reference_masks=semantic_reference_masks,
    )
    if union is not None:
        return (*union, [])
    return (
        None,
        None,
        None,
        [
            "No exact primary-subject reference mask is available; bounded camera "
            "attribution falls back to observed semantic bboxes only."
        ],
    )


def _semantic_bindings(
    root: Path,
    *,
    artifact_root: Path,
    canonical_object_id: Path,
    object_colors: dict[str, str],
    role_map_path: Path,
    subject_ids: set[str],
    manifest: SemanticReferenceMaskManifest | None,
    semantic_reference_masks: dict[str, tuple[Path, str, float]],
) -> tuple[list[SemanticMaskBinding], list[str]]:
    """Create exact run-owned mask pairs only from an explicit current semantic manifest."""

    if manifest is None:
        return (
            [],
            [
                "No semantic reference mask manifest is available; per-part contour and "
                "2D orientation metrics are unscorable."
            ],
        )
    roles = _semantic_role_map(role_map_path)
    with open_image(canonical_object_id) as opened:
        resolution = opened.size
    bindings: list[SemanticMaskBinding] = []
    limitations = [*manifest.limitations]
    for record in manifest.masks:
        if record.semantic_id not in subject_ids:
            continue
        if record.semantic_id not in object_colors:
            limitations.append(
                f"Semantic mask {record.semantic_id} has no current object-ID color."
            )
            continue
        snapshot = semantic_reference_masks.get(record.semantic_id)
        if snapshot is None:
            raise ValueError(f"semantic reference mask snapshot is missing: {record.semantic_id}")
        source_mask, expected_sha256, _confidence = snapshot
        if not file_exists(source_mask) or sha256_file(source_mask) != expected_sha256:
            raise ValueError(f"semantic reference mask changed: {record.semantic_id}")
        safe_name = _semantic_mask_filename(record.semantic_id)
        reference_copy = _aligned_reference_mask(
            source_mask,
            artifact_root / "semantic_masks" / "reference" / safe_name,
            resolution,
        )
        rendered_mask = extract_semantic_mask(
            canonical_object_id,
            object_colors[record.semantic_id],
            artifact_root / "semantic_masks" / "rendered" / safe_name,
        )
        bindings.append(
            SemanticMaskBinding(
                semantic_id=record.semantic_id,
                role=roles.get(record.semantic_id, "unscoped"),
                source_id=record.source_id,
                confidence=record.confidence,
                reference_mask_path=_job_relative(root, reference_copy),
                reference_mask_sha256=sha256_file(reference_copy),
                rendered_mask_path=_job_relative(root, rendered_mask),
                rendered_mask_sha256=sha256_file(rendered_mask),
            )
        )
    if not bindings:
        limitations.append(
            "No current explicit semantic mask could be paired with object-ID evidence."
        )
    return bindings, limitations


def _assembly_multiview_eligible(root: Path) -> bool:
    """Return whether the current authored ModelingPlan supports exterior assembly sanity."""

    path = root / "analysis" / "modeling_plan.json"
    if not file_exists(path):
        return False
    plan = ModelingPlan.model_validate_json(path.read_text(encoding="utf-8"))
    targets = [
        item for item in plan.objects if item.assembly_role in {"root", "attached"}
    ]
    return (
        plan.assembly_consistency_policy == "spatial_v1"
        and plan.stage == "authored"
        and plan.assembly_frame is not None
        and len(targets) >= 2
        and any(item.assembly_role == "attached" for item in targets)
    )


def _require_companion_sources_current(
    root: Path,
    *,
    job_id: str,
    qa_run_id: str,
    request_path: Path,
    request: QADiagnosticRequest,
    report_path: Path,
    report_sha256: str,
    probe_plan_path: Path,
    probe_plan_sha256: str,
    probe_manifest_path: Path,
    probe_manifest_sha256: str,
    role_map_path: Path,
    role_map_sha256: str,
    probes: list[CameraProbeResult],
) -> None:
    """Re-hash exact companion sources before publishing the terminal bundle."""

    current_sources = _load_exact_qa_sources(root, job_id, qa_run_id)
    if (
        current_sources[0].resolve()
        != _resolve_job_path(root, request.visual_qa_request_path)
        or current_sources[2].resolve()
        != _resolve_job_path(root, request.visual_qa_report_path)
        or current_sources[4].resolve()
        != _resolve_job_path(root, request.render_pass_manifest_path)
    ):
        raise RuntimeError("canonical QA source selection changed before bundle publication")
    if load_qa_diagnostic_request(root, request_path) != request:
        raise RuntimeError("QA diagnostic request changed before bundle publication")
    for path, digest, label in (
        (report_path, report_sha256, "diagnostic report"),
        (probe_plan_path, probe_plan_sha256, "camera probe plan"),
        (probe_manifest_path, probe_manifest_sha256, "camera probe manifest"),
        (role_map_path, role_map_sha256, "camera role map"),
    ):
        if not file_exists(path) or sha256_file(path) != digest:
            raise RuntimeError(f"{label} changed before bundle publication")
    optional_sources = (
        (
            request.semantic_reference_manifest_path,
            request.semantic_reference_manifest_sha256,
            "semantic reference manifest snapshot",
        ),
        (
            request.primary_reference_mask_path,
            request.primary_reference_mask_sha256,
            "primary reference mask",
        ),
    )
    for relative, digest, label in optional_sources:
        if relative is None or digest is None:
            continue
        path = _resolve_job_path(root, relative)
        if not file_exists(path) or sha256_file(path) != digest:
            raise RuntimeError(f"{label} changed before bundle publication")
    for binding in request.semantic_masks:
        for relative, digest, label in (
            (
                binding.reference_mask_path,
                binding.reference_mask_sha256,
                f"semantic reference mask {binding.semantic_id}",
            ),
            (
                binding.rendered_mask_path,
                binding.rendered_mask_sha256,
                f"semantic rendered mask {binding.semantic_id}",
            ),
        ):
            path = _resolve_job_path(root, relative)
            if not file_exists(path) or sha256_file(path) != digest:
                raise RuntimeError(f"{label} changed before bundle publication")
    for probe in probes:
        evidence_path = _resolve_job_path(root, str(probe.evidence_path))
        if (
            not file_exists(evidence_path)
            or sha256_file(evidence_path) != probe.evidence_sha256
        ):
            raise RuntimeError(
                f"camera probe evidence changed before bundle publication: {probe.probe_id}"
            )


def _run_optional_assembly_multiview(
    root: Path,
    *,
    job_id: str,
    qa_run_id: str,
    diagnostic_id: str,
    attempt_id: str,
    include_multiview: bool,
    render_engine: str,
    render_device: str,
) -> dict[str, Any]:
    """Run structural five-view evidence when eligible and otherwise report availability."""

    if not include_multiview:
        return {"status": "not_requested"}
    if not _assembly_multiview_eligible(root):
        return {
            "status": "not_applicable",
            "reason": "Current ModelingPlan has no eligible authored spatial assembly.",
        }
    source_key = f"{qa_run_id}\0{diagnostic_id}".encode()
    source_digest = hashlib.sha256(source_key).hexdigest()[:16]
    safe_attempt = re.sub(
        r"[^a-z0-9._-]+", "-", attempt_id.casefold()
    ).strip("-._")
    assembly_run_id = f"assembly-{source_digest}-{safe_attempt}"
    planned = plan_job_assembly_multiview_sanity(
        job_id,
        run_id=assembly_run_id,
        resolution=384,
    )
    result = run_job_assembly_multiview_sanity(
        job_id,
        assembly_run_id,
        plan_sha256=str(planned["plan_sha256"]),
        render_engine=render_engine,
        render_device=render_device,
    )
    return {
        "status": result["status"],
        "run_id": assembly_run_id,
        "plan_path": _job_relative(root, Path(planned["plan"])),
        "plan_sha256": planned["plan_sha256"],
        "report_path": _job_relative(root, Path(result["report"])),
        "report_sha256": result["report_sha256"],
        "render_manifest_path": _job_relative(root, Path(result["render_manifest"])),
        "render_manifest_sha256": result["render_manifest_sha256"],
        "reference_comparison_status": result["reference_comparison_status"],
    }


def run_job_visual_diagnostics(
    job_id: str,
    qa_run_id: str,
    *,
    diagnostic_id: str = _DEFAULT_DIAGNOSTIC_ID,
    max_camera_probes: int = 12,
    include_multiview_sanity: bool = True,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict[str, Any]:
    """Serialize one standalone diagnostic publication and reject concurrent writers."""

    selected_qa_run = _validate_id(qa_run_id, "qa_run_id")
    selected_diagnostic = _validate_id(diagnostic_id, "diagnostic_id")
    if max_camera_probes < 1 or max_camera_probes > 12:
        raise ValueError("max_camera_probes must be within [1, 12]")
    root = job_dir(job_id)
    diagnostic_root = (
        root / "qa" / "runs" / selected_qa_run / "diagnostics" / selected_diagnostic
    )
    with artifact_publication_lease(
        diagnostic_root,
        owner_kind="qa_diagnostic",
        owner_id=f"{selected_qa_run}:{selected_diagnostic}",
    ):
        return _run_job_visual_diagnostics_locked(
            job_id,
            selected_qa_run,
            diagnostic_id=selected_diagnostic,
            max_camera_probes=max_camera_probes,
            include_multiview_sanity=include_multiview_sanity,
            render_engine=render_engine,
            render_device=render_device,
        )


def _run_job_visual_diagnostics_locked(
    job_id: str,
    qa_run_id: str,
    *,
    diagnostic_id: str = _DEFAULT_DIAGNOSTIC_ID,
    max_camera_probes: int = 12,
    include_multiview_sanity: bool = True,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict[str, Any]:
    """Generate companion evidence while the caller owns its publication lease."""

    selected_qa_run = _validate_id(qa_run_id, "qa_run_id")
    selected_diagnostic = _validate_id(diagnostic_id, "diagnostic_id")
    if max_camera_probes < 1 or max_camera_probes > 12:
        raise ValueError("max_camera_probes must be within [1, 12]")
    root = job_dir(job_id)
    (
        visual_request_path,
        visual_request,
        visual_report_path,
        visual_report,
        pass_manifest_path,
        pass_manifest,
        reference_path,
    ) = _load_exact_qa_sources(root, job_id, selected_qa_run)
    scene_spec_path = root / "analysis" / "scene_spec.json"
    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    if (
        spec.job_id != job_id
        or sha256_file(scene_spec_path) != visual_request.scene_spec_sha256
        or visual_report.camera_fingerprint != visual_request.camera_fingerprint
    ):
        raise ValueError("canonical SceneSpec changed after the selected QA run")
    planned_role_map = derive_background_role_map(
        scene_spec_path,
        job_id=job_id,
        workflow_id=f"qa-diagnostic-{selected_diagnostic}",
    )
    planned_roles = assignment_roles(planned_role_map)
    subject_ids = {
        semantic_id
        for semantic_id, role in planned_roles.items()
        if role in {"primary", "supporting"}
    }
    if not subject_ids:
        raise ValueError("QA diagnostics require a primary or supporting semantic ID")
    diagnostic_root = (
        root / "qa" / "runs" / selected_qa_run / "diagnostics" / selected_diagnostic
    )
    bundle_path = diagnostic_root / "bundle_manifest.json"
    if file_exists(bundle_path):
        QADiagnosticBundleManifest.model_validate_json(
            bundle_path.read_text(encoding="utf-8")
        )
        raise FileExistsError(f"immutable QA diagnostic already exists: {diagnostic_root}")
    diagnostic_root.mkdir(parents=True, exist_ok=True)
    artifact_root = _next_diagnostic_attempt_root(diagnostic_root)
    try:
        (
            semantic_manifest,
            semantic_manifest_path,
            semantic_reference_masks,
        ) = _snapshot_current_semantic_manifest(
            root,
            job_id=job_id,
            scene_spec_path=scene_spec_path,
            reference_path=reference_path,
            artifact_root=artifact_root,
        )
        probe_semantic_masks = {
            semantic_id: binding
            for semantic_id, binding in semantic_reference_masks.items()
            if semantic_id in subject_ids
        }
        (
            primary_mask_path,
            primary_mask_sha256,
            primary_mask_source,
            primary_mask_limitations,
        ) = _select_primary_probe_mask(
            root,
            job_id=job_id,
            subject_ids=subject_ids,
            scene_spec_path=scene_spec_path,
            visual_request=visual_request,
            reference_path=reference_path,
            artifact_root=artifact_root,
            semantic_manifest=semantic_manifest,
            semantic_reference_masks=semantic_reference_masks,
        )
        probes, probe_plan_path, probe_manifest_path = run_bounded_camera_probes(
            root,
            job_id=job_id,
            qa_run_id=selected_qa_run,
            diagnostic_id=selected_diagnostic,
            artifact_root=artifact_root,
            scene_spec_path=scene_spec_path,
            camera_fingerprint=visual_request.camera_fingerprint,
            max_camera_probes=max_camera_probes,
            render_engine=render_engine,
            render_device=render_device,
            primary_reference_mask_path=primary_mask_path,
            primary_reference_mask_sha256=primary_mask_sha256,
            primary_reference_mask_source=primary_mask_source,
            semantic_reference_masks=probe_semantic_masks,
        )
        role_map_path = artifact_root / "role_map.json"
        rendered_roles = _semantic_role_map(role_map_path)
        rendered_subject_ids = {
            semantic_id
            for semantic_id, role in rendered_roles.items()
            if role in {"primary", "supporting"}
        }
        if rendered_subject_ids != subject_ids:
            raise RuntimeError(
                "camera role-map fallback membership changed during diagnostics"
            )
        canonical_object_id = _manifest_pass(
            root,
            root / "qa" / "runs" / selected_qa_run,
            pass_manifest,
            "object_id",
        )
        bindings, limitations = _semantic_bindings(
            root,
            artifact_root=artifact_root,
            canonical_object_id=canonical_object_id,
            object_colors=pass_manifest.object_id_colors,
            role_map_path=role_map_path,
            subject_ids=subject_ids,
            manifest=semantic_manifest,
            semantic_reference_masks=semantic_reference_masks,
        )
        probe_plan_sha256 = sha256_file(probe_plan_path)
        probe_manifest_sha256 = sha256_file(probe_manifest_path)
        role_map_sha256 = sha256_file(role_map_path)
        semantic_manifest_sha256 = (
            sha256_file(semantic_manifest_path)
            if semantic_manifest_path is not None
            else None
        )
        modeling_plan_path = root / "analysis" / "modeling_plan.json"
        modeling_plan_sha256 = (
            sha256_file(modeling_plan_path) if file_exists(modeling_plan_path) else None
        )
        multiview = _run_optional_assembly_multiview(
            root,
            job_id=job_id,
            qa_run_id=selected_qa_run,
            diagnostic_id=selected_diagnostic,
            attempt_id=artifact_root.name,
            include_multiview=include_multiview_sanity,
            render_engine=render_engine,
            render_device=render_device,
        )
        if not file_exists(role_map_path) or sha256_file(role_map_path) != role_map_sha256:
            raise RuntimeError("camera role map changed during companion diagnostics")
        assembly = _assembly_evidence_from_multiview(root, multiview)
        request = QADiagnosticRequest(
            job_id=job_id,
            qa_run_id=selected_qa_run,
            diagnostic_id=selected_diagnostic,
            artifact_root=_job_relative(root, diagnostic_root),
            visual_qa_request_path=_job_relative(root, visual_request_path),
            visual_qa_request_sha256=sha256_file(visual_request_path),
            visual_qa_report_path=_job_relative(root, visual_report_path),
            visual_qa_report_sha256=sha256_file(visual_report_path),
            render_pass_manifest_path=_job_relative(root, pass_manifest_path),
            render_pass_manifest_sha256=sha256_file(pass_manifest_path),
            scene_spec_path=_job_relative(root, scene_spec_path),
            scene_spec_sha256=sha256_file(scene_spec_path),
            modeling_plan_path=(
                _job_relative(root, modeling_plan_path)
                if file_exists(modeling_plan_path)
                else None
            ),
            modeling_plan_sha256=(
                modeling_plan_sha256
            ),
            camera_role_map_path=_job_relative(root, role_map_path),
            camera_role_map_sha256=role_map_sha256,
            assembly_report_path=assembly.report_path,
            assembly_report_sha256=assembly.report_sha256,
            primary_reference_mask_path=(
                _job_relative(root, primary_mask_path)
                if primary_mask_path is not None
                else None
            ),
            primary_reference_mask_sha256=primary_mask_sha256,
            primary_reference_mask_source=primary_mask_source,
            semantic_reference_manifest_path=(
                _job_relative(root, semantic_manifest_path)
                if semantic_manifest_path is not None
                else None
            ),
            semantic_reference_manifest_sha256=(
                semantic_manifest_sha256
            ),
            semantic_masks=bindings,
            max_camera_probes=max_camera_probes,
        )
        request_path = artifact_root / "request.json"
        write_json_atomic(request_path, request.model_dump(mode="json"))
        report = build_qa_diagnostic_report(
            root,
            request_path,
            probes,
            assembly_evidence=assembly,
        )
        report = report.model_copy(
            update={
                "limitations": [
                    *report.limitations,
                    *limitations,
                    *primary_mask_limitations,
                    "Existing VisualQAReport 0.6.0 metrics and score are unchanged.",
                    "PCA orientation is undirected and cannot prove 180-degree facing.",
                ]
            }
        )
        report_path = artifact_root / "report.json"
        write_json_atomic(report_path, report.model_dump(mode="json"))
        report_sha256 = sha256_file(report_path)
        _require_companion_sources_current(
            root,
            job_id=job_id,
            qa_run_id=selected_qa_run,
            request_path=request_path,
            request=request,
            report_path=report_path,
            report_sha256=report_sha256,
            probe_plan_path=probe_plan_path,
            probe_plan_sha256=probe_plan_sha256,
            probe_manifest_path=probe_manifest_path,
            probe_manifest_sha256=probe_manifest_sha256,
            role_map_path=role_map_path,
            role_map_sha256=role_map_sha256,
            probes=probes,
        )
        bundle = QADiagnosticBundleManifest(
            job_id=job_id,
            qa_run_id=selected_qa_run,
            diagnostic_id=selected_diagnostic,
            visual_qa_report_path=_job_relative(root, visual_report_path),
            visual_qa_report_sha256=sha256_file(visual_report_path),
            diagnostic_request_path=_job_relative(root, request_path),
            diagnostic_request_sha256=sha256_file(request_path),
            diagnostic_report_path=_job_relative(root, report_path),
            diagnostic_report_sha256=report_sha256,
            camera_probe_plan_path=_job_relative(root, probe_plan_path),
            camera_probe_plan_sha256=probe_plan_sha256,
            camera_probe_manifest_path=_job_relative(root, probe_manifest_path),
            camera_probe_manifest_sha256=probe_manifest_sha256,
            assembly_multiview=AssemblyMultiviewBundleEvidence.model_validate(multiview),
            created_at=datetime.now(UTC),
        )
        write_json_exclusive(bundle_path, bundle.model_dump(mode="json"))
        validate_qa_diagnostic_bundle(root, bundle_path)
    except Exception:
        # The failed numbered attempt remains immutable evidence; an explicit retry can
        # create a new attempt without overwriting it or weakening the terminal bundle.
        raise
    return {
        "ok": True,
        "job_id": job_id,
        "qa_run_id": selected_qa_run,
        "diagnostic_id": selected_diagnostic,
        "status": report.status,
        "attribution": report.attribution.classification,
        "attribution_confidence": report.attribution.confidence,
        "existing_direct_score": visual_report.direct_metrics.overall_direct_score,
        "canonical_v06_score_unchanged": True,
        "request": str(request_path),
        "report": str(report_path),
        "bundle_manifest": str(bundle_path),
        "assembly_multiview": multiview,
    }
