from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from .analysis import (
    analyze_job_reference,
    load_camera_solution,
    load_reference_analysis,
    validate_job_surface_details,
)
from .architecture import (
    get_interior_scope_status as get_interior_scope_status_internal,
)
from .architecture import (
    initialize_interior_scope as initialize_interior_scope_internal,
)
from .architecture import validate_job_interior_scope
from .auto_revision import (
    ConvergencePathLimit,
    apply_job_approved_revision,
    approve_job_qa_revision,
    approve_job_visual_convergence,
    cancel_job_visual_convergence,
    compile_job_qa_revision,
    get_job_visual_convergence_status,
    plan_job_visual_convergence,
    run_job_visual_convergence,
)
from .baking import bake_job_materials
from .blender_artifact_runner import (
    inspect_job_materials,
    render_job_material_swatches,
)
from .blender_runner import run_blender
from .config import get_settings, load_feature_config
from .constraints import evaluate_job_constraints, initialize_constraints
from .handoff import (
    generate_destination_handoff as generate_destination_handoff_internal,
)
from .handoff import (
    get_destination_handoff_status as get_destination_handoff_status_internal,
)
from .handoff import plan_destination_handoff as plan_destination_handoff_internal
from .handoff import (
    validate_destination_handoff as validate_destination_handoff_internal,
)
from .interior_qa import (
    approve_job_interior_qa_plan,
    get_job_interior_qa_status,
    plan_job_interior_qa,
    run_job_interior_qa,
)
from .materials import create_material_scaffold, validate_job_material_contracts
from .optimization import (
    approve_asset_optimization as approve_asset_optimization_internal,
)
from .optimization import (
    asset_status as get_asset_status_internal,
)
from .optimization import (
    initialize_asset_profile as initialize_asset_profile_internal,
)
from .optimization import (
    optimize_asset as optimize_asset_internal,
)
from .optimization import (
    plan_asset_optimization as plan_asset_optimization_internal,
)
from .optimization import (
    preflight_asset as preflight_asset_internal,
)
from .orchestration import (
    approve_workflow_gate as approve_workflow_gate_internal,
)
from .orchestration import cancel_workflow as cancel_workflow_internal
from .orchestration import complete_workflow_step as complete_workflow_step_internal
from .orchestration import destination_adapters as destination_adapters_internal
from .orchestration import get_workflow_status as get_workflow_status_internal
from .orchestration import plan_workflow as plan_workflow_internal
from .orchestration import reconcile_workflow as reconcile_workflow_internal
from .orchestration import resume_workflow as resume_workflow_internal
from .orchestration.models import WorkflowBudgets
from .packaging import (
    package_asset as package_asset_internal,
)
from .packaging import (
    validate_asset_package as validate_asset_package_internal,
)
from .packaging.material_conversion import (
    convert_portable_materials as convert_portable_materials_internal,
)
from .qa import ExistingFileQATargetProvider, run_job_visual_qa
from .reporting import generate_job_pdf_report, report_output_dir
from .revision import apply_revision_plan as apply_guarded_revision
from .stabilization import (
    audit_workspace_state as audit_workspace_state_internal,
)
from .stabilization import (
    cancel_local_workflow_queue_entry as cancel_local_queue_entry_internal,
)
from .stabilization import enqueue_short_workflow as enqueue_short_workflow_internal
from .stabilization import (
    generate_stability_pdf_report as generate_stability_pdf_report_internal,
)
from .stabilization import get_local_workflow_queue as get_local_workflow_queue_internal
from .stabilization import probe_release_environment as probe_release_environment_internal
from .stabilization import requeue_local_workflow as requeue_local_workflow_internal
from .stabilization import run_local_workflow_queue as run_local_workflow_queue_internal
from .texturing import (
    attach_texture_manifest_to_plan,
    generate_job_procedural_textures,
    get_material_family_presets,
)
from .validation import load_scene_spec
from .versioning import (
    CONSTRAINT_SCHEMA_VERSION,
    DESTINATION_HANDOFF_SCHEMA_VERSION,
    INTERIOR_SCOPE_SCHEMA_VERSION,
    MATERIAL_SCHEMA_VERSION,
    PORTABLE_ASSET_SCHEMA_VERSION,
    PROJECT_VERSION,
    REFERENCE_SCHEMA_VERSION,
    SCENE_SPEC_VERSION,
    STABILIZATION_SCHEMA_VERSION,
    VISUAL_QA_SCHEMA_VERSION,
    WORKFLOW_SCHEMA_VERSION,
)
from .workspace import (
    add_job_view,
    canonical_scene_spec_write_lock,
    ensure_job_dirs,
    job_dir,
    load_job,
    replace_scene_spec_if_current,
    sha256_file,
)
from .workspace import create_job as create_job_internal

mcp = FastMCP(
    "codex-blender-modeler",
    instructions=(
        "Project v0.9.0 adds release evidence, read-only workspace audits, and a bounded "
        "single-worker local queue while preserving V0.8 deterministic short-request "
        "routing, artifact freshness, "
        "resumable host steps, job write locks, and exact workflow approvals on top of "
        "the V0.7.4 LOD/collider review and hash-bound approval gate. It preserves "
        "semantic-preserving batching and static-asset cost evidence, "
        "the explicit opt-in InteriorScope safety boundary, "
        "run-owned portable material conversion and engine-neutral "
        "static-asset optimization and immutable portable "
        "packages while keeping "
        "SceneSpec v0.2 as the geometry contract. New assets require unique lowercase job IDs. "
        "Analyze references before SceneSpec authoring, preserve immutable inputs and stable IDs, "
        "then build, render, inspect, validate, and evaluate constraints. V0.7 derives LOD, "
        "collision, UV, texture, and interchange artifacts without replacing the canonical "
        "Blender scene. Generated QA targets remain advisory. Workflow orchestration never "
        "infers Unity, Unreal, or another destination engine."
    ),
)


@mcp.tool()
def create_job(
    job_id: str,
    reference_path: str,
    mode: str = "concept",
    reference_content_scope: str = "full_reference",
    target_subject: str | None = None,
    scale_anchors: list[str] | None = None,
    additional_views: dict[str, str] | None = None,
) -> dict:
    """Create a job with immutable source files and one explicit content boundary."""
    if mode not in {"concept", "measured"}:
        raise ValueError("mode must be concept or measured")
    views = {kind: Path(path) for kind, path in (additional_views or {}).items()}
    return create_job_internal(
        job_id,
        Path(reference_path),
        mode,
        scale_anchors or [],
        views,
        reference_content_scope=reference_content_scope,
        target_subject=target_subject,
    )


@mcp.tool()
def add_view(
    job_id: str,
    kind: str,
    image_path: str,
    replace: bool = False,
    scale_anchors: list[str] | None = None,
) -> dict:
    """Safely add one front/right/top/blueprint/CAD view without recreating the job."""
    return add_job_view(
        job_id,
        kind.strip().lower(),
        Path(image_path),
        replace=replace,
        scale_anchors=scale_anchors or [],
    )


@mcp.tool()
def get_job_status(job_id: str) -> dict:
    """Return job metadata, artifact presence, and the read-only interior policy state."""
    root = job_dir(job_id)
    metadata = load_job(job_id)
    pdf_root = report_output_dir(job_id)
    files = {
        "reference_analysis": (root / "analysis" / "reference_analysis.json").exists(),
        "camera_solution": (root / "analysis" / "camera_solution.json").exists(),
        "modeling_plan": (root / "analysis" / "modeling_plan.json").exists(),
        "scene_spec": (root / "analysis" / "scene_spec.json").exists(),
        "interior_scope": (root / "architecture" / "interior_scope.json").exists(),
        "interior_scope_approval": (
            root / "architecture" / "interior_scope.approval.json"
        ).exists(),
        "constraints": (root / "constraints" / "constraints.json").exists(),
        "blend": (root / "blender" / "scene.blend").exists(),
        "preview": (root / "renders" / "preview.png").exists(),
        "inventory": (root / "reports" / "scene_inventory.json").exists(),
        "validation": (root / "reports" / "validation.json").exists(),
        "constraint_solution": (root / "reports" / "constraint_solution.json").exists(),
        "material_plan": (root / "analysis" / "material_plan.json").exists(),
        "material_contract_validation": (
            root / "reports" / "material_contract_validation.json"
        ).exists(),
        "material_validation": (root / "reports" / "material_validation.json").exists(),
        "material_bakes": (root / "reports" / "material_bakes.json").exists(),
        "surface_detail_validation": (
            root / "reports" / "surface_detail_validation.json"
        ).exists(),
        "interior_scope_validation": (
            root / "reports" / "interior_scope_validation.json"
        ).exists(),
        "qa_latest": (root / "qa" / "latest.json").exists(),
        "interior_qa_latest": (root / "qa" / "interior" / "latest.json").exists(),
        "optimization_latest": (root / "optimization" / "latest.json").exists(),
        "workflow_latest": (root / "workflows" / "latest.json").exists(),
        "build_pdf": (pdf_root / "build_report.pdf").exists(),
        "material_pdf": (pdf_root / "material_report.pdf").exists(),
        "qa_pdf": (pdf_root / "qa_report.pdf").exists(),
        "export_pdf": (pdf_root / "export_report.pdf").exists(),
        "full_pdf": (pdf_root / "full_report.pdf").exists(),
        "glb": (root / "exports" / "scene.glb").exists(),
    }
    return {
        "metadata": metadata,
        "files": files,
        "interior_scope": get_interior_scope_status_internal(job_id),
    }


@mcp.tool()
def get_modeling_capabilities() -> dict:
    """Return supported contracts, recipes, safety boundaries, and feature flags."""
    feature_config = load_feature_config()
    return {
        "project_version": PROJECT_VERSION,
        "scene_spec_version": SCENE_SPEC_VERSION,
        "analysis_schema_version": REFERENCE_SCHEMA_VERSION,
        "constraint_schema_version": CONSTRAINT_SCHEMA_VERSION,
        "material_schema_version": MATERIAL_SCHEMA_VERSION,
        "visual_qa_schema_version": VISUAL_QA_SCHEMA_VERSION,
        "portable_asset_schema_version": PORTABLE_ASSET_SCHEMA_VERSION,
        "interior_scope_schema_version": INTERIOR_SCOPE_SCHEMA_VERSION,
        "workflow_schema_version": WORKFLOW_SCHEMA_VERSION,
        "stabilization_schema_version": STABILIZATION_SCHEMA_VERSION,
        "destination_handoff_schema_version": DESTINATION_HANDOFF_SCHEMA_VERSION,
        "feature_flags": {
            "material_core": feature_config.features.material_core,
            "shader_core": feature_config.features.shader_core,
            "texture_provider": feature_config.features.texture_provider,
            "visual_qa": feature_config.features.visual_qa,
            "image_model_qa": feature_config.features.image_model_qa,
            "automatic_revision": feature_config.features.automatic_revision,
            "portable_asset_core": feature_config.features.portable_asset_core,
            "workflow_orchestration": (
                feature_config.features.workflow_orchestration
            ),
            "stabilization_core": feature_config.features.stabilization_core,
            "destination_handoff": feature_config.features.destination_handoff,
            "revision_mode": feature_config.qa.revision_mode,
            "max_revision_iterations": feature_config.qa.max_revision_iterations,
        },
        "blender_compatibility": {
            "designed_target": "Blender 5.0.1",
            "integration_verification": "run blender_compatibility_probe on each install",
            "render_engine_probe_order": ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"],
            "subprocess_stdin": "DEVNULL",
            "python_exit_code": 1,
        },
        "portable_asset_profiles": [
            "portable_gltf",
            "fbx_interchange",
            "obj_legacy",
        ],
        "surface_detail_routing": {
            "modeling_contract": "optional ModelingPlan 0.4.0 fields",
            "representations": ["texture_channels", "baked_decal", "omit"],
            "geometry_required_for": [
                "silhouette",
                "structural",
                "gameplay",
                "physical_transparency",
            ],
            "portable_material_requirement": (
                "exact TextureManifest surface_detail_ids, UVMap, and PBR channels"
            ),
            "qa_behavior": (
                "coverage is reported separately and never treated as geometry similarity"
            ),
        },
        "portable_cost_optimization": {
            "consolidation_modes": [
                "none",
                "by_semantic_group",
                "by_spatial_cell",
            ],
            "exact_instance_detection": "advisory",
            "overlap_detection": "positive-volume AABB candidates",
            "internal_face_removal": "not automatic",
            "runtime_draw_calls": "estimated until a destination adapter is tested",
            "pre_execution_review": "required for exact LOD and collider settings",
            "approval": "hash-bound, explicit, single-use user approval",
            "profile_change_after_review": "rejected; start a new run",
        },
        "workflow_orchestration": {
            "intents": [
                "new_asset",
                "revise_asset",
                "add_measured_view",
                "interior_scope",
                "interior_visual_qa",
                "material_authoring",
                "visual_qa",
                "portable_package",
            ],
            "default_new_asset_scope": "proxy_only",
            "reference_content_scopes": [
                "primary_object_only",
                "full_reference",
            ],
            "primary_object_only_requires": "explicit target_subject",
            "execution_policies": ["standard", "background_exterior"],
            "delivery_scopes": ["preview_only", "portable_package"],
            "background_exterior": {
                "opt_in_only": True,
                "eligible_assets": (
                    "new concept static exterior background assets, plus package-only "
                    "extension of an eligible existing job"
                ),
                "delivery_scope_behavior": (
                    "explicit only for background_exterior; standard keeps legacy scope"
                ),
                "generic_reviews_skipped": [
                    "proxy_geometry",
                    "detailed_geometry",
                    "material_swatches",
                    "qa_review",
                    "final_package",
                ],
                "specialized_approvals_preserved": ["optimization_plan"],
                "direct_qa_runs": 1,
                "generated_target": False,
                "automatic_revision": False,
                "automatic_revision_iterations": 0,
                "texture_resolution_cap": 512,
                "external_provider_budget": 0,
                "package_continuation_binding": (
                    "exact preview plan, terminal completion, QA run, "
                    "canonical source, and embedded build fingerprints"
                ),
                "disqualification_outcome": (
                    "blocked requires_standard_workflow; create a new standard workflow"
                ),
            },
            "resume": "ready deterministic host steps only",
            "agent_completion": "exact hash-bound completion marker",
            "generic_approval": "exact gate and artifact fingerprint only",
            "specialized_approvals": [
                "interior_scope",
                "interior_qa_plan",
                "visual_revision",
                "optimization_plan",
            ],
            "destination_default": "unspecified",
            "engine_adapters": "not installed; stop at V0.7 portable package",
        },
        "stabilization": {
            "environment_probe": "reuses hash-bound Blender evidence without rerunning it",
            "workspace_audit": "bounded and read-only for canonical job data",
            "local_queue": "single worker; existing workflows only",
            "failed_retry": "explicit requeue authorization required",
            "approval_behavior": "never synthesized or bypassed",
        },
        "interior_capabilities": {
            "default_policy": "disabled",
            "policies": ["disabled", "visible_only", "proxy", "measured", "authored"],
            "approval": "manual interactive CLI approval bound to exact scope SHA-256",
            "scene_spec_contract_unchanged": True,
            "multi_view_qa": {
                "profiles": ["minimal", "standard", "thorough"],
                "approval": "exact plan SHA-256, explicit, single-use",
                "passes_per_view": 7,
                "canonical_blend_mutated": False,
                "reference_score_without_mapped_views": False,
            },
        },
        "geometry_kinds": [
            "primitive",
            "custom_mesh",
            "profile_extrude",
            "revolve",
            "curve",
            "terrain",
        ],
        "modifier_kinds": [
            "bevel",
            "mirror",
            "subdivision",
            "solidify",
            "array",
            "decimate",
            "remesh",
            "boolean",
        ],
        "material_capabilities": {
            "presets": sorted(get_material_family_presets()),
            "source_channels": [
                "base_color",
                "roughness",
                "metallic",
                "normal",
                "height",
                "emission",
            ],
            "bake_channels": [
                "base_color",
                "roughness",
                "metallic",
                "normal",
                "emission",
            ],
            "mapping_modes": ["uv", "object", "generated", "triplanar"],
            "implemented_bake_profiles": [
                "blender_eevee",
                "blender_cycles",
                "gltf_pbr",
            ],
        },
        "human_reports": {
            "format": "pdf",
            "scopes": ["build", "material", "qa", "full"],
            "canonical_source": "machine-readable JSON remains authoritative",
        },
        "visual_qa_passes": [
            "beauty",
            "silhouette",
            "object_id",
            "material_id",
            "normal",
            "depth",
            "wireframe",
        ],
        "revision_mode": "ID-addressed guarded operations",
        "notes": [
            "Keep large mesh payloads in workspace geometry files instead of inline JSON.",
            "Use profile/revolve/curve/terrain recipes before custom vertex arrays.",
            "Single-view concept reconstruction remains approximate without scale/camera anchors.",
        ],
    }


@mcp.tool()
def plan_short_workflow(
    request: str,
    job_id: str | None = None,
    reference_path: str | None = None,
    intent: str = "auto",
    scope: str = "auto",
    reference_content_scope: str | None = None,
    target_subject: str | None = None,
    execution_policy: str = "standard",
    delivery_scope: str | None = None,
    mode: str = "concept",
    view_kind: str | None = None,
    replace_view: bool = False,
    scale_anchors: list[str] | None = None,
    profile_id: str = "portable_gltf",
    destination_kind: str = "unspecified",
    destination_name: str | None = None,
    destination_version: str | None = None,
    max_host_steps_per_resume: int = 8,
    max_qa_iterations: int = 1,
    max_texture_resolution: int = 2048,
    max_lod0_triangles: int | None = None,
    external_provider_budget: int = 0,
    include_destination_handoff: bool = False,
) -> dict:
    """Route one short request into an immutable, approval-aware V0.8 workflow."""

    state = plan_workflow_internal(
        request,
        job_id=job_id,
        reference_path=reference_path,
        intent=intent,
        scope=scope,
        reference_content_scope=reference_content_scope,
        target_subject=target_subject,
        execution_policy=execution_policy,
        delivery_scope=delivery_scope,
        mode=mode,
        view_kind=view_kind,
        replace_view=replace_view,
        scale_anchors=scale_anchors or [],
        profile_id=profile_id,
        destination_kind=destination_kind,
        destination_name=destination_name,
        destination_version=destination_version,
        include_destination_handoff=include_destination_handoff,
        budgets=WorkflowBudgets(
            max_host_steps_per_resume=max_host_steps_per_resume,
            max_qa_iterations=max_qa_iterations,
            max_texture_resolution=max_texture_resolution,
            max_lod0_triangles=max_lod0_triangles,
            external_provider_budget=external_provider_budget,
        ),
    )
    return state.model_dump(mode="json")


@mcp.tool()
def get_workflow_state(job_id: str, workflow_id: str | None = None) -> dict:
    """Read one persisted V0.8 workflow state without executing any work."""

    return get_workflow_status_internal(job_id, workflow_id)


@mcp.tool()
def reconcile_short_workflow(job_id: str, workflow_id: str) -> dict:
    """Reconstruct V0.8 state from exact files, fingerprints, and approvals."""

    return reconcile_workflow_internal(job_id, workflow_id).model_dump(mode="json")


@mcp.tool()
def resume_short_workflow(
    job_id: str,
    workflow_id: str,
    max_host_steps: int | None = None,
    retry_failed: bool = False,
) -> dict:
    """Run deterministic host steps and retry a failure only when explicitly requested."""

    return resume_workflow_internal(
        job_id,
        workflow_id,
        max_host_steps=max_host_steps,
        retry_failed=retry_failed,
    ).model_dump(mode="json")


@mcp.tool()
def record_workflow_step_completion(
    job_id: str,
    workflow_id: str,
    step_id: str,
    input_fingerprint: str,
    note: str,
) -> dict:
    """Record one exact agent-authored completion marker after output validation."""

    return complete_workflow_step_internal(
        job_id,
        workflow_id,
        step_id,
        input_fingerprint=input_fingerprint,
        note=note,
    ).model_dump(mode="json")


@mcp.tool()
def approve_workflow_checkpoint(
    job_id: str,
    workflow_id: str,
    step_id: str,
    artifact_fingerprint: str,
    approval_note: str,
) -> dict:
    """Approve one exact generic checkpoint without replacing specialized approvals."""

    return approve_workflow_gate_internal(
        job_id,
        workflow_id,
        step_id,
        artifact_fingerprint=artifact_fingerprint,
        approval_note=approval_note,
    ).model_dump(mode="json")


@mcp.tool()
def cancel_short_workflow(job_id: str, workflow_id: str, reason: str) -> dict:
    """Cancel future workflow execution while preserving every existing artifact."""

    return cancel_workflow_internal(
        job_id,
        workflow_id,
        reason=reason,
    ).model_dump(mode="json")


@mcp.tool()
def get_destination_adapters() -> dict:
    """List validated destination adapters and engine-neutral fallback behavior."""

    return destination_adapters_internal()


@mcp.tool()
def probe_release_environment(probe_id: str | None = None) -> dict:
    """Persist a privacy-safe V0.9 host snapshot from existing compatibility evidence."""

    return probe_release_environment_internal(probe_id=probe_id).model_dump(mode="json")


@mcp.tool()
def audit_workspace_state(
    job_id: str | None = None,
    audit_id: str | None = None,
    scan_limit: int | None = None,
) -> dict:
    """Audit canonical workspace evidence without repairing or migrating it."""

    return audit_workspace_state_internal(
        job_id=job_id,
        audit_id=audit_id,
        scan_limit=scan_limit,
    ).model_dump(mode="json")


@mcp.tool()
def generate_stability_pdf_report(
    probe_id: str,
    audit_id: str,
    report_id: str,
) -> dict:
    """Project strict V0.9 JSON evidence into one immutable human-readable PDF."""

    return generate_stability_pdf_report_internal(
        probe_id,
        audit_id,
        report_id=report_id,
    )


@mcp.tool()
def enqueue_local_workflow(
    job_id: str,
    workflow_id: str,
    priority: int = 50,
    max_attempts: int = 3,
) -> dict:
    """Queue one existing V0.8 workflow without creating jobs or approvals."""

    return enqueue_short_workflow_internal(
        job_id,
        workflow_id,
        priority=priority,
        max_attempts=max_attempts,
    ).model_dump(mode="json")


@mcp.tool()
def get_local_workflow_queue() -> dict:
    """Read V0.9 local queue state without executing any workflow."""

    return get_local_workflow_queue_internal().model_dump(mode="json")


@mcp.tool()
def run_local_workflow_queue(
    max_entries: int = 1,
    max_host_steps: int | None = None,
) -> dict:
    """Run bounded existing host steps and stop at every agent or approval boundary."""

    return run_local_workflow_queue_internal(
        max_entries=max_entries,
        max_host_steps=max_host_steps,
    ).model_dump(mode="json")


@mcp.tool()
def requeue_local_workflow(entry_id: str, retry_failed: bool = False) -> dict:
    """Requeue one failed entry only with explicit failed-step retry authorization."""

    return requeue_local_workflow_internal(
        entry_id,
        retry_failed=retry_failed,
    ).model_dump(mode="json")


@mcp.tool()
def cancel_local_workflow_queue_entry(entry_id: str, reason: str) -> dict:
    """Cancel future queue dispatch without cancelling the underlying workflow."""

    return cancel_local_queue_entry_internal(entry_id, reason=reason).model_dump(
        mode="json"
    )


@mcp.tool()
def blender_compatibility_probe(smoke_exports: bool = True) -> dict:
    """Probe the configured Blender build and optionally smoke-test GLB/OBJ/FBX exports."""
    settings = get_settings()
    report = settings.repo_root / "reports" / "blender_compatibility.json"
    export_dir = settings.repo_root / "reports" / "compat_exports"
    args = ["--output", str(report)]
    if smoke_exports:
        args.extend(["--smoke-exports", "--export-dir", str(export_dir)])
    run_blender("probe_compat.py", args)
    return json.loads(report.read_text(encoding="utf-8"))


@mcp.tool()
def analyze_reference(
    job_id: str,
    provider: str = "auto",
    projection: str = "auto",
    focal_length_mm: float | None = None,
    azimuth_deg: float | None = None,
    elevation_deg: float | None = None,
) -> dict:
    """Generate deterministic image diagnostics and a camera-solution scaffold."""
    if provider not in {"auto", "basic", "opencv"}:
        raise ValueError("provider must be auto, basic, or opencv")
    if projection not in {"auto", "persp", "ortho"}:
        raise ValueError("projection must be auto, persp, or ortho")
    return analyze_job_reference(
        job_id,
        provider=provider,
        projection_hint=projection,
        focal_length_mm=focal_length_mm,
        azimuth_deg=azimuth_deg,
        elevation_deg=elevation_deg,
    )


@mcp.tool()
def get_reference_analysis(job_id: str) -> dict:
    """Return the current deterministic reference analysis and camera scaffold."""
    return {
        "reference_analysis": load_reference_analysis(job_id).model_dump(mode="json"),
        "camera_solution": load_camera_solution(job_id).model_dump(mode="json"),
    }


@mcp.tool()
def initialize_interior_scope(
    job_id: str,
    policy: str = "disabled",
    request: str = "",
    allowed_semantic_prefixes: list[str] | None = None,
    excluded_semantic_prefixes: list[str] | None = None,
    levels: list[str] | None = None,
    spaces: list[str] | None = None,
    furnishing: str = "none",
    evidence_status: str | None = None,
    assumptions: list[str] | None = None,
    notes: list[str] | None = None,
    overwrite: bool = False,
) -> dict:
    """Create an interior scope draft; this operation never approves or changes geometry."""

    evidence_defaults = {
        "disabled": "not_applicable",
        "visible_only": "observed",
        "proxy": "inferred",
        "measured": "measured",
        "authored": "authored",
    }
    if policy not in evidence_defaults:
        raise ValueError(
            "policy must be disabled, visible_only, proxy, measured, or authored"
        )
    scope = initialize_interior_scope_internal(
        job_id,
        policy=policy,
        request=request,
        allowed_semantic_prefixes=allowed_semantic_prefixes or [],
        excluded_semantic_prefixes=excluded_semantic_prefixes or [],
        levels=levels or [],
        spaces=spaces or [],
        furnishing=furnishing,
        evidence_status=evidence_status or evidence_defaults[policy],
        assumptions=assumptions or [],
        notes=notes or [],
        overwrite=overwrite,
    )
    return {
        "scope": scope.model_dump(mode="json"),
        "status": get_interior_scope_status_internal(job_id),
    }


@mcp.tool()
def get_interior_scope_status(job_id: str) -> dict:
    """Return the effective default, draft, approval, or stale interior state."""

    return get_interior_scope_status_internal(job_id)


@mcp.tool()
def validate_interior_scope(job_id: str) -> dict:
    """Validate canonical interior objects and write a machine-readable safety report."""

    return validate_job_interior_scope(job_id, write_report=True).model_dump(mode="json")


@mcp.tool()
def plan_interior_qa(
    job_id: str,
    profile: str = "standard",
    resolution: int = 512,
    max_views: int = 24,
    eye_height_m: float = 1.6,
    run_id: str | None = None,
) -> dict:
    """Plan bounded multi-view interior cameras and stop for exact user approval."""

    if not load_feature_config().features.visual_qa:
        raise ValueError("visual_qa is disabled in cbm.toml")
    return plan_job_interior_qa(
        job_id,
        profile=profile,
        resolution=resolution,
        max_views=max_views,
        eye_height_m=eye_height_m,
        run_id=run_id,
    )


@mcp.tool()
def approve_interior_qa_plan(
    job_id: str,
    run_id: str,
    plan_sha256: str,
    approval_note: str,
    approved_view_ids: list[str] | None = None,
) -> dict:
    """Record approval only after the user accepts the exact interior camera-plan hash."""

    return approve_job_interior_qa_plan(
        job_id,
        run_id,
        plan_sha256=plan_sha256,
        approval_note=approval_note,
        approved_view_ids=approved_view_ids,
    ).model_dump(mode="json")


@mcp.tool()
def run_interior_qa(
    job_id: str,
    run_id: str,
    approved_plan_sha256: str,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict:
    """Consume one exact approval and render seven passes for each interior view."""

    if not load_feature_config().features.visual_qa:
        raise ValueError("visual_qa is disabled in cbm.toml")
    return run_job_interior_qa(
        job_id,
        run_id,
        approved_plan_sha256=approved_plan_sha256,
        render_engine=render_engine,
        render_device=render_device,
    )


@mcp.tool()
def get_interior_qa_status(job_id: str, run_id: str | None = None) -> dict:
    """Return current plan, approval, render, report, and stale-source status."""

    return get_job_interior_qa_status(job_id, run_id=run_id)


@mcp.tool()
def init_constraints(job_id: str, overwrite: bool = False) -> dict:
    """Create the measured-mode constraints contract without changing SceneSpec."""
    path = initialize_constraints(job_id, overwrite=overwrite)
    return {"ok": True, "path": str(path)}


@mcp.tool()
def evaluate_constraints(job_id: str) -> dict:
    """Evaluate measured constraints against reports/scene_inventory.json."""
    return evaluate_job_constraints(job_id).model_dump(mode="json")


@mcp.tool()
def initialize_materials(job_id: str, overwrite: bool = False) -> dict:
    """Create the V0.5 material plan and shader-recipe scaffold without changing SceneSpec."""

    features = load_feature_config().features
    if not features.material_core or not features.shader_core:
        raise ValueError("material_core and shader_core must be enabled in cbm.toml")
    plan = create_material_scaffold(job_id, overwrite=overwrite)
    return plan.model_dump(mode="json")


@mcp.tool()
def validate_material_contracts(job_id: str) -> dict:
    """Validate material IDs, recipes, texture manifests, paths, and color-space contracts."""

    return validate_job_material_contracts(job_id)


@mcp.tool()
def validate_surface_details(job_id: str) -> dict:
    """Validate non-mesh detail routing and exact V0.5 texture-manifest coverage."""

    return validate_job_surface_details(
        job_id,
        require_materials=None,
        write_report=True,
    ).model_dump(mode="json")


@mcp.tool()
def get_surface_detail_status(job_id: str) -> dict:
    """Return current surface-detail coverage without changing canonical or report files."""

    return validate_job_surface_details(
        job_id,
        require_materials=None,
        write_report=False,
    ).model_dump(mode="json")


@mcp.tool()
def get_material_presets() -> dict:
    """List deterministic offline PBR material-family presets."""

    return get_material_family_presets()


@mcp.tool()
def generate_procedural_textures(
    job_id: str,
    material_id: str,
    preset: str = "standard_pbr",
    channels: list[str] | None = None,
    resolution: int = 512,
    seed: int = 0,
    intended_scale_m: float = 1.0,
    prompt: str = "",
    uv_set: str = "Object",
    surface_detail_ids: list[str] | None = None,
    detail_pattern: str = "none",
    output_relative_dir: str | None = None,
    overwrite: bool = False,
    attach: bool = True,
) -> dict:
    """Generate deterministic local PBR maps and optionally attach their manifest."""

    config = load_feature_config()
    if config.features.texture_provider != "procedural":
        raise ValueError("features.texture_provider must be procedural")
    if resolution < 16 or resolution > 8192:
        raise ValueError("resolution must be within [16, 8192]")
    if seed < 0:
        raise ValueError("seed must be non-negative")
    return generate_job_procedural_textures(
        job_id,
        material_id,
        preset=preset,
        channels=channels
        or [
            "base_color",
            "roughness",
            "metallic",
            "normal",
            "height",
            "emission",
        ],
        resolution=(resolution, resolution),
        seed=seed,
        intended_scale_m=intended_scale_m,
        prompt=prompt,
        uv_set=uv_set,
        surface_detail_ids=surface_detail_ids or [],
        detail_pattern=detail_pattern,
        output_relative_dir=output_relative_dir,
        overwrite=overwrite,
        attach=attach,
    )


@mcp.tool()
def attach_texture_manifest(
    job_id: str,
    material_id: str,
    manifest_path: str,
) -> dict:
    """Attach one validated job-local texture manifest to a stable material ID."""

    return attach_texture_manifest_to_plan(
        job_id,
        material_id,
        manifest_path,
    ).model_dump(mode="json")


@mcp.tool()
def bake_materials(
    job_id: str,
    profile: str = "gltf_pbr",
    resolution: int = 1024,
    margin_px: int = 16,
    render_device: str = "auto",
    material_ids: list[str] | None = None,
    strict: bool = True,
) -> dict:
    """Bake bounded portable PBR channels from the latest approved Blender scene."""

    if profile not in {"blender_eevee", "blender_cycles", "gltf_pbr"}:
        raise ValueError(
            "profile must be blender_eevee, blender_cycles, or gltf_pbr"
        )
    if render_device not in {"auto", "cpu", "gpu"}:
        raise ValueError("render_device must be auto, cpu, or gpu")
    return bake_job_materials(
        job_id,
        profile=profile,  # type: ignore[arg-type]
        resolution=resolution,
        margin_px=margin_px,
        render_device=render_device,  # type: ignore[arg-type]
        material_ids=material_ids,
        strict=strict,
    )


@mcp.tool()
def inspect_materials(job_id: str) -> dict:
    """Inspect applied Blender shader graphs, images, UVs, and texel-density estimates."""

    return inspect_job_materials(job_id)


@mcp.tool()
def render_material_swatches(
    job_id: str,
    render_engine: str = "eevee",
    render_device: str = "auto",
    size: int = 512,
    material_ids: list[str] | None = None,
) -> dict:
    """Render fixed sphere and plane previews for stable material IDs."""

    if render_engine not in {"eevee", "cycles"}:
        raise ValueError("render_engine must be eevee or cycles")
    if render_device not in {"auto", "cpu", "gpu"}:
        raise ValueError("render_device must be auto, cpu, or gpu")
    if render_engine == "eevee" and render_device != "auto":
        raise ValueError("render_device must be auto when render_engine is eevee")
    if size < 128 or size > 2048:
        raise ValueError("size must be within [128, 2048]")
    return render_job_material_swatches(
        job_id,
        render_engine=render_engine,
        render_device=render_device,
        size=size,
        material_ids=material_ids,
    )


@mcp.tool()
def generate_pdf_report(
    job_id: str,
    scope: str = "full",
    qa_run_id: str = "latest",
    interior_qa_run_id: str = "latest",
    optimization_run_id: str = "latest",
    package_id: str = "latest",
) -> dict:
    """Generate a human-readable Korean PDF from canonical job reports and images."""

    if scope not in {"build", "material", "qa", "export", "full"}:
        raise ValueError("scope must be build, material, qa, export, or full")
    return generate_job_pdf_report(
        job_id,
        scope=scope,  # type: ignore[arg-type]
        qa_run_id=qa_run_id,
        interior_qa_run_id=interior_qa_run_id,
        optimization_run_id=optimization_run_id,
        package_id=package_id,
    )


@mcp.tool()
def run_visual_qa(
    job_id: str,
    render_engine: str = "eevee",
    render_device: str = "auto",
    run_id: str | None = None,
    include_generated_target: bool = False,
    target_image_path: str | None = None,
    target_model: str = "external-image-model",
    target_model_version: str | None = None,
    target_seed: int | None = None,
    target_allowed_root: str | None = None,
    target_prompt: str | None = None,
) -> dict:
    """Run direct QA and optionally import one explicit advisory target image."""

    config = load_feature_config()
    include_target = include_generated_target or target_image_path is not None
    if not config.features.visual_qa:
        raise ValueError("visual_qa is disabled in cbm.toml")
    if include_target and not config.features.image_model_qa:
        raise ValueError("image_model_qa is disabled in cbm.toml")
    if include_generated_target and target_image_path is None:
        raise ValueError(
            "No bundled image generator is configured; provide target_image_path for the "
            "explicitly generated advisory image."
        )
    if target_seed is not None and target_seed < 0:
        raise ValueError("target_seed must be non-negative")
    if target_image_path is not None and not (target_prompt or "").strip():
        raise ValueError(
            "target_image_path requires the exact non-empty target_prompt used to create it"
        )
    provider = (
        ExistingFileQATargetProvider(
            Path(target_image_path),
            model=target_model,
            model_version=target_model_version,
            seed=target_seed,
            allowed_root=Path(target_allowed_root) if target_allowed_root else None,
        )
        if target_image_path is not None
        else None
    )
    return run_job_visual_qa(
        job_id,
        render_engine=render_engine,
        render_device=render_device,
        run_id=run_id,
        include_generated_target=include_target,
        provider=provider,
        target_prompt=target_prompt.strip() if target_prompt else None,
    )


@mcp.tool()
def compile_visual_revision(
    job_id: str,
    run_id: str,
    selected_candidate_ids: list[str],
    request: str,
) -> dict:
    """Compile selected safe QA candidates while leaving them explicitly unapproved."""

    if load_feature_config().qa.revision_mode == "off":
        raise ValueError("qa.revision_mode is off in cbm.toml")
    return compile_job_qa_revision(
        job_id,
        run_id,
        selected_candidate_ids=selected_candidate_ids,
        request=request,
    )


@mcp.tool()
def approve_visual_revision(
    job_id: str,
    run_id: str,
    approved_candidate_ids: list[str],
) -> dict:
    """Record explicit user approval; callers must not invoke this without that approval."""

    if load_feature_config().qa.revision_mode not in {"approve", "auto"}:
        raise ValueError("qa.revision_mode must be approve or auto in cbm.toml")
    return approve_job_qa_revision(
        job_id,
        run_id,
        approved_candidate_ids=approved_candidate_ids,
    )


@mcp.tool()
def apply_approved_visual_revision(
    job_id: str,
    run_id: str,
    render_engine: str = "eevee",
    render_device: str = "auto",
    minimum_improvement: float = 0.001,
) -> dict:
    """Apply one explicit approval, verify once, and restore the baseline on regression."""

    config = load_feature_config()
    if config.qa.revision_mode not in {"approve", "auto"}:
        raise ValueError("qa.revision_mode must be approve or auto in cbm.toml")
    if config.qa.max_revision_iterations < 1:
        raise ValueError("qa.max_revision_iterations must allow one iteration")
    return apply_job_approved_revision(
        job_id,
        run_id,
        run_pipeline=True,
        render_engine=render_engine,
        render_device=render_device,
        minimum_improvement=minimum_improvement,
    )


@mcp.tool()
def plan_visual_convergence(
    job_id: str,
    initial_qa_run_id: str,
    target_direct_score: float,
    target_silhouette_iou: float,
    allowed_target_ids: list[str] | None = None,
    session_id: str | None = None,
    minimum_iteration_gain: float = 0.001,
    minimum_candidate_confidence: float = 0.8,
    max_iterations: int = 3,
    max_candidate_groups_per_iteration: int = 3,
    max_candidates_per_iteration: int = 12,
    max_changed_ids_per_iteration: int = 6,
    path_limits: list[dict] | None = None,
) -> dict:
    """Plan a standard-only exact-hash envelope; limits may only narrow host policy."""

    if not load_feature_config().features.visual_qa:
        raise ValueError("visual_qa is disabled in cbm.toml")
    strict_path_limits = (
        [ConvergencePathLimit.model_validate(item) for item in path_limits]
        if path_limits is not None
        else None
    )
    return plan_job_visual_convergence(
        job_id,
        initial_qa_run_id,
        target_direct_score=target_direct_score,
        target_silhouette_iou=target_silhouette_iou,
        allowed_target_ids=allowed_target_ids,
        session_id=session_id,
        minimum_iteration_gain=minimum_iteration_gain,
        minimum_candidate_confidence=minimum_candidate_confidence,
        max_iterations=max_iterations,
        max_candidate_groups_per_iteration=max_candidate_groups_per_iteration,
        max_candidates_per_iteration=max_candidates_per_iteration,
        max_changed_ids_per_iteration=max_changed_ids_per_iteration,
        path_limits=strict_path_limits,
    )


@mcp.tool()
def approve_visual_convergence(
    job_id: str,
    session_id: str,
    plan_sha256: str,
    approval_note: str,
) -> dict:
    """Record exact user approval; callers must not infer it from a general request."""

    return approve_job_visual_convergence(
        job_id,
        session_id,
        plan_sha256=plan_sha256,
        approval_note=approval_note,
    )


@mcp.tool()
def run_visual_convergence(
    job_id: str,
    session_id: str,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict:
    """Run or recover at most one full exact-plan-approved iteration per call."""

    if not load_feature_config().features.visual_qa:
        raise ValueError("visual_qa is disabled in cbm.toml")
    return run_job_visual_convergence(
        job_id,
        session_id,
        render_engine=render_engine,
        render_device=render_device,
    )


@mcp.tool()
def get_visual_convergence_status(
    job_id: str,
    session_id: str,
) -> dict:
    """Inspect one convergence session read-only even after feature deactivation."""

    return get_job_visual_convergence_status(job_id, session_id)


@mcp.tool()
def cancel_visual_convergence(
    job_id: str,
    session_id: str,
    reason: str,
) -> dict:
    """Cancel one approved active session without authorizing another revision."""

    return cancel_job_visual_convergence(
        job_id,
        session_id,
        reason=reason,
    )


@mcp.tool()
def apply_revision_plan(job_id: str) -> dict:
    """Apply analysis/revision_plan.json without allowing unrelated SceneSpec fields to change."""

    root = ensure_job_dirs(job_id)
    current = root / "analysis" / "scene_spec.json"
    plan = root / "analysis" / "revision_plan.json"
    temp = (
        root
        / "analysis"
        / f".scene_spec.mcp-apply-revision-{uuid4().hex}.next.json"
    )
    owner = f"mcp-apply-revision-{uuid4().hex[:12]}"
    with canonical_scene_spec_write_lock(job_id, owner):
        _validated, report = apply_guarded_revision(
            scene_spec_path=current,
            plan_path=plan,
            output_path=temp,
        )
        replacement = replace_scene_spec_if_current(
            job_id,
            temp,
            expected_current_sha256=report["base_spec_sha256"],
            expected_candidate_sha256=sha256_file(temp),
            lock_owner_id=owner,
        )
    temp.unlink(missing_ok=True)
    report_path = root / "reports" / "revision_diff.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "scene_spec": str(current),
        "archived": replacement["archived_scene_spec"],
        "report": str(report_path),
        "changes": report["changes"],
    }


@mcp.tool()
def initialize_asset_profile(
    job_id: str,
    profile_id: str = "portable_gltf",
    asset_kind: str = "static_prop",
    consolidation_mode: str = "by_semantic_group",
    spatial_cell_size_m: float = 25.0,
    maximum_objects_per_batch: int = 64,
    lod_mode: str = "profile_default",
    generate_uv1: bool | None = None,
    pivot_policy: str = "keep",
    collision_strategy: str = "profile_default",
    max_collider_hulls_per_object: int = 8,
    max_collider_triangles_per_object: int = 256,
    budget_enforcement: str = "warning",
    max_lod0_render_objects: int | None = None,
    max_lod0_material_slots: int | None = None,
    max_lod0_estimated_draw_calls: int | None = None,
    max_lod0_triangles: int | None = None,
    max_collider_triangles: int | None = None,
    max_overlap_candidates: int | None = None,
    overwrite: bool = False,
) -> dict:
    """Initialize one profile with explicit LOD, collider, batching, and cost controls."""

    if asset_kind not in {"static_prop", "static_environment", "static_architecture"}:
        raise ValueError(
            "asset_kind must be static_prop, static_environment, or static_architecture"
        )
    if consolidation_mode not in {"none", "by_semantic_group", "by_spatial_cell"}:
        raise ValueError(
            "consolidation_mode must be none, by_semantic_group, or by_spatial_cell"
        )
    if lod_mode not in {"profile_default", "enabled", "disabled"}:
        raise ValueError("lod_mode must be profile_default, enabled, or disabled")
    if pivot_policy not in {"keep", "bounds_center", "base_center"}:
        raise ValueError("pivot_policy must be keep, bounds_center, or base_center")
    if collision_strategy not in {
        "profile_default",
        "none",
        "box",
        "sphere",
        "capsule",
        "convex_hull",
        "compound",
        "mesh_proxy",
    }:
        raise ValueError("Unsupported collision_strategy")
    result = initialize_asset_profile_internal(
        job_id,
        profile_id=profile_id,
        asset_kind=asset_kind,  # type: ignore[arg-type]
        consolidation_mode=consolidation_mode,  # type: ignore[arg-type]
        spatial_cell_size_m=spatial_cell_size_m,
        maximum_objects_per_batch=maximum_objects_per_batch,
        lod_mode=lod_mode,  # type: ignore[arg-type]
        generate_uv1=generate_uv1,
        pivot_policy=pivot_policy,  # type: ignore[arg-type]
        collision_strategy=collision_strategy,  # type: ignore[arg-type]
        max_collider_hulls_per_object=max_collider_hulls_per_object,
        max_collider_triangles_per_object=max_collider_triangles_per_object,
        budget_enforcement=budget_enforcement,
        max_lod0_render_objects=max_lod0_render_objects,
        max_lod0_material_slots=max_lod0_material_slots,
        max_lod0_estimated_draw_calls=max_lod0_estimated_draw_calls,
        max_lod0_triangles=max_lod0_triangles,
        max_collider_triangles=max_collider_triangles,
        max_overlap_candidates=max_overlap_candidates,
        overwrite=overwrite,
    )
    return result.model_dump(mode="json")


@mcp.tool()
def run_asset_preflight(
    job_id: str,
    profile_id: str = "portable_gltf",
    run_id: str | None = None,
) -> dict:
    """Run read-only topology and portability checks against the canonical Blender scene."""

    return preflight_asset_internal(
        job_id,
        profile_id=profile_id,
        run_id=run_id,
    ).model_dump(mode="json")


@mcp.tool()
def plan_portable_asset_optimization(
    job_id: str,
    profile_id: str = "portable_gltf",
    run_id: str | None = None,
) -> dict:
    """Return exact planned LOD and collider settings without running optimization."""

    return plan_asset_optimization_internal(
        job_id,
        profile_id=profile_id,
        run_id=run_id,
    ).model_dump(mode="json")


@mcp.tool()
def approve_portable_asset_optimization(
    job_id: str,
    run_id: str,
    plan_sha256: str,
    approval_note: str,
) -> dict:
    """Record approval only after the user accepts the exact reviewed plan hash."""

    return approve_asset_optimization_internal(
        job_id,
        run_id=run_id,
        plan_sha256=plan_sha256,
        approval_note=approval_note,
    ).model_dump(mode="json")


@mcp.tool()
def optimize_portable_asset(
    job_id: str,
    approved_plan_sha256: str,
    profile_id: str = "portable_gltf",
    run_id: str | None = None,
) -> dict:
    """Execute one reviewed, approved, hash-bound optimization run exactly once."""

    return optimize_asset_internal(
        job_id,
        profile_id=profile_id,
        run_id=run_id,
        approved_plan_sha256=approved_plan_sha256,
    ).model_dump(mode="json")


@mcp.tool()
def build_portable_package(
    job_id: str,
    profile_id: str = "portable_gltf",
    run_id: str | None = None,
    package_id: str | None = None,
    material_conversion_id: str | None = None,
    include_colliders: bool = True,
) -> dict:
    """Build one immutable engine-neutral package from a complete optimization run."""

    return package_asset_internal(
        job_id,
        profile_id=profile_id,
        run_id=run_id,
        package_id=package_id,
        material_conversion_id=material_conversion_id,
        include_colliders=include_colliders,
    ).model_dump(mode="json")


@mcp.tool()
def convert_portable_materials(
    job_id: str,
    run_id: str,
    conversion_id: str,
    profile_id: str = "portable_gltf",
    resolution: int = 1024,
    margin_px: int = 16,
    render_device: str = "auto",
) -> dict:
    """Create a hash-bound run-owned PBR material conversion for portable packaging."""

    if resolution < 16:
        raise ValueError("resolution must be at least 16")
    if margin_px < 1:
        raise ValueError("margin_px must be positive")
    if render_device not in {"auto", "cpu", "gpu"}:
        raise ValueError("render_device must be auto, cpu, or gpu")
    return convert_portable_materials_internal(
        job_id,
        profile_id=profile_id,
        run_id=run_id,
        conversion_id=conversion_id,
        resolution=resolution,
        margin_px=margin_px,
        render_device=render_device,
    ).model_dump(mode="json")


@mcp.tool()
def validate_portable_package(
    job_id: str,
    package_id: str,
    profile_id: str = "portable_gltf",
    bounds_tolerance_m: float = 0.0001,
) -> dict:
    """Clean-import an immutable package and validate IDs, materials, bounds, and paths."""

    if bounds_tolerance_m <= 0:
        raise ValueError("bounds_tolerance_m must be positive")
    return validate_asset_package_internal(
        job_id,
        package_id,
        profile_id=profile_id,
        bounds_tolerance_m=bounds_tolerance_m,
    ).model_dump(mode="json")


@mcp.tool()
def get_portable_asset_status(job_id: str) -> dict:
    """Return profiles, runs, packages, and validation evidence for one job."""

    return get_asset_status_internal(job_id)


@mcp.tool()
def plan_destination_handoff(
    job_id: str,
    profile_id: str,
    package_id: str,
    handoff_id: str | None = None,
    destination_hint: str | None = None,
) -> dict:
    """Plan a hash-bound handoff without modifying a package or destination project."""

    return plan_destination_handoff_internal(
        job_id,
        profile_id=profile_id,
        package_id=package_id,
        handoff_id=handoff_id,
        destination_hint=destination_hint,
    ).model_dump(mode="json")


@mcp.tool()
def generate_destination_handoff(
    job_id: str,
    handoff_id: str,
    plan_sha256: str,
) -> dict:
    """Generate one immutable source-side handoff from the exact plan digest."""

    return generate_destination_handoff_internal(
        job_id,
        handoff_id,
        approved_plan_sha256=plan_sha256,
    ).model_dump(mode="json")


@mcp.tool()
def validate_destination_handoff(
    job_id: str,
    profile_id: str,
    package_id: str,
    handoff_id: str,
) -> dict:
    """Read-only verify handoff receipts, source binding, and reconstruction contracts."""

    return validate_destination_handoff_internal(
        job_id,
        profile_id=profile_id,
        package_id=package_id,
        handoff_id=handoff_id,
    ).model_dump(mode="json")


@mcp.tool()
def get_destination_handoff_status(job_id: str) -> dict:
    """Return planned, generated, valid, invalid, and stale handoff state."""

    return get_destination_handoff_status_internal(job_id)


@mcp.tool()
def build_scene(
    job_id: str,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict:
    """Build the Blender scene deterministically from the job SceneSpec."""
    if render_engine not in {"eevee", "cycles"}:
        raise ValueError("render_engine must be eevee or cycles")
    if render_device not in {"auto", "cpu", "gpu"}:
        raise ValueError("render_device must be auto, cpu, or gpu")
    if render_engine == "eevee" and render_device != "auto":
        raise ValueError("render_device must be auto when render_engine is eevee")
    root = ensure_job_dirs(job_id)
    spec = root / "analysis" / "scene_spec.json"
    parsed = load_scene_spec(spec)
    validate_job_surface_details(
        job_id,
        require_materials=None,
        write_report=True,
        raise_on_error=True,
    )
    output = root / "blender" / "scene.blend"
    result = run_blender(
        "build_scene.py",
        [
            "--spec",
            str(spec),
            "--output",
            str(output),
            "--render-engine",
            render_engine,
            "--render-device",
            render_device,
        ],
    )
    return {
        "ok": True,
        "objects_requested": len(parsed.objects),
        "blend": str(output),
        "log": result.stdout[-4000:],
    }


@mcp.tool()
def render_preview(
    job_id: str,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict:
    """Render the fixed comparison camera to renders/preview.png."""
    if render_engine not in {"eevee", "cycles"}:
        raise ValueError("render_engine must be eevee or cycles")
    if render_device not in {"auto", "cpu", "gpu"}:
        raise ValueError("render_device must be auto, cpu, or gpu")
    if render_engine == "eevee" and render_device != "auto":
        raise ValueError("render_device must be auto when render_engine is eevee")
    root = ensure_job_dirs(job_id)
    blend = root / "blender" / "scene.blend"
    output = root / "renders" / "preview.png"
    result = run_blender(
        "render_preview.py",
        [
            "--output",
            str(output),
            "--render-engine",
            render_engine,
            "--render-device",
            render_device,
        ],
        blend_file=blend,
    )
    return {"ok": True, "preview": str(output), "log": result.stdout[-4000:]}


@mcp.tool()
def inspect_scene(job_id: str) -> dict:
    """Write and return a machine-readable object/material inventory."""
    root = ensure_job_dirs(job_id)
    blend = root / "blender" / "scene.blend"
    output = root / "reports" / "scene_inventory.json"
    run_blender("inspect_scene.py", ["--output", str(output)], blend_file=blend)
    return json.loads(output.read_text(encoding="utf-8"))


@mcp.tool()
def validate_scene(job_id: str) -> dict:
    """Validate SceneSpec, InteriorScope, object links, transforms, and Blender output."""
    root = ensure_job_dirs(job_id)
    spec = root / "analysis" / "scene_spec.json"
    load_scene_spec(spec)
    validate_job_interior_scope(job_id, write_report=True)
    validate_job_surface_details(
        job_id,
        require_materials=None,
        write_report=True,
        raise_on_error=True,
    )
    blend = root / "blender" / "scene.blend"
    output = root / "reports" / "validation.json"
    run_blender(
        "validate_scene.py",
        ["--spec", str(spec), "--output", str(output)],
        blend_file=blend,
    )
    return json.loads(output.read_text(encoding="utf-8"))


@mcp.tool()
def export_scene(job_id: str, format: str = "glb") -> dict:
    """Export the generated scene as glb, gltf, obj, or fbx."""
    if format not in {"glb", "gltf", "obj", "fbx"}:
        raise ValueError("format must be glb, gltf, obj, or fbx")
    root = ensure_job_dirs(job_id)
    blend = root / "blender" / "scene.blend"
    suffix = ".glb" if format == "glb" else f".{format}"
    output = root / "exports" / f"scene{suffix}"
    run_blender("export_scene.py", ["--format", format, "--output", str(output)], blend_file=blend)
    return {"ok": True, "path": str(output)}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
