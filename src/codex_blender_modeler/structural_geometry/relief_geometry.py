"""Deterministic host helpers for bounded camera-facing relief geometry."""

from __future__ import annotations

from collections.abc import Sequence

from .models import LoftGeometry, LoftSection


def _signed_area(points: Sequence[tuple[float, float]]) -> float:
    """Return the signed X/Z area used to normalize section winding."""

    return 0.5 * sum(
        x_a * z_b - x_b * z_a
        for (x_a, z_a), (x_b, z_b) in zip(
            points,
            (*points[1:], points[0]),
            strict=True,
        )
    )


def _counter_clockwise_loop(
    points: Sequence[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Copy one non-degenerate camera-plane loop into counter-clockwise order."""

    copied = [(float(x), float(z)) for x, z in points]
    if len(copied) < 3:
        raise ValueError("beveled relief requires at least three loop points")
    area = _signed_area(copied)
    if area == 0:
        raise ValueError("beveled relief loop area must be non-zero")
    return copied if area > 0 else list(reversed(copied))


def build_beveled_relief_loft(
    points: Sequence[tuple[float, float]],
    *,
    depth: float,
    bevel_depth: float,
    edge_inset_ratio: float,
) -> LoftGeometry:
    """Build a four-section Y-axis loft with exact outer projection and inset side walls."""

    if depth <= 0:
        raise ValueError("beveled relief depth must be positive")
    if bevel_depth <= 0 or 2.0 * bevel_depth >= depth:
        raise ValueError("bevel depth must be positive and less than half the relief depth")
    if not 0 < edge_inset_ratio < 0.5:
        raise ValueError("edge inset ratio must be between zero and one half")
    outer = _counter_clockwise_loop(points)
    center_x = sum(point[0] for point in outer) / len(outer)
    center_z = sum(point[1] for point in outer) / len(outer)
    scale = 1.0 - edge_inset_ratio
    inset = [
        (
            center_x + (x - center_x) * scale,
            center_z + (z - center_z) * scale,
        )
        for x, z in outer
    ]
    half_depth = depth / 2.0

    def _section(loop: Sequence[tuple[float, float]], y: float) -> LoftSection:
        """Lift one camera-plane loop onto a constant local-Y section."""

        return LoftSection(
            points=[(x, y, z) for x, z in loop],
            closed=True,
        )

    return LoftGeometry(
        sections=[
            _section(outer, -half_depth),
            _section(inset, -half_depth + bevel_depth),
            _section(inset, half_depth - bevel_depth),
            _section(outer, half_depth),
        ],
        resample_count=len(outer),
        cap_policy="ends",
        correspondence_policy="index",
        twist_offsets=[],
    )
