from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError
from typer.testing import CliRunner

from codex_blender_modeler import cli as cli_module
from codex_blender_modeler import mcp_server as mcp_module
from codex_blender_modeler.analysis.models import ModelingPlan
from codex_blender_modeler.blender_artifacts import write_json_atomic
from codex_blender_modeler.cli import app
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa import multiview_sanity as sanity
from codex_blender_modeler.qa.multiview_sanity import (
    ASSEMBLY_SANITY_PASS_KINDS,
    ASSEMBLY_SANITY_VIEW_IDS,
    AssemblySanityPassRecord,
    AssemblySanityPlan,
    AssemblySanityRenderManifest,
    AssemblySanityReport,
    AssemblySanityViewRender,
    plan_job_assembly_multiview_sanity,
    run_job_assembly_multiview_sanity,
)
from codex_blender_modeler.workspace import create_job, sha256_file

JOB_ID = "weapon_sanity_test"


def _scene() -> SceneSpec:
    """Create a compact manufactured asset with one central attached trigger."""

    return SceneSpec.model_validate(
        {
            "job_id": JOB_ID,
            "mode": "concept",
            "nominal_scene_size": [4.0, 1.0, 1.5],
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
                    "base_color": [0.4, 0.4, 0.4, 1.0],
                    "roughness": 0.5,
                    "metallic": 0.0,
                }
            ],
            "objects": [
                {
                    "id": "weapon.root",
                    "name": "Receiver",
                    "geometry": {
                        "kind": "primitive",
                        "primitive": "cube",
                        "dimensions": [3.0, 0.5, 0.8],
                    },
                    "material_id": "mat.test",
                },
                {
                    "id": "weapon.trigger",
                    "name": "Trigger",
                    "geometry": {
                        "kind": "primitive",
                        "primitive": "cube",
                        "dimensions": [0.2, 0.1, 0.35],
                    },
                    "material_id": "mat.test",
                },
            ],
            "camera": {
                "projection": "PERSP",
                "location": [5.0, -8.0, 4.0],
                "target": [0.0, 0.0, 0.0],
                "focal_length_mm": 50.0,
                "ortho_scale": 6.0,
                "resolution": [320, 240],
            },
        }
    )


def _modeling_plan() -> ModelingPlan:
    """Declare a root-frame center-plane relationship for the trigger."""

    return ModelingPlan.model_validate(
        {
            "job_id": JOB_ID,
            "reference_analysis_path": "analysis/reference_analysis.json",
            "camera_solution_path": "analysis/camera_solution.json",
            "stage": "authored",
            "objects": [
                {
                    "id": "weapon.root",
                    "label": "receiver",
                    "source_ids": ["reference"],
                    "scope_role": "primary",
                    "assembly_role": "root",
                },
                {
                    "id": "weapon.trigger",
                    "label": "trigger",
                    "source_ids": ["reference"],
                    "scope_role": "supporting",
                    "assembly_role": "attached",
                },
            ],
            "assembly_consistency_policy": "spatial_v1",
            "assembly_frame": {
                "root_object_id": "weapon.root",
                "longitudinal_axis": "X",
                "lateral_axis": "Y",
                "vertical_axis": "Z",
                "symmetry": "bilateral",
                "evidence_status": "inferred",
            },
            "assembly_relationships": [
                {
                    "id": "center.trigger",
                    "kind": "center_plane",
                    "subject_id": "weapon.trigger",
                    "reference_id": "weapon.root",
                    "axis": "Y",
                    "tolerance": {"mode": "relative", "value": 0.05},
                }
            ],
        }
    )


def _seed_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create exact canonical inputs and a stable placeholder authoring blend."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), (120, 130, 140)).save(reference)
    create_job(JOB_ID, reference, "concept", [])
    root = workspace / JOB_ID
    (root / "analysis" / "scene_spec.json").write_text(
        _scene().model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "analysis" / "modeling_plan.json").write_text(
        _modeling_plan().model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "blender" / "scene.blend").write_bytes(b"stable-authoring-blend")
    return root


def _args_map(arguments: list[str]) -> dict[str, str]:
    """Convert the simple flag/value Blender invocation into a test mapping."""

    return {
        arguments[index]: arguments[index + 1]
        for index in range(0, len(arguments), 2)
    }


def _mock_renderer(*, omit_trigger: bool = False):
    """Create a deterministic renderer double with exact run-owned image hashes."""

    def render(script_name: str, arguments: list[str], *, blend_file: Path):
        """Write the same manifest contract produced by the Blender diagnostic script."""

        assert script_name == "render_assembly_sanity.py"
        values = _args_map(arguments)
        root = Path(values["--job-root"])
        plan_path = Path(values["--plan"])
        manifest_path = Path(values["--manifest"])
        output_dir = Path(values["--output-dir"])
        plan = AssemblySanityPlan.model_validate_json(
            plan_path.read_text(encoding="utf-8")
        )
        width, height = plan.resolution
        colors = {"weapon.root": "#ff0000", "weapon.trigger": "#00ff00"}
        rendered_views: list[AssemblySanityViewRender] = []
        for view in plan.views:
            records: list[AssemblySanityPassRecord] = []
            for kind in ASSEMBLY_SANITY_PASS_KINDS:
                path = output_dir / view.view_id / f"{kind}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                image = Image.new("RGB", (width, height), (100, 110, 120))
                if kind == "object_id":
                    image = Image.new("RGB", (width, height), (255, 0, 0))
                    if not omit_trigger:
                        for x in range(width // 2, width):
                            for y in range(height):
                                image.putpixel((x, y), (0, 255, 0))
                image.save(path)
                records.append(
                    AssemblySanityPassRecord(
                        kind=kind,
                        path=path.relative_to(root).as_posix(),
                        sha256=sha256_file(path),
                        width=width,
                        height=height,
                    )
                )
            rendered_views.append(
                AssemblySanityViewRender(
                    view_id=view.view_id,
                    camera={
                        "name": "CBM_AssemblySanity_Camera",
                        "type": "PERSP",
                        "view_id": view.view_id,
                        "camera_direction_frame": [
                            round(float(value), 9)
                            for value in view.camera_direction_frame
                        ],
                        "screen_up_role": view.screen_up_role,
                        "location": [1.0, 1.0, 1.0],
                        "rotation_deg": [54.7356, 0.0, 45.0],
                        "target": [0.0, 0.0, 0.0],
                        "lens_mm": 50.0,
                        "clip_start": 0.01,
                        "clip_end": 100.0,
                    },
                    target_ids=plan.target_ids,
                    passes=records,
                )
            )
        manifest = AssemblySanityRenderManifest(
            job_id=plan.job_id,
            run_id=plan.run_id,
            plan_sha256=sha256_file(plan_path),
            scene_spec_sha256=plan.scene_spec_sha256,
            modeling_plan_sha256=plan.modeling_plan_sha256,
            source_blend_path=plan.source_blend_path,
            source_blend_sha256=sha256_file(blend_file),
            build_fingerprint=plan.build_fingerprint,
            blender_version="5.0.1",
            render_engine=values["--render-engine"],
            render_device=values["--render-device"],
            resolution=plan.resolution,
            object_id_colors=colors,
            assembly_frame_bounds={"min": [-1.5, -0.25, -0.4], "max": [1.5, 0.25, 0.4]},
            assembly_evaluation={
                "policy": "spatial_v1",
                "status": "passed",
                "ok": True,
                "checks": [],
            },
            views=rendered_views,
        )
        write_json_atomic(manifest_path, manifest.model_dump(mode="json"))

    return render


def test_plan_uses_exact_assembly_frame_views_and_relative_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan five root-frame views without creating a canonical V0.6 QA run."""

    root = _seed_job(tmp_path, monkeypatch)
    result = plan_job_assembly_multiview_sanity(
        JOB_ID,
        run_id="weapon-five-view",
        resolution=128,
    )
    plan = AssemblySanityPlan.model_validate_json(
        Path(result["plan"]).read_text(encoding="utf-8")
    )

    assert tuple(view.view_id for view in plan.views) == ASSEMBLY_SANITY_VIEW_IDS
    assert plan.views[0].camera_direction_frame == (1.0, 0.0, 0.0)
    assert plan.views[1].camera_direction_frame == (0.0, 1.0, 0.0)
    assert plan.views[2].camera_direction_frame == (0.0, 0.0, 1.0)
    assert plan.views[3].camera_direction_frame == (-1.0, 0.0, 0.0)
    assert plan.canonical_v06_qa_run is False
    assert plan.reference_comparison_mode == "structural_only"
    assert plan.scene_spec_path == "analysis/scene_spec.json"
    assert plan.source_blend_path == "blender/scene.blend"
    assert plan.reference_sources[0].path == "input/reference.png"
    assert not (root / "qa" / "runs" / "weapon-five-view").exists()


def test_run_writes_structural_only_report_and_preserves_authoring_blend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render five diagnostic views while keeping canonical QA and blend unchanged."""

    root = _seed_job(tmp_path, monkeypatch)
    planned = plan_job_assembly_multiview_sanity(
        JOB_ID,
        run_id="weapon-run",
        resolution=128,
    )
    blend = root / "blender" / "scene.blend"
    before = sha256_file(blend)
    monkeypatch.setattr(sanity, "run_blender", _mock_renderer())

    result = run_job_assembly_multiview_sanity(
        JOB_ID,
        "weapon-run",
        plan_sha256=str(planned["plan_sha256"]),
    )
    report = AssemblySanityReport.model_validate_json(
        Path(result["report"]).read_text(encoding="utf-8")
    )

    assert result["view_count"] == 5
    assert result["pass_count"] == 20
    assert report.structural_status == "passed"
    assert report.reference_comparison_status == "unscorable"
    assert report.quality_claimed is False
    assert report.canonical_v06_qa_run is False
    assert report.semantic_visibility_fraction == 1.0
    assert sha256_file(blend) == before
    assert not (root / "qa" / "runs" / "weapon-run").exists()


def test_run_fails_structurally_when_attached_part_is_hidden_in_every_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report a trigger absent from every object-ID view as a structural failure."""

    _seed_job(tmp_path, monkeypatch)
    planned = plan_job_assembly_multiview_sanity(
        JOB_ID,
        run_id="weapon-hidden-trigger",
        resolution=128,
    )
    monkeypatch.setattr(sanity, "run_blender", _mock_renderer(omit_trigger=True))

    result = run_job_assembly_multiview_sanity(
        JOB_ID,
        "weapon-hidden-trigger",
        plan_sha256=str(planned["plan_sha256"]),
    )
    report = AssemblySanityReport.model_validate_json(
        Path(result["report"]).read_text(encoding="utf-8")
    )

    assert report.structural_status == "failed"
    assert report.unseen_target_ids == ["weapon.trigger"]
    assert any(item.finding_id == "visibility.all_views" for item in report.findings)


def test_run_rejects_changed_canonical_source_before_blender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed when SceneSpec changes after the immutable diagnostic plan."""

    root = _seed_job(tmp_path, monkeypatch)
    planned = plan_job_assembly_multiview_sanity(
        JOB_ID,
        run_id="weapon-stale",
        resolution=128,
    )
    scene_path = root / "analysis" / "scene_spec.json"
    payload = json.loads(scene_path.read_text(encoding="utf-8"))
    payload["nominal_scene_size"][0] = 4.5
    scene_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    called = False

    def unexpected_renderer(*_args, **_kwargs):
        """Record any unsafe Blender invocation after canonical source drift."""

        nonlocal called
        called = True

    monkeypatch.setattr(sanity, "run_blender", unexpected_renderer)
    with pytest.raises(RuntimeError, match="SceneSpec is stale or changed"):
        run_job_assembly_multiview_sanity(
            JOB_ID,
            "weapon-stale",
            plan_sha256=str(planned["plan_sha256"]),
        )
    assert called is False


def test_run_rejects_wrong_or_mutated_exact_plan_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bind execution to the caller-reviewed plan and recheck it after Blender."""

    _seed_job(tmp_path, monkeypatch)
    planned = plan_job_assembly_multiview_sanity(
        JOB_ID,
        run_id="weapon-plan-binding",
        resolution=128,
    )
    called = False

    def unexpected_renderer(*_args, **_kwargs):
        """Record any render attempted with a caller hash that already mismatches."""

        nonlocal called
        called = True

    monkeypatch.setattr(sanity, "run_blender", unexpected_renderer)
    with pytest.raises(RuntimeError, match="caller-supplied reviewed"):
        run_job_assembly_multiview_sanity(
            JOB_ID,
            "weapon-plan-binding",
            plan_sha256="f" * 64,
        )
    assert called is False

    renderer = _mock_renderer()

    def mutate_plan_after_render(
        script_name: str,
        arguments: list[str],
        *,
        blend_file: Path,
    ) -> None:
        """Simulate plan tampering while Blender produces otherwise valid evidence."""

        renderer(script_name, arguments, blend_file=blend_file)
        plan_path = Path(_args_map(arguments)["--plan"])
        plan_path.write_text(
            plan_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(sanity, "run_blender", mutate_plan_after_render)
    with pytest.raises(RuntimeError, match="plan is missing or changed"):
        run_job_assembly_multiview_sanity(
            JOB_ID,
            "weapon-plan-binding",
            plan_sha256=str(planned["plan_sha256"]),
        )


def test_run_rechecks_exact_plan_when_blender_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prefer a source-drift failure when Blender and its exact plan fail together."""

    _seed_job(tmp_path, monkeypatch)
    planned = plan_job_assembly_multiview_sanity(
        JOB_ID,
        run_id="weapon-plan-failure-race",
        resolution=128,
    )

    def mutate_then_fail(
        _script_name: str,
        arguments: list[str],
        *,
        blend_file: Path,
    ) -> None:
        """Change the plan during a synthetic Blender exception."""

        assert blend_file.is_file()
        plan_path = Path(_args_map(arguments)["--plan"])
        plan_path.write_text(
            plan_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        raise RuntimeError("synthetic Blender failure")

    monkeypatch.setattr(sanity, "run_blender", mutate_then_fail)
    with pytest.raises(RuntimeError, match="source changed while Blender failed"):
        run_job_assembly_multiview_sanity(
            JOB_ID,
            "weapon-plan-failure-race",
            plan_sha256=str(planned["plan_sha256"]),
        )


def test_terminal_validator_rejects_coordinated_camera_contract_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a rewritten manifest/report pair whose camera no longer matches its plan."""

    root = _seed_job(tmp_path, monkeypatch)
    run_id = "weapon-camera-contract-tamper"
    planned = plan_job_assembly_multiview_sanity(
        JOB_ID,
        run_id=run_id,
        resolution=128,
    )
    monkeypatch.setattr(sanity, "run_blender", _mock_renderer())
    result = run_job_assembly_multiview_sanity(
        JOB_ID,
        run_id,
        plan_sha256=str(planned["plan_sha256"]),
    )
    manifest_path = Path(result["render_manifest"])
    report_path = Path(result["report"])
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_payload["views"][0]["camera"]["camera_direction_frame"] = [0.0, 1.0, 0.0]
    write_json_atomic(manifest_path, manifest_payload)
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    report_payload["render_manifest_sha256"] = sha256_file(manifest_path)
    write_json_atomic(report_path, report_payload)

    with pytest.raises(RuntimeError, match="camera differs from planned view"):
        sanity.validate_assembly_sanity_terminal(
            root,
            plan_path=Path(result["plan"]),
            plan_sha256=str(result["plan_sha256"]),
            manifest_path=manifest_path,
            manifest_sha256=sha256_file(manifest_path),
            report_path=report_path,
            report_sha256=sha256_file(report_path),
            expected_job_id=JOB_ID,
            expected_run_id=run_id,
        )


def test_terminal_validator_rejects_report_membership_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recompute semantic membership instead of trusting a coordinated report rewrite."""

    root = _seed_job(tmp_path, monkeypatch)
    run_id = "weapon-report-membership-tamper"
    planned = plan_job_assembly_multiview_sanity(
        JOB_ID,
        run_id=run_id,
        resolution=128,
    )
    monkeypatch.setattr(sanity, "run_blender", _mock_renderer())
    result = run_job_assembly_multiview_sanity(
        JOB_ID,
        run_id,
        plan_sha256=str(planned["plan_sha256"]),
    )
    report_path = Path(result["report"])
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    report_payload["visible_target_ids"] = ["weapon.root"]
    report_payload["unseen_target_ids"] = ["weapon.trigger"]
    report_payload["semantic_visibility_fraction"] = 0.5
    write_json_atomic(report_path, report_payload)

    with pytest.raises(ValueError, match="report differs from rendered evidence"):
        sanity.validate_assembly_sanity_terminal(
            root,
            plan_path=Path(result["plan"]),
            plan_sha256=str(result["plan_sha256"]),
            manifest_path=Path(result["render_manifest"]),
            manifest_sha256=str(result["render_manifest_sha256"]),
            report_path=report_path,
            report_sha256=sha256_file(report_path),
            expected_job_id=JOB_ID,
            expected_run_id=run_id,
        )


def test_live_assembly_publication_lease_rejects_a_concurrent_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a second assembly publisher before it invokes Blender or writes evidence."""

    root = _seed_job(tmp_path, monkeypatch)
    run_id = "weapon-concurrent-writer"
    planned = plan_job_assembly_multiview_sanity(
        JOB_ID,
        run_id=run_id,
        resolution=128,
    )
    called = False

    def unexpected_renderer(*_args: object, **_kwargs: object) -> None:
        """Record any renderer call made despite the live publication lease."""

        nonlocal called
        called = True

    monkeypatch.setattr(sanity, "run_blender", unexpected_renderer)
    run_dir = root / "qa" / "assembly_sanity" / "runs" / run_id
    with sanity.artifact_publication_lease(
        run_dir,
        owner_kind="test_writer",
        owner_id="first",
    ):
        with pytest.raises(RuntimeError, match="Another live writer"):
            run_job_assembly_multiview_sanity(
                JOB_ID,
                run_id,
                plan_sha256=str(planned["plan_sha256"]),
            )
    assert called is False
    assert not (run_dir / "render_manifest.json").exists()
    assert not (run_dir / "report.json").exists()
    assert not (run_dir / "views").exists()


def test_plan_paths_and_view_set_fail_closed() -> None:
    """Reject escaping source paths and incomplete multi-view plans."""

    payload = {
        "job_id": JOB_ID,
        "run_id": "invalid-plan",
        "scene_spec_path": "C:/outside/scene_spec.json",
        "scene_spec_sha256": "0" * 64,
        "modeling_plan_path": "analysis/modeling_plan.json",
        "modeling_plan_sha256": "1" * 64,
        "source_blend_path": "blender/scene.blend",
        "source_blend_sha256": "2" * 64,
        "build_fingerprint": "3" * 64,
        "source_fingerprint": "4" * 64,
        "assembly_frame": {
            "root_object_id": "weapon.root",
            "longitudinal_axis": "X",
            "lateral_axis": "Y",
            "vertical_axis": "Z",
        },
        "target_ids": ["weapon.root", "weapon.trigger"],
        "resolution": [128, 128],
        "views": [],
        "created_at": "2026-08-03T00:00:00+00:00",
    }
    with pytest.raises(ValidationError, match="job-relative"):
        AssemblySanityPlan.model_validate(payload)


def test_cli_and_mcp_public_surface_forward_only_bounded_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose plan/run operations without adding an approval or revision shortcut."""

    calls: list[tuple[str, str, dict[str, object]]] = []

    def fake_plan(job_id: str, **kwargs: object) -> dict[str, object]:
        """Capture one public planning request without accessing a workspace."""

        calls.append(("plan", job_id, kwargs))
        return {
            "job_id": job_id,
            "run_id": str(kwargs.get("run_id")),
            "status": "planned",
            "canonical_v06_qa_run": False,
        }

    def fake_run(job_id: str, run_id: str, **kwargs: object) -> dict[str, object]:
        """Capture one public diagnostic run without invoking Blender."""

        calls.append(("run", job_id, {"run_id": run_id, **kwargs}))
        return {
            "job_id": job_id,
            "run_id": run_id,
            "status": "warning",
            "canonical_v06_qa_run": False,
        }

    def fake_diagnose(
        job_id: str,
        qa_run_id: str,
        **kwargs: object,
    ) -> dict[str, object]:
        """Capture one bounded combined diagnostic request without touching a job."""

        calls.append(("diagnose", job_id, {"qa_run_id": qa_run_id, **kwargs}))
        return {
            "ok": True,
            "job_id": job_id,
            "qa_run_id": qa_run_id,
            "canonical_v06_score_unchanged": True,
        }

    monkeypatch.setattr(cli_module, "plan_job_assembly_multiview_sanity", fake_plan)
    monkeypatch.setattr(cli_module, "run_job_assembly_multiview_sanity", fake_run)
    monkeypatch.setattr(cli_module, "run_job_visual_diagnostics", fake_diagnose)
    runner = CliRunner()
    planned = runner.invoke(
        app,
        [
            "qa-assembly-sanity-plan",
            "asset-test",
            "--run-id",
            "assembly-public",
            "--resolution",
            "256",
        ],
    )
    executed = runner.invoke(
        app,
        [
            "qa-assembly-sanity-run",
            "asset-test",
            "--run-id",
            "assembly-public",
            "--plan-sha256",
            "a" * 64,
        ],
    )
    diagnosed = runner.invoke(
        app,
        [
            "qa-diagnose",
            "asset-test",
            "--qa-run-id",
            "qa-public",
            "--max-camera-probes",
            "3",
            "--no-assembly-multiview",
        ],
    )
    assert planned.exit_code == 0
    assert executed.exit_code == 0
    assert diagnosed.exit_code == 0
    assert calls[0] == (
        "plan",
        "asset-test",
        {"run_id": "assembly-public", "resolution": 256},
    )
    assert calls[1] == (
        "run",
        "asset-test",
        {
            "run_id": "assembly-public",
            "plan_sha256": "a" * 64,
            "render_engine": "eevee",
            "render_device": "auto",
        },
    )
    assert calls[2] == (
        "diagnose",
        "asset-test",
        {
            "qa_run_id": "qa-public",
            "diagnostic_id": "camera-geometry-v1",
            "max_camera_probes": 3,
            "include_multiview_sanity": False,
            "render_engine": "eevee",
            "render_device": "auto",
        },
    )

    monkeypatch.setattr(mcp_module, "plan_job_assembly_multiview_sanity", fake_plan)
    monkeypatch.setattr(mcp_module, "run_job_assembly_multiview_sanity", fake_run)
    monkeypatch.setattr(mcp_module, "run_job_visual_diagnostics", fake_diagnose)
    mcp_module.plan_assembly_multiview_sanity(
        "asset-test",
        run_id="assembly-mcp",
        resolution=320,
    )
    mcp_module.run_assembly_multiview_sanity(
        "asset-test",
        "assembly-mcp",
        "b" * 64,
    )
    mcp_module.run_visual_diagnostics(
        "asset-test",
        "qa-mcp",
        max_camera_probes=2,
        include_multiview_sanity=False,
    )
    assert calls[-3][0] == "plan"
    assert calls[-2][0] == "run"
    assert calls[-1][0] == "diagnose"

    with pytest.raises(ValueError, match=r"resolution must be within \[128, 1024\]"):
        mcp_module.plan_assembly_multiview_sanity(
            "asset-test",
            run_id="assembly-invalid",
            resolution=64,
        )
    with pytest.raises(ValueError, match=r"max_camera_probes must be within \[1, 12\]"):
        mcp_module.run_visual_diagnostics(
            "asset-test",
            "qa-invalid",
            max_camera_probes=13,
        )


def test_multiview_sanity_commands_and_mcp_tools_are_allowlisted() -> None:
    """Keep both diagnostic commands visible and both MCP operations explicitly allowed."""

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "qa-assembly-sanity-plan" in result.output
    assert "qa-assembly-sanity-run" in result.output
    assert "qa-diagnose" in result.output
    root = Path(__file__).resolve().parents[1]
    with (root / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert {
        "plan_assembly_multiview_sanity",
        "run_visual_diagnostics",
        "run_assembly_multiview_sanity",
    }.issubset(enabled)
