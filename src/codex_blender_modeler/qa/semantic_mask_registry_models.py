"""Strict contracts for publishing explicit semantic reference-mask evidence."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .diagnostic_models import JobRelativePath, SemanticId, Sha256


class SemanticMaskRegistryStrictModel(BaseModel):
    """Reject undeclared fields in semantic-mask registration evidence."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RegisteredSemanticMaskArtifact(SemanticMaskRegistryStrictModel):
    """Bind one registered semantic mask to its exact immutable file bytes."""

    semantic_id: SemanticId
    source_id: str = Field(min_length=1, max_length=192)
    path: JobRelativePath
    sha256: Sha256


class SemanticReferenceMaskPromotionReceipt(SemanticMaskRegistryStrictModel):
    """Journal one exact candidate manifest promoted as current QA evidence."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    registration_version: Literal["semantic_reference_mask_registration_v1"] = (
        "semantic_reference_mask_registration_v1"
    )
    status: Literal["promoted"] = "promoted"
    ok: Literal[True] = True
    job_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    registration_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,95}$")
    candidate_manifest_path: JobRelativePath
    candidate_manifest_sha256: Sha256
    canonical_manifest_path: Literal["analysis/masks/semantic_manifest.json"] = (
        "analysis/masks/semantic_manifest.json"
    )
    canonical_manifest_sha256: Sha256
    previous_canonical_sha256: Sha256 | None = None
    history_path: JobRelativePath | None = None
    scene_spec_path: Literal["analysis/scene_spec.json"] = "analysis/scene_spec.json"
    scene_spec_sha256: Sha256
    reference_path: JobRelativePath
    reference_sha256: Sha256
    masks: list[RegisteredSemanticMaskArtifact] = Field(min_length=1)
    promoted_at: datetime

    @model_validator(mode="after")
    def validate_registration_ownership(self) -> SemanticReferenceMaskPromotionReceipt:
        """Require exact registration-owned paths and a complete prior-history pair."""

        registration_root = PurePosixPath(
            f"analysis/masks/registrations/{self.registration_id}"
        )
        expected_manifest = registration_root / "manifest.json"
        if PurePosixPath(self.candidate_manifest_path) != expected_manifest:
            raise ValueError(
                "candidate manifest must use the exact registration-owned path"
            )
        mask_root = registration_root / "masks"
        for artifact in self.masks:
            path = PurePosixPath(artifact.path)
            if path.parts[: len(mask_root.parts)] != mask_root.parts:
                raise ValueError("registered masks must stay inside the registration")
        identifiers = [item.semantic_id for item in self.masks]
        paths = [item.path for item in self.masks]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("registered semantic mask IDs must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("registered semantic mask paths must be unique")
        if self.candidate_manifest_sha256 != self.canonical_manifest_sha256:
            raise ValueError("canonical manifest must preserve the exact candidate bytes")
        if (self.previous_canonical_sha256 is None) != (self.history_path is None):
            raise ValueError("previous canonical hash and history path must be paired")
        if self.history_path is not None and not self.history_path.startswith(
            "history/qa_semantic_masks/"
        ):
            raise ValueError("semantic mask history must stay in its dedicated directory")
        return self


class SemanticReferenceMaskRegistryStatus(SemanticMaskRegistryStrictModel):
    """Report current semantic-mask evidence without repairing or rewriting it."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    status: Literal["absent", "current", "legacy_current", "stale", "invalid"]
    ok: bool
    registration_id: str | None = None
    canonical_manifest_path: JobRelativePath | None = None
    canonical_manifest_sha256: Sha256 | None = None
    promotion_receipt_path: JobRelativePath | None = None
    promotion_receipt_sha256: Sha256 | None = None
    mask_count: int = Field(default=0, ge=0)
    issues: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status_payload(self) -> SemanticReferenceMaskRegistryStatus:
        """Keep success flags and optional registration evidence internally consistent."""

        if self.ok != (self.status in {"current", "legacy_current"}):
            raise ValueError("registry status ok flag does not match the status")
        canonical_values = (
            self.canonical_manifest_path,
            self.canonical_manifest_sha256,
        )
        if any(value is None for value in canonical_values) != all(
            value is None for value in canonical_values
        ):
            raise ValueError("canonical manifest path and hash must be paired")
        receipt_values = (
            self.registration_id,
            self.promotion_receipt_path,
            self.promotion_receipt_sha256,
        )
        if any(value is None for value in receipt_values) != all(
            value is None for value in receipt_values
        ):
            raise ValueError("registration ID and receipt path/hash must be supplied together")
        if self.status == "absent" and self.canonical_manifest_path is not None:
            raise ValueError("absent status cannot bind a canonical manifest")
        if self.status in {"stale", "invalid"} and not self.issues:
            raise ValueError("non-current semantic mask evidence requires issues")
        return self
