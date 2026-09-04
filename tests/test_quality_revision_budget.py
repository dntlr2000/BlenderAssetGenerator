"""Cost, single-loop continuity, shared local limits, and plateau strategy tests."""

from __future__ import annotations

import pytest
from test_reference_fidelity import artifact

from codex_blender_modeler.autonomy_v2.quality_revision_budget import reserve_revision
from codex_blender_modeler.autonomy_v2.quality_revision_models import (
    AQQualityRevisionLoopV01,
    RevisionCostV01,
    StructuralReentryPlanV01,
)


def loop() -> AQQualityRevisionLoopV01:
    """Create an explicitly opted-in fixture plan with separately declared execution costs."""

    return AQQualityRevisionLoopV01(
        job_id="fidelity_fixture",
        session_id="session",
        root_authorization=artifact("root"),
        approval_envelope=artifact("envelope"),
        hypothesis=artifact("hypothesis"),
        initial_state=artifact("state"),
        allow_disabled_experimental=True,
        cost_limit=RevisionCostV01(
            materializations=20,
            builds=5,
            qa_runs=5,
            closure_runs=5,
            diagnostic_views=20,
            promotions=10,
        ),
    )


def reentry(index: int, route: str = "structural_reentry") -> StructuralReentryPlanV01:
    """Bind a correction's exact before sources, route, expected policy purpose and cost."""

    return StructuralReentryPlanV01(
        loop=artifact("loop"),
        attempt=artifact(f"attempt-{index}"),
        round_index=index,
        source_scene=artifact("scene"),
        source_modeling_plan=artifact("modeling"),
        source_blend=artifact("blend"),
        feature_ids=["form"],
        target_ids=["body"],
        route=route,
        strategy="section-loft",
        change_strategy=False,
        cost=RevisionCostV01(
            materializations=2,
            builds=1,
            qa_runs=1,
            closure_runs=1,
            diagnostic_views=4,
            promotions=2,
        ),
        comparison_camera_sha256=artifact("camera").sha256,
        policy_gate={
            "structural_reentry": "structural_candidate_promotion",
            "parametric_revision": "bounded_parametric_revision",
            "material_revision": "material_candidate_promotion",
        }[route],
    )


def reserve(plan, prior=None):
    """Reserve one immutable fixture step, retaining the previous ledger fingerprint."""

    return reserve_revision(
        loop(),
        plan,
        loop_artifact=artifact("loop"),
        plan_artifact=artifact(f"plan-{plan.round_index}"),
        previous=prior,
        previous_artifact=artifact(f"ledger-{prior.sequence}") if prior else None,
    )


def test_three_structural_rounds_cannot_reset_or_expand() -> None:
    """A fresh job label, repeat ordinal or fourth structural round cannot regain budget."""

    first = reserve(reentry(1))
    with pytest.raises(ValueError, match="reset or skip"):
        reserve(reentry(1), first)
    second = reserve(reentry(2), first)
    third = reserve(reentry(3), second)
    with pytest.raises(PermissionError, match="round budget"):
        reserve(reentry(4), third)
    with pytest.raises(ValueError, match="another loop"):
        reserve(reentry(2).model_copy(update={"loop": artifact("renamed-loop")}), first)


def test_local_material_and_dimension_revisions_share_two_slots() -> None:
    """Changing the correction category cannot create a fresh local retry budget."""

    first = reserve(reentry(1, "material_revision"))
    second = reserve(reentry(2, "parametric_revision"), first)
    assert second.local_used == 2
    with pytest.raises(PermissionError, match="round budget"):
        reserve(reentry(3, "material_revision"), second)


def test_remaining_rounds_do_not_override_blender_cost_limit() -> None:
    """Reserve every materialization/build before launch and fail without any effect."""

    plan = reentry(1)
    plan.cost.materializations = 21
    with pytest.raises(PermissionError, match="materializations budget"):
        reserve(plan)


def test_only_one_representation_strategy_change_is_budgeted() -> None:
    """Strategy changes consume, rather than reset, the structural budget."""

    first = reserve(reentry(1).model_copy(update={"change_strategy": True}))
    with pytest.raises(PermissionError, match="strategy change"):
        reserve(reentry(2).model_copy(update={"change_strategy": True}), first)


def test_persistent_structure_is_not_hidden_by_an_unrelated_improvement() -> None:
    """Resolving a smaller feature cannot hide a repeatedly unresolved major structure defect."""

    from types import SimpleNamespace

    from codex_blender_modeler.autonomy_v2.quality_revision_budget import require_strategy_change

    first = SimpleNamespace(
        strategy="loft",
        next_action="structural_reentry",
        unresolved_features=["volume", "small_edge"],
    )
    second = SimpleNamespace(
        strategy="loft", next_action="structural_reentry", unresolved_features=["volume"]
    )
    assert require_strategy_change([first, second])
    second.next_action = "material_revision"
    assert not require_strategy_change([first, second])


def test_material_plateau_never_authorizes_structural_reauthoring() -> None:
    """Change material strategy within its local slot, never use geometry as camouflage."""

    from types import SimpleNamespace

    from codex_blender_modeler.autonomy_v2.quality_revision_budget import select_revision_route

    repeated = SimpleNamespace(
        strategy="isotropic-noise",
        next_action="material_revision",
        unresolved_features=["grain_direction"],
    )
    evaluation = SimpleNamespace(next_action="material_revision")
    route, _reason = select_revision_route(
        evaluation,
        [repeated, repeated],
        structural_used=0,
        local_used=1,
        strategy_switches_used=0,
        loop=loop(),
    )
    assert route == "material_revision"
    route, _reason = select_revision_route(
        evaluation,
        [repeated, repeated],
        structural_used=0,
        local_used=1,
        strategy_switches_used=1,
        loop=loop(),
    )
    assert route == "review_required"
