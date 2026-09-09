from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_GATE = ROOT / "scripts" / "run_v07_gates.ps1"
SHELL_GATE = ROOT / "scripts" / "run_v07_gates.sh"


def _source(path: Path) -> str:
    """Read one platform gate script for deterministic source-order checks."""

    return path.read_text(encoding="utf-8")


def test_v071_gates_convert_materials_before_packaging() -> None:
    """Both isolated gates insert the V0.7.1 conversion between optimize and package."""

    for path in (POWERSHELL_GATE, SHELL_GATE):
        source = _source(path)
        optimize = source.index("asset-optimize geometry_showcase")
        convert = source.index("asset-material-convert geometry_showcase")
        package = source.index("asset-package geometry_showcase")
        assert optimize < convert < package
        assert "--resolution 1024" in source
        assert "--margin-px 16" in source
        assert "--render-device auto" in source
        assert "--material-conversion-id" in source


def test_v074_gates_review_and_approve_exact_plan_before_optimization() -> None:
    """Both isolated gates exercise the required hash-bound pre-optimization decision."""

    for path in (POWERSHELL_GATE, SHELL_GATE):
        source = _source(path)
        review = source.index("asset-plan geometry_showcase")
        approval = source.index("asset-plan-approve geometry_showcase")
        optimize = source.index("asset-optimize geometry_showcase")
        assert review < approval < optimize
        assert "review_plan.json" in source
        assert "--approved-plan-sha256" in source


def test_v071_gates_use_distinct_deterministic_conversion_ids() -> None:
    """Every engine-neutral profile owns an unambiguous immutable conversion ID."""

    expected = {
        "v071-gltf-smoke-materials",
        "v071-fbx-smoke-materials",
        "v071-obj-smoke-materials",
    }
    for path in (POWERSHELL_GATE, SHELL_GATE):
        source = _source(path)
        assert all(identifier in source for identifier in expected)
        assert source.count("v071-gltf-smoke-materials") >= 2
        assert "conversion_manifest.json" in source


def test_v071_gates_use_short_repository_local_pytest_roots() -> None:
    """Keep deeply nested gate fixtures inside the ignored short-path test root."""

    for path in (POWERSHELL_GATE, SHELL_GATE):
        source = _source(path)
        assert "--basetemp" in source
        assert ".t/v7p-" in source
        assert "scripts/finalize_gate_run.py" in source
        assert "retention-policy" in source.lower()
        if path.suffix == ".ps1":
            assert "scripts/run_pytest_acl_safe.py" in source


def test_v071_windows_gate_hashes_without_module_autoloading() -> None:
    """Use the .NET SHA-256 primitive instead of an optional PowerShell cmdlet."""

    source = _source(POWERSHELL_GATE)
    assert "[System.Security.Cryptography.SHA256]::Create()" in source
    assert "Get-FileHash" not in source
