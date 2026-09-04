"""Additive, exact-bound GLB corner comparisons without changing legacy snapshot meaning."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..blender_artifacts import native_io_path, sha256_file
from ..production.validation import ensure_contained_production_path
from .geometry_survival_v02 import (
    GeometryIntentSurvivalReportV02,
    GeometryStageSnapshotV02,
    GeometrySurvivalCheckV02,
    _aggregate_status,
    compare_geometry_stage_snapshots_v02,
)
from .mesh_payload_v02 import (
    JobRelativePath,
    MeshPayloadV02StrictModel,
    Sha256,
    canonical_json_sha256,
)

# These fixed bounds are narrower than the legacy fingerprint cells. They are
# not caller-selectable and never apply to topology, materials, or authoring.
POSITION_COMPONENT_LIMIT_M = 0.000001
UV_COMPONENT_LIMIT = 0.0000001
NORMAL_COMPONENT_LIMIT = 0.005
NORMAL_ANGLE_LIMIT_DEGREES = 0.5


class DeliveryCornerV02(MeshPayloadV02StrictModel):
    """Bind full finite world position, UV and unit normal to the same triangle corner."""

    position: tuple[float, float, float]
    uv: tuple[float, float]
    normal: tuple[float, float, float]

    @model_validator(mode="after")
    def validate_normal(self) -> DeliveryCornerV02:
        """Reject invalid vectors rather than normalizing malformed recorded evidence."""

        length_squared = sum(value * value for value in self.normal)
        if abs(length_squared - 1.0) > 0.00001:
            raise ValueError("delivery corner normal must already be a unit vector")
        return self


class DeliveryTriangleV02(MeshPayloadV02StrictModel):
    """Retain a complete face-corner association under one stable object-instance ID."""

    semantic_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}(#[0-9]+)?$")
    corners: tuple[DeliveryCornerV02, DeliveryCornerV02, DeliveryCornerV02]


class GeometryDeliveryCornerEvidenceV02(MeshPayloadV02StrictModel):
    """Capture raw values beside the unchanged exact legacy stage snapshot."""

    schema_version: Literal["0.1.0"]
    kind: Literal["geometry_delivery_corner_evidence"] = "geometry_delivery_corner_evidence"
    blender_version: Literal["5.0.1"]
    snapshot: GeometryStageSnapshotV02
    triangles: list[DeliveryTriangleV02] = Field(min_length=1, max_length=1_000_000)

    @model_validator(mode="after")
    def validate_snapshot_projection(self) -> GeometryDeliveryCornerEvidenceV02:
        """Recompute legacy channel hashes from raw records before allowing comparison."""

        if self.snapshot.stage not in {"optimized_lod0", "clean_import_glb"}:
            raise ValueError("numerical corner evidence is limited to optimized GLB delivery")
        if len(self.triangles) != self.snapshot.evaluated_triangle_count:
            raise ValueError("corner evidence omitted or duplicated snapshot triangles")
        observed = corner_fingerprints(self.triangles)
        for name, fingerprint in (
            ("surface", self.snapshot.surface_equivalence_fingerprint),
            ("uv", self.snapshot.uv_fingerprint),
            ("normals", self.snapshot.split_normal_fingerprint),
        ):
            if fingerprint.status != "available" or observed[name] != fingerprint.sha256:
                raise ValueError(f"raw corner evidence does not reproduce snapshot {name}")
        return self


class GeometryCornerArtifactV02(MeshPayloadV02StrictModel):
    """Bind one immutable, contained raw-corner evidence file."""

    path: JobRelativePath
    sha256: Sha256
    byte_size: int = Field(gt=0)


class GeometryCornerComparisonV02(MeshPayloadV02StrictModel):
    """Record measured errors without accepting caller-defined tolerances."""

    policy_id: Literal["glb_corner_precision_v1"] = "glb_corner_precision_v1"
    triangle_count: int = Field(gt=0)
    corner_count: int = Field(gt=0)
    ambiguous_triangle_count: Literal[0] = 0
    maximum_position_component_error_m: float = Field(ge=0)
    maximum_uv_component_error: float = Field(ge=0)
    maximum_normal_component_error: float = Field(ge=0)
    maximum_normal_angle_degrees: float = Field(ge=0, le=180)

    @model_validator(mode="after")
    def validate_corner_count(self) -> GeometryCornerComparisonV02:
        """Require every triangle corner, never a sampled or averaged comparison."""

        if self.corner_count != 3 * self.triangle_count:
            raise ValueError("numerical comparison must cover every triangle corner")
        return self


class GeometryNumericalSurvivalReportV02(GeometryIntentSurvivalReportV02):
    """Add a versioned numerical proof while preserving the original exact comparison."""

    schema_version: Literal["0.2.0"] = Field(...)
    exact_snapshot_comparison: GeometryIntentSurvivalReportV02
    source_corner_evidence: GeometryCornerArtifactV02
    target_corner_evidence: GeometryCornerArtifactV02
    numerical_comparison: GeometryCornerComparisonV02

    @model_validator(mode="after")
    def validate_refinement(self) -> GeometryNumericalSurvivalReportV02:
        """Reject reclassification of unrelated gates or unbound comparison fields."""

        original = self.exact_snapshot_comparison
        if not needs_numerical_comparison(original):
            raise ValueError("numerical proof may refine only GLB UV/split-normal cell failures")
        for field in (
            "report_id",
            "relation",
            "source_stage",
            "source_snapshot_sha256",
            "target_stage",
            "target_snapshot_sha256",
            "package_format",
            "integration_authority",
            "v1_path_mutated",
        ):
            if getattr(self, field) != getattr(original, field):
                raise ValueError("numerical proof changed its exact snapshot binding")
        if self.source_corner_evidence.path == self.target_corner_evidence.path:
            raise ValueError("source and target corner evidence must be independent")
        if self.checks != refined_checks(original, self.numerical_comparison):
            raise ValueError("numerical survival checks do not follow the fixed policy")
        return self


def _sort_key(value: object) -> str:
    """Use the exact legacy JSON record ordering for reproducible fingerprints."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _quantize(values: tuple[float, ...], quantum: float, decimals: int) -> list[float]:
    """Reproduce legacy cells only to bind raw data, never to decide numerical closeness."""

    return [round(round(value / quantum) * quantum, decimals) or 0.0 for value in values]


def corner_fingerprints(triangles: list[DeliveryTriangleV02]) -> dict[str, str]:
    """Recreate the unchanged legacy surface, UV and split-normal channel fingerprints."""

    surface: list[object] = []
    uv: list[object] = []
    normals: list[object] = []
    for triangle in triangles:
        positions = []
        for corner in triangle.corners:
            position = _quantize(corner.position, 0.000002, 6)
            positions.append(position)
            uv.append(
                {
                    "semantic_id": triangle.semantic_id,
                    "position": position,
                    "uv": _quantize(corner.uv, 0.00002, 5),
                }
            )
            normals.append(
                {
                    "semantic_id": triangle.semantic_id,
                    "position": position,
                    "normal": _quantize(corner.normal, 0.01, 2),
                }
            )
        surface.append({"semantic_id": triangle.semantic_id, "positions": sorted(positions)})
    return {
        name: canonical_json_sha256(sorted(records, key=_sort_key))
        for name, records in (("surface", surface), ("uv", uv), ("normals", normals))
    }


def needs_numerical_comparison(report: GeometryIntentSurvivalReportV02) -> bool:
    """Select only exact GLB deliveries whose UV/normal cells are the sole hard failures."""

    failures = {item.check_id for item in report.checks if item.status == "failed"}
    return (
        report.schema_version == "0.1.0"
        and report.relation == "optimized_to_clean_import"
        and report.package_format == "GLB"
        and report.source_stage == "optimized_lod0"
        and report.target_stage == "clean_import_glb"
        and bool(failures)
        and failures <= {"uv_layout", "split_normals"}
        and all(item.status != "unscorable" for item in report.checks)
    )


def _triangle_index(
    evidence: GeometryDeliveryCornerEvidenceV02,
) -> dict[tuple, tuple[list[DeliveryCornerV02], tuple[float, ...]]]:
    """Reject ambiguous/degenerate faces and retain corner correspondence plus original winding."""

    result = {}
    for triangle in evidence.triangles:
        ordered = sorted(
            triangle.corners,
            key=lambda item: _quantize(item.position, 0.000002, 6),
        )
        positions = tuple(tuple(_quantize(item.position, 0.000002, 6)) for item in ordered)
        key = (triangle.semantic_id, positions)
        if len(set(positions)) != 3 or key in result:
            raise ValueError(
                "corner correspondence is ambiguous; numerical equivalence is unavailable"
            )
        first = triangle.corners[0].position
        second = tuple(b - a for a, b in zip(first, triangle.corners[1].position, strict=True))
        third = tuple(b - a for a, b in zip(first, triangle.corners[2].position, strict=True))
        area = (
            second[1] * third[2] - second[2] * third[1],
            second[2] * third[0] - second[0] * third[2],
            second[0] * third[1] - second[1] * third[0],
        )
        length = math.hypot(*area)
        if length == 0.0 or not math.isfinite(length):
            raise ValueError("corner evidence contains a degenerate triangle")
        result[key] = (ordered, tuple(value / length for value in area))
    return result


def compare_corner_evidence(
    source: GeometryDeliveryCornerEvidenceV02,
    target: GeometryDeliveryCornerEvidenceV02,
) -> GeometryCornerComparisonV02:
    """Measure every uniquely corresponding corner with strict joint UV/normal association."""

    if source.snapshot.stage != "optimized_lod0" or target.snapshot.stage != "clean_import_glb":
        raise ValueError("numerical comparison is limited to optimized-to-GLB delivery")
    for field in ("source_fingerprint_sha256", "build_fingerprint_sha256", "topology_profile"):
        if getattr(source.snapshot, field) != getattr(target.snapshot, field):
            raise ValueError("corner comparison belongs to different source/build bindings")
    left = _triangle_index(source)
    right = _triangle_index(target)
    if left.keys() != right.keys():
        raise ValueError("numerical comparison cannot replace missing or changed surface triangles")
    position_error = uv_error = normal_error = angle_error = 0.0
    for key in sorted(left):
        left_corners, left_winding = left[key]
        right_corners, right_winding = right[key]
        if sum(a * b for a, b in zip(left_winding, right_winding, strict=True)) <= 0.0:
            raise ValueError("triangle winding reversed; numerical equivalence is unavailable")
        for first, second in zip(left_corners, right_corners, strict=True):
            position_error = max(
                position_error,
                *(abs(a - b) for a, b in zip(first.position, second.position, strict=True)),
            )
            uv_error = max(
                uv_error, *(abs(a - b) for a, b in zip(first.uv, second.uv, strict=True))
            )
            normal_error = max(
                normal_error,
                *(abs(a - b) for a, b in zip(first.normal, second.normal, strict=True)),
            )
            length_product = math.sqrt(
                sum(value * value for value in first.normal)
                * sum(value * value for value in second.normal)
            )
            cosine = (
                sum(a * b for a, b in zip(first.normal, second.normal, strict=True))
                / length_product
            )
            angle_error = max(angle_error, math.degrees(math.acos(min(1.0, max(-1.0, cosine)))))
    return GeometryCornerComparisonV02(
        triangle_count=len(left),
        corner_count=3 * len(left),
        maximum_position_component_error_m=position_error,
        maximum_uv_component_error=uv_error,
        maximum_normal_component_error=normal_error,
        maximum_normal_angle_degrees=angle_error,
    )


def refined_checks(
    original: GeometryIntentSurvivalReportV02,
    comparison: GeometryCornerComparisonV02,
) -> list[GeometrySurvivalCheckV02]:
    """Apply fixed, narrower bounds without changing any topology or material check."""

    position_ok = comparison.maximum_position_component_error_m <= POSITION_COMPONENT_LIMIT_M
    uv_ok = position_ok and comparison.maximum_uv_component_error <= UV_COMPONENT_LIMIT
    normal_ok = (
        position_ok
        and comparison.maximum_normal_component_error <= NORMAL_COMPONENT_LIMIT
        and comparison.maximum_normal_angle_degrees <= NORMAL_ANGLE_LIMIT_DEGREES
    )
    result = []
    for check in original.checks:
        if check.check_id not in {"uv_layout", "split_normals"}:
            result.append(check)
            continue
        accepted = uv_ok if check.check_id == "uv_layout" else normal_ok
        if check.status == "exact" and accepted:
            result.append(check)
            continue
        message = (
            f"{check.check_id} {'is equivalent' if accepted else 'failed'} under "
            "glb_corner_precision_v1: complete unique triangle-corner correspondence; "
            f"position component <= {POSITION_COMPONENT_LIMIT_M} m; "
            f"UV component <= {UV_COMPONENT_LIMIT}; normal component <= {NORMAL_COMPONENT_LIMIT} "
            f"and normal angle <= {NORMAL_ANGLE_LIMIT_DEGREES} degrees"
        )
        result.append(
            GeometrySurvivalCheckV02(
                check_id=check.check_id,
                status="equivalent" if accepted else "failed",
                source_sha256=check.source_sha256,
                target_sha256=check.target_sha256,
                message=message,
            )
        )
    return result


def build_numerical_survival_report(
    *,
    report_id: str,
    source: GeometryDeliveryCornerEvidenceV02,
    target: GeometryDeliveryCornerEvidenceV02,
    source_artifact: GeometryCornerArtifactV02,
    target_artifact: GeometryCornerArtifactV02,
) -> GeometryNumericalSurvivalReportV02:
    """Build an additive proof whose exact base comparison remains visible and unchanged."""

    original = compare_geometry_stage_snapshots_v02(
        report_id=report_id,
        relation="optimized_to_clean_import",
        source=source.snapshot,
        target=target.snapshot,
        package_format="GLB",
    )
    if not needs_numerical_comparison(original):
        raise ValueError("exact comparison is not eligible for bounded GLB numerical proof")
    comparison = compare_corner_evidence(source, target)
    checks = refined_checks(original, comparison)
    payload = original.model_dump(mode="python")
    payload.update(
        schema_version="0.2.0",
        exact_snapshot_comparison=original,
        source_corner_evidence=source_artifact,
        target_corner_evidence=target_artifact,
        numerical_comparison=comparison,
        checks=checks,
        overall_status=_aggregate_status([item.status for item in checks]),
        known_losses=[item.message for item in checks if item.status == "known_loss"],
    )
    return GeometryNumericalSurvivalReportV02.model_validate(payload)


def bind_corner_evidence(root: Path, path: Path) -> GeometryCornerArtifactV02:
    """Bind only a contained regular file after the host has published its raw records."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    native = native_io_path(safe)
    if not os.path.isfile(native):
        raise ValueError("corner evidence is not a regular file")
    return GeometryCornerArtifactV02(
        path=safe.relative_to(root).as_posix(),
        sha256=sha256_file(safe),
        byte_size=os.stat(native).st_size,
    )


def load_corner_evidence(
    root: Path,
    artifact: GeometryCornerArtifactV02,
) -> GeometryDeliveryCornerEvidenceV02:
    """Rehash raw records and their original source artifact before using the proof."""

    path = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
    if bind_corner_evidence(root, path) != artifact:
        raise ValueError("corner evidence file changed")
    with open(native_io_path(path), "rb") as stream:
        evidence = GeometryDeliveryCornerEvidenceV02.model_validate_json(stream.read())
    source = ensure_contained_production_path(
        root, root / evidence.snapshot.artifact_path, must_exist=True
    )
    if (
        not os.path.isfile(native_io_path(source))
        or sha256_file(source) != evidence.snapshot.artifact_sha256
    ):
        raise ValueError("corner evidence source artifact changed")
    return evidence


def validate_numerical_survival_report(
    root: Path,
    report: GeometryNumericalSurvivalReportV02,
) -> tuple[GeometryStageSnapshotV02, GeometryStageSnapshotV02]:
    """Recompute every numerical result from exact contained source and target records."""

    source = load_corner_evidence(root, report.source_corner_evidence)
    target = load_corner_evidence(root, report.target_corner_evidence)
    recomputed = build_numerical_survival_report(
        report_id=report.report_id,
        source=source,
        target=target,
        source_artifact=report.source_corner_evidence,
        target_artifact=report.target_corner_evidence,
    )
    if report != recomputed:
        raise ValueError("numerical survival proof differs from its exact raw corner evidence")
    return source.snapshot, target.snapshot


def load_delivery_survival_report(
    path: Path,
) -> GeometryIntentSurvivalReportV02 | GeometryNumericalSurvivalReportV02:
    """Dispatch exact report versions without migrating or weakening legacy evidence."""

    with open(native_io_path(path), "rb") as stream:
        raw = stream.read()
    payload = json.loads(raw)
    version = payload.get("schema_version") if isinstance(payload, dict) else None
    if version == "0.1.0":
        return GeometryIntentSurvivalReportV02.model_validate_json(raw)
    if version == "0.2.0":
        return GeometryNumericalSurvivalReportV02.model_validate_json(raw)
    raise ValueError("unknown geometry delivery survival report version")
