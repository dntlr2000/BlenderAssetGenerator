"""Opt-in Blender 5 vertical smoke for AQ v2 geometry candidate promotion."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from codex_blender_modeler.autonomy_v2.approval_policy_service import (
    authorize_routine_gate,
    evaluate_routine_gate_eligibility,
    get_applied_policy_decision_receipt,
    plan_approval_envelope,
)
from codex_blender_modeler.autonomy_v2.candidate_validation_models import (
    GeometryAuthoringCompletionV2,
)
from codex_blender_modeler.autonomy_v2.candidate_validation_service import (
    validate_and_promote_geometry_candidate_v2,
)
from codex_blender_modeler.autonomy_v2.controller_bridge import (
    _required_authoring_profile,
    _session_bundle,
    execute_autonomy_v2_controller,
)
from codex_blender_modeler.autonomy_v2.delivery_service import (
    artifact_for_v2,
    write_immutable_v2_model,
)
from codex_blender_modeler.autonomy_v2.models import (
    AutonomyStateV2,
    RootAuthorizationV2,
)
from codex_blender_modeler.autonomy_v2.planner import plan_autonomous_static_prop_v2
from codex_blender_modeler.autonomy_v2.supervisor_service import (
    _controller_validation_boundary,
)
from codex_blender_modeler.autonomy_v2.transitions import transition_state
from codex_blender_modeler.blender_artifacts import sha256_file, write_json_atomic
from codex_blender_modeler.production.controller_executor import (
    FakeControllerForTests,
)
from codex_blender_modeler.production.controller_executor.models import (
    ControllerResult,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE") != "1",
    reason="set CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE=1 for Blender smoke",
)


def _json_bytes(payload: object) -> bytes:
    """Serialize one controller payload exactly as deterministic test output bytes."""

    value = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_json(path: Path, payload: object) -> None:
    """Write one host fixture through the repository's atomic JSON helper."""

    path.parent.mkdir(parents=True, exist_ok=True)
    value = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    write_json_atomic(path, value)


def _reference_analysis(job_id: str, reference_path: str, reference_sha: str) -> dict:
    """Return one minimal strict V0.4 reference-analysis fixture."""

    return {
        "schema_version": "0.4.0",
        "job_id": job_id,
        "provider": "basic",
        "images": [
            {
                "source_id": "ref.main",
                "path": reference_path,
                "sha256": reference_sha,
                "width": 32,
                "height": 32,
                "aspect_ratio": 1.0,
                "color_mode": "RGB",
                "has_alpha": False,
                "content_bbox_norm": [0.05, 0.05, 0.95, 0.95],
                "edge_density": 0.2,
                "bilateral_symmetry_score": 0.8,
                "dominant_colors": [],
                "line_angle_clusters": [],
                "diagnostics": {},
            }
        ],
        "recommended_projection": "ORTHO",
        "projection_confidence": 0.9,
        "reference_type": "orthographic_set",
        "scale_status": "unscaled",
        "assumptions": ["Fixture camera is intentionally underconstrained."],
        "warnings": [],
    }


def _camera_solution(job_id: str) -> dict:
    """Return the exact camera evidence bound by the candidate SceneSpec."""

    return {
        "schema_version": "0.4.0",
        "job_id": job_id,
        "projection": "ORTHO",
        "method": "orthographic_source",
        "focal_length_mm": 50.0,
        "azimuth_deg": 29.7449,
        "elevation_deg": -23.487,
        "roll_deg": 0.0,
        "view_direction": [-4.0, 7.0, -3.5],
        "principal_point_norm": [0.5, 0.5],
        "confidence": 0.9,
        "locked_fields": ["projection", "focal_length_mm"],
        "underconstrained": ["absolute_scale"],
        "assumptions": [],
    }


def _modeling_plan(job_id: str, note: str) -> dict:
    """Return one authored primary-only semantic plan for a structural hull."""

    return {
        "schema_version": "0.4.0",
        "job_id": job_id,
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
        "stage": "authored",
        "objects": [
            {
                "id": "asset.hull",
                "label": "Fixture hull",
                "recommended_geometry": "custom_mesh",
                "source_ids": ["ref.main"],
                "bbox_norm": [0.1, 0.1, 0.9, 0.9],
                "observed": True,
                "confidence": 0.9,
                "scope_role": "primary",
                "assembly_role": "unclassified",
                "required_assembly_checks": [],
                "notes": [note],
            }
        ],
        "assembly_consistency_policy": "legacy_unbound",
        "assembly_frame": None,
        "assembly_relationships": [],
        "surface_detail_policy": None,
        "surface_details": [],
        "global_notes": [note],
    }


def _scene_v03(job_id: str, reference_path: str) -> dict:
    """Return one whitelisted loft with explicit nonlegacy GeometryIntent."""

    return {
        "schema_version": "0.3.0",
        "job_id": job_id,
        "mode": "concept",
        "units": "METERS",
        "coordinate_system": {"handedness": "RIGHT", "up": "+Z", "forward": "-Y"},
        "nominal_scene_size": [4.0, 3.0, 2.5],
        "sources": [
            {
                "id": "ref.main",
                "path": reference_path,
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
                "base_color": [0.25, 0.4, 0.65, 1.0],
                "roughness": 0.5,
                "metallic": 0.05,
                "emission_strength": 0.0,
                "texture_manifest": None,
            }
        ],
        "objects": [
            {
                "id": "asset.hull",
                "name": "Fixture hull",
                "geometry": {
                    "kind": "loft",
                    "sections": [
                        {
                            "closed": True,
                            "points": [
                                [-1.0, -0.6, 0.0],
                                [1.0, -0.6, 0.0],
                                [1.0, 0.6, 0.0],
                                [-1.0, 0.6, 0.0],
                            ],
                        },
                        {
                            "closed": True,
                            "points": [
                                [-0.7, -0.4, 1.2],
                                [0.7, -0.4, 1.2],
                                [0.7, 0.4, 1.2],
                                [-0.7, 0.4, 1.2],
                            ],
                        },
                    ],
                    "resample_count": 4,
                    "cap_policy": "ends",
                    "correspondence_policy": "index",
                    "twist_offsets": [],
                },
                "geometry_intent": {
                    "face_groups": [
                        {"id": "body", "face_indices": list(range(8))}
                    ],
                    "sharp_edges": [{"vertices": [0, 1]}],
                    "crease_edges": [{"vertices": [0, 1], "weight": 0.5}],
                    "bevel_weights": [{"vertices": [1, 5], "weight": 0.25}],
                    "uv_seams": [{"vertices": [0, 1]}],
                    "smoothing_policy": {
                        "mode": "flat",
                        "angle_degrees": 30.0,
                        "keep_sharp": True,
                    },
                    "topology_policy": "static_prop_closed",
                    "subdivision_intent": {
                        "enabled": False,
                        "levels": 0,
                        "boundary_smoothing": "preserve_corners",
                    },
                    "lod_intent": {
                        "preserve_silhouette": True,
                        "protected_face_groups": ["body"],
                        "minimum_triangle_ratio": 0.5,
                    },
                },
                "transform": {
                    "location": [0.0, 0.0, 0.0],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                },
                "material_id": "mat.body",
                "modifiers": [],
                "generator": None,
                "parent_id": None,
                "shade_smooth": False,
                "tags": ["qa_role:primary", "scope:primary"],
                "evidence": [
                    {
                        "source_id": "ref.main",
                        "bbox_norm": [0.1, 0.1, 0.9, 0.9],
                        "status": "observed",
                        "confidence": 0.9,
                    }
                ],
                "editable": {},
            }
        ],
        "camera": {
            "projection": "ORTHO",
            "location": [4.0, -7.0, 4.0],
            "target": [0.0, 0.0, 0.5],
            "focal_length_mm": 50.0,
            "ortho_scale": 4.5,
            "resolution": [128, 128],
        },
        "assumptions": ["Hidden surfaces remain inferred."],
        "revision_notes": [],
    }


def _advance_reference(root: Path, session_id: str) -> None:
    """Advance the planned fixture to its first controller boundary."""

    session_root = root / "production" / "autonomy_v2" / session_id
    state = AutonomyStateV2.model_validate_json(
        (session_root / "states/0000.json").read_bytes()
    )
    authorization = RootAuthorizationV2.model_validate_json(
        (session_root / "root_authorization.json").read_bytes()
    )
    next_state = transition_state(
        state,
        event="reference_ready",
        evidence=authorization.primary_reference,
        created_at=state.created_at,
    )
    write_immutable_v2_model(
        root,
        session_root / "states/0001.json",
        next_state,
    )


def test_geometry_controller_candidate_builds_and_promotes_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bind exact controller, policy, Blender, promotion, and decision evidence."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    source = tmp_path / "candidate-smoke.png"
    Image.new("RGB", (32, 32), (48, 96, 144)).save(source)
    planned = plan_autonomous_static_prop_v2(
        "Create only the fixture hull.",
        reference_path=source,
        target_subject="fixture hull",
        requested_delivery_profiles=["review_only"],
        job_id="aqv2_candidate_smoke",
        allow_disabled_experimental=True,
    )
    session_id = str(planned["session_id"])
    root = workspace / "aqv2_candidate_smoke"
    plan_approval_envelope(
        "aqv2_candidate_smoke",
        session_id,
        approval_mode="autonomous",
        initial_user_request_sha256=str(
            planned["root_authorization"]["original_request_sha256"]  # type: ignore[index]
        ),
        explicit_autonomy_delegation_observed=True,
        allow_disabled_experimental=True,
    )
    session_root = root / "production" / "autonomy_v2" / session_id
    authorization = RootAuthorizationV2.model_validate_json(
        (session_root / "root_authorization.json").read_bytes()
    )
    reference_relative = authorization.primary_reference.path
    reference_sha = sha256_file(root / reference_relative)
    _write_json(
        root / "analysis/reference_analysis.json",
        _reference_analysis("aqv2_candidate_smoke", reference_relative, reference_sha),
    )
    _write_json(
        root / "analysis/camera_solution.json",
        _camera_solution("aqv2_candidate_smoke"),
    )
    _write_json(
        root / "analysis/modeling_plan.json",
        _modeling_plan("aqv2_candidate_smoke", "baseline"),
    )
    _advance_reference(root, session_id)
    root, session_root, plan, budget, _state, _artifact = _session_bundle(
        "aqv2_candidate_smoke",
        session_id,
    )
    profile_artifact = next(
        item
        for item in plan.phase_tool_profiles
        if item.path.endswith("/geometry_authoring.json")
    )
    input_root = session_root / "smoke_inputs"
    _write_json(input_root / "assignment.json", {"phase": "geometry_authoring"})
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
    candidate_modeling_bytes = _json_bytes(
        _modeling_plan("aqv2_candidate_smoke", "candidate")
    )
    scene_v03_bytes = _json_bytes(
        _scene_v03("aqv2_candidate_smoke", reference_relative)
    )
    completion = GeometryAuthoringCompletionV2(
        job_id="aqv2_candidate_smoke",
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=session_id,
        execution_id="exec-0002-geometry_authoring",
        assignment_sha256=assignment.sha256,
        tool_profile_sha256=profile_artifact.sha256,
        outputs=[
            {
                "name": "modeling_plan.json",
                "sha256": hashlib.sha256(candidate_modeling_bytes).hexdigest(),
                "byte_size": len(candidate_modeling_bytes),
            },
            {
                "name": "scene_spec_v03.json",
                "sha256": hashlib.sha256(scene_v03_bytes).hexdigest(),
                "byte_size": len(scene_v03_bytes),
            },
        ],
    )
    controller = FakeControllerForTests(
        payloads={
            "modeling_plan.json": candidate_modeling_bytes,
            "scene_spec_v03.json": scene_v03_bytes,
            "completion.json": _json_bytes(completion),
        }
    )
    result = execute_autonomy_v2_controller(
        "aqv2_candidate_smoke",
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=immutable_inputs,
        controller=controller,
        timeout_seconds=60,
    )
    assert result["result"]["status"] == "completed"
    root, session_root, plan, budget, state, _artifact = _session_bundle(
        "aqv2_candidate_smoke",
        session_id,
    )
    controller_result_artifact = state.provenance[-1]
    controller_result = ControllerResult.model_validate_json(
        (root / controller_result_artifact.path).read_bytes()
    )
    eligibility = evaluate_routine_gate_eligibility(
        "aqv2_candidate_smoke",
        session_id,
        gate_kind="geometry_candidate_promotion",
        exact_target_path=controller_result_artifact.path,
        exact_target_kind="controller-result",
        current_canonical_snapshot_path=authorization.primary_reference.path,
        current_canonical_snapshot_kind="canonical-reference-snapshot",
        dependency_paths=[
            controller_result.request.path,
            controller_result.tool_profile.path,
            *[item.path for item in controller_result.outputs],
        ],
        dependency_kinds=[
            "controller-request",
            "controller-tool-profile",
            *["controller-output" for _item in controller_result.outputs],
        ],
        allow_disabled_experimental=True,
    )
    assert eligibility["eligibility"] == "passed"
    issued = authorize_routine_gate(
        "aqv2_candidate_smoke",
        session_id,
        eligibility_report_path=str(eligibility["report_artifact"]["path"]),  # type: ignore[index]
        allow_disabled_experimental=True,
    )
    policy_authorization_path = str(
        issued["authorization_artifact"]["path"]  # type: ignore[index]
    )
    receipt, receipt_artifact = validate_and_promote_geometry_candidate_v2(
        job_root=root,
        session_root=session_root,
        plan=plan,
        budget=budget,
        state=state,
        authorization=authorization,
        policy_authorization_path=policy_authorization_path,
    )
    assert receipt.status == "passed"
    assert receipt_artifact.kind == "geometry_candidate_validation_receipt"
    assert receipt.candidate_modeling_plan.sha256 == sha256_file(
        root / "analysis/modeling_plan.json"
    )
    assert receipt.compiled_scene_spec.sha256 == sha256_file(
        root / "analysis/scene_spec.json"
    )
    assert receipt.candidate_blend.sha256 == sha256_file(root / "blender/scene.blend")
    assert receipt.geometry_intent_survival in receipt.provenance
    assert receipt.budget_usage_after.initial_candidates == 1
    assert receipt.budget_usage_after.total_blender_builds == 2
    assert receipt.budget_usage_after.canonical_promotions == 1
    policy_decision = get_applied_policy_decision_receipt(
        "aqv2_candidate_smoke",
        session_id,
        policy_authorization_path=policy_authorization_path,
        action_result_path=receipt_artifact.path,
    )
    assert policy_decision["status"] == "applied"
    assert policy_decision["is_user_approval"] is False
    recovered, recovered_artifact = validate_and_promote_geometry_candidate_v2(
        job_root=root,
        session_root=session_root,
        plan=plan,
        budget=budget,
        state=state,
        authorization=authorization,
        policy_authorization_path=policy_authorization_path,
    )
    assert recovered == receipt
    assert recovered_artifact == receipt_artifact

    advanced = _controller_validation_boundary(
        root,
        session_root,
        plan,
        budget,
        state,
        authorization,
        policy_authorization_path=policy_authorization_path,
    )
    assert advanced["outcome"] == "geometry_candidate_validated"
    root, _session_root, plan, _budget, material_boundary, _artifact = _session_bundle(
        "aqv2_candidate_smoke",
        session_id,
    )
    assert material_boundary.next_action == "execute_controller"
    assert material_boundary.provenance[-1] == receipt_artifact
    assert (
        _required_authoring_profile(root, plan, material_boundary)
        == "material_authoring"
    )
