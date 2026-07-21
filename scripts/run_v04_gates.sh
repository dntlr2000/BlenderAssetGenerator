#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_VISION=0
SKIP_EXPORTS=0
SKIP_MCP_CYCLES=0
for arg in "$@"; do
  case "$arg" in
    --skip-vision) SKIP_VISION=1 ;;
    --skip-exports) SKIP_EXPORTS=1 ;;
    --skip-mcp-cycles) SKIP_MCP_CYCLES=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$SKIP_VISION" -eq 1 ]]; then
  uv sync --frozen --extra dev
else
  uv sync --frozen --extra dev --extra vision
fi

uv run pytest
uv run ruff check .
uv run cbm doctor

if [[ "$SKIP_EXPORTS" -eq 1 ]]; then
  uv run cbm blender-compat --no-smoke-exports
else
  uv run cbm blender-compat
fi

ensure_example() {
  local name="$1"
  if [[ ! -f "workspaces/$name/job.json" ]]; then
    uv run cbm import-example "$name"
  fi
}

ensure_example geometry_showcase
uv run cbm build geometry_showcase
uv run cbm render geometry_showcase
uv run cbm inspect geometry_showcase
uv run cbm validate geometry_showcase
if [[ "$SKIP_EXPORTS" -eq 0 ]]; then
  uv run cbm export geometry_showcase --format glb
  uv run cbm export geometry_showcase --format obj
  uv run cbm export geometry_showcase --format fbx
fi

ensure_example measured_box
uv run cbm analyze-reference measured_box --projection ortho
uv run cbm build measured_box
uv run cbm render measured_box
uv run cbm inspect measured_box
uv run cbm validate measured_box
uv run cbm evaluate-constraints measured_box

ensure_example first_reference_test
uv run cbm analyze-reference first_reference_test
uv run cbm build first_reference_test
uv run cbm render first_reference_test
uv run cbm inspect first_reference_test
uv run cbm validate first_reference_test

uv run python scripts/verify_v04_regressions.py
if [[ "$SKIP_MCP_CYCLES" -eq 0 ]]; then
  uv run python scripts/run_v04_mcp_regressions.py --render-engine cycles --render-device gpu
fi

echo "V0.4 local gates completed."
