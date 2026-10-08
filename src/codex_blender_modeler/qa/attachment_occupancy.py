"""Bind exact V0.3 source regions to a complete source-camera projection of actual meshes."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from ..analysis.models import ModelingPlan
from ..attachment_runtime import artifact_bytes
from ..build_provenance import camera_contract_fingerprint, canonical_json_sha256
from ..models import SceneSpec
from ..reference_fidelity.models import ReferenceMaskSeedEvidenceV03
from ..reference_scope import (
    subject_object_ids,
    validate_modeling_plan_content_scope,
    validate_scene_content_scope,
)
from ..structural_geometry.attachment_companion import AttachmentIntentV01
from .reference_mask import validate_explicit_reference_seeds
from .reference_mask_constraints import validate_reference_trimap
from .reference_occupancy import (
    MAX_PIXELS,
    compare_sure_trimap_occupancy,
    rasterize_orthographic_occupancy,
)
from .reference_subject_extent import validate_recorded_primary_reference


def _artifact(root: Path, path: Path) -> dict[str, str]:
    """Bind one finished diagnostic file without accepting an absolute package path."""
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _output_directory(root: Path, path: Path) -> None:
    """Create exactly one fresh contained diagnostic directory without following links."""
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        if part in {".", ".."}:
            raise ValueError("reference occupancy output contains traversal")
        current /= part
        if current.is_symlink():
            raise ValueError("reference occupancy output contains a link")
    path.resolve().relative_to(root.resolve())
    path.mkdir(parents=True, exist_ok=False)


def validate_reference_region_context(root: Path, intent: AttachmentIntentV01) -> dict[str, Any]:
    """Validate all selected source evidence and camera without claiming geometry coverage."""
    selected = intent.reference_region_evidence
    if selected is None:
        raise ValueError("reference context validation requires an explicit selection")
    scene_bytes = artifact_bytes(root, intent.source_scene.model_dump(mode="json"))
    plan_bytes = artifact_bytes(root, intent.source_modeling_plan.model_dump(mode="json"))
    reference_bytes = artifact_bytes(root, intent.source_reference.model_dump(mode="json"))
    spec = SceneSpec.model_validate_json(scene_bytes)
    plan = ModelingPlan.model_validate_json(plan_bytes)
    if spec.job_id != intent.job_id or plan.job_id != intent.job_id or plan.stage != "authored":
        raise ValueError("reference occupancy source job/ModelingPlan identity differs")
    metadata = json.loads((root / "job.json").read_bytes())
    if metadata.get("reference_content_scope") != "primary_object_only":
        raise ValueError("selected alpha-backed occupancy requires explicit primary-object scope")
    target = metadata.get("target_subject")
    validate_modeling_plan_content_scope(plan, scope="primary_object_only", target_subject=target)
    validate_scene_content_scope(spec, scope="primary_object_only", target_subject=target)
    subject_ids = subject_object_ids(spec)
    if not subject_ids or {obj.id for obj in plan.objects} != subject_ids:
        raise ValueError("reference occupancy SceneSpec/ModelingPlan subject membership differs")
    evidence = ReferenceMaskSeedEvidenceV03.model_validate_json(
        artifact_bytes(root, selected.model_dump(mode="json"))
    )
    if evidence.reference_resolution[0] * evidence.reference_resolution[1] > MAX_PIXELS:
        raise ValueError("reference occupancy source resolution exceeds the scoped pixel limit")
    if evidence.reference.model_dump(mode="json") != intent.source_reference.model_dump(
        mode="json"
    ):
        raise ValueError("selected reference regions bind a different original reference")
    for item in (evidence.reference, evidence.trimap, evidence.subject_extent):
        artifact_bytes(root, item.model_dump(mode="json"))
    reference_path = root / intent.source_reference.path
    validate_recorded_primary_reference(root, intent.job_id, evidence.reference)
    validate_explicit_reference_seeds(
        root, reference_path, spec, evidence, allowed_object_ids=subject_ids
    )
    trimap, trimap_bytes = validate_reference_trimap(
        root, reference_path, spec, evidence, allowed_object_ids=subject_ids
    )
    camera = spec.camera
    source_camera = json.loads(scene_bytes)["camera"]
    if (
        camera.projection != "ORTHO"
        or camera.location[0] != camera.target[0]
        or camera.location[2] != camera.target[2]
        or camera.location[1] >= camera.target[1]
        or camera.resolution != evidence.reference_resolution
        or source_camera.get("sensor_fit", "AUTO") != "AUTO"
        or source_camera.get("pixel_aspect_x", 1.0) != 1.0
        or source_camera.get("pixel_aspect_y", 1.0) != 1.0
    ):
        raise ValueError(
            "reference occupancy requires exact axis-aligned ORTHO/AUTO square-pixel camera"
        )
    with Image.open(BytesIO(reference_bytes)) as opened:
        if (
            opened.mode != "RGBA"
            or opened.size != trimap.size
            or getattr(opened, "n_frames", 1) != 1
        ):
            raise ValueError(
                "reference occupancy requires original single-frame RGBA at the source grid"
            )
        alpha = opened.getchannel("A").tobytes()
    labels = trimap.tobytes()
    if any(
        (label == 255 and value == 0) or (label == 0 and value != 0)
        for label, value in zip(labels, alpha, strict=True)
    ):
        raise ValueError("sure reference labels contradict original alpha support")
    return {
        "spec": spec,
        "evidence": evidence,
        "trimap": trimap,
        "trimap_bytes": trimap_bytes,
        "source_camera": source_camera,
        "subject_ids": subject_ids,
    }


def evaluate_reference_region_occupancy(
    root: Path,
    intent: AttachmentIntentV01,
    raw_geometry: dict[str, Any],
    *,
    output_dir: Path,
) -> dict[str, Any]:
    """Rehash independent source regions and compare every sure pixel at the exact source grid.

    The fixed extraction caller owns native attestation. This adapter records its
    exact geometry/request digest but never promotes arbitrary supplied JSON to
    native evidence. Camera projection is the frozen mathematical source-camera
    contract, not a claim of pixel equality with a native beauty render.
    """
    selected = intent.reference_region_evidence
    if selected is None:
        return {
            "status": "unverified",
            "selected": False,
            "reason": "no explicit reference-region evidence selected",
            "actual_geometry_origin_verified": False,
            "final_human_acceptance": False,
        }
    context = validate_reference_region_context(root, intent)
    spec, evidence, trimap = context["spec"], context["evidence"], context["trimap"]
    trimap_bytes, source_camera, subject_ids = (
        context["trimap_bytes"],
        context["source_camera"],
        context["subject_ids"],
    )
    camera = spec.camera
    records = raw_geometry.get("objects")
    if not isinstance(records, list) or not 1 <= len(records) <= 128:
        raise ValueError("reference occupancy requires complete bounded extracted mesh records")
    ids = [record.get("semantic_id") for record in records]
    if len(ids) != len(set(ids)) or set(ids) != subject_ids:
        raise ValueError(
            "reference occupancy actual subject membership is missing, extra or duplicated"
        )
    vertices, faces, indices = [], [], {}
    for record in records:
        triangles = record.get("triangles")
        if not isinstance(triangles, list) or not triangles:
            raise ValueError("reference occupancy extracted semantic has no triangles")
        for triangle in triangles:
            corners = triangle.get("corners")
            if not isinstance(corners, list) or len(corners) != 3:
                raise ValueError("reference occupancy requires actual oriented triangle corners")
            face = []
            for point in corners:
                if not isinstance(point, (list, tuple)) or len(point) != 3:
                    raise ValueError("reference occupancy triangle corner is malformed")
                key = tuple(point)
                if key not in indices:
                    indices[key] = len(vertices)
                    vertices.append(key)
                face.append(indices[key])
            faces.append(face)
            if len(faces) > 25000 or len(vertices) > 65536:
                raise ValueError("reference occupancy actual geometry exceeds the scoped limit")
    projection, raster = rasterize_orthographic_occupancy(
        vertices,
        faces,
        resolution=evidence.reference_resolution,
        ortho_scale=camera.ortho_scale,
        center_x=camera.target[0],
        center_z=camera.target[2],
    )
    comparison = compare_sure_trimap_occupancy(trimap, projection)
    _output_directory(root, output_dir)
    projection_path = output_dir / "projection.png"
    trimap_path = output_dir / "reference_trimap.png"
    projection.save(projection_path, format="PNG")
    trimap_path.write_bytes(trimap_bytes)
    report = {
        **comparison,
        "selected": True,
        "raster": raster,
        "source_camera_fingerprint": camera_contract_fingerprint(source_camera),
        ("projection_camera"): (
            "frozen source-camera grid; native beauty-render equality is unverified"
        ),
        "source_scene": intent.source_scene.model_dump(mode="json"),
        "source_modeling_plan": intent.source_modeling_plan.model_dump(mode="json"),
        "source_reference": intent.source_reference.model_dump(mode="json"),
        "reference_region_evidence": selected.model_dump(mode="json"),
        "trimap": evidence.trimap.model_dump(mode="json"),
        "subject_extent": evidence.subject_extent.model_dump(mode="json"),
        "actual_geometry_sha256": canonical_json_sha256(raw_geometry),
        "extraction_request": {
            key: raw_geometry.get(key)
            for key in (
                "stage",
                "artifact",
                "source_fingerprint",
                "build_fingerprint",
                "intent_sha256",
            )
        },
        "subject_ids": sorted(subject_ids),
        "original_alpha_labels_verified": True,
        "source_artifacts_verified": True,
        "projection": _artifact(root, projection_path),
        "trimap_snapshot": _artifact(root, trimap_path),
        "actual_geometry_origin_verified": False,
        "final_human_acceptance": False,
    }
    path = output_dir / "report.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return report
