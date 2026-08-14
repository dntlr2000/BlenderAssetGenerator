"""Public CLI, MCP, allowlist, and capability parity for Material Closure 0.1.0."""

from __future__ import annotations

import hashlib
import inspect
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from codex_blender_modeler import cli, material_closure_public, mcp_server
from codex_blender_modeler.blender_artifacts import deterministic_json_bytes
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.material_closure.collector import (
    build_material_plan_absence_evidence,
)
from codex_blender_modeler.material_closure.models import (
    ExactArtifact,
    MaterialAttemptState,
    MaterialCanonicalSnapshot,
    MaterialRetrySupersessionReceipt,
    MaterialSessionSupersessionReceipt,
)
from codex_blender_modeler.material_closure.state_consistency import (
    build_material_canonical_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
CLI_COMMANDS = {
    "material-closure-plan",
    "material-closure-status",
    "material-preflight-run",
    "material-preflight-status",
    "material-graph-rebind",
    "material-state-consistency",
    "material-framework-failure-status",
    "material-retry-supersede",
    "material-repair-session-plan",
    "material-repair-session-run",
    "material-shadow-compile",
    "material-appearance-approve",
}
MCP_TOOLS = {
    "plan_material_closure",
    "get_material_closure_status",
    "run_material_preflight",
    "get_material_preflight_status",
    "rebind_material_graph",
    "get_material_state_consistency",
    "get_material_framework_failure_status",
    "supersede_material_retry",
    "plan_material_repair_session",
    "run_material_repair_session",
    "run_material_shadow_compile",
    "approve_material_appearance",
}


def test_material_closure_cli_and_mcp_surfaces_are_complete() -> None:
    """Expose exactly the requested additive commands while retaining distinct tool names."""

    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for command in CLI_COMMANDS:
        assert command in result.stdout
    for tool in MCP_TOOLS:
        assert callable(getattr(mcp_server, tool))


def test_material_closure_mcp_tools_are_project_enabled() -> None:
    """Keep every thin host facade inside the explicit project MCP allowlist."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        enabled = set(
            tomllib.load(handle)["mcp_servers"]["blender_modeler"]["enabled_tools"]
        )
    assert MCP_TOOLS <= enabled


def test_material_appearance_surface_requires_complete_caller_decision() -> None:
    """Require an approval file, exact UV expectation, and explicit observed-user flag."""

    cli_parameters = inspect.signature(cli.material_appearance_approve_command).parameters
    mcp_parameters = inspect.signature(mcp_server.approve_material_appearance).parameters
    required = {
        "job_id",
        "report_path",
        "approval_path",
        "expected_uv_layout_fingerprint",
    }
    assert required <= set(cli_parameters)
    assert required | {"explicit_user_decision_observed"} <= set(mcp_parameters)
    assert cli_parameters["confirm_explicit_user_decision"].default is False
    assert mcp_parameters["explicit_user_decision_observed"].default is inspect.Parameter.empty


def test_state_consistency_never_accepts_caller_observed_snapshot() -> None:
    """Force the host to build the observed canonical snapshot from current exact bytes."""

    for function in (
        cli.material_state_consistency_command,
        mcp_server.get_material_state_consistency,
    ):
        parameters = inspect.signature(function).parameters
        assert "observed_snapshot_path" not in parameters
        assert "expected_snapshot_path" in parameters


def test_material_closure_capability_is_additive_and_fail_closed() -> None:
    """Advertise the companion without claiming a new pipeline or canonical writer."""

    capabilities = mcp_server.get_modeling_capabilities()
    assert capabilities["material_closure_schema_version"] == "0.1.0"
    closure = capabilities["material_closure"]
    assert closure["status"] == "additive_pre_controller_companion"
    assert closure["canonical_writer"] == "existing_host_material_promotion_only"
    assert closure["repair_stop_boundary"] == "approval_pending"
    assert closure["automatic_migration"] is False
    assert closure["destination_writes"] is False


def test_shadow_surface_routes_through_complete_preflight() -> None:
    """Prevent the named shadow command from becoming a raw approval-bypass primitive."""

    source = inspect.getsource(mcp_server.run_material_shadow_compile)
    assert "run_material_shadow_compile_internal" in source
    assert "run_material_preflight" not in inspect.signature(
        mcp_server.run_material_shadow_compile
    ).parameters


def test_mutating_public_surfaces_delegate_to_immutable_publishers() -> None:
    """Keep stdout adapters backed by host publication instead of in-memory authority."""

    public_source = inspect.getsource(
        __import__(
            "codex_blender_modeler.material_closure_public",
            fromlist=["material_closure_public"],
        )
    )
    for publisher in (
        "publish_material_closure_model",
        "publish_material_repair_session_plan",
        "publish_material_retry_supersession",
        "publish_material_appearance_approval",
    ):
        assert publisher in public_source
    assert "execute_material_repair_session" in public_source


def test_state_consistency_uses_run_owned_host_observations() -> None:
    """Reject the preserved reports leaf as the authority for a repair observation."""

    source = inspect.getsource(
        __import__(
            "codex_blender_modeler.material_closure_public",
            fromlist=["material_closure_public"],
        ).get_material_state_consistency
    )
    assert "publish_current_material_canonical_observations" in source
    assert '"reports/build_provenance.json"' not in source


def test_state_consistency_reports_material_presence_transitions_append_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Observe absent/present transitions independently and preserve pre/post reports."""

    root = tmp_path / "job"
    root.mkdir()
    now = datetime(2026, 8, 14, tzinfo=UTC)

    def write(relative: str, content: bytes) -> Path:
        """Write one fixture input beneath the isolated job root."""

        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def bind(relative: str, artifact_id: str, kind: str) -> ExactArtifact:
        """Bind one fixture path to its current exact bytes."""

        content = root.joinpath(*relative.split("/")).read_bytes()
        return ExactArtifact(
            artifact_id=artifact_id,
            kind=kind,
            path=relative,
            sha256=hashlib.sha256(content).hexdigest(),
            byte_size=len(content),
            media_type="application/json",
        )

    scene_payload = {
        "schema_version": "0.2.0",
        "job_id": "fixture_job",
        "mode": "concept",
        "nominal_scene_size": [1.0, 1.0, 1.0],
        "sources": [],
        "materials": [],
        "objects": [],
        "camera": {
            "projection": "PERSP",
            "location": [2.0, -2.0, 2.0],
            "target": [0.0, 0.0, 0.0],
            "focal_length_mm": 50.0,
            "ortho_scale": 2.0,
            "resolution": [64, 64],
        },
    }
    write("analysis/scene_spec.json", deterministic_json_bytes(scene_payload))
    write("analysis/modeling_plan.json", b"{}\n")
    write("blender/scene.blend", b"fixture blend\n")
    write("production/state.json", b"{}\n")
    scene = bind("analysis/scene_spec.json", "scene", "scene_spec")
    modeling = bind("analysis/modeling_plan.json", "modeling", "modeling_plan")
    blend = bind("blender/scene.blend", "blend", "canonical_blend")
    state = bind("production/state.json", "state", "autonomy_v02_state")
    build_payload = collect_build_provenance(
        root,
        "fixture_job",
        validate_surface_details=False,
    )
    write("production/baseline/build.json", deterministic_json_bytes(build_payload))
    build = bind("production/baseline/build.json", "build", "build_provenance")
    absence_model = build_material_plan_absence_evidence(
        job_root=root,
        absence_id="baseline-absence",
        job_id="fixture_job",
        workflow_id="fixture-workflow",
        dispatch_id="fixture-dispatch",
        session_id="fixture-session",
        producer="tests",
        producer_version="0.1.0",
        created_at=now,
        observation_state=state,
        canonical_scene_spec=scene,
        canonical_blend=blend,
    )
    write(
        "production/baseline/material_plan_absence.json",
        deterministic_json_bytes(absence_model.model_dump(mode="json")),
    )
    absence = bind(
        "production/baseline/material_plan_absence.json",
        "baseline-absence",
        "material_plan_absence",
    )
    baseline = build_material_canonical_snapshot(
        job_root=root,
        snapshot_id="baseline-snapshot",
        job_id="fixture_job",
        workflow_id="fixture-workflow",
        dispatch_id="fixture-dispatch",
        session_id="fixture-session",
        producer="tests",
        producer_version="0.1.0",
        created_at=now,
        scene_spec=scene,
        modeling_plan=modeling,
        blend=blend,
        build_provenance=build,
        material_plan_absence=absence,
    )
    baseline_path = write(
        "production/baseline/snapshot.json",
        deterministic_json_bytes(baseline.model_dump(mode="json")),
    )
    attempt = MaterialAttemptState(
        attempt_id="attempt-absent",
        sequence=0,
        state="preflighting",
        canonical_snapshot=baseline,
        retry_required=False,
        retry_allowed=False,
        job_id="fixture_job",
        workflow_id="fixture-workflow",
        dispatch_id="fixture-dispatch",
        session_id="fixture-session",
        producer="tests",
        producer_version="0.1.0",
        created_at=now,
    )
    attempt_path = write(
        "production/attempt-absent.json",
        deterministic_json_bytes(attempt.model_dump(mode="json")),
    )
    monkeypatch.setattr(material_closure_public, "_job_root", lambda _job_id: root)

    decoy_blend = write("history/decoy.blend", b"fixture blend\n")
    decoy_payload = baseline.model_dump(mode="json")
    decoy_payload["blend"] = {
        **blend.model_dump(mode="json"),
        "artifact_id": "decoy-blend",
        "path": decoy_blend.relative_to(root).as_posix(),
    }
    decoy_snapshot_path = write(
        "production/baseline/decoy-snapshot.json",
        deterministic_json_bytes(decoy_payload),
    )
    decoy_attempt_payload = attempt.model_dump(mode="json")
    decoy_attempt_payload["canonical_snapshot"] = decoy_payload
    decoy_attempt_path = write(
        "production/decoy-attempt.json",
        deterministic_json_bytes(decoy_attempt_payload),
    )
    write("blender/scene.blend", b"mutated canonical blend\n")
    with pytest.raises(ValidationError, match="canonical Blend path and kind"):
        material_closure_public.get_material_state_consistency(
            "fixture_job",
            attempt_state_path=decoy_attempt_path.relative_to(root).as_posix(),
            top_level_state_path="production/state.json",
            expected_snapshot_path=decoy_snapshot_path.relative_to(root).as_posix(),
            report_id="reject-decoy-blend",
        )
    assert not (
        root
        / "production"
        / "material_closure"
        / "fixture-session"
        / "consistency"
        / "reject-decoy-blend"
    ).exists()
    write("blender/scene.blend", b"fixture blend\n")

    def fake_run_blender(
        _script_name: str,
        args: list[str],
        **_kwargs,
    ) -> None:
        """Emit one deterministic Blender 5 inventory for each observation leaf."""

        output = Path(args[args.index("--output") + 1])
        output.write_text(
            '{"job_id":"fixture_job","blender_version":"5.0.1","objects":[]}\n',
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.incident_service.run_blender",
        fake_run_blender,
    )
    common = {
        "job_id": "fixture_job",
        "attempt_state_path": attempt_path.relative_to(root).as_posix(),
        "top_level_state_path": "production/state.json",
        "expected_snapshot_path": baseline_path.relative_to(root).as_posix(),
    }
    absent_result = material_closure_public.get_material_state_consistency(
        **common,
        report_id="before-material",
    )
    assert absent_result["report"]["consistent"] is True
    before_observation = absent_result["observed_snapshot_artifact"]["path"]

    material_path = write(
        "analysis/material_plan.json",
        deterministic_json_bytes(
            {
                "schema_version": "0.5.0",
                "job_id": "fixture_job",
                "stage": "authored",
                "materials": [],
            }
        ),
    )
    present_result = material_closure_public.get_material_state_consistency(
        **common,
        report_id="after-material-present",
    )
    assert present_result["report"]["consistent"] is False
    assert {item["field"] for item in present_result["report"]["differences"]} >= {
        "material_plan",
        "material_plan_absence",
    }
    after_observation = present_result["observed_snapshot_artifact"]["path"]
    assert before_observation != after_observation
    assert root.joinpath(*before_observation.split("/")).is_file()
    assert root.joinpath(*after_observation.split("/")).is_file()

    present_snapshot = MaterialCanonicalSnapshot.model_validate_json(
        json.dumps(present_result["observed_snapshot"])
    )
    present_attempt = attempt.model_copy(
        update={
            "attempt_id": "attempt-present",
            "canonical_snapshot": present_snapshot,
        }
    )
    present_attempt_path = write(
        "production/attempt-present.json",
        deterministic_json_bytes(present_attempt.model_dump(mode="json")),
    )
    material_path.unlink()
    absent_again = material_closure_public.get_material_state_consistency(
        "fixture_job",
        attempt_state_path=present_attempt_path.relative_to(root).as_posix(),
        top_level_state_path="production/state.json",
        expected_snapshot_path=present_result["observed_snapshot_artifact"]["path"],
        report_id="after-material-absent",
    )
    assert absent_again["report"]["consistent"] is False
    assert {item["field"] for item in absent_again["report"]["differences"]} >= {
        "material_plan",
        "material_plan_absence",
    }


def test_status_preserves_same_timestamp_supersession_lists_and_ambiguity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """List distinct retry history and expose ambiguous repair targets without guessing."""

    root = tmp_path / "job"
    root.mkdir()
    now = datetime(2026, 8, 14, tzinfo=UTC)

    def artifact(relative: str, content: bytes, artifact_id: str, kind: str) -> ExactArtifact:
        """Write and bind one immutable status fixture dependency."""

        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return ExactArtifact(
            artifact_id=artifact_id,
            kind=kind,
            path=relative,
            sha256=hashlib.sha256(content).hexdigest(),
            byte_size=len(content),
            media_type="application/json",
        )

    state = artifact("production/state.json", b"{}\n", "state", "autonomy_v02_state")
    failure = artifact(
        "production/failure.json",
        b"{}\n",
        "failure",
        "material_framework_failure_report",
    )
    retry_entries: list[MaterialRetrySupersessionReceipt] = []
    for label in ("a", "b"):
        plan = artifact(
            f"production/retry-{label}.json",
            f'{{"retry":"{label}"}}\n'.encode(),
            f"retry-{label}",
            "retry_plan",
        )
        absence = artifact(
            f"production/absence-{label}.json",
            f'{{"absent":"{label}"}}\n'.encode(),
            f"absence-{label}",
            "material_retry_approval_absence",
        )
        receipt = MaterialRetrySupersessionReceipt(
            receipt_id=f"retry-receipt-{label}",
            retry_plan=plan,
            retry_approval_absence=absence,
            current_state=state,
            framework_failure_report=failure,
            supersession_reason="historical framework retry",
            job_id="fixture_job",
            workflow_id="fixture-workflow",
            dispatch_id="fixture-dispatch",
            session_id="fixture-session",
            producer="tests",
            producer_version="0.1.0",
            created_at=now,
        )
        retry_entries.append(receipt)
        path = root / "production" / "autonomy_v2" / "fixture-session" / (
            f"retry_supersessions/{receipt.receipt_id}/receipt.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(deterministic_json_bytes(receipt.model_dump(mode="json")))

    repair_plans = [
        artifact(
            f"production/repair-{label}.json",
            f'{{"repair":"{label}"}}\n'.encode(),
            f"repair-{label}",
            "material_repair_session_plan",
        )
        for label in ("a", "b")
    ]
    for label, repair in zip(("a", "b"), repair_plans, strict=True):
        receipt = MaterialSessionSupersessionReceipt(
            receipt_id=f"session-receipt-{label}",
            superseded_session_id="fixture-session",
            superseded_state=state,
            framework_failure_report=failure,
            repair_session_plan=repair,
            job_id="fixture_job",
            workflow_id="fixture-workflow",
            dispatch_id="fixture-dispatch",
            session_id=f"repair-session-{label}",
            producer="tests",
            producer_version="0.1.0",
            created_at=now,
        )
        path = root / "production" / "autonomy_v2" / "fixture-session" / (
            f"material_session_supersessions/{receipt.receipt_id}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(deterministic_json_bytes(receipt.model_dump(mode="json")))

    monkeypatch.setattr(material_closure_public, "_job_root", lambda _job_id: root)
    monkeypatch.setattr(
        material_closure_public,
        "get_autonomy_v2_material_closure_status",
        lambda *_args, **_kwargs: {"combined_status": "cancelled"},
    )
    result = material_closure_public.get_material_closure_status(
        "fixture_job",
        "fixture-session",
    )
    assert [item["receipt_id"] for item in result["retry_supersessions"]] == [
        "retry-receipt-a",
        "retry-receipt-b",
    ]
    assert len(result["session_supersessions"]) == 2
    assert result["session_supersession_ambiguities"][0]["policy"] == (
        "ambiguous_no_active_target_selected"
    )
    assert result["combined_status"] == "blocked"
    assert len(result["outbound_session_supersessions"]) == 2
    assert result["incoming_session_supersessions"] == []

    monkeypatch.setattr(
        material_closure_public,
        "get_autonomy_v2_material_closure_status",
        lambda *_args, **_kwargs: {"combined_status": "inconsistent"},
    )
    inconsistent = material_closure_public.get_material_closure_status(
        "fixture_job",
        "fixture-session",
    )
    assert inconsistent["combined_status"] == "inconsistent"

    conflicting = retry_entries[0].model_copy(
        update={
            "receipt_id": "retry-receipt-conflict",
            "retry_approval_absence": retry_entries[1].retry_approval_absence,
        }
    )
    conflict_path = root / "production" / "autonomy_v2" / "fixture-session" / (
        "retry_supersessions/retry-receipt-conflict/receipt.json"
    )
    conflict_path.parent.mkdir(parents=True, exist_ok=True)
    conflict_path.write_bytes(
        deterministic_json_bytes(conflicting.model_dump(mode="json"))
    )
    with pytest.raises(ValueError, match="same exact plan"):
        material_closure_public.get_material_closure_status(
            "fixture_job",
            "fixture-session",
        )


def test_status_treats_new_session_supersession_as_incoming_lineage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Expose incoming repair lineage without blocking or passing it as old-session state."""

    root = tmp_path / "job"
    root.mkdir()
    now = datetime(2026, 8, 14, tzinfo=UTC)

    def artifact(relative: str, artifact_id: str, kind: str) -> ExactArtifact:
        """Write and bind one exact incoming-lineage fixture artifact."""

        content = f'{{"artifact":"{artifact_id}"}}\n'.encode()
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return ExactArtifact(
            artifact_id=artifact_id,
            kind=kind,
            path=relative,
            sha256=hashlib.sha256(content).hexdigest(),
            byte_size=len(content),
            media_type="application/json",
        )

    state = artifact("production/old-state.json", "old-state", "autonomy_v02_state")
    failure = artifact(
        "production/failure.json",
        "failure",
        "material_framework_failure_report",
    )
    repair = artifact(
        "production/new-repair-plan.json",
        "repair-plan",
        "material_repair_session_plan",
    )
    receipt = MaterialSessionSupersessionReceipt(
        receipt_id="old-to-new",
        superseded_session_id="old-session",
        superseded_state=state,
        framework_failure_report=failure,
        repair_session_plan=repair,
        job_id="fixture_job",
        workflow_id="fixture-workflow",
        dispatch_id="fixture-dispatch",
        session_id="new-session",
        producer="tests",
        producer_version="0.1.0",
        created_at=now,
    )
    receipt_path = (
        root
        / "production"
        / "autonomy_v2"
        / "old-session"
        / "material_session_supersessions"
        / "old-to-new.json"
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(deterministic_json_bytes(receipt.model_dump(mode="json")))
    calls: list[dict[str, object]] = []

    def fake_status(*_args, **kwargs) -> dict[str, object]:
        """Capture whether incoming lineage is incorrectly sent to the old-state validator."""

        calls.append(kwargs)
        return {"combined_status": "running"}

    monkeypatch.setattr(material_closure_public, "_job_root", lambda _job_id: root)
    monkeypatch.setattr(
        material_closure_public,
        "get_autonomy_v2_material_closure_status",
        fake_status,
    )
    result = material_closure_public.get_material_closure_status(
        "fixture_job",
        "new-session",
    )
    assert calls[0]["session_supersession"] is None
    assert result["combined_status"] == "running"
    assert result["outbound_session_supersessions"] == []
    assert [
        item["receipt_id"] for item in result["incoming_session_supersessions"]
    ] == ["old-to-new"]


def test_status_fails_closed_on_malformed_canonical_supersession(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Surface malformed canonical receipt JSON while ignoring valid noncanonical copies."""

    root = tmp_path / "job"
    root.mkdir()
    noncanonical = (
        root
        / "production"
        / "material_repair"
        / "fixture-session"
        / "session_supersession"
        / "receipt.json"
    )
    noncanonical.parent.mkdir(parents=True, exist_ok=True)
    noncanonical.write_bytes(b'{"not":"a canonical receipt"}\n')
    monkeypatch.setattr(material_closure_public, "_job_root", lambda _job_id: root)
    monkeypatch.setattr(
        material_closure_public,
        "get_autonomy_v2_material_closure_status",
        lambda *_args, **_kwargs: {"combined_status": "running"},
    )
    ignored = material_closure_public.get_material_closure_status(
        "fixture_job",
        "fixture-session",
    )
    assert ignored["session_supersessions"] == []

    malformed = (
        root
        / "production"
        / "autonomy_v2"
        / "fixture-session"
        / "retry_supersessions"
        / "broken-receipt"
        / "receipt.json"
    )
    malformed.parent.mkdir(parents=True, exist_ok=True)
    malformed.write_bytes(b'{"broken":')
    with pytest.raises(ValueError, match="malformed canonical"):
        material_closure_public.get_material_closure_status(
            "fixture_job",
            "fixture-session",
        )
