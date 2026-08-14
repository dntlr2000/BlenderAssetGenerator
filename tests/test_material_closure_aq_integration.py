"""Focused additive AQ v2 integration tests for Material Closure projections."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.autonomy_v2.controller_bridge import (
    _require_material_status_companions_current,
    get_autonomy_v2_material_closure_status,
)
from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialControllerCompletionV2,
)
from codex_blender_modeler.autonomy_v2.material_phase_service import (
    MaterialPhaseError,
    validate_material_closure_controller_projections_v2,
)
from codex_blender_modeler.material_closure.models import (
    MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES,
    ExactArtifact,
    MaterialDependencyClosure,
    MaterialDependencyEntry,
    MaterialFrameworkFailureReport,
    MaterialPlannedOutput,
)
from codex_blender_modeler.material_closure.state_consistency import (
    _derive_aq_v2_combined_status,
)

NOW = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)


def test_combined_status_prioritizes_raw_terminals_and_blocking_companions() -> None:
    """Never report current when exact raw or companion evidence has stopped execution."""

    assert (
        _derive_aq_v2_combined_status(
            top_level_status="cancelled",
            state_consistent=True,
            material_attempt_state=None,
            blocking_companion_present=False,
        )
        == "cancelled"
    )


def test_combined_status_rejects_stale_companion_state_binding() -> None:
    """Reject a framework companion that points at any non-current AQ state bytes."""

    from codex_blender_modeler.autonomy_v2.models import AQV2Artifact, AutonomyStateV2

    raw_state = AutonomyStateV2.model_construct(
        job_id="job",
        workflow_id="workflow",
        dispatch_id="dispatch",
        session_id="session",
    )
    raw_artifact = AQV2Artifact(
        artifact_id="state-current",
        kind="state",
        path="production/autonomy_v2/session/states/0002.json",
        sha256="a" * 64,
        byte_size=2,
    )
    stale_state = ExactArtifact(
        artifact_id="state-stale",
        kind="current_state",
        path="production/autonomy_v2/session/states/0001.json",
        sha256="b" * 64,
        byte_size=1,
        media_type="application/json",
    )
    failure = MaterialFrameworkFailureReport.model_construct(
        job_id="job",
        workflow_id="workflow",
        dispatch_id="dispatch",
        session_id="session",
        current_state=stale_state,
    )
    with pytest.raises(ValueError, match="current raw AQ state"):
        _require_material_status_companions_current(
            state=raw_state,
            state_artifact=raw_artifact,
            attempt=None,
            consistency=None,
            failure=failure,
            retry=None,
            session=None,
        )
    assert (
        _derive_aq_v2_combined_status(
            top_level_status="running",
            state_consistent=True,
            material_attempt_state="approval_pending",
            blocking_companion_present=True,
        )
        == "blocked"
    )
    assert (
        _derive_aq_v2_combined_status(
            top_level_status="cancelled",
            state_consistent=False,
            material_attempt_state=None,
            blocking_companion_present=True,
        )
        == "inconsistent"
    )
    assert (
        _derive_aq_v2_combined_status(
            top_level_status="completed",
            state_consistent=True,
            material_attempt_state=None,
            blocking_companion_present=False,
        )
        == "completed"
    )
    assert (
        _derive_aq_v2_combined_status(
            top_level_status="running",
            state_consistent=True,
            material_attempt_state="preflight_failed",
            blocking_companion_present=False,
        )
        == "blocked"
    )


def _closure() -> MaterialDependencyClosure:
    """Build one generic closure with exact outputs and structural completion."""

    digest = "a" * 64
    entry = MaterialDependencyEntry(
        entry_id="scene-snapshot",
        role="canonical_scene_spec",
        path="production/material_closure/session/inputs/scene_spec.json",
        sha256="1" * 64,
        byte_size=10,
        source_kind="canonical_artifact",
        required=True,
        producer="tests",
        ownership="staging",
    )
    observation = MaterialDependencyEntry(
        entry_id="material-observation",
        role="canonical_material_plan_observation",
        path="analysis/material_plan.json",
        sha256="2" * 64,
        byte_size=10,
        source_kind="canonical_artifact",
        required=True,
        producer="tests",
        ownership="canonical",
    )
    baseline = MaterialDependencyEntry(
        entry_id="material-baseline",
        role="material_plan_baseline_snapshot",
        path="production/material_closure/session/inputs/material_plan.json",
        sha256="2" * 64,
        byte_size=10,
        source_kind="rollback_evidence",
        required=True,
        producer="tests",
        ownership="staging",
    )
    candidate = MaterialDependencyEntry(
        entry_id="candidate-plan",
        role="candidate_material_plan",
        path="production/material_closure/session/candidate/material_plan.json",
        sha256="3" * 64,
        byte_size=10,
        source_kind="staging_artifact",
        required=True,
        producer="tests",
        ownership="staging",
    )
    source_graph = MaterialDependencyEntry(
        entry_id="source-graph",
        role="source_material_graph",
        path="production/material_closure/session/graph/source.json",
        sha256="5" * 64,
        byte_size=10,
        source_kind="staging_artifact",
        required=True,
        producer="tests",
        ownership="staging",
    )
    rebind_plan = MaterialDependencyEntry(
        entry_id="rebind-plan",
        role="material_graph_rebinding_plan",
        path="production/material_closure/session/graph/rebinding_plan.json",
        sha256="6" * 64,
        byte_size=10,
        source_kind="derived_evidence",
        required=True,
        producer="tests",
        ownership="staging",
    )
    rebind_receipt = MaterialDependencyEntry(
        entry_id="rebind-receipt",
        role="material_graph_rebinding_receipt",
        path="production/material_closure/session/graph/rebinding_receipt.json",
        sha256="7" * 64,
        byte_size=10,
        source_kind="derived_evidence",
        required=True,
        producer="tests",
        ownership="staging",
    )
    rebound_graph = MaterialDependencyEntry(
        entry_id="rebound-graph",
        role="rebound_material_graph",
        path="production/material_closure/session/graph/rebound.json",
        sha256="4" * 64,
        byte_size=10,
        source_kind="derived_evidence",
        required=True,
        producer="tests",
        ownership="staging",
    )
    source_binding = ExactArtifact(
        artifact_id="closure-source-binding",
        kind="material_closure_source_binding",
        path="production/material_closure/session/source_binding.json",
        sha256="8" * 64,
        byte_size=10,
        media_type="application/json",
    )
    entries = [
        entry,
        observation,
        baseline,
        candidate,
        source_graph,
        rebind_plan,
        rebind_receipt,
        rebound_graph,
    ]
    existing_roles = {item.role for item in entries}
    for index, role in enumerate(
        sorted(MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES - existing_roles), start=10
    ):
        entries.append(
            MaterialDependencyEntry(
                entry_id=f"root-{role}",
                role=role,
                path=f"production/material_closure/session/common/{role}.json",
                sha256=f"{index:x}"[-1] * 64,
                byte_size=10,
                source_kind="policy_evidence",
                required=True,
                producer="tests",
                ownership="staging",
            )
        )
    outputs = [
        MaterialPlannedOutput(
            output_id="material-plan",
            output_kind="material_plan",
            path="production/autonomy_v2/session/outputs/material_plan.json",
            verification="exact_hash",
            sha256="3" * 64,
            media_type="application/json",
        ),
        MaterialPlannedOutput(
            output_id="material-graph",
            output_kind="material_graph",
            path="production/autonomy_v2/session/outputs/material_graph.json",
            verification="exact_hash",
            sha256="4" * 64,
            media_type="application/json",
        ),
        MaterialPlannedOutput(
            output_id="completion",
            output_kind="controller_completion",
            path="production/autonomy_v2/session/outputs/completion.json",
            verification="structural_binding",
            expected_schema_version="0.2.0",
            expected_field_bindings={"session_id": "session"},
            media_type="application/json",
        ),
    ]
    provisional = MaterialDependencyClosure.model_construct(
        closure_id="closure",
        closure_sha256=digest,
        job_id="job",
        workflow_id="workflow",
        dispatch_id="dispatch",
        session_id="session",
        producer="tests",
        producer_version="0.1.0",
        created_at=NOW,
        source_binding=source_binding,
        entries=entries,
        planned_outputs=outputs,
        rollback_baseline=ExactArtifact(
            artifact_id=baseline.entry_id,
            kind="rollback_baseline",
            path=baseline.path,
            sha256=baseline.sha256,
            byte_size=baseline.byte_size,
            media_type="application/json",
        ),
    )
    from codex_blender_modeler.material_closure.models import _closure_payload_digest

    return MaterialDependencyClosure.model_validate(
        {
            **provisional.model_dump(mode="python"),
            "closure_sha256": _closure_payload_digest(
                entries, outputs, source_binding
            ),
        }
    )


def test_closure_projection_is_identical_for_request_and_completion() -> None:
    """Accept only one complete immutable projection and structural completion binding."""

    closure = _closure()
    immutable_map = closure.project_immutable_input_map()
    validate_material_closure_controller_projections_v2(
        request_immutable_input_sha256=immutable_map,
        request_expected_output_sha256=closure.project_planned_output_map(),
        completion_immutable_input_sha256=immutable_map,
        completion_payload={"session_id": "session"},
        closure=closure,
    )


def test_reduced_completion_map_fails_closed_before_promotion() -> None:
    """Reject a controller completion that silently omits one closure dependency."""

    closure = _closure()
    immutable_map = closure.project_immutable_input_map()
    reduced_map = dict(immutable_map)
    reduced_map.pop(next(iter(reduced_map)))
    with pytest.raises(MaterialPhaseError, match="complete closure projection"):
        validate_material_closure_controller_projections_v2(
            request_immutable_input_sha256=immutable_map,
            request_expected_output_sha256=closure.project_planned_output_map(),
            completion_immutable_input_sha256=reduced_map,
            completion_payload={"session_id": "session"},
            closure=closure,
        )


def test_structural_completion_binding_rejects_wrong_session() -> None:
    """Reject completion bytes that target another session despite complete input maps."""

    closure = _closure()
    immutable_map = closure.project_immutable_input_map()
    with pytest.raises(MaterialPhaseError, match="completion payload"):
        validate_material_closure_controller_projections_v2(
            request_immutable_input_sha256=immutable_map,
            request_expected_output_sha256=closure.project_planned_output_map(),
            completion_immutable_input_sha256=immutable_map,
            completion_payload={"session_id": "other-session"},
            closure=closure,
        )


def test_closure_pairs_live_observation_with_run_owned_baseline() -> None:
    """Keep prewrite CAS evidence and an immutable post-promotion replay baseline."""

    closure = _closure()
    projection = closure.project_immutable_input_map()
    assert projection["analysis/material_plan.json"] == "2" * 64
    assert (
        projection["production/material_closure/session/inputs/material_plan.json"]
        == "2" * 64
    )


def test_closure_completion_accepts_run_owned_material_baseline() -> None:
    """Keep the legacy completion readable while allowing stabilized run-owned inputs."""

    closure = _closure()
    immutable_map = closure.project_immutable_input_map()
    MaterialControllerCompletionV2(
        completion_id="completion",
        job_id="job",
        workflow_id="workflow",
        dispatch_id="dispatch",
        session_id="session",
        execution_id="execution",
        assignment_sha256="5" * 64,
        tool_profile_sha256="6" * 64,
        immutable_input_sha256=immutable_map,
        source_scene_spec_sha256="1" * 64,
        source_material_plan_sha256="2" * 64,
        material_dependency_closure_sha256=closure.closure_sha256,
        material_plan_path="production/autonomy_v2/session/outputs/material_plan.json",
        material_plan_sha256="3" * 64,
        material_graph_path="production/autonomy_v2/session/outputs/material_graph.json",
        material_graph_sha256="4" * 64,
    )


def test_closure_promotion_revalidates_every_authority_under_host_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep closure, approval consumption, controller, and host promotion under one lock."""

    import codex_blender_modeler.autonomy_v2.material_phase_service as service

    lock_active = False
    events: list[str] = []

    @contextmanager
    def host_lock(
        job_id: str,
        session_id: str,
        *,
        ttl_seconds: int,
    ) -> Iterator[None]:
        """Expose one deterministic host-lock lifetime to every revalidation seam."""

        nonlocal lock_active
        assert (job_id, session_id, ttl_seconds) == ("job", "session", 3600)
        lock_active = True
        events.append("lock-enter")
        try:
            yield
        finally:
            events.append("lock-exit")
            lock_active = False

    def require_lock(event: str) -> None:
        """Record one validation only while the canonical host lock is active."""

        assert lock_active is True
        events.append(event)

    plan = SimpleNamespace(job_id="job", session_id="session")
    state = SimpleNamespace()
    budget = SimpleNamespace()
    result_artifact = SimpleNamespace()
    boundary_artifact = SimpleNamespace()
    consumption_artifact = SimpleNamespace()
    boundary = SimpleNamespace()
    closure = SimpleNamespace()
    request_artifact = SimpleNamespace()
    result = SimpleNamespace(request=SimpleNamespace())
    bundle = SimpleNamespace()
    promoted = (SimpleNamespace(), SimpleNamespace())

    def validate_boundary(*_args: object, **kwargs: object) -> tuple[object, object]:
        """Require full current-boundary replay after the lock has been acquired."""

        require_lock("boundary")
        assert kwargs["state"] is state
        assert kwargs["require_current_canonical"] is True
        return boundary, closure

    def read_result(*_args: object, **_kwargs: object) -> object:
        """Re-read the exact controller result while canonical state cannot change."""

        require_lock("result")
        return result

    def rebind_request(*_args: object, **_kwargs: object) -> object:
        """Rehash the nested controller request inside the same critical section."""

        require_lock("request")
        return request_artifact

    def validate_consumption(*_args: object, **_kwargs: object) -> object:
        """Revalidate the exact already-published approval consumption under lock."""

        require_lock("consumption")
        return SimpleNamespace()

    def load_bundle(*_args: object, **_kwargs: object) -> object:
        """Re-read controller outputs only after current approval evidence passes."""

        require_lock("controller")
        return bundle

    def validate_bundle(*_args: object, **_kwargs: object) -> None:
        """Bind the locked controller bundle back to the same exact closure."""

        require_lock("controller-closure")

    def promote(*_args: object, **kwargs: object) -> tuple[object, object]:
        """Enter existing host promotion without reacquiring or releasing the lock."""

        require_lock("promotion")
        assert kwargs["canonical_lock_held"] is True
        return promoted

    monkeypatch.setattr(service, "canonical_scene_spec_write_lock", host_lock)
    monkeypatch.setattr(
        service,
        "ensure_contained_production_path",
        lambda *_args, **_kwargs: tmp_path,
    )
    monkeypatch.setattr(
        service,
        "validate_material_closure_promotion_boundary_v2",
        validate_boundary,
    )
    monkeypatch.setattr(service, "_read_exact_model", read_result)
    monkeypatch.setattr(service, "_controller_to_aq", rebind_request)
    monkeypatch.setattr(
        service,
        "validate_material_appearance_approval_consumption_v2",
        validate_consumption,
    )
    monkeypatch.setattr(service, "_load_controller_material_bundle", load_bundle)
    monkeypatch.setattr(
        service,
        "_validate_controller_bundle_against_closure",
        validate_bundle,
    )
    monkeypatch.setattr(
        service,
        "_validate_and_promote_material_controller_result_v2",
        promote,
    )
    assert service.validate_and_promote_material_closure_controller_result_v2(
        tmp_path,
        plan,
        budget,
        state,
        result_artifact,
        boundary_artifact=boundary_artifact,
        approval_consumption_artifact=consumption_artifact,
    ) == promoted
    assert events == [
        "lock-enter",
        "boundary",
        "result",
        "request",
        "consumption",
        "controller",
        "controller-closure",
        "promotion",
        "lock-exit",
    ]


def test_combined_status_preserves_old_blocked_raw_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report a historical terminal without requiring new companion files or mutation."""

    raw_state = {
        "schema_version": "0.2.0",
        "contract_id": "state-session-0003",
        "job_id": "job",
        "workflow_id": "workflow",
        "dispatch_id": "dispatch",
        "session_id": "session",
        "input_sha256": "1" * 64,
        "source_fingerprint": "2" * 64,
        "producer": "tests",
        "producer_version": "0.2.0",
        "provenance": [
            {
                "artifact_id": "plan",
                "kind": "plan",
                "path": "production/autonomy_v2/session/plan.json",
                "sha256": "3" * 64,
                "byte_size": 1,
            }
        ],
        "created_at": NOW.isoformat(),
        "state_id": "state-session-0003",
        "plan": {
            "artifact_id": "plan",
            "kind": "plan",
            "path": "production/autonomy_v2/session/plan.json",
            "sha256": "3" * 64,
            "byte_size": 1,
        },
        "sequence": 3,
        "phase": "terminal",
        "status": "blocked",
        "next_action": "none",
        "quality_terminal": None,
        "source_freeze": None,
        "delivery_plan": None,
        "delivery_terminal": None,
        "delivery_results": [],
        "budget_usage": {},
        "previous_state_sha256": "4" * 64,
        "terminal_reason": "framework material closure incomplete",
    }
    raw_artifact = {
        "artifact_id": "state-session-0003",
        "kind": "state",
        "path": "production/autonomy_v2/session/states/0003.json",
        "sha256": "5" * 64,
        "byte_size": 1,
    }
    import codex_blender_modeler.autonomy_v2.controller_bridge as bridge

    monkeypatch.setattr(
        bridge,
        "get_autonomy_v2_status",
        lambda _job_id, _session_id: {
            "state": raw_state,
            "state_artifact": raw_artifact,
        },
    )
    monkeypatch.setattr(bridge, "job_dir", lambda _job_id: tmp_path)
    status = get_autonomy_v2_material_closure_status("job", "session")
    assert status["combined_status"] == "blocked"
    assert status["raw_state_preserved"] is True
    assert status["raw_aq"]["state"] == raw_state
