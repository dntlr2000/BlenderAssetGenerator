from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ReportScope = Literal["build", "material", "qa", "export", "full"]
NonEmptyString = Annotated[str, Field(min_length=1)]
JobId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]
ReportSourcePath = Annotated[
    str,
    Field(
        min_length=1,
        json_schema_extra={
            "pattern": (
                r"^(?!/)(?!\.{1,2}(?:/|$))(?!.*\/\.{1,2}(?:\/|$))"
                r"(?!.*//)(?!.*\/$)[^:\\]+$"
            )
        },
    ),
]


class StrictModel(BaseModel):
    """Reject undeclared fields in human-report provenance contracts."""

    model_config = ConfigDict(extra="forbid")


class ReportSource(StrictModel):
    """Record one immutable source file represented in a human-readable report."""

    kind: NonEmptyString
    path: ReportSourcePath
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def validate_job_relative_path(cls, value: str) -> str:
        """Keep report-source evidence portable and inside the owning job."""

        path = PurePosixPath(value)
        if (
            "\\" in value
            or ":" in value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.as_posix() != value
        ):
            raise ValueError("report source path must be normalized and job-relative")
        return value


class HumanReportManifest(StrictModel):
    """Describe one generated PDF and the machine-readable evidence used to create it."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: JobId
    scope: ReportScope
    generated_at: datetime
    pdf_path: NonEmptyString
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    qa_run_id: NonEmptyString | None = None
    interior_qa_run_id: NonEmptyString | None = None
    assembly_sanity_run_id: NonEmptyString | None = None
    optimization_run_id: NonEmptyString | None = None
    package_id: NonEmptyString | None = None
    font: NonEmptyString
    sources: list[ReportSource]
    warnings: list[str] = Field(default_factory=list)
