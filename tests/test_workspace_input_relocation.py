"""Relocated immutable inputs retain exact identity and hashes across host path styles."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from codex_blender_modeler import config
from codex_blender_modeler.workspace import (
    create_job,
    find_input_images,
    find_reference,
    resolve_job_input_path,
    resolve_metadata_path,
    sha256_file,
)


def _relocated_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locator: str):
    """Make one isolated historical metadata fixture with a real contained image."""
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(config, "REPO_ROOT", repository)
    workspace = tmp_path / "copied-workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    image = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "blue").save(image)
    metadata = create_job("asset", image, "concept", [])
    metadata["reference_path"] = locator
    metadata["sources"][0]["path"] = locator
    root = workspace / "asset"
    path = root / "job.json"
    path.write_text(json.dumps(metadata))
    return root, metadata, path.read_bytes()


@pytest.mark.parametrize("locator", [
    r"workspaces\asset\input\reference.png",
    "workspaces/asset/input/reference.png",
    r"E:\OldRepository\workspaces\asset\input\reference.png",
    "/old-repository/workspaces/asset/input/reference.png",
    "input/reference.png",
])
def test_exact_hashed_input_relocation_is_read_only(tmp_path, monkeypatch, locator):
    """Use the chosen workspace without rewriting historical locators or metadata."""
    root, metadata, before = _relocated_job(tmp_path, monkeypatch, locator)
    expected = root / "input/reference.png"
    assert find_reference("asset") == expected
    assert find_input_images("asset") == [expected]
    assert sha256_file(expected) == metadata["reference_sha256"]
    assert (root / "job.json").read_bytes() == before
    assert resolve_metadata_path(locator) != expected


@pytest.mark.parametrize("locator", [
    r"workspaces\other\input\reference.png",
    "workspaces/asset/input/../reference.png",
    "workspaces/asset/input/./reference.png",
    "workspaces/asset//input/reference.png",
    "asset/input/asset/input/reference.png",
    "unrelated/reference.png",
])
def test_relocation_rejects_foreign_or_ambiguous_paths(tmp_path, monkeypatch, locator):
    """Content equality cannot grant another job or unsafe path ownership."""
    root, metadata, before = _relocated_job(tmp_path, monkeypatch, locator)
    with pytest.raises((ValueError, FileNotFoundError)):
        find_reference("asset")
    assert (root / "job.json").read_bytes() == before


@pytest.mark.parametrize("expected", [None, "", "0" * 64, "malformed"])
def test_relocation_requires_exact_immutable_hash(tmp_path, monkeypatch, expected):
    """Reject absent, malformed and stale hashes without falling back to a guessed file."""
    root, _, _ = _relocated_job(tmp_path, monkeypatch, r"workspaces\asset\input\reference.png")
    with pytest.raises((ValueError, FileNotFoundError)):
        resolve_job_input_path(root, r"workspaces\asset\input\reference.png", expected)


def test_relocation_rejects_input_symlink(tmp_path, monkeypatch):
    """Reject a matching-byte link even when it resolves inside the owning input folder."""
    root, metadata, _ = _relocated_job(
        tmp_path, monkeypatch, r"workspaces\asset\input\reference.png"
    )
    original = root / "input/reference.png"
    target = root / "input/same.png"
    original.rename(target)
    original.symlink_to(target)
    with pytest.raises(ValueError, match="immutable input"):
        find_reference("asset")


def test_analysis_report_mask_and_multiview_use_relocated_input(tmp_path, monkeypatch):
    """Cover all read-only input consumers while retaining their own strict validations."""
    from codex_blender_modeler.analysis.pipeline import analyze_job_reference
    from codex_blender_modeler.qa.multiview_sanity import _reference_sources
    from codex_blender_modeler.qa.semantic_mask_registry import _primary_reference
    from codex_blender_modeler.reporting.service import _resolve_reference
    from codex_blender_modeler.stabilization.service import _resolve_source_path

    root, metadata, before = _relocated_job(
        tmp_path, monkeypatch, r"workspaces\asset\input\reference.png"
    )
    expected = root / "input/reference.png"
    warnings = []
    assert _resolve_reference(metadata, root, warnings) == expected
    assert not warnings
    assert _primary_reference(root, "asset")[0] == expected
    assert _reference_sources(root, metadata)[0].sha256 == metadata["reference_sha256"]
    assert _resolve_source_path(metadata["reference_path"], job_root=root,
                                expected_sha256=metadata["reference_sha256"]) == expected
    analyze_job_reference("asset", provider="basic")
    assert (root / "job.json").read_bytes() == before


def test_reporting_relocation_failure_does_not_disclose_host_path(tmp_path, monkeypatch):
    """Keep rejected reference locators out of persisted report warnings."""
    from codex_blender_modeler.reporting.service import _resolve_reference

    root, metadata, _ = _relocated_job(
        tmp_path, monkeypatch, r"workspaces\asset\input\reference.png"
    )
    (root / "input/reference.png").write_bytes(b"changed")
    warnings = []
    assert _resolve_reference(metadata, root, warnings) is None
    assert warnings == ["Skipped unavailable or invalid immutable reference evidence."]
    assert str(tmp_path) not in str(warnings)


def test_native_contained_input_checks_supplied_hash(tmp_path, monkeypatch):
    """A native spelling cannot skip the hash required by its metadata record."""
    root, metadata, _ = _relocated_job(
        tmp_path, monkeypatch, r"workspaces\asset\input\reference.png"
    )
    path = root / "input/reference.png"
    with pytest.raises(ValueError, match="hash changed"):
        resolve_job_input_path(root, str(path), "0" * 64)
    assert resolve_job_input_path(root, str(path), metadata["reference_sha256"]) == path
    assert resolve_job_input_path(root, str(path), None) == path


def test_relocation_rejects_linked_owner_root(tmp_path, monkeypatch):
    """A copied job name cannot legitimize an input under a redirected owner."""
    root, metadata, _ = _relocated_job(
        tmp_path, monkeypatch, r"workspaces\asset\input\reference.png"
    )
    owner = root.with_name("foreign_owner")
    root.rename(owner)
    root.symlink_to(owner, target_is_directory=True)
    with pytest.raises(ValueError, match="owning root"):
        resolve_job_input_path(root, metadata["reference_path"], metadata["reference_sha256"])


def test_audit_does_not_restore_rejected_path(tmp_path, monkeypatch):
    """Preserve an unsafe-path rejection instead of retrying generic metadata resolution."""
    from codex_blender_modeler.stabilization.service import _resolve_source_path

    root, metadata, _ = _relocated_job(
        tmp_path, monkeypatch, r"workspaces\asset\input\reference.png"
    )
    with pytest.raises(ValueError, match="unsafe component"):
        _resolve_source_path(
            str(root / "input/../input/reference.png"),
            job_root=root,
            expected_sha256=metadata["reference_sha256"],
        )


def test_input_link_detection_includes_windows_reparse_metadata(tmp_path, monkeypatch):
    """Treat a Windows reparse attribute as link-like even without isjunction support."""
    from types import SimpleNamespace

    from codex_blender_modeler import workspace

    monkeypatch.setattr(workspace.os.path, "islink", lambda _path: False)
    monkeypatch.setattr(workspace.os.path, "isjunction", lambda _path: False, raising=False)
    monkeypatch.setattr(
        workspace.os, "lstat", lambda _path: SimpleNamespace(st_file_attributes=0x400)
    )
    assert workspace._input_path_is_link_like(tmp_path / "junction")
