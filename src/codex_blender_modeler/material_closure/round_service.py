"""Validate immutable material round sources without changing AQ state or budgets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .models import ExactArtifact
from .preflight import validate_exact_artifact
from .round_models import MaterialClosureSourceBindingV02

if TYPE_CHECKING:
    from ..autonomy_v2.material_phase_models import MaterialPhaseReceiptV2
    from ..autonomy_v2.models import AutonomyPlanV2


def same_bytes(left: object, right: object) -> bool:
    """Compare exact contained artifacts independently of descriptive kind or ID labels."""
    return all(getattr(left, key) == getattr(right, key) for key in ("path", "sha256", "byte_size"))


def validate_round_source(
    root: Path,
    binding: MaterialClosureSourceBindingV02,
    plan: AutonomyPlanV2,
    *,
    require_current_state: bool = False,
) -> MaterialPhaseReceiptV2 | None:
    """Bind a round to its source state, latest geometry and optional promoted material lineage."""
    from ..autonomy_v2.material_phase_service import validate_material_phase_receipt_v2
    from ..autonomy_v2.models import AQV2Artifact, AutonomyPlanV2, AutonomyStateV2

    state_path = validate_exact_artifact(root, binding.source_state)
    state = AutonomyStateV2.model_validate_json(state_path.read_bytes())
    keys = ("job_id", "workflow_id", "dispatch_id", "session_id")
    if (
        tuple(getattr(state, key) for key in keys) != tuple(getattr(binding, key) for key in keys)
        or tuple(getattr(plan, key) for key in keys) != tuple(getattr(binding, key) for key in keys)
        or (state.phase, state.status, state.next_action)
        != ("authoring", "running", "execute_controller")
        or binding.execution_id != f"exec-{state.sequence + 1:04d}-material_authoring"
        or binding.source_state.path
        != f"production/autonomy_v2/{binding.session_id}/states/{state.sequence:04d}.json"
        or state.plan.path != binding.autonomy_plan_path
    ):
        raise ValueError("material round source is not its exact AQ authoring boundary")
    validate_exact_artifact(root, state.plan)
    if AutonomyPlanV2.model_validate_json((root / state.plan.path).read_bytes()) != plan:
        raise ValueError("material round source state binds another plan")
    if require_current_state:
        from ..autonomy_v2.controller_bridge import _state_chain

        latest, latest_artifact = _state_chain(
            root, root / "production/autonomy_v2" / plan.session_id
        )[-1]
        if latest != state or not same_bytes(latest_artifact, binding.source_state):
            raise ValueError("material round source state is stale")
    geometry_match = next(
        (
            (index, item)
            for index, item in reversed(list(enumerate(state.provenance)))
            if item.kind == "geometry_candidate_validation_receipt"
        ),
        None,
    )
    if geometry_match is None:
        raise ValueError("material round omits the latest exact geometry receipt")
    geometry_index, geometry = geometry_match
    if geometry.path != binding.geometry_candidate_validation_receipt_path:
        raise ValueError("material round omits the latest exact geometry receipt")
    validate_exact_artifact(root, geometry)
    material = binding.previous_material_phase_receipt
    material_match = next(
        (
            (index, item)
            for index, item in reversed(list(enumerate(state.provenance)))
            if item.kind == "material_phase_receipt"
        ),
        None,
    )
    if material is None:
        if material_match is not None and material_match[0] > geometry_index:
            raise ValueError("material round omits the promoted material lineage")
        return None
    if material_match is None or not same_bytes(material, material_match[1]):
        raise ValueError("material round mixes different material promotion receipts")
    if material_match[0] < geometry_index:
        raise ValueError("material round receipt precedes its current geometry")
    receipt = validate_material_phase_receipt_v2(
        root,
        AQV2Artifact(
            artifact_id=material.artifact_id,
            kind=material.kind,
            path=material.path,
            sha256=material.sha256,
            byte_size=material.byte_size,
        ),
        require_current=True,
    )
    if tuple(getattr(receipt, key) for key in keys) != tuple(getattr(binding, key) for key in keys):
        raise ValueError("material round receipt belongs to another AQ session")
    current_blend = root / "blender/scene.blend"
    from ..blender_artifacts import sha256_file

    if (
        sha256_file(current_blend) != receipt.authoring_blend_snapshot.sha256
        or current_blend.stat().st_size != receipt.authoring_blend_snapshot.byte_size
    ):
        raise ValueError("material round canonical Blend is not the promoted snapshot")
    for observation, snapshot in (
        (binding.canonical_scene_inventory_path, receipt.scene_inventory_snapshot),
        (binding.canonical_build_provenance_path, receipt.build_provenance_snapshot),
    ):
        if json.loads((root / observation).read_bytes()) != json.loads(
            (root / snapshot.path).read_bytes()
        ):
            raise ValueError("material round observations differ from the promoted Blend evidence")
    return receipt


def validate_round_preflight_state(
    root: Path,
    binding: MaterialClosureSourceBindingV02,
    observation_state: ExactArtifact,
    *,
    require_current: bool,
) -> None:
    """Revalidate one exact round against the preflight context and current AQ chain."""
    from ..autonomy_v2.models import AutonomyPlanV2

    if not same_bytes(binding.source_state, observation_state):
        raise ValueError("material preflight mixes source states from different rounds")
    if require_current:
        plan = AutonomyPlanV2.model_validate_json((root / binding.autonomy_plan_path).read_bytes())
        validate_round_source(root, binding, plan, require_current_state=True)
