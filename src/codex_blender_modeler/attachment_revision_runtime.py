"""Standard-library-only, fail-closed attachment revision history checks for Blender."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .attachment_runtime import artifact_bytes
from .solid_attachment_contract import validate_solid_root_contract

TARGETS = {
    "scene": "analysis/scene_spec.json",
    "model": "analysis/modeling_plan.json",
    "job": "job.json",
}
MAX_REVISIONS = 64


def _sha(content: bytes) -> str:
    """Hash physical archived bytes rather than normalized historical canonical files."""
    return hashlib.sha256(content).hexdigest()


def _stable(value: Any) -> str:
    """Mirror the host approval fingerprint's deterministic standard-library encoding."""
    return _sha(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    )


def _bytes(value: Any) -> bytes:
    """Mirror the host's stable physical JSON publication without importing orchestration."""
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def _read(root: Path, relative: str) -> bytes:
    """Read bounded ordinary transaction evidence through the shared containment guard."""
    from .paired_revision_runtime import _file

    path = _file(root, relative)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("attachment revision evidence exceeds byte limit")
    with path.open("rb") as stream:
        content = stream.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise ValueError("attachment revision evidence grew past byte limit")
    return content


def _workflow(value: str) -> str:
    """Reject foreign path syntax before resolving a workflow-owned record."""
    if not isinstance(value, str) or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value) is None:
        raise ValueError("attachment revision workflow identity is invalid")
    return f"workflows/{value}"


def _step_fingerprint(
    plan: dict, request: dict, step: dict, dependencies: dict, plan_hash: str, binding_hash: str
) -> str:
    """Recompute only the fixed author/approval inputs selected by this narrow route."""
    parameters = step["parameters"]
    if (
        "expected_modeling_plan_sha256" in parameters
        or "expected_assembly_consistency_policy" in parameters
    ):
        raise ValueError("attachment author/approval has unexpected mutable inputs")
    value = {
        "plan_sha256": plan_hash,
        "request_sha256": plan["request_sha256"],
        "step_id": step["step_id"],
        "parameters": parameters,
        "dependencies": {key: dependencies[key] for key in step["depends_on"]},
        "primary_reference_sha256": (
            request["primary_reference"]["sha256"] if request.get("primary_reference") else None
        ),
    }
    if parameters.get("bind_revision_geometry_payloads") is not True:
        raise ValueError("attachment revision omitted exact geometry payload binding")
    if step["step_id"] != "revision.author":
        value["revision_payload_binding_sha256"] = binding_hash
    return _stable(value)


def _historical_geometry(root: Path, document: dict, archived: dict[str, bytes]) -> None:
    """Rehash the complete retained geometry closure, using archives for historical canonicals."""
    pending = list(document["source_geometry"])
    visited = {}
    folded = {}
    total_bytes = 0
    while pending:
        artifact = pending.pop()
        path, digest = artifact["path"], artifact["sha256"]
        if path in visited:
            if visited[path] != digest:
                raise ValueError("attachment historical geometry has inconsistent source hashes")
            continue
        if len(visited) >= 512 or (path.casefold() in folded and folded[path.casefold()] != path):
            raise ValueError("attachment historical geometry exceeds bounded unique closure")
        visited[path], folded[path.casefold()] = digest, path
        if path in archived:
            content = archived[path]
            if _sha(content) != digest:
                raise ValueError("attachment historical canonical dependency differs from archive")
        else:
            content = artifact_bytes(root, artifact)
        total_bytes += len(content)
        if total_bytes > 64 * 1024 * 1024:
            raise ValueError("attachment historical geometry closure exceeds byte limit")
        try:
            raw = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(raw, dict) or "source_hashes" not in raw:
            continue
        sources = raw["source_hashes"]
        if not isinstance(sources, list) or _stable(sources) != raw.get(
            "source_fingerprint_sha256"
        ):
            raise ValueError("attachment historical geometry source fingerprint changed")
        for source in sources:
            if not isinstance(source, dict) or set(source) not in (
                {"path", "sha256"},
                {"role", "path", "sha256"},
            ):
                raise ValueError("attachment historical geometry dependency is malformed")
            pending.append({"path": source["path"], "sha256": source["sha256"]})


def validate_revision_transaction(
    root: Path, workflow_id: str, *, require_committed: bool = True
) -> dict:
    """Validate exact three-file archives, cycle-free record and original guarded approval chain."""
    prefix = _workflow(workflow_id)
    transaction = f"{prefix}/paired_revision"
    intent_bytes = _read(root, f"{transaction}/intent.json")
    intent = json.loads(intent_bytes)
    if set(intent) != {
        "schema_version",
        "job_id",
        "workflow_id",
        "binding_sha256",
        "before",
        "after",
        "evidence",
        "report_before_sha256",
    } or (
        intent["schema_version"] != "0.2.0"
        or intent["job_id"] != root.name
        or intent["workflow_id"] != workflow_id
    ):
        raise ValueError("attachment revision transaction identity or fields changed")
    archives = {}
    for direction in ("before", "after"):
        if set(intent[direction]) != set(TARGETS.values()):
            raise ValueError("attachment transaction must archive exactly scene/model/job")
        archives[direction] = {}
        for label, path in TARGETS.items():
            content = _read(root, f"{transaction}/{label}.{direction}.json")
            if _sha(content) != intent[direction][path]:
                raise ValueError("attachment transaction archive hash changed")
            archives[direction][path] = content
    if (
        intent["report_before_sha256"] is not None
        and _sha(_read(root, f"{transaction}/report.before.json")) != intent["report_before_sha256"]
    ):
        raise ValueError("attachment archived prior report changed")
    mandatory = {
        "analysis/revision_plan.json",
        "analysis/modeling_plan.json",
        f"{prefix}/plan.json",
        f"{prefix}/request.json",
        f"{prefix}/artifacts/revision_payload_binding.json",
        f"{prefix}/completions/revision.author.json",
        f"{prefix}/approvals/revision.approval.json",
    }
    if set(intent["evidence"]) != mandatory:
        raise ValueError("attachment transaction authority inventory changed")
    evidence = {}
    for path, digest in intent["evidence"].items():
        content = artifact_bytes(root, {"path": f"{transaction}/evidence/{path}", "sha256": digest})
        if path.startswith(prefix + "/"):
            artifact_bytes(root, {"path": path, "sha256": digest})
        evidence[path] = json.loads(content)
    binding = evidence[f"{prefix}/artifacts/revision_payload_binding.json"]
    if (
        intent["binding_sha256"]
        != intent["evidence"][f"{prefix}/artifacts/revision_payload_binding.json"]
    ):
        raise ValueError("attachment approval binding hash differs")
    if (
        set(binding)
        != {
            "job_id",
            "base_spec_sha256",
            "revision_plan_sha256",
            "candidate_scene_spec",
            "geometry_dependencies",
            "paired_modeling_plan",
            "attachment_revision",
        }
        or binding["job_id"] != root.name
    ):
        raise ValueError("attachment payload binding fields or job changed")
    companion, pair = binding["attachment_revision"], binding["paired_modeling_plan"]
    if (
        set(companion)
        != {
            "schema_version",
            "revision",
            "record",
            "metadata_after_sha256",
            "source_preflight",
            "float32_preflight",
        }
        or companion["schema_version"] != "0.1.0"
    ):
        raise ValueError("attachment revision companion changed")
    record = json.loads(artifact_bytes(root, companion["revision"]))
    if set(record) != {
        "schema_version",
        "kind",
        "job_id",
        "workflow_id",
        "initial_registration",
        "previous_revision",
        "previous_intent",
        "candidate_intent",
        "metadata_before_sha256",
    } or (
        record["schema_version"] != "0.1.0"
        or record["kind"] != "solid_root_attachment_revision"
        or record["job_id"] != root.name
        or record["workflow_id"] != workflow_id
        or record != companion["record"]
        or companion["revision"]["path"]
        != f"production/surface_attachment/revisions/{workflow_id}/revision.json"
        or companion["revision"]["sha256"] != _sha(_bytes(record))
    ):
        raise ValueError("attachment immutable revision record changed")
    before, after = (json.loads(archives[key]["job.json"]) for key in ("before", "after"))
    expected_after = dict(before)
    expected_after["attachment_revision"] = companion["revision"]
    if (
        _bytes(expected_after) != archives["after"]["job.json"]
        or record["metadata_before_sha256"] != intent["before"]["job.json"]
        or companion["metadata_after_sha256"] != intent["after"]["job.json"]
        or before.get("job_id") != root.name
        or after.get("job_id") != root.name
        or before.get("attachment_revision") != record["previous_revision"]
        or record["initial_registration"]
        != {
            "path": "production/surface_attachment/registration.json",
            "sha256": before.get("attachment_registration_sha256"),
        }
        or pair["preserved_sources"]["job.json"] != intent["before"]["job.json"]
    ):
        raise ValueError("attachment transaction rewrote unauthorized metadata")
    registration = json.loads(artifact_bytes(root, record["initial_registration"]))
    if (
        registration.get("kind") != "solid_root_attachment_registration"
        or registration.get("job_id") != root.name
        or registration.get("attachment_intent") != before.get("attachment_intent")
    ):
        raise ValueError("attachment revision initial registration changed")
    old = json.loads(artifact_bytes(root, record["previous_intent"]))
    candidate = json.loads(artifact_bytes(root, record["candidate_intent"]))
    for document in (old, candidate):
        validate_solid_root_contract(document)
        if document["job_id"] != root.name:
            raise ValueError("attachment revision intent belongs to another job")
    for document in (old, candidate):
        for key in ("source_camera_hypothesis", "source_reference"):
            artifact_bytes(root, document[key])
    for path, digest in pair["preserved_sources"].items():
        if path == "job.json":
            if _sha(archives["before"][path]) != digest:
                raise ValueError("attachment historical metadata source differs from archive")
        else:
            artifact_bytes(root, {"path": path, "sha256": digest})
    _historical_geometry(root, old, archives["before"])
    _historical_geometry(root, candidate, archives["after"])
    for path, digest in binding["geometry_dependencies"].items():
        if path in archives["after"]:
            if _sha(archives["after"][path]) != digest:
                raise ValueError("attachment archived candidate dependency changed")
        else:
            artifact_bytes(root, {"path": path, "sha256": digest})
    mutable = {"source_scene", "source_modeling_plan", "source_geometry"}
    if _stable({k: v for k, v in old.items() if k not in mutable}) != _stable(
        {k: v for k, v in candidate.items() if k not in mutable}
    ):
        raise ValueError("attachment revision changed immutable root/domain intent")
    for key, path in (
        ("source_scene", "analysis/scene_spec.json"),
        ("source_modeling_plan", "analysis/modeling_plan.json"),
    ):
        if old[key] != {"path": path, "sha256": intent["before"][path]} or candidate[key] != {
            "path": path,
            "sha256": intent["after"][path],
        }:
            raise ValueError("attachment historical intent differs from archived source bytes")
    if (
        binding["base_spec_sha256"] != intent["before"]["analysis/scene_spec.json"]
        or _sha(_bytes(binding["candidate_scene_spec"]))
        != intent["after"]["analysis/scene_spec.json"]
        or pair["base_modeling_plan_sha256"] != intent["before"]["analysis/modeling_plan.json"]
        or pair["candidate_sha256"] != intent["after"]["analysis/modeling_plan.json"]
        or intent["evidence"]["analysis/revision_plan.json"] != binding["revision_plan_sha256"]
        or intent["evidence"]["analysis/modeling_plan.json"] != pair["base_modeling_plan_sha256"]
        or any(
            companion[key].get("status") != "passed"
            for key in ("source_preflight", "float32_preflight")
        )
    ):
        raise ValueError("attachment approved prospective source/proof binding changed")
    from .paired_revision_runtime import _validate_contract

    request, plan, completion, approval = [
        evidence[f"{prefix}/{path}"]
        for path in (
            "request.json",
            "plan.json",
            "completions/revision.author.json",
            "approvals/revision.approval.json",
        )
    ]
    for name, document in zip(
        ("workflow_request", "workflow_plan", "workflow_step_completion", "workflow_approval"),
        (request, plan, completion, approval),
        strict=True,
    ):
        _validate_contract(name, document)
    for document in (request, plan, completion, approval):
        if (
            document.get("schema_version") != "0.8.0"
            or document.get("job_id") != root.name
            or document.get("workflow_id") != workflow_id
        ):
            raise ValueError("attachment authority has foreign identity")
    if (
        request.get("execution_policy") != "standard"
        or request.get("revision_strategy") != "manual_guarded"
        or request.get("intent_hint") != "revise_asset"
        or request.get("attachment_intent_path") != record["candidate_intent"]["path"]
        or request.get("attachment_intent_sha256") != record["candidate_intent"]["sha256"]
        or request.get("paired_modeling_plan_path") != pair["candidate_path"]
        or request.get("paired_modeling_plan_sha256") != pair["candidate_sha256"]
        or plan.get("request_sha256") != intent["evidence"][f"{prefix}/request.json"]
        or completion.get("plan_sha256") != intent["evidence"][f"{prefix}/plan.json"]
        or approval.get("plan_sha256") != completion["plan_sha256"]
        or completion.get("step_id") != "revision.author"
        or approval.get("step_id") != "revision.approval"
        or approval.get("status") != "approved"
        or approval.get("gate") != "detailed_geometry"
    ):
        raise ValueError("attachment exact request/author/approval binding changed")
    steps = {step["step_id"]: step for step in plan["steps"]}
    author_step, approval_step = steps["revision.author"], steps["revision.approval"]
    if author_step["depends_on"] != [] or approval_step["depends_on"] != ["revision.author"]:
        raise ValueError("attachment guarded author/approval dependencies changed")
    for step in (author_step, approval_step, steps["revision.apply"]):
        if (
            step["parameters"].get("attachment_metadata_before_sha256")
            != record["metadata_before_sha256"]
        ):
            raise ValueError("attachment planned original metadata changed")
        for key in (
            "paired_modeling_plan_path",
            "paired_modeling_plan_sha256",
            "attachment_intent_path",
            "attachment_intent_sha256",
        ):
            if step["parameters"].get(key) != request[key]:
                raise ValueError("attachment plan differs from exact request")
    artifacts = completion["output_artifacts"]
    if completion["output_fingerprint"] != _stable(
        [
            {key: item[key] for key in ("artifact_id", "path", "sha256", "integrity")}
            for item in artifacts
        ]
    ):
        raise ValueError("attachment author output fingerprint changed")
    required_outputs = {
        "revision.payload_binding": (
            f"{prefix}/artifacts/revision_payload_binding.json",
            intent["binding_sha256"],
        ),
        "revision.candidate_modeling_plan": (pair["candidate_path"], pair["candidate_sha256"]),
        "revision.candidate_attachment_intent": (
            record["candidate_intent"]["path"],
            record["candidate_intent"]["sha256"],
        ),
    }
    for key, (path, digest) in required_outputs.items():
        found = [item for item in artifacts if item["artifact_id"] == key]
        if (
            len(found) != 1
            or found[0]["path"] != path
            or found[0]["sha256"] != digest
            or found[0]["integrity"] != "valid"
        ):
            raise ValueError("attachment author omitted exact candidate evidence")
    author_fingerprint = _stable(
        {
            "input": completion["input_fingerprint"],
            "output": completion["output_fingerprint"],
            "completion_id": completion["completion_id"],
        }
    )
    if completion["input_fingerprint"] != _step_fingerprint(
        plan, request, author_step, {}, completion["plan_sha256"], intent["binding_sha256"]
    ) or approval["artifact_fingerprint"] != _step_fingerprint(
        plan,
        request,
        approval_step,
        {"revision.author": author_fingerprint},
        completion["plan_sha256"],
        intent["binding_sha256"],
    ):
        raise ValueError("attachment original approval fingerprint changed")
    if require_committed:
        receipt = json.loads(_read(root, f"{transaction}/receipt.json"))
        if (
            receipt
            != {
                "schema_version": "0.2.0",
                "status": "committed",
                "intent_sha256": _sha(intent_bytes),
                "after": intent["after"],
            }
            or (root / transaction / "rollback.json").exists()
        ):
            raise ValueError("attachment transaction has no exact committed receipt")
    return {
        "record": record,
        "revision": companion["revision"],
        "intent": intent,
        "archives": archives,
    }


def completed_attachment_transactions(root: Path) -> dict[str, dict]:
    """Block pending journals before selection, including absent metadata or stale-tip rollback."""
    from .authored_split_runtime import completed_authored_transactions
    from .paired_revision_runtime import assert_no_pending_pair

    specialized = completed_authored_transactions(root)
    workflows = root / "workflows"
    if workflows.is_symlink():
        raise ValueError("attachment workflows are linked")
    if not workflows.exists():
        return specialized
    paths = []
    for path in workflows.glob("*/paired_revision/intent.json"):
        if len(paths) >= 4096:
            raise ValueError("attachment transaction inventory exceeds bounded limit")
        paths.append(path)
    assert_no_pending_pair(root)
    committed = dict(specialized)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        content = _read(root, relative)
        intent = json.loads(content)
        prefix = path.parent.relative_to(root).as_posix()
        version = intent.get("schema_version")
        if version not in {"0.1.0", "0.2.0"}:
            raise ValueError("unknown paired transaction version")
        receipt_path, rollback_path = (
            root / prefix / "receipt.json",
            root / prefix / "rollback.json",
        )
        receipt = (
            json.loads(_read(root, f"{prefix}/receipt.json"))
            if receipt_path.exists() or receipt_path.is_symlink()
            else None
        )
        rollback = (
            json.loads(_read(root, f"{prefix}/rollback.json"))
            if rollback_path.exists() or rollback_path.is_symlink()
            else None
        )
        if (receipt is None) == (rollback is None):
            raise ValueError("paired revision transaction is incomplete or conflicting")
        terminal, direction, status = (
            (receipt, "after", "committed") if receipt else (rollback, "before", "rolled_back")
        )
        if terminal != {
            "schema_version": version,
            "status": status,
            "intent_sha256": _sha(content),
            direction: intent[direction],
        }:
            raise ValueError("paired revision transaction terminal hash changed")
        if version == "0.2.0":
            checked = validate_revision_transaction(
                root, path.parent.parent.name, require_committed=receipt is not None
            )
            if receipt is not None:
                if path.parent.parent.name in committed:
                    raise ValueError("attachment mixed-authority chain identity collision")
                committed[path.parent.parent.name] = checked
    return committed


def select_revised_attachment(
    root: Path, metadata: dict, initial: dict, committed: dict[str, dict]
) -> dict:
    """Follow only an explicit bounded chain and reject forks, missing records or older tips."""
    pointer = metadata.get("attachment_revision")
    if pointer is None:
        if "attachment_revision" in metadata or committed:
            raise ValueError("attachment committed revision pointer is missing")
        return initial
    seen, candidate, current = set(), None, pointer
    while current is not None:
        record = json.loads(artifact_bytes(root, current))
        workflow_id = record.get("workflow_id")
        if workflow_id in seen or len(seen) >= MAX_REVISIONS or workflow_id not in committed:
            raise ValueError("attachment revision chain is cyclic, excessive or uncommitted")
        seen.add(workflow_id)
        checked = committed[workflow_id]
        if checked["revision"] != current or record != checked["record"]:
            raise ValueError("attachment revision chain record differs from committed authority")
        if record["initial_registration"] != {
            "path": "production/surface_attachment/registration.json",
            "sha256": metadata["attachment_registration_sha256"],
        }:
            raise ValueError("attachment revision changed initial registration")
        if candidate is None:
            candidate = record["candidate_intent"]
            if any(
                _sha(_read(root, path)) != digest
                for path, digest in checked["intent"]["after"].items()
                if path in TARGETS.values()
            ):
                raise ValueError(
                    "attachment current canonical sources differ from committed revision"
                )
            if _sha(_read(root, "job.json")) != checked["intent"]["after"]["job.json"]:
                raise ValueError(
                    "attachment current metadata differs from exact committed revision"
                )
        previous = record["previous_revision"]
        if previous is None:
            if record["previous_intent"] != initial:
                raise ValueError("attachment revision chain omits initial intent")
        else:
            predecessor = json.loads(artifact_bytes(root, previous))
            if record["previous_intent"] != predecessor.get("candidate_intent"):
                raise ValueError("attachment revision predecessor selection differs")
        current = previous
    if seen != set(committed):
        raise ValueError("attachment revision chain omits a committed successor or contains a fork")
    return candidate
