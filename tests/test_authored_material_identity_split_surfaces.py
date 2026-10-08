"""Projection parity for explicitly separate authored material authority domains."""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from codex_blender_modeler import authored_split_runtime as runtime
from codex_blender_modeler import cli, mcp_server
from codex_blender_modeler.material_identity_split import authored_models as models

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "plan_authored_material_identity_split",
    "run_authored_material_identity_split_preapproval",
    "get_authored_material_identity_split_status",
    "get_authored_material_identity_split_approval_request",
    "approve_authored_material_identity_split",
    "approve_authored_material_identity_split_technical",
    "apply_authored_material_identity_split",
    "recover_authored_material_identity_split",
}


def test_explicit_public_tools_are_registered_enabled_and_non_user_by_default():
    """No existing user-only tool is silently converted to delegated authority."""
    with (ROOT / ".codex/config.toml").open("rb") as stream:
        enabled = set(tomllib.load(stream)["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert TOOLS <= enabled
    for name in TOOLS:
        assert callable(getattr(mcp_server, name))
    assert (
        inspect.signature(mcp_server.plan_authored_material_identity_split)
        .parameters["delegation_path"]
        .default
        is None
    )
    assert (
        inspect.signature(cli.authored_material_identity_split_approve_command)
        .parameters["confirm_explicit_user_decision"]
        .default
        is False
    )
    assert (
        inspect.signature(cli.authored_material_identity_split_approve_technical_command)
        .parameters["confirm_explicit_technical_decision"]
        .default
        is False
    )
    assert (
        mcp_server.get_modeling_capabilities()["material_identity_split_schema_version"] == "0.1.0"
    )


@pytest.mark.parametrize(
    "class_name",
    [
        "AuthoredMaterialIdentitySplitPlanV02",
        "AuthoredMaterialIdentitySplitDelegationV02",
        "AuthoredMaterialIdentitySplitApprovalV02",
        "AuthoredMaterialIdentitySplitTechnicalApprovalV02",
        "AuthoredMaterialIdentitySplitApplyIntentV02",
        "AuthoredMaterialIdentitySplitTechnicalApplyIntentV02",
        "AuthoredMaterialIdentitySplitApprovalRequestV02",
        "AuthoredMaterialIdentitySplitTechnicalApprovalRequestV02",
        "AuthoredMaterialIdentitySplitConsumptionV02",
        "AuthoredMaterialIdentitySplitTechnicalConsumptionV02",
    ],
)
def test_generated_authored_contracts_match_models(class_name):
    """Committed schemas retain exact separate actor/profile fields and strict unknown rejection."""
    import re

    model = getattr(models, class_name)
    stem = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower().replace("_v02", "_v02")
    stem = stem.replace("authored_material_identity_split_", "material_identity_split_authored_", 1)
    # Pydantic class names end in V02; the machine filename uses the same single suffix.
    path = ROOT / "schemas" / f"{stem}.schema.json"
    assert json.loads(path.read_bytes()) == model.model_json_schema()
    assert model.model_json_schema()["additionalProperties"] is False


def test_stdlib_contract_modules_do_not_require_host_site_packages():
    """Blender's unprimed reader can import both authority domains and material closures."""
    script = (
        "import sys;sys.path.insert(0,sys.argv[1]);"
        "from codex_blender_modeler import authored_split_runtime,authored_material_runtime;"
        "print('stdlib-ok')"
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", script, str(ROOT / "src")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "stdlib-ok"


@pytest.mark.parametrize(
    "run_id",
    [
        "consumed",
        "delegation_scope_consumed",
        "delegation_origin_consumed",
        "../x",
        "x/y",
        "x\\y",
        "X",
        "",
    ],
)
def test_authored_run_namespace_cannot_alias_authority_history(run_id):
    """Run paths cannot shadow the shared one-use claims or escape containment."""
    with pytest.raises(ValueError):
        runtime.prefix(run_id)
