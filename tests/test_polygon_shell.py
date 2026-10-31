"""Polygon authoring, exact corner mapping and legacy attachment compatibility."""

import copy
import json
from types import SimpleNamespace

import pytest
import test_solid_root_attachment_host as solid
import test_surface_attachment_host as surface

from codex_blender_modeler.attachment_runtime import selected_attachment
from codex_blender_modeler.packaging import attachment
from codex_blender_modeler.structural_geometry.mesh_payload_v02 import MeshPayloadV02
from codex_blender_modeler.structural_geometry.models import StructuralGeometryCandidate
from codex_blender_modeler.structural_geometry.polygon_shell import PolygonShellGeometry
from codex_blender_modeler.structural_geometry.polygon_shell_math import (
    topology_statistics,
    triangle_view,
    validate_polygon_shell_data,
)
from codex_blender_modeler.structural_geometry.service import materialize_structural_candidate
from codex_blender_modeler.structural_geometry.triangle_view import (
    MeshTriangleViewV01,
    project_triangle_view,
)


def cube():
    """Return six outward quads with deliberate per-corner UV seams."""
    return {
        "kind": "polygon_shell",
        "vertices": [[-1., -1., -1.], [1., -1., -1.], [1., 1., -1.], [-1., 1., -1.],
                     [-1., -1., 1.], [1., -1., 1.], [1., 1., 1.], [-1., 1., 1.]],
        "faces": [[3, 2, 1, 0], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5],
                  [2, 3, 7, 6], [3, 0, 4, 7]],
        "loop_uvs": [[0., 0.], [1., 0.], [1., 1.], [0., 1.]] * 6,
    }


def test_polygon_admission_preserves_faces_and_uvs():
    """Preserve authored quads while allowing bounded nonplanarity and triangle exceptions."""
    value = cube()
    value["vertices"][6][2] = 1.2
    parsed = PolygonShellGeometry.model_validate_json(json.dumps(value))
    assert parsed.model_dump(mode="json") == value
    stats = topology_statistics(value["vertices"], value["faces"])
    assert stats["quad_face_ratio"] == stats["quad_area_ratio"] == 1
    assert stats["maximum_quad_warp_degrees"] > 0
    value["faces"][0:1] = [[3, 2, 1], [3, 1, 0]]
    value["loop_uvs"] = None
    validate_polygon_shell_data(value)


def test_topology_reports_local_and_global_winding_defects():
    """Do not report a positive-volume closed shell as outward when one face is reversed."""
    value = cube()
    value["faces"][0].reverse()
    stats = topology_statistics(value["vertices"], value["faces"])
    assert stats["signed_volume"] > 0
    assert stats["edge_winding_conflicts"] == 4
    assert stats["closed_outward_orientation"] is False
    value = cube()
    for face in value["faces"]:
        face.reverse()
    stats = topology_statistics(value["vertices"], value["faces"])
    assert stats["edge_winding_conflicts"] == 0
    assert stats["closed_outward_orientation"] is False


@pytest.mark.parametrize("failure", ["open", "winding", "crossed", "unused", "uv", "extra"])
def test_polygon_invalid_input_fails_before_build(failure):
    """Reject malformed topology, corner identity and execution side channels."""
    value = cube()
    if failure == "open":
        value["faces"].pop()
    elif failure == "winding":
        value["faces"][0].reverse()
    elif failure == "crossed":
        value["faces"][0][1:3] = reversed(value["faces"][0][1:3])
    elif failure == "unused":
        value["vertices"].append([9., 9., 9.])
    elif failure == "uv":
        value["loop_uvs"].pop()
    else:
        value["script"] = "untrusted"
    with pytest.raises(ValueError):
        validate_polygon_shell_data(value)
    with pytest.raises(ValueError):
        PolygonShellGeometry.model_validate_json(json.dumps(value))


@pytest.mark.parametrize("failure", ["missing", "duplicate", "reversed", "cross_face", "bool"])
def test_triangle_partition_rejects_false_correspondence(failure):
    """Reject partial, duplicated, reversed and cross-polygon projections."""
    value = cube()
    loops = triangle_view(value["vertices"], value["faces"])["loop_indices"]
    if failure == "missing":
        loops.pop()
    elif failure == "duplicate":
        loops[1] = loops[0][:]
    elif failure == "reversed":
        loops[0].reverse()
    elif failure == "cross_face":
        loops[0][0] = 4
    else:
        loops[0][0] = False
    with pytest.raises(ValueError):
        triangle_view(value["vertices"], value["faces"], loops)


def test_triangle_view_preserves_material_groups_and_seams(tmp_path):
    """Map original polygon and loop attributes to both legal quad diagonal choices."""
    value = cube()
    mesh = SimpleNamespace(semantic_id="owner", vertices=value["vertices"], faces=value["faces"],
                           face_groups=[SimpleNamespace(id="a", face_indices=[0, 2, 4]),
                                        SimpleNamespace(id="b", face_indices=[1, 3, 5])])
    raw = surface.strict_payload(mesh, tmp_path)
    raw.update(loop_count=24, loop_uvs=value["loop_uvs"])
    raw["material_slots"].append({"slot_index": 1, "material_id": "mat.other"})
    raw["polygon_material_indices"] = [0, 1, 0, 1, 0, 1]
    raw["uv_seams"] = [{"vertices": [0, 1]}]
    intent = raw["source_geometry_intent"]
    intent["material_assignments"][1]["material_id"] = "mat.other"
    intent["uv_seams"] = [{"vertices": [0, 1]}]
    intent["source_intent_sha256"] = surface.canonical_json_sha256({
        k: v for k, v in intent.items() if k != "source_intent_sha256"
    })
    payload = MeshPayloadV02.model_validate_json(json.dumps(raw))
    before = payload.model_dump_json()
    loops = [[i, i + 1, i + 3] for i in range(0, 24, 4)]
    loops += [[i + 1, i + 2, i + 3] for i in range(0, 24, 4)]
    view = MeshTriangleViewV01.model_validate_json(json.dumps({
        "source_mesh": {"path": "mesh.json", "sha256": "0" * 64}, "loop_triangles": loops,
    }))
    projected = project_triangle_view(payload, view)
    assert len(projected.faces) == 12 and projected.loop_count == 36
    assert projected.face_groups[0].face_indices == [0, 2, 4, 6, 8, 10]
    assert projected.face_groups[1].face_indices == [1, 3, 5, 7, 9, 11]
    assert projected.loop_uvs == [payload.loop_uvs[i] for tri in loops for i in tri]
    assert projected.polygon_material_indices == [0, 1] * 6
    assert projected.uv_seams == payload.uv_seams
    assert payload.model_dump_json() == before


def polygon_registration(tmp_path, domain):
    """Upgrade only isolated test fixtures to explicit polygon source selection."""
    if domain == "solid":
        root, selection, doc = solid.registration_fixture(tmp_path)
    else:
        root, selection, _ = surface.registration_fixture(tmp_path)
        doc = json.loads((root / selection["path"]).read_bytes())
    doc["schema_version"] = "0.2.0"
    doc["source_triangle_views"] = []
    for i, artifact in enumerate(doc["source_geometry"]):
        original = json.loads((root / artifact["path"]).read_bytes())
        triangles = original["faces"]
        # Fixture boxes have paired fan triangles, so the exact polygon boundary is known.
        faces = []
        for a, b in zip(triangles[::2], triangles[1::2], strict=True):
            edges = [(t[j], t[(j + 1) % 3]) for t in (a, b) for j in range(3)]
            boundary = {x: y for x, y in edges if (y, x) not in edges}
            face = [a[0]]
            for _ in range(3):
                face.append(boundary[face[-1]])
            faces.append(face)
        groups = [SimpleNamespace(
            id=g["id"], face_indices=sorted({f // 2 for f in g["face_indices"]})
        ) for g in original["face_groups"]]
        mesh = SimpleNamespace(semantic_id=original["semantic_id"], vertices=original["vertices"],
                               faces=faces, face_groups=groups)
        raw = surface.strict_payload(mesh, root)
        raw.update(loop_count=sum(map(len, faces)), loop_uvs=[[0., 0.]] * sum(map(len, faces)))
        binding = surface.put(root, artifact["path"], raw)
        doc["source_geometry"][i] = binding
        mapping = triangle_view(mesh.vertices, faces)
        doc["source_triangle_views"].append(surface.put(root, f"views/{i}.json", {
            "source_mesh": binding, "loop_triangles": mapping["loop_indices"],
        }))
    selection = surface.put(root, selection["path"], doc)
    return root, selection, doc


@pytest.mark.parametrize("domain", ["surface", "solid"])
def test_polygon_attachment_registration_and_stale_views(tmp_path, monkeypatch, domain):
    """Execute real host registration and reject stale views without rewriting source payloads."""
    root, selection, doc = polygon_registration(tmp_path, domain)
    monkeypatch.setattr(attachment, "job_dir", lambda _: root)
    register = (attachment.register_solid_root_attachment_intent if domain == "solid"
                else attachment.register_surface_attachment_intent)
    register("fixture", intent_path=selection["path"], intent_sha256=selection["sha256"])
    assert selected_attachment(root, "fixture", root / "analysis/scene_spec.json") == selection
    parsed = attachment._parse_attachment_intent((root / selection["path"]).read_bytes())
    meshes = attachment._source_meshes(root, parsed)
    assert all(len(mesh.faces) == 12 and len(mesh.source.faces) == 6 for mesh in meshes.values())
    assert attachment.preflight_source_attachment(parsed, meshes)["status"] == "passed"
    (root / doc["source_triangle_views"][0]["path"]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        attachment._source_meshes(root, parsed)
    with pytest.raises(ValueError, match="changed"):
        selected_attachment(root, "fixture", root / "analysis/scene_spec.json")


def test_legacy_attachment_still_rejects_polygons(tmp_path):
    """Never broaden historical 0.1 source admission implicitly."""
    root, _selection, doc = polygon_registration(tmp_path, "solid")
    doc["schema_version"] = "0.1.0"
    del doc["source_triangle_views"]
    parsed = attachment._parse_attachment_intent(json.dumps(doc).encode())
    with pytest.raises(ValueError, match="triangulated"):
        attachment._source_meshes(root, parsed)


def test_legacy_payload_dispatch_rejects_polygon_before_io(tmp_path):
    """Require explicit payload 0.2 without creating a legacy materialization directory."""
    candidate = StructuralGeometryCandidate.model_validate_json(json.dumps({
        "semantic_id": "test.shell", "geometry": cube(),
    }))
    root = tmp_path / "absent"
    with pytest.raises(ValueError, match="explicit MeshPayload"):
        materialize_structural_candidate(job_root=root, candidate=candidate,
            candidate_relative_path="candidate.json", mesh_relative_path="mesh.json",
            blend_relative_path="mesh.blend", report_relative_path="report.json")
    assert not root.exists()


def test_expanded_budget_counts_quads_twice(tmp_path):
    """Reject an over-limit quad source even when its authored polygon count fits."""
    root, _selection, doc = polygon_registration(tmp_path, "solid")
    artifact = doc["source_geometry"][0]
    raw = json.loads((root / artifact["path"]).read_bytes())
    raw["faces"] = raw["faces"] * 342
    doc["source_geometry"][0] = surface.put(root, artifact["path"], raw)
    parsed = attachment._parse_attachment_intent(json.dumps(doc).encode())
    with pytest.raises(ValueError, match="expanded semantic triangle limit"):
        attachment._source_meshes(root, parsed)


def test_mixed_source_views_rejected(tmp_path):
    """Disallow a current view borrowed from another geometry payload or round."""
    root, _selection, doc = polygon_registration(tmp_path, "solid")
    selected = doc["source_triangle_views"][0]
    raw = json.loads((root / selected["path"]).read_bytes())
    raw["source_mesh"] = copy.deepcopy(doc["source_geometry"][1])
    doc["source_triangle_views"][0] = surface.put(root, selected["path"], raw)
    parsed = attachment._parse_attachment_intent(json.dumps(doc).encode())
    with pytest.raises(ValueError, match="repeats|mixed"):
        attachment._source_meshes(root, parsed)


def test_polygon_sealing_requires_complete_snapshot_closure(tmp_path):
    """Keep legacy partial report tests readable without letting new views omit their closure."""
    root, selection, _ = polygon_registration(tmp_path, "surface")
    extraction = surface.put(root, "audit/native.json", {"fixture": True})
    report = {"status": "passed", "intent": selection,
              "extraction_sha256": extraction["sha256"]}
    surface.put(root, "audit/native_report.json", report)
    with pytest.raises(ValueError, match="snapshots are missing"):
        attachment._capture_stage_evidence(root, root / "audit", "native", report)
