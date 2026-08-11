"""Deterministic local quality checks for staged generated-image candidates."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from ..blender_artifacts import stable_json_digest
from .artifacts import validate_codex_image_artifact
from .models import (
    CodexGeneratedImageEvidence,
    CodexImageArtifact,
    CodexImageGenerationAssignment,
    CodexImageGenerationCandidate,
    CodexImageGenerationQualityReport,
    CodexImageQualityCheck,
)


def evaluate_candidate_quality(
    *,
    job_root: Path,
    report_id: str,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    candidate: CodexImageGenerationCandidate,
    candidate_artifact: CodexImageArtifact,
    generated_image_evidence: CodexGeneratedImageEvidence,
    generated_image_evidence_artifact: CodexImageArtifact,
    created_at: datetime,
) -> CodexImageGenerationQualityReport:
    """Evaluate only locally observable raster properties and mark semantics unscorable."""

    _validate_candidate_bindings(
        assignment,
        assignment_artifact,
        completion_artifact,
        candidate,
        candidate_artifact,
        generated_image_evidence,
    )
    image_path = validate_codex_image_artifact(job_root, candidate.generated_file.artifact)
    with Image.open(image_path) as opened:
        if opened.format != "PNG":
            raise ValueError("quality input must decode as PNG")
        opened.load()
        image = opened.convert("RGBA")
        original_bands = opened.getbands()
    checks = [
        _dimension_check(assignment, image),
        _detail_check(image),
        _alpha_check(candidate, original_bands),
        _border_contamination_check(
            image,
            hard_gate=assignment.generation_intent
            in {
                "generated_surface_swatch_v1",
                "reference_guided_texture_patch_v1",
                "generated_image_procedural_hybrid_v1",
            },
        ),
    ]
    if assignment.generation_intent in {
        "generated_surface_swatch_v1",
        "reference_guided_texture_patch_v1",
        "generated_image_procedural_hybrid_v1",
    }:
        checks.append(_edge_seam_check(image))
    if candidate.generated_file.output_role == "emission":
        checks.append(_emission_check(image))
    if any("wood" in role.casefold() for role in candidate.semantic_roles):
        checks.append(_wood_direction_advisory(image))
    checks.extend(_semantic_advisories(assignment))
    hard_failed = any(check.hard_gate and check.status == "failed" for check in checks)
    hard_unscorable = any(
        check.hard_gate and check.status == "unscorable" for check in checks
    )
    if hard_failed:
        outcome = "failed"
    elif hard_unscorable:
        outcome = "review_required"
    else:
        outcome = "passed"
    scored = [check.score for check in checks if check.score is not None]
    deterministic_score = sum(scored) / len(scored) if scored else 0.0
    inputs = {
        "assignment": assignment_artifact.model_dump(mode="json"),
        "completion": completion_artifact.model_dump(mode="json"),
        "candidate": candidate_artifact.model_dump(mode="json"),
        "generated_image_evidence": generated_image_evidence_artifact.model_dump(
            mode="json"
        ),
        "checks": [check.model_dump(mode="json") for check in checks],
    }
    provenance = _unique_artifacts(
        [
            assignment_artifact,
            completion_artifact,
            candidate_artifact,
            generated_image_evidence_artifact,
            candidate.generated_file.artifact,
        ]
    )
    return CodexImageGenerationQualityReport(
        contract_id=report_id,
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        input_sha256=stable_json_digest(inputs),
        source_fingerprint=stable_json_digest(
            {**inputs, "source_sha256": candidate.generated_file.artifact.sha256}
        ),
        producer="codex_blender_modeler.codex_imagegen.quality",
        provenance=provenance,
        created_at=created_at,
        report_id=report_id,
        assignment=assignment_artifact,
        completion=completion_artifact,
        candidate=candidate_artifact,
        generated_image_evidence=generated_image_evidence_artifact,
        checks=checks,
        deterministic_score=deterministic_score,
        outcome=outcome,
        selection_eligible=outcome == "passed",
    )


def _validate_candidate_bindings(
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    candidate: CodexImageGenerationCandidate,
    candidate_artifact: CodexImageArtifact,
    evidence: CodexGeneratedImageEvidence,
) -> None:
    """Require candidate and generated evidence to bind the supplied assignment chain."""

    if candidate.assignment != assignment_artifact:
        raise ValueError("quality candidate binds a different assignment")
    if candidate.completion != completion_artifact:
        raise ValueError("quality candidate binds a different completion")
    if evidence.candidate != candidate_artifact or evidence.candidate_id != candidate.candidate_id:
        raise ValueError("quality evidence binds a different candidate")
    if evidence.generated_file != candidate.generated_file:
        raise ValueError("quality evidence generated file differs from the candidate")


def _dimension_check(
    assignment: CodexImageGenerationAssignment,
    image: Image.Image,
) -> CodexImageQualityCheck:
    """Score exact raster dimensions as a mandatory binary gate."""

    passed = image.size == (assignment.image_size.width, assignment.image_size.height)
    return CodexImageQualityCheck(
        check_id="png-dimensions",
        status="passed" if passed else "failed",
        score=1.0 if passed else 0.0,
        threshold=1.0,
        hard_gate=True,
        algorithm_id="exact-png-dimensions-v1",
        message=(
            "decoded PNG dimensions match assignment"
            if passed
            else "decoded PNG dimensions differ from assignment"
        ),
    )


def _detail_check(image: Image.Image) -> CodexImageQualityCheck:
    """Measure luminance variation to reject empty or nearly uniform generated pixels."""

    grayscale = image.convert("L")
    variance = float(ImageStat.Stat(grayscale).var[0]) / (255.0 * 255.0)
    score = min(1.0, variance / 0.05)
    passed = variance >= 0.0005
    return CodexImageQualityCheck(
        check_id="spatial-detail",
        status="passed" if passed else "failed",
        score=score,
        threshold=0.01,
        hard_gate=True,
        algorithm_id="normalized-luminance-variance-v1",
        message=(
            "image contains measurable spatial detail"
            if passed
            else "image is effectively uniform"
        ),
    )


def _alpha_check(
    candidate: CodexImageGenerationCandidate,
    original_bands: tuple[str, ...],
) -> CodexImageQualityCheck:
    """Require a decodable alpha source only when the declared output role needs it."""

    required = candidate.generated_file.output_role in {"decal_rgb", "opacity_source"}
    present = "A" in original_bands
    passed = present
    return CodexImageQualityCheck(
        check_id="alpha-extractability",
        status=("passed" if passed else "failed") if required else "advisory",
        score=(1.0 if passed else 0.0) if required else None,
        threshold=1.0 if required else None,
        hard_gate=required,
        algorithm_id="png-alpha-band-v1",
        message=(
            "alpha source is locally extractable"
            if present
            else "PNG has no explicit alpha channel"
        ),
    )


def _edge_seam_check(image: Image.Image) -> CodexImageQualityCheck:
    """Compare opposite edges as a deterministic tile-seam proxy."""

    width, height = image.size
    left = image.crop((0, 0, 1, height)).convert("RGB")
    right = image.crop((width - 1, 0, width, height)).convert("RGB")
    top = image.crop((0, 0, width, 1)).convert("RGB")
    bottom = image.crop((0, height - 1, width, height)).convert("RGB")
    horizontal = sum(ImageStat.Stat(ImageChops.difference(left, right)).rms) / 3.0
    vertical = sum(ImageStat.Stat(ImageChops.difference(top, bottom)).rms) / 3.0
    mismatch = (horizontal + vertical) / (2.0 * 255.0)
    score = max(0.0, 1.0 - mismatch)
    passed = mismatch <= 0.35
    return CodexImageQualityCheck(
        check_id="edge-seam-proxy",
        status="passed" if passed else "failed",
        score=score,
        threshold=0.65,
        hard_gate=True,
        algorithm_id="opposite-edge-rmse-v1",
        message=(
            "opposite edges are within the seam proxy limit"
            if passed
            else "opposite edges exceed the seam proxy limit"
        ),
    )


def _border_contamination_check(
    image: Image.Image,
    *,
    hard_gate: bool,
) -> CodexImageQualityCheck:
    """Compare outer pixels to adjacent rings as a deterministic border-frame proxy."""

    width, height = image.size
    rgb = image.convert("RGB")
    pairs = (
        (rgb.crop((0, 0, 1, height)), rgb.crop((1, 0, 2, height))),
        (
            rgb.crop((width - 1, 0, width, height)),
            rgb.crop((width - 2, 0, width - 1, height)),
        ),
        (rgb.crop((0, 0, width, 1)), rgb.crop((0, 1, width, 2))),
        (
            rgb.crop((0, height - 1, width, height)),
            rgb.crop((0, height - 2, width, height - 1)),
        ),
    )
    normalized = sum(
        sum(ImageStat.Stat(ImageChops.difference(outer, inner)).rms) / 3.0
        for outer, inner in pairs
    ) / (len(pairs) * 255.0)
    score = max(0.0, 1.0 - normalized)
    passed = normalized <= 0.5
    return CodexImageQualityCheck(
        check_id="border-contamination-proxy",
        status="passed" if passed else "failed",
        score=score,
        threshold=0.5,
        hard_gate=hard_gate,
        algorithm_id="outer-adjacent-ring-rmse-v1",
        message=(
            "outer border is locally continuous"
            if passed
            else "outer border differs sharply from its adjacent ring"
        ),
    )


def _emission_check(image: Image.Image) -> CodexImageQualityCheck:
    """Require emission candidates to retain usable luminance energy and variation."""

    stat = ImageStat.Stat(image.convert("L"))
    mean = float(stat.mean[0]) / 255.0
    variation = min(1.0, float(stat.var[0]) / (255.0 * 255.0 * 0.05))
    score = min(1.0, mean * 1.5) * 0.5 + variation * 0.5
    passed = mean >= 0.03 and variation >= 0.05
    return CodexImageQualityCheck(
        check_id="emission-usefulness",
        status="passed" if passed else "failed",
        score=score,
        threshold=0.05,
        hard_gate=True,
        algorithm_id="emission-luminance-energy-v1",
        message=(
            "emission luminance is usable"
            if passed
            else "emission candidate is too dark or uniform"
        ),
    )


def _wood_direction_advisory(image: Image.Image) -> CodexImageQualityCheck:
    """Report a local gradient anisotropy proxy without asserting intended grain direction."""

    grayscale = image.convert("L")
    x_difference = ImageChops.difference(grayscale, ImageChops.offset(grayscale, 1, 0))
    y_difference = ImageChops.difference(grayscale, ImageChops.offset(grayscale, 0, 1))
    x_energy = float(ImageStat.Stat(x_difference).mean[0])
    y_energy = float(ImageStat.Stat(y_difference).mean[0])
    total = x_energy + y_energy
    score = abs(x_energy - y_energy) / total if total else 0.0
    return CodexImageQualityCheck(
        check_id="wood-grain-anisotropy",
        status="advisory",
        score=score,
        threshold=None,
        hard_gate=False,
        algorithm_id="axis-gradient-anisotropy-v1",
        message="anisotropy is measured, but intended grain direction needs material context",
    )


def _semantic_advisories(
    assignment: CodexImageGenerationAssignment,
) -> list[CodexImageQualityCheck]:
    """Mark semantic text, object, and style claims unavailable to local pixel metrics."""

    checks = [
        CodexImageQualityCheck(
            check_id="unwanted-object-content",
            status="unscorable",
            score=None,
            threshold=None,
            hard_gate=False,
            algorithm_id="controller-review-required-v1",
            message="local deterministic checks cannot identify semantic unwanted objects",
        ),
        CodexImageQualityCheck(
            check_id="unwanted-text-content",
            status="unscorable",
            score=None,
            threshold=None,
            hard_gate=False,
            algorithm_id="controller-review-required-v1",
            message="local deterministic checks cannot identify semantic unwanted text",
        ),
        CodexImageQualityCheck(
            check_id="style-alignment",
            status="unscorable",
            score=None,
            threshold=None,
            hard_gate=False,
            algorithm_id="controller-review-required-v1",
            message="local deterministic checks cannot attest prompt-style alignment",
        ),
        CodexImageQualityCheck(
            check_id="background-alignment",
            status="unscorable",
            score=None,
            threshold=None,
            hard_gate=False,
            algorithm_id="controller-review-required-v1",
            message="local deterministic checks cannot attest semantic background alignment",
        ),
    ]
    if assignment.exact_text_sha256 is not None:
        checks.append(
            CodexImageQualityCheck(
                check_id="exact-text-exclusion",
                status="unscorable",
                score=None,
                threshold=None,
                hard_gate=False,
                algorithm_id="local-text-composition-required-v1",
                message="exact text remains excluded and must be composed locally",
            )
        )
    return checks


def _unique_artifacts(items: list[CodexImageArtifact]) -> list[CodexImageArtifact]:
    """Preserve evidence order while removing byte-identical bindings."""

    result: list[CodexImageArtifact] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (item.path, item.sha256, item.kind)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result
