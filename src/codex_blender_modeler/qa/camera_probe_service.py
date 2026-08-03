"""Render and score bounded camera probes as noncanonical V0.6 companion evidence."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from ..background_quality.models import BackgroundRoleMap
from ..background_quality.roles import assignment_roles, derive_background_role_map
from ..blender_artifacts import native_io_path, write_json_atomic
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..models import SceneSpec
from ..workspace import file_exists, sha256_file
from .diagnostic_models import (
    BoundedCameraDelta,
    CameraProbeResult,
    CameraProbeSemanticScore,
)
from .direct_compare import observed_regions_from_scene_spec
from .image_io import open_image
from .semantic_localizer import extract_semantic_bboxes, semantic_mask_image
from .semantic_shape import compare_semantic_masks, semantic_shape_similarity_score

_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PRIMARY_MASK_SOURCES = {
    "canonical_primary_object_reference",
    "semantic_primary_supporting_union",
}
SemanticProbeMask = tuple[Path, str, float]
_TERMINAL_CONTRACT = "camera_probe_terminal_v2"


def _utc_now() -> datetime:
    """Return a timezone-aware timestamp for evidence publication leases."""

    return datetime.now(UTC)


def _read_publication_lease(path: Path) -> dict[str, Any]:
    """Load one strict publication lease or fail closed on malformed ownership data."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Evidence publication lease exists but is unreadable: {path}"
        ) from exc
    required = {
        "lease_id",
        "owner_kind",
        "owner_id",
        "process_id",
        "acquired_at",
        "expires_at",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise RuntimeError(f"Evidence publication lease is malformed: {path}")
    lease_id = payload.get("lease_id")
    if not isinstance(lease_id, str) or not re.fullmatch(r"[0-9a-f]{32}", lease_id):
        raise RuntimeError(f"Evidence publication lease ID is malformed: {path}")
    try:
        acquired_at = datetime.fromisoformat(str(payload["acquired_at"]))
        expires_at = datetime.fromisoformat(str(payload["expires_at"]))
    except ValueError as exc:
        raise RuntimeError(f"Evidence publication lease timestamps are malformed: {path}") from exc
    if (
        acquired_at.tzinfo is None
        or expires_at.tzinfo is None
        or expires_at <= acquired_at
    ):
        raise RuntimeError(f"Evidence publication lease timestamps are invalid: {path}")
    return payload


def _archive_stale_publication_lease(path: Path, payload: Mapping[str, Any]) -> Path:
    """Archive one expired lease before another writer acquires the evidence scope."""

    history = path.parent / "stale_leases"
    history.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    destination = history / f"{stamp}_{payload['lease_id']}.json"
    os.replace(native_io_path(path), native_io_path(destination))
    return destination


@contextmanager
def artifact_publication_lease(
    scope_root: Path,
    *,
    owner_kind: str,
    owner_id: str,
    ttl_seconds: int = 3600,
) -> Iterator[dict[str, Any]]:
    """Hold one scope-local lease while immutable diagnostic evidence is published."""

    if ttl_seconds < 30 or ttl_seconds > 86400:
        raise ValueError("evidence publication lease TTL must be within [30, 86400]")
    scope = scope_root.expanduser().resolve()
    scope.mkdir(parents=True, exist_ok=True)
    lease_path = scope / ".publication_lease.json"
    now = _utc_now()
    payload: dict[str, Any] = {
        "lease_id": uuid4().hex,
        "owner_kind": owner_kind,
        "owner_id": owner_id,
        "process_id": os.getpid(),
        "acquired_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
    }
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    for _attempt in range(3):
        try:
            descriptor = os.open(
                native_io_path(lease_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            existing = _read_publication_lease(lease_path)
            expires_at = datetime.fromisoformat(str(existing["expires_at"]))
            if expires_at > _utc_now():
                raise RuntimeError(
                    "Another live writer owns the evidence publication lease: "
                    f"owner={existing['owner_kind']}:{existing['owner_id']} "
                    f"expires={expires_at.isoformat()}"
                ) from None
            try:
                _archive_stale_publication_lease(lease_path, existing)
            except FileNotFoundError:
                continue
            continue
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        break
    else:
        raise RuntimeError(f"Could not acquire evidence publication lease: {lease_path}")
    try:
        yield payload
    finally:
        if not lease_path.is_file():
            raise RuntimeError("Evidence publication lease disappeared before release")
        current = _read_publication_lease(lease_path)
        if current["lease_id"] != payload["lease_id"]:
            raise RuntimeError(
                "Evidence publication lease ownership changed; refusing to release it"
            )
        lease_path.unlink()


def write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    """Create one terminal JSON artifact exactly once without overwrite semantics."""

    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(dict(payload), indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    try:
        descriptor = os.open(
            native_io_path(destination),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError as exc:
        raise FileExistsError(f"immutable terminal artifact already exists: {destination}") from exc
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _job_relative(root: Path, path: Path) -> str:
    """Serialize one diagnostic artifact as a normalized job-relative POSIX path."""

    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        return resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"camera diagnostic artifact is outside the job: {resolved}") from exc


def _resolve_job_path(root: Path, value: str) -> Path:
    """Resolve one manifest path while preventing traversal outside the job root."""

    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"camera diagnostic path escapes the job: {value}") from exc
    return candidate


def _probe_deltas(max_nonbaseline: int) -> list[tuple[str, BoundedCameraDelta]]:
    """Return one neutral baseline plus a deterministic bounded camera probe sequence."""

    if max_nonbaseline < 1 or max_nonbaseline > 12:
        raise ValueError("max_camera_probes must be within [1, 12]")
    candidates = [
        ("yaw-positive", BoundedCameraDelta(rotation_delta_deg=(7.5, 0.0, 0.0))),
        ("yaw-negative", BoundedCameraDelta(rotation_delta_deg=(-7.5, 0.0, 0.0))),
        ("pitch-positive", BoundedCameraDelta(rotation_delta_deg=(0.0, 5.0, 0.0))),
        ("pitch-negative", BoundedCameraDelta(rotation_delta_deg=(0.0, -5.0, 0.0))),
        ("framing-near", BoundedCameraDelta(projection_scale=0.9)),
        ("framing-far", BoundedCameraDelta(projection_scale=1.1)),
        ("distance-near", BoundedCameraDelta(distance_scale=0.9)),
        ("distance-far", BoundedCameraDelta(distance_scale=1.1)),
        ("target-right", BoundedCameraDelta(target_offset_norm=(0.05, 0.0))),
        ("target-left", BoundedCameraDelta(target_offset_norm=(-0.05, 0.0))),
        ("target-up", BoundedCameraDelta(target_offset_norm=(0.0, 0.05))),
        ("target-down", BoundedCameraDelta(target_offset_norm=(0.0, -0.05))),
    ]
    return [("baseline", BoundedCameraDelta()), *candidates[:max_nonbaseline]]


def _bbox_similarity(
    reference: tuple[float, float, float, float],
    rendered: tuple[float, float, float, float] | None,
) -> float | None:
    """Convert observed and rendered semantic boxes into one bounded advisory score."""

    if rendered is None:
        return 0.0
    ref_center = ((reference[0] + reference[2]) / 2, (reference[1] + reference[3]) / 2)
    out_center = ((rendered[0] + rendered[2]) / 2, (rendered[1] + rendered[3]) / 2)
    ref_size = (reference[2] - reference[0], reference[3] - reference[1])
    out_size = (rendered[2] - rendered[0], rendered[3] - rendered[1])
    center_error = math.dist(ref_center, out_center) / math.sqrt(2)
    size_error = math.dist(ref_size, out_size) / math.sqrt(2)
    return max(0.0, 1.0 - min(1.0, center_error + size_error))


def _silhouette_iou(reference_path: Path, rendered_path: Path) -> float | None:
    """Score one exact broad-subject reference mask against a rendered silhouette."""

    with open_image(rendered_path) as opened:
        rendered = opened.convert("L").point(lambda value: 255 if value >= 128 else 0)
    with open_image(reference_path) as opened:
        reference = opened.convert("L").point(lambda value: 255 if value >= 128 else 0)
        if reference.size != rendered.size:
            reference = reference.resize(rendered.size, Image.Resampling.NEAREST)
    reference_pixels = reference.tobytes()
    rendered_pixels = rendered.tobytes()
    intersection = sum(
        1
        for reference_value, rendered_value in zip(
            reference_pixels,
            rendered_pixels,
            strict=True,
        )
        if reference_value and rendered_value
    )
    union = sum(
        1
        for reference_value, rendered_value in zip(
            reference_pixels,
            rendered_pixels,
            strict=True,
        )
        if reference_value or rendered_value
    )
    return intersection / union if union else None


def _primary_reference_mask_binding(
    root: Path,
    path: Path | None,
    expected_sha256: str | None,
    source: str | None,
) -> tuple[dict[str, str] | None, Path | None]:
    """Validate an optional exact primary-subject mask and serialize its plan binding."""

    supplied = (path is not None, expected_sha256 is not None, source is not None)
    if any(supplied) and not all(supplied):
        raise ValueError("primary reference mask path, hash, and source are required together")
    if not any(supplied):
        return None, None
    assert path is not None
    assert expected_sha256 is not None
    assert source is not None
    resolved = path.expanduser().resolve()
    relative = _job_relative(root, resolved)
    if source not in _PRIMARY_MASK_SOURCES:
        raise ValueError("unsupported primary reference mask source")
    if not _SHA256.fullmatch(expected_sha256):
        raise ValueError("primary reference mask requires one lowercase SHA-256 digest")
    if not file_exists(resolved) or sha256_file(resolved) != expected_sha256:
        raise ValueError("primary reference mask is missing or stale")
    return (
        {
            "path": relative,
            "sha256": expected_sha256,
            "source": source,
        },
        resolved,
    )


def _semantic_reference_mask_bindings(
    root: Path,
    values: Mapping[str, SemanticProbeMask] | None,
) -> tuple[list[dict[str, object]], dict[str, SemanticProbeMask]]:
    """Validate exact per-part masks and serialize their immutable probe bindings."""

    records: list[dict[str, object]] = []
    normalized: dict[str, SemanticProbeMask] = {}
    for semantic_id, raw in sorted((values or {}).items()):
        path, expected_sha256, confidence = raw
        if not semantic_id or any(character.isspace() for character in semantic_id):
            raise ValueError("semantic camera-probe IDs must be nonblank and whitespace-free")
        if not _SHA256.fullmatch(expected_sha256):
            raise ValueError(f"semantic camera-probe mask has an invalid hash: {semantic_id}")
        if not 0 <= confidence <= 1:
            raise ValueError(
                f"semantic camera-probe confidence must be within [0, 1]: {semantic_id}"
            )
        resolved = path.expanduser().resolve()
        relative = _job_relative(root, resolved)
        if not file_exists(resolved) or sha256_file(resolved) != expected_sha256:
            raise ValueError(f"semantic camera-probe mask is missing or stale: {semantic_id}")
        normalized[semantic_id] = (resolved, expected_sha256, confidence)
        records.append(
            {
                "semantic_id": semantic_id,
                "path": relative,
                "sha256": expected_sha256,
                "confidence": confidence,
            }
        )
    return records, normalized


def _pass_path(
    probe: Mapping[str, Any],
    kind: str,
    root: Path,
    *,
    expected_path: Path,
) -> Path:
    """Resolve one exact probe pass record from the Blender manifest."""

    records = probe.get("passes")
    if not isinstance(records, list):
        raise ValueError("camera probe manifest entry has no passes")
    matches = [item for item in records if isinstance(item, dict) and item.get("kind") == kind]
    if len(matches) != 1:
        raise ValueError(f"camera probe requires exactly one {kind} pass")
    record = matches[0]
    relative_path = record.get("path")
    expected_sha256 = record.get("sha256")
    if not isinstance(relative_path, str) or not _SHA256.fullmatch(
        str(expected_sha256)
    ):
        raise ValueError(f"camera probe {kind} pass binding is invalid")
    path = _resolve_job_path(root, relative_path)
    if path != expected_path.resolve():
        raise ValueError(
            f"camera probe {kind} pass does not use its exact run-owned path"
        )
    if not file_exists(path) or sha256_file(path) != record.get("sha256"):
        raise ValueError(f"camera probe {kind} pass is missing or changed")
    return path


def _score_probe(
    probe: Mapping[str, Any],
    *,
    root: Path,
    manifest_path: Path,
    manifest_sha256: str,
    expected_probe_dir: Path,
    object_colors: Mapping[str, str],
    observed: Mapping[str, tuple[tuple[float, float, float, float], float]],
    selected_ids: Sequence[str],
    primary_reference_mask_path: Path | None,
    semantic_reference_masks: Mapping[str, SemanticProbeMask],
) -> CameraProbeResult:
    """Score one probe from exact part masks when available, otherwise observed bboxes."""

    object_id_path = _pass_path(
        probe,
        "object_id",
        root,
        expected_path=expected_probe_dir / "object_id.png",
    )
    rendered = extract_semantic_bboxes(object_id_path, object_colors)
    primary_silhouette_score: float | None = None
    if primary_reference_mask_path is not None:
        silhouette_path = _pass_path(
            probe,
            "silhouette",
            root,
            expected_path=expected_probe_dir / "silhouette.png",
        )
        primary_silhouette_score = _silhouette_iou(
            primary_reference_mask_path,
            silhouette_path,
        )
    semantic_scores: list[CameraProbeSemanticScore] = []
    weighted_score = 0.0
    confidence_total = 0.0
    limitations: list[str] = []
    for semantic_id in selected_ids:
        evidence = observed.get(semantic_id)
        semantic_reference = semantic_reference_masks.get(semantic_id)
        if semantic_reference is not None:
            reference_path, _reference_sha256, confidence = semantic_reference
            rendered_mask = semantic_mask_image(
                object_id_path,
                object_colors[semantic_id],
            )
            with open_image(reference_path) as opened:
                reference_mask = opened.convert("L").point(
                    lambda value: 255 if value >= 128 else 0
                )
                if reference_mask.size != rendered_mask.size:
                    reference_mask = reference_mask.resize(
                        rendered_mask.size,
                        Image.Resampling.NEAREST,
                    )
            metrics = compare_semantic_masks(
                reference_mask,
                rendered_mask,
                semantic_id=semantic_id,
            )
            score = semantic_shape_similarity_score(metrics)
            if score is None:
                semantic_scores.append(
                    CameraProbeSemanticScore(
                        semantic_id=semantic_id,
                        scorable=False,
                        score_basis="semantic_shape",
                        limitations=[*metrics.limitations],
                    )
                )
                continue
            semantic_scores.append(
                CameraProbeSemanticScore(
                    semantic_id=semantic_id,
                    scorable=True,
                    score_basis="semantic_shape",
                    score=round(score, 6),
                    limitations=[*metrics.limitations],
                )
            )
            weighted_score += score * confidence
            confidence_total += confidence
            continue
        if evidence is None:
            semantic_scores.append(
                CameraProbeSemanticScore(
                    semantic_id=semantic_id,
                    scorable=False,
                    limitations=["No observed reference bbox is available for this semantic ID."],
                )
            )
            continue
        reference_bbox, confidence = evidence
        score = _bbox_similarity(reference_bbox, rendered.get(semantic_id))
        assert score is not None
        semantic_scores.append(
            CameraProbeSemanticScore(
                semantic_id=semantic_id,
                scorable=True,
                score_basis="bbox",
                score=round(score, 6),
            )
        )
        weighted_score += score * confidence
        confidence_total += confidence
    if confidence_total <= 0:
        limitations.append(
            "No reliable explicit semantic mask or observed bbox could score this camera probe."
        )
        status = "unscorable"
        overall = None
    else:
        status = "scored"
        overall = round(weighted_score / confidence_total, 6)
    if primary_reference_mask_path is not None and primary_silhouette_score is None:
        limitations.append("Exact primary-subject silhouette union is empty and unscorable.")
    delta = BoundedCameraDelta.model_validate(probe.get("camera_delta", {}))
    probe_id = str(probe["probe_id"])
    return CameraProbeResult(
        probe_id=probe_id,
        is_baseline=probe_id == "baseline",
        status=status,
        camera_delta=delta,
        overall_score=overall,
        primary_silhouette_score=(
            round(primary_silhouette_score, 6)
            if primary_silhouette_score is not None
            else None
        ),
        semantic_scores=semantic_scores,
        evidence_path=_job_relative(root, manifest_path),
        evidence_sha256=manifest_sha256,
        limitations=limitations,
    )


def _require_current_hash(path: Path, expected_sha256: str, label: str) -> None:
    """Fail closed when one immutable diagnostic input is missing or has changed."""

    if not file_exists(path) or sha256_file(path) != expected_sha256:
        raise RuntimeError(f"bounded camera diagnostic {label} changed during rendering")


def _validated_manifest_probes(
    manifest: Mapping[str, Any],
    *,
    root: Path,
    output_dir: Path,
    expected_deltas: Sequence[tuple[str, BoundedCameraDelta]],
    selected_ids: Sequence[str],
    primary_reference_mask: Mapping[str, str] | None,
) -> tuple[list[Mapping[str, Any]], dict[str, str]]:
    """Validate exact probe identities, deltas, pass ownership, and color bindings."""

    raw_probes = manifest.get("probes")
    colors = manifest.get("object_id_colors")
    if not isinstance(raw_probes, list) or not isinstance(colors, dict):
        raise ValueError("bounded camera probe manifest is incomplete")
    if not all(isinstance(probe, dict) for probe in raw_probes):
        raise ValueError("bounded camera probe manifest contains a malformed probe")
    if len(raw_probes) != len(expected_deltas):
        raise ValueError("bounded camera probe manifest has an unexpected probe count")
    expected_ids = [probe_id for probe_id, _delta in expected_deltas]
    actual_ids = [str(probe.get("probe_id", "")) for probe in raw_probes]
    if actual_ids != expected_ids or len(actual_ids) != len(set(actual_ids)):
        raise ValueError("bounded camera probe manifest does not match the exact probe plan")
    if manifest.get("target_ids") != list(selected_ids):
        raise ValueError("bounded camera probe manifest target IDs changed")
    if manifest.get("primary_reference_mask") != primary_reference_mask:
        raise ValueError("bounded camera probe primary-reference mask binding changed")
    normalized_colors = {str(key): str(value) for key, value in colors.items()}
    if sorted(normalized_colors) != list(selected_ids):
        raise ValueError("bounded camera probe manifest color IDs changed")
    for probe, (probe_id, expected_delta) in zip(
        raw_probes,
        expected_deltas,
        strict=True,
    ):
        actual_delta = BoundedCameraDelta.model_validate(probe.get("camera_delta", {}))
        if actual_delta != expected_delta:
            raise ValueError(f"camera probe delta changed for {probe_id}")
        passes = probe.get("passes")
        if not isinstance(passes, list):
            raise ValueError(f"camera probe {probe_id} has no pass records")
        pass_kinds = [
            str(record.get("kind", ""))
            for record in passes
            if isinstance(record, dict)
        ]
        if sorted(pass_kinds) != ["object_id", "silhouette"] or len(passes) != 2:
            raise ValueError(
                f"camera probe {probe_id} requires exactly silhouette and object_id passes"
            )
        expected_probe_dir = output_dir / probe_id
        for kind in ("silhouette", "object_id"):
            _pass_path(
                probe,
                kind,
                root,
                expected_path=expected_probe_dir / f"{kind}.png",
            )
    return list(raw_probes), normalized_colors


def _validate_diagnostic_artifact_root(
    artifact_root: Path,
    expected_root: Path,
) -> None:
    """Allow the canonical diagnostic root or one immutable numbered attempt below it."""

    if artifact_root == expected_root:
        return
    try:
        relative = artifact_root.relative_to(expected_root)
    except ValueError as exc:
        raise ValueError(
            "camera diagnostic artifact_root must remain inside the exact diagnostic root"
        ) from exc
    if (
        len(relative.parts) != 2
        or relative.parts[0] != "attempts"
        or not re.fullmatch(r"attempt-[0-9]{3}", relative.parts[1])
    ):
        raise ValueError(
            "camera diagnostic attempt roots must use attempts/attempt-NNN"
        )


def _expected_probe_resolution(spec: SceneSpec, maximum: int) -> tuple[int, int]:
    """Mirror Blender's bounded aspect-preserving probe resolution calculation."""

    width, height = spec.camera.resolution
    scale = min(1.0, maximum / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def _validate_probe_camera_record(record: Any, probe_id: str) -> None:
    """Require one finite actual-camera record for strict terminal probe evidence."""

    if not isinstance(record, dict):
        raise ValueError(f"camera probe {probe_id} has no actual camera record")
    required_sequences = ("location", "rotation_deg")
    for field in required_sequences:
        values = record.get(field)
        if (
            not isinstance(values, list)
            or len(values) != 3
            or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values)
        ):
            raise ValueError(f"camera probe {probe_id} has an invalid {field} record")
    projection = record.get("projection") or record.get("type")
    if projection not in {"PERSP", "ORTHO"}:
        raise ValueError(f"camera probe {probe_id} has an invalid projection record")
    numeric = [
        record.get("lens_mm"),
        record.get("ortho_scale"),
        record.get("clip_start"),
        record.get("clip_end"),
    ]
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in numeric):
        raise ValueError(f"camera probe {probe_id} has invalid lens or clipping data")
    if float(numeric[0]) <= 0 or float(numeric[2]) <= 0 or float(numeric[3]) <= float(numeric[2]):
        raise ValueError(f"camera probe {probe_id} has unsafe lens or clipping data")


def validate_camera_probe_terminal_evidence(
    root: Path,
    *,
    plan_path: Path,
    plan_sha256: str,
    manifest_path: Path,
    manifest_sha256: str,
    role_map_path: Path,
    role_map_sha256: str,
    expected_job_id: str | None = None,
    expected_qa_run_id: str | None = None,
    expected_diagnostic_id: str | None = None,
    report_probes: Sequence[CameraProbeResult] | None = None,
    report_semantic_ids: Sequence[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replay a camera-probe plan, manifest, passes, provenance, and report membership."""

    resolved_root = root.expanduser().resolve()
    resolved_plan = plan_path.expanduser().resolve()
    resolved_manifest = manifest_path.expanduser().resolve()
    resolved_role_map = role_map_path.expanduser().resolve()
    for path in (resolved_plan, resolved_manifest, resolved_role_map):
        _job_relative(resolved_root, path)
    if resolved_manifest != resolved_plan.parent / "render_manifest.json":
        raise ValueError("camera probe manifest is not beside its exact probe plan")
    if resolved_role_map != resolved_plan.parent.parent / "role_map.json":
        raise ValueError("camera probe role map is not owned by the exact diagnostic attempt")
    _require_current_hash(resolved_plan, plan_sha256, "terminal probe plan")
    _require_current_hash(resolved_manifest, manifest_sha256, "terminal render manifest")
    _require_current_hash(resolved_role_map, role_map_sha256, "terminal role map")
    try:
        plan = json.loads(resolved_plan.read_text(encoding="utf-8"))
        manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("camera probe terminal evidence is invalid JSON") from exc
    if not isinstance(plan, dict) or not isinstance(manifest, dict):
        raise ValueError("camera probe terminal evidence must contain JSON objects")
    identities = (
        ("job_id", expected_job_id),
        ("qa_run_id", expected_qa_run_id),
        ("diagnostic_id", expected_diagnostic_id),
    )
    if (
        plan.get("schema_version") != "0.6.0"
        or manifest.get("schema_version") != "0.6.0"
        or plan.get("diagnostic_kind") != "bounded_camera_probe"
        or manifest.get("diagnostic_kind") != "bounded_camera_probe"
        or manifest.get("probe_plan_sha256") != plan_sha256
        or plan.get("role_map_sha256") != role_map_sha256
        or manifest.get("role_map_sha256") != role_map_sha256
        or any(
            expected is not None
            and (plan.get(field) != expected or manifest.get(field) != expected)
            for field, expected in identities
        )
    ):
        raise ValueError("camera probe terminal identity or plan binding is invalid")
    strict = plan.get("terminal_contract") == _TERMINAL_CONTRACT
    if strict and (
        plan.get("canonical_v06_qa_run") is not False
        or manifest.get("canonical_v06_qa_run") is not False
    ):
        raise ValueError("strict camera probes must remain noncanonical diagnostics")
    raw_plan_probes = plan.get("probes")
    if not isinstance(raw_plan_probes, list) or not raw_plan_probes:
        raise ValueError("camera probe plan has no probes")
    plan_deltas: list[tuple[str, BoundedCameraDelta]] = []
    for raw_probe in raw_plan_probes:
        if not isinstance(raw_probe, dict) or not isinstance(raw_probe.get("probe_id"), str):
            raise ValueError("camera probe plan contains a malformed probe")
        plan_deltas.append(
            (
                str(raw_probe["probe_id"]),
                BoundedCameraDelta.model_validate(raw_probe.get("camera_delta", {})),
            )
        )
    if strict:
        if len(plan_deltas) < 2 or len(plan_deltas) > 13:
            raise ValueError("strict camera probe plan requires baseline plus bounded probes")
        if plan_deltas != _probe_deltas(len(plan_deltas) - 1):
            raise ValueError("strict camera probe plan changed its deterministic delta family")
        role_map = BackgroundRoleMap.model_validate_json(
            resolved_role_map.read_text(encoding="utf-8")
        )
        selected_ids = sorted(
            semantic_id
            for semantic_id, role in assignment_roles(role_map).items()
            if role in {"primary", "supporting"}
        )
        required_fields = {
            "target_ids",
            "scene_spec_path",
            "scene_spec_sha256",
            "camera_fingerprint",
            "build_fingerprint",
            "source_blend_path",
            "source_blend_sha256",
            "render_resolution",
        }
        if not required_fields.issubset(plan):
            raise ValueError("strict camera probe plan omits generation-time provenance")
        if (
            role_map.job_id != plan.get("job_id")
            or role_map.scene_spec_sha256 != plan.get("scene_spec_sha256")
            or plan.get("target_ids") != selected_ids
            or manifest.get("target_ids") != selected_ids
            or manifest.get("scene_spec_sha256") != plan.get("scene_spec_sha256")
            or manifest.get("camera_fingerprint") != plan.get("camera_fingerprint")
            or manifest.get("build_fingerprint") != plan.get("build_fingerprint")
            or manifest.get("source_blend_sha256") != plan.get("source_blend_sha256")
            or manifest.get("resolution") != plan.get("render_resolution")
        ):
            raise ValueError("camera probe generation-time provenance changed")
    else:
        raw_targets = manifest.get("target_ids") or plan.get("target_ids") or []
        if not isinstance(raw_targets, list):
            raise ValueError("legacy camera probe target membership is malformed")
        selected_ids = sorted(str(value) for value in raw_targets)
    primary_binding = plan.get("primary_reference_mask")
    if primary_binding is not None:
        if not isinstance(primary_binding, dict):
            raise ValueError("camera probe primary-reference binding is malformed")
        _require_current_hash(
            _resolve_job_path(resolved_root, str(primary_binding.get("path", ""))),
            str(primary_binding.get("sha256", "")),
            "terminal primary reference mask",
        )
    semantic_bindings = plan.get("semantic_reference_masks", [])
    if not isinstance(semantic_bindings, list):
        raise ValueError("camera probe semantic-reference bindings are malformed")
    semantic_ids: list[str] = []
    for binding in semantic_bindings:
        if not isinstance(binding, dict) or not isinstance(binding.get("semantic_id"), str):
            raise ValueError("camera probe semantic-reference binding is malformed")
        semantic_id = str(binding["semantic_id"])
        semantic_ids.append(semantic_id)
        _require_current_hash(
            _resolve_job_path(resolved_root, str(binding.get("path", ""))),
            str(binding.get("sha256", "")),
            f"terminal semantic reference mask {semantic_id}",
        )
    if len(semantic_ids) != len(set(semantic_ids)) or (
        strict and not set(semantic_ids).issubset(selected_ids)
    ):
        raise ValueError("camera probe semantic-reference membership is invalid")
    if strict:
        raw_probes, colors = _validated_manifest_probes(
            manifest,
            root=resolved_root,
            output_dir=resolved_plan.parent / "renders",
            expected_deltas=plan_deltas,
            selected_ids=selected_ids,
            primary_reference_mask=primary_binding,
        )
        expected_resolution = tuple(int(value) for value in plan["render_resolution"])
        for probe in raw_probes:
            probe_id = str(probe["probe_id"])
            _validate_probe_camera_record(probe.get("camera"), probe_id)
            for record in probe["passes"]:
                if (
                    (int(record.get("width", -1)), int(record.get("height", -1)))
                    != expected_resolution
                    or record.get("encoding") != "png-rgb8"
                ):
                    raise ValueError(f"camera probe {probe_id} pass metadata changed")
        if sorted(colors) != selected_ids:
            raise ValueError("camera probe object-ID color membership changed")
    else:
        raw_probes = manifest.get("probes")
        if not isinstance(raw_probes, list):
            raise ValueError("legacy camera probe manifest has no probes")
        for probe in raw_probes:
            if not isinstance(probe, dict):
                raise ValueError("legacy camera probe manifest entry is malformed")
            _validate_nested_legacy_probe_passes(resolved_root, probe)
    manifest_ids = [str(item.get("probe_id", "")) for item in raw_probes]
    plan_ids = [item[0] for item in plan_deltas]
    if manifest_ids != plan_ids or len(manifest_ids) != len(set(manifest_ids)):
        raise ValueError("camera probe membership differs between plan and manifest")
    if report_probes is not None:
        if [probe.probe_id for probe in report_probes] != manifest_ids:
            raise ValueError("camera probe report membership differs from terminal evidence")
        for result, (_probe_id, expected_delta) in zip(
            report_probes,
            plan_deltas,
            strict=True,
        ):
            if (
                result.camera_delta != expected_delta
                or result.evidence_path != _job_relative(resolved_root, resolved_manifest)
                or result.evidence_sha256 != manifest_sha256
            ):
                raise ValueError("camera probe report provenance differs from its plan")
            score_ids = [item.semantic_id for item in result.semantic_scores]
            if strict and score_ids != selected_ids:
                raise ValueError("camera probe report semantic membership changed")
    if (
        report_semantic_ids is not None
        and (strict or semantic_ids)
        and sorted(report_semantic_ids) != sorted(semantic_ids)
    ):
        raise ValueError("semantic shape report membership differs from probe bindings")
    return plan, manifest


def _validate_nested_legacy_probe_passes(root: Path, probe: Mapping[str, Any]) -> None:
    """Keep legacy probe bundles readable while still re-hashing every declared pass."""

    records = probe.get("passes")
    if not isinstance(records, list) or len(records) != 2:
        raise ValueError("legacy camera probe requires exactly two pass records")
    kinds = [str(record.get("kind", "")) for record in records if isinstance(record, dict)]
    if sorted(kinds) != ["object_id", "silhouette"]:
        raise ValueError("legacy camera probe pass membership changed")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("legacy camera probe pass record is malformed")
        _require_current_hash(
            _resolve_job_path(root, str(record.get("path", ""))),
            str(record.get("sha256", "")),
            "legacy terminal probe pass",
        )


def run_bounded_camera_probes(
    root: Path,
    *,
    job_id: str,
    qa_run_id: str,
    diagnostic_id: str,
    artifact_root: Path,
    scene_spec_path: Path,
    camera_fingerprint: str,
    max_camera_probes: int = 6,
    resolution: int = 256,
    render_engine: str = "eevee",
    render_device: str = "auto",
    primary_reference_mask_path: Path | None = None,
    primary_reference_mask_sha256: str | None = None,
    primary_reference_mask_source: str | None = None,
    semantic_reference_masks: Mapping[str, SemanticProbeMask] | None = None,
) -> tuple[list[CameraProbeResult], Path, Path]:
    """Render one bounded camera family and return exact advisory probe scores."""

    root = root.expanduser().resolve()
    scene_spec_path = scene_spec_path.expanduser().resolve()
    artifact_root = artifact_root.expanduser().resolve()
    if (
        not _SAFE_ID.fullmatch(job_id)
        or not _SAFE_ID.fullmatch(qa_run_id)
        or not _SAFE_ID.fullmatch(diagnostic_id)
    ):
        raise ValueError("QA run and diagnostic IDs must be portable identifiers")
    if not _SHA256.fullmatch(camera_fingerprint):
        raise ValueError("camera_fingerprint must be one lowercase SHA-256 digest")
    if resolution < 64 or resolution > 512:
        raise ValueError("camera probe resolution must be within [64, 512]")
    primary_mask_binding, primary_mask_path = _primary_reference_mask_binding(
        root,
        primary_reference_mask_path,
        primary_reference_mask_sha256,
        primary_reference_mask_source,
    )
    semantic_mask_bindings, normalized_semantic_masks = (
        _semantic_reference_mask_bindings(root, semantic_reference_masks)
    )
    _job_relative(root, scene_spec_path)
    _job_relative(root, artifact_root)
    expected_artifact_root = (
        root / "qa" / "runs" / qa_run_id / "diagnostics" / diagnostic_id
    ).resolve()
    _validate_diagnostic_artifact_root(artifact_root, expected_artifact_root)
    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    if spec.job_id != job_id:
        raise ValueError("camera diagnostic SceneSpec belongs to another job")
    reference_ids = {source.id for source in spec.sources if source.kind == "reference"}
    observed = observed_regions_from_scene_spec(
        scene_spec_path,
        source_ids=reference_ids,
    )
    role_map = derive_background_role_map(
        scene_spec_path,
        job_id=job_id,
        workflow_id=f"qa-diagnostic-{diagnostic_id}",
    )
    role_map_path = artifact_root / "role_map.json"
    write_json_atomic(role_map_path, role_map.model_dump(mode="json"))
    role_map_sha256 = sha256_file(role_map_path)
    roles = assignment_roles(role_map)
    selected_ids = sorted(
        semantic_id
        for semantic_id, role in roles.items()
        if role in {"primary", "supporting"}
    )
    if not selected_ids:
        raise ValueError("camera diagnostics require a primary or supporting semantic ID")
    unrelated_masks = sorted(set(normalized_semantic_masks) - set(selected_ids))
    if unrelated_masks:
        raise ValueError(
            "semantic camera-probe masks must target only primary/supporting IDs: "
            f"{unrelated_masks}"
        )
    deltas = _probe_deltas(max_camera_probes)
    scene_spec_sha256 = sha256_file(scene_spec_path)
    blend_path = root / "blender" / "scene.blend"
    if not file_exists(blend_path):
        raise FileNotFoundError(f"camera diagnostics require a built scene: {blend_path}")
    blend_hash = sha256_file(blend_path)
    provenance = collect_build_provenance(root, job_id, scene_spec_path=scene_spec_path)
    if str(provenance.get("scene_spec_sha256")) != scene_spec_sha256:
        raise RuntimeError("build provenance is not bound to the current SceneSpec")
    render_resolution = _expected_probe_resolution(spec, resolution)
    probe_plan = {
        "schema_version": "0.6.0",
        "diagnostic_kind": "bounded_camera_probe",
        "canonical_v06_qa_run": False,
        "terminal_contract": _TERMINAL_CONTRACT,
        "job_id": job_id,
        "qa_run_id": qa_run_id,
        "diagnostic_id": diagnostic_id,
        "scene_spec_path": _job_relative(root, scene_spec_path),
        "scene_spec_sha256": scene_spec_sha256,
        "camera_fingerprint": camera_fingerprint,
        "build_fingerprint": str(provenance["fingerprint"]),
        "source_blend_path": _job_relative(root, blend_path),
        "source_blend_sha256": blend_hash,
        "role_map_sha256": role_map_sha256,
        "target_ids": selected_ids,
        "requested_resolution": resolution,
        "render_resolution": list(render_resolution),
        "primary_reference_mask": primary_mask_binding,
        "semantic_reference_masks": semantic_mask_bindings,
        "probes": [
            {
                "probe_id": probe_id,
                "camera_delta": delta.model_dump(mode="json"),
            }
            for probe_id, delta in deltas
        ],
    }
    plan_path = artifact_root / "camera_probes" / "plan.json"
    write_json_atomic(plan_path, probe_plan)
    plan_sha256 = sha256_file(plan_path)
    manifest_path = artifact_root / "camera_probes" / "render_manifest.json"
    output_dir = artifact_root / "camera_probes" / "renders"
    try:
        run_blender(
            "render_camera_diagnostic_probes.py",
            [
                "--job-root",
                str(root),
                "--probe-plan",
                str(plan_path),
                "--probe-plan-sha256",
                plan_sha256,
                "--role-map",
                str(role_map_path),
                "--role-map-sha256",
                role_map_sha256,
                "--output-dir",
                str(output_dir),
                "--manifest",
                str(manifest_path),
                "--scene-spec",
                str(scene_spec_path),
                "--build-fingerprint",
                str(provenance["fingerprint"]),
                "--scene-spec-sha256",
                scene_spec_sha256,
                "--camera-fingerprint",
                camera_fingerprint,
                "--resolution",
                str(resolution),
                "--render-engine",
                render_engine,
                "--render-device",
                render_device,
            ],
            blend_file=blend_path,
        )
    except Exception as exc:
        if not file_exists(blend_path) or sha256_file(blend_path) != blend_hash:
            raise RuntimeError(
                "bounded camera diagnostics changed the authoring blend while failing"
            ) from exc
        raise
    if not file_exists(blend_path) or sha256_file(blend_path) != blend_hash:
        raise RuntimeError("bounded camera diagnostics changed the authoring blend")
    _require_current_hash(scene_spec_path, scene_spec_sha256, "SceneSpec")
    _require_current_hash(plan_path, plan_sha256, "probe plan")
    _require_current_hash(role_map_path, role_map_sha256, "role map")
    if primary_mask_path is not None:
        assert primary_reference_mask_sha256 is not None
        _require_current_hash(
            primary_mask_path,
            primary_reference_mask_sha256,
            "primary reference mask",
        )
    for semantic_id, (path, expected_sha256, _confidence) in (
        normalized_semantic_masks.items()
    ):
        _require_current_hash(path, expected_sha256, f"semantic mask {semantic_id}")
    if not file_exists(manifest_path):
        raise RuntimeError("bounded camera diagnostics did not create a render manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = (
        manifest.get("schema_version") == "0.6.0"
        and manifest.get("diagnostic_kind") == "bounded_camera_probe"
        and manifest.get("canonical_v06_qa_run") is False
        and manifest.get("job_id") == job_id
        and manifest.get("qa_run_id") == qa_run_id
        and manifest.get("diagnostic_id") == diagnostic_id
        and manifest.get("probe_plan_sha256") == plan_sha256
        and manifest.get("role_map_sha256") == role_map_sha256
        and manifest.get("scene_spec_sha256") == scene_spec_sha256
        and manifest.get("camera_fingerprint") == camera_fingerprint
        and manifest.get("build_fingerprint") == provenance["fingerprint"]
        and manifest.get("source_blend_sha256") == blend_hash
    )
    if not expected:
        raise RuntimeError("bounded camera probe manifest is not bound to current inputs")
    raw_probes, colors = _validated_manifest_probes(
        manifest,
        root=root,
        output_dir=output_dir,
        expected_deltas=deltas,
        selected_ids=selected_ids,
        primary_reference_mask=primary_mask_binding,
    )
    manifest_sha256 = sha256_file(manifest_path)
    results = [
        _score_probe(
            probe,
            root=root,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            expected_probe_dir=output_dir / str(probe["probe_id"]),
            object_colors=colors,
            observed=observed,
            selected_ids=selected_ids,
            primary_reference_mask_path=primary_mask_path,
            semantic_reference_masks=normalized_semantic_masks,
        )
        for probe in raw_probes
    ]
    _require_current_hash(manifest_path, manifest_sha256, "render manifest")
    _require_current_hash(scene_spec_path, scene_spec_sha256, "SceneSpec")
    _require_current_hash(plan_path, plan_sha256, "probe plan")
    _require_current_hash(role_map_path, role_map_sha256, "role map")
    if primary_mask_path is not None:
        assert primary_reference_mask_sha256 is not None
        _require_current_hash(
            primary_mask_path,
            primary_reference_mask_sha256,
            "primary reference mask",
        )
    for semantic_id, (path, expected_sha256, _confidence) in (
        normalized_semantic_masks.items()
    ):
        _require_current_hash(path, expected_sha256, f"semantic mask {semantic_id}")
    validate_camera_probe_terminal_evidence(
        root,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        role_map_path=role_map_path,
        role_map_sha256=role_map_sha256,
        expected_job_id=job_id,
        expected_qa_run_id=qa_run_id,
        expected_diagnostic_id=diagnostic_id,
        report_probes=results,
    )
    return results, plan_path, manifest_path
