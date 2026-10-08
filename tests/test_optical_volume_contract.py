"""Opt-in volume contracts preserve legacy bytes and reject unsupported transport."""

import copy
import json
import math
from pathlib import Path

import jsonschema
import pytest

from codex_blender_modeler.materials.models import ShaderRecipe
from codex_blender_modeler.optical_volume import validate_optical_volume, validate_volume_recipe
from codex_blender_modeler.optical_volume_models import OpticalVolumeSpec
from codex_blender_modeler.optimization.models import PortableSurfaceFactors
from codex_blender_modeler.packaging.material_conversion import _surface_factors
from codex_blender_modeler.shader_recipe_runtime import _validate_recipe


def volume():
    """Provide all explicit versioned constant-volume fields."""
    return {
        "schema_version": "0.1.0",
        "thickness_factor": 0.2,
        "attenuation_distance": 2.5,
        "attenuation_color": [0.7, 0.9, 0.8],
    }


def recipe():
    """Derive an explicitly opted-in transmissive recipe from the unchanged legacy defaults."""
    raw = ShaderRecipe(material_id="glass").model_dump(mode="json")
    raw.update(schema_version="0.5.1", volume=volume())
    raw["surface"]["transmission_weight"] = 0.95
    return raw


def test_legacy_default_recipe_serialization_has_no_new_field():
    """Old default recipe data roundtrips without a volume key or new version."""
    raw = ShaderRecipe(material_id="a").model_dump(mode="json")
    assert raw["schema_version"] == "0.5.0" and "volume" not in raw
    assert ShaderRecipe.model_validate_json(json.dumps(raw)).model_dump(mode="json") == raw
    assert _validate_recipe(raw, "a", Path("a.json"), "none")["schema_version"] == "0.5.0"


def test_opt_in_host_native_and_schema_agree():
    """The same exact new JSON is accepted by typed host, standard-library native and schema."""
    raw = recipe()
    before = copy.deepcopy(raw)
    typed = ShaderRecipe.model_validate(raw)
    native = _validate_recipe(raw, "glass", Path("glass.json"), "none")
    assert typed.model_dump(mode="json") == raw and native["volume"] == raw["volume"]
    jsonschema.validate(raw, ShaderRecipe.model_json_schema())
    assert raw == before


@pytest.mark.parametrize("version", ["0.5.0", "0.5.2", "", None])
def test_other_recipe_versions_cannot_claim_volume(version):
    """Version dispatch never silently activates or migrates a volume recipe."""
    raw = recipe()
    raw["schema_version"] = version
    for validate in [ShaderRecipe.model_validate, validate_volume_recipe]:
        with pytest.raises(ValueError):
            validate(raw)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, ShaderRecipe.model_json_schema())


@pytest.mark.parametrize("key", ["volume", "schema_version"])
def test_new_recipe_requires_explicit_version_and_volume(key):
    """Absent companion or absent explicit opt-in must not inherit permission to change optics."""
    raw = recipe()
    raw.pop(key)
    with pytest.raises(ValueError):
        ShaderRecipe.model_validate(raw)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, ShaderRecipe.model_json_schema())


@pytest.mark.parametrize("value", [None, {}, True, "volume"])
def test_null_or_unstructured_volume_rejected(value):
    """New version0.5.1 requires a bounded literal volume record."""
    raw = recipe()
    raw["volume"] = value
    with pytest.raises(ValueError):
        ShaderRecipe.model_validate(raw)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, ShaderRecipe.model_json_schema())


@pytest.mark.parametrize(
    "field,bad",
    [
        ("thickness_factor", 0),
        ("thickness_factor", -1),
        ("thickness_factor", 1e7),
        ("thickness_factor", True),
        ("thickness_factor", "0.2"),
        ("thickness_factor", math.nan),
        ("attenuation_distance", 0),
        ("attenuation_distance", math.inf),
        ("attenuation_color", [1, 1]),
        ("attenuation_color", [0, 1, 1]),
        ("attenuation_color", [True, 1, 1]),
        ("attenuation_color", [1.01, 1, 1]),
        ("schema_version", "0.2.0"),
    ],
)
def test_invalid_volume_domain_fails_identically(field, bad):
    """Strict scalar/color bounds cannot be repaired or coerced by the host model."""
    raw = volume()
    raw[field] = bad
    with pytest.raises(ValueError):
        validate_optical_volume(raw)
    with pytest.raises(ValueError):
        OpticalVolumeSpec.model_validate(raw)


def test_missing_unknown_fields_and_unbounded_attenuation():
    """All fields are explicit; null distance is the declared infinite-distance representation."""
    raw = volume()
    raw["attenuation_distance"] = None
    assert OpticalVolumeSpec.model_validate(raw).attenuation_distance is None
    raw["callback"] = "forbidden"
    with pytest.raises(ValueError):
        validate_optical_volume(raw)
    raw = volume()
    raw.pop("attenuation_color")
    with pytest.raises(ValueError):
        validate_optical_volume(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("transmission_weight", 0),
        ("transmission_weight", True),
        ("transmission_weight", math.nan),
        ("metallic", 0.2),
        ("metallic", False),
        ("alpha", 0.5),
        ("alpha", True),
        ("ior", 0.9),
        ("ior", math.inf),
    ],
)
def test_optical_surface_restrictions_are_explicit(field, value):
    """The initial volume subset requires a nonmetallic alpha-one transmitting dielectric."""
    raw = recipe()
    raw["surface"][field] = value
    with pytest.raises(ValueError):
        ShaderRecipe.model_validate(raw)
    with pytest.raises(ValueError):
        _validate_recipe(raw, "glass", Path("glass.json"), "none")
    if not isinstance(value, float) or math.isfinite(value):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(raw, ShaderRecipe.model_json_schema())


def test_legacy_portable_factors_are_byte_shape_compatible():
    """Absent optical companion does not introduce null into existing0.7.0 evidence."""
    raw = PortableSurfaceFactors().model_dump(mode="json")
    assert "optical_volume" not in raw
    assert _surface_factors(raw).model_dump(mode="json") == raw


def test_portable_factors_preserve_the_whole_volume_companion():
    """Constant thickness/attenuation survive host normalization rather than disappear."""
    raw = PortableSurfaceFactors(transmission_factor=0.9, metallic_factor=0.0).model_dump(
        mode="json"
    )
    raw["optical_volume"] = volume()
    assert _surface_factors(raw).model_dump(mode="json") == raw


def test_checked_in_shader_schema_contains_exact_opt_in():
    """The generated public schema remains synchronized with actual version dispatch."""
    root = Path(__file__).resolve().parents[1]
    actual = json.loads((root / "schemas/shader_recipe.schema.json").read_text())
    assert actual == ShaderRecipe.model_json_schema()


@pytest.mark.parametrize("field", ["metallic", "alpha", "ior", "transmission_weight"])
def test_new_optics_require_explicit_critical_surface_fields(field):
    """Host/native/schema cannot disagree through different legacy fallback defaults."""
    raw = recipe()
    raw["surface"].pop(field)
    with pytest.raises(ValueError):
        ShaderRecipe.model_validate(raw)
    with pytest.raises(ValueError):
        _validate_recipe(raw, "glass", Path("glass.json"), "none")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, ShaderRecipe.model_json_schema())


@pytest.mark.parametrize("family", ["emissive", "rock", "water"])
def test_disallowed_optical_families_have_schema_parity(family):
    """Experimental homogeneous dielectric transport does not activate other shader families."""
    raw = recipe()
    raw["family"] = family
    with pytest.raises(ValueError):
        ShaderRecipe.model_validate(raw)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, ShaderRecipe.model_json_schema())


def test_volume_recipe_layers_are_rejected_by_schema_and_host():
    """The initial opt-in branch does not borrow procedural-layer authority."""
    raw = recipe()
    raw["layers"] = [{"id": "noise", "kind": "noise"}]
    with pytest.raises(ValueError):
        ShaderRecipe.model_validate(raw)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, ShaderRecipe.model_json_schema())
