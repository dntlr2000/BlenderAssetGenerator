"""Bounded reference-grid occupancy diagnostics, separate from 3D fidelity claims.

The rasterizer evaluates every covered pixel centre with exact integer predicates
on supplied binary coordinates. It supports only axis-aligned orthographic X/Z
projection. Callers must bind inputs to actual inspected geometry and the frozen
camera; this pure helper cannot attest their origin or infer image interpretation.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from fractions import Fraction

from PIL import Image

MAX_PIXELS = 4_194_304
MAX_VERTICES = 65_536
MAX_TRIANGLES = 65_536
MAX_PIXEL_TESTS = 20_000_000
MAX_COMPONENT_DETAILS = 64


def _array(value: object, minimum: int, maximum: int, label: str) -> list | tuple:
    """Reject unbounded or caller-defined containers before consuming input."""
    if type(value) not in (list, tuple) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} requires a bounded built-in list or tuple")
    return value


def _number(value: object) -> Fraction:
    """Interpret finite bounded built-in coordinates exactly, excluding coercion."""
    if type(value) not in (int, float):
        raise ValueError("coordinates require built-in finite numbers")
    try:
        valid = math.isfinite(value) and abs(value) <= 1_000_000
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("coordinate exceeds the finite bound")
    result = Fraction(value)
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > 256:
        raise ValueError("coordinate exceeds exact arithmetic precision budget")
    return result


def _resolution(value: object) -> tuple[int, int]:
    """Bound the full image grid rather than downsampling an oversized request."""
    raw = _array(value, 2, 2, "resolution")
    if any(type(x) is not int or not 1 <= x <= 4096 for x in raw):
        raise ValueError("resolution requires positive bounded integer dimensions")
    if raw[0] * raw[1] > MAX_PIXELS:
        raise ValueError("image grid exceeds pixel budget")
    return raw[0], raw[1]


def rasterize_orthographic_occupancy(
    vertices: object,
    triangles: object,
    *,
    resolution: object,
    ortho_scale: object,
    center_x: object = 0.0,
    center_z: object = 0.0,
) -> tuple[Image.Image, dict]:
    """Rasterize actual X/Z triangles at exact pixel centres without edge dilation.

    The camera faces +Y with +Z up, square pixels and Blender AUTO sensor fit:
    ortho_scale spans the larger image dimension. Depth, materials, occlusion
    ordering and subpixel visual coverage are
    outside this binary occupancy check. Work exhaustion raises before any image
    is returned; the caller must never substitute the partly filled buffer.
    """
    width, height = _resolution(resolution)
    scale, cx, cz = map(_number, (ortho_scale, center_x, center_z))
    if scale <= 0:
        raise ValueError("orthographic scale must be positive")
    view_factor = max(width, height)
    projected = []
    for vertex in _array(vertices, 3, MAX_VERTICES, "vertices"):
        p = [_number(c) for c in _array(vertex, 3, 3, "vertex")]
        projected.append(
            (
                (p[0] - cx) * view_factor / scale + Fraction(width, 2),
                (cz - p[2]) * view_factor / scale + Fraction(height, 2),
            )
        )
    faces = _array(triangles, 1, MAX_TRIANGLES, "triangles")
    output = bytearray(width * height)
    tests = 0
    edge_tests = 0
    degenerate_projections = 0
    for face in faces:
        indices = _array(face, 3, 3, "triangle")
        if any(type(i) is not int or not 0 <= i < len(projected) for i in indices):
            raise ValueError("triangle index is invalid")
        if len(set(indices)) != 3:
            raise ValueError("triangle repeats an index")
        points = [projected[i] for i in indices]
        denominator = math.lcm(*(c.denominator for p in points for c in p))
        if denominator.bit_length() > 512:
            raise ValueError("projection exceeds exact arithmetic precision budget")
        q = [(int(2 * p[0] * denominator), int(2 * p[1] * denominator)) for p in points]
        area = (q[1][0] - q[0][0]) * (q[2][1] - q[0][1]) - (q[1][1] - q[0][1]) * (q[2][0] - q[0][0])
        if not area:
            degenerate_projections += 1
            continue
        if area < 0:
            q.reverse()
        left = max(0, math.ceil(min(p[0] for p in points) - Fraction(1, 2)))
        right = min(width - 1, math.floor(max(p[0] for p in points) - Fraction(1, 2)))
        top = max(0, math.ceil(min(p[1] for p in points) - Fraction(1, 2)))
        bottom = min(height - 1, math.floor(max(p[1] for p in points) - Fraction(1, 2)))
        edges = [(b[0] - a[0], b[1] - a[1], a) for a, b in zip(q, q[1:] + q[:1], strict=False)]
        for y in range(top, bottom + 1):
            py = (2 * y + 1) * denominator
            low, high = left, right
            # Each edge gives A*x+B>=0 for the exact centre ((2*x+1)*den, py).
            # Intersect all integer intervals; no bbox pixel sampling is necessary.
            for dx, dy, a in edges:
                coefficient = -2 * dy * denominator
                constant = dx * (py - a[1]) - dy * (denominator - a[0])
                edge_tests += 1
                if coefficient > 0:
                    low = max(low, -(constant // coefficient))
                elif coefficient < 0:
                    high = min(high, constant // -coefficient)
                elif constant < 0:
                    high = low - 1
            count = max(0, high - low + 1)
            tests += count
            if tests + edge_tests > MAX_PIXEL_TESTS:
                raise ValueError("complete rasterization exceeds pixel-test budget")
            if count:
                start = y * width + low
                output[start : start + count] = b"\xff" * count
    return Image.frombytes("L", (width, height), bytes(output)), {
        "method": "exact_orthographic_pixel_centres_v1",
        "pixel_tests": tests,
        "scanline_edge_tests": edge_tests,
        "combined_work_limit": MAX_PIXEL_TESTS,
        "camera_scope": "axis_aligned_orthographic_AUTO_square_pixels",
        "triangle_count": len(faces),
        "zero_area_projections": degenerate_projections,
        "boundary_dilation_pixels": 0,
        "actual_geometry_origin_verified": False,
        "depth_or_material_correctness_verified": False,
    }


def _components(mask: bytearray, width: int, height: int) -> dict:
    """Count every four-connected mismatch, retaining bounded largest-component detail."""
    count = 0
    largest = []
    for start, value in enumerate(mask):
        if not value:
            continue
        count += 1
        queue = deque([start])
        mask[start] = 0
        pixels = 0
        left = right = start % width
        top = bottom = start // width
        while queue:
            index = queue.popleft()
            x, y = index % width, index // width
            pixels += 1
            left, right, top, bottom = (
                min(left, x),
                max(right, x),
                min(top, y),
                max(bottom, y),
            )
            neighbours = []
            if x:
                neighbours.append(index - 1)
            if x + 1 < width:
                neighbours.append(index + 1)
            if y:
                neighbours.append(index - width)
            if y + 1 < height:
                neighbours.append(index + width)
            for neighbour in neighbours:
                if mask[neighbour]:
                    mask[neighbour] = 0
                    queue.append(neighbour)
        item = (pixels, left, top, right + 1, bottom + 1)
        if len(largest) < MAX_COMPONENT_DETAILS:
            heapq.heappush(largest, item)
        elif item > largest[0]:
            heapq.heapreplace(largest, item)
    return {
        "component_count": count,
        "connectivity": 4,
        "largest_components": [
            {"pixels": n, "bbox_pixels": [left, top, right, bottom]}
            for n, left, top, right, bottom in sorted(largest, reverse=True)
        ],
        "component_details_omitted": max(0, count - len(largest)),
    }


def compare_sure_trimap_occupancy(trimap: Image.Image, candidate: Image.Image) -> dict:
    """Check every sure reference pixel without converting ambiguity into a pass.

    Existing labels 0/255 mean sure background/foreground; 85/170 remain unscored.
    This is a complete image-grid measurement, not continuous surface attachment,
    automated semantic fidelity, native provenance or final human acceptance.
    """
    if trimap.mode != "L" or candidate.mode != "L" or trimap.size != candidate.size:
        raise ValueError("trimap and candidate require equal-resolution grayscale images")
    width, height = _resolution(trimap.size)
    expected, actual = trimap.tobytes(), candidate.tobytes()
    if not set(expected) <= {0, 85, 170, 255} or not {0, 255} <= set(expected):
        raise ValueError("trimap requires both sure classes and only existing labels")
    if not set(actual) <= {0, 255}:
        raise ValueError("candidate occupancy must be binary; no implicit thresholding")
    missing, extra = bytearray(len(expected)), bytearray(len(expected))
    foreground = background = ignored = 0
    for i, (reference, predicted) in enumerate(zip(expected, actual, strict=True)):
        if reference == 255:
            foreground += 1
            missing[i] = int(predicted == 0)
        elif reference == 0:
            background += 1
            extra[i] = int(predicted == 255)
        else:
            ignored += 1
    missing_count, extra_count = sum(missing), sum(extra)
    return {
        "scope": "all_sure_reference_pixels_at_declared_grid",
        "status": "passed" if not missing_count and not extra_count else "failed",
        "passed": not missing_count and not extra_count,
        "resolution": [width, height],
        "sure_foreground_pixels": foreground,
        "sure_background_pixels": background,
        "unscored_pixels": ignored,
        "missing_foreground_pixels": missing_count,
        "filled_background_pixels": extra_count,
        "missing_components": _components(missing, width, height),
        "extra_components": _components(extra, width, height),
        "resampling_applied": False,
        "gap_filling_applied": False,
        "artifact_identity_verified": False,
        "continuous_3d_attachment_verified": False,
        "whole_asset_fidelity_verified": False,
        "human_acceptance": False,
    }
