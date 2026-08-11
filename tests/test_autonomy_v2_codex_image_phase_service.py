"""Focused persistence tests for the AQ v2 Codex ImageGen phase service."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from codex_blender_modeler.autonomy_v2.codex_image_overlay import (
    AutonomyCodexImageOverlay,
)
from codex_blender_modeler.autonomy_v2.codex_image_phase_service import (
    adopt_codex_image_completion,
    get_codex_image_phase_status,
    initialize_codex_image_phase,
    publish_codex_image_assignment,
    terminalize_codex_image_phase,
)
from codex_blender_modeler.autonomy_v2.delivery_service import (
    artifact_for_v2,
    write_immutable_v2_model,
)
from codex_blender_modeler.autonomy_v2.models import AQV2Artifact, AutonomyStateV2
from codex_blender_modeler.autonomy_v2.planner import (
    plan_autonomous_static_prop_v2,
)
from codex_blender_modeler.autonomy_v2.transitions import transition_state
from codex_blender_modeler.blender_artifacts import native_io_path
from codex_blender_modeler.codex_imagegen import (
    CodexImageArtifact,
    CodexImageDimensions,
    CodexImageGenerationAssignment,
    CodexImageGenerationBudget,
    CodexImageGenerationBudgetUsage,
    CodexImageGenerationCandidate,
    CodexImageGenerationPlan,
    CodexImageGenerationPlanItem,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
    artifact_for_codex_image,
    build_codex_builtin_image_provider_profile,
    build_codex_imagegen_assignment,
    build_codex_imagegen_plan,
    build_default_codex_imagegen_budget,
    load_codex_image_model,
    write_immutable_codex_image_model,
)
from codex_blender_modeler.codex_imagegen import (
    command_service as imagegen_command_service,
)
from codex_blender_modeler.codex_imagegen import (
    public_service as imagegen_public_service,
)
from codex_blender_modeler.codex_imagegen.command_service import (
    adopt_codex_imagegen_material_phase,
    get_codex_imagegen_public_status,
    prepare_codex_imagegen_material_adoption,
    run_codex_imagegen_controller_phase,
    select_codex_imagegen_phase,
)
from codex_blender_modeler.codex_imagegen.completion import (
    copy_imagegen_png_and_write_completion,
)
from codex_blender_modeler.codex_imagegen.controller_bridge import (
    execute_codex_imagegen_controller,
)
from codex_blender_modeler.codex_imagegen.fake_controller_backend import (
    FakeCodexImagegenController,
)
from codex_blender_modeler.codex_imagegen.public_service import (
    adopt_codex_imagegen_completion,
    cancel_codex_imagegen,
    plan_codex_imagegen,
    run_codex_imagegen,
)
from codex_blender_modeler.material_authoring.codex_image_models import (
    CodexImageEvidenceBindingsV021,
    CodexImageMaterialAuthoringRequestV021,
    CodexImageMaterialSourceV021,
    ExactSignageTextEvidenceV021,
    ExactTextCompositionV021,
    LocalImageDerivationPolicyV021,
)
from codex_blender_modeler.material_authoring.models import (
    ExactArtifact,
    ProjectLocalFont,
    ScaleContextBinding,
    UVIdentity,
    UVIdentitySnapshot,
    UVRect,
)
from codex_blender_modeler.production.controller_executor import (
    DesktopInSessionController,
)
from codex_blender_modeler.structural_geometry.models import (
    AssetScaleContext,
    StructuralEvidenceArtifact,
)


@dataclass(frozen=True)
class _PhaseFixture:
    """Hold exact core models and artifacts for one isolated overlay session."""

    root: Path
    session_id: str
    created_at: datetime
    base_state: AutonomyStateV2
    base_state_artifact: CodexImageArtifact
    plan: CodexImageGenerationPlan
    plan_artifact: CodexImageArtifact
    budget: CodexImageGenerationBudget
    budget_artifact: CodexImageArtifact
    provider_profile_artifact: CodexImageArtifact
    plan_item: CodexImageGenerationPlanItem


class _DesktopOutcomeController:
    """Return one deterministic desktop outcome without producing canonical outputs."""

    controller_kind = "desktop_in_session"

    def __init__(self, status: str) -> None:
        """Store the requested one-shot status and an invocation counter."""

        self.status = status
        self.calls = 0

    def execute(
        self,
        *,
        assignment: Path,
        immutable_inputs: tuple[Path, ...],
        allowed_output_paths: tuple[Path, ...],
        tool_profile: object,
        timeout_seconds: int,
    ) -> str:
        """Return the configured final token and make rejection diagnostics concrete."""

        del assignment, immutable_inputs, tool_profile, timeout_seconds
        self.calls += 1
        if self.status == "rejected":
            allowed_output_paths[0].write_bytes(b"rejected-partial-output")
        return self.status


def _as_codex_artifact(payload: dict[str, object]) -> CodexImageArtifact:
    """Add JSON media semantics to one exact AQ v2 artifact binding."""

    return CodexImageArtifact.model_validate(
        {**payload, "media_type": "application/json"}
    )


def _write_aq_evidence(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
) -> AQV2Artifact:
    """Write a tiny immutable AQ test receipt and return its exact binding."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"artifact_id": artifact_id}) + "\n", encoding="utf-8")
    return artifact_for_v2(
        root,
        path,
        artifact_id=artifact_id,
        kind=kind,
    )


def _advance_base_to_material(
    root: Path,
    session_id: str,
    initial: AutonomyStateV2,
    created_at: datetime,
) -> tuple[AutonomyStateV2, CodexImageArtifact]:
    """Create a valid base AQ chain whose next controller phase is material authoring."""

    evidence_root = root / "production" / "autonomy_v2" / session_id / "test_evidence"
    reference = _write_aq_evidence(
        root,
        evidence_root / "reference.json",
        artifact_id="reference-ready",
        kind="reference_context",
    )
    state = transition_state(
        initial,
        event="reference_ready",
        evidence=reference,
        created_at=created_at + timedelta(seconds=1),
    )
    write_immutable_v2_model(
        root,
        root / "production" / "autonomy_v2" / session_id / "states" / "0001.json",
        state,
    )
    controller = _write_aq_evidence(
        root,
        evidence_root / "geometry-controller-result.json",
        artifact_id="geometry-controller-result",
        kind="controller_result",
    )
    state = transition_state(
        state,
        event="controller_output_ready",
        evidence=controller,
        created_at=created_at + timedelta(seconds=2),
    )
    write_immutable_v2_model(
        root,
        root / "production" / "autonomy_v2" / session_id / "states" / "0002.json",
        state,
    )
    receipt = _write_aq_evidence(
        root,
        evidence_root / "geometry-receipt.json",
        artifact_id="geometry-receipt",
        kind="geometry_candidate_validation_receipt",
    )
    state = transition_state(
        state,
        event="candidate_validated",
        evidence=receipt,
        created_at=created_at + timedelta(seconds=3),
    )
    state_path = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "states"
        / "0003.json"
    )
    write_immutable_v2_model(root, state_path, state)
    aq_artifact = artifact_for_v2(
        root,
        state_path,
        artifact_id=state.state_id,
        kind="autonomy_v2_state",
    )
    return state, _as_codex_artifact(aq_artifact.model_dump(mode="json"))


def _phase_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    job_id: str,
    material_boundary: bool,
    image_size: int = 64,
    quality_level: str = "low",
    fallback: str = "local_procedural_fallback",
) -> _PhaseFixture:
    """Build one AQ plan plus a bounded experimental image plan at a chosen square size."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / f"{job_id}.png"
    Image.new("RGB", (32, 32), (24, 48, 96)).save(reference)
    base = plan_autonomous_static_prop_v2(
        "Create only the test prop.",
        reference_path=reference,
        target_subject="test prop",
        requested_delivery_profiles=["review_only"],
        job_id=job_id,
        allow_disabled_experimental=True,
    )
    root = workspace / job_id
    session_id = str(base["session_id"])
    created_at = datetime.now(UTC)
    base_plan_artifact = _as_codex_artifact(base["artifacts"]["plan"])
    base_authorization_artifact = _as_codex_artifact(
        base["artifacts"]["root_authorization"]
    )
    profile = build_codex_builtin_image_provider_profile(
        contract_id=f"codex-profile-{session_id}",
        provider_profile_id=f"codex-profile-{session_id}",
        job_id=job_id,
        workflow_id=str(base["workflow_id"]),
        dispatch_id=str(base["dispatch_id"]),
        session_id=session_id,
        base_profile_artifact=base_plan_artifact,
        created_at=created_at,
    )
    codex_root = root / "production" / "autonomy_v2" / session_id / "codex_imagegen"
    profile_artifact = write_immutable_codex_image_model(
        root,
        codex_root / "provider-profile.json",
        profile,
        kind="codex-builtin-image-provider-profile",
    )
    budget = build_default_codex_imagegen_budget(
        contract_id=f"codex-budget-{session_id}",
        budget_id=f"codex-budget-{session_id}",
        job_id=job_id,
        workflow_id=str(base["workflow_id"]),
        dispatch_id=str(base["dispatch_id"]),
        session_id=session_id,
        provider_profile=profile_artifact,
        created_at=created_at,
    )
    budget_artifact = write_immutable_codex_image_model(
        root,
        codex_root / "budget.json",
        budget,
        kind="codex-image-generation-budget",
    )
    plan_item = CodexImageGenerationPlanItem(
        plan_item_id="surface-swatch",
        target_material_ids=["material-main"],
        semantic_roles=["primary-surface"],
        generation_intent="generated_surface_swatch_v1",
        allowed_output_roles=["base_color"],
        prompt_template_id="surface-swatch-v1",
        requested_candidate_count=1,
        quality_level=quality_level,
        image_size=CodexImageDimensions(width=image_size, height=image_size),
        aspect_ratio="square",
        fallback=fallback,
    )
    plan = build_codex_imagegen_plan(
        contract_id=f"codex-plan-{session_id}",
        plan_id=f"codex-plan-{session_id}",
        job_id=job_id,
        workflow_id=str(base["workflow_id"]),
        dispatch_id=str(base["dispatch_id"]),
        session_id=session_id,
        base_autonomy_plan=base_plan_artifact,
        base_root_authorization=base_authorization_artifact,
        provider_profile=profile,
        provider_profile_artifact=profile_artifact,
        budget=budget,
        budget_artifact=budget_artifact,
        items=[plan_item],
        created_at=created_at,
    )
    plan_artifact = plan_codex_imagegen(job_root=root, plan=plan)
    initial_base = AutonomyStateV2.model_validate_json(
        (root / str(base["artifacts"]["state"]["path"])).read_bytes()
    )
    if material_boundary:
        base_state, base_state_artifact = _advance_base_to_material(
            root,
            session_id,
            initial_base,
            created_at,
        )
    else:
        base_state = initial_base
        base_state_artifact = _as_codex_artifact(base["artifacts"]["state"])
    return _PhaseFixture(
        root=root,
        session_id=session_id,
        created_at=created_at,
        base_state=base_state,
        base_state_artifact=base_state_artifact,
        plan=plan,
        plan_artifact=plan_artifact,
        budget=budget,
        budget_artifact=budget_artifact,
        provider_profile_artifact=profile_artifact,
        plan_item=plan_item,
    )


def _initialize(fixture: _PhaseFixture):
    """Initialize one fixture through the explicit experimental override."""

    return initialize_codex_image_phase(
        fixture.root,
        generation_plan=fixture.plan_artifact,
        provider_profile=fixture.provider_profile_artifact,
        budget=fixture.budget_artifact,
        created_at=fixture.created_at + timedelta(seconds=4),
        allow_disabled_experimental=True,
    )


def _publish_waiting_assignment(
    fixture: _PhaseFixture,
    *,
    prompt: str,
) -> tuple[
    CodexImageGenerationAssignment,
    CodexImageArtifact,
    AutonomyCodexImageOverlay,
]:
    """Publish one exact assignment and advance its overlay to controller waiting."""

    assignment = build_codex_imagegen_assignment(
        contract_id="assignment-surface-00",
        assignment_id="surface-00",
        sequence=0,
        plan=fixture.plan,
        plan_artifact=fixture.plan_artifact,
        plan_item=fixture.plan_item,
        provider_profile_artifact=fixture.provider_profile_artifact,
        budget=fixture.budget,
        budget_artifact=fixture.budget_artifact,
        usage=CodexImageGenerationBudgetUsage(),
        base_state_artifact=fixture.base_state_artifact,
        job_root=fixture.root,
        rendered_prompt_text=prompt,
        reference_images=[],
        created_at=fixture.created_at + timedelta(seconds=5),
    )
    artifact = run_codex_imagegen(
        job_root=fixture.root,
        assignment=assignment,
    )
    state, _state_artifact = publish_codex_image_assignment(
        fixture.root,
        fixture.session_id,
        assignment=artifact,
        created_at=fixture.created_at + timedelta(seconds=6),
    )
    return assignment, artifact, state


def _completion_artifact(
    fixture: _PhaseFixture,
    assignment: CodexImageGenerationAssignment,
) -> CodexImageArtifact:
    """Bind the canonical completion written and published by ControllerExecutor."""

    return artifact_for_codex_image(
        fixture.root,
        fixture.root / assignment.completion_file_target,
        artifact_id=f"completion-{assignment.assignment_id}",
        kind="codex-image-generation-completion",
        media_type="application/json",
    )


def _execute_fake_completion(
    fixture: _PhaseFixture,
) -> tuple[
    CodexImageGenerationAssignment,
    CodexImageArtifact,
    FakeCodexImagegenController,
    CodexImageArtifact,
    CodexImageArtifact,
    CodexImageArtifact,
]:
    """Publish one waiting assignment and return its exact fake completion chain."""

    assignment, assignment_artifact, _waiting = _publish_waiting_assignment(
        fixture,
        prompt="Generate one deterministic crash-recovery swatch.",
    )
    controller = FakeCodexImagegenController(
        assignment_artifact=assignment_artifact,
        executed_at=fixture.created_at + timedelta(seconds=7),
    )
    execution = execute_codex_imagegen_controller(
        job_root=fixture.root,
        assignment_artifact=assignment_artifact,
        controller=controller,
        created_at=fixture.created_at + timedelta(seconds=7),
        timeout_seconds=30,
    )
    assert execution.result.status == "completed"
    return (
        assignment,
        assignment_artifact,
        controller,
        _completion_artifact(fixture, assignment),
        execution.request_artifact,
        execution.result_artifact,
    )


def _write_generated_source(path: Path) -> None:
    """Create one deterministic ImageGen-like source PNG outside the protected job root."""

    image = Image.new("RGBA", (64, 64))
    pixels = image.load()
    for y in range(64):
        for x in range(64):
            value = (x * 17 + y * 31) % 256
            pixels[x, y] = (value, (value * 3) % 256, 160, 255)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _material_artifact(artifact: CodexImageArtifact) -> ExactArtifact:
    """Convert one identical core artifact binding to the material companion type."""

    return ExactArtifact.model_validate(artifact.model_dump(mode="python"))


def _write_exact_text_evidence(
    fixture: _PhaseFixture,
    *,
    text: str,
    name: str,
) -> tuple[Path, ExactArtifact]:
    """Publish one strict local-text fixture and return its contained exact binding."""

    evidence = ExactSignageTextEvidenceV021(
        evidence_id=name,
        text=text,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        created_at=fixture.created_at,
    )
    path = fixture.root / "analysis" / f"{name}.json"
    path.write_text(
        json.dumps(evidence.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifact = artifact_for_codex_image(
        fixture.root,
        path,
        artifact_id=name,
        kind="exact-signage-text-evidence",
        media_type="application/json",
    )
    return path, _material_artifact(artifact)


def _write_bitmap_font(fixture: _PhaseFixture) -> ProjectLocalFont:
    """Publish a deterministic project-owned bitmap font for the exact AB fixture."""

    path = fixture.root / "assets" / "fonts" / "codex-command-font.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "glyph_width": 3,
                "glyph_height": 5,
                "spacing": 1,
                "glyphs": {
                    "A": ["010", "101", "111", "101", "101"],
                    "B": ["110", "101", "110", "101", "110"],
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    artifact = artifact_for_codex_image(
        fixture.root,
        path,
        artifact_id="codex-command-font",
        kind="project-local-bitmap-font",
        media_type="application/json",
    )
    return ProjectLocalFont(
        artifact=_material_artifact(artifact),
        font_format="bitmap_json_v1",
        license_id="fixture-project-owned",
        rights_status="project_owned",
        provenance="deterministic pytest bitmap font",
    )


def _material_scale_and_uv(
    fixture: _PhaseFixture,
) -> tuple[ScaleContextBinding, UVIdentity, ExactArtifact]:
    """Publish exact scale, UV, and legacy V0.5 inputs for one adoption test."""

    scene_path = fixture.root / "analysis" / "scene_spec-material.json"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text('{"schema_version":"0.2.0"}\n', encoding="utf-8")
    scene_artifact = artifact_for_codex_image(
        fixture.root,
        scene_path,
        artifact_id="material-scene-spec",
        kind="scene-spec-v02",
        media_type="application/json",
    )
    context = AssetScaleContext.from_bounds(
        asset_id="asset.main",
        job_id=fixture.plan.job_id,
        workflow_id=fixture.plan.workflow_id,
        dispatch_id=fixture.plan.dispatch_id,
        source_fingerprint="1" * 64,
        producer="pytest.codex_imagegen.command_service",
        producer_version="0.1.0",
        provenance=[
            StructuralEvidenceArtifact(
                role="scene_spec",
                path=scene_artifact.path,
                sha256=scene_artifact.sha256,
            )
        ],
        created_at=fixture.created_at,
        local_minimum=(0.0, 0.0, 0.0),
        local_maximum=(1.0, 0.5, 0.25),
        assembly_minimum=(0.0, 0.0, 0.0),
        assembly_maximum=(1.0, 0.5, 0.25),
        projected_pixel_size=128.0,
        target_texel_density_px_m=256.0,
    )
    context_path = fixture.root / "analysis" / "asset-scale-context.json"
    context_path.write_text(
        json.dumps(context.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    context_artifact = artifact_for_codex_image(
        fixture.root,
        context_path,
        artifact_id="material-scale-context",
        kind="asset-scale-context",
        media_type="application/json",
    )
    scale = ScaleContextBinding(
        artifact=_material_artifact(context_artifact),
        asset_id=context.asset_id,
        source_fingerprint=context.source_fingerprint,
        shortest_dimension_m=context.shortest_dimension_m,
        longest_dimension_m=max(context.assembly_bbox.dimensions()),
        target_texel_density_px_m=context.target_texel_density_px_m,
    )
    snapshot = UVIdentitySnapshot(
        semantic_id="asset.main",
        uv_set="UVMap",
        uv_fingerprint="2" * 64,
        ordered_polygon_corner_count=24,
        texel_density_px_m=256.0,
    )
    uv_path = fixture.root / "analysis" / "uv-identity.json"
    uv_path.write_text(
        json.dumps(snapshot.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    uv_artifact = artifact_for_codex_image(
        fixture.root,
        uv_path,
        artifact_id="material-uv-identity",
        kind="uv-identity-snapshot",
        media_type="application/json",
    )
    uv = UVIdentity(
        **snapshot.model_dump(mode="python"),
        evidence=_material_artifact(uv_artifact),
    )
    v05_path = fixture.root / "analysis" / "material-plan-v05.json"
    v05_path.write_text('{"schema_version":"0.5.0"}\n', encoding="utf-8")
    v05_artifact = artifact_for_codex_image(
        fixture.root,
        v05_path,
        artifact_id="material-plan-v05",
        kind="v05-material-plan",
        media_type="application/json",
    )
    return scale, uv, _material_artifact(v05_artifact)


def test_phase_initialization_is_explicit_immutable_and_prompt_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require opt-in, publish only the companion path, and keep status secret-safe."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-phase-init",
        material_boundary=False,
    )
    with pytest.raises(PermissionError, match="explicit opt-in"):
        initialize_codex_image_phase(
            fixture.root,
            generation_plan=fixture.plan_artifact,
            provider_profile=fixture.provider_profile_artifact,
            budget=fixture.budget_artifact,
            created_at=fixture.created_at,
            allow_disabled_experimental=False,
        )
    state, artifact = _initialize(fixture)
    expected = (
        f"production/autonomy_v2/{fixture.session_id}/codex_imagegen/"
        "overlay/states/0000.json"
    )
    assert artifact.path == expected
    assert state.status == "planned"
    recovered, recovered_artifact = _initialize(fixture)
    assert recovered == state
    assert recovered_artifact == artifact

    status = get_codex_image_phase_status(fixture.root, fixture.session_id)
    encoded = json.dumps(status, sort_keys=True)
    assert status["profile"]["status"] == "disabled_experimental"
    assert status["repository_can_spawn_codex_task"] is False
    assert status["autonomous_daemon"] is False
    assert "rendered_prompt_text" not in encoded
    assert "OPENAI_API_KEY" not in encoded
    completion_parameters = inspect.signature(
        adopt_codex_image_completion
    ).parameters
    assert "controller_request" in completion_parameters
    assert "controller_result" in completion_parameters
    assert "controller" in completion_parameters
    assert "protected_source_inventory_sha256" not in completion_parameters
    assert not any("api_key" in name.casefold() for name in completion_parameters)


def test_assignment_publication_waits_without_replay_or_base_state_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enter waiting_for_controller once and leave the exact base state untouched."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-phase-wait",
        material_boundary=True,
    )
    _initialize(fixture)
    secret_prompt = "confidential prompt that status must never expose"
    _assignment, assignment_artifact, state = _publish_waiting_assignment(
        fixture,
        prompt=secret_prompt,
    )
    base_before = (
        fixture.root / fixture.base_state_artifact.path
    ).read_bytes()
    assert state.status == "waiting_for_controller"
    assert state.next_action == "adopt_completion"
    assert state.budget_usage.total_generations == 0
    assert (fixture.root / fixture.base_state_artifact.path).read_bytes() == base_before

    first_status = get_codex_image_phase_status(fixture.root, fixture.session_id)
    second_status = get_codex_image_phase_status(fixture.root, fixture.session_id)
    assert first_status == second_status
    assert secret_prompt not in json.dumps(first_status, sort_keys=True)
    assert first_status["waiting_for_controller"] is True
    with pytest.raises(ValueError, match="already consumed|invalid"):
        publish_codex_image_assignment(
            fixture.root,
            fixture.session_id,
            assignment=assignment_artifact,
            created_at=fixture.created_at + timedelta(seconds=7),
        )
    states = list(
        (
            fixture.root
            / "production"
            / "autonomy_v2"
            / fixture.session_id
            / "codex_imagegen"
            / "overlay"
            / "states"
        ).glob("*.json")
    )
    assert len(states) == 2
    terminal = cancel_codex_imagegen(
        job_root=fixture.root,
        contract_id="waiting-cancel-terminal",
        terminal_id="waiting-cancel-terminal",
        plan_artifact=fixture.plan_artifact,
        budget=fixture.budget,
        budget_artifact=fixture.budget_artifact,
        budget_usage=state.budget_usage,
        reason="cancel the waiting controller boundary",
        created_at=fixture.created_at + timedelta(seconds=8),
        assignment_artifact=assignment_artifact,
    )
    cancelled, _cancelled_artifact = terminalize_codex_image_phase(
        fixture.root,
        fixture.session_id,
        event="cancelled",
        generation_terminal=terminal,
        created_at=fixture.created_at + timedelta(seconds=9),
    )
    assert cancelled.status == "cancelled"


def test_command_assignment_retry_rebinds_exact_file_after_state_publish_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover a pre-state assignment once while rejecting changed prompt or text inputs."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-command-assignment-crash",
        material_boundary=True,
    )
    _initialize(fixture)
    prompt = "Generate a neutral wood swatch without signage text."
    real_publish = imagegen_command_service.publish_codex_image_assignment

    def crash_before_state(*args: object, **kwargs: object) -> None:
        """Simulate process loss after assignment publication but before overlay state."""

        del args, kwargs
        raise RuntimeError("simulated assignment state publication crash")

    monkeypatch.setattr(
        imagegen_command_service,
        "publish_codex_image_assignment",
        crash_before_state,
    )
    with pytest.raises(RuntimeError, match="state publication crash"):
        run_codex_imagegen_controller_phase(
            job_id=fixture.plan.job_id,
            session_id=fixture.session_id,
            rendered_prompt_text=prompt,
            exact_text_value="AB",
            timeout_seconds=30,
        )
    assignment_path = (
        fixture.root
        / "production"
        / "autonomy_v2"
        / fixture.session_id
        / "codex_imagegen"
        / "assignments"
        / "material-00"
        / "assignment.json"
    )
    original_bytes = Path(native_io_path(assignment_path)).read_bytes()
    original_assignment = CodexImageGenerationAssignment.model_validate_json(
        original_bytes
    )
    crashed_status = get_codex_image_phase_status(fixture.root, fixture.session_id)
    assert crashed_status["state"]["status"] == "planned"
    assert crashed_status["budget"]["usage"]["assignments"] == 0

    with pytest.raises(ValueError, match="assignment inputs differ"):
        run_codex_imagegen_controller_phase(
            job_id=fixture.plan.job_id,
            session_id=fixture.session_id,
            rendered_prompt_text="Generate a different bounded swatch.",
            exact_text_value="AB",
            timeout_seconds=30,
        )
    with pytest.raises(ValueError, match="assignment inputs differ"):
        run_codex_imagegen_controller_phase(
            job_id=fixture.plan.job_id,
            session_id=fixture.session_id,
            rendered_prompt_text=prompt,
            exact_text_value="AC",
            timeout_seconds=30,
        )

    monkeypatch.setattr(
        imagegen_command_service,
        "publish_codex_image_assignment",
        real_publish,
    )
    recovered = run_codex_imagegen_controller_phase(
        job_id=fixture.plan.job_id,
        session_id=fixture.session_id,
        rendered_prompt_text=prompt,
        exact_text_value="AB",
        timeout_seconds=30,
    )
    assert recovered["status"] == "waiting_for_output"
    assert Path(native_io_path(assignment_path)).read_bytes() == original_bytes
    rebound = CodexImageArtifact.model_validate(recovered["assignment"])
    assert rebound.sha256 == hashlib.sha256(original_bytes).hexdigest()
    stored = load_codex_image_model(
        fixture.root,
        rebound,
        CodexImageGenerationAssignment,
    )
    assert stored.created_at == original_assignment.created_at
    recovered_status = get_codex_image_phase_status(fixture.root, fixture.session_id)
    assert recovered_status["state"]["status"] == "waiting_for_controller"
    assert recovered_status["budget"]["usage"]["assignments"] == 0
    assert recovered_status["budget"]["usage"]["total_generations"] == 0


@pytest.mark.parametrize(
    "fallback",
    [
        "local_procedural_fallback",
        "review_required",
        "user_image_required",
    ],
)
def test_command_capacity_rejection_applies_exact_plan_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fallback: str,
) -> None:
    """Terminalize an oversized planned assignment using only its declared fallback."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id=f"codex-capacity-{fallback.replace('_', '-')}",
        material_boundary=True,
        image_size=2048,
        quality_level="low",
        fallback=fallback,
    )
    _initialize(fixture)
    result = run_codex_imagegen_controller_phase(
        job_id=fixture.plan.job_id,
        session_id=fixture.session_id,
        rendered_prompt_text="Generate one bounded oversized swatch.",
        timeout_seconds=30,
    )
    assert result["status"] == fallback
    assert result["controller_status"] is None
    assert result["assignment"] is None
    terminal_artifact = CodexImageArtifact.model_validate(
        result["generation_terminal"]
    )
    terminal = load_codex_image_model(
        fixture.root,
        terminal_artifact,
        imagegen_command_service.CodexImageGenerationTerminal,
    )
    assert terminal.status == fallback
    assert terminal.plan_item_id == fixture.plan_item.plan_item_id
    assert terminal.runtime_trigger == "assignment_capacity_rejected"
    assert terminal.controller_request is None
    assert terminal.controller_result is None
    status = get_codex_image_phase_status(fixture.root, fixture.session_id)
    assert status["state"]["status"] == fallback
    assert status["state"]["next_action"] == "none"
    assert status["budget"]["usage"] == CodexImageGenerationBudgetUsage().model_dump(
        mode="json"
    )


@pytest.mark.parametrize(
    ("controller_status", "expected_status", "expected_trigger"),
    [
        ("timeout", "review_required", "controller_timeout"),
        ("failed", "review_required", "controller_failed"),
        ("rejected", "review_required", "controller_rejected"),
        ("cancelled", "cancelled", "controller_cancelled"),
    ],
)
def test_command_final_controller_result_binds_terminal_without_budget_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    controller_status: str,
    expected_status: str,
    expected_trigger: str,
) -> None:
    """Bind every final failure result and consume no generation budget on replay."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id=f"codex-controller-{controller_status}",
        material_boundary=True,
        fallback="review_required",
    )
    _initialize(fixture)
    controller = _DesktopOutcomeController(controller_status)
    monkeypatch.setattr(
        imagegen_command_service,
        "DesktopInSessionController",
        lambda: controller,
    )
    result = run_codex_imagegen_controller_phase(
        job_id=fixture.plan.job_id,
        session_id=fixture.session_id,
        rendered_prompt_text="Generate one bounded controller outcome swatch.",
        timeout_seconds=30,
    )
    assert result["status"] == expected_status
    assert result["controller_status"] == controller_status
    terminal_artifact = CodexImageArtifact.model_validate(
        result["generation_terminal"]
    )
    terminal = load_codex_image_model(
        fixture.root,
        terminal_artifact,
        imagegen_command_service.CodexImageGenerationTerminal,
    )
    request_artifact = CodexImageArtifact.model_validate(result["controller_request"])
    result_artifact = CodexImageArtifact.model_validate(result["controller_result"])
    assert terminal.status == expected_status
    assert terminal.runtime_trigger == expected_trigger
    assert terminal.plan_item_id == fixture.plan_item.plan_item_id
    assert terminal.controller_request == request_artifact
    assert terminal.controller_result == result_artifact
    assert request_artifact in terminal.provenance
    assert result_artifact in terminal.provenance
    assert terminal.budget_usage == CodexImageGenerationBudgetUsage()
    assert controller.calls == 1

    recovered = run_codex_imagegen_controller_phase(
        job_id=fixture.plan.job_id,
        session_id=fixture.session_id,
    )
    assert recovered["state"]["status"] == expected_status
    assert recovered["budget"]["usage"]["assignments"] == 0
    assert recovered["budget"]["usage"]["total_generations"] == 0
    assert controller.calls == 1


def test_capacity_terminal_recovers_after_state_write_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adopt an exact capacity terminal written before its overlay successor."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-capacity-terminal-crash",
        material_boundary=True,
        image_size=2048,
        fallback="user_image_required",
    )
    _initialize(fixture)
    real_terminalize = imagegen_command_service.terminalize_codex_image_phase

    def crash_before_state(*args: object, **kwargs: object) -> None:
        """Simulate process loss immediately after immutable terminal publication."""

        del args, kwargs
        raise RuntimeError("simulated terminal state crash")

    monkeypatch.setattr(
        imagegen_command_service,
        "terminalize_codex_image_phase",
        crash_before_state,
    )
    with pytest.raises(RuntimeError, match="terminal state crash"):
        run_codex_imagegen_controller_phase(
            job_id=fixture.plan.job_id,
            session_id=fixture.session_id,
            rendered_prompt_text="Generate one oversized crash fixture.",
            timeout_seconds=30,
        )
    assert get_codex_image_phase_status(fixture.root, fixture.session_id)["state"][
        "status"
    ] == "planned"
    terminal_path = (
        fixture.root
        / "production"
        / "autonomy_v2"
        / fixture.session_id
        / "codex_imagegen"
        / "terminal.json"
    )
    original = terminal_path.read_bytes()
    monkeypatch.setattr(
        imagegen_command_service,
        "terminalize_codex_image_phase",
        real_terminalize,
    )
    recovered = run_codex_imagegen_controller_phase(
        job_id=fixture.plan.job_id,
        session_id=fixture.session_id,
    )
    assert recovered["status"] == "user_image_required"
    assert terminal_path.read_bytes() == original
    assert recovered["next_action"] == "none"


def test_capacity_terminal_tamper_fails_before_state_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a validly shaped but changed crash-written terminal before adoption."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-capacity-terminal-tamper",
        material_boundary=True,
        image_size=2048,
        fallback="review_required",
    )
    _initialize(fixture)

    def crash_before_state(*args: object, **kwargs: object) -> None:
        """Leave the immutable terminal behind without publishing its overlay state."""

        del args, kwargs
        raise RuntimeError("simulated terminal state crash")

    monkeypatch.setattr(
        imagegen_command_service,
        "terminalize_codex_image_phase",
        crash_before_state,
    )
    with pytest.raises(RuntimeError, match="terminal state crash"):
        run_codex_imagegen_controller_phase(
            job_id=fixture.plan.job_id,
            session_id=fixture.session_id,
            rendered_prompt_text="Generate one oversized tamper fixture.",
            timeout_seconds=30,
        )
    terminal_path = (
        fixture.root
        / "production"
        / "autonomy_v2"
        / fixture.session_id
        / "codex_imagegen"
        / "terminal.json"
    )
    payload = json.loads(terminal_path.read_text(encoding="utf-8"))
    payload["reason"] = "tampered but model-valid reason"
    terminal_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="runtime terminal differs"):
        run_codex_imagegen_controller_phase(
            job_id=fixture.plan.job_id,
            session_id=fixture.session_id,
        )
    status = get_codex_image_phase_status(fixture.root, fixture.session_id)
    assert status["state"]["status"] == "planned"
    assert status["budget"]["usage"]["assignments"] == 0


def test_desktop_controller_waits_then_resumes_exact_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adopt desktop-authored outputs only after the same waiting request resumes."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-phase-desktop",
        material_boundary=True,
    )
    _initialize(fixture)
    assignment, assignment_artifact, waiting_state = _publish_waiting_assignment(
        fixture,
        prompt="Generate a neutral test swatch without text.",
    )
    base_path = Path(native_io_path(fixture.root / fixture.base_state_artifact.path))
    base_before = base_path.read_bytes()
    controller = DesktopInSessionController()
    first = execute_codex_imagegen_controller(
        job_root=fixture.root,
        assignment_artifact=assignment_artifact,
        controller=controller,
        created_at=fixture.created_at + timedelta(seconds=7),
        timeout_seconds=30,
    )
    assert first.result.status == "waiting_for_output"
    assert waiting_state.status == "waiting_for_controller"
    assert base_path.read_bytes() == base_before

    source = tmp_path / "desktop-imagegen-source" / "candidate.png"
    _write_generated_source(source)
    copy_imagegen_png_and_write_completion(
        controller_workspace_root=Path(
            native_io_path(first.controller_workspace_root)
        ),
        allowed_source_root=source.parent,
        assignment_path=Path(native_io_path(first.assignment_snapshot)),
        assignment_artifact=assignment_artifact,
        source_png_paths=[source],
        allowed_output_paths=tuple(
            Path(native_io_path(path)) for path in first.allowed_output_paths
        ),
        output_roles=["base_color"],
        completion_id=f"completion-{assignment.assignment_id}",
        controller_kind="desktop_in_session",
        controller_executed_at=fixture.created_at + timedelta(seconds=8),
    )
    resumed = execute_codex_imagegen_controller(
        job_root=fixture.root,
        assignment_artifact=assignment_artifact,
        controller=controller,
        created_at=fixture.created_at + timedelta(seconds=9),
        timeout_seconds=30,
    )
    assert resumed.result.status == "completed"
    assert resumed.request_artifact == first.request_artifact
    assert base_path.read_bytes() == base_before
    completion_artifact = _completion_artifact(fixture, assignment)
    state, _state_artifact = adopt_codex_image_completion(
        fixture.root,
        fixture.session_id,
        completion=completion_artifact,
        controller_request=resumed.request_artifact,
        controller_result=resumed.result_artifact,
        controller=controller,
        created_at=fixture.created_at + timedelta(seconds=10),
    )
    assert state.status == "completion_adopted"
    assert state.controller_request == resumed.request_artifact
    assert state.controller_result == resumed.result_artifact
    assert state.budget_usage.assignments == 1
    assert state.budget_usage.total_generations == 1
    assert base_path.read_bytes() == base_before


def test_fake_controller_completion_passes_full_phase_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the test-only fake through ControllerExecutor and phase adoption."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-phase-fake",
        material_boundary=True,
    )
    _initialize(fixture)
    assignment, assignment_artifact, _waiting = _publish_waiting_assignment(
        fixture,
        prompt="Generate one deterministic fake swatch.",
    )
    controller = FakeCodexImagegenController(
        assignment_artifact=assignment_artifact,
        executed_at=fixture.created_at + timedelta(seconds=7),
    )
    execution = execute_codex_imagegen_controller(
        job_root=fixture.root,
        assignment_artifact=assignment_artifact,
        controller=controller,
        created_at=fixture.created_at + timedelta(seconds=7),
        timeout_seconds=30,
    )
    assert execution.result.status == "completed"
    completion_artifact = _completion_artifact(fixture, assignment)
    state, _state_artifact = adopt_codex_image_completion(
        fixture.root,
        fixture.session_id,
        completion=completion_artifact,
        controller_request=execution.request_artifact,
        controller_result=execution.result_artifact,
        controller=controller,
        created_at=fixture.created_at + timedelta(seconds=8),
    )
    assert state.status == "completion_adopted"
    assert controller.calls == 1


@pytest.mark.parametrize("crash_after", [1, 2])
def test_completion_adoption_retry_recovers_partial_exact_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_after: int,
) -> None:
    """Resume after candidate or evidence publication without rewriting either file."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id=f"codex-completion-crash-{crash_after}",
        material_boundary=True,
    )
    _initialize(fixture)
    (
        _assignment,
        assignment_artifact,
        controller,
        completion_artifact,
        request_artifact,
        result_artifact,
    ) = _execute_fake_completion(fixture)
    real_write = imagegen_public_service.write_immutable_codex_image_model
    published: list[CodexImageArtifact] = []

    def crash_after_exact_write(*args: object, **kwargs: object) -> CodexImageArtifact:
        """Raise immediately after a configured immutable model reaches disk."""

        artifact = real_write(*args, **kwargs)
        published.append(artifact)
        if len(published) == crash_after:
            raise RuntimeError("simulated completion evidence publication crash")
        return artifact

    monkeypatch.setattr(
        imagegen_public_service,
        "write_immutable_codex_image_model",
        crash_after_exact_write,
    )
    adoption_args = {
        "job_root": fixture.root,
        "assignment_artifact": assignment_artifact,
        "completion_artifact": completion_artifact,
        "controller_request_artifact": request_artifact,
        "controller_result_artifact": result_artifact,
        "controller": controller,
        "created_at": fixture.created_at + timedelta(seconds=8),
    }
    with pytest.raises(RuntimeError, match="evidence publication crash"):
        adopt_codex_imagegen_completion(**adoption_args)
    published_bytes = {
        artifact.path: Path(native_io_path(fixture.root / artifact.path)).read_bytes()
        for artifact in published
    }

    monkeypatch.setattr(
        imagegen_public_service,
        "write_immutable_codex_image_model",
        real_write,
    )
    recovered = adopt_codex_imagegen_completion(**adoption_args)
    assert len(recovered.candidates) == 1
    assert len(recovered.generated_evidence) == 1
    for path, content in published_bytes.items():
        assert Path(native_io_path(fixture.root / path)).read_bytes() == content
    replayed = adopt_codex_imagegen_completion(**adoption_args)
    assert replayed == recovered


@pytest.mark.parametrize(
    ("crash_after", "tampered_leaf"),
    [(1, "candidate-00.json"), (2, "generated-image-evidence-00.json")],
)
def test_completion_adoption_retry_rejects_tampered_partial_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_after: int,
    tampered_leaf: str,
) -> None:
    """Fail closed when a crash-published candidate or evidence changes semantic scope."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id=f"codex-completion-tamper-{crash_after}",
        material_boundary=True,
    )
    _initialize(fixture)
    (
        _assignment,
        assignment_artifact,
        controller,
        completion_artifact,
        request_artifact,
        result_artifact,
    ) = _execute_fake_completion(fixture)
    real_write = imagegen_public_service.write_immutable_codex_image_model
    calls = 0

    def crash_after_exact_write(*args: object, **kwargs: object) -> CodexImageArtifact:
        """Publish a bounded prefix before simulating process loss."""

        nonlocal calls
        artifact = real_write(*args, **kwargs)
        calls += 1
        if calls == crash_after:
            raise RuntimeError("simulated partial publication crash")
        return artifact

    monkeypatch.setattr(
        imagegen_public_service,
        "write_immutable_codex_image_model",
        crash_after_exact_write,
    )
    adoption_args = {
        "job_root": fixture.root,
        "assignment_artifact": assignment_artifact,
        "completion_artifact": completion_artifact,
        "controller_request_artifact": request_artifact,
        "controller_result_artifact": result_artifact,
        "controller": controller,
        "created_at": fixture.created_at + timedelta(seconds=8),
    }
    with pytest.raises(RuntimeError, match="partial publication crash"):
        adopt_codex_imagegen_completion(**adoption_args)
    evidence_root = (
        fixture.root
        / "production"
        / "autonomy_v2"
        / fixture.session_id
        / "codex_imagegen"
        / "assignments"
        / "surface-00"
        / "evidence"
    )
    tampered_path = evidence_root / tampered_leaf
    payload = json.loads(Path(native_io_path(tampered_path)).read_text(encoding="utf-8"))
    payload["target_material_ids"] = ["material-tampered"]
    Path(native_io_path(tampered_path)).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        imagegen_public_service,
        "write_immutable_codex_image_model",
        real_write,
    )
    with pytest.raises(ValueError, match="evidence differs"):
        adopt_codex_imagegen_completion(**adoption_args)


@pytest.mark.parametrize("behavior", ["partial", "extra", "duplicate_completion"])
def test_fake_controller_invalid_output_sets_fail_executor_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    behavior: str,
) -> None:
    """Reject fake partial, extra, and duplicate outputs at the executor inventory gate."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id=f"codex-phase-fake-{behavior.replace('_', '-')}",
        material_boundary=True,
    )
    _initialize(fixture)
    _assignment, assignment_artifact, _waiting = _publish_waiting_assignment(
        fixture,
        prompt="Generate one bounded negative fixture.",
    )
    controller = FakeCodexImagegenController(
        assignment_artifact=assignment_artifact,
        behavior=behavior,
        executed_at=fixture.created_at + timedelta(seconds=7),
    )
    if behavior == "partial":
        execution = execute_codex_imagegen_controller(
            job_root=fixture.root,
            assignment_artifact=assignment_artifact,
            controller=controller,
            created_at=fixture.created_at + timedelta(seconds=7),
            timeout_seconds=30,
        )
        assert execution.result.status == "rejected"
        assert execution.result.outputs == []
        return

    with pytest.raises(ValueError, match="unexpected files"):
        execute_codex_imagegen_controller(
            job_root=fixture.root,
            assignment_artifact=assignment_artifact,
            controller=controller,
            created_at=fixture.created_at + timedelta(seconds=7),
            timeout_seconds=30,
        )


def test_fake_controller_wrong_hash_fails_completion_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a fake candidate changed after its completion digest was published."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-phase-fake-wrong-hash",
        material_boundary=True,
    )
    _initialize(fixture)
    assignment, assignment_artifact, _waiting = _publish_waiting_assignment(
        fixture,
        prompt="Generate one wrong-hash fixture.",
    )
    controller = FakeCodexImagegenController(
        assignment_artifact=assignment_artifact,
        behavior="wrong_hash",
        executed_at=fixture.created_at + timedelta(seconds=7),
    )
    execution = execute_codex_imagegen_controller(
        job_root=fixture.root,
        assignment_artifact=assignment_artifact,
        controller=controller,
        created_at=fixture.created_at + timedelta(seconds=7),
        timeout_seconds=30,
    )
    assert execution.result.status == "completed"
    with pytest.raises(ValueError, match="size changed|hash changed"):
        adopt_codex_image_completion(
            fixture.root,
            fixture.session_id,
            completion=_completion_artifact(fixture, assignment),
            controller_request=execution.request_artifact,
            controller_result=execution.result_artifact,
            controller=controller,
            created_at=fixture.created_at + timedelta(seconds=8),
        )


@pytest.mark.parametrize("tampered_target", ["request", "result"])
def test_phase_rejects_tampered_raw_controller_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tampered_target: str,
) -> None:
    """Reject exact-rebound request or result JSON that executor receipts cannot replay."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id=f"codex-phase-tampered-{tampered_target}",
        material_boundary=True,
    )
    _initialize(fixture)
    assignment, assignment_artifact, _waiting = _publish_waiting_assignment(
        fixture,
        prompt="Generate one fake swatch for tamper validation.",
    )
    controller = FakeCodexImagegenController(
        assignment_artifact=assignment_artifact,
        executed_at=fixture.created_at + timedelta(seconds=7),
    )
    execution = execute_codex_imagegen_controller(
        job_root=fixture.root,
        assignment_artifact=assignment_artifact,
        controller=controller,
        created_at=fixture.created_at + timedelta(seconds=7),
        timeout_seconds=30,
    )
    request_artifact = execution.request_artifact
    result_artifact = execution.result_artifact
    if tampered_target == "request":
        path = fixture.root / request_artifact.path
        tampered = execution.request.model_copy(
            update={"source_fingerprint": "f" * 64}
        )
        Path(native_io_path(path)).write_text(
            tampered.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        request_artifact = artifact_for_codex_image(
            fixture.root,
            path,
            artifact_id=request_artifact.artifact_id,
            kind=request_artifact.kind,
            media_type="application/json",
        )
    else:
        path = fixture.root / result_artifact.path
        tampered = execution.result.model_copy(update={"limitations": ["forged"]})
        Path(native_io_path(path)).write_text(
            tampered.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        result_artifact = artifact_for_codex_image(
            fixture.root,
            path,
            artifact_id=result_artifact.artifact_id,
            kind=result_artifact.kind,
            media_type="application/json",
        )
    with pytest.raises((ValueError, PermissionError)):
        adopt_codex_image_completion(
            fixture.root,
            fixture.session_id,
            completion=_completion_artifact(fixture, assignment),
            controller_request=request_artifact,
            controller_result=result_artifact,
            controller=controller,
            created_at=fixture.created_at + timedelta(seconds=8),
        )
    status = get_codex_image_phase_status(fixture.root, fixture.session_id)
    assert status["waiting_for_controller"] is True


def test_cancel_terminal_is_immutable_and_status_hides_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close a planned overlay once without exposing arbitrary terminal reason text."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-phase-cancel",
        material_boundary=False,
    )
    _initialize(fixture)
    private_reason = "private cancellation details must remain evidence-only"
    terminal_artifact = cancel_codex_imagegen(
        job_root=fixture.root,
        contract_id="cancel-terminal",
        terminal_id="cancel-terminal",
        plan_artifact=fixture.plan_artifact,
        budget=fixture.budget,
        budget_artifact=fixture.budget_artifact,
        budget_usage=CodexImageGenerationBudgetUsage(),
        reason=private_reason,
        created_at=fixture.created_at + timedelta(seconds=5),
    )
    state, _artifact = terminalize_codex_image_phase(
        fixture.root,
        fixture.session_id,
        event="cancelled",
        generation_terminal=terminal_artifact,
        created_at=fixture.created_at + timedelta(seconds=6),
    )
    assert state.status == "cancelled"
    status = get_codex_image_phase_status(fixture.root, fixture.session_id)
    assert status["terminal_reason_recorded"] is True
    assert private_reason not in json.dumps(status, sort_keys=True)
    with pytest.raises(ValueError, match="cannot transition"):
        terminalize_codex_image_phase(
            fixture.root,
            fixture.session_id,
            event="cancelled",
            generation_terminal=terminal_artifact,
            created_at=fixture.created_at + timedelta(seconds=7),
        )


def test_status_rejects_tampered_transition_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed when an immutable artifact named by the overlay changes on disk."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-phase-tamper",
        material_boundary=False,
    )
    _initialize(fixture)
    profile_path = fixture.root / fixture.provider_profile_artifact.path
    profile_path.write_bytes(profile_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="size changed|hash changed"):
        get_codex_image_phase_status(fixture.root, fixture.session_id)


def test_status_rejects_extra_overlay_state_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject extra files hidden beside the excluded append-only overlay state chain."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-phase-extra-state",
        material_boundary=False,
    )
    _initialize(fixture)
    states_root = (
        fixture.root
        / "production"
        / "autonomy_v2"
        / fixture.session_id
        / "codex_imagegen"
        / "overlay"
        / "states"
    )
    (states_root / "hidden.bin").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="extra member"):
        get_codex_image_phase_status(fixture.root, fixture.session_id)


def test_public_command_service_waits_resumes_and_selects_without_host_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive one Desktop assignment through completion and deterministic selection."""

    fixture = _phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="codex-command-flow",
        material_boundary=True,
    )
    _initialize(fixture)
    wrong_text_path, _wrong_text_artifact = _write_exact_text_evidence(
        fixture,
        text="BA",
        name="codex-command-wrong-text",
    )
    exact_text_path, exact_text_artifact = _write_exact_text_evidence(
        fixture,
        text="AB",
        name="codex-command-exact-text",
    )
    exact_text_font = _write_bitmap_font(fixture)
    first = run_codex_imagegen_controller_phase(
        job_id="codex-command-flow",
        session_id=fixture.session_id,
        rendered_prompt_text="Generate a neutral wood swatch without any text.",
        exact_text_value="AB",
        timeout_seconds=30,
    )
    assert first["status"] == "waiting_for_output"
    assert first["repository_invoked_imagegen"] is False
    assignment_artifact = CodexImageArtifact.model_validate(first["assignment"])
    source = tmp_path / "command-imagegen-source" / "candidate.png"
    _write_generated_source(source)
    copy_imagegen_png_and_write_completion(
        controller_workspace_root=Path(first["controller_workspace_root"]),
        allowed_source_root=source.parent,
        assignment_path=Path(first["assignment_snapshot"]),
        assignment_artifact=assignment_artifact,
        source_png_paths=[source],
        allowed_output_paths=tuple(Path(path) for path in first["allowed_output_paths"]),
        output_roles=["base_color"],
        completion_id="completion-material-00",
        controller_kind="desktop_in_session",
        controller_executed_at=fixture.created_at + timedelta(seconds=8),
    )
    resumed = run_codex_imagegen_controller_phase(
        job_id="codex-command-flow",
        session_id=fixture.session_id,
        rendered_prompt_text="Generate a neutral wood swatch without any text.",
        exact_text_value="AB",
        timeout_seconds=30,
    )
    assert resumed["status"] == "completed"
    assert resumed["next_action"] == "evaluate_quality"
    selected = select_codex_imagegen_phase(
        job_id="codex-command-flow",
        session_id=fixture.session_id,
    )
    assert selected["selection"]["outcome"] == "selected"
    assert selected["human_reviewed"] is False
    assert selected["semantic_checks_authoritative"] is False
    assert selected["next_action"] == "adopt_material"
    with pytest.raises(ValueError, match="differs from the assignment"):
        prepare_codex_imagegen_material_adoption(
            job_id="codex-command-flow",
            session_id=fixture.session_id,
            material_strategy="codex_generated_decal_v1",
            exact_text_evidence_path=wrong_text_path,
        )
    prepared = prepare_codex_imagegen_material_adoption(
        job_id="codex-command-flow",
        session_id=fixture.session_id,
        material_strategy="codex_generated_decal_v1",
        exact_text_evidence_path=exact_text_path,
    )
    assert prepared["status"] == "material_request_required"
    assert prepared["adoption"]["direct_channels"] == ["base_color"]
    adopted_text_artifact = ExactArtifact.model_validate(
        prepared["adoption"]["exact_text_composition"]
    )
    assert adopted_text_artifact.path == exact_text_artifact.path
    assert adopted_text_artifact.sha256 == exact_text_artifact.sha256
    assert prepared["canonical_material_unchanged"] is True
    selection_artifact = CodexImageArtifact.model_validate(
        selected["selection_artifact"]
    )
    selection = load_codex_image_model(
        fixture.root,
        selection_artifact,
        CodexImageGenerationSelection,
    )
    assert selection.selected_candidate is not None
    assert selection.selected_quality_report is not None
    candidate = load_codex_image_model(
        fixture.root,
        selection.selected_candidate,
        CodexImageGenerationCandidate,
    )
    report = load_codex_image_model(
        fixture.root,
        selection.selected_quality_report,
        CodexImageGenerationQualityReport,
    )
    scale, uv, v05 = _material_scale_and_uv(fixture)
    request = CodexImageMaterialAuthoringRequestV021(
        request_id="codex-command-material-request",
        job_id=fixture.plan.job_id,
        workflow_id=fixture.plan.workflow_id,
        run_id="codex-command-material-run",
        material_id="material-main",
        strategy="codex_generated_decal_v1",
        material_family="signage_decal",
        output_root=(
            "material_authoring/codex_imagegen/runs/codex-command-material-run"
        ),
        core_evidence=CodexImageEvidenceBindingsV021(
            selection=_material_artifact(selection_artifact),
            selected_evidence=_material_artifact(report.generated_image_evidence),
            selected_quality_report=_material_artifact(
                selection.selected_quality_report
            ),
            adoption=ExactArtifact.model_validate(prepared["adoption_artifact"]),
        ),
        source=CodexImageMaterialSourceV021(
            artifact=_material_artifact(candidate.generated_file.artifact),
            width=candidate.generated_file.width,
            height=candidate.generated_file.height,
            direct_role="base_color",
            color_space="srgb",
            license_id="codex-project-generation-fixture",
            rights_status="project_owned",
            provenance="deterministic fake controller fixture",
        ),
        source_v05_contracts=[v05],
        uv_identity=uv,
        scale_context=scale,
        derivation=LocalImageDerivationPolicyV021(
            output_resolution=256,
            minimum_spatial_standard_deviation=0.0,
        ),
        exact_text=ExactTextCompositionV021(
            evidence="exact_user_text",
            text="AB",
            text_evidence_artifact=adopted_text_artifact,
            font=exact_text_font,
            uv_rect=UVRect(minimum=(0.2, 0.2), maximum=(0.8, 0.8)),
            font_size_px=20,
        ),
        created_at=fixture.created_at + timedelta(seconds=10),
    )
    request_path = fixture.root / "production" / "codex-material-request.json"
    request_path.write_text(
        json.dumps(request.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    adopted = adopt_codex_imagegen_material_phase(
        job_id="codex-command-flow",
        session_id=fixture.session_id,
        material_request_path=request_path,
    )
    assert adopted["status"] == "adopted"
    assert adopted["next_action"] == "controller_promotion_required"
    assert adopted["canonical_material_unchanged"] is True
    assert adopted["actual_codex_imagegen_execution_verified"] is False
    recovered = adopt_codex_imagegen_material_phase(
        job_id="codex-command-flow",
        session_id=fixture.session_id,
        material_request_path=request_path,
    )
    assert recovered["status"] == "adopted"
    assert recovered["next_action"] == "controller_promotion_required"
    assert recovered["material_receipt"] == adopted["material_receipt"]
    status = get_codex_imagegen_public_status(
        job_id="codex-command-flow",
        session_id=fixture.session_id,
    )
    assert status["waiting_assignment_count"] == 0
    assert status["latest_completion"] is not None
    assert status["actual_codex_imagegen_execution_verified"] is False
