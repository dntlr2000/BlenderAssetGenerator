"""Reference occupancy catches local gaps that an aggregate silhouette can conceal."""

import math

import pytest
from PIL import Image

from codex_blender_modeler.qa import reference_occupancy as m


def rectangle(left, top, right, bottom, resolution=(10, 10), scale=10):
    """Make a world-space quad with exactly specified source-pixel boundaries."""
    w, h = resolution
    return [
        (
            float((x - w / 2) * scale / max(w, h)),
            0.0,
            float((h / 2 - y) * scale / max(w, h)),
        )
        for x, y in [(left, top), (right, top), (right, bottom), (left, bottom)]
    ], [(0, 1, 2), (0, 2, 3)]


def render(left=2, top=2, right=8, bottom=8, resolution=(10, 10)):
    """Rasterize a simple quad using the tested exact source-grid mapping."""
    v, t = rectangle(left, top, right, bottom, resolution)
    return m.rasterize_orthographic_occupancy(
        v, t, resolution=resolution, ortho_scale=10
    )[0]


def test_exact_rectangle_and_reversed_winding():
    """The complete projection has identical occupancy for either triangle winding."""
    v, t = rectangle(2, 2, 8, 8)
    first, info = m.rasterize_orthographic_occupancy(
        v, t, resolution=(10, 10), ortho_scale=10
    )
    second, _ = m.rasterize_orthographic_occupancy(
        v, [f[::-1] for f in t], resolution=(10, 10), ortho_scale=10
    )
    assert first.tobytes() == second.tobytes()
    assert first.histogram()[255] == 36
    assert not info["actual_geometry_origin_verified"]


def test_high_silhouette_does_not_hide_central_gap():
    """One missing interior pixel fails despite a99percent silhouette and unchanged bounds."""
    expected = Image.new("L", (20, 20), 0)
    for y in range(5, 15):
        for x in range(5, 15):
            expected.putpixel((x, y), 255)
    candidate = expected.copy()
    candidate.putpixel((10, 10), 0)
    result = m.compare_sure_trimap_occupancy(expected, candidate)
    assert result["status"] == "failed" and result["missing_foreground_pixels"] == 1
    assert result["missing_components"]["largest_components"] == [
        {"pixels": 1, "bbox_pixels": [10, 10, 11, 11]}
    ]
    assert expected.getbbox() == candidate.getbbox()


def test_preserve_intended_hole_and_separated_parts():
    """Intentional background holes and independent parts pass when faithfully retained."""
    expected = render()
    expected.putpixel((5, 5), 0)
    assert m.compare_sure_trimap_occupancy(expected, expected.copy())["passed"]
    candidate = expected.copy()
    candidate.putpixel((5, 5), 255)
    result = m.compare_sure_trimap_occupancy(expected, candidate)
    assert not result["passed"] and result["filled_background_pixels"] == 1


def test_ambiguous_pixels_remain_unscored():
    """Both probable labels are reported outside coverage without dilation or repair."""
    expected = render()
    expected.putpixel((5, 5), 85)
    expected.putpixel((6, 6), 170)
    candidate = render()
    candidate.putpixel((5, 5), 0)
    candidate.putpixel((6, 6), 0)
    result = m.compare_sure_trimap_occupancy(expected, candidate)
    assert result["passed"] and result["unscored_pixels"] == 2
    assert not result["whole_asset_fidelity_verified"]


def test_lateral_gap_and_thin_projection_detected():
    """Entire source-grid seam coverage distinguishes a missing pixel-centre column."""
    expected = render(2, 2, 8, 8)
    candidate = render(2, 2, 7, 8)
    result = m.compare_sure_trimap_occupancy(expected, candidate)
    assert result["missing_foreground_pixels"] == 6
    assert result["missing_components"]["largest_components"][0]["bbox_pixels"] == [
        7,
        2,
        8,
        8,
    ]


def test_exact_pixel_centre_on_edge_and_one_ulp_shift():
    """An exact edge covers its pixel centre; a representable inward shift does not."""
    v, t = rectangle(2.5, 2, 8, 8)
    first, _ = m.rasterize_orthographic_occupancy(
        v, t, resolution=(10, 10), ortho_scale=10
    )
    for i in (0, 3):
        x, y, z = v[i]
        v[i] = (math.nextafter(x, math.inf), y, z)
    second, _ = m.rasterize_orthographic_occupancy(
        v, t, resolution=(10, 10), ortho_scale=10
    )
    assert first.getpixel((2, 4)) == 255 and second.getpixel((2, 4)) == 0


@pytest.mark.parametrize(
    "resolution, expected_bbox",
    [((20, 10), (12, 3, 16, 7)), ((10, 20), (7, 8, 10, 12))],
)
def test_non_square_grid_blender_auto_sensor_fit(resolution, expected_bbox):
    """Literal world geometry follows Blender AUTO's larger-dimension ortho scale."""
    vertices = [(1.0, 0.0, -1.0), (3.0, 0.0, -1.0), (3.0, 0.0, 1.0), (1.0, 0.0, 1.0)]
    mask, _ = m.rasterize_orthographic_occupancy(
        vertices, [(0, 1, 2), (0, 2, 3)], resolution=resolution, ortho_scale=10
    )
    assert mask.getbbox() == expected_bbox
    assert mask.histogram()[255] == (expected_bbox[2] - expected_bbox[0]) * (
        expected_bbox[3] - expected_bbox[1]
    )


def test_depth_does_not_claim_contact():
    """Depth-disjoint copies have the same mask and cannot imply3D attachment."""
    v, t = rectangle(2, 2, 8, 8)
    deep = [(x, 123.0, z) for x, y, z in v]
    first, _ = m.rasterize_orthographic_occupancy(
        v, t, resolution=(10, 10), ortho_scale=10
    )
    second, _ = m.rasterize_orthographic_occupancy(
        deep, t, resolution=(10, 10), ortho_scale=10
    )
    result = m.compare_sure_trimap_occupancy(first, second)
    assert result["passed"] and not result["continuous_3d_attachment_verified"]


def test_camera_shift_changes_coverage():
    """Different camera centres visibly change measured pixels; no recentering is hidden."""
    v, t = rectangle(2, 2, 8, 8)
    candidate, _ = m.rasterize_orthographic_occupancy(
        v, t, resolution=(10, 10), ortho_scale=10, center_x=1
    )
    result = m.compare_sure_trimap_occupancy(render(), candidate)
    assert (
        result["missing_foreground_pixels"] == 6
        and result["filled_background_pixels"] == 6
    )


@pytest.mark.parametrize(
    "change",
    ["resize", "rgb", "antialias", "unknown_label", "no_foreground", "no_background"],
)
def test_invalid_masks_are_not_coerced(change):
    """Invalid encodings/resolutions cannot silently acquire a passing interpretation."""
    expected = render()
    candidate = expected.copy()
    if change == "resize":
        candidate = candidate.resize((5, 5))
    elif change == "rgb":
        candidate = candidate.convert("RGB")
    elif change == "antialias":
        candidate.putpixel((4, 4), 128)
    elif change == "unknown_label":
        expected.putpixel((4, 4), 128)
    elif change == "no_foreground":
        expected = Image.new("L", (10, 10), 0)
    else:
        expected = Image.new("L", (10, 10), 255)
    with pytest.raises(ValueError):
        m.compare_sure_trimap_occupancy(expected, candidate)


@pytest.mark.parametrize(
    "bad",
    [True, float("nan"), float("inf"), "1", 10**10000],
    ids=["bool", "nan", "infinity", "string", "huge_integer"],
)
def test_malformed_coordinates_refused(bad):
    """Data-only admission excludes coercions, nonfinite values and huge integers."""
    v, t = rectangle(2, 2, 8, 8)
    v[0] = (bad, 0.0, 0.0)
    with pytest.raises(ValueError):
        m.rasterize_orthographic_occupancy(v, t, resolution=(10, 10), ortho_scale=10)


def test_subclass_and_work_exhaustion_refused(monkeypatch):
    """No caller-defined traversal or partial raster may escape bounded execution."""

    class Evil(list):
        def __iter__(self):
            """Fail loudly if admission invokes caller-defined traversal."""
            raise AssertionError("must not call subclass iteration")

    v, t = rectangle(2, 2, 8, 8)
    with pytest.raises(ValueError):
        m.rasterize_orthographic_occupancy(
            Evil(v), t, resolution=(10, 10), ortho_scale=10
        )
    monkeypatch.setattr(m, "MAX_PIXEL_TESTS", 1)
    with pytest.raises(ValueError, match="budget"):
        m.rasterize_orthographic_occupancy(v, t, resolution=(10, 10), ortho_scale=10)


def test_components_are_four_connected_and_details_bounded():
    """Retain exact counts for all mismatches even when only largest extents are stored."""
    expected = Image.new("L", (32, 32), 0)
    candidate = expected.copy()
    expected.putpixel((31, 31), 255)
    candidate.putpixel((31, 31), 255)
    for y in range(0, 30, 2):
        for x in range(0, 30, 2):
            candidate.putpixel((x, y), 255)
    result = m.compare_sure_trimap_occupancy(expected, candidate)
    assert result["filled_background_pixels"] == 225
    assert result["extra_components"]["component_count"] == 225
    assert len(result["extra_components"]["largest_components"]) == 64
    assert result["extra_components"]["component_details_omitted"] == 161
