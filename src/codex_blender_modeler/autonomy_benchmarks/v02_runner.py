"""Deterministic host runner for Autonomous Quality reference benchmark 0.2."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..blender_runner import run_blender
from ..integrated_quality.v02_contour_metrics import compare_contours_v02
from ..integrated_quality.v02_models import (
    ContourEvidenceBindingV02,
    SemanticEvidenceBindingV02,
)
from ..integrated_quality.v02_semantic_metrics import compare_semantic_masks_v02
from .v02_models import (
    BenchmarkArtifactV02,
    BenchmarkCaseResultV02,
    BenchmarkCaseV02,
    BenchmarkManifestV02,
    BenchmarkMetricSetV02,
    BenchmarkReportV02,
    BenchmarkStagePlanV02,
    BenchmarkStageResultV02,
    BlenderBenchmarkReceiptV02,
    MetricDirectionExpectationV02,
    MetricDirectionResultV02,
    SyntheticPrimitiveV02,
    benchmark_case_contract_sha256_v02,
    canonical_json_sha256_v02,
)


@dataclass(frozen=True)
class _RasterSet:
    """Hold one in-memory beauty, silhouette, object-ID, and semantic raster set."""

    width: int
    height: int
    beauty: bytes
    silhouette: bytes
    object_id: bytes
    semantic_masks: dict[str, bytes]


def _file_sha256(path: Path) -> str:
    """Return the exact SHA-256 of one existing benchmark artifact."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_output_path(path: Path) -> Path:
    """Resolve an immutable report target and reject a pre-existing run artifact root."""

    resolved = path.resolve()
    if resolved.exists():
        raise FileExistsError(f"benchmark v02 report already exists: {resolved.name}")
    artifact_root = resolved.parent / "artifacts"
    if artifact_root.exists():
        raise FileExistsError("benchmark v02 artifact root already exists")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    artifact_root.mkdir()
    return resolved


def _write_immutable(path: Path, data: bytes) -> None:
    """Write one benchmark artifact exactly once without an overwrite path."""

    if path.exists():
        raise FileExistsError(f"benchmark v02 artifact already exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_json_immutable(path: Path, value: Any) -> None:
    """Write stable pretty JSON once for human inspection and exact byte hashing."""

    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    _write_immutable(path, data)


def _portable_graymap(width: int, height: int, pixels: bytes) -> bytes:
    """Encode deterministic binary PGM bytes with no library-specific metadata."""

    if len(pixels) != width * height:
        raise ValueError("grayscale raster byte count does not match dimensions")
    return f"P5\n{width} {height}\n255\n".encode("ascii") + pixels


def _portable_pixmap(width: int, height: int, pixels: bytes) -> bytes:
    """Encode deterministic binary PPM bytes with no library-specific metadata."""

    if len(pixels) != width * height * 3:
        raise ValueError("RGB raster byte count does not match dimensions")
    return f"P6\n{width} {height}\n255\n".encode("ascii") + pixels


def _round_pixel(value: float) -> int:
    """Round a transformed pixel coordinate deterministically away from half-down drift."""

    return int(math.floor(value + 0.5))


def _transformed_bbox(
    primitive: SyntheticPrimitiveV02,
    stage: BenchmarkStagePlanV02 | None,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    """Apply one bounded stage framing and semantic offset to a primitive bbox."""

    if stage is None:
        return primitive.bbox_px
    center_x = width / 2.0
    center_y = height / 2.0
    offset_x, offset_y = stage.semantic_offsets_px.get(primitive.semantic_id, (0, 0))
    translation_x = stage.translation_px[0] + offset_x
    translation_y = stage.translation_px[1] + offset_y
    x0, y0, x1, y1 = primitive.bbox_px
    transformed = (
        _round_pixel(center_x + (x0 - center_x) * stage.uniform_scale + translation_x),
        _round_pixel(center_y + (y0 - center_y) * stage.uniform_scale + translation_y),
        _round_pixel(center_x + (x1 - center_x) * stage.uniform_scale + translation_x),
        _round_pixel(center_y + (y1 - center_y) * stage.uniform_scale + translation_y),
    )
    tx0, ty0, tx1, ty1 = transformed
    return (
        max(0, min(width, tx0)),
        max(0, min(height, ty0)),
        max(0, min(width, tx1)),
        max(0, min(height, ty1)),
    )


def _primitive_pixel_indices(
    primitive: SyntheticPrimitiveV02,
    bbox: tuple[int, int, int, int],
    width: int,
) -> list[int]:
    """Rasterize one rectangle or ellipse using exact bounded integer predicates."""

    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0:
        return []
    if primitive.shape == "rectangle":
        return [y * width + x for y in range(y0, y1) for x in range(x0, x1)]
    radius_x2 = x1 - x0
    radius_y2 = y1 - y0
    radius_x_squared = radius_x2 * radius_x2
    radius_y_squared = radius_y2 * radius_y2
    threshold = radius_x_squared * radius_y_squared
    indices: list[int] = []
    for y in range(y0, y1):
        dy2 = 2 * y + 1 - (y0 + y1)
        for x in range(x0, x1):
            dx2 = 2 * x + 1 - (x0 + x1)
            if (
                dx2 * dx2 * radius_y_squared
                + dy2 * dy2 * radius_x_squared
                <= threshold
            ):
                indices.append(y * width + x)
    return indices


def _render_case_rasters(
    case: BenchmarkCaseV02,
    stage: BenchmarkStagePlanV02 | None,
) -> _RasterSet:
    """Render deterministic synthetic evidence from one exact case and perturbation."""

    width, height = case.known_camera.resolution_px
    background = bytes(case.reference_recipe.background_rgb)
    beauty = bytearray(background * (width * height))
    silhouette = bytearray(width * height)
    object_id = bytearray(width * height)
    semantic_masks = {
        item.semantic_id: bytearray(width * height)
        for item in case.reference_recipe.primitives
    }
    omitted = set(stage.omitted_semantic_ids if stage is not None else [])
    for primitive in case.reference_recipe.primitives:
        if primitive.semantic_id in omitted:
            continue
        bbox = _transformed_bbox(primitive, stage, width, height)
        for index in _primitive_pixel_indices(primitive, bbox, width):
            silhouette[index] = 255
            object_id[index] = primitive.object_id
            semantic_masks[primitive.semantic_id][index] = 255
            rgb_index = index * 3
            beauty[rgb_index : rgb_index + 3] = bytes(primitive.color_rgb)
    return _RasterSet(
        width=width,
        height=height,
        beauty=_portable_pixmap(width, height, bytes(beauty)),
        silhouette=_portable_graymap(width, height, bytes(silhouette)),
        object_id=_portable_graymap(width, height, bytes(object_id)),
        semantic_masks={
            semantic_id: _portable_graymap(width, height, bytes(mask))
            for semantic_id, mask in semantic_masks.items()
        },
    )


def _artifact(
    *,
    output_root: Path,
    relative_path: str,
    role: str,
    data: bytes,
    stage_id: str | None = None,
    semantic_id: str | None = None,
) -> BenchmarkArtifactV02:
    """Persist and hash one report-relative deterministic evidence artifact."""

    path = output_root / Path(relative_path)
    _write_immutable(path, data)
    return BenchmarkArtifactV02(
        role=role,
        path=relative_path,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        stage_id=stage_id,
        semantic_id=semantic_id,
    )


def _semantic_filename(semantic_id: str) -> str:
    """Map a validated stable semantic ID to one collision-resistant file stem."""

    return semantic_id.replace(".", "__").replace("-", "_")


def _persist_raster_set(
    *,
    output_root: Path,
    case: BenchmarkCaseV02,
    raster: _RasterSet,
    stage: BenchmarkStagePlanV02 | None,
) -> list[BenchmarkArtifactV02]:
    """Persist one complete reference or stage raster set with exact hashes."""

    label = "reference" if stage is None else f"stages/{stage.stage_id}"
    prefix = f"artifacts/{case.case_id}/{label}"
    stage_id = None if stage is None else stage.stage_id
    artifacts = [
        _artifact(
            output_root=output_root,
            relative_path=f"{prefix}/beauty.ppm",
            role="reference.beauty" if stage is None else "candidate.beauty",
            data=raster.beauty,
            stage_id=stage_id,
        ),
        _artifact(
            output_root=output_root,
            relative_path=f"{prefix}/silhouette.pgm",
            role="reference.silhouette" if stage is None else "candidate.silhouette",
            data=raster.silhouette,
            stage_id=stage_id,
        ),
        _artifact(
            output_root=output_root,
            relative_path=f"{prefix}/object_id.pgm",
            role="reference.object_id" if stage is None else "candidate.object_id",
            data=raster.object_id,
            stage_id=stage_id,
        ),
    ]
    for semantic_id, data in sorted(raster.semantic_masks.items()):
        artifacts.append(
            _artifact(
                output_root=output_root,
                relative_path=(
                    f"{prefix}/semantic_{_semantic_filename(semantic_id)}.pgm"
                ),
                role=(
                    "reference.semantic_mask"
                    if stage is None
                    else "candidate.semantic_mask"
                ),
                data=data,
                stage_id=stage_id,
                semantic_id=semantic_id,
            )
        )
    return artifacts


def _binary_iou(reference_path: Path, candidate_path: Path) -> float:
    """Compute exact foreground IoU from deterministic PGM payload bytes."""

    def pixels(path: Path) -> bytes:
        """Return binary PGM pixels after its fixed three-line header."""

        data = path.read_bytes()
        parts = data.split(b"\n", 3)
        if len(parts) != 4 or parts[0] != b"P5" or parts[2] != b"255":
            raise ValueError("benchmark mask is not a deterministic binary PGM")
        return parts[3]

    reference = pixels(reference_path)
    candidate = pixels(candidate_path)
    if len(reference) != len(candidate):
        raise ValueError("benchmark masks do not have equal pixel counts")
    intersection = sum(
        bool(left) and bool(right)
        for left, right in zip(reference, candidate, strict=True)
    )
    union = sum(
        bool(left) or bool(right)
        for left, right in zip(reference, candidate, strict=True)
    )
    return 1.0 if union == 0 else intersection / union


def _find_artifact(
    artifacts: list[BenchmarkArtifactV02],
    role: str,
    semantic_id: str | None = None,
) -> BenchmarkArtifactV02:
    """Select exactly one artifact by role and optional semantic identity."""

    matches = [
        item
        for item in artifacts
        if item.role == role and item.semantic_id == semantic_id
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one artifact for {role}/{semantic_id}")
    return matches[0]


def _measure_stage(
    *,
    output_root: Path,
    case: BenchmarkCaseV02,
    stage: BenchmarkStagePlanV02,
    camera_sha256: str,
    reference_artifacts: list[BenchmarkArtifactV02],
) -> BenchmarkStageResultV02:
    """Generate one candidate and evaluate actual IQ 0.2 contour and semantic metrics."""

    candidate_raster = _render_case_rasters(case, stage)
    candidate_artifacts = _persist_raster_set(
        output_root=output_root,
        case=case,
        raster=candidate_raster,
        stage=stage,
    )
    reference_silhouette = _find_artifact(reference_artifacts, "reference.silhouette")
    candidate_silhouette = _find_artifact(candidate_artifacts, "candidate.silhouette")
    contour_binding = ContourEvidenceBindingV02(
        evidence_id=f"{case.case_id}.reference.contour",
        origin="observed",
        authority="authoritative",
        artifact_path=reference_silhouette.path,
        artifact_sha256=reference_silhouette.sha256,
        camera_sha256=camera_sha256,
    )
    contour = compare_contours_v02(
        output_root / reference_silhouette.path,
        output_root / candidate_silhouette.path,
        reference_evidence=contour_binding,
        candidate_evidence_id=f"{case.case_id}.{stage.stage_id}.contour",
        candidate_artifact_sha256=candidate_silhouette.sha256,
        candidate_camera_sha256=camera_sha256,
        metric_id=f"{case.case_id}.{stage.stage_id}.contour_v02",
        boundary_tolerance_diagonal_fraction=0.015625,
    )
    if contour.status != "scored":
        raise ValueError("synthetic global contour unexpectedly became unscorable")
    semantic_scores: list[float] = []
    critical_scores: list[float] = []
    missing: list[str] = []
    registration_hash = canonical_json_sha256_v02(
        {
            "case_contract_sha256": case.contract_sha256,
            "camera_sha256": camera_sha256,
            "registration": "synthetic_observed_fixture_v02",
        }
    )
    for primitive in case.reference_recipe.primitives:
        reference = _find_artifact(
            reference_artifacts,
            "reference.semantic_mask",
            primitive.semantic_id,
        )
        candidate = _find_artifact(
            candidate_artifacts,
            "candidate.semantic_mask",
            primitive.semantic_id,
        )
        binding = SemanticEvidenceBindingV02(
            evidence_id=f"{case.case_id}.reference.{primitive.semantic_id}",
            semantic_id=primitive.semantic_id,
            origin="registered_observed",
            authority="authoritative",
            artifact_path=reference.path,
            artifact_sha256=reference.sha256,
            camera_sha256=camera_sha256,
            registration_receipt_sha256=registration_hash,
        )
        metric = compare_semantic_masks_v02(
            output_root / reference.path,
            output_root / candidate.path,
            reference_evidence=binding,
            candidate_evidence_id=(
                f"{case.case_id}.{stage.stage_id}.{primitive.semantic_id}"
            ),
            candidate_artifact_sha256=candidate.sha256,
            candidate_camera_sha256=camera_sha256,
            critical=primitive.critical,
            boundary_tolerance_diagonal_fraction=0.015625,
        )
        if metric.status != "scored" or metric.mask_iou is None:
            raise ValueError("synthetic semantic metric unexpectedly became unscorable")
        semantic_scores.append(metric.mask_iou)
        if primitive.critical:
            critical_scores.append(metric.mask_iou)
        if metric.missing_candidate:
            missing.append(primitive.semantic_id)
    if not critical_scores:
        raise ValueError("benchmark case must declare at least one critical semantic")
    silhouette_iou = _binary_iou(
        output_root / reference_silhouette.path,
        output_root / candidate_silhouette.path,
    )
    metrics = BenchmarkMetricSetV02(
        silhouette_iou=silhouette_iou,
        contour_boundary_f_score=contour.boundary_f_score,
        contour_chamfer_norm=contour.edge_distance_transform_chamfer_norm,
        mean_semantic_iou=sum(semantic_scores) / len(semantic_scores),
        minimum_critical_semantic_iou=min(critical_scores),
        missing_semantic_ids=sorted(missing),
    )
    fingerprint = canonical_json_sha256_v02(
        {
            "stage_plan": stage.model_dump(mode="json"),
            "artifact_hashes": [item.sha256 for item in candidate_artifacts],
            "metrics": metrics.model_dump(mode="json"),
        }
    )
    return BenchmarkStageResultV02(
        stage_id=stage.stage_id,
        stage_plan_sha256=canonical_json_sha256_v02(stage.model_dump(mode="json")),
        candidate_fingerprint_sha256=fingerprint,
        metrics=metrics,
        execution=stage.execution,
        artifacts=candidate_artifacts,
    )


def _metric_value(stage: BenchmarkStageResultV02, name: str) -> float:
    """Read one declared metric from a validated stage without dynamic code execution."""

    return float(getattr(stage.metrics, name))


def _evaluate_direction(
    expectation: MetricDirectionExpectationV02,
    stages: dict[str, BenchmarkStageResultV02],
) -> MetricDirectionResultV02:
    """Compare one exact stage pair against its declared metric movement."""

    start = _metric_value(stages[expectation.from_stage], expectation.metric)
    end = _metric_value(stages[expectation.to_stage], expectation.metric)
    delta = end - start
    epsilon = 1.0e-12
    minimum = expectation.minimum_absolute_delta
    if expectation.direction == "increase":
        matched = delta > epsilon and delta + epsilon >= minimum
    elif expectation.direction == "decrease":
        matched = delta < -epsilon and -delta + epsilon >= minimum
    elif expectation.direction == "nondecrease":
        matched = delta >= -epsilon and delta + epsilon >= minimum
    elif expectation.direction == "nonincrease":
        matched = delta <= epsilon and -delta + epsilon >= minimum
    else:
        matched = abs(delta) <= epsilon and minimum == 0
    return MetricDirectionResultV02(
        metric=expectation.metric,
        from_stage=expectation.from_stage,
        to_stage=expectation.to_stage,
        expected_direction=expectation.direction,
        minimum_absolute_delta=minimum,
        from_value=start,
        to_value=end,
        observed_delta=delta,
        matched=matched,
    )


def _run_blender_case_v02(
    *,
    output_root: Path,
    case: BenchmarkCaseV02,
    camera_sha256: str,
) -> BlenderBenchmarkReceiptV02:
    """Run only the fixed repository Blender probe for one explicitly eligible case."""

    prefix = Path("artifacts") / case.case_id / "blender"
    contract_relative = (prefix / "case_contract.json").as_posix()
    blend_relative = (prefix / "probe.blend").as_posix()
    render_relative = (prefix / "probe.png").as_posix()
    receipt_relative = (prefix / "receipt.json").as_posix()
    contract_path = output_root / contract_relative
    _write_json_immutable(contract_path, case.model_dump(mode="json"))
    contract_file_sha256 = _file_sha256(contract_path)
    run_blender(
        "probe_autonomous_quality_v02.py",
        [
            "--output-root",
            str(output_root),
            "--case-contract",
            contract_relative,
            "--case-contract-file-sha256",
            contract_file_sha256,
            "--blend-output",
            blend_relative,
            "--render-output",
            render_relative,
            "--receipt-output",
            receipt_relative,
            "--camera-sha256",
            camera_sha256,
        ],
        factory_startup=True,
        disable_autoexec=True,
    )
    receipt_path = output_root / receipt_relative
    receipt = BlenderBenchmarkReceiptV02.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    if receipt.case_id != case.case_id:
        raise ValueError("Blender receipt case ID does not match its request")
    if receipt.case_contract_file_sha256 != contract_file_sha256:
        raise ValueError("Blender receipt case hash does not match exact input bytes")
    if receipt.camera_sha256 != camera_sha256:
        raise ValueError("Blender receipt camera hash does not match its case")
    if receipt.blend_sha256 != _file_sha256(output_root / receipt.blend_path):
        raise ValueError("Blender receipt blend SHA-256 is stale")
    if receipt.render_sha256 != _file_sha256(output_root / receipt.render_path):
        raise ValueError("Blender receipt render SHA-256 is stale")
    return receipt


def _evaluate_case(
    *,
    output_root: Path,
    case: BenchmarkCaseV02,
    run_blender_smoke: bool,
) -> BenchmarkCaseResultV02:
    """Run one exact case and preserve optional Blender failure as machine evidence."""

    if benchmark_case_contract_sha256_v02(case.model_dump(mode="json")) != case.contract_sha256:
        raise ValueError("benchmark case became stale after manifest validation")
    camera_sha256 = canonical_json_sha256_v02(case.known_camera.model_dump(mode="json"))
    camera_relative = f"artifacts/{case.case_id}/reference/known_camera.json"
    _write_json_immutable(
        output_root / camera_relative,
        case.known_camera.model_dump(mode="json"),
    )
    reference_raster = _render_case_rasters(case, None)
    reference_artifacts = _persist_raster_set(
        output_root=output_root,
        case=case,
        raster=reference_raster,
        stage=None,
    )
    reference_artifacts.insert(
        0,
        BenchmarkArtifactV02(
            role="reference.known_camera",
            path=camera_relative,
            sha256=_file_sha256(output_root / camera_relative),
            byte_size=(output_root / camera_relative).stat().st_size,
        ),
    )
    stage_results = [
        _measure_stage(
            output_root=output_root,
            case=case,
            stage=stage,
            camera_sha256=camera_sha256,
            reference_artifacts=reference_artifacts,
        )
        for stage in case.stages
    ]
    stages_by_id = {item.stage_id: item for item in stage_results}
    direction_results = [
        _evaluate_direction(expectation, stages_by_id)
        for expectation in case.expected_metric_directions
    ]
    blender_status = "not_applicable"
    blender_receipt = None
    error = None
    if case.blender_smoke_supported:
        blender_status = "not_requested"
        if run_blender_smoke:
            try:
                blender_receipt = _run_blender_case_v02(
                    output_root=output_root,
                    case=case,
                    camera_sha256=camera_sha256,
                )
                blender_status = "passed"
            except Exception as exc:  # noqa: BLE001 - preserve bounded probe failure evidence
                blender_status = "failed"
                error = f"{type(exc).__name__}: {exc}"
    reference_fingerprint = canonical_json_sha256_v02(
        {
            "case_contract_sha256": case.contract_sha256,
            "camera_sha256": camera_sha256,
            "artifacts": [item.model_dump(mode="json") for item in reference_artifacts],
        }
    )
    ok = all(item.matched for item in direction_results) and blender_status != "failed"
    return BenchmarkCaseResultV02(
        case_id=case.case_id,
        category=case.category,
        case_contract_sha256=case.contract_sha256,
        known_camera_sha256=camera_sha256,
        reference_fingerprint_sha256=reference_fingerprint,
        reference_artifacts=reference_artifacts,
        stage_results=stage_results,
        metric_direction_results=direction_results,
        blender_status=blender_status,
        blender_receipt=blender_receipt,
        error=error,
        human_review_status="not_reviewed",
        ok=ok,
    )


def _manifest_report_path(path: Path) -> str:
    """Return a privacy-safe relative manifest label for the machine report."""

    if not path.is_absolute():
        value = path.as_posix()
        if value and not value.startswith("../") and "/../" not in value:
            return value.removeprefix("./")
    return f"inputs/{path.name}"


def run_benchmark_manifest_v02(
    manifest_path: Path,
    output_path: Path,
    *,
    run_blender_smoke: bool = False,
) -> BenchmarkReportV02:
    """Execute the strict host benchmark and optionally its fixed Blender smoke script."""

    manifest_bytes = manifest_path.read_bytes()
    manifest = BenchmarkManifestV02.model_validate_json(manifest_bytes)
    report_path = _safe_output_path(output_path)
    output_root = report_path.parent
    results = [
        _evaluate_case(
            output_root=output_root,
            case=case,
            run_blender_smoke=run_blender_smoke,
        )
        for case in manifest.cases
    ]
    passed = sum(item.ok for item in results)
    report = BenchmarkReportV02(
        benchmark_id=manifest.benchmark_id,
        manifest_path=_manifest_report_path(manifest_path),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        blender_requested=run_blender_smoke,
        blender_executed_case_count=sum(
            item.blender_status in {"passed", "failed"} for item in results
        ),
        case_results=results,
        passed_case_count=passed,
        failed_case_count=len(results) - passed,
        ok=passed == len(results),
        limitations=[
            *manifest.limitations,
            (
                "The duration fields are deterministic fixture-model values, not measured "
                "wall-clock performance."
            ),
            (
                "Package and round-trip fields remain not_run unless a future separately "
                "authorized benchmark actually produces and imports a portable package."
            ),
            (
                "human_review_status=not_reviewed: metric direction success is not human "
                "approval, production quality, or destination-runtime parity."
            ),
        ],
    )
    _write_json_immutable(report_path, report.model_dump(mode="json"))
    return report
