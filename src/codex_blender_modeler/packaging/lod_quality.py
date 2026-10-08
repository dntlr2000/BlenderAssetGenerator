"""Read-only integrity and metrics for explicitly supplied post-export LOD masks.

This diagnostic never supplies rendering attestation, native per-family verification,
publication approval, clean-import evidence, or authority to change an immutable package.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import struct
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image, ImageChops

from ..blender_artifacts import _is_link_or_reparse
from ..optimization.models import (
    AssetProfile,
    LODManifest,
    OptimizationPlan,
    PortableMaterialConversionManifest,
    PortableMaterialConversionPlan,
)
from ..workspace import native_io_path, sha256_file
from .models import ExportPackageManifest

VIEWS = ("canonical", "front", "right", "top")
ASSURANCE = (
    "Integrity and recomputed metrics for supplied exact masks; renderer provenance is "
    "declared, not independently rerendered or attested."
)
LIMITATIONS = [
    ASSURANCE,
    "Discrete views do not prove all-view quality, material appearance, topology, "
    "or runtime switching.",
    "Whole-asset masks can hide individual semantic-part errors through occlusion.",
    "This post-export diagnostic does not alter native quality, clean import, "
    "approval, or acceptance.",
]


def _regular_path(root: Path, relative: str) -> Path:
    """Resolve one ordinary contained file, rejecting links and nonportable relative names."""

    parsed = PurePosixPath(relative)
    if (
        not relative
        or parsed.is_absolute()
        or "\\" in relative
        or ":" in relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise ValueError("LOD diagnostic contains an unsafe relative path")
    root = root.absolute()
    if any(
        _is_link_or_reparse(os.lstat(native_io_path(parent))) for parent in (root, *root.parents)
    ):
        raise ValueError("LOD diagnostic root cannot be a link")
    path = root
    for part in parsed.parts:
        path = path / part
        if _is_link_or_reparse(os.lstat(native_io_path(path))):
            raise ValueError("LOD diagnostic files and directories cannot be links")
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("LOD diagnostic input is absent or escapes its root")
    return path


def _hash(path: Path, expected: str) -> str:
    """Check an explicitly selected exact SHA-256 before consuming an input."""

    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ValueError("LOD diagnostic requires an exact lowercase SHA-256")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError("LOD diagnostic input SHA-256 changed")
    return actual


def _strict_json(data: bytes) -> dict[str, Any]:
    """Parse bounded JSON and reject duplicate keys and non-finite constants."""

    if len(data) > 16 * 1024 * 1024:
        raise ValueError("LOD diagnostic JSON exceeds its bounded input size")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """Reject ambiguous duplicate-key JSON rather than silently keeping one value."""

        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("LOD diagnostic JSON has duplicate keys")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        """Reject JSON NaN and infinity before metrics or camera checks."""

        raise ValueError(f"LOD diagnostic JSON contains non-finite constant: {value}")

    result = json.loads(
        data,
        object_pairs_hook=unique_pairs,
        parse_constant=reject_constant,
    )
    if not isinstance(result, dict):
        raise ValueError("LOD diagnostic JSON must contain an object")
    return result


def _json(path: Path) -> dict[str, Any]:
    """Read one bounded JSON file through the strict diagnostic parser."""

    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("LOD diagnostic JSON exceeds its bounded input size")
    return _strict_json(path.read_bytes())


def _glb_members(path: Path) -> dict[tuple[str, int], list[str]]:
    """Read actual GLB mesh-node identities for exact scope/LOD selection checks."""

    with path.open("rb") as handle:
        header = handle.read(20)
        if len(header) != 20:
            raise ValueError("LOD diagnostic GLB header is incomplete")
        magic, version, length, json_size, chunk_type = struct.unpack("<5I", header)
        if (
            magic != 0x46546C67
            or version != 2
            or length != path.stat().st_size
            or chunk_type != 0x4E4F534A
            or json_size > 16 * 1024 * 1024
            or json_size + 20 > length
        ):
            raise ValueError("LOD diagnostic requires a bounded valid GLB 2 JSON chunk")
        document = _strict_json(handle.read(json_size))
    nodes = document.get("nodes")
    meshes = document.get("meshes")
    scenes = document.get("scenes")
    selected_scene = document.get("scene", 0)
    if (
        not isinstance(nodes, list)
        or not isinstance(meshes, list)
        or not isinstance(scenes, list)
        or type(selected_scene) is not int
        or not 0 <= selected_scene < len(scenes)
    ):
        raise ValueError("LOD GLB lacks a supported active scene and mesh-node graph")
    active: set[int] = set()
    pending = list(scenes[selected_scene].get("nodes", []))
    while pending:
        index = pending.pop()
        if type(index) is not int or not 0 <= index < len(nodes) or index in active:
            raise ValueError("LOD GLB active scene contains invalid or duplicate node references")
        active.add(index)
        node = nodes[index]
        if not isinstance(node, dict):
            raise ValueError("LOD GLB node must be an object")
        pending.extend(node.get("children", []))
    if any("mesh" in node and index not in active for index, node in enumerate(nodes)):
        raise ValueError("LOD GLB contains mesh nodes outside its declared active scene")
    members: dict[tuple[str, int], list[str]] = {}
    names: set[str] = set()
    for node in nodes:
        if "mesh" not in node:
            continue
        if type(node["mesh"]) is not int or not 0 <= node["mesh"] < len(meshes):
            raise ValueError("LOD GLB mesh node has an invalid mesh reference")
        extras = node.get("extras", {})
        if extras.get("cbm_asset_role") == "collider":
            continue
        name, semantic_id, level = (
            node.get("name"),
            extras.get("cbm_id"),
            extras.get("cbm_lod_level"),
        )
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or not isinstance(semantic_id, str)
            or not semantic_id
            or type(level) is not int
            or not 0 <= level <= 8
            or extras.get("cbm_asset_role") != ("render" if level == 0 else "lod")
        ):
            raise ValueError("GLB has ambiguous or missing semantic LOD mesh identity")
        names.add(name)
        members.setdefault((semantic_id, level), []).append(name)
    if not members or len({target for target, _ in members}) > 64:
        raise ValueError("LOD diagnostic requires one to 64 semantic families")
    return {key: sorted(value) for key, value in members.items()}


def _package_inputs(
    manifest_path: Path, expected_sha256: str
) -> tuple[
    ExportPackageManifest, AssetProfile, OptimizationPlan, LODManifest, Path, dict[str, str]
]:
    """Verify relocated package receipts and exact profile/plan/LOD/export snapshot binding."""

    manifest_path = _regular_path(manifest_path.parent, manifest_path.name)
    _hash(manifest_path, expected_sha256)
    package = ExportPackageManifest.model_validate(_json(manifest_path))
    if (
        package.status != "complete"
        or package.content_mode != "full_evidence"
        or package.profile_id != "portable_gltf"
        or package.optimization_plan is None
    ):
        raise ValueError("LOD diagnostic supports complete full_evidence GLB packages only")
    prefix = PurePosixPath(package.package_root)
    paths: dict[str, Path] = {}
    receipts: dict[str, Any] = {}
    for receipt in package.files:
        relative = PurePosixPath(receipt.path).relative_to(prefix).as_posix()
        if relative.casefold() in {key.casefold() for key in paths}:
            raise ValueError("LOD package contains ambiguous case-folded paths")
        path = _regular_path(manifest_path.parent, relative)
        if path.stat().st_size != receipt.byte_size:
            raise ValueError("LOD package receipt size changed")
        _hash(path, receipt.sha256)
        paths[relative], receipts[relative] = path, receipt
    required = {
        "metadata/asset_profile.json",
        "metadata/optimization_plan.json",
        "metadata/lod_manifest.json",
        "metadata/execution_plan.json",
        "metadata/optimized_asset_evidence.json",
        "export_evidence.json",
    }
    if not required <= paths.keys():
        raise ValueError("LOD package lacks required immutable evidence snapshots")
    profile = AssetProfile.model_validate(_json(paths["metadata/asset_profile.json"]))
    plan = OptimizationPlan.model_validate(_json(paths["metadata/optimization_plan.json"]))
    lod = LODManifest.model_validate(_json(paths["metadata/lod_manifest.json"]))
    execution = OptimizationPlan.model_validate(_json(paths["metadata/execution_plan.json"]))
    if (
        execution.job_id != plan.job_id
        or execution.profile_id != plan.profile_id
        or execution.source != plan.source
        or execution.plan_id != plan.plan_id
        or execution.profile_artifact != plan.profile_artifact
        or execution.status != "running"
    ):
        raise ValueError("LOD package has a foreign immutable execution plan")
    for item in (plan, lod):
        if (
            item.job_id != package.job_id
            or item.profile_id != package.profile_id
            or item.source != package.source
        ):
            raise ValueError("LOD package has stale or mixed job/run/source snapshots")
    if lod.run_id != package.run_id:
        raise ValueError("LOD package has foreign run identity")
    if profile.job_id != package.job_id or profile.profile_id != package.profile_id:
        raise ValueError("LOD package has a foreign profile snapshot")
    if plan.status != "complete" or lod.status != "complete":
        raise ValueError("LOD package requires completed optimization and LOD snapshots")
    if (
        plan.profile_artifact.sha256 != receipts["metadata/asset_profile.json"].sha256
        or package.optimization_plan.sha256 != receipts["metadata/optimization_plan.json"].sha256
        or package.optimization_plan.path != receipts["metadata/optimization_plan.json"].path
    ):
        raise ValueError("LOD package profile or optimization hash binding differs")
    outputs = {item.path: item for item in plan.output_manifests}
    for relative, kind in (
        ("metadata/lod_manifest.json", "lod_manifest"),
        ("metadata/execution_plan.json", "optimization_plan"),
        ("metadata/optimized_asset_evidence.json", "other"),
    ):
        original = f"optimization/runs/{package.run_id}/{PurePosixPath(relative).name}"
        if (
            original not in outputs
            or outputs[original].kind != kind
            or outputs[original].sha256 != receipts[relative].sha256
        ):
            raise ValueError("LOD package snapshot is not an exact optimization output")
    raw = _json(paths["metadata/optimized_asset_evidence.json"])
    blend_path = f"optimization/runs/{package.run_id}/optimized/scene.blend"
    blend = outputs.get(blend_path)
    if (
        raw.get("schema_version") != "0.7.0"
        or raw.get("kind") != "optimized_asset_manifest"
        or blend is None
        or blend.kind != "blend"
        or raw.get("ok") is not True
        or raw.get("plan_sha256") != receipts["metadata/execution_plan.json"].sha256
        or raw.get("profile_sha256") != plan.profile_artifact.sha256
        or raw.get("derived", {}).get("blend_sha256") != blend.sha256
        or raw.get("source", {}).get("build_fingerprint") != plan.source.build_fingerprint
        or any(
            entry.mesh.path != blend_path or entry.mesh.sha256 != blend.sha256
            for entry in lod.entries
        )
    ):
        raise ValueError("LOD package has stale or mixed derived-mesh provenance")
    expected_levels = {0, *(target.level for target in profile.lod.targets)}
    targets = {entry.target_id for entry in lod.entries}
    if any(
        {entry.level for entry in lod.entries if entry.target_id == target} != expected_levels
        for target in targets
    ):
        raise ValueError("LOD package manifest levels differ from its profile")
    if lod.quality_status == "verified" and any(
        entry.silhouette_iou is None for entry in lod.entries
    ):
        raise ValueError("Verified LOD quality contains an unmeasured silhouette entry")
    primary_receipt = next(item for item in package.files if item.id == package.primary_file_id)
    primary_relative = PurePosixPath(primary_receipt.path).relative_to(prefix).as_posix()
    primary = paths[primary_relative]
    if primary.suffix.lower() != ".glb":
        raise ValueError("LOD diagnostic primary asset must be GLB")
    export = _json(paths["export_evidence.json"])
    export_source = export.get("source", {})
    expected_blend_sha256 = blend.sha256
    expected_conversion_sha256 = None
    if package.material_conversion is not None:
        conversion_relative = "metadata/material_conversion_manifest.json"
        conversion_plan_relative = "metadata/material_conversion_plan.json"
        if conversion_relative not in paths or conversion_plan_relative not in paths:
            raise ValueError("LOD export lacks selected material conversion snapshots")
        conversion = PortableMaterialConversionManifest.model_validate(
            _json(paths[conversion_relative])
        ).model_dump(mode="json")
        conversion_plan = PortableMaterialConversionPlan.model_validate(
            _json(paths[conversion_plan_relative])
        )
        if (
            conversion_plan.job_id != package.job_id
            or conversion_plan.run_id != package.run_id
            or conversion_plan.profile_id != package.profile_id
            or conversion_plan.source != plan.source
        ):
            raise ValueError("LOD export has a foreign material conversion plan")
        expected_conversion_sha256 = receipts[conversion_plan_relative].sha256
        if (
            package.material_conversion.sha256 != receipts[conversion_relative].sha256
            or package.material_conversion.path != receipts[conversion_relative].path
            or conversion.get("job_id") != package.job_id
            or conversion.get("run_id") != package.run_id
            or conversion.get("profile_id") != package.profile_id
            or conversion.get("status") != "complete"
            or conversion.get("source") != plan.source.model_dump(mode="json")
            or conversion.get("plan_artifact", {}).get("sha256") != expected_conversion_sha256
            or conversion.get("profile_artifact", {}).get("sha256") != plan.profile_artifact.sha256
            or conversion.get("optimized_blend", {}).get("sha256") != blend.sha256
            or conversion.get("optimization_plan", {}).get("sha256")
            != receipts["metadata/execution_plan.json"].sha256
        ):
            raise ValueError("LOD export has a mixed material conversion source")
        expected_blend_sha256 = conversion.get("portable_blend", {}).get("sha256")
        if not isinstance(expected_blend_sha256, str):
            raise ValueError("LOD export material conversion has no derived blend hash")
    primary_exports = [
        item
        for item in export.get("files", [])
        if isinstance(item, dict) and item.get("path") == primary_relative
    ]
    if (
        export.get("schema_version") != "0.7.0"
        or export.get("ok") is not True
        or export.get("kind") != "portable_export_evidence"
        or export.get("format") != "glb"
        or export.get("content_mode", "full_evidence") != "full_evidence"
        or export.get("primary_file") != primary_relative
        or len(primary_exports) != 1
        or primary_exports[0].get("sha256") != primary_receipt.sha256
        or primary_exports[0].get("size_bytes") != primary_receipt.byte_size
        or export_source.get("job_id") != package.job_id
        or export_source.get("plan_sha256") != receipts["metadata/execution_plan.json"].sha256
        or export_source.get("build_fingerprint") != plan.source.build_fingerprint
        or export_source.get("source_build_fingerprint") != plan.source.build_fingerprint
        or export_source.get("optimized_blend_sha256") != expected_blend_sha256
        or export_source.get("material_conversion_plan_sha256") != expected_conversion_sha256
    ):
        raise ValueError("LOD export evidence has stale or mixed source/plan/primary binding")
    members = _glb_members(primary)
    if set(members) != {(entry.target_id, entry.level) for entry in lod.entries}:
        raise ValueError("Actual GLB semantic/LOD coverage differs from its manifest")
    return (
        package,
        profile,
        plan,
        lod,
        primary,
        {
            "package_manifest_sha256": expected_sha256,
            "profile_sha256": plan.profile_artifact.sha256,
            "optimization_plan_sha256": package.optimization_plan.sha256,
            "lod_manifest_sha256": receipts["metadata/lod_manifest.json"].sha256,
            "primary_asset_sha256": primary_receipt.sha256,
        },
    )


def _camera(value: Any) -> dict[str, Any]:
    """Require finite bounded camera declarations before exact cross-level comparisons."""

    if not isinstance(value, dict) or set(value) != {"matrix_world", "type", "lens", "ortho_scale"}:
        raise ValueError("LOD mask has an unsupported camera declaration")
    matrix = value["matrix_world"]
    if not isinstance(matrix, list) or len(matrix) != 16:
        raise ValueError("LOD camera matrix must have 16 finite components")
    if any(type(number) not in {int, float} or not math.isfinite(number) for number in matrix):
        raise ValueError("LOD camera matrix must be finite")
    if value["type"] not in {"ORTHO", "PERSP"}:
        raise ValueError("LOD camera projection is unsupported")
    if any(
        type(value[key]) not in {int, float} or not math.isfinite(value[key]) or value[key] <= 0
        for key in ("lens", "ortho_scale")
    ):
        raise ValueError("LOD camera scale/lens must be positive and finite")
    if any(
        abs(matrix[12 + index] - expected) > 1e-6 for index, expected in enumerate((0, 0, 0, 1))
    ):
        raise ValueError("LOD camera transform is not affine")
    columns = [[matrix[4 * row + column] for row in range(3)] for column in range(3)]
    for left in range(3):
        for right in range(3):
            dot = sum(a * b for a, b in zip(columns[left], columns[right], strict=True))
            if abs(dot - int(left == right)) > 1e-5:
                raise ValueError("LOD camera basis is not rigid orthonormal")
    a, b, c = columns
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    if abs(determinant - 1) > 1e-5:
        raise ValueError("LOD camera basis must be right-handed")
    return value


def _mask(path: Path, expected_sha256: str) -> tuple[Image.Image, int, bool]:
    """Decode a fixed-size alpha mask with the predeclared threshold and clipping guard."""

    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("LOD mask exceeds bounded PNG input size")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("LOD mask changed while computing metrics")
    with Image.open(io.BytesIO(data)) as image:
        if image.mode != "RGBA" or image.size != (1024, 1024) or image.format != "PNG":
            raise ValueError("LOD masks must be 1024x1024 RGBA PNGs")
        mask = image.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    count = mask.histogram()[255]
    border = any(
        mask.crop(box).getbbox() is not None
        for box in (
            (0, 0, 1024, 1),
            (0, 1023, 1024, 1024),
            (0, 0, 1, 1024),
            (1023, 0, 1024, 1024),
        )
    )
    return mask, count, border


def inspect_exported_lod_quality(
    package_manifest: Path,
    *,
    package_manifest_sha256: str,
    render_root: Path | None = None,
    render_plan_sha256: str | None = None,
    render_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Recompute explicit post-export mask diagnostics without altering any source or authority."""

    package, profile, _plan, lod, primary, hashes = _package_inputs(
        package_manifest, package_manifest_sha256
    )
    result: dict[str, Any] = {
        "schema_version": "0.1.0",
        "kind": "read_only_exported_lod_quality_diagnostic",
        "job_id": package.job_id,
        "run_id": package.run_id,
        "package_id": package.package_id,
        "bindings": hashes,
        "diagnostic_status": "unverified",
        "native_quality_status": lod.quality_status,
        "native_quality_verified_by_this_check": False,
        "renderer_provenance": "declared_not_independently_attested",
        "publication_or_acceptance_authority": False,
        "comparisons": [],
        "failed_count": 0,
        "passed_count": 0,
        "unavailable_count": 0,
        "limitations": list(LIMITATIONS),
    }
    floors = {entry.level: entry.minimum_silhouette_iou for entry in profile.lod.targets}
    recorded_failures = [
        {
            "target_id": entry.target_id,
            "level": entry.level,
            "iou": entry.silhouette_iou,
            "profile_floor": floors[entry.level],
        }
        for entry in lod.entries
        if entry.level
        and entry.silhouette_iou is not None
        and entry.silhouette_iou < floors[entry.level]
    ]
    result["recorded_manifest_failures"] = recorded_failures
    supplied = (
        render_root is not None,
        render_plan_sha256 is not None,
        render_manifest_sha256 is not None,
    )
    if any(supplied) and not all(supplied):
        raise ValueError("Select render root and both exact render hashes together")
    if not profile.lod.enabled:
        if any(supplied):
            raise ValueError("Disabled optional LODs cannot consume reduced-level mask evidence")
        result["diagnostic_status"] = "not_applicable"
        result["reason"] = (
            "Optional LODs are explicitly disabled; no reduced-level score is claimed."
        )
        return result
    if not any(supplied):
        result["diagnostic_status"] = "failed" if recorded_failures else "unverified"
        result["reason"] = (
            "No explicitly selected exported LOD mask evidence; unknown is not passed."
        )
        return result
    assert render_root is not None and render_plan_sha256 and render_manifest_sha256
    plan_path = _regular_path(render_root, "plan.json")
    manifest_path = _regular_path(render_root, "render_manifest.json")
    _hash(plan_path, render_plan_sha256)
    _hash(manifest_path, render_manifest_sha256)
    render_plan, rendered = _json(plan_path), _json(manifest_path)
    required_plan = {
        "kind": "bounded_independent_exported_lod_silhouette_plan",
        "primary_asset_sha256": hashes["primary_asset_sha256"],
        "blender_version": "5.0.1",
        "engine": "BLENDER_WORKBENCH",
        "geometry_only_flat_opaque_override": True,
        "resolution": [1024, 1024],
        "render_aa": "16",
        "mask_alpha_threshold": 128,
        "minimum_reference_foreground_pixels": 1024,
        "levels": [0, *sorted(floors)],
        "profile_floors": {str(level): floor for level, floor in floors.items()},
        "views": list(VIEWS),
        "native_lod_manifest_unchanged": True,
    }
    known_plan_fields = {
        *required_plan,
        "scopes",
        "maximum_render_count",
        "canonical_camera_matrix",
        "canonical_camera_lens_mm",
        "orthographic_camera_basis",
    }
    if set(render_plan) != known_plan_fields or set(rendered) != {
        "plan_sha256",
        "records",
        "elapsed_seconds",
        "canonical_or_package_saved",
    }:
        raise ValueError("Unsupported LOD diagnostic fields or schema version")
    if (
        not isinstance(render_plan["orthographic_camera_basis"], str)
        or not render_plan["orthographic_camera_basis"]
        or not isinstance(render_plan["levels"], list)
        or any(type(level) is not int for level in render_plan["levels"])
        or type(render_plan["maximum_render_count"]) is not int
        or type(rendered["elapsed_seconds"]) not in {int, float}
        or not math.isfinite(rendered["elapsed_seconds"])
        or rendered["elapsed_seconds"] < 0
    ):
        raise ValueError("Unsupported LOD diagnostic method/coverage declaration")
    if any(render_plan.get(key) != value for key, value in required_plan.items()):
        raise ValueError(
            "LOD render plan differs from the exact export/profile or supported method"
        )
    if (
        rendered.get("plan_sha256") != render_plan_sha256
        or rendered.get("canonical_or_package_saved") is not False
    ):
        raise ValueError("LOD render manifest has foreign plan binding or claims source mutation")
    members = _glb_members(primary)
    scopes = render_plan.get("scopes")
    targets = {target for target, _ in members}
    if (
        not isinstance(scopes, list)
        or not scopes
        or len(scopes) > 65
        or any(not isinstance(scope, str) for scope in scopes)
        or len(scopes) != len(set(scopes))
        or "whole_asset" not in scopes
        or not set(scopes) <= {"whole_asset", *targets}
    ):
        raise ValueError(
            "LOD diagnostic scopes must be unique and include the whole exported asset"
        )
    levels = [0, *sorted(floors)]
    expected = {(scope, view, level) for scope in scopes for view in VIEWS for level in levels}
    if render_plan.get("maximum_render_count") != len(expected):
        raise ValueError("LOD render plan has incomplete planned coverage")
    records = rendered.get("records")
    if not isinstance(records, list) or len(records) != len(expected):
        raise ValueError("LOD render manifest has incomplete or extra coverage")
    rows: dict[tuple[str, str, int], dict[str, Any]] = {}
    used_paths: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "scope",
            "view",
            "level",
            "selected_objects",
            "camera",
            "path",
            "sha256",
        }:
            raise ValueError("LOD mask record has unsupported fields")
        if type(record["level"]) is not int:
            raise ValueError("LOD mask level must be an integer")
        key = (record["scope"], record["view"], record["level"])
        if key not in expected or key in rows:
            raise ValueError("LOD masks have duplicated or foreign scope/view/level coverage")
        selected_targets = targets if key[0] == "whole_asset" else {key[0]}
        selected = sorted(name for target in selected_targets for name in members[(target, key[2])])
        if record["selected_objects"] != selected:
            raise ValueError("LOD masks select mixed, missing, or foreign actual GLB objects")
        camera = _camera(record["camera"])
        if key[1] == "canonical":
            if camera["matrix_world"] != render_plan.get("canonical_camera_matrix") or camera[
                "lens"
            ] != render_plan.get("canonical_camera_lens_mm"):
                raise ValueError("LOD canonical camera differs from the selected render plan")
        elif camera["type"] != "ORTHO":
            raise ValueError("LOD cardinal diagnostic cameras must be orthographic")
        else:
            direction = {"front": (0, 1, 0), "right": (-1, 0, 0), "top": (0, 0, -1)}[key[1]]
            if any(
                abs(-camera["matrix_world"][4 * axis + 2] - value) > 1e-5
                for axis, value in enumerate(direction)
            ):
                raise ValueError("LOD cardinal camera does not match its named viewing direction")
        path_string = record["path"]
        if not isinstance(path_string, str) or path_string.casefold() in used_paths:
            raise ValueError("LOD masks require unique ordinary paths")
        used_paths.add(path_string.casefold())
        path = _regular_path(render_root, path_string)
        _hash(path, record["sha256"])
        rows[key] = {**record, "local_path": path}
    for scope in scopes:
        for view in VIEWS:
            reference_row = rows[(scope, view, 0)]
            reference, reference_count, reference_border = _mask(
                reference_row["local_path"], reference_row["sha256"]
            )
            for level in sorted(floors):
                row = rows[(scope, view, level)]
                if row["camera"] != reference_row["camera"]:
                    raise ValueError("LOD masks do not reuse the exact LOD0 camera")
                candidate, candidate_count, candidate_border = _mask(
                    row["local_path"], row["sha256"]
                )
                intersection = ImageChops.darker(reference, candidate).histogram()[255]
                union = ImageChops.lighter(reference, candidate).histogram()[255]
                iou = intersection / union if union else None
                reason = None
                if reference_count < 1024:
                    reason = "reference_mask_too_small_for_declared_floor_precision"
                elif reference_border or candidate_border:
                    reason = "foreground_touches_image_boundary"
                status = (
                    "unavailable"
                    if reason
                    else "passed"
                    if iou is not None and iou >= floors[level]
                    else "failed"
                )
                result["comparisons"].append(
                    {
                        "scope": scope,
                        "view": view,
                        "level": level,
                        "profile_floor": floors[level],
                        "iou": iou,
                        "status": status,
                        "unavailability_reason": reason,
                        "reference_foreground_pixels": reference_count,
                        "candidate_foreground_pixels": candidate_count,
                        "intersection_pixels": intersection,
                        "union_pixels": union,
                        "source_mask_sha256": reference_row["sha256"],
                        "candidate_mask_sha256": row["sha256"],
                    }
                )
                result[f"{status}_count"] += 1
    result["diagnostic_status"] = (
        "failed"
        if recorded_failures or result["failed_count"]
        else "unverified"
        if result["unavailable_count"]
        else "passed_for_declared_coverage"
    )
    result["coverage"] = {
        "scopes": scopes,
        "views": list(VIEWS),
        "levels": levels,
        "isolated_semantic_coverage_complete": targets <= set(scopes),
    }
    hashes.update(
        render_plan_sha256=render_plan_sha256, render_manifest_sha256=render_manifest_sha256
    )
    result["reason"] = (
        "Only supplied declared discrete-view masks were recomputed; native quality unchanged."
    )
    return result
