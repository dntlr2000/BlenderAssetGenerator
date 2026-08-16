from __future__ import annotations

from pathlib import Path

import pytest

from codex_blender_modeler.workspace import add_job_view, create_job, load_job


def test_duplicate_job_is_rejected_without_mutation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    first = tmp_path / "first.png"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    create_job("asset_001", first, "concept", [])
    job_json = tmp_path / "workspaces" / "asset_001" / "job.json"
    before = job_json.read_bytes()

    with pytest.raises(FileExistsError):
        create_job("asset_001", second, "concept", [])

    assert job_json.read_bytes() == before
    assert not (tmp_path / "workspaces" / "asset_001" / "input" / "reference.jpg").exists()


def test_create_job_retries_transient_atomic_directory_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry a transient Windows-style publication denial without changing staged bytes."""

    from codex_blender_modeler import workspace

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference")
    original_replace = workspace.os.replace
    attempts = 0

    def transient_replace(source: Path, destination: Path) -> None:
        """Fail the first exact publication attempt and delegate the bounded retry."""

        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("simulated transient directory publication denial")
        original_replace(source, destination)

    monkeypatch.setattr(workspace.os, "replace", transient_replace)
    monkeypatch.setattr(workspace, "sleep", lambda _seconds: None)

    metadata = workspace.create_job("retry_asset", reference, "concept", [])

    assert attempts == 2
    assert metadata["reference_sha256"] == workspace.sha256_file(reference)
    assert (tmp_path / "workspaces" / "retry_asset" / "job.json").is_file()


def test_create_job_exhausts_atomic_directory_retry_without_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed after the bounded retry count and remove only the private staging tree."""

    from codex_blender_modeler import workspace

    workspace_root = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace_root))
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference")
    attempts = 0

    def denied_replace(_source: Path, _destination: Path) -> None:
        """Keep the exact atomic publication unavailable for every bounded attempt."""

        nonlocal attempts
        attempts += 1
        raise PermissionError("simulated persistent directory publication denial")

    monkeypatch.setattr(workspace.os, "replace", denied_replace)
    monkeypatch.setattr(workspace, "sleep", lambda _seconds: None)

    with pytest.raises(PermissionError, match="persistent directory publication"):
        workspace.create_job("blocked_asset", reference, "concept", [])

    assert attempts == 3
    assert not (workspace_root / "blocked_asset").exists()
    assert not list(workspace_root.glob(".blocked_asset.creating-*"))


def test_add_view_requires_explicit_replace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    reference = tmp_path / "reference.png"
    front_a = tmp_path / "front_a.png"
    front_b = tmp_path / "front_b.jpg"
    reference.write_bytes(b"reference")
    front_a.write_bytes(b"front-a")
    front_b.write_bytes(b"front-b")
    create_job("measured_001", reference, "measured", [])
    add_job_view("measured_001", "front", front_a)

    with pytest.raises(FileExistsError):
        add_job_view("measured_001", "front", front_b)

    result = add_job_view("measured_001", "front", front_b, replace=True)
    assert result["archived"]
    assert [source["kind"] for source in load_job("measured_001")["sources"]] == [
        "reference",
        "front",
    ]
    input_dir = tmp_path / "workspaces" / "measured_001" / "input"
    assert not (input_dir / "front.png").exists()
    assert (input_dir / "front.jpg").exists()


def test_bundled_example_ids_are_reserved(tmp_path, monkeypatch):
    from codex_blender_modeler import workspace
    from codex_blender_modeler.config import Settings

    source = tmp_path / "reference.png"
    source.write_bytes(b"png")
    monkeypatch.setattr(
        workspace,
        "get_settings",
        lambda: Settings(tmp_path, tmp_path / "workspaces", "blender", "codex", 900),
    )
    for job_id in (
        "floating_island",
        "geometry_showcase",
        "measured_box",
        "first_reference_test",
    ):
        with pytest.raises(ValueError, match="reserved"):
            workspace.create_job(job_id, source, "concept", [])
