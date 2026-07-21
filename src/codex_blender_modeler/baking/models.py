from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StrictModel(BaseModel):
    """Reject undeclared fields in versioned bake contracts."""

    model_config = ConfigDict(extra="forbid")


class BakeOutput(StrictModel):
    """Describe one baked PBR output and its expected color space."""

    channel: Literal[
        "base_color",
        "roughness",
        "metallic",
        "normal",
        "height",
        "occlusion",
        "opacity",
        "emission",
        "orm",
    ]
    path: str
    color_space: Literal["sRGB", "Non-Color"]
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class BakeManifest(StrictModel):
    """Record deterministic material baking inputs, outputs, and export profile."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "complete"}}},
                    "then": {
                        "required": [
                            "source_scene_spec_sha256",
                            "source_geometry_payloads_sha256",
                            "source_camera_fingerprint",
                            "source_material_plan_sha256",
                            "source_shader_recipe_sha256",
                            "source_blend_sha256",
                            "source_build_fingerprint",
                            "source_material_fingerprint",
                        ],
                        "properties": {
                            "outputs": {
                                "minItems": 1,
                                "items": {
                                    "required": ["sha256"],
                                    "properties": {
                                        "sha256": {
                                            "type": "string",
                                            "pattern": "^[0-9a-f]{64}$",
                                        }
                                    },
                                },
                            }
                        }
                    },
                }
            ]
        },
    )

    schema_version: Literal["0.5.0"] = "0.5.0"
    job_id: str
    material_id: str
    source_shader_recipe: str
    source_scene_spec_sha256: Sha256 | None = None
    source_geometry_payloads_sha256: dict[str, Sha256] = Field(default_factory=dict)
    source_camera_fingerprint: Sha256 | None = None
    source_material_plan_sha256: Sha256 | None = None
    source_shader_recipe_sha256: Sha256 | None = None
    source_texture_manifest: str | None = None
    source_texture_manifest_sha256: Sha256 | None = None
    source_texture_channels_sha256: dict[str, Sha256] = Field(default_factory=dict)
    source_blend_sha256: Sha256 | None = None
    source_build_fingerprint: Sha256 | None = None
    source_material_fingerprint: Sha256 | None = None
    profile: Literal[
        "blender_eevee", "blender_cycles", "gltf_pbr", "unity_urp_lit", "unity_hdrp_lit"
    ]
    resolution: tuple[int, int]
    uv_set: str = "UVMap"
    margin_px: int = Field(default=16, ge=0)
    outputs: list[BakeOutput]
    status: Literal["planned", "complete", "failed"] = "planned"
    blender_version: str | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outputs(self) -> BakeManifest:
        """Require unique output channels and valid bake dimensions."""

        if any(value < 1 or value > 8192 for value in self.resolution):
            raise ValueError("resolution values must be in [1, 8192]")
        channels = [item.channel for item in self.outputs]
        if len(channels) != len(set(channels)):
            raise ValueError("Bake output channels must be unique")
        if self.status == "complete" and not self.outputs:
            raise ValueError("A complete bake manifest requires outputs")
        if self.status == "complete" and any(output.sha256 is None for output in self.outputs):
            raise ValueError("Every complete bake output requires a SHA-256 digest")
        required_provenance = {
            "source_scene_spec_sha256": self.source_scene_spec_sha256,
            "source_camera_fingerprint": self.source_camera_fingerprint,
            "source_material_plan_sha256": self.source_material_plan_sha256,
            "source_shader_recipe_sha256": self.source_shader_recipe_sha256,
            "source_blend_sha256": self.source_blend_sha256,
            "source_build_fingerprint": self.source_build_fingerprint,
            "source_material_fingerprint": self.source_material_fingerprint,
        }
        if self.status == "complete":
            missing = sorted(key for key, value in required_provenance.items() if value is None)
            if missing:
                raise ValueError(f"A complete bake manifest requires provenance fields: {missing}")
        invalid_channels = sorted(
            channel
            for channel, digest in self.source_texture_channels_sha256.items()
            if not re.fullmatch(r"[0-9a-f]{64}", digest)
        )
        if invalid_channels:
            raise ValueError(
                f"Texture channel provenance requires SHA-256 digests: {invalid_channels}"
            )
        invalid_geometry = sorted(
            path
            for path, digest in self.source_geometry_payloads_sha256.items()
            if not re.fullmatch(r"[0-9a-f]{64}", digest)
        )
        if invalid_geometry:
            raise ValueError(
                f"Geometry payload provenance requires SHA-256 digests: {invalid_geometry}"
            )
        if (self.source_texture_manifest is None) != (
            self.source_texture_manifest_sha256 is None
        ):
            raise ValueError(
                "source_texture_manifest and source_texture_manifest_sha256 must appear together"
            )
        return self
