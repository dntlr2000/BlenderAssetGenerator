"""Actual structural promotion into full material closure; no fixture is art acceptance."""

from __future__ import annotations

import copy
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_blender_modeler import material_closure_public as public
from codex_blender_modeler.autonomy_v2.controller_bridge import _session_bundle
from codex_blender_modeler.autonomy_v2.execution_profile_service import (
    publish_execution_phase_profile,
)
from codex_blender_modeler.autonomy_v2.models import RootAuthorizationV2
from codex_blender_modeler.autonomy_v2.quality_revision_models import RevisionCostV01
from codex_blender_modeler.autonomy_v2.quality_revision_service import (
    begin_structural_reentry,
    fidelity_authoring_inputs,
)
from codex_blender_modeler.blender_artifacts import (
    deterministic_directory_files,
    native_io_path,
    sha256_file,
)
from codex_blender_modeler.material_closure.graph_rebinding import rebound_material_graph_sha256
from codex_blender_modeler.material_closure.models import (
    ExactArtifact,
    MaterialAQBudgetObservation,
    MaterialClosureSourceBinding,
    MaterialDependencyClosure,
    MaterialFrameworkFailureContext,
    MaterialGraphRebindingChange,
    MaterialPlannedOutput,
    MaterialPreflightBudget,
    MaterialPromotionPreflightRequest,
    MaterialResourceCounters,
)
from codex_blender_modeler.material_closure.preflight import (
    MaterialPreflightValidationError,
    collect_current_uv_layout_fingerprint,
)
from codex_blender_modeler.material_closure.round_models import (
    MaterialClosureSourceBindingV02,
    MaterialGraphRebindingPlanV02,
)
from codex_blender_modeler.material_closure.service import MaterialClosureService
from codex_blender_modeler.material_closure.state_consistency import (
    build_material_canonical_snapshot,
)
from codex_blender_modeler.material_graph.models import MaterialGraphSpec

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE") != "1",
    reason="set CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE=1 for the full structural closure",
)


def _publish(root, path, value, kind):
    """Publish a new test-owned contract using the host's create-once exact byte writer."""

    data = value if isinstance(value, bytes) else (value.model_dump_json(indent=2) + "\n").encode()
    return public._publish_bytes_exact(
        root,
        path,
        data,
        artifact_id=kind,
        kind=kind,
        media_type="application/json",
    )


def _exact(root, path, kind):
    """Bind one existing canonical or test-owned source without modifying it."""

    return public._exact_artifact(root, path, artifact_id=kind, kind=kind)


def _read(root, relative):
    """Read exact fixture bytes through the supported extended Windows path representation."""

    return Path(native_io_path(root / relative)).read_bytes()


def _prepare_closure(root, session_id):
    """Bind real geometry and deep material fixture paths to a fresh full closure."""

    from test_reference_fidelity_aq_blender_vertical import _material_plan

    _, _, plan, budget, state, state_ref = _session_bundle(root.name, session_id)
    common = dict(
        job_id=root.name,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=session_id,
        producer="structural_closure_test",
        producer_version="0.1.0",
        created_at=datetime.now(UTC),
    )
    prefix = f"production/material_closure/{session_id}"
    round_root = f"{prefix}/bindings/after-structure"
    geometry_ref = next(
        item
        for item in reversed(state.provenance)
        if item.kind == "geometry_candidate_validation_receipt"
    )
    geometry = json.loads(_read(root, geometry_ref.path))
    observations = {}
    for key, name, kind in (
        ("candidate_build_provenance", "build_provenance.json", "build_provenance"),
        ("candidate_inventory", "scene_inventory.json", "scene_inventory"),
    ):
        source = geometry[key]
        assert sha256_file(root / source["path"]) == source["sha256"]
        observations[kind] = _publish(
            root,
            f"{round_root}/canonical_observations/{name}",
            _read(root, source["path"]),
            kind,
        )
    scene = _exact(root, "analysis/scene_spec.json", "scene_spec")
    modeling = _exact(root, "analysis/modeling_plan.json", "modeling_plan")
    blend = _exact(root, "blender/scene.blend", "canonical_blend")
    material = _exact(root, "analysis/material_plan.json", "material_plan")
    source_state = _exact(root, state_ref.path, "autonomy_v2_state")
    assert geometry["canonical_blend"]["sha256"] == blend.sha256
    baseline = _publish(
        root,
        f"{round_root}/baseline.json",
        _read(root, material.path),
        "material_plan_baseline",
    )
    snapshot = build_material_canonical_snapshot(
        job_root=root,
        snapshot_id="after-structure",
        scene_spec=scene,
        modeling_plan=modeling,
        blend=blend,
        build_provenance=observations["build_provenance"],
        material_plan=material,
        **common,
    )
    snapshot_ref = _publish(
        root, f"{round_root}/snapshot.json", snapshot, "material_canonical_snapshot"
    )
    execution_id = f"exec-{state.sequence + 1:04d}-material_authoring"
    profile, profile_ref = publish_execution_phase_profile(
        root,
        plan,
        profile_id="material_authoring",
        execution_id=execution_id,
    )
    output_paths = {path.rsplit("/", 1)[1]: path for path in profile.allowed_output_paths}
    candidate = _publish(
        root,
        f"{round_root}/candidate.json",
        _material_plan(root.name, "closure revision"),
        "material_plan",
    )
    authorization = RootAuthorizationV2.model_validate_json(
        _read(root, plan.root_authorization.path)
    )
    reference = _exact(root, authorization.primary_reference.path, "reference")
    prior = next(
        item for item in reversed(state.provenance) if item.kind == "material_phase_receipt"
    )
    prior_receipt = json.loads(_read(root, prior.path))
    # Create a new graph from the fixture's prior semantics; never edit the old graph or receipt.
    graph_path = prior_receipt["material_graph_spec"]["path"]
    graph = json.loads(_read(root, graph_path))
    for item in graph["provenance"]["inputs"]:
        source = {"material_plan": candidate, "scene_spec": scene, "reference": reference}[
            item["role"]
        ]
        item.update(path=source.path, sha256=source.sha256)
    source_graph = _publish(
        root,
        f"{round_root}/source_graph.json",
        MaterialGraphSpec.model_validate_json(json.dumps(graph)),
        "source_material_graph",
    )
    index = next(
        i for i, item in enumerate(graph["provenance"]["inputs"]) if item["role"] == "material_plan"
    )
    rebound = copy.deepcopy(graph)
    rebound["provenance"]["inputs"][index]["path"] = output_paths["material_plan.json"]
    uv = collect_current_uv_layout_fingerprint(
        root, observations["scene_inventory"], expected_job_id=root.name
    )
    rebind_root = f"{prefix}/graph_rebindings/after-structure"
    binding = MaterialClosureSourceBindingV02(
        **common,
        binding_id="after-structure",
        execution_id=execution_id,
        source_state=source_state,
        scene_spec_path=scene.path,
        modeling_plan_path=modeling.path,
        root_authorization_path=plan.root_authorization.path,
        autonomy_plan_path=state.plan.path,
        autonomy_profile_path=plan.profile.path,
        autonomy_budget_path=plan.budget.path,
        material_phase_tool_profile_path=profile_ref.path,
        geometry_candidate_validation_receipt_path=geometry_ref.path,
        canonical_build_provenance_path=observations["build_provenance"].path,
        canonical_scene_inventory_path=observations["scene_inventory"].path,
        canonical_material_plan_observation_path=material.path,
        material_plan_baseline_snapshot_path=baseline.path,
        candidate_material_plan_path=candidate.path,
        material_graph_path=source_graph.path,
        graph_rebinding_plan_path=f"{rebind_root}/plan.json",
        graph_rebinding_receipt_path=f"{rebind_root}/receipt.json",
        rebound_material_graph_path=f"{rebind_root}/rebound_material_graph.json",
        rollback_baseline_path=snapshot_ref.path,
        uv_layout_fingerprint=uv,
        source_evidence=MaterialClosureSourceBinding(
            source_mode="procedural",
            primary_reference_path=reference.path,
            reference_authority_path=plan.root_authorization.path,
            additional_evidence_paths=[
                item.path for item in fidelity_authoring_inputs(root, plan, state, [])
            ],
        ),
    )
    binding_ref = _publish(
        root, binding.source_binding_path(), binding, "material_closure_source_binding"
    )
    rebind = MaterialGraphRebindingPlanV02(
        **common,
        binding_id=binding.binding_id,
        plan_id="after-structure",
        source_binding=binding_ref,
        source_graph=source_graph,
        candidate_material_plan=candidate,
        output_path=binding.rebound_material_graph_path,
        expected_rebound_sha256=rebound_material_graph_sha256(rebound),
        changes=[
            MaterialGraphRebindingChange(
                dependency_role="material_plan",
                path_pointer=f"/provenance/inputs/{index}/path",
                hash_pointer=f"/provenance/inputs/{index}/sha256",
                before_path=candidate.path,
                before_sha256=candidate.sha256,
                after_path=output_paths["material_plan.json"],
                after_sha256=candidate.sha256,
            )
        ],
    )
    _publish(root, binding.graph_rebinding_plan_path, rebind, "material_graph_rebinding_plan")
    rebound_result = public.rebind_material_graph(
        root.name, source_graph_path=source_graph.path, plan_path=binding.graph_rebinding_plan_path
    )
    rebound_ref = ExactArtifact.model_validate(rebound_result["rebound_graph_artifact"])
    outputs = [
        MaterialPlannedOutput(
            output_id=kind,
            output_kind=kind,
            path=output_paths[name],
            verification="exact_hash",
            sha256=artifact.sha256,
            media_type="application/json",
        )
        for kind, name, artifact in (
            ("material_plan", "material_plan.json", candidate),
            ("material_graph", "material_graph.json", rebound_ref),
        )
    ]
    outputs.append(
        MaterialPlannedOutput(
            output_id="completion",
            output_kind="controller_completion",
            path=output_paths["completion.json"],
            verification="structural_binding",
            expected_schema_version="0.2.0",
            media_type="application/json",
            expected_field_bindings={
                "job_id": root.name,
                "session_id": session_id,
                "execution_id": execution_id,
            },
        )
    )
    output_ref = _publish(
        root,
        f"{round_root}/outputs.json",
        json.dumps(
            {"planned_outputs": [item.model_dump(mode="json") for item in outputs]}
        ).encode(),
        "outputs",
    )
    closure = public.plan_material_closure(
        root.name,
        source_binding_path=binding_ref.path,
        planned_outputs_path=output_ref.path,
        closure_id="after-structure",
    )
    counters = MaterialResourceCounters(
        preflight_blender_runs=0,
        controller_invocations=0,
        canonical_promotions=0,
        appearance_revisions=0,
    )
    preflight_budget = MaterialPreflightBudget(
        **common,
        budget_id="after-structure",
        consumed=counters,
        limits=MaterialResourceCounters(**budget.funding.preflight_limits()),
    )
    budget_ref = _publish(
        root, f"{prefix}/budget.json", preflight_budget, "material_preflight_budget"
    )
    usage = state.budget_usage
    aq_usage = {}
    for name, used, limit in (
        ("blender_builds", "total_blender_builds", "total_blender_builds"),
        ("controller_invocations", "controller_invocations", "controller_invocations"),
        ("canonical_promotions", "canonical_promotions", "canonical_promotions"),
        ("actions", "total_actions", "global_action_limit"),
        ("quality_evaluations", "total_quality_evaluations", "total_quality_evaluations"),
    ):
        aq_usage.update(
            {f"{name}_used": getattr(usage, used), f"{name}_limit": getattr(budget, limit)}
        )
    context = MaterialFrameworkFailureContext(
        state_sequence=state.sequence,
        current_state=source_state,
        canonical_snapshot=snapshot,
        controller_execution_count=usage.controller_invocations,
        rollback_count=0,
        budget_usage=counters,
        aq_budget_observation=MaterialAQBudgetObservation(**aq_usage),
        neutral_preview_present=False,
        material_phase_receipt_present=True,
        integrated_quality_entered=True,
    )
    return MaterialPromotionPreflightRequest(
        **common,
        request_id="after-structure",
        closure=ExactArtifact.model_validate(closure["closure_artifact"]),
        closure_receipt=ExactArtifact.model_validate(closure["receipt_artifact"]),
        graph_rebinding_receipt=ExactArtifact.model_validate(rebound_result["receipt_artifact"]),
        candidate_material_plan=candidate,
        rebound_material_graph=rebound_ref,
        canonical_snapshot=snapshot_ref,
        budget=budget_ref,
        framework_failure_context=context,
        uv_layout_fingerprint=uv,
        planned_output_projection=closure["receipt"]["planned_output_projection"],
    )


def test_actual_structural_preflight_promotion_and_full_material_closure(tmp_path, monkeypatch):
    """Verify the revision bridge and protected deep paths before appearance authority."""

    from test_reference_fidelity_aq_blender_vertical import (
        _run_material_round,
        _run_structural_controller_round,
        _submit_actual_quality_round,
        _write_fixture_reference_mask,
    )
    from test_reference_fidelity_geometry_blender import _bound_fidelity_geometry_fixture

    root, session_id = _bound_fidelity_geometry_fixture(tmp_path, monkeypatch, funded=True)
    _write_fixture_reference_mask(root, next((root / "input").glob("*")))
    _run_material_round(root, session_id)
    _submit_actual_quality_round(root, session_id, run_id="closure-source-00", outcome="defect")
    budget = _session_bundle(root.name, session_id)[3]
    begin_structural_reentry(
        root.name,
        session_id,
        strategy="section-loft",
        cost=RevisionCostV01(**budget.funding.route_cost("structural_reentry")),
    )
    _run_structural_controller_round(root, session_id, with_preflight=True)
    protected = {
        path.relative_to(root): sha256_file(path) for path in deterministic_directory_files(root)
    }
    request = _prepare_closure(root, session_id)
    service = MaterialClosureService(root)
    result = service.run_preflight(request, preview_size=64)
    assert result.status == "complete_preflight_passed", result.failure
    assert result.shadow_receipt.blender_version == "5.0.1"
    assert result.resource_receipt.consumed_by_event.preflight_blender_runs == 6
    assert result.report.canonical_unchanged is True
    assert service.run_preflight(request, preview_size=64).report == result.report
    closure = MaterialDependencyClosure.model_validate_json(
        _read(root, request.closure.path)
    )
    from codex_blender_modeler.material_closure.fidelity_source import (
        collect_fidelity_closure_context,
    )

    binding = MaterialClosureSourceBindingV02.model_validate_json(
        _read(root, closure.source_binding.path)
    )
    context = collect_fidelity_closure_context(root, binding)
    assert len(context.render_paths) == 7
    assert len(context.snapshot_substitutions) == 1
    archived_path, archived_sha = next(iter(context.snapshot_substitutions.values()))
    assert closure.project_immutable_input_map()[archived_path] == archived_sha
    assert closure.project_immutable_input_map()["blender/scene.blend"] == sha256_file(
        root / "blender/scene.blend"
    )
    # Negative mutations affect only this isolated fixture, then restore its exact saved bytes.
    for relative in (archived_path, sorted(context.render_paths)[0]):
        path = Path(native_io_path(root / relative))
        saved = path.read_bytes()
        try:
            path.write_bytes(saved + b"stale-fixture")
            with pytest.raises(MaterialPreflightValidationError):
                service.validate_preflight_for_approval(result.report_artifact)
        finally:
            path.write_bytes(saved)
    mixed = binding.model_copy(
        update={
            "source_state": binding.source_state.model_copy(update={"sha256": "0" * 64}),
        }
    )
    with pytest.raises(MaterialPreflightValidationError):
        collect_fidelity_closure_context(root, mixed)
    assert protected == {path: sha256_file(root / path) for path in protected}
