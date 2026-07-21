from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .analysis import analyze_job_reference, load_camera_solution, load_reference_analysis
from .architecture import (
    get_interior_scope_status as get_interior_scope_status_internal,
)
from .architecture import (
    initialize_interior_scope as initialize_interior_scope_internal,
)
from .architecture import validate_job_interior_scope
from .auto_revision import (
    apply_job_approved_revision,
    approve_job_qa_revision,
    compile_job_qa_revision,
)
from .baking import bake_job_materials
from .blender_artifact_runner import (
    inspect_job_materials,
    render_job_material_swatches,
)
from .blender_runner import run_blender
from .config import get_settings, load_feature_config
from .constraints import evaluate_job_constraints, initialize_constraints
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
from .texturing import (
    attach_texture_manifest_to_plan,
    generate_job_procedural_textures,
    get_material_family_presets,
)
from .validation import load_scene_spec
from .versioning import (
    CONSTRAINT_SCHEMA_VERSION,
    INTERIOR_SCOPE_SCHEMA_VERSION,
    MATERIAL_SCHEMA_VERSION,
    PORTABLE_ASSET_SCHEMA_VERSION,
    PROJECT_VERSION,
    REFERENCE_SCHEMA_VERSION,
    SCENE_SPEC_VERSION,
    VISUAL_QA_SCHEMA_VERSION,
    WORKFLOW_SCHEMA_VERSION,
)
from .workspace import add_job_view, archive_scene_spec, ensure_job_dirs, job_dir, load_job
from .workspace import create_job as create_job_internal

mcp = FastMCP(
    "codex-blender-modeler",
    instructions=(
        "Project v0.8.0 adds deterministic short-request routing, artifact freshness, "
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
    scale_anchors: list[str] | None = None,
    additional_views: dict[str, str] | None = None,
) -> dict:
    """Create a job and copy immutable reference/blueprint images into the workspace."""
    if mode not in {"concept", "measured"}:
        raise ValueError("mode must be concept or measured")
    views = {kind: Path(path) for kind, path in (additional_views or {}).items()}
    return create_job_internal(job_id, Path(reference_path), mode, scale_anchors or [], views)


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
        "interior_scope_validation": (
            root / "reports" / "interior_scope_validation.json"
        ).exists(),
        "qa_latest": (root / "qa" / "latest.json").exists(),
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
                "material_authoring",
                "visual_qa",
                "portable_package",
            ],
            "default_new_asset_scope": "proxy_only",
            "resume": "ready deterministic host steps only",
            "agent_completion": "exact hash-bound completion marker",
            "generic_approval": "exact gate and artifact fingerprint only",
            "specialized_approvals": [
                "interior_scope",
                "visual_revision",
                "optimization_plan",
            ],
            "destination_default": "unspecified",
            "engine_adapters": "not installed; stop at V0.7 portable package",
        },
        "interior_capabilities": {
            "default_policy": "disabled",
            "policies": ["disabled", "visible_only", "proxy", "measured", "authored"],
            "approval": "manual interactive CLI approval bound to exact scope SHA-256",
            "scene_spec_contract_unchanged": True,
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
) -> dict:
    """Route one short request into an immutable, approval-aware V0.8 workflow."""

    state = plan_workflow_internal(
        request,
        job_id=job_id,
        reference_path=reference_path,
        intent=intent,
        scope=scope,
        mode=mode,
        view_kind=view_kind,
        replace_view=replace_view,
        scale_anchors=scale_anchors or [],
        profile_id=profile_id,
        destination_kind=destination_kind,
        destination_name=destination_name,
        destination_version=destination_version,
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
def apply_revision_plan(job_id: str) -> dict:
    """Apply analysis/revision_plan.json without allowing unrelated SceneSpec fields to change."""
    root = ensure_job_dirs(job_id)
    current = root / "analysis" / "scene_spec.json"
    plan = root / "analysis" / "revision_plan.json"
    temp = root / "analysis" / "scene_spec.next.json"
    _validated, report = apply_guarded_revision(
        scene_spec_path=current,
        plan_path=plan,
        output_path=temp,
    )
    archived = archive_scene_spec(job_id)
    temp.replace(current)
    report_path = root / "reports" / "revision_diff.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "scene_spec": str(current),
        "archived": str(archived) if archived else None,
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
