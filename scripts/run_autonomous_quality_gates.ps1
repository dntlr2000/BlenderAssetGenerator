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
    # Keep the default short and repository-local for nested Blender/package evidence.
    $OutputRoot = Join-Path (Get-Location) ".codex_test/aqg-$PID"
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
# Keep pytest repository-local while staying short enough for Windows nested evidence paths.
$PytestRoot = Join-Path (Get-Location) ".t/aqp-$PID"
New-Item -ItemType Directory -Path $PytestRoot -Force | Out-Null
$BenchmarkReport = Join-Path $OutputRoot "autonomous_quality_benchmark.json"
$BenchmarkV02Report = Join-Path $OutputRoot "autonomous_quality_benchmark_v02.json"

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
    "tests/test_packaging_long_paths_aq.py",
    "tests/test_aq_v02_geometry.py",
    "tests/test_aq_v02_delivery_geometry_blender.py",
    "tests/test_aq_v02_schema_registry.py",
    "tests/test_autonomy_v2_contracts.py",
    "tests/test_autonomy_v2_planner.py",
    "tests/test_autonomy_v2_controller_bridge.py",
    "tests/test_autonomy_v2_candidate_validation.py",
    "tests/test_autonomy_v2_candidate_validation_blender.py",
    "tests/test_autonomy_v2_delivery_executor.py",
    "tests/test_autonomy_v2_delivery_service.py",
    "tests/test_autonomy_v2_material_phase.py",
    "tests/test_autonomy_v2_quality_binding.py",
    "tests/test_autonomy_v2_quality_terminal.py",
    "tests/test_autonomy_v2_supervisor_delivery.py",
    "tests/test_autonomy_v2_supervisor_public.py",
    "tests/test_controller_executor_v02.py",
    "tests/test_geometry_intent_v02_reachability.py",
    "tests/test_integrated_quality_v02_metrics.py",
    "tests/test_integrated_quality_v02_ranking.py",
    "tests/test_integrated_quality_v02_service.py",
    "tests/test_integrated_quality_v02_schemas.py",
    "tests/test_material_graph_runtime.py",
    "tests/test_material_authoring_v02.py",
    "tests/test_material_authoring_schemas_v02.py",
    "tests/test_material_authoring_blender_v02.py",
    "tests/test_advanced_material_handoff_v02.py",
    "tests/test_codex_imagegen_core.py",
    "tests/test_codex_imagegen_security.py",
    "tests/test_codex_imagegen_schemas.py",
    "tests/test_autonomy_v2_codex_image_planner.py",
    "tests/test_autonomy_v2_codex_image_overlay.py",
    "tests/test_autonomy_v2_codex_image_phase_service.py",
    "tests/test_codex_image_material_authoring_v021.py",
    "tests/test_codex_imagegen_public_surface.py",
    "tests/test_codex_image_material_loop_contracts.py",
    "tests/test_codex_image_material_loop_normalization.py",
    "tests/test_codex_image_material_loop_selection.py",
    "tests/test_codex_image_material_loop_v05_adapter.py",
    "tests/test_codex_image_material_preview_service.py",
    "tests/test_codex_image_material_quality_service.py",
    "tests/test_codex_image_material_loop_service.py",
    "tests/test_codex_image_material_loop_public.py",
    "tests/test_material_closure_contracts.py",
    "tests/test_material_closure_service.py",
    "tests/test_material_closure_aq_integration.py",
    "tests/test_material_closure_schemas.py",
    "tests/test_material_closure_controller_repair.py",
    "tests/test_material_closure_incident_service.py",
    "tests/test_material_closure_public.py",
    "tests/test_autonomy_v2_supervisor_material_closure.py",
    "tests/test_material_identity_split_contracts.py",
    "tests/test_material_identity_split_schemas.py",
    "tests/test_material_identity_split_service.py",
    "tests/test_material_identity_split_transaction.py",
    "tests/test_material_identity_split_public.py",
    "tests/test_aq_approval_envelope.py",
    "tests/test_aq_approval_envelope_schemas.py",
    "tests/test_aq_approval_kpi.py",
    "tests/test_aq_approval_public_surface.py",
    "tests/test_no_job_specific_framework_literals.py",
    "tests/test_autonomous_quality_benchmarks_v02.py",
    "tests/test_repository_catalog.py",
    "tests/test_repository_summary_generator.py",
    "tests/test_ci_workflows.py"
)
Invoke-Uv run python scripts/check_no_job_specific_framework_literals.py
Invoke-Uv run pytest -q --basetemp (Join-Path $PytestRoot "f") @FocusedTests
Invoke-Uv run ruff check .
Invoke-Uv run cbm doctor

if (-not $SkipFullRegression) {
    Invoke-Uv run pytest --basetemp (Join-Path $PytestRoot "a")
}

$BenchmarkArguments = @(
    "run", "python", "-m", "codex_blender_modeler.autonomy_benchmarks",
    "--manifest", "examples/autonomous_quality_benchmarks/manifest.json",
    "--output", $BenchmarkReport
)
$BenchmarkV02Arguments = @(
    "run", "python", "-m", "codex_blender_modeler.autonomy_benchmarks.v02_cli",
    "--manifest", "examples/autonomous_quality_benchmarks_v02/manifest.json",
    "--output", $BenchmarkV02Report
)

if ($RunBlender) {
    $PreviousGeometrySmoke = $env:CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE
    $PreviousAutonomySmoke = $env:CBM_RUN_AUTONOMY_E2E_SMOKE
    $PreviousQualitySmoke = $env:CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE
    $PreviousPortableLongPathSmoke = $env:CBM_RUN_PORTABLE_LONG_PATH_BLENDER_SMOKE
    $PreviousAQV02GeometrySmoke = $env:CBM_RUN_AQ_V02_GEOMETRY_SMOKE
    $PreviousAQV02DeliveryGeometrySmoke = $env:CBM_RUN_AQ_V02_DELIVERY_GEOMETRY_SMOKE
    $PreviousAQV02CandidateValidationSmoke = $env:CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE
    $PreviousGeometryIntentReachabilitySmoke = $env:CBM_RUN_GEOMETRY_INTENT_V02_REACHABILITY_SMOKE
    $PreviousMaterialGraphSmoke = $env:CBM_RUN_MATERIAL_GRAPH_BLENDER_SMOKE
    $PreviousAQV02BenchmarkSmoke = $env:CBM_RUN_AQ_V02_BENCHMARK_BLENDER_SMOKE
    $PreviousMaterialAuthoringSmoke = $env:CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE
    $PreviousCodexImageMaterialSmoke = `
        $env:CBM_RUN_CODEX_IMAGE_MATERIAL_BLENDER_SMOKE
    $PreviousCodexImageMaterialLoopSmoke = `
        $env:CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_BLENDER_SMOKE
    $PreviousCodexImageMaterialLoopDeliverySmoke = `
        $env:CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_DELIVERY_BLENDER_E2E
    $PreviousMaterialClosureSmoke = $env:CBM_RUN_MATERIAL_CLOSURE_BLENDER_SMOKE
    $PreviousMaterialIdentitySplitSmoke = `
        $env:CBM_RUN_MATERIAL_IDENTITY_SPLIT_BLENDER_SMOKE
    try {
        $env:CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE = "1"
        $env:CBM_RUN_AUTONOMY_E2E_SMOKE = "1"
        $env:CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE = "1"
        $env:CBM_RUN_PORTABLE_LONG_PATH_BLENDER_SMOKE = "1"
        $env:CBM_RUN_AQ_V02_GEOMETRY_SMOKE = "1"
        $env:CBM_RUN_AQ_V02_DELIVERY_GEOMETRY_SMOKE = "1"
        $env:CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE = "1"
        $env:CBM_RUN_GEOMETRY_INTENT_V02_REACHABILITY_SMOKE = "1"
        $env:CBM_RUN_MATERIAL_GRAPH_BLENDER_SMOKE = "1"
        $env:CBM_RUN_AQ_V02_BENCHMARK_BLENDER_SMOKE = "1"
        $env:CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE = "1"
        $env:CBM_RUN_CODEX_IMAGE_MATERIAL_BLENDER_SMOKE = "1"
        $env:CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_BLENDER_SMOKE = "1"
        $env:CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_DELIVERY_BLENDER_E2E = "1"
        $env:CBM_RUN_MATERIAL_CLOSURE_BLENDER_SMOKE = "1"
        $env:CBM_RUN_MATERIAL_IDENTITY_SPLIT_BLENDER_SMOKE = "1"
        Invoke-Uv run cbm blender-compat
        Invoke-Uv run pytest -q --basetemp (Join-Path $PytestRoot "b") `
            tests/test_autonomous_structural_geometry_blender.py `
            tests/test_autonomous_quality_blender_evidence.py::test_blender_scale_assembly_and_topology_evidence `
            tests/test_blender_companion_service.py::test_static_prop_authoring_companions_are_hash_bound_and_read_only `
            tests/test_v07_blender_scripts.py::test_blender_runtime_writes_portable_json_to_extended_path `
            tests/test_autonomy_candidate_blender.py::test_initial_candidate_build_qa_and_policy_promotion `
            tests/test_autonomy_candidate_blender.py::test_autonomous_static_prop_reaches_one_terminal_delivery `
            tests/test_autonomy_candidate_blender.py::test_autonomous_static_prop_publishes_review_only_bundle_without_package `
            tests/test_aq_v02_geometry_blender.py `
            tests/test_aq_v02_delivery_geometry_blender.py `
            tests/test_autonomy_v2_candidate_validation_blender.py `
            tests/test_geometry_intent_v02_reachability.py `
            tests/test_material_graph_runtime.py::test_material_graph_compiles_reopens_and_inventories_in_blender_5 `
            tests/test_autonomous_quality_benchmarks_v02.py::test_v02_fixed_blender_probe_smoke `
            tests/test_material_authoring_blender_v02.py::test_fixed_material_families_compile_reopen_and_render_in_blender_5 `
            tests/test_codex_image_material_authoring_v021.py::test_fake_core_adoption_compiles_in_blender_5 `
            tests/test_codex_image_material_loop_blender.py `
            tests/test_codex_image_material_loop_delivery_blender.py `
            tests/test_material_closure_service.py::test_complete_preflight_runs_actual_blender_5_and_stops_before_approval `
            tests/test_material_identity_split_service.py::test_identity_split_runs_actual_blender_5_and_stops_before_scope_approval
        $BenchmarkArguments += "--run-blender"
        $BenchmarkV02Arguments += "--run-blender"
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
        if ($null -eq $PreviousAQV02GeometrySmoke) {
            Remove-Item Env:CBM_RUN_AQ_V02_GEOMETRY_SMOKE -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_AQ_V02_GEOMETRY_SMOKE = $PreviousAQV02GeometrySmoke
        }
        if ($null -eq $PreviousAQV02DeliveryGeometrySmoke) {
            Remove-Item Env:CBM_RUN_AQ_V02_DELIVERY_GEOMETRY_SMOKE `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_AQ_V02_DELIVERY_GEOMETRY_SMOKE = `
                $PreviousAQV02DeliveryGeometrySmoke
        }
        if ($null -eq $PreviousAQV02CandidateValidationSmoke) {
            Remove-Item Env:CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE = `
                $PreviousAQV02CandidateValidationSmoke
        }
        if ($null -eq $PreviousGeometryIntentReachabilitySmoke) {
            Remove-Item Env:CBM_RUN_GEOMETRY_INTENT_V02_REACHABILITY_SMOKE `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_GEOMETRY_INTENT_V02_REACHABILITY_SMOKE = `
                $PreviousGeometryIntentReachabilitySmoke
        }
        if ($null -eq $PreviousMaterialGraphSmoke) {
            Remove-Item Env:CBM_RUN_MATERIAL_GRAPH_BLENDER_SMOKE -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_MATERIAL_GRAPH_BLENDER_SMOKE = $PreviousMaterialGraphSmoke
        }
        if ($null -eq $PreviousAQV02BenchmarkSmoke) {
            Remove-Item Env:CBM_RUN_AQ_V02_BENCHMARK_BLENDER_SMOKE `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_AQ_V02_BENCHMARK_BLENDER_SMOKE = $PreviousAQV02BenchmarkSmoke
        }
        if ($null -eq $PreviousMaterialAuthoringSmoke) {
            Remove-Item Env:CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE = $PreviousMaterialAuthoringSmoke
        }
        if ($null -eq $PreviousCodexImageMaterialSmoke) {
            Remove-Item Env:CBM_RUN_CODEX_IMAGE_MATERIAL_BLENDER_SMOKE `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_CODEX_IMAGE_MATERIAL_BLENDER_SMOKE = `
                $PreviousCodexImageMaterialSmoke
        }
        if ($null -eq $PreviousCodexImageMaterialLoopSmoke) {
            Remove-Item Env:CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_BLENDER_SMOKE `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_BLENDER_SMOKE = `
                $PreviousCodexImageMaterialLoopSmoke
        }
        if ($null -eq $PreviousCodexImageMaterialLoopDeliverySmoke) {
            Remove-Item Env:CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_DELIVERY_BLENDER_E2E `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_DELIVERY_BLENDER_E2E = `
                $PreviousCodexImageMaterialLoopDeliverySmoke
        }
        if ($null -eq $PreviousMaterialClosureSmoke) {
            Remove-Item Env:CBM_RUN_MATERIAL_CLOSURE_BLENDER_SMOKE `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_MATERIAL_CLOSURE_BLENDER_SMOKE = `
                $PreviousMaterialClosureSmoke
        }
        if ($null -eq $PreviousMaterialIdentitySplitSmoke) {
            Remove-Item Env:CBM_RUN_MATERIAL_IDENTITY_SPLIT_BLENDER_SMOKE `
                -ErrorAction SilentlyContinue
        }
        else {
            $env:CBM_RUN_MATERIAL_IDENTITY_SPLIT_BLENDER_SMOKE = `
                $PreviousMaterialIdentitySplitSmoke
        }
    }

    if (-not $SkipLegacyGates) {
        Invoke-LegacyRegressionGates
    }
}

Invoke-Uv @BenchmarkArguments
Invoke-Uv @BenchmarkV02Arguments
Invoke-Native -Command "git" -Arguments @("diff", "--check")

Write-Host "AQ 0.1 gates and AQ 0.2 host/smoke checks completed; v2 remains disabled_experimental: $OutputRoot" `
    -ForegroundColor Green
