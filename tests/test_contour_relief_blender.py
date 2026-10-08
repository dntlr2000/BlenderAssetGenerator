"""Opt-in Blender 5 evidence for contour helpers through the fixed structural builder."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_contour_relief import CONTOURS, _shell, _signed_volume

from codex_blender_modeler import blender_runner
from codex_blender_modeler.structural_geometry.contour_relief import (
    build_contour_prism,
    build_relief_ribbon,
)
from codex_blender_modeler.structural_geometry.models import (
    GeometryIntent,
    SmoothingPolicy,
    StructuralGeometryCandidate,
)
from codex_blender_modeler.structural_geometry.service import materialize_structural_candidate

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE") != "1",
    reason="set CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE=1 for native contour-shell evidence",
)


@pytest.mark.parametrize(
    "fixture", ["panel", "concave_bracket", "forked_rail", "organic_plate", "prism", "ribbon"]
)
def test_contour_shell_materializes_in_blender(tmp_path: Path, monkeypatch, fixture):
    """Preserve caps, boundary, orientation and identity through actual native materialization."""
    if fixture == "prism":
        shell = build_contour_prism(CONTOURS["concave_bracket"], depth=0.4)
    elif fixture == "ribbon":
        shell = build_relief_ribbon(
            [(0, 0), (1, 0.2), (2, 0.2), (3, 0)],
            width=[0.15, 0.25, 0.2, 0.12],
            depth=0.12,
            bevel_width=0.015,
            bevel_depth=0.025,
            max_chord_error=0.002,
        )
    else:
        shell = _shell(CONTOURS[fixture])
    calls = []
    original = subprocess.run

    def capture(*args, **kwargs):
        """Retain exact native invocation and output without changing its execution boundary."""
        result = original(*args, **kwargs)
        calls.append(
            {
                "command": args[0],
                "stdin_devnull": kwargs.get("stdin") == subprocess.DEVNULL,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        (tmp_path / "native_command.json").write_text(json.dumps(calls, indent=2) + "\n")
        return result

    monkeypatch.setattr(blender_runner.subprocess, "run", capture)
    candidate = StructuralGeometryCandidate(
        semantic_id=f"fixture.{fixture}",
        geometry=shell,
        geometry_intent=GeometryIntent(smoothing_policy=SmoothingPolicy(mode="flat")),
    )
    payload = materialize_structural_candidate(
        job_root=tmp_path,
        candidate=candidate,
        candidate_relative_path="structural/recipe.json",
        mesh_relative_path="geometry/mesh.json",
        blend_relative_path="blender/mesh.blend",
        report_relative_path="reports/materialize.json",
        mesh_payload_version="0.2.0",
        material_id="mat.shell",
    )
    (tmp_path / "native_command.json").write_text(json.dumps(calls, indent=2) + "\n")
    assert calls and all(call["stdin_devnull"] and call["returncode"] == 0 for call in calls)
    assert all("--python-exit-code" in call["command"] for call in calls)
    assert payload.faces == [list(face) for face in shell.triangles]
    assert len(payload.vertices) == len(shell.vertices)
    for actual, expected in zip(payload.vertices, shell.vertices, strict=True):
        assert actual == pytest.approx(expected, abs=3e-7)
    # Reconstruct through the strict shell validator to recheck native float geometry.
    imported = shell.model_copy(update={"vertices": payload.vertices})
    type(shell).model_validate(imported.model_dump())
    assert _signed_volume(imported) == pytest.approx(_signed_volume(shell), rel=1e-5)
    assert payload.semantic_id == candidate.semantic_id
    assert payload.material_slots[0].material_id == "mat.shell"
