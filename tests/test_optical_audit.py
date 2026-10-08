"""Exact-byte optical diagnostics distinguish thin transmission from volume intent."""

import copy
import hashlib
import json
import math
import struct

import pytest

from codex_blender_modeler.packaging import optical_audit as a


def glb(document, binary=None):
    """Build a complete deterministic GLB test container with actual four-byte padding."""
    data = json.dumps(document, separators=(",", ":")).encode()
    data += b" " * (-len(data) % 4)
    chunks = struct.pack("<II", len(data), 0x4E4F534A) + data
    if binary is not None:
        binary += b"\0" * (-len(binary) % 4)
        chunks += struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<III", 0x46546C67, 2, len(chunks) + 12) + chunks


def inspect(document, binary=None):
    """Bind each test to the exact constructed GLB digest."""
    data = glb(document, binary)
    return a.inspect_glb_optical_materials(data, expected_sha256=hashlib.sha256(data).hexdigest())


def fixture():
    """Supply legal glTF optical extension names and default-dependent records."""
    return {
        "asset": {"version": "2.0"},
        "extensionsUsed": [a._TRANSMISSION],
        "materials": [
            {"name": "glass", "extensions": {a._TRANSMISSION: {"transmissionFactor": 0.9}}}
        ],
    }


def test_thin_glass_is_not_volume_refraction_evidence():
    """Nonzero transmission and a closed-looking render cannot imply serialized volume."""
    result = inspect(fixture())
    row = result["materials"][0]
    assert row["optical_mode"] == "thin_walled_transmission_declared"
    assert row["thickness_factor_mesh_units"] == 0 and row["ior"] == 1.5
    assert "volumetric refraction is not declared" in " ".join(row["limitations"])
    for key in (
        "actual_import_verified",
        "destination_support_verified",
        "geometry_verified",
        "rendered_refraction_verified",
        "acceptance_authority",
    ):
        assert result[key] is False


def test_volume_parameters_are_intent_not_native_or_engine_proof():
    """Preserve thickness/attenuation and identify geometry duty without a support claim."""
    d = fixture()
    d["extensionsUsed"] += [a._VOLUME, a._IOR]
    d["extensionsRequired"] = [a._VOLUME]
    d["materials"][0]["extensions"].update(
        {
            a._VOLUME: {
                "thicknessFactor": 0.12,
                "attenuationDistance": 3.5,
                "attenuationColor": [0.7, 1, 0.8],
            },
            a._IOR: {"ior": 1.46},
        }
    )
    before = copy.deepcopy(d)
    row = inspect(d, b"abc")["materials"][0]
    assert row["optical_mode"] == "volume_transmission_declared"
    assert row["requires_manifold_boundary"] is True
    assert row["thickness_factor_mesh_units"] == 0.12
    assert row["attenuation_distance_world_units"] == 3.5
    assert row["attenuation_distance_unbounded"] is False
    assert row["attenuation_color"] == [0.7, 1, 0.8] and row["ior"] == 1.46
    assert d == before


@pytest.mark.parametrize("volume", [{}, {"thicknessFactor": 0}])
def test_zero_volume_remains_thin(volume):
    """Extension presence alone does not enable volumetric behavior."""
    d = fixture()
    d["extensionsUsed"].append(a._VOLUME)
    d["materials"][0]["extensions"][a._VOLUME] = volume
    assert inspect(d)["materials"][0]["optical_mode"] == "thin_walled_transmission_declared"


def test_no_supported_transmission_stays_unresolved():
    """A volume without supported transmission is not silently interpreted as glass."""
    d = {
        "asset": {"version": "2.0"},
        "extensionsUsed": [a._VOLUME],
        "materials": [{"extensions": {a._VOLUME: {"thicknessFactor": 1}}}],
    }
    row = inspect(d)["materials"][0]
    assert row["optical_mode"] == "volume_declared_without_supported_transmission"
    assert row["attenuation_distance_unbounded"] is True
    assert row["attenuation_distance_world_units"] is None


def test_texture_modulation_is_not_measured_thickness():
    """Keep exact texture info without fetching images or assuming channel values."""
    d = fixture()
    d["textures"] = [{}]
    d["materials"][0]["extensions"][a._TRANSMISSION]["transmissionTexture"] = {
        "index": 0,
        "texCoord": 1,
        "extensions": {"KHR_texture_transform": {"texCoord": 2, "scale": [2, 1]}},
    }
    row = inspect(d)["materials"][0]
    tex = row["transmission_texture"]
    assert tex["texcoord"] == 1
    assert tex["serialized_texture_info"]["extensions"]["KHR_texture_transform"]["texCoord"] == 2
    assert tex["pixels_and_uv_support_verified"] is False
    assert "Texture modulation is not evaluated" in " ".join(row["limitations"])


@pytest.mark.parametrize("bad", [True, False, "0.9", None, -0.1, 1.01, math.inf, math.nan])
def test_bad_transmission_fails_without_coercion_or_clamp(bad):
    """Malformed transport cannot become usable audit evidence."""
    d = fixture()
    d["materials"][0]["extensions"][a._TRANSMISSION]["transmissionFactor"] = bad
    with pytest.raises(ValueError):
        inspect(d)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("thicknessFactor", -1),
        ("thicknessFactor", True),
        ("attenuationDistance", 0),
        ("attenuationDistance", None),
        ("attenuationColor", [1, 1]),
        ("attenuationColor", [1, -0.01, 1]),
        ("attenuationColor", [True, 1, 1]),
        ("thicknessTexture", {"index": 0}),
        ("thicknessTexture", None),
    ],
)
def test_malformed_volume_fields_fail(field, bad):
    """Preserve strict numeric and reference semantics in every interpreted volume field."""
    d = fixture()
    d["extensionsUsed"].append(a._VOLUME)
    d["materials"][0]["extensions"][a._VOLUME] = {field: bad}
    with pytest.raises(ValueError):
        inspect(d)


@pytest.mark.parametrize("value", [0, 1, 1.5, 3])
def test_special_ior_zero_and_valid_values_are_retained(value):
    """The specification's zero IOR special case is not silently clamped to one."""
    d = fixture()
    d["extensionsUsed"].append(a._IOR)
    d["materials"][0]["extensions"][a._IOR] = {"ior": value}
    assert inspect(d)["materials"][0]["ior"] == value


@pytest.mark.parametrize("value", [-1, 0.5, True, None, "1.5"])
def test_invalid_ior_fails(value):
    """Do not manufacture an index of refraction from malformed intent."""
    d = fixture()
    d["extensionsUsed"].append(a._IOR)
    d["materials"][0]["extensions"][a._IOR] = {"ior": value}
    with pytest.raises(ValueError):
        inspect(d)


def test_extension_declarations_must_be_consistent():
    """Missing used declarations and required-only features cannot look portable."""
    d = fixture()
    d["extensionsUsed"] = []
    with pytest.raises(ValueError, match="missing"):
        inspect(d)
    d = fixture()
    d["extensionsRequired"] = [a._VOLUME]
    with pytest.raises(ValueError, match="Required"):
        inspect(d)


@pytest.mark.parametrize(
    "transform",
    [
        lambda x: x[:-1],
        lambda x: x + b"tail",
        lambda x: b"oops" + x[4:],
        lambda x: x[:4] + struct.pack("<I", 1) + x[8:],
        lambda x: x[:12] + struct.pack("<I", 2**31) + x[16:],
    ],
)
def test_malformed_containers_fail_even_with_matching_hash(transform):
    """A digest proves identity, not structural validity or complete chunk boundaries."""
    data = transform(glb(fixture()))
    with pytest.raises(ValueError):
        a.inspect_glb_optical_materials(data, expected_sha256=hashlib.sha256(data).hexdigest())


def test_hash_mismatch_and_mutable_bytes_fail():
    """Bind exact immutable evidence before interpreting optical fields."""
    data = glb(fixture())
    with pytest.raises(ValueError, match="hash mismatch"):
        a.inspect_glb_optical_materials(data, expected_sha256="0" * 64)
    with pytest.raises(ValueError):
        a.inspect_glb_optical_materials(
            bytearray(data), expected_sha256=hashlib.sha256(data).hexdigest()
        )


def test_duplicate_json_keys_fail():
    """Ambiguous duplicate fields do not silently choose a favorable volume value."""
    raw = b'{"asset":{"version":"2.0"},"materials":[],"materials":[]}'
    raw += b" " * (-len(raw) % 4)
    data = struct.pack("<5I", 0x46546C67, 2, len(raw) + 20, len(raw), 0x4E4F534A) + raw
    with pytest.raises(ValueError, match="duplicate"):
        a.inspect_glb_optical_materials(data, expected_sha256=hashlib.sha256(data).hexdigest())


def test_empty_materials_are_empty_evidence():
    """A legal material-free document yields no invented optical assignment."""
    result = inspect({"asset": {"version": "2.0"}})
    assert result["materials"] == [] and result["scope"] == "all_serialized_materials"


@pytest.mark.parametrize("excluded", ["KHR_materials_unlit", "KHR_materials_pbrSpecularGlossiness"])
@pytest.mark.parametrize("optical", [a._TRANSMISSION, a._VOLUME, a._IOR])
def test_excluded_material_models_do_not_yield_optical_claim(excluded, optical):
    """The interpreted Khronos extensions exclude unlit and legacy specular-glossiness."""
    d = {
        "asset": {"version": "2.0"},
        "extensionsUsed": [optical, excluded],
        "materials": [{"extensions": {optical: {}, excluded: {}}}],
    }
    with pytest.raises(ValueError, match="excluded"):
        inspect(d)


def test_overflow_in_uninterpreted_extras_cannot_poison_report():
    """JSON exponent overflow is rejected even beyond the known optical scalar fields."""
    raw = b'{"asset":{"version":"2.0"},"extras":{"overflow":1e999}}'
    raw += b" " * (-len(raw) % 4)
    data = struct.pack("<5I", 0x46546C67, 2, len(raw) + 20, len(raw), 0x4E4F534A) + raw
    with pytest.raises(ValueError, match="overflow"):
        a.inspect_glb_optical_materials(data, expected_sha256=hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize(
    "name,value",
    [
        ("materials", [None]),
        ("materials", None),
        ("textures", None),
        ("extensionsUsed", [a._TRANSMISSION, a._TRANSMISSION]),
        ("extensionsRequired", [True]),
    ],
)
def test_malformed_top_level_records_fail(name, value):
    """Bounded interpreted records must retain their declared JSON types."""
    d = fixture()
    d[name] = value
    with pytest.raises(ValueError):
        inspect(d)


def test_material_limit_is_fail_closed(monkeypatch):
    """Exhausting explicit material count cannot yield a partial favorable report."""
    monkeypatch.setattr(a, "_MAX_MATERIALS", 1)
    d = fixture()
    d["materials"] *= 2
    with pytest.raises(ValueError, match="material count"):
        inspect(d)
