param(
    [switch]$SkipVision,
    [switch]$SkipCompatibility,
    [switch]$SkipTextureBake
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

# Runs one uv command and turns a native non-zero exit into a terminating gate failure.
function Invoke-Uv {
    & uv @args
    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed with exit code ${LASTEXITCODE}: $($args -join ' ')"
    }
}

# Runs one profile through cost-aware optimization, material conversion, package, and round trip.
function Invoke-PortableProfileGate(
    [string]$Profile,
    [string]$RunId,
    [string]$ConversionId,
    [string]$PackageId
) {
    Invoke-Uv run cbm asset-profile-init geometry_showcase `
        --profile $Profile --asset-kind static_environment
    Invoke-Uv run cbm asset-preflight geometry_showcase `
        --profile $Profile --run-id $RunId
    Invoke-Uv run cbm asset-plan geometry_showcase `
        --profile $Profile --run-id $RunId
    $PlanPath = Join-Path $SmokeWorkspace `
        "geometry_showcase/optimization/runs/$RunId/review_plan.json"
    $PlanHash = (Get-FileHash -Algorithm SHA256 $PlanPath).Hash.ToLowerInvariant()
    Invoke-Uv run cbm asset-plan-approve geometry_showcase `
        --run-id $RunId --plan-sha256 $PlanHash `
        --approval-note "Automated isolated V0.7.4 integration fixture approval."
    Invoke-Uv run cbm asset-optimize geometry_showcase `
        --profile $Profile --run-id $RunId --approved-plan-sha256 $PlanHash
    $CostReport = Join-Path $SmokeWorkspace `
        "geometry_showcase/optimization/runs/$RunId/asset_cost_report.json"
    if (-not (Test-Path $CostReport)) {
        throw "V0.7.4 static asset cost report is missing: $CostReport"
    }
    $CostPayload = Get-Content -Raw $CostReport | ConvertFrom-Json
    if (-not $CostPayload.ok -or $CostPayload.canonical_unchanged -ne $true) {
        throw "V0.7.4 static asset cost report did not pass: $CostReport"
    }
    Invoke-Uv run cbm asset-material-convert geometry_showcase `
        --profile $Profile --run-id $RunId --conversion-id $ConversionId `
        --resolution 1024 --margin-px 16 --render-device auto
    Invoke-Uv run cbm asset-package geometry_showcase `
        --profile $Profile --run-id $RunId --package-id $PackageId `
        --material-conversion-id $ConversionId
    Invoke-Uv run cbm asset-validate geometry_showcase `
        --profile $Profile --package-id $PackageId `
        --bounds-tolerance-m 0.0001
}

if ($SkipVision) {
    Invoke-Uv sync --frozen --extra dev
}
else {
    Invoke-Uv sync --frozen --extra dev --extra vision
}

Invoke-Uv run pytest
Invoke-Uv run ruff check .
Invoke-Uv run cbm doctor
if (-not $SkipCompatibility) {
    Invoke-Uv run cbm blender-compat
}

$PreviousWorkspace = $env:CBM_WORKSPACE_ROOT
$RunStamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
$SmokeRoot = Join-Path (Get-Location) "reports/v07_smoke/${RunStamp}-$PID"
$SmokeWorkspace = Join-Path $SmokeRoot "workspaces"
New-Item -ItemType Directory -Path $SmokeWorkspace -Force | Out-Null

try {
    $env:CBM_WORKSPACE_ROOT = $SmokeWorkspace
    Invoke-Uv run cbm import-example geometry_showcase
    Invoke-Uv run cbm material-scaffold geometry_showcase
    Invoke-Uv run cbm generate-procedural-textures geometry_showcase mat.blue `
        --preset rock --resolution 128 --seed 707 --uv-set UVMap --overwrite
    Invoke-Uv run cbm validate-material-contracts geometry_showcase
    Invoke-Uv run cbm build geometry_showcase
    Invoke-Uv run cbm render geometry_showcase
    Invoke-Uv run cbm inspect geometry_showcase
    Invoke-Uv run cbm validate geometry_showcase
    if (-not $SkipTextureBake) {
        Invoke-Uv run cbm bake-materials geometry_showcase --profile gltf_pbr `
            --resolution 128 --material-id mat.blue
    }

    Invoke-PortableProfileGate portable_gltf v07-gltf-smoke-run `
        v071-gltf-smoke-materials v07-gltf-smoke-package
    Invoke-PortableProfileGate fbx_interchange v07-fbx-smoke-run `
        v071-fbx-smoke-materials v07-fbx-smoke-package
    Invoke-PortableProfileGate obj_legacy v07-obj-smoke-run `
        v071-obj-smoke-materials v07-obj-smoke-package
    Invoke-Uv run cbm asset-status geometry_showcase
    Invoke-Uv run cbm report-pdf geometry_showcase --scope export `
        --optimization-run-id v07-gltf-smoke-run `
        --package-id v07-gltf-smoke-package

    $PackageManifest = Join-Path $SmokeWorkspace `
        "geometry_showcase/exports/packages/portable_gltf/v07-gltf-smoke-package/package_manifest.json"
    $RoundTrip = Join-Path $SmokeWorkspace `
        "geometry_showcase/optimization/runs/v07-gltf-smoke-run/roundtrip/v07-gltf-smoke-package/roundtrip_validation.json"
    $MaterialConversion = Join-Path $SmokeWorkspace `
        "geometry_showcase/optimization/material_conversions/v07-gltf-smoke-run/v071-gltf-smoke-materials/conversion_manifest.json"
    if (-not (Test-Path $MaterialConversion) -or `
        -not (Test-Path $PackageManifest) -or -not (Test-Path $RoundTrip)) {
        throw "V0.7 material conversion, package, or round-trip evidence is missing from the isolated smoke workspace."
    }
}
finally {
    if ($null -eq $PreviousWorkspace) {
        Remove-Item Env:CBM_WORKSPACE_ROOT -ErrorAction SilentlyContinue
    }
    else {
        $env:CBM_WORKSPACE_ROOT = $PreviousWorkspace
    }
}

Write-Host "V0.7.4 isolated portable static-asset gates completed: $SmokeRoot" `
    -ForegroundColor Green
