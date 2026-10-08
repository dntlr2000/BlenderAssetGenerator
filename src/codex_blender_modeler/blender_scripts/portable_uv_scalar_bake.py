"""Bounded UV-domain scalar baking helpers; normal channels stay on actual geometry."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from fractions import Fraction

SCALAR_CHANNELS = ("base_color", "roughness", "metallic", "emission")
METHOD = "uv_domain_scalar_v1"


def exact_float32_points(points):
    """Require exact Float2 representability on host and Blender before using proxy UV corners."""
    for point in points:
        for value in point:
            try:
                stored = struct.unpack(">f", struct.pack(">f", value))[0]
            except (OverflowError, struct.error) as error:
                raise ValueError("UV scalar bake proxy corner exceeds Float2 range") from error
            if not math.isfinite(value) or stored != value:
                raise ValueError(
                    "UV scalar bake proxy corners are not exactly float32 representable"
                )
    return points


def affine_layer_corners(layout, sampled, corners):
    """Prove a complete exact affine relation before extrapolating another sampled UV layer."""
    if len(layout) != len(sampled) or len(layout) < 3:
        raise ValueError("UV scalar bake requires complete sampled layer correspondence")
    if layout == sampled:
        return exact_float32_points([list(point) for point in corners])
    # Exact binary-float rationals avoid accepting approximately affine unrelated UV layers.
    origin = tuple(Fraction(value) for value in layout[0])
    first = next((i for i, point in enumerate(layout) if tuple(point) != tuple(layout[0])), None)
    if first is None:
        raise ValueError("UV scalar bake source layout has no extent")
    a = tuple(Fraction(layout[first][axis]) - origin[axis] for axis in (0, 1))
    second = None
    for i, point in enumerate(layout):
        b = tuple(Fraction(point[axis]) - origin[axis] for axis in (0, 1))
        determinant = a[0] * b[1] - a[1] * b[0]
        if determinant:
            second = i
            break
    if second is None:
        raise ValueError("UV scalar bake source layout is collinear")
    coefficients = []
    for axis in (0, 1):
        c = Fraction(sampled[0][axis])
        d = Fraction(sampled[first][axis]) - c
        e = Fraction(sampled[second][axis]) - c
        x = (d * b[1] - e * a[1]) / determinant
        y = (a[0] * e - b[0] * d) / determinant
        coefficients.append((x, y, c - x * origin[0] - y * origin[1]))
    for original, actual in zip(layout, sampled, strict=True):
        for axis, (x, y, c) in enumerate(coefficients):
            if x * Fraction(original[0]) + y * Fraction(original[1]) + c != Fraction(actual[axis]):
                raise ValueError(
                    "UV scalar bake ineligible: sampled UV layer is not exactly affine"
                )
    exact = [
        [x * Fraction(p[0]) + y * Fraction(p[1]) + c for x, y, c in coefficients] for p in corners
    ]
    result = [[float(value) for value in point] for point in exact]
    if any(
        Fraction(actual) != expected
        for point, originals in zip(result, exact, strict=True)
        for actual, expected in zip(point, originals, strict=True)
    ):
        raise ValueError("UV scalar bake ineligible: affine corners are not exactly representable")
    if not all(math.isfinite(value) for point in result for value in point):
        raise ValueError("UV scalar bake affine extrapolation is nonfinite")
    return exact_float32_points(result)


def snapshot_digest(value):
    """Bind finite ordered proxy evidence using the existing canonical JSON convention."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def coverage_pixel_box(bounds, resolution):
    """Include every bilinear texel touching a target tile, with PNG's downward V axis."""
    minimum_u, minimum_v, maximum_u, maximum_v = bounds
    return [
        max(0, math.floor(minimum_u * resolution - 0.5)),
        max(0, math.floor((1.0 - maximum_v) * resolution - 0.5)),
        min(resolution, math.ceil(maximum_u * resolution - 0.5) + 1),
        min(resolution, math.ceil((1.0 - minimum_v) * resolution - 0.5) + 1),
    ]
