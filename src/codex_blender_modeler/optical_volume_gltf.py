"""Bounded read-only glTF volume factors and object/primitive ownership verification."""

from __future__ import annotations

import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from .optical_volume import validate_optical_volume


def f32(value: float) -> float:
    """Return the exact pinned native socket projection."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _unique(pairs):
    """Reject duplicate JSON keys rather than select conflicting serialized meanings."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate optical glTF JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    """Reject nonstandard JSON numeric constants."""
    raise ValueError("Nonfinite optical glTF JSON constant: " + value)


def load_optical_gltf(path: Path, format_name: str) -> dict[str, Any]:
    """Read one bounded complete container without fetching any external dependency."""
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Optical export exceeds the inspection byte budget")
    data = path.read_bytes()
    if len(data) > 64 * 1024 * 1024:
        raise ValueError("Optical export exceeds the inspection byte budget")
    if format_name == "glb":
        if len(data) < 20 or struct.unpack_from("<III", data) != (0x46546C67, 2, len(data)):
            raise ValueError("Invalid complete optical GLB2 container")
        offset = 12
        chunks = []
        while offset < len(data):
            if offset + 8 > len(data):
                raise ValueError("Truncated optical GLB chunk")
            size, kind = struct.unpack_from("<II", data, offset)
            offset += 8
            if size % 4 or offset + size > len(data):
                raise ValueError("Invalid optical GLB chunk bounds")
            chunks.append((kind, data[offset : offset + size]))
            offset += size
        if not chunks or chunks[0][0] != 0x4E4F534A or len(chunks) > 2:
            raise ValueError("Unsupported optical GLB chunk structure")
        if len(chunks) == 2 and chunks[1][0] != 0x004E4942:
            raise ValueError("Invalid optical GLB binary chunk")
        data = chunks[0][1]
    elif format_name != "gltf":
        raise ValueError("Optical-volume verification requires glTF")
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("Optical glTF JSON exceeds inspection budget")
    result = json.loads(data, object_pairs_hook=_unique, parse_constant=_invalid_constant)
    if not isinstance(result, dict):
        raise ValueError("Optical glTF root must be an object")
    return result


def _number(value: Any, label: str) -> float:
    """Read a finite numeric literal without bool/string coercion."""
    if type(value) not in (int, float):
        raise ValueError("Invalid optical glTF numeric literal: " + label)
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError("Invalid optical glTF numeric literal: " + label) from error
    if not math.isfinite(result):
        raise ValueError("Invalid optical glTF numeric literal: " + label)
    return result


def _index(value: Any, values: list, label: str) -> int:
    """Check an actual serialized table reference."""
    if type(value) is not int or not 0 <= value < len(values):
        raise ValueError("Invalid optical glTF index: " + label)
    return value


def _array(value: Any, label: str) -> list:
    """Bound metadata traversal independently of source producer behavior."""
    if not isinstance(value, list) or len(value) > 100000:
        raise ValueError("Invalid or unbounded optical glTF array: " + label)
    return value


def _object(value: Any, label: str) -> dict:
    """Require metadata records rather than permitting ambiguous malformed extensions."""
    if not isinstance(value, dict):
        raise ValueError("Invalid optical glTF object: " + label)
    return value


def verify_optical_document(document: dict, expected: list[dict]) -> list[dict]:
    """Verify exact surface/volume constants and each real object-to-primitive assignment."""
    _object(document, "root")
    materials = _array(document.get("materials", []), "materials")
    nodes = _array(document.get("nodes", []), "nodes")
    meshes = _array(document.get("meshes", []), "meshes")
    accessors = _array(document.get("accessors", []), "accessors")
    expected_by_object = {}
    expected_by_material = {}
    for row in expected:
        if row["object"] in expected_by_object:
            raise ValueError("Ambiguous expected optical object identity")
        expected_by_object[row["object"]] = row
        previous = expected_by_material.setdefault(row["material"], row)
        if previous["contract"] != row["contract"] or previous["surface"] != row["surface"]:
            raise ValueError("Conflicting expected optical material semantics")
    material_names = Counter(
        m.get("name") for m in materials if isinstance(m, dict) and isinstance(m.get("name"), str)
    )
    active = {}
    for i, material in enumerate(materials):
        if not isinstance(material, dict):
            raise ValueError("Invalid optical glTF material")
        extensions = _object(material.get("extensions", {}), "material extensions")
        volume = extensions.get("KHR_materials_volume")
        if "KHR_materials_volume" in extensions:
            volume = _object(volume, "volume")
        if volume is not None and _number(volume.get("thicknessFactor", 0), "thickness") > 0:
            name = material.get("name")
            if not isinstance(name, str) or name in active or material_names[name] != 1:
                raise ValueError("Ambiguous serialized optical material identity")
            active[name] = i
    if set(active) != set(expected_by_material):
        raise ValueError("Exported volume materials lack exact validated boundary coverage")
    if not expected:
        return []
    declarations = _array(document.get("extensionsUsed", []), "extensionsUsed")
    if any(not isinstance(name, str) for name in declarations) or len(set(declarations)) != len(
        declarations
    ):
        raise ValueError("Invalid optical glTF extension declarations")
    if "KHR_materials_volume" not in declarations:
        raise ValueError("Export omitted the optical-volume extension declaration")
    if document.get("animations") or document.get("skins"):
        raise ValueError("Optical-volume export requires a static unskinned document")
    rows = []
    for name, wanted in expected_by_material.items():
        material = materials[active[name]]
        ext = material.get("extensions", {})
        if set(ext) - set(declarations):
            raise ValueError("Export omitted a used optical material extension declaration")
        if {"KHR_materials_unlit", "KHR_materials_pbrSpecularGlossiness"}.intersection(ext):
            raise ValueError("Optical volume acquired an incompatible material extension")
        actual = ext["KHR_materials_volume"]
        contract = validate_optical_volume(wanted["contract"])
        distance = contract["attenuation_distance"]
        projected = {
            "thicknessFactor": f32(contract["thickness_factor"]),
            "attenuationColor": [f32(x) for x in contract["attenuation_color"]],
            "attenuationDistance": None if distance is None else 1 / f32(1 / distance),
        }
        if "thicknessTexture" in actual:
            raise ValueError("Constant optical volume acquired a thickness texture")
        if _number(actual.get("thicknessFactor", 0), "thickness") != projected["thicknessFactor"]:
            raise ValueError("Exported optical thickness changed")
        color = actual.get("attenuationColor", [1, 1, 1])
        if (
            not isinstance(color, list)
            or len(color) != 3
            or [_number(x, "attenuation color") for x in color] != projected["attenuationColor"]
        ):
            raise ValueError("Exported optical attenuation color changed")
        actual_distance = (
            _number(actual["attenuationDistance"], "attenuation distance")
            if "attenuationDistance" in actual
            else None
        )
        if actual_distance != projected["attenuationDistance"]:
            raise ValueError("Exported optical attenuation distance changed")
        transmission = _object(ext.get("KHR_materials_transmission", {}), "transmission")
        if "transmissionTexture" in transmission:
            raise ValueError("Constant optical transmission acquired a texture")
        surface = wanted["surface"]
        if (
            _number(transmission.get("transmissionFactor", 0), "transmission")
            != surface["transmission"]
        ):
            raise ValueError("Exported optical transmission changed")
        ior = _object(ext.get("KHR_materials_ior", {}), "IOR")
        if _number(ior.get("ior", 1.5), "IOR") != surface["ior"]:
            raise ValueError("Exported optical IOR changed")
        pbr = _object(material.get("pbrMetallicRoughness", {}), "PBR")
        if _number(pbr.get("metallicFactor", 1), "metallic") != 0:
            raise ValueError("Exported optical dielectric lost metallic zero")
        rgba = pbr.get("baseColorFactor", [1, 1, 1, 1])
        if not isinstance(rgba, list) or len(rgba) != 4 or _number(rgba[3], "alpha") != 1:
            raise ValueError("Exported optical alpha changed")
        if material.get("alphaMode", "OPAQUE") != "OPAQUE":
            raise ValueError("Exported optical alpha coverage is not opaque")
        rows.append(
            {
                "material": name,
                "requested_contract": contract,
                "actual_glTF_volume": actual,
                "native_scalar_projection": projected,
                "surface": surface,
                "serialized_factors_verified": True,
                "serialized_material_usage_verified": True,
                "destination_support_verified": False,
                "object_usage": [],
            }
        )
    # Walk every declared scene to reject unreachable evidence and unexpected optical users.
    reachable = set()
    pending = []
    for scene in _array(document.get("scenes", []), "scenes"):
        pending.extend(_array(_object(scene, "scene").get("nodes", []), "scene nodes"))
    while pending:
        i = _index(pending.pop(), nodes, "scene node")
        if i in reachable:
            continue
        reachable.add(i)
        pending.extend(_array(_object(nodes[i], "node").get("children", []), "node children"))
        if len(pending) > 200000:
            raise ValueError("Optical node traversal budget exceeded")
    actual_objects = set()
    for i in sorted(reachable):
        node = nodes[i]
        if "mesh" not in node:
            continue
        mesh_index = _index(node["mesh"], meshes, "node mesh")
        mesh = _object(meshes[mesh_index], "mesh")
        primitives = _array(mesh.get("primitives", []), "primitives")
        used = [_object(p, "primitive").get("material") for p in primitives]
        optical = [m for m in used if m in active.values()]
        wanted = expected_by_object.get(node.get("name"))
        if not optical and wanted is None:
            continue
        if wanted is None or node.get("name") in actual_objects or not primitives:
            raise ValueError("Unexpected or ambiguous optical object usage")
        if any(type(m) is not int or m != active[wanted["material"]] for m in used):
            raise ValueError("Optical object primitives changed material assignment")
        if "skin" in node or "weights" in node or "weights" in mesh:
            raise ValueError("Optical boundary acquired a skin or morph weights")
        count = 0
        for primitive in primitives:
            if primitive.get("targets"):
                raise ValueError("Optical boundary acquired morph targets")
            if primitive.get("mode", 4) != 4:
                raise ValueError("Optical boundary must serialize as triangles")
            index = primitive.get("indices", primitive.get("attributes", {}).get("POSITION"))
            accessor = _object(accessors[_index(index, accessors, "triangle accessor")], "accessor")
            n = accessor.get("count")
            if type(n) is not int or n <= 0 or n % 3:
                raise ValueError("Invalid optical serialized triangle count")
            count += n // 3
        if count != wanted["triangles"]:
            raise ValueError("Serialized optical object triangle count changed")
        actual_objects.add(node["name"])
        next(r for r in rows if r["material"] == wanted["material"])["object_usage"].append(
            {
                "object": node["name"],
                "node_index": i,
                "mesh_index": mesh_index,
                "primitive_count": len(primitives),
                "triangles": count,
            }
        )
    if actual_objects != set(expected_by_object):
        raise ValueError("Expected optical objects are missing from actual scene usage")
    return rows
