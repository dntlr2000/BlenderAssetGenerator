"""Independent strict source-root subsets, cavities and source binding regressions."""

import json
from types import SimpleNamespace as NS

import pytest
import test_surface_attachment_host as util

from codex_blender_modeler.packaging import attachment as host
from codex_blender_modeler.structural_geometry.attachment_companion import (
    AttachmentIntentV01,
)
from codex_blender_modeler.structural_geometry.mesh_payload_v02 import MeshPayloadV02


def split_child(front=0.25, back=0.5):
    """Construct one closed long slab, splitting cap faces at x=.5 without changing its surface."""
    cap = [(x, front, z) for x in (0.0, 0.5, 2.0) for z in (0.0, 1.0)]
    vertices = cap + [(x, back, z) for x, _, z in cap]
    fronts = []
    for i in (0, 2):
        fronts.extend([(i, i + 2, i + 3), (i, i + 3, i + 1)])
    backs = [tuple(i + 6 for i in reversed(face)) for face in fronts]
    faces = fronts + backs
    boundary = [0, 2, 4, 5, 3, 1]
    for a, b in zip(boundary, boundary[1:] + boundary[:1], strict=False):
        faces.extend([(a, a + 6, b + 6), (a, b + 6, b)])
    return NS(
        semantic_id="relief",
        vertices=vertices,
        faces=[list(f) for f in faces],
        material_slots=[NS(material_id="mat.shared")],
        face_groups=[
            NS(id="upper", face_indices=list(range(4))),
            NS(id="lower", face_indices=list(range(4, 8))),
            NS(id="side", face_indices=list(range(8, 20))),
            NS(id="root_front", face_indices=[0, 1]),
            NS(id="root_back", face_indices=[4, 5]),
        ],
    )


def root_intent():
    """Select only the literal root strip with no relief-bound inheritance."""
    doc = util.intent().model_dump(mode="json")
    entry = doc["entries"][0]
    for name in (
        "minimum_embed_m",
        "maximum_embed_m",
        "minimum_remaining_thickness_m",
        "minimum_relief_height_m",
    ):
        entry.pop(name, None)
    entry.update(
        scope="required_root_patch",
        minimum_overlap_m=0.03125,
        subject_upper={"semantic_id": "relief", "face_group_id": "root_front"},
        subject_lower={"semantic_id": "relief", "face_group_id": "root_back"},
    )
    return AttachmentIntentV01.model_validate_json(json.dumps(doc))


def data(tmp_path, front=0.25, back=0.5):
    """Use real strict mesh admission, keeping raw actual fixture geometry explicitly separate."""
    meshes = {"owner": util.box("owner", 0.0, 1.0), "relief": split_child(front, back)}
    strict = {
        name: MeshPayloadV02.model_validate_json(json.dumps(util.strict_payload(mesh, tmp_path)))
        for name, mesh in meshes.items()
    }
    return strict, {"objects": [util.actual(mesh) for mesh in meshes.values()]}


def test_root_subset_proves_buried_strip_without_claiming_long_free_child(tmp_path):
    """Whole child eligibility and selected-strip overlap are separate, recorded predicates."""
    meshes, raw = data(tmp_path)
    result = host.evaluate_actual(root_intent(), meshes, raw)
    row = result["entries"][0]
    assert result["status"] == "passed"
    assert row["subject_solid"]["complete_triangle_count"] == 20
    assert row["selected_contact_source_faces"]["subject_front"] == [0, 1]
    assert row["selected_contact_source_faces"]["subject_back"] == [4, 5]
    assert len(row["subject_source_faces"]) == 20 and not row["free_subject_area_overlap_claimed"]


def test_full_relief_cannot_cherry_pick_the_same_supported_root_strip(tmp_path):
    """Even an exposed root subset does not replace the old whole-subject full-relief
    requirement."""
    meshes, raw = data(tmp_path, -0.125, 0.0625)
    root = root_intent()
    assert host.evaluate_actual(root, meshes, raw)["status"] == "passed"
    doc = root.model_dump(mode="json")
    entry = doc["entries"][0]
    entry.pop("minimum_overlap_m")
    entry.update(
        scope="required_full_patch",
        minimum_embed_m=0.03125,
        maximum_embed_m=0.09375,
        minimum_remaining_thickness_m=0.25,
        minimum_relief_height_m=0.0625,
    )
    full = AttachmentIntentV01.model_validate_json(json.dumps(doc))
    result = host.evaluate_actual(full, meshes, raw)
    assert (
        result["status"] == "failed"
        and result["entries"][0]["subject_solid"]["status"] == "unverified"
    )


@pytest.mark.parametrize("mutation", ["wrong_role", "missing_lower", "zero_contact", "cavity"])
def test_root_subset_still_refuses_invalid_solid_or_incomplete_contact(tmp_path, mutation):
    """New root semantics cannot hide wrong cap layers, a missing half, touching or a cavity."""
    meshes, raw = data(
        tmp_path,
        1.0 if mutation == "zero_contact" else 0.25,
        1.25 if mutation == "zero_contact" else 0.5,
    )
    intent = root_intent()
    if mutation == "wrong_role":
        doc = intent.model_dump(mode="json")
        entry = doc["entries"][0]
        entry["subject_lower"], entry["subject_upper"] = (
            entry["subject_upper"],
            entry["subject_lower"],
        )
        intent = AttachmentIntentV01.model_validate_json(json.dumps(doc))
    elif mutation == "missing_lower":
        payload = meshes["relief"].model_dump(mode="json")
        for groups in (
            payload["face_groups"],
            payload["source_geometry_intent"]["face_groups"],
        ):
            for group in groups:
                if group["id"] == "root_back":
                    group["face_indices"] = [4]
        declared = payload["source_geometry_intent"]
        declared.pop("source_intent_sha256")
        declared["source_intent_sha256"] = util.canonical_json_sha256(declared)
        meshes["relief"] = MeshPayloadV02.model_validate_json(json.dumps(payload))
    elif mutation == "cavity":
        owner = util.box("owner", 0.0, 1.0)
        cavity = util.box("cavity", 0.125, 0.875, 0.125, 0.875)
        cavity.faces = [list(reversed(face)) for face in cavity.faces]
        util.append_component(owner, cavity, "cavity.")
        meshes["owner"] = MeshPayloadV02.model_validate_json(
            json.dumps(util.strict_payload(owner, tmp_path))
        )
        raw["objects"][0] = util.actual(owner)
    try:
        result = host.evaluate_actual(intent, meshes, raw)
    except ValueError:
        return
    assert result["status"] != "passed", result


def test_same_semantic_distinct_complete_components_remain_eligible(tmp_path):
    """Two actual parts may be grouped under one semantic while their component memberships stay
    disjoint."""
    mesh = util.box("grouped", 0.0, 1.0)
    util.append_component(mesh, split_child(), "child.")
    parsed = MeshPayloadV02.model_validate_json(json.dumps(util.strict_payload(mesh, tmp_path)))
    doc = root_intent().model_dump(mode="json")
    entry = doc["entries"][0]
    for name in ("subject_upper", "subject_lower", "owner_front", "owner_back"):
        entry[name]["semantic_id"] = "grouped"
        if name.startswith("subject"):
            entry[name]["face_group_id"] = "child." + entry[name]["face_group_id"]
    intent = AttachmentIntentV01.model_validate_json(json.dumps(doc))
    result = host.evaluate_actual(intent, {"grouped": parsed}, {"objects": [util.actual(mesh)]})
    assert result["status"] == "passed"
    row = result["entries"][0]
    assert not set(row["subject_source_faces"]) & set(row["owner_source_faces"])


@pytest.mark.parametrize(
    "mutation",
    [
        "reference_alias",
        "reference_bytes",
        "plan_bytes",
        "plan_foreign_job",
        "plan_alias",
    ],
)
def test_required_primary_reference_and_canonical_plan_bindings(tmp_path, mutation):
    """Bytes, identity and canonical plan destination remain bound before geometry admission."""
    root, selection, _ = util.registration_fixture(tmp_path)
    doc = json.loads((root / selection["path"]).read_bytes())
    if mutation == "reference_alias":
        source = root / doc["source_reference"]["path"]
        alias = root / "input/copied_reference.png"
        alias.write_bytes(source.read_bytes())
        doc["source_reference"]["path"] = "input/copied_reference.png"
    elif mutation == "reference_bytes":
        source = root / doc["source_reference"]["path"]
        source.write_bytes(source.read_bytes() + b"changed")
    elif mutation == "plan_bytes":
        source = root / doc["source_modeling_plan"]["path"]
        source.write_bytes(source.read_bytes() + b"changed")
    elif mutation == "plan_foreign_job":
        doc["source_modeling_plan"] = util.put(
            root, "analysis/modeling_plan.json", {"job_id": "other"}
        )
    else:
        doc["source_modeling_plan"] = util.put(
            root, "analysis/copied_plan.json", {"job_id": "fixture"}
        )
    intent = AttachmentIntentV01.model_validate_json(json.dumps(doc))
    with pytest.raises((ValueError, RuntimeError)):
        host._source_meshes(root, intent)
