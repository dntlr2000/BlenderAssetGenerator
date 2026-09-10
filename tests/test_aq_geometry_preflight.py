"""Read-only candidate preflight and exact controller submission; fixtures are not art evidence."""

from __future__ import annotations

import copy
import json
import os
import runpy
import tomllib
from pathlib import Path

import pytest
import test_autonomy_v2_candidate_validation_blender as geometry_fixture
from PIL import Image
from test_aq_candidate_budget_preflight import staged_candidate
from typer.testing import CliRunner

from codex_blender_modeler import mcp_server
from codex_blender_modeler.autonomy_v2 import approval_supervisor_service as supervisor
from codex_blender_modeler.autonomy_v2.approval_policy_service import (
    approval_artifact_for,
    plan_approval_envelope,
)
from codex_blender_modeler.autonomy_v2.controller_bridge import (
    _session_bundle,
)
from codex_blender_modeler.autonomy_v2.delivery_service import artifact_for_v2
from codex_blender_modeler.autonomy_v2.geometry_preflight_models import (
    GeometryAuthoringPreflightV01,
)
from codex_blender_modeler.autonomy_v2.geometry_preflight_service import (
    GEOMETRY_PREFLIGHT_KIND,
    preflight_aq_geometry_authoring,
    submit_preflighted_geometry_candidate_v2,
)
from codex_blender_modeler.autonomy_v2.planner import plan_autonomous_static_prop_v2
from codex_blender_modeler.blender_artifacts import native_io_path, sha256_file
from codex_blender_modeler.cli import app

ROOT = Path(__file__).resolve().parents[1]


def _tree_hashes(root: Path) -> dict[str, str]:
    """Hash every ordinary fixture file, including long controller-owned paths."""

    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in root.rglob("*")
        if os.path.isfile(native_io_path(path))
    }


@pytest.fixture
def authoring(tmp_path, monkeypatch):
    """Prepare three semantic parts at a real pre-controller boundary without a render."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), (48, 96, 144)).save(source)
    job = "geometry_preflight"
    planned = plan_autonomous_static_prop_v2(
        "Create only the fixture hull.",
        reference_path=source,
        target_subject="fixture hull",
        requested_delivery_profiles=["review_only"],
        job_id=job,
        allow_disabled_experimental=True,
    )
    session_id = planned["session_id"]
    root = tmp_path / "workspaces" / job
    plan_approval_envelope(
        job,
        session_id,
        approval_mode="autonomous",
        initial_user_request_sha256=planned["root_authorization"]["original_request_sha256"],
        explicit_autonomy_delegation_observed=True,
        allow_disabled_experimental=True,
    )
    primary = planned["root_authorization"]["primary_reference"]
    for name, value in (
        (
            "reference_analysis",
            geometry_fixture._reference_analysis(job, primary["path"], primary["sha256"]),
        ),
        ("camera_solution", geometry_fixture._camera_solution(job)),
        ("modeling_plan", geometry_fixture._modeling_plan(job, "baseline")),
    ):
        geometry_fixture._write_json(root / "analysis" / f"{name}.json", value)
    geometry_fixture._advance_reference(root, session_id)
    scene = geometry_fixture._scene_v03(job, primary["path"])
    modeling = geometry_fixture._modeling_plan(job, "candidate")
    for data in (scene, modeling):
        data["objects"] = [copy.deepcopy(data["objects"][0]) for _ in range(3)]
        for index, item in enumerate(data["objects"]):
            item["id"] = f"asset.part{index}"
            role = "primary" if index == 0 else "supporting"
            if data is scene:
                item["tags"] = [f"qa_role:{role}"]
            else:
                item["scope_role"] = role
    directory = root / "fidelity/preflight"
    geometry_fixture._write_json(directory / "modeling_plan.json", modeling)
    geometry_fixture._write_json(directory / "scene_spec_v03.json", scene)
    geometry_fixture._write_json(directory / "assignment.json", {"phase": "geometry_authoring"})
    return root, session_id, scene


def _preflight(authoring):
    """Read the declared staged pair through the production preflight service."""

    root, session_id, _scene = authoring
    return preflight_aq_geometry_authoring(
        root.name,
        session_id,
        modeling_plan_path="fidelity/preflight/modeling_plan.json",
        scene_spec_v03_path="fidelity/preflight/scene_spec_v03.json",
    )


def _request(authoring, report):
    """Submit an explicit report through the real host bridge using a waiting desktop controller."""

    root, session_id, _scene = authoring
    report_path = root / "fidelity/preflight/report.json"
    if not report_path.exists():
        geometry_fixture._write_json(report_path, report)
    assignment = artifact_for_v2(
        root,
        root / "fidelity/preflight/assignment.json",
        artifact_id="assignment",
        kind="assignment",
    )
    preflight = artifact_for_v2(
        root,
        report_path,
        artifact_id="preflight",
        kind=GEOMETRY_PREFLIGHT_KIND,
    )
    return submit_preflighted_geometry_candidate_v2(
        root.name,
        session_id,
        assignment=assignment,
        preflight=preflight,
    )


def test_preflight_is_read_only_and_projects_the_complete_candidate_cost(authoring):
    """Cover all parts and future controller/build costs without consuming them."""

    root, session_id, _scene = authoring
    before = _tree_hashes(root)
    report = _preflight(authoring)
    assert report.outcome == "passed" and report.candidate_object_count == 3
    assert report.required_blender_builds == 4
    assert report.budget_usage_after.controller_invocations == 1
    assert report.budget_usage_after.total_actions == 2
    assert report.budget_usage_after.canonical_promotions == 1
    assert _session_bundle(root.name, session_id)[4].budget_usage.controller_invocations == 0
    assert _tree_hashes(root) == before


@pytest.mark.parametrize(
    "tags", [[], ["qa_role:primary", "qa_role:supporting"], ["qa_role:supporting"]]
)
def test_missing_ambiguous_or_mismatched_role_is_invalid_before_submission(authoring, tags):
    """Reject the incident's missing-role class and conflicting metadata without side effects."""

    root, _session, scene = authoring
    scene["objects"][0]["tags"] = tags
    geometry_fixture._write_json(root / "fidelity/preflight/scene_spec_v03.json", scene)
    before = _tree_hashes(root)
    report = _preflight(authoring)
    assert report.outcome == "invalid_candidate" and "role" in report.issues[0]
    assert report.budget_usage_after is None
    assert _tree_hashes(root) == before


def test_metadata_only_repair_does_not_change_the_scene_substance(authoring):
    """Preserve geometry, material and camera data during an unsubmitted metadata repair."""

    root, _session, scene = authoring
    original = copy.deepcopy(scene)
    scene["objects"][0]["tags"] = []
    geometry_fixture._write_json(root / "fidelity/preflight/scene_spec_v03.json", scene)
    assert _preflight(authoring).outcome == "invalid_candidate"
    scene["objects"][0]["tags"] = original["objects"][0]["tags"]
    geometry_fixture._write_json(root / "fidelity/preflight/scene_spec_v03.json", scene)
    assert _preflight(authoring).outcome == "passed"
    assert scene == original
    assert not (root / "aq2").exists()


@pytest.mark.parametrize("changed", ["candidate", "source", "session"])
def test_changed_candidate_source_or_session_cannot_issue_a_controller_request(authoring, changed):
    """Reject reuse of a saved pass with different source or candidate bytes."""

    root, session_id, _scene = authoring
    report = _preflight(authoring)
    if changed == "session":
        report = report.model_copy(update={"session_id": "another-session"})
    else:
        path = root / (
            report.candidate_scene_spec_v03.path
            if changed == "candidate"
            else "analysis/camera_solution.json"
        )
        path.write_bytes(path.read_bytes() + b"\n")
    state_before = _session_bundle(root.name, session_id)[4]
    with pytest.raises(ValueError, match="changed|another session"):
        _request(authoring, report)
    assert _session_bundle(root.name, session_id)[4] == state_before
    assert not (root / "production/autonomy_v2" / session_id / "controller_executions").exists()
    assert not (root / "analysis/scene_spec.json").exists()


def test_preflight_freezes_output_hashes_and_resume_does_not_consume_again(authoring):
    """Preserve a waiting request's exact report, sources and single invocation."""

    root, session_id, _scene = authoring
    report = _preflight(authoring)
    waiting = _request(authoring, report)
    assert waiting["result"]["status"] == "waiting_for_output"
    request = waiting["request"]
    expected = request["expected_output_sha256"]
    for artifact, name in (
        (report.candidate_modeling_plan, "modeling_plan.json"),
        (report.candidate_scene_spec_v03, "scene_spec_v03.json"),
    ):
        assert expected[f"{request['output_root']}/{name}"] == artifact.sha256
        assert any(item["sha256"] == artifact.sha256 for item in request["immutable_inputs"])
    state = _session_bundle(root.name, session_id)[4]
    assert state.budget_usage.controller_invocations == 1
    resumed = _request(authoring, report)
    assert resumed["request"] == request
    assert _session_bundle(root.name, session_id)[4] == state


def test_schema_failure_is_distinct_from_a_stale_artifact(authoring):
    """A malformed current candidate is a data error and does not leak rejected input values."""

    root, _session, _scene = authoring
    (root / "fidelity/preflight/scene_spec_v03.json").write_text('{"unexpected":"fixture-secret"}')
    report = _preflight(authoring)
    assert report.outcome == "invalid_candidate"
    assert "fixture-secret" not in report.model_dump_json()


def test_preflight_rejects_the_real_object_cost_without_consuming_budget(authoring):
    """Count all structural objects before issuing a controller or reserving candidate builds."""

    root, session_id, scene = authoring
    modeling_path = root / "fidelity/preflight/modeling_plan.json"
    modeling = json.loads(modeling_path.read_bytes())
    for data in (scene, modeling):
        data["objects"] = [copy.deepcopy(data["objects"][0]) for _ in range(21)]
        for index, item in enumerate(data["objects"]):
            item["id"] = f"asset.part{index}"
    geometry_fixture._write_json(modeling_path, modeling)
    geometry_fixture._write_json(root / "fidelity/preflight/scene_spec_v03.json", scene)
    before = _tree_hashes(root)
    report = _preflight(authoring)
    assert report.outcome == "budget_exhausted"
    assert report.required_blender_builds == 22
    assert "total_blender_builds" in report.issues[0]
    assert report.budget_usage_after is None and _tree_hashes(root) == before
    with pytest.raises(ValueError, match="failed"):
        _request(authoring, report)
    assert _session_bundle(root.name, session_id)[4].budget_usage.controller_invocations == 0


@pytest.mark.parametrize("changed", ["camera", "material", "geometry"])
def test_preflight_checks_camera_material_identity_and_geometry_kind(authoring, changed):
    """The pre-submission checker shares the full candidate contract, beyond role tags alone."""

    root, _session, scene = authoring
    if changed == "camera":
        scene["camera"]["focal_length_mm"] = 70.0
    elif changed == "material":
        scene["objects"][0]["material_id"] = "undeclared.material"
    else:
        scene["objects"][0]["geometry"] = {"kind": "cube", "size": [1.0, 1.0, 1.0]}
    geometry_fixture._write_json(root / "fidelity/preflight/scene_spec_v03.json", scene)
    before = _tree_hashes(root)
    assert _preflight(authoring).outcome == "invalid_candidate"
    assert _tree_hashes(root) == before


def test_a_changed_cost_projection_cannot_be_reused_as_a_pass(authoring):
    """Replay host-computed costs instead of trusting a structurally valid caller report."""

    root, session_id, _scene = authoring
    report = _preflight(authoring).model_copy(
        update={
            "candidate_object_count": 1,
            "required_blender_builds": 2,
        }
    )
    with pytest.raises(ValueError, match="differs from its current inputs"):
        _request(authoring, report)
    assert _session_bundle(root.name, session_id)[4].budget_usage.controller_invocations == 0


@pytest.mark.parametrize("changed", ["none", "scene", "reference"])
def test_structure_authoring_binds_the_exact_scene_and_authorized_reference(authoring, changed):
    """Reject mixed hypotheses or inline candidates while preserving a valid bound pair."""

    from test_reference_fidelity import hypothesis

    from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
    from codex_blender_modeler.reference_fidelity.service import artifact_at

    root, session_id, scene = authoring
    primary = _preflight(authoring).source_inputs[0]
    scene["objects"] = scene["objects"][:1]
    modeling_path = root / "fidelity/preflight/modeling_plan.json"
    modeling = json.loads(modeling_path.read_bytes())
    modeling["objects"] = modeling["objects"][:1]
    modeling["objects"][0]["assembly_role"] = "root"
    modeling["assembly_consistency_policy"] = "spatial_v1"
    modeling["assembly_frame"] = {
        "root_object_id": "asset.part0",
        "longitudinal_axis": "Y",
        "lateral_axis": "X",
        "vertical_axis": "Z",
        "evidence_status": "inferred",
    }
    geometry_fixture._write_json(modeling_path, modeling)
    geometry_fixture._write_json(root / "fidelity/preflight/scene_spec_v03.json", scene)
    observed = hypothesis().model_dump(mode="json")
    observed["job_id"] = root.name
    observed["reference"] = {"path": primary.path, "sha256": primary.sha256}
    observed["observations"][0]["region"] = [0.2, 0.2, 0.8, 0.8]
    observed["requirements"][0]["target_ids"] = ["asset.part0"]
    observed["camera"]["camera_fingerprint"] = camera_fingerprint(scene["camera"])
    if changed == "reference":
        alternate = root / "fidelity/preflight/alternate.png"
        Image.new("RGB", (32, 32), (100, 100, 100)).save(alternate)
        observed["reference"] = artifact_at(root, alternate).model_dump(mode="json")
    hypothesis_path = root / "fidelity/preflight/hypothesis.json"
    geometry_fixture._write_json(hypothesis_path, observed)
    inline = copy.deepcopy(scene)
    if changed == "scene":
        inline["materials"][0]["roughness"] = 0.9
    geometry_fixture._write_json(
        root / "fidelity/preflight/structure.json",
        {
            "schema_version": "0.1.0",
            "hypothesis": artifact_at(root, hypothesis_path).model_dump(),
            "scene": inline,
            "modeling_plan": modeling,
            "representation_rationale": "Observed sections define the structural volume.",
        },
    )
    before = _tree_hashes(root)
    arguments = dict(
        modeling_plan_path="fidelity/preflight/modeling_plan.json",
        scene_spec_v03_path="fidelity/preflight/scene_spec_v03.json",
        structure_authoring_path="fidelity/preflight/structure.json",
    )
    if changed == "reference":
        with pytest.raises(ValueError, match="reference differs from RootAuthorization"):
            preflight_aq_geometry_authoring(root.name, session_id, **arguments)
    else:
        report = preflight_aq_geometry_authoring(root.name, session_id, **arguments)
        assert report.outcome == ("passed" if changed == "none" else "invalid_candidate")
    assert _tree_hashes(root) == before


def test_preflighted_controller_output_still_passes_the_final_host_contract(tmp_path, monkeypatch):
    """Revalidate a completed exact request through the same mandatory post-controller checker."""

    from codex_blender_modeler.autonomy_v2.candidate_validation_service import (
        preflight_geometry_candidate_budget_v2,
    )
    from codex_blender_modeler.autonomy_v2.models import RootAuthorizationV2

    original = geometry_fixture.test_geometry_controller_candidate_builds_and_promotes_exactly

    def with_preflight(tmp_path, monkeypatch):
        """Select the new exact preflight path in the existing controller-only fixture."""

        original(tmp_path, monkeypatch, with_preflight=True)

    monkeypatch.setattr(
        geometry_fixture,
        "test_geometry_controller_candidate_builds_and_promotes_exactly",
        with_preflight,
    )
    root, _session, plan, budget, state, _artifact = staged_candidate(
        tmp_path,
        monkeypatch,
        object_count=3,
    )
    with open(native_io_path(root / plan.root_authorization.path), "rb") as handle:
        authorization = RootAuthorizationV2.model_validate_json(handle.read())
    before = _tree_hashes(root)
    projected = preflight_geometry_candidate_budget_v2(
        root=root,
        plan=plan,
        budget=budget,
        state=state,
        authorization=authorization,
    )
    assert projected.total_blender_builds == 4
    assert _tree_hashes(root) == before


def test_submitted_role_failure_terminal_keeps_consumption_and_job_local_classification(
    tmp_path,
    monkeypatch,
):
    """Use real immutable submitted output to test fail-closed handling before policy or Blender."""

    original_scene = geometry_fixture._scene_v03

    def invalid_scene(job_id, reference_path):
        """Omit metadata without changing recipe authority or material semantics."""

        result = original_scene(job_id, reference_path)
        result["objects"][0]["tags"] = []
        return result

    monkeypatch.setattr(geometry_fixture, "_scene_v03", invalid_scene)
    root, session, plan, _budget, state, _artifact = staged_candidate(
        tmp_path,
        monkeypatch,
        object_count=3,
    )
    result = supervisor._advance_geometry_with_policy(
        root.name,
        plan.session_id,
        state,
        quality_submission=None,
    )
    current = _session_bundle(root.name, plan.session_id)[4]
    assert result["state"]["status"] == "failed"
    assert current.budget_usage == state.budget_usage
    assert current.budget_usage.controller_invocations == 1
    assert not (session / "approval_envelope/authorizations").exists()
    assert not (root / "aq2").exists()
    artifact = approval_artifact_for(
        root,
        session / f"states/{current.sequence:04d}.json",
        artifact_id=current.state_id,
        kind="autonomy_v2_state",
    )
    failure, justification = supervisor._publish_blocked_failure_evidence(
        root.name,
        plan.session_id,
        current,
        artifact,
    )
    with open(native_io_path(root / failure.path), "rb") as handle:
        evidence = json.load(handle)
    with open(native_io_path(root / justification.path), "rb") as handle:
        classified = json.load(handle)
    assert evidence["category"] == "schema_serialization"
    assert evidence["user_approval_requested"] is False
    assert classified["classification"] == "job_local_candidate_error"
    with pytest.raises(PermissionError, match="fresh controller boundary"):
        preflight_aq_geometry_authoring(
            root.name,
            plan.session_id,
            modeling_plan_path="fidelity/unused.json",
            scene_spec_v03_path="fidelity/unused.json",
        )


def test_geometry_preflight_cli_mcp_schema_and_allowlist_match(authoring):
    """Exercise both public read-only surfaces and the authoritative new companion schema."""

    root, session_id, _scene = authoring
    expected = _preflight(authoring)
    result = CliRunner().invoke(
        app,
        [
            "aq-geometry-preflight",
            root.name,
            session_id,
            "--modeling-plan",
            expected.candidate_modeling_plan.path,
            "--scene-spec-v03",
            expected.candidate_scene_spec_v03.path,
        ],
    )
    assert result.exit_code == 0, result.output
    assert GeometryAuthoringPreflightV01.model_validate_json(result.stdout) == expected
    assert mcp_server.preflight_aq_geometry_authoring(
        root.name,
        session_id,
        expected.candidate_modeling_plan.path,
        expected.candidate_scene_spec_v03.path,
    ) == expected.model_dump(mode="json")
    config = tomllib.loads((ROOT / ".codex/config.toml").read_text())
    assert (
        "preflight_aq_geometry_authoring"
        in config["mcp_servers"]["blender_modeler"]["enabled_tools"]
    )
    registry = runpy.run_path(str(ROOT / "scripts/generate_schemas.py"))["SCHEMAS"]
    name = "aq_geometry_authoring_preflight_v01.schema.json"
    assert registry[name] is GeometryAuthoringPreflightV01
    assert json.loads((ROOT / "schemas" / name).read_bytes()) == expected.model_json_schema()
