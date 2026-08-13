from __future__ import annotations

import json
import os
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import codex_blender_modeler.orchestration.locks as orchestration_locks
import codex_blender_modeler.orchestration.service as orchestration_service
import codex_blender_modeler.qa.multiview_sanity as multiview_sanity
from codex_blender_modeler.autonomy.service import _policy_gate_exact_output_path
from codex_blender_modeler.optimization.service import initialize_asset_profile
from codex_blender_modeler.orchestration.locks import (
    acquire_workflow_lock,
    release_workflow_lock,
    write_expired_lock_for_test,
)
from codex_blender_modeler.orchestration.models import (
    WorkflowAttempt,
    WorkflowLock,
    WorkflowPlan,
    WorkflowStep,
)
from codex_blender_modeler.orchestration.service import (
    approve_workflow_gate,
    cancel_workflow,
    complete_workflow_step,
    destination_adapters,
    plan_workflow,
    reconcile_workflow,
    resume_workflow,
)
from codex_blender_modeler.qa.multiview_sanity import (
    ASSEMBLY_SANITY_PASS_KINDS,
    ASSEMBLY_SANITY_VIEW_IDS,
    AssemblySanityPlan,
    AssemblySanityRenderManifest,
    AssemblySanityReport,
    GeometryMultiviewVisualReview,
)
from codex_blender_modeler.workspace import create_job, job_dir, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def _write_workflow_lock_fixture(
    root: Path,
    *,
    owner_host: str | None,
    process_id: int,
    expired: bool,
    include_owner_host: bool = True,
) -> WorkflowLock:
    """Write one exact workflow-lock owner fixture for recovery-policy tests."""

    now = datetime.now(UTC)
    receipt = WorkflowLock(
        lock_id="f" * 32,
        workflow_id="wf-lock-owner",
        job_id="lock_asset",
        process_id=process_id,
        owner_host=owner_host,
        acquired_at=now - timedelta(minutes=2),
        expires_at=(now - timedelta(minutes=1) if expired else now + timedelta(minutes=1)),
    )
    payload = receipt.model_dump(mode="json")
    if not include_owner_host:
        payload.pop("owner_host")
    lock_path = root / "workflows" / ".lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return receipt


def _image(path: Path, color: tuple[int, int, int] = (60, 110, 170)) -> Path:
    """Create one small deterministic RGB reference fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 32), color).save(path)
    return path


def _write_interrupted_multiview_attempt(
    workflow_root: Path,
    *,
    workflow_id: str,
    job_id: str,
    step: WorkflowStep,
    input_fingerprint: str,
) -> None:
    """Persist one exact InterruptedAttempt authorizing bounded run recovery."""

    _write_failed_multiview_attempt(
        workflow_root,
        workflow_id=workflow_id,
        job_id=job_id,
        step=step,
        input_fingerprint=input_fingerprint,
        attempt_id="attempt-0001-interrupted",
        error_type="InterruptedAttempt",
        reason_code="host_failure",
    )


def _write_failed_multiview_attempt(
    workflow_root: Path,
    *,
    workflow_id: str,
    job_id: str,
    step: WorkflowStep,
    input_fingerprint: str,
    attempt_id: str = "attempt-0001-host-failure",
    error_type: str = "RuntimeError",
    reason_code: str | None = "host_failure",
) -> None:
    """Persist one exact prior failed host receipt for multi-view retry tests."""

    attempt = WorkflowAttempt(
        attempt_id=attempt_id,
        workflow_id=workflow_id,
        job_id=job_id,
        step_id=step.step_id,
        plan_sha256=sha256_file(workflow_root / "plan.json"),
        input_fingerprint=input_fingerprint,
        status="failed",
        error_type=error_type,
        error_message="fixture prior host failure",
        reason_code=reason_code,  # type: ignore[arg-type]
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    attempt_root = workflow_root / "attempts" / step.step_id
    attempt_root.mkdir(parents=True, exist_ok=True)
    (attempt_root / f"{attempt_id}.json").write_text(
        attempt.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def _workflow_assembly_sanity_plan(job_id: str, run_id: str) -> AssemblySanityPlan:
    """Create one minimal schema-valid workflow-owned five-view plan fixture."""

    directions = {
        "front": (1.0, 0.0, 0.0),
        "right": (0.0, 1.0, 0.0),
        "top": (0.0, 0.0, 1.0),
        "rear": (-1.0, 0.0, 0.0),
        "oblique": (1.0, 1.0, 0.5),
    }
    return AssemblySanityPlan(
        job_id=job_id,
        run_id=run_id,
        scene_spec_path="analysis/scene_spec.json",
        scene_spec_sha256="a" * 64,
        modeling_plan_path="analysis/modeling_plan.json",
        modeling_plan_sha256="b" * 64,
        source_blend_path="blender/scene.blend",
        source_blend_sha256="c" * 64,
        build_fingerprint="d" * 64,
        source_fingerprint="e" * 64,
        review_policy="exterior_geometry_review_v2",
        assembly_frame={
            "root_object_id": "asset.root",
            "longitudinal_axis": "X",
            "lateral_axis": "Y",
            "vertical_axis": "Z",
            "symmetry": "unknown",
            "evidence_status": "inferred",
        },
        target_ids=["asset.root"],
        resolution=(384, 384),
        views=[
            {
                "view_id": view_id,
                "camera_direction_frame": direction,
                "screen_up_role": "longitudinal" if view_id == "top" else "vertical",
                "target_ids": ["asset.root"],
            }
            for view_id, direction in directions.items()
        ],
        created_at="2026-08-04T00:00:00+00:00",
    )


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

    scene_seed = json.loads(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    path = root / "analysis" / "modeling_plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stage"] = "authored"
    payload["objects"] = [
        {
            "id": item["id"],
            "label": item["name"],
            "recommended_geometry": item["geometry"]["kind"],
            "source_ids": ["ref.main"],
            "bbox_norm": [0.1, 0.1, 0.9, 0.9],
            "observed": True,
            "confidence": 0.8,
            "assembly_role": "root" if index == 0 else "free_standing",
            "notes": [],
        }
        for index, item in enumerate(scene_seed["objects"])
    ]
    payload["assembly_consistency_policy"] = "spatial_v1"
    payload["assembly_frame"] = {
        "root_object_id": scene_seed["objects"][0]["id"],
        "longitudinal_axis": "X",
        "lateral_axis": "Y",
        "vertical_axis": "Z",
        "symmetry": "unknown",
        "evidence_status": "inferred",
        "source_ids": [],
        "confidence": 0.5,
        "notes": ["Test-only inferred assembly frame."],
    }
    payload["assembly_relationships"] = []
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


def test_reconcile_noop_preserves_state_and_latest_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Repeated no-op reconciliation preserves timestamps, hashes, bytes, and pointers."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    workflow_root = root / "workflows" / state.workflow_id
    state_path = workflow_root / "state.json"
    latest_path = root / "workflows" / "latest.json"
    state_bytes = state_path.read_bytes()
    latest_bytes = latest_path.read_bytes()
    state_mtime = state_path.stat().st_mtime_ns
    latest_mtime = latest_path.stat().st_mtime_ns
    state_sha256 = sha256_file(state_path)
    updated_at = state.updated_at

    for _index in range(3):
        reconciled = reconcile_workflow("workflow_asset", state.workflow_id)
        assert reconciled.updated_at == updated_at

    assert state_path.read_bytes() == state_bytes
    assert latest_path.read_bytes() == latest_bytes
    assert state_path.stat().st_mtime_ns == state_mtime
    assert latest_path.stat().st_mtime_ns == latest_mtime
    assert sha256_file(state_path) == state_sha256


def test_reconcile_updates_state_only_for_authoritative_evidence_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A changed declared artifact advances updated_at and persisted state bytes."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    state_path = root / "workflows" / state.workflow_id / "state.json"
    latest_path = root / "workflows" / "latest.json"
    state_bytes = state_path.read_bytes()
    latest_bytes = latest_path.read_bytes()
    state_sha256 = sha256_file(state_path)

    _author_modeling_plan(root, state)
    reconciled = reconcile_workflow("workflow_asset", state.workflow_id)

    assert reconciled.updated_at > state.updated_at
    assert state_path.read_bytes() != state_bytes
    assert latest_path.read_bytes() != latest_bytes
    assert sha256_file(state_path) != state_sha256
    modeling = next(
        item for item in reconciled.steps if item.step_id == "geometry.modeling_plan"
    )
    assert modeling.artifacts
    assert modeling.artifacts[0].currency == "superseded"


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
    assert step_ids.index("proxy.validate") < step_ids.index(
        "proxy.geometry_multiview"
    )
    assert step_ids.index("proxy.geometry_multiview") < step_ids.index(
        "proxy.geometry_multiview_visual_review"
    )
    assert step_ids.index("proxy.geometry_multiview_visual_review") < step_ids.index(
        "proxy.report"
    )
    assert step_ids.index("proxy.report") < step_ids.index("geometry.proxy_approval")
    modeling_step = next(
        item for item in plan["steps"] if item["step_id"] == "geometry.modeling_plan"
    )
    assert modeling_step["parameters"]["require_surface_detail_policy"] is True
    assert (
        modeling_step["parameters"]["require_assembly_consistency_policy"] is True
    )
    assert any("surface" in text.lower() for text in modeling_step["instructions"])
    assert any(
        "assembly_consistency_policy=spatial_v1" in text
        for text in modeling_step["instructions"]
    )
    proxy_step = next(
        item for item in plan["steps"] if item["step_id"] == "geometry.proxy_author"
    )
    assert any("parent-local" in text for text in proxy_step["instructions"])
    visual_review = next(
        item
        for item in plan["steps"]
        if item["step_id"] == "proxy.geometry_multiview_visual_review"
    )
    assert visual_review["execution_mode"] == "agent"
    assert visual_review["tool_name"] == "review_geometry_multiview"
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


def test_new_workflow_rejects_legacy_assembly_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Require the spatial-v1 assembly contract on newly planned modeling steps."""

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
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    current = next(
        item for item in state.steps if item.step_id == "geometry.modeling_plan"
    )

    with pytest.raises(RuntimeError, match="assembly_consistency_policy=spatial_v1"):
        complete_workflow_step(
            "workflow_asset",
            state.workflow_id,
            "geometry.modeling_plan",
            input_fingerprint=str(current.input_fingerprint),
            note="Attempted to retain an unbound legacy assembly plan.",
        )


def test_legacy_revision_omits_spatial_only_multiview_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep legacy jobs revisable without failing after canonical mutation."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "legacy_revision.png")
    create_job("legacy_revision_asset", reference, "concept", [])
    legacy_plan = {
        "schema_version": "0.4.0",
        "job_id": "legacy_revision_asset",
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
        "stage": "authored",
        "objects": [
            {
                "id": "asset.root",
                "label": "asset root",
                "scope_role": "primary",
            }
        ],
        "assembly_consistency_policy": "legacy_unbound",
    }
    modeling_plan_path = (
        workspace / "legacy_revision_asset" / "analysis" / "modeling_plan.json"
    )
    modeling_plan_path.write_text(
        json.dumps(legacy_plan, indent=2) + "\n",
        encoding="utf-8",
    )

    state = plan_workflow(
        "Revise the approved exterior proportions.",
        job_id="legacy_revision_asset",
        intent="revise_asset",
        revision_strategy="manual_guarded",
    )
    workflow_root = (
        workspace
        / "legacy_revision_asset"
        / "workflows"
        / state.workflow_id
    )
    plan = json.loads((workflow_root / "plan.json").read_text(encoding="utf-8"))
    step_ids = [item["step_id"] for item in plan["steps"]]
    report = next(item for item in plan["steps"] if item["step_id"] == "revision.report")
    apply_step = next(
        item for item in plan["steps"] if item["step_id"] == "revision.apply"
    )

    assert "revision.geometry_multiview" not in step_ids
    assert "revision.geometry_multiview_visual_review" not in step_ids
    assert "assembly_sanity_run_id" not in report["parameters"]
    assert apply_step["parameters"]["expected_modeling_plan_sha256"] == sha256_file(
        modeling_plan_path
    )
    assert (
        apply_step["parameters"]["expected_assembly_consistency_policy"]
        == "legacy_unbound"
    )
    for item in plan["steps"]:
        if item["step_id"].startswith("revision.") and item["step_id"] not in {
            "revision.author",
            "revision.approval",
        }:
            assert item["parameters"]["expected_modeling_plan_sha256"] == sha256_file(
                modeling_plan_path
            )
            assert (
                item["parameters"]["expected_assembly_consistency_policy"]
                == "legacy_unbound"
            )
    assert any("not applicable" in note for note in plan["notes"])


def test_standard_revision_defaults_to_single_gate_candidate_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Plan isolated before/after evaluation with only one final promotion approval."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "candidate_review.png")
    create_job("candidate_review_asset", reference, "concept", [])
    root = workspace / "candidate_review_asset"
    modeling_plan = {
        "schema_version": "0.4.0",
        "job_id": "candidate_review_asset",
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
        "stage": "authored",
        "objects": [{"id": "asset.root", "label": "root"}],
        "assembly_consistency_policy": "legacy_unbound",
    }
    (root / "analysis" / "modeling_plan.json").write_text(
        json.dumps(modeling_plan, indent=2) + "\n",
        encoding="utf-8",
    )

    state = plan_workflow(
        "Revise the main body proportions and compare before applying.",
        job_id="candidate_review_asset",
        intent="revise_asset",
    )
    workflow_root = root / "workflows" / state.workflow_id
    request = json.loads((workflow_root / "request.json").read_text(encoding="utf-8"))
    plan = json.loads((workflow_root / "plan.json").read_text(encoding="utf-8"))
    steps = {item["step_id"]: item for item in plan["steps"]}

    assert request["revision_strategy"] == "candidate_review"
    assert set(steps) == {
        "revision.author",
        "revision.evaluate",
        "revision.promotion_approval",
        "revision.promote",
    }
    assert steps["revision.author"]["outputs"][0]["path"].startswith(
        f"workflows/{state.workflow_id}/artifacts/r/"
    )
    assert steps["revision.evaluate"]["tool_name"] == "evaluate_candidate_revision"
    assert steps["revision.promotion_approval"]["approval_gate"] == "visual_revision"
    assert steps["revision.promote"]["tool_name"] == "promote_candidate_revision"
    assert "revision.approval" not in steps


def test_spatial_revision_keeps_five_view_geometry_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Schedule the new five-view review for an authored spatial-v1 job."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "spatial_revision.png")
    create_job("spatial_revision_asset", reference, "concept", [])
    modeling_plan = {
        "schema_version": "0.4.0",
        "job_id": "spatial_revision_asset",
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
        "stage": "authored",
        "objects": [
            {
                "id": "asset.root",
                "label": "asset root",
                "scope_role": "primary",
                "assembly_role": "root",
            }
        ],
        "assembly_consistency_policy": "spatial_v1",
        "assembly_frame": {
            "root_object_id": "asset.root",
            "longitudinal_axis": "X",
            "lateral_axis": "Y",
            "vertical_axis": "Z",
            "symmetry": "unknown",
            "evidence_status": "inferred",
        },
        "assembly_relationships": [],
    }
    plan_path = workspace / "spatial_revision_asset" / "analysis" / "modeling_plan.json"
    plan_path.write_text(json.dumps(modeling_plan, indent=2) + "\n", encoding="utf-8")

    state = plan_workflow(
        "Revise the approved exterior proportions.",
        job_id="spatial_revision_asset",
        intent="revise_asset",
        revision_strategy="manual_guarded",
    )
    workflow_root = (
        workspace
        / "spatial_revision_asset"
        / "workflows"
        / state.workflow_id
    )
    plan = json.loads((workflow_root / "plan.json").read_text(encoding="utf-8"))
    step_ids = [item["step_id"] for item in plan["steps"]]
    report = next(item for item in plan["steps"] if item["step_id"] == "revision.report")
    apply_step = next(
        item for item in plan["steps"] if item["step_id"] == "revision.apply"
    )

    assert "revision.geometry_multiview" in step_ids
    assert "revision.geometry_multiview_visual_review" in step_ids
    assert report["parameters"]["assembly_sanity_run_id"].endswith(
        "-revision-geometry"
    )
    assert apply_step["parameters"]["expected_modeling_plan_sha256"] == sha256_file(
        plan_path
    )
    assert (
        apply_step["parameters"]["expected_assembly_consistency_policy"] == "spatial_v1"
    )
    for item in plan["steps"]:
        if item["step_id"].startswith("revision.") and item["step_id"] not in {
            "revision.author",
            "revision.approval",
        }:
            assert item["parameters"]["expected_modeling_plan_sha256"] == sha256_file(
                plan_path
            )
            assert (
                item["parameters"]["expected_assembly_consistency_policy"]
                == "spatial_v1"
            )


def test_revision_planning_rejects_missing_modeling_plan_without_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fail before persisting a revision workflow when its ModelingPlan is absent."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "missing_plan_revision.png")
    create_job("missing_plan_revision", reference, "concept", [])
    root = workspace / "missing_plan_revision"

    with pytest.raises(FileNotFoundError, match="modeling_plan.json"):
        plan_workflow(
            "Revise this asset.",
            job_id="missing_plan_revision",
            intent="revise_asset",
        )

    assert not (root / "workflows" / "latest.json").exists()
    assert not any((root / "workflows").glob("wf-*"))


def test_revision_apply_binding_rejects_changed_modeling_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Detect ModelingPlan drift before the guarded revision can change SceneSpec."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "bound_revision.png")
    create_job("bound_revision_asset", reference, "concept", [])
    root = workspace / "bound_revision_asset"
    modeling_plan_path = root / "analysis" / "modeling_plan.json"
    payload = {
        "schema_version": "0.4.0",
        "job_id": "bound_revision_asset",
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
        "stage": "authored",
        "objects": [{"id": "asset.root", "label": "root"}],
        "assembly_consistency_policy": "legacy_unbound",
    }
    modeling_plan_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    expected_hash = sha256_file(modeling_plan_path)
    step = WorkflowStep(
        step_id="revision.apply",
        title="Apply guarded revision",
        phase="geometry",
        execution_mode="host",
        tool_name="apply_revision_plan",
        parameters={
            "expected_modeling_plan_sha256": expected_hash,
            "expected_assembly_consistency_policy": "legacy_unbound",
        },
    )
    orchestration_service._verify_revision_modeling_plan_binding(root, step)

    payload["global_notes"] = ["changed after immutable workflow planning"]
    modeling_plan_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        orchestration_service.OrchestrationArtifactConflict,
        match="ModelingPlan hash changed",
    ):
        orchestration_service._verify_revision_modeling_plan_binding(root, step)


def test_revision_downstream_host_and_agent_steps_reject_modeling_plan_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject post-apply host work and agent completion after ModelingPlan drift."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "downstream_bound_revision.png")
    create_job("downstream_bound_revision", reference, "concept", [])
    root = workspace / "downstream_bound_revision"
    modeling_plan_path = root / "analysis" / "modeling_plan.json"
    payload = {
        "schema_version": "0.4.0",
        "job_id": "downstream_bound_revision",
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
        "stage": "authored",
        "objects": [{"id": "asset.root", "label": "root"}],
        "assembly_consistency_policy": "legacy_unbound",
    }
    modeling_plan_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    binding = {
        "expected_modeling_plan_sha256": sha256_file(modeling_plan_path),
        "expected_assembly_consistency_policy": "legacy_unbound",
    }
    payload["global_notes"] = ["changed after revision.apply"]
    modeling_plan_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    request = SimpleNamespace(
        job_id="downstream_bound_revision",
        workflow_id="wf-downstream-binding",
    )
    host_step = WorkflowStep(
        step_id="revision.build",
        title="Build revised asset",
        phase="geometry",
        execution_mode="host",
        tool_name="build_scene",
        parameters=binding,
    )
    agent_step = WorkflowStep(
        step_id="revision.geometry_multiview_visual_review",
        title="Review revised asset",
        phase="geometry",
        execution_mode="agent",
        tool_name="review_geometry_multiview",
        parameters=binding,
    )

    with pytest.raises(
        orchestration_service.OrchestrationArtifactConflict,
        match="ModelingPlan hash changed",
    ):
        orchestration_service._execute_host_tool(
            root,
            root / "workflows" / request.workflow_id,
            request,
            host_step,
            input_fingerprint="a" * 64,
        )
    with pytest.raises(
        orchestration_service.OrchestrationArtifactConflict,
        match="ModelingPlan hash changed",
    ):
        orchestration_service._validate_agent_completion_semantics(
            root,
            agent_step,
            request,
        )


def test_revision_step_fingerprint_tracks_current_modeling_plan_only_when_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Make new revision receipts stale on plan drift without changing legacy fingerprints."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "fingerprint_revision.png")
    create_job("fingerprint_revision_asset", reference, "concept", [])
    root = workspace / "fingerprint_revision_asset"
    modeling_plan_path = root / "analysis" / "modeling_plan.json"
    payload = {
        "schema_version": "0.4.0",
        "job_id": "fingerprint_revision_asset",
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
        "stage": "authored",
        "objects": [{"id": "asset.root", "label": "root"}],
        "assembly_consistency_policy": "legacy_unbound",
    }
    modeling_plan_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    planned = plan_workflow(
        "Revise the exterior proportions.",
        job_id="fingerprint_revision_asset",
        intent="revise_asset",
        revision_strategy="manual_guarded",
    )
    _root, _workflow_root, request, plan, state = (
        orchestration_service._load_workflow(
            "fingerprint_revision_asset",
            planned.workflow_id,
        )
    )
    bound_step = next(item for item in plan.steps if item.step_id == "revision.build")
    legacy_step = bound_step.model_copy(update={"parameters": {}})
    states = {item.step_id: item for item in state.steps}
    bound_before = orchestration_service._step_input_fingerprint(
        plan,
        request,
        bound_step,
        states,
    )
    legacy_before = orchestration_service._step_input_fingerprint(
        plan,
        request,
        legacy_step,
        states,
    )

    payload["global_notes"] = ["changed after one completion receipt"]
    modeling_plan_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    assert bound_before != orchestration_service._step_input_fingerprint(
        plan,
        request,
        bound_step,
        states,
    )
    assert legacy_before == orchestration_service._step_input_fingerprint(
        plan,
        request,
        legacy_step,
        states,
    )


def test_revision_host_postcheck_rejects_mid_execution_modeling_plan_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fail one host attempt before snapshots when its bound plan changes mid-call."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "midcall_revision.png")
    create_job("midcall_revision_asset", reference, "concept", [])
    root = workspace / "midcall_revision_asset"
    modeling_plan_path = root / "analysis" / "modeling_plan.json"
    payload = {
        "schema_version": "0.4.0",
        "job_id": "midcall_revision_asset",
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
        "stage": "authored",
        "objects": [{"id": "asset.root", "label": "root"}],
        "assembly_consistency_policy": "legacy_unbound",
    }
    modeling_plan_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    planned = plan_workflow(
        "Revise the exterior proportions.",
        job_id="midcall_revision_asset",
        intent="revise_asset",
        revision_strategy="manual_guarded",
    )
    _root, workflow_root, request, plan, state = orchestration_service._load_workflow(
        "midcall_revision_asset",
        planned.workflow_id,
    )
    step = next(item for item in plan.steps if item.step_id == "revision.build")
    states = {item.step_id: item for item in state.steps}
    input_fingerprint = orchestration_service._step_input_fingerprint(
        plan,
        request,
        step,
        states,
    )
    synthetic_steps = [
        item.model_copy(
            update={
                "status": "ready",
                "input_fingerprint": input_fingerprint,
            }
        )
        if item.step_id == step.step_id
        else item
        for item in state.steps
    ]
    synthetic_state = state.model_copy(update={"steps": synthetic_steps})

    def mutate_plan(*_args: object, **_kwargs: object) -> None:
        """Simulate an external plan change while the host tool is executing."""

        payload["global_notes"] = ["changed during host execution"]
        modeling_plan_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    def accept_dependency_fixture(*_args: object, **_kwargs: object) -> None:
        """Bypass unrelated predecessor snapshots in this post-check unit fixture."""

        return None

    monkeypatch.setattr(
        orchestration_service,
        "_verify_dependency_sources",
        accept_dependency_fixture,
    )
    monkeypatch.setattr(orchestration_service, "_execute_host_tool", mutate_plan)
    with pytest.raises(
        orchestration_service.OrchestrationArtifactConflict,
        match="ModelingPlan hash changed",
    ):
        orchestration_service._execute_ready_host_step(
            root,
            workflow_root,
            request,
            plan,
            synthetic_state,
            step,
        )

    attempt_path = next((workflow_root / "attempts" / step.step_id).glob("*.json"))
    attempt = WorkflowAttempt.model_validate_json(
        attempt_path.read_text(encoding="utf-8")
    )
    assert attempt.status == "failed"
    assert attempt.reason_code == "orchestration_artifact_conflict"
    assert attempt.error_type == "OrchestrationArtifactConflict"
    assert all(not (root / output.path).exists() for output in step.outputs)


def test_scene_completion_rejects_spatial_plan_object_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fail closed when SceneSpec drops an ID from the authored assembly contract."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    state = _complete_modeling_plan(root, state)
    seed = json.loads(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    seed["job_id"] = "workflow_asset"
    seed["objects"] = seed["objects"][:-1]
    (root / "analysis" / "scene_spec.json").write_text(
        json.dumps(seed, indent=2) + "\n",
        encoding="utf-8",
    )
    current = next(
        item for item in state.steps if item.step_id == "geometry.proxy_author"
    )

    with pytest.raises((RuntimeError, ValueError), match="[Aa]ssembly consistency"):
        complete_workflow_step(
            "workflow_asset",
            state.workflow_id,
            "geometry.proxy_author",
            input_fingerprint=str(current.input_fingerprint),
            note="Attempted to omit one assembly-contract object.",
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
    assert step_ids.index("background_geometry.validate") < step_ids.index(
        "background_geometry.geometry_multiview"
    )
    assert step_ids.index("background_geometry.geometry_multiview") < step_ids.index(
        "background_geometry.geometry_multiview_visual_review"
    )
    assert step_ids.index(
        "background_geometry.geometry_multiview_visual_review"
    ) < step_ids.index("background_geometry.report")
    assert "geometry.proxy_author" not in step_ids
    assert "geometry.detail_author" not in step_ids
    background_modeling = next(
        item for item in steps if item["step_id"] == "geometry.modeling_plan"
    )
    assert (
        background_modeling["parameters"]["require_assembly_consistency_policy"]
        is True
    )
    assert any(
        "one side or oblique image" in instruction
        for instruction in background_modeling["instructions"]
    )
    background_author = next(
        item for item in steps if item["step_id"] == "geometry.background_author"
    )
    assert any("parent-local" in item for item in background_author["instructions"])
    geometry_review = next(
        item
        for item in steps
        if item["step_id"] == "background_geometry.geometry_multiview"
    )
    assert geometry_review["tool_name"] == "run_geometry_multiview_review"
    assert geometry_review["parameters"]["review_policy"] == (
        "exterior_geometry_review_v2"
    )
    assert geometry_review["parameters"]["resolution"] == 384
    visual_review = next(
        item
        for item in steps
        if item["step_id"] == "background_geometry.geometry_multiview_visual_review"
    )
    assert visual_review["tool_name"] == "review_geometry_multiview"
    assert visual_review["depends_on"] == [
        "background_geometry.geometry_multiview"
    ]
    background_report = next(
        item for item in steps if item["step_id"] == "background_geometry.report"
    )
    assert background_report["depends_on"] == [
        "background_geometry.geometry_multiview_visual_review"
    ]
    assert background_report["parameters"]["assembly_sanity_run_id"] == (
        geometry_review["parameters"]["run_id"]
    )
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


def _write_fake_geometry_multiview_outputs(root: Path, step: WorkflowStep) -> None:
    """Write schema-valid run-owned outputs for orchestration-only unit tests."""

    run_id = str(step.parameters["run_id"])
    resolution = int(step.parameters.get("resolution", 384))
    run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    modeling_plan = json.loads(
        (root / "analysis" / "modeling_plan.json").read_text(encoding="utf-8")
    )
    root_id = modeling_plan["assembly_frame"]["root_object_id"]
    directions = {
        "front": (1.0, 0.0, 0.0),
        "right": (0.0, 1.0, 0.0),
        "top": (0.0, 0.0, 1.0),
        "rear": (-1.0, 0.0, 0.0),
        "oblique": (1.0, 1.0, 0.5),
    }
    plan = AssemblySanityPlan(
        job_id="workflow_asset",
        run_id=run_id,
        scene_spec_path="analysis/scene_spec.json",
        scene_spec_sha256=sha256_file(root / "analysis" / "scene_spec.json"),
        modeling_plan_path="analysis/modeling_plan.json",
        modeling_plan_sha256=sha256_file(root / "analysis" / "modeling_plan.json"),
        source_blend_path="blender/scene.blend",
        source_blend_sha256=sha256_file(root / "blender" / "scene.blend"),
        build_fingerprint="a" * 64,
        source_fingerprint="b" * 64,
        review_policy="exterior_geometry_review_v2",
        assembly_frame=modeling_plan["assembly_frame"],
        target_ids=[root_id],
        resolution=(resolution, resolution),
        views=[
            {
                "view_id": view_id,
                "camera_direction_frame": directions[view_id],
                "screen_up_role": "longitudinal" if view_id == "top" else "vertical",
                "target_ids": [root_id],
            }
            for view_id in ASSEMBLY_SANITY_VIEW_IDS
        ],
        created_at="2026-08-04T00:00:00+00:00",
    )
    plan_path = run_root / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    rendered_views = []
    for view_id in ASSEMBLY_SANITY_VIEW_IDS:
        passes = []
        for kind in ASSEMBLY_SANITY_PASS_KINDS:
            path = run_root / "views" / view_id / f"{kind}.png"
            _image(path, (255, 0, 0) if kind == "object_id" else (60, 110, 170))
            passes.append(
                {
                    "kind": kind,
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha256_file(path),
                    "width": resolution,
                    "height": resolution,
                    "encoding": "png-rgb8",
                }
            )
        rendered_views.append(
            {
                "view_id": view_id,
                "camera": {
                    "view_id": view_id,
                    "camera_direction_frame": [
                        round(float(value), 9) for value in directions[view_id]
                    ],
                    "screen_up_role": (
                        "longitudinal" if view_id == "top" else "vertical"
                    ),
                    "type": "PERSP",
                    "location": [3.0, 3.0, 3.0],
                    "rotation_deg": [45.0, 0.0, 135.0],
                    "target": [0.0, 0.0, 0.0],
                    "lens_mm": 50.0,
                    "clip_start": 0.01,
                    "clip_end": 100.0,
                },
                "target_ids": [root_id],
                "passes": passes,
            }
        )
    manifest = AssemblySanityRenderManifest(
        job_id="workflow_asset",
        run_id=run_id,
        plan_sha256=sha256_file(plan_path),
        scene_spec_sha256=plan.scene_spec_sha256,
        modeling_plan_sha256=plan.modeling_plan_sha256,
        source_blend_path=plan.source_blend_path,
        source_blend_sha256=plan.source_blend_sha256,
        build_fingerprint=plan.build_fingerprint,
        blender_version="5.0.1",
        render_engine="BLENDER_EEVEE",
        render_device="CPU",
        resolution=plan.resolution,
        object_id_colors={root_id: "#ff0000"},
        assembly_frame_bounds={"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
        assembly_evaluation={"checks": []},
        views=rendered_views,
    )
    manifest_path = run_root / "render_manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    coverage, findings = multiview_sanity._coverage_and_findings(root, plan, manifest)
    report = AssemblySanityReport(
        job_id="workflow_asset",
        run_id=run_id,
        plan_sha256=sha256_file(plan_path),
        render_manifest_sha256=sha256_file(manifest_path),
        scene_spec_sha256=plan.scene_spec_sha256,
        modeling_plan_sha256=plan.modeling_plan_sha256,
        source_blend_sha256=plan.source_blend_sha256,
        build_fingerprint=plan.build_fingerprint,
        review_policy="exterior_geometry_review_v2",
        structural_status="passed",
        reference_comparison_note=multiview_sanity.ASSEMBLY_SANITY_REFERENCE_NOTE,
        target_ids=[root_id],
        visible_target_ids=[root_id],
        unseen_target_ids=[],
        semantic_visibility_fraction=1.0,
        view_coverage=coverage,
        assembly_evaluation={"checks": []},
        findings=findings,
        geometry_review={
            "outcome": "structurally_consistent",
            "v04_reentry": "not_indicated",
            "redesign_assessment": "not_indicated",
        },
        generated_at="2026-08-04T00:00:00+00:00",
    )
    (run_root / "report.json").write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def _complete_fake_geometry_visual_review(
    root: Path,
    state,
    monkeypatch: pytest.MonkeyPatch,
    *,
    prefix: str,
):
    """Write and complete one exact agent visual-review step for orchestration tests."""

    step_id = f"{prefix}.geometry_multiview_visual_review"
    current = next(item for item in state.steps if item.step_id == step_id)
    plan = json.loads(
        (root / "workflows" / state.workflow_id / "plan.json").read_text(encoding="utf-8")
    )
    step = next(item for item in plan["steps"] if item["step_id"] == step_id)
    run_id = str(step["parameters"]["run_id"])
    run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
    review = GeometryMultiviewVisualReview(
        job_id="workflow_asset",
        run_id=run_id,
        plan_sha256=sha256_file(run_root / "plan.json"),
        render_manifest_sha256=sha256_file(run_root / "render_manifest.json"),
        structural_report_sha256=sha256_file(run_root / "report.json"),
        reviewed_view_ids=list(ASSEMBLY_SANITY_VIEW_IDS),
        reviewed_pass_kinds=["beauty", "wireframe"],
        outcome="visually_coherent",
        v04_reentry="not_indicated",
        reviewed_at=datetime.now(UTC),
    )
    (run_root / "visual_review.json").write_text(
        review.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        orchestration_service,
        "validate_geometry_multiview_visual_review",
        lambda *_args, **_kwargs: review,
    )
    return complete_workflow_step(
        "workflow_asset",
        state.workflow_id,
        step_id,
        input_fingerprint=str(current.input_fingerprint),
        note="Codex reviewed all five beauty and wireframe views.",
    )


def _advance_proxy_to_report(
    root: Path,
    state,
    monkeypatch: pytest.MonkeyPatch,
):
    """Complete proxy host checks and the new hash-bound five-view agent review."""

    def execute_proxy_steps(
        host_root: Path,
        _workflow_root: Path,
        _request,
        host_step: WorkflowStep,
        *,
        input_fingerprint: str,
    ) -> None:
        """Publish only the fake multiview outputs needed after existing build fixtures."""

        assert input_fingerprint
        if host_step.step_id == "proxy.geometry_multiview":
            _write_fake_geometry_multiview_outputs(host_root, host_step)

    monkeypatch.setattr(
        orchestration_service,
        "_execute_host_tool",
        execute_proxy_steps,
    )
    advanced = resume_workflow(
        "workflow_asset",
        state.workflow_id,
        max_host_steps=5,
    )
    assert advanced.current_step_id == "proxy.geometry_multiview_visual_review"
    reviewed = _complete_fake_geometry_visual_review(
        root,
        advanced,
        monkeypatch,
        prefix="proxy",
    )
    assert reviewed.current_step_id == "proxy.report"
    return reviewed


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
    state = _advance_proxy_to_report(root, state, monkeypatch)
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
    workflow_plan = json.loads(
        (
            root / "workflows" / state.workflow_id / "plan.json"
        ).read_text(encoding="utf-8")
    )
    detail_plan_step = next(
        item
        for item in workflow_plan["steps"]
        if item["step_id"] == "geometry.detail_author"
    )
    assert any(
        "assembly relationships" in instruction
        for instruction in detail_plan_step["instructions"]
    )
    assert any(
        "parent-local" in instruction
        for instruction in detail_plan_step["instructions"]
    )
    step_ids = [item["step_id"] for item in workflow_plan["steps"]]
    assert step_ids.index("detail.validate") < step_ids.index(
        "detail.geometry_multiview"
    )
    assert step_ids.index("detail.geometry_multiview") < step_ids.index(
        "detail.geometry_multiview_visual_review"
    )
    assert step_ids.index("detail.geometry_multiview_visual_review") < step_ids.index(
        "detail.report"
    )
    detail_review = next(
        item
        for item in workflow_plan["steps"]
        if item["step_id"] == "detail.geometry_multiview"
    )
    detail_report = next(
        item for item in workflow_plan["steps"] if item["step_id"] == "detail.report"
    )
    assert detail_report["parameters"]["assembly_sanity_run_id"] == (
        detail_review["parameters"]["run_id"]
    )
    assert detail_report["depends_on"] == [
        "detail.geometry_multiview_visual_review"
    ]
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
    state = _advance_proxy_to_report(root, state, monkeypatch)
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
    assert first.owner_host == socket.gethostname()
    with pytest.raises(RuntimeError, match="Another workflow"):
        acquire_workflow_lock(root, "lock_asset", "wf-second")
    release_workflow_lock(root, first)
    stale = write_expired_lock_for_test(root, "lock_asset", "wf-expired")
    recovered = acquire_workflow_lock(root, "lock_asset", "wf-recovered")
    archived = list((root / "workflows" / "stale_locks").glob("*.json"))
    assert len(archived) == 1
    assert WorkflowLock.model_validate_json(
        archived[0].read_text(encoding="utf-8")
    ).lock_id == stale.lock_id
    release_workflow_lock(root, recovered)


@pytest.mark.parametrize("process_state", ["alive", "unknown"])
def test_expired_local_live_or_unknown_lock_is_never_recovered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    process_state: str,
) -> None:
    """Keep an expired local lock when its owner is alive or cannot be classified."""

    root = tmp_path / "job"
    root.mkdir()
    existing = _write_workflow_lock_fixture(
        root,
        owner_host=socket.gethostname(),
        process_id=4242,
        expired=True,
    )

    def classify_process(_process_id: int) -> str:
        """Return the parameterized local-process state for this lock fixture."""

        return process_state

    monkeypatch.setattr(orchestration_locks, "_local_process_state", classify_process)
    with pytest.raises(RuntimeError, match="live, remote, or unknown"):
        acquire_workflow_lock(root, "lock_asset", "wf-contender")

    current = WorkflowLock.model_validate_json(
        (root / "workflows" / ".lock.json").read_text(encoding="utf-8")
    )
    assert current.lock_id == existing.lock_id
    assert not (root / "workflows" / "stale_locks").exists()


@pytest.mark.parametrize(
    ("owner_host", "include_owner_host"),
    [("remote-owner.invalid", True), (None, False)],
)
def test_expired_remote_or_legacy_unknown_lock_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    owner_host: str | None,
    include_owner_host: bool,
) -> None:
    """Refuse automatic recovery when lock ownership is remote or lacks legacy host data."""

    root = tmp_path / "job"
    root.mkdir()
    existing = _write_workflow_lock_fixture(
        root,
        owner_host=owner_host,
        process_id=4242,
        expired=True,
        include_owner_host=include_owner_host,
    )

    def reject_local_probe(_process_id: int) -> str:
        """Fail if remote or unknown ownership reaches a local PID probe."""

        raise AssertionError("remote and unknown owners must not be probed locally")

    monkeypatch.setattr(orchestration_locks, "_local_process_state", reject_local_probe)
    with pytest.raises(RuntimeError, match="live, remote, or unknown"):
        acquire_workflow_lock(root, "lock_asset", "wf-contender")

    current = WorkflowLock.model_validate_json(
        (root / "workflows" / ".lock.json").read_text(encoding="utf-8")
    )
    assert current.lock_id == existing.lock_id
    assert not (root / "workflows" / "stale_locks").exists()


def test_unexpired_local_dead_lock_waits_for_ttl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve the V0.8 TTL boundary even when the local owner is already dead."""

    root = tmp_path / "job"
    root.mkdir()
    existing = _write_workflow_lock_fixture(
        root,
        owner_host=socket.gethostname(),
        process_id=4242,
        expired=False,
    )

    def dead_process(_process_id: int) -> str:
        """Classify the fixture owner as conclusively dead."""

        return "dead"

    monkeypatch.setattr(orchestration_locks, "_local_process_state", dead_process)
    with pytest.raises(RuntimeError, match="unexpired"):
        acquire_workflow_lock(root, "lock_asset", "wf-contender")

    current = WorkflowLock.model_validate_json(
        (root / "workflows" / ".lock.json").read_text(encoding="utf-8")
    )
    assert current.lock_id == existing.lock_id
    assert not (root / "workflows" / "stale_locks").exists()


def test_unreadable_lock_is_not_archived(tmp_path: Path) -> None:
    """Leave malformed lock evidence untouched for explicit manual recovery."""

    root = tmp_path / "job"
    lock_path = root / "workflows" / ".lock.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unreadable"):
        acquire_workflow_lock(root, "lock_asset", "wf-contender")

    assert lock_path.read_text(encoding="utf-8") == "{not-json\n"
    assert not (root / "workflows" / "stale_locks").exists()


def test_lock_transition_guard_rejects_a_concurrent_recovery(tmp_path: Path) -> None:
    """Serialize stale recovery so a contender cannot archive a newly acquired lock."""

    lock_path = tmp_path / "job" / "workflows" / ".lock.json"
    lock_path.parent.mkdir(parents=True)
    with orchestration_locks._lock_transition_guard(lock_path):
        with pytest.raises(RuntimeError, match="recovery is already in progress"):
            with orchestration_locks._lock_transition_guard(lock_path):
                raise AssertionError("a second transition guard must not be entered")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OpenProcess regression")
def test_windows_process_liveness_uses_open_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Classify the current Windows PID without invoking signal-based os.kill."""

    def reject_os_kill(_process_id: int, _signal: int) -> None:
        """Fail if the Windows liveness path attempts signal-based probing."""

        raise AssertionError("Windows PID liveness must use OpenProcess")

    monkeypatch.setattr(orchestration_locks.os, "kill", reject_os_kill)
    assert orchestration_locks._local_process_state(os.getpid()) == "alive"


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


def test_visual_diagnostics_host_step_forwards_exact_plan_parameters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Forward only the immutable workflow diagnostic parameters to the QA service."""

    captured: dict[str, object] = {}

    def run_diagnostics(job_id: str, qa_run_id: str, **kwargs: object) -> None:
        """Capture one diagnostic dispatch without creating Blender artifacts."""

        captured.update(job_id=job_id, qa_run_id=qa_run_id, **kwargs)

    monkeypatch.setattr(
        orchestration_service,
        "run_job_visual_diagnostics",
        run_diagnostics,
    )
    request = SimpleNamespace(job_id="diagnostic_asset")
    step = SimpleNamespace(
        tool_name="run_visual_diagnostics",
        parameters={
            "qa_run_id": "qa-run-001",
            "diagnostic_id": "camera-geometry-v1",
            "max_camera_probes": 3,
            "include_multiview_sanity": False,
        },
    )

    orchestration_service._execute_host_tool(
        tmp_path,
        tmp_path / "workflow",
        request,
        step,
        input_fingerprint="a" * 64,
    )

    assert captured == {
        "job_id": "diagnostic_asset",
        "qa_run_id": "qa-run-001",
        "diagnostic_id": "camera-geometry-v1",
        "max_camera_probes": 3,
        "include_multiview_sanity": False,
    }


def test_geometry_multiview_host_step_forwards_exact_workflow_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dispatch one fresh workflow-owned five-view review to exact planned paths."""

    root = tmp_path / "geometry_review_asset"
    workflow_root = root / "workflows" / "wf-geometry-review"
    workflow_root.mkdir(parents=True)
    run_id = "v08-geometry-review-detail-geometry"
    run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
    captured: dict[str, object] = {}

    def plan_review(job_id: str, **kwargs: object) -> dict[str, object]:
        """Capture exact plan parameters without invoking Blender."""

        captured.update(plan_job_id=job_id, **kwargs)
        return {
            "plan": str(run_root / "plan.json"),
            "plan_sha256": "a" * 64,
            "review_policy": "exterior_geometry_review_v2",
        }

    def run_review(job_id: str, selected_run_id: str, **kwargs: object) -> dict[str, object]:
        """Capture exact run parameters and return workflow-owned output paths."""

        captured.update(
            run_job_id=job_id,
            selected_run_id=selected_run_id,
            **kwargs,
        )
        return {
            "render_manifest": str(run_root / "render_manifest.json"),
            "report": str(run_root / "report.json"),
            "review_policy": "exterior_geometry_review_v2",
        }

    monkeypatch.setattr(
        orchestration_service,
        "plan_job_assembly_multiview_sanity",
        plan_review,
    )
    monkeypatch.setattr(
        orchestration_service,
        "run_job_assembly_multiview_sanity",
        run_review,
    )
    request = SimpleNamespace(
        job_id="geometry_review_asset",
        workflow_id="wf-geometry-review",
    )
    step = SimpleNamespace(
        step_id="detail.geometry_multiview",
        tool_name="run_geometry_multiview_review",
        parameters={
            "run_id": run_id,
            "resolution": 384,
            "review_policy": "exterior_geometry_review_v2",
        },
    )

    orchestration_service._execute_host_tool(
        root,
        workflow_root,
        request,
        step,
        input_fingerprint="b" * 64,
    )

    assert captured == {
        "plan_job_id": "geometry_review_asset",
        "run_id": run_id,
        "resolution": 384,
        "run_job_id": "geometry_review_asset",
        "selected_run_id": run_id,
        "plan_sha256": "a" * 64,
    }


def test_geometry_multiview_host_rejects_unowned_preexisting_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a pre-existing plan when no exact prior host attempt can own it."""

    root = tmp_path / "unowned_geometry_review_asset"
    workflow_id = "wf-unowned-geometry-review"
    workflow_root = root / "workflows" / workflow_id
    workflow_root.mkdir(parents=True)
    (workflow_root / "plan.json").write_text("{}\n", encoding="utf-8")
    run_id = "v08-unowned-geometry-review"
    run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
    run_root.mkdir(parents=True)
    (run_root / "plan.json").write_text(
        _workflow_assembly_sanity_plan(
            "unowned_geometry_review_asset",
            run_id,
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    step = WorkflowStep(
        step_id="detail.geometry_multiview",
        title="Review geometry",
        phase="geometry",
        execution_mode="host",
        tool_name="run_geometry_multiview_review",
        parameters={
            "run_id": run_id,
            "resolution": 384,
            "review_policy": "exterior_geometry_review_v2",
        },
    )
    called = False

    def run(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Fail the test if an unowned plan reaches the renderer."""

        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(
        orchestration_service,
        "run_job_assembly_multiview_sanity",
        run,
    )
    request = SimpleNamespace(
        job_id="unowned_geometry_review_asset",
        workflow_id=workflow_id,
    )

    with pytest.raises(
        orchestration_service.OrchestrationArtifactConflict,
        match="pre-existing geometry multi-view plan has no exact prior",
    ):
        orchestration_service._execute_host_tool(
            root,
            workflow_root,
            request,
            step,
            input_fingerprint="1" * 64,
        )

    assert called is False


@pytest.mark.parametrize("reason_code", ["host_failure", None])
def test_geometry_multiview_host_retries_plan_after_exact_host_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reason_code: str | None,
) -> None:
    """Reuse a plan after exact current or legacy host-failure ownership evidence."""

    root = tmp_path / "failed_geometry_review_asset"
    workflow_id = "wf-failed-geometry-review"
    workflow_root = root / "workflows" / workflow_id
    workflow_root.mkdir(parents=True)
    (workflow_root / "plan.json").write_text("{}\n", encoding="utf-8")
    run_id = "v08-failed-geometry-review"
    run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
    run_root.mkdir(parents=True)
    plan_path = run_root / "plan.json"
    plan_path.write_text(
        _workflow_assembly_sanity_plan(
            "failed_geometry_review_asset",
            run_id,
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    input_fingerprint = "2" * 64
    step = WorkflowStep(
        step_id="detail.geometry_multiview",
        title="Review geometry",
        phase="geometry",
        execution_mode="host",
        tool_name="run_geometry_multiview_review",
        parameters={
            "run_id": run_id,
            "resolution": 384,
            "review_policy": "exterior_geometry_review_v2",
        },
    )
    _write_failed_multiview_attempt(
        workflow_root,
        workflow_id=workflow_id,
        job_id="failed_geometry_review_asset",
        step=step,
        input_fingerprint=input_fingerprint,
        reason_code=reason_code,
    )
    calls: list[str] = []

    def run(job_id: str, selected_run_id: str, **kwargs: object) -> dict[str, object]:
        """Record reuse of the exact prior plan during an explicit host retry."""

        calls.append("run")
        assert job_id == "failed_geometry_review_asset"
        assert selected_run_id == run_id
        assert kwargs == {"plan_sha256": sha256_file(plan_path)}
        return {
            "render_manifest": str(run_root / "render_manifest.json"),
            "report": str(run_root / "report.json"),
            "review_policy": "exterior_geometry_review_v2",
        }

    monkeypatch.setattr(
        orchestration_service,
        "run_job_assembly_multiview_sanity",
        run,
    )
    request = SimpleNamespace(
        job_id="failed_geometry_review_asset",
        workflow_id=workflow_id,
    )

    orchestration_service._execute_host_tool(
        root,
        workflow_root,
        request,
        step,
        input_fingerprint=input_fingerprint,
    )

    assert calls == ["run"]


@pytest.mark.parametrize(
    ("case_id", "receipt_input_fingerprint", "error_type", "reason_code"),
    [
        ("mismatch", "3" * 64, "RuntimeError", "host_failure"),
        (
            "conflict",
            "4" * 64,
            "OrchestrationArtifactConflict",
            "orchestration_artifact_conflict",
        ),
        ("legacy-conflict", "4" * 64, "OrchestrationArtifactConflict", None),
    ],
)
def test_geometry_multiview_host_rejects_inexact_or_conflict_receipt(
    tmp_path: Path,
    case_id: str,
    receipt_input_fingerprint: str,
    error_type: str,
    reason_code: str | None,
) -> None:
    """Reject mismatched or conflict-only receipts as proof of run ownership."""

    root = tmp_path / f"rejected_geometry_review_{case_id}"
    workflow_id = f"wf-rejected-{case_id}"
    workflow_root = root / "workflows" / workflow_id
    workflow_root.mkdir(parents=True)
    (workflow_root / "plan.json").write_text("{}\n", encoding="utf-8")
    run_id = f"v08-rejected-{case_id}"
    run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
    run_root.mkdir(parents=True)
    (run_root / "plan.json").write_text(
        _workflow_assembly_sanity_plan(root.name, run_id).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    step = WorkflowStep(
        step_id="detail.geometry_multiview",
        title="Review geometry",
        phase="geometry",
        execution_mode="host",
        tool_name="run_geometry_multiview_review",
        parameters={
            "run_id": run_id,
            "resolution": 384,
            "review_policy": "exterior_geometry_review_v2",
        },
    )
    current_input_fingerprint = "4" * 64
    _write_failed_multiview_attempt(
        workflow_root,
        workflow_id=workflow_id,
        job_id=root.name,
        step=step,
        input_fingerprint=receipt_input_fingerprint,
        error_type=error_type,
        reason_code=reason_code,
    )
    request = SimpleNamespace(job_id=root.name, workflow_id=workflow_id)

    with pytest.raises(
        orchestration_service.OrchestrationArtifactConflict,
        match="pre-existing geometry multi-view plan has no exact prior",
    ):
        orchestration_service._execute_host_tool(
            root,
            workflow_root,
            request,
            step,
            input_fingerprint=current_input_fingerprint,
        )


@pytest.mark.parametrize(
    ("error_type", "reason_code"),
    [
        ("InterruptedAttempt", "host_failure"),
        ("RuntimeError", "host_failure"),
        ("RuntimeError", None),
    ],
)
def test_geometry_multiview_host_recovers_exact_prior_failed_partial_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error_type: str,
    reason_code: str | None,
) -> None:
    """Recover a partial run owned by exact interrupted, current, or legacy failure."""

    root = tmp_path / "geometry_review_recovery_asset"
    workflow_id = "wf-geometry-review-recovery"
    workflow_root = root / "workflows" / workflow_id
    workflow_root.mkdir(parents=True)
    workflow_plan_path = workflow_root / "plan.json"
    workflow_plan_path.write_text("{}\n", encoding="utf-8")
    run_id = "v08-geometry-review-recovery"
    run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
    run_root.mkdir(parents=True)
    plan = AssemblySanityPlan(
        job_id="geometry_review_recovery_asset",
        run_id=run_id,
        scene_spec_path="analysis/scene_spec.json",
        scene_spec_sha256="a" * 64,
        modeling_plan_path="analysis/modeling_plan.json",
        modeling_plan_sha256="b" * 64,
        source_blend_path="blender/scene.blend",
        source_blend_sha256="c" * 64,
        build_fingerprint="d" * 64,
        source_fingerprint="e" * 64,
        review_policy="exterior_geometry_review_v2",
        assembly_frame={
            "root_object_id": "asset.root",
            "longitudinal_axis": "X",
            "lateral_axis": "Y",
            "vertical_axis": "Z",
            "symmetry": "unknown",
            "evidence_status": "inferred",
        },
        target_ids=["asset.root"],
        resolution=(384, 384),
        views=[
            {
                "view_id": view_id,
                "camera_direction_frame": direction,
                "screen_up_role": "longitudinal" if view_id == "top" else "vertical",
                "target_ids": ["asset.root"],
            }
            for view_id, direction in {
                "front": (1.0, 0.0, 0.0),
                "right": (0.0, 1.0, 0.0),
                "top": (0.0, 0.0, 1.0),
                "rear": (-1.0, 0.0, 0.0),
                "oblique": (1.0, 1.0, 0.5),
            }.items()
        ],
        created_at="2026-08-04T00:00:00+00:00",
    )
    plan_path = run_root / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    _image(run_root / "views" / "front" / "beauty.png")

    input_fingerprint = "f" * 64
    step = WorkflowStep(
        step_id="detail.geometry_multiview",
        title="Review geometry",
        phase="geometry",
        execution_mode="host",
        tool_name="run_geometry_multiview_review",
        parameters={
            "run_id": run_id,
            "resolution": 384,
            "review_policy": "exterior_geometry_review_v2",
        },
    )
    attempt = WorkflowAttempt(
        attempt_id="attempt-0001-interrupted",
        workflow_id=workflow_id,
        job_id="geometry_review_recovery_asset",
        step_id=step.step_id,
        plan_sha256=sha256_file(workflow_plan_path),
        input_fingerprint=input_fingerprint,
        status="failed",
        error_type=error_type,
        error_message="fixture interruption",
        reason_code=reason_code,  # type: ignore[arg-type]
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    attempt_root = workflow_root / "attempts" / step.step_id
    attempt_root.mkdir(parents=True)
    (attempt_root / "attempt-0001-interrupted.json").write_text(
        attempt.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    calls: list[str] = []

    def recover(job_id: str, selected_run_id: str, **kwargs: object) -> dict[str, object]:
        """Record exact recovery authorization without touching a real workspace."""

        calls.append("recover")
        assert job_id == "geometry_review_recovery_asset"
        assert selected_run_id == run_id
        assert kwargs == {
            "plan_sha256": sha256_file(plan_path),
            "recovery_authorized": True,
        }
        return {"status": "recovered"}

    def run(job_id: str, selected_run_id: str, **kwargs: object) -> dict[str, object]:
        """Return exact terminal paths after the authorized recovery."""

        calls.append("run")
        assert job_id == "geometry_review_recovery_asset"
        assert selected_run_id == run_id
        assert kwargs == {"plan_sha256": sha256_file(plan_path)}
        return {
            "render_manifest": str(run_root / "render_manifest.json"),
            "report": str(run_root / "report.json"),
            "review_policy": "exterior_geometry_review_v2",
        }

    monkeypatch.setattr(
        orchestration_service,
        "recover_incomplete_job_assembly_multiview_sanity",
        recover,
    )
    monkeypatch.setattr(
        orchestration_service,
        "run_job_assembly_multiview_sanity",
        run,
    )
    request = SimpleNamespace(
        job_id="geometry_review_recovery_asset",
        workflow_id=workflow_id,
    )

    orchestration_service._execute_host_tool(
        root,
        workflow_root,
        request,
        step,
        input_fingerprint=input_fingerprint,
    )

    assert calls == ["recover", "run"]


def test_geometry_multiview_host_recovers_invalid_interrupted_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Replace an invalid interrupted terminal only after bounded recovery."""

    root = tmp_path / "invalid_terminal_asset"
    workflow_id = "wf-invalid-terminal"
    workflow_root = root / "workflows" / workflow_id
    workflow_root.mkdir(parents=True)
    (workflow_root / "plan.json").write_text("{}\n", encoding="utf-8")
    run_id = "v08-invalid-terminal"
    run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
    run_root.mkdir(parents=True)
    plan_path = run_root / "plan.json"
    plan_path.write_text(
        _workflow_assembly_sanity_plan(
            "invalid_terminal_asset",
            run_id,
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    manifest_path = run_root / "render_manifest.json"
    report_path = run_root / "report.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    report_path.write_text("{}\n", encoding="utf-8")
    input_fingerprint = "1" * 64
    step = WorkflowStep(
        step_id="detail.geometry_multiview",
        title="Review geometry",
        phase="geometry",
        execution_mode="host",
        tool_name="run_geometry_multiview_review",
        parameters={
            "run_id": run_id,
            "resolution": 384,
            "review_policy": "exterior_geometry_review_v2",
        },
    )
    _write_interrupted_multiview_attempt(
        workflow_root,
        workflow_id=workflow_id,
        job_id="invalid_terminal_asset",
        step=step,
        input_fingerprint=input_fingerprint,
    )
    calls: list[str] = []

    def reject_terminal(*_args: object, **_kwargs: object) -> object:
        """Model one terminal whose exact immutable evidence is invalid."""

        raise ValueError("invalid terminal fixture")

    def recover(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Remove invalid terminal files as the bounded recovery would."""

        calls.append("recover")
        manifest_path.unlink()
        report_path.unlink()
        return {"status": "recovered"}

    def run(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Return exact terminal paths after recovery."""

        calls.append("run")
        return {
            "render_manifest": str(manifest_path),
            "report": str(report_path),
            "review_policy": "exterior_geometry_review_v2",
        }

    monkeypatch.setattr(
        orchestration_service,
        "validate_assembly_sanity_terminal",
        reject_terminal,
    )
    monkeypatch.setattr(
        orchestration_service,
        "recover_incomplete_job_assembly_multiview_sanity",
        recover,
    )
    monkeypatch.setattr(
        orchestration_service,
        "run_job_assembly_multiview_sanity",
        run,
    )
    request = SimpleNamespace(
        job_id="invalid_terminal_asset",
        workflow_id=workflow_id,
    )

    orchestration_service._execute_host_tool(
        root,
        workflow_root,
        request,
        step,
        input_fingerprint=input_fingerprint,
    )

    assert calls == ["recover", "run"]


def test_geometry_multiview_host_recovers_interrupted_unpublished_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Recover an exact interrupted plan-temp run before planning it again."""

    root = tmp_path / "unpublished_plan_asset"
    workflow_id = "wf-unpublished-plan"
    workflow_root = root / "workflows" / workflow_id
    workflow_root.mkdir(parents=True)
    (workflow_root / "plan.json").write_text("{}\n", encoding="utf-8")
    run_id = "v08-unpublished-plan"
    run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
    run_root.mkdir(parents=True)
    (run_root / ".plan.json.1234.tmp").write_text("{\n", encoding="utf-8")
    input_fingerprint = "2" * 64
    step = WorkflowStep(
        step_id="detail.geometry_multiview",
        title="Review geometry",
        phase="geometry",
        execution_mode="host",
        tool_name="run_geometry_multiview_review",
        parameters={
            "run_id": run_id,
            "resolution": 384,
            "review_policy": "exterior_geometry_review_v2",
        },
    )
    _write_interrupted_multiview_attempt(
        workflow_root,
        workflow_id=workflow_id,
        job_id="unpublished_plan_asset",
        step=step,
        input_fingerprint=input_fingerprint,
    )
    calls: list[str] = []

    def recover(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Clear only the known unpublished-plan fixture artifacts."""

        calls.append("recover_unpublished")
        (run_root / ".plan.json.1234.tmp").unlink()
        run_root.rmdir()
        return {"status": "recovered"}

    def plan(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Return the exact replanned immutable path and hash."""

        calls.append("plan")
        return {
            "plan": str(run_root / "plan.json"),
            "plan_sha256": "3" * 64,
            "review_policy": "exterior_geometry_review_v2",
        }

    def run(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Return the exact terminal paths after replanning."""

        calls.append("run")
        return {
            "render_manifest": str(run_root / "render_manifest.json"),
            "report": str(run_root / "report.json"),
            "review_policy": "exterior_geometry_review_v2",
        }

    monkeypatch.setattr(
        orchestration_service,
        "recover_unpublished_job_assembly_multiview_plan",
        recover,
    )
    monkeypatch.setattr(
        orchestration_service,
        "plan_job_assembly_multiview_sanity",
        plan,
    )
    monkeypatch.setattr(
        orchestration_service,
        "run_job_assembly_multiview_sanity",
        run,
    )
    request = SimpleNamespace(
        job_id="unpublished_plan_asset",
        workflow_id=workflow_id,
    )

    orchestration_service._execute_host_tool(
        root,
        workflow_root,
        request,
        step,
        input_fingerprint=input_fingerprint,
    )

    assert calls == ["recover_unpublished", "plan", "run"]


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


def test_standard_full_workflow_can_end_at_explicit_v06_preview_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Allow a standard full authoring pass to stop after QA without V0.7 steps."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    state = plan_workflow(
        "Create a standard static asset and stop after its V0.6 review evidence.",
        job_id="standard_preview_boundary_asset",
        reference_path=_image(tmp_path / "standard_preview_boundary.png"),
        intent="new_asset",
        scope="full",
        execution_policy="standard",
        delivery_scope="preview_only",
    )
    root = workspace / state.job_id / "workflows" / state.workflow_id
    request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    routing = json.loads((root / "routing.json").read_text(encoding="utf-8"))
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    step_ids = [step["step_id"] for step in plan["steps"]]

    assert request["delivery_scope"] == "preview_only"
    assert routing["delivery_scope"] == "preview_only"
    assert plan["delivery_scope"] == "preview_only"
    assert "qa.run" in step_ids
    assert "qa.review" in step_ids
    assert not any(step_id.startswith("portable.") for step_id in step_ids)


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
    workflow = WorkflowPlan.model_validate(plan)
    exact_output = _policy_gate_exact_output_path(
        workspace / "portable_asset",
        workflow,
        boundary_step_id="portable.final_approval",
        gate_kind="final_package_acknowledgement",
    )
    planned_manifest = next(
        output["path"]
        for output in next(
            item for item in plan["steps"] if item["step_id"] == "portable.report"
        )["outputs"]
        if output["artifact_id"] == "portable.report.manifest"
    )
    assert exact_output == (
        "portable.report.manifest",
        workspace / "portable_asset" / planned_manifest,
    )
    assert "/artifacts/pdf/" in planned_manifest
    with pytest.raises(ValueError, match="not a prerequisite"):
        _policy_gate_exact_output_path(
            workspace / "portable_asset",
            workflow,
            boundary_step_id="portable.roundtrip",
            gate_kind="final_package_acknowledgement",
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
        assert authored["parameters"]["require_spatial_surface_details"] is True
    else:
        qa_run = next(item for item in plan["steps"] if item["step_id"] == "qa.run")
        qa_run_id = qa_run["parameters"]["run_id"]
        assert {item["path"] for item in qa_run["outputs"]} == {
            f"qa/runs/{qa_run_id}/request.json",
            f"qa/runs/{qa_run_id}/reference_mask.png",
            f"qa/runs/{qa_run_id}/reference_mask_manifest.json",
            f"qa/runs/{qa_run_id}/render_pass_manifest.json",
            f"qa/runs/{qa_run_id}/visual_qa_report.json",
            f"qa/runs/{qa_run_id}/revision_candidates.json",
            *{
                f"qa/runs/{qa_run_id}/passes/{kind}.png"
                for kind in (
                    "beauty",
                    "silhouette",
                    "object_id",
                    "material_id",
                    "normal",
                    "depth",
                    "wireframe",
                )
            },
        }
        assert all(item["lifecycle"] == "immutable_run" for item in qa_run["outputs"])


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
