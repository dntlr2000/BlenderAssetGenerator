#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_VISION=0
SKIP_COMPATIBILITY=0
SKIP_TEXTURE_BAKE=0
for arg in "$@"; do
  case "$arg" in
    --skip-vision) SKIP_VISION=1 ;;
    --skip-compatibility) SKIP_COMPATIBILITY=1 ;;
    --skip-texture-bake) SKIP_TEXTURE_BAKE=1 ;;
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
if [[ "$SKIP_COMPATIBILITY" -eq 0 ]]; then
  uv run cbm blender-compat
fi

PREVIOUS_WORKSPACE="${CBM_WORKSPACE_ROOT-}"
RUN_STAMP="$(date -u +%Y%m%dT%H%M%S)-$$"
SMOKE_ROOT="$PWD/reports/v07_smoke/$RUN_STAMP"
SMOKE_WORKSPACE="$SMOKE_ROOT/workspaces"
mkdir -p "$SMOKE_WORKSPACE"
export CBM_WORKSPACE_ROOT="$SMOKE_WORKSPACE"

# Restores the caller workspace selection while leaving derived smoke evidence intact.
restore_workspace() {
  if [[ -n "$PREVIOUS_WORKSPACE" ]]; then
    export CBM_WORKSPACE_ROOT="$PREVIOUS_WORKSPACE"
  else
    unset CBM_WORKSPACE_ROOT
  fi
}
trap restore_workspace EXIT

# Runs one profile through cost-aware optimization, material conversion, package, and round trip.
run_portable_profile_gate() {
  local profile="$1"
  local run_id="$2"
  local conversion_id="$3"
  local package_id="$4"
  uv run cbm asset-profile-init geometry_showcase \
    --profile "$profile" --asset-kind static_environment
  uv run cbm asset-preflight geometry_showcase \
    --profile "$profile" --run-id "$run_id"
  uv run cbm asset-plan geometry_showcase \
    --profile "$profile" --run-id "$run_id"
  local plan_path="$SMOKE_WORKSPACE/geometry_showcase/optimization/runs/$run_id/review_plan.json"
  local plan_hash
  plan_hash="$(sha256sum "$plan_path" | awk '{print $1}')"
  uv run cbm asset-plan-approve geometry_showcase \
    --run-id "$run_id" --plan-sha256 "$plan_hash" \
    --approval-note "Automated isolated V0.7.4 integration fixture approval."
  uv run cbm asset-optimize geometry_showcase \
    --profile "$profile" --run-id "$run_id" --approved-plan-sha256 "$plan_hash"
  local cost_report="$SMOKE_WORKSPACE/geometry_showcase/optimization/runs/$run_id/asset_cost_report.json"
  if [[ ! -f "$cost_report" ]]; then
    echo "V0.7.4 static asset cost report is missing: $cost_report" >&2
    exit 1
  fi
  uv run python -c \
    'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); assert p["ok"] and p["canonical_unchanged"]' \
    "$cost_report"
  uv run cbm asset-material-convert geometry_showcase \
    --profile "$profile" --run-id "$run_id" --conversion-id "$conversion_id" \
    --resolution 1024 --margin-px 16 --render-device auto
  uv run cbm asset-package geometry_showcase \
    --profile "$profile" --run-id "$run_id" --package-id "$package_id" \
    --material-conversion-id "$conversion_id"
  uv run cbm asset-validate geometry_showcase \
    --profile "$profile" --package-id "$package_id" \
    --bounds-tolerance-m 0.0001
}

uv run cbm import-example geometry_showcase
uv run cbm material-scaffold geometry_showcase
uv run cbm generate-procedural-textures geometry_showcase mat.blue \
  --preset rock --resolution 128 --seed 707 --uv-set UVMap --overwrite
uv run cbm validate-material-contracts geometry_showcase
uv run cbm build geometry_showcase
uv run cbm render geometry_showcase
uv run cbm inspect geometry_showcase
uv run cbm validate geometry_showcase
if [[ "$SKIP_TEXTURE_BAKE" -eq 0 ]]; then
  uv run cbm bake-materials geometry_showcase --profile gltf_pbr \
    --resolution 128 --material-id mat.blue
fi

run_portable_profile_gate portable_gltf v07-gltf-smoke-run \
  v071-gltf-smoke-materials v07-gltf-smoke-package
run_portable_profile_gate fbx_interchange v07-fbx-smoke-run \
  v071-fbx-smoke-materials v07-fbx-smoke-package
run_portable_profile_gate obj_legacy v07-obj-smoke-run \
  v071-obj-smoke-materials v07-obj-smoke-package
uv run cbm asset-status geometry_showcase
uv run cbm report-pdf geometry_showcase --scope export \
  --optimization-run-id v07-gltf-smoke-run --package-id v07-gltf-smoke-package

PACKAGE_MANIFEST="$SMOKE_WORKSPACE/geometry_showcase/exports/packages/portable_gltf/v07-gltf-smoke-package/package_manifest.json"
ROUNDTRIP="$SMOKE_WORKSPACE/geometry_showcase/optimization/runs/v07-gltf-smoke-run/roundtrip/v07-gltf-smoke-package/roundtrip_validation.json"
MATERIAL_CONVERSION="$SMOKE_WORKSPACE/geometry_showcase/optimization/material_conversions/v07-gltf-smoke-run/v071-gltf-smoke-materials/conversion_manifest.json"
if [[ ! -f "$MATERIAL_CONVERSION" || ! -f "$PACKAGE_MANIFEST" || ! -f "$ROUNDTRIP" ]]; then
  echo "V0.7 material conversion, package, or round-trip evidence is missing from the isolated smoke workspace." >&2
  exit 1
fi

echo "V0.7.4 isolated portable static-asset gates completed: $SMOKE_ROOT"
