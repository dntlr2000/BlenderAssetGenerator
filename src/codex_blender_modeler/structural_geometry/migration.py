"""Explicit hash-bound migration helpers for SceneSpec 0.2 to opt-in 0.3 candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from ..models import SceneSpec
from .models import (
    CONTRACT_VERSION,
    JobRelativePath,
    SceneSpecV03,
    Sha256,
    StableId,
    StructuralStrictModel,
)


def canonical_json_sha256(value: Any) -> str:
    """Return the SHA-256 of a compact deterministic JSON representation."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class SceneSpecV03MigrationPlan(StructuralStrictModel):
    """Bind one explicit legacy source to the exact validated 0.3 candidate."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    schema_version: Literal["0.1.0"] = CONTRACT_VERSION
    source_schema_version: Literal["0.2.0"] = "0.2.0"
    target_schema_version: Literal["0.3.0"] = "0.3.0"
    source_sha256: Sha256
    candidate_sha256: Sha256
    source_file_sha256: Sha256 | None = None
    candidate_file_sha256: Sha256 | None = None
    added_fields: list[str] = Field(default_factory=lambda: ["objects[].geometry_intent"])

    @model_validator(mode="after")
    def validate_added_fields(self) -> SceneSpecV03MigrationPlan:
        """Require the plan to declare the one backward-compatible opt-in extension."""

        if self.added_fields != ["objects[].geometry_intent"]:
            raise ValueError("migration added_fields must name only geometry_intent")
        return self


class SceneSpecV03MigrationReceipt(StructuralStrictModel):
    """Prove one derived-only migration application without canonical replacement."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    schema_version: Literal["0.1.0"] = CONTRACT_VERSION
    migration_id: StableId
    source_path: JobRelativePath
    source_file_sha256: Sha256
    source_canonical_sha256: Sha256
    migration_plan_path: JobRelativePath
    migration_plan_file_sha256: Sha256
    candidate_path: JobRelativePath
    candidate_file_sha256: Sha256
    candidate_canonical_sha256: Sha256
    derived_scene_spec_path: JobRelativePath
    derived_scene_spec_file_sha256: Sha256
    canonical_mutation_allowed: Literal[False] = False
    applied: Literal[True] = True
    created_at: datetime


def create_v03_migration_plan(
    source: SceneSpec | dict[str, Any],
) -> tuple[SceneSpecV03MigrationPlan, SceneSpecV03]:
    """Validate a 0.2 source and return an immutable plan plus exact 0.3 candidate."""

    legacy = source if isinstance(source, SceneSpec) else SceneSpec.model_validate(source)
    source_payload = legacy.model_dump(mode="json")
    candidate_payload = dict(source_payload)
    candidate_payload["schema_version"] = "0.3.0"
    candidate = SceneSpecV03.model_validate_json(json.dumps(candidate_payload))
    plan = SceneSpecV03MigrationPlan(
        source_sha256=canonical_json_sha256(source_payload),
        candidate_sha256=canonical_json_sha256(candidate.model_dump(mode="json")),
    )
    return plan, candidate


def apply_v03_migration_plan(
    source: SceneSpec | dict[str, Any],
    candidate: SceneSpecV03 | dict[str, Any],
    plan: SceneSpecV03MigrationPlan | dict[str, Any],
) -> SceneSpecV03:
    """Return the candidate only when source, candidate, and exact migration hashes match."""

    validated_plan = (
        plan
        if isinstance(plan, SceneSpecV03MigrationPlan)
        else SceneSpecV03MigrationPlan.model_validate_json(json.dumps(plan))
    )
    legacy = source if isinstance(source, SceneSpec) else SceneSpec.model_validate(source)
    validated_candidate = (
        candidate
        if isinstance(candidate, SceneSpecV03)
        else SceneSpecV03.model_validate_json(json.dumps(candidate))
    )
    source_hash = canonical_json_sha256(legacy.model_dump(mode="json"))
    candidate_hash = canonical_json_sha256(validated_candidate.model_dump(mode="json"))
    if source_hash != validated_plan.source_sha256:
        raise ValueError("SceneSpec 0.2 source no longer matches the migration plan")
    if candidate_hash != validated_plan.candidate_sha256:
        raise ValueError("SceneSpec 0.3 candidate no longer matches the migration plan")
    return validated_candidate
