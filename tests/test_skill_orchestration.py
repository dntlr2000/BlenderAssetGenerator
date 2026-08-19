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
from codex_blender_modeler.revision import RevisionOperation, RevisionPlan
from codex_blender_modeler.skill_orchestration import (
    cancel_aq_one_prompt_skill,
    cancel_standard_asset_cycle,
    get_skill_catalog,
    get_skill_execution_trace,
    get_standard_asset_cycle_status,
    plan_aq_one_prompt_skill,
    plan_standard_asset_cycle,
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
