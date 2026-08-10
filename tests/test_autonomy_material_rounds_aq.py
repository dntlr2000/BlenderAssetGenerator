"""Focused host tests for bounded Autonomous Quality V0.5 material rounds."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_blender_modeler.autonomy.authorization import (
    artifact_for,
    authorize_policy_gate,
    create_root_authorization,
)
from codex_blender_modeler.autonomy.material_rounds import (
    create_material_candidate_policy_target,
    prepare_material_candidate_round,
    promote_material_candidate_to_workflow_authored,
)
from codex_blender_modeler.autonomy.models import AutonomyArtifact, BudgetUsage
from codex_blender_modeler.autonomy.profiles import (
    build_default_budget,
    build_profile_snapshot,
)
from codex_blender_modeler.materials.models import (
    MaterialPlan,
    MaterialPlanItem,
    ShaderRecipe,
)
from codex_blender_modeler.orchestration.models import (
    ArtifactRequirement,
    DestinationRequest,
    DestinationResolution,
    WorkflowPlan,
    WorkflowState,
    WorkflowStep,
    WorkflowStepState,
)
from codex_blender_modeler.production.models import DelegatedWorkAssignment


def _write(path: Path, value: object) -> None:
    """Write deterministic JSON fixture evidence below one temporary job root."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _fixture(root: Path) -> dict[str, object]:
    """Create one exact material.author boundary with a strict V0.5 scaffold."""

    now = datetime(2026, 8, 10, tzinfo=UTC)
    root.mkdir(parents=True)
    scene = {
        "schema_version": "0.2.0",
        "job_id": "aq_material_prop",
        "materials": [
            {
                "id": "mat.body",
                "name": "Body",
                "shader": "principled",
                "base_color": [0.2, 0.35, 0.5, 1.0],
                "roughness": 0.42,
                "metallic": 0.1,
            }
        ],
        "objects": [{"id": "prop.body", "material_id": "mat.body"}],
    }
    _write(root / "analysis" / "scene_spec.json", scene)
    authored_root = root / "workflows" / "wf-aq-material" / "artifacts" / "m" / "authored"
    recipe_path = authored_root / "recipes" / "body.json"
    recipe = ShaderRecipe(material_id="mat.body")
    _write(recipe_path, recipe)
    plan = MaterialPlan(
        job_id="aq_material_prop",
        stage="scaffold",
        surface_detail_binding_policy="spatial_v1",
        materials=[
            MaterialPlanItem(
                material_id="mat.body",
                label="Body",
                texture_strategy="procedural",
                shader_recipe=recipe_path.relative_to(root).as_posix(),
            )
        ],
    )
    authored_plan_path = authored_root / "material_plan.json"
    _write(authored_plan_path, plan)
    destination = DestinationResolution(
        requested=DestinationRequest(kind="engine_neutral"),
        status="unsupported",
        reason="Portable package boundary only.",
    )
    workflow = WorkflowPlan(
        workflow_id="wf-aq-material",
        job_id="aq_material_prop",
        request_sha256="1" * 64,
        routing_sha256="2" * 64,
        intent="new_asset",
        scope="full",
        reference_content_scope="primary_object_only",
        target_subject="small static prop",
        execution_policy="standard",
        destination=destination,
        steps=[
            WorkflowStep(
                step_id="material.author",
                title="Author material",
                phase="material",
                execution_mode="agent",
                outputs=[
                    ArtifactRequirement(
                        artifact_id="material.plan.authored",
                        path=authored_root.relative_to(root).as_posix(),
                        lifecycle="immutable_run",
                        acceptance="nonempty_directory",
                    )
                ],
                parameters={
                    "candidate_plan_path": authored_plan_path.relative_to(root).as_posix(),
                },
            )
        ],
        terminal_step_id="material.author",
        created_at=now,
    )
    workflow_path = root / "workflows" / "wf-aq-material" / "plan.json"
    _write(workflow_path, workflow)
    plan_sha = hashlib.sha256(workflow_path.read_bytes()).hexdigest()
    input_fingerprint = "3" * 64
    state = WorkflowState(
        workflow_id="wf-aq-material",
        job_id="aq_material_prop",
        plan_sha256=plan_sha,
        request_sha256="1" * 64,
        reference_content_scope="primary_object_only",
        target_subject="small static prop",
        execution_policy="standard",
        status="waiting_for_agent",
        milestone="geometry_approved",
        current_step_id="material.author",
        steps=[
            WorkflowStepState(
                step_id="material.author",
                status="waiting_for_agent",
                input_fingerprint=input_fingerprint,
            )
        ],
        created_at=now,
        updated_at=now,
    )
    _write(root / "workflows" / "wf-aq-material" / "state.json", state)
    assignment = DelegatedWorkAssignment(
        assignment_id="assign-material-author",
        dispatch_id="dispatch-aq-material",
        controller_id="controller-aq-material",
        job_id="aq_material_prop",
        workflow_id="wf-aq-material",
        step_id="material.author",
        workflow_plan_sha256=plan_sha,
        input_fingerprint=input_fingerprint,
        advisory_role="material_reviewer",
        prompt="Author only the exact workflow-owned V0.5 material candidate.",
        controller_expected_outputs=[authored_root.relative_to(root).as_posix()],
        issued_at=now,
    )
    assignment_path = (
        root
        / "production"
        / "dispatches"
        / "dispatch-aq-material"
        / "assignment.json"
    )
    _write(assignment_path, assignment)
    session_root = root / "production" / "autonomy" / "aq-material-session"
    session_root.mkdir(parents=True)
    return {
        "now": now,
        "session_root": session_root,
        "assignment": artifact_for(root, assignment_path),
        "authored_plan_path": authored_plan_path,
        "recipe_path": recipe_path,
    }


def _policy(
    root: Path,
    fixture: dict[str, object],
    ranking: AutonomyArtifact,
    gate_target: AutonomyArtifact,
) -> AutonomyArtifact:
    """Issue one real exact PolicyAuthorization for the selected material ranking."""

    now = fixture["now"]
    session_root = fixture["session_root"]
    quality_path = session_root / "quality_gate_profile.json"
    _write(quality_path, {"quality": "fixture"})
    quality = artifact_for(root, quality_path)
    budget = build_default_budget(
        job_id="aq_material_prop",
        workflow_id="wf-aq-material",
        dispatch_id="dispatch-aq-material",
        source_artifact=quality,
        created_at=now,
    )
    budget_path = session_root / "budget.json"
    _write(budget_path, budget)
    budget_artifact = artifact_for(root, budget_path)
    profile = build_profile_snapshot(
        job_id="aq_material_prop",
        workflow_id="wf-aq-material",
        dispatch_id="dispatch-aq-material",
        budget=budget,
        budget_artifact=budget_artifact,
        quality_gate_profile=quality,
        created_at=now,
    )
    profile_path = session_root / "profile.json"
    _write(profile_path, profile)
    profile_artifact = artifact_for(root, profile_path)
    launch_path = root / "production" / "dispatches" / "dispatch-aq-material" / "launch.json"
    reference_path = root / "input" / "reference.png"
    launch_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    launch_path.write_bytes(b"launch")
    reference_path.write_bytes(b"reference")
    root_authorization = create_root_authorization(
        request_text="Create only this static prop and a portable GLB package.",
        job_id="aq_material_prop",
        workflow_id="wf-aq-material",
        dispatch_id="dispatch-aq-material",
        launch_or_binding=artifact_for(root, launch_path),
        primary_reference=artifact_for(root, reference_path),
        profile_artifact=profile_artifact,
        profile=profile,
        budget_artifact=budget_artifact,
        target_subject="small static prop",
        created_at=now,
    )
    root_path = session_root / "root_authorization.json"
    _write(root_path, root_authorization)
    root_artifact = artifact_for(root, root_path)
    grant = authorize_policy_gate(
        root_authorization=root_authorization,
        root_authorization_artifact=root_artifact,
        root_authorization_sha256=root_artifact.sha256,
        profile=profile,
        profile_artifact=profile_artifact,
        profile_sha256=profile_artifact.sha256,
        budget=budget,
        budget_artifact=budget_artifact,
        budget_sha256=budget_artifact.sha256,
        gate_kind="material_candidate_promotion",
        step_id="autonomy.material_candidate_promotion",
        workflow_input_fingerprint=ranking.sha256,
        gate_target=gate_target,
        target_artifact=ranking,
        budget_before=BudgetUsage(),
        budget_after=BudgetUsage(material_rounds=1, total_actions=1),
        previous_authorization_sha256=None,
        created_at=now,
    )
    grant_path = session_root / "policy_authorizations" / "material-round-01.json"
    _write(grant_path, grant)
    return artifact_for(root, grant_path)


def test_material_round_selects_exact_portable_candidate_with_measured_local_maps(
    tmp_path: Path,
) -> None:
    """Select a valid portable plan with hash-bound neutral image PBR evidence."""

    root = tmp_path / "job"
    fixture = _fixture(root)
    original = fixture["authored_plan_path"].read_bytes()
    ranking, ranking_artifact = prepare_material_candidate_round(
        root,
        fixture["session_root"],
        production_assignment=fixture["assignment"],
        candidate_limit=2,
    )
    assert len(ranking.candidate_evaluations) == 2
    assert ranking.material_quality_status == "passed"
    assert ranking.visual_comparison_performed is False
    assert fixture["authored_plan_path"].read_bytes() == original
    selected = MaterialPlan.model_validate_json(
        (root / ranking.selected_material_plan.path).read_text(encoding="utf-8")
    )
    assert selected.stage == "authored"
    assert selected.materials[0].export_profiles == ["blender_eevee", "gltf_pbr"]
    assert selected.materials[0].texture_strategy == "image"
    manifest = root / str(selected.materials[0].texture_manifest)
    assert manifest.is_file()
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert selected.materials[0].mapping.mode == "uv"
    assert selected.materials[0].mapping.uv_set == "UVMap"
    assert manifest_payload["uv_set"] == "UVMap"
    assert manifest_payload["provenance"]["provider"] == "cbm_autonomy_uniform_pbr"
    assert manifest_payload["surface_detail_ids"] == []
    assert manifest_payload["surface_detail_bindings"] == []
    common_source = (
        Path("src/codex_blender_modeler/blender_scripts/common.py")
        .read_text(encoding="utf-8")
    )
    assert 'provenance.get("provider") == "cbm_autonomy_uniform_pbr"' in common_source
    assert 'sampling_mode = "portable_uv_identity"' in common_source
    assert 'image_extension = "EXTEND"' in common_source
    assert set(manifest_payload["channels"]) == {
        "base_color",
        "roughness",
        "metallic",
        "normal",
        "height",
        "opacity",
        "emission",
    }

    reread, reread_artifact = prepare_material_candidate_round(
        root,
        fixture["session_root"],
        production_assignment=fixture["assignment"],
        candidate_limit=2,
    )
    assert reread == ranking
    assert reread_artifact == ranking_artifact


def test_second_material_round_binds_previous_selected_plan_without_promotion(
    tmp_path: Path,
) -> None:
    """Refine from the exact prior ranking while leaving V0.8 authored data untouched."""

    root = tmp_path / "job"
    fixture = _fixture(root)
    original = fixture["authored_plan_path"].read_bytes()
    first, first_artifact = prepare_material_candidate_round(
        root,
        fixture["session_root"],
        production_assignment=fixture["assignment"],
        candidate_limit=2,
        round_index=1,
    )
    second, second_artifact = prepare_material_candidate_round(
        root,
        fixture["session_root"],
        production_assignment=fixture["assignment"],
        candidate_limit=2,
        round_index=2,
        previous_ranking=first_artifact,
    )
    snapshot_path = root / second.round_input.path
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["previous_ranking"] == first_artifact.model_dump(mode="json")
    assert snapshot["baseline_material_plan"] == first.selected_material_plan.model_dump(
        mode="json"
    )
    assert second.round_id == "mr-02"
    assert second_artifact.path.endswith("mr/r02/ranking.json")
    assert fixture["authored_plan_path"].read_bytes() == original


def test_material_promotion_uses_policy_and_preserves_v08_authority(tmp_path: Path) -> None:
    """Place the selected plan only at material.author and leave canonical promotion to V0.8."""

    root = tmp_path / "job"
    fixture = _fixture(root)
    ranking, ranking_artifact = prepare_material_candidate_round(
        root,
        fixture["session_root"],
        production_assignment=fixture["assignment"],
        candidate_limit=2,
    )
    target = create_material_candidate_policy_target(
        root,
        fixture["session_root"],
        ranking_artifact=ranking_artifact,
        production_assignment=fixture["assignment"],
    )
    policy = _policy(root, fixture, ranking_artifact, target)
    receipt, receipt_artifact = promote_material_candidate_to_workflow_authored(
        root,
        fixture["session_root"],
        ranking_artifact=ranking_artifact,
        production_assignment=fixture["assignment"],
        policy_authorization_artifact=policy,
    )
    promoted = MaterialPlan.model_validate_json(
        fixture["authored_plan_path"].read_text(encoding="utf-8")
    )
    assert promoted.stage == "authored"
    assert hashlib.sha256(fixture["authored_plan_path"].read_bytes()).hexdigest() == (
        ranking.selected_material_plan.sha256
    )
    assert receipt.canonical_material_plan_written is False
    assert receipt.existing_v08_promotion_remains_authoritative is True
    assert not (root / "analysis" / "material_plan.json").exists()

    recovered, recovered_artifact = promote_material_candidate_to_workflow_authored(
        root,
        fixture["session_root"],
        ranking_artifact=ranking_artifact,
        production_assignment=fixture["assignment"],
        policy_authorization_artifact=policy,
    )
    assert recovered == receipt
    assert recovered_artifact == receipt_artifact


def test_material_promotion_rejects_unplanned_authored_plan_change(tmp_path: Path) -> None:
    """Fail closed when the V0.8 authored output changes after candidate evaluation."""

    root = tmp_path / "job"
    fixture = _fixture(root)
    _ranking, ranking_artifact = prepare_material_candidate_round(
        root,
        fixture["session_root"],
        production_assignment=fixture["assignment"],
        candidate_limit=2,
    )
    target = create_material_candidate_policy_target(
        root,
        fixture["session_root"],
        ranking_artifact=ranking_artifact,
        production_assignment=fixture["assignment"],
    )
    policy = _policy(root, fixture, ranking_artifact, target)
    fixture["authored_plan_path"].write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed outside"):
        promote_material_candidate_to_workflow_authored(
            root,
            fixture["session_root"],
            ranking_artifact=ranking_artifact,
            production_assignment=fixture["assignment"],
            policy_authorization_artifact=policy,
        )


def test_material_promotion_rejects_stale_source_recipe(tmp_path: Path) -> None:
    """Fail closed when an exact source recipe changes after the round snapshot."""

    root = tmp_path / "job"
    fixture = _fixture(root)
    _ranking, ranking_artifact = prepare_material_candidate_round(
        root,
        fixture["session_root"],
        production_assignment=fixture["assignment"],
        candidate_limit=2,
    )
    target = create_material_candidate_policy_target(
        root,
        fixture["session_root"],
        ranking_artifact=ranking_artifact,
        production_assignment=fixture["assignment"],
    )
    policy = _policy(root, fixture, ranking_artifact, target)
    fixture["recipe_path"].write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale or tampered"):
        promote_material_candidate_to_workflow_authored(
            root,
            fixture["session_root"],
            ranking_artifact=ranking_artifact,
            production_assignment=fixture["assignment"],
            policy_authorization_artifact=policy,
        )
