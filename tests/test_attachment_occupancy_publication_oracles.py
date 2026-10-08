"""Independent grid and publication-integrity regression cases."""

import hashlib
import json

import pytest
import test_surface_attachment_host as host_fixture
import test_surface_attachment_occupancy as fixture_api
from PIL import Image, ImageDraw

from codex_blender_modeler.packaging import attachment as host


def digest(path):
    """Bind the actual finished bytes for independent report assertions."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "missing_projection_directory",
        "changed_projection",
        "changed_trimap",
        "changed_coverage_report",
        "changed_extraction",
    ],
)
def test_published_coverage_must_retain_exact_inspected_bytes(tmp_path, monkeypatch, mutation):
    """A later stage cannot silently remove/change an earlier stage's selected diagnostic
    evidence."""
    root, intent, _, raw = fixture_api.fixture(tmp_path)
    selected = host_fixture.HashedArtifact(
        id="source.attachment_intent",
        kind="other",
        path="fixture_intent.json",
        sha256="0" * 64,
    )
    bound = host_fixture.source(selected)
    host_fixture.put(root, bound.blend.path, {"fixture_only": True})
    host_fixture.put(root, "converted.blend", {"fixture_only": True})
    host_fixture.put(root, "staging/asset.glb", {"fixture_only": True})
    stages = []

    def stage_fixture(root, source, artifact, stage, output):
        """Use the real adapter for PNG/report bytes; replace only native execution and
        mechanics."""
        stages.append(stage)
        host_fixture.put(root, output.relative_to(root).as_posix(), raw)
        coverage = fixture_api.assess(
            root,
            intent,
            raw,
            output.with_name(output.stem + "_reference_occupancy").relative_to(root).as_posix(),
        )
        report = {
            "status": "passed",
            "reference_region_coverage": coverage,
            "fixture_only": True,
            "extraction_sha256": digest(output),
        }
        host_fixture.put(
            root,
            output.with_name(output.stem + "_report.json").relative_to(root).as_posix(),
            report,
        )
        if stage == "clean_import_glb" and mutation is not None:
            earlier = output.parent / "native_evaluated_reference_occupancy"
            if mutation == "missing_projection_directory":
                earlier.rename(earlier.with_name("retained_original_native_coverage"))
            else:
                name = {
                    "changed_projection": "projection.png",
                    "changed_trimap": "reference_trimap.png",
                    "changed_coverage_report": "report.json",
                    "changed_extraction": None,
                }[mutation]
                path = earlier / name if name else output.parent / "native_evaluated.json"
                path.with_name("retained_original_" + path.name).write_bytes(path.read_bytes())
                path.write_bytes(path.read_bytes() + b"\n")
        return report

    monkeypatch.setattr(host, "inspect_stage", stage_fixture)
    arguments = dict(
        run_id="r1",
        package_id="p1",
        converted=root / "converted.blend",
        primary=root / "staging/asset.glb",
        staging_root=root / "staging",
    )
    if mutation is not None:
        with pytest.raises((ValueError, FileNotFoundError)):
            host.verify_package_attachment(root, bound, **arguments)
    else:
        host.verify_package_attachment(root, bound, **arguments)
        destination = root / "staging/metadata/attachment"
        summary = json.loads((destination / "summary.json").read_bytes())
        assert summary["status"] == "passed" and len(summary["evidence_files"]) == 15
        for name, expected in summary["evidence_files"].items():
            assert digest(destination / name) == expected


def test_single_missing_pixel_fails_despite_high_iou(tmp_path):
    """One isolated wrong sure pixel cannot hide inside an otherwise exact large union."""
    root, intent, _, _ = fixture_api.fixture(tmp_path)
    raw = fixture_api.target(
        [
            (4, 4, 12, 10),
            (4, 10, 10, 11),
            (11, 10, 12, 11),
            (4, 11, 12, 28),
            (20, 4, 28, 28),
            (12, 4, 20, 12),
            (12, 20, 20, 28),
        ]
    )
    report = fixture_api.assess(root, intent, raw)
    assert (
        report["status"] == "failed"
        and report["missing_foreground_pixels"] == 1
        and report["filled_background_pixels"] == 0
    )
    image = Image.open(root / report["projection"]["path"])
    assert image.getpixel((10, 10)) == 0
    assert report["projection"]["sha256"] == digest(root / report["projection"]["path"])
    assert (root / report["trimap_snapshot"]["path"]).read_bytes() == (
        root / "trimap.png"
    ).read_bytes()
    assert report["actual_geometry_origin_verified"] is False


@pytest.mark.parametrize(
    "resolution,outer,hole",
    [
        ((48, 32), (12, 10, 36, 22), (18, 13, 30, 19)),
        ((32, 48), (4, 18, 28, 30), (10, 21, 22, 27)),
    ],
)
def test_literal_non_square_camera_source_grid(resolution, outer, hole, tmp_path):
    """Literal world rectangles have separately specified Blender AUTO landscape/portrait pixel
    bounds."""
    root, intent, mask, _ = fixture_api.fixture(tmp_path)
    width, height = resolution
    left, t, r, b = outer
    hl, ht, hr, hb = hole
    image = Image.new("RGBA", resolution, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((left, t, r - 1, b - 1), fill=(100, 150, 200, 255))
    draw.rectangle((hl, ht, hr - 1, hb - 1), fill=(0, 0, 0, 0))
    image.save(root / "input/reference.png")
    image.getchannel("A").save(root / "trimap.png")
    ref = fixture_api.artifact(root, root / "input/reference.png")

    def norm(box):
        """Express separately asserted literal observation pixels as normalized evidence bounds."""
        return [box[0] / width, box[1] / height, box[2] / width, box[3] / height]

    scene = json.loads((root / intent.source_scene.path).read_bytes())
    scene["camera"]["resolution"] = list(resolution)
    scene["objects"][0]["evidence"][0]["bbox_norm"] = norm(outer)
    sb = fixture_api.put(root, intent.source_scene.path, scene)
    metadata = json.loads((root / "job.json").read_bytes())
    metadata["reference_sha256"] = ref["sha256"]
    metadata["sources"] = [{"kind": "reference", **ref}]
    fixture_api.put(root, "job.json", metadata)
    extent = json.loads((root / "extent.json").read_bytes())
    extent.update(
        reference=ref,
        reference_resolution=list(resolution),
        bbox_pixels=list(outer),
        foreground_pixel_count=216,
    )
    eb = fixture_api.put(root, "extent.json", extent)
    mask.update(
        reference=ref,
        reference_resolution=list(resolution),
        trimap=fixture_api.artifact(root, root / "trimap.png"),
        subject_extent=eb,
    )
    mask["seeds"][0]["bbox_norm"] = norm((left + 1, t + 1, left + 3, t + 3))
    mask["label_observations"][0]["bbox_norm"] = norm((left, t, left + 4, t + 3))
    mask["label_observations"][1]["bbox_norm"] = norm((0, 0, 2, 2))
    mb = fixture_api.put(root, "regions.json", mask)
    doc = intent.model_dump(mode="json")
    doc.update(source_reference=ref, source_scene=sb, reference_region_evidence=mb)
    chosen = fixture_api.AttachmentIntentV01.model_validate_json(json.dumps(doc))
    triangles = []
    for x0, z0, x1, z1 in [
        (-0.5, -0.25, -0.25, 0.25),
        (0.25, -0.25, 0.5, 0.25),
        (-0.25, -0.25, 0.25, -0.125),
        (-0.25, 0.125, 0.25, 0.25),
    ]:
        corners = [[x0, 0.0, z0], [x1, 0.0, z0], [x1, 0.0, z1], [x0, 0.0, z1]]
        for f in ((0, 1, 2), (0, 2, 3)):
            triangles.append({"corners": [corners[i] for i in f], "material_id": "mat.body"})
    report = fixture_api.assess(
        root,
        chosen,
        {"objects": [{"semantic_id": "asset.body", "triangles": triangles}]},
    )
    assert (
        report["status"] == "passed"
        and report["missing_foreground_pixels"] == report["filled_background_pixels"] == 0
    )
    actual = Image.open(root / report["projection"]["path"])
    assert actual.tobytes() == image.getchannel("A").tobytes()
    assert actual.getbbox() == outer and actual.histogram()[255] == 216
