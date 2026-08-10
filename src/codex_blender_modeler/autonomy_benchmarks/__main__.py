"""Command-line entry point for isolated Autonomous Quality benchmark evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from .runner import run_benchmark_manifest


def _build_parser() -> argparse.ArgumentParser:
    """Build the bounded benchmark CLI without exposing arbitrary execution hooks."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--run-blender",
        action="store_true",
        help="Run only the manifest-declared structural Blender smoke cases.",
    )
    return parser


def main() -> int:
    """Run the requested benchmark and return nonzero when any gate case fails."""

    arguments = _build_parser().parse_args()
    report = run_benchmark_manifest(
        arguments.manifest,
        arguments.output,
        run_blender_smoke=arguments.run_blender,
    )
    print(arguments.output.resolve())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
