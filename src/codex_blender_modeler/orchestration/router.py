"""Deterministic, fail-closed intent and destination routing for V0.8."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from .models import (
    DestinationRequest,
    DestinationResolution,
    IntentRouting,
    WorkflowIntent,
)

_TERMS: dict[WorkflowIntent, tuple[str, ...]] = {
    "add_measured_view": (
        "정면도",
        "측면도",
        "평면도",
        "청사진",
        "추가 뷰",
        "front view",
        "side view",
        "top view",
        "blueprint",
        "add view",
    ),
    "interior_scope": (
        "실내",
        "내부 공간",
        "방을",
        "복도",
        "interior",
        "room",
        "corridor",
        "furnishing",
    ),
    "material_authoring": (
        "재질",
        "텍스처",
        "셰이더",
        "머티리얼",
        "material",
        "texture",
        "shader",
        "pbr",
    ),
    "visual_qa": (
        "유사도",
        "외형 개선",
        "레퍼런스 비교",
        "시각 qa",
        "visual qa",
        "similarity",
        "silhouette",
        "compare render",
    ),
    "portable_package": (
        "내보내",
        "패키지",
        "최적화",
        "콜라이더",
        "export",
        "package",
        "optimize",
        "collider",
        "lod",
        "fbx",
        "glb",
        "gltf",
        "obj",
    ),
    "revise_asset": (
        "수정",
        "바꿔",
        "변경",
        "높여",
        "낮춰",
        "이동",
        "늘려",
        "줄여",
        "revise",
        "adjust",
        "change",
        "move",
        "resize",
    ),
    "new_asset": (
        "만들어",
        "모델링",
        "생성",
        "create",
        "model",
        "build asset",
    ),
}


def _matched_terms(request_text: str) -> dict[WorkflowIntent, list[str]]:
    """Collect case-insensitive routing terms without using a generative classifier."""

    normalized = request_text.casefold()
    return {
        intent: [term for term in terms if term.casefold() in normalized]
        for intent, terms in _TERMS.items()
    }


def resolve_destination(
    request_text: str,
    explicit: DestinationRequest,
) -> DestinationResolution:
    """Resolve only an explicit engine mention and stop unsupported targets at V0.7."""

    request = explicit
    normalized = request_text.casefold()
    if request.kind == "unspecified":
        if re.search(r"(?<![a-z0-9_])unity(?![a-z0-9_])", normalized):
            request = DestinationRequest(kind="unity")
        elif re.search(
            r"(?<![a-z0-9_])unreal(?:\s+engine)?(?![a-z0-9_])",
            normalized,
        ):
            request = DestinationRequest(kind="unreal")
    if request.kind == "engine_neutral":
        return DestinationResolution(
            requested=request,
            status="available",
            adapter_id="portable_static_asset_v07",
            reason="The V0.7 engine-neutral static-asset package adapter is available.",
        )
    if request.kind in {"unity", "unreal", "custom"}:
        label = request.name if request.kind == "custom" else request.kind
        return DestinationResolution(
            requested=request,
            status="unsupported",
            reason=(
                f"No validated {label} destination adapter is installed. The workflow will "
                "stop at the immutable V0.7 engine-neutral portable package."
            ),
        )
    return DestinationResolution(
        requested=request,
        status="not_requested",
        reason=(
            "No destination engine was explicitly selected; the workflow remains "
            "engine-neutral and stops at a portable package."
        ),
    )


def route_intent(
    *,
    workflow_id: str,
    job_id: str,
    request_text: str,
    intent_hint: str,
    new_job: bool,
    has_staged_view: bool,
    destination: DestinationRequest,
) -> IntentRouting:
    """Route one short request deterministically or reject ambiguous existing-job work."""

    matches = _matched_terms(request_text)
    matched_flat: list[str] = []
    reasons: list[str] = []
    requires_clarification = False
    if intent_hint != "auto":
        intent = intent_hint
        confidence = 1.0
        reasons.append(f"Caller explicitly selected intent={intent_hint}.")
    elif new_job:
        intent = "new_asset"
        confidence = 1.0
        reasons.append("A new immutable reference and unused job ID require new_asset routing.")
    elif has_staged_view:
        intent = "add_measured_view"
        confidence = 1.0
        reasons.append("An explicit auxiliary view kind requires add_measured_view routing.")
    else:
        active = [
            candidate
            for candidate in (
                "interior_scope",
                "portable_package",
                "material_authoring",
                "visual_qa",
                "revise_asset",
            )
            if matches[candidate]
        ]
        if len(active) == 1:
            intent = active[0]
            confidence = 0.9
            matched_flat = matches[intent]
            reasons.append(
                f"Existing-job request matched only the {intent} vocabulary."
            )
        elif len(active) > 1:
            raise ValueError(
                "Short request matches multiple existing-job intents; select --intent "
                f"explicitly: {active}"
            )
        else:
            requires_clarification = True
            raise ValueError(
                "Existing-job request is ambiguous. Explicitly select revision, add_view, "
                "interior, material, QA, or portable-package intent."
            )
    if not matched_flat:
        matched_flat = matches.get(intent, [])
    resolution = resolve_destination(request_text, destination)
    if resolution.status == "unsupported":
        reasons.append(resolution.reason)
    return IntentRouting(
        workflow_id=workflow_id,
        job_id=job_id,
        intent=intent,  # type: ignore[arg-type]
        confidence=confidence,
        reasons=reasons,
        matched_terms=sorted(set(matched_flat)),
        requires_clarification=requires_clarification,
        destination=resolution,
        routed_at=datetime.now(UTC),
    )


def destination_adapters() -> dict[str, object]:
    """Expose installed adapter capabilities without implying runtime parity."""

    return {
        "schema_version": "0.8.0",
        "adapters": [
            {
                "adapter_id": "portable_static_asset_v07",
                "destination": "engine_neutral",
                "status": "available",
                "formats": ["glb", "fbx", "obj"],
                "capabilities": [
                    "static_mesh",
                    "raw_pbr_channels",
                    "derived_lod",
                    "derived_collision",
                    "clean_import_roundtrip_in_blender",
                ],
                "limitations": [
                    "No engine prefab or actor reconstruction",
                    "No runtime shader conversion",
                    "No engine-side LOD switching or physics-cost validation",
                ],
            },
            {
                "adapter_id": None,
                "destination": "unity",
                "status": "unsupported",
                "fallback": "portable_static_asset_v07",
            },
            {
                "adapter_id": None,
                "destination": "unreal",
                "status": "unsupported",
                "fallback": "portable_static_asset_v07",
            },
            {
                "adapter_id": None,
                "destination": "custom",
                "status": "unsupported",
                "fallback": "portable_static_asset_v07",
            },
        ],
    }
