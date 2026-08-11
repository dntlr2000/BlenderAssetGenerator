"""Static validation for Python and Blender GitHub workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_workflow(name: str) -> dict[str, Any]:
    """Load workflow YAML with string-preserving BaseLoader semantics."""

    path = ROOT / ".github" / "workflows" / name
    payload = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(payload, dict)
    return payload


def _run_commands(payload: dict[str, Any]) -> str:
    """Collect every declared run command for stable policy assertions."""

    commands: list[str] = []
    for job in payload["jobs"].values():
        for step in job["steps"]:
            if "run" in step:
                commands.append(str(step["run"]))
    return "\n".join(commands)


def test_python_ci_runs_on_push_pr_and_dispatch_without_blender() -> None:
    """Keep portable Python CI comprehensive and free of Blender requirements."""

    workflow = _load_workflow("python-ci.yml")
    assert set(workflow["on"]) == {"pull_request", "push", "workflow_dispatch"}
    setup_python = next(
        step
        for step in workflow["jobs"]["python"]["steps"]
        if step.get("uses") == "actions/setup-python@v5"
    )
    assert setup_python["with"]["python-version"] == "3.11"
    commands = _run_commands(workflow)

    assert "uv sync --frozen --extra dev --extra vision" in commands
    assert "scripts/check_agent_instructions.py" in commands
    assert "scripts/generate_repository_summary.py --check" in commands
    assert "test_autonomous_quality_benchmarks.py" in commands
    assert "test_autonomous_quality_benchmarks_v02.py" in commands
    assert "codex_blender_modeler.autonomy_benchmarks.v02_cli" in commands
    assert "test_aq_v02_schema_registry.py" in commands
    assert "test_repository_catalog.py" in commands
    assert "test_controller_executor_v02.py" in commands
    assert "test_material_authoring_v02.py" in commands
    assert "uv run pytest" in commands
    assert "uv run ruff check ." in commands
    assert "blender-compat" not in commands


def test_blender_smoke_is_manual_and_self_hosted() -> None:
    """Require explicit dispatch and the Windows Blender 5 runner labels."""

    workflow = _load_workflow("blender-smoke.yml")
    assert set(workflow["on"]) == {"workflow_dispatch"}
    dispatch = workflow["on"]["workflow_dispatch"]
    execute = dispatch["inputs"]["execute_blender_smoke"]
    assert execute["default"] == "false"
    job = workflow["jobs"]["blender"]
    assert "execute_blender_smoke" in job["if"]
    assert set(job["runs-on"]) == {"self-hosted", "windows", "blender5"}
    commands = _run_commands(workflow)

    assert "uv run cbm blender-compat" in commands
    assert "run_autonomous_quality_gates.ps1" in commands
    assert "-RunBlender" in commands


def test_aq_v02_gate_scripts_wire_exact_opt_in_blender_nodes() -> None:
    """Keep every AQ v2 Blender smoke explicit and absent from portable Python CI."""

    powershell = (ROOT / "scripts" / "run_autonomous_quality_gates.ps1").read_text(
        encoding="utf-8"
    )
    bash = (ROOT / "scripts" / "run_autonomous_quality_gates.sh").read_text(
        encoding="utf-8"
    )
    python_commands = _run_commands(_load_workflow("python-ci.yml"))
    expected_env = {
        "CBM_RUN_AQ_V02_GEOMETRY_SMOKE",
        "CBM_RUN_MATERIAL_GRAPH_BLENDER_SMOKE",
        "CBM_RUN_AQ_V02_BENCHMARK_BLENDER_SMOKE",
        "CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE",
    }
    expected_nodes = {
        "tests/test_aq_v02_geometry_blender.py",
        "tests/test_material_graph_runtime.py::test_material_graph_compiles_reopens_and_inventories_in_blender_5",
        "tests/test_autonomous_quality_benchmarks_v02.py::test_v02_fixed_blender_probe_smoke",
        "tests/test_material_authoring_blender_v02.py::test_fixed_material_families_compile_reopen_and_render_in_blender_5",
    }
    for token in expected_env | expected_nodes:
        assert token in powershell
        assert token in bash
    for token in expected_env:
        assert token not in python_commands
    assert "codex_blender_modeler.autonomy_benchmarks.v02_cli" in powershell
    assert "codex_blender_modeler.autonomy_benchmarks.v02_cli" in bash
