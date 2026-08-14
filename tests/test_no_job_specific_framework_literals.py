"""Regression tests for the exact incident-literal framework gate."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_no_job_specific_framework_literals.py"


def _load_checker():
    """Load the standalone gate without making scripts a runtime package."""

    spec = importlib.util.spec_from_file_location("job_literal_checker", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_job_specific_literal_checker_has_exact_bounded_scope() -> None:
    """Keep the detector incident-specific instead of banning arbitrary hashes."""

    checker = _load_checker()
    tokens = {item.token for item in checker.INCIDENT_LITERALS}
    assert "item_crystalgun" in tokens
    assert "prop.crystalgun" in tokens
    assert all(token != "[0-9a-f]{64}" for token in tokens)
    roots = {path.relative_to(ROOT).as_posix() for path in checker.SCAN_ROOTS}
    assert roots == {"src/codex_blender_modeler", "schemas", "prompts"}
