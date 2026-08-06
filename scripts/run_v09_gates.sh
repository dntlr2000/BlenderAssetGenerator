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

# Builds one real GLB package and validates a movable Codex handoff in isolation.
run_destination_handoff_gate() {
  local run_id="v09-handoff-smoke-run"
  local conversion_id="v09-handoff-smoke-materials"
  local package_id="v09-handoff-smoke-package"
  local handoff_id="v09-handoff-smoke"
  uv run cbm import-example geometry_showcase
  uv run cbm material-scaffold geometry_showcase
  uv run cbm generate-procedural-textures geometry_showcase mat.blue \
    --preset rock --resolution 64 --seed 909 --uv-set UVMap --overwrite
  uv run cbm validate-material-contracts geometry_showcase
  uv run cbm build geometry_showcase
  uv run cbm render geometry_showcase
  uv run cbm inspect geometry_showcase
  uv run cbm validate geometry_showcase
  uv run cbm asset-profile-init geometry_showcase \
    --profile portable_gltf --asset-kind static_environment
  uv run cbm asset-preflight geometry_showcase \
    --profile portable_gltf --run-id "$run_id"
  uv run cbm asset-plan geometry_showcase \
    --profile portable_gltf --run-id "$run_id"
  local review_plan="$SMOKE_WORKSPACE/geometry_showcase/optimization/runs/$run_id/review_plan.json"
  local review_hash
  review_hash="$(uv run python -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$review_plan")"
  uv run cbm asset-plan-approve geometry_showcase \
    --run-id "$run_id" --plan-sha256 "$review_hash" \
    --approval-note "Automated isolated V0.9 handoff integration approval."
  uv run cbm asset-optimize geometry_showcase \
    --profile portable_gltf --run-id "$run_id" \
    --approved-plan-sha256 "$review_hash"
  uv run cbm asset-material-convert geometry_showcase \
    --profile portable_gltf --run-id "$run_id" --conversion-id "$conversion_id" \
    --resolution 1024 --margin-px 16 --render-device auto
  uv run cbm asset-package geometry_showcase \
    --profile portable_gltf --run-id "$run_id" --package-id "$package_id" \
    --material-conversion-id "$conversion_id"
  uv run cbm asset-validate geometry_showcase \
    --profile portable_gltf --package-id "$package_id" --bounds-tolerance-m 0.0001

  local package_manifest="$SMOKE_WORKSPACE/geometry_showcase/exports/packages/portable_gltf/$package_id/package_manifest.json"
  local package_hash_before
  package_hash_before="$(uv run python -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$package_manifest")"
  uv run cbm handoff-plan geometry_showcase \
    --profile portable_gltf --package-id "$package_id" --handoff-id "$handoff_id"
  local handoff_plan="$SMOKE_WORKSPACE/geometry_showcase/handoffs/$handoff_id/handoff_plan.json"
  local handoff_plan_hash
  handoff_plan_hash="$(uv run python -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$handoff_plan")"
  uv run cbm handoff-generate geometry_showcase \
    --handoff-id "$handoff_id" --plan-sha256 "$handoff_plan_hash"
  uv run cbm handoff-validate geometry_showcase \
    --profile portable_gltf --package-id "$package_id" --handoff-id "$handoff_id"
  uv run cbm handoff-status geometry_showcase
  uv run cbm report-pdf geometry_showcase --scope export \
    --optimization-run-id "$run_id" --package-id "$package_id"

  local envelope="$SMOKE_WORKSPACE/geometry_showcase/exports/destination_handoffs/portable_gltf/$package_id/$handoff_id"
  local package_hash_after
  package_hash_after="$(uv run python -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$package_manifest")"
  # Known non-blocking round-trip limitations produce status=warning while ok remains true.
  uv run python -c 'import json,sys,pathlib; e=pathlib.Path(sys.argv[1]); v=json.load(open(e/"destination_handoff_validation.json", encoding="utf-8")); assert v["ok"] and v["status"] in {"passed","warning"}; assert (e/"codex_handoff/handoff_manifest.json").is_file(); assert (e/"codex_handoff/handoff_report.pdf").is_file(); assert (e/"codex_handoff/handoff_report.manifest.json").is_file(); assert sys.argv[2] == sys.argv[3]' "$envelope" "$package_hash_before" "$package_hash_after"
}

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

if [[ "$SKIP_COMPATIBILITY" -eq 0 && "$SKIP_V07" -eq 0 ]]; then
  CBM_RUN_EXTERNAL_INTAKE_SMOKE=1 uv run pytest -q \
    tests/test_external_static_asset_intake.py::test_blender_external_intake_splits_materials_and_strips_scripts
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

run_destination_handoff_gate

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

HANDOFF_AUDIT_ID="handoff-audit-$RUN_ID_SAFE"
uv run cbm workspace-audit --job-id geometry_showcase --audit-id "$HANDOFF_AUDIT_ID"
HANDOFF_AUDIT_PATH="$PWD/reports/v09/audits/$HANDOFF_AUDIT_ID/workspace_audit.json"
uv run python -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); assert p["status"] == "passed" and p["handoff_count"] == 1 and p["valid_handoff_count"] == 1' "$HANDOFF_AUDIT_PATH"

PROBE_ID="probe-$RUN_ID_SAFE"
uv run cbm stability-probe --probe-id "$PROBE_ID"
PROBE_PATH="$PWD/reports/v09/environment/$PROBE_ID/environment_probe.json"
uv run python -c 'import sys; t=open(sys.argv[1], encoding="utf-8").read(); assert sys.argv[2] not in t and sys.argv[3] not in t' "$PROBE_PATH" "$PWD" "$SMOKE_WORKSPACE"

REPORT_ID="stability-$RUN_ID_SAFE"
uv run cbm stability-report-pdf --probe-id "$PROBE_ID" \
  --audit-id "$HANDOFF_AUDIT_ID" --report-id "$REPORT_ID"
PDF_ROOT="$PWD/output/pdf/v09/$REPORT_ID"
[[ -f "$PDF_ROOT/stability_report.pdf" ]]
[[ -f "$PDF_ROOT/stability_report.manifest.json" ]]

echo "V0.9 isolated stabilization gates completed: $SMOKE_ROOT"
