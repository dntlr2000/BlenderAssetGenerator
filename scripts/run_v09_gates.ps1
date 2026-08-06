param(
    [switch]$SkipVision,
    [switch]$SkipV08,
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

# Builds one real GLB package and validates a movable Codex handoff in the isolated workspace.
function Invoke-DestinationHandoffGate {
    $RunId = "v09-handoff-smoke-run"
    $ConversionId = "v09-handoff-smoke-materials"
    $PackageId = "v09-handoff-smoke-package"
    $HandoffId = "v09-handoff-smoke"
    Invoke-Uv run cbm import-example geometry_showcase
    Invoke-Uv run cbm material-scaffold geometry_showcase
    Invoke-Uv run cbm generate-procedural-textures geometry_showcase mat.blue `
        --preset rock --resolution 64 --seed 909 --uv-set UVMap --overwrite
    Invoke-Uv run cbm validate-material-contracts geometry_showcase
    Invoke-Uv run cbm build geometry_showcase
    Invoke-Uv run cbm render geometry_showcase
    Invoke-Uv run cbm inspect geometry_showcase
    Invoke-Uv run cbm validate geometry_showcase
    Invoke-Uv run cbm asset-profile-init geometry_showcase `
        --profile portable_gltf --asset-kind static_environment
    Invoke-Uv run cbm asset-preflight geometry_showcase `
        --profile portable_gltf --run-id $RunId
    Invoke-Uv run cbm asset-plan geometry_showcase `
        --profile portable_gltf --run-id $RunId
    $ReviewPlan = Join-Path $SmokeWorkspace `
        "geometry_showcase/optimization/runs/$RunId/review_plan.json"
    $ReviewHash = (Get-FileHash -Algorithm SHA256 $ReviewPlan).Hash.ToLowerInvariant()
    Invoke-Uv run cbm asset-plan-approve geometry_showcase `
        --run-id $RunId --plan-sha256 $ReviewHash `
        --approval-note "Automated isolated V0.9 handoff integration approval."
    Invoke-Uv run cbm asset-optimize geometry_showcase `
        --profile portable_gltf --run-id $RunId `
        --approved-plan-sha256 $ReviewHash
    Invoke-Uv run cbm asset-material-convert geometry_showcase `
        --profile portable_gltf --run-id $RunId --conversion-id $ConversionId `
        --resolution 1024 --margin-px 16 --render-device auto
    Invoke-Uv run cbm asset-package geometry_showcase `
        --profile portable_gltf --run-id $RunId --package-id $PackageId `
        --material-conversion-id $ConversionId
    Invoke-Uv run cbm asset-validate geometry_showcase `
        --profile portable_gltf --package-id $PackageId `
        --bounds-tolerance-m 0.0001

    $PackageManifest = Join-Path $SmokeWorkspace `
        "geometry_showcase/exports/packages/portable_gltf/$PackageId/package_manifest.json"
    $PackageHashBefore = `
        (Get-FileHash -Algorithm SHA256 $PackageManifest).Hash.ToLowerInvariant()
    Invoke-Uv run cbm handoff-plan geometry_showcase `
        --profile portable_gltf --package-id $PackageId --handoff-id $HandoffId
    $HandoffPlan = Join-Path $SmokeWorkspace `
        "geometry_showcase/handoffs/$HandoffId/handoff_plan.json"
    $HandoffPlanHash = `
        (Get-FileHash -Algorithm SHA256 $HandoffPlan).Hash.ToLowerInvariant()
    Invoke-Uv run cbm handoff-generate geometry_showcase `
        --handoff-id $HandoffId --plan-sha256 $HandoffPlanHash
    Invoke-Uv run cbm handoff-validate geometry_showcase `
        --profile portable_gltf --package-id $PackageId --handoff-id $HandoffId
    Invoke-Uv run cbm handoff-status geometry_showcase
    Invoke-Uv run cbm report-pdf geometry_showcase --scope export `
        --optimization-run-id $RunId --package-id $PackageId

    $Envelope = Join-Path $SmokeWorkspace `
        "geometry_showcase/exports/destination_handoffs/portable_gltf/$PackageId/$HandoffId"
    $Validation = Get-Content -Raw `
        (Join-Path $Envelope "destination_handoff_validation.json") | ConvertFrom-Json
    $HandoffManifest = Join-Path $Envelope "codex_handoff/handoff_manifest.json"
    $HandoffPdf = Join-Path $Envelope "codex_handoff/handoff_report.pdf"
    $HandoffPdfManifest = `
        Join-Path $Envelope "codex_handoff/handoff_report.manifest.json"
    $PackageHashAfter = `
        (Get-FileHash -Algorithm SHA256 $PackageManifest).Hash.ToLowerInvariant()
    # Known non-blocking round-trip limitations produce status=warning while ok remains true.
    if (-not $Validation.ok -or $Validation.status -notin @("passed", "warning") -or `
        -not (Test-Path $HandoffManifest) -or -not (Test-Path $HandoffPdf) -or `
        -not (Test-Path $HandoffPdfManifest) -or `
        $PackageHashBefore -ne $PackageHashAfter) {
        throw "V0.9 destination handoff gate failed or changed its source package."
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

if (-not $SkipCompatibility) {
    Invoke-Uv run cbm blender-compat
}

if (-not $SkipCompatibility -and -not $SkipV07) {
    $PreviousExternalIntakeSmoke = $env:CBM_RUN_EXTERNAL_INTAKE_SMOKE
    try {
        $env:CBM_RUN_EXTERNAL_INTAKE_SMOKE = "1"
        Invoke-Uv run pytest -q `
            tests/test_external_static_asset_intake.py::test_blender_external_intake_splits_materials_and_strips_scripts
    }
    finally {
        if ($null -eq $PreviousExternalIntakeSmoke) {
            [Environment]::SetEnvironmentVariable(
                "CBM_RUN_EXTERNAL_INTAKE_SMOKE", $null, "Process"
            )
        }
        else {
            $env:CBM_RUN_EXTERNAL_INTAKE_SMOKE = $PreviousExternalIntakeSmoke
        }
    }
}

if (-not $SkipV08) {
    $V08Arguments = @()
    if ($SkipV07) { $V08Arguments += "-SkipV07" }
    if ($SkipVision) { $V08Arguments += "-SkipVision" }
    if ($SkipCompatibility) { $V08Arguments += "-SkipCompatibility" }
    if ($SkipTextureBake) { $V08Arguments += "-SkipTextureBake" }
    & (Join-Path $PSScriptRoot "run_v08_gates.ps1") @V08Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "V0.8 regression gate failed with exit code ${LASTEXITCODE}."
    }
}

$PreviousWorkspace = $env:CBM_WORKSPACE_ROOT
$RunStamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
$SmokeRoot = Join-Path (Get-Location) "reports/v09_smoke/${RunStamp}-$PID"
$SmokeWorkspace = Join-Path $SmokeRoot "workspaces"
New-Item -ItemType Directory -Path $SmokeWorkspace -Force | Out-Null

try {
    $env:CBM_WORKSPACE_ROOT = $SmokeWorkspace
    Invoke-DestinationHandoffGate
    $Reference = (Resolve-Path "examples/geometry_showcase/reference.png").Path
    Invoke-Uv run cbm workflow-plan `
        --request "Create a bounded V0.9 proxy smoke workflow." `
        --job-id v09_queue_smoke --reference-path $Reference
    $LatestPath = Join-Path $SmokeWorkspace `
        "v09_queue_smoke/workflows/latest.json"
    $WorkflowId = (Get-Content -Raw $LatestPath | ConvertFrom-Json).workflow_id
    Invoke-Uv run cbm queue-enqueue v09_queue_smoke $WorkflowId `
        --priority 80 --max-attempts 2
    Invoke-Uv run cbm queue-run --max-entries 1 --max-host-steps 1
    $QueuePath = Join-Path $SmokeWorkspace ".cbm/queue/local_queue.json"
    $Queue = Get-Content -Raw $QueuePath | ConvertFrom-Json
    if ($Queue.max_concurrency -ne 1 -or $Queue.entries.Count -ne 1 -or `
        $Queue.entries[0].status -ne "waiting" -or `
        $Queue.entries[0].last_workflow_status -ne "waiting_for_agent") {
        throw "V0.9 local queue did not stop at the V0.8 agent boundary."
    }
    $ReceiptRoot = Join-Path $SmokeWorkspace `
        ".cbm/queue/receipts/$($Queue.entries[0].entry_id)"
    if ((Get-ChildItem $ReceiptRoot -Filter "*.json").Count -ne 1) {
        throw "V0.9 queue did not preserve exactly one immutable attempt receipt."
    }

    $AuditId = "audit-${RunStamp}-$PID".ToLowerInvariant()
    Invoke-Uv run cbm workspace-audit --job-id v09_queue_smoke `
        --audit-id $AuditId
    $AuditPath = Join-Path (Get-Location) `
        "reports/v09/audits/$AuditId/workspace_audit.json"
    $AuditText = Get-Content -Raw $AuditPath
    $Audit = $AuditText | ConvertFrom-Json
    if ($Audit.status -ne "passed" -or $Audit.scanned_job_count -ne 1) {
        throw "V0.9 isolated workspace audit did not pass."
    }
    if ($AuditText.Contains($SmokeWorkspace)) {
        throw "V0.9 audit leaked an absolute workspace path."
    }

    $HandoffAuditId = "handoff-audit-${RunStamp}-$PID".ToLowerInvariant()
    Invoke-Uv run cbm workspace-audit --job-id geometry_showcase `
        --audit-id $HandoffAuditId
    $HandoffAuditPath = Join-Path (Get-Location) `
        "reports/v09/audits/$HandoffAuditId/workspace_audit.json"
    $HandoffAudit = Get-Content -Raw $HandoffAuditPath | ConvertFrom-Json
    if ($HandoffAudit.status -ne "passed" -or `
        $HandoffAudit.handoff_count -ne 1 -or `
        $HandoffAudit.valid_handoff_count -ne 1) {
        throw "V0.9 workspace audit did not verify the isolated destination handoff."
    }

    $ProbeId = "probe-${RunStamp}-$PID".ToLowerInvariant()
    Invoke-Uv run cbm stability-probe --probe-id $ProbeId
    $ProbePath = Join-Path (Get-Location) `
        "reports/v09/environment/$ProbeId/environment_probe.json"
    $ProbeText = Get-Content -Raw $ProbePath
    if ($ProbeText.Contains((Get-Location).Path) -or `
        $ProbeText.Contains($SmokeWorkspace)) {
        throw "V0.9 environment probe leaked an absolute project or workspace path."
    }
    $ReportId = "stability-${RunStamp}-$PID".ToLowerInvariant()
    Invoke-Uv run cbm stability-report-pdf --probe-id $ProbeId `
        --audit-id $HandoffAuditId --report-id $ReportId
    $PdfRoot = Join-Path (Get-Location) "output/pdf/v09/$ReportId"
    if (-not (Test-Path (Join-Path $PdfRoot "stability_report.pdf")) -or `
        -not (Test-Path (Join-Path $PdfRoot "stability_report.manifest.json"))) {
        throw "V0.9 stability PDF or exact-hash sidecar was not generated."
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

Write-Host "V0.9 isolated stabilization gates completed: $SmokeRoot" `
    -ForegroundColor Green
