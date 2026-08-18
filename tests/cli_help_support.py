from __future__ import annotations

from collections.abc import Iterable

from rich.text import Text


def plain_cli_output(output: str) -> str:
    """Remove ANSI styling so CLI assertions inspect the visible help contract."""

    return Text.from_ansi(output).plain


def assert_cli_help_contract(
    output: str,
    *,
    required: Iterable[str] = (),
    forbidden: Iterable[str] = (),
) -> str:
    """Validate required and forbidden tokens against one normalized help string."""

    visible = plain_cli_output(output)
    missing = sorted(token for token in required if token not in visible)
    unexpected = sorted(token for token in forbidden if token in visible)
    if missing:
        raise AssertionError(f"missing CLI help tokens: {missing}")
    if unexpected:
        raise AssertionError(f"forbidden CLI help tokens: {unexpected}")
    return visible
