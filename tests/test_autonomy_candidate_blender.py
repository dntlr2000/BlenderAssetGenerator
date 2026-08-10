from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler.autonomy.models import AutonomyBudget, PolicyAuthorization
from codex_blender_modeler.autonomy.planner import plan_autonomous_static_prop
from codex_blender_modeler.autonomy.profiles import build_default_budget
from codex_blender_modeler.autonomy.reporting import validate_review_bundle
from codex_blender_modeler.autonomy.service import advance_autonomy, get_autonomy_status
from codex_blender_modeler.blender_artifacts import native_io_path, sha256_file
from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.handoff.models import DestinationHandoffManifest
from codex_blender_modeler.handoff.service import validate_destination_handoff
from codex_blender_modeler.production import record_delegated_production_step
from codex_blender_modeler.production.models import DelegatedWorkAssignment
from codex_blender_modeler.qa.multiview_sanity import (
    ASSEMBLY_SANITY_VIEW_IDS,
    GeometryMultiviewVisualReview,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AUTONOMY_E2E_SMOKE") != "1",
    reason="set CBM_RUN_AUTONOMY_E2E_SMOKE=1 for the Blender autonomy smoke",
)


def _read_utf8(path: Path) -> str:
    """Read one smoke artifact through an extended-length Windows path."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        return handle.read()


def _write_utf8(path: Path, value: str) -> None:
    """Write one smoke artifact through an extended-length Windows path."""

    with open(native_io_path(path), "w", encoding="utf-8") as handle:
        handle.write(value)


def _reference(path: Path) -> Path:
    """Render one deterministic box-like reference without external assets."""

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (256, 256), (238, 240, 244))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((50, 78, 206, 182), radius=16, fill=(45, 105, 170))
    draw.rectangle((72, 96, 184, 164), fill=(73, 137, 201))
    image.save(path)
    return path


def _ground_truth_reference(path: Path) -> Path:
    """Render the exact known fixture geometry for the package-success smoke path."""

    fixture_root = path.parent / "ground_truth"
    source = fixture_root / "input" / "source.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (238, 240, 244)).save(source)
    spec = {
        "schema_version": "0.2.0",
        "job_id": "aq_ground_truth",
        "mode": "concept",
        "units": "METERS",
        "coordinate_system": {"handedness": "RIGHT", "up": "+Z", "forward": "-Y"},
        "nominal_scene_size": [3.0, 3.0, 2.0],
        "sources": [
            {
                "id": "ref.main",
                "path": "input/source.png",
                "kind": "reference",
                "immutable": True,
                "scale_anchors": [],
            }
        ],
        "materials": [
            {
                "id": "mat.product.blue",
                "name": "Product blue",
                "shader": "principled",
                "base_color": [0.08, 0.34, 0.68, 1.0],
                "roughness": 0.45,
                "metallic": 0.05,
                "emission_strength": 0.0,
                "texture_manifest": None,
            }
        ],
        "objects": [
            {
                "id": "product.body",
                "name": "Box product body",
                "geometry": {
                    "kind": "primitive",
                    "primitive": "cube",
                    "dimensions": [2.0, 0.8, 1.2],
                    "segments": 24,
                    "ring_segments": 12,
                },
                "transform": {
                    "location": [0.0, 0.0, 0.6],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                },
                "material_id": "mat.product.blue",
                "modifiers": [
                    {"kind": "bevel", "width": 0.12, "segments": 3, "limit_method": "ANGLE"}
                ],
                "generator": None,
                "parent_id": None,
                "shade_smooth": False,
                "tags": ["qa_role:primary", "scope:primary"],
                "evidence": [
                    {
                        "source_id": "ref.main",
                        "bbox_norm": [0.19, 0.30, 0.81, 0.72],
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
            "ortho_scale": 3.4,
            "resolution": [256, 256],
        },
        "assumptions": ["Ground-truth smoke fixture."],
        "revision_notes": [],
    }
    spec_path = fixture_root / "analysis" / "scene_spec.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    blend = fixture_root / "blender" / "scene.blend"
    blend.parent.mkdir(parents=True, exist_ok=True)
    run_blender(
        "build_scene.py",
        [
            "--spec",
            str(spec_path),
            "--job-root",
            str(fixture_root),
            "--output",
            str(blend),
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    run_blender("render_preview.py", ["--output", str(path)], blend_file=blend)
    return path


def _author_candidate(root: Path, assignment: dict[str, object]) -> None:
    """Write the exact three controller-owned candidate files for the smoke asset."""

    output_root = root / str(assignment["output_root"])
    camera_set = json.loads(
        (root / str(assignment["camera_hypothesis_set"]["path"])).read_text(
            encoding="utf-8"
        )
    )
    camera_hypothesis = camera_set["hypotheses"][0]
    (output_root / "camera_hypothesis.json").write_text(
        json.dumps(camera_hypothesis, indent=2) + "\n",
        encoding="utf-8",
    )
    modeling_plan = {
        "schema_version": "0.4.0",
        "job_id": root.name,
        "reference_analysis_path": "reference_evidence/runs/aq/reference_evidence.json",
        "camera_solution_path": "reference_evidence/runs/aq/camera_hypothesis_set.json",
        "stage": "authored",
        "objects": [
            {
                "id": "product.body",
                "label": "Box product body",
                "recommended_geometry": "primitive",
                "source_ids": ["ref.main"],
                "bbox_norm": [0.19, 0.30, 0.81, 0.72],
                "observed": True,
                "confidence": 0.9,
                "scope_role": "primary",
                "assembly_role": "root",
                "required_assembly_checks": [],
                "notes": [],
            }
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
            "confidence": 0.7,
            "notes": ["Single-view depth and rear structure remain inferred."],
        },
        "assembly_relationships": [],
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
            "notes": ["Keep the clean product body free of invented panel lines."],
        },
        "surface_details": [],
        "global_notes": ["Single-image hidden depth remains inferred."],
    }
    (output_root / "modeling_plan.json").write_text(
        json.dumps(modeling_plan, indent=2) + "\n",
        encoding="utf-8",
    )
    authorization_path = (
        root
        / "production"
        / "autonomy"
        / str(assignment["session_id"])
        / "root_authorization.json"
    )
    source_path = json.loads(
        authorization_path.read_text(encoding="utf-8")
    )["primary_reference"]["path"]
    scene_spec = {
        "schema_version": "0.2.0",
        "job_id": root.name,
        "mode": "concept",
        "units": "METERS",
        "coordinate_system": {"handedness": "RIGHT", "up": "+Z", "forward": "-Y"},
        "nominal_scene_size": [3.0, 3.0, 2.0],
        "sources": [
            {
                "id": "ref.main",
                "path": source_path,
                "kind": "reference",
                "immutable": True,
                "scale_anchors": [],
            }
        ],
        "materials": [
            {
                "id": "mat.product.blue",
                "name": "Product blue",
                "shader": "principled",
                "base_color": [0.08, 0.34, 0.68, 1.0],
                "roughness": 0.45,
                "metallic": 0.05,
                "emission_strength": 0.0,
                "texture_manifest": None,
            }
        ],
        "objects": [
            {
                "id": "product.body",
                "name": "Box product body",
                "geometry": {
                    "kind": "primitive",
                    "primitive": "cube",
                    "dimensions": [2.0, 0.8, 1.2],
                    "segments": 24,
                    "ring_segments": 12,
                },
                "transform": {
                    "location": [0.0, 0.0, 0.6],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                },
                "material_id": "mat.product.blue",
                "modifiers": [
                    {"kind": "bevel", "width": 0.12, "segments": 3, "limit_method": "ANGLE"}
                ],
                "generator": None,
                "parent_id": None,
                "shade_smooth": False,
                "tags": ["qa_role:primary", "scope:primary"],
                "evidence": [
                    {
                        "source_id": "ref.main",
                        "bbox_norm": [0.19, 0.30, 0.81, 0.72],
                        "status": "observed",
                        "confidence": 0.9,
                    }
                ],
                "editable": {},
            }
        ],
        "camera": {
            "projection": (
                "PERSP"
                if camera_hypothesis["projection"] == "perspective"
                else "ORTHO"
            ),
            "location": [4.0, -7.0, 4.0],
            "target": [0.0, 0.0, 0.5],
            "focal_length_mm": (
                camera_hypothesis["intrinsics"]["focal_length_mm"] or 50.0
            ),
            "ortho_scale": 3.4,
            "resolution": [256, 256],
        },
        "assumptions": ["Back and exact depth are inferred."],
        "revision_notes": [],
    }
    (output_root / "scene_spec.json").write_text(
        json.dumps(scene_spec, indent=2) + "\n",
        encoding="utf-8",
    )


def _complete_multiview_review(root: Path, production: dict[str, object]) -> None:
    """Emulate the Codex controller's bounded five-view review in the Blender smoke."""

    production_state = production["state"]
    assert isinstance(production_state, dict)
    artifact = production_state["current_assignment"]
    assert isinstance(artifact, dict)
    assignment_path = root / str(artifact["path"])
    assignment = DelegatedWorkAssignment.model_validate_json(_read_utf8(assignment_path))
    workflow_plan = json.loads(
        _read_utf8(root / "workflows" / assignment.workflow_id / "plan.json")
    )
    step = next(
        item for item in workflow_plan["steps"] if item["step_id"] == assignment.step_id
    )
    run_id = str(step["parameters"]["run_id"])
    run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
    review = GeometryMultiviewVisualReview(
        job_id=root.name,
        run_id=run_id,
        plan_sha256=sha256_file(run_root / "plan.json"),
        render_manifest_sha256=sha256_file(run_root / "render_manifest.json"),
        structural_report_sha256=sha256_file(run_root / "report.json"),
        reviewed_view_ids=ASSEMBLY_SANITY_VIEW_IDS,
        reviewed_pass_kinds=("beauty", "wireframe"),
        outcome="visually_coherent",
        v04_reentry="not_indicated",
        reviewed_at=datetime.now(UTC),
    )
    _write_utf8(run_root / "visual_review.json", review.model_dump_json(indent=2) + "\n")
    record_delegated_production_step(
        root.name,
        assignment.dispatch_id,
        str(production_state["controller_id"]),
        step_id=assignment.step_id,
        input_fingerprint=assignment.input_fingerprint,
        note="Test controller reviewed every five-view beauty and wireframe pass.",
    )


def _review_only_budget(**kwargs: object) -> AutonomyBudget:
    """Limit one smoke session to a real initial evaluation plus review publication."""

    baseline = build_default_budget(**kwargs)  # type: ignore[arg-type]
    return baseline.model_copy(
        update={
            "initial_candidates": 1,
            "structural_rounds": 0,
            "parametric_convergence_iterations": 0,
            "material_rounds": 0,
            "package_repairs": 0,
            "total_blender_builds": 1,
            "total_quality_evaluations": 1,
            "canonical_promotions": 1,
            "global_action_limit": 3,
        }
    )


def test_initial_candidate_build_qa_and_policy_promotion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Build one real Blender candidate and promote it under an exact policy grant."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    planned = plan_autonomous_static_prop(
        "파란 상자 제품만 engine-neutral GLB로 제작해.",
        reference_path=_reference(tmp_path / "box_reference.png"),
        target_subject="파란 상자 제품",
        job_id="aq_blender_box",
        initial_candidate_limit=1,
    )
    session_id = planned["session_id"]
    advance_autonomy("aq_blender_box", session_id)
    assigned = advance_autonomy("aq_blender_box", session_id)
    assignment = assigned["candidate_assignment"]["assignment"]
    assignment["session_id"] = session_id
    root = workspace / "aq_blender_box"
    _author_candidate(root, assignment)

    evaluated = advance_autonomy("aq_blender_box", session_id)
    candidate_root = root / str(assignment["output_root"])
    candidate_evaluation = json.loads(
        _read_utf8(candidate_root / "candidate_evaluation.json")
    )
    assert candidate_evaluation["metrics"]["hard_gate_failures"] == 0
    assert candidate_evaluation["metrics"]["structural_quality"] == 1.0
    assert candidate_evaluation["metrics"]["material_quality"] is None
    assert candidate_evaluation["metrics"]["production_quality"] is None
    assert candidate_evaluation["evidence_status"] == "scored"
    quality_report = json.loads(
        _read_utf8(candidate_root / "integrated_quality" / "integrated_quality_report.json")
    )
    assert quality_report["outcome"] == "unscorable"
    axes = {item["axis"]: item for item in quality_report["axes"]}
    assert axes["material_fidelity"]["status"] == "unscorable"
    assert axes["production_readiness"]["status"] == "unscorable"
    gates = {item["gate_id"]: item for item in quality_report["hard_gates"]}
    for gate_id in (
        "gate.aq.evidence_binding",
        "gate.aq.build",
        "gate.aq.inspect",
        "gate.aq.validate",
        "gate.aq.required_semantics",
        "gate.aq.finite_transforms",
        "gate.aq.required_assembly",
        "gate.aq.topology_profile",
    ):
        assert gates[gate_id]["status"] == "passed"
    provenance_paths = {
        item["relative_path"] for item in quality_report["provenance"]["artifacts"]
    }
    assert any(path.endswith("assembly_companion_report.json") for path in provenance_paths)
    assert any(path.endswith("topology_companion_report.json") for path in provenance_paths)
    assert evaluated["state"]["next_action"] == "promote_best_candidate"
    promoted = advance_autonomy("aq_blender_box", session_id)
    assert promoted["state"]["next_action"] == "run_structural_round"
    assert (root / "analysis" / "scene_spec.json").is_file()
    assert (root / "analysis" / "modeling_plan.json").is_file()
    grants = list(
        (
            root / "production" / "autonomy" / session_id / "policy_authorizations"
        ).glob("*.json")
    )
    assert len(grants) == 1
    grant = PolicyAuthorization.model_validate_json(grants[0].read_text(encoding="utf-8"))
    assert grant.authorization_source == "preauthorized_profile"
    assert grant.decided_by == "autonomy_policy_engine"
    assert grant.gate_kind == "structural_candidate_promotion"
    assert grant.consumed is True
    assert not list((root / "workflows").glob("*/approvals/*.json"))
    assert get_autonomy_status("aq_blender_box", session_id)["state"]["status"] == (
        "running"
    )


def test_autonomous_static_prop_reaches_one_terminal_delivery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reach a quality-passed GLB, clean import, and package-bound handoff terminal."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    planned = plan_autonomous_static_prop(
        "파란 상자 제품만 engine-neutral GLB로 제작해.",
        reference_path=_ground_truth_reference(tmp_path / "box_reference.png"),
        target_subject="파란 상자 제품",
        job_id="aq_full_box",
        include_destination_handoff_envelope=True,
        initial_candidate_limit=1,
    )
    session_id = str(planned["session_id"])
    advance_autonomy("aq_full_box", session_id)
    assigned = advance_autonomy("aq_full_box", session_id)
    candidate = assigned["candidate_assignment"]["assignment"]
    candidate["session_id"] = session_id
    root = workspace / "aq_full_box"
    _author_candidate(root, candidate)

    status = assigned
    for _index in range(96):
        status = advance_autonomy("aq_full_box", session_id)
        state = status["state"]
        if state["status"] in {"completed", "blocked", "failed", "cancelled"}:
            break
        production_state = status["production"]["state"]
        if production_state["next_action"] == "controller_author":
            assignment_artifact = production_state["current_assignment"]
            assignment = DelegatedWorkAssignment.model_validate_json(
                _read_utf8(root / assignment_artifact["path"])
            )
            if assignment.step_id.endswith("geometry_multiview_visual_review"):
                _complete_multiview_review(root, status["production"])
            elif assignment.step_id not in {
                "reference.analyze",
                "geometry.modeling_plan",
                "geometry.proxy_author",
                "geometry.detail_author",
                "material.author",
            }:
                pytest.fail(f"unexpected controller assignment: {assignment.step_id}")
    assert status["state"]["status"] == "completed"
    assert status["terminal"] is not None
    terminal = status["terminal"]
    assert terminal["status"] == "quality_passed"
    assert terminal["package_manifest"] is not None
    assert terminal["roundtrip_validation"] is not None
    assert terminal["review_bundle_manifest"] is None
    handoff_artifact = terminal["destination_handoff_envelope"]
    assert handoff_artifact is not None
    handoff = DestinationHandoffManifest.model_validate_json(
        _read_utf8(root / handoff_artifact["path"])
    )
    handoff_validation = validate_destination_handoff(
        "aq_full_box",
        profile_id=handoff.profile_id,
        package_id=handoff.package_id,
        handoff_id=handoff.handoff_id,
    )
    assert handoff_validation.ok is True
    assert handoff_validation.handoff_manifest_sha256 == handoff_artifact["sha256"]


def test_autonomous_static_prop_publishes_review_only_bundle_without_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """End a mismatched real-Blender candidate as validated non-production review evidence."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy.planner.build_default_budget",
        _review_only_budget,
    )
    planned = plan_autonomous_static_prop(
        "파란 상자 제품만 engine-neutral GLB로 제작해.",
        reference_path=_reference(tmp_path / "mismatched_reference.png"),
        target_subject="파란 상자 제품",
        job_id="aq_review_box",
        initial_candidate_limit=1,
    )
    session_id = str(planned["session_id"])
    root = workspace / "aq_review_box"

    advance_autonomy("aq_review_box", session_id)
    assigned = advance_autonomy("aq_review_box", session_id)
    candidate = assigned["candidate_assignment"]["assignment"]
    candidate["session_id"] = session_id
    _author_candidate(root, candidate)

    evaluated = advance_autonomy("aq_review_box", session_id)
    assert evaluated["state"]["next_action"] == "promote_best_candidate"
    assert evaluated["remaining_budget"]["total_actions"] == 0
    status = advance_autonomy("aq_review_box", session_id)

    assert status["state"]["status"] == "completed"
    assert status["state"]["terminal_reason"] == "global_budget_exhausted"
    terminal = status["terminal"]
    assert terminal is not None
    assert terminal["status"] == "review_required"
    assert terminal["package_manifest"] is None
    assert terminal["roundtrip_validation"] is None
    assert terminal["destination_handoff_envelope"] is None
    review_artifact = terminal["review_bundle_manifest"]
    assert review_artifact is not None

    bundle_id = f"{session_id[:96]}-review"
    manifest, receipt = validate_review_bundle(root, bundle_id)
    assert manifest.production_ready is False
    assert manifest.destination_handoff_eligible is False
    assert manifest.termination_reason == "global_budget_exhausted"
    assert receipt.production_ready is False
    assert receipt.destination_handoff_eligible is False
    assert receipt.canonical_unchanged is True
    assert review_artifact["sha256"] == sha256_file(
        root / review_artifact["path"]
    )
    assert not list((root / "exports" / "packages").rglob("package_manifest.json"))
    assert not list(root.rglob("roundtrip_validation.json"))
