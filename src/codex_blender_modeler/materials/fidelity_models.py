from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject undeclared fields in V0.5 material-fidelity evidence."""

    model_config = ConfigDict(extra="forbid")


class ImageFidelityMetrics(StrictModel):
    """Store deterministic, normalized measurements for one raster channel."""

    width: int = Field(ge=1)
    height: int = Field(ge=1)
    sampled_pixels: int = Field(ge=1)
    luminance_mean: float = Field(ge=0, le=1)
    luminance_stddev: float = Field(ge=0, le=1)
    luminance_median: float = Field(ge=0, le=1)
    relative_variation: float = Field(ge=0)
    neighbor_delta_mean: float = Field(ge=0, le=1)
    residual_noise_mean: float = Field(ge=0, le=1)
    dark_contrast_fraction: float = Field(ge=0, le=1)
    dark_band_fraction: float = Field(ge=0, le=1)
    saturated_fraction: float = Field(ge=0, le=1)
    dominant_hue_deg: float | None = Field(default=None, ge=0, lt=360)


class NormalFidelityMetrics(StrictModel):
    """Measure tangent-space normal-map deviation from a flat +Z normal."""

    mean_deviation_deg: float = Field(ge=0, le=180)
    p95_deviation_deg: float = Field(ge=0, le=180)
    inverted_fraction: float = Field(ge=0, le=1)


class EmissionFidelityMetrics(StrictModel):
    """Measure emission coverage and hue against available reference evidence."""

    active_fraction: float = Field(ge=0, le=1)
    saturated_fraction: float = Field(ge=0, le=1)
    dominant_hue_deg: float | None = Field(default=None, ge=0, lt=360)
    reference_hue_deg: float | None = Field(default=None, ge=0, lt=360)
    hue_error_deg: float | None = Field(default=None, ge=0, le=180)


class MaterialChannelEvidence(StrictModel):
    """Bind one inspected image channel to its exact file hash and measurements."""

    channel: str
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image: ImageFidelityMetrics
    normal: NormalFidelityMetrics | None = None
    emission: EmissionFidelityMetrics | None = None


class MaterialFidelityFinding(StrictModel):
    """Record one deterministic material-fidelity result without authorizing changes."""

    code: str
    severity: Literal["info", "warning", "failed"]
    message: str
    material_id: str | None = None
    channel: str | None = None
    measured: float | None = None
    threshold: float | None = None
    evidence_paths: list[str] = Field(default_factory=list)


class MaterialFidelityEvidence(StrictModel):
    """Summarize measured channels and spatial-detail leakage risk for one material."""

    material_id: str
    shader_family: str
    texture_strategy: str
    texture_manifest_path: str | None = None
    texture_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    assigned_object_ids: list[str] = Field(default_factory=list)
    declared_surface_detail_ids: list[str] = Field(default_factory=list)
    declared_detail_parent_ids: list[str] = Field(default_factory=list)
    spatial_binding_count: int = Field(default=0, ge=0)
    legacy_unbound_detail_ids: list[str] = Field(default_factory=list)
    unbound_consumer_ids: list[str] = Field(default_factory=list)
    clean_surface_expected: bool
    channels: list[MaterialChannelEvidence] = Field(default_factory=list)
    finding_codes: list[str] = Field(default_factory=list)


class MaterialFidelityThresholds(StrictModel):
    """Persist the exact deterministic thresholds used to classify image evidence."""

    dark_contrast_fraction_max: float = Field(default=0.025, ge=0, le=1)
    dark_band_fraction_max: float = Field(default=0.04, ge=0, le=1)
    relative_variation_max: float = Field(default=0.28, ge=0)
    residual_noise_mean_max: float = Field(default=0.035, ge=0, le=1)
    normal_mean_deviation_deg_max: float = Field(default=18.0, ge=0, le=180)
    normal_p95_deviation_deg_max: float = Field(default=45.0, ge=0, le=180)
    emission_active_fraction_min: float = Field(default=0.65, ge=0, le=1)
    emission_hue_error_deg_max: float = Field(default=45.0, ge=0, le=180)


class MaterialFidelityReport(StrictModel):
    """Provide authoritative V0.5 raster measurements and advisory fidelity findings."""

    schema_version: Literal["0.5.0"] = "0.5.0"
    job_id: str
    status: Literal["passed", "warning", "failed", "unscorable"]
    ok: bool
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_hashes: dict[str, str] = Field(default_factory=dict)
    reference_path: str | None = None
    reference_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reference_metrics: ImageFidelityMetrics | None = None
    thresholds: MaterialFidelityThresholds = Field(default_factory=MaterialFidelityThresholds)
    material_count: int = Field(ge=0)
    image_material_count: int = Field(ge=0)
    passed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    failed: int = Field(ge=0)
    materials: list[MaterialFidelityEvidence] = Field(default_factory=list)
    findings: list[MaterialFidelityFinding] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_summary(self) -> MaterialFidelityReport:
        """Keep report status and counters consistent with detailed findings."""

        counts = {
            severity: sum(item.severity == severity for item in self.findings)
            for severity in ("info", "warning", "failed")
        }
        if (self.passed, self.warnings, self.failed) != (
            counts["info"],
            counts["warning"],
            counts["failed"],
        ):
            raise ValueError("Material-fidelity counts do not match findings")
        if self.ok != (self.failed == 0):
            raise ValueError("Material-fidelity ok must be true exactly when failed is zero")
        expected = (
            "failed"
            if self.failed
            else "unscorable"
            if self.image_material_count == 0
            else "warning"
            if self.warnings
            else "passed"
        )
        if self.status != expected:
            raise ValueError("Material-fidelity status does not match report evidence")
        return self
