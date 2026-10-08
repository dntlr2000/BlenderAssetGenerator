"""Strict bound selection and actual-correspondence negatives for local root-ball proof."""

import copy
import json

import pytest
import test_surface_attachment_host as legacy

from codex_blender_modeler.attachment_runtime import REGISTRATION_PATH, selected_attachment
from codex_blender_modeler.packaging import attachment as host
from codex_blender_modeler.solid_attachment_contract import validate_solid_root_contract
from codex_blender_modeler.structural_geometry.solid_attachment_companion import (
    SolidRootAttachmentIntentV01,
)
from codex_blender_modeler.structural_geometry.solid_root_ball import Budget


def document():
    """Declare a fixed local joint and complete semantic scope with no native claims."""
    old = legacy.intent().model_dump(mode="json")
    return {
        "schema_version": "0.1.0",
        "contract_kind": "solid_root_attachment_intent",
        **{
            key: old[key]
            for key in (
                "job_id",
                "source_reference",
                "source_modeling_plan",
                "source_scene",
                "source_geometry",
            )
        },
        "source_camera_hypothesis": {"path": "analysis/camera_hypothesis.json", "sha256": "5" * 64},
        "minimum_radius_m": 0.01,
        "radius_basis": "Explicit fixture joint with 0.08 overlap; fixed 0.02-radius witness.",
        "required_semantics": ["owner", "relief"],
        "entries": [
            {
                "attachment_id": "root",
                "scope": "required_local_overlap_ball",
                "owner_semantic_id": "owner",
                "subject_semantic_id": "relief",
                "joint_description": "Central inserted material joint, not the free tip.",
                "center": [0.5, 0.04, 0.5],
                "radius_m": 0.02,
                "root_bounds": [[0.35, 0.005, 0.35], [0.65, 0.075, 0.65]],
            }
        ],
    }


def fixture():
    """Supply exact simulated binary32 records over the declared complete solids."""
    meshes = {
        "owner": legacy.box("owner"),
        "relief": legacy.box("relief", -0.1, 0.08, 0.2, 0.8, ("upper", "lower", "side")),
    }
    return (
        SolidRootAttachmentIntentV01.model_validate_json(json.dumps(document())),
        meshes,
        {"objects": [legacy.actual(m) for m in meshes.values()]},
    )


def registration_fixture(tmp_path):
    """Bind real strict source payloads, reference, canonical plan and camera hypothesis."""
    root, old_selection, _ = legacy.registration_fixture(tmp_path)
    old = json.loads((root / old_selection["path"]).read_bytes())
    mesh = legacy.box("relief", -0.1, 0.08, 0.2, 0.8, ("upper", "lower", "side"))
    old["source_geometry"][1] = legacy.put(
        root, "geometry/relief.json", legacy.strict_payload(mesh, root)
    )
    scene = json.loads((root / old["source_scene"]["path"]).read_bytes())
    scene["camera"] = {
        "projection": "ORTHO",
        "location": [0.4, -3.0, 0.2],
        "target": [0.0, 0.0, 0.0],
        "focal_length_mm": 50.0,
        "ortho_scale": 2.0,
        "resolution": [32, 32],
    }
    old["source_scene"] = legacy.put(root, "analysis/scene_spec.json", scene)
    camera = legacy.put(
        root,
        "analysis/camera_hypothesis.json",
        {
            "schema_version": "0.1.0",
            "contract_kind": "reference_camera_hypothesis",
            "job_id": "fixture",
            "reference": old["source_reference"],
            "camera": scene["camera"],
            "calibration_status": "hypothesis_not_unique_recovery",
            "assumptions": ["Explicit synthetic oblique fixture camera."],
        },
    )
    doc = document()
    doc.update(
        {
            key: old[key]
            for key in (
                "source_reference",
                "source_modeling_plan",
                "source_scene",
                "source_geometry",
            )
        }
    )
    doc["source_camera_hypothesis"] = camera
    selection = legacy.put(root, "analysis/solid_root_intent.json", doc)
    return root, selection, doc


def register(root, selection, monkeypatch):
    """Invoke the actual explicit host selection route for an owned unbuilt test job."""
    monkeypatch.setattr(host, "job_dir", lambda _: root)
    return host.register_solid_root_attachment_intent(
        "fixture", intent_path=selection["path"], intent_sha256=selection["sha256"]
    )


def test_mathematical_scope_and_exact_f32_correspondence():
    """Host mapping validates all boundaries but caller JSON never becomes native evidence."""
    intent, meshes, raw = fixture()
    report = host.evaluate_actual(intent, meshes, raw)
    assert report["status"] == "passed"
    assert report["kind"] == "solid_root_attachment_report"
    assert report["source_correspondence_verified"] is True
    assert report["actual_triangle_extraction_verified"] is False
    assert report["seam_wide_coverage_claimed"] is False
    assert report["visual_fidelity_claimed"] is False
    assert report["aggregate_triangle_count"] == 24


@pytest.mark.parametrize(
    "mutation",
    [
        "center",
        "radius",
        "region",
        "unknown_owner",
        "same_owner",
        "minimum",
        "extra_field",
        "bool_radius",
        "duplicate_id",
    ],
)
def test_strict_intent_rejects_invalid_selection(mutation):
    """Host and fixed stdlib selectors share complete semantic and whole-region validation."""
    doc = document()
    entry = doc["entries"][0]
    if mutation == "center":
        entry["center"] = [0.8, 0.04, 0.5]
    elif mutation == "radius":
        entry["radius_m"] = 0.08
    elif mutation == "region":
        entry["root_bounds"] = [[0.49, 0.03, 0.49], [0.51, 0.05, 0.51]]
    elif mutation == "unknown_owner":
        entry["owner_semantic_id"] = "absent"
    elif mutation == "same_owner":
        entry["owner_semantic_id"] = "relief"
    elif mutation == "minimum":
        entry["radius_m"] = 0.005
    elif mutation == "extra_field":
        doc["silently_allow_unverified"] = True
    elif mutation == "bool_radius":
        entry["radius_m"] = True
    else:
        doc["entries"].append(copy.deepcopy(entry))
    for validate in [
        validate_solid_root_contract,
        lambda x: SolidRootAttachmentIntentV01.model_validate_json(json.dumps(x)),
    ]:
        with pytest.raises(ValueError):
            validate(doc)


@pytest.mark.parametrize(
    "mutation", ["position", "normal_winding", "material", "missing_face", "extra_object"]
)
def test_actual_drift_and_scope_fail(mutation):
    """F32 drift, orientation/material changes and missing or unrelated geometry fail closed."""
    intent, meshes, raw = fixture()
    raw = copy.deepcopy(raw)
    if mutation == "position":
        tri = raw["objects"][0]["triangles"][0]
        tri["corners"][0] = [tri["corners"][0][0] + 1e-7, *tri["corners"][0][1:]]
    elif mutation == "normal_winding":
        raw["objects"][0]["triangles"][0]["corners"].reverse()
    elif mutation == "material":
        raw["objects"][0]["triangles"][0]["material_id"] = "mat.other"
    elif mutation == "missing_face":
        raw["objects"][0]["triangles"].pop()
    else:
        raw["objects"].append({"semantic_id": "unrelated", "triangles": []})
    with pytest.raises(ValueError):
        host.evaluate_actual(intent, meshes, raw)


def test_registration_and_explicit_domain_boundary(tmp_path, monkeypatch):
    """Only the explicit new API selects the new domain, then all source bytes remain pinned."""
    root, selection, doc = registration_fixture(tmp_path)
    monkeypatch.setattr(host, "job_dir", lambda _: root)
    with pytest.raises(ValueError, match="another proof domain"):
        host.register_surface_attachment_intent(
            "fixture", intent_path=selection["path"], intent_sha256=selection["sha256"]
        )
    assert not (root / REGISTRATION_PATH).exists()
    assert register(root, selection, monkeypatch) == selection
    assert selected_attachment(root, "fixture", root / doc["source_scene"]["path"]) == selection
    reports = list((root / "reports/surface_attachment").glob("source-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_bytes())
    assert report["status"] == "passed" and report["actual_triangle_extraction_verified"] is False
    assert (
        json.loads((root / REGISTRATION_PATH).read_bytes())["kind"]
        == "solid_root_attachment_registration"
    )


@pytest.mark.parametrize("field", ["center", "radius_m", "root_bounds", "owner_semantic_id"])
def test_registered_selection_tampering_rejected(tmp_path, monkeypatch, field):
    """Changing a selected semantic root or witness cannot borrow its old immutable receipt."""
    root, selection, doc = registration_fixture(tmp_path)
    register(root, selection, monkeypatch)
    doc["entries"][0][field] = {
        "center": [0.51, 0.04, 0.5],
        "radius_m": 0.015,
        "root_bounds": [[0.3, 0.0, 0.3], [0.7, 0.08, 0.7]],
        "owner_semantic_id": "relief",
    }[field]
    legacy.put(root, selection["path"], doc)
    with pytest.raises(ValueError, match="changed"):
        selected_attachment(root, "fixture", root / "analysis/scene_spec.json")


def test_camera_and_geometry_hashes_remain_bound(tmp_path, monkeypatch):
    """An unchanged intent digest does not hide a changed camera dependency."""
    root, selection, doc = registration_fixture(tmp_path)
    register(root, selection, monkeypatch)
    path = root / doc["source_camera_hypothesis"]["path"]
    value = json.loads(path.read_bytes())
    value["camera"]["location"][0] += 0.1
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="changed"):
        selected_attachment(root, "fixture", root / "analysis/scene_spec.json")


def test_camera_scene_mismatch_rejected_before_registration(tmp_path, monkeypatch):
    """A newly hashed hypothesis cannot select a different camera than canonical authoring."""
    root, selection, doc = registration_fixture(tmp_path)
    path = root / doc["source_camera_hypothesis"]["path"]
    value = json.loads(path.read_bytes())
    value["camera"]["location"][0] += 0.1
    doc["source_camera_hypothesis"] = legacy.put(
        root, doc["source_camera_hypothesis"]["path"], value
    )
    selection = legacy.put(root, selection["path"], doc)
    with pytest.raises(ValueError, match="camera hypothesis"):
        register(root, selection, monkeypatch)
    assert not (root / REGISTRATION_PATH).exists()


@pytest.mark.parametrize("limit", [True, 0, -1, 1.5, 1000001])
def test_budget_type_and_range(limit):
    """Budget construction cannot expand caps or accept bool/float aliases."""
    with pytest.raises(ValueError):
        Budget(limit)


def test_aggregate_geometry_and_predicate_budgets():
    """A shared evaluation context counts all components and all root checks."""
    budget = Budget()
    for _ in range(6):
        budget.claim_component(4096)
    with pytest.raises(ValueError, match="aggregate"):
        budget.claim_component(4096)
    budget = Budget(2)
    budget.charge()
    budget.charge()
    with pytest.raises(ValueError, match="exhausted"):
        budget.charge()


@pytest.mark.parametrize("field", ["schema_version", "contract_kind", "scope"])
def test_omitted_serialization_headers_fail_before_registration(tmp_path, monkeypatch, field):
    """The model and fixed reader cannot disagree because a missing default was silently filled."""
    root, selection, doc = registration_fixture(tmp_path)
    if field == "scope":
        del doc["entries"][0][field]
    else:
        del doc[field]
    selection = legacy.put(root, selection["path"], doc)
    with pytest.raises(ValueError):
        register(root, selection, monkeypatch)
    assert not (root / REGISTRATION_PATH).exists()
    assert "attachment_intent" not in json.loads((root / "job.json").read_bytes())
