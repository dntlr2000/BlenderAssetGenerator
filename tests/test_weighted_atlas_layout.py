"""Pure contract tests for the opt-in world-area-weighted portable atlas."""

from __future__ import annotations

from copy import deepcopy
from decimal import ROUND_CEILING, ROUND_FLOOR, localcontext
from itertools import permutations

import pytest
from pydantic import ValidationError

from codex_blender_modeler.blender_scripts import portable_material_conversion_runtime as runtime
from codex_blender_modeler.optimization.models import PortableAtlasPolicy
from codex_blender_modeler.packaging.authored_uv import AuthoredUVInspection

WEIGHTED = "area_weighted_rect_v1"
AUTHORED = "validated_authored_uv_v1"


def _object(name: str, width: float = 1.0, height: float = 1.0) -> dict:
    """Build a complete inspected quad with independently named semantic ownership."""

    return {
        "identity": {
            "name": name,
            "semantic_id": f"asset.{name}",
            "source_object": f"source.{name}",
            "asset_role": "render",
            "lod_level": 0,
            "material_id": "mat.surface",
            "source_material_fingerprint": "a" * 64,
        },
        "vertices": [
            [0.0, 0.0, 0.0], [width, 0.0, 0.0],
            [width, height, 0.0], [0.0, height, 0.0],
        ],
        "matrix_world": [
            [1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0],
        ],
        "polygons": [[0, 1, 2, 3]],
        "polygon_materials": [0],
        "loops": [0, 1, 2, 3],
        "polygon_loops": [[0, 1, 2, 3]],
        "triangles": [[0, 1, 2], [0, 2, 3]],
        "uv_layers": {"Layout": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]},
        "source_uv_set": "Layout",
        "sampling": [],
        "active_uv_set": "Layout",
        "render_uv_set": "Layout",
    }


def _policy(resolution: int = 256, margin_px: int = 2, **changes) -> dict:
    """Select the additive strategy explicitly without changing legacy defaults."""

    return {
        "tile_strategy": WEIGHTED, "uv_method": AUTHORED,
        "resolution": resolution, "margin_px": margin_px, **changes,
    }


def _tiles(objects: list[dict], **policy_changes) -> list[tuple[float, float, float, float]]:
    """Resolve bounds in the caller's object order through the public pure API."""

    return runtime.resolve_atlas_tiles(_policy(**policy_changes), len(objects), objects)


def _pixel_cell(bounds: tuple, resolution: int, margin: int) -> tuple[int, int, int, int]:
    """Recover the complete integer cell including the margin reserved on each edge."""

    pixels = [value * resolution for value in bounds]
    assert all(value == round(value) for value in pixels)
    x0, y0, x1, y1 = (round(value) for value in pixels)
    assert x1 - x0 >= 1 and y1 - y0 >= 1
    return x0 - margin, y0 - margin, x1 + margin, y1 + margin


def _cell_area(bounds: tuple, resolution: int = 256, margin: int = 2) -> int:
    """Measure assigned cell area independently of the usable inset area."""

    x0, y0, x1, y1 = _pixel_cell(bounds, resolution, margin)
    return (x1 - x0) * (y1 - y0)


@pytest.mark.parametrize("count", [1, 2, 3, 17, 256])
@pytest.mark.parametrize("explicit_strategy", [False, True])
def test_legacy_dispatch_preserves_exact_grid_bounds(count, explicit_strategy):
    """Old omitted/default strategy inputs retain exact row-major floating-point results."""

    policy = {"resolution": 2048, "margin_px": 16}
    if explicit_strategy:
        policy["tile_strategy"] = "deterministic_grid"
    expected = [runtime.atlas_tile_bounds(i, count, 2048, 16) for i in range(count)]
    assert runtime.resolve_atlas_tiles(policy, count) == expected


def test_authored_grid_preserves_input_order_and_existing_bounds():
    """Selecting authored UV alone does not enable weighting or reorder legacy allocations."""

    objects = [_object("z", 30.0), _object("a", 1.0)]
    policy = _policy(tile_strategy="deterministic_grid")
    assert runtime.resolve_atlas_tiles(policy, 2, objects) == [
        runtime.atlas_tile_bounds(i, 2, 256, 2) for i in range(2)
    ]


def test_fixture_is_an_authored_uv_inspection_snapshot():
    """Allocation fixtures use actual inspection objects rather than an invented mesh dialect."""

    inspection = AuthoredUVInspection(
        blender_version="5.0.1", blend_sha256="b" * 64, stage="source",
        objects=[_object("small"), _object("large", 3.0)],
    )
    assert len(_tiles(inspection.model_dump(mode="json")["objects"])) == 2


def test_unequal_world_areas_receive_proportional_pixel_cells():
    """An exactly representable three-to-one area ratio receives three-to-one atlas area."""

    small, large = _tiles([_object("a", 1.0), _object("b", 3.0)])
    assert _cell_area(large) == 3 * _cell_area(small)
    assert _cell_area(small) + _cell_area(large) == 256 * 256


def test_world_area_applies_nonuniform_transform_in_the_surface_plane():
    """Surface weighting uses transformed triangle cross products, not local area or volume."""

    transformed = [_object("a"), _object("b")]
    transformed[1]["matrix_world"] = [
        [3.0, 0.0, 0.0, 17.0], [0.0, 2.0, 0.0, -9.0],
        [0.0, 0.0, 23.0, 4.0], [0.0, 0.0, 0.0, 1.0],
    ]
    assert _tiles(transformed) == _tiles([_object("a"), _object("b", 3.0, 2.0)])


def test_rotation_translation_and_reflection_preserve_world_area():
    """Rigid motion and reversed orientation cannot change positive surface-area weights."""

    objects = [_object("a"), _object("b", 3.0)]
    expected = _tiles(objects)
    objects[1]["matrix_world"] = [
        [0.0, -1.0, 0.0, 9.0], [-1.0, 0.0, 0.0, -13.0],
        [0.0, 0.0, 1.0, 12.0], [0.0, 0.0, 0.0, 1.0],
    ]
    assert _tiles(objects) == expected


def test_triangle_indices_address_loops_before_vertices():
    """Equivalent corner storage permutations preserve area despite different loop indices."""

    objects = [_object("a"), _object("b", 5.0, 2.0)]
    expected = _tiles(objects)
    objects[1]["loops"] = [2, 0, 3, 1]
    objects[1]["polygon_loops"] = [[1, 3, 0, 2]]
    objects[1]["triangles"] = [[1, 3, 0], [1, 0, 2]]
    layout = objects[1]["uv_layers"]["Layout"]
    objects[1]["uv_layers"]["Layout"] = [layout[index] for index in [2, 0, 3, 1]]
    assert _tiles(objects) == expected


@pytest.mark.parametrize("widths", [(7.0, 2.0, 3.0), (1.0, 1.0, 1.0)])
def test_semantic_allocations_survive_all_input_permutations_without_mutation(widths):
    """Stable identity decides placement while returned bounds remain aligned with input order."""

    objects = [_object(name, width) for name, width in zip(("c", "a", "b"), widths, strict=True)]
    original = deepcopy(objects)
    expected = dict(zip(
        (o["identity"]["semantic_id"] for o in objects), _tiles(objects), strict=True,
    ))
    for order in permutations(objects):
        reordered = list(order)
        actual = dict(zip(
            (o["identity"]["semantic_id"] for o in reordered), _tiles(reordered), strict=True,
        ))
        assert actual == expected
    assert objects == original


def test_fixed_decimal_precision_is_independent_of_callers_context():
    """Caller precision and rounding settings cannot alter repeatable pixel decisions."""

    objects = [_object("a"), _object("b", 1.7), _object("c", 2.3)]
    objects[0]["vertices"][2][2] = 0.37
    expected = _tiles(objects)
    for precision, rounding in [(2, ROUND_FLOOR), (45, ROUND_CEILING)]:
        with localcontext() as context:
            context.prec = precision
            context.rounding = rounding
            assert _tiles(objects) == expected


@pytest.mark.parametrize("count,resolution,margin", [(1, 64, 3), (7, 64, 2), (16, 128, 4)])
def test_integer_cells_cover_atlas_once_with_full_per_edge_margins(count, resolution, margin):
    """Expanded cells partition every pixel exactly once and retain usable positive interiors."""

    objects = [_object(f"part{i:03d}", float(i + 1)) for i in range(count)]
    bounds = _tiles(objects, resolution=resolution, margin_px=margin)
    occupied = set()
    for tile in bounds:
        x0, y0, x1, y1 = _pixel_cell(tile, resolution, margin)
        assert 0 <= x0 < x1 <= resolution and 0 <= y0 < y1 <= resolution
        cell = {(x, y) for x in range(x0, x1) for y in range(y0, y1)}
        assert not occupied.intersection(cell)
        occupied.update(cell)
    assert len(occupied) == resolution * resolution


def test_tight_capacity_retains_one_pixel_interiors():
    """A three-pixel cell retains a one-pixel interior after full margins on both edges."""

    tiles = _tiles([_object("small", 3.0), _object("large", 61.0)],
                   resolution=64, margin_px=1)
    x0, y0, x1, y1 = _pixel_cell(tiles[0], 64, 1)
    assert sorted((x1 - x0, y1 - y0)) == [3, 64]
    assert _cell_area(tiles[0], 64, 1) + _cell_area(tiles[1], 64, 1) == 64 * 64


@pytest.mark.parametrize("count,resolution,margin", [(1, 64, 32), (17, 64, 8), (225, 64, 2)])
def test_impossible_capacity_fails_instead_of_shrinking_margins(count, resolution, margin):
    """Overfull requests cannot produce zero-size interiors, overlapping cells or less padding."""

    with pytest.raises(ValueError):
        _tiles([_object(f"p{i}") for i in range(count)], resolution=resolution, margin_px=margin)


@pytest.mark.parametrize("changes", [
    {"resolution": 32}, {"resolution": 100}, {"resolution": 16384},
    {"resolution": True}, {"resolution": 256.0},
    {"margin_px": 0}, {"margin_px": -1}, {"margin_px": 1025}, {"margin_px": True},
])
def test_weighted_runtime_rejects_unsupported_pixel_policy(changes):
    """Weighted native-compatible policy requires bounded exact integer pixel settings."""

    with pytest.raises(ValueError):
        _tiles([_object("a")], **changes)


@pytest.mark.parametrize("method", [None, "smart_project", "validated_authored_uv_v2"])
def test_weighted_runtime_requires_exact_authored_uv_opt_in(method):
    """Weighting is refused unless the source UV proof method is explicitly supported."""

    policy = _policy(uv_method=method)
    if method is None:
        policy.pop("uv_method")
    with pytest.raises(ValueError):
        runtime.resolve_atlas_tiles(policy, 1, [_object("a")])


@pytest.mark.parametrize("strategy", ["area_weighted_rect_v2", "weighted", "", None])
def test_unknown_tile_strategy_fails_closed(strategy):
    """Unknown strategy values must not silently select legacy or weighted allocation."""

    with pytest.raises(ValueError):
        runtime.resolve_atlas_tiles(_policy(tile_strategy=strategy), 1, [_object("a")])


@pytest.mark.parametrize("count,objects", [(1, None), (1, []), (2, [_object("a")]), (0, [])])
def test_weighted_allocation_requires_complete_nonempty_source_count(count, objects):
    """Missing or mismatched object evidence cannot receive fabricated area weights."""

    with pytest.raises(ValueError):
        runtime.resolve_atlas_tiles(_policy(), count, objects)


def test_duplicate_source_identity_is_ambiguous_and_rejected():
    """Two objects with the same exact identity cannot receive insertion-order-dependent cells."""

    source = _object("a")
    with pytest.raises(ValueError):
        _tiles([source, deepcopy(source)])


@pytest.mark.parametrize("mutation", [
    "missing_identity", "missing_vertices", "missing_matrix_world", "missing_loops",
    "missing_triangles",
    "empty_vertices", "empty_triangles", "short_vertex", "short_matrix", "short_matrix_row",
    "projective_matrix", "nan_vertex", "infinite_matrix", "negative_loop", "large_loop",
    "bool_loop", "negative_triangle", "large_triangle", "short_triangle", "bool_triangle",
    "degenerate", "collinear", "singular_surface_transform",
])
def test_malformed_or_degenerate_geometry_fails_closed(mutation):
    """Incomplete, nonfinite, misindexed and zero-area snapshots never get fallback allocations."""

    source = _object("a")
    if mutation.startswith("missing_"):
        source.pop(mutation.removeprefix("missing_"))
    elif mutation.startswith("empty_"):
        source[mutation.removeprefix("empty_")] = []
    elif mutation == "short_vertex":
        source["vertices"][0] = [0.0, 0.0]
    elif mutation == "short_matrix":
        source["matrix_world"].pop()
    elif mutation == "short_matrix_row":
        source["matrix_world"][0].pop()
    elif mutation == "projective_matrix":
        source["matrix_world"][3][0] = 1.0
    elif mutation == "nan_vertex":
        source["vertices"][0][0] = float("nan")
    elif mutation == "infinite_matrix":
        source["matrix_world"][0][0] = float("inf")
    elif mutation in {"negative_loop", "large_loop", "bool_loop"}:
        source["loops"][0] = {"negative_loop": -1, "large_loop": 4, "bool_loop": True}[mutation]
    elif mutation in {"negative_triangle", "large_triangle", "bool_triangle"}:
        source["triangles"][0][0] = {
            "negative_triangle": -1, "large_triangle": 4, "bool_triangle": True,
        }[mutation]
    elif mutation == "short_triangle":
        source["triangles"][0].pop()
    elif mutation == "degenerate":
        source["triangles"] = [[0, 0, 1]]
    elif mutation == "collinear":
        source["vertices"] = [[float(i), 0.0, 0.0] for i in range(4)]
    elif mutation == "singular_surface_transform":
        source["matrix_world"][1][1] = 0.0
    with pytest.raises(ValueError):
        _tiles([source, _object("valid")])


def test_model_accepts_weighted_only_with_authored_uv():
    """The policy model exposes weighting as a strict explicit authored-UV companion."""

    policy = PortableAtlasPolicy(tile_strategy=WEIGHTED, uv_method=AUTHORED)
    assert policy.model_dump(mode="json")["tile_strategy"] == WEIGHTED
    assert policy.model_dump(mode="json")["uv_method"] == AUTHORED
    with pytest.raises(ValidationError):
        PortableAtlasPolicy(tile_strategy=WEIGHTED)
    with pytest.raises(ValidationError):
        PortableAtlasPolicy(tile_strategy=WEIGHTED, uv_method="smart_project")
    with pytest.raises(ValidationError):
        PortableAtlasPolicy(tile_strategy="area_weighted_rect_v2", uv_method=AUTHORED)


def test_default_policy_serialization_is_exactly_legacy():
    """Adding the strategy must preserve every existing default field and omit default UV mode."""

    assert PortableAtlasPolicy().model_dump(mode="json") == {
        "layout": "global_shared",
        "atlas_scope": "all_render_lod",
        "conversion_phase": "after_optimization_with_canonical_source_frame",
        "tile_strategy": "deterministic_grid",
        "uv_set": "CBMPortableAtlas",
        "resolution": 2048,
        "margin_px": 16,
        "maximum_overlap_fraction": 0.0,
        "preserve_existing_uv_sets": True,
        "required_channels": ["base_color", "roughness", "metallic", "normal", "emission"],
    }
