"""Deterministic companion assembly evaluation without canonical scene mutation."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Literal

from .models import (
    AABB,
    AssemblyArtifact,
    AssemblyCompanionReport,
    AssemblyCompanionRequest,
    AssemblyFinding,
    BroadPhasePair,
    BVHNarrowObservation,
    SemanticAssemblyRelation,
    TriangleMeshEvidence,
    Vec3,
)

FindingSeverity = Literal["hard_failure", "warning", "info", "unscorable"]


def _subtract(left: Vec3, right: Vec3) -> Vec3:
    """Subtract two 3D vectors."""

    return tuple(a - b for a, b in zip(left, right, strict=True))  # type: ignore[return-value]


def _dot(left: Vec3, right: Vec3) -> float:
    """Return the scalar dot product of two 3D vectors."""

    return sum(a * b for a, b in zip(left, right, strict=True))


def _squared_distance(left: Vec3, right: Vec3) -> float:
    """Return squared Euclidean distance between two 3D points."""

    delta = _subtract(left, right)
    return _dot(delta, delta)


def _point_triangle_distance(point: Vec3, a: Vec3, b: Vec3, c: Vec3) -> float:
    """Compute exact point-to-triangle distance using Voronoi regions."""

    ab = _subtract(b, a)
    ac = _subtract(c, a)
    ap = _subtract(point, a)
    d1 = _dot(ab, ap)
    d2 = _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return math.sqrt(_squared_distance(point, a))
    bp = _subtract(point, b)
    d3 = _dot(ab, bp)
    d4 = _dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return math.sqrt(_squared_distance(point, b))
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        factor = d1 / (d1 - d3)
        projection = tuple(a[i] + factor * ab[i] for i in range(3))
        return math.sqrt(_squared_distance(point, projection))
    cp = _subtract(point, c)
    d5 = _dot(ab, cp)
    d6 = _dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return math.sqrt(_squared_distance(point, c))
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        factor = d2 / (d2 - d6)
        projection = tuple(a[i] + factor * ac[i] for i in range(3))
        return math.sqrt(_squared_distance(point, projection))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        edge = _subtract(c, b)
        factor = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        projection = tuple(b[i] + factor * edge[i] for i in range(3))
        return math.sqrt(_squared_distance(point, projection))
    denominator = 1.0 / (va + vb + vc)
    v = vb * denominator
    w = vc * denominator
    projection = tuple(a[i] + ab[i] * v + ac[i] * w for i in range(3))
    return math.sqrt(_squared_distance(point, projection))


def _sample_indices(count: int, limit: int) -> list[int]:
    """Select stable, evenly distributed indices within a strict sample limit."""

    if count <= limit:
        return list(range(count))
    return sorted({min(count - 1, (index * count) // limit) for index in range(limit)})


def _directed_mesh_distance(
    source: TriangleMeshEvidence,
    target: TriangleMeshEvidence,
    limit: int,
) -> tuple[float, int]:
    """Measure sampled source vertices against every target triangle."""

    target_triangles = [
        tuple(target.vertices_m[index] for index in triangle)
        for triangle in target.triangles
    ]
    minimum = math.inf
    indices = _sample_indices(len(source.vertices_m), limit)
    for index in indices:
        point = source.vertices_m[index]
        for a, b, c in target_triangles:
            minimum = min(minimum, _point_triangle_distance(point, a, b, c))
    return minimum, len(indices)


def bounded_nearest_distance(
    first: TriangleMeshEvidence,
    second: TriangleMeshEvidence,
    maximum_samples: int = 512,
) -> tuple[float | None, int]:
    """Return a symmetric bounded vertex-to-triangle nearest-distance estimate."""

    if not first.vertices_m or not first.triangles or not second.vertices_m or not second.triangles:
        return None, 0
    per_direction = max(1, maximum_samples // 2)
    forward, forward_count = _directed_mesh_distance(first, second, per_direction)
    reverse, reverse_count = _directed_mesh_distance(second, first, per_direction)
    return min(forward, reverse), forward_count + reverse_count


def _axis_gap(first: AABB, second: AABB) -> Vec3:
    """Return nonnegative separation on each AABB axis."""

    return tuple(
        max(
            0.0,
            second.minimum[index] - first.maximum[index],
            first.minimum[index] - second.maximum[index],
        )
        for index in range(3)
    )  # type: ignore[return-value]


def _overlap_extent(first: AABB, second: AABB) -> Vec3:
    """Return nonnegative overlap extent on each AABB axis."""

    return tuple(
        max(
            0.0,
            min(first.maximum[index], second.maximum[index])
            - max(first.minimum[index], second.minimum[index]),
        )
        for index in range(3)
    )  # type: ignore[return-value]


def build_broad_phase_pairs(meshes: Iterable[TriangleMeshEvidence]) -> list[BroadPhasePair]:
    """Build deterministic unordered semantic AABB pair evidence."""

    ordered = sorted(meshes, key=lambda item: item.object_id)
    pairs: list[BroadPhasePair] = []
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            overlap = _overlap_extent(first.bounds, second.bounds)
            gap = _axis_gap(first.bounds, second.bounds)
            pairs.append(
                BroadPhasePair(
                    subject_id=first.object_id,
                    reference_id=second.object_id,
                    status=(
                        "overlap_candidate"
                        if all(value == 0 for value in gap)
                        else "separated"
                    ),
                    axis_gap_m=gap,
                    overlap_extent_m=overlap,
                )
            )
    return pairs


def _triangle_bounds(mesh: TriangleMeshEvidence, triangle: tuple[int, int, int]) -> AABB:
    """Return one triangle's positive-epsilon AABB for bounded overlap candidates."""

    vertices = [mesh.vertices_m[index] for index in triangle]
    minimum = tuple(min(vertex[axis] for vertex in vertices) for axis in range(3))
    maximum_raw = tuple(max(vertex[axis] for vertex in vertices) for axis in range(3))
    maximum = tuple(max(maximum_raw[axis], minimum[axis] + 1.0e-12) for axis in range(3))
    return AABB(minimum=minimum, maximum=maximum)


def _bounded_triangle_overlap_candidates(
    first: TriangleMeshEvidence,
    second: TriangleMeshEvidence,
    maximum_tests: int,
) -> int:
    """Count bounded triangle-AABB overlap candidates without claiming penetration."""

    count = 0
    tests = 0
    for first_triangle in first.triangles:
        first_bounds = _triangle_bounds(first, first_triangle)
        for second_triangle in second.triangles:
            if tests >= maximum_tests:
                return count
            tests += 1
            overlap = _overlap_extent(first_bounds, _triangle_bounds(second, second_triangle))
            if all(value > 0 for value in overlap):
                count += 1
    return count


def build_pure_python_observation(
    first: TriangleMeshEvidence,
    second: TriangleMeshEvidence,
    *,
    maximum_samples: int = 512,
    maximum_triangle_pair_tests: int = 4096,
) -> BVHNarrowObservation:
    """Create bounded fallback evidence while leaving penetration explicitly unavailable."""

    distance, sample_count = bounded_nearest_distance(first, second, maximum_samples)
    if distance is None:
        return BVHNarrowObservation(
            subject_id=first.object_id,
            reference_id=second.object_id,
            status="empty",
            backend="pure_python_bounded",
            bounded_sample_limit=maximum_samples,
        )
    return BVHNarrowObservation(
        subject_id=first.object_id,
        reference_id=second.object_id,
        status="available",
        backend="pure_python_bounded",
        overlap_triangle_pair_count=_bounded_triangle_overlap_candidates(
            first, second, maximum_triangle_pair_tests
        ),
        minimum_distance_m=distance,
        penetration_depth_m=None,
        sampled_point_count=sample_count,
        bounded_sample_limit=maximum_samples,
    )


def _relation_result(
    relation: SemanticAssemblyRelation,
    observation: BVHNarrowObservation | None,
) -> tuple[FindingSeverity, float | None, float | None, str]:
    """Evaluate one semantic relation from supported narrow or explicit measurements."""

    if relation.kind == "required_contact":
        if observation is None or observation.status != "available":
            return "unscorable", None, relation.maximum_m, "contact distance is unavailable"
        value = observation.minimum_distance_m
        assert value is not None
        passed = value <= float(relation.maximum_m) + relation.tolerance_m
        return (
            "info" if passed else ("hard_failure" if relation.required else "warning"),
            value,
            relation.maximum_m,
            (
                "required contact distance is within tolerance"
                if passed
                else "required contact distance exceeds tolerance"
            ),
        )
    if relation.kind == "supported_clearance":
        if observation is None or observation.status != "available":
            return "unscorable", None, relation.minimum_m, "clearance distance is unavailable"
        value = observation.minimum_distance_m
    else:
        value = relation.measured_value_m
        if value is None:
            return "unscorable", None, relation.maximum_m, "semantic measurement is unavailable"
    lower = relation.minimum_m if relation.minimum_m is not None else 0.0
    upper = relation.maximum_m if relation.maximum_m is not None else math.inf
    passed = lower - relation.tolerance_m <= value <= upper + relation.tolerance_m
    return (
        "info" if passed else ("hard_failure" if relation.required else "warning"),
        value,
        upper if math.isfinite(upper) else lower,
        (
            "semantic assembly relation is within tolerance"
            if passed
            else "semantic assembly relation is outside tolerance"
        ),
    )


def build_assembly_companion_report(
    request: AssemblyCompanionRequest,
    *,
    request_path: str,
    request_sha256: str,
    report_id: str,
) -> AssemblyCompanionReport:
    """Build one conservative broad/narrow/semantic companion report."""

    meshes = {item.object_id: item for item in request.meshes}
    broad_pairs = build_broad_phase_pairs(request.meshes)
    supplied = {
        tuple(sorted((item.subject_id, item.reference_id))): item
        for item in request.narrow_observations
    }
    required_pairs = {
        tuple(sorted((item.subject_id, item.reference_id)))
        for item in request.semantic_relations
    }
    observations: list[BVHNarrowObservation] = []
    for first_id, second_id in sorted(required_pairs):
        observation = supplied.get((first_id, second_id))
        if observation is None:
            observation = build_pure_python_observation(
                meshes[first_id],
                meshes[second_id],
                maximum_samples=request.maximum_distance_samples,
                maximum_triangle_pair_tests=request.maximum_triangle_pair_tests,
            )
        observations.append(observation)
    observation_map = {
        tuple(sorted((item.subject_id, item.reference_id))): item
        for item in observations
    }
    findings: list[AssemblyFinding] = []
    for pair in broad_pairs:
        findings.append(
            AssemblyFinding(
                finding_id=f"broad.{pair.subject_id}.{pair.reference_id}",
                phase="broad",
                severity="info",
                code=(
                    "AABB_OVERLAP_CANDIDATE"
                    if pair.status == "overlap_candidate"
                    else "AABB_SEPARATED"
                ),
                subject_id=pair.subject_id,
                reference_id=pair.reference_id,
                message=(
                    "AABB overlap is broad-phase evidence only."
                    if pair.status == "overlap_candidate"
                    else "AABBs are separated on at least one axis."
                ),
            )
        )
    for observation in observations:
        if observation.status != "available":
            findings.append(
                AssemblyFinding(
                    finding_id=f"narrow.{observation.subject_id}.{observation.reference_id}",
                    phase="narrow",
                    severity="unscorable",
                    code="NARROW_PHASE_UNAVAILABLE",
                    subject_id=observation.subject_id,
                    reference_id=observation.reference_id,
                    message=observation.error or "evaluated mesh evidence is empty",
                )
            )
        elif observation.penetration_depth_m is not None and observation.penetration_depth_m > 0:
            findings.append(
                AssemblyFinding(
                    finding_id=f"narrow.{observation.subject_id}.{observation.reference_id}.penetration",
                    phase="narrow",
                    severity="hard_failure",
                    code="MESH_PENETRATION",
                    subject_id=observation.subject_id,
                    reference_id=observation.reference_id,
                    measured_value_m=observation.penetration_depth_m,
                    limit_value_m=0.0,
                    message="Evaluated BVH evidence reports positive penetration depth.",
                )
            )
        elif observation.overlap_triangle_pair_count:
            findings.append(
                AssemblyFinding(
                    finding_id=f"narrow.{observation.subject_id}.{observation.reference_id}.overlap",
                    phase="narrow",
                    severity="warning",
                    code="TRIANGLE_OVERLAP_CANDIDATE",
                    subject_id=observation.subject_id,
                    reference_id=observation.reference_id,
                    measured_value_m=observation.minimum_distance_m,
                    message=(
                        "Triangle overlap candidates need signed Blender BVH evidence before "
                        "they can be classified as penetration."
                    ),
                )
            )
    for relation in request.semantic_relations:
        key = tuple(sorted((relation.subject_id, relation.reference_id)))
        severity, measured, limit, message = _relation_result(
            relation, observation_map.get(key)
        )
        findings.append(
            AssemblyFinding(
                finding_id=f"semantic.{relation.relation_id}",
                phase="semantic",
                severity=severity,
                code=f"SEMANTIC_{relation.kind.upper()}",
                subject_id=relation.subject_id,
                reference_id=relation.reference_id,
                relation_id=relation.relation_id,
                measured_value_m=measured,
                limit_value_m=limit,
                message=message,
            )
        )
    hard_failures = sum(item.severity == "hard_failure" for item in findings)
    warnings = sum(item.severity == "warning" for item in findings)
    unscorable = sum(item.severity == "unscorable" for item in findings)
    status = (
        "failed"
        if hard_failures
        else "unscorable"
        if unscorable
        else "warning"
        if warnings
        else "passed"
    )
    return AssemblyCompanionReport(
        report_id=report_id,
        provenance=request.provenance,
        request=AssemblyArtifact(
            role="assembly_request", path=request_path, sha256=request_sha256
        ),
        status=status,
        ok=status == "passed",
        broad_pairs=broad_pairs,
        narrow_observations=observations,
        findings=findings,
        hard_failures=hard_failures,
        warnings=warnings,
        unscorable=unscorable,
        limitations=[
            (
                "AABB and bounded nearest-distance evidence does not prove mechanism "
                "operation, manufacturability, or hidden structure truth."
            ),
            "Pure-Python triangle AABB overlaps are candidates, not signed penetration proof.",
        ],
    )
