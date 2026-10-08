"""Dependency-light, read-only paired transaction checks shared with Blender Python.

This module grants no write, recovery, approval, or execution authority. It reads only
versioned existing host evidence and the generated schemas shipped with this source.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .blender_artifacts import (
    deterministic_json_bytes,
    native_io_path,
    sha256_file,
    stable_json_digest,
)

SCENE_PATH = "analysis/scene_spec.json"
MODEL_PATH = "analysis/modeling_plan.json"
_SCHEMA_NAMES = frozenset(
    {
        "workflow_request",
        "workflow_plan",
        "workflow_step_completion",
        "workflow_approval",
        "workflow_attempt",
        "attachment_revision_transaction_intent_v02",
        "attachment_revision_commit_receipt_v02",
        "attachment_revision_rollback_receipt_v02",
        "paired_revision_transaction_intent",
        "paired_revision_commit_receipt",
        "paired_revision_rollback_receipt",
    }
)
_SCHEMA_KEYWORDS = frozenset(
    {
        "$defs",
        "$ref",
        "additionalProperties",
        "anyOf",
        "const",
        "default",
        "description",
        "enum",
        "format",
        "items",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "maxItems",
        "minLength",
        "minProperties",
        "minimum",
        "pattern",
        "properties",
        "propertyNames",
        "required",
        "title",
        "type",
    }
)


class _Envelope(dict):
    """Expose already-validated JSON keys as attributes without host model imports."""

    def __getattr__(self, name: str) -> Any:
        """Return only declared JSON fields; no evaluation or dynamic imports occur."""

        try:
            return self[name]
        except KeyError as exc:
            raise ValueError(f"paired runtime contract field is missing: {name}") from exc


def _envelope(value: Any) -> Any:
    """Wrap parsed dictionaries while preserving their exact JSON hashing behavior."""

    if isinstance(value, dict):
        return _Envelope({key: _envelope(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_envelope(item) for item in value]
    return value


def _semantic_check(name: str, value: Any) -> None:
    """Preserve the host envelopes' non-schema invariants at this read-only boundary."""

    if not isinstance(value, dict):
        return
    if name in {"WorkflowRequest", "WorkflowPlan"}:
        if value.get("execution_policy", "standard") != "standard":
            raise ValueError("paired runtime requires the Standard workflow contract")
        if (
            value.get("reference_content_scope") == "primary_object_only"
            and value.get("target_subject") is None
        ):
            raise ValueError("paired runtime primary-object scope requires a target subject")
    if name == "WorkflowRequest":
        if (
            value.get("intent_hint") != "revise_asset"
            or value.get("revision_strategy") != "manual_guarded"
            or value.get("paired_modeling_plan_path") is None
            or value.get("paired_modeling_plan_sha256") is None
            or value.get("background_preview_binding") is not None
            or value.get("fast_quality_policy") is not None
        ):
            raise ValueError("paired runtime request is not an explicit Standard manual revision")
        staged = value.get("staged_view")
        if staged is not None and staged.get("kind") == "reference":
            raise ValueError("paired runtime auxiliary view cannot replace the primary reference")
        if value.get("replace_existing_view") and staged is None:
            raise ValueError("paired runtime view replacement requires a staged view")
        if value.get("include_destination_handoff") and value.get("profile_id") == "obj_legacy":
            raise ValueError("paired runtime destination handoff profile is unsupported")
    elif name == "WorkflowPlan":
        if value.get("intent") != "revise_asset" or value.get("fast_quality_policy") is not None:
            raise ValueError("paired runtime plan intent or Standard quality policy changed")
        seen = set()
        for step in value["steps"]:
            if step["step_id"] in seen or set(step.get("depends_on", [])) - seen:
                raise ValueError("paired runtime plan is not an ordered unique DAG")
            seen.add(step["step_id"])
        if value["terminal_step_id"] not in seen:
            raise ValueError("paired runtime terminal step is missing")
    elif name == "WorkflowStep":
        mode = value["execution_mode"]
        approval = value.get("approval_gate")
        if (mode in {"approval", "specialized_approval"}) != (approval is not None) or (
            mode == "host" and not value.get("tool_name")
        ):
            raise ValueError("paired runtime execution boundary changed")
    elif name == "ArtifactRequirement":
        source = value.get("source_path")
        if value.get("lifecycle", "canonical") == "workflow_snapshot":
            if source is None or source == value["path"] or value.get("canonical"):
                raise ValueError("paired runtime snapshot lifecycle changed")
        elif source is not None:
            raise ValueError("paired runtime artifact source requires a snapshot")
    elif name == "WorkflowAttempt":
        status = value["status"]
        if status == "running" and any(
            value.get(key)
            for key in ("completed_at", "output_fingerprint", "error_type", "error_message")
        ):
            raise ValueError("paired running attempt contains completion evidence")
        if status == "succeeded" and (
            value.get("output_fingerprint") is None
            or value.get("completed_at") is None
            or value.get("error_type")
            or value.get("error_message")
        ):
            raise ValueError("paired successful attempt lacks clean terminal evidence")
        if status == "failed" and (
            not value.get("error_type")
            or not value.get("error_message")
            or value.get("completed_at") is None
        ):
            raise ValueError("paired failed attempt lacks terminal error evidence")
    elif name == "DestinationRequest":
        if (value["kind"] == "custom") != bool(value.get("name")):
            raise ValueError("paired runtime destination name is inconsistent")
    elif name == "DestinationResolution":
        if (value["status"] == "available" and not value.get("adapter_id")) or (
            value["status"] != "available" and value.get("adapter_id") is not None
        ):
            raise ValueError("paired runtime destination adapter is inconsistent")


def _schema_check(value: Any, schema: dict[str, Any], document: dict[str, Any]) -> None:
    """Validate only the finite JSON Schema subset emitted for these fixed read contracts."""

    if set(schema) - _SCHEMA_KEYWORDS:
        raise ValueError("paired runtime schema contains unsupported validation keywords")
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
            raise ValueError("paired runtime schemas permit only local definition references")
        name = reference.removeprefix("#/$defs/")
        if "/" in name or "~" in name or name not in document.get("$defs", {}):
            raise ValueError("paired runtime schema reference is invalid")
        _schema_check(value, document["$defs"][name], document)
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                _schema_check(value, branch, document)
                break
            except ValueError:
                pass
        else:
            raise ValueError("paired runtime value matches no declared schema variant")
    expected = schema.get("type")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "null": value is None,
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value),
    }
    if expected is not None and (expected not in valid or not valid[expected]):
        raise ValueError("paired runtime value has an invalid schema type")
    if "const" in schema and value != schema["const"]:
        raise ValueError("paired runtime contract version or constant changed")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("paired runtime contract enum is unknown")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - set(value):
            raise ValueError("paired runtime contract fields are missing")
        if len(value) < schema.get("minProperties", 0) or len(value) > schema.get(
            "maxProperties", math.inf
        ):
            raise ValueError("paired runtime object inventory changed")
        for name, item in value.items():
            if "propertyNames" in schema:
                _schema_check(name, schema["propertyNames"], document)
            if name in properties:
                _schema_check(item, properties[name], document)
            elif schema.get("additionalProperties") is False:
                raise ValueError("paired runtime contract has unknown fields")
            elif isinstance(schema.get("additionalProperties"), dict):
                _schema_check(item, schema["additionalProperties"], document)
            if (name == "path" or name.endswith("_path")) and isinstance(item, str):
                _relative(item)
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            raise ValueError("paired runtime array inventory is outside its bound")
        if "items" in schema:
            for item in value:
                _schema_check(item, schema["items"], document)
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get(
            "maxLength", math.inf
        ):
            raise ValueError("paired runtime string length is invalid")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ValueError("paired runtime string pattern is invalid")
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("paired runtime timestamp is invalid") from exc
        elif "format" in schema:
            raise ValueError("paired runtime schema format is unsupported")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if (
            not math.isfinite(value)
            or value < schema.get("minimum", -math.inf)
            or value > schema.get("maximum", math.inf)
        ):
            raise ValueError("paired runtime numeric bound is invalid")
    _semantic_check(str(schema.get("title", "")), value)


def _validate_contract(name: str, value: Any) -> None:
    """Load only an allowlisted generated local schema and validate one reader envelope."""

    if name not in _SCHEMA_NAMES:
        raise ValueError("unknown paired runtime reader contract")
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / f"{name}.schema.json"
    document = json.loads(schema_path.read_text(encoding="utf-8"))
    _schema_check(value, document, document)


def _load_contract(name: str, content: bytes) -> _Envelope:
    """Strictly validate host JSON without importing Pydantic or orchestration services."""

    value = json.loads(content)
    _validate_contract(name, value)
    return _envelope(value)


def _relative(value: str) -> None:
    """Reject non-normalized, escaped, absolute and platform-alternate artifact paths."""

    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("paired runtime artifact path must be normalized job-relative text")


def _contained(root: Path, path: Path, *, must_exist: bool) -> Path:
    """Match host lexical containment and reject every symlink or reparse ancestor."""

    owner = Path(os.path.abspath(os.fspath(root)))
    target = Path(os.path.abspath(os.fspath(path)))
    relative = target.relative_to(owner)
    if not os.path.isdir(native_io_path(owner)):
        raise ValueError("paired runtime job root is missing")
    current = owner
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        if os.path.lexists(native_io_path(current)):
            metadata = os.lstat(native_io_path(current))
            if stat.S_ISLNK(metadata.st_mode) or getattr(
                metadata, "st_file_attributes", 0
            ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError("paired runtime path traverses a symlink or reparse point")
    target.resolve(strict=False).relative_to(owner.resolve(strict=True))
    if must_exist and not os.path.exists(native_io_path(target)):
        raise FileNotFoundError(target)
    return target


def _file(root: Path, relative: str, *, exists: bool = True) -> Path:
    """Resolve a strict job-owned artifact without weakening the host path boundary."""

    _relative(relative)
    path = _contained(root, root / relative, must_exist=exists)
    if exists and not os.path.isfile(native_io_path(path)):
        raise ValueError("paired runtime artifact is not a regular file")
    return path


def transaction_path(root: Path, workflow_id: str, name: str) -> Path:
    """Locate only fixed transaction evidence for one exact workflow identity."""

    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", workflow_id) is None:
        raise ValueError("paired runtime workflow identity is invalid")
    if name not in {
        "intent.json",
        "receipt.json",
        "rollback.json",
        "scene.before.json",
        "model.before.json",
        "scene.after.json",
        "model.after.json",
        "report.before.json",
        "job.before.json",
        "job.after.json",
    }:
        raise ValueError("unknown paired runtime transaction artifact")
    return _file(root, f"workflows/{workflow_id}/paired_revision/{name}", exists=False)


def binding_path(root: Path, workflow_id: str) -> Path:
    """Read this workflow's fixed immutable candidate binding only."""

    return _file(root, f"workflows/{workflow_id}/artifacts/revision_payload_binding.json")


def _artifact_fingerprint(artifacts: list[_Envelope]) -> str:
    """Match the exact host artifact identity, hash and integrity fingerprint."""

    return stable_json_digest(
        [
            {
                "artifact_id": item.artifact_id,
                "path": item.path,
                "sha256": item.get("sha256"),
                "integrity": item.integrity,
            }
            for item in artifacts
        ]
    )


def _step_input_fingerprint(
    root: Path, plan: _Envelope, request: _Envelope, step: _Envelope, states: dict[str, Any]
) -> str:
    """Recreate only the three exact approval-chain fingerprints read by this guard."""

    if step.step_id not in {"revision.author", "revision.approval", "revision.apply"}:
        raise ValueError("unsupported paired runtime authority step")
    payload = {
        "plan_sha256": sha256_file(_file(root, f"workflows/{plan.workflow_id}/plan.json")),
        "request_sha256": plan.request_sha256,
        "step_id": step.step_id,
        "parameters": step.parameters,
        "dependencies": {key: states[key].completion_fingerprint for key in step.depends_on},
        "primary_reference_sha256": request.primary_reference.sha256
        if request.get("primary_reference")
        else None,
    }
    if step.parameters.get("expected_modeling_plan_sha256") is not None:
        if step.step_id != "revision.apply":
            raise ValueError("unsupported paired runtime pre-apply source contract")
        payload["current_modeling_plan_sha256"] = step.parameters["expected_modeling_plan_sha256"]
    if (
        step.parameters.get("bind_revision_geometry_payloads") is True
        and step.step_id != "revision.author"
    ):
        payload["revision_payload_binding_sha256"] = sha256_file(
            binding_path(root, plan.workflow_id)
        )
    return stable_json_digest(payload)


def _read_evidence(path: Path, *, bounded: bool = True) -> bytes:
    """Bound new attachment evidence reads while preserving legacy large source archives."""
    if not bounded:
        return path.read_bytes()
    limit = 8 * 1024 * 1024
    if path.stat().st_size > limit:
        raise ValueError("attachment transaction evidence exceeds byte limit")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError("attachment transaction evidence grew beyond byte limit")
    return content


def _load_intent(root: Path, workflow_id: str, expected: str | None = None) -> dict[str, Any]:
    """Read exact immutable intent and verify all archived before/after byte hashes."""

    path = transaction_path(root, workflow_id, "intent.json")
    content = _read_evidence(path)
    if expected is not None and hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("paired recovery intent hash changed")
    value = json.loads(content)
    version = value.get("schema_version")
    _validate_contract(
        "attachment_revision_transaction_intent_v02"
        if version == "0.2.0"
        else "paired_revision_transaction_intent",
        value,
    )
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
    targets = (("scene", SCENE_PATH), ("model", MODEL_PATH)) + (
        (("job", "job.json"),) if version == "0.2.0" else ()
    )
    for direction in ("before", "after"):
        if set(value[direction]) != {relative for _, relative in targets}:
            raise ValueError("paired transaction target inventory changed")
        for prefix, relative in targets:
            archive = transaction_path(root, workflow_id, f"{prefix}.{direction}.json")
            archive_digest = (
                hashlib.sha256(_read_evidence(archive)).hexdigest()
                if version == "0.2.0"
                else sha256_file(archive)
            )
            if archive_digest != value[direction][relative]:
                raise ValueError("paired transaction archive bytes changed")

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
        archived[relative] = _read_evidence(artifact, bounded=version == "0.2.0")
    request = _load_contract("workflow_request", archived[f"{prefix}/request.json"])
    plan = _load_contract("workflow_plan", archived[f"{prefix}/plan.json"])
    completion = _load_contract(
        "workflow_step_completion", archived[f"{prefix}/completions/revision.author.json"]
    )
    approval = _load_contract(
        "workflow_approval", archived[f"{prefix}/approvals/revision.approval.json"]
    )
    binding = json.loads(
        _read_evidence(binding_path(root, workflow_id), bounded=version == "0.2.0")
    )
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
        from .attachment_revision_runtime import validate_revision_transaction

        revision = binding["attachment_revision"]
        expected_before["job.json"] = revision["record"]["metadata_before_sha256"]
        expected_after["job.json"] = revision["metadata_after_sha256"]
        validate_revision_transaction(root, workflow_id, require_committed=False)
    elif "attachment_revision" in binding or request.get("attachment_intent_path") is not None:
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
        completion.input_fingerprint
        != _step_input_fingerprint(root, plan, request, author_step, {})
        or completion.output_fingerprint != _artifact_fingerprint(completion.output_artifacts)
        or approval.artifact_fingerprint
        != _step_input_fingerprint(
            root,
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
    receipt = json.loads(_read_evidence(path))
    _validate_contract(
        "attachment_revision_commit_receipt_v02"
        if receipt.get("schema_version") == "0.2.0"
        else "paired_revision_commit_receipt",
        receipt,
    )
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

    from .authored_split_runtime import completed_authored_transactions

    attachment_commits = completed_authored_transactions(root)
    workflows = root / "workflows"
    if not workflows.exists():
        if attachment_commits:
            from .attachment_revision_runtime import select_revised_attachment

            metadata = json.loads(_read_evidence(_file(root, "job.json")))
            select_revised_attachment(
                root, metadata, metadata.get("attachment_intent"), attachment_commits
            )
        return
    _contained(root, workflows, must_exist=True)
    paths = []
    for path in workflows.glob("*/paired_revision/intent.json"):
        if len(paths) >= 4096:
            raise ValueError("paired transaction inventory exceeds bounded limit")
        paths.append(path)
    for path in paths:
        workflow_id = path.parent.parent.name
        _file(root, path.relative_to(root).as_posix())
        committed = committed_receipt(root, workflow_id)
        if committed is not None:
            bounded = committed["schema_version"] == "0.2.0"
            prefix = f"workflows/{workflow_id}"
            plan = _load_contract(
                "workflow_plan", _read_evidence(_file(root, f"{prefix}/plan.json"), bounded=bounded)
            )
            request = _load_contract(
                "workflow_request",
                _read_evidence(_file(root, f"{prefix}/request.json"), bounded=bounded),
            )
            approval = _load_contract(
                "workflow_approval",
                _read_evidence(
                    _file(root, f"{prefix}/approvals/revision.approval.json"), bounded=bounded
                ),
            )
            step = next(item for item in plan.steps if item.step_id == "revision.apply")
            approval_fingerprint = stable_json_digest(
                {"input": approval.artifact_fingerprint, "approval_id": approval.approval_id}
            )
            expected_input = _step_input_fingerprint(
                root,
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
                attempt = _load_contract(
                    "workflow_attempt",
                    _read_evidence(
                        _file(root, attempt_path.relative_to(root).as_posix()), bounded=bounded
                    ),
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
                        "revision.job_metadata": "job.json",
                    }.get(output.artifact_id)
                    if target is not None and output.sha256 != intent["after"][target]:
                        raise ValueError("paired host snapshot differs from committed pair")
                completed = True
            if not completed:
                # A commit interrupted before host completion still needs the exact live pair.
                committed_receipt(root, workflow_id, require_current=True)
            if intent["schema_version"] == "0.2.0":
                from .attachment_revision_runtime import validate_revision_transaction

                if workflow_id in attachment_commits:
                    raise ValueError("attachment mixed-authority chain identity collision")
                attachment_commits[workflow_id] = validate_revision_transaction(root, workflow_id)
            continue
        rollback = transaction_path(root, workflow_id, "rollback.json")
        if rollback.exists():
            record = json.loads(_read_evidence(rollback))
            _validate_contract(
                "attachment_revision_rollback_receipt_v02"
                if record.get("schema_version") == "0.2.0"
                else "paired_revision_rollback_receipt",
                record,
            )
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
    if attachment_commits:
        from .attachment_revision_runtime import select_revised_attachment

        metadata = json.loads(_read_evidence(_file(root, "job.json")))
        select_revised_attachment(
            root, metadata, metadata.get("attachment_intent"), attachment_commits
        )
