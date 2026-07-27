param(
    [switch]$SkipVision,
    [switch]$SkipV07,
    [switch]$SkipCompatibility,
    [switch]$SkipTextureBake
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

if ($SkipVision) {
    Invoke-Uv sync --frozen --extra dev
}
else {
    Invoke-Uv sync --frozen --extra dev --extra vision
}

Invoke-Uv run pytest
Invoke-Uv run ruff check .
Invoke-Uv run cbm doctor

if (-not $SkipV07) {
    $V07Arguments = @()
    if ($SkipVision) { $V07Arguments += "-SkipVision" }
    if ($SkipCompatibility) { $V07Arguments += "-SkipCompatibility" }
    if ($SkipTextureBake) { $V07Arguments += "-SkipTextureBake" }
    & (Join-Path $PSScriptRoot "run_v07_gates.ps1") @V07Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "V0.7 regression gate failed with exit code ${LASTEXITCODE}."
    }
}

$PreviousWorkspace = $env:CBM_WORKSPACE_ROOT
$RunStamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
$SmokeRoot = Join-Path (Get-Location) "reports/v08_smoke/${RunStamp}-$PID"
$SmokeWorkspace = Join-Path $SmokeRoot "workspaces"
New-Item -ItemType Directory -Path $SmokeWorkspace -Force | Out-Null

try {
    $env:CBM_WORKSPACE_ROOT = $SmokeWorkspace
    $Reference = (Resolve-Path "examples/geometry_showcase/reference.png").Path
    Invoke-Uv run cbm workflow-plan `
        --request "Create a 3D proxy model from this image." `
        --job-id v08_proxy_smoke --reference-path $Reference
    $LatestPath = Join-Path $SmokeWorkspace `
        "v08_proxy_smoke/workflows/latest.json"
    $WorkflowId = (Get-Content -Raw $LatestPath | ConvertFrom-Json).workflow_id
    Invoke-Uv run cbm workflow-resume v08_proxy_smoke $WorkflowId `
        --max-host-steps 1
    Invoke-Uv run cbm workflow-status v08_proxy_smoke `
        --workflow-id $WorkflowId
    $StatePath = Join-Path $SmokeWorkspace `
        "v08_proxy_smoke/workflows/$WorkflowId/state.json"
    $State = Get-Content -Raw $StatePath | ConvertFrom-Json
    if ($State.status -ne "waiting_for_agent" -or `
        $State.current_step_id -ne "geometry.modeling_plan") {
        throw "V0.8 proxy workflow did not stop at the modeling-plan agent boundary."
    }

    Invoke-Uv run cbm workflow-plan `
        --request "Create a static exterior background preview." `
        --job-id v08_background_preview_smoke --reference-path $Reference `
        --execution-policy background_exterior --delivery-scope preview_only
    $BackgroundPreviewLatest = Join-Path $SmokeWorkspace `
        "v08_background_preview_smoke/workflows/latest.json"
    $BackgroundPreviewWorkflowId = `
        (Get-Content -Raw $BackgroundPreviewLatest | ConvertFrom-Json).workflow_id
    $BackgroundPreviewPlanPath = Join-Path $SmokeWorkspace `
        "v08_background_preview_smoke/workflows/$BackgroundPreviewWorkflowId/plan.json"
    $BackgroundPreviewPlan = `
        Get-Content -Raw $BackgroundPreviewPlanPath | ConvertFrom-Json
    $BackgroundPreviewRequestPath = Join-Path $SmokeWorkspace `
        "v08_background_preview_smoke/workflows/$BackgroundPreviewWorkflowId/request.json"
    $BackgroundPreviewRequest = `
        Get-Content -Raw $BackgroundPreviewRequestPath | ConvertFrom-Json
    $BackgroundPreviewQa = @(
        $BackgroundPreviewPlan.steps | Where-Object { $_.step_id -eq "qa.run" }
    )
    $BackgroundPreviewTerminal = $BackgroundPreviewPlan.steps | `
        Where-Object { $_.step_id -eq $BackgroundPreviewPlan.terminal_step_id }
    if ($BackgroundPreviewPlan.execution_policy -ne "background_exterior" -or `
        $BackgroundPreviewPlan.delivery_scope -ne "preview_only" -or `
        $BackgroundPreviewRequest.budgets.max_qa_iterations -ne 1 -or `
        $BackgroundPreviewRequest.budgets.max_texture_resolution -gt 512 -or `
        $BackgroundPreviewRequest.budgets.external_provider_budget -ne 0 -or `
        $BackgroundPreviewQa.Count -ne 1 -or `
        $BackgroundPreviewQa[0].parameters.include_generated_target -ne $false -or `
        -not $BackgroundPreviewQa[0].parameters.run_id -or `
        -not ($BackgroundPreviewPlan.steps.step_id -contains "background.eligibility") -or `
        $BackgroundPreviewTerminal.parameters.qa_run_id -eq "latest" -or `
        ($BackgroundPreviewPlan.steps | `
            Where-Object { $_.execution_mode -match "approval" }).Count -ne 0 -or `
        ($BackgroundPreviewPlan.steps | `
            Where-Object { $_.phase -eq "portable" }).Count -ne 0) {
        throw "V0.8 background preview plan violated its bounded fast-lane contract."
    }

    Invoke-Uv run cbm workflow-plan `
        --request "Create a static exterior background FBX package." `
        --job-id v08_background_package_smoke --reference-path $Reference `
        --execution-policy background_exterior `
        --delivery-scope portable_package `
        --profile fbx_interchange --destination engine_neutral
    $BackgroundPackageLatest = Join-Path $SmokeWorkspace `
        "v08_background_package_smoke/workflows/latest.json"
    $BackgroundPackageWorkflowId = `
        (Get-Content -Raw $BackgroundPackageLatest | ConvertFrom-Json).workflow_id
    $BackgroundPackagePlanPath = Join-Path $SmokeWorkspace `
        "v08_background_package_smoke/workflows/$BackgroundPackageWorkflowId/plan.json"
    $BackgroundPackagePlan = `
        Get-Content -Raw $BackgroundPackagePlanPath | ConvertFrom-Json
    $BackgroundPackageTerminal = $BackgroundPackagePlan.steps | `
        Where-Object { $_.step_id -eq $BackgroundPackagePlan.terminal_step_id }
    $BackgroundSpecialized = @(
        $BackgroundPackagePlan.steps | `
            Where-Object { $_.execution_mode -eq "specialized_approval" }
    )
    if (($BackgroundPackagePlan.steps | `
            Where-Object { $_.execution_mode -eq "approval" }).Count -ne 0 -or `
        $BackgroundSpecialized.Count -ne 1 -or `
        $BackgroundSpecialized[0].approval_gate -ne "optimization_plan" -or `
        $BackgroundPackagePlan.execution_policy -ne "background_exterior" -or `
        $BackgroundPackagePlan.delivery_scope -ne "portable_package" -or `
        -not ($BackgroundPackagePlan.steps.step_id -contains "background.eligibility") -or `
        $BackgroundPackageTerminal.parameters.qa_run_id -eq "latest" -or `
        $BackgroundPackageTerminal.parameters.optimization_run_id -eq "latest" -or `
        $BackgroundPackageTerminal.parameters.package_id -eq "latest" -or `
        ($BackgroundPackagePlan.steps.step_id -contains "portable.final_approval")) {
        throw "V0.8 background package plan did not preserve only V0.7 approval."
    }

    Invoke-Uv run cbm import-example geometry_showcase
    Invoke-Uv run cbm workflow-plan `
        --request "Prepare an FBX package for Unity." `
        --job-id geometry_showcase --intent portable_package `
        --profile fbx_interchange --destination unity `
        --include-destination-handoff
    $PortableLatest = Join-Path $SmokeWorkspace `
        "geometry_showcase/workflows/latest.json"
    $PortableWorkflowId = `
        (Get-Content -Raw $PortableLatest | ConvertFrom-Json).workflow_id
    $PortablePlanPath = Join-Path $SmokeWorkspace `
        "geometry_showcase/workflows/$PortableWorkflowId/plan.json"
    $PortablePlan = Get-Content -Raw $PortablePlanPath | ConvertFrom-Json
    if ($PortablePlan.destination.status -ne "unsupported" -or `
        $PortablePlan.destination.terminal_boundary -ne "portable_package" -or `
        $PortablePlan.terminal_step_id -ne "destination.handoff") {
        throw "V0.8 did not preserve the optional handoff boundary for Unity."
    }
    $HandoffStep = $PortablePlan.steps | `
        Where-Object { $_.step_id -eq "destination.handoff" }
    if ($null -eq $HandoffStep -or `
        $HandoffStep.depends_on[0] -ne "portable.final_approval") {
        throw "V0.8 destination handoff is not downstream of exact package approval."
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

Write-Host "V0.8 isolated orchestration gates completed: $SmokeRoot" `
    -ForegroundColor Green
