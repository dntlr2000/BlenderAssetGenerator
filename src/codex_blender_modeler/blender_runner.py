from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .blender_artifacts import native_io_path
from .config import executable_exists, get_settings


class BlenderRunError(RuntimeError):
    pass


def run_blender(
    script_name: str,
    args: list[str],
    blend_file: Path | None = None,
    *,
    factory_startup: bool = False,
    disable_autoexec: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run one fixed repository script with isolated stdin and bounded load options."""

    settings = get_settings()
    if not executable_exists(settings.blender_bin):
        raise FileNotFoundError(
            f"Blender executable not found: {settings.blender_bin}. Set BLENDER_BIN in .env"
        )
    script = settings.repo_root / "src" / "codex_blender_modeler" / "blender_scripts" / script_name
    if not os.path.isfile(native_io_path(script)):
        raise FileNotFoundError(script)

    command = [settings.blender_bin]
    if factory_startup:
        command.append("--factory-startup")
    if disable_autoexec:
        command.append("--disable-autoexec")
    command.extend(
        [
            "--background",
            "--python-exit-code",
            "1",
        ]
    )
    if blend_file is not None:
        if not os.path.isfile(native_io_path(blend_file)):
            raise FileNotFoundError(blend_file)
        command.append(native_io_path(blend_file))
    command.extend(["--python", str(script), "--", *args])

    result = subprocess.run(
        command,
        cwd=settings.repo_root,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=settings.blender_timeout,
        check=False,
    )
    if result.returncode != 0:
        raise BlenderRunError(
            "Blender command failed\n"
            f"Command: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result
