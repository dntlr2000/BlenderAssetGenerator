"""Exact embedded PNG costs and explicit, engine-independent RGBA8 storage estimates."""

from __future__ import annotations

import hashlib
import re
import struct
import zlib
from typing import Any

from .optical_audit import _document


def _integer(value: Any, minimum: int, maximum: int, label: str) -> int:
    """Require a bounded integer without accepting boolean or string coercion."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"Invalid embedded-image {label}")
    return value


def _rgba8_mip_bytes(width: int, height: int) -> int:
    """Sum a complete rectangular RGBA8 mip chain down to one by one."""
    total = width * height * 4
    while width > 1 or height > 1:
        width, height = max(1, width // 2), max(1, height // 2)
        total += width * height * 4
    return total


def inspect_glb_texture_cost(data: bytes, *, expected_sha256: str) -> dict[str, Any]:
    """Measure exact GLB image bytes; never infer visual gain or real engine allocation.

    PNG IHDR dimensions are CRC-checked but pixels are not decoded or quality-assessed.
    Estimates assume each serialized image is one uncompressed RGBA8 GPU resource.
    Engine compression, duplicate-resource sharing and upload policy remain unverified.
    External images, JPEG and extension-specific image containers are unsupported here.
    """
    if (
        not isinstance(expected_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
    ):
        raise ValueError("Texture cost audit needs an exact lowercase SHA-256")
    document = _document(data)
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise ValueError("Texture cost audit GLB hash mismatch")
    first_length = struct.unpack_from("<I", data, 12)[0]
    binary_start = 20 + first_length
    binary = data[binary_start + 8 :] if binary_start < len(data) else b""
    images = document.get("images", [])
    views = document.get("bufferViews", [])
    buffers = document.get("buffers", [])
    if not isinstance(images, list) or len(images) > 4096 or not isinstance(views, list):
        raise ValueError("Invalid embedded-image tables")
    if images and (
        not isinstance(buffers, list)
        or len(buffers) != 1
        or not isinstance(buffers[0], dict)
        or "uri" in buffers[0]
    ):
        raise ValueError("Embedded PNG audit requires one internal buffer")
    declared_length = (
        _integer(buffers[0].get("byteLength"), 0, len(binary), "buffer length") if images else 0
    )
    rows = []
    for index, item in enumerate(images):
        if not isinstance(item, dict) or "uri" in item or item.get("mimeType") != "image/png":
            raise ValueError("Texture cost audit supports only embedded PNG images")
        view_index = _integer(item.get("bufferView"), 0, len(views) - 1, "view index")
        view = views[view_index]
        if not isinstance(view, dict) or type(view.get("buffer")) is not int or view["buffer"] != 0:
            raise ValueError("Invalid image buffer binding")
        start = _integer(view.get("byteOffset", 0), 0, declared_length, "byte offset")
        length = _integer(view.get("byteLength"), 33, declared_length - start, "byte length")
        blob = binary[start : start + length]
        if blob[:8] != b"\x89PNG\r\n\x1a\n" or blob[8:16] != b"\0\0\0\rIHDR":
            raise ValueError("Embedded PNG has no complete IHDR")
        if zlib.crc32(blob[12:29]) != struct.unpack_from(">I", blob, 29)[0]:
            raise ValueError("Embedded PNG IHDR checksum differs")
        width, height, depth, color, compression, filtering, interlace = struct.unpack_from(
            ">IIBBBBB", blob, 16
        )
        _integer(width, 1, 16384, "width")
        _integer(height, 1, 16384, "height")
        depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
        if (
            width * height > 16777216
            or depth not in depths.get(color, set())
            or compression != 0
            or filtering != 0
            or interlace not in (0, 1)
        ):
            raise ValueError("Unsupported or malformed PNG dimensions/format")
        rows.append(
            {
                "image_index": index,
                "name": item.get("name"),
                "width": width,
                "height": height,
                "png_bit_depth": depth,
                "png_color_type": color,
                "encoded_bytes": length,
                "encoded_sha256": hashlib.sha256(blob).hexdigest(),
                "texels": width * height,
                "rgba8_base_bytes_estimate": width * height * 4,
                "rgba8_full_mip_bytes_estimate": _rgba8_mip_bytes(width, height),
            }
        )
    unique = {row["encoded_sha256"]: row for row in rows}
    return {
        "schema_version": "0.1.0",
        "glb_sha256": digest,
        "glb_bytes": len(data),
        "images": rows,
        "serialized_image_count": len(rows),
        "distinct_encoded_image_count": len(unique),
        "encoded_image_bytes_by_index": sum(row["encoded_bytes"] for row in rows),
        "distinct_encoded_image_bytes": sum(row["encoded_bytes"] for row in unique.values()),
        "rgba8_base_bytes_estimate": sum(row["rgba8_base_bytes_estimate"] for row in rows),
        "rgba8_full_mip_bytes_estimate": sum(row["rgba8_full_mip_bytes_estimate"] for row in rows),
        "estimate_basis": "One uncompressed RGBA8 resource per serialized image index",
        "pixels_decoded": False,
        "actual_engine_memory_verified": False,
        "visual_quality_verified": False,
        "texture_channel_semantics_verified": False,
    }
