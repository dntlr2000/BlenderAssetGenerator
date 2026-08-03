param(
    [switch]$SkipVision,
    [switch]$SkipExports,
    [switch]$SkipMcpCycles,
    [switch]$SkipV04,
    [switch]$SkipV06Mcp
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

if (-not $SkipV04) {
    & .\scripts\run_v04_gates.ps1 `
        -SkipVision:$SkipVision `
        -SkipExports:$SkipExports `
        -SkipMcpCycles:$SkipMcpCycles
    if ($LASTEXITCODE -ne 0) {
        throw "V0.4 gate failed with exit code ${LASTEXITCODE}"
    }
}
else {
    Invoke-Uv run pytest
    Invoke-Uv run ruff check .
    Invoke-Uv run cbm doctor
}

$PreviousWorkspace = $env:CBM_WORKSPACE_ROOT
$SmokeWorkspace = Join-Path (Get-Location) "reports/v06_smoke/workspaces"
New-Item -ItemType Directory -Path $SmokeWorkspace -Force | Out-Null

try {
    $env:CBM_WORKSPACE_ROOT = $SmokeWorkspace
    $SmokeJob = Join-Path $SmokeWorkspace "geometry_showcase/job.json"
    if (-not (Test-Path $SmokeJob)) {
        Invoke-Uv run cbm import-example geometry_showcase
    }
    $MaterialPlan = Join-Path $SmokeWorkspace "geometry_showcase/analysis/material_plan.json"
    if (-not (Test-Path $MaterialPlan)) {
        Invoke-Uv run cbm material-scaffold geometry_showcase
    }
    Invoke-Uv run cbm generate-procedural-textures geometry_showcase mat.blue `
        --preset rock --resolution 128 --seed 606 --uv-set UVMap --overwrite
    Invoke-Uv run cbm validate-material-contracts geometry_showcase
    Invoke-Uv run cbm build geometry_showcase
    Invoke-Uv run cbm render geometry_showcase
    Invoke-Uv run cbm validate geometry_showcase
    Invoke-Uv run cbm inspect-materials geometry_showcase
    Invoke-Uv run cbm render-material-swatches geometry_showcase --size 256
    Invoke-Uv run cbm bake-materials geometry_showcase --profile gltf_pbr `
        --resolution 128 --material-id mat.blue
    Invoke-Uv run cbm analyze-reference geometry_showcase
    Invoke-Uv run cbm visual-qa geometry_showcase
    $QaLatestPath = Join-Path $SmokeWorkspace "geometry_showcase/qa/latest.json"
    $QaRunId = (Get-Content -Raw $QaLatestPath | ConvertFrom-Json).run_id
    Invoke-Uv run cbm qa-diagnose geometry_showcase --qa-run-id $QaRunId
    Invoke-Uv run cbm qa-semantic-masks-status geometry_showcase
    Invoke-Uv run cbm report-pdf geometry_showcase --scope material
    Invoke-Uv run cbm report-pdf geometry_showcase --scope qa --qa-run-id latest
    Invoke-Uv run cbm report-pdf geometry_showcase --scope full --qa-run-id latest
    $env:CBM_V06_MATERIAL_JOB = "geometry_showcase"
    $env:CBM_V06_QA_JOB = "geometry_showcase"
    Invoke-Uv run python scripts/verify_v06_artifacts.py
    Invoke-Uv run python scripts/run_advisory_target_smoke.py

    if (-not $SkipV06Mcp) {
        Invoke-Uv run python scripts/run_v06_mcp_regressions.py
        $QaRunId = (Get-Content -Raw $QaLatestPath | ConvertFrom-Json).run_id
        Invoke-Uv run cbm qa-diagnose geometry_showcase --qa-run-id $QaRunId
        # Rebind both QA-derived PDFs after diagnostics extend the exact MCP QA evidence.
        Invoke-Uv run cbm report-pdf geometry_showcase --scope qa --qa-run-id latest
        Invoke-Uv run cbm report-pdf geometry_showcase --scope full --qa-run-id latest
        Invoke-Uv run python scripts/verify_v06_artifacts.py
    }
}
finally {
    if ($null -eq $PreviousWorkspace) {
        Remove-Item Env:CBM_WORKSPACE_ROOT -ErrorAction SilentlyContinue
    }
    else {
        $env:CBM_WORKSPACE_ROOT = $PreviousWorkspace
    }
    Remove-Item Env:CBM_V06_MATERIAL_JOB -ErrorAction SilentlyContinue
    Remove-Item Env:CBM_V06_QA_JOB -ErrorAction SilentlyContinue
}

Write-Host "V0.6 material, shader, and visual-QA gates completed." -ForegroundColor Green
