"""Opt-in Blender evidence for shell materialization and the unchanged AQ transaction."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import test_autonomy_v2_candidate_validation_blender as geometry_fixture
from test_aq_triangle_shell import tetra_shell

from codex_blender_modeler.structural_geometry.mesh_payload_io_v02 import (
    verify_mesh_payload_v02_source_hashes,
)
from codex_blender_modeler.structural_geometry.models import StructuralGeometryCandidate
from codex_blender_modeler.structural_geometry.service import materialize_structural_candidate

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE") != "1",
    reason="set CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE=1 for Blender shell smoke",
)


def test_shell_materialization_preserves_vertices_triangles_and_uvs(tmp_path: Path) -> None:
    """Compile through the fixed host builder and verify exact identity plus Blender float UVs."""
    geometry = tetra_shell()
    candidate = StructuralGeometryCandidate.model_validate_json(json.dumps({
        "semantic_id": "fixture.closed_shell", "geometry": geometry,
        "geometry_intent": {"smoothing_policy": {"mode": "flat"}},
    }))
    root = tmp_path / "shell"
    mesh = materialize_structural_candidate(job_root=root, candidate=candidate,
        candidate_relative_path="structural/recipe.json", mesh_relative_path="geometry/mesh.json",
        blend_relative_path="blender/mesh.blend", report_relative_path="reports/materialize.json",
        mesh_payload_version="0.2.0", material_id="mat.shell")
    assert mesh.builder_kind == "triangulated_shell"
    assert [list(vertex) for vertex in mesh.vertices] == geometry["vertices"]
    assert mesh.faces == geometry["triangles"]
    assert [list(uv) for uv in mesh.loop_uvs] == geometry["loop_uvs"]
    verify_mesh_payload_v02_source_hashes(mesh, job_root=root)


def test_shell_uses_exact_policy_promotion_and_crash_reconciliation(tmp_path, monkeypatch) -> None:
    """Run the existing transaction/reconciliation smoke with a data-only shell candidate."""
    original = geometry_fixture._scene_v03

    def scene(job_id, reference_path):
        """Map fixture intent to tetrahedron indices while retaining its authority bindings."""
        result = original(job_id, reference_path)
        result["objects"][0]["geometry"] = tetra_shell()
        intent = result["objects"][0]["geometry_intent"]
        intent["face_groups"][0]["face_indices"] = list(range(4))
        intent["bevel_weights"][0]["vertices"] = [1, 3]
        return result

    monkeypatch.setattr(geometry_fixture, "_scene_v03", scene)
    geometry_fixture.test_geometry_controller_candidate_builds_and_promotes_exactly(
        tmp_path, monkeypatch, with_preflight=True,
    )
