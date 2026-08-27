"""Deterministic repository-summary and Git-blob hashing tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_generator():
    """Load the standalone summary generator as a test-local module."""

    path = ROOT / "scripts" / "generate_repository_summary.py"
    spec = importlib.util.spec_from_file_location("cbm_generate_repository_summary", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *arguments: str) -> None:
    """Run one deterministic Git fixture command."""

    subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_git_blob_policy_uses_index_lf_payload(tmp_path: Path) -> None:
    """Hash the canonical LF blob rather than platform working-tree CRLF bytes."""

    generator = _load_generator()
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (tmp_path / "REPOSITORY_TREE.txt").write_text("stale\n", encoding="utf-8")
    (tmp_path / "FILE_MANIFEST.sha256").write_text("stale\n", encoding="utf-8")
    (tmp_path / "sample.txt").write_bytes(b"one\r\ntwo\r\n")
    _git(tmp_path, "add", ".")

    entries = generator.git_index_entries(tmp_path)
    sample = next(entry for entry in entries if entry.path == "sample.txt")
    payload = generator.git_blob_bytes(tmp_path, sample.object_id)

    assert payload == b"one\ntwo\n"
    manifest = generator.render_file_manifest(tmp_path, entries, {})
    expected = generator.canonical_blob_sha256(payload).encode("ascii") + b"  sample.txt"
    assert expected in manifest
    assert b"FILE_MANIFEST.sha256" not in manifest


def test_raw_verification_log_whitespace_policy_is_byte_preserving_and_narrow(
    tmp_path: Path,
) -> None:
    """Preserve raw log bytes while keeping non-log evidence under whitespace checks."""

    generator = _load_generator()
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())

    log_path = (
        tmp_path
        / "verification"
        / "evidence"
        / "fixture"
        / "logs"
        / "terminal.txt"
    )
    log_path.parent.mkdir(parents=True)
    raw_log = b"terminal output with spaces   \r\nnext line\r\n"
    log_path.write_bytes(raw_log)
    _git(tmp_path, "add", ".gitattributes", log_path.relative_to(tmp_path).as_posix())
    _git(tmp_path, "diff", "--cached", "--check")

    entries = generator.git_index_entries(tmp_path)
    log_relative_path = log_path.relative_to(tmp_path).as_posix()
    log_entry = next(entry for entry in entries if entry.path == log_relative_path)
    assert generator.git_blob_bytes(tmp_path, log_entry.object_id) == raw_log

    evidence_path = tmp_path / "verification" / "evidence" / "fixture" / "README.md"
    evidence_path.write_bytes(b"non-log evidence with spaces   \n")
    _git(tmp_path, "add", evidence_path.relative_to(tmp_path).as_posix())
    result = subprocess.run(
        ["git", "diff", "--cached", "--check"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "verification/evidence/fixture/README.md" in result.stdout


def test_readme_markers_are_replaced_deterministically() -> None:
    """Replace one generated block without duplicating markers or surrounding text."""

    generator = _load_generator()
    original = (
        b"# Readme\n\n"
        + generator.README_START.encode()
        + b"\nold\n"
        + generator.README_END.encode()
        + b"\n\nTail\n"
    )
    block = generator.README_START + "\nnew\n" + generator.README_END

    first = generator.replace_readme_block(original, block)
    second = generator.replace_readme_block(first, block)

    assert first == second
    assert first.count(generator.README_START.encode()) == 1
    assert b"Tail" in first


def test_drift_comparison_is_read_only(tmp_path: Path) -> None:
    """Report exact byte drift without modifying an existing generated file."""

    generator = _load_generator()
    target = tmp_path / "README.md"
    target.write_bytes(b"before\n")
    before = target.read_bytes()

    findings = generator.compare_repository_outputs(
        tmp_path,
        {"README.md": b"after\n", "REPOSITORY_TREE.txt": b"tree\n"},
    )

    assert findings == (
        "generated file drift: README.md",
        "missing generated file: REPOSITORY_TREE.txt",
    )
    assert target.read_bytes() == before


def test_current_summary_builds_without_blender() -> None:
    """Build current catalog JSON while verification evidence remains explicit."""

    generator = _load_generator()
    summary = generator.build_repository_summary(ROOT)

    assert summary["catalog"]["catalog_findings"] == []
    assert summary["verification"]["status"] in {"unavailable", "reported", "passed"}
    assert summary["hash_policy"]["payload_source"] == "git_blob"


def test_verification_summary_path_must_remain_contained(tmp_path: Path) -> None:
    """Reject absolute or escaping verification evidence paths."""

    generator = _load_generator()
    with pytest.raises(ValueError, match="repository-relative|escapes"):
        generator.load_verification_summary(tmp_path, "../outside.json")


def test_nested_verification_evidence_roots_must_be_portable(tmp_path: Path) -> None:
    """Reject missing or absolute gate evidence roots before generating repository claims."""

    generator = _load_generator()
    verification = tmp_path / "verification"
    verification.mkdir()
    summary = {
        "status": "passed",
        "test_count": 1,
        "tested_platforms": [],
        "quality_gates": {"focused": {"evidence_root": str(tmp_path.resolve())}},
    }
    summary_path = verification / "latest_summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(ValueError, match="repository-relative"):
        generator.load_verification_summary(tmp_path, "verification/latest_summary.json")

    summary["quality_gates"]["focused"]["evidence_root"] = "verification/evidence/focused"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="does not exist"):
        generator.load_verification_summary(tmp_path, "verification/latest_summary.json")

    (verification / "evidence" / "focused").mkdir(parents=True)
    loaded = generator.load_verification_summary(
        tmp_path,
        "verification/latest_summary.json",
    )
    assert loaded["status"] == "passed"
