"""Independent original-alpha/source-grid binding and actual-output mismatch tests."""

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler import models as scene_models
from codex_blender_modeler.qa.attachment_occupancy import (
    evaluate_reference_region_occupancy,
)
from codex_blender_modeler.structural_geometry.attachment_companion import (
    AttachmentIntentV01,
)


def put(root, relative, payload):
    """Write exact fixture JSON and return its immutable artifact reference."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return artifact(root, path)


def artifact(root, path):
    """Hash fixture bytes after every intentional mutation."""
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def target(rectangles):
    """Triangulate exact source-grid rectangles without rendering or native claims."""
    triangles = []
    for left, top, right, bottom in rectangles:
        corners = [
            [(x - 16) / 16, 0.0, (16 - y) / 16]
            for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))
        ]
        for face in ((0, 1, 2), (0, 2, 3)):
            triangles.append({"corners": [corners[i] for i in face], "material_id": "mat.body"})
    return {
        "objects": [{"semantic_id": "asset.body", "triangles": triangles}],
        "stage": "fixture_only",
        "artifact": {"path": "fixture.glb", "sha256": "0" * 64},
        "source_fingerprint": "1" * 64,
        "build_fingerprint": "2" * 64,
        "intent_sha256": "3" * 64,
    }


def fixture(tmp_path):
    """Use a transparent original ring with a true central hole and a complete explicit V0.3
    mask."""
    root = tmp_path / "occupancy"
    (root / "input").mkdir(parents=True)
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 27, 27), fill=(60, 140, 180, 255))
    draw.rectangle((12, 12, 19, 19), fill=(0, 0, 0, 0))
    image.save(root / "input/reference.png")
    reference = artifact(root, root / "input/reference.png")
    image.getchannel("A").save(root / "trimap.png")
    repo = Path(scene_models.__file__).resolve().parents[2]
    raw = json.loads((repo / "examples/geometry_showcase/scene_spec.seed.json").read_text())
    raw.update(job_id="occupancy")
    raw["objects"] = raw["objects"][:1]
    raw["objects"][0].update(
        id="asset.body",
        tags=["qa_role:primary"],
        parent_id=None,
        evidence=[
            {
                "source_id": "ref.main",
                "bbox_norm": [0.125, 0.125, 0.875, 0.875],
                "status": "observed",
                "confidence": 1.0,
            }
        ],
    )
    raw["sources"] = [
        {
            "id": "ref.main",
            "kind": "reference",
            "path": "input/reference.png",
            "immutable": True,
        }
    ]
    raw["camera"] = {
        "projection": "ORTHO",
        "location": [0.0, -3.0, 0.0],
        "target": [0.0, 0.0, 0.0],
        "focal_length_mm": 50.0,
        "ortho_scale": 2.0,
        "resolution": [32, 32],
    }
    spec = scene_models.SceneSpec.model_validate(raw)
    scene = put(root, "analysis/scene_spec.json", spec.model_dump(mode="json"))
    plan = put(
        root,
        "analysis/modeling_plan.json",
        {
            "job_id": "occupancy",
            "reference_analysis_path": "analysis/reference_analysis.json",
            "camera_solution_path": "analysis/camera_solution.json",
            "stage": "authored",
            "objects": [{"id": "asset.body", "label": "Body", "scope_role": "primary"}],
        },
    )
    put(
        root,
        "job.json",
        {
            "job_id": "occupancy",
            "reference_content_scope": "primary_object_only",
            "target_subject": "reference ring",
            "reference_sha256": reference["sha256"],
            "sources": [{"kind": "reference", **reference}],
        },
    )
    extent = put(
        root,
        "extent.json",
        {
            "schema_version": "0.1.0",
            "contract_kind": "reference_subject_extent_evidence",
            "job_id": "occupancy",
            "reference": reference,
            "reference_resolution": [32, 32],
            "reference_content_scope": "primary_object_only",
            "subject_object_ids": ["asset.body"],
            "observation_id": "original-alpha",
            "bbox_pixels": [4, 4, 28, 28],
            "foreground_pixel_count": 512,
            "confidence": 1.0,
            ("uncertainty"): (
                "Original alpha only; no recovered hidden geometry or artistic acceptance."
            ),
        },
    )
    mask = {
        "schema_version": "0.3.0",
        "contract_kind": "reference_mask_seed_evidence",
        "job_id": "occupancy",
        "reference": reference,
        "trimap": artifact(root, root / "trimap.png"),
        "subject_extent": extent,
        "reference_resolution": [32, 32],
        "subject_object_ids": ["asset.body"],
        "seeds": [
            {
                "object_id": "asset.body",
                "source_id": "ref.main",
                "observation_id": "solid-interior",
                "bbox_norm": [0.1875, 0.1875, 0.25, 0.25],
                "confidence": 1.0,
            }
        ],
        "label_observations": [
            {
                "observation_id": "original-fg",
                "bbox_norm": [0.15625, 0.15625, 0.28125, 0.28125],
                "label": "foreground",
                "confidence": 1.0,
            },
            {
                "observation_id": "original-bg",
                "bbox_norm": [0.0, 0.0, 0.0625, 0.0625],
                "label": "background",
                "confidence": 1.0,
            },
        ],
    }
    evidence = put(root, "regions.json", mask)
    geometry = put(root, "geometry.json", {"fixture_only": True})
    intent = AttachmentIntentV01.model_validate_json(
        json.dumps(
            {
                "job_id": "occupancy",
                "source_reference": reference,
                "source_modeling_plan": plan,
                "source_scene": scene,
                "source_geometry": [geometry],
                "reference_region_evidence": evidence,
                "entries": [
                    {
                        "attachment_id": "fixture.sheet",
                        "scope": "intentional_open",
                        "subject_lower": {
                            "semantic_id": "asset.body",
                            "face_group_id": "sheet",
                        },
                        ("exception_reason"): (
                            "Fixture tests only image-grid occupancy, not mechanical attachment."
                        ),
                    }
                ],
            }
        )
    )
    rectangles = [(4, 4, 12, 28), (20, 4, 28, 28), (12, 4, 20, 12), (12, 20, 20, 28)]
    return root, intent, mask, target(rectangles)


def assess(root, intent, raw, name="coverage"):
    """Run the real source-binding adapter without claiming fixture data came from Blender."""
    return evaluate_reference_region_occupancy(root, intent, raw, output_dir=root / name)


def test_absent_regions_are_unverified(tmp_path):
    """Missing opt-in is visible and never counts as reference-region coverage."""
    root, intent, _, raw = fixture(tmp_path)
    result = assess(root, intent.model_copy(update={"reference_region_evidence": None}), raw)
    assert result["status"] == "unverified" and result["selected"] is False
    assert not (root / "coverage").exists()


def test_all_sure_pixels_match_original_ring(tmp_path):
    """Every declared original foreground/background pixel agrees at the exact original grid."""
    root, intent, _, raw = fixture(tmp_path)
    result = assess(root, intent, raw)
    assert result["status"] == "passed"
    assert result["missing_foreground_pixels"] == result["filled_background_pixels"] == 0
    assert result["actual_geometry_origin_verified"] is False
    assert result["source_camera_fingerprint"]
    assert (root / "coverage/projection.png").is_file()


@pytest.mark.parametrize(
    "change", ["missing", "stale", "cropped", "swapped", "alpha_contradiction"]
)
def test_invalid_region_data_cannot_create_pass(tmp_path, change):
    """Missing/stale data and rehashed cropped/swapped/false sure pixels remain failures."""
    root, intent, mask, raw = fixture(tmp_path)
    path = root / "trimap.png"
    if change == "missing":
        path.unlink()
    elif change == "stale":
        path.write_bytes(b"changed")
    else:
        image = Image.open(path).copy()
        if change == "cropped":
            image = image.crop((4, 4, 28, 28))
        elif change == "swapped":
            image = image.point(lambda x: 255 - x)
        else:
            image.putpixel((25, 25), 0)
        image.save(path)
        mask["trimap"] = artifact(root, path)
        chosen = put(root, "regions_changed.json", mask)
        doc = intent.model_dump(mode="json")
        doc["reference_region_evidence"] = chosen
        intent = AttachmentIntentV01.model_validate_json(json.dumps(doc))
    with pytest.raises((ValueError, FileNotFoundError)):
        assess(root, intent, raw)


def test_output_gap_is_measured_without_filling(tmp_path):
    """A missing stripe of actual geometry remains missing in all 192 sure original pixels."""
    root, intent, _, _ = fixture(tmp_path)
    raw = target([(20, 4, 28, 28), (12, 4, 20, 12), (12, 20, 20, 28)])
    result = assess(root, intent, raw)
    assert result["status"] == "failed" and result["missing_foreground_pixels"] == 192
    assert result["gap_filling_applied"] is False


def test_filled_original_hole_fails(tmp_path):
    """Closing a true transparent original hole is reported as 64 wrong sure-background pixels."""
    root, intent, _, _ = fixture(tmp_path)
    result = assess(root, intent, target([(4, 4, 28, 28)]))
    assert result["status"] == "failed" and result["filled_background_pixels"] == 64


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate"])
def test_actual_subject_membership_must_be_complete(tmp_path, change):
    """A geometric union cannot hide omitted, extra or duplicate semantic identities."""
    root, intent, _, raw = fixture(tmp_path)
    if change == "missing":
        raw["objects"] = []
    elif change == "extra":
        raw["objects"].append({**raw["objects"][0], "semantic_id": "invented.subject"})
    else:
        raw["objects"].append(raw["objects"][0])
    with pytest.raises(ValueError, match="bounded extracted|subject membership"):
        assess(root, intent, raw)


@pytest.mark.parametrize(
    "change", ["stale", "tilted", "resolution", "perspective", "sensor", "pixel_aspect"]
)
def test_camera_tamper_and_unsupported_projection_refused(tmp_path, change):
    """Only the exact frozen supported source-camera grid may be used."""
    root, intent, _, raw = fixture(tmp_path)
    path = root / intent.source_scene.path
    scene = json.loads(path.read_bytes())
    camera = scene["camera"]
    if change in {"stale", "tilted"}:
        camera["location"][0] = 0.1
    elif change == "resolution":
        camera["resolution"] = [64, 64]
    elif change == "perspective":
        camera["projection"] = "PERSP"
    elif change == "sensor":
        camera["sensor_fit"] = "VERTICAL"
    else:
        camera["pixel_aspect_x"] = 2.0
    selected = put(root, intent.source_scene.path, scene)
    if change != "stale":
        doc = intent.model_dump(mode="json")
        doc["source_scene"] = selected
        intent = AttachmentIntentV01.model_validate_json(json.dumps(doc))
    with pytest.raises(ValueError):
        assess(root, intent, raw)
