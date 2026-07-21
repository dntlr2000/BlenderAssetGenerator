from pathlib import Path

from codex_blender_modeler.workspace import create_job, find_input_images, validate_job_id


def test_job_id() -> None:
    assert validate_job_id("floating_island-01") == "floating_island-01"


def test_multiview_job_outside_repo(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "external-workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace_root))

    reference = tmp_path / "reference.png"
    front = tmp_path / "front.png"
    top = tmp_path / "top.png"
    reference.write_bytes(b"reference")
    front.write_bytes(b"front")
    top.write_bytes(b"top")

    metadata = create_job(
        "measured_asset",
        reference,
        "measured",
        ["overall width = 2.4 m"],
        {"top": top, "front": front},
    )

    assert [source["kind"] for source in metadata["sources"]] == ["reference", "front", "top"]
    assert Path(metadata["reference_path"]).is_absolute()
    assert [path.stem for path in find_input_images("measured_asset")] == [
        "reference",
        "front",
        "top",
    ]
