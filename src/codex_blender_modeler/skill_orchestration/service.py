"""Traceable Skill Orchestration 0.1 adapters over V0.8 and AQ One-Prompt."""

from __future__ import annotations

import json
import os
import re
import stat
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..auto_revision.candidate_review_models import (
    CandidateReviewApproval,
    CandidateReviewDecision,
    CandidateReviewPromotionReceipt,
)
from ..auto_revision.candidate_review_service import validate_candidate_review_decision
from ..auto_revision.models import (
    ConvergenceReport,
    RevisionApproval,
    RevisionCandidates,
)
from ..autonomy_v2 import (
    cancel_one_prompt,
    close_human_quality_review_v2,
    get_autonomy_v2_status,
    get_one_prompt_status,
    plan_one_prompt_run,
    resume_one_prompt,
    run_one_prompt,
)
from ..autonomy_v2.approval_models import AQV2OnePromptRunTerminal
from ..autonomy_v2.models import DeliveryTerminalV2, QualityApprovedSourceFreeze
from ..blender_artifacts import (
    deterministic_json_bytes,
    native_io_path,
    publish_bytes_create_once,
    stable_json_digest,
    write_json_atomic,
)
from ..config import get_settings
from ..orchestration import (
    cancel_workflow,
    get_workflow_status,
    plan_workflow,
    resume_workflow,
)
from ..orchestration.models import (
    WorkflowApproval,
    WorkflowPlan,
    WorkflowRequest,
    WorkflowState,
)
from ..packaging.models import PortablePackageAcceptance
from ..qa.models import VisualQAReport
from ..qa.multiview_sanity import GeometryMultiviewVisualReview
from ..revision import RevisionPlan
from ..workspace import job_dir, load_job, sha256_file, validate_job_id
from .models import (
    AQSkillAdapterPlan,
    AQSkillAdapterState,
    AQSkillAdapterTerminal,
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
    StandardManualGuardedRerouteBinding,
    StandardQualityDispositionRecord,
    StandardQualityDispositionRequest,
    StandardTechnicalRecoveryBinding,
    UnderlyingExecutionBinding,
)

_REGISTRY_PATH = Path(".agents/skills/registry.json")
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_STANDARD_ENTRY = "standard-asset-cycle"
_AQ_ENTRY = "aq-one-prompt-orchestrator"
_GEOMETRY_REENTRY_REASON_PREFIX = "Geometry visual review requires bounded V0.4 re-entry"
_QUALITY_REVISION_REASON_PREFIX = (
    "Human needs_revision disposition routes bounded V0.4 candidate review"
)
_QUALITY_REVISION_MANUAL_REASON_PREFIX = (
    "Human needs_revision disposition routes material-impact manual guarded V0.4"
)
_CANDIDATE_IMPROVEMENT_REASON = (
    "Direct-reference score improved beyond the configured threshold."
)
_SURFACE_DETAIL_BLOCKER_PREFIX = (
    "Candidate invalidates the authored V0.5 surface-detail contract: "
)


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
    *,
    stage_ordinal: int | None = None,
) -> SkillArtifact:
    """Publish one append-only material-impact decision for a geometry stage."""

    if stage_ordinal is not None and stage_ordinal < 1:
        raise ValueError("material-impact stage ordinal must be positive")

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
    suffix = "" if stage_ordinal in {None, 1} else f"-{stage_ordinal:04d}"
    report = MaterialImpactReport(
        report_id=f"material-impact-{plan.run_id}{suffix}",
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
    report_path = (
        run_root / "material_impact.json"
        if stage_ordinal in {None, 1}
        else run_root / "material_impacts" / f"{stage_ordinal:04d}.json"
    )
    return _publish_model(root, report_path, report)


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
    technical_recovery: StandardTechnicalRecoveryBinding | None = None,
    technical_reroute: StandardManualGuardedRerouteBinding | None = None,
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
        technical_recovery=technical_recovery,
        technical_reroute=technical_reroute,
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
    technical_recovery: StandardTechnicalRecoveryBinding | None = None,
    technical_reroute: StandardManualGuardedRerouteBinding | None = None,
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
        technical_recovery=technical_recovery,
        technical_reroute=technical_reroute,
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


def _validate_standard_technical_recovery(
    root: Path,
    run_root: Path,
    *,
    run_id: str,
    job_id: str,
    binding: StandardCompositeStageBinding,
    prior_bindings: list[SkillArtifact],
    expected_sequence: int,
) -> None:
    """Validate one exact failed-child link behind a guarded continuation."""

    recovery = binding.technical_recovery
    if recovery is None:
        raise ValueError("technical recovery validation requires recovery evidence")
    if recovery.recovery_sequence != expected_sequence:
        raise ValueError("Standard technical recovery sequence is noncontiguous")
    if not prior_bindings or recovery.failed_stage_binding != prior_bindings[-1]:
        raise ValueError("Standard technical recovery lost its direct failed predecessor")
    for artifact in (
        recovery.failed_stage_binding,
        recovery.failed_workflow_state,
        recovery.failed_execution_receipt,
        recovery.canonical_scene_spec_snapshot,
    ):
        _validate_artifact(root, artifact)
    failed_binding = _load_model(
        root,
        recovery.failed_stage_binding,
        StandardCompositeStageBinding,
    )
    failed_state = _load_model(
        root,
        recovery.failed_workflow_state,
        WorkflowState,
    )
    failed_receipt = _load_model(
        root,
        recovery.failed_execution_receipt,
        SkillExecutionReceipt,
    )
    expected_receipt_root = f"{run_root.relative_to(root).as_posix()}/receipts/"
    if not recovery.failed_execution_receipt.path.startswith(expected_receipt_root):
        raise ValueError("Standard technical recovery receipt is outside its skill run")
    if (
        failed_binding.run_id != run_id
        or failed_binding.job_id != job_id
        or failed_state.job_id != job_id
        or failed_state.workflow_id != failed_binding.workflow_id
    ):
        raise ValueError("Standard technical recovery predecessor identity mismatch")
    if (
        failed_receipt.run_id != run_id
        or failed_receipt.job_id != job_id
        or failed_receipt.outcome != "failed"
        or failed_receipt.after.execution_id != failed_binding.workflow_id
        or failed_receipt.after.status != "failed"
        or failed_receipt.after.state != recovery.failed_workflow_state
    ):
        raise ValueError("Standard technical recovery lacks an exact failed receipt")
    failed_step = next(
        (item for item in failed_state.steps if item.step_id == recovery.failed_step_id),
        None,
    )
    if (
        failed_state.status != "failed"
        or failed_state.current_step_id != recovery.failed_step_id
        or failed_step is None
        or failed_step.status != "failed"
        or failed_step.reason_code != "host_failure"
        or failed_step.input_fingerprint != recovery.failed_input_fingerprint
    ):
        raise ValueError("Standard technical recovery source is not an exact host failure")
    continuation_plan = _load_model(root, binding.workflow_plan, WorkflowPlan)
    if continuation_plan.intent != "revise_asset":
        raise ValueError("Standard technical recovery must bind a revise_asset workflow")


def _workflow_request_for_plan(root: Path, plan: WorkflowPlan) -> WorkflowRequest:
    """Load one workflow request and verify the plan's exact request digest."""

    request_path = _contained_file(root, f"workflows/{plan.workflow_id}/request.json")
    if sha256_file(request_path) != plan.request_sha256:
        raise ValueError("workflow request changed after plan publication")
    return WorkflowRequest.model_validate_json(request_path.read_text(encoding="utf-8"))


def _completed_geometry_visual_review(
    root: Path,
    workflow_plan: WorkflowPlan,
    workflow_state: WorkflowState,
) -> GeometryMultiviewVisualReview | None:
    """Load the final completed geometry review and verify its immutable run hashes."""

    review_steps = [
        item
        for item in workflow_plan.steps
        if item.tool_name == "review_geometry_multiview"
    ]
    if not review_steps:
        return None
    planned_step = review_steps[-1]
    step_state = next(
        (item for item in workflow_state.steps if item.step_id == planned_step.step_id),
        None,
    )
    if step_state is None or step_state.status != "complete":
        return None
    artifact = next(
        (
            item
            for item in step_state.artifacts
            if item.artifact_id.endswith(".geometry_multiview.visual_review")
        ),
        None,
    )
    if artifact is None or artifact.sha256 is None or artifact.integrity != "valid":
        raise ValueError("completed geometry review lacks one exact valid artifact")
    review_path = _contained_file(root, artifact.path)
    if sha256_file(review_path) != artifact.sha256:
        raise ValueError("completed geometry visual-review artifact hash changed")
    review = GeometryMultiviewVisualReview.model_validate_json(
        review_path.read_text(encoding="utf-8")
    )
    expected_run_id = str(planned_step.parameters.get("run_id", ""))
    expected_path = (
        root
        / "qa"
        / "assembly_sanity"
        / "runs"
        / review.run_id
        / "visual_review.json"
    ).resolve()
    if (
        review.job_id != workflow_state.job_id
        or not expected_run_id
        or review.run_id != expected_run_id
        or review_path != expected_path
    ):
        raise ValueError("completed geometry visual review identity differs from its workflow")
    run_relative = f"qa/assembly_sanity/runs/{review.run_id}"
    plan_path = _contained_file(root, f"{run_relative}/plan.json")
    manifest_path = _contained_file(root, f"{run_relative}/render_manifest.json")
    report_path = _contained_file(root, f"{run_relative}/report.json")
    if (
        review.plan_sha256 != sha256_file(plan_path)
        or review.render_manifest_sha256 != sha256_file(manifest_path)
        or review.structural_report_sha256 != sha256_file(report_path)
    ):
        raise ValueError("completed geometry visual review source hashes changed")
    return review


def _geometry_review_requires_reentry(
    review: GeometryMultiviewVisualReview | None,
) -> bool:
    """Return whether exact visual evidence requests recommended or required V0.4 work."""

    return review is not None and review.v04_reentry in {"recommended", "required"}


def _untouched_material_workflow(
    workflow_plan: WorkflowPlan,
    workflow_state: WorkflowState,
) -> bool:
    """Recognize one newly planned material child before any host, agent, or approval work."""

    return (
        workflow_plan.intent == "material_authoring"
        and workflow_state.status == "planned"
        and workflow_state.current_step_id == "geometry.prerequisite"
        and all(
            item.status in {"ready", "pending"}
            and item.attempt_count == 0
            and item.completion_fingerprint is None
            and item.approval_id is None
            and all(artifact.integrity == "missing" for artifact in item.artifacts)
            for item in workflow_state.steps
        )
    )


def _evaluated_material_refresh_candidate(
    root: Path,
    binding: StandardCompositeStageBinding,
    workflow_plan: WorkflowPlan,
    workflow_request: WorkflowRequest,
    workflow_state: WorkflowState,
    *,
    require_current_sources: bool,
) -> CandidateReviewDecision | None:
    """Validate a visually improved candidate blocked only by stale V0.5 bindings."""

    if not (
        binding.stage_kind == "geometry"
        and binding.skill_id == "guarded-visual-revision"
        and workflow_plan.intent == "revise_asset"
        and workflow_request.revision_strategy == "candidate_review"
        and workflow_state.status == "waiting_for_approval"
        and workflow_state.current_step_id == "revision.promotion_approval"
        and workflow_state.waiting_gate == "visual_revision"
    ):
        return None
    planned_steps = {item.step_id: item for item in workflow_plan.steps}
    state_steps = {item.step_id: item for item in workflow_state.steps}
    author_plan = planned_steps.get("revision.author")
    evaluation_plan = planned_steps.get("revision.evaluate")
    approval_plan = planned_steps.get("revision.promotion_approval")
    author_state = state_steps.get("revision.author")
    evaluation_state = state_steps.get("revision.evaluate")
    approval_state = state_steps.get("revision.promotion_approval")
    if any(
        item is None
        for item in (
            author_plan,
            evaluation_plan,
            approval_plan,
            author_state,
            evaluation_state,
            approval_state,
        )
    ):
        raise ValueError("evaluated candidate reroute lacks its exact workflow steps")
    trial_id = evaluation_plan.parameters.get("trial_id")
    revision_plan_path = evaluation_plan.parameters.get("revision_plan_path")
    if not isinstance(trial_id, str) or not isinstance(revision_plan_path, str):
        raise ValueError("evaluated candidate reroute lacks its exact trial or plan path")
    decision_relative = f"qa/candidate_reviews/{trial_id}/decision_manifest.json"
    approval_relative = f"qa/candidate_reviews/{trial_id}/promotion_approval.json"
    author_artifacts = [
        item
        for item in author_state.artifacts
        if item.artifact_id == "revision.candidate_plan"
    ]
    decision_artifacts = [
        item
        for item in evaluation_state.artifacts
        if item.artifact_id == "revision.candidate_decision"
    ]
    approval_artifacts = [
        item
        for item in approval_state.artifacts
        if item.artifact_id == "revision.candidate_approval"
    ]
    if (
        author_state.status != "complete"
        or author_state.completion_fingerprint is None
        or len(author_artifacts) != 1
        or author_artifacts[0].path != revision_plan_path
        or author_artifacts[0].sha256 is None
        or author_artifacts[0].integrity != "valid"
        or evaluation_state.status != "complete"
        or evaluation_state.attempt_count < 1
        or evaluation_state.input_fingerprint is None
        or evaluation_state.completion_fingerprint is None
        or len(decision_artifacts) != 1
        or decision_artifacts[0].path != decision_relative
        or decision_artifacts[0].sha256 is None
        or decision_artifacts[0].integrity != "valid"
        or any(
            item.integrity != "valid" or item.sha256 is None
            for item in evaluation_state.artifacts
        )
        or approval_state.status != "waiting_for_approval"
        or approval_state.input_fingerprint is None
        or approval_state.completion_fingerprint is not None
        or approval_state.approval_id is not None
        or approval_state.attempt_count != 0
        or len(approval_artifacts) != 1
        or approval_artifacts[0].path != approval_relative
        or approval_artifacts[0].sha256 is not None
        or approval_artifacts[0].integrity != "missing"
    ):
        raise ValueError("evaluated candidate reroute is not at an untouched promotion gate")
    approval_path = root / Path(approval_relative)
    if os.path.lexists(native_io_path(approval_path)):
        raise PermissionError("evaluated candidate reroute cannot consume a promotion approval")
    decision_path = _contained_file(root, decision_relative)
    if sha256_file(decision_path) != decision_artifacts[0].sha256:
        raise ValueError("evaluated candidate reroute decision hash changed")
    decision = validate_candidate_review_decision(
        root,
        decision_path,
        require_current_sources=require_current_sources,
    )
    if (
        decision.job_id != binding.job_id
        or decision.workflow_id != binding.workflow_id
        or decision.trial_id != trial_id
        or decision.input_fingerprint != evaluation_state.input_fingerprint
        or decision.revision_plan.path != revision_plan_path
        or decision.revision_plan.sha256 != author_artifacts[0].sha256
        or decision.source_hashes.get("analysis/scene_spec.json")
        != decision.baseline_scene_spec.sha256
    ):
        raise ValueError("evaluated candidate reroute decision identity is inconsistent")
    surface_blockers = [
        item
        for item in decision.blockers
        if item.startswith(_SURFACE_DETAIL_BLOCKER_PREFIX)
    ]
    other_blockers = [
        item
        for item in decision.blockers
        if not item.startswith(_SURFACE_DETAIL_BLOCKER_PREFIX)
    ]
    if (
        decision.promotable
        or decision.status != "not_improved"
        or decision.scores.direct_score_delta
        < decision.scores.minimum_direct_improvement
        or decision.scores.silhouette_delta < -0.000001
        or not surface_blockers
        or other_blockers != [_CANDIDATE_IMPROVEMENT_REASON]
    ):
        raise PermissionError(
            "technical reroute accepts only a visually improved candidate blocked "
            "solely by authored V0.5 surface-detail bindings"
        )
    if require_current_sources:
        current_scene_spec = _contained_file(root, "analysis/scene_spec.json")
        if sha256_file(current_scene_spec) != decision.baseline_scene_spec.sha256:
            raise RuntimeError(
                "canonical SceneSpec changed before evaluated candidate technical reroute"
            )
    return decision


def _validate_standard_manual_guarded_reroute(
    root: Path,
    run_root: Path,
    *,
    run_id: str,
    job_id: str,
    binding: StandardCompositeStageBinding,
    prior_bindings: list[SkillArtifact],
    expected_sequence: int,
) -> None:
    """Validate one cancelled bounded child and its manual guarded successor."""

    reroute = binding.technical_reroute
    if reroute is None:
        raise ValueError("technical reroute validation requires reroute evidence")
    if reroute.reroute_sequence != expected_sequence:
        raise ValueError("Standard technical reroute sequence is noncontiguous")
    if not prior_bindings or reroute.source_stage_binding != prior_bindings[-1]:
        raise ValueError("Standard technical reroute lost its direct candidate predecessor")
    for artifact in (
        reroute.source_stage_binding,
        reroute.source_workflow_state,
        reroute.cancelled_workflow_state,
        reroute.cancellation_receipt,
    ):
        _validate_artifact(root, artifact)
    source_binding = _load_model(
        root,
        reroute.source_stage_binding,
        StandardCompositeStageBinding,
    )
    source_plan = _load_model(root, source_binding.workflow_plan, WorkflowPlan)
    source_request = _workflow_request_for_plan(root, source_plan)
    source_state = _load_model(root, reroute.source_workflow_state, WorkflowState)
    cancelled_state = _load_model(root, reroute.cancelled_workflow_state, WorkflowState)
    receipt = _load_model(root, reroute.cancellation_receipt, SkillExecutionReceipt)
    successor_plan = _load_model(root, binding.workflow_plan, WorkflowPlan)
    successor_request = _workflow_request_for_plan(root, successor_plan)
    expected_receipt_root = f"{run_root.relative_to(root).as_posix()}/receipts/"
    if not reroute.cancellation_receipt.path.startswith(expected_receipt_root):
        raise ValueError("Standard technical reroute receipt is outside its skill run")
    if (
        source_binding.run_id != run_id
        or source_binding.job_id != job_id
        or source_state.job_id != job_id
        or source_state.workflow_id != source_binding.workflow_id
        or cancelled_state.job_id != job_id
        or cancelled_state.workflow_id != source_binding.workflow_id
    ):
        raise ValueError("Standard technical reroute predecessor identity mismatch")
    source_step = next(
        (item for item in source_state.steps if item.step_id == "revision.author"),
        None,
    )
    source_is_untouched_candidate = (
        source_binding.stage_kind == "geometry"
        and source_binding.skill_id == "guarded-visual-revision"
        and source_plan.intent == "revise_asset"
        and source_request.revision_strategy == "candidate_review"
        and source_state.status == "waiting_for_agent"
        and source_state.current_step_id == "revision.author"
        and source_step is not None
        and source_step.status == "waiting_for_agent"
        and source_step.attempt_count == 0
        and source_step.completion_fingerprint is None
        and source_step.approval_id is None
        and all(artifact.integrity == "missing" for artifact in source_step.artifacts)
    )
    evaluated_decision = _evaluated_material_refresh_candidate(
        root,
        source_binding,
        source_plan,
        source_request,
        source_state,
        require_current_sources=False,
    )
    source_is_evaluated_material_refresh = evaluated_decision is not None
    source_is_rejected_material = False
    if source_binding.stage_kind == "material" and _untouched_material_workflow(
        source_plan,
        source_state,
    ):
        if len(prior_bindings) < 2:
            raise ValueError("geometry-review reroute lacks its geometry predecessor")
        if receipt.sequence <= 1:
            raise ValueError("geometry-review reroute lacks a predecessor receipt")
        predecessor_artifact = prior_bindings[-2]
        predecessor = _load_model(
            root,
            predecessor_artifact,
            StandardCompositeStageBinding,
        )
        predecessor_plan = _load_model(root, predecessor.workflow_plan, WorkflowPlan)
        predecessor_state_artifact = _workflow_state_source(
            root,
            predecessor.workflow_id,
        )
        predecessor_state = _load_model(
            root,
            predecessor_state_artifact,
            WorkflowState,
        )
        review = _completed_geometry_visual_review(
            root,
            predecessor_plan,
            predecessor_state,
        )
        prior_receipt_path = (
            run_root / "receipts" / f"{receipt.sequence - 1:04d}.json"
        )
        prior_receipt = SkillExecutionReceipt.model_validate_json(
            prior_receipt_path.read_text(encoding="utf-8")
        )
        _validate_artifact(root, prior_receipt.after.state)
        source_is_rejected_material = (
            predecessor.stage_kind == "geometry"
            and predecessor.ordinal + 1 == source_binding.ordinal
            and predecessor_state.status == "completed"
            and _geometry_review_requires_reentry(review)
            and receipt.previous_receipt_sha256 == sha256_file(prior_receipt_path)
            and prior_receipt.after.execution_id == predecessor.workflow_id
            and prior_receipt.after.status == "completed"
            and prior_receipt.after.state.sha256 == predecessor_state_artifact.sha256
        )
    if not (
        source_is_untouched_candidate
        or source_is_evaluated_material_refresh
        or source_is_rejected_material
    ):
        raise ValueError(
            "Standard technical reroute source is neither an untouched candidate, an "
            "evaluated material-refresh candidate, nor an untouched material child "
            "rejected by exact geometry review"
        )
    if (
        cancelled_state.status != "cancelled"
        or cancelled_state.current_step_id is not None
        or receipt.run_id != run_id
        or receipt.job_id != job_id
        or receipt.outcome != "cancelled"
        or receipt.before.execution_id != source_binding.workflow_id
        or receipt.before.state != reroute.source_workflow_state
        or receipt.after.execution_id != source_binding.workflow_id
        or receipt.after.state != reroute.cancelled_workflow_state
    ):
        raise ValueError("Standard technical reroute lacks an exact cancellation receipt")
    if (
        successor_plan.intent != "revise_asset"
        or successor_request.revision_strategy != "manual_guarded"
    ):
        raise ValueError("Standard technical reroute must bind manual_guarded revise_asset")
    if source_is_evaluated_material_refresh and (
        successor_request.raw_request != source_request.raw_request
        or not binding.created_reason.startswith(
            _QUALITY_REVISION_MANUAL_REASON_PREFIX
        )
    ):
        raise ValueError(
            "evaluated quality reroute must preserve its exact request and reason boundary"
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
    prior_bindings: list[SkillArtifact] = []
    recovery_sequence = 0
    reroute_sequence = 0
    for ordinal, artifact in enumerate(state.stage_bindings, start=1):
        binding = _load_model(root, artifact, StandardCompositeStageBinding)
        if binding.run_id != run_id or binding.job_id != job_id:
            raise ValueError("Standard child binding identity mismatch")
        if binding.ordinal != ordinal:
            raise ValueError("Standard child binding ordinal is noncontiguous")
        _validate_artifact(root, binding.workflow_plan)
        if binding.technical_recovery is not None:
            recovery_sequence += 1
            _validate_standard_technical_recovery(
                root,
                run_root,
                run_id=run_id,
                job_id=job_id,
                binding=binding,
                prior_bindings=prior_bindings,
                expected_sequence=recovery_sequence,
            )
        if binding.technical_reroute is not None:
            reroute_sequence += 1
            _validate_standard_manual_guarded_reroute(
                root,
                run_root,
                run_id=run_id,
                job_id=job_id,
                binding=binding,
                prior_bindings=prior_bindings,
                expected_sequence=reroute_sequence,
            )
        prior_bindings.append(artifact)
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
    for sequence, artifact in enumerate(state.quality_disposition_requests, start=1):
        request = _load_model(root, artifact, StandardQualityDispositionRequest)
        if (
            request.job_id != job_id
            or request.run_id != run_id
            or request.sequence != sequence
            or request.qa_source_stage_binding not in state.stage_bindings
        ):
            raise ValueError("quality-disposition request identity is noncontiguous")
        for bound in (
            request.qa_source_stage_binding,
            request.completed_qa_state,
            request.source_visual_qa_report,
            request.canonical_scene_spec_snapshot,
        ):
            _validate_artifact(root, bound)
    for sequence, artifact in enumerate(state.quality_dispositions, start=1):
        record = _load_model(root, artifact, StandardQualityDispositionRecord)
        request_artifact = state.quality_disposition_requests[sequence - 1]
        if (
            record.job_id != job_id
            or record.run_id != run_id
            or record.sequence != sequence
            or record.request != request_artifact
            or record.request_fingerprint != request_artifact.sha256
        ):
            raise ValueError("quality-disposition record identity is noncontiguous")
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


def _completed_qa_receipt_state(
    root: Path,
    run_root: Path,
    workflow_state: WorkflowState,
) -> SkillArtifact:
    """Find the immutable receipt snapshot for one exactly completed QA workflow."""

    receipt_root = run_root / "receipts"
    for receipt_path in reversed(sorted(receipt_root.glob("*.json"))):
        receipt = SkillExecutionReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        if (
            receipt.after.execution_id != workflow_state.workflow_id
            or receipt.after.status != "completed"
            or receipt.outcome != "completed"
        ):
            continue
        _validate_artifact(root, receipt.after.state)
        snapshotted = _load_model(root, receipt.after.state, WorkflowState)
        if snapshotted != workflow_state:
            raise ValueError("completed QA receipt snapshot differs from workflow state")
        return receipt.after.state
    raise ValueError("completed QA workflow lacks an immutable skill receipt snapshot")


def _enter_quality_disposition_boundary(
    root: Path,
    run_root: Path,
    plan: StandardCompositeRunPlan,
    state: StandardCompositeRunState,
    binding_artifact: SkillArtifact,
    binding: StandardCompositeStageBinding,
    workflow_state: WorkflowState,
) -> StandardCompositeRunState:
    """Publish one exact human quality request and stop before V0.7 planning."""

    if workflow_state.status != "completed":
        raise ValueError("quality disposition requires a completed QA workflow")
    workflow_plan = _load_model(root, binding.workflow_plan, WorkflowPlan)
    qa_run_id = _qa_run_id_from_workflow_plan(workflow_plan)
    qa_review = next(
        (item for item in workflow_state.steps if item.step_id == "qa.review"),
        None,
    )
    if (
        qa_review is None
        or qa_review.status != "complete"
        or qa_review.input_fingerprint is None
        or qa_review.completion_fingerprint is None
        or qa_review.approval_id is None
        or qa_review.completed_at is None
    ):
        raise ValueError("quality disposition requires one consumed exact qa.review")
    report_path = _contained_file(root, f"qa/runs/{qa_run_id}/visual_qa_report.json")
    report = VisualQAReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    if report.job_id != plan.job_id or report.run_id != qa_run_id:
        raise ValueError("quality-disposition QA report identity mismatch")
    scene_path = _contained_file(root, "analysis/scene_spec.json")
    sequence = len(state.quality_disposition_requests) + 1
    if sequence > plan.max_qa_revision_iterations + 1:
        raise RuntimeError("quality-disposition request exceeds the QA revision budget")
    snapshot_path = (
        run_root
        / "quality"
        / "snapshots"
        / f"{sequence:04d}-scene-spec.json"
    )
    publish_bytes_create_once(snapshot_path, scene_path.read_bytes())
    high_finding_ids = sorted(
        item.id for item in report.findings if item.severity == "high"
    )
    request = StandardQualityDispositionRequest(
        request_id=f"quality-request-{sequence:04d}",
        sequence=sequence,
        run_id=plan.run_id,
        job_id=plan.job_id,
        qa_source_stage_binding=binding_artifact,
        completed_qa_state=_completed_qa_receipt_state(
            root,
            run_root,
            workflow_state,
        ),
        source_visual_qa_report=_artifact_for(root, report_path),
        canonical_scene_spec_snapshot=_artifact_for(root, snapshot_path),
        source_qa_run_id=qa_run_id,
        qa_review_input_fingerprint=qa_review.input_fingerprint,
        qa_review_completion_fingerprint=qa_review.completion_fingerprint,
        qa_review_approval_id=qa_review.approval_id,
        direct_score=report.direct_metrics.overall_direct_score,
        silhouette_iou=report.direct_metrics.silhouette_iou,
        high_finding_ids=high_finding_ids,
        recommended_disposition=(
            "needs_revision" if high_finding_ids else "accepted"
        ),
        created_at=qa_review.completed_at,
    )
    request_artifact = _publish_model(
        root,
        run_root / "quality" / "requests" / f"{sequence:04d}.json",
        request,
    )
    return state.model_copy(
        update={
            "status": "waiting_for_quality_disposition",
            "current_stage_binding": binding_artifact,
            "quality_disposition_requests": [
                *state.quality_disposition_requests,
                request_artifact,
            ],
            "current_quality_disposition_request": request_artifact,
            "next_action": (
                "Inspect the exact V0.6 report and record accepted or needs_revision "
                f"with quality_disposition fingerprint {request_artifact.sha256}; the "
                "qa.review approval does not imply this decision."
            ),
            "updated_at": _utc_now(),
        }
    )


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


def _revision_operation_signature(operation: Any) -> bytes:
    """Serialize one bounded candidate or plan operation for exact multiset comparison."""

    return deterministic_json_bytes(
        {
            "target_type": operation.target_type,
            "target_id": operation.target_id,
            "path": operation.path,
            "op": operation.op,
            "value": operation.value,
        }
    )


def _latest_quality_revision_context(
    root: Path,
    state: StandardCompositeRunState,
) -> tuple[
    StandardQualityDispositionRequest,
    StandardQualityDispositionRecord,
    Path,
    RevisionCandidates,
]:
    """Load the latest exact needs-revision decision and its source V0.6 candidates."""

    if not state.quality_disposition_requests or not state.quality_dispositions:
        raise ValueError("bounded quality revision lacks its exact human disposition")
    request_artifact = state.quality_disposition_requests[-1]
    record_artifact = state.quality_dispositions[-1]
    request = _load_model(root, request_artifact, StandardQualityDispositionRequest)
    record = _load_model(root, record_artifact, StandardQualityDispositionRecord)
    if (
        record.request != request_artifact
        or record.request_fingerprint != request_artifact.sha256
        or record.disposition != "needs_revision"
    ):
        raise ValueError("bounded quality revision is not bound to exact needs_revision evidence")
    qa_root = f"qa/runs/{request.source_qa_run_id}"
    candidates_path = _contained_file(root, f"{qa_root}/revision_candidates.json")
    candidates = RevisionCandidates.model_validate_json(
        candidates_path.read_text(encoding="utf-8")
    )
    if (
        candidates.job_id != request.job_id
        or candidates.base_spec_sha256 != request.canonical_scene_spec_snapshot.sha256
        or candidates.source_report_sha256 != request.source_visual_qa_report.sha256
    ):
        raise ValueError("bounded quality revision candidates differ from the exact QA request")
    return request, record, candidates_path, candidates


def _quality_revision_request_text(
    plan: StandardCompositeRunPlan,
    request: StandardQualityDispositionRequest,
    candidates: RevisionCandidates,
) -> str:
    """Describe one exact source-QA repair without broadening the original asset request."""

    candidate_ids = ", ".join(candidate.id for candidate in candidates.candidates)
    return (
        f"{plan.request_text}\n\n"
        f"Bounded post-QA revision for exact source run {request.source_qa_run_id}. "
        f"The human disposition is needs_revision for request {request.request_id}. "
        f"Author only a workflow-owned RevisionPlan using applicable direct-reference "
        f"candidate operations from [{candidate_ids}]. Preserve the comparison camera, "
        "semantic/material identities, immutable inputs, and every unrelated path. The "
        "candidate must be evaluated in isolation before any canonical promotion."
    )


def _plan_quality_candidate_review_child(
    root: Path,
    run_root: Path,
    plan: StandardCompositeRunPlan,
    state: StandardCompositeRunState,
) -> StandardCompositeRunState:
    """Route one remaining human-requested QA repair through isolated candidate review."""

    if state.qa_revision_iterations >= plan.max_qa_revision_iterations:
        raise RuntimeError("bounded quality revision budget is exhausted")
    request, _record, _candidates_path, candidates = _latest_quality_revision_context(
        root,
        state,
    )
    eligible = [
        candidate
        for candidate in candidates.candidates
        if candidate.applicability == "approval_required"
        and candidate.target_type == "object"
        and "direct_reference" in candidate.evidence_sources
    ]
    if not eligible:
        raise RuntimeError(
            "exact source QA has no direct-reference candidate eligible for isolated review"
        )
    child = _plan_child_workflow(
        root,
        run_root,
        run_id=plan.run_id,
        job_id=plan.job_id,
        ordinal=len(state.stage_bindings) + 1,
        request_text=_quality_revision_request_text(plan, request, candidates),
        stage_kind="geometry",
        profile_id=plan.profile_id,
        reason=(
            f"{_QUALITY_REVISION_REASON_PREFIX}; exact request {request.request_id} and "
            f"source QA {request.source_qa_run_id}."
        ),
        revision_strategy="candidate_review",
    )
    cleared = state.model_copy(
        update={
            "qa_revision_source_run_id": None,
            "qa_baseline_scene_spec_sha256": None,
        }
    )
    return _append_child_to_state(cleared, child)


def _publish_candidate_review_continuation(
    root: Path,
    run_root: Path,
    plan: StandardCompositeRunPlan,
    state: StandardCompositeRunState,
    binding: StandardCompositeStageBinding,
    workflow_state: WorkflowState,
) -> SkillArtifact:
    """Bind one consumed candidate-review promotion as a Standard QA repair iteration."""

    if workflow_state.status != "completed":
        raise ValueError("candidate-review continuation requires one completed child workflow")
    request, _record, candidates_path, candidates = _latest_quality_revision_context(
        root,
        state,
    )
    workflow_plan = _load_model(root, binding.workflow_plan, WorkflowPlan)
    workflow_request_path = _contained_file(
        root,
        f"workflows/{binding.workflow_id}/request.json",
    )
    workflow_request = WorkflowRequest.model_validate_json(
        workflow_request_path.read_text(encoding="utf-8")
    )
    if (
        workflow_plan.intent != "revise_asset"
        or workflow_request.revision_strategy != "candidate_review"
        or workflow_request.job_id != plan.job_id
    ):
        raise ValueError("quality repair child is not an exact candidate-review revision")
    evaluation_steps = [
        item for item in workflow_plan.steps if item.step_id == "revision.evaluate"
    ]
    if len(evaluation_steps) != 1:
        raise ValueError("candidate-review child must contain one revision.evaluate step")
    evaluation_step = evaluation_steps[0]
    trial_id = evaluation_step.parameters.get("trial_id")
    plan_relative = evaluation_step.parameters.get("revision_plan_path")
    if not isinstance(trial_id, str) or not isinstance(plan_relative, str):
        raise ValueError("candidate-review child omitted its exact trial or plan path")
    trial_root = f"qa/candidate_reviews/{trial_id}"
    decision_path = _contained_file(root, f"{trial_root}/decision_manifest.json")
    approval_path = _contained_file(root, f"{trial_root}/promotion_approval.json")
    receipt_path = _contained_file(root, f"{trial_root}/promotion_receipt.json")
    revision_plan_path = _contained_file(root, plan_relative)
    decision = validate_candidate_review_decision(
        root,
        decision_path,
        require_current_sources=False,
    )
    approval = CandidateReviewApproval.model_validate_json(
        approval_path.read_text(encoding="utf-8")
    )
    receipt = CandidateReviewPromotionReceipt.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    revision_plan = RevisionPlan.model_validate_json(
        revision_plan_path.read_text(encoding="utf-8")
    )
    current_scene_spec = _contained_file(root, "analysis/scene_spec.json")
    current_scene_spec_sha256 = sha256_file(current_scene_spec)
    decision_sha256 = sha256_file(decision_path)
    approval_identity = stable_json_digest(
        approval.model_dump(mode="json", exclude={"used", "used_at"})
    )
    if (
        decision.job_id != plan.job_id
        or decision.workflow_id != binding.workflow_id
        or decision.trial_id != trial_id
        or not decision.promotable
        or decision.baseline_scene_spec.sha256
        != request.canonical_scene_spec_snapshot.sha256
        or decision.candidate_scene_spec.sha256 != current_scene_spec_sha256
        or decision.revision_plan.path != plan_relative
        or decision.revision_plan.sha256 != sha256_file(revision_plan_path)
    ):
        raise ValueError("candidate-review decision differs from the quality repair boundary")
    if (
        approval.job_id != plan.job_id
        or approval.trial_id != trial_id
        or approval.decision_sha256 != decision_sha256
        or approval.baseline_scene_spec_sha256
        != request.canonical_scene_spec_snapshot.sha256
        or approval.candidate_scene_spec_sha256 != current_scene_spec_sha256
        or not approval.used
        or approval.used_at is None
    ):
        raise ValueError("candidate-review promotion approval is stale or unconsumed")
    if (
        receipt.job_id != plan.job_id
        or receipt.workflow_id != binding.workflow_id
        or receipt.trial_id != trial_id
        or receipt.decision_sha256 != decision_sha256
        or receipt.approval_identity_sha256 != approval_identity
        or receipt.previous_canonical_sha256
        != request.canonical_scene_spec_snapshot.sha256
        or receipt.candidate_scene_spec_sha256 != current_scene_spec_sha256
        or receipt.final_canonical_sha256 != current_scene_spec_sha256
        or receipt.status != "promoted"
    ):
        raise ValueError("candidate-review promotion receipt is incomplete or mismatched")
    if (
        revision_plan.job_id != plan.job_id
        or revision_plan.base_spec_sha256
        != request.canonical_scene_spec_snapshot.sha256
    ):
        raise ValueError("candidate-review RevisionPlan differs from the waiting baseline")
    eligible_operations = Counter(
        _revision_operation_signature(candidate)
        for candidate in candidates.candidates
        if candidate.applicability == "approval_required"
        and "direct_reference" in candidate.evidence_sources
    )
    planned_operations = Counter(
        _revision_operation_signature(operation) for operation in revision_plan.operations
    )
    if not planned_operations or planned_operations - eligible_operations:
        raise ValueError(
            "candidate-review RevisionPlan contains operations outside the exact QA candidates"
        )
    evaluation_state = next(
        (item for item in workflow_state.steps if item.step_id == "revision.evaluate"),
        None,
    )
    if (
        evaluation_state is None
        or evaluation_state.status != "complete"
        or evaluation_state.input_fingerprint != decision.input_fingerprint
    ):
        raise ValueError("candidate-review workflow completion lost its evaluation fingerprint")
    iteration = state.qa_revision_iterations + 1
    if iteration > plan.max_qa_revision_iterations:
        raise RuntimeError("QA revision iteration budget was exceeded")
    continuation = GuardedRevisionContinuation(
        continuation_id=f"guarded-revision-{plan.run_id}-{iteration:04d}",
        run_id=plan.run_id,
        job_id=plan.job_id,
        iteration=iteration,
        source_qa_run_id=request.source_qa_run_id,
        baseline_scene_spec_sha256=request.canonical_scene_spec_snapshot.sha256,
        result_scene_spec_sha256=current_scene_spec_sha256,
        source_visual_qa_report=request.source_visual_qa_report,
        candidates=_artifact_for(root, candidates_path),
        revision_plan=_artifact_for(root, revision_plan_path),
        consumed_user_approval=_artifact_for(root, approval_path),
        application_report=_artifact_for(root, receipt_path),
        convergence_report=_artifact_for(root, decision_path),
        application_status="accepted",
        validated_at=receipt.promoted_at,
    )
    return _publish_model(
        root,
        run_root / "revisions" / f"{iteration:04d}.json",
        continuation,
    )


def _application_change_signature(change: dict[str, Any]) -> bytes:
    """Serialize one guarded application change for exact plan comparison."""

    required = {"target_type", "target_id", "path", "op", "after"}
    if not required.issubset(change):
        raise ValueError("guarded revision application change is incomplete")
    return deterministic_json_bytes(
        {
            "target_type": change["target_type"],
            "target_id": change["target_id"],
            "path": change["path"],
            "op": change["op"],
            "value": change["after"],
        }
    )


def _publish_manual_guarded_quality_continuation(
    root: Path,
    run_root: Path,
    plan: StandardCompositeRunPlan,
    state: StandardCompositeRunState,
    binding: StandardCompositeStageBinding,
    workflow_state: WorkflowState,
) -> SkillArtifact:
    """Bind one approved manual apply before mandatory fresh V0.5 and V0.6 work."""

    if workflow_state.status != "completed" or binding.technical_reroute is None:
        raise ValueError(
            "manual quality continuation requires one completed technical-reroute child"
        )
    request, _record, candidates_path, candidates = _latest_quality_revision_context(
        root,
        state,
    )
    workflow_plan = _load_model(root, binding.workflow_plan, WorkflowPlan)
    workflow_request = _workflow_request_for_plan(root, workflow_plan)
    if (
        workflow_plan.intent != "revise_asset"
        or workflow_request.revision_strategy != "manual_guarded"
        or workflow_request.job_id != plan.job_id
    ):
        raise ValueError("quality repair child is not an exact manual_guarded revision")
    planned_steps = {item.step_id: item for item in workflow_plan.steps}
    state_steps = {item.step_id: item for item in workflow_state.steps}
    author_plan = planned_steps.get("revision.author")
    approval_plan = planned_steps.get("revision.approval")
    apply_plan = planned_steps.get("revision.apply")
    author_state = state_steps.get("revision.author")
    approval_state = state_steps.get("revision.approval")
    apply_state = state_steps.get("revision.apply")
    if any(
        item is None
        for item in (
            author_plan,
            approval_plan,
            apply_plan,
            author_state,
            approval_state,
            apply_state,
        )
    ):
        raise ValueError("manual quality continuation lacks its guarded workflow steps")
    author_artifacts = [
        item for item in author_state.artifacts if item.artifact_id == "revision.plan"
    ]
    scene_artifacts = [
        item
        for item in apply_state.artifacts
        if item.artifact_id == "revision.scene_spec"
    ]
    diff_artifacts = [
        item for item in apply_state.artifacts if item.artifact_id == "revision.diff"
    ]
    if (
        author_state.status != "complete"
        or author_state.completion_fingerprint is None
        or len(author_artifacts) != 1
        or author_artifacts[0].path != "analysis/revision_plan.json"
        or author_artifacts[0].sha256 is None
        or author_artifacts[0].integrity != "valid"
        or approval_state.status != "complete"
        or approval_state.input_fingerprint is None
        or approval_state.completion_fingerprint is None
        or approval_state.approval_id is None
        or apply_state.status != "complete"
        or apply_state.attempt_count < 1
        or apply_state.completion_fingerprint is None
        or apply_state.completed_at is None
        or len(scene_artifacts) != 1
        or len(diff_artifacts) != 1
        or any(
            item.sha256 is None or item.integrity != "valid"
            for item in (*scene_artifacts, *diff_artifacts)
        )
    ):
        raise ValueError("manual quality continuation has incomplete guarded evidence")
    revision_plan_path = _contained_file(root, author_artifacts[0].path)
    scene_snapshot_path = _contained_file(root, scene_artifacts[0].path)
    application_path = _contained_file(root, diff_artifacts[0].path)
    if (
        sha256_file(revision_plan_path) != author_artifacts[0].sha256
        or sha256_file(scene_snapshot_path) != scene_artifacts[0].sha256
        or sha256_file(application_path) != diff_artifacts[0].sha256
    ):
        raise ValueError("manual quality continuation artifact hash changed")
    approval_path = _contained_file(
        root,
        f"workflows/{binding.workflow_id}/approvals/revision.approval.json",
    )
    approval = WorkflowApproval.model_validate_json(
        approval_path.read_text(encoding="utf-8")
    )
    workflow_plan_path = _validate_artifact(root, binding.workflow_plan)
    if (
        approval.workflow_id != binding.workflow_id
        or approval.job_id != plan.job_id
        or approval.step_id != "revision.approval"
        or approval.gate != "detailed_geometry"
        or approval.plan_sha256 != sha256_file(workflow_plan_path)
        or approval.artifact_fingerprint != approval_state.input_fingerprint
        or approval.approval_id != approval_state.approval_id
    ):
        raise ValueError("manual quality continuation approval is stale or mismatched")
    revision_plan = RevisionPlan.model_validate_json(
        revision_plan_path.read_text(encoding="utf-8")
    )
    application = json.loads(application_path.read_text(encoding="utf-8"))
    if not isinstance(application, dict) or not isinstance(
        application.get("changes"),
        list,
    ):
        raise ValueError("manual quality continuation application report is invalid")
    current_scene_spec = _contained_file(root, "analysis/scene_spec.json")
    current_scene_spec_sha256 = sha256_file(current_scene_spec)
    if (
        revision_plan.job_id != plan.job_id
        or revision_plan.base_spec_sha256
        != request.canonical_scene_spec_snapshot.sha256
        or application.get("ok") is not True
        or application.get("job_id") != plan.job_id
        or application.get("base_spec_sha256") != revision_plan.base_spec_sha256
        or application.get("result_spec_sha256") != current_scene_spec_sha256
        or scene_artifacts[0].sha256 != current_scene_spec_sha256
    ):
        raise ValueError("manual quality continuation differs from its exact QA baseline")
    eligible_operations = Counter(
        _revision_operation_signature(candidate)
        for candidate in candidates.candidates
        if candidate.applicability == "approval_required"
        and "direct_reference" in candidate.evidence_sources
    )
    planned_operations = Counter(
        _revision_operation_signature(operation) for operation in revision_plan.operations
    )
    applied_operations = Counter(
        _application_change_signature(change)
        for change in application["changes"]
        if isinstance(change, dict)
    )
    if (
        not planned_operations
        or planned_operations - eligible_operations
        or applied_operations != planned_operations
    ):
        raise ValueError(
            "manual quality continuation contains operations outside the exact QA candidates"
        )
    iteration = state.qa_revision_iterations + 1
    if iteration > plan.max_qa_revision_iterations:
        raise RuntimeError("QA revision iteration budget was exceeded")
    evidence_root = run_root / "revisions" / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    revision_plan_snapshot = evidence_root / f"{iteration:04d}-revision-plan.json"
    publish_bytes_create_once(revision_plan_snapshot, revision_plan_path.read_bytes())
    continuation = GuardedRevisionContinuation(
        continuation_id=f"guarded-revision-{plan.run_id}-{iteration:04d}",
        run_id=plan.run_id,
        job_id=plan.job_id,
        iteration=iteration,
        source_qa_run_id=request.source_qa_run_id,
        baseline_scene_spec_sha256=request.canonical_scene_spec_snapshot.sha256,
        result_scene_spec_sha256=current_scene_spec_sha256,
        source_visual_qa_report=request.source_visual_qa_report,
        candidates=_artifact_for(root, candidates_path),
        revision_plan=_artifact_for(root, revision_plan_snapshot),
        consumed_user_approval=_artifact_for(root, approval_path),
        application_report=_artifact_for(root, application_path),
        convergence_report=None,
        application_status="applied_unverified",
        validated_at=apply_state.completed_at,
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
    review = (
        _completed_geometry_visual_review(root, workflow_plan, workflow_state)
        if binding.stage_kind == "geometry"
        else None
    )
    if _geometry_review_requires_reentry(review):
        reentry_count = sum(
            _load_model(root, artifact, StandardCompositeStageBinding)
            .created_reason.startswith(_GEOMETRY_REENTRY_REASON_PREFIX)
            for artifact in state.stage_bindings
        )
        if reentry_count >= 1:
            return _publish_standard_terminal(
                root,
                run_root,
                plan,
                state,
                binding,
                workflow_state,
                terminal_type="blocked",
                reason=(
                    "Bounded V0.4 correction still requires geometry re-entry; preserve "
                    "the exact visual review and do not continue to material or QA."
                ),
            )
        child = _plan_child_workflow(
            root,
            run_root,
            run_id=plan.run_id,
            job_id=plan.job_id,
            ordinal=next_ordinal,
            request_text=plan.request_text,
            stage_kind="geometry",
            profile_id=plan.profile_id,
            reason=(
                f"{_GEOMETRY_REENTRY_REASON_PREFIX}; exact run {review.run_id} "
                f"recorded {review.outcome} before material or QA."
            ),
            revision_strategy="manual_guarded",
        )
        return _append_child_to_state(state, child)
    if (
        binding.stage_kind == "geometry"
        and binding.created_reason.startswith(_QUALITY_REVISION_REASON_PREFIX)
    ):
        evidence = _publish_candidate_review_continuation(
            root,
            run_root,
            plan,
            state,
            binding,
            workflow_state,
        )
        state = state.model_copy(
            update={
                "qa_revision_iterations": state.qa_revision_iterations + 1,
                "qa_revision_evidence": [*state.qa_revision_evidence, evidence],
            }
        )
    elif (
        binding.stage_kind == "geometry"
        and binding.created_reason.startswith(_QUALITY_REVISION_MANUAL_REASON_PREFIX)
    ):
        evidence = _publish_manual_guarded_quality_continuation(
            root,
            run_root,
            plan,
            state,
            binding,
            workflow_state,
        )
        state = state.model_copy(
            update={
                "qa_revision_iterations": state.qa_revision_iterations + 1,
                "qa_revision_evidence": [*state.qa_revision_evidence, evidence],
            }
        )
    if binding.stage_kind == "geometry" and workflow_plan.intent == "new_asset":
        if plan.goal == "full_cycle_to_package":
            if state.current_stage_binding is None:
                raise RuntimeError("completed Standard QA lost its stage binding")
            return _enter_quality_disposition_boundary(
                root,
                run_root,
                plan,
                state,
                state.current_stage_binding,
                binding,
                workflow_state,
            )
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
        snapshot_label = (
            "after-geometry"
            if binding.ordinal == 1
            else f"after-geometry-{binding.ordinal:04d}"
        )
        after = _capture_material_snapshot(root, run_root, snapshot_label)
        impact_artifact = _publish_material_impact(
            root,
            run_root,
            plan,
            after,
            stage_ordinal=binding.ordinal,
        )
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
        if state.current_stage_binding is None:
            raise RuntimeError("completed Standard QA lost its stage binding")
        return _enter_quality_disposition_boundary(
            root,
            run_root,
            plan,
            state,
            state.current_stage_binding,
            binding,
            workflow_state,
        )
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
    if current is None:
        return state
    if current == state.qa_baseline_scene_spec_sha256:
        if plan.goal == "full_cycle_to_package" and state.quality_dispositions:
            latest = _load_model(
                root,
                state.quality_dispositions[-1],
                StandardQualityDispositionRecord,
            )
            if latest.disposition == "needs_revision":
                return _plan_quality_candidate_review_child(root, run_root, plan, state)
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


def _recover_failed_standard_to_guarded_geometry(
    job_id: str,
    run_id: str,
    *,
    failed_state_sha256: str,
    recovery_reason: str,
) -> None:
    """Append a guarded geometry child without retrying an exact technical failure."""

    if re.fullmatch(r"[0-9a-f]{64}", failed_state_sha256) is None:
        raise ValueError("failed_state_sha256 must be one lowercase SHA-256 digest")
    normalized_reason = recovery_reason.strip()
    if not normalized_reason:
        raise ValueError("technical recovery requires an explicit non-empty reason")
    root, run_root, plan, state = _load_standard_run(job_id, run_id)
    with _skill_run_lock(run_root):
        root, run_root, plan, state = _load_standard_run(job_id, run_id)
        if (run_root / "terminal.json").is_file():
            raise RuntimeError("terminal Standard asset cycle cannot be recovered")
        if state.status != "failed":
            raise RuntimeError("guarded technical recovery requires a failed skill state")
        failed_binding_artifact = state.current_stage_binding
        failed_binding = _current_binding(root, state)
        failed_payload = get_workflow_status(job_id, failed_binding.workflow_id)
        failed_state = WorkflowState.model_validate(failed_payload["state"])
        failed_state_artifact = _workflow_state_source(root, failed_binding.workflow_id)
        if failed_state_artifact.sha256 != failed_state_sha256:
            raise RuntimeError("failed workflow state hash changed before technical recovery")
        failed_step = next(
            (
                item
                for item in failed_state.steps
                if item.step_id == failed_state.current_step_id
            ),
            None,
        )
        if (
            failed_state.status != "failed"
            or failed_state.reason_code != "host_failure"
            or failed_step is None
            or failed_step.status != "failed"
            or failed_step.reason_code != "host_failure"
            or failed_step.input_fingerprint is None
        ):
            raise PermissionError(
                "guarded technical recovery accepts only an exact failed host step"
            )
        receipt_sequence = _receipt_sequence(run_root) - 1
        if receipt_sequence < 1 or state.receipt_chain_head_sha256 is None:
            raise ValueError("failed Standard state lacks its execution receipt chain")
        failed_receipt_path = run_root / "receipts" / f"{receipt_sequence:04d}.json"
        failed_receipt_artifact = _artifact_for(root, failed_receipt_path)
        failed_receipt = SkillExecutionReceipt.model_validate_json(
            failed_receipt_path.read_text(encoding="utf-8")
        )
        _validate_artifact(root, failed_receipt.after.state)
        if (
            failed_receipt_artifact.sha256 != state.receipt_chain_head_sha256
            or failed_receipt.outcome != "failed"
            or failed_receipt.after.execution_id != failed_binding.workflow_id
            or failed_receipt.after.status != "failed"
            or failed_receipt.after.state.sha256 != failed_state_artifact.sha256
        ):
            raise ValueError("failed Standard state is not bound to its exact last receipt")
        scene_path = root / "analysis" / "scene_spec.json"
        if not scene_path.is_file():
            raise FileNotFoundError("guarded technical recovery requires canonical SceneSpec")
        current_scene_sha256 = sha256_file(scene_path)
        failed_scene_hashes = {
            artifact.sha256
            for step in failed_state.steps
            for artifact in step.artifacts
            if artifact.path == "analysis/scene_spec.json"
            and artifact.integrity == "valid"
            and artifact.currency == "current"
            and artifact.sha256 is not None
        }
        if failed_scene_hashes != {current_scene_sha256}:
            raise RuntimeError(
                "canonical SceneSpec differs from the exact failed workflow boundary"
            )
        recovery_sequence = 1 + sum(
            _load_model(root, artifact, StandardCompositeStageBinding).technical_recovery
            is not None
            for artifact in state.stage_bindings
        )
        scene_snapshot_path = (
            run_root
            / "recoveries"
            / f"{recovery_sequence:04d}-scene-spec-before.json"
        )
        publish_bytes_create_once(scene_snapshot_path, scene_path.read_bytes())
        scene_snapshot = _artifact_for(root, scene_snapshot_path)
        if failed_binding_artifact is None:
            raise RuntimeError("failed Standard state lost its current stage binding")
        recovery = StandardTechnicalRecoveryBinding(
            recovery_id=f"technical-recovery-{run_id}-{recovery_sequence:04d}",
            recovery_sequence=recovery_sequence,
            failed_stage_binding=failed_binding_artifact,
            failed_workflow_state=failed_receipt.after.state,
            failed_execution_receipt=failed_receipt_artifact,
            failed_step_id=failed_step.step_id,
            failed_input_fingerprint=failed_step.input_fingerprint,
            canonical_scene_spec_snapshot=scene_snapshot,
            recovery_reason=normalized_reason,
            created_at=_utc_now(),
        )
        child = _plan_child_workflow(
            root,
            run_root,
            run_id=plan.run_id,
            job_id=plan.job_id,
            ordinal=len(state.stage_bindings) + 1,
            request_text=plan.request_text,
            stage_kind="geometry",
            profile_id=plan.profile_id,
            reason=(
                "Exact host failure is preserved; a new guarded V0.4 geometry "
                "continuation must complete before downstream material recovery."
            ),
            revision_strategy="manual_guarded",
            technical_recovery=recovery,
        )
        _write_standard_state(run_root, _append_child_to_state(state, child))


def _reroute_standard_candidate_to_manual_guarded(
    job_id: str,
    run_id: str,
    *,
    candidate_state_sha256: str,
    reroute_reason: str,
) -> None:
    """Cancel one bounded candidate child and append its manual guarded replacement."""

    if re.fullmatch(r"[0-9a-f]{64}", candidate_state_sha256) is None:
        raise ValueError("candidate_state_sha256 must be one lowercase SHA-256 digest")
    normalized_reason = reroute_reason.strip()
    if not normalized_reason:
        raise ValueError("technical reroute requires an explicit non-empty reason")
    root, run_root, plan, state = _load_standard_run(job_id, run_id)
    with _skill_run_lock(run_root):
        root, run_root, plan, state = _load_standard_run(job_id, run_id)
        if (run_root / "terminal.json").is_file():
            raise RuntimeError("terminal Standard asset cycle cannot be rerouted")
        source_binding_artifact = state.current_stage_binding
        source_binding = _current_binding(root, state)
        source_plan = _load_model(root, source_binding.workflow_plan, WorkflowPlan)
        source_request = _workflow_request_for_plan(root, source_plan)
        source_payload = get_workflow_status(job_id, source_binding.workflow_id)
        source_state = WorkflowState.model_validate(source_payload["state"])
        source_state_artifact = _workflow_state_source(root, source_binding.workflow_id)
        if source_state_artifact.sha256 != candidate_state_sha256:
            raise RuntimeError("candidate workflow state hash changed before technical reroute")
        source_step = next(
            (item for item in source_state.steps if item.step_id == "revision.author"),
            None,
        )
        source_is_untouched_candidate = (
            source_binding_artifact is not None
            and source_binding.stage_kind == "geometry"
            and source_binding.skill_id == "guarded-visual-revision"
            and source_plan.intent == "revise_asset"
            and source_request.revision_strategy == "candidate_review"
            and source_state.status == "waiting_for_agent"
            and source_state.current_step_id == "revision.author"
            and source_step is not None
            and source_step.status == "waiting_for_agent"
            and source_step.attempt_count == 0
            and source_step.completion_fingerprint is None
            and source_step.approval_id is None
            and all(
                artifact.integrity == "missing" for artifact in source_step.artifacts
            )
        )
        evaluated_decision = _evaluated_material_refresh_candidate(
            root,
            source_binding,
            source_plan,
            source_request,
            source_state,
            require_current_sources=True,
        )
        evaluated_decision_sha256 = (
            sha256_file(
                _contained_file(
                    root,
                    "qa/candidate_reviews/"
                    f"{evaluated_decision.trial_id}/decision_manifest.json",
                )
            )
            if evaluated_decision is not None
            else None
        )
        if source_binding_artifact is None or not (
            source_is_untouched_candidate or evaluated_decision is not None
        ):
            raise PermissionError(
                "technical reroute accepts only an untouched candidate author step or an "
                "exact visually improved candidate blocked by stale V0.5 bindings"
            )
        receipt_sequence = _receipt_sequence(run_root) - 1
        if receipt_sequence < 1 or state.receipt_chain_head_sha256 is None:
            raise ValueError("candidate Standard state lacks its execution receipt chain")
        prior_receipt_path = run_root / "receipts" / f"{receipt_sequence:04d}.json"
        prior_receipt = SkillExecutionReceipt.model_validate_json(
            prior_receipt_path.read_text(encoding="utf-8")
        )
        if (
            sha256_file(prior_receipt_path) != state.receipt_chain_head_sha256
            or prior_receipt.after.execution_id != source_binding.workflow_id
            or prior_receipt.after.status != source_state.status
            or prior_receipt.after.state.sha256 != source_state_artifact.sha256
        ):
            raise ValueError("candidate Standard state is not bound to its exact last receipt")
        sequence = _receipt_sequence(run_root)
        before_snapshot = _snapshot_underlying_state(
            root,
            run_root,
            sequence=sequence,
            label="before-reroute",
            source_artifact=source_state_artifact,
        )
        bundle, registry = _load_bundle(root, run_root)
        route_key, _placeholder, route_reason = _standard_route(
            root,
            source_binding,
            source_state,
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
            reason=(
                f"{route_reason} "
                + (
                    "The exact nonpromotable candidate decision preserves direct visual "
                    "improvement but invalidates authored V0.5 surface-detail bindings; "
                    "with no promotion approval present, it is rerouted without approval."
                    if evaluated_decision is not None
                    else "The untouched candidate envelope cannot express the requested "
                    "custom-mesh redesign and is rerouted without approval."
                )
            ),
        )
        cancelled_state = cancel_workflow(
            job_id,
            source_binding.workflow_id,
            reason=f"Skill run {run_id}: {normalized_reason}",
        )
        cancelled_snapshot = _snapshot_underlying_state(
            root,
            run_root,
            sequence=sequence,
            label="after-reroute",
            source_artifact=_workflow_state_source(root, source_binding.workflow_id),
        )
        cancellation_receipt = _publish_execution_receipt(
            root,
            run_root,
            run_id=run_id,
            job_id=job_id,
            sequence=sequence,
            route=route,
            before=_workflow_binding(source_binding, before_snapshot, source_state),
            after=_workflow_binding(source_binding, cancelled_snapshot, cancelled_state),
            outcome="cancelled",
        )
        reroute_sequence = 1 + sum(
            _load_model(root, artifact, StandardCompositeStageBinding).technical_reroute
            is not None
            for artifact in state.stage_bindings
        )
        reroute = StandardManualGuardedRerouteBinding(
            reroute_id=f"manual-reroute-{run_id}-{reroute_sequence:04d}",
            reroute_sequence=reroute_sequence,
            source_stage_binding=source_binding_artifact,
            source_workflow_state=before_snapshot,
            cancelled_workflow_state=cancelled_snapshot,
            cancellation_receipt=cancellation_receipt,
            reroute_reason=normalized_reason,
            created_at=_utc_now(),
        )
        quality_material_refresh = (
            evaluated_decision is not None
            and source_binding.created_reason.startswith(
                _QUALITY_REVISION_REASON_PREFIX
            )
        )
        child = _plan_child_workflow(
            root,
            run_root,
            run_id=plan.run_id,
            job_id=plan.job_id,
            ordinal=len(state.stage_bindings) + 1,
            request_text=(
                source_request.raw_request
                if evaluated_decision is not None
                else plan.request_text
            ),
            stage_kind="geometry",
            profile_id=plan.profile_id,
            reason=(
                (
                    f"{_QUALITY_REVISION_MANUAL_REASON_PREFIX}; exact nonpromotable "
                    f"decision {evaluated_decision_sha256} is preserved "
                    "before fresh V0.5 material authoring."
                )
                if quality_material_refresh
                else (
                    "An ineligible candidate-review child is preserved as cancelled; "
                    "manual_guarded V0.4 authoring now owns the exact revision proposal."
                )
            ),
            revision_strategy="manual_guarded",
            technical_reroute=reroute,
        )
        state = state.model_copy(
            update={
                "receipt_chain_head_sha256": cancellation_receipt.sha256,
                "updated_at": _utc_now(),
            }
        )
        _write_standard_state(run_root, _append_child_to_state(state, child))


def _reconcile_unstarted_material_after_geometry_review(
    root: Path,
    run_root: Path,
    plan: StandardCompositeRunPlan,
    state: StandardCompositeRunState,
) -> StandardCompositeRunState:
    """Cancel an untouched material child when its exact geometry review requires re-entry."""

    source_binding_artifact = state.current_stage_binding
    if source_binding_artifact is None or len(state.stage_bindings) < 2:
        return state
    source_binding = _current_binding(root, state)
    if source_binding.stage_kind != "material":
        return state
    source_plan = _load_model(root, source_binding.workflow_plan, WorkflowPlan)
    source_payload = get_workflow_status(plan.job_id, source_binding.workflow_id)
    source_state = WorkflowState.model_validate(source_payload["state"])
    predecessor_artifact = state.stage_bindings[-2]
    predecessor = _load_model(
        root,
        predecessor_artifact,
        StandardCompositeStageBinding,
    )
    if predecessor.stage_kind != "geometry":
        return state
    predecessor_plan = _load_model(root, predecessor.workflow_plan, WorkflowPlan)
    predecessor_payload = get_workflow_status(plan.job_id, predecessor.workflow_id)
    predecessor_state = WorkflowState.model_validate(predecessor_payload["state"])
    if predecessor_state.status != "completed":
        return state
    review = _completed_geometry_visual_review(
        root,
        predecessor_plan,
        predecessor_state,
    )
    if not _geometry_review_requires_reentry(review):
        return state
    if not _untouched_material_workflow(source_plan, source_state):
        raise PermissionError(
            "geometry-review re-entry cannot reroute a material child after work began"
        )
    last_receipt_sequence = _receipt_sequence(run_root) - 1
    if last_receipt_sequence < 1 or state.receipt_chain_head_sha256 is None:
        raise ValueError("geometry-review re-entry lacks its predecessor receipt chain")
    predecessor_state_artifact = _workflow_state_source(
        root,
        predecessor.workflow_id,
    )
    last_receipt_path = run_root / "receipts" / f"{last_receipt_sequence:04d}.json"
    last_receipt = SkillExecutionReceipt.model_validate_json(
        last_receipt_path.read_text(encoding="utf-8")
    )
    _validate_artifact(root, last_receipt.after.state)
    if (
        sha256_file(last_receipt_path) != state.receipt_chain_head_sha256
        or last_receipt.after.execution_id != predecessor.workflow_id
        or last_receipt.after.status != "completed"
        or last_receipt.after.state.sha256 != predecessor_state_artifact.sha256
    ):
        raise ValueError(
            "geometry-review re-entry is not bound to the completed geometry receipt"
        )
    sequence = _receipt_sequence(run_root)
    source_state_artifact = _workflow_state_source(root, source_binding.workflow_id)
    before_snapshot = _snapshot_underlying_state(
        root,
        run_root,
        sequence=sequence,
        label="before-geometry-review-reroute",
        source_artifact=source_state_artifact,
    )
    bundle, registry = _load_bundle(root, run_root)
    route_key, _placeholder, route_reason = _standard_route(
        root,
        source_binding,
        source_state,
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
        run_id=plan.run_id,
        job_id=plan.job_id,
        sequence=sequence,
        execution_mode="standard",
        route_key=route_key,
        selected_skill=selected_skill,
        source_state=before_snapshot,
        reason=(
            f"{route_reason} The exact predecessor geometry review requires V0.4 "
            "re-entry, so this untouched downstream material child is cancelled."
        ),
    )
    finding_ids = ", ".join(item.finding_id for item in review.findings)
    reroute_reason = (
        f"Geometry review {review.run_id} recorded {review.outcome}"
        + (f" for {finding_ids}." if finding_ids else ".")
    )
    cancelled_state = cancel_workflow(
        plan.job_id,
        source_binding.workflow_id,
        reason=f"Skill run {plan.run_id}: {reroute_reason}",
    )
    cancelled_snapshot = _snapshot_underlying_state(
        root,
        run_root,
        sequence=sequence,
        label="after-geometry-review-reroute",
        source_artifact=_workflow_state_source(root, source_binding.workflow_id),
    )
    cancellation_receipt = _publish_execution_receipt(
        root,
        run_root,
        run_id=plan.run_id,
        job_id=plan.job_id,
        sequence=sequence,
        route=route,
        before=_workflow_binding(source_binding, before_snapshot, source_state),
        after=_workflow_binding(source_binding, cancelled_snapshot, cancelled_state),
        outcome="cancelled",
    )
    reroute_sequence = 1 + sum(
        _load_model(root, artifact, StandardCompositeStageBinding).technical_reroute
        is not None
        for artifact in state.stage_bindings
    )
    reroute = StandardManualGuardedRerouteBinding(
        reroute_id=f"manual-reroute-{plan.run_id}-{reroute_sequence:04d}",
        reroute_sequence=reroute_sequence,
        source_stage_binding=source_binding_artifact,
        source_workflow_state=before_snapshot,
        cancelled_workflow_state=cancelled_snapshot,
        cancellation_receipt=cancellation_receipt,
        reroute_reason=reroute_reason,
        created_at=_utc_now(),
    )
    child = _plan_child_workflow(
        root,
        run_root,
        run_id=plan.run_id,
        job_id=plan.job_id,
        ordinal=len(state.stage_bindings) + 1,
        request_text=plan.request_text,
        stage_kind="geometry",
        profile_id=plan.profile_id,
        reason=(
            f"{_GEOMETRY_REENTRY_REASON_PREFIX}; the untouched material child is "
            "preserved as cancelled before a second bounded correction proposal."
        ),
        revision_strategy="manual_guarded",
        technical_reroute=reroute,
    )
    updated = state.model_copy(
        update={
            "receipt_chain_head_sha256": cancellation_receipt.sha256,
            "updated_at": _utc_now(),
        }
    )
    return _append_child_to_state(updated, child)


def _reconcile_portable_before_quality_disposition(
    root: Path,
    run_root: Path,
    plan: StandardCompositeRunPlan,
    state: StandardCompositeRunState,
) -> StandardCompositeRunState:
    """Cancel one pre-optimization V0.7 review that bypassed the quality boundary."""

    if (
        plan.goal != "full_cycle_to_package"
        or state.quality_disposition_requests
        or state.current_stage_binding is None
        or len(state.stage_bindings) < 2
    ):
        return state
    portable_binding = _current_binding(root, state)
    if portable_binding.stage_kind != "portable":
        return state
    qa_binding_artifact = state.stage_bindings[-2]
    qa_binding = _load_model(root, qa_binding_artifact, StandardCompositeStageBinding)
    qa_plan = _load_model(root, qa_binding.workflow_plan, WorkflowPlan)
    _qa_run_id_from_workflow_plan(qa_plan)
    qa_state = WorkflowState.model_validate(
        get_workflow_status(plan.job_id, qa_binding.workflow_id)["state"]
    )
    if qa_state.status != "completed":
        raise PermissionError("V0.7 quality-barrier reconciliation lacks completed QA")
    portable_state = WorkflowState.model_validate(
        get_workflow_status(plan.job_id, portable_binding.workflow_id)["state"]
    )
    approval_index = next(
        (
            index
            for index, item in enumerate(portable_state.steps)
            if item.step_id == "portable.plan_approval"
        ),
        None,
    )
    if approval_index is None:
        raise ValueError("portable workflow omitted its optimization approval step")
    unconsumed = portable_state.steps[approval_index:]
    if (
        portable_state.status != "waiting_for_approval"
        or portable_state.current_step_id != "portable.plan_approval"
        or unconsumed[0].status != "waiting_for_approval"
        or any(item.attempt_count != 0 for item in unconsumed)
        or any(item.approval_id is not None for item in unconsumed)
        or any(item.completion_fingerprint is not None for item in unconsumed)
    ):
        raise PermissionError(
            "V0.7 quality-barrier reconciliation stops after optimization authority exists"
        )
    last_sequence = _receipt_sequence(run_root) - 1
    if last_sequence < 1 or state.receipt_chain_head_sha256 is None:
        raise ValueError("misrouted V0.7 review lacks its execution receipt")
    last_receipt_path = run_root / "receipts" / f"{last_sequence:04d}.json"
    last_receipt = SkillExecutionReceipt.model_validate_json(
        last_receipt_path.read_text(encoding="utf-8")
    )
    portable_state_artifact = _workflow_state_source(
        root,
        portable_binding.workflow_id,
    )
    if (
        sha256_file(last_receipt_path) != state.receipt_chain_head_sha256
        or last_receipt.after.execution_id != portable_binding.workflow_id
        or last_receipt.after.status != portable_state.status
        or last_receipt.after.state.sha256 != portable_state_artifact.sha256
    ):
        raise ValueError("misrouted V0.7 review differs from its exact last receipt")
    sequence = _receipt_sequence(run_root)
    before_snapshot = _snapshot_underlying_state(
        root,
        run_root,
        sequence=sequence,
        label="before-quality-barrier-reroute",
        source_artifact=portable_state_artifact,
    )
    bundle, registry = _load_bundle(root, run_root)
    route_key, _placeholder, route_reason = _standard_route(
        root,
        portable_binding,
        portable_state,
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
        run_id=plan.run_id,
        job_id=plan.job_id,
        sequence=sequence,
        execution_mode="standard",
        route_key=route_key,
        selected_skill=selected_skill,
        source_state=before_snapshot,
        reason=(
            f"{route_reason} The exact QA approval lacks a separate human quality "
            "disposition, so this unapproved optimization review is cancelled."
        ),
    )
    cancelled_state = cancel_workflow(
        plan.job_id,
        portable_binding.workflow_id,
        reason=(
            f"Skill run {plan.run_id}: preserve the premature V0.7 review and restore "
            "the separate human quality-disposition boundary."
        ),
    )
    cancelled_snapshot = _snapshot_underlying_state(
        root,
        run_root,
        sequence=sequence,
        label="after-quality-barrier-reroute",
        source_artifact=_workflow_state_source(root, portable_binding.workflow_id),
    )
    receipt = _publish_execution_receipt(
        root,
        run_root,
        run_id=plan.run_id,
        job_id=plan.job_id,
        sequence=sequence,
        route=route,
        before=_workflow_binding(
            portable_binding,
            before_snapshot,
            portable_state,
        ),
        after=_workflow_binding(
            portable_binding,
            cancelled_snapshot,
            cancelled_state,
        ),
        outcome="cancelled",
    )
    reconciled = state.model_copy(
        update={
            "status": "running",
            "current_stage_binding": qa_binding_artifact,
            "receipt_chain_head_sha256": receipt.sha256,
            "next_action": "Publish the exact human quality-disposition boundary.",
            "updated_at": _utc_now(),
        }
    )
    return _enter_quality_disposition_boundary(
        root,
        run_root,
        plan,
        reconciled,
        qa_binding_artifact,
        qa_binding,
        qa_state,
    )


def _record_standard_quality_disposition(
    job_id: str,
    run_id: str,
    *,
    disposition: str,
    request_fingerprint: str,
    user_note: str,
) -> None:
    """Consume one exact human quality decision and select only its bounded route."""

    if disposition not in {"accepted", "needs_revision"}:
        raise ValueError("quality disposition must be accepted or needs_revision")
    if re.fullmatch(r"[0-9a-f]{64}", request_fingerprint) is None:
        raise ValueError("quality-disposition fingerprint must be one lowercase SHA-256")
    normalized_note = user_note.strip()
    if not normalized_note:
        raise ValueError("quality disposition requires one non-empty user note")
    root, run_root, plan, state = _load_standard_run(job_id, run_id)
    with _skill_run_lock(run_root):
        root, run_root, plan, state = _load_standard_run(job_id, run_id)
        reconciled = _reconcile_quality_boundary_receipt_head(root, run_root, state)
        if reconciled != state:
            state = reconciled
            _write_standard_state(run_root, state)
        if state.status != "waiting_for_quality_disposition":
            raise RuntimeError("Standard cycle is not waiting for a quality disposition")
        request_artifact = state.current_quality_disposition_request
        if request_artifact is None or request_artifact.sha256 != request_fingerprint:
            raise RuntimeError("quality-disposition fingerprint is stale or mismatched")
        request = _load_model(
            root,
            request_artifact,
            StandardQualityDispositionRequest,
        )
        current_scene = _contained_file(root, "analysis/scene_spec.json")
        if sha256_file(current_scene) != request.canonical_scene_spec_snapshot.sha256:
            raise RuntimeError("canonical SceneSpec changed after quality review")
        qa_binding = _load_model(
            root,
            request.qa_source_stage_binding,
            StandardCompositeStageBinding,
        )
        completed_qa = _load_model(
            root,
            request.completed_qa_state,
            WorkflowState,
        )
        live_qa = WorkflowState.model_validate(
            get_workflow_status(job_id, qa_binding.workflow_id)["state"]
        )
        if completed_qa != live_qa or live_qa.status != "completed":
            raise RuntimeError("completed QA state changed before quality disposition")
        record_path = (
            run_root
            / "quality"
            / "dispositions"
            / f"{request.sequence:04d}.json"
        )
        if record_path.is_file():
            record = StandardQualityDispositionRecord.model_validate_json(
                record_path.read_text(encoding="utf-8")
            )
            if (
                record.request != request_artifact
                or record.request_fingerprint != request_fingerprint
                or record.disposition != disposition
                or record.user_note != normalized_note
            ):
                raise RuntimeError("an orphaned quality disposition conflicts with this decision")
            record_artifact = _artifact_for(root, record_path)
        else:
            record = StandardQualityDispositionRecord(
                disposition_id=f"quality-disposition-{request.sequence:04d}",
                sequence=request.sequence,
                run_id=run_id,
                job_id=job_id,
                request=request_artifact,
                request_fingerprint=request_fingerprint,
                disposition=disposition,  # type: ignore[arg-type]
                user_note=normalized_note,
                recorded_at=_utc_now(),
            )
            record_artifact = _publish_model(root, record_path, record)
        decided = state.model_copy(
            update={
                "quality_dispositions": [
                    *state.quality_dispositions,
                    record_artifact,
                ],
                "current_quality_disposition_request": None,
                "updated_at": _utc_now(),
            }
        )
        if disposition == "accepted":
            child = _plan_child_workflow(
                root,
                run_root,
                run_id=plan.run_id,
                job_id=plan.job_id,
                ordinal=len(state.stage_bindings) + 1,
                request_text=plan.request_text,
                stage_kind="portable",
                profile_id=plan.profile_id,
                reason=(
                    "Exact human quality disposition accepted the current V0.6 source; "
                    "V0.7 still requires its own optimization and final-package approvals."
                ),
            )
            _write_standard_state(run_root, _append_child_to_state(decided, child))
            return
        if state.qa_revision_iterations < plan.max_qa_revision_iterations:
            routed = _plan_quality_candidate_review_child(
                root,
                run_root,
                plan,
                decided,
            )
            _write_standard_state(run_root, routed)
            return
        terminal = _publish_standard_terminal(
            root,
            run_root,
            plan,
            decided.model_copy(
                update={
                    "status": "running",
                    "current_stage_binding": request.qa_source_stage_binding,
                    "next_action": None,
                }
            ),
            qa_binding,
            completed_qa,
            terminal_type="blocked",
            reason=(
                "Human quality disposition is needs_revision and the exact bounded QA "
                "revision budget is exhausted; no V0.7 package is authorized."
            ),
        )
        _write_standard_state(run_root, terminal)


def _reconcile_quality_boundary_receipt_head(
    root: Path,
    run_root: Path,
    state: StandardCompositeRunState,
) -> StandardCompositeRunState:
    """Adopt only contiguous no-op receipts left by a quality-boundary interruption."""

    if state.status != "waiting_for_quality_disposition":
        return state
    receipt_root = run_root / "receipts"
    route_root = run_root / "routes"
    receipt_paths = sorted(receipt_root.glob("*.json"))
    route_paths = sorted(route_root.glob("*.json"))
    if len(receipt_paths) != len(route_paths):
        raise ValueError("skill route and execution receipt counts differ")
    if not receipt_paths or state.receipt_chain_head_sha256 is None:
        raise ValueError("quality boundary lacks its persisted receipt-chain head")
    bundle, registry = _load_bundle(root, run_root)
    bundle_artifact = _artifact_for(root, run_root / "bundle.json")
    validated: list[
        tuple[
            SkillRouteDecision,
            SkillExecutionReceipt,
            WorkflowState,
            WorkflowState,
            str,
        ]
    ] = []
    previous_sha: str | None = None
    persisted_head_index: int | None = None
    for index, (route_path, receipt_path) in enumerate(
        zip(route_paths, receipt_paths, strict=True),
        start=1,
    ):
        if route_path.name != f"{index:04d}.json" or receipt_path.name != (
            f"{index:04d}.json"
        ):
            raise ValueError("skill route or receipt sequence is noncontiguous")
        route = SkillRouteDecision.model_validate_json(
            route_path.read_text(encoding="utf-8")
        )
        receipt = SkillExecutionReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        route_artifact = _artifact_for(root, route_path)
        receipt_sha256 = sha256_file(receipt_path)
        if (
            (route.job_id, route.run_id, route.execution_mode)
            != (state.job_id, state.run_id, "standard")
            or route.bundle_manifest != bundle_artifact
            or route.selected_skill_id
            != _route_from_registry(
                bundle,
                registry,
                execution_mode="standard",
                route_key=route.stage_key,
            )
        ):
            raise ValueError("quality-boundary route identity is invalid")
        if (
            (receipt.job_id, receipt.run_id, receipt.sequence)
            != (state.job_id, state.run_id, index)
            or receipt.previous_receipt_sha256 != previous_sha
            or receipt.route_decision != route_artifact
            or receipt.before.state != route.source_state
            or receipt.before.execution_kind != "workflow_v08"
            or receipt.after.execution_kind != "workflow_v08"
            or receipt.before.execution_id != receipt.after.execution_id
        ):
            raise ValueError("quality-boundary receipt chain is invalid")
        for artifact in (
            route.bundle_manifest,
            route.source_state,
            receipt.before.state,
            receipt.after.state,
        ):
            _validate_artifact(root, artifact)
        before_state = _load_model(root, receipt.before.state, WorkflowState)
        after_state = _load_model(root, receipt.after.state, WorkflowState)
        if (
            receipt.before.status != before_state.status
            or receipt.before.next_action != before_state.next_action
            or receipt.after.status != after_state.status
            or receipt.after.next_action != after_state.next_action
        ):
            raise ValueError("quality-boundary receipt projection differs from its snapshot")
        validated.append(
            (route, receipt, before_state, after_state, receipt_sha256)
        )
        if receipt_sha256 == state.receipt_chain_head_sha256:
            persisted_head_index = index - 1
        previous_sha = receipt_sha256
    if state.receipt_chain_head_sha256 == previous_sha:
        return state
    if persisted_head_index is None:
        raise ValueError("quality-boundary receipt head is stale or unknown")
    binding = _current_binding(root, state)
    live_state_artifact = _workflow_state_source(root, binding.workflow_id)
    live_state = _load_model(root, live_state_artifact, WorkflowState)
    if live_state.status != "completed":
        raise ValueError("quality-boundary trailing receipt lacks a completed live QA state")
    for route, receipt, before_state, after_state, _receipt_sha256 in validated[
        persisted_head_index + 1 :
    ]:
        expected_route, _placeholder, _reason = _standard_route(
            root,
            binding,
            before_state,
        )
        if (
            receipt.outcome != "completed"
            or receipt.before.execution_id != binding.workflow_id
            or receipt.after.execution_id != binding.workflow_id
            or route.stage_key != expected_route
            or before_state != live_state
            or after_state != live_state
        ):
            raise ValueError(
                "quality-boundary trailing receipt is not an idempotent completed replay"
            )
    return state.model_copy(
        update={
            "receipt_chain_head_sha256": previous_sha,
            "updated_at": _utc_now(),
        }
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
        reconciled = _reconcile_unstarted_material_after_geometry_review(
            root,
            run_root,
            plan,
            state,
        )
        if reconciled != state:
            state = reconciled
            _write_standard_state(run_root, state)
        quality_reconciled = _reconcile_portable_before_quality_disposition(
            root,
            run_root,
            plan,
            state,
        )
        if quality_reconciled != state:
            state = quality_reconciled
            _write_standard_state(run_root, state)
        receipt_reconciled = _reconcile_quality_boundary_receipt_head(
            root,
            run_root,
            state,
        )
        if receipt_reconciled != state:
            state = receipt_reconciled
            _write_standard_state(run_root, state)
        if state.status == "waiting_for_quality_disposition":
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
                    "waiting_for_quality_disposition",
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
    recover_failed_to_guarded_geometry: bool = False,
    failed_state_sha256: str | None = None,
    recovery_reason: str | None = None,
    reroute_candidate_to_manual_guarded: bool = False,
    candidate_state_sha256: str | None = None,
    reroute_reason: str | None = None,
    quality_disposition: str | None = None,
    quality_disposition_fingerprint: str | None = None,
    quality_disposition_note: str | None = None,
) -> dict[str, object]:
    """Resume the same Standard plan, snapshots, children, and receipt chain."""

    selected_actions = sum(
        (
            recover_failed_to_guarded_geometry,
            reroute_candidate_to_manual_guarded,
            quality_disposition is not None,
        )
    )
    if selected_actions > 1:
        raise ValueError("recovery, reroute, and quality disposition are mutually exclusive")
    if recover_failed_to_guarded_geometry:
        if retry_failed:
            raise ValueError("technical recovery and failed-step retry are mutually exclusive")
        if failed_state_sha256 is None or recovery_reason is None:
            raise ValueError(
                "technical recovery requires failed_state_sha256 and recovery_reason"
            )
        _recover_failed_standard_to_guarded_geometry(
            job_id,
            run_id,
            failed_state_sha256=failed_state_sha256,
            recovery_reason=recovery_reason,
        )
    elif failed_state_sha256 is not None or recovery_reason is not None:
        raise ValueError("recovery evidence requires recover_failed_to_guarded_geometry=true")
    if reroute_candidate_to_manual_guarded:
        if retry_failed:
            raise ValueError("technical reroute and failed-step retry are mutually exclusive")
        if candidate_state_sha256 is None or reroute_reason is None:
            raise ValueError(
                "technical reroute requires candidate_state_sha256 and reroute_reason"
            )
        _reroute_standard_candidate_to_manual_guarded(
            job_id,
            run_id,
            candidate_state_sha256=candidate_state_sha256,
            reroute_reason=reroute_reason,
        )
    elif candidate_state_sha256 is not None or reroute_reason is not None:
        raise ValueError(
            "reroute evidence requires reroute_candidate_to_manual_guarded=true"
        )
    if quality_disposition is not None:
        if quality_disposition_fingerprint is None or quality_disposition_note is None:
            raise ValueError(
                "quality disposition requires its exact fingerprint and user note"
            )
        _record_standard_quality_disposition(
            job_id,
            run_id,
            disposition=quality_disposition,
            request_fingerprint=quality_disposition_fingerprint,
            user_note=quality_disposition_note,
        )
    elif (
        quality_disposition_fingerprint is not None
        or quality_disposition_note is not None
    ):
        raise ValueError(
            "quality-disposition evidence requires --quality-disposition"
        )
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


def _aq_binding_from_snapshot(
    root: Path,
    session_id: str,
    state_artifact: SkillArtifact,
    *,
    status: str,
) -> UnderlyingExecutionBinding:
    """Bind an orphan route's exact AQ snapshot without inventing newer state."""

    path = _validate_artifact(root, state_artifact)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("AQ route source snapshot must contain one state object")
    next_action = payload.get("next_action")
    return UnderlyingExecutionBinding(
        execution_kind="aq_one_prompt_v01",
        execution_id=session_id,
        state=state_artifact,
        status=status,
        next_action=str(next_action) if next_action else None,
    )


def _aq_outcome(status: dict[str, object]) -> str:
    """Classify one One-Prompt result without inventing a new terminal meaning."""

    value = str(status.get("status", ""))
    state, _artifact = _aq_base_state(status)
    state_status = str(state.get("status", ""))
    terminal_outcome = {
        "completed": "completed",
        "partial": "completed",
        "review_required": "completed",
        "blocked": "blocked",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(state_status)
    if terminal_outcome is not None:
        return terminal_outcome
    if value == "terminal":
        return "completed"
    if value == "waiting_for_controller":
        return "waiting_for_controller"
    if value == "genuine_escalation":
        return "blocked"
    if value == "global_action_slice_exhausted":
        return "slice_exhausted"
    if value.startswith("waiting_for_integrated_quality"):
        return "waiting_for_controller"
    return "advanced"


def _snapshot_aq_state_exact(
    root: Path,
    run_root: Path,
    *,
    sequence: int,
    label: str,
    source_artifact: SkillArtifact,
) -> SkillArtifact:
    """Publish or exactly adopt one crash-surviving AQ state snapshot."""

    source = _validate_artifact(root, source_artifact)
    target = run_root / "underlying" / f"{sequence:04d}-{label}.json"
    if target.is_file():
        if target.read_bytes() != source.read_bytes():
            raise ValueError("pending AQ snapshot differs from the current exact source")
        return _artifact_for(root, target)
    publish_bytes_create_once(target, source.read_bytes())
    return _artifact_for(root, target)


def _load_pending_aq_route(
    root: Path,
    run_root: Path,
    *,
    run_id: str,
    job_id: str,
    bundle: SkillBundleManifest,
    registry: SkillRegistry,
    source_public_status: str,
) -> tuple[SkillArtifact, SkillRouteDecision] | None:
    """Validate and return the sole receipt-less AQ route after an interruption."""

    route_root = run_root / "routes"
    receipt_root = run_root / "receipts"
    route_paths = sorted(route_root.glob("*.json")) if route_root.is_dir() else []
    receipt_paths = sorted(receipt_root.glob("*.json")) if receipt_root.is_dir() else []
    if len(route_paths) == len(receipt_paths):
        return None
    if len(route_paths) != len(receipt_paths) + 1:
        raise ValueError("AQ skill run has more than one pending route")
    sequence = len(receipt_paths) + 1
    route_path = route_paths[-1]
    if route_path.name != f"{sequence:04d}.json":
        raise ValueError("pending AQ route sequence is noncontiguous")
    route_artifact = _artifact_for(root, route_path)
    route = _load_model(root, route_artifact, SkillRouteDecision)
    expected_source = run_root / "underlying" / f"{sequence:04d}-before.json"
    if (
        route.decision_id != f"route-{run_id}-{sequence:04d}"
        or (route.run_id, route.job_id, route.execution_mode) != (run_id, job_id, "aq")
        or route.bundle_manifest != _artifact_for(root, run_root / "bundle.json")
        or route.source_state != _artifact_for(root, expected_source)
    ):
        raise ValueError("pending AQ route identity or source binding is stale")
    source_state = json.loads(
        _validate_artifact(root, route.source_state).read_text(encoding="utf-8")
    )
    if not isinstance(source_state, dict):
        raise ValueError("pending AQ route source is not an AQ state object")
    source_status = {
        "status": source_public_status,
        "base_autonomy": {
            "state": source_state,
            "state_artifact": route.source_state.model_dump(mode="json"),
        },
    }
    expected_key, expected_reason = _aq_route_key(root, source_status)
    expected_skill = _route_from_registry(
        bundle,
        registry,
        execution_mode="aq",
        route_key=expected_key,
    )
    if (
        route.stage_key != expected_key
        or route.selected_skill_id != expected_skill
        or route.reason != expected_reason
    ):
        raise ValueError("pending AQ route differs from its exact source state")
    return route_artifact, route


def _update_aq_adapter_state(
    root: Path,
    run_root: Path,
    adapter_state: AQSkillAdapterState,
    *,
    after_status: dict[str, object],
    after_snapshot: SkillArtifact,
    receipt: SkillArtifact,
    bundle: SkillBundleManifest,
    registry: SkillRegistry,
) -> AQSkillAdapterState:
    """Refresh the derived adapter projection from one receipt-backed AQ observation."""

    after_key, _after_reason = _aq_route_key(root, after_status)
    after_skill = _route_from_registry(
        bundle,
        registry,
        execution_mode="aq",
        route_key=after_key,
    )
    after_state, _after_artifact = _aq_base_state(after_status)
    updated = adapter_state.model_copy(
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
    _write_aq_state(run_root, updated)
    return updated


def _aq_recovery_package_acceptances(
    root: Path,
    job_id: str,
    relative_paths: list[str] | None,
    *,
    expected_source_fingerprint: str | None = None,
) -> list[SkillArtifact]:
    """Validate explicitly named package acceptances and all exact evidence they bind."""

    artifacts: list[SkillArtifact] = []
    for relative_path in relative_paths or []:
        path = _contained_file(root, relative_path)
        acceptance = PortablePackageAcceptance.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        expected_path = (
            root
            / "optimization"
            / "runs"
            / acceptance.run_id
            / "package_acceptances"
            / acceptance.package_id
            / "acceptance.json"
        )
        if path != expected_path.resolve(strict=True):
            raise ValueError("AQ recovery package acceptance path differs from its identity")
        if (
            acceptance.job_id != job_id
            or not acceptance.consumed
            or not acceptance.canonical_unchanged
            or acceptance.destination_project_modified
        ):
            raise ValueError("AQ recovery package acceptance is not exact and non-mutating")
        if (
            expected_source_fingerprint is not None
            and acceptance.source_fingerprint != expected_source_fingerprint
        ):
            raise ValueError("AQ recovery package acceptance uses a different source freeze")
        manifest = _contained_file(root, acceptance.package_manifest_path)
        roundtrip = _contained_file(root, acceptance.roundtrip_validation_path)
        if (
            sha256_file(manifest) != acceptance.package_manifest_sha256
            or sha256_file(roundtrip) != acceptance.roundtrip_validation_sha256
        ):
            raise ValueError("AQ recovery package acceptance evidence changed")
        artifacts.append(_artifact_for(root, path))
    if len(artifacts) != len({(item.path, item.sha256) for item in artifacts}):
        raise ValueError("AQ recovery package acceptance paths must be unique")
    return artifacts


def _publish_aq_adapter_terminal(
    root: Path,
    run_root: Path,
    plan: AQSkillAdapterPlan,
    adapter_state: AQSkillAdapterState,
    one_prompt_status: dict[str, object],
) -> AQSkillAdapterTerminal | None:
    """Publish one immutable adapter terminal for an exact One-Prompt terminal."""

    if str(one_prompt_status.get("status")) != "terminal":
        return None
    terminal_payload = one_prompt_status.get("terminal")
    if not isinstance(terminal_payload, dict):
        raise ValueError("terminal One-Prompt status omitted its exact terminal")
    one_prompt_terminal = AQV2OnePromptRunTerminal.model_validate_json(
        json.dumps(terminal_payload)
    )
    one_prompt_path = (
        root
        / "production"
        / "autonomy_v2"
        / plan.session_id
        / "approval_envelope"
        / "one_prompt"
        / "terminal.json"
    )
    one_prompt_artifact = _artifact_for(root, one_prompt_path)
    final_aq_state = SkillArtifact(
        path=one_prompt_terminal.final_autonomy_state.path,
        sha256=one_prompt_terminal.final_autonomy_state.sha256,
    )
    _validate_artifact(root, final_aq_state)
    if (
        one_prompt_terminal.job_id != plan.job_id
        or one_prompt_terminal.session_id != plan.session_id
        or one_prompt_terminal.one_prompt_plan.path != plan.one_prompt_plan.path
        or one_prompt_terminal.one_prompt_plan.sha256 != plan.one_prompt_plan.sha256
    ):
        raise ValueError("One-Prompt terminal differs from the AQ skill plan")
    source_state = _aq_source_artifact(root, one_prompt_status)
    if source_state != final_aq_state:
        raise ValueError("One-Prompt terminal does not bind the current exact AQ state")
    terminal_path = run_root / "terminal.json"
    if terminal_path.is_file():
        existing = AQSkillAdapterTerminal.model_validate_json(
            terminal_path.read_text(encoding="utf-8")
        )
        if existing.recovery_package_acceptances:
            raise ValueError("ordinary AQ adapter terminal cannot carry recovery evidence")
        return existing
    terminal_state = adapter_state.model_copy(
        update={
            "status": "terminal",
            "source_state": final_aq_state,
            "next_action": None,
            "updated_at": _utc_now(),
        }
    )
    _write_aq_state(run_root, terminal_state)
    terminal_type = one_prompt_terminal.terminal_type
    candidate = terminal_type in {"production_delivery", "review_bundle"}
    reason = {
        "production_delivery": "One-Prompt published exact production-delivery evidence.",
        "review_bundle": "One-Prompt published an exact review-bundle terminal.",
        "genuine_escalation": "One-Prompt stopped at one consolidated genuine escalation.",
        "blocked": "One-Prompt preserved a fail-closed technical terminal.",
        "cancelled": "One-Prompt was explicitly cancelled.",
    }[terminal_type]
    terminal = AQSkillAdapterTerminal(
        terminal_id=f"terminal-{plan.run_id}",
        run_id=plan.run_id,
        job_id=plan.job_id,
        session_id=plan.session_id,
        plan=_artifact_for(root, run_root / "plan.json"),
        final_state=_state_artifact(root, run_root),
        final_aq_state=final_aq_state,
        authoritative_aq_terminal=one_prompt_artifact,
        one_prompt_terminal=one_prompt_artifact,
        terminal_type=terminal_type,
        campaign_terminal_candidate=candidate,
        reason=reason,
        created_at=_utc_now(),
    )
    _publish_model(root, terminal_path, terminal)
    return terminal


def _historical_aq_one_prompt_projection(
    job_id: str,
    session_id: str,
) -> dict[str, object]:
    """Expose an expired One-Prompt session read-only through its validated AQ chain."""

    base = get_autonomy_v2_status(job_id, session_id)
    return {
        "status": "historical_authorization_expired",
        "profile_status": "disabled_experimental",
        "job_id": job_id,
        "session_id": session_id,
        "base_autonomy": base,
        "terminal": None,
        "resume_same_state_budget_assignment": False,
        "repository_creates_codex_task": False,
        "app_close_background_execution": False,
    }


def _publish_reconciled_failed_aq_terminal(
    root: Path,
    run_root: Path,
    plan: AQSkillAdapterPlan,
    adapter_state: AQSkillAdapterState,
    base_status: dict[str, object],
    *,
    recovery_package_acceptance_paths: list[str],
) -> AQSkillAdapterTerminal:
    """Bind a historical failed AQ terminal to later exact recovery acceptance evidence."""

    state = base_status.get("state")
    state_artifact_payload = base_status.get("state_artifact")
    if not isinstance(state, dict) or not isinstance(state_artifact_payload, dict):
        raise ValueError("historical AQ status omitted its exact current state")
    if state.get("status") != "failed" or state.get("next_action") != "none":
        raise ValueError("historical AQ reconciliation requires a failed terminal state")
    final_aq_state = SkillArtifact(
        path=str(state_artifact_payload.get("path", "")),
        sha256=str(state_artifact_payload.get("sha256", "")),
    )
    _validate_artifact(root, final_aq_state)
    delivery_payload = state.get("delivery_terminal")
    if not isinstance(delivery_payload, dict):
        raise ValueError("historical AQ failure omitted its delivery terminal")
    delivery_artifact = SkillArtifact(
        path=str(delivery_payload.get("path", "")),
        sha256=str(delivery_payload.get("sha256", "")),
    )
    delivery = _load_model(root, delivery_artifact, DeliveryTerminalV2)
    if (
        delivery.job_id != plan.job_id
        or delivery.session_id != plan.session_id
        or delivery.outcome != "failed"
        or not delivery.canonical_unchanged
    ):
        raise ValueError("historical AQ delivery terminal is not the exact failed source")
    source_freeze = SkillArtifact(
        path=delivery.source_freeze.path,
        sha256=delivery.source_freeze.sha256,
    )
    freeze = _load_model(root, source_freeze, QualityApprovedSourceFreeze)
    recoveries = _aq_recovery_package_acceptances(
        root,
        plan.job_id,
        recovery_package_acceptance_paths,
        expected_source_fingerprint=freeze.v07_source_fingerprint,
    )
    terminal_path = run_root / "terminal.json"
    if terminal_path.is_file():
        existing = AQSkillAdapterTerminal.model_validate_json(
            terminal_path.read_text(encoding="utf-8")
        )
        if (
            existing.terminal_type != "reconciled_failed_recovery"
            or existing.authoritative_aq_terminal != delivery_artifact
            or existing.final_aq_state != final_aq_state
            or existing.recovery_package_acceptances != recoveries
        ):
            raise ValueError("historical AQ adapter terminal reconciliation is immutable")
        return existing
    if adapter_state.status != "terminal" or adapter_state.next_action is not None:
        raise ValueError("historical AQ adapter state was not closed before terminal publication")
    terminal = AQSkillAdapterTerminal(
        terminal_id=f"terminal-{plan.run_id}",
        run_id=plan.run_id,
        job_id=plan.job_id,
        session_id=plan.session_id,
        plan=_artifact_for(root, run_root / "plan.json"),
        final_state=_state_artifact(root, run_root),
        final_aq_state=final_aq_state,
        authoritative_aq_terminal=delivery_artifact,
        terminal_type="reconciled_failed_recovery",
        recovery_package_acceptances=recoveries,
        campaign_terminal_candidate=False,
        reason=(
            "The original failed AQ delivery remains unchanged; exact later package "
            "acceptance closes only the stale adapter projection."
        ),
        created_at=_utc_now(),
    )
    _publish_model(root, terminal_path, terminal)
    return terminal


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
        sequence = _receipt_sequence(run_root)
        bundle, registry = _load_bundle(root, run_root)
        pending = _load_pending_aq_route(
            root,
            run_root,
            run_id=run_id,
            job_id=job_id,
            bundle=bundle,
            registry=registry,
            source_public_status=adapter_state.status,
        )
        if pending is not None:
            route, decision = pending
            after_snapshot = _snapshot_aq_state_exact(
                root,
                run_root,
                sequence=sequence,
                label="after-recovery",
                source_artifact=_aq_source_artifact(root, before_status),
            )
            source_unchanged = decision.source_state.sha256 == after_snapshot.sha256
            receipt = _publish_execution_receipt(
                root,
                run_root,
                run_id=run_id,
                job_id=job_id,
                sequence=sequence,
                route=route,
                before=_aq_binding_from_snapshot(
                    root,
                    plan.session_id,
                    decision.source_state,
                    status=adapter_state.status,
                ),
                after=_aq_binding(
                    plan.session_id,
                    after_snapshot,
                    before_status,
                ),
                outcome="failed" if source_unchanged else _aq_outcome(before_status),
            )
            adapter_state = _update_aq_adapter_state(
                root,
                run_root,
                adapter_state,
                after_status=before_status,
                after_snapshot=after_snapshot,
                receipt=receipt,
                bundle=bundle,
                registry=registry,
            )
            _publish_aq_adapter_terminal(
                root,
                run_root,
                plan,
                adapter_state,
                before_status,
            )
            response = get_aq_one_prompt_skill_status(job_id, run_id)
            response["recovered_pending_route"] = True
            return response
        if (
            str(before_status.get("status")) == "terminal"
            and adapter_state.status == "terminal"
        ):
            _publish_aq_adapter_terminal(
                root,
                run_root,
                plan,
                adapter_state,
                before_status,
            )
            return get_aq_one_prompt_skill_status(job_id, run_id)
        before_snapshot = _snapshot_aq_state_exact(
            root,
            run_root,
            sequence=sequence,
            label="before",
            source_artifact=_aq_source_artifact(root, before_status),
        )
        route_key, route_reason = _aq_route_key(root, before_status)
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
        if str(before_status.get("status")) == "terminal":
            after_snapshot = _snapshot_aq_state_exact(
                root,
                run_root,
                sequence=sequence,
                label="after",
                source_artifact=_aq_source_artifact(root, before_status),
            )
            receipt = _publish_execution_receipt(
                root,
                run_root,
                run_id=run_id,
                job_id=job_id,
                sequence=sequence,
                route=route,
                before=_aq_binding(plan.session_id, before_snapshot, before_status),
                after=_aq_binding(plan.session_id, after_snapshot, before_status),
                outcome=_aq_outcome(before_status),
            )
            adapter_state = _update_aq_adapter_state(
                root,
                run_root,
                adapter_state,
                after_status=before_status,
                after_snapshot=after_snapshot,
                receipt=receipt,
                bundle=bundle,
                registry=registry,
            )
            _publish_aq_adapter_terminal(
                root,
                run_root,
                plan,
                adapter_state,
                before_status,
            )
            return get_aq_one_prompt_skill_status(job_id, run_id)
        executor = (
            resume_one_prompt
            if adapter_state.receipt_chain_head_sha256 is not None
            else run_one_prompt
        )
        try:
            result = executor(
                job_id,
                plan.session_id,
                max_actions=max_actions,
                quality_submission=quality_submission,
                allow_disabled_experimental=True,
            )
        except Exception:
            after_status = get_one_prompt_status(job_id, plan.session_id)
            after_snapshot = _snapshot_aq_state_exact(
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
                outcome=(
                    "failed"
                    if before_snapshot.sha256 == after_snapshot.sha256
                    else _aq_outcome(after_status)
                ),
            )
            adapter_state = _update_aq_adapter_state(
                root,
                run_root,
                adapter_state,
                after_status=after_status,
                after_snapshot=after_snapshot,
                receipt=receipt,
                bundle=bundle,
                registry=registry,
            )
            _publish_aq_adapter_terminal(
                root,
                run_root,
                plan,
                adapter_state,
                after_status,
            )
            raise
        after_status = get_one_prompt_status(job_id, plan.session_id)
        after_snapshot = _snapshot_aq_state_exact(
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
        adapter_state = _update_aq_adapter_state(
            root,
            run_root,
            adapter_state,
            after_status=after_status,
            after_snapshot=after_snapshot,
            receipt=receipt,
            bundle=bundle,
            registry=registry,
        )
        _publish_aq_adapter_terminal(
            root,
            run_root,
            plan,
            adapter_state,
            after_status,
        )
        response = get_aq_one_prompt_skill_status(job_id, run_id)
        response["last_one_prompt_result"] = result
        return response


def resume_aq_one_prompt_skill(
    job_id: str,
    run_id: str,
    *,
    max_actions: int = 32,
    quality_submission: dict[str, object] | None = None,
    human_quality_disposition_path: str | Path | None = None,
    experimental_opt_in: bool = False,
) -> dict[str, object]:
    """Resume the same AQ run and optionally close one exact human review terminal."""

    if not experimental_opt_in:
        raise PermissionError("AQ skill adapter remains disabled_experimental")
    _root, _run_root, plan, _adapter_state = _load_aq_run(job_id, run_id)
    if human_quality_disposition_path is not None:
        close_human_quality_review_v2(
            job_id,
            plan.session_id,
            skill_run_id=run_id,
            human_quality_disposition_path=human_quality_disposition_path,
            allow_disabled_experimental=True,
        )
    return run_aq_one_prompt_skill(
        job_id,
        run_id,
        max_actions=max_actions,
        quality_submission=quality_submission,
        experimental_opt_in=True,
    )


def reconcile_aq_one_prompt_skill_terminal(
    job_id: str,
    run_id: str,
    *,
    recovery_package_acceptance_paths: list[str],
    experimental_opt_in: bool = False,
) -> dict[str, object]:
    """Close one stale failed AQ adapter from exact append-only recovery evidence."""

    if not experimental_opt_in:
        raise PermissionError("AQ skill adapter remains disabled_experimental")
    if not recovery_package_acceptance_paths:
        raise ValueError("AQ terminal reconciliation requires recovery package acceptance")
    root, run_root, plan, adapter_state = _load_aq_run(job_id, run_id)
    with _skill_run_lock(run_root):
        root, run_root, plan, adapter_state = _load_aq_run(job_id, run_id)
        base_status = get_autonomy_v2_status(job_id, plan.session_id)
        state = base_status.get("state")
        state_artifact_payload = base_status.get("state_artifact")
        if not isinstance(state, dict) or not isinstance(state_artifact_payload, dict):
            raise ValueError("AQ terminal reconciliation omitted its exact base state")
        if state.get("status") != "failed" or state.get("next_action") != "none":
            raise ValueError("AQ terminal reconciliation accepts only a failed terminal")
        current_source = SkillArtifact(
            path=str(state_artifact_payload.get("path", "")),
            sha256=str(state_artifact_payload.get("sha256", "")),
        )
        _validate_artifact(root, current_source)
        terminal_path = run_root / "terminal.json"
        if terminal_path.is_file():
            _publish_reconciled_failed_aq_terminal(
                root,
                run_root,
                plan,
                adapter_state,
                base_status,
                recovery_package_acceptance_paths=(
                    recovery_package_acceptance_paths
                ),
            )
            return get_aq_one_prompt_skill_status(job_id, run_id)
        sequence = _receipt_sequence(run_root)
        bundle, registry = _load_bundle(root, run_root)
        projected_status = {
            "status": "historical_authorization_expired",
            "base_autonomy": base_status,
        }
        pending = _load_pending_aq_route(
            root,
            run_root,
            run_id=run_id,
            job_id=job_id,
            bundle=bundle,
            registry=registry,
            source_public_status="historical_authorization_expired",
        )
        if pending is None:
            before_snapshot = _snapshot_aq_state_exact(
                root,
                run_root,
                sequence=sequence,
                label="before",
                source_artifact=current_source,
            )
            route_key, route_reason = _aq_route_key(root, projected_status)
            selected_skill = _route_from_registry(
                bundle,
                registry,
                execution_mode="aq",
                route_key=route_key,
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
        else:
            route, decision = pending
            before_snapshot = decision.source_state
            route_key = decision.stage_key
            selected_skill = decision.selected_skill_id
        after_snapshot = _snapshot_aq_state_exact(
            root,
            run_root,
            sequence=sequence,
            label="after-reconciliation",
            source_artifact=current_source,
        )
        receipt = _publish_execution_receipt(
            root,
            run_root,
            run_id=run_id,
            job_id=job_id,
            sequence=sequence,
            route=route,
            before=_aq_binding_from_snapshot(
                root,
                plan.session_id,
                before_snapshot,
                status="failed",
            ),
            after=_aq_binding(
                plan.session_id,
                after_snapshot,
                projected_status,
            ),
            outcome="failed",
        )
        adapter_state = adapter_state.model_copy(
            update={
                "status": "terminal",
                "current_stage_key": route_key,
                "current_skill_id": selected_skill,
                "source_state": after_snapshot,
                "next_action": None,
                "receipt_chain_head_sha256": receipt.sha256,
                "updated_at": _utc_now(),
            }
        )
        _write_aq_state(run_root, adapter_state)
        _publish_reconciled_failed_aq_terminal(
            root,
            run_root,
            plan,
            adapter_state,
            base_status,
            recovery_package_acceptance_paths=recovery_package_acceptance_paths,
        )
        return get_aq_one_prompt_skill_status(job_id, run_id)


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
        _publish_aq_adapter_terminal(
            root,
            run_root,
            plan,
            adapter_state,
            after_status,
        )
        return get_aq_one_prompt_skill_status(job_id, run_id)


def get_aq_one_prompt_skill_status(job_id: str, run_id: str) -> dict[str, object]:
    """Read the AQ adapter and exact One-Prompt status without advancing either."""

    root, run_root, plan, state = _load_aq_run(job_id, run_id)
    terminal = None
    terminal_path = run_root / "terminal.json"
    if terminal_path.is_file():
        terminal_model = AQSkillAdapterTerminal.model_validate_json(
            terminal_path.read_text(encoding="utf-8")
        )
        terminal_artifacts = [
            terminal_model.plan,
            terminal_model.final_state,
            terminal_model.final_aq_state,
            terminal_model.authoritative_aq_terminal,
            *terminal_model.recovery_package_acceptances,
        ]
        if terminal_model.one_prompt_terminal is not None:
            terminal_artifacts.append(terminal_model.one_prompt_terminal)
        for artifact in terminal_artifacts:
            _validate_artifact(root, artifact)
        if (
            terminal_model.job_id != job_id
            or terminal_model.run_id != run_id
            or terminal_model.session_id != plan.session_id
            or terminal_model.final_state != _state_artifact(root, run_root)
            or state.status != "terminal"
            or state.next_action is not None
        ):
            raise ValueError("AQ adapter terminal differs from its current projection")
        terminal = terminal_model.model_dump(mode="json")
    try:
        one_prompt = get_one_prompt_status(job_id, plan.session_id)
    except PermissionError as exc:
        if str(exc) != "approval envelope has expired":
            raise
        one_prompt = _historical_aq_one_prompt_projection(job_id, plan.session_id)
    return {
        "status": state.status,
        "profile_status": "disabled_experimental",
        "job_id": job_id,
        "run_id": run_id,
        "session_id": plan.session_id,
        "entry_skill_id": _AQ_ENTRY,
        "plan": plan.model_dump(mode="json"),
        "state": state.model_dump(mode="json"),
        "terminal": terminal,
        "one_prompt": one_prompt,
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
    "reconcile_aq_one_prompt_skill_terminal",
    "resume_aq_one_prompt_skill",
    "resume_standard_asset_cycle",
    "run_aq_one_prompt_skill",
    "run_standard_asset_cycle",
]
