"""One opt-in comparison rig derived only from the frozen camera, never candidate bounds."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

CAMERA_STUDIO_PROFILE = "camera_studio_v1"


def lighting_implementation_sha256() -> str:
    """Bind the exact fixed-profile implementation selected by a new quality loop."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def validate_lighting_selection(profile: str | None, implementation_sha256: str | None) -> None:
    """Reject unknown, partial or stale opt-in selections before any render effects."""
    if profile is None and implementation_sha256 is None:
        return
    if profile != CAMERA_STUDIO_PROFILE:
        raise ValueError("unsupported comparison lighting profile")
    if implementation_sha256 != lighting_implementation_sha256():
        raise ValueError("comparison lighting implementation changed")


def _vector(value: Any) -> tuple[float, float, float]:
    """Require a finite three-component camera vector without coercing strings or booleans."""
    if not isinstance(value, (tuple, list)) or len(value) != 3 or any(
        isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
        for item in value
    ):
        raise ValueError("comparison lighting requires finite camera vectors")
    return tuple(float(item) for item in value)


def _unit(value: tuple[float, float, float]) -> tuple[float, float, float]:
    """Normalize a nondegenerate direction for the deterministic camera frame."""
    length = math.sqrt(sum(item * item for item in value))
    if length < 1e-8:
        raise ValueError("comparison lighting camera direction is degenerate")
    return tuple(item / length for item in value)


def _cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Compute the right-handed camera frame without a Blender or numpy dependency."""
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def camera_studio_rig(camera: dict[str, Any]) -> dict[str, Any]:
    """Freeze a neutral three-area-light rig to camera scale, position and target alone."""
    location, target = _vector(camera.get("location")), _vector(camera.get("target"))
    delta = tuple(a - b for a, b in zip(location, target, strict=True))
    distance = math.sqrt(sum(value * value for value in delta))
    if not 1e-4 <= distance <= 1e5:
        raise ValueError("comparison lighting camera distance is outside supported bounds")
    outward = _unit(delta)
    up_axis = (0.0, 1.0, 0.0) if abs(outward[2]) > .999999 else (0.0, 0.0, 1.0)
    right = _unit(_cross(up_axis, outward))
    up = _unit(_cross(outward, right))
    lights = []
    for name, x, y, z, energy_factor, size_factor in (
        ("CBM_QA_Fill", .8, .2, .65, 18.0, .7),
        ("CBM_QA_Key", -.75, .65, 1.0, 32.0, .6),
        ("CBM_QA_Rim", 0.0, .8, -.8, 25.0, .5),
    ):
        position = [target[i] + distance * (x * right[i] + y * up[i] + z * outward[i])
                    for i in range(3)]
        lights.append({"name": name, "location": position, "target": list(target),
                       "energy": energy_factor * distance ** 2, "size": size_factor * distance})
    return {"profile": CAMERA_STUDIO_PROFILE, "lights": lights,
            "world_color": [.18, .18, .18, 1.0], "world_strength": .35,
            "view_transform": "AgX", "look": "AgX - Medium High Contrast",
            "exposure": 0.0, "gamma": 1.0, "film_transparent": False}


def _close(actual: Any, expected: float, label: str) -> None:
    """Require finite recorded numbers within Blender float serialization precision."""
    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isclose(
        actual, expected, rel_tol=2e-5, abs_tol=2e-5
    ):
        raise ValueError(f"comparison lighting {label} differs from the selected profile")


def validate_camera_studio_conditions(
    camera: dict[str, Any], conditions: dict[str, Any], *, implementation_sha256: str
) -> None:
    """Verify actual recorded lamps and display settings against the frozen camera policy."""
    rig = camera_studio_rig(camera)
    if (conditions.get("comparison_lighting_profile") != CAMERA_STUDIO_PROFILE
            or conditions.get("lighting_implementation_sha256") != implementation_sha256):
        raise ValueError("render omitted or changed its selected comparison lighting binding")
    actual_lights = conditions.get("lights")
    if not isinstance(actual_lights, list) or len(actual_lights) != len(rig["lights"]):
        raise ValueError("comparison lighting requires exactly three recorded area lights")
    for actual, expected in zip(actual_lights, rig["lights"], strict=True):
        if not isinstance(actual, dict):
            raise ValueError("comparison lighting light record is incomplete")
        if (actual.get("type"), actual.get("shape"), actual.get("hide_render")) != (
            "AREA", "DISK", False
        ):
            raise ValueError("comparison lighting has an unsupported or hidden light")
        _close(actual.get("energy"), expected["energy"], "energy")
        _close(actual.get("size"), expected["size"], "size")
        color = _vector(actual.get("color"))
        matrix = actual.get("matrix_world")
        if not isinstance(matrix, list) or len(matrix) != 4 or any(
            not isinstance(row, list) or len(row) != 4 for row in matrix
        ):
            raise ValueError("comparison lighting light transform is incomplete")
        direction = _unit(tuple(a - b for a, b in zip(
            expected["location"], expected["target"], strict=True)))
        for index in range(3):
            _close(color[index], 1.0, "color")
            _close(matrix[index][3], expected["location"][index], "location")
            _close(matrix[index][2], direction[index], "direction")
    world = conditions.get("world", {})
    if not isinstance(world, dict):
        raise ValueError("comparison lighting world record is incomplete")
    backgrounds = world.get("backgrounds", [])
    if (not isinstance(backgrounds, list) or len(backgrounds) != 1
            or not isinstance(backgrounds[0], dict) or world.get("links") != [
        ["ShaderNodeBackground", "Background", "ShaderNodeOutputWorld", "Surface"]
    ]):
        raise ValueError("comparison lighting world differs from the neutral profile")
    color = backgrounds[0].get("color", [])
    if not isinstance(color, (list, tuple)) or len(color) != 4:
        raise ValueError("comparison lighting world color is incomplete")
    for actual, expected in zip(color, rig["world_color"], strict=True):
        _close(actual, expected, "world color")
    _close(backgrounds[0].get("strength"), rig["world_strength"], "world strength")
    for key in ("view_transform", "look", "exposure", "gamma", "film_transparent"):
        if conditions.get(key) != rig[key]:
            raise ValueError(f"comparison lighting {key} differs from the selected profile")
