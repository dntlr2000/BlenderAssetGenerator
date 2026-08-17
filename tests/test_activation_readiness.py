"""Focused service tests for additive disabled-experimental activation readiness."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from codex_blender_modeler.autonomy_v2.profiles import autonomy_v2_profile_status
from codex_blender_modeler.blender_artifacts import (
    deterministic_json_bytes,
    sha256_file,
    stable_json_digest,
)
from codex_blender_modeler.production import (
    ActivationArtifact,
    ActivationAssetCandidateIndex,
    ActivationAssetCandidateRegistry,
    ActivationAssetEligibilityReport,
    ActivationAssetEvidence,
    ActivationBaseline,
    ActivationBlenderEvidence,
    ActivationCandidateRegistryEntry,
    ActivationCommandReceipt,
    ActivationEvidenceCheck,
    ActivationEvidenceClassification,
    ActivationReadinessReport,
    ActivationSourceManifest,
    ActivationValidationError,
    HumanActivationAcceptance,
    SourceCheckpointRequired,
    activation_contract_capability,
    activation_service,
    build_activation_asset_candidate_index,
    create_activation_baseline,
    create_activation_readiness_report,
    evaluate_activation_asset_eligibility,
    load_activation_source_manifest,
    validate_human_activation_acceptance,
    write_activation_candidate_registry,
)
from codex_blender_modeler.production.activation_models import (
    ActivationSourceExclusion,
    ActivationSourceFile,
)

NOW = datetime(2026, 8, 17, 9, 30, tzinfo=UTC)


def _finalize_contract(
    model: type[BaseModel],
    payload: dict[str, Any],
    *,
    prefix: str,
    id_field: str,
    digest_field: str,
) -> BaseModel:
    """Populate deterministic identity fields exactly as the host service does."""

    provisional = model.model_construct(
        **payload,
        **{id_field: "pending-activation-identity", digest_field: "0" * 64},
    )
    digest = stable_json_digest(
        provisional.model_dump(mode="json", exclude={id_field, digest_field})
    )
    return model.model_validate(
        {
            **payload,
            id_field: f"{prefix}-{digest[:24]}",
            digest_field: digest,
        }
    )


def _write_bytes(root: Path, relative_path: str, content: bytes) -> Path:
    """Write one synthetic repository-contained evidence file for an isolated test."""

    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _artifact(
    root: Path,
    relative_path: str,
    *,
    artifact_id: str,
    kind: str,
) -> ActivationArtifact:
    """Bind one existing synthetic file to exact activation artifact metadata."""

    path = root / relative_path
    return ActivationArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=relative_path,
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
    )


def _write_model(
    root: Path,
    relative_path: str,
    model: BaseModel,
    *,
    artifact_id: str,
    kind: str,
) -> ActivationArtifact:
    """Write deterministic model bytes and return their exact synthetic artifact."""

    _write_bytes(
        root,
        relative_path,
        deterministic_json_bytes(model.model_dump(mode="json")),
    )
    return _artifact(
        root,
        relative_path,
        artifact_id=artifact_id,
        kind=kind,
    )


def _baseline_fixture(
    tmp_path: Path,
) -> tuple[
    Path,
    ActivationSourceManifest,
    ActivationArtifact,
    ActivationBaseline,
    ActivationArtifact,
]:
    """Create one internally consistent synthetic source manifest and baseline."""

    root = tmp_path / "repository"
    root.mkdir(parents=True)
    executable = _write_bytes(root, "tools/blender.exe", b"blender-5.0.1-fixture")
    _write_bytes(root, "reports/blender-version.txt", b"Blender 5.0.1\n")
    version_receipt = _artifact(
        root,
        "reports/blender-version.txt",
        artifact_id="blender-version-receipt",
        kind="blender_version_receipt",
    )
    blender = ActivationBlenderEvidence(
        executable_path=str(executable.resolve()),
        executable_sha256=sha256_file(executable),
        version="5.0.1",
        version_command=[str(executable.resolve()), "--version"],
        version_output_sha256=sha256_file(root / "reports/blender-version.txt"),
        version_receipt=version_receipt,
    )
    dependency = ActivationCommandReceipt(
        receipt_id="dependency-resolution",
        command_id="uv_sync_frozen_dev_vision",
        command=["uv", "sync", "--frozen", "--extra", "dev", "--extra", "vision"],
        status="passed",
        exit_code=0,
        output_sha256="1" * 64,
        recorded_at=NOW,
    )
    records = sorted(
        [
            ActivationSourceFile(
                path="schemas/activation.schema.json",
                role="schema",
                sha256="2" * 64,
                byte_size=2,
            ),
            ActivationSourceFile(
                path="src/controller.py",
                role="controller_promotion",
                sha256="3" * 64,
                byte_size=3,
            ),
            ActivationSourceFile(
                path="src/profiles.py",
                role="profile_registry",
                sha256="4" * 64,
                byte_size=4,
            ),
            ActivationSourceFile(
                path="uv.lock",
                role="dependency_lock",
                sha256="5" * 64,
                byte_size=5,
            ),
        ],
        key=lambda item: item.path,
    )
    by_path = {item.path: item for item in records}
    source_payload: dict[str, Any] = {
        "project_version": "0.9.0",
        "canonical_scenespec_version": "0.2.0",
        "git_commit_sha": "a" * 40,
        "git_tree_sha": "b" * 40,
        "working_tree_clean": True,
        "staged_tree_clean": True,
        "untracked_source_files": [],
        "source_files": records,
        "schema_files": [by_path["schemas/activation.schema.json"]],
        "controller_promotion_files": [by_path["src/controller.py"]],
        "profile_registry": by_path["src/profiles.py"],
        "uv_lock": by_path["uv.lock"],
        "python_version": "3.14.6",
        "uv_version": "0.8.17",
        "dependency_resolution_evidence": dependency,
        "blender": blender,
        "excluded_classes": [
            ActivationSourceExclusion(
                path_prefix="test_runs/",
                reason_code="test_copy",
                reason="Synthetic and copied repositories are not source evidence.",
            )
        ],
        "generator_version": "0.1.0",
        "generated_at": NOW,
    }
    source = _finalize_contract(
        ActivationSourceManifest,
        source_payload,
        prefix="activation-source",
        id_field="manifest_id",
        digest_field="manifest_sha256",
    )
    assert isinstance(source, ActivationSourceManifest)
    source_artifact = _write_model(
        root,
        "reports/activation/source.json",
        source,
        artifact_id=source.manifest_id,
        kind="activation_source_manifest",
    )
    validation = ActivationCommandReceipt(
        receipt_id="pytest-validation",
        command_id="pytest_full",
        command=["uv", "run", "pytest"],
        status="passed",
        exit_code=0,
        output_sha256="6" * 64,
        recorded_at=NOW,
    )
    baseline_payload: dict[str, Any] = {
        "source_manifest": source_artifact,
        "source_manifest_id": source.manifest_id,
        "source_manifest_sha256": source.manifest_sha256,
        "git_commit_sha": source.git_commit_sha,
        "git_tree_sha": source.git_tree_sha,
        "schema_manifest_sha256": "7" * 64,
        "controller_promotion_manifest_sha256": "8" * 64,
        "profile_registry_sha256": source.profile_registry.sha256,
        "uv_lock_sha256": source.uv_lock.sha256,
        "python_version": source.python_version,
        "uv_version": source.uv_version,
        "blender": blender,
        "validation_receipts": [validation],
        "profile_id": "autonomous_static_prop_v2",
        "profile_version": "0.2.0",
        "profile_status": "disabled_experimental",
        "campaign_created": False,
        "production_activation_performed": False,
        "human_activation_accepted": False,
        "created_at": NOW,
    }
    baseline = _finalize_contract(
        ActivationBaseline,
        baseline_payload,
        prefix="activation-baseline",
        id_field="baseline_id",
        digest_field="baseline_sha256",
    )
    assert isinstance(baseline, ActivationBaseline)
    baseline_artifact = _write_model(
        root,
        "reports/activation/baseline.json",
        baseline,
        artifact_id=baseline.baseline_id,
        kind="activation_baseline",
    )
    return root, source, source_artifact, baseline, baseline_artifact


def _classification(kind: str) -> ActivationEvidenceClassification:
    """Create a coherent authoritative or explicitly non-production classification."""

    if kind == "authoritative_job":
        return ActivationEvidenceClassification(
            kind=kind,
            authoritative=True,
            copied_workspace=False,
            test_only=False,
            activation_asset=True,
            production_evidence=True,
        )
    return ActivationEvidenceClassification(
        kind=kind,
        authoritative=False,
        copied_workspace=kind in {"copied_workspace", "local_clone"},
        test_only=True,
        activation_asset=False,
        production_evidence=False,
    )


def _candidate_evidence(
    root: Path,
    baseline: ActivationBaseline,
    baseline_artifact: ActivationArtifact,
    *,
    candidate_id: str,
    reference_bytes: bytes,
    classification_kind: str = "authoritative_job",
    terminal_state: str = "completed",
    canonical_disposition: str = "canonical",
    missing_decision: bool = False,
    empty_dependencies: bool = False,
) -> ActivationAssetEvidence:
    """Create one complete or deliberately incomplete explicit candidate evidence set."""

    evidence_root = (
        f"workspaces/{candidate_id}"
        if classification_kind == "authoritative_job"
        else f"test_runs/{candidate_id}"
        if classification_kind == "test_run"
        else f"copies/{classification_kind}/{candidate_id}"
    )
    _write_bytes(root, f"{evidence_root}/input/reference.png", reference_bytes)
    _write_bytes(root, f"{evidence_root}/candidate.json", b'{"candidate":true}\n')
    _write_bytes(root, f"{evidence_root}/final.blend", b"final-blend")
    primary = _artifact(
        root,
        f"{evidence_root}/input/reference.png",
        artifact_id=f"reference-{candidate_id}",
        kind="primary_reference",
    )
    candidate = _artifact(
        root,
        f"{evidence_root}/candidate.json",
        artifact_id=f"candidate-{candidate_id}",
        kind="candidate_artifact",
    )
    final = _artifact(
        root,
        f"{evidence_root}/final.blend",
        artifact_id=f"final-{candidate_id}",
        kind="final_artifact",
    )
    checks: list[ActivationEvidenceCheck] = []
    required = sorted(activation_service._REQUIRED_ELIGIBILITY_CHECKS)
    for check_id in required:
        artifacts: list[ActivationArtifact]
        if check_id == "policy_decision_chain":
            _write_bytes(root, f"{evidence_root}/{check_id}-auth.json", b"{}\n")
            policy = _artifact(
                root,
                f"{evidence_root}/{check_id}-auth.json",
                artifact_id=f"policy-{candidate_id}",
                kind="policy_authorization",
            )
            artifacts = [policy]
            if not missing_decision:
                _write_bytes(
                    root,
                    f"{evidence_root}/{check_id}-decision.json",
                    b"{}\n",
                )
                artifacts.append(
                    _artifact(
                        root,
                        f"{evidence_root}/{check_id}-decision.json",
                        artifact_id=f"decision-{candidate_id}",
                        kind="policy_decision_receipt",
                    )
                )
        elif check_id == "dependency_closure":
            if empty_dependencies:
                artifacts = []
            else:
                _write_bytes(root, f"{evidence_root}/{check_id}.json", b"{}\n")
                artifacts = [
                    _artifact(
                        root,
                        f"{evidence_root}/{check_id}.json",
                        artifact_id=f"dependency-{candidate_id}",
                        kind="eligibility_dependency",
                    )
                ]
        elif check_id == "artifact_binding":
            artifacts = [candidate, final]
        elif check_id == "source_baseline_binding":
            artifacts = [baseline_artifact]
        else:
            _write_bytes(root, f"{evidence_root}/{check_id}.json", b"{}\n")
            artifacts = [
                _artifact(
                    root,
                    f"{evidence_root}/{check_id}.json",
                    artifact_id=f"{check_id}-{candidate_id}",
                    kind=check_id,
                )
            ]
        checks.append(
            ActivationEvidenceCheck(
                check_id=check_id,
                status="passed",
                validator=f"fixture.{check_id}",
                artifacts=artifacts,
                detail=f"Synthetic exact evidence for {check_id}.",
            )
        )
    return ActivationAssetEvidence(
        candidate_id=candidate_id,
        job_id=f"job-{candidate_id}",
        workflow_id=f"workflow-{candidate_id}",
        session_id=f"session-{candidate_id}",
        attempt_id=f"attempt-{candidate_id}",
        revision_id=f"revision-{candidate_id}",
        evidence_root=evidence_root,
        classification=_classification(classification_kind),
        primary_reference=primary,
        candidate_artifact=candidate,
        final_artifact=final,
        source_activation_baseline=baseline_artifact,
        source_activation_baseline_id=baseline.baseline_id,
        source_activation_baseline_sha256=baseline.baseline_sha256,
        terminal_state=terminal_state,
        canonical_disposition=canonical_disposition,
        superseded_by_candidate_id=(
            f"replacement-{candidate_id}"
            if canonical_disposition == "superseded"
            else None
        ),
        checks=checks,
    )


def _eligibility(
    root: Path,
    baseline: ActivationBaseline,
    baseline_artifact: ActivationArtifact,
    *,
    candidate_id: str,
    reference_bytes: bytes,
    **changes: Any,
) -> tuple[ActivationAssetEligibilityReport, ActivationArtifact]:
    """Evaluate and persist one synthetic candidate through the real eligibility service."""

    evidence = _candidate_evidence(
        root,
        baseline,
        baseline_artifact,
        candidate_id=candidate_id,
        reference_bytes=reference_bytes,
        **changes,
    )
    return evaluate_activation_asset_eligibility(
        root,
        evidence=evidence,
        expected_baseline_artifact=baseline_artifact,
        output_path=(
            root
            / f"reports/activation_readiness/eligibility/{candidate_id}.json"
        ),
        generated_at=NOW,
    )


def _index(
    root: Path,
    baseline_artifact: ActivationArtifact,
    reports: list[tuple[ActivationAssetEligibilityReport, ActivationArtifact]],
) -> ActivationAssetCandidateIndex:
    """Write one explicit registry and build its real candidate index."""

    index, _artifact = _index_with_artifact(root, baseline_artifact, reports)
    return index


def _index_with_artifact(
    root: Path,
    baseline_artifact: ActivationArtifact,
    reports: list[tuple[ActivationAssetEligibilityReport, ActivationArtifact]],
) -> tuple[ActivationAssetCandidateIndex, ActivationArtifact]:
    """Write one explicit registry and return both the index and immutable artifact."""

    entries = [
        ActivationCandidateRegistryEntry(
            candidate_id=report.evidence.candidate_id,
            eligibility_report=artifact,
        )
        for report, artifact in sorted(
            reports,
            key=lambda item: item[0].evidence.candidate_id,
        )
    ]
    _registry, registry_artifact = write_activation_candidate_registry(
        root,
        entries=entries,
        output_path=root / "reports/activation_readiness/registry.json",
        generated_at=NOW,
    )
    index, _artifact_record = build_activation_asset_candidate_index(
        root,
        registry_artifact=registry_artifact,
        expected_baseline_artifact=baseline_artifact,
        output_path=root / "reports/activation_readiness/index.json",
        generated_at=NOW,
    )
    return index, _artifact_record


def test_policy_decision_and_dependency_are_real_eligibility_requirements(
    tmp_path: Path,
) -> None:
    """Reject missing decisions and zero dependencies through the eligibility service."""

    root, _source, _source_artifact, baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    missing, _artifact_record = _eligibility(
        root,
        baseline,
        baseline_artifact,
        candidate_id="missing-decision",
        reference_bytes=b"reference-a",
        missing_decision=True,
    )
    empty, _artifact_record = _eligibility(
        root,
        baseline,
        baseline_artifact,
        candidate_id="empty-dependency",
        reference_bytes=b"reference-b",
        empty_dependencies=True,
    )
    assert missing.eligible is False
    assert "missing_policy_decision_receipt" in {
        item.code for item in missing.exclusion_reasons
    }
    assert empty.eligible is False
    assert "empty_eligibility_dependency" in {
        item.code for item in empty.exclusion_reasons
    }


@pytest.mark.parametrize(
    "classification_kind",
    [
        "test_run",
        "copied_workspace",
        "local_clone",
        "shadow_job",
        "preflight_copy",
        "staging_copy",
        "recovery_copy",
        "audit_directory",
        "report_only_fixture",
        "review_bundle",
    ],
)
def test_candidate_index_excludes_every_nonproduction_copy_class(
    tmp_path: Path,
    classification_kind: str,
) -> None:
    """Call the real indexer and prove copied/test/staging roots count zero units."""

    root, _source, _source_artifact, baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    report = _eligibility(
        root,
        baseline,
        baseline_artifact,
        candidate_id=f"excluded-{classification_kind}",
        reference_bytes=b"same-reference",
        classification_kind=classification_kind,
    )
    index = _index(root, baseline_artifact, [report])
    assert index.counted_asset_units == 0
    assert index.distinct_asset_count == 0
    assert index.records[0].counted is False
    assert classification_kind in {
        item.code for item in index.records[0].exclusion_reasons
    }


def test_primary_reference_revisions_deduplicate_to_one_canonical_unit(
    tmp_path: Path,
) -> None:
    """Count one canonical revision and exclude its exact-hash superseded sibling."""

    root, _source, _source_artifact, baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    current = _eligibility(
        root,
        baseline,
        baseline_artifact,
        candidate_id="beam-current",
        reference_bytes=b"same-primary-reference",
    )
    superseded = _eligibility(
        root,
        baseline,
        baseline_artifact,
        candidate_id="beam-old",
        reference_bytes=b"same-primary-reference",
        canonical_disposition="superseded",
    )
    index = _index(root, baseline_artifact, [current, superseded])
    assert index.counted_asset_units == 1
    assert index.deduplication_groups[0].duplicate_count == 1
    assert (
        index.deduplication_groups[0].eligible_canonical_representative
        == "beam-current"
    )


def test_ambiguous_duplicate_terminal_successes_exclude_the_whole_group(
    tmp_path: Path,
) -> None:
    """Fail closed when two canonical terminal successes share one reference hash."""

    root, _source, _source_artifact, baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    reports = [
        _eligibility(
            root,
            baseline,
            baseline_artifact,
            candidate_id=candidate_id,
            reference_bytes=b"ambiguous-primary-reference",
        )
        for candidate_id in ("ambiguous-a", "ambiguous-b")
    ]
    index = _index(root, baseline_artifact, reports)
    assert index.counted_asset_units == 0
    assert index.deduplication_groups[0].status == "ambiguous"
    assert all(
        "ambiguous_duplicate_group"
        in {item.code for item in record.exclusion_reasons}
        for record in index.records
    )


def test_distinct_reference_hashes_count_as_distinct_assets(tmp_path: Path) -> None:
    """Count only two separately eligible primary-reference content hashes."""

    root, _source, _source_artifact, baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    reports = [
        _eligibility(
            root,
            baseline,
            baseline_artifact,
            candidate_id="distinct-a",
            reference_bytes=b"reference-a",
        ),
        _eligibility(
            root,
            baseline,
            baseline_artifact,
            candidate_id="distinct-b",
            reference_bytes=b"reference-b",
        ),
    ]
    index = _index(root, baseline_artifact, reports)
    assert index.distinct_asset_count == 2
    assert index.counted_asset_units == 2


@pytest.mark.parametrize("terminal_state", ["failed", "blocked", "cancelled", "nonterminal"])
def test_noncompleted_attempts_are_never_counted(
    tmp_path: Path,
    terminal_state: str,
) -> None:
    """Exclude every failed, blocked, cancelled, or nonterminal attempt."""

    root, _source, _source_artifact, baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    report = _eligibility(
        root,
        baseline,
        baseline_artifact,
        candidate_id=f"terminal-{terminal_state}",
        reference_bytes=terminal_state.encode("utf-8"),
        terminal_state=terminal_state,
    )
    index = _index(root, baseline_artifact, [report])
    assert index.counted_asset_units == 0
    assert f"terminal_{terminal_state}" in {
        item.code for item in index.records[0].exclusion_reasons
    }


def test_tampered_candidate_and_baseline_mismatch_fail_closed(tmp_path: Path) -> None:
    """Reject mutated candidate bytes and a source-baseline identity mismatch."""

    root, _source, _source_artifact, baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    evidence = _candidate_evidence(
        root,
        baseline,
        baseline_artifact,
        candidate_id="tampered-candidate",
        reference_bytes=b"reference",
    )
    (root / evidence.candidate_artifact.path).write_bytes(b"tampered")
    evidence = evidence.model_copy(
        update={"source_activation_baseline_sha256": "f" * 64}
    )
    report, _artifact_record = evaluate_activation_asset_eligibility(
        root,
        evidence=evidence,
        expected_baseline_artifact=baseline_artifact,
        output_path=(
            root / "reports/activation_readiness/eligibility/tampered.json"
        ),
        generated_at=NOW,
    )
    codes = {item.code for item in report.exclusion_reasons}
    assert "stale_tampered_missing_or_unknown_evidence" in codes
    assert "source_baseline_mismatch" in codes


def test_index_rehashes_evidence_after_eligibility_publication(tmp_path: Path) -> None:
    """Exclude evidence that becomes stale between eligibility and index construction."""

    root, _source, _source_artifact, baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    report = _eligibility(
        root,
        baseline,
        baseline_artifact,
        candidate_id="post-eligibility-tamper",
        reference_bytes=b"reference",
    )
    final_path = root / report[0].evidence.final_artifact.path
    final_path.write_bytes(b"tampered-after-eligibility")
    index = _index(root, baseline_artifact, [report])
    assert index.counted_asset_units == 0
    assert "stale_tampered_missing_or_unknown_evidence" in {
        item.code for item in index.records[0].exclusion_reasons
    }


def test_candidate_and_final_artifacts_require_exact_binding(tmp_path: Path) -> None:
    """Reject a passed binding check that names a different candidate or final artifact."""

    root, _source, _source_artifact, baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    evidence = _candidate_evidence(
        root,
        baseline,
        baseline_artifact,
        candidate_id="artifact-unbound",
        reference_bytes=b"reference",
    )
    checks = [
        check.model_copy(update={"artifacts": [evidence.primary_reference]})
        if check.check_id == "artifact_binding"
        else check
        for check in evidence.checks
    ]
    report, _artifact_record = evaluate_activation_asset_eligibility(
        root,
        evidence=evidence.model_copy(update={"checks": checks}),
        expected_baseline_artifact=baseline_artifact,
        output_path=(
            root
            / "reports/activation_readiness/eligibility/artifact-unbound.json"
        ),
        generated_at=NOW,
    )
    assert report.eligible is False
    assert "candidate_or_final_artifact_unbound" in {
        item.code for item in report.exclusion_reasons
    }


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".aq_activation_chain_audit_20260817/manifest.json", True),
        (".pytest_cache/v/cache/nodeids", True),
        ("test_runs/copy/source.py", True),
        ("TEST_RUNS/copy/source.py", True),
        (".codex_test/gate/output.json", True),
        ("output/previews/render.png", True),
        ("copied_repositories/main/src.py", True),
        ("unknown_generated/source.py", False),
    ],
)
def test_source_checkpoint_runtime_classification_preserves_leading_dots(
    path: str,
    expected: bool,
) -> None:
    """Exclude only named runtime classes while retaining dotted path identities."""

    assert activation_service._is_explicit_runtime_path(path) is expected


def test_source_manifest_internal_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    """Reject a rehashed file whose embedded source-manifest identity is stale."""

    root, source, _source_artifact, _baseline, _baseline_artifact = _baseline_fixture(
        tmp_path
    )
    payload = source.model_dump(mode="json")
    payload["python_version"] = "3.99-tampered"
    path = _write_bytes(
        root,
        "reports/activation/tampered-source.json",
        deterministic_json_bytes(payload),
    )
    artifact = ActivationArtifact(
        artifact_id=source.manifest_id,
        kind="activation_source_manifest",
        path=path.relative_to(root).as_posix(),
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
    )
    with pytest.raises(ValueError, match="canonical contract payload"):
        load_activation_source_manifest(root, artifact)


def test_dirty_source_checkpoint_rejects_baseline_before_artifact_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject baseline publication immediately when tracked source is dirty."""

    root = tmp_path / "repository"
    root.mkdir()
    monkeypatch.setattr(
        activation_service,
        "inspect_activation_source_checkpoint",
        lambda _root: {
            "working_tree_clean": False,
            "staged_tree_clean": True,
            "untracked_source_files": [],
        },
    )
    missing = ActivationArtifact(
        artifact_id="missing-source",
        kind="activation_source_manifest",
        path="reports/missing.json",
        sha256="0" * 64,
        byte_size=1,
    )
    with pytest.raises(SourceCheckpointRequired, match="clean committed"):
        create_activation_baseline(
            root,
            source_manifest_artifact=missing,
            validation_receipts=[],
        )


def test_activation_contract_writer_rejects_workspace_input_output(
    tmp_path: Path,
) -> None:
    """Prevent every readiness writer from targeting immutable workspace input."""

    root, _source, _source_artifact, baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    evidence = _candidate_evidence(
        root,
        baseline,
        baseline_artifact,
        candidate_id="forbidden-input-write",
        reference_bytes=b"reference",
    )
    forbidden = root / "workspaces/forbidden-input-write/input/readiness.json"
    with pytest.raises(ActivationValidationError, match="reports/activation_readiness"):
        evaluate_activation_asset_eligibility(
            root,
            evidence=evidence,
            expected_baseline_artifact=baseline_artifact,
            output_path=forbidden,
            generated_at=NOW,
        )
    assert forbidden.exists() is False


def test_human_acceptance_is_required_without_exposing_an_activation_writer(
    tmp_path: Path,
) -> None:
    """Refuse profile activation authority when exact human acceptance is absent."""

    root, _source, _source_artifact, _baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    placeholder = ActivationArtifact(
        artifact_id="missing-index",
        kind="activation_asset_candidate_index",
        path="reports/missing-index.json",
        sha256="0" * 64,
        byte_size=1,
    )
    with pytest.raises(PermissionError, match="HumanActivationAcceptance"):
        validate_human_activation_acceptance(
            root,
            baseline_artifact=baseline_artifact,
            candidate_index_artifact=placeholder,
            acceptance_artifact=None,
        )
    capability = activation_contract_capability()
    assert capability["profile_activation_writer_exposed"] is False
    assert capability["campaign_creation_supported_by_this_service"] is False
    profile = autonomy_v2_profile_status()
    assert profile["status"] == "disabled_experimental"
    assert profile["verified_active"] is False


def test_readiness_without_a_checkpoint_reports_source_checkpoint_required(
    tmp_path: Path,
) -> None:
    """Produce the expected non-activating blocked result while source is uncommitted."""

    root = tmp_path / "repository"
    root.mkdir()
    report, artifact = create_activation_readiness_report(
        root,
        source_manifest_artifact=None,
        baseline_artifact=None,
        output_path=None,
        generated_at=NOW,
    )
    assert artifact is None
    assert report.status == "source_checkpoint_required"
    assert report.profile_status == "disabled_experimental"
    assert report.campaign_created is False
    assert report.production_activation_performed is False
    assert report.human_activation_accepted is False


def test_readiness_fails_closed_if_the_live_profile_is_not_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse a readiness claim if the live AQ v2 registry is already active."""

    import codex_blender_modeler.autonomy_v2.profiles as profiles

    def active_profile() -> dict[str, object]:
        """Return one forbidden active projection for the readiness boundary."""

        return {"status": "verified_active", "verified_active": True}

    monkeypatch.setattr(profiles, "autonomy_v2_profile_status", active_profile)
    root = tmp_path / "repository"
    root.mkdir()
    report, artifact = create_activation_readiness_report(
        root,
        source_manifest_artifact=None,
        baseline_artifact=None,
        output_path=None,
        generated_at=NOW,
    )
    assert artifact is None
    assert report.status == "validation_blocked"
    assert report.blockers == ["AQ v2 profile is not disabled_experimental"]


SCHEMA_MODELS = {
    "activation_source_manifest.schema.json": ActivationSourceManifest,
    "activation_baseline.schema.json": ActivationBaseline,
    "activation_readiness_report.schema.json": ActivationReadinessReport,
    "activation_asset_evidence.schema.json": ActivationAssetEvidence,
    "activation_asset_eligibility_report.schema.json": ActivationAssetEligibilityReport,
    "activation_asset_candidate_registry.schema.json": ActivationAssetCandidateRegistry,
    "activation_asset_candidate_index.schema.json": ActivationAssetCandidateIndex,
    "human_activation_acceptance.schema.json": HumanActivationAcceptance,
}


@pytest.mark.parametrize(("filename", "model"), sorted(SCHEMA_MODELS.items()))
def test_activation_schema_matches_strict_model(filename: str, model: type[BaseModel]) -> None:
    """Keep every checked-in activation schema byte-equivalent to its strict model."""

    checked_in = json.loads((Path("schemas") / filename).read_text(encoding="utf-8"))
    assert checked_in == model.model_json_schema()


def test_human_acceptance_contract_has_finite_single_use_semantics() -> None:
    """Reject non-expiring acceptance while keeping policy authority explicitly false."""

    artifact = ActivationArtifact(
        artifact_id="fixture-artifact",
        kind="activation_baseline",
        path="reports/fixture.json",
        sha256="0" * 64,
        byte_size=1,
    )
    payload: dict[str, Any] = {
        "activation_baseline": artifact,
        "activation_baseline_id": "baseline-fixture",
        "activation_baseline_sha256": "1" * 64,
        "candidate_index": artifact.model_copy(
            update={"artifact_id": "index-fixture", "kind": "activation_asset_candidate_index"}
        ),
        "candidate_index_id": "index-fixture",
        "candidate_index_sha256": "2" * 64,
        "distinct_primary_reference_sha256s": ["3" * 64],
        "profile_id": "autonomous_static_prop_v2",
        "profile_version": "0.2.0",
        "requested_operation": "activate_profile",
        "reviewer_identity": "fixture-reviewer",
        "created_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "single_use": True,
        "is_policy_authorization": False,
        "is_user_approval": True,
    }
    acceptance = _finalize_contract(
        HumanActivationAcceptance,
        payload,
        prefix="human-activation",
        id_field="acceptance_id",
        digest_field="acceptance_sha256",
    )
    assert isinstance(acceptance, HumanActivationAcceptance)
    assert acceptance.single_use is True
    assert acceptance.is_policy_authorization is False
    invalid = acceptance.model_dump(mode="json")
    invalid["expires_at"] = invalid["created_at"]
    with pytest.raises(ValueError, match="expire after creation"):
        HumanActivationAcceptance.model_validate(invalid)


def test_human_acceptance_revalidates_exact_five_asset_set_and_prior_consumption(
    tmp_path: Path,
) -> None:
    """Accept one exact five-asset fixture and reject it after a consumption marker exists."""

    root, _source, _source_artifact, baseline, baseline_artifact = _baseline_fixture(
        tmp_path
    )
    reports = [
        _eligibility(
            root,
            baseline,
            baseline_artifact,
            candidate_id=f"accepted-{index}",
            reference_bytes=f"reference-{index}".encode(),
        )
        for index in range(5)
    ]
    index, index_artifact = _index_with_artifact(root, baseline_artifact, reports)
    accepted_hashes = sorted(
        group.primary_reference_sha256
        for group in index.deduplication_groups
        if group.counted_asset_units == 1
    )
    payload: dict[str, Any] = {
        "activation_baseline": baseline_artifact,
        "activation_baseline_id": baseline.baseline_id,
        "activation_baseline_sha256": baseline.baseline_sha256,
        "candidate_index": index_artifact,
        "candidate_index_id": index.index_id,
        "candidate_index_sha256": index.index_sha256,
        "distinct_primary_reference_sha256s": accepted_hashes,
        "profile_id": "autonomous_static_prop_v2",
        "profile_version": "0.2.0",
        "requested_operation": "activate_profile",
        "reviewer_identity": "fixture-reviewer",
        "created_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "single_use": True,
        "is_policy_authorization": False,
        "is_user_approval": True,
    }
    acceptance = _finalize_contract(
        HumanActivationAcceptance,
        payload,
        prefix="human-activation",
        id_field="acceptance_id",
        digest_field="acceptance_sha256",
    )
    assert isinstance(acceptance, HumanActivationAcceptance)
    acceptance_artifact = _write_model(
        root,
        "reports/activation/human-acceptance.json",
        acceptance,
        artifact_id=acceptance.acceptance_id,
        kind="human_activation_acceptance",
    )
    validated = validate_human_activation_acceptance(
        root,
        baseline_artifact=baseline_artifact,
        candidate_index_artifact=index_artifact,
        acceptance_artifact=acceptance_artifact,
        observed_at=NOW + timedelta(minutes=1),
    )
    assert validated.acceptance_id == acceptance.acceptance_id
    _write_bytes(
        root,
        (
            "reports/activation_readiness/acceptance_consumptions/"
            f"{acceptance.acceptance_id}.json"
        ),
        b'{"consumed":true}\n',
    )
    with pytest.raises(PermissionError, match="already consumed"):
        validate_human_activation_acceptance(
            root,
            baseline_artifact=baseline_artifact,
            candidate_index_artifact=index_artifact,
            acceptance_artifact=acceptance_artifact,
            observed_at=NOW + timedelta(minutes=2),
        )
