"""Fixed read-only Blender 5.0.1 inspector for opt-in authored UV conversion proof."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from convert_portable_materials import _conversion_objects  # noqa: E402
from portable_authored_uv_runtime import inspection, read_source  # noqa: E402
from portable_material_conversion_runtime import (  # noqa: E402
    sha256_file,
    write_json_atomic,
)


def main():
    """Read source/target storage into a caller-owned file without saving either blend."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-blend-sha256", required=True)
    parser.add_argument("--source-snapshot")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    blend = Path(bpy.data.filepath)
    before = sha256_file(blend)
    if before != args.expected_blend_sha256:
        raise ValueError("authored UV inspector blend hash mismatch")
    sources = read_source(args.source_snapshot)["objects"] if args.source_snapshot else None
    payload = inspection(_conversion_objects(), before, sources=sources)
    if sha256_file(blend) != before:
        raise ValueError("authored UV inspector input changed")
    write_json_atomic(Path(args.output), payload)


if __name__ == "__main__":
    main()
