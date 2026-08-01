from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import codex_blender_modeler.orchestration.service as orchestration_service
from codex_blender_modeler.optimization.service import initialize_asset_profile
from codex_blender_modeler.orchestration.locks import (
    acquire_workflow_lock,
    release_workflow_lock,
    write_expired_lock_for_test,
)
from codex_blender_modeler.orchestration.models import WorkflowAttempt, WorkflowStep
from codex_blender_modeler.orchestration.service import (
    approve_workflow_gate,
    cancel_workflow,
    complete_workflow_step,
    destination_adapters,
    plan_workflow,
    reconcile_workflow,
    resume_workflow,
)
from codex_blender_modeler.workspace import create_job, job_dir, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def _image(path: Path, color: tuple[int, int, int] = (60, 110, 170)) -> Path:
    """Create one small deterministic RGB reference fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 32), color).save(path)
    return path


def _new_proxy_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    scope: str = "auto",
):
    """Plan and analyze one isolated proxy workflow for marker/approval tests."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "reference.png")
    state = plan_workflow(
        "이 이미지로 정적 3D 프록시 모델을 만들어줘",
        job_id="workflow_asset",
        reference_path=reference,
        scope=scope,
    )
    state = resume_workflow("workflow_asset", state.workflow_id, max_host_steps=1)
    return workspace / "workflow_asset", state


def _author_modeling_plan(root: Path, state) -> None:
    """Promote the deterministic scaffold to one schema-valid authored modeling plan."""

    path = root / "analysis" / "modeling_plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stage"] = "authored"
    payload["objects"] = [
        {
            "id": "asset.body",
            "label": "body",
            "recommended_geometry": "primitive",
            "source_ids": ["reference"],
            "bbox_norm": [0.1, 0.1, 0.9, 0.9],
            "observed": True,
            "confidence": 0.8,
            "notes": [],
        }
    ]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    current = next(
        item for item in state.steps if item.step_id == "geometry.modeling_plan"
    )
    assert current.input_fingerprint


def _complete_modeling_plan(root: Path, state):
    """Record the exact agent marker for the authored modeling plan."""

    _author_modeling_plan(root, state)
    current = next(
        item for item in state.steps if item.step_id == "geometry.modeling_plan"
    )
    return complete_workflow_step(
        "workflow_asset",
        state.workflow_id,
        "geometry.modeling_plan",
        input_fingerprint=str(current.input_fingerprint),
        note="Authored one observed semantic object from the reference.",
    )


def _complete_proxy_scene(root: Path, state):
    """Write one valid SceneSpec and bind it to the waiting proxy-author step."""

    seed = json.loads(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    seed["job_id"] = "workflow_asset"
    scene_spec = root / "analysis" / "scene_spec.json"
    scene_spec.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    current = next(
        item for item in state.steps if item.step_id == "geometry.proxy_author"
    )
    assert current.input_fingerprint
    return complete_workflow_step(
        "workflow_asset",
        state.workflow_id,
        "geometry.proxy_author",
        input_fingerprint=str(current.input_fingerprint),
        note="Authored a schema-valid deterministic proxy SceneSpec.",
    )


def test_new_short_request_creates_isolated_proxy_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A new image creates one lowercase job and stops before agent judgment."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    assert state.status == "waiting_for_agent"
    assert state.current_step_id == "geometry.modeling_plan"
    assert state.milestone == "analyzed"
    assert state.execution_policy == "standard"
    assert state.delivery_scope == "preview_only"
    workflow = root / "workflows" / state.workflow_id
    assert (workflow / "request.json").is_file()
    assert (workflow / "routing.json").is_file()
    assert (workflow / "plan.json").is_file()
    plan = json.loads((workflow / "plan.json").read_text(encoding="utf-8"))
    step_ids = [item["step_id"] for item in plan["steps"]]
    assert plan["execution_policy"] == "standard"
    assert plan["delivery_scope"] == "preview_only"
    assert step_ids.index("proxy.report") < step_ids.index("geometry.proxy_approval")
    modeling_step = next(
        item for item in plan["steps"] if item["step_id"] == "geometry.modeling_plan"
    )
    assert modeling_step["parameters"]["require_surface_detail_policy"] is True
    assert any("surface" in text.lower() for text in modeling_step["instructions"])
    report = next(item for item in plan["steps"] if item["step_id"] == "proxy.report")
    assert report["tool_name"] == "generate_pdf_report"
    assert report["outputs"][0]["path"].startswith(
        f"workflows/{state.workflow_id}/artifacts/pdf/"
    )
    assert report["outputs"][0]["lifecycle"] == "immutable_run"
    request_text = (workflow / "request.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in request_text
    assert "input/reference.png" in request_text


def test_new_workflow_rejects_removed_surface_detail_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Require explicit small-detail routing on newly planned agent modeling steps."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    path = root / "analysis" / "modeling_plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stage"] = "authored"
    payload["objects"] = [
        {
            "id": "asset.body",
            "label": "body",
            "recommended_geometry": "primitive",
            "source_ids": ["reference"],
            "bbox_norm": [0.1, 0.1, 0.9, 0.9],
            "observed": True,
            "confidence": 0.8,
            "notes": [],
        }
    ]
    payload.pop("surface_detail_policy", None)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    current = next(
        item for item in state.steps if item.step_id == "geometry.modeling_plan"
    )

    with pytest.raises(RuntimeError, match="requires surface_detail_policy"):
        complete_workflow_step(
            "workflow_asset",
            state.workflow_id,
            "geometry.modeling_plan",
            input_fingerprint=str(current.input_fingerprint),
            note="Attempted to omit the required surface-detail policy.",
        )


def test_new_workflow_persists_primary_object_only_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bind an object-only selection through job, request, plan, state, and instructions."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "car.png")
    state = plan_workflow(
        "Model only the central car and exclude the surrounding rocks and seabed.",
        job_id="subject_only_asset",
        reference_path=reference,
        reference_content_scope="primary_object_only",
        target_subject="central car",
    )
    root = workspace / "subject_only_asset"
    workflow = root / "workflows" / state.workflow_id
    metadata = json.loads((root / "job.json").read_text(encoding="utf-8"))
    request = json.loads((workflow / "request.json").read_text(encoding="utf-8"))
    plan = json.loads((workflow / "plan.json").read_text(encoding="utf-8"))
    modeling_step = next(
        item for item in plan["steps"] if item["step_id"] == "geometry.modeling_plan"
    )
    scene_step = next(
        item for item in plan["steps"] if item["step_id"] == "geometry.proxy_author"
    )

    assert metadata["reference_content_scope"] == "primary_object_only"
    assert metadata["target_subject"] == "central car"
    assert request["reference_content_scope"] == "primary_object_only"
    assert plan["reference_content_scope"] == "primary_object_only"
    assert state.reference_content_scope == "primary_object_only"
    assert state.target_subject == "central car"
    assert any(
        "Exclude independent terrain" in instruction
        for instruction in modeling_step["instructions"]
    )
    assert any(
        "qa_role:primary" in instruction
        for instruction in scene_step["instructions"]
    )

    with pytest.raises(ValueError, match="immutable"):
        plan_workflow(
            "Revise this asset.",
            job_id="subject_only_asset",
            intent="revise_asset",
            reference_content_scope="full_reference",
        )


def test_background_preview_plan_skips_only_generic_review_gates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Plan one bounded exterior preview with direct QA and no generic approvals."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "background.png")
    state = plan_workflow(
        "Create a static exterior background prop and stop with a review preview.",
        job_id="background_preview_asset",
        reference_path=reference,
        execution_policy="background_exterior",
        delivery_scope="preview_only",
    )
    workflow_root = (
        workspace
        / "background_preview_asset"
        / "workflows"
        / state.workflow_id
    )
    request = json.loads((workflow_root / "request.json").read_text(encoding="utf-8"))
    routing = json.loads((workflow_root / "routing.json").read_text(encoding="utf-8"))
    plan = json.loads((workflow_root / "plan.json").read_text(encoding="utf-8"))
    steps = plan["steps"]
    step_ids = [item["step_id"] for item in steps]

    assert state.execution_policy == "background_exterior"
    assert state.delivery_scope == "preview_only"
    assert request["execution_policy"] == routing["execution_policy"] == (
        "background_exterior"
    )
    assert request["delivery_scope"] == routing["delivery_scope"] == "preview_only"
    assert request["requested_scope"] == "full"
    assert request["fast_quality_policy"] == "review_delivery_v2"
    assert plan["fast_quality_policy"] == "review_delivery_v2"
    assert request["budgets"]["max_qa_iterations"] == 1
    assert request["budgets"]["max_pre_qa_fit_attempts"] == 2
    assert request["budgets"]["max_texture_resolution"] == 512
    assert request["budgets"]["external_provider_budget"] == 0
    assert "geometry.background_author" in step_ids
    assert "background.fit" in step_ids
    assert step_ids.index("geometry.background_author") < step_ids.index(
        "background.fit"
    )
    assert step_ids.index("background.fit") < step_ids.index(
        "background_geometry.build"
    )
    assert "geometry.proxy_author" not in step_ids
    assert "geometry.detail_author" not in step_ids
    assert "qa.run" in step_ids
    assert "background.eligibility" in step_ids
    assert step_ids.index("qa.run") < step_ids.index("background.eligibility")
    assert step_ids.index("background.eligibility") < step_ids.index("qa.report")
    fit = next(item for item in steps if item["step_id"] == "background.fit")
    assert fit["parameters"]["max_attempts"] == 2
    eligibility = next(
        item for item in steps if item["step_id"] == "background.eligibility"
    )
    assert eligibility["parameters"]["quality_policy"] == "review_delivery_v2"
    assert eligibility["parameters"]["qa_run_id"] != "latest"
    assert next(item for item in steps if item["step_id"] == "qa.run")[
        "parameters"
    ]["include_generated_target"] is False
    assert not any(item["execution_mode"] == "approval" for item in steps)
    assert not any(item["execution_mode"] == "specialized_approval" for item in steps)
    assert not any(item["phase"] == "portable" for item in steps)
    assert plan["terminal_step_id"].startswith("background_delivery_")
    assert plan["terminal_step_id"].endswith(".report")


def test_background_portable_plan_keeps_exact_optimization_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep V0.7 optimization approval while omitting generic fast-lane reviews."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "background_package.png")
    state = plan_workflow(
        "Create a static exterior background asset and an engine-neutral FBX package.",
        job_id="background_package_asset",
        reference_path=reference,
        execution_policy="background_exterior",
        delivery_scope="portable_package",
        profile_id="fbx_interchange",
        destination_kind="engine_neutral",
    )
    workflow_root = (
        workspace
        / "background_package_asset"
        / "workflows"
        / state.workflow_id
    )
    plan = json.loads((workflow_root / "plan.json").read_text(encoding="utf-8"))
    steps = {item["step_id"]: item for item in plan["steps"]}
    specialized = [
        item
        for item in steps.values()
        if item["execution_mode"] == "specialized_approval"
    ]

    assert state.delivery_scope == "portable_package"
    assert not any(
        item["execution_mode"] == "approval" for item in steps.values()
    )
    assert [item["approval_gate"] for item in specialized] == [
        "optimization_plan"
    ]
    decision_instructions = " ".join(
        steps["portable.plan_approval"]["instructions"]
    )
    assert "approve, revise_asset, revise_profile, or cancel" in decision_instructions
    assert "intent=revise_asset" in decision_instructions
    assert "execution_policy=standard" in decision_instructions
    decision_next_action = orchestration_service._next_action(
        WorkflowStep.model_validate(steps["portable.plan_approval"]),
        "a" * 64,
        "waiting_for_approval",
    )
    assert "approve, revise_asset, revise_profile, or cancel" in decision_next_action
    assert "no choice is automatic" in decision_next_action
    assert steps["portable.optimize"]["depends_on"] == [
        "portable.plan_approval"
    ]
    assert "portable.final_approval" not in steps
    assert "portable.package" in steps
    assert "portable.roundtrip" in steps
    quality_path = steps["background.eligibility"]["parameters"]["output_path"]
    assert steps["portable.plan"]["parameters"]["source_quality_path"] == quality_path
    assert (
        steps["portable.report"]["parameters"]["background_quality_report_path"]
        == quality_path
    )
    assert plan["terminal_step_id"].startswith("background_delivery_")
    terminal_report = steps[plan["terminal_step_id"]]
    assert terminal_report["parameters"]["qa_run_id"] != "latest"
    assert terminal_report["parameters"]["optimization_run_id"] != "latest"
    assert terminal_report["parameters"]["package_id"] != "latest"


def test_background_preview_can_start_a_separate_package_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Extend an eligible preview job through a new immutable package-only workflow."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "background_extend.png")
    preview = plan_workflow(
        "Create a static exterior background preview.",
        job_id="background_extend_asset",
        reference_path=reference,
        execution_policy="background_exterior",
        delivery_scope="preview_only",
    )
    binding = orchestration_service.BackgroundPreviewBinding(
        workflow_id=preview.workflow_id,
        plan_sha256="1" * 64,
        terminal_step_id="background_delivery_preview.report",
        terminal_completion_fingerprint="2" * 64,
        qa_run_id="v08-preview-qa",
        source_fingerprint="3" * 64,
        build_fingerprint="4" * 64,
        quality_status="needs_revision",
        standard_workflow_recommended=True,
        quality_report_path="reports/background_delivery/preview_quality.json",
        quality_report_sha256="5" * 64,
        bound_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        orchestration_service,
        "_validate_background_execution",
        lambda **_kwargs: binding,
    )
    root = workspace / "background_extend_asset"
    seed = json.loads(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    seed["job_id"] = "background_extend_asset"
    (root / "analysis" / "scene_spec.json").write_text(
        json.dumps(seed, indent=2) + "\n",
        encoding="utf-8",
    )
    package = plan_workflow(
        "Package the approved background asset as engine-neutral FBX.",
        job_id="background_extend_asset",
        intent="portable_package",
        execution_policy="background_exterior",
        delivery_scope="portable_package",
        profile_id="fbx_interchange",
        destination_kind="engine_neutral",
    )
    package_plan = json.loads(
        (
            root / "workflows" / package.workflow_id / "plan.json"
        ).read_text(encoding="utf-8")
    )

    assert preview.workflow_id != package.workflow_id
    assert package_plan["steps"][0]["step_id"] == "geometry.prerequisite"
    assert package_plan["steps"][0]["tool_name"] == (
        "verify_background_preview_prerequisite"
    )
    assert package_plan["steps"][0]["parameters"]["preview_workflow_id"] == (
        preview.workflow_id
    )
    assert package_plan["steps"][0]["parameters"]["require_new_output"] is True
    assert "geometry.background_author" not in {
        item["step_id"] for item in package_plan["steps"]
    }
    assert any(
        item["approval_gate"] == "optimization_plan"
        for item in package_plan["steps"]
    )
    terminal = next(
        item
        for item in package_plan["steps"]
        if item["step_id"] == package_plan["terminal_step_id"]
    )
    assert terminal["parameters"]["qa_run_id"] == binding.qa_run_id
    assert terminal["parameters"]["optimization_run_id"] != "latest"
    assert terminal["parameters"]["package_id"] != "latest"
    portable_plan = next(
        item
        for item in package_plan["steps"]
        if item["step_id"] == "portable.plan"
    )
    assert portable_plan["parameters"]["source_quality_path"] == (
        binding.quality_report_path
    )
    prerequisite = package_plan["steps"][0]["parameters"]
    assert prerequisite["quality_status"] == "needs_revision"
    assert prerequisite["quality_report_sha256"] == binding.quality_report_sha256


def test_background_preview_binding_rejects_changed_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fail closed when a package continuation no longer matches preview provenance."""

    binding = orchestration_service.BackgroundPreviewBinding(
        workflow_id="wf-preview-binding",
        plan_sha256="1" * 64,
        terminal_step_id="background_delivery_preview.report",
        terminal_completion_fingerprint="2" * 64,
        qa_run_id="v08-preview-binding-qa",
        source_fingerprint="3" * 64,
        build_fingerprint="4" * 64,
        bound_at=datetime.now(UTC),
    )
    request = orchestration_service.WorkflowRequest(
        workflow_id="wf-package-binding",
        job_id="background_binding_asset",
        raw_request="Package the completed background preview.",
        intent_hint="portable_package",
        requested_scope="full",
        execution_policy="background_exterior",
        delivery_scope="portable_package",
        background_preview_binding=binding,
        budgets=orchestration_service.WorkflowBudgets(
            max_qa_iterations=1,
            max_texture_resolution=512,
        ),
        created_at=datetime.now(UTC),
    )
    output = (
        "reports/background_delivery/"
        "wf-package-binding_preview_binding.json"
    )
    step = orchestration_service.WorkflowStep(
        step_id="geometry.prerequisite",
        title="Verify exact preview",
        phase="geometry",
        execution_mode="host",
        tool_name="verify_background_preview_prerequisite",
        parameters={
            "require_new_output": True,
            "output_path": output,
            "preview_workflow_id": binding.workflow_id,
            "preview_plan_sha256": binding.plan_sha256,
            "preview_terminal_fingerprint": (
                binding.terminal_completion_fingerprint
            ),
            "source_fingerprint": binding.source_fingerprint,
            "build_fingerprint": binding.build_fingerprint,
        },
    )
    returned = iter(
        [
            SimpleNamespace(
                execution_policy="background_exterior",
                delivery_scope="preview_only",
            ),
            SimpleNamespace(terminal_step_id=binding.terminal_step_id),
            SimpleNamespace(),
        ]
    )
    monkeypatch.setattr(
        orchestration_service,
        "_load_model",
        lambda *_args, **_kwargs: next(returned),
    )
    monkeypatch.setattr(
        orchestration_service,
        "_reconcile_locked",
        lambda *_args, **_kwargs: SimpleNamespace(
            status="completed",
            milestone="delivered_for_review",
            plan_sha256=binding.plan_sha256,
            steps=[
                SimpleNamespace(
                    step_id=binding.terminal_step_id,
                    completion_fingerprint=(
                        binding.terminal_completion_fingerprint
                    ),
                )
            ],
        ),
    )
    monkeypatch.setattr(
        orchestration_service,
        "collect_source_provenance",
        lambda *_args, **_kwargs: SimpleNamespace(
            source_fingerprint="5" * 64,
            build_fingerprint=binding.build_fingerprint,
        ),
    )
    monkeypatch.setattr(
        orchestration_service,
        "load_interior_scope",
        lambda _root: None,
    )
    monkeypatch.setattr(
        orchestration_service,
        "load_scene_spec",
        lambda _path: SimpleNamespace(),
    )
    monkeypatch.setattr(
        orchestration_service,
        "list_interior_objects",
        lambda _spec: [],
    )

    with pytest.raises(
        orchestration_service.OrchestrationArtifactConflict,
        match="orchestration_artifact_conflict",
    ):
        orchestration_service._verify_background_preview_prerequisite(
            tmp_path,
            request,
            step,
        )
    result = json.loads((tmp_path / output).read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["status"] == "orchestration_artifact_conflict"
    assert "canonical source fingerprint changed after preview" in (
        result["blocking_reasons"]
    )


def test_background_package_extension_requires_a_completed_current_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject package-only continuation when no current fast preview is complete."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "background_incomplete.png")
    create_job("background_incomplete_asset", reference, "concept", [])
    root = workspace / "background_incomplete_asset"
    seed = json.loads(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    seed["job_id"] = "background_incomplete_asset"
    (root / "analysis" / "scene_spec.json").write_text(
        json.dumps(seed, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="current completed"):
        plan_workflow(
            "Package this background asset.",
            job_id="background_incomplete_asset",
            intent="portable_package",
            execution_policy="background_exterior",
            delivery_scope="portable_package",
            profile_id="fbx_interchange",
        )
    assert not (root / "workflows" / "latest.json").exists()


def test_legacy_background_eligibility_retains_high_finding_blocker(
    tmp_path: Path,
) -> None:
    """Keep the historical high-finding blocker for plans without the new policy."""

    root = tmp_path / "job"
    report_path = root / "qa" / "runs" / "run-001" / "visual_qa_report.json"
    report_path.parent.mkdir(parents=True)
    report = {
        "schema_version": "0.6.0",
        "job_id": "background_eligibility_asset",
        "run_id": "run-001",
        "request_sha256": "0" * 64,
        "camera_fingerprint": "1" * 64,
        "direct_metrics": {
            "silhouette_iou": 0.5,
            "silhouette_union_fraction": 0.5,
            "global_bbox": {
                "reference_bbox_norm": [0.1, 0.1, 0.9, 0.9],
                "rendered_bbox_norm": [0.1, 0.1, 0.9, 0.9],
                "center_error_norm": 0.0,
                "size_error_norm": 0.0,
            },
            "semantic_deviations": [],
            "overall_direct_score": 0.5,
        },
        "findings": [
            {
                "id": "direct.global_silhouette",
                "target_ids": ["asset.landmark"],
                "issue_type": "silhouette",
                "severity": "high",
                "description": "The overall silhouette differs materially.",
                "evidence_sources": ["direct_reference"],
                "confidence": 0.95,
                "metrics": {},
                "suggestion": None,
            }
        ],
        "generated_target_status": "not_requested",
        "warnings": [],
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    latest_path = root / "qa" / "latest.json"
    latest_path.write_text(
        json.dumps(
            {
                "visual_qa_report": (
                    "qa/runs/run-001/visual_qa_report.json"
                )
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    request = orchestration_service.WorkflowRequest(
        workflow_id="wf-background-eligibility",
        job_id="background_eligibility_asset",
        raw_request="Create a background exterior.",
        requested_scope="full",
        execution_policy="background_exterior",
        delivery_scope="preview_only",
        budgets=orchestration_service.WorkflowBudgets(
            max_qa_iterations=1,
            max_texture_resolution=512,
        ),
        created_at=datetime.now(UTC),
    )
    step = orchestration_service.WorkflowStep(
        step_id="background.eligibility",
        title="Check eligibility",
        phase="qa",
        execution_mode="host",
        tool_name="evaluate_background_delivery",
        parameters={
            "output_path": (
                "reports/background_delivery/"
                "wf-background-eligibility_eligibility.json"
            )
        },
    )

    with pytest.raises(RuntimeError, match="requires_standard_workflow"):
        orchestration_service._evaluate_background_delivery(root, request, step)
    result = json.loads(
        (
            root
            / "reports"
            / "background_delivery"
            / "wf-background-eligibility_eligibility.json"
        ).read_text(encoding="utf-8")
    )
    assert result["ok"] is False
    assert result["status"] == "requires_standard_workflow"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mode": "measured"}, "concept mode"),
        ({"scale_anchors": ["width = 2 m"]}, "scale anchors"),
        ({"include_destination_handoff": True}, "destination handoff"),
        ({"destination_kind": "unity"}, "engine-neutral"),
        (
            {"budgets": orchestration_service.WorkflowBudgets(
                external_provider_budget=1
            )},
            "external provider",
        ),
    ],
)
def test_background_unsafe_inputs_fail_before_job_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kwargs: dict,
    message: str,
) -> None:
    """Reject excluded fast-lane inputs before persisting canonical job evidence."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "unsafe_background.png")
    with pytest.raises(ValueError, match=message):
        plan_workflow(
            "Create a static exterior background prop.",
            job_id="unsafe_background_asset",
            reference_path=reference,
            execution_policy="background_exterior",
            delivery_scope="preview_only",
            **kwargs,
        )
    assert not (workspace / "unsafe_background_asset").exists()


@pytest.mark.parametrize(
    ("request_text", "risk"),
    [
        ("Create a background building with an interior.", "interior"),
        ("Create a rigged background prop.", "rig_or_skinning"),
        ("Create an animated background prop.", "animation"),
        ("Create an interactive gameplay object.", "gameplay"),
        ("Create this directly for Unity.", "engine_specific"),
    ],
)
def test_background_excluded_request_scope_requires_standard_before_job_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    request_text: str,
    risk: str,
) -> None:
    """Keep actual scope and runtime risks outside the visual-quality outcome model."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "excluded_scope.png")
    with pytest.raises(
        ValueError,
        match=rf"requires_standard_workflow:.*{risk}",
    ):
        plan_workflow(
            request_text,
            job_id="excluded_background_asset",
            reference_path=reference,
            execution_policy="background_exterior",
            delivery_scope="preview_only",
        )
    assert not (workspace / "excluded_background_asset").exists()


def test_background_negative_scope_limits_do_not_trigger_false_risk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Allow explicit exclusions such as no interior while retaining the fast policy."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "negative_scope.png")
    state = plan_workflow(
        "Create a static exterior prop without interior, rigging, animation, or gameplay.",
        job_id="negative_scope_background",
        reference_path=reference,
        execution_policy="background_exterior",
        delivery_scope="preview_only",
    )

    assert state.execution_policy == "background_exterior"
    assert state.status == "planned"


def test_analysis_scaffold_is_valid_but_not_agent_complete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep a valid analyzer scaffold distinct from an authored agent completion."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    step = next(item for item in state.steps if item.step_id == "geometry.modeling_plan")
    assert step.status == "waiting_for_agent"
    assert step.artifacts[0].integrity == "valid"
    assert step.artifacts[0].verification == "partially_verified"
    assert step.input_fingerprint
    with pytest.raises(RuntimeError, match="stage=authored"):
        complete_workflow_step(
            "workflow_asset",
            state.workflow_id,
            "geometry.modeling_plan",
            input_fingerprint=step.input_fingerprint,
            note="A scaffold must not be accepted as authored.",
        )
    assert not (root / "workflows" / state.workflow_id / "completions").exists()


def test_existing_job_rejects_different_primary_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A different asset cannot silently reuse an existing job ID."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    first = _image(tmp_path / "first.png", (10, 20, 30))
    second = _image(tmp_path / "second.png", (220, 210, 200))
    create_job("existing_asset", first, "concept", [])
    before = (workspace / "existing_asset" / "job.json").read_bytes()
    with pytest.raises(FileExistsError, match="cannot be reused"):
        plan_workflow(
            "이 이미지로 다시 만들어줘",
            job_id="existing_asset",
            reference_path=second,
        )
    assert (workspace / "existing_asset" / "job.json").read_bytes() == before
    assert not (workspace / "existing_asset" / "workflows" / "latest.json").exists()


def test_existing_job_rejects_explicit_new_asset_with_matching_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Force existing assets through revision even when the reference hash matches."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "reference.png", (30, 90, 160))
    create_job("existing_asset", reference, "concept", [])
    root = workspace / "existing_asset"
    before = (root / "job.json").read_bytes()
    with pytest.raises(FileExistsError, match="Use revise_asset"):
        plan_workflow(
            "같은 레퍼런스로 새 자산 생성을 다시 시작해줘",
            job_id="existing_asset",
            reference_path=reference,
            intent="new_asset",
        )
    assert (root / "job.json").read_bytes() == before
    assert list((root / "workflows").iterdir()) == []


def test_add_view_resume_promotes_staged_input_and_reanalyzes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Measured-view routing uses add_view and completes deterministic reanalysis."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    front = _image(tmp_path / "front.png", (180, 80, 40))
    create_job("measured_asset", primary, "measured", ["width = 2 m"])
    state = plan_workflow(
        "정면도를 추가해서 다시 분석해줘",
        job_id="measured_asset",
        reference_path=front,
        view_kind="front",
        mode="measured",
    )
    assert state.current_step_id == "view.add"
    finished = resume_workflow("measured_asset", state.workflow_id, max_host_steps=2)
    root = workspace / "measured_asset"
    assert finished.status == "completed"
    assert (root / "input" / "front.png").is_file()
    assert (root / "analysis" / "reference_analysis.json").is_file()
    metadata = json.loads((root / "job.json").read_text(encoding="utf-8"))
    assert {item["kind"] for item in metadata["sources"]} == {"reference", "front"}


def test_agent_completion_and_generic_approval_are_exactly_hash_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Agent markers and proxy approval reject stale or guessed fingerprints."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    state = _complete_modeling_plan(root, state)
    assert state.current_step_id == "geometry.proxy_author"
    state = _complete_proxy_scene(root, state)
    assert state.current_step_id == "proxy.build"
    (root / "blender").mkdir(exist_ok=True)
    (root / "blender" / "scene.blend").write_bytes(b"workflow-blend")
    (root / "renders").mkdir(exist_ok=True)
    (root / "renders" / "preview.png").write_bytes(b"workflow-preview")
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "scene_inventory.json").write_text(
        '{"job_id":"workflow_asset","objects":[]}\n',
        encoding="utf-8",
    )
    (root / "reports" / "validation.json").write_text(
        '{"ok":true,"errors":[],"warnings":[]}\n',
        encoding="utf-8",
    )
    original_execute = orchestration_service._execute_host_tool
    monkeypatch.setattr(
        orchestration_service,
        "_execute_host_tool",
        lambda *_args, **_kwargs: None,
    )
    state = resume_workflow(
        "workflow_asset",
        state.workflow_id,
        max_host_steps=4,
    )
    assert state.current_step_id == "proxy.report"
    monkeypatch.setattr(
        orchestration_service,
        "_execute_host_tool",
        original_execute,
    )
    state = resume_workflow("workflow_asset", state.workflow_id, max_host_steps=1)
    assert state.status == "waiting_for_approval"
    assert state.current_step_id == "geometry.proxy_approval"
    report_state = next(item for item in state.steps if item.step_id == "proxy.report")
    assert all((root / item.path).is_file() for item in report_state.artifacts)
    approval_state = next(
        item for item in state.steps if item.step_id == "geometry.proxy_approval"
    )
    with pytest.raises(ValueError, match="does not match"):
        approve_workflow_gate(
            "workflow_asset",
            state.workflow_id,
            "geometry.proxy_approval",
            artifact_fingerprint="0" * 64,
            approval_note="wrong hash",
        )
    completed = approve_workflow_gate(
        "workflow_asset",
        state.workflow_id,
        "geometry.proxy_approval",
        artifact_fingerprint=str(approval_state.input_fingerprint),
        approval_note="Proxy silhouette and layout reviewed.",
    )
    assert completed.status == "completed"
    assert completed.milestone == "completed"


def test_stale_agent_output_invalidates_completion_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Changing an agent output after completion marks its old receipt stale."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    state = _complete_modeling_plan(root, state)
    plan_path = root / "analysis" / "modeling_plan.json"
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["global_notes"].append("changed after marker")
    plan_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    stale = reconcile_workflow("workflow_asset", state.workflow_id)
    step = next(item for item in stale.steps if item.step_id == "geometry.modeling_plan")
    assert step.status == "stale"
    assert stale.status == "blocked"


def test_detail_author_preserves_exact_archived_proxy_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep approved proxy evidence valid during an archived detailed replacement."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path, scope="full")
    state = _complete_modeling_plan(root, state)
    state = _complete_proxy_scene(root, state)
    (root / "blender").mkdir(exist_ok=True)
    (root / "blender" / "scene.blend").write_bytes(b"workflow-blend")
    (root / "renders").mkdir(exist_ok=True)
    (root / "renders" / "preview.png").write_bytes(b"workflow-preview")
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "scene_inventory.json").write_text(
        '{"job_id":"workflow_asset","objects":[]}\n',
        encoding="utf-8",
    )
    (root / "reports" / "validation.json").write_text(
        '{"ok":true,"errors":[],"warnings":[]}\n',
        encoding="utf-8",
    )
    original_execute = orchestration_service._execute_host_tool
    monkeypatch.setattr(
        orchestration_service,
        "_execute_host_tool",
        lambda *_args, **_kwargs: None,
    )
    state = resume_workflow("workflow_asset", state.workflow_id, max_host_steps=4)
    monkeypatch.setattr(
        orchestration_service,
        "_execute_host_tool",
        original_execute,
    )
    state = resume_workflow("workflow_asset", state.workflow_id, max_host_steps=1)
    approval = next(
        item for item in state.steps if item.step_id == "geometry.proxy_approval"
    )
    state = approve_workflow_gate(
        "workflow_asset",
        state.workflow_id,
        "geometry.proxy_approval",
        artifact_fingerprint=str(approval.input_fingerprint),
        approval_note="Proxy evidence reviewed before detailed authoring.",
    )
    detail = next(
        item for item in state.steps if item.step_id == "geometry.detail_author"
    )
    scene = root / "analysis" / "scene_spec.json"
    history = root / "history"
    history.mkdir(exist_ok=True)
    (history / "20260731T000000Z_scene_spec.json").write_bytes(scene.read_bytes())
    payload = json.loads(scene.read_text(encoding="utf-8"))
    payload["revision_notes"].append("Expected detailed geometry replacement.")
    scene.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    completed = complete_workflow_step(
        "workflow_asset",
        state.workflow_id,
        "geometry.detail_author",
        input_fingerprint=str(detail.input_fingerprint),
        note="Authored one archived detailed SceneSpec replacement.",
    )

    proxy = next(
        item for item in completed.steps if item.step_id == "geometry.proxy_author"
    )
    authored = next(
        item for item in completed.steps if item.step_id == "geometry.detail_author"
    )
    assert proxy.status == "complete"
    assert proxy.artifacts[0].currency == "superseded"
    assert authored.status == "complete"
    assert completed.current_step_id == "detail.build"

    def execute_detail(
        host_root: Path,
        _workflow_root: Path,
        _request,
        host_step,
        *,
        input_fingerprint: str,
    ) -> None:
        """Publish a changed detail preview while leaving other fixture outputs intact."""

        assert input_fingerprint
        if host_step.step_id == "detail.render":
            (host_root / "renders" / "preview.png").write_bytes(b"detail-preview")

    monkeypatch.setattr(
        orchestration_service,
        "_execute_host_tool",
        execute_detail,
    )
    advanced = resume_workflow(
        "workflow_asset",
        state.workflow_id,
        max_host_steps=3,
    )
    inspected = next(
        item for item in advanced.steps if item.step_id == "detail.inspect"
    )
    assert inspected.status == "complete"
    assert advanced.current_step_id == "detail.validate"


def test_cancel_preserves_artifacts_and_prevents_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cancellation is non-destructive and cannot be bypassed by resume."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    reference_hash = (root / "input" / "reference.png").read_bytes()
    cancelled = cancel_workflow(
        "workflow_asset",
        state.workflow_id,
        reason="User stopped the test workflow.",
    )
    assert cancelled.status == "cancelled"
    assert (root / "input" / "reference.png").read_bytes() == reference_hash
    with pytest.raises(RuntimeError, match="cannot be resumed"):
        resume_workflow("workflow_asset", state.workflow_id)


def test_lock_rejects_concurrency_and_recovers_expired_receipt(tmp_path: Path) -> None:
    """A live lock blocks writers while one expired valid receipt is archived safely."""

    root = tmp_path / "job"
    root.mkdir()
    first = acquire_workflow_lock(root, "lock_asset", "wf-lock-test")
    with pytest.raises(RuntimeError, match="Another workflow"):
        acquire_workflow_lock(root, "lock_asset", "wf-second")
    release_workflow_lock(root, first)
    write_expired_lock_for_test(root, "lock_asset", "wf-expired")
    recovered = acquire_workflow_lock(root, "lock_asset", "wf-recovered")
    assert list((root / "workflows" / "stale_locks").glob("*.json"))
    release_workflow_lock(root, recovered)


def test_failed_host_step_requires_explicit_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A deterministic host failure stays frozen until retry is explicitly authorized."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    state = plan_workflow(
        "Create a 3D proxy model from this image.",
        job_id="retry_asset",
        reference_path=primary,
    )
    original = orchestration_service._execute_host_tool

    def fail_once(*_args, **_kwargs) -> None:
        """Raise one deterministic fixture failure before any host output is written."""

        raise RuntimeError("fixture host failure")

    monkeypatch.setattr(orchestration_service, "_execute_host_tool", fail_once)
    failed = resume_workflow("retry_asset", state.workflow_id, max_host_steps=1)
    assert failed.status == "failed"
    frozen = resume_workflow("retry_asset", state.workflow_id, max_host_steps=1)
    assert frozen.status == "failed"
    assert next(
        item for item in frozen.steps if item.step_id == "reference.analyze"
    ).attempt_count == 1

    monkeypatch.setattr(orchestration_service, "_execute_host_tool", original)
    retried = resume_workflow(
        "retry_asset",
        state.workflow_id,
        max_host_steps=1,
        retry_failed=True,
    )
    assert retried.status == "waiting_for_agent"
    attempts = sorted(
        (
            workspace
            / "retry_asset"
            / "workflows"
            / state.workflow_id
            / "attempts"
            / "reference.analyze"
        ).glob("*.json")
    )
    assert len(attempts) == 2
    assert sorted(json.loads(path.read_text())["status"] for path in attempts) == [
        "failed",
        "succeeded",
    ]


def test_blocked_artifact_conflict_retries_only_with_exact_failed_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Permit an explicit retry after a host artifact conflict has been corrected."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "artifact-conflict.png")
    state = plan_workflow(
        "Create a 3D proxy model from this image.",
        job_id="artifact_conflict_retry_asset",
        reference_path=primary,
    )
    original = orchestration_service._execute_host_tool

    def fail_with_conflict(*_args, **_kwargs) -> None:
        """Emit one host-side ownership conflict with an immutable failed receipt."""

        raise orchestration_service.OrchestrationArtifactConflict(
            "orchestration_artifact_conflict: fixture source owner mismatch"
        )

    monkeypatch.setattr(
        orchestration_service,
        "_execute_host_tool",
        fail_with_conflict,
    )
    blocked = resume_workflow(
        "artifact_conflict_retry_asset",
        state.workflow_id,
        max_host_steps=1,
    )
    assert blocked.status == "blocked"
    assert blocked.reason_code == "orchestration_artifact_conflict"

    monkeypatch.setattr(orchestration_service, "_execute_host_tool", original)
    retried = resume_workflow(
        "artifact_conflict_retry_asset",
        state.workflow_id,
        max_host_steps=1,
        retry_failed=True,
    )
    assert retried.status == "waiting_for_agent"
    attempts = sorted(
        (
            workspace
            / "artifact_conflict_retry_asset"
            / "workflows"
            / state.workflow_id
            / "attempts"
            / "reference.analyze"
        ).glob("*.json")
    )
    assert len(attempts) == 2
    assert sorted(json.loads(path.read_text())["status"] for path in attempts) == [
        "failed",
        "succeeded",
    ]


def test_requires_standard_workflow_is_blocked_and_not_retryable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve fast-lane disqualification as a terminal blocked decision."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "background_blocked.png")
    state = plan_workflow(
        "Create one static exterior background preview.",
        job_id="background_blocked_asset",
        reference_path=primary,
        execution_policy="background_exterior",
        delivery_scope="preview_only",
    )

    def require_standard(*_args, **_kwargs) -> None:
        """Simulate one deterministic fast-lane eligibility disqualification."""

        raise orchestration_service.RequiresStandardWorkflow(
            "requires_standard_workflow: fixture"
        )

    monkeypatch.setattr(
        orchestration_service,
        "_execute_host_tool",
        require_standard,
    )
    blocked = resume_workflow(
        "background_blocked_asset",
        state.workflow_id,
        max_host_steps=1,
    )

    assert blocked.status == "blocked"
    assert "new immutable standard workflow" in (blocked.next_action or "")
    assert next(
        item for item in blocked.steps if item.step_id == "reference.analyze"
    ).status == "blocked"
    with pytest.raises(RuntimeError, match="No current failed"):
        resume_workflow(
            "background_blocked_asset",
            state.workflow_id,
            retry_failed=True,
        )


def test_resume_finalizes_an_interrupted_attempt_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A prior running receipt is marked interrupted before a fresh unique attempt starts."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    state = plan_workflow(
        "Create a 3D proxy model from this image.",
        job_id="interrupted_asset",
        reference_path=primary,
    )
    root = workspace / "interrupted_asset"
    workflow_root = root / "workflows" / state.workflow_id
    current = next(
        item for item in state.steps if item.step_id == "reference.analyze"
    )
    assert current.input_fingerprint
    receipt = WorkflowAttempt(
        attempt_id="attempt-0001-interrupted",
        workflow_id=state.workflow_id,
        job_id="interrupted_asset",
        step_id="reference.analyze",
        plan_sha256=sha256_file(workflow_root / "plan.json"),
        input_fingerprint=current.input_fingerprint,
        status="running",
        started_at=datetime.now(UTC),
    )
    receipt_path = (
        workflow_root
        / "attempts"
        / "reference.analyze"
        / f"{receipt.attempt_id}.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")

    resumed = resume_workflow(
        "interrupted_asset",
        state.workflow_id,
        max_host_steps=1,
    )
    assert resumed.status == "waiting_for_agent"
    recovered = WorkflowAttempt.model_validate_json(receipt_path.read_text())
    assert recovered.status == "failed"
    assert recovered.error_type == "InterruptedAttempt"


def test_explicit_unity_target_stops_at_engine_neutral_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An explicit unsupported engine never receives fabricated adapter parity."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    create_job("portable_asset", primary, "concept", [])
    state = plan_workflow(
        "Unity로 옮길 FBX 패키지를 만들어줘",
        job_id="portable_asset",
        intent="portable_package",
    )
    workflow_root = workspace / "portable_asset" / "workflows" / state.workflow_id
    plan = json.loads((workflow_root / "plan.json").read_text(encoding="utf-8"))
    assert plan["destination"]["status"] == "unsupported"
    assert plan["destination"]["terminal_boundary"] == "portable_package"
    assert plan["steps"][-1]["step_id"] == "destination.unsupported"
    assert plan["terminal_step_id"] == "portable.final_approval"
    assert plan["steps"][1]["parameters"]["profile_id"] == "fbx_interchange"
    portable_ids = [item["step_id"] for item in plan["steps"]]
    assert portable_ids.index("portable.report") < portable_ids.index(
        "portable.final_approval"
    )
    adapters = destination_adapters()
    unity = next(
        item for item in adapters["adapters"] if item["destination"] == "unity"
    )
    assert unity["status"] == "unsupported"


def test_portable_workflow_reuses_existing_customized_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve an existing reviewed profile instead of replacing it with defaults."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    create_job("portable_profile_reuse", primary, "concept", [])
    profile = initialize_asset_profile(
        "portable_profile_reuse",
        lod_mode="disabled",
        collision_strategy="compound",
    )
    profile_path = (
        workspace
        / "portable_profile_reuse"
        / "asset_profiles"
        / "portable_gltf.json"
    )
    before = profile_path.read_bytes()

    orchestration_service._ensure_workflow_asset_profile(
        workspace / "portable_profile_reuse",
        "portable_profile_reuse",
        "portable_gltf",
    )

    assert profile.lod.enabled is False
    assert profile_path.read_bytes() == before


def test_optional_destination_handoff_follows_passed_portable_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Place the optional V0.9 handoff after package approval with exact output paths."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    create_job("handoff_workflow_asset", primary, "concept", [])
    state = plan_workflow(
        "Prepare a portable GLB package and a Codex destination handoff.",
        job_id="handoff_workflow_asset",
        intent="portable_package",
        profile_id="portable_gltf",
        include_destination_handoff=True,
    )
    workflow_root = (
        workspace / "handoff_workflow_asset" / "workflows" / state.workflow_id
    )
    request = json.loads((workflow_root / "request.json").read_text(encoding="utf-8"))
    plan = json.loads((workflow_root / "plan.json").read_text(encoding="utf-8"))
    steps = {item["step_id"]: item for item in plan["steps"]}
    assert request["include_destination_handoff"] is True
    assert plan["terminal_step_id"] == "destination.handoff"
    assert steps["destination.handoff"]["depends_on"] == ["portable.final_approval"]
    assert steps["destination.handoff"]["tool_name"] == "generate_destination_handoff"
    assert steps["portable.roundtrip"]["outputs"][0]["path"].startswith(
        "optimization/runs/"
    )
    assert "/roundtrip/" in steps["portable.roundtrip"]["outputs"][0]["path"]
    assert all(
        item["path"].startswith("exports/destination_handoffs/")
        for item in steps["destination.handoff"]["outputs"]
    )


def test_destination_handoff_rejects_obj_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a handoff request for legacy OBJ before persisting a workflow."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    create_job("obj_handoff_asset", primary, "concept", [])
    with pytest.raises(ValueError, match="GLB and FBX"):
        plan_workflow(
            "Prepare a legacy OBJ handoff.",
            job_id="obj_handoff_asset",
            intent="portable_package",
            profile_id="obj_legacy",
            include_destination_handoff=True,
        )


@pytest.mark.parametrize(
    ("intent", "request_text", "report_id", "approval_id"),
    [
        (
            "material_authoring",
            "Author materials and shaders.",
            "material.report",
            "material.approval",
        ),
        (
            "visual_qa",
            "Run direct reference visual QA.",
            "qa.report",
            "qa.review",
        ),
    ],
)
def test_human_review_gates_require_a_pdf_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    intent: str,
    request_text: str,
    report_id: str,
    approval_id: str,
) -> None:
    """Material and QA approvals depend on a PDF plus canonical JSON evidence."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / f"{intent}.png")
    job_id = f"{intent}_asset"
    create_job(job_id, primary, "concept", [])
    state = plan_workflow(
        request_text,
        job_id=job_id,
        intent=intent,
    )
    workflow_root = workspace / job_id / "workflows" / state.workflow_id
    plan = json.loads((workflow_root / "plan.json").read_text(encoding="utf-8"))
    step_ids = [item["step_id"] for item in plan["steps"]]
    assert step_ids.index(report_id) < step_ids.index(approval_id)
    approval = next(item for item in plan["steps"] if item["step_id"] == approval_id)
    assert approval["depends_on"] == [report_id]
    if intent == "material_authoring":
        scaffold = next(
            item for item in plan["steps"] if item["step_id"] == "material.scaffold"
        )
        authored = next(
            item for item in plan["steps"] if item["step_id"] == "material.author"
        )
        assert "material.promote" in step_ids
        assert scaffold["outputs"][0]["path"] != authored["outputs"][0]["path"]
        assert authored["depends_on"] == ["material.scaffold"]
    else:
        qa_run = next(item for item in plan["steps"] if item["step_id"] == "qa.run")
        assert qa_run["outputs"][0]["path"].startswith("qa/runs/")
        assert qa_run["outputs"][0]["path"] != "qa/latest.json"


def test_ambiguous_existing_request_requires_explicit_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Multiple existing-job intents fail closed instead of choosing a broad workflow."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    create_job("ambiguous_asset", primary, "concept", [])
    with pytest.raises(ValueError, match="multiple existing-job intents"):
        plan_workflow(
            "셰이더를 수정하고 QA 후 FBX로 내보내줘",
            job_id="ambiguous_asset",
        )
    assert not (job_dir("ambiguous_asset") / "workflows" / "latest.json").exists()
