"""Focused host-seam tests for exact material adoption and repair preflight runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from codex_blender_modeler.autonomy_v2.approval_models import ApprovalArtifact
from codex_blender_modeler.autonomy_v2.controller_bridge import (
    ExactMaterialClosureAdoptionController,
)
from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialClosurePolicyPromotionBoundaryV03,
    MaterialClosurePromotionBoundaryV2,
    MaterialControllerCompletionV2,
)
from codex_blender_modeler.autonomy_v2.models import AQV2Artifact
from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.material_closure.incident_service import (
    run_material_repair_session,
)
from codex_blender_modeler.material_closure.models import (
    MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES,
    MATERIAL_REPAIR_REQUIRED_STEPS,
    ExactArtifact,
    MaterialAQBudgetObservation,
    MaterialCanonicalSnapshot,
    MaterialClosureIssue,
    MaterialDependencyClosure,
    MaterialDependencyEntry,
    MaterialFrameworkFailureContext,
    MaterialPlannedOutput,
    MaterialPreflightCheck,
    MaterialPromotionPreflightFailure,
    MaterialPromotionPreflightReport,
    MaterialPromotionPreflightRequest,
    MaterialRepairSessionPlan,
    MaterialRepairSourceBinding,
    MaterialResourceCounters,
    _closure_payload_digest,
)
from codex_blender_modeler.material_closure.service import (
    MaterialClosureService,
    MaterialPromotionPreflightResult,
)
from codex_blender_modeler.production.controller_executor import (
    ControllerArtifact,
    PhaseToolProfile,
)

NOW = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)


def _write_json(path: Path, value: object) -> None:
    """Write one deterministic fixture model or JSON value to a contained path."""

    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def _exact_artifact(
    root: Path,
    relative_path: str,
    *,
    artifact_id: str,
    kind: str,
    media_type: str = "application/json",
) -> ExactArtifact:
    """Bind an existing fixture file to its exact path, size, and digest."""

    path = root.joinpath(*relative_path.split("/"))
    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=relative_path,
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
        media_type=media_type,
    )


def _aq_artifact(
    *,
    artifact_id: str,
    path: str,
    sha256: str | None = None,
    byte_size: int = 1,
) -> AQV2Artifact:
    """Build one distinct AQ projection artifact for a strict boundary fixture."""

    return AQV2Artifact(
        artifact_id=artifact_id,
        kind="fixture-evidence",
        path=path,
        sha256=sha256 or hashlib.sha256(artifact_id.encode("utf-8")).hexdigest(),
        byte_size=byte_size,
    )


@dataclass(frozen=True)
class _ControllerFixture:
    """Hold one full closure projection and its isolated controller call paths."""

    root: Path
    closure: MaterialDependencyClosure
    boundary: MaterialClosurePromotionBoundaryV2
    assignment: Path
    immutable_inputs: tuple[Path, ...]
    output_paths: tuple[Path, ...]
    tool_profile: PhaseToolProfile


def _controller_fixture(
    tmp_path: Path,
    *,
    candidate_alias_role: str | None = None,
) -> _ControllerFixture:
    """Build a full-root closure, optionally with one byte-identical candidate alias."""

    root = tmp_path / "controller-fixture"
    root.mkdir()
    output_root = (
        root
        / "workspace"
        / "controller_executions"
        / "execution-1"
        / "outputs"
    )
    planned_paths = {
        "material_plan": (
            "production/autonomy_v2/session-1/controller_executions/"
            "execution-1/material_plan.json"
        ),
        "material_graph": (
            "production/autonomy_v2/session-1/controller_executions/"
            "execution-1/material_graph.json"
        ),
        "controller_completion": (
            "production/autonomy_v2/session-1/controller_executions/"
            "execution-1/completion.json"
        ),
    }
    profile_source = ControllerArtifact(
        artifact_id="profile-source",
        role="profile-source",
        path="production/profile-source.json",
        sha256="f" * 64,
        byte_size=1,
    )
    tool_profile = PhaseToolProfile(
        contract_id="material-profile",
        job_id="fixture_job",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        input_sha256=profile_source.sha256,
        source_fingerprint="e" * 64,
        producer="tests.material_closure",
        provenance=[profile_source],
        created_at=NOW,
        profile_id="material_authoring",
        allowed_tools=[],
        forbidden_tools=["arbitrary_python"],
        allowed_input_roles=["material_closure"],
        allowed_output_paths=list(planned_paths.values()),
    )

    role_paths = {
        "material_closure_source_binding": (
            "production/material_closure/session-1/source_binding.json"
        ),
        "canonical_scene_spec": "analysis/scene_spec.json",
        "modeling_plan": "analysis/modeling_plan.json",
        "aq_root_authorization": (
            "production/autonomy_v2/session-1/root_authorization.json"
        ),
        "aq_autonomy_plan": "production/autonomy_v2/session-1/plan.json",
        "aq_autonomy_profile": "production/autonomy_v2/session-1/profile.json",
        "aq_autonomy_budget": "production/autonomy_v2/session-1/budget.json",
        "material_phase_tool_profile": (
            "production/autonomy_v2/session-1/tool_profiles/material_authoring.json"
        ),
        "geometry_candidate_validation_receipt": (
            "production/autonomy_v2/session-1/geometry/validation.json"
        ),
        "canonical_build_provenance": "reports/build_provenance.json",
        "canonical_scene_inventory": "reports/scene_inventory.json",
        "candidate_material_plan": "staging/material_plan.json",
        "source_material_graph": "staging/source_material_graph.json",
        "material_graph_rebinding_plan": (
            "production/material_closure/session-1/graph_rebindings/rebind-1/plan.json"
        ),
        "material_graph_rebinding_receipt": (
            "production/material_closure/session-1/graph_rebindings/rebind-1/receipt.json"
        ),
        "rebound_material_graph": (
            "production/material_closure/session-1/graph_rebindings/rebind-1/"
            "rebound_material_graph.json"
        ),
        "rollback_baseline": "history/material_rollback_baseline.json",
    }
    assert MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES <= set(role_paths)
    for role, relative_path in role_paths.items():
        path = root.joinpath(*relative_path.split("/"))
        if role == "material_phase_tool_profile":
            _write_json(path, tool_profile)
        else:
            _write_json(path, {"role": role, "fixture": "exact-controller"})
    if candidate_alias_role is not None:
        if candidate_alias_role not in role_paths:
            raise ValueError("candidate alias role is absent from the fixture")
        candidate_path = root.joinpath(*role_paths["candidate_material_plan"].split("/"))
        alias_path = root.joinpath(*role_paths[candidate_alias_role].split("/"))
        alias_path.write_bytes(candidate_path.read_bytes())

    entries: list[MaterialDependencyEntry] = []
    for role, relative_path in role_paths.items():
        path = root.joinpath(*relative_path.split("/"))
        entries.append(
            MaterialDependencyEntry(
                entry_id=f"entry-{role.replace('_', '-')}",
                role=role,
                path=relative_path,
                sha256=sha256_file(path),
                byte_size=path.stat().st_size,
                source_kind=(
                    "rollback_evidence"
                    if role == "rollback_baseline"
                    else "canonical_artifact"
                    if role.startswith("canonical_") or role == "modeling_plan"
                    else "staging_artifact"
                ),
                required=True,
                producer="tests",
                ownership=(
                    "canonical"
                    if role.startswith("canonical_") or role == "modeling_plan"
                    else "staging"
                ),
            )
        )
    entries.sort(key=lambda item: (item.role, item.path))
    entry_by_role = {entry.role: entry for entry in entries}
    planned_outputs = [
        MaterialPlannedOutput(
            output_id="output-material-plan",
            output_kind="material_plan",
            path=planned_paths["material_plan"],
            verification="exact_hash",
            sha256=entry_by_role["candidate_material_plan"].sha256,
            media_type="application/json",
        ),
        MaterialPlannedOutput(
            output_id="output-material-graph",
            output_kind="material_graph",
            path=planned_paths["material_graph"],
            verification="exact_hash",
            sha256=entry_by_role["rebound_material_graph"].sha256,
            media_type="application/json",
        ),
        MaterialPlannedOutput(
            output_id="output-completion",
            output_kind="controller_completion",
            path=planned_paths["controller_completion"],
            verification="structural_binding",
            expected_schema_version="0.2.0",
            expected_field_bindings={"session_id": "session-1"},
            media_type="application/json",
        ),
    ]
    planned_outputs.sort(key=lambda item: (item.output_kind, item.path))
    source_entry = entry_by_role["material_closure_source_binding"]
    source_binding = ExactArtifact(
        artifact_id="source-binding",
        kind="material_closure_source_binding",
        path=source_entry.path,
        sha256=source_entry.sha256,
        byte_size=source_entry.byte_size,
        media_type="application/json",
    )
    rollback_entry = entry_by_role["rollback_baseline"]
    rollback = ExactArtifact(
        artifact_id="rollback-baseline",
        kind="rollback_baseline",
        path=rollback_entry.path,
        sha256=rollback_entry.sha256,
        byte_size=rollback_entry.byte_size,
        media_type="application/json",
    )
    closure = MaterialDependencyClosure(
        closure_id="closure-1",
        closure_sha256=_closure_payload_digest(
            entries,
            planned_outputs,
            source_binding,
        ),
        job_id="fixture_job",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        producer="tests",
        producer_version="0.1.0",
        created_at=NOW,
        source_binding=source_binding,
        entries=entries,
        planned_outputs=planned_outputs,
        rollback_baseline=rollback,
    )

    candidate = entry_by_role["candidate_material_plan"]
    rebound = entry_by_role["rebound_material_graph"]
    named = {
        "current_state": _aq_artifact(
            artifact_id="current-state",
            path="production/autonomy_v2/session-1/states/0001.json",
        ),
        "dependency_closure": _aq_artifact(
            artifact_id="closure",
            path="production/material_closure/session-1/closure.json",
        ),
        "dependency_closure_receipt": _aq_artifact(
            artifact_id="closure-receipt",
            path="production/material_closure/session-1/closure_receipt.json",
        ),
        "graph_rebinding_receipt": _aq_artifact(
            artifact_id="rebind-receipt",
            path=entry_by_role["material_graph_rebinding_receipt"].path,
            sha256=entry_by_role["material_graph_rebinding_receipt"].sha256,
            byte_size=entry_by_role["material_graph_rebinding_receipt"].byte_size,
        ),
        "preflight_report": _aq_artifact(
            artifact_id="preflight-report",
            path="production/material_closure/session-1/preflights/preflight-1/report.json",
        ),
        "shadow_compile_receipt": _aq_artifact(
            artifact_id="shadow-receipt",
            path="production/material_closure/session-1/preflights/preflight-1/shadow.json",
        ),
        "neutral_preview_manifest": _aq_artifact(
            artifact_id="neutral-preview",
            path="production/material_closure/session-1/preflights/preflight-1/preview.json",
        ),
        "appearance_approval": _aq_artifact(
            artifact_id="appearance-approval",
            path="production/material_closure/session-1/approvals/approval-1.json",
        ),
        "state_consistency_report": _aq_artifact(
            artifact_id="consistency-report",
            path="production/material_closure/session-1/consistency.json",
        ),
        "candidate_material_plan": _aq_artifact(
            artifact_id="candidate-plan",
            path=candidate.path,
            sha256=candidate.sha256,
            byte_size=candidate.byte_size,
        ),
        "rebound_material_graph": _aq_artifact(
            artifact_id="rebound-graph",
            path=rebound.path,
            sha256=rebound.sha256,
            byte_size=rebound.byte_size,
        ),
    }
    boundary = MaterialClosurePromotionBoundaryV2(
        contract_id="boundary-contract",
        boundary_id="boundary-1",
        job_id="fixture_job",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        input_sha256="a" * 64,
        source_fingerprint="b" * 64,
        producer="tests.material_closure",
        provenance=list(named.values()),
        created_at=NOW,
        **named,
        immutable_input_sha256=closure.project_immutable_input_map(),
        planned_output_sha256=closure.project_planned_output_map(),
        canonical_scene_spec_sha256=entry_by_role["canonical_scene_spec"].sha256,
        canonical_blend_sha256="c" * 64,
        uv_layout_fingerprint="d" * 64,
    )
    assignment = root / "assignment.json"
    _write_json(assignment, boundary)
    immutable_inputs = tuple(
        root.joinpath(*entry.path.split("/"))
        for entry in sorted(closure.entries, key=lambda item: item.path)
    )
    output_paths = tuple(
        output_root / name
        for name in ("material_plan.json", "material_graph.json", "completion.json")
    )
    return _ControllerFixture(
        root=root,
        closure=closure,
        boundary=boundary,
        assignment=assignment,
        immutable_inputs=immutable_inputs,
        output_paths=output_paths,
        tool_profile=tool_profile,
    )


def test_policy_material_boundary_is_non_user_and_cannot_mix_appearance_approval(
    tmp_path: Path,
) -> None:
    """Model the additive policy seam without weakening the explicit boundary."""

    fixture = _controller_fixture(tmp_path)
    explicit = fixture.boundary

    def policy_artifact(name: str, kind: str) -> ApprovalArtifact:
        """Build one distinct approval-envelope artifact for policy-bound evidence."""

        return ApprovalArtifact.model_validate(
            _aq_artifact(
                artifact_id=name,
                path=f"production/autonomy_v2/session-1/approval_envelope/{name}.json",
            ).model_dump(mode="python")
            | {"kind": kind}
        )

    root_authorization = policy_artifact("root-authorization", "root-authorization")
    policy_profile = policy_artifact("policy-profile", "autonomy-approval-policy-profile")
    envelope = policy_artifact("approval-envelope", "autonomy-approval-envelope")
    budget = policy_artifact("approval-budget", "aqv2-approval-budget")
    authorization = policy_artifact(
        "material-policy-authorization",
        "aq-v2-routine-policy-authorization",
    )
    authorization_as_aq = AQV2Artifact.model_validate(
        authorization.model_dump(mode="python")
    )
    provenance = [
        explicit.current_state,
        explicit.dependency_closure,
        explicit.dependency_closure_receipt,
        explicit.graph_rebinding_receipt,
        explicit.preflight_report,
        explicit.shadow_compile_receipt,
        explicit.neutral_preview_manifest,
        authorization_as_aq,
        explicit.state_consistency_report,
        explicit.candidate_material_plan,
        explicit.rebound_material_graph,
    ]
    boundary = MaterialClosurePolicyPromotionBoundaryV03(
        contract_id="material-policy-boundary",
        boundary_id="material-policy-boundary",
        job_id=explicit.job_id,
        workflow_id=explicit.workflow_id,
        dispatch_id=explicit.dispatch_id,
        session_id=explicit.session_id,
        root_authorization=root_authorization,
        producer="tests.material_closure",
        created_at=NOW,
        approval_count_effect="reduces",
        approval_count_justification=(
            "Exact routine policy authority replaces no user approval artifact."
        ),
        policy_profile=policy_profile,
        approval_envelope=envelope,
        approval_budget=budget,
        policy_authorization=authorization,
        current_state=explicit.current_state,
        dependency_closure=explicit.dependency_closure,
        dependency_closure_receipt=explicit.dependency_closure_receipt,
        graph_rebinding_receipt=explicit.graph_rebinding_receipt,
        preflight_report=explicit.preflight_report,
        shadow_compile_receipt=explicit.shadow_compile_receipt,
        neutral_preview_manifest=explicit.neutral_preview_manifest,
        state_consistency_report=explicit.state_consistency_report,
        candidate_material_plan=explicit.candidate_material_plan,
        rebound_material_graph=explicit.rebound_material_graph,
        provenance=provenance,
        immutable_input_sha256=explicit.immutable_input_sha256,
        planned_output_sha256=explicit.planned_output_sha256,
        canonical_scene_spec_sha256=explicit.canonical_scene_spec_sha256,
        canonical_blend_sha256=explicit.canonical_blend_sha256,
        uv_layout_fingerprint=explicit.uv_layout_fingerprint,
    )

    assert boundary.appearance_approval_required is False
    assert boundary.policy_authorization_is_user_approval is False
    mixed = boundary.model_dump(mode="python")
    mixed["appearance_approval"] = explicit.appearance_approval
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        MaterialClosurePolicyPromotionBoundaryV03.model_validate(mixed)


def test_exact_controller_emits_only_closure_planned_bytes_and_completion(
    tmp_path: Path,
) -> None:
    """Adopt exact candidate bytes and emit one closure-bound completion only."""

    fixture = _controller_fixture(tmp_path)
    token = ExactMaterialClosureAdoptionController(fixture.closure).execute(
        assignment=fixture.assignment,
        immutable_inputs=fixture.immutable_inputs,
        allowed_output_paths=fixture.output_paths,
        tool_profile=fixture.tool_profile,
        timeout_seconds=60,
    )
    assert token == "completed"
    output_by_name = {path.name: path for path in fixture.output_paths}
    entry_by_role = {entry.role: entry for entry in fixture.closure.entries}
    candidate_path = fixture.root.joinpath(
        *entry_by_role["candidate_material_plan"].path.split("/")
    )
    rebound_path = fixture.root.joinpath(
        *entry_by_role["rebound_material_graph"].path.split("/")
    )
    assert output_by_name["material_plan.json"].read_bytes() == candidate_path.read_bytes()
    assert output_by_name["material_graph.json"].read_bytes() == rebound_path.read_bytes()
    completion = MaterialControllerCompletionV2.model_validate_json(
        output_by_name["completion.json"].read_bytes()
    )
    assert completion.material_dependency_closure_sha256 == fixture.closure.closure_sha256
    assert completion.immutable_input_sha256 == fixture.closure.project_immutable_input_map()
    assert completion.assignment_sha256 == sha256_file(fixture.assignment)
    assert completion.execution_id == "execution-1"
    assert {
        path.relative_to(fixture.output_paths[0].parent).as_posix()
        for path in fixture.output_paths[0].parent.rglob("*")
        if path.is_file()
    } == {"material_plan.json", "material_graph.json", "completion.json"}


@pytest.mark.parametrize("projection", ["immutable", "planned"])
def test_exact_controller_rejects_reduced_or_tampered_assignment_projection(
    tmp_path: Path,
    projection: str,
) -> None:
    """Fail before output when assignment maps no longer equal the full closure."""

    fixture = _controller_fixture(tmp_path)
    payload = fixture.boundary.model_dump(mode="python")
    if projection == "immutable":
        reduced = dict(fixture.boundary.immutable_input_sha256)
        reduced.pop(next(iter(reduced)))
        payload["immutable_input_sha256"] = reduced
    else:
        tampered = dict(fixture.boundary.planned_output_sha256)
        first = next(iter(tampered))
        tampered[first] = "0" * 64
        payload["planned_output_sha256"] = tampered
    changed = MaterialClosurePromotionBoundaryV2.model_validate(payload)
    _write_json(fixture.assignment, changed)
    with pytest.raises(ValueError, match="projection changed"):
        ExactMaterialClosureAdoptionController(fixture.closure).execute(
            assignment=fixture.assignment,
            immutable_inputs=fixture.immutable_inputs,
            allowed_output_paths=fixture.output_paths,
            tool_profile=fixture.tool_profile,
            timeout_seconds=60,
        )
    assert not any(path.exists() for path in fixture.output_paths)


def test_exact_controller_rejects_reduced_actual_snapshot_set(tmp_path: Path) -> None:
    """Require the controller call itself to carry every closure-declared input snapshot."""

    fixture = _controller_fixture(tmp_path)
    removable = next(
        path
        for path in fixture.immutable_inputs
        if path.as_posix().endswith("reports/scene_inventory.json")
    )
    reduced = tuple(path for path in fixture.immutable_inputs if path != removable)
    with pytest.raises(ValueError, match="immutable.*snapshot"):
        ExactMaterialClosureAdoptionController(fixture.closure).execute(
            assignment=fixture.assignment,
            immutable_inputs=reduced,
            allowed_output_paths=fixture.output_paths,
            tool_profile=fixture.tool_profile,
            timeout_seconds=60,
        )
    assert not any(path.exists() for path in fixture.output_paths)


def test_exact_controller_accepts_byte_identical_candidate_aliases(tmp_path: Path) -> None:
    """Select a deterministic candidate snapshot after the full alias multiset passes."""

    fixture = _controller_fixture(
        tmp_path,
        candidate_alias_role="source_material_graph",
    )
    assert (
        sum(
            sha256_file(path) == fixture.boundary.candidate_material_plan.sha256
            for path in fixture.immutable_inputs
        )
        == 2
    )
    token = ExactMaterialClosureAdoptionController(fixture.closure).execute(
        assignment=fixture.assignment,
        immutable_inputs=fixture.immutable_inputs,
        allowed_output_paths=fixture.output_paths,
        tool_profile=fixture.tool_profile,
        timeout_seconds=60,
    )
    assert token == "completed"
    assert fixture.output_paths[0].read_bytes() == fixture.root.joinpath(
        *fixture.boundary.candidate_material_plan.path.split("/")
    ).read_bytes()


def test_exact_controller_rejects_wrong_alias_snapshot_multiset(tmp_path: Path) -> None:
    """Reject alias calls whose digest counts differ from the complete closure projection."""

    fixture = _controller_fixture(
        tmp_path,
        candidate_alias_role="source_material_graph",
    )
    candidate_sha256 = fixture.boundary.candidate_material_plan.sha256
    alias_index = next(
        index
        for index, path in enumerate(fixture.immutable_inputs)
        if sha256_file(path) == candidate_sha256
    )
    replacement = next(
        path
        for path in fixture.immutable_inputs
        if sha256_file(path) != candidate_sha256
    )
    wrong_multiset = list(fixture.immutable_inputs)
    wrong_multiset[alias_index] = replacement
    with pytest.raises(ValueError, match="immutable snapshots differ"):
        ExactMaterialClosureAdoptionController(fixture.closure).execute(
            assignment=fixture.assignment,
            immutable_inputs=tuple(wrong_multiset),
            allowed_output_paths=fixture.output_paths,
            tool_profile=fixture.tool_profile,
            timeout_seconds=60,
        )
    assert not any(path.exists() for path in fixture.output_paths)


@dataclass(frozen=True)
class _RepairFixture:
    """Hold exact repair plan/source/request/snapshot artifacts and their disk paths."""

    root: Path
    plan_artifact: ExactArtifact
    source_artifact: ExactArtifact
    paths: dict[str, Path]
    request: MaterialPromotionPreflightRequest


def _repair_fixture(tmp_path: Path) -> _RepairFixture:
    """Build one material-only repair session with exact reusable geometry bindings."""

    root = tmp_path / "repair-job"
    root.mkdir()
    raw_files = {
        "analysis/scene_spec.json": b'{"scene":"unchanged"}\n',
        "analysis/modeling_plan.json": b'{"modeling":"unchanged"}\n',
        "blender/scene.blend": b"unchanged-blend-bytes\n",
        "production/material_repair/build_provenance.json": b'{"build":"current"}\n',
        "history/material_plan_absence.json": b'{"absent":true}\n',
        "history/geometry_validation.json": b'{"geometry":"passed"}\n',
        "history/framework_failure.json": b'{"framework":"blocked"}\n',
        "input/reference.png": b"fixture-reference-png",
        "production/material_repair/current_state.json": b'{"state":"blocked"}\n',
        "production/material_repair/closure.json": b'{"closure":"exact"}\n',
        "production/material_repair/closure_receipt.json": b'{"closure":"passed"}\n',
        "production/material_repair/rebinding_receipt.json": b'{"rebind":"passed"}\n',
        "production/material_repair/candidate_plan.json": b'{"candidate":"plan"}\n',
        "production/material_repair/rebound_graph.json": b'{"candidate":"graph"}\n',
        "production/material_repair/budget.json": b'{"budget":"bounded"}\n',
    }
    for relative_path, content in raw_files.items():
        path = root.joinpath(*relative_path.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    scene = _exact_artifact(
        root,
        "analysis/scene_spec.json",
        artifact_id="scene",
        kind="scene_spec",
    )
    modeling = _exact_artifact(
        root,
        "analysis/modeling_plan.json",
        artifact_id="modeling",
        kind="modeling_plan",
    )
    blend = _exact_artifact(
        root,
        "blender/scene.blend",
        artifact_id="blend",
        kind="canonical_blend",
        media_type="application/x-blender",
    )
    absence = _exact_artifact(
        root,
        "history/material_plan_absence.json",
        artifact_id="material-absence",
        kind="material_plan_absence",
    )
    geometry = _exact_artifact(
        root,
        "history/geometry_validation.json",
        artifact_id="geometry-validation",
        kind="geometry_validation",
    )
    failure = _exact_artifact(
        root,
        "history/framework_failure.json",
        artifact_id="framework-failure",
        kind="framework_failure",
    )
    reference = _exact_artifact(
        root,
        "input/reference.png",
        artifact_id="reference",
        kind="primary_reference",
        media_type="image/png",
    )
    current_state = _exact_artifact(
        root,
        "production/material_repair/current_state.json",
        artifact_id="state",
        kind="current_state",
    )
    build_provenance = _exact_artifact(
        root,
        "production/material_repair/build_provenance.json",
        artifact_id="build-provenance",
        kind="build_provenance",
    )
    bound: dict[str, Any] = {
        "job_id": "fixture_job",
        "workflow_id": "workflow-1",
        "dispatch_id": "dispatch-1",
        "session_id": "repair-session",
        "producer": "tests",
        "producer_version": "0.1.0",
        "created_at": NOW,
    }
    snapshot = MaterialCanonicalSnapshot(
        **bound,
        snapshot_id="snapshot-1",
        scene_spec=scene,
        modeling_plan=modeling,
        material_plan_absence=absence,
        blend=blend,
        build_provenance=build_provenance,
        build_provenance_fingerprint=build_provenance.sha256,
    )
    snapshot_relative = "production/material_repair/canonical_snapshot.json"
    snapshot_path = root.joinpath(*snapshot_relative.split("/"))
    _write_json(snapshot_path, snapshot)
    snapshot_artifact = _exact_artifact(
        root,
        snapshot_relative,
        artifact_id="snapshot-1",
        kind="material_canonical_snapshot",
    )
    counters = MaterialResourceCounters(
        preflight_blender_runs=0,
        controller_invocations=0,
        canonical_promotions=0,
        appearance_revisions=0,
    )
    fixture_artifacts = {
        name: _exact_artifact(
            root,
            relative,
            artifact_id=name.replace("_", "-"),
            kind=name,
        )
        for name, relative in {
            "closure": "production/material_repair/closure.json",
            "closure_receipt": "production/material_repair/closure_receipt.json",
            "rebinding_receipt": "production/material_repair/rebinding_receipt.json",
            "candidate_plan": "production/material_repair/candidate_plan.json",
            "rebound_graph": "production/material_repair/rebound_graph.json",
            "budget": "production/material_repair/budget.json",
        }.items()
    }
    request = MaterialPromotionPreflightRequest(
        **bound,
        request_id="preflight-request-1",
        closure=fixture_artifacts["closure"],
        closure_receipt=fixture_artifacts["closure_receipt"],
        graph_rebinding_receipt=fixture_artifacts["rebinding_receipt"],
        candidate_material_plan=fixture_artifacts["candidate_plan"],
        rebound_material_graph=fixture_artifacts["rebound_graph"],
        canonical_snapshot=snapshot_artifact,
        budget=fixture_artifacts["budget"],
        framework_failure_context=MaterialFrameworkFailureContext(
            state_sequence=12,
            current_state=current_state,
            canonical_snapshot=snapshot,
            controller_execution_count=0,
            rollback_count=0,
            budget_usage=counters,
            aq_budget_observation=MaterialAQBudgetObservation(
                blender_builds_used=13,
                blender_builds_limit=14,
                controller_invocations_used=6,
                controller_invocations_limit=16,
                canonical_promotions_used=1,
                canonical_promotions_limit=5,
                actions_used=9,
                actions_limit=72,
                quality_evaluations_used=0,
                quality_evaluations_limit=10,
            ),
            neutral_preview_present=False,
            material_phase_receipt_present=False,
            integrated_quality_entered=False,
        ),
        uv_layout_fingerprint="2" * 64,
        planned_output_projection={
            "production/material_repair/output/material_plan.json": (
                fixture_artifacts["candidate_plan"].sha256
            ),
            "production/material_repair/output/material_graph.json": (
                fixture_artifacts["rebound_graph"].sha256
            ),
        },
    )
    request_relative = (
        "production/material_closure/repair-session/preflights/preflight-1/request.json"
    )
    request_path = root.joinpath(*request_relative.split("/"))
    _write_json(request_path, request)
    request_artifact = _exact_artifact(
        root,
        request_relative,
        artifact_id="preflight-request-1",
        kind="material_preflight_request",
    )
    source = MaterialRepairSourceBinding(
        **bound,
        binding_id="repair-source-1",
        source_session_id="historical-session",
        scene_spec=scene,
        modeling_plan=modeling,
        blend=blend,
        geometry_approval_or_validation=geometry,
        material_plan_absence=absence,
        primary_reference=reference,
        uv_layout_fingerprint="2" * 64,
        target_subject="generic static fixture",
        content_scope_sha256="3" * 64,
        framework_failure_report=failure,
    )
    source_relative = "production/material_repair/repair-session/source_binding.json"
    source_path = root.joinpath(*source_relative.split("/"))
    _write_json(source_path, source)
    source_artifact = _exact_artifact(
        root,
        source_relative,
        artifact_id="repair-source-1",
        kind="material_repair_source_binding",
    )
    plan = MaterialRepairSessionPlan(
        **bound,
        plan_id="repair-plan-1",
        repair_attempt_id="repair-attempt-1",
        source_session_id="historical-session",
        source_binding=source_artifact,
        source_binding_sha256=source_artifact.sha256,
        preflight_request=request_artifact,
        required_steps=list(MATERIAL_REPAIR_REQUIRED_STEPS),
    )
    plan_relative = "production/material_repair/repair-session/plan.json"
    plan_path = root.joinpath(*plan_relative.split("/"))
    _write_json(plan_path, plan)
    plan_artifact = _exact_artifact(
        root,
        plan_relative,
        artifact_id="repair-plan-1",
        kind="material_repair_session_plan",
    )
    return _RepairFixture(
        root=root,
        plan_artifact=plan_artifact,
        source_artifact=source_artifact,
        paths={
            "plan": plan_path,
            "source": source_path,
            "request": request_path,
            "snapshot": snapshot_path,
        },
        request=request,
    )


def _mock_preflight_result(
    fixture: _RepairFixture,
    *,
    passed: bool,
) -> MaterialPromotionPreflightResult:
    """Build one complete mocked preflight terminal with exact report evidence."""

    bound = {
        "job_id": "fixture_job",
        "workflow_id": "workflow-1",
        "dispatch_id": "dispatch-1",
        "session_id": "repair-session",
        "producer": "tests",
        "producer_version": "0.1.0",
        "created_at": NOW,
    }
    request_artifact = _exact_artifact(
        fixture.root,
        fixture.paths["request"].relative_to(fixture.root).as_posix(),
        artifact_id="preflight-request-1",
        kind="material_preflight_request",
    )
    evidence = fixture.request.closure
    if passed:
        report = MaterialPromotionPreflightReport(
            **bound,
            report_id="preflight-report-1",
            request=request_artifact,
            closure=fixture.request.closure,
            closure_receipt=fixture.request.closure_receipt,
            graph_rebinding_receipt=fixture.request.graph_rebinding_receipt,
            shadow_compile_receipt=evidence.model_copy(
                update={"artifact_id": "shadow", "kind": "shadow_receipt"}
            ),
            neutral_preview_manifest=evidence.model_copy(
                update={"artifact_id": "preview", "kind": "neutral_preview"}
            ),
            resource_receipt=evidence.model_copy(
                update={"artifact_id": "resource", "kind": "resource_receipt"}
            ),
            checks=[
                MaterialPreflightCheck(
                    check_id="complete_preflight",
                    category="contract",
                    status="passed",
                    message="Complete mocked preflight passed.",
                )
            ],
            immutable_input_projection={"analysis/scene_spec.json": "4" * 64},
            planned_output_projection=fixture.request.planned_output_projection,
        )
        relative = "production/material_repair/preflight_report.json"
        _write_json(fixture.root.joinpath(*relative.split("/")), report)
        report_artifact = _exact_artifact(
            fixture.root,
            relative,
            artifact_id=report.report_id,
            kind="material_preflight_report",
        )
        return MaterialPromotionPreflightResult(
            report=report,
            report_artifact=report_artifact,
            failure=None,
            failure_artifact=None,
            framework_failure_report=None,
            framework_failure_report_artifact=None,
            shadow_receipt=None,
            shadow_receipt_artifact=None,
            neutral_preview=None,
            neutral_preview_artifact=None,
            resource_receipt=None,
            resource_receipt_artifact=None,
        )
    failure = MaterialPromotionPreflightFailure(
        **bound,
        failure_id="preflight-failure-1",
        request=request_artifact,
        closure=fixture.request.closure,
        issues=[
            MaterialClosureIssue(
                code="PREFLIGHT_FAILED",
                message="Complete mocked preflight failed before approval.",
            )
        ],
        framework_failure_report_path="history/framework_failure.json",
        recommendations=["Repair the exact failed dependency before a new attempt."],
    )
    relative = "production/material_repair/preflight_failure.json"
    _write_json(fixture.root.joinpath(*relative.split("/")), failure)
    failure_artifact = _exact_artifact(
        fixture.root,
        relative,
        artifact_id=failure.failure_id,
        kind="material_preflight_failure",
    )
    return MaterialPromotionPreflightResult(
        report=None,
        report_artifact=None,
        failure=failure,
        failure_artifact=failure_artifact,
        framework_failure_report=None,
        framework_failure_report_artifact=None,
        shadow_receipt=None,
        shadow_receipt_artifact=None,
        neutral_preview=None,
        neutral_preview_artifact=None,
        resource_receipt=None,
        resource_receipt_artifact=None,
    )


@pytest.mark.parametrize(
    ("passed", "expected_state"),
    [(True, "approval_pending"), (False, "preflight_failed")],
)
def test_material_repair_run_stops_without_approval_controller_or_canonical_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    passed: bool,
    expected_state: str,
) -> None:
    """Publish only a preapproval attempt state while preserving reusable geometry."""

    fixture = _repair_fixture(tmp_path)
    preflight = _mock_preflight_result(fixture, passed=passed)
    calls: list[tuple[str, int, datetime]] = []

    def _run_preflight(
        _service: MaterialClosureService,
        request: MaterialPromotionPreflightRequest,
        *,
        preview_size: int,
        created_at: datetime,
    ) -> MaterialPromotionPreflightResult:
        """Return the chosen complete terminal and record exact invocation arguments."""

        calls.append((request.request_id, preview_size, created_at))
        return preflight

    monkeypatch.setattr(MaterialClosureService, "run_preflight", _run_preflight)
    protected = {
        relative: sha256_file(fixture.root.joinpath(*relative.split("/")))
        for relative in (
            "analysis/scene_spec.json",
            "analysis/modeling_plan.json",
            "blender/scene.blend",
        )
    }
    result = run_material_repair_session(
        job_root=fixture.root,
        plan_artifact=fixture.plan_artifact,
        source_binding_artifact=fixture.source_artifact,
        preview_size=320,
        created_at=NOW,
    )
    assert calls == [("preflight-request-1", 320, NOW)]
    assert result.attempt_state.state == expected_state
    assert result.attempt_state.latest_preflight == (
        preflight.report_artifact if passed else preflight.failure_artifact
    )
    assert result.attempt_state.pending_approval is None
    assert result.attempt_state.latest_controller_result is None
    assert result.attempt_state.latest_promotion_receipt is None
    assert result.attempt_state.retry_allowed is False
    assert result.attempt_state_artifact.path.endswith("/state-0001.json")
    for relative, digest in protected.items():
        assert sha256_file(fixture.root.joinpath(*relative.split("/"))) == digest
    assert not (fixture.root / "analysis" / "material_plan.json").exists()
    assert not list(fixture.root.rglob("approval_consumptions"))
    assert not list(fixture.root.rglob("controller_executions"))
    assert not list(fixture.root.rglob("material_phase_receipt.json"))


@pytest.mark.parametrize("tampered_artifact", ["plan", "source", "request", "snapshot"])
def test_material_repair_run_exact_loads_every_bound_control_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tampered_artifact: str,
) -> None:
    """Reject changed plan, source, request, or snapshot bytes before preflight runs."""

    fixture = _repair_fixture(tmp_path)
    fixture.paths[tampered_artifact].write_bytes(
        fixture.paths[tampered_artifact].read_bytes() + b"tampered\n"
    )
    called = False

    def _unexpected_preflight(*_args: object, **_kwargs: object) -> None:
        """Record an error if exact-load rejection fails to stop service execution."""

        nonlocal called
        called = True

    monkeypatch.setattr(
        MaterialClosureService,
        "run_preflight",
        _unexpected_preflight,
    )
    with pytest.raises(ValueError, match="artifact changed"):
        run_material_repair_session(
            job_root=fixture.root,
            plan_artifact=fixture.plan_artifact,
            source_binding_artifact=fixture.source_artifact,
            created_at=NOW,
        )
    assert called is False
    assert not (
        fixture.root
        / "production"
        / "material_repair"
        / "repair-session"
        / "attempts"
    ).exists()
