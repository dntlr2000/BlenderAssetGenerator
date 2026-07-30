from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_blender_modeler.material_manifest import (
    MaterialManifestError,
    load_material_manifest,
)


def _write_manifest(root: Path, payload: dict) -> Path:
    """Write one test manifest and its referenced draft channels."""

    manifest_dir = root / "textures" / "mat.test"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "base.png").write_bytes(b"draft-base")
    (manifest_dir / "roughness.png").write_bytes(b"draft-roughness")
    path = manifest_dir / "texture_manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_payload() -> dict:
    """Return a minimal deterministic hybrid manifest payload."""

    return {
        "material_id": "mat.test",
        "uv_set": "Object",
        "intended_scale_m": 2.0,
        "resolution": [256, 256],
        "source_type": "hybrid",
        "channels": {
            "base_color": {
                "source": "image",
                "path": "base.png",
                "color_space": "sRGB",
            },
            "roughness": {
                "source": "image",
                "path": "roughness.png",
                "color_space": "Non-Color",
            },
            "height": {"source": "procedural"},
        },
        "procedural": {
            "seed": 17,
            "noise": {"scale": 3.0},
            "bump_strength": 0.2,
            "coordinate_uv_set": "Object",
            "coordinate_scale_m": 0.75,
        },
    }


def test_missing_manifest_preserves_legacy_material_behavior(tmp_path: Path) -> None:
    """A null manifest must keep existing SceneSpec materials valid."""

    manifest, path = load_material_manifest(
        {"id": "mat.test", "texture_manifest": None}, tmp_path
    )
    assert manifest is None
    assert path is None


def test_valid_hybrid_manifest_resolves_channels_and_color_spaces(tmp_path: Path) -> None:
    """A valid hybrid manifest resolves image paths within the job workspace."""

    path = _write_manifest(tmp_path, _valid_payload())
    manifest, resolved_path = load_material_manifest(
        {
            "id": "mat.test",
            "texture_manifest": "textures/mat.test/texture_manifest.json",
        },
        tmp_path,
    )
    assert resolved_path == path.resolve()
    assert manifest is not None
    assert manifest["channels"]["base_color"]["color_space"] == "sRGB"
    assert manifest["channels"]["roughness"]["color_space"] == "Non-Color"
    assert manifest["procedural"]["coordinate_uv_set"] == "Object"
    assert manifest["procedural"]["coordinate_scale_m"] == 0.75
    assert Path(manifest["channels"]["base_color"]["resolved_path"]).is_file()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("coordinate_uv_set", "World", "coordinate_uv_set"),
        ("coordinate_scale_m", 0.0, "coordinate_scale_m"),
        ("coordinate_scale_m", True, "coordinate_scale_m"),
    ],
)
def test_manifest_rejects_invalid_procedural_coordinate_override(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    """Reject unsupported hybrid procedural coordinates before Blender execution."""

    payload = _valid_payload()
    payload["procedural"][field] = value
    _write_manifest(tmp_path, payload)
    with pytest.raises(MaterialManifestError, match=message):
        load_material_manifest(
            {
                "id": "mat.test",
                "texture_manifest": "textures/mat.test/texture_manifest.json",
            },
            tmp_path,
        )


def test_manifest_rejects_material_id_mismatch(tmp_path: Path) -> None:
    """A manifest cannot silently target a different stable material ID."""

    payload = _valid_payload()
    payload["material_id"] = "mat.other"
    _write_manifest(tmp_path, payload)
    with pytest.raises(MaterialManifestError, match="material_id"):
        load_material_manifest(
            {
                "id": "mat.test",
                "texture_manifest": "textures/mat.test/texture_manifest.json",
            },
            tmp_path,
        )


def test_manifest_rejects_path_traversal(tmp_path: Path) -> None:
    """Manifest and channel paths must remain under the current job root."""

    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"outside")
    payload = _valid_payload()
    payload["channels"]["base_color"]["path"] = "../../../outside.png"
    _write_manifest(tmp_path, payload)
    with pytest.raises(MaterialManifestError, match="inside job root"):
        load_material_manifest(
            {
                "id": "mat.test",
                "texture_manifest": "textures/mat.test/texture_manifest.json",
            },
            tmp_path,
        )


def test_manifest_enforces_data_channel_color_space(tmp_path: Path) -> None:
    """Roughness and other data channels must remain Non-Color."""

    payload = _valid_payload()
    payload["channels"]["roughness"]["color_space"] = "sRGB"
    _write_manifest(tmp_path, payload)
    with pytest.raises(MaterialManifestError, match="Non-Color"):
        load_material_manifest(
            {
                "id": "mat.test",
                "texture_manifest": "textures/mat.test/texture_manifest.json",
            },
            tmp_path,
        )


def test_manifest_enforces_emission_as_srgb(tmp_path: Path) -> None:
    """Emission color maps use display color semantics, unlike scalar data channels."""

    payload = _valid_payload()
    manifest_dir = tmp_path / "textures" / "mat.test"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "base.png").write_bytes(b"draft-base")
    (manifest_dir / "roughness.png").write_bytes(b"draft-roughness")
    (manifest_dir / "emission.png").write_bytes(b"draft-emission")
    payload["channels"]["emission"] = {
        "source": "image",
        "path": "emission.png",
        "color_space": "sRGB",
    }
    path = manifest_dir / "texture_manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    manifest, _ = load_material_manifest(
        {"id": "mat.test", "texture_manifest": "textures/mat.test/texture_manifest.json"},
        tmp_path,
    )
    assert manifest is not None
    assert manifest["channels"]["emission"]["color_space"] == "sRGB"

    payload["channels"]["emission"]["color_space"] = "Non-Color"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MaterialManifestError, match="sRGB"):
        load_material_manifest(
            {
                "id": "mat.test",
                "texture_manifest": "textures/mat.test/texture_manifest.json",
            },
            tmp_path,
        )


def test_manifest_rejects_shared_file_with_mixed_color_spaces(tmp_path: Path) -> None:
    """One Blender image datablock cannot safely serve both color and data semantics."""

    payload = _valid_payload()
    payload["channels"]["roughness"]["path"] = "base.png"
    _write_manifest(tmp_path, payload)
    with pytest.raises(MaterialManifestError, match="conflicting color spaces"):
        load_material_manifest(
            {
                "id": "mat.test",
                "texture_manifest": "textures/mat.test/texture_manifest.json",
            },
            tmp_path,
        )


def test_manifest_rejects_future_version_and_source_composition_mismatch(
    tmp_path: Path,
) -> None:
    """Blender runtime never guesses how to consume a future or contradictory contract."""

    payload = _valid_payload()
    payload["schema_version"] = "9.0.0"
    path = _write_manifest(tmp_path, payload)
    with pytest.raises(MaterialManifestError, match="schema_version"):
        load_material_manifest(
            {
                "id": "mat.test",
                "texture_manifest": "textures/mat.test/texture_manifest.json",
            },
            tmp_path,
        )
    payload["schema_version"] = "0.5.0"
    payload["source_type"] = "image"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MaterialManifestError, match="source_type image"):
        load_material_manifest(
            {
                "id": "mat.test",
                "texture_manifest": "textures/mat.test/texture_manifest.json",
            },
            tmp_path,
        )


def test_manifest_rejects_unimplemented_procedural_channel(tmp_path: Path) -> None:
    """Future procedural channels fail preflight instead of becoming silent no-op nodes."""

    payload = _valid_payload()
    payload["channels"]["emission"] = {"source": "procedural"}
    _write_manifest(tmp_path, payload)
    with pytest.raises(MaterialManifestError, match="runtime subset"):
        load_material_manifest(
            {
                "id": "mat.test",
                "texture_manifest": "textures/mat.test/texture_manifest.json",
            },
            tmp_path,
        )
