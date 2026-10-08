"""Bounded, deterministic exterior refinement primitives for staged BAG recipes.

These pure data operators grant no controller, canonical-state or delivery authority.
They keep topology/UV arrays untouched and fail on excessive displacement.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np


def canonical_sha(value):
    """Hash a recipe or derived source map with BAG canonical JSON semantics."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def checked_vertices(value):
    """Reject malformed or nonfinite coordinate arrays before any refinement."""
    vertices = np.asarray(value, dtype=np.float64)
    if (
        vertices.ndim != 2
        or vertices.shape[1] != 3
        or len(vertices) < 3
        or not np.isfinite(vertices).all()
    ):
        raise ValueError("vertices must be finite Nx3 coordinates")
    return vertices


def checked_indices(value, count, minimum):
    """Require exact nonnegative integer selections without lossy numeric coercion."""
    if (
        not isinstance(value, (list, tuple))
        or len(value) < minimum
        or any(type(index) is not int or index < 0 or index >= count for index in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("indices must be unique bounded integers")
    return np.asarray(value, dtype=np.int64)


def bounded_result(before, after, maximum_displacement):
    """Quantize to actual Blender precision and enforce the declared motion bound."""
    if not 0 < maximum_displacement <= 1:
        raise ValueError("invalid displacement bound")
    result = np.asarray(after, dtype=np.float32).astype(np.float64)
    displacement = np.linalg.norm(result - before, axis=1)
    if not np.isfinite(result).all() or float(displacement.max()) > maximum_displacement:
        raise ValueError("refinement exceeds the declared displacement bound")
    return result.tolist(), {
        "maximum_displacement": float(displacement.max()),
        "mean_displacement": float(displacement.mean()),
        "quantization": "IEEE754_binary32",
    }


def quadratic_depth_regularize(
    vertices, *, basis, fit_indices, target_indices, weights, depth_offset, maximum_displacement
):
    """Fit a smooth shell field and regularize only explicitly weighted rear vertices.

    The two in-plane coordinates remain fixed. A single-image hidden side remains an
    inferred smooth-shell hypothesis, not recovered evidence. Boundary weights may
    lock exact perimeter positions.
    """
    before = checked_vertices(vertices)
    frame = np.asarray(basis, dtype=np.float64)
    if frame.shape != (3, 3) or not np.allclose(frame @ frame.T, np.eye(3), atol=1e-8):
        raise ValueError("basis must be orthonormal")
    fit = checked_indices(fit_indices, len(before), 6)
    targets = checked_indices(target_indices, len(before), 1)
    w = np.asarray(weights, dtype=float)
    if w.shape != targets.shape or not np.isfinite(w).all() or np.any((w < 0) | (w > 1)):
        raise ValueError("weights must be finite values in [0,1]")
    local = before @ frame.T
    design = np.stack(
        [
            np.ones(len(local)),
            local[:, 0],
            local[:, 1],
            local[:, 0] ** 2,
            local[:, 0] * local[:, 1],
            local[:, 1] ** 2,
        ],
        axis=1,
    )
    coefficients, _, rank, _ = np.linalg.lstsq(design[fit], local[fit, 2], rcond=None)
    if rank != 6:
        raise ValueError("quadratic support is rank deficient")
    proposed = design[targets] @ coefficients + depth_offset
    after = before.copy()
    after[targets] += ((proposed - local[targets, 2]) * w)[:, None] * frame[2]
    result, report = bounded_result(before, after, maximum_displacement)
    report.update(
        {
            "operation": "quadratic_depth_regularize",
            "coefficients": coefficients.tolist(),
            "fit_rms": float(np.sqrt(np.mean((design[fit] @ coefficients - local[fit, 2]) ** 2))),
            "target_count": len(targets),
            "locked_target_count": int(np.sum(w == 0)),
        }
    )
    return result, report


def fair_ring_profiles(
    vertices, *, ring_size, ring_count, axis, vertex_weights, iterations, maximum_displacement
):
    """Round overly serrated cross-sections without changing end stations or UVs."""
    before = checked_vertices(vertices)
    if (
        type(ring_size) is not int
        or type(ring_count) is not int
        or type(axis) is not int
        or ring_size < 4
        or ring_count < 2
        or ring_size * ring_count != len(before)
        or axis not in (0, 1, 2)
    ):
        raise ValueError("regular ring topology is required")
    if type(iterations) is not int or not 1 <= iterations <= 4:
        raise ValueError("iterations must be 1..4")
    weights = np.asarray(vertex_weights, dtype=float)
    if (
        weights.shape != (len(before),)
        or not np.isfinite(weights).all()
        or np.any((weights < 0) | (weights > 0.8))
    ):
        raise ValueError("profile weights must be in [0,.8]")
    result = before.reshape(ring_count, ring_size, 3).copy()
    for _ in range(iterations):
        neighbors = (np.roll(result, 1, axis=1) + np.roll(result, -1, axis=1)) / 2
        delta = neighbors - result
        delta[:, :, axis] = 0
        result += delta * weights.reshape(ring_count, ring_size, 1)
    output, report = bounded_result(before, result.reshape(-1, 3), maximum_displacement)
    report.update(
        {
            "operation": "fair_ring_profiles",
            "ring_count": ring_count,
            "ring_size": ring_size,
            "axis": axis,
            "iterations": iterations,
        }
    )
    return output, report


def normal_strength(rgb, strength):
    """Scale tangent-space slopes and renormalize, preserving OpenGL +Y convention."""
    if not 0 <= strength <= 1:
        raise ValueError("normal attenuation must be in [0,1]")
    values = np.asarray(rgb, dtype=float)
    if (
        values.ndim != 3
        or values.shape[-1] != 3
        or not np.isfinite(values).all()
        or np.any((values < 0) | (values > 255))
    ):
        raise ValueError("normal input must be finite HxWx3")
    vectors = values / 127.5 - 1
    vectors[..., :2] *= strength
    vectors /= np.maximum(np.linalg.norm(vectors, axis=-1, keepdims=True), 1e-12)
    return np.round((vectors + 1) * 127.5).clip(0, 255).astype(np.uint8)


def oxide_metal_response(base_rgb, metallic, roughness, *, metal_roughness=0.48):
    """Separate exposed-metal response from porous oxide using an existing mask.

    This is a material hypothesis controlled by an existing authored metal field;
    no photo pixel is treated as measured physical reflectance.
    """
    base = np.asarray(base_rgb, dtype=float) / 255
    metal = np.asarray(metallic, dtype=float) / 255
    rough = np.asarray(roughness, dtype=float) / 255
    if any(
        not np.isfinite(values).all() or np.any((values < 0) | (values > 1))
        for values in (base, metal, rough)
    ):
        raise ValueError("material channels must contain finite byte-range samples")
    if base.shape[:2] != metal.shape or rough.shape != metal.shape or base.shape[-1] != 3:
        raise ValueError("material channels must have matching dimensions")
    if not 0.2 <= metal_roughness <= 0.6:
        raise ValueError("material response parameters are outside the bounded domain")
    mask = np.clip((metal - 0.0235) / (0.8 - 0.0235), 0, 1)
    steel = (np.sum(base * np.array([0.2126, 0.7152, 0.0722]), axis=-1) * 0.99)[
        ..., None
    ] * np.array([0.98, 1.0, 1.02])
    oxide = base * np.array([1.03, 1.08, 1.08])
    rgb = oxide * (1 - mask[..., None]) + steel * mask[..., None]
    rr = rough * (1 - mask) + np.clip(metal_roughness + (rough - 0.69) * 0.28, 0.25, 0.55) * mask
    mm = 0.015 * (1 - mask) + 0.92 * mask
    return tuple(np.round(x * 255).clip(0, 255).astype(np.uint8) for x in (rgb, mm, rr))
