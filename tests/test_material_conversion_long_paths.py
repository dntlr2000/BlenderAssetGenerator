"""Exercise exact portable-conversion dependency I/O beyond Windows MAX_PATH."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from codex_blender_modeler.blender_artifacts import native_io_path, sha256_file
from codex_blender_modeler.blender_scripts import portable_material_conversion_runtime as runtime
from codex_blender_modeler.optimization.io import load_model
from codex_blender_modeler.packaging.material_conversion import _hashed_artifact, _shader_artifact


class _Contract(BaseModel):
    """Preserve the existing optimization loader's ordinary Python-validation semantics."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str
    count: int


def _deep_path(root: Path, name: str = "recipe.json") -> Path:
    """Select a fixture-owned dependency whose absolute filename exceeds 280 chars."""

    parent = root / "production/autonomy_v2/session/material_inputs"
    while len(os.path.abspath(parent / name)) < 280:
        parent /= "candidate-dependency-0123456789abcdef"
    return parent / name


def _write(path: Path, content: bytes) -> None:
    """Create exact fixture bytes through native I/O without changing prior files."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    with open(native_io_path(path), "xb") as stream:
        stream.write(content)


@pytest.mark.parametrize("kind", ["shader", "dependency"])
def test_portable_conversion_binds_exact_deep_inputs(tmp_path: Path, kind: str) -> None:
    """A readable long recipe binds the same relative path and SHA as a short one."""

    path = _deep_path(tmp_path)
    content = b'{"schema_version":"0.5.0","material_id":"mat.panel"}\n'
    _write(path, content)
    before = sha256_file(path)
    artifact = (
        _shader_artifact(tmp_path, "mat.panel", path)
        if kind == "shader"
        else _hashed_artifact(tmp_path, "recipe.panel", "other", path)
    )
    assert artifact.path == path.relative_to(tmp_path).as_posix()
    assert artifact.sha256 == hashlib.sha256(content).hexdigest() == before
    assert sha256_file(path) == before


@pytest.mark.parametrize("kind", ["shader", "dependency"])
def test_portable_conversion_deep_bindings_reject_escape(tmp_path: Path, kind: str) -> None:
    """Supporting native reads does not authorize a dependency outside its job."""

    path = _deep_path(tmp_path / "outside")
    _write(path, b"outside fixture")
    root = tmp_path / "job"
    root.mkdir()
    with pytest.raises(ValueError, match="outside the job workspace"):
        if kind == "shader":
            _shader_artifact(root, "mat.panel", path)
        else:
            _hashed_artifact(root, "recipe.panel", "other", path)


def test_optimization_loader_reads_deep_json_without_schema_relaxation(tmp_path: Path) -> None:
    """Native reads retain existing model validation, relative provenance and exact bytes."""

    path = _deep_path(tmp_path, "contract.json")
    content = b'{"schema_version":"0.7.0","count":"7"}\n'
    _write(path, content)
    assert load_model(path, _Contract) == _Contract(schema_version="0.7.0", count=7)
    assert sha256_file(path) == hashlib.sha256(content).hexdigest()
    bad_path = _deep_path(tmp_path, "invalid-contract.json")
    _write(bad_path, b'{"schema_version":"0.7.0","count":7,"unknown":true}')
    with pytest.raises(ValidationError, match="Extra inputs"):
        load_model(bad_path, _Contract)


def test_optimization_loader_keeps_missing_and_invalid_json_fail_closed(tmp_path: Path) -> None:
    """Long missing or malformed contracts remain distinct hard failures."""

    path = _deep_path(tmp_path, "missing-contract.json")
    with pytest.raises(FileNotFoundError):
        load_model(path, _Contract)
    malformed = _deep_path(tmp_path, "malformed-contract.json")
    _write(malformed, b"{not-json}")
    with pytest.raises(ValueError, match="Invalid JSON contract"):
        load_model(malformed, _Contract)


def test_blender_conversion_runtime_hashes_exact_deep_dependency(tmp_path: Path) -> None:
    """The stdlib-only Blender converter hashes the same deep bytes as the host."""

    path = _deep_path(tmp_path)
    content = b"exact shader binding for portable conversion"
    _write(path, content)
    assert runtime.sha256_file(path) == hashlib.sha256(content).hexdigest()
    assert sha256_file(path) == runtime.sha256_file(path)


def test_blender_conversion_runtime_publishes_deep_json_atomically(tmp_path: Path) -> None:
    """The conversion evidence writer retains serialization and clears its own transaction."""

    path = _deep_path(tmp_path, "conversion-evidence.json")
    payload = {"schema_version": "0.7.0", "unicode": "검증", "count": 3}
    runtime.write_json_atomic(path, payload)
    with open(native_io_path(path), encoding="utf-8") as stream:
        assert json.load(stream) == payload
    assert not os.path.exists(native_io_path(path.with_suffix(path.suffix + ".partial")))


@pytest.mark.parametrize("kind", ["shader", "dependency"])
def test_portable_conversion_missing_deep_inputs_remain_missing(tmp_path: Path, kind: str) -> None:
    """A native filename does not bypass the required regular-file existence check."""

    path = _deep_path(tmp_path)
    with pytest.raises(FileNotFoundError):
        if kind == "shader":
            _shader_artifact(tmp_path, "mat.panel", path)
        else:
            _hashed_artifact(tmp_path, "recipe.panel", "other", path)
