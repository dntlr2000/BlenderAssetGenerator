"""Stage-neutral GeometryIntent survival reports and AQ v2 integration hooks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .mesh_payload_v02 import (
    JobRelativePath,
    MeshPayloadV02StrictModel,
    Sha256,
    StableId,
    canonical_json_sha256,
)

GeometryStageV02 = Literal[
    "structural_materialization",
    "compiled_candidate",
    "promoted_canonical",
    "optimized_lod0",
    "clean_import_glb",
    "clean_import_fbx",
]
SurvivalRelationV02 = Literal[
    "materialization_to_candidate",
    "candidate_to_canonical",
    "canonical_to_optimized_lod0",
    "optimized_to_clean_import",
]


class GeometryEvidenceFingerprintV02(MeshPayloadV02StrictModel):
    """Represent one available, unavailable, or inapplicable exact evidence channel."""

    status: Literal["available", "unavailable", "not_applicable"]
    sha256: Sha256 | None
    reason: str | None

    @model_validator(mode="after")
    def validate_status(self) -> GeometryEvidenceFingerprintV02:
        """Require a hash only for available evidence and a reason otherwise."""

        if self.status == "available":
            if self.sha256 is None or self.reason is not None:
                raise ValueError("available evidence requires only sha256")
        elif self.sha256 is not None or not self.reason:
            raise ValueError("unavailable/inapplicable evidence requires only a reason")
        return self


class GeometryStageSnapshotV02(MeshPayloadV02StrictModel):
    """Capture exact structural state at one candidate, canonical, or delivery stage."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    stage: GeometryStageV02
    artifact_path: JobRelativePath
    artifact_sha256: Sha256
    source_fingerprint_sha256: Sha256
    build_fingerprint_sha256: Sha256
    semantic_id: StableId
    topology_profile: StableId
    vertex_count: int = Field(ge=0)
    face_count: int = Field(ge=0)
    loop_count: int = Field(ge=0)
    evaluated_triangle_count: int = Field(ge=0)
    topology_fingerprint: GeometryEvidenceFingerprintV02
    surface_equivalence_fingerprint: GeometryEvidenceFingerprintV02
    uv_fingerprint: GeometryEvidenceFingerprintV02
    material_slots_fingerprint: GeometryEvidenceFingerprintV02
    polygon_material_fingerprint: GeometryEvidenceFingerprintV02
    split_normal_fingerprint: GeometryEvidenceFingerprintV02
    sharp_edge_fingerprint: GeometryEvidenceFingerprintV02
    uv_seam_fingerprint: GeometryEvidenceFingerprintV02
    crease_fingerprint: GeometryEvidenceFingerprintV02
    bevel_fingerprint: GeometryEvidenceFingerprintV02
    smoothing_fingerprint: GeometryEvidenceFingerprintV02
    modifier_fingerprint: GeometryEvidenceFingerprintV02
    custom_attribute_fingerprint: GeometryEvidenceFingerprintV02

    @model_validator(mode="after")
    def validate_nonempty_mesh(self) -> GeometryStageSnapshotV02:
        """Reject an empty stage snapshot from the executable survival chain."""

        if min(self.vertex_count, self.face_count, self.loop_count) <= 0:
            raise ValueError("geometry stage snapshot requires a nonempty mesh")
        return self


class GeometrySurvivalCheckV02(MeshPayloadV02StrictModel):
    """Record one exact, equivalent, lost, unavailable, or failed comparison."""

    check_id: StableId
    status: Literal["exact", "equivalent", "known_loss", "unscorable", "failed"]
    source_sha256: Sha256 | None
    target_sha256: Sha256 | None
    message: str = Field(min_length=1)


class GeometryIntentSurvivalReportV02(MeshPayloadV02StrictModel):
    """Bind one immutable stage transition to explicit geometry-survival checks."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    report_id: StableId
    relation: SurvivalRelationV02
    source_stage: GeometryStageV02
    source_snapshot_sha256: Sha256
    target_stage: GeometryStageV02
    target_snapshot_sha256: Sha256
    package_format: Literal["GLB", "FBX"] | None
    checks: list[GeometrySurvivalCheckV02] = Field(min_length=1)
    overall_status: Literal["exact", "equivalent", "known_loss", "unscorable", "failed"]
    known_losses: list[str]
    integration_authority: Literal["aq_v2_only"] = "aq_v2_only"
    v1_path_mutated: Literal[False] = False

    @model_validator(mode="after")
    def validate_aggregate(self) -> GeometryIntentSurvivalReportV02:
        """Recompute the aggregate status and package-format constraints."""

        if self.relation == "optimized_to_clean_import":
            if self.package_format is None:
                raise ValueError("clean-import survival requires a package format")
        elif self.package_format is not None:
            raise ValueError("package_format is only valid for clean-import survival")
        expected = _aggregate_status([item.status for item in self.checks])
        if self.overall_status != expected:
            raise ValueError("overall_status does not match survival checks")
        losses = [item.message for item in self.checks if item.status == "known_loss"]
        if self.known_losses != losses:
            raise ValueError("known_losses must exactly project known-loss checks")
        return self


def _aggregate_status(
    values: list[Literal["exact", "equivalent", "known_loss", "unscorable", "failed"]],
) -> Literal["exact", "equivalent", "known_loss", "unscorable", "failed"]:
    """Return the most conservative deterministic aggregate for survival checks."""

    precedence = ("failed", "unscorable", "known_loss", "equivalent", "exact")
    return next(value for value in precedence if value in values)  # type: ignore[return-value]


def _fingerprint_check(
    check_id: str,
    source: GeometryEvidenceFingerprintV02,
    target: GeometryEvidenceFingerprintV02,
    *,
    metadata_loss_allowed: bool,
) -> GeometrySurvivalCheckV02:
    """Compare one evidence channel and preserve unavailable versus known-loss meaning."""

    if source.status != "available":
        return GeometrySurvivalCheckV02(
            check_id=check_id,
            status="unscorable",
            source_sha256=None,
            target_sha256=target.sha256,
            message=f"source {check_id} evidence is {source.status}: {source.reason}",
        )
    if target.status != "available":
        return GeometrySurvivalCheckV02(
            check_id=check_id,
            status="known_loss" if metadata_loss_allowed else "unscorable",
            source_sha256=source.sha256,
            target_sha256=None,
            message=(
                f"target format does not expose {check_id}: {target.reason}"
                if metadata_loss_allowed
                else f"target {check_id} evidence is {target.status}: {target.reason}"
            ),
        )
    status = "exact" if source.sha256 == target.sha256 else "failed"
    return GeometrySurvivalCheckV02(
        check_id=check_id,
        status=status,
        source_sha256=source.sha256,
        target_sha256=target.sha256,
        message=(
            f"{check_id} fingerprint matches"
            if status == "exact"
            else f"{check_id} fingerprint changed unexpectedly"
        ),
    )


def compare_geometry_stage_snapshots_v02(
    *,
    report_id: str,
    relation: SurvivalRelationV02,
    source: GeometryStageSnapshotV02,
    target: GeometryStageSnapshotV02,
    package_format: Literal["GLB", "FBX"] | None = None,
) -> GeometryIntentSurvivalReportV02:
    """Compare one planned AQ v2 transition without authorizing any canonical write."""

    expected_stages = {
        "materialization_to_candidate": (
            "structural_materialization",
            "compiled_candidate",
        ),
        "candidate_to_canonical": ("compiled_candidate", "promoted_canonical"),
        "canonical_to_optimized_lod0": ("promoted_canonical", "optimized_lod0"),
        "optimized_to_clean_import": (
            "optimized_lod0",
            "clean_import_glb" if package_format == "GLB" else "clean_import_fbx",
        ),
    }
    if (source.stage, target.stage) != expected_stages[relation]:
        raise ValueError("snapshot stages do not match the declared survival relation")
    checks: list[GeometrySurvivalCheckV02] = []
    for check_id, left, right in (
        ("semantic_identity", source.semantic_id, target.semantic_id),
        ("topology_profile", source.topology_profile, target.topology_profile),
    ):
        checks.append(
            GeometrySurvivalCheckV02(
                check_id=check_id,
                status="exact" if left == right else "failed",
                source_sha256=canonical_json_sha256(left),
                target_sha256=canonical_json_sha256(right),
                message=(
                    f"{check_id} matches"
                    if left == right
                    else f"{check_id} changed unexpectedly"
                ),
            )
        )

    exact_topology_required = relation in {
        "materialization_to_candidate",
        "candidate_to_canonical",
    }
    source_counts = (
        source.vertex_count,
        source.face_count,
        source.loop_count,
        source.evaluated_triangle_count,
    )
    target_counts = (
        target.vertex_count,
        target.face_count,
        target.loop_count,
        target.evaluated_triangle_count,
    )
    if exact_topology_required:
        count_status = "exact" if source_counts == target_counts else "failed"
    else:
        surfaces_match = (
            source.surface_equivalence_fingerprint.status == "available"
            and target.surface_equivalence_fingerprint.status == "available"
            and source.surface_equivalence_fingerprint.sha256
            == target.surface_equivalence_fingerprint.sha256
        )
        count_status = "exact" if source_counts == target_counts else (
            "equivalent" if surfaces_match else "failed"
        )
    checks.append(
        GeometrySurvivalCheckV02(
            check_id="mesh_counts",
            status=count_status,
            source_sha256=canonical_json_sha256(source_counts),
            target_sha256=canonical_json_sha256(target_counts),
            message=(
                "mesh counts match"
                if count_status == "exact"
                else "mesh counts changed with equivalent surface"
                if count_status == "equivalent"
                else "mesh counts changed without proven surface equivalence"
            ),
        )
    )

    is_clean_import = relation == "optimized_to_clean_import"
    common_channels = (
        ("uv_layout", source.uv_fingerprint, target.uv_fingerprint),
        (
            "material_slots",
            source.material_slots_fingerprint,
            target.material_slots_fingerprint,
        ),
        (
            "polygon_materials",
            source.polygon_material_fingerprint,
            target.polygon_material_fingerprint,
        ),
        (
            "split_normals",
            source.split_normal_fingerprint,
            target.split_normal_fingerprint,
        ),
        (
            "surface_equivalence",
            source.surface_equivalence_fingerprint,
            target.surface_equivalence_fingerprint,
        ),
    )
    for check_id, left, right in common_channels:
        checks.append(
            _fingerprint_check(
                check_id,
                left,
                right,
                metadata_loss_allowed=False,
            )
        )
    authoring_channels = (
        ("sharp_edges", source.sharp_edge_fingerprint, target.sharp_edge_fingerprint),
        ("uv_seams", source.uv_seam_fingerprint, target.uv_seam_fingerprint),
        ("creases", source.crease_fingerprint, target.crease_fingerprint),
        ("bevel", source.bevel_fingerprint, target.bevel_fingerprint),
        ("smoothing", source.smoothing_fingerprint, target.smoothing_fingerprint),
        ("modifiers", source.modifier_fingerprint, target.modifier_fingerprint),
        (
            "custom_attributes",
            source.custom_attribute_fingerprint,
            target.custom_attribute_fingerprint,
        ),
    )
    for check_id, left, right in authoring_channels:
        checks.append(
            _fingerprint_check(
                check_id,
                left,
                right,
                metadata_loss_allowed=is_clean_import,
            )
        )

    status = _aggregate_status([item.status for item in checks])
    losses = [item.message for item in checks if item.status == "known_loss"]
    return GeometryIntentSurvivalReportV02(
        report_id=report_id,
        relation=relation,
        source_stage=source.stage,
        source_snapshot_sha256=canonical_json_sha256(source),
        target_stage=target.stage,
        target_snapshot_sha256=canonical_json_sha256(target),
        package_format=package_format,
        checks=checks,
        overall_status=status,
        known_losses=losses,
    )


def validate_geometry_survival_chain_v02(
    reports: list[GeometryIntentSurvivalReportV02],
) -> Literal["exact", "equivalent", "known_loss", "unscorable", "failed"]:
    """Validate predecessor continuity and aggregate a candidate-to-delivery report chain."""

    if not reports:
        raise ValueError("geometry survival chain cannot be empty")
    for previous, current in zip(reports, reports[1:], strict=False):
        if previous.target_stage != current.source_stage:
            raise ValueError("geometry survival chain has a stage discontinuity")
        if previous.target_snapshot_sha256 != current.source_snapshot_sha256:
            raise ValueError("geometry survival chain has a snapshot hash discontinuity")
    return _aggregate_status([item.overall_status for item in reports])


def verify_geometry_stage_snapshot_artifact_v02(
    snapshot: GeometryStageSnapshotV02,
    *,
    job_root: Path,
) -> None:
    """Re-hash one contained stage artifact before using its snapshot in a report."""

    root = job_root.resolve()
    artifact = (root / Path(*snapshot.artifact_path.split("/"))).resolve()
    try:
        artifact.relative_to(root)
    except ValueError as exc:
        raise ValueError("geometry stage artifact escapes job root") from exc
    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != snapshot.artifact_sha256:
        raise ValueError("geometry stage artifact hash is stale")


def publish_geometry_survival_report_v02(
    path: Path,
    report: GeometryIntentSurvivalReportV02,
) -> str:
    """Publish one immutable report and return its exact file SHA-256 integration binding."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
    return hashlib.sha256(path.read_bytes()).hexdigest()
