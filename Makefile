.PHONY: setup doctor compat test lint schemas example build render inspect validate export gates-v04 gates-v06

setup:
	uv sync --extra dev --extra vision

doctor:
	uv run cbm doctor

compat:
	uv run cbm blender-compat

test:
	uv run pytest

lint:
	uv run ruff check .

schemas:
	uv run python scripts/generate_schemas.py

example:
	uv run cbm import-example geometry_showcase

build:
	uv run cbm build geometry_showcase

render:
	uv run cbm render geometry_showcase

inspect:
	uv run cbm inspect geometry_showcase

validate:
	uv run cbm validate geometry_showcase

export:
	uv run cbm export geometry_showcase --format glb

gates-v04:
	powershell -ExecutionPolicy Bypass -File scripts/run_v04_gates.ps1

gates-v06:
	powershell -ExecutionPolicy Bypass -File scripts/run_v06_gates.ps1
