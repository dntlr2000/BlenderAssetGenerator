"""Regression fixtures for grayscale height misrouted into a GLB normal slot."""

import hashlib
import importlib.util
import io
import json
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

PATH = Path(__file__).resolve().parents[1] / "scripts/audit_glb_texture_semantics.py"
SPEC = importlib.util.spec_from_file_location("normal_audit", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def image_bytes(pixels):
    """Encode a tiny real PNG fixture with exact supplied pixel-channel semantics."""
    stream = io.BytesIO()
    Image.fromarray(np.asarray(pixels, dtype=np.uint8)).save(stream, format="PNG")
    return stream.getvalue()


def glb_fixture(png, image_name="normal.png"):
    """Wrap a real image in the glTF material normalTexture binding path."""
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(png)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(png)}],
        "images": [{"bufferView": 0, "mimeType": "image/png", "name": image_name}],
        "textures": [{"source": 0}],
        "materials": [{"name": "material", "normalTexture": {"index": 0}}],
    }
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    binary = png + b"\0" * (-len(png) % 4)
    return (
        struct.pack("<4sII", b"glTF", 2, 28 + len(text) + len(binary))
        + struct.pack("<II", len(text), 0x4E4F534A)
        + text
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def test_grayscale_height_named_normal_is_rejected(tmp_path):
    """A reassuring filename cannot turn height samples into valid tangent normals."""
    path = tmp_path / "bad.glb"
    path.write_bytes(glb_fixture(image_bytes([[68, 127], [140, 150]])))
    result = MODULE.audit_glb(path)
    assert not result["passed"]
    assert "NORMAL_MAP_NOT_RGB_CHANNEL_DATA" in result["materials"][0]["findings"]
    assert "NORMAL_MAP_NONUNIT_VECTOR_FIELD" in result["materials"][0]["findings"]


def test_rgb_replicated_height_is_still_rejected(tmp_path):
    """Replicating grayscale into RGB does not cure the channel-semantic failure."""
    height = np.repeat(np.array([[68, 127], [140, 150]])[..., None], 3, axis=-1)
    path = tmp_path / "bad.glb"
    path.write_bytes(glb_fixture(image_bytes(height)))
    result = MODULE.audit_glb(path)
    assert not result["passed"]
    assert "NORMAL_MAP_ACHROMATIC_HEIGHT_LIKE_FIELD" in result["materials"][0]["findings"]


def test_correct_tangent_normal_named_height_passes(tmp_path):
    """Actual RGB tangent pixels determine semantics independently of a legacy name."""
    png = image_bytes([[[128, 128, 255], [140, 130, 254]]])
    path = tmp_path / "good.glb"
    path.write_bytes(glb_fixture(png, image_name="height.png"))
    assert MODULE.audit_glb(path)["passed"]


def test_exact_expected_normal_binding_detects_valid_wrong_image(tmp_path):
    """A different valid-looking normal field cannot pass expected channel identity."""
    expected = tmp_path / "expected.png"
    expected.write_bytes(image_bytes([[[128, 128, 255]]]))
    path = tmp_path / "wrong.glb"
    path.write_bytes(glb_fixture(image_bytes([[[150, 128, 253]]])))
    result = MODULE.audit_glb(
        path,
        {
            "material": {
                "path": str(expected),
                "sha256": hashlib.sha256(expected.read_bytes()).hexdigest(),
            }
        },
    )
    assert not result["passed"]
    assert "EXPORTED_NORMAL_CHANNEL_DIFFERS_FROM_EXPECTED" in result["materials"][0]["findings"]


def test_exact_expected_normal_binding_passes(tmp_path):
    """Export re-encoding may differ but exact decoded RGB channel data must survive."""
    png = image_bytes([[[128, 128, 255], [140, 130, 254]]])
    expected = tmp_path / "expected.png"
    expected.write_bytes(png)
    path = tmp_path / "good.glb"
    path.write_bytes(glb_fixture(png))
    assert MODULE.audit_glb(
        path, {"material": {"path": str(expected), "sha256": hashlib.sha256(png).hexdigest()}}
    )["passed"]


def test_stale_expected_map_hash_fails_closed(tmp_path):
    """Source map replacement requires a new explicit expected-channel binding."""
    png = image_bytes([[[128, 128, 255]]])
    expected = tmp_path / "expected.png"
    expected.write_bytes(png)
    path = tmp_path / "good.glb"
    path.write_bytes(glb_fixture(png))
    with pytest.raises(ValueError, match="stale"):
        MODULE.audit_glb(path, {"material": {"path": str(expected), "sha256": "0" * 64}})


@pytest.mark.parametrize("bad", [b"", b"glTF", struct.pack("<4sII", b"glTF", 2, 12), b"\0" * 28])
def test_invalid_glb_container_fails_closed(bad):
    """Truncated or malformed containers cannot produce a semantic pass."""
    with pytest.raises(ValueError):
        MODULE.parse_glb(bad)


@pytest.mark.parametrize("index", [-1, 1, 0.0, True, "0", None])
def test_invalid_reference_indices_fail_closed(index):
    """Malformed references cannot exploit Python negative indexing or coercion."""
    with pytest.raises(ValueError):
        MODULE.indexed([{}], index, "fixture")
