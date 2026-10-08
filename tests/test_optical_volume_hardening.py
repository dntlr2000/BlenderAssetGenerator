"""Counterexample regressions for strict opt-in factors and serialized boundary ownership."""

import json
import math
import struct
from pathlib import Path

import jsonschema
import pytest

from codex_blender_modeler.materials.models import ShaderRecipe
from codex_blender_modeler.optical_volume_gltf import (
    f32,
    load_optical_gltf,
    verify_optical_document,
)
from codex_blender_modeler.optimization.models import PortableSurfaceFactors
from codex_blender_modeler.packaging.material_conversion import _surface_factors
from codex_blender_modeler.shader_recipe_runtime import _validate_recipe


def contract():
    """Supply an explicitly complete constant volume."""
    return {
        "schema_version": "0.1.0",
        "thickness_factor": 0.2,
        "attenuation_distance": None,
        "attenuation_color": [1, 1, 1],
    }


def factors():
    """Supply required optical scalar literals rather than inherit metallic defaults."""
    return {
        "metallic_factor": 0,
        "alpha_factor": 1,
        "transmission_factor": 0.9,
        "optical_volume": contract(),
    }


@pytest.mark.parametrize("key", ["metallic_factor", "alpha_factor", "transmission_factor"])
def test_optical_factor_omissions_fail_host_schema_normalization(key):
    """Defaults never silently restore omitted opt-in dielectric intent."""
    raw = factors()
    raw.pop(key)
    for validate in (PortableSurfaceFactors.model_validate, _surface_factors):
        with pytest.raises(ValueError):
            validate(raw)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, PortableSurfaceFactors.model_json_schema())


@pytest.mark.parametrize(
    "key,bad",
    [
        ("metallic_factor", 1),
        ("metallic_factor", False),
        ("metallic_factor", "0"),
        ("alpha_factor", 0.5),
        ("alpha_factor", True),
        ("transmission_factor", 0),
        ("transmission_factor", "0.9"),
        ("roughness_factor", True),
        ("base_color_factor", [1, 1, 1, 0.5]),
        ("emission_factor", [1, "1", 1]),
    ],
)
def test_optical_factor_restrictions_match_all_public_paths(key, bad):
    """Versioned companions cannot exploit legacy scalar coercion or schema omissions."""
    raw = factors()
    raw[key] = bad
    for validate in (PortableSurfaceFactors.model_validate, _surface_factors):
        with pytest.raises(ValueError):
            validate(raw)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, PortableSurfaceFactors.model_json_schema())


@pytest.mark.parametrize("bad", [math.inf, math.nan, 10**1000])
def test_optical_factor_nonfinite_values_fail_closed(bad):
    """Non-JSON infinities and overflowing Python literals never escape as optics."""
    raw = factors()
    raw["roughness_factor"] = bad
    for validate in (PortableSurfaceFactors.model_validate, _surface_factors):
        with pytest.raises(ValueError):
            validate(raw)


def test_legacy_factor_coercion_and_serialization_stay_unchanged():
    """Opt-in strictness leaves existing absent/null companion scalar behavior intact."""
    for companion in ({}, {"optical_volume": None}):
        raw = {"metallic_factor": "0.7", "transmission_factor": "0.25", **companion}
        result = _surface_factors(raw).model_dump(mode="json")
        assert result["metallic_factor"] == 0.7 and result["transmission_factor"] == 0.25
        assert "optical_volume" not in result


@pytest.mark.parametrize(
    "key,bad", [("base_color", [-1, 1, 1, 1]), ("emission_color", [1, -1, 1, 1]), ("base_color", 1)]
)
def test_recipe_color_shape_and_domain_match_native_host_schema(key, bad):
    """New recipe color restrictions are consistent while legacy models retain their shape."""
    raw = ShaderRecipe(material_id="glass").model_dump(mode="json")
    raw.update(schema_version="0.5.1", volume=contract())
    raw["surface"].update(transmission_weight=0.9)
    raw["surface"][key] = bad
    for validate in (
        ShaderRecipe.model_validate,
        lambda data: _validate_recipe(data, "glass", Path("test.json"), "none"),
    ):
        with pytest.raises(ValueError):
            validate(raw)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, ShaderRecipe.model_json_schema())


def document_and_expected():
    """Build the smallest actual glTF ownership chain with explicit volume surface factors."""
    document = {
        "asset": {"version": "2.0"},
        "extensionsUsed": [
            "KHR_materials_volume",
            "KHR_materials_transmission",
            "KHR_materials_ior",
        ],
        "materials": [
            {
                "name": "glass",
                "pbrMetallicRoughness": {"metallicFactor": 0},
                "extensions": {
                    "KHR_materials_volume": {"thicknessFactor": f32(0.2)},
                    "KHR_materials_transmission": {"transmissionFactor": f32(0.9)},
                    "KHR_materials_ior": {"ior": f32(1.46)},
                },
            }
        ],
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Cube", "mesh": 0}],
        "meshes": [{"primitives": [{"material": 0, "indices": 0}]}],
        "accessors": [{"count": 36}],
    }
    expected = [
        {
            "object": "Cube",
            "material": "glass",
            "contract": contract(),
            "surface": {"ior": f32(1.46), "transmission": f32(0.9), "metallic": 0, "alpha": 1},
            "triangles": 12,
        }
    ]
    return document, expected


def test_serialized_optics_bind_real_usage_and_default_semantics():
    """One actual ownership chain and glTF omission defaults produce a truthful receipt."""
    document, expected = document_and_expected()
    result = verify_optical_document(document, expected)
    assert result[0]["object_usage"][0]["triangles"] == 12
    assert result[0]["destination_support_verified"] is False
    expected[0]["surface"]["ior"] = 1.5
    del document["materials"][0]["extensions"]["KHR_materials_ior"]
    assert verify_optical_document(document, expected)


@pytest.mark.parametrize(
    "case",
    [
        "ior",
        "transmission",
        "metallic",
        "missing_metallic",
        "alpha",
        "alpha_mode",
        "thickness_texture",
        "transmission_texture",
        "null_distance",
        "opaque_assignment",
        "missing_object",
        "unexpected_optical_user",
        "triangle_loss",
        "missing_volume",
        "missing_scene",
    ],
)
def test_serialized_counterexamples_fail_even_when_volume_factors_match(case):
    """Correct extension numbers alone cannot claim the actual material and boundary survived."""
    document, expected = document_and_expected()
    material = document["materials"][0]
    ext = material["extensions"]
    if case == "ior":
        del ext["KHR_materials_ior"]
    elif case == "transmission":
        ext["KHR_materials_transmission"]["transmissionFactor"] = 0.1
    elif case == "metallic":
        material["pbrMetallicRoughness"]["metallicFactor"] = 1
    elif case == "missing_metallic":
        del material["pbrMetallicRoughness"]["metallicFactor"]
    elif case == "alpha":
        material["pbrMetallicRoughness"]["baseColorFactor"] = [1, 1, 1, 0.5]
    elif case == "alpha_mode":
        material["alphaMode"] = "BLEND"
    elif case == "thickness_texture":
        ext["KHR_materials_volume"]["thicknessTexture"] = {"index": 0}
    elif case == "transmission_texture":
        ext["KHR_materials_transmission"]["transmissionTexture"] = {"index": 0}
    elif case == "null_distance":
        ext["KHR_materials_volume"]["attenuationDistance"] = None
    elif case == "opaque_assignment":
        document["materials"].append({"name": "opaque"})
        document["meshes"][0]["primitives"][0]["material"] = 1
    elif case == "missing_object":
        document["nodes"][0]["name"] = "Different"
    elif case == "unexpected_optical_user":
        document["nodes"].append({"name": "Extra", "mesh": 0})
        document["scenes"][0]["nodes"].append(1)
    elif case == "triangle_loss":
        document["accessors"][0]["count"] = 6
    elif case == "missing_volume":
        del ext["KHR_materials_volume"]
    elif case == "missing_scene":
        document["scenes"] = []
    with pytest.raises(ValueError):
        verify_optical_document(document, expected)


def test_loader_checks_complete_glb_and_duplicate_json_keys(tmp_path):
    """Container parsing never accepts ambiguous JSON or a truncated GLB."""
    document, _ = document_and_expected()
    data = json.dumps(document).encode()
    data += b" " * (-len(data) % 4)
    glb = struct.pack("<III", 0x46546C67, 2, 20 + len(data))
    glb += struct.pack("<II", len(data), 0x4E4F534A) + data
    path = tmp_path / "good.glb"
    path.write_bytes(glb)
    assert load_optical_gltf(path, "glb") == document
    path.write_bytes(glb[:-1])
    with pytest.raises(ValueError):
        load_optical_gltf(path, "glb")
    path = tmp_path / "bad.gltf"
    path.write_text('{"materials":[],"materials":[]}')
    with pytest.raises(ValueError):
        load_optical_gltf(path, "gltf")


def test_schema_checked_in_optical_factor_projection():
    """Public generated conversion schema embeds the actual strict portable factor schema."""
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "schemas/portable_material_conversion_manifest.schema.json").read_text()
    )
    assert (
        schema["$defs"]["PortableSurfaceFactors"]["allOf"]
        == PortableSurfaceFactors.model_json_schema()["allOf"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("animations", [{"channels": []}]),
        ("skins", [{"joints": []}]),
    ],
)
def test_optical_serialization_rejects_nonstatic_transport(field, value):
    """The initial optical subset never treats rig or animation transport as static proof."""
    document, expected = document_and_expected()
    document[field] = value
    with pytest.raises(ValueError, match="static unskinned"):
        verify_optical_document(document, expected)


@pytest.mark.parametrize("field,value", [("extensions", None), ("pbrMetallicRoughness", None)])
def test_malformed_optical_records_fail_with_bounded_diagnostics(field, value):
    """Malformed serialized record types cannot be interpreted as omitted defaults."""
    document, expected = document_and_expected()
    document["materials"][0][field] = value
    with pytest.raises(ValueError, match="Invalid optical glTF object"):
        verify_optical_document(document, expected)


@pytest.mark.parametrize(
    "extension", ["KHR_materials_volume", "KHR_materials_transmission", "KHR_materials_ior"]
)
def test_optical_extensions_require_actual_declarations(extension):
    """An extension object cannot silently exist outside the glTF extensionsUsed declaration."""
    document, expected = document_and_expected()
    document["extensionsUsed"].remove(extension)
    with pytest.raises(ValueError, match="extension declaration"):
        verify_optical_document(document, expected)


@pytest.mark.parametrize(
    "extension", ["KHR_materials_unlit", "KHR_materials_pbrSpecularGlossiness"]
)
def test_optical_material_exclusions_are_enforced(extension):
    """A transmitting volume cannot also claim unlit or legacy specular-glossiness semantics."""
    document, expected = document_and_expected()
    document["extensionsUsed"].append(extension)
    document["materials"][0]["extensions"][extension] = {}
    with pytest.raises(ValueError, match="incompatible material extension"):
        verify_optical_document(document, expected)
