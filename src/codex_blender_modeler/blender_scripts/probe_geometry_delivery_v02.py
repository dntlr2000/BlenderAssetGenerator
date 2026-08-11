"""Create a fixed LOD0 GLB/FBX fixture for AQ v2 delivery-survival inspection."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from portable_asset_common import operator_kwargs, sha256_file, write_json  # noqa: E402


def _parse_args() -> argparse.Namespace:
    """Parse only contained output paths for the fixed delivery fixture."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--optimized-blend", required=True)
    parser.add_argument("--glb", required=True)
    parser.add_argument("--fbx", required=True)
    parser.add_argument("--receipt", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def _contained(path: str, root: Path) -> Path:
    """Resolve one output path below the isolated fixture root."""

    candidate = Path(path).expanduser().resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("delivery fixture output escapes its job root") from exc
    if candidate.exists():
        raise FileExistsError(candidate)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def _build_fixture() -> bpy.types.Object:
    """Build one UV-mapped, sharp-edged, material-bound static render cube."""

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
    obj = bpy.context.object
    if obj is None or obj.type != "MESH":
        raise RuntimeError("fixed delivery fixture did not create one mesh")
    obj.name = "AQV2_DeliveryCube"
    obj["cbm_id"] = "asset.body"
    obj["cbm_asset_role"] = "render"
    obj["cbm_lod_level"] = 0
    obj["cbm_fixture"] = "geometry_delivery_v02"
    material = bpy.data.materials.new("mat.body")
    material["cbm_id"] = "mat.body"
    material.diffuse_color = (0.2, 0.45, 0.8, 1.0)
    obj.data.materials.append(material)
    for polygon in obj.data.polygons:
        polygon.material_index = 0
        polygon.use_smooth = False
    for edge in obj.data.edges:
        edge.use_edge_sharp = edge.index in {0, 1, 2, 3}
        edge.use_seam = edge.index in {0, 4, 8}
    if not obj.data.uv_layers:
        raise RuntimeError("fixed delivery cube has no generated UV layer")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def _export_glb(path: Path) -> None:
    """Export the selected fixture through Blender's built-in glTF operator."""

    operator = bpy.ops.export_scene.gltf
    operator(
        **operator_kwargs(
            operator,
            {
                "filepath": str(path),
                "export_format": "GLB",
                "use_selection": True,
                "export_extras": True,
                "export_materials": "EXPORT",
                "export_apply": False,
            },
        )
    )


def _export_fbx(path: Path) -> None:
    """Export the selected fixture through Blender's built-in FBX operator."""

    operator = bpy.ops.export_scene.fbx
    operator(
        **operator_kwargs(
            operator,
            {
                "filepath": str(path),
                "use_selection": True,
                "use_custom_props": True,
                "apply_unit_scale": True,
                "apply_scale_options": "FBX_SCALE_UNITS",
                "path_mode": "STRIP",
                "embed_textures": False,
                "use_metadata": False,
                "object_types": {"MESH"},
                "add_leaf_bones": False,
                "bake_anim": False,
                "use_tspace": True,
                "axis_forward": "-Z",
                "axis_up": "Y",
            },
        )
    )


def main() -> None:
    """Publish one immutable blend plus direct GLB and FBX exports and exact receipt."""

    args = _parse_args()
    root = Path(args.job_root).expanduser().resolve(strict=True)
    optimized_blend = _contained(args.optimized_blend, root)
    glb = _contained(args.glb, root)
    fbx = _contained(args.fbx, root)
    receipt = _contained(args.receipt, root)
    _build_fixture()
    bpy.ops.wm.save_as_mainfile(filepath=str(optimized_blend))
    _export_glb(glb)
    _export_fbx(fbx)
    outputs = [optimized_blend, glb, fbx]
    if any(not path.is_file() or path.stat().st_size == 0 for path in outputs):
        raise RuntimeError("fixed delivery fixture omitted an output")
    write_json(
        receipt,
        {
            "schema_version": "0.1.0",
            "status": "passed",
            "outputs": [
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha256_file(path),
                    "byte_size": path.stat().st_size,
                }
                for path in outputs
            ],
            "arbitrary_input_executed": False,
            "destination_project_written": False,
        },
    )


if __name__ == "__main__":
    main()
