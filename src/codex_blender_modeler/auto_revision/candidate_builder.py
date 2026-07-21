from __future__ import annotations

import math
from pathlib import Path

from ..models import SceneSpec
from ..qa.models import QAFinding, SuggestedEdit, VisualQAReport
from ..workspace import sha256_file
from .models import RevisionCandidate, RevisionCandidates

PathPart = str | int

_GROUP_FINDING_PREFIX = "direct.group_position."
_GROUP_DISPLACEMENT_KEYS = (
    "world_displacement_x",
    "world_displacement_y",
    "world_displacement_z",
)

_SAFE_OBJECT_PREFIXES: tuple[tuple[PathPart, ...], ...] = (
    ("transform", "location"),
    ("transform", "rotation_deg"),
    ("transform", "scale"),
    ("geometry", "dimensions"),
    ("geometry", "depth"),
    ("geometry", "profile"),
    ("geometry", "points"),
    ("geometry", "bevel_depth"),
    ("geometry", "size"),
    ("geometry", "heights"),
    ("geometry", "skirt_depth"),
)
_SAFE_MATERIAL_PREFIXES: tuple[tuple[PathPart, ...], ...] = (
    ("base_color",),
    ("roughness",),
    ("metallic",),
    ("emission_strength",),
)


def _matches_prefix(path: list[PathPart], prefix: tuple[PathPart, ...]) -> bool:
    """Return whether a candidate path begins with one allow-listed prefix."""

    return tuple(path[: len(prefix)]) == prefix


def _safe_applicability(finding: QAFinding, spec: SceneSpec) -> str:
    """Classify V0.6 suggestions while requiring approval for every executable edit."""

    suggestion = finding.suggestion
    if suggestion is None:
        return "manual_required"
    if set(finding.evidence_sources) == {"generated_target"}:
        return "manual_required"
    if suggestion.op == "append" or suggestion.target_type in {"camera", "scene"}:
        return "manual_required"
    if suggestion.target_type == "material":
        if not any(item.id == suggestion.target_id for item in spec.materials):
            return "manual_required"
        return (
            "approval_required"
            if any(_matches_prefix(suggestion.path, prefix) for prefix in _SAFE_MATERIAL_PREFIXES)
            else "manual_required"
        )
    target = next((item for item in spec.objects if item.id == suggestion.target_id), None)
    if target is None:
        return "manual_required"
    if target.geometry.kind == "custom_mesh" and suggestion.path[0] == "geometry":
        return "manual_required"
    return (
        "approval_required"
        if any(_matches_prefix(suggestion.path, prefix) for prefix in _SAFE_OBJECT_PREFIXES)
        else "manual_required"
    )


def _candidate_from_finding(
    finding: QAFinding,
    spec: SceneSpec,
) -> RevisionCandidate | None:
    """Convert an actionable QA finding into a guarded, still non-executable candidate."""

    suggestion = finding.suggestion
    if suggestion is None:
        return None
    applicability = _safe_applicability(finding, spec)
    return RevisionCandidate(
        id=f"candidate.{finding.id}",
        finding_id=finding.id,
        target_type=suggestion.target_type,
        target_id=suggestion.target_id,
        path=suggestion.path,
        op=suggestion.op,
        value=suggestion.value,
        reason=finding.description,
        evidence_sources=finding.evidence_sources,
        confidence=finding.confidence,
        applicability=applicability,
        acceptance_criteria=[f"Resolve QA finding {finding.id} without changing locked IDs."],
    )


def _group_candidates_from_finding(
    finding: QAFinding,
    spec: SceneSpec,
) -> list[RevisionCandidate] | None:
    """Expand one coherent group finding into atomic same-displacement member candidates."""

    if not finding.id.startswith(_GROUP_FINDING_PREFIX):
        return None
    if (
        finding.issue_type != "position"
        or "direct_reference" not in finding.evidence_sources
        or len(finding.target_ids) < 2
    ):
        return []
    displacement_values = [finding.metrics.get(key) for key in _GROUP_DISPLACEMENT_KEYS]
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        for value in displacement_values
    ):
        return []
    displacement = [float(value) for value in displacement_values]  # type: ignore[arg-type]
    objects = {item.id: item for item in spec.objects}
    if len(finding.target_ids) != len(set(finding.target_ids)):
        return []
    if any(target_id not in objects for target_id in finding.target_ids):
        return []

    candidates: list[RevisionCandidate] = []
    for target_id in sorted(finding.target_ids):
        target = objects[target_id]
        proposed = [
            round(target.transform.location[index] + displacement[index], 6)
            for index in range(3)
        ]
        member_finding = finding.model_copy(
            update={
                "target_ids": [target_id],
                "suggestion": SuggestedEdit(
                    target_type="object",
                    target_id=target_id,
                    path=["transform", "location"],
                    op="set",
                    value=proposed,
                ),
            }
        )
        candidate = _candidate_from_finding(member_finding, spec)
        if candidate is None:
            return []
        candidates.append(
            candidate.model_copy(
                update={
                    "id": f"candidate.{finding.id}.member.{target_id}",
                    "finding_id": finding.id,
                    "acceptance_criteria": [
                        f"Move every member of {finding.id} by the same world displacement.",
                        "Preserve all pairwise relative offsets within the semantic group.",
                    ],
                }
            )
        )
    return candidates


def _candidates_from_finding(
    finding: QAFinding,
    spec: SceneSpec,
) -> list[RevisionCandidate]:
    """Convert either a conventional finding or one coherent group finding to candidates."""

    group_candidates = _group_candidates_from_finding(finding, spec)
    if group_candidates is not None:
        return group_candidates
    candidate = _candidate_from_finding(finding, spec)
    return [candidate] if candidate is not None else []


def build_revision_candidates(
    report: VisualQAReport,
    *,
    report_path: Path,
    scene_spec_path: Path,
) -> RevisionCandidates:
    """Build hash-bound revision candidates while locking every unrelated semantic ID."""

    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    if spec.job_id != report.job_id:
        raise ValueError("visual QA report job_id does not match SceneSpec")
    candidates = [
        candidate
        for finding in report.findings
        for candidate in _candidates_from_finding(finding, spec)
    ]
    targeted_ids = {
        candidate.target_id
        for candidate in candidates
        if candidate.target_id is not None
    }
    locked_ids = sorted(
        ({item.id for item in spec.objects} | {item.id for item in spec.materials}) - targeted_ids
    )
    return RevisionCandidates(
        job_id=spec.job_id,
        base_spec_sha256=sha256_file(scene_spec_path),
        camera_fingerprint=report.camera_fingerprint,
        source_report_sha256=sha256_file(report_path),
        candidates=candidates,
        locked_ids=locked_ids,
        locked_paths=[["camera"]],
    )
