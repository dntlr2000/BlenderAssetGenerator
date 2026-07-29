from pathlib import Path

import pytest

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


def test_job_records_explicit_primary_object_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Persist one object-only choice and require an explicit subject description."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    reference = tmp_path / "car.png"
    reference.write_bytes(b"reference")

    with pytest.raises(ValueError, match="target_subject"):
        create_job(
            "missing_subject",
            reference,
            "concept",
            [],
            reference_content_scope="primary_object_only",
        )

    metadata = create_job(
        "car_only",
        reference,
        "concept",
        [],
        reference_content_scope="primary_object_only",
        target_subject="the central car",
    )
    assert metadata["reference_content_scope"] == "primary_object_only"
    assert metadata["target_subject"] == "the central car"
