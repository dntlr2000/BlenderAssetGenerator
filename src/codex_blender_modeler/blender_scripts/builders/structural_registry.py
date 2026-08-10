"""Opt-in Blender builder registry for legacy and structural SceneSpec 0.3 kinds."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import bpy

from builders import (
    boolean_tree,
    curve,
    custom_mesh,
    geometry_nodes_template,
    loft,
    multi_loop_extrude,
    primitive,
    profile_extrude,
    revolve,
    sweep,
    terrain,
)

Builder = Callable[[dict, Path], bpy.types.Object]

_STRUCTURAL_BUILDERS: dict[str, Builder] = {
    "primitive": primitive.build,
    "custom_mesh": custom_mesh.build,
    "profile_extrude": profile_extrude.build,
    "revolve": revolve.build,
    "curve": curve.build,
    "terrain": terrain.build,
    "loft": loft.build,
    "sweep": sweep.build,
    "boolean_tree": boolean_tree.build,
    "multi_loop_extrude": multi_loop_extrude.build,
    "geometry_nodes_template": geometry_nodes_template.build,
}


def supported_geometry_kinds() -> tuple[str, ...]:
    """Return the exact whitelisted structural builder names in stable order."""

    return tuple(sorted(_STRUCTURAL_BUILDERS))


def create_structural_geometry(spec: dict, base_dir: Path) -> bpy.types.Object:
    """Dispatch one validated geometry recipe without exposing arbitrary Blender code."""

    kind = str(spec.get("kind", ""))
    builder = _STRUCTURAL_BUILDERS.get(kind)
    if builder is None:
        raise ValueError(f"Unsupported structural geometry kind: {kind}")
    return builder(spec, base_dir)
