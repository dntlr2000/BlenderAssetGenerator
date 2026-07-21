from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from ..models import SceneSpec
from ..qa.camera_fingerprint import require_camera_fingerprint
from ..qa.models import VisualQAReport
from ..revision import (
    RevisionOperation,
    RevisionPlan,
    apply_revision_plan,
    load_revision_plan,
)
from ..workspace import sha256_file
from .approval import consume_revision_approval, load_revision_approval
from .models import (
    RevisionCandidate,
    RevisionCandidates,
    require_complete_group_candidate_selection,
)

_GROUP_FINDING_PREFIX = "direct.group_position."


def _operation_signature(
    *,
    target_type: str,
    target_id: str | None,
    path: list[str | int],
    op: str,
    value: Any,
) -> str:
    """Serialize an operation canonically for candidate-to-plan equality checks."""

    return json.dumps(
        {
            "target_type": target_type,
            "target_id": target_id,
            "path": path,
            "op": op,
            "value": value,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _candidate_signature(candidate: RevisionCandidate) -> str:
    """Return the executable signature represented by one approved candidate."""

    return _operation_signature(
        target_type=candidate.target_type,
        target_id=candidate.target_id,
        path=candidate.path,
        op=candidate.op,
        value=candidate.value,
    )


def _plan_signature(operation: RevisionOperation) -> str:
    """Return the executable signature represented by one RevisionPlan operation."""

    return _operation_signature(
        target_type=operation.target_type,
        target_id=operation.target_id,
        path=operation.path,
        op=operation.op,
        value=operation.value,
    )


def _paths_overlap(
    left: tuple[str | int, ...],
    right: tuple[str | int, ...],
) -> bool:
    """Return whether two revision paths are equal or one is an ancestor of the other."""

    shared_length = min(len(left), len(right))
    return left[:shared_length] == right[:shared_length]


def _group_candidate_displacement(
    candidate: RevisionCandidate,
    objects: dict[str, Any],
) -> tuple[float, float, float]:
    """Validate one group member operation and return its current-to-proposed delta."""

    if (
        candidate.target_type != "object"
        or candidate.target_id not in objects
        or candidate.path != ["transform", "location"]
        or candidate.op != "set"
        or set(candidate.evidence_sources) != {"direct_reference"}
    ):
        raise ValueError(
            "coherent group-position members must be direct-reference object "
            f"transform.location set operations: {candidate.id}"
        )
    if (
        not isinstance(candidate.value, list)
        or len(candidate.value) != 3
        or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in candidate.value
        )
    ):
        raise ValueError(
            f"coherent group-position candidate has an invalid location: {candidate.id}"
        )
    current = objects[str(candidate.target_id)].transform.location
    return tuple(float(candidate.value[index]) - current[index] for index in range(3))


def _require_source_report_integrity(
    candidates: RevisionCandidates,
    candidates_path: Path,
    scene_spec_path: Path,
) -> VisualQAReport:
    """Rebind group candidates to the unchanged sibling report and its declared displacement."""

    report_path = candidates_path.with_name("visual_qa_report.json")
    if not report_path.is_file():
        raise FileNotFoundError(f"Source visual QA report is missing: {report_path}")
    if sha256_file(report_path) != candidates.source_report_sha256:
        raise ValueError("source visual QA report changed after candidates were generated")
    report = VisualQAReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    if report.job_id != candidates.job_id:
        raise ValueError("source visual QA report job_id does not match candidates")
    if report.camera_fingerprint != candidates.camera_fingerprint:
        raise ValueError("source visual QA report camera does not match candidates")

    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    objects = {item.id: item for item in spec.objects}
    group_findings: dict[str, Any] = {}
    for finding in report.findings:
        if not finding.id.startswith(_GROUP_FINDING_PREFIX):
            continue
        if finding.id in group_findings:
            raise ValueError(f"duplicate group finding in source report: {finding.id}")
        group_findings[finding.id] = finding
    group_candidates: dict[str, list[RevisionCandidate]] = {}
    for candidate in candidates.candidates:
        if candidate.finding_id.startswith(_GROUP_FINDING_PREFIX):
            group_candidates.setdefault(candidate.finding_id, []).append(candidate)
    if set(group_findings) != set(group_candidates):
        raise ValueError("group findings and candidate bundles do not match exactly")

    for finding_id, finding in sorted(group_findings.items()):
        members = group_candidates[finding_id]
        finding_targets = list(finding.target_ids)
        candidate_targets = [str(candidate.target_id) for candidate in members]
        if (
            len(finding_targets) != len(set(finding_targets))
            or len(candidate_targets) != len(set(candidate_targets))
            or set(finding_targets) != set(candidate_targets)
        ):
            raise ValueError(
                "group finding target_ids do not match the complete candidate bundle: "
                f"{finding_id}"
            )
        expected_values = [
            finding.metrics.get("world_displacement_x"),
            finding.metrics.get("world_displacement_y"),
            finding.metrics.get("world_displacement_z"),
        ]
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in expected_values
        ):
            raise ValueError(f"group finding displacement is invalid: {finding_id}")
        expected = tuple(float(value) for value in expected_values)  # type: ignore[arg-type]
        for candidate in members:
            expected_prefix = f"candidate.{finding_id}.member."
            if not candidate.id.startswith(expected_prefix):
                raise ValueError(f"group candidate ID namespace is invalid: {candidate.id}")
            actual = _group_candidate_displacement(candidate, objects)
            if not all(
                math.isclose(
                    actual[index],
                    expected[index],
                    rel_tol=0.0,
                    abs_tol=1e-6,
                )
                for index in range(3)
            ):
                raise ValueError(
                    "group candidate delta does not match source report displacement: "
                    f"{candidate.id}"
                )
    return report


def _require_selected_candidate_integrity(
    candidates: RevisionCandidates,
    selected: list[RevisionCandidate],
    scene_spec_path: Path,
) -> None:
    """Validate atomic group bundles and reject conflicting edits to one target path."""

    selected_ids = [candidate.id for candidate in selected]
    require_complete_group_candidate_selection(candidates, selected_ids)
    conflicts: list[str] = []
    for index, left in enumerate(selected):
        for right in selected[index + 1 :]:
            if (
                left.target_type == right.target_type
                and left.target_id == right.target_id
                and _paths_overlap(tuple(left.path), tuple(right.path))
            ):
                conflicts.append(f"{left.id} <-> {right.id}")
    if conflicts:
        raise ValueError(
            "selected revision candidates contain conflicting target/path edits: "
            f"{sorted(conflicts)}"
        )

    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    objects = {item.id: item for item in spec.objects}
    grouped: dict[str, list[RevisionCandidate]] = {}
    for candidate in selected:
        if candidate.finding_id.startswith(_GROUP_FINDING_PREFIX):
            grouped.setdefault(candidate.finding_id, []).append(candidate)
    for finding_id, members in sorted(grouped.items()):
        if len(members) < 2:
            raise ValueError(f"coherent group-position bundle is too small: {finding_id}")
        displacements = [
            _group_candidate_displacement(candidate, objects) for candidate in members
        ]
        expected = displacements[0]
        if any(
            not all(
                math.isclose(
                    actual[index],
                    expected[index],
                    rel_tol=0.0,
                    abs_tol=1e-6,
                )
                for index in range(3)
            )
            for actual in displacements[1:]
        ):
            raise ValueError(
                "coherent group-position candidates do not share one world displacement: "
                f"{finding_id}"
            )


def compile_revision_plan(
    *,
    candidates_path: Path,
    scene_spec_path: Path,
    selected_candidate_ids: list[str],
    request: str,
    output_path: Path,
) -> RevisionPlan:
    """Compile only safe, selected QA candidates into the existing RevisionPlan contract."""

    candidates = RevisionCandidates.model_validate_json(
        candidates_path.read_text(encoding="utf-8")
    )
    if sha256_file(scene_spec_path) != candidates.base_spec_sha256:
        raise ValueError("revision candidates are stale relative to the current SceneSpec")
    require_camera_fingerprint(scene_spec_path, candidates.camera_fingerprint)
    _require_source_report_integrity(candidates, candidates_path, scene_spec_path)
    by_id = {candidate.id: candidate for candidate in candidates.candidates}
    missing = sorted(set(selected_candidate_ids) - set(by_id))
    if missing:
        raise ValueError(f"selected revision candidates do not exist: {missing}")
    if len(selected_candidate_ids) != len(set(selected_candidate_ids)):
        raise ValueError("selected revision candidate IDs must be unique")
    selected = [by_id[candidate_id] for candidate_id in selected_candidate_ids]
    _require_selected_candidate_integrity(candidates, selected, scene_spec_path)
    manual = [
        candidate.id
        for candidate in selected
        if candidate.applicability == "manual_required"
    ]
    if manual:
        raise ValueError(f"manual_required candidates cannot be compiled: {manual}")
    plan = RevisionPlan(
        job_id=candidates.job_id,
        base_spec_sha256=candidates.base_spec_sha256,
        request=request,
        operations=[
            RevisionOperation(
                op=candidate.op,
                target_type=candidate.target_type,
                target_id=candidate.target_id,
                path=candidate.path,
                value=candidate.value,
                reason=candidate.reason,
            )
            for candidate in selected
        ],
        acceptance_criteria=[
            criterion
            for candidate in selected
            for criterion in candidate.acceptance_criteria
        ],
        assumptions=[
            "Only explicitly approved QA candidates may be applied.",
            "Generated image targets remain advisory and cannot independently authorize edits.",
        ],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(plan.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return plan


def _index_by_id(raw: dict[str, Any], field: str) -> dict[str, dict[str, Any]]:
    """Index object or material records for strict untouched-subtree comparisons."""

    return {str(item["id"]): item for item in raw[field]}


def _require_locked_ids_unchanged(
    before: dict[str, Any],
    after: dict[str, Any],
    locked_ids: list[str],
) -> None:
    """Reject a revision if any QA-locked object or material subtree changed."""

    before_records = {**_index_by_id(before, "objects"), **_index_by_id(before, "materials")}
    after_records = {**_index_by_id(after, "objects"), **_index_by_id(after, "materials")}
    for semantic_id in locked_ids:
        if before_records.get(semantic_id) != after_records.get(semantic_id):
            raise ValueError(f"approved revision changed locked semantic ID: {semantic_id}")


def apply_approved_revision(
    *,
    scene_spec_path: Path,
    candidates_path: Path,
    plan_path: Path,
    approval_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Apply one exact approved plan, preserve locks, and consume approval after success."""

    candidates = RevisionCandidates.model_validate_json(
        candidates_path.read_text(encoding="utf-8")
    )
    approval = load_revision_approval(approval_path)
    plan = load_revision_plan(plan_path)
    if approval.used:
        raise ValueError(f"revision approval was already used: {approval.approval_id}")
    if approval.job_id != candidates.job_id or plan.job_id != candidates.job_id:
        raise ValueError("approval, candidates, and plan must belong to the same job")
    if sha256_file(candidates_path) != approval.candidates_sha256:
        raise ValueError("revision candidate file changed after approval")
    if sha256_file(plan_path) != approval.plan_sha256:
        raise ValueError("revision plan changed after approval")
    if sha256_file(scene_spec_path) != approval.base_spec_sha256:
        raise ValueError("SceneSpec changed after revision approval")
    if candidates.base_spec_sha256 != approval.base_spec_sha256:
        raise ValueError("candidate base hash does not match revision approval")
    require_camera_fingerprint(scene_spec_path, candidates.camera_fingerprint)
    _require_source_report_integrity(candidates, candidates_path, scene_spec_path)

    by_id = {candidate.id: candidate for candidate in candidates.candidates}
    missing = sorted(set(approval.approved_candidate_ids) - set(by_id))
    if missing:
        raise ValueError(f"revision approval references unknown candidates: {missing}")
    selected = [by_id[candidate_id] for candidate_id in approval.approved_candidate_ids]
    _require_selected_candidate_integrity(candidates, selected, scene_spec_path)
    if any(candidate.applicability == "manual_required" for candidate in selected):
        raise ValueError("revision approval contains a manual_required candidate")
    expected = Counter(_candidate_signature(candidate) for candidate in selected)
    actual = Counter(_plan_signature(operation) for operation in plan.operations)
    if expected != actual:
        raise ValueError("RevisionPlan operations do not exactly match approved candidates")

    before = json.loads(scene_spec_path.read_text(encoding="utf-8"))
    _validated, report = apply_revision_plan(
        scene_spec_path=scene_spec_path,
        plan_path=plan_path,
        output_path=output_path,
    )
    after = json.loads(output_path.read_text(encoding="utf-8"))
    selected_targets = {
        candidate.target_id for candidate in selected if candidate.target_id is not None
    }
    all_semantic_ids = {
        str(item["id"])
        for field in ("objects", "materials")
        for item in before[field]
    }
    dynamic_locks = sorted((all_semantic_ids - selected_targets) | set(candidates.locked_ids))
    _require_locked_ids_unchanged(before, after, dynamic_locks)
    if before["camera"] != after["camera"]:
        raise ValueError("approved visual QA revision changed the fixed comparison camera")
    consumed = consume_revision_approval(approval_path)
    return {
        **report,
        "approval_id": consumed.approval_id,
        "approval_used": consumed.used,
        "approved_candidate_ids": consumed.approved_candidate_ids,
    }
