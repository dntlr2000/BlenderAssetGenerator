"""Focused tests for the whitelist-only MaterialGraphSpec 0.1.0 contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from codex_blender_modeler.material_graph import (
    ChannelBinding,
    CurvatureMask,
    ImageMask,
    MaterialGraphArtifact,
    MaterialGraphLayer,
    MaterialGraphProvenance,
    MaterialGraphSpec,
    PositionSlopeMask,
    PreviewLightingPolicy,
    SemanticObjectMask,
    VertexAttributeMask,
)
from codex_blender_modeler.material_graph.models import TextureScale

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _artifact(role: str, path: str, sha256: str = SHA_A) -> MaterialGraphArtifact:
    """Build one valid graph artifact for focused contract tests."""

    return MaterialGraphArtifact(role=role, path=path, sha256=sha256)


def _provenance() -> MaterialGraphProvenance:
    """Build valid exact input provenance for one material graph."""

    return MaterialGraphProvenance(
        job_id="prop_a",
        workflow_id="workflow-a",
        dispatch_id="dispatch-a",
        project_version="0.9.0",
        inputs=[
            _artifact("material_plan", "analysis/material_plan.json", SHA_A),
            _artifact("scene_spec", "analysis/scene_spec.json", SHA_B),
        ],
    )


def _lighting() -> PreviewLightingPolicy:
    """Build the required neutral/reference-separated lighting policy."""

    return PreviewLightingPolicy(
        reference_source=_artifact("reference", "input/reference.png", SHA_C),
        reference_confidence=0.8,
    )


def _base_channel() -> ChannelBinding:
    """Build a portable constant base-color channel."""

    return ChannelBinding(
        channel="base_color",
        source_kind="constant",
        color_space="sRGB",
        constant=(0.3, 0.4, 0.5, 1.0),
    )


def _layer(mask: object, order: int = 0) -> MaterialGraphLayer:
    """Build one image-channel layer with the supplied whitelist mask."""

    return MaterialGraphLayer(
        layer_id=f"layer-{order}",
        order=order,
        material_id="mat.body",
        blend_mode="mix",
        channels=[
            ChannelBinding(
                channel="roughness",
                source_kind="image",
                color_space="Non-Color",
                image=_artifact("texture", f"textures/r{order}.png", SHA_B),
                physical_scale=TextureScale(width_m=0.25, height_m=0.25),
                sampling="clamp",
                localized_detail=True,
            )
        ],
        mask=mask,
    )


@pytest.mark.parametrize(
    "mask",
    [
        ImageMask(image=_artifact("mask", "textures/mask.png", SHA_C)),
        VertexAttributeMask(attribute="wear_weight"),
        SemanticObjectMask(semantic_ids=["prop.body"]),
        CurvatureMask(radius_m=0.01, low=0.2, high=0.8),
        PositionSlopeMask(
            mode="position", axis="Z", minimum=0.0, maximum=1.0, unit="meters"
        ),
    ],
)
def test_material_graph_supports_only_declared_mask_families(mask: object) -> None:
    """Accept each supported mask through deterministic discriminated serialization."""

    graph = MaterialGraphSpec(
        graph_id="graph-a",
        provenance=_provenance(),
        material_id="mat.body",
        base_channels=[_base_channel()],
        layers=[_layer(mask)],
        preview_lighting=_lighting(),
    )
    assert graph.layers[0].mask is not None
    assert graph.model_dump(mode="json")["layers"][0]["mask"]["kind"] in {
        "image",
        "vertex_attribute",
        "semantic_object",
        "curvature",
        "position_slope",
    }


def test_material_graph_rejects_data_srgb_and_repeated_local_detail() -> None:
    """Reject the two common sources of corrupt PBR and tiled localized details."""

    with pytest.raises(ValidationError, match="must use Non-Color"):
        ChannelBinding(
            channel="roughness",
            source_kind="constant",
            color_space="sRGB",
            constant=0.5,
        )
    with pytest.raises(ValidationError, match="localized details"):
        ChannelBinding(
            channel="normal",
            source_kind="image",
            color_space="Non-Color",
            image=_artifact("texture", "textures/normal.png"),
            physical_scale=TextureScale(width_m=1, height_m=1),
            localized_detail=True,
            sampling="repeat",
            normal_format="OpenGL",
        )


def test_material_graph_rejects_implicit_material_change_and_order_gap() -> None:
    """Keep material ownership stable and layer ordering deterministic."""

    mismatched = _layer(VertexAttributeMask(attribute="mask"))
    mismatched.material_id = "mat.other"
    with pytest.raises(ValidationError, match="material_id"):
        MaterialGraphSpec(
            graph_id="graph-a",
            provenance=_provenance(),
            material_id="mat.body",
            base_channels=[_base_channel()],
            layers=[mismatched],
            preview_lighting=_lighting(),
        )
    with pytest.raises(ValidationError, match="contiguous"):
        MaterialGraphSpec(
            graph_id="graph-b",
            provenance=_provenance(),
            material_id="mat.body",
            base_channels=[_base_channel()],
            layers=[_layer(VertexAttributeMask(attribute="mask"), order=1)],
            preview_lighting=_lighting(),
        )


def test_material_graph_rejects_arbitrary_node_fields_and_unsafe_paths() -> None:
    """Fail closed on arbitrary graph payloads and non-portable artifact paths."""

    payload = {
        "graph_id": "graph-a",
        "provenance": _provenance().model_dump(mode="json"),
        "material_id": "mat.body",
        "base_channels": [_base_channel().model_dump(mode="json")],
        "preview_lighting": _lighting().model_dump(mode="json"),
        "arbitrary_nodes": [{"type": "ShaderNodeScript"}],
    }
    with pytest.raises(ValidationError, match="Extra inputs"):
        MaterialGraphSpec.model_validate(payload)
    with pytest.raises(ValidationError, match="path"):
        _artifact("texture", "C:/unsafe/texture.png")
