"""Focused host and opt-in Blender tests for AQ reference benchmark 0.2."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from codex_blender_modeler.autonomy_benchmarks import v02_runner
from codex_blender_modeler.autonomy_benchmarks.v02_models import (
    BenchmarkArtifactV02,
    BenchmarkCaseResultV02,
    BenchmarkCaseV02,
    BenchmarkManifestV02,
    BenchmarkMetricSetV02,
    BenchmarkReportV02,
    BenchmarkStagePlanV02,
    BenchmarkStageResultV02,
    BlenderBenchmarkReceiptV02,
    KnownCameraV02,
    MetricDirectionExpectationV02,
    MetricDirectionResultV02,
    StageExecutionExpectationV02,
    SyntheticPrimitiveV02,
    SyntheticReferenceRecipeV02,
    benchmark_case_contract_sha256_v02,
)
from codex_blender_modeler.autonomy_benchmarks.v02_runner import (
    run_benchmark_manifest_v02,
)

MANIFEST = Path("examples/autonomous_quality_benchmarks_v02/manifest.json")
REQUIRED_CATEGORIES = {
    "simple_hard_surface_box",
    "curved_loft",
    "swept_handle",
    "boolean_panel",
    "ornate_multi_part_prop",
    "multi_material_prop",
    "wood_object",
    "signage_decal_object",
    "emissive_crystal_prop",
    "small_static_assembly",
}


def _manifest_payload() -> dict:
    """Load a fresh AQ 0.2 fixture payload for mutation-isolated tests."""

    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _write_manifest(path: Path, payload: dict) -> Path:
    """Write one temporary mutated manifest for strict negative tests."""

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def test_v02_manifest_covers_ten_requested_categories_and_exact_hashes() -> None:
    """Require all requested categories, four comparison stages, and exact case hashes."""

    manifest = BenchmarkManifestV02.model_validate_json(MANIFEST.read_bytes())
    assert len(manifest.cases) == 10
    assert {item.category for item in manifest.cases} == REQUIRED_CATEGORIES
    assert manifest.human_review_status == "not_reviewed"
    assert manifest.external_downloads_allowed is False
    for case in manifest.cases:
        assert benchmark_case_contract_sha256_v02(
            case.model_dump(mode="json")
        ) == case.contract_sha256
        assert [item.stage_id for item in case.stages] == [
            "v09_initial",
            "aq_v1_initial",
            "aq_v2_initial",
            "aq_v2_final",
        ]
        assert {item.semantic_id for item in case.reference_recipe.primitives}
        assert any(item.critical for item in case.reference_recipe.primitives)


def test_v02_host_runner_is_byte_deterministic_and_directional(tmp_path: Path) -> None:
    """Produce byte-identical reports with exact improved final synthetic evidence."""

    first_path = tmp_path / "first" / "report.json"
    second_path = tmp_path / "second" / "report.json"
    first = run_benchmark_manifest_v02(MANIFEST, first_path)
    second = run_benchmark_manifest_v02(MANIFEST, second_path)
    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first.ok is True
    assert first.passed_case_count == 10
    assert first.human_review_status == "not_reviewed"
    assert first.external_downloads_used is False
    for case in first.case_results:
        assert case.human_review_status == "not_reviewed"
        assert all(item.matched for item in case.metric_direction_results)
        final = case.stage_results[-1]
        assert final.stage_id == "aq_v2_final"
        assert final.metrics.silhouette_iou == 1.0
        assert final.metrics.contour_boundary_f_score == 1.0
        assert final.metrics.contour_chamfer_norm == 0.0
        assert final.metrics.mean_semantic_iou == 1.0
        assert final.metrics.minimum_critical_semantic_iou == 1.0
        assert final.execution.package_status == "not_run"
        assert final.execution.roundtrip_status == "not_run"
        assert final.duration_basis == "deterministic_fixture_model"


def test_v02_artifacts_bind_known_camera_reference_and_every_stage(tmp_path: Path) -> None:
    """Verify exact hashes for known camera, beauty, silhouette, object ID, and masks."""

    report = run_benchmark_manifest_v02(MANIFEST, tmp_path / "report.json")
    for case in report.case_results:
        reference_roles = {item.role for item in case.reference_artifacts}
        assert {
            "reference.known_camera",
            "reference.beauty",
            "reference.silhouette",
            "reference.object_id",
            "reference.semantic_mask",
        } <= reference_roles
        for artifact in case.reference_artifacts:
            path = tmp_path / artifact.path
            assert path.is_file()
            assert v02_runner._file_sha256(path) == artifact.sha256
            assert path.stat().st_size == artifact.byte_size
        for stage in case.stage_results:
            stage_roles = {item.role for item in stage.artifacts}
            assert {
                "candidate.beauty",
                "candidate.silhouette",
                "candidate.object_id",
                "candidate.semantic_mask",
            } <= stage_roles
            assert all(item.stage_id == stage.stage_id for item in stage.artifacts)


def test_v02_manifest_rejects_tampering_unknown_fields_and_missing_coverage(
    tmp_path: Path,
) -> None:
    """Fail closed for a stale case digest, injected field, or removed category."""

    payload = _manifest_payload()
    payload["cases"][0]["reference_recipe"]["primitives"][0]["bbox_px"][0] += 1
    with pytest.raises(ValueError, match="contract SHA-256 does not match"):
        BenchmarkManifestV02.model_validate_json(json.dumps(payload))
    payload = _manifest_payload()
    payload["arbitrary_script"] = "unsafe.py"
    with pytest.raises(ValueError, match="Extra inputs"):
        BenchmarkManifestV02.model_validate_json(json.dumps(payload))
    payload = _manifest_payload()
    payload["cases"] = [
        item for item in payload["cases"] if item["category"] != "wood_object"
    ]
    path = _write_manifest(tmp_path / "missing.json", payload)
    with pytest.raises(ValueError, match="at least 10|missing categories"):
        BenchmarkManifestV02.model_validate_json(path.read_bytes())


def test_v02_report_and_artifact_paths_are_immutable(tmp_path: Path) -> None:
    """Refuse report overwrite and reuse of a prior run-owned artifact root."""

    output = tmp_path / "report.json"
    run_benchmark_manifest_v02(MANIFEST, output)
    with pytest.raises(FileExistsError, match="report already exists"):
        run_benchmark_manifest_v02(MANIFEST, output)
    second = tmp_path / "second.json"
    with pytest.raises(FileExistsError, match="artifact root already exists"):
        run_benchmark_manifest_v02(MANIFEST, second)


def test_v02_blender_is_opt_in_and_bounded_to_declared_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep Blender disabled by default and invoke only explicitly supported fixtures."""

    called: list[str] = []

    def fake_blender_case_v02(*, output_root, case, camera_sha256):
        """Return a strict fake receipt without launching Blender in a host-only test."""

        called.append(case.case_id)
        assert output_root == tmp_path
        return BlenderBenchmarkReceiptV02(
            case_id=case.case_id,
            case_contract_path=f"artifacts/{case.case_id}/blender/case_contract.json",
            case_contract_file_sha256="a" * 64,
            blend_path=f"artifacts/{case.case_id}/blender/probe.blend",
            blend_sha256="b" * 64,
            render_path=f"artifacts/{case.case_id}/blender/probe.png",
            render_sha256="c" * 64,
            object_count=len(case.reference_recipe.primitives),
            camera_sha256=camera_sha256,
        )

    monkeypatch.setattr(v02_runner, "_run_blender_case_v02", fake_blender_case_v02)
    report = run_benchmark_manifest_v02(
        MANIFEST,
        tmp_path / "report.json",
        run_blender_smoke=True,
    )
    assert report.ok is True
    assert report.blender_executed_case_count == 2
    assert called == ["simple_hard_surface_box", "curved_loft"]
    assert all(
        item.blender_status
        == ("passed" if item.case_id in set(called) else "not_applicable")
        for item in report.case_results
    )


def test_v02_public_schema_classes_remain_strict() -> None:
    """Generate every public contract schema and retain extra-field rejection metadata."""

    schema_classes = [
        BenchmarkManifestV02,
        BenchmarkCaseV02,
        KnownCameraV02,
        SyntheticPrimitiveV02,
        SyntheticReferenceRecipeV02,
        StageExecutionExpectationV02,
        BenchmarkStagePlanV02,
        MetricDirectionExpectationV02,
        BenchmarkArtifactV02,
        BenchmarkMetricSetV02,
        BenchmarkStageResultV02,
        MetricDirectionResultV02,
        BlenderBenchmarkReceiptV02,
        BenchmarkCaseResultV02,
        BenchmarkReportV02,
    ]
    for model in schema_classes:
        schema = model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert schema["title"] == model.__name__


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_AQ_V02_BENCHMARK_BLENDER_SMOKE") != "1",
    reason="set CBM_RUN_AQ_V02_BENCHMARK_BLENDER_SMOKE=1 for Blender 5 smoke",
)
def test_v02_fixed_blender_probe_smoke(tmp_path: Path) -> None:
    """Build and render only declared cases through the fixed Blender 5 probe."""

    report = run_benchmark_manifest_v02(
        MANIFEST,
        tmp_path / "report.json",
        run_blender_smoke=True,
    )
    assert report.ok is True
    assert report.blender_executed_case_count == 2
    for case in report.case_results:
        if case.blender_status == "passed":
            assert case.blender_receipt is not None
            assert (tmp_path / case.blender_receipt.blend_path).is_file()
            assert (tmp_path / case.blender_receipt.render_path).is_file()
