"""Opt-in Blender 5 E2E for exact-approved dual-format AQ v2 delivery."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import codex_blender_modeler.autonomy_v2.delivery_executor as delivery_executor
from codex_blender_modeler.autonomy_v2.candidate_validation_models import (
    GeometryCandidateValidationReceiptV2,
)
from codex_blender_modeler.autonomy_v2.delivery_executor import (
    execute_approved_delivery_plan_v2,
)
from codex_blender_modeler.autonomy_v2.delivery_service import (
    artifact_for_v2,
    create_delivery_plan,
    prepare_v07_delivery_reviews,
    publish_delivery_terminal,
    publish_quality_source_freeze,
    quality_source_fingerprint_v2,
    quality_submission_input_sha256_v2,
    validate_delivery_terminal_v2,
    validate_quality_source_freeze,
    validate_v2_artifact,
    write_immutable_v2_model,
)
from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialPhaseReceiptV2,
    MaterialPromotionIntentV2,
)
from codex_blender_modeler.autonomy_v2.models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyProfileV2,
    BudgetUsageV2,
    QualityApprovedSourceFreeze,
    RootAuthorizationV2,
)
from codex_blender_modeler.autonomy_v2.quality_terminal_service import (
    publish_quality_terminal_v2,
)
from codex_blender_modeler.blender_artifacts import (
    sha256_file,
    stable_json_digest,
    write_json_atomic,
)
from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.config import executable_exists, get_settings
from codex_blender_modeler.integrated_quality.v02_contour_metrics import (
    compare_contours_v02,
)
from codex_blender_modeler.integrated_quality.v02_models import (
    ContourEvidenceBindingV02,
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
from codex_blender_modeler.material_graph.runtime_models import (
    MaterialGraphCompileReport,
    RuntimeArtifact,
)
from codex_blender_modeler.materials.scaffold import create_material_scaffold
from codex_blender_modeler.materials.service import validate_job_material_contracts
from codex_blender_modeler.optimization.io import load_model
from codex_blender_modeler.optimization.models import (
    OptimizationApproval,
    OptimizationPlan,
    PortableMaterialConversionManifest,
)
from codex_blender_modeler.optimization.optimizer import approve_asset_optimization
from codex_blender_modeler.optimization.provenance import collect_source_provenance
from codex_blender_modeler.packaging.material_conversion import (
    convert_portable_materials as convert_portable_materials_real,
)
from codex_blender_modeler.packaging.models import (
    ExportPackageManifest,
    RoundTripValidation,
)
from codex_blender_modeler.structural_geometry.geometry_delivery_inspector_v02 import (
    inspect_delivery_geometry_stage_v02,
)
from codex_blender_modeler.structural_geometry.geometry_survival_v02 import (
    GeometryIntentSurvivalReportV02,
    compare_geometry_stage_snapshots_v02,
    publish_geometry_survival_report_v02,
)
from codex_blender_modeler.workspace import ensure_job_dirs

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AQ_V02_DELIVERY_EXECUTOR_BLENDER_E2E") != "1",
    reason=("set CBM_RUN_AQ_V02_DELIVERY_EXECUTOR_BLENDER_E2E=1 for the Blender E2E"),
)

JOB_ID = "aq2delivery"
WORKFLOW_ID = "wf-aq2e2e"
DISPATCH_ID = "dispatch-aq2e2e"
SESSION_ID = "session-aq2e2e"
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _write_json(path: Path, payload: object) -> Path:
    """Write one deterministic JSON fixture and return its path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)
    return path


def _artifact(root: Path, path: Path, artifact_id: str, kind: str) -> AQV2Artifact:
    """Create one exact AQ v2 binding for a contained fixture artifact."""

    return artifact_for_v2(
        root,
        path,
        artifact_id=artifact_id,
        kind=kind,
    )


def _prepare_canonical_static_prop(workspace: Path) -> tuple[Path, dict[str, object]]:
    """Create and build one minimal primary-only canonical static prop."""

    root = ensure_job_dirs(JOB_ID)
    reference = root / "input" / "reference.png"
    Image.new("RGB", (64, 64), (28, 32, 38)).save(reference)
    scene_spec = {
        "schema_version": "0.2.0",
        "job_id": JOB_ID,
        "mode": "concept",
        "units": "METERS",
        "coordinate_system": {
            "handedness": "RIGHT",
            "up": "+Z",
            "forward": "-Y",
        },
        "nominal_scene_size": [2.0, 1.4, 1.2],
        "sources": [
            {
                "id": "reference.primary",
                "path": "input/reference.png",
                "kind": "reference",
                "immutable": True,
                "scale_anchors": [],
            }
        ],
        "materials": [
            {
                "id": "mat.body",
                "name": "Fixture painted metal",
                "shader": "principled",
                "base_color": [0.16, 0.34, 0.72, 1.0],
                "roughness": 0.42,
                "metallic": 0.35,
                "emission_strength": 0.0,
                "texture_manifest": None,
            }
        ],
        "objects": [
            {
                "id": "asset.body",
                "name": "AQ v2 delivery fixture body",
                "geometry": {
                    "kind": "primitive",
                    "primitive": "cube",
                    "dimensions": [2.0, 1.4, 1.2],
                    "segments": 16,
                    "ring_segments": 8,
                },
                "transform": {
                    "location": [0.0, 0.0, 0.6],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                },
                "material_id": "mat.body",
                "modifiers": [],
                "generator": None,
                "parent_id": None,
                "shade_smooth": False,
                "tags": ["qa_role:primary", "static-prop"],
                "evidence": [
                    {
                        "source_id": "reference.primary",
                        "bbox_norm": [0.2, 0.2, 0.8, 0.8],
                        "status": "observed",
                        "confidence": 1.0,
                    }
                ],
                "editable": {},
            }
        ],
        "camera": {
            "projection": "PERSP",
            "location": [3.6, -5.2, 3.0],
            "target": [0.0, 0.0, 0.6],
            "focal_length_mm": 50.0,
            "ortho_scale": 3.4,
            "resolution": [320, 240],
        },
        "assumptions": ["Synthetic bounded static-prop delivery fixture."],
        "revision_notes": [],
    }
    _write_json(root / "analysis" / "scene_spec.json", scene_spec)
    _write_json(
        root / "job.json",
        {
            "job_id": JOB_ID,
            "mode": "concept",
            "project_version_created": "0.9.0",
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
            "reference_path": str(reference),
            "reference_sha256": sha256_file(reference),
            "sources": [
                {
                    "kind": "reference",
                    "path": str(reference),
                    "sha256": sha256_file(reference),
                }
            ],
            "scale_anchors": [],
            "reference_content_scope": "primary_object_only",
            "target_subject": "fixture body",
        },
    )
    _write_json(
        root / "analysis" / "modeling_plan.json",
        {
            "schema_version": "0.4.0",
            "job_id": JOB_ID,
            "reference_analysis_path": "analysis/reference_analysis.json",
            "camera_solution_path": "analysis/camera_solution.json",
            "stage": "authored",
            "objects": [
                {
                    "id": "asset.body",
                    "label": "AQ v2 delivery fixture body",
                    "recommended_geometry": "primitive",
                    "source_ids": ["reference.primary"],
                    "bbox_norm": [0.2, 0.2, 0.8, 0.8],
                    "observed": True,
                    "confidence": 1.0,
                    "scope_role": "primary",
                    "assembly_role": "unclassified",
                    "required_assembly_checks": [],
                    "notes": ["Synthetic delivery fixture."],
                }
            ],
            "assembly_consistency_policy": "legacy_unbound",
            "assembly_frame": None,
            "assembly_relationships": [],
            "surface_detail_policy": None,
            "surface_details": [],
            "global_notes": ["Synthetic bounded static-prop delivery fixture."],
        },
    )
    create_material_scaffold(JOB_ID)
    material_validation = validate_job_material_contracts(JOB_ID)
    assert material_validation["ok"] is True
    blend = root / "blender" / "scene.blend"
    run_blender(
        "build_scene.py",
        [
            "--spec",
            str(root / "analysis" / "scene_spec.json"),
            "--output",
            str(blend),
        ],
        factory_startup=True,
        disable_autoexec=True,
    )
    build = collect_build_provenance(root, JOB_ID)
    _write_json(root / "reports" / "aq_v2" / "build_provenance.json", build)
    assert root.parent == workspace
    return root, build


def _publish_candidate_to_canonical_survival(
    root: Path,
    *,
    source_fingerprint: str,
    build_fingerprint: str,
) -> tuple[AQV2Artifact, AQV2Artifact, AQV2Artifact]:
    """Inspect the actual canonical blend twice and bind candidate promotion survival."""

    candidate = inspect_delivery_geometry_stage_v02(
        job_root=root,
        artifact_relative_path="blender/scene.blend",
        stage="compiled_candidate",
        output_relative_path="reports/aq_v2/compiled_candidate_snapshot.json",
        source_fingerprint_sha256=source_fingerprint,
        build_fingerprint_sha256=build_fingerprint,
    )
    canonical = inspect_delivery_geometry_stage_v02(
        job_root=root,
        artifact_relative_path="blender/scene.blend",
        stage="promoted_canonical",
        output_relative_path="reports/aq_v2/promoted_canonical_snapshot.json",
        source_fingerprint_sha256=source_fingerprint,
        build_fingerprint_sha256=build_fingerprint,
    )
    report = compare_geometry_stage_snapshots_v02(
        report_id="survival-candidate-to-canonical-e2e",
        relation="candidate_to_canonical",
        source=candidate,
        target=canonical,
    )
    assert report.overall_status == "exact"
    report_path = root / "reports" / "aq_v2" / "candidate_to_canonical.json"
    publish_geometry_survival_report_v02(report_path, report)
    return (
        _artifact(
            root,
            report_path,
            "candidate-to-canonical-survival",
            "geometry_survival",
        ),
        _artifact(
            root,
            root / "reports" / "aq_v2" / "compiled_candidate_snapshot.json",
            "candidate-geometry-snapshot",
            "geometry_snapshot",
        ),
        _artifact(
            root,
            root / "reports" / "aq_v2" / "promoted_canonical_snapshot.json",
            "canonical-geometry-snapshot",
            "geometry_snapshot",
        ),
    )


def _publish_passed_quality_report(
    root: Path,
    *,
    scene: AQV2Artifact,
    blend: AQV2Artifact,
    build: AQV2Artifact,
    material: AQV2Artifact,
    recipes: list[AQV2Artifact],
    textures: list[AQV2Artifact],
    geometry: list[AQV2Artifact],
    survival: AQV2Artifact,
    geometry_receipt: AQV2Artifact,
    material_receipt: AQV2Artifact,
) -> tuple[AQV2Artifact, list[AQV2Artifact], AQV2Artifact]:
    """Publish one exact passed IQ 0.2 report from deterministic observed masks."""

    camera_path = _write_json(
        root / "reports" / "aq_v2" / "quality_camera.json",
        {
            "projection": "PERSP",
            "location": [3.6, -5.2, 3.0],
            "target": [0.0, 0.0, 0.6],
            "focal_length_mm": 50.0,
        },
    )
    registration_path = _write_json(
        root / "reports" / "aq_v2" / "mask_registration.json",
        {"semantic_id": "asset.body", "status": "registered"},
    )
    legacy_path = _write_json(
        root / "reports" / "aq_v2" / "legacy_v06_report.json",
        {"schema_version": "0.6.0", "direct_score": 0.98, "status": "passed"},
    )
    camera = _artifact(root, camera_path, "quality-camera", "camera")
    registration = _artifact(
        root,
        registration_path,
        "quality-mask-registration",
        "registration_receipt",
    )
    legacy = _artifact(root, legacy_path, "quality-v06", "visual_qa_report")
    image = Image.new("L", (48, 48), 0)
    ImageDraw.Draw(image).rounded_rectangle((10, 12, 37, 35), radius=3, fill=255)
    reference_path = root / "reports" / "aq_v2" / "reference_mask.png"
    candidate_path = root / "reports" / "aq_v2" / "candidate_mask.png"
    image.save(reference_path)
    image.save(candidate_path)
    reference = _artifact(
        root,
        reference_path,
        "quality-reference-mask",
        "reference_mask",
    )
    candidate = _artifact(
        root,
        candidate_path,
        "quality-candidate-mask",
        "candidate_mask",
    )
    contour = compare_contours_v02(
        image,
        image,
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
    evidence = [camera, reference, candidate, registration, legacy]
    quality_source = quality_source_fingerprint_v2(root, JOB_ID)
    quality_input = quality_submission_input_sha256_v2(
        source_fingerprint=quality_source,
        camera_artifact=camera,
        quality_evidence=evidence,
        scene_spec=scene,
        authoring_blend=blend,
        build_provenance=build,
        material_plan=material,
        shader_recipes=recipes,
        texture_manifests=textures,
        geometry_payloads=geometry,
        geometry_intent_survival=survival,
        geometry_candidate_validation_receipt=geometry_receipt,
        material_phase_receipt=material_receipt,
    )
    report = build_integrated_quality_report_v02(
        report_id="iq-v02-delivery-e2e",
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        dispatch_id=DISPATCH_ID,
        source_fingerprint=quality_source,
        camera_sha256=camera.sha256,
        input_sha256=quality_input,
        legacy_v06_report_sha256=legacy.sha256,
        legacy_v06_direct_score=0.98,
        policy=IntegratedQualityPolicyV02(
            profile_id="quality.static_prop_v02",
            critical_semantic_ids=["asset.body"],
        ),
        contour=contour,
        semantics=[semantic],
        landmarks=[],
        multiview=MultiviewMetricV02(
            metric_id="multiview.unavailable",
            status="unscorable",
            observations=[],
            authoritative_view_count=0,
            limitations=["Optional multiview evidence is outside this delivery fixture."],
        ),
        advisory_metrics=[],
        producer=ProducerIdentityV02(
            name="cbm_aq_v02_delivery_e2e",
            version="0.2.0",
        ),
        created_at=NOW,
    )
    assert report.outcome == "passed"
    assert report.quality_accepted is True
    report_path = root / "reports" / "integrated_quality_v02" / "e2e_report.json"
    _write_json(report_path, report.model_dump(mode="json"))
    report_artifact = _artifact(
        root,
        report_path,
        "iq-v02-delivery-e2e",
        "integrated_quality_report",
    )
    return report_artifact, evidence, camera


def _source_artifacts(
    root: Path,
    build: dict[str, object],
) -> tuple[
    AQV2Artifact,
    AQV2Artifact,
    AQV2Artifact,
    AQV2Artifact,
    list[AQV2Artifact],
    list[AQV2Artifact],
    list[AQV2Artifact],
]:
    """Bind current canonical SceneSpec, blend, material, recipes, and payload sets."""

    source = collect_source_provenance(root, JOB_ID)
    assert source.scene_spec is not None
    assert source.material_plan is not None
    scene = _artifact(
        root,
        root / source.scene_spec.path,
        "canonical-scene-spec",
        "scene_spec",
    )
    blend = _artifact(
        root,
        root / source.blend.path,
        "canonical-authoring-blend",
        "blend",
    )
    build_artifact = _artifact(
        root,
        root / "reports" / "aq_v2" / "build_provenance.json",
        "canonical-build-provenance",
        "build_provenance",
    )
    material = _artifact(
        root,
        root / source.material_plan.path,
        "canonical-material-plan",
        "material_plan",
    )
    material_records = build.get("materials")
    assert isinstance(material_records, dict)
    recipe_paths = sorted(
        {
            str(record["shader_recipe_path"])
            for record in material_records.values()
            if isinstance(record, dict) and record.get("shader_recipe_path")
        }
    )
    recipes = [
        _artifact(root, root / relative, f"shader-recipe-{index:02d}", "shader_recipe")
        for index, relative in enumerate(recipe_paths, start=1)
    ]
    textures = [
        _artifact(
            root,
            root / item.path,
            f"texture-manifest-{index:02d}",
            "texture_manifest",
        )
        for index, item in enumerate(source.texture_manifests, start=1)
    ]
    geometry = [
        _artifact(
            root,
            root / item.path,
            f"geometry-payload-{index:02d}",
            "geometry_payload",
        )
        for index, item in enumerate(source.geometry_payloads, start=1)
    ]
    return scene, blend, build_artifact, material, recipes, textures, geometry


def _fixture_evidence(
    root: Path,
    name: str,
    *,
    kind: str = "promotion_fixture_evidence",
) -> AQV2Artifact:
    """Publish one nonempty contained artifact for a named promotion-fixture role."""

    path = _write_json(
        root / "reports" / "aq_v2" / "promotion_fixture" / f"{name}.json",
        {"fixture_role": name, "job_id": JOB_ID},
    )
    return _artifact(root, path, f"fixture-{name}", kind)


def _publish_material_compile_report(
    root: Path,
) -> AQV2Artifact:
    """Publish a strict passed compile report for the delivery-only promotion fixture."""

    roles = [
        "request",
        "normalized_plan",
        "dependency_manifest",
        "compiled_blend",
        "normalized_inventory",
        "portable_approximation",
        "neutral_preview_manifest",
        "reference_preview_manifest",
    ]
    artifacts: list[RuntimeArtifact] = []
    for role in roles:
        artifact = _fixture_evidence(root, f"compile-{role}")
        artifacts.append(
            RuntimeArtifact(
                role=role,
                path=artifact.path,
                sha256=artifact.sha256,
                byte_size=artifact.byte_size,
            )
        )
    report = MaterialGraphCompileReport(
        report_id="material-compile-delivery-e2e",
        request_id="material-compile-request-delivery-e2e",
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        dispatch_id=DISPATCH_ID,
        run_id="material-compile-run-delivery-e2e",
        graph_id="material-graph-delivery-e2e",
        material_id="mat.body",
        blender_version="5.0.1",
        blender_python_version="3.11",
        registry_sha256=stable_json_digest({"registry": "fixture"}),
        normalized_plan_sha256=stable_json_digest({"plan": "fixture"}),
        normalized_inventory_sha256=stable_json_digest({"inventory": "fixture"}),
        artifacts=artifacts,
        warnings=[],
        limitations=["Delivery E2E reuses the separately verified material compiler gate."],
        completed_at=NOW,
    )
    path = _write_json(
        root / "reports" / "aq_v2" / "promotion_fixture" / "compile_report.json",
        report.model_dump(mode="json"),
    )
    return _artifact(
        root,
        path,
        "material-compile-report-delivery-e2e",
        "material_graph_compile_report",
    )


def _publish_quality_promotion_receipts(
    root: Path,
    *,
    build: dict[str, object],
    root_authorization: AQV2Artifact,
    scene: AQV2Artifact,
    blend: AQV2Artifact,
    build_artifact: AQV2Artifact,
    material: AQV2Artifact,
    survival: AQV2Artifact,
    candidate_snapshot: AQV2Artifact,
    canonical_snapshot: AQV2Artifact,
) -> tuple[AQV2Artifact, AQV2Artifact]:
    """Publish strict geometry/material receipts bound to the real canonical fixture."""

    modeling = _artifact(
        root,
        root / "analysis" / "modeling_plan.json",
        "canonical-modeling-plan-delivery-e2e",
        "modeling_plan",
    )
    controller_result = _fixture_evidence(root, "geometry-controller-result")
    controller_request = _fixture_evidence(root, "geometry-controller-request")
    phase_profile = _fixture_evidence(root, "geometry-phase-tool-profile")
    controller_completion = _fixture_evidence(root, "geometry-controller-completion")
    scene_v03 = _fixture_evidence(root, "geometry-scene-spec-v03")
    structural = _fixture_evidence(root, "geometry-structural-recipe")
    mesh_payload = _fixture_evidence(root, "geometry-mesh-payload")
    materialization = _fixture_evidence(root, "geometry-materialization-receipt")
    inventory = _fixture_evidence(root, "geometry-candidate-inventory")
    validation = _fixture_evidence(root, "geometry-candidate-validation")
    geometry_provenance = [
        root_authorization,
        controller_result,
        controller_request,
        phase_profile,
        controller_completion,
        modeling,
        scene_v03,
        scene,
        structural,
        mesh_payload,
        materialization,
        blend,
        build_artifact,
        blend,
        inventory,
        validation,
        candidate_snapshot,
        modeling,
        scene,
        blend,
        canonical_snapshot,
        survival,
    ]
    geometry_receipt = GeometryCandidateValidationReceiptV2(
        contract_id=f"geometry-validation-{SESSION_ID}",
        receipt_id=f"geometry-validation-{SESSION_ID}",
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        dispatch_id=DISPATCH_ID,
        session_id=SESSION_ID,
        input_sha256=controller_result.sha256,
        source_fingerprint=stable_json_digest({"scene": scene.sha256, "survival": survival.sha256}),
        producer="codex_blender_modeler.autonomy_v2.candidate_validation_service",
        provenance=geometry_provenance,
        created_at=NOW,
        root_authorization=root_authorization,
        controller_result=controller_result,
        controller_request=controller_request,
        phase_tool_profile=phase_profile,
        controller_completion=controller_completion,
        candidate_modeling_plan=modeling,
        candidate_scene_spec_v03=scene_v03,
        compiled_scene_spec=scene,
        structural_recipes=[structural],
        mesh_payloads_v02=[mesh_payload],
        materialization_receipts=[materialization],
        materialization_blends=[blend],
        candidate_build_provenance=build_artifact,
        candidate_blend=blend,
        candidate_inventory=inventory,
        candidate_validation=validation,
        candidate_geometry_snapshot=candidate_snapshot,
        previous_modeling_plan_sha256=None,
        previous_scene_spec_sha256=None,
        previous_blend_sha256=None,
        canonical_archives=[],
        canonical_modeling_plan=modeling,
        canonical_scene_spec=scene,
        canonical_blend=blend,
        canonical_geometry_snapshot=canonical_snapshot,
        geometry_intent_survival=survival,
        target_subject="fixture body",
        budget_usage_after=BudgetUsageV2(
            initial_candidates=1,
            total_blender_builds=2,
            canonical_promotions=1,
            total_actions=1,
        ),
    )
    geometry_path = _write_json(
        root / "aq2" / "delivery_e2e_geometry" / "receipt.json",
        geometry_receipt.model_dump(mode="json"),
    )
    geometry_receipt_artifact = _artifact(
        root,
        geometry_path,
        geometry_receipt.contract_id,
        "geometry_candidate_validation_receipt",
    )

    material_controller = _fixture_evidence(root, "material-controller-result")
    material_completion = _fixture_evidence(root, "material-controller-completion")
    material_graph = _fixture_evidence(root, "material-graph-spec")
    material_validation = _fixture_evidence(root, "material-validation")
    compile_report = _publish_material_compile_report(root)
    source_scene = scene
    intent_provenance = [
        material_controller,
        material_completion,
        material,
        material_graph,
        material_validation,
        compile_report,
        source_scene,
    ]
    intent = MaterialPromotionIntentV2(
        contract_id="material-intent-delivery-e2e",
        intent_id="material-intent-delivery-e2e",
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        dispatch_id=DISPATCH_ID,
        session_id=SESSION_ID,
        input_sha256=stable_json_digest(
            {"controller": material_controller.sha256, "scene": scene.sha256}
        ),
        source_fingerprint=stable_json_digest(
            {"material": material.sha256, "graph": material_graph.sha256}
        ),
        producer="codex_blender_modeler.autonomy_v2.material_phase_service",
        provenance=intent_provenance,
        created_at=NOW,
        controller_result=material_controller,
        controller_completion=material_completion,
        material_plan_candidate=material,
        material_graph_spec=material_graph,
        material_validation=material_validation,
        graph_compile_report=compile_report,
        source_scene_spec=source_scene,
        previous_material_plan=None,
        expected_canonical_material_sha256=None,
        candidate_material_sha256=material.sha256,
    )
    intent_path = _write_json(
        root / "production" / "autonomy_v2" / SESSION_ID / "material_promotion_intent.json",
        intent.model_dump(mode="json"),
    )
    intent_artifact = _artifact(
        root,
        intent_path,
        intent.contract_id,
        "material_promotion_intent",
    )
    scene_inventory = _fixture_evidence(root, "material-scene-inventory")
    scene_validation = _fixture_evidence(root, "material-scene-validation")
    material_provenance = [
        intent_artifact,
        material_controller,
        material,
        material_graph,
        material_validation,
        compile_report,
        material,
        scene,
        blend,
        scene_inventory,
        scene_validation,
        build_artifact,
    ]
    build_fingerprint = build.get("fingerprint")
    assert isinstance(build_fingerprint, str)
    material_receipt = MaterialPhaseReceiptV2(
        contract_id="material-receipt-delivery-e2e",
        receipt_id="material-receipt-delivery-e2e",
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        dispatch_id=DISPATCH_ID,
        session_id=SESSION_ID,
        input_sha256=stable_json_digest(
            {"intent": intent_artifact.sha256, "build": build_fingerprint}
        ),
        source_fingerprint=stable_json_digest({"material": material.sha256, "scene": scene.sha256}),
        producer="codex_blender_modeler.autonomy_v2.material_phase_service",
        provenance=material_provenance,
        created_at=NOW,
        promotion_intent=intent_artifact,
        controller_result=material_controller,
        material_plan_candidate=material,
        material_graph_spec=material_graph,
        material_validation=material_validation,
        graph_compile_report=compile_report,
        archived_material_plan=None,
        canonical_material_snapshot=material,
        canonical_scene_snapshot=scene,
        authoring_blend_snapshot=blend,
        scene_inventory_snapshot=scene_inventory,
        scene_validation_snapshot=scene_validation,
        build_provenance_snapshot=build_artifact,
        previous_canonical_material_sha256=None,
        canonical_material_plan_sha256=material.sha256,
        canonical_scene_spec_sha256=scene.sha256,
        build_fingerprint=build_fingerprint,
        budget_usage_after=BudgetUsageV2(
            initial_candidates=1,
            material_rounds=1,
            total_blender_builds=3,
            canonical_promotions=2,
            total_actions=2,
        ),
    )
    material_path = _write_json(
        root
        / "production"
        / "autonomy_v2"
        / SESSION_ID
        / "material_phase"
        / "0001"
        / "promotion_receipt.json",
        material_receipt.model_dump(mode="json"),
    )
    material_receipt_artifact = _artifact(
        root,
        material_path,
        material_receipt.contract_id,
        "material_phase_receipt",
    )
    return geometry_receipt_artifact, material_receipt_artifact


def _publish_root_authorization(
    root: Path,
    reference: AQV2Artifact,
) -> AQV2Artifact:
    """Publish exact planner-shaped active authorization, profile, budget, and plan."""

    session_root = root / "production" / "autonomy_v2" / SESSION_ID
    dispatch = _fixture_evidence(root, "authorization-dispatch-plan")
    controller = _fixture_evidence(root, "authorization-controller-plan")
    launch_path = _write_json(
        session_root / "launch.json",
        {"mode": "desktop_in_session", "status": "test_fixture"},
    )
    tool_profile_path = _write_json(
        session_root / "tool_profile.json",
        {"phase": "delivery", "authority": "strict_existing_services"},
    )
    launch = _artifact(root, launch_path, "launch-v2-e2e", "production_launch")
    tool_profile = _artifact(
        root,
        tool_profile_path,
        "tool-profile-v2-e2e",
        "phase_tool_profile",
    )
    quality_policy = IntegratedQualityPolicyV02(
        profile_id="quality.static_prop_v02",
        critical_semantic_ids=["asset.body"],
    )
    quality_profile = write_immutable_v2_model(
        root,
        session_root / "integrated_quality_policy.json",
        quality_policy,
    )
    budget_input = {
        "dispatch_plan": dispatch.sha256,
        "quality_policy": quality_profile.sha256,
        "phase_profiles": [tool_profile.sha256],
    }
    budget_model = AutonomyBudgetV2(
        contract_id=f"budget-{SESSION_ID}",
        budget_id=f"budget-{SESSION_ID}",
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        dispatch_id=DISPATCH_ID,
        session_id=SESSION_ID,
        input_sha256=stable_json_digest(budget_input),
        source_fingerprint=stable_json_digest(
            {**budget_input, "profile": "autonomous_static_prop_v2"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[dispatch, quality_profile, tool_profile],
        created_at=NOW,
        delivery_runs=2,
    )
    budget = write_immutable_v2_model(root, session_root / "budget.json", budget_model)
    profile_input = {
        "budget": budget.sha256,
        "quality_policy": quality_profile.sha256,
        "phase_profiles": [tool_profile.sha256],
    }
    profile_model = AutonomyProfileV2(
        contract_id=f"profile-{SESSION_ID}",
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        dispatch_id=DISPATCH_ID,
        session_id=SESSION_ID,
        input_sha256=stable_json_digest(profile_input),
        source_fingerprint=stable_json_digest(
            {**profile_input, "status": "disabled_experimental"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[budget, quality_profile, tool_profile],
        created_at=NOW,
        status="disabled_experimental",
        allowed_asset_kinds=["static_hard_surface", "static_prop"],
        allowed_delivery_profiles=["review_only", "portable_gltf", "portable_fbx"],
        prohibited_capabilities=["interior", "measured", "rig", "animation"],
    )
    profile = write_immutable_v2_model(root, session_root / "profile.json", profile_model)
    request_sha256 = stable_json_digest(
        {"requested_delivery_profiles": ["portable_gltf", "portable_fbx"]}
    )
    authorization_inputs = {
        "request": request_sha256,
        "primary_reference": reference.sha256,
        "profile": profile.sha256,
        "budget": budget.sha256,
        "launch": launch.sha256,
        "quality_policy": quality_profile.sha256,
        "phase_profiles": [tool_profile.sha256],
        "requested_deliveries": ["portable_gltf", "portable_fbx"],
        "target_subject": "fixture body",
    }
    provenance = [reference, profile, budget, launch, quality_profile, tool_profile]
    authorization = RootAuthorizationV2(
        contract_id=f"authorization-{SESSION_ID}",
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        dispatch_id=DISPATCH_ID,
        session_id=SESSION_ID,
        input_sha256=stable_json_digest(authorization_inputs),
        source_fingerprint=stable_json_digest(
            {**authorization_inputs, "destination_hint": "engine_neutral"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=provenance,
        created_at=NOW,
        authorization_id=f"authorization-{SESSION_ID}",
        original_request_sha256=request_sha256,
        primary_reference=reference,
        profile=profile,
        budget=budget,
        production_launch_or_binding=launch,
        target_subject="fixture body",
        quality_profile=quality_profile,
        phase_tool_profiles=[tool_profile],
        allowed_delivery_profiles=["review_only", "portable_gltf", "portable_fbx"],
        requested_delivery_profiles=["portable_gltf", "portable_fbx"],
        prohibited_scopes=["interior", "measured", "rig", "animation", "gameplay"],
    )
    authorization_artifact = write_immutable_v2_model(
        root,
        session_root / "root_authorization.json",
        authorization,
    )
    plan_inputs = {
        "profile": profile.sha256,
        "authorization": authorization_artifact.sha256,
        "budget": budget.sha256,
        "dispatch": dispatch.sha256,
        "controller": controller.sha256,
        "phase_profiles": [tool_profile.sha256],
    }
    plan = AutonomyPlanV2(
        contract_id=f"plan-{SESSION_ID}",
        plan_id=f"plan-{SESSION_ID}",
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        dispatch_id=DISPATCH_ID,
        session_id=SESSION_ID,
        input_sha256=stable_json_digest(plan_inputs),
        source_fingerprint=stable_json_digest(
            {
                **plan_inputs,
                "requested_deliveries": ["portable_gltf", "portable_fbx"],
            }
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[
            profile,
            authorization_artifact,
            budget,
            dispatch,
            controller,
            tool_profile,
        ],
        created_at=NOW,
        profile=profile,
        root_authorization=authorization_artifact,
        budget=budget,
        production_dispatch_plan=dispatch,
        production_controller_plan=controller,
        phase_tool_profiles=[tool_profile],
        requested_delivery_profiles=["portable_gltf", "portable_fbx"],
        action_limit=budget_model.global_action_limit,
    )
    write_immutable_v2_model(root, session_root / "plan.json", plan)
    return authorization_artifact


def _publish_quality_terminal(
    root: Path,
    freeze: QualityApprovedSourceFreeze,
    freeze_artifact: AQV2Artifact,
) -> AQV2Artifact:
    """Publish the authoring-quality terminal independently of portable delivery."""

    _terminal, artifact = publish_quality_terminal_v2(
        job_root=root,
        session_id=SESSION_ID,
        status="quality_approved",
        integrated_quality_report=freeze.integrated_quality_report,
        source_freeze=freeze_artifact,
        reason="Exact IQ 0.2 fixture evidence passed before portable delivery.",
        created_at=NOW,
    )
    return artifact


def _load_bound_model(root: Path, artifact: AQV2Artifact, model):
    """Rehash and load one exact model named by an AQ v2 result."""

    path = validate_v2_artifact(root, artifact)
    return model.model_validate_json(path.read_bytes())


def test_exact_approved_dual_glb_fbx_delivery_and_crash_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run two independent real Blender deliveries and re-adopt their exact evidence."""

    settings = get_settings()
    if not executable_exists(settings.blender_bin):
        pytest.skip(f"Blender executable not found: {settings.blender_bin}")
    workspace = tmp_path.parent / "w"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    root, build = _prepare_canonical_static_prop(workspace)
    source = collect_source_provenance(root, JOB_ID)
    survival, candidate_snapshot, canonical_snapshot = _publish_candidate_to_canonical_survival(
        root,
        source_fingerprint=source.source_fingerprint,
        build_fingerprint=source.build_fingerprint,
    )
    scene, blend, build_artifact, material, recipes, textures, geometry = _source_artifacts(
        root, build
    )
    reference = _artifact(
        root,
        root / "input" / "reference.png",
        "primary-reference-e2e",
        "reference",
    )
    root_authorization = _publish_root_authorization(root, reference)
    geometry_receipt, material_receipt = _publish_quality_promotion_receipts(
        root,
        build=build,
        root_authorization=root_authorization,
        scene=scene,
        blend=blend,
        build_artifact=build_artifact,
        material=material,
        survival=survival,
        candidate_snapshot=candidate_snapshot,
        canonical_snapshot=canonical_snapshot,
    )
    report, quality_evidence, camera = _publish_passed_quality_report(
        root,
        scene=scene,
        blend=blend,
        build=build_artifact,
        material=material,
        recipes=recipes,
        textures=textures,
        geometry=geometry,
        survival=survival,
        geometry_receipt=geometry_receipt,
        material_receipt=material_receipt,
    )
    freeze, freeze_artifact = publish_quality_source_freeze(
        job_root=root,
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        dispatch_id=DISPATCH_ID,
        session_id=SESSION_ID,
        integrated_quality_report=report,
        quality_evidence=quality_evidence,
        scene_spec=scene,
        authoring_blend=blend,
        build_provenance=build_artifact,
        material_plan=material,
        shader_recipes=recipes,
        texture_manifests=textures,
        geometry_payloads=geometry,
        geometry_intent_survival=survival,
        geometry_candidate_validation_receipt=geometry_receipt,
        material_phase_receipt=material_receipt,
        camera_artifact=camera,
        created_at=NOW,
    )
    validate_quality_source_freeze(root, freeze)
    plan, plan_artifact = create_delivery_plan(
        job_root=root,
        root_authorization_artifact=root_authorization,
        source_freeze_artifact=freeze_artifact,
        plan_id="aq2-e2e",
        allow_disabled_experimental=True,
        created_at=NOW,
    )
    assert plan.direct_cross_format_conversion is False
    assert {item.source_freeze.sha256 for item in plan.requests} == {freeze_artifact.sha256}
    assert len({item.run_id for item in plan.requests}) == 2
    assert len({item.package_id for item in plan.requests}) == 2
    reviews, reviews_artifact = prepare_v07_delivery_reviews(
        job_root=root,
        delivery_plan_artifact=plan_artifact,
        created_at=NOW,
    )
    approvals: list[OptimizationApproval] = []
    for entry in reviews.entries:
        approval = approve_asset_optimization(
            JOB_ID,
            run_id=entry.run_id,
            plan_sha256=entry.exact_plan_sha256,
            approval_note=(
                f"Explicit fixture user approval for only {entry.profile_id} "
                f"plan {entry.exact_plan_sha256}."
            ),
        )
        approvals.append(approval)
    assert [item.approved_by for item in approvals] == ["user", "user"]
    assert len({item.plan_sha256 for item in approvals}) == 2
    canonical_hashes = {
        path: sha256_file(path)
        for path in (
            root / "analysis" / "scene_spec.json",
            root / "analysis" / "material_plan.json",
            root / "blender" / "scene.blend",
        )
    }

    def convert_fixture_at_low_resolution(
        job_id: str,
        *,
        profile_id: str,
        run_id: str,
        conversion_id: str,
    ) -> PortableMaterialConversionManifest:
        """Call the real converter with a bounded 128px E2E texture budget."""

        return convert_portable_materials_real(
            job_id,
            profile_id=profile_id,
            run_id=run_id,
            conversion_id=conversion_id,
            resolution=128,
            margin_px=8,
            render_device="cpu",
        )

    monkeypatch.setattr(
        delivery_executor,
        "convert_portable_materials",
        convert_fixture_at_low_resolution,
    )
    results = execute_approved_delivery_plan_v2(
        job_root=root,
        delivery_plan_artifact=plan_artifact,
        delivery_review_artifact=reviews_artifact,
    )
    assert [item.status for item in results] == ["completed", "completed"], [
        item.model_dump(mode="json") for item in results
    ]
    assert {item.source_freeze_sha256 for item in results} == {freeze_artifact.sha256}
    assert all(item.production_ready for item in results)

    by_profile = {item.profile_id: item for item in results}
    expected = {
        "portable_gltf": ("portable_gltf", ".glb", "GLB", "clean_import_glb"),
        "portable_fbx": ("fbx_interchange", ".fbx", "FBX", "clean_import_fbx"),
    }
    conversion_sources: dict[str, str] = {}
    for public_profile, (asset_profile, suffix, package_format, target_stage) in expected.items():
        result = by_profile[public_profile]
        assert result.package_manifest is not None
        assert result.roundtrip_validation is not None
        assert result.material_loss_report is not None
        assert result.geometry_survival_report is not None
        package = _load_bound_model(root, result.package_manifest, ExportPackageManifest)
        roundtrip = _load_bound_model(
            root,
            result.roundtrip_validation,
            RoundTripValidation,
        )
        material_loss = _load_bound_model(
            root,
            result.material_loss_report,
            PortableMaterialConversionManifest,
        )
        geometry_loss = _load_bound_model(
            root,
            result.geometry_survival_report,
            GeometryIntentSurvivalReportV02,
        )
        request = next(item for item in plan.requests if item.profile.profile_id == public_profile)
        assert request.run_id is not None
        assert request.package_id is not None
        completed_plan = load_model(
            root / "optimization" / "runs" / request.run_id / "optimization_plan.json",
            OptimizationPlan,
        )
        used_approval = load_model(
            root / "optimization" / "runs" / request.run_id / "optimization_approval.json",
            OptimizationApproval,
        )
        assert completed_plan.status == "complete"
        assert completed_plan.source.source_fingerprint == freeze.v07_source_fingerprint
        assert completed_plan.source.blend.path == "blender/scene.blend"
        assert completed_plan.source.blend.sha256 == blend.sha256
        assert used_approval.used is True
        assert used_approval.plan_sha256 == next(
            item.exact_plan_sha256
            for item in reviews.entries
            if item.delivery_id == result.delivery_id
        )
        primary = next(item for item in package.files if item.id == package.primary_file_id)
        assert Path(primary.path).suffix.casefold() == suffix
        assert package.profile_id == asset_profile
        assert package.run_id == request.run_id
        assert package.package_id == request.package_id
        assert package.source.source_fingerprint == freeze.v07_source_fingerprint
        assert roundtrip.ok is True
        assert roundtrip.status == "passed"
        assert roundtrip.profile_id == asset_profile
        raw_roundtrip = json.loads(
            (root / roundtrip.imported_inventory.path).read_text(encoding="utf-8")
        )
        assert raw_roundtrip["runtime"]["blender_version"] == "5.0.1"
        assert material_loss.status == "complete"
        assert material_loss.profile_id == asset_profile
        assert material_loss.missing_material_ids == []
        assert material_loss.optimized_blend.path.startswith(f"optimization/runs/{request.run_id}/")
        conversion_sources[public_profile] = material_loss.optimized_blend.path
        assert geometry_loss.package_format == package_format
        assert geometry_loss.target_stage == target_stage
        assert geometry_loss.overall_status == "known_loss"
        assert geometry_loss.known_losses
        assert all(item.status != "failed" for item in geometry_loss.checks)

    assert conversion_sources["portable_gltf"] != conversion_sources["portable_fbx"]
    assert conversion_sources["portable_gltf"].casefold().endswith(".blend")
    assert conversion_sources["portable_fbx"].casefold().endswith(".blend")
    assert {path: sha256_file(path) for path in canonical_hashes} == canonical_hashes

    adopted = execute_approved_delivery_plan_v2(
        job_root=root,
        delivery_plan_artifact=plan_artifact,
        delivery_review_artifact=reviews_artifact,
    )
    assert adopted == results
    quality_terminal = _publish_quality_terminal(root, freeze, freeze_artifact)
    terminal, terminal_artifact = publish_delivery_terminal(
        job_root=root,
        quality_terminal_artifact=quality_terminal,
        delivery_plan_artifact=plan_artifact,
        delivery_review_artifact=reviews_artifact,
        results=adopted,
        created_at=NOW,
    )
    assert terminal.outcome == "completed"
    assert terminal.canonical_unchanged is True
    assert validate_delivery_terminal_v2(root, terminal_artifact) == terminal
    assert {path: sha256_file(path) for path in canonical_hashes} == canonical_hashes
