"""Host enforcement for one finite, source-bound reference-fidelity campaign mandate."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from ..blender_artifacts import native_io_path, sha256_file
from ..config import get_settings
from ..production.activation_models import ActivationArtifact
from ..production.validation import ensure_contained_production_path
from ..reference_fidelity.models import (
    FidelityComparisonV01,
    FidelityEvaluationV01,
    ModelingHypothesisV01,
    VisualFindingSetV01,
)
from .delegation_models import (
    DelegationAsset,
    DelegationBindingV01,
    DelegationCost,
    DelegationDecisionV01,
    DelegationOutcomeV01,
    DelegationPreparationV01,
    DelegationScopeV01,
    FidelityCampaignDelegationV01,
)
from .fidelity_budget_service import read_fidelity_history


def _workspace() -> Path:
    """Use the configured workspace so isolated tests cannot consume production authority."""
    return get_settings().workspace_root.resolve()


def _directory(delegation_id: str) -> Path:
    """Validate the ID before resolving the persistent workspace-owned authority namespace."""
    from pydantic import TypeAdapter

    from ..stabilization.models import PortableId

    TypeAdapter(PortableId).validate_python(delegation_id)
    root = _workspace()
    return ensure_contained_production_path(
        root,
        root / ".fidelity_delegations" / delegation_id,
        must_exist=False,
    )


def exact_artifact(root: Path, path: Path, kind: str) -> ActivationArtifact:
    """Hash a contained, non-linked immutable artifact using its actual file bytes."""
    safe = ensure_contained_production_path(root, path, must_exist=True)
    return ActivationArtifact(
        artifact_id=f"{kind}-{sha256_file(safe)[:24]}",
        kind=kind,
        path=safe.relative_to(root).as_posix(),
        sha256=sha256_file(safe),
        byte_size=safe.stat().st_size,
    )


def _read(root: Path, artifact: ActivationArtifact) -> bytes:
    """Reject missing, changed, escaped or linked evidence before trusting any declaration."""
    path = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
    if sha256_file(path) != artifact.sha256 or path.stat().st_size != artifact.byte_size:
        raise ValueError("delegation artifact hash/size changed")
    return path.read_bytes()


def _publish(path: Path, model: BaseModel, kind: str) -> ActivationArtifact:
    """Publish exclusive evidence durably; a crash leaves visible, non-reusable evidence."""
    root = _workspace()
    safe = ensure_contained_production_path(root, path, must_exist=False)
    safe.parent.mkdir(parents=True, exist_ok=True)
    data = (model.model_dump_json(indent=2) + "\n").encode("utf-8")
    if safe.exists():
        if safe.read_bytes() != data:
            raise ValueError("immutable delegation evidence already exists with other bytes")
    else:
        with safe.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    return exact_artifact(root, safe, kind)


@contextmanager
def _guard() -> Iterator[None]:
    """Serialize approvals, reservations and admissions with an OS lock that survives crashes."""
    root = _workspace()
    root.mkdir(parents=True, exist_ok=True)
    path = ensure_contained_production_path(
        root,
        root / ".fidelity_delegations" / ".guard",
        must_exist=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(native_io_path(path), os.O_CREAT | os.O_RDWR, 0o600)
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


def _validate_source(contract: FidelityCampaignDelegationV01) -> None:
    """Require the approved clean Git checkpoint, baseline and current source-file hashes."""
    from ..production.activation_service import (
        inspect_activation_source_checkpoint,
        load_activation_baseline,
        load_activation_source_manifest,
    )

    root = get_settings().repo_root.resolve()
    manifest = load_activation_source_manifest(root, contract.source_manifest)
    baseline = load_activation_baseline(root, contract.baseline)
    checkpoint = inspect_activation_source_checkpoint(root)
    if (
        not checkpoint["working_tree_clean"]
        or not checkpoint["staged_tree_clean"]
        or checkpoint["git_commit_sha"] != manifest.git_commit_sha
        or checkpoint["git_tree_sha"] != manifest.git_tree_sha
        or baseline.source_manifest != contract.source_manifest
    ):
        raise PermissionError("delegation source/baseline is stale or not clean")
    for item in manifest.source_files:
        path = ensure_contained_production_path(root, root / item.path, must_exist=True)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        # Git archives can materialize LF or CRLF according to Git configuration.
        # Only ordinary text can use that equivalence; immutable -text snapshots stay raw.
        if digest != item.sha256 and not item.path.startswith("verification/evidence/"):
            if b"\0" not in data and "* text=auto" in (root / ".gitattributes").read_text():
                normalized = data.replace(b"\r\n", b"\n")
                if b"\r" not in normalized:
                    for payload in (normalized, normalized.replace(b"\n", b"\r\n")):
                        if hashlib.sha256(payload).hexdigest() == item.sha256:
                            digest = item.sha256
                            break
        if digest != item.sha256:
            raise ValueError(
                f"delegation source bytes differ from the approved checkpoint: {item.path}"
            )


def _validate_asset_evidence(asset: DelegationAsset) -> ModelingHypothesisV01:
    """Rehash inherited evidence and the independent observed criteria without migrating them."""
    root = get_settings().repo_root.resolve()
    _read(root, asset.reference)
    for artifact in asset.inherited_evidence:
        _read(root, artifact)
    hypothesis = ModelingHypothesisV01.model_validate_json(_read(root, asset.hypothesis))
    if hypothesis.reference.sha256 != asset.reference.sha256:
        raise ValueError("delegation hypothesis belongs to another reference")
    return hypothesis


def _history(contract: FidelityCampaignDelegationV01, scopes: list[DelegationScopeV01]) -> None:
    """Preserve old sessions and reject unreserved reference history or counter resets."""
    from .models import AutonomyStateV2

    for asset in contract.assets:
        current = read_fidelity_history(asset.reference.sha256)
        old = {(item.job_id, item.session_id): item for item in asset.prior_history}
        owned = {item.job_id: item for item in scopes if item.asset_id == asset.asset_id}
        observed = {(item.job_id, item.session_id): item for item in current}
        if any(observed.get(key) != value for key, value in old.items()):
            raise ValueError("delegation inherited history changed or disappeared")
        initial_used = 0
        for item in current:
            key = (item.job_id, item.session_id)
            if key not in old and (
                item.job_id not in owned or item.epoch_id != owned[item.job_id].funding.epoch_id
            ):
                raise PermissionError(
                    "unreserved reference history cannot reset delegation budgets"
                )
            if key in old:
                session = _workspace() / item.job_id / "production/autonomy_v2" / item.session_id
                lock = ensure_contained_production_path(
                    _workspace(), session / "autonomy.lock", must_exist=False
                )
                if lock.exists():
                    raise PermissionError(
                        "inherited session has an execution lock; preserve history"
                    )
                states = sorted((session / "states").glob("*.json"))
                state = AutonomyStateV2.model_validate_json(states[-1].read_bytes())
                initial_used += state.budget_usage.initial_candidates
        if asset.prior_initial_candidates < initial_used:
            raise ValueError("delegation hides previously consumed initial candidates")


def _validate_predecessor(contract: FidelityCampaignDelegationV01) -> None:
    """Require exact closed ancestry and retain every predecessor's reserved capacity."""
    _predecessor_scopes(contract)


def _predecessor_scopes(contract: FidelityCampaignDelegationV01) -> list[DelegationScopeV01]:
    """Replay approved ancestry oldest first without resetting observations at a new parent."""
    groups = []
    seen = {contract.delegation_id}
    jobs = set()
    current = contract
    while current.supersedes is not None:
        previous = FidelityCampaignDelegationV01.model_validate_json(
            _read(_workspace(), current.supersedes)
        )
        if previous.delegation_id in seen:
            raise ValueError("delegation predecessor chain repeats an identity")
        seen.add(previous.delegation_id)
        parent, ref, decision = _load(previous.delegation_id, active=False)
        if ref != current.supersedes or {a.reference.sha256 for a in parent.assets} != {
            a.reference.sha256 for a in current.assets
        }:
            raise ValueError("successor must preserve its exact predecessor references")
        scopes = _scopes(parent, ref, decision)
        prior = parent.prior_delegated_reservations.plus(
            scopes[-1].reserved_after if scopes else DelegationCost()
        )
        if current.prior_delegated_reservations != prior:
            raise ValueError("successor mandate cannot reset previously reserved capacity")
        closed = []
        for scope in scopes:
            if scope.job_id in jobs:
                raise ValueError("delegation predecessor chain repeats a job")
            jobs.add(scope.job_id)
            outcome = _outcome(scope)
            if outcome is None:
                if (_workspace() / scope.job_id).exists():
                    raise PermissionError(
                        "active delegated sessions must close with an exact outcome "
                        "before a new mandate"
                    )
                # A never-admitted reservation keeps its cost but supplies no observation.
                continue
            closed.append(scope)
        groups.append(closed)
        current = parent
    return [scope for group in reversed(groups) for scope in group]


def plan_fidelity_delegation(proposal: FidelityCampaignDelegationV01) -> dict[str, object]:
    """Publish a concrete mandate for one exact user decision; planning grants no authority."""
    contract = FidelityCampaignDelegationV01.model_validate_json(proposal.model_dump_json())
    _validate_source(contract)
    for asset in contract.assets:
        _validate_asset_evidence(asset)
    _history(contract, [])
    _validate_predecessor(contract)
    if contract.expires_at <= datetime.now(UTC):
        raise PermissionError("delegation expiry is already past")
    with _guard():
        artifact = _publish(
            _directory(contract.delegation_id) / "contract.json", contract, "fidelity_delegation"
        )
    return {
        "contract": contract.model_dump(mode="json"),
        "artifact": artifact.model_dump(mode="json"),
        "approved": False,
    }


def _load(delegation_id: str, *, active: bool = True):
    """Load exact parent authority; historical status may be read after expiry without execution."""
    directory = _directory(delegation_id)
    artifact = exact_artifact(_workspace(), directory / "contract.json", "fidelity_delegation")
    contract = FidelityCampaignDelegationV01.model_validate_json(_read(_workspace(), artifact))
    if contract.delegation_id != delegation_id:
        raise ValueError("delegation identity changed")
    decision_ref = exact_artifact(_workspace(), directory / "decision.json", "delegation_decision")
    decision = DelegationDecisionV01.model_validate_json(_read(_workspace(), decision_ref))
    if decision.contract != artifact or artifact.sha256 not in decision.exact_user_text:
        raise PermissionError("delegation lacks the exact mandate decision")
    if active:
        if contract.expires_at <= datetime.now(UTC):
            raise PermissionError("delegation expired; no new authority is available")
        _validate_source(contract)
        for asset in contract.assets:
            _validate_asset_evidence(asset)
            claims = _governing_contracts(asset.reference.sha256)
            if claims != [(contract.delegation_id, artifact.sha256)]:
                raise PermissionError("delegation has been superseded; no new policy authority")
    return contract, artifact, decision_ref


def approve_fidelity_delegation(
    delegation_id: str, *, contract_sha256: str, exact_user_text: str
) -> dict[str, object]:
    """Record the one explicit contract confirmation without approving any future artifact."""
    with _guard():
        directory = _directory(delegation_id)
        artifact = exact_artifact(_workspace(), directory / "contract.json", "fidelity_delegation")
        contract = FidelityCampaignDelegationV01.model_validate_json(_read(_workspace(), artifact))
        if contract_sha256 != artifact.sha256 or contract_sha256 not in exact_user_text:
            raise PermissionError("exact delegation SHA-256 must occur in the user's decision")
        if (directory / "decision.json").exists():
            _load(delegation_id)
            return get_fidelity_delegation_status(delegation_id)
        _validate_source(contract)
        _history(contract, [])
        _validate_predecessor(contract)
        if contract.expires_at <= datetime.now(UTC):
            raise PermissionError("delegation expired")
        for asset in contract.assets:
            _validate_asset_evidence(asset)
            claims = _governing_contracts(asset.reference.sha256)
            expected = []
            if contract.supersedes is not None:
                old = FidelityCampaignDelegationV01.model_validate_json(
                    _read(_workspace(), contract.supersedes)
                )
                expected = [(old.delegation_id, contract.supersedes.sha256)]
            if claims != expected:
                raise PermissionError("new mandate must name the current exact predecessor")
        decision = DelegationDecisionV01(
            contract=artifact, exact_user_text=exact_user_text, created_at=datetime.now(UTC)
        )
        _publish(directory / "decision.json", decision, "delegation_decision")
    return get_fidelity_delegation_status(delegation_id)


def _scopes(
    contract: FidelityCampaignDelegationV01,
    artifact: ActivationArtifact,
    decision: ActivationArtifact,
) -> list[DelegationScopeV01]:
    """Replay reserved slots and hash links; reject skipped slots, duplicate jobs and resets."""
    result = []
    previous = None
    total = DelegationCost()
    counts = dict.fromkeys((a.asset_id for a in contract.assets), 0)
    assets = {a.asset_id: a for a in contract.assets}
    for index, path in enumerate(
        sorted((_directory(contract.delegation_id) / "scopes").glob("*.json")), 1
    ):
        scope_ref = exact_artifact(_workspace(), path, "delegation_scope")
        scope = DelegationScopeV01.model_validate_json(_read(_workspace(), scope_ref))
        if (
            path.stem != f"{index:04d}"
            or scope.sequence != index
            or scope.previous != previous
            or scope.contract != artifact
            or scope.decision != decision
            or scope.asset_id not in assets
            or scope.reserved_before != total
        ):
            raise ValueError("delegation scope chain is stale, mixed or incomplete")
        asset = assets[scope.asset_id]
        slot_index = counts[scope.asset_id]
        if scope.slot_index != slot_index or slot_index >= len(asset.slots):
            raise PermissionError("delegation candidate slot exhausted or duplicated")
        if scope.job_id in {item.job_id for item in result}:
            raise ValueError("delegation cannot admit a job twice")
        expected = asset.slots[slot_index].funding(
            scope.job_id,
            f"{contract.delegation_id}-{index}",
            asset.reference.sha256,
            scope.funding.prior_history,
        )
        total = total.plus(asset.slots[slot_index].cost())
        if scope.funding != expected or scope.reserved_after != total:
            raise ValueError("delegation scope price differs from approved capacity")
        if int(scope.strategy_switch_reserved_on_entry) > asset.slots[slot_index].strategy_switches:
            raise ValueError("entry strategy change has no reserved capacity")
        if any(
            getattr(total, key) > value for key, value in contract.total_budget.model_dump().items()
        ):
            raise PermissionError("delegation aggregate budget exhausted")
        counts[scope.asset_id] += 1
        result.append(scope)
        previous = scope_ref
    return result


def assert_reference_delegation(
    reference_sha256: str, binding: DelegationBindingV01 | None
) -> None:
    """Reject unbound renamed plans for delegated references, including exhausted mandates."""
    matches = _governing_contracts(reference_sha256)
    if matches and (
        binding is None or matches != [(binding.delegation_id, binding.contract_sha256)]
    ):
        raise PermissionError(
            "reference is governed by an exact campaign delegation; no unbound reset"
        )


def _governing_contracts(reference_sha256: str) -> list[tuple[str, str]]:
    """Find approved leaf mandates by exact predecessor hashes, retaining closed parent history."""
    matches = []
    superseded = set()
    for path in sorted((_workspace() / ".fidelity_delegations").glob("*/decision.json")):
        contract, artifact, _decision = _load(path.parent.name, active=False)
        if reference_sha256 in {item.reference.sha256 for item in contract.assets}:
            matches.append((contract.delegation_id, artifact.sha256))
            if contract.supersedes is not None:
                _read(_workspace(), contract.supersedes)
                superseded.add(contract.supersedes.sha256)
    return [item for item in matches if item[1] not in superseded]


def _scope_binding(scope: DelegationScopeV01) -> DelegationBindingV01:
    """Derive the native binding from the persisted reservation, never caller counters."""
    contract = FidelityCampaignDelegationV01.model_validate_json(
        _read(_workspace(), scope.contract)
    )
    ref = exact_artifact(
        _workspace(),
        _directory(contract.delegation_id) / "scopes" / f"{scope.sequence:04d}.json",
        "delegation_scope",
    )
    return DelegationBindingV01(
        delegation_id=contract.delegation_id,
        scope_sequence=scope.sequence,
        contract_sha256=scope.contract.sha256,
        scope_sha256=ref.sha256,
    )


def _bound_scope(binding: DelegationBindingV01, *, active: bool = True):
    """Validate parent authority, ancestry and allocations before using an active child scope."""
    contract, artifact, decision = _load(binding.delegation_id, active=active)
    scopes = _scopes(contract, artifact, decision)
    if binding.scope_sequence > len(scopes) or artifact.sha256 != binding.contract_sha256:
        raise ValueError("delegation binding differs from its parent reservation")
    scope = scopes[binding.scope_sequence - 1]
    if _scope_binding(scope) != binding:
        raise ValueError("delegation scope hash changed")
    if active:
        _predecessor_scopes(contract)
        _history(contract, scopes)
    asset = next(a for a in contract.assets if a.asset_id == scope.asset_id)
    return contract, asset, scope, scopes


def _outcome(scope: DelegationScopeV01) -> DelegationOutcomeV01 | None:
    """Read and rehash a completed scope without allowing summary flags to confer success."""
    binding = _scope_binding(scope)
    path = _directory(binding.delegation_id) / "outcomes" / f"{scope.sequence:04d}.json"
    if not path.exists():
        return None
    result = DelegationOutcomeV01.model_validate_json(path.read_bytes())
    ref = exact_artifact(
        _workspace(),
        _directory(binding.delegation_id) / "scopes" / f"{scope.sequence:04d}.json",
        "delegation_scope",
    )
    if result.scope != ref:
        raise ValueError("delegation outcome belongs to another scope")
    for item in [result.terminal_state, *result.evidence]:
        _read(_workspace(), item)
    expected = _derive_outcome(scope, result.session_id, result.created_at)
    if result != expected:
        raise ValueError("delegation outcome differs from host-recomputed terminal evidence")
    return result


def issue_fidelity_scope(
    delegation_id: str, *, asset_id: str, job_id: str, strategy: str
) -> dict[str, object]:
    """Reserve a bounded successor while retaining reference strategy history across parents."""
    with _guard():
        contract, artifact, decision = _load(delegation_id)
        scopes = _scopes(contract, artifact, decision)
        _history(contract, scopes)
        predecessors = _predecessor_scopes(contract)
        for item in scopes:
            if item.job_id == job_id:
                if (item.asset_id, item.strategy) != (asset_id, strategy):
                    raise ValueError("existing scope cannot change its candidate identity")
                return {
                    "scope": item.model_dump(mode="json"),
                    "binding": _scope_binding(item).model_dump(mode="json"),
                }
        outcomes = [(item, _outcome(item)) for item in scopes]
        if any(result is None for _item, result in outcomes):
            raise PermissionError("previous reservation needs exact closure before a successor")
        completed = {
            item.asset_id
            for item, result in outcomes
            if result.technical_passed and result.visual_passed
        }
        next_asset = next((a for a in contract.assets if a.asset_id not in completed), None)
        if next_asset is None or next_asset.asset_id != asset_id:
            raise PermissionError("canary/ordered asset gate forbids this successor")
        prior_scopes = [item for item in scopes if item.asset_id == asset_id]
        slot_index = len(prior_scopes)
        if slot_index >= len(next_asset.slots):
            raise PermissionError("finite candidate budget exhausted; preserve best-known result")
        entry_switch = False
        strategy_scopes = [
            item for item in predecessors
            if item.funding.reference_sha256 == next_asset.reference.sha256
        ] + prior_scopes
        if strategy_scopes:
            entry_switch = _require_successor_strategy(
                strategy_scopes,
                strategy,
                next_asset,
                slot_index,
            )
        if (_workspace() / job_id).exists():
            raise PermissionError("delegation requires a fresh job; historical jobs stay immutable")
        sequence = len(scopes) + 1
        before = scopes[-1].reserved_after if scopes else DelegationCost()
        slot = next_asset.slots[slot_index]
        previous = (
            exact_artifact(
                _workspace(),
                _directory(delegation_id) / "scopes" / f"{sequence - 1:04d}.json",
                "delegation_scope",
            )
            if scopes
            else None
        )
        scope = DelegationScopeV01(
            contract=artifact,
            decision=decision,
            sequence=sequence,
            previous=previous,
            asset_id=asset_id,
            slot_index=slot_index,
            job_id=job_id,
            strategy=strategy,
            strategy_switch_reserved_on_entry=entry_switch,
            funding=slot.funding(
                job_id,
                f"{delegation_id}-{sequence}",
                next_asset.reference.sha256,
                read_fidelity_history(next_asset.reference.sha256),
            ),
            reserved_before=before,
            reserved_after=before.plus(slot.cost()),
            created_at=datetime.now(UTC),
        )
        _publish(
            _directory(delegation_id) / "scopes" / f"{sequence:04d}.json", scope, "delegation_scope"
        )
        return {
            "scope": scope.model_dump(mode="json"),
            "binding": _scope_binding(scope).model_dump(mode="json"),
        }


def _preparations(binding: DelegationBindingV01) -> list[DelegationPreparationV01]:
    """Replay all published data versions with exact hashes and contiguous repair counts."""
    _contract, asset, scope, _scopes_list = _bound_scope(binding)
    directory = _directory(binding.delegation_id)
    scope_ref = exact_artifact(
        _workspace(), directory / "scopes" / f"{scope.sequence:04d}.json", "delegation_scope"
    )
    result = []
    previous = None
    for index, path in enumerate(
        sorted((directory / "preparations" / f"{scope.sequence:04d}").glob("*.json"))
    ):
        current = DelegationPreparationV01.model_validate_json(path.read_bytes())
        if (
            path.stem != f"{index:04d}"
            or current.sequence != index
            or current.previous != previous
            or current.scope != scope_ref
        ):
            raise ValueError("delegation preparation history changed")
        if index > asset.slots[scope.slot_index].preparation_repairs:
            raise PermissionError("delegation preparation repair allowance exhausted")
        for item in current.artifacts:
            _read(_workspace(), item)
        result.append(current)
        previous = exact_artifact(_workspace(), path, "delegation_preparation")
    return result


def publish_fidelity_preparation(
    binding: DelegationBindingV01, paths: list[Path]
) -> dict[str, object]:
    """Publish one bounded data-only candidate set or repair before native session admission."""
    with _guard():
        _contract, asset, scope, _scopes_list = _bound_scope(binding)
        directory = _directory(binding.delegation_id)
        if list((_workspace() / scope.job_id / "production/autonomy_v2").glob("*/budget.json")):
            raise PermissionError("admitted preparation is frozen; use native guarded corrections")
        prior = _preparations(binding)
        if len(prior) > asset.slots[scope.slot_index].preparation_repairs:
            raise PermissionError("delegation preparation repair allowance exhausted")
        staging = directory / "staging" / f"{scope.sequence:04d}" / f"{len(prior):04d}"
        artifacts = []
        for path in paths:
            safe = ensure_contained_production_path(staging, path, must_exist=True)
            if safe.suffix.lower() not in {".json", ".png"}:
                raise PermissionError("delegated preparation publishes only JSON or PNG data")
            artifacts.append(exact_artifact(_workspace(), safe, "candidate_data"))
        if len({item.path for item in artifacts}) != len(artifacts):
            raise ValueError("preparation repeats a data artifact")
        previous = (
            exact_artifact(
                _workspace(),
                directory / "preparations" / f"{scope.sequence:04d}" / f"{len(prior) - 1:04d}.json",
                "delegation_preparation",
            )
            if prior
            else None
        )
        result = DelegationPreparationV01(
            scope=exact_artifact(
                _workspace(),
                directory / "scopes" / f"{scope.sequence:04d}.json",
                "delegation_scope",
            ),
            sequence=len(prior),
            previous=previous,
            artifacts=artifacts,
            created_at=datetime.now(UTC),
        )
        ref = _publish(
            directory / "preparations" / f"{scope.sequence:04d}" / f"{len(prior):04d}.json",
            result,
            "delegation_preparation",
        )
    return {"preparation": result.model_dump(mode="json"), "artifact": ref.model_dump(mode="json")}


@contextmanager
def delegated_admission(
    binding: DelegationBindingV01 | None,
    *,
    reference_path: Path,
    job_id: str | None,
    funding,
    request: str,
    target_subject: str,
    delivery_profiles: list[str],
    destination_hint: str,
) -> Iterator[None]:
    """Authorize native planning once; an interrupted admission cannot mint another session."""
    if binding is None and not (_workspace() / ".fidelity_delegations").exists():
        yield
        return
    with _guard():
        assert_reference_delegation(sha256_file(reference_path), binding)
        if binding is not None:
            contract, asset, scope, _all_scopes = _bound_scope(binding)
            if (
                job_id != scope.job_id
                or funding != scope.funding
                or sha256_file(reference_path) != asset.reference.sha256
                or request != contract.user_request
                or target_subject != asset.target_subject
                or delivery_profiles != [contract.delivery_profile]
                or destination_hint != "engine_neutral"
            ):
                raise PermissionError("native plan differs from the delegated scope")
            if not _preparations(binding):
                raise PermissionError(
                    "delegated candidate needs its preserved preparation data first"
                )
            if (_workspace() / scope.job_id).exists():
                raise PermissionError(
                    "delegated admission already started; resume the same session"
                )
        yield


def validate_delegated_budget(root: Path, budget, *, loop=None, hypothesis=None) -> None:
    """Recheck native resource, criteria, source and policy authority before delegated effects."""
    from .models import AutonomyBudgetV04

    if not isinstance(budget, AutonomyBudgetV04):
        return
    contract, asset, scope, _all_scopes = _bound_scope(budget.delegation)
    if (
        budget.job_id != scope.job_id
        or budget.funding != scope.funding
        or budget.delivery_runs != 1
    ):
        raise ValueError("native budget differs from its delegated reservation")
    if root.resolve() != (_workspace() / scope.job_id).resolve():
        raise ValueError("delegated budget belongs to another workspace")
    _preparations(budget.delegation)
    if loop is not None:
        expected = _validate_asset_evidence(asset)
        if (
            getattr(loop, "comparison_lighting_profile", None) != asset.comparison_lighting_profile
            or hypothesis.requirements != expected.requirements
            or hypothesis.observations != expected.observations
            or hypothesis.camera != expected.camera
            or hypothesis.authoring_strategy != scope.strategy
        ):
            raise PermissionError(
                "delegated loop changed frozen observations, camera or initial strategy"
            )
    # The parent grants autonomous local policy only; it grants no external provider or user gate.
    envelope_path = (
        root / "production/autonomy_v2" / budget.session_id / "approval_envelope/envelope.json"
    )
    if envelope_path.exists():
        from .approval_models import AutonomyApprovalEnvelope

        envelope = AutonomyApprovalEnvelope.model_validate_json(envelope_path.read_bytes())
        if (
            envelope.approval_mode != contract.approval_mode
            or envelope.allowed_provider_scopes != [contract.provider]
            or envelope.max_identity_splits != contract.extra_identity_split_operations
        ):
            raise PermissionError("delegated envelope expanded policy/provider authority")


def validate_delegated_strategy(
    budget, attempts: list, *, strategy: str, reserved_switches: int
) -> None:
    """Prevent cross-session plateau and strategy limits from resetting with a new candidate."""
    from .models import AutonomyBudgetV04
    from .quality_revision_budget import require_strategy_change

    if not isinstance(budget, AutonomyBudgetV04):
        return
    _contract, asset, scope, _all = _bound_scope(budget.delegation)
    cap = asset.slots[scope.slot_index].strategy_switches
    if reserved_switches + int(scope.strategy_switch_reserved_on_entry) > cap:
        raise PermissionError("delegated strategy switch budget exhausted")
    history = delegated_attempt_history(budget, attempts)
    if require_strategy_change(history) and strategy == history[-1].strategy:
        raise PermissionError("same defect stagnated twice; a funded strategy switch is required")


def _verified_scope_attempts(scope: DelegationScopeV01) -> list:
    """Recover a closed predecessor's exact attempts without trusting caller plateau counters."""
    from .quality_revision_service import _attempts, load_optional_loop

    outcome = _outcome(scope)
    if outcome is None:
        raise PermissionError("predecessor attempts require an exact closed scope")
    root = _workspace() / scope.job_id
    binding = load_optional_loop(root, outcome.session_id)
    return [item[0] for item in _attempts(root, outcome.session_id, binding[1])] if binding else []


def delegated_attempt_history(budget, attempts: list) -> list:
    """Join exact same-reference attempts across sessions and superseded parent mandates."""
    from .models import AutonomyBudgetV04

    if not isinstance(budget, AutonomyBudgetV04):
        return attempts
    contract, asset, scope, scopes = _bound_scope(budget.delegation, active=False)
    history = []
    previous_scopes = _predecessor_scopes(contract) + [
        previous for previous in scopes if previous.sequence < scope.sequence
    ]
    for previous in previous_scopes:
        if previous.funding.reference_sha256 == asset.reference.sha256:
            history.extend(_verified_scope_attempts(previous))
    return [*history, *attempts]


def delegated_switch_offset(budget) -> int:
    """Narrow the native one-switch route selector without modifying historical loop schemas."""
    from .models import AutonomyBudgetV04

    if not isinstance(budget, AutonomyBudgetV04):
        return 0
    _contract, asset, scope, _scopes_list = _bound_scope(budget.delegation, active=False)
    return (
        1
        - asset.slots[scope.slot_index].strategy_switches
        + int(scope.strategy_switch_reserved_on_entry)
    )


def _require_successor_strategy(
    scopes: list[DelegationScopeV01], strategy: str, asset: DelegationAsset, slot_index: int
) -> bool:
    """Charge strategy changes and reject inherited plateau, including a parent's first slot."""
    from .quality_revision_budget import require_strategy_change

    attempts = []
    for item in scopes:
        attempts.extend(_verified_scope_attempts(item))
    last_strategy = attempts[-1].strategy if attempts else scopes[-1].strategy
    changed = strategy != last_strategy
    if require_strategy_change(attempts) and not changed:
        raise PermissionError("successor cannot repeat the same stagnated defect strategy")
    if changed and asset.slots[slot_index].strategy_switches == 0:
        raise PermissionError("successor strategy switch has no delegated reserve")
    return changed


def _derive_outcome(
    scope: DelegationScopeV01, session_id: str, created_at: datetime
) -> DelegationOutcomeV01:
    """Recompute technical delivery and paired fidelity separately from human disposition."""
    from .controller_bridge import _session_bundle
    from .delivery_service import validate_delivery_terminal_v2
    from .models import AutonomyBudgetV04
    from .quality_revision_service import _attempts, _quality_submission_report, load_optional_loop

    root, _session, _plan, budget, state, state_ref = _session_bundle(scope.job_id, session_id)
    if not isinstance(budget, AutonomyBudgetV04) or budget.delegation != _scope_binding(scope):
        raise ValueError("delegation outcome is not from its admitted session")
    if state.next_action != "none":
        raise PermissionError("delegation successor requires a normal immutable terminal first")
    technical = False
    if state.status == "completed" and state.delivery_terminal is not None:
        terminal = validate_delivery_terminal_v2(root, state.delivery_terminal)
        technical = bool(terminal.results) and all(
            result.profile_id == "portable_gltf" and result.status == "completed"
            for result in terminal.results
        )
    evidence = []
    remaining = []
    visual = False
    loop = load_optional_loop(root, session_id)
    attempts = _attempts(root, session_id, loop[1]) if loop else []
    if attempts:
        attempt = attempts[-1][0]
        evaluation = FidelityEvaluationV01.model_validate_json(
            (root / attempt.fidelity_evaluation.path).read_bytes()
        )
        _contract, asset, _scope, _all = _bound_scope(budget.delegation, active=False)
        iq = _quality_submission_report(root, attempt.quality_submission)
        from ..reference_fidelity.service import read_artifact, validate_review_evidence

        review = VisualFindingSetV01.model_validate_json(read_artifact(root, attempt.visual_review))
        hypothesis = ModelingHypothesisV01.model_validate_json(
            read_artifact(root, loop[0].hypothesis)
        )
        qa = validate_review_evidence(root, hypothesis, review)
        floors_passed = (
            iq.contour.status == "scored"
            and iq.contour.boundary_f_score is not None
            and iq.contour.boundary_f_score >= asset.minimum_boundary_f_score
            and qa.direct_metrics.overall_direct_score >= asset.minimum_direct_score
            and qa.direct_metrics.silhouette_iou >= asset.minimum_silhouette_iou
        )
        remaining = list(attempt.unresolved_features)
        evidence.append(
            exact_artifact(
                _workspace(), root / attempt.fidelity_evaluation.path, "fidelity_evaluation"
            )
        )
        if attempt.paired_comparison is not None:
            comparison = _validate_comparison(root, attempt.paired_comparison)
            if comparison.after != attempt.fidelity_evaluation:
                raise ValueError("paired improvement describes another final candidate")
            evidence.append(
                exact_artifact(
                    _workspace(), root / attempt.paired_comparison.path, "fidelity_comparison"
                )
            )
            visual = (
                floors_passed
                and evaluation.outcome == "visually_satisfied"
                and evaluation.required_features == evaluation.satisfied_features
                and not remaining
                and comparison.outcome == "improved"
                and not comparison.unresolved_major_features
                and not comparison.regressed_features
            )
    if state.delivery_terminal is not None:
        evidence.append(
            exact_artifact(_workspace(), root / state.delivery_terminal.path, "delivery_terminal")
        )
    binding = _scope_binding(scope)
    return DelegationOutcomeV01(
        scope=exact_artifact(
            _workspace(),
            _directory(binding.delegation_id) / "scopes" / f"{scope.sequence:04d}.json",
            "delegation_scope",
        ),
        session_id=session_id,
        terminal_state=exact_artifact(_workspace(), root / state_ref.path, "terminal_state"),
        technical_passed=technical,
        visual_passed=visual,
        evidence=evidence,
        remaining_findings=remaining,
        created_at=created_at,
    )


def _validate_comparison(root: Path, artifact) -> FidelityComparisonV01:
    """Recompute a paired result from both actual render sets, never trust a summary flag."""
    from ..reference_fidelity.service import (
        _comparison_conditions,
        compare_evaluations,
        evaluate_review,
        read_artifact,
        validate_review_evidence,
    )

    comparison = FidelityComparisonV01.model_validate_json(read_artifact(root, artifact))
    evaluations, reviews = [], []
    for ref in (comparison.before, comparison.after):
        evaluation = FidelityEvaluationV01.model_validate_json(read_artifact(root, ref))
        review = VisualFindingSetV01.model_validate_json(
            read_artifact(root, evaluation.visual_review)
        )
        hypothesis = ModelingHypothesisV01.model_validate_json(
            read_artifact(root, evaluation.hypothesis)
        )
        qa = validate_review_evidence(root, hypothesis, review)
        if evaluation != evaluate_review(
            hypothesis,
            review,
            review_artifact=evaluation.visual_review,
            legacy_direct_score=qa.direct_metrics.overall_direct_score,
        ):
            raise ValueError("delegated comparison evaluation differs from actual evidence")
        evaluations.append(evaluation)
        reviews.append(review)
    if _comparison_conditions(root, reviews[0]) != _comparison_conditions(root, reviews[1]):
        raise ValueError("delegated paired comparison changed render conditions")
    expected = compare_evaluations(
        *evaluations,
        before_artifact=comparison.before,
        after_artifact=comparison.after,
        before_review=reviews[0],
        after_review=reviews[1],
    )
    if comparison != expected:
        raise ValueError("delegated paired comparison is not host-reproducible")
    return comparison


def close_fidelity_scope(binding: DelegationBindingV01, *, session_id: str) -> dict[str, object]:
    """Publish technical and visual closeout evidence without human or Activation acceptance."""
    with _guard():
        _contract, _asset, scope, _scopes_list = _bound_scope(binding)
        path = _directory(binding.delegation_id) / "outcomes" / f"{scope.sequence:04d}.json"
        existing = _outcome(scope)
        if existing is not None:
            if existing.session_id != session_id:
                raise ValueError("scope already closed by another session")
            result = existing
        else:
            result = _derive_outcome(scope, session_id, datetime.now(UTC))
            _publish(path, result, "delegation_outcome")
    return result.model_dump(mode="json")


def get_fidelity_delegation_status(delegation_id: str) -> dict[str, object]:
    """Report reserved capacity and separate outcomes read-only, including expired mandates."""
    contract, artifact, decision = _load(delegation_id, active=False)
    scopes = _scopes(contract, artifact, decision)
    outcomes = [_outcome(item) for item in scopes]
    return {
        "contract": artifact.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json"),
        "expired": contract.expires_at <= datetime.now(UTC),
        "total_budget": contract.total_budget.model_dump(),
        "prior_delegated_reservations": contract.prior_delegated_reservations.model_dump(),
        "reserved": (scopes[-1].reserved_after if scopes else DelegationCost()).model_dump(),
        "scopes": [item.model_dump(mode="json") for item in scopes],
        "outcomes": [item.model_dump(mode="json") if item else None for item in outcomes],
        "human_beauty_accepted": 0,
        "human_package_accepted": 0,
        "human_activation_accepted": False,
    }


def start_fidelity_scope(binding: DelegationBindingV01) -> dict[str, object]:
    """Start one funded skill session or expose its exact state after interruption."""
    from ..skill_orchestration.service import plan_aq_one_prompt_skill
    from .controller_bridge import get_autonomy_v2_status
    from .models import AutonomyBudgetV04, parse_autonomy_budget

    contract, asset, scope, _scopes_list = _bound_scope(binding)
    roots = sorted((_workspace() / scope.job_id / "production/autonomy_v2").glob("*/budget.json"))
    if roots:
        if len(roots) != 1:
            raise ValueError("delegated scope contains multiple session budgets")
        budget = parse_autonomy_budget(roots[0].read_bytes())
        if not isinstance(budget, AutonomyBudgetV04) or budget.delegation != binding:
            raise ValueError("interrupted session has a different campaign binding")
        result = get_autonomy_v2_status(scope.job_id, budget.session_id)
        return {
            "status": "existing_session",
            "job_id": scope.job_id,
            "session_id": budget.session_id,
            "session": result,
            "new_reservation": False,
        }
    return plan_aq_one_prompt_skill(
        contract.user_request,
        reference_path=get_settings().repo_root / asset.reference.path,
        target_subject=asset.target_subject,
        requested_delivery_profiles=[contract.delivery_profile],
        job_id=scope.job_id,
        approval_mode="autonomous",
        allowed_provider_scopes=["local_only"],
        explicit_autonomy_delegation_observed=True,
        experimental_opt_in=True,
        fidelity_budget_plan=scope.funding,
        delegation_binding=binding,
    )


def fidelity_scope_binding(delegation_id: str, sequence: int) -> DelegationBindingV01:
    """Resolve a persisted child scope; callers cannot supply substitute costs or authority."""
    contract, artifact, decision = _load(delegation_id)
    scopes = _scopes(contract, artifact, decision)
    if not 1 <= sequence <= len(scopes):
        raise ValueError("unknown delegation scope sequence")
    return _scope_binding(scopes[sequence - 1])
