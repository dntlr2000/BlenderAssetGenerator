"""Shared atlas exception is narrow, current-geometry-bound and independently native checked."""

from __future__ import annotations

import ast
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from test_surface_detail_policy import _seed_surface_detail_job, _write_authored_materials

from codex_blender_modeler.analysis.surface_details import validate_job_surface_details
from codex_blender_modeler.materials.fidelity import evaluate_material_fidelity
from codex_blender_modeler.surface_detail_atlas import (
    declared_atlas_uv_metrics,
    shared_atlas_errors,
)


def _save(path: Path, payload: object) -> None:
    """Write one fixture artifact deterministically."""

    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict, dict]:
    """Declare two real UV footprints in separate cells of one existing shared material."""

    root = _seed_surface_detail_job(tmp_path, monkeypatch)
    _write_authored_materials(root, claim_detail=True, binding_policy="spatial_v1",
                              spatial_binding=True)
    Image.new("RGB", (64, 64), (180, 190, 170)).save(root / "textures/mat.box/base_color.png")
    Image.new("RGB", (64, 64), (128, 128, 255)).save(root / "textures/mat.box/normal.png")
    scene_path = root / "analysis/scene_spec.json"
    scene = json.loads(scene_path.read_text())
    scene["objects"].append(deepcopy(scene["objects"][0]))
    scene["objects"][1]["id"] = "asset.second"
    plan_path = root / "analysis/modeling_plan.json"
    plan = json.loads(plan_path.read_text())
    plan["objects"].append(deepcopy(plan["objects"][0]))
    plan["objects"][1]["id"] = "asset.second"
    plan["surface_details"].append(deepcopy(plan["surface_details"][0]))
    plan["surface_details"][1]["id"] = "detail.second"
    plan["surface_details"][1]["parent_object_id"] = "asset.second"
    manifest_path = root / "textures/mat.box/texture_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["surface_detail_ids"].append("detail.second")
    manifest["surface_detail_bindings"].append(deepcopy(manifest["surface_detail_bindings"][0]))
    manifest["surface_detail_bindings"][1].update(
        detail_id="detail.second", parent_object_id="asset.second",
    )
    (root / "geometry").mkdir()
    inventory = {"objects": []}
    for index, item in enumerate(scene["objects"]):
        offset = 0.5 * index
        payload = {"vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                   "faces": [[0, 1, 2]],
                   "vertex_uvs": [[offset + 0.1, 0.1], [offset + 0.4, 0.1],
                                  [offset + 0.1, 0.9]]}
        mesh_path = f"geometry/{index}.json"
        _save(root / mesh_path, payload)
        item["geometry"] = {"kind": "custom_mesh", "path": mesh_path}
        metrics = declared_atlas_uv_metrics(root, item["geometry"], material_id="mat.box")
        binding = manifest["surface_detail_bindings"][index]
        binding["placement"]["uv_rect"] = [offset, 0, offset + 0.5, 1]
        binding["uv_layout_sha256"] = metrics["vertex_uv_binding_fingerprint"]
        inventory["objects"].append({"cbm_id": item["id"], "uv_layers": [metrics]})
    _save(scene_path, scene)
    _save(plan_path, plan)
    _save(manifest_path, manifest)
    _save(root / "reports/scene_inventory.json", inventory)
    return root, scene, manifest


def _report() -> Any:
    """Exercise the ordinary public host validation route without writing reports."""

    return validate_job_surface_details("surface_detail_asset", require_materials=True,
                                        write_report=False)


def test_explicit_shared_atlas_validates_all_current_uv_footprints(tmp_path, monkeypatch):
    """Existing material identities may share an atlas only with complete measured ownership."""

    _seed(tmp_path, monkeypatch)
    report = _report()
    assert report.ok, [item.message for item in report.checks if item.status == "failed"]
    assert report.textured == 2


@pytest.mark.parametrize("failure", [
    "overlap", "missing_user", "stale_inventory", "wrong_strategy", "out_of_cell",
    "missing_payload", "nonfinite_uv", "unknown_dialect", "no_padding", "mixed_material",
    "wrong_corner_order", "missing_occupancy", "outside_tile", "actual_image_size",
])
def test_shared_atlas_host_rejects_ambiguous_or_stale_proof(tmp_path, monkeypatch, failure):
    """Declared rectangles alone cannot override actual source UVs, identity or coverage."""

    root, scene, manifest = _seed(tmp_path, monkeypatch)
    manifest_path = root / "textures/mat.box/texture_manifest.json"
    if failure == "overlap":
        manifest["surface_detail_bindings"][0]["placement"]["uv_rect"][2] = 0.7
    elif failure == "missing_user":
        manifest["surface_detail_bindings"].pop()
        manifest["surface_detail_ids"].pop()
    elif failure == "wrong_strategy":
        path = root / "analysis/modeling_plan.json"
        plan = json.loads(path.read_text())
        plan["surface_details"][0]["uv_strategy"] = "existing_uv"
        _save(path, plan)
    elif failure in {"stale_inventory", "missing_occupancy"}:
        path = root / "reports/scene_inventory.json"
        inventory = json.loads(path.read_text())
        if failure == "stale_inventory":
            inventory["objects"][0]["uv_layers"][0]["vertex_uv_binding_fingerprint"] = "f" * 64
        else:
            inventory["objects"].pop()
        _save(path, inventory)
    elif failure == "missing_payload":
        scene["objects"][0]["geometry"]["path"] = "geometry/absent.json"
        _save(root / "analysis/scene_spec.json", scene)
    elif failure == "mixed_material":
        manifest["surface_detail_bindings"][0]["material_id"] = "mat.other"
    elif failure == "actual_image_size":
        Image.new("RGB", (32, 32), (128, 128, 255)).save(root / "textures/mat.box/normal.png")
    else:
        path = root / "geometry/0.json"
        payload = json.loads(path.read_text())
        if failure == "out_of_cell":
            payload["vertex_uvs"][0] = [0.85, 0.4]
        elif failure == "outside_tile":
            payload["vertex_uvs"][0] = [-0.5, 0.4]
        elif failure == "nonfinite_uv":
            payload["vertex_uvs"][0][0] = float("nan")
        elif failure == "unknown_dialect":
            payload["schema_version"] = "99.0.0"
        elif failure == "no_padding":
            payload["vertex_uvs"][0] = [0.499, 0.4]
        elif failure == "wrong_corner_order":
            payload["faces"][0] = [1, 0, 2]
        _save(path, payload)
        # Even a re-sealed source hash cannot prove a footprint outside its cell.
        if failure in {"out_of_cell", "outside_tile", "no_padding"}:
            metrics = declared_atlas_uv_metrics(root, scene["objects"][0]["geometry"],
                                                material_id="mat.box")
            manifest["surface_detail_bindings"][0]["uv_layout_sha256"] = metrics[
                "vertex_uv_binding_fingerprint"
            ]
    _save(manifest_path, manifest)
    report = _report()
    assert not report.ok
    assert any(item.status == "failed" for item in report.checks)


def _native_checker():
    """Load the pure runtime checker body without importing bpy into ordinary CI."""

    path = Path(__file__).resolve().parents[1] / (
        "src/codex_blender_modeler/blender_scripts/inspect_materials.py"
    )
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_spatial_binding_checks")
    namespace = {"Any": Any, "defaultdict": defaultdict, "shared_atlas_errors": shared_atlas_errors}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[function.name]


@pytest.mark.parametrize("failure", [None, "evaluated_escape", "evaluated_missing",
                                     "source_stale", "unbound_user", "no_strategy", "graph_failed",
                                     "no_uv_consumer", "ambiguous_material", "missing_instance_uv",
                                     "image_size_mismatch", "rounded_padding_boundary"])
def test_runtime_atlas_checks_actual_evaluated_uvs(tmp_path, monkeypatch, failure):
    """Native runtime refuses modifier/evaluation UV escape even when source rectangles pass."""

    root, _scene, manifest = _seed(tmp_path, monkeypatch)
    inventory = json.loads((root / "reports/scene_inventory.json").read_text())
    bindings = deepcopy(manifest["surface_detail_bindings"])
    for binding in bindings:
        binding["atlas_resolution"] = [64, 64]
    materials = [{"material_id": "mat.box", "spatial_bindings": bindings,
                  "spatial_graph_evidence": {"status": "passed"},
                  "atlas_image_sizes_valid": True}]
    objects = [{"object_id": entry["cbm_id"], "source_uv_layers": deepcopy(entry["uv_layers"]),
                "evaluated_uv_layer_metrics": deepcopy(entry["uv_layers"]),
                "material_stats": [{"material_id": "mat.box"}]} for entry in inventory["objects"]]
    strategies = {binding["detail_id"]: "material_atlas" for binding in bindings}
    if failure == "evaluated_escape":
        objects[0]["evaluated_uv_layer_metrics"][0]["coordinate_bounds"]["max"][0] = 0.8
    elif failure == "evaluated_missing":
        objects[0]["evaluated_uv_layer_metrics"] = []
    elif failure == "source_stale":
        objects[0]["source_uv_layers"][0]["vertex_uv_binding_fingerprint"] = "f" * 64
    elif failure == "unbound_user":
        extra = deepcopy(objects[0])
        extra["object_id"] = "asset.undeclared"
        objects.append(extra)
    elif failure == "no_strategy":
        strategies = {}
    elif failure == "graph_failed":
        materials[0]["spatial_graph_evidence"]["status"] = "failed"
    elif failure == "no_uv_consumer":
        objects.append({"object_id": "asset.no_uv", "material_stats": [],
                        "assigned_material_ids": ["mat.box"], "source_uv_layers": []})
    elif failure == "ambiguous_material":
        materials.append(deepcopy(materials[0]))
    elif failure == "missing_instance_uv":
        extra = deepcopy(objects[0])
        extra["source_uv_layers"] = []
        objects.append(extra)
    elif failure == "image_size_mismatch":
        materials[0]["atlas_image_sizes_valid"] = False
    elif failure == "rounded_padding_boundary":
        objects[0]["evaluated_uv_layer_metrics"][0]["coordinate_bounds"]["min"][0] = 2 / 64
    checks = _native_checker()(materials, objects, atlas_strategies=strategies)
    assert all(item["status"] == "passed" for item in checks) is (failure is None)


def test_source_atlas_path_rejects_symlink(tmp_path):
    """A mesh payload may not use a linked path to evade contained source proof."""

    (tmp_path / "actual.json").write_text("{}")
    (tmp_path / "alias.json").symlink_to(tmp_path / "actual.json")
    with pytest.raises(ValueError, match="links"):
        declared_atlas_uv_metrics(tmp_path, {"kind": "custom_mesh", "path": "alias.json"},
                                  material_id="mat.box")


def test_shared_atlas_fidelity_report_uses_same_current_source_proof(tmp_path, monkeypatch):
    """Reporting accepts valid ownership and retains the payload hashes it actually consumed."""

    root, _scene, _manifest = _seed(tmp_path, monkeypatch)
    texture = root / "textures/mat.box"
    Image.new("RGB", (64, 64), (180, 190, 170)).save(texture / "base_color.png")
    Image.new("RGB", (64, 64), (128, 128, 255)).save(texture / "normal.png")
    report = evaluate_material_fidelity(root)
    assert not any(item.code in {"surface_detail_binding_mismatch",
                                 "shared_detail_atlas_leakage_risk"}
                   for item in report.findings)
    assert "geometry/0.json" in report.input_hashes
    path = root / "geometry/0.json"
    payload = json.loads(path.read_text())
    payload["vertex_uvs"][0] = [0.8, 0.5]
    _save(path, payload)
    failed = evaluate_material_fidelity(root)
    assert any(item.code == "surface_detail_binding_mismatch" for item in failed.findings)


def test_v02_loop_uv_payload_uses_strict_json_contract(tmp_path):
    """V02 arrays must use the strict JSON loader and exact per-corner UV order."""

    from test_aq_v02_geometry import _payload_dict

    from codex_blender_modeler.structural_geometry.mesh_payload_v02 import (
        normalized_source_intent_sha256,
    )

    payload = _payload_dict(tmp_path)
    _save(tmp_path / "v02.json", payload)
    geometry = {"kind": "custom_mesh", "path": "v02.json"}
    with pytest.raises(ValueError, match="single material"):
        declared_atlas_uv_metrics(tmp_path, geometry, material_id="mat.body")
    payload["material_slots"] = [{"slot_index": 0, "material_id": "mat.body"}]
    payload["polygon_material_indices"] = [0] * len(payload["faces"])
    intent = payload["source_geometry_intent"]
    for assignment in intent["material_assignments"]:
        assignment["material_id"] = "mat.body"
    intent["source_intent_sha256"] = normalized_source_intent_sha256(
        {key: value for key, value in intent.items() if key != "source_intent_sha256"}
    )
    _save(tmp_path / "v02.json", payload)
    metrics = declared_atlas_uv_metrics(tmp_path, geometry, material_id="mat.body")
    assert metrics["coordinate_count"] == 24
    assert len(metrics["vertex_uv_binding_fingerprint"]) == 64


def test_standard_atlas_preserves_declared_uv_layer_identity(tmp_path):
    """A different declared Standard UV layer may never be normalized to UVMap."""

    from test_standard_custom_mesh import _fixture_payload

    payload, _scene = _fixture_payload(tmp_path)
    payload["uv_set"] = "OtherUV"
    _save(tmp_path / "standard.json", payload)
    with pytest.raises(ValueError, match="exact UVMap"):
        declared_atlas_uv_metrics(tmp_path, {"kind": "custom_mesh", "path": "standard.json"},
                                  material_id="mat.box")


def test_malformed_standard_atlas_is_normalized_failure(tmp_path):
    """Runtime-only Standard exceptions become ordinary failed atlas evidence."""

    _save(tmp_path / "standard.json", {"payload_kind": "standard_custom_mesh",
                                       "schema_version": "0.1.0"})
    with pytest.raises(ValueError, match="invalid Standard atlas payload"):
        declared_atlas_uv_metrics(tmp_path, {"kind": "custom_mesh", "path": "standard.json"},
                                  material_id="mat.box")
