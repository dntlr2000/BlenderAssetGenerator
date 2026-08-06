from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from codex_blender_modeler import blender_runner


def test_blender_runner_isolates_mcp_stdin_and_propagates_python_failures(
    tmp_path: Path, monkeypatch
) -> None:
    script_dir = tmp_path / "src" / "codex_blender_modeler" / "blender_scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "build_scene.py").write_text("print('ok')", encoding="utf-8")
    blender = tmp_path / "blender.exe"
    blender.write_bytes(b"")
    settings = SimpleNamespace(
        blender_bin=str(blender),
        repo_root=tmp_path,
        blender_timeout=10,
    )
    monkeypatch.setattr(blender_runner, "get_settings", lambda: settings)
    monkeypatch.setattr(blender_runner, "executable_exists", lambda _value: True)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    blender_runner.run_blender("build_scene.py", ["--demo", "1"])

    assert captured["command"][:4] == [
        str(blender),
        "--background",
        "--python-exit-code",
        "1",
    ]
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["check"] is False


def test_blender_runner_can_request_factory_startup_for_clean_imports(
    tmp_path: Path, monkeypatch
) -> None:
    """Insert factory-startup before background execution only when explicitly requested."""

    script_dir = tmp_path / "src" / "codex_blender_modeler" / "blender_scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "validate_export_roundtrip.py").write_text(
        "print('ok')", encoding="utf-8"
    )
    blender = tmp_path / "blender.exe"
    blender.write_bytes(b"")
    settings = SimpleNamespace(
        blender_bin=str(blender),
        repo_root=tmp_path,
        blender_timeout=10,
    )
    monkeypatch.setattr(blender_runner, "get_settings", lambda: settings)
    monkeypatch.setattr(blender_runner, "executable_exists", lambda _value: True)
    captured = {}

    def fake_run(command, **kwargs):
        """Capture the isolated Blender command without starting a process."""

        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    blender_runner.run_blender(
        "validate_export_roundtrip.py",
        ["--demo", "1"],
        factory_startup=True,
    )

    assert captured["command"][:5] == [
        str(blender),
        "--factory-startup",
        "--background",
        "--python-exit-code",
        "1",
    ]


def test_blender_runner_can_disable_autoexec_for_untrusted_blend_inputs(
    tmp_path: Path, monkeypatch
) -> None:
    """Place Blender safe-mode before an externally supplied blend is loaded."""

    script_dir = tmp_path / "src" / "codex_blender_modeler" / "blender_scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "inspect_external_static_asset.py").write_text(
        "print('ok')", encoding="utf-8"
    )
    blender = tmp_path / "blender.exe"
    blender.write_bytes(b"")
    source = tmp_path / "manual.blend"
    source.write_bytes(b"blend")
    settings = SimpleNamespace(
        blender_bin=str(blender),
        repo_root=tmp_path,
        blender_timeout=10,
    )
    monkeypatch.setattr(blender_runner, "get_settings", lambda: settings)
    monkeypatch.setattr(blender_runner, "executable_exists", lambda _value: True)
    captured = {}

    def fake_run(command, **_kwargs):
        """Capture the safe external-source Blender command without execution."""

        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    blender_runner.run_blender(
        "inspect_external_static_asset.py",
        ["--source", str(source)],
        blend_file=source,
        disable_autoexec=True,
    )

    assert captured["command"][:5] == [
        str(blender),
        "--disable-autoexec",
        "--background",
        "--python-exit-code",
        "1",
    ]
    assert captured["command"][5] == str(source)
