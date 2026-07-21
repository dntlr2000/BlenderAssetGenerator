from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

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
    assert '"loop_association_verified": False' in source
    assert '"axis_file_metadata_verified": False' in source
    assert '"unit_file_metadata_verified": False' in source
    assert 'node.type == "NORMAL_MAP"' in source
    assert '"material_normal_map"' in source


def test_runtime_scripts_do_not_reference_reserved_first_test_job() -> None:
    """Reusable V0.7 Blender scripts remain independent of historical test workspaces."""

    for name in SCRIPT_NAMES:
        source = (SCRIPT_ROOT / name).read_text(encoding="utf-8")
        assert "first_reference_test" not in source
