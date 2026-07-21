from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..models import StrictModel

InteriorPolicy = Literal["disabled", "visible_only", "proxy", "measured", "authored"]
FurnishingPolicy = Literal["none", "proxy", "detailed"]
InteriorEvidence = Literal["not_applicable", "observed", "inferred", "measured", "authored"]
_SEMANTIC_TOKEN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*(?:\.[a-zA-Z0-9][a-zA-Z0-9_-]*)*$")


class InteriorScope(StrictModel):
    """Declare the exact optional interior-authoring boundary for one job."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    job_id: str
    policy: InteriorPolicy = "disabled"
    request: str = ""
    allowed_semantic_prefixes: list[str] = Field(default_factory=list)
    excluded_semantic_prefixes: list[str] = Field(default_factory=list)
    levels: list[str] = Field(default_factory=list)
    spaces: list[str] = Field(default_factory=list)
    furnishing: FurnishingPolicy = "none"
    evidence_status: InteriorEvidence = "not_applicable"
    assumptions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: str

    @field_validator(
        "allowed_semantic_prefixes",
        "excluded_semantic_prefixes",
        "levels",
        "spaces",
    )
    @classmethod
    def validate_stable_tokens(cls, values: list[str]) -> list[str]:
        """Require non-empty unique scope tokens without path-like components."""

        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Interior scope tokens must not be empty")
        if any(not _SEMANTIC_TOKEN_RE.fullmatch(value) for value in normalized):
            raise ValueError("Interior scope tokens must be dot-delimited semantic IDs")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Interior scope tokens must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_policy_boundary(self) -> InteriorScope:
        """Keep disabled scope empty and require an explicit bounded request when enabled."""

        overlap = set(self.allowed_semantic_prefixes).intersection(
            self.excluded_semantic_prefixes
        )
        if overlap:
            raise ValueError(
                "Interior prefixes cannot be both allowed and excluded: "
                f"{sorted(overlap)}"
            )
        if self.policy == "disabled":
            if self.allowed_semantic_prefixes or self.excluded_semantic_prefixes:
                raise ValueError("Disabled interior scope cannot authorize semantic prefixes")
            if self.levels or self.spaces:
                raise ValueError("Disabled interior scope cannot declare levels or spaces")
            if self.furnishing != "none" or self.evidence_status != "not_applicable":
                raise ValueError("Disabled interior scope requires no furnishing and no evidence")
            return self
        if not self.request.strip():
            raise ValueError("Enabled interior scope requires the user's exact request")
        if not self.allowed_semantic_prefixes:
            raise ValueError("Enabled interior scope requires at least one allowed semantic prefix")
        expected_evidence = {
            "visible_only": {"observed"},
            "proxy": {"inferred", "authored"},
            "measured": {"measured"},
            "authored": {"authored"},
        }[self.policy]
        if self.evidence_status not in expected_evidence:
            raise ValueError(
                f"Interior policy {self.policy} requires evidence_status in "
                f"{sorted(expected_evidence)}"
            )
        return self


class InteriorScopeApproval(StrictModel):
    """Persist one user approval bound to the exact InteriorScope bytes."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    approval_id: str
    job_id: str
    scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_policy: InteriorPolicy
    approved_semantic_prefixes: list[str]
    excluded_semantic_prefixes: list[str] = Field(default_factory=list)
    approved_levels: list[str] = Field(default_factory=list)
    approved_spaces: list[str] = Field(default_factory=list)
    furnishing: FurnishingPolicy
    recorded_via: Literal["manual_cli"] = "manual_cli"
    approved_at: str
    approval_note: str = Field(min_length=1)
    status: Literal["approved", "revoked"] = "approved"

    @field_validator("approval_note")
    @classmethod
    def validate_approval_note(cls, value: str) -> str:
        """Require preserved user approval text rather than an empty placeholder."""

        stripped = value.strip()
        if not stripped:
            raise ValueError("Interior approval note must contain the user's explicit decision")
        return stripped

    @model_validator(mode="after")
    def validate_approval_snapshot(self) -> InteriorScopeApproval:
        """Require a meaningful enabled policy and unique approved semantic prefixes."""

        if self.approved_policy == "disabled":
            raise ValueError("Disabled interior scope does not require an approval")
        if not self.approved_semantic_prefixes:
            raise ValueError("Interior approval requires at least one semantic prefix")
        if len(self.approved_semantic_prefixes) != len(set(self.approved_semantic_prefixes)):
            raise ValueError("Approved semantic prefixes must be unique")
        return self


class InteriorScopeValidation(StrictModel):
    """Report whether SceneSpec interior objects remain inside the approved boundary."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    job_id: str
    ok: bool
    effective_policy: InteriorPolicy
    scope_state: Literal[
        "default_disabled",
        "explicit_disabled",
        "draft",
        "approved",
        "stale",
        "revoked",
    ]
    scope_present: bool
    approval_present: bool
    approval_valid: bool
    scope_sha256: str | None = None
    approval_sha256: str | None = None
    interior_object_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_summary(self) -> InteriorScopeValidation:
        """Keep the success flag synchronized with the deterministic error list."""

        if self.ok != (not self.errors):
            raise ValueError("Interior validation ok must be true exactly when errors are empty")
        return self
