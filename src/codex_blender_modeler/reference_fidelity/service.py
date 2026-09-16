"""Rehash actual render evidence and route visual defects without rewriting legacy QA."""

from __future__ import annotations

import json
from pathlib import Path

from ..autonomy.io import write_immutable_json
from ..blender_artifacts import native_io_path, publish_bytes_create_once, sha256_file
from ..models import SceneSpec
from ..production.validation import ensure_contained_production_path
from ..qa.hashing import canonical_model_sha256
from ..qa.models import RenderPassManifest, VisualQAReport, VisualQARequest
from .models import (
    FidelityArtifact,
    FidelityComparisonV01,
    FidelityEvaluationV01,
    FidelityModel,
    ModelingHypothesisV01,
    RenderEvidenceV01,
    RoutedFindingV01,
    VisualFindingSetV01,
)

ROUTES = {
    "volume": "structural_reentry",
    "cross_section": "structural_reentry",
    "part_relation": "structural_reentry",
    "silhouette": "structural_reentry",
    "local_dimension": "parametric_revision",
    "material": "material_revision",
    "surface_direction": "material_revision",
    "camera": "calibration",
    "missing_evidence": "evidence_required",
    "topology": "technical_recovery",
    "uv": "technical_recovery",
}


def artifact_at(root: Path, path: Path) -> FidelityArtifact:
    """Fingerprint an existing no-link file relative to its declared evidence root."""

    path = ensure_contained_production_path(root, path, must_exist=True)
    return FidelityArtifact(path=path.relative_to(root).as_posix(), sha256=sha256_file(path))


def read_artifact(root: Path, artifact: FidelityArtifact) -> bytes:
    """Reject tampering, absent files and path/link escape before consuming evidence."""

    path = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"reference fidelity evidence changed: {artifact.path}")
    with open(native_io_path(path), "rb") as handle:
        return handle.read()


def publish(root: Path, path: Path, model: FidelityModel) -> FidelityArtifact:
    """Publish append-only companion evidence; no canonical or historical replacement."""

    relative = path.relative_to(root).as_posix()
    if not (
        relative.startswith("fidelity/")
        or (relative.startswith("production/autonomy_v2/") and "/fidelity/" in relative)
    ):
        raise PermissionError("fidelity evidence must stay in its companion namespace")
    write_immutable_json(root, path, model.model_dump(mode="json"))
    return artifact_at(root, path)


def _geometry_dependencies(
    root: Path, scene: SceneSpec, snapshots: dict[str, FidelityArtifact] | None = None
) -> list[FidelityArtifact]:
    """Bind nested MeshPayload bytes through snapshots when a later round replaces the source."""

    from ..blender_artifacts import stable_json_digest

    pending = [getattr(obj.geometry, "path", None) for obj in scene.objects]
    result = {}
    while pending:
        relative = pending.pop()
        if relative is None or relative in result:
            continue
        if len(result) >= 512:
            raise ValueError("geometry dependency closure exceeds the bounded companion limit")
        if snapshots is not None:
            if relative not in snapshots:
                raise ValueError("geometry snapshot omits a nested source dependency")
            content = read_artifact(root, snapshots[relative])
            artifact = FidelityArtifact(path=relative, sha256=snapshots[relative].sha256)
        else:
            artifact = artifact_at(root, root / relative)
            content = read_artifact(root, artifact)
        payload = json.loads(content)
        result[relative] = artifact
        sources = payload.get("source_hashes", []) if isinstance(payload, dict) else []
        if sources:
            if payload.get("source_fingerprint_sha256") != stable_json_digest(sources):
                raise ValueError("geometry source fingerprint is stale")
            for source in sources:
                if snapshots is not None:
                    if source["path"] not in snapshots:
                        raise ValueError("geometry snapshot omits a nested source dependency")
                    dependency = FidelityArtifact(
                        path=source["path"], sha256=snapshots[source["path"]].sha256
                    )
                else:
                    dependency = artifact_at(root, root / source["path"])
                if dependency.sha256 != source["sha256"]:
                    raise ValueError("nested geometry dependency changed")
                pending.append(dependency.path)
    return [result[key] for key in sorted(result)]


def capture_render_evidence(
    root: Path, *, qa_run_id: str, output_dir: Path, scene_spec_path: Path | None = None
) -> RenderEvidenceV01:
    """Snapshot current source for an actual QA run without changing any old pass or report."""

    from ..qa.service import _validate_run_id
    from .source_snapshot import capture_build_sources

    _validate_run_id(qa_run_id)
    if not output_dir.relative_to(root).as_posix().startswith("fidelity/"):
        raise PermissionError("render evidence snapshots must stay in fidelity staging")
    base = root / "qa/runs" / qa_run_id
    manifest_artifact = artifact_at(root, base / "render_pass_manifest.json")
    manifest = RenderPassManifest.model_validate_json(read_artifact(root, manifest_artifact))
    source = artifact_at(root, scene_spec_path or root / "analysis/scene_spec.json")
    if source.sha256 != manifest.scene_spec_sha256:
        raise ValueError("QA no longer matches current source; supply its historical snapshot")
    scene_bytes = read_artifact(root, source)
    scene = SceneSpec.model_validate_json(scene_bytes)
    output_dir = ensure_contained_production_path(root, output_dir, must_exist=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = output_dir / "scene_spec.json"
    publish_bytes_create_once(snapshot, scene_bytes)
    payloads = _geometry_dependencies(root, scene)
    geometry_snapshots = {}
    for item in payloads:
        snapshot_path = ensure_contained_production_path(
            root, output_dir / "geometry" / item.sha256, must_exist=False
        )
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        publish_bytes_create_once(snapshot_path, read_artifact(root, item))
        geometry_snapshots[item.path] = artifact_at(root, snapshot_path)
    conditions_path = next(
        (
            path
            for path in (
                base / "comparison_conditions.json",
                base / "render_source/comparison_conditions.json",
            )
            if path.is_file()
        ),
        None,
    )
    evidence = RenderEvidenceV01(
        scene_spec=artifact_at(root, snapshot),
        geometry_payloads=payloads,
        geometry_snapshots=geometry_snapshots,
        qa_request=artifact_at(root, base / "request.json"),
        qa_report=artifact_at(root, base / "visual_qa_report.json"),
        pass_manifest=manifest_artifact,
        camera_fingerprint=manifest.camera_fingerprint,
        build_fingerprint=manifest.build_fingerprint,
        build_sources=capture_build_sources(
            root, root / source.path,
            expected_fingerprint=manifest.build_fingerprint, output=output_dir / "sources"
        ),
        comparison_conditions=(
            artifact_at(root, conditions_path) if conditions_path is not None else None
        ),
        render_engine=manifest.render_engine,
        resolution=manifest.resolution,
        passes={item.kind: artifact_at(root, base / item.path) for item in manifest.passes},
    )
    publish(root, output_dir / "render_evidence.json", evidence)
    return evidence


def validate_review_evidence(
    root: Path,
    hypothesis: ModelingHypothesisV01,
    review: VisualFindingSetV01,
) -> VisualQAReport:
    """Cross-check observations, source snapshots, seven passes and actual V0.6 identity."""

    if (
        ModelingHypothesisV01.model_validate_json(read_artifact(root, review.hypothesis))
        != hypothesis
    ):
        raise ValueError("review hypothesis bytes differ")
    if review.reference != hypothesis.reference or review.job_id != hypothesis.job_id:
        raise ValueError("review belongs to another reference or job")
    read_artifact(root, review.reference)
    evidence = review.evidence
    from .source_snapshot import validate_build_sources

    validate_build_sources(root, evidence)
    scene = SceneSpec.model_validate_json(read_artifact(root, evidence.scene_spec))
    request = VisualQARequest.model_validate_json(read_artifact(root, evidence.qa_request))
    report = VisualQAReport.model_validate_json(read_artifact(root, evidence.qa_report))
    manifest = RenderPassManifest.model_validate_json(read_artifact(root, evidence.pass_manifest))
    if {scene.job_id, request.job_id, report.job_id, manifest.job_id} != {review.job_id}:
        raise ValueError("render evidence belongs to another job")
    if request.run_id != report.run_id or manifest.run_id != report.run_id:
        raise ValueError("mixed render run evidence")
    if report.request_sha256 != canonical_model_sha256(request):
        raise ValueError("QA report does not bind the exact request")
    if request.render_pass_manifest_sha256 != evidence.pass_manifest.sha256:
        raise ValueError("QA request does not bind the pass manifest")
    if request.reference_sha256 != hypothesis.reference.sha256:
        raise ValueError("QA reference differs from independently observed reference")
    if hypothesis.reference_mask_seed_evidence is not None:
        _validate_reference_seed_manifest(root, hypothesis, scene, request, evidence.qa_request)
    if {request.scene_spec_sha256, manifest.scene_spec_sha256} != {evidence.scene_spec.sha256}:
        raise ValueError("render scene snapshot differs")
    if {
        request.camera_fingerprint,
        report.camera_fingerprint,
        manifest.camera_fingerprint,
        hypothesis.camera.camera_fingerprint,
    } != {evidence.camera_fingerprint}:
        raise ValueError("camera differs; calibrate and re-render both candidates for comparison")
    if (
        manifest.build_fingerprint != evidence.build_fingerprint
        or manifest.render_engine != evidence.render_engine
        or manifest.resolution != evidence.resolution
    ):
        raise ValueError("build or comparison conditions differ")
    semantic_ids = {item.id for item in scene.objects}
    required_ids = {key for item in hypothesis.requirements for key in item.target_ids}
    if not required_ids <= semantic_ids:
        # Missing generated parts are quality defects, but fictitious review targets are not.
        rated = {item.feature_id: item for item in review.assessments}
        for item in hypothesis.requirements:
            if not set(item.target_ids) <= semantic_ids:
                if item.feature_id in rated and rated[item.feature_id].outcome == "satisfied":
                    raise ValueError("cannot satisfy a feature whose target was not generated")
    payloads = {item.path: item for item in evidence.geometry_payloads}
    for obj in scene.objects:
        path = getattr(obj.geometry, "path", None)
        if path and path not in payloads:
            raise ValueError("render source omits an external geometry dependency")
    snapshots = evidence.geometry_snapshots or None
    if snapshots is not None:
        if set(snapshots) != set(payloads):
            raise ValueError("geometry snapshot inventory differs from its declared source paths")
        for name, artifact in snapshots.items():
            if artifact.sha256 != payloads[name].sha256:
                raise ValueError("geometry snapshot differs from the exact source payload")
            read_artifact(root, artifact)
    else:
        for artifact in evidence.geometry_payloads:
            read_artifact(root, artifact)
    for artifact in evidence.auxiliary_views:
        read_artifact(root, artifact)
    if set(payloads) != {
        item.path for item in _geometry_dependencies(root, scene, snapshots=snapshots)
    }:
        raise ValueError("visual evidence omits or adds nested geometry source dependencies")
    manifest_root = (root / evidence.pass_manifest.path).parent
    for record in manifest.passes:
        artifact = evidence.passes[record.kind]
        expected_path = ensure_contained_production_path(
            root,
            manifest_root / record.path,
            must_exist=True,
        )
        if root / artifact.path != expected_path or artifact.sha256 != record.sha256:
            raise ValueError("visual review substitutes another pass")
        read_artifact(root, artifact)
    if request.preview_sha256 != evidence.passes["beauty"].sha256:
        raise ValueError("review beauty differs from QA request")
    return report


def _validate_reference_seed_manifest(
    root: Path,
    hypothesis: ModelingHypothesisV01,
    scene: SceneSpec,
    request: VisualQARequest,
    request_artifact: FidelityArtifact,
) -> None:
    """Require the rendered mask to retain the exact separately bound segmentation evidence."""
    from ..blender_artifacts import stable_json_digest
    from ..qa.reference_mask import validate_explicit_reference_seeds
    from ..reference_scope import subject_object_ids

    expected = hypothesis.reference_mask_seed_evidence
    if expected is None:
        raise ValueError("explicit seed validation requires its hypothesis companion")
    directory = (root / request_artifact.path).parent
    manifest = json.loads(read_artifact(
        root, artifact_at(root, directory / "reference_mask_manifest.json")
    ))
    seeds = validate_explicit_reference_seeds(
        root, root / hypothesis.reference.path, scene, expected,
        allowed_object_ids=(subject_object_ids(scene) if manifest.get(
            "reference_content_scope"
        ) == "primary_object_only" else None),
    )
    projection = expected.model_dump(mode="json")
    if (
        manifest.get("seed_evidence") != projection
        or manifest.get("seed_evidence_sha256") != stable_json_digest(projection)
        or manifest.get("reference_sha256") != hypothesis.reference.sha256
        or manifest.get("output_sha256") != request.reference_mask_sha256
        or manifest.get("seeds") != [
            {"group_id": seed.group_id, "object_id": seed.object_id,
             "bbox_norm": list(seed.bbox_norm), "confidence": seed.confidence}
            for seed in seeds
        ]
        or not str(manifest.get("method", "")).startswith("opencv_grabcut_evidence_seeded")
    ):
        raise ValueError("rendered reference mask differs from its explicit segmentation evidence")
    mask = artifact_at(root, directory / "reference_mask.png")
    if mask.sha256 != request.reference_mask_sha256:
        raise ValueError("rendered reference mask bytes changed")


def _comparison_conditions(root: Path, review: VisualFindingSetV01) -> object:
    """Read actual renderer-recorded lighting; historical absence is not comparable evidence."""

    evidence = review.evidence
    if evidence.comparison_conditions is None:
        raise ValueError("paired visual comparison needs actual renderer conditions for both runs")
    payload = json.loads(read_artifact(root, evidence.comparison_conditions))
    if (payload.get("schema_version"), payload.get("contract_kind")) != (
        "0.1.0",
        "fidelity_render_conditions",
    ):
        raise ValueError("unknown renderer conditions contract")
    if (
        payload.get("scene_spec_sha256") != evidence.scene_spec.sha256
        or payload.get("camera_fingerprint") != evidence.camera_fingerprint
    ):
        raise ValueError("renderer conditions belong to another source/run")
    if payload.get("pass_manifest_sha256") != evidence.pass_manifest.sha256:
        original = artifact_at(
            root, (root / evidence.comparison_conditions.path).parent / "render_pass_manifest.json"
        )
        if original.sha256 != payload.get("pass_manifest_sha256"):
            raise ValueError("renderer conditions pass manifest changed")
        source_manifest = RenderPassManifest.model_validate_json(read_artifact(root, original))
        projected = RenderPassManifest.model_validate_json(
            read_artifact(root, evidence.pass_manifest)
        )
        source_data = source_manifest.model_dump(mode="json")
        projected_data = projected.model_dump(mode="json")
        for data in (source_data, projected_data):
            for record in data["passes"]:
                record.pop("path")
        if source_data != projected_data:
            raise ValueError("QA snapshot is not the exact renderer manifest projection")
    conditions = payload.get("conditions")
    if not isinstance(conditions, dict) or not conditions:
        raise ValueError("renderer conditions are missing")
    return conditions


def evaluate_review(
    hypothesis: ModelingHypothesisV01,
    review: VisualFindingSetV01,
    *,
    review_artifact: FidelityArtifact,
    legacy_direct_score: float,
) -> FidelityEvaluationV01:
    """Route every missing/defective requirement; high bbox/detail scores cannot cancel it."""

    if review.reference != hypothesis.reference or review.job_id != hypothesis.job_id:
        raise ValueError("review identity differs from hypothesis")
    requirements = {item.feature_id: item for item in hypothesis.requirements}
    ratings = {item.feature_id: item for item in review.assessments}
    if not ratings.keys() <= requirements.keys():
        raise ValueError("review names an unknown expected feature")
    findings = []
    required = satisfied = 0
    for feature in hypothesis.requirements:
        assessment = ratings.get(feature.feature_id)
        if feature.applicability == "not_applicable":
            if assessment is not None and assessment.outcome != "not_applicable":
                raise ValueError("assessment changes predeclared applicability")
            continue
        required += int(feature.required)
        if assessment is not None and assessment.outcome == "not_applicable":
            raise ValueError("evaluator cannot waive a frozen applicable requirement")
        if (
            assessment is not None
            and assessment.outcome == "satisfied"
            and assessment.confidence >= feature.minimum_confidence
        ):
            satisfied += int(feature.required)
            continue
        if assessment is None and not feature.required:
            continue
        missing = (
            assessment is None
            or assessment.outcome == "unscorable"
            or assessment.confidence < feature.minimum_confidence
        )
        kind = "missing_evidence" if missing else feature.kind
        findings.append(
            RoutedFindingV01(
                feature_id=feature.feature_id,
                target_ids=feature.target_ids,
                face_groups=feature.face_groups,
                observation_ids=feature.observation_ids,
                kind=kind,
                severity=feature.severity,
                expected=feature.expected,
                actual=assessment.actual
                if assessment
                else "Required observation was not evaluated.",
                comparison=feature.comparison,
                route=ROUTES[kind],
            )
        )
    # Technical/calibration/missing evidence must be resolved before geometry is blamed.
    priorities = [
        "technical_recovery",
        "calibration",
        "evidence_required",
        "structural_reentry",
        "parametric_revision",
        "material_revision",
    ]
    action = next(
        (route for route in priorities if any(f.route == route for f in findings)), "quality_ready"
    )
    outcome = (
        "unscorable"
        if any(f.kind == "missing_evidence" for f in findings)
        else "needs_revision"
        if findings
        else "visually_satisfied"
    )
    return FidelityEvaluationV01(
        hypothesis=review.hypothesis,
        visual_review=review_artifact,
        legacy_direct_score=legacy_direct_score,
        required_features=required,
        satisfied_features=satisfied,
        findings=findings,
        outcome=outcome,
        next_action=action,
    )


def evaluate_review_file(root: Path, review_path: Path, output: Path) -> FidelityArtifact:
    """Validate actual inputs and publish one recomputable nonhuman evaluation companion."""

    review_artifact = artifact_at(root, review_path)
    review = VisualFindingSetV01.model_validate_json(read_artifact(root, review_artifact))
    hypothesis = ModelingHypothesisV01.model_validate_json(read_artifact(root, review.hypothesis))
    report = validate_review_evidence(root, hypothesis, review)
    result = evaluate_review(
        hypothesis,
        review,
        review_artifact=review_artifact,
        legacy_direct_score=report.direct_metrics.overall_direct_score,
    )
    return publish(root, output, result)


def compare_evaluations(
    before: FidelityEvaluationV01,
    after: FidelityEvaluationV01,
    *,
    before_artifact: FidelityArtifact,
    after_artifact: FidelityArtifact,
    before_review: VisualFindingSetV01,
    after_review: VisualFindingSetV01,
) -> FidelityComparisonV01:
    """Require paired camera/conditions and actual defect resolution, without score gaming."""

    comparable = (
        before.hypothesis == after.hypothesis
        and before_review.reference == after_review.reference
        and before_review.evidence.camera_fingerprint == after_review.evidence.camera_fingerprint
        and before_review.evidence.resolution == after_review.evidence.resolution
        and before_review.evidence.render_engine == after_review.evidence.render_engine
    )
    previous = {item.feature_id for item in before.findings}
    current = {item.feature_id for item in after.findings}
    resolved = sorted(previous - current) if comparable else []
    regressed = sorted(current - previous) if comparable else []
    unresolved = sorted(item.feature_id for item in after.findings if item.severity != "minor")
    outcome = (
        "incomparable"
        if not comparable
        else "regressed"
        if regressed
        else "improved"
        if resolved and not unresolved
        else "partially_improved"
        if resolved
        else "unchanged"
    )
    return FidelityComparisonV01(
        before=before_artifact,
        after=after_artifact,
        resolved_features=resolved,
        regressed_features=regressed,
        unresolved_major_features=unresolved,
        direct_score_delta=after.legacy_direct_score - before.legacy_direct_score,
        outcome=outcome,
        reason=(
            "Same frozen observations and comparison conditions are required; improvement "
            "requires resolved features without new defects or unresolved major errors."
        ),
    )


def compare_evaluation_files(
    root: Path, *, before_path: Path, after_path: Path, output: Path
) -> FidelityArtifact:
    """Revalidate both actual render sets and publish a fair, source-bound comparison."""

    artifacts = [artifact_at(root, path) for path in (before_path, after_path)]
    evaluations = [
        FidelityEvaluationV01.model_validate_json(read_artifact(root, item)) for item in artifacts
    ]
    reviews = []
    for evaluation in evaluations:
        review = VisualFindingSetV01.model_validate_json(
            read_artifact(root, evaluation.visual_review)
        )
        hypothesis = ModelingHypothesisV01.model_validate_json(
            read_artifact(root, evaluation.hypothesis)
        )
        qa = validate_review_evidence(root, hypothesis, review)
        if evaluation != evaluate_review(
            hypothesis,
            review,
            review_artifact=evaluation.visual_review,
            legacy_direct_score=qa.direct_metrics.overall_direct_score,
        ):
            raise ValueError("comparison evaluation differs from its exact visual review")
        reviews.append(review)
    # Lighting belongs to the fixed comparison conditions, not a geometry improvement.
    if _comparison_conditions(root, reviews[0]) != _comparison_conditions(root, reviews[1]):
        raise ValueError("comparison lighting changed; re-render both sources under one condition")
    result = compare_evaluations(
        *evaluations,
        before_artifact=artifacts[0],
        after_artifact=artifacts[1],
        before_review=reviews[0],
        after_review=reviews[1],
    )
    return publish(root, output, result)
