"""Public parity and strict schema checks for the optional finite campaign mandate."""

from __future__ import annotations

import inspect
import json
import runpy
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from codex_blender_modeler import mcp_server
from codex_blender_modeler.cli import app

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "plan_fidelity_campaign_delegation",
    "record_fidelity_campaign_delegation_approval",
    "issue_fidelity_campaign_scope",
    "publish_fidelity_campaign_preparation",
    "start_fidelity_campaign_scope",
    "close_fidelity_campaign_scope",
    "get_fidelity_campaign_delegation_status",
}


def test_delegation_cli_mcp_allowlist_and_disabled_default():
    """Keep every added public entry discoverable and all mutations explicitly experimental."""
    config = tomllib.loads((ROOT / ".codex/config.toml").read_text(encoding="utf-8"))
    assert TOOLS <= set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    for name in TOOLS:
        function = getattr(mcp_server, name)
        assert callable(function)
        if not name.startswith("get_"):
            assert inspect.signature(function).parameters["experimental_opt_in"].default is False
    runner = CliRunner()
    for suffix in ("plan", "approve", "scope", "prepare", "start", "close", "status"):
        result = runner.invoke(app, [f"fidelity-delegation-{suffix}", "--help"])
        assert result.exit_code == 0, result.stdout


def test_delegation_schema_registry_exact_parity():
    """Generate all parent, scope, preparation, outcome and explicit budget schemas from models."""
    registry = runpy.run_path(str(ROOT / "scripts/generate_schemas.py"))["SCHEMAS"]
    names = {
        "fidelity_campaign_delegation_v01.schema.json",
        "fidelity_delegation_decision_v01.schema.json",
        "fidelity_delegation_scope_v01.schema.json",
        "fidelity_delegation_preparation_v01.schema.json",
        "fidelity_delegation_outcome_v01.schema.json",
        "autonomy_delegated_budget_v04.schema.json",
    }
    for name in names:
        assert (
            json.loads((ROOT / "schemas" / name).read_bytes()) == registry[name].model_json_schema()
        )
