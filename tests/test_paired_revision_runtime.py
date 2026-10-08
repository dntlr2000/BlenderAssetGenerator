"""Blender's dependency-light reader retains the host paired transaction safety boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_paired_revision_transaction import _paired

from codex_blender_modeler import paired_revision_runtime as runtime
from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.orchestration import paired_revision as host
from codex_blender_modeler.orchestration import service

ROOT = Path(__file__).parents[1]


def _interrupted(tmp_path, monkeypatch, stage):
    """Create genuine synthetic host evidence interrupted at one deterministic checkpoint."""

    root, state, before = _paired(tmp_path, monkeypatch)

    def interrupt(name):
        """Stop only at the requested transaction checkpoint."""
        if name == stage:
            raise RuntimeError("synthetic runtime test interruption")

    monkeypatch.setattr(host, "_checkpoint", interrupt)
    service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    monkeypatch.setattr(host, "_checkpoint", lambda _name: None)
    return root, state, before


@pytest.mark.parametrize("stage", ["after_intent", "after_scene", "after_model", "before_receipt"])
def test_dependency_light_reader_rejects_each_pending_state(tmp_path, monkeypatch, stage):
    """Every uncommitted canonical state remains blocked without loading host packages."""

    root, _state, _before = _interrupted(tmp_path, monkeypatch, stage)
    with pytest.raises(ValueError, match="incomplete"):
        runtime.assert_no_pending_pair(root)


def test_dependency_light_reader_preserves_unfinalized_pair_and_history(tmp_path, monkeypatch):
    """Exact unfinalized bytes are readable; mixed bytes fail and completed history stays valid."""

    root, state, before = _interrupted(tmp_path, monkeypatch, "after_receipt")
    runtime.assert_no_pending_pair(root)
    candidate = (root / host.MODEL_PATH).read_bytes()
    (root / host.MODEL_PATH).write_bytes(before[host.MODEL_PATH])
    with pytest.raises(ValueError, match="canonical"):
        runtime.assert_no_pending_pair(root)
    (root / host.MODEL_PATH).write_bytes(candidate)
    intent = host.transaction_path(root, state.workflow_id, "intent.json")
    service.recover_paired_workflow_revision(
        root.name, state.workflow_id, intent_sha256=sha256_file(intent)
    )
    (root / host.MODEL_PATH).write_bytes(candidate + b" ")
    runtime.assert_no_pending_pair(root)
    host.assert_no_pending_pair(root)


def test_dependency_light_reader_retains_rollback_semantics(tmp_path, monkeypatch):
    """Exact archived rollback is readable and its single-use authority remains host-controlled."""

    root, state, _before = _interrupted(tmp_path, monkeypatch, "after_scene")
    intent = host.transaction_path(root, state.workflow_id, "intent.json")
    service.recover_paired_workflow_revision(
        root.name, state.workflow_id, intent_sha256=sha256_file(intent)
    )
    runtime.assert_no_pending_pair(root)
    with pytest.raises(FileExistsError):
        service.recover_paired_workflow_revision(
            root.name, state.workflow_id, intent_sha256=sha256_file(intent)
        )


@pytest.mark.parametrize(
    "tamper", ["receipt_bytes", "unknown_receipt_field", "host_input", "host_outputs"]
)
def test_dependency_light_reader_rejects_terminal_tampering(tmp_path, monkeypatch, tamper):
    """Schema, exact-byte and original-authority checks remain active in the Blender reader."""

    root, state, _before = _paired(tmp_path, monkeypatch)
    service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    receipt = host.transaction_path(root, state.workflow_id, "receipt.json")
    if tamper == "receipt_bytes":
        receipt.write_bytes(receipt.read_bytes() + b" ")
    elif tamper == "unknown_receipt_field":
        raw = json.loads(receipt.read_bytes())
        raw["untrusted_override"] = True
        receipt.write_text(json.dumps(raw))
    else:
        path = next(
            (root / "workflows" / state.workflow_id / "attempts/revision.apply").glob("*.json")
        )
        raw = json.loads(path.read_bytes())
        if tamper == "host_input":
            raw["input_fingerprint"] = "0" * 64
        else:
            raw["outputs"] = [
                item
                for item in raw["outputs"]
                if item["artifact_id"] == "revision.paired_transaction"
            ]
            from codex_blender_modeler.blender_artifacts import stable_json_digest

            raw["output_fingerprint"] = stable_json_digest(
                [
                    {key: item[key] for key in ("artifact_id", "path", "sha256", "integrity")}
                    for item in raw["outputs"]
                ]
            )
        path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        runtime.assert_no_pending_pair(root)


def test_runtime_rejects_external_refs_and_unknown_schema_operators():
    """Reader schemas can never fetch external content or silently ignore new validation rules."""

    with pytest.raises(ValueError, match="local"):
        runtime._schema_check({}, {"$ref": "https://example.invalid/untrusted"}, {})
    with pytest.raises(ValueError, match="unsupported"):
        runtime._schema_check({}, {"unevaluatedProperties": False}, {})


@pytest.mark.parametrize("field,value", [("completed_at", None), ("error_type", "unexpected")])
def test_runtime_preserves_host_success_semantics(tmp_path, monkeypatch, field, value):
    """A successful receipt still requires clean terminal evidence beyond JSON field types."""

    root, state, _before = _paired(tmp_path, monkeypatch)
    service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    path = next((root / "workflows" / state.workflow_id / "attempts/revision.apply").glob("*.json"))
    raw = json.loads(path.read_bytes())
    raw[field] = value
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="terminal"):
        runtime.assert_no_pending_pair(root)


def test_guard_and_provenance_import_without_site_packages(tmp_path, monkeypatch):
    """Exercise committed guard evidence and real provenance under Python without Pydantic."""

    root, state, _before = _paired(tmp_path, monkeypatch)
    service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    python = os.environ.get("CBM_TEST_BLENDER_PYTHON", sys.executable)
    program = """
import importlib.util, json, sys
from pathlib import Path
assert importlib.util.find_spec('pydantic') is None
from codex_blender_modeler.paired_revision_runtime import assert_no_pending_pair
from codex_blender_modeler.build_provenance import collect_build_provenance
root = Path(sys.argv[1])
assert_no_pending_pair(root)
value = collect_build_provenance(
    root, root.name, validate_contracts=False, material_plan_mode='scene_spec_only')
assert value['job_id'] == root.name
assert 'codex_blender_modeler.orchestration' not in sys.modules
assert 'pydantic' not in sys.modules
print(json.dumps({'ok':True,'python':sys.executable,'pydantic_loaded':False}))
"""
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [python, "-S", "-c", program, str(root)], env=environment, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"]
