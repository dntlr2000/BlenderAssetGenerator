from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType

import pytest


def _load_runner() -> ModuleType:
    """Load the repository-local pytest runner without making scripts a package."""

    script_path = (Path("scripts") / "run_pytest_acl_safe.py").resolve()
    spec = importlib.util.spec_from_file_location("test_run_pytest_acl_safe", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selected_basetemp_accepts_both_pytest_argument_forms(tmp_path: Path) -> None:
    """Resolve only an explicitly supplied pytest basetemp argument."""

    module = _load_runner()
    expected = (tmp_path / "base").resolve()

    assert module.selected_basetemp(["--basetemp", str(expected)]) == expected
    assert module.selected_basetemp([f"--basetemp={expected}"]) == expected
    assert module.selected_basetemp(["-q"]) is None


def test_inherited_acl_mode_is_bounded_to_explicit_basetemp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leave unrelated Windows paths and nonrestrictive modes unchanged."""

    module = _load_runner()
    monkeypatch.setattr(module.sys, "platform", "win32")
    basetemp = (tmp_path / "base").resolve()

    roots = (basetemp,)
    assert module.inherited_acl_mkdir_mode(basetemp, 0o700, roots) == 0o777
    assert module.inherited_acl_mkdir_mode(basetemp / "child", 0o700, roots) == 0o777
    assert module.inherited_acl_mkdir_mode(tmp_path / "outside", 0o700, roots) == 0o700
    assert module.inherited_acl_mkdir_mode(basetemp / "child", 0o755, roots) == 0o755


def test_acl_environment_restores_mkdir_after_scoped_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore the process mkdir implementation after the pytest boundary exits."""

    module = _load_runner()
    monkeypatch.setattr(module.sys, "platform", "win32")
    basetemp = tmp_path / "base"
    basetemp.mkdir()
    original_mkdir = os.mkdir
    original_tempdir = module.tempfile.tempdir
    original_temp = os.environ.get("TEMP")
    original_tmp = os.environ.get("TMP")

    with module.pytest_basetemp_acl_environment(["--basetemp", str(basetemp)]):
        child = basetemp / "child"
        module.os.mkdir(child, 0o700)
        assert child.is_dir()
        assert module.tempfile.tempdir.endswith("base-process-temp")
        assert os.environ["TEMP"] == module.tempfile.tempdir
        assert os.environ["TMP"] == module.tempfile.tempdir
        marker = basetemp.with_name("base-process-temp") / ".retention-owner.json"
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["pid"] == os.getpid()
        assert payload["basetemp_name"] == "base"

    assert module.os.mkdir is original_mkdir
    assert module.tempfile.tempdir == original_tempdir
    assert os.environ.get("TEMP") == original_temp
    assert os.environ.get("TMP") == original_tmp
