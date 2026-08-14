"""Static validation for Python and Blender GitHub workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CODEX_IMAGEGEN_HOST_TESTS = (
    "tests/test_codex_imagegen_core.py",
    "tests/test_codex_imagegen_security.py",
    "tests/test_codex_imagegen_schemas.py",
    "tests/test_autonomy_v2_codex_image_planner.py",
    "tests/test_autonomy_v2_codex_image_overlay.py",
    "tests/test_autonomy_v2_codex_image_phase_service.py",
    "tests/test_codex_image_material_authoring_v021.py",
    "tests/test_codex_imagegen_public_surface.py",
    "tests/test_codex_image_material_loop_contracts.py",
    "tests/test_codex_image_material_loop_normalization.py",
    "tests/test_codex_image_material_loop_selection.py",
    "tests/test_codex_image_material_loop_v05_adapter.py",
    "tests/test_codex_image_material_preview_service.py",
    "tests/test_codex_image_material_quality_service.py",
    "tests/test_codex_image_material_loop_service.py",
    "tests/test_codex_image_material_loop_public.py",
)
MATERIAL_CLOSURE_HOST_TESTS = (
    "tests/test_material_closure_contracts.py",
    "tests/test_material_closure_service.py",
    "tests/test_material_closure_aq_integration.py",
    "tests/test_material_closure_schemas.py",
    "tests/test_material_closure_controller_repair.py",
    "tests/test_material_closure_incident_service.py",
    "tests/test_material_closure_public.py",
    "tests/test_autonomy_v2_supervisor_material_closure.py",
    "tests/test_no_job_specific_framework_literals.py",
)
MATERIAL_IDENTITY_SPLIT_HOST_TESTS = (
    "tests/test_material_identity_split_contracts.py",
    "tests/test_material_identity_split_schemas.py",
    "tests/test_material_identity_split_service.py",
    "tests/test_material_identity_split_transaction.py",
    "tests/test_material_identity_split_public.py",
)


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
    assert "scripts/check_no_job_specific_framework_literals.py" in commands
    assert "test_autonomous_quality_benchmarks.py" in commands
    assert "test_autonomous_quality_benchmarks_v02.py" in commands
    assert "codex_blender_modeler.autonomy_benchmarks.v02_cli" in commands
    assert "test_aq_v02_schema_registry.py" in commands
    assert "test_repository_catalog.py" in commands
    assert "test_controller_executor_v02.py" in commands
    assert "test_material_authoring_v02.py" in commands
    for test_name in CODEX_IMAGEGEN_HOST_TESTS:
        assert test_name in commands
    for test_name in MATERIAL_CLOSURE_HOST_TESTS:
        assert test_name in commands
    for test_name in MATERIAL_IDENTITY_SPLIT_HOST_TESTS:
        assert test_name in commands
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
        "CBM_RUN_CODEX_IMAGE_MATERIAL_BLENDER_SMOKE",
        "CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_BLENDER_SMOKE",
        "CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_DELIVERY_BLENDER_E2E",
        "CBM_RUN_MATERIAL_CLOSURE_BLENDER_SMOKE",
        "CBM_RUN_MATERIAL_IDENTITY_SPLIT_BLENDER_SMOKE",
    }
    expected_nodes = {
        "tests/test_aq_v02_geometry_blender.py",
        "tests/test_material_graph_runtime.py::test_material_graph_compiles_reopens_and_inventories_in_blender_5",
        "tests/test_autonomous_quality_benchmarks_v02.py::test_v02_fixed_blender_probe_smoke",
        "tests/test_material_authoring_blender_v02.py::test_fixed_material_families_compile_reopen_and_render_in_blender_5",
        "tests/test_codex_image_material_authoring_v021.py::test_fake_core_adoption_compiles_in_blender_5",
        "tests/test_codex_image_material_loop_blender.py",
        "tests/test_codex_image_material_loop_delivery_blender.py",
        "tests/test_material_closure_service.py::test_complete_preflight_runs_actual_blender_5_and_stops_before_approval",
        "tests/test_material_identity_split_service.py::test_identity_split_runs_actual_blender_5_and_stops_before_scope_approval",
    }
    for token in expected_env | expected_nodes:
        assert token in powershell
        assert token in bash
    for test_name in CODEX_IMAGEGEN_HOST_TESTS:
        assert test_name in powershell
        assert test_name in bash
    for test_name in MATERIAL_CLOSURE_HOST_TESTS:
        assert test_name in powershell
        assert test_name in bash
    for test_name in MATERIAL_IDENTITY_SPLIT_HOST_TESTS:
        assert test_name in powershell
        assert test_name in bash
    assert "scripts/check_no_job_specific_framework_literals.py" in powershell
    assert "scripts/check_no_job_specific_framework_literals.py" in bash
    for token in expected_env:
        assert token not in python_commands
    assert "codex_blender_modeler.autonomy_benchmarks.v02_cli" in powershell
    assert "codex_blender_modeler.autonomy_benchmarks.v02_cli" in bash


def test_codex_imagegen_gate_uses_fake_blender_evidence_without_live_provider() -> None:
    """Keep CI deterministic and prevent fake smoke evidence from becoming an actual claim."""

    paths = (
        ROOT / "scripts" / "run_autonomous_quality_gates.ps1",
        ROOT / "scripts" / "run_autonomous_quality_gates.sh",
        ROOT / ".github" / "workflows" / "python-ci.yml",
        ROOT / ".github" / "workflows" / "blender-smoke.yml",
    )
    wiring = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    forbidden_live_tokens = {
        "OPENAI_API_KEY",
        "client.images.generate",
        "client.images.edit",
        "image_gen__imagegen",
        "$imagegen",
    }
    for token in forbidden_live_tokens:
        assert token not in wiring

    material_test = (
        ROOT / "tests" / "test_codex_image_material_authoring_v021.py"
    ).read_text(encoding="utf-8")
    assert "test_fake_core_adoption_compiles_in_blender_5" in material_test
    assert 'smoke["fake_completion_verified"] is True' in material_test
    assert (
        'smoke["actual_codex_imagegen_execution_verified"] is False'
        in material_test
    )
