from __future__ import annotations

from pathlib import Path

import bpy

from builders import curve, custom_mesh, primitive, profile_extrude, revolve, terrain

_BUILDERS = {
    "primitive": primitive.build,
    "custom_mesh": custom_mesh.build,
    "profile_extrude": profile_extrude.build,
    "revolve": revolve.build,
    "curve": curve.build,
    "terrain": terrain.build,
}


def create_geometry(spec: dict, base_dir: Path) -> bpy.types.Object:
    kind = spec.get("kind")
    try:
        builder = _BUILDERS[kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported geometry kind: {kind}") from exc
    return builder(spec, base_dir)
