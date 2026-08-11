"""Focused checks for hierarchical repository instructions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_checker():
    """Load the standalone checker as a test-local module."""

    path = ROOT / "scripts" / "check_agent_instructions.py"
    spec = importlib.util.spec_from_file_location("cbm_check_agent_instructions", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_repository_instruction_hierarchy_is_current() -> None:
    """Keep size, links, sentinels, policies, and exact legacy rules valid."""

    checker = _load_checker()
    assert checker.validate_agent_instructions(ROOT) == ()


def test_every_instruction_chain_stays_within_budget() -> None:
    """Enforce the actual root-to-leaf loading budget for every AGENTS file."""

    checker = _load_checker()
    assert (ROOT / "AGENTS.md").stat().st_size <= checker.ROOT_MAX_BYTES
    for leaf in checker.discover_agent_files(ROOT):
        chain = checker.instruction_chain(ROOT, leaf)
        assert sum(path.stat().st_size for path in chain) <= checker.ROOT_TO_LEAF_MAX_BYTES


def test_structured_policy_conflict_is_rejected(tmp_path: Path) -> None:
    """Detect contradictory RULE_POLICY values instead of keyword guessing."""

    root = tmp_path
    root_agents = root / "AGENTS.md"
    leaf = root / "src" / "AGENTS.md"
    leaf.parent.mkdir()
    root_agents.write_text("<!-- RULE_POLICY project_skill=explicit -->\n", encoding="utf-8")
    leaf.write_text("<!-- RULE_POLICY project_skill=automatic -->\n", encoding="utf-8")

    checker = _load_checker()
    findings = checker._validate_policy_conflicts((root_agents, leaf), root)

    assert len(findings) == 1
    assert "project_skill" in findings[0]

