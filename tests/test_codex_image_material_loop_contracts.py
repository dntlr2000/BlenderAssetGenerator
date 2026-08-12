"""Focused strict-contract and semantic-review tests for the ImageGen material loop."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from codex_blender_modeler.autonomy_v2 import (
    codex_image_material_loop_service as loop_service,
)
from codex_blender_modeler.blender_artifacts import stable_json_digest
from codex_blender_modeler.codex_imagegen.artifacts import (
    artifact_for_codex_image,
    load_codex_image_model,
    write_immutable_codex_image_model,
)
from codex_blender_modeler.codex_imagegen.material_loop_models import (
    ALL_SEMANTIC_REVIEW_CATEGORIES,
    CodexImageMaterialLoopState,
    CodexImageMaterialLoopTerminal,
    CodexImageSemanticCheck,
    CodexImageSemanticReview,
    ImageGeneratedMaterialBridgePlan,
    ImageGeneratedMaterialControllerBinding,
    ImageGeneratedMaterialControllerInput,
    ImageGeneratedMaterialNeutralPreview,
    ImageGeneratedMaterialPromotionReceipt,
    ImageGenNativeNormalizationPlan,
    ImageGenNativeNormalizationReceipt,
    ImageMaterialLoopBudgetUsage,
    material_loop_state_input_sha256,
    validate_material_loop_transition,
)
from codex_blender_modeler.codex_imagegen.material_loop_semantic import (
    build_codex_image_semantic_review,
    candidate_selection_precedence_key,
    semantic_review_gate,
    validate_codex_image_semantic_review,
)
from codex_blender_modeler.codex_imagegen.models import CodexImageArtifact

NOW = datetime(2026, 8, 12, 0, 0, tzinfo=UTC)
SHA_A = "a" * 64


def _semantic_artifacts(root: Path) -> tuple[CodexImageArtifact, ...]:
    """Create exact reviewed-image, assignment, and deterministic-quality artifacts."""

    image_path = root / "imagegen" / "candidate.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (88, 56, 31)).save(image_path)
    assignment_path = root / "imagegen" / "assignment.json"
    assignment_path.write_text('{"assignment":true}\n', encoding="utf-8")
    quality_path = root / "imagegen" / "quality.json"
    quality_path.write_text('{"outcome":"passed"}\n', encoding="utf-8")
    return (
        artifact_for_codex_image(
            root,
            image_path,
            artifact_id="candidate-image",
            kind="codex-generated-image",
            media_type="image/png",
        ),
        artifact_for_codex_image(
            root,
            assignment_path,
            artifact_id="assignment",
            kind="codex-image-assignment",
            media_type="application/json",
        ),
        artifact_for_codex_image(
            root,
            quality_path,
            artifact_id="quality",
            kind="codex-image-quality",
            media_type="application/json",
        ),
    )


def _checks(
    overrides: dict[str, tuple[str, bool]] | None = None,
) -> list[CodexImageSemanticCheck]:
    """Build the exact canonical semantic category order with optional outcomes."""

    overrides = overrides or {}
    return [
        CodexImageSemanticCheck(
            category=category,
            outcome=overrides.get(category, ("passed", False))[0],
            confidence=0.9,
            rationale=f"bounded observation for {category}",
            explicit_forbidden_content=overrides.get(category, ("passed", False))[1],
        )
        for category in ALL_SEMANTIC_REVIEW_CATEGORIES
    ]


def _review(
    root: Path,
    *,
    checks: list[CodexImageSemanticCheck] | None = None,
    material_family: str = "wood",
) -> CodexImageSemanticReview:
    """Build one exact semantic review through the host constructor."""

    reviewed, assignment, quality = _semantic_artifacts(root)
    return build_codex_image_semantic_review(
        root,
        contract_id="semantic-review",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        candidate_id="candidate-1",
        reviewed_image=reviewed,
        assignment=assignment,
        deterministic_quality_report=quality,
        material_family=material_family,
        checks=checks or _checks(),
        created_at=NOW,
    )


def _contract_artifact(root: Path, name: str) -> CodexImageArtifact:
    """Create one unique exact JSON artifact for contract-closure tests."""

    path = root / "contract_evidence" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{{"artifact":"{name}"}}\n', encoding="utf-8")
    return artifact_for_codex_image(
        root,
        path,
        artifact_id=f"artifact-{name}",
        kind="material-loop-test-evidence",
        media_type="application/json",
    )


def _unique_artifacts(items: list[CodexImageArtifact]) -> list[CodexImageArtifact]:
    """Preserve order while collapsing only complete exact cross-field aliases."""

    observed: set[tuple[str, str, str, str, int, str]] = set()
    result: list[CodexImageArtifact] = []
    for item in items:
        identity = (
            item.artifact_id,
            item.kind,
            item.path,
            item.sha256,
            item.byte_size,
            item.media_type,
        )
        if identity not in observed:
            observed.add(identity)
            result.append(item)
    return result


def _bridge_plan_fixture(
    root: Path,
    *,
    requested_delivery_profiles: list[str] | None = None,
) -> tuple[ImageGeneratedMaterialBridgePlan, dict[str, CodexImageArtifact]]:
    """Build one complete bridge plan with an aliased ordered V0.5 input closure."""

    names = (
        "root-authorization",
        "aq-plan",
        "aq-profile",
        "aq-budget",
        "current-state",
        "canonical-scene",
        "geometry-receipt",
        "build-provenance",
        "provider-profile",
        "imagegen-plan",
        "assignment",
        "completion",
        "generation-terminal",
        "selected-candidate",
        "generated-evidence",
        "quality-report",
        "selection",
        "semantic-review",
        "normalization-receipt",
        "adoption",
        "authoring-request",
        "authoring-manifest",
        "authoring-receipt",
        "v05-receipt",
        "texture-output",
        "candidate-material-plan",
        "material-graph",
        "shader-recipe",
        "texture-manifest",
        "previous-material-plan",
        "v05-extra-input",
    )
    evidence = {name: _contract_artifact(root, name) for name in names}
    canonical_path = root / "analysis" / "material_plan.json"
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_bytes(
        (root / evidence["previous-material-plan"].path).read_bytes()
    )
    evidence["canonical-material-observation"] = artifact_for_codex_image(
        root,
        canonical_path,
        artifact_id="artifact-canonical-material-observation",
        kind="v05-material-plan",
        media_type="application/json",
    )
    direct = [
        evidence["root-authorization"],
        evidence["aq-plan"],
        evidence["aq-profile"],
        evidence["aq-budget"],
        evidence["current-state"],
        evidence["canonical-scene"],
        evidence["geometry-receipt"],
        evidence["build-provenance"],
        evidence["provider-profile"],
        evidence["imagegen-plan"],
        evidence["assignment"],
        evidence["completion"],
        evidence["generation-terminal"],
        evidence["selected-candidate"],
        evidence["generated-evidence"],
        evidence["quality-report"],
        evidence["selection"],
        evidence["semantic-review"],
        evidence["normalization-receipt"],
        evidence["adoption"],
        evidence["authoring-request"],
        evidence["authoring-manifest"],
        evidence["authoring-receipt"],
        evidence["v05-receipt"],
        evidence["texture-output"],
        evidence["candidate-material-plan"],
        evidence["material-graph"],
        evidence["shader-recipe"],
        evidence["texture-manifest"],
        evidence["canonical-material-observation"],
        evidence["previous-material-plan"],
    ]
    v05_inputs = [
        evidence["candidate-material-plan"],
        evidence["v05-extra-input"],
    ]
    allowed = [
        "controller/run/material_plan.json",
        "controller/run/material_graph.json",
        "controller/run/completion.json",
    ]
    expected = {
        allowed[0]: evidence["candidate-material-plan"].sha256,
        allowed[1]: evidence["material-graph"].sha256,
    }
    provenance = _unique_artifacts([*direct, *v05_inputs])
    plan = ImageGeneratedMaterialBridgePlan(
        contract_id="material-bridge-plan-session-loop",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        input_sha256=stable_json_digest(
            {item.path: item.sha256 for item in provenance}
        ),
        source_fingerprint=SHA_A,
        producer="material-loop-contract-test",
        provenance=provenance,
        created_at=NOW,
        base_aq_session_id="session-loop",
        selected_candidate_id="candidate-1",
        material_authoring_run_id="authoring-run",
        material_controller_request_id="controller-request",
        root_authorization=evidence["root-authorization"],
        aq_plan=evidence["aq-plan"],
        aq_profile=evidence["aq-profile"],
        aq_budget=evidence["aq-budget"],
        current_state=evidence["current-state"],
        canonical_scene_spec=evidence["canonical-scene"],
        geometry_validation_receipt=evidence["geometry-receipt"],
        current_build_provenance=evidence["build-provenance"],
        provider_profile=evidence["provider-profile"],
        imagegen_plan=evidence["imagegen-plan"],
        assignment=evidence["assignment"],
        completion=evidence["completion"],
        generation_terminal=evidence["generation-terminal"],
        selected_candidate=evidence["selected-candidate"],
        generated_image_evidence=evidence["generated-evidence"],
        quality_report=evidence["quality-report"],
        selection=evidence["selection"],
        semantic_review=evidence["semantic-review"],
        normalization_receipt=evidence["normalization-receipt"],
        adoption=evidence["adoption"],
        material_authoring_request=evidence["authoring-request"],
        material_authoring_manifest=evidence["authoring-manifest"],
        material_authoring_receipt=evidence["authoring-receipt"],
        v05_bridge_receipt=evidence["v05-receipt"],
        v05_controller_inputs=v05_inputs,
        texture_outputs=[evidence["texture-output"]],
        candidate_material_plan=evidence["candidate-material-plan"],
        material_graph_spec=evidence["material-graph"],
        shader_recipes=[evidence["shader-recipe"]],
        texture_manifests=[evidence["texture-manifest"]],
        canonical_material_observation=evidence[
            "canonical-material-observation"
        ],
        previous_material_plan=evidence["previous-material-plan"],
        canonical_scene_spec_sha256=evidence["canonical-scene"].sha256,
        geometry_build_fingerprint=SHA_A,
        uv_fingerprint=SHA_A,
        target_material_ids=["material-main"],
        target_semantic_ids=["semantic-main"],
        mutable_material_ids=["material-main"],
        requested_delivery_profiles=requested_delivery_profiles or ["none"],
        execution_mode="controller_authored_completion",
        output_root="controller/run",
        allowed_output_paths=allowed,
        expected_output_sha256=expected,
    )
    return plan, evidence


def _controller_input_fixture(
    root: Path,
) -> tuple[ImageGeneratedMaterialControllerInput, dict[str, CodexImageArtifact]]:
    """Build one controller input whose map contains the full unique V0.5 closure."""

    plan, evidence = _bridge_plan_fixture(root)
    plan_artifact = write_immutable_codex_image_model(
        root,
        root / "contract_evidence" / "bridge-plan.json",
        plan,
        kind="material-bridge-plan",
    )
    phase_profile = _contract_artifact(root, "phase-profile")
    direct = [
        plan_artifact,
        plan.current_state,
        phase_profile,
        plan.root_authorization,
        plan.aq_plan,
        plan.aq_profile,
        plan.aq_budget,
        plan.canonical_scene_spec,
        plan.geometry_validation_receipt,
        plan.current_build_provenance,
        plan.provider_profile,
        plan.generation_terminal,
        plan.selected_candidate,
        plan.generated_image_evidence,
        plan.quality_report,
        plan.selection,
        plan.semantic_review,
        plan.normalization_receipt,
        plan.adoption,
        plan.material_authoring_request,
        plan.material_authoring_manifest,
        plan.material_authoring_receipt,
        plan.v05_bridge_receipt,
        *plan.texture_outputs,
        plan.candidate_material_plan,
        plan.material_graph_spec,
        *plan.shader_recipes,
        *plan.texture_manifests,
        plan.canonical_material_observation,
        plan.previous_material_plan,
    ]
    artifacts = _unique_artifacts([*direct, *plan.v05_controller_inputs])
    controller_input = ImageGeneratedMaterialControllerInput(
        contract_id="material-controller-input-session-loop",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=stable_json_digest(
            {item.path: item.sha256 for item in artifacts}
        ),
        source_fingerprint=plan_artifact.sha256,
        producer="codex_blender_modeler.autonomy_v2.codex_image_material_loop_service",
        provenance=artifacts,
        created_at=NOW,
        bridge_plan=plan_artifact,
        current_state=plan.current_state,
        phase_tool_profile=phase_profile,
        root_authorization=plan.root_authorization,
        aq_plan=plan.aq_plan,
        aq_profile=plan.aq_profile,
        aq_budget=plan.aq_budget,
        canonical_scene_spec=plan.canonical_scene_spec,
        geometry_validation_receipt=plan.geometry_validation_receipt,
        current_build_provenance=plan.current_build_provenance,
        provider_profile=plan.provider_profile,
        generation_terminal=plan.generation_terminal,
        selected_candidate=plan.selected_candidate,
        generated_image_evidence=plan.generated_image_evidence,
        quality_report=plan.quality_report,
        selection=plan.selection,
        semantic_review=plan.semantic_review,
        normalization_receipt=plan.normalization_receipt,
        adoption=plan.adoption,
        material_authoring_request=plan.material_authoring_request,
        material_authoring_manifest=plan.material_authoring_manifest,
        material_authoring_receipt=plan.material_authoring_receipt,
        v05_bridge_receipt=plan.v05_bridge_receipt,
        v05_controller_inputs=plan.v05_controller_inputs,
        texture_outputs=plan.texture_outputs,
        candidate_material_plan=plan.candidate_material_plan,
        material_graph_spec=plan.material_graph_spec,
        shader_recipes=plan.shader_recipes,
        texture_manifests=plan.texture_manifests,
        canonical_material_observation=plan.canonical_material_observation,
        previous_material_plan=plan.previous_material_plan,
        immutable_input_sha256={item.path: item.sha256 for item in artifacts},
        source_scene_spec_sha256=plan.canonical_scene_spec.sha256,
        source_material_plan_sha256=plan.previous_material_plan.sha256,
        uv_fingerprint=plan.uv_fingerprint,
        target_material_ids=plan.target_material_ids,
        target_semantic_ids=plan.target_semantic_ids,
        execution_mode=plan.execution_mode,
        output_root=plan.output_root,
        allowed_output_paths=plan.allowed_output_paths,
        expected_output_sha256=plan.expected_output_sha256,
    )
    evidence["v05-extra-input"] = plan.v05_controller_inputs[-1]
    return controller_input, evidence


def _promotion_receipt_fixture(root: Path) -> ImageGeneratedMaterialPromotionReceipt:
    """Build a promotion receipt with a direct promoted-base-state binding."""

    names = (
        "promotion-bridge",
        "promotion-input",
        "promotion-binding",
        "promotion-request",
        "promotion-result",
        "material-phase-receipt",
        "promoted-base-state",
        "promotion-generation-terminal",
        "promotion-selection",
        "promotion-generated-evidence",
        "promotion-semantic-review",
        "promotion-normalization-receipt",
        "promotion-adoption",
        "promotion-authoring-manifest",
        "promotion-authoring-receipt",
        "promotion-graph-compile",
        "promotion-material-validation",
        "promotion-neutral-preview",
        "promotion-preview-manifest",
        "promotion-preview-image",
        "promotion-material-snapshot",
        "promotion-scene-snapshot",
    )
    evidence = {name: _contract_artifact(root, name) for name in names}
    provenance = list(evidence.values())
    return ImageGeneratedMaterialPromotionReceipt(
        contract_id="promotion-receipt",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        input_sha256=stable_json_digest(
            {item.path: item.sha256 for item in provenance}
        ),
        source_fingerprint=evidence["material-phase-receipt"].sha256,
        producer="material-loop-contract-test",
        provenance=provenance,
        created_at=NOW,
        bridge_plan=evidence["promotion-bridge"],
        controller_input=evidence["promotion-input"],
        controller_binding=evidence["promotion-binding"],
        controller_execution_request=evidence["promotion-request"],
        controller_result=evidence["promotion-result"],
        material_phase_receipt=evidence["material-phase-receipt"],
        promoted_base_state=evidence["promoted-base-state"],
        generation_terminal=evidence["promotion-generation-terminal"],
        selection=evidence["promotion-selection"],
        generated_image_evidence=evidence["promotion-generated-evidence"],
        semantic_review=evidence["promotion-semantic-review"],
        normalization_receipt=evidence["promotion-normalization-receipt"],
        adoption=evidence["promotion-adoption"],
        material_authoring_manifest=evidence["promotion-authoring-manifest"],
        material_authoring_receipt=evidence["promotion-authoring-receipt"],
        graph_compile_report=evidence["promotion-graph-compile"],
        material_validation=evidence["promotion-material-validation"],
        neutral_preview=evidence["promotion-neutral-preview"],
        neutral_preview_manifest=evidence["promotion-preview-manifest"],
        neutral_preview_image=evidence["promotion-preview-image"],
        canonical_material_snapshot=evidence["promotion-material-snapshot"],
        canonical_scene_snapshot=evidence["promotion-scene-snapshot"],
        canonical_material_plan_sha256=evidence["promotion-material-snapshot"].sha256,
        canonical_scene_spec_sha256=evidence["promotion-scene-snapshot"].sha256,
    )


def test_bridge_and_controller_bind_ordered_v05_input_closure(tmp_path: Path) -> None:
    """V0.5 receipt and ordered inputs remain direct, provenance, and map evidence."""

    plan, evidence = _bridge_plan_fixture(tmp_path)

    assert plan.v05_controller_inputs == [
        plan.candidate_material_plan,
        evidence["v05-extra-input"],
    ]
    assert evidence["v05-extra-input"] in plan.provenance
    payload = plan.model_dump(mode="python")
    payload["provenance"] = [
        item
        for item in payload["provenance"]
        if item["path"] != evidence["v05-extra-input"].path
    ]
    with pytest.raises(ValidationError, match="incomplete|extras"):
        ImageGeneratedMaterialBridgePlan.model_validate(payload)

    controller_input, controller_evidence = _controller_input_fixture(tmp_path / "input")
    extra = controller_evidence["v05-extra-input"]
    assert controller_input.immutable_input_sha256[extra.path] == extra.sha256
    payload = controller_input.model_dump(mode="python")
    del payload["immutable_input_sha256"][extra.path]
    with pytest.raises(ValidationError, match="immutable controller input map"):
        ImageGeneratedMaterialControllerInput.model_validate(payload)

    plan = load_codex_image_model(
        tmp_path / "input",
        controller_input.bridge_plan,
        ImageGeneratedMaterialBridgePlan,
    )
    loop_service._validate_material_controller_input_closure(
        plan,
        controller_input.bridge_plan,
        controller_input.phase_tool_profile,
        controller_input,
    )


def test_native_core_preparation_artifact_survives_controller_and_promotion_contracts(
    tmp_path: Path,
) -> None:
    """Carry the additive native-to-core receipt through every material authority hop."""

    plan, _evidence = _bridge_plan_fixture(tmp_path / "bridge")
    preparation = _contract_artifact(tmp_path / "bridge", "native-core-preparation")
    plan_payload = plan.model_dump(mode="python")
    plan_payload["native_core_preparation_receipt"] = preparation.model_dump(
        mode="python"
    )
    plan_payload["provenance"].append(preparation.model_dump(mode="python"))
    plan_payload["input_sha256"] = stable_json_digest(
        {
            item["path"]: item["sha256"]
            for item in plan_payload["provenance"]
        }
    )
    native_plan = ImageGeneratedMaterialBridgePlan.model_validate(plan_payload)
    plan_artifact = write_immutable_codex_image_model(
        tmp_path / "bridge",
        tmp_path / "bridge" / "contract_evidence" / "native-bridge-plan.json",
        native_plan,
        kind="material-bridge-plan",
    )
    phase_profile = _contract_artifact(tmp_path / "bridge", "native-phase-profile")
    controller_input = loop_service._build_material_controller_input(
        native_plan,
        plan_artifact,
        phase_profile,
        created_at=NOW,
    )
    assert controller_input.native_core_preparation_receipt == preparation
    assert controller_input.immutable_input_sha256[preparation.path] == preparation.sha256

    promotion = _promotion_receipt_fixture(tmp_path / "promotion")
    promotion_preparation = _contract_artifact(
        tmp_path / "promotion",
        "promotion-native-core-preparation",
    )
    promotion_payload = promotion.model_dump(mode="python")
    promotion_payload["native_core_preparation_receipt"] = (
        promotion_preparation.model_dump(mode="python")
    )
    promotion_payload["provenance"].append(
        promotion_preparation.model_dump(mode="python")
    )
    promotion_payload["input_sha256"] = stable_json_digest(
        {
            item["path"]: item["sha256"]
            for item in promotion_payload["provenance"]
        }
    )
    native_promotion = ImageGeneratedMaterialPromotionReceipt.model_validate(
        promotion_payload
    )
    assert native_promotion.native_core_preparation_receipt == promotion_preparation
    promotion_payload["provenance"] = promotion_payload["provenance"][:-1]
    with pytest.raises(ValidationError, match="incomplete|extras"):
        ImageGeneratedMaterialPromotionReceipt.model_validate(promotion_payload)
    changed = ImageGeneratedMaterialControllerInput.model_validate(
        {
            **controller_input.model_dump(mode="python"),
            "target_material_ids": ["material-replaced"],
        }
    )
    with pytest.raises(ValueError, match="frozen bridge closure"):
        loop_service._validate_material_controller_input_closure(
            plan,
            controller_input.bridge_plan,
            controller_input.phase_tool_profile,
            changed,
        )
    timestamp_replacement = ImageGeneratedMaterialControllerInput.model_validate(
        {
            **controller_input.model_dump(mode="python"),
            "created_at": controller_input.created_at + timedelta(seconds=1),
        }
    )
    with pytest.raises(ValueError, match="frozen bridge closure"):
        loop_service._validate_material_controller_input_closure(
            plan,
            controller_input.bridge_plan,
            controller_input.phase_tool_profile,
            timestamp_replacement,
        )


def test_bridge_delivery_profiles_support_dual_and_reject_ambiguous_modes(
    tmp_path: Path,
) -> None:
    """Delivery scope allows GLB plus FBX while none and review-only stay exclusive."""

    dual, _ = _bridge_plan_fixture(
        tmp_path / "dual",
        requested_delivery_profiles=["portable_gltf", "portable_fbx"],
    )
    assert dual.requested_delivery_profiles == ["portable_gltf", "portable_fbx"]
    payload = dual.model_dump(mode="python")
    for invalid in (
        ["none", "portable_gltf"],
        ["review_only", "portable_fbx"],
        ["portable_gltf", "portable_gltf"],
    ):
        payload["requested_delivery_profiles"] = invalid
        with pytest.raises(
            ValidationError,
            match="delivery profile|delivery profiles|review_only",
        ):
            ImageGeneratedMaterialBridgePlan.model_validate(payload)


def test_promotion_receipt_requires_promoted_base_state_in_provenance(
    tmp_path: Path,
) -> None:
    """Promotion evidence cannot omit the exact AQ state that adopted MaterialPhaseReceiptV2."""

    receipt = _promotion_receipt_fixture(tmp_path)
    assert receipt.promoted_base_state in receipt.provenance
    payload = receipt.model_dump(mode="python")
    payload["provenance"] = [
        item
        for item in payload["provenance"]
        if item["path"] != receipt.promoted_base_state.path
    ]
    with pytest.raises(ValidationError, match="incomplete|extras"):
        ImageGeneratedMaterialPromotionReceipt.model_validate(payload)


def test_lifecycle_envelopes_recompute_their_input_digests(tmp_path: Path) -> None:
    """Plan, promotion, preview, and terminal reject stale envelope digests."""

    plan, _ = _bridge_plan_fixture(tmp_path / "plan")
    plan_payload = plan.model_dump(mode="python")
    plan_payload["input_sha256"] = SHA_A
    with pytest.raises(ValidationError, match="bridge plan input digest"):
        ImageGeneratedMaterialBridgePlan.model_validate(plan_payload)

    controller_input, _ = _controller_input_fixture(tmp_path / "binding")
    input_artifact = write_immutable_codex_image_model(
        tmp_path / "binding",
        tmp_path / "binding" / "contract_evidence" / "controller-input.json",
        controller_input,
        kind="material-controller-input",
    )
    request = _contract_artifact(tmp_path / "binding", "controller-request")
    binding_inputs = dict(controller_input.immutable_input_sha256)
    binding_inputs[input_artifact.path] = input_artifact.sha256
    binding_provenance = [
        controller_input.bridge_plan,
        input_artifact,
        request,
        controller_input.phase_tool_profile,
    ]
    binding = ImageGeneratedMaterialControllerBinding(
        contract_id="material-controller-binding-session-loop",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        input_sha256=stable_json_digest(
            {"request": request.sha256, "inputs": binding_inputs}
        ),
        source_fingerprint=request.sha256,
        producer="material-loop-binding-test",
        provenance=binding_provenance,
        created_at=NOW,
        bridge_plan=controller_input.bridge_plan,
        controller_input=input_artifact,
        controller_execution_request=request,
        phase_tool_profile=controller_input.phase_tool_profile,
        execution_id="execution-loop",
        immutable_input_sha256=binding_inputs,
        allowed_output_paths=controller_input.allowed_output_paths,
        expected_output_sha256=controller_input.expected_output_sha256,
        controller_request_sha256=request.sha256,
    )
    binding_payload = binding.model_dump(mode="python")
    binding_payload["input_sha256"] = SHA_A
    with pytest.raises(ValidationError, match="binding input digest"):
        ImageGeneratedMaterialControllerBinding.model_validate(binding_payload)

    promotion = _promotion_receipt_fixture(tmp_path / "promotion")
    promotion_payload = promotion.model_dump(mode="python")
    promotion_payload["input_sha256"] = SHA_A
    with pytest.raises(ValidationError, match="promotion receipt input digest"):
        ImageGeneratedMaterialPromotionReceipt.model_validate(promotion_payload)

    terminal_inputs = [
        _contract_artifact(tmp_path / "terminal", name)
        for name in ("bridge", "state", "base-state")
    ]
    terminal = CodexImageMaterialLoopTerminal(
        contract_id="material-loop-terminal-session-loop",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        input_sha256=stable_json_digest(
            {item.path: item.sha256 for item in terminal_inputs}
        ),
        source_fingerprint=terminal_inputs[1].sha256,
        producer="material-loop-terminal-test",
        provenance=terminal_inputs,
        created_at=NOW,
        bridge_plan=terminal_inputs[0],
        latest_state=terminal_inputs[1],
        base_state=terminal_inputs[2],
        status="failed",
        material_candidate_promoted=False,
    )
    terminal_payload = terminal.model_dump(mode="python")
    terminal_payload["input_sha256"] = SHA_A
    with pytest.raises(ValidationError, match="terminal input digest"):
        CodexImageMaterialLoopTerminal.model_validate(terminal_payload)


def test_all_material_loop_top_level_contracts_are_strict_v010() -> None:
    """Every additive top-level schema rejects extras and advertises version 0.1.0."""

    contracts = (
        ImageGeneratedMaterialBridgePlan,
        ImageGeneratedMaterialControllerInput,
        ImageGeneratedMaterialControllerBinding,
        ImageGeneratedMaterialPromotionReceipt,
        ImageGeneratedMaterialNeutralPreview,
        ImageGenNativeNormalizationPlan,
        ImageGenNativeNormalizationReceipt,
        CodexImageSemanticReview,
        CodexImageMaterialLoopTerminal,
        CodexImageMaterialLoopState,
    )
    for contract in contracts:
        schema = contract.model_json_schema()
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "0.1.0"


def test_relative_paths_and_unknown_fields_fail_closed() -> None:
    """Shared exact artifacts reject path escape while strict records reject extras."""

    with pytest.raises(ValidationError, match="path"):
        CodexImageArtifact(
            artifact_id="escaped",
            kind="test",
            path="../escaped.png",
            sha256=SHA_A,
            byte_size=1,
            media_type="image/png",
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CodexImageSemanticCheck(
            category="unwanted_text",
            outcome="passed",
            confidence=0.5,
            rationale="none observed",
            undeclared=True,
        )
    with pytest.raises(ValidationError, match="finite_number"):
        CodexImageSemanticCheck(
            category="unwanted_text",
            outcome="passed",
            confidence=float("nan"),
            rationale="none observed",
        )


def test_semantic_review_is_non_human_exact_and_revalidates(tmp_path: Path) -> None:
    """A complete review stays advisory, human-reviewed false, and exact-byte bound."""

    review = _review(tmp_path)

    assert review.outcome == "passed"
    assert review.human_reviewed is False
    assert review.observed_reference_truth is False
    assert semantic_review_gate(review) == "passed"
    validate_codex_image_semantic_review(
        tmp_path,
        review,
        expected_candidate_id="candidate-1",
        expected_job_id="job-loop",
        expected_workflow_id="workflow-loop",
        expected_dispatch_id="dispatch-loop",
        expected_session_id="session-loop",
        expected_reviewed_image_sha256=review.reviewed_image.sha256,
    )
    payload = review.model_dump(mode="json")
    payload["human_reviewed"] = True
    with pytest.raises(ValidationError, match="literal_error"):
        CodexImageSemanticReview.model_validate(payload)


@pytest.mark.parametrize(
    ("expected", "message"),
    [
        ({"expected_job_id": "other-job"}, "job identity"),
        ({"expected_workflow_id": "other-workflow"}, "workflow identity"),
        ({"expected_dispatch_id": "other-dispatch"}, "dispatch identity"),
        ({"expected_session_id": "other-session"}, "session identity"),
        ({"expected_candidate_id": "other-candidate"}, "candidate identity"),
    ],
)
def test_semantic_review_rejects_each_cross_identity_replay(
    tmp_path: Path,
    expected: dict[str, str],
    message: str,
) -> None:
    """Every job/workflow/dispatch/session/candidate identity is independently bound."""

    with pytest.raises(ValueError, match=message):
        validate_codex_image_semantic_review(tmp_path, _review(tmp_path), **expected)


def test_explicit_unwanted_text_can_fail_but_aesthetic_failure_cannot(
    tmp_path: Path,
) -> None:
    """Only explicit forbidden-content categories may produce an authoritative failure."""

    failed = _review(
        tmp_path,
        checks=_checks({"unwanted_text": ("failed", True)}),
    )
    assert failed.outcome == "failed"
    assert semantic_review_gate(failed) == "failed"

    with pytest.raises(ValidationError, match="cannot hard-fail"):
        CodexImageSemanticCheck(
            category="wood_grain_naturalness",
            outcome="failed",
            confidence=0.8,
            rationale="subjective mismatch",
            explicit_forbidden_content=True,
        )


def test_unavailable_semantics_require_review_and_never_invent_pass(tmp_path: Path) -> None:
    """Unavailable visual inspection remains an explicit review boundary."""

    unavailable = _review(
        tmp_path,
        checks=_checks(
            {category: ("unavailable", False) for category in ALL_SEMANTIC_REVIEW_CATEGORIES}
        ),
    )
    assert unavailable.outcome == "unavailable"
    assert semantic_review_gate(unavailable) == "review_required"
    assert semantic_review_gate(None) == "review_required"


@pytest.mark.parametrize(
    ("material_family", "category", "outcome", "explicit", "aggregate"),
    [
        (
            "wood",
            "wood_grain_naturalness",
            "review_required",
            False,
            "review_required",
        ),
        ("signage_decal", "signage_or_decal_suitability", "passed", False, "passed"),
        (
            "crystal",
            "crystal_or_energy_pattern_suitability",
            "passed",
            False,
            "passed",
        ),
        (
            "emissive",
            "unwanted_object_or_background",
            "failed",
            True,
            "failed",
        ),
    ],
)
def test_material_role_semantic_cases_remain_structured_and_bounded(
    tmp_path: Path,
    material_family: str,
    category: str,
    outcome: str,
    explicit: bool,
    aggregate: str,
) -> None:
    """Wood, decal, crystal, and unwanted-object observations keep declared semantics."""

    review = _review(
        tmp_path,
        material_family=material_family,
        checks=_checks({category: (outcome, explicit)}),
    )

    assert review.material_family == material_family
    assert review.outcome == aggregate
    assert review.human_reviewed is False


def test_candidate_precedence_applies_declared_gate_order(tmp_path: Path) -> None:
    """File and deterministic gates precede semantic, suitability, repair, and stable ID."""

    passed = _review(tmp_path)
    good = candidate_selection_precedence_key(
        file_hard_gate_passed=True,
        deterministic_quality_outcome="passed",
        semantic_review=passed,
        material_role_suitable=True,
        repair_cost=0.25,
        candidate_id="candidate-b",
    )
    bad_file = candidate_selection_precedence_key(
        file_hard_gate_passed=False,
        deterministic_quality_outcome="passed",
        semantic_review=passed,
        material_role_suitable=True,
        repair_cost=0.0,
        candidate_id="candidate-a",
    )
    bad_quality = candidate_selection_precedence_key(
        file_hard_gate_passed=True,
        deterministic_quality_outcome="failed",
        semantic_review=passed,
        material_role_suitable=True,
        repair_cost=0.0,
        candidate_id="candidate-a",
    )
    stable_a = candidate_selection_precedence_key(
        file_hard_gate_passed=True,
        deterministic_quality_outcome="passed",
        semantic_review=passed,
        material_role_suitable=True,
        repair_cost=0.25,
        candidate_id="candidate-a",
    )

    assert good < bad_file
    assert good < bad_quality
    assert stable_a < good
    with pytest.raises(ValueError, match="finite"):
        candidate_selection_precedence_key(
            file_hard_gate_passed=True,
            deterministic_quality_outcome="passed",
            semantic_review=passed,
            material_role_suitable=True,
            repair_cost=float("inf"),
            candidate_id="candidate-a",
        )


def test_semantic_review_rejects_stale_reviewed_image(tmp_path: Path) -> None:
    """Changing reviewed bytes after recording invalidates the semantic review."""

    review = _review(tmp_path)
    (tmp_path / review.reviewed_image.path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="(?:size|hash) changed"):
        validate_codex_image_semantic_review(tmp_path, review)


def test_neutral_preview_cross_binds_real_render_inputs_and_png(tmp_path: Path) -> None:
    """Neutral preview binds receipt, blend, renderer, manifest, and exact PNG metadata."""

    files = {
        "receipt": ("material_phase/receipt.json", b'{"promoted":true}\n', "application/json"),
        "blend": ("build/authoring.blend", b"BLENDER-v305", "application/x-blender"),
        "renderer": (
            "scripts/render_material_swatches.py",
            b"# fixed renderer\n",
            "text/x-python",
        ),
        "manifest": (
            "material_phase/neutral_preview_manifest.json",
            b'{"renderer":"fixed"}\n',
            "application/json",
        ),
    }
    artifacts: dict[str, CodexImageArtifact] = {}
    for name, (relative, payload, media_type) in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        artifacts[name] = artifact_for_codex_image(
            tmp_path,
            path,
            artifact_id=f"preview-{name}",
            kind=f"preview-{name}",
            media_type=media_type,
        )
    image_path = tmp_path / "material_phase" / "neutral_preview.png"
    Image.new("RGB", (96, 64), (42, 55, 68)).save(image_path)
    artifacts["image"] = artifact_for_codex_image(
        tmp_path,
        image_path,
        artifact_id="preview-image",
        kind="neutral-material-preview",
        media_type="image/png",
    )

    preview = ImageGeneratedMaterialNeutralPreview(
        contract_id="neutral-preview",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        input_sha256=stable_json_digest(
            {
                "material_phase_receipt": artifacts["receipt"].model_dump(
                    mode="json"
                ),
                "renderer_script": artifacts["renderer"].model_dump(mode="json"),
                "material_id": "material-main",
                "size": 96,
            }
        ),
        source_fingerprint=artifacts["receipt"].sha256,
        producer="fixed-material-preview-service",
        provenance=list(artifacts.values()),
        created_at=NOW,
        material_phase_receipt=artifacts["receipt"],
        authoring_blend=artifacts["blend"],
        renderer_script=artifacts["renderer"],
        raw_swatch_manifest=artifacts["manifest"],
        preview_image=artifacts["image"],
        material_id="material-main",
        width=96,
        height=64,
        preview_image_path=artifacts["image"].path,
        preview_image_sha256=artifacts["image"].sha256,
        preview_image_byte_size=artifacts["image"].byte_size,
    )

    assert preview.actual_blender_rendered is True
    assert preview.human_reviewed is False
    assert preview.reference_matched is False
    payload = preview.model_dump()
    stale_digest = dict(payload)
    stale_digest["input_sha256"] = SHA_A
    with pytest.raises(ValidationError, match="preview input digest"):
        ImageGeneratedMaterialNeutralPreview.model_validate(stale_digest)
    payload["preview_image_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="image binding"):
        ImageGeneratedMaterialNeutralPreview.model_validate(payload)


def test_material_loop_state_transition_is_append_only_and_monotonic(tmp_path: Path) -> None:
    """The companion journal advances once and never decreases its own budget usage."""

    bridge_path = tmp_path / "loop" / "bridge.json"
    bridge_path.parent.mkdir(parents=True, exist_ok=True)
    bridge_path.write_text('{"bridge":true}\n', encoding="utf-8")
    bridge = artifact_for_codex_image(
        tmp_path,
        bridge_path,
        artifact_id="bridge",
        kind="imagegen-material-bridge-plan",
        media_type="application/json",
    )
    controller_input = _contract_artifact(tmp_path, "state-controller-input")
    initial_budget = ImageMaterialLoopBudgetUsage(normalization_runs=1)
    initial = CodexImageMaterialLoopState(
        contract_id="loop-state-zero",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        input_sha256=material_loop_state_input_sha256(
            sequence=0,
            previous_state_sha256=None,
            status="controller_promotion_required",
            bridge_plan_sha256=bridge.sha256,
            controller_input_sha256=controller_input.sha256,
            promotion_receipt_sha256=None,
            material_phase_receipt_sha256=None,
            budget_usage=initial_budget,
        ),
        source_fingerprint=bridge.sha256,
        producer="material-loop-state-service",
        provenance=[bridge, controller_input],
        created_at=NOW,
        state_id="loop-state-zero",
        sequence=0,
        status="controller_promotion_required",
        bridge_plan=bridge,
        controller_input=controller_input,
        budget_usage=initial_budget,
    )
    initial_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path / "loop" / "state-000000.json",
        initial,
        kind="imagegen-material-loop-state",
    )
    current_budget = ImageMaterialLoopBudgetUsage(
        normalization_runs=1,
        controller_invocations=1,
    )
    current = CodexImageMaterialLoopState(
        contract_id="loop-state-one",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        input_sha256=material_loop_state_input_sha256(
            sequence=1,
            previous_state_sha256=initial_artifact.sha256,
            status="promoting_material",
            bridge_plan_sha256=bridge.sha256,
            controller_input_sha256=controller_input.sha256,
            promotion_receipt_sha256=None,
            material_phase_receipt_sha256=None,
            budget_usage=current_budget,
        ),
        source_fingerprint=bridge.sha256,
        producer="material-loop-state-service",
        provenance=[bridge, controller_input, initial_artifact],
        created_at=NOW,
        state_id="loop-state-one",
        sequence=1,
        previous_state=initial_artifact,
        previous_state_sha256=initial_artifact.sha256,
        status="promoting_material",
        bridge_plan=bridge,
        controller_input=controller_input,
        budget_usage=current_budget,
    )

    validate_material_loop_transition(initial, current)
    regressed = current.model_copy(
        update={
            "budget_usage": ImageMaterialLoopBudgetUsage(
                normalization_runs=0,
                controller_invocations=1,
            )
        }
    )
    with pytest.raises(ValueError, match="monotonic"):
        validate_material_loop_transition(initial, regressed)
    replaced_input = current.model_copy(
        update={"controller_input": _contract_artifact(tmp_path, "other-controller-input")}
    )
    with pytest.raises(ValueError, match="controller-input binding"):
        validate_material_loop_transition(initial, replaced_input)


def test_material_loop_post_promotion_terminals_preserve_exact_closure(
    tmp_path: Path,
) -> None:
    """Blocked/review/failure terminals keep promotion receipts and exact terminal evidence."""

    bridge = _contract_artifact(tmp_path, "state-bridge")
    controller_input = _contract_artifact(tmp_path, "state-controller-input")
    promotion = _contract_artifact(tmp_path, "state-promotion")
    material = _contract_artifact(tmp_path, "state-material-receipt")
    base_promoted = _contract_artifact(tmp_path, "state-base-promoted")
    blocker = _contract_artifact(tmp_path, "state-blocker")
    waiting_budget = ImageMaterialLoopBudgetUsage(
        normalization_runs=1,
        semantic_reviews=1,
        controller_invocations=1,
        promotions_consumed=1,
    )
    waiting = CodexImageMaterialLoopState(
        contract_id="state-waiting",
        state_id="state-waiting",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        input_sha256=material_loop_state_input_sha256(
            sequence=0,
            previous_state_sha256=None,
            status="controller_promotion_required",
            bridge_plan_sha256=bridge.sha256,
            controller_input_sha256=controller_input.sha256,
            promotion_receipt_sha256=None,
            material_phase_receipt_sha256=None,
            budget_usage=ImageMaterialLoopBudgetUsage(),
        ),
        source_fingerprint=bridge.sha256,
        producer="material-loop-state-test",
        provenance=[bridge, controller_input],
        created_at=NOW,
        sequence=0,
        status="controller_promotion_required",
        bridge_plan=bridge,
        controller_input=controller_input,
    )
    initial_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path / "contract_evidence" / "state-initial.json",
        waiting,
        kind="material-loop-state",
    )
    promoting = CodexImageMaterialLoopState(
        contract_id="state-promoting",
        state_id="state-promoting",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        input_sha256=material_loop_state_input_sha256(
            sequence=1,
            previous_state_sha256=initial_artifact.sha256,
            status="promoting_material",
            bridge_plan_sha256=bridge.sha256,
            controller_input_sha256=controller_input.sha256,
            promotion_receipt_sha256=None,
            material_phase_receipt_sha256=None,
            budget_usage=ImageMaterialLoopBudgetUsage(controller_invocations=1),
        ),
        source_fingerprint=bridge.sha256,
        producer="material-loop-state-test",
        provenance=[bridge, controller_input, initial_artifact],
        created_at=NOW,
        sequence=1,
        previous_state=initial_artifact,
        previous_state_sha256=initial_artifact.sha256,
        status="promoting_material",
        bridge_plan=bridge,
        controller_input=controller_input,
        budget_usage=ImageMaterialLoopBudgetUsage(controller_invocations=1),
    )
    promoting_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path / "contract_evidence" / "state-promoting.json",
        promoting,
        kind="material-loop-state",
    )
    promoted = CodexImageMaterialLoopState(
        contract_id="state-promoted",
        state_id="state-promoted",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        input_sha256=material_loop_state_input_sha256(
            sequence=2,
            previous_state_sha256=promoting_artifact.sha256,
            status="material_promoted",
            bridge_plan_sha256=bridge.sha256,
            controller_input_sha256=controller_input.sha256,
            promotion_receipt_sha256=promotion.sha256,
            material_phase_receipt_sha256=material.sha256,
            base_state_sha256=base_promoted.sha256,
            budget_usage=waiting_budget,
        ),
        source_fingerprint=bridge.sha256,
        producer="material-loop-state-test",
        provenance=[
            bridge,
            controller_input,
            promoting_artifact,
            promotion,
            material,
            base_promoted,
        ],
        created_at=NOW,
        sequence=2,
        previous_state=promoting_artifact,
        previous_state_sha256=promoting_artifact.sha256,
        status="material_promoted",
        bridge_plan=bridge,
        controller_input=controller_input,
        promotion_receipt=promotion,
        material_phase_receipt=material,
        base_state=base_promoted,
        budget_usage=waiting_budget,
        promotion_consumed_sha256=promotion.sha256,
    )
    promoted_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path / "contract_evidence" / "state-promoted.json",
        promoted,
        kind="material-loop-state",
    )
    base_blocked = _contract_artifact(tmp_path, "state-base-blocked")
    blocked = CodexImageMaterialLoopState(
        contract_id="state-blocked",
        state_id="state-blocked",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        input_sha256=material_loop_state_input_sha256(
            sequence=3,
            previous_state_sha256=promoted_artifact.sha256,
            status="blocked",
            bridge_plan_sha256=bridge.sha256,
            controller_input_sha256=controller_input.sha256,
            promotion_receipt_sha256=promotion.sha256,
            material_phase_receipt_sha256=material.sha256,
            base_state_sha256=base_blocked.sha256,
            failure_evidence_sha256=blocker.sha256,
            budget_usage=waiting_budget,
        ),
        source_fingerprint=bridge.sha256,
        producer="material-loop-state-test",
        provenance=[
            bridge,
            controller_input,
            promoted_artifact,
            promotion,
            material,
            base_blocked,
            blocker,
        ],
        created_at=NOW,
        sequence=3,
        previous_state=promoted_artifact,
        previous_state_sha256=promoted_artifact.sha256,
        status="blocked",
        bridge_plan=bridge,
        controller_input=controller_input,
        promotion_receipt=promotion,
        material_phase_receipt=material,
        base_state=base_blocked,
        failure_evidence=blocker,
        budget_usage=waiting_budget,
        promotion_consumed_sha256=promotion.sha256,
    )

    validate_material_loop_transition(promoting, promoted)
    validate_material_loop_transition(promoted, blocked)
    payload = blocked.model_dump(mode="python")
    payload["material_phase_receipt"] = None
    with pytest.raises(ValidationError, match="form one closure"):
        CodexImageMaterialLoopState.model_validate(payload)


def test_material_loop_state_digest_binds_failure_reason_and_budget_is_single_use(
    tmp_path: Path,
) -> None:
    """Changing a failure reason changes the digest and every companion operation caps at one."""

    budget = ImageMaterialLoopBudgetUsage(controller_invocations=1)
    first = material_loop_state_input_sha256(
        sequence=2,
        previous_state_sha256=SHA_A,
        status="failed",
        bridge_plan_sha256=SHA_A,
        controller_input_sha256=SHA_A,
        promotion_receipt_sha256=None,
        material_phase_receipt_sha256=None,
        failure_evidence_sha256=SHA_A,
        latest_failure="first reason",
        budget_usage=budget,
    )
    second = material_loop_state_input_sha256(
        sequence=2,
        previous_state_sha256=SHA_A,
        status="failed",
        bridge_plan_sha256=SHA_A,
        controller_input_sha256=SHA_A,
        promotion_receipt_sha256=None,
        material_phase_receipt_sha256=None,
        failure_evidence_sha256=SHA_A,
        latest_failure="second reason",
        budget_usage=budget,
    )
    assert first != second
    with pytest.raises(ValidationError, match="less_than_equal"):
        ImageMaterialLoopBudgetUsage(controller_invocations=2)
