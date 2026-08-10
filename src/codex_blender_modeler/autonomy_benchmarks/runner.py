"""Host-first deterministic runner for the Autonomous Quality benchmark manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..blender_scripts.assembly import build_assembly_companion_report
from ..blender_scripts.assembly.models import AssemblyCompanionRequest
from ..blender_scripts.topology import evaluate_topology_profile, get_topology_profile
from ..blender_scripts.topology.models import (
    TopologyArtifact,
    TopologyObservation,
    TopologyProvenance,
)
from ..material_graph import MaterialGraphSpec
from ..models import PrimitiveGeometry, TerrainGeometry
from ..structural_geometry.mesh_math import build_loft_mesh, build_sweep_mesh
from ..structural_geometry.models import (
    BooleanTreeGeometry,
    LoftGeometry,
    StructuralGeometryCandidate,
    SweepGeometry,
)
from ..structural_geometry.service import materialize_structural_candidate
from .models import (
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkManifest,
    BenchmarkOutcome,
    BenchmarkReport,
)

_RUNNER_VERSION = "0.1.0"


def _canonical_bytes(value: Any) -> bytes:
    """Serialize one JSON-compatible value to deterministic UTF-8 bytes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    """Return the canonical SHA-256 digest for one JSON-compatible value."""

    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_output_path(path: Path) -> Path:
    """Resolve one immutable report path while rejecting every existing target."""

    resolved = path.resolve()
    if resolved.exists():
        raise FileExistsError(f"benchmark report already exists: {resolved.name}")
    return resolved


def _mesh_metrics(mesh: dict[str, Any]) -> dict[str, int | str]:
    """Return stable mesh counts and a canonical payload digest."""

    return {
        "vertex_count": len(mesh["vertices"]),
        "face_count": len(mesh["faces"]),
        "mesh_sha256": _sha256(mesh),
    }


def _run_simple_box(payload: dict[str, Any]) -> tuple[BenchmarkOutcome, dict[str, Any]]:
    """Validate one primitive box and report its explicit metric dimensions."""

    geometry = PrimitiveGeometry.model_validate(payload["geometry"])
    if geometry.primitive != "cube":
        raise ValueError("simple_box fixture must use a cube primitive")
    return "passed", {
        "primitive": geometry.primitive,
        "dimension_x_m": geometry.dimensions[0],
        "dimension_y_m": geometry.dimensions[1],
        "dimension_z_m": geometry.dimensions[2],
    }


def _run_loft(payload: dict[str, Any]) -> tuple[BenchmarkOutcome, dict[str, Any]]:
    """Compile one loft twice and require deterministic host mesh output."""

    geometry = LoftGeometry.model_validate_json(json.dumps(payload["geometry"]))
    first = build_loft_mesh(geometry.model_dump(mode="json"))
    second = build_loft_mesh(geometry.model_dump(mode="json"))
    if first != second:
        raise RuntimeError("loft host compilation was not deterministic")
    return "passed", _mesh_metrics(first)


def _run_sweep(payload: dict[str, Any]) -> tuple[BenchmarkOutcome, dict[str, Any]]:
    """Compile one curved sweep twice and require deterministic host mesh output."""

    geometry = SweepGeometry.model_validate_json(json.dumps(payload["geometry"]))
    first = build_sweep_mesh(geometry.model_dump(mode="json"))
    second = build_sweep_mesh(geometry.model_dump(mode="json"))
    if first != second:
        raise RuntimeError("sweep host compilation was not deterministic")
    return "passed", _mesh_metrics(first)


def _run_boolean_panel(payload: dict[str, Any]) -> tuple[BenchmarkOutcome, dict[str, Any]]:
    """Validate one complete bounded Boolean tree without claiming host mesh evaluation."""

    geometry = BooleanTreeGeometry.model_validate_json(json.dumps(payload["geometry"]))
    return "passed", {
        "operand_count": len(geometry.operands),
        "operation_count": len(geometry.operations),
        "root_id": geometry.root_id,
        "host_mesh_evaluation": "requires_blender_opt_in",
    }


def _run_small_assembly(payload: dict[str, Any]) -> tuple[BenchmarkOutcome, dict[str, Any]]:
    """Evaluate one bounded semantic-contact assembly fixture in pure Python."""

    request = AssemblyCompanionRequest.model_validate_json(json.dumps(payload["request"]))
    report = build_assembly_companion_report(
        request,
        request_path="benchmarks/small_assembly/request.json",
        request_sha256=_sha256(request.model_dump(mode="json")),
        report_id="aq-small-assembly-report",
    )
    return report.status, {
        "hard_failures": report.hard_failures,
        "warnings": report.warnings,
        "unscorable": report.unscorable,
        "broad_pair_count": len(report.broad_pairs),
        "narrow_observation_count": len(report.narrow_observations),
    }


def _run_terrain(payload: dict[str, Any]) -> tuple[BenchmarkOutcome, dict[str, Any]]:
    """Validate one inline height-grid and derive deterministic grid topology counts."""

    geometry = TerrainGeometry.model_validate(payload["geometry"])
    if geometry.mode != "height_grid" or geometry.heights is None:
        raise ValueError("terrain benchmark requires an inline height_grid")
    rows = len(geometry.heights)
    columns = len(geometry.heights[0])
    return "passed", {
        "row_count": rows,
        "column_count": columns,
        "vertex_count": rows * columns,
        "quad_count": (rows - 1) * (columns - 1),
    }


def _run_material_graph(payload: dict[str, Any]) -> tuple[BenchmarkOutcome, dict[str, Any]]:
    """Validate one whitelist-only material graph with portable channel semantics."""

    graph = MaterialGraphSpec.model_validate_json(json.dumps(payload["graph"]))
    return "passed", {
        "material_id": graph.material_id,
        "base_channel_count": len(graph.base_channels),
        "layer_count": len(graph.layers),
        "bake_required": graph.bake.required,
    }


def _run_topology_uv_failure(
    payload: dict[str, Any],
) -> tuple[BenchmarkOutcome, dict[str, Any]]:
    """Prove that one explicit UV0 failure remains a hard topology failure."""

    profile_name = payload["profile"]
    evidence = TopologyArtifact(
        role="topology_inventory",
        path="benchmarks/topology/inventory.json",
        sha256="c" * 64,
    )
    observations = [
        TopologyObservation(
            check=policy.check,
            availability="available",
            passed=policy.check != "uv0",
            measured_value=0,
            evidence=evidence,
            message=(
                "fixture intentionally omits a valid UV0"
                if policy.check == "uv0"
                else "fixture passes"
            ),
        )
        for policy in get_topology_profile(profile_name).checks
    ]
    provenance = TopologyProvenance(
        job_id="aq_benchmark",
        workflow_id="workflow-aq-benchmark",
        dispatch_id="dispatch-aq-benchmark",
        project_version="0.9.0",
        inputs=[
            TopologyArtifact(
                role="scene_spec",
                path="analysis/scene_spec.json",
                sha256="a" * 64,
            ),
            TopologyArtifact(
                role="blend",
                path="blender/scene.blend",
                sha256="b" * 64,
            ),
        ],
    )
    report = evaluate_topology_profile(
        report_id="aq-topology-uv-failure",
        provenance=provenance,
        profile_name=profile_name,
        observations=observations,
    )
    uv_result = next(item for item in report.results if item.check == "uv0")
    return report.status, {
        "profile": profile_name,
        "uv0_outcome": uv_result.outcome,
        "hard_failures": report.hard_failures,
        "warnings": report.warnings,
        "unscorable": report.unscorable,
    }


_HOST_RUNNERS = {
    "simple_box": _run_simple_box,
    "loft": _run_loft,
    "sweep": _run_sweep,
    "boolean_panel": _run_boolean_panel,
    "small_assembly": _run_small_assembly,
    "terrain": _run_terrain,
    "material_graph": _run_material_graph,
    "topology_uv_failure": _run_topology_uv_failure,
}


def _run_blender_case(case: BenchmarkCase, output_root: Path) -> dict[str, str]:
    """Materialize one supported structural case in an isolated report-owned directory."""

    candidate = StructuralGeometryCandidate.model_validate_json(
        json.dumps(
            {
                "semantic_id": f"benchmark.{case.case_id}",
                "geometry": case.payload["geometry"],
            }
        )
    )
    case_root = output_root / "blender" / case.case_id
    materialized = materialize_structural_candidate(
        job_root=case_root,
        candidate=candidate,
        candidate_relative_path="structural/candidate.json",
        mesh_relative_path="geometry/materialized.mesh.json",
        blend_relative_path="blender/materialized.blend",
        report_relative_path="reports/materialization.json",
    )
    return {
        "mesh": f"blender/{case.case_id}/geometry/materialized.mesh.json",
        "blend": f"blender/{case.case_id}/blender/materialized.blend",
        "report": f"blender/{case.case_id}/reports/materialization.json",
        "mesh_sha256": _sha256(materialized.model_dump(mode="json")),
    }


def _evaluate_case(
    case: BenchmarkCase,
    *,
    run_blender_smoke: bool,
    output_root: Path,
) -> BenchmarkCaseResult:
    """Evaluate one case and turn deterministic host or Blender errors into gate evidence."""

    payload_sha256 = _sha256(case.payload)
    try:
        observed, metrics = _HOST_RUNNERS[case.category](case.payload)
        blender_status = "not_applicable"
        blender_artifacts: dict[str, str] = {}
        error = None
        if case.blender_smoke_supported:
            blender_status = "not_requested"
            if run_blender_smoke:
                try:
                    blender_artifacts = _run_blender_case(case, output_root)
                    blender_status = "passed"
                except Exception as exc:  # noqa: BLE001 - report exact bounded smoke failure
                    blender_status = "failed"
                    error = f"{type(exc).__name__}: {exc}"
        matched = observed == case.expected_outcome
        return BenchmarkCaseResult(
            case_id=case.case_id,
            category=case.category,
            payload_sha256=payload_sha256,
            expected_outcome=case.expected_outcome,
            observed_outcome=observed,
            expectation_matched=matched,
            host_metrics=metrics,
            blender_status=blender_status,
            blender_artifacts=blender_artifacts,
            error=error,
            ok=matched and blender_status != "failed",
        )
    except Exception as exc:  # noqa: BLE001 - preserve fixture failure as machine evidence
        observed: BenchmarkOutcome = "failed"
        return BenchmarkCaseResult(
            case_id=case.case_id,
            category=case.category,
            payload_sha256=payload_sha256,
            expected_outcome=case.expected_outcome,
            observed_outcome=observed,
            expectation_matched=False,
            host_metrics={"host_evaluation_completed": False},
            blender_status="not_requested" if case.blender_smoke_supported else "not_applicable",
            error=f"{type(exc).__name__}: {exc}",
            ok=False,
        )


def run_benchmark_manifest(
    manifest_path: Path,
    output_path: Path,
    *,
    run_blender_smoke: bool = False,
) -> BenchmarkReport:
    """Validate one manifest, execute every case, and write one deterministic JSON report."""

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = BenchmarkManifest.model_validate(manifest_data)
    report_path = _safe_output_path(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results = [
        _evaluate_case(
            case,
            run_blender_smoke=run_blender_smoke,
            output_root=report_path.parent,
        )
        for case in manifest.cases
    ]
    passed = sum(case.ok for case in results)
    report = BenchmarkReport(
        benchmark_id=manifest.benchmark_id,
        manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        runner_version=_RUNNER_VERSION,
        blender_requested=run_blender_smoke,
        blender_executed_case_count=sum(
            case.blender_status in {"passed", "failed"} for case in results
        ),
        case_results=results,
        passed_case_count=passed,
        failed_case_count=len(results) - passed,
        ok=passed == len(results),
        limitations=[
            *manifest.limitations,
            (
                "Host fixture success validates declared contracts and deterministic math; "
                "it does not prove reference-image similarity or production asset quality."
            ),
            (
                "Optional Blender smoke validates materialization only and does not claim "
                "destination-engine parity, topology optimality, or quality improvement."
            ),
        ],
    )
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report
