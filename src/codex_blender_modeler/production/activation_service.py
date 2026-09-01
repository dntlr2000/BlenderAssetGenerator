"""Host-owned services for additive AQ activation-readiness contracts."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from ..blender_artifacts import (
    deterministic_json_bytes,
    native_io_path,
    publish_bytes_create_once,
    sha256_file,
    stable_json_digest,
)
from ..production.validation import ensure_contained_production_path
from .activation_models import (
    ACTIVATION_CONTRACT_VERSION,
    ACTIVATION_PROFILE_ID,
    ACTIVATION_PROFILE_VERSION,
    ActivationArtifact,
    ActivationAssetCandidateIndex,
    ActivationAssetCandidateRegistry,
    ActivationAssetEligibilityReport,
    ActivationAssetEvidence,
    ActivationAssetIndexRecord,
    ActivationBaseline,
    ActivationBlenderEvidence,
    ActivationCampaignOutcomeEligibilityReport,
    ActivationCampaignOutcomeEvidence,
    ActivationCampaignOutcomeIndex,
    ActivationCampaignOutcomeIndexRecord,
    ActivationCampaignOutcomeRegistry,
    ActivationCampaignReferenceGroup,
    ActivationCampaignRegistryEntry,
    ActivationCandidateRegistryEntry,
    ActivationCommandReceipt,
    ActivationExclusion,
    ActivationHumanQualityDisposition,
    ActivationReadinessFinding,
    ActivationReadinessReport,
    ActivationReferenceDeduplicationGroup,
    ActivationSourceExclusion,
    ActivationSourceFile,
    ActivationSourceManifest,
    HumanActivationAcceptance,
    HumanLocalActivationAcceptance,
    LocalActivationReadinessReport,
)

_ModelT = TypeVar("_ModelT", bound=BaseModel)

_PROFILE_REGISTRY_PATH = "src/codex_blender_modeler/autonomy_v2/profiles.py"
_CONTROLLER_PROMOTION_PATHS = frozenset(
    {
        "src/codex_blender_modeler/autonomy_v2/approval_policy_service.py",
        "src/codex_blender_modeler/autonomy_v2/approval_supervisor_service.py",
        "src/codex_blender_modeler/autonomy_v2/candidate_validation_service.py",
        "src/codex_blender_modeler/autonomy_v2/controller_bridge.py",
        "src/codex_blender_modeler/autonomy_v2/material_phase_service.py",
        "src/codex_blender_modeler/autonomy_v2/supervisor_service.py",
        "src/codex_blender_modeler/production/activation_models.py",
        "src/codex_blender_modeler/production/activation_service.py",
        "src/codex_blender_modeler/production/controller_executor/service.py",
    }
)
_SOURCE_EXCLUSIONS: tuple[tuple[str, str, str], ...] = (
    (".git/", "git_metadata", "Git object and index metadata are not source payloads."),
    (
        "workspaces/",
        "job_evidence",
        "Job inputs and evidence are immutable runtime data, not source bytes.",
    ),
    ("reports/", "runtime_reports", "Generated reports are outside source identity."),
    ("test_runs/", "test_copy", "Isolated validation copies are test-only."),
    (".pytest_cache/", "pytest_cache", "Pytest cache is non-authoritative."),
    ("pytest-tmp/", "pytest_basetemp", "Pytest basetemp is non-authoritative."),
    (".t/", "pytest_basetemp", "Short pytest basetemp is non-authoritative."),
    (".tr/", "pytest_basetemp", "Short pytest recovery data is non-authoritative."),
    (".codex_test/", "test_copy", "Codex gate output is test-only."),
    ("uv-cache/", "uv_cache", "Dependency cache is not lock evidence."),
    (".uv-cache/", "uv_cache", "Dependency cache is not lock evidence."),
    (".venv/", "dependency_environment", "Installed environments are not lock evidence."),
    ("output/", "generated_output", "Generated reports and previews are not source."),
    ("previews/", "generated_preview", "Generated previews are not source payloads."),
    (
        "copied_repositories/",
        "copied_repository",
        "Copied repositories are non-authoritative validation inputs.",
    ),
    (
        ".aq_activation_chain_audit_",
        "audit_only",
        "Read-only comparison material is not historical activation evidence.",
    ),
)


def _bounded_error_detail(exc: BaseException) -> str:
    """Fit one validation exception into the persisted exclusion-detail limit."""

    detail = str(exc).strip() or type(exc).__name__
    return detail[:1000]


_REQUIRED_ELIGIBILITY_CHECKS = frozenset(
    {
        "authoritative_job_contract",
        "root_authorization",
        "approval_envelope",
        "policy_decision_chain",
        "dependency_closure",
        "canonical_promotion",
        "terminal_completion",
        "qa_evidence",
        "package_evidence",
        "clean_import_evidence",
        "source_baseline_binding",
        "profile_binding",
        "human_review_evidence",
        "artifact_binding",
        "current_canonical_snapshot",
        "controller_writer_boundary",
    }
)
_REQUIRED_FINAL_VALIDATION_IDS = frozenset(
    {
        "uv_sync_frozen_dev_vision",
        "ruff_check",
        "pytest_full",
        "cbm_doctor",
        "cbm_blender_compat",
        "agent_instruction_check",
        "repository_summary_check",
        "approval_envelope_gate",
        "one_prompt_supervisor_gate",
        "activation_readiness_gate",
        "v07_gate",
        "v08_gate",
        "v09_gate",
        "git_diff_check",
        "blender_5_0_1_execution",
        "evidence_integrity_check",
    }
)


class SourceCheckpointRequired(RuntimeError):
    """Signal that activation evidence cannot bind an uncommitted source tree."""


class ActivationValidationError(RuntimeError):
    """Signal a fail-closed activation contract or evidence mismatch."""


def _require_disabled_activation_profile() -> dict[str, object]:
    """Require the live AQ v2 registry to remain disabled before readiness work."""

    from ..autonomy_v2.profiles import autonomy_v2_profile_status

    profile = autonomy_v2_profile_status()
    if profile.get("status") != "disabled_experimental" or profile.get(
        "verified_active"
    ) is not False:
        raise ActivationValidationError("AQ v2 profile is not disabled_experimental")
    return profile


def _utc_now(value: datetime | None = None) -> datetime:
    """Return one aware UTC timestamp for immutable activation evidence."""

    observed = value or datetime.now(UTC)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("activation timestamps must include a timezone offset")
    return observed.astimezone(UTC)


def _build_contract(
    model: type[_ModelT],
    payload: dict[str, Any],
    *,
    prefix: str,
    id_field: str,
    digest_field: str,
) -> _ModelT:
    """Populate deterministic identity fields and strict-validate one contract."""

    provisional = model.model_construct(
        **payload,
        **{
            id_field: "pending-activation-identity",
            digest_field: "0" * 64,
        },
    )
    projection = provisional.model_dump(
        mode="json",
        exclude={id_field, digest_field},
    )
    digest = stable_json_digest(projection)
    complete = dict(payload)
    complete[id_field] = f"{prefix}-{digest[:24]}"
    complete[digest_field] = digest
    return model.model_validate(complete)


def _artifact_for(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
) -> ActivationArtifact:
    """Bind one regular repository-contained file to exact size and SHA-256."""

    repository = root.expanduser().resolve(strict=True)
    safe = ensure_contained_production_path(repository, path, must_exist=True)
    if not os.path.isfile(native_io_path(safe)):
        raise ActivationValidationError(f"activation artifact is not a file: {safe}")
    size = os.path.getsize(native_io_path(safe))
    if size <= 0:
        raise ActivationValidationError(f"activation artifact is empty: {safe}")
    return ActivationArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=safe.relative_to(repository).as_posix(),
        sha256=sha256_file(safe),
        byte_size=size,
    )


def _validate_artifact(root: Path, artifact: ActivationArtifact) -> Path:
    """Reject missing, escaped, resized, or rehashed activation evidence."""

    repository = root.expanduser().resolve(strict=True)
    safe = ensure_contained_production_path(
        repository,
        repository / artifact.path,
        must_exist=True,
    )
    if not os.path.isfile(native_io_path(safe)):
        raise ActivationValidationError(
            f"activation artifact is not a regular file: {artifact.path}"
        )
    if os.path.getsize(native_io_path(safe)) != artifact.byte_size:
        raise ActivationValidationError(
            f"activation artifact size changed: {artifact.path}"
        )
    if sha256_file(safe) != artifact.sha256:
        raise ActivationValidationError(
            f"activation artifact hash changed: {artifact.path}"
        )
    return safe


def _write_contract(
    root: Path,
    path: Path,
    model: BaseModel,
    *,
    artifact_id: str,
    kind: str,
) -> ActivationArtifact:
    """Create or exact-adopt one deterministic immutable activation JSON file."""

    repository = root.expanduser().resolve(strict=True)
    destination = ensure_contained_production_path(
        repository,
        path,
        must_exist=False,
    )
    relative = destination.relative_to(repository)
    if relative.parts[:2] != ("reports", "activation_readiness"):
        raise ActivationValidationError(
            "activation contracts may be written only below reports/activation_readiness"
        )
    publish_bytes_create_once(
        destination,
        deterministic_json_bytes(model.model_dump(mode="json")),
    )
    return _artifact_for(
        repository,
        destination,
        artifact_id=artifact_id,
        kind=kind,
    )


def _load_contract(
    root: Path,
    artifact: ActivationArtifact,
    model: type[_ModelT],
) -> _ModelT:
    """Hash-check and strict-parse one immutable activation artifact."""

    path = _validate_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return model.model_validate_json(handle.read())


def _run_git(root: Path, args: Sequence[str], *, binary: bool = False) -> bytes | str:
    """Run one read-only Git query against the exact repository root."""

    completed = subprocess.run(
        ["git", "-C", os.fspath(root), *args],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ActivationValidationError(
            f"Git query failed ({' '.join(args)}): {message}"
        )
    if binary:
        return completed.stdout
    return completed.stdout.decode("utf-8", errors="strict").strip()


def _nul_paths(root: Path, args: Sequence[str]) -> list[str]:
    """Decode one NUL-delimited Git path listing with normalized POSIX separators."""

    payload = _run_git(root, args, binary=True)
    assert isinstance(payload, bytes)
    return sorted(
        item.decode("utf-8", errors="strict").replace("\\", "/")
        for item in payload.split(b"\0")
        if item
    )


def _is_explicit_runtime_path(path: str) -> bool:
    """Recognize only documented non-source runtime and audit path classes."""

    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    folded = normalized.casefold()
    return any(
        folded.startswith(prefix.casefold())
        for prefix, _code, _reason in _SOURCE_EXCLUSIONS
    )


def inspect_activation_source_checkpoint(root: Path) -> dict[str, object]:
    """Inspect commit, tree, staged, tracked, and unknown untracked source state."""

    repository = root.expanduser().resolve(strict=True)
    commit = str(_run_git(repository, ["rev-parse", "HEAD"]))
    tree = str(_run_git(repository, ["rev-parse", "HEAD^{tree}"]))
    staged = _nul_paths(repository, ["diff", "--cached", "--name-only", "-z"])
    unstaged = _nul_paths(repository, ["diff", "--name-only", "-z"])
    untracked = _nul_paths(
        repository,
        ["ls-files", "--others", "--exclude-standard", "-z"],
    )
    unknown_untracked = [path for path in untracked if not _is_explicit_runtime_path(path)]
    return {
        "git_commit_sha": commit,
        "git_tree_sha": tree,
        "staged_paths": staged,
        "unstaged_paths": unstaged,
        "untracked_paths": untracked,
        "untracked_source_files": unknown_untracked,
        "staged_tree_clean": not staged,
        "working_tree_clean": not staged and not unstaged and not unknown_untracked,
    }


def _source_role(path: str) -> str:
    """Classify every tracked Git blob while retaining unknown files as bound inputs."""

    if path in _CONTROLLER_PROMOTION_PATHS:
        return "controller_promotion"
    if path == _PROFILE_REGISTRY_PATH:
        return "profile_registry"
    if path == "uv.lock":
        return "dependency_lock"
    if path.startswith("schemas/"):
        return "schema"
    if path.startswith("src/"):
        return "source"
    if path.startswith("tests/"):
        return "test"
    if path.startswith("scripts/"):
        return "tooling"
    if path.startswith("verification/") or path.startswith("benchmarks/"):
        return "verification"
    if path.startswith("docs/") or path.endswith(".md"):
        return "documentation"
    if path.startswith("examples/") or path.startswith("textures/"):
        return "example"
    if path.startswith("prompts/"):
        return "prompt"
    if path.startswith((".github/", ".codex/", ".agents/")) or path.endswith(
        (".toml", ".yaml", ".yml")
    ):
        return "configuration"
    return "tracked_repository_input"


def _git_source_files(root: Path) -> list[ActivationSourceFile]:
    """Hash every regular Git blob from one exact commit archive in path order."""

    archive = _run_git(root, ["archive", "--format=tar", "HEAD"], binary=True)
    assert isinstance(archive, bytes)
    records: list[ActivationSourceFile] = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        for member in sorted(bundle.getmembers(), key=lambda item: item.name):
            if member.isdir():
                continue
            if not member.isfile():
                raise ActivationValidationError(
                    f"unsupported Git archive member: {member.name}"
                )
            handle = bundle.extractfile(member)
            if handle is None:
                raise ActivationValidationError(
                    f"Git archive member has no payload: {member.name}"
                )
            content = handle.read()
            path = member.name.replace("\\", "/")
            if _is_explicit_runtime_path(path):
                continue
            records.append(
                ActivationSourceFile(
                    path=path,
                    role=_source_role(path),
                    sha256=hashlib.sha256(content).hexdigest(),
                    byte_size=len(content),
                )
            )
    return records


def _validate_blender_evidence(root: Path, evidence: ActivationBlenderEvidence) -> None:
    """Rehash the exact Blender binary and its repository-contained version receipt."""

    executable = Path(evidence.executable_path).expanduser()
    if not executable.is_file() or sha256_file(executable) != evidence.executable_sha256:
        raise ActivationValidationError("Blender executable is missing or changed")
    _validate_artifact(root, evidence.version_receipt)


def build_activation_source_manifest(
    root: Path,
    *,
    dependency_resolution_evidence: ActivationCommandReceipt,
    blender: ActivationBlenderEvidence,
    python_version: str,
    uv_version: str,
    output_path: Path | None = None,
    generated_at: datetime | None = None,
) -> tuple[ActivationSourceManifest, ActivationArtifact]:
    """Create one immutable source manifest only from a clean exact Git checkpoint."""

    repository = root.expanduser().resolve(strict=True)
    checkpoint = inspect_activation_source_checkpoint(repository)
    if not checkpoint["working_tree_clean"] or not checkpoint["staged_tree_clean"]:
        raise SourceCheckpointRequired(
            "ActivationSourceManifest requires clean tracked and staged source state"
        )
    if checkpoint["untracked_source_files"]:
        raise SourceCheckpointRequired(
            "ActivationSourceManifest rejects unknown untracked source classes"
        )
    if dependency_resolution_evidence.status != "passed":
        raise ActivationValidationError("dependency resolution did not pass")
    if dependency_resolution_evidence.output_artifact is not None:
        _validate_artifact(repository, dependency_resolution_evidence.output_artifact)
    _validate_blender_evidence(repository, blender)
    source_files = _git_source_files(repository)
    by_path = {item.path: item for item in source_files}
    missing_critical = sorted(
        (_CONTROLLER_PROMOTION_PATHS | {_PROFILE_REGISTRY_PATH, "uv.lock"})
        - by_path.keys()
    )
    if missing_critical:
        raise ActivationValidationError(
            "source checkpoint omitted critical paths: " + ", ".join(missing_critical)
        )
    schema_files = [item for item in source_files if item.role == "schema"]
    controller_files = [
        by_path[path] for path in sorted(_CONTROLLER_PROMOTION_PATHS)
    ]
    payload: dict[str, Any] = {
        "project_version": "0.9.0",
        "canonical_scenespec_version": "0.2.0",
        "git_commit_sha": checkpoint["git_commit_sha"],
        "git_tree_sha": checkpoint["git_tree_sha"],
        "working_tree_clean": True,
        "staged_tree_clean": True,
        "untracked_source_files": [],
        "source_files": source_files,
        "schema_files": schema_files,
        "controller_promotion_files": controller_files,
        "profile_registry": by_path[_PROFILE_REGISTRY_PATH],
        "uv_lock": by_path["uv.lock"],
        "python_version": python_version,
        "uv_version": uv_version,
        "dependency_resolution_evidence": dependency_resolution_evidence,
        "blender": blender,
        "excluded_classes": [
            ActivationSourceExclusion(
                path_prefix=prefix,
                reason_code=reason_code,
                reason=reason,
            )
            for prefix, reason_code, reason in _SOURCE_EXCLUSIONS
        ],
        "generator_version": ACTIVATION_CONTRACT_VERSION,
        "generated_at": _utc_now(generated_at),
    }
    manifest = _build_contract(
        ActivationSourceManifest,
        payload,
        prefix="activation-source",
        id_field="manifest_id",
        digest_field="manifest_sha256",
    )
    destination = output_path or (
        repository
        / "reports"
        / "activation_readiness"
        / "source_manifests"
        / f"{manifest.manifest_id}.json"
    )
    artifact = _write_contract(
        repository,
        destination,
        manifest,
        artifact_id=manifest.manifest_id,
        kind="activation_source_manifest",
    )
    return manifest, artifact


def load_activation_source_manifest(
    root: Path,
    artifact: ActivationArtifact,
) -> ActivationSourceManifest:
    """Rehash and strict-parse one source manifest including its payload identity."""

    manifest = _load_contract(root, artifact, ActivationSourceManifest)
    if manifest.dependency_resolution_evidence.output_artifact is not None:
        _validate_artifact(
            root,
            manifest.dependency_resolution_evidence.output_artifact,
        )
    _validate_blender_evidence(root, manifest.blender)
    return manifest


def _aggregate_source_records(records: Iterable[ActivationSourceFile]) -> str:
    """Hash one ordered critical-source inventory into a compact baseline binding."""

    return stable_json_digest(
        [item.model_dump(mode="json") for item in sorted(records, key=lambda x: x.path)]
    )


def create_activation_baseline(
    root: Path,
    *,
    source_manifest_artifact: ActivationArtifact,
    validation_receipts: Sequence[ActivationCommandReceipt],
    output_path: Path | None = None,
    created_at: datetime | None = None,
) -> tuple[ActivationBaseline, ActivationArtifact]:
    """Create one immutable baseline only after clean source and every required gate pass."""

    repository = root.expanduser().resolve(strict=True)
    checkpoint = inspect_activation_source_checkpoint(repository)
    if not checkpoint["working_tree_clean"] or not checkpoint["staged_tree_clean"]:
        raise SourceCheckpointRequired(
            "ActivationBaseline requires a clean committed source checkpoint"
        )
    manifest = load_activation_source_manifest(repository, source_manifest_artifact)
    if (
        checkpoint["git_commit_sha"] != manifest.git_commit_sha
        or checkpoint["git_tree_sha"] != manifest.git_tree_sha
    ):
        raise ActivationValidationError("source checkpoint differs from its manifest")
    if _git_source_files(repository) != manifest.source_files:
        raise ActivationValidationError("current Git blobs differ from source manifest")
    receipts = sorted(validation_receipts, key=lambda item: item.command_id)
    receipt_ids = {item.command_id for item in receipts}
    missing = sorted(_REQUIRED_FINAL_VALIDATION_IDS - receipt_ids)
    if missing:
        raise ActivationValidationError(
            "activation baseline is missing required validation receipts: "
            + ", ".join(missing)
        )
    if any(item.status != "passed" for item in receipts):
        raise ActivationValidationError("activation baseline contains a failed gate")
    for receipt in receipts:
        if receipt.output_artifact is not None:
            _validate_artifact(repository, receipt.output_artifact)
    _require_disabled_activation_profile()
    payload: dict[str, Any] = {
        "source_manifest": source_manifest_artifact,
        "source_manifest_id": manifest.manifest_id,
        "source_manifest_sha256": manifest.manifest_sha256,
        "git_commit_sha": manifest.git_commit_sha,
        "git_tree_sha": manifest.git_tree_sha,
        "schema_manifest_sha256": _aggregate_source_records(manifest.schema_files),
        "controller_promotion_manifest_sha256": _aggregate_source_records(
            manifest.controller_promotion_files
        ),
        "profile_registry_sha256": manifest.profile_registry.sha256,
        "uv_lock_sha256": manifest.uv_lock.sha256,
        "python_version": manifest.python_version,
        "uv_version": manifest.uv_version,
        "blender": manifest.blender,
        "validation_receipts": receipts,
        "profile_id": ACTIVATION_PROFILE_ID,
        "profile_version": ACTIVATION_PROFILE_VERSION,
        "profile_status": "disabled_experimental",
        "campaign_created": False,
        "production_activation_performed": False,
        "human_activation_accepted": False,
        "created_at": _utc_now(created_at),
    }
    baseline = _build_contract(
        ActivationBaseline,
        payload,
        prefix="activation-baseline",
        id_field="baseline_id",
        digest_field="baseline_sha256",
    )
    destination = output_path or (
        repository
        / "reports"
        / "activation_readiness"
        / "baselines"
        / baseline.baseline_id
        / "activation_baseline.json"
    )
    artifact = _write_contract(
        repository,
        destination,
        baseline,
        artifact_id=baseline.baseline_id,
        kind="activation_baseline",
    )
    return baseline, artifact


def load_activation_baseline(
    root: Path,
    artifact: ActivationArtifact,
) -> ActivationBaseline:
    """Rehash and strict-parse one immutable activation baseline."""

    baseline = _load_contract(root, artifact, ActivationBaseline)
    manifest = load_activation_source_manifest(root, baseline.source_manifest)
    if (
        manifest.manifest_id != baseline.source_manifest_id
        or manifest.manifest_sha256 != baseline.source_manifest_sha256
    ):
        raise ActivationValidationError("baseline source manifest binding is inconsistent")
    _validate_blender_evidence(root, baseline.blender)
    for receipt in baseline.validation_receipts:
        if receipt.output_artifact is not None:
            _validate_artifact(root, receipt.output_artifact)
    return baseline


def _unique_exclusions(items: Iterable[ActivationExclusion]) -> list[ActivationExclusion]:
    """Deduplicate and sort machine exclusions without hiding distinct details."""

    unique = {
        (item.code, item.detail): item
        for item in items
    }
    return [unique[key] for key in sorted(unique)]


def _classification_exclusions(evidence: ActivationAssetEvidence) -> list[ActivationExclusion]:
    """Map explicit copy/staging classifications and protected paths to exclusions."""

    exclusions: list[ActivationExclusion] = []
    root = evidence.evidence_root.replace("\\", "/").casefold()
    if root.startswith("test_runs/"):
        exclusions.append(
            ActivationExclusion(
                code="test_run",
                detail="candidate evidence root is below test_runs",
            )
        )
    if ".pytest" in root or "/pytest-" in root or "/pytest_tmp/" in root:
        exclusions.append(
            ActivationExclusion(
                code="pytest_basetemp",
                detail="candidate evidence root is a pytest temporary workspace",
            )
        )
    kind_codes = {
        "test_run": "test_run",
        "pytest_basetemp": "pytest_basetemp",
        "copied_workspace": "copied_workspace",
        "local_clone": "local_clone",
        "shadow_job": "shadow_job",
        "preflight_copy": "preflight_copy",
        "staging_copy": "staging_copy",
        "recovery_copy": "recovery_copy",
        "audit_directory": "audit_directory",
        "report_only_fixture": "report_only_fixture",
        "review_bundle": "review_bundle",
    }
    code = kind_codes.get(evidence.classification.kind)
    if code is not None:
        exclusions.append(
            ActivationExclusion(
                code=code,
                detail=f"candidate classification is {evidence.classification.kind}",
            )
        )
    if not evidence.classification.authoritative:
        exclusions.append(
            ActivationExclusion(
                code="nonauthoritative_evidence",
                detail="candidate evidence is not authoritative job evidence",
            )
        )
    return exclusions


def _terminal_exclusions(evidence: ActivationAssetEvidence) -> list[ActivationExclusion]:
    """Reject all failed, blocked, cancelled, and nonterminal activation attempts."""

    if evidence.terminal_state == "completed":
        return []
    return [
        ActivationExclusion(
            code=f"terminal_{evidence.terminal_state}",
            detail=f"candidate terminal state is {evidence.terminal_state}",
        )
    ]


def _evidence_artifacts(evidence: ActivationAssetEvidence) -> list[ActivationArtifact]:
    """Flatten every direct and validator-owned artifact in one candidate contract."""

    return [
        evidence.primary_reference,
        evidence.candidate_artifact,
        evidence.final_artifact,
        evidence.source_activation_baseline,
        *[artifact for check in evidence.checks for artifact in check.artifacts],
    ]


def _artifact_exclusions(
    root: Path,
    evidence: ActivationAssetEvidence,
) -> list[ActivationExclusion]:
    """Rehash all candidate artifacts and return deterministic fail-closed reasons."""

    exclusions: list[ActivationExclusion] = []
    seen: set[tuple[str, str, int]] = set()
    for artifact in _evidence_artifacts(evidence):
        binding = (artifact.path, artifact.sha256, artifact.byte_size)
        if binding in seen:
            continue
        seen.add(binding)
        try:
            _validate_artifact(root, artifact)
        except (OSError, ValueError, ActivationValidationError) as exc:
            exclusions.append(
                ActivationExclusion(
                    code="stale_tampered_missing_or_unknown_evidence",
                    detail=f"{artifact.path}: {_bounded_error_detail(exc)}"[:1000],
                )
            )
    return exclusions


def evaluate_activation_asset_eligibility(
    root: Path,
    *,
    evidence: ActivationAssetEvidence,
    expected_baseline_artifact: ActivationArtifact,
    output_path: Path,
    generated_at: datetime | None = None,
) -> tuple[ActivationAssetEligibilityReport, ActivationArtifact]:
    """Evaluate one explicit evidence set without scanning or trusting path names alone."""

    repository = root.expanduser().resolve(strict=True)
    exclusions: list[ActivationExclusion] = []
    exclusions.extend(_classification_exclusions(evidence))
    exclusions.extend(_terminal_exclusions(evidence))
    if evidence.canonical_disposition == "superseded":
        exclusions.append(
            ActivationExclusion(
                code="superseded_revision",
                detail="candidate revision has an exact superseding candidate",
            )
        )
    elif evidence.canonical_disposition == "unknown":
        exclusions.append(
            ActivationExclusion(
                code="unknown_canonical_representative",
                detail="candidate has no unique canonical disposition",
            )
        )
    try:
        baseline = load_activation_baseline(repository, expected_baseline_artifact)
    except (OSError, ValueError, ActivationValidationError) as exc:
        baseline = None
        exclusions.append(
            ActivationExclusion(
                code="stale_tampered_or_missing_baseline",
                detail=_bounded_error_detail(exc),
            )
        )
    if (
        evidence.source_activation_baseline != expected_baseline_artifact
        or baseline is None
        or evidence.source_activation_baseline_id != baseline.baseline_id
        or evidence.source_activation_baseline_sha256 != baseline.baseline_sha256
    ):
        exclusions.append(
            ActivationExclusion(
                code="source_baseline_mismatch",
                detail="candidate source baseline differs from the indexing baseline",
            )
        )
    checks = {item.check_id: item for item in evidence.checks}
    for check_id in sorted(_REQUIRED_ELIGIBILITY_CHECKS):
        check = checks.get(check_id)
        if check is None:
            code = (
                "missing_policy_decision_receipt"
                if check_id == "policy_decision_chain"
                else "empty_eligibility_dependency"
                if check_id == "dependency_closure"
                else f"missing_{check_id}"
            )
            exclusions.append(
                ActivationExclusion(
                    code=code,
                    detail=f"required activation check is absent: {check_id}",
                )
            )
            continue
        if check.status != "passed":
            exclusions.append(
                ActivationExclusion(
                    code=f"{check_id}_{check.status}",
                    detail=check.detail,
                )
            )
        if not check.artifacts:
            exclusions.append(
                ActivationExclusion(
                    code=f"{check_id}_has_no_evidence",
                    detail=f"required activation check has no exact artifact: {check_id}",
                )
            )
    policy = checks.get("policy_decision_chain")
    if policy is not None:
        kinds = {item.kind for item in policy.artifacts}
        if "policy_authorization" not in kinds or "policy_decision_receipt" not in kinds:
            exclusions.append(
                ActivationExclusion(
                    code="missing_policy_decision_receipt",
                    detail="policy chain lacks both authorization and decision receipt",
                )
            )
    dependencies = checks.get("dependency_closure")
    if dependencies is not None and not any(
        item.kind == "eligibility_dependency" for item in dependencies.artifacts
    ):
        exclusions.append(
            ActivationExclusion(
                code="empty_eligibility_dependency",
                detail="dependency closure contains no exact eligibility dependency",
            )
        )
    artifact_binding = checks.get("artifact_binding")
    if artifact_binding is not None and (
        evidence.candidate_artifact not in artifact_binding.artifacts
        or evidence.final_artifact not in artifact_binding.artifacts
    ):
        exclusions.append(
            ActivationExclusion(
                code="candidate_or_final_artifact_unbound",
                detail="artifact binding does not contain the exact candidate and final artifacts",
            )
        )
    baseline_binding = checks.get("source_baseline_binding")
    if (
        baseline_binding is not None
        and evidence.source_activation_baseline not in baseline_binding.artifacts
    ):
        exclusions.append(
            ActivationExclusion(
                code="source_baseline_artifact_unbound",
                detail="source baseline check does not contain the exact baseline artifact",
            )
        )
    exclusions.extend(_artifact_exclusions(repository, evidence))
    exclusions = _unique_exclusions(exclusions)
    payload: dict[str, Any] = {
        "evidence": evidence,
        "eligible": not exclusions,
        "exclusion_reasons": exclusions,
        "generated_at": _utc_now(generated_at),
    }
    report = _build_contract(
        ActivationAssetEligibilityReport,
        payload,
        prefix="activation-eligibility",
        id_field="report_id",
        digest_field="report_sha256",
    )
    artifact = _write_contract(
        repository,
        output_path,
        report,
        artifact_id=report.report_id,
        kind="activation_asset_eligibility_report",
    )
    return report, artifact


def write_activation_candidate_registry(
    root: Path,
    *,
    entries: Sequence[ActivationCandidateRegistryEntry],
    output_path: Path,
    generated_at: datetime | None = None,
) -> tuple[ActivationAssetCandidateRegistry, ActivationArtifact]:
    """Create one explicit authoritative registry without discovering candidate roots."""

    repository = root.expanduser().resolve(strict=True)
    ordered = sorted(entries, key=lambda item: item.candidate_id)
    for entry in ordered:
        _validate_artifact(repository, entry.eligibility_report)
    registry_digest = stable_json_digest(
        [item.model_dump(mode="json") for item in ordered]
    )
    registry = ActivationAssetCandidateRegistry(
        registry_id=f"activation-registry-{registry_digest[:24]}",
        entries=ordered,
        generated_at=_utc_now(generated_at),
    )
    artifact = _write_contract(
        repository,
        output_path,
        registry,
        artifact_id=registry.registry_id,
        kind="activation_asset_candidate_registry",
    )
    return registry, artifact


def build_activation_asset_candidate_index(
    root: Path,
    *,
    registry_artifact: ActivationArtifact,
    expected_baseline_artifact: ActivationArtifact,
    output_path: Path,
    generated_at: datetime | None = None,
) -> tuple[ActivationAssetCandidateIndex, ActivationArtifact]:
    """Index only registered reports and deduplicate them by primary-reference bytes."""

    repository = root.expanduser().resolve(strict=True)
    registry = _load_contract(
        repository,
        registry_artifact,
        ActivationAssetCandidateRegistry,
    )
    baseline = load_activation_baseline(repository, expected_baseline_artifact)
    records: list[ActivationAssetIndexRecord] = []
    for entry in registry.entries:
        report = _load_contract(
            repository,
            entry.eligibility_report,
            ActivationAssetEligibilityReport,
        )
        if report.evidence.candidate_id != entry.candidate_id:
            raise ActivationValidationError(
                "candidate registry identity differs from eligibility report"
            )
        reasons = list(report.exclusion_reasons)
        reasons.extend(_artifact_exclusions(repository, report.evidence))
        if (
            report.evidence.source_activation_baseline != expected_baseline_artifact
            or report.evidence.source_activation_baseline_id != baseline.baseline_id
            or report.evidence.source_activation_baseline_sha256
            != baseline.baseline_sha256
        ):
            reasons.append(
                ActivationExclusion(
                    code="source_baseline_mismatch",
                    detail="eligibility report belongs to another activation baseline",
                )
            )
        reasons = _unique_exclusions(reasons)
        records.append(
            ActivationAssetIndexRecord(
                candidate_id=entry.candidate_id,
                job_id=report.evidence.job_id,
                session_id=report.evidence.session_id,
                attempt_id=report.evidence.attempt_id,
                revision_id=report.evidence.revision_id,
                primary_reference_sha256=report.evidence.primary_reference.sha256,
                eligibility_report=entry.eligibility_report,
                eligible=report.eligible and not reasons,
                counted=False,
                exclusion_reasons=reasons,
            )
        )
    grouped: dict[str, list[ActivationAssetIndexRecord]] = defaultdict(list)
    for record in records:
        grouped[record.primary_reference_sha256].append(record)
    groups: list[ActivationReferenceDeduplicationGroup] = []
    updated: dict[str, ActivationAssetIndexRecord] = {}
    for reference_sha in sorted(grouped):
        members = sorted(grouped[reference_sha], key=lambda item: item.candidate_id)
        eligible = [item for item in members if item.eligible]
        representative: str | None = None
        status = "excluded"
        if len(eligible) == 1:
            representative = eligible[0].candidate_id
            status = "counted"
        elif len(eligible) > 1:
            status = "ambiguous"
            for item in eligible:
                updated[item.candidate_id] = item.model_copy(
                    update={
                        "eligible": False,
                        "exclusion_reasons": _unique_exclusions(
                            [
                                *item.exclusion_reasons,
                                ActivationExclusion(
                                    code="ambiguous_duplicate_group",
                                    detail=(
                                        "multiple terminal canonical candidates share one "
                                        "primary-reference hash"
                                    ),
                                ),
                            ]
                        ),
                    }
                )
        for item in members:
            current = updated.get(item.candidate_id, item)
            updated[item.candidate_id] = current.model_copy(
                update={"counted": current.candidate_id == representative}
            )
        candidate_ids = [item.candidate_id for item in members]
        groups.append(
            ActivationReferenceDeduplicationGroup(
                primary_reference_sha256=reference_sha,
                candidate_ids=candidate_ids,
                eligible_canonical_representative=representative,
                excluded_candidate_ids=[
                    item for item in candidate_ids if item != representative
                ],
                status=status,
                counted_asset_units=1 if representative is not None else 0,
                duplicate_count=len(candidate_ids) - 1,
            )
        )
    final_records = [
        updated[item.candidate_id]
        for item in sorted(records, key=lambda record: record.candidate_id)
    ]
    counted = sum(item.counted_asset_units for item in groups)
    payload: dict[str, Any] = {
        "authoritative_registry": registry_artifact,
        "source_activation_baseline": expected_baseline_artifact,
        "source_activation_baseline_id": baseline.baseline_id,
        "source_activation_baseline_sha256": baseline.baseline_sha256,
        "records": final_records,
        "deduplication_groups": groups,
        "distinct_asset_count": counted,
        "counted_asset_units": counted,
        "generated_at": _utc_now(generated_at),
    }
    index = _build_contract(
        ActivationAssetCandidateIndex,
        payload,
        prefix="activation-index",
        id_field="index_id",
        digest_field="index_sha256",
    )
    artifact = _write_contract(
        repository,
        output_path,
        index,
        artifact_id=index.index_id,
        kind="activation_asset_candidate_index",
    )
    return index, artifact


def _campaign_evidence_artifacts(
    evidence: ActivationCampaignOutcomeEvidence,
) -> list[ActivationArtifact]:
    """Flatten every exact artifact explicitly named by one campaign outcome."""

    return [
        evidence.source_activation_baseline,
        evidence.primary_reference,
        evidence.adapter_terminal,
        evidence.human_quality_disposition,
        *evidence.actual_blender_render_manifests,
    ]


def _validate_relative_hash_artifact(root: Path, artifact: Any) -> Path:
    """Revalidate one owner-relative artifact with optional exact byte size."""

    owner = root.expanduser().resolve(strict=True)
    path = ensure_contained_production_path(
        owner,
        owner / str(artifact.path),
        must_exist=True,
    )
    expected_size = getattr(artifact, "byte_size", None)
    size_mismatch = expected_size is not None and os.path.getsize(
        native_io_path(path)
    ) != int(expected_size)
    if not os.path.isfile(native_io_path(path)) or size_mismatch or sha256_file(
        path
    ) != str(artifact.sha256):
        raise ActivationValidationError(
            f"embedded AQ artifact changed: {artifact.path}"
        )
    return path


def _validate_embedded_aq_artifact(root: Path, artifact: Any) -> Path:
    """Revalidate one exact AQ artifact relative to its owning job root."""

    if getattr(artifact, "byte_size", None) is None:
        raise ActivationValidationError("AQ artifact omitted its exact byte size")
    return _validate_relative_hash_artifact(root, artifact)


def _campaign_job_root(
    repository: Path,
    evidence: ActivationCampaignOutcomeEvidence,
    adapter_path: Path,
) -> Path:
    """Derive and verify the exact job/run ownership of one adapter terminal."""

    run_root = adapter_path.parent
    skill_root = run_root.parent
    job_root = skill_root.parent
    if (
        adapter_path.name != "terminal.json"
        or run_root.name != evidence.skill_run_id
        or skill_root.name != "skill_runs"
        or job_root.name != evidence.job_id
    ):
        raise ActivationValidationError(
            "adapter terminal path differs from the declared campaign job and run"
        )
    return ensure_contained_production_path(repository, job_root, must_exist=True)


def _artifact_binding_matches(
    left_root: Path,
    left: Any,
    right_root: Path,
    right: Any,
) -> bool:
    """Compare two exact artifacts after resolving their different owner roots."""

    left_path = _validate_relative_hash_artifact(left_root, left)
    right_path = _validate_relative_hash_artifact(right_root, right)
    return (
        left_path == right_path
        and str(left.sha256) == str(right.sha256)
        and (
            getattr(left, "byte_size", None) is None
            or getattr(right, "byte_size", None) is None
            or int(left.byte_size) == int(right.byte_size)
        )
    )


def _validate_campaign_blender_manifests(
    repository: Path,
    evidence: ActivationCampaignOutcomeEvidence,
    disposition: ActivationHumanQualityDisposition,
) -> set[str]:
    """Validate actual Blender 5 seven-pass manifests and the disposition beauty."""

    from ..qa.models import RenderPassManifest

    disposition_beauty = _validate_artifact(
        repository,
        disposition.representative_beauty,
    )
    qa_run_ids: set[str] = set()
    beauty_matches = 0
    for artifact in evidence.actual_blender_render_manifests:
        if artifact.kind != "render_pass_manifest":
            raise ActivationValidationError(
                "campaign Blender evidence must be a render_pass_manifest"
            )
        manifest_path = _validate_artifact(repository, artifact)
        manifest = RenderPassManifest.model_validate_json(manifest_path.read_bytes())
        if (
            manifest.job_id != evidence.job_id
            or manifest.run_id is None
            or manifest.blender_version != "5.0.1"
        ):
            raise ActivationValidationError(
                "campaign render manifest differs from the supported job/runtime"
            )
        qa_run_ids.add(manifest.run_id)
        for rendered_pass in manifest.passes:
            pass_path = ensure_contained_production_path(
                manifest_path.parent,
                manifest_path.parent / rendered_pass.path,
                must_exist=True,
            )
            if sha256_file(pass_path) != rendered_pass.sha256:
                raise ActivationValidationError(
                    f"campaign render pass changed: {rendered_pass.path}"
                )
            if (
                rendered_pass.kind == "beauty"
                and pass_path == disposition_beauty
                and rendered_pass.sha256
                == disposition.representative_beauty.sha256
            ):
                beauty_matches += 1
    if beauty_matches != 1:
        raise ActivationValidationError(
            "human disposition beauty must match exactly one Blender render manifest"
        )
    return qa_run_ids


def _campaign_terminal_exclusions(
    root: Path,
    evidence: ActivationCampaignOutcomeEvidence,
    disposition: ActivationHumanQualityDisposition | None,
) -> tuple[list[ActivationExclusion], bool]:
    """Validate exact adapter, One-Prompt, package, review, and disposition evidence."""

    from ..autonomy_v2.approval_models import (
        AQV2ApprovalTelemetryReport,
        AQV2OnePromptRunPlan,
        AQV2OnePromptRunTerminal,
    )
    from ..autonomy_v2.delivery_service import validate_delivery_terminal_v2
    from ..autonomy_v2.models import (
        AutonomyPlanV2,
        QualityApprovedSourceFreeze,
        RootAuthorizationV2,
    )
    from ..autonomy_v2.quality_terminal_service import (
        validate_quality_review_bundle_v2,
    )
    from ..qa.models import VisualQAReport
    from ..skill_orchestration.models import (
        AQSkillAdapterPlan,
        AQSkillAdapterState,
        AQSkillAdapterTerminal,
    )

    exclusions: list[ActivationExclusion] = []
    package_verified = False
    try:
        adapter_path = _validate_artifact(root, evidence.adapter_terminal)
        job_root = _campaign_job_root(root, evidence, adapter_path)
        adapter = AQSkillAdapterTerminal.model_validate_json(
            adapter_path.read_bytes()
        )
    except (OSError, ValueError, ActivationValidationError) as exc:
        return [
            ActivationExclusion(
                code="invalid_adapter_terminal",
                detail=_bounded_error_detail(exc),
            )
        ], False
    try:
        adapter_plan_path = _validate_relative_hash_artifact(job_root, adapter.plan)
        adapter_state_path = _validate_relative_hash_artifact(
            job_root,
            adapter.final_state,
        )
        _validate_relative_hash_artifact(job_root, adapter.final_aq_state)
        _validate_relative_hash_artifact(job_root, adapter.authoritative_aq_terminal)
        adapter_plan = AQSkillAdapterPlan.model_validate_json(
            adapter_plan_path.read_bytes()
        )
        adapter_state = AQSkillAdapterState.model_validate_json(
            adapter_state_path.read_bytes()
        )
        if (
            (adapter_plan.job_id, adapter_plan.run_id, adapter_plan.session_id)
            != (evidence.job_id, evidence.skill_run_id, evidence.session_id)
            or (adapter_state.job_id, adapter_state.run_id, adapter_state.session_id)
            != (evidence.job_id, evidence.skill_run_id, evidence.session_id)
            or adapter_state.status != "terminal"
            or adapter_state.next_action is not None
        ):
            raise ActivationValidationError(
                "adapter plan or final state differs from the campaign identity"
            )
    except (OSError, ValueError, ActivationValidationError) as exc:
        exclusions.append(
            ActivationExclusion(
                code="invalid_adapter_projection",
                detail=_bounded_error_detail(exc),
            )
        )
        return _unique_exclusions(exclusions), False
    if (
        adapter.job_id != evidence.job_id
        or adapter.session_id != evidence.session_id
        or adapter.run_id != evidence.skill_run_id
    ):
        exclusions.append(
            ActivationExclusion(
                code="adapter_terminal_identity_mismatch",
                detail="adapter terminal differs from campaign outcome identity",
            )
        )
    expected_terminal_type = {
        "production_delivery": "production_delivery",
        "usable_review_terminal": "review_bundle",
        "blocked": "blocked",
        "failed": "reconciled_failed_recovery",
        "cancelled": "cancelled",
    }.get(evidence.terminal_class)
    if expected_terminal_type is None or adapter.terminal_type != expected_terminal_type:
        exclusions.append(
            ActivationExclusion(
                code="terminal_class_mismatch",
                detail="declared campaign terminal class differs from adapter evidence",
            )
        )
    if evidence.terminal_class not in {
        "production_delivery",
        "usable_review_terminal",
    }:
        exclusions.append(
            ActivationExclusion(
                code=f"terminal_{evidence.terminal_class}",
                detail=f"campaign outcome is {evidence.terminal_class}",
            )
        )
    expected_disposition = {
        "production_delivery": "accepted",
        "usable_review_terminal": "needs_revision",
    }.get(evidence.terminal_class)
    if (
        expected_disposition is not None
        and disposition is not None
        and disposition.disposition != expected_disposition
    ):
        exclusions.append(
            ActivationExclusion(
                code="quality_disposition_terminal_mismatch",
                detail=(
                    "human quality disposition differs from the declared normal "
                    "campaign terminal"
                ),
            )
        )
    if not adapter.campaign_terminal_candidate:
        exclusions.append(
            ActivationExclusion(
                code="adapter_terminal_not_candidate",
                detail="adapter terminal is not a normal campaign terminal candidate",
            )
        )
    if adapter.one_prompt_terminal is None:
        return _unique_exclusions(exclusions), False
    try:
        one_prompt_path = _validate_relative_hash_artifact(
            job_root,
            adapter.one_prompt_terminal,
        )
        one_prompt = AQV2OnePromptRunTerminal.model_validate_json(
            one_prompt_path.read_bytes()
        )
        one_prompt_plan_path = _validate_embedded_aq_artifact(
            job_root,
            one_prompt.one_prompt_plan,
        )
        one_prompt_plan = AQV2OnePromptRunPlan.model_validate_json(
            one_prompt_plan_path.read_bytes()
        )
        base_plan_path = _validate_embedded_aq_artifact(
            job_root,
            one_prompt_plan.base_autonomy_plan,
        )
        base_plan = AutonomyPlanV2.model_validate_json(base_plan_path.read_bytes())
        authorization_path = _validate_embedded_aq_artifact(
            job_root,
            base_plan.root_authorization,
        )
        authorization = RootAuthorizationV2.model_validate_json(
            authorization_path.read_bytes()
        )
        telemetry_path = _validate_embedded_aq_artifact(
            job_root,
            one_prompt.approval_telemetry,
        )
        telemetry = AQV2ApprovalTelemetryReport.model_validate_json(
            telemetry_path.read_bytes()
        )
        if (
            (one_prompt.job_id, one_prompt.session_id)
            != (evidence.job_id, evidence.session_id)
            or (one_prompt_plan.job_id, one_prompt_plan.session_id)
            != (evidence.job_id, evidence.session_id)
            or (base_plan.job_id, base_plan.session_id)
            != (evidence.job_id, evidence.session_id)
            or (authorization.job_id, authorization.session_id)
            != (evidence.job_id, evidence.session_id)
            or one_prompt.one_prompt_plan.path != adapter_plan.one_prompt_plan.path
            or one_prompt.one_prompt_plan.sha256 != adapter_plan.one_prompt_plan.sha256
            or one_prompt.final_autonomy_state.path != adapter.final_aq_state.path
            or one_prompt.final_autonomy_state.sha256 != adapter.final_aq_state.sha256
        ):
            raise ActivationValidationError(
                "One-Prompt authority chain differs from the campaign adapter"
            )
        if not _artifact_binding_matches(
            root,
            evidence.primary_reference,
            job_root,
            authorization.primary_reference,
        ):
            raise ActivationValidationError(
                "campaign primary reference differs from RootAuthorizationV2"
            )
        if (
            telemetry.initial_user_request_count != evidence.initial_request_count
            or telemetry.additional_user_decision_count
            != evidence.additional_user_decision_count
            or telemetry.technical_user_approval_request_count
            != evidence.technical_user_approval_count
            or telemetry.canonical_corruption_count
            != evidence.canonical_corruption_count
            or telemetry.terminal_type != one_prompt.terminal_type
            or one_prompt.canonical_restored_after_rollback
            != evidence.rollback_integrity_preserved
            or telemetry.blender_build_count < 1
            or telemetry.quality_evaluation_count < 1
        ):
            raise ActivationValidationError(
                "campaign KPI counters differ from host-replayed One-Prompt telemetry"
            )
        if disposition is None:
            raise ActivationValidationError(
                "campaign terminal requires a valid exact human disposition"
            )
        qa_run_ids = _validate_campaign_blender_manifests(
            root,
            evidence,
            disposition,
        )
    except (OSError, ValueError, ActivationValidationError) as exc:
        exclusions.append(
            ActivationExclusion(
                code="invalid_one_prompt_terminal",
                detail=_bounded_error_detail(exc),
            )
        )
        return _unique_exclusions(exclusions), False
    if evidence.terminal_class == "production_delivery":
        if one_prompt.delivery_terminal is None:
            exclusions.append(
                ActivationExclusion(
                    code="missing_production_delivery_terminal",
                    detail="One-Prompt terminal omitted delivery evidence",
                )
            )
        else:
            try:
                delivery = validate_delivery_terminal_v2(
                    job_root,
                    one_prompt.delivery_terminal,
                )
                if (
                    delivery.outcome != "completed"
                    or any(
                        item.status != "completed" or not item.production_ready
                        for item in delivery.results
                    )
                ):
                    raise ActivationValidationError(
                        "delivery terminal is not fully production-ready"
                    )
                for result in delivery.results:
                    if result.package_manifest is None or result.roundtrip_validation is None:
                        raise ActivationValidationError(
                            "completed delivery omitted package or clean-import evidence"
                        )
                    _validate_embedded_aq_artifact(job_root, result.package_manifest)
                    _validate_embedded_aq_artifact(job_root, result.roundtrip_validation)
                freeze_path = _validate_embedded_aq_artifact(
                    job_root,
                    delivery.source_freeze,
                )
                freeze = QualityApprovedSourceFreeze.model_validate_json(
                    freeze_path.read_bytes()
                )
                visual_qa_runs: set[str] = set()
                for artifact in freeze.quality_evidence:
                    if artifact.kind != "visual_qa_report":
                        continue
                    report_path = _validate_embedded_aq_artifact(job_root, artifact)
                    report = VisualQAReport.model_validate_json(report_path.read_bytes())
                    visual_qa_runs.add(report.run_id)
                if not qa_run_ids.intersection(visual_qa_runs):
                    raise ActivationValidationError(
                        "campaign Blender manifest is outside the accepted quality freeze"
                    )
                package_verified = True
            except (OSError, ValueError, PermissionError, ActivationValidationError) as exc:
                exclusions.append(
                    ActivationExclusion(
                        code="invalid_production_package_evidence",
                        detail=_bounded_error_detail(exc),
                    )
                )
    elif evidence.terminal_class == "usable_review_terminal":
        if one_prompt.review_bundle is None:
            exclusions.append(
                ActivationExclusion(
                    code="missing_usable_review_bundle",
                    detail="One-Prompt terminal omitted review-bundle evidence",
                )
            )
        else:
            try:
                review = validate_quality_review_bundle_v2(
                    job_root,
                    one_prompt.review_bundle,
                )
                if (
                    len(review.recommended_actions)
                    != evidence.actionable_review_action_count
                ):
                    raise ActivationValidationError(
                        "review action count differs from exact review bundle"
                    )
                if disposition is None or not _artifact_binding_matches(
                    root,
                    disposition.representative_beauty,
                    job_root,
                    review.representative_render,
                ):
                    raise ActivationValidationError(
                        "review terminal differs from the disposition beauty"
                    )
            except (OSError, ValueError, PermissionError, ActivationValidationError) as exc:
                exclusions.append(
                    ActivationExclusion(
                        code="invalid_usable_review_bundle",
                        detail=_bounded_error_detail(exc),
                    )
                )
    return _unique_exclusions(exclusions), package_verified


def evaluate_activation_campaign_outcome(
    root: Path,
    *,
    evidence: ActivationCampaignOutcomeEvidence,
    expected_baseline_artifact: ActivationArtifact,
    output_path: Path,
    generated_at: datetime | None = None,
) -> tuple[ActivationCampaignOutcomeEligibilityReport, ActivationArtifact]:
    """Evaluate one explicit AQ terminal against local first-completion criteria."""

    repository = root.expanduser().resolve(strict=True)
    exclusions: list[ActivationExclusion] = []
    try:
        baseline = load_activation_baseline(repository, expected_baseline_artifact)
    except (OSError, ValueError, ActivationValidationError) as exc:
        baseline = None
        exclusions.append(
            ActivationExclusion(
                code="stale_tampered_or_missing_baseline",
                detail=_bounded_error_detail(exc),
            )
        )
    if (
        baseline is None
        or evidence.source_activation_baseline != expected_baseline_artifact
        or evidence.source_activation_baseline_id != baseline.baseline_id
        or evidence.source_activation_baseline_sha256 != baseline.baseline_sha256
    ):
        exclusions.append(
            ActivationExclusion(
                code="source_baseline_mismatch",
                detail="campaign outcome belongs to another activation baseline",
            )
        )
    for artifact in _campaign_evidence_artifacts(evidence):
        try:
            _validate_artifact(repository, artifact)
        except (OSError, ValueError, ActivationValidationError) as exc:
            exclusions.append(
                ActivationExclusion(
                    code="stale_tampered_missing_or_unknown_evidence",
                    detail=f"{artifact.path}: {_bounded_error_detail(exc)}"[:1000],
                )
            )
    disposition: ActivationHumanQualityDisposition | None = None
    try:
        disposition = _load_contract(
            repository,
            evidence.human_quality_disposition,
            ActivationHumanQualityDisposition,
        )
        if (
            disposition.job_id != evidence.job_id
            or disposition.skill_run_id != evidence.skill_run_id
        ):
            raise ActivationValidationError(
                "human quality disposition differs from campaign identity"
            )
        _validate_artifact(repository, disposition.representative_beauty)
    except (OSError, ValueError, ActivationValidationError) as exc:
        exclusions.append(
            ActivationExclusion(
                code="invalid_human_quality_disposition",
                detail=_bounded_error_detail(exc),
            )
        )
    terminal_exclusions, package_verified = _campaign_terminal_exclusions(
        repository,
        evidence,
        disposition,
    )
    exclusions.extend(terminal_exclusions)
    numeric_requirements = (
        ("additional_user_decisions", evidence.additional_user_decision_count),
        ("technical_user_approvals", evidence.technical_user_approval_count),
        ("canonical_corruption", evidence.canonical_corruption_count),
        ("unresolved_next_actions", evidence.unresolved_next_action_count),
    )
    for code, value in numeric_requirements:
        if value:
            exclusions.append(
                ActivationExclusion(
                    code=code,
                    detail=f"campaign outcome records {value} {code}",
                )
            )
    if not evidence.rollback_integrity_preserved:
        exclusions.append(
            ActivationExclusion(
                code="rollback_integrity_failed",
                detail="campaign outcome did not preserve rollback integrity",
            )
        )
    exclusions = _unique_exclusions(exclusions)
    eligible = not exclusions
    payload: dict[str, Any] = {
        "evidence": evidence,
        "eligible": eligible,
        "production_package_verified": eligible and package_verified,
        "exclusion_reasons": exclusions,
        "generated_at": _utc_now(generated_at),
    }
    report = _build_contract(
        ActivationCampaignOutcomeEligibilityReport,
        payload,
        prefix="activation-campaign-eligibility",
        id_field="report_id",
        digest_field="report_sha256",
    )
    artifact = _write_contract(
        repository,
        output_path,
        report,
        artifact_id=report.report_id,
        kind="activation_campaign_eligibility_report",
    )
    return report, artifact


def write_activation_campaign_registry(
    root: Path,
    *,
    entries: Sequence[ActivationCampaignRegistryEntry],
    output_path: Path,
    generated_at: datetime | None = None,
) -> tuple[ActivationCampaignOutcomeRegistry, ActivationArtifact]:
    """Create one explicit authoritative campaign registry without discovery."""

    repository = root.expanduser().resolve(strict=True)
    ordered = sorted(entries, key=lambda item: item.outcome_id)
    for entry in ordered:
        _validate_artifact(repository, entry.eligibility_report)
    digest = stable_json_digest([item.model_dump(mode="json") for item in ordered])
    registry = ActivationCampaignOutcomeRegistry(
        registry_id=f"activation-campaign-registry-{digest[:24]}",
        entries=ordered,
        generated_at=_utc_now(generated_at),
    )
    artifact = _write_contract(
        repository,
        output_path,
        registry,
        artifact_id=registry.registry_id,
        kind="activation_campaign_outcome_registry",
    )
    return registry, artifact


def build_activation_campaign_outcome_index(
    root: Path,
    *,
    registry_artifact: ActivationArtifact,
    expected_baseline_artifact: ActivationArtifact,
    output_path: Path,
    generated_at: datetime | None = None,
) -> tuple[ActivationCampaignOutcomeIndex, ActivationArtifact]:
    """Index explicitly registered normal terminals by distinct reference content."""

    repository = root.expanduser().resolve(strict=True)
    registry = _load_contract(
        repository,
        registry_artifact,
        ActivationCampaignOutcomeRegistry,
    )
    baseline = load_activation_baseline(repository, expected_baseline_artifact)
    records: list[ActivationCampaignOutcomeIndexRecord] = []
    for entry in registry.entries:
        report = _load_contract(
            repository,
            entry.eligibility_report,
            ActivationCampaignOutcomeEligibilityReport,
        )
        if report.evidence.outcome_id != entry.outcome_id:
            raise ActivationValidationError(
                "campaign registry identity differs from eligibility report"
            )
        reasons = list(report.exclusion_reasons)
        if (
            report.evidence.source_activation_baseline
            != expected_baseline_artifact
            or report.evidence.source_activation_baseline_id != baseline.baseline_id
            or report.evidence.source_activation_baseline_sha256
            != baseline.baseline_sha256
        ):
            reasons.append(
                ActivationExclusion(
                    code="source_baseline_mismatch",
                    detail="campaign report belongs to another activation baseline",
                )
            )
        for artifact in _campaign_evidence_artifacts(report.evidence):
            try:
                _validate_artifact(repository, artifact)
            except (OSError, ValueError, ActivationValidationError) as exc:
                reasons.append(
                    ActivationExclusion(
                        code="stale_tampered_missing_or_unknown_evidence",
                        detail=f"{artifact.path}: {_bounded_error_detail(exc)}"[:1000],
                    )
                )
        reasons = _unique_exclusions(reasons)
        records.append(
            ActivationCampaignOutcomeIndexRecord(
                outcome_id=entry.outcome_id,
                job_id=report.evidence.job_id,
                session_id=report.evidence.session_id,
                skill_run_id=report.evidence.skill_run_id,
                primary_reference_sha256=report.evidence.primary_reference.sha256,
                terminal_class=report.evidence.terminal_class,
                eligibility_report=entry.eligibility_report,
                eligible=report.eligible and not reasons,
                counted=False,
                production_package_verified=(
                    report.production_package_verified and not reasons
                ),
                exclusion_reasons=reasons,
            )
        )
    grouped: dict[str, list[ActivationCampaignOutcomeIndexRecord]] = defaultdict(list)
    for record in records:
        grouped[record.primary_reference_sha256].append(record)
    groups: list[ActivationCampaignReferenceGroup] = []
    updated: dict[str, ActivationCampaignOutcomeIndexRecord] = {}
    for reference_sha in sorted(grouped):
        members = sorted(grouped[reference_sha], key=lambda item: item.outcome_id)
        eligible = [item for item in members if item.eligible]
        representative: str | None = None
        status = "excluded"
        if len(eligible) == 1:
            representative = eligible[0].outcome_id
            status = "counted"
        elif len(eligible) > 1:
            status = "ambiguous"
            for item in eligible:
                updated[item.outcome_id] = item.model_copy(
                    update={
                        "eligible": False,
                        "production_package_verified": False,
                        "exclusion_reasons": _unique_exclusions(
                            [
                                *item.exclusion_reasons,
                                ActivationExclusion(
                                    code="ambiguous_campaign_reference",
                                    detail=(
                                        "multiple eligible outcomes share one primary "
                                        "reference hash"
                                    ),
                                ),
                            ]
                        ),
                    }
                )
        for item in members:
            current = updated.get(item.outcome_id, item)
            updated[item.outcome_id] = current.model_copy(
                update={"counted": current.outcome_id == representative}
            )
        selected = next(
            (item for item in members if item.outcome_id == representative),
            None,
        )
        groups.append(
            ActivationCampaignReferenceGroup(
                primary_reference_sha256=reference_sha,
                outcome_ids=[item.outcome_id for item in members],
                eligible_representative=representative,
                status=status,
                counted_asset_units=1 if representative is not None else 0,
                production_package_units=(
                    1
                    if selected is not None and selected.production_package_verified
                    else 0
                ),
            )
        )
    final_records = [
        updated[item.outcome_id]
        for item in sorted(records, key=lambda entry: entry.outcome_id)
    ]
    counted_records = [item for item in final_records if item.counted]
    payload: dict[str, Any] = {
        "authoritative_registry": registry_artifact,
        "source_activation_baseline": expected_baseline_artifact,
        "source_activation_baseline_id": baseline.baseline_id,
        "source_activation_baseline_sha256": baseline.baseline_sha256,
        "records": final_records,
        "reference_groups": groups,
        "distinct_successful_asset_count": len(counted_records),
        "production_delivery_count": sum(
            item.terminal_class == "production_delivery" for item in counted_records
        ),
        "usable_review_terminal_count": sum(
            item.terminal_class == "usable_review_terminal"
            for item in counted_records
        ),
        "production_package_count": sum(
            item.production_package_verified for item in counted_records
        ),
        "generated_at": _utc_now(generated_at),
    }
    index = _build_contract(
        ActivationCampaignOutcomeIndex,
        payload,
        prefix="activation-campaign-index",
        id_field="index_id",
        digest_field="index_sha256",
    )
    artifact = _write_contract(
        repository,
        output_path,
        index,
        artifact_id=index.index_id,
        kind="activation_campaign_outcome_index",
    )
    return index, artifact


def validate_human_local_activation_acceptance(
    root: Path,
    *,
    baseline_artifact: ActivationArtifact,
    campaign_outcome_index_artifact: ActivationArtifact,
    acceptance_artifact: ActivationArtifact | None,
    observed_at: datetime | None = None,
) -> HumanLocalActivationAcceptance:
    """Validate exact five-outcome human authority without consuming it."""

    if acceptance_artifact is None:
        raise PermissionError("local profile publication requires exact human acceptance")
    _require_disabled_activation_profile()
    repository = root.expanduser().resolve(strict=True)
    baseline = load_activation_baseline(repository, baseline_artifact)
    index = _load_contract(
        repository,
        campaign_outcome_index_artifact,
        ActivationCampaignOutcomeIndex,
    )
    acceptance = _load_contract(
        repository,
        acceptance_artifact,
        HumanLocalActivationAcceptance,
    )
    hashes = sorted(
        item.primary_reference_sha256
        for item in index.reference_groups
        if item.counted_asset_units == 1
    )
    now = _utc_now(observed_at)
    if (
        index.source_activation_baseline != baseline_artifact
        or index.source_activation_baseline_id != baseline.baseline_id
        or index.source_activation_baseline_sha256 != baseline.baseline_sha256
        or acceptance.activation_baseline != baseline_artifact
        or acceptance.activation_baseline_id != baseline.baseline_id
        or acceptance.activation_baseline_sha256 != baseline.baseline_sha256
        or acceptance.campaign_outcome_index != campaign_outcome_index_artifact
        or acceptance.campaign_outcome_index_id != index.index_id
        or acceptance.campaign_outcome_index_sha256 != index.index_sha256
        or acceptance.distinct_primary_reference_sha256s != hashes
        or index.distinct_successful_asset_count != 5
        or index.production_package_count < 1
        or not (acceptance.created_at <= now < acceptance.expires_at)
    ):
        raise PermissionError("human local activation acceptance is stale or incomplete")
    consumption = (
        repository
        / "reports"
        / "activation_readiness"
        / "local_acceptance_consumptions"
        / f"{acceptance.acceptance_id}.json"
    )
    if consumption.exists():
        raise PermissionError("human local activation acceptance was already consumed")
    return acceptance


def create_local_activation_readiness_report(
    root: Path,
    *,
    source_manifest_artifact: ActivationArtifact,
    baseline_artifact: ActivationArtifact,
    production_candidate_index_artifact: ActivationArtifact | None = None,
    campaign_outcome_index_artifact: ActivationArtifact | None = None,
    human_acceptance_artifact: ActivationArtifact | None = None,
    validation_blockers: Sequence[ActivationReadinessFinding] = (),
    output_path: Path | None = None,
    generated_at: datetime | None = None,
) -> tuple[LocalActivationReadinessReport, ActivationArtifact | None]:
    """Publish structured local readiness while separating future limitations."""

    repository = root.expanduser().resolve(strict=True)
    profile = _require_disabled_activation_profile()
    manifest = load_activation_source_manifest(repository, source_manifest_artifact)
    baseline = load_activation_baseline(repository, baseline_artifact)
    blockers = list(validation_blockers)
    if (
        baseline.source_manifest != source_manifest_artifact
        or baseline.source_manifest_id != manifest.manifest_id
        or baseline.source_manifest_sha256 != manifest.manifest_sha256
    ):
        blockers.append(
            ActivationReadinessFinding(
                finding_id="source_manifest_baseline_mismatch",
                detail="Activation baseline differs from its exact source manifest.",
            )
        )
    if production_candidate_index_artifact is not None:
        production_index = _load_contract(
            repository,
            production_candidate_index_artifact,
            ActivationAssetCandidateIndex,
        )
        if production_index.source_activation_baseline != baseline_artifact:
            blockers.append(
                ActivationReadinessFinding(
                    finding_id="production_index_baseline_mismatch",
                    detail="Strict production candidate index belongs to another baseline.",
                )
            )
    campaign_count = 0
    package_count = 0
    campaign_index = None
    if campaign_outcome_index_artifact is not None:
        campaign_index = _load_contract(
            repository,
            campaign_outcome_index_artifact,
            ActivationCampaignOutcomeIndex,
        )
        if campaign_index.source_activation_baseline != baseline_artifact:
            blockers.append(
                ActivationReadinessFinding(
                    finding_id="campaign_index_baseline_mismatch",
                    detail="Campaign outcome index belongs to another baseline.",
                )
            )
        else:
            campaign_count = campaign_index.distinct_successful_asset_count
            package_count = campaign_index.production_package_count
            if campaign_count > 5:
                blockers.append(
                    ActivationReadinessFinding(
                        finding_id="campaign_outcome_count_exceeds_target",
                        detail=(
                            "Campaign index must register exactly five distinct normal "
                            "outcomes for local Activation."
                        ),
                    )
                )
    accepted = None
    if human_acceptance_artifact is not None:
        if campaign_outcome_index_artifact is None:
            blockers.append(
                ActivationReadinessFinding(
                    finding_id="human_acceptance_without_campaign_index",
                    detail="Human activation acceptance has no campaign outcome index.",
                )
            )
        else:
            accepted = validate_human_local_activation_acceptance(
                repository,
                baseline_artifact=baseline_artifact,
                campaign_outcome_index_artifact=campaign_outcome_index_artifact,
                acceptance_artifact=human_acceptance_artifact,
                observed_at=generated_at,
            )
    open_requirements: list[ActivationReadinessFinding] = []
    if campaign_count < 5:
        open_requirements.append(
            ActivationReadinessFinding(
                finding_id="current_baseline_five_outcomes_required",
                detail=f"Current baseline has {campaign_count}/5 distinct normal outcomes.",
            )
        )
    if package_count < 1:
        open_requirements.append(
            ActivationReadinessFinding(
                finding_id="current_baseline_package_required",
                detail="At least one production package and clean import are required.",
            )
        )
    if accepted is None:
        open_requirements.append(
            ActivationReadinessFinding(
                finding_id="exact_human_local_activation_acceptance_required",
                detail="Exact single-use human local-profile acceptance is required.",
            )
        )
    excluded_details = list(profile.get("excluded_capabilities", []))
    excluded = [
        ActivationReadinessFinding(
            finding_id=str(capability),
            detail=f"Capability is outside local base scope: {capability}.",
        )
        for capability in excluded_details
    ]
    future_ids = [
        "desktop_sandbox_not_attested",
        "client_mediated_controller_unverified",
        "destination_runtime_parity_unverified",
    ]
    future_details = list(profile.get("future_limitations", []))
    future = [
        ActivationReadinessFinding(finding_id=finding_id, detail=str(detail))
        for finding_id, detail in zip(future_ids, future_details, strict=True)
    ]
    blockers = sorted(blockers, key=lambda item: item.finding_id)
    open_requirements = sorted(open_requirements, key=lambda item: item.finding_id)
    status = "ready_for_fresh_campaign"
    if blockers:
        status = "validation_blocked"
    elif campaign_count == 5 and package_count >= 1 and accepted is not None:
        status = "ready_for_profile_publication"
    elif campaign_count == 5 and package_count >= 1:
        status = "ready_for_human_activation_acceptance"
    elif campaign_count:
        status = "campaign_in_progress"
    payload: dict[str, Any] = {
        "status": status,
        "source_manifest": source_manifest_artifact,
        "activation_baseline": baseline_artifact,
        "production_candidate_index": production_candidate_index_artifact,
        "campaign_outcome_index": campaign_outcome_index_artifact,
        "distinct_campaign_outcome_count": campaign_count,
        "production_package_count": package_count,
        "exact_human_activation_acceptance": human_acceptance_artifact,
        "validation_blockers": blockers,
        "open_requirements": open_requirements,
        "excluded_capabilities": sorted(excluded, key=lambda item: item.finding_id),
        "future_limitations": sorted(future, key=lambda item: item.finding_id),
        "generated_at": _utc_now(generated_at),
    }
    report = _build_contract(
        LocalActivationReadinessReport,
        payload,
        prefix="local-activation-readiness",
        id_field="report_id",
        digest_field="report_sha256",
    )
    artifact = None
    if output_path is not None:
        artifact = _write_contract(
            repository,
            output_path,
            report,
            artifact_id=report.report_id,
            kind="local_activation_readiness_report",
        )
    return report, artifact


def validate_human_activation_acceptance(
    root: Path,
    *,
    baseline_artifact: ActivationArtifact,
    candidate_index_artifact: ActivationArtifact,
    acceptance_artifact: ActivationArtifact | None,
    expected_asset_count: int = 5,
    observed_at: datetime | None = None,
) -> HumanActivationAcceptance:
    """Require exact unused human acceptance before any external profile activation."""

    if acceptance_artifact is None:
        raise PermissionError(
            "profile activation requires exact HumanActivationAcceptance"
        )
    _require_disabled_activation_profile()
    repository = root.expanduser().resolve(strict=True)
    baseline = load_activation_baseline(repository, baseline_artifact)
    index = _load_contract(
        repository,
        candidate_index_artifact,
        ActivationAssetCandidateIndex,
    )
    acceptance = _load_contract(
        repository,
        acceptance_artifact,
        HumanActivationAcceptance,
    )
    counted_hashes = sorted(
        group.primary_reference_sha256
        for group in index.deduplication_groups
        if group.counted_asset_units == 1
    )
    now = _utc_now(observed_at)
    if (
        index.source_activation_baseline != baseline_artifact
        or index.source_activation_baseline_id != baseline.baseline_id
        or index.source_activation_baseline_sha256 != baseline.baseline_sha256
        or acceptance.activation_baseline != baseline_artifact
        or acceptance.activation_baseline_id != baseline.baseline_id
        or acceptance.activation_baseline_sha256 != baseline.baseline_sha256
        or acceptance.candidate_index != candidate_index_artifact
        or acceptance.candidate_index_id != index.index_id
        or acceptance.candidate_index_sha256 != index.index_sha256
        or acceptance.distinct_primary_reference_sha256s != counted_hashes
        or index.distinct_asset_count != expected_asset_count
        or acceptance.profile_id != ACTIVATION_PROFILE_ID
        or acceptance.profile_version != ACTIVATION_PROFILE_VERSION
        or not (acceptance.created_at <= now < acceptance.expires_at)
    ):
        raise PermissionError("human activation acceptance binding is stale or incomplete")
    consumption = (
        repository
        / "reports"
        / "activation_readiness"
        / "acceptance_consumptions"
        / f"{acceptance.acceptance_id}.json"
    )
    if consumption.exists():
        raise PermissionError("human activation acceptance was already consumed")
    return acceptance


def create_activation_readiness_report(
    root: Path,
    *,
    source_manifest_artifact: ActivationArtifact | None,
    baseline_artifact: ActivationArtifact | None,
    candidate_index_artifact: ActivationArtifact | None = None,
    validation_blockers: Sequence[str] = (),
    output_path: Path | None = None,
    generated_at: datetime | None = None,
) -> tuple[ActivationReadinessReport, ActivationArtifact | None]:
    """Report readiness or its exact blocker without accepting or activating a profile."""

    repository = root.expanduser().resolve(strict=True)
    blockers = sorted(set(validation_blockers))
    try:
        _require_disabled_activation_profile()
    except ActivationValidationError as exc:
        blockers = sorted(set([*blockers, str(exc)]))
    if blockers:
        status = "validation_blocked"
    elif baseline_artifact is None or source_manifest_artifact is None:
        status = "source_checkpoint_required"
        blockers = [
            "A clean committed source checkpoint and ActivationSourceManifest are required."
        ]
    else:
        baseline = load_activation_baseline(repository, baseline_artifact)
        manifest = load_activation_source_manifest(repository, source_manifest_artifact)
        if (
            baseline.source_manifest != source_manifest_artifact
            or baseline.source_manifest_id != manifest.manifest_id
            or baseline.source_manifest_sha256 != manifest.manifest_sha256
        ):
            status = "validation_blocked"
            blockers = ["ActivationBaseline differs from ActivationSourceManifest."]
        else:
            status = "ready_for_campaign_but_not_activated"
    if candidate_index_artifact is not None:
        index = _load_contract(
            repository,
            candidate_index_artifact,
            ActivationAssetCandidateIndex,
        )
        if baseline_artifact is None or index.source_activation_baseline != baseline_artifact:
            status = "validation_blocked"
            blockers = sorted(
                set([*blockers, "Candidate index belongs to another activation baseline."])
            )
    payload: dict[str, Any] = {
        "status": status,
        "source_manifest": source_manifest_artifact,
        "activation_baseline": baseline_artifact,
        "candidate_index": candidate_index_artifact,
        "blockers": blockers,
        "profile_id": ACTIVATION_PROFILE_ID,
        "profile_version": ACTIVATION_PROFILE_VERSION,
        "profile_status": "disabled_experimental",
        "human_activation_accepted": False,
        "campaign_created": False,
        "production_activation_performed": False,
        "generated_at": _utc_now(generated_at),
    }
    report = _build_contract(
        ActivationReadinessReport,
        payload,
        prefix="activation-readiness",
        id_field="report_id",
        digest_field="report_sha256",
    )
    artifact = None
    if output_path is not None:
        artifact = _write_contract(
            repository,
            output_path,
            report,
            artifact_id=report.report_id,
            kind="activation_readiness_report",
        )
    return report, artifact


def activation_contract_capability() -> dict[str, object]:
    """Expose additive readiness support without granting profile activation authority."""

    return {
        "contract_version": ACTIVATION_CONTRACT_VERSION,
        "profile_id": ACTIVATION_PROFILE_ID,
        "profile_version": ACTIVATION_PROFILE_VERSION,
        "status": "disabled_experimental",
        "source_manifest_supported": True,
        "immutable_baseline_supported": True,
        "explicit_candidate_registry_required": True,
        "primary_reference_deduplication": "sha256",
        "campaign_outcome_index_supported": True,
        "normal_campaign_terminals": [
            "production_delivery",
            "usable_review_terminal",
        ],
        "local_activation_scope": "local_desktop_in_session",
        "structured_local_readiness_supported": True,
        "human_activation_acceptance_required": True,
        "profile_activation_writer_exposed": False,
        "campaign_creation_supported_by_this_service": False,
        "legacy_auto_migration": False,
    }
