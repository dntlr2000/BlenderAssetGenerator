"""Bounded, data-only evaluation of explicitly authored radial height knots.

This is a piecewise cubic smoothstep profile with compact support, not a
Gaussian approximation. It performs no rasterization, mesh edits, or I/O.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from typing import TypeAlias

Knot: TypeAlias = tuple[float, float]
MAX_KNOTS = 128
MAX_RADIAL_SAMPLES = 4096
MAX_MAGNITUDE = 1.0e6


def _number(value: object, name: str) -> float:
    """Reject unknown types, booleans, nonfinite values and range overflow."""
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite built-in number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} exceeds the finite numeric envelope") from exc
    if not math.isfinite(result) or abs(result) > MAX_MAGNITUDE:
        raise ValueError(f"{name} must be finite and within +/-{MAX_MAGNITUDE}")
    return result


def validate_radial_profile(knots: list[Knot] | tuple[Knot, ...]) -> tuple[Knot, ...]:
    """Normalize 2..128 explicit increasing nonnegative radii and finite heights.

    Signed heights support bumps and grooves. The final height must be exactly
    zero. A profile starting at a positive radius must also start at zero height
    to join its zero interior continuously; a radius-zero center may be nonzero.
    """
    if type(knots) not in (list, tuple) or not 2 <= len(knots) <= MAX_KNOTS:
        raise ValueError(f"knots require 2..{MAX_KNOTS} explicit list/tuple entries")
    result: list[Knot] = []
    for knot in knots:
        if type(knot) not in (list, tuple) or len(knot) != 2:
            raise ValueError("each radial knot requires exactly (radius, height)")
        radius, height = _number(knot[0], "radius"), _number(knot[1], "height")
        if radius < 0 or (result and radius <= result[-1][0]):
            raise ValueError("radii must be nonnegative and strictly increasing")
        result.append((radius, height))
    if result[-1][1] != 0:
        raise ValueError("final radial height must be exactly zero for compact support")
    if result[0][0] > 0 and result[0][1] != 0:
        raise ValueError("positive inner support radius requires an initial zero height")
    return tuple(result)


@dataclass(frozen=True)
class RadialProfile:
    """An immutable validated profile; construction never substitutes a shape."""

    knots: tuple[Knot, ...]

    def __post_init__(self) -> None:
        """Validate/copy source data once, keeping later caller mutations isolated."""
        object.__setattr__(self, "knots", validate_radial_profile(self.knots))

    def height_at(self, radius: float) -> float:
        """Evaluate cubic smoothstep inside support and exact zero outside it.

        Each knot value is returned exactly. Smoothstep has zero slope at both
        ends of each interval, giving mathematical C1 joins and a C1 zero tail.
        Returned values use ordinary finite float arithmetic, not a sampling
        error certificate. Radius is a nonnegative distance in the knots' units.
        """
        radius = _number(radius, "sample radius")
        if radius < 0:
            raise ValueError("sample radius must be nonnegative")
        if radius < self.knots[0][0] or radius >= self.knots[-1][0]:
            return 0.0
        index = bisect_right(self.knots, radius, key=lambda knot: knot[0]) - 1
        left_radius, left_height = self.knots[index]
        if radius == left_radius:
            return left_height
        right_radius, right_height = self.knots[index + 1]
        t = (radius - left_radius) / (right_radius - left_radius)
        blend = t * t * (3.0 - 2.0 * t)
        return (1.0 - blend) * left_height + blend * right_height

    def heights_at(self, radii: list[float] | tuple[float, ...]) -> tuple[float, ...]:
        """Evaluate an explicit bounded batch without iterators or raster output."""
        if type(radii) not in (list, tuple) or not 0 <= len(radii) <= MAX_RADIAL_SAMPLES:
            raise ValueError(f"radii require 0..{MAX_RADIAL_SAMPLES} explicit entries")
        return tuple(self.height_at(radius) for radius in radii)
