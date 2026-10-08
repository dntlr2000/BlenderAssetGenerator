"""Read-only optical semantics from exact GLB bytes, without rendering or acceptance claims."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from typing import Any

_MAX_GLB_BYTES = 64 * 1024 * 1024
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_MATERIALS = 4096
_TRANSMISSION = "KHR_materials_transmission"
_VOLUME = "KHR_materials_volume"
_IOR = "KHR_materials_ior"
_MISSING = object()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys instead of silently choosing competing semantics."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Optical audit JSON has duplicate keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    """Refuse non-JSON numeric constants before interpreting optical factors."""
    raise ValueError(f"Optical audit contains nonfinite constant: {value}")


def _json_float(value: str) -> float:
    """Reject numeric overflow anywhere in JSON, including uninterpreted extras."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Optical audit JSON numeric overflow")
    return number


def _number(value: Any, name: str, low: float, high: float | None = None) -> float:
    """Read a finite literal scalar without bool/string coercion or clamping."""
    if type(value) not in (int, float):
        raise ValueError(f"Invalid optical scalar: {name}")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"Invalid optical scalar: {name}") from error
    if not math.isfinite(number) or number < low or (high is not None and number > high):
        raise ValueError(f"Invalid optical scalar: {name}")
    return number


def _object(value: Any, name: str) -> dict[str, Any]:
    """Require a JSON object for every interpreted extension record."""
    if not isinstance(value, dict):
        raise ValueError(f"Invalid optical object: {name}")
    return value


def _names(value: Any, name: str) -> list[str]:
    """Validate bounded unique extension names while preserving their serialized order."""
    if (
        not isinstance(value, list)
        or len(value) > 256
        or any(not isinstance(item, str) or not 1 <= len(item) <= 256 for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"Invalid extension list: {name}")
    return value


def _texture(value: Any, textures: list[Any], name: str) -> dict[str, Any] | None:
    """Inspect texture references only; no external URI or pixel is fetched or evaluated."""
    if value is _MISSING:
        return None
    record = _object(value, name)
    index = record.get("index")
    texcoord = record.get("texCoord", 0)
    if type(index) is not int or not 0 <= index < len(textures):
        raise ValueError(f"Invalid optical texture index: {name}")
    if type(texcoord) is not int or not 0 <= texcoord <= 2**31 - 1:
        raise ValueError(f"Invalid optical texture coordinate: {name}")
    return {
        "index": index,
        "texcoord": texcoord,
        "serialized_texture_info": record,
        "pixels_and_uv_support_verified": False,
    }


def _document(data: bytes) -> dict[str, Any]:
    """Validate a bounded complete GLB2 container before parsing its unique JSON chunk."""
    if type(data) is not bytes or not 20 <= len(data) <= _MAX_GLB_BYTES:
        raise ValueError("Optical audit requires bounded immutable GLB bytes")
    magic, version, length = struct.unpack_from("<III", data)
    if (magic, version, length) != (0x46546C67, 2, len(data)):
        raise ValueError("Optical audit requires an exact complete GLB2 container")
    offset = 12
    chunks: list[tuple[int, bytes]] = []
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("Optical audit GLB chunk header is incomplete")
        size, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        if size % 4 or offset + size > len(data) or len(chunks) >= 2:
            raise ValueError("Optical audit GLB chunk range is invalid or unsupported")
        chunks.append((kind, data[offset : offset + size]))
        offset += size
    if (
        not chunks
        or chunks[0][0] != 0x4E4F534A
        or (len(chunks) == 2 and chunks[1][0] != 0x004E4942)
        or len(chunks[0][1]) > _MAX_JSON_BYTES
    ):
        raise ValueError("Optical audit supports one JSON and optional BIN chunk")
    try:
        document = json.loads(
            chunks[0][1],
            object_pairs_hook=_unique,
            parse_constant=_reject_constant,
            parse_float=_json_float,
        )
    except (RecursionError, UnicodeDecodeError) as error:
        raise ValueError("Optical audit JSON is invalid or too deeply nested") from error
    document = _object(document, "document")
    if _object(document.get("asset"), "asset").get("version") != "2.0":
        raise ValueError("Optical audit requires glTF asset version 2.0")
    return document


def inspect_glb_optical_materials(data: bytes, *, expected_sha256: str) -> dict[str, Any]:
    """Report serialized transmission/volume intent; never assert beauty or engine support.

    The caller supplies actual GLB bytes and an independently expected digest.
    This opt-in helper has no canonical writer, renderer, importer or approval role.
    Nonzero volume thickness requires closed manifold geometry, checked elsewhere.
    """
    if (
        not isinstance(expected_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
    ):
        raise ValueError("Optical audit requires an exact lowercase SHA-256")
    if type(data) is not bytes or len(data) > _MAX_GLB_BYTES:
        raise ValueError("Optical audit requires bounded immutable GLB bytes")
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise ValueError("Optical audit GLB hash mismatch")
    document = _document(data)
    used = _names(document.get("extensionsUsed", []), "extensionsUsed")
    required = _names(document.get("extensionsRequired", []), "extensionsRequired")
    if not set(required).issubset(used):
        raise ValueError("Required GLB extensions must be declared used")
    materials = document.get("materials", [])
    textures = document.get("textures", [])
    if not isinstance(materials, list) or len(materials) > _MAX_MATERIALS:
        raise ValueError("Optical audit material count is invalid or unsupported")
    if not isinstance(textures, list) or len(textures) > 65536:
        raise ValueError("Optical audit texture count is invalid or unsupported")
    rows = []
    for index, raw in enumerate(materials):
        material = _object(raw, "material")
        extensions = _object(material.get("extensions", {}), "material.extensions")
        for name in (_TRANSMISSION, _VOLUME, _IOR):
            if name in extensions and name not in used:
                raise ValueError(f"Optical extension missing from extensionsUsed: {name}")
        if any(name in extensions for name in (_TRANSMISSION, _VOLUME, _IOR)) and any(
            name in extensions
            for name in ("KHR_materials_unlit", "KHR_materials_pbrSpecularGlossiness")
        ):
            raise ValueError("Optical extensions conflict with an excluded material model")
        transmission = _object(extensions.get(_TRANSMISSION, {}), _TRANSMISSION)
        volume = _object(extensions.get(_VOLUME, {}), _VOLUME)
        ior = _object(extensions.get(_IOR, {}), _IOR)
        factor = _number(transmission.get("transmissionFactor", 0.0), "transmissionFactor", 0, 1)
        thickness = _number(volume.get("thicknessFactor", 0.0), "thicknessFactor", 0)
        refractive_index = _number(ior.get("ior", 1.5), "ior", 0)
        if 0 < refractive_index < 1:
            raise ValueError("IOR must be zero or at least one")
        attenuation = volume.get("attenuationDistance")
        if "attenuationDistance" in volume:
            attenuation = _number(attenuation, "attenuationDistance", 0)
            if attenuation == 0:
                raise ValueError("attenuationDistance must be strictly positive")
        color = volume.get("attenuationColor", [1.0, 1.0, 1.0])
        if not isinstance(color, list) or len(color) != 3:
            raise ValueError("attenuationColor must have three components")
        color = [_number(value, "attenuationColor", 0, 1) for value in color]
        transmission_texture = _texture(
            transmission.get("transmissionTexture", _MISSING), textures, "transmissionTexture"
        )
        thickness_texture = _texture(
            volume.get("thicknessTexture", _MISSING), textures, "thicknessTexture"
        )
        if factor > 0 and thickness > 0:
            mode = "volume_transmission_declared"
        elif factor > 0:
            mode = "thin_walled_transmission_declared"
        elif thickness > 0:
            mode = "volume_declared_without_supported_transmission"
        else:
            mode = "no_supported_optical_transport_declared"
        limitations = ["Serialized factors do not verify renderer or destination importer support."]
        if factor > 0 and thickness == 0:
            limitations.append(
                "No nonzero volume thickness: volumetric refraction is not declared."
            )
        if thickness > 0:
            limitations.append(
                "Closed manifold boundary and physical thickness are not verified here."
            )
        if transmission_texture or thickness_texture:
            limitations.append(
                "Texture modulation is not evaluated; factors are not measured transport."
            )
        name = material.get("name")
        if "name" in material and not isinstance(name, str):
            raise ValueError("Material name must be a string when present")
        rows.append(
            {
                "material_index": index,
                "name": name,
                "optical_mode": mode,
                "transmission_factor": factor,
                "ior": refractive_index,
                "thickness_factor_mesh_units": thickness,
                "attenuation_distance_world_units": attenuation,
                "attenuation_distance_unbounded": attenuation is None,
                "attenuation_color": color,
                "transmission_texture": transmission_texture,
                "thickness_texture": thickness_texture,
                "serialized_optical_extensions": {
                    name: extensions[name]
                    for name in (_TRANSMISSION, _VOLUME, _IOR)
                    if name in extensions
                },
                "requires_manifold_boundary": thickness > 0,
                "limitations": limitations,
            }
        )
    return {
        "kind": "serialized_glb_optical_audit_v1",
        "source_sha256": digest,
        "source_bytes": len(data),
        "scope": "all_serialized_materials",
        "extensions_used": used,
        "extensions_required": required,
        "materials": rows,
        "actual_import_verified": False,
        "destination_support_verified": False,
        "geometry_verified": False,
        "rendered_refraction_verified": False,
        "acceptance_authority": False,
    }
