from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..revision import RevisionOperation, load_revision_plan
from ..workspace import sha256_file
from .models import (
    RevisionApproval,
    RevisionCandidate,
    RevisionCandidates,
    require_complete_group_candidate_selection,
)


def load_revision_approval(path: Path) -> RevisionApproval:
    """Load and strictly validate one revision approval record."""

    return RevisionApproval.model_validate_json(path.read_text(encoding="utf-8"))


def _candidate_operation_signature(candidate: RevisionCandidate) -> str:
    """Serialize one selected candidate operation for early plan equality checks."""

    return json.dumps(
        {
            "target_type": candidate.target_type,
            "target_id": candidate.target_id,
            "path": candidate.path,
            "op": candidate.op,
            "value": candidate.value,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _plan_operation_signature(operation: RevisionOperation) -> str:
    """Serialize one compiled plan operation for early candidate equality checks."""

    return json.dumps(
        {
            "target_type": operation.target_type,
            "target_id": operation.target_id,
            "path": operation.path,
            "op": operation.op,
            "value": operation.value,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def create_revision_approval(
    *,
    candidates_path: Path,
    plan_path: Path,
    approved_candidate_ids: list[str],
    output_path: Path,
) -> RevisionApproval:
    """Create an explicit single-use user approval bound to exact candidate and plan hashes."""

    candidates = RevisionCandidates.model_validate_json(
        candidates_path.read_text(encoding="utf-8")
    )
    available = {candidate.id: candidate for candidate in candidates.candidates}
    missing = sorted(set(approved_candidate_ids) - set(available))
    if missing:
        raise ValueError(f"approval references unknown candidates: {missing}")
    require_complete_group_candidate_selection(candidates, approved_candidate_ids)
    manual = sorted(
        candidate_id
        for candidate_id in approved_candidate_ids
        if available[candidate_id].applicability == "manual_required"
    )
    if manual:
        raise ValueError(
            "manual_required candidates cannot be approved for automatic apply: "
            f"{manual}"
        )
    plan = load_revision_plan(plan_path)
    if plan.job_id != candidates.job_id:
        raise ValueError("compiled RevisionPlan job_id does not match candidates")
    if plan.base_spec_sha256 != candidates.base_spec_sha256:
        raise ValueError("compiled RevisionPlan base hash does not match candidates")
    selected = [available[candidate_id] for candidate_id in approved_candidate_ids]
    expected = Counter(_candidate_operation_signature(candidate) for candidate in selected)
    actual = Counter(_plan_operation_signature(operation) for operation in plan.operations)
    if expected != actual:
        raise ValueError(
            "approved candidate operations do not exactly match the compiled RevisionPlan"
        )
    approval = RevisionApproval(
        approval_id=f"approval-{uuid4().hex}",
        job_id=candidates.job_id,
        candidates_sha256=sha256_file(candidates_path),
        plan_sha256=sha256_file(plan_path),
        base_spec_sha256=candidates.base_spec_sha256,
        approved_candidate_ids=approved_candidate_ids,
        approved_at=datetime.now(UTC).isoformat(),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(approval.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return approval


def consume_revision_approval(path: Path) -> RevisionApproval:
    """Mark an approval as consumed only after a guarded revision succeeds."""

    approval = load_revision_approval(path)
    if approval.used:
        raise ValueError(f"revision approval was already used: {approval.approval_id}")
    consumed = approval.model_copy(
        update={"used": True, "used_at": datetime.now(UTC).isoformat()}
    )
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(consumed.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)
    return consumed
