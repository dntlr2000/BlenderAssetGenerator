"""Generate deterministic repository summaries and detect documentation drift.

Hash policy:
- the path set and ordering come from the Git index via git ls-files -s -z;
- payloads come from exact Git blob bytes, where text clean filters have already produced
  repository-canonical LF content;
- FILE_MANIFEST.sha256 records SHA-256 of blob payload bytes, not Git object IDs;
- REPOSITORY_TREE.txt and README.md use their newly rendered bytes in the same manifest pass;
- FILE_MANIFEST.sha256 excludes itself to avoid a recursive digest.

Generation intentionally uses the index as the future commit boundary. Stage the intended
source path set before --write; CI receives that same canonical set from the checked-out commit.

The --check mode compares expected bytes only. It never writes files or updates the Git index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

README_START = "<!-- CBM:REPOSITORY_SUMMARY:START -->"
README_END = "<!-- CBM:REPOSITORY_SUMMARY:END -->"
TREE_PATH = "REPOSITORY_TREE.txt"
MANIFEST_PATH = "FILE_MANIFEST.sha256"
README_PATH = "README.md"
DEFAULT_VERIFICATION_SUMMARY = "verification/latest_summary.json"


@dataclass(frozen=True)
class GitIndexEntry:
    """Represent one stage-zero Git index path and its canonical blob ID."""

    mode: str
    object_id: str
    path: str


def _source_root(root: Path) -> Path:
    """Return the importable source directory for the repository catalog."""

    return root / "src"


def _load_catalog_module(root: Path) -> Any:
    """Import the pure catalog without importing CLI, MCP, or Blender modules."""

    source = str(_source_root(root))
    sys.path.insert(0, source)
    try:
        from codex_blender_modeler import repository_catalog
    finally:
        sys.path.pop(0)
    return repository_catalog


def _run_git(root: Path, arguments: list[str]) -> bytes:
    """Run one read-only Git query and return exact stdout bytes."""

    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return process.stdout


def git_index_entries(root: Path) -> tuple[GitIndexEntry, ...]:
    """Read stable stage-zero path and object bindings from the Git index."""

    raw = _run_git(root, ["ls-files", "-s", "-z"])
    entries: list[GitIndexEntry] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", 1)
        mode, object_id, stage = metadata.decode("ascii").split()
        if stage != "0":
            raise RuntimeError("repository summary refuses an unmerged Git index")
        path = path_bytes.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        entries.append(GitIndexEntry(mode=mode, object_id=object_id, path=path))
    return tuple(sorted(entries, key=lambda entry: entry.path.encode("utf-8")))


def git_blob_bytes(root: Path, object_id: str) -> bytes:
    """Read exact canonical payload bytes for one existing Git blob."""

    return _run_git(root, ["cat-file", "blob", object_id])


def git_blob_batch(root: Path, object_ids: tuple[str, ...]) -> dict[str, bytes]:
    """Read many canonical blobs through one deterministic cat-file batch process."""

    unique_ids = tuple(dict.fromkeys(object_ids))
    if not unique_ids:
        return {}
    request = ("\n".join(unique_ids) + "\n").encode("ascii")
    process = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        check=True,
        input=request,
        capture_output=True,
    )
    output = process.stdout
    offset = 0
    blobs: dict[str, bytes] = {}
    for expected_id in unique_ids:
        header_end = output.find(b"\n", offset)
        if header_end < 0:
            raise RuntimeError("git cat-file batch response ended before its header")
        header = output[offset:header_end].decode("ascii").split()
        if len(header) != 3 or header[0] != expected_id or header[1] != "blob":
            raise RuntimeError(f"unexpected git cat-file batch header: {header}")
        size = int(header[2])
        payload_start = header_end + 1
        payload_end = payload_start + size
        payload = output[payload_start:payload_end]
        if len(payload) != size or output[payload_end : payload_end + 1] != b"\n":
            raise RuntimeError("git cat-file batch response has an invalid payload boundary")
        blobs[expected_id] = payload
        offset = payload_end + 1
    if offset != len(output):
        raise RuntimeError("git cat-file batch response contains trailing bytes")
    return blobs


def canonical_blob_sha256(payload: bytes) -> str:
    """Hash canonical Git blob payload bytes with SHA-256."""

    return hashlib.sha256(payload).hexdigest()


def stable_json_sha256(value: Any) -> str:
    """Hash one registry projection through canonical compact JSON."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return canonical_blob_sha256(payload)


def render_repository_tree(entries: tuple[GitIndexEntry, ...]) -> bytes:
    """Render the deterministic flat tracked-tree projection with LF endings."""

    lines = ["BlenderAssetGenerator/"]
    lines.extend(f"  {entry.path}" for entry in entries)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _read_json_object(path: Path) -> dict[str, Any]:
    """Load one strict JSON object used as external verification evidence."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"verification summary must be a JSON object: {path}")
    return payload


def _resolve_repository_relative(root: Path, relative_path: str) -> Path:
    """Resolve one contained repository-relative evidence path or reject it."""

    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError("verification summary path must be repository-relative")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if resolved_root not in resolved.parents:
        raise ValueError("verification summary path escapes the repository")
    return resolved


def _validate_verification_evidence_roots(root: Path, payload: dict[str, Any]) -> None:
    """Require every declared gate evidence root to be contained and locally available."""

    quality_gates = payload.get("quality_gates", {})
    if not isinstance(quality_gates, dict):
        raise ValueError("verification summary quality_gates must be an object")
    for gate_id, gate in sorted(quality_gates.items()):
        if not isinstance(gate, dict):
            raise ValueError(f"verification gate must be an object: {gate_id}")
        evidence_root = gate.get("evidence_root")
        if evidence_root is None:
            continue
        if not isinstance(evidence_root, str) or not evidence_root:
            raise ValueError(f"verification evidence_root must be a non-empty string: {gate_id}")
        resolved = _resolve_repository_relative(root, evidence_root)
        if not resolved.exists():
            raise ValueError(f"verification evidence_root does not exist: {evidence_root}")


def load_verification_summary(root: Path, relative_path: str) -> dict[str, Any]:
    """Return existing verification evidence or an explicit unavailable projection."""

    path = _resolve_repository_relative(root, relative_path)
    if not path.is_file():
        return {
            "status": "unavailable",
            "source": relative_path,
            "test_count": None,
            "tested_platforms": [],
        }
    payload = _read_json_object(path)
    _validate_verification_evidence_roots(root, payload)
    return {
        "status": str(payload.get("status", "reported")),
        "source": relative_path,
        "test_count": payload.get("test_count"),
        "tested_platforms": payload.get("tested_platforms", []),
        "source_sha256": canonical_blob_sha256(path.read_bytes()),
    }


def build_repository_summary(
    root: Path,
    *,
    verification_summary_path: str = DEFAULT_VERIFICATION_SUMMARY,
) -> dict[str, Any]:
    """Build one deterministic registry and verification projection."""

    catalog = _load_catalog_module(root)
    projection = catalog.repository_catalog_projection(root)
    verification = load_verification_summary(root, verification_summary_path)
    return {
        "schema_version": "0.1.0",
        "project_version": "0.9.0",
        "hash_policy": {
            "path_source": "git_index_stage_zero",
            "payload_source": "git_blob",
            "text_normalization": "git_clean_filter_lf",
            "digest": "sha256_blob_payload",
            "manifest_self_included": False,
        },
        "catalog": projection,
        "verification": verification,
    }


def render_readme_summary_block(summary: dict[str, Any]) -> str:
    """Render the generated README block from authoritative catalog data."""

    catalog = summary["catalog"]
    builders = catalog["builders"]
    profiles = catalog["autonomy_profiles"]
    deliveries = catalog["delivery_profiles"]
    mcp = catalog["mcp"]
    verification = summary["verification"]
    active_profiles = [
        entry["profile_id"] for entry in profiles if entry["status"] == "verified_active"
    ]
    experimental_profiles = [
        entry["profile_id"]
        for entry in profiles
        if entry["status"] in {"disabled_experimental", "experimental_unverified"}
    ]
    outputs = [
        entry["delivery_id"]
        for entry in deliveries
        if entry["status"].startswith("existing_")
    ]
    experimental_outputs = [
        entry["delivery_id"]
        for entry in deliveries
        if entry["status"] in {"disabled_experimental", "experimental_unverified"}
    ]
    test_count = verification["test_count"]
    test_text = "unavailable" if test_count is None else str(test_count)
    lines = [
        README_START,
        "## Generated repository summary",
        "",
        "- Catalog schema: 0.1.0",
        "- Legacy builders: " + ", ".join(builders["legacy"]),
        "- Structural builders: " + ", ".join(builders["structural"]),
        "- Active autonomy profiles: " + (", ".join(active_profiles) or "none"),
        "- Experimental profiles: " + (", ".join(experimental_profiles) or "none"),
        "- Existing delivery outputs: " + (", ".join(outputs) or "none"),
        "- Experimental delivery roles: "
        + (", ".join(experimental_outputs) or "none"),
        f"- CLI commands: {len(catalog['cli_commands'])}",
        "- CLI registry SHA-256: " + stable_json_sha256(catalog["cli_commands"]),
        f"- MCP server tools: {len(mcp['server_tools'])}",
        "- MCP server registry SHA-256: " + stable_json_sha256(mcp["server_tools"]),
        f"- Project-enabled MCP tools: {len(mcp['project_enabled_tools'])}",
        "- Project-enabled MCP SHA-256: "
        + stable_json_sha256(mcp["project_enabled_tools"]),
        "- Controller phase profiles: "
        + ", ".join(profile["profile_id"] for profile in mcp["phase_profiles"]),
        "- Delivery registry SHA-256: " + stable_json_sha256(deliveries),
        f"- Latest reported test count: {test_text}",
        f"- Verification summary: {verification['source']} ({verification['status']})",
        "",
        "Server registration, project enablement, and controller phase profiles are "
        "separate authorization surfaces. Experimental entries are not verified support.",
        README_END,
    ]
    return "\n".join(lines)


def replace_readme_block(current: bytes, block: str) -> bytes:
    """Replace or append the generated README block using canonical LF text."""

    text = current.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    start = text.find(README_START)
    end = text.find(README_END)
    if (start < 0) != (end < 0):
        raise ValueError("README contains only one repository-summary marker")
    if start >= 0:
        if end < start:
            raise ValueError("README repository-summary markers are reversed")
        end += len(README_END)
        updated = text[:start].rstrip() + "\n\n" + block + text[end:]
    else:
        updated = text.rstrip() + "\n\n" + block + "\n"
    if not updated.endswith("\n"):
        updated += "\n"
    return updated.encode("utf-8")


def render_file_manifest(
    root: Path,
    entries: tuple[GitIndexEntry, ...],
    replacements: dict[str, bytes],
) -> bytes:
    """Render SHA-256 values over canonical blobs and generated replacements."""

    required_ids = tuple(
        entry.object_id
        for entry in entries
        if entry.path != MANIFEST_PATH and entry.path not in replacements
    )
    blob_payloads = git_blob_batch(root, required_ids)
    lines: list[str] = []
    for entry in entries:
        if entry.path == MANIFEST_PATH:
            continue
        payload = replacements.get(entry.path)
        if payload is None:
            payload = blob_payloads[entry.object_id]
        lines.append(f"{canonical_blob_sha256(payload)}  {entry.path}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def expected_repository_outputs(
    root: Path,
    *,
    verification_summary_path: str = DEFAULT_VERIFICATION_SUMMARY,
) -> dict[str, bytes]:
    """Build mutually consistent README, tree, and manifest bytes without writing."""

    entries = git_index_entries(root)
    summary = build_repository_summary(
        root,
        verification_summary_path=verification_summary_path,
    )
    readme_entry = next((entry for entry in entries if entry.path == README_PATH), None)
    if readme_entry is None:
        raise ValueError("README.md must be present in the Git index")
    current_readme = (root / README_PATH).read_bytes()
    readme = replace_readme_block(current_readme, render_readme_summary_block(summary))
    tree = render_repository_tree(entries)
    replacements = {
        README_PATH: readme,
        TREE_PATH: tree,
    }
    manifest = render_file_manifest(root, entries, replacements)
    return {
        README_PATH: readme,
        TREE_PATH: tree,
        MANIFEST_PATH: manifest,
    }


def compare_repository_outputs(root: Path, expected: dict[str, bytes]) -> tuple[str, ...]:
    """Report only byte drift between generated expectations and repository files."""

    findings: list[str] = []
    for relative_path, expected_bytes in expected.items():
        path = root / relative_path
        if not path.is_file():
            findings.append(f"missing generated file: {relative_path}")
            continue
        if path.read_bytes() != expected_bytes:
            findings.append(f"generated file drift: {relative_path}")
    return tuple(findings)


def _write_atomic(path: Path, payload: bytes) -> None:
    """Publish one generated file atomically without touching unrelated paths."""

    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def write_repository_outputs(root: Path, expected: dict[str, bytes]) -> None:
    """Write only the three declared generated repository projections."""

    for relative_path, payload in expected.items():
        _write_atomic(root / relative_path, payload)


def _build_parser() -> argparse.ArgumentParser:
    """Create the summary generator command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root; defaults to the script parent.",
    )
    parser.add_argument(
        "--verification-summary",
        default=DEFAULT_VERIFICATION_SUMMARY,
        help="Repository-relative latest verification summary JSON.",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--check",
        action="store_true",
        help="Detect drift without writing any file.",
    )
    modes.add_argument(
        "--write",
        action="store_true",
        help="Regenerate README, repository tree, and file manifest.",
    )
    return parser


def main() -> int:
    """Generate JSON, detect drift, or write declared summary projections."""

    args = _build_parser().parse_args()
    root = args.root.resolve()
    summary = build_repository_summary(
        root,
        verification_summary_path=args.verification_summary,
    )
    catalog_findings = tuple(summary["catalog"]["catalog_findings"])
    if args.check:
        expected = expected_repository_outputs(
            root,
            verification_summary_path=args.verification_summary,
        )
        findings = (*catalog_findings, *compare_repository_outputs(root, expected))
        if findings:
            for finding in findings:
                print(f"DRIFT: {finding}")
            return 1
        print("OK: repository catalog and generated projections are current")
        return 0
    if args.write:
        if catalog_findings:
            for finding in catalog_findings:
                print(f"ERROR: {finding}")
            return 1
        expected = expected_repository_outputs(
            root,
            verification_summary_path=args.verification_summary,
        )
        write_repository_outputs(root, expected)
        print("WROTE: README.md, REPOSITORY_TREE.txt, FILE_MANIFEST.sha256")
        return 0
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
