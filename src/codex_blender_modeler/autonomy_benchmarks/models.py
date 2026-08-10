"""Strict machine-readable contracts for the Autonomous Quality benchmark suite."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BenchmarkCategory = Literal[
    "simple_box",
    "loft",
    "sweep",
    "boolean_panel",
    "small_assembly",
    "terrain",
    "material_graph",
    "topology_uv_failure",
]
BenchmarkOutcome = Literal["passed", "warning", "failed", "unscorable"]
BlenderStatus = Literal["not_requested", "not_applicable", "passed", "failed"]


class BenchmarkStrictModel(BaseModel):
    """Reject undeclared fixture and report fields so benchmark drift fails closed."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class BenchmarkCase(BenchmarkStrictModel):
    """Declare one deterministic host fixture and its conservative expected outcome."""

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    category: BenchmarkCategory
    expected_outcome: BenchmarkOutcome
    blender_smoke_supported: bool = False
    payload: dict[str, Any]
    claim_scope: str = Field(min_length=1, max_length=1000)


class BenchmarkManifest(BenchmarkStrictModel):
    """Collect the minimum representative Autonomous Quality benchmark categories."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    benchmark_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    project_version: Literal["0.9.0"] = "0.9.0"
    autonomy_contract_version: Literal["0.1.0"] = "0.1.0"
    cases: list[BenchmarkCase] = Field(min_length=7)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_coverage(self) -> BenchmarkManifest:
        """Require unique IDs and every minimum regression category exactly once or more."""

        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("benchmark case IDs must be unique")
        minimum = {
            "simple_box",
            "loft",
            "sweep",
            "boolean_panel",
            "small_assembly",
            "terrain",
            "topology_uv_failure",
        }
        missing = sorted(minimum - {case.category for case in self.cases})
        if missing:
            raise ValueError(f"benchmark manifest is missing required categories: {missing}")
        return self


class BenchmarkCaseResult(BenchmarkStrictModel):
    """Record one exact fixture digest, observed outcome, and optional Blender evidence."""

    case_id: str
    category: BenchmarkCategory
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_outcome: BenchmarkOutcome
    observed_outcome: BenchmarkOutcome
    expectation_matched: bool
    host_metrics: dict[str, int | float | str | bool | None]
    blender_status: BlenderStatus
    blender_artifacts: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    ok: bool

    @model_validator(mode="after")
    def validate_result(self) -> BenchmarkCaseResult:
        """Keep the case gate consistent with expectation and requested Blender evidence."""

        expected_ok = self.expectation_matched and self.blender_status != "failed"
        if self.ok != expected_ok:
            raise ValueError("benchmark case ok does not match its evidence")
        if self.blender_status == "failed" and not self.error:
            raise ValueError("failed Blender evidence requires an error summary")
        return self


class BenchmarkReport(BenchmarkStrictModel):
    """Summarize a deterministic benchmark execution without claiming visual quality gain."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    benchmark_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runner_version: Literal["0.1.0"] = "0.1.0"
    blender_requested: bool
    blender_executed_case_count: int = Field(ge=0)
    case_results: list[BenchmarkCaseResult] = Field(min_length=7)
    passed_case_count: int = Field(ge=0)
    failed_case_count: int = Field(ge=0)
    ok: bool
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_summary(self) -> BenchmarkReport:
        """Require report counters and final status to match every case result exactly."""

        passed = sum(case.ok for case in self.case_results)
        failed = len(self.case_results) - passed
        executed = sum(
            case.blender_status in {"passed", "failed"} for case in self.case_results
        )
        if (self.passed_case_count, self.failed_case_count) != (passed, failed):
            raise ValueError("benchmark report counters do not match case results")
        if self.blender_executed_case_count != executed:
            raise ValueError("benchmark Blender counter does not match case results")
        if self.ok != (failed == 0):
            raise ValueError("benchmark report ok does not match failed case count")
        return self
