"""Opt-in Blender 5 smoke for optimized-to-clean-import AQ v2 geometry survival."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.structural_geometry.geometry_delivery_equivalence import (
    bind_corner_evidence,
    build_numerical_survival_report,
    compare_corner_evidence,
    load_corner_evidence,
    needs_numerical_comparison,
    validate_numerical_survival_report,
)
from codex_blender_modeler.structural_geometry.geometry_delivery_inspector_v02 import (
    inspect_delivery_geometry_stage_v02,
)
from codex_blender_modeler.structural_geometry.geometry_survival_v02 import (
    compare_geometry_stage_snapshots_v02,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AQ_V02_DELIVERY_GEOMETRY_SMOKE") != "1",
    reason="set CBM_RUN_AQ_V02_DELIVERY_GEOMETRY_SMOKE=1 for Blender smoke tests",
)


@pytest.mark.parametrize("precision_boundary", [False, True])
def test_direct_glb_and_fbx_preserve_delivery_geometry_equivalence(
    tmp_path: Path,
    precision_boundary: bool,
) -> None:
    """Inspect direct GLB/FBX, including exact-bound proof of a fixed float32 UV boundary."""

    root = tmp_path / "delivery_geometry"
    root.mkdir()
    optimized = root / "optimization" / "optimized.blend"
    glb = root / "exports" / "asset.glb"
    fbx = root / "exports" / "model.fbx"
    receipt = root / "reports" / "fixture_receipt.json"
    run_blender(
        "probe_geometry_delivery_v02.py",
        [
            "--job-root",
            str(root),
            "--optimized-blend",
            str(optimized),
            "--glb",
            str(glb),
            "--fbx",
            str(fbx),
            "--receipt",
            str(receipt),
            *(["--precision-boundary-fixture"] if precision_boundary else []),
        ],
        factory_startup=True,
        disable_autoexec=True,
    )
    original_hashes = {path: sha256_file(path) for path in (optimized, glb, fbx)}
    source = inspect_delivery_geometry_stage_v02(
        job_root=root,
        artifact_relative_path="optimization/optimized.blend",
        stage="optimized_lod0",
        output_relative_path="reports/optimized_snapshot.json",
        source_fingerprint_sha256="a" * 64,
        build_fingerprint_sha256="b" * 64,
        corner_evidence_relative_path="reports/optimized_corners.json",
    )
    for profile, stage, relative in (
        ("GLB", "clean_import_glb", "exports/asset.glb"),
        ("FBX", "clean_import_fbx", "exports/model.fbx"),
    ):
        target = inspect_delivery_geometry_stage_v02(
            job_root=root,
            artifact_relative_path=relative,
            stage=stage,
            output_relative_path=f"reports/{profile.casefold()}_snapshot.json",
            source_fingerprint_sha256="a" * 64,
            build_fingerprint_sha256="b" * 64,
            corner_evidence_relative_path=(
                "reports/glb_corners.json" if profile == "GLB" else None
            ),
        )
        report = compare_geometry_stage_snapshots_v02(
            report_id=f"delivery-{profile.casefold()}-survival",
            relation="optimized_to_clean_import",
            source=source,
            target=target,
            package_format=profile,
        )
        if profile == "GLB":
            left = bind_corner_evidence(root, root / "reports/optimized_corners.json")
            right = bind_corner_evidence(root, root / "reports/glb_corners.json")
            first = load_corner_evidence(root, left)
            second = load_corner_evidence(root, right)
            comparison = compare_corner_evidence(first, second)
            assert comparison.corner_count == 3 * source.evaluated_triangle_count
            assert needs_numerical_comparison(report) is precision_boundary
            if precision_boundary:
                original = report
                report = build_numerical_survival_report(
                    report_id=original.report_id,
                    source=first,
                    target=second,
                    source_artifact=left,
                    target_artifact=right,
                )
                assert original.overall_status == "failed"
                assert report.exact_snapshot_comparison == original
                assert comparison.maximum_uv_component_error < 0.0000001
                assert validate_numerical_survival_report(root, report) == (source, target)
        assert report.overall_status in {"exact", "equivalent", "known_loss"}
        assert all(check.status != "failed" for check in report.checks)
        assert report.package_format == profile
    assert {path: sha256_file(path) for path in original_hashes} == original_hashes
