"""Root-region host selection, full-component and immutable publication tests."""

import copy
import hashlib
import json

import pytest
import test_surface_attachment_host as f
from pydantic import ValidationError

from codex_blender_modeler.attachment_runtime import _rehash_root_regions
from codex_blender_modeler.packaging import attachment as m
from codex_blender_modeler.structural_geometry.attachment_companion import (
    AttachmentIntentV01,
    RootRegionSelectionV01,
)


def root_doc():
    """Choose an interior polygon larger than the component-anchor face subset."""
    return dict(
        schema_version="0.1.0",
        contract_kind="surface_attachment_root_region",
        job_id="fixture",
        attachment_id="ridge",
        subject_lower={"semantic_id": "relief", "face_group_id": "lower"},
        owner_front={"semantic_id": "owner", "face_group_id": "front"},
        frame_axes=[0, 2, 1],
        frame_signs=[1, 1, 1],
        polygon=[[0.3, 0.3], [0.9, 0.3], [0.9, 0.7], [0.3, 0.7]],
    )


def region_fixture():
    """Keep existing complete geometry and select immutable region bytes separately."""
    intent, meshes, raw = f.partial_root_fixture()
    doc = intent.model_dump(mode="json")
    doc["entries"] = [
        dict(
            attachment_id="ridge",
            scope="required_root_patch",
            root_region={"path": "analysis/root.json", "sha256": "a" * 64},
            minimum_overlap_m=0.01,
        )
    ]
    selected = AttachmentIntentV01.model_validate_json(json.dumps(doc))
    region = RootRegionSelectionV01.model_validate_json(json.dumps(root_doc()))
    return selected, meshes, raw, {"ridge": region}


def test_region_uses_full_component_not_anchor_triangles():
    """The polygon extends past the anchor's x=.8 edge but inside the complete fin."""
    intent, meshes, raw, regions = region_fixture()
    before = copy.deepcopy(raw)
    result = m.evaluate_actual(intent, meshes, raw, root_regions=regions)
    assert result["status"] == "passed"
    row = result["entries"][0]
    assert len(row["anchor_source_faces"]["subject_lower"]) == 2
    assert len(row["complete_clipping_source_faces"]["subject_back"]) == 4
    assert row["owner_solid"]["passed"] and row["subject_solid"]["passed"]
    assert before == raw


def test_region_unresolved_cannot_be_inferred():
    """Selected-but-unloaded polygons never fall back to legacy contact selection."""
    intent, meshes, raw, _ = region_fixture()
    assert m.evaluate_actual(intent, meshes, raw)["status"] == "unverified"
    with pytest.raises(ValueError, match="missing, extra or mixed"):
        m.evaluate_actual(intent, meshes, raw, root_regions={})


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", "other"),
        ("attachment_id", "other"),
        ("frame_axes", [2, 0, 1]),
        ("frame_signs", [-1, 1, 1]),
    ],
)
def test_region_binding_mismatch_rejected(field, value):
    """Region identity and projection must match the outer relation exactly."""
    intent, meshes, raw, regions = region_fixture()
    doc = root_doc()
    doc[field] = value
    regions["ridge"] = RootRegionSelectionV01.model_validate_json(json.dumps(doc))
    with pytest.raises(ValueError, match="differs"):
        m.evaluate_actual(intent, meshes, raw, root_regions=regions)


@pytest.mark.parametrize(
    "extra",
    [
        {"subject_lower": {"semantic_id": "relief", "face_group_id": "lower"}},
        {"subject_upper": {"semantic_id": "relief", "face_group_id": "upper"}},
        {"minimum_embed_m": 0.01},
        {"scope": "intentional_open", "exception_reason": "free tip"},
        {"scope": "required_full_patch"},
    ],
)
def test_mixed_or_wrong_scope_selection_rejected(extra):
    """Root polygons cannot expand into full-relief or exception modes."""
    intent, _, _, _ = region_fixture()
    doc = intent.model_dump(mode="json")
    doc["entries"][0].update(extra)
    with pytest.raises(ValidationError):
        AttachmentIntentV01.model_validate_json(json.dumps(doc))


@pytest.mark.parametrize(
    "polygon",
    [
        [[0.3, 0.3], [1.1, 0.3], [1.1, 0.7], [0.3, 0.7]],
        [[0.3, 0.3], [0.3, 0.7], [0.9, 0.3], [0.9, 0.7]],
    ],
)
def test_escaped_or_invalid_polygon_not_passed(polygon):
    """Unsupported rings and any positive owner gap remain failed or unverified."""
    intent, meshes, raw, regions = region_fixture()
    doc = root_doc()
    doc["polygon"] = polygon
    regions["ridge"] = RootRegionSelectionV01.model_validate_json(json.dumps(doc))
    assert m.evaluate_actual(intent, meshes, raw, root_regions=regions)["status"] != "passed"


def test_region_does_not_skip_whole_solid_cavity():
    """The clipped root cannot certify a hollow inward shell."""
    intent, meshes, raw, regions = region_fixture()
    cavity = f.box("cavity", 0.01, 0.19, 0.1, 0.9)
    cavity.faces = [list(reversed(face)) for face in cavity.faces]
    f.append_component(meshes["owner"], cavity, "cavity.")
    raw["objects"][0] = f.actual(meshes["owner"])
    with pytest.raises(ValueError, match="inward"):
        m.evaluate_actual(intent, meshes, raw, root_regions=regions)


@pytest.mark.parametrize(
    "change",
    [
        "stale",
        "missing",
        "symlink",
        "wrong_job",
        "nested_ring",
        "boolean_coordinate",
        "extra_field",
    ],
)
def test_stdlib_root_dependency_closure(tmp_path, change):
    """Native closure checks exact selected region bytes without optional geometry imports."""
    doc = root_doc()
    if change == "wrong_job":
        doc["job_id"] = "other"
    if change == "nested_ring":
        doc["polygon"] = [doc["polygon"]] * 3
    if change == "boolean_coordinate":
        doc["polygon"][0][0] = True
    if change == "extra_field":
        doc["authority"] = True
    ref = f.put(tmp_path, "analysis/root.json", doc)
    payload = {
        "entries": [dict(attachment_id="ridge", scope="required_root_patch", root_region=ref)]
    }
    path = tmp_path / ref["path"]
    if change == "stale":
        path.write_text("{}")
    if change == "missing":
        path.rename(tmp_path / "retained.json")
    if change == "symlink":
        path.rename(tmp_path / "retained.json")
        path.symlink_to(tmp_path / "retained.json")
    with pytest.raises((ValueError, FileNotFoundError)):
        _rehash_root_regions(tmp_path, payload, "fixture")


def test_bound_host_loader_and_stdlib_accept_same_valid_region(tmp_path):
    """Only explicit matching region bytes activate the mode in both host contexts."""
    selected, _, _, _ = region_fixture()
    doc = selected.model_dump(mode="json")
    doc["entries"][0]["root_region"] = f.put(tmp_path, "analysis/root.json", root_doc())
    intent = AttachmentIntentV01.model_validate_json(json.dumps(doc))
    regions = m.load_root_regions(tmp_path, intent)
    assert regions["ridge"].polygon[0] == (0.3, 0.3)
    _rehash_root_regions(tmp_path, doc, "fixture")


@pytest.mark.parametrize(
    "mutation", [None, "changed", "missing", "duplicate", "extra", "wrong_source"]
)
def test_snapshot_publication_exact_closure(tmp_path, mutation):
    """Publication seals complete region snapshots and rejects alteration or omission."""
    audit = tmp_path / "audit"
    stage = "native_evaluated"
    data = json.dumps(root_doc()).encode()
    digest = hashlib.sha256(data).hexdigest()
    name = m._region_snapshot_name("ridge")
    relative = f"audit/{stage}_root_regions/{name}"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    source = {"path": "analysis/root.json", "sha256": digest}
    snapshot = {
        "attachment_id": "ridge",
        "source": source,
        "snapshot": {"path": relative, "sha256": digest},
    }
    extraction = f.put(tmp_path, f"audit/{stage}.json", {"fixture": True})
    report = {
        "status": "passed",
        "reference_region_coverage": {"selected": False},
        "entries": [{"attachment_id": "ridge", "root_region": source}],
        "root_region_snapshots": [snapshot],
        "extraction_sha256": extraction["sha256"],
    }
    if mutation == "changed":
        path.write_bytes(b"changed")
    if mutation == "missing":
        report["root_region_snapshots"] = []
    if mutation == "duplicate":
        report["root_region_snapshots"].append(copy.deepcopy(snapshot))
    if mutation == "extra":
        report["root_region_snapshots"].append({**snapshot, "attachment_id": "other"})
    if mutation == "wrong_source":
        snapshot["source"] = {**source, "path": "elsewhere.json"}
    f.put(tmp_path, f"audit/{stage}_report.json", report)
    if mutation is None:
        result = m._capture_stage_evidence(tmp_path, audit, stage, report)
        assert f"{stage}_root_regions/{name}" in result
    else:
        with pytest.raises(ValueError):
            m._capture_stage_evidence(tmp_path, audit, stage, report)


def test_absent_selection_legacy_serialization_unchanged():
    """Optional root mode adds no null selector to historical face-group documents."""
    assert "root_region" not in f.intent().model_dump(mode="json")["entries"][0]


def registered_region_fixture(tmp_path, monkeypatch):
    """Use real strict geometry and registration, before any simulated native build."""
    root, selection, raw = f.registration_fixture(tmp_path)
    doc = json.loads((root / selection["path"]).read_bytes())
    region = root_doc()
    region["polygon"] = [[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.3, 0.7]]
    artifact = f.put(root, "analysis/root.json", region)
    doc["entries"] = [
        dict(
            attachment_id="ridge",
            scope="required_root_patch",
            root_region=artifact,
            minimum_overlap_m=0.01,
        )
    ]
    selection = f.put(root, selection["path"], doc)
    monkeypatch.setattr(m, "job_dir", lambda _: root)
    assert (
        m.register_surface_attachment_intent(
            "fixture", intent_path=selection["path"], intent_sha256=selection["sha256"]
        )
        == selection
    )
    return root, selection, raw, doc


def test_real_region_registration_is_immutable(tmp_path, monkeypatch):
    """Initial host registration binds nested region, and later tampering fails closed."""
    root, selection, _, _ = registered_region_fixture(tmp_path, monkeypatch)
    assert f.selected_attachment(root, "fixture", root / "analysis/scene_spec.json") == selection
    (root / "analysis/root.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        f.selected_attachment(root, "fixture", root / "analysis/scene_spec.json")


@pytest.mark.parametrize("stage", ["native_evaluated", "converted", "clean_import_glb"])
def test_fresh_stage_preserves_exact_root_snapshot(tmp_path, monkeypatch, stage):
    """Every supported actual stage retains selected source bytes in its own closure."""
    root, selection, raw, doc = registered_region_fixture(tmp_path, monkeypatch)
    f.put(root, "asset.glb", {"fixture_only": True})
    selected = f.HashedArtifact(id="source.attachment_intent", kind="other", **selection)
    bound = f.source(selected).model_copy(
        update={
            "scene_spec": f.HashedArtifact(
                id="scene_spec", kind="scene_spec", **doc["source_scene"]
            ),
            "geometry_payloads": [
                f.HashedArtifact(id=f"geometry.{i}", kind="geometry_payload", **entry)
                for i, entry in enumerate(doc["source_geometry"])
            ],
        }
    )
    output = root / f"audit/{stage}.json"
    output.parent.mkdir()

    def runner(script, arguments, **kwargs):
        """Return an exact host-bound test extraction; this is not native execution evidence."""
        values = dict(zip(arguments[::2], arguments[1::2], strict=True))
        report = {
            "schema_version": "0.1.0",
            "kind": "surface_attachment_actual_triangles",
            "blender_version": "5.0.1",
            "stage": stage,
            "artifact": {"path": "asset.glb", "sha256": values["--artifact-sha256"]},
            "source_fingerprint": bound.source_fingerprint,
            "build_fingerprint": bound.build_fingerprint,
            "intent_sha256": selected.sha256,
            "triangle_count": 24,
            **raw,
        }
        output.write_text(json.dumps(report))

    monkeypatch.setattr(m, "run_blender", runner)
    report = m.inspect_stage(root, bound, root / "asset.glb", stage, output)
    assert report["status"] == "passed"
    snapshot = report["root_region_snapshots"][0]
    assert (root / snapshot["snapshot"]["path"]).read_bytes() == (
        root / "analysis/root.json"
    ).read_bytes()
    assert len(m._capture_stage_evidence(root, output.parent, stage, report)) == 3
