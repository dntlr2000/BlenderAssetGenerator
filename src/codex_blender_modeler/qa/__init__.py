from typing import Any

from .advisory_compare import compare_preview_to_generated_target
from .camera_fingerprint import camera_fingerprint, require_camera_fingerprint
from .direct_compare import compare_reference_to_render, observed_regions_from_scene_spec
from .models import (
    BoundingBoxMetric,
    DirectVisualMetrics,
    QAFinding,
    QATargetManifest,
    RenderPassManifest,
    SurfaceDetailQASummary,
    VisualQAReport,
    VisualQARequest,
)
from .reporting import merge_advisory_target_result
from .request import create_visual_qa_request, validate_visual_qa_request
from .target_provider import (
    ExistingFileQATargetProvider,
    GeneratedTarget,
    QATargetProvider,
    generate_optional_qa_target,
)


def run_job_visual_qa(
    job_id: str,
    *,
    render_engine: str = "eevee",
    render_device: str = "auto",
    run_id: str | None = None,
    include_generated_target: bool = False,
    provider: QATargetProvider | None = None,
    target_prompt: str | None = None,
) -> dict[str, Any]:
    """Load and run the visual QA service lazily to avoid package import cycles."""

    from .service import run_job_visual_qa as run_service

    return run_service(
        job_id,
        render_engine=render_engine,
        render_device=render_device,
        run_id=run_id,
        include_generated_target=include_generated_target,
        provider=provider,
        target_prompt=target_prompt,
    )

__all__ = [
    "BoundingBoxMetric",
    "DirectVisualMetrics",
    "ExistingFileQATargetProvider",
    "GeneratedTarget",
    "QAFinding",
    "QATargetManifest",
    "QATargetProvider",
    "RenderPassManifest",
    "SurfaceDetailQASummary",
    "VisualQAReport",
    "VisualQARequest",
    "camera_fingerprint",
    "compare_preview_to_generated_target",
    "compare_reference_to_render",
    "create_visual_qa_request",
    "generate_optional_qa_target",
    "merge_advisory_target_result",
    "observed_regions_from_scene_spec",
    "require_camera_fingerprint",
    "run_job_visual_qa",
    "validate_visual_qa_request",
]
