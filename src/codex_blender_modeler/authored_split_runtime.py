"""Stdlib-only verification of specialized authored-material identity split history.

This reader grants no write authority and never imports host/Pydantic or bpy code.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from .attachment_runtime import artifact_bytes, contained_file
from .blender_artifacts import native_io_path

PROFILE = "authored_material_registered_solid_root_user_only"
DELEGATED_PROFILE = "authored_material_registered_solid_root_delegated_technical"
BASE = "production/material_identity_split_authored"
TARGETS = {
    "scene": "analysis/scene_spec.json",
    "model": "analysis/modeling_plan.json",
    "job": "job.json",
    "blend": "blender/scene.blend",
}
SOURCE_PATHS = {*TARGETS.values(), "analysis/material_plan.json"}
MAX_BINARY_BYTES = 512 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
SCHEMAS = {
    "plan": "material_identity_split_authored_plan_v02",
    "record": "authored_split_attachment_record_v02",
    "preapproval": "material_identity_split_authored_preapproval_v02",
    "invariants": "material_identity_split_authored_invariants_v02",
    "request": "material_identity_split_authored_approval_request_v02",
    "approval": "material_identity_split_authored_approval_v02",
    "apply": "material_identity_split_authored_apply_intent_v02",
    "journal": "material_identity_split_authored_journal_v02",
    "consumption": "material_identity_split_authored_consumption_v02",
    "terminal": "material_identity_split_authored_terminal_v02",
    "proofs": "material_identity_split_authored_root_proofs_v02",
    "delegation": "material_identity_split_authored_delegation_v02",
}


def sha(content: bytes) -> str:
    """Hash exact physical bytes, including user decision whitespace and encoding."""
    return hashlib.sha256(content).hexdigest()


def stable(value: Any) -> str:
    """Hash normalized JSON only for explicitly semantic source fingerprints."""
    return sha(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    )


def encode(value: Any) -> bytes:
    """Match the host immutable physical JSON encoding."""
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def prefix(run_id: str) -> str:
    """Select only a normalized bounded run namespace."""
    if not isinstance(run_id, str) or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", run_id) is None:
        raise ValueError("authored split run identity is invalid")
    if run_id in {"consumed", "delegation_scope_consumed", "delegation_origin_consumed"}:
        raise ValueError("authored split run identity collides with reserved authority history")
    return f"{BASE}/{run_id}"


def workflow_identity(run_id: str) -> str:
    """Avoid collisions with ordinary workflow names while retaining a fixed chain key."""
    prefix(run_id)
    return "mis-" + sha(run_id.encode())[:60]


def _file_signature(metadata: os.stat_result) -> tuple[int, ...]:
    """Bind file identity, size and write metadata without treating access time as a change."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _bounded_file(
    root: Path, relative: str, *, limit: int, retain_content: bool
) -> tuple[bytes, str]:
    """Stream stable bytes while comparing path and descriptor change times separately."""
    selected = Path(native_io_path(contained_file(root, relative)))
    before = selected.stat()
    if before.st_size > limit:
        raise ValueError("authored split artifact exceeds byte bound")
    signature = _file_signature(before)
    digest = hashlib.sha256()
    chunks = []
    with selected.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        opened_signature = _file_signature(opened)
        # Windows path stat and descriptor fstat can expose different ctime meanings.
        # Compare identity/write fields across APIs and retain each full race snapshot.
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened_signature[:-1] != signature[:-1]
            or _file_signature(selected.stat()) != signature
        ):
            raise ValueError("authored split artifact changed before reading")
        remaining = before.st_size
        while remaining:
            chunk = stream.read(min(_READ_CHUNK_BYTES, remaining))
            if not chunk:
                raise ValueError("authored split artifact size changed while reading")
            remaining -= len(chunk)
            digest.update(chunk)
            if retain_content:
                chunks.append(chunk)
        if stream.read(1) or _file_signature(os.fstat(stream.fileno())) != opened_signature:
            raise ValueError("authored split artifact size or metadata changed while reading")
    final = Path(native_io_path(contained_file(root, relative)))
    if _file_signature(final.stat()) != signature:
        raise ValueError("authored split artifact changed after reading")
    return b"".join(chunks), digest.hexdigest()


def read(root: Path, reference: dict, *, binary: bool = False) -> bytes:
    """Read exact contained bytes without allocating the binary policy limit for small files."""
    if not binary:
        return artifact_bytes(root, reference)
    if (
        not isinstance(reference, dict)
        or set(reference) != {"path", "sha256"}
        or not isinstance(reference["sha256"], str)
        or re.fullmatch(r"[a-f0-9]{64}", reference["sha256"]) is None
    ):
        raise ValueError("authored split binary reference is malformed")
    data, digest = _bounded_file(
        root, reference["path"], limit=MAX_BINARY_BYTES, retain_content=True
    )
    if digest != reference["sha256"]:
        raise ValueError("authored split binary artifact changed")
    return data


def reference(root: Path, path: str) -> dict[str, str]:
    """Stream-hash a stable contained file without retaining its binary or JSON payload."""
    if not isinstance(path, str):
        raise ValueError("authored split artifact path must be text")
    limit = MAX_BINARY_BYTES if path.endswith(".blend") else 8 * 1024 * 1024
    _, digest = _bounded_file(root, path, limit=limit, retain_content=False)
    return {"path": path, "sha256": digest}


def contract(root: Path, ref: dict, kind: str) -> dict:
    """Validate one exact allowlisted generated contract using the stdlib schema reader."""
    from .paired_revision_runtime import _schema_check

    value = json.loads(read(root, ref))
    name = SCHEMAS[kind]
    if (
        isinstance(value, dict)
        and value.get("profile") == DELEGATED_PROFILE
        and kind in {"request", "approval", "apply", "consumption"}
    ):
        name = {
            "request": "material_identity_split_authored_technical_approval_request_v02",
            "approval": "material_identity_split_authored_technical_approval_v02",
            "apply": "material_identity_split_authored_technical_apply_intent_v02",
            "consumption": "material_identity_split_authored_technical_consumption_v02",
        }[kind]
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / f"{name}.schema.json"
    schema = json.loads(schema_path.read_bytes())
    _schema_check(value, schema, schema)
    if not isinstance(value, dict) or set(value) != set(schema["properties"]):
        raise ValueError("authored split persisted contract must contain every exact field")
    for field in ("created_at", "decision_observed_at", "delegation_observed_at"):
        if field in value:
            observed = datetime.fromisoformat(value[field].replace("Z", "+00:00"))
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise ValueError("authored split timestamp must identify an unambiguous instant")
    if value.get("job_id") != root.name:
        raise ValueError("authored split contract belongs to another job")
    return value


def run_contract(root: Path, run_id: str, name: str, kind: str) -> tuple[dict, dict]:
    """Load the sole fixed artifact for this run and enforce exact run ownership."""
    ref = reference(root, f"{prefix(run_id)}/{name}")
    value = contract(root, ref, kind)
    if value.get("run_id") != run_id:
        raise ValueError("authored split evidence belongs to another run")
    return value, ref


def derivative_payload(source: dict, rule: dict, predecessor: dict) -> dict:
    """Change only the single material slot, normalized material intent and predecessor map."""
    result = copy.deepcopy(source)
    slots = result.get("material_slots")
    if slots != [{"slot_index": 0, "material_id": rule["source_material_id"]}]:
        raise ValueError("authored split requires one exact source material slot")
    slots[0]["material_id"] = rule["new_material_id"]
    intent = result["source_geometry_intent"]
    assignments = intent["material_assignments"]
    if not assignments or any(
        item["material_id"] != rule["source_material_id"] for item in assignments
    ):
        raise ValueError("authored split source material intent differs from source identity")
    for item in assignments:
        item["material_id"] = rule["new_material_id"]
    intent["source_intent_sha256"] = stable(
        {key: value for key, value in intent.items() if key != "source_intent_sha256"}
    )
    if any(item["path"] == predecessor["path"] for item in result["source_hashes"]):
        raise ValueError("authored split predecessor already exists in source closure")
    result["source_hashes"].append({"role": "source_mesh_payload", **predecessor})
    result["source_fingerprint_sha256"] = stable(result["source_hashes"])
    return result


def candidate_projection(
    scene: dict,
    model: dict,
    rules: list[dict],
    derivatives: list[dict],
    material_derivatives: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Derive the entire allowed paired change, including every exact matching detail row."""
    new_scene, new_model = copy.deepcopy(scene), copy.deepcopy(model)
    materials = {item["id"]: item for item in scene["materials"]}
    objects = {item["id"]: item for item in new_scene["objects"]}
    if len(materials) != len(scene["materials"]) or len(objects) != len(scene["objects"]):
        raise ValueError("authored split source IDs are duplicated")
    detail_ids = [item["id"] for item in model.get("surface_details", [])]
    if len(detail_ids) != len(set(detail_ids)):
        raise ValueError("authored split source detail IDs are duplicated")
    new_ids, targets, declared_details = set(), set(), set()
    derived = {item["object_id"]: item for item in derivatives}
    if len(derived) != len(derivatives):
        raise ValueError("authored split derivative objects are duplicated")
    for rule in rules:
        source, new, target = (
            rule[key] for key in ("source_material_id", "new_material_id", "target_object_id")
        )
        if new in materials or new in new_ids or target in targets or source not in materials:
            raise ValueError("authored split new identity or exclusive target is invalid")
        if target not in objects or objects[target]["material_id"] != source:
            raise ValueError("authored split target does not use its exact source material")
        matched = [
            item
            for item in new_model.get("surface_details", [])
            if item.get("parent_object_id") == target and item.get("target_material_id") == source
        ]
        if (
            not matched
            or {item["id"] for item in matched} != set(rule["surface_detail_ids"])
            or len(rule["surface_detail_ids"]) != len(set(rule["surface_detail_ids"]))
            or declared_details & set(rule["surface_detail_ids"])
        ):
            raise ValueError("authored split must cover all and only existing matching detail rows")
        new_ids.add(new)
        targets.add(target)
        declared_details.update(rule["surface_detail_ids"])
        clone = copy.deepcopy(materials[source])
        clone["id"] = new
        if material_derivatives is not None:
            graph = next(item for item in material_derivatives if item["object_id"] == target)
            if graph["candidate_manifest"] is not None:
                clone["texture_manifest"] = graph["candidate_manifest"]["path"]
        new_scene["materials"].append(clone)
        obj = objects[target]
        if (
            obj["geometry"].get("kind") != "custom_mesh"
            or obj["geometry"].get("path") != derived[target]["source"]["path"]
        ):
            raise ValueError("authored split derivative must select the actual source geometry")
        obj["material_id"] = new
        obj["geometry"]["path"] = derived[target]["candidate"]["path"]
        for detail in matched:
            detail["target_material_id"] = new
    if set(derived) != targets:
        raise ValueError("authored split derivative inventory differs from exact clone targets")
    for source in {rule["source_material_id"] for rule in rules}:
        if not any(item["material_id"] == source for item in new_scene["objects"]):
            raise ValueError("authored split must retain at least one user of each source material")
    return new_scene, new_model


def preserved_evidence_relative(root: Path, plan: dict, field: str) -> str:
    """Resolve only the exact existing same-job historical observation aliases."""
    from .paired_revision_runtime import _file

    names = {
        "reference_analysis_path": "reference_analysis.json",
        "camera_solution_path": "camera_solution.json",
    }
    if plan.get("job_id") != root.name or field not in names:
        raise ValueError("authored split preserved evidence identity is invalid")
    relative = plan[field]
    short = f"analysis/{names[field]}"
    historical = f"workspaces/{root.name}/{short}"
    if "\\" not in relative:
        literal = _file(root, relative, exists=False)
        if literal.is_file():
            return relative
        if literal.exists():
            _file(root, relative)
        if relative != historical:
            _file(root, relative)
            raise ValueError("authored split preserved evidence is missing")
    elif relative == historical.replace("/", "\\"):
        literal, nested = root / relative, _file(root, historical, exists=False)
        if literal.exists() or literal.is_symlink() or nested.exists():
            raise ValueError("authored split historical evidence alias is ambiguous")
    else:
        raise ValueError("authored split historical evidence alias is unsupported")
    _file(root, short)
    return short


def geometry_dependencies(root: Path, documents: list[dict], extra: list[dict]) -> dict[str, str]:
    """Rehash the complete recursive closure under shared file/count/casefold bounds."""
    pending = [*extra, *(item for doc in documents for item in doc["source_geometry"])]
    visited, folded, total = {}, {}, 0
    while pending:
        ref = pending.pop()
        path, digest = ref["path"], ref["sha256"]
        if path in visited:
            if visited[path] != digest:
                raise ValueError("authored split closure has conflicting source hashes")
            continue
        if len(visited) >= 512 or path.casefold() in folded:
            raise ValueError("authored split closure exceeds unique dependency bound")
        content = read(root, {"path": path, "sha256": digest})
        total += len(content)
        if total > 64 * 1024 * 1024:
            raise ValueError("authored split closure exceeds byte bound")
        visited[path], folded[path.casefold()] = digest, path
        try:
            raw = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(raw, dict) or "source_hashes" not in raw:
            continue
        sources = raw["source_hashes"]
        if not isinstance(sources, list) or stable(sources) != raw.get("source_fingerprint_sha256"):
            raise ValueError("authored split source fingerprint changed")
        for source in sources:
            if not isinstance(source, dict) or set(source) not in (
                {"path", "sha256"},
                {"path", "sha256", "role"},
            ):
                raise ValueError("authored split transitive source is malformed")
            pending.append({"path": source["path"], "sha256": source["sha256"]})
    return dict(sorted(visited.items()))


def validate_plan(root: Path, plan_ref: dict, *, current: bool = False) -> dict:
    """Verify exact source snapshots and all allowed candidate semantics without live selection."""
    from .attachment_revision_runtime import _historical_geometry
    from .solid_attachment_contract import validate_solid_root_contract

    plan = contract(root, plan_ref, "plan")
    base = prefix(plan["run_id"])
    if plan_ref["path"] != f"{base}/plan.json" or set(plan["source_files"]) != SOURCE_PATHS:
        raise ValueError("authored split plan/source inventory is not the fixed run contract")
    sources = {}
    for path, ref in plan["source_files"].items():
        if ref["path"] != f"{base}/source/{path}":
            raise ValueError("authored split source snapshot is outside its fixed run")
        sources[path] = read(root, ref, binary=path.endswith(".blend"))
        if (
            current
            and read(root, {"path": path, "sha256": ref["sha256"]}, binary=path.endswith(".blend"))
            != sources[path]
        ):
            raise ValueError("authored split current canonical precondition changed")
    if plan["profile"] == DELEGATED_PROFILE:
        if plan["delegation"] is None:
            raise ValueError("authored technical split requires exact source-bound user delegation")
        validate_delegation(root, plan["delegation"], plan)
    elif plan["delegation"] is not None:
        raise ValueError("direct-user authored split cannot silently borrow delegated authority")
    candidates = {}
    for field, leaf in (
        ("candidate_scene_spec", "scene.json"),
        ("candidate_modeling_plan", "model.json"),
        ("candidate_job_metadata", "job.json"),
        ("candidate_attachment_intent", "attachment.json"),
        ("attachment_revision", "revision.json"),
        ("root_proofs", "root_proofs.json"),
        ("prospective_build_provenance", "provenance.json"),
        ("source_build_provenance", "source_provenance.json"),
    ):
        ref = plan[field]
        if ref["path"] != f"{base}/candidate/{leaf}":
            raise ValueError("authored split candidate path is outside its fixed run")
        candidates[field] = json.loads(read(root, ref))
    scene, model, metadata = (
        json.loads(sources[path])
        for path in ("analysis/scene_spec.json", "analysis/modeling_plan.json", "job.json")
    )
    if any(doc.get("job_id") != root.name for doc in (scene, model, metadata)):
        raise ValueError("authored split source identity changed")
    expected_scene, expected_model = candidate_projection(
        scene, model, plan["clone_rules"], plan["derivatives"], plan["material_derivatives"]
    )
    if stable(candidates["candidate_scene_spec"]) != stable(expected_scene) or stable(
        candidates["candidate_modeling_plan"]
    ) != stable(expected_model):
        raise ValueError("authored split candidate changed outside its exact material allowlist")
    rules = {item["target_object_id"]: item for item in plan["clone_rules"]}
    for ordinal, item in enumerate(plan["derivatives"]):
        if item["candidate"]["path"] != f"{base}/candidate/mesh_{ordinal:03d}.json":
            raise ValueError("authored split mesh derivative is outside its fixed run")
        raw = json.loads(read(root, item["source"]))
        if raw.get("schema_version") != "0.2.0" or raw.get("semantic_id") != item["object_id"]:
            raise ValueError("authored split requires the exact strict MeshPayloadV02 identity")
        if stable(json.loads(read(root, item["candidate"]))) != stable(
            derivative_payload(raw, rules[item["object_id"]], item["source"])
        ):
            raise ValueError("authored split mesh differs outside exact material metadata")
    record = contract(root, plan["attachment_revision"], "record")
    if record["run_id"] != plan["run_id"] or record["workflow_id"] != workflow_identity(
        plan["run_id"]
    ):
        raise ValueError("authored split attachment run identity changed")
    expected_metadata = copy.deepcopy(metadata)
    expected_metadata["attachment_revision"] = plan["attachment_revision"]
    if (
        encode(expected_metadata) != read(root, plan["candidate_job_metadata"])
        or record["metadata_before_sha256"] != sha(sources["job.json"])
        or record["previous_revision"] != metadata.get("attachment_revision")
        or record["candidate_intent"] != plan["candidate_attachment_intent"]
        or record["initial_registration"]
        != {
            "path": "production/surface_attachment/registration.json",
            "sha256": metadata.get("attachment_registration_sha256"),
        }
    ):
        raise ValueError("authored split metadata transition changed unauthorized fields")
    registration = json.loads(read(root, record["initial_registration"]))
    if (
        registration.get("kind") != "solid_root_attachment_registration"
        or registration.get("attachment_intent") != metadata.get("attachment_intent")
        or registration.get("job_id") != root.name
    ):
        raise ValueError("authored split initial registration changed")
    old = json.loads(read(root, record["previous_intent"]))
    new = candidates["candidate_attachment_intent"]
    if record["previous_revision"] is None:
        if record["previous_intent"] != metadata["attachment_intent"]:
            raise ValueError("authored split initial predecessor changed")
    elif (
        json.loads(read(root, record["previous_revision"])).get("candidate_intent")
        != record["previous_intent"]
    ):
        raise ValueError("authored split predecessor selection changed")
    mutable = {"source_scene", "source_modeling_plan", "source_geometry"}
    if stable({key: value for key, value in old.items() if key not in mutable}) != stable(
        {key: value for key, value in new.items() if key not in mutable}
    ):
        raise ValueError("authored split immutable root/domain/reference/camera intent changed")
    for document, scene_hash, model_hash in (
        (
            old,
            sha(sources["analysis/scene_spec.json"]),
            sha(sources["analysis/modeling_plan.json"]),
        ),
        (new, plan["candidate_scene_spec"]["sha256"], plan["candidate_modeling_plan"]["sha256"]),
    ):
        validate_solid_root_contract(document)
        if (
            document["job_id"] != root.name
            or document["source_scene"]
            != {"path": "analysis/scene_spec.json", "sha256": scene_hash}
            or document["source_modeling_plan"]
            != {"path": "analysis/modeling_plan.json", "sha256": model_hash}
        ):
            raise ValueError("authored split attachment sources differ from exact paired bytes")
    replacement = {item["source"]["path"]: item["candidate"] for item in plan["derivatives"]}
    if new["source_geometry"] != [
        replacement.get(item["path"], item) for item in old["source_geometry"]
    ]:
        raise ValueError("authored split attachment geometry inventory changed")
    extras = [old["source_reference"], old["source_camera_hypothesis"]]
    for key in ("reference_analysis_path", "camera_solution_path"):
        if model.get(key):
            extras.append(reference(root, preserved_evidence_relative(root, model, key)))
    from .authored_material_runtime import validate_material_derivatives

    material_dependencies = validate_material_derivatives(
        root, plan, scene, json.loads(sources["analysis/material_plan.json"])
    )
    if material_dependencies != plan["material_dependencies"]:
        raise ValueError("authored split complete material graph closure changed")
    extras.extend(
        {"path": path, "sha256": digest} for path, digest in material_dependencies.items()
    )
    dependencies = geometry_dependencies(root, [old, new], extras)
    if dependencies != plan["immutable_dependencies"]:
        raise ValueError("authored split immutable source closure changed")
    _historical_geometry(root, old, sources)
    _historical_geometry(
        root,
        new,
        {
            "analysis/scene_spec.json": read(root, plan["candidate_scene_spec"]),
            "analysis/modeling_plan.json": read(root, plan["candidate_modeling_plan"]),
        },
    )
    proofs = contract(root, plan["root_proofs"], "proofs")
    if proofs["run_id"] != plan["run_id"] or any(
        proofs[key].get("status") != "passed"
        for key in ("source_binary64", "source_float32", "candidate_binary64", "candidate_float32")
    ):
        raise ValueError("authored split lacks complete passed source and Float32 proofs")
    for key in ("prospective_build_provenance", "source_build_provenance"):
        value = candidates[key]
        if value.get("fingerprint") != stable(
            {k: v for k, v in value.items() if k != "fingerprint"}
        ):
            raise ValueError("authored split build provenance fingerprint changed")
    prospective = candidates["prospective_build_provenance"]
    from .authored_material_runtime import identity_split_closure

    if prospective.get("authored_material_identity_split_closure") != identity_split_closure(
        plan["run_id"],
        plan["material_dependencies"],
        plan["source_files"],
        candidates["source_build_provenance"],
    ):
        raise ValueError("authored split prospective provenance omits the exact material graph")
    if (
        prospective.get("scene_spec_sha256") != plan["candidate_scene_spec"]["sha256"]
        or prospective.get("scene_spec_path") != "analysis/scene_spec.json"
        or prospective.get("job_id") != root.name
        or prospective.get("material_plan_mode") != "authored_identity_preserved"
        or prospective.get("material_plan_path") is not None
        or prospective.get("material_plan_sha256") is not None
        or prospective.get("materials") != {}
        or prospective.get("attachment_intent") != plan["candidate_attachment_intent"]
        or prospective.get("attachment_revision") != plan["attachment_revision"]
        or prospective.get("attachment_registration_sha256")
        != record["initial_registration"]["sha256"]
    ):
        raise ValueError("authored split prospective provenance does not bind the exact candidate")
    return {
        "plan": plan,
        "sources": sources,
        "candidates": candidates,
        "record": record,
        "old": old,
        "new": new,
    }


def cloned_native_scene_metadata(
    source: dict, plan: dict, prospective: dict, objects: dict
) -> dict:
    """Change only explicit source/provenance fields and material identities in optical evidence."""
    value = copy.deepcopy(source)
    for key, field in (
        ("cbm_material_build_fingerprint", "fingerprint"),
        ("cbm_scene_spec_sha256", "scene_spec_sha256"),
        ("cbm_camera_fingerprint", "camera_fingerprint"),
    ):
        value[key] = prospective[field]
    value["cbm_build_provenance"] = json.dumps(
        prospective, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    value["cbm_source_spec"] = "analysis/scene_spec.json"
    if "cbm_assembly_modeling_plan_sha256" in value:
        value["cbm_assembly_modeling_plan_sha256"] = plan["candidate_modeling_plan"]["sha256"]
    if "cbm_optical_volume_boundary_evidence" in value:
        evidence = json.loads(value["cbm_optical_volume_boundary_evidence"])
        rules = {objects[rule["target_object_id"]]["name"]: rule for rule in plan["clone_rules"]}
        for row in evidence:
            rule = rules.get(row["object"])
            if rule is not None:
                if row["material_id"] != rule["source_material_id"]:
                    raise ValueError("authored split source optical material identity differs")
                row["material_id"] = rule["new_material_id"]
                row["material"] = rule["new_material_id"]
        value["cbm_optical_volume_boundary_evidence"] = json.dumps(
            evidence, sort_keys=True, allow_nan=False
        )
    return value


def native_mesh_metadata(payload: dict, payload_ref: dict) -> dict:
    """Return the exact material-only fields emitted by the strict SceneSpec v02 builder."""
    return {
        "cbm_mesh_payload_version": "0.2.0",
        "cbm_v02_payload_sha256": payload_ref["sha256"],
        "cbm_v02_source_fingerprint": payload["source_fingerprint_sha256"],
        "cbm_v02_material_ids": json.dumps(
            [item["material_id"] for item in payload["material_slots"]], separators=(",", ":")
        ),
    }


def cloned_native_metadata(source: dict, rule: dict, derivative: dict) -> dict:
    """Project only exact clone identity, graph locators and host-specific binding metadata."""
    value = copy.deepcopy(source)
    value["cbm_id"] = rule["new_material_id"]
    if "cbm_material_id" in value:
        value["cbm_material_id"] = rule["new_material_id"]
    for field, key in (
        ("cbm_texture_manifest", "candidate_manifest"),
        ("cbm_shader_recipe", "candidate_recipe"),
    ):
        if field in value:
            if derivative[key] is None:
                raise ValueError("authored split native graph locator has no exact derivative")
            value[field] = derivative[key]["path"]
        if f"{field}_sha256" in value:
            value[f"{field}_sha256"] = derivative[key]["sha256"]
    if "cbm_material_source_fingerprint" in value:
        value["cbm_material_source_fingerprint"] = stable(
            {
                "source_fingerprint": source["cbm_material_source_fingerprint"],
                "material_id": rule["new_material_id"],
                "manifest": derivative["candidate_manifest"],
                "recipe": derivative["candidate_recipe"],
            }
        )
    if "cbm_spatial_bindings" in value:
        bindings = json.loads(value["cbm_spatial_bindings"])
        selected = [
            item for item in bindings if item["parent_object_id"] == rule["target_object_id"]
        ]
        if {item["detail_id"] for item in selected} != set(rule["surface_detail_ids"]):
            raise ValueError("authored split native spatial binding scope differs")
        value["cbm_spatial_bindings"] = json.dumps(selected, sort_keys=True, separators=(",", ":"))
        value["cbm_spatial_binding_count"] = len(selected)
    return value


def validate_native_invariants(
    root: Path, plan_ref: dict, source_ref: dict, candidate_ref: dict
) -> tuple[dict, dict]:
    """Verify complete native geometry, exact source binary32 correspondence and assignments."""
    import struct

    checked = validate_plan(root, plan_ref)
    plan, base = checked["plan"], prefix(checked["plan"]["run_id"])
    if (
        source_ref["path"] != f"{base}/source_native.json"
        or candidate_ref["path"] != f"{base}/candidate_native.json"
    ):
        raise ValueError("authored split native inventory paths changed")
    inventories = []
    for stage, ref in (("source", source_ref), ("candidate", candidate_ref)):
        value = json.loads(read(root, ref))
        if set(value) != {
            "schema_version",
            "profile",
            "job_id",
            "run_id",
            "plan",
            "stage",
            "blender_version",
            "blender_executable_sha256",
            "native_script_sha256",
            "blend",
            "build_provenance",
            "material_images",
            "native_materials",
            "scene_custom",
            "render_state_sha256",
            "objects",
            "cameras",
            "lights",
            "active_camera",
            "appearance_or_human_acceptance",
        } or (
            value["schema_version"] != "0.2.0"
            or value["profile"] != plan["profile"]
            or value["job_id"] != root.name
            or value["run_id"] != plan["run_id"]
            or value["plan"] != plan_ref
            or value["stage"] != stage
            or value["blender_version"] != "5.0.1"
            or value["appearance_or_human_acceptance"] is not False
        ):
            raise ValueError("authored split native inventory has unknown or foreign identity")
        if (
            not isinstance(value["render_state_sha256"], str)
            or re.fullmatch(r"[a-f0-9]{64}", value["render_state_sha256"]) is None
        ):
            raise ValueError("authored split native render-state digest is malformed")
        expected_provenance = checked["candidates"][
            "source_build_provenance" if stage == "source" else "prospective_build_provenance"
        ]
        if stable(value["build_provenance"]) != stable(expected_provenance):
            raise ValueError("authored split native provenance does not match the exact candidate")
        expected_blend = (
            {
                "path": "blender/scene.blend",
                "sha256": plan["source_files"]["blender/scene.blend"]["sha256"],
            }
            if stage == "source"
            else reference(root, f"{base}/shadow/final.blend")
        )
        if value["blend"] != expected_blend:
            raise ValueError("authored split native inventory binds another Blend")
        document = checked["old" if stage == "source" else "new"]
        scene = (
            json.loads(checked["sources"]["analysis/scene_spec.json"])
            if stage == "source"
            else checked["candidates"]["candidate_scene_spec"]
        )
        from .authored_material_runtime import manifest_member

        expected_images = {}
        for material in scene["materials"]:
            refs = {}
            if stage == "source" and plan["source_material_plan_mode"] == "current":
                channels = (
                    expected_provenance.get("materials", {})
                    .get(material["id"], {})
                    .get("texture_channels", {})
                )
                refs = {ref["path"]: ref for ref in channels.values()}
            elif material.get("texture_manifest"):
                manifest_path = material["texture_manifest"]
                manifest = json.loads(read(root, reference(root, manifest_path)))
                for channel in manifest["channels"].values():
                    if channel.get("source") == "image":
                        path = manifest_member(root, manifest_path, channel["path"])
                        refs[path] = reference(root, path)
            expected_images[material["id"]] = [refs[key] for key in sorted(refs)]
        if value["material_images"] != expected_images:
            raise ValueError(
                "authored split native texture nodes differ from the exact image closure"
            )
        objects = {item["id"]: item for item in scene["objects"]}
        if set(value["objects"]) != set(objects) or set(objects) != set(
            document["required_semantics"]
        ):
            raise ValueError("authored split native object inventory changed")
        payloads = {
            json.loads(read(root, ref))["semantic_id"]: json.loads(read(root, ref))
            for ref in document["source_geometry"]
        }
        for semantic, obj in value["objects"].items():
            if set(obj) != {
                "name",
                "matrix_world",
                "dimensions",
                "raw_mesh",
                "evaluated_mesh",
                "materials",
                "native_custom",
            }:
                raise ValueError("authored split native object projection changed")
            if obj["materials"] != [objects[semantic]["material_id"]]:
                raise ValueError("authored split native material assignment differs from plan")
            identity_matrix = [
                [1.0 if first == second else 0.0 for second in range(4)] for first in range(4)
            ]
            if obj["matrix_world"] != identity_matrix:
                raise ValueError(
                    "authored split native transform is not the preserved world-space identity"
                )
            payload = payloads[semantic]
            payload_ref = next(
                ref
                for ref in document["source_geometry"]
                if json.loads(read(root, ref))["semantic_id"] == semantic
            )
            if any(
                obj["native_custom"].get(key) != value
                for key, value in native_mesh_metadata(payload, payload_ref).items()
            ):
                raise ValueError("authored split native mesh payload metadata is stale")
            vertices = [
                [struct.unpack("f", struct.pack("f", float(n)))[0] for n in vertex]
                for vertex in payload["vertices"]
            ]
            uvs = [
                [struct.unpack("f", struct.pack("f", float(n)))[0] for n in uv]
                for uv in payload["loop_uvs"]
            ]
            for key in ("raw_mesh", "evaluated_mesh"):
                mesh = obj[key]
                expected = {
                    "vertices_sha256": stable(vertices),
                    "faces_sha256": stable(payload["faces"]),
                    "uv_layers_sha256": stable([{"name": "UVMap", "uvs": uvs}]),
                    "polygon_material_indices_sha256": stable(payload["polygon_material_indices"]),
                    "smooth_polygon_flags_sha256": stable(payload["smooth_polygon_flags"]),
                    "sharp_edges_sha256": stable(
                        sorted(edge["vertices"] for edge in payload["sharp_edges"])
                    ),
                    "uv_seams_sha256": stable(
                        sorted(edge["vertices"] for edge in payload["uv_seams"])
                    ),
                    "vertex_count": len(vertices),
                    "face_count": len(payload["faces"]),
                    "loop_count": payload["loop_count"],
                    "active_uv": "UVMap",
                    "uv_layer_names": ["UVMap"],
                }
                if set(mesh) != {*expected, "full_geometry_sha256"} or any(
                    mesh[key] != target for key, target in expected.items()
                ):
                    raise ValueError(
                        "authored split native complete-array digests differ "
                        "from source binary32 geometry"
                    )
                if (
                    not isinstance(mesh["full_geometry_sha256"], str)
                    or re.fullmatch(r"[a-f0-9]{64}", mesh["full_geometry_sha256"]) is None
                ):
                    raise ValueError("authored split complete native geometry digest is invalid")
        inventories.append(value)
    source, candidate = inventories
    expected_scene = cloned_native_scene_metadata(
        source["scene_custom"],
        plan,
        checked["candidates"]["prospective_build_provenance"],
        source["objects"],
    )
    if stable(expected_scene) != stable(candidate["scene_custom"]):
        raise ValueError("authored split native scene metadata changed outside exact projection")
    source_materials, candidate_materials = (
        source["native_materials"],
        candidate["native_materials"],
    )
    source_ids = {
        item["id"]
        for item in json.loads(checked["sources"]["analysis/scene_spec.json"])["materials"]
    }
    if set(source_materials) != source_ids or set(candidate_materials) != source_ids | {
        rule["new_material_id"] for rule in plan["clone_rules"]
    }:
        raise ValueError("authored split native material coverage changed")
    for entry in [*source_materials.values(), *candidate_materials.values()]:
        if set(entry) != {"graph_sha256", "settings_sha256", "custom"} or any(
            not isinstance(entry[key], str) or re.fullmatch(r"[a-f0-9]{64}", entry[key]) is None
            for key in ("graph_sha256", "settings_sha256")
        ):
            raise ValueError("authored split native full graph/settings digest is malformed")
    for identity, original in source_materials.items():
        if stable(original) != stable(candidate_materials[identity]):
            raise ValueError("authored split retained native material changed")
    for rule, derivative in zip(plan["clone_rules"], plan["material_derivatives"], strict=True):
        original = source_materials[rule["source_material_id"]]
        expected = {
            **original,
            "custom": cloned_native_metadata(original["custom"], rule, derivative),
        }
        if stable(expected) != stable(candidate_materials[rule["new_material_id"]]):
            raise ValueError("authored split cloned native shader graph/settings changed")
    for field in (
        "render_state_sha256",
        "blender_executable_sha256",
        "native_script_sha256",
        "cameras",
        "lights",
        "active_camera",
    ):
        if stable(source[field]) != stable(candidate[field]):
            raise ValueError("authored split native environment or camera/light changed")
    for semantic, old in source["objects"].items():
        new = candidate["objects"][semantic]
        expected_custom = copy.deepcopy(old["native_custom"])
        if "cbm_assembly_modeling_plan_sha256" in expected_custom:
            expected_custom["cbm_assembly_modeling_plan_sha256"] = plan["candidate_modeling_plan"][
                "sha256"
            ]
        derivative = next(
            (item for item in plan["derivatives"] if item["object_id"] == semantic), None
        )
        if derivative is not None:
            payload = json.loads(read(root, derivative["candidate"]))
            expected_custom.update(native_mesh_metadata(payload, derivative["candidate"]))
            if "cbm_source_fingerprint" in expected_custom:
                expected_custom["cbm_source_fingerprint"] = payload["source_fingerprint_sha256"]
        if stable(expected_custom) != stable(new["native_custom"]):
            raise ValueError(
                "authored split native mesh custom metadata changed outside projection"
            )
        if stable(
            {key: value for key, value in old.items() if key not in {"materials", "native_custom"}}
        ) != stable(
            {key: value for key, value in new.items() if key not in {"materials", "native_custom"}}
        ):
            raise ValueError(
                "authored split native geometry/topology/UV/smoothing/transform changed"
            )
    return source, candidate


def validate_request(root: Path, request_ref: dict, *, current: bool = False) -> dict:
    """Follow the exact passed native/preapproval/invariant closure without granting approval."""
    request = contract(root, request_ref, "request")
    base = prefix(request["run_id"])
    if request_ref["path"] != f"{base}/approval_request.json":
        raise ValueError("authored split request path changed")
    checked = validate_plan(root, request["plan"], current=current)
    if (
        checked["plan"]["run_id"] != request["run_id"]
        or checked["plan"]["profile"] != request["profile"]
    ):
        raise ValueError("authored split request/plan belongs to another run")
    preapproval = contract(root, request["preapproval"], "preapproval")
    invariants = contract(root, request["invariant_report"], "invariants")
    if (
        request["preapproval"]["path"] != f"{base}/preapproval.json"
        or request["invariant_report"]["path"] != f"{base}/invariants.json"
    ):
        raise ValueError("authored split preapproval/invariant paths changed")
    for doc in (preapproval, invariants):
        if (
            doc["run_id"] != request["run_id"]
            or doc["plan"] != request["plan"]
            or doc["profile"] != request["profile"]
        ):
            raise ValueError("authored split native proof has foreign run or plan")
    if (
        preapproval["invariant_report"] != request["invariant_report"]
        or preapproval["shadow_blend"] != request["shadow_blend"]
        or invariants["root_proofs"] != checked["plan"]["root_proofs"]
        or invariants["source_native_inventory"] != preapproval["source_native_inventory"]
        or invariants["candidate_native_inventory"] != preapproval["candidate_native_inventory"]
    ):
        raise ValueError("authored split request/native/invariant binding changed")
    source, candidate = validate_native_invariants(
        root,
        request["plan"],
        preapproval["source_native_inventory"],
        preapproval["candidate_native_inventory"],
    )
    if request["shadow_blend"] != candidate["blend"]:
        raise ValueError("authored split request selects a different native Blend")
    read(root, request["shadow_blend"], binary=True)
    scripts = preapproval["native_script_sha256"]
    expected_scripts = {
        f"src/codex_blender_modeler/blender_scripts/{name}"
        for name in (
            "inspect_scene.py",
            "validate_scene.py",
            "authored_split_native.py",
        )
    }
    if (
        set(scripts) != expected_scripts
        or preapproval["blender_executable_sha256"] != source["blender_executable_sha256"]
        or scripts["src/codex_blender_modeler/blender_scripts/authored_split_native.py"]
        != source["native_script_sha256"]
    ):
        raise ValueError("authored split native executable/script identity changed")
    for path, digest in scripts.items():
        read(root, {"path": f"{base}/native_scripts/{Path(path).name}", "sha256": digest})
    for key, leaf in (
        ("shadow_validation", "validation.json"),
        ("shadow_scene_inventory", "scene_inventory.json"),
    ):
        if preapproval[key]["path"] != f"{base}/shadow/{leaf}":
            raise ValueError("authored split native output path changed")
        value = json.loads(read(root, preapproval[key]))
        if key == "shadow_validation" and value.get("ok") is not True:
            raise ValueError("authored split native validation did not pass")
        if key == "shadow_scene_inventory" and value.get("blender_version") != "5.0.1":
            raise ValueError("authored split inventory has another Blender version")
    return {**checked, "request": request, "preapproval": preapproval, "invariants": invariants}


def source_dependency_snapshot(
    root: Path, scene: dict, model: dict, material_plan: dict, metadata: dict
) -> dict:
    """Observe the complete current source graph for an exact one-split delegation boundary."""
    from .authored_material_runtime import material_dependencies

    pointer = metadata.get("attachment_revision")
    selected = (
        json.loads(read(root, pointer))["candidate_intent"]
        if pointer
        else metadata["attachment_intent"]
    )
    old = json.loads(read(root, selected))
    extras = [old["source_reference"], old["source_camera_hypothesis"]]
    for key in ("reference_analysis_path", "camera_solution_path"):
        if model.get(key):
            extras.append(reference(root, preserved_evidence_relative(root, model, key)))
    extras.extend(
        {"path": path, "sha256": digest}
        for path, digest in material_dependencies(root, scene, material_plan, []).items()
    )
    return geometry_dependencies(root, [old], extras)


def delegation_origin_identity(delegation: dict) -> str:
    """Identify original conversation authority independently of wrapper IDs, dates and paths."""
    return stable(
        {
            "job_id": delegation["job_id"],
            "question_message_id": delegation["question_message_id"],
            "question_sha256": delegation["question"]["sha256"],
            "reply_message_id": delegation["reply_message_id"],
            "reply_sha256": delegation["reply"]["sha256"],
        }
    )


def delegation_identity(delegation: dict) -> str:
    """Bind the original question/reply and finite task scope without mutable run/wrapper data."""
    return stable(
        {
            "origin": delegation_origin_identity(delegation),
            "source_sha256": delegation["source_sha256"],
            "source_dependency_sha256": delegation["source_dependency_sha256"],
            "clone_rules": delegation["clone_rules"],
            "approval_scope": "material_identity_split",
            "allowed_action": "select_and_approve_exact_specialized_technical_candidate",
        }
    )


def consumption_payload(root: Path, intent: dict, intent_ref: dict, plan: dict) -> dict:
    """Derive the sole exact logical authority claim in the selected domain."""
    approval_key, decision_key = authority_fields(intent)
    value = {
        "schema_version": "0.2.0",
        "profile": intent["profile"],
        "job_id": root.name,
        "run_id": intent["run_id"],
        "apply_intent": intent_ref,
        approval_key: intent[approval_key],
        "approval_request": intent["approval_request"],
        decision_key: intent[decision_key],
        "consumption_ordinal": 1,
        "consumed_once": True,
    }
    if intent["profile"] == DELEGATED_PROFILE:
        delegation = validate_delegation(root, intent["delegation"], plan)
        value.update(
            delegation=intent["delegation"],
            decision_actor="delegated_assistant",
            original_delegation_id=delegation["original_delegation_id"],
            delegation_origin_id=delegation_origin_identity(delegation),
            user_approval_consumed=False,
            aq_authority_consumed=False,
        )
    return value


def consumption_claim_paths(consumption: dict) -> list[str]:
    """Claim both exact decision and original bounded user delegation across rewrappings."""
    approval_key, _ = authority_fields(consumption)
    paths = [f"{BASE}/consumed/{consumption[approval_key]['sha256']}.json"]
    if consumption["profile"] == DELEGATED_PROFILE:
        paths.extend(
            [
                f"{BASE}/delegation_scope_consumed/{consumption['original_delegation_id']}.json",
                f"{BASE}/delegation_origin_consumed/{consumption['delegation_origin_id']}.json",
            ]
        )
    return paths


def validate_delegation(root: Path, ref: dict, plan: dict) -> dict:
    """Rehash actual question/reply bytes and enforce the exact finite source/clone delegation."""
    delegation = contract(root, ref, "delegation")
    if delegation["original_delegation_id"] != delegation_identity(delegation):
        raise ValueError("authored split original delegation identity was rewrapped or changed")
    for namespace, identity in (
        ("delegation_scope_consumed", delegation["original_delegation_id"]),
        ("delegation_origin_consumed", delegation_origin_identity(delegation)),
    ):
        path = f"{BASE}/{namespace}/{identity}.json"
        if (root / path).exists() or (root / path).is_symlink():
            claim = contract(root, reference(root, path), "consumption")
            if claim["run_id"] != plan["run_id"]:
                raise ValueError(
                    "authored split original delegation already consumed; "
                    "new wrappers or scopes cannot reset it"
                )
    if delegation["run_id"] != plan["run_id"] or delegation["profile"] != plan["profile"]:
        raise ValueError("authored split delegation belongs to another run or profile")
    expected_sources = {path: artifact["sha256"] for path, artifact in plan["source_files"].items()}
    if delegation["source_sha256"] != expected_sources or stable(
        delegation["clone_rules"]
    ) != stable(plan["clone_rules"]):
        raise ValueError("authored split delegation exceeds the exact observed source/clone scope")
    sources = {
        path: json.loads(read(root, ref))
        for path, ref in plan["source_files"].items()
        if not path.endswith(".blend")
    }
    expected_dependencies = source_dependency_snapshot(
        root,
        sources["analysis/scene_spec.json"],
        sources["analysis/modeling_plan.json"],
        sources["analysis/material_plan.json"],
        sources["job.json"],
    )
    if delegation["source_dependency_sha256"] != expected_dependencies:
        raise ValueError("authored split delegation source dependency closure changed")
    if (
        delegation["question"] == delegation["reply"]
        or not read(root, delegation["question"])
        or not read(root, delegation["reply"])
    ):
        raise ValueError(
            "authored split delegation requires distinct original question and reply bytes"
        )
    return delegation


def authority_fields(value: dict) -> tuple[str, str]:
    """Keep non-user technical authority fields separate from direct user approval fields."""
    if value["profile"] == DELEGATED_PROFILE:
        return "technical_approval", "technical_decision"
    return "approval", "user_decision"


def validate_approval(root: Path, intent: dict, *, current: bool = False) -> dict:
    """Require exact authority in the explicitly selected specialized user or technical domain."""
    run_id, base = intent["run_id"], prefix(intent["run_id"])
    checked = validate_request(root, intent["approval_request"], current=current)
    request = checked["request"]
    approval_key, decision_key = authority_fields(intent)
    approval = contract(root, intent[approval_key], "approval")
    if (
        intent["plan"] != request["plan"]
        or intent["run_id"] != request["run_id"]
        or intent["job_id"] != root.name
        or intent["profile"] != request["profile"]
        or approval["profile"] != intent["profile"]
    ):
        raise ValueError("authored split apply authority is not bound to the exact request/profile")
    if (
        intent[approval_key]["path"] != f"{base}/{approval_key}.json"
        or intent[decision_key]["path"] != f"{base}/{decision_key}.txt"
        or approval["run_id"] != run_id
        or approval["decision"] != "approved"
        or approval["approval_request"] != intent["approval_request"]
        or approval[decision_key + "_text_sha256"] != intent[decision_key]["sha256"]
    ):
        raise ValueError("authored split specialized authority is rejected, foreign or changed")
    for key in ("plan", "preapproval", "invariant_report", "shadow_blend"):
        if approval[key] != request[key]:
            raise ValueError(
                "authored split approval differs from exact requested native candidate"
            )
    if intent["profile"] == DELEGATED_PROFILE:
        if (
            intent["delegation"] != checked["plan"]["delegation"]
            or approval["delegation"] != intent["delegation"]
        ):
            raise ValueError("authored split technical approval has another user delegation")
        validate_delegation(root, intent["delegation"], checked["plan"])
    if not read(root, intent[decision_key]):
        raise ValueError("authored split exact decision bytes are empty")
    return {**checked, "approval": approval}


def validate_transaction(root: Path, run_id: str, *, terminal_required: bool = True) -> dict:
    """Validate four exact archives and the specialized request/decision/one-use journal chain."""
    base = prefix(run_id)
    intent, intent_ref = run_contract(root, run_id, "apply_intent.json", "apply")
    checked = validate_approval(root, intent)
    consumption, consumption_ref = run_contract(root, run_id, "consumption.json", "consumption")
    expected_consumption = consumption_payload(root, intent, intent_ref, checked["plan"])
    if consumption != expected_consumption:
        raise ValueError("authored split one-use consumption linkage changed")
    for path in consumption_claim_paths(consumption):
        global_claim = json.loads(read(root, {"path": path, "sha256": consumption_ref["sha256"]}))
        if global_claim != consumption:
            raise ValueError("authored split original authority is consumed by another transaction")
    journal, journal_ref = run_contract(root, run_id, "journal.json", "journal")
    if (
        journal["apply_intent"] != intent_ref
        or journal["approval_consumption"] != consumption_ref
        or journal["profile"] != intent["profile"]
        or set(journal["before"]) != set(TARGETS.values())
        or set(journal["after"]) != set(TARGETS.values())
    ):
        raise ValueError("authored split transaction must bind exactly four canonical files")
    plan = checked["plan"]
    candidate_refs = {
        "analysis/scene_spec.json": plan["candidate_scene_spec"],
        "analysis/modeling_plan.json": plan["candidate_modeling_plan"],
        "job.json": plan["candidate_job_metadata"],
        "blender/scene.blend": checked["request"]["shadow_blend"],
    }
    archives = {"before": {}, "after": {}}
    for direction, refs in (("before", plan["source_files"]), ("after", candidate_refs)):
        for label, path in TARGETS.items():
            expected_hash = refs[path]["sha256"]
            if journal[direction][path] != expected_hash:
                raise ValueError(
                    "authored split journal changed a source or approved candidate hash"
                )
            extension = "blend" if label == "blend" else "json"
            archives[direction][path] = read(
                root,
                {
                    "path": f"{base}/archives/{label}.{direction}.{extension}",
                    "sha256": expected_hash,
                },
                binary=label == "blend",
            )
    committed = (root / base / "receipt.json").exists()
    rolled_back = (root / base / "rollback.json").exists()
    terminal = None
    if committed or rolled_back:
        if committed and rolled_back:
            raise ValueError("authored split transaction has conflicting terminals")
        terminal, _ = run_contract(
            root, run_id, "receipt.json" if committed else "rollback.json", "terminal"
        )
        if (
            terminal["journal"] != journal_ref
            or terminal["profile"] != intent["profile"]
            or terminal["status"] != ("committed" if committed else "rolled_back")
            or terminal["canonical"] != journal["after" if committed else "before"]
        ):
            raise ValueError("authored split terminal differs from exact four-file journal")
    elif terminal_required:
        raise ValueError(
            "authored split transaction is incomplete; exact journal recovery required"
        )
    return {
        **checked,
        "record": checked["record"],
        "revision": plan["attachment_revision"],
        "intent": journal,
        "apply_intent": intent,
        "journal": journal_ref,
        "archives": archives,
        "terminal": terminal,
    }


def completed_authored_transactions(root: Path) -> dict[str, dict]:
    """Block every partial specialized attempt and return committed mixed-chain members."""
    base = root / BASE
    if base.is_symlink():
        raise ValueError("authored split transaction namespace is linked")
    if not base.exists():
        return {}
    from .paired_revision_runtime import _contained

    _contained(root, base, must_exist=True)
    runs = []
    claims = {}
    for path in base.iterdir():
        if path.name in {"consumed", "delegation_scope_consumed", "delegation_origin_consumed"}:
            _contained(root, path, must_exist=True)
            if not path.is_dir():
                raise ValueError("authored split global consumption namespace is not a directory")
            for claim_path in path.iterdir():
                if len(claims) >= 4096:
                    raise ValueError("authored split consumption inventory exceeds bounded limit")
                ref = reference(root, claim_path.relative_to(root).as_posix())
                claim = contract(root, ref, "consumption")
                if claim_path.relative_to(root).as_posix() not in consumption_claim_paths(claim):
                    raise ValueError("authored split global consumption path changed")
                if claim["run_id"] in claims and claims[claim["run_id"]] != claim:
                    raise ValueError("authored split run has conflicting original authority claims")
                claims[claim["run_id"]] = claim
            continue
        if len(runs) >= 4096:
            raise ValueError("authored split transaction inventory exceeds bounded limit")
        _contained(root, path, must_exist=True)
        if path.is_dir() and any(
            (path / name).exists() or (path / name).is_symlink()
            for name in (
                "apply_intent.json",
                "consumption.json",
                "journal.json",
                "receipt.json",
                "rollback.json",
            )
        ):
            runs.append(path.name)
    if set(claims) - set(runs):
        raise ValueError("authored split consumed transaction is missing from history")
    committed = {}
    for run_id in runs:
        checked = validate_transaction(root, run_id)
        if checked["terminal"]["status"] == "committed":
            key = checked["record"]["workflow_id"]
            if key in committed:
                raise ValueError("authored split committed chain identity collision")
            committed[key] = checked
    return committed


def collect_preserved_authored_split_provenance(root: Path) -> dict:
    """Read exact committed native-clone provenance; never certify an ordinary rebuild."""
    from .attachment_runtime import selected_attachment
    from .paired_revision_runtime import assert_no_pending_pair

    root = root.resolve(strict=True)
    assert_no_pending_pair(root)
    selected_attachment(root, root.name, root / "analysis/scene_spec.json")
    metadata = json.loads(read(root, reference(root, "job.json")))
    revision = metadata.get("attachment_revision")
    if revision is None:
        raise ValueError("authored preserved native provenance requires a committed split tip")
    record = json.loads(read(root, revision))
    if record.get("kind") != "solid_root_attachment_material_identity_split_revision":
        raise ValueError("authored preserved native provenance requires the exact split tip")
    checked = validate_transaction(root, record["run_id"])
    if checked["terminal"]["status"] != "committed" or checked["revision"] != revision:
        raise ValueError("authored preserved native provenance is not the committed selected tip")
    for path, digest in checked["intent"]["after"].items():
        if reference(root, path)["sha256"] != digest:
            raise ValueError("authored preserved native provenance cannot certify a rebuilt Blend")
    return checked["candidates"]["prospective_build_provenance"]
