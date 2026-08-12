"""Focused Blender 5 smoke tests for strict authoring companion inspection."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from PIL import Image

from codex_blender_modeler.analysis.models import ModelingPlan
from codex_blender_modeler.blender_artifacts import native_io_path
from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.blender_scripts.topology import (
    TopologyArtifact,
    TopologyObservation,
    TopologyProvenance,
    evaluate_topology_profile,
    get_topology_profile,
)
from codex_blender_modeler.integrated_quality.blender_companion_service import (
    inspect_static_prop_authoring_companions,
)
from codex_blender_modeler.models import SceneSpec


def _sha256(path: Path) -> str:
    """Hash one canonical fixture before and after read-only inspection."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_warning_only_unavailable_topology_evidence_keeps_profile_reviewable() -> None:
    """Keep advisory absence explicit without failing otherwise scored hard checks."""

    evidence = TopologyArtifact(
        role="topology_inventory",
        path="reports/aq/topology.json",
        sha256="c" * 64,
    )
    observations = [
        TopologyObservation(
            check=policy.check,
            availability="available",
            passed=True,
            measured_value=0,
            evidence=evidence,
            message="fixture passes",
        )
        for policy in get_topology_profile("static_prop_closed").checks
    ]
    index = next(
        item
        for item, observation in enumerate(observations)
        if observation.check == "texel_density"
    )
    observations[index] = TopologyObservation(
        check="texel_density",
        availability="unavailable",
        message="image-backed material lacks an approved texel-density target",
    )
    report = evaluate_topology_profile(
        report_id="aq-warning-only-unavailable",
        provenance=TopologyProvenance(
            job_id="aq_fixture",
            workflow_id="wf-aq-fixture",
            dispatch_id="dispatch-aq-fixture",
            project_version="0.9.0",
            inputs=[
                TopologyArtifact(
                    role="scene_spec",
                    path="analysis/scene_spec.json",
                    sha256="a" * 64,
                ),
                TopologyArtifact(
                    role="blend",
                    path="blender/scene.blend",
                    sha256="b" * 64,
                ),
            ],
        ),
        profile_name="static_prop_closed",
        observations=observations,
    )
    result = next(item for item in report.results if item.check == "texel_density")
    assert result.outcome == "unscorable"
    assert result.profile_failure_severity == "warning"
    assert report.unscorable == 1
    assert report.status == "warning"
    assert report.ok is True


def _scene(job_id: str) -> SceneSpec:
    """Create two separated closed cubes with one surface-contact relationship target."""

    return SceneSpec.model_validate(
        {
            "schema_version": "0.2.0",
            "job_id": job_id,
            "mode": "concept",
            "units": "METERS",
            "coordinate_system": {
                "handedness": "RIGHT",
                "up": "+Z",
                "forward": "-Y",
            },
            "nominal_scene_size": [3.0, 3.0, 3.0],
            "sources": [
                {
                    "id": "ref.main",
                    "path": "input/reference.png",
                    "kind": "reference",
                    "immutable": True,
                    "scale_anchors": [],
                }
            ],
            "materials": [
                {
                    "id": "mat.fixture",
                    "name": "Fixture",
                    "shader": "principled",
                    "base_color": [0.3, 0.5, 0.8, 1.0],
                    "roughness": 0.5,
                    "metallic": 0.0,
                    "emission_strength": 0.0,
                    "texture_manifest": None,
                }
            ],
            "objects": [
                {
                    "id": "fixture.base",
                    "name": "Fixture Base",
                    "geometry": {
                        "kind": "primitive",
                        "primitive": "cube",
                        "dimensions": [2.0, 2.0, 1.0],
                        "segments": 16,
                        "ring_segments": 8,
                    },
                    "transform": {
                        "location": [0.0, 0.0, 0.5],
                        "rotation_deg": [0.0, 0.0, 0.0],
                        "scale": [1.0, 1.0, 1.0],
                    },
                    "material_id": "mat.fixture",
                    "modifiers": [],
                    "generator": None,
                    "parent_id": None,
                    "shade_smooth": False,
                    "tags": ["qa_role:primary"],
                    "evidence": [],
                    "editable": {},
                },
                {
                    "id": "fixture.cap",
                    "name": "Fixture Cap",
                    "geometry": {
                        "kind": "primitive",
                        "primitive": "cube",
                        "dimensions": [1.0, 1.0, 1.0],
                        "segments": 16,
                        "ring_segments": 8,
                    },
                    "transform": {
                        "location": [0.0, 0.0, 1.501],
                        "rotation_deg": [0.0, 0.0, 0.0],
                        "scale": [1.0, 1.0, 1.0],
                    },
                    "material_id": "mat.fixture",
                    "modifiers": [],
                    "generator": None,
                    "parent_id": None,
                    "shade_smooth": False,
                    "tags": ["qa_role:supporting"],
                    "evidence": [],
                    "editable": {},
                },
            ],
            "camera": {
                "projection": "ORTHO",
                "location": [4.0, -6.0, 4.0],
                "target": [0.0, 0.0, 1.0],
                "focal_length_mm": 50.0,
                "ortho_scale": 4.0,
                "resolution": [320, 240],
            },
            "assumptions": [],
            "revision_notes": [],
        }
    )


def _plan(job_id: str) -> ModelingPlan:
    """Create a spatial_v1 plan whose required contact is evaluable in Blender."""

    return ModelingPlan.model_validate(
        {
            "schema_version": "0.4.0",
            "job_id": job_id,
            "reference_analysis_path": "analysis/reference_analysis.json",
            "camera_solution_path": "analysis/camera_solution.json",
            "stage": "authored",
            "objects": [
                {
                    "id": "fixture.base",
                    "label": "base",
                    "recommended_geometry": "primitive",
                    "source_ids": [],
                    "observed": False,
                    "confidence": 1.0,
                    "scope_role": "primary",
                    "assembly_role": "root",
                    "required_assembly_checks": [],
                    "notes": [],
                },
                {
                    "id": "fixture.cap",
                    "label": "cap",
                    "recommended_geometry": "primitive",
                    "source_ids": [],
                    "observed": False,
                    "confidence": 1.0,
                    "scope_role": "supporting",
                    "assembly_role": "attached",
                    "required_assembly_checks": ["position"],
                    "notes": [],
                },
            ],
            "assembly_consistency_policy": "spatial_v1",
            "assembly_frame": {
                "root_object_id": "fixture.base",
                "longitudinal_axis": "X",
                "lateral_axis": "Y",
                "vertical_axis": "Z",
                "symmetry": "bilateral",
                "evidence_status": "authored",
                "source_ids": [],
                "confidence": 1.0,
                "notes": [],
            },
            "assembly_relationships": [
                {
                    "id": "fixture.cap.contact",
                    "kind": "surface_contact",
                    "subject_id": "fixture.cap",
                    "reference_id": "fixture.base",
                    "evidence_status": "authored",
                    "source_ids": [],
                    "confidence": 1.0,
                    "required": True,
                    "tolerance": {"mode": "meters", "value": 0.002},
                    "instance_policy": "pairwise",
                    "notes": [],
                    "axis": "Z",
                    "subject_side": "MIN",
                    "reference_side": "MAX",
                    "min_transverse_overlap_ratio": 0.1,
                }
            ],
            "surface_detail_policy": None,
            "surface_details": [],
            "global_notes": [],
        }
    )


@pytest.mark.skipif(
    os.getenv("CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE") != "1",
    reason="Set CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE=1 for Blender 5 evidence.",
)
def test_static_prop_authoring_companions_are_hash_bound_and_read_only(
    tmp_path: Path,
) -> None:
    """Build one fixture and publish honest strict reports from its evaluated blend."""

    job_root = tmp_path / "aq_companion_fixture"
    for relative in ("input", "analysis", "blender", "reports"):
        (job_root / relative).mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), (40, 80, 160)).save(job_root / "input" / "reference.png")
    scene_path = job_root / "analysis" / "scene_spec.json"
    plan_path = job_root / "analysis" / "modeling_plan.json"
    scene_path.write_text(_scene(job_root.name).model_dump_json(indent=2) + "\n", encoding="utf-8")
    plan_path.write_text(_plan(job_root.name).model_dump_json(indent=2) + "\n", encoding="utf-8")
    blend_path = job_root / "blender" / "scene.blend"
    run_blender(
        "build_scene.py",
        ["--spec", str(scene_path), "--output", str(blend_path)],
        disable_autoexec=True,
    )
    before = {path: _sha256(path) for path in (scene_path, plan_path, blend_path)}

    output_root_relative = (
        "reports/aq_companions/"
        + "long-companion-segment-"
        + "x" * 48
        + "/run-"
        + "y" * 48
    )
    output_root = job_root / output_root_relative
    interrupted_stage = output_root.parent / f".{output_root.name}.staging-interrupted"
    os.makedirs(native_io_path(interrupted_stage), exist_ok=False)
    with open(native_io_path(interrupted_stage / "partial.json"), "w", encoding="utf-8") as handle:
        handle.write("{}\n")
    result = inspect_static_prop_authoring_companions(
        job_root=job_root,
        workflow_id="wf-aq-companion",
        dispatch_id="dispatch-aq-companion",
        output_root_relative=output_root_relative,
    )

    assert result.assembly_report.status == "passed"
    semantic = [item for item in result.assembly_report.findings if item.phase == "semantic"]
    assert len(semantic) == 1
    assert semantic[0].severity == "info"
    assert result.topology_report.profile.name == "static_prop_closed"
    assert len(result.topology_report.results) == 18
    assert result.topology_report.status == "passed"
    not_applicable = {
        item.check for item in result.topology_report.results if item.outcome == "not_applicable"
    }
    assert {"island_padding", "texel_density"}.issubset(not_applicable)
    assert {path: _sha256(path) for path in before} == before
    assert len(os.path.abspath(os.fspath(result.snapshot_path))) > 260
    assert os.path.isfile(native_io_path(result.snapshot_path))
    assert os.path.isfile(native_io_path(result.assembly_request_path))
    assert os.path.isfile(native_io_path(result.assembly_report_path))
    assert os.path.isfile(native_io_path(result.topology_report_path))
    assert os.path.isdir(
        native_io_path(
            output_root.parent / "interrupted_staging" / interrupted_stage.name
        )
    )
    with pytest.raises(FileExistsError):
        inspect_static_prop_authoring_companions(
            job_root=job_root,
            workflow_id="wf-aq-companion",
            dispatch_id="dispatch-aq-companion",
            output_root_relative=output_root_relative,
        )
