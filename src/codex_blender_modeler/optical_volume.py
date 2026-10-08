"""Blender-safe, bounded constant optical-volume intent without execution authority."""

from __future__ import annotations

import math
from typing import Any


def validate_optical_volume(value: Any) -> dict[str, Any]:
    """Validate explicit versioned homogeneous volume factors without coercion or inference."""
    fields = {"schema_version", "thickness_factor", "attenuation_distance", "attenuation_color"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Optical volume requires its exact four explicit fields")
    if value["schema_version"] != "0.1.0":
        raise ValueError("Unsupported optical volume version")

    def scalar(raw: Any, label: str, minimum: float, maximum: float) -> float:
        """Keep all optical scalars finite and bounded without accepting bool/string input."""
        if type(raw) not in (int, float):
            raise ValueError(f"Invalid optical volume {label}")
        try:
            number = float(raw)
        except OverflowError as error:
            raise ValueError(f"Invalid optical volume {label}") from error
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(f"Invalid optical volume {label}")
        return number

    thickness = scalar(value["thickness_factor"], "thickness_factor", 1e-6, 1e6)
    distance = value["attenuation_distance"]
    if distance is not None:
        distance = scalar(distance, "attenuation_distance", 1e-6, 1e6)
    color = value["attenuation_color"]
    if not isinstance(color, (list, tuple)) or len(color) != 3:
        raise ValueError("Optical volume attenuation_color requires three finite components")
    color = [scalar(component, "attenuation_color", 1e-6, 1) for component in color]
    return {
        "schema_version": "0.1.0",
        "thickness_factor": thickness,
        "attenuation_distance": distance,
        "attenuation_color": color,
    }


def validate_volume_recipe(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Require opt-in recipe0.5.1 and an alpha-one transmissive dielectric surface."""
    version = raw.get("schema_version", "0.5.0")
    if version == "0.5.0":
        if "volume" in raw:
            raise ValueError("Legacy recipe0.5.0 cannot contain an optical volume field")
        return None
    if version != "0.5.1":
        raise ValueError("Unsupported optical-volume shader recipe version")
    allowed = {
        "schema_version",
        "material_id",
        "family",
        "surface",
        "mapping",
        "layers",
        "texture_manifest",
        "blender_master",
        "bake_required",
        "assumptions",
        "volume",
    }
    if set(raw) - allowed:
        raise ValueError("Optical-volume recipe contains unknown root fields")
    if "family" not in raw or "surface" not in raw:
        raise ValueError("Optical volume requires explicit family and surface intent")
    volume = validate_optical_volume(raw.get("volume"))
    surface = raw.get("surface", {})
    if not isinstance(surface, dict):
        raise ValueError("Optical volume needs a literal surface record")
    if not {"metallic", "alpha", "ior", "transmission_weight"}.issubset(surface):
        raise ValueError("Optical volume requires explicit dielectric surface scalars")
    for field, raw_value in surface.items():
        values = raw_value if isinstance(raw_value, (list, tuple)) else [raw_value]
        for value in values:
            if type(value) not in (int, float):
                raise ValueError(f"Optical volume surface {field} must be finite literal data")
            try:
                finite = math.isfinite(float(value))
            except OverflowError as error:
                raise ValueError(f"Optical volume surface {field} overflows") from error
            if not finite:
                raise ValueError(f"Optical volume surface {field} is nonfinite")
    for color_field in ("base_color", "emission_color"):
        if color_field in surface:
            color = surface[color_field]
            if not isinstance(color, (list, tuple)) or len(color) != 4:
                raise ValueError("Optical volume colors require four numeric components")
            if any(x < 0 for x in color):
                raise ValueError("Optical volume colors must be nonnegative")
    if raw.get("layers", []):
        raise ValueError("Initial optical volume supports constant/image surfaces without layers")
    transmission = surface.get("transmission_weight", 0.0)
    if type(transmission) not in (int, float) or not 0 < transmission <= 1:
        raise ValueError("Optical volume requires positive constant transmission")
    for field, default in (("metallic", 0.0), ("alpha", 1.0), ("ior", 1.45)):
        value = surface.get(field, default)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"Optical volume requires a finite constant {field}")
    if not 1.0 <= surface.get("ior", 1.45) <= 3.0:
        raise ValueError("Optical volume IOR is outside the supported domain")
    if surface.get("metallic", 0.0) != 0.0 or surface.get("alpha", 1.0) != 1.0:
        raise ValueError("Experimental optical volume requires metallic zero and alpha one")
    if raw.get("family", "standard_pbr") not in {"glass", "standard_pbr"}:
        raise ValueError("Experimental optical volume requires a Principled glass/PBR family")
    return volume
