"""Pure AQ v2 GeometryIntent classification without changing the v1 Blender runtime."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Literal

from .mesh_payload_v02 import (
    FaceGroupV02,
    FaceMaterialIntentV02,
    ModifierDispositionV02,
    SmoothingPolicyV02,
    SourceGeometryIntentV02,
    SubdivisionIntentV02,
    WeightedNormalIntentV02,
    canonical_json_sha256,
)
from .models import GeometryIntent

BuilderKindV02 = Literal[
    "loft",
    "sweep",
    "boolean_tree",
    "multi_loop_extrude",
    "geometry_nodes_template",
    "custom_mesh",
    "fixture",
]


def _disposition(
    effect: str,
    disposition: str,
    *,
    source_id: str,
    details: object,
) -> ModifierDispositionV02:
    """Construct one exact-hash-bound modifier disposition from normalized details."""

    return ModifierDispositionV02.model_validate(
        {
            "effect": effect,
            "disposition": disposition,
            "source_id": source_id,
            "details_sha256": canonical_json_sha256(details),
        }
    )


def classify_geometry_intent_v02(
    intent: GeometryIntent,
    *,
    builder_kind: BuilderKindV02,
    material_assignments: Iterable[FaceMaterialIntentV02] = (),
    legacy_modifier_kinds: Iterable[str] = (),
) -> tuple[SourceGeometryIntentV02, list[ModifierDispositionV02]]:
    """Normalize v0.1 intent and classify each effect once for opt-in v2 compilation."""

    legacy_kinds = list(legacy_modifier_kinds)
    if len(legacy_kinds) != len(set(legacy_kinds)):
        raise ValueError("legacy modifier list repeats one effect")
    if intent.smoothing_policy.mode == "legacy":
        raise ValueError("AQ v2 requires an explicit non-legacy smoothing policy")
    if intent.subdivision_intent.enabled and "subdivision" in legacy_kinds:
        raise ValueError("subdivision is duplicated by GeometryIntent and legacy modifiers")
    if builder_kind == "boolean_tree" and "boolean" in legacy_kinds:
        raise ValueError("Boolean evaluation is duplicated by builder and legacy modifiers")
    if builder_kind == "geometry_nodes_template" and "geometry_nodes" in legacy_kinds:
        raise ValueError("Geometry Nodes evaluation is duplicated by builder and legacy modifiers")

    mode = intent.smoothing_policy.mode
    smoothing = SmoothingPolicyV02(
        mode=mode,
        angle_degrees=(
            intent.smoothing_policy.angle_degrees
            if mode == "smooth_by_angle"
            else None
        ),
        keep_explicit_sharp=intent.smoothing_policy.keep_sharp,
    )
    weighted_normal = WeightedNormalIntentV02(
        enabled=mode == "weighted_normals",
        keep_sharp=intent.smoothing_policy.keep_sharp,
        weight_mode="FACE_AREA_WITH_ANGLE",
        disposition=(
            "recreate_in_compiled_build" if mode == "weighted_normals" else "reject"
        ),
    )
    subdivision = SubdivisionIntentV02(
        enabled=intent.subdivision_intent.enabled,
        levels=intent.subdivision_intent.levels,
        render_levels=intent.subdivision_intent.levels,
        subdivision_type="CATMULL_CLARK",
        boundary_smoothing=(
            "PRESERVE_CORNERS"
            if intent.subdivision_intent.boundary_smoothing == "preserve_corners"
            else "ALL"
        ),
        disposition=(
            "recreate_in_compiled_build"
            if intent.subdivision_intent.enabled
            else "reject"
        ),
    )
    normalized_without_hash = {
        "face_groups": [
            FaceGroupV02.model_validate(item.model_dump(mode="json")).model_dump(mode="json")
            for item in intent.face_groups
        ],
        "material_assignments": [
            item.model_dump(mode="json") for item in material_assignments
        ],
        "sharp_edges": [item.model_dump(mode="json") for item in intent.sharp_edges],
        "uv_seams": [item.model_dump(mode="json") for item in intent.uv_seams],
        "edge_creases": [
            item.model_dump(mode="json") for item in intent.crease_edges
        ],
        "bevel_weights": [
            item.model_dump(mode="json") for item in intent.bevel_weights
        ],
        "smoothing_policy": smoothing.model_dump(mode="json"),
        "topology_profile": intent.topology_policy,
        "weighted_normal_intent": weighted_normal.model_dump(mode="json"),
        "subdivision_intent": subdivision.model_dump(mode="json"),
    }
    source = SourceGeometryIntentV02.model_validate_json(
        json.dumps(
            {
                "source_intent_sha256": canonical_json_sha256(normalized_without_hash),
                **normalized_without_hash,
            }
        )
    )

    policy: list[ModifierDispositionV02] = []
    if builder_kind == "boolean_tree":
        policy.append(
            _disposition(
                "boolean",
                "bake_into_mesh",
                source_id="builder.boolean_tree",
                details={"builder_kind": builder_kind},
            )
        )
    if builder_kind == "geometry_nodes_template":
        policy.append(
            _disposition(
                "geometry_nodes",
                "bake_into_mesh",
                source_id="builder.geometry_nodes_template",
                details={"builder_kind": builder_kind},
            )
        )
    if weighted_normal.enabled:
        policy.append(
            _disposition(
                "weighted_normal",
                "recreate_in_compiled_build",
                source_id="intent.smoothing_policy",
                details=weighted_normal.model_dump(mode="json"),
            )
        )
    if subdivision.enabled:
        policy.append(
            _disposition(
                "subdivision",
                "recreate_in_compiled_build",
                source_id="intent.subdivision_intent",
                details=subdivision.model_dump(mode="json"),
            )
        )
    baked_legacy = {
        "bevel",
        "mirror",
        "solidify",
        "array",
        "decimate",
        "remesh",
        "boolean",
        "normal_transfer",
    }
    for kind in legacy_kinds:
        if kind in baked_legacy:
            policy.append(
                _disposition(
                    kind,
                    "bake_into_mesh",
                    source_id=f"legacy_modifier.{kind}",
                    details={"kind": kind, "parameter_contract": "caller_hash_required"},
                )
            )
        else:
            policy.append(
                _disposition(
                    "unsupported",
                    "reject",
                    source_id=f"legacy_modifier.{kind}",
                    details={"kind": kind, "reason": "unsupported_v02_effect"},
                )
            )
    return source, policy
