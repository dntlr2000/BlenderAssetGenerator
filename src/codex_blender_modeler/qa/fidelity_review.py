"""Source-bound manual detail/attachment review for explicitly selected exterior v3."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..analysis.models import ModelingPlan
from ..blender_artifacts import publish_bytes_create_once, stable_json_digest
from ..models import SceneSpec, StrictModel
from ..workspace import sha256_file

POLICY = "exterior_geometry_review_v3"


class ReviewArtifact(StrictModel):
    """Bind one contained immutable input without granting source-write authority."""

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        """Reject absolute, ambiguous, or escaping paths before file access."""

        if (
            "\\" in value
            or ":" in value
            or "\x00" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("detail-review artifacts require normalized job-relative paths")
        return value


class DetailReviewContract(StrictModel):
    """Keep broad-phase declarations separate from actual manual visual evidence."""

    modeling_plan: ReviewArtifact
    scene_spec: ReviewArtifact
    reference: ReviewArtifact | None = None
    internal_form_target_ids: list[str]
    attachment_target_ids: list[str]
    observed_reference_target_ids: list[str]
    broad_phase_relation_ids: list[str]
    surface_detail_ids: list[str]
    attachment_evidence: Literal["broad_phase_only"] = "broad_phase_only"
    internal_detail_evidence: Literal["unverified"] = "unverified"
    surface_detail_appearance: Literal["unverified"] = "unverified"
    automated_fidelity_verified: Literal[False] = False
    review_scope: Literal["geometry_internal_form_and_attachment"] = (
        "geometry_internal_form_and_attachment"
    )
    material_appearance_verified: Literal[False] = False
    whole_asset_fidelity_verified: Literal[False] = False

    @model_validator(mode="after")
    def validate_inventory(self) -> DetailReviewContract:
        """Require deterministic inventories without inventing observed or attachment support."""

        for field in (
            "internal_form_target_ids",
            "attachment_target_ids",
            "observed_reference_target_ids",
            "broad_phase_relation_ids",
            "surface_detail_ids",
        ):
            values = getattr(self, field)
            if values != sorted(set(values)):
                raise ValueError("detail-review inventories must be uniquely sorted")
        if not set(self.attachment_target_ids) <= set(self.internal_form_target_ids):
            raise ValueError("attachment review targets must belong to the reviewed asset")
        return self


class DetailVisualAssessment(StrictModel):
    """Record an explicit limited visual judgment, never physical-contact certification."""

    target_id: str = Field(min_length=1)
    aspect: Literal["internal_form", "attachment", "reference_internal_detail"]
    reference_basis: Literal["observed_reference", "inferred_only"]
    outcome: Literal["visually_supported", "defect", "unscorable"]
    view_ids: list[Literal["front", "right", "top", "rear", "oblique"]] = Field(min_length=1)
    observation: str = Field(min_length=8)
    limitations: str = Field(min_length=8)
    finding_ids: list[str] = Field(default_factory=list)
    surface_detail_ids: list[str] = Field(default_factory=list)
    attachment_reference_ids: list[str] = Field(default_factory=list)
    physical_contact_verified: Literal[False] = False
    human_acceptance: Literal[False] = False

    @model_validator(mode="after")
    def validate_assessment(self) -> DetailVisualAssessment:
        """Require useful observations, unique evidence, and findings for unresolved work."""

        if len(self.view_ids) != len(set(self.view_ids)):
            raise ValueError("detail-review views must be unique")
        if len(self.finding_ids) != len(set(self.finding_ids)):
            raise ValueError("detail-review findings must be unique")
        if self.attachment_reference_ids != sorted(set(self.attachment_reference_ids)):
            raise ValueError("attachment reference IDs must be uniquely sorted")
        if self.aspect != "attachment" and self.attachment_reference_ids:
            raise ValueError("only attachment assessments may name visual seat partners")
        if (
            self.aspect == "attachment"
            and self.outcome == "visually_supported"
            and not self.attachment_reference_ids
        ):
            raise ValueError("supported attachment assessment requires an explicit seat partner")
        if self.outcome != "visually_supported" and not self.finding_ids:
            raise ValueError("defect or unscorable detail assessment requires finding IDs")
        if self.outcome == "visually_supported" and self.finding_ids:
            raise ValueError("supported detail assessment cannot carry unresolved findings")
        return self


def _artifact(root: Path, path: Path) -> ReviewArtifact:
    """Fingerprint only ordinary files inside the owning job."""

    from ..production.validation import ensure_contained_production_path

    path = ensure_contained_production_path(root, path, must_exist=True)
    return ReviewArtifact(path=path.relative_to(root).as_posix(), sha256=sha256_file(path))


def _read(root: Path, artifact: ReviewArtifact) -> bytes:
    """Reject changed, missing, linked, or escaped review evidence."""

    from ..production.validation import ensure_contained_production_path

    path = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
    if sha256_file(path) != artifact.sha256:
        raise ValueError("detail-review evidence is missing or changed")
    return path.read_bytes()


def _snapshot(root: Path, source: Path, destination: Path) -> ReviewArtifact:
    """Copy exact source bytes once into a run-owned immutable input slot."""

    from ..production.validation import ensure_contained_production_path

    content = _read(root, _artifact(root, source))
    destination = ensure_contained_production_path(root, destination, must_exist=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    publish_bytes_create_once(destination, content)
    return _artifact(root, destination)


def review_inventory(modeling_plan: ModelingPlan, target_ids: list[str], scene: SceneSpec) -> dict:
    """Expose declared requirements without interpreting names, notes, or missing detail."""

    attached = sorted(
        item.id
        for item in modeling_plan.objects
        if item.id in target_ids and item.assembly_role == "attached"
    )
    reference_ids = {item.id for item in scene.sources if item.kind == "reference"}
    observed = sorted(
        item.id
        for item in scene.objects
        if item.id in target_ids
        and any(
            evidence.status == "observed" and evidence.source_id in reference_ids
            for evidence in item.evidence
        )
    )
    return {
        "observed_reference_target_ids": observed,
        "internal_form_target_ids": sorted(target_ids),
        "attachment_target_ids": attached,
        "broad_phase_relation_ids": sorted(
            item.id
            for item in modeling_plan.assembly_relationships
            if item.required and item.subject_id in attached
        ),
        "surface_detail_ids": sorted(item.id for item in modeling_plan.surface_details),
    }


def capture_detail_review_contract(
    root: Path,
    run_dir: Path,
    *,
    scene_path: Path,
    modeling_plan_path: Path,
    target_ids: list[str],
    reference_path: Path | None,
) -> DetailReviewContract:
    """Freeze exact source declarations and primary reference for the native visual review."""

    folder = run_dir / "detail_review_inputs"
    model = ModelingPlan.model_validate_json(modeling_plan_path.read_bytes())
    scene = SceneSpec.model_validate_json(scene_path.read_bytes())
    scene_artifact = _snapshot(root, scene_path, folder / "scene_spec.json")
    plan_artifact = _snapshot(root, modeling_plan_path, folder / "modeling_plan.json")
    reference = (
        _snapshot(root, reference_path, folder / "reference.png")
        if reference_path is not None
        else None
    )
    return DetailReviewContract(
        modeling_plan=plan_artifact,
        scene_spec=scene_artifact,
        reference=reference,
        **review_inventory(model, target_ids, scene),
    )


def validate_detail_review_contract(root: Path, plan: object) -> DetailReviewContract:
    """Replay v3 source coverage from exact snapshots rather than mutable current sources."""

    contract = plan.detail_review_contract
    if contract is None:
        raise ValueError("exterior v3 requires detail-review source coverage")
    base = f"qa/assembly_sanity/runs/{plan.run_id}/detail_review_inputs/"
    for field, name in (
        ("modeling_plan", "modeling_plan.json"),
        ("scene_spec", "scene_spec.json"),
        ("reference", "reference.png"),
    ):
        artifact = getattr(contract, field)
        if artifact is not None and artifact.path != base + name:
            raise ValueError("detail-review input is outside its exact run-owned slot")
    model = ModelingPlan.model_validate_json(_read(root, contract.modeling_plan))
    scene = SceneSpec.model_validate_json(_read(root, contract.scene_spec))
    if (
        contract.modeling_plan.sha256 != plan.modeling_plan_sha256
        or contract.scene_spec.sha256 != plan.scene_spec_sha256
        or model.job_id != plan.job_id
        or scene.job_id != plan.job_id
    ):
        raise ValueError("detail-review source snapshot does not bind the plan")
    for field, expected in review_inventory(model, plan.target_ids, scene).items():
        if getattr(contract, field) != expected:
            raise ValueError("detail-review coverage differs from declared source requirements")
    references = [item for item in plan.reference_sources if item.kind == "reference"]
    if bool(references) != (contract.reference is not None):
        raise ValueError("detail-review primary reference evidence is missing")
    if contract.reference is not None:
        if len(references) != 1 or contract.reference.sha256 != references[0].sha256:
            raise ValueError("detail-review reference differs from immutable primary reference")
        _read(root, contract.reference)
    return contract


def validate_detail_visual_assessments(root: Path, plan: object, review: object) -> None:
    """Require complete source-bound manual observations and route every unresolved aspect."""

    contract = validate_detail_review_contract(root, plan)
    expected = {(target, "internal_form") for target in contract.internal_form_target_ids}
    expected.update((target, "attachment") for target in contract.attachment_target_ids)
    expected.add((plan.assembly_frame.root_object_id, "reference_internal_detail"))
    actual = {(item.target_id, item.aspect) for item in review.detail_assessments}
    if actual != expected or len(actual) != len(review.detail_assessments):
        raise ValueError(
            "exterior v3 requires one assessment for every internal form and attachment"
        )
    if review.reviewed_detail_contract_sha256 != stable_json_digest(
        contract.model_dump(mode="json")
    ):
        raise ValueError("detail-review observations do not bind the exact source/image contract")
    findings = {item.finding_id: item for item in review.findings}
    model = ModelingPlan.model_validate_json(_read(root, contract.modeling_plan))
    detail_parents = {item.id: item.parent_object_id for item in model.surface_details}
    for assessment in review.detail_assessments:
        expected_basis = (
            "observed_reference"
            if assessment.aspect == "reference_internal_detail"
            or assessment.target_id in contract.observed_reference_target_ids
            else "inferred_only"
        )
        expected_details = (
            sorted(detail_parents)
            if assessment.aspect == "reference_internal_detail"
            else sorted(
                key for key, parent in detail_parents.items() if parent == assessment.target_id
            )
            if assessment.aspect == "internal_form"
            else []
        )
        if assessment.aspect == "attachment":
            partners = set(assessment.attachment_reference_ids)
            if (
                not partners <= set(contract.internal_form_target_ids)
                or assessment.target_id in partners
            ):
                raise ValueError("attachment assessment names an invalid visual seat partner")
            required_contacts = {
                item.reference_id
                for item in model.assembly_relationships
                if item.kind == "surface_contact"
                and item.required
                and item.subject_id == assessment.target_id
            }
            if assessment.outcome == "visually_supported" and not required_contacts <= partners:
                raise ValueError("attachment assessment omits a declared required contact partner")
        if assessment.surface_detail_ids != expected_details:
            raise ValueError("detail assessment must explicitly cover each declared surface detail")
        if assessment.reference_basis != expected_basis:
            raise ValueError(
                "detail review cannot promote inferred geometry to observed reference evidence"
            )
        if (
            assessment.aspect in {"internal_form", "reference_internal_detail"}
            and assessment.reference_basis == "observed_reference"
            and contract.reference is None
            and assessment.outcome != "unscorable"
        ):
            raise ValueError("internal-form fidelity needs the actual primary reference")
        for finding_id in assessment.finding_ids:
            finding = findings.get(finding_id)
            if (
                finding is None
                or assessment.target_id not in finding.target_ids
                or not set(assessment.view_ids) <= set(finding.view_ids)
            ):
                raise ValueError("detail assessment finding omits its target or evidence views")
            if assessment.outcome == "unscorable":
                if finding.issue_type != "insufficient_evidence":
                    raise ValueError("unscorable detail must route additional evidence")
            elif finding.issue_type == "insufficient_evidence" or finding.severity == "info":
                raise ValueError("detail defect must route revision or redesign review")


def require_detail_quality_progression(plan: object, review: object) -> None:
    """Keep v3 review acknowledgment separate from permission to advance quality gates."""

    if plan.review_policy != POLICY:
        return
    expected = {
        (target, "internal_form") for target in plan.detail_review_contract.internal_form_target_ids
    }
    expected.update(
        (target, "attachment") for target in plan.detail_review_contract.attachment_target_ids
    )
    expected.add((plan.assembly_frame.root_object_id, "reference_internal_detail"))
    if {(item.target_id, item.aspect) for item in review.detail_assessments} != expected:
        raise ValueError("additional_evidence_required: mandatory detail assessments are absent")
    if any(item.outcome == "unscorable" for item in review.detail_assessments):
        raise ValueError(
            "additional_evidence_required: mandatory detail/attachment review is unscorable"
        )
    if any(item.outcome == "defect" for item in review.detail_assessments):
        raise ValueError(
            "revision_required: mandatory detail/attachment visual review found defects"
        )
    if review.outcome != "visually_coherent":
        raise ValueError(
            "review_required: unresolved geometry review cannot advance exterior v3 quality"
        )
