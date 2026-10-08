"""Adversarial correspondence, source-selection and complete-owner host tests."""

import copy
import hashlib
import json
import struct
from types import SimpleNamespace as NS

import pytest

from codex_blender_modeler.attachment_runtime import (
    REGISTRATION_PATH,
    artifact_bytes,
    selected_attachment,
)
from codex_blender_modeler.optimization import provenance
from codex_blender_modeler.optimization.models import HashedArtifact, SourceProvenance
from codex_blender_modeler.packaging import attachment as m
from codex_blender_modeler.structural_geometry.attachment_companion import (
    AttachmentIntentV01,
)
from codex_blender_modeler.structural_geometry.mesh_payload_v02 import (
    MeshPayloadSourceHashV02,
    canonical_json_sha256,
    source_hash_fingerprint,
)


def box(name, front=0.0, back=0.2, low=0.0, high=1.0, labels=("front", "back", "side")):
    """Create a complete outward closed box with exact explicit face groups."""
    vertices = [(low, y, low) for y in ()]
    for y in (front, back):
        vertices += [(low, y, low), (high, y, low), (high, y, high), (low, y, high)]
    faces = [
        [0, 1, 2],
        [0, 2, 3],
        [4, 6, 5],
        [4, 7, 6],
        [0, 4, 5],
        [0, 5, 1],
        [1, 5, 6],
        [1, 6, 2],
        [2, 6, 7],
        [2, 7, 3],
        [3, 7, 4],
        [3, 4, 0],
    ]
    return NS(
        semantic_id=name,
        vertices=vertices,
        faces=faces,
        material_slots=[NS(material_id="mat.shared")],
        face_groups=[
            NS(id=labels[0], face_indices=[0, 1]),
            NS(id=labels[1], face_indices=[2, 3]),
            NS(id=labels[2], face_indices=list(range(4, 12))),
        ],
    )


def actual(mesh):
    """Simulate serialized positions for correspondence tests, never native evidence."""
    vertices = [tuple(struct.unpack("f", struct.pack("f", x))[0] for x in p) for p in mesh.vertices]
    return {
        "semantic_id": mesh.semantic_id,
        "triangles": [
            {"corners": [vertices[i] for i in face], "material_id": "mat.shared"}
            for face in mesh.faces
        ],
    }


def intent():
    """Define one required complete patch with strict finite bounds."""
    return AttachmentIntentV01.model_validate_json(
        json.dumps(
            {
                "job_id": "fixture",
                "source_reference": {"path": "input/reference.png", "sha256": "3" * 64},
                "source_modeling_plan": {
                    "path": "analysis/modeling_plan.json",
                    "sha256": "4" * 64,
                },
                "source_scene": {
                    "path": "analysis/scene_spec.json",
                    "sha256": "0" * 64,
                },
                "source_geometry": [
                    {"path": "geometry/owner.json", "sha256": "1" * 64},
                    {"path": "geometry/relief.json", "sha256": "2" * 64},
                ],
                "entries": [
                    {
                        "attachment_id": "ridge",
                        "scope": "required_full_patch",
                        "subject_lower": {
                            "semantic_id": "relief",
                            "face_group_id": "lower",
                        },
                        "subject_upper": {
                            "semantic_id": "relief",
                            "face_group_id": "upper",
                        },
                        "owner_front": {
                            "semantic_id": "owner",
                            "face_group_id": "front",
                        },
                        "owner_back": {"semantic_id": "owner", "face_group_id": "back"},
                        "minimum_embed_m": 0.01,
                        "maximum_embed_m": 0.03,
                        "minimum_remaining_thickness_m": 0.1,
                        "minimum_relief_height_m": 0.01,
                    }
                ],
            }
        )
    )


def fixture():
    """Supply separate complete closed owner and embedded raised subject."""
    meshes = {
        "owner": box("owner"),
        "relief": box("relief", -0.1, 0.02, 0.2, 0.8, ("upper", "lower", "side")),
    }
    return meshes, {"objects": [actual(mesh) for mesh in meshes.values()]}


def partial_root_fixture():
    """Use a closed fin whose selected buried left root is a strict subset of both full caps."""
    vertices = [(x, y, z) for y in (0.05, 0.15) for z in (0.2, 0.8) for x in (0.2, 0.8, 1.4)]
    faces = [
        [0, 1, 4],
        [0, 4, 3],
        [1, 2, 5],
        [1, 5, 4],
        [6, 10, 7],
        [6, 9, 10],
        [7, 11, 8],
        [7, 10, 11],
    ]
    boundary = [0, 1, 2, 5, 4, 3]
    for a, b in zip(boundary, boundary[1:] + boundary[:1], strict=True):
        faces.extend([[a, a + 6, b + 6], [a, b + 6, b]])
    subject = NS(
        semantic_id="relief",
        vertices=vertices,
        faces=faces,
        material_slots=[NS(material_id="mat.shared")],
        face_groups=[
            NS(id="upper", face_indices=[0, 1]),
            NS(id="lower", face_indices=[4, 5]),
            NS(id="free_upper", face_indices=[2, 3]),
            NS(id="free_lower", face_indices=[6, 7]),
            NS(id="side", face_indices=list(range(8, len(faces)))),
        ],
    )
    meshes = {"owner": box("owner"), "relief": subject}
    raw = {"objects": [actual(mesh) for mesh in meshes.values()]}
    doc = intent().model_dump(mode="json")
    entry = doc["entries"][0]
    entry["scope"] = "required_root_patch"
    for key in (
        "minimum_embed_m",
        "maximum_embed_m",
        "minimum_remaining_thickness_m",
        "minimum_relief_height_m",
    ):
        entry[key] = None
    entry["minimum_overlap_m"] = 0.01
    return AttachmentIntentV01.model_validate_json(json.dumps(doc)), meshes, raw


def test_partial_buried_root_uses_complete_solid_and_only_declared_contact():
    """A buried root passes without claiming that the free fin outside the owner overlaps it."""
    selected, meshes, raw = partial_root_fixture()
    report = m.evaluate_actual(selected, meshes, raw)
    assert report["status"] == "passed"
    row = report["entries"][0]
    assert row["subject_solid"]["front_triangle_count"] == 4
    assert row["selected_root_front_triangle_count"] == 2
    assert row["free_subject_area_overlap_claimed"] is False
    assert row["outward_exposure_required"] is False


def test_root_scope_does_not_ignore_cavity():
    """Whole-owner cavity negatives remain mandatory even for a partial insertion region."""
    selected, meshes, raw = partial_root_fixture()
    cavity = box("cavity", 0.01, 0.19, 0.1, 0.9)
    cavity.faces = [list(reversed(face)) for face in cavity.faces]
    append_component(meshes["owner"], cavity, "cavity.")
    raw["objects"][0] = actual(meshes["owner"])
    with pytest.raises(ValueError, match="inward"):
        m.evaluate_actual(selected, meshes, raw)


def test_relief_mode_still_refuses_two_cherry_picked_cap_subsets():
    """Root support does not weaken full-relief whole-base completeness."""
    _, meshes, raw = partial_root_fixture()
    meshes["owner"] = box("owner", high=2.0)
    raw["objects"][0] = actual(meshes["owner"])
    assert m.evaluate_actual(intent(), meshes, raw)["status"] == "failed"


@pytest.mark.parametrize("scope", ["required_full_patch", "required_root_patch"])
def test_cap_aliases_cannot_certify_attachment_to_same_component(scope):
    """Distinct face-group names cannot disguise that subject and owner are the same solid."""
    mesh = box("owner")
    mesh.face_groups += [
        NS(id="alias.upper", face_indices=[0, 1]),
        NS(id="alias.lower", face_indices=[2, 3]),
    ]
    doc = intent().model_dump(mode="json")
    entry = doc["entries"][0]
    entry["subject_upper"] = {"semantic_id": "owner", "face_group_id": "alias.upper"}
    entry["subject_lower"] = {"semantic_id": "owner", "face_group_id": "alias.lower"}
    entry["scope"] = scope
    if scope == "required_root_patch":
        for key in (
            "minimum_embed_m",
            "maximum_embed_m",
            "minimum_remaining_thickness_m",
            "minimum_relief_height_m",
        ):
            entry[key] = None
        entry["minimum_overlap_m"] = 0.01
    with pytest.raises(ValueError, match="same complete component"):
        m.evaluate_actual(
            AttachmentIntentV01.model_validate_json(json.dumps(doc)),
            {"owner": mesh},
            {"objects": [actual(mesh)]},
        )


def test_distinct_attached_components_may_share_semantic_identity():
    """Grouping real closed solids keeps honest component ownership without extra mesh IDs."""
    meshes, _ = fixture()
    append_component(meshes["owner"], meshes["relief"], "relief.")
    doc = intent().model_dump(mode="json")
    doc["entries"][0]["subject_upper"] = {
        "semantic_id": "owner",
        "face_group_id": "relief.upper",
    }
    doc["entries"][0]["subject_lower"] = {
        "semantic_id": "owner",
        "face_group_id": "relief.lower",
    }
    report = m.evaluate_actual(
        AttachmentIntentV01.model_validate_json(json.dumps(doc)),
        {"owner": meshes["owner"]},
        {"objects": [actual(meshes["owner"])]},
    )
    assert report["status"] == "passed"
    assert not set(report["entries"][0]["owner_source_faces"]) & set(
        report["entries"][0]["subject_source_faces"]
    )


def append_component(mesh, other, prefix):
    """Group a complete same-material component without changing its topology or cost."""
    offset, face_offset = len(mesh.vertices), len(mesh.faces)
    mesh.vertices += other.vertices
    mesh.faces += [[v + offset for v in face] for face in other.faces]
    mesh.face_groups += [
        NS(id=prefix + g.id, face_indices=[i + face_offset for i in g.face_indices])
        for g in other.face_groups
    ]


def test_grouped_component_complete_proof():
    """Two relief solids may share one semantic mesh while the selected component stays complete."""
    meshes, raw = fixture()
    append_component(
        meshes["relief"],
        box("other", -0.1, 0.02, 1.2, 1.8, ("upper", "lower", "side")),
        "other.",
    )
    raw["objects"][1] = actual(meshes["relief"])
    result = m.evaluate_actual(intent(), meshes, raw)
    assert result["status"] == "passed"
    assert result["entries"][0]["subject_source_faces"] == list(range(12))
    assert result["entries"][0]["owner_solid"]["owner_volume_verified"] is True
    assert result["actual_triangle_extraction_verified"] is False


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "reverse", "material", "moved", "foreign"]
)
def test_forged_actual_geometry_refused(mutation):
    """Unmatched, ambiguous, reversed, foreign, changed or wrong-material triangles fail."""
    mesh = box("owner")
    raw = actual(mesh)
    if mutation == "missing":
        raw["triangles"].pop()
    if mutation == "duplicate":
        raw["triangles"][1] = copy.deepcopy(raw["triangles"][0])
    if mutation == "reverse":
        raw["triangles"][0]["corners"].reverse()
    if mutation == "material":
        raw["triangles"][0]["material_id"] = "mat.other"
    if mutation == "moved":
        raw["triangles"][0]["corners"][0] = (5.0, 0.0, 0.0)
    if mutation == "foreign":
        raw["semantic_id"] = "wrong_owner"
    with pytest.raises(ValueError):
        m.map_actual_mesh(mesh, raw)


def test_subtolerance_crack_not_welded():
    """Position matching tolerance cannot hide a split shared vertex in actual geometry."""
    mesh = box("owner")
    raw = actual(mesh)
    raw["triangles"][0]["corners"][0] = (0.0000005, 0.0, 0.0)
    with pytest.raises(ValueError, match="missing or ambiguous"):
        m.map_actual_mesh(mesh, raw)


def test_complete_lower_group_required():
    """Deleting half the selected lower faces cannot shrink the proof to a convenient sample."""
    meshes, raw = fixture()
    meshes["relief"].face_groups[1].face_indices = [2]
    result = m.evaluate_actual(intent(), meshes, raw)
    assert result["status"] == "failed"


def test_wrong_owner_layer_refused():
    """Swapped front/back planes cannot establish real solid containment."""
    meshes, raw = fixture()
    meshes["owner"].face_groups[0].face_indices = [2, 3]
    meshes["owner"].face_groups[1].face_indices = [0, 1]
    assert m.evaluate_actual(intent(), meshes, raw)["status"] == "failed"


def test_hollow_owner_inner_shell_cannot_be_ignored():
    """An inward cavity component is rejected even if the selected outer box looks valid."""
    meshes, raw = fixture()
    inner = box("cavity", 0.01, 0.19, 0.1, 0.9)
    inner.faces = [list(reversed(face)) for face in inner.faces]
    append_component(meshes["owner"], inner, "cavity.")
    raw["objects"][0] = actual(meshes["owner"])
    with pytest.raises(ValueError, match="inward"):
        m.evaluate_actual(intent(), meshes, raw)


def test_split_open_cavity_faces_cannot_be_ignored():
    """Individually indexed inward cavity triangles remain disallowed omitted open components."""
    meshes, raw = fixture()
    owner = meshes["owner"]
    cavity = box("cavity", 0.01, 0.19, 0.1, 0.9)
    for face in cavity.faces:
        indices = []
        for index in reversed(face):
            indices.append(len(owner.vertices))
            owner.vertices.append(cavity.vertices[index])
        owner.faces.append(indices)
    raw["objects"][0] = actual(owner)
    with pytest.raises(ValueError, match="open or non-manifold"):
        m.evaluate_actual(intent(), meshes, raw)


def test_positive_volume_pinched_cavity_rejected():
    """A positive sum-volume extra component cannot hide an inward shell at a nonmanifold vertex."""
    meshes, raw = fixture()
    owner = meshes["owner"]
    cavity = box("cavity", 0.01, 0.19, 0.1, 0.9)
    cavity.faces = [list(reversed(face)) for face in cavity.faces]
    append_component(owner, cavity, "cavity.")
    extra = box("positive_extra", 0.01, 1.01, 0.1, 1.1)
    offset = len(owner.vertices) - 1
    owner.vertices.extend(extra.vertices[1:])
    owner.faces.extend([[8 if i == 0 else i + offset for i in face] for face in extra.faces])
    raw["objects"][0] = actual(owner)
    with pytest.raises(ValueError):
        m.evaluate_actual(intent(), meshes, raw)


def put(root, name, value):
    """Store only small isolated test bytes and return their exact input binding."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value).encode()
    path.write_bytes(data)
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}


def bind_metadata(root, selection):
    """Create explicit test-only registration/metadata agreement, never production authority."""
    doc = json.loads((root / selection["path"]).read_bytes())
    metadata = {
        "job_id": "fixture",
        "sources": [{"kind": "reference", **doc["source_reference"]}],
    }
    original = put(root, "job.json", metadata)
    registration = put(
        root,
        REGISTRATION_PATH,
        {
            "schema_version": "0.1.0",
            "kind": "surface_attachment_registration",
            "job_id": "fixture",
            "attachment_intent": selection,
            "metadata_before_sha256": original["sha256"],
        },
    )
    put(
        root,
        "job.json",
        {
            **metadata,
            "attachment_intent": selection,
            "attachment_registration_sha256": registration["sha256"],
        },
    )


def selected_fixture(root):
    """Create a narrow explicit metadata/intent/source binding for provenance tests."""
    scene = put(root, "analysis/scene_spec.json", {"job_id": "fixture"})
    geometry = put(root, "geometry/mesh.json", {"vertices": []})
    doc = intent().model_dump(mode="json")
    doc["source_reference"] = put(root, "input/reference.png", {"fixture_image_bytes": True})
    doc["source_modeling_plan"] = put(root, "analysis/modeling_plan.json", {"job_id": "fixture"})
    doc["source_scene"] = scene
    doc["source_geometry"] = [geometry]
    selection = put(root, "analysis/attachment_intent.json", doc)
    bind_metadata(root, selection)
    return selection


def test_explicit_selection_binds_source_bytes(tmp_path):
    """Selected missing/stale source bytes are errors, never legacy fallback."""
    selected_fixture(tmp_path)
    assert selected_attachment(tmp_path, "fixture", tmp_path / "analysis/scene_spec.json")
    (tmp_path / "geometry/mesh.json").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        selected_attachment(tmp_path, "fixture", tmp_path / "analysis/scene_spec.json")


@pytest.mark.parametrize("relative", ["input/reference.png", "analysis/modeling_plan.json"])
def test_reference_and_modeling_plan_staleness_block_native_selection(tmp_path, relative):
    """Reference and ModelingPlan are rehashed unconditionally, even without spatial plan
    helpers."""
    selected_fixture(tmp_path)
    (tmp_path / relative).write_text("changed exact selected context")
    with pytest.raises(ValueError, match="changed"):
        selected_attachment(tmp_path, "fixture", tmp_path / "analysis/scene_spec.json")


@pytest.mark.parametrize("dependency", ["reference", "trimap", "subject_extent"])
def test_selected_regions_rehash_nested_bytes_in_stdlib_reader(tmp_path, dependency):
    """Native source closure verifies transitive hashes without importing image libraries."""
    selected_fixture(tmp_path)
    path = tmp_path / "analysis/attachment_intent.json"
    doc = json.loads(path.read_bytes())
    reference = doc["source_reference"]
    trimap = put(tmp_path, "analysis/fixture-trimap.png", {"hash_only_fixture": True})
    extent = put(
        tmp_path,
        "analysis/extent.json",
        {
            "schema_version": "0.1.0",
            "contract_kind": "reference_subject_extent_evidence",
            "job_id": "fixture",
            "reference": reference,
        },
    )
    regions = put(
        tmp_path,
        "analysis/regions.json",
        {
            "schema_version": "0.3.0",
            "contract_kind": "reference_mask_seed_evidence",
            "job_id": "fixture",
            "reference": reference,
            "trimap": trimap,
            "subject_extent": extent,
        },
    )
    doc["reference_region_evidence"] = regions
    selection = put(tmp_path, "analysis/attachment_intent.json", doc)
    bind_metadata(tmp_path, selection)
    assert selected_attachment(tmp_path, "fixture", tmp_path / "analysis/scene_spec.json")
    changed = {"reference": reference, "trimap": trimap, "subject_extent": extent}[dependency]
    (tmp_path / changed["path"]).write_text("changed selected nested source")
    with pytest.raises(ValueError, match="changed"):
        selected_attachment(tmp_path, "fixture", tmp_path / "analysis/scene_spec.json")


def test_unselected_conventional_file_does_not_activate(tmp_path):
    """A similarly named file has no authority to activate the optional check."""
    selected_fixture(tmp_path)
    put(tmp_path, "job.json", {"job_id": "fixture"})
    (tmp_path / REGISTRATION_PATH).unlink()
    assert selected_attachment(tmp_path, "fixture", tmp_path / "analysis/scene_spec.json") is None


@pytest.mark.parametrize("removal", ["selector", "receipt", "metadata"])
def test_registered_selection_cannot_disappear(tmp_path, removal):
    """Missing either side of the immutable registration latch fails before rebuilding."""
    selected_fixture(tmp_path)
    if removal == "selector":
        put(tmp_path, "job.json", {"job_id": "fixture"})
    elif removal == "receipt":
        (tmp_path / REGISTRATION_PATH).unlink()
    else:
        (tmp_path / "job.json").unlink()
    with pytest.raises(ValueError, match="incomplete|missing"):
        selected_attachment(tmp_path, "fixture", tmp_path / "analysis/scene_spec.json")


def test_selected_symlink_refused(tmp_path):
    """An in-root alias remains an unsupported link, not an accepted artifact."""
    selected_fixture(tmp_path)
    original = tmp_path / "geometry/mesh.json"
    data = original.read_bytes()
    original.unlink()
    target = tmp_path / "geometry/other.json"
    target.write_bytes(data)
    original.symlink_to(target)
    with pytest.raises(ValueError, match="link"):
        selected_attachment(tmp_path, "fixture", tmp_path / "analysis/scene_spec.json")


def source(selected=None):
    """Construct a strict source contract to verify additive serialization and freshness."""

    def artifact(kind, path):
        return HashedArtifact(id=kind, kind=kind, path=path, sha256="0" * 64)

    return SourceProvenance(
        scene_spec=artifact("scene_spec", "analysis/scene_spec.json"),
        blend=artifact("blend", "blender/scene.blend"),
        source_fingerprint="1" * 64,
        build_fingerprint="2" * 64,
        attachment_intent=selected,
    )


def test_absence_preserves_legacy_and_removal_fails_frozen_run(tmp_path, monkeypatch):
    """No-selection bytes stay absent, but an already selected run cannot downgrade."""
    legacy = source()
    assert "attachment_intent" not in legacy.model_dump(mode="json")
    selected = HashedArtifact(
        id="source.attachment_intent",
        kind="other",
        path="analysis/attachment.json",
        sha256="3" * 64,
    )
    bound = source(selected)
    assert selected in bound.artifacts()
    monkeypatch.setattr(provenance, "collect_source_provenance", lambda *a: legacy)
    with pytest.raises(RuntimeError, match="changed"):
        provenance.require_unchanged_source(bound, tmp_path, "fixture")


def test_selected_stage_refuses_preexisting_extraction(tmp_path):
    """A caller cannot supply a stale supposedly native snapshot instead of running inspection."""
    selected = HashedArtifact(
        id="source.attachment_intent",
        kind="other",
        path="analysis/attachment.json",
        sha256="3" * 64,
    )
    output = tmp_path / "forged.json"
    output.write_text("{}")
    with pytest.raises(FileExistsError, match="freshly"):
        m.inspect_stage(
            tmp_path,
            source(selected),
            tmp_path / "asset.glb",
            "clean_import_glb",
            output,
        )


def test_source_artifact_rehash_rejects_forgery(tmp_path):
    """Hash-bound artifact loading rejects forged bytes at the same selected path."""
    ref = put(tmp_path, "intent.json", {"truth": True})
    (tmp_path / "intent.json").write_text('{"truth":false}')
    with pytest.raises(ValueError, match="changed"):
        artifact_bytes(tmp_path, ref)


def strict_payload(mesh, root):
    """Create a valid single-slot MeshPayload using the real existing strict source contract."""
    dependency = put(root, "evidence/source.json", {"fixture": True})
    source_hash = {"role": "structural_candidate", **dependency}
    groups = [{"id": g.id, "face_indices": g.face_indices} for g in mesh.face_groups]
    weighted = {
        "enabled": False,
        "keep_sharp": True,
        "weight_mode": "FACE_AREA_WITH_ANGLE",
        "disposition": "reject",
    }
    subdivision = {
        "enabled": False,
        "levels": 0,
        "render_levels": 0,
        "subdivision_type": "CATMULL_CLARK",
        "boundary_smoothing": "PRESERVE_CORNERS",
        "disposition": "reject",
    }
    surface = {"mode": "flat", "angle_degrees": None, "keep_explicit_sharp": True}
    source_intent = {
        "face_groups": groups,
        "material_assignments": [
            {"face_group_id": g.id, "material_id": "mat.shared"} for g in mesh.face_groups
        ],
        "sharp_edges": [],
        "uv_seams": [],
        "edge_creases": [],
        "bevel_weights": [],
        "smoothing_policy": surface,
        "topology_profile": "static_prop_closed",
        "weighted_normal_intent": weighted,
        "subdivision_intent": subdivision,
    }
    count = len(mesh.faces)
    return {
        "schema_version": "0.2.0",
        "semantic_id": mesh.semantic_id,
        "builder_kind": "custom_mesh",
        "vertices": mesh.vertices,
        "faces": mesh.faces,
        "loop_count": count * 3,
        "loop_uvs": [[0.0, 0.0]] * (count * 3),
        "material_slots": [{"slot_index": 0, "material_id": "mat.shared"}],
        "polygon_material_indices": [0] * count,
        "sharp_edges": [],
        "uv_seams": [],
        "edge_creases": [],
        "bevel_weights": [],
        "face_groups": groups,
        "smooth_polygon_flags": [False] * count,
        "smoothing_policy": surface,
        "custom_attribute_manifest": [],
        "modifier_materialization_policy": [],
        "weighted_normal_intent": weighted,
        "subdivision_intent": subdivision,
        "source_geometry_intent": {
            "source_intent_sha256": canonical_json_sha256(source_intent),
            **source_intent,
        },
        "findings": [],
        "source_hashes": [source_hash],
        "source_fingerprint_sha256": source_hash_fingerprint(
            [MeshPayloadSourceHashV02.model_validate(source_hash)]
        ),
    }


def registration_fixture(tmp_path):
    """Prepare an unbuilt real strict source and optional companion for host selection tests."""
    root = tmp_path / "fixture"
    root.mkdir()
    meshes, raw = fixture()
    geometry, objects = [], []
    for name, mesh in meshes.items():
        path = f"geometry/{name}.json"
        geometry.append(put(root, path, strict_payload(mesh, root)))
        objects.append(
            {
                "id": name,
                "geometry": {"kind": "custom_mesh", "path": path},
                "transform": {
                    "location": [0, 0, 0],
                    "rotation_deg": [0, 0, 0],
                    "scale": [1, 1, 1],
                },
                "modifiers": [],
                "generator": None,
                "parent_id": None,
            }
        )
    scene = put(root, "analysis/scene_spec.json", {"job_id": "fixture", "objects": objects})
    doc = intent().model_dump(mode="json")
    doc.update(source_scene=scene, source_geometry=geometry)
    doc["source_reference"] = put(root, "input/reference.png", {"fixture_image_bytes": True})
    doc["source_modeling_plan"] = put(root, "analysis/modeling_plan.json", {"job_id": "fixture"})
    selection = put(root, "analysis/attachment_intent.json", doc)
    put(
        root,
        "job.json",
        {
            "job_id": "fixture",
            "sources": [{"kind": "reference", **doc["source_reference"]}],
        },
    )
    return root, selection, raw


def test_real_registration_and_built_reuse_refusal(tmp_path, monkeypatch):
    """Only the host function selects exact source before first build; built selection cannot
    replay."""
    root, selection, _ = registration_fixture(tmp_path)
    monkeypatch.setattr(m, "job_dir", lambda _: root)
    selected = m.register_surface_attachment_intent(
        "fixture", intent_path=selection["path"], intent_sha256=selection["sha256"]
    )
    assert selected == selection
    reports = list((root / "reports/surface_attachment").glob("source-*.json"))
    assert len(reports) == 1
    preflight = json.loads(reports[0].read_bytes())
    assert preflight["status"] == "passed"
    assert preflight["stage"] == "source_float32_prediction"
    assert preflight["actual_triangle_extraction_verified"] is False
    assert selected_attachment(root, "fixture", root / "analysis/scene_spec.json") == selection
    put(root, "blender/scene.blend", {"fake_fixture_only": True})
    with pytest.raises(ValueError, match="unbuilt"):
        m.register_surface_attachment_intent(
            "fixture", intent_path=selection["path"], intent_sha256=selection["sha256"]
        )


def test_source_overhang_fails_before_registration_or_native_work(tmp_path, monkeypatch):
    """An unsupported full relief footprint is refused before material or bake work."""
    root, selection, _ = registration_fixture(tmp_path)
    overhang = box("relief", -0.1, 0.02, 0.8, 1.4, ("upper", "lower", "side"))
    geometry = put(root, "geometry/relief.json", strict_payload(overhang, root))
    doc = json.loads((root / selection["path"]).read_bytes())
    doc["source_geometry"][1] = geometry
    selection = put(root, selection["path"], doc)
    monkeypatch.setattr(m, "job_dir", lambda _: root)
    with pytest.raises(ValueError, match="source attachment preflight"):
        m.register_surface_attachment_intent(
            "fixture", intent_path=selection["path"], intent_sha256=selection["sha256"]
        )
    assert "attachment_intent" not in json.loads((root / "job.json").read_bytes())
    assert not (root / REGISTRATION_PATH).exists()
    assert not (root / "blender/scene.blend").exists()


def test_registration_refuses_changed_selected_intent(tmp_path, monkeypatch):
    """A second valid source-bound intent cannot replace the previously selected meaning."""
    root, selection, _ = registration_fixture(tmp_path)
    monkeypatch.setattr(m, "job_dir", lambda _: root)
    m.register_surface_attachment_intent(
        "fixture", intent_path=selection["path"], intent_sha256=selection["sha256"]
    )
    new = json.loads((root / selection["path"]).read_bytes())
    new["entries"][0]["maximum_embed_m"] = 0.04
    changed = put(root, "analysis/attachment_other.json", new)
    with pytest.raises(ValueError, match="cannot change"):
        m.register_surface_attachment_intent(
            "fixture", intent_path=changed["path"], intent_sha256=changed["sha256"]
        )


@pytest.mark.parametrize(
    "field", ["build_fingerprint", "source_fingerprint", "intent_sha256", "artifact"]
)
def test_fresh_extraction_mixed_artifact_projection_refused(tmp_path, monkeypatch, field):
    """Even a fresh result with plausible triangles must match every exact host request binding."""
    root, selection, raw_geometry = registration_fixture(tmp_path)
    bind_metadata(root, selection)
    put(root, "asset.glb", {"fixture_only": True})
    selected = HashedArtifact(id="source.attachment_intent", kind="other", **selection)
    bound = source(selected)
    doc = json.loads((root / selection["path"]).read_bytes())
    bound = bound.model_copy(
        update={
            "scene_spec": HashedArtifact(id="scene_spec", kind="scene_spec", **doc["source_scene"]),
            "geometry_payloads": [
                HashedArtifact(id=f"geometry.{i}", kind="geometry_payload", **entry)
                for i, entry in enumerate(doc["source_geometry"])
            ],
        }
    )

    def forged_runner(script, arguments, **kwargs):
        """Simulate a faulty extraction projection without invoking Blender."""
        values = dict(zip(arguments[::2], arguments[1::2], strict=True))
        assert script == "inspect_surface_attachment_geometry.py"
        report = {
            "schema_version": "0.1.0",
            "kind": "surface_attachment_actual_triangles",
            "blender_version": "5.0.1",
            "stage": "clean_import_glb",
            "artifact": {"path": "asset.glb", "sha256": values["--artifact-sha256"]},
            "source_fingerprint": bound.source_fingerprint,
            "build_fingerprint": bound.build_fingerprint,
            "intent_sha256": selected.sha256,
            "triangle_count": 24,
            **raw_geometry,
        }
        report[field] = (
            {"path": "other.glb", "sha256": "0" * 64} if field == "artifact" else "0" * 64
        )
        (root / "extracted.json").write_text(json.dumps(report))

    monkeypatch.setattr(m, "run_blender", forged_runner)
    with pytest.raises(ValueError, match="exact host request"):
        m.inspect_stage(
            root, bound, root / "asset.glb", "clean_import_glb", root / "extracted.json"
        )


@pytest.mark.parametrize("coverage_status", ["passed", "failed", "unverified"])
def test_fresh_stage_preserves_selected_coverage_failure(tmp_path, monkeypatch, coverage_status):
    """A mechanical pass cannot overwrite a selected image-region failure or attest omitted
    coverage."""
    from codex_blender_modeler.qa import attachment_occupancy

    root, selection, raw_geometry = registration_fixture(tmp_path)
    bind_metadata(root, selection)
    put(root, "asset.glb", {"fixture_only": True})
    selected = HashedArtifact(id="source.attachment_intent", kind="other", **selection)
    bound = source(selected)
    doc = json.loads((root / selection["path"]).read_bytes())
    bound = bound.model_copy(
        update={
            "scene_spec": HashedArtifact(id="scene_spec", kind="scene_spec", **doc["source_scene"]),
            "geometry_payloads": [
                HashedArtifact(id=f"geometry.{i}", kind="geometry_payload", **entry)
                for i, entry in enumerate(doc["source_geometry"])
            ],
        }
    )

    def fixture_runner(script, arguments, **kwargs):
        """Exercise request validation using explicit API-double output, never native evidence."""
        values = dict(zip(arguments[::2], arguments[1::2], strict=True))
        put(
            root,
            "extracted.json",
            {
                "schema_version": "0.1.0",
                "kind": "surface_attachment_actual_triangles",
                "blender_version": "5.0.1",
                "stage": "clean_import_glb",
                "artifact": {
                    "path": "asset.glb",
                    "sha256": values["--artifact-sha256"],
                },
                "source_fingerprint": bound.source_fingerprint,
                "build_fingerprint": bound.build_fingerprint,
                "intent_sha256": selected.sha256,
                "triangle_count": 24,
                **raw_geometry,
            },
        )

    def coverage_fixture(*args, **kwargs):
        """Supply a fixed coverage outcome to isolate stage failure composition."""
        return {
            "status": coverage_status,
            "selected": coverage_status != "unverified",
            "actual_geometry_origin_verified": False,
        }

    monkeypatch.setattr(m, "run_blender", fixture_runner)
    monkeypatch.setattr(
        attachment_occupancy, "evaluate_reference_region_occupancy", coverage_fixture
    )
    if coverage_status == "failed":
        with pytest.raises(ValueError, match="failed or unverified"):
            m.inspect_stage(
                root,
                bound,
                root / "asset.glb",
                "clean_import_glb",
                root / "extracted.json",
            )
    else:
        report = m.inspect_stage(
            root, bound, root / "asset.glb", "clean_import_glb", root / "extracted.json"
        )
        assert report["status"] == "passed"
        assert report["reference_region_coverage"]["actual_geometry_origin_verified"] is (
            coverage_status == "passed"
        )
    saved = json.loads((root / "extracted_report.json").read_bytes())
    assert saved["reference_region_coverage"]["status"] == coverage_status
    assert saved["status"] == ("failed" if coverage_status == "failed" else "passed")


@pytest.mark.parametrize(
    "failing_stage",
    [
        None,
        "converted",
        "missing_projection_directory",
        "changed_projection",
        "changed_trimap",
        "changed_coverage_report",
        "changed_extraction",
        "changed_stage_report",
        "changed_copied_projection",
        "late_copied_projection",
        "late_summary",
        "late_native_artifact",
    ],
)
def test_package_copies_bound_coverage_only_after_all_stage_checks(
    tmp_path, monkeypatch, failing_stage
):
    """Staged publication receives every diagnostic, while a later failure leaves only audit
    evidence."""
    selected = HashedArtifact(
        id="source.attachment_intent",
        kind="other",
        path="analysis/intent.json",
        sha256="0" * 64,
    )
    bound = source(selected)
    put(tmp_path, bound.blend.path, {"fixture_only": True})
    put(tmp_path, "converted.blend", {"fixture_only": True})
    put(tmp_path, "staging/asset.glb", {"fixture_only": True})
    stages = []

    def stage_fixture(root, source, artifact, stage, output):
        """Produce deterministic host-wiring fixtures without asserting native extraction."""
        stages.append(stage)
        extraction = put(root, output.relative_to(root).as_posix(), {"stage": stage})
        if stage == failing_stage:
            raise ValueError("selected coverage mismatch")
        coverage = output.with_name(output.stem + "_reference_occupancy")
        region = {
            "status": "passed",
            "selected": True,
            "actual_geometry_origin_verified": False,
            "fixture_only": True,
        }
        for key, name in (
            ("projection", "projection.png"),
            ("trimap_snapshot", "reference_trimap.png"),
        ):
            region[key] = put(
                root,
                (coverage / name).relative_to(root).as_posix(),
                {"fixture_only": name},
            )
        put(root, (coverage / "report.json").relative_to(root).as_posix(), region)
        report = {
            "status": "passed",
            "fixture_only": True,
            "reference_region_coverage": region,
            "extraction_sha256": extraction["sha256"],
        }
        put(
            root,
            output.with_name(output.stem + "_report.json").relative_to(root).as_posix(),
            report,
        )
        if stage == "clean_import_glb":
            earlier = output.parent / "native_evaluated_reference_occupancy"
            if failing_stage == "missing_projection_directory":
                earlier.rename(earlier.with_name("retained_original_native_coverage"))
            elif (
                failing_stage
                and failing_stage.startswith("changed_")
                and failing_stage != "changed_copied_projection"
            ):
                target = {
                    "changed_projection": earlier / "projection.png",
                    "changed_trimap": earlier / "reference_trimap.png",
                    "changed_coverage_report": earlier / "report.json",
                    "changed_extraction": output.parent / "native_evaluated.json",
                    "changed_stage_report": output.parent / "native_evaluated_report.json",
                }[failing_stage]
                target.write_bytes(target.read_bytes() + b"\n")
        return report

    monkeypatch.setattr(m, "inspect_stage", stage_fixture)
    arguments = dict(
        run_id="r1",
        package_id="p1",
        converted=tmp_path / "converted.blend",
        primary=tmp_path / "staging/asset.glb",
        staging_root=tmp_path / "staging",
    )
    destination = tmp_path / "staging/metadata/attachment"
    if failing_stage == "changed_copied_projection":
        original_copy = m.shutil.copyfile

        def corrupt_copy(source, target):
            """A copying fault must fail before a success summary is written."""
            result = original_copy(source, target)
            if str(target).endswith("projection.png"):
                target.write_bytes(target.read_bytes() + b"\n")
            return result

        monkeypatch.setattr(m.shutil, "copyfile", corrupt_copy)
    if failing_stage and not failing_stage.startswith("late_"):
        with pytest.raises((ValueError, FileNotFoundError)):
            m.verify_package_attachment(tmp_path, bound, **arguments)
        assert not (destination / "summary.json").exists()
        assert (tmp_path / "optimization/runs/r1/attachment_checks/p1/asset.glb").is_file()
    else:
        closure = m.verify_package_attachment(tmp_path, bound, **arguments)
        assert stages == ["native_evaluated", "converted", "clean_import_glb"]
        for stage in stages:
            for name in ("projection.png", "reference_trimap.png", "report.json"):
                original = (
                    tmp_path
                    / "optimization/runs/r1/attachment_checks/p1"
                    / (stage + "_reference_occupancy")
                    / name
                )
                assert (
                    destination / (stage + "_reference_occupancy") / name
                ).read_bytes() == original.read_bytes()
        m._verify_package_attachment_closure(tmp_path, closure)
        if failing_stage:
            changed = {
                "late_copied_projection": destination
                / "native_evaluated_reference_occupancy/projection.png",
                "late_summary": destination / "summary.json",
                "late_native_artifact": tmp_path / bound.blend.path,
            }[failing_stage]
            changed.write_bytes(changed.read_bytes() + b"\n")
            with pytest.raises(ValueError, match="changed before publication"):
                m._verify_package_attachment_closure(tmp_path, closure)
