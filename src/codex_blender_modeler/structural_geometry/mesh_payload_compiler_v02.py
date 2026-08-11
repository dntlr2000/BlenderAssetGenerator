"""Host integration hook for isolated MeshPayload 0.2 Blender compilation."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..blender_runner import run_blender
from .geometry_survival_v02 import GeometryStageSnapshotV02
from .mesh_payload_io_v02 import (
    file_sha256,
    load_mesh_payload_v02,
    verify_mesh_payload_v02_source_hashes,
)
from .mesh_payload_v02 import (
    JobRelativePath,
    MeshPayloadV02StrictModel,
    Sha256,
    canonical_json_sha256,
)


class MeshPayloadV02CompileReport(MeshPayloadV02StrictModel):
    """Validate the fixed Blender compiler's output and exact source binding."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    status: Literal["passed"]
    payload_path: JobRelativePath
    payload_file_sha256: Sha256
    snapshot: GeometryStageSnapshotV02


def _resolve_job_path(job_root: Path, relative_path: str) -> Path:
    """Resolve one normalized job-relative compiler path and reject escape."""

    if not relative_path or "\\" in relative_path or Path(relative_path).is_absolute():
        raise ValueError("compiler paths must be normalized job-relative paths")
    if any(part in {"", ".", ".."} for part in relative_path.split("/")):
        raise ValueError("compiler path contains an unsafe segment")
    root = job_root.resolve()
    path = (root / Path(*relative_path.split("/"))).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("compiler path escapes job root") from exc
    return path


def compile_mesh_payload_v02(
    *,
    job_root: Path,
    payload_relative_path: str,
    output_blend_relative_path: str,
    report_relative_path: str,
) -> MeshPayloadV02CompileReport:
    """Validate and compile one opt-in v2 payload without touching any v1 path."""

    payload_path = _resolve_job_path(job_root, payload_relative_path)
    output_blend = _resolve_job_path(job_root, output_blend_relative_path)
    report_path = _resolve_job_path(job_root, report_relative_path)
    if not payload_path.is_file():
        raise FileNotFoundError(payload_path)
    for output in (output_blend, report_path):
        if output.exists():
            raise FileExistsError(output)
        output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_mesh_payload_v02(payload_path)
    payload.assert_compilable()
    verify_mesh_payload_v02_source_hashes(payload, job_root=job_root)
    payload_file_hash = file_sha256(payload_path)
    run_blender(
        "compile_mesh_payload_v02.py",
        [
            "--payload",
            str(payload_path),
            "--job-root",
            str(job_root.resolve()),
            "--output-blend",
            str(output_blend),
            "--report",
            str(report_path),
            "--payload-sha256",
            payload_file_hash,
        ],
        factory_startup=True,
        disable_autoexec=True,
    )
    report = MeshPayloadV02CompileReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    if report.payload_path != payload_relative_path:
        raise RuntimeError("Blender compiler report changed the payload path")
    if report.payload_file_sha256 != payload_file_hash:
        raise RuntimeError("Blender compiler report changed the payload hash")
    snapshot = report.snapshot
    if snapshot.stage != "compiled_candidate":
        raise RuntimeError("Blender compiler emitted an unexpected survival stage")
    if snapshot.artifact_path != output_blend_relative_path:
        raise RuntimeError("Blender compiler report changed the output blend path")
    if snapshot.artifact_sha256 != file_sha256(output_blend):
        raise RuntimeError("compiled blend hash differs from stage snapshot")
    if snapshot.semantic_id != payload.semantic_id:
        raise RuntimeError("compiled blend changed the payload semantic ID")
    if snapshot.source_fingerprint_sha256 != payload.source_fingerprint_sha256:
        raise RuntimeError("compiled blend changed the source fingerprint")
    if snapshot.build_fingerprint_sha256 != canonical_json_sha256(payload):
        raise RuntimeError("compiled build fingerprint differs from exact payload")
    return report
