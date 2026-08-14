"""Validate hierarchical AGENTS instructions and exact legacy RULE_ID preservation."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT_MAX_BYTES = 12 * 1024
ROOT_TO_LEAF_MAX_BYTES = 28 * 1024
EXPECTED_INVARIANT_COUNT = 192
EXPECTED_INVARIANT_SHA256 = "d6d4a5b6c982c601f20bb95969e340d75e78a33e478fac26454e3281c167a865"

ROOT_SENTINELS = (
    "CBM-ROOT-IMMUTABLE-INPUT",
    "CBM-ROOT-MACHINE-JSON",
    "CBM-ROOT-USER-CHANGES",
    "CBM-ROOT-NO-RESET",
    "CBM-ROOT-NO-SYNTH-APPROVAL",
    "CBM-ROOT-CONTROLLER-WRITE",
    "CBM-ROOT-NO-ARBITRARY-CODE",
    "CBM-ROOT-PACKAGE-REVIEW-SEPARATION",
    "CBM-ROOT-NO-DEST-WRITE",
    "CBM-ROOT-NO-UNVERIFIED",
    "CBM-ROOT-SKILL-OPTIN",
    "CBM-ROOT-METHOD-DOC",
    "CBM-ROOT-NO-AUTO-MIGRATION",
    "CBM-ROOT-FAIL-CLOSED",
    "CBM-ROOT-HISTORY",
)

REQUIRED_DOCS = (
    "docs/agent/README.md",
    "docs/agent/source_of_truth.md",
    "docs/agent/invariant_catalog.md",
    "docs/agent/approvals_and_authorization.md",
    "docs/agent/evidence_hashing_and_history.md",
    "docs/agent/blender_execution.md",
    "docs/agent/testing_and_verification.md",
    "docs/agent/packaging_and_handoff.md",
    "docs/agent/autonomy_safety.md",
    "docs/agent/workflow_reference.md",
)

REQUIRED_LEAF_AGENTS = (
    "src/codex_blender_modeler/autonomy/AGENTS.md",
    "src/codex_blender_modeler/integrated_quality/AGENTS.md",
    "src/codex_blender_modeler/material_graph/AGENTS.md",
    "src/codex_blender_modeler/materials/AGENTS.md",
    "src/codex_blender_modeler/material_closure/AGENTS.md",
    "src/codex_blender_modeler/material_preflight/AGENTS.md",
    "src/codex_blender_modeler/material_promotion/AGENTS.md",
    "src/codex_blender_modeler/material_recovery/AGENTS.md",
    "src/codex_blender_modeler/texturing/AGENTS.md",
    "src/codex_blender_modeler/packaging/AGENTS.md",
    "src/codex_blender_modeler/handoff/AGENTS.md",
    "src/codex_blender_modeler/orchestration/AGENTS.md",
    "src/codex_blender_modeler/production/AGENTS.md",
    "src/codex_blender_modeler/blender_scripts/AGENTS.md",
)

RULE_PATTERN = re.compile(r"^- \[CBM-INV-(\d{3})\] (.+)$", re.MULTILINE)
POLICY_PATTERN = re.compile(r"<!-- RULE_POLICY ([a-z0-9_]+)=([^\s]+) -->")
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _tracked_and_untracked_paths(root: Path) -> tuple[Path, ...]:
    """List repository-visible paths without walking user workspaces or temp trees."""

    process = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths = [
        root / item.decode("utf-8", errors="surrogateescape")
        for item in process.stdout.split(b"\0")
        if item
    ]
    return tuple(paths)


def discover_agent_files(root: Path) -> tuple[Path, ...]:
    """Return root and leaf AGENTS files visible to Git in stable path order."""

    files = {
        path.resolve()
        for path in _tracked_and_untracked_paths(root)
        if path.name == "AGENTS.md" and "workspaces" not in path.parts
    }
    root_agents = (root / "AGENTS.md").resolve()
    if root_agents.exists():
        files.add(root_agents)
    return tuple(sorted(files, key=lambda item: item.as_posix()))


def instruction_chain(root: Path, leaf: Path) -> tuple[Path, ...]:
    """Resolve every AGENTS file from repository root through one leaf directory."""

    root = root.resolve()
    leaf = leaf.resolve()
    if leaf.name != "AGENTS.md":
        raise ValueError(f"instruction leaf must be AGENTS.md: {leaf}")
    if root not in leaf.parents and leaf != root / "AGENTS.md":
        raise ValueError(f"instruction leaf escapes repository root: {leaf}")

    chain: list[Path] = []
    cursor = leaf.parent
    while True:
        candidate = cursor / "AGENTS.md"
        if candidate.exists():
            chain.append(candidate.resolve())
        if cursor == root:
            break
        cursor = cursor.parent
    return tuple(reversed(chain))


def _validate_instruction_sizes(root: Path, agent_files: tuple[Path, ...]) -> list[str]:
    """Check root and root-to-leaf byte budgets."""

    findings: list[str] = []
    root_agents = root / "AGENTS.md"
    root_size = root_agents.stat().st_size
    if root_size > ROOT_MAX_BYTES:
        findings.append(
            f"root AGENTS.md is {root_size} bytes; maximum is {ROOT_MAX_BYTES}"
        )
    for leaf in agent_files:
        chain = instruction_chain(root, leaf)
        combined = sum(path.stat().st_size for path in chain)
        if combined > ROOT_TO_LEAF_MAX_BYTES:
            relative = leaf.relative_to(root).as_posix()
            findings.append(
                f"instruction chain for {relative} is {combined} bytes; "
                f"maximum is {ROOT_TO_LEAF_MAX_BYTES}"
            )
    return findings


def _validate_root_sentinels(root: Path) -> list[str]:
    """Require every absolute root sentinel exactly once."""

    text = (root / "AGENTS.md").read_text(encoding="utf-8")
    findings: list[str] = []
    for sentinel in ROOT_SENTINELS:
        count = text.count(f"[{sentinel}]")
        if count != 1:
            findings.append(f"root sentinel {sentinel} occurs {count} times")
    return findings


def _validate_rule_catalog(root: Path) -> list[str]:
    """Verify contiguous exact legacy rules and their canonical LF digest."""

    catalog_path = root / "docs" / "agent" / "invariant_catalog.md"
    text = catalog_path.read_text(encoding="utf-8")
    matches = RULE_PATTERN.findall(text)
    findings: list[str] = []
    numbers = [int(number) for number, _body in matches]
    expected_numbers = list(range(1, EXPECTED_INVARIANT_COUNT + 1))
    if numbers != expected_numbers:
        findings.append(
            "invariant RULE_ID sequence must be exactly CBM-INV-001..CBM-INV-192"
        )
        return findings

    canonical = "".join(
        f"{number}. {body}\n" for number, (_rule_id, body) in enumerate(matches, start=1)
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if digest != EXPECTED_INVARIANT_SHA256:
        findings.append(
            f"legacy invariant digest changed: {digest} != {EXPECTED_INVARIANT_SHA256}"
        )
    declared = re.search(r"Legacy canonical text SHA-256: ([0-9a-f]{64})", text)
    if declared is None or declared.group(1) != EXPECTED_INVARIANT_SHA256:
        findings.append("invariant catalog declares the wrong legacy digest")

    source_root = root / "src"
    sys.path.insert(0, str(source_root))
    try:
        from codex_blender_modeler.repository_catalog import RULE_GROUPS
    finally:
        sys.path.pop(0)
    covered: list[int] = []
    for _name, first, last in RULE_GROUPS:
        covered.extend(range(first, last + 1))
    if covered != expected_numbers:
        findings.append("repository RULE_GROUPS must cover each legacy invariant exactly once")
    return findings


def _validate_required_paths(root: Path) -> list[str]:
    """Require the documented hierarchy and subsystem leaf instructions."""

    findings: list[str] = []
    for relative in (*REQUIRED_DOCS, *REQUIRED_LEAF_AGENTS):
        if not (root / relative).is_file():
            findings.append(f"required instruction path is missing: {relative}")
    return findings


def _validate_links(root: Path) -> list[str]:
    """Check local Markdown links in root, leaf, and agent-guide files."""

    candidates = [root / "AGENTS.md"]
    candidates.extend(root / relative for relative in REQUIRED_DOCS)
    candidates.extend(root / relative for relative in REQUIRED_LEAF_AGENTS)
    findings: list[str] = []
    for source in candidates:
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8")
        for raw_target in LINK_PATTERN.findall(text):
            target = raw_target.strip().split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (source.parent / target).resolve()
            if root.resolve() not in resolved.parents and resolved != root.resolve():
                findings.append(
                    f"escaping instruction link in "
                    f"{source.relative_to(root).as_posix()}: {raw_target}"
                )
                continue
            if not resolved.exists():
                findings.append(
                    f"broken instruction link in {source.relative_to(root).as_posix()}: "
                    f"{raw_target}"
                )
    return findings


def _validate_policy_conflicts(agent_files: tuple[Path, ...], root: Path) -> list[str]:
    """Reject conflicting structured RULE_POLICY values across AGENTS layers."""

    values: dict[str, tuple[str, Path]] = {}
    findings: list[str] = []
    for path in agent_files:
        text = path.read_text(encoding="utf-8")
        for key, value in POLICY_PATTERN.findall(text):
            previous = values.get(key)
            if previous is not None and previous[0] != value:
                findings.append(
                    f"RULE_POLICY {key} conflicts between "
                    f"{previous[1].relative_to(root).as_posix()}={previous[0]} and "
                    f"{path.relative_to(root).as_posix()}={value}"
                )
            else:
                values[key] = (value, path)
    return findings


def validate_agent_instructions(root: Path) -> tuple[str, ...]:
    """Return all deterministic instruction hierarchy findings."""

    root = root.resolve()
    agent_files = discover_agent_files(root)
    findings: list[str] = []
    findings.extend(_validate_required_paths(root))
    if not (root / "AGENTS.md").is_file():
        findings.append("root AGENTS.md is missing")
        return tuple(findings)
    findings.extend(_validate_instruction_sizes(root, agent_files))
    findings.extend(_validate_root_sentinels(root))
    if (root / "docs" / "agent" / "invariant_catalog.md").is_file():
        findings.extend(_validate_rule_catalog(root))
    findings.extend(_validate_links(root))
    findings.extend(_validate_policy_conflicts(agent_files, root))
    return tuple(findings)


def _build_parser() -> argparse.ArgumentParser:
    """Create the standalone instruction-checker argument parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root; defaults to the script parent.",
    )
    return parser


def main() -> int:
    """Run the checker and return a CI-friendly status code."""

    args = _build_parser().parse_args()
    findings = validate_agent_instructions(args.root)
    if findings:
        for finding in findings:
            print(f"ERROR: {finding}")
        return 1
    root_size = (args.root / "AGENTS.md").stat().st_size
    agent_count = len(discover_agent_files(args.root))
    print(
        "OK: agent instructions "
        f"(root={root_size} bytes, files={agent_count}, invariants={EXPECTED_INVARIANT_COUNT})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
