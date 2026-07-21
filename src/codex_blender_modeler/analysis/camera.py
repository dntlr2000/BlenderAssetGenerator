from __future__ import annotations

import math
from typing import Literal

from .models import CameraSolution, ReferenceAnalysis


def _direction(azimuth_deg: float, elevation_deg: float) -> tuple[float, float, float]:
    azimuth = math.radians(azimuth_deg)
    elevation = math.radians(elevation_deg)
    x = math.cos(elevation) * math.sin(azimuth)
    y = -math.cos(elevation) * math.cos(azimuth)
    z = math.sin(elevation)
    return (round(x, 6), round(y, 6), round(z, 6))


def solve_camera(
    analysis: ReferenceAnalysis,
    *,
    projection_hint: Literal["auto", "persp", "ortho"] = "auto",
    focal_length_mm: float | None = None,
    azimuth_deg: float | None = None,
    elevation_deg: float | None = None,
) -> CameraSolution:
    locked: list[str] = []
    assumptions: list[str] = []
    if projection_hint != "auto":
        projection = "PERSP" if projection_hint == "persp" else "ORTHO"
        method = "user_hint"
        confidence = 1.0
        locked.append("projection")
    elif analysis.recommended_projection == "ORTHO":
        projection = "ORTHO"
        method = "orthographic_source"
        confidence = analysis.projection_confidence
    elif analysis.recommended_projection == "PERSP":
        projection = "PERSP"
        method = "line_heuristic" if analysis.provider == "opencv" else "default_heuristic"
        confidence = analysis.projection_confidence
    else:
        projection = "PERSP"
        method = "default_heuristic"
        confidence = 0.25
        assumptions.append(
            "Projection was under-constrained; perspective was chosen as a safe default."
        )

    focal = float(focal_length_mm or 50.0)
    azimuth = float(azimuth_deg if azimuth_deg is not None else 35.0)
    elevation = float(elevation_deg if elevation_deg is not None else 28.0)
    if focal_length_mm is not None:
        locked.append("focal_length_mm")
    if azimuth_deg is not None:
        locked.append("azimuth_deg")
    if elevation_deg is not None:
        locked.append("elevation_deg")
    underconstrained = ["absolute_camera_distance", "principal_point", "scene_scale"]
    if projection == "ORTHO":
        underconstrained.append("ortho_scale")
    else:
        underconstrained.append("depth_scale")

    return CameraSolution(
        job_id=analysis.job_id,
        projection=projection,
        method=method,
        focal_length_mm=focal,
        azimuth_deg=azimuth,
        elevation_deg=elevation,
        roll_deg=0.0,
        view_direction=_direction(azimuth, elevation),
        confidence=confidence,
        locked_fields=locked,
        underconstrained=underconstrained,
        assumptions=assumptions,
    )
