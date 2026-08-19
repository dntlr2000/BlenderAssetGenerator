"""Traceable Skill Orchestration 0.1 adapters over V0.8 and AQ One-Prompt."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..auto_revision.models import (
    ConvergenceReport,
    RevisionApproval,
    RevisionCandidates,
)
from ..autonomy_v2 import (
    cancel_one_prompt,
    get_one_prompt_status,
    plan_one_prompt_run,
    resume_one_prompt,
    run_one_prompt,
)
from ..blender_artifacts import (
    deterministic_json_bytes,
    native_io_path,
    publish_bytes_create_once,
    write_json_atomic,
)
from ..config import get_settings
from ..orchestration import (
    cancel_workflow,
    get_workflow_status,
    plan_workflow,
    resume_workflow,
)
from ..orchestration.models import WorkflowPlan, WorkflowState
from ..revision import RevisionPlan
from ..workspace import job_dir, load_job, sha256_file, validate_job_id
from .models import (
    AQSkillAdapterPlan,
    AQSkillAdapterState,
    GuardedRevisionContinuation,
    MaterialImpactReport,
    MaterialImpactSnapshot,
    SkillArtifact,
    SkillBundleManifest,
    SkillBundleResource,
    SkillExecutionReceipt,
    SkillRegistry,
    SkillRouteDecision,
    StandardCompositeRunPlan,
    StandardCompositeRunState,
    StandardCompositeRunTerminal,
    StandardCompositeStageBinding,
    UnderlyingExecutionBinding,
)

_REGISTRY_PATH = Path(".agents/skills/registry.json")
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_STANDARD_ENTRY = "standard-asset-cycle"
_AQ_ENTRY = "aq-one-prompt-orchestrator"


def _utc_now() -> datetime:
    """Return one timezone-aware UTC timestamp for persisted evidence."""

    return datetime.now(UTC)


def _validate_run_id(run_id: str) -> str:
    """Reject run identifiers that cannot be used as portable directory names."""

    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("skill run_id must be a portable lowercase identifier")
    return run_id


def _new_run_id(prefix: str) -> str:
    """Create one collision-resistant portable skill run identifier."""

    return f"{prefix}-{uuid4().hex[:20]}"


def _is_link_or_reparse(path: Path) -> bool:
    """Recognize symlinks and Windows reparse points without following them."""

    metadata = os.lstat(native_io_path(path))
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _assert_no_link_segments(root: Path, path: Path) -> None:
    """Reject every link or reparse point below one trusted owning root."""

    lexical_root = Path(os.path.abspath(native_io_path(root)))
    lexical_path = Path(os.path.abspath(native_io_path(path)))
    try:
        relative = lexical_path.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError("skill path is outside its owning root") from exc
    current = lexical_root
    for segment in relative.parts:
        current /= segment
        if not os.path.lexists(native_io_path(current)):
            raise FileNotFoundError(current)
        if _is_link_or_reparse(current):
            raise ValueError(f"skill path contains a link or reparse point: {relative}")


def _contained_file(root: Path, relative_path: str) -> Path:
    """Resolve one regular non-link file contained by the supplied root."""

    candidate = root / Path(relative_path)
    resolved_root = root.resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"artifact path escapes its owning root: {relative_path}")
    _assert_no_link_segments(root, candidate)
    if not resolved.is_file():
        raise ValueError(f"artifact path must be a regular non-link file: {relative_path}")
    return resolved


def _job_relative(root: Path, path: Path) -> str:
    """Convert one contained job artifact path into normalized POSIX metadata."""

    lexical_root = Path(os.path.abspath(native_io_path(root)))
    lexical_path = Path(os.path.abspath(native_io_path(path)))
    try:
        relative = lexical_path.relative_to(lexical_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"skill artifact is outside its job: {path}") from exc
    _contained_file(root, relative)
    return relative


def _artifact_for(root: Path, path: Path) -> SkillArtifact:
    """Build an exact job-relative file binding for one existing artifact."""

    return SkillArtifact(path=_job_relative(root, path), sha256=sha256_file(path))


def _validate_artifact(root: Path, artifact: SkillArtifact) -> Path:
    """Re-hash one bound artifact and fail closed on mutation or path escape."""

    path = _contained_file(root, artifact.path)
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"skill artifact hash mismatch: {artifact.path}")
    return path


def _publish_model(root: Path, path: Path, model: Any) -> SkillArtifact:
    """Publish one Pydantic model immutably and return its exact binding."""

    payload = deterministic_json_bytes(model.model_dump(mode="json"))
    publish_bytes_create_once(path, payload)
    return _artifact_for(root, path)


def _load_model(root: Path, artifact: SkillArtifact, model_type: Any) -> Any:
    """Validate one exact artifact before parsing it through a strict model."""

    path = _validate_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return model_type.model_validate_json(handle.read())


def _skill_run_root(root: Path, run_id: str, *, create: bool = False) -> Path:
    """Resolve one contained skill-run directory without following aliases."""

    skill_root = root / "skill_runs"
    if skill_root.exists():
        _assert_no_link_segments(root, skill_root)
        if not skill_root.is_dir():
            raise ValueError("skill run root must be a regular directory")
    elif create:
        skill_root.mkdir(parents=True)
    else:
        raise FileNotFoundError(skill_root)
    selected = skill_root / _validate_run_id(run_id)
    if create:
        selected.mkdir(exist_ok=False)
    if not selected.is_dir():
        raise FileNotFoundError(selected)
    resolved_root = root.resolve(strict=True)
    resolved = selected.resolve(strict=True)
    _assert_no_link_segments(root, selected)
    if resolved_root not in resolved.parents:
        raise ValueError("skill run directory is linked or outside its job")
    return resolved


@contextmanager
def _skill_run_lock(run_root: Path) -> Iterator[None]:
    """Serialize one adapter transition and fail closed after interrupted ownership."""

    lock_path = run_root / ".write.lock"
    token = uuid4().hex
    descriptor = os.open(native_io_path(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, token.encode("ascii"))
    finally:
        os.close(descriptor)
    try:
        yield
    finally:
        try:
            current = lock_path.read_text(encoding="ascii")
        except FileNotFoundError:
            current = ""
        if current != token:
            raise RuntimeError("skill run lock ownership changed during execution")
        lock_path.unlink()


def _skill_frontmatter_name(text: str) -> str:
    """Extract one simple YAML skill name without accepting body-text lookalikes."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("skill definition is missing opening YAML front matter")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("skill definition is missing closing YAML front matter") from exc
    values = [
        line.split(":", 1)[1].strip().strip("\"'")
        for line in lines[1:end]
        if line.split(":", 1)[0].strip() == "name" and ":" in line
    ]
    if len(values) != 1 or not _RUN_ID_RE.fullmatch(values[0]):
        raise ValueError("skill definition requires one portable front matter name")
    return values[0]


def load_skill_registry() -> tuple[SkillRegistry, str]:
    """Load the live strict registry and validate every declared local resource."""

    repo_root = get_settings().repo_root.resolve(strict=True)
    path = _contained_file(repo_root, _REGISTRY_PATH.as_posix())
    registry = SkillRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    for skill in registry.skills:
        skill_path = _contained_file(repo_root, skill.skill_path)
        text = skill_path.read_text(encoding="utf-8")
        if _skill_frontmatter_name(text) != skill.skill_id:
            raise ValueError(f"skill front matter name does not match registry: {skill.skill_id}")
        for resource in skill.supporting_resources:
            _contained_file(repo_root, resource)
    return registry, sha256_file(path)


def _registry_map(registry: SkillRegistry) -> dict[str, Any]:
    """Index one validated skill registry by stable skill ID."""

    return {item.skill_id: item for item in registry.skills}


def _transitive_skill_ids(registry: SkillRegistry, entry_skill_id: str) -> list[str]:
    """Resolve one fixed dependency bundle in deterministic dependency-first order."""

    skill_map = _registry_map(registry)
    if entry_skill_id not in registry.entry_skills:
        raise ValueError(f"skill is not a public entrypoint: {entry_skill_id}")
    ordered: list[str] = []
    visited: set[str] = set()

    def visit(skill_id: str) -> None:
        """Append one dependency branch exactly once."""

        if skill_id in visited:
            return
        for dependency in skill_map[skill_id].dependencies:
            visit(dependency)
        visited.add(skill_id)
        ordered.append(skill_id)

    visit(entry_skill_id)
    return ordered


def _snapshot_skill_bundle(
    root: Path,
    run_root: Path,
    *,
    run_id: str,
    job_id: str,
    entry_skill_id: str,
    execution_mode: str,
) -> SkillArtifact:
    """Copy the live registry and authorized transitive resources into one run."""

    repo_root = get_settings().repo_root.resolve(strict=True)
    registry, _registry_sha = load_skill_registry()
    skill_map = _registry_map(registry)
    skill_ids = _transitive_skill_ids(registry, entry_skill_id)
    if any(execution_mode not in skill_map[item].execution_modes for item in skill_ids):
        raise ValueError("entrypoint dependency bundle crosses execution modes")
    registry_source = _contained_file(repo_root, _REGISTRY_PATH.as_posix())
    registry_target = run_root / "snapshots" / "registry.json"
    publish_bytes_create_once(registry_target, registry_source.read_bytes())
    resources: list[SkillBundleResource] = []
    for skill_id in skill_ids:
        definition = skill_map[skill_id]
        declared = [definition.skill_path, *definition.supporting_resources]
        for index, source_name in enumerate(declared):
            source = _contained_file(repo_root, source_name)
            target_name = "SKILL.md" if index == 0 else f"resource-{index:03d}-{source.name}"
            target = run_root / "snapshots" / "skills" / skill_id / target_name
            publish_bytes_create_once(target, source.read_bytes())
            resources.append(
                SkillBundleResource(
                    skill_id=skill_id,
                    source_path=source_name,
                    snapshot_path=_job_relative(root, target),
                    sha256=sha256_file(target),
                )
            )
    manifest = SkillBundleManifest(
        bundle_id=f"bundle-{run_id}",
        run_id=run_id,
        job_id=job_id,
        entry_skill_id=entry_skill_id,
        execution_mode=execution_mode,  # type: ignore[arg-type]
        registry_snapshot=_artifact_for(root, registry_target),
        skill_ids=skill_ids,
        resources=resources,
        created_at=_utc_now(),
    )
    return _publish_model(root, run_root / "bundle.json", manifest)


def _load_bundle(root: Path, run_root: Path) -> tuple[SkillBundleManifest, SkillRegistry]:
    """Replay one bundle only from its immutable registry and resource snapshots."""

    run_relative = run_root.relative_to(root.resolve(strict=True)).as_posix()
    bundle_path = _contained_file(root, f"{run_relative}/bundle.json")
    bundle = SkillBundleManifest.model_validate_json(bundle_path.read_text(encoding="utf-8"))
    if (bundle.job_id, bundle.run_id) != (root.name, run_root.name):
        raise ValueError("skill bundle identity differs from its owning run")
    expected_mode = {
        _STANDARD_ENTRY: "standard",
        _AQ_ENTRY: "aq",
    }.get(bundle.entry_skill_id)
    if expected_mode is None or bundle.execution_mode != expected_mode:
        raise ValueError("skill bundle entrypoint and execution mode differ")
    expected_registry = f"{run_relative}/snapshots/registry.json"
    if bundle.registry_snapshot.path != expected_registry:
        raise ValueError("skill bundle registry snapshot path is not run-owned")
    registry_path = _validate_artifact(root, bundle.registry_snapshot)
    registry = SkillRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
    expected = _transitive_skill_ids(registry, bundle.entry_skill_id)
    if bundle.skill_ids != expected:
        raise ValueError("skill bundle no longer matches its snapshotted dependency DAG")
    skill_map = _registry_map(registry)
    if any(bundle.execution_mode not in skill_map[item].execution_modes for item in expected):
        raise ValueError("skill bundle mode differs from its snapshotted registry")
    expected_resources: list[tuple[str, str, str]] = []
    for skill_id in expected:
        definition = skill_map[skill_id]
        sources = [definition.skill_path, *definition.supporting_resources]
        for index, source_name in enumerate(sources):
            target_name = (
                "SKILL.md"
                if index == 0
                else f"resource-{index:03d}-{Path(source_name).name}"
            )
            expected_resources.append(
                (
                    skill_id,
                    source_name,
                    f"{run_relative}/snapshots/skills/{skill_id}/{target_name}",
                )
            )
    actual_resources = [
        (item.skill_id, item.source_path, item.snapshot_path)
        for item in bundle.resources
    ]
    if actual_resources != expected_resources:
        raise ValueError("skill bundle resource inventory differs from its registry")
    for resource in bundle.resources:
        path = _contained_file(root, resource.snapshot_path)
        if sha256_file(path) != resource.sha256:
            raise ValueError(f"skill snapshot changed: {resource.snapshot_path}")
        if resource.source_path == skill_map[resource.skill_id].skill_path:
            if _skill_frontmatter_name(path.read_text(encoding="utf-8")) != resource.skill_id:
                raise ValueError("snapshotted skill front matter differs from its registry")
    return bundle, registry


def get_skill_catalog() -> dict[str, object]:
    """Return the validated live catalog without creating a run or granting authority."""

    registry, digest = load_skill_registry()
    return {
        "status": "available",
        "registry": registry.model_dump(mode="json"),
        "registry_sha256": digest,
        "entry_skills": list(registry.entry_skills),
        "canonical_write_authority": False,
        "approval_authority": False,
    }


def _capture_material_snapshot(
    root: Path,
    run_root: Path,
    label: str,
) -> MaterialImpactSnapshot:
    """Copy material-sensitive canonical evidence into one immutable run boundary."""

    candidates = {
        "scene_spec": root / "analysis" / "scene_spec.json",
        "modeling_plan": root / "analysis" / "modeling_plan.json",
        "material_plan": root / "analysis" / "material_plan.json",
        "scene_inventory": root / "reports" / "scene_inventory.json",
    }
    artifacts: dict[str, SkillArtifact | None] = {}
    for name, source in candidates.items():
        if not source.is_file():
            artifacts[name] = None
            continue
        target = run_root / "snapshots" / "material" / label / f"{name}.json"
        publish_bytes_create_once(target, source.read_bytes())
        artifacts[name] = _artifact_for(root, target)
    return MaterialImpactSnapshot(**artifacts)


def _json_from_optional_artifact(
    root: Path,
    artifact: SkillArtifact | None,
) -> dict[str, Any] | None:
    """Read one optional exact JSON object used by material-impact projection."""

    if artifact is None:
        return None
    path = _validate_artifact(root, artifact)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"material-impact source must be a JSON object: {artifact.path}")
    return payload


def _material_sensitive_projection(
    root: Path,
    snapshot: MaterialImpactSnapshot,
) -> dict[str, object]:
    """Project only material IDs, assignments, surface details, and UV evidence."""

    scene = _json_from_optional_artifact(root, snapshot.scene_spec) or {}
    modeling = _json_from_optional_artifact(root, snapshot.modeling_plan) or {}
    inventory = _json_from_optional_artifact(root, snapshot.scene_inventory) or {}
    assignments: list[dict[str, object]] = []
    for item in scene.get("objects", []):
        if not isinstance(item, dict):
            continue
        assignments.append(
            {
                "id": item.get("id"),
                "material_id": item.get("material_id"),
                "material_ids": item.get("material_ids"),
            }
        )

    def collect_uv(value: object, prefix: str = "") -> list[tuple[str, object]]:
        """Collect deterministic UV and material-fingerprint fields recursively."""

        found: list[tuple[str, object]] = []
        if isinstance(value, dict):
            for key in sorted(value):
                child = value[key]
                path = f"{prefix}.{key}" if prefix else key
                lowered = key.casefold()
                if "uv" in lowered and ("sha" in lowered or "fingerprint" in lowered):
                    found.append((path, child))
                else:
                    found.extend(collect_uv(child, path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                found.extend(collect_uv(child, f"{prefix}[{index}]"))
        return found

    return {
        "assignments": assignments,
        "surface_details": modeling.get("surface_details", []),
        "uv_fingerprints": collect_uv(inventory),
        "material_plan_present": snapshot.material_plan is not None,
    }


def _publish_material_impact(
    root: Path,
    run_root: Path,
    plan: StandardCompositeRunPlan,
    after: MaterialImpactSnapshot,
) -> SkillArtifact:
    """Compare exact before/after projections and publish the smart-stage decision."""

    changed: list[str] = []
    reasons: list[str] = []
    required = plan.stage_policy == "force_all"
    try:
        before_projection = _material_sensitive_projection(
            root, plan.initial_material_snapshot
        )
        after_projection = _material_sensitive_projection(root, after)
        for key in ("assignments", "surface_details", "uv_fingerprints"):
            if before_projection[key] != after_projection[key]:
                changed.append(key)
        if not bool(before_projection["material_plan_present"]):
            changed.append("material_plan_absent_before_geometry")
        if changed:
            required = True
            reasons.append(
                "Material identities, assignments, localized details, UV evidence, or the "
                "existing MaterialPlan boundary changed."
            )
        elif plan.stage_policy == "smart":
            reasons.append(
                "Material-sensitive projections are unchanged, so V0.5 may be skipped; "
                "fresh V0.6 QA remains mandatory."
            )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        required = True
        changed.append("unscorable_material_impact")
        reasons.append(f"Material impact could not be proven unchanged: {type(exc).__name__}")
    if plan.stage_policy == "force_all":
        reasons.append("force_all explicitly requires a fresh V0.5 stage.")
    report = MaterialImpactReport(
        report_id=f"material-impact-{plan.run_id}",
        run_id=plan.run_id,
        job_id=plan.job_id,
        stage_policy=plan.stage_policy,
        before=plan.initial_material_snapshot,
        after=after,
        material_authoring_required=required,
        changed_inputs=sorted(set(changed)),
        reasons=reasons,
        evaluated_at=_utc_now(),
    )
    return _publish_model(root, run_root / "material_impact.json", report)


def _workflow_plan_artifact(root: Path, workflow_id: str) -> SkillArtifact:
    """Bind one immutable V0.8 child workflow plan to the composite run."""

    return _artifact_for(root, root / "workflows" / workflow_id / "plan.json")


def _publish_stage_binding(
    root: Path,
    run_root: Path,
    *,
    run_id: str,
    job_id: str,
    ordinal: int,
    stage_kind: str,
    skill_id: str,
    workflow_id: str,
    reason: str,
) -> SkillArtifact:
    """Publish one immutable child-workflow binding in sequence order."""

    binding = StandardCompositeStageBinding(
        binding_id=f"stage-{run_id}-{ordinal:04d}",
        run_id=run_id,
        job_id=job_id,
        ordinal=ordinal,
        stage_kind=stage_kind,  # type: ignore[arg-type]
        skill_id=skill_id,
        workflow_id=workflow_id,
        workflow_plan=_workflow_plan_artifact(root, workflow_id),
        created_reason=reason,
        created_at=_utc_now(),
    )
    return _publish_model(root, run_root / "stages" / f"{ordinal:04d}.json", binding)


def _plan_stage_workflow(
    request_text: str,
    *,
    job_id: str,
    stage_kind: str,
    profile_id: str,
    reference_path: str | Path | None = None,
    mode: str = "concept",
    reference_content_scope: str | None = None,
    target_subject: str | None = None,
    revision_strategy: str = "candidate_review",
) -> tuple[WorkflowState, str]:
    """Plan one existing V0.8 stage and return its primary guidance skill."""

    if stage_kind == "geometry" and reference_path is not None:
        state = plan_workflow(
            request_text,
            job_id=job_id,
            reference_path=reference_path,
            intent="new_asset",
            scope="full",
            delivery_scope="preview_only",
            mode=mode,
            reference_content_scope=reference_content_scope,
            target_subject=target_subject,
            profile_id=profile_id,
        )
        skill_id = "reference-to-scene"
    elif stage_kind == "geometry":
        state = plan_workflow(
            request_text,
            job_id=job_id,
            intent="revise_asset",
            scope="geometry_only",
            revision_strategy=revision_strategy,
            profile_id=profile_id,
        )
        skill_id = "guarded-visual-revision"
    elif stage_kind == "material":
        state = plan_workflow(
            request_text,
            job_id=job_id,
            intent="material_authoring",
            scope="material_only",
            profile_id=profile_id,
        )
        skill_id = "material-authoring"
    elif stage_kind == "qa":
        state = plan_workflow(
            request_text,
            job_id=job_id,
            intent="visual_qa",
            scope="qa_only",
            profile_id=profile_id,
        )
        skill_id = "visual-qa"
    elif stage_kind == "portable":
        state = plan_workflow(
            request_text,
            job_id=job_id,
            intent="portable_package",
            scope="portable_only",
            profile_id=profile_id,
        )
        skill_id = "portable-asset-delivery"
    else:
        raise ValueError(f"unsupported Standard composite stage: {stage_kind}")
    return state, skill_id


def _plan_child_workflow(
    root: Path,
    run_root: Path,
    *,
    run_id: str,
    job_id: str,
    ordinal: int,
    request_text: str,
    stage_kind: str,
    profile_id: str,
    reason: str,
    reference_path: str | Path | None = None,
    mode: str = "concept",
    reference_content_scope: str | None = None,
    target_subject: str | None = None,
    revision_strategy: str = "candidate_review",
) -> SkillArtifact:
    """Create and bind one existing V0.8 workflow for a composite stage."""

    state, skill_id = _plan_stage_workflow(
        request_text,
        job_id=job_id,
        stage_kind=stage_kind,
        profile_id=profile_id,
        reference_path=reference_path,
        mode=mode,
        reference_content_scope=reference_content_scope,
        target_subject=target_subject,
        revision_strategy=revision_strategy,
    )
    return _publish_stage_binding(
        root,
        run_root,
        run_id=run_id,
        job_id=job_id,
        ordinal=ordinal,
        stage_kind=stage_kind,
        skill_id=skill_id,
        workflow_id=state.workflow_id,
        reason=reason,
    )


def _state_artifact(root: Path, run_root: Path) -> SkillArtifact:
    """Bind the current mutable adapter state after its latest atomic write."""

    return _artifact_for(root, run_root / "state.json")


def _write_skill_latest_pointer(
    run_root: Path,
    *,
    job_id: str,
    run_id: str,
    entry_skill_id: str,
    status: str,
    updated_at: datetime,
) -> None:
    """Refresh the derived latest-run pointer without changing historical evidence."""

    write_json_atomic(
        run_root.parent / "latest.json",
        {
            "schema_version": "0.1.0",
            "job_id": job_id,
            "run_id": run_id,
            "entry_skill_id": entry_skill_id,
            "status": status,
            "updated_at": updated_at.isoformat(),
        },
    )


def _write_standard_state(run_root: Path, state: StandardCompositeRunState) -> None:
    """Atomically publish the current derived Standard adapter projection."""

    write_json_atomic(run_root / "state.json", state.model_dump(mode="json"))
    _write_skill_latest_pointer(
        run_root,
        job_id=state.job_id,
        run_id=state.run_id,
        entry_skill_id=_STANDARD_ENTRY,
        status=state.status,
        updated_at=state.updated_at,
    )


def _write_aq_state(run_root: Path, state: AQSkillAdapterState) -> None:
    """Atomically publish the current derived AQ adapter projection."""

    write_json_atomic(run_root / "state.json", state.model_dump(mode="json"))
    _write_skill_latest_pointer(
        run_root,
        job_id=state.job_id,
        run_id=state.run_id,
        entry_skill_id=_AQ_ENTRY,
        status=state.status,
        updated_at=state.updated_at,
    )


def _load_standard_run(
    job_id: str,
    run_id: str,
) -> tuple[Path, Path, StandardCompositeRunPlan, StandardCompositeRunState]:
    """Load and revalidate one Standard plan, state, bundle, and stage inventory."""

    root = job_dir(validate_job_id(job_id)).resolve(strict=True)
    load_job(job_id)
    run_root = _skill_run_root(root, run_id)
    bundle, _registry = _load_bundle(root, run_root)
    run_relative = run_root.relative_to(root).as_posix()
    plan_path = _contained_file(root, f"{run_relative}/plan.json")
    state_path = _contained_file(root, f"{run_relative}/state.json")
    plan = StandardCompositeRunPlan.model_validate_json(
        plan_path.read_text(encoding="utf-8")
    )
    state = StandardCompositeRunState.model_validate_json(
        state_path.read_text(encoding="utf-8")
    )
    if plan.job_id != job_id or plan.run_id != run_id:
        raise ValueError("Standard skill plan identity differs from its path")
    if plan.bundle_manifest != _artifact_for(root, run_root / "bundle.json"):
        raise ValueError("Standard skill plan no longer binds its exact bundle")
    if bundle.entry_skill_id != _STANDARD_ENTRY or bundle.execution_mode != "standard":
        raise ValueError("Standard skill run has the wrong entry bundle")
    if state.job_id != job_id or state.run_id != run_id:
        raise ValueError("Standard skill state identity differs from its path")
    if state.qa_revision_iterations > plan.max_qa_revision_iterations:
        raise ValueError("Standard skill state exceeds its QA revision budget")
    if state.plan != _artifact_for(root, plan_path):
        raise ValueError("Standard skill state no longer binds its exact plan")
    if state.stage_bindings[0] != plan.initial_stage_binding:
        raise ValueError("Standard skill state lost its initial child binding")
    for artifact in state.stage_bindings:
        binding = _load_model(root, artifact, StandardCompositeStageBinding)
        if binding.run_id != run_id or binding.job_id != job_id:
            raise ValueError("Standard child binding identity mismatch")
        _validate_artifact(root, binding.workflow_plan)
    if state.current_stage_binding is not None:
        _validate_artifact(root, state.current_stage_binding)
    if state.material_impact_report is not None:
        _validate_artifact(root, state.material_impact_report)
    for iteration, artifact in enumerate(state.qa_revision_evidence, start=1):
        continuation = _load_model(root, artifact, GuardedRevisionContinuation)
        if (
            continuation.job_id != job_id
            or continuation.run_id != run_id
            or continuation.iteration != iteration
        ):
            raise ValueError("guarded revision continuation identity is noncontiguous")
        for bound in (
            continuation.source_visual_qa_report,
            continuation.candidates,
            continuation.revision_plan,
            continuation.consumed_user_approval,
            continuation.application_report,
        ):
            _validate_artifact(root, bound)
        if continuation.convergence_report is not None:
            _validate_artifact(root, continuation.convergence_report)
    return root, run_root, plan, state


def _current_binding(
    root: Path,
    state: StandardCompositeRunState,
) -> StandardCompositeStageBinding:
    """Load the exact current Standard child binding or reject a terminal projection."""

    if state.current_stage_binding is None:
        raise RuntimeError("Standard skill run has no current child workflow")
    return _load_model(root, state.current_stage_binding, StandardCompositeStageBinding)


def plan_standard_asset_cycle(
    request_text: str,
    *,
    goal: str,
    job_id: str,
    reference_path: str | Path | None = None,
    stage_policy: str = "smart",
    max_qa_revision_iterations: int = 1,
    profile_id: str = "portable_gltf",
    mode: str = "concept",
    reference_content_scope: str | None = None,
    target_subject: str | None = None,
    revision_strategy: str = "candidate_review",
    run_id: str | None = None,
) -> dict[str, object]:
    """Plan one Standard composite cycle and snapshot its exact skill bundle."""

    normalized_request = request_text.strip()
    if not normalized_request:
        raise ValueError("Standard asset cycle request must not be empty")
    if goal not in {
        "new_asset_to_qa",
        "polish_existing_to_qa",
        "material_refresh_to_qa",
        "qa_repair_cycle",
        "full_cycle_to_package",
    }:
        raise ValueError("unsupported Standard asset-cycle goal")
    if stage_policy not in {"smart", "force_all"}:
        raise ValueError("stage_policy must be smart or force_all")
    selected_run_id = _validate_run_id(run_id or _new_run_id("standard-skill"))
    candidate_root = job_dir(job_id)
    existing = (candidate_root / "job.json").is_file()
    if goal == "new_asset_to_qa" and existing:
        raise FileExistsError("new_asset_to_qa requires an unused job ID")
    if goal in {"polish_existing_to_qa", "material_refresh_to_qa", "qa_repair_cycle"}:
        if not existing:
            raise FileNotFoundError("selected Standard goal requires an existing job")
    if not existing and goal == "full_cycle_to_package" and reference_path is None:
        raise ValueError("a new full_cycle_to_package run requires reference_path")
    if not existing and reference_path is None:
        raise ValueError("a new Standard asset cycle requires reference_path")

    before_snapshot: MaterialImpactSnapshot | None = None
    if existing:
        root_before = candidate_root.resolve(strict=True)
        reserved_path = root_before / "skill_runs" / selected_run_id
        if os.path.lexists(native_io_path(reserved_path)):
            raise FileExistsError(reserved_path)

    geometry_goals = {
        "new_asset_to_qa",
        "polish_existing_to_qa",
        "full_cycle_to_package",
    }
    if not existing or goal in geometry_goals:
        initial_stage = "geometry"
    elif goal == "material_refresh_to_qa":
        initial_stage = "material"
    else:
        initial_stage = "qa"
    try:
        if existing:
            root = candidate_root.resolve(strict=True)
            initial_workflow, skill_id = _plan_stage_workflow(
                normalized_request,
                job_id=job_id,
                stage_kind=initial_stage,
                profile_id=profile_id,
                revision_strategy=revision_strategy,
            )
            run_root = _skill_run_root(root, selected_run_id, create=True)
            before_snapshot = _capture_material_snapshot(root, run_root, "before")
            initial_binding = _publish_stage_binding(
                root,
                run_root,
                run_id=selected_run_id,
                job_id=job_id,
                ordinal=1,
                stage_kind=initial_stage,
                skill_id=skill_id,
                workflow_id=initial_workflow.workflow_id,
                reason=f"Initial {goal} stage selected by explicit Standard goal.",
            )
        else:
            provisional = plan_workflow(
                normalized_request,
                job_id=job_id,
                reference_path=reference_path,
                intent="new_asset",
                scope="full",
                delivery_scope="preview_only",
                mode=mode,
                reference_content_scope=reference_content_scope,
                target_subject=target_subject,
                profile_id=profile_id,
            )
            root = job_dir(job_id).resolve(strict=True)
            run_root = _skill_run_root(root, selected_run_id, create=True)
            before_snapshot = _capture_material_snapshot(root, run_root, "before")
            initial_binding = _publish_stage_binding(
                root,
                run_root,
                run_id=selected_run_id,
                job_id=job_id,
                ordinal=1,
                stage_kind="geometry",
                skill_id="reference-to-scene",
                workflow_id=provisional.workflow_id,
                reason="New asset uses the existing full Standard preview workflow through QA.",
            )
        if before_snapshot is None:
            raise RuntimeError("Standard planning did not capture its initial material boundary")
        bundle_artifact = _snapshot_skill_bundle(
            root,
            run_root,
            run_id=selected_run_id,
            job_id=job_id,
            entry_skill_id=_STANDARD_ENTRY,
            execution_mode="standard",
        )
        plan = StandardCompositeRunPlan(
            plan_id=f"plan-{selected_run_id}",
            run_id=selected_run_id,
            job_id=job_id,
            request_text=normalized_request,
            goal=goal,  # type: ignore[arg-type]
            stage_policy=stage_policy,  # type: ignore[arg-type]
            max_qa_revision_iterations=max_qa_revision_iterations,
            profile_id=profile_id,  # type: ignore[arg-type]
            bundle_manifest=bundle_artifact,
            initial_material_snapshot=before_snapshot,
            initial_stage_binding=initial_binding,
            created_at=_utc_now(),
        )
        plan_artifact = _publish_model(root, run_root / "plan.json", plan)
        state = StandardCompositeRunState(
            run_id=selected_run_id,
            job_id=job_id,
            plan=plan_artifact,
            status="planned",
            current_stage_binding=initial_binding,
            stage_bindings=[initial_binding],
            next_action="Resume the current V0.8 child workflow.",
            updated_at=_utc_now(),
        )
        _write_standard_state(run_root, state)
        return get_standard_asset_cycle_status(job_id, selected_run_id)
    except Exception:
        # Preserve a successfully created V0.8 job/workflow as visible evidence. Remove nothing.
        raise


def _snapshot_underlying_state(
    root: Path,
    run_root: Path,
    *,
    sequence: int,
    label: str,
    source_artifact: SkillArtifact,
) -> SkillArtifact:
    """Copy one mutable underlying state into immutable receipt-owned evidence."""

    source = _validate_artifact(root, source_artifact)
    target = run_root / "underlying" / f"{sequence:04d}-{label}.json"
    publish_bytes_create_once(target, source.read_bytes())
    return _artifact_for(root, target)


def _workflow_state_source(root: Path, workflow_id: str) -> SkillArtifact:
    """Bind the currently persisted V0.8 state file before snapshotting it."""

    return _artifact_for(root, root / "workflows" / workflow_id / "state.json")


def _receipt_sequence(run_root: Path) -> int:
    """Select the next append-only skill receipt sequence number."""

    receipt_root = run_root / "receipts"
    existing = sorted(receipt_root.glob("*.json")) if receipt_root.is_dir() else []
    return len(existing) + 1


def _route_from_registry(
    bundle: SkillBundleManifest,
    registry: SkillRegistry,
    *,
    execution_mode: str,
    route_key: str,
) -> str:
    """Resolve one unique snapshotted route and enforce bundle containment."""

    matches = [
        item.skill_id
        for item in registry.skills
        if execution_mode in item.execution_modes and route_key in item.route_keys
    ]
    if len(matches) != 1:
        raise ValueError(f"skill route is not unique: {execution_mode}:{route_key}")
    selected = matches[0]
    if selected not in bundle.skill_ids:
        raise PermissionError(f"selected skill is outside the invocation bundle: {selected}")
    return selected


def _standard_route(
    root: Path,
    binding: StandardCompositeStageBinding,
    workflow_state: WorkflowState,
) -> tuple[str, str, str]:
    """Map one exact V0.8 current step to the matching Standard leaf skill."""

    workflow_plan = _load_model(root, binding.workflow_plan, WorkflowPlan)
    step = None
    if workflow_state.current_step_id is not None:
        step = next(
            item
            for item in workflow_plan.steps
            if item.step_id == workflow_state.current_step_id
        )
    if step is None:
        fallback = {
            "geometry": ("standard.geometry.author", "completed geometry stage"),
            "material": ("standard.material.plan", "completed material stage"),
            "qa": ("standard.qa", "completed QA stage"),
            "portable": ("standard.portable", "completed portable stage"),
        }[binding.stage_kind]
        return fallback[0], "", fallback[1]
    if step.phase == "job":
        return "standard.proxy", "", f"V0.8 current step is {step.step_id}."
    if step.phase == "analysis":
        if step.execution_mode == "agent":
            return (
                "standard.geometry.author",
                "",
                f"V0.8 current step is {step.step_id}.",
            )
        return "standard.reference", "", f"V0.8 current step is {step.step_id}."
    if step.phase == "geometry":
        if step.step_id.startswith("revision.") or "candidate" in step.step_id:
            return "standard.qa.revision", "", f"V0.8 current step is {step.step_id}."
        if step.execution_mode == "agent":
            return "standard.geometry.author", "", f"V0.8 current step is {step.step_id}."
        return "standard.geometry.build", "", f"V0.8 current step is {step.step_id}."
    if step.phase == "material":
        return "standard.material.plan", "", f"V0.8 current step is {step.step_id}."
    if step.phase == "qa":
        return "standard.qa", "", f"V0.8 current step is {step.step_id}."
    if step.phase == "portable":
        return "standard.portable", "", f"V0.8 current step is {step.step_id}."
    return "standard.qa", "", f"V0.8 destination/manual boundary is {step.step_id}."


def _publish_route_decision(
    root: Path,
    run_root: Path,
    *,
    run_id: str,
    job_id: str,
    sequence: int,
    execution_mode: str,
    route_key: str,
    selected_skill: str,
    source_state: SkillArtifact,
    reason: str,
) -> SkillArtifact:
    """Publish one immutable skill selection before invoking the underlying engine."""

    decision = SkillRouteDecision(
        decision_id=f"route-{run_id}-{sequence:04d}",
        run_id=run_id,
        job_id=job_id,
        execution_mode=execution_mode,  # type: ignore[arg-type]
        stage_key=route_key,
        selected_skill_id=selected_skill,
        bundle_manifest=_artifact_for(root, run_root / "bundle.json"),
        source_state=source_state,
        reason=reason,
        decided_at=_utc_now(),
    )
    return _publish_model(root, run_root / "routes" / f"{sequence:04d}.json", decision)


def _previous_receipt_sha(run_root: Path, sequence: int) -> str | None:
    """Return the exact prior receipt hash for an append-only trace event."""

    if sequence == 1:
        return None
    path = run_root / "receipts" / f"{sequence - 1:04d}.json"
    if not path.is_file():
        raise ValueError("skill receipt chain has a missing predecessor")
    return sha256_file(path)


def _publish_execution_receipt(
    root: Path,
    run_root: Path,
    *,
    run_id: str,
    job_id: str,
    sequence: int,
    route: SkillArtifact,
    before: UnderlyingExecutionBinding,
    after: UnderlyingExecutionBinding,
    outcome: str,
) -> SkillArtifact:
    """Append one exact before/after projection without granting execution authority."""

    receipt = SkillExecutionReceipt(
        receipt_id=f"receipt-{run_id}-{sequence:04d}",
        run_id=run_id,
        job_id=job_id,
        sequence=sequence,
        route_decision=route,
        before=before,
        after=after,
        outcome=outcome,  # type: ignore[arg-type]
        previous_receipt_sha256=_previous_receipt_sha(run_root, sequence),
        recorded_at=_utc_now(),
    )
    return _publish_model(root, run_root / "receipts" / f"{sequence:04d}.json", receipt)


def _workflow_binding(
    binding: StandardCompositeStageBinding,
    state_artifact: SkillArtifact,
    state: WorkflowState,
) -> UnderlyingExecutionBinding:
    """Project one V0.8 child state into a skill execution binding."""

    return UnderlyingExecutionBinding(
        execution_kind="workflow_v08",
        execution_id=binding.workflow_id,
        state=state_artifact,
        status=state.status,
        next_action=state.next_action,
    )


def _standard_outcome(state: WorkflowState) -> str:
    """Classify one V0.8 state using the SkillExecutionReceipt outcome vocabulary."""

    return {
        "waiting_for_agent": "waiting_for_agent",
        "waiting_for_approval": "waiting_for_approval",
        "completed": "completed",
        "blocked": "blocked",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(state.status, "advanced")


def _adapter_status_from_workflow(state: WorkflowState) -> str:
    """Project a V0.8 status without changing its original meaning."""

    return {
        "planned": "planned",
        "running": "running",
        "waiting_for_agent": "waiting_for_agent",
        "waiting_for_approval": "waiting_for_approval",
        "blocked": "blocked",
        "completed": "running",
        "failed": "failed",
        "cancelled": "cancelled",
    }[state.status]


def _append_child_to_state(
    state: StandardCompositeRunState,
    binding: SkillArtifact,
) -> StandardCompositeRunState:
    """Advance the derived composite projection to one newly planned child workflow."""

    return state.model_copy(
        update={
            "status": "running",
            "current_stage_binding": binding,
            "stage_bindings": [*state.stage_bindings, binding],
            "next_action": "Resume the newly planned V0.8 child workflow.",
            "updated_at": _utc_now(),
        }
    )


def _publish_standard_terminal(
    root: Path,
    run_root: Path,
    plan: StandardCompositeRunPlan,
    state: StandardCompositeRunState,
    binding: StandardCompositeStageBinding,
    workflow_state: WorkflowState,
    *,
    terminal_type: str,
    reason: str,
) -> StandardCompositeRunState:
    """Freeze the final child and adapter state before publishing a safe terminal."""

    terminal_state = state.model_copy(
        update={
            "status": terminal_type,
            "current_stage_binding": None,
            "next_action": None,
            "updated_at": _utc_now(),
        }
    )
    _write_standard_state(run_root, terminal_state)
    final_source = _workflow_state_source(root, binding.workflow_id)
    final_underlying = _snapshot_underlying_state(
        root,
        run_root,
        sequence=max(1, _receipt_sequence(run_root)),
        label="terminal",
        source_artifact=final_source,
    )
    terminal = StandardCompositeRunTerminal(
        terminal_id=f"terminal-{plan.run_id}",
        run_id=plan.run_id,
        job_id=plan.job_id,
        plan=_artifact_for(root, run_root / "plan.json"),
        final_state=_state_artifact(root, run_root),
        terminal_type=terminal_type,  # type: ignore[arg-type]
        final_workflow=_workflow_binding(binding, final_underlying, workflow_state),
        stage_bindings=terminal_state.stage_bindings,
        reason=reason,
        created_at=_utc_now(),
    )
    _publish_model(root, run_root / "terminal.json", terminal)
    return terminal_state


def _qa_run_id_from_workflow_plan(workflow_plan: WorkflowPlan) -> str:
    """Read the exact immutable V0.6 run ID from one QA child workflow plan."""

    matches = [item for item in workflow_plan.steps if item.step_id == "qa.run"]
    if len(matches) != 1:
        raise ValueError("QA child workflow must contain one canonical qa.run step")
    run_id = matches[0].parameters.get("run_id")
    if not isinstance(run_id, str):
        raise ValueError("QA child workflow omitted its immutable V0.6 run ID")
    return _validate_run_id(run_id)


def _publish_guarded_revision_continuation(
    root: Path,
    run_root: Path,
    plan: StandardCompositeRunPlan,
    state: StandardCompositeRunState,
    *,
    current_scene_spec_sha256: str,
) -> SkillArtifact:
    """Validate and bind one consumed V0.6 approval before scheduling fresh QA."""

    source_run_id = state.qa_revision_source_run_id
    baseline_sha256 = state.qa_baseline_scene_spec_sha256
    if source_run_id is None or baseline_sha256 is None:
        raise ValueError("Standard QA revision boundary lacks its exact source run")
    qa_root = f"qa/runs/{source_run_id}"
    source_report_path = _contained_file(root, f"{qa_root}/visual_qa_report.json")
    candidates_path = _contained_file(root, f"{qa_root}/revision_candidates.json")
    revision_plan_path = _contained_file(root, f"{qa_root}/revision_plan.json")
    approval_path = _contained_file(root, f"{qa_root}/revision_approval.json")
    application_path = _contained_file(root, f"{qa_root}/application_report.json")
    candidates = RevisionCandidates.model_validate_json(
        candidates_path.read_text(encoding="utf-8")
    )
    revision_plan = RevisionPlan.model_validate_json(
        revision_plan_path.read_text(encoding="utf-8")
    )
    approval = RevisionApproval.model_validate_json(
        approval_path.read_text(encoding="utf-8")
    )
    application = json.loads(application_path.read_text(encoding="utf-8"))
    if not isinstance(application, dict):
        raise ValueError("guarded revision application report must be a JSON object")
    if (
        candidates.job_id != plan.job_id
        or revision_plan.job_id != plan.job_id
        or approval.job_id != plan.job_id
    ):
        raise ValueError("guarded revision evidence belongs to another job")
    if (
        candidates.base_spec_sha256 != baseline_sha256
        or revision_plan.base_spec_sha256 != baseline_sha256
        or approval.base_spec_sha256 != baseline_sha256
    ):
        raise ValueError("guarded revision evidence differs from the waiting baseline")
    if sha256_file(source_report_path) != candidates.source_report_sha256:
        raise ValueError("guarded revision source QA report hash is stale")
    if (
        approval.candidates_sha256 != sha256_file(candidates_path)
        or approval.plan_sha256 != sha256_file(revision_plan_path)
        or not approval.used
        or approval.used_at is None
    ):
        raise ValueError("guarded revision approval is stale or unconsumed")
    application_status = application.get("status")
    if application_status not in {"accepted", "applied_unverified"}:
        raise ValueError("guarded revision was not applied at an accepted continuation boundary")
    if (
        application.get("job_id") != plan.job_id
        or application.get("run_id") != source_run_id
        or application.get("approval_id") != approval.approval_id
        or application.get("approved_candidate_ids") != approval.approved_candidate_ids
        or application.get("base_spec_sha256") != baseline_sha256
        or application.get("result_spec_sha256") != current_scene_spec_sha256
        or application.get("approval_used") is not True
        or not isinstance(application.get("completed_at"), str)
    ):
        raise ValueError("guarded revision application report is incomplete or mismatched")
    convergence_artifact: SkillArtifact | None = None
    if application_status == "accepted":
        convergence_path = _contained_file(root, f"{qa_root}/convergence.json")
        convergence = ConvergenceReport.model_validate_json(
            convergence_path.read_text(encoding="utf-8")
        )
        if (
            convergence.job_id != plan.job_id
            or convergence.before_report_sha256 != candidates.source_report_sha256
            or not convergence.accepted
            or convergence.status != "improved"
        ):
            raise ValueError("guarded revision convergence evidence is not accepted")
        convergence_artifact = _artifact_for(root, convergence_path)
    iteration = state.qa_revision_iterations + 1
    continuation = GuardedRevisionContinuation(
        continuation_id=f"guarded-revision-{plan.run_id}-{iteration:04d}",
        run_id=plan.run_id,
        job_id=plan.job_id,
        iteration=iteration,
        source_qa_run_id=source_run_id,
        baseline_scene_spec_sha256=baseline_sha256,
        result_scene_spec_sha256=current_scene_spec_sha256,
        source_visual_qa_report=_artifact_for(root, source_report_path),
        candidates=_artifact_for(root, candidates_path),
        revision_plan=_artifact_for(root, revision_plan_path),
        consumed_user_approval=_artifact_for(root, approval_path),
        application_report=_artifact_for(root, application_path),
        convergence_report=convergence_artifact,
        application_status=application_status,  # type: ignore[arg-type]
        validated_at=_utc_now(),
    )
    return _publish_model(
        root,
        run_root / "revisions" / f"{iteration:04d}.json",
        continuation,
    )


def _continue_after_completed_child(
    root: Path,
    run_root: Path,
    plan: StandardCompositeRunPlan,
    state: StandardCompositeRunState,
    binding: StandardCompositeStageBinding,
    workflow_state: WorkflowState,
) -> StandardCompositeRunState:
    """Plan the next required child or publish the Standard composite terminal."""

    workflow_plan = _load_model(root, binding.workflow_plan, WorkflowPlan)
    next_ordinal = len(state.stage_bindings) + 1
    if binding.stage_kind == "geometry" and workflow_plan.intent == "new_asset":
        if plan.goal == "full_cycle_to_package":
            child = _plan_child_workflow(
                root,
                run_root,
                run_id=plan.run_id,
                job_id=plan.job_id,
                ordinal=next_ordinal,
                request_text=plan.request_text,
                stage_kind="portable",
                profile_id=plan.profile_id,
                reason="New Standard preview reached QA; explicit full-cycle goal adds V0.7.",
            )
            return _append_child_to_state(state, child)
        return _publish_standard_terminal(
            root,
            run_root,
            plan,
            state,
            binding,
            workflow_state,
            terminal_type="completed",
            reason="Existing full Standard preview workflow completed through V0.6 QA.",
        )
    if binding.stage_kind == "geometry":
        after = _capture_material_snapshot(root, run_root, "after-geometry")
        impact_artifact = _publish_material_impact(root, run_root, plan, after)
        impact = _load_model(root, impact_artifact, MaterialImpactReport)
        state = state.model_copy(update={"material_impact_report": impact_artifact})
        stage_kind = "material" if impact.material_authoring_required else "qa"
        child = _plan_child_workflow(
            root,
            run_root,
            run_id=plan.run_id,
            job_id=plan.job_id,
            ordinal=next_ordinal,
            request_text=plan.request_text,
            stage_kind=stage_kind,
            profile_id=plan.profile_id,
            reason=(
                "MaterialImpactReport requires fresh V0.5 authoring."
                if stage_kind == "material"
                else "MaterialImpactReport permits V0.5 skip; fresh V0.6 remains mandatory."
            ),
        )
        return _append_child_to_state(state, child)
    if binding.stage_kind == "material":
        child = _plan_child_workflow(
            root,
            run_root,
            run_id=plan.run_id,
            job_id=plan.job_id,
            ordinal=next_ordinal,
            request_text=plan.request_text,
            stage_kind="qa",
            profile_id=plan.profile_id,
            reason="Canonical material evidence changed, so fresh V0.6 QA is mandatory.",
        )
        return _append_child_to_state(state, child)
    if binding.stage_kind == "qa" and plan.goal == "qa_repair_cycle":
        if state.qa_revision_iterations < plan.max_qa_revision_iterations:
            scene_path = root / "analysis" / "scene_spec.json"
            baseline = sha256_file(scene_path) if scene_path.is_file() else None
            if baseline is None:
                raise FileNotFoundError("QA repair cycle requires canonical SceneSpec")
            qa_run_id = _qa_run_id_from_workflow_plan(workflow_plan)
            return state.model_copy(
                update={
                    "status": "waiting_for_external_revision",
                    "qa_revision_source_run_id": qa_run_id,
                    "qa_baseline_scene_spec_sha256": baseline,
                    "next_action": (
                        "Use this exact V0.6 run's hash-bound guarded revision approval/apply "
                        "path, then resume the same skill run to validate it and rerun QA."
                    ),
                    "updated_at": _utc_now(),
                }
            )
    if binding.stage_kind == "qa" and plan.goal == "full_cycle_to_package":
        child = _plan_child_workflow(
            root,
            run_root,
            run_id=plan.run_id,
            job_id=plan.job_id,
            ordinal=next_ordinal,
            request_text=plan.request_text,
            stage_kind="portable",
            profile_id=plan.profile_id,
            reason="Fresh V0.6 QA completed; explicit full-cycle goal adds V0.7.",
        )
        return _append_child_to_state(state, child)
    return _publish_standard_terminal(
        root,
        run_root,
        plan,
        state,
        binding,
        workflow_state,
        terminal_type="completed",
        reason=f"Standard composite reached its declared {plan.goal} boundary.",
    )


def _resume_external_revision_boundary(
    root: Path,
    run_root: Path,
    plan: StandardCompositeRunPlan,
    state: StandardCompositeRunState,
) -> StandardCompositeRunState:
    """Detect an externally approved canonical revision before scheduling fresh QA."""

    scene_path = root / "analysis" / "scene_spec.json"
    current = sha256_file(scene_path) if scene_path.is_file() else None
    if current is None or current == state.qa_baseline_scene_spec_sha256:
        return state
    iterations = state.qa_revision_iterations + 1
    if iterations > plan.max_qa_revision_iterations:
        raise RuntimeError("QA revision iteration budget was exceeded")
    evidence = _publish_guarded_revision_continuation(
        root,
        run_root,
        plan,
        state,
        current_scene_spec_sha256=current,
    )
    child = _plan_child_workflow(
        root,
        run_root,
        run_id=plan.run_id,
        job_id=plan.job_id,
        ordinal=len(state.stage_bindings) + 1,
        request_text=plan.request_text,
        stage_kind="qa",
        profile_id=plan.profile_id,
        reason="Exact external guarded revision changed SceneSpec; rerun fixed-camera V0.6 QA.",
    )
    return _append_child_to_state(
        state.model_copy(
            update={
                "qa_revision_iterations": iterations,
                "qa_revision_source_run_id": None,
                "qa_baseline_scene_spec_sha256": None,
                "qa_revision_evidence": [*state.qa_revision_evidence, evidence],
            }
        ),
        child,
    )


def run_standard_asset_cycle(
    job_id: str,
    run_id: str,
    *,
    max_host_steps: int = 8,
    max_stage_transitions: int = 4,
    retry_failed: bool = False,
) -> dict[str, object]:
    """Advance bounded Standard child workflows until the next meaningful boundary."""

    if not 1 <= max_stage_transitions <= 8:
        raise ValueError("max_stage_transitions must be within [1, 8]")
    root, run_root, plan, state = _load_standard_run(job_id, run_id)
    with _skill_run_lock(run_root):
        root, run_root, plan, state = _load_standard_run(job_id, run_id)
        if (run_root / "terminal.json").is_file():
            return get_standard_asset_cycle_status(job_id, run_id)
        if state.status == "waiting_for_external_revision":
            resumed = _resume_external_revision_boundary(root, run_root, plan, state)
            if resumed == state:
                return get_standard_asset_cycle_status(job_id, run_id)
            state = resumed
            _write_standard_state(run_root, state)
        for transition_index in range(max_stage_transitions):
            binding = _current_binding(root, state)
            before_payload = get_workflow_status(job_id, binding.workflow_id)
            before_state = WorkflowState.model_validate(before_payload["state"])
            if before_state.status == "failed" and not retry_failed:
                state = state.model_copy(
                    update={
                        "status": "failed",
                        "next_action": (
                            "Retry only this exact failed V0.8 step with retry_failed=true, "
                            "or cancel the composite run."
                        ),
                        "updated_at": _utc_now(),
                    }
                )
                _write_standard_state(run_root, state)
                break
            sequence = _receipt_sequence(run_root)
            before_snapshot = _snapshot_underlying_state(
                root,
                run_root,
                sequence=sequence,
                label="before",
                source_artifact=_workflow_state_source(root, binding.workflow_id),
            )
            bundle, registry = _load_bundle(root, run_root)
            route_key, _placeholder, route_reason = _standard_route(
                root, binding, before_state
            )
            selected_skill = _route_from_registry(
                bundle,
                registry,
                execution_mode="standard",
                route_key=route_key,
            )
            route = _publish_route_decision(
                root,
                run_root,
                run_id=run_id,
                job_id=job_id,
                sequence=sequence,
                execution_mode="standard",
                route_key=route_key,
                selected_skill=selected_skill,
                source_state=before_snapshot,
                reason=route_reason,
            )
            after_state = resume_workflow(
                job_id,
                binding.workflow_id,
                max_host_steps=max_host_steps,
                retry_failed=retry_failed and transition_index == 0,
            )
            after_snapshot = _snapshot_underlying_state(
                root,
                run_root,
                sequence=sequence,
                label="after",
                source_artifact=_workflow_state_source(root, binding.workflow_id),
            )
            receipt = _publish_execution_receipt(
                root,
                run_root,
                run_id=run_id,
                job_id=job_id,
                sequence=sequence,
                route=route,
                before=_workflow_binding(binding, before_snapshot, before_state),
                after=_workflow_binding(binding, after_snapshot, after_state),
                outcome=_standard_outcome(after_state),
            )
            state = state.model_copy(
                update={
                    "status": _adapter_status_from_workflow(after_state),
                    "next_action": after_state.next_action,
                    "receipt_chain_head_sha256": receipt.sha256,
                    "updated_at": _utc_now(),
                }
            )
            if after_state.status == "completed":
                state = _continue_after_completed_child(
                    root, run_root, plan, state, binding, after_state
                )
                _write_standard_state(run_root, state)
                if state.status in {
                    "completed",
                    "blocked",
                    "cancelled",
                    "waiting_for_external_revision",
                }:
                    break
                continue
            if after_state.status == "blocked":
                state = _publish_standard_terminal(
                    root,
                    run_root,
                    plan,
                    state,
                    binding,
                    after_state,
                    terminal_type="blocked",
                    reason=after_state.next_action or "V0.8 child workflow blocked.",
                )
            elif after_state.status == "cancelled":
                state = _publish_standard_terminal(
                    root,
                    run_root,
                    plan,
                    state,
                    binding,
                    after_state,
                    terminal_type="cancelled",
                    reason=after_state.cancelled_reason or "V0.8 child workflow cancelled.",
                )
            _write_standard_state(run_root, state)
            break
        return get_standard_asset_cycle_status(job_id, run_id)


def resume_standard_asset_cycle(
    job_id: str,
    run_id: str,
    *,
    max_host_steps: int = 8,
    max_stage_transitions: int = 4,
    retry_failed: bool = False,
) -> dict[str, object]:
    """Resume the same Standard plan, snapshots, children, and receipt chain."""

    return run_standard_asset_cycle(
        job_id,
        run_id,
        max_host_steps=max_host_steps,
        max_stage_transitions=max_stage_transitions,
        retry_failed=retry_failed,
    )


def cancel_standard_asset_cycle(
    job_id: str,
    run_id: str,
    *,
    reason: str,
) -> dict[str, object]:
    """Cancel future Standard work while preserving every child and trace artifact."""

    normalized = reason.strip()
    if not normalized:
        raise ValueError("Standard asset-cycle cancellation reason must not be empty")
    root, run_root, plan, state = _load_standard_run(job_id, run_id)
    with _skill_run_lock(run_root):
        root, run_root, plan, state = _load_standard_run(job_id, run_id)
        if (run_root / "terminal.json").is_file():
            raise RuntimeError("terminal Standard asset cycle cannot be cancelled again")
        binding = _current_binding(root, state)
        before_workflow = WorkflowState.model_validate(
            get_workflow_status(job_id, binding.workflow_id)["state"]
        )
        workflow = before_workflow
        sequence = _receipt_sequence(run_root)
        before_snapshot = _snapshot_underlying_state(
            root,
            run_root,
            sequence=sequence,
            label="before-cancel",
            source_artifact=_workflow_state_source(root, binding.workflow_id),
        )
        bundle, registry = _load_bundle(root, run_root)
        route_key, _placeholder, route_reason = _standard_route(
            root, binding, before_workflow
        )
        selected_skill = _route_from_registry(
            bundle,
            registry,
            execution_mode="standard",
            route_key=route_key,
        )
        route = _publish_route_decision(
            root,
            run_root,
            run_id=run_id,
            job_id=job_id,
            sequence=sequence,
            execution_mode="standard",
            route_key=route_key,
            selected_skill=selected_skill,
            source_state=before_snapshot,
            reason=f"{route_reason} The composite cancellation was explicitly requested.",
        )
        if workflow.status not in {"completed", "cancelled"}:
            workflow = cancel_workflow(
                job_id,
                binding.workflow_id,
                reason=f"Skill run {run_id}: {normalized}",
            )
        after_snapshot = _snapshot_underlying_state(
            root,
            run_root,
            sequence=sequence,
            label="after-cancel",
            source_artifact=_workflow_state_source(root, binding.workflow_id),
        )
        receipt = _publish_execution_receipt(
            root,
            run_root,
            run_id=run_id,
            job_id=job_id,
            sequence=sequence,
            route=route,
            before=_workflow_binding(binding, before_snapshot, before_workflow),
            after=_workflow_binding(binding, after_snapshot, workflow),
            outcome="cancelled",
        )
        state = state.model_copy(
            update={
                "receipt_chain_head_sha256": receipt.sha256,
                "updated_at": _utc_now(),
            }
        )
        state = _publish_standard_terminal(
            root,
            run_root,
            plan,
            state,
            binding,
            workflow,
            terminal_type="cancelled",
            reason=normalized,
        )
        _write_standard_state(run_root, state)
        return get_standard_asset_cycle_status(job_id, run_id)


def get_standard_asset_cycle_status(job_id: str, run_id: str) -> dict[str, object]:
    """Read and validate one Standard composite projection without advancing it."""

    root, run_root, plan, state = _load_standard_run(job_id, run_id)
    current = None
    current_route = None
    if state.current_stage_binding is not None:
        binding = _current_binding(root, state)
        current = get_workflow_status(job_id, binding.workflow_id)
        workflow_state = WorkflowState.model_validate(current["state"])
        route_key, _placeholder, route_reason = _standard_route(
            root, binding, workflow_state
        )
        bundle, registry = _load_bundle(root, run_root)
        current_route = {
            "stage_key": route_key,
            "skill_id": _route_from_registry(
                bundle,
                registry,
                execution_mode="standard",
                route_key=route_key,
            ),
            "workflow_id": binding.workflow_id,
            "source_state": _workflow_state_source(
                root, binding.workflow_id
            ).model_dump(mode="json"),
            "reason": route_reason,
            "canonical_write_authority": False,
            "approval_authority": False,
        }
    terminal = None
    terminal_path = run_root / "terminal.json"
    if terminal_path.is_file():
        terminal_model = StandardCompositeRunTerminal.model_validate_json(
            terminal_path.read_text(encoding="utf-8")
        )
        _validate_artifact(root, terminal_model.plan)
        _validate_artifact(root, terminal_model.final_state)
        _validate_artifact(root, terminal_model.final_workflow.state)
        terminal = terminal_model.model_dump(mode="json")
    return {
        "status": state.status,
        "job_id": job_id,
        "run_id": run_id,
        "entry_skill_id": _STANDARD_ENTRY,
        "plan": plan.model_dump(mode="json"),
        "state": state.model_dump(mode="json"),
        "current_workflow": current,
        "current_skill_route": current_route,
        "terminal": terminal,
        "canonical_write_authority": False,
        "approval_authority": False,
    }


def _aq_base_state(status: dict[str, object]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract the exact base AQ state and artifact from One-Prompt status."""

    base = status.get("base_autonomy")
    if not isinstance(base, dict):
        raise ValueError("One-Prompt status omitted base_autonomy")
    state = base.get("state")
    artifact = base.get("state_artifact")
    if not isinstance(state, dict) or not isinstance(artifact, dict):
        raise ValueError("One-Prompt status omitted exact AQ state evidence")
    return state, artifact


def _aq_source_artifact(root: Path, status: dict[str, object]) -> SkillArtifact:
    """Validate and adapt the current AQ state artifact into skill evidence."""

    _state, artifact = _aq_base_state(status)
    path_value = artifact.get("path")
    sha_value = artifact.get("sha256")
    if not isinstance(path_value, str) or not isinstance(sha_value, str):
        raise ValueError("AQ state artifact path/hash is malformed")
    selected = SkillArtifact(path=path_value, sha256=sha_value)
    _validate_artifact(root, selected)
    return selected


def _aq_controller_profile(root: Path, state: dict[str, Any]) -> tuple[str, bool]:
    """Infer geometry/material and closure only from exact current controller evidence."""

    provenance = state.get("provenance", [])
    if not isinstance(provenance, list):
        raise ValueError("AQ state provenance must be a list")
    for artifact in reversed(provenance):
        if not isinstance(artifact, dict):
            continue
        path_value = artifact.get("path")
        sha_value = artifact.get("sha256")
        if not isinstance(path_value, str) or not path_value.endswith("/result.json"):
            continue
        if not isinstance(sha_value, str):
            raise ValueError("AQ controller result omitted its hash")
        result_path = _validate_artifact(
            root, SkillArtifact(path=path_value, sha256=sha_value)
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        profile_ref = result.get("tool_profile") if isinstance(result, dict) else None
        if not isinstance(profile_ref, dict):
            raise ValueError("AQ controller result omitted its exact tool profile")
        profile_artifact = SkillArtifact(
            path=str(profile_ref.get("path", "")),
            sha256=str(profile_ref.get("sha256", "")),
        )
        profile_path = _validate_artifact(root, profile_artifact)
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile_id = str(profile.get("profile_id", ""))
        serialized = json.dumps(result, sort_keys=True).casefold()
        closure = "material_closure" in serialized or "material-closure" in serialized
        if profile_id == "material_authoring":
            return "material", closure
        if profile_id == "geometry_authoring":
            return "geometry", False
        raise ValueError("AQ current controller profile is neither geometry nor material")
    joined = " ".join(
        f"{item.get('kind', '')} {item.get('path', '')}".casefold()
        for item in provenance
        if isinstance(item, dict)
    )
    if "material" in joined or "geometry_candidate_validation" in joined:
        return "material", "material_closure" in joined
    return "geometry", False


def _aq_route_key(
    root: Path,
    status: dict[str, object],
) -> tuple[str, str]:
    """Map one exact One-Prompt/AQ state to a unique internal stage route."""

    state, _artifact = _aq_base_state(status)
    state_status = str(state.get("status", ""))
    next_action = str(state.get("next_action", ""))
    prompt_status = str(status.get("status", ""))
    if prompt_status == "genuine_escalation":
        return "aq.recovery.genuine_escalation", "One-Prompt has a genuine escalation."
    if state_status == "blocked":
        return "aq.recovery.blocked_terminal", "AQ reached a blocked terminal."
    if state_status == "failed":
        return "aq.recovery.failed_terminal", "AQ reached a failed terminal."
    if state_status == "cancelled":
        return "aq.recovery.cancelled_terminal", "AQ reached a cancelled terminal."
    if state_status == "review_required":
        return "aq.quality.review_terminal", "IQ produced a safe review terminal."
    if state_status in {"completed", "partial"} and next_action == "none":
        return "aq.delivery.completed_terminal", "AQ delivery reached a terminal."
    if next_action == "collect_reference":
        return "aq.reference.collect_reference", "AQ requests exact reference collection."
    if next_action in {"execute_controller", "validate_candidate"}:
        profile, closure = _aq_controller_profile(root, state)
        if profile == "material" and closure:
            return "aq.material.closure", "Current material controller evidence uses closure."
        return (
            f"aq.{profile}.{next_action}",
            f"Current AQ controller profile is {profile}_authoring.",
        )
    delivery_actions = {
        "freeze_quality_source",
        "plan_delivery",
        "await_v07_approval",
        "run_delivery",
        "publish_review",
        "terminalize",
    }
    if next_action == "run_integrated_quality":
        return "aq.quality.run_integrated_quality", "AQ requests Integrated Quality."
    if next_action in delivery_actions:
        return f"aq.delivery.{next_action}", f"AQ delivery action is {next_action}."
    return "aq.recovery.technical", f"AQ state requires bounded recovery: {next_action}."


def _aq_binding(
    session_id: str,
    state_artifact: SkillArtifact,
    status: dict[str, object],
) -> UnderlyingExecutionBinding:
    """Project one AQ One-Prompt status into a traceable underlying binding."""

    state, _artifact = _aq_base_state(status)
    return UnderlyingExecutionBinding(
        execution_kind="aq_one_prompt_v01",
        execution_id=session_id,
        state=state_artifact,
        status=str(status.get("status", state.get("status", "unknown"))),
        next_action=str(state.get("next_action")) if state.get("next_action") else None,
    )


def _aq_outcome(status: dict[str, object]) -> str:
    """Classify one One-Prompt result without inventing a new terminal meaning."""

    value = str(status.get("status", ""))
    state, _artifact = _aq_base_state(status)
    state_status = str(state.get("status", ""))
    if value == "terminal":
        return {
            "completed": "completed",
            "partial": "completed",
            "review_required": "completed",
            "blocked": "blocked",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(state_status, "completed")
    if value == "waiting_for_controller":
        return "waiting_for_controller"
    if value == "genuine_escalation":
        return "blocked"
    if value == "global_action_slice_exhausted":
        return "slice_exhausted"
    if value.startswith("waiting_for_integrated_quality"):
        return "waiting_for_controller"
    return "advanced"


def _load_aq_run(
    job_id: str,
    run_id: str,
) -> tuple[Path, Path, AQSkillAdapterPlan, AQSkillAdapterState]:
    """Load and revalidate one AQ adapter plan, state, bundle, and One-Prompt plan."""

    root = job_dir(validate_job_id(job_id)).resolve(strict=True)
    load_job(job_id)
    run_root = _skill_run_root(root, run_id)
    bundle, _registry = _load_bundle(root, run_root)
    if bundle.entry_skill_id != _AQ_ENTRY or bundle.execution_mode != "aq":
        raise ValueError("AQ skill run has the wrong entry bundle")
    run_relative = run_root.relative_to(root).as_posix()
    plan_path = _contained_file(root, f"{run_relative}/plan.json")
    state_path = _contained_file(root, f"{run_relative}/state.json")
    plan = AQSkillAdapterPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    state = AQSkillAdapterState.model_validate_json(state_path.read_text(encoding="utf-8"))
    if (plan.job_id, plan.run_id) != (job_id, run_id):
        raise ValueError("AQ skill plan identity differs from its path")
    if plan.bundle_manifest != _artifact_for(root, run_root / "bundle.json"):
        raise ValueError("AQ skill plan no longer binds its exact bundle")
    if (state.job_id, state.run_id, state.session_id) != (
        job_id,
        run_id,
        plan.session_id,
    ):
        raise ValueError("AQ skill state identity differs from its plan")
    if state.plan != _artifact_for(root, plan_path):
        raise ValueError("AQ skill state no longer binds its exact plan")
    _validate_artifact(root, plan.one_prompt_plan)
    _validate_artifact(root, state.source_state)
    return root, run_root, plan, state


def plan_aq_one_prompt_skill(
    request: str,
    *,
    reference_path: str | Path,
    target_subject: str,
    requested_delivery_profiles: list[str],
    approval_mode: str = "autonomous",
    explicit_autonomy_delegation_observed: bool,
    allowed_provider_scopes: list[str] | None = None,
    job_id: str | None = None,
    controller_execution_mode: str = "desktop_in_session",
    destination_hint: str = "engine_neutral",
    experimental_opt_in: bool = False,
    run_id: str | None = None,
) -> dict[str, object]:
    """Plan an AQ One-Prompt session and bind the experimental AQ skill bundle."""

    if not experimental_opt_in:
        raise PermissionError("AQ skill adapter remains disabled_experimental")
    base = plan_one_prompt_run(
        request,
        reference_path=reference_path,
        target_subject=target_subject,
        requested_delivery_profiles=requested_delivery_profiles,
        approval_mode=approval_mode,  # type: ignore[arg-type]
        explicit_autonomy_delegation_observed=explicit_autonomy_delegation_observed,
        allowed_provider_scopes=allowed_provider_scopes,  # type: ignore[arg-type]
        job_id=job_id,
        controller_execution_mode=controller_execution_mode,
        destination_hint=destination_hint,
        allow_disabled_experimental=True,
    )
    created_job_id = str(base["job_id"])
    session_id = str(base["session_id"])
    selected_run_id = _validate_run_id(run_id or _new_run_id("aq-skill"))
    root = job_dir(created_job_id).resolve(strict=True)
    run_root = _skill_run_root(root, selected_run_id, create=True)
    bundle_artifact = _snapshot_skill_bundle(
        root,
        run_root,
        run_id=selected_run_id,
        job_id=created_job_id,
        entry_skill_id=_AQ_ENTRY,
        execution_mode="aq",
    )
    one_prompt_raw = base.get("one_prompt_plan_artifact")
    if not isinstance(one_prompt_raw, dict):
        raise ValueError("One-Prompt planner omitted its exact plan artifact")
    one_prompt_artifact = SkillArtifact(
        path=str(one_prompt_raw.get("path", "")),
        sha256=str(one_prompt_raw.get("sha256", "")),
    )
    _validate_artifact(root, one_prompt_artifact)
    plan = AQSkillAdapterPlan(
        plan_id=f"plan-{selected_run_id}",
        run_id=selected_run_id,
        job_id=created_job_id,
        session_id=session_id,
        bundle_manifest=bundle_artifact,
        one_prompt_plan=one_prompt_artifact,
        created_at=_utc_now(),
    )
    plan_artifact = _publish_model(root, run_root / "plan.json", plan)
    status = get_one_prompt_status(created_job_id, session_id)
    source = _aq_source_artifact(root, status)
    initial_snapshot = _snapshot_underlying_state(
        root,
        run_root,
        sequence=0,
        label="initial",
        source_artifact=source,
    )
    route_key, _reason = _aq_route_key(root, status)
    bundle, registry = _load_bundle(root, run_root)
    selected_skill = _route_from_registry(
        bundle, registry, execution_mode="aq", route_key=route_key
    )
    base_state, _base_artifact = _aq_base_state(status)
    adapter_state = AQSkillAdapterState(
        run_id=selected_run_id,
        job_id=created_job_id,
        session_id=session_id,
        plan=plan_artifact,
        status=str(status["status"]),
        current_stage_key=route_key,
        current_skill_id=selected_skill,
        source_state=initial_snapshot,
        next_action=str(base_state.get("next_action", "")) or None,
        updated_at=_utc_now(),
    )
    _write_aq_state(run_root, adapter_state)
    return get_aq_one_prompt_skill_status(created_job_id, selected_run_id)


def run_aq_one_prompt_skill(
    job_id: str,
    run_id: str,
    *,
    max_actions: int = 32,
    quality_submission: dict[str, object] | None = None,
    experimental_opt_in: bool = False,
) -> dict[str, object]:
    """Advance the exact AQ One-Prompt session and append one routed trace receipt."""

    if not experimental_opt_in:
        raise PermissionError("AQ skill adapter remains disabled_experimental")
    root, run_root, plan, adapter_state = _load_aq_run(job_id, run_id)
    with _skill_run_lock(run_root):
        root, run_root, plan, adapter_state = _load_aq_run(job_id, run_id)
        before_status = get_one_prompt_status(job_id, plan.session_id)
        if str(before_status.get("status")) == "terminal":
            return get_aq_one_prompt_skill_status(job_id, run_id)
        sequence = _receipt_sequence(run_root)
        before_snapshot = _snapshot_underlying_state(
            root,
            run_root,
            sequence=sequence,
            label="before",
            source_artifact=_aq_source_artifact(root, before_status),
        )
        route_key, route_reason = _aq_route_key(root, before_status)
        bundle, registry = _load_bundle(root, run_root)
        selected_skill = _route_from_registry(
            bundle, registry, execution_mode="aq", route_key=route_key
        )
        route = _publish_route_decision(
            root,
            run_root,
            run_id=run_id,
            job_id=job_id,
            sequence=sequence,
            execution_mode="aq",
            route_key=route_key,
            selected_skill=selected_skill,
            source_state=before_snapshot,
            reason=route_reason,
        )
        executor = (
            resume_one_prompt
            if adapter_state.receipt_chain_head_sha256 is not None
            else run_one_prompt
        )
        result = executor(
            job_id,
            plan.session_id,
            max_actions=max_actions,
            quality_submission=quality_submission,
            allow_disabled_experimental=True,
        )
        after_status = get_one_prompt_status(job_id, plan.session_id)
        after_snapshot = _snapshot_underlying_state(
            root,
            run_root,
            sequence=sequence,
            label="after",
            source_artifact=_aq_source_artifact(root, after_status),
        )
        receipt = _publish_execution_receipt(
            root,
            run_root,
            run_id=run_id,
            job_id=job_id,
            sequence=sequence,
            route=route,
            before=_aq_binding(plan.session_id, before_snapshot, before_status),
            after=_aq_binding(plan.session_id, after_snapshot, after_status),
            outcome=_aq_outcome(after_status),
        )
        after_key, _after_reason = _aq_route_key(root, after_status)
        after_skill = _route_from_registry(
            bundle, registry, execution_mode="aq", route_key=after_key
        )
        after_state, _after_artifact = _aq_base_state(after_status)
        adapter_state = adapter_state.model_copy(
            update={
                "status": str(after_status.get("status", "unknown")),
                "current_stage_key": after_key,
                "current_skill_id": after_skill,
                "source_state": after_snapshot,
                "next_action": str(after_state.get("next_action", "")) or None,
                "receipt_chain_head_sha256": receipt.sha256,
                "updated_at": _utc_now(),
            }
        )
        _write_aq_state(run_root, adapter_state)
        response = get_aq_one_prompt_skill_status(job_id, run_id)
        response["last_one_prompt_result"] = result
        return response


def resume_aq_one_prompt_skill(
    job_id: str,
    run_id: str,
    *,
    max_actions: int = 32,
    quality_submission: dict[str, object] | None = None,
    experimental_opt_in: bool = False,
) -> dict[str, object]:
    """Resume the same AQ plan, state, budget, assignment, snapshots, and receipts."""

    if not experimental_opt_in:
        raise PermissionError("AQ skill adapter remains disabled_experimental")
    _load_aq_run(job_id, run_id)
    return run_aq_one_prompt_skill(
        job_id,
        run_id,
        max_actions=max_actions,
        quality_submission=quality_submission,
        experimental_opt_in=True,
    )


def cancel_aq_one_prompt_skill(
    job_id: str,
    run_id: str,
    *,
    reason: str,
    experimental_opt_in: bool = False,
) -> dict[str, object]:
    """Cancel the exact underlying One-Prompt session and preserve adapter evidence."""

    if not experimental_opt_in:
        raise PermissionError("AQ skill adapter remains disabled_experimental")
    normalized = reason.strip()
    if not normalized:
        raise ValueError("AQ skill cancellation reason must not be empty")
    root, run_root, plan, adapter_state = _load_aq_run(job_id, run_id)
    with _skill_run_lock(run_root):
        root, run_root, plan, adapter_state = _load_aq_run(job_id, run_id)
        before_status = get_one_prompt_status(job_id, plan.session_id)
        if str(before_status.get("status")) == "terminal":
            raise RuntimeError("terminal AQ One-Prompt session cannot be cancelled again")
        sequence = _receipt_sequence(run_root)
        before_snapshot = _snapshot_underlying_state(
            root,
            run_root,
            sequence=sequence,
            label="before-cancel",
            source_artifact=_aq_source_artifact(root, before_status),
        )
        route_key, route_reason = _aq_route_key(root, before_status)
        bundle, registry = _load_bundle(root, run_root)
        selected_skill = _route_from_registry(
            bundle, registry, execution_mode="aq", route_key=route_key
        )
        route = _publish_route_decision(
            root,
            run_root,
            run_id=run_id,
            job_id=job_id,
            sequence=sequence,
            execution_mode="aq",
            route_key=route_key,
            selected_skill=selected_skill,
            source_state=before_snapshot,
            reason=f"{route_reason} The AQ cancellation was explicitly requested.",
        )
        cancel_one_prompt(
            job_id,
            plan.session_id,
            reason=normalized,
            allow_disabled_experimental=True,
        )
        after_status = get_one_prompt_status(job_id, plan.session_id)
        source = _aq_source_artifact(root, after_status)
        snapshot = _snapshot_underlying_state(
            root,
            run_root,
            sequence=sequence,
            label="after-cancel",
            source_artifact=source,
        )
        receipt = _publish_execution_receipt(
            root,
            run_root,
            run_id=run_id,
            job_id=job_id,
            sequence=sequence,
            route=route,
            before=_aq_binding(plan.session_id, before_snapshot, before_status),
            after=_aq_binding(plan.session_id, snapshot, after_status),
            outcome="cancelled",
        )
        route_key, _route_reason = _aq_route_key(root, after_status)
        selected_skill = _route_from_registry(
            bundle, registry, execution_mode="aq", route_key=route_key
        )
        base_state, _artifact = _aq_base_state(after_status)
        adapter_state = adapter_state.model_copy(
            update={
                "status": str(after_status.get("status", "terminal")),
                "current_stage_key": route_key,
                "current_skill_id": selected_skill,
                "source_state": snapshot,
                "next_action": str(base_state.get("next_action", "")) or None,
                "receipt_chain_head_sha256": receipt.sha256,
                "updated_at": _utc_now(),
            }
        )
        _write_aq_state(run_root, adapter_state)
        return get_aq_one_prompt_skill_status(job_id, run_id)


def get_aq_one_prompt_skill_status(job_id: str, run_id: str) -> dict[str, object]:
    """Read the AQ adapter and exact One-Prompt status without advancing either."""

    _root, _run_root, plan, state = _load_aq_run(job_id, run_id)
    return {
        "status": state.status,
        "profile_status": "disabled_experimental",
        "job_id": job_id,
        "run_id": run_id,
        "session_id": plan.session_id,
        "entry_skill_id": _AQ_ENTRY,
        "plan": plan.model_dump(mode="json"),
        "state": state.model_dump(mode="json"),
        "one_prompt": get_one_prompt_status(job_id, plan.session_id),
        "canonical_write_authority": False,
        "approval_authority": False,
        "repository_creates_codex_task": False,
        "app_close_background_execution": False,
    }


def get_skill_execution_trace(job_id: str, run_id: str) -> dict[str, object]:
    """Validate and return the immutable registry, bundle, routes, and receipt chain."""

    root = job_dir(validate_job_id(job_id)).resolve(strict=True)
    load_job(job_id)
    run_root = _skill_run_root(root, run_id)
    bundle, registry = _load_bundle(root, run_root)
    routes: list[dict[str, object]] = []
    route_root = run_root / "routes"
    if route_root.exists():
        _assert_no_link_segments(root, route_root)
        if not route_root.is_dir():
            raise ValueError("skill route root must be a regular directory")
    route_paths = sorted(route_root.glob("*.json")) if route_root.is_dir() else []
    bundle_artifact = _artifact_for(root, run_root / "bundle.json")
    for sequence, path in enumerate(route_paths, start=1):
        route_path = _contained_file(root, path.relative_to(root).as_posix())
        route = SkillRouteDecision.model_validate_json(
            route_path.read_text(encoding="utf-8")
        )
        if path.name != f"{sequence:04d}.json":
            raise ValueError("skill route sequence is noncontiguous")
        if (route.job_id, route.run_id, route.execution_mode) != (
            job_id,
            run_id,
            bundle.execution_mode,
        ):
            raise ValueError("skill route identity differs from its run bundle")
        if route.bundle_manifest != bundle_artifact:
            raise ValueError("skill route no longer binds its exact bundle")
        if route.selected_skill_id not in bundle.skill_ids:
            raise ValueError("skill route selected a skill outside its bundle")
        selected_skill = _route_from_registry(
            bundle,
            registry,
            execution_mode=route.execution_mode,
            route_key=route.stage_key,
        )
        if route.selected_skill_id != selected_skill:
            raise ValueError("skill route selection differs from its registry")
        _validate_artifact(root, route.bundle_manifest)
        _validate_artifact(root, route.source_state)
        routes.append(route.model_dump(mode="json"))
    receipts: list[dict[str, object]] = []
    previous_sha: str | None = None
    receipt_root = run_root / "receipts"
    if receipt_root.exists():
        _assert_no_link_segments(root, receipt_root)
        if not receipt_root.is_dir():
            raise ValueError("skill receipt root must be a regular directory")
    receipt_paths = sorted(receipt_root.glob("*.json")) if receipt_root.is_dir() else []
    if len(route_paths) != len(receipt_paths):
        raise ValueError("skill route and execution receipt counts differ")
    for sequence, path in enumerate(receipt_paths, start=1):
        receipt_path = _contained_file(root, path.relative_to(root).as_posix())
        receipt = SkillExecutionReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        if path.name != f"{sequence:04d}.json" or (
            receipt.sequence != sequence
            or receipt.previous_receipt_sha256 != previous_sha
        ):
            raise ValueError("skill execution receipt chain is noncontiguous")
        if (receipt.job_id, receipt.run_id) != (job_id, run_id):
            raise ValueError("skill execution receipt identity differs from its run")
        route_artifact = _artifact_for(root, route_paths[sequence - 1])
        if receipt.route_decision != route_artifact:
            raise ValueError("skill execution receipt no longer binds its exact route")
        route = SkillRouteDecision.model_validate(routes[sequence - 1])
        if receipt.before.state != route.source_state:
            raise ValueError("skill receipt before-state differs from its route source")
        if (
            receipt.before.execution_kind,
            receipt.before.execution_id,
        ) != (
            receipt.after.execution_kind,
            receipt.after.execution_id,
        ):
            raise ValueError("skill receipt changed its underlying execution identity")
        _validate_artifact(root, route_artifact)
        _validate_artifact(root, receipt.before.state)
        _validate_artifact(root, receipt.after.state)
        receipts.append(receipt.model_dump(mode="json"))
        previous_sha = sha256_file(receipt_path)
    if bundle.entry_skill_id == _STANDARD_ENTRY:
        _root, _run_root, _plan, state = _load_standard_run(job_id, run_id)
    elif bundle.entry_skill_id == _AQ_ENTRY:
        _root, _run_root, _plan, state = _load_aq_run(job_id, run_id)
    else:
        raise ValueError("skill trace has an unsupported entry skill")
    if state.receipt_chain_head_sha256 != previous_sha:
        raise ValueError("skill state receipt-chain head is stale or mismatched")
    return {
        "status": "valid",
        "job_id": job_id,
        "run_id": run_id,
        "registry": registry.model_dump(mode="json"),
        "bundle": bundle.model_dump(mode="json"),
        "routes": routes,
        "receipts": receipts,
        "receipt_chain_head_sha256": previous_sha,
        "canonical_write_authority": False,
        "approval_authority": False,
    }


__all__ = [
    "cancel_aq_one_prompt_skill",
    "cancel_standard_asset_cycle",
    "get_aq_one_prompt_skill_status",
    "get_skill_catalog",
    "get_skill_execution_trace",
    "get_standard_asset_cycle_status",
    "load_skill_registry",
    "plan_aq_one_prompt_skill",
    "plan_standard_asset_cycle",
    "resume_aq_one_prompt_skill",
    "resume_standard_asset_cycle",
    "run_aq_one_prompt_skill",
    "run_standard_asset_cycle",
]
