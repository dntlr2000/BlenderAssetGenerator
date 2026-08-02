from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from codex_blender_modeler.material_manifest import load_material_manifest
from codex_blender_modeler.texturing import load_texture_manifest


def _schema_errors(payload: dict) -> list[str]:
    """Return checked-in texture-schema validation errors for one payload."""

    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "schemas" / "texture_manifest.schema.json").read_text(encoding="utf-8")
    )
    return [error.message for error in Draft202012Validator(schema).iter_errors(payload)]


def test_legacy_manifest_normalizes_to_v05_contract(tmp_path: Path) -> None:
    """A v0.4 manifest without a version loads as the v0.5 host contract."""

    path = tmp_path / "texture_manifest.json"
    path.write_text(
        json.dumps(
            {
                "material_id": "mat.test",
                "uv_set": "Object",
                "intended_scale_m": 2.0,
                "resolution": [128, 128],
                "source_type": "procedural",
                "channels": {"height": {"source": "procedural"}},
                "procedural": {"seed": 8},
            }
        ),
        encoding="utf-8",
    )

    manifest = load_texture_manifest(path)
    payload = manifest.model_dump(mode="json")
    assert manifest.schema_version == "0.5.0"
    assert not _schema_errors(payload)


def test_compatibility_facade_preserves_resolved_image_behavior(tmp_path: Path) -> None:
    """The original import path still resolves image files for Blender builds."""

    manifest_dir = tmp_path / "textures" / "mat.test"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "base.png").write_bytes(b"draft")
    relative = "textures/mat.test/texture_manifest.json"
    (tmp_path / relative).write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.test",
                "uv_set": "Object",
                "intended_scale_m": 1.0,
                "resolution": [64, 64],
                "source_type": "image",
                "channels": {
                    "base_color": {
                        "source": "image",
                        "path": "base.png",
                        "color_space": "sRGB",
                    }
                },
                "procedural": {},
            }
        ),
        encoding="utf-8",
    )

    manifest, _ = load_material_manifest(
        {"id": "mat.test", "texture_manifest": relative}, tmp_path
    )
    assert manifest is not None
    assert Path(manifest["channels"]["base_color"]["resolved_path"]).is_file()


def test_texture_contract_rejects_wrong_data_color_space(tmp_path: Path) -> None:
    """Data channels cannot be interpreted as display color."""

    path = tmp_path / "texture_manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.test",
                "uv_set": "Object",
                "intended_scale_m": 1.0,
                "resolution": [64, 64],
                "source_type": "image",
                "channels": {
                    "roughness": {
                        "source": "image",
                        "path": "roughness.png",
                        "color_space": "sRGB",
                    }
                },
                "procedural": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Non-Color"):
        load_texture_manifest(path)


def test_blender_spatial_sampling_is_non_repeating_and_auditable() -> None:
    """Keep spatial-v1 runtime sampling separate from legacy scaled-repeat manifests."""

    root = Path(__file__).resolve().parents[1]
    common = (
        root / "src" / "codex_blender_modeler" / "blender_scripts" / "common.py"
    ).read_text(encoding="utf-8")
    inspector = (
        root
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "inspect_materials.py"
    ).read_text(encoding="utf-8")

    assert 'image_extension = {"clip": "CLIP", "clamp": "EXTEND"}[wrap]' in common
    assert '"spatial_uv_identity" if spatial_mode else "legacy_scaled"' in common
    assert "if spatial_mode or procedural_uv_set is not None:" in common
    assert '"uv_set": procedural_uv_set or manifest["uv_set"]' in common
    assert '"cbm_spatial_bindings"' in common
    assert "vertex_uv_binding_fingerprint" in inspector
    assert "Spatial binding does not match the current parent UV layout" in inspector
    assert "load_material_manifest" in inspector
    assert 'node.bl_idname != "ShaderNodeTexImage"' in inspector
    assert 'mapping.bl_idname != "ShaderNodeMapping"' in inspector
    assert 'coordinates.bl_idname != "ShaderNodeUVMap"' in inspector
    assert 'getattr(coordinates, "uv_map", "")' in inspector
    assert 'item.get("material_id") == material_id' in inspector
    assert '"spatial_graph_evidence": graph_evidence' in inspector
    assert '"Location": (0.0, 0.0, 0.0)' in inspector
    assert '"Rotation": (0.0, 0.0, 0.0)' in inspector
    assert 'sha256_file(actual_path) != expected_channel["sha256"]' in inspector
    assert "_clear_material_provenance(material)" in common

    portable = (
        root
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "portable_asset_common.py"
    ).read_text(encoding="utf-8")
    assert '">Qddddd"' in portable
    assert "struct.pack(" in portable
    assert "vertex_uv_binding_fingerprint = binding_digest.hexdigest()" in portable
