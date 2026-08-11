from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from rich.console import Console
from rich.table import Table

from .analysis import (
    analyze_job_reference,
    load_modeling_plan,
    validate_job_surface_details,
)
from .architecture import (
    approve_interior_scope,
    get_interior_scope_status,
    initialize_interior_scope,
    validate_job_interior_scope,
)
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
from .auto_revision.candidate_review_service import (
    approve_candidate_review,
    get_candidate_review_status,
    recover_failed_candidate_review_promotion,
)
from .autonomy.planner import plan_autonomous_static_prop
from .autonomy.profiles import get_autonomy_profile_status
from .autonomy_v2 import (
    advance_autonomy_v2,
    autonomy_v2_profile_status,
    cancel_autonomy_v2,
    delivery_profile_catalog,
    get_autonomy_v2_status,
    plan_autonomous_static_prop_v2,
    run_autonomy_v2,
)
from .autonomy_v2.codex_image_planner import (
    plan_autonomous_static_prop_v2_codex_imagegen,
)
from .baking import bake_job_materials
from .blender_artifact_runner import (
    inspect_job_materials,
    render_job_material_swatches,
)
from .blender_runner import run_blender
from .codex_imagegen.command_service import (
    adopt_codex_imagegen_material_phase,
    get_codex_imagegen_public_status,
    prepare_codex_imagegen_material_adoption,
    run_codex_imagegen_controller_phase,
    select_codex_imagegen_phase,
)
from .codex_runner import run_codex_json
from .config import executable_exists, get_settings, load_feature_config
from .constraints import evaluate_job_constraints, initialize_constraints
from .external_intake import (
    approve_external_static_asset_intake,
    get_external_static_asset_intake_status,
    normalize_external_static_asset,
    plan_external_static_asset_intake,
    validate_external_static_asset_intake,
)
from .handoff import (
    generate_destination_handoff,
    get_destination_handoff_status,
    plan_destination_handoff,
    validate_destination_handoff,
)
from .integrated_quality import (
    get_integrated_quality_status,
    run_integrated_quality,
)
from .interior_qa import (
    approve_job_interior_qa_plan,
    get_job_interior_qa_status,
    plan_job_interior_qa,
    run_job_interior_qa,
)
from .materials import (
    create_material_scaffold,
    load_material_plan,
    validate_job_material_contracts,
    validate_job_material_fidelity,
)
from .migration import migrate_v1_file
from .optimization import (
    approve_asset_optimization,
    initialize_asset_profile,
    optimize_asset,
    plan_asset_optimization,
    preflight_asset,
)
from .optimization import (
    asset_status as get_asset_status,
)
from .orchestration import (
    approve_workflow_gate,
    cancel_workflow,
    complete_workflow_step,
    destination_adapters,
    get_workflow_status,
    reconcile_workflow,
    resume_workflow,
)
from .orchestration import (
    plan_workflow as plan_orchestrated_workflow,
)
from .orchestration.models import WorkflowBudgets
from .packaging import package_asset, validate_asset_package
from .packaging.material_conversion import convert_portable_materials
from .production import (
    advance_delegated_production_controller,
    bind_asset_production_task,
    create_asset_production_dispatch,
    get_asset_production_dispatch_status,
    record_delegated_production_step,
)
from .production.controller_executor import controller_capability_catalog
from .qa import (
    ExistingFileQATargetProvider,
    get_job_semantic_reference_mask_status,
    plan_job_assembly_multiview_sanity,
    register_job_semantic_reference_masks,
    run_job_assembly_multiview_sanity,
    run_job_visual_diagnostics,
    run_job_visual_qa,
)
from .reporting import generate_job_pdf_report, report_output_dir
from .revision import apply_revision_plan, sha256_file
from .stabilization import (
    audit_workspace_state,
    cancel_local_workflow_queue_entry,
    enqueue_short_workflow,
    generate_stability_pdf_report,
    get_local_workflow_queue,
    probe_release_environment,
    requeue_local_workflow,
    run_local_workflow_queue,
)
from .structural_geometry.migration_service import (
    apply_scene_spec_v03_migration,
    plan_scene_spec_v03_migration,
)
from .texturing import (
    attach_texture_manifest_to_plan,
    generate_job_procedural_textures,
    get_material_family_presets,
)
from .validation import load_scene_spec
from .versioning import PROJECT_VERSION
from .workspace import (
    add_job_view,
    canonical_scene_spec_write_lock,
    create_job,
    ensure_job_dirs,
    find_input_images,
    job_dir,
    load_job,
    metadata_path,
    replace_scene_spec_if_current,
)

app = typer.Typer(no_args_is_help=True, help="Codex Blender Modeler CLI")
console = Console()


def _scene_spec_path(job_id: str) -> Path:
    """Resolve the canonical geometry contract for one job."""

    return job_dir(job_id) / "analysis" / "scene_spec.json"


def _scene_spec_candidate_path(job_id: str, operation: str) -> Path:
    """Create one collision-resistant job-local candidate path for a CLI writer."""

    return job_dir(job_id) / "analysis" / f".scene_spec.{operation}-{uuid4().hex}.next.json"


def _cli_scene_spec_lock_owner(operation: str) -> str:
    """Create one valid shared-lock owner ID for a canonical CLI operation."""

    return f"cli-{operation}-{uuid4().hex[:12]}"


def _promote_cli_scene_spec(
    job_id: str,
    candidate_path: Path,
    *,
    expected_current_sha256: str | None,
    operation: str,
) -> dict:
    """Serialize and compare-promote one validated CLI SceneSpec candidate."""

    candidate_sha256 = sha256_file(candidate_path)
    owner = _cli_scene_spec_lock_owner(operation)
    with canonical_scene_spec_write_lock(job_id, owner):
        result = replace_scene_spec_if_current(
            job_id,
            candidate_path,
            expected_current_sha256=expected_current_sha256,
            expected_candidate_sha256=candidate_sha256,
            lock_owner_id=owner,
        )
    candidate_path.unlink(missing_ok=True)
    return result


def _validate_render_options(render_engine: str, render_device: str) -> None:
    """Reject renderer/device combinations unsupported by deterministic runners."""

    if render_engine not in {"eevee", "cycles"}:
        raise typer.BadParameter("render-engine must be eevee or cycles")
    if render_device not in {"auto", "cpu", "gpu"}:
        raise typer.BadParameter("render-device must be auto, cpu, or gpu")
    if render_engine == "eevee" and render_device != "auto":
        raise typer.BadParameter("render-device must be auto for EEVEE")


def _parse_convergence_path_limits(
    encoded_limits: list[str] | None,
) -> list[ConvergencePathLimit] | None:
    """Parse repeatable strict JSON path limits without broadening host policy."""

    if encoded_limits is None:
        return None
    parsed: list[ConvergencePathLimit] = []
    for index, encoded in enumerate(encoded_limits, start=1):
        try:
            payload = json.loads(encoded)
            parsed.append(ConvergencePathLimit.model_validate(payload))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise typer.BadParameter(
                f"--path-limit-json item {index} is not a valid strict ConvergencePathLimit: {exc}"
            ) from exc
    return parsed


def _parse_required_csv(value: str, *, option_name: str) -> list[str]:
    """Split one comma-separated CLI option and reject an empty identifier set."""

    parsed = [item.strip() for item in value.split(",") if item.strip()]
    if not parsed:
        raise typer.BadParameter(f"{option_name} must contain at least one value")
    return parsed


def _read_optional_prompt_file(path: Path | None) -> str | None:
    """Read an optional local prompt file without echoing its contents to CLI output."""

    if path is None:
        return None
    prompt = path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise typer.BadParameter("prompt-file must contain non-empty UTF-8 text")
    return prompt


@app.command()
def doctor() -> None:
    """Check local prerequisites and paths."""
    settings = get_settings()
    table = Table(title="Codex Blender Modeler doctor")
    table.add_column("Check")
    table.add_column("Value")
    table.add_column("Status")
    rows = [
        ("Repository", str(settings.repo_root), settings.repo_root.is_dir()),
        ("Workspace", str(settings.workspace_root), True),
        ("Blender", settings.blender_bin, executable_exists(settings.blender_bin)),
        ("Codex", settings.codex_bin, executable_exists(settings.codex_bin)),
    ]
    for name, value, ok in rows:
        table.add_row(name, value, "OK" if ok else "MISSING")
    console.print(table)
    if not all(ok for _, _, ok in rows):
        raise typer.Exit(code=1)


@app.command("blender-compat")
def blender_compat(
    smoke_exports: Annotated[bool, typer.Option("--smoke-exports/--no-smoke-exports")] = True,
) -> None:
    """Probe Blender APIs and optionally smoke-test GLB/OBJ/FBX exports."""
    settings = get_settings()
    report = settings.repo_root / "reports" / "blender_compatibility.json"
    export_dir = settings.repo_root / "reports" / "compat_exports"
    args = ["--output", str(report)]
    if smoke_exports:
        args.extend(["--smoke-exports", "--export-dir", str(export_dir)])
    result = run_blender("probe_compat.py", args)
    console.print(result.stdout.strip())
    console.print_json(report.read_text(encoding="utf-8"))


@app.command("new")
def new_job(
    job_id: str,
    image: Annotated[Path, typer.Option("--image", exists=True, file_okay=True, dir_okay=False)],
    mode: Annotated[str, typer.Option("--mode")] = "concept",
    reference_content_scope: Annotated[
        str, typer.Option("--reference-content-scope")
    ] = "full_reference",
    target_subject: Annotated[str | None, typer.Option("--target-subject")] = None,
    scale_anchor: Annotated[list[str] | None, typer.Option("--scale-anchor")] = None,
    view: Annotated[
        list[str] | None,
        typer.Option("--view", help="Repeat kind=/absolute/path for front/right/top/blueprint/cad"),
    ] = None,
) -> None:
    """Create a job and copy immutable reference/blueprint images into it."""
    if mode not in {"concept", "measured"}:
        raise typer.BadParameter("mode must be concept or measured")
    additional_views: dict[str, Path] = {}
    for assignment in view or []:
        if "=" not in assignment:
            raise typer.BadParameter("--view must use kind=/absolute/path")
        kind, raw_path = assignment.split("=", 1)
        kind = kind.strip().lower()
        if kind not in {"front", "right", "top", "blueprint", "cad"}:
            raise typer.BadParameter(f"Unsupported view kind: {kind}")
        candidate = Path(raw_path).expanduser()
        if not candidate.is_file():
            raise typer.BadParameter(f"View file does not exist: {candidate}")
        additional_views[kind] = candidate
    metadata = create_job(
        job_id,
        image,
        mode,
        scale_anchor or [],
        additional_views,
        reference_content_scope=reference_content_scope,
        target_subject=target_subject,
    )
    console.print_json(json.dumps(metadata, ensure_ascii=False))


@app.command("add-view")
def add_view(
    job_id: str,
    kind: Annotated[str, typer.Option("--kind")],
    image: Annotated[Path, typer.Option("--image", exists=True, file_okay=True, dir_okay=False)],
    replace: Annotated[bool, typer.Option("--replace")] = False,
    scale_anchor: Annotated[list[str] | None, typer.Option("--scale-anchor")] = None,
) -> None:
    """Safely add or explicitly replace one measured/reference view."""
    result = add_job_view(
        job_id,
        kind.strip().lower(),
        image,
        replace=replace,
        scale_anchors=scale_anchor or [],
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("analyze-reference")
def analyze_reference(
    job_id: str,
    provider: Annotated[str, typer.Option("--provider")] = "auto",
    projection: Annotated[str, typer.Option("--projection")] = "auto",
    focal_length_mm: Annotated[float | None, typer.Option("--focal-length-mm")] = None,
    azimuth_deg: Annotated[float | None, typer.Option("--azimuth-deg")] = None,
    elevation_deg: Annotated[float | None, typer.Option("--elevation-deg")] = None,
) -> None:
    """Create deterministic image diagnostics and a camera-solution scaffold."""
    if provider not in {"auto", "basic", "opencv"}:
        raise typer.BadParameter("provider must be auto, basic, or opencv")
    if projection not in {"auto", "persp", "ortho"}:
        raise typer.BadParameter("projection must be auto, persp, or ortho")
    result = analyze_job_reference(
        job_id,
        provider=provider,  # type: ignore[arg-type]
        projection_hint=projection,  # type: ignore[arg-type]
        focal_length_mm=focal_length_mm,
        azimuth_deg=azimuth_deg,
        elevation_deg=elevation_deg,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("import-example")
def import_example(
    name: Annotated[str, typer.Argument()] = "floating_island",
) -> None:
    """Copy a complete bundled example, including deterministic payloads, into a workspace."""
    settings = get_settings()
    example = settings.repo_root / "examples" / name
    if not example.is_dir():
        raise typer.BadParameter(f"Unknown example: {name}")
    root = job_dir(name)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Example workspace already exists: {root}")
    root = ensure_job_dirs(name)
    reference = example / "reference.png"
    target_reference = root / "input" / "reference.png"
    if reference.exists():
        shutil.copy2(reference, target_reference)
    shutil.copy2(example / "scene_spec.seed.json", root / "analysis" / "scene_spec.json")
    for payload_dir in ("geometry", "materials", "textures"):
        source_dir = example / payload_dir
        if source_dir.is_dir():
            shutil.copytree(source_dir, root / payload_dir, dirs_exist_ok=True)
    modeling_plan_seed = example / "modeling_plan.seed.json"
    if modeling_plan_seed.exists():
        target_plan = root / "analysis" / "modeling_plan.json"
        shutil.copy2(modeling_plan_seed, target_plan)
        load_modeling_plan(target_plan)
    constraint_seed = example / "constraints.seed.json"
    if constraint_seed.exists():
        shutil.copy2(constraint_seed, root / "constraints" / "constraints.json")
    material_plan_seed = example / "material_plan.seed.json"
    if material_plan_seed.exists():
        target_material_plan = root / "analysis" / "material_plan.json"
        shutil.copy2(material_plan_seed, target_material_plan)
        load_material_plan(target_material_plan)
    metadata = json.loads((example / "job.json").read_text(encoding="utf-8"))
    if target_reference.exists():
        metadata["reference_path"] = metadata_path(target_reference)
        metadata["reference_sha256"] = sha256_file(target_reference)
        metadata["sources"] = [
            {
                "kind": "reference",
                "path": metadata_path(target_reference),
                "sha256": sha256_file(target_reference),
            }
        ]
    metadata["project_version_created"] = PROJECT_VERSION
    (root / "job.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    load_scene_spec(root / "analysis" / "scene_spec.json")
    console.print(f"Imported example to {root}")


@app.command()
def analyze(job_id: str) -> None:
    """Ask Codex to turn the job reference into a schema-valid SceneSpec."""
    settings = get_settings()
    metadata = load_job(job_id)
    images = find_input_images(job_id)
    template = (settings.repo_root / "prompts" / "analyze_reference.md").read_text(encoding="utf-8")
    prompt = (
        template
        + "\n\n# Job context\n"
        + json.dumps(metadata, indent=2, ensure_ascii=False)
        + f"\nTarget job directory: {job_dir(job_id)}\n"
    )
    output = _scene_spec_path(job_id)
    expected_current_sha256 = sha256_file(output) if output.is_file() else None
    candidate = _scene_spec_candidate_path(job_id, "analyze")
    run_codex_json(
        prompt=prompt,
        images=images,
        schema=settings.repo_root / "schemas" / "scene_spec.schema.json",
        output=candidate,
    )
    spec = load_scene_spec(candidate)
    replacement = _promote_cli_scene_spec(
        job_id,
        candidate,
        expected_current_sha256=expected_current_sha256,
        operation="analyze",
    )
    console.print(f"SceneSpec created: {output} ({len(spec.objects)} objects)")
    if replacement["archived_scene_spec"]:
        console.print(f"Previous revision archived: {replacement['archived_scene_spec']}")


@app.command()
def revise(job_id: str, request: str) -> None:
    """Ask Codex to minimally revise the canonical SceneSpec."""
    settings = get_settings()
    current = _scene_spec_path(job_id)
    spec = load_scene_spec(current)
    preview = job_dir(job_id) / "renders" / "preview.png"
    images = find_input_images(job_id)
    if preview.is_file():
        images.append(preview)
    template = (settings.repo_root / "prompts" / "revise_scene.md").read_text(encoding="utf-8")
    prompt = (
        template
        + f"\n\nUser request:\n{request}\n"
        + f"\nCurrent SceneSpec path: {current}\n"
        + f"Current job ID: {spec.job_id}\n"
    )
    expected_current_sha256 = sha256_file(current)
    temp = _scene_spec_candidate_path(job_id, "revise")
    run_codex_json(
        prompt=prompt,
        images=images,
        schema=settings.repo_root / "schemas" / "scene_spec.schema.json",
        output=temp,
    )
    next_spec = load_scene_spec(temp)
    if next_spec.job_id != job_id:
        raise ValueError(f"Revised SceneSpec job_id changed to {next_spec.job_id}")
    replacement = _promote_cli_scene_spec(
        job_id,
        temp,
        expected_current_sha256=expected_current_sha256,
        operation="revise",
    )
    console.print(f"Revised SceneSpec written: {current}")
    if replacement["archived_scene_spec"]:
        console.print(f"Previous revision archived: {replacement['archived_scene_spec']}")


@app.command("migrate-spec")
def migrate_spec(job_id: str) -> None:
    """Migrate a primitive-only SceneSpec v0.1 file to v0.2 geometry recipes."""
    current = _scene_spec_path(job_id)
    if not current.is_file():
        raise typer.BadParameter(f"SceneSpec does not exist: {current}")
    raw = json.loads(current.read_text(encoding="utf-8"))
    if raw.get("schema_version") == "0.2.0":
        console.print(f"Already on SceneSpec v0.2.0: {current}")
        return
    expected_current_sha256 = sha256_file(current)
    candidate = _scene_spec_candidate_path(job_id, "migrate")
    migrate_v1_file(current, candidate)
    load_scene_spec(candidate)
    replacement = _promote_cli_scene_spec(
        job_id,
        candidate,
        expected_current_sha256=expected_current_sha256,
        operation="migrate",
    )
    console.print(f"Migrated to SceneSpec v0.2.0: {current}")
    if replacement["archived_scene_spec"]:
        console.print(f"Previous revision archived: {replacement['archived_scene_spec']}")


@app.command("plan-revision")
def plan_revision(job_id: str, request: str) -> None:
    """Ask Codex for a small, ID-addressed RevisionPlan without mutating SceneSpec."""
    settings = get_settings()
    current = _scene_spec_path(job_id)
    spec = load_scene_spec(current)
    preview = job_dir(job_id) / "renders" / "preview.png"
    images = find_input_images(job_id)
    if preview.is_file():
        images.append(preview)
    template = (settings.repo_root / "prompts" / "plan_revision.md").read_text(encoding="utf-8")
    base_hash = sha256_file(current)
    prompt = (
        template
        + f"\n\nUser request:\n{request}\n"
        + f"\nCurrent SceneSpec path: {current}\n"
        + f"Exact job_id: {spec.job_id}\n"
        + f"Exact base_spec_sha256: {base_hash}\n"
    )
    output = job_dir(job_id) / "analysis" / "revision_plan.json"
    run_codex_json(
        prompt=prompt,
        images=images,
        schema=settings.repo_root / "schemas" / "revision_plan.schema.json",
        output=output,
    )
    console.print(f"RevisionPlan created: {output}")
    console.print_json(output.read_text(encoding="utf-8"))


@app.command("apply-revision")
def apply_revision(job_id: str) -> None:
    """Apply the current guarded RevisionPlan and emit an exact before/after report."""
    root = job_dir(job_id)
    current = _scene_spec_path(job_id)
    plan = root / "analysis" / "revision_plan.json"
    if not plan.is_file():
        raise typer.BadParameter(f"Revision plan does not exist: {plan}")
    temp = _scene_spec_candidate_path(job_id, "apply-revision")
    owner = _cli_scene_spec_lock_owner("apply-revision")
    with canonical_scene_spec_write_lock(job_id, owner):
        _validated, report = apply_revision_plan(
            scene_spec_path=current,
            plan_path=plan,
            output_path=temp,
        )
        replacement = replace_scene_spec_if_current(
            job_id,
            temp,
            expected_current_sha256=report["base_spec_sha256"],
            expected_candidate_sha256=report["result_spec_sha256"],
            lock_owner_id=owner,
        )
    temp.unlink(missing_ok=True)
    report_path = root / "reports" / "revision_diff.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    console.print(f"Guarded revision applied: {current}")
    if replacement["archived_scene_spec"]:
        console.print(f"Previous revision archived: {replacement['archived_scene_spec']}")
    console.print(f"Exact diff report: {report_path}")


@app.command("init-constraints")
def init_constraints(
    job_id: str,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Create an empty measured-mode constraint contract for a job."""
    path = initialize_constraints(job_id, overwrite=overwrite)
    console.print(f"Constraint template: {path}")


@app.command("evaluate-constraints")
def evaluate_constraints(job_id: str) -> None:
    """Evaluate constraints against the latest Blender scene inventory."""
    solution = evaluate_job_constraints(job_id)
    console.print_json(solution.model_dump_json())
    if not solution.ok:
        raise typer.Exit(code=2)


@app.command("material-scaffold")
def material_scaffold(
    job_id: str,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Create a V0.5 material plan and portable shader recipes from approved materials."""

    features = load_feature_config().features
    if not features.material_core or not features.shader_core:
        raise typer.BadParameter("material_core and shader_core must be enabled in cbm.toml")
    plan = create_material_scaffold(job_id, overwrite=overwrite)
    console.print_json(plan.model_dump_json())


@app.command("validate-material-contracts")
def validate_materials(job_id: str) -> None:
    """Validate V0.5 material plans, shader recipes, and texture manifests on the host."""

    report = validate_job_material_contracts(job_id)
    console.print_json(json.dumps(report, ensure_ascii=False))
    if not report["ok"]:
        raise typer.Exit(code=2)


@app.command("validate-material-fidelity")
def validate_material_fidelity(job_id: str) -> None:
    """Measure deterministic V0.5 texture fidelity and spatial-detail leakage risks."""

    report = validate_job_material_fidelity(job_id)
    console.print_json(json.dumps(report, ensure_ascii=False))
    if not report["ok"]:
        raise typer.Exit(code=2)


@app.command("validate-surface-details")
def validate_surface_details(job_id: str) -> None:
    """Validate non-mesh detail routing and current V0.5 texture coverage."""

    report = validate_job_surface_details(
        job_id,
        require_materials=None,
        write_report=True,
    )
    console.print_json(report.model_dump_json())
    if not report.ok:
        raise typer.Exit(code=2)


@app.command("surface-detail-status")
def surface_detail_status(job_id: str) -> None:
    """Inspect current surface-detail geometry and texture bindings without writing files."""

    report = validate_job_surface_details(
        job_id,
        require_materials=None,
        write_report=False,
    )
    console.print_json(report.model_dump_json())


@app.command("material-presets")
def material_presets() -> None:
    """List deterministic offline PBR material-family presets."""

    console.print_json(json.dumps(get_material_family_presets(), ensure_ascii=False))


@app.command("generate-procedural-textures")
def generate_procedural_textures(
    job_id: str,
    material_id: str,
    preset: Annotated[str, typer.Option("--preset")] = "standard_pbr",
    channel: Annotated[list[str] | None, typer.Option("--channel")] = None,
    resolution: Annotated[int, typer.Option("--resolution", min=16, max=8192)] = 512,
    seed: Annotated[int, typer.Option("--seed", min=0)] = 0,
    intended_scale_m: Annotated[float, typer.Option("--scale-m", min=0.000001)] = 1.0,
    prompt: Annotated[str, typer.Option("--prompt")] = "",
    uv_set: Annotated[str, typer.Option("--uv-set")] = "Object",
    surface_detail_id: Annotated[list[str] | None, typer.Option("--surface-detail-id")] = None,
    surface_detail_binding_json: Annotated[
        list[str] | None, typer.Option("--surface-detail-binding-json")
    ] = None,
    detail_pattern: Annotated[str, typer.Option("--detail-pattern")] = "none",
    output_relative_dir: Annotated[str | None, typer.Option("--output-relative-dir")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    attach: Annotated[bool, typer.Option("--attach/--no-attach")] = True,
) -> None:
    """Generate reproducible local PBR maps and optionally attach their manifest."""

    config = load_feature_config()
    if config.features.texture_provider != "procedural":
        raise typer.BadParameter("features.texture_provider must be procedural")
    bindings: list[dict] = []
    for value in surface_detail_binding_json or []:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                "surface-detail-binding-json must contain one JSON object"
            ) from exc
        if not isinstance(payload, dict):
            raise typer.BadParameter("surface-detail-binding-json must contain one JSON object")
        bindings.append(payload)
    result = generate_job_procedural_textures(
        job_id,
        material_id,
        preset=preset,
        channels=channel
        or (
            "base_color",
            "roughness",
            "metallic",
            "normal",
            "height",
            "emission",
        ),
        resolution=(resolution, resolution),
        seed=seed,
        intended_scale_m=intended_scale_m,
        prompt=prompt,
        uv_set=uv_set,
        surface_detail_ids=surface_detail_id or (),
        surface_detail_bindings=bindings,
        detail_pattern=detail_pattern,
        output_relative_dir=output_relative_dir,
        overwrite=overwrite,
        attach=attach,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("attach-texture-manifest")
def attach_texture_manifest(
    job_id: str,
    material_id: str,
    manifest_path: Annotated[str, typer.Option("--manifest")],
) -> None:
    """Attach one validated job-local texture manifest to a stable material ID."""

    plan = attach_texture_manifest_to_plan(job_id, material_id, manifest_path)
    console.print_json(plan.model_dump_json())


@app.command("bake-materials")
def bake_materials(
    job_id: str,
    profile: Annotated[str, typer.Option("--profile")] = "gltf_pbr",
    resolution: Annotated[int, typer.Option("--resolution", min=1, max=8192)] = 1024,
    margin_px: Annotated[int, typer.Option("--margin-px", min=0)] = 16,
    render_device: Annotated[str, typer.Option("--render-device")] = "auto",
    material_id: Annotated[list[str] | None, typer.Option("--material-id")] = None,
    strict: Annotated[bool, typer.Option("--strict/--allow-partial")] = True,
) -> None:
    """Bake bounded portable PBR channels from the latest approved Blender scene."""

    if render_device not in {"auto", "cpu", "gpu"}:
        raise typer.BadParameter("render-device must be auto, cpu, or gpu")
    report = bake_job_materials(
        job_id,
        profile=profile,  # type: ignore[arg-type]
        resolution=resolution,
        margin_px=margin_px,
        render_device=render_device,  # type: ignore[arg-type]
        material_ids=material_id,
        strict=strict,
    )
    console.print_json(json.dumps(report, ensure_ascii=False))


@app.command("inspect-materials")
def inspect_materials(job_id: str) -> None:
    """Inspect applied Blender node graphs, images, color spaces, and UV statistics."""

    report = inspect_job_materials(job_id)
    console.print_json(json.dumps(report, ensure_ascii=False))
    if not report.get("ok", False):
        raise typer.Exit(code=2)


@app.command("render-material-swatches")
def render_material_swatches(
    job_id: str,
    render_engine: Annotated[str, typer.Option("--render-engine")] = "eevee",
    render_device: Annotated[str, typer.Option("--render-device")] = "auto",
    size: Annotated[int, typer.Option("--size", min=128, max=2048)] = 512,
    material_id: Annotated[list[str] | None, typer.Option("--material-id")] = None,
) -> None:
    """Render fixed sphere and plane previews for selected stable material IDs."""

    _validate_render_options(render_engine, render_device)
    manifest = render_job_material_swatches(
        job_id,
        render_engine=render_engine,
        render_device=render_device,
        size=size,
        material_ids=material_id,
    )
    console.print_json(json.dumps(manifest, ensure_ascii=False))


@app.command("report-pdf")
def report_pdf(
    job_id: str,
    scope: Annotated[str, typer.Option("--scope")] = "full",
    qa_run_id: Annotated[str, typer.Option("--qa-run-id")] = "latest",
    interior_qa_run_id: Annotated[str, typer.Option("--interior-qa-run-id")] = "latest",
    assembly_sanity_run_id: Annotated[str | None, typer.Option("--assembly-sanity-run-id")] = None,
    optimization_run_id: Annotated[str, typer.Option("--optimization-run-id")] = "latest",
    package_id: Annotated[str, typer.Option("--package-id")] = "latest",
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Generate a Korean human-readable PDF while preserving canonical JSON reports."""

    if scope not in {"build", "material", "qa", "export", "full"}:
        raise typer.BadParameter("scope must be build, material, qa, export, or full")
    result = generate_job_pdf_report(
        job_id,
        scope=scope,  # type: ignore[arg-type]
        qa_run_id=qa_run_id,
        interior_qa_run_id=interior_qa_run_id,
        assembly_sanity_run_id=assembly_sanity_run_id,
        optimization_run_id=optimization_run_id,
        package_id=package_id,
        output_path=output,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("visual-qa")
def visual_qa(
    job_id: str,
    render_engine: Annotated[str, typer.Option("--render-engine")] = "eevee",
    render_device: Annotated[str, typer.Option("--render-device")] = "auto",
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    generated_target: Annotated[bool, typer.Option("--generated-target")] = False,
    target_image: Annotated[Path | None, typer.Option("--target-image")] = None,
    target_model: Annotated[str, typer.Option("--target-model")] = "external-image-model",
    target_model_version: Annotated[str | None, typer.Option("--target-model-version")] = None,
    target_seed: Annotated[int | None, typer.Option("--target-seed", min=0)] = None,
    target_allowed_root: Annotated[Path | None, typer.Option("--target-allowed-root")] = None,
    target_prompt_file: Annotated[Path | None, typer.Option("--target-prompt-file")] = None,
) -> None:
    """Render V0.6 passes and optionally import one advisory image-model target."""

    _validate_render_options(render_engine, render_device)
    features = load_feature_config()
    include_target = generated_target or target_image is not None
    if not features.features.visual_qa:
        raise typer.BadParameter("visual_qa is disabled in cbm.toml")
    if include_target and not features.features.image_model_qa:
        raise typer.BadParameter("image_model_qa is disabled in cbm.toml")
    if generated_target and target_image is None:
        raise typer.BadParameter(
            "The local CLI has no bundled image generator; pass --target-image with the "
            "explicitly generated advisory image."
        )
    if target_image is not None and target_prompt_file is None:
        raise typer.BadParameter(
            "--target-image requires --target-prompt-file so the actual generation prompt "
            "can be hashed for provenance."
        )
    target_prompt = None
    if target_prompt_file is not None:
        try:
            target_prompt = (
                target_prompt_file.expanduser()
                .resolve(strict=True)
                .read_text(encoding="utf-8")
                .strip()
            )
        except OSError as exc:
            raise typer.BadParameter(f"Cannot read target prompt file: {exc}") from exc
        if not target_prompt:
            raise typer.BadParameter("target prompt file must not be empty")
    provider = (
        ExistingFileQATargetProvider(
            target_image,
            model=target_model,
            model_version=target_model_version,
            seed=target_seed,
            allowed_root=target_allowed_root,
        )
        if target_image is not None
        else None
    )
    result = run_job_visual_qa(
        job_id,
        render_engine=render_engine,
        render_device=render_device,
        run_id=run_id,
        include_generated_target=include_target,
        provider=provider,
        target_prompt=target_prompt,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("qa-compile-revision")
def qa_compile_revision(
    job_id: str,
    run_id: str,
    candidate_id: Annotated[list[str], typer.Option("--candidate-id")],
    request: Annotated[str, typer.Option("--request")],
) -> None:
    """Compile selected safe QA candidates without creating or implying approval."""

    config = load_feature_config()
    if config.qa.revision_mode == "off":
        raise typer.BadParameter("qa.revision_mode is off in cbm.toml")
    result = compile_job_qa_revision(
        job_id,
        run_id,
        selected_candidate_ids=candidate_id,
        request=request,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("qa-approve-revision")
def qa_approve_revision(
    job_id: str,
    run_id: str,
    candidate_id: Annotated[list[str], typer.Option("--candidate-id")],
) -> None:
    """Record the user's explicit, hash-bound, single-use approval for selected candidates."""

    config = load_feature_config()
    if config.qa.revision_mode not in {"approve", "auto"}:
        raise typer.BadParameter("qa.revision_mode must be approve or auto in cbm.toml")
    result = approve_job_qa_revision(
        job_id,
        run_id,
        approved_candidate_ids=candidate_id,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("qa-apply-approved")
def qa_apply_approved(
    job_id: str,
    run_id: str,
    render_engine: Annotated[str, typer.Option("--render-engine")] = "eevee",
    render_device: Annotated[str, typer.Option("--render-device")] = "auto",
    minimum_improvement: Annotated[
        float, typer.Option("--minimum-improvement", min=0.0, max=1.0)
    ] = 0.001,
) -> None:
    """Apply one approved QA revision and accept or automatically restore after verification."""

    _validate_render_options(render_engine, render_device)
    config = load_feature_config()
    if config.qa.revision_mode not in {"approve", "auto"}:
        raise typer.BadParameter("qa.revision_mode must be approve or auto in cbm.toml")
    if config.qa.max_revision_iterations < 1:
        raise typer.BadParameter("qa.max_revision_iterations must allow one iteration")
    result = apply_job_approved_revision(
        job_id,
        run_id,
        run_pipeline=True,
        render_engine=render_engine,
        render_device=render_device,
        minimum_improvement=minimum_improvement,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("qa-convergence-plan")
def qa_convergence_plan(
    job_id: str,
    initial_qa_run_id: str,
    target_direct_score: Annotated[float, typer.Option("--target-direct-score", min=0.0, max=1.0)],
    target_silhouette_iou: Annotated[
        float, typer.Option("--target-silhouette-iou", min=0.0, max=1.0)
    ],
    allowed_target_id: Annotated[list[str] | None, typer.Option("--allowed-target-id")] = None,
    session_id: Annotated[str | None, typer.Option("--session-id")] = None,
    minimum_iteration_gain: Annotated[
        float, typer.Option("--minimum-iteration-gain", min=0.000001, max=1.0)
    ] = 0.001,
    minimum_candidate_confidence: Annotated[
        float, typer.Option("--minimum-candidate-confidence", min=0.0, max=1.0)
    ] = 0.8,
    max_iterations: Annotated[int, typer.Option("--max-iterations", min=1, max=5)] = 3,
    max_candidate_groups: Annotated[int, typer.Option("--max-candidate-groups", min=1, max=20)] = 3,
    max_candidates: Annotated[int, typer.Option("--max-candidates", min=1, max=100)] = 12,
    max_changed_ids: Annotated[int, typer.Option("--max-changed-ids", min=1, max=50)] = 6,
    path_limit_json: Annotated[
        list[str] | None,
        typer.Option(
            "--path-limit-json",
            help=(
                "Repeatable strict JSON ConvergencePathLimit object that may only "
                "narrow the host-derived path, operation, and delta envelope."
            ),
        ),
    ] = None,
) -> None:
    """Plan one standard-only exact-hash envelope without changing geometry."""

    if not load_feature_config().features.visual_qa:
        raise typer.BadParameter("visual_qa is disabled in cbm.toml")
    result = plan_job_visual_convergence(
        job_id,
        initial_qa_run_id,
        target_direct_score=target_direct_score,
        target_silhouette_iou=target_silhouette_iou,
        allowed_target_ids=allowed_target_id,
        session_id=session_id,
        minimum_iteration_gain=minimum_iteration_gain,
        minimum_candidate_confidence=minimum_candidate_confidence,
        max_iterations=max_iterations,
        max_candidate_groups_per_iteration=max_candidate_groups,
        max_candidates_per_iteration=max_candidates,
        max_changed_ids_per_iteration=max_changed_ids,
        path_limits=_parse_convergence_path_limits(path_limit_json),
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("qa-convergence-approve")
def qa_convergence_approve(
    job_id: str,
    session_id: str,
    plan_sha256: Annotated[str, typer.Option("--plan-sha256")],
    approval_note: Annotated[str, typer.Option("--approval-note")],
) -> None:
    """Record explicit user approval for one exact bounded-convergence plan hash."""

    result = approve_job_visual_convergence(
        job_id,
        session_id,
        plan_sha256=plan_sha256,
        approval_note=approval_note,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("qa-convergence-run")
def qa_convergence_run(
    job_id: str,
    session_id: str,
    render_engine: Annotated[str, typer.Option("--render-engine")] = "eevee",
    render_device: Annotated[str, typer.Option("--render-device")] = "auto",
) -> None:
    """Run or recover at most one full approved convergence iteration."""

    _validate_render_options(render_engine, render_device)
    if not load_feature_config().features.visual_qa:
        raise typer.BadParameter("visual_qa is disabled in cbm.toml")
    result = run_job_visual_convergence(
        job_id,
        session_id,
        render_engine=render_engine,
        render_device=render_device,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("qa-convergence-status")
def qa_convergence_status(
    job_id: str,
    session_id: str,
) -> None:
    """Read one bounded visual-convergence session without changing its evidence."""

    result = get_job_visual_convergence_status(job_id, session_id)
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("qa-convergence-cancel")
def qa_convergence_cancel(
    job_id: str,
    session_id: str,
    reason: Annotated[str, typer.Option("--reason")],
) -> None:
    """Cancel one approved active convergence session with an explicit reason."""

    result = cancel_job_visual_convergence(
        job_id,
        session_id,
        reason=reason,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("asset-profile-init")
def asset_profile_init(
    job_id: str,
    profile: Annotated[str, typer.Option("--profile")] = "portable_gltf",
    asset_kind: Annotated[str, typer.Option("--asset-kind")] = "static_prop",
    consolidation: Annotated[str, typer.Option("--consolidation")] = "by_semantic_group",
    spatial_cell_size_m: Annotated[float, typer.Option("--spatial-cell-size-m")] = 25.0,
    maximum_objects_per_batch: Annotated[int, typer.Option("--maximum-objects-per-batch")] = 64,
    lod_mode: Annotated[str, typer.Option("--lod-mode")] = "profile_default",
    generate_uv1: Annotated[bool | None, typer.Option("--generate-uv1/--no-generate-uv1")] = None,
    pivot_policy: Annotated[str, typer.Option("--pivot-policy")] = "keep",
    collision_strategy: Annotated[str, typer.Option("--collision-strategy")] = "profile_default",
    max_collider_hulls_per_object: Annotated[
        int, typer.Option("--max-collider-hulls-per-object")
    ] = 8,
    max_collider_triangles_per_object: Annotated[
        int, typer.Option("--max-collider-triangles-per-object")
    ] = 256,
    budget_enforcement: Annotated[str, typer.Option("--budget-enforcement")] = "warning",
    max_render_objects: Annotated[int | None, typer.Option("--max-render-objects")] = None,
    max_material_slots: Annotated[int | None, typer.Option("--max-material-slots")] = None,
    max_draw_calls: Annotated[int | None, typer.Option("--max-draw-calls")] = None,
    max_lod0_triangles: Annotated[int | None, typer.Option("--max-lod0-triangles")] = None,
    max_collider_triangles: Annotated[int | None, typer.Option("--max-collider-triangles")] = None,
    max_overlap_candidates: Annotated[int | None, typer.Option("--max-overlap-candidates")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Initialize one engine-neutral profile with explicit optimization defaults."""

    if profile not in {"portable_gltf", "fbx_interchange", "obj_legacy"}:
        raise typer.BadParameter("profile must be portable_gltf, fbx_interchange, or obj_legacy")
    if asset_kind not in {"static_prop", "static_environment", "static_architecture"}:
        raise typer.BadParameter(
            "asset-kind must be static_prop, static_environment, or static_architecture"
        )
    if consolidation not in {"none", "by_semantic_group", "by_spatial_cell"}:
        raise typer.BadParameter(
            "consolidation must be none, by_semantic_group, or by_spatial_cell"
        )
    if budget_enforcement not in {"warning", "fail"}:
        raise typer.BadParameter("budget-enforcement must be warning or fail")
    if lod_mode not in {"profile_default", "enabled", "disabled"}:
        raise typer.BadParameter("lod-mode must be profile_default, enabled, or disabled")
    if pivot_policy not in {"keep", "bounds_center", "base_center"}:
        raise typer.BadParameter("pivot-policy must be keep, bounds_center, or base_center")
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
        raise typer.BadParameter(
            "collision-strategy must be profile_default, none, box, sphere, capsule, "
            "convex_hull, compound, or mesh_proxy"
        )
    result = initialize_asset_profile(
        job_id,
        profile_id=profile,
        asset_kind=asset_kind,  # type: ignore[arg-type]
        consolidation_mode=consolidation,  # type: ignore[arg-type]
        spatial_cell_size_m=spatial_cell_size_m,
        maximum_objects_per_batch=maximum_objects_per_batch,
        lod_mode=lod_mode,  # type: ignore[arg-type]
        generate_uv1=generate_uv1,
        pivot_policy=pivot_policy,  # type: ignore[arg-type]
        collision_strategy=collision_strategy,  # type: ignore[arg-type]
        max_collider_hulls_per_object=max_collider_hulls_per_object,
        max_collider_triangles_per_object=max_collider_triangles_per_object,
        budget_enforcement=budget_enforcement,
        max_lod0_render_objects=max_render_objects,
        max_lod0_material_slots=max_material_slots,
        max_lod0_estimated_draw_calls=max_draw_calls,
        max_lod0_triangles=max_lod0_triangles,
        max_collider_triangles=max_collider_triangles,
        max_overlap_candidates=max_overlap_candidates,
        overwrite=overwrite,
    )
    console.print_json(result.model_dump_json())


@app.command("interior-scope-init")
def interior_scope_init(
    job_id: str,
    policy: Annotated[str, typer.Option("--policy")] = "disabled",
    request: Annotated[str, typer.Option("--request")] = "",
    allow_prefix: Annotated[list[str] | None, typer.Option("--allow-prefix")] = None,
    exclude_prefix: Annotated[list[str] | None, typer.Option("--exclude-prefix")] = None,
    level: Annotated[list[str] | None, typer.Option("--level")] = None,
    space: Annotated[list[str] | None, typer.Option("--space")] = None,
    furnishing: Annotated[str, typer.Option("--furnishing")] = "none",
    evidence_status: Annotated[str | None, typer.Option("--evidence-status")] = None,
    assumption: Annotated[list[str] | None, typer.Option("--assumption")] = None,
    note: Annotated[list[str] | None, typer.Option("--note")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Create an explicit interior boundary without authorizing or changing geometry."""

    evidence_defaults = {
        "disabled": "not_applicable",
        "visible_only": "observed",
        "proxy": "inferred",
        "measured": "measured",
        "authored": "authored",
    }
    if policy not in evidence_defaults:
        raise typer.BadParameter(
            "policy must be disabled, visible_only, proxy, measured, or authored"
        )
    scope = initialize_interior_scope(
        job_id,
        policy=policy,
        request=request,
        allowed_semantic_prefixes=allow_prefix or [],
        excluded_semantic_prefixes=exclude_prefix or [],
        levels=level or [],
        spaces=space or [],
        furnishing=furnishing,
        evidence_status=evidence_status or evidence_defaults[policy],
        assumptions=assumption or [],
        notes=note or [],
        overwrite=overwrite,
    )
    result = get_interior_scope_status(job_id)
    result["scope"] = scope.model_dump(mode="json")
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("interior-scope-approve")
def interior_scope_approve(
    job_id: str,
    scope_sha256: Annotated[str, typer.Option("--scope-sha256")],
    approval_note: Annotated[str, typer.Option("--approval-note")],
) -> None:
    """Persist one exact approval only after a human-facing interactive confirmation."""

    expected_confirmation = f"APPROVE {scope_sha256}"
    confirmation = typer.prompt(
        f"Manual approval required. Type the exact phrase '{expected_confirmation}'"
    )
    if confirmation.strip() != expected_confirmation:
        raise typer.Abort()
    approval = approve_interior_scope(
        job_id,
        scope_sha256=scope_sha256,
        approval_note=approval_note,
        manual_confirmation=True,
    )
    console.print_json(approval.model_dump_json())


@app.command("interior-scope-status")
def interior_scope_status(job_id: str) -> None:
    """Show the effective interior policy without creating any contract files."""

    console.print_json(json.dumps(get_interior_scope_status(job_id), ensure_ascii=False))


@app.command("interior-scope-validate")
def interior_scope_validate(job_id: str) -> None:
    """Validate canonical SceneSpec interiors against the current approved scope."""

    report = validate_job_interior_scope(job_id, write_report=True)
    console.print_json(report.model_dump_json())
    if not report.ok:
        raise typer.Exit(code=2)


@app.command("qa-assembly-sanity-plan")
def qa_assembly_sanity_plan(
    job_id: str,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    resolution: Annotated[int, typer.Option("--resolution", min=128, max=1024)] = 384,
) -> None:
    """Plan a noncanonical five-view assembly diagnostic without bypassing approvals."""

    if not load_feature_config().features.visual_qa:
        raise typer.BadParameter("visual_qa is disabled in cbm.toml")
    result = plan_job_assembly_multiview_sanity(
        job_id,
        run_id=run_id,
        resolution=resolution,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("qa-semantic-masks-register")
def qa_semantic_masks_register(
    job_id: str,
    registration_id: Annotated[str, typer.Option("--registration-id")],
    manifest_sha256: Annotated[str, typer.Option("--manifest-sha256")],
) -> None:
    """Promote one exact job-owned semantic-mask candidate after strict validation."""

    if not load_feature_config().features.visual_qa:
        raise typer.BadParameter("visual_qa is disabled in cbm.toml")
    receipt = register_job_semantic_reference_masks(
        job_id,
        registration_id,
        manifest_sha256=manifest_sha256,
    )
    console.print_json(receipt.model_dump_json())


@app.command("qa-semantic-masks-status")
def qa_semantic_masks_status(job_id: str) -> None:
    """Inspect current semantic-mask evidence without repairing or rewriting it."""

    status = get_job_semantic_reference_mask_status(job_id)
    console.print_json(status.model_dump_json())


@app.command("qa-diagnose")
def qa_diagnose(
    job_id: str,
    qa_run_id: Annotated[str, typer.Option("--qa-run-id")],
    diagnostic_id: Annotated[str, typer.Option("--diagnostic-id")] = "camera-geometry-v1",
    max_camera_probes: Annotated[
        int,
        typer.Option(
            "--max-camera-probes",
            min=1,
            max=12,
            help="Maximum non-baseline deltas; a neutral baseline is rendered separately.",
        ),
    ] = 12,
    include_multiview_sanity: Annotated[
        bool,
        typer.Option("--assembly-multiview/--no-assembly-multiview"),
    ] = True,
    render_engine: Annotated[str, typer.Option("--render-engine")] = "eevee",
    render_device: Annotated[str, typer.Option("--render-device")] = "auto",
) -> None:
    """Run advisory camera, part-shape, and optional assembly diagnostics."""

    _validate_render_options(render_engine, render_device)
    if not load_feature_config().features.visual_qa:
        raise typer.BadParameter("visual_qa is disabled in cbm.toml")
    result = run_job_visual_diagnostics(
        job_id,
        qa_run_id,
        diagnostic_id=diagnostic_id,
        max_camera_probes=max_camera_probes,
        include_multiview_sanity=include_multiview_sanity,
        render_engine=render_engine,
        render_device=render_device,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("qa-assembly-sanity-run")
def qa_assembly_sanity_run(
    job_id: str,
    run_id: Annotated[str, typer.Option("--run-id")],
    plan_sha256: Annotated[str, typer.Option("--plan-sha256")],
    render_engine: Annotated[str, typer.Option("--render-engine")] = "eevee",
    render_device: Annotated[str, typer.Option("--render-device")] = "auto",
) -> None:
    """Run structural views without replacing V0.6, interior, or revision approvals."""

    _validate_render_options(render_engine, render_device)
    if not load_feature_config().features.visual_qa:
        raise typer.BadParameter("visual_qa is disabled in cbm.toml")
    result = run_job_assembly_multiview_sanity(
        job_id,
        run_id,
        plan_sha256=plan_sha256,
        render_engine=render_engine,
        render_device=render_device,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))
    if result.get("status") == "failed":
        raise typer.Exit(code=2)


@app.command("interior-qa-plan")
def interior_qa_plan(
    job_id: str,
    profile: Annotated[str, typer.Option("--profile")] = "standard",
    resolution: Annotated[int, typer.Option("--resolution", min=128, max=2048)] = 512,
    max_views: Annotated[int, typer.Option("--max-views", min=1, max=64)] = 24,
    eye_height_m: Annotated[float, typer.Option("--eye-height-m", min=0.01, max=3.0)] = 1.6,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Plan isolated multi-view interior QA and stop for exact hash approval."""

    if not load_feature_config().features.visual_qa:
        raise typer.BadParameter("visual_qa is disabled in cbm.toml")
    result = plan_job_interior_qa(
        job_id,
        profile=profile,
        resolution=resolution,
        max_views=max_views,
        eye_height_m=eye_height_m,
        run_id=run_id,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("interior-qa-plan-approve")
def interior_qa_plan_approve(
    job_id: str,
    run_id: Annotated[str, typer.Option("--run-id")],
    plan_sha256: Annotated[str, typer.Option("--plan-sha256")],
    approval_note: Annotated[str, typer.Option("--approval-note")],
    view_id: Annotated[list[str] | None, typer.Option("--view-id")] = None,
) -> None:
    """Record explicit approval for one exact interior QA camera plan."""

    approval = approve_job_interior_qa_plan(
        job_id,
        run_id,
        plan_sha256=plan_sha256,
        approval_note=approval_note,
        approved_view_ids=view_id,
    )
    console.print_json(approval.model_dump_json())


@app.command("interior-qa-run")
def interior_qa_run(
    job_id: str,
    run_id: Annotated[str, typer.Option("--run-id")],
    approved_plan_sha256: Annotated[str, typer.Option("--approved-plan-sha256")],
    render_engine: Annotated[str, typer.Option("--render-engine")] = "eevee",
    render_device: Annotated[str, typer.Option("--render-device")] = "auto",
) -> None:
    """Consume one approved plan and render seven passes from every selected interior view."""

    _validate_render_options(render_engine, render_device)
    if not load_feature_config().features.visual_qa:
        raise typer.BadParameter("visual_qa is disabled in cbm.toml")
    result = run_job_interior_qa(
        job_id,
        run_id,
        approved_plan_sha256=approved_plan_sha256,
        render_engine=render_engine,
        render_device=render_device,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))
    if not result["ok"]:
        raise typer.Exit(code=2)


@app.command("interior-qa-status")
def interior_qa_status(
    job_id: str,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Show current interior QA plan, approval, execution, and stale-source state."""

    result = get_job_interior_qa_status(job_id, run_id=run_id)
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("external-intake-plan")
def external_intake_plan(
    job_id: str,
    source_path: Path,
    plan_id: Annotated[str | None, typer.Option("--plan-id")] = None,
) -> None:
    """Inspect one external static source, copy exact evidence, and await approval."""

    result = plan_external_static_asset_intake(
        job_id,
        source_path,
        plan_id=plan_id,
    )
    console.print_json(result.model_dump_json())


@app.command("external-intake-approve")
def external_intake_approve(
    job_id: str,
    plan_id: Annotated[str, typer.Option("--plan-id")],
    plan_sha256: Annotated[str, typer.Option("--plan-sha256")],
    approval_note: Annotated[str, typer.Option("--approval-note")],
) -> None:
    """Record one single-use user approval for an exact external-intake plan hash."""

    result = approve_external_static_asset_intake(
        job_id,
        plan_id,
        plan_sha256,
        approval_note=approval_note,
    )
    console.print_json(result.model_dump_json())


@app.command("external-intake-normalize")
def external_intake_normalize(
    job_id: str,
    plan_id: Annotated[str, typer.Option("--plan-id")],
    plan_sha256: Annotated[str, typer.Option("--plan-sha256")],
) -> None:
    """Consume one exact approval and publish the normalized static authoring derivative."""

    result = normalize_external_static_asset(job_id, plan_id, plan_sha256)
    console.print_json(result.model_dump_json())


@app.command("external-intake-validate")
def external_intake_validate(job_id: str) -> None:
    """Verify external source, dependencies, contracts, normalized blend, and provenance."""

    result = validate_external_static_asset_intake(job_id)
    console.print_json(result.model_dump_json())
    if not result.ok:
        raise typer.Exit(code=2)


@app.command("external-intake-status")
def external_intake_status(job_id: str) -> None:
    """Show read-only external-intake approval, normalization, and V0.7 readiness."""

    console.print_json(
        json.dumps(get_external_static_asset_intake_status(job_id), ensure_ascii=False)
    )


@app.command("asset-preflight")
def asset_preflight(
    job_id: str,
    profile: Annotated[str, typer.Option("--profile")] = "portable_gltf",
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Inspect canonical mesh portability without changing the authoring scene."""

    result = preflight_asset(job_id, profile_id=profile, run_id=run_id)
    console.print_json(result.model_dump_json())
    if not result.ok:
        raise typer.Exit(code=2)


@app.command("asset-optimize")
def asset_optimize(
    job_id: str,
    approved_plan_sha256: Annotated[str, typer.Option("--approved-plan-sha256")],
    profile: Annotated[str, typer.Option("--profile")] = "portable_gltf",
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Execute one reviewed and explicitly approved run-owned optimization plan."""

    result = optimize_asset(
        job_id,
        profile_id=profile,
        run_id=run_id,
        approved_plan_sha256=approved_plan_sha256,
    )
    console.print_json(result.model_dump_json())


@app.command("asset-plan")
def asset_plan(
    job_id: str,
    profile: Annotated[str, typer.Option("--profile")] = "portable_gltf",
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Show exact LOD, collider, batching, and cost assumptions before execution."""

    result = plan_asset_optimization(job_id, profile_id=profile, run_id=run_id)
    console.print_json(result.model_dump_json())


@app.command("asset-plan-approve")
def asset_plan_approve(
    job_id: str,
    run_id: Annotated[str, typer.Option("--run-id")],
    plan_sha256: Annotated[str, typer.Option("--plan-sha256")],
    approval_note: Annotated[str, typer.Option("--approval-note")],
) -> None:
    """Record one hash-bound user approval for a reviewed optimization plan."""

    result = approve_asset_optimization(
        job_id,
        run_id=run_id,
        plan_sha256=plan_sha256,
        approval_note=approval_note,
    )
    console.print_json(result.model_dump_json())


@app.command("asset-package")
def asset_package(
    job_id: str,
    profile: Annotated[str, typer.Option("--profile")] = "portable_gltf",
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    package_id: Annotated[str | None, typer.Option("--package-id")] = None,
    material_conversion_id: Annotated[str | None, typer.Option("--material-conversion-id")] = None,
    include_colliders: Annotated[
        bool, typer.Option("--include-colliders/--exclude-colliders")
    ] = True,
) -> None:
    """Build one immutable portable package from a complete optimization run."""

    result = package_asset(
        job_id,
        profile_id=profile,
        run_id=run_id,
        package_id=package_id,
        material_conversion_id=material_conversion_id,
        include_colliders=include_colliders,
    )
    console.print_json(result.model_dump_json())


@app.command("asset-material-convert")
def asset_material_convert(
    job_id: str,
    run_id: Annotated[str, typer.Option("--run-id")],
    conversion_id: Annotated[str, typer.Option("--conversion-id")],
    profile: Annotated[str, typer.Option("--profile")] = "portable_gltf",
    resolution: Annotated[int, typer.Option("--resolution", min=16)] = 1024,
    margin_px: Annotated[int, typer.Option("--margin-px", min=1)] = 16,
    render_device: Annotated[str, typer.Option("--render-device")] = "auto",
) -> None:
    """Bake run-owned portable PBR atlases without changing authoring materials."""

    if render_device not in {"auto", "cpu", "gpu"}:
        raise typer.BadParameter("render-device must be auto, cpu, or gpu")
    result = convert_portable_materials(
        job_id,
        profile_id=profile,
        run_id=run_id,
        conversion_id=conversion_id,
        resolution=resolution,
        margin_px=margin_px,
        render_device=render_device,
    )
    console.print_json(result.model_dump_json())


@app.command("asset-validate")
def asset_validate(
    job_id: str,
    package_id: Annotated[str, typer.Option("--package-id")],
    profile: Annotated[str, typer.Option("--profile")] = "portable_gltf",
    bounds_tolerance_m: Annotated[
        float, typer.Option("--bounds-tolerance-m", min=0.000001)
    ] = 0.0001,
) -> None:
    """Clean-import one immutable package and verify normalized portable semantics."""

    result = validate_asset_package(
        job_id,
        package_id,
        profile_id=profile,
        bounds_tolerance_m=bounds_tolerance_m,
    )
    console.print_json(result.model_dump_json())
    if not result.ok:
        raise typer.Exit(code=2)


@app.command("asset-status")
def portable_asset_status(job_id: str) -> None:
    """Show V0.7 profiles, optimization runs, packages, and validation evidence."""

    console.print_json(json.dumps(get_asset_status(job_id), ensure_ascii=False))


@app.command("handoff-plan")
def handoff_plan_command(
    job_id: str,
    profile: Annotated[str, typer.Option("--profile")],
    package_id: Annotated[str, typer.Option("--package-id")],
    handoff_id: Annotated[str | None, typer.Option("--handoff-id")] = None,
    destination_hint: Annotated[str | None, typer.Option("--destination-hint")] = None,
) -> None:
    """Plan one package-bound destination handoff without copying or changing assets."""

    result = plan_destination_handoff(
        job_id,
        profile_id=profile,
        package_id=package_id,
        handoff_id=handoff_id,
        destination_hint=destination_hint,
    )
    console.print_json(result.model_dump_json())


@app.command("handoff-generate")
def handoff_generate_command(
    job_id: str,
    handoff_id: Annotated[str, typer.Option("--handoff-id")],
    plan_sha256: Annotated[str, typer.Option("--plan-sha256")],
) -> None:
    """Generate one immutable destination handoff from the exact reviewed plan hash."""

    result = generate_destination_handoff(
        job_id,
        handoff_id,
        approved_plan_sha256=plan_sha256,
    )
    console.print_json(result.model_dump_json())


@app.command("handoff-validate")
def handoff_validate_command(
    job_id: str,
    profile: Annotated[str, typer.Option("--profile")],
    package_id: Annotated[str, typer.Option("--package-id")],
    handoff_id: Annotated[str, typer.Option("--handoff-id")],
) -> None:
    """Read-only verify every handoff file and its exact source package binding."""

    result = validate_destination_handoff(
        job_id,
        profile_id=profile,
        package_id=package_id,
        handoff_id=handoff_id,
    )
    console.print_json(result.model_dump_json())
    if not result.ok:
        raise typer.Exit(code=2)


@app.command("handoff-status")
def handoff_status_command(job_id: str) -> None:
    """Show planned, generated, valid, invalid, and stale destination handoffs."""

    console.print_json(json.dumps(get_destination_handoff_status(job_id), ensure_ascii=False))


@app.command("workflow-plan")
def workflow_plan_command(
    request: Annotated[str, typer.Option("--request")],
    job_id: Annotated[str | None, typer.Option("--job-id")] = None,
    reference_path: Annotated[str | None, typer.Option("--reference-path")] = None,
    intent: Annotated[str, typer.Option("--intent")] = "auto",
    scope: Annotated[str, typer.Option("--scope")] = "auto",
    reference_content_scope: Annotated[
        str | None, typer.Option("--reference-content-scope")
    ] = None,
    target_subject: Annotated[str | None, typer.Option("--target-subject")] = None,
    execution_policy: Annotated[str, typer.Option("--execution-policy")] = "standard",
    revision_strategy: Annotated[str, typer.Option("--revision-strategy")] = "candidate_review",
    delivery_scope: Annotated[str | None, typer.Option("--delivery-scope")] = None,
    mode: Annotated[str, typer.Option("--mode")] = "concept",
    view_kind: Annotated[str | None, typer.Option("--view-kind")] = None,
    replace_view: Annotated[bool, typer.Option("--replace-view")] = False,
    scale_anchor: Annotated[list[str] | None, typer.Option("--scale-anchor")] = None,
    profile: Annotated[str, typer.Option("--profile")] = "portable_gltf",
    destination: Annotated[str, typer.Option("--destination")] = "unspecified",
    destination_name: Annotated[str | None, typer.Option("--destination-name")] = None,
    destination_version: Annotated[str | None, typer.Option("--destination-version")] = None,
    max_host_steps: Annotated[int, typer.Option("--max-host-steps", min=1, max=64)] = 8,
    max_qa_iterations: Annotated[int, typer.Option("--max-qa-iterations", min=0, max=10)] = 1,
    max_texture_resolution: Annotated[
        int, typer.Option("--max-texture-resolution", min=16, max=8192)
    ] = 2048,
    max_lod0_triangles: Annotated[int | None, typer.Option("--max-lod0-triangles", min=1)] = None,
    external_provider_budget: Annotated[
        int, typer.Option("--external-provider-budget", min=0, max=100)
    ] = 0,
    include_destination_handoff: Annotated[
        bool,
        typer.Option("--include-destination-handoff/--no-destination-handoff"),
    ] = False,
) -> None:
    """Route one short request into an immutable approval-aware workflow plan."""

    state = plan_orchestrated_workflow(
        request,
        job_id=job_id,
        reference_path=reference_path,
        intent=intent,
        scope=scope,
        reference_content_scope=reference_content_scope,
        target_subject=target_subject,
        execution_policy=execution_policy,
        revision_strategy=revision_strategy,
        delivery_scope=delivery_scope,
        mode=mode,
        view_kind=view_kind,
        replace_view=replace_view,
        scale_anchors=scale_anchor or [],
        profile_id=profile,
        destination_kind=destination,
        destination_name=destination_name,
        destination_version=destination_version,
        include_destination_handoff=include_destination_handoff,
        budgets=WorkflowBudgets(
            max_host_steps_per_resume=max_host_steps,
            max_qa_iterations=max_qa_iterations,
            max_texture_resolution=max_texture_resolution,
            max_lod0_triangles=max_lod0_triangles,
            external_provider_budget=external_provider_budget,
        ),
    )
    console.print_json(state.model_dump_json())


@app.command("autonomy-profile-status")
def autonomy_profile_status_command(
    profile_id: Annotated[str | None, typer.Option("--profile-id")] = None,
) -> None:
    """List the sole verified autonomy profile and disabled experimental entries."""

    console.print_json(
        json.dumps(get_autonomy_profile_status(profile_id), ensure_ascii=False)
    )


@app.command("autonomy-v2-profile-status")
def autonomy_v2_profile_status_command() -> None:
    """Report the parallel AQ v2 activation state without enabling it."""

    console.print_json(json.dumps(autonomy_v2_profile_status(), ensure_ascii=False))


@app.command("autonomy-v2-delivery-profiles")
def autonomy_v2_delivery_profiles_command() -> None:
    """List exact review, GLB, and FBX delivery mappings for AQ v2."""

    console.print_json(json.dumps(delivery_profile_catalog(), ensure_ascii=False))


@app.command("codex-imagegen-status")
def codex_imagegen_status_command(
    job_id: Annotated[str | None, typer.Option("--job-id")] = None,
    session_id: Annotated[str | None, typer.Option("--session-id")] = None,
) -> None:
    """Report static capability or one persisted ImageGen overlay without prompts."""

    console.print_json(
        json.dumps(
            get_codex_imagegen_public_status(
                job_id=job_id,
                session_id=session_id,
            ),
            ensure_ascii=False,
        )
    )


@app.command("codex-imagegen-plan")
def codex_imagegen_plan_command(
    request: str,
    reference_path: Annotated[str, typer.Option("--reference")],
    target_subject: Annotated[str, typer.Option("--target-subject")],
    target_material_ids: Annotated[str, typer.Option("--target-material-ids")],
    semantic_roles: Annotated[str, typer.Option("--semantic-roles")],
    prompt_template_id: Annotated[str, typer.Option("--prompt-template-id")],
    deliveries: Annotated[
        str,
        typer.Option(
            "--deliveries",
            help="Comma-separated: review_only,portable_gltf,portable_fbx",
        ),
    ] = "portable_gltf",
    allowed_output_roles: Annotated[
        str,
        typer.Option(
            "--output-roles",
            help="Comma-separated: base_color,decal_rgb,emission,opacity_source",
        ),
    ] = "base_color",
    generation_intent: Annotated[
        str,
        typer.Option("--generation-intent"),
    ] = "generated_surface_swatch_v1",
    requested_candidate_count: Annotated[
        int,
        typer.Option("--candidate-count", min=1, max=3),
    ] = 1,
    quality_level: Annotated[str, typer.Option("--quality-level")] = "low",
    image_width: Annotated[int, typer.Option("--image-width", min=64, max=2048)] = 1024,
    image_height: Annotated[int, typer.Option("--image-height", min=64, max=2048)] = 1024,
    aspect_ratio: Annotated[str, typer.Option("--aspect-ratio")] = "square",
    fallback: Annotated[str, typer.Option("--fallback")] = "local_procedural_fallback",
    job_id: Annotated[str | None, typer.Option("--job-id")] = None,
    controller_execution_mode: Annotated[
        str,
        typer.Option("--controller-mode"),
    ] = "desktop_in_session",
    destination_hint: Annotated[
        str,
        typer.Option("--destination-hint"),
    ] = "engine_neutral",
    enable_v2: Annotated[
        bool,
        typer.Option(
            "--enable-v2/--disable-v2",
            help="Explicitly opt in to the AQ v2 Codex ImageGen overlay.",
        ),
    ] = False,
    allow_disabled_experimental: Annotated[
        bool,
        typer.Option(
            "--allow-disabled-experimental/--deny-disabled-experimental",
            help="Explicitly permit planning while the companion profile is disabled.",
        ),
    ] = False,
) -> None:
    """Plan the disabled ImageGen overlay only after both explicit opt-ins."""

    result = plan_autonomous_static_prop_v2_codex_imagegen(
        request,
        reference_path=reference_path,
        target_subject=target_subject,
        requested_delivery_profiles=_parse_required_csv(
            deliveries,
            option_name="deliveries",
        ),  # type: ignore[arg-type]
        target_material_ids=_parse_required_csv(
            target_material_ids,
            option_name="target-material-ids",
        ),
        semantic_roles=_parse_required_csv(
            semantic_roles,
            option_name="semantic-roles",
        ),
        allowed_output_roles=_parse_required_csv(
            allowed_output_roles,
            option_name="output-roles",
        ),  # type: ignore[arg-type]
        generation_intent=generation_intent,  # type: ignore[arg-type]
        prompt_template_id=prompt_template_id,
        requested_candidate_count=requested_candidate_count,
        quality_level=quality_level,  # type: ignore[arg-type]
        image_width=image_width,
        image_height=image_height,
        aspect_ratio=aspect_ratio,  # type: ignore[arg-type]
        fallback=fallback,
        job_id=job_id,
        controller_execution_mode=controller_execution_mode,
        destination_hint=destination_hint,
        codex_imagegen_allowed=enable_v2,
        allow_disabled_experimental=allow_disabled_experimental,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("codex-imagegen-run")
def codex_imagegen_run_command(
    job_id: str,
    session_id: str,
    prompt_file: Annotated[
        Path | None,
        typer.Option(
            "--prompt-file",
            help="UTF-8 prompt file required only when publishing a new assignment.",
        ),
    ] = None,
    plan_item_id: Annotated[
        str | None,
        typer.Option("--plan-item-id"),
    ] = None,
    exact_text_value: Annotated[
        str | None,
        typer.Option(
            "--exact-text-value",
            help="Local-composition text guard; never a request for generated text.",
        ),
    ] = None,
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, max=900),
    ] = 900,
) -> None:
    """Publish or resume one waiting desktop assignment without invoking ImageGen."""

    result = run_codex_imagegen_controller_phase(
        job_id=job_id,
        session_id=session_id,
        rendered_prompt_text=_read_optional_prompt_file(prompt_file),
        plan_item_id=plan_item_id,
        exact_text_value=exact_text_value,
        timeout_seconds=timeout_seconds,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("codex-imagegen-select")
def codex_imagegen_select_command(job_id: str, session_id: str) -> None:
    """Evaluate staged candidates locally and select at most one exact candidate."""

    console.print_json(
        json.dumps(
            select_codex_imagegen_phase(job_id=job_id, session_id=session_id),
            ensure_ascii=False,
        )
    )


@app.command("codex-imagegen-adopt")
def codex_imagegen_adopt_command(
    job_id: str,
    session_id: str,
    material_request: Annotated[
        Path | None,
        typer.Option(
            "--material-request",
            help="Contained MaterialAuthoring 0.2.1 request used only to finalize staging.",
        ),
    ] = None,
    material_strategy: Annotated[
        str | None,
        typer.Option(
            "--material-strategy",
            help="Optional strategy override used only while preparing adoption.",
        ),
    ] = None,
    direct_channels: Annotated[
        str | None,
        typer.Option(
            "--direct-channels",
            help="Optional comma-separated direct channels used only while preparing adoption.",
        ),
    ] = None,
    exact_text_evidence: Annotated[
        Path | None,
        typer.Option(
            "--exact-text-evidence",
            help=(
                "Contained ExactSignageTextEvidence 0.2.1 JSON used only while "
                "preparing adoption."
            ),
        ),
    ] = None,
) -> None:
    """Prepare an adoption contract or finalize one strict local material request."""

    if material_request is not None:
        if (
            material_strategy is not None
            or direct_channels is not None
            or exact_text_evidence is not None
        ):
            raise typer.BadParameter(
                "material-strategy, direct-channels, and exact-text-evidence "
                "are prepare-only options"
            )
        result = adopt_codex_imagegen_material_phase(
            job_id=job_id,
            session_id=session_id,
            material_request_path=material_request,
        )
    else:
        result = prepare_codex_imagegen_material_adoption(
            job_id=job_id,
            session_id=session_id,
            material_strategy=material_strategy,
            direct_channels=(
                None
                if direct_channels is None
                else _parse_required_csv(
                    direct_channels,
                    option_name="direct-channels",
                )
            ),
            exact_text_evidence_path=exact_text_evidence,
        )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("autonomy-v2-plan")
def autonomy_v2_plan_command(
    request: str,
    reference_path: Annotated[str, typer.Option("--reference")],
    target_subject: Annotated[str, typer.Option("--target-subject")],
    deliveries: Annotated[
        str,
        typer.Option(
            "--deliveries",
            help="Comma-separated: review_only,portable_gltf,portable_fbx",
        ),
    ] = "portable_gltf",
    job_id: Annotated[str | None, typer.Option("--job-id")] = None,
    controller_execution_mode: Annotated[
        str, typer.Option("--controller-mode")
    ] = "desktop_in_session",
    destination_hint: Annotated[
        str, typer.Option("--destination-hint")
    ] = "engine_neutral",
    experimental_opt_in: Annotated[
        bool,
        typer.Option("--enable-v2/--disable-v2"),
    ] = False,
) -> None:
    """Plan the disabled-by-default AQ v2 overlay only after explicit experimental opt-in."""

    requested = [item.strip() for item in deliveries.split(",") if item.strip()]
    result = plan_autonomous_static_prop_v2(
        request,
        reference_path=reference_path,
        target_subject=target_subject,
        requested_delivery_profiles=requested,  # type: ignore[arg-type]
        job_id=job_id,
        controller_execution_mode=controller_execution_mode,
        destination_hint=destination_hint,
        allow_disabled_experimental=experimental_opt_in,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("autonomy-v2-status")
def autonomy_v2_status_command(job_id: str, session_id: str) -> None:
    """Reconstruct one experimental v2 session without advancing it."""

    console.print_json(
        json.dumps(get_autonomy_v2_status(job_id, session_id), ensure_ascii=False)
    )


def _load_quality_submission_payload(path: Path | None) -> dict[str, object] | None:
    """Read one strict AQ v2 quality-submission object for a CLI host action."""

    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("AQ v2 quality submission JSON must contain one object")
    return payload


@app.command("autonomy-v2-advance")
def autonomy_v2_advance_command(
    job_id: str,
    session_id: str,
    quality_submission: Annotated[
        Path | None,
        typer.Option("--quality-submission"),
    ] = None,
    experimental_opt_in: Annotated[
        bool,
        typer.Option("--enable-v2/--disable-v2"),
    ] = False,
) -> None:
    """Advance at most one experimental AQ v2 host action and stop at safe boundaries."""

    result = advance_autonomy_v2(
        job_id,
        session_id,
        quality_submission=_load_quality_submission_payload(quality_submission),
        allow_disabled_experimental=experimental_opt_in,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("autonomy-v2-run")
def autonomy_v2_run_command(
    job_id: str,
    session_id: str,
    max_actions: Annotated[int, typer.Option("--max-actions")] = 8,
    quality_submission: Annotated[
        Path | None,
        typer.Option("--quality-submission"),
    ] = None,
    experimental_opt_in: Annotated[
        bool,
        typer.Option("--enable-v2/--disable-v2"),
    ] = False,
) -> None:
    """Run a bounded AQ v2 action loop that stops at input, controller, and approvals."""

    result = run_autonomy_v2(
        job_id,
        session_id,
        max_actions=max_actions,
        quality_submission=_load_quality_submission_payload(quality_submission),
        allow_disabled_experimental=experimental_opt_in,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("autonomy-v2-cancel")
def autonomy_v2_cancel_command(
    job_id: str,
    session_id: str,
    reason: Annotated[str, typer.Option("--reason")],
) -> None:
    """Cancel future v2 actions while preserving immutable session evidence."""

    console.print_json(
        json.dumps(
            cancel_autonomy_v2(job_id, session_id, reason=reason),
            ensure_ascii=False,
        )
    )


@app.command("controller-executor-status")
def controller_executor_status_command() -> None:
    """Report exact controller adapter and phase-profile availability."""

    console.print_json(json.dumps(controller_capability_catalog(), ensure_ascii=False))


@app.command("scene-spec-v03-migration-plan")
def scene_spec_v03_migration_plan_command(job_id: str, migration_id: str) -> None:
    """Create one immutable derived-only SceneSpec 0.3 migration plan and candidate."""

    console.print_json(
        json.dumps(
            plan_scene_spec_v03_migration(job_id, migration_id),
            ensure_ascii=False,
        )
    )


@app.command("scene-spec-v03-migration-apply")
def scene_spec_v03_migration_apply_command(
    job_id: str,
    migration_id: str,
    exact_plan_sha256: Annotated[str, typer.Option("--exact-plan-sha256")],
) -> None:
    """Apply one exact migration plan to a derived copy without canonical mutation."""

    console.print_json(
        json.dumps(
            apply_scene_spec_v03_migration(
                job_id,
                migration_id,
                exact_plan_sha256=exact_plan_sha256,
            ),
            ensure_ascii=False,
        )
    )


@app.command("autonomy-plan")
def autonomy_plan_command(
    request: str,
    reference_path: Annotated[str, typer.Option("--reference")],
    target_subject: Annotated[str, typer.Option("--target-subject")],
    job_id: Annotated[str | None, typer.Option("--job-id")] = None,
    controller_execution_mode: Annotated[
        str, typer.Option("--controller-mode")
    ] = "desktop_in_session",
    include_destination_handoff_envelope: Annotated[
        bool,
        typer.Option("--handoff-envelope/--no-handoff-envelope"),
    ] = False,
) -> None:
    """Create one bounded static-prop autonomy overlay on a new standard workflow."""

    result = plan_autonomous_static_prop(
        request,
        reference_path=reference_path,
        target_subject=target_subject,
        job_id=job_id,
        controller_execution_mode=controller_execution_mode,
        include_destination_handoff_envelope=(
            include_destination_handoff_envelope
        ),
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("autonomy-bind")
def autonomy_bind_command(
    job_id: str,
    session_id: str,
    external_task_id: Annotated[str, typer.Option("--external-task-id")],
    external_host_id: Annotated[str | None, typer.Option("--external-host-id")] = None,
    enforced_controller_tool_profile_sha256: Annotated[
        str | None,
        typer.Option("--tool-profile-sha256"),
    ] = None,
) -> None:
    """Bind a client-mediated autonomy session to one exact external controller task."""

    from .autonomy.service import bind_autonomy_controller

    result = bind_autonomy_controller(
        job_id,
        session_id,
        external_task_id=external_task_id,
        external_host_id=external_host_id,
        enforced_controller_tool_profile_sha256=(
            enforced_controller_tool_profile_sha256
        ),
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("autonomy-status")
def autonomy_status_command(job_id: str, session_id: str) -> None:
    """Verify and report one exact autonomy session without advancing it."""

    from .autonomy.service import get_autonomy_status

    console.print_json(
        json.dumps(get_autonomy_status(job_id, session_id), ensure_ascii=False)
    )


@app.command("autonomy-advance")
def autonomy_advance_command(job_id: str, session_id: str) -> None:
    """Execute at most one locked state-machine action and write its exact receipt."""

    from .autonomy.service import advance_autonomy

    console.print_json(
        json.dumps(advance_autonomy(job_id, session_id), ensure_ascii=False)
    )


@app.command("autonomy-run")
def autonomy_run_command(
    job_id: str,
    session_id: str,
    max_actions: Annotated[int, typer.Option("--max-actions", min=1, max=64)] = 8,
) -> None:
    """Supervise a bounded number of separately locked autonomy actions."""

    from .autonomy.service import run_autonomy

    console.print_json(
        json.dumps(
            run_autonomy(job_id, session_id, max_actions=max_actions),
            ensure_ascii=False,
        )
    )


@app.command("autonomy-resume")
def autonomy_resume_command(
    job_id: str,
    session_id: str,
    max_actions: Annotated[int, typer.Option("--max-actions", min=1, max=64)] = 8,
) -> None:
    """Resume a non-terminal session through the same bounded supervisor contract."""

    from .autonomy.service import resume_autonomy

    console.print_json(
        json.dumps(
            resume_autonomy(job_id, session_id, max_actions=max_actions),
            ensure_ascii=False,
        )
    )


@app.command("autonomy-cancel")
def autonomy_cancel_command(
    job_id: str,
    session_id: str,
    reason: Annotated[str, typer.Option("--reason")],
) -> None:
    """Cancel future autonomy actions without deleting canonical or immutable evidence."""

    from .autonomy.service import cancel_autonomy

    console.print_json(
        json.dumps(
            cancel_autonomy(job_id, session_id, reason=reason),
            ensure_ascii=False,
        )
    )


@app.command("integrated-quality-run")
def integrated_quality_run_command(
    job_id: str,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    quality_profile_path: Annotated[
        str | None, typer.Option("--quality-profile")
    ] = None,
    qa_report_path: Annotated[str | None, typer.Option("--qa-report")] = None,
    validation_path: Annotated[str | None, typer.Option("--validation")] = None,
    material_validation_path: Annotated[
        str | None, typer.Option("--material-validation")
    ] = None,
    material_fidelity_path: Annotated[
        str | None, typer.Option("--material-fidelity")
    ] = None,
    mesh_preflight_path: Annotated[
        str | None, typer.Option("--mesh-preflight")
    ] = None,
    roundtrip_path: Annotated[str | None, typer.Option("--roundtrip")] = None,
) -> None:
    """Write an immutable four-axis companion report from explicit existing evidence."""

    result = run_integrated_quality(
        job_id,
        run_id=run_id,
        quality_profile_path=quality_profile_path,
        qa_report_path=qa_report_path,
        validation_path=validation_path,
        material_validation_path=material_validation_path,
        material_fidelity_path=material_fidelity_path,
        mesh_preflight_path=mesh_preflight_path,
        roundtrip_path=roundtrip_path,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("integrated-quality-status")
def integrated_quality_status_command(
    job_id: str,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Verify one exact companion report; latest is only a convenience selector."""

    console.print_json(
        json.dumps(
            get_integrated_quality_status(job_id, run_id),
            ensure_ascii=False,
        )
    )


@app.command("production-dispatch")
def production_dispatch_command(
    request: Annotated[str, typer.Option("--request")],
    reference_path: Annotated[str, typer.Option("--reference")],
    purpose: Annotated[str, typer.Option("--purpose")],
    job_id: Annotated[str | None, typer.Option("--job-id")] = None,
    mode: Annotated[str, typer.Option("--mode")] = "concept",
    reference_content_scope: Annotated[
        str, typer.Option("--content-scope")
    ] = "full_reference",
    target_subject: Annotated[str | None, typer.Option("--subject")] = None,
    execution_policy: Annotated[str, typer.Option("--policy")] = "standard",
    controller_execution_mode: Annotated[
        str, typer.Option("--ctrl-mode")
    ] = "client_mediated",
    profile: Annotated[str, typer.Option("--profile")] = "portable_gltf",
    destination: Annotated[str, typer.Option("--dest-kind")] = "unspecified",
    destination_name: Annotated[str | None, typer.Option("--dest-name")] = None,
    destination_version: Annotated[str | None, typer.Option("--dest-version")] = None,
    destination_render_pipeline: Annotated[
        str | None, typer.Option("--dest-pipeline")
    ] = None,
    include_destination_handoff: Annotated[
        bool,
        typer.Option("--handoff/--no-handoff"),
    ] = False,
    max_host_steps: Annotated[int, typer.Option("--host-limit", min=1, max=64)] = 8,
    max_qa_iterations: Annotated[int, typer.Option("--qa-limit", min=0, max=10)] = 1,
    max_texture_resolution: Annotated[
        int, typer.Option("--texture-limit", min=16, max=8192)
    ] = 2048,
    max_lod0_triangles: Annotated[int | None, typer.Option("--triangle-limit", min=1)] = None,
    external_provider_budget: Annotated[
        int, typer.Option("--provider-limit", min=0, max=100)
    ] = 0,
    convergence_mode: Annotated[
        str, typer.Option("--convergence")
    ] = "disabled",
    convergence_target_direct_score: Annotated[
        float | None, typer.Option("--target-direct", min=0.0, max=1.0)
    ] = None,
    convergence_target_silhouette_iou: Annotated[
        float | None, typer.Option("--target-iou", min=0.0, max=1.0)
    ] = None,
    convergence_minimum_iteration_gain: Annotated[
        float, typer.Option("--min-gain", min=0.000001, max=1.0)
    ] = 0.001,
    convergence_minimum_candidate_confidence: Annotated[
        float, typer.Option("--min-confidence", min=0.0, max=1.0)
    ] = 0.8,
    convergence_max_iterations: Annotated[
        int, typer.Option("--conv-iters", min=1, max=5)
    ] = 3,
) -> None:
    """Create a V0.8 workflow and an explicit production-controller bundle."""

    result = create_asset_production_dispatch(
        request,
        reference_path=reference_path,
        purpose=purpose,
        job_id=job_id,
        mode=mode,
        reference_content_scope=reference_content_scope,
        target_subject=target_subject,
        execution_policy=execution_policy,
        controller_execution_mode=controller_execution_mode,
        profile_id=profile,
        destination_kind=destination,
        destination_name=destination_name,
        destination_version=destination_version,
        destination_render_pipeline=destination_render_pipeline,
        include_destination_handoff=include_destination_handoff,
        max_host_steps_per_resume=max_host_steps,
        max_qa_iterations=max_qa_iterations,
        max_texture_resolution=max_texture_resolution,
        max_lod0_triangles=max_lod0_triangles,
        external_provider_budget=external_provider_budget,
        convergence_mode=convergence_mode,
        convergence_target_direct_score=convergence_target_direct_score,
        convergence_target_silhouette_iou=convergence_target_silhouette_iou,
        convergence_minimum_iteration_gain=convergence_minimum_iteration_gain,
        convergence_minimum_candidate_confidence=(
            convergence_minimum_candidate_confidence
        ),
        convergence_max_iterations=convergence_max_iterations,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("production-bind-task")
def production_bind_task_command(
    job_id: str,
    dispatch_id: str,
    controller_id: Annotated[str, typer.Option("--controller-id")],
    external_task_id: Annotated[str, typer.Option("--external-task-id")],
    external_host_id: Annotated[str | None, typer.Option("--external-host-id")] = None,
    confirm_controller_tool_policy: Annotated[
        bool,
        typer.Option("--confirm-tool-profile"),
    ] = False,
    enforced_controller_tool_profile_sha256: Annotated[
        str,
        typer.Option("--tool-profile-sha256"),
    ] = "",
) -> None:
    """Bind a task created by a supporting Codex client to one exact launch manifest."""

    binding = bind_asset_production_task(
        job_id,
        dispatch_id,
        controller_id,
        external_task_id=external_task_id,
        external_host_id=external_host_id,
        client_tool_policy_enforced=confirm_controller_tool_policy,
        enforced_controller_tool_profile_sha256=(
            enforced_controller_tool_profile_sha256
        ),
    )
    console.print_json(binding.model_dump_json())


@app.command("production-status")
def production_status_command(job_id: str, dispatch_id: str) -> None:
    """Read production state without running host work or changing workflow evidence."""

    console.print_json(
        json.dumps(
            get_asset_production_dispatch_status(job_id, dispatch_id),
            ensure_ascii=False,
        )
    )


@app.command("production-advance")
def production_advance_command(
    job_id: str,
    dispatch_id: str,
    controller_id: Annotated[str, typer.Option("--controller-id")],
    max_host_steps: Annotated[int | None, typer.Option("--max-host-steps", min=1, max=64)] = None,
) -> None:
    """Advance one safe production-controller action and stop at existing approvals."""

    result = advance_delegated_production_controller(
        job_id,
        dispatch_id,
        controller_id,
        max_host_steps=max_host_steps,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("production-complete-step")
def production_complete_step_command(
    job_id: str,
    dispatch_id: str,
    controller_id: Annotated[str, typer.Option("--controller-id")],
    step_id: Annotated[str, typer.Option("--step-id")],
    input_fingerprint: Annotated[str, typer.Option("--input-fingerprint")],
    note: Annotated[str, typer.Option("--note")],
) -> None:
    """Record one controller-authored V0.8 agent step through its exact assignment."""

    result = record_delegated_production_step(
        job_id,
        dispatch_id,
        controller_id,
        step_id=step_id,
        input_fingerprint=input_fingerprint,
        note=note,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("candidate-review-approve")
def candidate_review_approve_command(
    job_id: str,
    trial_id: str,
    decision_sha256: Annotated[str, typer.Option("--decision-sha256")],
    approval_note: Annotated[str | None, typer.Option("--approval-note")] = None,
) -> None:
    """Approve one exact promotable candidate decision for single-use promotion."""

    approval = approve_candidate_review(
        job_id,
        trial_id,
        decision_sha256=decision_sha256,
        approval_note=approval_note,
    )
    console.print_json(approval.model_dump_json())


@app.command("candidate-review-status")
def candidate_review_status_command(job_id: str, trial_id: str) -> None:
    """Read candidate decision, approval, source freshness, and promotion state."""

    console.print_json(
        json.dumps(
            get_candidate_review_status(job_id, trial_id),
            ensure_ascii=False,
        )
    )


@app.command("candidate-review-recover-promotion")
def candidate_review_recover_promotion_command(
    job_id: str,
    trial_id: str,
    decision_sha256: Annotated[str, typer.Option("--decision-sha256")],
    workflow_id: Annotated[str | None, typer.Option("--workflow-id")] = None,
) -> None:
    """Rollback one consumed receipt-less candidate promotion to its exact baseline."""

    receipt = recover_failed_candidate_review_promotion(
        job_id,
        trial_id,
        decision_sha256=decision_sha256,
        workflow_id=workflow_id,
    )
    console.print_json(receipt.model_dump_json())


@app.command("workflow-status")
def workflow_status_command(
    job_id: str,
    workflow_id: Annotated[str | None, typer.Option("--workflow-id")] = None,
) -> None:
    """Read one persisted workflow state without executing or approving anything."""

    console.print_json(json.dumps(get_workflow_status(job_id, workflow_id), ensure_ascii=False))


@app.command("workflow-reconcile")
def workflow_reconcile_command(job_id: str, workflow_id: str) -> None:
    """Reconstruct workflow state from exact current artifacts and receipts."""

    state = reconcile_workflow(job_id, workflow_id)
    console.print_json(state.model_dump_json())


@app.command("workflow-resume")
def workflow_resume_command(
    job_id: str,
    workflow_id: str,
    max_host_steps: Annotated[int | None, typer.Option("--max-host-steps", min=1, max=64)] = None,
    retry_failed: Annotated[
        bool,
        typer.Option(
            "--retry-failed",
            help="Explicitly retry only the current failed deterministic host step.",
        ),
    ] = False,
) -> None:
    """Run deterministic host steps, requiring an explicit flag for failed retries."""

    state = resume_workflow(
        job_id,
        workflow_id,
        max_host_steps=max_host_steps,
        retry_failed=retry_failed,
    )
    console.print_json(state.model_dump_json())
    if state.status == "failed":
        raise typer.Exit(code=2)


@app.command("workflow-complete-step")
def workflow_complete_step_command(
    job_id: str,
    workflow_id: str,
    step_id: Annotated[str, typer.Option("--step-id")],
    input_fingerprint: Annotated[str, typer.Option("--input-fingerprint")],
    note: Annotated[str, typer.Option("--note")],
) -> None:
    """Bind one agent-authored output marker to current workflow inputs and files."""

    state = complete_workflow_step(
        job_id,
        workflow_id,
        step_id,
        input_fingerprint=input_fingerprint,
        note=note,
    )
    console.print_json(state.model_dump_json())


@app.command("workflow-approve")
def workflow_approve_command(
    job_id: str,
    workflow_id: str,
    step_id: Annotated[str, typer.Option("--step-id")],
    artifact_fingerprint: Annotated[str, typer.Option("--artifact-fingerprint")],
    approval_note: Annotated[str, typer.Option("--approval-note")],
) -> None:
    """Approve one exact generic checkpoint without bypassing specialized approvals."""

    state = approve_workflow_gate(
        job_id,
        workflow_id,
        step_id,
        artifact_fingerprint=artifact_fingerprint,
        approval_note=approval_note,
    )
    console.print_json(state.model_dump_json())


@app.command("workflow-cancel")
def workflow_cancel_command(
    job_id: str,
    workflow_id: str,
    reason: Annotated[str, typer.Option("--reason")],
) -> None:
    """Stop future workflow execution without deleting any generated evidence."""

    state = cancel_workflow(job_id, workflow_id, reason=reason)
    console.print_json(state.model_dump_json())


@app.command("workflow-adapters")
def workflow_adapters_command() -> None:
    """List validated destination capabilities and engine-neutral fallbacks."""

    console.print_json(json.dumps(destination_adapters(), ensure_ascii=False))


@app.command("stability-probe")
def stability_probe_command(
    probe_id: Annotated[str | None, typer.Option("--probe-id")] = None,
) -> None:
    """Snapshot privacy-safe V0.9 host and existing Blender compatibility evidence."""

    report = probe_release_environment(probe_id=probe_id)
    console.print_json(report.model_dump_json())


@app.command("workspace-audit")
def workspace_audit_command(
    job_id: Annotated[str | None, typer.Option("--job-id")] = None,
    audit_id: Annotated[str | None, typer.Option("--audit-id")] = None,
    scan_limit: Annotated[int | None, typer.Option("--scan-limit", min=100, max=1_000_000)] = None,
) -> None:
    """Audit workspace hashes and receipts without migrating or repairing canonical data."""

    report = audit_workspace_state(
        job_id=job_id,
        audit_id=audit_id,
        scan_limit=scan_limit,
    )
    console.print_json(report.model_dump_json())
    if report.status == "failed":
        raise typer.Exit(code=2)


@app.command("stability-report-pdf")
def stability_report_pdf_command(
    probe_id: Annotated[str, typer.Option("--probe-id")],
    audit_id: Annotated[str, typer.Option("--audit-id")],
    report_id: Annotated[str, typer.Option("--report-id")],
) -> None:
    """Render immutable V0.9 environment and audit evidence as a PDF summary."""

    result = generate_stability_pdf_report(
        probe_id,
        audit_id,
        report_id=report_id,
    )
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("queue-enqueue")
def queue_enqueue_command(
    job_id: str,
    workflow_id: str,
    priority: Annotated[int, typer.Option("--priority", min=0, max=100)] = 50,
    max_attempts: Annotated[int, typer.Option("--max-attempts", min=1, max=10)] = 3,
) -> None:
    """Queue one existing non-terminal V0.8 workflow for bounded local execution."""

    queue = enqueue_short_workflow(
        job_id,
        workflow_id,
        priority=priority,
        max_attempts=max_attempts,
    )
    console.print_json(queue.model_dump_json())


@app.command("queue-status")
def queue_status_command() -> None:
    """Read the local workflow queue without resuming or approving any workflow."""

    console.print_json(get_local_workflow_queue().model_dump_json())


@app.command("queue-run")
def queue_run_command(
    max_entries: Annotated[int, typer.Option("--max-entries", min=1, max=64)] = 1,
    max_host_steps: Annotated[int | None, typer.Option("--max-host-steps", min=1, max=64)] = None,
) -> None:
    """Run queued host work sequentially and stop at agent or approval boundaries."""

    queue = run_local_workflow_queue(
        max_entries=max_entries,
        max_host_steps=max_host_steps,
    )
    console.print_json(queue.model_dump_json())


@app.command("queue-requeue")
def queue_requeue_command(
    entry_id: str,
    retry_failed: Annotated[
        bool,
        typer.Option(
            "--retry-failed",
            help="Explicitly authorize retry of only the current failed V0.8 host step.",
        ),
    ] = False,
) -> None:
    """Requeue one failed entry only with explicit failed-step retry authorization."""

    queue = requeue_local_workflow(entry_id, retry_failed=retry_failed)
    console.print_json(queue.model_dump_json())


@app.command("queue-cancel")
def queue_cancel_command(
    entry_id: str,
    reason: Annotated[str, typer.Option("--reason")],
) -> None:
    """Cancel future queue dispatch without cancelling the underlying workflow."""

    queue = cancel_local_workflow_queue_entry(entry_id, reason=reason)
    console.print_json(queue.model_dump_json())


@app.command()
def build(job_id: str) -> None:
    """Build blender/scene.blend from analysis/scene_spec.json."""
    root = job_dir(job_id)
    spec_path = root / "analysis" / "scene_spec.json"
    load_scene_spec(spec_path)
    validate_job_surface_details(
        job_id,
        require_materials=None,
        write_report=True,
        raise_on_error=True,
    )
    output = root / "blender" / "scene.blend"
    result = run_blender("build_scene.py", ["--spec", str(spec_path), "--output", str(output)])
    console.print(result.stdout.strip())
    console.print(f"Built: {output}")


@app.command()
def render(job_id: str) -> None:
    """Render a comparison preview."""
    root = job_dir(job_id)
    blend = root / "blender" / "scene.blend"
    output = root / "renders" / "preview.png"
    result = run_blender(
        "render_preview.py",
        ["--output", str(output)],
        blend_file=blend,
    )
    console.print(result.stdout.strip())
    console.print(f"Rendered: {output}")


@app.command()
def inspect(job_id: str) -> None:
    """Write a scene inventory report."""
    root = job_dir(job_id)
    blend = root / "blender" / "scene.blend"
    output = root / "reports" / "scene_inventory.json"
    run_blender("inspect_scene.py", ["--output", str(output)], blend_file=blend)
    console.print(f"Inventory: {output}")


@app.command()
def validate(job_id: str) -> None:
    """Run deterministic schema and Blender scene checks."""
    root = job_dir(job_id)
    spec_path = root / "analysis" / "scene_spec.json"
    load_scene_spec(spec_path)
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
        ["--spec", str(spec_path), "--output", str(output)],
        blend_file=blend,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    console.print_json(json.dumps(report, ensure_ascii=False))
    if not report.get("ok", False):
        raise typer.Exit(code=2)


@app.command("export")
def export_scene(
    job_id: str,
    format: Annotated[str, typer.Option("--format")] = "glb",
) -> None:
    """Export the generated scene."""
    if format not in {"glb", "gltf", "obj", "fbx"}:
        raise typer.BadParameter("format must be glb, gltf, obj, or fbx")
    root = job_dir(job_id)
    blend = root / "blender" / "scene.blend"
    suffix = ".glb" if format == "glb" else f".{format}"
    output = root / "exports" / f"scene{suffix}"
    run_blender(
        "export_scene.py",
        ["--format", format, "--output", str(output)],
        blend_file=blend,
    )
    console.print(f"Exported: {output}")


@app.command()
def status(job_id: str) -> None:
    """Show job files and current SceneSpec counts."""
    root = job_dir(job_id)
    metadata = load_job(job_id)
    table = Table(title=f"Job: {job_id}")
    table.add_column("Item")
    table.add_column("Status")
    table.add_row("Mode", metadata.get("mode", "unknown"))
    interior = get_interior_scope_status(job_id)
    table.add_row(
        "Interior policy",
        f"{interior['effective_policy']} ({interior['scope_state']})",
    )
    for rel in [
        "job.json",
        "analysis/reference_analysis.json",
        "analysis/camera_solution.json",
        "analysis/modeling_plan.json",
        "analysis/scene_spec.json",
        "analysis/material_plan.json",
        "architecture/interior_scope.json",
        "architecture/interior_scope.approval.json",
        "constraints/constraints.json",
        "blender/scene.blend",
        "renders/preview.png",
        "reports/scene_inventory.json",
        "reports/validation.json",
        "reports/constraint_solution.json",
        "reports/material_contract_validation.json",
        "reports/material_validation.json",
        "reports/material_swatches.json",
        "reports/material_bakes.json",
        "reports/surface_detail_validation.json",
        "reports/interior_scope_validation.json",
        "qa/latest.json",
        "optimization/latest.json",
        "exports/scene.glb",
    ]:
        table.add_row(rel, "exists" if (root / rel).exists() else "missing")
    pdf_root = report_output_dir(job_id)
    for name in (
        "build_report.pdf",
        "material_report.pdf",
        "qa_report.pdf",
        "export_report.pdf",
        "full_report.pdf",
    ):
        path = pdf_root / name
        table.add_row(f"output/pdf/{job_id}/{name}", "exists" if path.exists() else "missing")
    console.print(table)


if __name__ == "__main__":
    app()
