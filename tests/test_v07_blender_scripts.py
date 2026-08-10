from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from codex_blender_modeler.config import executable_exists, get_settings

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "src" / "codex_blender_modeler" / "blender_scripts"
SCRIPT_NAMES = (
    "portable_asset_common.py",
    "inspect_asset_topology.py",
    "prepare_optimized_asset.py",
    "export_portable_package.py",
    "validate_export_roundtrip.py",
)


def load_common() -> ModuleType:
    """Load the Blender-independent portable helper without importing bpy."""

    path = SCRIPT_ROOT / "portable_asset_common.py"
    spec = importlib.util.spec_from_file_location("portable_asset_common_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load portable_asset_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_export_script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load export verification helpers with a harmless fake bpy module."""

    path = SCRIPT_ROOT / "export_portable_package.py"
    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    spec = importlib.util.spec_from_file_location("portable_export_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load export_portable_package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_roundtrip_script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load round-trip policy helpers with a harmless fake bpy module."""

    path = SCRIPT_ROOT / "validate_export_roundtrip.py"
    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    spec = importlib.util.spec_from_file_location("portable_roundtrip_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load validate_export_roundtrip.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gltf_uv0_fixture() -> tuple[dict, dict]:
    """Return one minimal converted glTF document and matching export contract."""

    document = {
        "textures": [{"source": 0}],
        "materials": [
            {
                "extras": {"cbm_id": "mat.body"},
                "normalTexture": {"index": 0},
                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
            }
        ],
        "meshes": [
            {
                "primitives": [
                    {
                        "material": 0,
                        "attributes": {
                            "POSITION": 0,
                            "TEXCOORD_0": 1,
                            "TANGENT": 2,
                        },
                    }
                ]
            }
        ],
    }
    contract = {
        "status": "verified",
        "export_format": "gltf",
        "required_uv_set": "CBMPortableAtlas",
        "required_uv_channel_index": 0,
        "objects": [{"material_ids": ["mat.body"]}],
    }
    return document, contract


def test_portable_script_functions_have_descriptions() -> None:
    """Every V0.7 Blender-side method has the repository-required short description."""

    for name in SCRIPT_NAMES:
        tree = ast.parse((SCRIPT_ROOT / name).read_text(encoding="utf-8"))
        missing = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and ast.get_docstring(node) is None
        ]
        assert missing == [], f"{name}: undocumented functions {missing}"


def test_sha256_file_uses_lowercase_contract(tmp_path: Path) -> None:
    """Blender runtime digests match the lowercase V0.7 SHA-256 schema contract."""

    common = load_common()
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"portable-v07")
    digest = common.sha256_file(payload)
    assert len(digest) == 64
    assert digest == digest.lower()
    assert set(digest) <= set("0123456789abcdef")


def test_portable_json_io_supports_windows_extended_paths(tmp_path: Path) -> None:
    """Write, read, and hash deterministic Blender evidence beyond legacy MAX_PATH."""

    common = load_common()
    directory = tmp_path
    for index in range(8):
        directory /= f"quality-companion-output-{index:02d}-0123456789abcdef"
    output = directory / "assembly_topology_report.json"
    if os.name == "nt":
        assert len(os.path.abspath(output)) > 260
    payload = {"kind": "quality_companion_evidence", "ok": True}

    common.write_json(output, payload)

    assert os.path.isfile(common.native_io_path(output))
    assert common.read_json_object(output) == payload
    assert len(common.sha256_file(output)) == 64


@pytest.mark.skipif(
    os.getenv("CBM_RUN_PORTABLE_LONG_PATH_BLENDER_SMOKE") != "1",
    reason="Set CBM_RUN_PORTABLE_LONG_PATH_BLENDER_SMOKE=1 for Blender 5 evidence.",
)
def test_blender_runtime_writes_portable_json_to_extended_path(tmp_path: Path) -> None:
    """Run the fixed long-path JSON probe through Blender's bundled Python."""

    settings = get_settings()
    if not executable_exists(settings.blender_bin):
        pytest.skip(f"Blender executable not found: {settings.blender_bin}")
    directory = tmp_path
    for index in range(8):
        directory /= f"blender-quality-output-{index:02d}-0123456789abcdef"
    output = directory / "assembly_topology_report.json"
    if os.name == "nt":
        assert len(os.path.abspath(output)) > 260
    script = ROOT / "tests" / "blender_scripts" / "probe_portable_json_long_path.py"
    result = subprocess.run(
        [
            settings.blender_bin,
            "--factory-startup",
            "--background",
            "--python-exit-code",
            "1",
            "--python",
            str(script),
            "--",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=settings.blender_timeout,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    common = load_common()
    assert common.read_json_object(output)["ok"] is True


def test_portable_path_rejects_root_escape(tmp_path: Path) -> None:
    """Portable package manifests cannot serialize an artifact outside package root."""

    common = load_common()
    root = tmp_path / "package"
    root.mkdir()
    inside = root / "asset.glb"
    inside.write_bytes(b"glb")
    outside = tmp_path / "outside.glb"
    outside.write_bytes(b"glb")
    assert common.portable_path(inside, root) == "asset.glb"
    with pytest.raises(ValueError, match="outside the portable root"):
        common.portable_path(outside, root)


def test_blender_relative_texture_paths_resolve_inside_package(tmp_path: Path) -> None:
    """Treat Blender's double-slash notation as package-relative, not Windows UNC."""

    common = load_common()
    package = tmp_path / "package"
    target = package / "textures" / "stone.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"png")
    status, resolved = common.package_dependency_path("//textures/stone.png", package)
    assert status == "portable"
    assert resolved == target.resolve()


def test_runtime_absolute_texture_inside_package_is_not_external(tmp_path: Path) -> None:
    """Accept a resolved runtime path only when the image remains inside the package."""

    common = load_common()
    package = tmp_path / "package"
    target = package / "textures" / "stone.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"png")
    status, resolved = common.package_dependency_path(str(target.resolve()), package)
    assert status == "package_absolute"
    assert resolved == target.resolve()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C:/private/stone.png", "absolute"),
        ("\\\\server\\share\\stone.png", "absolute"),
        ("../outside.png", "outside"),
        ("//../outside.png", "outside"),
        ("textures/bad:name.png", "absolute"),
    ],
)
def test_texture_dependency_paths_reject_nonportable_values(
    tmp_path: Path,
    raw: str,
    expected: str,
) -> None:
    """Reject OS-absolute, traversal, UNC, and ADS-like texture dependencies."""

    common = load_common()
    package = tmp_path / "package"
    package.mkdir()
    status, _resolved = common.package_dependency_path(raw, package)
    assert status == expected


def test_scene_provenance_prefers_embedded_build_fingerprint() -> None:
    """Runtime provenance exposes the canonical embedded build fingerprint exactly."""

    common = load_common()

    class FakeScene(dict):
        """Provide Blender-like custom property access for one pure provenance test."""

    scene = FakeScene(
        cbm_job_id="portable_prop",
        cbm_schema_version="0.2.0",
        cbm_scene_spec_sha256="a" * 64,
        cbm_camera_fingerprint="b" * 64,
        cbm_material_build_fingerprint="c" * 64,
        cbm_build_provenance='{"fingerprint":"d"}',
    )
    provenance = common.scene_source_provenance(scene)
    assert provenance["job_id"] == "portable_prop"
    assert provenance["build_fingerprint"] == "c" * 64
    assert provenance["embedded_build_provenance"] == {"fingerprint": "d"}


def test_prepare_script_requires_separate_versioned_profile() -> None:
    """The Blender preparer consumes canonical plan and profile files separately."""

    source = (SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--plan", required=True)' in source
    assert 'parser.add_argument("--profile", required=True)' in source
    assert "OptimizationPlan must be approved" in source
    assert "output_blend == source_blend" in source


def test_prepare_script_supports_profile_base_center_pivot() -> None:
    """Keep the public base-center profile policy executable in derived Blender scenes."""

    source = (SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8")
    assert 'if normalized in {"base_center", "bottom_center"}' in source
    assert "min(corner.z for corner in local_corners)" in source
    assert "obj.data.transform(Matrix.Translation(-base_center))" in source
    assert "obj.matrix_world = obj.matrix_world @ Matrix.Translation(base_center)" in source


def test_prepare_script_omits_overlap_volumes_that_round_to_zero() -> None:
    """Keep report-only overlap findings strictly positive after evidence rounding."""

    source = (SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8")
    rounded = source.index("rounded_volume = round(volume, 9)")
    positive_check = source.index("if rounded_volume <= 0.0:", rounded)
    count = source.index("total += 1", positive_check)
    assert rounded < positive_check < count
    assert '"overlap_volume_m3": rounded_volume' in source


def test_prepare_script_reacquires_uv0_after_uv1_collection_mutation() -> None:
    """Keep the stable material UV name after Blender invalidates UV layer wrappers."""

    source = (SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8")
    assert "material_uv_name = str(uv0.name)" in source
    assert "uv0 = obj.data.uv_layers.get(material_uv_name)" in source
    assert "return actions, material_uv_name" in source
    assert "uv1_name == material_uv_name" in source
    assert 'return f"generated:{uv_set}"' in source


def test_prepare_script_triangulates_only_derived_ngons_before_tangents() -> None:
    """Make tangent calculation portable without rewriting the canonical source scene."""

    source = (SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8")
    assert "def triangulate_ngons_for_tangent_basis" in source
    assert "if len(face.verts) > 4" in source
    assert "triangulate_ngons_for_tangent_basis(lod0)" in source
    assert '"triangulated_ngons": triangulated_ngons' in source


def test_prepare_script_rejects_anonymous_authoring_geometry() -> None:
    """Do not let a stale preflight hide canonical geometry without semantic ownership."""

    source = (SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8")
    assert "anonymous_authoring_geometry" in source
    assert "Canonical authoring geometry is missing stable cbm_id" in source
    assert source.index("if anonymous_authoring_geometry") < source.index(
        "source_objects = authoring_geometry"
    )


def test_prepare_script_rejects_render_inclusion_of_boolean_helpers() -> None:
    """Keep tagged cutter volumes out of every derived portable render scene."""

    source = (SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8")
    assert "def object_source_tags" in source
    assert 'NON_RENDER_BOOLEAN_TAG = "hidden-boolean-target"' in source
    assert "bool(source.hide_render)" in source
    assert "if unsafe_helpers:" in source
    assert "Optimization directives include canonical non-render helper sources" in source


def test_prepare_script_enforces_lod_budget_on_derived_geometry_only() -> None:
    """Clean degenerate derived LOD faces before a bounded budget correction pass."""

    source = (SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8")
    assert "def estimated_triangle_count" in source
    assert "def normalize_derived_lod_for_budget" in source
    assert 'bmesh.ops.delete(editable, geom=zero_area_faces, context="FACES")' in source
    assert "maximum_triangles = (" in source
    assert "math.ceil(source_triangles * ratio)" in source
    assert "CBM_LOD{level}_BUDGET_CORRECTION" in source
    assert "LOD{level} triangle budget remains exceeded" in source
    assert source.index("target.data = source.data.copy()") < source.index(
        "triangulated_faces, removed_zero_area_faces = "
        "normalize_derived_lod_for_budget("
    )


def test_prepare_script_batches_only_semantic_owned_derived_objects() -> None:
    """Keep V0.7.3 batching derived-only, lossless, and stable-ID traceable."""

    source = (SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8")
    assert "def consolidate_semantic_batches" in source
    assert 'role not in {"render", "lod"}' in source
    assert 'semantic_id = str(obj.get("cbm_id"))' in source
    assert "triangles_after != triangles_before" in source
    assert 'target["cbm_batch_source_objects"]' in source
    assert "deduplicate_exact_colliders" in source


def test_prepare_script_reports_overlap_and_instances_without_destructive_claims() -> None:
    """Treat overlap and instancing as advisory evidence until an engine adapter exists."""

    source = (SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8")
    assert "def detect_exact_instances" in source
    assert "def detect_overlap_candidates" in source
    assert '"action": "report_only"' in source
    assert "Internal and coplanar hidden faces remain unclassified" in source
    assert "Estimated draw calls are material-slot proxies" in source


def test_export_evidence_is_distinct_and_records_portability_limits() -> None:
    """Keep raw Blender evidence distinct from the authoritative host package contract."""

    source = (SCRIPT_ROOT / "export_portable_package.py").read_text(encoding="utf-8")
    assert '"kind": "portable_export_evidence"' in source
    assert '"file_metadata_verified": False' in source
    assert '"path_mode": "COPY"' in source
    assert source.count('"path_mode": "COPY"') >= 2
    assert '"path_mode": "STRIP"' in source
    assert '"embed_textures": False' in source
    assert '"use_metadata": False' in source
    assert "sanitize_fbx_absolute_paths(" in source
    assert "data.count(original)" in source
    assert "FBX path sanitizer left an expected absolute path" in source
    assert "_same_length_relative_path" in source
    assert "raw PBR " in source
    assert "sidecars remain authoritative" in source


def test_export_script_rejects_tagged_boolean_helpers_in_render_roles() -> None:
    """Block old or tampered optimized scenes from exporting cutter solids."""

    source = (SCRIPT_ROOT / "export_portable_package.py").read_text(encoding="utf-8")
    assert "def object_source_tags" in source
    assert 'NON_RENDER_BOOLEAN_TAG = "hidden-boolean-target"' in source
    assert 'bool(obj.get("cbm_source_hide_render", False))' in source
    assert "if unsafe_helpers:" in source
    assert "Portable export scene contains canonical non-render helpers" in source


def test_fbx_export_promotes_portable_atlas_to_uv0_and_exports_tangents() -> None:
    """Bind portable atlas textures and normal-map tangents to FBX TEXCOORD_0."""

    source = (SCRIPT_ROOT / "export_portable_package.py").read_text(encoding="utf-8")
    assert "def normalize_fbx_uv_bindings" in source
    assert "def normalize_portable_uv_bindings" in source
    assert '"required_uv_channel_index": 0' in source
    assert '"destination_semantic": "TEXCOORD_0"' in source
    assert '"tangent_uv_set": atlas_uv_set' in source
    assert '"use_tspace": True' in source
    assert "Blender FBX exporter exposes no tangent-space export option" in source
    assert source.index("normalize_portable_uv_bindings(") < source.index(
        "sanitize_export_custom_properties(selected)"
    )


def test_glb_export_verifies_file_level_texcoord0_and_tangent_attributes() -> None:
    """Require converted glTF materials and primitives to expose portable UV0 evidence."""

    source = (SCRIPT_ROOT / "export_portable_package.py").read_text(encoding="utf-8")
    assert "def verify_gltf_texture_coordinate_binding" in source
    assert "gltf_material_textureinfo_texcoord0" in source
    assert "TEXCOORD_0" in source
    assert "TANGENT" in source
    assert 'if args.format in {"glb", "gltf"}:' in source


def test_gltf_uv0_file_verifier_accepts_complete_portable_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Accept an exact converted material, TEXCOORD_0, and tangent binding."""

    module = load_export_script(monkeypatch)
    document, contract = _gltf_uv0_fixture()
    path = tmp_path / "asset.gltf"
    path.write_text(json.dumps(document), encoding="utf-8")
    result = module.verify_gltf_texture_coordinate_binding(path, "gltf", contract)
    assert result["status"] == "verified"
    assert result["verified_texture_binding_count"] == 2
    assert result["verified_primitive_count"] == 1


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("missing_index", "exact integer texture index"),
        ("string_index", "exact integer texture index"),
        ("bool_index", "exact integer texture index"),
        ("nonzero_transform_texcoord", "TEXCOORD_0"),
        ("missing_texcoord0", "no TEXCOORD_0"),
        ("missing_tangent", "no TANGENT"),
        ("untextured_converted_material", "no texture bindings"),
        ("format_mismatch", "contract format differs"),
    ],
)
def test_gltf_uv0_file_verifier_rejects_incomplete_or_mismatched_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    """Fail closed for malformed TextureInfo, geometry binding, or format evidence."""

    module = load_export_script(monkeypatch)
    document, contract = _gltf_uv0_fixture()
    normal = document["materials"][0]["normalTexture"]
    primitive = document["meshes"][0]["primitives"][0]
    if case == "missing_index":
        del normal["index"]
    elif case == "string_index":
        normal["index"] = "0"
    elif case == "bool_index":
        normal["index"] = True
    elif case == "nonzero_transform_texcoord":
        normal["extensions"] = {"KHR_texture_transform": {"texCoord": 2}}
    elif case == "missing_texcoord0":
        del primitive["attributes"]["TEXCOORD_0"]
    elif case == "missing_tangent":
        del primitive["attributes"]["TANGENT"]
    elif case == "untextured_converted_material":
        document["materials"].append({"extras": {"cbm_id": "mat.trim"}})
        document["meshes"][0]["primitives"].append(
            {
                "material": 1,
                "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
            }
        )
        contract["objects"][0]["material_ids"].append("mat.trim")
    elif case == "format_mismatch":
        contract["export_format"] = "glb"
    path = tmp_path / "asset.gltf"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeError, match=message):
        module.verify_gltf_texture_coordinate_binding(path, "gltf", contract)


def test_roundtrip_hard_gates_portable_uv_binding_and_loop_association() -> None:
    """Keep strict FBX identity and explicit glTF semantic-binding verification."""

    source = (SCRIPT_ROOT / "validate_export_roundtrip.py").read_text(
        encoding="utf-8"
    )
    assert "vertex_uv_binding_fingerprint_preserved" in source
    assert "def portable_uv_binding_readiness" in source
    assert "portable material UV0/tangent binding failed" in source
    assert "glTF_file_texcoord0_plus_imported_uv0_summary" in source
    assert "has no verified export UV0 binding contract" in source
    assert "manifest_import_format_mismatch" in source
    assert "export_contract_format_mismatch" in source
    assert '"portable_uv_binding": {' in source


def test_roundtrip_uv_policy_rejects_manifest_cli_and_contract_format_confusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject mismatched importer, manifest, and verified UV-contract formats."""

    module = load_roundtrip_script(monkeypatch)
    manifest = {
        "format": "glb",
        "uv_binding_contract": {
            "status": "verified",
            "export_format": "fbx",
            "required_uv_set": "CBMPortableAtlas",
            "required_uv_channel_index": 0,
        },
    }
    expected = {
        "asset_role": "render",
        "topology": {
            "uv_layers": [{"name": "CBMPortableAtlas", "active_render": True}]
        },
    }
    actual = {
        "topology": {"uv_layers": [{"name": "UVMap", "active_render": True}]}
    }
    uv_readiness = {
        "summary_tolerance": 1e-5,
        "layers": [
            {
                "non_finite_coordinate_count": 0,
                "bounds_max_abs_error": 0.0,
                "total_area_abs_error": 0.0,
            }
        ],
    }
    tangent = {"status": "ready", "uv_set": "UVMap"}
    importer_mismatch = module.portable_uv_binding_readiness(
        manifest,
        expected,
        actual,
        uv_readiness,
        tangent,
        format_name="fbx",
    )
    contract_mismatch = module.portable_uv_binding_readiness(
        manifest,
        expected,
        actual,
        uv_readiness,
        tangent,
        format_name="glb",
    )
    assert importer_mismatch["reason"] == "manifest_import_format_mismatch"
    assert contract_mismatch["reason"] == "export_contract_format_mismatch"


def test_obj_export_preserves_portable_material_identity_uv_and_dependencies() -> None:
    """OBJ adapts stable IDs, active UV0, and image sidecars to its legacy contract."""

    source = (SCRIPT_ROOT / "export_portable_package.py").read_text(encoding="utf-8")
    assert "def normalize_obj_material_names" in source
    assert 'material_id = str(material.get("cbm_id") or material.name)' in source
    assert "def stage_obj_image_dependencies" in source
    assert "shutil.copy2(source, target)" in source
    assert "def export_object_inventory" in source
    assert 'serialized["name"] = "UVMap"' in source
    assert 'topology["uv_layers"] = [serialized]' in source
    assert "OBJ preserves only the active render UV set" in source


def test_portable_export_sanitizes_authoring_metadata_before_export() -> None:
    """Portable primary files retain stable IDs but exclude authoring-only metadata."""

    source = (SCRIPT_ROOT / "export_portable_package.py").read_text(encoding="utf-8")
    assert "sanitize_export_custom_properties(selected)" in source
    assert 'PORTABLE_MATERIAL_PROPERTIES = frozenset({"cbm_id"})' in source
    assert '"policy": "portable_identity_whitelist"' in source


def test_roundtrip_tangent_calculation_errors_fail_validation() -> None:
    """A present tangent API that raises is a validation failure, not a warning."""

    source = (SCRIPT_ROOT / "validate_export_roundtrip.py").read_text(encoding="utf-8")
    error_block = source.split(
        "except (AttributeError, RuntimeError, TypeError, ValueError) as exc:", 1
    )[1].split("finally:", 1)[0]
    assert '"status": "failed"' in error_block
    assert '"reason": "tangent_calculation_error"' in error_block


def test_roundtrip_tangent_uv_contract_rejects_missing_or_ambiguous_layers() -> None:
    """Normal-map UV declarations cannot silently fall back to another imported UV set."""

    source = (SCRIPT_ROOT / "validate_export_roundtrip.py").read_text(encoding="utf-8")
    assert '"reason": "declared_normal_uv_missing"' in source
    assert '"reason": "declared_normal_uv_ambiguous"' in source
    assert source.index("if material_uv_sets:") < source.index(
        'selection_basis = "active_render_fallback"'
    )


def test_portable_export_binds_the_exact_input_blend_hash() -> None:
    """Export validates the loaded derivative before and after writing a package asset."""

    source = (SCRIPT_ROOT / "export_portable_package.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--expected-input-blend-sha256", required=True)' in source
    assert "Loaded portable input blend SHA-256 does not match" in source
    assert "Portable input blend changed while the export was running" in source


def test_roundtrip_validator_requires_package_root_and_honest_readiness() -> None:
    """Clean imports bind dependencies to the package and avoid unsupported claims."""

    source = (SCRIPT_ROOT / "validate_export_roundtrip.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--package-root", required=True)' in source
    assert 'expected_manifest.get("kind") != "portable_export_evidence"' in source
    assert "package_dependency_path(raw, package_root)" in source
    assert '"custom_normal_equivalence_verified": False' in source
    assert '"preserved_exported_tangents_verified": False' in source
    assert '"loop_association_verified": not uv_association_unverified_objects' in source
    assert '"axis_file_metadata_verified": False' in source
    assert '"unit_file_metadata_verified": False' in source
    assert 'node.type == "NORMAL_MAP"' in source
    assert '"material_normal_map"' in source


def test_runtime_scripts_do_not_reference_reserved_first_test_job() -> None:
    """Reusable V0.7 Blender scripts remain independent of historical test workspaces."""

    for name in SCRIPT_NAMES:
        source = (SCRIPT_ROOT / name).read_text(encoding="utf-8")
        assert "first_reference_test" not in source
