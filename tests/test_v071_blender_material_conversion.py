from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "src" / "codex_blender_modeler" / "blender_scripts"
SCRIPT_PATH = SCRIPT_ROOT / "convert_portable_materials.py"
RUNTIME_PATH = SCRIPT_ROOT / "portable_material_conversion_runtime.py"


def load_runtime() -> ModuleType:
    """Load only the Blender-independent conversion helpers for unit tests."""

    spec = importlib.util.spec_from_file_location(
        "portable_material_conversion_runtime_test",
        RUNTIME_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load portable material conversion runtime")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v071_conversion_methods_have_descriptions() -> None:
    """Repository policy requires every added Blender conversion method to be described."""

    for path in (SCRIPT_PATH, RUNTIME_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        missing = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and ast.get_docstring(node) is None
        ]
        assert missing == [], f"{path.name}: undocumented functions {missing}"


def test_atlas_grid_tiles_are_deterministic_and_disjoint() -> None:
    """Global row-major tiles stay separated by the declared pixel margin."""

    runtime = load_runtime()
    first = [runtime.atlas_tile_bounds(index, 17, 2048, 16) for index in range(17)]
    second = [runtime.atlas_tile_bounds(index, 17, 2048, 16) for index in range(17)]
    assert first == second
    assert runtime.grid_shape(17) == (5, 4)
    for minimum_u, minimum_v, maximum_u, maximum_v in first:
        assert 0.0 <= minimum_u < maximum_u <= 1.0
        assert 0.0 <= minimum_v < maximum_v <= 1.0
    for index, left in enumerate(first):
        for right in first[index + 1 :]:
            overlap_u = min(left[2], right[2]) - max(left[0], right[0])
            overlap_v = min(left[3], right[3]) - max(left[1], right[1])
            assert overlap_u <= 0.0 or overlap_v <= 0.0


def test_atlas_grid_rejects_unusable_margin() -> None:
    """Do not silently generate empty tiles at undersized resolutions."""

    runtime = load_runtime()
    with pytest.raises(ValueError, match="too small"):
        runtime.atlas_tile_bounds(0, 100, 64, 16)


def test_blender_texture_path_survives_atomic_directory_promotion(tmp_path: Path) -> None:
    """Converted image nodes use Blender-relative paths rather than staging absolutes."""

    runtime = load_runtime()
    blend = tmp_path / "conversion.partial" / "converted" / "scene.blend"
    texture = tmp_path / "conversion.partial" / "textures" / "stone" / "base_color.png"
    assert runtime.blender_relative_path(texture, blend.parent) == (
        "//../textures/stone/base_color.png"
    )


def test_stable_object_key_uses_semantics_source_lod_and_name() -> None:
    """Atlas allocation does not depend on Blender collection insertion order."""

    runtime = load_runtime()
    values = [
        {"name": "z", "semantic_id": "b", "source_object": "s", "lod_level": 0},
        {"name": "b", "semantic_id": "a", "source_object": "s", "lod_level": 1},
        {"name": "a", "semantic_id": "a", "source_object": "s", "lod_level": 0},
    ]
    assert [item["name"] for item in sorted(values, key=runtime.stable_object_key)] == [
        "a",
        "b",
        "z",
    ]


def test_runtime_generates_contract_safe_ids_from_blender_names() -> None:
    """Underscored Blender names become bounded V0.7 StableId values with hash suffixes."""

    runtime = load_runtime()
    value = runtime.stable_identifier("island.part__LOD2", "binding")
    assert "_" not in value
    assert len(value) <= 128
    assert value == runtime.stable_identifier("island.part__LOD2", "binding")


def test_conversion_script_exposes_hash_bound_run_owned_arguments() -> None:
    """The host can bind every staged conversion input and output explicitly."""

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    for argument in (
        "--job-root",
        "--conversion-plan",
        "--profile",
        "--output-blend",
        "--output-evidence",
        "--output-texture-root",
        "--resolution",
        "--margin-px",
        "--render-device",
        "--source-blend-sha256",
        "--expected-plan-sha256",
    ):
        assert f'parser.add_argument("{argument}"' in source
    assert "Portable material conversion cannot overwrite the optimized source" in source
    assert "Optimized source blend changed during derived conversion" in source


def test_conversion_excludes_authoring_and_colliders_and_rejects_generated_mapping() -> None:
    """Only render/LOD meshes are converted and ambiguous Generated coordinates fail closed."""

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'CONVERTIBLE_ROLES = {"render", "lod"}' in source
    assert "in CONVERTIBLE_ROLES" in source
    assert 'if mode == "generated"' in source
    host_source = (
        ROOT / "src" / "codex_blender_modeler" / "packaging" / "material_conversion.py"
    ).read_text(encoding="utf-8")
    assert 'if recipe.mapping.mode == "generated"' in host_source
    assert "V0.7.1 portable" in host_source
    assert "requires an explicit authored fallback" in source
    assert "exactly one material slot" in source


def test_conversion_freezes_source_coordinates_before_atlas_activation() -> None:
    """UV and Object mappings retain their pre-atlas coordinate semantics during baking."""

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'nodes.new("ShaderNodeUVMap")' in source
    assert 'uv_node.name = "CBM_Portable_SourceUV"' in source
    assert "node.object = source_object" in source
    assert "cbm_source_object" in source
    assert source.index("_clone_source_material(obj)") < source.index(
        "_create_atlas_uv(obj, bounds)"
    )


def test_atlas_uv_reacquires_float2_storage_after_edit_mode() -> None:
    """Blender 5 must not reuse deprecated UV-loop RNA handles after Smart Project."""

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    function = source[source.index("def _create_atlas_uv(") : source.index("\ndef _activate_many(")]
    object_mode = function.index('bpy.ops.object.mode_set(mode="OBJECT")')
    reacquire = function.index("layer = mesh.uv_layers.get(ATLAS_UV_SET)", object_mode)
    float2_get = function.index('uv_values.foreach_get("vector", coordinates)', reacquire)
    float2_set = function.index('uv_values.foreach_set("vector", coordinates)', float2_get)
    assert object_mode < reacquire < float2_get < float2_set
    assert "for loop in layer.data" not in function


def test_atlas_uv_repairs_zero_area_smart_project_faces() -> None:
    """Degenerate Smart UV faces trigger a strict per-face Lightmap Pack fallback."""

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "def _degenerate_uv_faces" in source
    assert "def _lightmap_fallback" in source
    assert 'bpy.ops.uv.lightmap_pack.poll()' in source
    assert '"PREF_NEW_UVLAYER": False' in source
    assert "Portable atlas retains" in source
    assert '"unwrap_method": unwrap_method' in source


def test_portable_conversion_repairs_only_detected_tangent_micro_slivers() -> None:
    """Tangent repair is conditional, bounded, evidenced, and run-owned."""

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "def _invalid_tangent_faces" in source
    assert "def _micro_sliver_faces" in source
    assert "def _simulated_export_tangent_faces" in source
    assert "def _repair_tangent_micro_slivers" in source
    assert "bmesh.ops.dissolve_degenerate" in source
    assert "dist=1e-6" in source
    assert 'quad_method="BEAUTY"' in source
    assert '"repair_method": "dissolve_degenerate"' in source
    assert '"micro_sliver_face_count_before": len(micro_slivers)' in source
    assert "bounds_delta > 1e-6" in source
    assert source.index("_create_atlas_uv(obj, bounds)") < source.index(
        "_repair_tangent_micro_slivers(obj, ATLAS_UV_SET)"
    )


def test_conversion_bakes_five_channels_and_includes_emission_strength() -> None:
    """Portable maps include bounded PBR channels and intensity-weighted emission."""

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert (
        'CHANNELS = ("base_color", "roughness", "metallic", "normal", "emission")'
        in source
    )
    assert 'multiply.blend_type = "MULTIPLY"' in source
    assert "_emission_strength_socket(material)" in source
    assert 'kwargs["normal_space"] = "TANGENT"' in source
    assert '"emission": "sRGB"' in source
    assert "_bake_global_channels(" in source


def test_conversion_requires_exact_global_atlas_policy_and_scope() -> None:
    """Blender execution rechecks host-approved atlas and material coverage contracts."""

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'ATLAS_UV_SET = "CBMPortableAtlas"' in source
    assert '"layout": "global_shared"' in source
    assert '"atlas_scope": "all_render_lod"' in source
    assert '"tile_strategy": "deterministic_grid"' in source
    assert '"required_channels": list(CHANNELS)' in source
    assert "required_material_ids must exactly match derived material IDs" in source
    assert "Conversion target_ids are stale" in source
    assert "Shader recipe artifact changed" in source


def test_conversion_writes_relocatable_portable_materials_and_atomic_evidence() -> None:
    """The derived blend and raw report are separate, relocatable, and atomically published."""

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "image.filepath_raw = blender_relative_path(output, output_blend.parent)" in source
    assert '"relative_remap": False' in source
    assert 'temporary = output_blend.with_name(output_blend.stem + ".partial.blend")' in source
    assert '"kind": "portable_material_conversion_evidence"' in source
    assert '"optimized_blend_sha256": source_blend_sha256' in source
    assert '"conversion_plan_sha256": plan_sha256' in source
    assert '"profile_sha256": profile_sha256' in source
    assert '"portable_blend": {' in source
    assert '"sha256": output_blend_sha256' in source
    assert "first_reference_test" not in source
