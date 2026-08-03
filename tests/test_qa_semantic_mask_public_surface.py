from __future__ import annotations

import json
import runpy
import tomllib
from pathlib import Path
from types import SimpleNamespace

from typer.main import get_command
from typer.testing import CliRunner

import codex_blender_modeler.cli as cli_module
import codex_blender_modeler.mcp_server as mcp_module
from codex_blender_modeler.cli import app
from codex_blender_modeler.qa.semantic_mask_registry_models import (
    SemanticReferenceMaskPromotionReceipt,
    SemanticReferenceMaskRegistryStatus,
)

ROOT = Path(__file__).resolve().parents[1]


class _PublicResult:
    """Provide the Pydantic serialization surface used by CLI and MCP wrappers."""

    def __init__(self, payload: dict) -> None:
        """Retain one deterministic public result payload for wrapper assertions."""

        self.payload = payload

    def model_dump_json(self) -> str:
        """Serialize the captured payload for Rich CLI JSON output."""

        return json.dumps(self.payload)

    def model_dump(self, *, mode: str = "python") -> dict:
        """Return the captured payload through the MCP-compatible model surface."""

        assert mode in {"python", "json"}
        return self.payload


def _visual_qa_enabled() -> SimpleNamespace:
    """Return the smallest feature-config shape needed by public QA commands."""

    return SimpleNamespace(features=SimpleNamespace(visual_qa=True))


def test_semantic_mask_cli_commands_expose_exact_registration_controls() -> None:
    """Keep semantic-mask publication explicit and exact-hash-bound in the CLI."""

    commands = get_command(app).commands
    assert "qa-semantic-masks-register" in commands
    assert "qa-semantic-masks-status" in commands
    register_options = {
        option
        for parameter in commands["qa-semantic-masks-register"].params
        for option in getattr(parameter, "opts", [])
    }
    assert "--registration-id" in register_options
    assert "--manifest-sha256" in register_options


def test_semantic_mask_cli_delegates_to_safe_registry_services(monkeypatch) -> None:
    """Verify CLI wrappers forward exact identity without accepting arbitrary paths."""

    calls: list[tuple] = []

    def fake_register(job_id: str, registration_id: str, *, manifest_sha256: str):
        """Capture one exact registration request without touching a workspace."""

        calls.append(("register", job_id, registration_id, manifest_sha256))
        return _PublicResult({"status": "promoted", "registration_id": registration_id})

    def fake_status(job_id: str):
        """Return one read-only status payload without touching a workspace."""

        calls.append(("status", job_id))
        return _PublicResult({"status": "current", "job_id": job_id})

    monkeypatch.setattr(cli_module, "load_feature_config", _visual_qa_enabled)
    monkeypatch.setattr(cli_module, "register_job_semantic_reference_masks", fake_register)
    monkeypatch.setattr(
        cli_module,
        "get_job_semantic_reference_mask_status",
        fake_status,
    )
    exact_hash = "a" * 64
    runner = CliRunner()
    registered = runner.invoke(
        app,
        [
            "qa-semantic-masks-register",
            "asset-test",
            "--registration-id",
            "manual-001",
            "--manifest-sha256",
            exact_hash,
        ],
    )
    status = runner.invoke(app, ["qa-semantic-masks-status", "asset-test"])

    assert registered.exit_code == 0
    assert status.exit_code == 0
    assert calls == [
        ("register", "asset-test", "manual-001", exact_hash),
        ("status", "asset-test"),
    ]


def test_semantic_mask_mcp_tools_delegate_to_safe_registry_services(monkeypatch) -> None:
    """Verify MCP tools expose only exact promotion and read-only status operations."""

    calls: list[tuple] = []

    def fake_register(job_id: str, registration_id: str, *, manifest_sha256: str):
        """Capture one MCP registration request without changing canonical evidence."""

        calls.append(("register", job_id, registration_id, manifest_sha256))
        return _PublicResult({"ok": True, "registration_id": registration_id})

    def fake_status(job_id: str):
        """Return one MCP status payload without changing canonical evidence."""

        calls.append(("status", job_id))
        return _PublicResult({"ok": True, "job_id": job_id})

    monkeypatch.setattr(mcp_module, "load_feature_config", _visual_qa_enabled)
    monkeypatch.setattr(mcp_module, "register_job_semantic_reference_masks", fake_register)
    monkeypatch.setattr(
        mcp_module,
        "get_job_semantic_reference_mask_status",
        fake_status,
    )
    exact_hash = "b" * 64

    registered = mcp_module.register_semantic_reference_masks(
        "asset-test",
        "manual-002",
        exact_hash,
    )
    status = mcp_module.get_semantic_reference_mask_status("asset-test")

    assert registered == {"ok": True, "registration_id": "manual-002"}
    assert status == {"ok": True, "job_id": "asset-test"}
    assert calls == [
        ("register", "asset-test", "manual-002", exact_hash),
        ("status", "asset-test"),
    ]


def test_semantic_mask_mcp_tools_are_allowlisted() -> None:
    """Keep both semantic-mask tools inside the explicit project MCP allowlist."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert {
        "register_semantic_reference_masks",
        "get_semantic_reference_mask_status",
    } <= enabled


def test_semantic_mask_registry_models_are_exposed_to_schema_generation() -> None:
    """Require schema generation to publish both immutable receipt and status models."""

    schemas = runpy.run_path(str(ROOT / "scripts" / "generate_schemas.py"))["SCHEMAS"]
    assert schemas["semantic_reference_mask_promotion_receipt.schema.json"] is (
        SemanticReferenceMaskPromotionReceipt
    )
    assert schemas["semantic_reference_mask_registry_status.schema.json"] is (
        SemanticReferenceMaskRegistryStatus
    )
