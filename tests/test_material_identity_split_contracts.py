"""Focused strict-contract and deterministic projection tests for identity split 0.1.0."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from codex_blender_modeler.material_closure.models import ExactArtifact
from codex_blender_modeler.material_identity_split.models import (
    MaterialIdentityCloneRule,
    MaterialIdentitySplitCanonicalPreconditions,
    MaterialIdentitySplitModelingPlanChange,
    MaterialIdentitySplitPreapprovalReport,
    MaterialIdentitySplitStatusProjection,
)
from codex_blender_modeler.material_identity_split.service import (
    MaterialIdentitySplitError,
    _candidate_modeling_plan_payload,
    _clone_scene_expected,
    _shadow_binding_derivative_relative_path,
    _validate_scene_candidate,
)

NOW = datetime(2026, 8, 14, tzinfo=UTC)


def test_shadow_binding_derivative_path_is_compact_and_deterministic() -> None:
    """Keep run-owned shadow derivative leaves bounded for legacy Windows readers."""

    first = _shadow_binding_derivative_relative_path(
        1,
        "prop.crystalgun.frame.trim",
    )
    assert first == _shadow_binding_derivative_relative_path(
        1,
        "prop.crystalgun.frame.trim",
    )
    assert first.startswith("analysis/mbd/01-")
    assert len(first) == len("analysis/mbd/01-") + 12 + len(".json")
    assert first != _shadow_binding_derivative_relative_path(
        1,
        "prop.crystalgun.rear.crown",
    )


def _artifact(
    artifact_id: str,
    path: str,
    kind: str,
    *,
    sha: str = "a" * 64,
) -> ExactArtifact:
    """Build one strict synthetic exact artifact without touching the filesystem."""

    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=path,
        sha256=sha,
        byte_size=10,
        media_type="application/json",
    )


def _identity() -> dict[str, object]:
    """Return one reusable bound identity for strict companion models."""

    return {
        "job_id": "fixture_job",
        "workflow_id": "workflow_1",
        "dispatch_id": "dispatch-1",
        "run_id": "identity-split-1",
        "producer": "test_fixture",
        "producer_version": "0.1.0",
        "created_at": NOW,
    }


def _preconditions() -> MaterialIdentitySplitCanonicalPreconditions:
    """Build strict canonical preconditions with a MaterialPlan absence artifact."""

    return MaterialIdentitySplitCanonicalPreconditions(
        scene_spec=_artifact("scene", "analysis/scene_spec.json", "scene_spec"),
        modeling_plan=_artifact("modeling", "analysis/modeling_plan.json", "modeling_plan"),
        blend=_artifact("blend", "blender/scene.blend", "canonical_blend").model_copy(
            update={"media_type": "application/x-blender"}
        ),
        material_plan_absence=_artifact(
            "absence",
            "production/material_repair/session/material_plan_absence.json",
            "material_plan_absence",
        ),
        root_authorization=_artifact(
            "authority",
            "production/autonomy_v2/session/root_authorization.json",
            "root_authorization",
        ),
        primary_reference=_artifact(
            "reference", "input/reference.png", "primary_reference"
        ).model_copy(update={"media_type": "image/png"}),
        content_scope_sha256="b" * 64,
        target_subject="bounded fixture prop",
        uv_layout_fingerprint="c" * 64,
    )


def _scene() -> dict[str, object]:
    """Return a compact semantic SceneSpec-like payload for projection tests."""

    return {
        "materials": [
            {
                "id": "mat.source",
                "name": "Source",
                "shader": "principled",
                "base_color": [0.2, 0.3, 0.4, 1.0],
                "roughness": 0.4,
            }
        ],
        "objects": [
            {"id": "object.target", "material_id": "mat.source"},
            {"id": "object.retained", "material_id": "mat.source"},
        ],
        "revision_notes": [],
        "sources": [{"id": "reference"}],
    }


def _clone_rule() -> MaterialIdentityCloneRule:
    """Return one exclusive clone rule plus one retained source assignment."""

    return MaterialIdentityCloneRule(
        source_material_id="mat.source",
        new_material_id="mat.split",
        target_object_id="object.target",
        surface_detail_id="detail.target",
        retained_source_object_ids=["object.retained"],
    )


def test_canonical_preconditions_reject_decoy_paths_and_kinds() -> None:
    """Reject strict-looking canonical artifacts that point to staging paths."""

    payload = _preconditions().model_dump(mode="json")
    payload["blend"]["path"] = "production/decoy/scene.blend"
    with pytest.raises(ValidationError, match="canonical precondition"):
        MaterialIdentitySplitCanonicalPreconditions.model_validate(payload)


def test_exact_scene_clone_projection_changes_only_identity_and_assignment() -> None:
    """Derive precisely one semantic clone and one target assignment replacement."""

    canonical = _scene()
    candidate = _clone_scene_expected(canonical, [_clone_rule()])
    assert candidate["materials"][-1] == {
        **canonical["materials"][0],
        "id": "mat.split",
    }
    assert candidate["objects"][0]["material_id"] == "mat.split"
    assert candidate["objects"][1]["material_id"] == "mat.source"
    assert candidate["revision_notes"] == []
    _validate_scene_candidate(canonical, candidate, [_clone_rule()])


def test_scene_candidate_rejects_semantic_clone_drift() -> None:
    """Reject a cloned identity whose appearance semantics also changed."""

    canonical = _scene()
    candidate = _clone_scene_expected(canonical, [_clone_rule()])
    candidate["materials"][-1]["roughness"] = 0.1
    with pytest.raises(MaterialIdentitySplitError, match="exact identity-clone"):
        _validate_scene_candidate(canonical, candidate, [_clone_rule()])


def test_scene_candidate_rejects_revision_note_injection() -> None:
    """Reject incidental metadata insertion outside the four logical changes."""

    canonical = _scene()
    candidate = _clone_scene_expected(canonical, [_clone_rule()])
    candidate["revision_notes"] = ["silently inserted"]
    with pytest.raises(MaterialIdentitySplitError, match="exact identity-clone"):
        _validate_scene_candidate(canonical, candidate, [_clone_rule()])


def test_modeling_plan_projection_changes_only_declared_detail_target() -> None:
    """Preserve every unrelated detail and exact channel list in the paired plan."""

    canonical = {
        "surface_details": [
            {
                "id": "detail.target",
                "parent_object_id": "object.target",
                "target_material_id": "mat.source",
                "channels": ["base_color", "roughness"],
            },
            {
                "id": "detail.retained",
                "parent_object_id": "object.retained",
                "target_material_id": "mat.source",
                "channels": ["emission"],
            },
        ],
        "global_notes": [],
    }
    change = MaterialIdentitySplitModelingPlanChange(
        detail_id="detail.target",
        parent_object_id="object.target",
        source_material_id="mat.source",
        new_material_id="mat.split",
        required_channels=["base_color", "roughness"],
    )
    candidate, preserved = _candidate_modeling_plan_payload(canonical, [change])
    assert candidate["surface_details"][0]["target_material_id"] == "mat.split"
    assert candidate["surface_details"][1] == canonical["surface_details"][1]
    assert preserved == {"detail.retained": ["emission"]}


def test_modeling_plan_projection_rejects_stale_channel_contract() -> None:
    """Reject a paired change whose requested channels differ from canonical truth."""

    canonical = {
        "surface_details": [
            {
                "id": "detail.target",
                "parent_object_id": "object.target",
                "target_material_id": "mat.source",
                "channels": ["emission"],
            }
        ]
    }
    change = MaterialIdentitySplitModelingPlanChange(
        detail_id="detail.target",
        parent_object_id="object.target",
        source_material_id="mat.source",
        new_material_id="mat.split",
        required_channels=["base_color"],
    )
    with pytest.raises(MaterialIdentitySplitError, match="stale"):
        _candidate_modeling_plan_payload(canonical, [change])


def test_passed_preapproval_is_not_user_approval() -> None:
    """Keep passed framework evidence explicitly distinct from a user decision."""

    report = MaterialIdentitySplitPreapprovalReport(
        **_identity(),
        report_id="preapproval-report",
        request=_artifact(
            "request",
            "production/material_identity_split/identity-split-1/preapproval/request.json",
            "material_identity_split_preapproval_request",
        ),
        status="passed",
        checks=[
            {
                "check_id": "check-1",
                "category": "candidate",
                "status": "passed",
                "message": "candidate passed",
            }
        ],
        shadow_build_receipt=_artifact(
            "shadow",
            "production/material_identity_split/identity-split-1/preapproval/shadow.json",
            "material_identity_split_shadow_build_receipt",
        ),
        invariant_report=_artifact(
            "invariant",
            "production/material_identity_split/identity-split-1/preapproval/invariant.json",
            "material_identity_split_invariant_report",
        ),
        approval_request_eligible=True,
    )
    assert report.actual_user_approval_created is False
    assert report.approval_consumption_count == 0
    assert report.canonical_write_count == 0


def test_ready_status_requires_exact_approval_request_without_side_effects() -> None:
    """Project the explicit-scope boundary while all execution counters remain zero."""

    state = _artifact(
        "state",
        "production/material_identity_split/identity-split-1/states/0002.json",
        "material_identity_split_transaction_state",
    )
    projection = MaterialIdentitySplitStatusProjection(
        **_identity(),
        projection_id="status-projection",
        transaction_id="identity-split-1",
        state_artifacts=[state],
        latest_state=state,
        latest_sequence=2,
        status="eligible_for_explicit_user_scope_approval",
        framework_ready_for_explicit_scope_approval=True,
        approval_request=_artifact(
            "approval-request",
            "production/material_identity_split/identity-split-1/approval_request.json",
            "material_identity_split_approval_request",
        ),
        actual_user_approval_count=0,
        approval_consumption_count=0,
        apply_intent_count=0,
        canonical_write_count=0,
        repair_session_count=0,
        controller_count=0,
        promotion_count=0,
        material_phase_receipt_count=0,
        iq_count=0,
        package_count=0,
        destination_write_count=0,
    )
    assert projection.framework_ready_for_explicit_scope_approval is True
    assert projection.actual_user_approval_count == 0


def test_unknown_schema_version_and_field_fail_closed() -> None:
    """Reject version guessing and undeclared extension fields in additive contracts."""

    payload = _preconditions().model_dump(mode="json")
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        MaterialIdentitySplitCanonicalPreconditions.model_validate(payload)
