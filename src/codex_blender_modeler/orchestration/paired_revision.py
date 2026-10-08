"""Bounded opt-in ModelingPlan companions and fail-closed paired host transactions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..analysis.models import ModelingPlan
from ..blender_artifacts import deterministic_json_bytes, publish_bytes_create_once, sha256_file
from ..models import SceneSpec
from ..workspace import _require_scene_spec_lock_owner
from .paired_models import (
    AttachmentCommitReceiptV02,
    AttachmentRollbackReceiptV02,
    AttachmentTransactionIntentV02,
    PairedCommitReceipt,
    PairedModelingPlanBinding,
    PairedRollbackReceipt,
    PairedTransactionIntent,
)


def ensure_contained_production_path(*args, **kwargs):
    """Load the existing containment helper lazily to avoid orchestration import cycles."""

    from ..production.validation import ensure_contained_production_path as validate

    return validate(*args, **kwargs)


PAIRED_PATH_PARAMETER = "paired_modeling_plan_path"
PAIRED_HASH_PARAMETER = "paired_modeling_plan_sha256"
SCENE_PATH = "analysis/scene_spec.json"
MODEL_PATH = "analysis/modeling_plan.json"
JOB_PATH = "job.json"


def _targets(version: str) -> tuple[tuple[str, str], ...]:
    """Select only the exact legacy pair or opted-in fixed triple target inventory."""
    if version not in {"0.1.0", "0.2.0"}:
        raise ValueError("unknown paired transaction version")
    return (("scene", SCENE_PATH), ("model", MODEL_PATH)) + (
        (("job", JOB_PATH),) if version == "0.2.0" else ()
    )


def _file(root: Path, relative: str, *, exists: bool = True) -> Path:
    """Require normalized lexical containment, ordinary files and no link ancestors."""

    from .models import _validate_job_relative_path

    _validate_job_relative_path(relative)
    path = ensure_contained_production_path(root, root / relative, must_exist=exists)
    if exists and not path.is_file():
        raise ValueError("paired revision artifact must be a regular file")
    return path


def _diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    """Describe exact normalized field changes, including ordered list membership."""

    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict) and before.keys() == after.keys():
        return [
            entry for key in before for entry in _diff(before[key], after[key], f"{path}/{key}")
        ]
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [
            entry
            for index, (a, b) in enumerate(zip(before, after, strict=True))
            for entry in _diff(a, b, f"{path}/{index}")
        ]
    return [{"path": path, "before": before, "after": after}]


def validate_modeling_change(old: ModelingPlan, new: ModelingPlan) -> list[dict[str, Any]]:
    """Allow representation notes and additive same-identity checks without weakening evidence."""

    a, b = old.model_dump(mode="json"), new.model_dump(mode="json")
    json.dumps(a, allow_nan=False)
    json.dumps(b, allow_nan=False)
    allowed = {
        "objects",
        "global_notes",
        "assembly_relationships",
        "surface_details",
        "surface_detail_policy",
    }
    if any(a[key] != b[key] for key in a if key not in allowed):
        raise ValueError(
            "paired revision changed immutable ModelingPlan identity, evidence or frame"
        )
    if old.stage != "authored" or new.stage != "authored":
        raise ValueError("paired revision requires authored ModelingPlans")
    if [obj.id for obj in old.objects] != [obj.id for obj in new.objects]:
        raise ValueError("paired revision changed semantic object identities or ordering")
    for before, after in zip(a["objects"], b["objects"], strict=True):
        if any(
            before[key] != after[key]
            for key in before
            if key not in {"recommended_geometry", "notes", "required_assembly_checks"}
        ):
            raise ValueError(
                "paired revision changed object identity, scope, role or observation evidence"
            )
        if not set(before["required_assembly_checks"]) <= set(after["required_assembly_checks"]):
            raise ValueError("paired revision weakened required assembly checks")
    for key in ("assembly_relationships", "surface_details"):
        if [item["id"] for item in b[key]][: len(a[key])] != [item["id"] for item in a[key]]:
            raise ValueError(f"paired revision must append {key} without reordering history")
        updated = {item["id"]: item for item in b[key]}
        for original in a[key]:
            replacement = updated.get(original["id"])
            if replacement is None or any(
                original[field] != replacement[field]
                for field in original
                if field != "notes" or key == "assembly_relationships"
            ):
                raise ValueError(f"paired revision removed or weakened existing {key}")
    before_policy, after_policy = a["surface_detail_policy"], b["surface_detail_policy"]
    if before_policy is not None:
        if after_policy is None or any(
            before_policy[key] != after_policy[key]
            for key in before_policy
            if key not in {"notes", "geometry_required_conditions"}
        ):
            raise ValueError("paired revision changed existing surface-detail policy")
        if not set(before_policy["geometry_required_conditions"]) <= set(
            after_policy["geometry_required_conditions"]
        ):
            raise ValueError("paired revision weakened geometry-required conditions")
    elif after_policy is not None and (
        after_policy["mode"] != "explicit" or after_policy["default_representation"] == "omit"
    ):
        raise ValueError("new paired surface-detail policy must be explicit and non-omitting")
    sources = {source for obj in old.objects for source in obj.source_ids}
    if any(not set(detail.source_ids) <= sources for detail in new.surface_details):
        raise ValueError("paired revision introduced new surface-detail observation sources")
    if any(not set(relation.source_ids) <= sources for relation in new.assembly_relationships):
        raise ValueError("paired revision introduced new relationship observation sources")
    return _diff(a, b)


def validate_pair(
    root: Path,
    before_scene: SceneSpec,
    candidate_scene: SceneSpec,
    old: ModelingPlan,
    new: ModelingPlan,
) -> list[dict[str, Any]]:
    """Validate unchanged semantic scope and the candidate's real assembly/detail contracts."""

    from ..analysis.assembly import validate_assembly_prebuild_contract
    from ..analysis.surface_details import validate_surface_detail_contract
    from ..reference_scope import (
        reference_content_scope_from_metadata,
        validate_modeling_plan_content_scope,
        validate_scene_content_scope,
    )
    from ..validation import validate_scene_spec_interior_contract

    changes = validate_modeling_change(old, new)
    a, b = before_scene.model_dump(mode="json"), candidate_scene.model_dump(mode="json")
    json.dumps(a, allow_nan=False)
    json.dumps(b, allow_nan=False)
    for key in ("schema_version", "job_id", "mode", "units", "coordinate_system", "sources"):
        if a[key] != b[key]:
            raise ValueError(f"paired revision changed immutable SceneSpec {key}")
    if root.name != old.job_id or old.job_id != before_scene.job_id:
        raise ValueError("paired revision belongs to another job")
    if {obj.id for obj in before_scene.objects} != {obj.id for obj in candidate_scene.objects}:
        raise ValueError("paired revision changed SceneSpec semantic identities")
    if {mat.id for mat in before_scene.materials} != {mat.id for mat in candidate_scene.materials}:
        raise ValueError("paired revision changed material identities")
    original = {obj.id: obj for obj in before_scene.objects}
    for obj in candidate_scene.objects:
        old_obj = original[obj.id]
        if obj.material_id != old_obj.material_id or obj.evidence != old_obj.evidence:
            raise ValueError("paired revision changed material assignments or observation evidence")
        if obj.tags != old_obj.tags or obj.generator != old_obj.generator:
            raise ValueError("paired revision changed object scope tags or instance count")
    if {obj.id for obj in new.objects} != set(original):
        raise ValueError("paired ModelingPlan and SceneSpec identities differ")
    metadata = json.loads(_file(root, "job.json").read_bytes())
    scope, subject = reference_content_scope_from_metadata(metadata)
    validate_modeling_plan_content_scope(new, scope=scope, target_subject=subject)
    validate_scene_content_scope(candidate_scene, scope=scope, target_subject=subject)
    validate_scene_spec_interior_contract(candidate_scene, root / SCENE_PATH)
    for report in (
        validate_assembly_prebuild_contract(new, candidate_scene),
        validate_surface_detail_contract(new, candidate_scene, root),
    ):
        if not report.ok:
            raise ValueError("paired candidate violates assembly or surface-detail contracts")
    return changes


def _preserved_evidence_relative(root: Path, plan: ModelingPlan, field: str) -> str:
    """Resolve only exact same-job historical observation aliases without editing them.

    Existing ordinary POSIX-relative files retain their literal meaning. The two
    historical workspace-prefixed spellings may fall back to the same job's fixed
    analysis filename only when no competing literal file exists. Generic candidate
    and dependency paths still pass through the unchanged strict `_file` boundary.
    """

    filenames = {
        "reference_analysis_path": "reference_analysis.json",
        "camera_solution_path": "camera_solution.json",
    }
    if plan.job_id != root.name or field not in filenames:
        raise ValueError("preserved evidence belongs to another job or field")
    relative = getattr(plan, field)
    short = f"analysis/{filenames[field]}"
    historical = f"workspaces/{plan.job_id}/{short}"
    if "\\" not in relative:
        # A valid existing modern locator is never silently reinterpreted as an alias.
        literal = _file(root, relative, exists=False)
        if literal.is_file():
            return relative
        if literal.exists():
            _file(root, relative)
        if relative != historical:
            _file(root, relative)
            raise ValueError("missing preserved evidence")
    elif relative == historical.replace("/", "\\"):
        # On POSIX a backslash can be a filename character; such ambiguity is refused.
        literal = root / relative
        nested = _file(root, historical, exists=False)
        if literal.exists() or literal.is_symlink() or nested.exists():
            raise ValueError("ambiguous historical preserved evidence locator")
    else:
        raise ValueError("unsupported historical preserved evidence locator")
    _file(root, short)
    return short


def preserved_source_hashes(root: Path, plan: ModelingPlan) -> dict[str, str]:
    """Pin observation/camera evidence, immutable job metadata and every input byte."""

    relatives = {
        "job.json",
        _preserved_evidence_relative(root, plan, "reference_analysis_path"),
        _preserved_evidence_relative(root, plan, "camera_solution_path"),
    }
    input_root = ensure_contained_production_path(root, root / "input", must_exist=True)
    for path in input_root.rglob("*"):
        ensure_contained_production_path(root, path, must_exist=True)
        if path.is_file():
            relatives.add(path.relative_to(root).as_posix())
    return {relative: sha256_file(_file(root, relative)) for relative in sorted(relatives)}


def validate_candidate_path(root: Path, relative: str, expected: str) -> ModelingPlan:
    """Reject canonical, output, unknown, escaped or stale ModelingPlan candidate sources."""

    if relative in {MODEL_PATH, SCENE_PATH, "analysis/revision_plan.json"} or relative.startswith(
        ("input/", "reports/", "history/", "workflows/")
    ):
        raise ValueError("paired ModelingPlan requires a distinct staged analysis candidate")
    if not relative.startswith("analysis/") or not relative.endswith(".json"):
        raise ValueError("paired ModelingPlan candidate must be a staged analysis JSON file")
    path = _file(root, relative)
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("paired ModelingPlan candidate hash changed")
    candidate = ModelingPlan.model_validate_json(content)
    old = ModelingPlan.model_validate_json(_file(root, MODEL_PATH).read_bytes())
    validate_modeling_change(old, candidate)
    return candidate


def create_modeling_binding(
    root: Path, candidate_scene: SceneSpec, relative: str, expected: str
) -> dict[str, Any]:
    """Bind both exact plan bytes and narrow changes to the existing revision approval."""

    old_path = _file(root, MODEL_PATH)
    before_hash = sha256_file(old_path)
    old = ModelingPlan.model_validate_json(old_path.read_bytes())
    new = validate_candidate_path(root, relative, expected)
    before_scene = SceneSpec.model_validate_json(_file(root, SCENE_PATH).read_bytes())
    changes = validate_pair(root, before_scene, candidate_scene, old, new)
    sources = preserved_source_hashes(root, old)
    if sha256_file(old_path) != before_hash or sha256_file(_file(root, relative)) != expected:
        raise ValueError("paired ModelingPlan changed during binding")
    return {
        "schema_version": "0.1.0",
        "base_modeling_plan_sha256": before_hash,
        "candidate_path": relative,
        "candidate_sha256": expected,
        "base_modeling_plan": old.model_dump(mode="json"),
        "candidate_modeling_plan": new.model_dump(mode="json"),
        "base_scene_spec": before_scene.model_dump(mode="json"),
        "changes": changes,
        "preserved_sources": sources,
    }


def validate_modeling_binding(
    root: Path, payload: dict[str, Any], candidate_scene: SceneSpec,
    *, metadata_after_sha256: str | None = None,
) -> None:
    """Reject changed companion structure, source evidence, candidate bytes or exact field diff."""

    PairedModelingPlanBinding.model_validate(payload)
    keys = {
        "schema_version",
        "base_modeling_plan_sha256",
        "candidate_path",
        "candidate_sha256",
        "base_modeling_plan",
        "candidate_modeling_plan",
        "base_scene_spec",
        "changes",
        "preserved_sources",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != keys
        or payload["schema_version"] != "0.1.0"
    ):
        raise ValueError("paired ModelingPlan binding fields or version changed")
    old = ModelingPlan.model_validate(payload["base_modeling_plan"])
    new = ModelingPlan.model_validate(payload["candidate_modeling_plan"])
    source = _file(root, payload["candidate_path"])
    if (
        sha256_file(source) != payload["candidate_sha256"]
        or ModelingPlan.model_validate_json(source.read_bytes()) != new
    ):
        raise ValueError("paired ModelingPlan candidate bytes changed")
    current_sources = preserved_source_hashes(root, old)
    if metadata_after_sha256 is not None and current_sources[JOB_PATH] == metadata_after_sha256:
        # The caller first validates the exact approval-bound attachment companion.
        current_sources[JOB_PATH] = payload["preserved_sources"][JOB_PATH]
    if current_sources != payload["preserved_sources"]:
        raise ValueError("paired revision observation evidence changed")
    if (
        validate_pair(
            root, SceneSpec.model_validate(payload["base_scene_spec"]), candidate_scene, old, new
        )
        != payload["changes"]
    ):
        raise ValueError("paired ModelingPlan exact diff changed")


def transaction_path(root: Path, workflow_id: str, name: str) -> Path:
    """Resolve one fixed workflow-owned paired transaction artifact without following links."""

    from pydantic import TypeAdapter

    from .models import WorkflowId

    TypeAdapter(WorkflowId).validate_python(workflow_id)
    if name not in {
        "intent.json",
        "receipt.json",
        "rollback.json",
        "recovery_started.json",
        "scene.before.json",
        "model.before.json",
        "scene.after.json",
        "model.after.json",
        "scene.restored.json",
        "model.restored.json",
        "finalized.json",
        "report.before.json",
        "job.before.json",
        "job.after.json",
        "job.restored.json",
    }:
        raise ValueError("unknown paired transaction artifact")
    return _file(root, f"workflows/{workflow_id}/paired_revision/{name}", exists=False)


def _publish(path: Path, payload: Any) -> None:
    """Publish immutable complete JSON once while refusing divergent evidence."""

    publish_bytes_create_once(path, deterministic_json_bytes(payload))


def _checkpoint(name: str) -> None:
    """Expose deterministic transaction interruption points to host tests only."""


def _cas(root: Path, workflow_id: str, relative: str, expected: str, content: bytes) -> None:
    """Atomically replace exactly the current bytes under the existing shared job lock."""

    target = _file(root, relative)
    temporary = target.with_name(f".{target.name}.paired-{uuid4().hex}.tmp")
    publish_bytes_create_once(temporary, content)
    _require_scene_spec_lock_owner(root, root.name, workflow_id)
    target = _file(root, relative)
    if sha256_file(target) != expected:
        raise ValueError("paired CAS refuses a concurrent canonical edit")
    if temporary.read_bytes() != content:
        raise ValueError("paired CAS replacement bytes changed")
    if sha256_file(_file(root, relative)) != expected:
        raise ValueError("paired CAS refuses a late concurrent canonical edit")
    os.replace(temporary, target)


def _load_intent(root: Path, workflow_id: str, expected: str | None = None) -> dict[str, Any]:
    """Read exact immutable intent and verify all archived before/after byte hashes."""

    path = transaction_path(root, workflow_id, "intent.json")
    content = path.read_bytes()
    if expected is not None and hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("paired recovery intent hash changed")
    value = json.loads(content)
    version = value.get("schema_version")
    (AttachmentTransactionIntentV02 if version == "0.2.0"
     else PairedTransactionIntent).model_validate(value)
    keys = {
        "schema_version",
        "job_id",
        "workflow_id",
        "binding_sha256",
        "before",
        "after",
        "evidence",
        "report_before_sha256",
    }
    if (
        set(value) != keys
        or value["schema_version"] not in {"0.1.0", "0.2.0"}
        or value["job_id"] != root.name
        or value["workflow_id"] != workflow_id
    ):
        raise ValueError("paired transaction intent is invalid")
    if value["report_before_sha256"] is not None:
        if (
            sha256_file(transaction_path(root, workflow_id, "report.before.json"))
            != value["report_before_sha256"]
        ):
            raise ValueError("paired archived prior report changed")
    for direction in ("before", "after"):
        if set(value[direction]) != {relative for _, relative in _targets(version)}:
            raise ValueError("paired transaction target inventory changed")
        for prefix, relative in _targets(version):
            archive = transaction_path(root, workflow_id, f"{prefix}.{direction}.json")
            if sha256_file(archive) != value[direction][relative]:
                raise ValueError("paired transaction archive bytes changed")
    from .models import WorkflowApproval, WorkflowPlan, WorkflowRequest, WorkflowStepCompletion
    from .revision_payloads import binding_path

    prefix = f"workflows/{workflow_id}"
    mandatory = {
        "analysis/revision_plan.json",
        MODEL_PATH,
        f"{prefix}/plan.json",
        f"{prefix}/request.json",
        f"{prefix}/artifacts/revision_payload_binding.json",
        f"{prefix}/completions/revision.author.json",
        f"{prefix}/approvals/revision.approval.json",
    }
    if set(value["evidence"]) != mandatory:
        raise ValueError("paired intent must bind the exact Standard generic approval chain")
    archived = {}
    for relative, digest in value["evidence"].items():
        artifact = _file(root, f"{prefix}/paired_revision/evidence/{relative}")
        if sha256_file(artifact) != digest:
            raise ValueError("paired archived authority evidence changed")
        if relative.startswith(prefix + "/") and sha256_file(_file(root, relative)) != digest:
            raise ValueError("paired immutable authority chain changed")
        archived[relative] = artifact.read_bytes()
    request = WorkflowRequest.model_validate_json(archived[f"{prefix}/request.json"])
    plan = WorkflowPlan.model_validate_json(archived[f"{prefix}/plan.json"])
    completion = WorkflowStepCompletion.model_validate_json(
        archived[f"{prefix}/completions/revision.author.json"]
    )
    approval = WorkflowApproval.model_validate_json(
        archived[f"{prefix}/approvals/revision.approval.json"]
    )
    binding = json.loads(binding_path(root, workflow_id).read_bytes())
    pair = binding["paired_modeling_plan"]
    expected_after = {
        SCENE_PATH: hashlib.sha256(
            deterministic_json_bytes(binding["candidate_scene_spec"])
        ).hexdigest(),
        MODEL_PATH: pair["candidate_sha256"],
    }
    expected_before = {
        SCENE_PATH: binding["base_spec_sha256"],
        MODEL_PATH: pair["base_modeling_plan_sha256"],
    }
    if version == "0.2.0":
        from ..attachment_revision_runtime import validate_revision_transaction

        revision = binding["attachment_revision"]
        expected_before[JOB_PATH] = revision["record"]["metadata_before_sha256"]
        expected_after[JOB_PATH] = revision["metadata_after_sha256"]
        validate_revision_transaction(root, workflow_id, require_committed=False)
    elif "attachment_revision" in binding or request.attachment_intent_path is not None:
        raise ValueError("attachment revision cannot use a legacy two-file transaction")
    if (
        sha256_file(binding_path(root, workflow_id)) != value["binding_sha256"]
        or value["before"] != expected_before
        or value["after"] != expected_after
        or request.job_id != root.name
        or request.workflow_id != workflow_id
        or request.paired_modeling_plan_path != pair["candidate_path"]
        or request.paired_modeling_plan_sha256 != pair["candidate_sha256"]
        or plan.request_sha256 != value["evidence"][f"{prefix}/request.json"]
        or plan.workflow_id != workflow_id
        or plan.job_id != root.name
        or completion.plan_sha256 != value["evidence"][f"{prefix}/plan.json"]
        or approval.plan_sha256 != completion.plan_sha256
        or completion.step_id != "revision.author"
        or approval.step_id != "revision.approval"
        or completion.job_id != root.name
        or approval.job_id != root.name
        or completion.workflow_id != workflow_id
        or approval.workflow_id != workflow_id
        or not any(
            item.artifact_id == "revision.payload_binding"
            and item.sha256 == value["binding_sha256"]
            for item in completion.output_artifacts
        )
    ):
        raise ValueError(
            "paired intent differs from original approval, author or candidate binding"
        )
    from types import SimpleNamespace

    from ..blender_artifacts import stable_json_digest
    from .service import _artifact_fingerprint, _step_input_fingerprint

    author_step = next(step for step in plan.steps if step.step_id == "revision.author")
    approval_step = next(step for step in plan.steps if step.step_id == "revision.approval")
    author_fingerprint = stable_json_digest(
        {
            "input": completion.input_fingerprint,
            "output": completion.output_fingerprint,
            "completion_id": completion.completion_id,
        }
    )
    if (
        completion.input_fingerprint != _step_input_fingerprint(plan, request, author_step, {})
        or completion.output_fingerprint != _artifact_fingerprint(completion.output_artifacts)
        or approval.artifact_fingerprint
        != _step_input_fingerprint(
            plan,
            request,
            approval_step,
            {"revision.author": SimpleNamespace(completion_fingerprint=author_fingerprint)},
        )
    ):
        raise ValueError("paired original author or approval fingerprint is invalid")
    if (
        value["evidence"]["analysis/revision_plan.json"] != binding["revision_plan_sha256"]
        or value["evidence"][MODEL_PATH] != expected_before[MODEL_PATH]
    ):
        raise ValueError("paired source hashes differ from approved binding")
    return value


def committed_receipt(
    root: Path, workflow_id: str, *, require_current: bool = False
) -> dict[str, Any] | None:
    """Validate committed provenance without retroactively staling immutable workflow history."""

    path = transaction_path(root, workflow_id, "receipt.json")
    if not path.exists():
        return None
    receipt = json.loads(path.read_bytes())
    (AttachmentCommitReceiptV02 if receipt.get("schema_version") == "0.2.0"
     else PairedCommitReceipt).model_validate(receipt)
    if (
        set(receipt) != {"schema_version", "status", "intent_sha256", "after"}
        or receipt["schema_version"] not in {"0.1.0", "0.2.0"}
        or receipt["status"] != "committed"
    ):
        raise ValueError("paired committed receipt is invalid")
    intent = _load_intent(root, workflow_id, receipt["intent_sha256"])
    if (
        receipt["after"] != intent["after"]
        or receipt["schema_version"] != intent["schema_version"]
        or transaction_path(root, workflow_id, "rollback.json").exists()
    ):
        raise ValueError("paired transaction terminal evidence conflicts")
    from .revision_payloads import binding_path

    if sha256_file(binding_path(root, workflow_id)) != intent["binding_sha256"]:
        raise ValueError("paired transaction binding changed")
    if require_current and any(
        sha256_file(_file(root, relative)) != expected
        for relative, expected in intent["after"].items()
    ):
        raise ValueError("paired current canonical files differ from committed pair")
    return receipt


def assert_no_pending_pair(root: Path) -> None:
    """Block all canonical readers/writers while a two-file promotion needs explicit recovery."""

    from ..authored_split_runtime import BASE as authored_base

    if (root / authored_base).exists() or (root / authored_base).is_symlink():
        from ..paired_revision_runtime import assert_no_pending_pair as runtime_guard

        runtime_guard(root)
    workflows = root / "workflows"
    if not workflows.exists():
        return
    ensure_contained_production_path(root, workflows, must_exist=True)
    for path in workflows.glob("*/paired_revision/intent.json"):
        workflow_id = path.parent.parent.name
        _file(root, path.relative_to(root).as_posix())
        if committed_receipt(root, workflow_id) is not None:
            from types import SimpleNamespace

            from ..blender_artifacts import stable_json_digest
            from .models import WorkflowApproval, WorkflowAttempt, WorkflowPlan, WorkflowRequest
            from .service import _artifact_fingerprint, _step_input_fingerprint

            prefix = f"workflows/{workflow_id}"
            plan = WorkflowPlan.model_validate_json(_file(root, f"{prefix}/plan.json").read_bytes())
            request = WorkflowRequest.model_validate_json(
                _file(root, f"{prefix}/request.json").read_bytes()
            )
            approval = WorkflowApproval.model_validate_json(
                _file(root, f"{prefix}/approvals/revision.approval.json").read_bytes()
            )
            step = next(item for item in plan.steps if item.step_id == "revision.apply")
            approval_fingerprint = stable_json_digest(
                {"input": approval.artifact_fingerprint, "approval_id": approval.approval_id}
            )
            expected_input = _step_input_fingerprint(
                plan,
                request,
                step,
                {
                    "revision.approval": SimpleNamespace(
                        completion_fingerprint=approval_fingerprint
                    ),
                },
            )
            intent = _load_intent(root, workflow_id)
            receipt_path = transaction_path(root, workflow_id, "receipt.json")
            completed = False
            attempts = root / "workflows" / workflow_id / "attempts" / "revision.apply"
            for attempt_path in attempts.glob("*.json"):
                attempt = WorkflowAttempt.model_validate_json(
                    _file(root, attempt_path.relative_to(root).as_posix()).read_bytes()
                )
                if attempt.status != "succeeded":
                    continue
                bound = next(
                    (
                        item
                        for item in attempt.outputs
                        if item.artifact_id == "revision.paired_transaction"
                    ),
                    None,
                )
                if (
                    attempt.job_id != root.name
                    or attempt.workflow_id != workflow_id
                    or attempt.step_id != "revision.apply"
                    or bound is None
                    or bound.sha256 != sha256_file(receipt_path)
                    or bound.path != receipt_path.relative_to(root).as_posix()
                    or attempt.plan_sha256
                    != sha256_file(_file(root, f"workflows/{workflow_id}/plan.json"))
                    or attempt.output_fingerprint != _artifact_fingerprint(attempt.outputs)
                    or attempt.input_fingerprint != expected_input
                    or [item.artifact_id for item in attempt.outputs]
                    != [item.artifact_id for item in step.outputs]
                ):
                    raise ValueError("paired committed host receipt was tampered")
                for output, requirement in zip(attempt.outputs, step.outputs, strict=True):
                    if (
                        output.path != requirement.path
                        or output.integrity != "valid"
                        or output.sha256 != sha256_file(_file(root, requirement.path))
                    ):
                        raise ValueError("paired committed host snapshot was tampered")
                    target = {
                        "revision.scene_spec": SCENE_PATH,
                        "revision.modeling_plan": MODEL_PATH,
                        "revision.job_metadata": JOB_PATH,
                    }.get(output.artifact_id)
                    if target is not None and output.sha256 != intent["after"][target]:
                        raise ValueError("paired host snapshot differs from committed pair")
                completed = True
            if not completed:
                # A commit interrupted before host completion still needs the exact live pair.
                committed_receipt(root, workflow_id, require_current=True)
            continue
        rollback = transaction_path(root, workflow_id, "rollback.json")
        if rollback.exists():
            record = json.loads(rollback.read_bytes())
            (AttachmentRollbackReceiptV02 if record.get("schema_version") == "0.2.0"
             else PairedRollbackReceipt).model_validate(record)
            intent = _load_intent(root, workflow_id, record.get("intent_sha256"))
            if (
                set(record) == {"schema_version", "status", "intent_sha256", "before"}
                and record["schema_version"] == intent["schema_version"]
                and record["status"] == "rolled_back"
                and record["before"] == intent["before"]
            ):
                continue
        raise ValueError(
            "paired revision transaction is incomplete; exact intent hash recovery required"
        )

    if any(
        json.loads(path.read_bytes()).get("schema_version") == "0.2.0"
        for path in workflows.glob("*/paired_revision/intent.json")
    ):
        # Reuse the Blender-safe current-tip/anti-fork checks for every host reader too.
        from ..paired_revision_runtime import assert_no_pending_pair as runtime_guard

        runtime_guard(root)


def apply_pair(
    root: Path, workflow_id: str, binding: dict[str, Any], evidence: dict[str, str]
) -> dict[str, Any]:
    """Consume exact existing authority once and publish one journaled, validated canonical pair."""

    from .revision_payloads import binding_path, geometry_dependency_hashes, validate_binding
    from .service import _validate_guarded_revision_authority

    assert_no_pending_pair(root)
    intent_path = transaction_path(root, workflow_id, "intent.json")
    if intent_path.exists():
        raise FileExistsError("paired revision approval already consumed; replay is forbidden")
    _require_scene_spec_lock_owner(root, root.name, workflow_id)
    _validate_guarded_revision_authority(root, workflow_id)
    if validate_binding(root, workflow_id, require_current_candidate=True) != binding:
        raise ValueError("paired candidate changed before transaction")
    paired = binding["paired_modeling_plan"]
    before = {
        SCENE_PATH: binding["base_spec_sha256"],
        MODEL_PATH: paired["base_modeling_plan_sha256"],
    }
    after_content = {
        SCENE_PATH: deterministic_json_bytes(binding["candidate_scene_spec"]),
        MODEL_PATH: _file(root, paired["candidate_path"]).read_bytes(),
    }
    attachment = binding.get("attachment_revision")
    version = "0.2.0" if attachment is not None else "0.1.0"
    if attachment is not None:
        from .attachment_revision import metadata_after

        before[JOB_PATH] = attachment["record"]["metadata_before_sha256"]
        after_content[JOB_PATH] = metadata_after(
            _file(root, JOB_PATH).read_bytes(), attachment["revision"]
        )
        if (hashlib.sha256(after_content[JOB_PATH]).hexdigest()
                != attachment["metadata_after_sha256"]):
            raise ValueError("attachment revision prospective metadata changed")
        _publish(_file(root, attachment["revision"]["path"], exists=False), attachment["record"])
    after = {
        relative: hashlib.sha256(content).hexdigest() for relative, content in after_content.items()
    }
    for prefix, relative in _targets(version):
        content = _file(root, relative).read_bytes()
        if hashlib.sha256(content).hexdigest() != before[relative]:
            raise ValueError("paired baseline changed before archive")
        publish_bytes_create_once(
            transaction_path(root, workflow_id, f"{prefix}.before.json"), content
        )
        publish_bytes_create_once(
            transaction_path(root, workflow_id, f"{prefix}.after.json"), after_content[relative]
        )
    _checkpoint("after_archives")
    _validate_guarded_revision_authority(root, workflow_id)
    if validate_binding(root, workflow_id, require_current_candidate=True) != binding:
        raise ValueError("paired candidate changed before authority consumption")
    if any(
        sha256_file(_file(root, relative)) != expected for relative, expected in evidence.items()
    ):
        raise ValueError("paired authority evidence changed before consumption")
    previous_report = _file(root, "reports/revision_diff.json", exists=False)
    report_before_hash = None
    if previous_report.exists():
        report_bytes = _file(root, "reports/revision_diff.json").read_bytes()
        report_before_hash = hashlib.sha256(report_bytes).hexdigest()
        publish_bytes_create_once(
            transaction_path(root, workflow_id, "report.before.json"), report_bytes
        )
    intent = {
        "schema_version": version,
        "job_id": root.name,
        "workflow_id": workflow_id,
        "binding_sha256": sha256_file(binding_path(root, workflow_id)),
        "before": before,
        "after": after,
        "evidence": evidence,
        "report_before_sha256": report_before_hash,
    }
    for relative, digest in evidence.items():
        content = _file(root, relative).read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("paired approval/source evidence changed during archival")
        publish_bytes_create_once(
            _file(
                root, f"workflows/{workflow_id}/paired_revision/evidence/{relative}", exists=False
            ),
            content,
        )
    _publish(intent_path, intent)
    _checkpoint("after_intent")
    expected_pair = dict(before)
    for label, relative in _targets(version):
        # Track every exact owned write while preserving all other authority hashes.
        if any(sha256_file(_file(root, path)) != digest for path, digest in expected_pair.items()):
            raise ValueError("paired baseline changed between canonical writes")
        if any(sha256_file(_file(root, path)) != expected_pair.get(path, digest)
               for path, digest in evidence.items()):
            raise ValueError("paired authority changed between canonical writes")
        validate_modeling_binding(
            root, paired, SceneSpec.model_validate(binding["candidate_scene_spec"]),
            metadata_after_sha256=attachment["metadata_after_sha256"] if attachment else None,
        )
        if (
            geometry_dependency_hashes(
                root, SceneSpec.model_validate(binding["candidate_scene_spec"])
            )
            != binding["geometry_dependencies"]
        ):
            raise ValueError("paired geometry payload closure changed during transaction")
        _cas(root, workflow_id, relative, before[relative], after_content[relative])
        expected_pair[relative] = after[relative]
        _checkpoint(f"after_{label}")
    _load_intent(root, workflow_id)
    if any(sha256_file(_file(root, relative)) != digest for relative, digest in after.items()):
        raise ValueError("paired post-apply canonical hashes changed")
    validate_modeling_binding(
        root, paired, SceneSpec.model_validate_json(_file(root, SCENE_PATH).read_bytes()),
        metadata_after_sha256=attachment["metadata_after_sha256"] if attachment else None,
    )
    _checkpoint("after_validation")
    if (
        geometry_dependency_hashes(root, SceneSpec.model_validate(binding["candidate_scene_spec"]))
        != binding["geometry_dependencies"]
    ):
        raise ValueError("paired geometry payload closure changed before commit")
    receipt = {
        "schema_version": version,
        "status": "committed",
        "intent_sha256": sha256_file(intent_path),
        "after": after,
    }
    _checkpoint("before_receipt")
    _load_intent(root, workflow_id)
    if any(sha256_file(_file(root, relative)) != digest for relative, digest in after.items()):
        raise ValueError("paired canonical output changed at commit boundary")
    if (
        geometry_dependency_hashes(root, SceneSpec.model_validate(binding["candidate_scene_spec"]))
        != binding["geometry_dependencies"]
    ):
        raise ValueError("paired geometry payload changed at commit boundary")
    validate_modeling_binding(
        root, paired, SceneSpec.model_validate(binding["candidate_scene_spec"]),
            metadata_after_sha256=attachment["metadata_after_sha256"] if attachment else None,
    )
    if attachment is not None:
        from .attachment_revision import validate_attachment_binding

        validate_attachment_binding(root, workflow_id, binding)
        # Full proofs can be expensive: recheck every bound byte after they finish.
        validate_modeling_binding(
            root, paired, SceneSpec.model_validate(binding["candidate_scene_spec"]),
            metadata_after_sha256=attachment["metadata_after_sha256"],
        )
        _load_intent(root, workflow_id)
        if any(sha256_file(_file(root, path)) != digest for path, digest in after.items()):
            raise ValueError("attachment canonical output changed during final proof")
        if geometry_dependency_hashes(
            root, SceneSpec.model_validate(binding["candidate_scene_spec"])
        ) != binding["geometry_dependencies"]:
            raise ValueError("attachment geometry changed during final proof")
    _publish(transaction_path(root, workflow_id, "receipt.json"), receipt)
    _checkpoint("after_receipt")
    return receipt


def recover_pair(root: Path, workflow_id: str, intent_sha256: str) -> dict[str, Any]:
    """Restore exact owned bytes; interrupted rollback may resume without replay."""

    _require_scene_spec_lock_owner(root, root.name, workflow_id)
    intent = _load_intent(root, workflow_id, intent_sha256)
    if (
        transaction_path(root, workflow_id, "receipt.json").exists()
        or transaction_path(root, workflow_id, "rollback.json").exists()
    ):
        raise FileExistsError("paired transaction is already terminal; recovery replay forbidden")
    _publish(
        transaction_path(root, workflow_id, "recovery_started.json"),
        {"intent_sha256": intent_sha256},
    )
    _checkpoint("recovery_started")
    for prefix, relative in _targets(intent["schema_version"]):
        current = sha256_file(_file(root, relative))
        if current not in {intent["before"][relative], intent["after"][relative]}:
            raise ValueError("paired recovery refuses to replace concurrent user edits")
        archive = transaction_path(root, workflow_id, f"{prefix}.before.json")
        content = archive.read_bytes()
        if hashlib.sha256(content).hexdigest() != intent["before"][relative]:
            raise ValueError("paired recovery archive changed")
        if current != intent["before"][relative]:
            _cas(root, workflow_id, relative, current, content)
        _publish(
            transaction_path(root, workflow_id, f"{prefix}.restored.json"),
            {"intent_sha256": intent_sha256, "sha256": intent["before"][relative]},
        )
        _checkpoint(f"recovery_after_{prefix}")
    if any(
        sha256_file(_file(root, relative)) != digest
        for relative, digest in intent["before"].items()
    ):
        raise ValueError("paired restored files changed before rollback receipt")
    receipt = {
        "schema_version": intent["schema_version"],
        "status": "rolled_back",
        "intent_sha256": intent_sha256,
        "before": intent["before"],
    }
    _publish(transaction_path(root, workflow_id, "rollback.json"), receipt)
    return receipt


def publish_revision_diff(root: Path, workflow_id: str, report: dict[str, Any]) -> None:
    """Publish only this transaction's derived report while preserving any prior report bytes."""

    intent = _load_intent(root, workflow_id)
    path = _file(root, "reports/revision_diff.json", exists=False)
    content = deterministic_json_bytes(report)
    if path.exists() and _file(root, "reports/revision_diff.json").read_bytes() == content:
        return
    if intent["report_before_sha256"] is None:
        publish_bytes_create_once(path, content)
    else:
        _cas(
            root, workflow_id, "reports/revision_diff.json", intent["report_before_sha256"], content
        )
