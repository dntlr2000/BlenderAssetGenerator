param(
    [switch]$RunBlender,
    [switch]$SkipFullRegression,
    [switch]$SkipLegacyGates,
    [switch]$SkipVision,
    [switch]$SkipTextureBake,
    [string]$OutputRoot
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

# Runs one uv command and converts a native non-zero exit into a terminating gate failure.
function Invoke-Uv {
    & uv @args
    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed with exit code ${LASTEXITCODE}: $($args -join ' ')"
    }
}

# Runs one native command and preserves its exact failure as a gate failure.
function Invoke-Native {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "native command failed with exit code ${LASTEXITCODE}: $Command"
    }
}

# Runs the existing V0.9 gate, which transitively preserves the V0.8 and V0.7 gates.
function Invoke-LegacyRegressionGates {
    $LegacyArguments = @()
    if ($SkipVision) { $LegacyArguments += "-SkipVision" }
    if ($SkipTextureBake) { $LegacyArguments += "-SkipTextureBake" }
    & (Join-Path $PSScriptRoot "run_v09_gates.ps1") @LegacyArguments
}

if (-not $OutputRoot) {
    # Keep the default short enough for nested Blender/package evidence on Windows.
    $OutputRoot = Join-Path ([System.IO.Path]::GetTempPath()) "aqg-$PID"
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$BenchmarkReport = Join-Path $OutputRoot "autonomous_quality_benchmark.json"

if ($SkipVision) {
    Invoke-Uv sync --frozen --extra dev
}
else {
    Invoke-Uv sync --frozen --extra dev --extra vision
}

$FocusedTests = @(
    "tests/test_autonomous_quality_benchmarks.py",
    "tests/test_autonomous_quality_schemas.py",
    "tests/test_autonomous_quality_public_surface.py",
    "tests/test_aq_evidence_envelopes.py",
    "tests/test_autonomous_quality_blender_evidence.py",
    "tests/test_autonomous_structural_geometry.py",
    "tests/test_scene_spec_v03_migration_public.py",
    "tests/test_reference_evidence_aq.py",
    "tests/test_integrated_quality_aq.py",
    "tests/test_integrated_quality_hard_gate_evidence.py",
    "tests/test_material_graph_aq.py",
    "tests/test_assembly_topology_aq.py",
    "tests/test_blender_companion_service.py",
    "tests/test_autonomy_aq.py",
    "tests/test_autonomy_authorization_hardening.py",
    "tests/test_autonomy_candidate_quality_aq.py",
    "tests/test_autonomy_candidate_scope.py",
    "tests/test_autonomy_structural_candidate_reachability.py",
    "tests/test_autonomy_failure_recovery_aq.py",
    "tests/test_autonomy_material_rounds_aq.py",
    "tests/test_autonomy_production_budget_aq.py",
    "tests/test_autonomy_review_bundle_aq.py",
    "tests/test_autonomy_terminal_verifier_aq.py",
    "tests/test_autonomy_worker.py",
    "tests/test_packaging_long_paths_aq.py"
)
Invoke-Uv run pytest -q --basetemp (Join-Path $OutputRoot "pt-focused") @FocusedTests
Invoke-Uv run ruff check .
Invoke-Uv run cbm doctor

if (-not $SkipFullRegression) {
    Invoke-Uv run pytest --basetemp (Join-Path $OutputRoot "pt-full")
}

$BenchmarkArguments = @(
    "run", "python", "-m", "codex_blender_modeler.autonomy_benchmarks",
    "--manifest", "examples/autonomous_quality_benchmarks/manifest.json",
    "--output", $BenchmarkReport
)

if ($RunBlender) {
    $PreviousGeometrySmoke = $env:CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE
    $PreviousAutonomySmoke = $env:CBM_RUN_AUTONOMY_E2E_SMOKE
    $PreviousQualitySmoke = $env:CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE
    $PreviousPortableLongPathSmoke = $env:CBM_RUN_PORTABLE_LONG_PATH_BLENDER_SMOKE
    try {
        $env:CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE = "1"
        $env:CBM_RUN_AUTONOMY_E2E_SMOKE = "1"
        $env:CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE = "1"
        $env:CBM_RUN_PORTABLE_LONG_PATH_BLENDER_SMOKE = "1"
        Invoke-Uv run cbm blender-compat
        Invoke-Uv run pytest -q --basetemp (Join-Path $OutputRoot "pt-blender") `
            tests/test_autonomous_structural_geometry_blender.py `
            tests/test_autonomous_quality_blender_evidence.py::test_blender_scale_assembly_and_topology_evidence `
            tests/test_blender_companion_service.py::test_static_prop_authoring_companions_are_hash_bound_and_read_only `
            tests/test_v07_blender_scripts.py::test_blender_runtime_writes_portable_json_to_extended_path `
            tests/test_autonomy_candidate_blender.py::test_initial_candidate_build_qa_and_policy_promotion `
            tests/test_autonomy_candidate_blender.py::test_autonomous_static_prop_reaches_one_terminal_delivery `
            tests/test_autonomy_candidate_blender.py::test_autonomous_static_prop_publishes_review_only_bundle_without_package
        $BenchmarkArguments += "--run-blender"
    }
    finally {
        if ($null -eq $PreviousGeometrySmoke) {
            Remove-Item Env:CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE = $PreviousGeometrySmoke
        }
        if ($null -eq $PreviousAutonomySmoke) {
            Remove-Item Env:CBM_RUN_AUTONOMY_E2E_SMOKE -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_AUTONOMY_E2E_SMOKE = $PreviousAutonomySmoke
        }
        if ($null -eq $PreviousQualitySmoke) {
            Remove-Item Env:CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE = $PreviousQualitySmoke
        }
        if ($null -eq $PreviousPortableLongPathSmoke) {
            Remove-Item Env:CBM_RUN_PORTABLE_LONG_PATH_BLENDER_SMOKE `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_PORTABLE_LONG_PATH_BLENDER_SMOKE = $PreviousPortableLongPathSmoke
        }
    }

    if (-not $SkipLegacyGates) {
        Invoke-LegacyRegressionGates
    }
}

Invoke-Uv @BenchmarkArguments
Invoke-Native -Command "git" -Arguments @("diff", "--check")

Write-Host "Autonomous Quality 0.1.0 gates completed: $OutputRoot" `
    -ForegroundColor Green
