from __future__ import annotations

import hashlib
import json
import math
import os
import re
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from pathlib import Path
from typing import Any


def native_io_path(path: Path) -> str:
    """Use extended Windows filenames for stdlib I/O without changing serialized paths."""

    resolved = os.path.abspath(os.fspath(path.expanduser()))
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


def sha256_file(path: Path) -> str:
    """Hash one native-path conversion input or output without loading it at once."""

    digest = hashlib.sha256()
    with open(native_io_path(path), "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_component(value: str) -> str:
    """Convert one stable material ID into a traversal-safe directory component."""

    if re.fullmatch(r"[A-Za-z0-9._-]+", value) and value not in {".", ".."}:
        return value
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "material"
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{suffix}"


def stable_identifier(value: str, prefix: str) -> str:
    """Create a deterministic V0.7 StableId without filesystem-only underscores."""

    normalized_prefix = re.sub(r"[^A-Za-z0-9.:-]+", ".", prefix).strip(".:-")
    normalized_value = re.sub(r"[^A-Za-z0-9.:-]+", ".", value).strip(".:-")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    base = f"{normalized_prefix}.{normalized_value}" if normalized_value else normalized_prefix
    maximum_base = 127 - len(digest) - 1
    base = base[:maximum_base].rstrip(".:-")
    return f"{base}.{digest}"


def fingerprint_json(value: Any) -> str:
    """Hash one JSON-compatible conversion record using canonical key ordering."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def grid_shape(count: int) -> tuple[int, int]:
    """Return the smallest near-square deterministic atlas grid for an object count."""

    if count < 1:
        raise ValueError("Atlas object count must be positive")
    columns = int(math.ceil(math.sqrt(count)))
    rows = int(math.ceil(count / columns))
    return columns, rows


def atlas_tile_bounds(
    index: int,
    count: int,
    resolution: int,
    margin_px: int,
) -> tuple[float, float, float, float]:
    """Allocate one inset non-overlapping UV tile in stable row-major order."""

    if index < 0 or index >= count:
        raise ValueError(f"Atlas tile index {index} is outside [0, {count})")
    if resolution < 1:
        raise ValueError("Atlas resolution must be positive")
    if margin_px < 0:
        raise ValueError("Atlas margin must be non-negative")
    columns, rows = grid_shape(count)
    column = index % columns
    row = index // columns
    cell_width = 1.0 / columns
    cell_height = 1.0 / rows
    # Reserve the full bake dilation on every tile edge so neighboring margins meet
    # at the cell boundary without writing into another object's usable UV region.
    inset = margin_px / resolution
    if inset * 2.0 >= min(cell_width, cell_height):
        raise ValueError(
            "Atlas resolution is too small for the requested object count and margin"
        )
    return (
        column * cell_width + inset,
        row * cell_height + inset,
        (column + 1) * cell_width - inset,
        (row + 1) * cell_height - inset,
    )


def _area_decimal(value: Any) -> Decimal:
    """Read finite numeric snapshot components without accepting booleans or coercion."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("weighted atlas snapshot coordinates must be finite numbers")
    if not math.isfinite(value):
        raise ValueError("weighted atlas snapshot coordinates must be finite numbers")
    return Decimal(value) if isinstance(value, int) else Decimal.from_float(value)


def _snapshot_surface_area(source: dict[str, Any]) -> Decimal:
    """Measure world-space triangle area from exact stored inputs at fixed Decimal precision."""

    vertices, matrix = source.get("vertices"), source.get("matrix_world")
    loops, triangles = source.get("loops"), source.get("triangles")
    if (
        not isinstance(vertices, list) or not 1 <= len(vertices) <= 500000
        or not isinstance(matrix, (list, tuple)) or len(matrix) != 4
        or any(not isinstance(row, (list, tuple)) or len(row) != 4 for row in matrix)
        or not isinstance(loops, list) or not 3 <= len(loops) <= 500000
        or not isinstance(triangles, list) or not 1 <= len(triangles) <= 250000
    ):
        raise ValueError("weighted atlas requires a complete bounded geometry snapshot")
    transform = [[_area_decimal(value) for value in row] for row in matrix]
    if transform[3] != [0, 0, 0, 1]:
        raise ValueError("weighted atlas requires an affine world matrix")
    world = []
    for vertex in vertices:
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 3:
            raise ValueError("weighted atlas vertex must have three coordinates")
        point = [_area_decimal(value) for value in vertex]
        world.append([
            sum((transform[axis][j] * point[j] for j in range(3)), transform[axis][3])
            for axis in range(3)
        ])
    if any(type(index) is not int or not 0 <= index < len(world) for index in loops):
        raise ValueError("weighted atlas snapshot has an invalid vertex loop index")
    area = Decimal(0)
    for triangle in triangles:
        if (
            not isinstance(triangle, (list, tuple)) or len(triangle) != 3
            or len(set(triangle)) != 3
            or any(type(index) is not int or not 0 <= index < len(loops) for index in triangle)
        ):
            raise ValueError("weighted atlas snapshot has an invalid triangle loop index")
        a, b, c = [world[loops[index]] for index in triangle]
        u = [b[j] - a[j] for j in range(3)]
        v = [c[j] - a[j] for j in range(3)]
        cross = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
                 u[0] * v[1] - u[1] * v[0]]
        squared = sum(value * value for value in cross)
        if not squared.is_finite() or squared <= 0:
            raise ValueError("weighted atlas snapshot contains degenerate world triangles")
        area += squared.sqrt() / 2
    if not area.is_finite() or area <= 0:
        raise ValueError("weighted atlas requires positive finite surface area")
    return area


def resolve_atlas_tiles(
    policy: dict[str, Any], object_count: int,
    source_objects: list[dict[str, Any]] | None = None,
) -> list[tuple[float, float, float, float]]:
    """Resolve legacy grid or opt-in area-weighted pixel rectangles from the bound snapshot.

    Weighted v1 uses Decimal precision 64 and half-even integer splits, one-pixel
    minimum interiors, and no UV-occupancy or reference-importance compensation.
    Return order follows the caller's snapshot; allocation order follows stable IDs.
    """

    strategy = policy.get("tile_strategy", "deterministic_grid")
    resolution, margin = policy.get("resolution"), policy.get("margin_px")
    if strategy == "deterministic_grid":
        return [atlas_tile_bounds(index, object_count, resolution, margin)
                for index in range(object_count)]
    if strategy != "area_weighted_rect_v1":
        raise ValueError("unknown portable atlas tile strategy")
    if policy.get("uv_method") != "validated_authored_uv_v1":
        raise ValueError("area_weighted_rect_v1 requires validated_authored_uv_v1")
    if (
        type(object_count) is not int or not 1 <= object_count <= 256
        or type(resolution) is not int or not 64 <= resolution <= 8192
        or resolution & (resolution - 1)
        or type(margin) is not int or not 1 <= margin <= 1024
        or not isinstance(source_objects, list) or len(source_objects) != object_count
    ):
        raise ValueError("weighted atlas requires a valid policy and complete source snapshot")
    minimum = 2 * margin + 1
    if (resolution // minimum) ** 2 < object_count:
        raise ValueError("weighted atlas capacity cannot preserve pixel margins and interiors")
    if sum(len(item.get("triangles", [])) for item in source_objects) > 1000000:
        raise ValueError("weighted atlas triangle resource limit exceeded")
    result: dict[tuple[str, str, int, str], tuple[float, float, float, float]] = {}
    keys = []
    with localcontext(Context(prec=64, rounding=ROUND_HALF_EVEN)):
        weighted = []
        names = set()
        for source in source_objects:
            identity = source.get("identity", {})
            if any(not isinstance(identity.get(name), str) or not identity[name]
                   for name in ("semantic_id", "source_object", "name")):
                raise ValueError("weighted atlas requires exact stable source identities")
            if type(identity.get("lod_level")) is not int or not 0 <= identity["lod_level"] <= 8:
                raise ValueError("weighted atlas source LOD identity is invalid")
            key = stable_object_key(identity)
            if key in keys or identity["name"] in names:
                raise ValueError("weighted atlas source identities are duplicated")
            keys.append(key)
            names.add(identity["name"])
            weighted.append((key, _snapshot_surface_area(source)))
        weighted.sort(key=lambda item: (-item[1], item[0]))

        def divide(items, rectangle):
            """Partition integer cells with deterministic feasible weighted bisections."""
            x0, y0, x1, y1 = rectangle
            width, height = x1 - x0, y1 - y0
            if len(items) == 1:
                result[items[0][0]] = ((x0 + margin) / resolution, (y0 + margin) / resolution,
                                      (x1 - margin) / resolution, (y1 - margin) / resolution)
                return
            total = sum(item[1] for item in items)
            prefix = Decimal(0)
            candidates = []
            for count in range(1, len(items)):
                prefix += items[count - 1][1]
                fraction = prefix / total
                for axis, length, breadth in ((0, width, height), (1, height, width)):
                    across = breadth // minimum
                    if not across:
                        continue
                    low = ((count + across - 1) // across) * minimum
                    high = length - ((len(items) - count + across - 1) // across) * minimum
                    if low > high:
                        continue
                    cut = max(low, min(high, int((fraction * length).to_integral_value())))
                    # Prefer balanced weight groups and a cut along the longer dimension.
                    score = (abs(fraction - Decimal("0.5")), -length,
                             abs(Decimal(cut) / length - fraction), axis, count)
                    candidates.append((score, axis, count, cut))
            if not candidates:
                raise ValueError(
                    "weighted atlas capacity cannot preserve pixel margins and interiors"
                )
            _, axis, count, cut = min(candidates)
            if axis == 0:
                left, right = (x0, y0, x0 + cut, y1), (x0 + cut, y0, x1, y1)
            else:
                left, right = (x0, y0, x1, y0 + cut), (x0, y0 + cut, x1, y1)
            divide(items[:count], left)
            divide(items[count:], right)

        divide(weighted, (0, 0, resolution, resolution))
    return [result[key] for key in keys]


def blender_relative_path(path: Path, blend_directory: Path) -> str:
    """Serialize one image path using Blender's relocatable double-slash notation."""

    relative = os.path.relpath(path.resolve(), blend_directory.resolve()).replace("\\", "/")
    return f"//{relative}"


def stable_object_key(record: dict[str, Any]) -> tuple[str, str, int, str]:
    """Sort derived render and LOD objects independently of Blender insertion order."""

    return (
        str(record.get("semantic_id") or record.get("cbm_id") or ""),
        str(record.get("source_object") or record.get("cbm_source_object") or ""),
        int(record.get("lod_level") or record.get("cbm_lod_level") or 0),
        str(record.get("name") or ""),
    )


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Publish legacy deterministic JSON atomically through native-path I/O."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    with open(native_io_path(temporary), "w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(native_io_path(temporary), native_io_path(path))
