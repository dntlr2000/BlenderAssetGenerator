"""Strict, recomputed converted-blend proof for the optional authored UV v1 mode."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Annotated, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

from ..blender_artifacts import native_io_path
from ..blender_runner import run_blender
from ..blender_scripts.portable_authored_uv_proof import prove_authored_uv, validate_uv_layout
from ..blender_scripts.portable_material_conversion_runtime import (
    resolve_atlas_tiles,
    stable_identifier,
)
from ..optimization.io import resolve_inside
from ..workspace import sha256_file

MODE = "validated_authored_uv_v1"
ATLAS = "CBMPortableAtlas"
MAX_BYTES = 128 * 1024 * 1024
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[StrictInt, Field(ge=0)]
Point2 = tuple[StrictFloat, StrictFloat]
Point3 = tuple[StrictFloat, StrictFloat, StrictFloat]


class StrictProofModel(BaseModel):
    """Reject extra fields, coercive counts, and nonfinite proof numbers."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def strict_literal_types(cls, value):
        """Prevent JSON booleans/counts from masquerading as each other's exact literals."""
        if isinstance(value, dict):
            for name, field in cls.model_fields.items():
                choices = (
                    get_args(field.annotation) if get_origin(field.annotation) is Literal else ()
                )
                if (
                    name in value
                    and choices
                    and not any(
                        type(value[name]) is type(choice) and value[name] == choice
                        for choice in choices
                    )
                ):
                    raise ValueError(f"{name} requires its exact literal JSON type")
        return value


class UVIdentity(StrictProofModel):
    """Bind ordered geometry to its exact derived object and source material."""

    name: str
    semantic_id: str
    source_object: str
    asset_role: Literal["render", "lod"]
    lod_level: Annotated[StrictInt, Field(ge=0, le=8)]
    material_id: str
    source_material_fingerprint: Digest


class UVSampling(StrictProofModel):
    """Record the measured named layer used by every supported UV consumer."""

    node_name: str
    node_type: Literal["UVMAP", "NORMAL_MAP", "TEX_IMAGE", "TEX_COORD"]
    selection: Literal["uv_map", "normal_map", "image_vector", "texture_coordinate_uv"]
    uv_set: str


class UVSnapshot(StrictProofModel):
    """Retain full ordered native corner storage and topology without rounding."""

    identity: UVIdentity
    vertices: Annotated[list[Point3], Field(min_length=1, max_length=500000)]
    matrix_world: tuple[tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat], ...]
    polygons: Annotated[list[list[Count]], Field(min_length=1, max_length=250000)]
    polygon_materials: list[Count]
    loops: Annotated[list[Count], Field(min_length=3, max_length=500000)]
    polygon_loops: list[list[Count]]
    triangles: Annotated[list[tuple[Count, Count, Count]], Field(min_length=1, max_length=250000)]
    uv_layers: dict[str, list[Point2]]
    source_uv_set: str
    sampling: list[UVSampling]
    active_uv_set: str
    render_uv_set: str


class AuthoredUVInspection(StrictProofModel):
    """Bind a fixed Blender 5.0.1 read-only inspection to exact blend bytes."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    kind: Literal["authored_uv_inspection"] = "authored_uv_inspection"
    uv_method: Literal["validated_authored_uv_v1"] = MODE
    blender_version: Literal["5.0.1"]
    blend_sha256: Digest
    stage: Literal["source", "target"]
    objects: Annotated[list[UVSnapshot], Field(min_length=1, max_length=256)]


class UVMeasurement(StrictProofModel):
    """Describe an exhaustive exact triangle-interior scan, never a skipped scan."""

    loop_count: Count
    triangle_count: Count
    uv_minimum: Point2
    uv_maximum: Point2
    uv_fingerprint_sha256: Digest
    topology_fingerprint_sha256: Digest
    layout_fingerprint_sha256: Digest
    degenerate_triangle_count: Literal[0]
    overlap_pair_count: Literal[0]
    candidate_pair_count: Count
    broadphase_pair_count: Count
    sweep_axis: Literal[0, 1]
    complete: Literal[True]


class UVObjectProof(StrictProofModel):
    """Bind one object's source and stored affine target with complete measured scans."""

    schema_version: Literal["0.1.0"]
    method: Literal["validated_authored_uv_v1"]
    source: UVMeasurement
    target: UVMeasurement
    target_bounds: tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat]
    mapping_target_bounds: tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat]
    orientation_preserved: Literal[True]
    actual_target_matches_reconstruction: Literal[True]
    source_snapshot_sha256: Digest
    target_snapshot_sha256: Digest


class AuthoredUVProof(StrictProofModel):
    """Bind recomputable snapshots to one conversion; this is not render attestation."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    kind: Literal["authored_uv_proof"] = "authored_uv_proof"
    uv_method: Literal["validated_authored_uv_v1"] = MODE
    conversion_plan_sha256: Digest
    source_snapshot_sha256: Digest
    optimized_blend_sha256: Digest
    portable_blend_sha256: Digest
    source: AuthoredUVInspection
    target: AuthoredUVInspection
    objects: Annotated[list[UVObjectProof], Field(min_length=1, max_length=256)]
    attestation: Literal["host_recomputed_and_blender_reopened_not_cryptographic_attestation"] = (
        "host_recomputed_and_blender_reopened_not_cryptographic_attestation"
    )


def canonical_hash(payload):
    """Hash exact ordered finite JSON values with version-fixed canonical encoding."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def read_json(path):
    """Load bounded JSON while rejecting duplicate keys and nonfinite literals."""

    def unique(pairs):
        """Reject duplicate fields before normalization can erase them."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate authored UV proof JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        """Reject nonstandard JSON numeric literals."""
        raise ValueError(f"nonfinite authored UV JSON value: {value}")

    with open(native_io_path(path), "rb") as stream:
        payload = stream.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("authored UV evidence resource limit exceeded")
    return json.loads(payload, object_pairs_hook=unique, parse_constant=nonfinite)


def write_proof_model(path, model):
    """Atomically write bounded compact new proof bytes without replacing existing evidence."""
    if os.path.lexists(native_io_path(path)):
        raise FileExistsError(path)
    payload = (model.model_dump_json() + "\n").encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ValueError("authored UV evidence resource limit exceeded")
    temporary = path.with_name(path.name + ".partial")
    with open(native_io_path(temporary), "xb") as stream:
        stream.write(payload)
    os.replace(native_io_path(temporary), native_io_path(path))


def inspect_blend(blend, digest, *, source_path=None, runner=None):
    """Reopen exact blend bytes through a fixed inspector, writing only temporary evidence."""
    with tempfile.TemporaryDirectory(prefix="cbm-authored-uv-") as directory:
        output = Path(directory) / "inspection.json"
        args = ["--output", str(output), "--expected-blend-sha256", digest]
        if source_path is not None:
            args.extend(["--source-snapshot", str(source_path)])
        (runner or run_blender)(
            "inspect_authored_uv.py",
            args,
            blend_file=blend,
            factory_startup=True,
            disable_autoexec=True,
        )
        result = AuthoredUVInspection.model_validate(read_json(output))
    if result.blend_sha256 != digest or sha256_file(blend) != digest:
        raise ValueError("authored UV inspector hash binding changed")
    return result


def validate_inspection(inspection, plan, *, stage):
    """Verify exact identity coverage, complete corner topology and bounded raw source layout."""
    raw = inspection.model_dump(mode="json")
    if raw["stage"] != stage:
        raise ValueError("authored UV inspection stage mismatch")
    objects = raw["objects"]
    keys = [
        (
            item["identity"]["semantic_id"],
            item["identity"]["source_object"],
            item["identity"]["lod_level"],
            item["identity"]["name"],
        )
        for item in objects
    ]
    if keys != sorted(set(keys)) or len({item["identity"]["name"] for item in objects}) != len(
        keys
    ):
        raise ValueError("authored UV object bindings must be ordered and unique")
    materials = {item.material_id: item for item in plan.materials}
    if {item["identity"]["material_id"] for item in objects} != set(materials):
        raise ValueError("authored UV material coverage mismatch")
    for material_id, binding in materials.items():
        actual_targets = {
            item["identity"]["semantic_id"]
            for item in objects
            if item["identity"]["material_id"] == material_id
        }
        if actual_targets != set(binding.target_ids):
            raise ValueError("authored UV exact material target coverage mismatch")
    for item in objects:
        identity = item["identity"]
        material = materials[identity["material_id"]]
        if (
            identity["semantic_id"] not in material.target_ids
            or identity["source_material_fingerprint"] != material.source_material_fingerprint
        ):
            raise ValueError("authored UV source identity/fingerprint mismatch")
        loops = item["loops"]
        polygons = item["polygons"]
        polygon_loops = item["polygon_loops"]
        if (
            len(polygons) != len(polygon_loops)
            or len(polygons) != len(item["polygon_materials"])
            or any(item["polygon_materials"])
            or len(item["matrix_world"]) != 4
            or [value for row in polygon_loops for value in row] != list(range(len(loops)))
        ):
            raise ValueError("authored UV incomplete ordered polygon/loop topology")
        owners = {}
        for index, (vertices, corners) in enumerate(zip(polygons, polygon_loops, strict=True)):
            if len(corners) < 3 or len(vertices) != len(corners):
                raise ValueError("authored UV polygon corner coverage mismatch")
            for vertex, corner in zip(vertices, corners, strict=True):
                if vertex >= len(item["vertices"]) or loops[corner] != vertex:
                    raise ValueError("authored UV ordered vertex/corner mismatch")
                owners[corner] = index
        counts = [0] * len(polygons)
        for triangle in item["triangles"]:
            if any(corner >= len(loops) for corner in triangle):
                raise ValueError("authored UV triangle corner out of range")
            owner = owners[triangle[0]]
            if any(owners[corner] != owner for corner in triangle):
                raise ValueError("authored UV triangle crosses polygon boundary")
            counts[owner] += 1
        if counts != [len(poly) - 2 for poly in polygons]:
            raise ValueError("authored UV triangle enumeration is incomplete")
        if not 1 <= len(item["uv_layers"]) <= 8:
            raise ValueError("authored UV layer count resource limit")
        if any(len(values) != len(loops) for values in item["uv_layers"].values()):
            raise ValueError("authored UV layer loop coverage mismatch")
        if (
            item["active_uv_set"] not in item["uv_layers"]
            or item["render_uv_set"] not in item["uv_layers"]
        ):
            raise ValueError("authored UV active/render selection is missing")
        sampling = item["sampling"]
        if len({binding["node_name"] for binding in sampling}) != len(sampling):
            raise ValueError("authored UV source sampling node bindings are duplicated")
        selection_types = {
            "uv_map": "UVMAP",
            "normal_map": "NORMAL_MAP",
            "image_vector": "TEX_IMAGE",
            "texture_coordinate_uv": "TEX_COORD",
        }
        if any(
            binding["uv_set"] not in item["uv_layers"]
            or selection_types[binding["selection"]] != binding["node_type"]
            for binding in sampling
        ):
            raise ValueError("authored UV sampled layer or consumer binding is invalid")
        selected = item["source_uv_set"]
        if selected not in item["uv_layers"] or selected == ATLAS:
            raise ValueError("authored UV selected source layer missing or collides")
        if stage == "source":
            if ATLAS in item["uv_layers"]:
                raise ValueError("authored UV source-target layer collision")
            validate_uv_layout(item["uv_layers"][selected], item["triangles"])
    return raw


def build_proof(source, target, plan, plan_sha256, source_sha256):
    """Independently reconstruct every stored affine target and scan all triangle interiors."""
    left = validate_inspection(source, plan, stage="source")
    right = validate_inspection(target, plan, stage="target")
    if source.blend_sha256 != plan.optimized_blend.sha256:
        raise ValueError("authored UV source blend binding mismatch")
    if len(left["objects"]) != len(right["objects"]):
        raise ValueError("authored UV source/target object coverage mismatch")
    proofs = []
    tiles = resolve_atlas_tiles(
        plan.atlas_policy.model_dump(mode="json"), len(left["objects"]), left["objects"]
    )
    fields = (
        "identity",
        "vertices",
        "matrix_world",
        "polygons",
        "polygon_materials",
        "loops",
        "polygon_loops",
        "triangles",
        "source_uv_set",
    )
    for index, (before, after) in enumerate(zip(left["objects"], right["objects"], strict=True)):
        if any(before[key] != after[key] for key in fields):
            raise ValueError("authored UV geometry/topology/ordered identity changed")
        if set(after["uv_layers"]) != set(before["uv_layers"]) | {ATLAS}:
            raise ValueError("authored UV original layer coverage changed")
        if any(after["uv_layers"][key] != value for key, value in before["uv_layers"].items()):
            raise ValueError("authored UV original source layer changed")
        if after["active_uv_set"] != ATLAS or after["render_uv_set"] != ATLAS:
            raise ValueError("authored UV target atlas activation mismatch")
        if not any(
            item["node_type"] == "UVMAP" and item["node_name"] == "CBM_PortableAtlasUV"
            for item in after["sampling"]
        ):
            raise ValueError("authored UV portable atlas sampling consumer is missing")
        if any(item["uv_set"] != ATLAS for item in after["sampling"]):
            raise ValueError("authored UV portable material samples the wrong layer")
        bounds = tiles[index]
        proof = prove_authored_uv(
            before["uv_layers"][before["source_uv_set"]],
            before["triangles"],
            bounds,
            actual_target_uvs=after["uv_layers"][ATLAS],
        )
        proof.pop("target_uvs")
        proofs.append(
            UVObjectProof(
                **proof,
                source_snapshot_sha256=canonical_hash(before),
                target_snapshot_sha256=canonical_hash(after),
            )
        )
    return AuthoredUVProof(
        conversion_plan_sha256=plan_sha256,
        source_snapshot_sha256=source_sha256,
        optimized_blend_sha256=source.blend_sha256,
        portable_blend_sha256=target.blend_sha256,
        source=source,
        target=target,
        objects=proofs,
    )


def verify_saved_proof(root, directory, plan, manifest, *, reinspect=True):
    """Reject missing/stale/tampered proof and independently reopen both exact blend files."""
    source_ref = plan.authored_uv_source
    proof_ref = manifest.authored_uv_proof
    if source_ref is None or proof_ref is None or manifest.portable_blend is None:
        raise ValueError("authored UV complete conversion requires source and proof artifacts")
    source_path = resolve_inside(root, source_ref.path, "authored UV source")
    proof_path = resolve_inside(root, proof_ref.path, "authored UV proof")
    if (
        source_path != directory / "authored_uv_source.json"
        or proof_path != directory / "authored_uv_proof.json"
    ):
        raise ValueError("authored UV proof artifact path mismatch")
    if sha256_file(source_path) != source_ref.sha256 or sha256_file(proof_path) != proof_ref.sha256:
        raise ValueError("authored UV proof artifact hash changed")
    source = AuthoredUVInspection.model_validate(read_json(source_path))
    saved = AuthoredUVProof.model_validate(read_json(proof_path))
    rebuilt = build_proof(
        source, saved.target, plan, manifest.plan_artifact.sha256, source_ref.sha256
    )
    if rebuilt != saved or saved.portable_blend_sha256 != manifest.portable_blend.sha256:
        raise ValueError("authored UV proof differs from independently recomputed evidence")
    validate_manifest_proof(plan, manifest, saved)
    if reinspect:
        actual_source = inspect_blend(
            resolve_inside(root, plan.optimized_blend.path, "source"), plan.optimized_blend.sha256
        )
        actual_target = inspect_blend(
            resolve_inside(root, manifest.portable_blend.path, "target"),
            manifest.portable_blend.sha256,
            source_path=source_path,
        )
        if actual_source != source or actual_target != saved.target:
            raise ValueError("authored UV snapshots do not describe the actual saved blends")
    return saved


def validate_manifest_proof(plan, manifest, proof):
    """Bind normalized public tiles and material identities back to the recomputed raw proof."""
    for field in (
        "atlas_policy",
        "optimized_blend",
        "profile_artifact",
        "optimization_plan",
        "uv_manifest",
        "required_material_ids",
    ):
        if getattr(plan, field) != getattr(manifest, field):
            raise ValueError("authored UV manifest plan binding changed")
    if len(manifest.tiles) != len(proof.objects):
        raise ValueError("authored UV manifest tile coverage mismatch")
    for index, (snapshot, measured, tile) in enumerate(
        zip(proof.source.objects, proof.objects, manifest.tiles, strict=True)
    ):
        identity = snapshot.identity
        expected = {
            "binding_id": stable_identifier(f"{index:06d}.{identity.name}", "binding"),
            "derived_object_id": stable_identifier(identity.name, "derived"),
            "target_id": identity.semantic_id,
            "material_id": identity.material_id,
            "lod_level": identity.lod_level,
            "unwrap_method": MODE,
            "quality_status": "verified",
            "overlap_fraction": 0.0,
        }
        if any(getattr(tile, key) != value for key, value in expected.items()):
            raise ValueError("authored UV manifest tile identity/measurement changed")
        if (*tile.uv_minimum, *tile.uv_maximum) != measured.target_bounds:
            raise ValueError("authored UV manifest tile bounds changed")
    for binding, entry in zip(plan.materials, manifest.entries, strict=True):
        if any(
            getattr(binding, key) != getattr(entry, key)
            for key in (
                "material_id",
                "source_shader_recipe",
                "source_material_fingerprint",
                "mapping_mode",
            )
        ):
            raise ValueError("authored UV manifest material binding changed")
