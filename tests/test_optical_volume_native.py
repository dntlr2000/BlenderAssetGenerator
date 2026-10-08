"""Actual Blender5.0.1 graph/conversion/export/import proof for the opt-in volume subset."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "fixture", ["optical_volume_native_probe.py", "optical_volume_hardening_probe.py"]
)
def test_volume_survives_real_native_conversion_and_glb(tmp_path, fixture):
    """Build, convert and reimport a closed volume; reject tampering and open boundaries."""
    blender = os.environ.get("BLENDER_BIN") or shutil.which("blender")
    if not blender:
        pytest.skip("Blender unavailable: native optical-volume evidence not established")
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="2")
    for variable in (
        "TEMP",
        "TMP",
        "TMPDIR",
        "BLENDER_USER_CONFIG",
        "BLENDER_USER_SCRIPTS",
        "BLENDER_USER_DATAFILES",
        "MESA_SHADER_CACHE_DIR",
    ):
        folder = tmp_path / variable
        folder.mkdir()
        env[variable] = str(folder)
    result = subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--threads",
            "2",
            "--python-exit-code",
            "1",
            "--python",
            str(root / "tests/fixtures" / fixture),
            "--",
            "--repo",
            str(root),
            "--output",
            str(tmp_path / "result"),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    (tmp_path / "blender.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads((tmp_path / "result/RESULT.json").read_text())
    assert evidence["status"] == "passed" and evidence["blender"] == "5.0.1"
    if fixture == "optical_volume_native_probe.py":
        assert (
            evidence["actual_serialization_verification"][0]["serialized_factors_verified"] is True
        )
        assert evidence["actual_import_boundary"][0]["closed_connected_outward_boundary"] is True
        assert evidence["actual_Unity_test"] is False
    else:
        assert len(evidence["results"]) >= 20
