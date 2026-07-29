from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Color4 = tuple[float, float, float, float]
ShaderFamily = Literal[
    "standard_pbr",
    "rock",
    "terrain",
    "water",
    "glass",
    "foliage",
    "lava",
    "cloud",
    "emissive",
]


class StrictModel(BaseModel):
    """Reject undeclared fields in versioned material contracts."""

    model_config = ConfigDict(extra="forbid")


class MappingSpec(StrictModel):
    """Describe deterministic material coordinates and their physical scale."""

    mode: Literal["uv", "object", "generated", "triplanar"] = "object"
    uv_set: str = "UVMap"
    real_world_scale_m: float = Field(default=1.0, gt=0)
    texel_density_px_m: float | None = Field(default=None, gt=0)


class MaterialPlanItem(StrictModel):
    """Plan one stable SceneSpec material without changing geometry."""

    material_id: str
    label: str
    shader_family: ShaderFamily = "standard_pbr"
    texture_strategy: Literal["none", "procedural", "image", "hybrid"] = "none"
    mapping: MappingSpec = Field(default_factory=MappingSpec)
    texture_manifest: str | None = None
    shader_recipe: str | None = None
    export_profiles: list[
        Literal["blender_eevee", "blender_cycles", "gltf_pbr", "unity_urp_lit", "unity_hdrp_lit"]
    ] = Field(default_factory=lambda: ["blender_eevee"])
    evidence_status: Literal["observed", "inferred"] = "observed"
    confidence: float = Field(default=0.5, ge=0, le=1)
    notes: list[str] = Field(default_factory=list)


class MaterialPlan(StrictModel):
    """Record the approved material decomposition before authoring shader files."""

    schema_version: Literal["0.5.0"] = "0.5.0"
    job_id: str
    scene_spec_path: str = "analysis/scene_spec.json"
    stage: Literal["scaffold", "authored"] = "scaffold"
    materials: list[MaterialPlanItem] = Field(default_factory=list)
    global_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_material_ids(self) -> MaterialPlan:
        """Require unique material IDs and content for an authored plan."""

        material_ids = [item.material_id for item in self.materials]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("Material plan IDs must be unique")
        if self.stage == "authored" and not self.materials:
            raise ValueError("An authored material plan must contain at least one material")
        return self


class MaterialPromotionReceipt(StrictModel):
    """Bind one workflow-owned authored candidate to its canonical promotion."""

    schema_version: Literal["0.8.0"] = "0.8.0"
    status: Literal["promoted"] = "promoted"
    ok: Literal[True] = True
    workflow_id: str
    job_id: str
    step_id: Literal["material.promote"] = "material.promote"
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_plan_path: str
    candidate_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_canonical_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    canonical_plan_path: Literal["analysis/material_plan.json"] = (
        "analysis/material_plan.json"
    )
    canonical_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    history_path: str | None = None
    scene_spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependency_sha256: dict[str, str] = Field(default_factory=dict)
    promoted_at: datetime


class SurfaceSpec(StrictModel):
    """Store portable Principled-style surface parameters by semantic name."""

    base_color: Color4 = (0.8, 0.8, 0.8, 1.0)
    metallic: float = Field(default=0.0, ge=0, le=1)
    roughness: float = Field(default=0.5, ge=0, le=1)
    ior: float = Field(default=1.45, ge=1.0, le=3.0)
    transmission_weight: float = Field(default=0.0, ge=0, le=1)
    alpha: float = Field(default=1.0, ge=0, le=1)
    emission_color: Color4 = (0.0, 0.0, 0.0, 1.0)
    emission_strength: float = Field(default=0.0, ge=0)
    coat_weight: float = Field(default=0.0, ge=0, le=1)
    subsurface_weight: float = Field(default=0.0, ge=0, le=1)
    anisotropic: float = Field(default=0.0, ge=0, le=1)


class ShaderLayer(StrictModel):
    """Describe one whitelisted material layer and its optional mask."""

    id: str
    kind: Literal["constant", "image", "noise", "gradient", "fresnel", "normal", "bump"]
    channels: list[
        Literal["base_color", "roughness", "metallic", "normal", "height", "opacity", "emission"]
    ] = Field(default_factory=list)
    blend: Literal["replace", "mix", "multiply", "add", "screen", "overlay"] = "mix"
    factor: float = Field(default=1.0, ge=0, le=1)
    mask: Literal["none", "height", "slope", "cavity", "noise", "fresnel"] = "none"
    parameters: dict[str, Any] = Field(default_factory=dict)


class ShaderRecipe(StrictModel):
    """Define a whitelisted, Blender-version-neutral shader recipe."""

    schema_version: Literal["0.5.0"] = "0.5.0"
    material_id: str
    family: ShaderFamily = "standard_pbr"
    surface: SurfaceSpec = Field(default_factory=SurfaceSpec)
    mapping: MappingSpec = Field(default_factory=MappingSpec)
    layers: list[ShaderLayer] = Field(default_factory=list)
    texture_manifest: str | None = None
    blender_master: bool = True
    bake_required: bool = False
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_layer_ids(self) -> ShaderRecipe:
        """Keep shader layer IDs stable and unique for guarded revisions."""

        layer_ids = [layer.id for layer in self.layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("Shader layer IDs must be unique")
        return self


class MaterialValidationCheck(StrictModel):
    """Report one deterministic material-contract check."""

    id: str
    status: Literal["passed", "warning", "failed"]
    message: str
    material_id: str | None = None
    path: str | None = None


class MaterialValidationReport(StrictModel):
    """Summarize host and Blender material validation outcomes."""

    schema_version: Literal["0.5.0"] = "0.5.0"
    job_id: str
    ok: bool
    passed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    failed: int = Field(ge=0)
    checks: list[MaterialValidationCheck] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> MaterialValidationReport:
        """Ensure summary counts and the success flag match individual checks."""

        counts = {
            status: sum(item.status == status for item in self.checks)
            for status in ("passed", "warning", "failed")
        }
        if (self.passed, self.warnings, self.failed) != (
            counts["passed"],
            counts["warning"],
            counts["failed"],
        ):
            raise ValueError("Material validation counts do not match checks")
        if self.ok != (self.failed == 0):
            raise ValueError("Material validation ok must be true exactly when failed is zero")
        return self
