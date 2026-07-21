from __future__ import annotations

from pathlib import Path

import pytest

from codex_blender_modeler.optimization.models import HashedArtifact, SourceProvenance
from codex_blender_modeler.optimization.optimizer import (
    _asset_cost_report,
    _lod_manifest,
    _maximum_lod_triangle_count,
)
from codex_blender_modeler.optimization.profiles import create_builtin_profile


def _artifact(artifact_id: str, kind: str, path: str) -> HashedArtifact:
    """Create one deterministic provenance artifact for LOD host tests."""

    return HashedArtifact(
        id=artifact_id,
        kind=kind,  # type: ignore[arg-type]
        path=path,
        sha256="a" * 64,
    )


def _source() -> SourceProvenance:
    """Create the minimum valid canonical source provenance fixture."""

    return SourceProvenance(
        scene_spec=_artifact("source.scene", "scene_spec", "analysis/scene_spec.json"),
        blend=_artifact("source.blend", "blend", "blender/scene.blend"),
        source_fingerprint="b" * 64,
        build_fingerprint="c" * 64,
    )


def _record(role: str, triangles: int, *, level: int | None = None) -> dict[str, object]:
    """Build one normalized Blender inventory record for a semantic LOD family."""

    return {
        "name": f"asset.body.{role}.{level}",
        "type": "MESH",
        "semantic_id": "asset.body",
        "asset_role": role,
        "lod_level": level,
        "bbox_world": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
        "topology": {"triangles_estimated": triangles},
        "material_ids": ["mat.body"],
    }


def _manifest(
    tmp_path: Path,
    records: list[dict[str, object]],
    *,
    profile_id: str = "portable_gltf",
):
    """Normalize one test inventory through the production V0.7 LOD manifest builder."""

    blend = tmp_path / "optimization" / "runs" / "run-001" / "optimized" / "scene.blend"
    blend.parent.mkdir(parents=True, exist_ok=True)
    blend.write_bytes(b"derived blend")
    profile = create_builtin_profile("lod_contract_test", profile_id, "static_prop")
    return _lod_manifest(
        tmp_path,
        "run-001",
        profile,
        _source(),
        {"objects": records},
        blend,
    )


@pytest.mark.parametrize(
    ("source_triangles", "target_ratio", "expected"),
    [
        (0, 0.6, 0),
        (1, 0.3, 1),
        (7, 0.6, 5),
        (10, 0.3, 3),
    ],
)
def test_maximum_lod_count_uses_only_whole_triangle_ceiling(
    source_triangles: int,
    target_ratio: float,
    expected: int,
) -> None:
    """Convert profile ratios to deterministic integral targets without approximation bands."""

    assert _maximum_lod_triangle_count(source_triangles, target_ratio) == expected


def test_lod_manifest_requires_exact_profile_ratios_and_keeps_silhouette_unverified(
    tmp_path: Path,
) -> None:
    """Accept exact rounded targets while leaving every silhouette metric explicitly null."""

    manifest = _manifest(
        tmp_path,
        [
            _record("render", 7, level=0),
            _record("lod", 5, level=1),
            _record("lod", 3, level=2),
        ],
    )

    assert [entry.level for entry in manifest.entries] == [0, 1, 2]
    assert [entry.triangle_count for entry in manifest.entries] == [7, 5, 3]
    assert all(entry.silhouette_iou is None for entry in manifest.entries)
    assert manifest.unverified_checks == ["silhouette_iou"]


def test_lod_manifest_rounds_each_semantic_instance_before_aggregation(
    tmp_path: Path,
) -> None:
    """Accept repeated objects whose indivisible triangle targets round per instance."""

    manifest = _manifest(
        tmp_path,
        [
            _record("render", 3, level=0),
            _record("render", 3, level=0),
            _record("lod", 2, level=1),
            _record("lod", 2, level=1),
            _record("lod", 1, level=2),
            _record("lod", 1, level=2),
        ],
    )

    assert [entry.triangle_count for entry in manifest.entries] == [6, 4, 2]


def test_lod_manifest_keeps_per_instance_rounding_after_semantic_batching(
    tmp_path: Path,
) -> None:
    """Use pre-batch action evidence so joined LODs keep their original integral ceilings."""

    blend = tmp_path / "optimization" / "runs" / "run-001" / "optimized" / "scene.blend"
    blend.parent.mkdir(parents=True, exist_ok=True)
    blend.write_bytes(b"derived blend")
    profile = create_builtin_profile("lod_contract_test", "portable_gltf", "static_prop")
    manifest = _lod_manifest(
        tmp_path,
        "run-001",
        profile,
        _source(),
        {
            "objects": [
                _record("render", 4, level=0),
                _record("lod", 4, level=1),
                _record("lod", 2, level=2),
            ],
            "actions": [
                {"semantic_id": "asset.body", "lod_triangle_counts": {"0": 2}},
                {"semantic_id": "asset.body", "lod_triangle_counts": {"0": 2}},
            ],
        },
        blend,
    )
    assert [entry.triangle_count for entry in manifest.entries] == [4, 4, 2]


def test_asset_cost_report_enforces_only_explicit_fail_budgets() -> None:
    """Keep default metrics advisory but fail one explicitly bounded proxy when requested."""

    profile = create_builtin_profile(
        "lod_contract_test",
        "portable_gltf",
        "static_prop",
        budget_enforcement="fail",
        max_lod0_render_objects=1,
    )
    snapshot = {
        "lod0_render_objects": 2,
        "lod0_material_slots": 2,
        "lod0_estimated_draw_calls": 2,
        "lod0_vertices": 16,
        "lod0_triangles": 24,
        "lod_objects": 4,
        "collider_objects": 2,
        "collider_triangles": 24,
        "total_derived_triangles": 96,
        "unique_materials": 1,
        "overlap_candidates": 0,
    }
    report = _asset_cost_report(
        "run-001",
        profile,
        _source(),
        {
            "cost_optimization": {
                "before": snapshot,
                "after": snapshot,
                "consolidation_batches": [],
                "cleanup_records": [],
                "instance_groups": [],
                "overlap_findings_before": [],
                "overlap_findings_after": [],
                "limitations": ["Runtime draw calls remain unverified."],
            }
        },
    )
    assert report.ok is False
    assert report.budgets[0].status == "failed"


def test_lod_manifest_accepts_results_below_the_profile_triangle_budget(
    tmp_path: Path,
) -> None:
    """Allow topology-driven extra reduction while keeping silhouette explicitly unverified."""

    manifest = _manifest(
        tmp_path,
        [
            _record("render", 7, level=0),
            _record("lod", 4, level=1),
            _record("lod", 2, level=2),
        ],
    )

    assert [entry.triangle_count for entry in manifest.entries] == [7, 4, 2]


def test_lod_manifest_rejects_results_above_the_profile_triangle_budget(
    tmp_path: Path,
) -> None:
    """Reject a derived LOD that fails to meet the profile reduction ceiling."""

    with pytest.raises(RuntimeError, match=r"LOD1 triangle count.*actual=6.*maximum=5"):
        _manifest(
            tmp_path,
            [
                _record("render", 7, level=0),
                _record("lod", 6, level=1),
                _record("lod", 3, level=2),
            ],
        )


@pytest.mark.parametrize(
    "records",
    [
        [_record("render", 10, level=0), _record("lod", 6, level=1)],
        [
            _record("render", 10, level=0),
            _record("lod", 6, level=1),
            _record("lod", 3, level=2),
            _record("lod", 1, level=3),
        ],
        [_record("lod", 6, level=1), _record("lod", 3, level=2)],
    ],
)
def test_lod_manifest_requires_exact_expected_level_set(
    tmp_path: Path,
    records: list[dict[str, object]],
) -> None:
    """Reject missing LOD0, missing targets, and extra levels outside the AssetProfile."""

    with pytest.raises(RuntimeError, match="LOD levels|no LOD0"):
        _manifest(tmp_path, records)


def test_disabled_lod_profile_accepts_only_lod0(tmp_path: Path) -> None:
    """Keep OBJ's disabled LOD policy limited to its evaluated LOD0 copy."""

    manifest = _manifest(
        tmp_path,
        [_record("render", 12, level=0)],
        profile_id="obj_legacy",
    )
    assert [entry.level for entry in manifest.entries] == [0]
    with pytest.raises(RuntimeError, match="LOD levels"):
        _manifest(
            tmp_path / "extra",
            [_record("render", 12, level=0), _record("lod", 6, level=1)],
            profile_id="obj_legacy",
        )
