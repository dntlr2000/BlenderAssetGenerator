"""Focused planning tests for the disabled-by-default AQ v2 overlay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from codex_blender_modeler.autonomy_v2 import (
    AutonomyPlanV2,
    RootAuthorizationV2,
    plan_autonomous_static_prop_v2,
    validate_v2_artifact,
)


def _reference(path: Path) -> Path:
    """Create one deterministic local reference without network or user workspace writes."""

    Image.new("RGB", (48, 32), (90, 120, 150)).save(path)
    return path


def test_v2_planning_fails_before_job_creation_while_profile_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public default cannot mutate a workspace for an unverified profile."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    with pytest.raises(PermissionError, match="disabled_experimental"):
        plan_autonomous_static_prop_v2(
            "Create the isolated object.",
            reference_path=_reference(tmp_path / "reference.png"),
            target_subject="the blue object",
            requested_delivery_profiles=["portable_gltf"],
            job_id="aq_v2_disabled",
        )
    assert not (workspace / "aq_v2_disabled").exists()


def test_v2_internal_plan_binds_standard_dispatch_and_phase_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit test override creates exact v2 evidence without approvals or packages."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    result = plan_autonomous_static_prop_v2(
        "Create only the blue handheld prop.",
        reference_path=_reference(tmp_path / "reference.png"),
        target_subject="blue handheld prop",
        requested_delivery_profiles=["portable_gltf", "portable_fbx"],
        job_id="aq_v2_planner",
        allow_disabled_experimental=True,
    )
    assert result["profile_status"] == "disabled_experimental"
    assert result["task_created_by_repository"] is False
    assert result["automatic_user_approval"] is False
    root = workspace / "aq_v2_planner"
    session_id = str(result["session_id"])
    session_root = root / "production" / "autonomy_v2" / session_id
    plan = AutonomyPlanV2.model_validate_json(
        (session_root / "plan.json").read_bytes()
    )
    authorization = RootAuthorizationV2.model_validate_json(
        (session_root / "root_authorization.json").read_bytes()
    )
    assert plan.requested_delivery_profiles == ["portable_gltf", "portable_fbx"]
    assert len(plan.phase_tool_profiles) == 7
    assert authorization.destination_project_write is False
    assert authorization.synthetic_user_approval is False
    assert authorization.reference_content_scope == "primary_object_only"
    for artifact in plan.provenance:
        validate_v2_artifact(root, artifact)

    workflow_request = json.loads(
        (
            root
            / "workflows"
            / str(result["workflow_id"])
            / "request.json"
        ).read_text(encoding="utf-8")
    )
    assert workflow_request["execution_policy"] == "standard"
    assert workflow_request["reference_content_scope"] == "primary_object_only"
    assert workflow_request["target_subject"] == "blue handheld prop"
    assert not list(root.glob("**/approvals/*.json"))
    assert not list((root / "exports" / "packages").glob("**/package_manifest.json"))


def test_v2_long_request_keeps_exact_root_hash_and_bounded_dispatch_purpose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the full initial request authoritative while bounding its dispatch summary."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    external_path = "C:/outside/private/reference.png"
    request = f"Create the isolated prop from {external_path}. " + ("detail " * 220).strip()
    result = plan_autonomous_static_prop_v2(
        request,
        reference_path=_reference(tmp_path / "long-reference.png"),
        target_subject="isolated long-request prop",
        requested_delivery_profiles=["portable_gltf"],
        job_id="aq_v2_long_request",
        allow_disabled_experimental=True,
    )

    root = workspace / "aq_v2_long_request"
    workflow_request = json.loads(
        (
            root
            / "workflows"
            / str(result["workflow_id"])
            / "request.json"
        ).read_text(encoding="utf-8")
    )
    dispatch_request = json.loads(
        (
            root
            / "production"
            / "dispatches"
            / str(result["dispatch_id"])
            / "dispatch_request.json"
        ).read_text(encoding="utf-8")
    )
    expected_sha256 = hashlib.sha256(request.encode("utf-8")).hexdigest()
    assert workflow_request["raw_request"] == request
    assert result["root_authorization"]["original_request_sha256"] == expected_sha256
    assert len(dispatch_request["purpose"]) <= 1000
    assert expected_sha256 in dispatch_request["purpose"]
    assert external_path not in dispatch_request["purpose"]


def test_v2_delivery_scope_is_validated_before_dispatch_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contradictory review/package scope is rejected before creating a job."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    with pytest.raises(ValueError, match="review_only"):
        plan_autonomous_static_prop_v2(
            "Create an object.",
            reference_path=_reference(tmp_path / "reference.png"),
            target_subject="object",
            requested_delivery_profiles=["review_only", "portable_fbx"],
            job_id="aq_v2_invalid_scope",
            allow_disabled_experimental=True,
        )
    assert not (workspace / "aq_v2_invalid_scope").exists()
