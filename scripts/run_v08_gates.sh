#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_VISION=0
SKIP_V07=0
SKIP_COMPATIBILITY=0
SKIP_TEXTURE_BAKE=0
for arg in "$@"; do
  case "$arg" in
    --skip-vision) SKIP_VISION=1 ;;
    --skip-v07) SKIP_V07=1 ;;
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

if [[ "$SKIP_V07" -eq 0 ]]; then
  V07_ARGS=()
  [[ "$SKIP_VISION" -eq 1 ]] && V07_ARGS+=(--skip-vision)
  [[ "$SKIP_COMPATIBILITY" -eq 1 ]] && V07_ARGS+=(--skip-compatibility)
  [[ "$SKIP_TEXTURE_BAKE" -eq 1 ]] && V07_ARGS+=(--skip-texture-bake)
  ./scripts/run_v07_gates.sh "${V07_ARGS[@]}"
fi

PREVIOUS_WORKSPACE="${CBM_WORKSPACE_ROOT-}"
RUN_STAMP="$(date -u +%Y%m%dT%H%M%S)-$$"
SMOKE_ROOT="$PWD/reports/v08_smoke/$RUN_STAMP"
SMOKE_WORKSPACE="$SMOKE_ROOT/workspaces"
mkdir -p "$SMOKE_WORKSPACE"
export CBM_WORKSPACE_ROOT="$SMOKE_WORKSPACE"

# Restores the caller workspace while preserving isolated smoke evidence.
restore_workspace() {
  if [[ -n "$PREVIOUS_WORKSPACE" ]]; then
    export CBM_WORKSPACE_ROOT="$PREVIOUS_WORKSPACE"
  else
    unset CBM_WORKSPACE_ROOT
  fi
}
trap restore_workspace EXIT

REFERENCE="$PWD/examples/geometry_showcase/reference.png"
uv run cbm workflow-plan \
  --request "Create a 3D proxy model from this image." \
  --job-id v08_proxy_smoke --reference-path "$REFERENCE"
LATEST_PATH="$SMOKE_WORKSPACE/v08_proxy_smoke/workflows/latest.json"
WORKFLOW_ID="$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["workflow_id"])' "$LATEST_PATH")"
uv run cbm workflow-resume v08_proxy_smoke "$WORKFLOW_ID" --max-host-steps 1
uv run cbm workflow-status v08_proxy_smoke --workflow-id "$WORKFLOW_ID"
STATE_PATH="$SMOKE_WORKSPACE/v08_proxy_smoke/workflows/$WORKFLOW_ID/state.json"
uv run python -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); assert p["status"] == "waiting_for_agent" and p["current_step_id"] == "geometry.modeling_plan"' "$STATE_PATH"

uv run cbm workflow-plan \
  --request "Create a static exterior background preview." \
  --job-id v08_background_preview_smoke --reference-path "$REFERENCE" \
  --execution-policy background_exterior --delivery-scope preview_only
BACKGROUND_PREVIEW_LATEST="$SMOKE_WORKSPACE/v08_background_preview_smoke/workflows/latest.json"
BACKGROUND_PREVIEW_WORKFLOW_ID="$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["workflow_id"])' "$BACKGROUND_PREVIEW_LATEST")"
BACKGROUND_PREVIEW_PLAN="$SMOKE_WORKSPACE/v08_background_preview_smoke/workflows/$BACKGROUND_PREVIEW_WORKFLOW_ID/plan.json"
BACKGROUND_PREVIEW_REQUEST="$SMOKE_WORKSPACE/v08_background_preview_smoke/workflows/$BACKGROUND_PREVIEW_WORKFLOW_ID/request.json"
uv run python -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); r=json.load(open(sys.argv[2], encoding="utf-8")); q=[x for x in p["steps"] if x["step_id"]=="qa.run"]; t=next(x for x in p["steps"] if x["step_id"]==p["terminal_step_id"]); assert p["execution_policy"]=="background_exterior" and p["delivery_scope"]=="preview_only"; assert r["budgets"]["max_qa_iterations"]==1 and r["budgets"]["max_texture_resolution"]<=512 and r["budgets"]["external_provider_budget"]==0; assert len(q)==1 and q[0]["parameters"]["include_generated_target"] is False and q[0]["parameters"]["run_id"]; assert "background.eligibility" in {x["step_id"] for x in p["steps"]}; assert t["parameters"]["qa_run_id"]!="latest"; assert not [x for x in p["steps"] if "approval" in x["execution_mode"]]; assert not [x for x in p["steps"] if x["phase"]=="portable"]' "$BACKGROUND_PREVIEW_PLAN" "$BACKGROUND_PREVIEW_REQUEST"

uv run cbm workflow-plan \
  --request "Create a static exterior background FBX package." \
  --job-id v08_background_package_smoke --reference-path "$REFERENCE" \
  --execution-policy background_exterior --delivery-scope portable_package \
  --profile fbx_interchange --destination engine_neutral
BACKGROUND_PACKAGE_LATEST="$SMOKE_WORKSPACE/v08_background_package_smoke/workflows/latest.json"
BACKGROUND_PACKAGE_WORKFLOW_ID="$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["workflow_id"])' "$BACKGROUND_PACKAGE_LATEST")"
BACKGROUND_PACKAGE_PLAN="$SMOKE_WORKSPACE/v08_background_package_smoke/workflows/$BACKGROUND_PACKAGE_WORKFLOW_ID/plan.json"
uv run python -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); generic=[x for x in p["steps"] if x["execution_mode"]=="approval"]; specialized=[x for x in p["steps"] if x["execution_mode"]=="specialized_approval"]; ids={x["step_id"] for x in p["steps"]}; t=next(x for x in p["steps"] if x["step_id"]==p["terminal_step_id"]); assert p["execution_policy"]=="background_exterior" and p["delivery_scope"]=="portable_package"; assert not generic and len(specialized)==1 and specialized[0]["approval_gate"]=="optimization_plan"; assert "background.eligibility" in ids and "portable.final_approval" not in ids; assert t["parameters"]["qa_run_id"]!="latest" and t["parameters"]["optimization_run_id"]!="latest" and t["parameters"]["package_id"]!="latest"' "$BACKGROUND_PACKAGE_PLAN"

uv run cbm import-example geometry_showcase
uv run cbm workflow-plan \
  --request "Prepare an FBX package for Unity." \
  --job-id geometry_showcase --intent portable_package \
  --profile fbx_interchange --destination unity \
  --include-destination-handoff
PORTABLE_LATEST="$SMOKE_WORKSPACE/geometry_showcase/workflows/latest.json"
PORTABLE_WORKFLOW_ID="$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["workflow_id"])' "$PORTABLE_LATEST")"
PORTABLE_PLAN="$SMOKE_WORKSPACE/geometry_showcase/workflows/$PORTABLE_WORKFLOW_ID/plan.json"
uv run python -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); s={x["step_id"]:x for x in p["steps"]}; assert p["destination"]["status"] == "unsupported" and p["destination"]["terminal_boundary"] == "portable_package" and p["terminal_step_id"] == "destination.handoff"; assert s["destination.handoff"]["depends_on"] == ["portable.final_approval"]' "$PORTABLE_PLAN"

echo "V0.8 isolated orchestration gates completed: $SMOKE_ROOT"
