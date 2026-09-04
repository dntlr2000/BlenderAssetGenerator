"""Reference-fidelity coverage, defect routing and fair before/after comparison controls."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from codex_blender_modeler.blender_artifacts import stable_json_digest
from codex_blender_modeler.reference_fidelity.models import (
    CameraHypothesis,
    FeatureAssessment,
    FeatureRequirement,
    FidelityArtifact,
    ModelingHypothesisV01,
    ReferenceObservation,
    RenderEvidenceV01,
    VisualFindingSetV01,
)
from codex_blender_modeler.reference_fidelity.service import compare_evaluations, evaluate_review


def artifact(name: str) -> FidelityArtifact:
    """Create deterministic contract-only evidence, without claiming Blender execution."""

    return FidelityArtifact(path=f"fixtures/{name}.json", sha256=stable_json_digest(name))


def hypothesis(kind: str = "volume", representation: str = "solid") -> ModelingHypothesisV01:
    """Build an independent observed structural requirement for positive/negative controls."""

    return ModelingHypothesisV01(
        job_id="fidelity_fixture",
        hypothesis_id="hypothesis",
        reference=artifact("reference"),
        observations=[
            ReferenceObservation(
                observation_id="visible-mass",
                region=(0.0, 0.0, 1.0, 1.0),
                description="Visible top and side meet along a continuous longitudinal edge.",
                status="observed",
                confidence=0.9,
                uncertainty="Hidden back face is inferred.",
            )
        ],
        requirements=[
            FeatureRequirement(
                feature_id="form",
                observation_ids=["visible-mass"],
                target_ids=["body"],
                kind=kind,
                expected="Continuous top, side and end surfaces enclose the main volume.",
                comparison="Compare visible planes and normal/depth, not only the outline.",
            )
        ],
        camera=CameraHypothesis(
            camera_fingerprint=stable_json_digest("camera"),
            origin="visual_hypothesis",
            evidence_observation_ids=["visible-mass"],
            rationale="Three visible plane directions.",
            uncertainty="Single image; focal distance and absolute scale remain ambiguous.",
        ),
        representation=representation,
        volume_and_sections="Long tapering rectangular volume.",
        part_relations="Single continuous body; no separate parts are required.",
        hidden_geometry_assumptions=["Back surface is an inferred continuation."],
        authoring_strategy="section-loft",
    )


def review(plan: ModelingHypothesisV01, outcome: str | None) -> VisualFindingSetV01:
    """Build a nonhuman rating with all seven pass bindings, or deliberate missing coverage."""

    return VisualFindingSetV01(
        job_id=plan.job_id,
        review_id="review",
        hypothesis=artifact("hypothesis"),
        reference=plan.reference,
        evidence=RenderEvidenceV01(
            scene_spec=artifact("scene"),
            qa_request=artifact("request"),
            qa_report=artifact("report"),
            pass_manifest=artifact("manifest"),
            camera_fingerprint=plan.camera.camera_fingerprint,
            build_fingerprint=stable_json_digest("build"),
            render_engine="BLENDER_EEVEE",
            resolution=(512, 512),
            passes={
                name: artifact(name)
                for name in (
                    "beauty",
                    "silhouette",
                    "object_id",
                    "material_id",
                    "normal",
                    "depth",
                    "wireframe",
                )
            },
        ),
        assessments=[]
        if outcome is None
        else [
            FeatureAssessment(
                feature_id="form",
                outcome=outcome,
                confidence=0.9,
                actual="Visible planes and relationships were inspected in the supplied passes.",
                evidence_passes=["beauty", "normal", "depth"],
                candidate_region=(0.0, 0.0, 1.0, 1.0),
            )
        ],
    )


def evaluate(plan: ModelingHypothesisV01, rating: VisualFindingSetV01, score: float = 0.989347):
    """Exercise pure evaluation without claiming fixture fingerprints are actual render files."""

    return evaluate_review(
        plan, rating, review_artifact=artifact("review"), legacy_direct_score=score
    )


@pytest.mark.parametrize("kind", ["volume", "cross_section", "part_relation", "silhouette"])
def test_wrong_structure_is_not_cleared_by_high_outline_score(kind: str) -> None:
    """A nearly perfect legacy bbox/silhouette score cannot hide an observed structural defect."""

    plan = hypothesis(kind)
    result = evaluate(plan, review(plan, "defect"))
    assert result.legacy_direct_score == 0.989347
    assert result.next_action == "structural_reentry"
    assert result.outcome == "needs_revision"
    assert result.human_quality_disposition == "not_recorded"
    assert result.findings[0].target_ids == ["body"]


def test_omitted_expected_feature_generates_finding_and_next_action() -> None:
    """An empty semantic/landmark-style submission is missing evidence, not an empty pass."""

    plan = hypothesis()
    result = evaluate(plan, review(plan, None))
    assert result.outcome == "unscorable"
    assert result.next_action == "evidence_required"
    assert result.findings[0].feature_id == "form"
    assert result.findings[0].kind == "missing_evidence"


@pytest.mark.parametrize("representation", ["solid", "shell", "sheet", "assembly"])
def test_valid_geometry_has_no_blanket_thickness_or_part_count_gate(representation: str) -> None:
    """A genuine thin shell/folded cloth or single part can satisfy its own observations."""

    plan = hypothesis(representation=representation)
    assert evaluate(plan, review(plan, "satisfied")).outcome == "visually_satisfied"


def test_applicability_is_frozen_before_evaluation() -> None:
    """Uniform material or nonapplicable features may be declared N/A but not waived later."""

    plan = hypothesis("surface_direction")
    with pytest.raises(ValueError, match="waive"):
        evaluate(plan, review(plan, "not_applicable"))
    item = plan.requirements[0].model_copy(
        update={
            "applicability": "not_applicable",
            "applicability_reason": "Reference is a uniform surface.",
        }
    )
    plan = plan.model_copy(update={"requirements": [item]})
    assert evaluate(plan, review(plan, "not_applicable")).findings == []


@pytest.mark.parametrize(
    ("kind", "route"),
    [
        ("local_dimension", "parametric_revision"),
        ("material", "material_revision"),
        ("surface_direction", "material_revision"),
        ("camera", "calibration"),
        ("uv", "technical_recovery"),
        ("topology", "technical_recovery"),
    ],
)
def test_precise_defect_routing(kind: str, route: str) -> None:
    """Appearance, scalar, camera and technical defects do not all request structural edits."""

    plan = hypothesis(kind)
    assert evaluate(plan, review(plan, "defect")).next_action == route


def test_uncertain_ai_judgment_cannot_claim_pass_or_human_authority() -> None:
    """Low-confidence satisfaction remains unscorable, and the contract forbids human approval."""

    plan = hypothesis()
    rating = review(plan, "satisfied")
    rating.assessments[0].confidence = 0.3
    assert evaluate(plan, rating).outcome == "unscorable"
    data = rating.model_dump(mode="json")
    data["human_quality_disposition"] = "accepted"
    with pytest.raises(ValidationError):
        VisualFindingSetV01.model_validate(data)


def test_structure_improvement_can_reduce_legacy_direct_score() -> None:
    """Real structural correction need not improve a misleading near-perfect outline metric."""

    plan = hypothesis()
    old, new = review(plan, "defect"), review(plan, "satisfied")
    result = compare_evaluations(
        evaluate(plan, old),
        evaluate(plan, new, score=0.91),
        before_artifact=artifact("before"),
        after_artifact=artifact("after"),
        before_review=old,
        after_review=new,
    )
    assert result.outcome == "improved"
    assert result.resolved_features == ["form"]
    assert result.direct_score_delta < 0


def test_camera_change_is_not_geometry_improvement() -> None:
    """A reframed result needs new paired renders rather than borrowing the old comparison."""

    plan = hypothesis()
    old, new = review(plan, "defect"), review(plan, "satisfied")
    new.evidence.camera_fingerprint = stable_json_digest("new-camera")
    result = compare_evaluations(
        evaluate(plan, old),
        evaluate(plan, new),
        before_artifact=artifact("before"),
        after_artifact=artifact("after"),
        before_review=old,
        after_review=new,
    )
    assert result.outcome == "incomparable"
    assert not result.resolved_features


def test_hidden_inference_cannot_be_required_reference_truth() -> None:
    """Generated extra views cannot turn an unobserved back face into measured reference data."""

    data = hypothesis().model_dump(mode="json")
    data["observations"][0]["status"] = "inferred"
    import json

    with pytest.raises(ValidationError, match="observed"):
        ModelingHypothesisV01.model_validate_json(json.dumps(data))
