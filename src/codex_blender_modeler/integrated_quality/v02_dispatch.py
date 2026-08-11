"""Explicit version dispatch that leaves the Integrated Quality 0.1 loader unchanged."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .models import IntegratedQualityReport
from .v02_models import IntegratedQualityReportV02


def load_integrated_quality_report_versioned(
    payload: Mapping[str, Any],
) -> IntegratedQualityReport | IntegratedQualityReportV02:
    """Load exact 0.1 or 0.2 payloads without rewriting or automatically migrating them."""

    version = payload.get("schema_version")
    encoded = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))
    if version == "0.1.0":
        return IntegratedQualityReport.model_validate_json(encoded)
    if version == "0.2.0":
        return IntegratedQualityReportV02.model_validate_json(encoded)
    raise ValueError(f"unsupported integrated quality schema_version: {version!r}")


def integrated_quality_report_model_for_version(
    schema_version: str,
) -> type[IntegratedQualityReport] | type[IntegratedQualityReportV02]:
    """Resolve an explicit report model without introducing a default-version fallback."""

    if schema_version == "0.1.0":
        return IntegratedQualityReport
    if schema_version == "0.2.0":
        return IntegratedQualityReportV02
    raise ValueError(f"unsupported integrated quality schema_version: {schema_version!r}")
