"""Strict V0.9 contracts for reversible workspace relocation evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .models import (
    JobId,
    PortableId,
    RelativePath,
    Sha256,
    V09StrictModel,
    WorkflowId,
)

SCHEMA_VERSION = "0.9.0"

WorkspaceRelocationAction = Literal["archive", "restore"]
WorkspaceTerminalClassification = Literal["completed", "cancelled", "failed"]


def _json_default(value: Any) -> Any:
    """Project nested strict models into the same JSON representation validators use."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"Unsupported relocation digest value: {type(value).__name__}")


def _stable_digest(payload: dict[str, Any]) -> str:
    """Hash one JSON-compatible relocation payload deterministically."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class WorkspaceArchiveArtifact(V09StrictModel):
    """Bind one archive-control artifact by archive-root-relative path and bytes."""

    kind: Literal["workspace_relocation_plan", "workspace_relocation_receipt"]
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(ge=1)


class WorkspaceRelocationPlan(V09StrictModel):
    """Authorize one exact same-volume archive or restore operation."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    plan_id: PortableId
    action: WorkspaceRelocationAction
    job_id: JobId
    classification: WorkspaceTerminalClassification
    workflow_id: WorkflowId
    workflow_state_sha256: Sha256
    job_metadata_sha256: Sha256
    archive_entry_path: RelativePath
    source_tree_sha256: Sha256
    source_file_count: int = Field(ge=1)
    source_directory_count: int = Field(ge=1)
    source_byte_size: int = Field(ge=1)
    allow_failed: bool = False
    prior_archive_receipt: WorkspaceArchiveArtifact | None = None
    created_at: datetime
    input_sha256: Sha256

    @model_validator(mode="after")
    def validate_relocation_plan(self) -> WorkspaceRelocationPlan:
        """Require action-specific evidence and an exact deterministic input digest."""

        if self.classification == "failed" and not self.allow_failed:
            raise ValueError("failed workspace relocation requires allow_failed=true")
        if self.classification != "failed" and self.allow_failed:
            raise ValueError("allow_failed is valid only for failed workspaces")
        if self.action == "archive" and self.prior_archive_receipt is not None:
            raise ValueError("archive plan cannot reference a prior archive receipt")
        if self.action == "restore" and self.prior_archive_receipt is None:
            raise ValueError("restore plan requires the exact prior archive receipt")
        expected = _stable_digest(
            self.model_dump(mode="json", exclude={"input_sha256"})
        )
        if self.input_sha256 != expected:
            raise ValueError("workspace relocation plan input digest is inconsistent")
        return self


class WorkspaceRelocationReceipt(V09StrictModel):
    """Prove one exact workspace relocation or crash-adopted move."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    receipt_id: PortableId
    plan: WorkspaceArchiveArtifact
    action: WorkspaceRelocationAction
    job_id: JobId
    classification: WorkspaceTerminalClassification
    workflow_id: WorkflowId
    workflow_state_sha256: Sha256
    job_metadata_sha256: Sha256
    archive_entry_path: RelativePath
    tree_sha256: Sha256
    file_count: int = Field(ge=1)
    directory_count: int = Field(ge=1)
    byte_size: int = Field(ge=1)
    source_location: Literal["workspace", "archive"]
    destination_location: Literal["workspace", "archive"]
    adopted_interrupted_move: bool = False
    completed_at: datetime
    input_sha256: Sha256

    @model_validator(mode="after")
    def validate_relocation_receipt(self) -> WorkspaceRelocationReceipt:
        """Keep direction fields and the receipt input digest internally consistent."""

        expected_locations = (
            ("workspace", "archive")
            if self.action == "archive"
            else ("archive", "workspace")
        )
        if (self.source_location, self.destination_location) != expected_locations:
            raise ValueError("workspace relocation receipt direction is inconsistent")
        expected = _stable_digest(
            self.model_dump(mode="json", exclude={"input_sha256"})
        )
        if self.input_sha256 != expected:
            raise ValueError("workspace relocation receipt input digest is inconsistent")
        return self


def relocation_input_sha256(payload: dict[str, Any]) -> str:
    """Return the public deterministic digest used by relocation constructors."""

    return _stable_digest(payload)
