from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_runtime():
    """Import the Blender-stdlib UV requirement helper without importing bpy."""

    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "surface_detail_uv_runtime.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_test_surface_detail_uv_runtime",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_plan(root: Path, surface_details: list[dict]) -> None:
    """Write one minimal runtime ModelingPlan fixture."""

    analysis = root / "analysis"
    analysis.mkdir(parents=True)
    (analysis / "modeling_plan.json").write_text(
        json.dumps(
            {
                "schema_version": "0.4.0",
                "job_id": "surface_uv_test",
                "surface_details": surface_details,
            }
        ),
        encoding="utf-8",
    )


def _detail(
    detail_id: str,
    strategy: str,
    *,
    parent_id: str = "asset.body",
    representation: str = "texture_channels",
) -> dict:
    """Create one compact non-omitted surface-detail runtime fixture."""

    return {
        "id": detail_id,
        "parent_object_id": parent_id,
        "representation": representation,
        "uv_strategy": strategy if representation != "omit" else None,
    }


def test_missing_modeling_plan_needs_no_surface_detail_uv(tmp_path: Path) -> None:
    """Keep legacy or object-only jobs unchanged when no ModelingPlan exists."""

    runtime = _load_runtime()

    assert runtime.load_surface_detail_uv_requirements(tmp_path) == {}


def test_material_atlas_and_projected_patch_allow_deterministic_generation(
    tmp_path: Path,
) -> None:
    """Merge textured details per parent and permit one shared deterministic UVMap."""

    runtime = _load_runtime()
    _write_plan(
        tmp_path,
        [
            _detail("detail.weave", "material_atlas"),
            _detail("detail.label", "projected_patch"),
            _detail("detail.omitted", "existing_uv", representation="omit"),
        ],
    )

    requirements = runtime.load_surface_detail_uv_requirements(tmp_path)

    assert requirements == {
        "asset.body": {
            "mode": "uv",
            "uv_set": "UVMap",
            "generate_if_missing": True,
            "detail_ids": ["detail.label", "detail.weave"],
            "strategies": ["material_atlas", "projected_patch"],
        }
    }


def test_existing_uv_strategy_never_authorizes_generation(tmp_path: Path) -> None:
    """Keep existing_uv fail-closed when the approved mesh supplies no UV layer."""

    runtime = _load_runtime()
    _write_plan(tmp_path, [_detail("detail.existing", "existing_uv")])

    requirement = runtime.load_surface_detail_uv_requirements(tmp_path)["asset.body"]

    assert requirement["generate_if_missing"] is False
    assert requirement["uv_set"] == "UVMap"


def test_duplicate_surface_detail_ids_fail_inside_blender_runtime(
    tmp_path: Path,
) -> None:
    """Reject malformed duplicate IDs even when a host preflight was bypassed."""

    runtime = _load_runtime()
    _write_plan(
        tmp_path,
        [
            _detail("detail.duplicate", "material_atlas"),
            _detail("detail.duplicate", "material_atlas", parent_id="asset.other"),
        ],
    )

    with pytest.raises(RuntimeError, match="duplicated"):
        runtime.load_surface_detail_uv_requirements(tmp_path)


def test_build_scene_consumes_modeling_plan_uv_requirements() -> None:
    """Keep the canonical builder wired to ModelingPlan-driven UV preparation."""

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "build_scene.py"
    ).read_text(encoding="utf-8")

    assert "load_surface_detail_uv_requirements" in source
    assert "generate_if_missing" in source
    assert '"cbm_surface_detail_uv_ids"' in source
