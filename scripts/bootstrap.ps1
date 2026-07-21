$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw "uv is required. Install it first, then re-run this script."
}

uv sync --extra dev --extra vision
New-Item -ItemType Directory -Force -Path workspaces | Out-Null
Write-Host "Setup complete. Run: uv run cbm doctor; uv run cbm blender-compat"
