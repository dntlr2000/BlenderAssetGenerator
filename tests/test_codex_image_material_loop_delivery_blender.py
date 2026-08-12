"""Opt-in Blender 5 review-boundary and export-mechanism material-loop E2E."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import test_codex_image_material_loop_blender as loop_fixtures
from PIL import Image, ImageDraw

import codex_blender_modeler.autonomy_v2.supervisor_service as supervisor_service
from codex_blender_modeler.autonomy_v2.codex_image_material_loop_service import (
    execute_codex_image_material_loop_controller,
    finalize_codex_image_material_loop_promotion,
    promote_codex_image_material_loop,
    publish_codex_image_material_loop_bridge,
    validate_codex_image_material_loop_terminal,
)
from codex_blender_modeler.autonomy_v2.codex_image_material_preview_service import (
    render_promoted_codex_image_material_preview,
    validate_promoted_codex_image_material_preview,
)
from codex_blender_modeler.autonomy_v2.controller_bridge import (
    _session_bundle,
    get_autonomy_v2_status,
)
from codex_blender_modeler.autonomy_v2.delivery_service import (
    artifact_for_v2,
    quality_source_fingerprint_v2,
    quality_submission_input_sha256_v2,
    validate_quality_source_freeze,
    validate_v2_artifact,
)
from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialControllerCompletionV2,
)
from codex_blender_modeler.autonomy_v2.material_phase_service import (
    validate_material_phase_receipt_v2,
)
from codex_blender_modeler.autonomy_v2.models import (
    AQV2Artifact,
    AutonomyProfileV2,
    AutonomyStateV2,
    DeliveryPlan,
    DeliveryReviewBinding,
    QualityApprovedSourceFreeze,
    RootAuthorizationV2,
)
from codex_blender_modeler.autonomy_v2.supervisor_service import (
    QualitySubmissionV2,
    advance_autonomy_v2,
)
from codex_blender_modeler.blender_artifacts import (
    native_io_path,
    sha256_file,
    stable_json_digest,
    write_json_atomic,
)
from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.codex_imagegen import CodexImageArtifact
from codex_blender_modeler.codex_imagegen.material_loop_models import (
    ImageGeneratedMaterialBridgePlan,
    ImageGeneratedMaterialControllerInput,
    ImageGeneratedMaterialPromotionReceipt,
)
from codex_blender_modeler.config import executable_exists, get_settings
from codex_blender_modeler.integrated_quality.v02_contour_metrics import (
    compare_contours_v02,
)
from codex_blender_modeler.integrated_quality.v02_models import (
    ContourEvidenceBindingV02,
    IntegratedQualityPolicyV02,
    MultiviewMetricV02,
    ProducerIdentityV02,
)
from codex_blender_modeler.integrated_quality.v02_service import (
    build_integrated_quality_report_v02,
)
from codex_blender_modeler.optimization.io import (
    job_relative,
    run_directory,
    utc_now,
    write_model,
)
from codex_blender_modeler.optimization.models import (
    OptimizationPlan,
    PortableMaterialConversionManifest,
)
from codex_blender_modeler.optimization.optimizer import (
    _asset_cost_report,
    _collision_manifest,
    _lod_manifest,
    _manifest_artifact,
    _uv_manifest,
)
from codex_blender_modeler.optimization.preflight import (
    load_asset_profile,
    profile_path,
)
from codex_blender_modeler.optimization.provenance import (
    collect_source_provenance,
)
from codex_blender_modeler.packaging.material_conversion import (
    convert_portable_materials as convert_portable_materials_real,
)
from codex_blender_modeler.packaging.service import package_asset
from codex_blender_modeler.production.controller_executor import FakeControllerForTests
from codex_blender_modeler.structural_geometry.geometry_delivery_inspector_v02 import (
    inspect_delivery_geometry_stage_v02,
)
from codex_blender_modeler.structural_geometry.geometry_survival_v02 import (
    GeometryIntentSurvivalReportV02,
    compare_geometry_stage_snapshots_v02,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_DELIVERY_BLENDER_E2E") != "1",
    reason=(
        "set CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_DELIVERY_BLENDER_E2E=1 "
        "for the real Blender review-boundary and export-mechanism E2E"
    ),
)


@dataclass(frozen=True)
class _PromotedLoopFixture:
    """Carry one real promoted fake-raster loop into IQ and delivery checks."""

    geometry: Any
    promotion: ImageGeneratedMaterialPromotionReceipt
    promotion_artifact: CodexImageArtifact
    quality_state: AutonomyStateV2


@dataclass(frozen=True)
class _PassedQualityFixture:
    """Carry one exact passed IQ submission and its immutable source freeze."""

    promoted: _PromotedLoopFixture
    submission: QualitySubmissionV2
    freeze: QualityApprovedSourceFreeze
    freeze_artifact: AQV2Artifact


@dataclass(frozen=True)
class _MechanismDeliveryEvidence:
    """Carry unapproved test-only export evidence that production cannot adopt."""

    public_profile: str
    asset_profile: str
    mechanism_run_id: str
    primary_asset: Path
    export_evidence: dict[str, Any]
    roundtrip_evidence: dict[str, Any]
    material_conversion: PortableMaterialConversionManifest
    geometry_survival: GeometryIntentSurvivalReportV02


def _aq_artifact(artifact: CodexImageArtifact) -> AQV2Artifact:
    """Project one exact companion artifact into the AQ v2 evidence shape."""

    return AQV2Artifact(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )


def _write_json(path: Path, payload: object) -> Path:
    """Write one deterministic contained JSON fixture and return its path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)
    return path


def _artifact(root: Path, path: Path, artifact_id: str, kind: str) -> AQV2Artifact:
    """Bind one existing contained file as exact AQ v2 evidence."""

    return artifact_for_v2(
        root,
        path,
        artifact_id=artifact_id,
        kind=kind,
    )


def _promote_fake_material_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    requested_delivery_profiles: list[str],
    case: Any | None = None,
    use_actual_source: bool = False,
) -> _PromotedLoopFixture:
    """Run one bounded fake or historical ImageGen source through real promotion."""

    if not use_actual_source:
        for variable in (
            "CBM_CODEX_IMAGEGEN_ACTUAL_SOURCE_PATH",
            "CBM_CODEX_IMAGEGEN_ACTUAL_SOURCE_SHA256",
            "CBM_CODEX_IMAGEGEN_ACTUAL_PROMPT_SHA256",
        ):
            monkeypatch.delenv(variable, raising=False)
    original_planner = loop_fixtures.plan_autonomous_static_prop_v2

    def plan_with_delivery_profiles(*args: object, **kwargs: object) -> dict[str, object]:
        """Replace only the fixture's requested delivery profile list before planning."""

        kwargs["requested_delivery_profiles"] = list(requested_delivery_profiles)
        return original_planner(*args, **kwargs)

    monkeypatch.setattr(
        loop_fixtures,
        "plan_autonomous_static_prop_v2",
        plan_with_delivery_profiles,
    )
    def advance_reference_through_host(
        job_id: str,
        session_id: str,
        *,
        quality_submission: QualitySubmissionV2 | dict[str, object] | None = None,
        allow_disabled_experimental: bool = False,
    ) -> dict[str, object]:
        """Use the real V0.9 host action so downstream state keeps its receipt."""

        result = advance_autonomy_v2(
            job_id,
            session_id,
            quality_submission=quality_submission,
            allow_disabled_experimental=True,
        )
        assert result["advanced"] is True
        assert result["outcome"] == "reference_ready"
        root, _session_root, _plan, _budget, _state, _artifact = _session_bundle(
            job_id,
            session_id,
        )
        session_root = root / "production" / "autonomy_v2" / session_id
        authorization = RootAuthorizationV2.model_validate_json(
            (session_root / "root_authorization.json").read_bytes()
        )
        reference_path = authorization.primary_reference.path
        reference_sha256 = sha256_file(root / reference_path)
        loop_fixtures.geometry_fixtures._write_json(
            root / "analysis" / "reference_analysis.json",
            loop_fixtures.geometry_fixtures._reference_analysis(
                root.name,
                reference_path,
                reference_sha256,
            ),
        )
        loop_fixtures.geometry_fixtures._write_json(
            root / "analysis" / "camera_solution.json",
            loop_fixtures.geometry_fixtures._camera_solution(root.name),
        )
        loop_fixtures.geometry_fixtures._write_json(
            root / "analysis" / "modeling_plan.json",
            loop_fixtures.geometry_fixtures._modeling_plan(root.name, "baseline"),
        )
        return result

    monkeypatch.setattr(
        supervisor_service,
        "advance_autonomy_v2",
        advance_reference_through_host,
    )
    fixture = loop_fixtures._geometry_material_boundary(tmp_path, monkeypatch)
    case = case or loop_fixtures._MATERIAL_CASES[0]
    created_at = datetime.now(UTC)
    baseline = loop_fixtures._publish_material_baseline(fixture)
    image = loop_fixtures._fake_imagegen_selection(
        fixture,
        case,
        created_at=created_at,
    )
    assert image.fake_source_used is (not use_actual_source)
    assert image.actual_builtin_source_used is use_actual_source
    normalization, semantic = loop_fixtures._normalization_and_semantic_review(
        fixture,
        image,
        case,
        created_at=created_at + timedelta(seconds=10),
    )
    authoring, _authoring_artifact, generation_terminal, adoption = (
        loop_fixtures._author_material_v021(
            fixture,
            image,
            case,
            baseline,
            normalization,
            created_at=created_at + timedelta(seconds=20),
        )
    )
    base_bridge = loop_fixtures._publish_v05_bridge_plan(
        fixture,
        image,
        case,
        authoring,
        generation_terminal,
        adoption,
        normalization,
        semantic,
        created_at=created_at + timedelta(seconds=30),
    )
    authored_provenance = [
        artifact
        for artifact in base_bridge.provenance
        if artifact != base_bridge.exact_adoption_preflight
    ]
    bridge_plan = ImageGeneratedMaterialBridgePlan.model_validate(
        {
            **base_bridge.model_dump(mode="python"),
            "input_sha256": stable_json_digest(
                {artifact.path: artifact.sha256 for artifact in authored_provenance}
            ),
            "provenance": authored_provenance,
            "requested_delivery_profiles": requested_delivery_profiles,
            "execution_mode": "controller_authored_completion",
            "exact_adoption_preflight": None,
        }
    )
    assert bridge_plan.execution_mode == "controller_authored_completion"
    assert bridge_plan.expected_output_sha256 == base_bridge.expected_output_sha256
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
    outputs = {Path(item).name: item for item in bridge_plan.allowed_output_paths}
    plan_bytes = (fixture.root / bridge_plan.candidate_material_plan.path).read_bytes()
    graph_bytes = (fixture.root / bridge_plan.material_graph_spec.path).read_bytes()
    source_material_plan_sha256 = controller_input.source_material_plan_sha256
    assert source_material_plan_sha256 is not None
    completion = MaterialControllerCompletionV2(
        completion_id=f"{case.slug}-delivery-material-completion",
        job_id=fixture.plan.job_id,
        workflow_id=fixture.plan.workflow_id,
        dispatch_id=fixture.plan.dispatch_id,
        session_id=fixture.session_id,
        execution_id=f"exec-{fixture.state.sequence + 1:04d}-material_authoring",
        assignment_sha256=controller_input_artifact.sha256,
        tool_profile_sha256=controller_input.phase_tool_profile.sha256,
        immutable_input_sha256=controller_input.immutable_input_sha256,
        source_scene_spec_sha256=bridge_plan.canonical_scene_spec_sha256,
        source_material_plan_sha256=source_material_plan_sha256,
        material_plan_path=outputs["material_plan.json"],
        material_plan_sha256=hashlib.sha256(plan_bytes).hexdigest(),
        material_graph_path=outputs["material_graph.json"],
        material_graph_sha256=hashlib.sha256(graph_bytes).hexdigest(),
    )
    executed = execute_codex_image_material_loop_controller(
        fixture.plan.job_id,
        fixture.session_id,
        controller=FakeControllerForTests(
            payloads={
                "material_plan.json": plan_bytes,
                "material_graph.json": graph_bytes,
                "completion.json": loop_fixtures.geometry_fixtures._json_bytes(completion),
            }
        ),
        timeout_seconds=60,
        allow_disabled_experimental=True,
    )
    assert executed["controller_status"] == "completed"
    result_state = AutonomyStateV2.model_validate_json(json.dumps(executed["state"]))
    result_artifact = result_state.provenance[-1]
    root, _session_root, plan, budget, state, _state_artifact = _session_bundle(
        fixture.plan.job_id,
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
    assert validate_material_phase_receipt_v2(
        root,
        receipt_artifact,
        require_current=True,
    ) == receipt
    preview, preview_artifact = render_promoted_codex_image_material_preview(
        root,
        material_phase_receipt=loop_fixtures.artifact_for_codex_image(
            root,
            root / receipt_artifact.path,
            artifact_id=receipt.contract_id,
            kind="material-phase-receipt",
            media_type="application/json",
        ),
        preview_id=f"{case.slug}-delivery-neutral-preview",
        material_id=loop_fixtures._MATERIAL_ID,
        size=64,
        created_at=created_at + timedelta(seconds=40),
    )
    assert preview.actual_blender_rendered is True
    assert preview.human_reviewed is False
    finalized = finalize_codex_image_material_loop_promotion(
        root,
        material_phase_receipt_artifact=receipt_artifact,
        neutral_preview_artifact=preview_artifact,
        created_at=created_at + timedelta(seconds=41),
    )
    promotion_artifact = CodexImageArtifact.model_validate(
        finalized["promotion_receipt_artifact"]
    )
    promotion = ImageGeneratedMaterialPromotionReceipt.model_validate_json(
        json.dumps(finalized["promotion_receipt"])
    )
    status = get_autonomy_v2_status(fixture.plan.job_id, fixture.session_id)
    quality_state = AutonomyStateV2.model_validate_json(json.dumps(status["state"]))
    assert (quality_state.phase, quality_state.status, quality_state.next_action) == (
        "quality",
        "running",
        "run_integrated_quality",
    )
    assert quality_state.provenance[-1] == _aq_artifact(
        promotion.material_phase_receipt
    ).model_copy(
        update={"kind": "material_phase_receipt"}
    )
    return _PromotedLoopFixture(
        geometry=fixture,
        promotion=promotion,
        promotion_artifact=promotion_artifact,
        quality_state=quality_state,
    )


def _source_artifacts(
    promoted: _PromotedLoopFixture,
) -> tuple[
    AQV2Artifact,
    AQV2Artifact,
    AQV2Artifact,
    AQV2Artifact,
    list[AQV2Artifact],
    list[AQV2Artifact],
    list[AQV2Artifact],
    AQV2Artifact,
    AQV2Artifact,
]:
    """Resolve exact current canonical and promotion artifacts for passed IQ."""

    root = promoted.geometry.root
    state = promoted.quality_state
    material_receipt_artifact = state.provenance[-1]
    material_receipt = validate_material_phase_receipt_v2(
        root,
        material_receipt_artifact,
        require_current=True,
    )
    source = collect_source_provenance(root, promoted.geometry.plan.job_id)
    assert source.scene_spec is not None
    assert source.material_plan is not None
    build_payload = json.loads(
        (root / material_receipt.build_provenance_snapshot.path).read_text(
            encoding="utf-8"
        )
    )
    material_records = build_payload.get("materials")
    assert isinstance(material_records, dict)
    shader_paths = sorted(
        {
            str(record["shader_recipe_path"])
            for record in material_records.values()
            if isinstance(record, dict) and record.get("shader_recipe_path")
        }
    )
    shader_recipes = [
        _artifact(root, root / path, f"delivery-shader-{index:02d}", "shader_recipe")
        for index, path in enumerate(shader_paths, start=1)
    ]
    texture_manifests = [
        _artifact(
            root,
            root / item.path,
            f"delivery-texture-{index:02d}",
            "texture_manifest",
        )
        for index, item in enumerate(source.texture_manifests, start=1)
    ]
    geometry_payloads = [
        _artifact(
            root,
            root / item.path,
            f"delivery-geometry-{index:02d}",
            "geometry_payload",
        )
        for index, item in enumerate(source.geometry_payloads, start=1)
    ]
    canonical_blend = _artifact(
        root,
        root / source.blend.path,
        "material-loop-canonical-blend",
        "blend",
    )
    canonical_material = _artifact(
        root,
        root / source.material_plan.path,
        "material-loop-canonical-material-plan",
        "material_plan",
    )
    assert canonical_blend.sha256 == material_receipt.authoring_blend_snapshot.sha256
    assert canonical_material.sha256 == material_receipt.canonical_material_plan_sha256
    return (
        promoted.geometry.receipt.canonical_scene_spec,
        canonical_blend,
        material_receipt.build_provenance_snapshot,
        canonical_material,
        shader_recipes,
        texture_manifests,
        geometry_payloads,
        promoted.geometry.receipt.geometry_intent_survival,
        material_receipt_artifact,
    )


def _build_passed_quality_submission(
    promoted: _PromotedLoopFixture,
) -> QualitySubmissionV2:
    """Build one host-recomputable passed IQ report with the full companion chain."""

    root = promoted.geometry.root
    plan = promoted.geometry.plan
    (
        scene,
        blend,
        build,
        material,
        shader_recipes,
        texture_manifests,
        geometry_payloads,
        survival,
        material_receipt,
    ) = _source_artifacts(promoted)
    preview = validate_promoted_codex_image_material_preview(
        root,
        promoted.promotion.neutral_preview,
        require_current=True,
    )
    camera = _artifact(
        root,
        root / "analysis" / "camera_solution.json",
        "material-loop-delivery-camera",
        "camera",
    )
    evidence_root = root / "reports" / "codex_image_material_loop_delivery"
    mask = Image.new("L", (48, 48), 0)
    ImageDraw.Draw(mask).rounded_rectangle((10, 12, 37, 35), radius=3, fill=255)
    reference_path = evidence_root / "reference_mask.png"
    candidate_path = evidence_root / "candidate_mask.png"
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(reference_path, format="PNG")
    mask.save(candidate_path, format="PNG")
    reference = _artifact(root, reference_path, "material-loop-reference-mask", "reference_mask")
    candidate = _artifact(root, candidate_path, "material-loop-candidate-mask", "candidate_mask")
    legacy_path = _write_json(
        evidence_root / "legacy_v06_report.json",
        {"schema_version": "0.6.0", "direct_score": 0.98, "status": "passed"},
    )
    legacy = _artifact(root, legacy_path, "material-loop-legacy-v06", "visual_qa_report")
    contour = compare_contours_v02(
        mask,
        mask,
        reference_evidence=ContourEvidenceBindingV02(
            evidence_id="material-loop.reference.contour",
            origin="observed",
            authority="authoritative",
            artifact_path=reference.path,
            artifact_sha256=reference.sha256,
            camera_sha256=camera.sha256,
        ),
        candidate_evidence_id="material-loop.candidate.contour",
        candidate_artifact_sha256=candidate.sha256,
        candidate_camera_sha256=camera.sha256,
    )
    policy = IntegratedQualityPolicyV02.model_validate_json(
        (root / promoted.geometry.authorization.quality_profile.path).read_bytes()
    )
    assert policy.profile_id == "autonomous_static_prop_v2"
    companion = [
        promoted.promotion_artifact,
        promoted.promotion.generated_image_evidence,
        promoted.promotion.semantic_review,
        promoted.promotion.normalization_receipt,
        promoted.promotion.adoption,
        promoted.promotion.material_authoring_manifest,
        promoted.promotion.material_authoring_receipt,
        promoted.promotion.graph_compile_report,
        promoted.promotion.material_validation,
        promoted.promotion.neutral_preview,
        preview.renderer_script,
        preview.raw_swatch_manifest,
        promoted.promotion.neutral_preview_image,
    ]
    quality_evidence = [
        camera,
        reference,
        candidate,
        legacy,
        *[_aq_artifact(item) for item in companion],
    ]
    quality_source = quality_source_fingerprint_v2(root, plan.job_id)
    quality_input = quality_submission_input_sha256_v2(
        source_fingerprint=quality_source,
        camera_artifact=camera,
        quality_evidence=quality_evidence,
        scene_spec=scene,
        authoring_blend=blend,
        build_provenance=build,
        material_plan=material,
        shader_recipes=shader_recipes,
        texture_manifests=texture_manifests,
        geometry_payloads=geometry_payloads,
        geometry_intent_survival=survival,
        geometry_candidate_validation_receipt=promoted.geometry.receipt_artifact,
        material_phase_receipt=material_receipt,
    )
    report = build_integrated_quality_report_v02(
        report_id=f"iq-material-loop-delivery-{plan.session_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        source_fingerprint=quality_source,
        camera_sha256=camera.sha256,
        input_sha256=quality_input,
        legacy_v06_report_sha256=legacy.sha256,
        legacy_v06_direct_score=0.98,
        policy=policy,
        contour=contour,
        semantics=[],
        landmarks=[],
        multiview=MultiviewMetricV02(
            metric_id="material-loop.multiview.unavailable",
            status="unscorable",
            observations=[],
            authoritative_view_count=0,
            limitations=["Optional multiview evidence is outside this bounded fixture."],
        ),
        advisory_metrics=[],
        producer=ProducerIdentityV02(
            name="pytest_codex_image_material_loop_delivery",
            version="0.2.0",
        ),
        created_at=datetime.now(UTC),
    )
    assert report.outcome == "passed"
    assert report.quality_accepted is True
    report_path = _write_json(
        evidence_root / "integrated_quality_v02.json",
        report.model_dump(mode="json"),
    )
    report_artifact = _artifact(
        root,
        report_path,
        report.report_id,
        "integrated_quality_report",
    )
    return QualitySubmissionV2(
        integrated_quality_report=report_artifact,
        quality_evidence=quality_evidence,
        camera_artifact=camera,
        scene_spec=scene,
        authoring_blend=blend,
        build_provenance=build,
        material_plan=material,
        shader_recipes=shader_recipes,
        texture_manifests=texture_manifests,
        geometry_payloads=geometry_payloads,
        geometry_intent_survival=survival,
    )


def _advance_passed_quality(promoted: _PromotedLoopFixture) -> _PassedQualityFixture:
    """Advance one real material loop through passed IQ and validate its source freeze."""

    submission = _build_passed_quality_submission(promoted)
    plan = promoted.geometry.plan
    result = advance_autonomy_v2(
        plan.job_id,
        plan.session_id,
        quality_submission=submission,
        allow_disabled_experimental=True,
    )
    assert result["advanced"] is True
    assert result["outcome"] == "passed"
    assert (
        result["codex_image_material_loop"]["terminal"]["status"]
        == "quality_approved"
    )
    freeze_artifact = AQV2Artifact.model_validate(result["source_freeze"])
    freeze = QualityApprovedSourceFreeze.model_validate_json(
        validate_v2_artifact(promoted.geometry.root, freeze_artifact).read_bytes()
    )
    validate_quality_source_freeze(promoted.geometry.root, freeze)
    terminal_payload = result["codex_image_material_loop"]["terminal_artifact"]
    terminal_artifact = CodexImageArtifact.model_validate(terminal_payload)
    companion_terminal = validate_codex_image_material_loop_terminal(
        promoted.geometry.root,
        terminal_artifact,
        require_current=True,
    )
    assert companion_terminal.status == "quality_approved"
    assert companion_terminal.quality_passed is True
    assert companion_terminal.packages_completed is False
    return _PassedQualityFixture(
        promoted=promoted,
        submission=submission,
        freeze=freeze,
        freeze_artifact=freeze_artifact,
    )


def _load_bound_model(root: Path, artifact: AQV2Artifact, model: type[Any]) -> Any:
    """Rehash and parse one exact result model through its declared artifact binding."""

    validated_path = validate_v2_artifact(root, artifact)
    return model.model_validate_json(Path(native_io_path(validated_path)).read_bytes())


def _bounded_material_conversion(
    job_id: str,
    *,
    profile_id: str,
    run_id: str,
    conversion_id: str,
) -> PortableMaterialConversionManifest:
    """Run the real converter with a bounded 128-pixel texture budget for E2E."""

    return convert_portable_materials_real(
        job_id,
        profile_id=profile_id,
        run_id=run_id,
        conversion_id=conversion_id,
        resolution=128,
        margin_px=8,
        render_device="cpu",
    )


def _read_json_object_native(path: Path) -> dict[str, Any]:
    """Read one JSON object through the native Windows long-path spelling."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _prepare_unapproved_mechanism_optimization(
    *,
    root: Path,
    reviewed_plan: OptimizationPlan,
    mechanism_run_id: str,
) -> OptimizationPlan:
    """Prepare derived Blender inputs without publishing any authorization evidence.

    This test-only run exercises the fixed Blender optimizer and normalizers. Its
    lifecycle timestamps satisfy the strict OptimizationPlan shape, but the run has
    no review, user approval, or policy authorization and must remain unacceptable to
    production packaging validators.
    """

    run_root = run_directory(root, mechanism_run_id, create=True)
    source_preflight = root / reviewed_plan.preflight_report.path
    target_preflight = run_root / "mesh_preflight_report.json"
    shutil.copy2(native_io_path(source_preflight), native_io_path(target_preflight))
    preflight_artifact = reviewed_plan.preflight_report.model_copy(
        update={"path": job_relative(root, target_preflight)}
    )
    started_at = utc_now()
    running = reviewed_plan.model_copy(
        update={
            "plan_id": f"pytest-mechanism.{mechanism_run_id}",
            "preflight_report": preflight_artifact,
            "status": "running",
            "approved_at": started_at,
            "notes": [
                *reviewed_plan.notes,
                "PYTEST MECHANISM ONLY: no user or policy authorization exists, and "
                "production package validation must reject this run.",
            ],
        }
    )
    running = OptimizationPlan.model_validate(running.model_dump(mode="json"))
    execution_plan_path = run_root / "execution_plan.json"
    write_model(execution_plan_path, running)
    write_model(run_root / "optimization_plan.json", running)
    profile = load_asset_profile(root, running.profile_id)
    optimized_blend = run_root / "optimized" / "scene.blend"
    raw_evidence_path = run_root / "optimized_asset_evidence.json"
    run_blender(
        "prepare_optimized_asset.py",
        [
            "--plan",
            str(execution_plan_path),
            "--profile",
            str(profile_path(root, running.profile_id)),
            "--output-blend",
            str(optimized_blend),
            "--output-manifest",
            str(raw_evidence_path),
        ],
        blend_file=root / "blender" / "scene.blend",
    )
    raw = _read_json_object_native(raw_evidence_path)
    assert raw["ok"] is True
    assert raw["source"]["build_fingerprint"] == running.source.build_fingerprint
    cost = _asset_cost_report(mechanism_run_id, profile, running.source, raw)
    assert cost.ok is True
    lod = _lod_manifest(
        root,
        mechanism_run_id,
        profile,
        running.source,
        raw,
        optimized_blend,
    )
    collision = _collision_manifest(
        root,
        mechanism_run_id,
        profile,
        running.source,
        raw,
        optimized_blend,
    )
    uv = _uv_manifest(mechanism_run_id, profile, running.source, raw)
    manifest_paths = {
        "lod": run_root / "lod_manifest.json",
        "collision": run_root / "collision_manifest.json",
        "uv": run_root / "uv_manifest.json",
        "cost": run_root / "asset_cost_report.json",
    }
    for path, model in (
        (manifest_paths["lod"], lod),
        (manifest_paths["collision"], collision),
        (manifest_paths["uv"], uv),
        (manifest_paths["cost"], cost),
    ):
        write_model(path, model)
    output_kinds = {
        "lod": "lod_manifest",
        "collision": "collision_manifest",
        "uv": "uv_manifest",
        "cost": "asset_cost_report",
    }
    outputs = [
        _manifest_artifact(
            root,
            f"pytest.mechanism.{name}.{mechanism_run_id}",
            output_kinds[name],
            path,
        )
        for name, path in manifest_paths.items()
    ]
    outputs.extend(
        [
            _manifest_artifact(
                root,
                f"pytest.mechanism.execution.{mechanism_run_id}",
                "optimization_plan",
                execution_plan_path,
            ),
            _manifest_artifact(
                root,
                f"pytest.mechanism.blend.{mechanism_run_id}",
                "blend",
                optimized_blend,
            ),
            _manifest_artifact(
                root,
                f"pytest.mechanism.evidence.{mechanism_run_id}",
                "other",
                raw_evidence_path,
            ),
        ]
    )
    complete = running.model_copy(
        update={
            "status": "complete",
            "completed_at": utc_now(),
            "output_manifests": outputs,
        }
    )
    complete = OptimizationPlan.model_validate(complete.model_dump(mode="json"))
    write_model(run_root / "optimization_plan.json", complete)
    assert not (run_root / "optimization_approval.json").exists()
    assert not (run_root / "optimization_policy_authorization.json").exists()
    assert not (run_root / "optimization_review.json").exists()
    return complete


def _run_unapproved_delivery_mechanism(
    *,
    promoted: _PromotedLoopFixture,
    review_entry: Any,
    case: Any,
) -> _MechanismDeliveryEvidence:
    """Exercise real GLB/FBX export and clean import outside production acceptance."""

    root = promoted.geometry.root
    public_profile = review_entry.profile_id
    asset_profile = review_entry.asset_profile_id
    suffix = "gltf" if public_profile == "portable_gltf" else "fbx"
    mechanism_run_id = f"pytest-mechanism-{case.slug}-{suffix}"
    reviewed_plan = _load_bound_model(
        root,
        review_entry.optimization_plan,
        OptimizationPlan,
    )
    complete = _prepare_unapproved_mechanism_optimization(
        root=root,
        reviewed_plan=reviewed_plan,
        mechanism_run_id=mechanism_run_id,
    )
    assert complete.source.source_fingerprint == reviewed_plan.source.source_fingerprint
    conversion_id = f"pytest-mechanism-{case.slug}-{suffix}-materials"
    material_conversion = _bounded_material_conversion(
        promoted.geometry.plan.job_id,
        profile_id=asset_profile,
        run_id=mechanism_run_id,
        conversion_id=conversion_id,
    )
    assert material_conversion.status == "complete"
    assert material_conversion.missing_material_ids == []
    rejected_package_id = f"pytest-must-reject-{case.slug}-{suffix}"
    with pytest.raises(
        RuntimeError,
        match="Optimization review and approval evidence is incomplete",
    ):
        package_asset(
            promoted.geometry.plan.job_id,
            profile_id=asset_profile,
            run_id=mechanism_run_id,
            package_id=rejected_package_id,
            material_conversion_id=conversion_id,
        )
    assert not (
        root / "exports" / "packages" / asset_profile / rejected_package_id
    ).exists()

    profile = load_asset_profile(root, asset_profile)
    package_root = (
        root
        / "reports"
        / "pytest_mechanism_delivery"
        / case.slug
        / public_profile
    )
    package_root.mkdir(parents=True, exist_ok=False)
    primary_asset = package_root / (
        "model.fbx" if profile.primary_format == "fbx" else "asset.glb"
    )
    export_evidence_path = package_root / "export_evidence.json"
    portable_blend = root / material_conversion.portable_blend.path
    conversion_plan_path = root / material_conversion.plan_artifact.path
    execution_plan_path = (
        root / "optimization" / "runs" / mechanism_run_id / "execution_plan.json"
    )
    export_args = [
        "--format",
        profile.primary_format,
        "--output",
        str(primary_asset),
        "--manifest",
        str(export_evidence_path),
        "--package-root",
        str(package_root),
        "--expected-plan-sha256",
        sha256_file(execution_plan_path),
        "--expected-input-blend-sha256",
        sha256_file(portable_blend),
        "--expected-material-conversion-plan-sha256",
        sha256_file(conversion_plan_path),
    ]
    if profile.collision.strategy != "none":
        export_args.append("--include-colliders")
    run_blender(
        "export_portable_package.py",
        export_args,
        blend_file=portable_blend,
    )
    export_evidence = _read_json_object_native(export_evidence_path)
    assert export_evidence["kind"] == "portable_export_evidence"
    assert export_evidence["format"] == profile.primary_format
    assert export_evidence["ok"] is True
    assert export_evidence["runtime"]["blender_version"] == "5.0.1"
    assert not (package_root / "package_manifest.json").exists()

    roundtrip_evidence_path = package_root / "roundtrip_evidence.json"
    run_blender(
        "validate_export_roundtrip.py",
        [
            "--format",
            profile.primary_format,
            "--input",
            str(primary_asset),
            "--expected",
            str(export_evidence_path),
            "--output",
            str(roundtrip_evidence_path),
            "--package-root",
            str(package_root),
            "--bounds-tolerance",
            "0.0001",
        ],
        factory_startup=True,
    )
    roundtrip_evidence = _read_json_object_native(roundtrip_evidence_path)
    assert roundtrip_evidence["kind"] == "roundtrip_validation"
    assert roundtrip_evidence["ok"] is True
    assert roundtrip_evidence["runtime"]["blender_version"] == "5.0.1"

    geometry_root = (
        root / "optimization" / "runs" / mechanism_run_id / "pytest_geometry"
    )
    optimized_snapshot = inspect_delivery_geometry_stage_v02(
        job_root=root,
        artifact_relative_path=material_conversion.portable_blend.path,
        stage="optimized_lod0",
        output_relative_path=(
            geometry_root / "optimized_lod0_snapshot.json"
        ).relative_to(root).as_posix(),
        source_fingerprint_sha256=complete.source.source_fingerprint,
        build_fingerprint_sha256=complete.source.build_fingerprint,
    )
    target_stage = (
        "clean_import_glb" if public_profile == "portable_gltf" else "clean_import_fbx"
    )
    imported_snapshot = inspect_delivery_geometry_stage_v02(
        job_root=root,
        artifact_relative_path=primary_asset.relative_to(root).as_posix(),
        stage=target_stage,
        output_relative_path=(
            geometry_root / f"{target_stage}_snapshot.json"
        ).relative_to(root).as_posix(),
        source_fingerprint_sha256=complete.source.source_fingerprint,
        build_fingerprint_sha256=complete.source.build_fingerprint,
    )
    survival = compare_geometry_stage_snapshots_v02(
        report_id=f"pytest-mechanism-{case.slug}-{suffix}-survival",
        relation="optimized_to_clean_import",
        source=optimized_snapshot,
        target=imported_snapshot,
        package_format="GLB" if public_profile == "portable_gltf" else "FBX",
    )
    assert survival.overall_status in {"exact", "equivalent", "known_loss"}
    assert all(item.status != "failed" for item in survival.checks)
    return _MechanismDeliveryEvidence(
        public_profile=public_profile,
        asset_profile=asset_profile,
        mechanism_run_id=mechanism_run_id,
        primary_asset=primary_asset,
        export_evidence=export_evidence,
        roundtrip_evidence=roundtrip_evidence,
        material_conversion=material_conversion,
        geometry_survival=survival,
    )


def test_review_only_material_loop_finishes_without_portable_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finish the real material loop through a host-owned review-only terminal."""

    settings = get_settings()
    if not executable_exists(settings.blender_bin):
        pytest.skip(f"Blender executable not found: {settings.blender_bin}")
    promoted = _promote_fake_material_loop(
        tmp_path,
        monkeypatch,
        requested_delivery_profiles=["review_only"],
    )
    passed = _advance_passed_quality(promoted)
    plan = promoted.geometry.plan
    planned = advance_autonomy_v2(
        plan.job_id,
        plan.session_id,
        allow_disabled_experimental=True,
    )
    assert planned["advanced"] is True
    assert planned["outcome"] == "delivery_pending"
    assert planned["delivery_review"] is None
    delivery = advance_autonomy_v2(
        plan.job_id,
        plan.session_id,
        allow_disabled_experimental=True,
    )
    assert delivery["advanced"] is True
    assert delivery["outcome"] == "review_only"
    result = delivery["delivery_results"][0]
    assert result["status"] == "review_only"
    assert result["production_ready"] is False
    assert result["package_manifest"] is None
    assert result["roundtrip_validation"] is None
    assert passed.freeze.session_id == plan.session_id
    session_root = (
        promoted.geometry.root / "production" / "autonomy_v2" / plan.session_id
    )
    assert not (session_root / "delivery_reviews.json").exists()
    assert not list((promoted.geometry.root / "optimization").glob("runs/*"))
    profile = AutonomyProfileV2.model_validate_json(
        (promoted.geometry.root / plan.profile.path).read_bytes()
    )
    assert profile.status == "disabled_experimental"


_DUAL_DELIVERY_CASES = [
    *((case, False) for case in loop_fixtures._MATERIAL_CASES),
    (loop_fixtures._MATERIAL_CASES[0], True),
]


@pytest.mark.parametrize(
    ("case", "use_actual_source"),
    _DUAL_DELIVERY_CASES,
    ids=[
        *(f"fake-{case.family}" for case in loop_fixtures._MATERIAL_CASES),
        "actual-wood",
    ],
)
def test_dual_review_boundary_and_unapproved_blender_export_mechanisms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: Any,
    use_actual_source: bool,
) -> None:
    """Stop at exact review, then probe GLB/FBX mechanisms without authorization."""

    settings = get_settings()
    if not executable_exists(settings.blender_bin):
        pytest.skip(f"Blender executable not found: {settings.blender_bin}")
    if use_actual_source and not os.environ.get("CBM_CODEX_IMAGEGEN_ACTUAL_SOURCE_PATH"):
        pytest.skip("historical actual-source delivery requires its exact source path")
    if use_actual_source:
        with pytest.raises(
            PermissionError,
            match="semantic material review is not passed",
        ):
            _promote_fake_material_loop(
                tmp_path,
                monkeypatch,
                requested_delivery_profiles=["portable_gltf", "portable_fbx"],
                case=case,
                use_actual_source=True,
            )
        root = tmp_path / "w" / loop_fixtures._JOB_ID
        assert not list(root.glob("optimization/runs/*/optimization_approval.json"))
        assert not list(root.glob("packages/**/package_manifest.json"))
        assert not list(root.glob("production/autonomy_v2/**/delivery_terminal.json"))
        return
    promoted = _promote_fake_material_loop(
        tmp_path,
        monkeypatch,
        requested_delivery_profiles=["portable_gltf", "portable_fbx"],
        case=case,
        use_actual_source=use_actual_source,
    )
    passed = _advance_passed_quality(promoted)
    plan = promoted.geometry.plan
    planned = advance_autonomy_v2(
        plan.job_id,
        plan.session_id,
        allow_disabled_experimental=True,
    )
    delivery_plan_artifact = AQV2Artifact.model_validate(planned["delivery_plan"])
    delivery_review_artifact = AQV2Artifact.model_validate(planned["delivery_review"])
    delivery_plan = _load_bound_model(
        promoted.geometry.root,
        delivery_plan_artifact,
        DeliveryPlan,
    )
    delivery_review = _load_bound_model(
        promoted.geometry.root,
        delivery_review_artifact,
        DeliveryReviewBinding,
    )
    assert delivery_plan.direct_cross_format_conversion is False
    assert [item.profile.profile_id for item in delivery_plan.requests] == [
        "portable_gltf",
        "portable_fbx",
    ]
    assert len({item.run_id for item in delivery_plan.requests}) == 2
    assert len({item.package_id for item in delivery_plan.requests}) == 2
    assert promoted.geometry.authorization.synthetic_user_approval is False
    for entry in delivery_review.entries:
        reviewed_plan = _load_bound_model(
            promoted.geometry.root,
            entry.optimization_plan,
            OptimizationPlan,
        )
        formal_run_root = (
            promoted.geometry.root / "optimization" / "runs" / entry.run_id
        )
        assert reviewed_plan.status == "draft"
        assert entry.exact_plan_sha256 == entry.optimization_plan.sha256
        assert reviewed_plan.source.source_fingerprint == passed.freeze.v07_source_fingerprint
        assert not (formal_run_root / "optimization_approval.json").exists()
        assert not (
            formal_run_root / "optimization_policy_authorization.json"
        ).exists()
        request = next(
            item
            for item in delivery_plan.requests
            if item.delivery_id == entry.delivery_id
        )
        assert request.package_id is not None
        assert request.profile.asset_profile_id is not None
        assert not (
            promoted.geometry.root
            / "exports"
            / "packages"
            / request.profile.asset_profile_id
            / request.package_id
        ).exists()
    waiting = advance_autonomy_v2(
        plan.job_id,
        plan.session_id,
        allow_disabled_experimental=True,
    )
    assert waiting["advanced"] is False
    assert waiting["outcome"] == "waiting_for_v07_approval"
    assert waiting["next_action"] == "approve_exact_v07_plans"
    canonical_hashes = {
        path: sha256_file(path)
        for path in (
            promoted.geometry.root / "analysis" / "scene_spec.json",
            promoted.geometry.root / "analysis" / "material_plan.json",
            promoted.geometry.root / "blender" / "scene.blend",
        )
    }
    mechanisms = [
        _run_unapproved_delivery_mechanism(
            promoted=promoted,
            review_entry=entry,
            case=case,
        )
        for entry in delivery_review.entries
    ]
    assert [item.public_profile for item in mechanisms] == [
        "portable_gltf",
        "portable_fbx",
    ]
    assert len({item.mechanism_run_id for item in mechanisms}) == 2
    assert len({item.primary_asset for item in mechanisms}) == 2
    assert all(item.primary_asset.is_file() for item in mechanisms)
    assert all(item.roundtrip_evidence["ok"] is True for item in mechanisms)
    assert all(
        item.material_conversion.missing_material_ids == [] for item in mechanisms
    )
    assert all(
        item.geometry_survival.overall_status
        in {"exact", "equivalent", "known_loss"}
        for item in mechanisms
    )
    assert {path: sha256_file(path) for path in canonical_hashes} == canonical_hashes
    still_waiting = advance_autonomy_v2(
        plan.job_id,
        plan.session_id,
        allow_disabled_experimental=True,
    )
    assert still_waiting["advanced"] is False
    assert still_waiting["outcome"] == "waiting_for_v07_approval"
    assert not list(
        (promoted.geometry.root / "exports" / "packages").rglob(
            "package_manifest.json"
        )
    )
    assert not (
        promoted.geometry.root
        / "production"
        / "autonomy_v2"
        / plan.session_id
        / "delivery_terminal.json"
    ).exists()
    assert {path: sha256_file(path) for path in canonical_hashes} == canonical_hashes
    profile = AutonomyProfileV2.model_validate_json(
        (promoted.geometry.root / plan.profile.path).read_bytes()
    )
    assert profile.status == "disabled_experimental"
