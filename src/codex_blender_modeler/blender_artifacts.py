from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import uuid4

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def native_io_path(path: Path) -> str:
    """Return an absolute filename that supports extended Windows path lengths."""

    resolved = os.path.abspath(os.fspath(path.expanduser()))
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


def file_exists(path: Path) -> bool:
    """Check one regular artifact through its platform-native filename."""

    return os.path.isfile(native_io_path(path))


def safe_artifact_name(value: str) -> str:
    """Convert a stable semantic ID into a portable artifact directory name."""

    compact = _SAFE_NAME_RE.sub("_", value.strip()).strip("._")
    return compact or "unnamed"


def stable_rgb(value: str) -> tuple[float, float, float]:
    """Map an ID to a deterministic, non-black RGB color for machine-readable passes."""

    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return (
        0.18 + (digest[0] / 255.0) * 0.74,
        0.18 + (digest[1] / 255.0) * 0.74,
        0.18 + (digest[2] / 255.0) * 0.74,
    )


def linear_to_srgb(value: float) -> float:
    """Convert one linear channel to its standard sRGB display encoding."""

    bounded = max(0.0, min(1.0, value))
    if bounded <= 0.0031308:
        return 12.92 * bounded
    return 1.055 * (bounded ** (1.0 / 2.4)) - 0.055


def unique_color_map(values: list[str]) -> dict[str, tuple[float, float, float]]:
    """Assign deterministic collision-free linear colors to a set of semantic IDs."""

    result: dict[str, tuple[float, float, float]] = {}
    used: set[str] = set()
    for value in sorted(set(values)):
        attempt = 0
        while True:
            key = value if attempt == 0 else f"{value}#{attempt}"
            color = stable_rgb(key)
            display_color = tuple(linear_to_srgb(channel) for channel in color)
            encoded = rgb_hex(display_color)  # type: ignore[arg-type]
            if encoded not in used:
                result[value] = color
                used.add(encoded)
                break
            attempt += 1
    return result


def rgb_hex(color: tuple[float, float, float]) -> str:
    """Encode a normalized RGB triplet as a lowercase hexadecimal color."""

    values = [max(0, min(255, round(channel * 255))) for channel in color]
    return "#" + "".join(f"{value:02x}" for value in values)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one generated artifact."""

    digest = hashlib.sha256()
    with open(native_io_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_directory_files(directory: Path) -> list[Path]:
    """Enumerate regular files deterministically with long-path and link safety."""

    root = Path(os.path.abspath(os.fspath(directory)))
    root_native = native_io_path(root)
    if not os.path.isdir(root_native):
        raise FileNotFoundError(root)
    root_metadata = os.lstat(root_native)
    root_attributes = getattr(root_metadata, "st_file_attributes", 0)
    if os.path.islink(root_native) or bool(
        root_attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise ValueError("artifact directory contains a symlink or junction")

    pending = [root]
    files: list[Path] = []
    while pending:
        current = pending.pop()
        with os.scandir(native_io_path(current)) as iterator:
            entries = list(iterator)
        for entry in entries:
            member = current / entry.name
            metadata = entry.stat(follow_symlinks=False)
            attributes = getattr(metadata, "st_file_attributes", 0)
            if entry.is_symlink() or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise ValueError("artifact directory contains a symlink or junction")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(member)
            elif stat.S_ISREG(metadata.st_mode):
                files.append(member)
            else:
                raise ValueError(
                    f"artifact directory contains an unsupported entry: {entry.name}"
                )
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def sha256_directory(
    directory: Path,
    *,
    files: Iterable[Path] | None = None,
) -> str:
    """Hash an exact deterministic directory inventory and every member digest."""

    root = Path(os.path.abspath(os.fspath(directory)))
    selected = list(files) if files is not None else deterministic_directory_files(root)
    records = [
        {
            "path": item.relative_to(root).as_posix(),
            "sha256": sha256_file(item),
        }
        for item in sorted(selected, key=lambda item: item.relative_to(root).as_posix())
    ]
    return stable_json_digest(records)


def stable_json_digest(value: Any) -> str:
    """Hash JSON-compatible content using canonical key ordering."""

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def deterministic_json_bytes(value: Any) -> bytes:
    """Serialize one JSON value with stable UTF-8, LF, indentation, and final newline."""

    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def native_json_bytes(value: Any) -> bytes:
    """Serialize JSON with the historical host newline convention used by legacy APIs."""

    text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    return text.replace("\n", os.linesep).encode("utf-8")


def _immutable_file_matches(path: Path, content: bytes) -> bool:
    """Return whether one pre-existing regular non-link file has the exact bytes."""

    native = native_io_path(path)
    try:
        metadata = os.lstat(native)
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    ):
        raise FileExistsError(f"immutable artifact path is not a regular file: {path}")
    with open(native, "rb") as handle:
        return handle.read() == content


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    """Recognize POSIX links and Windows junction/reparse metadata without following it."""

    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _ensure_lexical_directory(path: Path) -> None:
    """Create missing lexical ancestors while rejecting every link or reparse hop."""

    directory = Path(os.path.abspath(os.fspath(path.expanduser())))
    chain = list(reversed((directory, *directory.parents)))
    for member in chain:
        native = native_io_path(member)
        try:
            metadata = os.lstat(native)
        except FileNotFoundError:
            try:
                os.mkdir(native)
            except FileExistsError:
                pass
            metadata = os.lstat(native)
        if _is_link_or_reparse(metadata):
            raise ValueError(
                f"immutable artifact ancestor is a symlink or reparse point: {member}"
            )
        if not stat.S_ISDIR(metadata.st_mode):
            raise NotADirectoryError(
                f"immutable artifact ancestor is not a directory: {member}"
            )


def _require_lexical_destination_safe(path: Path) -> None:
    """Recheck lexical ancestors and reject an existing linked final destination."""

    _ensure_lexical_directory(path.parent)
    native = native_io_path(path)
    try:
        metadata = os.lstat(native)
    except FileNotFoundError:
        return
    if _is_link_or_reparse(metadata):
        raise FileExistsError(
            f"immutable artifact path is a symlink or reparse point: {path}"
        )


def publish_bytes_create_once(
    path: Path,
    content: bytes,
) -> bool:
    """Atomically link complete immutable bytes once, exact-adopting identical peers."""

    destination = Path(os.path.abspath(os.fspath(path.expanduser())))
    _require_lexical_destination_safe(destination)
    create_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if os.path.lexists(native_io_path(destination)):
        if not _immutable_file_matches(destination, content):
            raise FileExistsError(f"conflicting immutable artifact bytes: {destination}")
        return False
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{uuid4().hex}.immutable.tmp"
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(native_io_path(temporary), create_flags, 0o600)
        destination_created = False
        try:
            pending = memoryview(content)
            while pending:
                written = os.write(descriptor, pending)
                if written <= 0:
                    raise OSError("immutable artifact write made no progress")
                pending = pending[written:]
            os.fsync(descriptor)
        finally:
            if descriptor is not None:
                os.close(descriptor)
                descriptor = None
        _require_lexical_destination_safe(destination)
        try:
            os.link(native_io_path(temporary), native_io_path(destination))
            destination_created = True
        except FileExistsError as exc:
            if not _immutable_file_matches(destination, content):
                raise FileExistsError(
                    f"conflicting immutable artifact bytes: {destination}"
                ) from exc
        return destination_created
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if os.path.lexists(native_io_path(temporary)):
            os.unlink(native_io_path(temporary))


def artifact_path(path: Path, manifest_path: Path) -> str:
    """Prefer a manifest-relative path while retaining an absolute fallback."""

    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(manifest_path.parent.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON artifact atomically so interrupted Blender runs do not look complete."""

    destination = path.expanduser().resolve()
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    with open(native_io_path(temporary), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    os.replace(native_io_path(temporary), native_io_path(destination))
