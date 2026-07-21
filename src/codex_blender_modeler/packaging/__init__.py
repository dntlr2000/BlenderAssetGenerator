"""Engine-neutral V0.7 texture-packing and portable-package contracts."""

from .material_conversion import (
    MaterialConversionSelection,
    convert_portable_materials,
    load_portable_material_conversion,
    material_conversion_directory,
)
from .models import (
    BoundsComparison,
    ExportPackageManifest,
    PackageFile,
    PackedTexture,
    RoundTripCheck,
    RoundTripValidation,
    TextureChannelMapping,
    TexturePackManifest,
)
from .service import package_asset, profile_id_to_format, validate_asset_package
from .texture_packing import (
    PORTABLE_PBR_CHANNELS,
    RAW_CHANNEL_COLOR_SPACES,
    TexturePackingError,
    TexturePackingResult,
    build_portable_texture_package,
)

__all__ = [
    "BoundsComparison",
    "ExportPackageManifest",
    "MaterialConversionSelection",
    "PackageFile",
    "PORTABLE_PBR_CHANNELS",
    "PackedTexture",
    "RAW_CHANNEL_COLOR_SPACES",
    "RoundTripCheck",
    "RoundTripValidation",
    "TextureChannelMapping",
    "TexturePackManifest",
    "TexturePackingError",
    "TexturePackingResult",
    "build_portable_texture_package",
    "convert_portable_materials",
    "load_portable_material_conversion",
    "material_conversion_directory",
    "package_asset",
    "profile_id_to_format",
    "validate_asset_package",
]
