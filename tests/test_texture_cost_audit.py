"""Keep exact file cost separate from declared texture resolution and engine estimates."""

import hashlib
import json
import struct
import zlib

import pytest

from codex_blender_modeler.packaging.texture_cost_audit import inspect_glb_texture_cost


def png_header(width, height):
    """Build a CRC-valid IHDR fixture; the audit explicitly does not decode pixels."""
    body = b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + body + struct.pack(">I", zlib.crc32(body))


def glb(image, mutate=None):
    """Construct a tiny embedded GLB with independent JSON and BIN padding."""
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(image)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(image)}],
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
    }
    if mutate:
        mutate(document)
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary = image + b"\0" * (-len(image) % 4)
    result = struct.pack("<III", 0x46546C67, 2, 28 + len(encoded) + len(binary))
    result += struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    return result + struct.pack("<II", len(binary), 0x004E4942) + binary


def audit(data):
    """Bind each fixture to its exact independently computed bytes."""
    return inspect_glb_texture_cost(data, expected_sha256=hashlib.sha256(data).hexdigest())


def test_declared_2048_profile_has_four_times_base_texels():
    """Equal encoded fixture size does not imply equal estimated GPU allocation."""
    low, high = audit(glb(png_header(1024, 1024))), audit(glb(png_header(2048, 2048)))
    assert high["encoded_image_bytes_by_index"] == low["encoded_image_bytes_by_index"] == 33
    assert high["rgba8_base_bytes_estimate"] == 4 * low["rgba8_base_bytes_estimate"]
    assert high["rgba8_full_mip_bytes_estimate"] == 4 * low["rgba8_full_mip_bytes_estimate"] + 4
    assert high["pixels_decoded"] is False
    assert high["actual_engine_memory_verified"] is False
    assert high["visual_quality_verified"] is False


def test_nonsquare_mip_chain_is_exact():
    """Rectangular chains clamp each side to one instead of using a blanket 4/3."""
    result = audit(glb(png_header(3, 5)))
    assert result["rgba8_full_mip_bytes_estimate"] == (15 + 2 + 1) * 4


def test_duplicate_image_indices_have_separate_declared_resource_estimates():
    """Deduplication is disclosed separately and is never silently assumed for a GPU."""
    data = glb(png_header(4, 4), lambda d: d["images"].append(dict(d["images"][0])))
    result = audit(data)
    assert result["serialized_image_count"] == 2
    assert result["distinct_encoded_image_count"] == 1
    assert result["encoded_image_bytes_by_index"] == 66
    assert result["distinct_encoded_image_bytes"] == 33
    assert result["rgba8_base_bytes_estimate"] == 128


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["images"][0].update(uri="https://example.invalid/image.png"),
        lambda d: d["images"][0].update(mimeType="image/jpeg"),
        lambda d: d["images"][0].update(bufferView=-1),
        lambda d: d["images"][0].update(bufferView=True),
        lambda d: d["bufferViews"][0].update(byteOffset=999),
        lambda d: d["bufferViews"][0].update(byteLength=999),
        lambda d: d["bufferViews"][0].update(buffer=True),
        lambda d: d["buffers"][0].update(uri="elsewhere.bin"),
    ],
)
def test_unsupported_or_malformed_bindings_fail_closed(mutation):
    """External, ambiguous and escaping image data never receives a cost receipt."""
    with pytest.raises(ValueError):
        audit(glb(png_header(4, 4), mutation))


@pytest.mark.parametrize("dimensions", [(0, 1), (1, 0), (16385, 1), (8192, 8192)])
def test_dimensions_are_bounded(dimensions):
    """A valid header checksum cannot authorize an excessive image allocation."""
    with pytest.raises(ValueError):
        audit(glb(png_header(*dimensions)))


def test_corrupt_checksum_and_stale_glb_hash_fail():
    """Tampered dimensions and wrong expected files are distinct fail-closed cases."""
    image = bytearray(png_header(4, 4))
    image[20] ^= 1
    with pytest.raises(ValueError, match="checksum"):
        audit(glb(bytes(image)))
    with pytest.raises(ValueError, match="hash mismatch"):
        inspect_glb_texture_cost(glb(png_header(4, 4)), expected_sha256="0" * 64)
