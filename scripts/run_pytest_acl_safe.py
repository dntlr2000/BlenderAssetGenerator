"""Run pytest while preserving inherited ACLs inside an explicit Windows basetemp."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest


def selected_basetemp(arguments: Sequence[str]) -> Path | None:
    """Resolve pytest's explicit basetemp without guessing a default temp location."""

    for index, argument in enumerate(arguments):
        if argument == "--basetemp":
            if index + 1 >= len(arguments):
                return None
            return Path(arguments[index + 1]).resolve()
        if argument.startswith("--basetemp="):
            return Path(argument.split("=", 1)[1]).resolve()
    return None


def inherited_acl_mkdir_mode(
    path: Any,
    mode: int,
    acl_roots: Sequence[Path],
) -> int:
    """Broaden restrictive Windows mode only inside declared pytest temp roots."""

    if sys.platform != "win32" or mode != 0o700:
        return mode
    try:
        candidate = Path(path).resolve(strict=False)
    except (OSError, TypeError, ValueError):
        return mode
    return (
        0o777
        if any(candidate == root or candidate.is_relative_to(root) for root in acl_roots)
        else mode
    )


@contextmanager
def pytest_basetemp_acl_environment(arguments: Sequence[str]) -> Iterator[None]:
    """Make only explicit pytest basetemp children inherit the invoking Windows ACL."""

    basetemp = selected_basetemp(arguments)
    if sys.platform != "win32" or basetemp is None:
        yield
        return

    process_temp_root = basetemp.with_name(f"{basetemp.name}-process-temp")
    acl_roots = (basetemp, process_temp_root)
    original_mkdir = os.mkdir
    original_tempdir = tempfile.tempdir
    original_temp = os.environ.get("TEMP")
    original_tmp = os.environ.get("TMP")

    def inherited_acl_mkdir(
        path: Any,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        """Delegate mkdir while translating only the explicit basetemp's 0o700 mode."""

        effective_mode = (
            inherited_acl_mkdir_mode(path, mode, acl_roots)
            if dir_fd is None
            else mode
        )
        if dir_fd is None:
            original_mkdir(path, effective_mode)
        else:
            original_mkdir(path, effective_mode, dir_fd=dir_fd)

    os.mkdir = inherited_acl_mkdir
    try:
        process_temp_root.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(process_temp_root)
        os.environ["TEMP"] = str(process_temp_root)
        os.environ["TMP"] = str(process_temp_root)
        yield
    finally:
        os.mkdir = original_mkdir
        tempfile.tempdir = original_tempdir
        if original_temp is None:
            os.environ.pop("TEMP", None)
        else:
            os.environ["TEMP"] = original_temp
        if original_tmp is None:
            os.environ.pop("TMP", None)
        else:
            os.environ["TMP"] = original_tmp


def main(arguments: Sequence[str] | None = None) -> int:
    """Execute pytest with the narrow Windows basetemp ACL compatibility boundary."""

    selected = list(sys.argv[1:] if arguments is None else arguments)
    with pytest_basetemp_acl_environment(selected):
        return int(pytest.main(selected))


if __name__ == "__main__":
    raise SystemExit(main())
