from __future__ import annotations

import math
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from ..blender_artifacts import stable_json_digest, write_json_atomic
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..models import SceneSpec
from ..workspace import job_dir, replace_scene_spec_if_current, sha256_file
from .models import (
    BackgroundFitAttempt,
    BackgroundFitChange,
    BackgroundFitMetrics,
    BackgroundFitReport,
    BackgroundScenePromotionReceipt,
)
from .roles import assignment_roles, derive_background_role_map, observed_role_bbox


class BackgroundFitConflict(RuntimeError):
    """Report an unexpected canonical change before bounded fit promotion."""


def _job_relative(root: Path, path: Path) -> str:
    """Serialize one resolved artifact path relative to the owning job."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"background fit artifact is outside the job: {path}") from exc


def _reference_content_mask(root: Path) -> Path:
    """Resolve the deterministic primary-reference content mask used by V0.4."""

    preferred = root / "analysis" / "masks" / "reference_content.png"
    if preferred.is_file():
        return preferred
    candidates = sorted((root / "analysis" / "masks").glob("*reference*_content.png"))
    if len(candidates) != 1:
        raise FileNotFoundError("background fit requires one reference content mask")
    return candidates[0]


def _binary_mask(path: Path, size: tuple[int, int] | None = None) -> Image.Image:
    """Load one thresholded grayscale mask and align it by nearest-neighbor sampling."""

    with Image.open(path) as opened:
        mask = opened.convert("L")
        if size is not None and mask.size != size:
            mask = mask.resize(size, Image.Resampling.NEAREST)
        return mask.point(lambda value: 255 if value >= 128 else 0)


def _normalized_bbox(mask: Image.Image) -> tuple[float, float, float, float] | None:
    """Return one normalized foreground box for deterministic fit diagnostics."""

    box = mask.getbbox()
    if box is None:
        return None
    left, top, right, bottom = box
    width, height = mask.size
    return left / width, top / height, right / width, bottom / height


def _clip_reference_mask(
    mask: Image.Image,
    bbox: tuple[float, float, float, float],
) -> Image.Image:
    """Keep reference foreground only inside the observed primary semantic union."""

    width, height = mask.size
    left = max(0, min(width, math.floor(bbox[0] * width)))
    top = max(0, min(height, math.floor(bbox[1] * height)))
    right = max(0, min(width, math.ceil(bbox[2] * width)))
    bottom = max(0, min(height, math.ceil(bbox[3] * height)))
    clipped = Image.new("L", mask.size, 0)
    if right > left and bottom > top:
        clipped.paste(mask.crop((left, top, right, bottom)), (left, top))
    return clipped


def _iou(reference: Image.Image, rendered: Image.Image) -> float:
    """Compute binary intersection-over-union for one primary-subject diagnostic."""

    reference_values = [value > 0 for value in reference.getdata()]
    rendered_values = [value > 0 for value in rendered.getdata()]
    intersection = sum(
        left and right
        for left, right in zip(reference_values, rendered_values, strict=True)
    )
    union = sum(
        left or right
        for left, right in zip(reference_values, rendered_values, strict=True)
    )
    return round(intersection / union, 6) if union else 0.0


def _bbox_similarity(
    reference: tuple[float, float, float, float],
    rendered: tuple[float, float, float, float],
) -> float:
    """Convert normalized primary center and size error into a bounded similarity."""

    ref_center = ((reference[0] + reference[2]) / 2, (reference[1] + reference[3]) / 2)
    out_center = ((rendered[0] + rendered[2]) / 2, (rendered[1] + rendered[3]) / 2)
    ref_size = (reference[2] - reference[0], reference[3] - reference[1])
    out_size = (rendered[2] - rendered[0], rendered[3] - rendered[1])
    center_error = math.dist(ref_center, out_center) / math.sqrt(2)
    size_error = math.dist(ref_size, out_size) / math.sqrt(2)
    return round(max(0.0, 1.0 - min(1.0, center_error + size_error)), 6)


def _candidate_metrics(
    reference_mask_path: Path,
    rendered_mask_path: Path,
    reference_bbox: tuple[float, float, float, float] | None,
) -> BackgroundFitMetrics:
    """Measure one rendered primary silhouette against clipped reference evidence."""

    rendered = _binary_mask(rendered_mask_path)
    if reference_bbox is None:
        return BackgroundFitMetrics(
            scorable=False,
            limitations=["No reliable observed primary semantic bbox is available."],
        )
    reference = _clip_reference_mask(
        _binary_mask(reference_mask_path, rendered.size),
        reference_bbox,
    )
    reference_render_bbox = _normalized_bbox(reference)
    rendered_bbox = _normalized_bbox(rendered)
    if reference_render_bbox is None or rendered_bbox is None:
        return BackgroundFitMetrics(
            scorable=False,
            primary_reference_bbox_norm=reference_render_bbox,
            primary_rendered_bbox_norm=rendered_bbox,
            limitations=[
                "Primary reference or rendered subject mask has no measurable foreground."
            ],
        )
    silhouette = _iou(reference, rendered)
    bbox_score = _bbox_similarity(reference_render_bbox, rendered_bbox)
    return BackgroundFitMetrics(
        scorable=True,
        primary_reference_bbox_norm=reference_render_bbox,
        primary_rendered_bbox_norm=rendered_bbox,
        primary_silhouette_iou=silhouette,
        primary_bbox_similarity=bbox_score,
        combined_score=round(0.7 * silhouette + 0.3 * bbox_score, 6),
    )


def _normalize(vector: list[float]) -> list[float]:
    """Normalize one three-component vector with a stable zero-length fallback."""

    length = math.sqrt(sum(value * value for value in vector))
    if length <= 1e-9:
        return [0.0, -1.0, 0.0]
    return [value / length for value in vector]


def _cross(left: list[float], right: list[float]) -> list[float]:
    """Return the three-dimensional cross product used for camera-frame movement."""

    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]


def _adjust_camera_candidate(
    payload: dict[str, Any],
    metrics: BackgroundFitMetrics,
    *,
    damping: float,
) -> tuple[dict[str, Any], list[BackgroundFitChange]]:
    """Create one bounded camera-only refinement from image-space primary errors."""

    if (
        not metrics.scorable
        or metrics.primary_reference_bbox_norm is None
        or metrics.primary_rendered_bbox_norm is None
    ):
        return deepcopy(payload), []
    candidate = deepcopy(payload)
    camera = candidate["camera"]
    location = [float(value) for value in camera["location"]]
    original_location = list(location)
    target = [float(value) for value in camera["target"]]
    view = _normalize([target[index] - location[index] for index in range(3)])
    distance = max(
        0.001,
        math.sqrt(
            sum((target[index] - location[index]) ** 2 for index in range(3))
        ),
    )
    right = _normalize(_cross(view, [0.0, 0.0, 1.0]))
    if abs(sum(value * value for value in right)) <= 1e-9:
        right = [1.0, 0.0, 0.0]
    up = _normalize(_cross(right, view))
    reference = metrics.primary_reference_bbox_norm
    rendered = metrics.primary_rendered_bbox_norm
    ref_center = ((reference[0] + reference[2]) / 2, (reference[1] + reference[3]) / 2)
    out_center = ((rendered[0] + rendered[2]) / 2, (rendered[1] + rendered[3]) / 2)
    ref_size = (
        max(1e-4, reference[2] - reference[0]),
        max(1e-4, reference[3] - reference[1]),
    )
    out_size = (
        max(1e-4, rendered[2] - rendered[0]),
        max(1e-4, rendered[3] - rendered[1]),
    )
    size_ratio = max(out_size[0] / ref_size[0], out_size[1] / ref_size[1])
    size_ratio = 1.0 + (max(0.8, min(1.25, size_ratio)) - 1.0) * damping
    changes: list[BackgroundFitChange] = []
    if camera["projection"] == "ORTHO":
        previous_scale = float(camera["ortho_scale"])
        camera["ortho_scale"] = round(previous_scale * size_ratio, 9)
        if camera["ortho_scale"] != previous_scale:
            changes.append(
                BackgroundFitChange(
                    path=["camera", "ortho_scale"],
                    before=previous_scale,
                    after=camera["ortho_scale"],
                    reason="Bound primary subject occupancy to observed reference size.",
                )
            )
        vertical_span = float(camera["ortho_scale"])
    else:
        distance *= size_ratio
        location = [
            target[index] - view[index] * distance for index in range(3)
        ]
        focal_length = max(1e-3, float(camera["focal_length_mm"]))
        vertical_span = 2.0 * distance * math.tan(
            math.atan(36.0 / (2.0 * focal_length))
        )
    resolution = camera.get("resolution", [1, 1])
    aspect = max(1e-4, float(resolution[0]) / max(1.0, float(resolution[1])))
    horizontal_span = vertical_span * aspect
    dx = (out_center[0] - ref_center[0]) * damping
    dy = (out_center[1] - ref_center[1]) * damping
    shift = [
        right[index] * dx * horizontal_span
        - up[index] * dy * vertical_span
        for index in range(3)
    ]
    previous_target = list(target)
    target = [target[index] + shift[index] for index in range(3)]
    location = [location[index] + shift[index] for index in range(3)]
    camera["target"] = [round(value, 9) for value in target]
    camera["location"] = [round(value, 9) for value in location]
    if camera["target"] != previous_target:
        changes.append(
            BackgroundFitChange(
                path=["camera", "target"],
                before=previous_target,
                after=camera["target"],
                reason="Move the camera frame toward the observed primary center.",
            )
        )
    if camera["location"] != original_location:
        changes.append(
            BackgroundFitChange(
                path=["camera", "location"],
                before=original_location,
                after=camera["location"],
                reason=(
                    (
                        "Bound perspective occupancy and translate the camera with "
                        "its target while preserving view direction."
                    )
                    if camera["projection"] == "PERSP"
                    else (
                        "Translate the orthographic camera with its target while "
                        "preserving view direction."
                    )
                ),
            )
        )
    return candidate, changes


def _render_candidate(
    root: Path,
    candidate_path: Path,
    role_map_path: Path,
    attempt_root: Path,
) -> Path:
    """Build and render one isolated low-resolution primary silhouette candidate."""

    spec = SceneSpec.model_validate_json(candidate_path.read_text(encoding="utf-8"))
    provenance = collect_build_provenance(
        root,
        spec.job_id,
        scene_spec_path=candidate_path,
    )
    blend_path = attempt_root / "scene.blend"
    run_blender(
        "build_scene.py",
        [
            "--spec",
            str(candidate_path),
            "--job-root",
            str(root),
            "--output",
            str(blend_path),
        ],
    )
    silhouette_path = attempt_root / "primary_silhouette.png"
    manifest_path = attempt_root / "fit_manifest.json"
    run_blender(
        "render_fit_diagnostic.py",
        [
            "--output",
            str(silhouette_path),
            "--manifest",
            str(manifest_path),
            "--scene-spec",
            str(candidate_path),
            "--build-fingerprint",
            str(provenance["fingerprint"]),
            "--scene-spec-sha256",
            str(provenance["scene_spec_sha256"]),
            "--camera-fingerprint",
            str(provenance["camera_fingerprint"]),
            "--role-map",
            str(role_map_path),
            "--resolution",
            "256",
        ],
        blend_file=blend_path,
    )
    return silhouette_path


def _write_candidate(path: Path, payload: dict[str, Any]) -> SceneSpec:
    """Strictly validate and persist one workflow-owned SceneSpec candidate."""

    model = SceneSpec.model_validate(payload)
    write_json_atomic(path, model.model_dump(mode="json"))
    return model


def run_background_pre_qa_fit(
    job_id: str,
    *,
    workflow_id: str,
    input_fingerprint: str,
    initial_candidate_path: Path,
    fit_root: Path,
    max_attempts: int = 2,
) -> BackgroundFitReport:
    """Run at most two camera refinements and promote only the best strict candidate."""

    if max_attempts < 0 or max_attempts > 2:
        raise ValueError("background pre-QA fit max_attempts must be within [0, 2]")
    root = job_dir(job_id)
    canonical_path = root / "analysis" / "scene_spec.json"
    initial_candidate_path = initial_candidate_path.resolve()
    fit_root = fit_root.resolve()
    _job_relative(root, initial_candidate_path)
    _job_relative(root, fit_root)
    if fit_root.exists():
        raise FileExistsError(f"background fit evidence already exists: {fit_root}")
    if not canonical_path.is_file() or not initial_candidate_path.is_file():
        raise FileNotFoundError("background fit requires canonical and initial SceneSpec")
    initial_hash = sha256_file(initial_candidate_path)
    previous_hash = sha256_file(canonical_path)
    if previous_hash != initial_hash:
        raise BackgroundFitConflict(
            "canonical SceneSpec changed after the initial workflow snapshot"
        )
    initial_spec = SceneSpec.model_validate_json(
        initial_candidate_path.read_text(encoding="utf-8")
    )
    if initial_spec.job_id != job_id or initial_spec.mode != "concept":
        raise ValueError("background fit supports only the owning concept-mode job")

    fit_root.mkdir(parents=True, exist_ok=False)
    candidate_root = fit_root / "candidates"
    attempts_root = fit_root / "attempts"
    candidate_root.mkdir()
    attempts_root.mkdir()
    baseline_path = candidate_root / "attempt-00.json"
    baseline_path.write_bytes(initial_candidate_path.read_bytes())
    baseline_spec = SceneSpec.model_validate_json(
        baseline_path.read_text(encoding="utf-8")
    )
    role_map = derive_background_role_map(
        baseline_path,
        job_id=job_id,
        workflow_id=workflow_id,
    )
    role_map_path = fit_root / "role_map.json"
    write_json_atomic(role_map_path, role_map.model_dump(mode="json"))
    roles = assignment_roles(role_map)
    primary_bbox = observed_role_bbox(baseline_spec, roles, ["primary"])
    reference_mask = _reference_content_mask(root)
    reference_hash = sha256_file(reference_mask)
    role_map_hash = sha256_file(role_map_path)

    attempts: list[BackgroundFitAttempt] = []
    candidate_payloads: dict[int, dict[str, Any]] = {
        0: baseline_spec.model_dump(mode="json")
    }
    best_index = 0
    best_score: float | None = None
    try:
        baseline_render = _render_candidate(
            root,
            baseline_path,
            role_map_path,
            attempts_root / "attempt-00",
        )
        baseline_metrics = _candidate_metrics(
            reference_mask,
            baseline_render,
            primary_bbox,
        )
        best_score = baseline_metrics.combined_score
        attempts.append(
            BackgroundFitAttempt(
                attempt_index=0,
                candidate_path=_job_relative(root, baseline_path),
                candidate_sha256=sha256_file(baseline_path),
                input_fingerprint=stable_json_digest(
                    {
                        "workflow_input": input_fingerprint,
                        "candidate": sha256_file(baseline_path),
                        "reference_mask": reference_hash,
                        "role_map": role_map_hash,
                        "attempt": 0,
                    }
                ),
                metrics=baseline_metrics,
                outcome="baseline",
                reason="Captured the immutable initial authoring candidate.",
            )
        )
    except Exception as exc:
        attempts.append(
            BackgroundFitAttempt(
                attempt_index=0,
                candidate_path=_job_relative(root, baseline_path),
                candidate_sha256=sha256_file(baseline_path),
                input_fingerprint=stable_json_digest(
                    {
                        "workflow_input": input_fingerprint,
                        "candidate": sha256_file(baseline_path),
                        "reference_mask": reference_hash,
                        "role_map": role_map_hash,
                        "attempt": 0,
                    }
                ),
                outcome="failed",
                reason=f"Baseline diagnostic unavailable: {type(exc).__name__}: {exc}",
            )
        )

    for attempt_index in range(1, max_attempts + 1):
        previous_attempt = attempts[best_index]
        if previous_attempt.metrics is None or not previous_attempt.metrics.scorable:
            break
        candidate_payload, changes = _adjust_camera_candidate(
            candidate_payloads[best_index],
            previous_attempt.metrics,
            damping=1.0 if attempt_index == 1 else 0.5,
        )
        if not changes:
            break
        candidate_path = candidate_root / f"attempt-{attempt_index:02d}.json"
        _write_candidate(candidate_path, candidate_payload)
        candidate_payloads[attempt_index] = candidate_payload
        attempt_fingerprint = stable_json_digest(
            {
                "workflow_input": input_fingerprint,
                "parent_candidate": previous_attempt.candidate_sha256,
                "candidate": sha256_file(candidate_path),
                "reference_mask": reference_hash,
                "role_map": role_map_hash,
                "attempt": attempt_index,
            }
        )
        try:
            rendered = _render_candidate(
                root,
                candidate_path,
                role_map_path,
                attempts_root / f"attempt-{attempt_index:02d}",
            )
            metrics = _candidate_metrics(reference_mask, rendered, primary_bbox)
            score = metrics.combined_score
            improved = (
                score is not None
                and (best_score is None or score > best_score + 0.0001)
            )
            attempts.append(
                BackgroundFitAttempt(
                    attempt_index=attempt_index,
                    candidate_path=_job_relative(root, candidate_path),
                    candidate_sha256=sha256_file(candidate_path),
                    input_fingerprint=attempt_fingerprint,
                    changes=changes,
                    metrics=metrics,
                    improved=improved,
                    outcome="evaluated",
                    reason=(
                        "Candidate improved the bounded primary fit score."
                        if improved
                        else "Candidate did not improve the bounded primary fit score."
                    ),
                )
            )
            if improved:
                best_index = attempt_index
                best_score = score
        except Exception as exc:
            attempts.append(
                BackgroundFitAttempt(
                    attempt_index=attempt_index,
                    candidate_path=_job_relative(root, candidate_path),
                    candidate_sha256=sha256_file(candidate_path),
                    input_fingerprint=attempt_fingerprint,
                    changes=changes,
                    outcome="failed",
                    reason=f"Diagnostic failed: {type(exc).__name__}: {exc}",
                )
            )

    attempts = [
        item.model_copy(update={"selected": item.attempt_index == best_index})
        for item in attempts
    ]
    selected_path = root / attempts[best_index].candidate_path
    selected_hash = sha256_file(selected_path)
    archived_path: Path | None = None
    canonical_changed = best_index != 0
    if canonical_changed:
        selected_model = SceneSpec.model_validate_json(
            selected_path.read_text(encoding="utf-8")
        )
        if selected_model.job_id != job_id:
            raise BackgroundFitConflict(
                "selected background-fit SceneSpec belongs to another job"
            )
        selected_hash = sha256_file(selected_path)
        replacement = replace_scene_spec_if_current(
            job_id,
            selected_path,
            expected_current_sha256=previous_hash,
            expected_candidate_sha256=selected_hash,
            lock_owner_id=workflow_id,
        )
        archived_value = replacement["archived_scene_spec"]
        archived_path = Path(archived_value) if archived_value is not None else None
    new_hash = sha256_file(canonical_path)
    receipt = BackgroundScenePromotionReceipt(
        job_id=job_id,
        workflow_id=workflow_id,
        input_fingerprint=input_fingerprint,
        initial_candidate_path=_job_relative(root, initial_candidate_path),
        initial_candidate_sha256=initial_hash,
        selected_candidate_path=_job_relative(root, selected_path),
        selected_candidate_sha256=selected_hash,
        selected_attempt_index=best_index,
        previous_canonical_sha256=previous_hash,
        new_canonical_sha256=new_hash,
        canonical_changed=canonical_changed,
        archived_scene_spec_path=(
            _job_relative(root, archived_path) if archived_path is not None else None
        ),
        role_map_path=_job_relative(root, role_map_path),
        role_map_sha256=role_map_hash,
        promoted_at=datetime.now(UTC),
    )
    receipt_path = fit_root / "promotion_receipt.json"
    write_json_atomic(receipt_path, receipt.model_dump(mode="json"))
    limitations = [
        "Pre-QA fit adjusts only the bounded comparison camera.",
        "It does not edit custom-mesh vertices, semantic IDs, materials, or interiors.",
        "This diagnostic is not the canonical seven-pass V0.6 QA run.",
    ]
    if not attempts[best_index].metrics or not attempts[best_index].metrics.scorable:
        limitations.append(
            "Primary fit evidence was unscorable; the initial candidate was retained."
        )
    report = BackgroundFitReport(
        job_id=job_id,
        workflow_id=workflow_id,
        status=(
            "completed"
            if attempts[best_index].metrics is not None
            and attempts[best_index].metrics.scorable
            else "degraded"
        ),
        input_fingerprint=input_fingerprint,
        max_refinement_attempts=max_attempts,
        initial_candidate_sha256=initial_hash,
        selected_candidate_sha256=selected_hash,
        selected_attempt_index=best_index,
        role_map_path=_job_relative(root, role_map_path),
        role_map_sha256=role_map_hash,
        promotion_receipt_path=_job_relative(root, receipt_path),
        promotion_receipt_sha256=sha256_file(receipt_path),
        attempts=attempts,
        limitations=limitations,
        completed_at=datetime.now(UTC),
    )
    write_json_atomic(fit_root / "fit_report.json", report.model_dump(mode="json"))
    return report
