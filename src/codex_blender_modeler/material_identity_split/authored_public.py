"""Explicit public adapters for the 0.2 authored-material authority domains."""

from __future__ import annotations

import json

from .. import authored_split_runtime as runtime
from ..workspace import job_dir
from .authored_models import (
    AuthoredMaterialIdentitySplitApplyIntentV02,
    AuthoredMaterialIdentitySplitApprovalV02,
    AuthoredMaterialIdentitySplitTechnicalApplyIntentV02,
    AuthoredMaterialIdentitySplitTechnicalApprovalV02,
)
from .authored_service import (
    prepare_authored_material_identity_split,
    publish_authored_material_identity_split_approval,
    publish_authored_material_identity_split_technical_approval,
    run_authored_material_identity_split_preapproval,
)
from .authored_transaction import (
    apply_authored_material_identity_split,
    recover_authored_material_identity_split,
)


def plan_authored_material_identity_split_public(
    job_id: str,
    *,
    run_id: str,
    clone_rules_path: str,
    source_material_plan_mode: str = "current",
    delegation_path: str | None = None,
) -> dict:
    """Read exact caller clone rules and prepare only the explicitly selected authored profile."""
    root = job_dir(job_id).resolve(strict=True)
    rules = json.loads(runtime.read(root, runtime.reference(root, clone_rules_path)))
    if not isinstance(rules, list):
        raise ValueError("authored split clone rules must be an explicit JSON array")
    return prepare_authored_material_identity_split(
        root,
        run_id=run_id,
        clone_rules=rules,
        source_material_plan_mode=source_material_plan_mode,
        delegation_path=delegation_path,
    )


def run_authored_material_identity_split_preapproval_public(job_id: str, *, plan_path: str) -> dict:
    """Run the fixed isolated native preapproval and stop before specialized user authority."""
    return run_authored_material_identity_split_preapproval(job_dir(job_id), plan_path=plan_path)


def get_authored_material_identity_split_approval_request(
    job_id: str, *, approval_request_path: str
) -> dict:
    """Read one validated native candidate request without interpreting it as approval."""
    root = job_dir(job_id).resolve(strict=True)
    ref = runtime.reference(root, approval_request_path)
    checked = runtime.validate_request(root, ref)
    return {
        "approval_request": checked["request"],
        "approval_request_artifact": ref,
        "is_user_approval": False,
    }


def approve_authored_material_identity_split(
    job_id: str,
    *,
    approval_request_path: str,
    approval_path: str,
    user_decision_path: str,
    explicit_user_decision_observed: bool,
) -> dict:
    """Preserve caller-authored approval and exact original user decision bytes."""
    root = job_dir(job_id).resolve(strict=True)
    approval = AuthoredMaterialIdentitySplitApprovalV02.model_validate_json(
        runtime.read(root, runtime.reference(root, approval_path))
    )
    return publish_authored_material_identity_split_approval(
        root,
        approval_request_path=approval_request_path,
        approval=approval,
        user_decision=runtime.read(root, runtime.reference(root, user_decision_path)),
        explicit_user_decision_observed=explicit_user_decision_observed,
    )


def apply_authored_material_identity_split_public(job_id: str, *, apply_intent_path: str) -> dict:
    """Apply only a complete caller-authored specialized four-file intent."""
    root = job_dir(job_id).resolve(strict=True)
    content = runtime.read(root, runtime.reference(root, apply_intent_path))
    model = (
        AuthoredMaterialIdentitySplitTechnicalApplyIntentV02
        if json.loads(content).get("profile") == runtime.DELEGATED_PROFILE
        else AuthoredMaterialIdentitySplitApplyIntentV02
    )
    intent = model.model_validate_json(content)
    return apply_authored_material_identity_split(root, intent=intent)


def recover_authored_material_identity_split_public(
    job_id: str, *, run_id: str, apply_intent_sha256: str
) -> dict:
    """Recover a partial exact intent without another approval or canonical rebuild."""
    return recover_authored_material_identity_split(
        job_dir(job_id), run_id=run_id, apply_intent_sha256=apply_intent_sha256
    )


def get_authored_material_identity_split_status(job_id: str, *, run_id: str) -> dict:
    """Report a validated immutable run boundary, including explicit recovery-required state."""
    root = job_dir(job_id).resolve(strict=True)
    base = runtime.prefix(run_id)
    plan, ref = runtime.run_contract(root, run_id, "plan.json", "plan")
    runtime.validate_plan(root, ref)
    status = "planned"
    if (root / base / "apply_intent.json").exists():
        intent, _ = runtime.run_contract(root, run_id, "apply_intent.json", "apply")
        runtime.validate_approval(root, intent)
        if (root / base / "journal.json").exists():
            checked = runtime.validate_transaction(root, run_id, terminal_required=False)
            status = checked["terminal"]["status"] if checked["terminal"] else "recovery_required"
        else:
            status = "recovery_required"
    elif (root / base / "approval_request.json").exists():
        checked = runtime.validate_request(
            root, runtime.reference(root, f"{base}/approval_request.json")
        )
        status = checked["request"]["status"]
    elif (root / base / "failure.json").exists():
        runtime.read(root, runtime.reference(root, f"{base}/failure.json"))
        status = "preapproval_failed"
    return {
        "schema_version": "0.2.0",
        "profile": plan["profile"],
        "job_id": job_id,
        "run_id": run_id,
        "status": status,
        "plan": ref,
        "material_closure_status": plan["material_closure_status"],
        "final_human_acceptance": False,
    }


def approve_authored_material_identity_split_technical(
    job_id: str,
    *,
    approval_request_path: str,
    technical_approval_path: str,
    technical_decision_path: str,
    explicit_technical_decision_observed: bool,
) -> dict:
    """Publish only an explicit assistant technical decision under an exact existing delegation."""
    root = job_dir(job_id).resolve(strict=True)
    approval = AuthoredMaterialIdentitySplitTechnicalApprovalV02.model_validate_json(
        runtime.read(root, runtime.reference(root, technical_approval_path))
    )
    return publish_authored_material_identity_split_technical_approval(
        root,
        approval_request_path=approval_request_path,
        approval=approval,
        technical_decision=runtime.read(root, runtime.reference(root, technical_decision_path)),
        explicit_technical_decision_observed=explicit_technical_decision_observed,
    )
