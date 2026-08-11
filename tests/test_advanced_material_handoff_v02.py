"""Focused advisory-only AdvancedMaterialHandoff 0.1.0 tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_blender_modeler.handoff.advanced_material_models import (
    AdvancedMaterialHandoffPlan,
    AdvancedMaterialHandoffRequest,
)
from codex_blender_modeler.handoff.advanced_material_service import (
    destination_channel_mapping,
    generate_advanced_material_handoff_plan,
)
from codex_blender_modeler.material_authoring.models import (
    AdvancedPreviewPolicy,
    CrystalPortableInput,
    ExactArtifact,
    MaterialAuthoringRequest,
    ResolutionSelectorInput,
    ScaleContextBinding,
    UVIdentity,
    UVIdentitySnapshot,
)
from codex_blender_modeler.material_authoring.service import author_material_candidate
from codex_blender_modeler.structural_geometry.models import (
    AssetScaleContext,
    StructuralEvidenceArtifact,
)
from codex_blender_modeler.workspace import sha256_file

NOW = datetime(2026, 8, 11, 3, 0, tzinfo=UTC)


def test_standard_pbr_unity_channel_mappings_remain_explicit_and_advisory() -> None:
    """Cover standard PBR packing semantics for both planned Unity shader families."""

    assert destination_channel_mapping("metallic", "unity_urp") == (
        "_MetallicGlossMap",
        "pack metallic scalar",
        "R",
    )
    assert destination_channel_mapping("roughness", "unity_urp") == (
        "_MetallicGlossMap",
        "invert roughness to smoothness",
        "A",
    )
    assert destination_channel_mapping("occlusion", "unity_hdrp") == (
        "_MaskMap",
        "pack ambient occlusion",
        "G",
    )
    assert destination_channel_mapping("roughness", "unity_hdrp") == (
        "_MaskMap",
        "invert roughness to perceptual smoothness",
        "A",
    )
    assert destination_channel_mapping("emission", "unity_urp")[0] == "_EmissionMap"


def _write_json(path: Path, payload: object) -> None:
    """Write deterministic JSON for one isolated handoff fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _artifact(root: Path, path: Path, artifact_id: str, kind: str) -> ExactArtifact:
    """Bind one isolated JSON file to exact handoff evidence metadata."""

    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=path.relative_to(root).as_posix(),
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
        media_type="application/json",
    )


def _crystal_manifest(root: Path) -> tuple[ExactArtifact, ExactArtifact]:
    """Author one lossy crystal bundle for URP/HDRP advisory planning."""

    scene = root / "analysis" / "scene_spec.json"
    _write_json(scene, {"schema_version": "0.2.0"})
    material = root / "analysis" / "material_plan.json"
    _write_json(material, {"schema_version": "0.5.0"})
    provenance = [
        StructuralEvidenceArtifact(
            role="scene_spec",
            path="analysis/scene_spec.json",
            sha256=sha256_file(scene),
        )
    ]
    context = AssetScaleContext.from_bounds(
        asset_id="crystal.main",
        job_id="crystal_fixture",
        workflow_id="wf-crystal",
        dispatch_id="dispatch-crystal",
        source_fingerprint="a" * 64,
        producer="pytest",
        producer_version="0.1.0",
        provenance=provenance,
        created_at=NOW,
        local_minimum=(0.0, 0.0, 0.0),
        local_maximum=(0.5, 0.2, 0.1),
        assembly_minimum=(0.0, 0.0, 0.0),
        assembly_maximum=(0.5, 0.2, 0.1),
        projected_pixel_size=128.0,
        target_texel_density_px_m=512.0,
    )
    scale_path = root / "production" / "scale_context.json"
    _write_json(scale_path, context.model_dump(mode="json"))
    scale_artifact = _artifact(root, scale_path, "scale-context", "asset-scale-context")
    uv_snapshot = UVIdentitySnapshot(
        semantic_id="crystal.main",
        uv_set="UVMap",
        uv_fingerprint="b" * 64,
        ordered_polygon_corner_count=96,
        texel_density_px_m=512.0,
    )
    uv_path = root / "analysis" / "uv_identity.json"
    _write_json(uv_path, uv_snapshot.model_dump(mode="json"))
    uv = UVIdentity(
        **uv_snapshot.model_dump(mode="python"),
        evidence=_artifact(root, uv_path, "uv-identity", "uv-identity-snapshot"),
    )
    request = MaterialAuthoringRequest(
        request_id="request-crystal",
        job_id="crystal_fixture",
        workflow_id="wf-crystal",
        run_id="crystal-authoring",
        material_id="mat.crystal",
        strategy="crystal_portable_approximation_v1",
        output_root="material_authoring/runs/crystal-authoring",
        source_v05_contracts=[_artifact(root, material, "material-plan", "v05-material-plan")],
        scale_context=ScaleContextBinding(
            artifact=scale_artifact,
            asset_id=context.asset_id,
            source_fingerprint=context.source_fingerprint,
            shortest_dimension_m=context.shortest_dimension_m,
            longest_dimension_m=max(context.assembly_bbox.dimensions()),
            target_texel_density_px_m=context.target_texel_density_px_m,
        ),
        resolution=ResolutionSelectorInput(
            selector_id="selector-crystal",
            material_family="crystal",
            mapping_kind="unique",
            projected_pixel_footprint=128.0,
            target_texel_density_px_m=512.0,
            longest_object_dimension_m=0.5,
            package_budget_bytes=128 * 1024 * 1024,
            requested_pixels=256,
        ),
        preview_policy=AdvancedPreviewPolicy(),
        crystal=CrystalPortableInput(
            ior=1.47,
            transmission=0.91,
            roughness=0.08,
            absorption_tint=(0.1, 0.4, 0.8),
            absorption_distance_m=0.3,
            fresnel_strength=0.85,
            emission_color=(0.0, 0.05, 0.1),
            emission_strength=1.2,
            thickness_approximation_m=0.015,
            opacity_approximation=0.3,
            intended_real_world_scale_m=0.5,
            uv_identity=uv,
        ),
        created_at=NOW,
    )
    receipt = author_material_candidate(root, request)
    receipt_path = (
        root / "material_authoring/runs/crystal-authoring/material_authoring_receipt.json"
    )
    return receipt.manifest, _artifact(
        root,
        receipt_path,
        "receipt-crystal-authoring",
        "material-authoring-receipt",
    )


def test_unity_urp_and_hdrp_plans_are_advisory_and_preserve_losses(tmp_path: Path) -> None:
    """Generate both Unity-family plans without writing or claiming destination parity."""

    root = tmp_path / "job"
    root.mkdir()
    manifest, authoring_receipt = _crystal_manifest(root)
    for target in ("unity_urp", "unity_hdrp"):
        plan_id = f"plan-{target.replace('_', '-')}"
        request = AdvancedMaterialHandoffRequest(
            request_id=f"request-{target.replace('_', '-')}",
            plan_id=plan_id,
            job_id="crystal_fixture",
            material_authoring_manifest=manifest,
            material_authoring_receipt=authoring_receipt,
            destination_target=target,
            destination_hint="Unity project version and pipeline remain unverified",
            output_root=f"exports/advanced_material_handoffs/{plan_id}",
            created_at=NOW,
        )
        receipt = generate_advanced_material_handoff_plan(root, request)
        plan = AdvancedMaterialHandoffPlan.model_validate_json(
            (root / receipt.plan.path).read_bytes()
        )
        assert plan.status == "advisory_plan"
        assert plan.destination_write_performed is False
        assert plan.engine_execution_performed is False
        assert plan.runtime_parity_verified is False
        assert plan.contract.preferred_shader_family == (
            "Shader Graph required for transmission intent"
        )
        assert plan.contract.ior == 1.47
        assert plan.contract.transmission == 0.91
        assert plan.contract.thickness_m == 0.015
        assert plan.contract.double_sided_intent is None
        assert plan.contract.approximation_policy == "custom_shader_reconstruction_required"
        assert "runtime parity remains unverified" in plan.known_limitations
        assert all(item.advisory_only for item in plan.contract.raw_pbr_channel_mapping)
        assert receipt.destination_write_performed is False
    assert not (root / "Assets").exists()
    assert not (root / "Packages").exists()


def test_advanced_handoff_rejects_changed_authored_channel(tmp_path: Path) -> None:
    """Fail closed when a run-owned raw channel changes after the authoring receipt."""

    root = tmp_path / "job"
    root.mkdir()
    manifest_artifact, authoring_receipt = _crystal_manifest(root)
    manifest = json.loads((root / manifest_artifact.path).read_text(encoding="utf-8"))
    channel_path = root / manifest["channels"][0]["artifact"]["path"]
    channel_path.write_bytes(b"tampered")
    request = AdvancedMaterialHandoffRequest(
        request_id="request-stale-urp",
        plan_id="plan-stale-urp",
        job_id="crystal_fixture",
        material_authoring_manifest=manifest_artifact,
        material_authoring_receipt=authoring_receipt,
        destination_target="unity_urp",
        output_root="exports/advanced_material_handoffs/plan-stale-urp",
        created_at=NOW,
    )
    with pytest.raises(ValueError, match="(?:size|hash) changed"):
        generate_advanced_material_handoff_plan(root, request)
    assert not (root / request.output_root).exists()
