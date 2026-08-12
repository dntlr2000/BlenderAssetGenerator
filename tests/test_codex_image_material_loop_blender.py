"""Opt-in Blender 5 vertical smoke for the Codex ImageGen material loop."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import test_autonomy_v2_candidate_validation_blender as geometry_fixtures
from PIL import Image

from codex_blender_modeler.autonomy_v2.candidate_validation_models import (
    GeometryAuthoringCompletionV2,
    GeometryCandidateValidationReceiptV2,
)
from codex_blender_modeler.autonomy_v2.candidate_validation_service import (
    validate_and_promote_geometry_candidate_v2,
)
from codex_blender_modeler.autonomy_v2.controller_bridge import (
    _session_bundle,
    execute_autonomy_v2_controller,
)
from codex_blender_modeler.autonomy_v2.delivery_service import artifact_for_v2
from codex_blender_modeler.autonomy_v2.models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyStateV2,
    RootAuthorizationV2,
)
from codex_blender_modeler.autonomy_v2.planner import plan_autonomous_static_prop_v2
from codex_blender_modeler.autonomy_v2.supervisor_service import (
    _controller_validation_boundary,
)
from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.codex_imagegen import (
    CodexImageArtifact,
    CodexImageDimensions,
    CodexImageGenerationBudgetUsage,
    CodexImageGenerationPlanItem,
    ImageToMaterialAdoption,
    artifact_for_codex_image,
    build_codex_builtin_image_provider_profile,
    build_codex_imagegen_assignment,
    build_codex_imagegen_plan,
    build_default_codex_imagegen_budget,
    write_immutable_codex_image_model,
)
from codex_blender_modeler.codex_imagegen.controller_bridge import (
    execute_codex_imagegen_controller,
)
from codex_blender_modeler.codex_imagegen.public_service import (
    plan_codex_imagegen,
    run_codex_imagegen,
)
from codex_blender_modeler.production.controller_executor import FakeControllerForTests

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_BLENDER_SMOKE") != "1",
    reason=("set CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_BLENDER_SMOKE=1 for the Blender smoke"),
)

_JOB_ID = "codex_image_material_loop_smoke"
_MATERIAL_ID = "mat.body"
_SEMANTIC_ID = "asset.hull"
_ACTUAL_WOOD_PROMPT = (
    "Create a square seamless wood surface swatch for a Blender base-color texture. "
    "Warm medium-brown natural grain with subtle knots and fine longitudinal fibers, "
    "even neutral diffuse lighting, orthographic flat material sample, edge-to-edge "
    "texture. No object, furniture, scene, perspective, shadows, text, letters, "
    "numbers, logo, watermark, frame, border, normal-map colors, or UI."
)
_ACTUAL_WOOD_PROMPT_SHA256 = (
    "aa6b6e372ddae92d58845591977878e111f7f1ca2b5fc997024fc03a1cf92b1a"
)


@dataclass(frozen=True)
class _MaterialCase:
    """Describe one allowed ImageGen material-family contract for the vertical smoke."""

    family: str
    slug: str
    strategy: str
    direct_role: str
    semantic_role: str
    generation_intent: str
    prompt: str


_MATERIAL_CASES = (
    _MaterialCase(
        family="wood",
        slug="wood",
        strategy="codex_generated_procedural_hybrid_v1",
        direct_role="base_color",
        semantic_role="wood-grain",
        generation_intent="generated_image_procedural_hybrid_v1",
        prompt="Generate a neutral wood grain swatch without text.",
    ),
    _MaterialCase(
        family="signage_decal",
        slug="signage-decal",
        strategy="codex_generated_decal_v1",
        direct_role="decal_rgb",
        semantic_role="signage-background",
        generation_intent="generated_decal_art_v1",
        prompt="Generate a neutral blank signage decal background without text.",
    ),
    _MaterialCase(
        family="emissive",
        slug="emissive",
        strategy="codex_generated_emission_v1",
        direct_role="emission",
        semantic_role="emission-pattern",
        generation_intent="generated_emission_pattern_v1",
        prompt="Generate an abstract emissive energy pattern without text.",
    ),
    _MaterialCase(
        family="crystal",
        slug="crystal",
        strategy="codex_generated_procedural_hybrid_v1",
        direct_role="base_color",
        semantic_role="crystal-pattern",
        generation_intent="generated_image_procedural_hybrid_v1",
        prompt="Generate an abstract crystal surface pattern without text.",
    ),
)


@dataclass(frozen=True)
class _GeometryFixture:
    """Carry the exact AQ material boundary produced by real geometry promotion."""

    root: Path
    session_id: str
    plan: AutonomyPlanV2
    budget: AutonomyBudgetV2
    state: AutonomyStateV2
    state_artifact: AQV2Artifact
    authorization: RootAuthorizationV2
    receipt: GeometryCandidateValidationReceiptV2
    receipt_artifact: AQV2Artifact


@dataclass(frozen=True)
class _ImageFixture:
    """Carry one exact fake or supplied ImageGen lifecycle selected for authoring."""

    provider_profile: CodexImageArtifact
    generation_plan: CodexImageArtifact
    assignment: CodexImageArtifact
    completion: CodexImageArtifact
    controller_request: CodexImageArtifact
    controller_result: CodexImageArtifact
    selection: CodexImageArtifact
    selected_candidate: CodexImageArtifact
    generated_evidence: CodexImageArtifact
    quality_report: CodexImageArtifact
    exact_text_evidence: CodexImageArtifact | None
    actual_builtin_source_used: bool
    fake_source_used: bool


class _ExactSourceCodexImagegenController:
    """Copy one externally supplied, hash-bound PNG through the current assignment."""

    def __init__(
        self,
        *,
        assignment_artifact: CodexImageArtifact,
        source_path: Path,
        expected_source_sha256: str,
        expected_prompt_sha256: str,
        executed_at: datetime,
        controller_kind: str = "desktop_in_session",
    ) -> None:
        """Freeze the exact source and prompt bindings for one controller invocation."""

        self.assignment_artifact = assignment_artifact
        self.source_path = source_path
        self.expected_source_sha256 = expected_source_sha256
        self.expected_prompt_sha256 = expected_prompt_sha256
        self.executed_at = executed_at
        self.controller_kind = controller_kind
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
        """Verify and copy the supplied PNG into the unique controller completion."""

        from codex_blender_modeler.codex_imagegen.completion import (
            copy_imagegen_png_and_write_completion,
        )
        from codex_blender_modeler.codex_imagegen.models import (
            CodexImageGenerationAssignment,
        )

        del immutable_inputs, timeout_seconds
        self.calls += 1
        if getattr(tool_profile, "network_access", None) != "denied":
            raise ValueError("actual-source fixture requires denied network authority")
        assignment_model = CodexImageGenerationAssignment.model_validate_json(
            assignment.read_bytes()
        )
        if assignment_model.prompt_sha256 != self.expected_prompt_sha256:
            raise ValueError("actual-source prompt hash differs from the assignment")
        if sha256_file(self.source_path) != self.expected_source_sha256:
            raise ValueError("actual-source PNG hash differs from the expected SHA-256")
        copy_imagegen_png_and_write_completion(
            controller_workspace_root=Path(
                os.path.commonpath([assignment, *allowed_output_paths])
            ),
            allowed_source_root=self.source_path.parent,
            assignment_path=assignment,
            assignment_artifact=self.assignment_artifact,
            source_png_paths=[self.source_path],
            allowed_output_paths=allowed_output_paths,
            output_roles=[assignment_model.allowed_output_roles[0]],
            completion_id=f"completion-{assignment_model.assignment_id}",
            controller_kind=self.controller_kind,
            controller_executed_at=self.executed_at,
        )
        return "completed"


def _codex_json(root: Path, artifact: AQV2Artifact) -> CodexImageArtifact:
    """Project one rehashed AQ artifact into the JSON companion shape."""

    return artifact_for_codex_image(
        root,
        root / artifact.path,
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        media_type="application/json",
    )


def _write_fake_material_source(path: Path, *, size: int = 64) -> None:
    """Write a deterministic seamless RGBA pattern that passes local hard gates."""

    image = Image.new("RGBA", (size, size))
    pixels = image.load()
    for y in range(size):
        source_y = 0 if y == size - 1 else y
        for x in range(size):
            source_x = 0 if x == size - 1 else x
            band = ((source_x // 8) + (source_y // 8)) % 2
            value = 72 + band * 144
            pixels[x, y] = (value, min(255, value + 24), 255 - value // 2, 255)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


def _geometry_material_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> _GeometryFixture:
    """Run the existing actual geometry controller, Blender validation, and promotion."""

    workspace = tmp_path / "w"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "r.png"
    Image.new("RGB", (32, 32), (48, 96, 144)).save(reference)
    planned = plan_autonomous_static_prop_v2(
        "Create only the fixture hull.",
        reference_path=reference,
        target_subject="fixture hull",
        requested_delivery_profiles=["review_only"],
        job_id=_JOB_ID,
        allow_disabled_experimental=True,
    )
    session_id = str(planned["session_id"])
    root = workspace / _JOB_ID
    session_root = root / "production" / "autonomy_v2" / session_id
    authorization = RootAuthorizationV2.model_validate_json(
        (session_root / "root_authorization.json").read_bytes()
    )
    reference_relative = authorization.primary_reference.path
    reference_sha256 = sha256_file(root / reference_relative)
    geometry_fixtures._write_json(
        root / "analysis/reference_analysis.json",
        geometry_fixtures._reference_analysis(
            _JOB_ID,
            reference_relative,
            reference_sha256,
        ),
    )
    geometry_fixtures._write_json(
        root / "analysis/camera_solution.json",
        geometry_fixtures._camera_solution(_JOB_ID),
    )
    geometry_fixtures._write_json(
        root / "analysis/modeling_plan.json",
        geometry_fixtures._modeling_plan(_JOB_ID, "baseline"),
    )
    from codex_blender_modeler.autonomy_v2.supervisor_service import (
        advance_autonomy_v2,
    )

    reference_advance = advance_autonomy_v2(
        _JOB_ID,
        session_id,
        allow_disabled_experimental=True,
    )
    assert reference_advance["outcome"] == "reference_ready"
    reference_analysis = json.loads(
        (root / "analysis" / "reference_analysis.json").read_text(encoding="utf-8")
    )
    reference_source_id = reference_analysis["images"][0]["source_id"]
    root, session_root, plan, budget, _state, _artifact = _session_bundle(
        _JOB_ID,
        session_id,
    )
    profile_artifact = next(
        item for item in plan.phase_tool_profiles if item.path.endswith("/geometry_authoring.json")
    )
    input_root = session_root / "vertical_inputs"
    geometry_fixtures._write_json(
        input_root / "assignment.json",
        {"phase": "geometry_authoring"},
    )
    assignment = artifact_for_v2(
        root,
        input_root / "assignment.json",
        artifact_id="geometry-assignment",
        kind="assignment",
    )
    immutable_inputs = [
        artifact_for_v2(
            root,
            root / reference_relative,
            artifact_id="primary-reference-input",
            kind="reference",
        ),
        artifact_for_v2(
            root,
            root / "analysis/reference_analysis.json",
            artifact_id="reference-analysis-input",
            kind="reference",
        ),
        artifact_for_v2(
            root,
            root / "analysis/camera_solution.json",
            artifact_id="camera-solution-input",
            kind="camera",
        ),
        artifact_for_v2(
            root,
            root / "analysis/modeling_plan.json",
            artifact_id="modeling-baseline-input",
            kind="baseline-scene",
        ),
    ]
    modeling_bytes = geometry_fixtures._json_bytes(
        geometry_fixtures._modeling_plan(_JOB_ID, "candidate")
    )
    scene_bytes = geometry_fixtures._json_bytes(
        geometry_fixtures._scene_v03(_JOB_ID, reference_relative)
    )
    modeling_payload = json.loads(modeling_bytes)
    modeling_payload["objects"][0]["source_ids"] = [reference_source_id]
    modeling_bytes = geometry_fixtures._json_bytes(modeling_payload)
    scene_payload = json.loads(scene_bytes)
    scene_payload["sources"][0]["id"] = reference_source_id
    scene_payload["objects"][0]["evidence"][0]["source_id"] = reference_source_id
    camera_solution = json.loads(
        (root / "analysis" / "camera_solution.json").read_text(encoding="utf-8")
    )
    camera = scene_payload["camera"]
    camera["projection"] = camera_solution["projection"]
    camera["focal_length_mm"] = camera_solution["focal_length_mm"]
    camera["location"] = [0.0, 0.0, 0.0]
    camera["target"] = camera_solution["view_direction"]
    scene_bytes = geometry_fixtures._json_bytes(scene_payload)
    completion = GeometryAuthoringCompletionV2(
        job_id=_JOB_ID,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=session_id,
        execution_id="exec-0002-geometry_authoring",
        assignment_sha256=assignment.sha256,
        tool_profile_sha256=profile_artifact.sha256,
        outputs=[
            {
                "name": "modeling_plan.json",
                "sha256": hashlib.sha256(modeling_bytes).hexdigest(),
                "byte_size": len(modeling_bytes),
            },
            {
                "name": "scene_spec_v03.json",
                "sha256": hashlib.sha256(scene_bytes).hexdigest(),
                "byte_size": len(scene_bytes),
            },
        ],
    )
    response = execute_autonomy_v2_controller(
        _JOB_ID,
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=immutable_inputs,
        controller=FakeControllerForTests(
            payloads={
                "modeling_plan.json": modeling_bytes,
                "scene_spec_v03.json": scene_bytes,
                "completion.json": geometry_fixtures._json_bytes(completion),
            }
        ),
        timeout_seconds=60,
    )
    assert response["result"]["status"] == "completed"
    root, session_root, plan, budget, state, _artifact = _session_bundle(
        _JOB_ID,
        session_id,
    )
    receipt, receipt_artifact = validate_and_promote_geometry_candidate_v2(
        job_root=root,
        session_root=session_root,
        plan=plan,
        budget=budget,
        state=state,
        authorization=authorization,
    )
    advanced = _controller_validation_boundary(
        root,
        session_root,
        plan,
        budget,
        state,
        authorization,
    )
    assert advanced["outcome"] == "geometry_candidate_validated"
    root, _session_root, plan, budget, state, state_artifact = _session_bundle(
        _JOB_ID,
        session_id,
    )
    assert (state.phase, state.status, state.next_action) == (
        "authoring",
        "running",
        "execute_controller",
    )
    return _GeometryFixture(
        root=root,
        session_id=session_id,
        plan=plan,
        budget=budget,
        state=state,
        state_artifact=state_artifact,
        authorization=authorization,
        receipt=receipt,
        receipt_artifact=receipt_artifact,
    )


def _fake_imagegen_selection(
    fixture: _GeometryFixture,
    case: _MaterialCase,
    *,
    created_at: datetime,
) -> _ImageFixture:
    """Run fake or exact supplied ImageGen through the formal controller boundary."""

    from codex_blender_modeler.autonomy_v2.codex_image_phase_service import (
        adopt_codex_image_completion,
        initialize_codex_image_phase,
        publish_codex_image_assignment,
        record_codex_image_quality,
        record_codex_image_selection,
    )
    from codex_blender_modeler.codex_imagegen.artifacts import load_codex_image_model
    from codex_blender_modeler.codex_imagegen.models import (
        CodexImageGenerationQualityReport,
    )
    from codex_blender_modeler.codex_imagegen.public_service import (
        adopt_codex_imagegen_completion as adopt_public_completion,
    )
    from codex_blender_modeler.codex_imagegen.public_service import (
        select_codex_imagegen_candidate,
    )
    from codex_blender_modeler.codex_imagegen.quality import evaluate_candidate_quality

    base_plan = _codex_json(
        fixture.root,
        artifact_for_v2(
            fixture.root,
            fixture.root / "production" / "autonomy_v2" / fixture.session_id / "plan.json",
            artifact_id=f"plan-{fixture.session_id}",
            kind="plan",
        ),
    )
    base_authorization = _codex_json(fixture.root, fixture.plan.root_authorization)
    profile = build_codex_builtin_image_provider_profile(
        contract_id=f"codex-profile-{fixture.session_id}",
        provider_profile_id=f"codex-profile-{fixture.session_id}",
        job_id=_JOB_ID,
        workflow_id=fixture.plan.workflow_id,
        dispatch_id=fixture.plan.dispatch_id,
        session_id=fixture.session_id,
        base_profile_artifact=base_plan,
        created_at=created_at,
    )
    codex_root = fixture.root / "production" / "autonomy_v2" / fixture.session_id / "codex_imagegen"
    profile_artifact = write_immutable_codex_image_model(
        fixture.root,
        codex_root / "provider-profile.json",
        profile,
        kind="codex-builtin-image-provider-profile",
    )
    budget = build_default_codex_imagegen_budget(
        contract_id=f"codex-budget-{fixture.session_id}",
        budget_id=f"codex-budget-{fixture.session_id}",
        job_id=_JOB_ID,
        workflow_id=fixture.plan.workflow_id,
        dispatch_id=fixture.plan.dispatch_id,
        session_id=fixture.session_id,
        provider_profile=profile_artifact,
        created_at=created_at,
    )
    budget_artifact = write_immutable_codex_image_model(
        fixture.root,
        codex_root / "budget.json",
        budget,
        kind="codex-image-generation-budget",
    )
    exact_text_evidence = (
        _publish_exact_text_evidence(fixture, created_at=created_at)
        if case.family == "signage_decal"
        else None
    )
    actual_source_value = os.environ.get("CBM_CODEX_IMAGEGEN_ACTUAL_SOURCE_PATH")
    use_actual_source = case.family == "wood" and bool(actual_source_value)
    rendered_prompt = _ACTUAL_WOOD_PROMPT if use_actual_source else case.prompt
    image_size = CodexImageDimensions(width=64, height=64)
    if use_actual_source:
        with Image.open(Path(str(actual_source_value))) as opened:
            width, height = opened.size
        image_size = CodexImageDimensions(width=width, height=height)
    item = CodexImageGenerationPlanItem(
        plan_item_id=f"{case.slug}-swatch",
        target_material_ids=[_MATERIAL_ID],
        semantic_roles=[case.semantic_role],
        generation_intent=case.generation_intent,
        allowed_output_roles=[case.direct_role],
        prompt_template_id=f"{case.slug}-swatch-v1",
        requested_candidate_count=1,
        quality_level="medium" if use_actual_source else "low",
        image_size=image_size,
        aspect_ratio="square",
        fallback="review_required",
    )
    image_plan = build_codex_imagegen_plan(
        contract_id=f"codex-plan-{fixture.session_id}",
        plan_id=f"codex-plan-{fixture.session_id}",
        job_id=_JOB_ID,
        workflow_id=fixture.plan.workflow_id,
        dispatch_id=fixture.plan.dispatch_id,
        session_id=fixture.session_id,
        base_autonomy_plan=base_plan,
        base_root_authorization=base_authorization,
        provider_profile=profile,
        provider_profile_artifact=profile_artifact,
        budget=budget,
        budget_artifact=budget_artifact,
        items=[item],
        created_at=created_at,
    )
    plan_artifact = plan_codex_imagegen(job_root=fixture.root, plan=image_plan)
    initialize_codex_image_phase(
        fixture.root,
        generation_plan=plan_artifact,
        provider_profile=profile_artifact,
        budget=budget_artifact,
        created_at=created_at + timedelta(seconds=1),
        allow_disabled_experimental=True,
    )
    assignment = build_codex_imagegen_assignment(
        contract_id=f"assignment-{case.slug}-00",
        assignment_id=f"{case.slug}-00",
        sequence=0,
        plan=image_plan,
        plan_artifact=plan_artifact,
        plan_item=item,
        provider_profile_artifact=profile_artifact,
        budget=budget,
        budget_artifact=budget_artifact,
        usage=CodexImageGenerationBudgetUsage(),
        base_state_artifact=_codex_json(fixture.root, fixture.state_artifact),
        job_root=fixture.root,
        rendered_prompt_text=rendered_prompt,
        reference_images=[],
        created_at=created_at + timedelta(seconds=2),
        exact_text_value="AB" if case.family == "signage_decal" else None,
    )
    assignment_artifact = run_codex_imagegen(
        job_root=fixture.root,
        assignment=assignment,
    )
    publish_codex_image_assignment(
        fixture.root,
        fixture.session_id,
        assignment=assignment_artifact,
        created_at=created_at + timedelta(seconds=3),
    )
    if use_actual_source:
        expected_source_sha256 = os.environ.get(
            "CBM_CODEX_IMAGEGEN_ACTUAL_SOURCE_SHA256"
        )
        expected_prompt_sha256 = os.environ.get(
            "CBM_CODEX_IMAGEGEN_ACTUAL_PROMPT_SHA256",
            _ACTUAL_WOOD_PROMPT_SHA256,
        )
        if expected_source_sha256 is None or expected_prompt_sha256 is None:
            raise ValueError(
                "actual ImageGen source requires exact source and prompt SHA-256 values"
            )
        if expected_prompt_sha256 != _ACTUAL_WOOD_PROMPT_SHA256:
            raise ValueError("actual-source expected prompt SHA differs from historical evidence")
        controller = _ExactSourceCodexImagegenController(
            assignment_artifact=assignment_artifact,
            source_path=Path(actual_source_value),
            expected_source_sha256=expected_source_sha256,
            expected_prompt_sha256=expected_prompt_sha256,
            executed_at=created_at + timedelta(seconds=4),
        )
    else:
        fake_source = fixture.root.parent / f"{case.slug}-fake-source.png"
        _write_fake_material_source(fake_source)
        controller = _ExactSourceCodexImagegenController(
            assignment_artifact=assignment_artifact,
            source_path=fake_source,
            expected_source_sha256=sha256_file(fake_source),
            expected_prompt_sha256=assignment.prompt_sha256,
            executed_at=created_at + timedelta(seconds=4),
            controller_kind="fake_for_tests",
        )
    execution = execute_codex_imagegen_controller(
        job_root=fixture.root,
        assignment_artifact=assignment_artifact,
        controller=controller,
        created_at=created_at + timedelta(seconds=4),
        timeout_seconds=30,
    )
    assert execution.result.status == "completed"
    completion_artifact = artifact_for_codex_image(
        fixture.root,
        fixture.root / assignment.completion_file_target,
        artifact_id=f"completion-{assignment.assignment_id}",
        kind="codex-image-generation-completion",
        media_type="application/json",
    )
    adopt_codex_image_completion(
        fixture.root,
        fixture.session_id,
        completion=completion_artifact,
        controller_request=execution.request_artifact,
        controller_result=execution.result_artifact,
        controller=controller,
        created_at=created_at + timedelta(seconds=5),
    )
    adopted_public = adopt_public_completion(
        job_root=fixture.root,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        controller_request_artifact=execution.request_artifact,
        controller_result_artifact=execution.result_artifact,
        controller=controller,
        created_at=created_at + timedelta(seconds=5),
    )
    candidates = list(adopted_public.candidates)
    generated_evidence = list(adopted_public.generated_evidence)
    assert len(candidates) == len(generated_evidence) == 1
    candidate, candidate_artifact = candidates[0]
    generated, generated_artifact = generated_evidence[0]
    quality = evaluate_candidate_quality(
        job_root=fixture.root,
        report_id=f"quality-{assignment.assignment_id}-00",
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        generated_image_evidence=generated,
        generated_image_evidence_artifact=generated_artifact,
        created_at=created_at + timedelta(seconds=6),
    )
    quality_artifact = write_immutable_codex_image_model(
        fixture.root,
        fixture.root
        / Path(candidate_artifact.path).parent
        / "quality-00.json",
        quality,
        kind="codex-image-generation-quality-report",
    )
    assert quality.outcome == "passed"
    record_codex_image_quality(
        fixture.root,
        fixture.session_id,
        candidates=[candidate_artifact],
        quality_reports=[quality_artifact],
        created_at=created_at + timedelta(seconds=7),
    )
    selection, selection_artifact = select_codex_imagegen_candidate(
        job_root=fixture.root,
        selection_id=f"selection-{assignment.assignment_id}",
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidates=candidates,
        quality_reports=[(quality, quality_artifact)],
        created_at=created_at + timedelta(seconds=8),
    )
    record_codex_image_selection(
        fixture.root,
        fixture.session_id,
        selection=selection_artifact,
        created_at=created_at + timedelta(seconds=9),
    )
    assert selection.selected_candidate is not None
    assert selection.selected_quality_report is not None
    quality = load_codex_image_model(
        fixture.root,
        selection.selected_quality_report,
        CodexImageGenerationQualityReport,
    )
    return _ImageFixture(
        provider_profile=profile_artifact,
        generation_plan=plan_artifact,
        assignment=assignment_artifact,
        completion=completion_artifact,
        controller_request=execution.request_artifact,
        controller_result=execution.result_artifact,
        selection=selection_artifact,
        selected_candidate=selection.selected_candidate,
        generated_evidence=quality.generated_image_evidence,
        quality_report=selection.selected_quality_report,
        exact_text_evidence=exact_text_evidence,
        actual_builtin_source_used=use_actual_source,
        fake_source_used=not use_actual_source,
    )


def _write_json_model(path: Path, value: object) -> None:
    """Write one strict test model using stable indented JSON bytes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _publish_exact_text_evidence(
    fixture: _GeometryFixture,
    *,
    created_at: datetime,
) -> CodexImageArtifact:
    """Publish exact AB signage text without placing it in the ImageGen prompt."""

    from codex_blender_modeler.material_authoring.codex_image_models import (
        ExactSignageTextEvidenceV021,
    )

    text = "AB"
    evidence = ExactSignageTextEvidenceV021(
        evidence_id="material-loop-signage-text",
        text=text,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        created_at=created_at,
    )
    path = fixture.root / "analysis" / "material_loop_signage_text.json"
    _write_json_model(path, evidence)
    return artifact_for_codex_image(
        fixture.root,
        path,
        artifact_id="material-loop-signage-text",
        kind="exact-signage-text-evidence",
        media_type="application/json",
    )


def _publish_bitmap_font(fixture: _GeometryFixture):
    """Publish a project-owned bitmap font containing the exact AB glyph set."""

    from codex_blender_modeler.material_authoring.models import ProjectLocalFont

    path = fixture.root / "assets" / "fonts" / "material-loop-font.json"
    _write_json_model(
        path,
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
    )
    artifact = artifact_for_codex_image(
        fixture.root,
        path,
        artifact_id="material-loop-font",
        kind="project-local-bitmap-font",
        media_type="application/json",
    )
    return ProjectLocalFont(
        artifact=_material_exact(artifact),
        font_format="bitmap_json_v1",
        license_id="fixture-project-owned",
        rights_status="project_owned",
        provenance="deterministic pytest bitmap font",
    )


def _material_exact(artifact: CodexImageArtifact):
    """Project one companion artifact into the identical material exact type."""

    from codex_blender_modeler.material_authoring.models import ExactArtifact

    return ExactArtifact.model_validate(artifact.model_dump(mode="python"))


def _publish_material_baseline(fixture: _GeometryFixture):
    """Publish the canonical V0.5 baseline required by the additive bridge."""

    from codex_blender_modeler.material_authoring.models import ExactArtifact
    from codex_blender_modeler.materials.models import (
        MappingSpec,
        MaterialPlan,
        MaterialPlanItem,
    )

    baseline = MaterialPlan(
        job_id=_JOB_ID,
        stage="scaffold",
        materials=[
            MaterialPlanItem(
                material_id=_MATERIAL_ID,
                label="Fixture body",
                texture_strategy="none",
                mapping=MappingSpec(mode="object", real_world_scale_m=1.0),
                evidence_status="observed",
                confidence=1.0,
                notes=["Geometry-promotion baseline before ImageGen material adoption."],
            )
        ],
        global_notes=["Test-only baseline; no user material approval is implied."],
    )
    path = fixture.root / "analysis" / "material_plan.json"
    _write_json_model(path, baseline)
    artifact = artifact_for_codex_image(
        fixture.root,
        path,
        artifact_id="material-baseline",
        kind="v05-material-plan",
        media_type="application/json",
    )
    return ExactArtifact.model_validate(artifact.model_dump(mode="python"))


def _normalization_and_semantic_review(
    fixture: _GeometryFixture,
    image: _ImageFixture,
    case: _MaterialCase,
    *,
    created_at: datetime,
) -> tuple[CodexImageArtifact, CodexImageArtifact]:
    """Publish a byte-preserving normalization and non-human semantic fixture review."""

    from codex_blender_modeler.codex_imagegen.artifacts import load_codex_image_model
    from codex_blender_modeler.codex_imagegen.material_loop_models import (
        ALL_SEMANTIC_REVIEW_CATEGORIES,
        CodexImageSemanticCheck,
        ImageGenNativeNormalizationReceipt,
        MaterialLoopRasterSize,
        imagegen_native_normalization_output_path,
        imagegen_native_normalization_plan_path,
    )
    from codex_blender_modeler.codex_imagegen.material_loop_normalization import (
        execute_native_image_normalization,
        plan_native_image_normalization,
    )
    from codex_blender_modeler.codex_imagegen.material_loop_semantic import (
        build_codex_image_semantic_review,
    )
    from codex_blender_modeler.codex_imagegen.models import (
        CodexGeneratedImageEvidence,
    )

    generated = load_codex_image_model(
        fixture.root,
        image.generated_evidence,
        CodexGeneratedImageEvidence,
    )
    loop_root = (
        fixture.root
        / "production"
        / "autonomy_v2"
        / fixture.session_id
        / "codex_imagegen"
        / "material_loop_inputs"
    )
    plan = plan_native_image_normalization(
        fixture.root,
        contract_id=f"{case.slug}-native-normalization",
        job_id=_JOB_ID,
        workflow_id=fixture.plan.workflow_id,
        dispatch_id=fixture.plan.dispatch_id,
        session_id=fixture.session_id,
        source_image=generated.generated_file.artifact,
        output_path=imagegen_native_normalization_output_path(
            fixture.session_id,
            f"{case.slug}-native-normalization",
        ),
        target_size=MaterialLoopRasterSize(width=64, height=64),
        source_color_space="srgb",
        preferred_operation="contain_pad",
        created_at=created_at,
    )
    plan_artifact = write_immutable_codex_image_model(
        fixture.root,
        fixture.root
        / imagegen_native_normalization_plan_path(
            fixture.session_id,
            f"{case.slug}-native-normalization",
        ),
        plan,
        kind="imagegen-native-normalization-plan",
    )
    receipt = execute_native_image_normalization(
        fixture.root,
        plan,
        plan_artifact,
        receipt_contract_id=f"{case.slug}-native-normalization-receipt",
        created_at=created_at + timedelta(seconds=1),
    )
    assert isinstance(receipt, ImageGenNativeNormalizationReceipt)
    assert receipt.status in {"pass_through", "normalized"}
    if image.fake_source_used:
        assert receipt.status == "pass_through"
    assert receipt.normalized_image is not None
    receipt_artifact = write_immutable_codex_image_model(
        fixture.root,
        loop_root / "normalization_receipt.json",
        receipt,
        kind="imagegen-native-normalization-receipt",
    )
    category_rationales = {
        "unwanted_text": "The deterministic fake fixture contains no text glyphs.",
        "unwanted_object_or_background": (
            "The deterministic fake fixture contains only the bounded swatch pixels."
        ),
        "material_family_suitability": (
            f"The bounded fixture is accepted only for this {case.family} contract smoke."
        ),
        "signage_or_decal_suitability": (
            "Signage suitability is evaluated only by this bounded synthetic fixture."
        ),
        "wood_grain_naturalness": (
            "Wood naturalness is evaluated only by this bounded synthetic fixture."
        ),
        "decorative_pattern_asset_suitability": (
            "Decorative-pattern suitability is not used beyond this bounded test input."
        ),
        "crystal_or_energy_pattern_suitability": (
            "Crystal or energy suitability is bounded to this synthetic fixture."
        ),
        "reference_style_alignment": (
            "The fake reference and fake candidate are contract fixtures, not observed truth."
        ),
        "repeat_or_tile_suitability": (
            "The deterministic fixture is accepted for the adapter's bounded repeat path."
        ),
        "lighting_hotspot": "The deterministic fixture contains no simulated hotspot.",
        "perspective_distortion": (
            "The generated contract fixture is a square swatch without projected perspective."
        ),
        "boundary_contamination": (
            "The deterministic fixture has no separately introduced boundary content."
        ),
    }
    semantic_checks = [
        CodexImageSemanticCheck(
            category=category,
            outcome="passed",
            confidence=1.0,
            rationale=category_rationales[category],
        )
        for category in ALL_SEMANTIC_REVIEW_CATEGORIES
    ]
    semantic_producer = "pytest.fake_nonhuman_semantic_review"
    if image.actual_builtin_source_used:
        observed = {
            "unwanted_text": (
                "passed",
                0.99,
                "Current-task visual inspection found no text, letters, logo, or watermark.",
            ),
            "unwanted_object_or_background": (
                "passed",
                0.99,
                "Current-task visual inspection found only a flat wood surface swatch.",
            ),
            "material_family_suitability": (
                "passed",
                0.95,
                "The observed brown longitudinal grain is suitable for the bounded wood role.",
            ),
            "signage_or_decal_suitability": (
                "unavailable",
                0.0,
                "The wood-only review does not claim signage or decal suitability.",
            ),
            "wood_grain_naturalness": (
                "passed",
                0.9,
                "The visible fibers and knots appear plausible for a wood base-color swatch.",
            ),
            "decorative_pattern_asset_suitability": (
                "unavailable",
                0.0,
                "The wood-only review does not claim a decorative-pattern role.",
            ),
            "crystal_or_energy_pattern_suitability": (
                "unavailable",
                0.0,
                "The wood-only review does not claim a crystal or energy role.",
            ),
            "reference_style_alignment": (
                "unavailable",
                0.0,
                "No independent visual reference was supplied for style comparison.",
            ),
            "repeat_or_tile_suitability": (
                "review_required",
                0.6,
                "A single visual inspection cannot prove opposite-edge seamless tiling.",
            ),
            "lighting_hotspot": (
                "passed",
                0.9,
                "No obvious localized highlight or cast shadow is visible.",
            ),
            "perspective_distortion": (
                "passed",
                0.95,
                "The image appears as a flat orthographic surface sample.",
            ),
            "boundary_contamination": (
                "passed",
                0.95,
                "No frame, border, UI, or unrelated boundary content is visible.",
            ),
        }
        semantic_checks = [
            CodexImageSemanticCheck(
                category=category,
                outcome=observed[category][0],
                confidence=observed[category][1],
                rationale=observed[category][2],
            )
            for category in ALL_SEMANTIC_REVIEW_CATEGORIES
        ]
        semantic_producer = "current_codex_task_semantic_review"
    semantic = build_codex_image_semantic_review(
        fixture.root,
        contract_id=f"{case.slug}-semantic-review",
        job_id=_JOB_ID,
        workflow_id=fixture.plan.workflow_id,
        dispatch_id=fixture.plan.dispatch_id,
        session_id=fixture.session_id,
        candidate_id=generated.candidate_id,
        reviewed_image=receipt.normalized_image,
        assignment=image.assignment,
        deterministic_quality_report=image.quality_report,
        material_family=case.family,
        checks=semantic_checks,
        producer=semantic_producer,
        created_at=created_at + timedelta(seconds=2),
    )
    assert semantic.outcome == (
        "review_required" if image.actual_builtin_source_used else "passed"
    )
    semantic_artifact = write_immutable_codex_image_model(
        fixture.root,
        loop_root / "semantic_review.json",
        semantic,
        kind="codex-image-semantic-review",
    )
    return receipt_artifact, semantic_artifact


def _author_material_v021(
    fixture: _GeometryFixture,
    image: _ImageFixture,
    case: _MaterialCase,
    baseline: object,
    normalization_artifact: CodexImageArtifact,
    *,
    created_at: datetime,
) -> tuple[object, CodexImageArtifact, CodexImageArtifact, CodexImageArtifact]:
    """Adopt an unchanged 0.2.1 request through the normalized companion boundary."""

    from codex_blender_modeler.codex_imagegen.artifacts import load_codex_image_model
    from codex_blender_modeler.codex_imagegen.command_service import (
        adopt_codex_imagegen_material_phase,
        prepare_codex_imagegen_material_adoption,
    )
    from codex_blender_modeler.codex_imagegen.material_loop_models import (
        ImageGenNativeNormalizationPlan,
        ImageGenNativeNormalizationReceipt,
    )
    from codex_blender_modeler.material_authoring.codex_image_models import (
        CodexImageEvidenceBindingsV021,
        CodexImageMaterialAuthoringRequestV021,
        CodexImageMaterialSourceV021,
        ExactTextCompositionV021,
        LocalImageDerivationPolicyV021,
    )
    from codex_blender_modeler.material_authoring.codex_image_normalized_adapter import (
        build_codex_image_normalized_material_request,
    )
    from codex_blender_modeler.material_authoring.codex_image_normalized_models import (
        CodexImageNormalizedMaterialAuthoringReceiptV010,
    )
    from codex_blender_modeler.material_authoring.models import (
        ScaleContextBinding,
        UVIdentity,
        UVIdentitySnapshot,
        UVRect,
    )
    from codex_blender_modeler.structural_geometry.models import (
        AssetScaleContext,
        StructuralEvidenceArtifact,
    )

    prepared = prepare_codex_imagegen_material_adoption(
        job_id=_JOB_ID,
        session_id=fixture.session_id,
        material_strategy=case.strategy,
        direct_channels=[case.direct_role],
        exact_text_evidence_path=(
            fixture.root / image.exact_text_evidence.path
            if image.exact_text_evidence is not None
            else None
        ),
    )
    adoption_artifact = CodexImageArtifact.model_validate(prepared["adoption_artifact"])
    prepared_adoption = ImageToMaterialAdoption.model_validate_json(
        json.dumps(prepared["adoption"])
    )
    normalization = load_codex_image_model(
        fixture.root,
        normalization_artifact,
        ImageGenNativeNormalizationReceipt,
    )
    assert normalization.normalized_image is not None
    normalization_plan = load_codex_image_model(
        fixture.root,
        normalization.plan,
        ImageGenNativeNormalizationPlan,
    )
    scene_path = fixture.root / "analysis" / "scene_spec.json"
    scene_sha256 = sha256_file(scene_path)
    scale_context = AssetScaleContext.from_bounds(
        asset_id=_SEMANTIC_ID,
        job_id=_JOB_ID,
        workflow_id=fixture.plan.workflow_id,
        dispatch_id=fixture.plan.dispatch_id,
        source_fingerprint=scene_sha256,
        producer="pytest.codex_image_material_loop",
        producer_version="0.1.0",
        provenance=[
            StructuralEvidenceArtifact(
                role="scene_spec",
                path="analysis/scene_spec.json",
                sha256=scene_sha256,
            )
        ],
        created_at=created_at,
        local_minimum=(-1.0, -0.6, 0.0),
        local_maximum=(1.0, 0.6, 1.2),
        assembly_minimum=(-1.0, -0.6, 0.0),
        assembly_maximum=(1.0, 0.6, 1.2),
        projected_pixel_size=128.0,
        target_texel_density_px_m=256.0,
    )
    scale_path = fixture.root / "analysis" / "asset_scale_context.json"
    _write_json_model(scale_path, scale_context)
    scale_artifact = artifact_for_codex_image(
        fixture.root,
        scale_path,
        artifact_id="material-scale-context",
        kind="asset-scale-context",
        media_type="application/json",
    )
    scale = ScaleContextBinding(
        artifact=_material_exact(scale_artifact),
        asset_id=scale_context.asset_id,
        source_fingerprint=scale_context.source_fingerprint,
        shortest_dimension_m=scale_context.shortest_dimension_m,
        longest_dimension_m=max(scale_context.assembly_bbox.dimensions()),
        target_texel_density_px_m=scale_context.target_texel_density_px_m,
    )
    uv_fingerprint = hashlib.sha256(f"{scene_sha256}:{_SEMANTIC_ID}:UVMap:24".encode()).hexdigest()
    uv_snapshot = UVIdentitySnapshot(
        semantic_id=_SEMANTIC_ID,
        uv_set="UVMap",
        uv_fingerprint=uv_fingerprint,
        ordered_polygon_corner_count=24,
        texel_density_px_m=256.0,
    )
    uv_path = fixture.root / "analysis" / "uv_identity.json"
    _write_json_model(uv_path, uv_snapshot)
    uv_artifact = artifact_for_codex_image(
        fixture.root,
        uv_path,
        artifact_id="material-uv-identity",
        kind="uv-identity-snapshot",
        media_type="application/json",
    )
    uv_identity = UVIdentity(
        **uv_snapshot.model_dump(mode="python"),
        evidence=_material_exact(uv_artifact),
    )
    exact_text = None
    if case.family == "signage_decal":
        assert prepared_adoption.exact_text_composition is not None
        exact_text = ExactTextCompositionV021(
            evidence="exact_user_text",
            text="AB",
            text_evidence_artifact=_material_exact(
                prepared_adoption.exact_text_composition
            ),
            font=_publish_bitmap_font(fixture),
            uv_rect=UVRect(minimum=(0.2, 0.2), maximum=(0.8, 0.8)),
            font_size_px=20,
        )
    request = CodexImageMaterialAuthoringRequestV021(
        request_id=f"{case.slug}-material-request",
        job_id=_JOB_ID,
        workflow_id=fixture.plan.workflow_id,
        run_id=f"{case.slug}-material-run",
        material_id=_MATERIAL_ID,
        strategy=case.strategy,
        material_family=case.family,
        output_root=(
            f"material_authoring/codex_imagegen/runs/{case.slug}-material-run"
        ),
        core_evidence=CodexImageEvidenceBindingsV021(
            selection=_material_exact(image.selection),
            selected_evidence=_material_exact(image.generated_evidence),
            selected_quality_report=_material_exact(image.quality_report),
            adoption=_material_exact(adoption_artifact),
        ),
        source=CodexImageMaterialSourceV021(
            artifact=_material_exact(normalization.source_image),
            width=normalization_plan.source_size.width,
            height=normalization_plan.source_size.height,
            direct_role=case.direct_role,
            color_space="srgb",
            license_id="codex-project-generation-fixture",
            rights_status="project_owned",
            provenance=(
                "hash-bound supplied Codex built-in source copied by ControllerExecutor"
                if image.actual_builtin_source_used
                else "deterministic fake controller fixture; not actual Codex ImageGen"
            ),
        ),
        source_v05_contracts=[baseline],
        uv_identity=uv_identity,
        scale_context=scale,
        derivation=LocalImageDerivationPolicyV021(
            output_resolution=256,
            expected_grain_axis="none",
            minimum_spatial_standard_deviation=0.0,
            maximum_offset_edge_rmse=1.0,
        ),
        exact_text=exact_text,
        created_at=created_at + timedelta(seconds=1),
    )
    base_request_artifact = write_immutable_codex_image_model(
        fixture.root,
        fixture.root
        / "production"
        / "autonomy_v2"
        / fixture.session_id
        / "codex_imagegen"
        / f"{case.slug}-base-material-request-v021.json",
        request,
        kind="codex-image-material-authoring-request",
    )
    effective_source = request.source.model_copy(
        update={
            "artifact": _material_exact(normalization.normalized_image),
            "width": normalization.target_size.width,
            "height": normalization.target_size.height,
            "provenance": (
                "deterministic normalized derivative of the unchanged selected source"
            ),
        }
    )
    normalized_request = build_codex_image_normalized_material_request(
        fixture.root,
        contract_id=f"{case.slug}-normalized-material-request",
        run_id=f"{case.slug}-normalized-material-run",
        base_request=request,
        base_request_artifact=base_request_artifact,
        normalization_plan=normalization.plan,
        normalization_receipt=normalization_artifact,
        effective_source=effective_source,
        created_at=created_at + timedelta(seconds=2),
    )
    request_path = (
        fixture.root
        / "production"
        / "autonomy_v2"
        / fixture.session_id
        / "codex_imagegen"
        / "material_request.json"
    )
    _write_json_model(request_path, normalized_request)
    adopted = adopt_codex_imagegen_material_phase(
        job_id=_JOB_ID,
        session_id=fixture.session_id,
        material_request_path=request_path,
    )
    assert adopted["status"] == "adopted"
    receipt_artifact = CodexImageArtifact.model_validate(adopted["material_receipt"])
    terminal_artifact = CodexImageArtifact.model_validate(adopted["generation_terminal"])
    receipt = load_codex_image_model(
        fixture.root,
        receipt_artifact,
        CodexImageNormalizedMaterialAuthoringReceiptV010,
    )
    return receipt, receipt_artifact, terminal_artifact, adoption_artifact


def _codex_from_material(root: Path, artifact: object) -> CodexImageArtifact:
    """Rebind one material exact artifact through the media-aware artifact service."""

    return artifact_for_codex_image(
        root,
        root / str(artifact.path),
        artifact_id=str(artifact.artifact_id),
        kind=str(artifact.kind),
        media_type=str(artifact.media_type),
    )


def _merge_exact_codex_aliases(
    direct: list[CodexImageArtifact],
    aliases: list[CodexImageArtifact],
) -> list[CodexImageArtifact]:
    """Merge exact V0.5 aliases into bridge provenance without identity conflicts."""

    merged = list(direct)
    by_path = {item.path: item for item in direct}
    by_id = {item.artifact_id: item for item in direct}
    if len(by_path) != len(direct) or len(by_id) != len(direct):
        raise ValueError("direct bridge fixture artifacts must be unique")
    for artifact in aliases:
        current = by_path.get(artifact.path)
        if current is not None:
            if current != artifact:
                raise ValueError("V0.5 fixture alias differs from direct artifact identity")
            continue
        if artifact.artifact_id in by_id:
            raise ValueError("V0.5 fixture alias reuses a different artifact ID")
        merged.append(artifact)
        by_path[artifact.path] = artifact
        by_id[artifact.artifact_id] = artifact
    return merged


def _publish_v05_bridge_plan(
    fixture: _GeometryFixture,
    image: _ImageFixture,
    case: _MaterialCase,
    authoring_receipt: object,
    terminal_artifact: CodexImageArtifact,
    adoption_artifact: CodexImageArtifact,
    normalization_artifact: CodexImageArtifact,
    semantic_artifact: CodexImageArtifact,
    *,
    created_at: datetime,
):
    """Publish V0.5 blueprints and construct the exact companion bridge plan."""

    from codex_blender_modeler.autonomy_v2.codex_image_material_loop_service import (
        publish_codex_image_v05_exact_adoption_preflight,
    )
    from codex_blender_modeler.blender_artifacts import stable_json_digest
    from codex_blender_modeler.codex_imagegen.artifacts import load_codex_image_model
    from codex_blender_modeler.codex_imagegen.material_loop_models import (
        ImageGeneratedMaterialBridgePlan,
    )
    from codex_blender_modeler.codex_imagegen.models import (
        CodexGeneratedImageEvidence,
    )
    from codex_blender_modeler.material_authoring.codex_image_normalized_models import (
        CodexImageNormalizedMaterialAuthoringReceiptV010,
        CodexImageNormalizedMaterialAuthoringRequestV010,
    )
    from codex_blender_modeler.material_authoring.codex_image_v05_bridge import (
        publish_codex_image_v05_bridge,
    )
    from codex_blender_modeler.production.controller_executor import PhaseToolProfile

    receipt = CodexImageNormalizedMaterialAuthoringReceiptV010.model_validate(
        authoring_receipt.model_dump(mode="python")
    )
    request = CodexImageNormalizedMaterialAuthoringRequestV010.model_validate_json(
        (fixture.root / receipt.request.path).read_bytes()
    )
    profile_artifact = next(
        item
        for item in fixture.plan.phase_tool_profiles
        if item.path.endswith("/material_authoring.json")
    )
    profile = PhaseToolProfile.model_validate_json(
        (fixture.root / profile_artifact.path).read_bytes()
    )
    paths = {Path(item).name: item for item in profile.allowed_output_paths}
    generated = load_codex_image_model(
        fixture.root,
        image.generated_evidence,
        CodexGeneratedImageEvidence,
    )
    canonical_scene = _codex_json(
        fixture.root,
        fixture.receipt.canonical_scene_spec,
    )
    authoring_artifact = artifact_for_codex_image(
        fixture.root,
        (fixture.root / receipt.request.path).with_name("receipt.json"),
        artifact_id=receipt.receipt_id,
        kind="codex-image-normalized-material-authoring-receipt",
        media_type="application/json",
    )
    v05_receipt = publish_codex_image_v05_bridge(
        fixture.root,
        receipt,
        bridge_run_id=f"{case.slug}-v05-bridge",
        dispatch_id=fixture.plan.dispatch_id,
        material_plan_output_path=paths["material_plan.json"],
        material_graph_output_path=paths["material_graph.json"],
        source_authoring_receipt_artifact=_material_exact(authoring_artifact),
        source_scene_spec_artifact=_material_exact(canonical_scene),
    )
    v05_receipt_artifact = artifact_for_codex_image(
        fixture.root,
        fixture.root / Path(v05_receipt.candidate_material_plan.path).parent / "receipt.json",
        artifact_id=v05_receipt.receipt_id,
        kind="codex-image-v05-bridge-receipt",
        media_type="application/json",
    )
    _preflight, preflight_artifact = publish_codex_image_v05_exact_adoption_preflight(
        fixture.root,
        preflight_id=f"{case.slug}-exact-adoption-preflight",
        v05_bridge_receipt_artifact=v05_receipt_artifact,
        created_at=created_at,
    )
    v05_controller_inputs = [
        _codex_from_material(fixture.root, item.artifact)
        for item in v05_receipt.controller_inputs
    ]
    texture_outputs = [
        _codex_from_material(fixture.root, item) for item in receipt.outputs
    ]
    candidate_plan = _codex_from_material(
        fixture.root,
        v05_receipt.candidate_material_plan,
    )
    candidate_graph = _codex_from_material(
        fixture.root,
        v05_receipt.candidate_material_graph,
    )
    shader_recipes = [_codex_from_material(fixture.root, v05_receipt.shader_recipe)]
    texture_manifests = [_codex_from_material(fixture.root, v05_receipt.texture_manifest)]
    assert v05_receipt.previous_canonical_material_plan is not None
    previous_material = _codex_from_material(
        fixture.root,
        v05_receipt.previous_canonical_material_plan,
    )
    canonical_material_observation = _codex_from_material(
        fixture.root,
        v05_receipt.source_material_plan,
    )
    build_provenance = _codex_json(
        fixture.root,
        fixture.receipt.candidate_build_provenance,
    )
    fingerprint = json.loads((fixture.root / build_provenance.path).read_text(encoding="utf-8"))[
        "fingerprint"
    ]
    root_authorization = _codex_json(
        fixture.root,
        fixture.plan.root_authorization,
    )
    aq_plan = _codex_json(
        fixture.root,
        artifact_for_v2(
            fixture.root,
            fixture.root / "production" / "autonomy_v2" / fixture.session_id / "plan.json",
            artifact_id=f"plan-{fixture.session_id}",
            kind="plan",
        ),
    )
    aq_profile = _codex_json(fixture.root, fixture.plan.profile)
    aq_budget = _codex_json(fixture.root, fixture.plan.budget)
    current_state = _codex_json(fixture.root, fixture.state_artifact)
    geometry_receipt = _codex_json(fixture.root, fixture.receipt_artifact)
    request_artifact = _codex_from_material(fixture.root, receipt.request)
    manifest_artifact = _codex_from_material(fixture.root, receipt.manifest)
    direct_artifacts = [
        root_authorization,
        aq_plan,
        aq_profile,
        aq_budget,
        current_state,
        canonical_scene,
        geometry_receipt,
        build_provenance,
        image.provider_profile,
        image.generation_plan,
        image.assignment,
        image.completion,
        terminal_artifact,
        image.selected_candidate,
        image.generated_evidence,
        image.quality_report,
        image.selection,
        semantic_artifact,
        normalization_artifact,
        adoption_artifact,
        request_artifact,
        manifest_artifact,
        authoring_artifact,
        v05_receipt_artifact,
        preflight_artifact,
        *texture_outputs,
        candidate_plan,
        candidate_graph,
        *shader_recipes,
        *texture_manifests,
        canonical_material_observation,
        previous_material,
    ]
    artifacts = _merge_exact_codex_aliases(direct_artifacts, v05_controller_inputs)
    identity = {
        "session_id": fixture.session_id,
        "candidate": generated.candidate_id,
        "candidate_plan": candidate_plan.sha256,
        "candidate_graph": candidate_graph.sha256,
    }
    output_root = str(Path(profile.allowed_output_paths[0]).parent).replace("\\", "/")
    return ImageGeneratedMaterialBridgePlan(
        contract_id=f"material-bridge-plan-{fixture.session_id}",
        job_id=_JOB_ID,
        workflow_id=fixture.plan.workflow_id,
        dispatch_id=fixture.plan.dispatch_id,
        session_id=fixture.session_id,
        input_sha256=stable_json_digest(
            {item.path: item.sha256 for item in artifacts}
        ),
        source_fingerprint=stable_json_digest({**identity, "stage": "v05"}),
        producer="pytest.codex_image_material_loop",
        provenance=artifacts,
        created_at=created_at,
        base_aq_session_id=fixture.session_id,
        selected_candidate_id=generated.candidate_id,
        material_authoring_run_id=receipt.run_id,
        material_controller_request_id=f"{case.slug}-material-controller",
        root_authorization=root_authorization,
        aq_plan=aq_plan,
        aq_profile=aq_profile,
        aq_budget=aq_budget,
        current_state=current_state,
        canonical_scene_spec=canonical_scene,
        geometry_validation_receipt=geometry_receipt,
        current_build_provenance=build_provenance,
        provider_profile=image.provider_profile,
        imagegen_plan=image.generation_plan,
        assignment=image.assignment,
        completion=image.completion,
        generation_terminal=terminal_artifact,
        selected_candidate=image.selected_candidate,
        generated_image_evidence=image.generated_evidence,
        quality_report=image.quality_report,
        selection=image.selection,
        semantic_review=semantic_artifact,
        normalization_receipt=normalization_artifact,
        adoption=adoption_artifact,
        material_authoring_request=request_artifact,
        material_authoring_manifest=manifest_artifact,
        material_authoring_receipt=authoring_artifact,
        v05_bridge_receipt=v05_receipt_artifact,
        exact_adoption_preflight=preflight_artifact,
        v05_controller_inputs=v05_controller_inputs,
        texture_outputs=texture_outputs,
        candidate_material_plan=candidate_plan,
        material_graph_spec=candidate_graph,
        shader_recipes=shader_recipes,
        texture_manifests=texture_manifests,
        canonical_material_observation=canonical_material_observation,
        previous_material_plan=previous_material,
        canonical_scene_spec_sha256=canonical_scene.sha256,
        geometry_build_fingerprint=fingerprint,
        uv_fingerprint=request.base_request.uv_identity.uv_fingerprint,
        target_material_ids=[_MATERIAL_ID],
        target_semantic_ids=[_SEMANTIC_ID],
        mutable_material_ids=[_MATERIAL_ID],
        immutable_material_ids=[],
        requested_delivery_profiles=["review_only"],
        execution_mode="exact_adoption",
        output_root=output_root,
        allowed_output_paths=profile.allowed_output_paths,
        expected_output_sha256=v05_receipt.expected_output_sha256,
    )


def _aq_from_codex(artifact: CodexImageArtifact) -> AQV2Artifact:
    """Project one exact companion artifact into the AQ quality-evidence shape."""

    return AQV2Artifact(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )


@pytest.mark.parametrize("case", _MATERIAL_CASES, ids=lambda item: item.family)
def test_imagegen_family_reaches_verified_material_or_review_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: _MaterialCase,
) -> None:
    """Promote fake family evidence or stop actual-source evidence for review."""

    from codex_blender_modeler.autonomy_v2.codex_image_material_loop_service import (
        execute_codex_image_material_loop_controller,
        finalize_codex_image_material_loop_promotion,
        promote_codex_image_material_loop,
        publish_codex_image_material_loop_bridge,
    )
    from codex_blender_modeler.autonomy_v2.codex_image_material_preview_service import (
        render_promoted_codex_image_material_preview,
    )
    from codex_blender_modeler.autonomy_v2.codex_image_material_quality_service import (
        validate_codex_image_material_quality_boundary,
    )
    from codex_blender_modeler.autonomy_v2.controller_bridge import (
        get_autonomy_v2_status,
    )
    from codex_blender_modeler.autonomy_v2.material_phase_service import (
        validate_material_phase_receipt_v2,
    )
    from codex_blender_modeler.autonomy_v2.supervisor_service import (
        QualitySubmissionV2,
    )
    from codex_blender_modeler.codex_imagegen.material_loop_models import (
        ImageGeneratedMaterialControllerInput,
        ImageGeneratedMaterialPromotionReceipt,
    )
    from codex_blender_modeler.material_graph.runtime_models import (
        MaterialGraphCompileReport,
    )

    fixture = _geometry_material_boundary(tmp_path, monkeypatch)
    created_at = datetime.now(UTC)
    baseline = _publish_material_baseline(fixture)
    image = _fake_imagegen_selection(fixture, case, created_at=created_at)
    expected_actual_source = bool(
        os.environ.get("CBM_CODEX_IMAGEGEN_ACTUAL_SOURCE_PATH")
    ) and case.family == "wood"
    assert image.actual_builtin_source_used is expected_actual_source
    assert image.fake_source_used is (not expected_actual_source)
    normalization, semantic = _normalization_and_semantic_review(
        fixture,
        image,
        case,
        created_at=created_at + timedelta(seconds=10),
    )
    if expected_actual_source:
        from codex_blender_modeler.codex_imagegen.artifacts import (
            load_codex_image_model,
        )
        from codex_blender_modeler.codex_imagegen.material_loop_models import (
            CodexImageSemanticReview,
        )

        review = load_codex_image_model(
            fixture.root,
            semantic,
            CodexImageSemanticReview,
        )
        assert review.outcome == "review_required"
        assert review.human_reviewed is False
        assert review.producer == "current_codex_task_semantic_review"
        assert sha256_file(fixture.root / "analysis" / "material_plan.json") == (
            baseline.sha256
        )
        return
    authoring, _authoring_artifact, terminal, adoption = _author_material_v021(
        fixture,
        image,
        case,
        baseline,
        normalization,
        created_at=created_at + timedelta(seconds=20),
    )
    bridge_plan = _publish_v05_bridge_plan(
        fixture,
        image,
        case,
        authoring,
        terminal,
        adoption,
        normalization,
        semantic,
        created_at=created_at + timedelta(seconds=30),
    )
    published = publish_codex_image_material_loop_bridge(
        fixture.root,
        bridge_plan=bridge_plan,
        created_at=created_at + timedelta(seconds=31),
    )
    controller_input = ImageGeneratedMaterialControllerInput.model_validate_json(
        json.dumps(published["controller_input"])
    )
    controller_input_artifact = CodexImageArtifact.model_validate(
        published["controller_input_artifact"]
    )
    assert controller_input.source_material_plan_sha256 is not None
    outputs = {Path(item).name: item for item in bridge_plan.allowed_output_paths}
    plan_bytes = (fixture.root / bridge_plan.candidate_material_plan.path).read_bytes()
    graph_bytes = (fixture.root / bridge_plan.material_graph_spec.path).read_bytes()
    execution_id = f"exec-{fixture.state.sequence + 1:04d}-material_authoring"
    from codex_blender_modeler.autonomy_v2.material_phase_models import (
        MaterialControllerCompletionV2,
    )

    completion = MaterialControllerCompletionV2(
        completion_id=f"{case.slug}-material-completion",
        job_id=_JOB_ID,
        workflow_id=fixture.plan.workflow_id,
        dispatch_id=fixture.plan.dispatch_id,
        session_id=fixture.session_id,
        execution_id=execution_id,
        assignment_sha256=controller_input_artifact.sha256,
        tool_profile_sha256=controller_input.phase_tool_profile.sha256,
        immutable_input_sha256=controller_input.immutable_input_sha256,
        source_scene_spec_sha256=bridge_plan.canonical_scene_spec_sha256,
        source_material_plan_sha256=controller_input.source_material_plan_sha256,
        material_plan_path=outputs["material_plan.json"],
        material_plan_sha256=hashlib.sha256(plan_bytes).hexdigest(),
        material_graph_path=outputs["material_graph.json"],
        material_graph_sha256=hashlib.sha256(graph_bytes).hexdigest(),
    )
    executed = execute_codex_image_material_loop_controller(
        _JOB_ID,
        fixture.session_id,
        controller=FakeControllerForTests(
            payloads={
                "material_plan.json": plan_bytes,
                "material_graph.json": graph_bytes,
                "completion.json": geometry_fixtures._json_bytes(completion),
            }
        ),
        timeout_seconds=60,
        allow_disabled_experimental=True,
    )
    assert executed["controller_status"] == "completed"
    result_state = AutonomyStateV2.model_validate_json(json.dumps(executed["state"]))
    result_artifact = result_state.provenance[-1]
    root, _session_root, plan, budget, state, _state_artifact = _session_bundle(
        _JOB_ID,
        fixture.session_id,
    )
    receipt, receipt_artifact = promote_codex_image_material_loop(
        root,
        plan=plan,
        budget=budget,
        state=state,
        result_artifact=result_artifact,
        allow_disabled_experimental=True,
    )
    validated = validate_material_phase_receipt_v2(
        root,
        receipt_artifact,
        require_current=True,
    )
    assert validated == receipt
    assert receipt.status == "promoted"
    assert receipt.canonical_scene_spec_sha256 == fixture.receipt.canonical_scene_spec.sha256
    compile_report = MaterialGraphCompileReport.model_validate_json(
        (root / receipt.graph_compile_report.path).read_bytes()
    )
    assert compile_report.ok is True
    assert compile_report.blender_version == "5.0.1"
    material_receipt_codex = artifact_for_codex_image(
        root,
        root / receipt_artifact.path,
        artifact_id=receipt.contract_id,
        kind="material-phase-receipt",
        media_type="application/json",
    )
    preview, preview_artifact = render_promoted_codex_image_material_preview(
        root,
        material_phase_receipt=material_receipt_codex,
        preview_id=f"{case.slug}-neutral-preview",
        material_id=_MATERIAL_ID,
        size=64,
        created_at=created_at + timedelta(seconds=40),
    )
    assert preview.actual_blender_rendered is True
    assert preview.human_reviewed is False
    preview_manifest = json.loads(
        (root / preview.raw_swatch_manifest.path).read_text(encoding="utf-8")
    )
    assert preview_manifest["blender_version"] == "5.0.1"
    finalized = finalize_codex_image_material_loop_promotion(
        root,
        material_phase_receipt_artifact=receipt_artifact,
        neutral_preview_artifact=preview_artifact,
        created_at=created_at + timedelta(seconds=41),
    )
    promotion_artifact = CodexImageArtifact.model_validate(finalized["promotion_receipt_artifact"])
    promotion = ImageGeneratedMaterialPromotionReceipt.model_validate_json(
        json.dumps(finalized["promotion_receipt"])
    )
    assert finalized["next_action"] == "run_integrated_quality"
    status = get_autonomy_v2_status(_JOB_ID, fixture.session_id)
    quality_state = AutonomyStateV2.model_validate_json(json.dumps(status["state"]))
    assert (quality_state.phase, quality_state.status, quality_state.next_action) == (
        "quality",
        "running",
        "run_integrated_quality",
    )
    camera_artifact = artifact_for_v2(
        root,
        root / "analysis" / "camera_solution.json",
        artifact_id="fixed-camera-boundary",
        kind="camera",
    )
    required_quality = [
        promotion_artifact,
        promotion.generated_image_evidence,
        promotion.semantic_review,
        promotion.normalization_receipt,
        promotion.adoption,
        promotion.material_authoring_manifest,
        promotion.material_authoring_receipt,
        promotion.graph_compile_report,
        promotion.material_validation,
        promotion.neutral_preview,
        preview.renderer_script,
        preview.raw_swatch_manifest,
        promotion.neutral_preview_image,
    ]
    current_authoring_blend = artifact_for_v2(
        root,
        root / "blender" / "scene.blend",
        artifact_id=preview.authoring_blend.artifact_id,
        kind="canonical_blend",
    )
    submission = QualitySubmissionV2(
        integrated_quality_report=fixture.receipt.geometry_intent_survival,
        quality_evidence=[
            *[_aq_from_codex(item) for item in required_quality],
            camera_artifact,
        ],
        camera_artifact=camera_artifact,
        authoring_blend=current_authoring_blend,
    )
    observed = validate_codex_image_material_quality_boundary(
        root,
        session_id=fixture.session_id,
        promotion_receipt_artifact=promotion_artifact,
        quality_submission=submission,
        state=quality_state,
    )
    assert observed == promotion
    assert promotion.status == "promoted"
    assert quality_state.delivery_plan is None
    assert fixture.authorization.synthetic_user_approval is False
