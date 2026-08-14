"""Pure fail-closed surface-detail and UV compatibility checks."""

from __future__ import annotations

from .models import (
    MaterialClosureIssue,
    MaterialClosureSourceBindingArtifact,
    MaterialPromotionPreflightRequest,
    SurfaceDetailMaterialBinding,
    SurfaceDetailPreflightResult,
    SurfaceDetailRequirement,
)


def validate_preflight_uv_source_binding(
    request: MaterialPromotionPreflightRequest,
    source_binding: MaterialClosureSourceBindingArtifact,
) -> None:
    """Require preflight to use the exact UV fingerprint sealed into closure roots."""

    if request.uv_layout_fingerprint != source_binding.uv_layout_fingerprint:
        raise ValueError("preflight UV fingerprint differs from closure source binding")


def validate_surface_detail_bindings(
    requirements: list[SurfaceDetailRequirement],
    bindings: list[SurfaceDetailMaterialBinding],
) -> SurfaceDetailPreflightResult:
    """Validate every localized detail against one exact candidate material mapping."""

    issues: list[MaterialClosureIssue] = []
    by_id: dict[str, SurfaceDetailMaterialBinding] = {}
    duplicate_ids: set[str] = set()
    for binding in bindings:
        if binding.detail_id in by_id:
            duplicate_ids.add(binding.detail_id)
        else:
            by_id[binding.detail_id] = binding
    for detail_id in sorted(duplicate_ids):
        issues.append(
            MaterialClosureIssue(
                code="DUPLICATE_SURFACE_DETAIL_BINDING",
                message=f"surface detail has multiple material bindings: {detail_id}",
            )
        )
    requirement_ids = [item.detail_id for item in requirements]
    if len(requirement_ids) != len(set(requirement_ids)):
        issues.append(
            MaterialClosureIssue(
                code="DUPLICATE_SURFACE_DETAIL_REQUIREMENT",
                message="surface-detail requirement IDs must be unique",
            )
        )
    for requirement in sorted(requirements, key=lambda item: item.detail_id):
        binding = by_id.get(requirement.detail_id)
        if binding is None:
            issues.append(
                MaterialClosureIssue(
                    code="MISSING_SURFACE_DETAIL_BINDING",
                    message=f"surface detail lacks a candidate binding: {requirement.detail_id}",
                )
            )
            continue
        if binding.object_id != requirement.object_id:
            issues.append(
                MaterialClosureIssue(
                    code="SURFACE_DETAIL_OBJECT_MISMATCH",
                    message=f"surface detail object differs: {requirement.detail_id}",
                )
            )
        if binding.material_id != requirement.material_id:
            issues.append(
                MaterialClosureIssue(
                    code="SURFACE_DETAIL_MATERIAL_MISMATCH",
                    message=f"surface detail material differs: {requirement.detail_id}",
                )
            )
        if binding.strategy not in {"image", "hybrid"}:
            issues.append(
                MaterialClosureIssue(
                    code="SURFACE_DETAIL_IMAGE_STRATEGY_REQUIRED",
                    message=f"localized detail requires image or hybrid: {requirement.detail_id}",
                )
            )
        if binding.mapping != "uv" or binding.uv_set != requirement.uv_set:
            issues.append(
                MaterialClosureIssue(
                    code="SURFACE_DETAIL_UV_MAPPING_MISMATCH",
                    message=f"surface detail UV set differs: {requirement.detail_id}",
                )
            )
        if binding.uv_layout_fingerprint != requirement.uv_layout_fingerprint:
            issues.append(
                MaterialClosureIssue(
                    code="SURFACE_DETAIL_UV_FINGERPRINT_MISMATCH",
                    message=f"surface detail UV fingerprint is stale: {requirement.detail_id}",
                )
            )
        missing_channels = sorted(
            set(requirement.requested_channels) - set(binding.available_channels)
        )
        if missing_channels:
            issues.append(
                MaterialClosureIssue(
                    code="SURFACE_DETAIL_CHANNEL_MISSING",
                    message=(
                        f"surface detail channels are absent for {requirement.detail_id}: "
                        f"{missing_channels}"
                    ),
                )
            )
        if requirement.coverage_id not in binding.coverage_ids:
            issues.append(
                MaterialClosureIssue(
                    code="SURFACE_DETAIL_COVERAGE_MISSING",
                    message=f"surface detail coverage is absent: {requirement.detail_id}",
                )
            )
        if requirement.mask is not None and requirement.mask.path not in binding.mask_paths:
            issues.append(
                MaterialClosureIssue(
                    code="SURFACE_DETAIL_MASK_MISSING",
                    message=f"surface detail mask is absent: {requirement.detail_id}",
                    path=requirement.mask.path,
                )
            )
        if binding.detail_owned_by_geometry:
            issues.append(
                MaterialClosureIssue(
                    code="DUPLICATE_DETAIL_OWNERSHIP",
                    message=(
                        f"surface detail is also owned by geometry: {requirement.detail_id}"
                    ),
                )
            )
    ordered = sorted(
        issues,
        key=lambda item: (item.code, item.path or "", item.message),
    )
    return SurfaceDetailPreflightResult(
        status="failed" if ordered else "passed",
        checked_detail_ids=sorted(set(requirement_ids)),
        issues=ordered,
    )


__all__ = [
    "validate_preflight_uv_source_binding",
    "validate_surface_detail_bindings",
]
