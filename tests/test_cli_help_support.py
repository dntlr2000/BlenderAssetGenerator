from __future__ import annotations

import pytest
from cli_help_support import assert_cli_help_contract, plain_cli_output


def test_plain_cli_output_preserves_unstyled_help() -> None:
    """Keep ordinary non-ANSI help tokens visible to assertions."""

    output = "Options:\n  --max-actions INTEGER\n  --enable-v2 / --disable-v2\n"
    assert plain_cli_output(output) == output.rstrip("\n")
    assert_cli_help_contract(
        output,
        required=("--max-actions", "--enable-v2", "--disable-v2"),
        forbidden=("--retry-failed",),
    )


def test_cli_help_contract_joins_ansi_fragmented_option_tokens() -> None:
    """Recognize options whose visible token is split across Rich style spans."""

    output = (
        "\x1b[1m-\x1b[0m\x1b[1m-max\x1b[0m\x1b[1m-actions\x1b[0m "
        "\x1b[1m-\x1b[0m\x1b[1m-enable\x1b[0m\x1b[1m-v2\x1b[0m"
    )
    assert_cli_help_contract(output, required=("--max-actions", "--enable-v2"))


@pytest.mark.parametrize("required", ("--max-actions", "--enable-v2"))
def test_cli_help_contract_rejects_actually_missing_required_option(required: str) -> None:
    """Fail closed when a required visible option is genuinely absent."""

    with pytest.raises(AssertionError, match="missing CLI help tokens"):
        assert_cli_help_contract("Options:\n  --help\n", required=(required,))


def test_cli_help_contract_rejects_ansi_fragmented_forbidden_option() -> None:
    """Detect a forbidden option even when Rich splits its styled token."""

    output = (
        "\x1b[1m-\x1b[0m\x1b[1m-retry\x1b[0m"
        "\x1b[1m-failed\x1b[0m"
    )
    with pytest.raises(AssertionError, match="forbidden CLI help tokens"):
        assert_cli_help_contract(output, forbidden=("--retry-failed",))
