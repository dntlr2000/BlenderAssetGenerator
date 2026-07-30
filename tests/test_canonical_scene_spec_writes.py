from __future__ import annotations

import json
from pathlib import Path

import pytest

import codex_blender_modeler.cli as cli
import codex_blender_modeler.mcp_server as mcp_server
from codex_blender_modeler.orchestration.locks import workflow_write_lock
from codex_blender_modeler.workspace import (
    canonical_scene_spec_write_lock,
    replace_scene_spec_if_current,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[1]


def _seed_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    job_id: str = "writer_asset",
) -> tuple[Path, Path, Path]:
    """Create one isolated canonical SceneSpec and a distinct validated candidate."""

    workspace = tmp_path / "workspaces"
    root = workspace / job_id
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    for relative in ("analysis", "history", "reports", "workflows"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "job.json").write_text(
        json.dumps({"job_id": job_id, "mode": "concept"}) + "\n",
        encoding="utf-8",
    )
    payload = json.loads(
        (
            ROOT
            / "examples"
            / "geometry_showcase"
            / "scene_spec.seed.json"
        ).read_text(encoding="utf-8")
    )
    payload["job_id"] = job_id
    current = root / "analysis" / "scene_spec.json"
    current.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    payload.setdefault("revision_notes", []).append("writer-lock candidate")
    candidate = root / "analysis" / "scene_spec.writer.next.json"
    candidate.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return root, current, candidate


def test_compare_replace_requires_exact_shared_job_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject canonical replacement when the caller owns no shared job writer lock."""

    _root, current, candidate = _seed_job(tmp_path, monkeypatch)
    before = sha256_file(current)

    with pytest.raises(RuntimeError, match="requires the shared job write lock"):
        replace_scene_spec_if_current(
            "writer_asset",
            candidate,
            expected_current_sha256=before,
            expected_candidate_sha256=sha256_file(candidate),
            lock_owner_id="cli-test-no-lock",
        )

    assert sha256_file(current) == before
    assert candidate.is_file()


def test_compare_replace_archives_exact_current_and_preserves_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archive and replace only while the exact current and candidate hashes match."""

    _root, current, candidate = _seed_job(tmp_path, monkeypatch)
    before = sha256_file(current)
    candidate_hash = sha256_file(candidate)
    owner = "cli-writer-test"

    with canonical_scene_spec_write_lock("writer_asset", owner):
        result = replace_scene_spec_if_current(
            "writer_asset",
            candidate,
            expected_current_sha256=before,
            expected_candidate_sha256=candidate_hash,
            lock_owner_id=owner,
        )

    archive = Path(str(result["archived_scene_spec"]))
    assert sha256_file(current) == candidate_hash
    assert sha256_file(archive) == before
    assert candidate.is_file()
    assert not list(current.parent.glob(".scene_spec.replace-*.json"))


def test_compare_replace_rejects_stale_current_under_owned_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed when canonical content changes after candidate generation."""

    _root, current, candidate = _seed_job(tmp_path, monkeypatch)
    expected = sha256_file(current)
    owner = "cli-stale-test"

    with canonical_scene_spec_write_lock("writer_asset", owner):
        current.write_text(current.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        changed = sha256_file(current)
        with pytest.raises(RuntimeError, match="changed before replacement"):
            replace_scene_spec_if_current(
                "writer_asset",
                candidate,
                expected_current_sha256=expected,
                expected_candidate_sha256=sha256_file(candidate),
                lock_owner_id=owner,
            )

    assert sha256_file(current) == changed
    assert candidate.is_file()


@pytest.mark.parametrize("surface", ["cli", "mcp"])
def test_active_convergence_style_lock_blocks_public_guarded_writer_before_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    """Keep CLI and MCP guarded writers from entering apply under another job owner."""

    root, current, _candidate = _seed_job(tmp_path, monkeypatch)
    (root / "analysis" / "revision_plan.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    called = False

    def fake_apply(*args, **kwargs):
        """Record any unsafe entry into revision application."""

        nonlocal called
        called = True
        raise AssertionError("guarded apply must not run while another writer owns the job")

    if surface == "cli":
        monkeypatch.setattr(cli, "apply_revision_plan", fake_apply)

        def invoke() -> object:
            """Invoke the public CLI writer."""

            return cli.apply_revision("writer_asset")

    else:
        monkeypatch.setattr(mcp_server, "apply_guarded_revision", fake_apply)

        def invoke() -> object:
            """Invoke the public MCP writer."""

            return mcp_server.apply_revision_plan("writer_asset")

    before = sha256_file(current)
    with workflow_write_lock(
        root,
        "writer_asset",
        "convergence-owner",
        ttl_seconds=60,
    ):
        with pytest.raises(RuntimeError, match="Another workflow owns the job write lock"):
            invoke()

    assert called is False
    assert sha256_file(current) == before
