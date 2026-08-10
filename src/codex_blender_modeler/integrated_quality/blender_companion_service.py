"""Host promotion of read-only Blender assembly and topology companion evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from ..analysis.models import ModelingPlan
from ..blender_artifacts import native_io_path
from ..blender_runner import run_blender
from ..blender_scripts.assembly.models import (
    AssemblyArtifact,
    AssemblyCompanionReport,
    AssemblyCompanionRequest,
    AssemblyFinding,
    AssemblyProvenance,
    BVHNarrowObservation,
    SemanticAssemblyRelation,
    TriangleMeshEvidence,
)
from ..blender_scripts.assembly.service import build_broad_phase_pairs
from ..blender_scripts.topology.models import (
    TopologyArtifact,
    TopologyCompanionReport,
    TopologyObservation,
    TopologyProvenance,
)
from ..blender_scripts.topology.service import evaluate_topology_profile
from ..models import SceneSpec
from ..versioning import PROJECT_VERSION


@dataclass(frozen=True)
class StaticPropCompanionResult:
    """Expose final immutable paths and validated strict companion reports."""

    output_root: Path
    snapshot_path: Path
    assembly_request_path: Path
    assembly_report_path: Path
    topology_report_path: Path
    assembly_report: AssemblyCompanionReport
    topology_report: TopologyCompanionReport


def _sha256(path: Path) -> str:
    """Hash one exact file in bounded streaming chunks."""

    digest = hashlib.sha256()
    with open(native_io_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text(path: Path) -> str:
    """Read one companion artifact through a Windows extended-length path."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        return handle.read()


def _is_file(path: Path) -> bool:
    """Test one companion file without legacy Windows path-length truncation."""

    return os.path.isfile(native_io_path(path))


def _exists(path: Path) -> bool:
    """Test one companion path without legacy Windows path-length truncation."""

    return os.path.exists(native_io_path(path))


def _archive_interrupted_stages(output_root: Path) -> list[Path]:
    """Archive receipt-less companion stages before one deterministic retry."""

    parent = output_root.parent
    if not _exists(parent):
        return []
    prefix = f".{output_root.name}.staging-"
    interrupted = parent / "interrupted_staging"
    archived: list[Path] = []
    with os.scandir(native_io_path(parent)) as entries:
        candidates = sorted(
            (entry for entry in entries if entry.name.startswith(prefix)),
            key=lambda entry: entry.name,
        )
    for entry in candidates:
        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
            raise RuntimeError(
                "interrupted companion stage is not a plain directory: "
                f"{entry.name}"
            )
        os.makedirs(native_io_path(interrupted), exist_ok=True)
        destination = interrupted / entry.name
        if _exists(destination):
            raise RuntimeError(f"interrupted companion archive already exists: {entry.name}")
        os.replace(entry.path, native_io_path(destination))
        archived.append(destination)
    return archived


def _resolve_job_relative(job_root: Path, value: str) -> Path:
    """Resolve one normalized POSIX job-relative path without allowing escape."""

    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not value
        or "\\" in value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("companion paths must be normalized job-relative POSIX paths")
    root = job_root.resolve()
    candidate = (root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("companion path escapes the job workspace") from exc
    return candidate


def _relative(job_root: Path, path: Path) -> str:
    """Convert one contained file path to normalized job-relative POSIX form."""

    return path.resolve().relative_to(job_root.resolve()).as_posix()


def _write_model(path: Path, model: Any) -> None:
    """Persist one validated model without overwriting an existing artifact."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    with open(native_io_path(path), "x", encoding="utf-8", newline="\n") as handle:
        handle.write(model.model_dump_json(indent=2) + "\n")


def _load_snapshot(path: Path, expected_hashes: dict[str, str]) -> dict[str, Any]:
    """Load the bounded Blender snapshot and verify its exact source hash echo."""

    try:
        payload = json.loads(_read_text(path))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Blender companion snapshot is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Blender companion snapshot must contain one JSON object")
    if payload.get("kind") != "static_prop_authoring_companion_snapshot":
        raise RuntimeError("Blender companion snapshot has an unexpected kind")
    if payload.get("source_hashes") != expected_hashes:
        raise RuntimeError("Blender companion snapshot source hashes are stale")
    topology = payload.get("topology")
    assembly = payload.get("assembly")
    if not isinstance(topology, dict) or not isinstance(assembly, dict):
        raise RuntimeError("Blender companion snapshot is missing topology or assembly evidence")
    return payload


def _normalized_request_relations(plan: ModelingPlan) -> list[SemanticAssemblyRelation]:
    """Preserve relationship identity in the strict request without inventing measurements."""

    result: list[SemanticAssemblyRelation] = []
    for relation in plan.assembly_relationships:
        tolerance_m = (
            float(relation.tolerance.value) if relation.tolerance.mode == "meters" else 0.001
        )
        result.append(
            SemanticAssemblyRelation(
                relation_id=relation.id,
                kind="center_plane",
                subject_id=relation.subject_id,
                reference_id=relation.reference_id,
                required=relation.required,
                tolerance_m=tolerance_m,
                measured_value_m=None,
            )
        )
    return result


def _assembly_request(
    *,
    plan: ModelingPlan,
    provenance: AssemblyProvenance,
    snapshot: dict[str, Any],
    snapshot_artifact: AssemblyArtifact,
    request_id: str,
) -> AssemblyCompanionRequest:
    """Validate evaluated semantic meshes and Blender BVH observations as one request."""

    assembly = snapshot["assembly"]
    meshes = [
        TriangleMeshEvidence.model_validate_json(
            json.dumps(
                {
                    "object_id": str(item["object_id"]),
                    "snapshot": snapshot_artifact.model_dump(mode="json"),
                    "bounds": item["bounds"],
                    "vertices_m": item["vertices_m"],
                    "triangles": item["triangles"],
                }
            )
        )
        for item in assembly.get("meshes", [])
    ]
    observations = [
        BVHNarrowObservation.model_validate_json(json.dumps(item))
        for item in assembly.get("narrow_observations", [])
    ]
    return AssemblyCompanionRequest(
        request_id=request_id,
        provenance=provenance,
        meshes=meshes,
        semantic_relations=_normalized_request_relations(plan),
        narrow_observations=observations,
        maximum_distance_samples=512,
        maximum_triangle_pair_tests=4096,
    )


def _semantic_findings(plan: ModelingPlan, evaluation: dict[str, Any]) -> list[AssemblyFinding]:
    """Convert live relationship checks without mislabeling non-meter residuals."""

    checks = evaluation.get("checks", [])
    if not isinstance(checks, list):
        raise RuntimeError("assembly relationship evaluation checks must be an array")
    by_relation: dict[str, list[dict[str, Any]]] = {}
    for check in checks:
        if not isinstance(check, dict):
            raise RuntimeError("assembly relationship checks must contain objects")
        relation_id = check.get("relation_id")
        if isinstance(relation_id, str):
            by_relation.setdefault(relation_id, []).append(check)
    findings: list[AssemblyFinding] = []
    for relation in plan.assembly_relationships:
        related = by_relation.get(relation.id, [])
        unavailable = not related or any(
            item.get("metrics", {}).get("scorable") is False for item in related
        )
        if unavailable:
            severity = "unscorable"
        elif any(item.get("status") == "failed" for item in related):
            severity = "hard_failure" if relation.required else "warning"
        elif any(item.get("status") == "warning" for item in related):
            severity = "warning"
        else:
            severity = "info"
        meter_checks = [
            item
            for item in related
            if item.get("tolerance_mode") == "meters"
            and isinstance(item.get("residual"), (int, float))
        ]
        measured = max(float(item["residual"]) for item in meter_checks) if meter_checks else None
        limit = max(float(item["tolerance"]) for item in meter_checks) if meter_checks else None
        messages = [str(item.get("message", "")) for item in related]
        findings.append(
            AssemblyFinding(
                finding_id=f"semantic.{relation.id}",
                phase="semantic",
                severity=severity,
                code=f"SEMANTIC_{relation.kind.upper()}",
                subject_id=relation.subject_id,
                reference_id=relation.reference_id,
                relation_id=relation.id,
                measured_value_m=measured,
                limit_value_m=limit,
                message=(
                    " | ".join(messages[:4])
                    if messages
                    else "Declared relationship has no evaluated Blender check."
                ),
            )
        )
    return findings


def _assembly_report(
    *,
    request: AssemblyCompanionRequest,
    request_path: str,
    request_sha256: str,
    snapshot: dict[str, Any],
    plan: ModelingPlan,
    report_id: str,
) -> AssemblyCompanionReport:
    """Build a strict report from broad, actual BVH, and semantic Blender evidence."""

    broad_pairs = build_broad_phase_pairs(request.meshes)
    findings: list[AssemblyFinding] = [
        AssemblyFinding(
            finding_id=f"broad.{pair.subject_id}.{pair.reference_id}",
            phase="broad",
            severity="info",
            code=(
                "AABB_OVERLAP_CANDIDATE" if pair.status == "overlap_candidate" else "AABB_SEPARATED"
            ),
            subject_id=pair.subject_id,
            reference_id=pair.reference_id,
            message=(
                "Evaluated AABBs overlap; this is broad-phase evidence only."
                if pair.status == "overlap_candidate"
                else "Evaluated AABBs are separated on at least one axis."
            ),
        )
        for pair in broad_pairs
    ]
    for observation in request.narrow_observations:
        if observation.status != "available":
            severity = "unscorable"
            code = "NARROW_PHASE_UNAVAILABLE"
            message = observation.error or "Evaluated mesh evidence is empty."
        elif observation.overlap_triangle_pair_count:
            severity = "warning"
            code = "BVH_SURFACE_INTERSECTION"
            message = (
                "Blender BVH found surface overlap; signed penetration depth and "
                "mechanism behavior remain unavailable."
            )
        else:
            severity = "info"
            code = "BVH_SEPARATED_OR_CONTACT"
            message = "Blender BVH found no triangle-surface overlap."
        findings.append(
            AssemblyFinding(
                finding_id=f"narrow.{observation.subject_id}.{observation.reference_id}",
                phase="narrow",
                severity=severity,
                code=code,
                subject_id=observation.subject_id,
                reference_id=observation.reference_id,
                measured_value_m=observation.minimum_distance_m,
                message=message,
            )
        )
    evaluation = snapshot["assembly"].get("relationship_evaluation", {})
    if not isinstance(evaluation, dict):
        raise RuntimeError("assembly relationship evaluation must be an object")
    findings.extend(_semantic_findings(plan, evaluation))
    hard_failures = sum(item.severity == "hard_failure" for item in findings)
    warnings = sum(item.severity == "warning" for item in findings)
    unscorable = sum(item.severity == "unscorable" for item in findings)
    status = (
        "failed"
        if hard_failures
        else "unscorable"
        if unscorable
        else "warning"
        if warnings
        else "passed"
    )
    return AssemblyCompanionReport(
        report_id=report_id,
        provenance=request.provenance,
        request=AssemblyArtifact(role="assembly_request", path=request_path, sha256=request_sha256),
        status=status,
        ok=status == "passed",
        broad_pairs=broad_pairs,
        narrow_observations=request.narrow_observations,
        findings=findings,
        hard_failures=hard_failures,
        warnings=warnings,
        unscorable=unscorable,
        limitations=[
            "BVH surface overlap is not a signed penetration-depth measurement.",
            "Evaluated relationships do not prove mechanism motion or hidden structure truth.",
            "Relative and angular residuals remain in the raw snapshot and are not "
            "mislabeled as meters.",
        ],
    )


def _topology_report(
    *,
    snapshot: dict[str, Any],
    provenance: TopologyProvenance,
    evidence: TopologyArtifact,
    report_id: str,
) -> TopologyCompanionReport:
    """Promote all 18 raw checks through the immutable static_prop_closed profile."""

    raw = snapshot["topology"].get("observations", [])
    if not isinstance(raw, list):
        raise RuntimeError("topology observations must be an array")
    observations: list[TopologyObservation] = []
    for item in raw:
        if not isinstance(item, dict):
            raise RuntimeError("topology observations must contain objects")
        payload = dict(item)
        if payload.get("availability") == "available":
            payload["evidence"] = evidence.model_dump(mode="json")
        observations.append(
            TopologyObservation.model_validate_json(json.dumps(payload))
        )
    return evaluate_topology_profile(
        report_id=report_id,
        provenance=provenance,
        profile_name="static_prop_closed",
        observations=observations,
    )


def inspect_static_prop_authoring_companions(
    *,
    job_root: Path,
    workflow_id: str,
    dispatch_id: str,
    output_root_relative: str,
    scene_spec_relative: str = "analysis/scene_spec.json",
    modeling_plan_relative: str = "analysis/modeling_plan.json",
    blend_relative: str = "blender/scene.blend",
) -> StaticPropCompanionResult:
    """Inspect one current authoring blend and atomically publish strict companion evidence."""

    root = job_root.resolve()
    scene_path = _resolve_job_relative(root, scene_spec_relative)
    plan_path = _resolve_job_relative(root, modeling_plan_relative)
    blend_path = _resolve_job_relative(root, blend_relative)
    for path in (scene_path, plan_path, blend_path):
        if not _is_file(path):
            raise FileNotFoundError(path)
    scene = SceneSpec.model_validate_json(_read_text(scene_path))
    plan = ModelingPlan.model_validate_json(_read_text(plan_path))
    if scene.job_id != plan.job_id or scene.job_id != root.name:
        raise ValueError("SceneSpec, ModelingPlan, and job directory identities must match")
    output_root = _resolve_job_relative(root, output_root_relative)
    if _exists(output_root):
        raise FileExistsError(f"companion output already exists: {output_root}")
    os.makedirs(native_io_path(output_root.parent), exist_ok=True)
    _archive_interrupted_stages(output_root)
    stage = output_root.parent / f".{output_root.name}.staging-{uuid4().hex}"
    os.mkdir(native_io_path(stage))
    source_hashes = {
        "scene_spec": _sha256(scene_path),
        "modeling_plan": _sha256(plan_path),
        "blend": _sha256(blend_path),
    }
    snapshot_stage = stage / "authoring_companion_snapshot.json"
    try:
        run_blender(
            "inspect_quality_companions.py",
            [
                "--job-root",
                str(root),
                "--output",
                str(snapshot_stage),
                "--modeling-plan-relative",
                modeling_plan_relative,
                "--scene-spec-sha256",
                source_hashes["scene_spec"],
                "--modeling-plan-sha256",
                source_hashes["modeling_plan"],
                "--blend-sha256",
                source_hashes["blend"],
            ],
            blend_file=blend_path,
            disable_autoexec=True,
        )
        snapshot = _load_snapshot(snapshot_stage, source_hashes)
        final_snapshot = output_root / snapshot_stage.name
        snapshot_relative = _relative(root, final_snapshot)
        snapshot_sha = _sha256(snapshot_stage)
        assembly_provenance = AssemblyProvenance(
            job_id=scene.job_id,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            project_version=PROJECT_VERSION,
            inputs=[
                AssemblyArtifact(
                    role="scene_spec", path=scene_spec_relative, sha256=source_hashes["scene_spec"]
                ),
                AssemblyArtifact(
                    role="modeling_plan",
                    path=modeling_plan_relative,
                    sha256=source_hashes["modeling_plan"],
                ),
                AssemblyArtifact(role="blend", path=blend_relative, sha256=source_hashes["blend"]),
            ],
        )
        request = _assembly_request(
            plan=plan,
            provenance=assembly_provenance,
            snapshot=snapshot,
            snapshot_artifact=AssemblyArtifact(
                role="mesh_snapshot", path=snapshot_relative, sha256=snapshot_sha
            ),
            request_id=f"{dispatch_id}.assembly-request",
        )
        request_stage = stage / "assembly_companion_request.json"
        _write_model(request_stage, request)
        final_request = output_root / request_stage.name
        report = _assembly_report(
            request=request,
            request_path=_relative(root, final_request),
            request_sha256=_sha256(request_stage),
            snapshot=snapshot,
            plan=plan,
            report_id=f"{dispatch_id}.assembly-report",
        )
        assembly_report_stage = stage / "assembly_companion_report.json"
        _write_model(assembly_report_stage, report)
        topology_provenance = TopologyProvenance(
            job_id=scene.job_id,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            project_version=PROJECT_VERSION,
            inputs=[
                TopologyArtifact(
                    role="scene_spec", path=scene_spec_relative, sha256=source_hashes["scene_spec"]
                ),
                TopologyArtifact(role="blend", path=blend_relative, sha256=source_hashes["blend"]),
                TopologyArtifact(
                    role="topology_inventory", path=snapshot_relative, sha256=snapshot_sha
                ),
            ],
        )
        topology_report = _topology_report(
            snapshot=snapshot,
            provenance=topology_provenance,
            evidence=TopologyArtifact(
                role="topology_inventory", path=snapshot_relative, sha256=snapshot_sha
            ),
            report_id=f"{dispatch_id}.topology-report",
        )
        topology_report_stage = stage / "topology_companion_report.json"
        _write_model(topology_report_stage, topology_report)
        if {
            key: _sha256(path)
            for key, path in (
                ("scene_spec", scene_path),
                ("modeling_plan", plan_path),
                ("blend", blend_path),
            )
        } != source_hashes:
            raise RuntimeError("Canonical authoring evidence changed during companion inspection")
        os.replace(native_io_path(stage), native_io_path(output_root))
    except Exception:
        shutil.rmtree(native_io_path(stage), ignore_errors=True)
        raise
    return StaticPropCompanionResult(
        output_root=output_root,
        snapshot_path=output_root / snapshot_stage.name,
        assembly_request_path=output_root / request_stage.name,
        assembly_report_path=output_root / assembly_report_stage.name,
        topology_report_path=output_root / topology_report_stage.name,
        assembly_report=report,
        topology_report=topology_report,
    )
