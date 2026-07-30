#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_V04=0
SKIP_V06_MCP=0
V04_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --skip-v04) SKIP_V04=1 ;;
    --skip-v06-mcp) SKIP_V06_MCP=1 ;;
    --skip-vision|--skip-exports|--skip-mcp-cycles) V04_ARGS+=("$arg") ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$SKIP_V04" -eq 0 ]]; then
  ./scripts/run_v04_gates.sh "${V04_ARGS[@]}"
else
  uv run pytest
  uv run ruff check .
  uv run cbm doctor
fi

PREVIOUS_WORKSPACE="${CBM_WORKSPACE_ROOT-}"
SMOKE_WORKSPACE="$PWD/reports/v06_smoke/workspaces"
mkdir -p "$SMOKE_WORKSPACE"
export CBM_WORKSPACE_ROOT="$SMOKE_WORKSPACE"

if [[ ! -f "$SMOKE_WORKSPACE/geometry_showcase/job.json" ]]; then
  uv run cbm import-example geometry_showcase
fi
if [[ ! -f "$SMOKE_WORKSPACE/geometry_showcase/analysis/material_plan.json" ]]; then
  uv run cbm material-scaffold geometry_showcase
fi
uv run cbm generate-procedural-textures geometry_showcase mat.blue \
  --preset rock --resolution 128 --seed 606 --uv-set UVMap --overwrite
uv run cbm validate-material-contracts geometry_showcase
uv run cbm build geometry_showcase
uv run cbm render geometry_showcase
uv run cbm validate geometry_showcase
uv run cbm inspect-materials geometry_showcase
uv run cbm render-material-swatches geometry_showcase --size 256
uv run cbm bake-materials geometry_showcase --profile gltf_pbr \
  --resolution 128 --material-id mat.blue
uv run cbm analyze-reference geometry_showcase
uv run cbm visual-qa geometry_showcase
uv run cbm report-pdf geometry_showcase --scope material
uv run cbm report-pdf geometry_showcase --scope qa --qa-run-id latest
uv run cbm report-pdf geometry_showcase --scope full --qa-run-id latest
export CBM_V06_MATERIAL_JOB=geometry_showcase
export CBM_V06_QA_JOB=geometry_showcase
uv run python scripts/verify_v06_artifacts.py
uv run python scripts/run_advisory_target_smoke.py

if [[ "$SKIP_V06_MCP" -eq 0 ]]; then
  uv run python scripts/run_v06_mcp_regressions.py
  # Rebind the combined PDF to the exact latest QA run created by the MCP smoke.
  uv run cbm report-pdf geometry_showcase --scope full --qa-run-id latest
  uv run python scripts/verify_v06_artifacts.py
fi

if [[ -n "$PREVIOUS_WORKSPACE" ]]; then
  export CBM_WORKSPACE_ROOT="$PREVIOUS_WORKSPACE"
else
  unset CBM_WORKSPACE_ROOT
fi
unset CBM_V06_MATERIAL_JOB CBM_V06_QA_JOB

echo "V0.6 material, shader, and visual-QA gates completed."
