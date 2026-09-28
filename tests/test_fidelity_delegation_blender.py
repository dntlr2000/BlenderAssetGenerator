"""Actual Blender native delegation transport; synthetic observations are not art acceptance."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import test_autonomy_v2_candidate_validation_blender as geometry
import test_reference_fidelity_geometry_blender as bound_geometry
from test_reference_fidelity import hypothesis
from test_reference_fidelity_aq_blender_vertical import (
    _run_material_round,
    _write_fixture_reference_mask,
)

from codex_blender_modeler.autonomy_v2 import delegation_service as service
from codex_blender_modeler.autonomy_v2.controller_bridge import _session_bundle
from codex_blender_modeler.autonomy_v2.delegation_models import (
    DelegationAsset,
    DelegationBindingV01,
    DelegationSlot,
    FidelityCampaignDelegationV01,
)
from codex_blender_modeler.autonomy_v2.models import AutonomyBudgetV04
from codex_blender_modeler.autonomy_v2.quality_revision_models import parse_quality_revision_loop
from codex_blender_modeler.autonomy_v2.quality_revision_service import render_quality_evidence
from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.comparison_lighting import (
    CAMERA_STUDIO_PROFILE,
    lighting_implementation_sha256,
)
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.reference_fidelity.models import FidelityArtifact
from codex_blender_modeler.reference_fidelity.service import publish

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE") != "1",
    reason="requires explicit Blender 5.0.1 native delegation smoke",
)


def test_delegated_native_geometry_material_closure_and_seven_pass_qa(tmp_path, monkeypatch):
    """Run real promotion/closure/QA under parent policy and reject changed authority pre-render."""
    old_plan = geometry.plan_autonomous_static_prop_v2
    old_bind = bound_geometry.bind_quality_revision_loop
    workspace = tmp_path / "workspaces"
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(
            repo_root=tmp_path,
            workspace_root=workspace,
        ),
    )
    monkeypatch.setattr(service, "_validate_source", lambda _contract: None)
    selected = {}

    def delegated_plan(request, **kwargs):
        """Add a synthetic parent while retaining native planning and budgets."""
        reference, job = kwargs["reference_path"], kwargs["job_id"]
        ref = service.exact_artifact(tmp_path, reference, "reference_image")
        template = hypothesis()
        observed = template.model_copy(
            update={
                "job_id": job,
                "reference": FidelityArtifact(path=ref.path, sha256=ref.sha256),
                "observations": [
                    template.observations[0].model_copy(
                        update={
                            "region": (0.2, 0.2, 0.8, 0.8),
                            "description": (
                                "Uniform fixture region; test transport, not shape truth."
                            ),
                            "uncertainty": "Authored test hull; no reference fidelity claimed.",
                        }
                    )
                ],
                "requirements": [
                    template.requirements[0].model_copy(update={"target_ids": ["asset.hull"]})
                ],
                "camera": template.camera.model_copy(
                    update={
                        "camera_fingerprint": camera_fingerprint(
                            geometry._scene_v03(job, ref.path)["camera"]
                        ),
                    }
                ),
            }
        )
        path = tmp_path / "frozen_hypothesis.json"
        path.write_text(observed.model_dump_json(), encoding="utf-8")
        hyp_ref = service.exact_artifact(tmp_path, path, "modeling_hypothesis")
        slot = DelegationSlot(
            initial_object_limit=1,
            correction_object_limit=1,
            structural_rounds=3,
            parametric_rounds=0,
            material_corrections=2,
            strategy_switches=1,
        )
        asset = DelegationAsset(
            asset_id="hull",
            target_subject=kwargs["target_subject"],
            reference=ref,
            hypothesis=hyp_ref,
            prior_history=[],
            prior_initial_candidates=0,
            inherited_evidence=[hyp_ref],
            slots=[slot],
        )
        contract = FidelityCampaignDelegationV01(
            delegation_id="native-blender-fixture",
            user_request=request,
            source_manifest=hyp_ref,
            baseline=hyp_ref,
            assets=[asset],
            total_budget=asset.cost(),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        planned = service.plan_fidelity_delegation(contract)
        digest = planned["artifact"]["sha256"]
        service.approve_fidelity_delegation(
            contract.delegation_id,
            contract_sha256=digest,
            exact_user_text=f"Synthetic fixture approval {digest}",
        )
        scope = service.issue_fidelity_scope(
            contract.delegation_id,
            asset_id="hull",
            job_id=job,
            strategy=observed.authoring_strategy,
        )
        binding = DelegationBindingV01.model_validate(scope["binding"])
        stage = service._directory(binding.delegation_id) / "staging/0001/0000/hull.json"
        stage.parent.mkdir(parents=True)
        stage.write_text(
            json.dumps(geometry._scene_v03(job, "input/reference.png")), encoding="utf-8"
        )
        service.publish_fidelity_preparation(binding, [stage])
        kwargs["requested_delivery_profiles"] = ["portable_gltf"]
        kwargs["delegation_binding"] = binding
        kwargs["fidelity_budget_plan"] = service._bound_scope(binding)[2].funding
        selected["binding"] = binding
        return old_plan(request, **kwargs)

    def selected_lighting(job_id, session_id, plan_path):
        """Select frozen lighting in a new proposal and preserve the legacy proposal."""
        root = workspace / job_id
        raw = json.loads(plan_path.read_bytes())
        raw.update(
            schema_version="0.4.0",
            comparison_lighting_profile=CAMERA_STUDIO_PROFILE,
            lighting_implementation_sha256=lighting_implementation_sha256(),
        )
        loop = parse_quality_revision_loop(json.dumps(raw))
        candidate = root / "fidelity/delegated_loop_proposal.json"
        publish(root, candidate, loop)
        return old_bind(job_id, session_id, candidate)

    monkeypatch.setattr(geometry, "plan_autonomous_static_prop_v2", delegated_plan)
    monkeypatch.setattr(bound_geometry, "bind_quality_revision_loop", selected_lighting)
    root, session = bound_geometry._bound_fidelity_geometry_fixture(
        tmp_path, monkeypatch, funded=True
    )
    _run_material_round(root, session)
    _write_fixture_reference_mask(root, root / "input/reference.png")
    before = {
        name: sha256_file(root / name)
        for name in ("analysis/scene_spec.json", "blender/scene.blend")
    }
    result = render_quality_evidence(root.name, session, run_id="delegated-seven-passes")
    assert len(result["render_evidence"]["passes"]) == 7
    assert all(sha256_file(root / name) == digest for name, digest in before.items())
    assert isinstance(_session_bundle(root.name, session)[3], AutonomyBudgetV04)
    status = service.get_fidelity_delegation_status(selected["binding"].delegation_id)
    assert status["reserved"]["candidates"] == 1 and status["human_beauty_accepted"] == 0
    scope = service._directory(selected["binding"].delegation_id) / "scopes/0001.json"
    scope.write_bytes(scope.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="scope hash changed"):
        render_quality_evidence(root.name, session, run_id="forbidden-after-change")
    assert not (root / "qa/runs/forbidden-after-change").exists()
