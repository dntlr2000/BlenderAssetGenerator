from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str) -> str:
    """Read one V0.9 gate script for deterministic boundary assertions."""

    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_v09_windows_gate_uses_isolated_workspace_and_queue_boundary() -> None:
    """Require the Windows gate to preserve isolation, receipts, audit, and redaction."""

    text = _script("run_v09_gates.ps1")
    assert "reports/v09_smoke" in text
    assert "$env:CBM_WORKSPACE_ROOT = $SmokeWorkspace" in text
    assert "queue-enqueue" in text
    assert "queue-run" in text
    assert "waiting_for_agent" in text
    assert "workspace-audit" in text
    assert "stability-probe" in text
    assert "stability-report-pdf" in text
    assert "handoff-plan" in text
    assert "handoff-generate" in text
    assert "handoff-validate" in text
    assert "valid_handoff_count" in text
    assert "geometry_showcase" in text
    assert "CBM_RUN_EXTERNAL_INTAKE_SMOKE" in text
    assert "test_blender_external_intake_splits_materials_and_strips_scripts" in text
    assert '@("passed", "warning")' in text
    assert '$V08Arguments = @()' in text
    assert "Remove-Item" not in text.replace(
        "Remove-Item Env:CBM_WORKSPACE_ROOT -ErrorAction SilentlyContinue",
        "",
    )


def test_v09_posix_gate_uses_isolated_workspace_and_queue_boundary() -> None:
    """Require the POSIX gate to match the Windows stabilization safety checks."""

    text = _script("run_v09_gates.sh")
    assert "reports/v09_smoke" in text
    assert 'export CBM_WORKSPACE_ROOT="$SMOKE_WORKSPACE"' in text
    assert "queue-enqueue" in text
    assert "queue-run" in text
    assert "waiting_for_agent" in text
    assert "workspace-audit" in text
    assert "stability-probe" in text
    assert "stability-report-pdf" in text
    assert "handoff-plan" in text
    assert "handoff-generate" in text
    assert "handoff-validate" in text
    assert "valid_handoff_count" in text
    assert "geometry_showcase" in text
    assert "CBM_RUN_EXTERNAL_INTAKE_SMOKE=1" in text
    assert "test_blender_external_intake_splits_materials_and_strips_scripts" in text
    assert 'in {"passed","warning"}' in text
    assert "V08_ARGS=()" in text
    assert "${RUN_STAMP,,}" not in text
    assert "rm -" not in text
