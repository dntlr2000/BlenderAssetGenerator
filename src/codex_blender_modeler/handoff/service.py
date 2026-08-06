"""Generate and verify immutable engine-neutral destination handoff envelopes."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from ..config import get_settings, load_feature_config
from ..external_intake.models import ExternalAssetManifest
from ..optimization.io import (
    job_relative,
    load_model,
    resolve_inside,
    utc_now,
    validate_filesystem_id,
    write_model,
)
from ..packaging.models import ExportPackageManifest, RoundTripValidation
from ..validation import load_scene_spec
from ..workspace import file_exists, job_dir, native_io_path, sha256_file
from .models import (
    AssemblyManifest,
    AssemblyNode,
    AxisContract,
    DestinationContext,
    DestinationHandoffManifest,
    DestinationHandoffPlan,
    DestinationHandoffValidation,
    HandoffFileReceipt,
    HandoffReportManifest,
    HandoffValidationCheck,
    HierarchySummary,
    ImportChecklist,
    ImportChecklistItem,
    LODColliderSummary,
    MaterialChannelMapping,
    MaterialMappingManifest,
    PivotSnapshot,
    PortableMaterialMapping,
    RawPBRContract,
    SourceArtifact,
    TextureCoordinateBinding,
    TransformSnapshot,
)
from .pdf_report import render_handoff_pdf

SUPPORTED_PROFILES = {"portable_gltf", "fbx_interchange"}
SUPPORTED_SCOPE = [
    "static asset import planning",
    "axis, unit, pivot, and hierarchy reconstruction planning",
    "portable PBR channel mapping",
    "LOD and collider reconstruction planning",
    "user-approved destination import and validation",
]
EXCLUDED_SCOPE = [
    "Unity or Unreal Editor automation",
    "engine prefab, actor, or runtime material graph creation",
    "runtime parity claims",
    "CAD B-Rep",
    "rigging, skinning, and animation",
    "gameplay logic",
    "unapproved destination project changes",
]
IMPORT_SCHEMA_FILENAMES = (
    "destination_import_plan.schema.json",
    "destination_import_receipt.schema.json",
    "destination_import_validation.schema.json",
)


def _require_handoff_feature() -> None:
    """Reject handoff operations when the explicit V0.9 feature flag is disabled."""

    if not load_feature_config().features.destination_handoff:
        raise RuntimeError("destination_handoff is disabled in cbm.toml")


def _portable_handoff_id(prefix: str) -> str:
    """Create one sortable lowercase identifier for an immutable handoff artifact."""

    stamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ").lower()
    return f"{prefix}-{stamp}-{uuid4().hex[:8]}"


def _require_profile(profile_id: str) -> str:
    """Limit handoff generation to the two supported engine-neutral package profiles."""

    if profile_id not in SUPPORTED_PROFILES:
        raise ValueError(
            "destination handoff supports GLB and FBX profiles "
            "(portable_gltf and fbx_interchange) only"
        )
    return profile_id


def _is_link_like(path: Path) -> bool:
    """Detect symbolic links and Windows junctions before copying or hashing content."""

    native = native_io_path(path)
    if os.path.islink(native):
        return True
    junction_test = getattr(os.path, "isjunction", None)
    return bool(junction_test(native)) if callable(junction_test) else False


def _is_directory(path: Path) -> bool:
    """Check one directory through the Windows extended-length path representation."""

    return os.path.isdir(native_io_path(path))


def _file_size(path: Path) -> int:
    """Read one file size without truncating a valid extended Windows path."""

    return int(os.stat(native_io_path(path)).st_size)


def _copy_file(source: Path, target: Path) -> None:
    """Copy one file while preserving metadata and supporting extended Windows paths."""

    os.makedirs(native_io_path(target.parent), exist_ok=True)
    shutil.copy2(native_io_path(source), native_io_path(target))


def _relative_posix(root: Path, path: Path) -> str:
    """Return one lexical envelope-relative POSIX path after containment verification."""

    absolute_root = Path(os.path.abspath(os.fspath(root.expanduser())))
    absolute_path = Path(os.path.abspath(os.fspath(path.expanduser())))
    try:
        return absolute_path.relative_to(absolute_root).as_posix()
    except ValueError as exc:
        raise ValueError("handoff path escapes its declared root") from exc


def _walk_regular_files(root: Path) -> list[Path]:
    """Enumerate regular files deterministically through extended Windows paths."""

    native_root = native_io_path(root)
    if not os.path.isdir(native_root):
        raise FileNotFoundError(root)
    files: list[Path] = []
    for current, directory_names, file_names in os.walk(native_root, followlinks=False):
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            relative = os.path.relpath(os.path.join(current, name), native_root)
            candidate = root.joinpath(*Path(relative).parts)
            if _is_link_like(candidate):
                raise RuntimeError("handoff tree contains a link-like directory")
        for name in file_names:
            relative = os.path.relpath(os.path.join(current, name), native_root)
            candidate = root.joinpath(*Path(relative).parts)
            if _is_link_like(candidate) or not file_exists(candidate):
                raise RuntimeError("handoff tree contains a non-regular file")
            files.append(candidate)
    return files


def _media_type(path: Path) -> str:
    """Return a stable media type for one handoff file receipt."""

    known = {
        ".fbx": "application/octet-stream",
        ".glb": "model/gltf-binary",
        ".json": "application/json",
        ".md": "text/markdown",
        ".pdf": "application/pdf",
    }
    return known.get(path.suffix.casefold()) or mimetypes.guess_type(path.name)[0] or (
        "application/octet-stream"
    )


def _file_id(kind: str, relative: str) -> str:
    """Derive a portable unique receipt ID from one relative path and artifact role."""

    suffix = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
    normalized = kind.casefold().replace("_", "-")
    return f"{normalized}-{suffix}"


def _receipt(
    envelope_root: Path,
    path: Path,
    kind: str,
) -> HandoffFileReceipt:
    """Create one exact envelope-relative receipt for an existing regular file."""

    relative = _relative_posix(envelope_root, path)
    if _is_link_like(path) or not file_exists(path):
        raise FileNotFoundError(f"handoff receipt is missing or link-like: {relative}")
    return HandoffFileReceipt(
        file_id=_file_id(kind, relative),
        kind=kind,  # type: ignore[arg-type]
        path=relative,
        sha256=sha256_file(path),
        byte_size=_file_size(path),
        media_type=_media_type(path),
    )


def _source_artifact(root: Path, path: Path, kind: str) -> SourceArtifact:
    """Create one exact job-relative source artifact after containment verification."""

    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("source handoff artifact escapes the job workspace") from exc
    if _is_link_like(path) or not file_exists(path):
        raise FileNotFoundError(path)
    return SourceArtifact(
        kind=kind,  # type: ignore[arg-type]
        path=job_relative(root, path),
        sha256=sha256_file(path),
        byte_size=_file_size(path),
    )


def _package_directory(root: Path, profile_id: str, package_id: str) -> Path:
    """Resolve one requested package directory without accepting path-like identifiers."""

    validate_filesystem_id(package_id, "package_id")
    base = root / "exports" / "packages" / profile_id
    return resolve_inside(base, package_id, "portable package")


def _package_relative_path(package: ExportPackageManifest, value: str) -> str:
    """Convert one job-relative package receipt into its package-root-relative path."""

    try:
        return PurePosixPath(value).relative_to(PurePosixPath(package.package_root)).as_posix()
    except ValueError as exc:
        raise ValueError("package receipt does not stay below package_root") from exc


def _verify_source_package(
    root: Path,
    profile_id: str,
    package_id: str,
) -> tuple[Path, Path, ExportPackageManifest, dict[str, Path]]:
    """Verify a complete package, all receipts, containment, and untracked-file absence."""

    package_root = _package_directory(root, profile_id, package_id)
    if _is_link_like(package_root) or not _is_directory(package_root):
        raise FileNotFoundError(f"portable package is missing or link-like: {package_id}")
    manifest_path = package_root / "package_manifest.json"
    package = load_model(manifest_path, ExportPackageManifest)
    if (
        package.job_id != root.name
        or package.profile_id != profile_id
        or package.package_id != package_id
        or package.status != "complete"
    ):
        raise ValueError("package manifest identity or lifecycle does not match the request")
    declared_root = resolve_inside(root, package.package_root, "declared package root")
    if declared_root != package_root.resolve():
        raise ValueError("package manifest package_root does not match its directory")

    verified: dict[str, Path] = {}
    for item in package.files:
        path = resolve_inside(root, item.path, f"package file {item.id}")
        try:
            path.relative_to(package_root.resolve())
        except ValueError as exc:
            raise ValueError(f"package file escapes its package root: {item.id}") from exc
        if _is_link_like(path) or not file_exists(path):
            raise FileNotFoundError(f"package dependency is missing or link-like: {item.id}")
        if _file_size(path) != item.byte_size or sha256_file(path) != item.sha256:
            raise RuntimeError(f"package receipt changed: {item.id}")
        verified[item.id] = path

    actual = {
        _relative_posix(package_root, path) for path in _walk_regular_files(package_root)
    }
    tracked = {
        _relative_posix(package_root, path) for path in verified.values()
    }
    untracked = actual - tracked - {_relative_posix(package_root, manifest_path)}
    if untracked:
        raise RuntimeError(f"portable package contains untracked files: {sorted(untracked)}")
    if tracked - actual:
        raise RuntimeError("portable package has receipts without files")
    return package_root, manifest_path, package, verified


def _verify_roundtrip(
    root: Path,
    package: ExportPackageManifest,
    manifest_path: Path,
) -> tuple[Path, RoundTripValidation, Path]:
    """Require a passed clean-import report bound to the exact package manifest hash."""

    roundtrip_root = (
        root / "optimization" / "runs" / package.run_id / "roundtrip" / package.package_id
    )
    report_path = roundtrip_root / "roundtrip_validation.json"
    report = load_model(report_path, RoundTripValidation)
    if (
        report.job_id != package.job_id
        or report.profile_id != package.profile_id
        or report.package_id != package.package_id
        or report.run_id != package.run_id
        or report.status != "passed"
        or not report.ok
    ):
        raise RuntimeError("destination handoff requires a passed matching round trip")
    if report.package_manifest.sha256 != sha256_file(manifest_path):
        raise RuntimeError("round-trip validation is stale for the current package manifest")
    evidence_path = resolve_inside(root, report.imported_inventory.path, "round-trip evidence")
    try:
        evidence_path.relative_to(roundtrip_root.resolve())
    except ValueError as exc:
        raise ValueError("round-trip evidence escapes its validation directory") from exc
    if _is_link_like(evidence_path) or not file_exists(evidence_path):
        raise FileNotFoundError("round-trip evidence is missing or link-like")
    if sha256_file(evidence_path) != report.imported_inventory.sha256:
        raise RuntimeError("round-trip evidence hash no longer matches its report")
    if (
        package.profile_id in {"fbx_interchange", "portable_gltf"}
        and package.material_conversion is not None
    ):
        evidence = _json_object(evidence_path, "round-trip evidence")
        portable_binding = evidence.get("readiness", {}).get(
            "portable_uv_binding", {}
        )
        if (
            not isinstance(portable_binding, dict)
            or portable_binding.get("status") != "verified"
        ):
            raise RuntimeError(
                "converted portable handoff requires verified atlas UV0 and tangent "
                "binding"
            )
    return report_path, report, evidence_path


def _snapshot_package(package_root: Path) -> dict[str, tuple[str, int]]:
    """Hash every regular source package file to prove generation caused no mutation."""

    snapshot: dict[str, tuple[str, int]] = {}
    for path in _walk_regular_files(package_root):
        relative = _relative_posix(package_root, path)
        snapshot[relative] = (sha256_file(path), _file_size(path))
    return snapshot


def _write_text(path: Path, value: str) -> None:
    """Write one deterministic UTF-8 text artifact with a final newline."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    with open(native_io_path(path), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(value.rstrip() + "\n")


def plan_destination_handoff(
    job_id: str,
    *,
    profile_id: str,
    package_id: str,
    handoff_id: str | None = None,
    destination_hint: str | None = None,
) -> DestinationHandoffPlan:
    """Create an immutable plan bound to a passed package without copying any asset."""

    _require_handoff_feature()
    _require_profile(profile_id)
    root = job_dir(job_id)
    if not root.is_dir():
        raise FileNotFoundError(f"job does not exist: {job_id}")
    selected_handoff_id = handoff_id or _portable_handoff_id("handoff")
    validate_filesystem_id(selected_handoff_id, "handoff_id")
    if selected_handoff_id.casefold() != selected_handoff_id:
        raise ValueError("handoff_id must be lowercase")
    package_root, manifest_path, package, _files = _verify_source_package(
        root, profile_id, package_id
    )
    report_path, _report, evidence_path = _verify_roundtrip(root, package, manifest_path)
    output_root = (
        root
        / "exports"
        / "destination_handoffs"
        / profile_id
        / package_id
        / selected_handoff_id
    )
    plan = DestinationHandoffPlan(
        plan_id=f"handoff-plan-{selected_handoff_id}",
        handoff_id=selected_handoff_id,
        job_id=job_id,
        profile_id=profile_id,  # type: ignore[arg-type]
        package_id=package_id,
        run_id=package.run_id,
        package_root=job_relative(root, package_root),
        package_manifest=_source_artifact(root, manifest_path, "package_manifest"),
        roundtrip_validation=_source_artifact(
            root, report_path, "roundtrip_validation"
        ),
        roundtrip_evidence=_source_artifact(root, evidence_path, "roundtrip_evidence"),
        output_root=job_relative(root, output_root),
        destination_hint=destination_hint,
        supported_scope=SUPPORTED_SCOPE,
        excluded_scope=EXCLUDED_SCOPE,
        created_at=utc_now(),
    )
    plans_root = root / "handoffs"
    plans_root.mkdir(parents=True, exist_ok=True)
    final_root = plans_root / selected_handoff_id
    if final_root.exists() or output_root.exists():
        raise FileExistsError(f"destination handoff ID already exists: {selected_handoff_id}")
    staging = plans_root / f".{uuid4().hex[:8]}.tmp"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        write_model(staging / "handoff_plan.json", plan)
        os.replace(staging, final_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return plan


def _load_handoff_plan(
    root: Path,
    handoff_id: str,
    approved_plan_sha256: str,
) -> tuple[Path, DestinationHandoffPlan]:
    """Load one exact plan and reject stale or mismatched generation authorization."""

    validate_filesystem_id(handoff_id, "handoff_id")
    plan_path = root / "handoffs" / handoff_id / "handoff_plan.json"
    plan = load_model(plan_path, DestinationHandoffPlan)
    if plan.handoff_id != handoff_id or plan.job_id != root.name:
        raise ValueError("handoff plan does not match the requested job or ID")
    if sha256_file(plan_path) != approved_plan_sha256.lower():
        raise PermissionError("handoff generation requires the exact current plan SHA-256")
    return plan_path, plan


def _copy_verified_package(
    package_root: Path,
    manifest_path: Path,
    package: ExportPackageManifest,
    verified: dict[str, Path],
    destination: Path,
) -> dict[str, Path]:
    """Copy only verified package receipts plus its immutable manifest into the envelope."""

    destination.mkdir(parents=True, exist_ok=False)
    copied: dict[str, Path] = {}
    for item in package.files:
        relative = _package_relative_path(package, item.path)
        target = destination.joinpath(*PurePosixPath(relative).parts)
        _copy_file(verified[item.id], target)
        if _file_size(target) != item.byte_size or sha256_file(target) != item.sha256:
            raise RuntimeError(f"copied package receipt failed verification: {item.id}")
        copied[item.id] = target
    copied_manifest = destination / "package_manifest.json"
    _copy_file(manifest_path, copied_manifest)
    if sha256_file(copied_manifest) != sha256_file(manifest_path):
        raise RuntimeError("copied package manifest does not match the source")
    actual = {
        _relative_posix(destination, path) for path in _walk_regular_files(destination)
    }
    expected = {
        _relative_posix(destination, path) for path in copied.values()
    } | {_relative_posix(destination, copied_manifest)}
    if actual != expected:
        raise RuntimeError("copied package contains unexpected or missing files")
    return copied


def _json_object(path: Path, label: str) -> dict[str, Any]:
    """Load one required JSON object without accepting arrays or scalar payloads."""

    try:
        with open(native_io_path(path), encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label} JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _optional_json(path: Path) -> dict[str, Any]:
    """Load an optional JSON object or return an empty mapping when it is absent."""

    return _json_object(path, path.name) if file_exists(path) else {}


def _canonical_parent_map(root: Path, package: ExportPackageManifest) -> dict[str, str]:
    """Read advisory parent relationships from the current canonical source contract."""

    if package.source.source_kind == "external_static_asset":
        artifact = package.source.external_asset_manifest
        if artifact is None:
            return {}
        manifest_path = resolve_inside(root, artifact.path, "external asset manifest")
        if not file_exists(manifest_path) or sha256_file(manifest_path) != artifact.sha256:
            return {}
        with open(native_io_path(manifest_path), encoding="utf-8") as handle:
            manifest = ExternalAssetManifest.model_validate_json(handle.read())
        return {
            item.semantic_id: item.parent_semantic_id
            for item in manifest.objects
            if item.parent_semantic_id is not None
        }
    artifact = package.source.scene_spec
    if artifact is None:
        return {}
    scene_path = resolve_inside(root, artifact.path, "source SceneSpec")
    if not file_exists(scene_path) or sha256_file(scene_path) != artifact.sha256:
        return {}
    spec = load_scene_spec(scene_path)
    return {
        item.id: item.parent_id
        for item in spec.objects
        if getattr(item, "parent_id", None) is not None
    }


def _export_object_index(export_evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index strict-enough export evidence objects by their unique exported name."""

    objects = export_evidence.get("objects", [])
    if not isinstance(objects, list):
        raise ValueError("export evidence objects must be a list")
    index: dict[str, dict[str, Any]] = {}
    for item in objects:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("export evidence contains an invalid object record")
        name = item["name"]
        if name in index:
            raise ValueError(f"export evidence contains a duplicate object name: {name}")
        index[name] = item
    return index


def _vec3(value: Any, label: str) -> tuple[float, float, float]:
    """Normalize one finite three-number export field into a tuple."""

    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must contain three numbers")
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain three numbers") from exc
    return result  # type: ignore[return-value]


def _build_assembly_manifest(
    root: Path,
    handoff_id: str,
    package: ExportPackageManifest,
    package_manifest_sha256: str,
    primary_path: str,
    delivery_mapping: dict[str, Any],
    export_evidence: dict[str, Any],
) -> AssemblyManifest:
    """Convert package delivery evidence into a flat, semantic reconstruction manifest."""

    records = delivery_mapping.get("objects", [])
    if not isinstance(records, list) or not records:
        raise ValueError("delivery mapping must contain exported objects")
    evidence_by_name = _export_object_index(export_evidence)
    parent_map = _canonical_parent_map(root, package)
    semantic_counts = Counter(
        str(item.get("semantic_id")) for item in records if isinstance(item, dict)
    )
    nodes: list[AssemblyNode] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("delivery mapping contains an invalid object record")
        name = record.get("name")
        semantic_id = record.get("semantic_id")
        role = record.get("asset_role")
        if not isinstance(name, str) or not isinstance(semantic_id, str):
            raise ValueError("delivery mapping object lacks name or semantic_id")
        if role not in {"render", "lod", "collider"}:
            raise ValueError(f"unsupported delivery role for {name}: {role}")
        evidence = evidence_by_name.get(name)
        if evidence is None:
            raise ValueError(f"delivery object lacks matching export evidence: {name}")
        location = _vec3(evidence.get("location"), f"{name}.location")
        rotation = _vec3(evidence.get("rotation_euler"), f"{name}.rotation_euler")
        scale = _vec3(evidence.get("scale"), f"{name}.scale")
        bbox = evidence.get("bbox_world")
        if not isinstance(bbox, dict):
            raise ValueError(f"{name}.bbox_world is missing")
        minimum = _vec3(bbox.get("min"), f"{name}.bbox_world.min")
        instance_index = record.get("instance_index")
        relation = (
            "explicit_index"
            if isinstance(instance_index, int)
            else "advisory"
            if semantic_counts[semantic_id] > 1
            else "unavailable"
        )
        material_ids = record.get("material_ids", [])
        if not isinstance(material_ids, list) or not all(
            isinstance(item, str) for item in material_ids
        ):
            raise ValueError(f"{name}.material_ids is invalid")
        lod_level = record.get("lod_level")
        if role == "render" and lod_level is None:
            lod_level = 0
        normalized_lod_level = lod_level if isinstance(lod_level, int) else None
        lod_group_id = None
        if role != "collider":
            group_source = f"{semantic_id}\0{instance_index!r}"
            lod_group_id = "lodgroup." + hashlib.sha256(
                group_source.encode("utf-8")
            ).hexdigest()[:20]
        node = AssemblyNode(
            export_key=str(record.get("export_key") or name),
            object_name=name,
            semantic_id=semantic_id,
            instance_index=instance_index if isinstance(instance_index, int) else None,
            canonical_parent_semantic_id=parent_map.get(semantic_id),
            transform=TransformSnapshot(
                translation_m=location,
                rotation_euler_rad=rotation,
                scale=scale,
            ),
            material_ids=material_ids,
            lod_level=normalized_lod_level,
            lod_group_id=lod_group_id,
            default_active=role != "collider" and normalized_lod_level == 0,
            collider_target_id=semantic_id if role == "collider" else None,
            render_object=role != "collider",
            asset_role=role,
            source_package_file=primary_path,
            repeated_instance_relation=relation,
            pivot=PivotSnapshot(
                origin_translation_m=location,
                base_plane_z_m=minimum[2],
            ),
        )
        nodes.append(node)
    return AssemblyManifest(
        handoff_id=handoff_id,
        package_manifest_sha256=package_manifest_sha256,
        primary_model=primary_path,
        nodes=nodes,
        semantic_ids=sorted({item.semantic_id for item in nodes}),
        material_ids=sorted(
            {material for item in nodes for material in item.material_ids}
        ),
    )


def _texture_receipt_by_source_path(
    package: ExportPackageManifest,
    package_file_receipts: dict[str, HandoffFileReceipt],
) -> dict[str, HandoffFileReceipt]:
    """Index envelope texture receipts by their original job-relative package paths."""

    result: dict[str, HandoffFileReceipt] = {}
    for item in package.files:
        if item.kind == "texture" and item.id in package_file_receipts:
            result[item.path] = package_file_receipts[item.id]
    return result


def _channel_meaning(channel: str) -> tuple[str, str]:
    """Return portable color-space and semantic text for one PBR channel."""

    values = {
        "base_color": ("sRGB", "surface albedo"),
        "normal": ("Non-Color", "OpenGL tangent-space normal"),
        "metallic": ("Non-Color", "scalar metalness"),
        "roughness": ("Non-Color", "scalar perceptual roughness"),
        "occlusion": ("Non-Color", "ambient occlusion multiplier"),
        "emission": ("sRGB", "emissive color"),
        "opacity": ("Non-Color", "opacity or declared alpha coverage"),
    }
    return values[channel]


def _build_material_mapping(
    handoff_id: str,
    package: ExportPackageManifest,
    package_manifest_sha256: str,
    texture_pack: dict[str, Any],
    material_conversion: dict[str, Any],
    export_evidence: dict[str, Any],
    package_file_receipts: dict[str, HandoffFileReceipt],
) -> MaterialMappingManifest:
    """Build portable mappings and prefer one verified global atlas when converted."""

    texture_by_source = _texture_receipt_by_source_path(package, package_file_receipts)
    conversion_hashes = {
        str(item.get("channel")): str(item.get("sha256"))
        for item in material_conversion.get("outputs", [])
        if isinstance(item, dict)
        and isinstance(item.get("channel"), str)
        and isinstance(item.get("sha256"), str)
    }
    candidates: dict[tuple[str, str], list[tuple[int, dict[str, Any], dict[str, Any]]]] = {}
    for texture in texture_pack.get("textures", []):
        if not isinstance(texture, dict):
            continue
        output = texture.get("output", {})
        output_path = output.get("path") if isinstance(output, dict) else None
        receipt = texture_by_source.get(output_path) if isinstance(output_path, str) else None
        if receipt is None:
            continue
        packing = texture.get("packing")
        texture_id = str(texture.get("texture_id", ""))
        portable_atlas = (
            texture_id.startswith("texture.conversion.")
            and isinstance(output_path, str)
            and "/portable_atlas/" in output_path.replace("\\", "/")
        )
        priority = 0 if portable_atlas else 1 if packing == "raw_channels" else 2
        mappings = texture.get("mappings", [])
        material_ids = texture.get("material_ids", [])
        if not isinstance(mappings, list) or not isinstance(material_ids, list):
            continue
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue
            source_channel = mapping.get("source_channel")
            if source_channel not in {
                "base_color",
                "normal",
                "metallic",
                "roughness",
                "occlusion",
                "emission",
                "opacity",
            }:
                continue
            for material_id in material_ids:
                if isinstance(material_id, str):
                    candidates.setdefault((material_id, source_channel), []).append(
                        (priority, texture, mapping)
                    )
    conversion_by_id = {
        item.get("material_id"): item
        for item in material_conversion.get("entries", [])
        if isinstance(item, dict) and isinstance(item.get("material_id"), str)
    }
    uv_contract = export_evidence.get("uv_binding_contract", {})
    if material_conversion and (
        not isinstance(uv_contract, dict) or uv_contract.get("status") != "verified"
    ):
        raise RuntimeError("portable material mapping requires verified export UV binding")
    coordinate_binding = (
        TextureCoordinateBinding(
            required_uv_set=str(uv_contract["required_uv_set"]),
            required_uv_channel_index=uv_contract["required_uv_channel_index"],
            destination_semantic=str(
                uv_contract.get("destination_semantic", "TEXCOORD_0")
            ),
            tangent_uv_set=str(uv_contract["tangent_uv_set"]),
        )
        if material_conversion
        else None
    )
    materials: list[PortableMaterialMapping] = []
    channels = (
        "base_color",
        "normal",
        "metallic",
        "roughness",
        "occlusion",
        "emission",
        "opacity",
    )
    for material_id in sorted(package.material_ids):
        conversion = conversion_by_id.get(material_id, {})
        mappings: list[MaterialChannelMapping] = []
        for channel in channels:
            color_space, meaning = _channel_meaning(channel)
            options = sorted(
                candidates.get((material_id, channel), []),
                key=lambda item: (item[0], str(item[1].get("texture_id", ""))),
            )
            if conversion:
                options = [
                    option
                    for option in options
                    if option[0] == 0
                    and option[1].get("output", {}).get("sha256")
                    == conversion_hashes.get(channel)
                ]
            if not options:
                mappings.append(
                    MaterialChannelMapping(
                        channel=channel,  # type: ignore[arg-type]
                        status="unavailable",
                        color_space=color_space,  # type: ignore[arg-type]
                        meaning=meaning,
                    )
                )
                continue
            priority, texture, mapping = options[0]
            output = texture["output"]
            receipt = texture_by_source[output["path"]]
            mappings.append(
                MaterialChannelMapping(
                    channel=channel,  # type: ignore[arg-type]
                    status="available" if priority == 0 else "packed",
                    file=receipt,
                    component=mapping.get("output_channel"),
                    color_space=texture.get("color_space", color_space),
                    meaning=meaning,
                )
            )
        losses = conversion.get("losses", []) if isinstance(conversion, dict) else []
        warnings = conversion.get("warnings", []) if isinstance(conversion, dict) else []
        materials.append(
            PortableMaterialMapping(
                material_id=material_id,
                mapping_mode="uv" if conversion else "portable_package",
                source_mapping_mode=str(conversion.get("mapping_mode", "unknown")),
                portable_mapping_mode="uv" if conversion else "unverified",
                texture_representation=(
                    "portable_global_atlas"
                    if conversion
                    else "preserved_raw_channels"
                ),
                texture_coordinate_binding=coordinate_binding if conversion else None,
                channels=mappings,
                blender_master_shader_baked=bool(conversion),
                known_losses=[str(item) for item in losses] if isinstance(losses, list) else [],
                warnings=[str(item) for item in warnings] if isinstance(warnings, list) else [],
            )
        )
    return MaterialMappingManifest(
        handoff_id=handoff_id,
        package_manifest_sha256=package_manifest_sha256,
        pbr_contract=RawPBRContract(),
        materials=materials,
    )


def _build_import_checklist(handoff_id: str) -> ImportChecklist:
    """Create the fixed destination safety and approval checklist requested for V0.9."""

    rows = [
        (
            "immutable-evidence",
            "Treat package files and metadata as immutable evidence.",
            "pre_plan",
        ),
        (
            "detect-destination",
            "Detect the destination engine, version, and render pipeline.",
            "pre_plan",
        ),
        ("avoid-support-claims", "Do not claim support from detection alone.", "pre_plan"),
        ("draft-import-plan", "Write import_plan.json before copying or modifying files.", "plan"),
        (
            "report-reconstruction",
            "Report axis, units, pivot, hierarchy, materials, textures, LOD, and colliders.",
            "plan",
        ),
        (
            "map-portable-channels",
            "Plan destination channel conversions without assuming Blender shader transfer.",
            "plan",
        ),
        (
            "verify-uv0-binding",
            "Verify required_uv_set imports as TEXCOORD_0 and drives normal-map tangents.",
            "plan",
        ),
        (
            "plan-lod-membership",
            "Plan mutually exclusive LOD groups with only each group's LOD0 active by default.",
            "plan",
        ),
        (
            "show-losses",
            "Show expected files, transformations, and known losses to the user.",
            "plan",
        ),
        (
            "request-approval",
            "Obtain explicit user approval for the exact import plan.",
            "approval",
        ),
        (
            "apply-approved-plan",
            "Modify the destination only after approval and within the plan.",
            "apply",
        ),
        ("write-receipt", "Write import_receipt.json for all destination changes.", "apply"),
        (
            "validate-import",
            "Write import_validation.json and report unresolved dependencies.",
            "validate",
        ),
        (
            "honor-exclusions",
            "Exclude rigs, animation, gameplay logic, and unapproved advanced shaders.",
            "validate",
        ),
    ]
    items: list[ImportChecklistItem] = []
    for index, (item_id, instruction, gate) in enumerate(rows, start=1):
        items.append(
            ImportChecklistItem(
                order=index,
                item_id=item_id,
                title=item_id.replace("-", " ").title(),
                instruction=instruction,
                gate=gate,  # type: ignore[arg-type]
            )
        )
    return ImportChecklist(handoff_id=handoff_id, items=items)


def _destination_context(
    plan: DestinationHandoffPlan,
    primary_path: str,
    package: ExportPackageManifest,
    roundtrip: RoundTripValidation,
    export_evidence: dict[str, Any],
    assembly: AssemblyManifest,
) -> DestinationContext:
    """Build the destination context from verified package and round-trip evidence."""

    coordinate = export_evidence.get("coordinate_contract", {})
    if not isinstance(coordinate, dict):
        coordinate = {}
    axis = AxisContract(
        interchange_up_axis=coordinate.get("export_up_axis", "+Y"),
        interchange_forward_axis=coordinate.get("export_forward_axis", "-Z"),
        file_metadata_verified=bool(coordinate.get("file_metadata_verified", False)),
    )
    lod_levels = sorted(
        {
            node.lod_level
            for node in assembly.nodes
            if node.asset_role == "lod" and node.lod_level is not None
        }
    )
    lod_group_ids = {
        node.lod_group_id
        for node in assembly.nodes
        if node.asset_role == "lod" and node.lod_group_id is not None
    }
    collider_count = sum(node.asset_role == "collider" for node in assembly.nodes)
    losses = [*package.known_losses]
    unverified = [
        "destination engine, version, and render pipeline",
        "destination runtime material and shader parity",
        "destination import axis and unit behavior until import validation",
        "destination instancing, draw calls, physics, and LOD selection behavior",
    ]
    if not axis.file_metadata_verified:
        unverified.append("interchange file metadata beyond export-operator evidence")
    unverified.extend(
        "clean-import warning: " + _bounded_handoff_warning(check.message, max_length=500)
        for check in roundtrip.checks
        if check.status == "warning"
    )
    return DestinationContext(
        handoff_id=plan.handoff_id,
        profile_id=plan.profile_id,
        primary_model=primary_path,
        axis=axis,
        pivot_policy=(
            "Preserve each exported object origin first; use the recorded source +Z base plane "
            "only when the destination plan explicitly changes placement."
        ),
        expected_bounds=roundtrip.bounds.source,
        hierarchy=HierarchySummary(),
        pbr=RawPBRContract(),
        lod_and_collider=LODColliderSummary(
            lod_present=bool(lod_levels),
            lod_levels=lod_levels,
            lod_group_count=len(lod_group_ids),
            membership_explicit=bool(lod_group_ids),
            collider_present=collider_count > 0,
            collider_count=collider_count,
        ),
        known_format_losses=losses,
        unverified_items=unverified,
        destination_hint=plan.destination_hint,
    )


def _limitations_text(context: DestinationContext) -> str:
    """Render bounded known limitations without embedding executable instructions."""

    lines = [
        "# Known limitations",
        "",
        "This handoff is an engine-neutral static-asset delivery contract.",
        "",
        "## Excluded scope",
        *[f"- {item}" for item in EXCLUDED_SCOPE],
        "",
        "## Format losses",
        *([f"- {item}" for item in context.known_format_losses] or ["- None declared."]),
        "",
        "## Unverified items",
        *[f"- {item}" for item in context.unverified_items],
        "",
        "Blender procedural master shaders are not assumed to survive interchange. Use only the "
        "portable channels recorded in material_mapping.json unless the destination plan "
        "explicitly authors an approved replacement.",
    ]
    return "\n".join(lines)


def _copy_import_schemas(destination: Path) -> list[Path]:
    """Copy strict destination result schemas into the movable handoff envelope."""

    source_root = get_settings().repo_root / "schemas"
    os.makedirs(native_io_path(destination), exist_ok=True)
    copied: list[Path] = []
    for filename in IMPORT_SCHEMA_FILENAMES:
        source = source_root / filename
        if not file_exists(source):
            raise FileNotFoundError(f"required destination schema is missing: {filename}")
        target = destination / filename
        _copy_file(source, target)
        copied.append(target)
    return copied


def _classify_envelope_file(path: Path, primary: Path, textures: set[Path]) -> str:
    """Classify one generated envelope file for final validation receipts."""

    if path == primary:
        return "primary_model"
    if path in textures:
        return "texture"
    by_name = {
        "package_manifest.json": "package_manifest",
        "roundtrip_validation.json": "roundtrip_validation",
        "roundtrip_evidence.json": "roundtrip_evidence",
        "destination_context.json": "destination_context",
        "assembly_manifest.json": "assembly_manifest",
        "material_mapping.json": "material_mapping",
        "import_checklist.json": "import_checklist",
        "codex_import_prompt.md": "prompt_template",
        "known_limitations.md": "known_limitations",
        "handoff_manifest.json": "handoff_manifest",
        "handoff_report.pdf": "pdf_report",
        "handoff_report.manifest.json": "pdf_manifest",
    }
    if path.name in IMPORT_SCHEMA_FILENAMES:
        return "import_schema"
    if path.name in by_name:
        return by_name[path.name]
    return "package_file" if "package" in path.parts else "other"


def _source_fingerprint(receipts: list[HandoffFileReceipt]) -> str:
    """Hash ordered machine-source paths and digests for a PDF sidecar fingerprint."""

    digest = hashlib.sha256()
    for item in sorted(receipts, key=lambda receipt: receipt.path):
        digest.update(item.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _write_handoff_pdf(
    envelope: Path,
    handoff_root: Path,
    manifest: DestinationHandoffManifest,
    context: DestinationContext,
    assembly: AssemblyManifest,
    materials: MaterialMappingManifest,
    checklist: ImportChecklist,
) -> tuple[Path, Path]:
    """Create a derived handoff PDF and exact source-hash sidecar manifest."""

    pdf_path = handoff_root / "handoff_report.pdf"
    source_paths = [
        handoff_root / "handoff_manifest.json",
        handoff_root / "destination_context.json",
        handoff_root / "assembly_manifest.json",
        handoff_root / "material_mapping.json",
        handoff_root / "import_checklist.json",
    ]
    sources = [
        _receipt(envelope, path, _classify_envelope_file(path, Path(), set()))
        for path in source_paths
    ]
    render_handoff_pdf(
        {
            "handoff_manifest": manifest.model_dump(mode="json"),
            "destination_context": context.model_dump(mode="json"),
            "assembly_manifest": assembly.model_dump(mode="json"),
            "material_mapping": materials.model_dump(mode="json"),
            "import_checklist": checklist.model_dump(mode="json"),
        },
        pdf_path,
    )
    sidecar_path = handoff_root / "handoff_report.manifest.json"
    sidecar = HandoffReportManifest(
        handoff_id=manifest.handoff_id,
        pdf_path=pdf_path.relative_to(envelope).as_posix(),
        pdf_sha256=sha256_file(pdf_path),
        source_fingerprint=_source_fingerprint(sources),
        sources=sources,
        generated_at=utc_now(),
        warnings=[
            "PDF is derived; machine-readable JSON remains authoritative.",
            "Destination runtime parity is not verified by this report.",
        ],
    )
    write_model(sidecar_path, sidecar)
    return pdf_path, sidecar_path


def _bounded_handoff_warning(message: str, max_length: int = 2000) -> str:
    """Bound copied warning text while hash-linking it to full round-trip evidence."""

    if len(message) <= max_length:
        return message
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    suffix = (
        "... [truncated in handoff summary; full warning remains in round-trip "
        f"evidence; sha256={digest}]"
    )
    return message[: max_length - len(suffix)] + suffix


def _validation_checks(
    roundtrip: RoundTripValidation,
) -> list[HandoffValidationCheck]:
    """Return handoff checks while preserving non-blocking round-trip warnings."""

    rows = [
        ("package-current", "package", "Source package receipts remain current."),
        ("roundtrip-passed", "roundtrip", "Clean-import round trip is passed and hash-bound."),
        ("relative-paths", "path", "All handoff paths are normalized and relative."),
        ("file-receipts", "hash", "Every envelope file has an exact SHA-256 receipt."),
        ("assembly-coverage", "assembly", "Assembly identities cover exported objects."),
        ("material-coverage", "material", "Portable material IDs have channel mappings."),
        ("safe-prompt", "prompt", "Destination prompt contains approval and non-execution rules."),
        ("pdf-derived", "pdf", "PDF sidecar binds exact JSON source hashes."),
        ("dependencies-present", "dependency", "No declared package dependency is missing."),
    ]
    checks = [
        HandoffValidationCheck(
            check_id=check_id,
            category=category,  # type: ignore[arg-type]
            status="passed",
            message=message,
        )
        for check_id, category, message in rows
    ]
    checks.extend(
        HandoffValidationCheck(
            check_id=f"roundtrip-warning-{index:03d}",
            category="roundtrip",
            status="warning",
            message=_bounded_handoff_warning(item.message),
        )
        for index, item in enumerate(
            (check for check in roundtrip.checks if check.status == "warning"),
            start=1,
        )
    )
    return checks


def generate_destination_handoff(
    job_id: str,
    handoff_id: str,
    *,
    approved_plan_sha256: str,
) -> DestinationHandoffValidation:
    """Generate one immutable, hash-bound handoff envelope without changing source data."""

    _require_handoff_feature()
    root = job_dir(job_id)
    _plan_path, plan = _load_handoff_plan(root, handoff_id, approved_plan_sha256)
    package_root, manifest_path, package, verified = _verify_source_package(
        root, plan.profile_id, plan.package_id
    )
    report_path, roundtrip, evidence_path = _verify_roundtrip(root, package, manifest_path)
    source_snapshot = _snapshot_package(package_root)
    if (
        plan.package_manifest.sha256 != sha256_file(manifest_path)
        or plan.roundtrip_validation.sha256 != sha256_file(report_path)
        or plan.roundtrip_evidence.sha256 != sha256_file(evidence_path)
    ):
        raise RuntimeError("handoff plan is stale for the current package or round-trip evidence")
    output = resolve_inside(root, plan.output_root, "handoff output")
    expected_parent = root / "exports" / "destination_handoffs" / plan.profile_id / plan.package_id
    if output.parent.resolve() != expected_parent.resolve():
        raise ValueError("handoff output root no longer matches the planned package boundary")
    if output.exists():
        raise FileExistsError(f"destination handoff already exists: {plan.handoff_id}")
    expected_parent.mkdir(parents=True, exist_ok=True)
    staging = expected_parent / f".{uuid4().hex[:8]}.tmp"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        copied = _copy_verified_package(
            package_root, manifest_path, package, verified, staging / "package"
        )
        evidence_root = staging / "evidence"
        evidence_root.mkdir()
        copied_roundtrip = evidence_root / "roundtrip_validation.json"
        copied_evidence = evidence_root / "roundtrip_evidence.json"
        _copy_file(report_path, copied_roundtrip)
        _copy_file(evidence_path, copied_evidence)
        if sha256_file(copied_roundtrip) != plan.roundtrip_validation.sha256:
            raise RuntimeError("copied round-trip validation hash mismatch")
        if sha256_file(copied_evidence) != plan.roundtrip_evidence.sha256:
            raise RuntimeError("copied round-trip evidence hash mismatch")

        package_receipts: dict[str, HandoffFileReceipt] = {}
        copied_textures: set[Path] = set()
        for item in package.files:
            target = copied[item.id]
            kind = "texture" if item.kind == "texture" else (
                "primary_model" if item.id == package.primary_file_id else "package_file"
            )
            package_receipts[item.id] = _receipt(staging, target, kind)
            if item.kind == "texture":
                copied_textures.add(target)
        primary_item = next(item for item in package.files if item.id == package.primary_file_id)
        primary_path = copied[primary_item.id]
        primary_relative = primary_path.relative_to(staging).as_posix()
        package_manifest_hash = sha256_file(manifest_path)
        package_manifest_receipt = _receipt(
            staging, staging / "package" / "package_manifest.json", "package_manifest"
        )
        roundtrip_receipt = _receipt(
            staging, copied_roundtrip, "roundtrip_validation"
        )
        roundtrip_evidence_receipt = _receipt(
            staging, copied_evidence, "roundtrip_evidence"
        )

        delivery_mapping = _json_object(
            staging / "package" / "metadata" / "delivery_mapping.json",
            "delivery mapping",
        )
        export_evidence = _json_object(
            staging / "package" / "export_evidence.json",
            "export evidence",
        )
        texture_pack = _optional_json(staging / "package" / "texture_pack_manifest.json")
        material_conversion = _optional_json(
            staging / "package" / "metadata" / "material_conversion_manifest.json"
        )
        assembly = _build_assembly_manifest(
            root,
            plan.handoff_id,
            package,
            package_manifest_hash,
            primary_relative,
            delivery_mapping,
            export_evidence,
        )
        materials = _build_material_mapping(
            plan.handoff_id,
            package,
            package_manifest_hash,
            texture_pack,
            material_conversion,
            export_evidence,
            package_receipts,
        )
        context = _destination_context(
            plan,
            primary_relative,
            package,
            roundtrip,
            export_evidence,
            assembly,
        )
        checklist = _build_import_checklist(plan.handoff_id)

        handoff_root = staging / "codex_handoff"
        handoff_root.mkdir()
        context_path = handoff_root / "destination_context.json"
        assembly_path = handoff_root / "assembly_manifest.json"
        material_path = handoff_root / "material_mapping.json"
        checklist_path = handoff_root / "import_checklist.json"
        write_model(context_path, context)
        write_model(assembly_path, assembly)
        write_model(material_path, materials)
        write_model(checklist_path, checklist)
        prompt_source = get_settings().repo_root / "prompts" / "codex_destination_import.md"
        if not file_exists(prompt_source):
            raise FileNotFoundError("destination Codex prompt template is missing")
        prompt_path = handoff_root / "codex_import_prompt.md"
        _copy_file(prompt_source, prompt_path)
        with open(native_io_path(prompt_path), encoding="utf-8") as handle:
            prompt_text = handle.read()
        required_prompt_tokens = {
            "<PACKAGE_PATH>",
            "<DESTINATION_PROJECT_ROOT>",
            "<OPTIONAL_DESTINATION_HINT>",
            "import_plan.json",
            "import_receipt.json",
        }
        if not required_prompt_tokens <= set(
            token for token in required_prompt_tokens if token in prompt_text
        ):
            raise RuntimeError("destination Codex prompt is missing required safety tokens")
        limitations_path = handoff_root / "known_limitations.md"
        _write_text(limitations_path, _limitations_text(context))
        schema_paths = _copy_import_schemas(handoff_root / "schemas")

        context_receipt = _receipt(staging, context_path, "destination_context")
        assembly_receipt = _receipt(staging, assembly_path, "assembly_manifest")
        material_receipt = _receipt(staging, material_path, "material_mapping")
        checklist_receipt = _receipt(staging, checklist_path, "import_checklist")
        prompt_receipt = _receipt(staging, prompt_path, "prompt_template")
        limitations_receipt = _receipt(staging, limitations_path, "known_limitations")
        schema_receipts = [_receipt(staging, path, "import_schema") for path in schema_paths]
        texture_receipts = [
            package_receipts[item.id]
            for item in package.files
            if item.kind == "texture"
        ]
        core_files = [
            package_manifest_receipt,
            *[package_receipts[item.id] for item in package.files],
            roundtrip_receipt,
            roundtrip_evidence_receipt,
            context_receipt,
            assembly_receipt,
            material_receipt,
            checklist_receipt,
            prompt_receipt,
            limitations_receipt,
            *schema_receipts,
        ]
        manifest = DestinationHandoffManifest(
            handoff_id=plan.handoff_id,
            job_id=job_id,
            profile_id=plan.profile_id,
            package_id=package.package_id,
            run_id=package.run_id,
            package_manifest=package_manifest_receipt,
            roundtrip_validation=roundtrip_receipt,
            primary_model=package_receipts[primary_item.id],
            textures=texture_receipts,
            semantic_ids=package.semantic_ids,
            material_ids=package.material_ids,
            destination_context=context_receipt,
            assembly_manifest=assembly_receipt,
            material_mapping=material_receipt,
            import_checklist=checklist_receipt,
            import_prompt=prompt_receipt,
            known_limitations=limitations_receipt,
            import_schemas=schema_receipts,
            assembly_manifest_sha256=assembly_receipt.sha256,
            material_mapping_sha256=material_receipt.sha256,
            prompt_template_sha256=prompt_receipt.sha256,
            lod_present=context.lod_and_collider.lod_present,
            collider_present=context.lod_and_collider.collider_present,
            supported_scope=plan.supported_scope,
            excluded_scope=plan.excluded_scope,
            core_files=core_files,
            generated_at=utc_now(),
        )
        manifest_output = handoff_root / "handoff_manifest.json"
        write_model(manifest_output, manifest)
        pdf_path, sidecar_path = _write_handoff_pdf(
            staging,
            handoff_root,
            manifest,
            context,
            assembly,
            materials,
            checklist,
        )
        manifest_hash = sha256_file(manifest_output)
        actual_files = sorted(
            (
                path
                for path in _walk_regular_files(staging)
                if path.name != "destination_handoff_validation.json"
            ),
            key=lambda path: _relative_posix(staging, path),
        )
        file_receipts = [
            _receipt(
                staging,
                path,
                _classify_envelope_file(path, primary_path, copied_textures),
            )
            for path in actual_files
        ]
        checks = _validation_checks(roundtrip)
        warning_count = sum(item.status == "warning" for item in checks)
        failed_count = sum(item.status == "failed" for item in checks)
        passed_count = sum(item.status == "passed" for item in checks)
        validation = DestinationHandoffValidation(
            validation_id=f"handoff-validation-{plan.handoff_id}",
            handoff_id=plan.handoff_id,
            job_id=job_id,
            profile_id=plan.profile_id,
            package_id=package.package_id,
            handoff_manifest_sha256=manifest_hash,
            package_manifest_sha256=package_manifest_hash,
            roundtrip_validation_sha256=roundtrip_receipt.sha256,
            status="warning" if warning_count else "passed",
            ok=failed_count == 0,
            passed=passed_count,
            warnings=warning_count,
            failed=failed_count,
            expected_file_count=len(file_receipts),
            files=file_receipts,
            checks=checks,
            missing_dependency_count=0,
            absolute_path_count=0,
            source_package_current=True,
            created_at=utc_now(),
        )
        write_model(staging / "destination_handoff_validation.json", validation)
        if source_snapshot != _snapshot_package(package_root):
            raise RuntimeError("source package changed during handoff generation")
        if not file_exists(pdf_path) or not file_exists(sidecar_path):
            raise RuntimeError("handoff PDF or sidecar was not generated")
        os.replace(staging, output)
        return validation
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _envelope_paths(
    root: Path,
    profile_id: str,
    package_id: str,
    handoff_id: str,
) -> Path:
    """Resolve one handoff envelope inside its profile and package namespace."""

    _require_profile(profile_id)
    for value, label in (
        (package_id, "package_id"),
        (handoff_id, "handoff_id"),
    ):
        validate_filesystem_id(value, label)
    base = root / "exports" / "destination_handoffs" / profile_id / package_id
    return resolve_inside(base, handoff_id, "destination handoff")


def _verify_receipt(envelope: Path, item: HandoffFileReceipt) -> Path:
    """Verify one final envelope receipt without following paths outside its root."""

    path = resolve_inside(envelope, item.path, f"handoff file {item.file_id}")
    if _is_link_like(path) or not file_exists(path):
        raise FileNotFoundError(f"handoff file is missing or link-like: {item.path}")
    if _file_size(path) != item.byte_size or sha256_file(path) != item.sha256:
        raise RuntimeError(f"handoff file receipt changed: {item.path}")
    return path


def validate_destination_handoff(
    job_id: str,
    *,
    profile_id: str,
    package_id: str,
    handoff_id: str,
) -> DestinationHandoffValidation:
    """Read-only validate an envelope, its source binding, and every contained receipt."""

    _require_handoff_feature()
    root = job_dir(job_id)
    envelope = _envelope_paths(root, profile_id, package_id, handoff_id)
    if _is_link_like(envelope) or not _is_directory(envelope):
        raise FileNotFoundError(f"destination handoff is missing or link-like: {handoff_id}")
    validation_path = envelope / "destination_handoff_validation.json"
    validation = load_model(validation_path, DestinationHandoffValidation)
    if (
        validation.job_id != job_id
        or validation.profile_id != profile_id
        or validation.package_id != package_id
        or validation.handoff_id != handoff_id
    ):
        raise ValueError("handoff validation identity does not match the request")
    verified = {
        _relative_posix(envelope, _verify_receipt(envelope, item))
        for item in validation.files
    }
    actual = {_relative_posix(envelope, path) for path in _walk_regular_files(envelope)}
    if actual != verified | {_relative_posix(envelope, validation_path)}:
        raise RuntimeError("handoff envelope contains untracked or missing files")

    handoff_root = envelope / "codex_handoff"
    manifest = load_model(
        handoff_root / "handoff_manifest.json", DestinationHandoffManifest
    )
    load_model(handoff_root / "destination_context.json", DestinationContext)
    load_model(handoff_root / "assembly_manifest.json", AssemblyManifest)
    load_model(handoff_root / "material_mapping.json", MaterialMappingManifest)
    load_model(handoff_root / "import_checklist.json", ImportChecklist)
    load_model(handoff_root / "handoff_report.manifest.json", HandoffReportManifest)
    if sha256_file(handoff_root / "handoff_manifest.json") != validation.handoff_manifest_sha256:
        raise RuntimeError("handoff manifest hash does not match final validation")
    copied_package_manifest = envelope / manifest.package_manifest.path
    if sha256_file(copied_package_manifest) != validation.package_manifest_sha256:
        raise RuntimeError("copied package manifest hash does not match handoff binding")
    copied_roundtrip = envelope / manifest.roundtrip_validation.path
    if sha256_file(copied_roundtrip) != validation.roundtrip_validation_sha256:
        raise RuntimeError("copied round-trip hash does not match handoff binding")

    package_root, source_manifest, package, _verified = _verify_source_package(
        root, profile_id, package_id
    )
    source_roundtrip, _roundtrip, _evidence = _verify_roundtrip(
        root, package, source_manifest
    )
    if (
        sha256_file(source_manifest) != validation.package_manifest_sha256
        or sha256_file(source_roundtrip) != validation.roundtrip_validation_sha256
    ):
        raise RuntimeError("destination handoff is stale for its source package")
    if _snapshot_package(package_root) != _snapshot_package(envelope / "package"):
        raise RuntimeError("copied package is not byte-identical to its source package")
    return validation


def get_destination_handoff_status(job_id: str) -> dict[str, Any]:
    """List handoff plans and classify generated envelopes without changing evidence."""

    _require_handoff_feature()
    root = job_dir(job_id)
    plans: list[dict[str, Any]] = []
    plans_root = root / "handoffs"
    if plans_root.is_dir():
        for plan_path in sorted(plans_root.glob("*/handoff_plan.json")):
            try:
                plan = load_model(plan_path, DestinationHandoffPlan)
                output = resolve_inside(root, plan.output_root, "handoff output")
                status = "planned"
                error: str | None = None
                if output.is_dir():
                    try:
                        validate_destination_handoff(
                            job_id,
                            profile_id=plan.profile_id,
                            package_id=plan.package_id,
                            handoff_id=plan.handoff_id,
                        )
                        status = "valid"
                    except RuntimeError as exc:
                        status = "stale" if "stale" in str(exc).casefold() else "invalid"
                        error = str(exc)
                    except Exception as exc:
                        status = "invalid"
                        error = f"{type(exc).__name__}: {exc}"
                plans.append(
                    {
                        "handoff_id": plan.handoff_id,
                        "profile_id": plan.profile_id,
                        "package_id": plan.package_id,
                        "plan_path": job_relative(root, plan_path),
                        "plan_sha256": sha256_file(plan_path),
                        "output_root": plan.output_root,
                        "status": status,
                        "error": error,
                    }
                )
            except Exception as exc:
                plans.append(
                    {
                        "handoff_id": plan_path.parent.name,
                        "status": "invalid",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    known_ids = {
        str(item.get("handoff_id"))
        for item in plans
        if isinstance(item.get("handoff_id"), str)
    }
    envelopes_root = root / "exports" / "destination_handoffs"
    if envelopes_root.is_dir():
        for validation_path in sorted(
            envelopes_root.glob("*/*/*/destination_handoff_validation.json")
        ):
            handoff_id = validation_path.parent.name
            if handoff_id in known_ids:
                continue
            relative_parts = validation_path.relative_to(envelopes_root).parts
            if len(relative_parts) != 4:
                continue
            profile_id, package_id = relative_parts[0], relative_parts[1]
            try:
                validation = validate_destination_handoff(
                    job_id,
                    profile_id=profile_id,
                    package_id=package_id,
                    handoff_id=handoff_id,
                )
                status = "invalid"
                error = (
                    "Generated handoff is valid internally but its immutable source plan "
                    "is missing."
                )
                output_root = job_relative(root, validation_path.parent)
                if not validation.ok:
                    error = "Generated handoff validation does not report ok=true."
            except Exception as exc:
                status = "invalid"
                error = f"{type(exc).__name__}: {exc}"
                output_root = job_relative(root, validation_path.parent)
            plans.append(
                {
                    "handoff_id": handoff_id,
                    "profile_id": profile_id,
                    "package_id": package_id,
                    "plan_path": None,
                    "plan_sha256": None,
                    "output_root": output_root,
                    "status": status,
                    "error": error,
                }
            )
    valid_count = sum(item["status"] == "valid" for item in plans)
    generated_count = sum(item["status"] in {"valid", "invalid", "stale"} for item in plans)
    overall = (
        "not_requested"
        if not plans
        else "invalid"
        if any(item["status"] == "invalid" for item in plans)
        else "stale"
        if any(item["status"] == "stale" for item in plans)
        else "valid"
        if valid_count
        else "generated"
        if generated_count
        else "planned"
    )
    return {
        "job_id": job_id,
        "status": overall,
        "handoff_count": len(plans),
        "generated_count": generated_count,
        "valid_count": valid_count,
        "handoffs": plans,
    }
