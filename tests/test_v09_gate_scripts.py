from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str) -> str:
    """Read one V0.9 gate script for deterministic boundary assertions."""

    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_v09_windows_gate_uses_isolated_workspace_and_queue_boundary() -> None:
    """Require Windows isolation, named child arguments, receipts, audit, and redaction."""

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
    assert '$V08Arguments = @{ RetentionPolicy = $RetentionPolicy }' in text
    assert '".t/v9p-${PytestStamp}-$PID"' in text
    assert (
        "Invoke-Uv run python scripts/run_pytest_acl_safe.py --basetemp $PytestRoot"
        in text
    )
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
    assert 'PYTEST_ROOT_RELATIVE=".t/v9p-' in text
    assert 'uv run pytest --basetemp "$PYTEST_ROOT"' in text
    assert "scripts/finalize_gate_run.py" in text
    assert '--retention-policy "$RETENTION_POLICY"' in text
    assert "${RUN_STAMP,,}" not in text
    assert "rm -" not in text


def test_v09_windows_gate_hashes_without_module_autoloading() -> None:
    """Use the .NET SHA-256 primitive for every exact Windows gate binding."""

    text = _script("run_v09_gates.ps1")
    assert "[System.Security.Cryptography.SHA256]::Create()" in text
    assert "Get-FileHash" not in text


@pytest.mark.parametrize("gate", ["aq", "v09", "v08"])
@pytest.mark.parametrize("policy,enabled", [("Preserve", True), ("CompactSuccess", False)])
def test_windows_nested_gates_bind_actual_named_parameters(
    tmp_path: Path, gate: str, policy: str, enabled: bool,
) -> None:
    """Execute each real child-call block against an inert script to catch positional flags."""

    shell = shutil.which("pwsh")
    if shell is None:
        pytest.skip("PowerShell is required to execute native child-script argument binding")
    child = '''param(
    [switch]$SkipVision, [switch]$SkipTextureBake,
    [switch]$SkipV07, [switch]$SkipCompatibility,
    [ValidateSet("CompactSuccess", "Preserve")][string]$RetentionPolicy
)
$PSBoundParameters | ConvertTo-Json -Compress
exit 0
'''
    for name in ("run_v09_gates.ps1", "run_v08_gates.ps1", "run_v07_gates.ps1"):
        (tmp_path / name).write_text(child, encoding="utf-8")
    probe = tmp_path / "probe.ps1"
    probe.write_text('''param([string]$SourcePath, [string]$FixtureRoot,
    [string]$Gate, [string]$Policy, [int]$Enabled)
$ErrorActionPreference = "Stop"
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $SourcePath, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw "Source gate did not parse" }
$nodes = $ast.FindAll({ param($node)
    if ($Gate -eq "aq") {
        return $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Invoke-LegacyRegressionGates"
    }
    $condition = if ($Gate -eq "v09") { "-not `$SkipV08" } else { "-not `$SkipV07" }
    return $node -is [System.Management.Automation.Language.IfStatementAst] -and
        $node.Clauses[0].Item1.Extent.Text -eq $condition
}, $true)
if ($nodes.Count -ne 1) { throw "Expected exactly one nested gate call block" }
$body = if ($Gate -eq "aq") { $nodes[0].Body.Extent.Text }
    else { $nodes[0].Clauses[0].Item2.Extent.Text }
$body = $body.Substring(1, $body.Length - 2).Replace('$PSScriptRoot', '$FixtureRoot')
$RetentionPolicy = $Policy
$SkipVision = $SkipTextureBake = $SkipCompatibility = $SkipV07 = [bool]$Enabled
& ([scriptblock]::Create($body))
''', encoding="utf-8")
    source_name = "run_autonomous_quality_gates.ps1" if gate == "aq" else f"run_{gate}_gates.ps1"
    result = subprocess.run(
        [shell, "-NoProfile", "-File", str(probe),
         "-SourcePath", str(ROOT / "scripts" / source_name),
         "-FixtureRoot", str(tmp_path), "-Gate", gate,
         "-Policy", policy, "-Enabled", str(int(enabled))],
        cwd=tmp_path, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    bound = {
        key: value.get("IsPresent") if isinstance(value, dict) else value
        for key, value in json.loads(result.stdout).items()
    }
    expected = {"RetentionPolicy": policy}
    if enabled:
        expected.update(SkipVision=True, SkipTextureBake=True)
        if gate != "aq":
            expected["SkipCompatibility"] = True
        if gate == "v09":
            expected["SkipV07"] = True
    assert bound == expected
