"""Focused Skill Orchestration 0.1 registry, Standard, AQ, and trace tests."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from codex_blender_modeler.analysis.models import ModelingPlan
from codex_blender_modeler.auto_revision.models import (
    RevisionApproval,
    RevisionCandidate,
    RevisionCandidates,
)
from codex_blender_modeler.orchestration import plan_workflow
from codex_blender_modeler.orchestration.models import (
    WorkflowApproval,
    WorkflowPlan,
    WorkflowState,
)
from codex_blender_modeler.qa.multiview_sanity import GeometryMultiviewVisualReview
from codex_blender_modeler.revision import RevisionOperation, RevisionPlan
from codex_blender_modeler.skill_orchestration import (
    cancel_aq_one_prompt_skill,
    cancel_standard_asset_cycle,
    get_skill_catalog,
    get_skill_execution_trace,
    get_standard_asset_cycle_status,
    plan_aq_one_prompt_skill,
    plan_standard_asset_cycle,
    reconcile_aq_one_prompt_skill_terminal,
    resume_standard_asset_cycle,
    run_aq_one_prompt_skill,
    run_standard_asset_cycle,
)
from codex_blender_modeler.skill_orchestration import service as skill_service
from codex_blender_modeler.skill_orchestration.models import (
    GuardedRevisionContinuation,
    MaterialImpactReport,
    MaterialImpactSnapshot,
    SkillArtifact,
    SkillExecutionReceipt,
    SkillRegistry,
    StandardCompositeRunPlan,
    StandardCompositeRunState,
    StandardCompositeStageBinding,
)
from codex_blender_modeler.skill_orchestration.service import (
    _aq_route_key,
    _capture_material_snapshot,
    _publish_guarded_revision_continuation,
    _publish_material_impact,
)
from codex_blender_modeler.stabilization.service import _audit_skill_runs
from codex_blender_modeler.workspace import sha256_file


def _image(path: Path) -> Path:
    """Create one deterministic local reference image for a new Standard job."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 32), (70, 100, 150)).save(path)
    return path


def _write_material_projection(root: Path, *, material_id: str) -> None:
    """Write the four material-sensitive JSON sources used by impact evaluation."""

    (root / "analysis").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "analysis" / "scene_spec.json").write_text(
        json.dumps({"objects": [{"id": "body", "material_id": material_id}]}) + "\n",
        encoding="utf-8",
    )
    (root / "analysis" / "modeling_plan.json").write_text(
        json.dumps({"surface_details": []}) + "\n",
        encoding="utf-8",
    )
    (root / "analysis" / "material_plan.json").write_text(
        json.dumps({"materials": [{"id": material_id}]}) + "\n",
        encoding="utf-8",
    )
    (root / "reports" / "scene_inventory.json").write_text(
        json.dumps({"objects": [{"id": "body", "uv_layout_sha256": "a" * 64}]})
        + "\n",
        encoding="utf-8",
    )


def _write_authored_modeling_plan(root: Path, job_id: str) -> None:
    """Create the exact authored V0.4 boundary required by revise_asset planning."""

    plan = ModelingPlan.model_validate(
        {
            "job_id": job_id,
            "reference_analysis_path": "analysis/reference_analysis.json",
            "camera_solution_path": "analysis/camera_solution.json",
            "stage": "authored",
            "objects": [
                {
                    "id": "body",
                    "label": "body",
                    "source_ids": ["ref.main"],
                    "assembly_role": "unclassified",
                }
            ],
            "assembly_consistency_policy": "legacy_unbound",
        }
    )
    (root / "analysis" / "modeling_plan.json").write_text(
        plan.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def _prepare_full_cycle_quality_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    job_id: str,
    run_id: str,
    max_qa_revision_iterations: int,
    stage_policy: str = "smart",
    max_stage_transitions: int = 1,
) -> tuple[Path, dict[str, object]]:
    """Complete one synthetic exact QA child and return its human quality boundary."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    plan_workflow(
        "Create the initial bounded reference asset.",
        job_id=job_id,
        reference_path=_image(tmp_path / f"{job_id}.png"),
    )
    root = workspace / job_id
    _write_material_projection(root, material_id="paint")
    _write_authored_modeling_plan(root, job_id)
    planned = plan_standard_asset_cycle(
        "Continue through exact QA and only then consider portable delivery.",
        goal="full_cycle_to_package",
        job_id=job_id,
        max_qa_revision_iterations=max_qa_revision_iterations,
        stage_policy=stage_policy,  # type: ignore[arg-type]
        run_id=run_id,
    )
    run_root = root / "skill_runs" / run_id
    state = StandardCompositeRunState.model_validate(planned["state"])
    qa_binding_artifact = skill_service._plan_child_workflow(
        root,
        run_root,
        run_id=run_id,
        job_id=job_id,
        ordinal=2,
        request_text="Run one exact fixed-camera V0.6 comparison.",
        stage_kind="qa",
        profile_id="portable_gltf",
        reason="Synthetic regression reaches the exact QA quality boundary.",
    )
    state = skill_service._append_child_to_state(state, qa_binding_artifact)
    skill_service._write_standard_state(run_root, state)
    qa_binding = StandardCompositeStageBinding.model_validate_json(
        (root / qa_binding_artifact.path).read_text(encoding="utf-8")
    )
    qa_plan = WorkflowPlan.model_validate_json(
        (root / qa_binding.workflow_plan.path).read_text(encoding="utf-8")
    )
    qa_run_id = skill_service._qa_run_id_from_workflow_plan(qa_plan)
    qa_root = root / "qa" / "runs" / qa_run_id
    qa_root.mkdir(parents=True, exist_ok=True)
    report_path = qa_root / "visual_qa_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "0.6.0",
                "job_id": job_id,
                "run_id": qa_run_id,
                "request_sha256": "1" * 64,
                "camera_fingerprint": "2" * 64,
                "direct_metrics": {
                    "scoring_version": "semantic_bbox_v2",
                    "silhouette_iou": 0.7,
                    "silhouette_union_fraction": 0.4,
                    "global_bbox": {
                        "reference_bbox_norm": [0.1, 0.1, 0.9, 0.9],
                        "rendered_bbox_norm": [0.2, 0.2, 0.8, 0.8],
                        "center_error_norm": 0.0,
                        "size_error_norm": 0.2,
                    },
                    "semantic_deviations": [],
                    "overall_direct_score": 0.75,
                },
                "findings": [
                    {
                        "id": "direct.global_silhouette",
                        "target_ids": [],
                        "issue_type": "silhouette",
                        "severity": "high",
                        "description": "The primary silhouette still differs.",
                        "evidence_sources": ["direct_reference"],
                        "confidence": 0.9,
                        "metrics": {"silhouette_iou": 0.7},
                        "suggestion": None,
                    }
                ],
                "generated_target_status": "not_requested",
                "warnings": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (qa_root / "revision_candidates.json").write_text(
        RevisionCandidates(
            job_id=job_id,
            base_spec_sha256=sha256_file(root / "analysis" / "scene_spec.json"),
            camera_fingerprint="2" * 64,
            source_report_sha256=sha256_file(report_path),
            candidates=[
                RevisionCandidate(
                    id="candidate.direct.proportion.body",
                    finding_id="direct.proportion.body",
                    target_type="object",
                    target_id="body",
                    path=["transform", "scale"],
                    op="set",
                    value=[1.05, 1.05, 1.05],
                    reason="Match the direct-reference image-space size.",
                    evidence_sources=["direct_reference"],
                    confidence=0.8,
                    applicability="approval_required",
                    acceptance_criteria=["Direct silhouette improves without ID changes."],
                )
            ],
            locked_ids=["paint"],
            locked_paths=[["camera"]],
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    qa_state_path = root / "workflows" / qa_binding.workflow_id / "state.json"

    def complete_exact_qa(
        selected_job_id: str,
        selected_workflow_id: str,
        *,
        max_host_steps: int,
        retry_failed: bool,
    ) -> WorkflowState:
        """Publish the consumed qa.review fixture for one composite resume."""

        assert (selected_job_id, selected_workflow_id) == (job_id, qa_binding.workflow_id)
        assert max_host_steps >= 1
        assert retry_failed is False
        current = WorkflowState.model_validate_json(
            qa_state_path.read_text(encoding="utf-8")
        )
        completed = current.model_copy(
            update={
                "status": "completed",
                "current_step_id": None,
                "steps": [
                    item.model_copy(
                        update={
                            "status": "complete",
                            "input_fingerprint": item.input_fingerprint or "3" * 64,
                            "completion_fingerprint": "4" * 64,
                            "approval_id": (
                                "approval-quality-review"
                                if item.step_id == "qa.review"
                                else item.approval_id
                            ),
                            "completed_at": datetime.now(UTC),
                            "error": None,
                            "reason_code": None,
                        }
                    )
                    for item in current.steps
                ],
                "next_action": None,
                "waiting_gate": None,
                "updated_at": datetime.now(UTC),
            }
        )
        qa_state_path.write_text(
            completed.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return completed

    monkeypatch.setattr(skill_service, "resume_workflow", complete_exact_qa)
    result = run_standard_asset_cycle(
        job_id,
        run_id,
        max_host_steps=1,
        max_stage_transitions=max_stage_transitions,
    )
    return root, result


def _impact_plan(
    root: Path,
    *,
    run_id: str,
    stage_policy: str,
    before: MaterialImpactSnapshot,
) -> StandardCompositeRunPlan:
    """Create one isolated plan sufficient to exercise MaterialImpactReport policy."""

    placeholder = root / f"{run_id}-placeholder.json"
    placeholder.write_text("{}\n", encoding="utf-8")
    artifact = SkillArtifact(
        path=placeholder.relative_to(root).as_posix(),
        sha256=sha256_file(placeholder),
    )
    return StandardCompositeRunPlan(
        plan_id=f"plan-{run_id}",
        run_id=run_id,
        job_id="materialimpact",
        request_text="Evaluate exact material-sensitive changes.",
        goal="polish_existing_to_qa",
        stage_policy=stage_policy,  # type: ignore[arg-type]
        bundle_manifest=artifact,
        initial_material_snapshot=before,
        initial_stage_binding=artifact,
        created_at=datetime.now(UTC),
    )


def test_material_impact_smart_skips_only_when_projection_is_unchanged(
    tmp_path: Path,
) -> None:
    """Require fresh V0.5 when assignments change and permit it only when proven stable."""

    root = tmp_path / "materialimpact"
    unchanged_run = root / "skill_runs" / "impact-unchanged"
    unchanged_run.mkdir(parents=True)
    _write_material_projection(root, material_id="paint")
    unchanged_before = _capture_material_snapshot(root, unchanged_run, "before")
    unchanged_after = _capture_material_snapshot(root, unchanged_run, "after")
    unchanged_plan = _impact_plan(
        root,
        run_id="impact-unchanged",
        stage_policy="smart",
        before=unchanged_before,
    )
    unchanged_artifact = _publish_material_impact(
        root,
        unchanged_run,
        unchanged_plan,
        unchanged_after,
    )
    unchanged = MaterialImpactReport.model_validate_json(
        (root / unchanged_artifact.path).read_text(encoding="utf-8")
    )
    assert unchanged.material_authoring_required is False
    assert unchanged.changed_inputs == []

    changed_run = root / "skill_runs" / "impact-changed"
    changed_run.mkdir()
    _write_material_projection(root, material_id="paint")
    changed_before = _capture_material_snapshot(root, changed_run, "before")
    _write_material_projection(root, material_id="metal")
    changed_after = _capture_material_snapshot(root, changed_run, "after")
    changed_plan = _impact_plan(
        root,
        run_id="impact-changed",
        stage_policy="smart",
        before=changed_before,
    )
    changed_artifact = _publish_material_impact(
        root,
        changed_run,
        changed_plan,
        changed_after,
    )
    changed = MaterialImpactReport.model_validate_json(
        (root / changed_artifact.path).read_text(encoding="utf-8")
    )
    assert changed.material_authoring_required is True
    assert "assignments" in changed.changed_inputs


def test_material_impact_force_all_requires_fresh_v05(tmp_path: Path) -> None:
    """Keep force_all authoritative even when every material-sensitive input is stable."""

    root = tmp_path / "materialimpact"
    run_root = root / "skill_runs" / "impact-force-all"
    run_root.mkdir(parents=True)
    _write_material_projection(root, material_id="paint")
    before = _capture_material_snapshot(root, run_root, "before")
    after = _capture_material_snapshot(root, run_root, "after")
    plan = _impact_plan(
        root,
        run_id="impact-force-all",
        stage_policy="force_all",
        before=before,
    )
    artifact = _publish_material_impact(root, run_root, plan, after)
    report = MaterialImpactReport.model_validate_json(
        (root / artifact.path).read_text(encoding="utf-8")
    )
    assert report.material_authoring_required is True
    assert any("force_all" in reason for reason in report.reasons)


def test_material_impact_is_append_only_across_geometry_stages(tmp_path: Path) -> None:
    """Keep repeated geometry decisions distinct without rewriting the first report."""

    root = tmp_path / "materialimpact"
    run_root = root / "skill_runs" / "impact-repeated-geometry"
    run_root.mkdir(parents=True)
    _write_material_projection(root, material_id="paint")
    before = _capture_material_snapshot(root, run_root, "before")
    plan = _impact_plan(
        root,
        run_id="impact-repeated-geometry",
        stage_policy="force_all",
        before=before,
    )
    first_after = _capture_material_snapshot(root, run_root, "after-geometry")
    first_artifact = _publish_material_impact(
        root,
        run_root,
        plan,
        first_after,
        stage_ordinal=1,
    )
    first_path = root / first_artifact.path
    first_bytes = first_path.read_bytes()

    _write_material_projection(root, material_id="metal")
    second_after = _capture_material_snapshot(
        root,
        run_root,
        "after-geometry-0005",
    )
    second_artifact = _publish_material_impact(
        root,
        run_root,
        plan,
        second_after,
        stage_ordinal=5,
    )
    second = MaterialImpactReport.model_validate_json(
        (root / second_artifact.path).read_text(encoding="utf-8")
    )

    assert first_artifact.path.endswith("material_impact.json")
    assert second_artifact.path.endswith("material_impacts/0005.json")
    assert first_path.read_bytes() == first_bytes
    assert second.report_id == "material-impact-impact-repeated-geometry-0005"
    assert second.after.scene_spec is not None
    assert second.after.scene_spec.path.endswith(
        "snapshots/material/after-geometry-0005/scene_spec.json"
    )


def test_guarded_revision_continuation_requires_consumed_exact_v06_evidence(
    tmp_path: Path,
) -> None:
    """Reject a SceneSpec change until its exact V0.6 approval and apply are consumed."""

    root = tmp_path / "materialimpact"
    run_root = root / "skill_runs" / "qa-repair-run"
    run_root.mkdir(parents=True)
    _write_material_projection(root, material_id="paint")
    before = _capture_material_snapshot(root, run_root, "before")
    plan = _impact_plan(
        root,
        run_id="qa-repair-run",
        stage_policy="smart",
        before=before,
    ).model_copy(update={"goal": "qa_repair_cycle"})
    placeholder = plan.initial_stage_binding
    baseline_sha256 = "b" * 64
    result_sha256 = "c" * 64
    state = StandardCompositeRunState(
        run_id=plan.run_id,
        job_id=plan.job_id,
        plan=plan.bundle_manifest,
        status="waiting_for_external_revision",
        current_stage_binding=placeholder,
        stage_bindings=[placeholder],
        qa_revision_source_run_id="qa-source",
        qa_baseline_scene_spec_sha256=baseline_sha256,
        next_action="Apply one exact guarded revision.",
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(FileNotFoundError):
        _publish_guarded_revision_continuation(
            root,
            run_root,
            plan,
            state,
            current_scene_spec_sha256=result_sha256,
        )

    qa_root = root / "qa" / "runs" / "qa-source"
    qa_root.mkdir(parents=True)
    source_report = qa_root / "visual_qa_report.json"
    source_report.write_text("{}\n", encoding="utf-8")
    candidate = RevisionCandidate(
        id="candidate-1",
        finding_id="finding-1",
        target_type="object",
        target_id="body",
        path=["transform", "scale", 0],
        op="set",
        value=1.1,
        reason="Match the observed width.",
        evidence_sources=["direct_reference"],
        confidence=0.8,
        applicability="approval_required",
        acceptance_criteria=["Direct silhouette width improves."],
    )
    candidates = RevisionCandidates(
        job_id=plan.job_id,
        base_spec_sha256=baseline_sha256,
        camera_fingerprint="a" * 64,
        source_report_sha256=sha256_file(source_report),
        candidates=[candidate],
    )
    candidates_path = qa_root / "revision_candidates.json"
    candidates_path.write_text(
        candidates.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    revision_plan = RevisionPlan(
        job_id=plan.job_id,
        base_spec_sha256=baseline_sha256,
        request="Apply the selected exact correction.",
        operations=[
            RevisionOperation(
                op="set",
                target_type="object",
                target_id="body",
                path=["transform", "scale", 0],
                value=1.1,
                reason="Match the observed width.",
            )
        ],
        acceptance_criteria=["Direct silhouette width improves."],
    )
    revision_plan_path = qa_root / "revision_plan.json"
    revision_plan_path.write_text(
        revision_plan.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    approval = RevisionApproval(
        approval_id="approval-1",
        job_id=plan.job_id,
        candidates_sha256=sha256_file(candidates_path),
        plan_sha256=sha256_file(revision_plan_path),
        base_spec_sha256=baseline_sha256,
        approved_candidate_ids=["candidate-1"],
        approved_at=datetime.now(UTC).isoformat(),
        used=True,
        used_at=datetime.now(UTC).isoformat(),
    )
    approval_path = qa_root / "revision_approval.json"
    approval_path.write_text(
        approval.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (qa_root / "application_report.json").write_text(
        json.dumps(
            {
                "schema_version": "0.6.0",
                "job_id": plan.job_id,
                "run_id": "qa-source",
                "status": "applied_unverified",
                "approval_id": approval.approval_id,
                "approved_candidate_ids": approval.approved_candidate_ids,
                "base_spec_sha256": baseline_sha256,
                "result_spec_sha256": result_sha256,
                "approval_used": True,
                "completed_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    artifact = _publish_guarded_revision_continuation(
        root,
        run_root,
        plan,
        state,
        current_scene_spec_sha256=result_sha256,
    )
    continuation = GuardedRevisionContinuation.model_validate_json(
        (root / artifact.path).read_text(encoding="utf-8")
    )
    assert continuation.application_status == "applied_unverified"
    assert continuation.result_scene_spec_sha256 == result_sha256
    assert continuation.approval_authority is False


def test_registry_declares_exact_entrypoints_and_acyclic_routes() -> None:
    """Require the validated 23-skill DAG and only the two approved public entries."""

    catalog = get_skill_catalog()
    registry = SkillRegistry.model_validate(catalog["registry"])
    assert registry.entry_skills == [
        "standard-asset-cycle",
        "aq-one-prompt-orchestrator",
    ]
    assert len(registry.skills) == 23
    assert catalog["canonical_write_authority"] is False
    assert catalog["approval_authority"] is False


def test_skill_receipt_schema_is_strict_and_chain_origin_is_exact() -> None:
    """Reject undeclared receipt data and a non-origin receipt without predecessor."""

    schema = SkillExecutionReceipt.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "0.1.0"


def test_standard_new_asset_plan_ends_at_qa_and_snapshots_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Plan the existing full preview flow without silently appending V0.7 delivery."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    result = plan_standard_asset_cycle(
        "이 레퍼런스로 정적 소품을 QA까지 제작해줘",
        goal="new_asset_to_qa",
        job_id="skillasset",
        reference_path=_image(tmp_path / "reference.png"),
        run_id="standard-skill-test",
    )
    assert result["status"] == "planned"
    run_root = workspace / "skillasset" / "skill_runs" / "standard-skill-test"
    bundle = json.loads((run_root / "bundle.json").read_text(encoding="utf-8"))
    assert bundle["entry_skill_id"] == "standard-asset-cycle"
    assert "portable-asset-delivery" in bundle["skill_ids"]
    assert len(bundle["resources"]) == len(bundle["skill_ids"])
    workflow_id = result["current_workflow"]["workflow_id"]
    workflow_plan = json.loads(
        (
            workspace
            / "skillasset"
            / "workflows"
            / workflow_id
            / "plan.json"
        ).read_text(encoding="utf-8")
    )
    assert any(step["step_id"] == "qa.review" for step in workflow_plan["steps"])
    assert not any(step["phase"] == "portable" for step in workflow_plan["steps"])


@pytest.mark.parametrize(
    ("goal", "stage_kind", "intent"),
    [
        ("polish_existing_to_qa", "geometry", "revise_asset"),
        ("material_refresh_to_qa", "material", "material_authoring"),
        ("qa_repair_cycle", "qa", "visual_qa"),
        ("full_cycle_to_package", "geometry", "revise_asset"),
    ],
)
def test_standard_existing_goals_plan_the_expected_v08_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    goal: str,
    stage_kind: str,
    intent: str,
) -> None:
    """Map every existing-asset goal to a new immutable V0.8 child workflow."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    suffix = goal.split("_", 1)[0].replace("full", "package")
    job_id = f"existing-{suffix}"
    plan_workflow(
        "Create the initial bounded reference asset.",
        job_id=job_id,
        reference_path=_image(tmp_path / f"{job_id}.png"),
    )
    _write_authored_modeling_plan(workspace / job_id, job_id)
    result = plan_standard_asset_cycle(
        "Continue this existing asset to the selected boundary.",
        goal=goal,
        job_id=job_id,
        run_id=f"standard-{suffix}",
    )
    binding_path = workspace / job_id / result["state"]["current_stage_binding"]["path"]
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    assert binding["stage_kind"] == stage_kind
    workflow_plan = json.loads(
        (workspace / job_id / binding["workflow_plan"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    assert workflow_plan["intent"] == intent


def test_standard_run_routes_to_agent_boundary_and_validates_trace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Advance host analysis only until V0.8 requests exact agent-authored geometry."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    planned = plan_standard_asset_cycle(
        "이 레퍼런스로 정적 소품을 QA까지 제작해줘",
        goal="new_asset_to_qa",
        job_id="skilltrace",
        reference_path=_image(tmp_path / "trace.png"),
        run_id="standard-skill-trace",
    )
    result = run_standard_asset_cycle(
        "skilltrace",
        planned["run_id"],
        max_host_steps=4,
    )
    assert result["status"] == "waiting_for_agent"
    assert result["current_skill_route"]["skill_id"] == "reference-to-scene"
    assert result["current_skill_route"]["stage_key"] == "standard.geometry.author"
    trace = get_skill_execution_trace("skilltrace", "standard-skill-trace")
    assert trace["status"] == "valid"
    assert len(trace["routes"]) == 1
    assert len(trace["receipts"]) == 1
    assert trace["receipts"][0]["outcome"] == "waiting_for_agent"


def test_full_cycle_requires_exact_human_quality_disposition_before_v07(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Stop after consumed qa.review and plan V0.7 only after an exact human decision."""

    job_id = "skillqualitybarrier"
    run_id = "standard-quality-barrier"
    root, waiting = _prepare_full_cycle_quality_boundary(
        monkeypatch,
        tmp_path,
        job_id=job_id,
        run_id=run_id,
        max_qa_revision_iterations=1,
    )
    assert waiting["status"] == "waiting_for_quality_disposition"
    state = StandardCompositeRunState.model_validate(waiting["state"])
    assert len(state.stage_bindings) == 2
    assert len(state.quality_disposition_requests) == 1
    assert state.quality_dispositions == []
    request_artifact = state.current_quality_disposition_request
    assert request_artifact is not None
    request = json.loads(
        (root / request_artifact.path).read_text(encoding="utf-8")
    )
    assert request["qa_review_approval_id"] == "approval-quality-review"
    assert request["recommended_disposition"] == "needs_revision"
    assert request["high_finding_ids"] == ["direct.global_silhouette"]
    state_path = root / "skill_runs" / run_id / "state.json"
    state_before_stale_decision = state_path.read_bytes()
    with pytest.raises(RuntimeError, match="stale or mismatched"):
        skill_service._record_standard_quality_disposition(
            job_id,
            run_id,
            disposition="accepted",
            request_fingerprint="0" * 64,
            user_note="Accept only the exact current V0.6 visual result.",
        )
    assert state_path.read_bytes() == state_before_stale_decision

    skill_service._record_standard_quality_disposition(
        job_id,
        run_id,
        disposition="accepted",
        request_fingerprint=request_artifact.sha256,
        user_note="Accept only the exact current V0.6 visual result.",
    )
    accepted = get_standard_asset_cycle_status(job_id, run_id)
    accepted_state = StandardCompositeRunState.model_validate(accepted["state"])
    assert accepted_state.status == "running"
    assert len(accepted_state.quality_dispositions) == 1
    assert accepted_state.current_quality_disposition_request is None
    portable_binding = StandardCompositeStageBinding.model_validate_json(
        (root / accepted_state.stage_bindings[-1].path).read_text(encoding="utf-8")
    )
    assert portable_binding.stage_kind == "portable"
    assert "still requires its own optimization" in portable_binding.created_reason


def test_full_cycle_stops_at_new_quality_disposition_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Stop the transition loop after publishing exactly one human quality request."""

    job_id = "skillqualityloopstop"
    run_id = "standard-quality-loop-stop"
    root, waiting = _prepare_full_cycle_quality_boundary(
        monkeypatch,
        tmp_path,
        job_id=job_id,
        run_id=run_id,
        max_qa_revision_iterations=0,
        max_stage_transitions=8,
    )

    state = StandardCompositeRunState.model_validate(waiting["state"])
    assert waiting["status"] == "waiting_for_quality_disposition"
    assert len(state.quality_disposition_requests) == 1
    assert sorted(
        path.name
        for path in (root / "skill_runs" / run_id / "quality" / "requests").glob(
            "*.json"
        )
    ) == ["0001.json"]


def test_full_cycle_adopts_only_idempotent_quality_boundary_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Recover a persisted quality boundary after one append-only no-op receipt."""

    job_id = "skillqualityreceiptadoption"
    run_id = "standard-quality-receipt-adoption"
    root, waiting = _prepare_full_cycle_quality_boundary(
        monkeypatch,
        tmp_path,
        job_id=job_id,
        run_id=run_id,
        max_qa_revision_iterations=0,
    )
    state = StandardCompositeRunState.model_validate(waiting["state"])
    run_root = root / "skill_runs" / run_id
    binding = skill_service._current_binding(root, state)
    workflow_state = WorkflowState.model_validate(
        get_standard_asset_cycle_status(job_id, run_id)["current_workflow"]["state"]
    )
    sequence = skill_service._receipt_sequence(run_root)
    source = skill_service._workflow_state_source(root, binding.workflow_id)
    before_snapshot = skill_service._snapshot_underlying_state(
        root,
        run_root,
        sequence=sequence,
        label="before",
        source_artifact=source,
    )
    bundle, registry = skill_service._load_bundle(root, run_root)
    route_key, _placeholder, route_reason = skill_service._standard_route(
        root,
        binding,
        workflow_state,
    )
    route = skill_service._publish_route_decision(
        root,
        run_root,
        run_id=run_id,
        job_id=job_id,
        sequence=sequence,
        execution_mode="standard",
        route_key=route_key,
        selected_skill=skill_service._route_from_registry(
            bundle,
            registry,
            execution_mode="standard",
            route_key=route_key,
        ),
        source_state=before_snapshot,
        reason=route_reason,
    )
    after_snapshot = skill_service._snapshot_underlying_state(
        root,
        run_root,
        sequence=sequence,
        label="after",
        source_artifact=source,
    )
    trailing_receipt = skill_service._publish_execution_receipt(
        root,
        run_root,
        run_id=run_id,
        job_id=job_id,
        sequence=sequence,
        route=route,
        before=skill_service._workflow_binding(
            binding,
            before_snapshot,
            workflow_state,
        ),
        after=skill_service._workflow_binding(
            binding,
            after_snapshot,
            workflow_state,
        ),
        outcome="completed",
    )

    with pytest.raises(ValueError, match="receipt-chain head is stale"):
        get_skill_execution_trace(job_id, run_id)
    recovered = run_standard_asset_cycle(job_id, run_id, max_stage_transitions=8)
    recovered_state = StandardCompositeRunState.model_validate(recovered["state"])

    assert recovered["status"] == "waiting_for_quality_disposition"
    assert recovered_state.receipt_chain_head_sha256 == trailing_receipt.sha256
    assert len(recovered_state.quality_disposition_requests) == 1
    assert get_skill_execution_trace(job_id, run_id)["status"] == "valid"


def test_needs_revision_quality_disposition_respects_exact_revision_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Publish a safe terminal instead of packaging when no QA revision remains."""

    job_id = "skillqualityexhausted"
    run_id = "standard-quality-exhausted"
    root, waiting = _prepare_full_cycle_quality_boundary(
        monkeypatch,
        tmp_path,
        job_id=job_id,
        run_id=run_id,
        max_qa_revision_iterations=0,
    )
    state = StandardCompositeRunState.model_validate(waiting["state"])
    request_artifact = state.current_quality_disposition_request
    assert request_artifact is not None
    skill_service._record_standard_quality_disposition(
        job_id,
        run_id,
        disposition="needs_revision",
        request_fingerprint=request_artifact.sha256,
        user_note="The current high silhouette finding still requires revision.",
    )
    terminal = get_standard_asset_cycle_status(job_id, run_id)
    assert terminal["status"] == "blocked"
    assert terminal["terminal"]["terminal_type"] == "blocked"
    assert "revision budget is exhausted" in terminal["terminal"]["reason"]
    assert len(terminal["state"]["quality_dispositions"]) == 1
    assert not any(
        StandardCompositeStageBinding.model_validate_json(
            (root / artifact["path"]).read_text(encoding="utf-8")
        ).stage_kind
        == "portable"
        for artifact in terminal["state"]["stage_bindings"]
    )


def test_needs_revision_with_budget_routes_isolated_candidate_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Use the default candidate-review host path without changing global QA mode."""

    job_id = "skillqualitycandidate"
    run_id = "standard-quality-candidate"
    root, waiting = _prepare_full_cycle_quality_boundary(
        monkeypatch,
        tmp_path,
        job_id=job_id,
        run_id=run_id,
        max_qa_revision_iterations=1,
    )
    state = StandardCompositeRunState.model_validate(waiting["state"])
    request_artifact = state.current_quality_disposition_request
    assert request_artifact is not None
    skill_service._record_standard_quality_disposition(
        job_id,
        run_id,
        disposition="needs_revision",
        request_fingerprint=request_artifact.sha256,
        user_note="Use only the remaining bounded direct-reference revision budget.",
    )

    routed = get_standard_asset_cycle_status(job_id, run_id)
    routed_state = StandardCompositeRunState.model_validate(routed["state"])
    assert routed_state.status == "running"
    assert routed_state.qa_revision_iterations == 0
    assert routed_state.qa_revision_evidence == []
    assert routed_state.qa_revision_source_run_id is None
    assert routed_state.qa_baseline_scene_spec_sha256 is None
    binding = StandardCompositeStageBinding.model_validate_json(
        (root / routed_state.stage_bindings[-1].path).read_text(encoding="utf-8")
    )
    assert binding.stage_kind == "geometry"
    assert binding.created_reason.startswith(skill_service._QUALITY_REVISION_REASON_PREFIX)
    workflow_request = json.loads(
        (root / "workflows" / binding.workflow_id / "request.json").read_text(
            encoding="utf-8"
        )
    )
    workflow_plan = WorkflowPlan.model_validate_json(
        (root / binding.workflow_plan.path).read_text(encoding="utf-8")
    )
    assert workflow_plan.intent == "revise_asset"
    assert workflow_request["revision_strategy"] == "candidate_review"
    assert "candidate.direct.proportion.body" in workflow_request["raw_request"]


def test_standard_failed_host_appends_exact_guarded_geometry_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve a failed child while linking a fresh guarded V0.4 continuation."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    planned = plan_standard_asset_cycle(
        "Create one bounded Standard asset through a portable package.",
        goal="full_cycle_to_package",
        job_id="skilltechnicalrecovery",
        reference_path=_image(tmp_path / "technical-recovery.png"),
        stage_policy="force_all",
        run_id="standard-technical-recovery",
    )
    root = workspace / "skilltechnicalrecovery"
    _write_authored_modeling_plan(root, "skilltechnicalrecovery")
    workflow_id = planned["current_workflow"]["workflow_id"]
    workflow_root = root / "workflows" / workflow_id
    workflow_state_path = workflow_root / "state.json"
    scene_path = root / "analysis" / "scene_spec.json"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text('{"fixture":"canonical-before-recovery"}\n', encoding="utf-8")
    scene_sha256 = sha256_file(scene_path)
    initial = WorkflowState.model_validate_json(workflow_state_path.read_text(encoding="utf-8"))
    build_index = next(
        index for index, item in enumerate(initial.steps) if item.step_id == "material.build"
    )
    prepared_steps = []
    for index, item in enumerate(initial.steps):
        artifacts = item.artifacts
        if item.step_id == "geometry.detail_author":
            artifacts = [
                artifact.model_copy(
                    update={
                        "sha256": scene_sha256,
                        "integrity": "valid",
                        "currency": "current",
                        "verification": "partially_verified",
                        "reason": "Exact canonical recovery fixture.",
                    }
                )
                if artifact.path == "analysis/scene_spec.json"
                else artifact
                for artifact in artifacts
            ]
        status = "complete" if index < build_index else "pending"
        if index == build_index:
            status = "ready"
        prepared_steps.append(
            item.model_copy(
                update={
                    "status": status,
                    "artifacts": artifacts,
                    "error": None,
                    "reason_code": None,
                }
            )
        )
    prepared = initial.model_copy(
        update={
            "status": "running",
            "milestone": "geometry_approved",
            "current_step_id": "material.build",
            "steps": prepared_steps,
            "next_action": "Execute the prepared material build fixture.",
            "reason_code": None,
        }
    )
    workflow_state_path.write_text(
        prepared.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    def fail_exact_host_step(
        selected_job_id: str,
        selected_workflow_id: str,
        *,
        max_host_steps: int,
        retry_failed: bool,
    ) -> WorkflowState:
        """Publish one exact failed host state for the composite recovery fixture."""

        assert (selected_job_id, selected_workflow_id) == (
            "skilltechnicalrecovery",
            workflow_id,
        )
        assert max_host_steps >= 1
        assert retry_failed is False
        current = WorkflowState.model_validate_json(
            workflow_state_path.read_text(encoding="utf-8")
        )
        failed_steps = [
            item.model_copy(
                update={
                    "status": "failed",
                    "attempt_count": item.attempt_count + 1,
                    "error": "Synthetic exact host failure.",
                    "reason_code": "host_failure",
                }
            )
            if item.step_id == "material.build"
            else item
            for item in current.steps
        ]
        failed = current.model_copy(
            update={
                "status": "failed",
                "current_step_id": "material.build",
                "steps": failed_steps,
                "next_action": "Preserve this failure and plan guarded recovery.",
                "reason_code": "host_failure",
            }
        )
        workflow_state_path.write_text(
            failed.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return failed

    monkeypatch.setattr(skill_service, "resume_workflow", fail_exact_host_step)
    failed = run_standard_asset_cycle(
        "skilltechnicalrecovery",
        "standard-technical-recovery",
        max_host_steps=1,
    )
    assert failed["status"] == "failed"
    failed_state_sha256 = sha256_file(workflow_state_path)
    failed_state_bytes = workflow_state_path.read_bytes()
    scene_bytes = scene_path.read_bytes()
    with pytest.raises(RuntimeError, match="state hash changed"):
        skill_service._recover_failed_standard_to_guarded_geometry(
            "skilltechnicalrecovery",
            "standard-technical-recovery",
            failed_state_sha256="0" * 64,
            recovery_reason="Replace the invalid material path with guarded geometry review.",
        )
    assert not (root / "skill_runs" / "standard-technical-recovery" / "recoveries").exists()

    skill_service._recover_failed_standard_to_guarded_geometry(
        "skilltechnicalrecovery",
        "standard-technical-recovery",
        failed_state_sha256=failed_state_sha256,
        recovery_reason="Preserve the technical incident and require guarded geometry review.",
    )
    recovered = get_standard_asset_cycle_status(
        "skilltechnicalrecovery",
        "standard-technical-recovery",
    )
    assert recovered["status"] == "running"
    assert len(recovered["state"]["stage_bindings"]) == 2
    recovery_binding_artifact = recovered["state"]["stage_bindings"][1]
    recovery_binding = StandardCompositeStageBinding.model_validate_json(
        (root / recovery_binding_artifact["path"]).read_text(encoding="utf-8")
    )
    assert recovery_binding.stage_kind == "geometry"
    assert recovery_binding.skill_id == "guarded-visual-revision"
    assert recovery_binding.technical_recovery is not None
    assert recovery_binding.technical_recovery.failed_workflow_state.sha256 == (
        failed_state_sha256
    )
    assert recovery_binding.technical_recovery.failed_step_id == "material.build"
    assert recovery_binding.technical_recovery.user_approval_requested is False
    continuation_plan = WorkflowPlan.model_validate_json(
        (root / recovery_binding.workflow_plan.path).read_text(encoding="utf-8")
    )
    assert continuation_plan.intent == "revise_asset"
    continuation_request = json.loads(
        (
            root
            / "workflows"
            / continuation_plan.workflow_id
            / "request.json"
        ).read_text(encoding="utf-8")
    )
    assert continuation_request["revision_strategy"] == "manual_guarded"
    assert workflow_state_path.read_bytes() == failed_state_bytes
    assert scene_path.read_bytes() == scene_bytes
    trace = get_skill_execution_trace(
        "skilltechnicalrecovery",
        "standard-technical-recovery",
    )
    assert trace["status"] == "valid"
    assert len(trace["receipts"]) == 1


def test_standard_reroutes_only_an_untouched_candidate_to_manual_guarded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cancel an ineligible untouched candidate and preserve its exact reroute receipt."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    plan_workflow(
        "Create the initial bounded reference asset.",
        job_id="skillmanualreroute",
        reference_path=_image(tmp_path / "manual-reroute.png"),
    )
    root = workspace / "skillmanualreroute"
    _write_authored_modeling_plan(root, "skillmanualreroute")
    planned = plan_standard_asset_cycle(
        "Replace custom-mesh topology under an exact guarded revision.",
        goal="polish_existing_to_qa",
        job_id="skillmanualreroute",
        revision_strategy="candidate_review",
        run_id="standard-manual-reroute",
    )
    initial_binding_artifact = planned["state"]["current_stage_binding"]
    initial_binding = StandardCompositeStageBinding.model_validate_json(
        (root / initial_binding_artifact["path"]).read_text(encoding="utf-8")
    )
    waiting = run_standard_asset_cycle(
        "skillmanualreroute",
        "standard-manual-reroute",
        max_host_steps=1,
        max_stage_transitions=1,
    )
    assert waiting["status"] == "waiting_for_agent"
    candidate_state_path = root / "workflows" / initial_binding.workflow_id / "state.json"
    candidate_state_sha256 = sha256_file(candidate_state_path)
    stages_root = root / "skill_runs" / "standard-manual-reroute" / "stages"
    stage_paths_before = sorted(stages_root.iterdir())
    with pytest.raises(RuntimeError, match="state hash changed"):
        resume_standard_asset_cycle(
            "skillmanualreroute",
            "standard-manual-reroute",
            reroute_candidate_to_manual_guarded=True,
            candidate_state_sha256="0" * 64,
            reroute_reason="The candidate envelope cannot edit custom-mesh payloads.",
        )
    assert sorted(stages_root.iterdir()) == stage_paths_before

    rerouted = resume_standard_asset_cycle(
        "skillmanualreroute",
        "standard-manual-reroute",
        max_host_steps=1,
        max_stage_transitions=1,
        reroute_candidate_to_manual_guarded=True,
        candidate_state_sha256=candidate_state_sha256,
        reroute_reason="The candidate envelope cannot edit custom-mesh payloads.",
    )
    assert rerouted["status"] == "waiting_for_agent"
    assert len(rerouted["state"]["stage_bindings"]) == 2
    cancelled = WorkflowState.model_validate_json(candidate_state_path.read_text(encoding="utf-8"))
    assert cancelled.status == "cancelled"
    successor_artifact = rerouted["state"]["stage_bindings"][1]
    successor = StandardCompositeStageBinding.model_validate_json(
        (root / successor_artifact["path"]).read_text(encoding="utf-8")
    )
    assert successor.technical_reroute is not None
    assert successor.technical_reroute.source_stage_binding == SkillArtifact.model_validate(
        initial_binding_artifact
    )
    assert successor.technical_reroute.user_approval_requested is False
    successor_plan = WorkflowPlan.model_validate_json(
        (root / successor.workflow_plan.path).read_text(encoding="utf-8")
    )
    successor_request = json.loads(
        (root / "workflows" / successor_plan.workflow_id / "request.json").read_text(
            encoding="utf-8"
        )
    )
    assert successor_request["revision_strategy"] == "manual_guarded"
    trace = get_skill_execution_trace("skillmanualreroute", "standard-manual-reroute")
    assert trace["status"] == "valid"
    assert [receipt["outcome"] for receipt in trace["receipts"]] == [
        "waiting_for_agent",
        "cancelled",
        "waiting_for_agent",
    ]


def test_standard_reroutes_material_blocked_candidate_and_records_manual_apply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve nonpromotable evaluation and count only its approved manual apply."""

    original_resume = skill_service.resume_workflow
    job_id = "skillqualitymaterialreroute"
    run_id = "standard-quality-material-reroute"
    root, waiting = _prepare_full_cycle_quality_boundary(
        monkeypatch,
        tmp_path,
        job_id=job_id,
        run_id=run_id,
        max_qa_revision_iterations=1,
        stage_policy="force_all",
    )
    waiting_state = StandardCompositeRunState.model_validate(waiting["state"])
    quality_request = waiting_state.current_quality_disposition_request
    assert quality_request is not None
    skill_service._record_standard_quality_disposition(
        job_id,
        run_id,
        disposition="needs_revision",
        request_fingerprint=quality_request.sha256,
        user_note="Use only the exact remaining direct-reference correction.",
    )
    monkeypatch.setattr(skill_service, "resume_workflow", original_resume)
    candidate_waiting = run_standard_asset_cycle(
        job_id,
        run_id,
        max_host_steps=1,
        max_stage_transitions=1,
    )
    candidate_binding_artifact = candidate_waiting["state"]["current_stage_binding"]
    candidate_binding = StandardCompositeStageBinding.model_validate_json(
        (root / candidate_binding_artifact["path"]).read_text(encoding="utf-8")
    )
    candidate_root = root / "workflows" / candidate_binding.workflow_id
    candidate_state_path = candidate_root / "state.json"
    candidate_plan = WorkflowPlan.model_validate_json(
        (candidate_root / "plan.json").read_text(encoding="utf-8")
    )
    candidate_request = json.loads(
        (candidate_root / "request.json").read_text(encoding="utf-8")
    )
    evaluation_plan = next(
        item for item in candidate_plan.steps if item.step_id == "revision.evaluate"
    )
    trial_id = str(evaluation_plan.parameters["trial_id"])
    candidate_revision_path = root / str(
        evaluation_plan.parameters["revision_plan_path"]
    )
    baseline_sha256 = sha256_file(root / "analysis" / "scene_spec.json")
    candidate_revision = RevisionPlan(
        job_id=job_id,
        base_spec_sha256=baseline_sha256,
        request="Scale only the exact direct-reference body candidate.",
        operations=[
            RevisionOperation(
                op="set",
                target_type="object",
                target_id="body",
                path=["transform", "scale"],
                value=[1.05, 1.05, 1.05],
                reason="Match the exact direct-reference silhouette candidate.",
            )
        ],
        acceptance_criteria=["Direct silhouette improves without ID changes."],
    )
    candidate_revision_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_revision_path.write_text(
        candidate_revision.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    trial_root = root / "qa" / "candidate_reviews" / trial_id
    trial_root.mkdir(parents=True, exist_ok=True)
    decision_path = trial_root / "decision_manifest.json"
    decision_path.write_text("{}\n", encoding="utf-8")
    (trial_root / "candidate_review_report.pdf").write_bytes(b"synthetic-pdf")
    (trial_root / "candidate_review_report.manifest.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    evaluated_input_fingerprint = "b" * 64
    fake_decision = SimpleNamespace(
        job_id=job_id,
        workflow_id=candidate_binding.workflow_id,
        trial_id=trial_id,
        input_fingerprint=evaluated_input_fingerprint,
        revision_plan=SimpleNamespace(
            path=candidate_revision_path.relative_to(root).as_posix(),
            sha256=sha256_file(candidate_revision_path),
        ),
        source_hashes={"analysis/scene_spec.json": baseline_sha256},
        baseline_scene_spec=SimpleNamespace(sha256=baseline_sha256),
        scores=SimpleNamespace(
            direct_score_delta=0.05,
            minimum_direct_improvement=0.001,
            silhouette_delta=0.04,
        ),
        status="not_improved",
        promotable=False,
        blockers=[
            skill_service._CANDIDATE_IMPROVEMENT_REASON,
            skill_service._SURFACE_DETAIL_BLOCKER_PREFIX
            + "uv_layout_sha256 differs from the current parent UVMap fingerprint",
        ],
    )

    def publish_material_blocked_evaluation(
        selected_job_id: str,
        selected_workflow_id: str,
        *,
        max_host_steps: int,
        retry_failed: bool,
    ) -> WorkflowState:
        """Publish one exact evaluated candidate state without a promotion approval."""

        if selected_workflow_id != candidate_binding.workflow_id:
            return original_resume(
                selected_job_id,
                selected_workflow_id,
                max_host_steps=max_host_steps,
                retry_failed=retry_failed,
            )
        current = WorkflowState.model_validate_json(
            candidate_state_path.read_text(encoding="utf-8")
        )
        updated_steps = []
        for item in current.steps:
            artifacts = item.artifacts
            if item.step_id == "revision.author":
                artifacts = [
                    artifact.model_copy(
                        update={
                            "sha256": sha256_file(candidate_revision_path),
                            "integrity": "valid",
                            "currency": "current",
                            "verification": "partially_verified",
                            "reason": "Synthetic exact candidate plan.",
                        }
                    )
                    for artifact in artifacts
                ]
                updated_steps.append(
                    item.model_copy(
                        update={
                            "status": "complete",
                            "completion_fingerprint": "a" * 64,
                            "artifacts": artifacts,
                            "completed_at": datetime.now(UTC),
                        }
                    )
                )
                continue
            if item.step_id == "revision.evaluate":
                artifacts = [
                    artifact.model_copy(
                        update={
                            "sha256": sha256_file(root / artifact.path),
                            "integrity": "valid",
                            "currency": "current",
                            "verification": "partially_verified",
                            "reason": "Synthetic exact candidate evaluation.",
                        }
                    )
                    for artifact in artifacts
                ]
                updated_steps.append(
                    item.model_copy(
                        update={
                            "status": "complete",
                            "input_fingerprint": evaluated_input_fingerprint,
                            "completion_fingerprint": "c" * 64,
                            "attempt_count": 1,
                            "artifacts": artifacts,
                            "completed_at": datetime.now(UTC),
                        }
                    )
                )
                continue
            if item.step_id == "revision.promotion_approval":
                updated_steps.append(
                    item.model_copy(
                        update={
                            "status": "waiting_for_approval",
                            "input_fingerprint": "d" * 64,
                        }
                    )
                )
                continue
            updated_steps.append(item)
        evaluated = current.model_copy(
            update={
                "status": "waiting_for_approval",
                "milestone": "qa_review",
                "current_step_id": "revision.promotion_approval",
                "steps": updated_steps,
                "next_action": "Do not approve the nonpromotable candidate.",
                "waiting_gate": "visual_revision",
                "updated_at": datetime.now(UTC),
            }
        )
        candidate_state_path.write_text(
            evaluated.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return evaluated

    monkeypatch.setattr(
        skill_service,
        "validate_candidate_review_decision",
        lambda *_args, **_kwargs: fake_decision,
    )
    monkeypatch.setattr(
        skill_service,
        "resume_workflow",
        publish_material_blocked_evaluation,
    )
    evaluated = run_standard_asset_cycle(
        job_id,
        run_id,
        max_host_steps=1,
        max_stage_transitions=1,
    )
    assert evaluated["status"] == "waiting_for_approval"
    evaluated_state_sha256 = sha256_file(candidate_state_path)
    rerouted = resume_standard_asset_cycle(
        job_id,
        run_id,
        max_host_steps=1,
        max_stage_transitions=1,
        reroute_candidate_to_manual_guarded=True,
        candidate_state_sha256=evaluated_state_sha256,
        reroute_reason=(
            "Exact visual improvement invalidates authored V0.5 spatial bindings and "
            "requires fresh material authoring after guarded apply."
        ),
    )
    manual_binding_artifact = rerouted["state"]["current_stage_binding"]
    manual_binding = StandardCompositeStageBinding.model_validate_json(
        (root / manual_binding_artifact["path"]).read_text(encoding="utf-8")
    )
    assert manual_binding.created_reason.startswith(
        skill_service._QUALITY_REVISION_MANUAL_REASON_PREFIX
    )
    manual_root = root / "workflows" / manual_binding.workflow_id
    manual_request = json.loads(
        (manual_root / "request.json").read_text(encoding="utf-8")
    )
    assert manual_request["raw_request"] == candidate_request["raw_request"]
    assert not (trial_root / "promotion_approval.json").exists()
    manual_plan = WorkflowPlan.model_validate_json(
        (manual_root / "plan.json").read_text(encoding="utf-8")
    )
    assert manual_plan.intent == "revise_asset"
    manual_state_path = manual_root / "state.json"
    manual_revision_path = root / "analysis" / "revision_plan.json"
    manual_revision_path.write_text(
        candidate_revision.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    result_scene_bytes = (
        json.dumps(
            {
                "objects": [
                    {
                        "id": "body",
                        "material_id": "paint",
                        "transform": {"scale": [1.05, 1.05, 1.05]},
                    }
                ]
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()
    scene_path = root / "analysis" / "scene_spec.json"
    scene_path.write_bytes(result_scene_bytes)
    result_scene_sha256 = sha256_file(scene_path)
    application = {
        "ok": True,
        "job_id": job_id,
        "request": candidate_revision.request,
        "base_spec_sha256": baseline_sha256,
        "result_spec_sha256": result_scene_sha256,
        "changes": [
            {
                "op": "set",
                "target_type": "object",
                "target_id": "body",
                "path": ["transform", "scale"],
                "before": [1.0, 1.0, 1.0],
                "after": [1.05, 1.05, 1.05],
                "reason": "Match the exact direct-reference silhouette candidate.",
            }
        ],
        "acceptance_criteria": candidate_revision.acceptance_criteria,
        "assumptions": [],
    }
    approval_fingerprint = "e" * 64
    approval_id = "approval-manual-quality-reroute"
    approval_root = manual_root / "approvals"
    approval_root.mkdir(parents=True, exist_ok=True)
    (approval_root / "revision.approval.json").write_text(
        WorkflowApproval(
            approval_id=approval_id,
            workflow_id=manual_binding.workflow_id,
            job_id=job_id,
            step_id="revision.approval",
            gate="detailed_geometry",
            plan_sha256=sha256_file(manual_root / "plan.json"),
            artifact_fingerprint=approval_fingerprint,
            approval_note="Approve only the exact direct-reference scale correction.",
            approved_at=datetime.now(UTC),
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )

    def complete_manual_guarded_apply(
        selected_job_id: str,
        selected_workflow_id: str,
        *,
        max_host_steps: int,
        retry_failed: bool,
    ) -> WorkflowState:
        """Publish exact approved manual apply snapshots for composite continuation."""

        if selected_workflow_id != manual_binding.workflow_id:
            return original_resume(
                selected_job_id,
                selected_workflow_id,
                max_host_steps=max_host_steps,
                retry_failed=retry_failed,
            )
        current = WorkflowState.model_validate_json(
            manual_state_path.read_text(encoding="utf-8")
        )
        completed_steps = []
        for item in current.steps:
            artifacts = item.artifacts
            input_fingerprint = item.input_fingerprint or "f" * 64
            approval = item.approval_id
            attempt_count = item.attempt_count
            if item.step_id == "revision.author":
                artifacts = [
                    artifact.model_copy(
                        update={
                            "sha256": sha256_file(manual_revision_path),
                            "integrity": "valid",
                            "currency": "current",
                            "verification": "partially_verified",
                            "reason": "Synthetic exact manual RevisionPlan.",
                        }
                    )
                    for artifact in artifacts
                ]
            elif item.step_id == "revision.approval":
                input_fingerprint = approval_fingerprint
                approval = approval_id
            elif item.step_id == "revision.apply":
                published = []
                for artifact in artifacts:
                    output = root / artifact.path
                    output.parent.mkdir(parents=True, exist_ok=True)
                    if artifact.artifact_id == "revision.scene_spec":
                        output.write_bytes(result_scene_bytes)
                    elif artifact.artifact_id == "revision.diff":
                        output.write_text(
                            json.dumps(application, indent=2) + "\n",
                            encoding="utf-8",
                        )
                    published.append(
                        artifact.model_copy(
                            update={
                                "sha256": sha256_file(output),
                                "integrity": "valid",
                                "currency": "current",
                                "verification": "partially_verified",
                                "reason": "Synthetic exact guarded apply snapshot.",
                            }
                        )
                    )
                artifacts = published
                attempt_count = 1
            completed_steps.append(
                item.model_copy(
                    update={
                        "status": "complete",
                        "input_fingerprint": input_fingerprint,
                        "completion_fingerprint": "9" * 64,
                        "attempt_count": attempt_count,
                        "artifacts": artifacts,
                        "approval_id": approval,
                        "completed_at": datetime.now(UTC),
                        "error": None,
                        "reason_code": None,
                    }
                )
            )
        completed = current.model_copy(
            update={
                "status": "completed",
                "milestone": "completed",
                "current_step_id": None,
                "steps": completed_steps,
                "next_action": None,
                "waiting_gate": None,
                "updated_at": datetime.now(UTC),
            }
        )
        manual_state_path.write_text(
            completed.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return completed

    monkeypatch.setattr(skill_service, "resume_workflow", complete_manual_guarded_apply)
    continued = run_standard_asset_cycle(
        job_id,
        run_id,
        max_host_steps=1,
        max_stage_transitions=1,
    )
    continued_state = StandardCompositeRunState.model_validate(continued["state"])
    assert continued_state.qa_revision_iterations == 1
    assert len(continued_state.qa_revision_evidence) == 1
    continuation = GuardedRevisionContinuation.model_validate_json(
        (root / continued_state.qa_revision_evidence[0].path).read_text(encoding="utf-8")
    )
    assert continuation.application_status == "applied_unverified"
    assert continuation.convergence_report is None
    assert continuation.baseline_scene_spec_sha256 == baseline_sha256
    assert continuation.result_scene_spec_sha256 == result_scene_sha256
    assert continuation.revision_plan.path.startswith(
        f"skill_runs/{run_id}/revisions/evidence/"
    )
    next_binding = StandardCompositeStageBinding.model_validate_json(
        (root / continued_state.current_stage_binding.path).read_text(encoding="utf-8")
    )
    assert next_binding.stage_kind == "material"
    assert "fresh V0.5" in next_binding.created_reason


def test_standard_reroutes_unstarted_material_after_rejected_geometry_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cancel untouched V0.5 work and plan one bounded V0.4 correction after rejection."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    job_id = "skillgeometryreviewreroute"
    run_id = "standard-geometry-review-reroute"
    plan_workflow(
        "Create the initial bounded reference asset.",
        job_id=job_id,
        reference_path=_image(tmp_path / "geometry-review-reroute.png"),
    )
    root = workspace / job_id
    _write_material_projection(root, material_id="paint")
    _write_authored_modeling_plan(root, job_id)
    planned = plan_standard_asset_cycle(
        "Continue only after rejected geometry is corrected.",
        goal="full_cycle_to_package",
        job_id=job_id,
        stage_policy="force_all",
        revision_strategy="manual_guarded",
        run_id=run_id,
    )
    geometry_workflow_id = planned["current_workflow"]["workflow_id"]
    geometry_state_path = root / "workflows" / geometry_workflow_id / "state.json"
    original_resume = skill_service.resume_workflow

    def complete_initial_geometry(
        selected_job_id: str,
        selected_workflow_id: str,
        *,
        max_host_steps: int,
        retry_failed: bool,
    ) -> WorkflowState:
        """Complete only the synthetic predecessor and delegate its guarded successor."""

        assert selected_job_id == job_id
        assert max_host_steps >= 1
        if selected_workflow_id != geometry_workflow_id:
            return original_resume(
                selected_job_id,
                selected_workflow_id,
                max_host_steps=max_host_steps,
                retry_failed=retry_failed,
            )
        current = WorkflowState.model_validate_json(
            geometry_state_path.read_text(encoding="utf-8")
        )
        completed = current.model_copy(
            update={
                "status": "completed",
                "current_step_id": None,
                "steps": [
                    item.model_copy(
                        update={
                            "status": "complete",
                            "completion_fingerprint": "a" * 64,
                            "completed_at": datetime.now(UTC),
                        }
                    )
                    for item in current.steps
                ],
                "next_action": None,
                "updated_at": datetime.now(UTC),
            }
        )
        geometry_state_path.write_text(
            completed.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return completed

    monkeypatch.setattr(skill_service, "resume_workflow", complete_initial_geometry)
    monkeypatch.setattr(
        skill_service,
        "_completed_geometry_visual_review",
        lambda *_args: None,
    )
    misrouted = run_standard_asset_cycle(
        job_id,
        run_id,
        max_host_steps=1,
        max_stage_transitions=1,
    )
    assert misrouted["current_workflow"]["state"]["status"] == "planned"
    material_workflow_id = misrouted["current_workflow"]["workflow_id"]
    material_state_path = root / "workflows" / material_workflow_id / "state.json"
    material_state_sha256 = sha256_file(material_state_path)
    rejected_review = GeometryMultiviewVisualReview(
        job_id=job_id,
        run_id="v08-rejected-geometry",
        plan_sha256="b" * 64,
        render_manifest_sha256="c" * 64,
        structural_report_sha256="d" * 64,
        reviewed_view_ids=("front", "right", "top", "rear", "oblique"),
        reviewed_pass_kinds=("beauty", "wireframe"),
        outcome="v04_redesign_review_required",
        v04_reentry="required",
        findings=[
            {
                "finding_id": "visual.topology.bridge",
                "issue_type": "topology_artifact",
                "severity": "error",
                "view_ids": ["front", "oblique"],
                "target_ids": ["body"],
                "description": "A synthetic bridge remains visible across views.",
                "recommended_v04_action": "redesign_review",
            }
        ],
        reviewed_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        skill_service,
        "_completed_geometry_visual_review",
        lambda *_args: rejected_review,
    )

    rerouted = run_standard_asset_cycle(
        job_id,
        run_id,
        max_host_steps=1,
        max_stage_transitions=1,
    )

    assert rerouted["status"] == "waiting_for_agent"
    assert len(rerouted["state"]["stage_bindings"]) == 3
    cancelled = WorkflowState.model_validate_json(
        material_state_path.read_text(encoding="utf-8")
    )
    assert cancelled.status == "cancelled"
    assert all(item.attempt_count == 0 for item in cancelled.steps)
    assert sha256_file(material_state_path) != material_state_sha256
    successor_artifact = rerouted["state"]["stage_bindings"][-1]
    successor = StandardCompositeStageBinding.model_validate_json(
        (root / successor_artifact["path"]).read_text(encoding="utf-8")
    )
    assert successor.stage_kind == "geometry"
    assert successor.technical_reroute is not None
    assert successor.created_reason.startswith(
        skill_service._GEOMETRY_REENTRY_REASON_PREFIX
    )
    successor_plan = WorkflowPlan.model_validate_json(
        (root / successor.workflow_plan.path).read_text(encoding="utf-8")
    )
    successor_request = json.loads(
        (root / "workflows" / successor_plan.workflow_id / "request.json").read_text(
            encoding="utf-8"
        )
    )
    assert successor_request["revision_strategy"] == "manual_guarded"
    trace = get_skill_execution_trace(job_id, run_id)
    assert trace["status"] == "valid"
    assert [receipt["outcome"] for receipt in trace["receipts"]] == [
        "completed",
        "cancelled",
        "waiting_for_agent",
    ]


def test_skill_snapshot_tampering_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a changed run-owned SKILL.md snapshot without consulting live sources."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    plan_standard_asset_cycle(
        "정적 소품을 QA까지 제작해줘",
        goal="new_asset_to_qa",
        job_id="skilltamper",
        reference_path=_image(tmp_path / "tamper.png"),
        run_id="standard-skill-tamper",
    )
    snapshot = (
        workspace
        / "skilltamper"
        / "skill_runs"
        / "standard-skill-tamper"
        / "snapshots"
        / "skills"
        / "standard-asset-cycle"
        / "SKILL.md"
    )
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="skill snapshot changed"):
        get_standard_asset_cycle_status("skilltamper", "standard-skill-tamper")


def test_live_skill_change_does_not_change_a_snapshotted_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Resume from run-owned definitions after a later live skill body change."""

    workspace = tmp_path / "workspaces"
    fake_repo = tmp_path / "repo"
    shutil.copytree(
        Path(__file__).resolve().parents[1] / ".agents" / "skills",
        fake_repo / ".agents" / "skills",
    )
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(
        skill_service,
        "get_settings",
        lambda: SimpleNamespace(repo_root=fake_repo),
    )
    plan_standard_asset_cycle(
        "정적 소품을 QA까지 제작해줘",
        goal="new_asset_to_qa",
        job_id="skilllivechange",
        reference_path=_image(tmp_path / "live-change.png"),
        run_id="standard-skill-live-change",
    )
    live = fake_repo / ".agents" / "skills" / "standard-asset-cycle" / "SKILL.md"
    live.write_text(live.read_text(encoding="utf-8") + "\nLive revision.\n", encoding="utf-8")
    resumed = run_standard_asset_cycle(
        "skilllivechange",
        "standard-skill-live-change",
        max_host_steps=4,
    )
    assert resumed["status"] == "waiting_for_agent"
    assert get_skill_execution_trace(
        "skilllivechange", "standard-skill-live-change"
    )["status"] == "valid"


def test_bundle_mutation_breaks_its_plan_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a self-consistent-looking bundle after its immutable plan was published."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    plan_standard_asset_cycle(
        "정적 소품을 QA까지 제작해줘",
        goal="new_asset_to_qa",
        job_id="skillbundletamper",
        reference_path=_image(tmp_path / "bundle-tamper.png"),
        run_id="standard-skill-bundle-tamper",
    )
    bundle_path = (
        workspace
        / "skillbundletamper"
        / "skill_runs"
        / "standard-skill-bundle-tamper"
        / "bundle.json"
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["created_at"] = "2030-01-01T00:00:00Z"
    bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exact bundle"):
        get_standard_asset_cycle_status(
            "skillbundletamper", "standard-skill-bundle-tamper"
        )


def test_standard_cancellation_appends_an_exact_trace_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Record explicit composite cancellation with exact before/after V0.8 evidence."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    plan_standard_asset_cycle(
        "이 레퍼런스로 정적 소품을 QA까지 제작해줘",
        goal="new_asset_to_qa",
        job_id="skillcancel",
        reference_path=_image(tmp_path / "cancel.png"),
        run_id="standard-skill-cancel",
    )
    cancelled = cancel_standard_asset_cycle(
        "skillcancel",
        "standard-skill-cancel",
        reason="사용자가 현재 복합 작업 중단을 요청함",
    )
    assert cancelled["status"] == "cancelled"
    trace = get_skill_execution_trace("skillcancel", "standard-skill-cancel")
    assert len(trace["routes"]) == 1
    assert len(trace["receipts"]) == 1
    assert trace["receipts"][0]["before"]["status"] == "planned"
    assert trace["receipts"][0]["after"]["status"] == "cancelled"
    assert trace["receipts"][0]["outcome"] == "cancelled"


def test_v09_audit_validates_skill_runs_and_detects_snapshot_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Surface corrupt skill evidence through the existing read-only V0.9 audit."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    plan_standard_asset_cycle(
        "정적 소품을 QA까지 제작해줘",
        goal="new_asset_to_qa",
        job_id="skillaudit",
        reference_path=_image(tmp_path / "audit.png"),
        run_id="standard-skill-audit",
    )
    job_root = workspace / "skillaudit"
    assert _audit_skill_runs(job_root, "skillaudit") == []
    snapshot = (
        job_root
        / "skill_runs"
        / "standard-skill-audit"
        / "snapshots"
        / "skills"
        / "standard-asset-cycle"
        / "SKILL.md"
    )
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    findings = _audit_skill_runs(job_root, "skillaudit")
    assert [item.code for item in findings] == ["SKILL_RUN_INVALID"]


def test_aq_skill_plan_remains_disabled_without_explicit_opt_in(tmp_path: Path) -> None:
    """Fail before creating an AQ job when the experimental adapter opt-in is absent."""

    with pytest.raises(PermissionError, match="disabled_experimental"):
        plan_aq_one_prompt_skill(
            "이 소품을 자율 제작해줘",
            reference_path=_image(tmp_path / "aq.png"),
            target_subject="prop",
            requested_delivery_profiles=["review_only"],
            explicit_autonomy_delegation_observed=True,
        )


def test_aq_skill_plan_and_cancel_preserve_disabled_profile_and_receipt_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exercise the explicit experimental adapter without activating its AQ profile."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    planned = plan_aq_one_prompt_skill(
        "이 소품을 현재 작업 안에서 자율 제작해줘",
        reference_path=_image(tmp_path / "aq-cancel.png"),
        target_subject="isolated static prop",
        requested_delivery_profiles=["review_only"],
        explicit_autonomy_delegation_observed=True,
        job_id="skill-aq-cancel",
        experimental_opt_in=True,
        run_id="aq-skill-cancel",
    )
    assert planned["profile_status"] == "disabled_experimental"
    cancelled = cancel_aq_one_prompt_skill(
        "skill-aq-cancel",
        "aq-skill-cancel",
        reason="bounded adapter cancellation test",
        experimental_opt_in=True,
    )
    assert cancelled["status"] == "terminal"
    assert cancelled["profile_status"] == "disabled_experimental"
    assert cancelled["terminal"]["terminal_type"] == "cancelled"
    assert cancelled["terminal"]["campaign_terminal_candidate"] is False
    trace = get_skill_execution_trace("skill-aq-cancel", "aq-skill-cancel")
    assert len(trace["routes"]) == 1
    assert len(trace["receipts"]) == 1
    assert trace["receipts"][0]["outcome"] == "cancelled"
    repeated = run_aq_one_prompt_skill(
        "skill-aq-cancel",
        "aq-skill-cancel",
        experimental_opt_in=True,
    )
    assert repeated["status"] == "terminal"
    assert len(
        get_skill_execution_trace("skill-aq-cancel", "aq-skill-cancel")["receipts"]
    ) == 1


@pytest.mark.parametrize(
    ("state_status", "route_key"),
    [
        ("review_required", "aq.quality.review_terminal"),
        ("blocked", "aq.recovery.blocked_terminal"),
        ("failed", "aq.recovery.failed_terminal"),
        ("cancelled", "aq.recovery.cancelled_terminal"),
        ("completed", "aq.delivery.completed_terminal"),
    ],
)
def test_aq_terminal_routes_are_unique(
    tmp_path: Path,
    state_status: str,
    route_key: str,
) -> None:
    """Map terminal meaning to quality, delivery, or recovery without ambiguity."""

    status = {
        "status": "terminal",
        "base_autonomy": {
            "state": {
                "status": state_status,
                "next_action": "none",
                "provenance": [],
            },
            "state_artifact": {"path": "unused.json", "sha256": "a" * 64},
        },
    }
    selected, _reason = _aq_route_key(tmp_path, status)
    assert selected == route_key


def test_aq_adapter_records_executor_failure_without_orphaning_its_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Close a routed adapter exception with one failed receipt for safe retry."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    plan_aq_one_prompt_skill(
        "이 소품을 현재 작업 안에서 자율 제작해줘",
        reference_path=_image(tmp_path / "aq-failure.png"),
        target_subject="isolated static prop",
        requested_delivery_profiles=["review_only"],
        explicit_autonomy_delegation_observed=True,
        job_id="skill-aq-failure",
        experimental_opt_in=True,
        run_id="aq-skill-failure",
    )

    def _raise_executor_failure(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Inject one bounded adapter-visible executor failure."""

        raise ValueError("injected executor failure")

    monkeypatch.setattr(skill_service, "run_one_prompt", _raise_executor_failure)
    with pytest.raises(ValueError, match="injected executor failure"):
        run_aq_one_prompt_skill(
            "skill-aq-failure",
            "aq-skill-failure",
            experimental_opt_in=True,
        )
    trace = get_skill_execution_trace("skill-aq-failure", "aq-skill-failure")
    assert len(trace["routes"]) == 1
    assert len(trace["receipts"]) == 1
    assert trace["receipts"][0]["outcome"] == "failed"


def test_aq_adapter_recovers_one_interrupted_pending_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Hash-validate and receipt one route left by a process interruption."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    plan_aq_one_prompt_skill(
        "이 소품을 현재 작업 안에서 자율 제작해줘",
        reference_path=_image(tmp_path / "aq-interrupt.png"),
        target_subject="isolated static prop",
        requested_delivery_profiles=["review_only"],
        explicit_autonomy_delegation_observed=True,
        job_id="skill-aq-interrupt",
        experimental_opt_in=True,
        run_id="aq-skill-interrupt",
    )

    def _interrupt_executor(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Interrupt after route publication and before AQ state advancement."""

        raise KeyboardInterrupt("injected adapter interruption")

    monkeypatch.setattr(skill_service, "run_one_prompt", _interrupt_executor)
    with pytest.raises(KeyboardInterrupt, match="injected adapter interruption"):
        run_aq_one_prompt_skill(
            "skill-aq-interrupt",
            "aq-skill-interrupt",
            experimental_opt_in=True,
        )
    recovered = run_aq_one_prompt_skill(
        "skill-aq-interrupt",
        "aq-skill-interrupt",
        experimental_opt_in=True,
    )
    assert recovered["recovered_pending_route"] is True
    trace = get_skill_execution_trace("skill-aq-interrupt", "aq-skill-interrupt")
    assert len(trace["routes"]) == 1
    assert len(trace["receipts"]) == 1
    assert trace["receipts"][0]["outcome"] == "failed"


def test_aq_adapter_reconciles_an_externally_terminalized_one_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Project an exact terminal created outside the adapter into its receipt chain."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    planned = plan_aq_one_prompt_skill(
        "이 소품을 현재 작업 안에서 자율 제작해줘",
        reference_path=_image(tmp_path / "aq-terminal.png"),
        target_subject="isolated static prop",
        requested_delivery_profiles=["review_only"],
        explicit_autonomy_delegation_observed=True,
        job_id="skill-aq-terminal",
        experimental_opt_in=True,
        run_id="aq-skill-terminal",
    )
    skill_service.cancel_one_prompt(
        "skill-aq-terminal",
        str(planned["session_id"]),
        reason="external exact terminal fixture",
        allow_disabled_experimental=True,
    )

    reconciled = run_aq_one_prompt_skill(
        "skill-aq-terminal",
        "aq-skill-terminal",
        experimental_opt_in=True,
    )
    assert reconciled["status"] == "terminal"
    assert reconciled["one_prompt"]["status"] == "terminal"
    assert reconciled["terminal"]["terminal_type"] == "cancelled"
    trace = get_skill_execution_trace("skill-aq-terminal", "aq-skill-terminal")
    assert trace["receipts"][-1]["outcome"] == "cancelled"


def test_aq_failed_terminal_reconciliation_requires_exact_recovery_evidence() -> None:
    """Reject an empty recovery projection before touching any historical AQ run."""

    with pytest.raises(ValueError, match="requires recovery package acceptance"):
        reconcile_aq_one_prompt_skill_terminal(
            "missing-job",
            "missing-run",
            recovery_package_acceptance_paths=[],
            experimental_opt_in=True,
        )
