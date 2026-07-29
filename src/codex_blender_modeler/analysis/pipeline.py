from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..reference_scope import reference_content_scope_from_metadata
from ..workspace import find_input_images, job_dir, load_job, metadata_path, resolve_metadata_path
from .basic import analyze_image
from .camera import solve_camera
from .models import CameraSolution, ModelingPlan, ReferenceAnalysis


def _source_records(metadata: dict) -> list[dict]:
    image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    return [
        record
        for record in metadata.get("sources", [])
        if Path(record["path"]).suffix.lower() in image_extensions
    ]


def _reference_type(kinds: set[str]) -> str:
    if "blueprint" in kinds:
        return "blueprint_set"
    orthographic = {"front", "right", "top"}
    if len(kinds & orthographic) >= 2:
        return "orthographic_set"
    if kinds == {"reference"}:
        return "perspective_reference"
    if kinds & orthographic:
        return "mixed"
    return "unknown"


def _projection_recommendation(kinds: set[str], provider: str, images) -> tuple[str, float]:
    if len(kinds & {"front", "right", "top"}) >= 1 or "blueprint" in kinds:
        return "ORTHO", 0.9
    if provider == "opencv" and any(image.line_angle_clusters for image in images):
        return "PERSP", 0.62
    return "UNKNOWN", 0.25


def analyze_job_reference(
    job_id: str,
    *,
    provider: Literal["auto", "basic", "opencv"] = "auto",
    projection_hint: Literal["auto", "persp", "ortho"] = "auto",
    focal_length_mm: float | None = None,
    azimuth_deg: float | None = None,
    elevation_deg: float | None = None,
) -> dict[str, str]:
    """Create deterministic diagnostics plus a scope-aware modeling-plan scaffold."""

    root = job_dir(job_id)
    metadata = load_job(job_id)
    reference_content_scope, target_subject = reference_content_scope_from_metadata(
        metadata
    )
    diagnostics = root / "analysis" / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)

    selected_provider = provider
    if provider in {"auto", "opencv"}:
        try:
            import cv2  # noqa: F401
            import numpy  # noqa: F401
        except ImportError:
            if provider == "opencv":
                raise RuntimeError(
                    "OpenCV provider requested but vision dependencies are missing. "
                    "Run: uv sync --extra vision"
                ) from None
            selected_provider = "basic"
        else:
            selected_provider = "opencv"
    if selected_provider == "auto":
        selected_provider = "basic"

    records = _source_records(metadata)
    if not records:
        # Compatibility fallback for v0.2 jobs with incomplete metadata.
        records = [
            {"kind": path.stem, "path": metadata_path(path)} for path in find_input_images(job_id)
        ]

    images = []
    for record in records:
        source_id = str(record["kind"])
        path = resolve_metadata_path(str(record["path"]))
        image_analysis = analyze_image(source_id, path, diagnostics)
        if selected_provider == "opencv":
            from .opencv_provider import enrich_with_line_analysis

            image_analysis = enrich_with_line_analysis(path, image_analysis)
        images.append(image_analysis)

    kinds = {record["kind"] for record in records}
    recommended, confidence = _projection_recommendation(kinds, selected_provider, images)
    anchors = metadata.get("scale_anchors", [])
    if not anchors:
        scale_status = "unscaled"
    elif len(anchors) == 1:
        scale_status = "anchored"
    else:
        scale_status = "multi_anchor"
    assumptions = [
        "Image analysis is diagnostic and does not establish exact 3D dimensions by itself.",
        (
            "Content masks and projection hints are heuristic unless explicit blueprints "
            "or anchors exist."
        ),
    ]
    warnings = []
    if selected_provider == "basic":
        warnings.append(
            "OpenCV line analysis was not used; install the vision extra for "
            "line-angle diagnostics."
        )
    analysis = ReferenceAnalysis(
        job_id=job_id,
        provider=selected_provider,
        images=images,
        recommended_projection=recommended,
        projection_confidence=confidence,
        reference_type=_reference_type(kinds),
        scale_status=scale_status,
        assumptions=assumptions,
        warnings=warnings,
    )
    camera = solve_camera(
        analysis,
        projection_hint=projection_hint,
        focal_length_mm=focal_length_mm,
        azimuth_deg=azimuth_deg,
        elevation_deg=elevation_deg,
    )

    analysis_path = root / "analysis" / "reference_analysis.json"
    camera_path = root / "analysis" / "camera_solution.json"
    plan_path = root / "analysis" / "modeling_plan.json"
    analysis_path.write_text(analysis.model_dump_json(indent=2) + "\n", encoding="utf-8")
    camera_path.write_text(camera.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if not plan_path.exists():
        scope_note = (
            "Model only the explicitly selected primary subject "
            f"{target_subject!r} and its structurally attached/supporting components; "
            "exclude independent terrain, ground, vegetation, rocks, props, backdrop, "
            "and atmospheric context."
            if reference_content_scope == "primary_object_only"
            else "Model the relevant visible reference scene, including selected context."
        )
        plan = ModelingPlan(
            job_id=job_id,
            reference_analysis_path=metadata_path(analysis_path),
            camera_solution_path=metadata_path(camera_path),
            global_notes=[
                (
                    "This scaffold is intentionally empty; Codex should populate semantic "
                    "objects before SceneSpec authoring."
                ),
                (
                    f"Immutable reference_content_scope={reference_content_scope}; "
                    f"target_subject={target_subject!r}."
                ),
                scope_note,
            ],
        )
        plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return {
        "reference_analysis": str(analysis_path),
        "camera_solution": str(camera_path),
        "modeling_plan": str(plan_path),
        "provider": selected_provider,
    }


def load_reference_analysis(path_or_job: str | Path) -> ReferenceAnalysis:
    path = Path(path_or_job)
    if not path.is_file():
        path = job_dir(str(path_or_job)) / "analysis" / "reference_analysis.json"
    return ReferenceAnalysis.model_validate_json(path.read_text(encoding="utf-8"))


def load_camera_solution(path_or_job: str | Path) -> CameraSolution:
    """Load and validate a camera solution from a path or workspace job ID."""

    path = Path(path_or_job)
    if not path.is_file():
        path = job_dir(str(path_or_job)) / "analysis" / "camera_solution.json"
    return CameraSolution.model_validate_json(path.read_text(encoding="utf-8"))


def load_modeling_plan(path_or_job: str | Path) -> ModelingPlan:
    """Load and validate a semantic modeling plan from a path or workspace job ID."""

    path = Path(path_or_job)
    if not path.is_file():
        path = job_dir(str(path_or_job)) / "analysis" / "modeling_plan.json"
    return ModelingPlan.model_validate_json(path.read_text(encoding="utf-8"))
