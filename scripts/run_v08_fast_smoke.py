"""Run the V0.8 background-exterior lifecycle in one isolated smoke workspace."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from codex_blender_modeler.background_quality import (
    BackgroundFitReport,
    BackgroundQualityReport,
)
from codex_blender_modeler.optimization import approve_asset_optimization
from codex_blender_modeler.orchestration.service import (
    complete_workflow_step,
    plan_workflow,
    resume_workflow,
)
from codex_blender_modeler.qa.diagnostic_service import (
    validate_qa_diagnostic_bundle,
)
from codex_blender_modeler.qa.multiview_sanity import (
    GeometryMultiviewVisualReview,
    GeometryVisualReviewFinding,
    validate_assembly_sanity_terminal,
)
from codex_blender_modeler.workspace import job_dir, sha256_file


def _step_state(state, step_id: str):
    """Return one current workflow step state or fail with its stable identifier."""

    return next(item for item in state.steps if item.step_id == step_id)


def _load_plan(root: Path, workflow_id: str) -> dict:
    """Load one immutable V0.8 plan from the smoke job."""

    return json.loads(
        (root / "workflows" / workflow_id / "plan.json").read_text(
            encoding="utf-8"
        )
    )


def _author_modeling_plan(root: Path, state, scene_spec_path: Path) -> object:
    """Author a spatial-v1 smoke plan that matches the exact source SceneSpec IDs."""

    scene_spec = json.loads(scene_spec_path.read_text(encoding="utf-8"))
    source_ids = [str(item["id"]) for item in scene_spec["sources"]]
    path = root / "analysis" / "modeling_plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stage"] = "authored"
    payload["objects"] = [
        {
            "id": item["id"],
            "label": item["name"],
            "recommended_geometry": item["geometry"]["kind"],
            "source_ids": source_ids,
            "bbox_norm": [0.0, 0.0, 1.0, 1.0],
            "observed": True,
            "confidence": 1.0,
            "assembly_role": "root" if index == 0 else "free_standing",
            "notes": ["Isolated V0.8 lifecycle smoke fixture."],
        }
        for index, item in enumerate(scene_spec["objects"])
    ]
    payload["assembly_consistency_policy"] = "spatial_v1"
    payload["assembly_frame"] = {
        "root_object_id": scene_spec["objects"][0]["id"],
        "longitudinal_axis": "X",
        "lateral_axis": "Y",
        "vertical_axis": "Z",
        "symmetry": "unknown",
        "evidence_status": "inferred",
        "source_ids": [],
        "confidence": 0.5,
        "notes": ["Test-only inferred assembly frame."],
    }
    payload["assembly_relationships"] = []
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    current = _step_state(state, "geometry.modeling_plan")
    return complete_workflow_step(
        state.job_id,
        state.workflow_id,
        "geometry.modeling_plan",
        input_fingerprint=str(current.input_fingerprint),
        note="Authored isolated smoke modeling plan.",
    )


def _author_scene_spec(root: Path, state, source: Path) -> object:
    """Install one deterministic example SceneSpec and complete exterior authoring."""

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["job_id"] = state.job_id
    output = root / "analysis" / "scene_spec.json"
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    current = _step_state(state, "geometry.background_author")
    return complete_workflow_step(
        state.job_id,
        state.workflow_id,
        "geometry.background_author",
        input_fingerprint=str(current.input_fingerprint),
        note="Authored isolated smoke moderate-detail exterior SceneSpec.",
    )


def _author_geometry_multiview_review(root: Path, state) -> object:
    """Publish honest unscorable smoke evidence after validating the five-view terminal."""

    step_id = "background_geometry.geometry_multiview_visual_review"
    plan = _load_plan(root, state.workflow_id)
    step = next(item for item in plan["steps"] if item["step_id"] == step_id)
    run_id = str(step["parameters"]["run_id"])
    run_root = root / "qa" / "assembly_sanity" / "runs" / run_id
    plan_path = run_root / "plan.json"
    manifest_path = run_root / "render_manifest.json"
    report_path = run_root / "report.json"
    plan_sha256 = sha256_file(plan_path)
    manifest_sha256 = sha256_file(manifest_path)
    report_sha256 = sha256_file(report_path)
    validate_assembly_sanity_terminal(
        root,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        report_path=report_path,
        report_sha256=report_sha256,
        expected_job_id=state.job_id,
        expected_run_id=run_id,
    )
    review = GeometryMultiviewVisualReview(
        job_id=state.job_id,
        run_id=run_id,
        plan_sha256=plan_sha256,
        render_manifest_sha256=manifest_sha256,
        structural_report_sha256=report_sha256,
        reviewed_view_ids=["front", "right", "top", "rear", "oblique"],
        reviewed_pass_kinds=["beauty", "wireframe"],
        outcome="unscorable",
        v04_reentry="not_indicated",
        findings=[
            GeometryVisualReviewFinding(
                finding_id="smoke.image_capable_review_required",
                issue_type="insufficient_evidence",
                severity="warning",
                view_ids=["front", "right", "top", "rear", "oblique"],
                target_ids=[],
                description=(
                    "The automated lifecycle smoke validates exact image files and hashes "
                    "but does not contain an image-capable reviewer."
                ),
                recommended_v04_action="additional_evidence",
            )
        ],
        reviewed_at=datetime.now(UTC),
    )
    output = run_root / "visual_review.json"
    output.write_text(review.model_dump_json(indent=2) + "\n", encoding="utf-8")
    current = _step_state(state, step_id)
    return complete_workflow_step(
        state.job_id,
        state.workflow_id,
        step_id,
        input_fingerprint=str(current.input_fingerprint),
        note=(
            "Validated the exact five-view terminal and recorded an honest unscorable "
            "lifecycle-smoke review that still requires image-capable inspection."
        ),
    )


def _author_material_candidate(root: Path, state) -> object:
    """Mark the workflow-owned local scaffold as one authored V0.5 candidate."""

    plan = _load_plan(root, state.workflow_id)
    step = next(item for item in plan["steps"] if item["step_id"] == "material.author")
    candidate = root / step["parameters"]["candidate_plan_path"]
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["stage"] = "authored"
    payload["global_notes"].append("Authored by isolated V0.8 lifecycle smoke.")
    candidate.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    current = _step_state(state, "material.author")
    return complete_workflow_step(
        state.job_id,
        state.workflow_id,
        "material.author",
        input_fingerprint=str(current.input_fingerprint),
        note="Authored isolated local procedural material candidate.",
    )


def _assert_preview_complete(root: Path, state) -> tuple[str, str]:
    """Validate the bounded fast preview terminal state and exact single QA run."""

    if state.status != "completed" or state.milestone != "delivered_for_review":
        raise RuntimeError(
            f"Fast preview did not complete: {state.status}/{state.current_step_id}"
        )
    plan = _load_plan(root, state.workflow_id)
    qa_step = next(item for item in plan["steps"] if item["step_id"] == "qa.run")
    run_id = str(qa_step["parameters"]["run_id"])
    run_root = root / "qa" / "runs" / run_id
    runs = [item for item in (root / "qa" / "runs").iterdir() if item.is_dir()]
    if runs != [run_root]:
        raise RuntimeError("Fast preview must contain exactly one planned QA run")
    if (run_root / "qa_target_manifest.json").exists() or (run_root / "target").exists():
        raise RuntimeError("Fast preview unexpectedly generated an advisory target")
    pass_manifest = json.loads(
        (run_root / "render_pass_manifest.json").read_text(encoding="utf-8")
    )
    pass_kinds = [item["kind"] for item in pass_manifest["passes"]]
    expected = [
        "beauty",
        "silhouette",
        "object_id",
        "material_id",
        "normal",
        "depth",
        "wireframe",
    ]
    if pass_kinds != expected:
        raise RuntimeError(f"Unexpected QA pass set: {pass_kinds}")
    if state.quality_status not in {"passed", "needs_revision", "unscorable"}:
        raise RuntimeError("Fast preview did not expose one explicit quality outcome")
    if not state.quality_report_path or not state.quality_report_sha256:
        raise RuntimeError("Fast preview did not bind its quality report")
    quality_path = root / state.quality_report_path
    if sha256_file(quality_path) != state.quality_report_sha256:
        raise RuntimeError("Fast preview quality binding is stale")
    quality = BackgroundQualityReport.model_validate_json(
        quality_path.read_text(encoding="utf-8")
    )
    fit_path = root / quality.fit_report_path
    fit = BackgroundFitReport.model_validate_json(
        fit_path.read_text(encoding="utf-8")
    )
    if len(fit.attempts) > 3 or fit.max_refinement_attempts > 2:
        raise RuntimeError("Fast preview exceeded its bounded pre-QA fit budget")
    if quality.qa_run_id != run_id or quality.quality_status != state.quality_status:
        raise RuntimeError("Fast preview quality is not bound to the exact QA run")
    diagnostic_step = next(
        item for item in plan["steps"] if item["step_id"] == "qa.diagnostics"
    )
    diagnostic_id = str(diagnostic_step["parameters"]["diagnostic_id"])
    diagnostic_path = (
        run_root / "diagnostics" / diagnostic_id / "bundle_manifest.json"
    )
    bundle, request, diagnostic = validate_qa_diagnostic_bundle(
        root,
        diagnostic_path,
    )
    diagnostic_state = _step_state(state, "qa.diagnostics")
    if (
        diagnostic_state.status != "complete"
        or bundle.qa_run_id != run_id
        or request.qa_run_id != run_id
        or diagnostic.qa_run_id != run_id
        or diagnostic.advisory_only is not True
    ):
        raise RuntimeError("Fast preview companion diagnostics are incomplete or stale")
    return run_id, quality.quality_status


def _run_portable_continuation(job_id: str, profile_id: str) -> tuple[object, str]:
    """Stop at exact optimization approval, approve the fixture, and finish round trip."""

    state = plan_workflow(
        "Package the completed background exterior using the exact V0.7 review gate.",
        job_id=job_id,
        intent="portable_package",
        execution_policy="background_exterior",
        delivery_scope="portable_package",
        profile_id=profile_id,
        destination_kind="engine_neutral",
    )
    state = resume_workflow(job_id, state.workflow_id, max_host_steps=64)
    if (
        state.status != "waiting_for_approval"
        or state.current_step_id != "portable.plan_approval"
        or state.waiting_gate != "optimization_plan"
    ):
        raise RuntimeError("Portable fast workflow did not stop at exact V0.7 approval")
    root = job_dir(job_id)
    plan = _load_plan(root, state.workflow_id)
    approval_step = next(
        item for item in plan["steps"] if item["step_id"] == "portable.plan_approval"
    )
    run_id = str(approval_step["parameters"]["run_id"])
    review_plan = root / "optimization" / "runs" / run_id / "review_plan.json"
    approve_asset_optimization(
        job_id,
        run_id=run_id,
        plan_sha256=sha256_file(review_plan),
        approval_note="Isolated V0.8 lifecycle smoke approval.",
    )
    state = resume_workflow(job_id, state.workflow_id, max_host_steps=64)
    if state.status != "completed":
        raise RuntimeError(
            f"Portable fast workflow did not complete: {state.status}/{state.current_step_id}"
        )
    package_step = next(
        item for item in plan["steps"] if item["step_id"] == "portable.package"
    )
    return state, str(package_step["parameters"]["package_id"])


def run_fast_smoke(
    job_id: str,
    reference_path: Path,
    scene_spec_path: Path,
    profile_id: str,
) -> dict:
    """Run actual Blender-backed preview and package lifecycle gates."""

    state = plan_workflow(
        "Create one static exterior background preview.",
        job_id=job_id,
        reference_path=reference_path,
        execution_policy="background_exterior",
        delivery_scope="preview_only",
    )
    state = resume_workflow(job_id, state.workflow_id, max_host_steps=1)
    root = job_dir(job_id)
    state = _author_modeling_plan(root, state, scene_spec_path)
    state = _author_scene_spec(root, state, scene_spec_path)
    state = resume_workflow(job_id, state.workflow_id, max_host_steps=64)
    if state.current_step_id == "background_geometry.geometry_multiview_visual_review":
        state = _author_geometry_multiview_review(root, state)
        state = resume_workflow(job_id, state.workflow_id, max_host_steps=64)
    if state.current_step_id != "material.author":
        raise RuntimeError("Fast preview did not stop at material authoring")
    state = _author_material_candidate(root, state)
    state = resume_workflow(job_id, state.workflow_id, max_host_steps=64)
    qa_run_id, quality_status = _assert_preview_complete(root, state)
    preview_workflow_id = state.workflow_id
    portable_state, package_id = _run_portable_continuation(job_id, profile_id)
    return {
        "schema_version": "0.8.0",
        "job_id": job_id,
        "preview_workflow_id": preview_workflow_id,
        "preview_status": "completed",
        "preview_milestone": "delivered_for_review",
        "qa_run_id": qa_run_id,
        "qa_run_count": 1,
        "quality_status": quality_status,
        "standard_workflow_recommended": state.standard_workflow_recommended,
        "pre_qa_fit_max_attempts": 2,
        "generated_target": False,
        "automatic_revision": False,
        "external_provider": False,
        "portable_workflow_id": portable_state.workflow_id,
        "portable_status": portable_state.status,
        "package_id": package_id,
    }


def main() -> int:
    """Parse isolated gate inputs, run the lifecycle, and print its JSON summary."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--scene-spec", type=Path, required=True)
    parser.add_argument(
        "--profile",
        choices=["portable_gltf", "fbx_interchange", "obj_legacy"],
        default="fbx_interchange",
    )
    arguments = parser.parse_args()
    result = run_fast_smoke(
        arguments.job_id,
        arguments.reference.resolve(),
        arguments.scene_spec.resolve(),
        arguments.profile,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
