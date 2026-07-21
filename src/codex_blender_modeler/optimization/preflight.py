"""Host-side V0.7 portable mesh-preflight orchestration."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..blender_artifacts import write_json_atomic
from ..blender_runner import run_blender
from ..config import load_feature_config
from ..workspace import job_dir, sha256_file
from .io import job_relative, new_run_id, run_directory, utc_now, write_latest_run, write_model
from .models import (
    AssetProfile,
    Bounds3D,
    HashedArtifact,
    MeshPreflightCheck,
    MeshPreflightReport,
    MeshSummary,
)
from .provenance import collect_source_provenance, require_unchanged_source


def profile_path(job_root: Path, profile_id: str) -> Path:
    """Resolve one profile contract under its job-owned asset profile directory."""

    if profile_id not in {"portable_gltf", "fbx_interchange", "obj_legacy"}:
        raise ValueError("Unsupported portable profile")
    return job_root / "asset_profiles" / f"{profile_id}.json"


def load_asset_profile(job_root: Path, profile_id: str) -> AssetProfile:
    """Load and validate one existing engine-neutral asset profile."""

    path = profile_path(job_root, profile_id)
    if not path.is_file():
        raise FileNotFoundError(
            f"Asset profile does not exist; initialize it before preflight: {path}"
        )
    return AssetProfile.model_validate_json(path.read_text(encoding="utf-8"))


def _preflight_policy(profile: AssetProfile) -> dict[str, Any]:
    """Translate a versioned asset profile into bounded Blender inspection switches."""

    return {
        "require_uv0": not profile.uv.generate_uv0_if_missing,
        "require_material": True,
        "require_applied_scale": True,
        "fail_on_negative_determinant": True,
        "fail_on_non_finite": True,
        "fail_on_degenerate_faces": True,
        "fail_on_loose_geometry": False,
        "fail_on_open_boundaries": False,
        "allowed_open_semantic_ids": [],
        "max_triangles_total": None,
        "max_triangles_per_object": None,
    }


def _check_category(message: str) -> str:
    """Classify a Blender diagnostic into the portable preflight contract taxonomy."""

    lowered = message.lower()
    if "material" in lowered:
        return "material"
    if "uv" in lowered:
        return "uv"
    if "normal" in lowered:
        return "normal"
    if "scale" in lowered or "determinant" in lowered or "transform" in lowered:
        return "transform"
    if "triangle" in lowered or "budget" in lowered:
        return "budget"
    return "topology"


def _raw_checks(
    raw: dict[str, Any],
    evidence_path: str,
) -> list[MeshPreflightCheck]:
    """Convert raw Blender errors and warnings into uniquely identified checks."""

    checks: list[MeshPreflightCheck] = []
    for status, key in (("failed", "errors"), ("warning", "warnings")):
        messages = raw.get(key, [])
        if not isinstance(messages, list):
            raise ValueError(f"Raw preflight {key} must be an array")
        for index, value in enumerate(messages, start=1):
            message = str(value)
            checks.append(
                MeshPreflightCheck(
                    id=f"preflight.{status}.{index:04d}",
                    category=_check_category(message),  # type: ignore[arg-type]
                    status=status,  # type: ignore[arg-type]
                    message=message,
                    evidence_path=evidence_path,
                )
            )
    checks.append(
        MeshPreflightCheck(
            id="preflight.inspection.completed",
            category="topology",
            status="passed",
            message="Blender completed read-only portable topology inspection.",
            evidence_path=evidence_path,
        )
    )
    return checks


def _mesh_summaries(raw: dict[str, Any]) -> list[MeshSummary]:
    """Aggregate Blender object instances into stable semantic mesh-family summaries."""

    objects = raw.get("objects", [])
    if not isinstance(objects, list):
        raise ValueError("Raw preflight objects must be an array")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in objects:
        if not isinstance(record, dict) or record.get("type") not in {"MESH", "CURVE"}:
            continue
        target_id = str(record.get("semantic_id") or record.get("name") or "")
        if not target_id:
            raise ValueError("Every portable mesh requires a stable semantic ID")
        groups[target_id].append(record)

    summaries: list[MeshSummary] = []
    for target_id, records in sorted(groups.items()):
        topology_records = [
            record.get("topology", {})
            for record in records
            if isinstance(record.get("topology"), dict)
        ]
        minima = [record["bbox_world"]["min"] for record in records]
        maxima = [record["bbox_world"]["max"] for record in records]
        boundary_count = sum(int(item.get("boundary_edge_count", 0)) for item in topology_records)
        exceptions = ["open_boundary"] if boundary_count else []
        if any(record.get("type") == "CURVE" for record in records):
            exceptions.append("evaluated_curve_topology_unavailable_during_preflight")
        summaries.append(
            MeshSummary(
                target_id=target_id,
                object_count=len(records),
                vertex_count=sum(int(item.get("vertices", 0)) for item in topology_records),
                triangle_count=sum(
                    int(item.get("triangles_estimated", 0)) for item in topology_records
                ),
                boundary_edge_count=boundary_count,
                non_manifold_edge_count=sum(
                    int(item.get("overused_edge_count", 0)) for item in topology_records
                ),
                degenerate_face_count=sum(
                    int(item.get("degenerate_face_count", 0)) for item in topology_records
                ),
                negative_scale_count=sum(
                    bool(item.get("negative_determinant")) for item in topology_records
                ),
                bounds=Bounds3D(
                    minimum=tuple(
                        min(float(value[axis]) for value in minima) for axis in range(3)
                    ),
                    maximum=tuple(
                        max(float(value[axis]) for value in maxima) for axis in range(3)
                    ),
                ),
                declared_exceptions=exceptions,
            )
        )
    return summaries


def _verify_raw_source(raw: dict[str, Any], job_id: str, fingerprint: str) -> None:
    """Reject Blender evidence produced from a stale or mismatched authoring scene."""

    source = raw.get("source")
    if not isinstance(source, dict):
        raise RuntimeError("Blender preflight did not report source provenance")
    if source.get("job_id") != job_id:
        raise RuntimeError(
            f"Blender scene job mismatch: {source.get('job_id')!r} != {job_id!r}"
        )
    embedded = source.get("build_fingerprint") or source.get(
        "material_build_fingerprint"
    )
    if embedded != fingerprint:
        raise RuntimeError(
            "Blender scene is stale relative to canonical geometry/material contracts; "
            "rebuild before V0.7 preflight."
        )


def run_asset_preflight(
    job_id: str,
    profile_id: str = "portable_gltf",
    *,
    run_id: str | None = None,
) -> MeshPreflightReport:
    """Run one isolated read-only Blender preflight and persist its validated report."""

    if not load_feature_config().features.portable_asset_core:
        raise RuntimeError("portable_asset_core is disabled in cbm.toml")
    root = job_dir(job_id)
    profile = load_asset_profile(root, profile_id)
    if profile.job_id != job_id:
        raise ValueError("Asset profile job_id does not match the requested job")
    selected_run_id = run_id or new_run_id("preflight")
    source = collect_source_provenance(root, job_id)
    profile_receipt = profile_artifact(root, profile)
    run_root = run_directory(root, selected_run_id, create=True)
    policy_path = run_root / "preflight_policy.json"
    raw_path = run_root / "preflight_raw.json"
    try:
        write_json_atomic(policy_path, _preflight_policy(profile))
        run_blender(
            "inspect_asset_topology.py",
            ["--output", str(raw_path), "--policy", str(policy_path)],
            blend_file=root / "blender" / "scene.blend",
        )
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Raw Blender preflight must contain a JSON object")
        _verify_raw_source(raw, job_id, source.build_fingerprint)
        require_unchanged_source(source, root, job_id)
        evidence_path = job_relative(root, raw_path)
        checks = _raw_checks(raw, evidence_path)
        counts = {
            status: sum(check.status == status for check in checks)
            for status in ("passed", "warning", "failed")
        }
        ok = counts["failed"] == 0
        report = MeshPreflightReport(
            report_id=f"preflight.{selected_run_id}",
            job_id=job_id,
            profile_id=profile.profile_id,
            profile_artifact=profile_receipt,
            source=source,
            status="passed" if ok else "failed",
            ok=ok,
            passed=counts["passed"],
            warnings=counts["warning"],
            failed=counts["failed"],
            checks=checks,
            meshes=_mesh_summaries(raw),
            created_at=utc_now(),
            notes=[
                f"Raw Blender evidence: {evidence_path}",
                f"Raw evidence SHA-256: {sha256_file(raw_path)}",
            ],
        )
        write_model(run_root / "mesh_preflight_report.json", report)
        write_latest_run(
            root,
            selected_run_id,
            "preflight_passed" if ok else "preflight_failed",
        )
        return report
    except Exception as exc:
        failed = MeshPreflightReport(
            report_id=f"preflight.{selected_run_id}",
            job_id=job_id,
            profile_id=profile.profile_id,
            profile_artifact=profile_receipt,
            source=source,
            status="failed",
            ok=False,
            passed=0,
            warnings=0,
            failed=1,
            checks=[
                MeshPreflightCheck(
                    id="preflight.execution.failed",
                    category="topology",
                    status="failed",
                    message=str(exc),
                )
            ],
            meshes=[],
            created_at=utc_now(),
            notes=["Preflight execution failed before normalized evidence completed."],
        )
        write_model(run_root / "mesh_preflight_report.json", failed)
        write_latest_run(root, selected_run_id, "preflight_error")
        raise


def profile_artifact(job_root: Path, profile: AssetProfile) -> HashedArtifact:
    """Hash one stored profile for optimization-plan provenance."""

    path = profile_path(job_root, profile.profile_id)
    return HashedArtifact(
        id=f"profile.{profile.profile_id}",
        kind="asset_profile",
        path=job_relative(job_root, path),
        sha256=sha256_file(path),
    )
