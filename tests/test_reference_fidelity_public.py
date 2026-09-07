"""CLI/MCP/schema and disabled-experimental parity for the reference-fidelity companion."""

from __future__ import annotations

import json
import runpy
import tomllib
from pathlib import Path

from cli_help_support import assert_cli_help_contract
from typer.testing import CliRunner

from codex_blender_modeler import mcp_server
from codex_blender_modeler.cli import app
from codex_blender_modeler.reference_fidelity import reference_fidelity_capability

ROOT = Path(__file__).resolve().parents[1]
SURFACES = {
    "fidelity-evidence": "capture_reference_fidelity_evidence",
    "fidelity-evaluate": "evaluate_reference_fidelity",
    "fidelity-material-preflight": "preflight_directional_material",
    "fidelity-compare": "compare_reference_fidelity",
    "aq-quality-loop-bind": "bind_aq_quality_revision_loop",
    "aq-quality-attempt": "submit_aq_quality_attempt",
    "aq-quality-render": "render_aq_reference_fidelity",
    "aq-quality-supplement": "supplement_aq_quality_evidence",
    "aq-structural-reentry": "begin_aq_structural_reentry",
    "aq-quality-reentry": "begin_aq_quality_reentry",
}


def test_fidelity_public_surfaces_are_callable_allowlisted_and_documented() -> None:
    """Expose identical host actions through CLI/MCP and the exact AQ quality skill tools."""

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert_cli_help_contract(result.stdout, required=set(SURFACES))
    enabled = set(
        tomllib.loads((ROOT / ".codex/config.toml").read_text())["mcp_servers"]["blender_modeler"][
            "enabled_tools"
        ]
    )
    for command, name in SURFACES.items():
        assert runner.invoke(app, [command, "--help"]).exit_code == 0
        assert callable(getattr(mcp_server, name)) and name in enabled


def test_fidelity_companion_schemas_match_the_authoritative_generator() -> None:
    """Keep new companion versions separate from all unchanged canonical/legacy schemas."""

    registry = runpy.run_path(str(ROOT / "scripts/generate_schemas.py"))["SCHEMAS"]
    names = [
        name
        for name in registry
        if any(
            token in name
            for token in (
                "fidelity",
                "modeling_hypothesis",
                "quality_revision_loop",
                "quality_attempt_v01",
                "quality_render_reservation",
                "structural_reentry",
                "revision_cost_v01",
                "revision_ledger",
                "structure_authoring",
            )
        )
    ]
    assert len(names) >= 14
    for name in names:
        assert (
            json.loads((ROOT / "schemas" / name).read_text()) == registry[name].model_json_schema()
        )


def test_fidelity_capability_cannot_claim_activation_or_approval() -> None:
    """Keep experimental route support separate from human acceptance and campaign evidence."""

    capability = reference_fidelity_capability()
    assert capability["status"] == "disabled_experimental"
    assert capability["canonical_scene_spec"] == "0.2.0"
    assert capability["quality_revision_loop_versions"] == ["0.1.0", "0.2.0"]
    assert capability["quality_revision_routing"]["0.1.0"] == "legacy_strictest"
    assert capability["quality_revision_routing"]["0.2.0"] == "causal_v2"
    assert capability["automatic_migration"] is False
    assert capability["nonhuman_review_is_approval"] is False
    assert capability["new_campaign_visual_success_claimed"] is False
