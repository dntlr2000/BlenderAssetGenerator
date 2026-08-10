"""Bounded session-owned V0.5 material candidate authoring and selection."""

from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from ..blender_artifacts import native_io_path, stable_json_digest
from ..material_manifest import load_material_manifest
from ..materials.fidelity import evaluate_material_fidelity
from ..materials.io import load_material_plan, load_shader_recipe, resolve_job_path
from ..materials.models import MaterialPlan, MaterialValidationReport, ShaderRecipe
from ..materials.validation import validate_material_contracts
from ..orchestration.models import WorkflowPlan, WorkflowState
from ..production.models import DelegatedWorkAssignment
from ..texturing.models import TextureChannel, TextureManifest, TextureProvenance
from ..workspace import sha256_file
from .authorization import (
    artifact_for,
    canonical_digest,
    validate_policy_authorization,
)
from .io import ensure_autonomy_path, write_immutable_json
from .material_models import (
    MaterialCandidateAssignment,
    MaterialCandidateCompletionMarker,
    MaterialCandidateEvaluation,
    MaterialCandidatePromotionReceipt,
    MaterialCandidateRanking,
    MaterialCandidateStrategy,
    MaterialRoundInputSnapshot,
)
from .models import AutonomyArtifact, PolicyAuthorization, PolicyGateTarget

_STRATEGIES: tuple[MaterialCandidateStrategy, ...] = (
    "portable_pbr_v05",
    "faithful_v05",
)


def _utc_now() -> datetime:
    """Return one timezone-aware timestamp for immutable material evidence."""

    return datetime.now(UTC)


def _path_exists(path: Path) -> bool:
    """Check one material-round path through extended-length Windows syntax."""

    return os.path.exists(native_io_path(path))


def _path_is_file(path: Path) -> bool:
    """Check one material-round file without the Windows MAX_PATH limit."""

    return os.path.isfile(native_io_path(path))


def _read_utf8(path: Path) -> str:
    """Read one material-round JSON artifact through its native path."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        return handle.read()


def _read_bytes(path: Path) -> bytes:
    """Read one exact material candidate payload through its native path."""

    with open(native_io_path(path), "rb") as handle:
        return handle.read()


def _write_bytes(path: Path, content: bytes) -> None:
    """Write one exact material candidate payload through its native path."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    with open(native_io_path(path), "wb") as handle:
        handle.write(content)


def _relative(root: Path, path: Path) -> str:
    """Return one normalized job-relative path after containment verification."""

    resolved = ensure_autonomy_path(root, path, must_exist=_path_exists(path))
    return resolved.relative_to(root.resolve()).as_posix()


def _json_bytes(value: Any) -> bytes:
    """Serialize one Pydantic model or JSON value with deterministic UTF-8 layout."""

    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _write_exact_once(root: Path, path: Path, content: bytes) -> None:
    """Publish exact bytes once, accepting only an identical interrupted-run recovery."""

    destination = ensure_autonomy_path(root, path, must_exist=False)
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    ensure_autonomy_path(root, destination.parent, must_exist=True)
    if _path_exists(destination):
        if not _path_is_file(destination) or _read_bytes(destination) != content:
            raise FileExistsError(f"immutable material evidence differs: {destination}")
        return
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    _write_bytes(temporary, content)
    os.replace(native_io_path(temporary), native_io_path(destination))


def _verify_artifact(root: Path, artifact: AutonomyArtifact) -> Path:
    """Require one contained regular file to retain its exact recorded SHA-256."""

    path = ensure_autonomy_path(root, root / artifact.path, must_exist=True)
    if not _path_is_file(path) or sha256_file(path) != artifact.sha256:
        raise ValueError(f"material-round artifact is stale or tampered: {artifact.path}")
    return path


def _artifact_from_content(root: Path, path: Path, content: bytes) -> AutonomyArtifact:
    """Describe not-yet-published contained bytes using their final relative path."""

    relative = path.resolve().relative_to(root.resolve()).as_posix()
    return AutonomyArtifact(
        path=relative,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _dependency_artifacts(root: Path, plan: MaterialPlan) -> list[AutonomyArtifact]:
    """Hash all existing recipe, manifest, and image dependencies used by one plan."""

    paths: dict[str, Path] = {}
    for item in plan.materials:
        manifest_value = item.texture_manifest
        if item.shader_recipe:
            recipe_path = resolve_job_path(root, item.shader_recipe, "shader recipe")
            paths[_relative(root, recipe_path)] = recipe_path
            manifest_value = manifest_value or load_shader_recipe(recipe_path).texture_manifest
        if not manifest_value:
            continue
        manifest, manifest_path = load_material_manifest(
            {"id": item.material_id, "texture_manifest": manifest_value},
            root,
        )
        if manifest is None or manifest_path is None:
            raise RuntimeError("declared texture manifest could not be loaded")
        paths[_relative(root, manifest_path)] = manifest_path
        for channel in manifest["channels"].values():
            resolved = channel.get("resolved_path")
            if resolved:
                channel_path = Path(str(resolved))
                paths[_relative(root, channel_path)] = channel_path
    return [artifact_for(root, paths[key]) for key in sorted(paths)]


def _material_authoring_context(
    root: Path,
    production_assignment: AutonomyArtifact,
) -> tuple[DelegatedWorkAssignment, WorkflowPlan, AutonomyArtifact, Path]:
    """Validate the exact current V0.8 material.author assignment and output path."""

    assignment = DelegatedWorkAssignment.model_validate_json(
        _read_utf8(_verify_artifact(root, production_assignment))
    )
    if assignment.step_id != "material.author":
        raise ValueError("AQ material rounds require the current material.author assignment")
    workflow_path = root / "workflows" / assignment.workflow_id / "plan.json"
    workflow_artifact = artifact_for(root, workflow_path)
    workflow = WorkflowPlan.model_validate_json(_read_utf8(workflow_path))
    if workflow.job_id != assignment.job_id:
        raise ValueError("material assignment and workflow plan job identities differ")
    if workflow_artifact.sha256 != assignment.workflow_plan_sha256:
        raise ValueError("material assignment workflow plan binding is stale")
    step = next((item for item in workflow.steps if item.step_id == "material.author"), None)
    if step is None:
        raise ValueError("workflow does not declare material.author")
    authored_plan = resolve_job_path(
        root,
        str(step.parameters.get("candidate_plan_path", "")),
        "workflow authored material plan",
    )
    if not _path_is_file(authored_plan):
        raise FileNotFoundError(authored_plan)
    authored_root = authored_plan.parent.relative_to(root).as_posix()
    if not any(
        Path(path).as_posix() == authored_root
        for path in assignment.controller_expected_outputs
    ):
        raise ValueError("material assignment does not own the authored output directory")
    return assignment, workflow, workflow_artifact, authored_plan


def _input_snapshot(
    root: Path,
    session_root: Path,
    production_assignment: AutonomyArtifact,
    *,
    round_index: int,
    candidate_limit: int,
    previous_ranking: AutonomyArtifact | None = None,
) -> tuple[MaterialRoundInputSnapshot, AutonomyArtifact, Path]:
    """Create or verify one immutable copy of mutable material-authoring inputs."""

    assignment, workflow, workflow_artifact, authored_plan = _material_authoring_context(
        root,
        production_assignment,
    )
    actual_limit = min(candidate_limit, len(_STRATEGIES))
    if not 1 <= round_index <= 3 or not 1 <= actual_limit <= 3:
        raise ValueError("material round index and candidate limit must be within 1..3")
    round_id = f"mr-{round_index:02d}"
    round_root = ensure_autonomy_path(
        root,
        session_root / "mr" / f"r{round_index:02d}",
        must_exist=False,
    )
    input_root = round_root / "input"
    snapshot_path = input_root / "snapshot.json"
    if _path_is_file(snapshot_path):
        snapshot = MaterialRoundInputSnapshot.model_validate_json(
            _read_utf8(snapshot_path)
        )
        snapshot_artifact = artifact_for(root, snapshot_path)
        if (
            snapshot.production_assignment != production_assignment
            or snapshot.workflow_plan != workflow_artifact
            or snapshot.round_index != round_index
            or snapshot.candidate_limit != actual_limit
            or snapshot.previous_ranking != previous_ranking
        ):
            raise ValueError("existing material input snapshot differs from this request")
        for artifact in (
            snapshot.production_assignment,
            snapshot.workflow_plan,
            snapshot.material_plan_snapshot,
            snapshot.scene_spec_snapshot,
            *([snapshot.baseline_material_plan] if snapshot.baseline_material_plan else []),
            *([snapshot.previous_ranking] if snapshot.previous_ranking else []),
            *snapshot.source_dependencies,
        ):
            _verify_artifact(root, artifact)
        return snapshot, snapshot_artifact, round_root

    workflow_plan = load_material_plan(authored_plan)
    if workflow_plan.job_id != assignment.job_id or workflow_plan.stage != "scaffold":
        raise ValueError("material rounds require the untouched V0.8 scaffold candidate")
    baseline_path = authored_plan
    baseline_artifact: AutonomyArtifact | None = None
    ranking_artifact: AutonomyArtifact | None = None
    if round_index > 1:
        if previous_ranking is None:
            raise ValueError("later material rounds require the previous exact ranking")
        ranking_path = _verify_artifact(root, previous_ranking)
        ranking = MaterialCandidateRanking.model_validate_json(
            _read_utf8(ranking_path)
        )
        if (
            ranking.job_id != assignment.job_id
            or ranking.workflow_id != assignment.workflow_id
            or ranking.dispatch_id != assignment.dispatch_id
            or ranking.session_id != session_root.name
            or ranking.round_id != f"mr-{round_index - 1:02d}"
        ):
            raise ValueError("previous material ranking is not the immediate session round")
        baseline_path = _verify_artifact(root, ranking.selected_material_plan)
        baseline_artifact = ranking.selected_material_plan
        ranking_artifact = previous_ranking
    elif previous_ranking is not None:
        raise ValueError("first material round cannot reference a previous ranking")
    plan = load_material_plan(baseline_path)
    if plan.job_id != assignment.job_id:
        raise ValueError("material round baseline belongs to another job")
    scene_path = root / "analysis" / "scene_spec.json"
    if not _path_is_file(scene_path):
        raise FileNotFoundError(scene_path)
    plan_snapshot_path = input_root / "material_plan.json"
    scene_snapshot_path = input_root / "scene_spec.json"
    _write_exact_once(root, plan_snapshot_path, _read_bytes(baseline_path))
    _write_exact_once(root, scene_snapshot_path, _read_bytes(scene_path))
    plan_snapshot = artifact_for(root, plan_snapshot_path)
    scene_snapshot = artifact_for(root, scene_snapshot_path)
    dependencies = _dependency_artifacts(root, plan)
    created_at = _utc_now()
    input_payload = {
        "assignment": production_assignment.model_dump(mode="json"),
        "workflow": workflow_artifact.model_dump(mode="json"),
        "source_plan": sha256_file(authored_plan),
        "baseline_plan": sha256_file(baseline_path),
        "previous_ranking": previous_ranking.model_dump(mode="json") if previous_ranking else None,
        "scene": scene_snapshot.sha256,
        "dependencies": [item.model_dump(mode="json") for item in dependencies],
        "candidate_limit": actual_limit,
    }
    snapshot = MaterialRoundInputSnapshot(
        contract_id=f"{round_id}-input",
        snapshot_id=f"{round_id}-input",
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        input_sha256=canonical_digest(input_payload),
        source_fingerprint=canonical_digest(
            {"input": input_payload, "assignment_input": assignment.input_fingerprint}
        ),
        producer="codex_blender_modeler.autonomy.material_rounds",
        producer_version="0.1.0",
        provenance=[
            production_assignment,
            workflow_artifact,
            plan_snapshot,
            scene_snapshot,
            *([baseline_artifact] if baseline_artifact else []),
            *([ranking_artifact] if ranking_artifact else []),
        ],
        created_at=created_at,
        session_id=session_root.name,
        round_id=round_id,
        round_index=round_index,
        candidate_limit=actual_limit,
        production_assignment=production_assignment,
        workflow_plan=workflow_artifact,
        source_authored_plan_path=_relative(root, authored_plan),
        source_authored_plan_sha256=sha256_file(authored_plan),
        material_plan_snapshot=plan_snapshot,
        baseline_material_plan=baseline_artifact,
        previous_ranking=ranking_artifact,
        scene_spec_snapshot=scene_snapshot,
        source_dependencies=dependencies,
    )
    write_immutable_json(root, snapshot_path, snapshot.model_dump(mode="json"))
    return snapshot, artifact_for(root, snapshot_path), round_root


def _candidate_plan(
    root: Path,
    snapshot: MaterialRoundInputSnapshot,
    candidate_root: Path,
    strategy: MaterialCandidateStrategy,
) -> tuple[
    MaterialPlan,
    list[tuple[Path, ShaderRecipe]],
    list[tuple[Path, bytes]],
]:
    """Build one appearance-preserving plan plus deterministic portable PBR evidence."""

    source = load_material_plan(_verify_artifact(root, snapshot.material_plan_snapshot))
    recipes: list[tuple[Path, ShaderRecipe]] = []
    texture_files: list[tuple[Path, bytes]] = []
    items = []
    for index, item in enumerate(source.materials, start=1):
        recipe_relative: str | None = None
        texture_manifest_relative: str | None = item.texture_manifest
        texture_strategy = item.texture_strategy
        source_recipe: ShaderRecipe | None = None
        if item.shader_recipe:
            source_recipe = load_shader_recipe(
                resolve_job_path(root, item.shader_recipe, "source shader recipe")
            )
            recipe_path = candidate_root / "recipes" / f"material-{index:03d}.json"
            recipe_relative = recipe_path.relative_to(root).as_posix()
        if strategy == "portable_pbr_v05":
            portable_mapping = item.mapping.model_copy(
                update={"mode": "uv", "uv_set": "UVMap"}
            )
            source_recipe = source_recipe or ShaderRecipe(
                material_id=item.material_id,
                family=item.shader_family,
                mapping=portable_mapping,
            )
            source_recipe = source_recipe.model_copy(
                update={"mapping": portable_mapping}
            )
            manifest_path = (
                candidate_root / "textures" / f"material-{index:03d}" / "texture_manifest.json"
            )
            texture_manifest_relative = manifest_path.relative_to(root).as_posix()
            generated = _portable_texture_bundle(
                manifest_path,
                material_id=item.material_id,
                recipe=source_recipe,
            )
            texture_files.extend(generated)
            source_recipe = source_recipe.model_copy(
                update={
                    "texture_manifest": texture_manifest_relative,
                    "bake_required": False,
                    "assumptions": [
                        *source_recipe.assumptions,
                        (
                            "AQ portable candidate uses uniform local PBR maps derived "
                            "only from the exact V0.5 surface values; no unsupported detail "
                            "is invented."
                        ),
                    ],
                }
            )
            texture_strategy = "image"
        if source_recipe is not None:
            if recipe_relative is None:
                recipe_path = candidate_root / "recipes" / f"material-{index:03d}.json"
                recipe_relative = recipe_path.relative_to(root).as_posix()
            recipes.append((recipe_path, source_recipe))
        export_profiles = list(item.export_profiles)
        if strategy == "portable_pbr_v05" and "gltf_pbr" not in export_profiles:
            export_profiles.append("gltf_pbr")
        items.append(
            item.model_copy(
                update={
                    "shader_recipe": recipe_relative,
                    "texture_strategy": texture_strategy,
                    "texture_manifest": texture_manifest_relative,
                    "mapping": (
                        source_recipe.mapping
                        if strategy == "portable_pbr_v05" and source_recipe is not None
                        else item.mapping
                    ),
                    "export_profiles": export_profiles,
                }
            )
        )
    return (
        source.model_copy(
            update={
                "stage": "authored",
                "materials": items,
                "global_notes": [
                    *source.global_notes,
                    (
                        "AQ deterministic material candidate preserves the observed V0.5 "
                        "surface values and does not invent reference-unsupported detail."
                    ),
                ],
            }
        ),
        recipes,
        texture_files,
    )


def _png_bytes(mode: str, color: int | tuple[int, ...], *, size: int = 256) -> bytes:
    """Encode one bounded uniform PNG without introducing unsupported surface detail."""

    stream = io.BytesIO()
    Image.new(mode, (size, size), color=color).save(
        stream,
        format="PNG",
        optimize=False,
        compress_level=9,
    )
    return stream.getvalue()


def _unit_channel(value: float) -> int:
    """Convert one finite normalized surface scalar to an exact 8-bit channel."""

    return max(0, min(255, int(round(float(value) * 255.0))))


def _portable_texture_bundle(
    manifest_path: Path,
    *,
    material_id: str,
    recipe: ShaderRecipe,
) -> list[tuple[Path, bytes]]:
    """Create neutral image-backed PBR channels and their exact TextureManifest bytes."""

    surface = recipe.surface
    base_rgb = tuple(_unit_channel(value) for value in surface.base_color[:3])
    emission_rgb = tuple(
        _unit_channel(value * min(surface.emission_strength, 1.0))
        for value in surface.emission_color[:3]
    )
    channel_bytes: dict[str, bytes] = {
        "base_color": _png_bytes("RGB", base_rgb),
        "roughness": _png_bytes("L", _unit_channel(surface.roughness)),
        "metallic": _png_bytes("L", _unit_channel(surface.metallic)),
        "normal": _png_bytes("RGB", (128, 128, 255)),
        "height": _png_bytes("L", 128),
        "opacity": _png_bytes("L", _unit_channel(surface.alpha)),
        "emission": _png_bytes("RGB", emission_rgb),
    }
    file_names = {name: f"{name}.png" for name in channel_bytes}
    manifest = TextureManifest(
        material_id=material_id,
        uv_set="UVMap" if recipe.mapping.mode == "uv" else "Object",
        intended_scale_m=recipe.mapping.real_world_scale_m,
        resolution=(256, 256),
        source_type="image",
        channels={
            name: TextureChannel(
                source="image",
                path=file_names[name],
                color_space="sRGB" if name in {"base_color", "emission"} else "Non-Color",
            )
            for name in channel_bytes
        },
        provenance=TextureProvenance(
            provider="cbm_autonomy_uniform_pbr",
            provider_version="0.1.0",
            prompt=(
                "Deterministic neutral PBR maps copied from the exact whitelisted "
                "ShaderRecipe surface; no reference-unsupported marks or relief."
            ),
            source_hashes=[
                stable_json_digest(recipe.model_dump(mode="json")),
            ],
            generated_sha256={
                name: hashlib.sha256(content).hexdigest()
                for name, content in channel_bytes.items()
            },
            license="project-local deterministic derivative",
        ),
        shader_recipe=recipe.material_id,
        color_space_rules={
            "base_color": "sRGB",
            "emission": "sRGB",
            "data_channels": "Non-Color",
        },
        generation_notes=(
            "Uniform clean fallback for portable validation; it is not a claim of "
            "reference-matched raster detail."
        ),
        expected_preview_goal="Preserve exact V0.5 surface color and scalar channels.",
    )
    outputs = [
        (manifest_path.parent / file_names[name], content)
        for name, content in sorted(channel_bytes.items())
    ]
    outputs.append((manifest_path, _json_bytes(manifest)))
    return outputs


def _candidate_prompt(strategy: MaterialCandidateStrategy) -> str:
    """Describe the narrow deterministic authoring envelope bound into one assignment."""

    return (
        "Create one local V0.5 MaterialPlan candidate from the exact scaffold. Preserve "
        "material IDs, shader surfaces, texture pointers, UV semantics, and all localized "
        "detail bindings. Do not call providers or invent scratches, seams, grooves, or "
        f"normal relief. Candidate strategy: {strategy}."
    )


def _publish_candidate(
    root: Path,
    round_root: Path,
    snapshot: MaterialRoundInputSnapshot,
    snapshot_artifact: AutonomyArtifact,
    *,
    candidate_index: int,
    strategy: MaterialCandidateStrategy,
) -> tuple[MaterialCandidateCompletionMarker, AutonomyArtifact]:
    """Atomically publish one exact candidate bundle without writing canonical data."""

    candidate_id = f"m{snapshot.round_index:02d}c{candidate_index:02d}"
    candidate_root = round_root / "c" / candidate_id
    completion_path = candidate_root / "completion.json"
    if _path_is_file(completion_path):
        completion = MaterialCandidateCompletionMarker.model_validate_json(
            _read_utf8(completion_path)
        )
        if completion.candidate_id != candidate_id:
            raise ValueError("existing material candidate identity differs")
        for artifact in (
            completion.assignment,
            completion.material_plan,
            *completion.shader_recipes,
            *completion.texture_dependencies,
        ):
            _verify_artifact(root, artifact)
        return completion, artifact_for(root, completion_path)
    if _path_exists(candidate_root):
        raise FileExistsError(f"partial material candidate directory exists: {candidate_root}")

    staging = candidate_root.parent / f".{candidate_id}.{uuid4().hex[:8]}.tmp"
    os.makedirs(native_io_path(staging), exist_ok=False)
    final_plan_path = candidate_root / "material_plan.json"
    plan, recipes, texture_files = _candidate_plan(root, snapshot, candidate_root, strategy)
    plan_bytes = _json_bytes(plan)
    prompt = _candidate_prompt(strategy)
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assignment_path = candidate_root / "assignment.json"
    assignment_input = canonical_digest(
        {
            "round_input": snapshot_artifact.model_dump(mode="json"),
            "candidate_id": candidate_id,
            "strategy": strategy,
            "prompt_sha256": prompt_sha,
        }
    )
    assignment = MaterialCandidateAssignment(
        contract_id=f"assignment-{candidate_id}",
        assignment_id=f"assignment-{candidate_id}",
        job_id=snapshot.job_id,
        workflow_id=snapshot.workflow_id,
        dispatch_id=snapshot.dispatch_id,
        input_sha256=assignment_input,
        source_fingerprint=canonical_digest(
            {"input": assignment_input, "round_source": snapshot.source_fingerprint}
        ),
        producer="codex_blender_modeler.autonomy.material_rounds",
        producer_version="0.1.0",
        provenance=[snapshot_artifact],
        created_at=_utc_now(),
        session_id=snapshot.session_id,
        round_id=snapshot.round_id,
        candidate_id=candidate_id,
        candidate_index=candidate_index,
        strategy=strategy,
        round_input=snapshot_artifact,
        output_root=_relative(root, candidate_root),
        required_outputs=[
            _relative(root, final_plan_path),
            _relative(root, completion_path),
        ],
        authoring_prompt_sha256=prompt_sha,
    )
    assignment_bytes = _json_bytes(assignment)
    recipe_artifacts: list[AutonomyArtifact] = []
    for final_path, recipe in recipes:
        content = _json_bytes(recipe)
        stage_path = staging / final_path.relative_to(candidate_root)
        _write_bytes(stage_path, content)
        recipe_artifacts.append(_artifact_from_content(root, final_path, content))
    texture_artifacts: list[AutonomyArtifact] = []
    for final_path, content in texture_files:
        stage_path = staging / final_path.relative_to(candidate_root)
        _write_bytes(stage_path, content)
        texture_artifacts.append(_artifact_from_content(root, final_path, content))
    _write_bytes(staging / "material_plan.json", plan_bytes)
    _write_bytes(staging / "assignment.json", assignment_bytes)
    plan_artifact = _artifact_from_content(root, final_plan_path, plan_bytes)
    assignment_artifact = _artifact_from_content(root, assignment_path, assignment_bytes)
    bundle_sha = stable_json_digest(
        {
            "assignment": assignment_artifact.model_dump(mode="json"),
            "plan": plan_artifact.model_dump(mode="json"),
            "recipes": [item.model_dump(mode="json") for item in recipe_artifacts],
            "textures": [item.model_dump(mode="json") for item in texture_artifacts],
        }
    )
    completion_input = canonical_digest(
        {
            "assignment": assignment_artifact.model_dump(mode="json"),
            "plan": plan_artifact.model_dump(mode="json"),
            "recipes": [item.model_dump(mode="json") for item in recipe_artifacts],
            "textures": [item.model_dump(mode="json") for item in texture_artifacts],
        }
    )
    completion = MaterialCandidateCompletionMarker(
        contract_id=f"completion-{candidate_id}",
        completion_id=f"completion-{candidate_id}",
        job_id=snapshot.job_id,
        workflow_id=snapshot.workflow_id,
        dispatch_id=snapshot.dispatch_id,
        input_sha256=completion_input,
        source_fingerprint=canonical_digest(
            {"input": completion_input, "bundle": bundle_sha}
        ),
        producer="codex_blender_modeler.autonomy.material_rounds",
        producer_version="0.1.0",
        provenance=[
            assignment_artifact,
            plan_artifact,
            *recipe_artifacts,
            *texture_artifacts,
        ],
        created_at=_utc_now(),
        session_id=snapshot.session_id,
        round_id=snapshot.round_id,
        candidate_id=candidate_id,
        assignment=assignment_artifact,
        material_plan=plan_artifact,
        shader_recipes=recipe_artifacts,
        texture_dependencies=texture_artifacts,
        bundle_sha256=bundle_sha,
    )
    _write_bytes(staging / "completion.json", _json_bytes(completion))
    os.makedirs(native_io_path(candidate_root.parent), exist_ok=True)
    os.replace(native_io_path(staging), native_io_path(candidate_root))
    return completion, artifact_for(root, completion_path)


def _relative_validation_report(
    root: Path,
    report: MaterialValidationReport,
) -> MaterialValidationReport:
    """Remove host-absolute paths from one session-owned validation report."""

    checks = []
    for item in report.checks:
        value = item.path
        if value:
            path = Path(value)
            if path.is_absolute():
                try:
                    value = path.resolve().relative_to(root.resolve()).as_posix()
                except ValueError:
                    value = None
        checks.append(item.model_copy(update={"path": value}))
    return report.model_copy(update={"checks": checks})


def _change_magnitude(baseline: MaterialPlan, candidate: MaterialPlan) -> float:
    """Measure bounded plan metadata changes while ignoring contained recipe relocation."""

    before = {item.material_id: item for item in baseline.materials}
    if not candidate.materials:
        return 1.0
    changed = 0
    for item in candidate.materials:
        source = before.get(item.material_id)
        if source is None:
            changed += 1
            continue
        if set(item.export_profiles) != set(source.export_profiles):
            changed += 1
    return round(changed / len(candidate.materials), 6)


def _evaluate_candidate(
    root: Path,
    round_root: Path,
    snapshot: MaterialRoundInputSnapshot,
    completion: MaterialCandidateCompletionMarker,
    completion_artifact: AutonomyArtifact,
) -> tuple[MaterialCandidateEvaluation, AutonomyArtifact]:
    """Validate one material candidate and preserve unavailable raster evidence honestly."""

    assignment = MaterialCandidateAssignment.model_validate_json(
        _read_utf8(_verify_artifact(root, completion.assignment))
    )
    evaluation_root = round_root / "e" / assignment.candidate_id
    evaluation_path = evaluation_root / "evaluation.json"
    if _path_is_file(evaluation_path):
        evaluation = MaterialCandidateEvaluation.model_validate_json(
            _read_utf8(evaluation_path)
        )
        for artifact in (
            evaluation.assignment,
            evaluation.completion_marker,
            evaluation.material_plan,
            evaluation.contract_validation,
            evaluation.fidelity_report,
        ):
            _verify_artifact(root, artifact)
        return evaluation, artifact_for(root, evaluation_path)
    plan_path = _verify_artifact(root, completion.material_plan)
    plan = load_material_plan(plan_path)
    scene = json.loads(
        _read_utf8(_verify_artifact(root, snapshot.scene_spec_snapshot))
    )
    validation = _relative_validation_report(
        root,
        validate_material_contracts(plan, scene, root),
    )
    fidelity = evaluate_material_fidelity(root, plan_path=plan_path)
    validation_path = evaluation_root / "contract_validation.json"
    fidelity_path = evaluation_root / "fidelity_report.json"
    _write_exact_once(root, validation_path, _json_bytes(validation))
    _write_exact_once(root, fidelity_path, _json_bytes(fidelity))
    validation_artifact = artifact_for(root, validation_path)
    fidelity_artifact = artifact_for(root, fidelity_path)
    portable_count = sum("gltf_pbr" in item.export_profiles for item in plan.materials)
    portable_coverage = portable_count / len(plan.materials) if plan.materials else 0.0
    baseline = load_material_plan(_verify_artifact(root, snapshot.material_plan_snapshot))
    magnitude = _change_magnitude(baseline, plan)
    eligible = validation.ok and fidelity.status != "failed"
    reasons = [
        "Strict V0.5 material-contract validation passed."
        if validation.ok
        else "Strict V0.5 material-contract validation failed.",
        (
            "Image-backed fidelity evidence is unavailable; no visual pass is claimed."
            if fidelity.status == "unscorable"
            else f"Deterministic material fidelity status is {fidelity.status}."
        ),
        f"Portable glTF material coverage is {portable_coverage:.3f}.",
    ]
    input_payload = {
        "completion": completion_artifact.model_dump(mode="json"),
        "validation": validation_artifact.model_dump(mode="json"),
        "fidelity": fidelity_artifact.model_dump(mode="json"),
    }
    evaluation = MaterialCandidateEvaluation(
        contract_id=f"evaluation-{assignment.candidate_id}",
        evaluation_id=f"evaluation-{assignment.candidate_id}",
        job_id=snapshot.job_id,
        workflow_id=snapshot.workflow_id,
        dispatch_id=snapshot.dispatch_id,
        input_sha256=canonical_digest(input_payload),
        source_fingerprint=canonical_digest(
            {"input": input_payload, "round_source": snapshot.source_fingerprint}
        ),
        producer="codex_blender_modeler.autonomy.material_rounds",
        producer_version="0.1.0",
        provenance=[
            completion_artifact,
            completion.material_plan,
            validation_artifact,
            fidelity_artifact,
        ],
        created_at=_utc_now(),
        session_id=snapshot.session_id,
        round_id=snapshot.round_id,
        candidate_id=assignment.candidate_id,
        candidate_index=assignment.candidate_index,
        strategy=assignment.strategy,
        assignment=completion.assignment,
        completion_marker=completion_artifact,
        material_plan=completion.material_plan,
        contract_validation=validation_artifact,
        fidelity_report=fidelity_artifact,
        contract_valid=validation.ok,
        fidelity_status=fidelity.status,
        portable_material_coverage=round(portable_coverage, 6),
        change_magnitude=magnitude,
        eligible_for_selection=eligible,
        ranking_reasons=reasons,
    )
    write_immutable_json(root, evaluation_path, evaluation.model_dump(mode="json"))
    return evaluation, artifact_for(root, evaluation_path)


def _ranking_key(evaluation: MaterialCandidateEvaluation) -> tuple[int, int, float, float, int]:
    """Rank valid evidence first, then fidelity, portability, and smallest bounded change."""

    fidelity_rank = {"passed": 0, "warning": 1, "unscorable": 2, "failed": 3}
    return (
        0 if evaluation.eligible_for_selection else 1,
        fidelity_rank[evaluation.fidelity_status],
        -evaluation.portable_material_coverage,
        evaluation.change_magnitude,
        evaluation.candidate_index,
    )


def prepare_material_candidate_round(
    root: Path,
    session_root: Path,
    *,
    production_assignment: AutonomyArtifact,
    candidate_limit: int,
    round_index: int = 1,
    previous_ranking: AutonomyArtifact | None = None,
) -> tuple[MaterialCandidateRanking, AutonomyArtifact]:
    """Create, validate, and rank bounded local V0.5 candidates without promotion."""

    root = root.resolve()
    session_root = ensure_autonomy_path(root, session_root, must_exist=True)
    snapshot, snapshot_artifact, round_root = _input_snapshot(
        root,
        session_root,
        production_assignment,
        round_index=round_index,
        candidate_limit=candidate_limit,
        previous_ranking=previous_ranking,
    )
    ranking_path = round_root / "ranking.json"
    if _path_is_file(ranking_path):
        ranking = MaterialCandidateRanking.model_validate_json(
            _read_utf8(ranking_path)
        )
        for artifact in (
            ranking.round_input,
            *ranking.candidate_evaluations,
            ranking.selected_evaluation,
            ranking.selected_material_plan,
        ):
            _verify_artifact(root, artifact)
        return ranking, artifact_for(root, ranking_path)

    evaluated: list[tuple[MaterialCandidateEvaluation, AutonomyArtifact]] = []
    for index, strategy in enumerate(_STRATEGIES[: snapshot.candidate_limit], start=1):
        completion, completion_artifact = _publish_candidate(
            root,
            round_root,
            snapshot,
            snapshot_artifact,
            candidate_index=index,
            strategy=strategy,
        )
        evaluated.append(
            _evaluate_candidate(
                root,
                round_root,
                snapshot,
                completion,
                completion_artifact,
            )
        )
    eligible = [item for item in evaluated if item[0].eligible_for_selection]
    if not eligible:
        raise RuntimeError("no strictly valid local V0.5 material candidate exists")
    selected, selected_artifact = min(eligible, key=lambda item: _ranking_key(item[0]))
    input_payload = {
        "round_input": snapshot_artifact.model_dump(mode="json"),
        "evaluations": [artifact.model_dump(mode="json") for _item, artifact in evaluated],
    }
    ranking = MaterialCandidateRanking(
        contract_id=f"ranking-{snapshot.round_id}",
        ranking_id=f"ranking-{snapshot.round_id}",
        job_id=snapshot.job_id,
        workflow_id=snapshot.workflow_id,
        dispatch_id=snapshot.dispatch_id,
        input_sha256=canonical_digest(input_payload),
        source_fingerprint=canonical_digest(
            {"input": input_payload, "round_source": snapshot.source_fingerprint}
        ),
        producer="codex_blender_modeler.autonomy.material_rounds",
        producer_version="0.1.0",
        provenance=[snapshot_artifact, *[artifact for _item, artifact in evaluated]],
        created_at=_utc_now(),
        session_id=snapshot.session_id,
        round_id=snapshot.round_id,
        round_input=snapshot_artifact,
        candidate_evaluations=[artifact for _item, artifact in evaluated],
        selected_evaluation=selected_artifact,
        selected_material_plan=selected.material_plan,
        material_quality_status=selected.fidelity_status,
        selection_reasons=[
            "Candidates with failed contracts or failed fidelity evidence were excluded.",
            "Available fidelity evidence outranks portability metadata.",
            "Ties prefer portable glTF coverage and then the smallest plan change.",
            (
                "The selected result remains unscorable for visual material fidelity."
                if selected.fidelity_status == "unscorable"
                else f"Selected material fidelity status: {selected.fidelity_status}."
            ),
        ],
    )
    write_immutable_json(root, ranking_path, ranking.model_dump(mode="json"))
    return ranking, artifact_for(root, ranking_path)


def create_material_candidate_policy_target(
    root: Path,
    session_root: Path,
    *,
    ranking_artifact: AutonomyArtifact,
    production_assignment: AutonomyArtifact,
) -> AutonomyArtifact:
    """Create the exact gate target required for a material candidate policy grant."""

    root = root.resolve()
    session_root = ensure_autonomy_path(root, session_root, must_exist=True)
    ranking = MaterialCandidateRanking.model_validate_json(
        _read_utf8(_verify_artifact(root, ranking_artifact))
    )
    assignment, _workflow, workflow_artifact, _authored = _material_authoring_context(
        root,
        production_assignment,
    )
    if (
        ranking.job_id != assignment.job_id
        or ranking.workflow_id != assignment.workflow_id
        or ranking.dispatch_id != assignment.dispatch_id
        or ranking.session_id != session_root.name
    ):
        raise ValueError("material ranking and production assignment identities differ")
    dependency_fingerprints = {
        "material.author": assignment.input_fingerprint,
        "material.ranking": ranking_artifact.sha256,
    }
    target = PolicyGateTarget(
        contract_id=f"gate-target-{ranking.round_id}",
        target_id=f"gate-target-{ranking.round_id}",
        job_id=ranking.job_id,
        workflow_id=ranking.workflow_id,
        dispatch_id=ranking.dispatch_id,
        input_sha256=ranking_artifact.sha256,
        source_fingerprint=canonical_digest(
            {
                "workflow_plan": workflow_artifact.sha256,
                "input_fingerprint": ranking_artifact.sha256,
                "dependencies": dependency_fingerprints,
            }
        ),
        producer="codex_blender_modeler.autonomy.material_rounds",
        producer_version="0.1.0",
        provenance=[workflow_artifact, ranking_artifact, production_assignment],
        created_at=_utc_now(),
        session_id=ranking.session_id,
        workflow_step_id="autonomy.material_candidate_promotion",
        workflow_input_fingerprint=ranking_artifact.sha256,
        gate_kind="material_candidate_promotion",
        workflow_plan=workflow_artifact,
        dependency_completion_fingerprints=dependency_fingerprints,
        dependency_artifacts=[production_assignment, ranking_artifact],
    )
    target_path = (
        session_root
        / "mr"
        / f"r{int(ranking.round_id.rsplit('-', 1)[1]):02d}"
        / "policy_target.json"
    )
    if _path_is_file(target_path):
        stored = PolicyGateTarget.model_validate_json(
            _read_utf8(target_path)
        )
        if stored.model_copy(update={"created_at": target.created_at}) != target:
            raise ValueError("existing material policy target differs from exact ranking")
    else:
        write_immutable_json(root, target_path, target.model_dump(mode="json"))
    return artifact_for(root, target_path)


def promote_material_candidate_to_workflow_authored(
    root: Path,
    session_root: Path,
    *,
    ranking_artifact: AutonomyArtifact,
    production_assignment: AutonomyArtifact,
    policy_authorization_artifact: AutonomyArtifact,
) -> tuple[MaterialCandidatePromotionReceipt, AutonomyArtifact]:
    """Place only a policy-selected exact plan where existing V0.8 completion expects it."""

    root = root.resolve()
    session_root = ensure_autonomy_path(root, session_root, must_exist=True)
    ranking = MaterialCandidateRanking.model_validate_json(
        _read_utf8(_verify_artifact(root, ranking_artifact))
    )
    evaluation = MaterialCandidateEvaluation.model_validate_json(
        _read_utf8(_verify_artifact(root, ranking.selected_evaluation))
    )
    selected_path = _verify_artifact(root, ranking.selected_material_plan)
    snapshot = MaterialRoundInputSnapshot.model_validate_json(
        _read_utf8(_verify_artifact(root, ranking.round_input))
    )
    for dependency in snapshot.source_dependencies:
        _verify_artifact(root, dependency)
    assignment, _workflow, _workflow_artifact, authored_plan = (
        _material_authoring_context(root, production_assignment)
    )
    if snapshot.production_assignment != production_assignment:
        raise ValueError("material round is bound to a different production assignment")
    state_path = root / "workflows" / assignment.workflow_id / "state.json"
    state = WorkflowState.model_validate_json(_read_utf8(state_path))
    step_state = next(
        (item for item in state.steps if item.step_id == "material.author"),
        None,
    )
    if (
        state.status != "waiting_for_agent"
        or state.current_step_id != "material.author"
        or step_state is None
        or step_state.input_fingerprint != assignment.input_fingerprint
    ):
        raise PermissionError("workflow is not waiting at the exact material.author boundary")
    policy = PolicyAuthorization.model_validate_json(
        _read_utf8(_verify_artifact(root, policy_authorization_artifact))
    )
    validate_policy_authorization(
        root,
        policy,
        expected_job_id=ranking.job_id,
        expected_workflow_id=ranking.workflow_id,
        expected_step_id="autonomy.material_candidate_promotion",
        expected_gate_kind="material_candidate_promotion",
        expected_input_fingerprint=ranking_artifact.sha256,
    )
    if policy.target_artifact != ranking_artifact:
        raise ValueError("material policy authorization targets a different ranking")
    if not evaluation.eligible_for_selection:
        raise PermissionError("selected material candidate is not eligible")
    if evaluation.material_plan != ranking.selected_material_plan:
        raise ValueError("material ranking selected plan and evaluation disagree")
    current_scene = root / "analysis" / "scene_spec.json"
    if sha256_file(current_scene) != snapshot.scene_spec_snapshot.sha256:
        raise ValueError("SceneSpec changed after the material input snapshot")
    current_hash = sha256_file(authored_plan)
    selected_hash = ranking.selected_material_plan.sha256
    if current_hash not in {snapshot.source_authored_plan_sha256, selected_hash}:
        raise ValueError("workflow-authored MaterialPlan changed outside this AQ round")
    plan = load_material_plan(selected_path)
    validation = validate_material_contracts(
        plan,
        json.loads(_read_utf8(current_scene)),
        root,
    )
    if not validation.ok:
        raise RuntimeError("selected material candidate no longer validates")
    receipt_path = (
        session_root
        / "mr"
        / f"r{int(ranking.round_id.rsplit('-', 1)[1]):02d}"
        / "promotion_receipt.json"
    )
    if current_hash != selected_hash:
        temporary = authored_plan.parent / f".{authored_plan.name}.{uuid4().hex}.tmp"
        _write_bytes(temporary, _read_bytes(selected_path))
        os.replace(native_io_path(temporary), native_io_path(authored_plan))
    if sha256_file(authored_plan) != selected_hash:
        raise RuntimeError("workflow-authored MaterialPlan promotion hash mismatch")
    previous_plan = snapshot.material_plan_snapshot
    input_payload = {
        "ranking": ranking_artifact.model_dump(mode="json"),
        "policy": policy_authorization_artifact.model_dump(mode="json"),
        "assignment": production_assignment.model_dump(mode="json"),
        "selected": ranking.selected_material_plan.model_dump(mode="json"),
    }
    receipt = MaterialCandidatePromotionReceipt(
        contract_id=f"promotion-{ranking.round_id}",
        receipt_id=f"promotion-{ranking.round_id}",
        job_id=ranking.job_id,
        workflow_id=ranking.workflow_id,
        dispatch_id=ranking.dispatch_id,
        input_sha256=canonical_digest(input_payload),
        source_fingerprint=canonical_digest(
            {"input": input_payload, "round_source": ranking.source_fingerprint}
        ),
        producer="codex_blender_modeler.autonomy.material_rounds",
        producer_version="0.1.0",
        provenance=[
            ranking_artifact,
            policy_authorization_artifact,
            production_assignment,
            ranking.selected_material_plan,
            previous_plan,
        ],
        created_at=_utc_now(),
        session_id=ranking.session_id,
        round_id=ranking.round_id,
        ranking=ranking_artifact,
        selected_evaluation=ranking.selected_evaluation,
        selected_material_plan=ranking.selected_material_plan,
        policy_authorization=policy_authorization_artifact,
        production_assignment=production_assignment,
        previous_authored_plan=previous_plan,
        workflow_authored_plan_path=_relative(root, authored_plan),
        workflow_authored_plan_sha256=selected_hash,
        scene_spec_sha256=sha256_file(current_scene),
    )
    if _path_is_file(receipt_path):
        stored = MaterialCandidatePromotionReceipt.model_validate_json(
            _read_utf8(receipt_path)
        )
        if stored.model_copy(update={"created_at": receipt.created_at}) != receipt:
            raise ValueError("existing material promotion receipt differs from recovery")
        receipt = stored
    else:
        write_immutable_json(root, receipt_path, receipt.model_dump(mode="json"))
    return receipt, artifact_for(root, receipt_path)
