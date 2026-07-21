param(
    [switch]$SkipVision,
    [switch]$SkipExports,
    [switch]$SkipMcpCycles
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

# Runs one uv command and converts a native non-zero exit code into a terminating error.
function Invoke-Uv {
    & uv @args
    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed with exit code ${LASTEXITCODE}: $($args -join ' ')"
    }
}

if ($SkipVision) {
    Invoke-Uv sync --frozen --extra dev
} else {
    Invoke-Uv sync --frozen --extra dev --extra vision
}

Invoke-Uv run pytest
Invoke-Uv run ruff check .
Invoke-Uv run cbm doctor

if ($SkipExports) {
    Invoke-Uv run cbm blender-compat --no-smoke-exports
} else {
    Invoke-Uv run cbm blender-compat
}

function Ensure-Example([string]$Name) {
    $JobJson = Join-Path (Join-Path "workspaces" $Name) "job.json"
    if (-not (Test-Path $JobJson)) {
        Invoke-Uv run cbm import-example $Name
    }
}

Ensure-Example "geometry_showcase"
Invoke-Uv run cbm build geometry_showcase
Invoke-Uv run cbm render geometry_showcase
Invoke-Uv run cbm inspect geometry_showcase
Invoke-Uv run cbm validate geometry_showcase
if (-not $SkipExports) {
    Invoke-Uv run cbm export geometry_showcase --format glb
    Invoke-Uv run cbm export geometry_showcase --format obj
    Invoke-Uv run cbm export geometry_showcase --format fbx
}

Ensure-Example "measured_box"
Invoke-Uv run cbm analyze-reference measured_box --projection ortho
Invoke-Uv run cbm build measured_box
Invoke-Uv run cbm render measured_box
Invoke-Uv run cbm inspect measured_box
Invoke-Uv run cbm validate measured_box
Invoke-Uv run cbm evaluate-constraints measured_box

Ensure-Example "first_reference_test"
Invoke-Uv run cbm analyze-reference first_reference_test
Invoke-Uv run cbm build first_reference_test
Invoke-Uv run cbm render first_reference_test
Invoke-Uv run cbm inspect first_reference_test
Invoke-Uv run cbm validate first_reference_test

Invoke-Uv run python scripts/verify_v04_regressions.py
if (-not $SkipMcpCycles) {
    Invoke-Uv run python scripts/run_v04_mcp_regressions.py --render-engine cycles --render-device gpu
}

Write-Host "V0.4 local gates completed." -ForegroundColor Green
