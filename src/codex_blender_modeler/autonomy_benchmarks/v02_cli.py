"""Command-line entry point for the isolated AQ 0.2 synthetic benchmark."""

from __future__ import annotations

import argparse
from pathlib import Path

from .v02_runner import run_benchmark_manifest_v02


def _build_parser() -> argparse.ArgumentParser:
    """Build a fixed AQ 0.2 benchmark CLI with no arbitrary execution surface."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--run-blender",
        action="store_true",
        help="Run only the v0.2 manifest-declared fixed Blender smoke cases.",
    )
    return parser


def main() -> int:
    """Run the strict v0.2 benchmark and fail when any declared case fails."""

    arguments = _build_parser().parse_args()
    report = run_benchmark_manifest_v02(
        arguments.manifest,
        arguments.output,
        run_blender_smoke=arguments.run_blender,
    )
    print(arguments.output.resolve())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
