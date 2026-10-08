"""Independent final-schema, anchor-role and package-closure oracles."""

import hashlib
import json
from pathlib import Path

import pytest
import test_root_region_host as region_fixture
import test_surface_attachment_host as fixture

from codex_blender_modeler.packaging import attachment as host
from codex_blender_modeler.structural_geometry.attachment_companion import (
    AttachmentIntentV01,
    RootRegionSelectionV01,
)

STAGED = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "filename, model",
    [
        ("surface_attachment_root_region_v01.schema.json", RootRegionSelectionV01),
        ("surface_attachment_intent_v01.schema.json", AttachmentIntentV01),
    ],
)
def test_published_schema_exact_model_parity(filename, model):
    """Require exact schema/model parity for both affected generated projections."""
    assert json.loads((STAGED / "schemas" / filename).read_bytes()) == model.model_json_schema()


@pytest.mark.parametrize("change", ["subject_wrong_role", "owner_wrong_role", "self_support"])
def test_component_anchor_role_or_self_support_refused(change):
    """Preserve cap-role checks and refuse self-supporting solids."""
    intent, meshes, raw, regions = region_fixture.region_fixture()
    doc = region_fixture.root_doc()
    if change == "subject_wrong_role":
        doc["subject_lower"]["face_group_id"] = "upper"
    elif change == "owner_wrong_role":
        doc["owner_front"]["face_group_id"] = "back"
    else:
        doc["owner_front"] = {"semantic_id": "relief", "face_group_id": "upper"}
    regions["ridge"] = RootRegionSelectionV01.model_validate_json(json.dumps(doc))
    with pytest.raises(ValueError, match="role|alias"):
        host.evaluate_actual(intent, meshes, raw, root_regions=regions)


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "source_during",
        "snapshot_during",
        "report_during",
        "source_after",
        "destination_after",
    ],
)
def test_full_package_root_closure_rechecked(tmp_path, monkeypatch, mutation):
    """Seal root sources, snapshots and copied evidence through final publication."""
    root = tmp_path
    selected = fixture.HashedArtifact(
        id="source.attachment_intent", kind="other", path="fixture.json", sha256="0" * 64
    )
    bound = fixture.source(selected)
    fixture.put(root, bound.blend.path, {"fixture_only": True})
    fixture.put(root, "converted.blend", {"fixture_only": True})
    fixture.put(root, "staging/asset.glb", {"fixture_only": True})
    source = fixture.put(root, "analysis/root.json", region_fixture.root_doc())
    region_bytes = (root / source["path"]).read_bytes()
    name = host._region_snapshot_name("ridge")
    stages = []

    def inspect(root, source_binding, artifact, stage, output):
        """Exercise actual package closure machinery using test-only extraction records."""
        stages.append(stage)
        extraction = fixture.put(root, output.relative_to(root).as_posix(), {"fixture_only": True})
        snapshot_path = output.with_name(output.stem + "_root_regions") / name
        snapshot_path.parent.mkdir()
        snapshot_path.write_bytes(region_bytes)
        report = {
            "status": "passed",
            "reference_region_coverage": {"selected": False},
            "entries": [{"attachment_id": "ridge", "root_region": source}],
            "root_region_snapshots": [
                {
                    "attachment_id": "ridge",
                    "source": source,
                    "snapshot": {
                        "path": snapshot_path.relative_to(root).as_posix(),
                        "sha256": hashlib.sha256(region_bytes).hexdigest(),
                    },
                }
            ],
            "extraction_sha256": extraction["sha256"],
        }
        fixture.put(
            root,
            output.with_name(output.stem + "_report.json").relative_to(root).as_posix(),
            report,
        )
        if stage == "clean_import_glb":
            if mutation == "source_during":
                (root / source["path"]).write_bytes(b"changed")
            elif mutation == "snapshot_during":
                (output.parent / "native_evaluated_root_regions" / name).write_bytes(b"changed")
            elif mutation == "report_during":
                (output.parent / "native_evaluated_report.json").write_bytes(b"changed")
        return report

    monkeypatch.setattr(host, "inspect_stage", inspect)
    arguments = dict(
        run_id="r1",
        package_id="p1",
        converted=root / "converted.blend",
        primary=root / "staging/asset.glb",
        staging_root=root / "staging",
    )
    if mutation in {"source_during", "snapshot_during", "report_during"}:
        with pytest.raises(ValueError, match="changed"):
            host.verify_package_attachment(root, bound, **arguments)
        return
    closure = host.verify_package_attachment(root, bound, **arguments)
    assert stages == ["native_evaluated", "converted", "clean_import_glb"]
    assert closure["inspected_artifacts"][source["path"]] == source["sha256"]
    assert len(closure["audit_files"]) == 9
    for stage in stages:
        copied = root / "staging/metadata/attachment" / (stage + "_root_regions") / name
        assert copied.read_bytes() == region_bytes
    if mutation == "source_after":
        (root / source["path"]).write_bytes(b"changed")
    elif mutation == "destination_after":
        copied.write_bytes(b"changed")
    if mutation is None:
        host._verify_package_attachment_closure(root, closure)
    else:
        with pytest.raises(ValueError, match="changed"):
            host._verify_package_attachment_closure(root, closure)
