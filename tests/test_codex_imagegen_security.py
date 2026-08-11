"""Security and dependency sentinels for the ImageGen companion package."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from codex_blender_modeler.codex_imagegen.models import CodexImageArtifact


def test_package_has_no_external_provider_or_network_imports() -> None:
    """Prevent SDK, HTTP client, socket, and browser dependencies in repository code."""

    package = Path("src/codex_blender_modeler/codex_imagegen")
    forbidden_roots = {
        "aiohttp",
        "httpx",
        "openai",
        "requests",
        "socket",
        "urllib",
    }
    violations: list[str] = []
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                roots = {node.module.split(".")[0]}
            else:
                continue
            if roots & forbidden_roots:
                violations.append(f"{path.name}:{node.lineno}")
    assert violations == []


def test_package_contains_no_external_endpoint_literals() -> None:
    """Reject HTTP endpoint literals even when no client library is imported."""

    package = Path("src/codex_blender_modeler/codex_imagegen")
    content = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(package.glob("*.py"))
    ).casefold()
    assert "http://" not in content
    assert "https://" not in content


@pytest.mark.parametrize(
    "path",
    ["../escape.png", "/absolute.png", "C:/escape.png", "a//b.png", "a\\b.png"],
)
def test_artifact_paths_reject_escape_and_nonportable_syntax(path: str) -> None:
    """Reject every lexical path form that could escape the owning job workspace."""

    with pytest.raises(ValidationError):
        CodexImageArtifact(
            artifact_id="invalid-path",
            kind="codex-image-generated-png",
            path=path,
            sha256="0" * 64,
            byte_size=1,
            media_type="image/png",
        )
