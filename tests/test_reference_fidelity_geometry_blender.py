"""Opt-in initial geometry promotion with a fidelity hypothesis; no visual acceptance."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import test_autonomy_v2_candidate_validation_blender as geometry_smoke
from PIL import ImageDraw
from test_reference_fidelity import hypothesis

from codex_blender_modeler.autonomy_v2.approval_policy_service import _load_approval_boundary
from codex_blender_modeler.autonomy_v2.candidate_validation_models import (
    GeometryCandidateValidationReceiptV2,
)
from codex_blender_modeler.autonomy_v2.controller_bridge import _session_bundle
from codex_blender_modeler.autonomy_v2.quality_revision_models import (
    AQQualityRevisionLoopV01,
    RevisionCostV01,
)
from codex_blender_modeler.autonomy_v2.quality_revision_service import (
    bind_quality_revision_loop,
    load_optional_loop,
)
from codex_blender_modeler.production.controller_executor.models import ControllerExecutionRequest
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.reference_fidelity.models import (
    FidelityArtifact,
    ReferenceMaskLabelObservationV02,
    ReferenceMaskSeedEvidenceV01,
    ReferenceMaskSeedEvidenceV02,
    ReferenceMaskSeedV01,
    ReferenceObservation,
)
from codex_blender_modeler.reference_fidelity.service import artifact_at, publish

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE") != "1",
    reason="set CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE=1 for actual fidelity geometry smoke",
)


def _bound_fidelity_geometry_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, funded: bool = False,
    segmentation_seed: bool = False,
    segmentation_constraints: bool = False,
) -> tuple[Path, str]:
    """Build a legacy/funded AQ fixture with optional observed V0.1 seeds or V0.2 trimap."""

    segmentation_seed = segmentation_seed or segmentation_constraints

    old_modeling = geometry_smoke._modeling_plan
    old_advance = geometry_smoke._advance_reference
    old_image_new = geometry_smoke.Image.new
    old_plan = geometry_smoke.plan_autonomous_static_prop_v2

    def funded_plan(request, **kwargs):
        """Select the finite companion before creating any test-owned root authorization."""

        from codex_blender_modeler.autonomy_v2.fidelity_budget_service import (
            plan_fidelity_budget_epoch,
        )

        kwargs["fidelity_budget_plan"] = plan_fidelity_budget_epoch(
            epoch_id="fixture-epoch", job_id=kwargs["job_id"],
            reference_path=kwargs["reference_path"],
            initial_object_limit=1, correction_object_limit=1,
        )
        return old_plan(request, **kwargs)

    def informative_reference(mode, size, color=0):
        """Give the vertical fixture measurable image detail instead of missing evidence."""

        image = old_image_new(mode, size, color)
        if mode == "RGB" and size == (32, 32):
            pixels = image.load()
            for y in range(size[1]):
                for x in range(size[0]):
                    offset = 52 if (x // 4 + y // 4) % 2 else 0
                    pixels[x, y] = (
                        (210, 210, 210) if segmentation_seed and not (7 <= x < 25 and 7 <= y < 25)
                        else (48 + offset, 96 + offset, 144 - offset // 2)
                    )
        return image

    def spatial_modeling(job_id, note):
        """Declare one authored inferred spatial hull using the existing ModelingPlan contract."""

        result = old_modeling(job_id, note)
        result["assembly_consistency_policy"] = "spatial_v1"
        result["assembly_frame"] = {
            "root_object_id": "asset.hull",
            "longitudinal_axis": "Y",
            "lateral_axis": "X",
            "vertical_axis": "Z",
            "evidence_status": "inferred",
        }
        result["objects"][0]["assembly_role"] = "root"
        result["global_notes"] = ["Fixture-only authored hull; no actual reference quality claim."]
        return result

    def bind_then_advance(root, session_id):
        """Bind exact observation/segmentation companions before real fixture geometry effects."""

        job_id = root.name
        _root, _session, plan, _budget, _state, state_artifact = _session_bundle(job_id, session_id)
        boundary = _load_approval_boundary(job_id, session_id)
        source = boundary[2].primary_reference
        template = hypothesis()
        camera = geometry_smoke._scene_v03(job_id, source.path)["camera"]
        observed = template.model_copy(
            update={
                "job_id": job_id,
                "reference": FidelityArtifact(path=source.path, sha256=source.sha256),
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
                    template.requirements[0].model_copy(
                        update={
                            "target_ids": ["asset.hull"],
                        }
                    )
                ],
                "camera": template.camera.model_copy(
                    update={
                        "camera_fingerprint": camera_fingerprint(camera),
                    }
                ),
            }
        )
        if segmentation_seed:
            patch = ReferenceObservation(
                observation_id="fixture-interior", region=(.4, .4, .6, .6), status="observed",
                confidence=.9, description="Known foreground in the independent synthetic image.",
                uncertainty="Synthetic transport evidence; never a real asset judgment.",
            )
            observed = observed.model_copy(update={
                "observations": [*observed.observations, patch],
                "reference_mask_seed_evidence": ReferenceMaskSeedEvidenceV01(
                    job_id=job_id, reference=observed.reference,
                    seeds=[ReferenceMaskSeedV01(object_id="asset.hull", source_id="ref.main",
                        observation_id=patch.observation_id, bbox_norm=patch.region,
                        confidence=patch.confidence)],
                ),
            })
        if segmentation_constraints:
            background = ReferenceObservation(
                observation_id="fixture-background", region=(.03, .03, .12, .12),
                status="observed", confidence=.9,
                description="Known exterior background in the independent synthetic reference.",
                uncertainty="Synthetic transport fixture, not a real asset quality judgment.",
            )
            trimap = old_image_new("L", (32, 32), 0)
            labels = ImageDraw.Draw(trimap)
            labels.rectangle((5, 5, 26, 26), fill=85)
            labels.rectangle((7, 7, 24, 24), fill=170)
            labels.rectangle((9, 9, 22, 22), fill=255)
            trimap_path = root / "fidelity/reference-trimap.png"
            trimap_path.parent.mkdir(parents=True, exist_ok=True)
            trimap.save(trimap_path)
            selected = ReferenceMaskSeedEvidenceV02(
                **observed.reference_mask_seed_evidence.model_dump(exclude={"schema_version"}),
                trimap=artifact_at(root, trimap_path), reference_resolution=(32, 32),
                reference_content_scope="primary_object_only", subject_object_ids=["asset.hull"],
                label_observations=[ReferenceMaskLabelObservationV02(
                    observation_id=item.observation_id, bbox_norm=item.region,
                    confidence=item.confidence, label=label,
                ) for item, label in ((patch, "foreground"), (background, "background"))],
            )
            observed = observed.model_copy(update={
                "observations": [*observed.observations, background],
                "reference_mask_seed_evidence": selected,
            })
        observed_ref = publish(root, root / "fidelity/hypothesis.json", observed)
        loop = AQQualityRevisionLoopV01(
            job_id=job_id,
            session_id=session_id,
            root_authorization=FidelityArtifact(
                path=plan.root_authorization.path, sha256=plan.root_authorization.sha256
            ),
            approval_envelope=FidelityArtifact(path=boundary[9].path, sha256=boundary[9].sha256),
            initial_state=FidelityArtifact(path=state_artifact.path, sha256=state_artifact.sha256),
            hypothesis=observed_ref,
            structural_revision_limit=2,
            local_revision_limit=2,
            cost_limit=RevisionCostV01(
                materializations=2, builds=4, qa_runs=4, closure_runs=2, promotions=4
            ),
            allow_disabled_experimental=True,
        )
        if funded:
            from codex_blender_modeler.autonomy_v2.quality_revision_models import (
                AQQualityRevisionLoopV03,
            )

            epoch = _budget.funding
            loop = AQQualityRevisionLoopV03.model_validate({
                **loop.model_dump(), "schema_version": "0.3.0", "funding": epoch,
                "structural_revision_limit": epoch.structural_rounds,
                "initial_pipeline_reserve": RevisionCostV01(**epoch.initial_cost()),
                "cost_limit": RevisionCostV01(**epoch.revision_cost()),
            })
        proposal = root / "fidelity/proposed_loop.json"
        publish(root, proposal, loop)
        bind_quality_revision_loop(job_id, session_id, proposal)
        old_advance(root, session_id)

    monkeypatch.setattr(geometry_smoke, "_modeling_plan", spatial_modeling)
    monkeypatch.setattr(geometry_smoke, "_advance_reference", bind_then_advance)
    monkeypatch.setattr(geometry_smoke.Image, "new", informative_reference)
    if funded:
        monkeypatch.setattr(geometry_smoke, "plan_autonomous_static_prop_v2", funded_plan)
    # Reuse the full legacy smoke's real controller/policy/build/idempotent promotion assertions.
    geometry_smoke.test_geometry_controller_candidate_builds_and_promotes_exactly(
        tmp_path, monkeypatch
    )
    root = tmp_path / "workspaces/aqv2_candidate_smoke"
    sessions = list((root / "production/autonomy_v2").iterdir())
    assert len(sessions) == 1
    _, _, _plan, _budget, state, _artifact = _session_bundle(root.name, sessions[0].name)
    receipt = GeometryCandidateValidationReceiptV2.model_validate_json(
        (root / state.provenance[-1].path).read_bytes()
    )
    request = ControllerExecutionRequest.model_validate_json(
        (root / receipt.controller_request.path).read_bytes()
    )
    loop, loop_artifact = load_optional_loop(root, sessions[0].name)
    assert {loop_artifact.path, loop.hypothesis.path} <= {
        item.path for item in request.immutable_inputs
    }
    assert state.source_freeze is None and state.quality_terminal is None
    return root, sessions[0].name


def test_bound_fidelity_observations_reach_actual_geometry_promotion(tmp_path, monkeypatch):
    """Exercise real planning, policy, build and promotion with the additive authoring gate."""

    _bound_fidelity_geometry_fixture(tmp_path, monkeypatch)
