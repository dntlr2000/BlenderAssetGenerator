"""Read-only embedded GLB normal-map semantic and expected-channel verification.

The audit is additional technical evidence, never package or appearance acceptance.
It inspects the pixels actually referenced by normalTexture, not image filenames.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image


def pixel_evidence(blob):
    """Decode bounded image bytes and inspect RGB tangent-normal semantics."""
    with Image.open(io.BytesIO(blob)) as image:
        if image.width * image.height > 16777216:
            raise ValueError("normal-map image exceeds the bounded audit size")
        original_mode = image.mode
        pixels = np.asarray(image.convert("RGB"), dtype=np.uint8)
    vectors = pixels.astype(np.float64) / 127.5 - 1
    lengths = np.linalg.norm(vectors, axis=-1)
    invalid = ~np.isfinite(lengths) | (lengths < 0.8) | (lengths > 1.2)
    achromatic = (pixels[..., 0] == pixels[..., 1]) & (pixels[..., 1] == pixels[..., 2])
    findings = []
    if original_mode not in ("RGB", "RGBA"):
        findings.append("NORMAL_MAP_NOT_RGB_CHANNEL_DATA")
    if float(invalid.mean()) > 0.01:
        findings.append("NORMAL_MAP_NONUNIT_VECTOR_FIELD")
    if float(achromatic.mean()) > 0.99:
        findings.append("NORMAL_MAP_ACHROMATIC_HEIGHT_LIKE_FIELD")
    return {
        "source_mode": original_mode,
        "dimensions": [int(pixels.shape[1]), int(pixels.shape[0])],
        "decoded_rgb_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
        "encoded_sha256": hashlib.sha256(blob).hexdigest(),
        "unit_length_range": [float(lengths.min()), float(lengths.max())],
        "outside_unit_tolerance_fraction": float(invalid.mean()),
        "achromatic_fraction": float(achromatic.mean()),
        "findings": findings,
    }


def parse_glb(blob):
    """Parse the GLB container with bounded chunks and exact header checks."""
    if len(blob) < 20:
        raise ValueError("truncated GLB")
    magic, version, length = struct.unpack_from("<4sII", blob)
    if magic != b"glTF" or version != 2 or length != len(blob):
        raise ValueError("invalid GLB header")
    position = 12
    document = None
    binary = None
    while position < len(blob):
        if position + 8 > len(blob):
            raise ValueError("truncated GLB chunk header")
        size, kind = struct.unpack_from("<II", blob, position)
        position += 8
        if size % 4 or position + size > len(blob):
            raise ValueError("invalid GLB chunk extent")
        body = blob[position : position + size]
        if kind == 0x4E4F534A:
            if document is not None:
                raise ValueError("duplicate GLB JSON")
            document = json.loads(body)
        elif kind == 0x004E4942:
            if binary is not None:
                raise ValueError("duplicate GLB binary chunk")
            binary = body
        position += size
    if not isinstance(document, dict) or binary is None:
        raise ValueError("GLB JSON or binary missing")
    return document, binary


def indexed(values, index, label):
    """Reject negative, noninteger and out-of-range glTF reference indices."""
    if not isinstance(values, list) or type(index) is not int or not 0 <= index < len(values):
        raise ValueError(f"invalid {label} reference index")
    return values[index]


def audit_glb(path, expected=None):
    """Validate every embedded normal image and optional exact expected material map."""
    path = Path(path)
    blob = path.read_bytes()
    document, binary = parse_glb(blob)
    rows = []
    expected = expected or {}
    seen = set()
    for index, material in enumerate(document.get("materials", [])):
        name = material.get("name", str(index))
        seen.add(name)
        expected_map = expected.get(name)
        reference = material.get("normalTexture")
        row = {
            "material_index": index,
            "material_name": name,
            "normal_texture_present": reference is not None,
            "findings": [],
        }
        if reference is None:
            if expected_map is not None:
                row["findings"].append("EXPECTED_NORMAL_TEXTURE_MISSING")
            rows.append(row)
            continue
        texture = indexed(document.get("textures"), reference["index"], "normal texture")
        if "source" not in texture:
            raise ValueError("unsupported normal texture source extension")
        source = indexed(document.get("images"), texture["source"], "normal image")
        if "uri" in source or "bufferView" not in source:
            raise ValueError("normal audit requires contained embedded image bytes")
        view = indexed(document.get("bufferViews"), source["bufferView"], "normal image buffer")
        if view.get("buffer", 0) != 0:
            raise ValueError("normal image references an external buffer")
        start = view.get("byteOffset", 0)
        length = view["byteLength"]
        if (
            type(start) is not int
            or type(length) is not int
            or start < 0
            or length < 1
            or start + length > len(binary)
        ):
            raise ValueError("normal image buffer view is outside binary payload")
        evidence = pixel_evidence(binary[start : start + length])
        row["image"] = evidence
        row["findings"].extend(evidence["findings"])
        if expected_map is not None:
            expected_path = Path(expected_map["path"])
            expected_bytes = expected_path.read_bytes()
            if hashlib.sha256(expected_bytes).hexdigest() != expected_map["sha256"]:
                raise ValueError("expected normal-map binding is stale")
            expected_evidence = pixel_evidence(expected_bytes)
            row["expected_encoded_sha256"] = expected_map["sha256"]
            row["expected_decoded_rgb_sha256"] = expected_evidence["decoded_rgb_sha256"]
            if evidence["decoded_rgb_sha256"] != expected_evidence["decoded_rgb_sha256"]:
                row["findings"].append("EXPORTED_NORMAL_CHANNEL_DIFFERS_FROM_EXPECTED")
        rows.append(row)
    missing = sorted(set(expected) - seen)
    return {
        "schema_version": "0.1.0",
        "kind": "glb_normal_texture_semantic_audit",
        "glb_sha256": hashlib.sha256(blob).hexdigest(),
        "materials": rows,
        "expected_materials_missing": missing,
        "passed": not missing and all(not row["findings"] for row in rows),
        "scope": (
            "Embedded texture semantics and exact expected-channel evidence only. "
            "No renderer, engine or appearance acceptance."
        ),
    }


def main():
    """Write a read-only material semantic audit for one exact GLB."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--expected-json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.expected_json.read_text()) if args.expected_json else None
    result = audit_glb(args.glb, expected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
