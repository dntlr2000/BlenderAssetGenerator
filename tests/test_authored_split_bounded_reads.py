"""Bounded real-file I/O regressions; synthetic files grant no production authority."""

from __future__ import annotations

import hashlib
import os
import tracemalloc
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler import authored_split_runtime as runtime
from codex_blender_modeler.blender_artifacts import native_io_path


def _ref(path: str, content: bytes) -> dict[str, str]:
    """Construct an exact synthetic reference independently of the runtime reader."""
    return {"path": path, "sha256": hashlib.sha256(content).hexdigest()}


def _observe_reads(monkeypatch, target, *, after_read=None, before_open=None, short=False):
    """Observe actual reads and deterministic file races without patching validation."""
    original_open = Path.open
    requests = []

    class ObservedReader:
        """Forward real file I/O while recording allocation requests and injecting races."""

        def __init__(self, stream):
            """Keep the underlying descriptor available for real fstat checks."""
            self.stream = stream

        def fileno(self):
            """Expose the genuine file descriptor to the unchanged runtime validator."""
            return self.stream.fileno()

        def read(self, size=-1):
            """Record the requested size and optionally mutate after the first real read."""
            requests.append(size)
            assert 0 < size <= 1024 * 1024
            content = self.stream.read(min(size, 17) if short else size)
            if len(requests) == 1 and after_read is not None:
                after_read()
            return content

    @contextmanager
    def observed_stream(path, *args, **kwargs):
        """Bracket a genuine selected-file stream with optional pre-open mutation."""
        if before_open is not None:
            before_open()
        with original_open(path, *args, **kwargs) as stream:
            yield ObservedReader(stream)

    def observed_open(path, *args, **kwargs):
        """Observe the selected physical file with either lexical or native Windows paths."""
        mode = args[0] if args else kwargs.get("mode", "r")
        if native_io_path(path) == native_io_path(target) and mode == "rb":
            return observed_stream(path, *args, **kwargs)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)
    return requests


def _read_or_reference(root, relative, content, operation):
    """Exercise both unchanged public binary reader and reference-producing surfaces."""
    expected = _ref(relative, content)
    if operation == "read":
        assert runtime.read(root, expected, binary=True) == content
    else:
        assert runtime.reference(root, relative) == expected


@pytest.mark.parametrize("operation", ["read", "reference"])
@pytest.mark.parametrize("size", [0, 19, 1024 * 1024 + 37])
def test_exact_binary_bytes_hash_and_small_read_requests(tmp_path, monkeypatch, operation, size):
    """Empty, tiny and multichunk binaries preserve exact bytes without policy-sized reads."""
    content = (b"BLENDER\x00\xff\r\n" * (size // 11 + 1))[:size]
    path = tmp_path / "scene.blend"
    path.write_bytes(content)
    requests = _observe_reads(monkeypatch, path)
    _read_or_reference(tmp_path, path.name, content, operation)
    assert requests[-1] == 1
    assert max(requests) <= min(1024 * 1024, max(1, size))
    assert runtime.MAX_BINARY_BYTES == 512 * 1024 * 1024


@pytest.mark.parametrize("operation", ["read", "reference"])
def test_partial_reads_are_collected_exactly(tmp_path, monkeypatch, operation):
    """Legitimate short reads are accumulated until the observed file size is reached."""
    content = b"short reads are allowed" * 31
    path = tmp_path / "scene.blend"
    path.write_bytes(content)
    requests = _observe_reads(monkeypatch, path, short=True)
    _read_or_reference(tmp_path, path.name, content, operation)
    assert len(requests) > 2


@pytest.mark.parametrize(
    "reference",
    [
        None,
        [],
        "scene.blend",
        {},
        {"path": "scene.blend"},
        {"path": "scene.blend", "sha256": None},
        {"path": "scene.blend", "sha256": 123},
        {"path": "scene.blend", "sha256": "A" * 64},
        {"path": "scene.blend", "sha256": "a" * 63},
        {"path": "scene.blend", "sha256": "a" * 64, "approval": True},
    ],
)
def test_malformed_binary_references_fail_closed(tmp_path, reference):
    """Malformed hashes, missing fields and additional authority never reach file reading."""
    with pytest.raises(ValueError, match="reference is malformed"):
        runtime.read(tmp_path, reference, binary=True)


def test_tampered_binary_hash_is_rejected(tmp_path):
    """Matching size cannot make changed exact bytes satisfy an archived hash."""
    path = tmp_path / "scene.blend"
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="binary artifact changed"):
        runtime.read(tmp_path, _ref(path.name, b"initial"), binary=True)


@pytest.mark.parametrize("operation", ["read", "reference"])
@pytest.mark.parametrize("relative", ["../scene.blend", "/scene.blend", "a/../scene.blend", None])
def test_escaped_or_malformed_paths_are_rejected(tmp_path, operation, relative):
    """Both public readers retain strict normalized job-relative path containment."""
    with pytest.raises(ValueError):
        _read_or_reference(tmp_path, relative, b"", operation)


@pytest.mark.parametrize("operation", ["read", "reference"])
def test_linked_binary_is_rejected(tmp_path, operation):
    """Even a same-root alias to matching bytes cannot replace an ordinary artifact."""
    path = tmp_path / "actual.blend"
    path.write_bytes(b"synthetic")
    (tmp_path / "scene.blend").symlink_to(path)
    with pytest.raises(ValueError, match="symlink|link"):
        _read_or_reference(tmp_path, "scene.blend", b"synthetic", operation)


@pytest.mark.parametrize("operation", ["read", "reference"])
def test_oversized_binary_rejected_before_open(tmp_path, monkeypatch, operation):
    """A sparse file beyond the unchanged 512 MiB ceiling is rejected before allocation."""
    path = tmp_path / "scene.blend"
    with path.open("wb") as stream:
        stream.truncate(512 * 1024 * 1024 + 1)

    def unexpected_open():
        """Fail if an oversized artifact reaches its read-open operation."""
        pytest.fail("oversized binary opened")

    _observe_reads(monkeypatch, path, before_open=unexpected_open)
    with pytest.raises(ValueError, match="byte bound"):
        _read_or_reference(tmp_path, path.name, b"", operation)


def test_ordinary_reference_keeps_eight_mib_limit(tmp_path):
    """Only .blend gets the binary bound; ordinary evidence keeps its 8 MiB allowance."""
    path = tmp_path / "evidence.json"
    with path.open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="byte bound"):
        runtime.reference(tmp_path, path.name)


def test_reference_does_not_retain_binary_payload(tmp_path):
    """Reference hashing uses chunk-sized memory rather than retaining a whole archive."""
    path = tmp_path / "scene.blend"
    with path.open("wb") as stream:
        stream.truncate(12 * 1024 * 1024)
    expected = hashlib.sha256()
    zeros = bytes(1024 * 1024)
    for _ in range(12):
        expected.update(zeros)
    tracemalloc.start()
    try:
        assert runtime.reference(tmp_path, path.name) == {
            "path": path.name,
            "sha256": expected.hexdigest(),
        }
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024


@pytest.mark.parametrize("operation", ["read", "reference"])
@pytest.mark.parametrize("change", ["grow", "shrink", "rewrite", "replace", "link"])
def test_changes_during_read_fail_closed(tmp_path, monkeypatch, operation, change):
    """Real growth, shrink, same-size mutation and path substitution cannot yield a binding."""
    path = tmp_path / "scene.blend"
    content = b"synthetic archive" * 8192
    path.write_bytes(content)

    def mutate():
        """Change only this synthetic fixture after its first actual read completes."""
        if change == "grow":
            with path.open("ab") as stream:
                stream.write(b"growth")
        elif change == "shrink":
            with path.open("r+b") as stream:
                stream.truncate(1)
        elif change == "rewrite":
            before = path.stat()
            path.write_bytes(b"x" * len(content))
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        else:
            replacement = tmp_path / "replacement.blend"
            replacement.write_bytes(content)
            if change == "replace":
                replacement.replace(path)
            else:
                path.unlink()
                path.symlink_to(replacement)

    _observe_reads(monkeypatch, path, after_read=mutate)
    with pytest.raises(ValueError, match="changed|symlink|link"):
        _read_or_reference(tmp_path, path.name, content, operation)


@pytest.mark.parametrize("operation", ["read", "reference"])
def test_change_between_stat_and_open_is_rejected(tmp_path, monkeypatch, operation):
    """The opened descriptor must still identify the file observed before opening."""
    path = tmp_path / "scene.blend"
    content = b"original"
    path.write_bytes(content)

    def mutate():
        """Grow the selected synthetic fixture after stat but before actual open."""
        path.write_bytes(content + b"growth")

    requests = _observe_reads(monkeypatch, path, before_open=mutate)
    with pytest.raises(ValueError, match="changed before reading"):
        _read_or_reference(tmp_path, path.name, content, operation)
    assert not requests


def test_nonbinary_reader_preserves_exact_json_validation(tmp_path):
    """The unrelated default attachment reader still enforces exact bytes and hashes."""
    path = tmp_path / "evidence.json"
    content = b'{"synthetic": true}\r\n'
    path.write_bytes(content)
    assert runtime.read(tmp_path, _ref(path.name, content)) == content
    assert runtime.reference(tmp_path, path.name) == _ref(path.name, content)
    with pytest.raises(ValueError, match="bytes changed"):
        runtime.read(tmp_path, _ref(path.name, content + b" "))


@pytest.mark.parametrize("operation", ["read", "reference"])
@pytest.mark.parametrize("descriptor_changes", [False, True])
def test_path_and_descriptor_change_times(tmp_path, monkeypatch, operation, descriptor_changes):
    """Accept stable cross-API ctime differences but reject descriptor-only metadata races."""
    path = tmp_path / "scene.blend"
    content = b"stable file with independently reported descriptor change time"
    path.write_bytes(content)
    original_fstat = os.fstat
    calls = 0

    def descriptor_stat(fd):
        """Retain real file identity while modeling distinct descriptor ctime semantics."""
        nonlocal calls
        calls += 1
        metadata = original_fstat(fd)
        fields = {
            name: getattr(metadata, name)
            for name in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
        }
        fields["st_ctime_ns"] = 123456789 + (calls if descriptor_changes else 0)
        return SimpleNamespace(**fields)

    monkeypatch.setattr(os, "fstat", descriptor_stat)
    if descriptor_changes:
        with pytest.raises(ValueError, match="metadata changed while reading"):
            _read_or_reference(tmp_path, path.name, content, operation)
    else:
        _read_or_reference(tmp_path, path.name, content, operation)
    assert calls == 2


@pytest.mark.parametrize("binary", [False, True])
def test_long_artifact_paths_preserve_exact_read_and_reference(tmp_path, binary):
    """Deep native files retain containment, bounds and exact hashes for both read modes."""
    relative = "/".join(["retained-artifact-segment-" + "x" * 28] * 5)
    relative += "/scene.blend" if binary else "/evidence.json"
    selected = Path(native_io_path(tmp_path / relative))
    selected.parent.mkdir(parents=True)
    content = b'{"synthetic": "deep exact artifact"}'
    selected.write_bytes(content)
    assert len(str(tmp_path / relative)) > 260
    expected = _ref(relative, content)
    assert runtime.read(tmp_path, expected, binary=binary) == content
    assert runtime.reference(tmp_path, relative) == expected
    with pytest.raises(ValueError, match="changed"):
        runtime.read(tmp_path, _ref(relative, content + b"x"), binary=binary)


def test_long_artifact_publication_keeps_create_once_boundary(tmp_path):
    """Deep authored shadow files publish once and cannot replace different existing bytes."""
    from codex_blender_modeler.material_identity_split.authored_service import publish

    relative = "/".join(["shadow-material-segment-" + "x" * 28] * 5) + "/evidence.json"
    content = b'{"synthetic": "immutable shadow"}'
    expected = _ref(relative, content)
    assert publish(tmp_path, relative, content) == expected
    assert publish(tmp_path, relative, content) == expected
    with pytest.raises(FileExistsError, match="conflicting immutable"):
        publish(tmp_path, relative, content + b"\n")
    assert runtime.read(tmp_path, expected) == content
