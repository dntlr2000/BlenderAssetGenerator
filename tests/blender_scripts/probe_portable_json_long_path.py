"""Exercise portable companion JSON I/O inside Blender's bundled Python."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = ROOT / "src" / "codex_blender_modeler" / "blender_scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from portable_asset_common import read_json_object, sha256_file, write_json  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Parse the one host-owned output path used by this fixed smoke probe."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def main() -> int:
    """Round-trip deterministic quality evidence and verify its exact digest."""

    output = Path(parse_args().output)
    payload = {
        "kind": "portable_json_long_path_blender_smoke",
        "ok": True,
        "runtime": "blender_python",
    }
    write_json(output, payload)
    if read_json_object(output) != payload:
        raise RuntimeError("Portable JSON long-path payload changed after writing")
    digest = sha256_file(output)
    if len(digest) != 64 or digest.lower() != digest:
        raise RuntimeError("Portable JSON long-path SHA-256 is invalid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
