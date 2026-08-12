"""Focused service tests for ImageGen-to-AQ material controller authority."""

from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.autonomy_v2 import codex_image_material_loop_service as service
from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialControllerCompletionV2,
)
from codex_blender_modeler.codex_imagegen.artifacts import artifact_for_codex_image
from codex_blender_modeler.codex_imagegen.material_loop_models import (
    ImageMaterialLoopBudgetUsage,
)
from codex_blender_modeler.codex_imagegen.models import CodexImageArtifact
from codex_blender_modeler.materials.models import MaterialPlan, MaterialPlanItem
from codex_blender_modeler.production.controller_executor import PhaseToolProfile

NOW = datetime(2026, 8, 12, 0, 0, tzinfo=UTC)


def _write_json(path: Path, payload: object) -> None:
    """Write one deterministic JSON fixture for an isolated controller workspace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _artifact(root: Path, name: str) -> CodexImageArtifact:
    """Create one exact companion artifact with a stable fixture identity."""

    path = root / "inputs" / f"{name}.json"
    _write_json(path, {"name": name})
    return artifact_for_codex_image(
        root,
        path,
        artifact_id=name,
        kind="fixture",
        media_type="application/json",
    )


def _create_directory_link_or_skip(link: Path, target: Path) -> None:
    """Create one directory link for containment tests or skip unsupported hosts."""

    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"directory junction creation is unavailable: {result.stderr}")
        return
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink creation is unavailable: {exc}")


def test_exact_adoption_preflight_rejects_linked_output_root_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a linked preflight ancestor before any shadow or Blender output write."""

    v05_artifact = _artifact(tmp_path, "v05-preflight")
    preflight_root = tmp_path.joinpath(
        *service.codex_image_v05_exact_adoption_preflight_root_path(
            "session-loop",
            "preflight-linked-root",
        ).split("/")
    )
    linked_parent = preflight_root.parent
    linked_parent.parent.mkdir(parents=True, exist_ok=True)
    linked_target = tmp_path / "linked-preflight-target"
    linked_target.mkdir()
    _create_directory_link_or_skip(linked_parent, linked_target)
    monkeypatch.setattr(
        service,
        "load_codex_image_model",
        lambda *_args, **_kwargs: SimpleNamespace(session_id="session-loop"),
    )
    monkeypatch.setattr(
        service,
        "validate_codex_image_v05_bridge",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(ValueError, match="symlink or junction"):
        service.publish_codex_image_v05_exact_adoption_preflight(
            tmp_path,
            preflight_id="preflight-linked-root",
            v05_bridge_receipt_artifact=v05_artifact,
            created_at=NOW,
        )

    assert list(linked_target.iterdir()) == []


def test_aq_projection_preserves_exact_kind_unless_alias_is_requested(
    tmp_path: Path,
) -> None:
    """Root authorization projection retains its hyphenated authoritative kind."""

    artifact = _artifact(tmp_path, "root-authorization").model_copy(
        update={"kind": "root-authorization"}
    )

    assert service._aq_from_codex(artifact).kind == "root-authorization"
    assert (
        service._aq_from_codex(artifact, role="material-baseline").kind
        == "material-baseline"
    )


def test_normalized_authoring_boundary_reads_legacy_scope_from_base_request() -> None:
    """Keep legacy material fields off the normalized companion wrapper surface."""

    source = inspect.getsource(service._validate_image_and_authoring_boundary)
    tree = ast.parse(textwrap.dedent(source))
    direct_request_fields = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "request"
    }
    legacy_fields = {
        "core_evidence",
        "derivation",
        "exact_text",
        "material_family",
        "material_id",
        "scale_context",
        "source",
        "source_v05_contracts",
        "strategy",
        "uv_identity",
    }

    assert direct_request_fields.isdisjoint(legacy_fields)
    assert "base_request.uv_identity.semantic_id" in source
    assert "effective_source.artifact.sha256" in source


def _controller_input_stub(
    root: Path,
    *,
    assignment: Path,
    plan_path: Path,
    graph_path: Path,
    allowed: list[str],
) -> SimpleNamespace:
    """Build the exact field surface consumed by the fixed adoption controller."""

    assignment_artifact = artifact_for_codex_image(
        root,
        assignment,
        artifact_id="assignment",
        kind="assignment",
        media_type="application/json",
    )
    plan_artifact = artifact_for_codex_image(
        root,
        plan_path,
        artifact_id="plan-blueprint",
        kind="material-plan",
        media_type="application/json",
    )
    graph_artifact = artifact_for_codex_image(
        root,
        graph_path,
        artifact_id="graph-blueprint",
        kind="material-graph",
        media_type="application/json",
    )
    scene_path = root / "analysis" / "scene_spec.json"
    baseline_path = root / "analysis" / "material_plan.json"
    _write_json(scene_path, {"scene": True})
    _write_json(baseline_path, {"material": True})
    scene = artifact_for_codex_image(
        root,
        scene_path,
        artifact_id="scene",
        kind="scene",
        media_type="application/json",
    )
    baseline = artifact_for_codex_image(
        root,
        baseline_path,
        artifact_id="baseline",
        kind="material-baseline",
        media_type="application/json",
    )
    profile = _artifact(root, "profile")
    return SimpleNamespace(
        execution_mode="exact_adoption",
        candidate_material_plan=plan_artifact,
        material_graph_spec=graph_artifact,
        expected_output_sha256={
            allowed[0]: plan_artifact.sha256,
            allowed[1]: graph_artifact.sha256,
        },
        allowed_output_paths=allowed,
        session_id="session-loop",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        phase_tool_profile=profile,
        immutable_input_sha256={
            scene.path: scene.sha256,
            baseline.path: baseline.sha256,
        },
        source_scene_spec_sha256=scene.sha256,
        source_material_plan_sha256=baseline.sha256,
        assignment=assignment_artifact,
        snapshots=(plan_path, graph_path),
    )


def test_merge_artifact_aliases_preserves_order_and_rejects_conflicts(
    tmp_path: Path,
) -> None:
    """The V0.5 dependency union keeps order while failing on conflicting aliases."""

    first = _artifact(tmp_path, "first")
    second = _artifact(tmp_path, "second")

    assert service._merge_artifact_aliases([first], [first, second]) == [first, second]
    conflict = first.model_copy(update={"sha256": "f" * 64})
    with pytest.raises(ValueError, match="conflicting identity"):
        service._merge_artifact_aliases([first], [conflict])


def _promotion_identity() -> SimpleNamespace:
    """Build the common session identity used by post-quality receipt tests."""

    return SimpleNamespace(
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
    )


@pytest.mark.parametrize(
    ("phase", "status", "next_action"),
    [
        ("quality", "quality_approved", "plan_delivery"),
        ("delivery", "delivery_pending", "await_v07_approval"),
        ("terminal", "completed", "none"),
    ],
)
def test_current_material_receipt_survives_quality_approved_descendants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    status: str,
    next_action: str,
) -> None:
    """A passed freeze keeps the exact material receipt current during delivery."""

    material = service._aq_from_codex(
        _artifact(tmp_path, "material-receipt").model_copy(
            update={"kind": "material_phase_receipt"}
        )
    )
    freeze_artifact = service._aq_from_codex(
        _artifact(tmp_path, "source-freeze").model_copy(update={"kind": "source-freeze"})
    )
    quality_terminal = service._aq_from_codex(
        _artifact(tmp_path, "quality-terminal").model_copy(
            update={"kind": "quality-terminal"}
        )
    )
    state = SimpleNamespace(
        phase=phase,
        status=status,
        next_action=next_action,
        provenance=[material, quality_terminal],
        quality_terminal=quality_terminal,
        source_freeze=freeze_artifact,
    )
    identity = _promotion_identity()
    terminal = SimpleNamespace(
        **vars(identity),
        status="quality_approved",
        source_freeze=freeze_artifact,
    )
    freeze = SimpleNamespace(material_phase_receipt=material)
    receipt = SimpleNamespace(**vars(identity))
    monkeypatch.setattr(service, "get_autonomy_v2_status", lambda *_args: {"state": {}})
    monkeypatch.setattr(
        service.AutonomyStateV2,
        "model_validate_json",
        staticmethod(lambda _payload: state),
    )
    monkeypatch.setattr(service, "validate_quality_terminal_v2", lambda *_args: terminal)
    monkeypatch.setattr(
        service,
        "_quality_terminal_anchor",
        lambda *_args: SimpleNamespace(
            phase="quality",
            status="quality_approved",
            next_action="plan_delivery",
            source_freeze=freeze_artifact,
        ),
    )
    monkeypatch.setattr(service, "_read_model", lambda *_args: freeze)
    monkeypatch.setattr(service, "validate_quality_source_freeze", lambda *_args: None)
    monkeypatch.setattr(
        service,
        "validate_material_phase_receipt_v2",
        lambda *_args, **_kwargs: receipt,
    )

    assert service._current_material_promotion_receipt(tmp_path, identity) is receipt


def test_current_material_receipt_rejects_post_quality_freeze_splice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quality freeze cannot authorize a different material promotion receipt."""

    material = service._aq_from_codex(
        _artifact(tmp_path, "material-receipt-splice").model_copy(
            update={"kind": "material_phase_receipt"}
        )
    )
    other_material = service._aq_from_codex(
        _artifact(tmp_path, "other-material-receipt").model_copy(
            update={"kind": "material_phase_receipt"}
        )
    )
    freeze_artifact = service._aq_from_codex(_artifact(tmp_path, "freeze-splice"))
    quality_terminal = service._aq_from_codex(_artifact(tmp_path, "terminal-splice"))
    state = SimpleNamespace(
        phase="quality",
        status="quality_approved",
        next_action="plan_delivery",
        provenance=[material, quality_terminal],
        quality_terminal=quality_terminal,
        source_freeze=freeze_artifact,
    )
    identity = _promotion_identity()
    terminal = SimpleNamespace(
        **vars(identity),
        status="quality_approved",
        source_freeze=freeze_artifact,
    )
    monkeypatch.setattr(service, "get_autonomy_v2_status", lambda *_args: {"state": {}})
    monkeypatch.setattr(
        service.AutonomyStateV2,
        "model_validate_json",
        staticmethod(lambda _payload: state),
    )
    monkeypatch.setattr(service, "validate_quality_terminal_v2", lambda *_args: terminal)
    monkeypatch.setattr(
        service,
        "_quality_terminal_anchor",
        lambda *_args: SimpleNamespace(
            phase="quality",
            status="quality_approved",
            next_action="plan_delivery",
            source_freeze=freeze_artifact,
        ),
    )
    monkeypatch.setattr(
        service,
        "_read_model",
        lambda *_args: SimpleNamespace(material_phase_receipt=other_material),
    )
    monkeypatch.setattr(service, "validate_quality_source_freeze", lambda *_args: None)

    with pytest.raises(ValueError, match="another material promotion"):
        service._current_material_promotion_receipt(tmp_path, identity)


def test_current_material_receipt_requires_exact_nonpassing_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review evidence authorizes replay only at its exact terminal AQ boundary."""

    material = service._aq_from_codex(
        _artifact(tmp_path, "review-material-receipt").model_copy(
            update={"kind": "material_phase_receipt"}
        )
    )
    quality_terminal = service._aq_from_codex(_artifact(tmp_path, "review-terminal"))
    state = SimpleNamespace(
        phase="terminal",
        status="completed",
        next_action="none",
        provenance=[material, quality_terminal],
        quality_terminal=quality_terminal,
        source_freeze=None,
    )
    identity = _promotion_identity()
    terminal = SimpleNamespace(
        **vars(identity),
        status="review_required",
        source_freeze=None,
    )
    monkeypatch.setattr(service, "get_autonomy_v2_status", lambda *_args: {"state": {}})
    monkeypatch.setattr(
        service.AutonomyStateV2,
        "model_validate_json",
        staticmethod(lambda _payload: state),
    )
    monkeypatch.setattr(service, "validate_quality_terminal_v2", lambda *_args: terminal)
    monkeypatch.setattr(
        service,
        "_quality_terminal_anchor",
        lambda *_args: SimpleNamespace(
            phase="terminal",
            status="review_required",
            next_action="none",
            source_freeze=None,
        ),
    )

    with pytest.raises(ValueError, match="current AQ boundary"):
        service._current_material_promotion_receipt(tmp_path, identity)


def test_exact_adoption_controller_copies_blueprints_and_authors_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fixed controller writes only exact plan, graph, and strict completion outputs."""

    assignment = tmp_path / "assignment.json"
    plan_path = tmp_path / "snapshots" / "plan.json"
    graph_path = tmp_path / "snapshots" / "graph.json"
    _write_json(assignment, {"assignment": True})
    _write_json(
        plan_path,
        MaterialPlan(
            job_id="job-loop",
            stage="authored",
            materials=[MaterialPlanItem(material_id="mat.main", label="Main")],
        ).model_dump(mode="json"),
    )
    _write_json(graph_path, {"graph": "exact-blueprint"})
    canonical = [
        "production/autonomy_v2/session-loop/controller_outputs/material_authoring/"
        "material_plan.json",
        "production/autonomy_v2/session-loop/controller_outputs/material_authoring/"
        "material_graph.json",
        "production/autonomy_v2/session-loop/controller_outputs/material_authoring/"
        "completion.json",
    ]
    stub = _controller_input_stub(
        tmp_path,
        assignment=assignment,
        plan_path=plan_path,
        graph_path=graph_path,
        allowed=canonical,
    )
    assignment.write_text(json.dumps({"strict": "stub"}), encoding="utf-8")
    monkeypatch.setattr(
        service.ImageGeneratedMaterialControllerInput,
        "model_validate_json",
        staticmethod(lambda _payload: stub),
    )
    output_root = (
        tmp_path
        / "production"
        / "autonomy_v2"
        / "session-loop"
        / "controller_executions"
        / "exec-0001-material_authoring"
        / "controller_workspace"
        / "outputs"
    )
    outputs = tuple(output_root / Path(item).name for item in canonical)
    profile = PhaseToolProfile.model_construct(profile_id="material_authoring")

    token = service.ExactCodexImageMaterialAdoptionController().execute(
        assignment=assignment,
        immutable_inputs=stub.snapshots,
        allowed_output_paths=outputs,
        tool_profile=profile,
        timeout_seconds=30,
    )

    assert token == "completed"
    assert outputs[0].read_bytes() == plan_path.read_bytes()
    assert outputs[1].read_bytes() == graph_path.read_bytes()
    completion = MaterialControllerCompletionV2.model_validate_json(
        outputs[2].read_bytes()
    )
    assert completion.execution_id == "exec-0001-material_authoring"
    assert completion.material_plan_path == canonical[0]
    assert completion.material_graph_path == canonical[1]


def test_exact_adoption_controller_rejects_authored_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact-copy controller never accepts controller-authored completion authority."""

    assignment = tmp_path / "assignment.json"
    assignment.write_text("{}", encoding="utf-8")
    stub = SimpleNamespace(execution_mode="controller_authored_completion")
    monkeypatch.setattr(
        service.ImageGeneratedMaterialControllerInput,
        "model_validate_json",
        staticmethod(lambda _payload: stub),
    )
    profile = PhaseToolProfile.model_construct(profile_id="material_authoring")

    with pytest.raises(PermissionError, match="rejects authored"):
        service.ExactCodexImageMaterialAdoptionController().execute(
            assignment=assignment,
            immutable_inputs=(),
            allowed_output_paths=(),
            tool_profile=profile,
            timeout_seconds=30,
        )


def test_make_state_binds_sequence_base_and_failure_evidence(tmp_path: Path) -> None:
    """State construction hashes newly required sequence, base, and failure bindings."""

    plan_artifact = _artifact(tmp_path, "bridge")
    controller_input_artifact = _artifact(tmp_path, "controller-input")
    failure = _artifact(tmp_path, "rollback")
    plan = SimpleNamespace(
        session_id="session-loop",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
    )
    usage = ImageMaterialLoopBudgetUsage(controller_invocations=1)

    state = service._make_state(
        plan,
        plan_artifact,
        controller_input_artifact,
        sequence=1,
        status="failed",
        budget_usage=usage,
        created_at=NOW,
        previous=(SimpleNamespace(), _artifact(tmp_path, "previous")),
        failure_evidence=failure,
        latest_failure="rollback recorded",
    )

    assert state.sequence == 1
    assert state.failure_evidence == failure
    assert state.latest_failure == "rollback recorded"


def test_promotion_guard_is_noop_without_material_loop(tmp_path: Path) -> None:
    """Generic AQ promotion remains unchanged when a session has no loop companion."""

    session_root = tmp_path / "production" / "autonomy_v2" / "session-loop"
    session_root.mkdir(parents=True)
    plan = SimpleNamespace(session_id="session-loop")

    assert (
        service.validate_codex_image_material_controller_promotion_boundary(
            tmp_path,
            session_root,
            plan,
            SimpleNamespace(),
            SimpleNamespace(),
        )
        is False
    )


def test_promotion_failure_without_rollback_does_not_invent_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-write failure binds the exact host result and a static failure code."""

    session_root = tmp_path / "production" / "autonomy_v2" / "session-loop"
    loop_root = session_root / "codex_image_material_loop"
    (loop_root / "bridge_plan.json").parent.mkdir(parents=True)
    (loop_root / "bridge_plan.json").write_text("{}", encoding="utf-8")
    bridge_artifact = _artifact(tmp_path, "prewrite-bridge")
    input_artifact = _artifact(tmp_path, "prewrite-input")
    previous_artifact = _artifact(tmp_path, "prewrite-state")
    result_codex = _artifact(tmp_path, "prewrite-result")
    result_aq = service._aq_from_codex(result_codex, role="controller_result")
    base_state_artifact = service._aq_from_codex(
        _artifact(tmp_path, "prewrite-base-state"), role="state"
    )
    bridge = SimpleNamespace(
        session_id="session-loop",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
    )
    latest = SimpleNamespace(
        status="promoting_material",
        sequence=1,
        budget_usage=ImageMaterialLoopBudgetUsage(controller_invocations=1),
    )
    base_state = SimpleNamespace(sequence=3, provenance=[result_aq])
    monkeypatch.setattr(
        service,
        "_load_loop_bundle",
        lambda *_: (
            loop_root,
            bridge,
            bridge_artifact,
            None,
            input_artifact,
            [(latest, previous_artifact)],
        ),
    )
    monkeypatch.setattr(
        service,
        "_base_aq_state_chain",
        lambda *_: [(base_state, base_state_artifact)],
    )
    monkeypatch.setattr(
        service,
        "validate_v2_artifact",
        lambda root, artifact: root / artifact.path,
    )
    captured: dict[str, object] = {}

    def _capture_append(*args: object):
        """Capture the exact pre-write failure state."""

        captured["state"] = args[-1]
        return args[-1], _artifact(tmp_path, "prewrite-failed-state")

    monkeypatch.setattr(service, "_append_state", _capture_append)
    monkeypatch.setattr(
        service,
        "_publish_pre_promotion_terminal_locked",
        lambda *_args, **_kwargs: (
            SimpleNamespace(model_dump=lambda **_: {"status": "failed"}),
            _artifact(tmp_path, "prewrite-terminal"),
        ),
    )

    result = service.record_codex_image_material_promotion_failure_locked(
        tmp_path,
        session_root,
        SimpleNamespace(session_id="session-loop"),
        base_state,
        result_aq,
    )

    failed = captured["state"]
    assert result is not None
    assert failed.failure_evidence.path == result_codex.path
    assert failed.latest_failure == "material_promotion_prewrite_failed"


def test_promotion_rollback_appends_exact_failed_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host rollback receipt becomes the sole exact companion failure evidence."""

    session_root = tmp_path / "production" / "autonomy_v2" / "session-loop"
    loop_root = session_root / "codex_image_material_loop"
    (loop_root / "bridge_plan.json").parent.mkdir(parents=True)
    (loop_root / "bridge_plan.json").write_text("{}", encoding="utf-8")
    rollback_path = session_root / "material_phase" / "0003" / "rollback_receipt.json"
    _write_json(rollback_path, {"rollback": True})
    bridge_artifact = _artifact(tmp_path, "failure-bridge")
    input_artifact = _artifact(tmp_path, "failure-input")
    previous_artifact = _artifact(tmp_path, "promoting-state")
    result_codex = _artifact(tmp_path, "promotion-result")
    result_aq = service._aq_from_codex(result_codex, role="controller_result")
    base_state_artifact = service._aq_from_codex(
        _artifact(tmp_path, "promotion-base-state"), role="state"
    )
    bridge = SimpleNamespace(
        session_id="session-loop",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
    )
    latest = SimpleNamespace(
        status="promoting_material",
        sequence=1,
        budget_usage=ImageMaterialLoopBudgetUsage(controller_invocations=1),
    )
    base_state = SimpleNamespace(sequence=3, provenance=[result_aq])
    monkeypatch.setattr(
        service,
        "_load_loop_bundle",
        lambda _root, _session: (
            loop_root,
            bridge,
            bridge_artifact,
            None,
            input_artifact,
            [(latest, previous_artifact)],
        ),
    )
    rollback = SimpleNamespace(
        contract_id="material-rollback-exec",
        status="rolled_back",
        reason="canonical source restored",
        controller_result=result_aq,
        provenance=[],
    )
    monkeypatch.setattr(service, "_read_model", lambda *_args: rollback)
    monkeypatch.setattr(
        service,
        "validate_v2_artifact",
        lambda root, artifact: root / artifact.path,
    )
    monkeypatch.setattr(
        service,
        "_base_aq_state_chain",
        lambda *_: [(base_state, base_state_artifact)],
    )
    captured: dict[str, object] = {}

    def _capture_append(*args: object):
        """Capture the proposed terminal state without touching shared history."""

        proposed = args[-1]
        captured["state"] = proposed
        return proposed, _artifact(tmp_path, "failed-state")

    monkeypatch.setattr(service, "_append_state", _capture_append)
    monkeypatch.setattr(
        service,
        "_publish_pre_promotion_terminal_locked",
        lambda *_args, **_kwargs: (
            SimpleNamespace(model_dump=lambda **_: {"status": "failed"}),
            _artifact(tmp_path, "rollback-terminal"),
        ),
    )

    result = service.record_codex_image_material_promotion_failure_locked(
        tmp_path,
        session_root,
        SimpleNamespace(session_id="session-loop"),
        base_state,
        result_aq,
    )

    failed = captured["state"]
    assert result is not None
    assert failed.status == "failed"
    assert failed.failure_evidence.path.endswith("rollback_receipt.json")
    assert failed.latest_failure == "material_promotion_rolled_back"


def test_exact_adoption_rejects_staging_only_not_run_receipt(tmp_path: Path) -> None:
    """Exact adoption cannot reinterpret a staging-only V0.5 receipt as compiled proof."""

    receipt = SimpleNamespace(
        staging_only=True,
        blender_compilation_status="not_run",
        controller_result_created=False,
    )
    with pytest.raises(PermissionError, match="independently precompiled"):
        service._validate_exact_adoption_evidence(
            tmp_path,
            SimpleNamespace(
                execution_mode="exact_adoption",
                exact_adoption_preflight=None,
            ),
            receipt,
        )
    service._validate_exact_adoption_evidence(
        tmp_path,
        SimpleNamespace(execution_mode="controller_authored_completion"),
        receipt,
    )


def test_status_exposes_stable_controller_delivery_and_budget_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status keeps request/result, delivery progress, and remaining budget explicit."""

    loop_root = (
        tmp_path
        / "production"
        / "autonomy_v2"
        / "session-loop"
        / "codex_image_material_loop"
    )
    loop_root.mkdir(parents=True)
    plan_artifact = _artifact(tmp_path, "status-plan")
    input_artifact = _artifact(tmp_path, "status-input")
    latest_artifact = _artifact(tmp_path, "status-loop-state")
    base_codex = _artifact(tmp_path, "status-base-state")
    base_artifact = service._aq_from_codex(base_codex, role="state")
    plan = SimpleNamespace(
        current_state=base_codex,
        requested_delivery_profiles=["portable_gltf", "portable_fbx"],
        model_dump=lambda **_: {"session_id": "session-loop"},
    )
    controller_input = SimpleNamespace(model_dump=lambda **_: {"contract_id": "input"})
    latest = SimpleNamespace(
        base_state=base_codex,
        model_dump=lambda **_: {"status": "waiting_for_quality"},
    )
    base_state = SimpleNamespace(
        phase="delivery",
        status="delivery_pending",
        next_action="run_delivery",
        source_freeze=None,
        delivery_plan=None,
        delivery_terminal=None,
        delivery_results=[],
        model_dump=lambda **_: {"status": "delivery_pending"},
    )
    monkeypatch.setattr(
        service,
        "_load_loop_bundle",
        lambda *_: (
            loop_root,
            plan,
            plan_artifact,
            controller_input,
            input_artifact,
            [(latest, latest_artifact)],
        ),
    )
    monkeypatch.setattr(
        service,
        "_base_aq_state_chain",
        lambda *_: [(base_state, base_artifact)],
    )
    monkeypatch.setattr(
        service,
        "_controller_execution_status_projection",
        lambda *_: {"status": "completed", "request": {"execution_id": "exec"}},
    )
    monkeypatch.setattr(
        service,
        "_remaining_budget_status_projection",
        lambda *_: {"material_loop": {"promotions_consumed": 0}, "base_aq": {}},
    )

    status = service.get_codex_image_material_loop_status(tmp_path, "session-loop")

    assert status["controller_execution"]["request"] == {"execution_id": "exec"}
    assert status["delivery_progress"]["requested_profiles"] == [
        "portable_gltf",
        "portable_fbx",
    ]
    assert status["remaining_budget"]["material_loop"]["promotions_consumed"] == 0
