"""Conservative inventory, planning, execution, and gate-run retention services."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..blender_artifacts import (
    deterministic_json_bytes,
    native_io_path,
    publish_bytes_create_once,
    sha256_file,
)
from ..config import get_settings
from .models import (
    GateOutcome,
    GateRetentionRecoveryReceiptV01,
    GateRunReceiptV01,
    RetentionPolicy,
    StorageArtifact,
    StorageCleanupCandidate,
    StorageCleanupPlanV01,
    StorageCleanupReceiptV01,
    StorageCleanupResult,
    StorageEntryKind,
    StorageInventoryV01,
    StorageTreeEntry,
    storage_input_sha256,
)

_ALLOWED_ROOTS = (".b", ".t")
_CONTROL_ROOT = Path("reports/storage_retention")
_GATE_RECEIPT_ROOT = Path("reports/gate_runs")
_OPERATION_ROOT = Path(".cbm/storage_retention")
_PORTABLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_TEMP_PATH_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_.-])((?:\.b|\.t)/(?:[A-Za-z0-9_.@+\-]+/)*[A-Za-z0-9_.@+\-]+)"
)
_PID_SUFFIX_RE = re.compile(r"-(\d+)(?:-process-temp)?$")
_LOCK_SUFFIXES = (".lock", ".lock.json")
_OWNER_MARKER = ".retention-owner.json"
_PROTECTION_SCAN_ROOTS = (Path("reports"), Path("workspaces"), Path("workspace_archive"))


@dataclass(frozen=True)
class _TreeScan:
    """Hold deterministic identity and operational metadata for one temporary tree."""

    tree_sha256: str | None
    file_count: int
    directory_count: int
    byte_size: int
    newest_mtime_ns: int
    link_found: bool
    lock_found: bool
    owner_pids: tuple[int, ...]
    matched_protected_hashes: tuple[str, ...]


@dataclass(frozen=True)
class _ProtectionIndex:
    """Hold exact path/hash anchors and the bytes that produced their index."""

    relative_paths: frozenset[str]
    sha256_values: frozenset[str]
    verified_success_roots: frozenset[str]
    source_sha256: str
    inaccessible_paths: tuple[str, ...]


class _UnsafeTreeError(ValueError):
    """Signal a link, reparse point, or unsupported member in a cleanup tree."""


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for retention evidence."""

    return datetime.now(UTC)


def _json_timestamp(value: datetime) -> str:
    """Encode one timestamp exactly as Pydantic JSON mode emits UTC values."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    """Create one sortable portable storage-control identifier."""

    stamp = _utc_now().strftime("%Y%m%dT%H%M%S%fZ").lower()
    return f"{prefix}-{stamp}-{uuid4().hex[:8]}"


def _validate_portable_id(value: str) -> str:
    """Reject identifiers that could escape an immutable control directory."""

    if not _PORTABLE_ID_RE.fullmatch(value):
        raise ValueError("storage retention identifier is not portable")
    return value


def _absolute_lexical(path: Path) -> Path:
    """Normalize a path lexically without resolving links or junctions."""

    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _is_link_or_reparse_metadata(metadata: os.stat_result) -> bool:
    """Recognize POSIX links and Windows junction/reparse metadata."""

    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _is_link_like(path: Path) -> bool:
    """Return whether an existing path is a symbolic link or reparse point."""

    metadata = os.lstat(native_io_path(path))
    return _is_link_or_reparse_metadata(metadata)


def _assert_no_link_ancestors(path: Path, *, include_leaf: bool) -> None:
    """Reject every existing linked component before retention-control I/O."""

    candidate = _absolute_lexical(path)
    parts = candidate.parts
    if not parts:
        raise ValueError("retention path is empty")
    current = Path(parts[0])
    selected = parts[1:] if include_leaf else parts[1:-1]
    for part in selected:
        current /= part
        native = native_io_path(current)
        if not os.path.lexists(native):
            continue
        metadata = os.lstat(native)
        if _is_link_or_reparse_metadata(metadata):
            raise _UnsafeTreeError(f"retention path contains a link: {current}")


def _repo_root(repo_root: Path | None) -> Path:
    """Resolve and validate the repository boundary used by one retention call."""

    selected = _absolute_lexical(repo_root or get_settings().repo_root)
    _assert_no_link_ancestors(selected, include_leaf=True)
    if not os.path.isdir(native_io_path(selected)) or _is_link_like(selected):
        raise NotADirectoryError(selected)
    return selected


def _contained_path(repo: Path, relative: str, *, must_exist: bool) -> Path:
    """Resolve one normalized repository-relative path without following links."""

    if (
        not relative
        or "\\" in relative
        or ":" in relative
        or relative.startswith("/")
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise ValueError("retention paths must be normalized repository-relative POSIX paths")
    candidate = _absolute_lexical(repo / Path(*relative.split("/")))
    candidate.relative_to(repo)
    _assert_no_link_ancestors(candidate, include_leaf=must_exist)
    if must_exist and not os.path.lexists(native_io_path(candidate)):
        raise FileNotFoundError(candidate)
    return candidate


def _ensure_directory(repo: Path, relative: str) -> Path:
    """Create one contained control directory while rejecting linked ancestors."""

    destination = _contained_path(repo, relative, must_exist=False)
    os.makedirs(native_io_path(destination), exist_ok=True)
    _assert_no_link_ancestors(destination, include_leaf=True)
    if not os.path.isdir(native_io_path(destination)) or _is_link_like(destination):
        raise NotADirectoryError(destination)
    return destination


def _relative_path(repo: Path, path: Path) -> str:
    """Project one lexically contained path to normalized repository-relative syntax."""

    return _absolute_lexical(path).relative_to(repo).as_posix()


def _write_immutable_model(repo: Path, relative: str, model: Any) -> Path:
    """Create or exact-adopt one deterministic retention JSON artifact."""

    destination = _contained_path(repo, relative, must_exist=False)
    _ensure_directory(repo, destination.parent.relative_to(repo).as_posix())
    publish_bytes_create_once(
        destination,
        deterministic_json_bytes(model.model_dump(mode="json")),
    )
    return destination


def _read_regular_bytes(path: Path) -> bytes:
    """Read one required regular, non-linked file through its native path."""

    _assert_no_link_ancestors(path, include_leaf=True)
    metadata = os.lstat(native_io_path(path))
    if not stat.S_ISREG(metadata.st_mode) or _is_link_or_reparse_metadata(metadata):
        raise ValueError(f"retention artifact is not a regular file: {path}")
    with open(native_io_path(path), "rb") as handle:
        return handle.read()


def _load_model(repo: Path, relative: str, model_type: type[Any]) -> Any:
    """Load one strict retention model from a contained immutable path."""

    path = _contained_path(repo, relative, must_exist=True)
    return model_type.model_validate_json(_read_regular_bytes(path))


def _artifact(repo: Path, path: Path, *, kind: str) -> StorageArtifact:
    """Bind one existing retention artifact by relative path, digest, and size."""

    relative = _relative_path(repo, path)
    return StorageArtifact(
        kind=kind,
        path=relative,
        sha256=sha256_file(path),
        byte_size=os.path.getsize(native_io_path(path)),
    )


def _git_bytes(repo: Path, arguments: Sequence[str]) -> bytes:
    """Run one bounded read-only Git query without a shell."""

    result = subprocess.run(
        ["git", *arguments],
        cwd=native_io_path(repo),
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Git query failed: {message}")
    return result.stdout


def _repository_commit(repo: Path) -> str:
    """Return the current exact Git commit without claiming a clean worktree."""

    value = _git_bytes(repo, ["rev-parse", "HEAD"]).decode("ascii").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40,64}", value):
        raise ValueError("repository HEAD is not a hexadecimal commit")
    return value


def _tracked_and_unignored_files(repo: Path) -> list[str]:
    """List tracked and unignored source files whose bytes can add temp references."""

    tracked_raw = _git_bytes(repo, ["ls-files", "-c", "-z"])
    untracked_raw = _git_bytes(repo, ["ls-files", "-o", "--exclude-standard", "-z"])
    tracked = {
        item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for item in tracked_raw.split(b"\0")
        if item
    }
    untracked = {
        item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for item in untracked_raw.split(b"\0")
        if item
    }
    values = tracked | {
        value
        for value in untracked
        if not value.startswith(".b/") and not value.startswith(".t/")
    }
    excluded_roots = (
        _CONTROL_ROOT.as_posix(),
        _GATE_RECEIPT_ROOT.as_posix(),
        _OPERATION_ROOT.as_posix(),
        *[root.as_posix() for root in _PROTECTION_SCAN_ROOTS],
    )
    return sorted(
        (
            value
            for value in values
            if not any(value == root or value.startswith(root + "/") for root in excluded_roots)
        ),
        key=str.casefold,
    )


def _is_separately_scanned_internal_alias(scan_root: Path, member: Path) -> bool:
    """Accept only link targets independently reachable inside the same evidence root."""

    try:
        resolved = _absolute_lexical(member.resolve(strict=True))
        boundary = _absolute_lexical(scan_root)
        resolved.relative_to(boundary)
        _assert_no_link_ancestors(resolved, include_leaf=True)
        metadata = os.lstat(native_io_path(resolved))
    except (OSError, ValueError):
        return False
    return not _is_link_or_reparse_metadata(metadata) and (
        stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
    )


def _walk_json_files(repo: Path, root: Path, inaccessible: list[str]) -> Iterable[Path]:
    """Yield deterministic regular JSON files while refusing linked preserved evidence."""

    absolute = _absolute_lexical(repo / root)
    if not os.path.lexists(native_io_path(absolute)):
        return
    pending = [absolute]
    while pending:
        current = pending.pop()
        try:
            metadata = os.lstat(native_io_path(current))
            if _is_link_or_reparse_metadata(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise _UnsafeTreeError(f"preserved evidence root is linked or invalid: {current}")
            with os.scandir(native_io_path(current)) as iterator:
                entries = sorted(list(iterator), key=lambda item: item.name.casefold())
        except (OSError, _UnsafeTreeError):
            inaccessible.append(_relative_path(repo, current))
            continue
        directories: list[Path] = []
        for entry in entries:
            member = current / entry.name
            relative = _relative_path(repo, member)
            if relative == _CONTROL_ROOT.as_posix() or relative.startswith(
                _CONTROL_ROOT.as_posix() + "/"
            ):
                continue
            try:
                member_metadata = entry.stat(follow_symlinks=False)
            except OSError:
                inaccessible.append(relative)
                continue
            if entry.is_symlink() or _is_link_or_reparse_metadata(member_metadata):
                if not _is_separately_scanned_internal_alias(absolute, member):
                    inaccessible.append(relative)
            elif stat.S_ISDIR(member_metadata.st_mode):
                directories.append(member)
            elif stat.S_ISREG(member_metadata.st_mode) and entry.name.lower().endswith(
                ".json"
            ):
                yield member
        pending.extend(reversed(directories))


def _extract_temp_references(data: bytes) -> tuple[set[str], set[str]]:
    """Extract conservative `.b`/`.t` path literals and lowercase SHA-256 anchors."""

    text = data.decode("utf-8", errors="ignore").replace("\\", "/")
    paths = {match.group(1).rstrip(".,;:") for match in _TEMP_PATH_RE.finditer(text)}
    hashes = {match.group(0).decode("ascii") for match in _SHA256_RE.finditer(data.lower())}
    return paths, hashes


def _scan_protection_sources(repo: Path) -> _ProtectionIndex:
    """Build a fail-closed index from tracked text and preserved machine JSON."""

    inaccessible: list[str] = []
    selected: set[str] = set(_tracked_and_unignored_files(repo))
    for root in _PROTECTION_SCAN_ROOTS:
        for path in _walk_json_files(repo, root, inaccessible):
            selected.add(_relative_path(repo, path))

    digest = hashlib.sha256()
    protected_paths: set[str] = {
        relative
        for relative in selected
        if relative.startswith(".b/") or relative.startswith(".t/")
    }
    protected_hashes: set[str] = set()
    verified_success_roots: set[str] = set()
    for relative in sorted(selected, key=str.casefold):
        try:
            path = _contained_path(repo, relative, must_exist=True)
            data = _read_regular_bytes(path)
        except (OSError, ValueError):
            inaccessible.append(relative)
            continue
        file_sha256 = hashlib.sha256(data).hexdigest()
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(file_sha256.encode("ascii"))
        digest.update(b"\n")

        gate_prefix = _GATE_RECEIPT_ROOT.as_posix() + "/"
        if relative.startswith(gate_prefix) and relative.endswith("/preflight.json"):
            continue
        if relative.startswith(gate_prefix) and relative.endswith("/receipt.json"):
            try:
                receipt = GateRunReceiptV01.model_validate_json(data)
            except ValueError:
                inaccessible.append(relative)
                continue
            if (
                receipt.gate_outcome == "passed"
                and receipt.retention_outcome == "preserved_by_policy"
            ):
                verified_success_roots.add(receipt.run_root)
                if receipt.process_temp_root is not None:
                    verified_success_roots.add(receipt.process_temp_root)
            continue

        paths, hashes = _extract_temp_references(data)
        protected_paths.update(paths)
        protected_hashes.update(hashes)

    normalized_inaccessible = tuple(sorted(set(inaccessible), key=str.casefold))
    for relative in normalized_inaccessible:
        digest.update(b"inaccessible\0")
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\n")
    return _ProtectionIndex(
        relative_paths=frozenset(protected_paths),
        sha256_values=frozenset(protected_hashes),
        verified_success_roots=frozenset(verified_success_roots),
        source_sha256=digest.hexdigest(),
        inaccessible_paths=normalized_inaccessible,
    )


def _scan_tree(
    root: Path,
    *,
    hash_tree: bool,
    protected_hashes: frozenset[str] = frozenset(),
    allow_link_members: bool = False,
) -> _TreeScan:
    """Traverse one tree without following links and hash allowed members deterministically."""

    absolute = _absolute_lexical(root)
    metadata = os.lstat(native_io_path(absolute))
    if _is_link_or_reparse_metadata(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise _UnsafeTreeError("temporary candidate root is linked or not a directory")
    digest = hashlib.sha256() if hash_tree else None
    file_count = 0
    directory_count = 1
    byte_size = 0
    newest_mtime_ns = metadata.st_mtime_ns
    link_found = False
    lock_found = False
    owner_pids: set[int] = set()
    matched_hashes: set[str] = set()
    if digest is not None:
        digest.update(b'{"path":".","type":"directory"}\n')

    pending = [absolute]
    while pending:
        current = pending.pop()
        with os.scandir(native_io_path(current)) as iterator:
            entries = sorted(list(iterator), key=lambda item: item.name.casefold())
        directories: list[Path] = []
        for entry in entries:
            member = current / entry.name
            member_metadata = entry.stat(follow_symlinks=False)
            if entry.is_symlink() or _is_link_or_reparse_metadata(member_metadata):
                if not allow_link_members:
                    raise _UnsafeTreeError(
                        "temporary candidate contains a link or reparse point"
                    )
                link_found = True
                file_count += 1
                newest_mtime_ns = max(newest_mtime_ns, member_metadata.st_mtime_ns)
                relative = member.relative_to(absolute).as_posix()
                if entry.name.endswith(_LOCK_SUFFIXES):
                    lock_found = True
                if digest is not None:
                    link_target = os.readlink(native_io_path(member))
                    record = {
                        "path": relative,
                        "target_sha256": hashlib.sha256(
                            os.fsencode(link_target)
                        ).hexdigest(),
                        "type": "link",
                    }
                    digest.update(
                        json.dumps(record, sort_keys=True, separators=(",", ":")).encode(
                            "utf-8"
                        )
                        + b"\n"
                    )
                continue
            newest_mtime_ns = max(newest_mtime_ns, member_metadata.st_mtime_ns)
            relative = member.relative_to(absolute).as_posix()
            if stat.S_ISDIR(member_metadata.st_mode):
                directory_count += 1
                directories.append(member)
                if digest is not None:
                    record = {"path": relative, "type": "directory"}
                    digest.update(
                        json.dumps(record, sort_keys=True, separators=(",", ":")).encode(
                            "utf-8"
                        )
                        + b"\n"
                    )
                continue
            if not stat.S_ISREG(member_metadata.st_mode):
                raise _UnsafeTreeError("temporary candidate contains an unsupported entry")
            file_count += 1
            byte_size += member_metadata.st_size
            if entry.name.endswith(_LOCK_SUFFIXES):
                lock_found = True
            if entry.name == _OWNER_MARKER:
                try:
                    payload = json.loads(_read_regular_bytes(member))
                    pid = payload.get("pid") if isinstance(payload, dict) else None
                    if isinstance(pid, int) and pid > 0:
                        owner_pids.add(pid)
                except (OSError, ValueError, json.JSONDecodeError):
                    lock_found = True
            if digest is not None:
                file_sha256 = sha256_file(member)
                if file_sha256 in protected_hashes:
                    matched_hashes.add(file_sha256)
                record = {
                    "byte_size": member_metadata.st_size,
                    "path": relative,
                    "sha256": file_sha256,
                    "type": "file",
                }
                digest.update(
                    json.dumps(record, sort_keys=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                    + b"\n"
                )
        pending.extend(reversed(directories))
    return _TreeScan(
        tree_sha256=digest.hexdigest() if digest is not None else None,
        file_count=file_count,
        directory_count=directory_count,
        byte_size=byte_size,
        newest_mtime_ns=newest_mtime_ns,
        link_found=link_found,
        lock_found=lock_found,
        owner_pids=tuple(sorted(owner_pids)),
        matched_protected_hashes=tuple(sorted(matched_hashes)),
    )


def _pid_alive(pid: int) -> bool:
    """Conservatively report whether one process identifier may still be active."""

    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _entry_kind(name: str) -> StorageEntryKind:
    """Classify only recognizable run-owned or cache-shaped temporary roots."""

    lowered = name.casefold()
    if lowered.endswith("-process-temp"):
        return "process_temp"
    if lowered in {".pytest_cache", ".ruff_cache", "uv-cache", ".uv-cache"}:
        return "cache"
    if re.match(r"^(?:v[789]p-|aqg-|gate-)", lowered):
        return "gate_run"
    if any(token in lowered for token in ("pytest", "full", "focused", "blender")):
        return "pytest_basetemp"
    return "unknown"


def _entry_has_reference(relative: str, references: frozenset[str]) -> bool:
    """Protect an entire immediate run root when any exact descendant is referenced."""

    folded = relative.casefold()
    prefix = folded + "/"
    return any(
        reference.casefold() == folded
        or reference.casefold().startswith(prefix)
        or folded.startswith(reference.casefold() + "/")
        for reference in references
    )


def _candidate_pid(name: str) -> int | None:
    """Extract a conventional trailing process ID from one gate-run directory name."""

    match = _PID_SUFFIX_RE.search(name)
    return int(match.group(1)) if match else None


def _classify_entry(
    repo: Path,
    root_name: str,
    entry: os.DirEntry[str],
    *,
    protection: _ProtectionIndex,
    minimum_age: timedelta,
    now: datetime,
) -> tuple[StorageTreeEntry, str | None]:
    """Inspect and fail-closed classify one immediate temporary-root child."""

    relative = f"{root_name}/{entry.name}"
    kind = _entry_kind(entry.name)
    try:
        metadata = entry.stat(follow_symlinks=False)
        if entry.is_symlink() or _is_link_or_reparse_metadata(metadata):
            raise _UnsafeTreeError("LINK_OR_REPARSE_POINT")
        if not stat.S_ISDIR(metadata.st_mode):
            raise _UnsafeTreeError("NOT_A_DIRECTORY")
        scan = _scan_tree(Path(entry.path), hash_tree=False, allow_link_members=True)
    except (OSError, _UnsafeTreeError) as exc:
        reason = str(exc) or type(exc).__name__
        return (
            StorageTreeEntry(
                path=relative,
                root=root_name,
                kind=kind,
                disposition="protected",
                reasons=[f"UNREADABLE_OR_UNSAFE:{reason}"],
                file_count=0,
                directory_count=1,
                byte_size=0,
                tree_sha256=None,
                newest_mtime_ns=max(0, getattr(locals().get("metadata"), "st_mtime_ns", 0)),
                matched_protected_hashes=[],
            ),
            relative,
        )

    reasons: list[str] = []
    if protection.inaccessible_paths:
        reasons.append("PROTECTION_INDEX_INCOMPLETE")
    if scan.link_found:
        reasons.append("CONTAINS_LINK_OR_REPARSE_POINT")
    if _entry_has_reference(relative, protection.relative_paths):
        reasons.append("REFERENCED_BY_PRESERVED_EVIDENCE")
    newest = datetime.fromtimestamp(scan.newest_mtime_ns / 1_000_000_000, tz=UTC)
    if now - newest < minimum_age:
        reasons.append("MINIMUM_AGE_NOT_REACHED")
    candidate_pid = _candidate_pid(entry.name)
    active_pids = set(scan.owner_pids)
    if candidate_pid is not None:
        active_pids.add(candidate_pid)
    if scan.lock_found or any(_pid_alive(pid) for pid in active_pids):
        reasons.append("ACTIVE_OR_LOCKED")

    if not reasons:
        if kind == "cache":
            reasons.append("RECREATABLE_CACHE")
        elif relative in protection.verified_success_roots:
            reasons.append("VERIFIED_SUCCESS_RUN")
        elif kind == "process_temp":
            paired = repo / root_name / entry.name[: -len("-process-temp")]
            if not os.path.lexists(native_io_path(paired)):
                reasons.append("ORPHAN_PROCESS_TEMP")
            else:
                reasons.append("UNKNOWN_PAIRED_RUN_OUTCOME")
        else:
            reasons.append("UNKNOWN_RUN_OUTCOME")

    eligible_codes = {"RECREATABLE_CACHE", "VERIFIED_SUCCESS_RUN", "ORPHAN_PROCESS_TEMP"}
    disposition = "eligible" if set(reasons) <= eligible_codes else "protected"
    tree_sha256: str | None = None
    matched_hashes: tuple[str, ...] = ()
    if disposition == "eligible":
        exact = _scan_tree(
            Path(entry.path),
            hash_tree=True,
            protected_hashes=protection.sha256_values,
        )
        tree_sha256 = exact.tree_sha256
        matched_hashes = exact.matched_protected_hashes
        scan = exact
        if matched_hashes:
            disposition = "protected"
            reasons = ["MATCHES_PROTECTED_ARTIFACT_HASH"]
            tree_sha256 = None
    return (
        StorageTreeEntry(
            path=relative,
            root=root_name,
            kind=kind,
            disposition=disposition,
            reasons=reasons,
            file_count=scan.file_count,
            directory_count=scan.directory_count,
            byte_size=scan.byte_size,
            tree_sha256=tree_sha256,
            newest_mtime_ns=scan.newest_mtime_ns,
            matched_protected_hashes=list(matched_hashes),
        ),
        None,
    )


def _inventory_path(inventory_id: str) -> str:
    """Return the immutable repository-relative path for one inventory."""

    return f"{_CONTROL_ROOT.as_posix()}/inventories/{_validate_portable_id(inventory_id)}.json"


def _plan_path(plan_id: str) -> str:
    """Return the immutable repository-relative path for one cleanup plan."""

    return f"{_CONTROL_ROOT.as_posix()}/plans/{_validate_portable_id(plan_id)}.json"


def _receipt_path(receipt_id: str, *, attempt: bool = False) -> str:
    """Return the immutable path for a completed or partial cleanup receipt."""

    branch = "attempts" if attempt else "receipts"
    return f"{_CONTROL_ROOT.as_posix()}/{branch}/{_validate_portable_id(receipt_id)}.json"


def inventory_repository_storage(
    *,
    repo_root: Path | None = None,
    roots: Sequence[str] = _ALLOWED_ROOTS,
    minimum_age_hours: int = 24,
    now: datetime | None = None,
) -> StorageInventoryV01:
    """Publish a non-destructive inventory of exact `.b` and `.t` child trees."""

    repo = _repo_root(repo_root)
    normalized_roots = sorted(set(roots))
    if not normalized_roots or any(root not in _ALLOWED_ROOTS for root in normalized_roots):
        raise ValueError("storage inventory roots are restricted to .b and .t")
    if minimum_age_hours < 1 or minimum_age_hours > 8760:
        raise ValueError("minimum_age_hours must be within [1, 8760]")
    observed_at = (now or _utc_now()).astimezone(UTC)
    protection = _scan_protection_sources(repo)
    entries: list[StorageTreeEntry] = []
    inaccessible = list(protection.inaccessible_paths)
    for root_name in normalized_roots:
        root = repo / root_name
        if not os.path.lexists(native_io_path(root)):
            continue
        try:
            root_metadata = os.lstat(native_io_path(root))
            if _is_link_or_reparse_metadata(root_metadata) or not stat.S_ISDIR(
                root_metadata.st_mode
            ):
                raise _UnsafeTreeError("temporary root is linked or invalid")
            with os.scandir(native_io_path(root)) as iterator:
                children = sorted(list(iterator), key=lambda item: item.name.casefold())
        except (OSError, _UnsafeTreeError):
            inaccessible.append(root_name)
            continue
        for child in children:
            if not child.is_dir(follow_symlinks=False) and not child.is_symlink():
                continue
            record, inaccessible_path = _classify_entry(
                repo,
                root_name,
                child,
                protection=protection,
                minimum_age=timedelta(hours=minimum_age_hours),
                now=observed_at,
            )
            entries.append(record)
            if inaccessible_path is not None:
                inaccessible.append(inaccessible_path)
    entries.sort(key=lambda item: item.path.casefold())
    inaccessible = sorted(set(inaccessible), key=str.casefold)
    eligible_bytes = sum(
        entry.byte_size for entry in entries if entry.disposition == "eligible"
    )
    protected_bytes = sum(
        entry.byte_size for entry in entries if entry.disposition == "protected"
    )
    payload: dict[str, Any] = {
        "schema_version": "0.1.0",
        "inventory_id": _new_id("storage-inventory"),
        "repository_commit": _repository_commit(repo),
        "protection_source_sha256": protection.source_sha256,
        "roots": normalized_roots,
        "minimum_age_hours": minimum_age_hours,
        "status": "partial" if inaccessible else "complete",
        "entries": [entry.model_dump(mode="json") for entry in entries],
        "inaccessible_paths": inaccessible,
        "total_byte_size": eligible_bytes + protected_bytes,
        "eligible_byte_size": eligible_bytes,
        "protected_byte_size": protected_bytes,
        "generated_at": _json_timestamp(observed_at),
    }
    payload["input_sha256"] = storage_input_sha256(payload)
    inventory = StorageInventoryV01.model_validate(payload)
    _write_immutable_model(repo, _inventory_path(inventory.inventory_id), inventory)
    return inventory


def _load_inventory(repo: Path, inventory_id: str) -> tuple[StorageInventoryV01, Path]:
    """Load one persisted inventory and return its exact artifact path."""

    relative = _inventory_path(inventory_id)
    path = _contained_path(repo, relative, must_exist=True)
    return StorageInventoryV01.model_validate_json(_read_regular_bytes(path)), path


def plan_storage_cleanup(
    inventory_id: str,
    *,
    repo_root: Path | None = None,
) -> StorageCleanupPlanV01:
    """Publish an exact plan containing only unchanged inventory-eligible trees."""

    repo = _repo_root(repo_root)
    inventory, inventory_path = _load_inventory(repo, inventory_id)
    if inventory.repository_commit != _repository_commit(repo):
        raise ValueError("repository commit changed after storage inventory")
    protection = _scan_protection_sources(repo)
    if protection.source_sha256 != inventory.protection_source_sha256:
        raise ValueError("retention protection sources changed after inventory")

    candidates: list[StorageCleanupCandidate] = []
    for entry in inventory.entries:
        if entry.disposition != "eligible":
            continue
        candidate_path = _contained_path(repo, entry.path, must_exist=True)
        snapshot = _scan_tree(
            candidate_path,
            hash_tree=True,
            protected_hashes=protection.sha256_values,
        )
        if snapshot.matched_protected_hashes:
            raise ValueError(f"cleanup candidate now matches protected evidence: {entry.path}")
        if (
            snapshot.tree_sha256 != entry.tree_sha256
            or snapshot.file_count != entry.file_count
            or snapshot.directory_count != entry.directory_count
            or snapshot.byte_size != entry.byte_size
        ):
            raise ValueError(f"cleanup candidate changed after inventory: {entry.path}")
        candidates.append(
            StorageCleanupCandidate(
                path=entry.path,
                root=entry.root,
                kind=entry.kind,
                tree_sha256=snapshot.tree_sha256,
                file_count=snapshot.file_count,
                directory_count=snapshot.directory_count,
                byte_size=snapshot.byte_size,
            )
        )
    candidates.sort(key=lambda item: item.path.casefold())
    payload: dict[str, Any] = {
        "schema_version": "0.1.0",
        "plan_id": _new_id("storage-cleanup"),
        "inventory": _artifact(repo, inventory_path, kind="storage_inventory").model_dump(
            mode="json"
        ),
        "repository_commit": inventory.repository_commit,
        "protection_source_sha256": inventory.protection_source_sha256,
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "expected_reclaimable_bytes": sum(item.byte_size for item in candidates),
        "excluded_entry_count": len(inventory.entries) - len(candidates),
        "created_at": _json_timestamp(_utc_now()),
    }
    payload["input_sha256"] = storage_input_sha256(payload)
    plan = StorageCleanupPlanV01.model_validate(payload)
    _write_immutable_model(repo, _plan_path(plan.plan_id), plan)
    return plan


def _load_plan(repo: Path, plan_id: str) -> tuple[StorageCleanupPlanV01, Path]:
    """Load one persisted cleanup plan and return its exact artifact path."""

    relative = _plan_path(plan_id)
    path = _contained_path(repo, relative, must_exist=True)
    return StorageCleanupPlanV01.model_validate_json(_read_regular_bytes(path)), path


def _validate_immediate_candidate(path: str) -> None:
    """Require an exact immediate child of `.b` or `.t`, never either root itself."""

    parts = path.split("/")
    if len(parts) != 2 or parts[0] not in _ALLOWED_ROOTS:
        raise ValueError("cleanup candidates must be immediate children of .b or .t")


def _candidate_token(path: str) -> str:
    """Create a collision-resistant quarantine member name from a relative path."""

    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def _capture_marker_path(plan_id: str, candidate: StorageCleanupCandidate) -> str:
    """Return the append-only capture marker path for one cleanup candidate."""

    return (
        f"{_OPERATION_ROOT.as_posix()}/operations/{_validate_portable_id(plan_id)}/"
        f"{_candidate_token(candidate.path)}.captured.json"
    )


def _removed_marker_path(plan_id: str, candidate: StorageCleanupCandidate) -> str:
    """Return the append-only removal marker path for one cleanup candidate."""

    return (
        f"{_OPERATION_ROOT.as_posix()}/operations/{_validate_portable_id(plan_id)}/"
        f"{_candidate_token(candidate.path)}.removed.json"
    )


def _quarantine_path(repo: Path, plan_id: str, candidate: StorageCleanupCandidate) -> Path:
    """Resolve one exact candidate-specific quarantine path inside the repository."""

    relative = (
        f"{_OPERATION_ROOT.as_posix()}/quarantine/{_validate_portable_id(plan_id)}/"
        f"{_candidate_token(candidate.path)}"
    )
    return _contained_path(repo, relative, must_exist=False)


def _marker_payload(
    plan: StorageCleanupPlanV01,
    candidate: StorageCleanupCandidate,
    *,
    state: str,
) -> dict[str, Any]:
    """Build one deterministic candidate operation marker."""

    return {
        "schema_version": "0.1.0",
        "plan_id": plan.plan_id,
        "plan_input_sha256": plan.input_sha256,
        "candidate": candidate.model_dump(mode="json"),
        "state": state,
    }


def _write_operation_marker(
    repo: Path,
    relative: str,
    payload: dict[str, Any],
) -> None:
    """Publish one append-only operational marker used for crash-safe cleanup resume."""

    destination = _contained_path(repo, relative, must_exist=False)
    _ensure_directory(repo, destination.parent.relative_to(repo).as_posix())
    publish_bytes_create_once(destination, deterministic_json_bytes(payload))


def _unlink_link_member(path: Path, metadata: os.stat_result) -> None:
    """Remove one link or junction entry without traversing or modifying its target."""

    if os.name == "nt" and stat.S_ISDIR(metadata.st_mode):
        os.rmdir(native_io_path(path))
        return
    os.unlink(native_io_path(path))


def _unlink_regular_member(path: Path, metadata: os.stat_result) -> None:
    """Remove one regular file, clearing only a Windows read-only deletion barrier."""

    try:
        os.unlink(native_io_path(path))
    except PermissionError:
        if os.name != "nt":
            raise
        os.chmod(native_io_path(path), metadata.st_mode | stat.S_IWRITE)
        os.unlink(native_io_path(path))


def _remove_regular_directory(path: Path) -> None:
    """Remove one empty ordinary directory with a bounded Windows retry."""

    try:
        os.rmdir(native_io_path(path))
    except PermissionError:
        if os.name != "nt":
            raise
        os.chmod(native_io_path(path), stat.S_IWRITE)
        os.rmdir(native_io_path(path))


def _safe_remove_tree(
    root: Path,
    *,
    quarantine_root: Path,
    allow_link_members: bool = False,
) -> None:
    """Delete one exact quarantined tree without ever following linked members."""

    absolute = _absolute_lexical(root)
    boundary = _absolute_lexical(quarantine_root)
    absolute.relative_to(boundary)
    if absolute == boundary:
        raise ValueError("cannot remove the quarantine root itself")
    _assert_no_link_ancestors(absolute, include_leaf=True)
    metadata = os.lstat(native_io_path(absolute))
    if _is_link_or_reparse_metadata(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise _UnsafeTreeError("quarantined cleanup candidate is linked or invalid")
    pending: list[tuple[Path, bool]] = [(absolute, False)]
    while pending:
        current, visited = pending.pop()
        if visited:
            _remove_regular_directory(current)
            continue
        current_metadata = os.lstat(native_io_path(current))
        if _is_link_or_reparse_metadata(current_metadata) or not stat.S_ISDIR(
            current_metadata.st_mode
        ):
            raise _UnsafeTreeError("quarantine member changed into a link or non-directory")
        pending.append((current, True))
        with os.scandir(native_io_path(current)) as iterator:
            entries = sorted(list(iterator), key=lambda item: item.name.casefold(), reverse=True)
        for entry in entries:
            member = current / entry.name
            member_metadata = entry.stat(follow_symlinks=False)
            if entry.is_symlink() or _is_link_or_reparse_metadata(member_metadata):
                if not allow_link_members:
                    raise _UnsafeTreeError(
                        "quarantine member contains a link or reparse point"
                    )
                _unlink_link_member(member, member_metadata)
                continue
            if stat.S_ISDIR(member_metadata.st_mode):
                pending.append((member, False))
            elif stat.S_ISREG(member_metadata.st_mode):
                _unlink_regular_member(member, member_metadata)
            else:
                raise _UnsafeTreeError("quarantine member contains an unsupported entry")


def _load_completed_receipt(
    repo: Path,
    plan_id: str,
) -> StorageCleanupReceiptV01 | None:
    """Return an already completed plan receipt for idempotent apply or resume."""

    receipt_id = f"receipt-{_validate_portable_id(plan_id)}"
    relative = _receipt_path(receipt_id)
    path = _contained_path(repo, relative, must_exist=False)
    if not os.path.isfile(native_io_path(path)):
        return None
    receipt = StorageCleanupReceiptV01.model_validate_json(_read_regular_bytes(path))
    verify_storage_cleanup_receipt(receipt.receipt_id, repo_root=repo)
    return receipt


def _build_cleanup_receipt(
    repo: Path,
    plan: StorageCleanupPlanV01,
    plan_path: Path,
    results: list[StorageCleanupResult],
    *,
    completed: bool,
) -> StorageCleanupReceiptV01:
    """Publish one immutable completed or partial cleanup execution receipt."""

    sorted_results = sorted(results, key=lambda item: item.path.casefold())
    receipt_id = (
        f"receipt-{plan.plan_id}"
        if completed
        else f"attempt-{plan.plan_id}-{uuid4().hex[:8]}"
    )
    payload: dict[str, Any] = {
        "schema_version": "0.1.0",
        "receipt_id": receipt_id,
        "plan": _artifact(repo, plan_path, kind="storage_cleanup_plan").model_dump(
            mode="json"
        ),
        "status": "completed" if completed else "partial",
        "results": [item.model_dump(mode="json") for item in sorted_results],
        "reclaimed_byte_size": sum(
            item.byte_size for item in sorted_results if item.status == "removed"
        ),
        "completed_at": _json_timestamp(_utc_now()),
    }
    payload["input_sha256"] = storage_input_sha256(payload)
    receipt = StorageCleanupReceiptV01.model_validate(payload)
    _write_immutable_model(
        repo,
        _receipt_path(receipt.receipt_id, attempt=not completed),
        receipt,
    )
    return receipt


def _preflight_cleanup_plan(repo: Path, plan: StorageCleanupPlanV01) -> None:
    """Revalidate all protection sources and uncaptured candidates before deletion."""

    if plan.repository_commit != _repository_commit(repo):
        raise ValueError("repository commit changed after cleanup planning")
    protection = _scan_protection_sources(repo)
    if protection.source_sha256 != plan.protection_source_sha256:
        raise ValueError("retention protection sources changed after cleanup planning")
    for candidate in plan.candidates:
        _validate_immediate_candidate(candidate.path)
        source = _contained_path(repo, candidate.path, must_exist=False)
        quarantine = _quarantine_path(repo, plan.plan_id, candidate)
        captured = _contained_path(
            repo,
            _capture_marker_path(plan.plan_id, candidate),
            must_exist=False,
        )
        if os.path.isfile(native_io_path(captured)):
            source_exists = os.path.lexists(native_io_path(source))
            quarantine_exists = os.path.lexists(native_io_path(quarantine))
            if source_exists:
                raise ValueError("captured cleanup candidate reappeared at its source path")
            if quarantine_exists and _is_link_like(quarantine):
                raise _UnsafeTreeError("captured cleanup quarantine became a link")
            continue
        if os.path.lexists(native_io_path(quarantine)):
            snapshot = _scan_tree(
                quarantine,
                hash_tree=True,
                protected_hashes=protection.sha256_values,
            )
        else:
            snapshot = _scan_tree(
                _contained_path(repo, candidate.path, must_exist=True),
                hash_tree=True,
                protected_hashes=protection.sha256_values,
            )
        if snapshot.matched_protected_hashes:
            raise ValueError(f"cleanup candidate matches protected evidence: {candidate.path}")
        if (
            snapshot.tree_sha256 != candidate.tree_sha256
            or snapshot.file_count != candidate.file_count
            or snapshot.directory_count != candidate.directory_count
            or snapshot.byte_size != candidate.byte_size
        ):
            raise ValueError(f"cleanup candidate is stale: {candidate.path}")
        if os.path.lexists(native_io_path(source)) and os.path.lexists(
            native_io_path(quarantine)
        ):
            raise FileExistsError("cleanup source and quarantine destination both exist")


def _execute_cleanup_plan(
    repo: Path,
    plan: StorageCleanupPlanV01,
    plan_path: Path,
) -> StorageCleanupReceiptV01:
    """Capture, remove, and receipt every exact candidate with crash-safe markers."""

    existing = _load_completed_receipt(repo, plan.plan_id)
    if existing is not None:
        return existing
    _preflight_cleanup_plan(repo, plan)
    quarantine_root = _ensure_directory(repo, f"{_OPERATION_ROOT.as_posix()}/quarantine")
    results: list[StorageCleanupResult] = []
    failed = False
    for candidate in plan.candidates:
        source = _contained_path(repo, candidate.path, must_exist=False)
        quarantine = _quarantine_path(repo, plan.plan_id, candidate)
        capture_relative = _capture_marker_path(plan.plan_id, candidate)
        removed_relative = _removed_marker_path(plan.plan_id, candidate)
        capture_marker = _contained_path(repo, capture_relative, must_exist=False)
        removed_marker = _contained_path(repo, removed_relative, must_exist=False)
        try:
            if not os.path.isfile(native_io_path(capture_marker)):
                _ensure_directory(repo, quarantine.parent.relative_to(repo).as_posix())
                if os.path.lexists(native_io_path(source)) and not os.path.lexists(
                    native_io_path(quarantine)
                ):
                    os.replace(native_io_path(source), native_io_path(quarantine))
                elif not os.path.lexists(native_io_path(quarantine)):
                    raise FileNotFoundError("cleanup candidate disappeared before capture")
                snapshot = _scan_tree(quarantine, hash_tree=True)
                if (
                    snapshot.tree_sha256 != candidate.tree_sha256
                    or snapshot.file_count != candidate.file_count
                    or snapshot.directory_count != candidate.directory_count
                    or snapshot.byte_size != candidate.byte_size
                ):
                    if not os.path.lexists(native_io_path(source)):
                        os.replace(native_io_path(quarantine), native_io_path(source))
                    raise ValueError("captured cleanup candidate differs from its plan")
                _write_operation_marker(
                    repo,
                    capture_relative,
                    _marker_payload(plan, candidate, state="captured"),
                )
            elif os.path.lexists(native_io_path(source)):
                raise ValueError("captured cleanup candidate reappeared at its source path")
            if not os.path.isfile(native_io_path(removed_marker)):
                if os.path.lexists(native_io_path(quarantine)):
                    _safe_remove_tree(quarantine, quarantine_root=quarantine_root)
                _write_operation_marker(
                    repo,
                    removed_relative,
                    _marker_payload(plan, candidate, state="removed"),
                )
            results.append(
                StorageCleanupResult(
                    path=candidate.path,
                    tree_sha256=candidate.tree_sha256,
                    byte_size=candidate.byte_size,
                    status="removed",
                    message="Exact quarantined temporary tree removed.",
                )
            )
        except (OSError, ValueError) as exc:
            failed = True
            results.append(
                StorageCleanupResult(
                    path=candidate.path,
                    tree_sha256=candidate.tree_sha256,
                    byte_size=candidate.byte_size,
                    status="remaining",
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
            break
    if failed:
        completed_paths = {item.path for item in results}
        for candidate in plan.candidates:
            if candidate.path in completed_paths:
                continue
            results.append(
                StorageCleanupResult(
                    path=candidate.path,
                    tree_sha256=candidate.tree_sha256,
                    byte_size=candidate.byte_size,
                    status="remaining",
                    message="Not attempted after an earlier cleanup failure.",
                )
            )
    return _build_cleanup_receipt(
        repo,
        plan,
        plan_path,
        results,
        completed=not failed,
    )


def apply_storage_cleanup(
    plan_id: str,
    *,
    confirm_plan_sha256: str,
    repo_root: Path | None = None,
) -> StorageCleanupReceiptV01:
    """Execute only a persisted plan whose exact file digest was externally confirmed."""

    repo = _repo_root(repo_root)
    plan, plan_path = _load_plan(repo, plan_id)
    if not re.fullmatch(r"[0-9a-f]{64}", confirm_plan_sha256):
        raise ValueError("confirm_plan_sha256 must be one lowercase SHA-256")
    if sha256_file(plan_path) != confirm_plan_sha256:
        raise PermissionError("cleanup plan confirmation SHA-256 does not match")
    return _execute_cleanup_plan(repo, plan, plan_path)


def resume_storage_cleanup(
    plan_id: str,
    *,
    confirm_plan_sha256: str,
    repo_root: Path | None = None,
) -> StorageCleanupReceiptV01:
    """Resume or exact-adopt one previously confirmed cleanup plan."""

    return apply_storage_cleanup(
        plan_id,
        confirm_plan_sha256=confirm_plan_sha256,
        repo_root=repo_root,
    )


def _find_receipt_path(repo: Path, receipt_id: str) -> Path:
    """Locate one completed or partial receipt without accepting arbitrary paths."""

    _validate_portable_id(receipt_id)
    for attempt in (False, True):
        relative = _receipt_path(receipt_id, attempt=attempt)
        path = _contained_path(repo, relative, must_exist=False)
        if os.path.isfile(native_io_path(path)):
            return path
    raise FileNotFoundError(f"storage cleanup receipt does not exist: {receipt_id}")


def verify_storage_cleanup_receipt(
    receipt_id: str,
    *,
    repo_root: Path | None = None,
) -> StorageCleanupReceiptV01:
    """Validate a cleanup receipt, its exact plan, and every claimed removed path."""

    repo = _repo_root(repo_root)
    receipt_path = _find_receipt_path(repo, receipt_id)
    receipt = StorageCleanupReceiptV01.model_validate_json(
        _read_regular_bytes(receipt_path)
    )
    plan_path = _contained_path(repo, receipt.plan.path, must_exist=True)
    if (
        sha256_file(plan_path) != receipt.plan.sha256
        or os.path.getsize(native_io_path(plan_path)) != receipt.plan.byte_size
    ):
        raise ValueError("cleanup receipt plan artifact is stale")
    plan = StorageCleanupPlanV01.model_validate_json(_read_regular_bytes(plan_path))
    expected = {item.path: item for item in plan.candidates}
    if any(result.path not in expected for result in receipt.results):
        raise ValueError("cleanup receipt contains an unplanned result")
    if receipt.status == "completed" and {item.path for item in receipt.results} != set(
        expected
    ):
        raise ValueError("completed cleanup receipt omitted planned candidates")
    for result in receipt.results:
        candidate = expected[result.path]
        if (
            result.tree_sha256 != candidate.tree_sha256
            or result.byte_size != candidate.byte_size
        ):
            raise ValueError("cleanup receipt result differs from its planned candidate")
        if result.status == "removed":
            source = _contained_path(repo, result.path, must_exist=False)
            quarantine = _quarantine_path(repo, plan.plan_id, candidate)
            removed_marker = _contained_path(
                repo,
                _removed_marker_path(plan.plan_id, candidate),
                must_exist=True,
            )
            if os.path.lexists(native_io_path(source)) or os.path.lexists(
                native_io_path(quarantine)
            ):
                raise ValueError("cleanup receipt claims removal while tree still exists")
            payload = json.loads(_read_regular_bytes(removed_marker))
            if payload != _marker_payload(plan, candidate, state="removed"):
                raise ValueError("cleanup removed marker differs from its exact plan")
    return receipt


def _aggregate_gate_snapshots(
    repo: Path,
    relative_paths: Sequence[str],
) -> tuple[str, int, int, int]:
    """Hash one or two exact run-owned trees into a deterministic gate-run identity."""

    records: list[dict[str, Any]] = []
    file_count = 0
    directory_count = 0
    byte_size = 0
    for relative in relative_paths:
        _validate_immediate_candidate(relative)
        path = _contained_path(repo, relative, must_exist=True)
        snapshot = _scan_tree(path, hash_tree=True, allow_link_members=True)
        records.append(
            {
                "path": relative,
                "tree_sha256": snapshot.tree_sha256,
                "file_count": snapshot.file_count,
                "directory_count": snapshot.directory_count,
                "byte_size": snapshot.byte_size,
            }
        )
        file_count += snapshot.file_count
        directory_count += snapshot.directory_count
        byte_size += snapshot.byte_size
    records.sort(key=lambda item: str(item["path"]).casefold())
    return storage_input_sha256({"trees": records}), file_count, directory_count, byte_size


def _gate_receipt_path(run_id: str) -> str:
    """Return the immutable receipt path for one uniquely named gate execution."""

    return f"{_GATE_RECEIPT_ROOT.as_posix()}/{_validate_portable_id(run_id)}/receipt.json"


def _gate_preflight_path(run_id: str) -> str:
    """Return the immutable preflight path written before gate scratch can move."""

    return f"{_GATE_RECEIPT_ROOT.as_posix()}/{_validate_portable_id(run_id)}/preflight.json"


def finalize_gate_run(
    *,
    run_id: str,
    gate_id: str,
    run_root: str,
    process_temp_root: str | None = None,
    gate_outcome: GateOutcome = "passed",
    retention_policy: RetentionPolicy = "compact_success",
    started_at: datetime | None = None,
    repo_root: Path | None = None,
) -> GateRunReceiptV01:
    """Publish a gate result and compact only a successful run-owned scratch tree."""

    repo = _repo_root(repo_root)
    _validate_portable_id(run_id)
    _validate_portable_id(gate_id)
    existing_path = _contained_path(repo, _gate_receipt_path(run_id), must_exist=False)
    if os.path.isfile(native_io_path(existing_path)):
        existing = GateRunReceiptV01.model_validate_json(_read_regular_bytes(existing_path))
        if (
            existing.run_id != run_id
            or existing.gate_id != gate_id
            or existing.run_root != run_root
            or existing.process_temp_root != process_temp_root
            or existing.gate_outcome != gate_outcome
            or existing.retention_policy != retention_policy
        ):
            raise ValueError("existing gate receipt differs from the requested finalization")
        if existing.retention_outcome == "preserved_retention_failure":
            raise RuntimeError(existing.message)
        return existing
    selected_paths = [run_root]
    if process_temp_root is not None:
        _contained_path(repo, process_temp_root, must_exist=True)
        selected_paths.append(process_temp_root)
    aggregate, file_count, directory_count, byte_size = _aggregate_gate_snapshots(
        repo, selected_paths
    )
    preflight_payload = {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "gate_id": gate_id,
        "repository_commit": _repository_commit(repo),
        "run_roots": sorted(selected_paths, key=str.casefold),
        "gate_outcome": gate_outcome,
        "retention_policy": retention_policy,
        "source_tree_sha256": aggregate,
        "source_file_count": file_count,
        "source_directory_count": directory_count,
        "source_byte_size": byte_size,
        "started_at": _json_timestamp(started_at or _utc_now()),
    }
    preflight_payload["input_sha256"] = storage_input_sha256(preflight_payload)
    preflight_relative = _gate_preflight_path(run_id)
    preflight_path = _contained_path(repo, preflight_relative, must_exist=False)
    _ensure_directory(repo, preflight_path.parent.relative_to(repo).as_posix())
    publish_bytes_create_once(preflight_path, deterministic_json_bytes(preflight_payload))
    preflight_artifact = _artifact(repo, preflight_path, kind="gate_run_preflight")
    retention_outcome = (
        "preserved_failure"
        if gate_outcome != "passed"
        else "preserved_by_policy"
        if retention_policy == "preserve"
        else "compacted"
    )
    message = (
        "Failed or interrupted gate scratch was preserved."
        if gate_outcome != "passed"
        else "Successful gate scratch was preserved by explicit policy."
        if retention_policy == "preserve"
        else "Successful gate scratch was compacted after receipt preflight."
    )
    failure: Exception | None = None
    if retention_outcome == "compacted":
        quarantine_root = _ensure_directory(
            repo, f"{_OPERATION_ROOT.as_posix()}/gate-quarantine/{run_id}"
        )
        captured: list[Path] = []
        try:
            for relative in selected_paths:
                source = _contained_path(repo, relative, must_exist=True)
                token = _candidate_token(relative)
                destination = quarantine_root / token
                if os.path.lexists(native_io_path(destination)):
                    raise FileExistsError("gate quarantine destination already exists")
                os.replace(native_io_path(source), native_io_path(destination))
                captured.append(destination)
            for destination in captured:
                _safe_remove_tree(
                    destination,
                    quarantine_root=quarantine_root,
                    allow_link_members=True,
                )
            with os.scandir(native_io_path(quarantine_root)) as iterator:
                quarantine_empty = next(iterator, None) is None
            if quarantine_empty:
                _remove_regular_directory(quarantine_root)
        except (OSError, ValueError) as exc:
            failure = exc
            retention_outcome = "preserved_retention_failure"
            message = f"Gate passed but retention failed closed: {type(exc).__name__}: {exc}"

    payload: dict[str, Any] = {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "gate_id": gate_id,
        "repository_commit": preflight_payload["repository_commit"],
        "run_root": run_root,
        "process_temp_root": process_temp_root,
        "gate_outcome": gate_outcome,
        "retention_policy": retention_policy,
        "retention_outcome": retention_outcome,
        "source_tree_sha256": aggregate,
        "source_file_count": file_count,
        "source_directory_count": directory_count,
        "source_byte_size": byte_size,
        "retained_artifacts": [preflight_artifact.model_dump(mode="json")],
        "started_at": preflight_payload["started_at"],
        "completed_at": _json_timestamp(_utc_now()),
        "message": message,
    }
    payload["input_sha256"] = storage_input_sha256(payload)
    receipt = GateRunReceiptV01.model_validate(payload)
    _write_immutable_model(repo, _gate_receipt_path(run_id), receipt)
    if failure is not None:
        raise RuntimeError(message) from failure
    return receipt


def _gate_recovery_receipt_path(run_id: str, recovery_id: str) -> str:
    """Return one append-only gate-retention recovery receipt path."""

    return (
        f"{_GATE_RECEIPT_ROOT.as_posix()}/{_validate_portable_id(run_id)}/"
        f"retention_recoveries/{_validate_portable_id(recovery_id)}.json"
    )


def _gate_expected_roots(receipt: GateRunReceiptV01) -> list[str]:
    """Return the sorted unique scratch roots bound by one gate receipt."""

    roots = [receipt.run_root]
    if receipt.process_temp_root is not None:
        roots.append(receipt.process_temp_root)
    return sorted(set(roots), key=str.casefold)


def _verify_bound_artifact(repo: Path, artifact: StorageArtifact) -> Path:
    """Verify one exact retention artifact before trusting its machine fields."""

    path = _contained_path(repo, artifact.path, must_exist=True)
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"retention artifact hash differs: {artifact.path}")
    if os.path.getsize(native_io_path(path)) != artifact.byte_size:
        raise ValueError(f"retention artifact size differs: {artifact.path}")
    return path


def _load_completed_gate_recovery(
    repo: Path,
    run_id: str,
) -> GateRetentionRecoveryReceiptV01 | None:
    """Return an already verified completed recovery for idempotent resume."""

    relative = (
        f"{_GATE_RECEIPT_ROOT.as_posix()}/{_validate_portable_id(run_id)}/"
        "retention_recoveries"
    )
    directory = _contained_path(repo, relative, must_exist=False)
    if not os.path.lexists(native_io_path(directory)):
        return None
    _assert_no_link_ancestors(directory, include_leaf=True)
    metadata = os.lstat(native_io_path(directory))
    if _is_link_or_reparse_metadata(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise _UnsafeTreeError("gate recovery receipt directory is linked or invalid")
    with os.scandir(native_io_path(directory)) as iterator:
        entries = sorted(list(iterator), key=lambda item: item.name.casefold())
    completed: list[GateRetentionRecoveryReceiptV01] = []
    for entry in entries:
        member = directory / entry.name
        member_metadata = entry.stat(follow_symlinks=False)
        if (
            entry.is_symlink()
            or _is_link_or_reparse_metadata(member_metadata)
            or not stat.S_ISREG(member_metadata.st_mode)
            or not entry.name.endswith(".json")
        ):
            raise _UnsafeTreeError("gate recovery receipt directory contains an invalid entry")
        recovery = GateRetentionRecoveryReceiptV01.model_validate_json(
            _read_regular_bytes(member)
        )
        if recovery.run_id != run_id:
            raise ValueError("gate recovery receipt run binding differs")
        if recovery.status == "completed":
            completed.append(recovery)
    if len(completed) > 1:
        raise ValueError("multiple completed gate retention recoveries were found")
    if not completed:
        return None
    return verify_gate_retention_recovery_receipt(
        run_id,
        completed[0].recovery_id,
        repo_root=repo,
    )


def resume_gate_run_retention(
    run_id: str,
    *,
    repo_root: Path | None = None,
) -> GateRetentionRecoveryReceiptV01:
    """Resume deletion only inside quarantine created by a failed gate compaction."""

    repo = _repo_root(repo_root)
    _validate_portable_id(run_id)
    completed = _load_completed_gate_recovery(repo, run_id)
    if completed is not None:
        return completed
    gate_receipt_path = _contained_path(repo, _gate_receipt_path(run_id), must_exist=True)
    gate_receipt = GateRunReceiptV01.model_validate_json(
        _read_regular_bytes(gate_receipt_path)
    )
    if gate_receipt.run_id != run_id:
        raise ValueError("gate receipt run binding differs")
    if (
        gate_receipt.gate_outcome != "passed"
        or gate_receipt.retention_policy != "compact_success"
        or gate_receipt.retention_outcome != "preserved_retention_failure"
    ):
        raise ValueError("only failed retention from a passed compact-success gate can resume")
    if gate_receipt.source_tree_sha256 is None:
        raise ValueError("gate retention recovery requires its source tree digest")
    for artifact in gate_receipt.retained_artifacts:
        if artifact.kind == "gate_run_preflight":
            _verify_bound_artifact(repo, artifact)

    expected_roots = _gate_expected_roots(gate_receipt)
    quarantine_relative = (
        f"{_OPERATION_ROOT.as_posix()}/gate-quarantine/{_validate_portable_id(run_id)}"
    )
    quarantine_root = _contained_path(repo, quarantine_relative, must_exist=False)
    expected_tokens = {_candidate_token(relative) for relative in expected_roots}
    if os.path.lexists(native_io_path(quarantine_root)):
        _assert_no_link_ancestors(quarantine_root, include_leaf=True)
        quarantine_metadata = os.lstat(native_io_path(quarantine_root))
        if _is_link_or_reparse_metadata(quarantine_metadata) or not stat.S_ISDIR(
            quarantine_metadata.st_mode
        ):
            raise _UnsafeTreeError("gate quarantine root is linked or invalid")
        with os.scandir(native_io_path(quarantine_root)) as iterator:
            actual_tokens = {entry.name for entry in iterator}
        if not actual_tokens.issubset(expected_tokens):
            raise ValueError("gate quarantine contains an unexpected member")

    removed: list[str] = []
    remaining: list[str] = []
    failures: list[str] = []
    for relative in expected_roots:
        source = _contained_path(repo, relative, must_exist=False)
        quarantine = quarantine_root / _candidate_token(relative)
        source_exists = os.path.lexists(native_io_path(source))
        quarantine_exists = os.path.lexists(native_io_path(quarantine))
        if source_exists:
            remaining.append(relative)
            if quarantine_exists:
                failures.append(f"{relative}: source and quarantine both exist")
            else:
                failures.append(f"{relative}: source root was never quarantined and was preserved")
            continue
        if quarantine_exists:
            try:
                _safe_remove_tree(
                    quarantine,
                    quarantine_root=quarantine_root,
                    allow_link_members=True,
                )
            except (OSError, ValueError) as exc:
                remaining.append(relative)
                failures.append(f"{relative}: {type(exc).__name__}: {exc}")
                continue
        removed.append(relative)

    if os.path.lexists(native_io_path(quarantine_root)):
        with os.scandir(native_io_path(quarantine_root)) as iterator:
            quarantine_empty = next(iterator, None) is None
        if quarantine_empty:
            _remove_regular_directory(quarantine_root)
    removed.sort(key=str.casefold)
    remaining.sort(key=str.casefold)
    status = "completed" if not remaining else "partial"
    message = (
        "Quarantined gate scratch was removed without touching source roots or link targets."
        if status == "completed"
        else "Gate retention recovery remains partial: " + "; ".join(failures)
    )
    payload: dict[str, Any] = {
        "schema_version": "0.1.0",
        "recovery_id": _new_id("gate-recovery"),
        "run_id": run_id,
        "gate_receipt": _artifact(
            repo,
            gate_receipt_path,
            kind="gate_run_receipt",
        ).model_dump(mode="json"),
        "status": status,
        "expected_roots": expected_roots,
        "removed_roots": removed,
        "remaining_roots": remaining,
        "source_tree_sha256": gate_receipt.source_tree_sha256,
        "source_byte_size": gate_receipt.source_byte_size,
        "reclaimed_byte_size": gate_receipt.source_byte_size if status == "completed" else 0,
        "completed_at": _json_timestamp(_utc_now()),
        "message": message,
    }
    payload["input_sha256"] = storage_input_sha256(payload)
    recovery = GateRetentionRecoveryReceiptV01.model_validate(payload)
    _write_immutable_model(
        repo,
        _gate_recovery_receipt_path(run_id, recovery.recovery_id),
        recovery,
    )
    if recovery.status == "completed":
        return verify_gate_retention_recovery_receipt(
            run_id,
            recovery.recovery_id,
            repo_root=repo,
        )
    return recovery


def verify_gate_retention_recovery_receipt(
    run_id: str,
    recovery_id: str,
    *,
    repo_root: Path | None = None,
) -> GateRetentionRecoveryReceiptV01:
    """Verify one gate recovery receipt and every completed removal it claims."""

    repo = _repo_root(repo_root)
    recovery = _load_model(
        repo,
        _gate_recovery_receipt_path(run_id, recovery_id),
        GateRetentionRecoveryReceiptV01,
    )
    if recovery.run_id != run_id or recovery.recovery_id != recovery_id:
        raise ValueError("gate recovery receipt identity differs")
    gate_receipt_path = _verify_bound_artifact(repo, recovery.gate_receipt)
    gate_receipt = GateRunReceiptV01.model_validate_json(
        _read_regular_bytes(gate_receipt_path)
    )
    if (
        gate_receipt.run_id != run_id
        or recovery.expected_roots != _gate_expected_roots(gate_receipt)
        or recovery.source_tree_sha256 != gate_receipt.source_tree_sha256
        or recovery.source_byte_size != gate_receipt.source_byte_size
    ):
        raise ValueError("gate recovery receipt differs from its source gate receipt")
    if recovery.status == "completed":
        quarantine_root = _contained_path(
            repo,
            f"{_OPERATION_ROOT.as_posix()}/gate-quarantine/{run_id}",
            must_exist=False,
        )
        for relative in recovery.expected_roots:
            source = _contained_path(repo, relative, must_exist=False)
            quarantine = quarantine_root / _candidate_token(relative)
            if os.path.lexists(native_io_path(source)) or os.path.lexists(
                native_io_path(quarantine)
            ):
                raise ValueError("completed gate recovery still has retained scratch")
    return recovery
