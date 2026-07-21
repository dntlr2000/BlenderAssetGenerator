import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.qa import (
    QATargetManifest,
    VisualQARequest,
    camera_fingerprint,
    compare_reference_to_render,
    create_visual_qa_request,
    generate_optional_qa_target,
    merge_advisory_target_result,
    observed_regions_from_scene_spec,
    require_camera_fingerprint,
    validate_visual_qa_request,
)
from codex_blender_modeler.qa.direct_compare import _overall_direct_score
from codex_blender_modeler.qa.models import (
    REQUIRED_QA_PASS_KINDS,
    BoundingBoxMetric,
    DirectVisualMetrics,
    RenderPassManifest,
    RenderPassRecord,
    SemanticDeviation,
)
from codex_blender_modeler.workspace import sha256_file

SHA = "0" * 64


def _request(mask_path: Path, include_target: bool = False) -> VisualQARequest:
    """Build one hash-complete fixed-camera request for isolated QA tests."""

    return VisualQARequest(
        job_id="qa_test",
        run_id="run-001",
        mode="concept",
        reference_path=str(mask_path),
        reference_sha256=SHA,
        reference_mask_path=str(mask_path),
        reference_mask_sha256=SHA,
        preview_path=str(mask_path),
        preview_sha256=SHA,
        render_pass_manifest_path="qa_pass_manifest.json",
        render_pass_manifest_sha256=SHA,
        scene_spec_sha256=SHA,
        camera_fingerprint=SHA,
        include_generated_target=include_target,
    )


def _rectangle_image(
    path: Path,
    *,
    rgb: bool = False,
    box: tuple[int, int, int, int] = (20, 10, 59, 49),
) -> None:
    """Write one deterministic rectangular foreground fixture at a chosen bbox."""

    image = Image.new("RGB" if rgb else "L", (100, 80), (0, 0, 0) if rgb else 0)
    draw = ImageDraw.Draw(image)
    draw.rectangle(box, fill=(255, 0, 0) if rgb else 255)
    image.save(path)


def _pass_records(
    path: str,
    *,
    width: int,
    height: int,
    sha256: str = SHA,
) -> list[RenderPassRecord]:
    """Create the complete V0.6 seven-pass fixture at one resolution."""

    return [
        RenderPassRecord(
            kind=kind,
            path=path,
            sha256=sha256,
            width=width,
            height=height,
            encoding="png-rgb8",
        )
        for kind in REQUIRED_QA_PASS_KINDS
    ]


def test_camera_fingerprint_detects_fixed_camera_changes() -> None:
    """Camera fingerprints remain stable and reject changed comparison framing."""

    camera = {
        "projection": "ORTHO",
        "location": [5, -8, 6],
        "target": [0, 0, 1],
        "focal_length_mm": 50,
        "ortho_scale": 12,
        "resolution": [640, 480],
    }
    first = camera_fingerprint(camera)
    assert camera_fingerprint(dict(camera)) == first
    changed = {**camera, "ortho_scale": 13}
    with pytest.raises(ValueError, match="comparison camera changed"):
        require_camera_fingerprint(changed, first)


def test_direct_compare_scores_identical_masks_and_localizes_semantic_id(
    tmp_path: Path,
) -> None:
    """Direct QA returns perfect masks and stable semantic bounding boxes for identical input."""

    mask = tmp_path / "reference_mask.png"
    object_id = tmp_path / "object_id.png"
    _rectangle_image(mask)
    _rectangle_image(object_id, rgb=True)
    report = compare_reference_to_render(
        _request(mask),
        silhouette_path=mask,
        object_id_path=object_id,
        object_id_colors={"asset.body": "#ff0000"},
        observed_regions={"asset.body": ((0.2, 0.125, 0.6, 0.625), 0.95)},
    )
    assert report.direct_metrics.silhouette_iou == 1.0
    assert report.direct_metrics.overall_direct_score == 1.0
    assert report.direct_metrics.scoring_version == "semantic_bbox_v2"
    assert report.direct_metrics.semantic_deviations[0].target_id == "asset.body"
    assert report.findings == []


def test_direct_compare_score_improves_when_semantic_bbox_alignment_improves(
    tmp_path: Path,
) -> None:
    """Semantic center corrections improve score even when the global silhouette is fixed."""

    mask = tmp_path / "reference_mask.png"
    aligned_id = tmp_path / "aligned_object_id.png"
    shifted_id = tmp_path / "shifted_object_id.png"
    _rectangle_image(mask)
    _rectangle_image(aligned_id, rgb=True)
    _rectangle_image(shifted_id, rgb=True, box=(40, 20, 79, 59))
    kwargs = {
        "object_id_colors": {"asset.body": "#ff0000"},
        "observed_regions": {"asset.body": ((0.2, 0.125, 0.6, 0.625), 0.95)},
    }

    shifted = compare_reference_to_render(
        _request(mask),
        silhouette_path=mask,
        object_id_path=shifted_id,
        **kwargs,
    )
    aligned = compare_reference_to_render(
        _request(mask),
        silhouette_path=mask,
        object_id_path=aligned_id,
        **kwargs,
    )

    assert shifted.direct_metrics.silhouette_iou == aligned.direct_metrics.silhouette_iou == 1
    assert shifted.direct_metrics.global_bbox == aligned.direct_metrics.global_bbox
    assert shifted.direct_metrics.overall_direct_score < aligned.direct_metrics.overall_direct_score
    assert aligned.direct_metrics.overall_direct_score == 1.0


def test_direct_compare_semantic_score_weights_missing_ids_by_confidence(
    tmp_path: Path,
) -> None:
    """Missing semantic IDs penalize the direct score in proportion to evidence confidence."""

    mask = tmp_path / "reference_mask.png"
    object_id = tmp_path / "object_id.png"
    _rectangle_image(mask)
    _rectangle_image(object_id, rgb=True)
    colors = {"asset.present": "#ff0000", "asset.missing": "#00ff00"}
    reference_bbox = (0.2, 0.125, 0.6, 0.625)

    low_confidence_missing = compare_reference_to_render(
        _request(mask),
        silhouette_path=mask,
        object_id_path=object_id,
        object_id_colors=colors,
        observed_regions={
            "asset.present": (reference_bbox, 0.9),
            "asset.missing": (reference_bbox, 0.1),
        },
    )
    high_confidence_missing = compare_reference_to_render(
        _request(mask),
        silhouette_path=mask,
        object_id_path=object_id,
        object_id_colors=colors,
        observed_regions={
            "asset.present": (reference_bbox, 0.1),
            "asset.missing": (reference_bbox, 0.9),
        },
    )

    assert low_confidence_missing.direct_metrics.overall_direct_score == 1.0
    assert high_confidence_missing.direct_metrics.overall_direct_score == 0.75
    assert (
        low_confidence_missing.direct_metrics.overall_direct_score
        > high_confidence_missing.direct_metrics.overall_direct_score
    )


def test_direct_compare_without_semantic_evidence_preserves_legacy_weights(
    tmp_path: Path,
) -> None:
    """Jobs without reliable semantic evidence retain the legacy silhouette/bbox score."""

    reference = tmp_path / "reference_mask.png"
    shifted = tmp_path / "shifted_silhouette.png"
    _rectangle_image(reference)
    _rectangle_image(shifted, box=(30, 10, 69, 49))

    report = compare_reference_to_render(
        _request(reference),
        silhouette_path=shifted,
    )

    bbox = report.direct_metrics.global_bbox
    expected_bbox_score = 1.0 - (bbox.center_error_norm or 0.0) - (
        bbox.size_error_norm or 0.0
    )
    expected = round(
        0.75 * report.direct_metrics.silhouette_iou + 0.25 * expected_bbox_score,
        6,
    )
    assert report.direct_metrics.overall_direct_score == expected
    assert report.direct_metrics.scoring_version == "legacy_bbox_v1"


def test_direct_compare_low_confidence_semantics_preserve_legacy_score(
    tmp_path: Path,
) -> None:
    """Evidence below the executable direct-confidence threshold cannot activate V2."""

    mask = tmp_path / "reference_mask.png"
    object_id = tmp_path / "object_id.png"
    _rectangle_image(mask)
    _rectangle_image(object_id, rgb=True)
    baseline = compare_reference_to_render(
        _request(mask),
        silhouette_path=mask,
    )
    low_confidence = compare_reference_to_render(
        _request(mask),
        silhouette_path=mask,
        object_id_path=object_id,
        object_id_colors={"asset.missing": "#00ff00"},
        observed_regions={
            "asset.missing": ((0.2, 0.125, 0.6, 0.625), 0.699999),
        },
    )

    assert low_confidence.direct_metrics.scoring_version == "legacy_bbox_v1"
    assert (
        low_confidence.direct_metrics.overall_direct_score
        == baseline.direct_metrics.overall_direct_score
        == 1.0
    )


def test_semantic_score_caps_nested_ids_to_one_group_vote() -> None:
    """Duplicating aligned nested IDs cannot increase one group's total scoring weight."""

    perfect = BoundingBoxMetric(
        reference_bbox_norm=(0.1, 0.1, 0.9, 0.9),
        rendered_bbox_norm=(0.1, 0.1, 0.9, 0.9),
        center_error_norm=0,
        size_error_norm=0,
    )
    missing = BoundingBoxMetric(
        reference_bbox_norm=(0.1, 0.1, 0.9, 0.9),
        rendered_bbox_norm=None,
    )
    global_bbox = perfect
    one_forest = [
        SemanticDeviation(target_id="island.forest.zone", metric=perfect, confidence=0.9),
        SemanticDeviation(target_id="island.volcano.rim", metric=missing, confidence=0.9),
    ]
    many_forest = [
        *[
            SemanticDeviation(
                target_id=f"island.forest.part_{index}",
                metric=perfect,
                confidence=0.9,
            )
            for index in range(10)
        ],
        SemanticDeviation(target_id="island.volcano.rim", metric=missing, confidence=0.9),
    ]

    one_score, one_version = _overall_direct_score(0.5, global_bbox, one_forest)
    many_score, many_version = _overall_direct_score(0.5, global_bbox, many_forest)

    assert one_version == many_version == "semantic_bbox_v2"
    assert many_score == one_score


def test_observed_regions_filter_multiple_reference_source_ids(tmp_path: Path) -> None:
    """Primary-reference filtering excludes a higher-confidence auxiliary-view bbox."""

    source = Path(__file__).resolve().parents[1] / "examples" / "geometry_showcase" / (
        "scene_spec.seed.json"
    )
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["sources"].append(
        {
            "id": "view.front",
            "path": "input/front.png",
            "kind": "front",
            "immutable": True,
            "scale_anchors": [],
        }
    )
    target = raw["objects"][0]
    target["evidence"] = [
        {
            "source_id": "ref.main",
            "bbox_norm": [0.1, 0.1, 0.4, 0.4],
            "status": "observed",
            "confidence": 0.8,
        },
        {
            "source_id": "view.front",
            "bbox_norm": [0.6, 0.6, 0.9, 0.9],
            "status": "observed",
            "confidence": 0.99,
        },
    ]
    scene_path = tmp_path / "scene_spec.json"
    scene_path.write_text(json.dumps(raw), encoding="utf-8")

    regions = observed_regions_from_scene_spec(
        scene_path,
        source_ids={"ref.main", "ref.secondary"},
    )

    assert regions[target["id"]] == ((0.1, 0.1, 0.4, 0.4), 0.8)


def test_legacy_direct_metrics_json_defaults_to_legacy_scoring() -> None:
    """Existing V0.6 JSON without a score-contract field remains loadable as legacy."""

    payload = {
        "silhouette_iou": 0.5,
        "silhouette_union_fraction": 0.5,
        "global_bbox": {
            "reference_bbox_norm": [0.1, 0.1, 0.9, 0.9],
            "rendered_bbox_norm": [0.1, 0.1, 0.9, 0.9],
            "center_error_norm": 0,
            "size_error_norm": 0,
        },
        "semantic_deviations": [],
        "overall_direct_score": 0.625,
    }

    metrics = DirectVisualMetrics.model_validate(payload)

    assert metrics.scoring_version == "legacy_bbox_v1"


class _FailingProvider:
    """Provide a deterministic failure to verify optional-provider degradation."""

    name = "failing"

    def generate(self, request: VisualQARequest, prompt: str, output_path: Path):
        """Raise a provider error without writing an artifact."""

        raise RuntimeError("provider unavailable")


def test_optional_target_provider_failure_is_non_fatal(tmp_path: Path) -> None:
    """Image-model failures become advisory target manifests instead of pipeline exceptions."""

    mask = tmp_path / "reference_mask.png"
    _rectangle_image(mask)
    manifest = generate_optional_qa_target(
        _request(mask, include_target=True),
        provider=_FailingProvider(),
        prompt="same camera",
        output_path=tmp_path / "target.png",
    )
    assert isinstance(manifest, QATargetManifest)
    assert manifest.status == "failed"
    assert manifest.advisory_only is True
    assert "provider unavailable" in str(manifest.error)
    report = compare_reference_to_render(
        _request(mask, include_target=True),
        silhouette_path=mask,
    )
    combined = merge_advisory_target_result(report, manifest)
    assert combined.generated_target_status == "failed"
    assert combined.direct_metrics == report.direct_metrics


def test_render_pass_schema_accepts_blender_manifest_shape() -> None:
    """The host manifest contract accepts the agreed Blender-side pass structure."""

    manifest = RenderPassManifest(
        job_id="qa_test",
        scene_spec_sha256=SHA,
        camera_fingerprint=SHA,
        build_fingerprint=SHA,
        blender_version="5.0.1",
        render_engine="BLENDER_EEVEE",
        render_device="DEFAULT",
        resolution=(64, 64),
        passes=_pass_records("pass.png", width=64, height=64),
        object_id_colors={"asset.body": "#ff0000"},
    )
    payload = json.loads(manifest.model_dump_json())
    assert [record["kind"] for record in payload["passes"]] == list(
        REQUIRED_QA_PASS_KINDS
    )


def test_render_pass_schema_rejects_incomplete_pass_set() -> None:
    """The public QA manifest rejects any subset of the required seven outputs."""

    with pytest.raises(ValueError):
        RenderPassManifest(
            job_id="qa_test",
            scene_spec_sha256=SHA,
            camera_fingerprint=SHA,
            build_fingerprint=SHA,
            blender_version="5.0.1",
            render_engine="BLENDER_EEVEE",
            render_device="DEFAULT",
            resolution=(64, 64),
            passes=_pass_records("pass.png", width=64, height=64)[:-1],
        )


def test_visual_qa_request_rejects_stale_reference_artifacts(tmp_path: Path) -> None:
    """Hash validation prevents comparison after immutable evidence or passes change."""

    root = Path(__file__).resolve().parents[1]
    scene_path = tmp_path / "analysis" / "scene_spec.json"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text(
        (root / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    mask = tmp_path / "silhouette.png"
    _rectangle_image(mask)
    manifest_path = tmp_path / "qa_pass_manifest.json"
    manifest = RenderPassManifest(
        job_id="geometry_showcase",
        run_id="run-001",
        scene_spec_sha256=sha256_file(scene_path),
        camera_fingerprint=camera_fingerprint(scene_path),
        build_fingerprint=str(
            collect_build_provenance(
                tmp_path,
                "geometry_showcase",
                scene_spec_path=scene_path,
            )["fingerprint"]
        ),
        blender_version="5.0.1",
        render_engine="BLENDER_EEVEE",
        render_device="DEFAULT",
        resolution=(100, 80),
        passes=_pass_records(
            mask.name,
            width=100,
            height=80,
            sha256=sha256_file(mask),
        ),
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    request = create_visual_qa_request(
        job_id="geometry_showcase",
        run_id="run-001",
        mode="concept",
        reference_path=mask,
        reference_mask_path=mask,
        preview_path=mask,
        render_pass_manifest_path=manifest_path,
        scene_spec_path=scene_path,
    )
    validate_visual_qa_request(request, scene_spec_path=scene_path)
    Image.new("L", (100, 80), 255).save(mask)
    with pytest.raises(ValueError, match="hash changed"):
        validate_visual_qa_request(request, scene_spec_path=scene_path)
