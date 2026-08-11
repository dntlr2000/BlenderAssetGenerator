#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

RUN_BLENDER=0
SKIP_FULL_REGRESSION=0
SKIP_LEGACY_GATES=0
SKIP_VISION=0
SKIP_TEXTURE_BAKE=0
OUTPUT_ROOT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-blender) RUN_BLENDER=1; shift ;;
    --skip-full-regression) SKIP_FULL_REGRESSION=1; shift ;;
    --skip-legacy-gates) SKIP_LEGACY_GATES=1; shift ;;
    --skip-vision) SKIP_VISION=1; shift ;;
    --skip-texture-bake) SKIP_TEXTURE_BAKE=1; shift ;;
    --output-root)
      [[ $# -ge 2 ]] || { echo "--output-root requires a path" >&2; exit 2; }
      OUTPUT_ROOT="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$OUTPUT_ROOT" ]]; then
  # Keep the default short for deeply nested Blender/package evidence.
  OUTPUT_ROOT="${TMPDIR:-/tmp}/aqg-$$"
fi
mkdir -p "$OUTPUT_ROOT"
# Keep pytest fixtures outside the repository and independent of a long report path.
PYTEST_ROOT="${TMPDIR:-/tmp}/aqp-$$"
mkdir -p "$PYTEST_ROOT"
BENCHMARK_REPORT="$OUTPUT_ROOT/autonomous_quality_benchmark.json"
BENCHMARK_V02_REPORT="$OUTPUT_ROOT/autonomous_quality_benchmark_v02.json"

if [[ "$SKIP_VISION" -eq 1 ]]; then
  uv sync --frozen --extra dev
else
  uv sync --frozen --extra dev --extra vision
fi

FOCUSED_TESTS=(
  tests/test_autonomous_quality_benchmarks.py
  tests/test_autonomous_quality_schemas.py
  tests/test_autonomous_quality_public_surface.py
  tests/test_aq_evidence_envelopes.py
  tests/test_autonomous_quality_blender_evidence.py
  tests/test_autonomous_structural_geometry.py
  tests/test_scene_spec_v03_migration_public.py
  tests/test_reference_evidence_aq.py
  tests/test_integrated_quality_aq.py
  tests/test_integrated_quality_hard_gate_evidence.py
  tests/test_material_graph_aq.py
  tests/test_assembly_topology_aq.py
  tests/test_blender_companion_service.py
  tests/test_autonomy_aq.py
  tests/test_autonomy_authorization_hardening.py
  tests/test_autonomy_candidate_quality_aq.py
  tests/test_autonomy_candidate_scope.py
  tests/test_autonomy_structural_candidate_reachability.py
  tests/test_autonomy_failure_recovery_aq.py
  tests/test_autonomy_material_rounds_aq.py
  tests/test_autonomy_production_budget_aq.py
  tests/test_autonomy_review_bundle_aq.py
  tests/test_autonomy_terminal_verifier_aq.py
  tests/test_autonomy_worker.py
  tests/test_packaging_long_paths_aq.py
  tests/test_aq_v02_geometry.py
  tests/test_aq_v02_delivery_geometry_blender.py
  tests/test_aq_v02_schema_registry.py
  tests/test_autonomy_v2_contracts.py
  tests/test_autonomy_v2_planner.py
  tests/test_autonomy_v2_controller_bridge.py
  tests/test_autonomy_v2_candidate_validation.py
  tests/test_autonomy_v2_candidate_validation_blender.py
  tests/test_autonomy_v2_delivery_executor.py
  tests/test_autonomy_v2_delivery_service.py
  tests/test_autonomy_v2_material_phase.py
  tests/test_autonomy_v2_quality_binding.py
  tests/test_autonomy_v2_quality_terminal.py
  tests/test_autonomy_v2_supervisor_delivery.py
  tests/test_autonomy_v2_supervisor_public.py
  tests/test_controller_executor_v02.py
  tests/test_geometry_intent_v02_reachability.py
  tests/test_integrated_quality_v02_metrics.py
  tests/test_integrated_quality_v02_ranking.py
  tests/test_integrated_quality_v02_service.py
  tests/test_integrated_quality_v02_schemas.py
  tests/test_material_graph_runtime.py
  tests/test_material_authoring_v02.py
  tests/test_material_authoring_schemas_v02.py
  tests/test_material_authoring_blender_v02.py
  tests/test_advanced_material_handoff_v02.py
  tests/test_autonomous_quality_benchmarks_v02.py
  tests/test_repository_catalog.py
  tests/test_repository_summary_generator.py
  tests/test_ci_workflows.py
)
uv run pytest -q --basetemp "$PYTEST_ROOT/f" "${FOCUSED_TESTS[@]}"
uv run ruff check .
uv run cbm doctor

if [[ "$SKIP_FULL_REGRESSION" -eq 0 ]]; then
  uv run pytest --basetemp "$PYTEST_ROOT/a"
fi

BENCHMARK_ARGS=(
  run python -m codex_blender_modeler.autonomy_benchmarks
  --manifest examples/autonomous_quality_benchmarks/manifest.json
  --output "$BENCHMARK_REPORT"
)
BENCHMARK_V02_ARGS=(
  run python -m codex_blender_modeler.autonomy_benchmarks.v02_cli
  --manifest examples/autonomous_quality_benchmarks_v02/manifest.json
  --output "$BENCHMARK_V02_REPORT"
)

if [[ "$RUN_BLENDER" -eq 1 ]]; then
  uv run cbm blender-compat
  CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE=1 \
  CBM_RUN_AUTONOMY_E2E_SMOKE=1 \
  CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE=1 \
  CBM_RUN_PORTABLE_LONG_PATH_BLENDER_SMOKE=1 \
  CBM_RUN_AQ_V02_GEOMETRY_SMOKE=1 \
  CBM_RUN_AQ_V02_DELIVERY_GEOMETRY_SMOKE=1 \
  CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE=1 \
  CBM_RUN_AQ_V02_DELIVERY_EXECUTOR_BLENDER_E2E=1 \
  CBM_RUN_GEOMETRY_INTENT_V02_REACHABILITY_SMOKE=1 \
  CBM_RUN_MATERIAL_GRAPH_BLENDER_SMOKE=1 \
  CBM_RUN_AQ_V02_BENCHMARK_BLENDER_SMOKE=1 \
  CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE=1 \
    uv run pytest -q --basetemp "$PYTEST_ROOT/b" \
      tests/test_autonomous_structural_geometry_blender.py \
      tests/test_autonomous_quality_blender_evidence.py::test_blender_scale_assembly_and_topology_evidence \
      tests/test_blender_companion_service.py::test_static_prop_authoring_companions_are_hash_bound_and_read_only \
      tests/test_v07_blender_scripts.py::test_blender_runtime_writes_portable_json_to_extended_path \
      tests/test_autonomy_candidate_blender.py::test_initial_candidate_build_qa_and_policy_promotion \
      tests/test_autonomy_candidate_blender.py::test_autonomous_static_prop_reaches_one_terminal_delivery \
      tests/test_autonomy_candidate_blender.py::test_autonomous_static_prop_publishes_review_only_bundle_without_package \
      tests/test_aq_v02_geometry_blender.py \
      tests/test_aq_v02_delivery_geometry_blender.py \
      tests/test_autonomy_v2_candidate_validation_blender.py \
      tests/test_aq_v02_delivery_executor_blender.py \
      tests/test_geometry_intent_v02_reachability.py \
      tests/test_material_graph_runtime.py::test_material_graph_compiles_reopens_and_inventories_in_blender_5 \
      tests/test_autonomous_quality_benchmarks_v02.py::test_v02_fixed_blender_probe_smoke \
      tests/test_material_authoring_blender_v02.py::test_fixed_material_families_compile_reopen_and_render_in_blender_5
  BENCHMARK_ARGS+=(--run-blender)
  BENCHMARK_V02_ARGS+=(--run-blender)

  if [[ "$SKIP_LEGACY_GATES" -eq 0 ]]; then
    LEGACY_ARGS=()
    [[ "$SKIP_VISION" -eq 1 ]] && LEGACY_ARGS+=(--skip-vision)
    [[ "$SKIP_TEXTURE_BAKE" -eq 1 ]] && LEGACY_ARGS+=(--skip-texture-bake)
    # The V0.9 gate transitively runs the existing V0.8 and V0.7 regression gates.
    ./scripts/run_v09_gates.sh "${LEGACY_ARGS[@]}"
  fi
fi

uv "${BENCHMARK_ARGS[@]}"
uv "${BENCHMARK_V02_ARGS[@]}"
git diff --check
printf 'AQ 0.1 gates and AQ 0.2 host/smoke checks completed; v2 remains disabled_experimental: %s\n' "$OUTPUT_ROOT"
