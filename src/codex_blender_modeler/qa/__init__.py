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
from .multiview_sanity import (
    ASSEMBLY_SANITY_PASS_KINDS,
    ASSEMBLY_SANITY_VIEW_IDS,
    AssemblySanityFinding,
    AssemblySanityPassRecord,
    AssemblySanityPlan,
    AssemblySanityReferenceSource,
    AssemblySanityRenderManifest,
    AssemblySanityReport,
    AssemblySanityViewCoverage,
    AssemblySanityViewPlan,
    AssemblySanityViewRender,
    plan_job_assembly_multiview_sanity,
    run_job_assembly_multiview_sanity,
)
from .reporting import merge_advisory_target_result
from .request import create_visual_qa_request, validate_visual_qa_request
from .semantic_mask_registry import (
    get_job_semantic_reference_mask_status,
    register_job_semantic_reference_masks,
)
from .semantic_mask_registry_models import (
    RegisteredSemanticMaskArtifact,
    SemanticReferenceMaskPromotionReceipt,
    SemanticReferenceMaskRegistryStatus,
)
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


def run_job_visual_diagnostics(
    job_id: str,
    qa_run_id: str,
    *,
    diagnostic_id: str = "camera-geometry-v1",
    max_camera_probes: int = 12,
    include_multiview_sanity: bool = True,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict[str, Any]:
    """Run bounded companion diagnostics lazily without changing canonical V0.6 QA."""

    from .diagnostic_service import run_job_visual_diagnostics as run_service

    return run_service(
        job_id,
        qa_run_id,
        diagnostic_id=diagnostic_id,
        max_camera_probes=max_camera_probes,
        include_multiview_sanity=include_multiview_sanity,
        render_engine=render_engine,
        render_device=render_device,
    )

__all__ = [
    "ASSEMBLY_SANITY_PASS_KINDS",
    "ASSEMBLY_SANITY_VIEW_IDS",
    "AssemblySanityFinding",
    "AssemblySanityPassRecord",
    "AssemblySanityPlan",
    "AssemblySanityReferenceSource",
    "AssemblySanityRenderManifest",
    "AssemblySanityReport",
    "AssemblySanityViewCoverage",
    "AssemblySanityViewPlan",
    "AssemblySanityViewRender",
    "BoundingBoxMetric",
    "DirectVisualMetrics",
    "ExistingFileQATargetProvider",
    "GeneratedTarget",
    "QAFinding",
    "QATargetManifest",
    "QATargetProvider",
    "RenderPassManifest",
    "RegisteredSemanticMaskArtifact",
    "SemanticReferenceMaskPromotionReceipt",
    "SemanticReferenceMaskRegistryStatus",
    "SurfaceDetailQASummary",
    "VisualQAReport",
    "VisualQARequest",
    "camera_fingerprint",
    "compare_preview_to_generated_target",
    "compare_reference_to_render",
    "create_visual_qa_request",
    "generate_optional_qa_target",
    "get_job_semantic_reference_mask_status",
    "merge_advisory_target_result",
    "observed_regions_from_scene_spec",
    "plan_job_assembly_multiview_sanity",
    "require_camera_fingerprint",
    "register_job_semantic_reference_masks",
    "run_job_assembly_multiview_sanity",
    "run_job_visual_diagnostics",
    "run_job_visual_qa",
    "validate_visual_qa_request",
]
