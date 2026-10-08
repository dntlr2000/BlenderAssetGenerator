"""Weighted policy must survive host, native and public-surface recomputation."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_authored_uv_conversion import fixture
from test_uv_scalar_bake import SQUARE, evidence_fixture
from typer.testing import CliRunner

from codex_blender_modeler import cli, mcp_server
from codex_blender_modeler.blender_scripts.portable_authored_uv_proof import mapped_uvs
from codex_blender_modeler.blender_scripts.portable_material_conversion_runtime import (
    atlas_tile_bounds,
    resolve_atlas_tiles,
)
from codex_blender_modeler.optimization.models import PortableAtlasPolicy
from codex_blender_modeler.packaging.authored_uv import (
    ATLAS,
    AuthoredUVInspection,
    build_proof,
    canonical_hash,
)
from codex_blender_modeler.packaging.scalar_bake import validate_scalar_evidence


def _weighted(plan):
    """Select a valid weighted policy while preserving each fixture's exact source binding."""
    raw = plan.atlas_policy.model_dump(mode="json")
    raw["tile_strategy"] = "area_weighted_rect_v1"
    plan.atlas_policy = PortableAtlasPolicy.model_validate(raw)
    return plan.atlas_policy.model_dump(mode="json")


def test_host_proof_recomputes_weighted_bounds_and_rejects_old_grid():
    """A plausible nonoverlapping grid cannot replace the selected area-weighted mapping."""
    plan, source, target = fixture()
    policy = _weighted(plan)
    source.objects[0].matrix_world = (
        (3.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0),
    )
    raw = target.model_dump(mode="json")
    raw["objects"][0]["matrix_world"] = source.objects[0].matrix_world
    target = AuthoredUVInspection.model_validate(raw)
    with pytest.raises(ValueError, match="affine reconstruction"):
        build_proof(source, target, plan, "e" * 64, "a" * 64)
    tiles = resolve_atlas_tiles(
        policy, len(source.objects), [row.model_dump(mode="json") for row in source.objects]
    )
    for row, bounds in zip(raw["objects"], tiles, strict=True):
        row["uv_layers"][ATLAS] = mapped_uvs(row["uv_layers"]["Layout"], bounds)
    proof = build_proof(
        source, AuthoredUVInspection.model_validate(raw), plan, "e" * 64, "a" * 64
    )
    assert [row.target_bounds for row in proof.objects] == tiles
    assert all(row.orientation_preserved for row in proof.objects)
    source.objects[0].matrix_world = source.objects[1].matrix_world
    raw["objects"][0]["matrix_world"] = source.objects[0].matrix_world
    with pytest.raises(ValueError, match="affine reconstruction"):
        build_proof(source, AuthoredUVInspection.model_validate(raw), plan, "e" * 64, "a" * 64)


def test_scalar_evidence_recomputes_weighted_source_and_rejects_forged_bounds(tmp_path):
    """Freshly declared scalar rows must agree with the same exact source area allocation."""
    plan, source, outputs, evidence = evidence_fixture(tmp_path)
    policy = _weighted(plan)
    source.objects[0].vertices[1] = (3.0, 0.0, 0.0)
    source.objects[0].vertices[2] = (3.0, 1.0, 0.0)
    tiles = resolve_atlas_tiles(
        policy, len(source.objects), [row.model_dump(mode="json") for row in source.objects]
    )
    for row, original, bounds in zip(evidence.objects, source.objects, tiles, strict=True):
        row.source_snapshot_sha256 = canonical_hash(original.model_dump(mode="json"))
        row.target_bounds = bounds
        row.target_corners = mapped_uvs(SQUARE, bounds)
    assert validate_scalar_evidence(evidence, source, plan, "e" * 64, tmp_path, outputs)
    evidence.objects[0].target_bounds = atlas_tile_bounds(0, 2, 2048, 16)
    evidence.objects[0].target_corners = mapped_uvs(SQUARE, evidence.objects[0].target_bounds)
    with pytest.raises(ValueError, match="bounds changed"):
        validate_scalar_evidence(evidence, source, plan, "e" * 64, tmp_path, outputs)


def test_native_policy_requires_authored_source_binding():
    """Exercise the actual native policy checker without importing Blender into host CI."""
    path = Path(__file__).resolve().parents[1] / (
        "src/codex_blender_modeler/blender_scripts/convert_portable_materials.py"
    )
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_validate_atlas_policy")
    channels = ("base_color", "roughness", "metallic", "normal", "emission")
    namespace = {"Any": Any, "CHANNELS": channels, "ATLAS_UV_SET": ATLAS}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    checker = namespace[function.name]
    policy = PortableAtlasPolicy(
        uv_method="validated_authored_uv_v1", tile_strategy="area_weighted_rect_v1"
    ).model_dump(mode="json")
    plan = {"atlas_policy": policy, "authored_uv_source": {"sha256": "a" * 64}}
    assert checker(plan, 2048, 16) == policy
    plan.pop("authored_uv_source")
    with pytest.raises(ValueError, match="source inspection"):
        checker(plan, 2048, 16)
    policy["uv_method"] = "smart_project"
    with pytest.raises(ValueError, match="requires validated_authored_uv_v1"):
        checker(plan, 2048, 16)


def test_cli_and_mcp_forward_only_explicit_weighted_policy(monkeypatch):
    """Both public surfaces route the same opt-in and refuse unsupported combinations early."""
    calls = []

    def record(*args, **kwargs):
        """Capture the requested policy without touching a workspace or invoking Blender."""
        calls.append(kwargs)
        return SimpleNamespace(model_dump_json=lambda: "{}", model_dump=lambda **kw: {})

    monkeypatch.setattr(cli, "convert_portable_materials", record)
    monkeypatch.setattr(mcp_server, "convert_portable_materials_internal", record)
    arguments = ["asset-material-convert", "asset", "--run-id", "run", "--conversion-id", "conv",
                 "--tile-strategy", "area_weighted_rect_v1"]
    assert CliRunner().invoke(cli.app, arguments).exit_code != 0
    assert not calls
    assert CliRunner().invoke(
        cli.app, [*arguments, "--uv-method", "validated_authored_uv_v1"]
    ).exit_code == 0
    mcp_server.convert_portable_materials(
        "asset", "run", "conv", uv_method="validated_authored_uv_v1",
        tile_strategy="area_weighted_rect_v1",
    )
    assert all(call["tile_strategy"] == "area_weighted_rect_v1" for call in calls)
    with pytest.raises(ValueError, match="requires validated_authored_uv_v1"):
        mcp_server.convert_portable_materials(
            "asset", "run", "conv", tile_strategy="area_weighted_rect_v1"
        )
