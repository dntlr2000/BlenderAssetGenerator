"""Focused deterministic tests for the Autonomous Quality benchmark fixture and runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_blender_modeler.autonomy_benchmarks import (
    BenchmarkManifest,
    run_benchmark_manifest,
    runner,
)

MANIFEST = Path("examples/autonomous_quality_benchmarks/manifest.json")


def _manifest_payload() -> dict:
    """Load a fresh benchmark fixture payload for mutation-isolated tests."""

    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _write_manifest(path: Path, payload: dict) -> Path:
    """Write one temporary benchmark manifest with stable UTF-8 formatting."""

    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def test_manifest_covers_minimum_categories_and_one_material_case() -> None:
    """Require every requested category plus explicit material-graph contract coverage."""

    manifest = BenchmarkManifest.model_validate(_manifest_payload())
    categories = {case.category for case in manifest.cases}
    assert {
        "simple_box",
        "loft",
        "sweep",
        "boolean_panel",
        "small_assembly",
        "terrain",
        "topology_uv_failure",
        "material_graph",
    } == categories


def test_host_runner_is_deterministic_and_records_expected_negative(tmp_path: Path) -> None:
    """Produce byte-identical host reports and retain the expected UV hard failure."""

    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first = run_benchmark_manifest(MANIFEST, first_path)
    second = run_benchmark_manifest(MANIFEST, second_path)
    assert first.ok is True
    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    topology = next(
        case for case in first.case_results if case.category == "topology_uv_failure"
    )
    assert topology.observed_outcome == "failed"
    assert topology.expectation_matched is True
    assert topology.host_metrics["uv0_outcome"] == "hard_failure"


def test_invalid_negative_fixture_cannot_masquerade_as_expected_failure(
    tmp_path: Path,
) -> None:
    """Treat an evaluation exception as a gate failure even for a negative fixture."""

    payload = _manifest_payload()
    topology = next(
        case for case in payload["cases"] if case["category"] == "topology_uv_failure"
    )
    topology["payload"]["profile"] = "not-a-profile"
    manifest = _write_manifest(tmp_path / "invalid-negative.json", payload)
    report = run_benchmark_manifest(manifest, tmp_path / "report.json")
    result = next(
        case for case in report.case_results if case.category == "topology_uv_failure"
    )
    assert report.ok is False
    assert result.expectation_matched is False
    assert result.ok is False
    assert result.error is not None


def test_report_path_is_immutable(tmp_path: Path) -> None:
    """Refuse to overwrite an earlier exact benchmark report."""

    output = tmp_path / "report.json"
    run_benchmark_manifest(MANIFEST, output)
    with pytest.raises(FileExistsError, match="already exists"):
        run_benchmark_manifest(MANIFEST, output)


def test_manifest_rejects_missing_category_and_unknown_fields() -> None:
    """Fail closed when fixture coverage shrinks or undeclared data is injected."""

    payload = _manifest_payload()
    payload["cases"] = [
        case for case in payload["cases"] if case["category"] != "terrain"
    ]
    with pytest.raises(ValueError, match="missing required categories"):
        BenchmarkManifest.model_validate(payload)
    payload = _manifest_payload()
    payload["arbitrary_command"] = "python unsafe.py"
    with pytest.raises(ValueError, match="Extra inputs"):
        BenchmarkManifest.model_validate(payload)


def test_blender_opt_in_runs_only_declared_structural_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep Blender disabled by default and bounded to the three declared smoke cases."""

    called: list[str] = []

    def fake_blender_case(case, output_root):
        """Return contained fake artifacts without launching Blender in the host test."""

        called.append(case.case_id)
        assert output_root == tmp_path
        return {
            "mesh": f"blender/{case.case_id}/geometry/materialized.mesh.json",
            "blend": f"blender/{case.case_id}/blender/materialized.blend",
            "report": f"blender/{case.case_id}/reports/materialization.json",
            "mesh_sha256": "f" * 64,
        }

    monkeypatch.setattr(runner, "_run_blender_case", fake_blender_case)
    report = run_benchmark_manifest(
        MANIFEST,
        tmp_path / "report.json",
        run_blender_smoke=True,
    )
    assert report.ok is True
    assert report.blender_executed_case_count == 3
    assert called == ["tapered_loft", "curved_sweep", "boolean_panel"]
    assert all(
        not Path(value).is_absolute()
        for case in report.case_results
        for value in case.blender_artifacts.values()
        if not value.startswith("f" * 64)
    )


def test_blender_case_parses_strict_structural_geometry_from_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept JSON arrays at the strict contract boundary before Blender materialization."""

    captured = []

    def fake_materialize_structural_candidate(**kwargs):
        """Capture the validated candidate without launching Blender."""

        captured.append(kwargs["candidate"])
        return kwargs["candidate"]

    monkeypatch.setattr(
        runner,
        "materialize_structural_candidate",
        fake_materialize_structural_candidate,
    )
    manifest = BenchmarkManifest.model_validate(_manifest_payload())
    loft = next(case for case in manifest.cases if case.category == "loft")

    artifacts = runner._run_blender_case(loft, tmp_path)

    assert captured[0].geometry.kind == "loft"
    assert artifacts["mesh"].endswith("materialized.mesh.json")
