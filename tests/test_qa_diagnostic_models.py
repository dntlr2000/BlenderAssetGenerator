from __future__ import annotations

from datetime import UTC, datetime

import pytest

from codex_blender_modeler.qa.diagnostic_models import (
    AssemblyDiagnosticEvidence,
    AssemblyMultiviewBundleEvidence,
    BoundedCameraDelta,
    CameraProbeResult,
    CameraProbeSemanticScore,
    DiagnosticAttribution,
    QADiagnosticBundleManifest,
    QADiagnosticReport,
    QADiagnosticRequest,
    SemanticMaskBinding,
    SemanticReferenceMaskManifest,
    SemanticReferenceMaskRecord,
)

SHA = "a" * 64
RUN_ROOT = "qa/runs/run-001"
DIAGNOSTIC_ROOT = f"{RUN_ROOT}/diagnostics/diag-001"


def _semantic_binding() -> SemanticMaskBinding:
    """Build one valid run-owned semantic mask binding for contract tests."""

    return SemanticMaskBinding(
        semantic_id="weapon.trigger",
        role="supporting",
        source_id="reference",
        confidence=0.9,
        reference_mask_path=f"{DIAGNOSTIC_ROOT}/masks/trigger.reference.png",
        reference_mask_sha256=SHA,
        rendered_mask_path=f"{DIAGNOSTIC_ROOT}/masks/trigger.rendered.png",
        rendered_mask_sha256=SHA,
    )


def _request_payload() -> dict[str, object]:
    """Return a minimal valid diagnostic request payload."""

    return {
        "job_id": "weapon_test",
        "qa_run_id": "run-001",
        "diagnostic_id": "diag-001",
        "artifact_root": DIAGNOSTIC_ROOT,
        "visual_qa_request_path": f"{RUN_ROOT}/request.json",
        "visual_qa_request_sha256": SHA,
        "visual_qa_report_path": f"{RUN_ROOT}/visual_qa_report.json",
        "visual_qa_report_sha256": SHA,
        "render_pass_manifest_path": f"{RUN_ROOT}/render_pass_manifest.json",
        "render_pass_manifest_sha256": SHA,
        "scene_spec_sha256": SHA,
        "semantic_masks": [_semantic_binding().model_dump(mode="json")],
    }


def _baseline_probe() -> CameraProbeResult:
    """Build one neutral scored baseline probe."""

    return CameraProbeResult(
        probe_id="baseline",
        is_baseline=True,
        status="scored",
        overall_score=0.6,
        semantic_scores=[
            CameraProbeSemanticScore(
                semantic_id="weapon.trigger",
                scorable=True,
                score=0.6,
            )
        ],
        evidence_path=f"{DIAGNOSTIC_ROOT}/probes/baseline.json",
        evidence_sha256=SHA,
    )


def test_diagnostic_request_accepts_hash_bound_run_owned_inputs() -> None:
    """A valid request retains its exact QA-run and semantic-mask bindings."""

    request = QADiagnosticRequest.model_validate(_request_payload())

    assert request.artifact_root == DIAGNOSTIC_ROOT
    assert request.semantic_masks[0].semantic_id == "weapon.trigger"
    assert request.max_camera_probes == 12


def test_diagnostic_request_allows_missing_explicit_semantic_masks() -> None:
    """Legacy jobs can request an honest unscorable companion diagnostic."""

    payload = _request_payload()
    payload["semantic_masks"] = []

    request = QADiagnosticRequest.model_validate(payload)

    assert request.semantic_masks == []


def test_semantic_reference_manifest_binds_masks_to_reference_and_scene() -> None:
    """Reusable semantic masks are exact evidence instead of inferred bounding boxes."""

    manifest = SemanticReferenceMaskManifest(
        job_id="weapon_test",
        reference_path="input/reference.png",
        reference_sha256=SHA,
        scene_spec_sha256=SHA,
        masks=[
            SemanticReferenceMaskRecord(
                semantic_id="weapon.trigger",
                source_id="reference",
                path="analysis/masks/semantic/weapon.trigger.png",
                sha256=SHA,
                confidence=0.94,
            )
        ],
        generated_at=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert manifest.manifest_version == "semantic_reference_masks_v1"
    assert manifest.masks[0].path.startswith("analysis/masks/")

    with pytest.raises(ValueError, match="inside analysis/masks"):
        SemanticReferenceMaskManifest.model_validate(
            {
                **manifest.model_dump(mode="json"),
                "masks": [
                    {
                        **manifest.masks[0].model_dump(mode="json"),
                        "path": "input/claimed_trigger.png",
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("artifact_root", f"{RUN_ROOT}/other/diag-001", "artifact_root"),
        (
            "visual_qa_report_path",
            "qa/runs/other-run/visual_qa_report.json",
            "must remain inside",
        ),
        ("scene_spec_path", "../scene_spec.json", "must not escape"),
    ],
)
def test_diagnostic_request_rejects_unowned_or_escaping_paths(
    field: str,
    value: str,
    message: str,
) -> None:
    """Request validation rejects path escape and cross-run evidence substitution."""

    payload = _request_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        QADiagnosticRequest.model_validate(payload)


def test_diagnostic_request_requires_optional_path_hash_pairs() -> None:
    """Optional source evidence cannot be declared without its exact hash."""

    payload = _request_payload()
    payload["modeling_plan_path"] = "analysis/modeling_plan.json"

    with pytest.raises(ValueError, match="supplied together"):
        QADiagnosticRequest.model_validate(payload)


def test_bounded_camera_delta_rejects_large_side_view_substitution() -> None:
    """Camera probes stay close to the approved comparison view."""

    with pytest.raises(ValueError, match="15 degrees"):
        BoundedCameraDelta(rotation_delta_deg=(0.0, 25.0, 0.0))


def test_camera_probe_requires_a_neutral_baseline() -> None:
    """The baseline flag cannot be assigned to an altered comparison camera."""

    with pytest.raises(ValueError, match="neutral camera"):
        CameraProbeResult(
            probe_id="baseline",
            is_baseline=True,
            status="scored",
            camera_delta=BoundedCameraDelta(distance_scale=1.1),
            overall_score=0.6,
            semantic_scores=[
                CameraProbeSemanticScore(
                    semantic_id="weapon.trigger",
                    scorable=True,
                    score=0.6,
                )
            ],
            evidence_path=f"{DIAGNOSTIC_ROOT}/probes/baseline.json",
            evidence_sha256=SHA,
        )


def test_companion_report_is_advisory_and_requires_one_baseline() -> None:
    """The companion report is explicitly advisory and baseline-bound."""

    baseline = _baseline_probe()
    report = QADiagnosticReport(
        job_id="weapon_test",
        qa_run_id="run-001",
        diagnostic_id="diag-001",
        request_path=f"{DIAGNOSTIC_ROOT}/request.json",
        request_sha256=SHA,
        status="degraded",
        semantic_metrics=[],
        camera_probes=[baseline],
        assembly_evidence=AssemblyDiagnosticEvidence(),
        attribution=DiagnosticAttribution(
            classification="ambiguous",
            confidence=0.35,
            baseline_probe_id="baseline",
            baseline_score=0.6,
            reasons=["bounded probes do not separate camera and geometry"],
        ),
        limitations=["explicit semantic reference masks are unavailable"],
        generated_at=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert report.schema_version == "0.6.0"
    assert report.diagnostic_version == "camera_geometry_attribution_v1"
    assert report.advisory_only is True

    with pytest.raises(ValueError, match="exactly one baseline"):
        QADiagnosticReport.model_validate(
            {
                **report.model_dump(mode="json"),
                "camera_probes": [
                    {
                        **baseline.model_dump(mode="json"),
                        "is_baseline": False,
                    }
                ],
            }
        )


def test_companion_bundle_binds_direct_and_advisory_evidence() -> None:
    """The companion bundle keeps canonical QA and structural evidence hash-separated."""

    multiview = AssemblyMultiviewBundleEvidence(
        status="warning",
        run_id="assembly-run-001",
        plan_path="qa/assembly_sanity/runs/assembly-run-001/plan.json",
        plan_sha256=SHA,
        report_path="qa/assembly_sanity/runs/assembly-run-001/report.json",
        report_sha256=SHA,
        render_manifest_path=(
            "qa/assembly_sanity/runs/assembly-run-001/render_manifest.json"
        ),
        render_manifest_sha256=SHA,
        reference_comparison_status="unscorable",
    )
    bundle = QADiagnosticBundleManifest(
        job_id="weapon_test",
        qa_run_id="run-001",
        diagnostic_id="diag-001",
        visual_qa_report_path=f"{RUN_ROOT}/visual_qa_report.json",
        visual_qa_report_sha256=SHA,
        diagnostic_request_path=f"{DIAGNOSTIC_ROOT}/request.json",
        diagnostic_request_sha256=SHA,
        diagnostic_report_path=f"{DIAGNOSTIC_ROOT}/report.json",
        diagnostic_report_sha256=SHA,
        camera_probe_plan_path=f"{DIAGNOSTIC_ROOT}/camera_probes/plan.json",
        camera_probe_plan_sha256=SHA,
        camera_probe_manifest_path=(
            f"{DIAGNOSTIC_ROOT}/camera_probes/render_manifest.json"
        ),
        camera_probe_manifest_sha256=SHA,
        assembly_multiview=multiview,
        created_at=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert bundle.canonical_v06_qa_run is False
    assert bundle.canonical_v06_score_unchanged is True
    assert bundle.assembly_multiview.reference_comparison_status == "unscorable"


def test_companion_bundle_rejects_partial_multiview_and_cross_run_paths() -> None:
    """A partial structural binding or substituted QA run fails closed."""

    with pytest.raises(ValueError, match="every binding"):
        AssemblyMultiviewBundleEvidence(
            status="passed",
            run_id="assembly-run-001",
        )

    payload = {
        "job_id": "weapon_test",
        "qa_run_id": "run-001",
        "diagnostic_id": "diag-001",
        "visual_qa_report_path": "qa/runs/other-run/visual_qa_report.json",
        "visual_qa_report_sha256": SHA,
        "diagnostic_request_path": f"{DIAGNOSTIC_ROOT}/request.json",
        "diagnostic_request_sha256": SHA,
        "diagnostic_report_path": f"{DIAGNOSTIC_ROOT}/report.json",
        "diagnostic_report_sha256": SHA,
        "camera_probe_plan_path": f"{DIAGNOSTIC_ROOT}/camera_probes/plan.json",
        "camera_probe_plan_sha256": SHA,
        "camera_probe_manifest_path": (
            f"{DIAGNOSTIC_ROOT}/camera_probes/render_manifest.json"
        ),
        "camera_probe_manifest_sha256": SHA,
        "assembly_multiview": {"status": "not_requested"},
        "created_at": datetime(2026, 8, 3, tzinfo=UTC).isoformat(),
    }
    with pytest.raises(ValueError, match="canonical run"):
        QADiagnosticBundleManifest.model_validate(payload)
