"""Immutable step-plan construction for routed V0.8 workflows."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import PurePosixPath

from .models import (
    ArtifactRequirement,
    IntentRouting,
    WorkflowPlan,
    WorkflowRequest,
    WorkflowScope,
    WorkflowStep,
)


def _artifact(
    artifact_id: str,
    path: str,
    *,
    source_path: str | None = None,
    lifecycle: str = "canonical",
    acceptance: str = "exists",
    canonical: bool = False,
) -> ArtifactRequirement:
    """Create one concise artifact requirement for an immutable workflow plan."""

    return ArtifactRequirement(
        artifact_id=artifact_id,
        path=path,
        source_path=source_path,
        lifecycle=lifecycle,  # type: ignore[arg-type]
        acceptance=acceptance,  # type: ignore[arg-type]
        canonical=canonical,
    )


def _step(
    step_id: str,
    title: str,
    phase: str,
    mode: str,
    *,
    tool: str | None = None,
    depends_on: list[str] | None = None,
    outputs: list[ArtifactRequirement] | None = None,
    gate: str | None = None,
    parameters: dict[str, str | int | float | bool] | None = None,
    instructions: list[str] | None = None,
) -> WorkflowStep:
    """Create one validated plan step while keeping templates readable."""

    return WorkflowStep(
        step_id=step_id,
        title=title,
        phase=phase,  # type: ignore[arg-type]
        execution_mode=mode,  # type: ignore[arg-type]
        tool_name=tool,
        depends_on=depends_on or [],
        outputs=outputs or [],
        approval_gate=gate,  # type: ignore[arg-type]
        parameters=parameters or {},
        instructions=instructions or [],
    )


def _reference_content_instructions(request: WorkflowRequest) -> list[str]:
    """Translate one immutable content-scope selection into agent authoring rules."""

    if request.reference_content_scope == "primary_object_only":
        return [
            (
                f"Model only target_subject={request.target_subject!r} and components "
                "structurally belonging to that subject."
            ),
            (
                "Exclude independent terrain, ground planes, vegetation, rocks, props, "
                "backdrops, atmospheric effects, and other surrounding scene context."
            ),
            (
                "ModelingPlan objects must declare scope_role=primary or supporting; "
                "SceneSpec objects must declare qa_role:primary or qa_role:supporting."
            ),
        ]
    return [
        (
            "reference_content_scope=full_reference permits relevant visible context; "
            "keep primary, supporting, decorative, and ground/background roles explicit."
        )
    ]


def _assembly_consistency_instructions() -> list[str]:
    """Return shared single-view rules for parent-local three-dimensional assembly intent."""

    return [
        (
            "Author assembly_consistency_policy=spatial_v1 with one explicit assembly_frame "
            "and parent-local relationships for structural or functional components."
        ),
        (
            "For manufactured or bilaterally symmetric assets, classify functional parts "
            "with center_plane, coaxial, bbox_containment, or surface_contact intent as "
            "applicable; "
            "examples include triggers, levers, handles, and wheels, but never infer policy "
            "from an object name alone."
        ),
        (
            "For elongated or directional attached parts, add signed 3D axis_alignment "
            "relations and axis_clearance where separation along an assembly axis matters. "
            "Use two feasible non-collinear directed axis relations when a full facing "
            "orientation must be constrained; a 2D silhouette axis cannot prove 180-degree "
            "facing."
        ),
        (
            "Every attached object must list its mandatory check categories in "
            "required_assembly_checks (`position`, `axis`, `orientation`, or `clearance`) "
            "so a missing supporting relation fails closed instead of silently disappearing."
        ),
        (
            "Use side_specific placement only when an orthogonal/multiview/blueprint source or "
            "an explicit user-authored requirement establishes that side. Visibility in one "
            "side or oblique image is not hidden-depth side evidence; otherwise a bilateral "
            "manufactured functional part defaults to inferred center_plane or coaxial intent."
        ),
        (
            "Record evidence_status and confidence on the assembly frame and every relationship; "
            "observed or measured evidence must name the exact SceneSpec source IDs, while an "
            "inferred hidden-axis assumption must remain explicitly inferred."
        ),
        (
            "Do not copy a component's 2D screen offset into a hidden depth or lateral axis. "
            "Plan attachment, center plane, axial alignment, containment, and contact in the "
            "declared parent-local assembly frame."
        ),
    ]


def _scene_assembly_instructions() -> list[str]:
    """Return SceneSpec authoring rules that preserve the ModelingPlan assembly contract."""

    return [
        (
            "Preserve the ModelingPlan assembly_frame, every relationship ID, subject/reference "
            "ID, "
            "evidence status, and confidence; do not silently drop or reinterpret them."
        ),
        (
            "Satisfy each spatial_v1 relationship in the declared parent-local frame, "
            "including center_plane, coaxial, bbox_containment, surface_contact, and evidenced "
            "side_specific placement, plus signed axis_alignment and axis_clearance when "
            "declared. Preserve every object's required_assembly_checks membership."
        ),
        (
            "Never copy a reference-image screen-space offset into an unobserved SceneSpec "
            "depth/lateral coordinate. Keep hidden-axis placement inferred and structurally "
            "coherent with its parent."
        ),
    ]


def _append_build_cycle(
    steps: list[WorkflowStep],
    dependency: str,
    prefix: str,
) -> str:
    """Append deterministic build, render, inspect, and validation steps."""

    build_id = f"{prefix}.build"
    render_id = f"{prefix}.render"
    inspect_id = f"{prefix}.inspect"
    validate_id = f"{prefix}.validate"
    steps.extend(
        [
            _step(
                build_id,
                "Build canonical Blender scene",
                "geometry",
                "host",
                tool="build_scene",
                depends_on=[dependency],
                outputs=[_artifact(f"{prefix}.blend", "blender/scene.blend")],
            ),
            _step(
                render_id,
                "Render fixed comparison preview",
                "geometry",
                "host",
                tool="render_preview",
                depends_on=[build_id],
                outputs=[_artifact(f"{prefix}.preview", "renders/preview.png")],
            ),
            _step(
                inspect_id,
                "Inspect semantic scene inventory",
                "geometry",
                "host",
                tool="inspect_scene",
                depends_on=[build_id],
                outputs=[
                    _artifact(
                        f"{prefix}.inventory",
                        "reports/scene_inventory.json",
                        acceptance="valid_json",
                    )
                ],
            ),
            _step(
                validate_id,
                "Validate SceneSpec and Blender output",
                "geometry",
                "host",
                tool="validate_scene",
                depends_on=[render_id, inspect_id],
                outputs=[
                    _artifact(
                        f"{prefix}.validation",
                        "reports/validation.json",
                        acceptance="json_ok",
                    )
                ],
            ),
        ]
    )
    return validate_id


def _append_pdf_report(
    steps: list[WorkflowStep],
    dependency: str,
    prefix: str,
    scope: str,
    *,
    parameters: dict[str, str | int | float | bool] | None = None,
) -> str:
    """Append one human-readable PDF and hash manifest before a review gate."""

    step_id = f"{prefix}.report"
    output_path = f"reports/pdf/{prefix}_report.pdf"
    manifest_path = f"reports/pdf/{prefix}_report.manifest.json"
    report_parameters = {"scope": scope, "output_path": output_path}
    report_parameters.update(parameters or {})
    phase = {
        "build": "geometry",
        "material": "material",
        "qa": "qa",
        "export": "portable",
        "full": "qa",
    }[scope]
    steps.append(
        _step(
            step_id,
            f"Generate {scope} PDF review",
            phase,
            "host",
            tool="generate_pdf_report",
            depends_on=[dependency],
            outputs=[
                _artifact(f"{prefix}.report.pdf", output_path),
                _artifact(
                    f"{prefix}.report.manifest",
                    manifest_path,
                    acceptance="valid_json",
                ),
            ],
            parameters={**report_parameters, "require_new_output": True},
        )
    )
    return step_id


def _geometry_multiview_run_id(workflow_id: str, prefix: str) -> str:
    """Return one deterministic run ID for a workflow-owned V0.4 geometry review."""

    digest = hashlib.sha256(f"{workflow_id}\0{prefix}".encode()).hexdigest()[:12]
    return f"v08-{digest}-{prefix}-geometry"


def _append_geometry_multiview_review(
    steps: list[WorkflowStep],
    dependency: str,
    *,
    workflow_id: str,
    prefix: str,
) -> tuple[str, str]:
    """Append exact five-view renders plus a Codex visual reading of their geometry."""

    run_id = _geometry_multiview_run_id(workflow_id, prefix)
    run_root = f"qa/assembly_sanity/runs/{run_id}"
    step_id = f"{prefix}.geometry_multiview"
    pass_outputs = [
        _artifact(
            f"{prefix}.geometry_multiview.{view_id}.{kind}",
            f"{run_root}/views/{view_id}/{kind}.png",
            lifecycle="immutable_run",
        )
        for view_id in ("front", "right", "top", "rear", "oblique")
        for kind in ("beauty", "silhouette", "object_id", "wireframe")
    ]
    steps.append(
        _step(
            step_id,
            "Review exterior geometry from five temporary cameras",
            "geometry",
            "host",
            tool="run_geometry_multiview_review",
            depends_on=[dependency],
            outputs=[
                _artifact(
                    f"{prefix}.geometry_multiview.plan",
                    f"{run_root}/plan.json",
                    acceptance="valid_json",
                    lifecycle="immutable_run",
                ),
                _artifact(
                    f"{prefix}.geometry_multiview.manifest",
                    f"{run_root}/render_manifest.json",
                    acceptance="valid_json",
                    lifecycle="immutable_run",
                ),
                _artifact(
                    f"{prefix}.geometry_multiview.report",
                    f"{run_root}/report.json",
                    acceptance="valid_json",
                    lifecycle="immutable_run",
                ),
                *pass_outputs,
            ],
            parameters={
                "run_id": run_id,
                "resolution": 384,
                "review_policy": "exterior_geometry_review_v2",
            },
            instructions=[
                "Use temporary front, right, top, rear, and oblique cameras only.",
                "Treat side and rear reference similarity as unscorable unless separately "
                "calibrated per-view evidence exists.",
                "Record structural findings and a manual-only V0.4 re-entry recommendation; "
                "never authorize or apply a geometry revision from this step.",
            ],
        )
    )
    visual_step_id = f"{prefix}.geometry_multiview_visual_review"
    steps.append(
        _step(
            visual_step_id,
            "Visually inspect all five geometry-review views",
            "geometry",
            "agent",
            tool="review_geometry_multiview",
            depends_on=[step_id],
            outputs=[
                _artifact(
                    f"{prefix}.geometry_multiview.visual_review",
                    f"{run_root}/visual_review.json",
                    acceptance="valid_json",
                    lifecycle="immutable_run",
                )
            ],
            parameters={"run_id": run_id},
            instructions=[
                "Read front, right, top, rear, and oblique beauty and wireframe images; "
                "do not infer that merely generating them constitutes visual inspection.",
                "Check cross-view shape coherence, proportions, orientation, assembly, and "
                "obvious topology artifacts for the primary/supporting geometry.",
                "Write GeometryMultiviewVisualReview 0.6.0 bound to the exact plan, render "
                "manifest, and structural-report SHA-256 values.",
                "Reference likeness outside the calibrated canonical reference camera remains "
                "unscorable; do not invent side/rear similarity or authorize a revision.",
                "Recommend bounded V0.4 revision or manual redesign review when appropriate.",
            ],
        )
    )
    return visual_step_id, run_id


def _bind_revision_modeling_plan_contract(
    steps: list[WorkflowStep],
    *,
    modeling_plan_sha256: str,
    assembly_consistency_policy: str,
) -> None:
    """Bind every post-approval revision step to one exact ModelingPlan contract."""

    binding = {
        "expected_modeling_plan_sha256": modeling_plan_sha256,
        "expected_assembly_consistency_policy": assembly_consistency_policy,
    }
    for index, step in enumerate(steps):
        if not step.step_id.startswith("revision.") or step.step_id in {
            "revision.author",
            "revision.approval",
            "revision.promotion_approval",
        }:
            continue
        steps[index] = step.model_copy(update={"parameters": {**step.parameters, **binding}})


def _append_candidate_review_revision_flow(
    steps: list[WorkflowStep],
    request: WorkflowRequest,
    *,
    assembly_consistency_policy: str,
) -> str:
    """Append isolated evaluation and one final exact promotion approval for revisions."""

    trial_id = f"cr-{request.workflow_id[-16:]}"
    plan_path = f"workflows/{request.workflow_id}/artifacts/r/revision_plan.json"
    trial_root = f"qa/candidate_reviews/{trial_id}"
    instructions = (
        [
            (
                "Preserve every current spatial_v1 assembly relationship and parent-local "
                "placement unless the user's exact request explicitly targets it."
            ),
            (
                "Author only bounded existing-object transform or parametric geometry edits; "
                "camera, materials, semantic membership, custom-mesh vertices, and redesign "
                "work are outside candidate_review."
            ),
            (
                "The plan is evaluated in a workflow-owned candidate. Do not write the "
                "canonical SceneSpec or analysis/revision_plan.json."
            ),
        ]
        if assembly_consistency_policy == "spatial_v1"
        else [
            (
                "The exact source ModelingPlan is legacy_unbound. Preserve stable semantic "
                "IDs and author only bounded existing-object parametric edits."
            ),
            (
                "The plan is evaluated in a workflow-owned candidate. Do not write the "
                "canonical SceneSpec or analysis/revision_plan.json."
            ),
        ]
    )
    steps.extend(
        [
            _step(
                "revision.author",
                "Author workflow-owned candidate RevisionPlan",
                "geometry",
                "agent",
                tool="author_revision_plan",
                outputs=[
                    _artifact(
                        "revision.candidate_plan",
                        plan_path,
                        acceptance="valid_json",
                        lifecycle="immutable_run",
                    )
                ],
                instructions=instructions,
            ),
            _step(
                "revision.evaluate",
                "Build and compare isolated baseline and revision candidate",
                "qa",
                "host",
                tool="evaluate_candidate_revision",
                depends_on=["revision.author"],
                outputs=[
                    _artifact(
                        "revision.candidate_decision",
                        f"{trial_root}/decision_manifest.json",
                        acceptance="valid_json",
                        lifecycle="immutable_run",
                    ),
                    _artifact(
                        "revision.candidate_report",
                        f"{trial_root}/candidate_review_report.pdf",
                        lifecycle="immutable_run",
                    ),
                    _artifact(
                        "revision.candidate_report_manifest",
                        f"{trial_root}/candidate_review_report.manifest.json",
                        acceptance="valid_json",
                        lifecycle="immutable_run",
                    ),
                ],
                parameters={
                    "trial_id": trial_id,
                    "revision_plan_path": plan_path,
                    "minimum_improvement": 0.001,
                    "require_new_output": True,
                },
            ),
            _step(
                "revision.promotion_approval",
                "Approve exact candidate-review promotion decision",
                "qa",
                "specialized_approval",
                depends_on=["revision.evaluate"],
                outputs=[
                    _artifact(
                        "revision.candidate_approval",
                        f"{trial_root}/promotion_approval.json",
                        acceptance="valid_json",
                        lifecycle="immutable_run",
                    )
                ],
                gate="visual_revision",
                parameters={"trial_id": trial_id},
                instructions=[
                    (
                        "Show the exact decision_manifest.json SHA-256, before/after direct "
                        "score, silhouette, constraints, changed IDs, blockers, and the "
                        "derived candidate_review_report.pdf."
                    ),
                    (
                        "Only one exact approval is required here; internal plan and build "
                        "fingerprints remain machine-verified and are not separate user gates."
                    ),
                ],
            ),
            _step(
                "revision.promote",
                "Promote approved candidate and rebuild canonical authoring outputs",
                "geometry",
                "host",
                tool="promote_candidate_revision",
                depends_on=["revision.promotion_approval"],
                outputs=[
                    _artifact(
                        "revision.promoted_scene_spec",
                        "analysis/scene_spec.json",
                        acceptance="valid_json",
                        canonical=True,
                    ),
                    _artifact(
                        "revision.promoted_blend",
                        "blender/scene.blend",
                    ),
                    _artifact(
                        "revision.promoted_inventory",
                        "reports/scene_inventory.json",
                        acceptance="valid_json",
                    ),
                    _artifact(
                        "revision.promoted_validation",
                        "reports/validation.json",
                        acceptance="valid_json",
                    ),
                    _artifact(
                        "revision.promotion_receipt",
                        f"{trial_root}/promotion_receipt.json",
                        acceptance="valid_json",
                        lifecycle="immutable_run",
                    ),
                ],
                parameters={"trial_id": trial_id, "require_new_output": True},
            ),
        ]
    )
    return "revision.promote"


def _append_proxy_flow(
    steps: list[WorkflowStep],
    dependency: str,
    request: WorkflowRequest,
) -> str:
    """Append analysis, proxy authoring, deterministic build, and user approval."""

    content_instructions = _reference_content_instructions(request)
    steps.extend(
        [
            _step(
                "reference.analyze",
                "Analyze immutable reference evidence",
                "analysis",
                "host",
                tool="analyze_reference",
                depends_on=[dependency],
                outputs=[
                    _artifact(
                        "reference.analysis",
                        "analysis/reference_analysis.json",
                        acceptance="valid_json",
                        canonical=True,
                    ),
                    _artifact(
                        "reference.camera",
                        "analysis/camera_solution.json",
                        acceptance="valid_json",
                        canonical=True,
                    ),
                ],
            ),
            _step(
                "geometry.modeling_plan",
                "Author semantic modeling plan",
                "analysis",
                "agent",
                tool="author_modeling_plan",
                depends_on=["reference.analyze"],
                outputs=[
                    _artifact(
                        "geometry.modeling_plan.output",
                        "analysis/modeling_plan.json",
                        acceptance="valid_json",
                        canonical=True,
                    )
                ],
                instructions=[
                    "Use deterministic reference diagnostics as evidence, not recovered truth.",
                    "Record observed and inferred objects with stable semantic IDs.",
                    "Classify small surface-attached marks before geometry authoring: route "
                    "non-structural windows, seams, labels, rivets, and repeated shallow detail "
                    "to surface_details; keep silhouette, structural, transparent, or "
                    "gameplay-relevant parts in objects.",
                    "Route a mark to a textured surface_detail only when its parent object, "
                    "target material, observed reference region, and stable UV placement can "
                    "be represented. Otherwise mark it omitted with an explicit reason instead "
                    "of authoring a whole-material pattern.",
                    "A generic semantic label never authorizes invented panel lines, seams, "
                    "grooves, scratches, or other repeated marks outside observed evidence.",
                    *_assembly_consistency_instructions(),
                    *content_instructions,
                ],
                parameters={
                    "require_surface_detail_policy": True,
                    "require_assembly_consistency_policy": True,
                },
            ),
            _step(
                "geometry.proxy_author",
                "Author proxy SceneSpec",
                "geometry",
                "agent",
                tool="author_proxy_scene_spec",
                depends_on=["geometry.modeling_plan"],
                outputs=[
                    _artifact(
                        "geometry.proxy_scene_spec",
                        "analysis/scene_spec.json",
                        acceptance="valid_json",
                        canonical=True,
                    )
                ],
                instructions=[
                    "Do not create interiors without an exact approved InteriorScope.",
                    "Stop at major silhouette, proportions, and semantic decomposition.",
                    "Do not create SceneSpec objects for IDs routed through surface_details.",
                    *_scene_assembly_instructions(),
                    *content_instructions,
                ],
            ),
        ]
    )
    validated = _append_build_cycle(steps, "geometry.proxy_author", "proxy")
    reviewed, review_run_id = _append_geometry_multiview_review(
        steps,
        validated,
        workflow_id=request.workflow_id,
        prefix="proxy",
    )
    report = _append_pdf_report(
        steps,
        reviewed,
        "proxy",
        "build",
        parameters={"assembly_sanity_run_id": review_run_id},
    )
    steps.append(
        _step(
            "geometry.proxy_approval",
            "Approve exact proxy evidence",
            "geometry",
            "approval",
            depends_on=[report],
            gate="proxy_geometry",
            instructions=[
                "Approval binds the current SceneSpec, preview, inventory, and validation hashes."
            ],
        )
    )
    return "geometry.proxy_approval"


def _append_background_geometry_flow(
    steps: list[WorkflowStep],
    dependency: str,
    *,
    request: WorkflowRequest,
    max_fit_attempts: int,
) -> str:
    """Append bounded exterior authoring plus one workflow-owned pre-QA fit."""

    workflow_id = request.workflow_id
    content_instructions = _reference_content_instructions(request)
    geometry_root = f"workflows/{workflow_id}/artifacts/g"
    initial_candidate = f"{geometry_root}/initial_scene_spec.json"
    fit_root = f"{geometry_root}/fit"
    promoted_snapshot = f"{geometry_root}/promoted_scene_spec.json"

    steps.extend(
        [
            _step(
                "reference.analyze",
                "Analyze immutable background reference evidence",
                "analysis",
                "host",
                tool="analyze_reference",
                depends_on=[dependency],
                outputs=[
                    _artifact(
                        "reference.analysis",
                        "analysis/reference_analysis.json",
                        acceptance="valid_json",
                        canonical=True,
                    ),
                    _artifact(
                        "reference.camera",
                        "analysis/camera_solution.json",
                        acceptance="valid_json",
                        canonical=True,
                    ),
                ],
            ),
            _step(
                "geometry.modeling_plan",
                "Author bounded exterior modeling plan",
                "analysis",
                "agent",
                tool="author_modeling_plan",
                depends_on=["reference.analyze"],
                outputs=[
                    _artifact(
                        "geometry.modeling_plan.output",
                        "analysis/modeling_plan.json",
                        acceptance="valid_json",
                        canonical=True,
                    )
                ],
                instructions=[
                    "Plan one static exterior background asset with stable semantic IDs.",
                    "Record hidden geometry as inferred and never create an interior.",
                    "Route non-structural surface-attached micro-detail to surface_details "
                    "instead of one mesh per mark; keep geometry-worthy parts in objects.",
                    "Use a textured surface_detail only when the parent object, target "
                    "material, observed reference region, and stable UV placement can be "
                    "represented; otherwise omit it explicitly rather than inventing a "
                    "whole-material pattern.",
                    "A generic semantic label never authorizes unobserved repeated panels, "
                    "seams, grooves, scratches, or lines.",
                    *_assembly_consistency_instructions(),
                    *content_instructions,
                    "If measured, rigged, interactive, or high-ambiguity work is required, "
                    "stop and report requires_standard_workflow without recording completion.",
                ],
                parameters={
                    "require_surface_detail_policy": True,
                    "require_assembly_consistency_policy": True,
                },
            ),
            _step(
                "geometry.background_author",
                "Author moderate-detail background exterior SceneSpec",
                "geometry",
                "agent",
                tool="author_background_exterior_scene_spec",
                depends_on=["geometry.modeling_plan"],
                outputs=[
                    _artifact(
                        "geometry.background_scene_spec",
                        initial_candidate,
                        source_path="analysis/scene_spec.json",
                        lifecycle="workflow_snapshot",
                        acceptance="valid_json",
                    )
                ],
                instructions=[
                    "Create one bounded moderate-detail exterior pass, not a rough proxy.",
                    "Prioritize silhouette, proportions, and medium structures over micro-detail.",
                    "Do not create SceneSpec objects for IDs routed through surface_details.",
                    "Assign one appropriate qa_role:primary, qa_role:supporting, "
                    "qa_role:decorative, or qa_role:ground_background tag to each object; "
                    "primary_object_only requires an explicit role on every object.",
                    *_scene_assembly_instructions(),
                    *content_instructions,
                    "Do not create interiors, rigs, animation, gameplay logic, or "
                    "engine-specific geometry.",
                    "If the evidence no longer qualifies for the fast lane, stop and report "
                    "requires_standard_workflow without recording completion.",
                ],
            ),
            _step(
                "background.fit",
                "Run bounded primary-subject pre-QA fit",
                "geometry",
                "host",
                tool="fit_background_exterior",
                depends_on=["geometry.background_author"],
                outputs=[
                    _artifact(
                        "background.fit.evidence",
                        fit_root,
                        acceptance="nonempty_directory",
                        lifecycle="immutable_run",
                    ),
                    _artifact(
                        "background.fit.promoted_scene_spec",
                        promoted_snapshot,
                        source_path="analysis/scene_spec.json",
                        lifecycle="workflow_snapshot",
                        acceptance="valid_json",
                    ),
                ],
                parameters={
                    "initial_candidate_path": initial_candidate,
                    "fit_root": fit_root,
                    "max_attempts": max_fit_attempts,
                },
                instructions=[
                    "Render low-resolution primary-only diagnostics for at most two refinements.",
                    "Promote only a strictly validated improvement; retain baseline otherwise.",
                    "This is not the canonical seven-pass V0.6 QA run.",
                ],
            ),
        ]
    )
    validated = _append_build_cycle(
        steps,
        "background.fit",
        "background_geometry",
    )
    reviewed, review_run_id = _append_geometry_multiview_review(
        steps,
        validated,
        workflow_id=request.workflow_id,
        prefix="background_geometry",
    )
    return _append_pdf_report(
        steps,
        reviewed,
        "background_geometry",
        "build",
        parameters={"assembly_sanity_run_id": review_run_id},
    )


def _append_detail_flow(
    steps: list[WorkflowStep],
    dependency: str,
    request: WorkflowRequest,
) -> str:
    """Append one agent-authored detail pass and a separately approved result."""

    steps.append(
        _step(
            "geometry.detail_author",
            "Author approved-scope detailed geometry",
            "geometry",
            "agent",
            tool="author_detailed_scene_spec",
            depends_on=[dependency],
            outputs=[
                _artifact(
                    "geometry.detail_scene_spec",
                    "analysis/scene_spec.json",
                    acceptance="valid_json",
                    canonical=True,
                )
            ],
            instructions=[
                "Archive the previous SceneSpec before canonical replacement.",
                "Preserve camera, stable IDs, assembly relationships, and every unrequested "
                "property.",
                *_scene_assembly_instructions(),
                *_reference_content_instructions(request),
            ],
        )
    )
    validated = _append_build_cycle(steps, "geometry.detail_author", "detail")
    reviewed, review_run_id = _append_geometry_multiview_review(
        steps,
        validated,
        workflow_id=request.workflow_id,
        prefix="detail",
    )
    report = _append_pdf_report(
        steps,
        reviewed,
        "detail",
        "build",
        parameters={"assembly_sanity_run_id": review_run_id},
    )
    steps.append(
        _step(
            "geometry.detail_approval",
            "Approve exact detailed geometry evidence",
            "geometry",
            "approval",
            depends_on=[report],
            gate="detailed_geometry",
        )
    )
    return "geometry.detail_approval"


def _append_material_flow(
    steps: list[WorkflowStep],
    dependency: str,
    *,
    workflow_id: str,
    require_approval: bool = True,
) -> str:
    """Append candidate-based V0.5 authoring and an exact canonical promotion."""

    material_root = f"workflows/{workflow_id}/artifacts/m"
    scaffold_root = f"{material_root}/scaffold"
    authored_root = f"{material_root}/authored"
    authored_plan = f"{authored_root}/material_plan.json"
    promotion_receipt = f"{material_root}/promotion.json"
    promoted_snapshot = f"{material_root}/promoted.json"

    steps.extend(
        [
            _step(
                "material.uv_inventory",
                "Inspect stable UV layout evidence",
                "material",
                "host",
                tool="inspect_scene",
                depends_on=[dependency],
                outputs=[
                    _artifact(
                        "material.uv_inventory",
                        "reports/scene_inventory.json",
                        acceptance="valid_json",
                    )
                ],
            ),
            _step(
                "material.scaffold",
                "Initialize stable material contracts",
                "material",
                "host",
                tool="material_scaffold_candidate",
                depends_on=["material.uv_inventory"],
                outputs=[
                    _artifact(
                        "material.plan.scaffold",
                        scaffold_root,
                        acceptance="nonempty_directory",
                        lifecycle="immutable_run",
                    )
                ],
                parameters={
                    "scaffold_root": scaffold_root,
                    "authored_root": authored_root,
                },
            ),
            _step(
                "material.author",
                "Author material, texture, and shader recipes",
                "material",
                "agent",
                tool="author_material_contracts",
                depends_on=["material.scaffold"],
                outputs=[
                    _artifact(
                        "material.plan.authored",
                        authored_root,
                        acceptance="nonempty_directory",
                        lifecycle="immutable_run",
                    )
                ],
                parameters={
                    "candidate_plan_path": authored_plan,
                    "require_spatial_surface_details": True,
                },
                instructions=[
                    "Edit only the workflow-owned authored candidate directory.",
                    "Use only whitelisted Blender 5-compatible shader recipes.",
                    "Keep portable surface semantics separate from Blender master graphs.",
                    "For every textured surface_detail, author a UVMap image/hybrid manifest "
                    "whose spatial binding identifies the exact parent object, UV layout, "
                    "placement, PBR channels, and reference evidence for that decision.",
                    "Do not paint generic panel, seam, groove, scratch, or line patterns over "
                    "a shared material. If exact placement is unavailable, use a clean, "
                    "low-variance base PBR surface and stop for a V0.4 ModelingPlan decision "
                    "that explicitly omits or re-routes that localized detail.",
                    "Keep tileable base PBR variation separate from localized detail overlays; "
                    "localized overlays must not use repeat wrapping.",
                    "Read the current reports/scene_inventory.json and bind uv_layout_sha256 "
                    "to the parent object's exact UVMap vertex_uv_binding_fingerprint; never "
                    "invent, copy from another object, or leave that hash unverified.",
                    "Do not call external texture or image providers unless the immutable "
                    "workflow budget permits them.",
                ],
            ),
            _step(
                "material.promote",
                "Validate and promote exact material contracts",
                "material",
                "host",
                tool="promote_material_contracts",
                depends_on=["material.author"],
                outputs=[
                    _artifact(
                        "material.plan.promotion_receipt",
                        promotion_receipt,
                        acceptance="json_ok",
                        lifecycle="immutable_run",
                    ),
                    _artifact(
                        "material.plan.promoted_snapshot",
                        promoted_snapshot,
                        source_path="analysis/material_plan.json",
                        lifecycle="workflow_snapshot",
                        acceptance="valid_json",
                    ),
                ],
                parameters={
                    "candidate_plan_path": authored_plan,
                    "promotion_receipt_path": promotion_receipt,
                },
            ),
            _step(
                "material.contract_validate",
                "Validate material contracts",
                "material",
                "host",
                tool="validate_material_contracts",
                depends_on=["material.promote"],
                outputs=[
                    _artifact(
                        "material.contract_report",
                        "reports/material_contract_validation.json",
                        acceptance="json_ok",
                    )
                ],
            ),
            _step(
                "material.fidelity",
                "Measure deterministic material fidelity",
                "material",
                "host",
                tool="validate_material_fidelity",
                depends_on=["material.contract_validate"],
                outputs=[
                    _artifact(
                        "material.fidelity_report",
                        "reports/material_fidelity_validation.json",
                        acceptance="json_ok",
                    )
                ],
                instructions=[
                    "Treat warning and unscorable outcomes as visible review evidence, not "
                    "automatic approval or geometry failure.",
                    "Return dark-line, full-field variation, normal, emission, and spatial "
                    "leakage findings to V0.5 authoring before any manual material approval.",
                ],
            ),
            _step(
                "material.build",
                "Rebuild scene with approved material contracts",
                "material",
                "host",
                tool="build_scene",
                depends_on=["material.fidelity"],
                outputs=[_artifact("material.blend", "blender/scene.blend")],
            ),
            _step(
                "material.inspect",
                "Inspect Blender material graphs and UVs",
                "material",
                "host",
                tool="inspect_materials",
                depends_on=["material.build"],
                outputs=[
                    _artifact(
                        "material.runtime_report",
                        "reports/material_validation.json",
                        acceptance="json_ok",
                    )
                ],
            ),
            _step(
                "material.swatches",
                "Render fixed material swatches",
                "material",
                "host",
                tool="render_material_swatches",
                depends_on=["material.inspect"],
                outputs=[
                    _artifact(
                        "material.swatch_manifest",
                        "reports/material_swatches.json",
                        acceptance="valid_json",
                    )
                ],
            ),
        ]
    )
    report = _append_pdf_report(steps, "material.swatches", "material", "material")
    if not require_approval:
        return report
    steps.append(
        _step(
            "material.approval",
            "Approve exact material swatches and reports",
            "material",
            "approval",
            depends_on=[report],
            gate="material_swatches",
        )
    )
    return "material.approval"


def _append_qa_flow(
    steps: list[WorkflowStep],
    dependency: str,
    *,
    require_review: bool = True,
    run_id: str | None = None,
    append_report: bool = True,
) -> str:
    """Append canonical QA plus additive diagnostics before report/review delivery."""

    run_parameters: dict[str, str | int | float | bool] = {
        "include_generated_target": False,
        "require_new_output": True,
    }
    if run_id is not None:
        run_parameters["run_id"] = run_id
        run_parameters["diagnostic_policy"] = "camera_geometry_v1"
        qa_outputs = [
            _artifact(
                "qa.run.request",
                f"qa/runs/{run_id}/request.json",
                acceptance="valid_json",
                lifecycle="immutable_run",
            ),
            _artifact(
                "qa.run.reference_mask",
                f"qa/runs/{run_id}/reference_mask.png",
                acceptance="exists",
                lifecycle="immutable_run",
            ),
            _artifact(
                "qa.run.reference_mask_manifest",
                f"qa/runs/{run_id}/reference_mask_manifest.json",
                acceptance="valid_json",
                lifecycle="immutable_run",
            ),
            _artifact(
                "qa.run.render_pass_manifest",
                f"qa/runs/{run_id}/render_pass_manifest.json",
                acceptance="valid_json",
                lifecycle="immutable_run",
            ),
            _artifact(
                "qa.run.visual_report",
                f"qa/runs/{run_id}/visual_qa_report.json",
                acceptance="valid_json",
                lifecycle="immutable_run",
            ),
            _artifact(
                "qa.run.revision_candidates",
                f"qa/runs/{run_id}/revision_candidates.json",
                acceptance="valid_json",
                lifecycle="immutable_run",
            ),
            *[
                _artifact(
                    f"qa.run.pass.{kind}",
                    f"qa/runs/{run_id}/passes/{kind}.png",
                    acceptance="exists",
                    lifecycle="immutable_run",
                )
                for kind in (
                    "beauty",
                    "silhouette",
                    "object_id",
                    "material_id",
                    "normal",
                    "depth",
                    "wireframe",
                )
            ],
        ]
    else:
        qa_outputs = [
            _artifact(
                "qa.latest",
                "qa/latest.json",
                acceptance="valid_json",
            )
        ]
    steps.extend(
        [
            _step(
                "qa.run",
                "Run fixed-camera direct-reference QA",
                "qa",
                "host",
                tool="run_visual_qa",
                depends_on=[dependency],
                outputs=qa_outputs,
                parameters=run_parameters,
            ),
        ]
    )
    qa_dependency = "qa.run"
    if run_id is not None:
        diagnostic_id = "camera-geometry-v1"
        diagnostic_root = f"qa/runs/{run_id}/diagnostics/{diagnostic_id}"
        steps.append(
            _step(
                "qa.diagnostics",
                "Run bounded camera, semantic-shape, and assembly diagnostics",
                "qa",
                "host",
                tool="run_visual_diagnostics",
                depends_on=["qa.run"],
                outputs=[
                    _artifact(
                        "qa.diagnostics.bundle",
                        f"{diagnostic_root}/bundle_manifest.json",
                        acceptance="valid_json",
                        lifecycle="immutable_run",
                    )
                ],
                parameters={
                    "qa_run_id": run_id,
                    "diagnostic_id": diagnostic_id,
                    "max_camera_probes": 12,
                    "include_multiview_sanity": True,
                    "require_new_output": True,
                },
                instructions=[
                    "This companion evidence never changes the canonical V0.6 score.",
                    "Camera attribution and multi-view sanity are advisory and cannot "
                    "authorize geometry changes.",
                ],
            )
        )
        qa_dependency = "qa.diagnostics"
    if not append_report:
        return qa_dependency
    report = _append_pdf_report(
        steps,
        qa_dependency,
        "qa",
        "qa",
        parameters={"qa_run_id": run_id or "latest"},
    )
    if not require_review:
        return report
    steps.append(
        _step(
            "qa.review",
            "Review QA findings and revision candidates",
            "qa",
            "approval",
            depends_on=[report],
            gate="qa_review",
            instructions=[
                "This approval acknowledges the exact report; it does not authorize a revision.",
                "Apply candidates only through the separate hash-bound visual-revision flow.",
            ],
        )
    )
    return "qa.review"


def _append_background_eligibility(
    steps: list[WorkflowStep],
    dependency: str,
    request: WorkflowRequest,
    *,
    qa_run_id: str,
) -> str:
    """Append review-delivery quality classification without rewriting V0.6 evidence."""

    output = f"reports/background_delivery/{request.workflow_id}_quality.json"
    fit_root = f"workflows/{request.workflow_id}/artifacts/g/fit"
    steps.append(
        _step(
            "background.eligibility",
            "Classify completed preview quality for user review",
            "qa",
            "host",
            tool="evaluate_background_delivery",
            depends_on=[dependency],
            outputs=[
                _artifact(
                    "background.delivery_eligibility",
                    output,
                    acceptance="json_ok",
                    lifecycle="immutable_run",
                )
            ],
            parameters={
                "output_path": output,
                "qa_run_id": qa_run_id,
                "role_map_path": f"{fit_root}/role_map.json",
                "fit_report_path": f"{fit_root}/fit_report.json",
                "quality_policy": "review_delivery_v2",
            },
            instructions=[
                "Visual findings classify quality as passed, needs_revision, or unscorable.",
                "A high visual finding recommends standard revision but does not block "
                "preview review delivery.",
                "Scope, safety, tampering, and host failures retain their distinct blockers.",
                "This check never applies a QA candidate or edits canonical geometry.",
            ],
        )
    )
    return "background.eligibility"


def _append_interior_qa_flow(
    steps: list[WorkflowStep],
    dependency: str,
    request: WorkflowRequest,
) -> str:
    """Append approved multi-view interior planning, rendering, and review steps."""

    suffix = request.workflow_id[-8:]
    run_id = f"v08-interior-{suffix}"
    run_root = f"qa/interior/runs/{run_id}"
    steps.extend(
        [
            _step(
                "interior_qa.scope_validate",
                "Validate exact approved InteriorScope",
                "interior",
                "host",
                tool="validate_interior_scope",
                depends_on=[dependency],
                outputs=[
                    _artifact(
                        "interior_qa.scope_validation",
                        "reports/interior_scope_validation.json",
                        acceptance="json_ok",
                    )
                ],
            ),
            _step(
                "interior_qa.plan",
                "Plan bounded multi-view interior cameras",
                "qa",
                "host",
                tool="plan_interior_qa",
                depends_on=["interior_qa.scope_validate"],
                outputs=[
                    _artifact(
                        "interior_qa.source_inventory",
                        f"{run_root}/source_inventory.json",
                        acceptance="valid_json",
                    ),
                    _artifact(
                        "interior_qa.plan.output",
                        f"{run_root}/plan.json",
                        acceptance="valid_json",
                    ),
                ],
                parameters={
                    "run_id": run_id,
                    "profile": "standard",
                    "require_new_output": True,
                },
                instructions=[
                    "Planning is read-only for canonical geometry and the authoring blend.",
                    "Show the exact plan SHA-256 before requesting specialized approval.",
                ],
            ),
            _step(
                "interior_qa.plan_approval",
                "Approve exact interior camera plan",
                "qa",
                "specialized_approval",
                depends_on=["interior_qa.plan"],
                outputs=[
                    _artifact(
                        "interior_qa.plan_approval.output",
                        f"{run_root}/plan_approval.json",
                        acceptance="valid_json",
                    )
                ],
                gate="interior_qa_plan",
                parameters={"run_id": run_id},
                instructions=[
                    "Use the exact plan.json SHA-256 and explicit user approval.",
                    "Generic workflow approval cannot replace this specialized approval.",
                ],
            ),
            _step(
                "interior_qa.run",
                "Render and inspect approved interior views",
                "qa",
                "host",
                tool="run_interior_qa",
                depends_on=["interior_qa.plan_approval"],
                outputs=[
                    _artifact(
                        "interior_qa.render_manifest",
                        f"{run_root}/render_manifest.json",
                        acceptance="valid_json",
                    ),
                    _artifact(
                        "interior_qa.report",
                        f"{run_root}/interior_qa_report.json",
                        acceptance="valid_json",
                    ),
                    _artifact(
                        "interior_qa.candidates",
                        f"{run_root}/revision_candidates.json",
                        acceptance="valid_json",
                    ),
                    _artifact(
                        "interior_qa.latest",
                        "qa/interior/latest.json",
                        acceptance="valid_json",
                    ),
                ],
                parameters={"run_id": run_id, "require_new_output": True},
                instructions=[
                    "Every approved view must render exactly seven V0.6 pass kinds.",
                    "Do not save temporary cameras or isolation state to the authoring blend.",
                ],
            ),
        ]
    )
    report = _append_pdf_report(
        steps,
        "interior_qa.run",
        "interior_qa",
        "qa",
        parameters={
            "qa_run_id": "latest",
            "interior_qa_run_id": run_id,
        },
    )
    steps.append(
        _step(
            "interior_qa.review",
            "Review multi-view interior evidence",
            "qa",
            "approval",
            depends_on=[report],
            gate="qa_review",
            instructions=[
                "This review acknowledges the exact evidence only.",
                "Interior revision candidates remain manual and require a separate "
                "canonical geometry revision.",
            ],
        )
    )
    return "interior_qa.review"


def _append_portable_flow(
    steps: list[WorkflowStep],
    dependency: str,
    request: WorkflowRequest,
    *,
    require_final_review: bool = True,
    source_quality_path: str | None = None,
) -> str:
    """Append V0.7 packaging while optionally retaining its generic final review."""

    run_id, conversion_id, package_id = _portable_ids(request)
    profile_path = f"asset_profiles/{request.profile_id}.json"
    run_root = f"optimization/runs/{run_id}"
    package_root = f"exports/packages/{request.profile_id}/{package_id}"
    plan_parameters: dict[str, str | int | float | bool] = {
        "profile_id": request.profile_id,
        "run_id": run_id,
    }
    if source_quality_path is not None:
        plan_parameters["source_quality_path"] = source_quality_path
    steps.extend(
        [
            _step(
                "portable.profile",
                "Initialize engine-neutral static-asset profile",
                "portable",
                "host",
                tool="initialize_asset_profile",
                depends_on=[dependency],
                outputs=[
                    _artifact(
                        "portable.profile.output",
                        profile_path,
                        acceptance="valid_json",
                        canonical=True,
                    )
                ],
                parameters={"profile_id": request.profile_id},
            ),
            _step(
                "portable.preflight",
                "Run read-only topology preflight",
                "portable",
                "host",
                tool="run_asset_preflight",
                depends_on=["portable.profile"],
                outputs=[
                    _artifact(
                        "portable.preflight.report",
                        f"{run_root}/mesh_preflight_report.json",
                        acceptance="json_ok",
                    )
                ],
                parameters={"profile_id": request.profile_id, "run_id": run_id},
            ),
            _step(
                "portable.plan",
                "Generate exact LOD and collider review",
                "portable",
                "host",
                tool="plan_portable_asset_optimization",
                depends_on=["portable.preflight"],
                outputs=[
                    _artifact(
                        "portable.review_plan",
                        f"{run_root}/review_plan.json",
                        acceptance="valid_json",
                    ),
                    _artifact(
                        "portable.review",
                        f"{run_root}/optimization_review.json",
                        acceptance="valid_json",
                    ),
                ],
                parameters=plan_parameters,
            ),
            _step(
                "portable.plan_approval",
                "Review exact LOD, collider, and asset-revision choices",
                "portable",
                "specialized_approval",
                depends_on=["portable.plan"],
                outputs=[
                    _artifact(
                        "portable.optimization_approval",
                        f"{run_root}/optimization_approval.json",
                        acceptance="valid_json",
                    )
                ],
                gate="optimization_plan",
                parameters={"profile_id": request.profile_id, "run_id": run_id},
                instructions=[
                    "Inspect optimization_review.json and choose approve, revise_asset, "
                    "revise_profile, or cancel.",
                    "Use asset-plan-approve with the exact review_plan.json SHA-256 only "
                    "for approve.",
                    "Choose revise_asset for geometry, silhouette, proportion, or semantic "
                    "corrections. After explicit user selection, use plan_short_workflow "
                    "with intent=revise_asset and execution_policy=standard to create a new "
                    "immutable workflow; do not convert or approve this portable workflow.",
                    "Choose revise_profile only for LOD, collider, consolidation, UV, "
                    "texture, or budget settings; then create a fresh V0.7 run and approval.",
                    "After any canonical asset revision, rebuild and rerun QA before "
                    "starting a fresh V0.7 preflight and review.",
                ],
            ),
            _step(
                "portable.optimize",
                "Create approved derived LOD, collider, UV, and optimized scene",
                "portable",
                "host",
                tool="optimize_portable_asset",
                depends_on=["portable.plan_approval"],
                outputs=[
                    _artifact(
                        "portable.optimization_plan",
                        f"{run_root}/optimization_plan.json",
                        acceptance="valid_json",
                    ),
                    _artifact(
                        "portable.optimized_blend",
                        f"{run_root}/optimized/scene.blend",
                    ),
                    _artifact(
                        "portable.cost_report",
                        f"{run_root}/asset_cost_report.json",
                        acceptance="json_ok",
                    ),
                ],
                parameters={"profile_id": request.profile_id, "run_id": run_id},
            ),
            _step(
                "portable.material_convert",
                "Create portable raw PBR material conversion",
                "portable",
                "host",
                tool="convert_portable_materials",
                depends_on=["portable.optimize"],
                outputs=[
                    _artifact(
                        "portable.material_conversion",
                        (
                            "optimization/material_conversions/"
                            f"{run_id}/{conversion_id}/conversion_manifest.json"
                        ),
                        acceptance="valid_json",
                    )
                ],
                parameters={
                    "profile_id": request.profile_id,
                    "run_id": run_id,
                    "conversion_id": conversion_id,
                    "resolution": min(request.budgets.max_texture_resolution, 4096),
                },
            ),
            _step(
                "portable.package",
                "Build immutable engine-neutral package",
                "portable",
                "host",
                tool="build_portable_package",
                depends_on=["portable.material_convert"],
                outputs=[
                    _artifact(
                        "portable.package_manifest",
                        f"{package_root}/package_manifest.json",
                        acceptance="valid_json",
                    )
                ],
                parameters={
                    "profile_id": request.profile_id,
                    "run_id": run_id,
                    "conversion_id": conversion_id,
                    "package_id": package_id,
                },
            ),
            _step(
                "portable.roundtrip",
                "Clean-import and validate portable package",
                "portable",
                "host",
                tool="validate_portable_package",
                depends_on=["portable.package"],
                outputs=[
                    _artifact(
                        "portable.roundtrip_report",
                        f"{run_root}/roundtrip/{package_id}/roundtrip_validation.json",
                        acceptance="json_ok",
                    )
                ],
                parameters={
                    "profile_id": request.profile_id,
                    "package_id": package_id,
                },
            ),
        ]
    )
    report_parameters: dict[str, str | int | float | bool] = {
        "optimization_run_id": run_id,
        "package_id": package_id,
    }
    if source_quality_path is not None:
        report_parameters["background_quality_report_path"] = source_quality_path
    report = _append_pdf_report(
        steps,
        "portable.roundtrip",
        "portable",
        "export",
        parameters=report_parameters,
    )
    terminal = report
    if require_final_review:
        steps.append(
            _step(
                "portable.final_approval",
                "Approve exact portable package and round-trip evidence",
                "portable",
                "approval",
                depends_on=[report],
                gate="final_package",
            )
        )
        terminal = "portable.final_approval"
    if request.include_destination_handoff:
        suffix = request.workflow_id[-8:]
        handoff_id = f"v08-{suffix}-handoff"
        handoff_root = (
            f"exports/destination_handoffs/{request.profile_id}/{package_id}/{handoff_id}"
        )
        steps.append(
            _step(
                "destination.handoff",
                "Generate immutable Codex destination handoff",
                "destination",
                "agent",
                tool="generate_destination_handoff",
                depends_on=["portable.final_approval"],
                outputs=[
                    _artifact(
                        "destination.handoff.manifest",
                        f"{handoff_root}/codex_handoff/handoff_manifest.json",
                        acceptance="valid_json",
                    ),
                    _artifact(
                        "destination.handoff.validation",
                        f"{handoff_root}/destination_handoff_validation.json",
                        acceptance="json_ok",
                    ),
                    _artifact(
                        "destination.handoff.pdf_manifest",
                        f"{handoff_root}/codex_handoff/handoff_report.manifest.json",
                        acceptance="valid_json",
                    ),
                    _artifact(
                        "destination.handoff.directory",
                        handoff_root,
                        acceptance="nonempty_directory",
                    ),
                ],
                parameters={
                    "profile_id": request.profile_id,
                    "package_id": package_id,
                    "handoff_id": handoff_id,
                },
                instructions=[
                    "Plan the handoff against the exact passed round-trip package.",
                    "Generate and validate it without modifying a destination project.",
                    "Record completion only after exact package and handoff hashes pass.",
                ],
            )
        )
        terminal = "destination.handoff"
    if request.destination.kind in {"unity", "unreal", "custom"}:
        steps.append(
            _step(
                "destination.unsupported",
                "Stop at portable package; destination adapter is unavailable",
                "destination",
                "manual",
                tool="select_validated_destination_adapter",
                depends_on=[terminal],
                instructions=[request.destination.kind + " adapter is not implemented."],
            )
        )
        return terminal
    return terminal


def _portable_ids(request: WorkflowRequest) -> tuple[str, str, str]:
    """Derive stable V0.7 run, material-conversion, and package IDs from a workflow."""

    suffix = request.workflow_id[-8:]
    return (
        f"v08-{suffix}",
        f"v08-{suffix}-materials",
        f"v08-{suffix}-package",
    )


def _scope_for_routing(request: WorkflowRequest, routing: IntentRouting) -> WorkflowScope:
    """Keep explicit scope while applying conservative intent-specific defaults."""

    return request.requested_scope


def _is_run_owned_path(path: str, workflow_id: str) -> bool:
    """Identify paths already isolated by an exact workflow, run, or package ID."""

    return path.startswith(
        (
            f"workflows/{workflow_id}/",
            "qa/runs/",
            "qa/interior/runs/",
            "optimization/runs/",
            "exports/packages/",
            "exports/material_conversions/",
            f"reports/background_delivery/{workflow_id}_",
        )
    )


def _bind_artifact_lifecycle(
    steps: list[WorkflowStep],
    workflow_id: str,
) -> list[WorkflowStep]:
    """Bind host outputs to immutable evidence while retaining mutable source locations."""

    bound: list[WorkflowStep] = []
    for step in steps:
        parameters = dict(step.parameters)
        outputs: list[ArtifactRequirement] = []
        if step.tool_name == "generate_pdf_report":
            report_key = hashlib.sha256(step.step_id.encode("utf-8")).hexdigest()[:12]
            output_path = f"workflows/{workflow_id}/artifacts/pdf/{report_key}.pdf"
            parameters["output_path"] = output_path
            outputs = [
                _artifact(
                    f"{step.step_id}.pdf",
                    output_path,
                    lifecycle="immutable_run",
                ),
                _artifact(
                    f"{step.step_id}.manifest",
                    output_path.removesuffix(".pdf") + ".manifest.json",
                    acceptance="valid_json",
                    lifecycle="immutable_run",
                ),
            ]
        else:
            for output in step.outputs:
                if output.lifecycle != "canonical":
                    outputs.append(output)
                    continue
                if step.execution_mode != "host":
                    outputs.append(output)
                    continue
                if step.tool_name == "create_job":
                    outputs.append(output)
                    continue
                if _is_run_owned_path(output.path, workflow_id):
                    outputs.append(
                        output.model_copy(
                            update={
                                "lifecycle": "immutable_run",
                                "canonical": False,
                            }
                        )
                    )
                    continue
                snapshot_key = hashlib.sha256(
                    f"{step.step_id}\0{output.path}".encode()
                ).hexdigest()[:16]
                suffix = PurePosixPath(output.path).suffix
                snapshot_path = f"workflows/{workflow_id}/artifacts/s/{snapshot_key}{suffix}"
                outputs.append(
                    output.model_copy(
                        update={
                            "path": snapshot_path,
                            "source_path": output.path,
                            "lifecycle": "workflow_snapshot",
                            "canonical": False,
                        }
                    )
                )
        bound.append(
            step.model_copy(
                update={
                    "outputs": outputs,
                    "parameters": parameters,
                }
            )
        )
    return bound


def build_workflow_plan(
    request: WorkflowRequest,
    routing: IntentRouting,
    *,
    request_sha256: str,
    routing_sha256: str,
    existing_modeling_plan_sha256: str | None = None,
    existing_assembly_consistency_policy: str | None = None,
) -> WorkflowPlan:
    """Build one immutable plan while preserving every specialized safety approval.

    Existing-job revision plans bind the exact ModelingPlan policy and hash so
    a legacy ``legacy_unbound`` job can omit the spatial-only review without a
    later policy change silently altering that decision.
    """

    if (
        request.execution_policy != routing.execution_policy
        or request.delivery_scope != routing.delivery_scope
    ):
        raise ValueError("workflow request and routing execution policies do not match")
    steps: list[WorkflowStep] = []
    scope = _scope_for_routing(request, routing)
    if routing.intent == "revise_asset":
        if existing_modeling_plan_sha256 is None:
            raise ValueError("revise_asset requires an exact existing ModelingPlan SHA-256")
        if len(existing_modeling_plan_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in existing_modeling_plan_sha256
        ):
            raise ValueError("revise_asset ModelingPlan SHA-256 must be lowercase hex")
        if existing_assembly_consistency_policy not in {
            "legacy_unbound",
            "spatial_v1",
        }:
            raise ValueError("revise_asset requires a supported existing assembly policy")
    if routing.intent == "new_asset":
        steps.append(
            _step(
                "job.created",
                "Create isolated immutable-reference job",
                "job",
                "host",
                tool="create_job",
                outputs=[
                    _artifact(
                        "job.metadata",
                        "job.json",
                        acceptance="valid_json",
                        canonical=True,
                    )
                ],
            )
        )
        if request.execution_policy == "background_exterior":
            qa_run_id = f"v08-{request.workflow_id[-8:]}-qa"
            quality_path = f"reports/background_delivery/{request.workflow_id}_quality.json"
            terminal = _append_background_geometry_flow(
                steps,
                "job.created",
                request=request,
                max_fit_attempts=request.budgets.max_pre_qa_fit_attempts,
            )
            terminal = _append_material_flow(
                steps,
                terminal,
                workflow_id=request.workflow_id,
                require_approval=False,
            )
            terminal = _append_qa_flow(
                steps,
                terminal,
                require_review=False,
                run_id=qa_run_id,
                append_report=False,
            )
            terminal = _append_background_eligibility(
                steps,
                terminal,
                request,
                qa_run_id=qa_run_id,
            )
            terminal = _append_pdf_report(
                steps,
                terminal,
                "qa",
                "qa",
                parameters={
                    "qa_run_id": qa_run_id,
                    "background_quality_report_path": quality_path,
                },
            )
            if request.delivery_scope == "portable_package":
                terminal = _append_portable_flow(
                    steps,
                    terminal,
                    request,
                    require_final_review=False,
                    source_quality_path=quality_path,
                )
            delivery_prefix = f"background_delivery_{request.workflow_id[-8:]}"
            report_parameters: dict[str, str | int | float | bool] = {
                "qa_run_id": qa_run_id,
                "background_quality_report_path": quality_path,
            }
            if request.delivery_scope == "portable_package":
                optimization_run_id, _conversion_id, package_id = _portable_ids(request)
                report_parameters.update(
                    {
                        "optimization_run_id": optimization_run_id,
                        "package_id": package_id,
                    }
                )
            terminal = _append_pdf_report(
                steps,
                terminal,
                delivery_prefix,
                "full",
                parameters=report_parameters,
            )
        else:
            terminal = _append_proxy_flow(steps, "job.created", request)
            if scope == "full":
                terminal = _append_detail_flow(steps, terminal, request)
                terminal = _append_material_flow(
                    steps,
                    terminal,
                    workflow_id=request.workflow_id,
                )
                terminal = _append_qa_flow(
                    steps,
                    terminal,
                    run_id=f"v08-{request.workflow_id[-8:]}-qa",
                )
                if request.delivery_scope in {None, "portable_package"}:
                    terminal = _append_portable_flow(steps, terminal, request)
    elif routing.intent == "add_measured_view":
        steps.append(
            _step(
                "view.add",
                "Promote staged measured view into immutable job evidence",
                "analysis",
                "host",
                tool="add_view",
                outputs=[
                    _artifact(
                        "view.job_metadata",
                        "job.json",
                        acceptance="valid_json",
                        canonical=True,
                    )
                ],
                parameters={"require_new_output": True},
            )
        )
        steps.append(
            _step(
                "reference.analyze",
                "Reanalyze all registered reference views",
                "analysis",
                "host",
                tool="analyze_reference",
                depends_on=["view.add"],
                outputs=[
                    _artifact(
                        "view.reference_analysis",
                        "analysis/reference_analysis.json",
                        acceptance="valid_json",
                        canonical=True,
                    ),
                    _artifact(
                        "view.camera_solution",
                        "analysis/camera_solution.json",
                        acceptance="valid_json",
                        canonical=True,
                    ),
                ],
                parameters={"require_new_output": True},
            )
        )
        terminal = "reference.analyze"
    elif routing.intent == "revise_asset":
        if request.revision_strategy == "candidate_review":
            terminal = _append_candidate_review_revision_flow(
                steps,
                request,
                assembly_consistency_policy=str(existing_assembly_consistency_policy),
            )
        else:
            steps.extend(
                [
                    _step(
                        "revision.author",
                        "Author minimal guarded RevisionPlan",
                        "geometry",
                        "agent",
                        tool="author_revision_plan",
                        outputs=[
                            _artifact(
                                "revision.plan",
                                "analysis/revision_plan.json",
                                acceptance="valid_json",
                                canonical=True,
                            )
                        ],
                        instructions=(
                            [
                                (
                                    "Preserve every current spatial_v1 assembly relationship "
                                    "and parent-local placement unless the user's exact request "
                                    "explicitly targets that relationship."
                                ),
                                (
                                    "Do not convert a 2D reference-screen offset into an "
                                    "unobserved depth/lateral revision; keep inferred hidden-axis "
                                    "assumptions and stable subject/reference IDs intact."
                                ),
                            ]
                            if existing_assembly_consistency_policy == "spatial_v1"
                            else [
                                (
                                    "The exact source ModelingPlan is legacy_unbound. Preserve "
                                    "stable semantic IDs and do not claim spatial-v1 assembly or "
                                    "multi-view evidence; migration requires a separate review."
                                )
                            ]
                        ),
                    ),
                    _step(
                        "revision.approval",
                        "Approve exact guarded revision plan",
                        "geometry",
                        "approval",
                        depends_on=["revision.author"],
                        gate="detailed_geometry",
                    ),
                    _step(
                        "revision.apply",
                        "Apply guarded revision and archive previous SceneSpec",
                        "geometry",
                        "host",
                        tool="apply_revision_plan",
                        depends_on=["revision.approval"],
                        outputs=[
                            _artifact(
                                "revision.scene_spec",
                                "analysis/scene_spec.json",
                                acceptance="valid_json",
                                canonical=True,
                            ),
                            _artifact(
                                "revision.diff",
                                "reports/revision_diff.json",
                                acceptance="valid_json",
                            ),
                        ],
                        parameters={"require_new_output": True},
                    ),
                ]
            )
            terminal = _append_build_cycle(steps, "revision.apply", "revision")
            if existing_assembly_consistency_policy == "spatial_v1":
                terminal, review_run_id = _append_geometry_multiview_review(
                    steps,
                    terminal,
                    workflow_id=request.workflow_id,
                    prefix="revision",
                )
                terminal = _append_pdf_report(
                    steps,
                    terminal,
                    "revision",
                    "build",
                    parameters={"assembly_sanity_run_id": review_run_id},
                )
            else:
                terminal = _append_pdf_report(
                    steps,
                    terminal,
                    "revision",
                    "build",
                )
        _bind_revision_modeling_plan_contract(
            steps,
            modeling_plan_sha256=str(existing_modeling_plan_sha256),
            assembly_consistency_policy=str(existing_assembly_consistency_policy),
        )
    elif routing.intent == "interior_scope":
        steps.extend(
            [
                _step(
                    "interior.scope_author",
                    "Author exact opt-in InteriorScope draft",
                    "interior",
                    "agent",
                    tool="initialize_interior_scope",
                    outputs=[
                        _artifact(
                            "interior.scope",
                            "architecture/interior_scope.json",
                            acceptance="valid_json",
                            canonical=True,
                        )
                    ],
                    instructions=[
                        "The draft must encode the user's exact allowed/excluded boundary."
                    ],
                ),
                _step(
                    "interior.scope_approval",
                    "Manually approve exact InteriorScope hash",
                    "interior",
                    "specialized_approval",
                    depends_on=["interior.scope_author"],
                    outputs=[
                        _artifact(
                            "interior.scope_approval.output",
                            "architecture/interior_scope.approval.json",
                            acceptance="valid_json",
                            canonical=True,
                        )
                    ],
                    gate="interior_scope",
                ),
                _step(
                    "interior.geometry_author",
                    "Author only approved static interior geometry",
                    "interior",
                    "agent",
                    tool="author_interior_scene_spec",
                    depends_on=["interior.scope_approval"],
                    outputs=[
                        _artifact(
                            "interior.scene_spec",
                            "analysis/scene_spec.json",
                            acceptance="valid_json",
                            canonical=True,
                        )
                    ],
                ),
            ]
        )
        terminal = _append_build_cycle(steps, "interior.geometry_author", "interior")
    elif routing.intent == "material_authoring":
        terminal = _append_material_flow(
            steps,
            "geometry.prerequisite",
            workflow_id=request.workflow_id,
        )
        steps.insert(
            0,
            _step(
                "geometry.prerequisite",
                "Verify current geometry validation",
                "geometry",
                "host",
                tool="verify_geometry_prerequisite",
                outputs=[
                    _artifact(
                        "geometry.validation.current",
                        "reports/validation.json",
                        acceptance="json_ok",
                    )
                ],
            ),
        )
    elif routing.intent == "visual_qa":
        steps.append(
            _step(
                "geometry.prerequisite",
                "Verify current geometry validation",
                "geometry",
                "host",
                tool="verify_geometry_prerequisite",
                outputs=[
                    _artifact(
                        "qa.geometry_validation",
                        "reports/validation.json",
                        acceptance="json_ok",
                    )
                ],
            )
        )
        terminal = _append_qa_flow(
            steps,
            "geometry.prerequisite",
            run_id=f"v08-{request.workflow_id[-8:]}-qa",
        )
    elif routing.intent == "interior_visual_qa":
        steps.append(
            _step(
                "geometry.prerequisite",
                "Verify current geometry validation",
                "geometry",
                "host",
                tool="verify_geometry_prerequisite",
                outputs=[
                    _artifact(
                        "interior_qa.geometry_validation",
                        "reports/validation.json",
                        acceptance="json_ok",
                    )
                ],
            )
        )
        terminal = _append_interior_qa_flow(
            steps,
            "geometry.prerequisite",
            request,
        )
    else:
        prerequisite_tool = "verify_geometry_prerequisite"
        prerequisite_title = "Verify current geometry validation"
        prerequisite_parameters: dict[str, str | int | float | bool] = {}
        prerequisite_output = _artifact(
            "portable.geometry_validation",
            "reports/validation.json",
            acceptance="json_ok",
        )
        if request.execution_policy == "background_exterior":
            binding = request.background_preview_binding
            if binding is None:
                raise ValueError(
                    "background package continuation requires an exact preview binding"
                )
            prerequisite_tool = "verify_background_preview_prerequisite"
            prerequisite_title = "Verify exact completed background preview binding"
            binding_output = (
                f"reports/background_delivery/{request.workflow_id}_preview_binding.json"
            )
            prerequisite_parameters = {
                "require_new_output": True,
                "output_path": binding_output,
                "preview_workflow_id": binding.workflow_id,
                "preview_plan_sha256": binding.plan_sha256,
                "preview_terminal_fingerprint": (binding.terminal_completion_fingerprint),
                "source_fingerprint": binding.source_fingerprint,
                "build_fingerprint": binding.build_fingerprint,
            }
            if binding.quality_report_path is not None:
                prerequisite_parameters.update(
                    {
                        "quality_status": str(binding.quality_status),
                        "standard_workflow_recommended": bool(
                            binding.standard_workflow_recommended
                        ),
                        "quality_report_path": binding.quality_report_path,
                        "quality_report_sha256": str(binding.quality_report_sha256),
                    }
                )
            prerequisite_output = _artifact(
                "portable.background_preview_binding",
                binding_output,
                acceptance="json_ok",
            )
        steps.append(
            _step(
                "geometry.prerequisite",
                prerequisite_title,
                "geometry",
                "host",
                tool=prerequisite_tool,
                outputs=[prerequisite_output],
                parameters=prerequisite_parameters,
            )
        )
        terminal = _append_portable_flow(
            steps,
            "geometry.prerequisite",
            request,
            require_final_review=(request.execution_policy != "background_exterior"),
            source_quality_path=(
                request.background_preview_binding.quality_report_path
                if request.execution_policy == "background_exterior"
                and request.background_preview_binding is not None
                else None
            ),
        )
        if request.execution_policy == "background_exterior":
            delivery_prefix = f"background_delivery_{request.workflow_id[-8:]}"
            optimization_run_id, _conversion_id, package_id = _portable_ids(request)
            terminal = _append_pdf_report(
                steps,
                terminal,
                delivery_prefix,
                "full",
                parameters={
                    "qa_run_id": request.background_preview_binding.qa_run_id,
                    "optimization_run_id": optimization_run_id,
                    "package_id": package_id,
                    **(
                        {
                            "background_quality_report_path": (
                                request.background_preview_binding.quality_report_path
                            )
                        }
                        if request.background_preview_binding.quality_report_path is not None
                        else {}
                    ),
                },
            )
    steps = _bind_artifact_lifecycle(steps, request.workflow_id)
    return WorkflowPlan(
        workflow_id=request.workflow_id,
        job_id=request.job_id,
        request_sha256=request_sha256,
        routing_sha256=routing_sha256,
        intent=routing.intent,
        scope=scope,
        reference_content_scope=request.reference_content_scope,
        target_subject=request.target_subject,
        execution_policy=request.execution_policy,
        delivery_scope=request.delivery_scope,
        fast_quality_policy=request.fast_quality_policy,
        destination=routing.destination,
        steps=steps,
        terminal_step_id=terminal,
        created_at=datetime.now(UTC),
        notes=[
            "V0.8 coordinates existing V0.4-V0.7 contracts; it does not infer hidden geometry.",
            "Agent steps require exact output completion markers before dependent host steps run.",
            (
                f"Reference content scope is {request.reference_content_scope}; "
                f"target subject is {request.target_subject!r}."
            ),
            (
                "background_exterior omits generic review gates but never bypasses "
                "specialized approvals."
                if request.execution_policy == "background_exterior"
                else (
                    "standard candidate_review omits only the pre-execution RevisionPlan "
                    "approval and retains one exact post-evaluation promotion approval."
                    if request.revision_strategy == "candidate_review"
                    else "standard manual_guarded preserves every legacy generic and "
                    "specialized review boundary."
                )
            ),
            *(
                [
                    "Geometry multi-view review is not applicable: the exact source "
                    "ModelingPlan is legacy_unbound and has no spatial_v1 assembly frame."
                ]
                if routing.intent == "revise_asset"
                and existing_assembly_consistency_policy == "legacy_unbound"
                else []
            ),
        ],
    )
