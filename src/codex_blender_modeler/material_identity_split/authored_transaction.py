"""Four-file CAS and exact rollback for explicit-profile authored identity splits."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from .. import authored_split_runtime as runtime
from .. import workspace
from ..blender_artifacts import publish_bytes_create_once, sha256_file
from ..orchestration.locks import workflow_write_lock
from ..paired_revision_runtime import _file, assert_no_pending_pair
from ..workspace import _require_scene_spec_lock_owner
from .authored_models import (
    AuthoredMaterialIdentitySplitApplyIntentV02,
    AuthoredMaterialIdentitySplitConsumptionV02,
    AuthoredMaterialIdentitySplitJournalV02,
    AuthoredMaterialIdentitySplitTechnicalApplyIntentV02,
    AuthoredMaterialIdentitySplitTechnicalConsumptionV02,
    AuthoredMaterialIdentitySplitTerminalV02,
)
from .authored_service import publish, validate_authored_split_plan


def _root(job_root: Path) -> Path:
    """Bind the shared lock to the passed job and the host's exact workspace selection."""
    if job_root.is_symlink():
        raise ValueError("authored split canonical job cannot be linked")
    root = job_root.expanduser().resolve(strict=True)
    selected = workspace.job_dir(root.name)
    if selected.is_symlink() or selected.resolve(strict=True) != root:
        raise ValueError(
            "authored split passed job root differs from the host workspace lock target"
        )
    return root


def _checkpoint(name: str) -> None:
    """Expose deterministic synthetic crash injection without runtime callback authority."""


def _cas(root: Path, owner: str, path: str, expected: str, content: bytes) -> None:
    """Replace only an exact owned canonical byte state under the existing shared job lock."""
    destination = _file(root, path)
    temporary = destination.with_name(f".{destination.name}.authored-split-{uuid4().hex}.tmp")
    publish_bytes_create_once(temporary, content)
    _require_scene_spec_lock_owner(root, root.name, owner)
    if sha256_file(_file(root, path)) != expected or temporary.read_bytes() != content:
        raise ValueError("authored split CAS refuses concurrent or tampered bytes")
    if sha256_file(_file(root, path)) != expected:
        raise ValueError("authored split CAS refuses a late concurrent edit")
    os.replace(temporary, destination)


def _state(root: Path, expected: dict[str, str], plan: dict) -> None:
    """Rehash all four tracked files and preserved material/source inputs at every boundary."""
    for path, digest in expected.items():
        runtime.read(root, {"path": path, "sha256": digest}, binary=path.endswith(".blend"))
    runtime.read(
        root,
        {
            "path": "analysis/material_plan.json",
            "sha256": plan["source_files"]["analysis/material_plan.json"]["sha256"],
        },
    )
    for path, digest in plan["immutable_dependencies"].items():
        runtime.read(root, {"path": path, "sha256": digest})
    if (root / "analysis/material_binding_derivative.json").exists():
        raise ValueError("authored split effective-geometry override appeared during transaction")


def _journal(root: Path, intent: dict, intent_ref: dict, checked: dict) -> dict:
    """Publish the sole deterministic one-use claim/journal, exact-adopting crash predecessors."""
    run_id, base = intent["run_id"], runtime.prefix(intent["run_id"])
    identity = {"job_id": root.name, "run_id": run_id, "profile": intent["profile"]}
    consumption_fields = runtime.consumption_payload(root, intent, intent_ref, checked["plan"])
    model = (
        AuthoredMaterialIdentitySplitTechnicalConsumptionV02
        if intent["profile"] == runtime.DELEGATED_PROFILE
        else AuthoredMaterialIdentitySplitConsumptionV02
    )
    consumption = model.model_validate_json(runtime.encode(consumption_fields))
    for path in runtime.consumption_claim_paths(consumption_fields):
        publish(root, path, consumption)
    _checkpoint("after_global_consumption")
    consumption_ref = publish(root, f"{base}/consumption.json", consumption)
    _checkpoint("after_consumption")
    plan = checked["plan"]
    candidate = {
        "analysis/scene_spec.json": plan["candidate_scene_spec"],
        "analysis/modeling_plan.json": plan["candidate_modeling_plan"],
        "job.json": plan["candidate_job_metadata"],
        "blender/scene.blend": checked["request"]["shadow_blend"],
    }
    journal = AuthoredMaterialIdentitySplitJournalV02(
        **identity,
        apply_intent=intent_ref,
        approval_consumption=consumption_ref,
        before={path: plan["source_files"][path]["sha256"] for path in runtime.TARGETS.values()},
        after={path: candidate[path]["sha256"] for path in runtime.TARGETS.values()},
    )
    return publish(root, f"{base}/journal.json", journal)


def apply_authored_material_identity_split(
    job_root: Path,
    *,
    intent: AuthoredMaterialIdentitySplitApplyIntentV02
    | AuthoredMaterialIdentitySplitTechnicalApplyIntentV02,
) -> dict:
    """Consume one specialized user decision and CAS SceneSpec/ModelingPlan/job/Blend together."""
    root = _root(job_root)
    intent_model = (
        AuthoredMaterialIdentitySplitTechnicalApplyIntentV02
        if intent.profile == runtime.DELEGATED_PROFILE
        else AuthoredMaterialIdentitySplitApplyIntentV02
    )
    intent_model.model_validate_json(intent.model_dump_json())
    raw = intent.model_dump(mode="json")
    if intent.job_id != root.name:
        raise ValueError("authored split apply intent belongs to another job")
    base, owner = runtime.prefix(intent.run_id), runtime.workflow_identity(intent.run_id)
    assert_no_pending_pair(root)
    with workflow_write_lock(root, root.name, owner, ttl_seconds=86400):
        assert_no_pending_pair(root)
        if (root / base / "apply_intent.json").exists():
            raise FileExistsError(
                "authored split original approval already consumed; apply replay forbidden"
            )
        checked = runtime.validate_approval(root, raw, current=True)
        validate_authored_split_plan(root, raw["plan"], current=True)
        plan = checked["plan"]
        prospective_intent = {
            "path": f"{base}/apply_intent.json",
            "sha256": runtime.sha(runtime.encode(raw)),
        }
        prospective_claim = runtime.consumption_payload(root, raw, prospective_intent, plan)
        for claim_path in runtime.consumption_claim_paths(prospective_claim):
            path = root / claim_path
            if path.exists() or path.is_symlink():
                raise FileExistsError(
                    "authored split original authority already consumed; rewrapping is forbidden"
                )
        before = {path: plan["source_files"][path]["sha256"] for path in runtime.TARGETS.values()}
        _state(root, before, plan)
        candidate = {
            "analysis/scene_spec.json": plan["candidate_scene_spec"],
            "analysis/modeling_plan.json": plan["candidate_modeling_plan"],
            "job.json": plan["candidate_job_metadata"],
            "blender/scene.blend": checked["request"]["shadow_blend"],
        }
        for label, path in runtime.TARGETS.items():
            extension = "blend" if label == "blend" else "json"
            for direction, ref in (
                ("before", plan["source_files"][path]),
                ("after", candidate[path]),
            ):
                publish(
                    root,
                    f"{base}/archives/{label}.{direction}.{extension}",
                    runtime.read(root, ref, binary=label == "blend"),
                )
        _checkpoint("after_archives")
        runtime.validate_approval(root, raw, current=True)
        _state(root, before, plan)
        intent_ref = publish(root, f"{base}/apply_intent.json", intent)
        _checkpoint("after_apply_intent")
        journal_ref = _journal(root, raw, intent_ref, checked)
        _checkpoint("after_journal")
        verified = runtime.validate_transaction(root, intent.run_id, terminal_required=False)
        expected = dict(before)
        for label, path in runtime.TARGETS.items():
            _state(root, expected, plan)
            runtime.validate_transaction(root, intent.run_id, terminal_required=False)
            content = verified["archives"]["after"][path]
            _cas(root, owner, path, before[path], content)
            expected[path] = runtime.sha(content)
            _checkpoint(f"after_{label}")
        _state(root, expected, plan)
        # Complete source/F32 proofs run against explicit prospective sources, never a
        # canonical selector while this four-file journal is pending.
        validate_authored_split_plan(root, raw["plan"], current=False)
        runtime.validate_transaction(root, intent.run_id, terminal_required=False)
        _state(root, expected, plan)
        _checkpoint("before_receipt")
        runtime.validate_transaction(root, intent.run_id, terminal_required=False)
        _state(root, expected, plan)
        receipt = publish(
            root,
            f"{base}/receipt.json",
            AuthoredMaterialIdentitySplitTerminalV02(
                job_id=root.name,
                run_id=intent.run_id,
                profile=intent.profile,
                status="committed",
                journal=journal_ref,
                canonical=expected,
            ),
        )
        _checkpoint("after_receipt")
        assert_no_pending_pair(root)
        return {
            "status": "committed",
            "apply_intent": intent_ref,
            "receipt": receipt,
            "material_closure_status": "pending_native_material_workflow",
            "canonical_rebuild_performed": False,
        }


def recover_authored_material_identity_split(
    job_root: Path, *, run_id: str, apply_intent_sha256: str
) -> dict:
    """Roll back exact owned bytes, including interrupted consumption, without new authority."""
    root = _root(job_root)
    base, owner = runtime.prefix(run_id), runtime.workflow_identity(run_id)
    with workflow_write_lock(root, root.name, owner, ttl_seconds=86400):
        if (root / base / "receipt.json").exists() or (root / base / "rollback.json").exists():
            raise FileExistsError(
                "authored split transaction is terminal; recovery replay forbidden"
            )
        intent_ref = {"path": f"{base}/apply_intent.json", "sha256": apply_intent_sha256}
        intent = runtime.contract(root, intent_ref, "apply")
        if intent["run_id"] != run_id:
            raise ValueError("authored split recovery has a foreign intent")
        checked = runtime.validate_approval(root, intent)
        plan = checked["plan"]
        before = {path: plan["source_files"][path]["sha256"] for path in runtime.TARGETS.values()}
        if not (root / base / "journal.json").exists():
            # A pre-journal crash cannot have written any canonical file. Exact-adopt
            # deterministic missing claim bytes, then consume the aborted transaction.
            _state(root, before, plan)
            _journal(root, intent, intent_ref, checked)
        verified = runtime.validate_transaction(root, run_id, terminal_required=False)
        journal = verified["intent"]
        expected = {
            path: runtime.reference(root, path)["sha256"] for path in runtime.TARGETS.values()
        }
        if any(
            expected[path] not in {journal["before"][path], journal["after"][path]}
            for path in expected
        ):
            raise ValueError("authored split recovery refuses concurrent user edits")
        _state(root, expected, plan)
        publish(
            root,
            f"{base}/recovery_started.json",
            {"schema_version": "0.2.0", "apply_intent": intent_ref, "journal": verified["journal"]},
        )
        _checkpoint("recovery_started")
        for label, path in runtime.TARGETS.items():
            runtime.validate_transaction(root, run_id, terminal_required=False)
            _state(root, expected, plan)
            if expected[path] != before[path]:
                _cas(root, owner, path, expected[path], verified["archives"]["before"][path])
            expected[path] = before[path]
            _checkpoint(f"recovery_after_{label}")
        runtime.validate_transaction(root, run_id, terminal_required=False)
        _state(root, before, plan)
        receipt = publish(
            root,
            f"{base}/rollback.json",
            AuthoredMaterialIdentitySplitTerminalV02(
                job_id=root.name,
                run_id=run_id,
                profile=intent["profile"],
                status="rolled_back",
                journal=verified["journal"],
                canonical=before,
            ),
        )
        assert_no_pending_pair(root)
        return {"status": "rolled_back", "rollback": receipt, "approval_reconsumed": False}
