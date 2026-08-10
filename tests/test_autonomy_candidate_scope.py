from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_blender_modeler.analysis.models import ModelingPlan
from codex_blender_modeler.autonomy.authorization import artifact_for
from codex_blender_modeler.autonomy.candidate_evaluator import (
    _validate_candidate_content_scope,
    _validate_candidate_phase,
)
from codex_blender_modeler.autonomy.models import (
    AutonomyArtifact,
    CandidateAuthoringAssignment,
    RootAuthorization,
)
from codex_blender_modeler.models import SceneSpec


def _plan_payload(job_id: str = "candidate_scope") -> dict[str, object]:
    """Return one valid authored object-only ModelingPlan payload."""

    return {
        "schema_version": "0.4.0",
        "job_id": job_id,
        "reference_analysis_path": "reference_evidence/reference.json",
        "camera_solution_path": "reference_evidence/cameras.json",
        "stage": "authored",
        "objects": [
            {
                "id": "product.body",
                "label": "Main product body",
                "recommended_geometry": "primitive",
                "source_ids": ["ref.main"],
                "bbox_norm": [0.2, 0.2, 0.8, 0.8],
                "observed": True,
                "confidence": 0.9,
                "scope_role": "primary",
                "assembly_role": "root",
                "required_assembly_checks": [],
                "notes": [],
            },
            {
                "id": "product.handle",
                "label": "Attached handle",
                "recommended_geometry": "primitive",
                "source_ids": ["ref.main"],
                "bbox_norm": [0.6, 0.35, 0.8, 0.65],
                "observed": True,
                "confidence": 0.8,
                "scope_role": "supporting",
                "assembly_role": "attached",
                "required_assembly_checks": ["position"],
                "notes": [],
            },
        ],
        "assembly_consistency_policy": "spatial_v1",
        "assembly_frame": {
            "root_object_id": "product.body",
            "longitudinal_axis": "X",
            "lateral_axis": "Y",
            "vertical_axis": "Z",
            "symmetry": "bilateral",
            "evidence_status": "inferred",
            "source_ids": [],
            "confidence": 0.8,
            "notes": [],
        },
        "assembly_relationships": [
            {
                "kind": "center_plane",
                "id": "assembly.handle.center",
                "subject_id": "product.handle",
                "reference_id": "product.body",
                "evidence_status": "inferred",
                "source_ids": [],
                "confidence": 0.7,
                "required": True,
                "tolerance": {"mode": "relative", "value": 0.1},
                "instance_policy": "family_bounds",
                "notes": [],
                "axis": "Z",
            }
        ],
        "surface_detail_policy": {
            "mode": "texture_preferred",
            "default_representation": "texture_channels",
            "prefer_texture_for_repeated_details": True,
            "max_texture_projected_size_px": 128,
            "max_texture_relief_m": 0.01,
            "geometry_required_conditions": [
                "silhouette",
                "structural",
                "gameplay",
                "physical_transparency",
            ],
            "notes": [],
        },
        "surface_details": [],
        "global_notes": [],
    }


def _scene_payload(job_id: str = "candidate_scope") -> dict[str, object]:
    """Return one valid primary-plus-supporting object-only SceneSpec payload."""

    def object_payload(
        object_id: str,
        name: str,
        role: str,
        location: list[float],
    ) -> dict[str, object]:
        """Build one minimal primitive object with an explicit AQ role."""

        return {
            "id": object_id,
            "name": name,
            "geometry": {
                "kind": "primitive",
                "primitive": "cube",
                "dimensions": [1.0, 0.6, 0.8],
                "segments": 12,
                "ring_segments": 8,
            },
            "transform": {
                "location": location,
                "rotation_deg": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            },
            "material_id": "mat.body",
            "modifiers": [],
            "generator": None,
            "parent_id": None,
            "shade_smooth": False,
            "tags": [f"qa_role:{role}", f"scope:{role}"],
            "evidence": [
                {
                    "source_id": "ref.main",
                    "bbox_norm": [0.2, 0.2, 0.8, 0.8],
                    "status": "observed",
                    "confidence": 0.8,
                }
            ],
            "editable": {},
        }

    return {
        "schema_version": "0.2.0",
        "job_id": job_id,
        "mode": "concept",
        "units": "METERS",
        "coordinate_system": {"handedness": "RIGHT", "up": "+Z", "forward": "-Y"},
        "nominal_scene_size": [2.0, 2.0, 2.0],
        "sources": [
            {
                "id": "ref.main",
                "path": "input/reference.png",
                "kind": "reference",
                "immutable": True,
                "scale_anchors": [],
            }
        ],
        "materials": [
            {
                "id": "mat.body",
                "name": "Body",
                "shader": "principled",
                "base_color": [0.2, 0.4, 0.7, 1.0],
                "roughness": 0.5,
                "metallic": 0.0,
                "emission_strength": 0.0,
                "texture_manifest": None,
            }
        ],
        "objects": [
            object_payload("product.body", "Main product body", "primary", [0, 0, 0.4]),
            object_payload("product.handle", "Attached handle", "supporting", [0.7, 0, 0.4]),
        ],
        "camera": {
            "projection": "ORTHO",
            "location": [3.0, -5.0, 3.0],
            "target": [0.0, 0.0, 0.4],
            "focal_length_mm": 50.0,
            "ortho_scale": 3.0,
            "resolution": [128, 128],
        },
        "assumptions": [],
        "revision_notes": [],
    }


def _authorization(root: Path) -> RootAuthorization:
    """Construct the exact root fields consumed by the pure candidate-scope validator."""

    reference = root / "input" / "reference.png"
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_bytes(b"reference-evidence")
    return RootAuthorization.model_construct(
        reference_content_scope="primary_object_only",
        target_subject="portable product",
        primary_reference=artifact_for(root, reference),
        prohibited_scopes=["interior", "external_network_provider"],
    )


def _validate(root: Path, plan: dict[str, object], scene: dict[str, object]) -> None:
    """Parse strict candidate contracts and run the host scope validator."""

    _validate_candidate_content_scope(
        root,
        _authorization(root),
        ModelingPlan.model_validate(plan),
        SceneSpec.model_validate(scene),
    )


def test_accepts_explicit_primary_and_supporting_candidate(tmp_path: Path) -> None:
    """Allow a target object and one structurally attached supporting component."""

    _validate(tmp_path, _plan_payload(), _scene_payload())


def test_rejects_context_object_disguised_as_supporting(tmp_path: Path) -> None:
    """Reject terrain, rocks, and other independent context despite a supporting tag."""

    plan = _plan_payload()
    scene = _scene_payload()
    plan["objects"][1]["id"] = "environment.rocks"
    plan["objects"][1]["label"] = "Background rocks"
    plan["assembly_relationships"][0]["subject_id"] = "environment.rocks"
    scene["objects"][1]["id"] = "environment.rocks"
    scene["objects"][1]["name"] = "Background rocks"
    with pytest.raises(PermissionError, match="contextual terrain"):
        _validate(tmp_path, plan, scene)


def test_rejects_interior_in_static_prop_candidate(tmp_path: Path) -> None:
    """Reject a room namespace because the active AQ profile grants no InteriorScope."""

    plan = _plan_payload()
    scene = _scene_payload()
    plan["objects"][1]["id"] = "product.room"
    plan["objects"][1]["label"] = "Interior room"
    plan["assembly_relationships"][0]["subject_id"] = "product.room"
    scene["objects"][1]["id"] = "product.room"
    scene["objects"][1]["name"] = "Interior room"
    with pytest.raises(PermissionError, match="no InteriorScope authority"):
        _validate(tmp_path, plan, scene)


def test_rejects_external_texture_provider_injection(tmp_path: Path) -> None:
    """Reject an image/provider manifest not produced by the local deterministic provider."""

    plan = _plan_payload()
    scene = _scene_payload()
    manifest_path = tmp_path / "textures" / "remote" / "texture_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.body",
                "uv_set": "Object",
                "intended_scale_m": 1.0,
                "resolution": [64, 64],
                "source_type": "procedural",
                "channels": {
                    "base_color": {"source": "procedural", "strength": 1.0}
                },
                "provenance": {"provider": "remote_image_model"},
            }
        ),
        encoding="utf-8",
    )
    scene["materials"][0]["texture_manifest"] = (
        "textures/remote/texture_manifest.json"
    )
    with pytest.raises(PermissionError, match="external or unverifiable provider"):
        _validate(tmp_path, plan, scene)


def test_refinement_preserves_primary_and_supporting_ids(tmp_path: Path) -> None:
    """Require every baseline subject ID and semantic role in structural refinement."""

    baseline_plan = ModelingPlan.model_validate(_plan_payload())
    baseline_plan_path = tmp_path / "analysis" / "modeling_plan.json"
    baseline_plan_path.parent.mkdir(parents=True)
    baseline_plan_path.write_text(
        baseline_plan.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    baseline_scene = SceneSpec.model_validate(_scene_payload()).model_dump(mode="json")
    candidate_plan_payload = _plan_payload()
    candidate_plan_payload["objects"] = candidate_plan_payload["objects"][:1]
    candidate_plan_payload["assembly_relationships"] = []
    candidate_scene_payload = _scene_payload()
    candidate_scene_payload["objects"] = candidate_scene_payload["objects"][:1]
    candidate_plan = ModelingPlan.model_validate(candidate_plan_payload)
    candidate_scene = SceneSpec.model_validate(candidate_scene_payload)
    assignment = CandidateAuthoringAssignment.model_construct(
        candidate_phase="structural",
        workflow_scene_spec=AutonomyArtifact(
            path="analysis/scene_spec.json",
            sha256="0" * 64,
        ),
        workflow_modeling_plan=artifact_for(tmp_path, baseline_plan_path),
    )
    with pytest.raises(PermissionError, match="primary/supporting IDs"):
        _validate_candidate_phase(
            assignment,
            baseline_scene,
            candidate_plan,
            candidate_scene,
            "1" * 64,
            tmp_path,
        )
