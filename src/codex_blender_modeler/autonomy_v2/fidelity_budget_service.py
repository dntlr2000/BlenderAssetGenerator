"""Read-only lifetime accounting and single-writer admission for finite fidelity epochs."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..blender_artifacts import sha256_file, stable_json_digest
from ..config import get_settings
from ..production.validation import ensure_contained_production_path
from .fidelity_budget_models import (
    FidelityBudgetEpochV01,
    FidelityHistoryEntryV01,
    FidelityLifetimeUsageV01,
)
from .models import AutonomyBudgetV03, AutonomyStateV2, RootAuthorizationV2, parse_autonomy_budget
from .transitions import validate_initial_state, validate_state_transition


def _preflight_history(root: Path, session_id: str) -> tuple[int, dict[str, str]]:
    """Rehash closure history and replay its existing resource chain without changing receipts."""

    from ..material_closure.models import MaterialPreflightBudget, MaterialPromotionPreflightRequest
    from ..material_closure.preflight import validate_exact_artifact
    from ..material_closure.service import _resource_chain_head

    directory = root / "production" / "material_closure" / session_id
    inventory = {}
    requests = []
    for path in sorted(directory.rglob("*.json")):
        safe = ensure_contained_production_path(root, path, must_exist=True)
        inventory[path.relative_to(root).as_posix()] = sha256_file(safe)
        if path.name == "preflight_request.json":
            requests.append(MaterialPromotionPreflightRequest.model_validate_json(safe.read_bytes()))
    if not requests:
        return 0, inventory
    request = requests[-1]
    budget_path = validate_exact_artifact(root, request.budget)
    budget = MaterialPreflightBudget.model_validate_json(budget_path.read_bytes())
    return _resource_chain_head(root, request, budget).preflight_blender_runs, inventory


def _session_history(root: Path, session: Path) -> FidelityHistoryEntryV01:
    """Validate immutable state/ledger chains and retain conservative consumed/reserved totals."""

    from .delivery_service import validate_v2_artifact
    from .quality_revision_service import _load_ledger, _render_reservations, load_optional_loop

    budget = parse_autonomy_budget((session / "budget.json").read_bytes())
    states = []
    for index, path in enumerate(sorted((session / "states").glob("*.json"))):
        state = AutonomyStateV2.model_validate_json(path.read_bytes())
        if path.stem != f"{index:04d}" or state.sequence != index:
            raise ValueError("funding history contains an incomplete state chain")
        if (state.job_id, state.session_id) != (root.name, session.name):
            raise ValueError("funding history state belongs to another session")
        if states:
            validate_state_transition(states[-1], state)
        else:
            validate_initial_state(state)
        states.append(state)
    if not states:
        raise ValueError("funding history session has no immutable state")
    state = states[-1]
    validate_v2_artifact(root, state.plan)
    usage = state.budget_usage
    preflight_used, closure_inventory = _preflight_history(root, session.name)
    consumed = FidelityLifetimeUsageV01(
        structural=usage.structural_rounds,
        local=max(usage.parametric_convergence_iterations,
                  usage.material_rounds - 1 - usage.structural_rounds),
        blender_builds=usage.total_blender_builds,
        preflight_blender_runs=preflight_used,
        quality_evaluations=usage.total_quality_evaluations,
        promotions=usage.canonical_promotions,
    )
    binding = load_optional_loop(root, session.name)
    if binding is not None:
        loop, artifact = binding
        ledger = _load_ledger(root, session.name, loop, artifact)
        renders = _render_reservations(root, session.name, artifact)
        consumed.quality_evaluations += len(renders)
        if ledger:
            last = ledger[-1][0]
            # A reservation survives a crash even when its candidate never reaches promotion.
            initial = next(
                (item.budget_usage for item in states
                 if item.next_action == "run_integrated_quality"),
                states[0].budget_usage,
            )
            consumed.structural = max(consumed.structural, last.structural_used)
            consumed.local = max(consumed.local, last.local_used)
            consumed.strategy_switches = last.strategy_switches_used
            consumed.blender_builds = max(
                consumed.blender_builds,
                initial.total_blender_builds
                + last.cost_used.materializations + last.cost_used.builds,
            )
            consumed.promotions = max(
                consumed.promotions, initial.canonical_promotions + last.cost_used.promotions,
            )
            consumed.quality_evaluations = max(
                consumed.quality_evaluations,
                initial.total_quality_evaluations + last.cost_used.qa_runs,
            )
    inventory = dict(closure_inventory)
    for path in sorted(session.rglob("*.json")):
        safe = ensure_contained_production_path(root, path, must_exist=True)
        inventory[path.relative_to(root).as_posix()] = sha256_file(safe)
    return FidelityHistoryEntryV01(
        job_id=root.name, session_id=session.name,
        session_evidence_sha256=stable_json_digest(inventory),
        last_state_sha256=sha256_file(session / "states" / f"{state.sequence:04d}.json"),
        budget_sha256=sha256_file(session / "budget.json"),
        status=state.status, next_action=state.next_action,
        funded_epoch=isinstance(budget, AutonomyBudgetV03), usage=consumed,
        epoch_id=budget.funding.epoch_id if isinstance(budget, AutonomyBudgetV03) else None,
    )


def read_fidelity_history(
    reference_sha256: str, *, exclude: tuple[str, str] | None = None,
) -> list[FidelityHistoryEntryV01]:
    """Find reference-identical AQ sessions independently of job, session or asset labels."""

    from .delivery_service import validate_v2_artifact

    workspace = get_settings().workspace_root.resolve()
    result = []
    seen = set()
    for path in sorted(workspace.glob("*/production/autonomy_v2/*/root_authorization.json")):
        if path.resolve() in seen:
            continue
        seen.add(path.resolve())
        root, session = path.parents[3], path.parent
        safe = ensure_contained_production_path(workspace, path, must_exist=True)
        authorization = RootAuthorizationV2.model_validate_json(safe.read_bytes())
        if (root.name, session.name) == exclude:
            continue
        if authorization.primary_reference.sha256 != reference_sha256:
            continue
        if (authorization.job_id, authorization.session_id) != (root.name, session.name):
            raise ValueError("funding history authorization belongs to another session")
        validate_v2_artifact(root, authorization.primary_reference)
        validate_v2_artifact(root, authorization.budget)
        result.append(_session_history(root, session))
    return sorted(result, key=lambda item: (item.job_id, item.session_id))


def plan_fidelity_budget_epoch(
    *, epoch_id: str, job_id: str, reference_path: Path,
    initial_object_limit: int, correction_object_limit: int,
    structural_rounds: int = 3, parametric_rounds: int = 0, material_corrections: int = 2,
) -> FidelityBudgetEpochV01:
    """Prepare a reviewable funding proposal only; no session or future artifact is authorized."""

    reference_sha256 = sha256_file(reference_path)
    history = read_fidelity_history(reference_sha256)
    prior = FidelityLifetimeUsageV01(**{
        key: sum(getattr(item.usage, key) for item in history)
        for key in FidelityLifetimeUsageV01.model_fields
    })
    return FidelityBudgetEpochV01(
        epoch_id=epoch_id, job_id=job_id, reference_sha256=reference_sha256,
        prior_history=history, prior_usage=prior,
        initial_object_limit=initial_object_limit, correction_object_limit=correction_object_limit,
        structural_rounds=structural_rounds, parametric_rounds=parametric_rounds,
        material_corrections=material_corrections,
    )


def validate_fidelity_epoch_history(
    funding: FidelityBudgetEpochV01, *, active_session: tuple[str, str] | None = None,
) -> None:
    """Reject stale history, renaming resets or a concurrent funded epoch before new effects."""

    current = read_fidelity_history(funding.reference_sha256, exclude=active_session)
    if current != funding.prior_history:
        raise ValueError("fidelity funding history changed; exact new epoch scope is required")
    if active_session is None and any(
        item.funded_epoch and item.next_action != "none" for item in current
    ):
        raise PermissionError("a reference-identical funded epoch is still active")
    if any(item.epoch_id == funding.epoch_id for item in current):
        raise PermissionError("a consumed fidelity funding epoch cannot be reused")


def require_funded_loop(root: Path, session_id: str, budget: AutonomyBudgetV03) -> None:
    """Require the matching companion before the first funded controller or canonical action."""

    from .quality_revision_models import AQQualityRevisionLoopV03
    from .quality_revision_service import load_optional_loop

    binding = load_optional_loop(root, session_id)
    if binding is None or not isinstance(binding[0], AQQualityRevisionLoopV03):
        raise PermissionError("funded execution requires the exact V0.3 quality loop first")
    if binding[0].funding != budget.funding:
        raise ValueError("funded loop differs from the root budget epoch")
    validate_fidelity_epoch_history(budget.funding, active_session=(root.name, session_id))


@contextmanager
def fidelity_epoch_admission(funding: FidelityBudgetEpochV01) -> Iterator[None]:
    """Serialize reference-wide epoch creation with a persistent, nonrefundable guard."""

    workspace = get_settings().workspace_root.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    guard = ensure_contained_production_path(
        workspace, workspace / ".fidelity_budget" / f"{funding.reference_sha256}.guard",
        must_exist=False,
    )
    guard.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(guard, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        validate_fidelity_epoch_history(funding)
        yield
    finally:
        if locked:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
