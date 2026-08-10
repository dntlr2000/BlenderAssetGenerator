"""Focused fail-closed tests for Autonomous Quality terminal evidence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.autonomy.authorization import artifact_for
from codex_blender_modeler.autonomy.models import (
    AutonomyArtifact,
    AutonomyState,
    BudgetUsage,
)
from codex_blender_modeler.autonomy.reporting import build_review_bundle
from codex_blender_modeler.autonomy.service import (
    _terminal_contract,
    _verify_destination_handoff_terminal,
    _verify_terminal_evidence,
)
from codex_blender_modeler.blender_artifacts import (
    sha256_file,
    stable_json_digest,
    write_json_atomic,
)
from codex_blender_modeler.integrated_quality import write_integrated_quality_evidence
from codex_blender_modeler.integrated_quality.models import (
    AxisThreshold,
    EvidenceAvailability,
    IntegratedQualityReport,
    ProducerIdentity,
    QualityArtifact,
    QualityAxisResult,
    QualityGateProfile,
    QualityProvenance,
    quality_artifact_input_sha256,
)
from codex_blender_modeler.optimization.models import (
    Bounds3D,
    HashedArtifact,
    SourceProvenance,
)
from codex_blender_modeler.packaging.models import (
    BoundsComparison,
    ExportPackageManifest,
    PackageFile,
    RoundTripValidation,
)

_NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
_JOB_ID = "aq_terminal_prop"
_WORKFLOW_ID = "wf-aq-terminal"
_DISPATCH_ID = "dispatch-aq-terminal"
_SESSION_ID = "session-aq-terminal"


def test_destination_handoff_terminal_requires_recursive_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bind a terminal handoff to the read-only recursive envelope validator."""

    from codex_blender_modeler.autonomy import service as autonomy_service

    root = tmp_path / _JOB_ID
    root.mkdir()
    _session_root, state = _terminal_state(root, reason="quality_target_reached")
    manifest_path = _write(
        root
        / "exports"
        / "destination_handoffs"
        / "portable_gltf"
        / "package-1"
        / "handoff-1"
        / "codex_handoff"
        / "handoff_manifest.json",
        b"{}\n",
    )
    artifact = artifact_for(root, manifest_path)
    monkeypatch.setattr(
        autonomy_service.DestinationHandoffManifest,
        "model_validate_json",
        lambda _payload: SimpleNamespace(
            job_id=_JOB_ID,
            profile_id="portable_gltf",
            package_id="package-1",
            handoff_id="handoff-1",
        ),
    )
    calls: list[tuple[str, str, str, str]] = []

    def validate(job_id: str, *, profile_id: str, package_id: str, handoff_id: str):
        """Return one exact recursive validation fixture and capture its identity."""

        calls.append((job_id, profile_id, package_id, handoff_id))
        return SimpleNamespace(
            ok=True,
            status="passed",
            handoff_manifest_sha256=artifact.sha256,
        )

    monkeypatch.setattr(autonomy_service, "validate_destination_handoff", validate)
    _verify_destination_handoff_terminal(root, state, artifact)
    assert calls == [(_JOB_ID, "portable_gltf", "package-1", "handoff-1")]


def _write(path: Path, content: bytes) -> Path:
    """Write one deterministic binary fixture below the isolated job root."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _hashed(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
) -> HashedArtifact:
    """Create one V0.7 hash receipt for an existing contained fixture file."""

    return HashedArtifact(
        id=artifact_id,
        kind=kind,
        path=path.resolve().relative_to(root.resolve()).as_posix(),
        sha256=sha256_file(path),
    )


def _terminal_state(root: Path, *, reason: str) -> tuple[Path, AutonomyState]:
    """Publish one exact completed terminal state for verifier-focused tests."""

    support = artifact_for(root, _write(root / "fixture" / "support.json", b"{}\n"))
    state = AutonomyState(
        contract_id="state-aq-terminal",
        job_id=_JOB_ID,
        workflow_id=_WORKFLOW_ID,
        dispatch_id=_DISPATCH_ID,
        input_sha256=support.sha256,
        source_fingerprint=support.sha256,
        producer="aq.terminal.tests",
        producer_version="0.1.0",
        provenance=[support],
        created_at=_NOW,
        session_id=_SESSION_ID,
        root_authorization=support,
        profile=support,
        budget=support,
        status="completed",
        phase="terminal",
        next_action="none",
        action_sequence=1,
        budget_usage=BudgetUsage(),
        terminal_reason=reason,
        observed_at=_NOW,
    )
    session_root = root / "production" / "autonomy" / _SESSION_ID
    state_path = session_root / "transitions" / "0001" / "state.json"
    write_json_atomic(state_path, state.model_dump(mode="json"))
    return session_root, state


def _quality_evidence(
    root: Path,
    session_root: Path,
    *,
    accepted: bool,
) -> tuple[IntegratedQualityReport, AutonomyArtifact, Path]:
    """Create exact IQ JSON, sidecar, PDF, profile, and source evidence."""

    producer = ProducerIdentity(name="aq-terminal-tests", version="0.1.0")
    source_path = _write(root / "qa" / "terminal_source.json", b'{"exact":true}\n')
    source_artifact = QualityArtifact(
        artifact_id="terminal-quality-source",
        kind="test-fixture",
        relative_path=source_path.relative_to(root).as_posix(),
        sha256=sha256_file(source_path),
        producer=producer,
        produced_at=_NOW,
    )
    source_fingerprint = hashlib.sha256(b"terminal-quality-source").hexdigest()
    profile = QualityGateProfile(
        schema_version="0.1.0",
        profile_id="aq-terminal-quality-profile",
        job_id=_JOB_ID,
        workflow_id=_WORKFLOW_ID,
        dispatch_id=_DISPATCH_ID,
        input_sha256=quality_artifact_input_sha256([]),
        source_fingerprint=source_fingerprint,
        producer=producer,
        provenance=[],
        created_at=_NOW,
        axis_thresholds=[
            AxisThreshold(
                axis="reference_alignment",
                pass_score=0.8,
                warning_score=0.6,
            )
        ],
    )
    profile_path = session_root / "quality_gate_profile.final.json"
    write_json_atomic(profile_path, profile.model_dump(mode="json"))
    availability = EvidenceAvailability(
        evidence_id="terminal-reference-evidence",
        axis="reference_alignment",
        status="available",
        artifact_id=source_artifact.artifact_id,
        confidence=1.0,
        reason="Exact isolated evidence is available.",
    )
    axis = QualityAxisResult(
        axis="reference_alignment",
        status="passed" if accepted else "failed",
        score=1.0 if accepted else 0.2,
        confidence=1.0,
        evidence_ids=[availability.evidence_id],
    )
    provenance = QualityProvenance(
        job_id=_JOB_ID,
        workflow_id=_WORKFLOW_ID,
        dispatch_id=_DISPATCH_ID,
        source_fingerprint=source_fingerprint,
        input_sha256=stable_json_digest(
            {source_artifact.relative_path: source_artifact.sha256}
        ),
        artifacts=[source_artifact],
    )
    report = IntegratedQualityReport(
        schema_version="0.1.0",
        report_id="aq-terminal-final",
        job_id=_JOB_ID,
        workflow_id=_WORKFLOW_ID,
        dispatch_id=_DISPATCH_ID,
        input_sha256=provenance.input_sha256,
        source_fingerprint=provenance.source_fingerprint,
        gate_profile_id=profile.profile_id,
        gate_profile_sha256=sha256_file(profile_path),
        provenance=provenance,
        producer=producer,
        created_at=_NOW,
        outcome="passed" if accepted else "needs_revision",
        quality_accepted=accepted,
        axes=[axis],
        evidence_availability=[availability],
    )
    output_root = session_root / "integrated_quality" / "final"
    write_integrated_quality_evidence(root, report, output_dir=output_root)
    report_path = output_root / "integrated_quality_report.json"
    return report, artifact_for(root, report_path), source_path


def _portable_delivery(
    root: Path,
) -> tuple[AutonomyArtifact, AutonomyArtifact, Path, Path]:
    """Create one self-consistent minimal V0.7 package and passed round trip."""

    scene_spec = _write(root / "analysis" / "scene_spec.json", b'{"fixture":1}\n')
    blend = _write(root / "blender" / "scene.blend", b"BLENDER-v500")
    source = SourceProvenance(
        scene_spec=_hashed(
            root,
            scene_spec,
            artifact_id="source.scene-spec",
            kind="scene_spec",
        ),
        blend=_hashed(root, blend, artifact_id="source.blend", kind="blend"),
        source_fingerprint="1" * 64,
        build_fingerprint="2" * 64,
    )
    package_root = root / "exports" / "packages" / "portable_gltf" / "aq-package"
    optimization_plan = _write(
        package_root / "metadata" / "optimization_plan.json",
        b'{"plan":"exact"}\n',
    )
    primary = _write(package_root / "asset.glb", b"glTF-terminal-package")
    optimization_receipt = _hashed(
        root,
        optimization_plan,
        artifact_id="optimization.plan",
        kind="optimization_plan",
    )
    package = ExportPackageManifest(
        package_id="aq-package",
        job_id=_JOB_ID,
        run_id="aq-run",
        profile_id="portable_gltf",
        source=source,
        optimization_plan=optimization_receipt,
        status="complete",
        package_root=package_root.relative_to(root).as_posix(),
        files=[
            PackageFile(
                id="package.optimization-plan",
                kind="metadata",
                path=optimization_receipt.path,
                sha256=optimization_receipt.sha256,
                byte_size=optimization_plan.stat().st_size,
                media_type="application/json",
            ),
            PackageFile(
                id="package.primary",
                kind="primary_asset",
                path=primary.relative_to(root).as_posix(),
                sha256=sha256_file(primary),
                byte_size=primary.stat().st_size,
                media_type="model/gltf-binary",
            ),
        ],
        primary_file_id="package.primary",
        semantic_ids=["prop.body"],
        material_ids=["mat.body"],
        created_at=_NOW,
        completed_at=_NOW,
    )
    package_path = package_root / "package_manifest.json"
    write_json_atomic(package_path, package.model_dump(mode="json"))
    package_hashed = _hashed(
        root,
        package_path,
        artifact_id="package.manifest",
        kind="package_manifest",
    )
    inventory = _write(
        root / "optimization" / "runs" / "aq-run" / "roundtrip" / "inventory.json",
        b'{"objects":["prop.body"]}\n',
    )
    bounds = Bounds3D(minimum=(0.0, 0.0, 0.0), maximum=(1.0, 1.0, 1.0))
    roundtrip = RoundTripValidation(
        validation_id="aq-roundtrip",
        job_id=_JOB_ID,
        run_id=package.run_id,
        package_id=package.package_id,
        profile_id=package.profile_id,
        package_manifest=package_hashed,
        imported_inventory=_hashed(
            root,
            inventory,
            artifact_id="roundtrip.inventory",
            kind="roundtrip_inventory",
        ),
        status="passed",
        ok=True,
        passed=0,
        warnings=0,
        failed=0,
        bounds=BoundsComparison(
            source=bounds,
            imported=bounds,
            max_abs_error_m=0.0,
            tolerance_m=0.0001,
            passed=True,
        ),
        expected_semantic_ids=package.semantic_ids,
        observed_semantic_ids=package.semantic_ids,
        semantic_id_coverage=1.0,
        expected_material_ids=package.material_ids,
        observed_material_ids=package.material_ids,
        material_id_coverage=1.0,
        created_at=_NOW,
    )
    roundtrip_path = inventory.parent / "roundtrip_validation.json"
    write_json_atomic(roundtrip_path, roundtrip.model_dump(mode="json"))
    return (
        artifact_for(root, package_path),
        artifact_for(root, roundtrip_path),
        primary,
        inventory,
    )


def _review_delivery(
    root: Path,
    quality_path: Path,
) -> AutonomyArtifact:
    """Publish one real hash-bound review-only bundle for terminal verification."""

    blend = _write(root / "review-inputs" / "best.blend", b"BLENDER-review")
    preview = _write(root / "review-inputs" / "preview.glb", b"glTF-review")
    render = _write(root / "review-inputs" / "beauty.png", b"PNG-review")
    unresolved = _write(root / "review-inputs" / "unresolved.json", b"{}\n")
    history = _write(root / "review-inputs" / "history.json", b"{}\n")
    comparison = _write(root / "review-inputs" / "comparison.json", b"{}\n")
    manifest, _receipt = build_review_bundle(
        root,
        bundle_id="aq-terminal-review",
        session_id=_SESSION_ID,
        job_id=_JOB_ID,
        workflow_id=_WORKFLOW_ID,
        dispatch_id=_DISPATCH_ID,
        termination_reason="plateau",
        best_candidate_blend=blend,
        preview_glb=preview,
        representative_renders=[render],
        integrated_quality_report=quality_path,
        unresolved_findings=unresolved,
        iteration_history=history,
        candidate_comparison=comparison,
        next_manual_actions=["Return to reviewed V0.4 authoring."],
        created_at=_NOW,
    )
    return artifact_for(
        root,
        root
        / "exports"
        / "review_bundles"
        / manifest.bundle_id
        / "review_bundle_manifest.json",
    )


def test_quality_passed_terminal_revalidates_nested_package_and_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Accept current V0.7 evidence and reject nested package or inventory tampering."""

    from codex_blender_modeler.autonomy import service

    root = tmp_path / _JOB_ID
    session_root, state = _terminal_state(root, reason="quality_target_reached")
    _report, quality, _source = _quality_evidence(
        root,
        session_root,
        accepted=True,
    )
    package, roundtrip, primary, inventory = _portable_delivery(root)
    monkeypatch.setattr(
        service,
        "require_unchanged_source",
        lambda expected, _root, _job_id: expected,
    )
    terminal = _terminal_contract(
        root,
        session_root,
        state,
        status="quality_passed",
        reason="quality_target_reached",
        quality=quality,
        package=package,
        roundtrip=roundtrip,
    )
    _verify_terminal_evidence(root, session_root, state, terminal)

    original_primary = primary.read_bytes()
    primary.write_bytes(b"tampered-package")
    with pytest.raises(RuntimeError, match="receipt (size|SHA-256) changed"):
        _verify_terminal_evidence(root, session_root, state, terminal)
    primary.write_bytes(original_primary)

    inventory.write_bytes(b'{"tampered":true}\n')
    with pytest.raises(ValueError, match="roundtrip inventory is stale or tampered"):
        _verify_terminal_evidence(root, session_root, state, terminal)


def test_review_terminal_revalidates_bundle_and_rejects_nested_tampering(
    tmp_path: Path,
) -> None:
    """Accept a non-passing review delivery and reject a changed copied preview."""

    root = tmp_path / _JOB_ID
    session_root, state = _terminal_state(root, reason="plateau")
    report, quality, _source = _quality_evidence(
        root,
        session_root,
        accepted=False,
    )
    quality_path = root / quality.path
    review = _review_delivery(root, quality_path)
    terminal = _terminal_contract(
        root,
        session_root,
        state,
        status="review_required",
        reason="plateau",
        quality=quality,
        review_bundle=review,
    )
    assert report.quality_accepted is False
    _verify_terminal_evidence(root, session_root, state, terminal)

    preview = root / "exports" / "review_bundles" / "aq-terminal-review" / "preview.glb"
    preview.write_bytes(b"changed-review-preview")
    with pytest.raises(ValueError, match="hash mismatch"):
        _verify_terminal_evidence(root, session_root, state, terminal)


@pytest.mark.parametrize("mutation", ["status", "reason", "final_state"])
def test_terminal_rejects_state_status_reason_and_final_state_mismatch(
    tmp_path: Path,
    mutation: str,
) -> None:
    """Reject any terminal claim that differs from the exact final state contract."""

    root = tmp_path / mutation / _JOB_ID
    session_root, state = _terminal_state(root, reason="plateau")
    _report, quality, _source = _quality_evidence(
        root,
        session_root,
        accepted=False,
    )
    review = _review_delivery(root, root / quality.path)
    terminal = _terminal_contract(
        root,
        session_root,
        state,
        status="review_required",
        reason="plateau",
        quality=quality,
        review_bundle=review,
    )
    if mutation == "status":
        changed = terminal.model_copy(update={"status": "blocked"})
        expected = "status differs"
    elif mutation == "reason":
        changed = terminal.model_copy(update={"reason": "cycle_detected"})
        expected = "identity or reason differs"
    else:
        changed = terminal.model_copy(
            update={"final_state": terminal.integrated_quality_report}
        )
        expected = "final-state binding is stale"
    with pytest.raises(ValueError, match=expected):
        _verify_terminal_evidence(root, session_root, state, changed)


@pytest.mark.parametrize("mutation", ["profile", "source"])
def test_terminal_rejects_quality_profile_or_provenance_tampering(
    tmp_path: Path,
    mutation: str,
) -> None:
    """Reject changed quality policy bytes and changed authoritative source evidence."""

    root = tmp_path / mutation / _JOB_ID
    session_root, state = _terminal_state(root, reason="plateau")
    _report, quality, source = _quality_evidence(
        root,
        session_root,
        accepted=False,
    )
    review = _review_delivery(root, root / quality.path)
    terminal = _terminal_contract(
        root,
        session_root,
        state,
        status="review_required",
        reason="plateau",
        quality=quality,
        review_bundle=review,
    )
    if mutation == "profile":
        profile_path = session_root / "quality_gate_profile.final.json"
        profile_path.write_bytes(b'{"tampered":true}\n')
        expected = "profile binding is missing"
    else:
        source.write_bytes(b'{"exact":false}\n')
        expected = "integrated quality provenance changed"
    with pytest.raises(ValueError, match=expected):
        _verify_terminal_evidence(root, session_root, state, terminal)
