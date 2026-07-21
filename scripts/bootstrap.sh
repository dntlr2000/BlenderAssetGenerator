#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it first, then re-run this script." >&2
  exit 1
fi

uv sync --extra dev --extra vision
mkdir -p workspaces
printf '%s\n' 'Setup complete. Run: uv run cbm doctor; uv run cbm blender-compat'
