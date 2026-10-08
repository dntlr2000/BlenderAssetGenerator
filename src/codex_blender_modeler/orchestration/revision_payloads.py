"""Exact geometry-byte bindings for newly planned Standard guarded revisions."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from ..blender_scripts.standard_custom_mesh_runtime import validate_standard_custom_mesh_payload
from ..build_provenance import _geometry_payload_hashes
from ..models import SceneSpec
from ..revision import preview_revision_plan
from ..structural_geometry.mesh_payload_io_v02 import (
    LegacyVertexUvMeshPayload,
    load_compatible_mesh_payload,
)

BINDING_PARAMETER = "bind_revision_geometry_payloads"
_BINDING_KEYS = {
    "job_id",
    "base_spec_sha256",
    "revision_plan_sha256",
    "candidate_scene_spec",
    "geometry_dependencies",
}


def _contained_file(root: Path, relative: str) -> Path:
    """Resolve a normalized, existing job-owned file without links or junctions."""

    from ..production.validation import ensure_contained_production_path

    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or ":" in relative
        or relative.startswith("/")
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or PurePosixPath(relative).as_posix() != relative
    ):
        raise ValueError("revision geometry dependency must be normalized job-relative text")
    path = ensure_contained_production_path(root, root / relative, must_exist=True)
    if not path.is_file():
        raise ValueError("revision geometry dependency is not a regular file")
    return path


def binding_path(root: Path, workflow_id: str) -> Path:
    """Locate only this workflow's fixed immutable internal geometry binding."""

    from ..production.validation import ensure_contained_production_path

    return ensure_contained_production_path(
        root,
        root / "workflows" / workflow_id / "artifacts" / "revision_payload_binding.json",
        must_exist=False,
    )


def geometry_dependency_hashes(root: Path, scene: SceneSpec) -> dict[str, str]:
    """Validate supported payloads and enumerate their bounded physical-byte closure."""

    pending: list[tuple[str, str | None, str | None]] = []
    hashes: dict[str, str] = {}
    folded: dict[str, str] = {}
    raw_scene = scene.model_dump(mode="json")
    for obj in scene.objects:
        geometry = obj.geometry.model_dump(mode="json")
        if geometry["kind"] == "custom_mesh" and geometry.get("path"):
            pending.append((geometry["path"], obj.id, None))
        elif geometry["kind"] == "terrain" and geometry.get("mode") == "heightmap":
            pending.append((geometry["heightmap_path"], None, None))

    # Bind actual override paths rather than provenance's source-path/effective-hash aliases.
    companion = root / "analysis" / "material_binding_derivative.json"
    if companion.exists() or companion.is_symlink():
        safe = _contained_file(root, "analysis/material_binding_derivative.json")
        content = safe.read_bytes()
        manifest = json.loads(content)
        pending.append(
            ("analysis/material_binding_derivative.json", None, hashlib.sha256(content).hexdigest())
        )
        pending.append((manifest["source_receipt_path"], None, manifest["source_receipt_sha256"]))
        for item in manifest["bindings"]:
            pending.append((item["scene_payload_path"], item["object_id"], item["source_sha256"]))
            pending.append((item["derivative_path"], item["object_id"], item["derivative_sha256"]))

    while pending:
        relative, object_id, expected = pending.pop()
        if isinstance(relative, str) and relative.casefold() in {
            "analysis/scene_spec.json",
            "reports/revision_diff.json",
            "blender/scene.blend",
            "renders/preview.png",
            "reports/scene_inventory.json",
            "reports/validation.json",
        }:
            raise ValueError(
                "revision geometry requires frozen sources, not revision/build outputs"
            )
        path = _contained_file(root, relative)
        with open(native_io_path(path), "rb") as handle:
            content = handle.read()
        digest = hashlib.sha256(content).hexdigest()
        if expected is not None and digest != expected:
            raise ValueError(f"nested revision geometry dependency changed: {relative}")
        if relative.casefold() in folded and folded[relative.casefold()] != relative:
            raise ValueError("revision geometry dependency has a case-colliding path")
        folded[relative.casefold()] = relative
        visited = relative in hashes
        if visited and hashes[relative] != digest:
            raise ValueError("revision geometry dependency changed while collecting")
        if not visited and len(hashes) >= 512:
            raise ValueError("revision geometry dependency closure exceeds 512 files")
        hashes[relative] = digest
        try:
            raw = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            if object_id is not None:
                raise ValueError("revision custom_mesh payload is not valid JSON") from None
            continue
        if not isinstance(raw, dict):
            if object_id is not None:
                raise ValueError("revision custom_mesh payload must be an object")
            continue
        if raw.get("job_id", scene.job_id) != scene.job_id:
            raise ValueError("revision geometry dependency belongs to a foreign job")
        # An object-to-payload association is checked even when a nested source visited it first.
        if object_id is not None:
            identity = (
                raw.get("object_id")
                if raw.get("payload_kind") == "standard_custom_mesh"
                else raw.get("semantic_id")
                if raw.get("schema_version") == "0.2.0"
                else object_id
            )
            if identity != object_id:
                raise ValueError("revision custom_mesh object identity changed")
        if not visited and "source_hashes" in raw:
            sources = raw["source_hashes"]
            if not isinstance(sources, list) or raw.get(
                "source_fingerprint_sha256"
            ) != stable_json_digest(sources):
                raise ValueError("revision geometry source fingerprint is stale")
            source_paths = set()
            for source in sources:
                if (
                    not isinstance(source, dict)
                    or set(source) not in ({"path", "sha256"}, {"role", "path", "sha256"})
                    or not isinstance(source["path"], str)
                    or not isinstance(source["sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) is None
                    or source["path"] in source_paths
                ):
                    raise ValueError("revision geometry source declaration is invalid")
                source_paths.add(source["path"])
                pending.append((source["path"], None, source["sha256"]))
        if object_id is None and not ("vertices" in raw or "faces" in raw or "payload_kind" in raw):
            continue
        if raw.get("payload_kind") == "standard_custom_mesh":
            payload = validate_standard_custom_mesh_payload(raw)
            if not visited:
                for prefix in ("source_scene_spec", "source_blend"):
                    pending.append((payload[f"{prefix}_path"], None, payload[f"{prefix}_sha256"]))
        elif raw.get("payload_kind") is not None:
            raise ValueError("unsupported revision custom_mesh payload_kind")
        elif raw.get("schema_version") in {None, "0.1.0"}:
            # Mirror both legacy builder dialects; extra metadata is not structural authority.
            if raw.get("loop_uvs") is not None:
                raise ValueError("legacy custom_mesh loop_uvs require Standard payload_kind")
            LegacyVertexUvMeshPayload.model_validate_json(json.dumps(raw))
        else:
            load_compatible_mesh_payload(raw)
    # Preserve Standard source identity/topology and material-override validation semantics.
    _geometry_payload_hashes(root.resolve(), raw_scene)
    for relative, expected in hashes.items():
        if sha256_file(_contained_file(root, relative)) != expected:
            raise ValueError("revision geometry dependency changed while collecting")
    return dict(sorted(hashes.items()))


def create_binding(
    root: Path,
    *,
    paired_modeling_plan_path: str | None = None,
    paired_modeling_plan_sha256: str | None = None,
    attachment_intent_path: str | None = None,
    attachment_intent_sha256: str | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Derive one exact candidate and dependency map without modifying canonical evidence."""

    plan_path = _contained_file(root, "analysis/revision_plan.json")
    source_path = _contained_file(root, "analysis/scene_spec.json")
    plan_hash = sha256_file(plan_path)
    candidate, report = preview_revision_plan(scene_spec_path=source_path, plan_path=plan_path)
    result = {
        "job_id": candidate.job_id,
        "base_spec_sha256": report["base_spec_sha256"],
        "revision_plan_sha256": plan_hash,
        "candidate_scene_spec": candidate.model_dump(mode="json"),
        "geometry_dependencies": geometry_dependency_hashes(root, candidate),
    }
    if paired_modeling_plan_path is not None:
        from .paired_revision import create_modeling_binding

        if "analysis/modeling_plan.json" in {p.casefold() for p in result["geometry_dependencies"]}:
            raise ValueError("paired geometry must not depend on mutable canonical ModelingPlan")
        result["paired_modeling_plan"] = create_modeling_binding(
            root, candidate, paired_modeling_plan_path, str(paired_modeling_plan_sha256)
        )
    if attachment_intent_path is not None:
        if "job.json" in {path.casefold() for path in result["geometry_dependencies"]}:
            raise ValueError("attachment revision geometry cannot depend on mutable job metadata")
        from .attachment_revision import create_attachment_binding

        if workflow_id is None or "paired_modeling_plan" not in result:
            raise ValueError("attachment revision requires a paired workflow identity")
        result["attachment_revision"] = create_attachment_binding(
            root, workflow_id, candidate, result["paired_modeling_plan"],
            attachment_intent_path, str(attachment_intent_sha256),
        )
    if (
        sha256_file(plan_path) != plan_hash
        or sha256_file(source_path) != report["base_spec_sha256"]
    ):
        raise ValueError("revision source changed while binding geometry dependencies")
    return result


def validate_binding(
    root: Path,
    workflow_id: str,
    *,
    require_current_candidate: bool = False,
) -> dict[str, Any]:
    """Re-enumerate the exact closure and optionally rederive its approved baseline candidate."""

    path = binding_path(root, workflow_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    from .models import WorkflowPlan, WorkflowRequest

    request = WorkflowRequest.model_validate_json(
        _contained_file(root, f"workflows/{workflow_id}/request.json").read_bytes()
    )
    paired = request.paired_modeling_plan_path is not None
    attachment = request.attachment_intent_path is not None
    expected_keys = (_BINDING_KEYS | ({"paired_modeling_plan"} if paired else set())
                     | ({"attachment_revision"} if attachment else set()))
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ValueError("revision geometry binding fields changed")
    candidate = SceneSpec.model_validate(payload["candidate_scene_spec"])
    if candidate.job_id != root.name or payload["job_id"] != root.name:
        raise ValueError("revision geometry binding belongs to a foreign job")
    if geometry_dependency_hashes(root, candidate) != payload["geometry_dependencies"]:
        raise ValueError(
            "revision geometry dependency map changed, is missing, or has extra entries"
        )
    if paired:
        from .paired_revision import validate_modeling_binding

        companion = payload["paired_modeling_plan"]
        plan = WorkflowPlan.model_validate_json(
            _contained_file(root, f"workflows/{workflow_id}/plan.json").read_bytes()
        )
        apply_step = next(item for item in plan.steps if item.step_id == "revision.apply")
        if companion.get("base_modeling_plan_sha256") != apply_step.parameters.get(
            "expected_modeling_plan_sha256"
        ):
            raise ValueError("paired ModelingPlan baseline differs from original workflow contract")
        if (
            companion.get("candidate_path") != request.paired_modeling_plan_path
            or companion.get("candidate_sha256") != request.paired_modeling_plan_sha256
        ):
            raise ValueError("paired ModelingPlan differs from explicit workflow selection")
        if "analysis/modeling_plan.json" in {
            p.casefold() for p in payload["geometry_dependencies"]
        }:
            raise ValueError("paired geometry references mutable canonical ModelingPlan")
        validate_modeling_binding(
            root, companion, candidate,
            metadata_after_sha256=(payload["attachment_revision"]["metadata_after_sha256"]
                                   if attachment else None),
        )
    if attachment:
        from .attachment_revision import validate_attachment_binding

        record = payload["attachment_revision"]["record"]
        if record["candidate_intent"] != {
            "path": request.attachment_intent_path, "sha256": request.attachment_intent_sha256
        }:
            raise ValueError("attachment candidate differs from explicit workflow request")
        if (apply_step.parameters.get("attachment_metadata_before_sha256")
                != record["metadata_before_sha256"]):
            raise ValueError("attachment original metadata differs from the planned source")
        validate_attachment_binding(root, workflow_id, payload)
    if (
        require_current_candidate
        and create_binding(
            root,
            paired_modeling_plan_path=request.paired_modeling_plan_path,
            paired_modeling_plan_sha256=request.paired_modeling_plan_sha256,
            attachment_intent_path=request.attachment_intent_path,
            attachment_intent_sha256=request.attachment_intent_sha256,
            workflow_id=workflow_id,
        )
        != payload
    ):
        raise ValueError("revision geometry binding is stale relative to its plan or baseline")
    return payload


def revision_evidence_hashes(root: Path, workflow_id: str) -> dict[str, str]:
    """Pin the fixed live authority/source files used by one guarded host transaction."""

    prefix = f"workflows/{workflow_id}"
    relatives = [
        "analysis/revision_plan.json",
        "analysis/modeling_plan.json",
        f"{prefix}/plan.json",
        f"{prefix}/request.json",
        f"{prefix}/artifacts/revision_payload_binding.json",
        f"{prefix}/completions/revision.author.json",
    ]
    for authority in ("approvals", "policy_authorizations"):
        relative = f"{prefix}/{authority}/revision.approval.json"
        if (root / relative).exists() or (root / relative).is_symlink():
            relatives.append(relative)
    return {relative: sha256_file(_contained_file(root, relative)) for relative in relatives}
