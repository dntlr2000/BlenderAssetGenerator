"""Explicit solid-root source rebinding through an existing guarded paired approval."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from ..attachment_runtime import REGISTRATION_PATH, artifact_bytes, selected_attachment
from ..blender_artifacts import deterministic_json_bytes, stable_json_digest
from ..models import SceneSpec
from ..packaging.attachment import preflight_source_attachment
from ..packaging.solid_attachment import load_solid_source_meshes
from ..structural_geometry.attachment_companion import Artifact
from ..structural_geometry.solid_root_ball import Budget, certify_ball, prepare_solid
from .models import JobId, Sha256, V08StrictModel, WorkflowId
from .paired_revision import MODEL_PATH, SCENE_PATH, _file


class AttachmentRevisionRecordV01(V08StrictModel):
    """Link immutable initial registration and predecessor to one exact guarded workflow."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    kind: Literal["solid_root_attachment_revision"] = "solid_root_attachment_revision"
    job_id: JobId
    workflow_id: WorkflowId
    initial_registration: Artifact
    previous_revision: Artifact | None
    previous_intent: Artifact
    candidate_intent: Artifact
    metadata_before_sha256: Sha256


class AttachmentRevisionBindingV01(V08StrictModel):
    """Bind exact metadata before/after and both complete proof domains into author approval."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    revision: Artifact
    record: AttachmentRevisionRecordV01
    metadata_after_sha256: Sha256
    source_preflight: dict[str, Any]
    float32_preflight: dict[str, Any]


def _sha(data: bytes) -> str:
    """Hash exact physical bytes without normalization."""
    return hashlib.sha256(data).hexdigest()


def revision_path(workflow_id: str) -> str:
    """Select a single immutable revision record in the existing attachment namespace."""
    from pydantic import TypeAdapter

    TypeAdapter(WorkflowId).validate_python(workflow_id)
    return f"production/surface_attachment/revisions/{workflow_id}/revision.json"


def _require_successor_capacity(root: Path, previous_revision: dict | None) -> None:
    """Refuse a prospective chain that would exceed the reader's exact shared bound."""
    from ..attachment_revision_runtime import MAX_REVISIONS

    seen = set()
    pointer = previous_revision
    while pointer is not None:
        identity = (pointer["path"], pointer["sha256"])
        if identity in seen or len(seen) + 1 >= MAX_REVISIONS:
            raise ValueError("attachment prospective revision chain exceeds bounded capacity")
        seen.add(identity)
        record = json.loads(artifact_bytes(root, pointer))
        pointer = record["previous_revision"]


def validate_candidate_intent(root: Path, path: str, sha256: str) -> dict[str, Any]:
    """Require an explicit contained staged intent with unchanged root/domain/reference intent."""
    if (
        not path.startswith("analysis/")
        or not path.endswith(".json")
        or path in {SCENE_PATH, MODEL_PATH, "analysis/revision_plan.json"}
    ):
        raise ValueError("attachment intent candidate requires a distinct staged analysis JSON")
    selected = selected_attachment(root, root.name, root / SCENE_PATH)
    if selected is None or selected["path"] == path:
        raise ValueError(
            "attachment revision requires a distinct existing registered solid-root intent"
        )
    metadata = json.loads(_file(root, "job.json").read_bytes())
    _require_successor_capacity(root, metadata.get("attachment_revision"))
    old = json.loads(artifact_bytes(root, selected))
    new = json.loads(artifact_bytes(root, {"path": path, "sha256": sha256}))
    validate_rebinding(old, new)
    from ..attachment_revision_runtime import _historical_geometry

    _historical_geometry(
        root,
        old,
        {
            SCENE_PATH: _file(root, SCENE_PATH).read_bytes(),
            MODEL_PATH: _file(root, MODEL_PATH).read_bytes(),
            "job.json": _file(root, "job.json").read_bytes(),
        },
    )
    return new


def validate_rebinding(old: dict[str, Any], new: dict[str, Any]) -> None:
    """Permit source bindings alone, preserving all roots, domains, semantic order and camera."""
    from ..structural_geometry.polygon_attachment import parse_solid_root_intent

    parse_solid_root_intent(json.dumps(old).encode())
    parse_solid_root_intent(json.dumps(new).encode())
    mutable = {"source_scene", "source_modeling_plan", "source_geometry"}
    if old.get("schema_version") == new.get("schema_version") == "0.2.0":
        mutable.add("source_triangle_views")
    if stable_json_digest({k: v for k, v in old.items() if k not in mutable}) != stable_json_digest(
        {k: v for k, v in new.items() if k not in mutable}
    ):
        raise ValueError(
            "attachment revision changed immutable root, domain, reference or camera intent"
        )
    if (
        new["source_scene"]["path"] != SCENE_PATH
        or new["source_modeling_plan"]["path"] != MODEL_PATH
    ):
        raise ValueError("attachment revision must bind exact prospective canonical scene and plan")


def _proofs(root: Path, document: dict[str, Any], sources: dict[str, bytes]) -> tuple[dict, dict]:
    """Recompute complete source and binary32 embedded-solid/root proofs under unchanged caps."""
    from ..attachment_revision_runtime import _historical_geometry

    _historical_geometry(root, document, sources)
    from ..structural_geometry.polygon_attachment import parse_solid_root_intent

    intent = parse_solid_root_intent(json.dumps(document).encode())
    meshes = load_solid_source_meshes(root, intent, prospective_sources=sources)
    budget = Budget()
    solids = {
        key: prepare_solid(mesh.vertices, mesh.faces, budget)
        for key, mesh in sorted(meshes.items())
    }
    rows = []
    for entry in intent.entries:
        rows.append(
            {
                "attachment_id": entry.attachment_id,
                "owner_certificate": certify_ball(
                    solids[entry.owner_semantic_id],
                    entry.center,
                    entry.radius_m,
                    entry.root_bounds,
                    budget,
                ),
                "subject_certificate": certify_ball(
                    solids[entry.subject_semantic_id],
                    entry.center,
                    entry.radius_m,
                    entry.root_bounds,
                    budget,
                ),
            }
        )
    source = {
        "status": "passed",
        "stage": "source_binary64",
        "aggregate_triangle_count": budget.triangle_count,
        "aggregate_embedding_work_units": budget.embedding_scans[0],
        "aggregate_root_predicate_visits": budget.used,
        "entries": rows,
        "native_geometry_verified": False,
        "final_human_acceptance": False,
    }
    float32 = preflight_source_attachment(intent, meshes)
    if float32["status"] != "passed":
        raise ValueError("attachment revision source Float32 preflight failed")
    return source, float32


def metadata_after(before: bytes, revision: dict[str, str]) -> bytes:
    """Change only the revision pointer while retaining all initial registration fields."""
    document = json.loads(before)
    document["attachment_revision"] = revision
    return deterministic_json_bytes(document)


def create_attachment_binding(
    root: Path, workflow_id: str, scene: SceneSpec, pair: dict[str, Any], path: str, sha256: str
) -> dict[str, Any]:
    """Derive a cycle-free immutable record and prospective metadata before approval exists."""
    candidate = validate_candidate_intent(root, path, sha256)
    before = _file(root, "job.json").read_bytes()
    metadata = json.loads(before)
    selected = selected_attachment(root, root.name, root / SCENE_PATH)
    record = {
        "schema_version": "0.1.0",
        "kind": "solid_root_attachment_revision",
        "job_id": root.name,
        "workflow_id": workflow_id,
        "initial_registration": {
            "path": REGISTRATION_PATH,
            "sha256": metadata["attachment_registration_sha256"],
        },
        "previous_revision": metadata.get("attachment_revision"),
        "previous_intent": selected,
        "candidate_intent": {"path": path, "sha256": sha256},
        "metadata_before_sha256": _sha(before),
    }
    revision = {
        "path": revision_path(workflow_id),
        "sha256": _sha(deterministic_json_bytes(record)),
    }
    source, float32 = _proofs(
        root,
        candidate,
        {
            SCENE_PATH: deterministic_json_bytes(scene.model_dump(mode="json")),
            MODEL_PATH: artifact_bytes(
                root, {"path": pair["candidate_path"], "sha256": pair["candidate_sha256"]}
            ),
        },
    )
    result = {
        "schema_version": "0.1.0",
        "revision": revision,
        "record": record,
        "metadata_after_sha256": _sha(metadata_after(before, revision)),
        "source_preflight": source,
        "float32_preflight": float32,
    }
    AttachmentRevisionBindingV01.model_validate(result)
    return result


def validate_attachment_binding(
    root: Path, workflow_id: str, binding: dict[str, Any], *, metadata_before: bytes | None = None
) -> None:
    """Recheck immutable binding and prospective proofs without staging fake canonical sources."""
    value = binding["attachment_revision"]
    AttachmentRevisionBindingV01.model_validate(value)
    record = value["record"]
    _require_successor_capacity(root, record["previous_revision"])
    if record["job_id"] != root.name or record["workflow_id"] != workflow_id:
        raise ValueError("attachment revision binding belongs to another workflow or job")
    if value["revision"] != {
        "path": revision_path(workflow_id),
        "sha256": _sha(deterministic_json_bytes(record)),
    }:
        raise ValueError("attachment immutable revision record changed")
    old = json.loads(artifact_bytes(root, record["previous_intent"]))
    candidate = json.loads(artifact_bytes(root, record["candidate_intent"]))
    validate_rebinding(old, candidate)
    if metadata_before is None:
        current = _file(root, "job.json").read_bytes()
        if _sha(current) == record["metadata_before_sha256"]:
            metadata_before = current
        else:
            metadata_before = _file(
                root, f"workflows/{workflow_id}/paired_revision/job.before.json"
            ).read_bytes()
            if _sha(current) != value["metadata_after_sha256"]:
                raise ValueError("attachment revision metadata changed outside exact transaction")
    if _sha(metadata_before) != record["metadata_before_sha256"]:
        raise ValueError("attachment revision archived initial metadata changed")
    before = json.loads(metadata_before)
    registration = json.loads(artifact_bytes(root, record["initial_registration"]))
    if (
        record["initial_registration"]
        != {"path": REGISTRATION_PATH, "sha256": before.get("attachment_registration_sha256")}
        or before.get("attachment_intent") != registration.get("attachment_intent")
        or before.get("attachment_revision") != record["previous_revision"]
        or _sha(metadata_after(metadata_before, value["revision"]))
        != value["metadata_after_sha256"]
        or binding["paired_modeling_plan"]["preserved_sources"]["job.json"] != _sha(metadata_before)
    ):
        raise ValueError("attachment revision metadata/registration binding differs")
    pair = binding["paired_modeling_plan"]
    source, float32 = _proofs(
        root,
        candidate,
        {
            SCENE_PATH: deterministic_json_bytes(binding["candidate_scene_spec"]),
            MODEL_PATH: artifact_bytes(
                root, {"path": pair["candidate_path"], "sha256": pair["candidate_sha256"]}
            ),
        },
    )
    if source != value["source_preflight"] or float32 != value["float32_preflight"]:
        raise ValueError("attachment revision source preflight evidence changed")
