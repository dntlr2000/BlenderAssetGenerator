"""Additive request/schema/public forwarding parity for guarded solid-root intent revisions."""

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_paired_revision_public_surface import PAIR, _request
from typer.testing import CliRunner

from codex_blender_modeler import cli, mcp_server
from codex_blender_modeler.orchestration import attachment_revision, paired_models
from codex_blender_modeler.orchestration.models import WorkflowRequest

ROOT = Path(__file__).parents[1]
INTENT = {
    "attachment_intent_path": "analysis/candidates/intent.json",
    "attachment_intent_sha256": "c" * 64,
}


@pytest.mark.parametrize(
    "options",
    [
        {"attachment_intent_path": INTENT["attachment_intent_path"]},
        {"attachment_intent_sha256": INTENT["attachment_intent_sha256"]},
        INTENT,
        {**PAIR, **INTENT, "intent_hint": "auto"},
        {**PAIR, **INTENT, "revision_strategy": "candidate_review"},
        {**PAIR, **INTENT, "execution_policy": "background_exterior"},
        {**PAIR, **INTENT, "attachment_intent_sha256": "A" * 64},
        {**PAIR, **INTENT, "attachment_intent_path": "../escaped.json"},
    ],
)
def test_request_rejects_missing_pair_or_expanded_selection(options):
    """Only a complete exact explicit Standard paired selection admits the new companion."""
    with pytest.raises(ValueError):
        _request(**options)


def test_absent_fields_do_not_change_legacy_request_bytes():
    """Default-None selections remain absent rather than silently migrating historical requests."""
    original = _request(**PAIR)
    assert not (INTENT.keys() & original.model_dump(mode="json").keys())
    assert (
        original.model_dump_json()
        == original.model_copy(update={key: None for key in INTENT}).model_dump_json()
    )
    selected = _request(**PAIR, **INTENT)
    assert all(selected.model_dump(mode="json")[key] == value for key, value in INTENT.items())


@pytest.mark.parametrize("selected", [False, True])
def test_cli_and_mcp_forward_only_explicit_intent_arguments(monkeypatch, selected):
    """Both existing public planners expose the same optional names without changing old calls."""
    calls = []

    def capture(request, **kwargs):
        """Record forwarding without publishing requests or synthetic authority."""
        calls.append(kwargs)
        return SimpleNamespace(model_dump_json=lambda: "{}", model_dump=lambda **_: {})

    monkeypatch.setattr(cli, "plan_orchestrated_workflow", capture)
    monkeypatch.setattr(mcp_server, "plan_workflow_internal", capture)
    options = {**PAIR, **(INTENT if selected else {})}
    args = [
        "workflow-plan",
        "--request",
        "Exact candidate",
        "--job-id",
        "paired_asset",
        "--intent",
        "revise_asset",
        "--revision-strategy",
        "manual_guarded",
    ]
    for key, value in options.items():
        args.extend(["--" + key.replace("_", "-"), value])
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    mcp_server.plan_short_workflow(
        "Exact candidate",
        job_id="paired_asset",
        intent="revise_asset",
        revision_strategy="manual_guarded",
        **options,
    )
    for call in calls:
        assert {key: call[key] for key in INTENT if key in call} == (INTENT if selected else {})


@pytest.mark.parametrize(
    "filename,model",
    [
        ("attachment_revision_record_v01", attachment_revision.AttachmentRevisionRecordV01),
        ("attachment_revision_binding_v01", attachment_revision.AttachmentRevisionBindingV01),
        (
            "attachment_revision_transaction_intent_v02",
            paired_models.AttachmentTransactionIntentV02,
        ),
        ("attachment_revision_commit_receipt_v02", paired_models.AttachmentCommitReceiptV02),
        ("attachment_revision_rollback_receipt_v02", paired_models.AttachmentRollbackReceiptV02),
        ("workflow_request", WorkflowRequest),
    ],
)
def test_machine_contracts_match_authoritative_generated_schemas(filename, model):
    """New companions are additive schemas and never modify the legacy pair receipt schema."""
    assert (
        json.loads((ROOT / "schemas" / f"{filename}.schema.json").read_bytes())
        == model.model_json_schema()
    )
    for key in INTENT:
        assert inspect.signature(mcp_server.plan_short_workflow).parameters[key].default is None
