"""Focused host tests for AQ v2 material validation and canonical promotion."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_blender_modeler.autonomy_v2.delivery_service import (
    artifact_for_v2,
    write_immutable_v2_model,
)
from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialControllerCompletionV2,
    MaterialPhaseRollbackReceiptV2,
)
from codex_blender_modeler.autonomy_v2.material_phase_service import (
    MaterialPhaseError,
    validate_and_promote_material_controller_result_v2,
)
from codex_blender_modeler.autonomy_v2.models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyStateV2,
    RootAuthorizationV2,
)
from codex_blender_modeler.blender_artifacts import (
    sha256_file,
    stable_json_digest,
    write_json_atomic,
)
from codex_blender_modeler.material_graph.models import (
    ChannelBinding,
    MaterialGraphArtifact,
    MaterialGraphProvenance,
    MaterialGraphSpec,
    PreviewLightingPolicy,
)
from codex_blender_modeler.material_graph.runtime_models import (
    MaterialGraphCompileBundle,
    MaterialGraphCompileReport,
    RuntimeArtifact,
)
from codex_blender_modeler.materials.models import MaterialPlan, MaterialPlanItem
from codex_blender_modeler.production.controller_executor import (
    ControllerArtifact,
    ControllerExecutionRequest,
    ControllerResult,
    FakeControllerForTests,
    PhaseToolProfile,
    execute_controller_request,
    write_controller_contract,
)

NOW = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)


def _write_json(path: Path, value: object) -> None:
    """Write one deterministic JSON fixture beneath its temporary job root."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    write_json_atomic(path, payload)


def _aq_artifact(
    root: Path,
    relative: str,
    artifact_id: str,
    kind: str,
) -> AQV2Artifact:
    """Bind one existing fixture file through the production containment service."""

    return artifact_for_v2(
        root,
        root / relative,
        artifact_id=artifact_id,
        kind=kind,
    )


def _controller_artifact(
    root: Path,
    relative: str,
    artifact_id: str,
    role: str,
) -> ControllerArtifact:
    """Bind one existing fixture as a strict controller input artifact."""

    path = root / relative
    return ControllerArtifact(
        artifact_id=artifact_id,
        role=role,
        path=relative,
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
    )


def _scene_payload(job_id: str) -> dict[str, object]:
    """Create one minimal primary-only static prop SceneSpec 0.2 fixture."""

    return {
        "schema_version": "0.2.0",
        "job_id": job_id,
        "mode": "concept",
        "units": "METERS",
        "coordinate_system": {"handedness": "RIGHT", "up": "+Z", "forward": "-Y"},
        "nominal_scene_size": [1.0, 1.0, 1.0],
        "sources": [
            {
                "id": "source.reference",
                "path": "input/reference.png",
                "kind": "reference",
                "immutable": True,
                "scale_anchors": [],
            }
        ],
        "materials": [
            {
                "id": "mat.body",
                "name": "Body",
                "shader": "principled",
                "base_color": [0.5, 0.4, 0.3, 1.0],
                "roughness": 0.5,
                "metallic": 0.0,
                "emission_strength": 0.0,
                "texture_manifest": None,
            }
        ],
        "objects": [
            {
                "id": "body",
                "name": "Body",
                "geometry": {
                    "kind": "primitive",
                    "primitive": "cube",
                    "dimensions": [1.0, 1.0, 1.0],
                    "segments": 8,
                    "ring_segments": 8,
                },
                "transform": {
                    "location": [0.0, 0.0, 0.0],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                },
                "material_id": "mat.body",
                "modifiers": [],
                "generator": None,
                "parent_id": None,
                "shade_smooth": True,
                "tags": ["qa_role:primary"],
                "evidence": [],
                "editable": {},
            }
        ],
        "camera": {
            "projection": "PERSP",
            "location": [2.0, -2.0, 1.5],
            "target": [0.0, 0.0, 0.0],
            "focal_length_mm": 50.0,
            "ortho_scale": 2.0,
            "resolution": [256, 256],
        },
        "assumptions": [],
        "revision_notes": [],
    }


def _material_plan(job_id: str, note: str) -> MaterialPlan:
    """Create one authored, dependency-free V0.5 plan with a distinct exact hash."""

    return MaterialPlan(
        job_id=job_id,
        stage="authored",
        materials=[
            MaterialPlanItem(
                material_id="mat.body",
                label="Body",
                texture_strategy="none",
                confidence=0.9,
                notes=[note],
            )
        ],
        global_notes=[note],
    )


def _phase_profile(
    root: Path,
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    output_root: str,
) -> tuple[PhaseToolProfile, AQV2Artifact, ControllerArtifact]:
    """Publish the exact material_authoring profile used by the executor fixture."""

    placeholder = root / "production" / "dispatch_plan.json"
    _write_json(placeholder, {"dispatch_id": dispatch_id})
    source = _controller_artifact(
        root,
        "production/dispatch_plan.json",
        "dispatch-plan",
        "production-dispatch-plan",
    )
    outputs = [
        f"{output_root}/material_plan.json",
        f"{output_root}/material_graph.json",
        f"{output_root}/completion.json",
    ]
    profile = PhaseToolProfile(
        contract_id=f"profile-material-{session_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=source.sha256,
        source_fingerprint=stable_json_digest({"source": source.sha256}),
        producer="tests.material_phase",
        provenance=[source],
        created_at=NOW,
        profile_id="material_authoring",
        allowed_tools=[],
        forbidden_tools=["arbitrary_python"],
        allowed_input_roles=["assignment", "scene", "material-baseline", "reference"],
        allowed_output_paths=outputs,
    )
    profile_path = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "tool_profiles"
        / "material_authoring.json"
    )
    write_controller_contract(profile_path, profile)
    aq = _aq_artifact(
        root,
        profile_path.relative_to(root).as_posix(),
        profile.contract_id,
        "phase_tool_profile",
    )
    controller = _controller_artifact(
        root,
        profile_path.relative_to(root).as_posix(),
        profile.contract_id,
        "tool_profile",
    )
    return profile, aq, controller


def _dummy_artifact(root: Path, name: str) -> AQV2Artifact:
    """Publish one non-empty exact placeholder for unrelated plan dependencies."""

    path = root / "production" / "fixtures" / f"{name}.json"
    _write_json(path, {"id": name})
    return _aq_artifact(
        root,
        path.relative_to(root).as_posix(),
        name,
        "fixture",
    )


def _plan_and_state(
    root: Path,
    profile_artifact: AQV2Artifact,
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    material_rounds: int,
) -> tuple[AutonomyPlanV2, AutonomyBudgetV2, AutonomyStateV2]:
    """Create strict AQ v2 plan and candidate-validation state fixtures."""

    primary = _aq_artifact(
        root,
        "input/reference.png",
        "primary-reference",
        "primary_reference",
    )
    profile = _dummy_artifact(root, "aq-profile")
    budget = AutonomyBudgetV2(
        contract_id=f"budget-{session_id}",
        budget_id=f"budget-{session_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=primary.sha256,
        source_fingerprint=stable_json_digest({"primary": primary.sha256}),
        producer="tests.material_phase",
        provenance=[primary],
        created_at=NOW,
        material_rounds=material_rounds,
    )
    budget_artifact = write_immutable_v2_model(
        root,
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "budget.json",
        budget,
    )
    launch = _dummy_artifact(root, "production-launch")
    quality = _dummy_artifact(root, "quality-profile")
    authorization = RootAuthorizationV2(
        contract_id=f"authorization-{session_id}",
        authorization_id=f"authorization-{session_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=primary.sha256,
        source_fingerprint=stable_json_digest({"primary": primary.sha256}),
        producer="tests.material_phase",
        provenance=[
            primary,
            profile,
            budget_artifact,
            launch,
            quality,
            profile_artifact,
        ],
        created_at=NOW,
        original_request_sha256="1" * 64,
        primary_reference=primary,
        profile=profile,
        budget=budget_artifact,
        production_launch_or_binding=launch,
        target_subject="fixture body",
        quality_profile=quality,
        phase_tool_profiles=[profile_artifact],
        allowed_delivery_profiles=["review_only"],
        requested_delivery_profiles=["review_only"],
        prohibited_scopes=["interior", "rigging", "destination_project_write"],
    )
    authorization_artifact = write_immutable_v2_model(
        root,
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "root_authorization.json",
        authorization,
    )
    dispatch_plan = _dummy_artifact(root, "dispatch-plan-aq")
    controller_plan = _dummy_artifact(root, "controller-plan-aq")
    plan_payload = {
        "authorization": authorization_artifact.sha256,
        "profile": profile.sha256,
        "budget": budget_artifact.sha256,
    }
    plan = AutonomyPlanV2(
        contract_id=f"plan-{session_id}",
        plan_id=f"plan-{session_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(plan_payload),
        source_fingerprint=stable_json_digest({**plan_payload, "phase": "material"}),
        producer="tests.material_phase",
        provenance=[
            authorization_artifact,
            profile,
            budget_artifact,
            dispatch_plan,
            controller_plan,
        ],
        created_at=NOW,
        profile=profile,
        root_authorization=authorization_artifact,
        budget=budget_artifact,
        production_dispatch_plan=dispatch_plan,
        production_controller_plan=controller_plan,
        phase_tool_profiles=[profile_artifact],
        requested_delivery_profiles=["review_only"],
    )
    plan_path = (
        root / "production" / "autonomy_v2" / session_id / "plan.json"
    )
    plan_artifact = write_immutable_v2_model(root, plan_path, plan)
    state = AutonomyStateV2(
        contract_id=f"state-{session_id}-0002",
        state_id=f"state-{session_id}-0002",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=plan_artifact.sha256,
        source_fingerprint=stable_json_digest({"plan": plan_artifact.sha256}),
        producer="tests.material_phase",
        provenance=[plan_artifact],
        created_at=NOW,
        plan=plan_artifact,
        sequence=2,
        phase="authoring",
        status="running",
        next_action="validate_candidate",
    )
    return plan, budget, state


class _FakeCompiler:
    """Publish a strict report while leaving whitelist behavior to compiler unit tests."""

    def __init__(self, root: Path) -> None:
        """Bind the fake compiler to one temporary job root."""

        self.root = root

    def _report(self, run_root: str) -> MaterialGraphCompileBundle:
        """Read the exact graph and construct one strict compile report fixture."""

        graph_path = next(
            (self.root / "production" / "autonomy_v2").glob(
                "*/controller_outputs/material_authoring/material_graph.json"
            )
        )
        graph = MaterialGraphSpec.model_validate_json(graph_path.read_bytes())
        roles = (
            "request",
            "normalized_plan",
            "dependency_manifest",
            "compiled_blend",
            "normalized_inventory",
            "portable_approximation",
            "neutral_preview_manifest",
            "reference_preview_manifest",
        )
        report = MaterialGraphCompileReport(
            report_id="material-compile-report",
            request_id="material-compile-request",
            job_id=graph.provenance.job_id,
            workflow_id=graph.provenance.workflow_id,
            dispatch_id=graph.provenance.dispatch_id,
            run_id="material-compile",
            graph_id=graph.graph_id,
            material_id=graph.material_id,
            blender_version="5.0.1",
            blender_python_version="3.11.13",
            registry_sha256="2" * 64,
            normalized_plan_sha256="3" * 64,
            normalized_inventory_sha256="4" * 64,
            artifacts=[
                RuntimeArtifact(
                    role=role,
                    path=f"fixture/{index:02d}-{role}.bin",
                    sha256=f"{index + 1:x}" * 64,
                    byte_size=1,
                )
                for index, role in enumerate(roles)
            ],
            completed_at=NOW,
        )
        return MaterialGraphCompileBundle(run_root=run_root, report=report)

    def compile_run(
        self,
        *,
        graph_spec_path: str,
        run_root: str,
        run_id: str,
        policy: object | None = None,
    ) -> MaterialGraphCompileBundle:
        """Publish one strict fake report at the fixed host run root."""

        del graph_spec_path, run_id, policy
        bundle = self._report(run_root)
        _write_json(self.root / run_root / "compile_report.json", bundle.report)
        return bundle

    def validate_compile_run(self, *, run_root: str) -> MaterialGraphCompileBundle:
        """Reparse the published fake report for recovery and lock-time checks."""

        report = MaterialGraphCompileReport.model_validate_json(
            (self.root / run_root / "compile_report.json").read_bytes()
        )
        return MaterialGraphCompileBundle(run_root=run_root, report=report)


def _controller_result_bundle(
    root: Path,
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    profile: PhaseToolProfile,
    profile_controller_artifact: ControllerArtifact,
    graph_extra: dict[str, object] | None = None,
) -> AQV2Artifact:
    """Execute the real isolated controller around strict material output payloads."""

    assignment_path = root / "assignments" / "material.json"
    _write_json(assignment_path, {"phase": "material_authoring"})
    assignment = _controller_artifact(
        root,
        "assignments/material.json",
        "material-assignment",
        "assignment",
    )
    scene_input = _controller_artifact(
        root,
        "analysis/scene_spec.json",
        "scene-spec",
        "scene",
    )
    material_input = _controller_artifact(
        root,
        "analysis/material_plan.json",
        "material-baseline",
        "material-baseline",
    )
    reference_input = _controller_artifact(
        root,
        "input/reference.png",
        "reference",
        "reference",
    )
    output_by_name = {Path(path).name: path for path in profile.allowed_output_paths}
    candidate = _material_plan(job_id, "candidate")
    candidate_bytes = (
        json.dumps(candidate.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    ).encode()
    candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
    graph = MaterialGraphSpec(
        graph_id="graph-body",
        provenance=MaterialGraphProvenance(
            job_id=job_id,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            project_version="0.9.0",
            inputs=[
                MaterialGraphArtifact(
                    role="material_plan",
                    path=output_by_name["material_plan.json"],
                    sha256=candidate_sha,
                ),
                MaterialGraphArtifact(
                    role="scene_spec",
                    path=scene_input.path,
                    sha256=scene_input.sha256,
                ),
                MaterialGraphArtifact(
                    role="reference",
                    path=reference_input.path,
                    sha256=reference_input.sha256,
                ),
            ],
        ),
        material_id="mat.body",
        base_channels=[
            ChannelBinding(
                channel="base_color",
                source_kind="constant",
                color_space="sRGB",
                constant=(0.4, 0.3, 0.2, 1.0),
            ),
            ChannelBinding(
                channel="roughness",
                source_kind="constant",
                color_space="Non-Color",
                constant=0.45,
            ),
        ],
        preview_lighting=PreviewLightingPolicy(
            reference_source=MaterialGraphArtifact(
                role="reference",
                path=reference_input.path,
                sha256=reference_input.sha256,
            ),
            reference_confidence=0.8,
        ),
    )
    graph_payload = graph.model_dump(mode="json")
    graph_payload.update(graph_extra or {})
    graph_bytes = (
        json.dumps(graph_payload, indent=2, ensure_ascii=False) + "\n"
    ).encode()
    graph_sha = hashlib.sha256(graph_bytes).hexdigest()
    immutable_map = {
        scene_input.path: scene_input.sha256,
        material_input.path: material_input.sha256,
        reference_input.path: reference_input.sha256,
    }
    completion = MaterialControllerCompletionV2(
        completion_id="material-completion",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        execution_id="exec-material",
        assignment_sha256=assignment.sha256,
        tool_profile_sha256=profile_controller_artifact.sha256,
        immutable_input_sha256=immutable_map,
        source_scene_spec_sha256=scene_input.sha256,
        source_material_plan_sha256=material_input.sha256,
        material_plan_path=output_by_name["material_plan.json"],
        material_plan_sha256=candidate_sha,
        material_graph_path=output_by_name["material_graph.json"],
        material_graph_sha256=graph_sha,
    )
    completion_bytes = (
        json.dumps(completion.model_dump(mode="json"), indent=2, ensure_ascii=False)
        + "\n"
    ).encode()
    request = ControllerExecutionRequest(
        contract_id="request-material",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(immutable_map),
        source_fingerprint=stable_json_digest(
            {**immutable_map, "outputs": profile.allowed_output_paths}
        ),
        producer="tests.material_phase",
        provenance=[
            assignment,
            scene_input,
            material_input,
            reference_input,
            profile_controller_artifact,
        ],
        created_at=NOW,
        execution_id="exec-material",
        controller_kind="fake_for_tests",
        assignment=assignment,
        immutable_inputs=[scene_input, material_input, reference_input],
        tool_profile=profile_controller_artifact,
        output_root=str(Path(profile.allowed_output_paths[0]).parent).replace("\\", "/"),
        allowed_output_paths=profile.allowed_output_paths,
        timeout_seconds=30,
    )
    request_path = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "controller_executions"
        / "exec-material"
        / "request.json"
    )
    write_controller_contract(request_path, request)
    result = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=FakeControllerForTests(
            payloads={
                "material_plan.json": candidate_bytes,
                "material_graph.json": graph_bytes,
                "completion.json": completion_bytes,
            }
        ),
    )
    result_path = request_path.with_name("result.json")
    _write_json(result_path, result)
    return _aq_artifact(
        root,
        result_path.relative_to(root).as_posix(),
        result.contract_id,
        "controller_result",
    )


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    graph_extra: dict[str, object] | None = None,
    material_rounds: int = 2,
) -> tuple[
    Path,
    AutonomyPlanV2,
    AutonomyBudgetV2,
    AutonomyStateV2,
    AQV2Artifact,
    str,
]:
    """Create one complete AQ v2 material boundary with real executor evidence."""

    job_id = "material_phase_case"
    workflow_id = "wf-material-phase"
    dispatch_id = "dispatch-material-phase"
    session_id = "aqv2-material-phase"
    root = tmp_path / "workspaces" / job_id
    (root / "input").mkdir(parents=True)
    (root / "input" / "reference.png").write_bytes(b"reference-image")
    _write_json(
        root / "job.json",
        {
            "job_id": job_id,
            "reference_content_scope": "primary_object_only",
            "target_subject": "fixture body",
        },
    )
    _write_json(root / "analysis" / "scene_spec.json", _scene_payload(job_id))
    baseline = _material_plan(job_id, "baseline")
    _write_json(root / "analysis" / "material_plan.json", baseline)
    baseline_sha = sha256_file(root / "analysis" / "material_plan.json")
    output_root = (
        f"production/autonomy_v2/{session_id}/controller_outputs/material_authoring"
    )
    profile, profile_aq, profile_controller = _phase_profile(
        root,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        output_root=output_root,
    )
    plan, budget, state = _plan_and_state(
        root,
        profile_aq,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        material_rounds=material_rounds,
    )
    result = _controller_result_bundle(
        root,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        profile=profile,
        profile_controller_artifact=profile_controller,
        graph_extra=graph_extra,
    )
    state = state.model_copy(update={"provenance": [*state.provenance, result]})
    import codex_blender_modeler.autonomy_v2.material_phase_service as service
    import codex_blender_modeler.workspace as workspace

    monkeypatch.setattr(workspace, "job_dir", lambda selected: root)
    monkeypatch.setattr(service, "MaterialGraphCompilerService", _FakeCompiler)

    def fake_run_blender(
        script_name: str,
        args: list[str],
        *,
        blend_file: Path | None = None,
        **_kwargs: object,
    ) -> None:
        """Write deterministic build, inventory, and validation outputs."""

        del blend_file
        output = Path(args[args.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        if script_name == "build_scene.py":
            output.write_bytes(
                b"blend:" + sha256_file(root / "analysis" / "material_plan.json").encode()
            )
        elif script_name == "inspect_scene.py":
            _write_json(output, {"objects": ["body"], "materials": ["mat.body"]})
        elif script_name == "validate_scene.py":
            _write_json(output, {"ok": True, "checks": []})
        else:
            raise AssertionError(f"unexpected Blender script: {script_name}")

    monkeypatch.setattr(service, "run_blender", fake_run_blender)
    return root, plan, budget, state, result, baseline_sha


def test_material_phase_promotes_only_after_compile_and_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Promote an exact plan and retain compile, archive, and fresh build evidence."""

    root, plan, budget, state, result, baseline_sha = _fixture(tmp_path, monkeypatch)
    receipt, artifact = validate_and_promote_material_controller_result_v2(
        root,
        plan,
        budget,
        state,
        result,
    )
    assert receipt.status == "promoted"
    assert receipt.previous_canonical_material_sha256 == baseline_sha
    assert receipt.canonical_material_plan_sha256 == sha256_file(
        root / "analysis" / "material_plan.json"
    )
    assert receipt.archived_material_plan is not None
    assert receipt.build_provenance_snapshot.sha256 == sha256_file(
        root / receipt.build_provenance_snapshot.path
    )
    assert artifact.path.endswith("/promotion_receipt.json")
    recovered, recovered_artifact = validate_and_promote_material_controller_result_v2(
        root,
        plan,
        budget,
        state,
        result,
    )
    assert recovered == receipt
    assert recovered_artifact.sha256 == artifact.sha256


def test_material_policy_decision_failure_rolls_back_canonical_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore canonical material bytes when PolicyDecisionReceipt publication fails."""

    root, plan, budget, state, result, baseline_sha = _fixture(tmp_path, monkeypatch)
    import codex_blender_modeler.autonomy_v2.approval_policy_service as policy_service
    import codex_blender_modeler.autonomy_v2.material_phase_service as service

    def reject_decision(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Simulate a fail-closed host decision writer after candidate promotion."""

        raise PermissionError("PolicyDecisionReceipt unavailable")

    monkeypatch.setattr(
        policy_service,
        "publish_policy_decision_receipt",
        reject_decision,
    )
    with pytest.raises(MaterialPhaseError, match="rollback evidence"):
        service._validate_and_promote_material_controller_result_v2(
            root,
            plan,
            budget,
            state,
            result,
            policy_authorization_path=(
                f"production/autonomy_v2/{plan.session_id}/approval_envelope/"
                "authorizations/fixture.json"
            ),
            canonical_lock_held=False,
        )
    assert sha256_file(root / "analysis" / "material_plan.json") == baseline_sha
    assert list(root.rglob("rollback_receipt.json"))
    assert not list(
        root.glob(
            f"production/autonomy_v2/{plan.session_id}/approval_envelope/decisions/*.json"
        )
    )


def test_material_phase_accepts_only_an_explicit_authorized_profile_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Permit a loop-validated recovery profile without weakening the default plan bind."""

    root, plan, budget, state, result, _baseline_sha = _fixture(tmp_path, monkeypatch)
    del budget
    import codex_blender_modeler.autonomy_v2.material_phase_service as service

    result_model = ControllerResult.model_validate_json(
        (root / result.path).read_bytes()
    )
    result_profile_artifact = artifact_for_v2(
        root,
        root / result_model.tool_profile.path,
        artifact_id=result_model.tool_profile.artifact_id,
        kind="controller_phase_tool_profile",
    )
    result_profile = PhaseToolProfile.model_validate_json(
        (root / result_profile_artifact.path).read_bytes()
    )
    base_profile = result_profile.model_copy(
        update={
            "contract_id": "material-authoring-base-profile",
            "input_sha256": "1" * 64,
            "source_fingerprint": "2" * 64,
        }
    )
    base_profile_path = root / "production" / "base-material-profile.json"
    _write_json(base_profile_path, base_profile)
    base_profile_artifact = artifact_for_v2(
        root,
        base_profile_path,
        artifact_id=base_profile.contract_id,
        kind="material-authoring-profile",
    )
    plan_with_base_profile = plan.model_copy(
        update={"phase_tool_profiles": [base_profile_artifact]}
    )

    with pytest.raises(MaterialPhaseError, match="plan material profile"):
        service._load_controller_material_bundle(
            root,
            plan_with_base_profile,
            state,
            result,
        )

    bundle = service._load_controller_material_bundle(
        root,
        plan_with_base_profile,
        state,
        result,
        authorized_profile_artifact=result_profile_artifact,
    )
    assert bundle.profile == result_profile


def test_supervisor_material_boundary_transitions_to_integrated_quality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatch the exact material profile and enter IQ only after host promotion."""

    root, plan, budget, state, result, _baseline_sha = _fixture(tmp_path, monkeypatch)
    import codex_blender_modeler.autonomy_v2.codex_image_material_loop_service as loop
    import codex_blender_modeler.autonomy_v2.supervisor_service as supervisor

    captured: dict[str, object] = {}
    original_promote = supervisor.validate_and_promote_material_controller_result_v2

    def capture_profile_override(*args: object, **kwargs: object) -> object:
        """Capture the guard-authorized profile passed into host material promotion."""

        captured.update(kwargs)
        return original_promote(*args, **kwargs)

    monkeypatch.setattr(
        loop,
        "validate_codex_image_material_controller_promotion_boundary",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        supervisor,
        "validate_and_promote_material_controller_result_v2",
        capture_profile_override,
    )
    authorization = RootAuthorizationV2.model_validate_json(
        (root / plan.root_authorization.path).read_bytes()
    )
    session_root = root / "production" / "autonomy_v2" / plan.session_id
    response = supervisor._controller_validation_boundary(
        root,
        session_root,
        plan,
        budget,
        state,
        authorization,
    )
    assert response["advanced"] is True
    assert response["outcome"] == "material_candidate_validated"
    next_state = AutonomyStateV2.model_validate_json(json.dumps(response["state"]))
    assert (next_state.phase, next_state.status, next_state.next_action) == (
        "quality",
        "running",
        "run_integrated_quality",
    )
    assert next_state.budget_usage.material_rounds == 1
    assert next_state.budget_usage.total_blender_builds == 2
    assert next_state.budget_usage.canonical_promotions == 1
    assert next_state.provenance[-1].kind == "material_phase_receipt"
    assert captured["authorized_profile_artifact"] is not None


def test_material_phase_rejects_unknown_graph_before_canonical_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject extra MaterialGraph fields without replacing the canonical V0.5 plan."""

    root, plan, budget, state, result, baseline_sha = _fixture(
        tmp_path,
        monkeypatch,
        graph_extra={"raw_blender_node": "ShaderNodeScript"},
    )
    with pytest.raises(MaterialPhaseError, match="MaterialGraphSpec"):
        validate_and_promote_material_controller_result_v2(
            root,
            plan,
            budget,
            state,
            result,
        )
    assert sha256_file(root / "analysis" / "material_plan.json") == baseline_sha
    assert not list((root / "history" / "materials").glob("*.json"))


def test_material_phase_rejects_stale_canonical_scene_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a controller result after its canonical SceneSpec source has changed."""

    root, plan, budget, state, result, baseline_sha = _fixture(tmp_path, monkeypatch)
    scene_path = root / "analysis" / "scene_spec.json"
    scene_payload = json.loads(scene_path.read_text(encoding="utf-8"))
    scene_payload["materials"][0]["roughness"] = 0.6
    _write_json(scene_path, scene_payload)
    with pytest.raises(MaterialPhaseError, match="controller nested artifact changed"):
        validate_and_promote_material_controller_result_v2(
            root,
            plan,
            budget,
            state,
            result,
        )
    assert sha256_file(root / "analysis" / "material_plan.json") == baseline_sha
    assert not list((root / "history" / "materials").glob("*.json"))


def test_material_phase_rolls_back_when_canonical_rebuild_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore the exact baseline and write a rollback receipt after build failure."""

    root, plan, budget, state, result, baseline_sha = _fixture(tmp_path, monkeypatch)
    import codex_blender_modeler.autonomy_v2.material_phase_service as service

    original = service.run_blender
    failed = False

    def fail_promoted_validation(
        script_name: str,
        args: list[str],
        *,
        blend_file: Path | None = None,
        **kwargs: object,
    ) -> None:
        """Fail once while the candidate MaterialPlan is canonical, then allow rollback."""

        nonlocal failed
        if (
            script_name == "validate_scene.py"
            and not failed
            and sha256_file(root / "analysis" / "material_plan.json") != baseline_sha
        ):
            failed = True
            raise RuntimeError("injected canonical rebuild failure")
        original(script_name, args, blend_file=blend_file, **kwargs)

    monkeypatch.setattr(service, "run_blender", fail_promoted_validation)
    with pytest.raises(MaterialPhaseError, match="rollback evidence"):
        validate_and_promote_material_controller_result_v2(
            root,
            plan,
            budget,
            state,
            result,
        )
    assert failed
    assert sha256_file(root / "analysis" / "material_plan.json") == baseline_sha
    rollback_path = (
        root
        / "production"
        / "autonomy_v2"
        / plan.session_id
        / "material_phase"
        / f"{state.sequence:04d}"
        / "rollback_receipt.json"
    )
    rollback = MaterialPhaseRollbackReceiptV2.model_validate_json(
        rollback_path.read_bytes()
    )
    assert rollback.status == "rolled_back"
    assert rollback.restored_build_provenance_snapshot is not None


def test_material_phase_rolls_back_when_atomic_replace_raises_after_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detect a completed canonical replace and still restore the exact baseline."""

    root, plan, budget, state, result, baseline_sha = _fixture(tmp_path, monkeypatch)
    import codex_blender_modeler.autonomy_v2.material_phase_service as service

    original_replace = service.os.replace
    injected = False

    def replace_then_fail(source: object, destination: object) -> None:
        """Raise once after the candidate bytes have reached canonical storage."""

        nonlocal injected
        original_replace(source, destination)
        if not injected and ".material_plan." in str(source):
            injected = True
            raise OSError("injected post-replace failure")

    monkeypatch.setattr(service.os, "replace", replace_then_fail)
    with pytest.raises(MaterialPhaseError, match="rollback evidence"):
        validate_and_promote_material_controller_result_v2(
            root,
            plan,
            budget,
            state,
            result,
        )
    assert injected
    assert sha256_file(root / "analysis" / "material_plan.json") == baseline_sha
    rollback_path = (
        root
        / "production"
        / "autonomy_v2"
        / plan.session_id
        / "material_phase"
        / f"{state.sequence:04d}"
        / "rollback_receipt.json"
    )
    assert rollback_path.is_file()
    rollback = MaterialPhaseRollbackReceiptV2.model_validate_json(
        rollback_path.read_bytes()
    )
    assert rollback.status == "rolled_back"
    assert rollback.restored_build_provenance_snapshot is not None


def test_material_phase_rejects_exhausted_budget_before_host_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an exhausted material-round budget before compile or canonical writes."""

    root, plan, budget, state, result, baseline_sha = _fixture(
        tmp_path,
        monkeypatch,
        material_rounds=0,
    )
    with pytest.raises(PermissionError, match="material_rounds budget"):
        validate_and_promote_material_controller_result_v2(
            root,
            plan,
            budget,
            state,
            result,
        )
    assert sha256_file(root / "analysis" / "material_plan.json") == baseline_sha
    phase_root = (
        root
        / "production"
        / "autonomy_v2"
        / plan.session_id
        / "material_phase"
        / f"{state.sequence:04d}"
    )
    assert not phase_root.exists()


def test_material_phase_rejects_unbound_budget_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a caller-supplied budget that differs from the immutable plan artifact."""

    root, plan, budget, state, result, baseline_sha = _fixture(tmp_path, monkeypatch)
    broadened = budget.model_copy(update={"material_rounds": 3})
    with pytest.raises(MaterialPhaseError, match="budget differs from its plan binding"):
        validate_and_promote_material_controller_result_v2(
            root,
            plan,
            broadened,
            state,
            result,
        )
    assert sha256_file(root / "analysis" / "material_plan.json") == baseline_sha
