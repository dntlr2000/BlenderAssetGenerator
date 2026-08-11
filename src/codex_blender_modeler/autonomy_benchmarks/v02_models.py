"""Strict deterministic contracts for Autonomous Quality benchmark 0.2."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.2.0"
RUNNER_VERSION = "0.2.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"

BenchmarkCategoryV02 = Literal[
    "simple_hard_surface_box",
    "curved_loft",
    "swept_handle",
    "boolean_panel",
    "ornate_multi_part_prop",
    "multi_material_prop",
    "wood_object",
    "signage_decal_object",
    "emissive_crystal_prop",
    "small_static_assembly",
]
BenchmarkStageIdV02 = Literal[
    "v09_initial",
    "aq_v1_initial",
    "aq_v2_initial",
    "aq_v2_final",
]
MetricNameV02 = Literal[
    "silhouette_iou",
    "contour_boundary_f_score",
    "contour_chamfer_norm",
    "mean_semantic_iou",
    "minimum_critical_semantic_iou",
]
MetricDirectionV02 = Literal["increase", "decrease", "nondecrease", "nonincrease", "equal"]
HumanReviewStatusV02 = Literal["not_reviewed"]
PackageStatusV02 = Literal["not_run", "planned", "passed", "failed"]
RoundtripStatusV02 = Literal["not_run", "passed", "failed"]
BlenderStatusV02 = Literal["not_requested", "not_applicable", "passed", "failed"]


def _validate_relative_path(value: str) -> str:
    """Require one normalized POSIX path that cannot escape its report root."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty POSIX relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not contain empty, current, or parent segments")
    if PurePosixPath(value).as_posix() != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
StableId = Annotated[str, Field(pattern=ID_PATTERN)]
RelativePath = Annotated[str, AfterValidator(_validate_relative_path)]


def canonical_json_bytes_v02(value: Any) -> bytes:
    """Serialize one JSON-compatible value to stable UTF-8 benchmark bytes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_json_sha256_v02(value: Any) -> str:
    """Return the canonical SHA-256 for one benchmark-compatible value."""

    return hashlib.sha256(canonical_json_bytes_v02(value)).hexdigest()


def benchmark_case_contract_sha256_v02(value: dict[str, Any]) -> str:
    """Hash one case contract while excluding its self-referential digest field."""

    payload = dict(value)
    payload.pop("contract_sha256", None)
    return canonical_json_sha256_v02(payload)


class BenchmarkV02StrictModel(BaseModel):
    """Reject undeclared fields, implicit coercions, and non-finite values."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class KnownCameraV02(BenchmarkV02StrictModel):
    """Declare one known synthetic camera shared by reference and candidates."""

    projection: Literal["orthographic", "perspective"]
    location_m: tuple[float, float, float]
    target_m: tuple[float, float, float]
    rotation_deg: tuple[float, float, float]
    focal_length_mm: float | None = Field(default=None, gt=0)
    ortho_scale_m: float | None = Field(default=None, gt=0)
    resolution_px: tuple[int, int]

    @model_validator(mode="after")
    def validate_projection(self) -> KnownCameraV02:
        """Require exactly the lens field appropriate for the selected projection."""

        width, height = self.resolution_px
        if width < 16 or height < 16 or width * height > 1_048_576:
            raise ValueError("benchmark camera resolution is outside the bounded range")
        if self.projection == "orthographic":
            if self.ortho_scale_m is None or self.focal_length_mm is not None:
                raise ValueError("orthographic cameras require only ortho_scale_m")
        elif self.focal_length_mm is None or self.ortho_scale_m is not None:
            raise ValueError("perspective cameras require only focal_length_mm")
        return self


class SyntheticPrimitiveV02(BenchmarkV02StrictModel):
    """Describe one bounded deterministic 2D primitive in the known camera view."""

    primitive_id: StableId
    semantic_id: StableId
    qa_role: Literal["primary", "supporting", "decorative", "ground_background"]
    critical: bool
    shape: Literal["rectangle", "ellipse"]
    bbox_px: tuple[int, int, int, int]
    object_id: int = Field(ge=1, le=255)
    color_rgb: tuple[int, int, int]

    @model_validator(mode="after")
    def validate_primitive(self) -> SyntheticPrimitiveV02:
        """Require a non-empty box and byte-range deterministic beauty color."""

        x0, y0, x1, y1 = self.bbox_px
        if x1 <= x0 or y1 <= y0:
            raise ValueError("synthetic primitive bbox must have positive area")
        if any(value < 0 or value > 255 for value in self.color_rgb):
            raise ValueError("synthetic primitive color components must be bytes")
        if self.qa_role == "ground_background" and self.critical:
            raise ValueError("ground/background primitives cannot be critical")
        return self


class SyntheticReferenceRecipeV02(BenchmarkV02StrictModel):
    """Bind a reference beauty, silhouette, object-ID, and semantic-mask recipe."""

    background_rgb: tuple[int, int, int]
    primitives: list[SyntheticPrimitiveV02] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_recipe(self) -> SyntheticReferenceRecipeV02:
        """Require unique primitive/object/semantic identities and valid colors."""

        if any(value < 0 or value > 255 for value in self.background_rgb):
            raise ValueError("reference background color components must be bytes")
        primitive_ids = [item.primitive_id for item in self.primitives]
        semantic_ids = [item.semantic_id for item in self.primitives]
        object_ids = [item.object_id for item in self.primitives]
        if len(primitive_ids) != len(set(primitive_ids)):
            raise ValueError("synthetic primitive IDs must be unique")
        if len(semantic_ids) != len(set(semantic_ids)):
            raise ValueError("synthetic semantic IDs must be unique")
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("synthetic object IDs must be unique")
        return self


class StageExecutionExpectationV02(BenchmarkV02StrictModel):
    """Record deterministic modeled execution counts without claiming wall-clock timing."""

    build_count: int = Field(ge=0, le=100)
    render_count: int = Field(ge=0, le=100)
    iteration_count: int = Field(ge=0, le=100)
    rollback_count: int = Field(ge=0, le=100)
    termination_reason: Literal[
        "initial_evidence_captured",
        "legacy_policy_stopped",
        "candidate_ready",
        "quality_target_reached",
        "plateau",
        "budget_exhausted",
        "host_failure",
    ]
    package_status: PackageStatusV02
    package_format: Literal["none", "glb", "fbx", "obj"]
    roundtrip_status: RoundtripStatusV02
    deterministic_duration_ms: int = Field(ge=0, le=86_400_000)

    @model_validator(mode="after")
    def validate_package_state(self) -> StageExecutionExpectationV02:
        """Prevent fixture counters from fabricating package or round-trip success."""

        if self.package_status == "not_run":
            if self.package_format != "none" or self.roundtrip_status != "not_run":
                raise ValueError("a package that was not run cannot claim output or round trip")
        elif self.package_format == "none":
            raise ValueError("a package attempt requires a declared portable format")
        if self.package_status != "passed" and self.roundtrip_status == "passed":
            raise ValueError("round-trip success requires package success")
        return self


class BenchmarkStagePlanV02(BenchmarkV02StrictModel):
    """Describe one bounded synthetic candidate perturbation and modeled execution state."""

    stage_id: BenchmarkStageIdV02
    translation_px: tuple[int, int]
    uniform_scale: float = Field(gt=0.25, le=2.0)
    omitted_semantic_ids: list[StableId] = Field(default_factory=list)
    semantic_offsets_px: dict[StableId, tuple[int, int]] = Field(default_factory=dict)
    execution: StageExecutionExpectationV02

    @model_validator(mode="after")
    def validate_unique_omissions(self) -> BenchmarkStagePlanV02:
        """Reject duplicate omissions and conflicting omit/offset instructions."""

        if len(self.omitted_semantic_ids) != len(set(self.omitted_semantic_ids)):
            raise ValueError("omitted semantic IDs must be unique")
        overlap = set(self.omitted_semantic_ids) & set(self.semantic_offsets_px)
        if overlap:
            raise ValueError(f"omitted semantics cannot also receive offsets: {sorted(overlap)}")
        return self


class MetricDirectionExpectationV02(BenchmarkV02StrictModel):
    """Declare an exact expected metric direction between two named stages."""

    metric: MetricNameV02
    from_stage: BenchmarkStageIdV02
    to_stage: BenchmarkStageIdV02
    direction: MetricDirectionV02
    minimum_absolute_delta: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_stage_pair(self) -> MetricDirectionExpectationV02:
        """Reject self-comparisons that cannot demonstrate benchmark direction."""

        if self.from_stage == self.to_stage:
            raise ValueError("metric direction stages must differ")
        return self


class BenchmarkCaseV02(BenchmarkV02StrictModel):
    """Declare one exact synthetic reference-to-asset comparison fixture."""

    case_id: StableId
    category: BenchmarkCategoryV02
    seed: int = Field(ge=0, le=2_147_483_647)
    contract_sha256: Sha256
    known_camera: KnownCameraV02
    reference_recipe: SyntheticReferenceRecipeV02
    stages: list[BenchmarkStagePlanV02]
    expected_metric_directions: list[MetricDirectionExpectationV02] = Field(min_length=1)
    blender_smoke_supported: bool = False
    claim_scope: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_case_contract(self) -> BenchmarkCaseV02:
        """Require complete stages, contained geometry, and an exact self digest."""

        width, height = self.known_camera.resolution_px
        semantic_ids = {item.semantic_id for item in self.reference_recipe.primitives}
        for primitive in self.reference_recipe.primitives:
            x0, y0, x1, y1 = primitive.bbox_px
            if x0 < 0 or y0 < 0 or x1 > width or y1 > height:
                raise ValueError("synthetic primitive bbox exceeds the known camera frame")
        stage_ids = [item.stage_id for item in self.stages]
        required_order = [
            "v09_initial",
            "aq_v1_initial",
            "aq_v2_initial",
            "aq_v2_final",
        ]
        if stage_ids != required_order:
            raise ValueError("benchmark stages must use the exact comparison order")
        for stage in self.stages:
            referenced = set(stage.omitted_semantic_ids) | set(
                stage.semantic_offsets_px
            )
            unknown = referenced - semantic_ids
            if unknown:
                raise ValueError(f"stage references unknown semantic IDs: {sorted(unknown)}")
        direction_keys = [
            (item.metric, item.from_stage, item.to_stage)
            for item in self.expected_metric_directions
        ]
        if len(direction_keys) != len(set(direction_keys)):
            raise ValueError("metric direction expectations must be unique")
        raw = self.model_dump(mode="json", exclude={"contract_sha256"})
        if benchmark_case_contract_sha256_v02(raw) != self.contract_sha256:
            raise ValueError("benchmark case contract SHA-256 does not match")
        return self


class BenchmarkManifestV02(BenchmarkV02StrictModel):
    """Collect the ten required synthetic AQ 0.2 reference-to-asset categories."""

    schema_version: Literal["0.2.0"] = SCHEMA_VERSION
    benchmark_id: StableId
    project_version: Literal["0.9.0"] = "0.9.0"
    autonomy_contract_version: Literal["0.2.0"] = "0.2.0"
    external_downloads_allowed: Literal[False] = False
    human_review_status: HumanReviewStatusV02 = "not_reviewed"
    cases: list[BenchmarkCaseV02] = Field(min_length=10, max_length=64)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_coverage(self) -> BenchmarkManifestV02:
        """Require unique case IDs and every requested synthetic category."""

        case_ids = [item.case_id for item in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("benchmark v02 case IDs must be unique")
        required = {
            "simple_hard_surface_box",
            "curved_loft",
            "swept_handle",
            "boolean_panel",
            "ornate_multi_part_prop",
            "multi_material_prop",
            "wood_object",
            "signage_decal_object",
            "emissive_crystal_prop",
            "small_static_assembly",
        }
        missing = sorted(required - {item.category for item in self.cases})
        if missing:
            raise ValueError(f"benchmark v02 manifest is missing categories: {missing}")
        return self


class BenchmarkArtifactV02(BenchmarkV02StrictModel):
    """Bind one generated reference or candidate artifact to exact bytes."""

    role: StableId
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(gt=0)
    stage_id: BenchmarkStageIdV02 | None = None
    semantic_id: StableId | None = None


class BenchmarkMetricSetV02(BenchmarkV02StrictModel):
    """Store scored comparison values without hiding missing critical semantics."""

    silhouette_iou: float = Field(ge=0, le=1)
    contour_boundary_f_score: float = Field(ge=0, le=1)
    contour_chamfer_norm: float = Field(ge=0)
    mean_semantic_iou: float = Field(ge=0, le=1)
    minimum_critical_semantic_iou: float = Field(ge=0, le=1)
    missing_semantic_ids: list[StableId]


class BenchmarkStageResultV02(BenchmarkV02StrictModel):
    """Record one stage's exact artifacts, metrics, and modeled execution outcome."""

    stage_id: BenchmarkStageIdV02
    stage_plan_sha256: Sha256
    candidate_fingerprint_sha256: Sha256
    metrics: BenchmarkMetricSetV02
    execution: StageExecutionExpectationV02
    duration_basis: Literal["deterministic_fixture_model"] = "deterministic_fixture_model"
    artifacts: list[BenchmarkArtifactV02] = Field(min_length=4)


class MetricDirectionResultV02(BenchmarkV02StrictModel):
    """Record one expected and observed deterministic metric movement."""

    metric: MetricNameV02
    from_stage: BenchmarkStageIdV02
    to_stage: BenchmarkStageIdV02
    expected_direction: MetricDirectionV02
    minimum_absolute_delta: float = Field(ge=0, le=1)
    from_value: float = Field(ge=0)
    to_value: float = Field(ge=0)
    observed_delta: float
    matched: bool


class BlenderBenchmarkReceiptV02(BenchmarkV02StrictModel):
    """Bind one opt-in fixed-script Blender smoke to its exact case and outputs."""

    schema_version: Literal["0.2.0"] = SCHEMA_VERSION
    case_id: StableId
    case_contract_path: RelativePath
    case_contract_file_sha256: Sha256
    blend_path: RelativePath
    blend_sha256: Sha256
    render_path: RelativePath
    render_sha256: Sha256
    object_count: int = Field(ge=1)
    camera_sha256: Sha256
    external_downloads_used: Literal[False] = False


class BenchmarkCaseResultV02(BenchmarkV02StrictModel):
    """Summarize one exact case while keeping human review explicitly absent."""

    case_id: StableId
    category: BenchmarkCategoryV02
    case_contract_sha256: Sha256
    known_camera_sha256: Sha256
    reference_fingerprint_sha256: Sha256
    reference_artifacts: list[BenchmarkArtifactV02] = Field(min_length=4)
    stage_results: list[BenchmarkStageResultV02]
    metric_direction_results: list[MetricDirectionResultV02] = Field(min_length=1)
    blender_status: BlenderStatusV02
    blender_receipt: BlenderBenchmarkReceiptV02 | None = None
    error: str | None = None
    human_review_status: HumanReviewStatusV02 = "not_reviewed"
    ok: bool

    @model_validator(mode="after")
    def validate_result(self) -> BenchmarkCaseResultV02:
        """Require complete stage ordering and consistent Blender/error outcome."""

        expected_order = [
            "v09_initial",
            "aq_v1_initial",
            "aq_v2_initial",
            "aq_v2_final",
        ]
        if [item.stage_id for item in self.stage_results] != expected_order:
            raise ValueError("benchmark v02 result stages must preserve comparison order")
        expected_ok = all(item.matched for item in self.metric_direction_results)
        expected_ok = expected_ok and self.blender_status != "failed" and self.error is None
        if self.ok != expected_ok:
            raise ValueError("benchmark v02 case ok does not match its evidence")
        if (self.blender_status == "passed") != (self.blender_receipt is not None):
            raise ValueError("passed Blender status must bind exactly one receipt")
        if self.blender_status == "failed" and self.error is None:
            raise ValueError("failed Blender smoke requires an error summary")
        return self


class BenchmarkReportV02(BenchmarkV02StrictModel):
    """Summarize a deterministic AQ 0.2 benchmark without claiming human quality."""

    schema_version: Literal["0.2.0"] = SCHEMA_VERSION
    benchmark_id: StableId
    manifest_path: RelativePath
    manifest_sha256: Sha256
    runner_version: Literal["0.2.0"] = RUNNER_VERSION
    external_downloads_used: Literal[False] = False
    blender_requested: bool
    blender_executed_case_count: int = Field(ge=0)
    deterministic_host_evidence: Literal[True] = True
    human_review_status: HumanReviewStatusV02 = "not_reviewed"
    case_results: list[BenchmarkCaseResultV02] = Field(min_length=10)
    passed_case_count: int = Field(ge=0)
    failed_case_count: int = Field(ge=0)
    ok: bool
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_summary(self) -> BenchmarkReportV02:
        """Require exact counters and final status to match every case result."""

        passed = sum(item.ok for item in self.case_results)
        failed = len(self.case_results) - passed
        executed = sum(
            item.blender_status in {"passed", "failed"} for item in self.case_results
        )
        if (self.passed_case_count, self.failed_case_count) != (passed, failed):
            raise ValueError("benchmark v02 report counters do not match case results")
        if self.blender_executed_case_count != executed:
            raise ValueError("benchmark v02 Blender counter does not match case results")
        if self.ok != (failed == 0):
            raise ValueError("benchmark v02 report ok does not match failed case count")
        return self
