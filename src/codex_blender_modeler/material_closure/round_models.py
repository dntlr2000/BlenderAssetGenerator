"""Explicit additive source bindings for several material rounds in one AQ session."""

from __future__ import annotations

import json
from typing import Literal, TypeVar, cast

from pydantic import BaseModel, model_validator

from ..stabilization.models import PortableId
from .models import (
    ExactArtifact,
    MaterialClosureSourceBindingArtifact,
    MaterialGraphRebindingPlan,
    MaterialGraphRebindingReceipt,
)

MATERIAL_CLOSURE_ROUND_SCHEMA_VERSION = "0.2.0"
ModelT = TypeVar("ModelT", bound=BaseModel)


class MaterialClosureSourceBindingV02(MaterialClosureSourceBindingArtifact):
    """Freeze one candidate and source state without replacing earlier session bindings."""

    schema_version: Literal["0.2.0"] = MATERIAL_CLOSURE_ROUND_SCHEMA_VERSION
    authority_mode: Literal["aq_same_session"] = "aq_same_session"
    execution_id: PortableId
    source_state: ExactArtifact
    previous_material_phase_receipt: ExactArtifact | None = None

    def source_binding_path(self) -> str:
        """Own a distinct immutable binding directory within the existing AQ session."""
        return (
            f"production/material_closure/{self.session_id}/bindings/"
            f"{self.binding_id}/source_binding.json"
        )

    def canonical_observation_prefix(self) -> str:
        """Keep this round's immutable observations beside its own binding."""
        return (
            f"production/material_closure/{self.session_id}/bindings/"
            f"{self.binding_id}/canonical_observations/"
        )

    @model_validator(mode="after")
    def validate_round(self) -> MaterialClosureSourceBindingV02:
        """Require exact AQ state and immutable round-owned observations before collection."""
        prefix = f"production/autonomy_v2/{self.session_id}/states/"
        leaf = self.source_state.path.removeprefix(prefix)
        if (
            self.source_state.kind not in {"state", "autonomy_v2_state"}
            or not self.source_state.path.startswith(prefix)
            or not leaf.endswith(".json")
            or not leaf[:-5].isdigit()
            or len(leaf[:-5]) < 4
        ):
            raise ValueError("round source state must use its exact AQ state leaf")
        observation_prefix = self.canonical_observation_prefix()
        if (
            self.canonical_build_provenance_path != f"{observation_prefix}build_provenance.json"
            or self.canonical_scene_inventory_path != f"{observation_prefix}scene_inventory.json"
        ):
            raise ValueError("round observations must be immutable binding-owned files")
        if (
            self.previous_material_phase_receipt is not None
            and self.previous_material_phase_receipt.kind != "material_phase_receipt"
        ):
            raise ValueError("round material lineage requires an exact host phase receipt")
        return self


class MaterialGraphRebindingPlanV02(MaterialGraphRebindingPlan):
    """Select an exact round binding without granting new retry or promotion authority."""

    schema_version: Literal["0.2.0"] = MATERIAL_CLOSURE_ROUND_SCHEMA_VERSION
    binding_id: PortableId

    def source_binding_path(self) -> str:
        """Require the named round's exact binding rather than a mutable session pointer."""
        return (
            f"production/material_closure/{self.session_id}/bindings/"
            f"{self.binding_id}/source_binding.json"
        )


class MaterialGraphRebindingReceiptV02(MaterialGraphRebindingReceipt):
    """Record an immutable graph derivative for the same exact round binding."""

    schema_version: Literal["0.2.0"] = MATERIAL_CLOSURE_ROUND_SCHEMA_VERSION
    binding_id: PortableId

    def source_binding_path(self) -> str:
        """Bind the receipt to the identical round namespace selected by its plan."""
        return (
            f"production/material_closure/{self.session_id}/bindings/"
            f"{self.binding_id}/source_binding.json"
        )


def parse_material_closure_contract(payload: bytes | str, model: type[ModelT]) -> ModelT:
    """Dispatch only three additive companions by exact schema version; never migrate bytes."""
    companions = {
        MaterialClosureSourceBindingArtifact: MaterialClosureSourceBindingV02,
        MaterialGraphRebindingPlan: MaterialGraphRebindingPlanV02,
        MaterialGraphRebindingReceipt: MaterialGraphRebindingReceiptV02,
    }
    if model not in companions:
        return model.model_validate_json(payload)
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Material Closure companion must be a JSON object")
    version = data.get("schema_version")
    if version == "0.1.0":
        return model.model_validate_json(payload)
    if version == MATERIAL_CLOSURE_ROUND_SCHEMA_VERSION:
        return cast(ModelT, companions[model].model_validate_json(payload))
    raise ValueError("unknown Material Closure companion schema version")
