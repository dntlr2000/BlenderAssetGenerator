"""AQ v2 quality-freeze and independent-delivery host-service tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler.autonomy_v2.delivery_service import (
    artifact_for_v2,
    create_delivery_plan,
    publish_delivery_terminal,
    publish_quality_source_freeze,
    quality_submission_input_sha256_v2,
    validate_delivery_terminal_v2,
    validate_host_recomputed_quality_report_v2,
    validate_quality_source_freeze,
    write_immutable_v2_model,
)
from codex_blender_modeler.autonomy_v2.models import (
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyProfileV2,
    DeliveryResult,
    QualityApprovedSourceFreeze,
    QualityTerminalV2,
    RootAuthorizationV2,
)
from codex_blender_modeler.autonomy_v2.quality_terminal_service import (
    publish_quality_terminal_v2,
)
from codex_blender_modeler.blender_artifacts import stable_json_digest
from codex_blender_modeler.integrated_quality.v02_contour_metrics import (
    compare_contours_v02,
)
from codex_blender_modeler.integrated_quality.v02_models import (
    ContourEvidenceBindingV02,
    ContourMetricsV02,
    IntegratedQualityPolicyV02,
    MultiviewMetricV02,
    ProducerIdentityV02,
    SemanticEvidenceBindingV02,
)
from codex_blender_modeler.integrated_quality.v02_semantic_metrics import (
    compare_semantic_masks_v02,
)
from codex_blender_modeler.integrated_quality.v02_service import (
    build_integrated_quality_report_v02,
)

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def _file_artifact(root: Path, name: str, kind: str):
    """Write and bind one deterministic non-empty source fixture."""

    path = root / "fixtures" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{{"name":"{name}"}}\n', encoding="utf-8")
    return artifact_for_v2(root, path, artifact_id=name, kind=kind)


def _freeze_and_authorization(
    root: Path,
    *,
    requested_delivery_profiles: list[str] | None = None,
    expires_at: datetime | None = None,
) -> tuple[QualityApprovedSourceFreeze, Path, Path]:
    """Publish a receipt-bearing freeze plus exact host plan/profile/budget authority."""

    job_id = "aq_v2_delivery"
    workflow_id = "wf-aq-v2-delivery"
    dispatch_id = "dispatch-aq-v2-delivery"
    session_id = "aq-v2-delivery"
    deliveries = requested_delivery_profiles or ["portable_gltf", "portable_fbx"]
    session_root = root / "production" / "autonomy_v2" / session_id
    primary = _file_artifact(root, "primary-reference", "reference")
    dispatch = _file_artifact(root, "dispatch-plan", "production_dispatch_plan")
    controller = _file_artifact(root, "controller-plan", "production_controller_plan")
    launch = _file_artifact(root, "launch", "production_launch")
    tool_profile = _file_artifact(root, "tool-profile", "phase_tool_profile")
    policy = IntegratedQualityPolicyV02(profile_id="quality.static-prop-v02")
    policy_artifact = write_immutable_v2_model(
        root,
        session_root / "integrated_quality_policy.json",
        policy,
    )
    budget_input = {
        "dispatch_plan": dispatch.sha256,
        "quality_policy": policy_artifact.sha256,
        "phase_profiles": [tool_profile.sha256],
    }
    budget_model = AutonomyBudgetV2(
        contract_id=f"budget-{session_id}",
        budget_id=f"budget-{session_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(budget_input),
        source_fingerprint=stable_json_digest(
            {**budget_input, "profile": "autonomous_static_prop_v2"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[dispatch, policy_artifact, tool_profile],
        created_at=NOW,
        delivery_runs=sum(item != "review_only" for item in deliveries),
    )
    budget = write_immutable_v2_model(root, session_root / "budget.json", budget_model)
    profile_input = {
        "budget": budget.sha256,
        "quality_policy": policy_artifact.sha256,
        "phase_profiles": [tool_profile.sha256],
    }
    profile_model = AutonomyProfileV2(
        contract_id=f"profile-{session_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(profile_input),
        source_fingerprint=stable_json_digest(
            {**profile_input, "status": "disabled_experimental"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[budget, policy_artifact, tool_profile],
        created_at=NOW,
        status="disabled_experimental",
        allowed_asset_kinds=["static_hard_surface", "static_prop"],
        allowed_delivery_profiles=["review_only", "portable_gltf", "portable_fbx"],
        prohibited_capabilities=["interior", "measured", "rig", "animation"],
    )
    profile = write_immutable_v2_model(root, session_root / "profile.json", profile_model)
    authorization_inputs = {
        "request": "c" * 64,
        "primary_reference": primary.sha256,
        "profile": profile.sha256,
        "budget": budget.sha256,
        "launch": launch.sha256,
        "quality_policy": policy_artifact.sha256,
        "phase_profiles": [tool_profile.sha256],
        "requested_deliveries": deliveries,
        "target_subject": "test asset",
    }
    root_authorization = RootAuthorizationV2(
        contract_id=f"authorization-{session_id}",
        authorization_id=f"authorization-{session_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(authorization_inputs),
        source_fingerprint=stable_json_digest(
            {**authorization_inputs, "destination_hint": "engine_neutral"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[primary, profile, budget, launch, policy_artifact, tool_profile],
        created_at=NOW,
        original_request_sha256="c" * 64,
        primary_reference=primary,
        profile=profile,
        budget=budget,
        production_launch_or_binding=launch,
        target_subject="test asset",
        quality_profile=policy_artifact,
        phase_tool_profiles=[tool_profile],
        allowed_delivery_profiles=["review_only", "portable_gltf", "portable_fbx"],
        requested_delivery_profiles=deliveries,  # type: ignore[arg-type]
        prohibited_scopes=["interior", "measured", "rig", "animation"],
        expires_at=expires_at,
    )
    root_artifact = write_immutable_v2_model(
        root,
        session_root / "root_authorization.json",
        root_authorization,
    )
    plan_inputs = {
        "profile": profile.sha256,
        "authorization": root_artifact.sha256,
        "budget": budget.sha256,
        "dispatch": dispatch.sha256,
        "controller": controller.sha256,
        "phase_profiles": [tool_profile.sha256],
    }
    autonomy_plan = AutonomyPlanV2(
        contract_id=f"plan-{session_id}",
        plan_id=f"plan-{session_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(plan_inputs),
        source_fingerprint=stable_json_digest(
            {**plan_inputs, "requested_deliveries": deliveries}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[
            profile,
            root_artifact,
            budget,
            dispatch,
            controller,
            tool_profile,
        ],
        created_at=NOW,
        profile=profile,
        root_authorization=root_artifact,
        budget=budget,
        production_dispatch_plan=dispatch,
        production_controller_plan=controller,
        phase_tool_profiles=[tool_profile],
        requested_delivery_profiles=deliveries,  # type: ignore[arg-type]
        action_limit=budget_model.global_action_limit,
    )
    write_immutable_v2_model(root, session_root / "plan.json", autonomy_plan)

    scene = _file_artifact(root, "scene-spec", "scene_spec")
    blend = _file_artifact(root, "authoring-blend", "blend")
    build = _file_artifact(root, "build-provenance", "build_provenance")
    quality_input = _file_artifact(root, "quality-input", "quality_evidence")
    quality_report = build_integrated_quality_report_v02(
        report_id="iq-v02-delivery-fixture",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        source_fingerprint="f" * 64,
        camera_sha256=quality_input.sha256,
        input_sha256="e" * 64,
        policy=policy,
        contour=ContourMetricsV02(
            metric_id="reference.contour-v02",
            status="scored",
            authority="authoritative",
            evidence_ids=["reference.contour", "candidate.contour"],
            reference_mask_sha256=quality_input.sha256,
            candidate_mask_sha256=quality_input.sha256,
            camera_sha256=quality_input.sha256,
            width=32,
            height=32,
            reference_boundary_pixels=20,
            candidate_boundary_pixels=20,
            boundary_tolerance_px=0.25,
            boundary_tolerance_diagonal_fraction=0.005,
            boundary_precision=0.95,
            boundary_recall=0.95,
            boundary_f_score=0.95,
            edge_distance_transform_chamfer_norm=0.01,
        ),
        semantics=[],
        landmarks=[],
        multiview=MultiviewMetricV02(
            metric_id="multiview.unavailable",
            status="unscorable",
            observations=[],
            authoritative_view_count=0,
            limitations=["optional multiview evidence was not supplied"],
        ),
        advisory_metrics=[],
        producer=ProducerIdentityV02(
            name="cbm_integrated_quality_v02",
            version="0.2.0",
        ),
        created_at=NOW,
    )
    quality_path = root / "fixtures" / "quality-report.json"
    quality_path.write_text(
        quality_report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    quality = artifact_for_v2(
        root,
        quality_path,
        artifact_id=quality_report.report_id,
        kind="integrated_quality_report",
    )
    material = _file_artifact(root, "material-plan", "material_plan")
    shader = _file_artifact(root, "shader-recipe", "shader_recipe")
    texture = _file_artifact(root, "texture-manifest", "texture_manifest")
    geometry = _file_artifact(root, "mesh-payload", "geometry_payload")
    survival = _file_artifact(root, "intent-survival", "geometry_survival")
    geometry_receipt = _file_artifact(
        root,
        "geometry-validation-receipt",
        "geometry_candidate_validation_receipt",
    )
    material_receipt = _file_artifact(
        root,
        "material-phase-receipt",
        "material_phase_receipt",
    )
    frozen = {
        "scene_spec": scene.sha256,
        "authoring_blend": blend.sha256,
        "build_provenance": build.sha256,
        "integrated_quality_report": quality.sha256,
        "quality_evidence": [quality_input.sha256],
        "material_plan": material.sha256,
        "shader_recipes": [shader.sha256],
        "texture_manifests": [texture.sha256],
        "geometry_payloads": [geometry.sha256],
        "geometry_intent_survival": survival.sha256,
        "geometry_candidate_validation_receipt": geometry_receipt.sha256,
        "material_phase_receipt": material_receipt.sha256,
        "quality_source_fingerprint": quality_report.source_fingerprint,
        "quality_input_sha256": quality_report.input_sha256,
        "v07_source_fingerprint": "f" * 64,
    }
    provenance = [
        scene,
        blend,
        build,
        quality,
        quality_input,
        material,
        shader,
        texture,
        geometry,
        survival,
        geometry_receipt,
        material_receipt,
    ]
    freeze = QualityApprovedSourceFreeze(
        contract_id="quality-freeze-aq-v2-delivery",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(
            {
                "quality_report": quality.sha256,
                "quality_input": quality_report.input_sha256,
                "camera": quality_report.camera_sha256,
            }
        ),
        source_fingerprint=stable_json_digest(frozen),
        producer="codex_blender_modeler.autonomy_v2.delivery_service",
        provenance=provenance,
        created_at=NOW,
        freeze_id="quality-freeze-aq-v2-delivery",
        scene_spec=scene,
        authoring_blend=blend,
        build_provenance=build,
        integrated_quality_report=quality,
        quality_evidence=[quality_input],
        material_plan=material,
        shader_recipes=[shader],
        texture_manifests=[texture],
        geometry_payloads=[geometry],
        geometry_intent_survival=survival,
        geometry_candidate_validation_receipt=geometry_receipt,
        material_phase_receipt=material_receipt,
        v07_source_fingerprint="f" * 64,
        frozen_source_sha256=stable_json_digest(frozen),
    )
    freeze_path = session_root / "source_freeze.json"
    freeze_artifact = write_immutable_v2_model(root, freeze_path, freeze)
    return freeze, root / root_artifact.path, root / freeze_artifact.path


def test_delivery_plan_is_disabled_publicly_but_testable_in_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled v2 cannot run publicly while the isolated contract path remains testable."""

    root = tmp_path / "job"
    root.mkdir()
    _, root_path, freeze_path = _freeze_and_authorization(root)
    root_artifact = artifact_for_v2(
        root,
        root_path,
        artifact_id="authorization-aq-v2-delivery",
        kind="root-authorization",
    )
    freeze_artifact = artifact_for_v2(
        root,
        freeze_path,
        artifact_id="quality-freeze-aq-v2-delivery",
        kind="source-freeze",
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.collect_source_provenance",
        lambda _root, _job: SimpleNamespace(source_fingerprint="f" * 64),
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.validate_quality_source_freeze",
        lambda _root, _freeze: None,
    )

    with pytest.raises(PermissionError, match="disabled_experimental"):
        create_delivery_plan(
            job_root=root,
            root_authorization_artifact=root_artifact,
            source_freeze_artifact=freeze_artifact,
            plan_id="delivery-plan-disabled",
        )

    plan, plan_artifact = create_delivery_plan(
        job_root=root,
        root_authorization_artifact=root_artifact,
        source_freeze_artifact=freeze_artifact,
        plan_id="delivery-plan-isolated",
        allow_disabled_experimental=True,
        created_at=NOW,
    )
    assert [item.profile.profile_id for item in plan.requests] == [
        "portable_gltf",
        "portable_fbx",
    ]
    assert len({item.run_id for item in plan.requests}) == 2
    assert len({item.package_id for item in plan.requests}) == 2
    assert plan.generic_authorization_replaces_v07_approval is False
    assert (root / plan_artifact.path).is_file()


def test_direct_delivery_plan_rejects_expired_root_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an expired authorization before a direct delivery service writes a plan."""

    root = tmp_path / "expired"
    root.mkdir()
    _, root_path, freeze_path = _freeze_and_authorization(
        root,
        expires_at=NOW - timedelta(seconds=1),
    )
    root_artifact = artifact_for_v2(
        root,
        root_path,
        artifact_id="authorization-aq-v2-delivery",
        kind="root-authorization",
    )
    freeze_artifact = artifact_for_v2(
        root,
        freeze_path,
        artifact_id="quality-freeze-aq-v2-delivery",
        kind="source-freeze",
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.validate_quality_source_freeze",
        lambda _root, _freeze: None,
    )
    with pytest.raises(PermissionError, match="expired"):
        create_delivery_plan(
            job_root=root,
            root_authorization_artifact=root_artifact,
            source_freeze_artifact=freeze_artifact,
            plan_id="delivery-plan-expired",
            allow_disabled_experimental=True,
        )


def test_direct_delivery_plan_rejects_tampered_root_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject changed root-authorization bytes before any direct delivery side effect."""

    root = tmp_path / "tampered"
    root.mkdir()
    _, root_path, freeze_path = _freeze_and_authorization(root)
    root_artifact = artifact_for_v2(
        root,
        root_path,
        artifact_id="authorization-aq-v2-delivery",
        kind="root-authorization",
    )
    freeze_artifact = artifact_for_v2(
        root,
        freeze_path,
        artifact_id="quality-freeze-aq-v2-delivery",
        kind="source-freeze",
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.validate_quality_source_freeze",
        lambda _root, _freeze: None,
    )
    root_path.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="size changed|hash changed"):
        create_delivery_plan(
            job_root=root,
            root_authorization_artifact=root_artifact,
            source_freeze_artifact=freeze_artifact,
            plan_id="delivery-plan-tampered",
            allow_disabled_experimental=True,
        )


def test_review_only_terminal_rejects_forgery_then_binds_valid_quality_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a forged quality terminal before publishing a valid review-only delivery."""

    root = tmp_path / "aq_v2_delivery"
    root.mkdir()
    freeze, root_path, freeze_path = _freeze_and_authorization(
        root,
        requested_delivery_profiles=["review_only"],
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.collect_source_provenance",
        lambda _root, _job: SimpleNamespace(source_fingerprint="f" * 64),
    )
    root_artifact = artifact_for_v2(
        root,
        root_path,
        artifact_id="authorization-aq-v2-delivery",
        kind="root-authorization",
    )
    freeze_artifact = artifact_for_v2(
        root,
        freeze_path,
        artifact_id="quality-freeze-aq-v2-delivery",
        kind="source-freeze",
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.validate_quality_source_freeze",
        lambda _root, _freeze: None,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.quality_terminal_service.validate_quality_source_freeze",
        lambda _root, _freeze: None,
    )
    plan, plan_artifact = create_delivery_plan(
        job_root=root,
        root_authorization_artifact=root_artifact,
        source_freeze_artifact=freeze_artifact,
        plan_id="delivery-plan-review-only",
        allow_disabled_experimental=True,
        created_at=NOW,
    )
    quality_terminal = QualityTerminalV2(
        contract_id="quality-terminal-review-only",
        terminal_id="quality-terminal-review-only",
        job_id=freeze.job_id,
        workflow_id=freeze.workflow_id,
        dispatch_id=freeze.dispatch_id,
        session_id=freeze.session_id,
        input_sha256=stable_json_digest({"freeze": freeze_artifact.sha256}),
        source_fingerprint=stable_json_digest(
            {"freeze": freeze.frozen_source_sha256, "status": "quality_approved"}
        ),
        producer="tests.autonomy_v2.delivery",
        provenance=[freeze_artifact, freeze.integrated_quality_report],
        created_at=NOW,
        status="quality_approved",
        integrated_quality_report=freeze.integrated_quality_report,
        source_freeze=freeze_artifact,
        reason="quality evidence passed before review-only delivery",
    )
    forged_terminal_artifact = write_immutable_v2_model(
        root,
        root / "production" / "autonomy_v2" / freeze.session_id / "forged_quality_terminal.json",
        quality_terminal,
    )
    result = DeliveryResult(
        delivery_id=plan.requests[0].delivery_id,
        profile_id="review_only",
        status="review_only",
        source_freeze_sha256=freeze_artifact.sha256,
        production_ready=False,
    )
    with pytest.raises(ValueError, match="host publisher|publisher path"):
        publish_delivery_terminal(
            job_root=root,
            quality_terminal_artifact=forged_terminal_artifact,
            delivery_plan_artifact=plan_artifact,
            delivery_review_artifact=None,
            results=[result],
            created_at=NOW,
        )

    _quality_terminal, quality_terminal_artifact = publish_quality_terminal_v2(
        job_root=root,
        session_id=freeze.session_id,
        status="quality_approved",
        integrated_quality_report=freeze.integrated_quality_report,
        source_freeze=freeze_artifact,
        reason="Exact IQ 0.2 evidence passed before review-only delivery.",
        created_at=NOW,
    )
    terminal, terminal_artifact = publish_delivery_terminal(
        job_root=root,
        quality_terminal_artifact=quality_terminal_artifact,
        delivery_plan_artifact=plan_artifact,
        delivery_review_artifact=None,
        results=[result],
        created_at=NOW,
    )
    assert terminal.outcome == "review_only"
    assert terminal.delivery_review is None
    assert terminal.results == [result]
    assert (root / terminal_artifact.path).is_file()
    assert validate_delivery_terminal_v2(root, terminal_artifact) == terminal

    wrong_profile = result.model_copy(update={"profile_id": "portable_gltf"})
    with pytest.raises(ValueError, match="planned profile"):
        publish_delivery_terminal(
            job_root=root,
            quality_terminal_artifact=quality_terminal_artifact,
            delivery_plan_artifact=plan_artifact,
            delivery_review_artifact=None,
            results=[wrong_profile],
            created_at=NOW,
        )

    quality_terminal_path = root / quality_terminal_artifact.path
    quality_terminal_path.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="size changed|hash changed"):
        validate_delivery_terminal_v2(root, terminal_artifact)


def test_source_freeze_detects_artifact_and_canonical_supersession(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Freeze validation rejects both direct evidence tamper and newer canonical provenance."""

    root = tmp_path / "job"
    root.mkdir()
    freeze, _, _ = _freeze_and_authorization(root)
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.collect_source_provenance",
        lambda _root, _job: SimpleNamespace(source_fingerprint="f" * 64),
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.validate_host_recomputed_quality_report_v2",
        lambda **_kwargs: _kwargs["report"],
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.validate_quality_source_inputs_v2",
        lambda **_kwargs: "f" * 64,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.validate_quality_promotion_evidence_v2",
        lambda **_kwargs: (SimpleNamespace(), SimpleNamespace()),
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.quality_submission_input_sha256_v2",
        lambda **_kwargs: "e" * 64,
    )
    validate_quality_source_freeze(root, freeze)

    (root / freeze.scene_spec.path).write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="size changed|hash changed"):
        validate_quality_source_freeze(root, freeze)

    (root / freeze.scene_spec.path).write_text('{"name":"scene-spec"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.collect_source_provenance",
        lambda _root, _job: SimpleNamespace(source_fingerprint="e" * 64),
    )
    with pytest.raises(ValueError, match="canonical source changed"):
        validate_quality_source_freeze(root, freeze)


def test_host_recomputed_iq_rejects_self_consistent_forged_high_scores(
    tmp_path: Path,
) -> None:
    """Recompute exact mask bytes so forged contour and semantic pass scores are rejected."""

    root = tmp_path / "iq-recompute"
    root.mkdir()
    camera = _file_artifact(root, "recompute-camera", "camera")
    registration = _file_artifact(
        root,
        "recompute-registration",
        "registration_receipt",
    )
    reference_image = Image.new("L", (32, 32), 0)
    candidate_image = Image.new("L", (32, 32), 0)
    ImageDraw.Draw(reference_image).rectangle((5, 8, 18, 23), fill=255)
    ImageDraw.Draw(candidate_image).rectangle((14, 8, 27, 23), fill=255)
    reference_path = root / "quality" / "reference.png"
    candidate_path = root / "quality" / "candidate.png"
    reference_path.parent.mkdir()
    reference_image.save(reference_path)
    candidate_image.save(candidate_path)
    reference = artifact_for_v2(
        root,
        reference_path,
        artifact_id="recompute-reference",
        kind="reference_mask",
    )
    candidate = artifact_for_v2(
        root,
        candidate_path,
        artifact_id="recompute-candidate",
        kind="candidate_mask",
    )
    contour = compare_contours_v02(
        reference_path,
        candidate_path,
        reference_evidence=ContourEvidenceBindingV02(
            evidence_id="reference.contour",
            origin="observed",
            authority="authoritative",
            artifact_path=reference.path,
            artifact_sha256=reference.sha256,
            camera_sha256=camera.sha256,
        ),
        candidate_evidence_id="candidate.contour",
        candidate_artifact_sha256=candidate.sha256,
        candidate_camera_sha256=camera.sha256,
    )
    semantic = compare_semantic_masks_v02(
        reference_path,
        candidate_path,
        reference_evidence=SemanticEvidenceBindingV02(
            evidence_id="reference.semantic.body",
            semantic_id="asset.body",
            origin="registered_observed",
            authority="authoritative",
            artifact_path=reference.path,
            artifact_sha256=reference.sha256,
            camera_sha256=camera.sha256,
            registration_receipt_sha256=registration.sha256,
        ),
        candidate_evidence_id="candidate.semantic.body",
        candidate_artifact_sha256=candidate.sha256,
        candidate_camera_sha256=camera.sha256,
        critical=True,
    )
    policy = IntegratedQualityPolicyV02(
        profile_id="quality.static-prop-v02",
        critical_semantic_ids=["asset.body"],
    )
    base_arguments = {
        "report_id": "iq-v02-host-recompute",
        "job_id": "aq_v2_delivery",
        "workflow_id": "wf-aq-v2-delivery",
        "dispatch_id": "dispatch-aq-v2-delivery",
        "source_fingerprint": "a" * 64,
        "camera_sha256": camera.sha256,
        "input_sha256": "b" * 64,
        "policy": policy,
        "landmarks": [],
        "multiview": MultiviewMetricV02(
            metric_id="multiview.unavailable",
            status="unscorable",
            observations=[],
            authoritative_view_count=0,
            limitations=["optional multiview evidence was not supplied"],
        ),
        "advisory_metrics": [],
        "producer": ProducerIdentityV02(
            name="cbm_integrated_quality_v02",
            version="0.2.0",
        ),
        "created_at": NOW,
    }
    genuine = build_integrated_quality_report_v02(
        **base_arguments,
        contour=contour,
        semantics=[semantic],
    )
    assert genuine.outcome == "blocked"
    evidence = [camera, reference, candidate, registration]
    assert (
        validate_host_recomputed_quality_report_v2(
            job_root=root,
            report=genuine,
            quality_evidence=evidence,
            camera_artifact=camera,
            expected_policy=policy,
        )
        == genuine
    )

    forged_contour = contour.model_copy(
        update={
            "boundary_precision": 1.0,
            "boundary_recall": 1.0,
            "boundary_f_score": 1.0,
            "edge_distance_transform_chamfer_norm": 0.0,
        }
    )
    forged_semantic = semantic.model_copy(
        update={
            "mask_iou": 1.0,
            "missing_candidate": False,
            "contour": semantic.contour.model_copy(
                update={
                    "boundary_precision": 1.0,
                    "boundary_recall": 1.0,
                    "boundary_f_score": 1.0,
                    "edge_distance_transform_chamfer_norm": 0.0,
                }
            ),
        }
    )
    forged = build_integrated_quality_report_v02(
        **base_arguments,
        contour=forged_contour,
        semantics=[forged_semantic],
    )
    assert forged.outcome == "passed"
    with pytest.raises(ValueError, match="host-recomputed"):
        validate_host_recomputed_quality_report_v2(
            job_root=root,
            report=forged,
            quality_evidence=evidence,
            camera_artifact=camera,
            expected_policy=policy,
        )


def test_quality_source_freeze_requires_exact_passed_iq_v02(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a rehashed, hard-gate-passed IQ 0.2 report can freeze canonical sources."""

    root = tmp_path / "job"
    root.mkdir()
    scene = _file_artifact(root, "canonical-scene", "scene_spec")
    blend = _file_artifact(root, "canonical-blend", "blend")
    build = _file_artifact(root, "canonical-build", "build_provenance")
    material = _file_artifact(root, "canonical-material", "material_plan")
    shader = _file_artifact(root, "canonical-shader", "shader_recipe")
    texture = _file_artifact(root, "canonical-texture", "texture_manifest")
    geometry = _file_artifact(root, "canonical-geometry", "geometry_payload")
    survival = _file_artifact(root, "canonical-survival", "geometry_survival")
    camera = _file_artifact(root, "quality-camera", "camera")
    registration = _file_artifact(root, "mask-registration", "registration_receipt")
    legacy = _file_artifact(root, "legacy-v06-report", "visual_qa_report")

    mask_root = root / "quality-fixtures"
    mask_root.mkdir()
    reference_path = mask_root / "reference.png"
    candidate_path = mask_root / "candidate.png"
    image = Image.new("L", (32, 32), 0)
    ImageDraw.Draw(image).rectangle((8, 8, 23, 23), fill=255)
    image.save(reference_path)
    image.save(candidate_path)
    reference = artifact_for_v2(
        root,
        reference_path,
        artifact_id="quality-reference-mask",
        kind="reference_mask",
    )
    candidate = artifact_for_v2(
        root,
        candidate_path,
        artifact_id="quality-candidate-mask",
        kind="candidate_mask",
    )
    contour_binding = ContourEvidenceBindingV02(
        evidence_id="reference.contour",
        origin="observed",
        authority="authoritative",
        artifact_path=reference.path,
        artifact_sha256=reference.sha256,
        camera_sha256=camera.sha256,
    )
    contour = compare_contours_v02(
        image,
        image,
        reference_evidence=contour_binding,
        candidate_evidence_id="candidate.contour",
        candidate_artifact_sha256=candidate.sha256,
        candidate_camera_sha256=camera.sha256,
    )
    semantic = compare_semantic_masks_v02(
        image,
        image,
        reference_evidence=SemanticEvidenceBindingV02(
            evidence_id="reference.semantic.body",
            semantic_id="asset.body",
            origin="registered_observed",
            authority="authoritative",
            artifact_path=reference.path,
            artifact_sha256=reference.sha256,
            camera_sha256=camera.sha256,
            registration_receipt_sha256=registration.sha256,
        ),
        candidate_evidence_id="candidate.semantic.body",
        candidate_artifact_sha256=candidate.sha256,
        candidate_camera_sha256=camera.sha256,
        critical=True,
    )
    policy = IntegratedQualityPolicyV02(
        profile_id="quality.static_prop_v02",
        critical_semantic_ids=["asset.body"],
    )
    policy_artifact = write_immutable_v2_model(
        root,
        root / "fixtures" / "quality-policy-v02.json",
        policy,
    )
    stale_quality_input = "9" * 64
    stale_quality_source = "8" * 64
    report = build_integrated_quality_report_v02(
        report_id="iq-v02-freeze-report",
        job_id="aq_v2_delivery",
        workflow_id="wf-aq-v2-delivery",
        dispatch_id="dispatch-aq-v2-delivery",
        source_fingerprint=stale_quality_source,
        camera_sha256=camera.sha256,
        input_sha256=stale_quality_input,
        legacy_v06_report_sha256=legacy.sha256,
        legacy_v06_direct_score=0.9,
        policy=policy,
        contour=contour,
        semantics=[semantic],
        landmarks=[],
        multiview=MultiviewMetricV02(
            metric_id="multiview.unavailable",
            status="unscorable",
            observations=[],
            authoritative_view_count=0,
            limitations=["optional multiview evidence was not supplied"],
        ),
        advisory_metrics=[],
        producer=ProducerIdentityV02(
            name="cbm_integrated_quality_v02",
            version="0.2.0",
        ),
        created_at=NOW,
    )
    assert report.outcome == "passed"
    report_path = root / "reports" / "integrated_quality_v02" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report_artifact = artifact_for_v2(
        root,
        report_path,
        artifact_id="iq-v02-freeze-report",
        kind="integrated_quality_report",
    )
    current_source = SimpleNamespace(
        source_fingerprint="f" * 64,
        scene_spec=SimpleNamespace(path=scene.path, sha256=scene.sha256),
        blend=SimpleNamespace(path=blend.path, sha256=blend.sha256),
        material_plan=SimpleNamespace(path=material.path, sha256=material.sha256),
        geometry_payloads=[SimpleNamespace(path=geometry.path, sha256=geometry.sha256)],
        texture_manifests=[SimpleNamespace(path=texture.path, sha256=texture.sha256)],
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.collect_source_provenance",
        lambda _root, _job: current_source,
    )
    evidence = [camera, reference, candidate, registration, legacy]
    geometry_receipt = _file_artifact(
        root,
        "geometry-validation-receipt",
        "geometry_candidate_validation_receipt",
    )
    material_receipt = _file_artifact(
        root,
        "material-phase-receipt",
        "material_phase_receipt",
    )
    quality_source = "f" * 64
    quality_input = quality_submission_input_sha256_v2(
        source_fingerprint=quality_source,
        camera_artifact=camera,
        quality_evidence=evidence,
        scene_spec=scene,
        authoring_blend=blend,
        build_provenance=build,
        material_plan=material,
        shader_recipes=[shader],
        texture_manifests=[texture],
        geometry_payloads=[geometry],
        geometry_intent_survival=survival,
        geometry_candidate_validation_receipt=geometry_receipt,
        material_phase_receipt=material_receipt,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.validate_quality_source_inputs_v2",
        lambda **_kwargs: quality_source,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.validate_quality_promotion_evidence_v2",
        lambda **_kwargs: (SimpleNamespace(), SimpleNamespace()),
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.quality_source_fingerprint_v2",
        lambda _root, _job: quality_source,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.validate_root_authorization_boundary_v2",
        lambda **_kwargs: (
            SimpleNamespace(quality_profile=policy_artifact),
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
        ),
    )
    with pytest.raises(ValueError, match="exact accepted source-freeze input"):
        publish_quality_source_freeze(
            job_root=root,
            job_id="aq_v2_delivery",
            workflow_id="wf-aq-v2-delivery",
            dispatch_id="dispatch-aq-v2-delivery",
            session_id="aq-v2-stale-quality",
            integrated_quality_report=report_artifact,
            quality_evidence=evidence,
            scene_spec=scene,
            authoring_blend=blend,
            build_provenance=build,
            material_plan=material,
            shader_recipes=[shader],
            texture_manifests=[texture],
            geometry_payloads=[geometry],
            geometry_intent_survival=survival,
            geometry_candidate_validation_receipt=geometry_receipt,
            material_phase_receipt=material_receipt,
            camera_artifact=camera,
            created_at=NOW,
        )

    accepted_report = report.model_copy(
        update={
            "source_fingerprint": quality_source,
            "input_sha256": quality_input,
        }
    )
    accepted_report_path = root / "reports" / "integrated_quality_v02" / "accepted.json"
    accepted_report_path.write_text(
        accepted_report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    accepted_report_artifact = artifact_for_v2(
        root,
        accepted_report_path,
        artifact_id="iq-v02-freeze-report-accepted",
        kind="integrated_quality_report",
    )
    freeze, freeze_artifact = publish_quality_source_freeze(
        job_root=root,
        job_id="aq_v2_delivery",
        workflow_id="wf-aq-v2-delivery",
        dispatch_id="dispatch-aq-v2-delivery",
        session_id="aq-v2-delivery",
        integrated_quality_report=accepted_report_artifact,
        quality_evidence=evidence,
        scene_spec=scene,
        authoring_blend=blend,
        build_provenance=build,
        material_plan=material,
        shader_recipes=[shader],
        texture_manifests=[texture],
        geometry_payloads=[geometry],
        geometry_intent_survival=survival,
        geometry_candidate_validation_receipt=geometry_receipt,
        material_phase_receipt=material_receipt,
        camera_artifact=camera,
        created_at=NOW,
    )
    assert freeze.quality_status == "passed"
    assert freeze.v07_source_fingerprint == "f" * 64
    assert (root / freeze_artifact.path).is_file()
    validate_quality_source_freeze(root, freeze)

    report_path.write_text(
        report.model_dump_json(indent=2).replace('"passed"', '"needs_revision"', 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="artifact (?:size|hash) changed"):
        publish_quality_source_freeze(
            job_root=root,
            job_id="aq_v2_delivery",
            workflow_id="wf-aq-v2-delivery",
            dispatch_id="dispatch-aq-v2-delivery",
            session_id="aq-v2-delivery-tampered",
            integrated_quality_report=report_artifact,
            quality_evidence=evidence,
            scene_spec=scene,
            authoring_blend=blend,
            build_provenance=build,
            material_plan=material,
            shader_recipes=[shader],
            texture_manifests=[texture],
            geometry_payloads=[geometry],
            geometry_intent_survival=survival,
            geometry_candidate_validation_receipt=geometry_receipt,
            material_phase_receipt=material_receipt,
            camera_artifact=camera,
            created_at=NOW,
        )
