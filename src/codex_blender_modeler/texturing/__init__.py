"""Texture manifests and provider-neutral host contracts for project v0.5."""

from .manifest import (
    COLOR_CHANNELS,
    DATA_CHANNELS,
    IMAGE_CHANNELS,
    SOURCE_TYPES,
    UV_SETS,
    MaterialManifestError,
    load_material_manifest,
    load_texture_manifest,
)
from .models import TextureChannel, TextureManifest, TextureProvenance
from .procedural_provider import (
    MATERIAL_FAMILY_PRESETS,
    PROCEDURAL_PBR_CHANNELS,
    PillowProceduralTextureProvider,
    ProceduralTextureResult,
    generate_procedural_pbr,
    list_material_family_presets,
)
from .providers import TextureGenerationRequest, TextureProvider
from .service import (
    attach_texture_manifest_to_plan,
    generate_job_procedural_textures,
    get_material_family_presets,
)

__all__ = [
    "DATA_CHANNELS",
    "COLOR_CHANNELS",
    "IMAGE_CHANNELS",
    "SOURCE_TYPES",
    "UV_SETS",
    "MaterialManifestError",
    "MATERIAL_FAMILY_PRESETS",
    "PROCEDURAL_PBR_CHANNELS",
    "PillowProceduralTextureProvider",
    "ProceduralTextureResult",
    "TextureChannel",
    "TextureGenerationRequest",
    "TextureManifest",
    "TextureProvider",
    "TextureProvenance",
    "attach_texture_manifest_to_plan",
    "generate_job_procedural_textures",
    "generate_procedural_pbr",
    "get_material_family_presets",
    "list_material_family_presets",
    "load_material_manifest",
    "load_texture_manifest",
]
