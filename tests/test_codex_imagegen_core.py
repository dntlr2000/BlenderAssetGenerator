"""Focused lifecycle tests for the credential-free Codex ImageGen companion."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from codex_blender_modeler.blender_artifacts import (
    sha256_file,
    stable_json_digest,
    write_json_atomic,
)
from codex_blender_modeler.codex_imagegen import (
    native_core_preparation as native_core_service,
)
from codex_blender_modeler.codex_imagegen.adoption import (
    build_image_to_material_adoption,
)
from codex_blender_modeler.codex_imagegen.artifacts import (
    artifact_for_codex_image,
    load_codex_image_model,
    write_immutable_codex_image_model,
)
from codex_blender_modeler.codex_imagegen.assignment import (
    build_codex_imagegen_assignment,
    codex_image_source_inventory_sha256,
)
from codex_blender_modeler.codex_imagegen.budget import (
    apply_completion_usage,
    build_default_codex_imagegen_budget,
)
from codex_blender_modeler.codex_imagegen.completion import (
    build_codex_imagegen_candidate,
    build_generated_image_evidence,
    copy_imagegen_png_and_write_completion,
    validate_codex_imagegen_completion,
)
from codex_blender_modeler.codex_imagegen.fake_controller_backend import (
    FakeCodexImagegenController,
)
from codex_blender_modeler.codex_imagegen.material_loop_models import (
    MaterialLoopRasterSize,
    imagegen_native_normalization_output_path,
    imagegen_native_normalization_plan_path,
)
from codex_blender_modeler.codex_imagegen.material_loop_normalization import (
    plan_native_image_normalization,
    validate_native_normalization_receipt,
)
from codex_blender_modeler.codex_imagegen.models import (
    CodexBuiltinImageProviderProfile,
    CodexImageArtifact,
    CodexImageDimensions,
    CodexImageGenerationBudgetUsage,
    CodexImageGenerationPlanItem,
)
from codex_blender_modeler.codex_imagegen.native_core_preparation import (
    publish_codex_image_native_core_preparation_receipt,
    validate_codex_image_native_core_preparation_receipt,
    validate_native_core_preparation_binding,
)
from codex_blender_modeler.codex_imagegen.native_output_adoption import (
    adopt_codex_imagegen_native_output_bytes,
    validate_codex_image_native_output_adoption,
)
from codex_blender_modeler.codex_imagegen.planning import build_codex_imagegen_plan
from codex_blender_modeler.codex_imagegen.profile import (
    build_codex_builtin_image_provider_profile,
    codex_imagegen_profile_status,
)
from codex_blender_modeler.codex_imagegen.public_service import (
    adopt_codex_imagegen_completion,
    adopt_codex_imagegen_native_output,
    prepare_codex_imagegen_native_output_for_core_completion,
    validate_prepared_native_output_for_core_completion,
)
from codex_blender_modeler.codex_imagegen.quality import evaluate_candidate_quality
from codex_blender_modeler.codex_imagegen.selection import (
    select_codex_imagegen_candidate,
)
from codex_blender_modeler.production.controller_executor import (
    ControllerArtifact,
    ControllerExecutionRequest,
    build_phase_tool_profile,
    execute_controller_request,
    write_controller_contract,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _create_native_directory_link_or_skip(link: Path, target: Path) -> None:
    """Create one linked native-evidence root or skip unsupported hosts."""

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


def _write_artifact(
    root: Path,
    relative: str,
    *,
    artifact_id: str,
    kind: str,
    payload: bytes = b"{}\n",
    media_type: str = "application/json",
) -> CodexImageArtifact:
    """Write and bind one non-empty test artifact below the temporary job root."""

    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return artifact_for_codex_image(
        root,
        path,
        artifact_id=artifact_id,
        kind=kind,
        media_type=media_type,
    )


def _write_tileable_png(
    path: Path,
    *,
    width: int = 64,
    height: int = 64,
    mode: str = "RGBA",
) -> None:
    """Write a deterministic patterned RGB or RGBA PNG with matching opposite edges."""

    if mode not in {"RGB", "RGBA"}:
        raise ValueError("test PNG mode must be RGB or RGBA")
    image = Image.new(mode, (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            repeated_x = min(x, width - 1 - x)
            repeated_y = min(y, height - 1 - y)
            value = (repeated_x * 23 + repeated_y * 41) % 256
            color = (value, (value * 3) % 256, (value * 5) % 256)
            pixels[x, y] = (*color, 255) if mode == "RGBA" else color
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


def _build_assignment(
    root: Path,
    *,
    candidate_count: int = 1,
    prompt: str = "seamless neutral wood swatch without text",
    exact_text_value: str | None = None,
    output_role: str = "base_color",
):
    """Build and publish a fully bound activated profile, budget, plan, and assignment."""

    base_profile = _write_artifact(
        root,
        "production/autonomy_v2/session-1/profile.json",
        artifact_id="base-profile",
        kind="autonomy-profile-v2",
    )
    provider = build_codex_builtin_image_provider_profile(
        contract_id="provider-contract",
        provider_profile_id="provider-profile",
        job_id="job-1",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        base_profile_artifact=base_profile,
        created_at=NOW,
    )
    provider_artifact = write_immutable_codex_image_model(
        root,
        root / "production/autonomy_v2/session-1/codex_imagegen/provider.json",
        provider,
        kind="codex-builtin-image-provider-profile",
    )
    budget = build_default_codex_imagegen_budget(
        contract_id="budget-contract",
        budget_id="budget-1",
        job_id="job-1",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        provider_profile=provider_artifact,
        created_at=NOW,
    )
    budget_artifact = write_immutable_codex_image_model(
        root,
        root / "production/autonomy_v2/session-1/codex_imagegen/budget.json",
        budget,
        kind="codex-image-generation-budget",
    )
    base_plan = _write_artifact(
        root,
        "production/autonomy_v2/session-1/plan.json",
        artifact_id="base-plan",
        kind="autonomy-plan-v2",
    )
    authorization = _write_artifact(
        root,
        "production/autonomy_v2/session-1/root-authorization.json",
        artifact_id="root-authorization",
        kind="root-authorization-v2",
    )
    item = CodexImageGenerationPlanItem(
        plan_item_id="swatch-1",
        target_material_ids=["material-wood"],
        semantic_roles=["wood-grain"],
        generation_intent="generated_surface_swatch_v1",
        allowed_output_roles=[output_role],
        prompt_template_id="surface-swatch-v1",
        requested_candidate_count=candidate_count,
        quality_level="low",
        image_size=CodexImageDimensions(width=64, height=64),
        aspect_ratio="square",
        fallback="local_procedural_fallback",
    )
    plan = build_codex_imagegen_plan(
        contract_id="imagegen-plan-contract",
        plan_id="imagegen-plan-1",
        job_id="job-1",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        base_autonomy_plan=base_plan,
        base_root_authorization=authorization,
        provider_profile=provider,
        provider_profile_artifact=provider_artifact,
        budget=budget,
        budget_artifact=budget_artifact,
        items=[item],
        created_at=NOW,
    )
    plan_artifact = write_immutable_codex_image_model(
        root,
        root / "production/autonomy_v2/session-1/codex_imagegen/plan.json",
        plan,
        kind="codex-image-generation-plan",
    )
    base_state = _write_artifact(
        root,
        "production/autonomy_v2/session-1/state.json",
        artifact_id="base-state",
        kind="autonomy-state-v2",
    )
    assignment = build_codex_imagegen_assignment(
        contract_id="assignment-contract",
        assignment_id="assignment-1",
        sequence=0,
        plan=plan,
        plan_artifact=plan_artifact,
        plan_item=item,
        provider_profile_artifact=provider_artifact,
        budget=budget,
        budget_artifact=budget_artifact,
        usage=CodexImageGenerationBudgetUsage(),
        base_state_artifact=base_state,
        job_root=root,
        rendered_prompt_text=prompt,
        reference_images=[],
        created_at=NOW,
        exact_text_value=exact_text_value,
    )
    assignment_artifact = write_immutable_codex_image_model(
        root,
        root
        / "production/autonomy_v2/session-1/codex_imagegen/assignments"
        / "assignment-1/assignment.json",
        assignment,
        kind="codex-image-generation-assignment",
    )
    return assignment, assignment_artifact, budget


def test_profile_is_static_disabled_and_has_no_network_or_key_requirement(
    tmp_path: Path,
) -> None:
    """Keep discovery honest before exact current-task activation evidence exists."""

    status = codex_imagegen_profile_status()
    assert status["status"] == "disabled_experimental"
    assert status["network_required"] is False
    assert status["api_key_required"] is False
    assert status["repository_can_spawn_codex_task"] is False
    assignment, _assignment_artifact, _budget = _build_assignment(tmp_path)
    profile = load_codex_image_model(
        tmp_path,
        assignment.provider_profile,
        CodexBuiltinImageProviderProfile,
    )
    payload = profile.model_dump(mode="python")
    payload["status"] = "verified_active"
    with pytest.raises(ValidationError):
        CodexBuiltinImageProviderProfile.model_validate(payload)


def test_full_candidate_quality_selection_and_adoption_chain(tmp_path: Path) -> None:
    """Validate staged pixels through selection and non-canonical material adoption."""

    assignment, assignment_artifact, budget = _build_assignment(tmp_path)
    source = (
        tmp_path
        / "production/autonomy_v2/session-1/codex_imagegen/controller-source.png"
    )
    _write_tileable_png(source)
    output_paths = tuple(
        tmp_path / path
        for path in [
            *assignment.candidate_output_paths,
            assignment.completion_file_target,
        ]
    )
    completion = copy_imagegen_png_and_write_completion(
        controller_workspace_root=tmp_path,
        allowed_source_root=tmp_path,
        assignment_path=tmp_path / assignment_artifact.path,
        assignment_artifact=assignment_artifact,
        source_png_paths=[source],
        allowed_output_paths=output_paths,
        output_roles=["base_color"],
        completion_id="completion-assignment-1",
        controller_kind="fake_for_tests",
        controller_executed_at=NOW,
    )
    completion_artifact = artifact_for_codex_image(
        tmp_path,
        output_paths[-1],
        artifact_id=completion.contract_id,
        kind="codex-image-generation-completion",
        media_type="application/json",
    )
    validated_assignment, validated_completion, paths = (
        validate_codex_imagegen_completion(
            job_root=tmp_path,
            assignment_artifact=assignment_artifact,
            completion_artifact=completion_artifact,
        )
    )
    assert validated_assignment == assignment
    assert validated_completion == completion
    assert paths == [output_paths[0]]
    controller_request = _write_artifact(
        tmp_path,
        "production/autonomy_v2/session-1/codex_imagegen/controller-request.json",
        artifact_id="controller-request-1",
        kind="controller-request",
    )
    controller_result = _write_artifact(
        tmp_path,
        "production/autonomy_v2/session-1/codex_imagegen/controller-result.json",
        artifact_id="controller-result-1",
        kind="controller-result",
    )
    candidate = build_codex_imagegen_candidate(
        contract_id="candidate-contract-1",
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        controller_request_artifact=controller_request,
        controller_result_artifact=controller_result,
        generated_file=completion.generated_files[0],
        created_at=NOW,
    )
    candidate_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path / "production/autonomy_v2/session-1/codex_imagegen/candidate.json",
        candidate,
        kind="codex-image-generation-candidate",
    )
    evidence = build_generated_image_evidence(
        contract_id="generated-evidence-1",
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        created_at=NOW,
    )
    evidence_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path / "production/autonomy_v2/session-1/codex_imagegen/evidence.json",
        evidence,
        kind="codex-generated-image-evidence",
    )
    report = evaluate_candidate_quality(
        job_root=tmp_path,
        report_id="quality-report-1",
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        generated_image_evidence=evidence,
        generated_image_evidence_artifact=evidence_artifact,
        created_at=NOW,
    )
    assert report.outcome == "passed"
    semantic_ids = {
        "background-alignment",
        "style-alignment",
        "unwanted-object-content",
        "unwanted-text-content",
    }
    semantic_checks = {
        check.check_id: check.status
        for check in report.checks
        if check.check_id in semantic_ids
    }
    assert semantic_checks == dict.fromkeys(semantic_ids, "unscorable")
    report_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path / "production/autonomy_v2/session-1/codex_imagegen/quality.json",
        report,
        kind="codex-image-generation-quality-report",
    )
    selection = select_codex_imagegen_candidate(
        selection_id="selection-1",
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidates=[(candidate, candidate_artifact)],
        quality_reports=[(report, report_artifact)],
        created_at=NOW,
    )
    selection_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path / "production/autonomy_v2/session-1/codex_imagegen/selection.json",
        selection,
        kind="codex-image-generation-selection",
    )
    assert (
        validate_native_core_preparation_binding(
            job_root=tmp_path,
            assignment_artifact=assignment_artifact,
            core_completion=completion_artifact,
            core_candidate=candidate_artifact,
            core_generated_image_evidence=evidence_artifact,
            core_quality_report=report_artifact,
            core_selection=selection_artifact,
            preparation_receipt=None,
        )
        is None
    )
    adoption = build_image_to_material_adoption(
        contract_id="adoption-contract-1",
        adoption_id="adoption-1",
        selection=selection,
        selection_artifact=selection_artifact,
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        generated_image_evidence=evidence,
        generated_image_evidence_artifact=evidence_artifact,
        quality_report=report,
        quality_report_artifact=report_artifact,
        material_strategy="codex_generated_base_color_v1",
        direct_channels=["base_color"],
        derived_channels=[],
        created_at=NOW,
    )
    assert adoption.selected_source_sha256 == candidate.generated_file.artifact.sha256
    assert adoption.canonical_write_performed is False
    usage = apply_completion_usage(
        budget,
        CodexImageGenerationBudgetUsage(),
        completion,
        elapsed_seconds=2,
    )
    assert usage.total_generations == 1
    assert usage.candidates == 1


def test_native_png_is_preserved_normalized_and_passes_existing_core_selection(
    tmp_path: Path,
) -> None:
    """Adopt 1254px native bytes, normalize to 64px, then reuse core completion."""

    assignment, assignment_artifact, _budget = _build_assignment(tmp_path)
    native_source = (
        tmp_path
        / "production/autonomy_v2/session-1/codex_imagegen/controller-native.png"
    )
    native_seed = native_source.with_name("controller-native-seed.png")
    _write_tileable_png(native_seed, width=64, height=64, mode="RGB")
    with Image.open(native_seed) as seeded:
        seeded.resize((1254, 1254), Image.Resampling.NEAREST).save(
            native_source,
            format="PNG",
        )
    original_bytes = native_source.read_bytes()
    original_sha256 = sha256_file(native_source)
    adoption = adopt_codex_imagegen_native_output(
        job_root=tmp_path,
        assignment_artifact=assignment_artifact,
        allowed_source_root=tmp_path,
        native_source_path=native_source,
        native_output_id="native-output-1",
        ordinal=0,
        output_role="base_color",
        receipt_contract_id="native-adoption-1",
        created_at=NOW,
    )
    original_path = tmp_path / adoption.original_image.path
    assert adoption.receipt.native_size == MaterialLoopRasterSize(
        width=1254,
        height=1254,
    )
    assert adoption.receipt.expected_assignment_size == MaterialLoopRasterSize(
        width=64,
        height=64,
    )
    assert original_path.read_bytes() == original_bytes
    assert adoption.original_image.sha256 == original_sha256
    resumed_adoption = adopt_codex_imagegen_native_output(
        job_root=tmp_path,
        assignment_artifact=assignment_artifact,
        allowed_source_root=tmp_path,
        native_source_path=native_source.with_name("missing-after-receipt.png"),
        native_output_id="native-output-1",
        ordinal=0,
        output_role="base_color",
        receipt_contract_id="native-adoption-1",
        created_at=NOW,
    )
    assert resumed_adoption == adoption
    _write_tileable_png(native_source, width=1254, height=1254, mode="RGBA")
    with pytest.raises(FileExistsError, match="conflicts"):
        adopt_codex_imagegen_native_output(
            job_root=tmp_path,
            assignment_artifact=assignment_artifact,
            allowed_source_root=tmp_path,
            native_source_path=native_source,
            native_output_id="native-output-1",
            ordinal=0,
            output_role="base_color",
            receipt_contract_id="native-adoption-1",
            created_at=NOW,
        )

    plan = plan_native_image_normalization(
        tmp_path,
        contract_id="native-normalization-1",
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        source_image=adoption.original_image,
        output_path=imagegen_native_normalization_output_path(
            assignment.session_id,
            "native-normalization-1",
        ),
        target_size=MaterialLoopRasterSize(width=64, height=64),
        source_color_space="srgb",
        preferred_operation="contain_pad",
        created_at=NOW,
    )
    plan_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path
        / imagegen_native_normalization_plan_path(
            assignment.session_id,
            plan.contract_id,
        ),
        plan,
        kind="imagegen-native-normalization-plan",
    )
    prepared = prepare_codex_imagegen_native_output_for_core_completion(
        job_root=tmp_path,
        assignment_artifact=assignment_artifact,
        adoption_receipt_artifact=adoption.receipt_artifact,
        plan=plan,
        plan_artifact=plan_artifact,
        receipt_contract_id="native-normalization-receipt-1",
        created_at=NOW,
    )
    assert (
        prepared.receipt.native_output_adoption_receipt
        == adoption.receipt_artifact
    )
    normalized_path = tmp_path / prepared.normalized_image.path
    with Image.open(normalized_path) as opened:
        assert opened.size == (64, 64)
    assert original_path.read_bytes() == original_bytes
    assert sha256_file(original_path) == original_sha256

    output_paths = tuple(
        tmp_path / path
        for path in [
            *assignment.candidate_output_paths,
            assignment.completion_file_target,
        ]
    )
    completion = copy_imagegen_png_and_write_completion(
        controller_workspace_root=tmp_path,
        allowed_source_root=tmp_path,
        assignment_path=tmp_path / assignment_artifact.path,
        assignment_artifact=assignment_artifact,
        source_png_paths=[normalized_path],
        allowed_output_paths=output_paths,
        output_roles=["base_color"],
        completion_id="native-completion-1",
        controller_kind="fake_for_tests",
        controller_executed_at=NOW,
    )
    completion_artifact = artifact_for_codex_image(
        tmp_path,
        output_paths[-1],
        artifact_id=completion.contract_id,
        kind="codex-image-generation-completion",
        media_type="application/json",
    )
    validate_codex_imagegen_completion(
        job_root=tmp_path,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
    )
    controller_request = _write_artifact(
        tmp_path,
        "production/autonomy_v2/session-1/codex_imagegen/native-request.json",
        artifact_id="native-request-1",
        kind="controller-request",
    )
    controller_result = _write_artifact(
        tmp_path,
        "production/autonomy_v2/session-1/codex_imagegen/native-result.json",
        artifact_id="native-result-1",
        kind="controller-result",
    )
    candidate = build_codex_imagegen_candidate(
        contract_id="native-candidate-1",
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        controller_request_artifact=controller_request,
        controller_result_artifact=controller_result,
        generated_file=completion.generated_files[0],
        created_at=NOW,
    )
    candidate_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path / "production/autonomy_v2/session-1/codex_imagegen/native-candidate.json",
        candidate,
        kind="codex-image-generation-candidate",
    )
    evidence = build_generated_image_evidence(
        contract_id="native-evidence-1",
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        created_at=NOW,
    )
    evidence_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path / "production/autonomy_v2/session-1/codex_imagegen/native-evidence.json",
        evidence,
        kind="codex-generated-image-evidence",
    )
    report = evaluate_candidate_quality(
        job_root=tmp_path,
        report_id="native-quality-1",
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        generated_image_evidence=evidence,
        generated_image_evidence_artifact=evidence_artifact,
        created_at=NOW,
    )
    report_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path / "production/autonomy_v2/session-1/codex_imagegen/native-quality.json",
        report,
        kind="codex-image-generation-quality-report",
    )
    selection = select_codex_imagegen_candidate(
        selection_id="native-selection-1",
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidates=[(candidate, candidate_artifact)],
        quality_reports=[(report, report_artifact)],
        created_at=NOW,
    )
    assert report.outcome == "passed"
    assert selection.outcome == "selected"
    assert selection.selected_candidate == candidate_artifact
    assert original_path.read_bytes() == original_bytes
    selection_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path
        / "production/autonomy_v2/session-1/codex_imagegen/native-selection.json",
        selection,
        kind="codex-image-generation-selection",
    )
    with pytest.raises(ValueError, match="origin is orphaned"):
        validate_native_core_preparation_binding(
            job_root=tmp_path,
            assignment_artifact=assignment_artifact,
            core_completion=completion_artifact,
            core_candidate=candidate_artifact,
            core_generated_image_evidence=evidence_artifact,
            core_quality_report=report_artifact,
            core_selection=selection_artifact,
            preparation_receipt=None,
        )
    native_core = publish_codex_image_native_core_preparation_receipt(
        job_root=tmp_path,
        preparation_id="native-core-preparation-1",
        assignment_artifact=assignment_artifact,
        native_output_adoption_receipt=adoption.receipt_artifact,
        normalization_plan=plan_artifact,
        normalization_receipt=prepared.receipt_artifact,
        core_completion=completion_artifact,
        core_candidate=candidate_artifact,
        core_generated_image_evidence=evidence_artifact,
        core_quality_report=report_artifact,
        core_selection=selection_artifact,
        created_at=NOW,
    )
    validated_preparation = validate_native_core_preparation_binding(
        job_root=tmp_path,
        assignment_artifact=assignment_artifact,
        core_completion=completion_artifact,
        core_candidate=candidate_artifact,
        core_generated_image_evidence=evidence_artifact,
        core_quality_report=report_artifact,
        core_selection=selection_artifact,
        preparation_receipt=native_core.receipt_artifact,
    )
    assert validated_preparation == native_core.receipt
    assert native_core.receipt.core_contracts_modified is False
    assert native_core.receipt.normalized_image.sha256 == (
        native_core.receipt.core_generated_image.sha256
    )
    tampered_preparation_artifact = native_core.receipt_artifact.model_copy(
        update={"sha256": "f" * 64}
    )
    with pytest.raises(ValueError, match="hash changed"):
        validate_codex_image_native_core_preparation_receipt(
            tmp_path,
            tampered_preparation_artifact,
        )

    wrong_assignment = _write_artifact(
        tmp_path,
        "production/autonomy_v2/session-1/codex_imagegen/wrong-assignment.json",
        artifact_id="wrong-assignment",
        kind="codex-image-generation-assignment",
    )
    with pytest.raises(ValueError, match="another assignment"):
        prepare_codex_imagegen_native_output_for_core_completion(
            job_root=tmp_path,
            assignment_artifact=wrong_assignment,
            adoption_receipt_artifact=adoption.receipt_artifact,
            plan=plan,
            plan_artifact=plan_artifact,
            receipt_contract_id="wrong-target-receipt",
            created_at=NOW,
        )
    replay_tamper = plan.model_copy(update={"input_sha256": "f" * 64})
    with pytest.raises(ValueError, match="input digest"):
        prepare_codex_imagegen_native_output_for_core_completion(
            job_root=tmp_path,
            assignment_artifact=assignment_artifact,
            adoption_receipt_artifact=adoption.receipt_artifact,
            plan=replay_tamper,
            plan_artifact=plan_artifact,
            receipt_contract_id="wrong-replay-receipt",
            created_at=NOW,
        )
    receipt_tamper = prepared.receipt_artifact.model_copy(
        update={"sha256": "f" * 64}
    )
    with pytest.raises(ValueError, match="hash changed"):
        validate_prepared_native_output_for_core_completion(
            job_root=tmp_path,
            assignment_artifact=assignment_artifact,
            adoption_receipt_artifact=adoption.receipt_artifact,
            plan=plan,
            plan_artifact=plan_artifact,
            receipt_artifact=receipt_tamper,
        )
    adoption_tamper = adoption.receipt_artifact.model_copy(
        update={"sha256": "e" * 64}
    )
    with pytest.raises(ValueError, match="hash changed"):
        validate_prepared_native_output_for_core_completion(
            job_root=tmp_path,
            assignment_artifact=assignment_artifact,
            adoption_receipt_artifact=adoption_tamper,
            plan=plan,
            plan_artifact=plan_artifact,
            receipt_artifact=prepared.receipt_artifact,
        )
    orphaned_receipt = prepared.receipt.model_copy(
        update={
            "native_output_adoption_receipt": None,
            "input_sha256": stable_json_digest(
                {
                    "plan_sha256": plan_artifact.sha256,
                    "source_sha256": plan.source_image.sha256,
                    "output_sha256": prepared.normalized_image.sha256,
                    "native_output_adoption_receipt_sha256": None,
                }
            ),
        }
    )
    with pytest.raises(ValueError, match="native-original normalization"):
        validate_native_normalization_receipt(tmp_path, plan, orphaned_receipt)


def test_native_origin_scan_rejects_linked_normalization_root(tmp_path: Path) -> None:
    """Reject a linked normalization evidence root instead of treating it as absent."""

    assignment, assignment_artifact, _budget = _build_assignment(tmp_path)
    image_artifact = _write_artifact(
        tmp_path,
        "production/autonomy_v2/session-1/codex_imagegen/generated-placeholder.png",
        artifact_id="generated-placeholder",
        kind="codex-generated-image",
        media_type="image/png",
    )
    evidence_parent = (
        tmp_path
        / "production"
        / "autonomy_v2"
        / assignment.session_id
        / "codex_imagegen"
    )
    evidence_parent.mkdir(parents=True, exist_ok=True)
    linked_root = evidence_parent / "native_normalizations"
    linked_target = tmp_path / "linked-native-normalizations"
    linked_target.mkdir()
    _create_native_directory_link_or_skip(linked_root, linked_target)

    with pytest.raises(ValueError, match="symlink or junction"):
        native_core_service._matching_native_normalization_origins(
            tmp_path,
            assignment=assignment,
            assignment_artifact=assignment_artifact,
            generated_image=image_artifact,
            ordinal=0,
            output_role="base_color",
        )


def test_native_original_crash_adoption_and_tamper_rejection(tmp_path: Path) -> None:
    """Adopt an exact crash-left original and reject conflicting or changed evidence."""

    _assignment, assignment_artifact, _budget = _build_assignment(tmp_path)
    source = (
        tmp_path / "production/autonomy_v2/session-1/codex_imagegen/native-crash.png"
    )
    _write_tileable_png(source, width=96, height=96, mode="RGBA")
    first = adopt_codex_imagegen_native_output_bytes(
        tmp_path,
        assignment_artifact=assignment_artifact,
        allowed_source_root=tmp_path,
        native_source_path=source,
        native_output_id="native-crash-1",
        ordinal=0,
        output_role="base_color",
        receipt_contract_id="native-crash-receipt-1",
        created_at=NOW,
    )
    resumed = adopt_codex_imagegen_native_output_bytes(
        tmp_path,
        assignment_artifact=assignment_artifact,
        allowed_source_root=tmp_path,
        native_source_path=source,
        native_output_id="native-crash-1",
        ordinal=0,
        output_role="base_color",
        receipt_contract_id="native-crash-receipt-1",
        created_at=NOW,
    )
    assert resumed == first
    validate_codex_image_native_output_adoption(tmp_path, resumed)

    forged = resumed.model_copy(update={"input_sha256": "f" * 64})
    with pytest.raises(ValueError, match="digest"):
        validate_codex_image_native_output_adoption(tmp_path, forged)
    _write_tileable_png(source, width=96, height=96, mode="RGB")
    with pytest.raises(FileExistsError, match="conflicts"):
        adopt_codex_imagegen_native_output_bytes(
            tmp_path,
            assignment_artifact=assignment_artifact,
            allowed_source_root=tmp_path,
            native_source_path=source,
            native_output_id="native-crash-1",
            ordinal=0,
            output_role="base_color",
            receipt_contract_id="native-crash-receipt-1",
            created_at=NOW,
        )
    original_path = tmp_path / resumed.original_image.path
    original_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="(?:size|hash) changed"):
        validate_codex_image_native_output_adoption(tmp_path, resumed)


@pytest.mark.parametrize(
    ("mode", "expected_status", "expected_outcome"),
    [("RGBA", "passed", "passed"), ("RGB", "failed", "failed")],
)
def test_opacity_source_quality_requires_extractable_alpha(
    tmp_path: Path,
    mode: str,
    expected_status: str,
    expected_outcome: str,
) -> None:
    """Require an explicit PNG alpha band before opacity-source pixels are eligible."""

    root = tmp_path / mode.lower()
    root.mkdir()
    assignment, assignment_artifact, _budget = _build_assignment(
        root,
        output_role="opacity_source",
    )
    source = root / "production/autonomy_v2/session-1/codex_imagegen/opacity.png"
    _write_tileable_png(source, mode=mode)
    output_paths = tuple(
        root / path
        for path in [
            *assignment.candidate_output_paths,
            assignment.completion_file_target,
        ]
    )
    completion = copy_imagegen_png_and_write_completion(
        controller_workspace_root=root,
        allowed_source_root=root,
        assignment_path=root / assignment_artifact.path,
        assignment_artifact=assignment_artifact,
        source_png_paths=[source],
        allowed_output_paths=output_paths,
        output_roles=["opacity_source"],
        completion_id=f"completion-opacity-{mode.lower()}",
        controller_kind="fake_for_tests",
        controller_executed_at=NOW,
    )
    completion_artifact = artifact_for_codex_image(
        root,
        output_paths[-1],
        artifact_id=completion.contract_id,
        kind="codex-image-generation-completion",
        media_type="application/json",
    )
    controller_request = _write_artifact(
        root,
        "production/autonomy_v2/session-1/codex_imagegen/opacity-request.json",
        artifact_id=f"opacity-request-{mode.lower()}",
        kind="controller-request",
    )
    controller_result = _write_artifact(
        root,
        "production/autonomy_v2/session-1/codex_imagegen/opacity-result.json",
        artifact_id=f"opacity-result-{mode.lower()}",
        kind="controller-result",
    )
    candidate = build_codex_imagegen_candidate(
        contract_id=f"opacity-candidate-{mode.lower()}",
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        controller_request_artifact=controller_request,
        controller_result_artifact=controller_result,
        generated_file=completion.generated_files[0],
        created_at=NOW,
    )
    candidate_artifact = write_immutable_codex_image_model(
        root,
        root
        / "production/autonomy_v2/session-1/codex_imagegen"
        / f"opacity-candidate-{mode.lower()}.json",
        candidate,
        kind="codex-image-generation-candidate",
    )
    evidence = build_generated_image_evidence(
        contract_id=f"opacity-evidence-{mode.lower()}",
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        created_at=NOW,
    )
    evidence_artifact = write_immutable_codex_image_model(
        root,
        root
        / "production/autonomy_v2/session-1/codex_imagegen"
        / f"opacity-evidence-{mode.lower()}.json",
        evidence,
        kind="codex-generated-image-evidence",
    )
    report = evaluate_candidate_quality(
        job_root=root,
        report_id=f"opacity-quality-{mode.lower()}",
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        generated_image_evidence=evidence,
        generated_image_evidence_artifact=evidence_artifact,
        created_at=NOW,
    )
    alpha = next(
        check for check in report.checks if check.check_id == "alpha-extractability"
    )
    assert alpha.status == expected_status
    assert alpha.hard_gate is True
    assert report.outcome == expected_outcome
    assert report.selection_eligible is (expected_outcome == "passed")


def test_immutable_model_publication_exact_adopts_duplicate_bytes(tmp_path: Path) -> None:
    """Exact-adopt identical evidence while never rewriting its immutable bytes."""

    assignment, _artifact, _budget = _build_assignment(tmp_path)
    duplicate = tmp_path / "duplicate.json"
    first = write_immutable_codex_image_model(
        tmp_path,
        duplicate,
        assignment,
        kind="codex-image-generation-assignment",
    )
    original = duplicate.read_bytes()
    adopted = write_immutable_codex_image_model(
        tmp_path,
        duplicate,
        assignment,
        kind="codex-image-generation-assignment",
    )
    assert adopted == first
    assert duplicate.read_bytes() == original


def test_source_inventory_excludes_only_current_imagegen_subtree(tmp_path: Path) -> None:
    """Keep overlay runtime stable while detecting every protected job-file mutation."""

    assignment, _artifact, _budget = _build_assignment(tmp_path)
    initial = assignment.protected_source_inventory_sha256
    assert initial == codex_image_source_inventory_sha256(tmp_path, "session-1")
    excluded_file = (
        tmp_path
        / "production/autonomy_v2/session-1/codex_imagegen/runtime/new-output.json"
    )
    excluded_file.parent.mkdir(parents=True, exist_ok=True)
    excluded_file.write_text("{}\n", encoding="utf-8")
    assert initial == codex_image_source_inventory_sha256(tmp_path, "session-1")
    protected_file = tmp_path / "production/protected-change.json"
    protected_file.write_text("{}\n", encoding="utf-8")
    assert initial != codex_image_source_inventory_sha256(tmp_path, "session-1")


def test_fake_controller_writes_only_declared_local_outputs(tmp_path: Path) -> None:
    """Exercise the deterministic fake backend without a provider SDK or network client."""

    assignment, assignment_artifact, _budget = _build_assignment(tmp_path)
    outputs = tuple(
        tmp_path / path
        for path in [
            *assignment.candidate_output_paths,
            assignment.completion_file_target,
        ]
    )
    controller = FakeCodexImagegenController(
        assignment_artifact=assignment_artifact,
        executed_at=NOW,
    )
    profile = type("ProfileFixture", (), {"network_access": "denied"})()
    token = controller.execute(
        assignment=tmp_path / assignment_artifact.path,
        immutable_inputs=(),
        allowed_output_paths=outputs,
        tool_profile=profile,
        timeout_seconds=30,
    )
    assert token == "completed"
    assert controller.calls == 1
    assert all(path.is_file() for path in outputs)


def test_fake_controller_over_budget_completion_fails_closed(tmp_path: Path) -> None:
    """Reject a fake completion that exceeds the immutable per-assignment generation cap."""

    assignment, assignment_artifact, _budget = _build_assignment(tmp_path)
    outputs = tuple(
        tmp_path / path
        for path in [
            *assignment.candidate_output_paths,
            assignment.completion_file_target,
        ]
    )
    controller = FakeCodexImagegenController(
        assignment_artifact=assignment_artifact,
        behavior="over_budget",
        executed_at=NOW,
    )
    profile = type("ProfileFixture", (), {"network_access": "denied"})()
    token = controller.execute(
        assignment=tmp_path / assignment_artifact.path,
        immutable_inputs=(),
        allowed_output_paths=outputs,
        tool_profile=profile,
        timeout_seconds=900,
    )
    assert token == "completed"
    completion_artifact = artifact_for_codex_image(
        tmp_path,
        outputs[-1],
        artifact_id="completion-assignment-1",
        kind="codex-image-generation-completion",
        media_type="application/json",
    )
    with pytest.raises(ValueError, match="per-assignment budget"):
        validate_codex_imagegen_completion(
            job_root=tmp_path,
            assignment_artifact=assignment_artifact,
            completion_artifact=completion_artifact,
        )


def test_public_completion_adoption_replays_full_controller_lifecycle(
    tmp_path: Path,
) -> None:
    """Require raw executor receipts before host candidate evidence can be published."""

    assignment, assignment_artifact, _budget = _build_assignment(tmp_path)
    controller_assignment = ControllerArtifact(
        artifact_id=assignment_artifact.artifact_id,
        role="assignment",
        path=assignment_artifact.path,
        sha256=assignment_artifact.sha256,
        byte_size=assignment_artifact.byte_size,
    )
    output_paths = [
        *assignment.candidate_output_paths,
        assignment.completion_file_target,
    ]
    profile = build_phase_tool_profile(
        profile_id="codex_imagegen",
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        source_artifact=controller_assignment,
        allowed_input_roles=["assignment"],
        allowed_output_paths=output_paths,
        created_at=NOW,
    )
    execution_root = (
        tmp_path
        / "production/autonomy_v2/session-1/codex_imagegen/controller_executions"
        / "execution-1"
    )
    profile_path = execution_root / "tool-profile.json"
    write_controller_contract(profile_path, profile)
    profile_binding = artifact_for_codex_image(
        tmp_path,
        profile_path,
        artifact_id=profile.contract_id,
        kind="controller-tool-profile",
        media_type="application/json",
    )
    controller_profile = ControllerArtifact(
        artifact_id=profile_binding.artifact_id,
        role="tool_profile",
        path=profile_binding.path,
        sha256=profile_binding.sha256,
        byte_size=profile_binding.byte_size,
    )
    request_inputs = {
        "assignment": controller_assignment.sha256,
        "profile": controller_profile.sha256,
        "outputs": output_paths,
    }
    request = ControllerExecutionRequest(
        contract_id="controller-request-1",
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        input_sha256=stable_json_digest(request_inputs),
        source_fingerprint=stable_json_digest(
            {**request_inputs, "provider": assignment.provider_id}
        ),
        producer="tests.codex_imagegen",
        provenance=[controller_assignment, controller_profile],
        created_at=NOW,
        execution_id="execution-1",
        controller_kind="fake_for_tests",
        assignment=controller_assignment,
        immutable_inputs=[controller_assignment],
        tool_profile=controller_profile,
        output_root=assignment.staging_output_directory,
        allowed_output_paths=output_paths,
        timeout_seconds=30,
    )
    request_path = execution_root / "request.json"
    write_controller_contract(request_path, request)
    request_artifact = artifact_for_codex_image(
        tmp_path,
        request_path,
        artifact_id=request.contract_id,
        kind="controller-request",
        media_type="application/json",
    )
    controller = FakeCodexImagegenController(
        assignment_artifact=assignment_artifact,
        executed_at=NOW,
    )
    result = execute_controller_request(
        job_root=tmp_path,
        request_path=request_path,
        controller=controller,
    )
    assert result.status == "completed"
    result_path = execution_root / "result.json"
    write_json_atomic(result_path, result.model_dump(mode="json"))
    result_artifact = artifact_for_codex_image(
        tmp_path,
        result_path,
        artifact_id=result.contract_id,
        kind="controller-result",
        media_type="application/json",
    )
    completion_artifact = artifact_for_codex_image(
        tmp_path,
        tmp_path / assignment.completion_file_target,
        artifact_id=f"completion-{assignment.assignment_id}",
        kind="codex-image-generation-completion",
        media_type="application/json",
    )
    adopted = adopt_codex_imagegen_completion(
        job_root=tmp_path,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        controller_request_artifact=request_artifact,
        controller_result_artifact=result_artifact,
        controller=controller,
        created_at=NOW,
    )
    assert len(adopted.candidates) == 1
    assert len(adopted.generated_evidence) == 1
    assert controller.calls == 1


def test_controller_helper_rejects_output_and_source_root_escape(tmp_path: Path) -> None:
    """Require explicit containment for both isolated outputs and local generated sources."""

    assignment, assignment_artifact, _budget = _build_assignment(tmp_path)
    source = tmp_path / "source.png"
    _write_tileable_png(source)
    escaped_root = tmp_path.parent / f"{tmp_path.name}-escaped"
    escaped_outputs = (
        escaped_root / "candidate-00.png",
        escaped_root / "completion.json",
    )
    with pytest.raises(ValueError, match="escapes"):
        copy_imagegen_png_and_write_completion(
            controller_workspace_root=tmp_path,
            allowed_source_root=tmp_path,
            assignment_path=tmp_path / assignment_artifact.path,
            assignment_artifact=assignment_artifact,
            source_png_paths=[source],
            allowed_output_paths=escaped_outputs,
            output_roles=["base_color"],
            completion_id="escaped-completion",
            controller_kind="fake_for_tests",
            controller_executed_at=NOW,
        )
    allowed_source_root = tmp_path / "allowed-sources"
    allowed_source_root.mkdir()
    outputs = tuple(
        tmp_path / path
        for path in [
            *assignment.candidate_output_paths,
            assignment.completion_file_target,
        ]
    )
    with pytest.raises(ValueError, match="escapes"):
        copy_imagegen_png_and_write_completion(
            controller_workspace_root=tmp_path,
            allowed_source_root=allowed_source_root,
            assignment_path=tmp_path / assignment_artifact.path,
            assignment_artifact=assignment_artifact,
            source_png_paths=[source],
            allowed_output_paths=outputs,
            output_roles=["base_color"],
            completion_id="escaped-source-completion",
            controller_kind="fake_for_tests",
            controller_executed_at=NOW,
        )


def test_controller_helper_rejects_linked_source_when_supported(tmp_path: Path) -> None:
    """Reject a source symlink instead of following it into staged evidence."""

    assignment, assignment_artifact, _budget = _build_assignment(tmp_path)
    source_root = tmp_path / "allowed-sources"
    source = source_root / "source.png"
    _write_tileable_png(source)
    linked = source_root / "linked.png"
    try:
        linked.symlink_to(source)
    except OSError:
        pytest.skip("test environment cannot create a file symlink")
    outputs = tuple(
        tmp_path / path
        for path in [
            *assignment.candidate_output_paths,
            assignment.completion_file_target,
        ]
    )
    with pytest.raises(ValueError, match="symlink|junction|non-linked"):
        copy_imagegen_png_and_write_completion(
            controller_workspace_root=tmp_path,
            allowed_source_root=source_root,
            assignment_path=tmp_path / assignment_artifact.path,
            assignment_artifact=assignment_artifact,
            source_png_paths=[linked],
            allowed_output_paths=outputs,
            output_roles=["base_color"],
            completion_id="linked-source-completion",
            controller_kind="fake_for_tests",
            controller_executed_at=NOW,
        )
def test_contracts_reject_prompt_tampering_and_forbidden_direct_channel(
    tmp_path: Path,
) -> None:
    """Fail closed on stale prompt bytes and direct normal-map generation claims."""

    assignment, _artifact, _budget = _build_assignment(tmp_path)
    tampered = assignment.model_dump()
    tampered["rendered_prompt_text"] = "changed prompt"
    with pytest.raises(ValidationError, match="prompt hash"):
        type(assignment).model_validate(tampered)
    item_payload = {
        "plan_item_id": "invalid-role",
        "target_material_ids": ["material-1"],
        "semantic_roles": ["surface"],
        "generation_intent": "generated_surface_swatch_v1",
        "allowed_output_roles": ["normal"],
        "prompt_template_id": "prompt-1",
        "requested_candidate_count": 1,
        "quality_level": "low",
        "image_size": {"width": 64, "height": 64},
        "aspect_ratio": "square",
        "fallback": "local_procedural_fallback",
    }
    with pytest.raises(ValidationError):
        CodexImageGenerationPlanItem.model_validate(item_payload)


def test_exact_signage_text_is_hashed_but_never_sent_in_prompt(tmp_path: Path) -> None:
    """Keep exact glyph content local while retaining a byte-exact assignment binding."""

    assignment, _artifact, _budget = _build_assignment(
        tmp_path,
        exact_text_value="OPEN 24H",
    )
    assert assignment.exact_text_sha256 is not None
    assert "OPEN 24H" not in assignment.rendered_prompt_text
    second_root = tmp_path / "second-job"
    second_root.mkdir()
    with pytest.raises(ValueError, match="must not appear"):
        _build_assignment(
            second_root,
            prompt="make a sign reading open 24h",
            exact_text_value="OPEN 24H",
        )


def test_completion_validation_rejects_generated_pixel_tampering(tmp_path: Path) -> None:
    """Reject a PNG whose bytes change after controller completion publication."""

    assignment, assignment_artifact, _budget = _build_assignment(tmp_path)
    source = (
        tmp_path
        / "production/autonomy_v2/session-1/codex_imagegen/source-for-tamper.png"
    )
    _write_tileable_png(source)
    output_paths = tuple(
        tmp_path / path
        for path in [
            *assignment.candidate_output_paths,
            assignment.completion_file_target,
        ]
    )
    completion = copy_imagegen_png_and_write_completion(
        controller_workspace_root=tmp_path,
        allowed_source_root=source.parent,
        assignment_path=tmp_path / assignment_artifact.path,
        assignment_artifact=assignment_artifact,
        source_png_paths=[source],
        allowed_output_paths=output_paths,
        output_roles=["base_color"],
        completion_id="completion-tamper",
        controller_kind="fake_for_tests",
        controller_executed_at=NOW,
    )
    completion_artifact = artifact_for_codex_image(
        tmp_path,
        output_paths[-1],
        artifact_id=completion.contract_id,
        kind="codex-image-generation-completion",
        media_type="application/json",
    )
    with output_paths[0].open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(ValueError, match="size changed|hash changed"):
        validate_codex_imagegen_completion(
            job_root=tmp_path,
            assignment_artifact=assignment_artifact,
            completion_artifact=completion_artifact,
        )
