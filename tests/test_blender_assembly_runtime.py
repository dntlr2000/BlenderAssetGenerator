from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.config import get_settings


def _load_runtime(monkeypatch: pytest.MonkeyPatch):
    """Import the Blender-only assembly helper with minimal host-side module stubs."""

    bpy = types.ModuleType("bpy")
    mathutils = types.ModuleType("mathutils")
    mathutils.Matrix = tuple
    mathutils.Vector = tuple
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils)
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "assembly_runtime.py"
    )
    spec = importlib.util.spec_from_file_location("_test_assembly_runtime", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bounds_relation_detects_geometry_baked_lateral_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Center-plane checks must inspect geometry bounds rather than object location."""

    runtime = _load_runtime(monkeypatch)
    relation = {
        "kind": "center_plane",
        "axis": "Y",
        "tolerance": {"mode": "relative", "value": 0.05},
    }
    reference = {"min": [-5.0, -1.0, -1.0], "max": [5.0, 1.0, 1.0]}
    centered = {"min": [-0.5, -0.1, -0.8], "max": [0.5, 0.1, -0.2]}
    baked_offset = {"min": [-0.5, -0.9, -0.8], "max": [0.5, -0.7, -0.2]}

    centered_residual, centered_tolerance, _, centered_metrics = (
        runtime._evaluate_bounds_relation(relation, centered, reference, None)
    )
    offset_residual, offset_tolerance, _, offset_metrics = (
        runtime._evaluate_bounds_relation(relation, baked_offset, reference, None)
    )

    assert centered_residual == pytest.approx(0.0)
    assert centered_residual <= centered_tolerance
    assert offset_residual == pytest.approx(0.4)
    assert offset_residual > offset_tolerance
    assert centered_metrics["bbox_basis"] == offset_metrics["bbox_basis"]
    assert centered_metrics["bbox_basis"].endswith("assembly_frame_meters")
    assert "location" not in centered_metrics


def test_runtime_contact_and_bilateral_checks_match_host_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject no-overlap contact and bilateral pairs that drift on transverse axes."""

    runtime = _load_runtime(monkeypatch)
    reference = {"min": [-5.0, -1.0, -1.0], "max": [5.0, 1.0, 1.0]}
    no_overlap_subject = {"min": [6.0, -0.2, 1.0], "max": [7.0, 0.2, 1.4]}
    contact = {
        "kind": "surface_contact",
        "axis": "Z",
        "subject_side": "MIN",
        "reference_side": "MAX",
        "min_transverse_overlap_ratio": 0.05,
        "tolerance": {"mode": "meters", "value": 0.01},
    }
    contact_residual, contact_tolerance, _, contact_metrics = (
        runtime._evaluate_bounds_relation(
            contact,
            no_overlap_subject,
            reference,
            None,
        )
    )
    assert contact_residual <= contact_tolerance
    assert contact_metrics["transverse_overlap_ok"] is False

    subject = {"min": [-1.0, -0.8, 0.0], "max": [0.0, -0.6, 0.4]}
    peer = {"min": [1.0, 0.6, 0.0], "max": [2.0, 0.8, 0.4]}
    bilateral = {
        "kind": "bilateral_pair",
        "axis": "Y",
        "tolerance": {"mode": "relative", "value": 0.05},
    }
    bilateral_residual, bilateral_tolerance, _, _ = (
        runtime._evaluate_bounds_relation(bilateral, subject, reference, peer)
    )
    assert bilateral_residual == pytest.approx(0.2)
    assert bilateral_residual > bilateral_tolerance


def test_runtime_axis_alignment_and_clearance_match_host_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Score evaluated object bases and directional broad-phase gaps deterministically."""

    runtime = _load_runtime(monkeypatch)
    subject = {"min": [-2.0, -0.1, -0.8], "max": [-1.5, 0.1, -0.2]}
    reference = {"min": [-1.0, -0.2, -0.9], "max": [1.0, 0.2, 0.1]}
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    rotated = [[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    alignment = {
        "kind": "axis_alignment",
        "subject_axis": "+X",
        "target_direction": [1.0, 0.0, 0.0],
        "target_space": "assembly_frame",
        "directionality": "directed",
        "angular_tolerance_deg": 5.0,
        "tolerance": {"mode": "relative", "value": 0.05},
    }
    passed, allowed, mode, metrics = runtime._evaluate_bounds_relation(
        alignment,
        subject,
        reference,
        None,
        subject_basis=identity,
        reference_basis=identity,
    )
    failed, _, _, failed_metrics = runtime._evaluate_bounds_relation(
        alignment,
        subject,
        reference,
        None,
        subject_basis=rotated,
        reference_basis=identity,
    )
    assert passed == pytest.approx(0.0)
    assert passed <= allowed
    assert mode == "degrees"
    assert metrics["evaluation_basis"] == "evaluated_object_axes_in_assembly_frame"
    assert failed == pytest.approx(90.0)
    assert failed_metrics["angular_error_deg"] == pytest.approx(90.0)

    clearance = {
        "kind": "axis_clearance",
        "axis": "X",
        "direction": "POSITIVE",
        "minimum_gap": {"mode": "meters", "value": 0.25},
        "maximum_gap": {"mode": "meters", "value": 0.75},
        "min_transverse_overlap_ratio": 0.05,
        "tolerance": {"mode": "meters", "value": 0.01},
    }
    residual, tolerance, mode, metrics = runtime._evaluate_bounds_relation(
        clearance,
        subject,
        reference,
        None,
    )
    assert residual == pytest.approx(0.0)
    assert residual <= tolerance
    assert mode == "meters"
    assert metrics["evaluated_gap"] == pytest.approx(0.5)
    assert metrics["transverse_overlap_ok"] is True


def test_blender_scripts_embed_and_report_assembly_provenance() -> None:
    """Build, inspect, and validation scripts must expose one coherent assembly contract."""

    root = Path(__file__).resolve().parents[1]
    scripts = root / "src" / "codex_blender_modeler" / "blender_scripts"
    build = (scripts / "build_scene.py").read_text(encoding="utf-8")
    inspect = (scripts / "inspect_scene.py").read_text(encoding="utf-8")
    validate = (scripts / "validate_scene.py").read_text(encoding="utf-8")
    runtime = (scripts / "assembly_runtime.py").read_text(encoding="utf-8")

    assert "attach_assembly_metadata" in build
    assert '"cbm_assembly_modeling_plan_sha256"' in runtime
    assert '"matrix_local"' in inspect
    assert '"matrix_world"' in inspect
    assert '"bbox_world"' in inspect
    assert '"basis_assembly_frame"' in inspect
    assert '"assembly": assembly' in validate
    assert "world_to_frame @ point" in runtime
    assert "transform.location" in runtime
    assert "triangle/BVH" in runtime


def test_runtime_keeps_legacy_contract_nonblocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing ModelingPlan remains readable as legacy_unbound without new checks."""

    runtime = _load_runtime(monkeypatch)
    contract = runtime.load_assembly_contract(tmp_path)

    assert contract["policy"] == "legacy_unbound"
    assert contract["sha256"] is None
    assert contract["relationships"] == []


def test_assembly_frame_requires_one_unique_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing or generated-multiple frame roots must fail before relation scoring."""

    runtime = _load_runtime(monkeypatch)

    class FakeObject(dict):
        """Provide the minimal instance metadata used before root matrix evaluation."""

        def __init__(self, name: str) -> None:
            super().__init__(cbm_instance_index=0)
            self.name = name

    frame = {"root_object_id": "asset.root"}
    missing_matrix, missing_error = runtime.resolve_assembly_world_to_frame(
        frame,
        {},
        None,
    )
    multiple_matrix, multiple_error = runtime.resolve_assembly_world_to_frame(
        frame,
        {"asset.root": [FakeObject("root_a"), FakeObject("root_b")]},
        None,
    )

    assert missing_matrix is None
    assert "count=0" in missing_error
    assert multiple_matrix is None
    assert "count=2" in multiple_error


def test_runtime_instance_policies_reject_ambiguous_reference_families(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Family and broadcast policies require one concrete reference in the root frame."""

    runtime = _load_runtime(monkeypatch)

    class FakeObject(dict):
        """Expose deterministic generated-instance metadata for operand resolution."""

        def __init__(self, name: str, index: int) -> None:
            super().__init__(cbm_instance_index=index)
            self.name = name

    object_map = {
        "subject": [FakeObject("subject", 0)],
        "reference": [FakeObject("reference_a", 0), FakeObject("reference_b", 1)],
    }
    family_operands, family_error = runtime._relationship_operands(
        {
            "subject_id": "subject",
            "reference_id": "reference",
            "instance_policy": "family_bounds",
        },
        object_map,
    )
    broadcast_operands, broadcast_error = runtime._relationship_operands(
        {
            "subject_id": "subject",
            "reference_id": "reference",
            "instance_policy": "broadcast_reference",
        },
        object_map,
    )

    assert family_operands == []
    assert "exactly one" in family_error
    assert broadcast_operands == []
    assert "exactly one" in broadcast_error


def _smoke_scene(job_id: str, lateral_center: float) -> dict:
    """Create one minimal raw SceneSpec with a geometry-baked attached-part offset."""

    y_min = lateral_center - 0.1
    y_max = lateral_center + 0.1
    vertices = [
        [x, y, z]
        for z in (-0.8, -0.2)
        for y in (y_min, y_max)
        for x in (-0.5, 0.5)
    ]
    return {
        "schema_version": "0.2.0",
        "job_id": job_id,
        "mode": "concept",
        "nominal_scene_size": [10.0, 2.0, 2.0],
        "sources": [
            {"id": "reference", "path": "input/reference.png", "kind": "reference"}
        ],
        "materials": [
            {
                "id": "mat.test",
                "name": "Test",
                "base_color": [0.4, 0.4, 0.4, 1.0],
                "roughness": 0.5,
                "metallic": 0.0,
            }
        ],
        "objects": [
            {
                "id": "asset.root",
                "name": "Root",
                "geometry": {
                    "kind": "primitive",
                    "primitive": "cube",
                    "dimensions": [10.0, 2.0, 2.0],
                },
                "material_id": "mat.test",
            },
            {
                "id": "asset.attached",
                "name": "Attached",
                "geometry": {
                    "kind": "custom_mesh",
                    "vertices": vertices,
                    "faces": [
                        [0, 1, 3, 2],
                        [4, 6, 7, 5],
                        [0, 4, 5, 1],
                        [2, 3, 7, 6],
                        [0, 2, 6, 4],
                        [1, 5, 7, 3],
                    ],
                    "recalculate_normals": True,
                },
                "material_id": "mat.test",
                "transform": {
                    "location": [0.0, 0.0, 0.0],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                },
            },
        ],
        "camera": {
            "projection": "PERSP",
            "location": [8.0, -12.0, 7.0],
            "target": [0.0, 0.0, 0.0],
            "focal_length_mm": 50.0,
            "ortho_scale": 12.0,
            "resolution": [320, 240],
        },
        "assumptions": [],
        "revision_notes": [],
    }


def _smoke_plan(job_id: str) -> dict:
    """Create one minimal spatial assembly plan for Blender runtime smoke tests."""

    return {
        "schema_version": "0.4.0",
        "job_id": job_id,
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
        "stage": "authored",
        "objects": [
            {
                "id": "asset.root",
                "label": "Root",
                "assembly_role": "root",
                "source_ids": ["reference"],
            },
            {
                "id": "asset.attached",
                "label": "Attached",
                "assembly_role": "attached",
                "source_ids": ["reference"],
            },
        ],
        "assembly_consistency_policy": "spatial_v1",
        "assembly_frame": {
            "root_object_id": "asset.root",
            "longitudinal_axis": "X",
            "lateral_axis": "Y",
            "vertical_axis": "Z",
            "symmetry": "bilateral",
            "evidence_status": "inferred",
            "source_ids": [],
            "confidence": 0.5,
            "notes": [],
        },
        "assembly_relationships": [
            {
                "id": "center.attached",
                "kind": "center_plane",
                "subject_id": "asset.attached",
                "reference_id": "asset.root",
                "axis": "Y",
                "evidence_status": "inferred",
                "source_ids": [],
                "confidence": 0.5,
                "required": True,
                "tolerance": {"mode": "relative", "value": 0.05},
                "instance_policy": "family_bounds",
                "notes": [],
            }
        ],
        "surface_details": [],
        "global_notes": [],
    }


def _meter_frame_smoke_scene(job_id: str) -> dict:
    """Create rotated parts whose common assembly-axis centers are intentionally aligned."""

    angle = 30.0
    cosine = 0.8660254037844386
    sine = 0.5

    def world_xy(x_value: float, y_value: float) -> list[float]:
        """Rotate one assembly-frame XY position into the authored world frame."""

        return [
            x_value * cosine - y_value * sine,
            x_value * sine + y_value * cosine,
            0.0,
        ]

    scene = _smoke_scene(job_id, 0.0)
    scene["objects"] = [
        {
            "id": "asset.root",
            "name": "Root",
            "geometry": {
                "kind": "primitive",
                "primitive": "cube",
                "dimensions": [10.0, 2.0, 2.0],
            },
            "material_id": "mat.test",
            "transform": {
                "location": [0.0, 0.0, 0.0],
                "rotation_deg": [0.0, 0.0, angle],
                "scale": [1.0, 1.0, 1.0],
            },
        },
        {
            "id": "asset.meter_subject",
            "name": "Meter Subject",
            "geometry": {
                "kind": "primitive",
                "primitive": "cube",
                "dimensions": [0.4, 0.1, 0.4],
            },
            "material_id": "mat.test",
            "transform": {
                "location": world_xy(0.0, 0.04),
                "rotation_deg": [0.0, 0.0, 75.0],
                "scale": [1.0, 1.0, 1.0],
            },
        },
        {
            "id": "asset.rotated_reference",
            "name": "Rotated Reference",
            "geometry": {
                "kind": "primitive",
                "primitive": "cube",
                "dimensions": [2.0, 0.4, 0.4],
            },
            "material_id": "mat.test",
            "transform": {
                "location": world_xy(2.0, 0.2),
                "rotation_deg": [0.0, 0.0, -20.0],
                "scale": [1.0, 1.0, 1.0],
            },
        },
        {
            "id": "asset.rotated_subject",
            "name": "Rotated Subject",
            "geometry": {
                "kind": "primitive",
                "primitive": "cube",
                "dimensions": [1.0, 0.3, 0.3],
            },
            "material_id": "mat.test",
            "transform": {
                "location": world_xy(3.0, 0.2),
                "rotation_deg": [0.0, 0.0, 55.0],
                "scale": [1.0, 1.0, 1.0],
            },
        },
    ]
    return scene


def _meter_frame_smoke_plan(job_id: str) -> dict:
    """Create meter-tolerance and rotated-reference relationships in one root frame."""

    plan = _smoke_plan(job_id)
    plan["objects"] = [
        {
            "id": object_id,
            "label": object_id,
            "assembly_role": "root" if object_id == "asset.root" else "attached",
            "source_ids": ["reference"],
            "required_assembly_checks": (
                ["axis"]
                if object_id in {"asset.meter_subject", "asset.rotated_subject"}
                else []
            ),
        }
        for object_id in (
            "asset.root",
            "asset.meter_subject",
            "asset.rotated_reference",
            "asset.rotated_subject",
        )
    ]
    plan["assembly_relationships"] = [
        {
            "id": "center.meter_subject",
            "kind": "center_plane",
            "subject_id": "asset.meter_subject",
            "reference_id": "asset.root",
            "axis": "Y",
            "evidence_status": "inferred",
            "source_ids": [],
            "confidence": 0.5,
            "required": True,
            "tolerance": {"mode": "meters", "value": 0.05},
            "instance_policy": "family_bounds",
            "notes": [],
        },
        {
            "id": "center.rotated_pair",
            "kind": "center_plane",
            "subject_id": "asset.rotated_subject",
            "reference_id": "asset.rotated_reference",
            "axis": "Y",
            "evidence_status": "inferred",
            "source_ids": [],
            "confidence": 0.5,
            "required": True,
            "tolerance": {"mode": "meters", "value": 0.05},
            "instance_policy": "family_bounds",
            "notes": [],
        },
        {
            "id": "axis.meter_subject",
            "kind": "axis_alignment",
            "subject_id": "asset.meter_subject",
            "reference_id": "asset.root",
            "subject_axis": "+X",
            "target_direction": [0.7071067811865476, 0.7071067811865476, 0.0],
            "target_space": "assembly_frame",
            "directionality": "directed",
            "angular_tolerance_deg": 0.01,
            "evidence_status": "inferred",
            "source_ids": [],
            "confidence": 0.5,
            "required": True,
            "tolerance": {"mode": "relative", "value": 0.05},
            "instance_policy": "family_bounds",
            "notes": [],
        },
        {
            "id": "axis.rotated_pair",
            "kind": "axis_alignment",
            "subject_id": "asset.rotated_subject",
            "reference_id": "asset.rotated_reference",
            "subject_axis": "+X",
            "target_direction": [0.25881904510252074, 0.9659258262890683, 0.0],
            "target_space": "reference_local",
            "directionality": "directed",
            "angular_tolerance_deg": 0.01,
            "evidence_status": "inferred",
            "source_ids": [],
            "confidence": 0.5,
            "required": True,
            "tolerance": {"mode": "relative", "value": 0.05},
            "instance_policy": "family_bounds",
            "notes": [],
        },
    ]
    return plan


def _apply_nonuniform_root_scale(blend_path: Path) -> None:
    """Apply one test-only unapplied root scale inside an isolated Blender file."""

    settings = get_settings()
    expression = (
        "import bpy; "
        "root=bpy.data.objects['asset.root']; "
        "root.scale=(2.0,0.5,1.5); "
        "bpy.context.view_layer.update(); "
        f"bpy.ops.wm.save_as_mainfile(filepath={str(blend_path)!r})"
    )
    result = subprocess.run(
        [
            settings.blender_bin,
            "--background",
            "--python-exit-code",
            "1",
            str(blend_path),
            "--python-expr",
            expression,
        ],
        cwd=settings.repo_root,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=settings.blender_timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Blender test-only root-scale mutation failed\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


@pytest.mark.skipif(
    os.getenv("CBM_RUN_BLENDER_ASSEMBLY_SMOKE") != "1",
    reason="Set CBM_RUN_BLENDER_ASSEMBLY_SMOKE=1 for Blender 5 runtime evidence.",
)
@pytest.mark.parametrize(
    ("lateral_center", "expected_ok", "expected_status"),
    [(0.0, True, "passed"), (-0.8, False, "failed")],
)
def test_blender_runtime_assembly_smoke(
    tmp_path: Path,
    lateral_center: float,
    expected_ok: bool,
    expected_status: str,
) -> None:
    """Build and validate isolated centered and geometry-baked-offset Blender scenes."""

    job_id = "assembly_runtime_smoke"
    job_root = tmp_path / ("centered" if expected_ok else "offset")
    analysis = job_root / "analysis"
    blender = job_root / "blender"
    reports = job_root / "reports"
    analysis.mkdir(parents=True)
    blender.mkdir()
    reports.mkdir()
    spec_path = analysis / "scene_spec.json"
    plan_path = analysis / "modeling_plan.json"
    blend_path = blender / "scene.blend"
    inventory_path = reports / "scene_inventory.json"
    report_path = reports / "validation.json"
    spec_path.write_text(
        json.dumps(_smoke_scene(job_id, lateral_center), indent=2),
        encoding="utf-8",
    )
    plan_path.write_text(
        json.dumps(_smoke_plan(job_id), indent=2),
        encoding="utf-8",
    )

    run_blender(
        "build_scene.py",
        [
            "--spec",
            str(spec_path),
            "--job-root",
            str(job_root),
            "--output",
            str(blend_path),
        ],
        factory_startup=True,
    )
    run_blender(
        "inspect_scene.py",
        ["--output", str(inventory_path)],
        blend_file=blend_path,
    )
    run_blender(
        "validate_scene.py",
        ["--spec", str(spec_path), "--output", str(report_path)],
        blend_file=blend_path,
    )

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    attached = next(
        item for item in inventory["objects"] if item.get("cbm_id") == "asset.attached"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    check = next(
        item
        for item in report["assembly"]["checks"]
        if item.get("relation_id") == "center.attached"
    )
    assert report["ok"] is expected_ok
    assert inventory["assembly"]["policy"] == "spatial_v1"
    assert len(attached["matrix_local"]) == 4
    assert len(attached["matrix_world"]) == 4
    assert attached["assembly_relationship_ids"] == ["center.attached"]
    assert report["assembly"]["status"] == expected_status
    assert check["status"] == expected_status
    assert check["metrics"]["bbox_basis"] == (
        "evaluated_bbox_corners_in_assembly_frame_meters"
    )
    if expected_ok:
        stale_report_path = reports / "validation_stale.json"
        plan_path.unlink()
        run_blender(
            "validate_scene.py",
            ["--spec", str(spec_path), "--output", str(stale_report_path)],
            blend_file=blend_path,
        )
        stale = json.loads(stale_report_path.read_text(encoding="utf-8"))
        assert stale["ok"] is False
        assert stale["assembly"]["status"] == "stale"


@pytest.mark.skipif(
    os.getenv("CBM_RUN_BLENDER_ASSEMBLY_SMOKE") != "1",
    reason="Set CBM_RUN_BLENDER_ASSEMBLY_SMOKE=1 for Blender 5 runtime evidence.",
)
def test_blender_runtime_uses_orthonormal_root_meter_frame(tmp_path: Path) -> None:
    """Ignore root scale in frame axes while retaining true meter-space geometry bounds."""

    job_id = "assembly_meter_frame_smoke"
    job_root = tmp_path / "meter_frame"
    analysis = job_root / "analysis"
    blender = job_root / "blender"
    reports = job_root / "reports"
    analysis.mkdir(parents=True)
    blender.mkdir()
    reports.mkdir()
    spec_path = analysis / "scene_spec.json"
    blend_path = blender / "scene.blend"
    inventory_path = reports / "scene_inventory.json"
    report_path = reports / "validation.json"
    spec_path.write_text(
        json.dumps(_meter_frame_smoke_scene(job_id), indent=2),
        encoding="utf-8",
    )
    (analysis / "modeling_plan.json").write_text(
        json.dumps(_meter_frame_smoke_plan(job_id), indent=2),
        encoding="utf-8",
    )

    run_blender(
        "build_scene.py",
        [
            "--spec",
            str(spec_path),
            "--job-root",
            str(job_root),
            "--output",
            str(blend_path),
        ],
        factory_startup=True,
    )
    _apply_nonuniform_root_scale(blend_path)
    run_blender(
        "inspect_scene.py",
        ["--output", str(inventory_path)],
        blend_file=blend_path,
    )
    run_blender(
        "validate_scene.py",
        ["--spec", str(spec_path), "--output", str(report_path)],
        blend_file=blend_path,
    )

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    relation_checks = {
        item["relation_id"]: item
        for item in report["assembly"]["checks"]
        if item.get("relation_id")
    }
    meter_subject = next(
        item
        for item in inventory["objects"]
        if item.get("cbm_id") == "asset.meter_subject"
    )

    assert report["ok"] is True
    assert report["assembly"]["status"] == "passed"
    assert relation_checks["center.meter_subject"]["residual"] == pytest.approx(
        0.04,
        abs=1.0e-6,
    )
    assert relation_checks["center.rotated_pair"]["residual"] == pytest.approx(
        0.0,
        abs=1.0e-6,
    )
    assert relation_checks["axis.meter_subject"]["residual"] == pytest.approx(
        0.0,
        abs=5.0e-5,
    )
    assert relation_checks["axis.rotated_pair"]["residual"] == pytest.approx(
        0.0,
        abs=5.0e-5,
    )
    assert meter_subject["bbox_assembly_frame"] is not None
    assert meter_subject["basis_assembly_frame"] is not None
    center_y = sum(
        meter_subject["bbox_assembly_frame"][boundary][1]
        for boundary in ("min", "max")
    ) * 0.5
    assert center_y == pytest.approx(0.04, abs=1.0e-6)
