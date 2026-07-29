from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from ..blender_artifacts import write_json_atomic
from ..models import SceneSpec
from ..optimization.provenance import collect_source_provenance
from ..qa.hashing import canonical_model_sha256
from ..qa.models import (
    REQUIRED_QA_PASS_KINDS,
    RenderPassManifest,
    VisualQAReport,
    VisualQARequest,
)
from ..reference_scope import reference_content_scope_from_metadata
from ..workspace import sha256_file
from .fit import (
    _bbox_similarity,
    _binary_mask,
    _clip_reference_mask,
    _iou,
    _normalized_bbox,
)
from .models import (
    BackgroundFitReport,
    BackgroundQualityFinding,
    BackgroundQualityReport,
    BackgroundRoleMap,
    BackgroundScenePromotionReceipt,
    ObjectRole,
)
from .roles import assignment_roles, observed_role_bbox


class BackgroundQualityConflict(RuntimeError):
    """Report changed or internally inconsistent final QA evidence."""


def _reference_scope_for_root(root: Path) -> tuple[str, str | None]:
    """Read job-local content scope while preserving legacy isolated fixtures."""

    metadata_path = root / "job.json"
    if not metadata_path.is_file():
        return reference_content_scope_from_metadata({})
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackgroundQualityConflict(
            f"job metadata is unreadable: {type(exc).__name__}"
        ) from exc
    if not isinstance(metadata, dict):
        raise BackgroundQualityConflict("job metadata must be a JSON object")
    try:
        return reference_content_scope_from_metadata(metadata)
    except ValueError as exc:
        raise BackgroundQualityConflict(
            f"reference content scope is invalid: {exc}"
        ) from exc


def _job_relative(root: Path, path: Path) -> str:
    """Serialize one resolved quality artifact relative to the owning job."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise BackgroundQualityConflict(
            f"quality evidence escaped the job workspace: {path}"
        ) from exc


def _resolve_manifest_path(manifest_path: Path, value: str) -> Path:
    """Resolve one render-pass path while requiring containment in the QA run."""

    path = Path(value).expanduser()
    resolved = path.resolve() if path.is_absolute() else (manifest_path.parent / path).resolve()
    try:
        resolved.relative_to(manifest_path.parent.resolve())
    except ValueError as exc:
        raise BackgroundQualityConflict(
            "render-pass evidence escaped its immutable QA run"
        ) from exc
    return resolved


def _resolve_job_relative_path(root: Path, value: str) -> Path:
    """Resolve one declared job-relative evidence path without allowing escape."""

    resolved = (root / value).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise BackgroundQualityConflict(
            f"background quality evidence escaped the job workspace: {value}"
        ) from exc
    return resolved


def _validate_fit_evidence(
    root: Path,
    *,
    workflow_id: str,
    current_scene_sha256: str,
    role_map_path: Path,
    role_map: BackgroundRoleMap,
    fit_report_path: Path,
    fit_report: BackgroundFitReport,
) -> None:
    """Verify the immutable fit, role, candidate, and promotion hash chain."""

    _job_relative(root, fit_report_path)
    if (
        role_map.workflow_id != workflow_id
        or fit_report.workflow_id != workflow_id
    ):
        raise BackgroundQualityConflict("background fit workflow identity mismatch")
    if (
        _job_relative(root, role_map_path) != fit_report.role_map_path
        or sha256_file(role_map_path) != fit_report.role_map_sha256
        or role_map.scene_spec_sha256 != fit_report.initial_candidate_sha256
    ):
        raise BackgroundQualityConflict("background role-map binding changed")
    selected = next(
        (
            attempt
            for attempt in fit_report.attempts
            if attempt.attempt_index == fit_report.selected_attempt_index
        ),
        None,
    )
    if selected is None or not selected.selected:
        raise BackgroundQualityConflict("background fit selected attempt is invalid")
    selected_path = _resolve_job_relative_path(root, selected.candidate_path)
    if (
        not selected_path.is_file()
        or sha256_file(selected_path) != selected.candidate_sha256
        or selected.candidate_sha256 != fit_report.selected_candidate_sha256
        or current_scene_sha256 != fit_report.selected_candidate_sha256
    ):
        raise BackgroundQualityConflict("background fit candidate or canonical binding changed")
    receipt_path = _resolve_job_relative_path(
        root,
        fit_report.promotion_receipt_path,
    )
    if (
        not receipt_path.is_file()
        or sha256_file(receipt_path) != fit_report.promotion_receipt_sha256
    ):
        raise BackgroundQualityConflict("background fit promotion receipt changed")
    receipt = BackgroundScenePromotionReceipt.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    if (
        receipt.job_id != fit_report.job_id
        or receipt.workflow_id != workflow_id
        or receipt.input_fingerprint != fit_report.input_fingerprint
        or receipt.initial_candidate_sha256 != fit_report.initial_candidate_sha256
        or receipt.selected_candidate_sha256 != fit_report.selected_candidate_sha256
        or receipt.selected_attempt_index != fit_report.selected_attempt_index
        or receipt.new_canonical_sha256 != current_scene_sha256
        or receipt.role_map_path != fit_report.role_map_path
        or receipt.role_map_sha256 != fit_report.role_map_sha256
    ):
        raise BackgroundQualityConflict("background fit promotion binding changed")


def _hex_rgb(value: str) -> tuple[int, int, int]:
    """Decode one deterministic object-ID color from its manifest hex string."""

    normalized = value.removeprefix("#")
    if len(normalized) != 6:
        raise BackgroundQualityConflict(f"invalid object-ID color: {value}")
    return tuple(int(normalized[index : index + 2], 16) for index in (0, 2, 4))


def _role_mask(
    object_id_path: Path,
    object_colors: dict[str, str],
    roles: dict[str, ObjectRole],
    selected_roles: set[ObjectRole],
) -> Image.Image:
    """Extract exact semantic-role pixels from the shader-independent object-ID pass."""

    allowed = {
        _hex_rgb(color)
        for identifier, color in object_colors.items()
        if roles.get(identifier) in selected_roles
    }
    with Image.open(object_id_path) as opened:
        image = opened.convert("RGB")
        mask = Image.new("L", image.size, 0)
        mask.putdata([255 if pixel in allowed else 0 for pixel in image.getdata()])
    return mask


def _finding_role(
    target_ids: list[str],
    roles: dict[str, ObjectRole],
) -> ObjectRole | str:
    """Select the highest-priority role represented by one immutable QA finding."""

    found = {roles[target] for target in target_ids if target in roles}
    for role in ("primary", "supporting", "decorative", "ground_background"):
        if role in found:
            return role
    return "unscoped"


def _delivery_severity(original: str, role: ObjectRole | str) -> str:
    """Translate raw severity into review-delivery priority without altering QA JSON."""

    if original == "high" and role == "primary":
        return "revision_required"
    if original == "high" and role == "supporting":
        return "important"
    if original in {"high", "medium"}:
        return "warning"
    return "info"


def _primary_metrics(
    request: VisualQARequest,
    manifest: RenderPassManifest,
    manifest_path: Path,
    spec: SceneSpec,
    roles: dict[str, ObjectRole],
) -> tuple[float | None, float | None, list[str]]:
    """Compute a ground-independent primary subject silhouette and bbox score."""

    primary_bbox = observed_role_bbox(spec, roles, ["primary"])
    if primary_bbox is None:
        return None, None, ["No reliable observed primary bbox is available."]
    object_record = next(
        item for item in manifest.passes if item.kind == "object_id"
    )
    object_path = _resolve_manifest_path(manifest_path, object_record.path)
    if not object_path.is_file() or sha256_file(object_path) != object_record.sha256:
        raise BackgroundQualityConflict("object-ID pass hash changed after canonical QA")
    primary_rendered = _role_mask(
        object_path,
        manifest.object_id_colors,
        roles,
        {"primary"},
    )
    reference_path = Path(request.reference_mask_path).expanduser().resolve()
    if not reference_path.is_file() or sha256_file(reference_path) != request.reference_mask_sha256:
        raise BackgroundQualityConflict("QA reference mask hash changed")
    reference = _clip_reference_mask(
        _binary_mask(reference_path, primary_rendered.size),
        primary_bbox,
    )
    reference_box = _normalized_bbox(reference)
    rendered_box = _normalized_bbox(primary_rendered)
    if reference_box is None:
        return None, None, ["Primary reference mask contains no measurable foreground."]
    if rendered_box is None:
        return None, None, ["Primary object-ID role mask contains no measurable foreground."]
    return (
        _iou(reference, primary_rendered),
        _bbox_similarity(reference_box, rendered_box),
        [],
    )


def evaluate_background_quality(
    root: Path,
    *,
    job_id: str,
    workflow_id: str,
    qa_run_id: str,
    role_map_path: Path,
    fit_report_path: Path,
    output_path: Path,
) -> BackgroundQualityReport:
    """Create a review-delivery quality outcome without blocking on visual findings."""

    qa_root = root / "qa" / "runs" / qa_run_id
    request_path = qa_root / "request.json"
    report_path = qa_root / "visual_qa_report.json"
    manifest_path = qa_root / "render_pass_manifest.json"
    required = (request_path, report_path, manifest_path, role_map_path, fit_report_path)
    if not all(path.is_file() for path in required):
        raise FileNotFoundError("background quality requires exact QA, role, and fit evidence")
    request = VisualQARequest.model_validate_json(
        request_path.read_text(encoding="utf-8")
    )
    report = VisualQAReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    manifest = RenderPassManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    role_map = BackgroundRoleMap.model_validate_json(
        role_map_path.read_text(encoding="utf-8")
    )
    fit_report = BackgroundFitReport.model_validate_json(
        fit_report_path.read_text(encoding="utf-8")
    )
    if (
        request.job_id != job_id
        or report.job_id != job_id
        or manifest.job_id != job_id
        or role_map.job_id != job_id
        or fit_report.job_id != job_id
        or request.run_id != qa_run_id
        or report.run_id != qa_run_id
        or manifest.run_id != qa_run_id
    ):
        raise BackgroundQualityConflict("background quality evidence identity mismatch")
    if request.include_generated_target or report.generated_target_status != "not_requested":
        raise BackgroundQualityConflict(
            "background fast quality evidence unexpectedly contains a generated target"
        )
    kinds = [item.kind for item in manifest.passes]
    if (
        len(kinds) != len(REQUIRED_QA_PASS_KINDS)
        or set(kinds) != set(REQUIRED_QA_PASS_KINDS)
    ):
        raise BackgroundQualityConflict("canonical QA pass set changed")
    scene_path = root / "analysis" / "scene_spec.json"
    spec = SceneSpec.model_validate_json(scene_path.read_text(encoding="utf-8"))
    current_scene_sha256 = sha256_file(scene_path)
    _validate_fit_evidence(
        root,
        workflow_id=workflow_id,
        current_scene_sha256=current_scene_sha256,
        role_map_path=role_map_path,
        role_map=role_map,
        fit_report_path=fit_report_path,
        fit_report=fit_report,
    )
    if (
        request.scene_spec_sha256 != current_scene_sha256
        or manifest.scene_spec_sha256 != request.scene_spec_sha256
        or report.request_sha256 != canonical_model_sha256(request)
        or request.render_pass_manifest_sha256 != sha256_file(manifest_path)
        or report.camera_fingerprint != request.camera_fingerprint
        or manifest.camera_fingerprint != request.camera_fingerprint
    ):
        raise BackgroundQualityConflict(
            "canonical source, QA request model, or camera fingerprint changed"
        )
    source = collect_source_provenance(root, job_id)
    reference_content_scope, target_subject = _reference_scope_for_root(root)
    if manifest.build_fingerprint != source.build_fingerprint:
        raise BackgroundQualityConflict("canonical QA build fingerprint is stale")
    roles = assignment_roles(role_map)
    primary_score, primary_bbox_score, unscorable = _primary_metrics(
        request,
        manifest,
        manifest_path,
        spec,
        roles,
    )

    classified: list[BackgroundQualityFinding] = []
    primary_high: list[str] = []
    supporting_high: list[str] = []
    decorative: list[str] = []
    environment: list[str] = []
    recommended_targets: set[str] = set()
    for finding in report.findings:
        role = _finding_role(finding.target_ids, roles)
        delivery = _delivery_severity(finding.severity, role)
        classified.append(
            BackgroundQualityFinding(
                finding_id=finding.id,
                original_severity=finding.severity,
                delivery_severity=delivery,  # type: ignore[arg-type]
                role=role,  # type: ignore[arg-type]
                target_ids=list(finding.target_ids),
                issue_type=finding.issue_type,
                description=finding.description,
                evidence_sources=list(finding.evidence_sources),
            )
        )
        if finding.severity == "high" and role == "primary":
            primary_high.append(finding.id)
            recommended_targets.update(finding.target_ids)
        elif finding.severity == "high" and role == "supporting":
            supporting_high.append(finding.id)
            recommended_targets.update(finding.target_ids)
        elif role == "decorative" and finding.severity in {"medium", "high"}:
            decorative.append(finding.id)
        elif role == "ground_background":
            environment.append(finding.id)

    if primary_score is not None and primary_score < 0.8:
        primary_high.append("quality.primary_silhouette")
        classified.append(
            BackgroundQualityFinding(
                finding_id="quality.primary_silhouette",
                original_severity="high",
                delivery_severity="revision_required",
                role="primary",
                issue_type="silhouette",
                description=(
                    "Ground-independent primary subject silhouette remains below "
                    "the fast review threshold."
                ),
                evidence_sources=["direct_reference"],
            )
        )
        recommended_targets.update(
            identifier for identifier, role in roles.items() if role == "primary"
        )
    if primary_bbox_score is not None and primary_bbox_score < 0.8:
        primary_high.append("quality.primary_bbox")
        classified.append(
            BackgroundQualityFinding(
                finding_id="quality.primary_bbox",
                original_severity="high",
                delivery_severity="revision_required",
                role="primary",
                issue_type="proportion",
                description=(
                    "Ground-independent primary subject framing or proportions remain "
                    "below the fast review threshold."
                ),
                evidence_sources=["direct_reference"],
            )
        )
        recommended_targets.update(
            identifier for identifier, role in roles.items() if role == "primary"
        )

    if unscorable:
        quality_status = "unscorable"
    elif primary_high or supporting_high:
        quality_status = "needs_revision"
    else:
        quality_status = "passed"
    standard_recommended = quality_status != "passed"
    quality = BackgroundQualityReport(
        job_id=job_id,
        workflow_id=workflow_id,
        reference_content_scope=reference_content_scope,
        target_subject=target_subject,
        quality_status=quality_status,
        quality_accepted=quality_status == "passed",
        standard_workflow_recommended=standard_recommended,
        overall_direct_score=report.direct_metrics.overall_direct_score,
        primary_silhouette_score=primary_score,
        primary_bbox_similarity=primary_bbox_score,
        findings=classified,
        primary_high_findings=sorted(set(primary_high)),
        supporting_high_findings=sorted(set(supporting_high)),
        decorative_warnings=sorted(set(decorative)),
        environment_findings=sorted(set(environment)),
        unscorable_evidence=unscorable,
        recommended_standard_revision_targets=sorted(recommended_targets),
        limitations=[
            "Workflow completion means review evidence is delivered, not quality accepted.",
            "Decorative and ground/background findings do not block preview delivery.",
            "The original V0.6 report remains the authoritative direct-comparison evidence.",
            (
                "Direct QA is scoped to the selected primary subject and its supporting "
                "components; omitted surroundings are outside this asset contract."
                if reference_content_scope == "primary_object_only"
                else "Direct QA covers the selected full-reference scene content."
            ),
        ],
        qa_run_id=qa_run_id,
        qa_request_path=_job_relative(root, request_path),
        qa_request_sha256=sha256_file(request_path),
        visual_qa_report_path=_job_relative(root, report_path),
        visual_qa_report_sha256=sha256_file(report_path),
        render_pass_manifest_path=_job_relative(root, manifest_path),
        render_pass_manifest_sha256=sha256_file(manifest_path),
        role_map_path=_job_relative(root, role_map_path),
        role_map_sha256=sha256_file(role_map_path),
        fit_report_path=_job_relative(root, fit_report_path),
        fit_report_sha256=sha256_file(fit_report_path),
        source_fingerprint=source.source_fingerprint,
        build_fingerprint=source.build_fingerprint,
        qa_scene_spec_sha256=request.scene_spec_sha256,
        qa_camera_fingerprint=request.camera_fingerprint,
        evaluated_at=datetime.now(UTC),
    )
    write_json_atomic(output_path, quality.model_dump(mode="json"))
    return quality
