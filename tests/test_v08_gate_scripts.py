from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_GATE = ROOT / "scripts" / "run_v08_gates.ps1"
SHELL_GATE = ROOT / "scripts" / "run_v08_gates.sh"


def _source(path: Path) -> str:
    """Read one V0.8 gate script for deterministic boundary assertions."""

    return path.read_text(encoding="utf-8")


def test_v08_gates_use_an_isolated_proxy_workflow() -> None:
    """Both gates stop a new-reference smoke run at the first agent boundary."""

    for path in (POWERSHELL_GATE, SHELL_GATE):
        source = _source(path)
        assert "reports/v08_smoke" in source
        assert "v08_proxy_smoke" in source
        assert "workflow-plan" in source
        assert "workflow-resume" in source
        assert "waiting_for_agent" in source
        assert "geometry.modeling_plan" in source
        assert "first_reference_test" not in source


def test_v08_gates_preserve_the_unsupported_engine_boundary() -> None:
    """Both gates prove that a Unity request remains an engine-neutral package plan."""

    for path in (POWERSHELL_GATE, SHELL_GATE):
        source = _source(path)
        assert "--destination unity" in source
        assert "unsupported" in source
        assert "portable_package" in source
        assert "portable.final_approval" in source


def test_v08_gates_retain_the_v07_regression_path() -> None:
    """Both gates run the verified portable-asset suite unless explicitly skipped."""

    for path in (POWERSHELL_GATE, SHELL_GATE):
        source = _source(path)
        assert "run_v07_gates" in source
        assert "SkipV07" in source or "skip-v07" in source
