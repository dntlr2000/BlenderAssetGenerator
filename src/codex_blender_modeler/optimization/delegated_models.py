"""Optional exact five-asset technical delegation, separate from V0.7 approval."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .models import HashedArtifact, JobId, Sha256, SourceProvenance, StableId, V07StrictModel


class DelegatedStrictModel(V07StrictModel):
    """Keep optional authority timestamps timezone-aware and fail closed on naive values."""

    @model_validator(mode="after")
    def validate_authority_timestamps(self):
        """Require an explicit timezone for every top-level authority timestamp."""

        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError("delegated authority timestamps require a timezone")
        return self


class DelegatedAssetIdentityV01(DelegatedStrictModel):
    """Name one immutable job/reference identity in the expressly delegated task."""

    job_id: JobId
    reference_sha256: Sha256


class DelegatedOptimizationScopeV01(DelegatedStrictModel):
    """Preserve exact user delegation and its separately confirmed contract extension."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    artifact_kind: Literal["delegated_optimization_scope"] = "delegated_optimization_scope"
    delegation_id: StableId
    job_id: JobId
    issuer: Literal["host"] = "host"
    delegation_text: HashedArtifact
    extension_confirmation_text: HashedArtifact
    task_context_id: StableId
    expires_at: datetime
    maximum_authorizations_per_job: Literal[3] = 3
    allowed_assets: list[DelegatedAssetIdentityV01] = Field(min_length=5, max_length=5)
    extension_confirmation: Literal["explicit_user_confirmation"]
    purpose: Literal["five_asset_local_portable_gltf_technical_completion"] = (
        "five_asset_local_portable_gltf_technical_completion"
    )
    final_human_acceptance: Literal[False] = False
    created_at: datetime

    @model_validator(mode="after")
    def validate_scope(self) -> DelegatedOptimizationScopeV01:
        """Reject duplicate scope identities and a root outside the five declared jobs."""

        jobs = [item.job_id for item in self.allowed_assets]
        if len(set(jobs)) != 5 or self.job_id not in jobs:
            raise ValueError("delegation requires five unique jobs including its owning job")
        if self.delegation_text.kind != "other" or self.extension_confirmation_text.kind != "other":
            raise ValueError("delegation text must use kind=other")
        if self.expires_at.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("delegated scope timestamps must include a timezone")
        lifetime = (self.expires_at - self.created_at).total_seconds()
        if not 0 < lifetime <= 7 * 86400:
            raise ValueError("delegation must expire within seven days of host issuance")
        return self


class DelegatedOptimizationAuthorizationV01(DelegatedStrictModel):
    """Bind one delegated assistant technical decision to an exact current candidate."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    artifact_kind: Literal["delegated_optimization_authorization"] = (
        "delegated_optimization_authorization"
    )
    authorization_id: StableId
    grant_ordinal: int = Field(ge=1, le=3)
    job_id: JobId
    run_id: StableId
    actor: Literal["delegated_assistant"] = "delegated_assistant"
    issuer: Literal["host"] = "host"
    scope: HashedArtifact
    delegation_text_sha256: Sha256
    reference_sha256: Sha256
    source: SourceProvenance
    candidate_sha256: Sha256
    plan_sha256: Sha256
    review_sha256: Sha256
    profile_sha256: Sha256
    preflight_sha256: Sha256
    profile_id: Literal["portable_gltf"] = "portable_gltf"
    primary_format: Literal["glb"] = "glb"
    purpose: Literal["local_technical_package_generation_and_clean_import"] = (
        "local_technical_package_generation_and_clean_import"
    )
    decision_note: str = Field(min_length=1)
    one_time: Literal[True] = True
    final_human_acceptance: Literal[False] = False
    authorized_at: datetime

    @model_validator(mode="after")
    def validate_candidate(self) -> DelegatedOptimizationAuthorizationV01:
        """Keep authority on the exact SceneSpec-backed candidate without external intake."""

        if self.scope.kind != "other" or self.source.source_kind != "scene_spec":
            raise ValueError("delegated authority requires a scope and SceneSpec candidate")
        if self.source.scene_spec is None or self.candidate_sha256 != self.source.scene_spec.sha256:
            raise ValueError("candidate hash must match the exact source SceneSpec")
        return self


class DelegatedOptimizationConsumptionV01(DelegatedStrictModel):
    """Append an immutable, exact single-use receipt without rewriting the grant."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    artifact_kind: Literal["delegated_optimization_consumption"] = (
        "delegated_optimization_consumption"
    )
    job_id: JobId
    run_id: StableId
    authorization: HashedArtifact
    source_fingerprint: Sha256
    plan_sha256: Sha256
    actor: Literal["delegated_assistant"] = "delegated_assistant"
    final_human_acceptance: Literal[False] = False
    consumed_at: datetime


class DelegatedOptimizationWorkflowBindingV01(DelegatedStrictModel):
    """Explicitly bind a grant to one unchanged Standard workflow optimization gate."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    artifact_kind: Literal["delegated_optimization_workflow_binding"] = (
        "delegated_optimization_workflow_binding"
    )
    job_id: JobId
    workflow_id: StableId
    run_id: StableId
    workflow_plan: HashedArtifact
    workflow_input_fingerprint: Sha256
    authorization: HashedArtifact
    actor: Literal["delegated_assistant"] = "delegated_assistant"
    final_human_acceptance: Literal[False] = False
    created_at: datetime


class DelegatedPackageAuthorityV01(DelegatedStrictModel):
    """Self-contained technical package evidence; never future execution or human acceptance."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    artifact_kind: Literal["delegated_package_authority"] = "delegated_package_authority"
    job_id: JobId
    run_id: StableId
    package_id: StableId
    profile_id: Literal["portable_gltf"] = "portable_gltf"
    actor: Literal["delegated_assistant"] = "delegated_assistant"
    source_fingerprint: Sha256
    evidence_sha256: dict[str, Sha256]
    final_human_acceptance: Literal[False] = False
    grants_execution_authority: Literal[False] = False
    created_at: datetime
