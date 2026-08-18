"""Public, derived-only SceneSpec 0.2 to 0.3 migration tests."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest
from cli_help_support import assert_cli_help_contract
from typer.testing import CliRunner

from codex_blender_modeler import cli, mcp_server
from codex_blender_modeler.cli import app
from codex_blender_modeler.structural_geometry import migration_service
from codex_blender_modeler.structural_geometry.migration import (
    SceneSpecV03MigrationReceipt,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    """Return one exact test-file hash."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migration_job(tmp_path: Path) -> Path:
    """Create one isolated job containing only a valid canonical SceneSpec 0.2 source."""

    root = tmp_path / "migration_public_job"
    source = root / "analysis" / "scene_spec.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_bytes()
    )
    return root


def test_plan_and_apply_publish_only_run_owned_derived_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the canonical 0.2 source byte-identical while deriving exact 0.3 evidence."""

    root = _migration_job(tmp_path)
    source = root / "analysis" / "scene_spec.json"
    source_before = source.read_bytes()
    monkeypatch.setattr(migration_service, "job_dir", lambda _job_id: root)

    planned = migration_service.plan_scene_spec_v03_migration(
        "migration_public_job",
        "migration_001",
    )
    assert planned["status"] == "awaiting_exact_plan_hash"
    assert planned["canonical_source_mutated"] is False
    assert source.read_bytes() == source_before
    assert json.loads(source.read_text(encoding="utf-8"))["schema_version"] == "0.2.0"

    with pytest.raises(ValueError, match="plan SHA-256 does not match"):
        migration_service.apply_scene_spec_v03_migration(
            "migration_public_job",
            "migration_001",
            exact_plan_sha256="0" * 64,
        )
    assert not (root / "structural_migrations/migration_001/applied").exists()

    applied = migration_service.apply_scene_spec_v03_migration(
        "migration_public_job",
        "migration_001",
        exact_plan_sha256=planned["migration_plan_sha256"],
    )
    assert applied["status"] == "derived_candidate_applied"
    assert applied["canonical_source_mutated"] is False
    assert source.read_bytes() == source_before
    derived = root / applied["derived_scene_spec_path"]
    assert json.loads(derived.read_text(encoding="utf-8"))["schema_version"] == "0.3.0"
    receipt_path = root / applied["migration_receipt_path"]
    receipt = SceneSpecV03MigrationReceipt.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    assert receipt.migration_plan_file_sha256 == planned["migration_plan_sha256"]
    assert receipt.source_file_sha256 == _sha256(source)
    assert receipt.canonical_mutation_allowed is False

    with pytest.raises(FileExistsError, match="already been applied"):
        migration_service.apply_scene_spec_v03_migration(
            "migration_public_job",
            "migration_001",
            exact_plan_sha256=planned["migration_plan_sha256"],
        )


def test_apply_rejects_stale_source_and_tampered_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed when either exact migration input changes after planning."""

    root = _migration_job(tmp_path)
    source = root / "analysis" / "scene_spec.json"
    monkeypatch.setattr(migration_service, "job_dir", lambda _job_id: root)
    planned = migration_service.plan_scene_spec_v03_migration(
        "migration_public_job",
        "migration_stale",
    )
    source_payload = json.loads(source.read_text(encoding="utf-8"))
    source_payload["revision_notes"].append("stale canonical edit")
    source.write_text(json.dumps(source_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="source file no longer matches"):
        migration_service.apply_scene_spec_v03_migration(
            "migration_public_job",
            "migration_stale",
            exact_plan_sha256=planned["migration_plan_sha256"],
        )

    root = _migration_job(tmp_path / "candidate_case")
    monkeypatch.setattr(migration_service, "job_dir", lambda _job_id: root)
    planned = migration_service.plan_scene_spec_v03_migration(
        "migration_public_job",
        "migration_tampered",
    )
    candidate = root / planned["candidate_path"]
    candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
    candidate_payload["revision_notes"].append("tampered candidate")
    candidate.write_text(json.dumps(candidate_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate file no longer matches"):
        migration_service.apply_scene_spec_v03_migration(
            "migration_public_job",
            "migration_tampered",
            exact_plan_sha256=planned["migration_plan_sha256"],
        )


def test_migration_identifier_and_existing_run_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject path escapes and implicit overwrite of immutable migration runs."""

    root = _migration_job(tmp_path)
    monkeypatch.setattr(migration_service, "job_dir", lambda _job_id: root)
    with pytest.raises(ValueError, match="migration_id must match"):
        migration_service.plan_scene_spec_v03_migration(
            "migration_public_job",
            "../escape",
        )
    migration_service.plan_scene_spec_v03_migration(
        "migration_public_job",
        "migration_immutable",
    )
    with pytest.raises(FileExistsError, match="already exists"):
        migration_service.plan_scene_spec_v03_migration(
            "migration_public_job",
            "migration_immutable",
        )


def test_cli_and_mcp_expose_exact_hash_migration_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep CLI and MCP surfaces additive, exact-hash bound, and explicitly allowlisted."""

    planned = {
        "status": "awaiting_exact_plan_hash",
        "migration_plan_sha256": "a" * 64,
    }
    applied = {"status": "derived_candidate_applied"}
    monkeypatch.setattr(cli, "plan_scene_spec_v03_migration", lambda *_args: planned)
    monkeypatch.setattr(
        cli,
        "apply_scene_spec_v03_migration",
        lambda *_args, **_kwargs: applied,
    )
    runner = CliRunner()
    plan_result = runner.invoke(
        app,
        ["scene-spec-v03-migration-plan", "migration_public_job", "migration_cli"],
    )
    assert plan_result.exit_code == 0
    assert "awaiting_exact_plan_hash" in plan_result.stdout
    apply_help = runner.invoke(app, ["scene-spec-v03-migration-apply", "--help"])
    assert apply_help.exit_code == 0
    assert_cli_help_contract(apply_help.stdout, required=("--exact-plan-sha256",))

    monkeypatch.setattr(
        mcp_server,
        "plan_scene_spec_v03_migration_internal",
        lambda *_args: planned,
    )
    monkeypatch.setattr(
        mcp_server,
        "apply_scene_spec_v03_migration_internal",
        lambda *_args, **_kwargs: applied,
    )
    assert mcp_server.plan_scene_spec_v03_migration(
        "migration_public_job", "migration_mcp"
    ) == planned
    assert mcp_server.apply_scene_spec_v03_migration(
        "migration_public_job",
        "migration_mcp",
        "a" * 64,
    ) == applied

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        enabled = set(
            tomllib.load(handle)["mcp_servers"]["blender_modeler"]["enabled_tools"]
        )
    assert {
        "plan_scene_spec_v03_migration",
        "apply_scene_spec_v03_migration",
    } <= enabled
