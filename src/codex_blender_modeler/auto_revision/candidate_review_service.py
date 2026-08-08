"""Isolated before/after revision evaluation with one final promotion approval."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from ..blender_artifacts import stable_json_digest, write_json_atomic
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..constraints.evaluator import evaluate_constraint_set, load_constraints
from ..models import SceneSpec
from ..qa.models import VisualQAReport, VisualQARequest
from ..qa.multiview_sanity import (
    plan_job_assembly_multiview_sanity_for_sources,
    run_job_assembly_multiview_sanity,
)
from ..qa.request import validate_visual_qa_request
from ..qa.service import run_scene_spec_visual_qa_snapshot
from ..qa.structural_regression import (
    compare_assembly_sanity_terminals,
    terminal_evidence_from_run_result,
)
from ..revision import RevisionPlan, apply_revision_plan, load_revision_plan
from ..workspace import (
    current_job_write_lock_owner,
    job_dir,
    replace_scene_spec_if_current,
    sha256_file,
)
from .candidate_review_models import (
    CandidateReviewApproval,
    CandidateReviewArtifact,
    CandidateReviewDecision,
    CandidateReviewPromotionReceipt,
    CandidateReviewScore,
)
from .convergence import evaluate_convergence

_TRIAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_ALLOWED_PATH_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("transform", "location"),
    ("transform", "rotation_deg"),
    ("transform", "scale"),
    ("geometry", "dimensions"),
    ("geometry", "depth"),
    ("geometry", "size"),
    ("geometry", "bevel_depth"),
    ("geometry", "skirt_depth"),
)


class CandidateReviewConflict(RuntimeError):
    """Report stale or tampered candidate-review evidence without changing canonical data."""


def _utc_now() -> datetime:
    """Return one timezone-aware UTC timestamp for immutable review evidence."""

    return datetime.now(UTC)


def _validate_trial_id(value: str) -> str:
    """Reject non-portable or traversal-capable candidate-review trial IDs."""

    if not _TRIAL_ID_RE.fullmatch(value):
        raise ValueError("trial_id must match [a-z0-9][a-z0-9._-]{0,95}")
    return value


def _resolve_job_relative(root: Path, value: str) -> Path:
    """Resolve one normalized job-relative path without allowing workspace escape."""

    if not value or "\\" in value or ":" in value or value.startswith("/"):
        raise ValueError("candidate-review path must be normalized job-relative POSIX")
    parts = PurePosixPath(value).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("candidate-review path must not escape the job")
    path = (root.resolve() / Path(*parts)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("candidate-review path escapes the job") from exc
    return path


def _job_relative(root: Path, path: Path) -> str:
    """Serialize one exact artifact path relative to the owning job."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"candidate-review artifact is outside the job: {path}") from exc


def _artifact(root: Path, path: Path) -> CandidateReviewArtifact:
    """Create one immutable path/hash binding for a candidate-review artifact."""

    if not path.is_file():
        raise FileNotFoundError(path)
    return CandidateReviewArtifact(
        path=_job_relative(root, path),
        sha256=sha256_file(path),
    )


def _write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    """Publish one JSON artifact once and reject accidental evidence replacement."""

    if path.exists():
        raise FileExistsError(f"candidate-review evidence already exists: {path}")
    write_json_atomic(path, payload)


def _collect_source_hashes(root: Path, job_id: str, scene_spec_path: Path) -> dict[str, str]:
    """Collect every build/reference/constraint source that must remain current at promotion."""

    provenance = collect_build_provenance(root, job_id, scene_spec_path=scene_spec_path)
    collected: dict[str, str] = {_job_relative(root, scene_spec_path): sha256_file(scene_spec_path)}

    def visit(value: Any) -> None:
        """Traverse provenance records and collect exact paired path/hash fields."""

        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_path") and isinstance(item, str):
                    hash_key = f"{key[:-5]}_sha256"
                    digest = value.get(hash_key)
                    if isinstance(digest, str) and len(digest) == 64:
                        collected[item] = digest
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(provenance)
    geometry_hashes = provenance.get("geometry_payloads_sha256", {})
    if isinstance(geometry_hashes, dict):
        for path, digest in geometry_hashes.items():
            if isinstance(path, str) and isinstance(digest, str):
                collected[path] = digest
    materials = provenance.get("materials", {})
    if isinstance(materials, dict):
        for record in materials.values():
            if not isinstance(record, dict):
                continue
            channels = record.get("texture_channels", {})
            if isinstance(channels, dict):
                for channel in channels.values():
                    if isinstance(channel, dict):
                        path = channel.get("path")
                        digest = channel.get("sha256")
                        if isinstance(path, str) and isinstance(digest, str):
                            collected[path] = digest
    for source in sorted((root / "input").rglob("*")):
        if source.is_file():
            collected[_job_relative(root, source)] = sha256_file(source)
    for optional in (
        root / "analysis" / "modeling_plan.json",
        root / "constraints" / "constraints.json",
    ):
        if optional.is_file():
            collected[_job_relative(root, optional)] = sha256_file(optional)
    return dict(sorted(collected.items()))


def _validate_review_plan(plan: RevisionPlan, baseline: SceneSpec) -> None:
    """Restrict candidate review to bounded existing-object parametric geometry edits."""

    if len(plan.operations) > 24:
        raise ValueError("candidate_review permits at most 24 bounded operations")
    object_ids = {item.id for item in baseline.objects}
    for operation in plan.operations:
        if operation.target_type != "object" or operation.target_id not in object_ids:
            raise ValueError(
                "candidate_review permits only existing object targets; use manual_guarded "
                "for camera, scene, material, add/remove, or redesign work"
            )
        if operation.op not in {"set", "add", "multiply"}:
            raise ValueError("candidate_review permits only set, add, or multiply operations")
        normalized = tuple(str(part) for part in operation.path if isinstance(part, str))
        if not any(normalized[: len(prefix)] == prefix for prefix in _ALLOWED_PATH_PREFIXES):
            raise ValueError(
                f"candidate_review path is outside the bounded geometry envelope: {operation.path}"
            )
        if operation.path[:2] == ["geometry", "path"]:
            raise ValueError("candidate_review cannot edit custom-mesh payload paths")
        if isinstance(operation.value, float) and not math.isfinite(operation.value):
            raise ValueError("candidate_review numeric values must be finite")


def _validate_candidate_invariants(baseline: SceneSpec, candidate: SceneSpec) -> None:
    """Require stable camera, source, object, material, and semantic identity contracts."""

    if baseline.job_id != candidate.job_id:
        raise ValueError("candidate SceneSpec belongs to another job")
    if baseline.camera != candidate.camera:
        raise ValueError("candidate_review locks the comparison camera")
    if baseline.sources != candidate.sources:
        raise ValueError("candidate_review cannot change immutable reference sources")
    if baseline.materials != candidate.materials:
        raise ValueError("candidate_review cannot change material identities or contracts")
    baseline_ids = [item.id for item in baseline.objects]
    candidate_ids = [item.id for item in candidate.objects]
    if baseline_ids != candidate_ids:
        raise ValueError("candidate_review cannot add, remove, or reorder semantic objects")
    for before, after in zip(baseline.objects, candidate.objects, strict=True):
        if before.material_id != after.material_id:
            raise ValueError(f"candidate_review changed material identity for {before.id}")
        before_geometry = before.geometry.model_dump(mode="json")
        after_geometry = after.geometry.model_dump(mode="json")
        if before_geometry.get("kind") == "custom_mesh" and (
            before_geometry.get("path") != after_geometry.get("path")
            or before_geometry.get("vertices") != after_geometry.get("vertices")
            or before_geometry.get("faces") != after_geometry.get("faces")
        ):
            raise ValueError("candidate_review cannot edit custom-mesh payloads or vertices")


def _build_candidate_scene(
    root: Path,
    scene_spec_path: Path,
    output_root: Path,
) -> tuple[Path, Path, Path]:
    """Build, inspect, and structurally validate one isolated SceneSpec candidate."""

    output_root.mkdir(parents=True, exist_ok=False)
    blend_path = output_root / "scene.blend"
    inventory_path = output_root / "scene_inventory.json"
    validation_path = output_root / "validation.json"
    run_blender(
        "build_scene.py",
        [
            "--spec",
            str(scene_spec_path),
            "--job-root",
            str(root),
            "--output",
            str(blend_path),
        ],
    )
    run_blender(
        "inspect_scene.py",
        ["--output", str(inventory_path)],
        blend_file=blend_path,
    )
    run_blender(
        "validate_scene.py",
        ["--spec", str(scene_spec_path), "--output", str(validation_path)],
        blend_file=blend_path,
    )
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if not isinstance(validation, dict) or validation.get("ok") is not True:
        raise RuntimeError("candidate-review scene validation did not report ok=true")
    return blend_path, inventory_path, validation_path


def _evaluate_constraints(
    root: Path,
    inventory_path: Path,
    output_path: Path,
) -> Path | None:
    """Evaluate optional measured constraints against one isolated inventory snapshot."""

    constraints_path = root / "constraints" / "constraints.json"
    if not constraints_path.is_file():
        return None
    constraint_set = load_constraints(constraints_path)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    solution = evaluate_constraint_set(constraint_set, inventory)
    write_json_atomic(output_path, solution.model_dump(mode="json"))
    return output_path


def _constraint_payload(path: Path | None) -> tuple[int, list[dict[str, Any]] | None]:
    """Return failed count and result records from one optional constraint solution."""

    if path is None:
        return 0, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return int(payload.get("failed", 0)) + int(payload.get("missing", 0)), payload.get(
        "results", []
    )


def _assembly_policy(root: Path) -> str:
    """Read the authored assembly policy without requiring it for legacy jobs."""

    path = root / "analysis" / "modeling_plan.json"
    if not path.is_file():
        return "legacy_unbound"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return str(payload.get("assembly_consistency_policy", "legacy_unbound"))


def _run_structural_comparison(
    root: Path,
    job_id: str,
    trial_id: str,
    baseline_spec: Path,
    baseline_blend: Path,
    candidate_spec: Path,
    candidate_blend: Path,
    output_path: Path,
) -> Path | None:
    """Run the exact five-view veto guard for authored spatial-v1 assets."""

    if _assembly_policy(root) != "spatial_v1":
        return None
    token = stable_json_digest({"job": job_id, "trial": trial_id})[:10]
    baseline_run_id = f"cr-{token}-baseline"
    candidate_run_id = f"cr-{token}-candidate"
    baseline_plan = plan_job_assembly_multiview_sanity_for_sources(
        job_id,
        scene_spec_path=baseline_spec,
        blend_path=baseline_blend,
        run_id=baseline_run_id,
    )
    candidate_plan = plan_job_assembly_multiview_sanity_for_sources(
        job_id,
        scene_spec_path=candidate_spec,
        blend_path=candidate_blend,
        run_id=candidate_run_id,
    )
    baseline_result = run_job_assembly_multiview_sanity(
        job_id,
        baseline_run_id,
        plan_sha256=str(baseline_plan["plan_sha256"]),
    )
    candidate_result = run_job_assembly_multiview_sanity(
        job_id,
        candidate_run_id,
        plan_sha256=str(candidate_plan["plan_sha256"]),
    )
    comparison = compare_assembly_sanity_terminals(
        root,
        baseline=terminal_evidence_from_run_result(root, baseline_result),
        result=terminal_evidence_from_run_result(root, candidate_result),
        expected_job_id=job_id,
    )
    write_json_atomic(output_path, comparison.model_dump(mode="json"))
    return output_path


def _source_current(root: Path, source_hashes: dict[str, str]) -> bool:
    """Return whether every hash-bound source still matches the decision input map."""

    for relative, expected in source_hashes.items():
        path = _resolve_job_relative(root, relative)
        if not path.is_file() or sha256_file(path) != expected:
            return False
    return True


def validate_candidate_review_decision(
    root: Path,
    decision_path: Path,
    *,
    require_current_sources: bool,
) -> CandidateReviewDecision:
    """Validate immutable decision artifacts and optionally require current canonical sources."""

    decision = CandidateReviewDecision.model_validate_json(
        decision_path.read_text(encoding="utf-8")
    )
    if decision.job_id != root.name:
        raise ValueError("candidate-review decision belongs to another job")
    artifact_fields = (
        "revision_plan",
        "baseline_scene_spec",
        "candidate_scene_spec",
        "revision_diff",
        "baseline_blend",
        "candidate_blend",
        "baseline_inventory",
        "candidate_inventory",
        "baseline_validation",
        "candidate_validation",
        "baseline_qa_report",
        "candidate_qa_report",
        "baseline_qa_request",
        "candidate_qa_request",
        "baseline_qa_manifest",
        "candidate_qa_manifest",
        "baseline_constraints",
        "candidate_constraints",
        "structural_comparison",
    )
    for field in artifact_fields:
        artifact = getattr(decision, field)
        if artifact is None:
            continue
        path = _resolve_job_relative(root, artifact.path)
        if not path.is_file() or sha256_file(path) != artifact.sha256:
            raise CandidateReviewConflict(
                f"candidate-review artifact is missing or changed: {artifact.path}"
            )
    baseline_report = VisualQAReport.model_validate_json(
        _resolve_job_relative(root, decision.baseline_qa_report.path).read_text(encoding="utf-8")
    )
    candidate_report = VisualQAReport.model_validate_json(
        _resolve_job_relative(root, decision.candidate_qa_report.path).read_text(encoding="utf-8")
    )
    if baseline_report.camera_fingerprint != candidate_report.camera_fingerprint:
        raise CandidateReviewConflict("candidate-review comparison camera changed")
    for request_artifact, report, scene_artifact, manifest_artifact in (
        (
            decision.baseline_qa_request,
            baseline_report,
            decision.baseline_scene_spec,
            decision.baseline_qa_manifest,
        ),
        (
            decision.candidate_qa_request,
            candidate_report,
            decision.candidate_scene_spec,
            decision.candidate_qa_manifest,
        ),
    ):
        request_path = _resolve_job_relative(root, request_artifact.path)
        request = VisualQARequest.model_validate_json(request_path.read_text(encoding="utf-8"))
        if report.request_sha256 != sha256_file(request_path):
            raise CandidateReviewConflict("candidate-review QA report request hash changed")
        manifest = validate_visual_qa_request(
            request,
            scene_spec_path=_resolve_job_relative(root, scene_artifact.path),
            job_root=root,
        )
        if (
            sha256_file(_resolve_job_relative(root, manifest_artifact.path))
            != request.render_pass_manifest_sha256
        ):
            raise CandidateReviewConflict("candidate-review QA manifest binding changed")
        if manifest.run_id != report.run_id:
            raise CandidateReviewConflict("candidate-review QA run identities do not match")
    if require_current_sources and not _source_current(root, decision.source_hashes):
        raise CandidateReviewConflict(
            "candidate-review canonical or source fingerprint changed before promotion"
        )
    return decision


def evaluate_candidate_review(
    job_id: str,
    *,
    trial_id: str,
    revision_plan_path: str | Path,
    input_fingerprint: str,
    workflow_id: str | None = None,
    minimum_improvement: float = 0.001,
) -> CandidateReviewDecision:
    """Evaluate one RevisionPlan in isolation and write an exact promotion decision."""

    selected_trial_id = _validate_trial_id(trial_id)
    if len(input_fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in input_fingerprint
    ):
        raise ValueError("candidate-review input fingerprint must be lowercase SHA-256")
    root = job_dir(job_id).resolve()
    canonical_path = root / "analysis" / "scene_spec.json"
    plan_path = (
        Path(revision_plan_path).expanduser().resolve()
        if Path(revision_plan_path).is_absolute()
        else _resolve_job_relative(root, str(revision_plan_path))
    )
    _job_relative(root, plan_path)
    trial_root = root / "qa" / "candidate_reviews" / selected_trial_id
    if trial_root.exists():
        raise FileExistsError(f"candidate-review trial already exists: {selected_trial_id}")
    baseline = SceneSpec.model_validate_json(canonical_path.read_text(encoding="utf-8"))
    plan = load_revision_plan(plan_path)
    if plan.job_id != job_id or plan.base_spec_sha256 != sha256_file(canonical_path):
        raise CandidateReviewConflict("candidate-review RevisionPlan is stale or mismatched")
    _validate_review_plan(plan, baseline)
    source_hashes = _collect_source_hashes(root, job_id, canonical_path)
    trial_root.mkdir(parents=True, exist_ok=False)
    baseline_spec_path = trial_root / "baseline" / "scene_spec.json"
    candidate_spec_path = trial_root / "candidate" / "scene_spec.json"
    baseline_spec_path.parent.mkdir(parents=True)
    candidate_spec_path.parent.mkdir(parents=True)
    baseline_spec_path.write_bytes(canonical_path.read_bytes())
    candidate, diff = apply_revision_plan(
        scene_spec_path=baseline_spec_path,
        plan_path=plan_path,
        output_path=candidate_spec_path,
    )
    _validate_candidate_invariants(baseline, candidate)
    diff_path = trial_root / "revision_diff.json"
    write_json_atomic(diff_path, diff)
    baseline_blend, baseline_inventory, baseline_validation = _build_candidate_scene(
        root,
        baseline_spec_path,
        trial_root / "baseline" / "build",
    )
    candidate_blend, candidate_inventory, candidate_validation = _build_candidate_scene(
        root,
        candidate_spec_path,
        trial_root / "candidate" / "build",
    )
    baseline_qa = run_scene_spec_visual_qa_snapshot(
        job_id,
        scene_spec_path=baseline_spec_path,
        blend_path=baseline_blend,
        run_dir=trial_root / "baseline" / "qa",
        run_id=f"cr-{selected_trial_id[:40]}-baseline",
    )
    candidate_qa = run_scene_spec_visual_qa_snapshot(
        job_id,
        scene_spec_path=candidate_spec_path,
        blend_path=candidate_blend,
        run_dir=trial_root / "candidate" / "qa",
        run_id=f"cr-{selected_trial_id[:40]}-candidate",
    )
    baseline_constraints = _evaluate_constraints(
        root,
        baseline_inventory,
        trial_root / "baseline" / "constraint_solution.json",
    )
    candidate_constraints = _evaluate_constraints(
        root,
        candidate_inventory,
        trial_root / "candidate" / "constraint_solution.json",
    )
    structural_path = _run_structural_comparison(
        root,
        job_id,
        selected_trial_id,
        baseline_spec_path,
        baseline_blend,
        candidate_spec_path,
        candidate_blend,
        trial_root / "structural_comparison.json",
    )
    changed_ids = sorted(
        {
            str(item["target_id"])
            for item in diff["changes"]
            if item.get("target_type") == "object" and item.get("target_id")
        }
    )
    preserved_ids = sorted({item.id for item in baseline.objects} - set(changed_ids))
    before_failed, before_results = _constraint_payload(baseline_constraints)
    after_failed, after_results = _constraint_payload(candidate_constraints)
    convergence = evaluate_convergence(
        before_report_path=Path(str(baseline_qa["visual_qa_report"])),
        after_report_path=Path(str(candidate_qa["visual_qa_report"])),
        changed_ids=changed_ids,
        preserved_ids=preserved_ids,
        before_failed_constraints=before_failed,
        after_failed_constraints=after_failed,
        before_constraint_results=before_results,
        after_constraint_results=after_results,
        multiview_comparison_path=structural_path,
        minimum_improvement=minimum_improvement,
    )
    before_report = VisualQAReport.model_validate_json(
        Path(str(baseline_qa["visual_qa_report"])).read_text(encoding="utf-8")
    )
    after_report = VisualQAReport.model_validate_json(
        Path(str(candidate_qa["visual_qa_report"])).read_text(encoding="utf-8")
    )
    silhouette_delta = round(
        after_report.direct_metrics.silhouette_iou - before_report.direct_metrics.silhouette_iou,
        6,
    )
    silhouette_regressed = silhouette_delta < -0.000001
    accepted = convergence.accepted and not silhouette_regressed
    status = (
        "promotable"
        if accepted
        else "regressed"
        if convergence.status == "regressed" or silhouette_regressed
        else "not_improved"
    )
    blockers = [] if accepted else list(convergence.reasons)
    if silhouette_regressed:
        blockers.append("Fixed-camera silhouette IoU regressed during candidate evaluation.")
    decision = CandidateReviewDecision(
        job_id=job_id,
        trial_id=selected_trial_id,
        workflow_id=workflow_id,
        input_fingerprint=input_fingerprint,
        source_hashes=source_hashes,
        revision_plan=_artifact(root, plan_path),
        baseline_scene_spec=_artifact(root, baseline_spec_path),
        candidate_scene_spec=_artifact(root, candidate_spec_path),
        revision_diff=_artifact(root, diff_path),
        baseline_blend=_artifact(root, baseline_blend),
        candidate_blend=_artifact(root, candidate_blend),
        baseline_inventory=_artifact(root, baseline_inventory),
        candidate_inventory=_artifact(root, candidate_inventory),
        baseline_validation=_artifact(root, baseline_validation),
        candidate_validation=_artifact(root, candidate_validation),
        baseline_qa_report=_artifact(root, Path(str(baseline_qa["visual_qa_report"]))),
        candidate_qa_report=_artifact(root, Path(str(candidate_qa["visual_qa_report"]))),
        baseline_qa_request=_artifact(root, Path(str(baseline_qa["request"]))),
        candidate_qa_request=_artifact(root, Path(str(candidate_qa["request"]))),
        baseline_qa_manifest=_artifact(root, Path(str(baseline_qa["render_pass_manifest"]))),
        candidate_qa_manifest=_artifact(root, Path(str(candidate_qa["render_pass_manifest"]))),
        baseline_constraints=(
            _artifact(root, baseline_constraints) if baseline_constraints else None
        ),
        candidate_constraints=(
            _artifact(root, candidate_constraints) if candidate_constraints else None
        ),
        structural_comparison=(_artifact(root, structural_path) if structural_path else None),
        changed_ids=changed_ids,
        preserved_ids=preserved_ids,
        changed_paths=[list(item["path"]) for item in diff["changes"]],
        scores=CandidateReviewScore(
            baseline_direct_score=before_report.direct_metrics.overall_direct_score,
            candidate_direct_score=after_report.direct_metrics.overall_direct_score,
            direct_score_delta=convergence.score_delta,
            baseline_silhouette_iou=before_report.direct_metrics.silhouette_iou,
            candidate_silhouette_iou=after_report.direct_metrics.silhouette_iou,
            silhouette_delta=silhouette_delta,
            minimum_direct_improvement=minimum_improvement,
        ),
        status=status,  # type: ignore[arg-type]
        promotable=accepted,
        blockers=blockers,
        limitations=[
            "Candidate review evaluates bounded existing-object parameter edits only.",
            "The canonical SceneSpec remains unchanged until exact decision approval.",
            "Generated targets and material edits are excluded from promotion authority.",
        ],
        evaluated_at=_utc_now(),
    )
    decision_path = trial_root / "decision_manifest.json"
    _write_immutable_json(decision_path, decision.model_dump(mode="json"))
    validate_candidate_review_decision(
        root,
        decision_path,
        require_current_sources=True,
    )
    return decision


def approve_candidate_review(
    job_id: str,
    trial_id: str,
    *,
    decision_sha256: str,
    approval_note: str | None = None,
) -> CandidateReviewApproval:
    """Record one user approval bound only to the exact promotable decision manifest."""

    root = job_dir(job_id).resolve()
    selected_trial_id = _validate_trial_id(trial_id)
    trial_root = root / "qa" / "candidate_reviews" / selected_trial_id
    decision_path = trial_root / "decision_manifest.json"
    if not decision_path.is_file() or sha256_file(decision_path) != decision_sha256:
        raise CandidateReviewConflict("candidate-review decision SHA-256 is stale or wrong")
    decision = validate_candidate_review_decision(
        root,
        decision_path,
        require_current_sources=True,
    )
    if not decision.promotable:
        raise PermissionError("only a promotable candidate-review decision may be approved")
    approval = CandidateReviewApproval(
        approval_id=f"candidate-review-{uuid4().hex}",
        job_id=job_id,
        trial_id=selected_trial_id,
        decision_sha256=decision_sha256,
        baseline_scene_spec_sha256=decision.baseline_scene_spec.sha256,
        candidate_scene_spec_sha256=decision.candidate_scene_spec.sha256,
        approval_note=approval_note,
        approved_at=_utc_now(),
    )
    approval_path = trial_root / "promotion_approval.json"
    _write_immutable_json(approval_path, approval.model_dump(mode="json"))
    return approval


def validate_candidate_review_approval(
    root: Path,
    trial_id: str,
    *,
    require_current_sources: bool,
) -> tuple[CandidateReviewDecision, CandidateReviewApproval]:
    """Validate an exact promotion approval before or after its one-time consumption."""

    trial_root = root / "qa" / "candidate_reviews" / _validate_trial_id(trial_id)
    decision_path = trial_root / "decision_manifest.json"
    approval_path = trial_root / "promotion_approval.json"
    if not decision_path.is_file() or not approval_path.is_file():
        raise FileNotFoundError("candidate-review decision or approval is missing")
    decision = validate_candidate_review_decision(
        root,
        decision_path,
        require_current_sources=require_current_sources,
    )
    approval = CandidateReviewApproval.model_validate_json(
        approval_path.read_text(encoding="utf-8")
    )
    if (
        approval.job_id != decision.job_id
        or approval.trial_id != decision.trial_id
        or approval.decision_sha256 != sha256_file(decision_path)
        or approval.baseline_scene_spec_sha256 != decision.baseline_scene_spec.sha256
        or approval.candidate_scene_spec_sha256 != decision.candidate_scene_spec.sha256
    ):
        raise CandidateReviewConflict("candidate-review approval binding is inconsistent")
    if not decision.promotable:
        raise CandidateReviewConflict("candidate-review approval targets a rejected decision")
    return decision, approval


def _rebuild_canonical(root: Path, job_id: str) -> tuple[Path, Path, Path]:
    """Rebuild, inspect, and validate the newly promoted canonical authoring scene."""

    spec = root / "analysis" / "scene_spec.json"
    blend = root / "blender" / "scene.blend"
    inventory = root / "reports" / "scene_inventory.json"
    validation = root / "reports" / "validation.json"
    run_blender("build_scene.py", ["--spec", str(spec), "--output", str(blend)])
    run_blender(
        "inspect_scene.py",
        ["--output", str(inventory)],
        blend_file=blend,
    )
    run_blender(
        "validate_scene.py",
        ["--spec", str(spec), "--output", str(validation)],
        blend_file=blend,
    )
    payload = json.loads(validation.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("promoted candidate validation did not report ok=true")
    return blend, inventory, validation


def promote_candidate_review(
    job_id: str,
    trial_id: str,
    *,
    workflow_id: str | None = None,
) -> CandidateReviewPromotionReceipt:
    """Promote one approved candidate once, rebuilding canonical outputs or rolling back."""

    root = job_dir(job_id).resolve()
    selected_trial_id = _validate_trial_id(trial_id)
    trial_root = root / "qa" / "candidate_reviews" / selected_trial_id
    receipt_path = trial_root / "promotion_receipt.json"
    if receipt_path.exists():
        raise FileExistsError("candidate-review promotion receipt already exists")
    decision, approval = validate_candidate_review_approval(
        root,
        selected_trial_id,
        require_current_sources=True,
    )
    if approval.used:
        raise PermissionError("candidate-review approval has already been consumed")
    lock_owner = workflow_id or current_job_write_lock_owner(job_id)
    candidate_path = _resolve_job_relative(root, decision.candidate_scene_spec.path)
    approval_path = trial_root / "promotion_approval.json"
    approval_identity = stable_json_digest(
        approval.model_dump(mode="json", exclude={"used", "used_at"})
    )
    replacement = replace_scene_spec_if_current(
        job_id,
        candidate_path,
        expected_current_sha256=decision.baseline_scene_spec.sha256,
        expected_candidate_sha256=decision.candidate_scene_spec.sha256,
        lock_owner_id=lock_owner,
    )
    archived_value = replacement.get("archived_scene_spec")
    archived_path = Path(str(archived_value)).resolve() if archived_value else None
    status = "promoted"
    notes = ["Canonical SceneSpec was promoted from exact isolated candidate evidence."]
    try:
        blend, inventory, validation = _rebuild_canonical(root, job_id)
    except Exception as exc:
        baseline_path = _resolve_job_relative(root, decision.baseline_scene_spec.path)
        replace_scene_spec_if_current(
            job_id,
            baseline_path,
            expected_current_sha256=decision.candidate_scene_spec.sha256,
            expected_candidate_sha256=decision.baseline_scene_spec.sha256,
            lock_owner_id=lock_owner,
        )
        blend, inventory, validation = _rebuild_canonical(root, job_id)
        status = "rolled_back"
        notes.append(f"Promotion rebuild failed and canonical baseline was restored: {exc}")
    consumed = approval.model_copy(update={"used": True, "used_at": _utc_now()})
    write_json_atomic(approval_path, consumed.model_dump(mode="json"))
    final_spec = root / "analysis" / "scene_spec.json"
    provenance = collect_build_provenance(root, job_id, scene_spec_path=final_spec)
    receipt = CandidateReviewPromotionReceipt(
        job_id=job_id,
        trial_id=selected_trial_id,
        workflow_id=workflow_id,
        decision_sha256=sha256_file(trial_root / "decision_manifest.json"),
        approval_identity_sha256=approval_identity,
        previous_canonical_sha256=decision.baseline_scene_spec.sha256,
        candidate_scene_spec_sha256=decision.candidate_scene_spec.sha256,
        final_canonical_sha256=sha256_file(final_spec),
        archived_scene_spec=(_artifact(root, archived_path) if archived_path is not None else None),
        final_blend=_artifact(root, blend),
        final_inventory=_artifact(root, inventory),
        final_validation=_artifact(root, validation),
        final_build_fingerprint=str(provenance["fingerprint"]),
        status=status,  # type: ignore[arg-type]
        promoted_at=_utc_now(),
        notes=notes,
    )
    _write_immutable_json(receipt_path, receipt.model_dump(mode="json"))
    if status == "rolled_back":
        raise RuntimeError(notes[-1])
    return receipt


def get_candidate_review_status(job_id: str, trial_id: str) -> dict[str, Any]:
    """Report immutable review, approval, promotion, and current-source state."""

    root = job_dir(job_id).resolve()
    selected_trial_id = _validate_trial_id(trial_id)
    trial_root = root / "qa" / "candidate_reviews" / selected_trial_id
    decision_path = trial_root / "decision_manifest.json"
    approval_path = trial_root / "promotion_approval.json"
    receipt_path = trial_root / "promotion_receipt.json"
    report_path = trial_root / "candidate_review_report.pdf"
    report_manifest_path = trial_root / "candidate_review_report.manifest.json"
    decision: CandidateReviewDecision | None = None
    valid = False
    current = False
    if decision_path.is_file():
        try:
            decision = validate_candidate_review_decision(
                root,
                decision_path,
                require_current_sources=False,
            )
            valid = True
            current = _source_current(root, decision.source_hashes)
        except (OSError, ValueError, CandidateReviewConflict):
            valid = False
    approval = None
    if approval_path.is_file():
        try:
            approval = CandidateReviewApproval.model_validate_json(
                approval_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            approval = None
    receipt = None
    if receipt_path.is_file():
        try:
            receipt = CandidateReviewPromotionReceipt.model_validate_json(
                receipt_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            receipt = None
    report_valid = False
    if report_manifest_path.is_file():
        try:
            from .candidate_review_reporting import validate_candidate_review_pdf_manifest

            validate_candidate_review_pdf_manifest(root, report_manifest_path)
            report_valid = True
        except (OSError, ValueError):
            report_valid = False
    return {
        "job_id": job_id,
        "trial_id": selected_trial_id,
        "decision_exists": decision_path.is_file(),
        "decision_sha256": sha256_file(decision_path) if decision_path.is_file() else None,
        "decision_valid": valid,
        "sources_current": current,
        "decision_status": decision.status if decision is not None else None,
        "promotable": decision.promotable if decision is not None else False,
        "review_pdf_exists": report_path.is_file(),
        "review_pdf_path": (_job_relative(root, report_path) if report_path.is_file() else None),
        "review_pdf_sha256": sha256_file(report_path) if report_path.is_file() else None,
        "review_pdf_manifest_valid": report_valid,
        "approval_exists": approval_path.is_file(),
        "approval_used": approval.used if approval is not None else None,
        "promotion_status": receipt.status if receipt is not None else None,
        "promotion_receipt_sha256": (sha256_file(receipt_path) if receipt_path.is_file() else None),
    }
