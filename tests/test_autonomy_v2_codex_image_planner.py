"""Focused tests for the explicit AQ v2 Codex ImageGen overlay planner."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from codex_blender_modeler.autonomy_v2.codex_image_phase_service import (
    get_codex_image_phase_status,
)
from codex_blender_modeler.autonomy_v2.codex_image_planner import (
    plan_autonomous_static_prop_v2_codex_imagegen,
)
from codex_blender_modeler.autonomy_v2.profiles import autonomy_v2_profile_status


def test_codex_image_planner_requires_both_explicit_opt_ins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject the companion before creating a base job when either opt-in is absent."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), (32, 64, 96)).save(reference)
    with pytest.raises(PermissionError, match="explicit provider"):
        plan_autonomous_static_prop_v2_codex_imagegen(
            "Create the isolated test prop.",
            reference_path=reference,
            target_subject="test prop",
            requested_delivery_profiles=["review_only"],
            target_material_ids=["material-main"],
            semantic_roles=["primary-surface"],
            allowed_output_roles=["base_color"],
            generation_intent="generated_surface_swatch_v1",
            prompt_template_id="surface-swatch-v1",
            job_id="codex-image-no-opt-in",
            codex_imagegen_allowed=False,
            allow_disabled_experimental=True,
        )
    assert not workspace.exists()


def test_codex_image_planner_preserves_local_base_and_initializes_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create exact additive evidence while leaving the local AQ v2 profile unchanged."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), (32, 64, 96)).save(reference)
    result = plan_autonomous_static_prop_v2_codex_imagegen(
        "Create the isolated test prop.",
        reference_path=reference,
        target_subject="test prop",
        requested_delivery_profiles=["review_only"],
        target_material_ids=["material-main"],
        semantic_roles=["primary-surface"],
        allowed_output_roles=["base_color"],
        generation_intent="generated_surface_swatch_v1",
        prompt_template_id="surface-swatch-v1",
        requested_candidate_count=1,
        image_width=64,
        image_height=64,
        job_id="codex-image-planned",
        codex_imagegen_allowed=True,
        allow_disabled_experimental=True,
    )
    assert result["profile_status"] == "disabled_experimental"
    assert result["controller_required"] is True
    assert result["repository_can_spawn_codex_task"] is False
    assert result["autonomous_daemon"] is False
    assert result["network_required"] is False
    assert result["api_key_required"] is False
    assert result["base"]["profile"]["profile_id"] == "autonomous_static_prop_v2"
    assert autonomy_v2_profile_status()["profile_id"] == "autonomous_static_prop_v2"
    root = workspace / "codex-image-planned"
    status = get_codex_image_phase_status(root, str(result["session_id"]))
    assert status["profile"]["status"] == "disabled_experimental"
    assert status["state"]["status"] == "planned"
    assert status["waiting_for_controller"] is False
    assert status["actual_codex_imagegen_execution_verified"] is False
