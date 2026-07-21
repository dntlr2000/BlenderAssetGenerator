from pathlib import Path

from codex_blender_modeler.blender_artifacts import (
    artifact_path,
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
