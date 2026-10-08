"""Explicit Standard workflow adapter for optional delegated technical authority."""

from __future__ import annotations

from pathlib import Path

from ..workspace import job_dir, sha256_file
from .delegated import (
    AUTHORIZATION_FILE,
    CONSUMPTION_FILE,
    _artifact,
    _host_lock,
    _read_exact,
    _require_opt_in,
    _safe_path,
    _write_contract_once,
    _write_once,
    validate_delegated_optimization_authorization,
)
from .delegated_models import DelegatedOptimizationWorkflowBindingV01
from .io import load_model, run_directory, utc_now, validate_filesystem_id
from .models import OptimizationPlan

BINDING_FILE = "delegated_optimization_binding.json"
RUN_BINDING_FILE = "optimization_delegated_workflow_binding.json"


def load_delegated_workflow_binding(
    root: Path,
    workflow_root: Path,
    *,
    expected_input_fingerprint: str | None = None,
) -> DelegatedOptimizationWorkflowBindingV01 | None:
    """Load only an explicitly issued binding and revalidate its exact non-user authority."""

    from ..orchestration.models import WorkflowPlan, WorkflowRequest

    path = _safe_path(root, workflow_root / BINDING_FILE)
    if not path.exists():
        return None
    binding = load_model(path, DelegatedOptimizationWorkflowBindingV01)
    plan_path = _read_exact(root, binding.workflow_plan)
    plan = load_model(plan_path, WorkflowPlan)
    request_path = _safe_path(root, workflow_root / "request.json")
    request = load_model(request_path, WorkflowRequest)
    if (
        binding.job_id != root.name
        or binding.workflow_id != workflow_root.name
        or plan_path != workflow_root / "plan.json"
        or plan.job_id != binding.job_id
        or plan.workflow_id != binding.workflow_id
        or request.execution_policy != "standard"
        or request.workflow_id != plan.workflow_id
        or request.job_id != plan.job_id
        or sha256_file(request_path) != plan.request_sha256
        or (
            expected_input_fingerprint is not None
            and expected_input_fingerprint != binding.workflow_input_fingerprint
        )
    ):
        raise ValueError("delegated workflow binding is stale or foreign")
    gates = [step for step in plan.steps if step.approval_gate == "optimization_plan"]
    if (
        len(gates) != 1
        or gates[0].step_id != "portable.plan_approval"
        or gates[0].parameters.get("run_id") != binding.run_id
        or gates[0].parameters.get("profile_id") != "portable_gltf"
    ):
        raise ValueError("delegated binding does not match the exact Standard optimization gate")
    policy = _safe_path(
        root, workflow_root / "policy_authorizations" / "portable.plan_approval.json"
    )
    if policy.exists():
        raise ValueError("workflow mixes delegated and AQ policy authority")
    grant_path = _read_exact(root, binding.authorization)
    run_root = _safe_path(root, run_directory(root, binding.run_id))
    if grant_path != run_root / AUTHORIZATION_FILE:
        raise ValueError("delegated workflow grant points outside the exact run")
    snapshot = _safe_path(root, run_root / RUN_BINDING_FILE)
    if snapshot.read_bytes() != path.read_bytes():
        raise ValueError("delegated workflow binding snapshot changed")
    for name in ("plan", "request"):
        retained = _safe_path(root, run_root / f"optimization_delegated_workflow_{name}.json")
        if retained.read_bytes() != (workflow_root / f"{name}.json").read_bytes():
            raise ValueError("delegated workflow retained snapshot changed")
    optimization = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    validate_delegated_optimization_authorization(
        root,
        run_root,
        optimization,
        require_consumed=(run_root / CONSUMPTION_FILE).exists(),
        expected_authorization_sha256=binding.authorization.sha256,
    )
    return binding


def bind_delegated_optimization_workflow(
    job_id: str,
    *,
    workflow_id: str,
    workflow_plan_sha256: str,
    workflow_input_fingerprint: str,
    run_id: str,
    authorization_sha256: str,
    enable_delegated_authority: bool = False,
) -> DelegatedOptimizationWorkflowBindingV01:
    """Opt in one currently waiting Standard gate without editing its immutable plan."""

    from ..orchestration.service import _load_workflow, _reconcile_locked

    _require_opt_in(enable_delegated_authority)
    validate_filesystem_id(workflow_id, "workflow_id")
    root = job_dir(job_id)
    workflow_root = _safe_path(root, root / "workflows" / workflow_id)
    run_root = _safe_path(root, run_directory(root, run_id))
    with _host_lock(root, job_id, workflow_id):
        _root, _workflow_root, request, plan, previous = _load_workflow(job_id, workflow_id)
        if (
            request.execution_policy != "standard"
            or sha256_file(workflow_root / "plan.json") != workflow_plan_sha256
            or (previous is not None and previous.status in {"cancelled", "complete", "failed"})
        ):
            raise ValueError("delegated binding requires a current unchanged Standard workflow")
        state = _reconcile_locked(root, workflow_root, plan, request, previous=previous)
        gate = next(
            (step for step in state.steps if step.step_id == "portable.plan_approval"), None
        )
        planned_gate = next(
            (step for step in plan.steps if step.step_id == "portable.plan_approval"), None
        )
        if (
            gate is None
            or planned_gate is None
            or gate.status != "waiting_for_approval"
            or gate.input_fingerprint != workflow_input_fingerprint
            or planned_gate.parameters.get("run_id") != run_id
        ):
            raise ValueError(
                "delegated binding requires the exact currently waiting optimization gate"
            )
        optimization = load_model(run_root / "optimization_plan.json", OptimizationPlan)
        grant = validate_delegated_optimization_authorization(
            root,
            run_root,
            optimization,
            require_consumed=False,
            expected_authorization_sha256=authorization_sha256,
        )
        binding = DelegatedOptimizationWorkflowBindingV01(
            job_id=job_id,
            workflow_id=workflow_id,
            run_id=run_id,
            workflow_plan=_artifact(root, workflow_root / "plan.json", f"workflow.{workflow_id}"),
            workflow_input_fingerprint=workflow_input_fingerprint,
            authorization=_artifact(root, run_root / AUTHORIZATION_FILE, grant.authorization_id),
            created_at=utc_now(),
        )
        target = _safe_path(root, workflow_root / BINDING_FILE)
        snapshot = _safe_path(root, run_root / RUN_BINDING_FILE)
        if target.exists() or snapshot.exists():
            raise FileExistsError("delegated workflow binding already exists")
        _write_once(
            run_root / "optimization_delegated_workflow_plan.json",
            (workflow_root / "plan.json").read_bytes(),
        )
        _write_once(
            run_root / "optimization_delegated_workflow_request.json",
            (workflow_root / "request.json").read_bytes(),
        )
        _write_contract_once(target, binding)
        _write_once(snapshot, target.read_bytes())
        load_delegated_workflow_binding(
            root, workflow_root, expected_input_fingerprint=workflow_input_fingerprint
        )
    return binding
