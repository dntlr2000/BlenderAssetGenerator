"""Versioned additive schemas for exact bounded ModelingPlan revision evidence."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..analysis.models import ModelingPlan
from ..models import SceneSpec
from .models import JobId, JobRelativePath, Sha256, V08StrictModel, WorkflowId


class PairedFieldChange(V08StrictModel):
    """Record one exact normalized field diff without adding an operation executor."""

    path: str
    before: Any
    after: Any


class PairedModelingPlanBinding(V08StrictModel):
    """Bind immutable source identities, selected candidate bytes and preserved observations."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    base_modeling_plan_sha256: Sha256
    candidate_path: JobRelativePath
    candidate_sha256: Sha256
    base_modeling_plan: ModelingPlan
    candidate_modeling_plan: ModelingPlan
    base_scene_spec: SceneSpec
    changes: list[PairedFieldChange]
    preserved_sources: dict[JobRelativePath, Sha256]


class PairedTransactionIntent(V08StrictModel):
    """Consume one exact existing Standard approval for a fixed two-file transaction."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    job_id: JobId
    workflow_id: WorkflowId
    binding_sha256: Sha256
    before: dict[Literal["analysis/scene_spec.json", "analysis/modeling_plan.json"], Sha256] = (
        Field(min_length=2, max_length=2)
    )
    after: dict[Literal["analysis/scene_spec.json", "analysis/modeling_plan.json"], Sha256] = Field(
        min_length=2, max_length=2
    )
    evidence: dict[JobRelativePath, Sha256]
    report_before_sha256: Sha256 | None


class PairedCommitReceipt(V08StrictModel):
    """Certify the exact committed canonical pair without asserting visual acceptance."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    status: Literal["committed"] = "committed"
    intent_sha256: Sha256
    after: dict[Literal["analysis/scene_spec.json", "analysis/modeling_plan.json"], Sha256] = Field(
        min_length=2, max_length=2
    )


class PairedRollbackReceipt(V08StrictModel):
    """Certify exact source restoration after an interrupted, non-replayable transaction."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    status: Literal["rolled_back"] = "rolled_back"
    intent_sha256: Sha256
    before: dict[Literal["analysis/scene_spec.json", "analysis/modeling_plan.json"], Sha256] = (
        Field(min_length=2, max_length=2)
    )


TripleTarget = Literal["analysis/scene_spec.json", "analysis/modeling_plan.json", "job.json"]


class AttachmentTransactionIntentV02(PairedTransactionIntent):
    """Add only exact job metadata to the fixed paired transaction's canonical inventory."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    before: dict[TripleTarget, Sha256] = Field(min_length=3, max_length=3)
    after: dict[TripleTarget, Sha256] = Field(min_length=3, max_length=3)


class AttachmentCommitReceiptV02(PairedCommitReceipt):
    """Certify one opted-in three-file commit without changing legacy receipt bytes."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    after: dict[TripleTarget, Sha256] = Field(min_length=3, max_length=3)


class AttachmentRollbackReceiptV02(PairedRollbackReceipt):
    """Certify exact three-file restoration without making consumed authority replayable."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    before: dict[TripleTarget, Sha256] = Field(min_length=3, max_length=3)
