"""Optional measured scalar-coverage evidence; historical UV-only proofs retain their meaning."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from PIL import Image
from pydantic import Field, StrictFloat, StrictInt, model_validator

from ..blender_artifacts import native_io_path
from ..blender_scripts.portable_authored_uv_proof import mapped_uvs
from ..blender_scripts.portable_material_conversion_runtime import resolve_atlas_tiles
from ..blender_scripts.portable_uv_scalar_bake import (
    SCALAR_CHANNELS,
    affine_layer_corners,
    coverage_pixel_box,
)
from ..optimization.io import resolve_inside
from ..workspace import sha256_file
from .authored_uv import (
    AuthoredUVInspection,
    Digest,
    Point2,
    StrictProofModel,
    canonical_hash,
    read_json,
)


class ScalarDependency(StrictProofModel):
    """Describe one allowlisted source node participating in an actual scalar evaluation."""

    node_name: str
    node_type: Literal["TEX_IMAGE", "MAPPING", "UVMAP", "VALUE", "RGB"]
    output: str
    uv_set: str | None = None
    image_name: str | None = None
    interpolation: str | None = None
    extension: str | None = None
    projection: Literal["FLAT"] | None = None

    @model_validator(mode="after")
    def validate_dependency_shape(self):
        """Require sampling metadata only for its actual UV-map or image consumer kind."""
        image_values = (self.image_name, self.interpolation, self.extension, self.projection)
        if self.node_type == "TEX_IMAGE":
            if self.uv_set is not None or any(value is None for value in image_values):
                raise ValueError("scalar image dependency requires complete flat sampling metadata")
        elif any(value is not None for value in image_values):
            raise ValueError("non-image scalar dependency cannot contain image metadata")
        if (self.node_type == "UVMAP") != (self.uv_set is not None):
            raise ValueError("scalar UV layer binding must belong exactly to a UV Map node")
        return self


class ScalarProxy(StrictProofModel):
    """Bind a disposable scalar evaluation rectangle to its exact original UV snapshot."""

    name: str
    material_id: str
    source_snapshot_sha256: Digest
    source_uv_set: str
    source_bounds: tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat]
    target_bounds: tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat]
    target_corners: Annotated[list[Point2], Field(min_length=4, max_length=4)]
    sampled_uv_layers: list[str]
    layer_corners: dict[str, Annotated[list[Point2], Field(min_length=4, max_length=4)]]
    dependencies: dict[str, list[ScalarDependency]]


class ScalarCoverageImage(StrictProofModel):
    """Bind the independent white-emission coverage mask without exposing a free path."""

    file_name: Literal["authored_uv_coverage.png"]
    sha256: Digest


class AuthoredUVScalarBakeEvidence(StrictProofModel):
    """Prove scalar-domain raster coverage while explicitly excluding normal fidelity claims."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    kind: Literal["authored_uv_scalar_bake_evidence"] = "authored_uv_scalar_bake_evidence"
    method: Literal["uv_domain_scalar_v1"] = "uv_domain_scalar_v1"
    conversion_plan_sha256: Digest
    optimized_blend_sha256: Digest
    source_snapshot_sha256: Digest
    resolution: Annotated[StrictInt, Field(ge=1, le=8192)]
    margin_px: Annotated[StrictInt, Field(ge=1, le=1024)]
    scalar_channels: list[Literal["base_color", "roughness", "metallic", "emission"]]
    scalar_outputs: dict[str, Digest]
    normal_method: Literal["unchanged_actual_mesh_tangent_bake"]
    normal_coverage_and_basis_fidelity: Literal["not_proved_by_scalar_coverage"]
    coverage: ScalarCoverageImage
    objects: Annotated[list[ScalarProxy], Field(min_length=1, max_length=256)]


def validate_scalar_evidence(evidence, source, plan, plan_sha256, directory, outputs):
    """Recompute exact proxy coordinates and every bilinear-support coverage pixel on the host."""
    if (
        evidence.conversion_plan_sha256 != plan_sha256
        or evidence.optimized_blend_sha256 != plan.optimized_blend.sha256
        or evidence.source_snapshot_sha256 != plan.authored_uv_source.sha256
        or evidence.resolution != plan.atlas_policy.resolution
        or evidence.margin_px != plan.atlas_policy.margin_px
        or tuple(evidence.scalar_channels) != SCALAR_CHANNELS
    ):
        raise ValueError("authored scalar bake input/policy binding changed")
    expected_outputs = {item.channel: item.sha256 for item in outputs if item.channel != "normal"}
    if evidence.scalar_outputs != expected_outputs:
        raise ValueError("authored scalar bake channel binding changed")
    if len(evidence.objects) != len(source.objects):
        raise ValueError("authored scalar bake object coverage changed")
    tiles = resolve_atlas_tiles(
        plan.atlas_policy.model_dump(mode="json"), len(source.objects),
        [item.model_dump(mode="json") for item in source.objects],
    )
    coverage = directory / evidence.coverage.file_name
    if sha256_file(coverage) != evidence.coverage.sha256:
        raise ValueError("authored scalar coverage mask changed")
    with Image.open(native_io_path(coverage)) as image:
        if (
            image.size != (evidence.resolution, evidence.resolution)
            or image.mode != "RGB"
            or image.format != "PNG"
        ):
            raise ValueError("authored scalar coverage image format changed")
        image.load()
        for index, (row, original) in enumerate(zip(evidence.objects, source.objects, strict=True)):
            raw = original.model_dump(mode="json")
            if (
                row.name != original.identity.name
                or row.material_id != original.identity.material_id
                or row.source_uv_set != original.source_uv_set
                or row.source_snapshot_sha256 != canonical_hash(raw)
            ):
                raise ValueError("authored scalar source snapshot identity changed")
            layout = raw["uv_layers"][row.source_uv_set]
            minimum = [min(p[a] for p in layout) for a in (0, 1)]
            maximum = [max(p[a] for p in layout) for a in (0, 1)]
            corners = [
                [minimum[0], minimum[1]],
                [maximum[0], minimum[1]],
                [maximum[0], maximum[1]],
                [minimum[0], maximum[1]],
            ]
            bounds = tiles[index]
            if row.source_bounds != tuple(minimum + maximum) or row.target_bounds != bounds:
                raise ValueError("authored scalar inverse-affine bounds changed")
            if [list(p) for p in row.target_corners] != mapped_uvs(corners, bounds):
                raise ValueError("authored scalar target rectangle changed")
            if row.sampled_uv_layers != sorted(set(row.sampled_uv_layers)):
                raise ValueError("authored scalar sampled layers are not unique and ordered")
            if set(row.dependencies) != set(SCALAR_CHANNELS):
                raise ValueError("authored scalar dependency channel coverage changed")
            used = {
                node.uv_set
                for nodes in row.dependencies.values()
                for node in nodes
                if node.node_type == "UVMAP"
            }
            if used != set(row.sampled_uv_layers) or not used.issubset(raw["uv_layers"]):
                raise ValueError("authored scalar dependency UV binding changed")
            if set(row.layer_corners) != used | {row.source_uv_set}:
                raise ValueError("authored scalar proxy source layers changed")
            for name, values in row.layer_corners.items():
                expected = affine_layer_corners(layout, raw["uv_layers"][name], corners)
                if [list(p) for p in values] != expected or not all(
                    math.isfinite(v) for p in values for v in p
                ):
                    raise ValueError("authored scalar proxy source coordinates changed")
            crop = image.crop(coverage_pixel_box(bounds, evidence.resolution))
            if crop.getextrema() != ((255, 255), (255, 255), (255, 255)):
                raise ValueError("authored scalar bake leaves unverified bilinear-support pixels")
    return evidence


def verify_saved_scalar_evidence(root, directory, plan, manifest):
    """Validate additive scalar coverage only when present; absence remains historical UV-only."""
    artifact = manifest.authored_uv_scalar_bake
    if artifact is None:
        return None
    path = resolve_inside(root, artifact.path, "authored scalar bake evidence")
    if path != directory / "authored_uv_scalar_bake.json" or sha256_file(path) != artifact.sha256:
        raise ValueError("authored scalar bake evidence path/hash changed")
    evidence = AuthoredUVScalarBakeEvidence.model_validate(read_json(path))
    source_path = resolve_inside(root, plan.authored_uv_source.path, "authored UV source")
    if sha256_file(source_path) != plan.authored_uv_source.sha256:
        raise ValueError("authored scalar source inspection hash changed")
    source = AuthoredUVInspection.model_validate(read_json(source_path))
    return validate_scalar_evidence(
        evidence, source, plan, manifest.plan_artifact.sha256, directory, manifest.outputs
    )
