"""Finalize one repository gate and compact only its successful run-owned scratch."""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from codex_blender_modeler.storage_retention import finalize_gate_run


def _parser() -> argparse.ArgumentParser:
    """Build the narrow gate-finalization command-line contract."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--gate-id", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--process-temp-root")
    parser.add_argument(
        "--gate-outcome",
        choices=("passed", "failed", "interrupted"),
        default="passed",
    )
    parser.add_argument(
        "--retention-policy",
        choices=("compact-success", "preserve"),
        default="compact-success",
    )
    parser.add_argument("--started-at")
    return parser


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an optional ISO-8601 gate start timestamp without guessing a timezone."""

    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--started-at must include an explicit timezone")
    return parsed


def main() -> int:
    """Publish the exact gate receipt and return a distinct retention failure code."""

    arguments = _parser().parse_args()
    try:
        receipt = finalize_gate_run(
            run_id=arguments.run_id,
            gate_id=arguments.gate_id,
            run_root=arguments.run_root,
            process_temp_root=arguments.process_temp_root,
            gate_outcome=arguments.gate_outcome,
            retention_policy=arguments.retention_policy.replace("-", "_"),
            started_at=_parse_timestamp(arguments.started_at),
        )
    except RuntimeError as exc:
        print(json.dumps({"retention_status": "failed", "error": str(exc)}))
        return 3
    print(receipt.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
