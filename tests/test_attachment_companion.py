"""Exact binding and anti-misattribution tests for optional attachment companion staging."""

import hashlib
import json

import pytest
from test_owner_relief import fixture

from codex_blender_modeler.structural_geometry.attachment_companion import (
    Artifact,
    AttachmentIntentV01,
    evaluate_bound_patches,
)


def put(root, name, payload):
    """Write a unique test artifact and record its actual digest."""
    data = json.dumps(payload).encode()
    (root / name).write_bytes(data)
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}


def setup(root):
    """Freeze named semantic groups against exact source and claimed export artifacts."""
    scene = put(root, "scene.json", {})
    geometry = put(root, "geometry.json", {})
    export = put(root, "actual.glb", {"test_only": True})
    selectors = {
        name: {
            "semantic_id": "relief" if name in ("lower", "upper") else "owner",
            "face_group_id": name,
        }
        for name in ("lower", "upper", "front", "back")
    }
    entry = {
        "attachment_id": "ridge.01",
        "scope": "required_full_patch",
        "subject_lower": selectors["lower"],
        "subject_upper": selectors["upper"],
        "owner_front": selectors["front"],
        "owner_back": selectors["back"],
        "minimum_embed_m": 0.01,
        "maximum_embed_m": 0.03,
        "minimum_remaining_thickness_m": 0.1,
        "minimum_relief_height_m": 0.0,
    }
    intent = {
        "schema_version": "0.1.0",
        "contract_kind": "surface_attachment_intent",
        "job_id": "fixture",
        "source_reference": put(root, "reference.json", {"test_only_reference": True}),
        "source_modeling_plan": put(root, "modeling_plan.json", {"job_id": "fixture"}),
        "source_scene": scene,
        "source_geometry": [geometry],
        "entries": [entry],
    }
    f = fixture()
    patches = []
    for name in selectors:
        prefix = "owner_" + name if name in ("front", "back") else name
        patches.append(
            {
                "selection": selectors[name],
                "source_geometry": geometry,
                "vertices_m": f[prefix + "_vertices"],
                "triangles": f[prefix + "_triangles"],
            }
        )
    snapshot = {
        "schema_version": "0.1.0",
        "contract_kind": "surface_attachment_triangle_snapshot",
        "job_id": "fixture",
        "inspected_artifact": export,
        "source_scene": scene,
        "stage": "clean_import_glb",
        "patches": patches,
    }
    return intent, snapshot


def evaluate(root, intent, snapshot):
    """Load fresh immutable model bytes and compute their geometric diagnostics."""
    ia = Artifact(**put(root, "intent.json", intent))
    sa = Artifact(**put(root, "snapshot.json", snapshot))
    return evaluate_bound_patches(root, ia, sa)


def test_valid_data_is_not_export_extraction_attestation(tmp_path):
    """A geometric pass cannot turn a named GLB artifact into verified extraction."""
    intent, snapshot = setup(tmp_path)
    r = evaluate(tmp_path, intent, snapshot)
    assert r["entries"][0]["passed"] is True
    assert r["status"] == "unverified" and r["actual_triangle_extraction_verified"] is False


def test_wrong_owner_not_rescued_by_coincident_geometry(tmp_path):
    """A geometrically coincident patch with a different owner identity is unavailable evidence."""
    intent, snapshot = setup(tmp_path)
    snapshot["patches"][2]["selection"]["semantic_id"] = "wrong_owner"
    # Detach the formerly shared test dictionary so only the snapshot is changed.
    intent["entries"][0]["owner_front"] = {
        "semantic_id": "owner",
        "face_group_id": "front",
    }
    with pytest.raises(ValueError, match="required selected patch absent"):
        evaluate(tmp_path, intent, snapshot)


def test_stale_export_bytes_fail_binding(tmp_path):
    """An unchanged triangle snapshot cannot authorize a modified exported artifact."""
    intent, snapshot = setup(tmp_path)
    (tmp_path / "actual.glb").write_bytes(b"changed")
    with pytest.raises(ValueError, match="stale artifact bytes"):
        evaluate(tmp_path, intent, snapshot)


def test_missing_selected_intent_never_becomes_legacy(tmp_path):
    """The explicit caller binding persists when its selected companion file disappears."""
    intent, snapshot = setup(tmp_path)
    ia = Artifact(**put(tmp_path, "intent.json", intent))
    sa = Artifact(**put(tmp_path, "snapshot.json", snapshot))
    (tmp_path / "intent.json").unlink()
    with pytest.raises(FileNotFoundError):
        evaluate_bound_patches(tmp_path, ia, sa)


def test_scope_cannot_be_waived_without_new_hash(tmp_path):
    """A rewritten exception with the same selected artifact digest is stale evidence."""
    intent, snapshot = setup(tmp_path)
    ia = Artifact(**put(tmp_path, "intent.json", intent))
    sa = Artifact(**put(tmp_path, "snapshot.json", snapshot))
    intent["entries"][0]["scope"] = "intentional_open"
    (tmp_path / "intent.json").write_text(json.dumps(intent))
    with pytest.raises(ValueError, match="stale artifact bytes"):
        evaluate_bound_patches(tmp_path, ia, sa)


def test_required_patch_missing_or_duplicate_is_refused(tmp_path):
    """Neither omission nor duplicate candidate groups can make a required patch complete."""
    intent, snapshot = setup(tmp_path)
    snapshot["patches"].pop()
    with pytest.raises(ValueError, match="required selected patch absent"):
        evaluate(tmp_path, intent, snapshot)
    intent, snapshot = setup(tmp_path)
    snapshot["patches"].append(snapshot["patches"][0])
    with pytest.raises(ValueError, match="snapshot repeats"):
        evaluate(tmp_path, intent, snapshot)


def test_model_rejects_extra_authority_and_implicit_exception(tmp_path):
    """The companion contains no new write/approval authority and demands explicit exceptions."""
    intent, _ = setup(tmp_path)
    intent["approval"] = True
    with pytest.raises(ValueError):
        AttachmentIntentV01.model_validate_json(json.dumps(intent))
    intent.pop("approval")
    intent["entries"][0]["scope"] = "intentional_open"
    with pytest.raises(ValueError):
        AttachmentIntentV01.model_validate_json(json.dumps(intent))


@pytest.mark.parametrize("path", ["../outside", "/outside", "a//b", "a\\b", "C:/outside"])
def test_artifact_path_escape_refused(path):
    """Persisted source bindings remain normalized root-relative artifacts."""
    with pytest.raises(ValueError):
        Artifact(path=path, sha256="0" * 64)
