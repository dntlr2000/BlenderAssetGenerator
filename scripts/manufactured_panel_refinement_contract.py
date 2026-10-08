"""Pure-Python closed data contract for manufactured-panel refinement staging."""

import hashlib
import json
import math
from pathlib import Path


class RecipeError(ValueError):
    """An input is stale, ambiguous, outside the bounded scope, or malformed."""


def sha(path):
    """Return the exact SHA-256 of a readable source file."""
    path = Path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise RecipeError("Source exceeds 32 MiB staging bound")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact(value, keys, label):
    """Require an object with no omitted or additional keys."""
    if not isinstance(value, dict) or set(value) != set(keys):
        raise RecipeError(f"{label}: unexpected fields")


def number(value, lower, upper, label):
    """Accept only finite bounded JSON numbers, excluding booleans."""
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
        raise RecipeError(f"{label}: out of range")


def vector(value, width, lower, upper, label):
    """Validate an exact-width numeric vector with bounded components."""
    if not isinstance(value, list) or len(value) != width:
        raise RecipeError(f"{label}: wrong vector size")
    for item in value:
        number(item, lower, upper, label)


def contained(root, relative):
    """Reject absolute paths, traversal, symlink escape, and missing source files."""
    if (
        not isinstance(relative, str)
        or "\\" in relative
        or ":" in relative
        or relative.startswith("/")
        or any(x in ("", ".", "..") for x in relative.split("/"))
    ):
        raise RecipeError("Invalid relative path")
    candidate = root / relative
    for entry in (candidate, *candidate.parents):
        if entry == root:
            break
        if entry.is_symlink():
            raise RecipeError("Linked source is not permitted")
    path = candidate.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise RecipeError("Missing or escaped source")
    return path


def _validate_recipe(root):
    """Validate every operation, source binding and parameter without bpy or mutation."""
    root = Path(root).resolve()
    r = read_json(contained(root, "refinement_recipe.json"))
    exact(
        r,
        {
            "schema_version",
            "kind",
            "inputs",
            "source_scene_sha256",
            "reference_sha256",
            "edge_roll",
            "edge_roll_overrides",
            "core",
            "sight_mount",
            "grip_backstrap",
            "material_surface_overrides",
            "limits",
            "weld_tolerance_m",
            "edge_segments_by_id",
            "section_rebuilds",
            "stock_inlay_reseat",
        },
        "recipe",
    )
    if r["schema_version"] != "0.1.0" or r["kind"] != "manufactured_panel_refinement":
        raise RecipeError("Unknown recipe version/kind")
    if (
        sha(contained(root, "sources/baseline_scene_spec.json")) != r["source_scene_sha256"]
        or sha(contained(root, "input/reference.png")) != r["reference_sha256"]
    ):
        raise RecipeError("Stale source/reference")
    spec = read_json(contained(root, "sources/baseline_scene_spec.json"))
    if not isinstance(spec, dict) or not 1 <= len(spec["objects"]) <= 256:
        raise RecipeError("Invalid source object count")
    ids = {o["id"] for o in spec["objects"]}
    materials = {m["id"] for m in spec["materials"]}
    if len(ids) != len(spec["objects"]) or not 1 <= len(materials) <= 256:
        raise RecipeError("Ambiguous source identities")
    if len(materials) != len(spec["materials"]):
        raise RecipeError("Duplicate material identities")
    for field in (
        "inputs",
        "edge_roll_overrides",
        "edge_segments_by_id",
        "section_rebuilds",
        "material_surface_overrides",
    ):
        if not isinstance(r[field], dict):
            raise RecipeError("Invalid mapping: " + field)
    if set(r["inputs"]) != ids:
        raise RecipeError("Semantic coverage mismatch")
    for row in r["inputs"].values():
        exact(row, {"path", "sha256"}, "input")
        if sha(contained(root, row["path"])) != row["sha256"]:
            raise RecipeError("Stale geometry")
    number(r["weld_tolerance_m"], 0, 1e-5, "weld tolerance")
    e = r["edge_roll"]
    exact(e, {"width_m", "segments", "angle_degrees", "clamp_overlap"}, "edge roll")
    number(e["width_m"], 0.001, 0.05, "width")
    number(e["angle_degrees"], 20, 90, "angle")
    if (
        type(e["segments"]) is not int
        or not 1 <= e["segments"] <= 4
        or e["clamp_overlap"] is not True
    ):
        raise RecipeError("Invalid bevel segments/clamp")
    for sid, value in r["edge_roll_overrides"].items():
        if sid not in ids:
            raise RecipeError("Unknown edge target")
        number(value, 0.001, e["width_m"], "edge override")
    if set(r["edge_segments_by_id"]) != ids:
        raise RecipeError("Edge segment coverage mismatch")
    for value in r["edge_segments_by_id"].values():
        if type(value) is not int or not 1 <= value <= 4:
            raise RecipeError("Invalid local edge segments")
    for sid, section in r["section_rebuilds"].items():
        if sid not in ids:
            raise RecipeError("Unknown section target")
        if section.get("kind") == "source_profile":
            exact(
                section,
                {"kind", "indices", "half_depth", "bevel_width", "segments"},
                "source profile",
            )
            source = read_json(contained(root, r["inputs"][sid]["path"]))
            if (
                not isinstance(section["indices"], list)
                or not 3 <= len(section["indices"]) <= 16
                or any(
                    type(i) is not int or not 0 <= i < len(source["vertices"])
                    for i in section["indices"]
                )
            ):
                raise RecipeError("Bad profile index")
            number(section["half_depth"], 0.1, 0.6, "profile depth")
        elif section.get("kind") == "annular_x":
            exact(
                section,
                {"kind", "outer_yz", "inner_yz", "x_range", "bevel_width", "segments"},
                "annular section",
            )
            if len(section["outer_yz"]) != 8 or len(section["inner_yz"]) != 8:
                raise RecipeError("Annular section size")
            for point in section["outer_yz"] + section["inner_yz"]:
                vector(point, 2, -10, 10, "annular point")
            vector(section["x_range"], 2, -10, 10, "annular X")
            if section["x_range"][0] >= section["x_range"][1]:
                raise RecipeError("Annular order")
        else:
            raise RecipeError("Unknown section recipe")
        number(section["bevel_width"], 0.01, 0.16, "section bevel")
        if type(section["segments"]) is not int or not 1 <= section["segments"] <= 3:
            raise RecipeError("Section segments")
    t = r["stock_inlay_reseat"]
    exact(
        t, {"semantic_id", "start_index", "end_index", "xz_center", "xz_scale", "z_offset"}, "inlay"
    )
    if t["semantic_id"] not in ids:
        raise RecipeError("Inlay target")
    count = len(read_json(contained(root, r["inputs"][t["semantic_id"]]["path"]))["vertices"])
    if (
        type(t["start_index"]) is not int
        or type(t["end_index"]) is not int
        or not 0 <= t["start_index"] < t["end_index"] <= count
    ):
        raise RecipeError("Inlay range")
    vector(t["xz_center"], 2, -10, 10, "inlay center")
    number(t["xz_scale"], 0.8, 1, "inlay scale")
    number(t["z_offset"], -0.05, 0.05, "inlay shift")
    c = r["core"]
    exact(
        c,
        {
            "semantic_id",
            "x_sections",
            "radius_factors",
            "center_y",
            "center_z",
            "radius_y",
            "radius_z",
            "radial_segments",
        },
        "core",
    )
    if (
        c["semantic_id"] not in ids
        or type(c["radial_segments"]) is not int
        or c["radial_segments"] != 12
    ):
        raise RecipeError("Invalid core target/segments")
    vector(c["x_sections"], 4, -10, 10, "core X")
    vector(c["radius_factors"], 4, 0.1, 1, "core radii")
    if any(b <= a for a, b in zip(c["x_sections"], c["x_sections"][1:], strict=False)):
        raise RecipeError("Core sections not ordered")
    number(c["center_y"], -10, 10, "center")
    number(c["center_z"], -10, 10, "center")
    number(c["radius_y"], 0.01, 0.2, "Y radius")
    number(c["radius_z"], 0.01, 0.3, "Z radius")
    s = r["sight_mount"]
    exact(
        s,
        {"semantic_id", "housing_restore", "rail_x", "rail_half_depth", "bottom_z", "height"},
        "sight",
    )
    if s["semantic_id"] not in ids:
        raise RecipeError("Unknown sight target")
    source = read_json(contained(root, r["inputs"][s["semantic_id"]]["path"]))
    for i, p in s["housing_restore"].items():
        if not i.isdigit() or not 0 <= int(i) < len(source["vertices"]):
            raise RecipeError("Invalid vertex index")
        vector(p, 3, -10, 10, "restored vertex")
    vector(s["rail_x"], 2, -10, 10, "rail X")
    vector(s["bottom_z"], 2, -10, 10, "rail Z")
    number(s["rail_half_depth"], 0.05, 0.5, "rail depth")
    number(s["height"], 0.05, 0.3, "rail height")
    if s["rail_x"][0] >= s["rail_x"][1]:
        raise RecipeError("Invalid rail direction")
    t = r["grip_backstrap"]
    exact(t, {"semantic_id", "profile_xz", "half_depth"}, "trim")
    if (
        t["semantic_id"] not in ids
        or not isinstance(t["profile_xz"], list)
        or not 3 <= len(t["profile_xz"]) <= 16
    ):
        raise RecipeError("Invalid trim target/profile")
    for p in t["profile_xz"]:
        vector(p, 2, -10, 10, "trim point")
    number(t["half_depth"], 0.01, 0.25, "trim depth")
    if set(r["material_surface_overrides"]) != materials:
        raise RecipeError("Material coverage mismatch")
    for m in r["material_surface_overrides"].values():
        allowed = {"base_color", "roughness", "metallic", "emission_color", "emission_strength"}
        if not {"base_color", "roughness", "metallic"} <= set(m) <= allowed:
            raise RecipeError("Unknown material operation")
        vector(m["base_color"], 4, 0, 1, "base color")
        number(m["roughness"], 0.05, 1, "roughness")
        number(m["metallic"], 0, 1, "metallic")
        if "emission_color" in m:
            vector(m["emission_color"], 4, 0, 1, "emission color")
        if "emission_strength" in m:
            number(m["emission_strength"], 0, 1, "emission strength")
    if (
        not isinstance(r["limits"], list)
        or len(r["limits"]) > 64
        or not all(isinstance(x, str) and len(x) <= 4096 for x in r["limits"])
    ):
        raise RecipeError("Invalid limits")
    return r


def _object_pairs(pairs):
    """Reject duplicate keys before recipe semantics can become ambiguous."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecipeError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def _reject_constant(value):
    """Exclude JSON extensions for nonfinite constants."""
    raise RecipeError("Nonfinite JSON constant: " + value)


def read_json(path):
    """Read at most 32 MiB of strict UTF-8 JSON with no duplicate keys."""
    path = Path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise RecipeError("JSON exceeds 32 MiB staging bound")
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_object_pairs,
        parse_constant=_reject_constant,
    )


def validate_recipe(root):
    """Validate fail-closed recipe data without granting canonical execution authority."""
    try:
        return _validate_recipe(root)
    except RecipeError:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
        RecursionError,
        OverflowError,
    ) as error:
        raise RecipeError("Malformed or unavailable staging dependency") from error
