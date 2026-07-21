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
