"""Opt-in Blender 5.0.1 materialization and independent native topology proofs."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_profiled_relief import ADVERSARIAL_TAPER, make_ribbon, signed_volume

from codex_blender_modeler import blender_runner
from codex_blender_modeler.structural_geometry import profiled_relief as module
from codex_blender_modeler.structural_geometry.models import (
    GeometryIntent,
    LoftGeometry,
    LoftSection,
    SmoothingPolicy,
    StructuralGeometryCandidate,
)
from codex_blender_modeler.structural_geometry.service import materialize_structural_candidate
from codex_blender_modeler.structural_geometry.triangle_shell import TriangulatedShellGeometry

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE") != "1",
    reason="set CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE=1 for native profiled-relief evidence",
)


@pytest.mark.parametrize(
    "fixture", ["ridge", "trough", "chamfer", "extreme_taper", "sparse_gem", "adversarial_negative"]
)
def test_profiled_geometry_survives_native_materialization(tmp_path: Path, monkeypatch, fixture):
    """Prove exact face identity, native closed winding and evaluated triangle embedding."""
    if fixture == "adversarial_negative":
        with pytest.raises(ValueError, match="emitted triangles"):
            module.build_profiled_relief_ribbon(**ADVERSARIAL_TAPER)
        # Test-only negative control, never an authoring option or production mode.
        with monkeypatch.context() as context:
            context.setattr(module, "_validate_embedded", lambda shell: None)
            geometry = module.build_profiled_relief_ribbon(**ADVERSARIAL_TAPER)
    elif fixture == "sparse_gem":
        geometry = LoftGeometry(
            sections=[
                LoftSection(
                    points=[
                        (x * radius, y, z * radius) for x, z in [(0, -1), (1, 0), (0, 1), (-1, 0)]
                    ],
                    closed=True,
                )
                for radius, y in [(0.2, -0.1), (1.0, 0.0), (0.2, 0.1)]
            ],
            correspondence_policy="index",
        )
    elif fixture == "extreme_taper":
        geometry = make_ribbon(
            "trough", width=[0.001, 0.2, 0.01, 0.15], depth=[0.2, 0.001, 0.08, 0.004]
        )
    else:
        geometry = make_ribbon(fixture)
    calls = []
    original = subprocess.run

    def capture(*args, **kwargs):
        """Serialize native execution when requested and record the unchanged command."""
        lock_path = os.environ.get("CBM_TEST_BLENDER_LOCK")
        if lock_path:
            import fcntl

            with open(lock_path, "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = original(*args, **kwargs)
        else:
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
        (tmp_path / "native_commands.json").write_text(json.dumps(calls, indent=2) + "\n")
        return result

    monkeypatch.setattr(blender_runner.subprocess, "run", capture)
    candidate = StructuralGeometryCandidate(
        semantic_id=f"fixture.{fixture}",
        geometry=geometry,
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
        material_id="mat.profile",
    )
    if isinstance(geometry, TriangulatedShellGeometry):
        assert payload.faces == [list(face) for face in geometry.triangles]
        reconstructed = TriangulatedShellGeometry(
            vertices=payload.vertices, triangles=geometry.triangles
        )
        assert signed_volume(reconstructed) == pytest.approx(signed_volume(geometry), rel=1e-4)
        for actual, expected in zip(payload.vertices, geometry.vertices, strict=True):
            assert actual == pytest.approx(expected, abs=3e-7)
    assert payload.semantic_id == candidate.semantic_id
    assert payload.material_slots[0].material_id == "mat.profile"
    probe = tmp_path / "reports/native_independent_probe.json"
    result = subprocess.run(
        [
            os.environ["BLENDER_BIN"],
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            "--python",
            str(Path(__file__).with_name("blender_profiled_relief_probe.py")),
            "--",
            "--blend",
            str(tmp_path / "blender/mesh.blend"),
            "--output",
            str(probe),
        ]
        + (["--expect-intersections"] if fixture == "adversarial_negative" else []),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(probe.read_text())
    assert report["blender_version"] == "5.0.1"
    assert all(call["stdin_devnull"] and call["returncode"] == 0 for call in calls)
    assert all("--python-exit-code" in call["command"] for call in calls)
