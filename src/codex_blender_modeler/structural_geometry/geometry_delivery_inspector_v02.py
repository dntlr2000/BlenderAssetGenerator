"""Host-owned Blender inspection for optimized and clean-import AQ v2 geometry stages."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

from ..blender_artifacts import native_io_path, sha256_file
from ..blender_runner import run_blender
from ..production.validation import ensure_contained_production_path
from .geometry_survival_v02 import GeometryStageSnapshotV02

DeliveryGeometryStage = Literal[
    "compiled_candidate",
    "promoted_canonical",
    "optimized_lod0",
    "clean_import_glb",
    "clean_import_fbx",
]


def inspect_delivery_geometry_stage_v02(
    *,
    job_root: Path,
    artifact_relative_path: str,
    stage: DeliveryGeometryStage,
    output_relative_path: str,
    source_fingerprint_sha256: str,
    build_fingerprint_sha256: str,
    topology_profile: str = "static_prop_closed",
) -> GeometryStageSnapshotV02:
    """Inspect one immutable delivery artifact and atomically publish its strict snapshot."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    artifact = ensure_contained_production_path(
        root,
        root / artifact_relative_path,
        must_exist=True,
    )
    if not os.path.isfile(native_io_path(artifact)):
        raise FileNotFoundError(artifact)
    output = ensure_contained_production_path(
        root,
        root / output_relative_path,
        must_exist=False,
    )
    if os.path.exists(native_io_path(output)):
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output = ensure_contained_production_path(root, output, must_exist=False)
    staging = ensure_contained_production_path(
        root,
        output.with_name(f".{output.name}.{uuid4().hex}.tmp"),
        must_exist=False,
    )
    artifact_sha256 = sha256_file(artifact)
    arguments = [
        "--job-root",
        str(root),
        "--artifact",
        str(artifact),
        "--artifact-sha256",
        artifact_sha256,
        "--stage",
        stage,
        "--source-fingerprint-sha256",
        source_fingerprint_sha256,
        "--build-fingerprint-sha256",
        build_fingerprint_sha256,
        "--topology-profile",
        topology_profile,
        "--output",
        str(staging),
    ]
    try:
        run_blender(
            "inspect_geometry_delivery_v02.py",
            arguments,
            blend_file=(
                artifact
                if stage
                in {"compiled_candidate", "promoted_canonical", "optimized_lod0"}
                else None
            ),
            factory_startup=stage in {"clean_import_glb", "clean_import_fbx"},
            disable_autoexec=True,
        )
        snapshot = GeometryStageSnapshotV02.model_validate_json(
            Path(native_io_path(staging)).read_bytes()
        )
        expected_relative = artifact.relative_to(root).as_posix()
        if (
            snapshot.stage != stage
            or snapshot.artifact_path != expected_relative
            or snapshot.artifact_sha256 != artifact_sha256
            or snapshot.source_fingerprint_sha256 != source_fingerprint_sha256
            or snapshot.build_fingerprint_sha256 != build_fingerprint_sha256
            or snapshot.topology_profile != topology_profile
            or snapshot.semantic_id != "asset.aggregate"
        ):
            raise ValueError("delivery geometry snapshot does not match its host request")
        if sha256_file(artifact) != artifact_sha256:
            raise RuntimeError("delivery artifact changed during host inspection")
        os.replace(native_io_path(staging), native_io_path(output))
        return snapshot
    except Exception:
        if os.path.isfile(native_io_path(staging)):
            os.unlink(native_io_path(staging))
        raise
