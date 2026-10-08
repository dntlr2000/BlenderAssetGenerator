"""Check an explicitly selected post-export LOD mask diagnostic without changing package bytes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from codex_blender_modeler.packaging.lod_quality import inspect_exported_lod_quality


def main() -> int:
    """Print exact-hash-bound diagnostic results; unknown is distinct from a successful check."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-manifest", type=Path, required=True)
    parser.add_argument("--package-manifest-sha256", required=True)
    parser.add_argument("--render-root", type=Path)
    parser.add_argument("--render-plan-sha256")
    parser.add_argument("--render-manifest-sha256")
    args = parser.parse_args()
    try:
        result = inspect_exported_lod_quality(
            args.package_manifest,
            package_manifest_sha256=args.package_manifest_sha256,
            render_root=args.render_root,
            render_plan_sha256=args.render_plan_sha256,
            render_manifest_sha256=args.render_manifest_sha256,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
        StopIteration,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "kind": "read_only_exported_lod_quality_diagnostic",
                    "diagnostic_status": "invalid_evidence",
                    "error": str(exc),
                    "publication_or_acceptance_authority": False,
                },
                indent=2,
            )
        )
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    if result["diagnostic_status"] == "failed":
        return 1
    return 2 if result["diagnostic_status"] == "unverified" else 0


if __name__ == "__main__":
    raise SystemExit(main())
