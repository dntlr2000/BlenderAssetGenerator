"""Fail-closed host validation for material promotion preflight evidence."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..analysis.models import ModelingPlan
from ..analysis.surface_details import validate_surface_detail_contract
from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from ..material_graph.models import MaterialGraphSpec
from ..materials.models import MaterialPlan
from ..materials.validation import validate_material_contracts
from ..models import SceneSpec
from ..texturing.models import TextureManifest
from .models import (
    MaterialClosureIssue,
    MaterialPreflightBudget,
    SurfaceDetailMaterialBinding,
    SurfaceDetailPreflightResult,
    SurfaceDetailRequirement,
)


class MaterialPreflightValidationError(RuntimeError):
    """Signal stale, incomplete, unsafe, or otherwise ineligible preflight evidence."""


def _model_payload(value: object) -> dict[str, Any]:
    """Convert one strict contract or mapping into a JSON-compatible dictionary."""

    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    elif isinstance(value, dict):
        payload = value
    else:
        raise TypeError("preflight evidence must be a strict contract or mapping")
    if not isinstance(payload, dict):
        raise TypeError("preflight evidence must serialize as an object")
    return payload


def _is_link_like(path: Path) -> bool:
    """Detect symlinks and Windows reparse points without following them."""

    native = native_io_path(path)
    if os.path.islink(native):
        return True
    try:
        metadata = os.lstat(native)
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def resolve_contained_path(
    job_root: Path,
    relative_path: str,
    *,
    must_exist: bool,
) -> Path:
    """Resolve one normalized job-relative path while rejecting links and escapes."""

    root = job_root.expanduser().resolve()
    if (
        not relative_path
        or "\\" in relative_path
        or relative_path.startswith("/")
        or ":" in relative_path
    ):
        raise MaterialPreflightValidationError("artifact path is not normalized and relative")
    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise MaterialPreflightValidationError("artifact path contains an unsafe segment")
    current = root
    for part in parts:
        current = current / part
        if _is_link_like(current):
            raise MaterialPreflightValidationError(
                f"artifact path traverses a link: {relative_path}"
            )
    try:
        current.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise MaterialPreflightValidationError(
            f"artifact path escapes the owning job: {relative_path}"
        ) from exc
    if must_exist and not os.path.isfile(native_io_path(current)):
        raise MaterialPreflightValidationError(f"required artifact is missing: {relative_path}")
    return current


def validate_exact_artifact(job_root: Path, artifact: object) -> Path:
    """Require one exact regular file whose bytes and size match its contract."""

    payload = _model_payload(artifact)
    try:
        relative_path = str(payload["path"])
        expected_sha256 = str(payload["sha256"])
        expected_size = int(payload["byte_size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MaterialPreflightValidationError("exact artifact binding is incomplete") from exc
    path = resolve_contained_path(job_root, relative_path, must_exist=True)
    actual_size = os.path.getsize(native_io_path(path))
    if actual_size != expected_size:
        raise MaterialPreflightValidationError(
            f"artifact byte size changed: {relative_path}"
        )
    if sha256_file(path) != expected_sha256:
        raise MaterialPreflightValidationError(f"artifact SHA-256 changed: {relative_path}")
    return path


def validate_dependency_closure(
    job_root: Path,
    closure: object,
    *,
    receipt: object | None = None,
    require_current_canonical: bool = True,
    historical_mutable_paths: set[str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Replay deterministic closure ordering, exact inputs, outputs, and receipt projections."""

    payload = _model_payload(closure)
    entries = payload.get("entries")
    planned_outputs = payload.get("planned_outputs")
    if not isinstance(entries, list) or not entries:
        raise MaterialPreflightValidationError("dependency closure has no entries")
    if not isinstance(planned_outputs, list) or not planned_outputs:
        raise MaterialPreflightValidationError("dependency closure has no planned outputs")
    if payload.get("collection_mode") != "host_graph_derived":
        raise MaterialPreflightValidationError(
            "dependency closure was not derived by the host recursive collector"
        )
    source_binding = payload.get("source_binding")
    if source_binding is None:
        raise MaterialPreflightValidationError("dependency closure has no source binding")
    validate_exact_artifact(job_root, source_binding)

    entry_keys: list[tuple[str, str]] = []
    casefold_paths: set[str] = set()
    immutable_projection: dict[str, str] = {}
    for raw_entry in entries:
        entry = _model_payload(raw_entry)
        role = str(entry.get("role", ""))
        path = str(entry.get("path", ""))
        key = (role, path)
        if key in entry_keys:
            raise MaterialPreflightValidationError(f"duplicate closure entry: {role}:{path}")
        folded = path.casefold()
        if folded in casefold_paths:
            raise MaterialPreflightValidationError(f"case-colliding closure path: {path}")
        entry_keys.append(key)
        casefold_paths.add(folded)
        expected_sha256 = str(entry.get("sha256", ""))
        mutable_paths = historical_mutable_paths or set()
        should_rehash = require_current_canonical or path not in mutable_paths
        if should_rehash:
            artifact_path = resolve_contained_path(job_root, path, must_exist=True)
            expected_size = int(entry.get("byte_size", -1))
            if os.path.getsize(native_io_path(artifact_path)) != expected_size:
                raise MaterialPreflightValidationError(f"closure byte size changed: {path}")
            if sha256_file(artifact_path) != expected_sha256:
                raise MaterialPreflightValidationError(f"closure dependency is stale: {path}")
        immutable_projection[path] = expected_sha256
    if entry_keys != sorted(entry_keys):
        raise MaterialPreflightValidationError("dependency closure entries are not deterministic")

    output_keys: list[tuple[str, str]] = []
    output_casefold: set[str] = set()
    planned_projection: dict[str, str] = {}
    for raw_output in planned_outputs:
        output = _model_payload(raw_output)
        role = str(output.get("output_kind", ""))
        path = str(output.get("path", ""))
        verification = str(output.get("verification", ""))
        expected_sha256 = output.get("sha256")
        resolve_contained_path(job_root, path, must_exist=False)
        key = (role, path)
        if key in output_keys or path.casefold() in output_casefold:
            raise MaterialPreflightValidationError(f"duplicate planned output: {path}")
        output_keys.append(key)
        output_casefold.add(path.casefold())
        if verification == "exact_hash" and isinstance(expected_sha256, str):
            planned_projection[path] = expected_sha256
        elif verification != "structural_binding":
            raise MaterialPreflightValidationError(
                f"planned output has an unsupported verification mode: {path}"
            )
    if output_keys != sorted(output_keys, key=lambda item: (item[0], item[1])):
        raise MaterialPreflightValidationError("planned outputs are not deterministic")

    rollback = payload.get("rollback_baseline")
    if rollback is None:
        raise MaterialPreflightValidationError("rollback baseline is unavailable")
    validate_exact_artifact(job_root, rollback)

    closure_sha256 = str(payload.get("closure_sha256", ""))
    sorted_entries = sorted(entries, key=lambda item: (item["role"], item["path"]))
    sorted_outputs = sorted(
        planned_outputs,
        key=lambda item: (item["output_kind"], item["path"]),
    )
    expected_closure_sha256 = stable_json_digest(
        {
            "entries": sorted_entries,
            "planned_outputs": sorted_outputs,
            "source_binding": _model_payload(source_binding),
        }
    )
    if closure_sha256 != expected_closure_sha256:
        raise MaterialPreflightValidationError("dependency closure digest is not reproducible")

    projected_inputs = getattr(closure, "project_immutable_input_map", None)
    projected_outputs = getattr(closure, "project_planned_output_map", None)
    if callable(projected_inputs) and dict(projected_inputs()) != immutable_projection:
        raise MaterialPreflightValidationError("closure immutable projection is inconsistent")
    if callable(projected_outputs) and dict(projected_outputs()) != planned_projection:
        raise MaterialPreflightValidationError("closure planned output projection is inconsistent")

    if receipt is not None:
        receipt_payload = _model_payload(receipt)
        if receipt_payload.get("status") != "passed":
            raise MaterialPreflightValidationError("dependency closure receipt did not pass")
        if receipt_payload.get("closure_sha256") != closure_sha256:
            raise MaterialPreflightValidationError("closure receipt payload digest changed")
        if dict(receipt_payload.get("immutable_input_projection", {})) != immutable_projection:
            raise MaterialPreflightValidationError("closure receipt input projection changed")
        if dict(receipt_payload.get("planned_output_projection", {})) != planned_projection:
            raise MaterialPreflightValidationError("closure receipt output projection changed")
        receipt_closure = receipt_payload.get("closure")
        if receipt_closure is not None:
            validate_exact_artifact(job_root, receipt_closure)
    return (
        dict(sorted(immutable_projection.items())),
        dict(sorted(planned_projection.items())),
    )


def validate_candidate_material_contracts(
    job_root: Path,
    *,
    candidate_material_plan: object,
    rebound_material_graph: object,
    scene_spec: object,
) -> tuple[MaterialPlan, MaterialGraphSpec, list[dict[str, Any]]]:
    """Strictly validate the candidate plan, graph, and their stable scene identities."""

    plan_path = validate_exact_artifact(job_root, candidate_material_plan)
    graph_path = validate_exact_artifact(job_root, rebound_material_graph)
    scene_path = validate_exact_artifact(job_root, scene_spec)
    try:
        plan = MaterialPlan.model_validate_json(plan_path.read_bytes())
        graph = MaterialGraphSpec.model_validate_json(graph_path.read_bytes())
        scene_payload = json.loads(scene_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as exc:
        raise MaterialPreflightValidationError("candidate material contracts are invalid") from exc
    if not isinstance(scene_payload, dict):
        raise MaterialPreflightValidationError("canonical SceneSpec is not a JSON object")
    report = validate_material_contracts(plan, scene_payload, job_root)
    failures = [item.model_dump(mode="json") for item in report.checks if item.status == "failed"]
    if failures:
        messages = "; ".join(str(item["message"]) for item in failures)
        raise MaterialPreflightValidationError(f"candidate material validation failed: {messages}")
    scene_material_ids = {
        str(item.get("id"))
        for item in scene_payload.get("materials", [])
        if isinstance(item, dict) and item.get("id")
    }
    plan_material_ids = {item.material_id for item in plan.materials}
    if scene_material_ids != plan_material_ids:
        raise MaterialPreflightValidationError(
            "candidate MaterialPlan material IDs differ from canonical SceneSpec"
        )
    if graph.material_id not in plan_material_ids:
        raise MaterialPreflightValidationError("MaterialGraph material ID is not in MaterialPlan")
    material_inputs = [item for item in graph.provenance.inputs if item.role == "material_plan"]
    scene_inputs = [item for item in graph.provenance.inputs if item.role == "scene_spec"]
    if len(material_inputs) != 1 or len(scene_inputs) != 1:
        raise MaterialPreflightValidationError(
            "MaterialGraph provenance requires one material plan and one SceneSpec"
        )
    if material_inputs[0].sha256 != _model_payload(candidate_material_plan)["sha256"]:
        raise MaterialPreflightValidationError(
            "MaterialGraph provenance targets another candidate MaterialPlan"
        )
    if scene_inputs[0].sha256 != _model_payload(scene_spec)["sha256"]:
        raise MaterialPreflightValidationError(
            "MaterialGraph provenance targets another canonical SceneSpec"
        )
    return plan, graph, [item.model_dump(mode="json") for item in report.checks]


def validate_surface_details(
    job_root: Path,
    *,
    requirements: list[SurfaceDetailRequirement],
    bindings: list[SurfaceDetailMaterialBinding],
    scene_object_ids: set[str] | None = None,
    scene_material_ids: set[str] | None = None,
) -> SurfaceDetailPreflightResult:
    """Cross-check localized material coverage, UV identity, masks, and ownership."""

    issues: list[MaterialClosureIssue] = []
    binding_by_id = {item.detail_id: item for item in bindings}
    if len(binding_by_id) != len(bindings):
        issues.append(
            MaterialClosureIssue(
                code="DUPLICATE_SURFACE_DETAIL_BINDING",
                message="surface-detail bindings contain a duplicate detail identity",
            )
        )
    for requirement in sorted(requirements, key=lambda item: item.detail_id):
        binding = binding_by_id.get(requirement.detail_id)
        if scene_object_ids is not None and requirement.object_id not in scene_object_ids:
            issues.append(
                MaterialClosureIssue(
                    code="SURFACE_DETAIL_OBJECT_MISSING",
                    message=f"SceneSpec has no object {requirement.object_id}",
                    entry_id=requirement.detail_id,
                )
            )
        if scene_material_ids is not None and requirement.material_id not in scene_material_ids:
            issues.append(
                MaterialClosureIssue(
                    code="SURFACE_DETAIL_MATERIAL_MISSING",
                    message=f"SceneSpec has no material {requirement.material_id}",
                    entry_id=requirement.detail_id,
                )
            )
        if binding is None:
            issues.append(
                MaterialClosureIssue(
                    code="SURFACE_DETAIL_COVERAGE_MISSING",
                    message=f"no material binding covers detail {requirement.detail_id}",
                    entry_id=requirement.detail_id,
                )
            )
            continue
        comparisons = (
            (binding.object_id == requirement.object_id, "SURFACE_DETAIL_OBJECT_MISMATCH"),
            (binding.material_id == requirement.material_id, "SURFACE_DETAIL_MATERIAL_MISMATCH"),
            (binding.strategy in {"image", "hybrid"}, "SURFACE_DETAIL_STRATEGY_INVALID"),
            (binding.strategy == requirement.strategy, "SURFACE_DETAIL_STRATEGY_MISMATCH"),
            (binding.mapping == "uv", "SURFACE_DETAIL_MAPPING_INVALID"),
            (binding.uv_set == requirement.uv_set, "SURFACE_DETAIL_UV_SET_MISMATCH"),
            (
                binding.uv_layout_fingerprint == requirement.uv_layout_fingerprint,
                "SURFACE_DETAIL_UV_FINGERPRINT_MISMATCH",
            ),
            (
                requirement.coverage_id in binding.coverage_ids,
                "SURFACE_DETAIL_COVERAGE_MISSING",
            ),
            (
                set(requirement.requested_channels).issubset(binding.available_channels),
                "SURFACE_DETAIL_CHANNEL_MISSING",
            ),
            (not binding.detail_owned_by_geometry, "SURFACE_DETAIL_DUPLICATE_OWNERSHIP"),
        )
        for passed, code in comparisons:
            if not passed:
                issues.append(
                    MaterialClosureIssue(
                        code=code,
                        message=f"surface-detail binding failed for {requirement.detail_id}",
                        entry_id=requirement.detail_id,
                    )
                )
        if requirement.mask is not None:
            try:
                validate_exact_artifact(job_root, requirement.mask)
            except MaterialPreflightValidationError:
                issues.append(
                    MaterialClosureIssue(
                        code="SURFACE_DETAIL_MASK_STALE",
                        message=(
                            "surface-detail mask is missing or stale for "
                            f"{requirement.detail_id}"
                        ),
                        path=requirement.mask.path,
                        entry_id=requirement.detail_id,
                    )
                )
            if requirement.mask.path not in binding.mask_paths:
                issues.append(
                    MaterialClosureIssue(
                        code="SURFACE_DETAIL_MASK_UNBOUND",
                        message=f"surface-detail mask is not bound for {requirement.detail_id}",
                        path=requirement.mask.path,
                        entry_id=requirement.detail_id,
                    )
                )
    unknown = sorted(set(binding_by_id) - {item.detail_id for item in requirements})
    for detail_id in unknown:
        issues.append(
            MaterialClosureIssue(
                code="UNDECLARED_SURFACE_DETAIL_BINDING",
                message=f"candidate contains undeclared surface-detail binding {detail_id}",
                entry_id=detail_id,
            )
        )
    return SurfaceDetailPreflightResult(
        status="failed" if issues else "passed",
        checked_detail_ids=sorted(item.detail_id for item in requirements),
        issues=issues,
    )


def validate_declared_surface_detail_completeness(
    job_root: Path,
    *,
    modeling_plan_artifact: object,
    scene_spec_artifact: object,
    inventory_artifact: object,
    material_plan: MaterialPlan,
    requirements: list[SurfaceDetailRequirement],
    bindings: list[SurfaceDetailMaterialBinding],
    uv_layout_fingerprint: str,
) -> int:
    """Require request facts and texture manifests to cover every planned surface detail."""

    try:
        modeling_plan = ModelingPlan.model_validate_json(
            validate_exact_artifact(job_root, modeling_plan_artifact).read_bytes()
        )
        scene_spec = SceneSpec.model_validate_json(
            validate_exact_artifact(job_root, scene_spec_artifact).read_bytes()
        )
    except (OSError, ValidationError) as exc:
        raise MaterialPreflightValidationError(
            "canonical surface-detail planning contracts are invalid"
        ) from exc
    planned = {
        detail.id: detail
        for detail in modeling_plan.surface_details
        if detail.representation != "omit"
    }
    request_requirements = {item.detail_id: item for item in requirements}
    request_bindings = {item.detail_id: item for item in bindings}
    if (
        len(request_requirements) != len(requirements)
        or len(request_bindings) != len(bindings)
        or set(request_requirements) != set(planned)
        or set(request_bindings) != set(planned)
    ):
        raise MaterialPreflightValidationError(
            "preflight surface-detail requirements and bindings must exactly cover ModelingPlan"
        )
    plan_materials = {item.material_id: item for item in material_plan.materials}
    for detail_id, detail in sorted(planned.items()):
        material_id = str(detail.target_material_id)
        item = plan_materials.get(material_id)
        if (
            item is None
            or item.texture_strategy not in {"image", "hybrid"}
            or item.mapping.mode != "uv"
            or not item.texture_manifest
        ):
            raise MaterialPreflightValidationError(
                f"candidate MaterialPlan lacks image-backed UV coverage for {detail_id}"
            )
        manifest_path = resolve_contained_path(
            job_root,
            item.texture_manifest,
            must_exist=True,
        )
        try:
            manifest = TextureManifest.model_validate_json(manifest_path.read_bytes())
        except (OSError, ValidationError) as exc:
            raise MaterialPreflightValidationError(
                f"surface-detail TextureManifest is invalid for {detail_id}"
            ) from exc
        manifest_bindings = [
            candidate
            for candidate in manifest.surface_detail_bindings
            if candidate.detail_id == detail_id
        ]
        if len(manifest_bindings) != 1:
            raise MaterialPreflightValidationError(
                f"TextureManifest must contain one exact spatial binding for {detail_id}"
            )
        manifest_binding = manifest_bindings[0]
        requirement = request_requirements[detail_id]
        request_binding = request_bindings[detail_id]
        expected_mask_path = manifest_binding.placement.mask_path
        expected_uv_rect = manifest_binding.placement.uv_rect
        if requirement.mask is None:
            mask_matches = expected_mask_path is None
        else:
            try:
                validate_exact_artifact(job_root, requirement.mask)
            except MaterialPreflightValidationError as exc:
                raise MaterialPreflightValidationError(
                    f"surface-detail mask is stale for {detail_id}"
                ) from exc
            mask_matches = (
                expected_mask_path == requirement.mask.path
                and manifest_binding.placement.mask_sha256 == requirement.mask.sha256
            )
        uv_rect_payload = (
            None
            if requirement.uv_rect is None
            else (
                requirement.uv_rect.u_min,
                requirement.uv_rect.v_min,
                requirement.uv_rect.u_max,
                requirement.uv_rect.v_max,
            )
        )
        if not (
            requirement.object_id == detail.parent_object_id
            and requirement.material_id == material_id
            and requirement.strategy == item.texture_strategy
            and requirement.uv_set == manifest_binding.uv_set == manifest.uv_set
            and requirement.uv_layout_fingerprint == uv_layout_fingerprint
            and requirement.requested_channels == detail.channels
            and requirement.coverage_id == detail_id
            and requirement.wrap_policy == "clamp"
            and mask_matches
            and uv_rect_payload == expected_uv_rect
        ):
            raise MaterialPreflightValidationError(
                f"preflight surface-detail requirement differs from ModelingPlan for {detail_id}"
            )
        expected_masks = sorted(
            str(candidate.placement.mask_path)
            for candidate in manifest.surface_detail_bindings
            if candidate.placement.mask_path is not None
        )
        if not (
            request_binding.object_id == detail.parent_object_id
            and request_binding.material_id == material_id
            and request_binding.strategy == item.texture_strategy
            and request_binding.mapping == item.mapping.mode
            and request_binding.uv_set == manifest_binding.uv_set
            and request_binding.uv_layout_fingerprint == uv_layout_fingerprint
            and request_binding.available_channels == sorted(manifest.channels)
            and request_binding.coverage_ids == sorted(manifest.surface_detail_ids)
            and request_binding.mask_paths == expected_masks
            and request_binding.detail_owned_by_geometry is False
        ):
            raise MaterialPreflightValidationError(
                f"preflight material binding differs from candidate manifest for {detail_id}"
            )
    if planned and material_plan.surface_detail_binding_policy != "spatial_v1":
        raise MaterialPreflightValidationError(
            "planned surface details require spatial_v1 candidate material bindings"
        )
    report = validate_surface_detail_contract(
        modeling_plan,
        scene_spec,
        job_root,
        material_plan=material_plan,
        require_materials=True,
        inventory_path=validate_exact_artifact(job_root, inventory_artifact),
    )
    if not report.ok:
        failures = "; ".join(
            check.message for check in report.checks if check.status == "failed"
        )
        raise MaterialPreflightValidationError(
            f"candidate surface-detail material coverage failed: {failures}"
        )
    return len(planned)


def validate_preflight_budget(
    budget: MaterialPreflightBudget,
    *,
    required_blender_runs: int,
) -> None:
    """Require bounded preflight capacity without borrowing any production budget."""

    if (
        required_blender_runs < 1
        or budget.consumed.preflight_blender_runs + required_blender_runs
        > budget.limits.preflight_blender_runs
    ):
        raise MaterialPreflightValidationError("preflight Blender budget is exhausted")


def collect_current_uv_layout_fingerprint(
    job_root: Path,
    inventory: object,
    *,
    expected_job_id: str,
) -> str:
    """Recompute one semantic, order-stable UV fingerprint from exact Blender 5 inventory."""

    inventory_path = validate_exact_artifact(job_root, inventory)
    try:
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaterialPreflightValidationError("scene inventory is not valid UTF-8 JSON") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("job_id") != expected_job_id
        or payload.get("blender_version") != "5.0.1"
    ):
        raise MaterialPreflightValidationError(
            "UV inventory requires the expected job and exact Blender 5.0.1"
        )
    objects = payload.get("objects")
    if not isinstance(objects, list):
        raise MaterialPreflightValidationError("UV inventory has no object list")
    by_id: dict[str, set[tuple[str | None, str | None, str | None]]] = {}
    sha_pattern = re.compile(r"^[0-9a-f]{64}$")
    for raw_object in objects:
        if not isinstance(raw_object, dict) or raw_object.get("type") != "MESH":
            continue
        object_id = raw_object.get("cbm_id") or raw_object.get("object_id")
        if not isinstance(object_id, str) or not object_id:
            raise MaterialPreflightValidationError(
                "mesh inventory object lacks a semantic identity"
            )
        active_uv = raw_object.get("active_uv")
        layers = raw_object.get("uv_layers") or raw_object.get("source_uv_layers")
        if active_uv is None:
            record = (None, None, None)
        else:
            if not isinstance(active_uv, str) or not isinstance(layers, list):
                raise MaterialPreflightValidationError(
                    f"UV inventory is incomplete for {object_id}"
                )
            matches = [
                item
                for item in layers
                if isinstance(item, dict) and item.get("name") == active_uv
            ]
            if len(matches) != 1:
                raise MaterialPreflightValidationError(
                    f"active UV layer is ambiguous for {object_id}"
                )
            coordinate = matches[0].get("coordinate_fingerprint")
            binding = matches[0].get("vertex_uv_binding_fingerprint")
            if not (
                isinstance(coordinate, str)
                and sha_pattern.fullmatch(coordinate)
                and isinstance(binding, str)
                and sha_pattern.fullmatch(binding)
            ):
                raise MaterialPreflightValidationError(
                    f"UV fingerprints are incomplete for {object_id}"
                )
            record = (active_uv, coordinate, binding)
        by_id.setdefault(object_id, set()).add(record)
    if not by_id:
        raise MaterialPreflightValidationError("UV inventory has no semantic mesh objects")
    inconsistent = [object_id for object_id, values in by_id.items() if len(values) != 1]
    if inconsistent:
        raise MaterialPreflightValidationError(
            "semantic object instances have inconsistent UV layouts: "
            + ", ".join(sorted(inconsistent))
        )
    projection = [
        {
            "object_id": object_id,
            "active_uv": next(iter(values))[0],
            "coordinate_fingerprint": next(iter(values))[1],
            "vertex_uv_binding_fingerprint": next(iter(values))[2],
        }
        for object_id, values in sorted(by_id.items())
    ]
    return stable_json_digest({"semantic_mesh_uv_layouts": projection})


def approval_ineligibility_reasons(
    *,
    report: object | None,
    closure_receipt: object | None,
    rebinding_receipt: object | None,
    shadow_receipt: object | None,
    neutral_preview: object | None,
    consistency_report: object | None = None,
) -> tuple[str, ...]:
    """Return deterministic reasons why no material appearance approval may be requested."""

    required = {
        "closure_receipt": closure_receipt,
        "rebinding_receipt": rebinding_receipt,
        "preflight_report": report,
        "shadow_compile_receipt": shadow_receipt,
        "neutral_preview": neutral_preview,
    }
    reasons: list[str] = []
    for label, value in required.items():
        if value is None:
            reasons.append(f"{label}_missing")
            continue
        payload = _model_payload(value)
        status = payload.get("status")
        if label != "neutral_preview" and status != "passed":
            reasons.append(f"{label}_not_passed")
    if consistency_report is not None:
        payload = _model_payload(consistency_report)
        if payload.get("status") not in {"consistent", "passed"} and not bool(
            payload.get("consistent", False)
        ):
            reasons.append("material_state_inconsistent")
    if report is not None:
        payload = _model_payload(report)
        if bool(payload.get("approval_plan_eligible", True)) is not True:
            reasons.append("preflight_report_ineligible")
    return tuple(sorted(set(reasons)))


def validate_preflight_for_approval(
    *,
    report: object | None,
    closure_receipt: object | None,
    rebinding_receipt: object | None,
    shadow_receipt: object | None,
    neutral_preview: object | None,
    consistency_report: object | None = None,
) -> object:
    """Return the passed report only when every pre-approval boundary is current."""

    reasons = approval_ineligibility_reasons(
        report=report,
        closure_receipt=closure_receipt,
        rebinding_receipt=rebinding_receipt,
        shadow_receipt=shadow_receipt,
        neutral_preview=neutral_preview,
        consistency_report=consistency_report,
    )
    if reasons:
        raise MaterialPreflightValidationError(
            "material approval plan is ineligible: " + ", ".join(reasons)
        )
    assert report is not None
    return report


__all__ = [
    "MaterialPreflightValidationError",
    "approval_ineligibility_reasons",
    "collect_current_uv_layout_fingerprint",
    "resolve_contained_path",
    "validate_candidate_material_contracts",
    "validate_declared_surface_detail_completeness",
    "validate_dependency_closure",
    "validate_exact_artifact",
    "validate_preflight_budget",
    "validate_preflight_for_approval",
    "validate_surface_details",
]
