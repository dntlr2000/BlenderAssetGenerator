from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.qa.models import (
    REQUIRED_QA_PASS_KINDS,
    QAFinding,
    RenderPassManifest,
    RenderPassRecord,
)
from codex_blender_modeler.qa.service import run_job_visual_qa
from codex_blender_modeler.qa.target_provider import GeneratedTarget
from codex_blender_modeler.workspace import sha256_file


def _rectangle(path: Path, color: int | tuple[int, int, int]) -> None:
    """Write a normalized rectangle matching the fixture's observed evidence box."""

    mode = "RGB" if isinstance(color, tuple) else "L"
    background = (0, 0, 0) if mode == "RGB" else 0
    image = Image.new(mode, (100, 100), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 59, 69), fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _job_fixture(tmp_path: Path, monkeypatch) -> tuple[Path, str]:
    """Create one V0.4-compatible job with immutable input, mask, SceneSpec, and evidence."""

    workspace = tmp_path / "workspaces"
    root = workspace / "asset_qa"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = root / "input" / "reference.png"
    mask = root / "analysis" / "masks" / "reference_content.png"
    _rectangle(reference, (255, 255, 255))
    _rectangle(mask, 255)
    repository = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (repository / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    raw["job_id"] = "asset_qa"
    target_id = raw["objects"][0]["id"]
    raw["objects"][0]["evidence"] = [
        {
            "source_id": "ref.main",
            "bbox_norm": [0.2, 0.2, 0.6, 0.7],
            "status": "observed",
            "confidence": 0.95,
        }
    ]
    scene_spec = root / "analysis" / "scene_spec.json"
    scene_spec.parent.mkdir(parents=True, exist_ok=True)
    scene_spec.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    metadata = {
        "job_id": "asset_qa",
        "mode": "concept",
        "reference_path": str(reference),
        "reference_sha256": sha256_file(reference),
        "sources": [
            {
                "kind": "reference",
                "path": str(reference),
                "sha256": sha256_file(reference),
            }
        ],
        "scale_anchors": [],
    }
    (root / "job.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return root, target_id


def _mock_render(root: Path, target_id: str):
    """Create a mock Blender renderer that emits the complete seven-pass QA contract."""

    def render(
        job_id: str,
        *,
        render_engine: str,
        render_device: str,
        run_id: str,
        camera_fingerprint: str,
        scene_spec_sha256: str,
    ) -> RenderPassManifest:
        """Write deterministic pass files and return their validated manifest."""

        assert job_id == "asset_qa"
        output = root / "renders" / "passes"
        records: list[RenderPassRecord] = []
        for kind in REQUIRED_QA_PASS_KINDS:
            path = output / f"{kind}.png"
            color: int | tuple[int, int, int] = (
                (255, 0, 0) if kind == "object_id" else (255, 255, 255)
            )
            if kind == "silhouette":
                color = 255
            _rectangle(path, color)
            records.append(
                RenderPassRecord(
                    kind=kind,
                    path=str(path),
                    sha256=sha256_file(path),
                    width=100,
                    height=100,
                    encoding="png-rgb8",
                )
            )
        return RenderPassManifest(
            job_id=job_id,
            run_id=run_id,
            scene_spec_sha256=scene_spec_sha256,
            camera_fingerprint=camera_fingerprint,
            build_fingerprint=str(
                collect_build_provenance(root, job_id)["fingerprint"]
            ),
            blender_version="5.0.1",
            render_engine=render_engine,
            render_device=render_device,
            resolution=(100, 100),
            passes=records,
            object_id_colors={target_id: "#ff0000"},
        )

    return render


def test_visual_qa_service_persists_isolated_direct_run(tmp_path: Path, monkeypatch) -> None:
    """One mocked Blender cycle snapshots passes, validates hashes, and updates latest metadata."""

    from codex_blender_modeler.qa import service

    root, target_id = _job_fixture(tmp_path, monkeypatch)
    reference_hash = sha256_file(root / "input" / "reference.png")
    monkeypatch.setattr(service, "_render_job_qa_passes", _mock_render(root, target_id))
    result = run_job_visual_qa("asset_qa", run_id="run-direct")
    run_dir = root / "qa" / "runs" / "run-direct"
    assert result["direct_score"] == 1.0
    assert result["finding_count"] == result["direct_finding_count"] == 0
    assert result["generated_target_advisory_count"] == 0
    assert result["group_suggestion_count"] == 0
    assert result["candidate_count"] == 0
    assert (run_dir / "request.json").is_file()
    assert (run_dir / "reference_mask.png").is_file()
    assert (run_dir / "reference_mask_manifest.json").is_file()
    assert (run_dir / "passes" / "object_id.png").is_file()
    assert (run_dir / "visual_qa_report.json").is_file()
    assert (run_dir / "revision_candidates.json").is_file()
    latest = json.loads((root / "qa" / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "run-direct"
    assert latest["reference_mask"] == "qa/runs/run-direct/reference_mask.png"
    request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    assert Path(request["reference_mask_path"]) == run_dir / "reference_mask.png"
    assert request["reference_mask_sha256"] == sha256_file(run_dir / "reference_mask.png")
    assert latest["visual_qa_report"].startswith("qa/runs/run-direct/")
    assert sha256_file(root / "input" / "reference.png") == reference_hash
    with pytest.raises(FileExistsError):
        run_job_visual_qa("asset_qa", run_id="run-direct")


def test_visual_qa_service_excludes_auxiliary_view_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A higher-confidence front-view bbox cannot contaminate primary-reference scoring."""

    from codex_blender_modeler.qa import service

    root, target_id = _job_fixture(tmp_path, monkeypatch)
    scene_path = root / "analysis" / "scene_spec.json"
    raw = json.loads(scene_path.read_text(encoding="utf-8"))
    raw["sources"].append(
        {
            "id": "view.front",
            "path": "input/front.png",
            "kind": "front",
            "immutable": True,
            "scale_anchors": [],
        }
    )
    raw["objects"][0]["evidence"].append(
        {
            "source_id": "view.front",
            "bbox_norm": [0.65, 0.1, 0.95, 0.4],
            "status": "observed",
            "confidence": 0.99,
        }
    )
    scene_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    monkeypatch.setattr(service, "_render_job_qa_passes", _mock_render(root, target_id))

    result = run_job_visual_qa("asset_qa", run_id="run-primary-reference-only")
    report = json.loads(Path(result["visual_qa_report"]).read_text(encoding="utf-8"))
    deviation = report["direct_metrics"]["semantic_deviations"][0]

    assert result["direct_score"] == 1.0
    assert report["direct_metrics"]["scoring_version"] == "semantic_bbox_v2"
    assert deviation["metric"]["reference_bbox_norm"] == [0.2, 0.2, 0.6, 0.7]


class _CountingProvider:
    """Record explicit advisory-target calls while producing one deterministic target."""

    name = "counting"

    def __init__(self) -> None:
        """Initialize the provider call counter."""

        self.calls = 0

    def generate(self, request, prompt: str, output_path: Path) -> GeneratedTarget:
        """Generate a small target only when the service explicitly invokes the provider."""

        self.calls += 1
        Image.new("RGB", (100, 100), (128, 128, 128)).save(output_path)
        return GeneratedTarget(path=output_path, model="mock-image-model", seed=7)


def test_visual_qa_service_calls_target_provider_only_when_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Supplying a provider alone does not make generated imagery authoritative or automatic."""

    from codex_blender_modeler.qa import service

    root, target_id = _job_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(service, "_render_job_qa_passes", _mock_render(root, target_id))
    provider = _CountingProvider()
    disabled = run_job_visual_qa(
        "asset_qa",
        run_id="run-disabled",
        provider=provider,
    )
    assert disabled["generated_target_status"] == "not_requested"
    assert provider.calls == 0
    enabled = run_job_visual_qa(
        "asset_qa",
        run_id="run-enabled",
        include_generated_target=True,
        provider=provider,
    )
    assert enabled["generated_target_status"] == "generated"
    assert provider.calls == 1
    assert enabled["direct_score"] == 1.0
    assert enabled["finding_count"] == enabled["direct_finding_count"] == 0
    assert enabled["group_suggestion_count"] == 0
    assert enabled["candidate_count"] == 0
    target_manifest = json.loads(Path(enabled["qa_target_manifest"]).read_text(encoding="utf-8"))
    assert target_manifest["advisory_only"] is True
    prompt_path = Path(target_manifest["prompt_path"])
    assert prompt_path.is_file()
    assert enabled["qa_target_prompt"] == str(prompt_path)
    assert "advisory visual-QA target" in prompt_path.read_text(encoding="utf-8")
    report = json.loads(Path(enabled["visual_qa_report"]).read_text(encoding="utf-8"))
    advisory = [
        finding
        for finding in report["findings"]
        if finding["evidence_sources"] == ["generated_target"]
    ]
    assert advisory
    assert enabled["generated_target_advisory_count"] == len(advisory)
    assert all(finding["confidence"] <= 0.35 for finding in advisory)
    assert all(
        finding["metrics"]["configured_advisory_weight"] == 0.15
        for finding in advisory
    )
    assert all(finding["suggestion"] is None for finding in advisory)


def test_visual_qa_service_reports_group_bundles_separately(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Count one coherent group bundle separately from its atomic member candidates."""

    from codex_blender_modeler.qa import service

    root, target_id = _job_fixture(tmp_path, monkeypatch)
    raw = json.loads((root / "analysis" / "scene_spec.json").read_text(encoding="utf-8"))
    second_target_id = raw["objects"][1]["id"]

    def enrich_group(report, _spec):
        """Inject one deterministic group finding after the direct comparison fixture."""

        group = QAFinding(
            id="direct.group_position.demo.fixture",
            target_ids=[target_id, second_target_id],
            issue_type="position",
            severity="low",
            description="Move the fixture group coherently.",
            evidence_sources=["direct_reference"],
            confidence=0.8,
            metrics={
                "world_displacement_x": 0.1,
                "world_displacement_y": 0.0,
                "world_displacement_z": 0.0,
            },
        )
        return report.model_copy(update={"findings": [*report.findings, group]})

    monkeypatch.setattr(service, "_render_job_qa_passes", _mock_render(root, target_id))
    monkeypatch.setattr(service, "enrich_direct_qa_suggestions", enrich_group)

    result = run_job_visual_qa("asset_qa", run_id="run-group-count")

    assert result["finding_count"] == result["direct_finding_count"] == 0
    assert result["generated_target_advisory_count"] == 0
    assert result["group_suggestion_count"] == 1
    assert result["candidate_count"] == 2
