from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .material_manifest import load_material_manifest
from .shader_recipe_runtime import load_runtime_shader_recipes

CAMERA_FINGERPRINT_FIELDS = (
    "projection",
    "location",
    "target",
    "focal_length_mm",
    "ortho_scale",
    "resolution",
)


class BuildProvenanceError(RuntimeError):
    """Report a missing, malformed, or stale canonical Blender-build fingerprint."""


def sha256_file(path: Path) -> str:
    """Hash one canonical source or derived artifact without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    """Hash one JSON-compatible value using the repository's canonical serialization."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_json_text(value: Any) -> str:
    """Serialize build provenance deterministically for storage in Blender properties."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def camera_contract_payload(camera: dict[str, Any]) -> dict[str, Any]:
    """Normalize SceneSpec camera scalar types exactly like the host Pydantic contract."""

    missing = sorted(set(CAMERA_FINGERPRINT_FIELDS) - set(camera))
    if missing:
        raise BuildProvenanceError(f"SceneSpec camera is missing fingerprint fields: {missing}")
    for field in ("location", "target"):
        value = camera[field]
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise BuildProvenanceError(f"SceneSpec camera {field} must have three components")
    resolution = camera["resolution"]
    if not isinstance(resolution, (list, tuple)) or len(resolution) != 2:
        raise BuildProvenanceError("SceneSpec camera resolution must have two components")
    return {
        "focal_length_mm": float(camera["focal_length_mm"]),
        "location": [float(value) for value in camera["location"]],
        "ortho_scale": float(camera["ortho_scale"]),
        "projection": str(camera["projection"]),
        "resolution": [int(value) for value in resolution],
        "target": [float(value) for value in camera["target"]],
    }


def camera_contract_fingerprint(camera: dict[str, Any]) -> str:
    """Hash the same fixed SceneSpec camera subset used by host-side visual QA."""

    return canonical_json_sha256(camera_contract_payload(camera))


def _relative_path(root: Path, path: Path, label: str) -> str:
    """Normalize a provenance path and reject sources outside the job workspace."""

    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise BuildProvenanceError(f"{label} is outside the job workspace: {resolved}") from exc


def _texture_channel_hashes(
    root: Path,
    material_id: str,
    manifest_value: str | None,
) -> dict[str, dict[str, str]]:
    """Hash every image channel consumed by one validated texture manifest."""

    if not manifest_value:
        return {}
    manifest, _ = load_material_manifest(
        {"id": material_id, "texture_manifest": manifest_value},
        root,
    )
    if manifest is None:
        return {}
    result: dict[str, dict[str, str]] = {}
    for channel, contract in sorted(manifest["channels"].items()):
        resolved_value = contract.get("resolved_path")
        if not resolved_value:
            continue
        resolved = Path(str(resolved_value)).expanduser().resolve()
        result[str(channel)] = {
            "path": _relative_path(root, resolved, f"texture channel {channel}"),
            "sha256": sha256_file(resolved),
        }
    provenance = manifest.get("provenance")
    declared_hashes = provenance.get("generated_sha256", {}) if isinstance(provenance, dict) else {}
    if not isinstance(declared_hashes, dict):
        raise BuildProvenanceError(
            f"Texture manifest generated_sha256 must be an object for {material_id}"
        )
    for channel, declared in sorted(declared_hashes.items()):
        actual = result.get(str(channel), {}).get("sha256")
        if actual != declared:
            raise BuildProvenanceError(
                f"Texture channel hash does not match manifest provenance for "
                f"{material_id}.{channel}: expected={declared} actual={actual}"
            )
    return result


def _geometry_payload_hashes(root: Path, scene_spec: dict[str, Any]) -> dict[str, str]:
    """Hash every external custom-mesh or terrain-heightmap payload used by SceneSpec."""

    payloads: dict[str, str] = {}
    objects = scene_spec.get("objects", [])
    if not isinstance(objects, list):
        raise BuildProvenanceError("SceneSpec objects must be an array")
    for item in objects:
        if not isinstance(item, dict):
            continue
        geometry = item.get("geometry")
        if not isinstance(geometry, dict):
            continue
        path_value = None
        if geometry.get("kind") == "custom_mesh":
            path_value = geometry.get("path")
        elif geometry.get("kind") == "terrain" and geometry.get("mode") == "heightmap":
            path_value = geometry.get("heightmap_path")
        if not path_value:
            continue
        if not isinstance(path_value, str):
            raise BuildProvenanceError(
                f"Geometry payload path for {item.get('id', '<unknown>')} must be a string"
            )
        resolved = (root / path_value).expanduser().resolve()
        relative = _relative_path(root, resolved, "geometry payload")
        if not resolved.is_file():
            raise BuildProvenanceError(f"Geometry payload does not exist: {resolved}")
        payloads[relative] = sha256_file(resolved)
    return dict(sorted(payloads.items()))


def _optional_interior_contract_hashes(root: Path) -> dict[str, Any] | None:
    """Bind an explicitly created interior scope and approval without changing legacy hashes."""

    scope_path = root / "architecture" / "interior_scope.json"
    if not scope_path.is_file():
        return None
    approval_path = root / "architecture" / "interior_scope.approval.json"
    return {
        "scope_path": _relative_path(root, scope_path, "interior scope"),
        "scope_sha256": sha256_file(scope_path),
        "approval_path": (
            _relative_path(root, approval_path, "interior approval")
            if approval_path.is_file()
            else None
        ),
        "approval_sha256": sha256_file(approval_path) if approval_path.is_file() else None,
    }


def collect_build_provenance(
    job_root: Path,
    job_id: str,
    *,
    scene_spec_path: Path | None = None,
    validate_contracts: bool = True,
) -> dict[str, Any]:
    """Collect build inputs, optionally running host-only Pydantic contract validation."""

    root = job_root.expanduser().resolve()
    spec_path = (
        scene_spec_path.expanduser().resolve()
        if scene_spec_path is not None
        else root / "analysis" / "scene_spec.json"
    )
    if not spec_path.is_file():
        raise BuildProvenanceError(f"SceneSpec does not exist: {spec_path}")
    try:
        scene_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildProvenanceError(f"SceneSpec is invalid JSON: {spec_path}") from exc
    if not isinstance(scene_spec, dict) or scene_spec.get("job_id") != job_id:
        actual_job_id = scene_spec.get("job_id") if isinstance(scene_spec, dict) else None
        raise BuildProvenanceError(
            f"SceneSpec job_id {actual_job_id!r} does not match {job_id!r}"
        )
    is_job_workspace = (root / "job.json").is_file() or (root / "architecture").is_dir()
    reference_scope_payload: dict[str, Any] | None = None
    metadata_path = root / "job.json"
    reference_content_scope: str | None = None
    target_subject: str | None = None
    if metadata_path.is_file():
        from .reference_scope import reference_content_scope_from_metadata

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            reference_content_scope, target_subject = (
                reference_content_scope_from_metadata(metadata)
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise BuildProvenanceError(
                f"Reference content-scope metadata is invalid: {exc}"
            ) from exc
        if reference_content_scope != "full_reference":
            reference_scope_payload = {
                "reference_content_scope": reference_content_scope,
                "target_subject": target_subject,
            }
    if is_job_workspace and validate_contracts:
        from .architecture.service import validate_scene_interior_scope
        from .models import SceneSpec
        from .reference_scope import validate_scene_content_scope

        try:
            parsed_scene_spec = SceneSpec.model_validate(scene_spec)
        except ValueError as exc:
            raise BuildProvenanceError(f"SceneSpec contract is invalid: {spec_path}") from exc
        interior_report = validate_scene_interior_scope(
            parsed_scene_spec,
            root,
            write_report=False,
        )
        if not interior_report.ok:
            formatted = "; ".join(interior_report.errors)
            raise BuildProvenanceError(f"InteriorScope validation failed: {formatted}")
        if reference_content_scope is not None:
            try:
                validate_scene_content_scope(
                    parsed_scene_spec,
                    scope=reference_content_scope,
                    target_subject=target_subject,
                )
            except ValueError as exc:
                raise BuildProvenanceError(
                    f"Reference content-scope validation failed: {exc}"
                ) from exc
    camera = scene_spec.get("camera")
    if not isinstance(camera, dict):
        raise BuildProvenanceError("SceneSpec camera must be an object")

    runtime_recipes = load_runtime_shader_recipes(root, job_id)
    plan_path = root / "analysis" / "material_plan.json"
    materials: dict[str, dict[str, Any]] = {}
    for material_id, runtime in sorted(runtime_recipes.items()):
        recipe_value = runtime.get("cbm_recipe_path")
        recipe_path = Path(str(recipe_value)).expanduser().resolve() if recipe_value else None
        manifest_value = runtime.get("cbm_texture_manifest")
        manifest_path_value = runtime.get("cbm_texture_manifest_path")
        manifest_path = (
            Path(str(manifest_path_value)).expanduser().resolve()
            if manifest_path_value
            else None
        )
        record: dict[str, Any] = {
            "shader_recipe_path": (
                _relative_path(root, recipe_path, "shader recipe") if recipe_path else None
            ),
            "shader_recipe_sha256": sha256_file(recipe_path) if recipe_path else None,
            "texture_manifest_path": (
                _relative_path(root, manifest_path, "texture manifest")
                if manifest_path
                else None
            ),
            "texture_manifest_sha256": (
                sha256_file(manifest_path) if manifest_path else None
            ),
            "texture_channels": _texture_channel_hashes(
                root,
                material_id,
                str(manifest_value) if manifest_value else None,
            ),
        }
        record["fingerprint"] = canonical_json_sha256(record)
        materials[material_id] = record

    payload: dict[str, Any] = {
        "schema_version": "0.5.0",
        "job_id": job_id,
        "scene_spec_path": _relative_path(root, spec_path, "SceneSpec"),
        "scene_spec_sha256": sha256_file(spec_path),
        "geometry_payloads_sha256": _geometry_payload_hashes(root, scene_spec),
        "camera_fingerprint": camera_contract_fingerprint(camera),
        "material_plan_path": (
            _relative_path(root, plan_path, "material plan") if plan_path.is_file() else None
        ),
        "material_plan_sha256": sha256_file(plan_path) if plan_path.is_file() else None,
        "materials": materials,
    }
    interior_contracts = _optional_interior_contract_hashes(root)
    if interior_contracts is not None:
        payload["interior_contracts"] = interior_contracts
    if reference_scope_payload is not None:
        payload["reference_content_scope"] = reference_scope_payload
    payload["fingerprint"] = canonical_json_sha256(payload)
    return payload


def require_matching_build_provenance(
    stored_json: str,
    expected_fingerprint: str,
    *,
    operation: str = "baking",
) -> dict[str, Any]:
    """Reject a Blender scene whose embedded build inputs differ from current contracts."""

    try:
        stored = json.loads(stored_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BuildProvenanceError("Blender scene build provenance is missing or invalid") from exc
    if not isinstance(stored, dict):
        raise BuildProvenanceError("Blender scene build provenance must be an object")
    declared = stored.get("fingerprint")
    unsigned = dict(stored)
    unsigned.pop("fingerprint", None)
    actual = canonical_json_sha256(unsigned)
    if declared != actual:
        raise BuildProvenanceError(
            f"Blender scene build provenance is internally inconsistent: {declared} != {actual}"
        )
    if actual != expected_fingerprint:
        raise BuildProvenanceError(
            "Blender scene is stale relative to SceneSpec/material contracts; "
            f"rebuild before {operation} ({actual} != {expected_fingerprint})"
        )
    return stored
