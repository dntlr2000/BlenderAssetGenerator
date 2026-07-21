#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_VISION=0
SKIP_V08=0
SKIP_V07=0
SKIP_COMPATIBILITY=0
SKIP_TEXTURE_BAKE=0
for arg in "$@"; do
  case "$arg" in
    --skip-vision) SKIP_VISION=1 ;;
    --skip-v08) SKIP_V08=1 ;;
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

if [[ "$SKIP_COMPATIBILITY" -eq 0 ]]; then
  uv run cbm blender-compat
fi

if [[ "$SKIP_V08" -eq 0 ]]; then
  V08_ARGS=()
  [[ "$SKIP_V07" -eq 1 ]] && V08_ARGS+=(--skip-v07)
  [[ "$SKIP_VISION" -eq 1 ]] && V08_ARGS+=(--skip-vision)
  [[ "$SKIP_COMPATIBILITY" -eq 1 ]] && V08_ARGS+=(--skip-compatibility)
  [[ "$SKIP_TEXTURE_BAKE" -eq 1 ]] && V08_ARGS+=(--skip-texture-bake)
  ./scripts/run_v08_gates.sh "${V08_ARGS[@]}"
fi

PREVIOUS_WORKSPACE="${CBM_WORKSPACE_ROOT-}"
RUN_STAMP="$(date -u +%Y%m%dT%H%M%S)-$$"
RUN_ID_SAFE="$(printf '%s' "$RUN_STAMP" | tr '[:upper:]' '[:lower:]')"
SMOKE_ROOT="$PWD/reports/v09_smoke/$RUN_STAMP"
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
  --request "Create a bounded V0.9 proxy smoke workflow." \
  --job-id v09_queue_smoke --reference-path "$REFERENCE"
LATEST_PATH="$SMOKE_WORKSPACE/v09_queue_smoke/workflows/latest.json"
WORKFLOW_ID="$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["workflow_id"])' "$LATEST_PATH")"
uv run cbm queue-enqueue v09_queue_smoke "$WORKFLOW_ID" \
  --priority 80 --max-attempts 2
uv run cbm queue-run --max-entries 1 --max-host-steps 1
QUEUE_PATH="$SMOKE_WORKSPACE/.cbm/queue/local_queue.json"
uv run python -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); e=p["entries"]; assert p["max_concurrency"] == 1 and len(e) == 1 and e[0]["status"] == "waiting" and e[0]["last_workflow_status"] == "waiting_for_agent"' "$QUEUE_PATH"
RECEIPT_ROOT="$SMOKE_WORKSPACE/.cbm/queue/receipts/$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["entries"][0]["entry_id"])' "$QUEUE_PATH")"
[[ "$(find "$RECEIPT_ROOT" -maxdepth 1 -name '*.json' | wc -l)" -eq 1 ]]

AUDIT_ID="audit-$RUN_ID_SAFE"
uv run cbm workspace-audit --job-id v09_queue_smoke --audit-id "$AUDIT_ID"
AUDIT_PATH="$PWD/reports/v09/audits/$AUDIT_ID/workspace_audit.json"
uv run python -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); assert p["status"] == "passed" and p["scanned_job_count"] == 1; assert sys.argv[2] not in open(sys.argv[1], encoding="utf-8").read()' "$AUDIT_PATH" "$SMOKE_WORKSPACE"

PROBE_ID="probe-$RUN_ID_SAFE"
uv run cbm stability-probe --probe-id "$PROBE_ID"
PROBE_PATH="$PWD/reports/v09/environment/$PROBE_ID/environment_probe.json"
uv run python -c 'import sys; t=open(sys.argv[1], encoding="utf-8").read(); assert sys.argv[2] not in t and sys.argv[3] not in t' "$PROBE_PATH" "$PWD" "$SMOKE_WORKSPACE"

REPORT_ID="stability-$RUN_ID_SAFE"
uv run cbm stability-report-pdf --probe-id "$PROBE_ID" \
  --audit-id "$AUDIT_ID" --report-id "$REPORT_ID"
PDF_ROOT="$PWD/output/pdf/v09/$REPORT_ID"
[[ -f "$PDF_ROOT/stability_report.pdf" ]]
[[ -f "$PDF_ROOT/stability_report.manifest.json" ]]

echo "V0.9 isolated stabilization gates completed: $SMOKE_ROOT"
