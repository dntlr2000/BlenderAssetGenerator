"""Focused generic Material Closure service and pre-approval boundary tests."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pydantic import ValidationError

from codex_blender_modeler.autonomy_v2.candidate_validation_models import (
    GeometryCandidateValidationReceiptV2,
)
from codex_blender_modeler.autonomy_v2.models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyProfileV2,
    BudgetUsageV2,
    RootAuthorizationV2,
)
from codex_blender_modeler.blender_artifacts import sha256_file, stable_json_digest
from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.material_closure.collector import (
    MaterialClosureCollectionError,
    build_material_plan_absence_evidence,
    collect_material_dependency_closure_from_roots,
)
from codex_blender_modeler.material_closure.graph_rebinding import (
    serialize_rebound_material_graph,
)
from codex_blender_modeler.material_closure.models import (
    ExactArtifact,
    MaterialAppearanceApproval,
    MaterialAQBudgetObservation,
    MaterialCanonicalSnapshot,
    MaterialClosureSourceBinding,
    MaterialClosureSourceBindingArtifact,
    MaterialDependencyClosure,
    MaterialDependencyClosureReceipt,
    MaterialFrameworkFailureContext,
    MaterialGraphRebindingChange,
    MaterialGraphRebindingPlan,
    MaterialGraphRebindingReceipt,
    MaterialPlannedOutput,
    MaterialPreflightBudget,
    MaterialPreflightCheck,
    MaterialPromotionPreflightRequest,
    MaterialResourceCounters,
    MaterialShadowCompileReceipt,
    SurfaceDetailMaterialBinding,
    SurfaceDetailRequirement,
    SurfaceDetailUVRect,
)
from codex_blender_modeler.material_closure.preflight import (
    MaterialPreflightValidationError,
    collect_current_uv_layout_fingerprint,
)
from codex_blender_modeler.material_closure.service import (
    MaterialClosureService,
    material_shadow_compile,
    publish_material_appearance_approval,
)
from codex_blender_modeler.material_closure.shadow_compile import (
    MaterialShadowCompileResult,
)
from codex_blender_modeler.material_graph.models import (
    ChannelBinding,
    MaterialGraphArtifact,
    MaterialGraphProvenance,
    MaterialGraphSpec,
    PreviewLightingPolicy,
)
from codex_blender_modeler.materials.models import (
    MappingSpec,
    MaterialPlan,
    MaterialPlanItem,
)
from codex_blender_modeler.production.controller_executor.models import ControllerArtifact
from codex_blender_modeler.production.controller_executor.profiles import (
    build_phase_tool_profile,
)
from codex_blender_modeler.texturing.models import (
    SurfaceDetailBinding,
    SurfaceDetailPlacement,
    TextureChannel,
    TextureManifest,
)

NOW = datetime(2026, 8, 14, tzinfo=UTC)
SHA_A = "a" * 64


def _write_json(path: Path, payload: object) -> None:
    """Write deterministic fixture JSON without relying on service internals."""

    value = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _artifact(
    root: Path,
    relative: str,
    *,
    artifact_id: str,
    kind: str,
    media_type: str = "application/json",
) -> ExactArtifact:
    """Bind one existing fixture file to exact Material Closure evidence."""

    path = root.joinpath(*relative.split("/"))
    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=relative,
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
        media_type=media_type,
    )


def _bound_fields() -> dict[str, Any]:
    """Return one reusable strict workflow/session binding for fixture contracts."""

    return {
        "job_id": "fixture_job",
        "workflow_id": "workflow_1",
        "dispatch_id": "dispatch-1",
        "session_id": "session-1",
        "producer": "test_fixture",
        "producer_version": "0.1.0",
        "created_at": NOW,
    }


def _aq_artifact(
    root: Path,
    relative: str,
    *,
    artifact_id: str,
    kind: str,
) -> AQV2Artifact:
    """Bind one existing fixture file as exact AQ v2 evidence."""

    path = root.joinpath(*relative.split("/"))
    return AQV2Artifact(
        artifact_id=artifact_id,
        kind=kind,
        path=relative,
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
    )


def _fixture_aq_evidence(root: Path, name: str) -> AQV2Artifact:
    """Publish one non-authoritative ancillary artifact for a strict AQ fixture."""

    relative = f"production/aq_fixture/evidence/{name}.json"
    _write_json(root.joinpath(*relative.split("/")), {"fixture": name})
    return _aq_artifact(root, relative, artifact_id=name, kind=name.replace("_", "-"))


def _publish_common_material_roots(
    root: Path,
    *,
    scene: ExactArtifact,
    modeling: ExactArtifact,
    blend: ExactArtifact,
    inventory: ExactArtifact,
    reference: ExactArtifact,
) -> dict[str, str]:
    """Publish one mutually exact-bound AQ authority and geometry root graph."""

    observation_prefix = "production/material_closure/session-1/canonical_observations/"
    build_path = (
        f"{observation_prefix}build_provenance.json"
        if inventory.path.startswith(observation_prefix)
        else "reports/build_provenance.json"
    )
    _write_json(
        root.joinpath(*build_path.split("/")),
        collect_build_provenance(
            root,
            "fixture_job",
            surface_detail_inventory_path=root.joinpath(*inventory.path.split("/")),
        ),
    )
    build = _aq_artifact(
        root,
        build_path,
        artifact_id="canonical-build-provenance",
        kind="build-provenance",
    )
    aq_scene = AQV2Artifact(
        artifact_id="canonical-scene-spec",
        kind="scene-spec",
        path=scene.path,
        sha256=scene.sha256,
        byte_size=scene.byte_size,
    )
    aq_modeling = AQV2Artifact(
        artifact_id="canonical-modeling-plan",
        kind="modeling-plan",
        path=modeling.path,
        sha256=modeling.sha256,
        byte_size=modeling.byte_size,
    )
    aq_blend = AQV2Artifact(
        artifact_id="canonical-blend",
        kind="canonical-blend",
        path=blend.path,
        sha256=blend.sha256,
        byte_size=blend.byte_size,
    )
    aq_inventory = AQV2Artifact(
        artifact_id="canonical-scene-inventory",
        kind="scene-inventory",
        path=inventory.path,
        sha256=inventory.sha256,
        byte_size=inventory.byte_size,
    )
    aq_reference = AQV2Artifact(
        artifact_id="primary-reference",
        kind="primary-reference",
        path=reference.path,
        sha256=reference.sha256,
        byte_size=reference.byte_size,
    )
    dispatch = _fixture_aq_evidence(root, "production_dispatch_plan")
    controller = _fixture_aq_evidence(root, "production_controller_plan")
    quality = _fixture_aq_evidence(root, "integrated_quality_policy")
    launch = _fixture_aq_evidence(root, "production_launch")
    workflow_request = _fixture_aq_evidence(root, "workflow_request")

    tool_source_relative = "production/aq_fixture/tool_profile_source.json"
    _write_json(root.joinpath(*tool_source_relative.split("/")), {"source": "dispatch"})
    source_path = root.joinpath(*tool_source_relative.split("/"))
    tool_source = ControllerArtifact(
        artifact_id="tool-profile-source",
        role="production-dispatch-plan",
        path=tool_source_relative,
        sha256=sha256_file(source_path),
        byte_size=source_path.stat().st_size,
    )
    phase_paths: dict[str, str] = {}
    phase_artifacts: list[AQV2Artifact] = []
    for profile_id in ("geometry_authoring", "material_authoring"):
        phase = build_phase_tool_profile(
            profile_id=profile_id,
            job_id="fixture_job",
            workflow_id="workflow_1",
            dispatch_id="dispatch-1",
            session_id="session-1",
            source_artifact=tool_source,
            allowed_input_roles=["immutable-evidence"],
            allowed_output_paths=[f"production/controller/{profile_id}/output.json"],
            created_at=NOW,
        )
        relative = f"production/aq_fixture/{profile_id}_tool_profile.json"
        _write_json(root.joinpath(*relative.split("/")), phase)
        phase_paths[profile_id] = relative
        phase_artifacts.append(
            _aq_artifact(
                root,
                relative,
                artifact_id=f"{profile_id}-tool-profile",
                kind="phase-tool-profile",
            )
        )

    envelope = {
        "job_id": "fixture_job",
        "workflow_id": "workflow_1",
        "dispatch_id": "dispatch-1",
        "session_id": "session-1",
        "producer": "material_closure_fixture",
        "created_at": NOW,
    }
    budget_input = {
        "dispatch": dispatch.sha256,
        "quality": quality.sha256,
        "phase_profiles": [item.sha256 for item in phase_artifacts],
    }
    budget = AutonomyBudgetV2(
        contract_id="budget-session-1",
        budget_id="budget-session-1",
        input_sha256=stable_json_digest(budget_input),
        source_fingerprint=stable_json_digest({**budget_input, "budget": "bounded"}),
        provenance=[dispatch, quality, *phase_artifacts],
        **envelope,
    )
    budget_path = "production/aq_fixture/budget.json"
    _write_json(root.joinpath(*budget_path.split("/")), budget)
    budget_artifact = _aq_artifact(
        root, budget_path, artifact_id="budget-session-1", kind="autonomy-budget"
    )
    profile_input = {
        "budget": budget_artifact.sha256,
        "quality": quality.sha256,
        "phase_profiles": [item.sha256 for item in phase_artifacts],
    }
    profile = AutonomyProfileV2(
        contract_id="profile-session-1",
        input_sha256=stable_json_digest(profile_input),
        source_fingerprint=stable_json_digest(
            {**profile_input, "status": "disabled_experimental"}
        ),
        provenance=[budget_artifact, quality, *phase_artifacts],
        status="disabled_experimental",
        allowed_asset_kinds=["static_prop"],
        allowed_delivery_profiles=["review_only"],
        prohibited_capabilities=["destination_project_write", "synthetic_user_approval"],
        **envelope,
    )
    profile_path = "production/aq_fixture/profile.json"
    _write_json(root.joinpath(*profile_path.split("/")), profile)
    profile_artifact = _aq_artifact(
        root, profile_path, artifact_id="profile-session-1", kind="autonomy-profile"
    )
    authorization_input = {
        "reference": aq_reference.sha256,
        "profile": profile_artifact.sha256,
        "budget": budget_artifact.sha256,
        "launch": launch.sha256,
        "quality": quality.sha256,
        "phase_profiles": [item.sha256 for item in phase_artifacts],
    }
    authorization = RootAuthorizationV2(
        contract_id="authorization-session-1",
        authorization_id="authorization-session-1",
        input_sha256=stable_json_digest(authorization_input),
        source_fingerprint=stable_json_digest(
            {**authorization_input, "target": "generic fixture"}
        ),
        provenance=[
            aq_reference,
            workflow_request,
            profile_artifact,
            budget_artifact,
            launch,
            quality,
            *phase_artifacts,
        ],
        original_request_sha256=stable_json_digest({"request": "fixture"}),
        primary_reference=aq_reference,
        profile=profile_artifact,
        budget=budget_artifact,
        production_launch_or_binding=launch,
        target_subject="generic fixture",
        quality_profile=quality,
        phase_tool_profiles=phase_artifacts,
        allowed_delivery_profiles=["review_only"],
        requested_delivery_profiles=["review_only"],
        prohibited_scopes=list(profile.prohibited_capabilities),
        **envelope,
    )
    authorization_path = "production/aq_fixture/root_authorization.json"
    _write_json(root.joinpath(*authorization_path.split("/")), authorization)
    authorization_artifact = _aq_artifact(
        root,
        authorization_path,
        artifact_id="authorization-session-1",
        kind="root-authorization",
    )
    plan_input = {
        "profile": profile_artifact.sha256,
        "authorization": authorization_artifact.sha256,
        "budget": budget_artifact.sha256,
        "dispatch": dispatch.sha256,
        "controller": controller.sha256,
        "phase_profiles": [item.sha256 for item in phase_artifacts],
    }
    plan = AutonomyPlanV2(
        contract_id="plan-session-1",
        plan_id="plan-session-1",
        input_sha256=stable_json_digest(plan_input),
        source_fingerprint=stable_json_digest({**plan_input, "deliveries": ["review_only"]}),
        provenance=[
            profile_artifact,
            authorization_artifact,
            budget_artifact,
            dispatch,
            controller,
            *phase_artifacts,
        ],
        profile=profile_artifact,
        root_authorization=authorization_artifact,
        budget=budget_artifact,
        production_dispatch_plan=dispatch,
        production_controller_plan=controller,
        phase_tool_profiles=phase_artifacts,
        requested_delivery_profiles=["review_only"],
        action_limit=budget.global_action_limit,
        **envelope,
    )
    plan_path = "production/aq_fixture/plan.json"
    _write_json(root.joinpath(*plan_path.split("/")), plan)

    controller_result = _fixture_aq_evidence(root, "geometry_controller_result")
    controller_request = _fixture_aq_evidence(root, "geometry_controller_request")
    controller_completion = _fixture_aq_evidence(root, "geometry_controller_completion")
    scene_v03 = _fixture_aq_evidence(root, "candidate_scene_spec_v03")
    structural = _fixture_aq_evidence(root, "structural_recipe")
    mesh = _fixture_aq_evidence(root, "mesh_payload_v02")
    materialization = _fixture_aq_evidence(root, "materialization_receipt")
    validation = _fixture_aq_evidence(root, "geometry_validation")
    candidate_snapshot = _fixture_aq_evidence(root, "candidate_geometry_snapshot")
    canonical_snapshot = _fixture_aq_evidence(root, "canonical_geometry_snapshot")
    survival = _fixture_aq_evidence(root, "geometry_intent_survival")
    geometry_provenance = [
        authorization_artifact,
        controller_result,
        controller_request,
        phase_artifacts[0],
        controller_completion,
        aq_modeling,
        scene_v03,
        aq_scene,
        structural,
        mesh,
        materialization,
        aq_blend,
        build,
        aq_blend,
        aq_inventory,
        validation,
        candidate_snapshot,
        aq_modeling,
        aq_scene,
        aq_blend,
        canonical_snapshot,
        survival,
    ]
    geometry = GeometryCandidateValidationReceiptV2(
        contract_id="geometry-validation-session-1",
        receipt_id="geometry-validation-session-1",
        input_sha256=controller_result.sha256,
        source_fingerprint=stable_json_digest(
            {"scene": aq_scene.sha256, "inventory": aq_inventory.sha256}
        ),
        provenance=geometry_provenance,
        root_authorization=authorization_artifact,
        controller_result=controller_result,
        controller_request=controller_request,
        phase_tool_profile=phase_artifacts[0],
        controller_completion=controller_completion,
        candidate_modeling_plan=aq_modeling,
        candidate_scene_spec_v03=scene_v03,
        compiled_scene_spec=aq_scene,
        structural_recipes=[structural],
        mesh_payloads_v02=[mesh],
        materialization_receipts=[materialization],
        materialization_blends=[aq_blend],
        candidate_build_provenance=build,
        candidate_blend=aq_blend,
        candidate_inventory=aq_inventory,
        candidate_validation=validation,
        candidate_geometry_snapshot=candidate_snapshot,
        previous_modeling_plan_sha256=None,
        previous_scene_spec_sha256=None,
        previous_blend_sha256=None,
        canonical_archives=[],
        canonical_modeling_plan=aq_modeling,
        canonical_scene_spec=aq_scene,
        canonical_blend=aq_blend,
        canonical_geometry_snapshot=canonical_snapshot,
        geometry_intent_survival=survival,
        target_subject="generic fixture",
        budget_usage_after=BudgetUsageV2(
            initial_candidates=1,
            total_blender_builds=1,
            canonical_promotions=1,
            total_actions=1,
        ),
        **envelope,
    )
    geometry_path = "production/aq_fixture/geometry_validation_receipt.json"
    _write_json(root.joinpath(*geometry_path.split("/")), geometry)
    return {
        "root_authorization_path": authorization_path,
        "autonomy_plan_path": plan_path,
        "autonomy_profile_path": profile_path,
        "autonomy_budget_path": budget_path,
        "material_phase_tool_profile_path": phase_paths["material_authoring"],
        "geometry_candidate_validation_receipt_path": geometry_path,
        "canonical_build_provenance_path": build_path,
        "canonical_scene_inventory_path": inventory.path,
    }


@dataclass(frozen=True)
class _Fixture:
    """Hold one complete valid generic preflight input fixture."""

    root: Path
    request: MaterialPromotionPreflightRequest
    canonical_blend: ExactArtifact
    reference: ExactArtifact


def _fixture(
    tmp_path: Path,
    *,
    actual_canonical_blender: bool = False,
    run_owned_observations: bool = False,
    with_surface_detail: bool = False,
) -> _Fixture:
    """Build complete strict closure, rebinding, snapshot, budget, and request evidence."""

    root = tmp_path / "job"
    root.mkdir()
    scene_payload = {
        "schema_version": "0.2.0",
        "job_id": "fixture_job",
        "mode": "concept",
        "nominal_scene_size": [1.0, 1.0, 1.0],
        "sources": [
            {
                "id": "reference",
                "path": "input/reference.png",
                "kind": "reference",
            }
        ],
        "materials": [
            {
                "id": "mat0",
                "name": "Fixture Material",
                "base_color": [0.2, 0.3, 0.4, 1.0],
                "roughness": 0.5,
                "metallic": 0.0,
            }
        ],
        "objects": [
            {
                "id": "object0",
                "name": "Fixture Object",
                "geometry": {
                    "kind": "primitive",
                    "primitive": "cube",
                    "dimensions": [1.0, 1.0, 1.0],
                },
                "material_id": "mat0",
            }
        ],
        "camera": {
            "projection": "PERSP",
            "location": [2.0, -2.0, 2.0],
            "target": [0.0, 0.0, 0.0],
            "focal_length_mm": 50.0,
            "ortho_scale": 2.0,
            "resolution": [512, 512],
        },
    }
    _write_json(root / "analysis" / "scene_spec.json", scene_payload)
    _write_json(root / "analysis" / "reference_analysis.json", {"status": "fixture"})
    _write_json(root / "analysis" / "camera_solution.json", {"status": "fixture"})
    modeling_payload: dict[str, object] = {
        "schema_version": "0.4.0",
        "job_id": "fixture_job",
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
    }
    if with_surface_detail:
        modeling_payload.update(
            {
                "surface_detail_policy": {"mode": "explicit"},
                "surface_details": [
                    {
                        "id": "detail0",
                        "label": "Fixture mark",
                        "parent_object_id": "object0",
                        "representation": "texture_channels",
                        "target_material_id": "mat0",
                        "channels": ["base_color"],
                        "uv_strategy": "existing_uv",
                    }
                ],
            }
        )
    _write_json(root / "analysis" / "modeling_plan.json", modeling_payload)
    _write_json(root / "history" / "rollback.json", {"rollback": "available"})
    _write_json(
        root / "production" / "state.json",
        {
            "kind": "standard_workflow_state",
            "schema_version": "0.1.0",
            "job_id": "fixture_job",
            "workflow_id": "workflow_1",
            "dispatch_id": "dispatch-1",
            "session_id": "session-1",
            "sequence": 4,
            "status": "running",
        },
    )
    (root / "input").mkdir()
    (root / "input" / "reference.png").write_bytes(b"fixture-reference")
    (root / "blender").mkdir()
    inventory_relative = (
        "production/material_closure/session-1/canonical_observations/"
        "scene_inventory.json"
        if run_owned_observations
        else "reports/scene_inventory.json"
    )
    inventory_path = root.joinpath(*inventory_relative.split("/"))
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    if actual_canonical_blender:
        run_blender(
            "build_scene.py",
            [
                "--spec",
                str(root / "analysis" / "scene_spec.json"),
                "--job-root",
                str(root),
                "--output",
                str(root / "blender" / "scene.blend"),
            ],
            factory_startup=True,
            disable_autoexec=True,
        )
        run_blender(
            "inspect_scene.py",
            ["--output", str(inventory_path)],
            blend_file=root / "blender" / "scene.blend",
            disable_autoexec=True,
        )
    else:
        (root / "blender" / "scene.blend").write_bytes(
            b"canonical-blend-before-material"
        )
        _write_json(
            inventory_path,
            {
                "job_id": "fixture_job",
                "blender_version": "5.0.1",
                "objects": [
                    {
                        "type": "MESH",
                        "cbm_id": "object0",
                        "active_uv": "UVMap",
                        "uv_layers": [
                            {
                                "name": "UVMap",
                                "coordinate_fingerprint": "1" * 64,
                                "vertex_uv_binding_fingerprint": "2" * 64,
                                "coordinate_bounds": {
                                    "min": [0.0, 0.0],
                                    "max": [1.0, 1.0],
                                },
                            }
                        ],
                    }
                ],
            },
        )

    scene = _artifact(
        root,
        "analysis/scene_spec.json",
        artifact_id="scene-spec",
        kind="scene_spec",
    )
    modeling = _artifact(
        root,
        "analysis/modeling_plan.json",
        artifact_id="modeling-plan",
        kind="modeling_plan",
    )
    blend = _artifact(
        root,
        "blender/scene.blend",
        artifact_id="canonical-blend",
        kind="canonical_blend",
        media_type="application/x-blender",
    )
    rollback = _artifact(
        root,
        "history/rollback.json",
        artifact_id="rollback-baseline",
        kind="rollback_baseline",
    )
    state = _artifact(
        root,
        "production/state.json",
        artifact_id="current-state",
        kind="current_state",
    )
    reference = _artifact(
        root,
        "input/reference.png",
        artifact_id="reference",
        kind="primary_reference",
        media_type="image/png",
    )
    inventory = _artifact(
        root,
        inventory_relative,
        artifact_id="canonical-scene-inventory",
        kind="scene_inventory",
    )
    uv_layout_fingerprint = collect_current_uv_layout_fingerprint(
        root,
        inventory,
        expected_job_id="fixture_job",
    )

    texture_manifest_path: str | None = None
    if with_surface_detail:
        texture_manifest_path = "detail_manifest.json"
        texture_image_path = "textures/detail_base.png"
        texture_image = root.joinpath(*texture_image_path.split("/"))
        texture_image.parent.mkdir(parents=True, exist_ok=True)
        texture_image.write_bytes(b"fixture-detail-texture")
        _write_json(
            root.joinpath(*texture_manifest_path.split("/")),
            TextureManifest(
                material_id="mat0",
                uv_set="UVMap",
                intended_scale_m=1.0,
                resolution=(64, 64),
                source_type="image",
                channels={
                    "base_color": TextureChannel(
                        source="image",
                        path=texture_image_path,
                        color_space="sRGB",
                    )
                },
                surface_detail_ids=["detail0"],
                surface_detail_bindings=[
                    SurfaceDetailBinding(
                        detail_id="detail0",
                        parent_object_id="object0",
                        material_id="mat0",
                        uv_layout_sha256="2" * 64,
                        placement=SurfaceDetailPlacement(
                            mode="uv_rect",
                            uv_rect=(0.1, 0.1, 0.3, 0.3),
                        ),
                        channels=["base_color"],
                    )
                ],
            ).model_dump(mode="json", exclude_none=True),
        )
    plan = MaterialPlan(
        job_id="fixture_job",
        stage="authored",
        surface_detail_binding_policy=(
            "spatial_v1" if with_surface_detail else "legacy_unbound"
        ),
        materials=[
            MaterialPlanItem(
                material_id="mat0",
                label="Fixture",
                texture_strategy="image" if with_surface_detail else "none",
                mapping=MappingSpec(mode="uv") if with_surface_detail else MappingSpec(),
                texture_manifest=texture_manifest_path,
            )
        ],
    )
    _write_json(root / "staging" / "material_plan.json", plan)
    candidate_plan = _artifact(
        root,
        "staging/material_plan.json",
        artifact_id="candidate-plan",
        kind="candidate_material_plan",
    )
    planned_plan_path = "production/controller/output/material_plan.json"
    planned_graph_path = "production/controller/output/material_graph.json"
    graph = MaterialGraphSpec(
        graph_id="graph-1",
        material_id="mat0",
        provenance=MaterialGraphProvenance(
            job_id="fixture_job",
            workflow_id="workflow_1",
            dispatch_id="dispatch-1",
            project_version="0.9.0",
            inputs=[
                MaterialGraphArtifact(
                    role="scene_spec",
                    path=scene.path,
                    sha256=scene.sha256,
                ),
                MaterialGraphArtifact(
                    role="material_plan",
                    path=planned_plan_path,
                    sha256=candidate_plan.sha256,
                ),
                MaterialGraphArtifact(
                    role="reference",
                    path=reference.path,
                    sha256=reference.sha256,
                ),
            ],
        ),
        base_channels=[
            ChannelBinding(
                channel="base_color",
                source_kind="constant",
                color_space="sRGB",
                constant=(0.2, 0.3, 0.4, 1.0),
            ),
            ChannelBinding(
                channel="roughness",
                source_kind="constant",
                color_space="Non-Color",
                constant=0.5,
            ),
        ],
        preview_lighting=PreviewLightingPolicy(
            reference_source=MaterialGraphArtifact(
                role="reference",
                path=reference.path,
                sha256=reference.sha256,
            ),
            reference_confidence=1.0,
        ),
    )
    rebind_root = "production/material_closure/session-1/graph_rebindings/rebind-1"
    rebound_path = f"{rebind_root}/rebound_material_graph.json"
    rebind_plan_path = f"{rebind_root}/plan.json"
    rebind_receipt_path = f"{rebind_root}/receipt.json"
    rebound_file = root.joinpath(*rebound_path.split("/"))
    rebound_file.parent.mkdir(parents=True, exist_ok=True)
    rebound_file.write_bytes(
        serialize_rebound_material_graph(graph.model_dump(mode="json"))
    )
    rebound_graph = _artifact(
        root,
        rebound_path,
        artifact_id="rebound-graph",
        kind="rebound_material_graph",
    )
    source_inputs = [
        item.model_copy(update={"path": candidate_plan.path, "sha256": "f" * 64})
        if item.role == "material_plan"
        else item
        for item in graph.provenance.inputs
    ]
    source_graph_model = graph.model_copy(
        update={"provenance": graph.provenance.model_copy(update={"inputs": source_inputs})}
    )
    _write_json(root / "staging" / "source_graph.json", source_graph_model)
    source_graph = _artifact(
        root,
        "staging/source_graph.json",
        artifact_id="source-graph",
        kind="source_material_graph",
    )
    _write_json(
        root / "analysis" / "reference_authority.json",
        {
            "canonical_blend": blend.model_dump(mode="json"),
            "current_state": state.model_dump(mode="json"),
            "scene_inventory": inventory.model_dump(mode="json"),
        },
    )
    planned_outputs = [
        MaterialPlannedOutput(
            output_id="output-plan",
            output_kind="material_plan",
            path=planned_plan_path,
            verification="exact_hash",
            sha256=candidate_plan.sha256,
            media_type="application/json",
        ),
        MaterialPlannedOutput(
            output_id="output-graph",
            output_kind="material_graph",
            path=planned_graph_path,
            verification="exact_hash",
            sha256=rebound_graph.sha256,
            media_type="application/json",
        ),
        MaterialPlannedOutput(
            output_id="output-completion",
            output_kind="controller_completion",
            path="production/controller/output/completion.json",
            verification="structural_binding",
            expected_schema_version="0.1.0",
            expected_field_bindings={"immutable_inputs": "closure_projection"},
            media_type="application/json",
        ),
    ]
    planned_outputs.sort(key=lambda item: (item.output_kind, item.path))
    absence_model = build_material_plan_absence_evidence(
        job_root=root,
        absence_id="material-absence",
        job_id="fixture_job",
        workflow_id="workflow_1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        producer="test_fixture",
        producer_version="0.1.0",
        created_at=NOW,
        observation_state=state,
        canonical_scene_spec=scene,
        canonical_blend=blend,
    )
    _write_json(root / "production" / "material_plan_absence.json", absence_model)
    absence = _artifact(
        root,
        "production/material_plan_absence.json",
        artifact_id="material-absence",
        kind="material_plan_absence",
    )
    common_roots = _publish_common_material_roots(
        root,
        scene=scene,
        modeling=modeling,
        blend=blend,
        inventory=inventory,
        reference=reference,
    )
    source_binding = MaterialClosureSourceBindingArtifact(
        **_bound_fields(),
        binding_id="source-binding-1",
        uv_layout_fingerprint=uv_layout_fingerprint,
        scene_spec_path=scene.path,
        modeling_plan_path=modeling.path,
        **common_roots,
        material_plan_absence_evidence_path=absence.path,
        candidate_material_plan_path=candidate_plan.path,
        material_graph_path=source_graph.path,
        graph_rebinding_plan_path=rebind_plan_path,
        graph_rebinding_receipt_path=rebind_receipt_path,
        rebound_material_graph_path=rebound_graph.path,
        rollback_baseline_path=rollback.path,
        source_evidence=MaterialClosureSourceBinding(
            source_mode="procedural",
            primary_reference_path=reference.path,
            reference_authority_path="analysis/reference_authority.json",
        ),
    )
    source_binding_path = "production/material_closure/session-1/source_binding.json"
    _write_json(root.joinpath(*source_binding_path.split("/")), source_binding)
    source_binding_artifact = _artifact(
        root,
        source_binding_path,
        artifact_id="source-binding-1",
        kind="material_closure_source_binding",
    )
    change = MaterialGraphRebindingChange(
        dependency_role="material_plan",
        path_pointer="/provenance/inputs/1/path",
        hash_pointer="/provenance/inputs/1/sha256",
        before_path=candidate_plan.path,
        before_sha256="f" * 64,
        after_path=planned_plan_path,
        after_sha256=candidate_plan.sha256,
    )
    rebinding_plan_model = MaterialGraphRebindingPlan(
        **_bound_fields(),
        plan_id="rebind-1",
        source_binding=source_binding_artifact,
        source_graph=source_graph,
        candidate_material_plan=candidate_plan,
        output_path=rebound_graph.path,
        expected_rebound_sha256=rebound_graph.sha256,
        changes=[change],
    )
    _write_json(root.joinpath(*rebind_plan_path.split("/")), rebinding_plan_model)
    rebinding_plan = _artifact(
        root,
        rebind_plan_path,
        artifact_id="rebind-1",
        kind="material_graph_rebinding_plan",
    )
    rebinding_receipt = MaterialGraphRebindingReceipt(
        **_bound_fields(),
        receipt_id="rebinding-receipt-1",
        plan=rebinding_plan,
        source_binding=source_binding_artifact,
        status="passed",
        source_graph=source_graph,
        rebound_graph=rebound_graph,
        applied_changes=[change],
        semantic_content_unchanged=True,
    )
    _write_json(root.joinpath(*rebind_receipt_path.split("/")), rebinding_receipt)
    rebinding_receipt_artifact = _artifact(
        root,
        rebind_receipt_path,
        artifact_id="rebinding-receipt-1",
        kind="material_graph_rebinding_receipt",
    )
    closure = collect_material_dependency_closure_from_roots(
        job_root=root,
        source_binding=source_binding_artifact,
        closure_id="closure-1",
        job_id="fixture_job",
        workflow_id="workflow_1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        producer="test_fixture",
        producer_version="0.1.0",
        created_at=NOW,
        planned_outputs=planned_outputs,
    )
    _write_json(root / "production" / "closure.json", closure)
    closure_artifact = _artifact(
        root,
        "production/closure.json",
        artifact_id="closure-1",
        kind="material_dependency_closure",
    )
    closure_receipt = MaterialDependencyClosureReceipt(
        **_bound_fields(),
        receipt_id="closure-receipt-1",
        closure=closure_artifact,
        closure_sha256=closure.closure_sha256,
        status="passed",
        immutable_input_projection=closure.project_immutable_input_map(),
        planned_output_projection=closure.project_planned_output_map(),
    )
    _write_json(root / "production" / "closure_receipt.json", closure_receipt)
    closure_receipt_artifact = _artifact(
        root,
        "production/closure_receipt.json",
        artifact_id="closure-receipt-1",
        kind="material_dependency_closure_receipt",
    )
    snapshot = MaterialCanonicalSnapshot(
        **_bound_fields(),
        snapshot_id="snapshot-1",
        scene_spec=scene,
        modeling_plan=modeling,
        material_plan_absence=absence,
        blend=blend,
        build_provenance=_artifact(
            root,
            common_roots["canonical_build_provenance_path"],
            artifact_id="canonical-build-provenance",
            kind="build_provenance",
        ),
        build_provenance_fingerprint=sha256_file(
            root.joinpath(*common_roots["canonical_build_provenance_path"].split("/"))
        ),
    )
    _write_json(root / "production" / "canonical_snapshot.json", snapshot)
    snapshot_artifact = _artifact(
        root,
        "production/canonical_snapshot.json",
        artifact_id="snapshot-1",
        kind="material_canonical_snapshot",
    )
    counters = MaterialResourceCounters(
        preflight_blender_runs=0,
        controller_invocations=0,
        canonical_promotions=0,
        appearance_revisions=0,
    )
    budget = MaterialPreflightBudget(
        **_bound_fields(),
        budget_id="budget-1",
        limits=MaterialResourceCounters(
            preflight_blender_runs=6,
            controller_invocations=1,
            canonical_promotions=1,
            appearance_revisions=1,
        ),
        consumed=counters,
    )
    _write_json(root / "production" / "budget.json", budget)
    budget_artifact = _artifact(
        root,
        "production/budget.json",
        artifact_id="budget-1",
        kind="material_preflight_budget",
    )
    context = MaterialFrameworkFailureContext(
        state_sequence=4,
        current_state=state,
        canonical_snapshot=snapshot,
        controller_execution_count=0,
        rollback_count=0,
        budget_usage=counters,
        aq_budget_observation=MaterialAQBudgetObservation(
            blender_builds_used=0,
            blender_builds_limit=14,
            controller_invocations_used=0,
            controller_invocations_limit=16,
            canonical_promotions_used=0,
            canonical_promotions_limit=5,
            actions_used=0,
            actions_limit=72,
            quality_evaluations_used=0,
            quality_evaluations_limit=10,
        ),
        neutral_preview_present=False,
        material_phase_receipt_present=False,
        integrated_quality_entered=False,
    )
    request = MaterialPromotionPreflightRequest(
        **_bound_fields(),
        request_id="request-1",
        closure=closure_artifact,
        closure_receipt=closure_receipt_artifact,
        graph_rebinding_receipt=rebinding_receipt_artifact,
        candidate_material_plan=candidate_plan,
        rebound_material_graph=rebound_graph,
        canonical_snapshot=snapshot_artifact,
        budget=budget_artifact,
        framework_failure_context=context,
        uv_layout_fingerprint=uv_layout_fingerprint,
        surface_details=(
            [
                SurfaceDetailRequirement(
                    detail_id="detail0",
                    object_id="object0",
                    material_id="mat0",
                    strategy="image",
                    uv_set="UVMap",
                    uv_layout_fingerprint=uv_layout_fingerprint,
                    requested_channels=["base_color"],
                    coverage_id="detail0",
                    uv_rect=SurfaceDetailUVRect(
                        u_min=0.1,
                        v_min=0.1,
                        u_max=0.3,
                        v_max=0.3,
                    ),
                    wrap_policy="clamp",
                )
            ]
            if with_surface_detail
            else []
        ),
        surface_bindings=(
            [
                SurfaceDetailMaterialBinding(
                    detail_id="detail0",
                    object_id="object0",
                    material_id="mat0",
                    strategy="image",
                    mapping="uv",
                    uv_set="UVMap",
                    uv_layout_fingerprint=uv_layout_fingerprint,
                    available_channels=["base_color"],
                    coverage_ids=["detail0"],
                )
            ]
            if with_surface_detail
            else []
        ),
        planned_output_projection=closure.project_planned_output_map(),
    )
    return _Fixture(root=root, request=request, canonical_blend=blend, reference=reference)


def _fake_shadow(
    job_root: Path,
    *,
    request: MaterialPromotionPreflightRequest,
    request_artifact: ExactArtifact,
    closure_artifact: ExactArtifact,
    shadow_root_path: str,
    created_at: datetime,
    **_kwargs: object,
) -> MaterialShadowCompileResult:
    """Return exact deterministic Blender-like evidence without requiring bpy in Python CI."""

    shadow_root = job_root.joinpath(*shadow_root_path.split("/"))
    shadow_root.mkdir(parents=True)
    _write_json(shadow_root / "validation.json", {"ok": True, "blender": "5.0.1"})
    validation = _artifact(
        job_root,
        (shadow_root / "validation.json").relative_to(job_root).as_posix(),
        artifact_id="shadow-validation",
        kind="shadow_scene_validation",
    )
    preview_path = shadow_root / "neutral_preview" / "mat0" / "swatch.png"
    preview_path.parent.mkdir(parents=True)
    Image.new("RGBA", (64, 64), (32, 64, 96, 255)).save(preview_path)
    preview = _artifact(
        job_root,
        preview_path.relative_to(job_root).as_posix(),
        artifact_id="neutral-image",
        kind="neutral_preview_image",
        media_type="image/png",
    )
    _write_json(
        shadow_root / "neutral_preview" / "renderer.json",
        {"scope": "neutral_studio", "image_sha256": preview.sha256},
    )
    renderer = _artifact(
        job_root,
        (shadow_root / "neutral_preview" / "renderer.json").relative_to(job_root).as_posix(),
        artifact_id="neutral-renderer",
        kind="neutral_preview_renderer_manifest",
    )
    bound = _bound_fields()
    bound["created_at"] = created_at
    receipt = MaterialShadowCompileReceipt(
        **bound,
        receipt_id="shadow-request-1",
        preflight_request=request_artifact,
        closure=closure_artifact,
        status="passed",
        blender_version="5.0.1",
        blender_executable_sha256=SHA_A,
        shadow_root=shadow_root_path,
        checks=[
            MaterialPreflightCheck(
                check_id="shadow_complete",
                category="blender",
                status="passed",
                message="Isolated full-scene build, inspect, validation, and render passed.",
            )
        ],
        outputs=[validation, preview, renderer],
    )
    return MaterialShadowCompileResult(
        receipt=receipt,
        preview_image=preview,
        preview_renderer_manifest=renderer,
        color_management_fingerprint="c" * 64,
        blender_runs_attempted=6,
    )


def test_preflight_success_is_approval_eligible_and_crash_adopted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require one exact neutral preview and prevent a duplicate Blender execution."""

    fixture = _fixture(tmp_path)
    calls = 0

    def fake(*args: object, **kwargs: object) -> MaterialShadowCompileResult:
        """Count fixture shadow invocations before returning exact evidence."""

        nonlocal calls
        calls += 1
        return _fake_shadow(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        fake,
    )
    service = MaterialClosureService(fixture.root)
    result = service.run_preflight(fixture.request, preview_size=64, created_at=NOW)
    assert result.failure is None, (
        result.failure.issues if result.failure is not None else None
    )
    assert result.approval_plan_eligible
    assert result.report is not None
    assert result.report.approval_may_be_requested is True
    assert result.report.controller_may_execute is False
    assert result.neutral_preview is not None
    assert result.neutral_preview.reference_matched_preview is None
    assert result.resource_receipt is not None
    assert result.resource_receipt.consumed_by_event.preflight_blender_runs == 6
    assert result.resource_receipt.consumed_by_event.controller_invocations == 0
    adopted = service.run_preflight(fixture.request, preview_size=64, created_at=NOW)
    assert adopted.approval_plan_eligible
    assert calls == 1


def test_preflight_uses_run_owned_canonical_inventory_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay UV identity from the source-bound observation instead of a stale report path."""

    fixture = _fixture(tmp_path, run_owned_observations=True)
    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        _fake_shadow,
    )
    result = MaterialClosureService(fixture.root).run_preflight(
        fixture.request,
        preview_size=64,
        created_at=NOW,
    )
    assert result.failure is None
    assert result.approval_plan_eligible
    assert not (fixture.root / "reports" / "scene_inventory.json").exists()


def test_preflight_requires_every_modeling_plan_surface_detail_before_blender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an empty request when ModelingPlan requires exact texture-backed details."""

    fixture = _fixture(tmp_path, with_surface_detail=True)
    called = False

    def forbidden(*_args: object, **_kwargs: object) -> MaterialShadowCompileResult:
        """Fail if incomplete surface-detail evidence reaches isolated Blender work."""

        nonlocal called
        called = True
        raise AssertionError("surface-detail completeness must fail before Blender")

    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        forbidden,
    )
    incomplete = fixture.request.model_copy(
        update={"surface_details": [], "surface_bindings": []}
    )
    result = MaterialClosureService(fixture.root).run_preflight(
        incomplete,
        created_at=NOW,
    )
    assert result.failure is not None
    assert "exactly cover ModelingPlan" in result.failure.issues[0].message
    assert not called
    assert result.failure.approval_created is False
    assert result.failure.controller_invocations_consumed == 0


def test_preflight_accepts_exact_modeling_plan_and_texture_manifest_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept exact request, MaterialPlan, manifest, UV, and placement agreement."""

    fixture = _fixture(tmp_path, with_surface_detail=True)
    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        _fake_shadow,
    )
    result = MaterialClosureService(fixture.root).run_preflight(
        fixture.request,
        preview_size=64,
        created_at=NOW,
    )
    assert result.failure is None
    assert result.report is not None
    surface_check = next(
        check for check in result.report.checks if check.check_id == "surface_details"
    )
    assert surface_check.status == "passed"


def test_missing_dependency_fails_before_blender_approval_controller_or_canonical_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require both strict failure contracts while preserving every canonical byte."""

    fixture = _fixture(tmp_path)
    canonical_before = sha256_file(fixture.root / fixture.canonical_blend.path)
    (fixture.root / fixture.reference.path).unlink()
    called = False

    def forbidden(*_args: object, **_kwargs: object) -> MaterialShadowCompileResult:
        """Fail the test if dependency validation allows Blender to start."""

        nonlocal called
        called = True
        raise AssertionError("shadow compile must not start")

    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        forbidden,
    )
    result = MaterialClosureService(fixture.root).run_preflight(
        fixture.request,
        created_at=NOW,
    )
    assert not result.approval_plan_eligible
    assert not called
    assert result.failure is not None
    assert result.framework_failure_report is not None
    assert result.failure.approval_created is False
    assert result.failure.controller_invocations_consumed == 0
    assert result.failure.canonical_promotions_consumed == 0
    assert result.failure.canonical_write_performed is False
    assert result.framework_failure_report.framework_failure is True
    assert result.framework_failure_report.existing_retry_execution_forbidden is True
    assert sha256_file(fixture.root / fixture.canonical_blend.path) == canonical_before


@pytest.mark.parametrize(
    "binding_field",
    [
        "root_authorization_path",
        "autonomy_plan_path",
        "autonomy_profile_path",
        "autonomy_budget_path",
        "material_phase_tool_profile_path",
        "geometry_candidate_validation_receipt_path",
        "canonical_build_provenance_path",
        "canonical_scene_inventory_path",
    ],
)
def test_each_required_common_root_is_rehashed_before_closure_collection(
    tmp_path: Path,
    binding_field: str,
) -> None:
    """Reject deletion of every explicit common root instead of trusting indirect JSON."""

    fixture = _fixture(tmp_path)
    source_binding_path = (
        fixture.root
        / "production"
        / "material_closure"
        / "session-1"
        / "source_binding.json"
    )
    binding = MaterialClosureSourceBindingArtifact.model_validate_json(
        source_binding_path.read_bytes()
    )
    target = fixture.root.joinpath(*str(getattr(binding, binding_field)).split("/"))
    target.unlink()
    closure = MaterialDependencyClosure.model_validate_json(
        (fixture.root / "production" / "closure.json").read_bytes()
    )
    with pytest.raises(MaterialClosureCollectionError, match="(MISSING_DEPENDENCY|ROOT_ARTIFACT)"):
        collect_material_dependency_closure_from_roots(
            job_root=fixture.root,
            source_binding=closure.source_binding,
            closure_id=closure.closure_id,
            job_id=closure.job_id,
            workflow_id=closure.workflow_id,
            dispatch_id=closure.dispatch_id,
            session_id=closure.session_id,
            producer=closure.producer,
            producer_version=closure.producer_version,
            created_at=closure.created_at,
            planned_outputs=closure.planned_outputs,
        )


def test_output_root_is_derived_and_reserved_before_any_write(tmp_path: Path) -> None:
    """Reject caller-selected analysis/input/blender publication paths before mutation."""

    fixture = _fixture(tmp_path)
    service = MaterialClosureService(fixture.root)
    with pytest.raises(MaterialPreflightValidationError, match="run-owned path"):
        service.run_preflight(fixture.request, output_root="analysis/preflight")
    assert not (fixture.root / "analysis" / "preflight").exists()


def test_unrecognized_failure_context_state_fails_before_publication(tmp_path: Path) -> None:
    """Reject arbitrary contained JSON as a framework-state anchor before writing a request."""

    fixture = _fixture(tmp_path)
    _write_json(fixture.root / "production" / "arbitrary_state.json", {"sequence": 4})
    arbitrary = _artifact(
        fixture.root,
        "production/arbitrary_state.json",
        artifact_id="arbitrary-state",
        kind="current_state",
    )
    context = fixture.request.framework_failure_context.model_copy(
        update={"current_state": arbitrary}
    )
    request = fixture.request.model_copy(update={"framework_failure_context": context})
    with pytest.raises(MaterialPreflightValidationError, match="recognized"):
        MaterialClosureService(fixture.root).run_preflight(request)
    assert not (
        fixture.root
        / "production"
        / "material_closure"
        / "session-1"
        / "preflights"
        / "request-1"
    ).exists()


def test_historical_replay_tolerates_expected_promotion_but_approval_replay_does_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve execution-time evidence after expected canonical Blend supersession."""

    fixture = _fixture(tmp_path)
    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        _fake_shadow,
    )
    service = MaterialClosureService(fixture.root)
    result = service.run_preflight(fixture.request, preview_size=64, created_at=NOW)
    assert result.report_artifact is not None
    (fixture.root / fixture.canonical_blend.path).write_bytes(b"promoted-canonical-blend")
    replayed = service.validate_published_preflight(result.report_artifact)
    assert replayed.status == "passed"
    with pytest.raises(MaterialPreflightValidationError, match="closure (byte size|dependency)"):
        service.validate_preflight_for_approval(result.report_artifact)


def test_public_shadow_facade_is_always_complete_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose shadow compilation only as the full dependency-to-approval preflight gate."""

    fixture = _fixture(tmp_path)
    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        _fake_shadow,
    )
    result = material_shadow_compile(
        fixture.root,
        fixture.request,
        preview_size=64,
        created_at=NOW,
    )
    assert result.status == "complete_preflight_passed"
    assert result.execution_scope == "complete_preflight_with_shadow_compile"
    assert result.report_artifact is not None
    assert result.shadow_receipt_artifact is not None
    assert result.neutral_preview_artifact is not None
    assert result.resource_receipt_artifact is not None


def test_appearance_publisher_rejects_unobserved_or_stale_user_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject synthesized or stale approval fields without fabricating a user decision."""

    fixture = _fixture(tmp_path)
    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        _fake_shadow,
    )
    result = material_shadow_compile(
        fixture.root,
        fixture.request,
        preview_size=64,
        created_at=NOW,
    )
    assert result.report_artifact is not None
    assert result.neutral_preview is not None
    closure_path = fixture.root.joinpath(*fixture.request.closure.path.split("/"))
    closure = MaterialDependencyClosure.model_validate_json(closure_path.read_bytes())
    snapshot = fixture.request.framework_failure_context.canonical_snapshot
    approval = MaterialAppearanceApproval.model_construct(
        **_bound_fields(),
        approval_id="untrusted-appearance-claim-1",
        decision="approved",
        approved_by="untrusted_fixture",
        scope="material_appearance_promotion",
        candidate_material_plan_sha256=fixture.request.candidate_material_plan.sha256,
        rebound_material_graph_sha256=fixture.request.rebound_material_graph.sha256,
        closure_sha256=closure.closure_sha256,
        preflight_report_sha256=result.report_artifact.sha256,
        neutral_preview_sha256=result.neutral_preview.preview_image.sha256,
        canonical_scene_spec_sha256=snapshot.scene_spec.sha256,
        canonical_blend_sha256=snapshot.blend.sha256,
        uv_layout_fingerprint=fixture.request.uv_layout_fingerprint,
        known_limitations=[],
    )
    with pytest.raises(PermissionError, match="explicit observed user decision"):
        publish_material_appearance_approval(
            fixture.root,
            report_artifact=result.report_artifact,
            approval=approval,
            explicit_user_decision_observed=False,
        )
    approval_root = (
        fixture.root
        / "production"
        / "material_closure"
        / "session-1"
        / "appearance_approvals"
    )
    assert not approval_root.exists()
    stale = approval.model_copy(update={"canonical_blend_sha256": "f" * 64})
    with pytest.raises(PermissionError, match="authored from a user decision"):
        publish_material_appearance_approval(
            fixture.root,
            report_artifact=result.report_artifact,
            approval=stale,
            explicit_user_decision_observed=True,
        )
    assert not approval_root.exists()
    assert not approval_root.exists()


def test_session_budget_blocks_a_distinct_second_request_before_blender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aggregate one immutable budget across request IDs instead of resetting per request."""

    fixture = _fixture(tmp_path)
    calls = 0

    def fake(*args: object, **kwargs: object) -> MaterialShadowCompileResult:
        """Count the only budget-authorized shadow execution."""

        nonlocal calls
        calls += 1
        return _fake_shadow(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        fake,
    )
    service = MaterialClosureService(fixture.root)
    first = service.run_preflight(fixture.request, preview_size=64, created_at=NOW)
    assert first.approval_plan_eligible
    second_request = fixture.request.model_copy(update={"request_id": "request-2"})
    second = service.run_preflight(
        second_request,
        preview_size=64,
        created_at=NOW.replace(second=1),
    )
    assert not second.approval_plan_eligible
    assert second.failure is not None
    assert "budget" in second.failure.issues[0].message
    assert calls == 1


def test_tampered_resource_chain_fails_before_blender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject modified prior resource evidence rather than deriving a fresh budget head."""

    fixture = _fixture(tmp_path)
    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        _fake_shadow,
    )
    service = MaterialClosureService(fixture.root)
    first = service.run_preflight(fixture.request, preview_size=64, created_at=NOW)
    assert first.resource_receipt_artifact is not None
    receipt_path = fixture.root.joinpath(
        *first.resource_receipt_artifact.path.split("/")
    )
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["receipt_id"] = "resource-forged"
    _write_json(receipt_path, payload)
    called = False

    def forbidden(*_args: object, **_kwargs: object) -> MaterialShadowCompileResult:
        """Prove budget-chain tampering is rejected before Blender."""

        nonlocal called
        called = True
        raise AssertionError("Blender must not run after resource-chain tampering")

    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        forbidden,
    )
    second = service.run_preflight(
        fixture.request.model_copy(update={"request_id": "request-2"}),
        preview_size=64,
        created_at=NOW.replace(second=1),
    )
    assert second.failure is not None
    assert not called
    assert "exact resource receipt" in second.failure.issues[0].message


def test_shadow_receipt_rejects_non_supported_blender_version() -> None:
    """Keep actual support claims pinned to exact Blender 5.0.1 evidence."""

    fields = _bound_fields()
    artifact = ExactArtifact(
        artifact_id="artifact",
        kind="test_artifact",
        path="production/test.json",
        sha256=SHA_A,
        byte_size=1,
        media_type="application/json",
    )
    with pytest.raises(ValidationError, match="5.0.1"):
        MaterialShadowCompileReceipt(
            **fields,
            receipt_id="shadow",
            preflight_request=artifact,
            closure=artifact,
            status="passed",
            blender_version="4.3.0",
            blender_executable_sha256=SHA_A,
            shadow_root="production/shadow",
            checks=[
                MaterialPreflightCheck(
                    check_id="shadow_complete",
                    category="blender",
                    status="passed",
                    message="passed",
                )
            ],
            outputs=[artifact],
        )


def test_uv_fingerprint_is_semantic_order_stable_and_mutation_sensitive(
    tmp_path: Path,
) -> None:
    """Derive UV identity from semantic objects while ignoring inventory list order."""

    root = tmp_path / "job"
    root.mkdir()
    layer_a = {
        "name": "UVMap",
        "coordinate_fingerprint": "1" * 64,
        "vertex_uv_binding_fingerprint": "2" * 64,
    }
    layer_b = {
        "name": "UVMap",
        "coordinate_fingerprint": "3" * 64,
        "vertex_uv_binding_fingerprint": "4" * 64,
    }
    objects = [
        {
            "type": "MESH",
            "cbm_id": "object.b",
            "active_uv": "UVMap",
            "uv_layers": [layer_b],
        },
        {
            "type": "MESH",
            "cbm_id": "object.a",
            "active_uv": "UVMap",
            "uv_layers": [layer_a],
        },
    ]

    def write_inventory(name: str, rows: list[dict[str, object]]) -> ExactArtifact:
        """Persist and exact-bind one synthetic Blender inventory variant."""

        relative = f"reports/{name}.json"
        _write_json(
            root.joinpath(*relative.split("/")),
            {
                "job_id": "fixture_job",
                "blender_version": "5.0.1",
                "objects": rows,
            },
        )
        return _artifact(root, relative, artifact_id=name, kind="scene_inventory")

    first = collect_current_uv_layout_fingerprint(
        root,
        write_inventory("first", objects),
        expected_job_id="fixture_job",
    )
    reordered = collect_current_uv_layout_fingerprint(
        root,
        write_inventory("reordered", list(reversed(objects))),
        expected_job_id="fixture_job",
    )
    assert reordered == first
    mutated_objects = json.loads(json.dumps(objects))
    mutated_objects[0]["uv_layers"][0]["coordinate_fingerprint"] = "5" * 64
    mutated = collect_current_uv_layout_fingerprint(
        root,
        write_inventory("mutated", mutated_objects),
        expected_job_id="fixture_job",
    )
    assert mutated != first


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_MATERIAL_CLOSURE_BLENDER_SMOKE") != "1",
    reason="set CBM_RUN_MATERIAL_CLOSURE_BLENDER_SMOKE=1 for Blender 5.0.1 smoke",
)
def test_complete_preflight_runs_actual_blender_5_and_stops_before_approval(
    tmp_path: Path,
) -> None:
    """Run real Blender preflight and prove its review boundary has no side effects."""

    fixture = _fixture(tmp_path, actual_canonical_blender=True)
    canonical_paths = {
        "scene_spec": fixture.root / "analysis" / "scene_spec.json",
        "modeling_plan": fixture.root / "analysis" / "modeling_plan.json",
        "blend": fixture.root.joinpath(*fixture.canonical_blend.path.split("/")),
    }
    canonical_before = {
        role: (sha256_file(path), path.stat().st_size)
        for role, path in canonical_paths.items()
    }
    assert not (fixture.root / "analysis" / "material_plan.json").exists()
    result = material_shadow_compile(
        fixture.root,
        fixture.request,
        preview_size=64,
        created_at=NOW,
    )
    assert result.status == "complete_preflight_passed"
    assert result.approval_plan_eligible is True
    assert result.report is not None
    assert result.report.approval_may_be_requested is True
    assert result.report.controller_may_execute is False
    assert result.report.canonical_unchanged is True
    assert result.shadow_receipt is not None
    assert result.shadow_receipt.blender_version == "5.0.1"
    assert result.shadow_receipt.canonical_unchanged is True
    assert result.resource_receipt is not None
    assert result.resource_receipt.consumed_by_event.preflight_blender_runs > 0
    assert result.resource_receipt.consumed_by_event.controller_invocations == 0
    assert result.resource_receipt.consumed_by_event.canonical_promotions == 0
    assert result.neutral_preview is not None
    preview_path = fixture.root.joinpath(
        *result.neutral_preview.preview_image.path.split("/")
    )
    with Image.open(preview_path) as image:
        image.load()
        assert image.format == "PNG"
        assert image.size == (64, 64)
    assert {
        role: (sha256_file(path), path.stat().st_size)
        for role, path in canonical_paths.items()
    } == canonical_before
    assert not (fixture.root / "analysis" / "material_plan.json").exists()
    assert not list(fixture.root.rglob("appearance_approvals"))
    assert not list(fixture.root.rglob("approval_consumptions"))
    assert not list(fixture.root.rglob("controller_executions"))
    assert not list(fixture.root.rglob("promotion_receipt.json"))
    assert not list(fixture.root.rglob("rollback_receipt.json"))
    assert not list(fixture.root.rglob("material_phase_receipt.json"))
    assert not any(
        part.lower() in {"unity", "unreal", "destination"}
        for path in fixture.root.rglob("*")
        for part in path.relative_to(fixture.root).parts
    )
