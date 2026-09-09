"""Strict additive contracts for evidence-aware repository storage retention."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from ..stabilization.models import PortableId, RelativePath, Sha256, V09StrictModel

SCHEMA_VERSION = "0.1.0"

StorageRoot = Literal[".b", ".t"]
GitCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
StorageEntryKind = Literal[
    "cache",
    "gate_run",
    "process_temp",
    "pytest_basetemp",
    "unknown",
]
StorageDisposition = Literal["eligible", "protected"]
InventoryStatus = Literal["complete", "partial"]
CleanupReceiptStatus = Literal["completed", "partial", "failed"]
GateRetentionRecoveryStatus = Literal["completed", "partial"]
GateOutcome = Literal["passed", "failed", "interrupted"]
RetentionPolicy = Literal["compact_success", "preserve"]
RetentionOutcome = Literal[
    "compacted",
    "preserved_by_policy",
    "preserved_failure",
    "preserved_retention_failure",
]


def _stable_digest(payload: dict[str, Any]) -> str:
    """Hash one JSON-compatible contract projection deterministically."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class StorageArtifact(V09StrictModel):
    """Bind one repository-relative storage-control artifact by exact bytes."""

    kind: Literal[
        "storage_inventory",
        "storage_cleanup_plan",
        "storage_cleanup_receipt",
        "gate_run_preflight",
        "gate_run_receipt",
        "gate_retention_recovery_receipt",
        "gate_retained_artifact",
    ]
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(ge=1)


class StorageTreeEntry(V09StrictModel):
    """Describe one exact immediate child of an allowed temporary root."""

    path: RelativePath
    root: StorageRoot
    kind: StorageEntryKind
    disposition: StorageDisposition
    reasons: list[str] = Field(min_length=1)
    file_count: int = Field(ge=0)
    directory_count: int = Field(ge=1)
    byte_size: int = Field(ge=0)
    tree_sha256: Sha256 | None = None
    newest_mtime_ns: int = Field(ge=0)
    matched_protected_hashes: list[Sha256] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tree_entry(self) -> StorageTreeEntry:
        """Require exact tree identity only for entries eligible for deletion."""

        if self.disposition == "eligible" and self.tree_sha256 is None:
            raise ValueError("eligible storage entries require tree_sha256")
        if self.matched_protected_hashes and self.disposition != "protected":
            raise ValueError("protected hash matches cannot remain deletion eligible")
        return self


class StorageInventoryV01(V09StrictModel):
    """Record a conservative inventory of repository-local temporary roots."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    inventory_id: PortableId
    repository_commit: GitCommit
    protection_source_sha256: Sha256
    roots: list[StorageRoot] = Field(min_length=1, max_length=2)
    minimum_age_hours: int = Field(ge=1, le=8760)
    status: InventoryStatus
    entries: list[StorageTreeEntry]
    inaccessible_paths: list[RelativePath] = Field(default_factory=list)
    total_byte_size: int = Field(ge=0)
    eligible_byte_size: int = Field(ge=0)
    protected_byte_size: int = Field(ge=0)
    generated_at: datetime
    input_sha256: Sha256

    @model_validator(mode="after")
    def validate_inventory(self) -> StorageInventoryV01:
        """Keep inventory ordering, totals, status, and digest internally consistent."""

        paths = [entry.path for entry in self.entries]
        if paths != sorted(paths, key=str.casefold) or len(paths) != len(set(paths)):
            raise ValueError("storage inventory entries must be unique and sorted")
        if self.roots != sorted(set(self.roots)):
            raise ValueError("storage inventory roots must be unique and sorted")
        eligible = sum(
            entry.byte_size for entry in self.entries if entry.disposition == "eligible"
        )
        protected = sum(
            entry.byte_size for entry in self.entries if entry.disposition == "protected"
        )
        if (
            self.eligible_byte_size != eligible
            or self.protected_byte_size != protected
            or self.total_byte_size != eligible + protected
        ):
            raise ValueError("storage inventory byte totals are inconsistent")
        if (self.status == "partial") != bool(self.inaccessible_paths):
            raise ValueError("partial inventory status must match inaccessible paths")
        expected = _stable_digest(
            self.model_dump(mode="json", exclude={"input_sha256"})
        )
        if self.input_sha256 != expected:
            raise ValueError("storage inventory input digest is inconsistent")
        return self


class StorageCleanupCandidate(V09StrictModel):
    """Bind one deletion candidate to its exact pre-cleanup tree identity."""

    path: RelativePath
    root: StorageRoot
    kind: StorageEntryKind
    tree_sha256: Sha256
    file_count: int = Field(ge=0)
    directory_count: int = Field(ge=1)
    byte_size: int = Field(ge=0)


class StorageCleanupPlanV01(V09StrictModel):
    """Freeze one exact, non-expanding set of repository-local deletion candidates."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    plan_id: PortableId
    inventory: StorageArtifact
    repository_commit: GitCommit
    protection_source_sha256: Sha256
    candidates: list[StorageCleanupCandidate]
    expected_reclaimable_bytes: int = Field(ge=0)
    excluded_entry_count: int = Field(ge=0)
    created_at: datetime
    input_sha256: Sha256

    @model_validator(mode="after")
    def validate_cleanup_plan(self) -> StorageCleanupPlanV01:
        """Require sorted unique candidates, exact totals, and a deterministic digest."""

        paths = [candidate.path for candidate in self.candidates]
        if paths != sorted(paths, key=str.casefold) or len(paths) != len(set(paths)):
            raise ValueError("cleanup plan candidates must be unique and sorted")
        if self.inventory.kind != "storage_inventory":
            raise ValueError("cleanup plan must reference a storage inventory")
        if self.expected_reclaimable_bytes != sum(
            candidate.byte_size for candidate in self.candidates
        ):
            raise ValueError("cleanup plan byte total is inconsistent")
        expected = _stable_digest(
            self.model_dump(mode="json", exclude={"input_sha256"})
        )
        if self.input_sha256 != expected:
            raise ValueError("storage cleanup plan input digest is inconsistent")
        return self


class StorageCleanupResult(V09StrictModel):
    """Record the result for one exact candidate without claiming recoverability."""

    path: RelativePath
    tree_sha256: Sha256
    byte_size: int = Field(ge=0)
    status: Literal["removed", "remaining"]
    message: str = Field(min_length=1, max_length=2000)


class StorageCleanupReceiptV01(V09StrictModel):
    """Prove the bounded outcome of one exact cleanup plan execution."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    receipt_id: PortableId
    plan: StorageArtifact
    status: CleanupReceiptStatus
    results: list[StorageCleanupResult]
    reclaimed_byte_size: int = Field(ge=0)
    completed_at: datetime
    input_sha256: Sha256

    @model_validator(mode="after")
    def validate_cleanup_receipt(self) -> StorageCleanupReceiptV01:
        """Keep result ordering, status, reclaimed bytes, and digest consistent."""

        paths = [result.path for result in self.results]
        if paths != sorted(paths, key=str.casefold) or len(paths) != len(set(paths)):
            raise ValueError("cleanup receipt results must be unique and sorted")
        removed = sum(
            result.byte_size for result in self.results if result.status == "removed"
        )
        if self.reclaimed_byte_size != removed:
            raise ValueError("cleanup receipt reclaimed byte total is inconsistent")
        if self.status == "completed" and any(
            result.status != "removed" for result in self.results
        ):
            raise ValueError("completed cleanup receipt cannot contain remaining entries")
        if self.plan.kind != "storage_cleanup_plan":
            raise ValueError("cleanup receipt must reference a cleanup plan")
        expected = _stable_digest(
            self.model_dump(mode="json", exclude={"input_sha256"})
        )
        if self.input_sha256 != expected:
            raise ValueError("storage cleanup receipt input digest is inconsistent")
        return self


class GateRunReceiptV01(V09StrictModel):
    """Separate one gate result from the retention outcome of its run-owned scratch tree."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    run_id: PortableId
    gate_id: PortableId
    repository_commit: GitCommit
    run_root: RelativePath
    process_temp_root: RelativePath | None = None
    gate_outcome: GateOutcome
    retention_policy: RetentionPolicy
    retention_outcome: RetentionOutcome
    source_tree_sha256: Sha256 | None = None
    source_file_count: int = Field(ge=0)
    source_directory_count: int = Field(ge=0)
    source_byte_size: int = Field(ge=0)
    retained_artifacts: list[StorageArtifact] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime
    message: str = Field(min_length=1, max_length=2000)
    input_sha256: Sha256

    @model_validator(mode="after")
    def validate_gate_run_receipt(self) -> GateRunReceiptV01:
        """Prevent a failed gate or failed retention pass from claiming compaction."""

        if self.retention_outcome == "compacted":
            if self.gate_outcome != "passed" or self.retention_policy != "compact_success":
                raise ValueError("only successful compact_success gates can be compacted")
            if self.source_tree_sha256 is None:
                raise ValueError("compacted gate runs require the original tree digest")
        if self.gate_outcome != "passed" and self.retention_outcome != "preserved_failure":
            raise ValueError("failed or interrupted gates must preserve their run tree")
        if self.retention_policy == "preserve" and self.retention_outcome not in {
            "preserved_by_policy",
            "preserved_failure",
        }:
            raise ValueError("preserve policy cannot claim automatic compaction")
        if not any(item.kind == "gate_run_preflight" for item in self.retained_artifacts):
            raise ValueError("gate run receipt requires its immutable preflight artifact")
        expected = _stable_digest(
            self.model_dump(mode="json", exclude={"input_sha256"})
        )
        if self.input_sha256 != expected:
            raise ValueError("gate run receipt input digest is inconsistent")
        return self


class GateRetentionRecoveryReceiptV01(V09StrictModel):
    """Record append-only recovery of scratch quarantined by a passed gate."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    recovery_id: PortableId
    run_id: PortableId
    gate_receipt: StorageArtifact
    status: GateRetentionRecoveryStatus
    expected_roots: list[RelativePath] = Field(min_length=1, max_length=2)
    removed_roots: list[RelativePath]
    remaining_roots: list[RelativePath]
    source_tree_sha256: Sha256
    source_byte_size: int = Field(ge=0)
    reclaimed_byte_size: int = Field(ge=0)
    completed_at: datetime
    message: str = Field(min_length=1, max_length=2000)
    input_sha256: Sha256

    @model_validator(mode="after")
    def validate_gate_retention_recovery(self) -> GateRetentionRecoveryReceiptV01:
        """Require an exact root partition and conservative reclaimed-byte claim."""

        expected = sorted(set(self.expected_roots), key=str.casefold)
        removed = sorted(set(self.removed_roots), key=str.casefold)
        remaining = sorted(set(self.remaining_roots), key=str.casefold)
        if self.expected_roots != expected:
            raise ValueError("gate recovery expected roots must be unique and sorted")
        if self.removed_roots != removed or self.remaining_roots != remaining:
            raise ValueError("gate recovery result roots must be unique and sorted")
        if set(removed) & set(remaining) or set(removed) | set(remaining) != set(expected):
            raise ValueError("gate recovery results must partition the expected roots")
        if self.gate_receipt.kind != "gate_run_receipt":
            raise ValueError("gate recovery must reference its exact gate receipt")
        if (self.status == "completed") != (not remaining):
            raise ValueError("gate recovery status must match its remaining roots")
        expected_reclaimed = self.source_byte_size if self.status == "completed" else 0
        if self.reclaimed_byte_size != expected_reclaimed:
            raise ValueError("gate recovery reclaimed bytes must remain conservative")
        expected_digest = _stable_digest(
            self.model_dump(mode="json", exclude={"input_sha256"})
        )
        if self.input_sha256 != expected_digest:
            raise ValueError("gate recovery input digest is inconsistent")
        return self


def storage_input_sha256(payload: dict[str, Any]) -> str:
    """Return the deterministic digest shared by storage-retention constructors."""

    return _stable_digest(payload)
