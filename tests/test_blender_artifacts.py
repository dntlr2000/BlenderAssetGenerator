import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from codex_blender_modeler.blender_artifacts import (
    artifact_path,
    publish_bytes_create_once,
    rgb_hex,
    safe_artifact_name,
    stable_json_digest,
    unique_color_map,
    write_json_atomic,
)


def test_safe_artifact_name_preserves_semantic_id_components() -> None:
    """Portable artifact names retain readable semantic ID punctuation."""

    assert safe_artifact_name(" mat:rock / cliff ") == "mat_rock_cliff"
    assert safe_artifact_name("...") == "unnamed"


def test_unique_color_map_is_deterministic_and_collision_free() -> None:
    """ID pass colors remain stable regardless of input ordering and duplicates."""

    first = unique_color_map(["asset.b", "asset.a", "asset.a"])
    second = unique_color_map(["asset.a", "asset.b"])
    assert first == second
    assert len(set(first.values())) == 2
    assert all(len(rgb_hex(color)) == 7 for color in first.values())


def test_stable_json_digest_ignores_mapping_key_order() -> None:
    """QA run fingerprints use canonical JSON ordering."""

    assert stable_json_digest({"b": 2, "a": 1}) == stable_json_digest({"a": 1, "b": 2})


def test_atomic_json_and_relative_artifact_path(tmp_path: Path) -> None:
    """Generated reports are complete JSON files with portable relative paths."""

    manifest = tmp_path / "qa" / "manifest.json"
    image = tmp_path / "qa" / "passes" / "beauty.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")
    write_json_atomic(manifest, {"ok": True})
    assert manifest.read_text(encoding="utf-8").endswith("\n")
    assert artifact_path(image, manifest) == "passes/beauty.png"


def test_immutable_create_once_allows_only_one_distinct_payload_writer(
    tmp_path: Path,
) -> None:
    """Synchronize distinct writers and retain exactly one complete immutable winner."""

    destination = tmp_path / "immutable.json"
    payloads = [f'{{"writer":{index}}}\n'.encode() for index in range(8)]
    barrier = Barrier(len(payloads))

    def publish(content: bytes) -> tuple[str, bytes]:
        """Release one competing publisher at the shared test barrier."""

        barrier.wait()
        try:
            created = publish_bytes_create_once(destination, content)
        except FileExistsError:
            return "conflict", content
        return "created" if created else "adopted", content

    with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
        results = list(executor.map(publish, payloads))
    assert [status for status, _content in results].count("created") == 1
    assert [status for status, _content in results].count("conflict") == 7
    winner = next(content for status, content in results if status == "created")
    assert destination.read_bytes() == winner


def test_immutable_create_once_concurrently_exact_adopts_same_payload(
    tmp_path: Path,
) -> None:
    """Synchronize identical writers so one creates and every peer exact-adopts."""

    destination = tmp_path / "immutable.json"
    content = b'{"same":true}\n'
    barrier = Barrier(8)

    def publish(_index: int) -> bool:
        """Release one identical publisher at the shared test barrier."""

        barrier.wait()
        return publish_bytes_create_once(destination, content)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(publish, range(8)))
    assert results.count(True) == 1
    assert results.count(False) == 7
    assert destination.read_bytes() == content


def test_immutable_create_once_never_changes_preexisting_bytes(tmp_path: Path) -> None:
    """Exact-adopt matching pre-existing bytes and reject a conflicting replacement."""

    destination = tmp_path / "immutable.json"
    original = b'{"original":true}\n'
    destination.write_bytes(original)
    assert publish_bytes_create_once(destination, original) is False
    with pytest.raises(FileExistsError, match="conflicting immutable artifact bytes"):
        publish_bytes_create_once(destination, b'{"replacement":true}\n')
    assert destination.read_bytes() == original


def test_immutable_create_once_never_exposes_failed_partial_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the final path absent when writing the private complete-bytes temp fails."""

    destination = tmp_path / "immutable.json"

    def fail_write(_descriptor: int, _content: object) -> int:
        """Simulate a host write failure before atomic no-replace publication."""

        raise OSError("simulated write failure")

    monkeypatch.setattr("codex_blender_modeler.blender_artifacts.os.write", fail_write)
    with pytest.raises(OSError, match="simulated write failure"):
        publish_bytes_create_once(destination, b'{"complete":true}\n')
    assert not destination.exists()
    assert list(tmp_path.glob(".*.immutable.tmp")) == []


def _create_symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    """Create one test link or skip where the host forbids unprivileged symlinks."""

    try:
        os.symlink(target, link, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"host cannot create the required symlink fixture: {exc}")


def test_immutable_create_once_rejects_existing_final_symlink(tmp_path: Path) -> None:
    """Reject a linked final leaf without modifying its target bytes."""

    target = tmp_path / "target.json"
    target.write_bytes(b'{}\n')
    destination = tmp_path / "immutable.json"
    _create_symlink_or_skip(destination, target, directory=False)

    with pytest.raises(FileExistsError, match="symlink or reparse point"):
        publish_bytes_create_once(destination, b'{"replacement":true}\n')
    assert target.read_bytes() == b'{}\n'


def test_immutable_create_once_rejects_dangling_final_symlink(tmp_path: Path) -> None:
    """Detect a dangling final link lexically instead of resolving through its target."""

    destination = tmp_path / "immutable.json"
    _create_symlink_or_skip(destination, tmp_path / "missing.json", directory=False)

    with pytest.raises(FileExistsError, match="symlink or reparse point"):
        publish_bytes_create_once(destination, b'{"replacement":true}\n')
    assert destination.is_symlink()


def test_immutable_create_once_rejects_linked_parent(tmp_path: Path) -> None:
    """Reject a linked parent before creating a temp or final file through it."""

    target_parent = tmp_path / "target"
    target_parent.mkdir()
    linked_parent = tmp_path / "linked"
    _create_symlink_or_skip(linked_parent, target_parent, directory=True)

    with pytest.raises(ValueError, match="ancestor is a symlink or reparse point"):
        publish_bytes_create_once(linked_parent / "immutable.json", b'{}\n')
    assert list(target_parent.iterdir()) == []


@pytest.mark.skipif(
    not hasattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT"),
    reason="Windows reparse attributes are unavailable on this host",
)
def test_immutable_create_once_rejects_parent_reparse_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject Windows parent reparse metadata without requiring symlink privileges."""

    parent = tmp_path / "parent"
    parent.mkdir()
    destination = parent / "immutable.json"
    real_lstat = os.lstat

    def report_parent_reparse(path: str | bytes) -> os.stat_result | SimpleNamespace:
        """Project the real parent directory metadata with the reparse flag set."""

        metadata = real_lstat(path)
        if Path(path).name == parent.name:
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return metadata

    monkeypatch.setattr(
        "codex_blender_modeler.blender_artifacts.os.lstat",
        report_parent_reparse,
    )
    with pytest.raises(ValueError, match="ancestor is a symlink or reparse point"):
        publish_bytes_create_once(destination, b'{}\n')
    assert not destination.exists()
