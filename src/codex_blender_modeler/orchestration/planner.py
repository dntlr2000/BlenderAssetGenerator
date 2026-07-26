"""Immutable step-plan construction for routed V0.8 workflows."""

from __future__ import annotations

from datetime import UTC, datetime

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
    acceptance: str = "exists",
    canonical: bool = False,
) -> ArtifactRequirement:
    """Create one concise artifact requirement for an immutable workflow plan."""

    return ArtifactRequirement(
        artifact_id=artifact_id,
        path=path,
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


def _append_proxy_flow(steps: list[WorkflowStep], dependency: str) -> str:
    """Append analysis, proxy authoring, deterministic build, and user approval."""

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
                ],
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
                ],
            ),
        ]
    )
    validated = _append_build_cycle(steps, "geometry.proxy_author", "proxy")
    report = _append_pdf_report(steps, validated, "proxy", "build")
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


def _append_detail_flow(steps: list[WorkflowStep], dependency: str) -> str:
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
                "Preserve camera, stable IDs, and every unrequested property.",
            ],
        )
    )
    validated = _append_build_cycle(steps, "geometry.detail_author", "detail")
    report = _append_pdf_report(steps, validated, "detail", "build")
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


def _append_material_flow(steps: list[WorkflowStep], dependency: str) -> str:
    """Append V0.5 material contracts, runtime inspection, swatches, and approval."""

    steps.extend(
        [
            _step(
                "material.scaffold",
                "Initialize stable material contracts",
                "material",
                "host",
                tool="material_scaffold",
                depends_on=[dependency],
                outputs=[
                    _artifact(
                        "material.plan.scaffold",
                        "analysis/material_plan.json",
                        acceptance="valid_json",
                        canonical=True,
                    )
                ],
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
                        "analysis/material_plan.json",
                        acceptance="valid_json",
                        canonical=True,
                    )
                ],
                instructions=[
                    "Use only whitelisted Blender 5-compatible shader recipes.",
                    "Keep portable surface semantics separate from Blender master graphs.",
                ],
            ),
            _step(
                "material.contract_validate",
                "Validate material contracts",
                "material",
                "host",
                tool="validate_material_contracts",
                depends_on=["material.author"],
                outputs=[
                    _artifact(
                        "material.contract_report",
                        "reports/material_contract_validation.json",
                        acceptance="json_ok",
                    )
                ],
            ),
            _step(
                "material.build",
                "Rebuild scene with approved material contracts",
                "material",
                "host",
                tool="build_scene",
                depends_on=["material.contract_validate"],
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


def _append_qa_flow(steps: list[WorkflowStep], dependency: str) -> str:
    """Append one V0.6 direct-reference QA run and non-executing review gate."""

    steps.extend(
        [
            _step(
                "qa.run",
                "Run fixed-camera direct-reference QA",
                "qa",
                "host",
                tool="run_visual_qa",
                depends_on=[dependency],
                outputs=[
                    _artifact(
                        "qa.latest",
                        "qa/latest.json",
                        acceptance="valid_json",
                    )
                ],
                parameters={
                    "include_generated_target": False,
                    "require_new_output": True,
                },
            ),
        ]
    )
    report = _append_pdf_report(
        steps,
        "qa.run",
        "qa",
        "qa",
        parameters={"qa_run_id": "latest"},
    )
    steps.append(
        _step(
            "qa.review",
            "Review QA findings and revision candidates",
            "qa",
            "approval",
            depends_on=[report],
            gate="qa_review",
            instructions=[
                "This approval acknowledges the exact report; it does not authorize "
                "a revision.",
                "Apply candidates only through the separate hash-bound visual-revision flow.",
            ],
        )
    )
    return "qa.review"


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
) -> str:
    """Append V0.7 preflight, LOD/collider review, packaging, and round-trip gates."""

    suffix = request.workflow_id[-8:]
    run_id = f"v08-{suffix}"
    conversion_id = f"v08-{suffix}-materials"
    package_id = f"v08-{suffix}-package"
    profile_path = f"asset_profiles/{request.profile_id}.json"
    run_root = f"optimization/runs/{run_id}"
    package_root = f"exports/packages/{request.profile_id}/{package_id}"
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
                parameters={"profile_id": request.profile_id, "run_id": run_id},
            ),
            _step(
                "portable.plan_approval",
                "Approve exact LOD and collider plan",
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
                    "Use asset-plan-approve with the exact review_plan.json SHA-256.",
                    "Changing LOD or collider settings requires a new run and new approval.",
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
    report = _append_pdf_report(
        steps,
        "portable.roundtrip",
        "portable",
        "export",
        parameters={
            "optimization_run_id": run_id,
            "package_id": package_id,
        },
    )
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
        handoff_id = f"v08-{suffix}-handoff"
        handoff_root = (
            "exports/destination_handoffs/"
            f"{request.profile_id}/{package_id}/{handoff_id}"
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


def _scope_for_routing(request: WorkflowRequest, routing: IntentRouting) -> WorkflowScope:
    """Keep explicit scope while applying conservative intent-specific defaults."""

    return request.requested_scope


def build_workflow_plan(
    request: WorkflowRequest,
    routing: IntentRouting,
    *,
    request_sha256: str,
    routing_sha256: str,
) -> WorkflowPlan:
    """Build one immutable plan that preserves every V0.4-V0.7 approval boundary."""

    steps: list[WorkflowStep] = []
    scope = _scope_for_routing(request, routing)
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
        terminal = _append_proxy_flow(steps, "job.created")
        if scope == "full":
            terminal = _append_detail_flow(steps, terminal)
            terminal = _append_material_flow(steps, terminal)
            terminal = _append_qa_flow(steps, terminal)
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
        terminal = _append_material_flow(steps, "geometry.prerequisite")
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
        terminal = _append_qa_flow(steps, "geometry.prerequisite")
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
        steps.append(
            _step(
                "geometry.prerequisite",
                "Verify current geometry validation",
                "geometry",
                "host",
                tool="verify_geometry_prerequisite",
                outputs=[
                    _artifact(
                        "portable.geometry_validation",
                        "reports/validation.json",
                        acceptance="json_ok",
                    )
                ],
            )
        )
        terminal = _append_portable_flow(steps, "geometry.prerequisite", request)
    return WorkflowPlan(
        workflow_id=request.workflow_id,
        job_id=request.job_id,
        request_sha256=request_sha256,
        routing_sha256=routing_sha256,
        intent=routing.intent,
        scope=scope,
        destination=routing.destination,
        steps=steps,
        terminal_step_id=terminal,
        created_at=datetime.now(UTC),
        notes=[
            "V0.8 coordinates existing V0.4-V0.7 contracts; it does not infer hidden geometry.",
            "Agent steps require exact output completion markers before dependent host steps run.",
        ],
    )
