"""Buried structural roots require full overlap, distinct from exposed relief."""

import json

import pytest
from test_attachment_companion import setup
from test_owner_relief import plane

from codex_blender_modeler.structural_geometry.attachment_companion import (
    AttachmentEntry,
    AttachmentIntentV01,
)
from codex_blender_modeler.structural_geometry.owner_relief import (
    inspect_attachment,
    inspect_inserted_root,
)


def root_fixture():
    """Declare a complete buried patch inside a thick owner without requiring exposure."""
    front, faces = plane(0.0)
    back, _ = plane(0.2)
    upper, _ = plane(0.04, 0.2, 0.8)
    lower, _ = plane(0.12, 0.2, 0.8)
    return dict(
        lower_vertices=lower,
        lower_triangles=faces,
        upper_vertices=upper,
        upper_triangles=faces,
        owner_front_vertices=front,
        owner_front_triangles=faces,
        owner_back_vertices=back,
        owner_back_triangles=faces,
        minimum_overlap=0.02,
    )


def test_buried_root_positive_and_relief_still_negative():
    """A valid buried insertion does not weaken the separate exposed-relief predicate."""
    data = root_fixture()
    report = inspect_inserted_root(**data)
    assert report["passed"] and not report["outward_exposure_required"]
    assert not report["free_subject_area_overlap_claimed"]
    data.pop("minimum_overlap")
    relief = inspect_attachment(
        **data,
        minimum_embed=0.01,
        maximum_embed=0.15,
        minimum_remaining_thickness=0.05,
        minimum_relief_height=0.0,
    )
    assert relief["status"] == "failed"


@pytest.mark.parametrize(
    "kind",
    ["behind", "front", "zero_touch", "insufficient", "lateral", "missing_middle"],
)
def test_root_disconnection_and_partial_coverage(kind):
    """Whole-patch overlap fails on depth gaps, zero-only contact or unsupported area."""
    data = root_fixture()
    if kind == "behind":
        data["upper_vertices"] = [(x, y + 0.3, z) for x, y, z in data["upper_vertices"]]
        data["lower_vertices"] = [(x, y + 0.3, z) for x, y, z in data["lower_vertices"]]
    elif kind == "front":
        data["upper_vertices"] = [(x, y - 0.3, z) for x, y, z in data["upper_vertices"]]
        data["lower_vertices"] = [(x, y - 0.3, z) for x, y, z in data["lower_vertices"]]
    elif kind == "zero_touch":
        data["upper_vertices"] = [(x, 0.2, z) for x, y, z in data["upper_vertices"]]
        data["lower_vertices"] = [(x, 0.3, z) for x, y, z in data["lower_vertices"]]
    elif kind == "insufficient":
        data["upper_vertices"] = [(x, 0.19, z) for x, y, z in data["upper_vertices"]]
        data["lower_vertices"] = [(x, 0.3, z) for x, y, z in data["lower_vertices"]]
    elif kind == "lateral":
        for key in ("upper_vertices", "lower_vertices"):
            data[key] = [(x + 0.4, y, z) for x, y, z in data[key]]
    else:
        data["owner_front_triangles"] = [(0, 1, 2)]
    assert inspect_inserted_root(**data)["status"] == "failed"


def test_internal_depth_break_cannot_hide_from_root_vertices():
    """An owner depth extremum inside the root is measured at inserted overlay vertices."""
    data = root_fixture()
    data["owner_front_vertices"] = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 0.0, 1.0),
        (0.0, 0.0, 1.0),
        (0.5, 0.15, 0.5),
    ]
    data["owner_front_triangles"] = [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    assert inspect_inserted_root(**data)["status"] == "failed"


def test_complete_patch_overlap_switching_has_exact_minimum():
    """Crossing affine interval limits retain the true whole-domain minimum."""
    data = root_fixture()
    data["upper_vertices"] = [(x, -0.02 + 0.1 * x, z) for x, y, z in data["upper_vertices"]]
    data["lower_vertices"] = [(x, 0.08 + 0.1 * x, z) for x, y, z in data["lower_vertices"]]
    report = inspect_inserted_root(**data)
    assert report["passed"] and report["minimum_overlap_m_exact"] is not None
    assert report["owner_volume_verified"] is False


def test_root_contract_is_explicit_and_cannot_borrow_relief_bounds(tmp_path):
    """Only a fresh root scope/hash can choose interval overlap; mixed bounds are refused."""
    intent, _ = setup(tmp_path)
    entry = intent["entries"][0]
    entry["scope"] = "required_root_patch"
    for key in (
        "minimum_embed_m",
        "maximum_embed_m",
        "minimum_remaining_thickness_m",
        "minimum_relief_height_m",
    ):
        entry.pop(key)
    entry["minimum_overlap_m"] = 0.01
    parsed = AttachmentIntentV01.model_validate_json(json.dumps(intent))
    assert parsed.entries[0].minimum_overlap_m == 0.01
    entry["minimum_embed_m"] = 0.01
    with pytest.raises(ValueError):
        AttachmentEntry.model_validate_json(json.dumps(entry))


@pytest.mark.parametrize("name", ["reference.json", "modeling_plan.json"])
def test_reference_and_plan_bytes_are_mandatory_exact_inputs(tmp_path, name):
    """Stale reference or modeling-plan bytes fail the same bound diagnostic loader."""
    from test_attachment_companion import evaluate

    intent, snapshot = setup(tmp_path)
    (tmp_path / name).write_text("changed")
    with pytest.raises(ValueError, match="stale artifact bytes"):
        evaluate(tmp_path, intent, snapshot)
