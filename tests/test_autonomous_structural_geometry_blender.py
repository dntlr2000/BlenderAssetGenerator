"""Opt-in Blender 5 smoke tests for every structural geometry materializer."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from codex_blender_modeler.autonomy.authorization import artifact_for
from codex_blender_modeler.autonomy.candidate_evaluator import (
    _build_candidate,
    _compile_optional_structural_scene,
)
from codex_blender_modeler.autonomy.models import CandidateAuthoringAssignment
from codex_blender_modeler.blender_runner import BlenderRunError
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.structural_geometry.models import StructuralGeometryCandidate
from codex_blender_modeler.structural_geometry.service import (
    materialize_structural_candidate,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE") != "1",
    reason="set CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE=1 for Blender smoke tests",
)


def _primitive() -> dict[str, Any]:
    """Return one bounded cube operand recipe for the Boolean smoke fixture."""

    return {
        "kind": "primitive",
        "primitive": "cube",
        "dimensions": [1.5, 1.5, 1.5],
    }


def _boolean_tree(
    operation: str,
    *,
    tool_location: tuple[float, float, float] = (0.75, 0.0, 0.0),
) -> dict[str, Any]:
    """Return one transformed two-cube Boolean tree for the selected exact operation."""

    return {
        "kind": "boolean_tree",
        "operands": [
            {"id": "base", "geometry": _primitive()},
            {
                "id": "tool",
                "geometry": _primitive(),
                "transform": {"location": tool_location},
            },
        ],
        "operations": [
            {
                "id": "root",
                "operation": operation,
                "left_id": "base",
                "right_id": "tool",
            }
        ],
        "root_id": "root",
    }


def _candidates() -> list[tuple[str, dict[str, Any]]]:
    """Return representative strict candidates for every newly exposed builder kind."""

    return [
        (
            "loft",
            {
                "kind": "loft",
                "sections": [
                    {
                        "closed": True,
                        "points": [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
                    },
                    {
                        "closed": True,
                        "points": [
                            [-0.5, -0.5, 2],
                            [0.5, -0.5, 2],
                            [0.5, 0.5, 2],
                            [-0.5, 0.5, 2],
                        ],
                    },
                ],
                "resample_count": 4,
            },
        ),
        (
            "sweep",
            {
                "kind": "sweep",
                "profile": [[-0.2, -0.1], [0.2, -0.1], [0.2, 0.1], [-0.2, 0.1]],
                "path": [[0, 0, 0], [0, 1, 0], [0.5, 2, 0.5]],
            },
        ),
        (
            "multi_loop_extrude",
            {
                "kind": "multi_loop_extrude",
                "outer_loop": [[-2, -2], [2, -2], [2, 2], [-2, 2]],
                "hole_loops": [
                    [[-0.5, -0.5], [-0.5, 0.5], [0.5, 0.5], [0.5, -0.5]]
                ],
                "depth": 0.5,
            },
        ),
        (
            "boolean_tree",
            _boolean_tree("DIFFERENCE"),
        ),
        (
            "geometry_nodes_template",
            {
                "kind": "geometry_nodes_template",
                "template_id": "linear_instance_v1",
                "count": 4,
                "spacing": [1.25, 0, 0],
                "instance_dimensions": [1, 0.5, 0.5],
            },
        ),
    ]


@pytest.mark.parametrize(("kind", "geometry"), _candidates())
def test_structural_builder_materializes_in_blender(
    tmp_path,
    kind: str,
    geometry: dict[str, Any],
) -> None:
    """Materialize one candidate and verify stable semantic and nonempty mesh evidence."""

    job_root = tmp_path / f"structural_{kind}"
    candidate: dict[str, Any] = {
        "schema_version": "0.1.0",
        "semantic_id": f"asset.{kind}",
        "geometry": geometry,
    }
    if kind == "loft":
        candidate["geometry_intent"] = {
            "face_groups": [{"id": "body", "face_indices": [0]}],
            "sharp_edges": [{"vertices": [0, 1]}],
            "crease_edges": [{"vertices": [0, 1], "weight": 0.5}],
            "uv_seams": [{"vertices": [0, 1]}],
            "smoothing_policy": {"mode": "flat"},
        }
    validated = StructuralGeometryCandidate.model_validate_json(json.dumps(candidate))
    payload = materialize_structural_candidate(
        job_root=job_root,
        candidate=validated,
        candidate_relative_path="structural/candidate.json",
        mesh_relative_path="geometry/materialized.mesh.json",
        blend_relative_path="blender/materialized.blend",
        report_relative_path="reports/materialization.json",
    )
    assert payload.builder_kind == kind
    assert payload.semantic_id == f"asset.{kind}"
    assert payload.vertices
    assert payload.faces


def test_concave_multi_loop_discards_redundant_zero_area_cap_triangles(
    tmp_path: Path,
) -> None:
    """Materialize a valid charm profile that Blender tessellates with a zero-area no-op."""

    candidate = StructuralGeometryCandidate.model_validate_json(
        json.dumps({
            "schema_version": "0.1.0",
            "semantic_id": "prop.crystalgun.charms.cluster",
            "geometry": {
                "kind": "multi_loop_extrude",
                "outer_loop": [
                    [-0.2, -0.15],
                    [0.24, -0.15],
                    [0.24, -0.23],
                    [0.19, -0.23],
                    [0.2, -0.42],
                    [0.16, -0.62],
                    [0.12, -0.42],
                    [0.13, -0.23],
                    [0.07, -0.23],
                    [0.08, -0.47],
                    [0.03, -0.72],
                    [-0.02, -0.47],
                    [-0.01, -0.23],
                    [-0.08, -0.23],
                    [-0.07, -0.38],
                    [-0.13, -0.58],
                    [-0.19, -0.38],
                    [-0.18, -0.23],
                    [-0.2, -0.23],
                ],
                "hole_loops": [],
                "depth": 0.07,
                "axis": "Y",
                "cap": True,
            },
            "geometry_intent": {
                "face_groups": [],
                "sharp_edges": [],
                "crease_edges": [],
                "bevel_weights": [],
                "uv_seams": [],
                "smoothing_policy": {
                    "mode": "flat",
                    "angle_degrees": 30.0,
                    "keep_sharp": True,
                },
                "topology_policy": "static_prop_closed",
                "subdivision_intent": {
                    "enabled": False,
                    "levels": 0,
                    "boundary_smoothing": "preserve_corners",
                },
                "lod_intent": {
                    "preserve_silhouette": True,
                    "protected_face_groups": [],
                    "minimum_triangle_ratio": 1.0,
                },
            },
        })
    )
    payload = materialize_structural_candidate(
        job_root=tmp_path / "concave_multi_loop",
        candidate=candidate,
        candidate_relative_path="structural/candidate.json",
        mesh_relative_path="geometry/materialized.mesh.json",
        blend_relative_path="blender/materialized.blend",
        report_relative_path="reports/materialization.json",
        mesh_payload_version="0.2.0",
        material_id="mat.crystal.translucent",
    )

    assert payload.builder_kind == "multi_loop_extrude"
    assert payload.semantic_id == "prop.crystalgun.charms.cluster"
    assert payload.vertices
    assert payload.faces


def test_boolean_intersection_materializes_exact_overlap_in_blender(tmp_path: Path) -> None:
    """Evaluate INTERSECT in Blender and verify the overlapping cubes' exact bounds."""

    candidate = StructuralGeometryCandidate.model_validate_json(
        json.dumps({
            "schema_version": "0.1.0",
            "semantic_id": "asset.boolean_intersection",
            "geometry": _boolean_tree("INTERSECT"),
        })
    )
    payload = materialize_structural_candidate(
        job_root=tmp_path / "boolean_intersection",
        candidate=candidate,
        candidate_relative_path="structural/candidate.json",
        mesh_relative_path="geometry/materialized.mesh.json",
        blend_relative_path="blender/materialized.blend",
        report_relative_path="reports/materialization.json",
    )
    bounds = [
        (
            min(vertex[axis] for vertex in payload.vertices),
            max(vertex[axis] for vertex in payload.vertices),
        )
        for axis in range(3)
    ]

    assert bounds == pytest.approx([(0.0, 0.75), (-0.75, 0.75), (-0.75, 0.75)])
    assert payload.faces


def test_boolean_intersection_rejects_an_empty_blender_result(tmp_path: Path) -> None:
    """Fail closed when exact INTERSECT evaluates two disjoint operands to no mesh."""

    candidate = StructuralGeometryCandidate.model_validate_json(
        json.dumps({
            "schema_version": "0.1.0",
            "semantic_id": "asset.boolean_empty_intersection",
            "geometry": _boolean_tree("INTERSECT", tool_location=(3.0, 0.0, 0.0)),
        })
    )

    with pytest.raises(BlenderRunError, match="produced an empty mesh"):
        materialize_structural_candidate(
            job_root=tmp_path / "boolean_empty_intersection",
            candidate=candidate,
            candidate_relative_path="structural/candidate.json",
            mesh_relative_path="geometry/materialized.mesh.json",
            blend_relative_path="blender/materialized.blend",
            report_relative_path="reports/materialization.json",
        )


def _candidate_scene_payload(job_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return mirrored V0.2/V0.3 scenes spanning every structural builder family."""

    structural = _candidates()
    objects: list[dict[str, Any]] = []
    for index, (kind, _geometry) in enumerate(structural):
        objects.append(
            {
                "id": f"asset.{kind}",
                "name": f"Structural {kind}",
                "geometry": {
                    "kind": "primitive",
                    "primitive": "cube",
                    "dimensions": [1.0, 1.0, 1.0],
                    "segments": 16,
                    "ring_segments": 8,
                },
                "transform": {
                    "location": [float(index * 4), 0.0, 0.0],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                },
                "material_id": "mat.structural",
                "modifiers": [],
                "generator": None,
                "parent_id": None,
                "shade_smooth": False,
                "tags": ["qa_role:primary", "scope:primary"],
                "evidence": [
                    {
                        "source_id": "ref.main",
                        "bbox_norm": [0.1, 0.1, 0.9, 0.9],
                        "status": "observed",
                        "confidence": 0.9,
                    }
                ],
                "editable": {},
            }
        )
    legacy: dict[str, Any] = {
        "schema_version": "0.2.0",
        "job_id": job_id,
        "mode": "concept",
        "units": "METERS",
        "coordinate_system": {"handedness": "RIGHT", "up": "+Z", "forward": "-Y"},
        "nominal_scene_size": [16.0, 6.0, 5.0],
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
                "id": "mat.structural",
                "name": "Structural gray",
                "shader": "principled",
                "base_color": [0.35, 0.4, 0.45, 1.0],
                "roughness": 0.5,
                "metallic": 0.0,
                "emission_strength": 0.0,
                "texture_manifest": None,
            }
        ],
        "objects": objects,
        "camera": {
            "projection": "ORTHO",
            "location": [8.0, -22.0, 10.0],
            "target": [6.0, 0.0, 0.5],
            "focal_length_mm": 50.0,
            "ortho_scale": 18.0,
            "resolution": [256, 256],
        },
        "assumptions": ["Structural reachability Blender smoke."],
        "revision_notes": [],
    }
    scene_v03 = json.loads(json.dumps(legacy))
    scene_v03["schema_version"] = "0.3.0"
    for obj, (_kind, geometry) in zip(
        scene_v03["objects"],
        structural,
        strict=True,
    ):
        obj["geometry"] = geometry
    return legacy, scene_v03


def test_aq_candidate_compiles_and_builds_all_structural_recipes(tmp_path: Path) -> None:
    """Reach actual Blender loft, sweep, Boolean, and multi-loop builders from AQ staging."""

    job_root = tmp_path / "structural_candidate_reach"
    output_root = "workflows/wf/artifacts/candidates/candidate-01"
    candidate_root = job_root / output_root
    candidate_root.mkdir(parents=True)
    (job_root / "input").mkdir(parents=True)
    (job_root / "input" / "reference.png").write_bytes(b"immutable-smoke-reference")
    legacy_payload, scene_v03_payload = _candidate_scene_payload(job_root.name)
    legacy = SceneSpec.model_validate(legacy_payload)
    legacy_path = candidate_root / "scene_spec.json"
    legacy_path.write_text(legacy.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (candidate_root / "scene_spec_v03.json").write_text(
        json.dumps(scene_v03_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    assignment = CandidateAuthoringAssignment.model_construct(
        output_root=output_root,
        scene_spec_v03_output=f"{output_root}/scene_spec_v03.json",
    )

    compilation = _compile_optional_structural_scene(
        job_root,
        candidate_root,
        assignment,
        legacy,
        artifact_for(job_root, legacy_path),
    )
    blend, inventory, validation = _build_candidate(
        job_root,
        candidate_root,
        compilation.effective_scene_path,
    )

    assert len(compilation.recipe_artifacts) == 5
    assert len(compilation.mesh_payload_artifacts) == 5
    assert {item.geometry.kind for item in compilation.scene.objects} == {"custom_mesh"}
    assert blend.is_file()
    assert inventory.is_file()
    assert json.loads(validation.read_text(encoding="utf-8"))["ok"] is True
