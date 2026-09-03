"""Exact-bound GLB numerical proofs preserve legacy failures and reject real changes."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from codex_blender_modeler.autonomy_v2.delivery_service import _validate_numerical_package_survival
from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.structural_geometry.geometry_delivery_equivalence import (
    DeliveryCornerV02,
    DeliveryTriangleV02,
    GeometryDeliveryCornerEvidenceV02,
    GeometryNumericalSurvivalReportV02,
    bind_corner_evidence,
    build_numerical_survival_report,
    compare_corner_evidence,
    corner_fingerprints,
    load_corner_evidence,
    load_delivery_survival_report,
    needs_numerical_comparison,
    validate_numerical_survival_report,
)
from codex_blender_modeler.structural_geometry.geometry_survival_v02 import (
    GeometryEvidenceFingerprintV02,
    GeometryIntentSurvivalReportV02,
    GeometryStageSnapshotV02,
    compare_geometry_stage_snapshots_v02,
    publish_geometry_survival_report_v02,
)


def _triangle(
    *,
    v: float = 0.35130998492240906,
    nx: float = 0.10504073649644852,
    semantic_id: str = "body#0",
) -> DeliveryTriangleV02:
    """Create one unit-normal face with UV/normal values near legacy cell boundaries."""

    return DeliveryTriangleV02(
        semantic_id=semantic_id,
        corners=tuple(
            DeliveryCornerV02(
                position=position,
                uv=(0.4 * index, v),
                normal=(nx, 0.0, math.sqrt(1.0 - nx * nx)),
            )
            for index, position in enumerate(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
        ),
    )


def _evidence(
    root: Path,
    stage: str,
    triangles: list[DeliveryTriangleV02],
) -> GeometryDeliveryCornerEvidenceV02:
    """Bind complete synthetic records to immutable fixture artifacts and legacy hashes."""

    artifact = root / ("source.blend" if stage == "optimized_lod0" else "target.glb")
    if not artifact.exists():
        artifact.write_bytes(stage.encode("ascii"))
    hashes = corner_fingerprints(triangles)
    available = GeometryEvidenceFingerprintV02(status="available", sha256="a" * 64, reason=None)
    fingerprints = dict.fromkeys(
        (
            "topology_fingerprint",
            "material_slots_fingerprint",
            "polygon_material_fingerprint",
            "sharp_edge_fingerprint",
            "uv_seam_fingerprint",
            "crease_fingerprint",
            "bevel_fingerprint",
            "smoothing_fingerprint",
            "modifier_fingerprint",
            "custom_attribute_fingerprint",
        ),
        available,
    )
    for field, channel in (
        ("surface_equivalence_fingerprint", "surface"),
        ("uv_fingerprint", "uv"),
        ("split_normal_fingerprint", "normals"),
    ):
        fingerprints[field] = GeometryEvidenceFingerprintV02(
            status="available",
            sha256=hashes[channel],
            reason=None,
        )
    snapshot = GeometryStageSnapshotV02(
        stage=stage,
        artifact_path=artifact.name,
        artifact_sha256=sha256_file(artifact),
        source_fingerprint_sha256="b" * 64,
        build_fingerprint_sha256="c" * 64,
        semantic_id="delivery.lod0",
        topology_profile="static_prop_closed",
        vertex_count=3 * len(triangles),
        face_count=len(triangles),
        loop_count=3 * len(triangles),
        evaluated_triangle_count=len(triangles),
        **fingerprints,
    )
    return GeometryDeliveryCornerEvidenceV02(
        schema_version="0.1.0",
        blender_version="5.0.1",
        snapshot=snapshot,
        triangles=triangles,
    )


def _pair(
    root: Path,
) -> tuple[GeometryDeliveryCornerEvidenceV02, GeometryDeliveryCornerEvidenceV02]:
    """Return a boundary-crossing pair differing only by very small UV/normal values."""

    return (
        _evidence(root, "optimized_lod0", [_triangle()]),
        _evidence(
            root,
            "clean_import_glb",
            [
                _triangle(v=0.35131001472473145, nx=0.10499873757362366),
            ],
        ),
    )


def _exact(
    source: GeometryDeliveryCornerEvidenceV02,
    target: GeometryDeliveryCornerEvidenceV02,
) -> GeometryIntentSurvivalReportV02:
    """Run the unchanged legacy comparison for the same complete snapshots."""

    return compare_geometry_stage_snapshots_v02(
        report_id="survival-glb-optimized-clean-import",
        relation="optimized_to_clean_import",
        source=source.snapshot,
        target=target.snapshot,
        package_format="GLB",
    )


def _proof(
    root: Path,
    source: GeometryDeliveryCornerEvidenceV02,
    target: GeometryDeliveryCornerEvidenceV02,
    *,
    evidence_prefix: str = "",
) -> GeometryNumericalSurvivalReportV02:
    """Publish two independent raw records and build their exact-bound numerical proof."""

    artifacts = []
    for name, evidence in (
        ("optimized_lod0_corners.json", source),
        ("clean_import_glb_corners.json", target),
    ):
        path = root / evidence_prefix / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(evidence.model_dump_json(indent=2) + "\n")
        artifacts.append(bind_corner_evidence(root, path))
    return build_numerical_survival_report(
        report_id="survival-glb-optimized-clean-import",
        source=source,
        target=target,
        source_artifact=artifacts[0],
        target_artifact=artifacts[1],
    )


def test_boundary_noise_adds_proof_without_rewriting_legacy_evidence(tmp_path: Path) -> None:
    """Keep old failed hashes unchanged while measuring all uniquely paired corners."""

    source, target = _pair(tmp_path)
    old = _exact(source, target)
    old_bytes = old.model_dump_json()
    assert old.overall_status == "failed"
    assert needs_numerical_comparison(old)
    report = _proof(tmp_path, source, target)
    assert report.schema_version == "0.2.0"
    assert report.overall_status == "equivalent"
    assert report.exact_snapshot_comparison.model_dump_json() == old_bytes
    assert old.model_dump_json() == old_bytes
    comparison = report.numerical_comparison
    assert comparison.corner_count == 3
    assert comparison.maximum_position_component_error_m == 0.0
    assert comparison.maximum_uv_component_error == pytest.approx(2.9802322387695312e-8)
    assert 0.0 < comparison.maximum_normal_angle_degrees < 0.01
    assert validate_numerical_survival_report(tmp_path, report) == (
        source.snapshot,
        target.snapshot,
    )
    path = tmp_path / "survival.json"
    digest = publish_geometry_survival_report_v02(path, report)
    assert digest == sha256_file(path)
    assert load_delivery_survival_report(path) == report
    with pytest.raises(ValidationError):
        GeometryIntentSurvivalReportV02.model_validate_json(path.read_bytes())


@pytest.mark.parametrize("version", [None, "0.3.0", "0.0.0", 0.2])
def test_report_loader_rejects_unknown_or_missing_version(tmp_path: Path, version: object) -> None:
    """Require explicit dispatch instead of inventing a migration from malformed JSON."""

    payload = _exact(*_pair(tmp_path)).model_dump(mode="json")
    if version is None:
        del payload["schema_version"]
    else:
        payload["schema_version"] = version
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown geometry delivery"):
        load_delivery_survival_report(path)


def test_legacy_report_loader_keeps_original_version_and_failure(tmp_path: Path) -> None:
    """Do not retrofit numerical evidence into a previously published 0.1 report."""

    report = _exact(*_pair(tmp_path))
    path = tmp_path / "legacy.json"
    digest = publish_geometry_survival_report_v02(path, report)
    assert type(load_delivery_survival_report(path)) is GeometryIntentSurvivalReportV02
    assert load_delivery_survival_report(path).overall_status == "failed"
    assert sha256_file(path) == digest


@pytest.mark.parametrize("corruption", ["uv", "normal", "flip", "position"])
def test_actual_channel_changes_fail_fixed_numerical_bounds(
    tmp_path: Path, corruption: str
) -> None:
    """Reject real UV movement, normal change, inverted shading and sub-cell displacement."""

    first = _triangle()
    second = _triangle(v=0.35131001472473145, nx=0.10499873757362366)
    if corruption == "uv":
        second = _triangle(v=0.3513102, nx=0.10499873757362366)
    elif corruption == "normal":
        second = _triangle(v=0.35131001472473145, nx=0.112)
    elif corruption == "flip":
        second = second.model_copy(
            update={
                "corners": tuple(
                    corner.model_copy(
                        update={
                            "normal": tuple(-value for value in corner.normal),
                        }
                    )
                    for corner in second.corners
                ),
            }
        )
    else:
        first = first.model_copy(
            update={
                "corners": (
                    first.corners[0].model_copy(update={"position": (-0.0000009, 0.0, 0.0)}),
                    *first.corners[1:],
                )
            }
        )
        second = second.model_copy(
            update={
                "corners": (
                    second.corners[0].model_copy(update={"position": (0.0000009, 0.0, 0.0)}),
                    *second.corners[1:],
                )
            }
        )
    source = _evidence(tmp_path, "optimized_lod0", [first])
    target = _evidence(tmp_path, "clean_import_glb", [second])
    report = _proof(tmp_path, source, target)
    assert report.overall_status == "failed"
    assert any(check.status == "failed" for check in report.checks)
    validate_numerical_survival_report(tmp_path, report)


@pytest.mark.parametrize(
    "invalid_field", ["material_slots_fingerprint", "polygon_material_fingerprint"]
)
def test_material_changes_cannot_use_numerical_refinement(
    tmp_path: Path, invalid_field: str
) -> None:
    """Limit the companion to UV/normal cells, without weakening material or other gates."""

    source, target = _pair(tmp_path)
    snapshot = target.snapshot.model_copy(
        update={
            invalid_field: GeometryEvidenceFingerprintV02(
                status="available", sha256="f" * 64, reason=None
            ),
        }
    )
    target = target.model_copy(update={"snapshot": snapshot})
    assert not needs_numerical_comparison(_exact(source, target))
    with pytest.raises(ValueError, match="not eligible"):
        _proof(tmp_path, source, target)


def test_ambiguous_duplicate_faces_fail_closed(tmp_path: Path) -> None:
    """Do not average coincident faces or invent a triangle pairing."""

    source = _evidence(tmp_path, "optimized_lod0", [_triangle(), _triangle()])
    target_triangle = _triangle(v=0.35131001472473145, nx=0.10499873757362366)
    target = _evidence(tmp_path, "clean_import_glb", [target_triangle, target_triangle])
    with pytest.raises(ValueError, match="ambiguous"):
        compare_corner_evidence(source, target)


def test_reordered_corners_and_optional_instance_ids_keep_correspondence(tmp_path: Path) -> None:
    """Accept deterministic interchange ordering without requiring a synthetic instance ID."""

    first = _triangle(semantic_id="body")
    second = _triangle(semantic_id="body", v=0.35131001472473145, nx=0.10499873757362366)
    second = second.model_copy(update={"corners": (*second.corners[1:], second.corners[0])})
    source = _evidence(tmp_path, "optimized_lod0", [first])
    target = _evidence(tmp_path, "clean_import_glb", [second])
    assert _proof(tmp_path, source, target).overall_status == "equivalent"


def test_reversed_triangle_winding_is_not_an_ordering_difference(tmp_path: Path) -> None:
    """Reject flipped face winding even if unordered surface/UV/normal hashes still match."""

    source, target = _pair(tmp_path)
    triangle = target.triangles[0]
    reversed_triangle = triangle.model_copy(update={"corners": tuple(reversed(triangle.corners))})
    target = _evidence(tmp_path, "clean_import_glb", [reversed_triangle])
    with pytest.raises(ValueError, match="winding reversed"):
        _proof(tmp_path, source, target)


def test_swapped_seam_uvs_are_not_hidden_by_global_hashes(tmp_path: Path) -> None:
    """Compare complete faces so shared-position UV swaps cannot masquerade as equivalent."""

    first = _triangle(v=0.1)
    second = _triangle(v=0.9)
    second = second.model_copy(
        update={
            "corners": tuple(
                corner.model_copy(update={"position": tuple(-value for value in corner.position)})
                for corner in second.corners
            )
        }
    )
    changed = []
    for triangle, origin_uv in ((first, second.corners[0].uv), (second, first.corners[0].uv)):
        corners = tuple(
            corner.model_copy(
                update={
                    "normal": (0.10499873757362366, 0.0, math.sqrt(1.0 - 0.10499873757362366**2)),
                }
            )
            for corner in triangle.corners
        )
        changed.append(
            triangle.model_copy(
                update={
                    "corners": (corners[0].model_copy(update={"uv": origin_uv}), *corners[1:]),
                }
            )
        )
    source = _evidence(tmp_path, "optimized_lod0", [first, second])
    target = _evidence(tmp_path, "clean_import_glb", changed)
    assert source.snapshot.uv_fingerprint == target.snapshot.uv_fingerprint
    report = _proof(tmp_path, source, target)
    assert report.overall_status == "failed"
    assert report.numerical_comparison.maximum_uv_component_error == pytest.approx(0.8)
    assert (
        next(check for check in report.checks if check.check_id == "uv_layout").status == "failed"
    )


@pytest.mark.parametrize("mutation", ["file", "source", "summary", "snapshot", "cross_job"])
def test_revalidation_rejects_tampered_or_unbound_proof(tmp_path: Path, mutation: str) -> None:
    """Rehash all inputs and recompute results instead of trusting a claimed passing summary."""

    source, target = _pair(tmp_path)
    report = _proof(tmp_path, source, target)
    if mutation == "file":
        (tmp_path / report.source_corner_evidence.path).write_text("{}", encoding="utf-8")
    elif mutation == "source":
        (tmp_path / source.snapshot.artifact_path).write_bytes(b"changed source")
    elif mutation == "summary":
        report = report.model_copy(
            update={
                "numerical_comparison": report.numerical_comparison.model_copy(
                    update={"maximum_uv_component_error": 0.0},
                )
            }
        )
    elif mutation == "snapshot":
        report = report.model_copy(update={"source_snapshot_sha256": "f" * 64})
    else:
        source = source.model_copy(
            update={
                "snapshot": source.snapshot.model_copy(
                    update={
                        "source_fingerprint_sha256": "f" * 64,
                    }
                )
            }
        )
        path = tmp_path / report.source_corner_evidence.path
        path.write_text(source.model_dump_json(), encoding="utf-8")
        report = report.model_copy(
            update={"source_corner_evidence": bind_corner_evidence(tmp_path, path)}
        )
    with pytest.raises(ValueError):
        validate_numerical_survival_report(tmp_path, report)


@pytest.mark.parametrize("mutation", ["count", "hash", "version", "missing_version", "nonfinite"])
def test_raw_corner_evidence_rejects_incomplete_or_invalid_projection(
    tmp_path: Path, mutation: str
) -> None:
    """Require full finite records reproducing the exact supported-version snapshot."""

    source, _target = _pair(tmp_path)
    payload = source.model_dump(mode="json")
    if mutation == "count":
        payload["snapshot"]["evaluated_triangle_count"] = 2
    elif mutation == "hash":
        payload["snapshot"]["uv_fingerprint"]["sha256"] = "f" * 64
    elif mutation == "version":
        payload["schema_version"] = "0.2.0"
    elif mutation == "missing_version":
        del payload["schema_version"]
    else:
        payload["triangles"][0]["corners"][0]["uv"][0] = float("inf")
    with pytest.raises(ValidationError):
        GeometryDeliveryCornerEvidenceV02.model_validate_json(json.dumps(payload))


def test_raw_evidence_cannot_escape_job_root(tmp_path: Path) -> None:
    """Reject external raw evidence instead of granting numerical proof access outside the job."""

    root = tmp_path / "job"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        bind_corner_evidence(root, outside)


def test_raw_evidence_original_artifact_is_rehashed(tmp_path: Path) -> None:
    """Do not allow a self-consistent JSON record to replace changed source bytes."""

    source, target = _pair(tmp_path)
    report = _proof(tmp_path, source, target)
    assert load_corner_evidence(tmp_path, report.target_corner_evidence) == target
    (tmp_path / target.snapshot.artifact_path).write_bytes(b"new glb")
    with pytest.raises(ValueError, match="source artifact changed"):
        load_corner_evidence(tmp_path, report.target_corner_evidence)


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "source_path",
        "source_hash",
        "primary_path",
        "primary_hash",
        "primary_kind",
        "freeze",
        "build",
        "request",
        "missing_conversion",
        "wrong_run",
        "snapshot",
    ],
)
def test_terminal_consumer_requires_exact_package_binding(
    tmp_path: Path, mutation: str | None
) -> None:
    """Reject a valid proof transplanted onto another package, source, build or request."""

    source, target = _pair(tmp_path)
    geometry_relative = "optimization/runs/delivery-run/aq_v2/geometry"
    report = _proof(tmp_path, source, target, evidence_prefix=geometry_relative)
    for snapshot in (source.snapshot, target.snapshot):
        path = tmp_path / geometry_relative / f"{snapshot.stage}_snapshot.json"
        path.write_text(snapshot.model_dump_json(), encoding="utf-8")
    freeze = SimpleNamespace(v07_source_fingerprint=source.snapshot.source_fingerprint_sha256)
    request = SimpleNamespace(delivery_id="glb", run_id="delivery-run")
    blend = SimpleNamespace(
        path=source.snapshot.artifact_path, sha256=source.snapshot.artifact_sha256
    )
    primary = SimpleNamespace(
        id="primary",
        kind="primary_asset",
        path=target.snapshot.artifact_path,
        sha256=target.snapshot.artifact_sha256,
    )
    material = SimpleNamespace(portable_blend=blend)
    package = SimpleNamespace(
        files=[primary],
        primary_file_id="primary",
        source=SimpleNamespace(build_fingerprint=source.snapshot.build_fingerprint_sha256),
    )
    if mutation == "source_path":
        blend.path = "other-source.blend"
    elif mutation == "source_hash":
        blend.sha256 = "d" * 64
    elif mutation == "primary_path":
        primary.path = "other-target.glb"
    elif mutation == "primary_hash":
        primary.sha256 = "d" * 64
    elif mutation == "primary_kind":
        primary.kind = "metadata"
    elif mutation == "freeze":
        freeze.v07_source_fingerprint = "d" * 64
    elif mutation == "build":
        package.source.build_fingerprint = "d" * 64
    elif mutation == "request":
        request.delivery_id = "other-request"
    elif mutation == "missing_conversion":
        material.portable_blend = None
    elif mutation == "wrong_run":
        request.run_id = "other-run"
    elif mutation == "snapshot":
        changed = source.snapshot.model_copy(update={"build_fingerprint_sha256": "d" * 64})
        (tmp_path / geometry_relative / "optimized_lod0_snapshot.json").write_text(
            changed.model_dump_json(), encoding="utf-8"
        )
    if mutation is None:
        _validate_numerical_package_survival(tmp_path, freeze, request, package, material, report)
    else:
        with pytest.raises(ValueError, match="numerical geometry evidence"):
            _validate_numerical_package_survival(
                tmp_path, freeze, request, package, material, report
            )
