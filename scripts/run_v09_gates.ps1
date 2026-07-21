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
        --audit-id $AuditId --report-id $ReportId
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
