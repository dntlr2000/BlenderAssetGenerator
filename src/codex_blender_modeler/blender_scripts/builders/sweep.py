"""Blender builder for deterministic parallel-transport sweep geometry."""

from __future__ import annotations

from pathlib import Path

import bpy

from codex_blender_modeler.structural_geometry.mesh_math import build_sweep_mesh

from ._structural_mesh import create_mesh_object


def build(spec: dict, _base_dir: Path) -> bpy.types.Object:
    """Build a validated profile sweep as one deterministic Blender mesh."""

    return create_mesh_object(
        "CBM_StructuralSweep",
        build_sweep_mesh(spec),
        builder_kind="sweep",
    )
