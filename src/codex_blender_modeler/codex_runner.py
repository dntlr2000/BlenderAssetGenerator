from __future__ import annotations

import subprocess
from pathlib import Path

from .config import executable_exists, get_settings


class CodexRunError(RuntimeError):
    pass


def run_codex_json(
    *,
    prompt: str,
    images: list[Path],
    schema: Path,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    settings = get_settings()
    if not executable_exists(settings.codex_bin):
        raise FileNotFoundError(f"Codex executable not found: {settings.codex_bin}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if not images:
        raise ValueError("At least one image is required")
    command = [
        settings.codex_bin,
        "exec",
        "--sandbox",
        "workspace-write",
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(output),
    ]
    for image in images:
        resolved = image.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        command.extend(["--image", str(resolved)])
    command.append(prompt)
    result = subprocess.run(
        command,
        cwd=settings.repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise CodexRunError(
            "Codex command failed\n"
            f"Command: {' '.join(command[:-1])} <prompt>\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result
