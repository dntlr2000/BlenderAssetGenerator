from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa import camera_probe_service as service
from codex_blender_modeler.qa.semantic_localizer import extract_semantic_mask
from codex_blender_modeler.workspace import sha256_file

JOB_ID = "camera_probe_test"
QA_RUN_ID = "qa-run-001"
DIAGNOSTIC_ID = "camera-diag-001"
CAMERA_SHA256 = "c" * 64
BUILD_SHA256 = "b" * 64


def _scene_spec() -> SceneSpec:
    """Create one compact observed subject for deterministic bbox scoring."""

    return SceneSpec.model_validate(
        {
            "job_id": JOB_ID,
            "mode": "concept",
            "nominal_scene_size": [4.0, 2.0, 2.0],
            "sources": [
                {
                    "id": "reference",
                    "path": "input/reference.png",
                    "kind": "reference",
                }
            ],
            "materials": [
                {
                    "id": "mat.test",
                    "name": "Test",
                    "base_color": [0.5, 0.5, 0.5, 1.0],
                    "roughness": 0.5,
                    "metallic": 0.0,
                }
            ],
            "objects": [
                {
                    "id": "asset.body",
                    "name": "Body",
                    "geometry": {
                        "kind": "primitive",
                        "primitive": "cube",
                        "dimensions": [3.0, 1.0, 1.0],
                    },
                    "material_id": "mat.test",
                    "tags": ["qa_role:primary"],
                    "evidence": [
                        {
                            "source_id": "reference",
                            "bbox_norm": [0.25, 0.25, 0.75, 0.75],
                            "status": "observed",
                            "confidence": 0.9,
                        }
                    ],
                },
                {
                    "id": "asset.trigger",
                    "name": "Trigger",
                    "geometry": {
                        "kind": "primitive",
                        "primitive": "cube",
                        "dimensions": [0.2, 0.1, 0.3],
                    },
                    "material_id": "mat.test",
                    "tags": ["qa_role:supporting"],
                    "evidence": [
                        {
                            "source_id": "reference",
                            "bbox_norm": [0.4, 0.4, 0.6, 0.6],
                            "status": "observed",
                            "confidence": 0.8,
                        }
                    ],
                },
            ],
            "camera": {
                "projection": "PERSP",
                "location": [5.0, -8.0, 4.0],
                "target": [0.0, 0.0, 0.0],
                "focal_length_mm": 50.0,
                "ortho_scale": 6.0,
                "resolution": [100, 100],
            },
        }
    )


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Seed one isolated job root, canonical SceneSpec, and inert source blend."""

    root = tmp_path / "job"
    scene_spec_path = root / "analysis" / "scene_spec.json"
    scene_spec_path.parent.mkdir(parents=True)
    scene_spec_path.write_text(_scene_spec().model_dump_json(indent=2), encoding="utf-8")
    blend_path = root / "blender" / "scene.blend"
    blend_path.parent.mkdir(parents=True)
    blend_path.write_bytes(b"immutable authoring blend")
    artifact_root = (
        root / "qa" / "runs" / QA_RUN_ID / "diagnostics" / DIAGNOSTIC_ID
    )
    return root, scene_spec_path, artifact_root


def _argument_map(arguments: list[str]) -> dict[str, str]:
    """Convert the renderer's paired CLI arguments into a test lookup."""

    return {
        arguments[index]: arguments[index + 1]
        for index in range(0, len(arguments), 2)
    }


def _fake_renderer(
    *,
    mutation: str | None = None,
) -> Callable[..., None]:
    """Create exact fake Blender evidence with optional adversarial mutation."""

    def render(
        script_name: str,
        arguments: list[str],
        blend_file: Path | None = None,
        **_kwargs: object,
    ) -> None:
        """Materialize the requested probe passes and one hash-bound manifest."""

        assert script_name == "render_camera_diagnostic_probes.py"
        assert blend_file is not None
        values = _argument_map(arguments)
        root = Path(values["--job-root"])
        plan_path = Path(values["--probe-plan"])
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        output_dir = Path(values["--output-dir"])
        manifest_path = Path(values["--manifest"])
        source_blend_sha256 = sha256_file(blend_file)
        width, height = [int(value) for value in plan["render_resolution"]]
        colors = {"asset.body": "#ff0000", "asset.trigger": "#00ff00"}
        records: list[dict[str, object]] = []
        for raw_probe in plan["probes"]:
            probe_id = raw_probe["probe_id"]
            probe_dir = output_dir / probe_id
            probe_dir.mkdir(parents=True, exist_ok=True)
            object_id_path = probe_dir / "object_id.png"
            silhouette_path = probe_dir / "silhouette.png"
            object_id = Image.new("RGB", (width, height), (0, 0, 0))
            draw = ImageDraw.Draw(object_id)
            draw.rectangle(
                (width // 4, height // 4, width * 3 // 4 - 1, height * 3 // 4 - 1),
                fill=(255, 0, 0),
            )
            draw.rectangle(
                (width * 2 // 5, height * 2 // 5, width * 3 // 5 - 1, height * 3 // 5 - 1),
                fill=(0, 255, 0),
            )
            object_id.save(object_id_path)
            Image.new("RGB", (width, height), (255, 255, 255)).save(silhouette_path)
            object_record_path = object_id_path
            if mutation == "escaped_pass" and probe_id == "baseline":
                object_record_path = Path(values["--scene-spec"])
            records.append(
                {
                    "probe_id": probe_id,
                    "camera_delta": raw_probe["camera_delta"],
                    "camera": {
                        "projection": "PERSP",
                        "location": [5.0, -8.0, 4.0],
                        "rotation_deg": [60.0, 0.0, 30.0],
                        "target": [0.0, 0.0, 0.0],
                        "lens_mm": 50.0,
                        "ortho_scale": 6.0,
                        "clip_start": 0.1,
                        "clip_end": 1000.0,
                    },
                    "passes": [
                        {
                            "kind": "silhouette",
                            "path": silhouette_path.relative_to(root).as_posix(),
                            "sha256": sha256_file(silhouette_path),
                            "width": width,
                            "height": height,
                            "encoding": "png-rgb8",
                        },
                        {
                            "kind": "object_id",
                            "path": object_record_path.relative_to(root).as_posix(),
                            "sha256": sha256_file(object_record_path),
                            "width": width,
                            "height": height,
                            "encoding": "png-rgb8",
                        },
                    ],
                }
            )
        if mutation == "reordered_probes":
            records.reverse()
        manifest = {
            "schema_version": "0.6.0",
            "diagnostic_kind": "bounded_camera_probe",
            "canonical_v06_qa_run": False,
            "job_id": JOB_ID,
            "qa_run_id": QA_RUN_ID,
            "diagnostic_id": DIAGNOSTIC_ID,
            "probe_plan_sha256": values["--probe-plan-sha256"],
            "role_map_sha256": values["--role-map-sha256"],
            "scene_spec_sha256": values["--scene-spec-sha256"],
            "camera_fingerprint": values["--camera-fingerprint"],
            "build_fingerprint": values["--build-fingerprint"],
            "source_blend_sha256": source_blend_sha256,
            "resolution": [width, height],
            "target_ids": sorted(colors),
            "object_id_colors": colors,
            "primary_reference_mask": plan.get("primary_reference_mask"),
            "probes": records,
            "warnings": [],
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        if mutation == "tamper_plan":
            plan_path.write_text(plan_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        if mutation == "tamper_primary_mask":
            binding = plan.get("primary_reference_mask")
            assert isinstance(binding, dict)
            (root / str(binding["path"])).write_bytes(b"tampered mask")
        if mutation == "tamper_semantic_mask":
            bindings = plan.get("semantic_reference_masks")
            assert isinstance(bindings, list) and bindings
            (root / str(bindings[0]["path"])).write_bytes(b"tampered mask")
        if mutation in {"tamper_blend", "tamper_blend_and_raise"}:
            blend_file.write_bytes(b"mutated blend")
        if mutation == "tamper_blend_and_raise":
            raise RuntimeError("synthetic Blender failure")

    return render


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    mutation: str | None = None,
    max_camera_probes: int = 2,
    with_primary_mask: bool = False,
    with_semantic_masks: bool = False,
) -> tuple[list[service.CameraProbeResult], Path, Path, Path]:
    """Execute the service against one isolated mocked Blender renderer."""

    root, scene_spec_path, artifact_root = _workspace(tmp_path)
    scene_spec_sha256 = sha256_file(scene_spec_path)
    monkeypatch.setattr(service, "run_blender", _fake_renderer(mutation=mutation))
    monkeypatch.setattr(
        service,
        "collect_build_provenance",
        lambda *_args, **_kwargs: {
            "fingerprint": BUILD_SHA256,
            "scene_spec_sha256": scene_spec_sha256,
        },
    )
    primary_mask_path: Path | None = None
    primary_mask_sha256: str | None = None
    primary_mask_source: str | None = None
    if with_primary_mask:
        primary_mask_path = root / "qa" / "runs" / QA_RUN_ID / "reference_mask.png"
        primary_mask_path.parent.mkdir(parents=True, exist_ok=True)
        reference_mask = Image.new("L", (100, 100), 0)
        ImageDraw.Draw(reference_mask).rectangle((25, 25, 74, 74), fill=255)
        reference_mask.save(primary_mask_path)
        primary_mask_sha256 = sha256_file(primary_mask_path)
        primary_mask_source = "canonical_primary_object_reference"
    semantic_masks: dict[str, service.SemanticProbeMask] = {}
    if with_semantic_masks:
        semantic_root = root / "analysis" / "masks" / "fixture"
        for semantic_id, bounds, confidence in (
            ("asset.body", (25, 25, 74, 74), 0.9),
            ("asset.trigger", (40, 40, 59, 59), 0.8),
        ):
            path = semantic_root / f"{semantic_id.replace('.', '-')}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("L", (100, 100), 0)
            draw = ImageDraw.Draw(image)
            draw.rectangle(bounds, fill=255)
            if semantic_id == "asset.body":
                draw.rectangle((40, 40, 59, 59), fill=0)
            image.save(path)
            semantic_masks[semantic_id] = (path, sha256_file(path), confidence)
    results, plan_path, manifest_path = service.run_bounded_camera_probes(
        root,
        job_id=JOB_ID,
        qa_run_id=QA_RUN_ID,
        diagnostic_id=DIAGNOSTIC_ID,
        artifact_root=artifact_root,
        scene_spec_path=scene_spec_path,
        camera_fingerprint=CAMERA_SHA256,
        max_camera_probes=max_camera_probes,
        resolution=128,
        primary_reference_mask_path=primary_mask_path,
        primary_reference_mask_sha256=primary_mask_sha256,
        primary_reference_mask_source=primary_mask_source,
        semantic_reference_masks=semantic_masks,
    )
    return results, plan_path, manifest_path, root


def test_bounded_camera_probe_service_scores_exact_run_owned_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exact object-ID boxes produce perfect deterministic probe scores."""

    results, plan_path, manifest_path, root = _run(monkeypatch, tmp_path)

    assert [result.probe_id for result in results] == [
        "baseline",
        "yaw-positive",
        "yaw-negative",
    ]
    assert all(result.overall_score == pytest.approx(1.0) for result in results)
    assert results[0].is_baseline is True
    assert results[0].evidence_sha256 == sha256_file(manifest_path)
    assert plan_path.relative_to(root).as_posix().endswith("camera_probes/plan.json")
    assert manifest_path.relative_to(root).as_posix().endswith(
        "camera_probes/render_manifest.json"
    )
    assert (root / "blender" / "scene.blend").read_bytes() == b"immutable authoring blend"
    assert all(result.primary_silhouette_score is None for result in results)
    assert json.loads(plan_path.read_text(encoding="utf-8"))["primary_reference_mask"] is None


def test_probe_service_scores_and_binds_an_exact_primary_silhouette(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An explicit subject mask adds IoU evidence without replacing bbox scores."""

    results, plan_path, manifest_path, root = _run(
        monkeypatch,
        tmp_path,
        with_primary_mask=True,
    )

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    binding = plan["primary_reference_mask"]
    assert binding["source"] == "canonical_primary_object_reference"
    assert sha256_file(root / binding["path"]) == binding["sha256"]
    assert manifest["primary_reference_mask"] == binding
    assert all(result.overall_score == pytest.approx(1.0) for result in results)
    assert all(result.primary_silhouette_score == pytest.approx(0.25) for result in results)


def test_probe_service_prefers_exact_per_part_shape_over_bbox_only_scoring(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Use contour and orientation-sensitive masks when explicit part evidence exists."""

    results, plan_path, _manifest_path, root = _run(
        monkeypatch,
        tmp_path,
        with_semantic_masks=True,
    )

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert [item["semantic_id"] for item in plan["semantic_reference_masks"]] == [
        "asset.body",
        "asset.trigger",
    ]
    for item in plan["semantic_reference_masks"]:
        assert sha256_file(root / item["path"]) == item["sha256"]
    assert all(result.overall_score == pytest.approx(1.0) for result in results)
    assert all(
        score.score_basis == "semantic_shape"
        for result in results
        for score in result.semantic_scores
    )


def test_probe_service_rejects_primary_mask_changed_during_render(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A stale exact silhouette binding fails closed instead of falling back silently."""

    with pytest.raises(RuntimeError, match="primary reference mask"):
        _run(
            monkeypatch,
            tmp_path,
            mutation="tamper_primary_mask",
            with_primary_mask=True,
        )


def test_probe_service_rejects_semantic_mask_changed_during_render(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A changed per-part contour mask fails closed instead of falling back to bboxes."""

    with pytest.raises(RuntimeError, match="semantic mask asset.body"):
        _run(
            monkeypatch,
            tmp_path,
            mutation="tamper_semantic_mask",
            with_semantic_masks=True,
        )


def test_probe_family_uses_the_declared_bounded_count() -> None:
    """The maximum plan contains one baseline plus twelve unique bounded probes."""

    probes = service._probe_deltas(12)

    assert len(probes) == 13
    assert probes[0][0] == "baseline"
    assert probes[0][1].is_neutral()
    assert len({probe_id for probe_id, _delta in probes}) == 13
    with pytest.raises(ValueError, match="within"):
        service._probe_deltas(13)


def test_bbox_similarity_uses_normalized_center_and_size_error() -> None:
    """Known bbox translation produces the expected bounded similarity score."""

    assert service._bbox_similarity(
        (0.25, 0.25, 0.75, 0.75),
        (0.35, 0.25, 0.85, 0.75),
    ) == pytest.approx(1.0 - 0.1 / (2**0.5))
    assert service._bbox_similarity((0.25, 0.25, 0.75, 0.75), None) == 0.0


@pytest.mark.parametrize("mutation", ["reordered_probes", "escaped_pass", "tamper_plan"])
def test_probe_service_rejects_wrong_identity_path_or_tampered_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    """Same-count substitution, escaped passes, and input mutation all fail closed."""

    with pytest.raises((ValueError, RuntimeError)):
        _run(monkeypatch, tmp_path, mutation=mutation)


@pytest.mark.parametrize("raises", [False, True])
def test_probe_service_detects_source_blend_mutation_even_when_runner_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raises: bool,
) -> None:
    """Authoring-blend immutability is checked on successful and failed Blender calls."""

    mutation = "tamper_blend_and_raise" if raises else "tamper_blend"
    with pytest.raises(RuntimeError, match="authoring blend"):
        _run(monkeypatch, tmp_path, mutation=mutation)


def test_probe_service_rejects_artifact_root_outside_exact_run_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Diagnostic outputs cannot be redirected outside their exact run-owned root."""

    root, scene_spec_path, _artifact_root = _workspace(tmp_path)
    called = False

    def unexpected_runner(*_args: object, **_kwargs: object) -> None:
        """Record an unexpected renderer invocation without writing any files."""

        nonlocal called
        called = True

    monkeypatch.setattr(service, "run_blender", unexpected_runner)
    with pytest.raises(ValueError, match="outside the job|exact QA run/diagnostic path"):
        service.run_bounded_camera_probes(
            root,
            job_id=JOB_ID,
            qa_run_id=QA_RUN_ID,
            diagnostic_id=DIAGNOSTIC_ID,
            artifact_root=tmp_path / "outside",
            scene_spec_path=scene_spec_path,
            camera_fingerprint=CAMERA_SHA256,
        )
    assert called is False


@pytest.mark.parametrize(
    "mutation",
    ["scene", "camera", "build", "blend", "delta", "pass_path", "targets"],
)
def test_terminal_probe_validator_rejects_coordinated_contract_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    """Reject parseable terminal tampering even when callers provide refreshed outer hashes."""

    results, plan_path, manifest_path, root = _run(monkeypatch, tmp_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "scene":
        manifest["scene_spec_sha256"] = "1" * 64
    elif mutation == "camera":
        manifest["probes"][0]["camera"]["type"] = "PANO"
    elif mutation == "build":
        manifest["build_fingerprint"] = "2" * 64
    elif mutation == "blend":
        manifest["source_blend_sha256"] = "3" * 64
    elif mutation == "delta":
        plan["probes"][1]["camera_delta"]["rotation_delta_deg"] = [6.0, 0.0, 0.0]
        manifest["probes"][1]["camera_delta"]["rotation_delta_deg"] = [6.0, 0.0, 0.0]
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        manifest["probe_plan_sha256"] = sha256_file(plan_path)
    elif mutation == "pass_path":
        passes = manifest["probes"][0]["passes"]
        passes[1]["path"] = passes[0]["path"]
        passes[1]["sha256"] = passes[0]["sha256"]
    else:
        plan["target_ids"] = ["asset.body"]
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        manifest["probe_plan_sha256"] = sha256_file(plan_path)
        manifest["target_ids"] = ["asset.body"]
        manifest["object_id_colors"] = {"asset.body": "#ff0000"}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises((ValueError, RuntimeError)):
        service.validate_camera_probe_terminal_evidence(
            root,
            plan_path=plan_path,
            plan_sha256=sha256_file(plan_path),
            manifest_path=manifest_path,
            manifest_sha256=sha256_file(manifest_path),
            role_map_path=plan_path.parent.parent / "role_map.json",
            role_map_sha256=sha256_file(plan_path.parent.parent / "role_map.json"),
            expected_job_id=JOB_ID,
            expected_qa_run_id=QA_RUN_ID,
            expected_diagnostic_id=DIAGNOSTIC_ID,
            report_probes=results,
        )


def test_terminal_probe_validator_rejects_report_semantic_membership_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Require every strict report probe to preserve primary/supporting score membership."""

    results, plan_path, manifest_path, root = _run(monkeypatch, tmp_path)
    tampered = [
        results[0].model_copy(update={"semantic_scores": results[0].semantic_scores[:1]}),
        *results[1:],
    ]
    with pytest.raises(ValueError, match="semantic membership"):
        service.validate_camera_probe_terminal_evidence(
            root,
            plan_path=plan_path,
            plan_sha256=sha256_file(plan_path),
            manifest_path=manifest_path,
            manifest_sha256=sha256_file(manifest_path),
            role_map_path=plan_path.parent.parent / "role_map.json",
            role_map_sha256=sha256_file(plan_path.parent.parent / "role_map.json"),
            expected_job_id=JOB_ID,
            expected_qa_run_id=QA_RUN_ID,
            expected_diagnostic_id=DIAGNOSTIC_ID,
            report_probes=tampered,
        )


def test_exclusive_terminal_json_refuses_overwrite(tmp_path: Path) -> None:
    """Create terminal JSON once and reject a second writer without changing bytes."""

    path = tmp_path / "terminal.json"
    service.write_json_exclusive(path, {"value": 1})
    original = path.read_bytes()
    with pytest.raises(FileExistsError, match="already exists"):
        service.write_json_exclusive(path, {"value": 2})
    assert path.read_bytes() == original


def test_semantic_mask_is_exact_deterministic_and_never_overwrites_source(
    tmp_path: Path,
) -> None:
    """Exact-color extraction is stable while the immutable object-ID pass stays unchanged."""

    source = tmp_path / "object_id.png"
    image = Image.new("RGB", (4, 2), (0, 0, 0))
    image.putpixel((1, 0), (255, 0, 0))
    image.putpixel((2, 1), (255, 0, 0))
    image.save(source)
    source_sha256 = sha256_file(source)
    first = extract_semantic_mask(source, "#ff0000", tmp_path / "first.png")
    second = extract_semantic_mask(source, "ff0000", tmp_path / "second.png")

    with Image.open(first) as mask:
        assert list(mask.getdata()) == [0, 255, 0, 0, 0, 0, 255, 0]
    assert sha256_file(first) == sha256_file(second)
    assert sha256_file(source) == source_sha256
    with pytest.raises(ValueError, match="must not overwrite"):
        extract_semantic_mask(source, "#ff0000", source)
    assert sha256_file(source) == source_sha256
