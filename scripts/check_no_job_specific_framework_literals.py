"""Reject known incident-specific literals from reusable framework source and prompts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    ROOT / "src" / "codex_blender_modeler",
    ROOT / "schemas",
    ROOT / "prompts",
)
ROOT_PROMPT_GLOBS = ("*PROMPTS*.md",)


@dataclass(frozen=True)
class IncidentLiteral:
    """Describe one exact incident token that reusable framework files must not contain."""

    token: str
    label: str


INCIDENT_LITERALS = (
    IncidentLiteral("item_crystalgun", "incident job identifier"),
    IncidentLiteral("item-crystalgun", "incident portable job identifier"),
    IncidentLiteral("prop.crystalgun", "incident semantic prefix"),
    IncidentLiteral(
        "aqv2-20260813t050847825044z-1232d4a0",
        "incident AQ session identifier",
    ),
    IncidentLiteral(
        "ef7cadec41a56a10701c10ea623fb6367dc05cb34acc39f8d360b8752fe77ab8",
        "incident SceneSpec digest",
    ),
    IncidentLiteral(
        "52779a95bd5bf4f87b55cd6481d55c8e50efcaca79e7c16973682314b1a4b225",
        "incident ModelingPlan digest",
    ),
    IncidentLiteral(
        "5def13d76012b0c9747dce6ef016799550bca74a9e5f2e3bccf6b7ed8a9ebe5a",
        "incident Blender scene digest",
    ),
    IncidentLiteral(
        "exec-0011-material-graph-binding-closure-retry",
        "incident retry execution identifier",
    ),
    IncidentLiteral(
        "MATERIAL GRAPH BINDING CLOSURE RETRY",
        "incident retry approval phrase",
    ),
)


def _candidate_files() -> list[Path]:
    """Return deterministic reusable-source files covered by the incident scan."""

    candidates: set[Path] = set()
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        candidates.update(path for path in root.rglob("*") if path.is_file())
    for pattern in ROOT_PROMPT_GLOBS:
        candidates.update(path for path in ROOT.glob(pattern) if path.is_file())
    return sorted(candidates, key=lambda item: item.relative_to(ROOT).as_posix().casefold())


def find_job_specific_framework_literals() -> list[str]:
    """Return stable findings for exact incident literals in reusable framework files."""

    findings: list[str] = []
    for path in _candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        folded = text.casefold()
        relative = path.relative_to(ROOT).as_posix()
        for incident in INCIDENT_LITERALS:
            if incident.token.casefold() in folded:
                findings.append(f"{relative}: {incident.label}: {incident.token}")
    return findings


def main() -> int:
    """Print exact findings and return nonzero while reusable code remains incident-bound."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    findings = find_job_specific_framework_literals()
    if findings:
        for finding in findings:
            print(f"JOB_SPECIFIC_FRAMEWORK_LITERAL: {finding}")
        return 1
    print("OK: no known job-specific framework literals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
