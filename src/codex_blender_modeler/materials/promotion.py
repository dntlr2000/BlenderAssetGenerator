"""Workflow-owned material candidate validation and canonical promotion."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..blender_artifacts import stable_json_digest
from ..material_manifest import load_material_manifest
from ..validation import load_scene_spec
from ..workspace import job_dir, sha256_file
from .io import load_material_plan, load_shader_recipe, resolve_job_path
from .models import MaterialPromotionReceipt
from .validation import validate_material_contracts


def _directory_digest(path: Path) -> str:
    """Hash every file in one candidate bundle using deterministic relative paths."""

    records = [
        {
            "path": item.relative_to(path).as_posix(),
            "sha256": sha256_file(item),
        }
        for item in sorted(path.rglob("*"))
        if item.is_file()
    ]
    return stable_json_digest(records)


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    """Atomically replace one canonical byte stream after its parent exists."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".p-{uuid4().hex[:8]}.tmp"
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomically persist one promotion journal or final receipt."""

    _write_bytes_atomic(
        path,
        (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def _record_dependency(
    root: Path,
    records: dict[str, str],
    path: Path,
    label: str,
) -> None:
    """Record one existing job-owned dependency by normalized relative path."""

    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside the job root") from exc
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    records[relative] = sha256_file(resolved)


def _dependency_hashes(root: Path, candidate_plan_path: Path) -> dict[str, str]:
    """Hash candidate recipes, texture manifests, and manifest-owned image channels."""

    plan = load_material_plan(candidate_plan_path)
    records: dict[str, str] = {}
    for item in plan.materials:
        manifest_value = item.texture_manifest
        if item.shader_recipe:
            recipe_path = resolve_job_path(root, item.shader_recipe, "shader recipe")
            _record_dependency(root, records, recipe_path, "shader recipe")
            recipe = load_shader_recipe(recipe_path)
            manifest_value = manifest_value or recipe.texture_manifest
        if not manifest_value:
            continue
        manifest, manifest_path = load_material_manifest(
            {"id": item.material_id, "texture_manifest": manifest_value},
            root,
        )
        if manifest is None or manifest_path is None:
            raise RuntimeError("Declared texture manifest could not be loaded")
        _record_dependency(root, records, manifest_path, "texture manifest")
        for channel in manifest["channels"].values():
            resolved_path = channel.get("resolved_path")
            if resolved_path:
                _record_dependency(
                    root,
                    records,
                    Path(str(resolved_path)),
                    "texture channel",
                )
    return dict(sorted(records.items()))


def _preserve_previous_plan(
    root: Path,
    workflow_id: str,
    canonical_path: Path,
) -> tuple[str | None, str | None]:
    """Archive an existing canonical MaterialPlan under a deterministic history path."""

    if not canonical_path.is_file():
        return None, None
    previous_hash = sha256_file(canonical_path)
    history_key = stable_json_digest(
        {"workflow_id": workflow_id, "sha256": previous_hash}
    )[:16]
    relative = (
        Path("history")
        / "materials"
        / f"mat_{history_key}.json"
    )
    history_path = root / relative
    if history_path.exists():
        if not history_path.is_file() or sha256_file(history_path) != previous_hash:
            raise RuntimeError("Existing material history path does not match its hash")
    else:
        _write_bytes_atomic(history_path, canonical_path.read_bytes())
    return previous_hash, relative.as_posix()


def promote_workflow_material_candidate(
    job_id: str,
    workflow_id: str,
    *,
    candidate_plan_path: str,
    receipt_path: str,
    input_fingerprint: str,
) -> MaterialPromotionReceipt:
    """Strictly validate one authored candidate and promote its exact plan bytes."""

    root = job_dir(job_id)
    workflow_root = resolve_job_path(
        root,
        f"workflows/{workflow_id}",
        "workflow root",
    )
    candidate = resolve_job_path(root, candidate_plan_path, "candidate material plan")
    receipt = resolve_job_path(root, receipt_path, "material promotion receipt")
    try:
        candidate.relative_to(workflow_root / "artifacts" / "m" / "authored")
        receipt.relative_to(workflow_root / "artifacts" / "m")
    except ValueError as exc:
        raise ValueError(
            "Material candidate and receipt must remain in the owning workflow artifacts"
        ) from exc
    plan = load_material_plan(candidate)
    if plan.job_id != job_id or plan.stage != "authored":
        raise RuntimeError("Material promotion requires this job's authored candidate")
    scene_spec_path = root / "analysis" / "scene_spec.json"
    scene_spec = load_scene_spec(scene_spec_path).model_dump(mode="json")
    validation = validate_material_contracts(plan, scene_spec, root)
    if not validation.ok:
        raise RuntimeError("Authored material candidate failed strict contract validation")

    candidate_bytes = candidate.read_bytes()
    candidate_hash = sha256_file(candidate)
    candidate_bundle = candidate.parent
    bundle_hash = _directory_digest(candidate_bundle)
    dependencies = _dependency_hashes(root, candidate)
    canonical_path = root / "analysis" / "material_plan.json"
    pending_path = receipt.with_name(".promotion.pending")

    if receipt.exists():
        raise FileExistsError(f"Material promotion receipt is immutable: {receipt}")
    if pending_path.is_file():
        pending = MaterialPromotionReceipt.model_validate_json(
            pending_path.read_text(encoding="utf-8")
        )
        if (
            pending.workflow_id != workflow_id
            or pending.input_fingerprint != input_fingerprint
            or pending.candidate_plan_sha256 != candidate_hash
            or not canonical_path.is_file()
            or sha256_file(canonical_path) != pending.canonical_plan_sha256
        ):
            raise RuntimeError("Incomplete material promotion journal is inconsistent")
        os.replace(pending_path, receipt)
        return pending

    previous_hash, history_path = _preserve_previous_plan(
        root,
        workflow_id,
        canonical_path,
    )
    promoted = MaterialPromotionReceipt(
        workflow_id=workflow_id,
        job_id=job_id,
        input_fingerprint=input_fingerprint,
        candidate_plan_path=candidate_plan_path,
        candidate_plan_sha256=candidate_hash,
        candidate_bundle_sha256=bundle_hash,
        previous_canonical_sha256=previous_hash,
        canonical_plan_sha256=candidate_hash,
        history_path=history_path,
        scene_spec_sha256=sha256_file(scene_spec_path),
        dependency_sha256=dependencies,
        promoted_at=datetime.now(UTC),
    )
    _write_json_atomic(pending_path, promoted.model_dump(mode="json"))
    _write_bytes_atomic(canonical_path, candidate_bytes)
    if sha256_file(canonical_path) != promoted.canonical_plan_sha256:
        raise RuntimeError("Canonical MaterialPlan hash does not match promoted candidate")
    os.replace(pending_path, receipt)
    return promoted
