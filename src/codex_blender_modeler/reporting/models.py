from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReportScope = Literal["build", "material", "qa", "export", "full"]


class StrictModel(BaseModel):
    """Reject undeclared fields in human-report provenance contracts."""

    model_config = ConfigDict(extra="forbid")


class ReportSource(StrictModel):
    """Record one immutable source file represented in a human-readable report."""

    kind: str
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class HumanReportManifest(StrictModel):
    """Describe one generated PDF and the machine-readable evidence used to create it."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    scope: ReportScope
    generated_at: str
    pdf_path: str
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    qa_run_id: str | None = None
    optimization_run_id: str | None = None
    package_id: str | None = None
    font: str
    sources: list[ReportSource]
    warnings: list[str] = Field(default_factory=list)
