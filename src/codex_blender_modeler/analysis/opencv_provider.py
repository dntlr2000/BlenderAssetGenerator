from __future__ import annotations

import math
from pathlib import Path

from .models import ImageAnalysis, LineAngleCluster


def enrich_with_line_analysis(image_path: Path, analysis: ImageAnalysis) -> ImageAnalysis:
    """Add conservative Hough-line angle clusters when the optional vision extra is installed."""

    import cv2  # type: ignore
    import numpy as np  # type: ignore

    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return analysis
    max_side = max(image.shape[:2])
    if max_side > 1024:
        scale = 1024 / max_side
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(image, 60, 160)
    minimum = max(20, round(min(image.shape[:2]) * 0.08))
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=50,
        minLineLength=minimum,
        maxLineGap=12,
    )
    if lines is None:
        return analysis

    angles: list[float] = []
    for line in lines[:400]:
        x1, y1, x2, y2 = line[0]
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
        angles.append(angle)
    if not angles:
        return analysis

    bins: dict[int, list[float]] = {}
    for angle in angles:
        bucket = int(round(angle / 10.0) * 10) % 180
        bins.setdefault(bucket, []).append(angle)
    clusters = []
    for _bucket, members in sorted(bins.items(), key=lambda item: len(item[1]), reverse=True)[:6]:
        mean = sum(members) / len(members)
        spread = math.sqrt(sum((value - mean) ** 2 for value in members) / len(members))
        clusters.append(
            LineAngleCluster(
                angle_deg=round(mean, 4),
                count=len(members),
                spread_deg=round(spread, 4),
            )
        )
    return analysis.model_copy(update={"line_angle_clusters": clusters})
