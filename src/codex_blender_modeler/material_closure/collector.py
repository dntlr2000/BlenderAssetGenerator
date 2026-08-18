"""Fail-closed collection of declared Material Closure inputs from one job root."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Collection
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ValidationError

from ..analysis.models import ModelingPlan
from ..blender_artifacts import native_io_path
from ..codex_imagegen.material_loop_models import (
    CodexImageCompanionSelectionReceipt,
    CodexImageSemanticReview,
    ImageGenNativeNormalizationPlan,
    ImageGenNativeNormalizationReceipt,
)
from ..codex_imagegen.models import (
    CodexBuiltinImageProviderProfile,
    CodexGeneratedImageEvidence,
    CodexImageGenerationAssignment,
    CodexImageGenerationCompletion,
    CodexImageGenerationSelection,
    ImageToMaterialAdoption,
)
from ..material_authoring.codex_image_models import (
    CodexImageAuthoredMaterialManifestV021,
    CodexImageMaterialAuthoringReceiptV021,
    CodexImageMaterialAuthoringRequestV021,
)
from ..material_authoring.codex_image_normalized_models import (
    CodexImageNormalizedAuthoredMaterialManifestV010,
    CodexImageNormalizedMaterialAuthoringReceiptV010,
    CodexImageNormalizedMaterialAuthoringRequestV010,
)
from ..material_graph.models import MaterialGraphSpec
from ..materials.models import MaterialPlan, ShaderRecipe
from ..models import SceneSpec
from ..production.controller_executor.models import PhaseToolProfile
from ..texturing.models import TextureManifest
from .graph_rebinding import apply_material_graph_rebinding
from .models import (
    ExactArtifact,
    MaterialCanonicalMaterialPlanAbsence,
    MaterialClosureIssue,
    MaterialClosureSourceBinding,
    MaterialClosureSourceBindingArtifact,
    MaterialDependencyClosure,
    MaterialDependencyEntry,
    MaterialGraphRebindingPlan,
    MaterialGraphRebindingReceipt,
    MaterialPlannedOutput,
    _closure_payload_digest,
    material_plan_absence_context_sha256,
)


class MaterialClosureCollectionError(ValueError):
    """Expose all deterministic dependency failures without publishing a partial closure."""

    def __init__(self, issues: list[MaterialClosureIssue]) -> None:
        """Store a stable issue list for failure-report construction."""

        self.issues = issues
        super().__init__("; ".join(f"{item.code}: {item.message}" for item in issues))


MaterialClosureCollectionBinding = MaterialClosureSourceBindingArtifact

_TYPED_IMAGEGEN_MODELS: dict[str, tuple[type[Any], ...]] = {
    "imagegen_provider_profile": (CodexBuiltinImageProviderProfile,),
    "imagegen_assignment": (CodexImageGenerationAssignment,),
    "imagegen_completion": (CodexImageGenerationCompletion,),
    "imagegen_generated_image_evidence": (CodexGeneratedImageEvidence,),
    "imagegen_normalization_plan": (ImageGenNativeNormalizationPlan,),
    "imagegen_normalization_receipt": (ImageGenNativeNormalizationReceipt,),
    "imagegen_semantic_review": (CodexImageSemanticReview,),
    "imagegen_selection_receipt": (
        CodexImageCompanionSelectionReceipt,
        CodexImageGenerationSelection,
    ),
    "image_to_material_adoption": (ImageToMaterialAdoption,),
    "material_authoring_request": (
        CodexImageNormalizedMaterialAuthoringRequestV010,
        CodexImageMaterialAuthoringRequestV021,
    ),
    "material_authoring_manifest": (
        CodexImageNormalizedAuthoredMaterialManifestV010,
        CodexImageAuthoredMaterialManifestV021,
    ),
    "material_authoring_receipt": (
        CodexImageNormalizedMaterialAuthoringReceiptV010,
        CodexImageMaterialAuthoringReceiptV021,
    ),
}


def _is_manifest_dependency_link_like(path: Path) -> bool:
    """Detect link-like metadata with one non-following filesystem read."""

    native = native_io_path(path)
    try:
        metadata = os.lstat(native)
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attributes & reparse_flag:
        return True
    return stat.S_ISLNK(metadata.st_mode)


def sha256_file(path: Path) -> str:
    """Hash one regular file without interpreting its contents."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def material_plan_parent_fingerprint(job_root: Path) -> str:
    """Fingerprint every non-link entry below the canonical MaterialPlan parent."""

    root = job_root.resolve(strict=True)
    parent = root / "analysis"
    try:
        resolved_parent = parent.resolve(strict=True)
        resolved_parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_MATERIAL_PLAN_PARENT",
                    message="canonical MaterialPlan parent is missing or escapes the job",
                    path="analysis",
                )
            ]
        ) from exc
    if parent.is_symlink() or not resolved_parent.is_dir():
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_MATERIAL_PLAN_PARENT",
                    message="canonical MaterialPlan parent must be a non-link directory",
                    path="analysis",
                )
            ]
        )
    records: list[dict[str, object]] = []
    pending = [resolved_parent]
    while pending:
        directory = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="UNREADABLE_MATERIAL_PLAN_PARENT",
                        message="canonical MaterialPlan parent cannot be enumerated",
                        path="analysis",
                    )
                ]
            ) from exc
        for child in children:
            relative = child.relative_to(root).as_posix()
            if relative.casefold() == "analysis/material_plan.json":
                raise MaterialClosureCollectionError(
                    [
                        MaterialClosureIssue(
                            code="CANONICAL_MATERIAL_PLAN_PRESENT",
                            message="canonical MaterialPlan exists; absence evidence is stale",
                            path=relative,
                        )
                    ]
                )
            if child.is_symlink():
                raise MaterialClosureCollectionError(
                    [
                        MaterialClosureIssue(
                            code="MATERIAL_PLAN_PARENT_LINK",
                            message="MaterialPlan parent fingerprint rejects links",
                            path=relative,
                        )
                    ]
                )
            if child.is_dir():
                records.append({"kind": "directory", "path": relative})
                pending.append(child)
            elif child.is_file():
                records.append(
                    {
                        "kind": "file",
                        "path": relative,
                        "sha256": sha256_file(child),
                        "byte_size": child.stat().st_size,
                    }
                )
            else:
                raise MaterialClosureCollectionError(
                    [
                        MaterialClosureIssue(
                            code="MATERIAL_PLAN_PARENT_SPECIAL_FILE",
                            message="MaterialPlan parent fingerprint rejects special files",
                            path=relative,
                        )
                    ]
                )
    encoded = json.dumps(
        sorted(records, key=lambda item: (str(item["path"]), str(item["kind"]))),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json_object(job_root: Path, relative_path: str) -> dict[str, Any]:
    """Read one contained non-link JSON object without accepting path escape."""

    root = job_root.resolve(strict=True)
    candidate = root.joinpath(*relative_path.split("/"))
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_ROOT_ARTIFACT",
                    message="root artifact is missing or escapes the job",
                    path=relative_path,
                )
            ]
        ) from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_ROOT_ARTIFACT",
                    message="root artifact must be a regular non-link file",
                    path=relative_path,
                )
            ]
        )
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_ROOT_ARTIFACT",
                    message="root artifact is not valid UTF-8 JSON",
                    path=relative_path,
                )
            ]
        ) from exc
    if not isinstance(payload, dict):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_ROOT_ARTIFACT",
                    message="root artifact JSON must be an object",
                    path=relative_path,
                )
            ]
        )
    return payload


def _entry_from_path(
    job_root: Path,
    *,
    role: str,
    path: str,
    source_kind: str,
    ownership: str,
    producer: str,
    dependency_parent: str | None = None,
    material_id: str | None = None,
) -> MaterialDependencyEntry:
    """Create one exact entry from host-observed current file bytes."""

    root = job_root.resolve(strict=True)
    candidate = root.joinpath(*path.split("/"))
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="MISSING_DEPENDENCY",
                    message=f"host-derived dependency is missing for role {role}",
                    path=path,
                )
            ]
        ) from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="UNSUPPORTED_DEPENDENCY_FILE",
                    message=f"host-derived dependency is not a contained regular file: {role}",
                    path=path,
                )
            ]
        )
    digest = sha256_file(resolved)
    identity = role.encode("utf-8") + b"\0" + path.encode("utf-8")
    entry_id = f"dep-{hashlib.sha256(identity).hexdigest()[:20]}"
    return MaterialDependencyEntry(
        entry_id=entry_id,
        role=role,
        path=path,
        sha256=digest,
        byte_size=resolved.stat().st_size,
        source_kind=source_kind,
        required=True,
        producer=producer,
        dependency_parent=dependency_parent,
        material_id=material_id,
        ownership=ownership,
    )


def _resolve_manifest_owned_dependency_path(
    job_root: Path,
    *,
    manifest_path: str,
    declared_path: str,
) -> str:
    """Resolve one TextureManifest-owned path from its manifest parent, fail closed."""

    raw_parts = declared_path.split("/")
    declared = PurePosixPath(declared_path)
    if (
        not declared_path
        or "\\" in declared_path
        or ":" in declared_path
        or declared.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_MANIFEST_DEPENDENCY_PATH",
                    message="TextureManifest-owned dependency path must be relative and normalized",
                    path=manifest_path,
                )
            ]
        )
    relative = (PurePosixPath(manifest_path).parent / declared).as_posix()
    root = job_root.resolve(strict=True)
    candidate = root.joinpath(*relative.split("/"))
    current = root
    for part in relative.split("/"):
        current = current / part
        if _is_manifest_dependency_link_like(current):
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="MANIFEST_DEPENDENCY_LINK",
                        message="TextureManifest-owned dependency path rejects links",
                        path=relative,
                    )
                ]
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_MANIFEST_DEPENDENCY_PATH",
                    message="TextureManifest-owned dependency is missing or escapes the job",
                    path=relative,
                )
            ]
        ) from exc
    if not resolved.is_file():
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_MANIFEST_DEPENDENCY_PATH",
                    message="TextureManifest-owned dependency must be a regular file",
                    path=relative,
                )
            ]
        )
    return relative


def _add_path(
    job_root: Path,
    entries: dict[str, MaterialDependencyEntry],
    *,
    role: str,
    path: str,
    source_kind: str,
    ownership: str,
    producer: str,
    dependency_parent: str | None = None,
    material_id: str | None = None,
    expected_sha256: str | None = None,
) -> None:
    """Insert one host-derived path once and reject conflicting embedded digests."""

    entry = _entry_from_path(
        job_root,
        role=role,
        path=path,
        source_kind=source_kind,
        ownership=ownership,
        producer=producer,
        dependency_parent=dependency_parent,
        material_id=material_id,
    )
    if expected_sha256 is not None and entry.sha256 != expected_sha256:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="STALE_EMBEDDED_HASH",
                    message=f"embedded hash is stale for role {role}",
                    path=path,
                )
            ]
        )
    prior = entries.get(path)
    if prior is not None and prior.sha256 != entry.sha256:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="CONFLICTING_PATH_HASH",
                    message="one dependency path resolved to conflicting hashes",
                    path=path,
                )
            ]
        )
    if prior is None:
        entries[path] = entry


def validate_exact_artifact_current(
    job_root: Path,
    artifact: ExactArtifact,
    *,
    role: str,
) -> None:
    """Rehash one exact artifact and reject stale observation-context bytes."""

    observed = _entry_from_path(
        job_root,
        role=role,
        path=artifact.path,
        source_kind="canonical_artifact",
        ownership="canonical",
        producer="material_closure_absence_validator",
    )
    if (observed.sha256, observed.byte_size) != (
        artifact.sha256,
        artifact.byte_size,
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="STALE_MATERIAL_PLAN_ABSENCE_CONTEXT",
                    message=f"MaterialPlan absence {role} bytes changed",
                    path=artifact.path,
                )
            ]
        )


def validate_material_plan_absence_evidence(
    job_root: Path,
    absence: MaterialCanonicalMaterialPlanAbsence,
    *,
    source_binding: MaterialClosureSourceBindingArtifact | None = None,
) -> None:
    """Prove exact state, scene, blend, parent bytes, and continued canonical absence."""

    if source_binding is not None:
        expected_scope = (
            source_binding.job_id,
            source_binding.workflow_id,
            source_binding.dispatch_id,
            source_binding.session_id,
        )
        observed_scope = (
            absence.job_id,
            absence.workflow_id,
            absence.dispatch_id,
            absence.session_id,
        )
        if observed_scope != expected_scope:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="MATERIAL_PLAN_ABSENCE_SCOPE_MISMATCH",
                        message="MaterialPlan absence belongs to another workflow session",
                        path=absence.canonical_path,
                    )
                ]
            )
        if absence.canonical_scene_spec.path != source_binding.scene_spec_path:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="MATERIAL_PLAN_ABSENCE_SCENE_MISMATCH",
                        message="MaterialPlan absence binds another canonical SceneSpec",
                        path=absence.canonical_scene_spec.path,
                    )
                ]
            )
    for role, artifact in (
        ("observation_state", absence.observation_state),
        ("canonical_scene_spec", absence.canonical_scene_spec),
        ("canonical_blend", absence.canonical_blend),
    ):
        validate_exact_artifact_current(job_root, artifact, role=role)
    observed_parent = material_plan_parent_fingerprint(job_root)
    if observed_parent != absence.filesystem_parent_fingerprint:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="STALE_MATERIAL_PLAN_PARENT_FINGERPRINT",
                    message="canonical MaterialPlan parent contents changed after observation",
                    path="analysis",
                )
            ]
        )


def build_material_plan_absence_evidence(
    *,
    job_root: Path,
    absence_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    producer: str,
    producer_version: str,
    created_at: datetime,
    observation_state: ExactArtifact,
    canonical_scene_spec: ExactArtifact,
    canonical_blend: ExactArtifact,
) -> MaterialCanonicalMaterialPlanAbsence:
    """Build a strict no-write observation after rehashing current canonical context."""

    for role, artifact in (
        ("observation_state", observation_state),
        ("canonical_scene_spec", canonical_scene_spec),
        ("canonical_blend", canonical_blend),
    ):
        validate_exact_artifact_current(job_root, artifact, role=role)
    parent_fingerprint = material_plan_parent_fingerprint(job_root)
    context_sha256 = material_plan_absence_context_sha256(
        absence_id=absence_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        observation_state=observation_state,
        canonical_scene_spec=canonical_scene_spec,
        canonical_blend=canonical_blend,
        filesystem_parent_fingerprint=parent_fingerprint,
    )
    return MaterialCanonicalMaterialPlanAbsence(
        absence_id=absence_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        producer=producer,
        producer_version=producer_version,
        created_at=created_at,
        observation_state=observation_state,
        observation_context_sha256=context_sha256,
        canonical_scene_spec=canonical_scene_spec,
        canonical_blend=canonical_blend,
        filesystem_parent_fingerprint=parent_fingerprint,
    )


def _iter_exact_artifact_refs(
    value: object,
    *,
    location: str = "$",
) -> list[tuple[str, str, str]]:
    """Recursively find strict path/hash artifact-shaped references in source evidence."""

    found: list[tuple[str, str, str]] = []
    if isinstance(value, dict):
        path = value.get("path")
        sha256 = value.get("sha256")
        if (
            isinstance(path, str)
            and isinstance(sha256, str)
            and len(sha256) == 64
            and all(character in "0123456789abcdef" for character in sha256)
        ):
            found.append((location, path, sha256))
        for key in sorted(value):
            found.extend(_iter_exact_artifact_refs(value[key], location=f"{location}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_iter_exact_artifact_refs(item, location=f"{location}[{index}]"))
    return found


def _iter_sized_exact_artifact_refs(
    value: object,
    *,
    location: str = "$",
) -> list[tuple[str, str, str, int]]:
    """Recursively enumerate artifact-shaped path/hash/size bindings from typed roots."""

    found: list[tuple[str, str, str, int]] = []
    if isinstance(value, BaseModel):
        return _iter_sized_exact_artifact_refs(value.model_dump(mode="json"), location=location)
    if isinstance(value, dict):
        path = value.get("path")
        sha256 = value.get("sha256")
        byte_size = value.get("byte_size")
        if (
            isinstance(path, str)
            and isinstance(sha256, str)
            and len(sha256) == 64
            and all(character in "0123456789abcdef" for character in sha256)
            and isinstance(byte_size, int)
            and byte_size >= 0
        ):
            found.append((location, path, sha256, byte_size))
        for key in sorted(value):
            found.extend(_iter_sized_exact_artifact_refs(value[key], location=f"{location}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_iter_sized_exact_artifact_refs(item, location=f"{location}[{index}]"))
    return found


def _exact_binding(value: object) -> tuple[str, str, int]:
    """Normalize one AQ/controller artifact into its exact byte identity."""

    path = getattr(value, "path", None)
    sha256 = getattr(value, "sha256", None)
    byte_size = getattr(value, "byte_size", None)
    if not isinstance(path, str) or not isinstance(sha256, str) or not isinstance(byte_size, int):
        raise TypeError("artifact does not expose an exact path/hash/size binding")
    return path, sha256, byte_size


def _entry_binding(entry: MaterialDependencyEntry) -> tuple[str, str, int]:
    """Project one closure entry into the same exact tuple as embedded artifacts."""

    return entry.path, entry.sha256, entry.byte_size


def _require_embedded_entry(
    *,
    artifact: object,
    entry: MaterialDependencyEntry,
    code: str,
    message: str,
) -> None:
    """Require an embedded artifact reference to equal the host-observed root bytes."""

    if _exact_binding(artifact) != _entry_binding(entry):
        raise MaterialClosureCollectionError(
            [MaterialClosureIssue(code=code, message=message, path=entry.path)]
        )


def _parse_common_root(
    job_root: Path,
    *,
    role: str,
    path: str,
    binding: MaterialClosureSourceBindingArtifact,
    expected_session_id: str,
) -> BaseModel:
    """Strict-dispatch one required AQ/controller root and enforce full identity."""

    # AQ v2's package initializer exposes material services that import this collector;
    # defer its leaf model imports until collection to keep public imports acyclic.
    from ..autonomy_v2.candidate_validation_models import (
        GeometryCandidateValidationReceiptV2,
    )
    from ..autonomy_v2.models import (
        AutonomyBudgetV2,
        AutonomyPlanV2,
        AutonomyProfileV2,
        RootAuthorizationV2,
    )

    model_types: dict[str, type[BaseModel]] = {
        "aq_root_authorization": RootAuthorizationV2,
        "aq_autonomy_plan": AutonomyPlanV2,
        "aq_autonomy_profile": AutonomyProfileV2,
        "aq_autonomy_budget": AutonomyBudgetV2,
        "material_phase_tool_profile": PhaseToolProfile,
        "geometry_candidate_validation_receipt": GeometryCandidateValidationReceiptV2,
    }
    model_type = model_types[role]
    try:
        parsed = model_type.model_validate_json(job_root.joinpath(*path.split("/")).read_bytes())
    except (OSError, ValidationError) as exc:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_COMMON_MATERIAL_ROOT",
                    message=f"{role} failed strict schema dispatch: {str(exc)[:1600]}",
                    path=path,
                )
            ]
        ) from exc
    expected = (
        str(binding.job_id),
        str(binding.workflow_id),
        str(binding.dispatch_id),
        expected_session_id,
    )
    observed = tuple(
        str(getattr(parsed, name))
        for name in ("job_id", "workflow_id", "dispatch_id", "session_id")
    )
    if observed != expected:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="COMMON_MATERIAL_ROOT_SCOPE_MISMATCH",
                    message=f"{role} belongs to another job/workflow/dispatch/session",
                    path=path,
                )
            ]
        )
    return parsed


def _contains_exact_artifact(items: list[object], expected: object) -> bool:
    """Return whether an artifact list contains one exact path/hash/size binding."""

    expected_binding = _exact_binding(expected)
    return any(_exact_binding(item) == expected_binding for item in items)


def _repair_source_matches_authority(
    repair_source: Any,
    authorization: Any,
    binding: MaterialClosureSourceBindingArtifact,
) -> bool:
    """Return whether repair lineage preserves the exact old request and material scope."""

    return bool(
        repair_source.primary_reference.path == binding.source_evidence.primary_reference_path
        and repair_source.uv_layout_fingerprint == binding.uv_layout_fingerprint
        and repair_source.target_subject == authorization.target_subject
        and repair_source.content_scope_sha256 == authorization.original_request_sha256
    )


def _repair_source_reuses_rollback_geometry(
    repair_source: Any,
    rollback_observation: Any,
) -> bool:
    """Require repair lineage to reuse the rollback observation's exact artifacts."""

    return bool(
        rollback_observation.source_session_id == repair_source.source_session_id
        and rollback_observation.geometry_validation_receipt
        == repair_source.geometry_approval_or_validation
        and rollback_observation.current_scene_spec == repair_source.scene_spec
        and rollback_observation.current_modeling_plan == repair_source.modeling_plan
        and rollback_observation.current_blend == repair_source.blend
    )


def _collect_rollback_restoration_dependencies(
    job_root: Path,
    entries: dict[str, MaterialDependencyEntry],
    *,
    observation: BaseModel,
    observation_path: str,
    producer: str,
) -> None:
    """Rehash and collect every exact artifact nested in a rollback observation."""

    observation_entry = entries.get(observation_path)
    if observation_entry is None:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="MISSING_REPAIR_ROLLBACK_RESTORATION",
                    message="rollback restoration wrapper is absent from the closure graph",
                    path=observation_path,
                )
            ]
        )
    for location, path, sha256, byte_size in _iter_sized_exact_artifact_refs(observation):
        _add_path(
            job_root,
            entries,
            role="material_rollback_restoration_dependency",
            path=path,
            source_kind="rollback_evidence",
            ownership="canonical",
            producer=producer,
            dependency_parent=observation_entry.entry_id,
            expected_sha256=sha256,
        )
        if entries[path].byte_size != byte_size:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="STALE_ROLLBACK_RESTORATION_BYTE_SIZE",
                        message=(f"rollback restoration artifact size is stale at {location}"),
                        path=path,
                    )
                ]
            )


def _require_repair_imagegen_root_listed(
    entry: MaterialDependencyEntry,
    reusable_bindings: set[tuple[str, str, int]],
) -> None:
    """Require one reusable ImageGen root to be exact-listed by repair lineage."""

    if _entry_binding(entry) not in reusable_bindings:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="UNLISTED_REPAIR_IMAGEGEN_EVIDENCE",
                    message="repair ImageGen root is not exact-listed by its source lineage",
                    path=entry.path,
                )
            ]
        )


def _validate_common_root_graph(
    job_root: Path,
    entries: dict[str, MaterialDependencyEntry],
    *,
    binding: MaterialClosureSourceBindingArtifact,
    producer: str,
) -> None:
    """Validate and recursively collect every required AQ/canonical material root."""

    # See _parse_common_root: imports stay local to avoid autonomy_v2 package cycles.
    from ..autonomy_v2.candidate_validation_models import (
        GeometryCandidateValidationReceiptV2,
    )
    from ..autonomy_v2.models import (
        AutonomyBudgetV2,
        AutonomyPlanV2,
        AutonomyProfileV2,
        RootAuthorizationV2,
    )
    from .models import (
        MaterialRepairSourceBinding,
        MaterialRollbackRestorationObservation,
    )

    repair_source: MaterialRepairSourceBinding | None = None
    rollback_observation: MaterialRollbackRestorationObservation | None = None
    expected_authority_session = str(binding.session_id)
    if binding.authority_mode == "material_repair_lineage":
        assert binding.repair_source_binding_path is not None
        try:
            repair_source = MaterialRepairSourceBinding.model_validate_json(
                job_root.joinpath(*binding.repair_source_binding_path.split("/")).read_bytes()
            )
        except (OSError, ValidationError) as exc:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="INVALID_MATERIAL_REPAIR_LINEAGE",
                        message=str(exc)[:1600],
                        path=binding.repair_source_binding_path,
                    )
                ]
            ) from exc
        if (
            str(repair_source.job_id),
            str(repair_source.workflow_id),
            str(repair_source.dispatch_id),
            str(repair_source.session_id),
        ) != (
            str(binding.job_id),
            str(binding.workflow_id),
            str(binding.dispatch_id),
            str(binding.session_id),
        ):
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="MATERIAL_REPAIR_LINEAGE_SCOPE_MISMATCH",
                        message="repair source binding targets another current repair session",
                        path=binding.repair_source_binding_path,
                    )
                ]
            )
        expected_authority_session = str(repair_source.source_session_id)
        if repair_source.latest_successful_rollback_receipt is None:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="MISSING_REPAIR_ROLLBACK_RESTORATION",
                        message="repair lineage requires exact successful rollback restoration",
                        path=binding.repair_source_binding_path,
                    )
                ]
            )
        rollback_artifact = repair_source.latest_successful_rollback_receipt
        try:
            rollback_observation = MaterialRollbackRestorationObservation.model_validate_json(
                job_root.joinpath(*rollback_artifact.path.split("/")).read_bytes()
            )
        except (OSError, ValidationError) as exc:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="INVALID_REPAIR_ROLLBACK_RESTORATION",
                        message=str(exc)[:1600],
                        path=rollback_artifact.path,
                    )
                ]
            ) from exc
        observed_rollback_path = job_root.joinpath(*rollback_artifact.path.split("/"))
        if (
            sha256_file(observed_rollback_path) != rollback_artifact.sha256
            or observed_rollback_path.stat().st_size != rollback_artifact.byte_size
            or not _repair_source_reuses_rollback_geometry(
                repair_source,
                rollback_observation,
            )
        ):
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="REPAIR_ROLLBACK_RESTORATION_MISMATCH",
                        message="rollback restoration does not bind current repair geometry",
                        path=rollback_artifact.path,
                    )
                ]
            )

    parsed = {
        role: _parse_common_root(
            job_root,
            role=role,
            path=path,
            binding=binding,
            expected_session_id=expected_authority_session,
        )
        for role, path in (
            ("aq_root_authorization", binding.root_authorization_path),
            ("aq_autonomy_plan", binding.autonomy_plan_path),
            ("aq_autonomy_profile", binding.autonomy_profile_path),
            ("aq_autonomy_budget", binding.autonomy_budget_path),
            ("material_phase_tool_profile", binding.material_phase_tool_profile_path),
            (
                "geometry_candidate_validation_receipt",
                binding.geometry_candidate_validation_receipt_path,
            ),
        )
    }
    authorization = RootAuthorizationV2.model_validate(parsed["aq_root_authorization"])
    plan = AutonomyPlanV2.model_validate(parsed["aq_autonomy_plan"])
    profile = AutonomyProfileV2.model_validate(parsed["aq_autonomy_profile"])
    budget = AutonomyBudgetV2.model_validate(parsed["aq_autonomy_budget"])
    tool_profile = PhaseToolProfile.model_validate(parsed["material_phase_tool_profile"])
    geometry = GeometryCandidateValidationReceiptV2.model_validate(
        parsed["geometry_candidate_validation_receipt"]
    )
    if repair_source is not None:
        for artifact, entry, label in (
            (repair_source.scene_spec, entries[binding.scene_spec_path], "SceneSpec"),
            (repair_source.modeling_plan, entries[binding.modeling_plan_path], "ModelingPlan"),
            (
                repair_source.geometry_approval_or_validation,
                entries[binding.geometry_candidate_validation_receipt_path],
                "geometry validation receipt",
            ),
        ):
            _require_embedded_entry(
                artifact=artifact,
                entry=entry,
                code="MATERIAL_REPAIR_SOURCE_BINDING_MISMATCH",
                message=f"repair lineage binds another {label}",
            )
        if not _repair_source_matches_authority(
            repair_source,
            authorization,
            binding,
        ):
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="MATERIAL_REPAIR_SCOPE_MISMATCH",
                        message=(
                            "repair lineage changes the old request, reference, UV identity, "
                            "or subject scope"
                        ),
                        path=binding.repair_source_binding_path,
                    )
                ]
            )
        repair_parent = entries[binding.repair_source_binding_path].entry_id
        for location, path, sha256, byte_size in _iter_sized_exact_artifact_refs(repair_source):
            _add_path(
                job_root,
                entries,
                role="material_repair_lineage_dependency",
                path=path,
                source_kind="policy_evidence",
                ownership="canonical",
                producer=producer,
                dependency_parent=repair_parent,
                expected_sha256=sha256,
            )
            if entries[path].byte_size != byte_size:
                raise MaterialClosureCollectionError(
                    [
                        MaterialClosureIssue(
                            code="STALE_REPAIR_LINEAGE_BYTE_SIZE",
                            message=f"repair lineage artifact size is stale at {location}",
                            path=path,
                        )
                    ]
                )
        assert rollback_observation is not None
        assert repair_source.latest_successful_rollback_receipt is not None
        _collect_rollback_restoration_dependencies(
            job_root,
            entries,
            observation=rollback_observation,
            observation_path=repair_source.latest_successful_rollback_receipt.path,
            producer=producer,
        )

    root_entries = {
        "authorization": entries[binding.root_authorization_path],
        "plan": entries[binding.autonomy_plan_path],
        "profile": entries[binding.autonomy_profile_path],
        "budget": entries[binding.autonomy_budget_path],
        "tool": entries[binding.material_phase_tool_profile_path],
    }
    for artifact, entry, name in (
        (plan.root_authorization, root_entries["authorization"], "plan authorization"),
        (plan.profile, root_entries["profile"], "plan profile"),
        (plan.budget, root_entries["budget"], "plan budget"),
        (authorization.profile, root_entries["profile"], "authorization profile"),
        (authorization.budget, root_entries["budget"], "authorization budget"),
        (geometry.root_authorization, root_entries["authorization"], "geometry authorization"),
    ):
        _require_embedded_entry(
            artifact=artifact,
            entry=entry,
            code="COMMON_ROOT_EXACT_BINDING_MISMATCH",
            message=f"{name} does not bind the declared current root bytes",
        )
    if authorization.status != "active":
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INACTIVE_ROOT_AUTHORIZATION",
                    message="material closure requires an active exact root authorization",
                    path=binding.root_authorization_path,
                )
            ]
        )
    if (
        plan.phase_tool_profiles != authorization.phase_tool_profiles
        or plan.requested_delivery_profiles != authorization.requested_delivery_profiles
        or plan.action_limit != budget.global_action_limit
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="AQ_PLAN_AUTHORIZATION_BUDGET_MISMATCH",
                    message="AQ plan, authorization, profile set, or action budget diverges",
                )
            ]
        )
    if tool_profile.profile_id != "material_authoring" or any(
        not _contains_exact_artifact(items, root_entries["tool"])
        for items in (
            list(plan.phase_tool_profiles),
            list(authorization.phase_tool_profiles),
            list(profile.provenance),
            list(budget.provenance),
            list(plan.provenance),
            list(authorization.provenance),
        )
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="MATERIAL_PHASE_TOOL_PROFILE_BINDING_MISMATCH",
                    message="material_authoring tool profile is not mutually exact-bound",
                    path=binding.material_phase_tool_profile_path,
                )
            ]
        )
    if not _contains_exact_artifact(list(profile.provenance), plan.budget):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="AQ_PROFILE_BUDGET_BINDING_MISMATCH",
                    message="AQ profile provenance omits the exact autonomy budget",
                    path=binding.autonomy_profile_path,
                )
            ]
        )
    primary_entry = entries.get(binding.source_evidence.primary_reference_path)
    if primary_entry is None or _exact_binding(authorization.primary_reference) != _entry_binding(
        primary_entry
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="ROOT_AUTHORIZATION_REFERENCE_MISMATCH",
                    message="root authorization does not bind the declared primary reference",
                    path=binding.source_evidence.primary_reference_path,
                )
            ]
        )
    if (
        geometry.reference_content_scope != authorization.reference_content_scope
        or geometry.target_subject != authorization.target_subject
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="GEOMETRY_AUTHORIZATION_SCOPE_MISMATCH",
                    message="geometry validation changed the authorized subject or scope",
                    path=binding.geometry_candidate_validation_receipt_path,
                )
            ]
        )
    for artifact, path, label in (
        (geometry.canonical_scene_spec, binding.scene_spec_path, "canonical SceneSpec"),
        (geometry.canonical_modeling_plan, binding.modeling_plan_path, "canonical ModelingPlan"),
    ):
        _require_embedded_entry(
            artifact=artifact,
            entry=entries[path],
            code="GEOMETRY_CANONICAL_BINDING_MISMATCH",
            message=f"geometry validation receipt binds another {label}",
        )
    _add_path(
        job_root,
        entries,
        role="compiled_scene_spec",
        path=geometry.compiled_scene_spec.path,
        source_kind="derived_evidence",
        ownership="staging",
        producer=producer,
        dependency_parent=entries[binding.geometry_candidate_validation_receipt_path].entry_id,
        expected_sha256=geometry.compiled_scene_spec.sha256,
    )
    compiled_entry = entries[geometry.compiled_scene_spec.path]
    canonical_scene_entry = entries[binding.scene_spec_path]
    if (compiled_entry.sha256, compiled_entry.byte_size) != (
        canonical_scene_entry.sha256,
        canonical_scene_entry.byte_size,
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="GEOMETRY_COMPILED_SCENE_MISMATCH",
                    message=(
                        "geometry validation compiled SceneSpec bytes differ from the "
                        "current canonical SceneSpec"
                    ),
                    path=geometry.compiled_scene_spec.path,
                )
            ]
        )
    if geometry.canonical_blend.path != "blender/scene.blend":
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="GEOMETRY_CANONICAL_BLEND_PATH_MISMATCH",
                    message="geometry validation receipt does not bind canonical Blender scene",
                    path=geometry.canonical_blend.path,
                )
            ]
        )
    current_blend_entry = entries.get("blender/scene.blend")
    if current_blend_entry is None:
        _add_path(
            job_root,
            entries,
            role="canonical_blend",
            path="blender/scene.blend",
            source_kind="canonical_artifact",
            ownership="canonical",
            producer=producer,
        )
        current_blend_entry = entries["blender/scene.blend"]
    if _exact_binding(geometry.canonical_blend) != _entry_binding(current_blend_entry):
        if repair_source is None:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="GEOMETRY_CANONICAL_BLEND_BINDING_MISMATCH",
                        message="geometry validation receipt binds stale canonical Blend bytes",
                        path="blender/scene.blend",
                    )
                ]
            )
        rollback_observation_path = repair_source.latest_successful_rollback_receipt
        assert rollback_observation_path is not None
        assert rollback_observation is not None
        allowed_blend_bindings = {
            _exact_binding(geometry.canonical_blend),
            _exact_binding(rollback_observation.current_blend),
        }
        if _entry_binding(current_blend_entry) not in allowed_blend_bindings or _exact_binding(
            rollback_observation.current_blend
        ) != _entry_binding(current_blend_entry):
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="UNPROVEN_REPAIR_BLEND_SUPERSESSION",
                        message=(
                            "current Blend is neither approved geometry nor exact rollback output"
                        ),
                        path="blender/scene.blend",
                    )
                ]
            )

    for root_role, root_path in (
        ("aq_root_authorization", binding.root_authorization_path),
        ("aq_autonomy_plan", binding.autonomy_plan_path),
        ("aq_autonomy_profile", binding.autonomy_profile_path),
        ("aq_autonomy_budget", binding.autonomy_budget_path),
        ("material_phase_tool_profile", binding.material_phase_tool_profile_path),
        (
            "geometry_candidate_validation_receipt",
            binding.geometry_candidate_validation_receipt_path,
        ),
    ):
        parent = entries[root_path].entry_id
        for location, path, sha256, byte_size in _iter_sized_exact_artifact_refs(parsed[root_role]):
            if (
                repair_source is not None
                and root_role == "geometry_candidate_validation_receipt"
                and path == "blender/scene.blend"
                and sha256 == geometry.canonical_blend.sha256
            ):
                # The exact historical geometry Blend remains bound by the receipt itself;
                # the current canonical Blend is separately proven by rollback restoration.
                continue
            _add_path(
                job_root,
                entries,
                role="aq_material_root_dependency",
                path=path,
                source_kind="policy_evidence",
                ownership="canonical",
                producer=producer,
                dependency_parent=parent,
                expected_sha256=sha256,
            )
            if entries[path].byte_size != byte_size:
                raise MaterialClosureCollectionError(
                    [
                        MaterialClosureIssue(
                            code="STALE_EMBEDDED_BYTE_SIZE",
                            message=f"embedded artifact size is stale at {location}",
                            path=path,
                        )
                    ]
                )

    geometry_tool_path = job_root.joinpath(*geometry.phase_tool_profile.path.split("/"))
    try:
        geometry_tool = PhaseToolProfile.model_validate_json(geometry_tool_path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_GEOMETRY_TOOL_PROFILE",
                    message=str(exc)[:1600],
                    path=geometry.phase_tool_profile.path,
                )
            ]
        ) from exc
    geometry_identity = tuple(
        str(getattr(geometry_tool, name))
        for name in ("job_id", "workflow_id", "dispatch_id", "session_id")
    )
    expected_identity = (
        str(binding.job_id),
        str(binding.workflow_id),
        str(binding.dispatch_id),
        expected_authority_session,
    )
    if (
        geometry_identity != expected_identity
        or geometry_tool.profile_id != "geometry_authoring"
        or not _contains_exact_artifact(list(plan.phase_tool_profiles), geometry.phase_tool_profile)
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="GEOMETRY_TOOL_PROFILE_BINDING_MISMATCH",
                    message="geometry receipt tool profile is not current plan-bound authority",
                    path=geometry.phase_tool_profile.path,
                )
            ]
        )

    build_payload = _read_json_object(job_root, binding.canonical_build_provenance_path)
    try:
        from ..build_provenance import collect_build_provenance

        recomputed_build = collect_build_provenance(
            job_root,
            str(binding.job_id),
            surface_detail_inventory_path=job_root.joinpath(
                *binding.canonical_scene_inventory_path.split("/")
            ),
        )
    except (OSError, ValueError) as exc:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="CANONICAL_BUILD_PROVENANCE_RECOMPUTE_FAILED",
                    message=str(exc)[:1600],
                    path=binding.canonical_build_provenance_path,
                )
            ]
        ) from exc
    if build_payload != recomputed_build:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="STALE_CANONICAL_BUILD_PROVENANCE",
                    message="canonical build provenance differs from current contracts",
                    path=binding.canonical_build_provenance_path,
                )
            ]
        )

    inventory_payload = _read_json_object(job_root, binding.canonical_scene_inventory_path)
    if (
        inventory_payload.get("job_id") != str(binding.job_id)
        or inventory_payload.get("blender_version") != "5.0.1"
        or not isinstance(inventory_payload.get("objects"), list)
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_CANONICAL_SCENE_INVENTORY",
                    message="canonical inventory has wrong identity, Blender version, or shape",
                    path=binding.canonical_scene_inventory_path,
                )
            ]
        )
    from .preflight import collect_current_uv_layout_fingerprint

    inventory_entry = entries[binding.canonical_scene_inventory_path]
    inventory_artifact = ExactArtifact(
        artifact_id="canonical-scene-inventory",
        kind="scene_inventory",
        path=inventory_entry.path,
        sha256=inventory_entry.sha256,
        byte_size=inventory_entry.byte_size,
        media_type="application/json",
    )
    observed_uv = collect_current_uv_layout_fingerprint(
        job_root,
        inventory_artifact,
        expected_job_id=str(binding.job_id),
    )
    candidate_inventory_entry = entries.get(geometry.candidate_inventory.path)
    if candidate_inventory_entry is None:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="MISSING_GEOMETRY_INVENTORY",
                    message="geometry validation receipt omits its candidate inventory",
                    path=geometry.candidate_inventory.path,
                )
            ]
        )
    candidate_inventory = ExactArtifact(
        artifact_id="geometry-candidate-inventory",
        kind="scene_inventory",
        path=candidate_inventory_entry.path,
        sha256=candidate_inventory_entry.sha256,
        byte_size=candidate_inventory_entry.byte_size,
        media_type="application/json",
    )
    candidate_uv = collect_current_uv_layout_fingerprint(
        job_root,
        candidate_inventory,
        expected_job_id=str(binding.job_id),
    )
    if observed_uv != binding.uv_layout_fingerprint or candidate_uv != observed_uv:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="UV_LAYOUT_FINGERPRINT_MISMATCH",
                    message="binding, canonical inventory, and approved geometry UVs diverge",
                    path=binding.canonical_scene_inventory_path,
                )
            ]
        )


def _validate_typed_imagegen_root(
    *,
    job_root: Path,
    role: str,
    path: str,
    binding: MaterialClosureSourceBindingArtifact,
    expected_session_id: str | None = None,
) -> BaseModel | dict[str, Any]:
    """Strict-dispatch one typed ImageGen root and enforce its workflow identity chain."""

    payload = _read_json_object(job_root, path)
    model_types = _TYPED_IMAGEGEN_MODELS.get(role)
    if model_types is None:
        return payload
    parsed: Any | None = None
    errors: list[str] = []
    encoded = job_root.joinpath(*path.split("/")).read_bytes()
    for model_type in model_types:
        try:
            parsed = model_type.model_validate_json(encoded)
            break
        except ValidationError as exc:
            errors.append(f"{model_type.__name__}: {exc}")
    if parsed is None:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_TYPED_IMAGEGEN_EVIDENCE",
                    message=(f"{role} failed strict schema dispatch: " + " | ".join(errors)[:1600]),
                    path=path,
                )
            ]
        )
    expected_scope = {
        "job_id": str(binding.job_id),
        "workflow_id": str(binding.workflow_id),
        "dispatch_id": str(binding.dispatch_id),
        "session_id": expected_session_id or str(binding.session_id),
    }
    mismatches = [
        name
        for name, expected in expected_scope.items()
        if hasattr(parsed, name) and str(getattr(parsed, name)) != expected
    ]
    if mismatches:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="IMAGEGEN_EVIDENCE_SCOPE_MISMATCH",
                    message=f"{role} targets another identity: {sorted(mismatches)}",
                    path=path,
                )
            ]
        )
    if isinstance(parsed, CodexImageCompanionSelectionReceipt):
        core_path = parsed.core_selection.path
        try:
            core_selection = CodexImageGenerationSelection.model_validate_json(
                job_root.joinpath(*core_path.split("/")).read_bytes()
            )
        except ValidationError as exc:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="INVALID_CORE_IMAGEGEN_SELECTION",
                        message=str(exc)[:1800],
                        path=core_path,
                    )
                ]
            ) from exc
        core_scope = {name: str(getattr(core_selection, name)) for name in expected_scope}
        if core_scope != expected_scope:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="IMAGEGEN_CORE_SELECTION_SCOPE_MISMATCH",
                        message="companion core selection targets another workflow session",
                        path=core_path,
                    )
                ]
            )
    return parsed


def validate_typed_imagegen_evidence_root(
    job_root: Path,
    *,
    role: str,
    path: str,
    binding: MaterialClosureSourceBindingArtifact,
) -> BaseModel:
    """Strict-dispatch one public typed ImageGen root without accepting generic JSON."""

    if role not in _TYPED_IMAGEGEN_MODELS:
        raise ValueError(f"unsupported typed ImageGen evidence role: {role}")
    parsed = _validate_typed_imagegen_root(
        job_root=job_root,
        role=role,
        path=path,
        binding=binding,
    )
    if not isinstance(parsed, BaseModel):
        raise AssertionError("typed ImageGen evidence did not produce a strict model")
    return parsed


def _artifact_binding(value: object) -> tuple[str, str]:
    """Project one strict artifact-like object into its exact path/hash binding."""

    path = getattr(value, "path", None)
    sha256 = getattr(value, "sha256", None)
    if not isinstance(path, str) or not isinstance(sha256, str):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_IMAGEGEN_CHAIN_ARTIFACT",
                    message="typed ImageGen identity chain contains a non-artifact binding",
                )
            ]
        )
    return path, sha256


def _validate_imagegen_identity_chain(
    typed: dict[str, BaseModel],
    entries: dict[str, MaterialDependencyEntry],
    binding: MaterialClosureSourceBinding,
) -> None:
    """Require every typed ImageGen root to bind the same exact workflow artifacts."""

    root_paths = {
        name.removesuffix("_path"): getattr(binding, name)
        for name in (
            "imagegen_provider_profile_path",
            "imagegen_assignment_path",
            "imagegen_completion_path",
            "imagegen_generated_image_evidence_path",
            "imagegen_normalization_plan_path",
            "imagegen_normalization_receipt_path",
            "imagegen_semantic_review_path",
            "imagegen_selection_receipt_path",
            "image_to_material_adoption_path",
            "material_authoring_request_path",
            "material_authoring_manifest_path",
            "material_authoring_receipt_path",
        )
    }

    def root(role: str) -> tuple[str, str]:
        """Return the exact current entry identity for one typed source root."""

        path = root_paths[role]
        assert isinstance(path, str)
        entry = entries[path]
        return entry.path, entry.sha256

    checks: list[tuple[str, object, set[tuple[str, str]]]] = [
        (
            "assignment.provider_profile",
            typed["imagegen_assignment"].provider_profile,
            {root("imagegen_provider_profile")},
        ),
        (
            "completion.assignment",
            typed["imagegen_completion"].assignment,
            {root("imagegen_assignment")},
        ),
        (
            "generated.assignment",
            typed["imagegen_generated_image_evidence"].assignment,
            {root("imagegen_assignment")},
        ),
        (
            "generated.completion",
            typed["imagegen_generated_image_evidence"].completion,
            {root("imagegen_completion")},
        ),
        (
            "normalization_receipt.plan",
            typed["imagegen_normalization_receipt"].plan,
            {root("imagegen_normalization_plan")},
        ),
        (
            "semantic_review.assignment",
            typed["imagegen_semantic_review"].assignment,
            {root("imagegen_assignment")},
        ),
        (
            "selection.assignment",
            typed["imagegen_selection_receipt"].assignment,
            {root("imagegen_assignment")},
        ),
        (
            "selection.completion",
            typed["imagegen_selection_receipt"].completion,
            {root("imagegen_completion")},
        ),
        (
            "adoption.generated_image_evidence",
            typed["image_to_material_adoption"].generated_image_evidence,
            {root("imagegen_generated_image_evidence")},
        ),
        (
            "manifest.request",
            typed["material_authoring_manifest"].request,
            {root("material_authoring_request")},
        ),
        (
            "receipt.request",
            typed["material_authoring_receipt"].request,
            {root("material_authoring_request")},
        ),
        (
            "receipt.manifest",
            typed["material_authoring_receipt"].manifest,
            {root("material_authoring_manifest")},
        ),
    ]
    selection = typed["imagegen_selection_receipt"]
    allowed_selection = {root("imagegen_selection_receipt")}
    if isinstance(selection, CodexImageCompanionSelectionReceipt):
        allowed_selection.add(_artifact_binding(selection.core_selection))
    checks.append(
        (
            "adoption.selection",
            typed["image_to_material_adoption"].selection,
            allowed_selection,
        )
    )
    for label, artifact, allowed in checks:
        if _artifact_binding(artifact) not in allowed:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="IMAGEGEN_EVIDENCE_CHAIN_MISMATCH",
                        message=f"typed ImageGen evidence link is stale: {label}",
                    )
                ]
            )
    generated = typed["imagegen_generated_image_evidence"]
    normalization_plan = typed["imagegen_normalization_plan"]
    normalization_receipt = typed["imagegen_normalization_receipt"]
    semantic_review = typed["imagegen_semantic_review"]
    adoption = typed["image_to_material_adoption"]
    if (
        normalization_receipt.status == "review_required"
        or normalization_receipt.normalized_image is None
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="IMAGEGEN_NORMALIZATION_INCOMPLETE",
                    message="ImageGen material closure requires a completed normalization",
                )
            ]
        )
    selected_candidate = getattr(selection, "selected_candidate", None)
    if getattr(selection, "outcome", None) != "selected" or selected_candidate is None:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="IMAGEGEN_SELECTION_INCOMPLETE",
                    message="ImageGen material closure requires one selected candidate",
                )
            ]
        )
    extra_links = (
        (
            "normalization_plan.source_image",
            normalization_plan.source_image,
            generated.generated_file.artifact,
        ),
        (
            "normalization_receipt.source_image",
            normalization_receipt.source_image,
            normalization_plan.source_image,
        ),
        (
            "semantic_review.assignment",
            semantic_review.assignment,
            typed["imagegen_assignment"],
        ),
        (
            "adoption.selected_candidate",
            adoption.selected_candidate,
            selected_candidate,
        ),
        (
            "generated.candidate",
            generated.candidate,
            selected_candidate,
        ),
    )
    for label, observed, expected in extra_links:
        expected_binding = (
            root("imagegen_assignment")
            if isinstance(expected, CodexImageGenerationAssignment)
            else _artifact_binding(expected)
        )
        if _artifact_binding(observed) != expected_binding:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="IMAGEGEN_EVIDENCE_CHAIN_MISMATCH",
                        message=f"typed ImageGen evidence link is stale: {label}",
                    )
                ]
            )
    if (
        semantic_review.candidate_id != generated.candidate_id
        or adoption.selected_source_sha256 != generated.generated_file.artifact.sha256
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="IMAGEGEN_SELECTED_SOURCE_MISMATCH",
                    message="semantic/adoption evidence targets another selected source",
                )
            ]
        )
    if isinstance(selection, CodexImageCompanionSelectionReceipt):
        core = typed.get("imagegen_core_selection")
        if not isinstance(core, CodexImageGenerationSelection):
            raise AssertionError("companion selection core was not strict-dispatched")
        if (
            core.outcome != "selected"
            or core.selected_candidate is None
            or _artifact_binding(core.selected_candidate) != _artifact_binding(selected_candidate)
        ):
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="IMAGEGEN_COMPANION_CORE_SELECTION_MISMATCH",
                        message="companion and core selection disagree",
                    )
                ]
            )


def _collect_source_evidence(
    job_root: Path,
    entries: dict[str, MaterialDependencyEntry],
    *,
    binding: MaterialClosureSourceBinding,
    contract_binding: MaterialClosureSourceBindingArtifact,
    producer: str,
) -> dict[str, BaseModel]:
    """Collect typed source roots and every exact nested artifact they reference."""

    repair_source = None
    expected_imagegen_session = str(contract_binding.session_id)
    reusable_imagegen_bindings: set[tuple[str, str, int]] | None = None
    if contract_binding.authority_mode == "material_repair_lineage":
        from .models import MaterialRepairSourceBinding

        assert contract_binding.repair_source_binding_path is not None
        try:
            repair_source = MaterialRepairSourceBinding.model_validate_json(
                job_root.joinpath(
                    *contract_binding.repair_source_binding_path.split("/")
                ).read_bytes()
            )
        except (OSError, ValidationError) as exc:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="INVALID_MATERIAL_REPAIR_LINEAGE",
                        message=str(exc)[:1600],
                        path=contract_binding.repair_source_binding_path,
                    )
                ]
            ) from exc
        expected_imagegen_session = str(repair_source.source_session_id)
        reusable_imagegen_bindings = {
            _exact_binding(item) for item in repair_source.reusable_imagegen_evidence
        }

    roots: list[tuple[str, str, bool]] = [
        ("primary_reference", binding.primary_reference_path, False),
        ("reference_authority", binding.reference_authority_path, True),
    ]
    if binding.manual_image_source_path is not None:
        roots.append(("manual_image_source", binding.manual_image_source_path, False))
    imagegen_names = (
        "imagegen_provider_profile_path",
        "imagegen_assignment_path",
        "imagegen_completion_path",
        "imagegen_generated_image_evidence_path",
        "imagegen_normalization_plan_path",
        "imagegen_normalization_receipt_path",
        "imagegen_semantic_review_path",
        "imagegen_selection_receipt_path",
        "image_to_material_adoption_path",
        "material_authoring_request_path",
        "material_authoring_manifest_path",
        "material_authoring_receipt_path",
    )
    roots.extend(
        (name.removesuffix("_path"), value, True)
        for name in imagegen_names
        if (value := getattr(binding, name)) is not None
    )
    roots.extend(
        ("additional_material_evidence", path, True) for path in binding.additional_evidence_paths
    )
    typed_models: dict[str, BaseModel] = {}
    for role, path, recursively_collect in roots:
        _add_path(
            job_root,
            entries,
            role=role,
            path=path,
            source_kind="generated_evidence",
            ownership="staging",
            producer=producer,
        )
        if role in _TYPED_IMAGEGEN_MODELS and reusable_imagegen_bindings is not None:
            _require_repair_imagegen_root_listed(
                entries[path],
                reusable_imagegen_bindings,
            )
        if not recursively_collect:
            continue
        payload = _read_json_object(job_root, path)
        if role in _TYPED_IMAGEGEN_MODELS:
            parsed = _validate_typed_imagegen_root(
                job_root=job_root,
                role=role,
                path=path,
                binding=contract_binding,
                expected_session_id=expected_imagegen_session,
            )
            if not isinstance(parsed, BaseModel):
                raise AssertionError("typed ImageGen dispatch returned an untyped payload")
            typed_models[role] = parsed
            if isinstance(parsed, CodexImageCompanionSelectionReceipt):
                typed_models["imagegen_core_selection"] = (
                    CodexImageGenerationSelection.model_validate_json(
                        job_root.joinpath(*parsed.core_selection.path.split("/")).read_bytes()
                    )
                )
            payload = parsed.model_dump(mode="json")
        parent_id = entries[path].entry_id
        for _location, nested_path, expected_sha256 in _iter_exact_artifact_refs(payload):
            _add_path(
                job_root,
                entries,
                role="source_evidence_dependency",
                path=nested_path,
                source_kind="generated_evidence",
                ownership="staging",
                producer=producer,
                dependency_parent=parent_id,
                expected_sha256=expected_sha256,
            )
    if binding.source_mode == "imagegen":
        _validate_imagegen_identity_chain(typed_models, entries, binding)
    return typed_models


def _validate_imagegen_material_chain(
    typed: dict[str, BaseModel],
    material_plan: MaterialPlan,
    entries: dict[str, MaterialDependencyEntry],
    binding: MaterialClosureSourceBinding,
) -> None:
    """Bind selected ImageGen bytes through adoption and authoring to current materials."""

    if binding.source_mode != "imagegen":
        return
    request = typed["material_authoring_request"]
    manifest = typed["material_authoring_manifest"]
    receipt = typed["material_authoring_receipt"]
    adoption = typed["image_to_material_adoption"]
    normalization_plan = typed["imagegen_normalization_plan"]
    normalization_receipt = typed["imagegen_normalization_receipt"]
    selection = typed["imagegen_selection_receipt"]
    generated = typed["imagegen_generated_image_evidence"]
    root_paths = {
        name.removesuffix("_path"): getattr(binding, name)
        for name in (
            "imagegen_selection_receipt_path",
            "imagegen_generated_image_evidence_path",
            "imagegen_normalization_plan_path",
            "imagegen_normalization_receipt_path",
            "image_to_material_adoption_path",
            "material_authoring_request_path",
            "material_authoring_manifest_path",
        )
    }

    def root(role: str) -> tuple[str, str]:
        """Return one exact typed-root path and digest from collected current bytes."""

        path = root_paths[role]
        assert isinstance(path, str)
        entry = entries[path]
        return entry.path, entry.sha256

    base_request = (
        request.base_request
        if isinstance(request, CodexImageNormalizedMaterialAuthoringRequestV010)
        else request
    )
    if not isinstance(base_request, CodexImageMaterialAuthoringRequestV021):
        raise AssertionError("ImageGen material request did not expose its 0.2.1 base")
    plan_material_ids = {item.material_id for item in material_plan.materials}
    adoption_material_ids = set(adoption.target_material_ids)
    if (
        not adoption_material_ids.issubset(plan_material_ids)
        or base_request.material_id not in adoption_material_ids
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="IMAGEGEN_MATERIAL_ID_CHAIN_MISMATCH",
                    message="ImageGen adoption/request targets differ from MaterialPlan",
                )
            ]
        )
    allowed_selection = {root("imagegen_selection_receipt")}
    if isinstance(selection, CodexImageCompanionSelectionReceipt):
        allowed_selection.add(_artifact_binding(selection.core_selection))
    core_links = (
        (base_request.core_evidence.selection, allowed_selection),
        (
            base_request.core_evidence.selected_evidence,
            {root("imagegen_generated_image_evidence")},
        ),
        (base_request.core_evidence.adoption, {root("image_to_material_adoption")}),
    )
    if any(_artifact_binding(artifact) not in allowed for artifact, allowed in core_links):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="IMAGEGEN_AUTHORING_CORE_EVIDENCE_MISMATCH",
                    message="material authoring request omits or swaps selected core evidence",
                )
            ]
        )
    if (
        base_request.strategy != adoption.material_strategy
        or base_request.source.artifact.sha256 != adoption.selected_source_sha256
        or base_request.source.artifact.sha256 != generated.generated_file.artifact.sha256
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="IMAGEGEN_AUTHORING_SOURCE_MISMATCH",
                    message="material authoring source/strategy differs from adoption",
                )
            ]
        )
    if isinstance(request, CodexImageNormalizedMaterialAuthoringRequestV010):
        normalized = normalization_receipt.normalized_image
        if normalized is None:
            raise AssertionError("completed normalization has no exact output")
        normalized_links = (
            (request.normalization_plan, root("imagegen_normalization_plan")),
            (request.normalization_receipt, root("imagegen_normalization_receipt")),
            (request.effective_source.artifact, _artifact_binding(normalized)),
        )
        if any(_artifact_binding(artifact) != expected for artifact, expected in normalized_links):
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="IMAGEGEN_NORMALIZED_AUTHORING_MISMATCH",
                        message="normalized authoring request uses another normalization",
                    )
                ]
            )
    else:
        if _artifact_binding(base_request.source.artifact) != _artifact_binding(
            normalization_plan.source_image
        ):
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="IMAGEGEN_AUTHORING_SOURCE_PATH_MISMATCH",
                        message="direct authoring request uses another selected image",
                    )
                ]
            )
    request_root = root("material_authoring_request")
    manifest_root = root("material_authoring_manifest")
    request_material_id = base_request.material_id
    if isinstance(manifest, CodexImageNormalizedAuthoredMaterialManifestV010):
        manifest_material_id = manifest.material_id
        manifest_request = manifest.request
        manifest_output_artifacts = [channel.output for channel in manifest.channels]
        manifest_run_id = manifest.run_id
        request_run_id = request.run_id
    elif isinstance(manifest, CodexImageAuthoredMaterialManifestV021):
        manifest_material_id = manifest.material_id
        manifest_request = manifest.request
        manifest_output_artifacts = [channel.output for channel in manifest.channels]
        manifest_run_id = manifest.run_id
        request_run_id = base_request.run_id
    else:
        raise AssertionError("ImageGen material manifest strict dispatch was lost")
    if (
        manifest_material_id != request_material_id
        or manifest_run_id != request_run_id
        or _artifact_binding(manifest_request) != request_root
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="IMAGEGEN_AUTHORING_MANIFEST_MISMATCH",
                    message="material authoring manifest targets another request/material/run",
                )
            ]
        )
    if (
        _artifact_binding(receipt.request) != request_root
        or _artifact_binding(receipt.manifest) != manifest_root
        or receipt.run_id != request_run_id
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="IMAGEGEN_AUTHORING_RECEIPT_MISMATCH",
                    message="material authoring receipt targets another request/manifest/run",
                )
            ]
        )
    receipt_outputs = {_artifact_binding(item) for item in receipt.outputs}
    if not {_artifact_binding(item) for item in manifest_output_artifacts}.issubset(
        receipt_outputs
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="IMAGEGEN_AUTHORING_OUTPUT_CLOSURE_MISMATCH",
                    message="material authoring receipt omits manifest channel outputs",
                )
            ]
        )


def collect_material_dependency_closure_from_roots(
    *,
    job_root: Path,
    source_binding: ExactArtifact,
    closure_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    producer: str,
    producer_version: str,
    created_at: datetime,
    planned_outputs: list[MaterialPlannedOutput],
) -> MaterialDependencyClosure:
    """Recursively derive all material-plan, manifest, graph, image, mask, and reference inputs."""

    expected_binding_path = f"production/material_closure/{session_id}/source_binding.json"
    if (
        source_binding.kind != "material_closure_source_binding"
        or source_binding.path != expected_binding_path
        or source_binding.media_type != "application/json"
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="NONCANONICAL_SOURCE_BINDING_ARTIFACT",
                    message="Material Closure source binding kind/path/media type is invalid",
                    path=source_binding.path,
                )
            ]
        )
    binding_path = job_root.joinpath(*source_binding.path.split("/"))
    if (
        not binding_path.is_file()
        or binding_path.stat().st_size != source_binding.byte_size
        or sha256_file(binding_path) != source_binding.sha256
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="STALE_SOURCE_BINDING",
                    message="Material Closure source binding bytes are missing or stale",
                    path=source_binding.path,
                )
            ]
        )
    try:
        binding = MaterialClosureSourceBindingArtifact.model_validate_json(
            binding_path.read_bytes()
        )
    except ValidationError as exc:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_SOURCE_BINDING",
                    message=str(exc)[:1800],
                    path=source_binding.path,
                )
            ]
        ) from exc
    expected_scope = (job_id, workflow_id, dispatch_id, session_id)
    observed_scope = (
        binding.job_id,
        binding.workflow_id,
        binding.dispatch_id,
        binding.session_id,
    )
    if observed_scope != expected_scope:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="SOURCE_BINDING_SCOPE_MISMATCH",
                    message="Material Closure source binding targets another workflow session",
                    path=source_binding.path,
                )
            ]
        )

    has_material = any(
        value is not None
        for value in (
            binding.canonical_material_plan_observation_path,
            binding.material_plan_baseline_snapshot_path,
        )
    )
    if has_material:
        if (
            binding.canonical_material_plan_observation_path != "analysis/material_plan.json"
            or binding.material_plan_baseline_snapshot_path is None
            or binding.material_plan_absence_evidence_path is not None
        ):
            raise ValueError(
                "existing MaterialPlan requires canonical observation and run-owned snapshot"
            )
    elif binding.material_plan_absence_evidence_path is None:
        raise ValueError("absent MaterialPlan requires exact generic absence evidence")
    if binding.material_plan_baseline_snapshot_path == "analysis/material_plan.json":
        raise ValueError("MaterialPlan baseline must not alias the live canonical observation")
    entries: dict[str, MaterialDependencyEntry] = {}
    root_specs = [
        (
            "material_closure_source_binding",
            source_binding.path,
            "policy_evidence",
            "request_owned",
        ),
        ("canonical_scene_spec", binding.scene_spec_path, "canonical_artifact", "canonical"),
        ("modeling_plan", binding.modeling_plan_path, "canonical_artifact", "canonical"),
        (
            "aq_root_authorization",
            binding.root_authorization_path,
            "policy_evidence",
            "canonical",
        ),
        (
            "aq_autonomy_plan",
            binding.autonomy_plan_path,
            "policy_evidence",
            "canonical",
        ),
        (
            "aq_autonomy_profile",
            binding.autonomy_profile_path,
            "policy_evidence",
            "canonical",
        ),
        (
            "aq_autonomy_budget",
            binding.autonomy_budget_path,
            "policy_evidence",
            "canonical",
        ),
        (
            "material_phase_tool_profile",
            binding.material_phase_tool_profile_path,
            "policy_evidence",
            "canonical",
        ),
        (
            "geometry_candidate_validation_receipt",
            binding.geometry_candidate_validation_receipt_path,
            "generated_evidence",
            "canonical",
        ),
        (
            "canonical_build_provenance",
            binding.canonical_build_provenance_path,
            "canonical_artifact",
            "canonical",
        ),
        (
            "canonical_scene_inventory",
            binding.canonical_scene_inventory_path,
            "canonical_artifact",
            "canonical",
        ),
        (
            "candidate_material_plan",
            binding.candidate_material_plan_path,
            "staging_artifact",
            "staging",
        ),
        (
            "source_material_graph",
            binding.material_graph_path,
            "staging_artifact",
            "staging",
        ),
        (
            "material_graph_rebinding_plan",
            binding.graph_rebinding_plan_path,
            "policy_evidence",
            "request_owned",
        ),
        (
            "material_graph_rebinding_receipt",
            binding.graph_rebinding_receipt_path,
            "derived_evidence",
            "request_owned",
        ),
        (
            "rebound_material_graph",
            binding.rebound_material_graph_path,
            "derived_evidence",
            "request_owned",
        ),
        (
            "rollback_baseline",
            binding.rollback_baseline_path,
            "rollback_evidence",
            "canonical",
        ),
    ]
    if binding.material_plan_baseline_snapshot_path is not None:
        root_specs.append(
            (
                "canonical_material_plan_observation",
                binding.canonical_material_plan_observation_path,
                "canonical_artifact",
                "canonical",
            )
        )
        root_specs.append(
            (
                "material_plan_baseline_snapshot",
                binding.material_plan_baseline_snapshot_path,
                "generated_evidence",
                "staging",
            )
        )
    else:
        root_specs.append(
            (
                "material_plan_absence_evidence",
                binding.material_plan_absence_evidence_path,
                "generated_evidence",
                "canonical",
            )
        )
    if binding.repair_source_binding_path is not None:
        root_specs.append(
            (
                "material_repair_source_binding",
                binding.repair_source_binding_path,
                "policy_evidence",
                "request_owned",
            )
        )
    for role, path, source_kind, ownership in root_specs:
        assert path is not None
        _add_path(
            job_root,
            entries,
            role=role,
            path=path,
            source_kind=source_kind,
            ownership=ownership,
            producer=producer,
        )
    if binding.material_plan_absence_evidence_path is not None:
        absence_path = binding.material_plan_absence_evidence_path
        try:
            absence = MaterialCanonicalMaterialPlanAbsence.model_validate_json(
                job_root.joinpath(*absence_path.split("/")).read_bytes()
            )
        except (OSError, ValidationError) as exc:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="INVALID_MATERIAL_PLAN_ABSENCE_EVIDENCE",
                        message=str(exc)[:1800],
                        path=absence_path,
                    )
                ]
            ) from exc
        validate_material_plan_absence_evidence(
            job_root,
            absence,
            source_binding=binding,
        )
        absence_parent = entries[absence_path].entry_id
        for role, artifact in (
            ("material_plan_absence_observation_state", absence.observation_state),
            ("material_plan_absence_scene_spec", absence.canonical_scene_spec),
            ("material_plan_absence_blend", absence.canonical_blend),
        ):
            _add_path(
                job_root,
                entries,
                role=role,
                path=artifact.path,
                source_kind="canonical_artifact",
                ownership="canonical",
                producer=producer,
                dependency_parent=absence_parent,
                expected_sha256=artifact.sha256,
            )
    typed_source_evidence = _collect_source_evidence(
        job_root,
        entries,
        binding=binding.source_evidence,
        contract_binding=binding,
        producer=producer,
    )
    _validate_common_root_graph(
        job_root,
        entries,
        binding=binding,
        producer=producer,
    )
    if binding.material_plan_baseline_snapshot_path is not None:
        observation = entries["analysis/material_plan.json"]
        baseline = entries[binding.material_plan_baseline_snapshot_path]
        if (observation.sha256, observation.byte_size) != (
            baseline.sha256,
            baseline.byte_size,
        ):
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="MATERIAL_BASELINE_SNAPSHOT_MISMATCH",
                        message=("run-owned MaterialPlan baseline differs from live observation"),
                        path=binding.material_plan_baseline_snapshot_path,
                    )
                ]
            )
    _read_json_object(job_root, binding.scene_spec_path)
    _read_json_object(job_root, binding.modeling_plan_path)
    _read_json_object(job_root, binding.candidate_material_plan_path)
    _read_json_object(job_root, binding.material_graph_path)
    _read_json_object(job_root, binding.graph_rebinding_plan_path)
    _read_json_object(job_root, binding.graph_rebinding_receipt_path)
    _read_json_object(job_root, binding.rebound_material_graph_path)
    try:
        scene_spec = SceneSpec.model_validate_json(
            job_root.joinpath(*binding.scene_spec_path.split("/")).read_bytes()
        )
        modeling_plan = ModelingPlan.model_validate_json(
            job_root.joinpath(*binding.modeling_plan_path.split("/")).read_bytes()
        )
        material_plan = MaterialPlan.model_validate_json(
            job_root.joinpath(*binding.candidate_material_plan_path.split("/")).read_bytes()
        )
        source_material_graph = MaterialGraphSpec.model_validate_json(
            job_root.joinpath(*binding.material_graph_path.split("/")).read_bytes()
        )
        graph_rebinding_plan = MaterialGraphRebindingPlan.model_validate_json(
            job_root.joinpath(*binding.graph_rebinding_plan_path.split("/")).read_bytes()
        )
        graph_rebinding_receipt = MaterialGraphRebindingReceipt.model_validate_json(
            job_root.joinpath(*binding.graph_rebinding_receipt_path.split("/")).read_bytes()
        )
        material_graph = MaterialGraphSpec.model_validate_json(
            job_root.joinpath(*binding.rebound_material_graph_path.split("/")).read_bytes()
        )
    except ValidationError as exc:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="INVALID_MATERIAL_ROOT_CONTRACT",
                    message=str(exc)[:1800],
                )
            ]
        ) from exc
    if scene_spec.job_id != job_id or modeling_plan.job_id != job_id:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="MATERIAL_ROOT_JOB_MISMATCH",
                    message="SceneSpec or ModelingPlan belongs to another job",
                )
            ]
        )
    if material_plan.job_id != job_id:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="MATERIAL_PLAN_JOB_MISMATCH",
                    message="candidate MaterialPlan belongs to another job",
                    path=binding.candidate_material_plan_path,
                )
            ]
        )
    _validate_imagegen_material_chain(
        typed_source_evidence,
        material_plan,
        entries,
        binding.source_evidence,
    )
    if (
        graph_rebinding_plan.source_binding.path != source_binding.path
        or graph_rebinding_plan.source_binding.sha256 != source_binding.sha256
        or graph_rebinding_receipt.source_binding.path != source_binding.path
        or graph_rebinding_receipt.source_binding.sha256 != source_binding.sha256
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="GRAPH_REBIND_SOURCE_BINDING_MISMATCH",
                    message="graph rebind evidence targets another source inventory",
                )
            ]
        )
    source_graph_entry = entries[binding.material_graph_path]
    candidate_entry = entries[binding.candidate_material_plan_path]
    rebound_entry = entries[binding.rebound_material_graph_path]
    expected_rebind_links = (
        (graph_rebinding_plan.source_graph, source_graph_entry),
        (graph_rebinding_plan.candidate_material_plan, candidate_entry),
        (graph_rebinding_receipt.source_graph, source_graph_entry),
        (graph_rebinding_receipt.rebound_graph, rebound_entry),
    )
    if any(
        artifact is None
        or (artifact.path, artifact.sha256, artifact.byte_size)
        != (entry.path, entry.sha256, entry.byte_size)
        for artifact, entry in expected_rebind_links
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="GRAPH_REBIND_ARTIFACT_MISMATCH",
                    message="graph rebind plan or receipt has a stale exact artifact",
                )
            ]
        )
    plan_entry = entries[binding.graph_rebinding_plan_path]
    if (
        graph_rebinding_receipt.plan.path,
        graph_rebinding_receipt.plan.sha256,
        graph_rebinding_receipt.plan.byte_size,
    ) != (plan_entry.path, plan_entry.sha256, plan_entry.byte_size):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="GRAPH_REBIND_PLAN_RECEIPT_MISMATCH",
                    message="graph rebind receipt targets another plan",
                )
            ]
        )
    if graph_rebinding_plan.output_path != binding.rebound_material_graph_path:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="GRAPH_REBIND_OUTPUT_PATH_MISMATCH",
                    message="graph rebind plan output differs from source binding",
                    path=graph_rebinding_plan.output_path,
                )
            ]
        )
    if graph_rebinding_plan.expected_rebound_sha256 != rebound_entry.sha256:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="GRAPH_REBIND_OUTPUT_HASH_MISMATCH",
                    message="rebound graph bytes differ from the planned derivative",
                    path=binding.rebound_material_graph_path,
                )
            ]
        )
    expected_rebound, expected_changes = apply_material_graph_rebinding(
        source_material_graph.model_dump(mode="json"),
        graph_rebinding_plan,
    )
    if (
        expected_rebound != material_graph.model_dump(mode="json")
        or expected_changes != graph_rebinding_receipt.applied_changes
        or graph_rebinding_receipt.status != "passed"
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="GRAPH_REBIND_REPLAY_MISMATCH",
                    message="rebound graph or receipt differs from deterministic replay",
                )
            ]
        )
    scene_material_ids = {item.id for item in scene_spec.materials}
    plan_material_ids = {item.material_id for item in material_plan.materials}
    if scene_material_ids != plan_material_ids:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="MATERIAL_ID_COVERAGE_MISMATCH",
                    message=("candidate MaterialPlan IDs do not exactly cover SceneSpec materials"),
                )
            ]
        )
    if material_graph.material_id not in plan_material_ids:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="MATERIAL_GRAPH_ID_MISMATCH",
                    message="MaterialGraph material ID is absent from candidate MaterialPlan",
                )
            ]
        )
    planned_exact = {
        item.output_kind: item for item in planned_outputs if item.verification == "exact_hash"
    }
    if (
        planned_exact.get("material_plan") is None
        or planned_exact["material_plan"].sha256 != candidate_entry.sha256
        or planned_exact.get("material_graph") is None
        or planned_exact["material_graph"].sha256 != rebound_entry.sha256
    ):
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="PLANNED_MATERIAL_OUTPUT_HASH_MISMATCH",
                    message="planned content outputs differ from candidate or rebound bytes",
                )
            ]
        )
    scene_parent = entries[binding.scene_spec_path].entry_id
    for source in scene_spec.sources:
        _add_path(
            job_root,
            entries,
            role="scene_reference_source",
            path=source.path,
            source_kind="request_input",
            ownership="canonical",
            producer=producer,
            dependency_parent=scene_parent,
        )
    modeling_parent = entries[binding.modeling_plan_path].entry_id
    for role, path in (
        ("reference_analysis", modeling_plan.reference_analysis_path),
        ("camera_solution", modeling_plan.camera_solution_path),
    ):
        _add_path(
            job_root,
            entries,
            role=role,
            path=path,
            source_kind="canonical_artifact",
            ownership="canonical",
            producer=producer,
            dependency_parent=modeling_parent,
        )
    for item in material_plan.materials:
        if item.shader_recipe:
            _add_path(
                job_root,
                entries,
                role="shader_recipe",
                path=item.shader_recipe,
                source_kind="staging_artifact",
                ownership="staging",
                producer=producer,
                dependency_parent=entries[binding.candidate_material_plan_path].entry_id,
                material_id=item.material_id,
            )
            try:
                recipe = ShaderRecipe.model_validate_json(
                    job_root.joinpath(*item.shader_recipe.split("/")).read_bytes()
                )
            except ValidationError as exc:
                raise MaterialClosureCollectionError(
                    [
                        MaterialClosureIssue(
                            code="INVALID_SHADER_RECIPE",
                            message=str(exc)[:1800],
                            path=item.shader_recipe,
                        )
                    ]
                ) from exc
            if recipe.material_id != item.material_id:
                raise MaterialClosureCollectionError(
                    [
                        MaterialClosureIssue(
                            code="SHADER_RECIPE_MATERIAL_ID_MISMATCH",
                            message=(f"ShaderRecipe targets another material: {item.material_id}"),
                            path=item.shader_recipe,
                        )
                    ]
                )
            if recipe.texture_manifest and recipe.texture_manifest != item.texture_manifest:
                raise MaterialClosureCollectionError(
                    [
                        MaterialClosureIssue(
                            code="SHADER_RECIPE_MANIFEST_MISMATCH",
                            message=(
                                f"ShaderRecipe manifest differs from MaterialPlan: "
                                f"{item.material_id}"
                            ),
                            path=item.shader_recipe,
                        )
                    ]
                )
        if not item.texture_manifest:
            if item.texture_strategy in {"image", "hybrid"}:
                raise MaterialClosureCollectionError(
                    [
                        MaterialClosureIssue(
                            code="MISSING_TEXTURE_MANIFEST",
                            message=f"image-backed material lacks manifest: {item.material_id}",
                        )
                    ]
                )
            continue
        _add_path(
            job_root,
            entries,
            role="texture_manifest",
            path=item.texture_manifest,
            source_kind="staging_artifact",
            ownership="staging",
            producer=producer,
            dependency_parent=entries[binding.candidate_material_plan_path].entry_id,
            material_id=item.material_id,
        )
        try:
            manifest = TextureManifest.model_validate_json(
                job_root.joinpath(*item.texture_manifest.split("/")).read_bytes()
            )
        except ValidationError as exc:
            raise MaterialClosureCollectionError(
                [
                    MaterialClosureIssue(
                        code="INVALID_TEXTURE_MANIFEST",
                        message=str(exc)[:1800],
                        path=item.texture_manifest,
                    )
                ]
            ) from exc
        manifest_parent = entries[item.texture_manifest].entry_id
        if manifest.shader_recipe:
            _add_path(
                job_root,
                entries,
                role="shader_recipe",
                path=manifest.shader_recipe,
                source_kind="staging_artifact",
                ownership="staging",
                producer=producer,
                dependency_parent=manifest_parent,
                material_id=item.material_id,
            )
        for channel_name, channel in sorted(manifest.channels.items()):
            if channel.source == "image" and channel.path:
                channel_path = _resolve_manifest_owned_dependency_path(
                    job_root,
                    manifest_path=item.texture_manifest,
                    declared_path=channel.path,
                )
                _add_path(
                    job_root,
                    entries,
                    role=f"texture_channel_{channel_name}",
                    path=channel_path,
                    source_kind="staging_artifact",
                    ownership="staging",
                    producer=producer,
                    dependency_parent=manifest_parent,
                    material_id=item.material_id,
                    expected_sha256=(
                        None
                        if manifest.provenance is None
                        else manifest.provenance.generated_sha256.get(channel_name)
                    ),
                )
        for surface in manifest.surface_detail_bindings:
            if surface.placement.mask_path:
                mask_path = _resolve_manifest_owned_dependency_path(
                    job_root,
                    manifest_path=item.texture_manifest,
                    declared_path=surface.placement.mask_path,
                )
                _add_path(
                    job_root,
                    entries,
                    role="surface_detail_mask",
                    path=mask_path,
                    source_kind="staging_artifact",
                    ownership="staging",
                    producer=producer,
                    dependency_parent=manifest_parent,
                    material_id=item.material_id,
                    expected_sha256=surface.placement.mask_sha256,
                )
    graph_parent = entries[binding.rebound_material_graph_path].entry_id
    graph_artifacts = list(material_graph.provenance.inputs)
    graph_artifacts.extend(
        channel.image for channel in material_graph.base_channels if channel.image is not None
    )
    graph_artifacts.extend(
        layer_channel.image
        for layer in material_graph.layers
        for layer_channel in layer.channels
        if layer_channel.image is not None
    )
    graph_artifacts.extend(
        layer.mask.image
        for layer in material_graph.layers
        if getattr(layer.mask, "kind", None) == "image"
    )
    graph_artifacts.append(material_graph.preview_lighting.reference_source)
    for artifact in graph_artifacts:
        future_output = next(
            (
                item
                for item in planned_outputs
                if item.path == artifact.path and item.verification == "exact_hash"
            ),
            None,
        )
        if future_output is not None:
            if future_output.sha256 != artifact.sha256:
                raise MaterialClosureCollectionError(
                    [
                        MaterialClosureIssue(
                            code="GRAPH_PLANNED_OUTPUT_BINDING_MISMATCH",
                            message="graph provenance differs from planned exact output",
                            path=artifact.path,
                        )
                    ]
                )
            if artifact.role == "material_plan" and artifact.sha256 != candidate_entry.sha256:
                raise MaterialClosureCollectionError(
                    [
                        MaterialClosureIssue(
                            code="GRAPH_CANDIDATE_PLAN_BINDING_MISMATCH",
                            message="graph provenance differs from candidate MaterialPlan",
                            path=artifact.path,
                        )
                    ]
                )
            continue
        _add_path(
            job_root,
            entries,
            role=f"material_graph_{artifact.role}",
            path=artifact.path,
            source_kind="staging_artifact",
            ownership="staging",
            producer=producer,
            dependency_parent=graph_parent,
            material_id=material_graph.material_id,
            expected_sha256=artifact.sha256,
        )
    rollback_entry = entries[binding.rollback_baseline_path]
    rollback_artifact = ExactArtifact(
        artifact_id=rollback_entry.entry_id,
        kind="rollback_baseline",
        path=rollback_entry.path,
        sha256=rollback_entry.sha256,
        byte_size=rollback_entry.byte_size,
        media_type="application/json",
    )
    return collect_material_dependency_closure(
        job_root=job_root,
        closure_id=closure_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        producer=producer,
        producer_version=producer_version,
        created_at=created_at,
        entries=list(entries.values()),
        planned_outputs=planned_outputs,
        rollback_baseline=rollback_artifact,
        source_binding=source_binding,
        required_roles={
            "canonical_scene_spec",
            "modeling_plan",
            "candidate_material_plan",
            "source_material_graph",
            "material_graph_rebinding_plan",
            "material_graph_rebinding_receipt",
            "rebound_material_graph",
            "rollback_baseline",
        },
    )


def validate_declared_dependencies(
    job_root: Path,
    entries: list[MaterialDependencyEntry],
    *,
    required_roles: Collection[str] = (),
) -> list[MaterialClosureIssue]:
    """Check containment, regular files, exact sizes/hashes, collisions, and required roles."""

    root = job_root.resolve(strict=True)
    issues: list[MaterialClosureIssue] = []
    seen_paths: dict[str, MaterialDependencyEntry] = {}
    seen_casefold: dict[str, str] = {}
    observed_roles = {item.role for item in entries}
    for role in sorted(set(required_roles) - observed_roles):
        issues.append(
            MaterialClosureIssue(
                code="MISSING_REQUIRED_ROLE",
                message=f"required dependency role is absent: {role}",
            )
        )
    for entry in sorted(entries, key=lambda item: (item.role, item.path)):
        if entry.path in seen_paths:
            prior = seen_paths[entry.path]
            code = (
                "CONFLICTING_PATH_HASH"
                if prior.sha256 != entry.sha256
                else "DUPLICATE_DEPENDENCY_PATH"
            )
            issues.append(
                MaterialClosureIssue(
                    code=code,
                    message=f"dependency path appears more than once: {entry.path}",
                    path=entry.path,
                    entry_id=entry.entry_id,
                )
            )
            continue
        seen_paths[entry.path] = entry
        folded = entry.path.casefold()
        if folded in seen_casefold and seen_casefold[folded] != entry.path:
            issues.append(
                MaterialClosureIssue(
                    code="DEPENDENCY_CASE_COLLISION",
                    message=(f"dependency path case-collides with {seen_casefold[folded]}"),
                    path=entry.path,
                    entry_id=entry.entry_id,
                )
            )
            continue
        seen_casefold[folded] = entry.path
        candidate = root.joinpath(*entry.path.split("/"))
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            issues.append(
                MaterialClosureIssue(
                    code="MISSING_DEPENDENCY",
                    message="declared material dependency is missing",
                    path=entry.path,
                    entry_id=entry.entry_id,
                )
            )
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            issues.append(
                MaterialClosureIssue(
                    code="DEPENDENCY_PATH_ESCAPE",
                    message="resolved material dependency escapes the job root",
                    path=entry.path,
                    entry_id=entry.entry_id,
                )
            )
            continue
        if candidate.is_symlink() or not resolved.is_file():
            issues.append(
                MaterialClosureIssue(
                    code="UNSUPPORTED_DEPENDENCY_FILE",
                    message="dependency must be one contained regular non-link file",
                    path=entry.path,
                    entry_id=entry.entry_id,
                )
            )
            continue
        observed_size = resolved.stat().st_size
        if observed_size != entry.byte_size:
            issues.append(
                MaterialClosureIssue(
                    code="STALE_DEPENDENCY_SIZE",
                    message=(f"declared byte size {entry.byte_size} differs from {observed_size}"),
                    path=entry.path,
                    entry_id=entry.entry_id,
                )
            )
            continue
        if sha256_file(resolved) != entry.sha256:
            issues.append(
                MaterialClosureIssue(
                    code="STALE_DEPENDENCY_HASH",
                    message="declared dependency hash differs from current bytes",
                    path=entry.path,
                    entry_id=entry.entry_id,
                )
            )
    return issues


def collect_material_dependency_closure(
    *,
    job_root: Path,
    closure_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    producer: str,
    producer_version: str,
    created_at: datetime,
    entries: list[MaterialDependencyEntry],
    planned_outputs: list[MaterialPlannedOutput],
    rollback_baseline: ExactArtifact,
    source_binding: ExactArtifact,
    required_roles: Collection[str] = (),
) -> MaterialDependencyClosure:
    """Support internal tests after a host-owned traversal has derived every entry."""

    issues = validate_declared_dependencies(
        job_root,
        entries,
        required_roles=required_roles,
    )
    if issues:
        raise MaterialClosureCollectionError(issues)
    sorted_entries = sorted(entries, key=lambda item: (item.role, item.path))
    sorted_outputs = sorted(planned_outputs, key=lambda item: (item.output_kind, item.path))
    return MaterialDependencyClosure.model_validate(
        {
            "closure_id": closure_id,
            "job_id": job_id,
            "workflow_id": workflow_id,
            "dispatch_id": dispatch_id,
            "session_id": session_id,
            "producer": producer,
            "producer_version": producer_version,
            "created_at": created_at,
            "closure_sha256": _closure_payload_digest(
                sorted_entries,
                sorted_outputs,
                source_binding,
            ),
            "collection_mode": "host_graph_derived",
            "source_binding": source_binding.model_dump(mode="json"),
            "entries": [item.model_dump(mode="json") for item in sorted_entries],
            "planned_outputs": [item.model_dump(mode="json") for item in sorted_outputs],
            "rollback_baseline": rollback_baseline.model_dump(mode="json"),
        }
    )


def replay_host_graph_derived_closure(
    job_root: Path,
    closure: MaterialDependencyClosure,
) -> MaterialDependencyClosure:
    """Re-derive a public closure from its exact source binding and require full equality."""

    replayed = collect_material_dependency_closure_from_roots(
        job_root=job_root,
        source_binding=closure.source_binding,
        closure_id=closure.closure_id,
        job_id=closure.job_id,
        workflow_id=closure.workflow_id,
        dispatch_id=closure.dispatch_id,
        session_id=closure.session_id,
        producer=closure.producer,
        producer_version=closure.producer_version,
        created_at=closure.created_at,
        planned_outputs=closure.planned_outputs,
    )
    if replayed != closure:
        raise MaterialClosureCollectionError(
            [
                MaterialClosureIssue(
                    code="CLOSURE_GRAPH_REPLAY_MISMATCH",
                    message=("published closure differs from host graph-derived collection"),
                    path=closure.source_binding.path,
                )
            ]
        )
    return replayed


__all__ = [
    "MaterialClosureCollectionBinding",
    "MaterialClosureCollectionError",
    "build_material_plan_absence_evidence",
    "collect_material_dependency_closure_from_roots",
    "material_plan_parent_fingerprint",
    "replay_host_graph_derived_closure",
    "sha256_file",
    "validate_declared_dependencies",
    "validate_exact_artifact_current",
    "validate_material_plan_absence_evidence",
    "validate_typed_imagegen_evidence_root",
]
