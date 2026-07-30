"""Deterministic candidate-envelope checks for bounded V0.6 convergence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, model_validator

from ..models import StrictModel
from .convergence_session_models import (
    SHA256_PATTERN,
    ConvergencePathFamily,
    ConvergencePathLimit,
    VisualConvergenceApproval,
    VisualConvergenceIteration,
    VisualConvergencePlan,
)
from .models import RevisionCandidate, RevisionCandidates

PathPart = str | int
RejectionCode = Literal[
    "manual_required",
    "generated_target_only",
    "missing_direct_reference",
    "target_type_not_allowed",
    "material_edits_disabled",
    "target_not_allowed",
    "target_locked",
    "custom_mesh_geometry",
    "path_not_allowed",
    "operation_not_allowed",
    "missing_baseline_value",
    "invalid_numeric_delta",
    "absolute_delta_exceeded",
    "relative_delta_exceeded",
    "confidence_below_threshold",
    "partial_group_selection",
    "candidate_conflict",
    "iteration_group_budget",
    "iteration_candidate_budget",
    "iteration_target_budget",
]

_GROUP_FINDING_PREFIX = "direct.group_position."
_PATH_FAMILY_PREFIXES: dict[ConvergencePathFamily, tuple[PathPart, ...]] = {
    "transform.location": ("transform", "location"),
    "transform.rotation_deg": ("transform", "rotation_deg"),
    "transform.scale": ("transform", "scale"),
    "geometry.dimensions": ("geometry", "dimensions"),
    "geometry.depth": ("geometry", "depth"),
    "geometry.size": ("geometry", "size"),
    "geometry.bevel_depth": ("geometry", "bevel_depth"),
    "geometry.skirt_depth": ("geometry", "skirt_depth"),
    "material.base_color": ("base_color",),
    "material.roughness": ("roughness",),
    "material.metallic": ("metallic",),
    "material.emission_strength": ("emission_strength",),
}
_INDEXED_FAMILIES: dict[ConvergencePathFamily, int] = {
    "transform.location": 3,
    "transform.rotation_deg": 3,
    "transform.scale": 3,
    "geometry.dimensions": 3,
    "material.base_color": 4,
}


class ConvergenceCandidateRejection(StrictModel):
    """Explain why one candidate could not use the bounded session authority."""

    candidate_id: str
    code: RejectionCode
    message: str


class ConvergenceCandidateSelection(StrictModel):
    """Record deterministic selected IDs and fail-closed candidate decisions."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    session_id: str
    job_id: str
    candidates_sha256: str = Field(pattern=SHA256_PATTERN)
    base_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    source_qa_report_sha256: str = Field(pattern=SHA256_PATTERN)
    selected_candidate_ids: list[str] = Field(default_factory=list)
    rejected: list[ConvergenceCandidateRejection] = Field(default_factory=list)
    selection_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_decisions(self) -> ConvergenceCandidateSelection:
        """Require unique and disjoint selected and rejected candidate identities."""

        if len(self.selected_candidate_ids) != len(set(self.selected_candidate_ids)):
            raise ValueError("selected convergence candidate IDs must be unique")
        rejected_ids = [item.candidate_id for item in self.rejected]
        if len(rejected_ids) != len(set(rejected_ids)):
            raise ValueError("rejected convergence candidate IDs must be unique")
        collisions = sorted(set(self.selected_candidate_ids).intersection(rejected_ids))
        if collisions:
            raise ValueError(f"candidate decisions overlap: {collisions}")
        return self


def _canonical_sha256(value: Any) -> str:
    """Hash one JSON-compatible value with deterministic canonical serialization."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_convergence_activation(
    plan: VisualConvergencePlan,
    approval: VisualConvergenceApproval,
    *,
    plan_sha256: str,
) -> None:
    """Verify one active approval against the exact plan and immutable baseline."""

    if approval.status != "active":
        raise ValueError("visual convergence approval is not active")
    checks = {
        "session_id": (approval.session_id, plan.session_id),
        "job_id": (approval.job_id, plan.job_id),
        "plan_sha256": (approval.plan_sha256, plan_sha256),
        "input_fingerprint": (approval.input_fingerprint, plan.input_fingerprint),
        "initial_scene_spec_sha256": (
            approval.initial_scene_spec_sha256,
            plan.initial_scene_spec_sha256,
        ),
        "initial_qa_report_sha256": (
            approval.initial_qa_report_sha256,
            plan.initial_qa_report_sha256,
        ),
        "initial_candidates_sha256": (
            approval.initial_candidates_sha256,
            plan.initial_candidates_sha256,
        ),
        "initial_build_fingerprint": (
            approval.initial_build_fingerprint,
            plan.initial_build_fingerprint,
        ),
        "initial_build_provenance_sha256": (
            approval.initial_build_provenance_sha256,
            plan.initial_build_provenance_sha256,
        ),
        "host_safety_envelope_sha256": (
            approval.host_safety_envelope_sha256,
            plan.host_safety_envelope_sha256,
        ),
        "initial_constraints_present": (
            approval.initial_constraints_present,
            plan.initial_constraints_present,
        ),
        "initial_constraints_sha256": (
            approval.initial_constraints_sha256,
            plan.initial_constraints_sha256,
        ),
        "camera_fingerprint": (
            approval.camera_fingerprint,
            plan.camera_fingerprint,
        ),
    }
    mismatches = sorted(label for label, values in checks.items() if values[0] != values[1])
    if mismatches:
        raise ValueError(f"visual convergence approval binding mismatch: {mismatches}")


def _path_family(
    candidate: RevisionCandidate,
    path_limits: Mapping[ConvergencePathFamily, ConvergencePathLimit],
) -> ConvergencePathFamily | None:
    """Resolve one candidate path only when its complete structure is allow-listed."""

    for family in sorted(path_limits):
        if candidate.target_type == "material" and not family.startswith("material."):
            continue
        if candidate.target_type == "object" and family.startswith("material."):
            continue
        prefix = _PATH_FAMILY_PREFIXES[family]
        if tuple(candidate.path[: len(prefix)]) != prefix:
            continue
        remainder = candidate.path[len(prefix) :]
        if not remainder:
            return family
        component_count = _INDEXED_FAMILIES.get(family)
        if (
            component_count is not None
            and len(remainder) == 1
            and isinstance(remainder[0], int)
            and not isinstance(remainder[0], bool)
            and 0 <= remainder[0] < component_count
        ):
            return family
    return None


def _numeric_sequence(value: Any) -> list[float] | None:
    """Normalize one finite scalar or flat numeric sequence for delta checks."""

    values = value if isinstance(value, (list, tuple)) else [value]
    normalized: list[float] = []
    for item in values:
        if (
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
        ):
            return None
        normalized.append(float(item))
    return normalized


def _after_values(
    *,
    operation: str,
    before: list[float],
    operand: list[float],
) -> list[float] | None:
    """Evaluate one bounded numeric operation without mutating canonical data."""

    if operation == "set":
        return operand if len(operand) == len(before) else None
    if len(operand) == 1 and len(before) > 1:
        operand = operand * len(before)
    if len(operand) != len(before):
        return None
    if operation == "add":
        return [left + right for left, right in zip(before, operand, strict=True)]
    if operation == "multiply":
        return [left * right for left, right in zip(before, operand, strict=True)]
    return None


def _delta_rejection(
    candidate: RevisionCandidate,
    limit: ConvergencePathLimit,
    baseline_value: Any,
) -> tuple[RejectionCode, str] | None:
    """Return the first deterministic numeric-envelope violation for a candidate."""

    before = _numeric_sequence(baseline_value)
    operand = _numeric_sequence(candidate.value)
    if before is None or operand is None:
        return "invalid_numeric_delta", "candidate and baseline values must be finite numeric data"
    after = _after_values(operation=candidate.op, before=before, operand=operand)
    if after is None or any(not math.isfinite(item) for item in after):
        return "invalid_numeric_delta", "candidate operation has incompatible numeric dimensions"
    absolute_delta = max(abs(right - left) for left, right in zip(before, after, strict=True))
    relative_deltas = [
        0.0
        if right == left
        else abs(right - left) / max(abs(left), 1e-12)
        for left, right in zip(before, after, strict=True)
    ]
    relative_delta = max(relative_deltas)
    if (
        limit.max_absolute_delta is not None
        and absolute_delta > limit.max_absolute_delta + 1e-12
    ):
        return (
            "absolute_delta_exceeded",
            f"absolute delta {absolute_delta:.12g} exceeds {limit.max_absolute_delta:.12g}",
        )
    if (
        limit.max_relative_delta is not None
        and relative_delta > limit.max_relative_delta + 1e-12
    ):
        return (
            "relative_delta_exceeded",
            f"relative delta {relative_delta:.12g} exceeds {limit.max_relative_delta:.12g}",
        )
    return None


def _candidate_rejection(
    plan: VisualConvergencePlan,
    candidate: RevisionCandidate,
    *,
    baseline_values: Mapping[str, Any],
    path_limits: Mapping[ConvergencePathFamily, ConvergencePathLimit],
) -> tuple[RejectionCode, str] | None:
    """Apply the complete fail-closed envelope to one QA candidate."""

    if set(candidate.evidence_sources) == {"generated_target"}:
        return "generated_target_only", "generated-target-only evidence is advisory"
    if candidate.applicability == "manual_required":
        return "manual_required", "manual_required candidates cannot use session authority"
    if "direct_reference" not in candidate.evidence_sources:
        return (
            "missing_direct_reference",
            "automatic convergence requires direct reference evidence",
        )
    if candidate.target_type not in {"object", "material"}:
        return "target_type_not_allowed", "camera and scene candidates remain manual"
    if candidate.target_type == "material" and not plan.allow_material_edits:
        return "material_edits_disabled", "material edits are locked by this geometry session"
    target_id = candidate.target_id
    if target_id in plan.locked_target_ids:
        return "target_locked", "candidate target is explicitly locked"
    if target_id is None or target_id not in plan.allowed_target_ids:
        return "target_not_allowed", "candidate target is outside the approved semantic envelope"
    if (
        target_id in plan.custom_mesh_target_ids
        and candidate.path
        and candidate.path[0] == "geometry"
    ):
        return "custom_mesh_geometry", "custom-mesh geometry edits remain manual"
    family = _path_family(candidate, path_limits)
    if family is None:
        return "path_not_allowed", "candidate path is outside approved path families"
    limit = path_limits[family]
    if candidate.op not in limit.allowed_operations:
        return "operation_not_allowed", "candidate operation is outside the path rule"
    if candidate.confidence < plan.minimum_candidate_confidence:
        return "confidence_below_threshold", "candidate confidence is below the session minimum"
    if candidate.id not in baseline_values:
        return "missing_baseline_value", "candidate requires its exact current numeric value"
    return _delta_rejection(candidate, limit, baseline_values[candidate.id])


def _paths_conflict(left: RevisionCandidate, right: RevisionCandidate) -> bool:
    """Detect competing operations on the same target and overlapping SceneSpec paths."""

    if left.target_type != right.target_type or left.target_id != right.target_id:
        return False
    shortest = min(len(left.path), len(right.path))
    return left.path[:shortest] == right.path[:shortest]


def _group_key(candidate: RevisionCandidate) -> str:
    """Keep coherent direct group-position edits atomic during selection."""

    if candidate.finding_id.startswith(_GROUP_FINDING_PREFIX):
        return f"group:{candidate.finding_id}"
    return f"candidate:{candidate.id}"


def _selection_hash_payload(
    *,
    plan: VisualConvergencePlan,
    candidates_sha256: str,
    selected: list[str],
    rejected: list[ConvergenceCandidateRejection],
) -> dict[str, Any]:
    """Build canonical selection evidence independent of candidate input ordering."""

    return {
        "schema_version": "0.6.0",
        "session_id": plan.session_id,
        "job_id": plan.job_id,
        "candidates_sha256": candidates_sha256,
        "selected_candidate_ids": selected,
        "rejected": [
            item.model_dump(mode="json")
            for item in sorted(rejected, key=lambda record: record.candidate_id)
        ],
    }


def select_convergence_candidates(
    plan: VisualConvergencePlan,
    candidates: RevisionCandidates,
    *,
    candidates_sha256: str,
    expected_base_scene_spec_sha256: str,
    expected_source_qa_report_sha256: str,
    baseline_values: Mapping[str, Any],
) -> ConvergenceCandidateSelection:
    """Select nonconflicting direct-reference candidates within the exact envelope."""

    if candidates.job_id != plan.job_id:
        raise ValueError("convergence candidates job_id does not match the session")
    if candidates.camera_fingerprint != plan.camera_fingerprint:
        raise ValueError("convergence candidates changed the approved comparison camera")
    if candidates.base_spec_sha256 != expected_base_scene_spec_sha256:
        raise ValueError("convergence candidates are stale for the current SceneSpec")
    if candidates.source_report_sha256 != expected_source_qa_report_sha256:
        raise ValueError("convergence candidates are stale for the current QA report")
    path_limits = {item.path_family: item for item in plan.path_limits}
    grouped: dict[str, list[RevisionCandidate]] = {}
    for candidate in candidates.candidates:
        grouped.setdefault(_group_key(candidate), []).append(candidate)
    ordered_groups = sorted(
        grouped.values(),
        key=lambda group: (
            -min(item.confidence for item in group),
            min(item.id for item in group),
        ),
    )
    selected_candidates: list[RevisionCandidate] = []
    selected_groups = 0
    selected_ids: set[str] = set()
    rejected_by_id: dict[str, ConvergenceCandidateRejection] = {}

    def reject_group(
        group: Sequence[RevisionCandidate],
        code: RejectionCode,
        message: str,
    ) -> None:
        """Record one deterministic reason for every member of an atomic group."""

        for item in sorted(group, key=lambda candidate: candidate.id):
            rejected_by_id[item.id] = ConvergenceCandidateRejection(
                candidate_id=item.id,
                code=code,
                message=message,
            )

    for group in ordered_groups:
        group = sorted(group, key=lambda item: item.id)
        violations = [
            (item, _candidate_rejection(
                plan,
                item,
                baseline_values=baseline_values,
                path_limits=path_limits,
            ))
            for item in group
        ]
        violations = [(item, violation) for item, violation in violations if violation is not None]
        if violations:
            code, message = violations[0][1]
            if len(group) > 1:
                code = "partial_group_selection"
                message = (
                    "coherent group candidate rejected because at least one member "
                    f"failed the envelope: {violations[0][0].id}: {message}"
                )
            reject_group(group, code, message)
            continue
        if any(
            _paths_conflict(left, right)
            for index, left in enumerate(group)
            for right in group[index + 1 :]
        ):
            reject_group(
                group,
                "candidate_conflict",
                "coherent group contains overlapping edits for the same target path",
            )
            continue
        if selected_groups >= plan.max_candidate_groups_per_iteration:
            reject_group(group, "iteration_group_budget", "candidate-group budget exhausted")
            continue
        if len(selected_candidates) + len(group) > plan.max_candidates_per_iteration:
            reject_group(group, "iteration_candidate_budget", "candidate budget exhausted")
            continue
        group_targets = {
            item.target_id for item in group if item.target_id is not None
        }
        existing_targets = {
            item.target_id for item in selected_candidates if item.target_id is not None
        }
        if len(existing_targets | group_targets) > plan.max_changed_ids_per_iteration:
            reject_group(group, "iteration_target_budget", "changed semantic-ID budget exhausted")
            continue
        if any(
            _paths_conflict(item, existing)
            for item in group
            for existing in selected_candidates
        ):
            reject_group(group, "candidate_conflict", "candidate overlaps a higher-priority edit")
            continue
        selected_candidates.extend(group)
        selected_groups += 1
        selected_ids.update(item.id for item in group)

    selected = sorted(selected_ids)
    rejected = sorted(rejected_by_id.values(), key=lambda item: item.candidate_id)
    payload = _selection_hash_payload(
        plan=plan,
        candidates_sha256=candidates_sha256,
        selected=selected,
        rejected=rejected,
    )
    return ConvergenceCandidateSelection(
        session_id=plan.session_id,
        job_id=plan.job_id,
        candidates_sha256=candidates_sha256,
        base_scene_spec_sha256=candidates.base_spec_sha256,
        source_qa_report_sha256=candidates.source_report_sha256,
        selected_candidate_ids=selected,
        rejected=rejected,
        selection_sha256=_canonical_sha256(payload),
    )


def validate_iteration_receipt_chain(
    plan: VisualConvergencePlan,
    approval: VisualConvergenceApproval,
    *,
    plan_sha256: str,
    approval_sha256: str,
    receipts: Sequence[tuple[VisualConvergenceIteration, str]],
) -> None:
    """Verify ordered iteration indices, exact activation hashes, and predecessor links."""

    validate_convergence_activation(plan, approval, plan_sha256=plan_sha256)
    if len(receipts) > plan.max_iterations:
        raise ValueError("visual convergence receipt chain exceeds max_iterations")
    previous_hash: str | None = None
    previous_canonical = plan.initial_scene_spec_sha256
    expected_source_run = plan.initial_qa_run_id
    expected_source_report = plan.initial_qa_report_sha256
    expected_source_candidates = plan.initial_candidates_sha256
    expected_source_build = plan.initial_build_fingerprint
    for expected_index, (receipt, receipt_sha256) in enumerate(receipts, start=1):
        if expected_index > 1 and receipts[expected_index - 2][0].status != "accepted":
            raise ValueError(
                "a non-accepted convergence receipt must terminate the receipt chain"
            )
        if receipt.iteration_index != expected_index:
            raise ValueError("visual convergence receipt indices must be contiguous")
        if receipt.session_id != plan.session_id or receipt.job_id != plan.job_id:
            raise ValueError("visual convergence receipt identity mismatch")
        if receipt.plan_sha256 != plan_sha256:
            raise ValueError("visual convergence receipt plan hash mismatch")
        if receipt.approval_sha256 != approval_sha256:
            raise ValueError("visual convergence receipt approval hash mismatch")
        if receipt.input_fingerprint != plan.input_fingerprint:
            raise ValueError("visual convergence receipt input fingerprint mismatch")
        if receipt.previous_iteration_receipt_sha256 != previous_hash:
            raise ValueError("visual convergence receipt predecessor hash mismatch")
        if receipt.base_scene_spec_sha256 != previous_canonical:
            raise ValueError("visual convergence receipt canonical base hash mismatch")
        if (
            receipt.source_qa_run_id != expected_source_run
            or receipt.source_qa_report_sha256 != expected_source_report
        ):
            raise ValueError("visual convergence receipt source QA chain mismatch")
        if (
            expected_source_candidates is not None
            and receipt.candidates_sha256 != expected_source_candidates
        ):
            raise ValueError("visual convergence receipt source candidates chain mismatch")
        if (
            expected_source_build is not None
            and receipt.source_build_fingerprint != expected_source_build
        ):
            raise ValueError("visual convergence receipt source build chain mismatch")
        previous_hash = receipt_sha256
        previous_canonical = receipt.canonical_scene_spec_sha256
        if receipt.status == "accepted":
            if (
                receipt.result_qa_run_id is None
                or receipt.result_qa_report_sha256 is None
                or receipt.result_candidates_sha256 is None
            ):
                raise ValueError("accepted convergence receipt lacks result QA chain data")
            expected_source_run = receipt.result_qa_run_id
            expected_source_report = receipt.result_qa_report_sha256
            expected_source_candidates = receipt.result_candidates_sha256
            expected_source_build = (
                receipt.result_build_fingerprint
                if receipt.result_build_fingerprint is not None
                else expected_source_build
            )
