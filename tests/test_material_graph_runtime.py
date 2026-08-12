"""Focused host tests for the whitelist MaterialGraph runtime compiler."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from PIL import Image
from pydantic import ValidationError

from codex_blender_modeler.blender_artifacts import native_io_path
from codex_blender_modeler.material_graph.compiler_service import (
    MaterialGraphCompileError,
    MaterialGraphCompilerService,
    _canonical_topological_order,
    _sha256_file,
)
from codex_blender_modeler.material_graph.models import (
    ChannelBinding,
    ImageMask,
    MaterialGraphArtifact,
    MaterialGraphLayer,
    MaterialGraphProvenance,
    MaterialGraphSpec,
    PreviewLightingPolicy,
    TextureScale,
)
from codex_blender_modeler.material_graph.registry import (
    PUBLIC_TEMPLATE_REGISTRY,
    MaterialGraphRegistryError,
    legacy_registry_sha256,
    registry_sha256,
    validate_runtime_plan,
)
from codex_blender_modeler.material_graph.runtime_models import (
    GraphCompilerPolicy,
    MaterialGraphCompileReport,
    NormalizedMaterialGraphPlan,
    NormalizedMaterialNodeInventory,
    RuntimeArtifact,
    RuntimeInputDefault,
    RuntimeLinkInventory,
    RuntimeLinkPlan,
    RuntimeNodeInventory,
    RuntimeNodePlan,
    RuntimeSetting,
)


def _sha256(path: Path) -> str:
    """Hash exact fixture bytes for immutable dependency declarations."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    """Write stable UTF-8 JSON for one isolated compiler fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _artifact(role: str, path: str, job_root: Path) -> MaterialGraphArtifact:
    """Bind a fixture artifact to its exact current digest."""

    return MaterialGraphArtifact(
        role=role,
        path=path,
        sha256=_sha256(job_root.joinpath(*path.split("/"))),
    )


def _build_job(job_root: Path, *, masked_layer: bool = False) -> str:
    """Create an isolated graph with image color, scalar data, and normal channels."""

    material_plan = job_root / "analysis" / "material_plan.json"
    scene_spec = job_root / "analysis" / "scene_spec.json"
    scene_blend = job_root / "blender" / "scene.blend"
    material_plan.parent.mkdir(parents=True)
    scene_blend.parent.mkdir(parents=True)
    material_plan.write_text('{"material":"fixture"}\n', encoding="utf-8")
    scene_spec.write_text('{"scene":"fixture"}\n', encoding="utf-8")
    scene_blend.write_bytes(b"canonical-scene-fixture")
    texture_root = job_root / "textures"
    input_root = job_root / "input"
    texture_root.mkdir()
    input_root.mkdir()
    Image.new("RGBA", (4, 4), (80, 120, 180, 255)).save(texture_root / "base_color.png")
    Image.new("RGBA", (4, 4), (128, 128, 255, 255)).save(texture_root / "normal.png")
    Image.new("L", (4, 4), 255).save(texture_root / "mask.png")
    Image.new("RGB", (4, 4), (100, 100, 100)).save(input_root / "reference.png")
    provenance = MaterialGraphProvenance(
        job_id="runtime_fixture",
        workflow_id="workflow-runtime",
        dispatch_id="dispatch-runtime",
        project_version="0.9.0",
        inputs=[
            _artifact("material_plan", "analysis/material_plan.json", job_root),
            _artifact("scene_spec", "analysis/scene_spec.json", job_root),
            _artifact("texture", "textures/base_color.png", job_root),
            _artifact("texture", "textures/normal.png", job_root),
            _artifact("reference", "input/reference.png", job_root),
        ],
    )
    channels = [
        ChannelBinding(
            channel="base_color",
            source_kind="image",
            color_space="sRGB",
            image=_artifact("texture", "textures/base_color.png", job_root),
            physical_scale=TextureScale(width_m=0.5, height_m=0.5),
        ),
        ChannelBinding(
            channel="roughness",
            source_kind="constant",
            color_space="Non-Color",
            constant=0.45,
        ),
        ChannelBinding(
            channel="normal",
            source_kind="image",
            color_space="Non-Color",
            image=_artifact("texture", "textures/normal.png", job_root),
            physical_scale=TextureScale(width_m=0.5, height_m=0.5),
            normal_format="OpenGL",
        ),
    ]
    layers = []
    if masked_layer:
        layers = [
            MaterialGraphLayer(
                layer_id="masked-replace",
                order=0,
                material_id="mat.fixture",
                blend_mode="replace",
                channels=[
                    ChannelBinding(
                        channel="metallic",
                        source_kind="constant",
                        color_space="Non-Color",
                        constant=0.2,
                    )
                ],
                mask=ImageMask(image=_artifact("mask", "textures/mask.png", job_root)),
            )
        ]
    graph = MaterialGraphSpec(
        graph_id="graph-runtime",
        provenance=provenance,
        material_id="mat.fixture",
        base_channels=channels,
        layers=layers,
        preview_lighting=PreviewLightingPolicy(
            reference_source=_artifact("reference", "input/reference.png", job_root),
            reference_confidence=0.8,
        ),
    )
    graph_path = job_root / "materials" / "material_graph.json"
    _write_json(graph_path, graph)
    return "materials/material_graph.json"


INITIAL_WHITELIST_TEMPLATES = {
    "texture_coordinate",
    "mapping",
    "image_texture",
    "noise_texture",
    "voronoi_texture",
    "wave_texture",
    "gradient_texture",
    "color_ramp",
    "mix_color",
    "math",
    "separate_color",
    "combine_color",
    "normal_map",
    "bump",
    "fresnel",
    "principled_bsdf",
    "transparent_bsdf",
    "emission",
    "mix_shader",
    "material_output",
}


def _representative_whitelist_plan(
    base: NormalizedMaterialGraphPlan, *, dependency_id: str
) -> NormalizedMaterialGraphPlan:
    """Build one connected plan that exercises every current semantic template."""

    nodes = [
        RuntimeNodePlan(node_id="texcoord", template_id="texture_coordinate"),
        RuntimeNodePlan(
            node_id="mapping",
            template_id="mapping",
            input_defaults=[RuntimeInputDefault(socket_id="scale", value=(2.0, 2.0, 2.0))],
        ),
        RuntimeNodePlan(
            node_id="image",
            template_id="image_texture",
            settings=[
                RuntimeSetting(setting_id="dependency_id", value=dependency_id),
                RuntimeSetting(setting_id="color_space", value="sRGB"),
                RuntimeSetting(setting_id="sampling", value="repeat"),
            ],
        ),
        RuntimeNodePlan(
            node_id="noise",
            template_id="noise_texture",
            settings=[RuntimeSetting(setting_id="dimensions", value="3d")],
            input_defaults=[
                RuntimeInputDefault(socket_id="scale", value=4.0),
                RuntimeInputDefault(socket_id="detail", value=2.0),
                RuntimeInputDefault(socket_id="roughness", value=0.5),
                RuntimeInputDefault(socket_id="lacunarity", value=2.0),
                RuntimeInputDefault(socket_id="distortion", value=0.1),
            ],
        ),
        RuntimeNodePlan(
            node_id="voronoi",
            template_id="voronoi_texture",
            settings=[
                RuntimeSetting(setting_id="dimensions", value="3d"),
                RuntimeSetting(setting_id="feature", value="f1"),
                RuntimeSetting(setting_id="distance_metric", value="euclidean"),
            ],
            input_defaults=[
                RuntimeInputDefault(socket_id="scale", value=3.0),
                RuntimeInputDefault(socket_id="randomness", value=0.7),
            ],
        ),
        RuntimeNodePlan(
            node_id="wave",
            template_id="wave_texture",
            settings=[
                RuntimeSetting(setting_id="wave_type", value="bands"),
                RuntimeSetting(setting_id="direction", value="x"),
                RuntimeSetting(setting_id="profile", value="sine"),
            ],
            input_defaults=[
                RuntimeInputDefault(socket_id="scale", value=5.0),
                RuntimeInputDefault(socket_id="distortion", value=0.2),
                RuntimeInputDefault(socket_id="detail", value=2.0),
                RuntimeInputDefault(socket_id="detail_scale", value=1.5),
                RuntimeInputDefault(socket_id="detail_roughness", value=0.4),
                RuntimeInputDefault(socket_id="phase", value=0.25),
            ],
        ),
        RuntimeNodePlan(
            node_id="gradient",
            template_id="gradient_texture",
            settings=[RuntimeSetting(setting_id="gradient_type", value="linear")],
        ),
        RuntimeNodePlan(
            node_id="ramp",
            template_id="color_ramp",
            settings=[
                RuntimeSetting(setting_id="interpolation", value="linear"),
                RuntimeSetting(setting_id="position_0", value=0.2),
                RuntimeSetting(setting_id="red_0", value=0.05),
                RuntimeSetting(setting_id="green_0", value=0.1),
                RuntimeSetting(setting_id="blue_0", value=0.2),
                RuntimeSetting(setting_id="alpha_0", value=1.0),
                RuntimeSetting(setting_id="position_1", value=0.8),
                RuntimeSetting(setting_id="red_1", value=0.8),
                RuntimeSetting(setting_id="green_1", value=0.6),
                RuntimeSetting(setting_id="blue_1", value=0.2),
                RuntimeSetting(setting_id="alpha_1", value=1.0),
            ],
        ),
        RuntimeNodePlan(
            node_id="separate",
            template_id="separate_color",
            settings=[RuntimeSetting(setting_id="mode", value="rgb")],
        ),
        RuntimeNodePlan(
            node_id="combine",
            template_id="combine_color",
            settings=[RuntimeSetting(setting_id="mode", value="rgb")],
        ),
        RuntimeNodePlan(
            node_id="math",
            template_id="math",
            settings=[
                RuntimeSetting(setting_id="operation", value="multiply"),
                RuntimeSetting(setting_id="clamp", value=True),
            ],
        ),
        RuntimeNodePlan(
            node_id="mix-color",
            template_id="mix_color",
            settings=[
                RuntimeSetting(setting_id="blend_mode", value="mix"),
                RuntimeSetting(setting_id="clamp_factor", value=True),
                RuntimeSetting(setting_id="clamp_result", value=False),
            ],
        ),
        RuntimeNodePlan(
            node_id="normal-map",
            template_id="normal_map",
            input_defaults=[RuntimeInputDefault(socket_id="strength", value=0.5)],
        ),
        RuntimeNodePlan(
            node_id="bump",
            template_id="bump",
            input_defaults=[
                RuntimeInputDefault(socket_id="strength", value=0.4),
                RuntimeInputDefault(socket_id="distance", value=0.05),
            ],
        ),
        RuntimeNodePlan(
            node_id="fresnel",
            template_id="fresnel",
            input_defaults=[RuntimeInputDefault(socket_id="ior", value=1.45)],
        ),
        RuntimeNodePlan(
            node_id="principled",
            template_id="principled_bsdf",
            input_defaults=[
                RuntimeInputDefault(socket_id="roughness", value=0.4),
                RuntimeInputDefault(socket_id="metallic", value=0.1),
                RuntimeInputDefault(socket_id="alpha", value=1.0),
            ],
        ),
        RuntimeNodePlan(
            node_id="transparent",
            template_id="transparent_bsdf",
            input_defaults=[RuntimeInputDefault(socket_id="color", value=(1.0, 1.0, 1.0, 1.0))],
        ),
        RuntimeNodePlan(
            node_id="emission",
            template_id="emission",
            input_defaults=[
                RuntimeInputDefault(socket_id="color", value=(0.1, 0.2, 1.0, 1.0)),
                RuntimeInputDefault(socket_id="strength", value=2.0),
            ],
        ),
        RuntimeNodePlan(node_id="mix-shader-a", template_id="mix_shader"),
        RuntimeNodePlan(node_id="mix-shader-b", template_id="mix_shader"),
        RuntimeNodePlan(node_id="output", template_id="material_output"),
    ]
    links: list[RuntimeLinkPlan] = []

    def connect(source_node: str, source_socket: str, target_node: str, target_socket: str) -> None:
        """Append one stable semantic link to the representative plan."""

        links.append(
            RuntimeLinkPlan(
                link_id=f"link-{len(links) + 1:03d}",
                source_node_id=source_node,
                source_socket_id=source_socket,
                target_node_id=target_node,
                target_socket_id=target_socket,
            )
        )

    connect("texcoord", "uv", "mapping", "vector")
    for target in ("image", "noise", "voronoi", "wave", "gradient"):
        connect("mapping", "vector", target, "vector")
    connect("image", "color", "separate", "color")
    connect("separate", "red", "combine", "red")
    connect("separate", "green", "combine", "green")
    connect("separate", "blue", "combine", "blue")
    connect("noise", "factor", "ramp", "factor")
    connect("gradient", "factor", "math", "value_a")
    connect("voronoi", "distance", "math", "value_b")
    connect("math", "value", "mix-color", "factor")
    connect("ramp", "color", "mix-color", "color_a")
    connect("combine", "color", "mix-color", "color_b")
    connect("noise", "color", "normal-map", "color")
    connect("wave", "factor", "bump", "height")
    connect("normal-map", "normal", "bump", "normal")
    connect("mix-color", "color", "principled", "base_color")
    connect("bump", "normal", "principled", "normal")
    connect("fresnel", "factor", "mix-shader-a", "factor")
    connect("principled", "bsdf", "mix-shader-a", "shader_a")
    connect("transparent", "bsdf", "mix-shader-a", "shader_b")
    connect("wave", "factor", "mix-shader-b", "factor")
    connect("mix-shader-a", "shader", "mix-shader-b", "shader_a")
    connect("emission", "shader", "mix-shader-b", "shader_b")
    connect("mix-shader-b", "shader", "output", "surface")
    return NormalizedMaterialGraphPlan(
        plan_id=f"{base.plan_id}-whitelist",
        graph_id=base.graph_id,
        material_id=base.material_id,
        graph_spec_path=base.graph_spec_path,
        graph_spec_sha256=base.graph_spec_sha256,
        registry_sha256=registry_sha256(),
        policy=base.policy,
        nodes=nodes,
        links=links,
        topological_order=_canonical_topological_order(nodes, links),
        layer_count=base.layer_count,
        texture_count=1,
    )


def test_prepare_compile_is_deterministic_and_semantic_only(tmp_path: Path) -> None:
    """Build equal normalized plans without exposing Blender node or socket controls."""

    graph_path = _build_job(tmp_path)
    service = MaterialGraphCompilerService(tmp_path)
    first = service.prepare_compile(graph_spec_path=graph_path, run_id="run-a")
    second = service.prepare_compile(graph_spec_path=graph_path, run_id="run-b")
    assert first.plan == second.plan
    assert first.plan.registry_sha256 == registry_sha256()
    assert first.plan.texture_count == 2
    assert first.neutral_preview.scope == "neutral_studio"
    assert first.reference_preview.scope == "reference_matched"
    assert not first.neutral_preview.rendered
    assert not first.reference_preview.rendered
    serialized = first.plan.model_dump_json()
    assert "ShaderNode" not in serialized
    assert "bl_idname" not in serialized
    assert "python" not in serialized.lower()
    assert {item.role for item in first.dependencies.dependencies} >= {
        "graph_spec",
        "material_plan",
        "texture",
        "reference",
    }


def test_runtime_registry_covers_initial_whitelist_and_preserves_v1_digest(
    tmp_path: Path,
) -> None:
    """Validate all 20 templates while retaining exact seven-template v1 evidence."""

    graph_path = _build_job(tmp_path)
    prepared = MaterialGraphCompilerService(tmp_path).prepare_compile(
        graph_spec_path=graph_path,
        run_id="registry-whitelist",
    )
    image_node = next(item for item in prepared.plan.nodes if item.node_id == "image-base-color")
    dependency_id = next(
        item.value for item in image_node.settings if item.setting_id == "dependency_id"
    )
    plan = _representative_whitelist_plan(
        prepared.plan,
        dependency_id=str(dependency_id),
    )
    assert set(PUBLIC_TEMPLATE_REGISTRY) == INITIAL_WHITELIST_TEMPLATES
    assert {item.template_id for item in plan.nodes} == INITIAL_WHITELIST_TEMPLATES
    assert validate_runtime_plan(plan) <= plan.policy.maximum_depth
    assert legacy_registry_sha256() == (
        "57818419668d417ff2018159af37102976b71b3c4325b1bfce18588f8d61ec10"
    )
    legacy_plan = prepared.plan.model_copy(update={"registry_sha256": legacy_registry_sha256()})
    assert validate_runtime_plan(legacy_plan) > 0


def test_runtime_registry_rejects_extended_ranges_and_ramp_order(
    tmp_path: Path,
) -> None:
    """Fail closed on out-of-range semantic defaults and invalid ramp ordering."""

    graph_path = _build_job(tmp_path)
    prepared = MaterialGraphCompilerService(tmp_path).prepare_compile(
        graph_spec_path=graph_path,
        run_id="registry-ranges",
    )
    image_node = next(item for item in prepared.plan.nodes if item.node_id == "image-base-color")
    dependency_id = next(
        item.value for item in image_node.settings if item.setting_id == "dependency_id"
    )
    plan = _representative_whitelist_plan(
        prepared.plan,
        dependency_id=str(dependency_id),
    )
    noise = next(item for item in plan.nodes if item.node_id == "noise")
    invalid_noise = noise.model_copy(
        update={
            "input_defaults": [
                item.model_copy(update={"value": 100_000.1}) if item.socket_id == "scale" else item
                for item in noise.input_defaults
            ]
        }
    )
    with pytest.raises(MaterialGraphRegistryError, match="outside its range"):
        validate_runtime_plan(
            plan.model_copy(
                update={
                    "nodes": [
                        invalid_noise if item.node_id == "noise" else item for item in plan.nodes
                    ]
                }
            )
        )

    ramp = next(item for item in plan.nodes if item.node_id == "ramp")
    invalid_ramp = ramp.model_copy(
        update={
            "settings": [
                item.model_copy(update={"value": 0.9}) if item.setting_id == "position_0" else item
                for item in ramp.settings
            ]
        }
    )
    with pytest.raises(MaterialGraphRegistryError, match="position_0"):
        validate_runtime_plan(
            plan.model_copy(
                update={
                    "nodes": [
                        invalid_ramp if item.node_id == "ramp" else item for item in plan.nodes
                    ]
                }
            )
        )


def test_prepare_compile_rejects_stale_and_escaping_sources(tmp_path: Path) -> None:
    """Fail closed when exact dependency bytes change or a source path escapes the job."""

    graph_path = _build_job(tmp_path)
    (tmp_path / "textures" / "base_color.png").write_bytes(b"tampered")
    service = MaterialGraphCompilerService(tmp_path)
    with pytest.raises(MaterialGraphCompileError, match="stale"):
        service.prepare_compile(graph_spec_path=graph_path, run_id="run-stale")
    with pytest.raises(MaterialGraphCompileError, match="unsafe path"):
        service.prepare_compile(graph_spec_path="../outside.json", run_id="run-escape")


def test_dependency_resolver_supports_extended_length_paths(tmp_path: Path) -> None:
    """Resolve one regular dependency beyond MAX_PATH without weakening containment."""

    parts = [f"segment-{index}-{'x' * 40}" for index in range(6)]
    relative = "/".join(["textures", *parts, "generated-image-evidence.json"])
    dependency = tmp_path.joinpath(*relative.split("/"))
    os.makedirs(native_io_path(dependency.parent), exist_ok=True)
    with open(native_io_path(dependency), "wb") as handle:
        handle.write(b'{"kind":"generated-image-evidence"}\n')
    assert len(os.path.abspath(os.fspath(dependency))) > 260

    resolved = MaterialGraphCompilerService(tmp_path)._resolve_contained_file(relative)

    assert resolved == dependency
    assert _sha256_file(resolved) == hashlib.sha256(
        b'{"kind":"generated-image-evidence"}\n'
    ).hexdigest()
    with open(native_io_path(resolved), "rb") as handle:
        assert handle.read() == b'{"kind":"generated-image-evidence"}\n'


def test_dependency_resolver_still_rejects_link_traversal(tmp_path: Path) -> None:
    """Keep symlink traversal fail-closed while using lexical long-path containment."""

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "dependency.json").write_text("{}\n", encoding="utf-8")
    link = tmp_path / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(MaterialGraphCompileError, match="symlink"):
        MaterialGraphCompilerService(tmp_path)._resolve_contained_file(
            "linked/dependency.json"
        )


def test_runtime_registry_rejects_raw_templates_cycles_and_depth() -> None:
    """Reject raw Blender fields, unknown templates, cycles, and over-depth graphs."""

    with pytest.raises(ValidationError, match="Extra inputs"):
        RuntimeNodePlan.model_validate(
            {
                "node_id": "raw",
                "template_id": "principled_bsdf",
                "settings": [],
                "input_defaults": [],
                "bl_idname": "ShaderNodeScript",
            }
        )
    base = NormalizedMaterialGraphPlan(
        plan_id="plan-cycle",
        graph_id="graph-cycle",
        material_id="mat.cycle",
        graph_spec_path="materials/cycle.json",
        graph_spec_sha256="a" * 64,
        registry_sha256=registry_sha256(),
        policy=GraphCompilerPolicy(),
        nodes=[
            RuntimeNodePlan(node_id="map-a", template_id="mapping"),
            RuntimeNodePlan(node_id="map-b", template_id="mapping"),
        ],
        links=[
            RuntimeLinkPlan(
                link_id="link-a",
                source_node_id="map-a",
                source_socket_id="vector",
                target_node_id="map-b",
                target_socket_id="vector",
            ),
            RuntimeLinkPlan(
                link_id="link-b",
                source_node_id="map-b",
                source_socket_id="vector",
                target_node_id="map-a",
                target_socket_id="vector",
            ),
        ],
        topological_order=["map-a", "map-b"],
        layer_count=0,
        texture_count=0,
    )
    with pytest.raises(MaterialGraphRegistryError, match="cycle"):
        validate_runtime_plan(base)
    for forbidden_template in (
        "custom_node",
        "script_node",
        "node_group",
        "driver_node",
        "callback_node",
    ):
        unknown = base.model_copy(
            update={
                "nodes": [
                    base.nodes[0].model_copy(update={"template_id": forbidden_template}),
                    base.nodes[1],
                ]
            }
        )
        with pytest.raises(MaterialGraphRegistryError, match="unknown or forbidden"):
            validate_runtime_plan(unknown)
    chain = base.model_copy(
        update={
            "policy": GraphCompilerPolicy(maximum_depth=2),
            "nodes": [
                RuntimeNodePlan(node_id=f"map-{index}", template_id="mapping") for index in range(3)
            ],
            "links": [
                RuntimeLinkPlan(
                    link_id=f"link-{index}",
                    source_node_id=f"map-{index}",
                    source_socket_id="vector",
                    target_node_id=f"map-{index + 1}",
                    target_socket_id="vector",
                )
                for index in range(2)
            ],
            "topological_order": ["map-0", "map-1", "map-2"],
        }
    )
    with pytest.raises(MaterialGraphRegistryError, match="depth cap"):
        validate_runtime_plan(chain)


def test_runtime_compiler_rejects_unimplemented_masks_and_texture_caps(
    tmp_path: Path,
) -> None:
    """Fail closed rather than approximating masked layers or exceeding texture policy."""

    graph_path = _build_job(tmp_path, masked_layer=True)
    service = MaterialGraphCompilerService(tmp_path)
    with pytest.raises(MaterialGraphCompileError, match="masked layers"):
        service.prepare_compile(graph_spec_path=graph_path, run_id="run-mask")

    second_root = tmp_path / "texture-cap"
    second_path = _build_job(second_root)
    capped = MaterialGraphCompilerService(second_root)
    with pytest.raises(MaterialGraphCompileError, match="texture cap"):
        capped.prepare_compile(
            graph_spec_path=second_path,
            run_id="run-cap",
            policy=GraphCompilerPolicy(maximum_textures=1),
        )
    with pytest.raises(MaterialGraphCompileError, match="node cap"):
        capped.prepare_compile(
            graph_spec_path=second_path,
            run_id="run-node-cap",
            policy=GraphCompilerPolicy(maximum_nodes=2),
        )

    third_root = tmp_path / "layer-cap"
    third_path = _build_job(third_root, masked_layer=True)
    with pytest.raises(MaterialGraphCompileError, match="layer cap"):
        MaterialGraphCompilerService(third_root).prepare_compile(
            graph_spec_path=third_path,
            run_id="run-layer-cap",
            policy=GraphCompilerPolicy(maximum_layers=0),
        )


def test_runtime_compiler_rejects_silent_normal_height_and_uv_approximations(
    tmp_path: Path,
) -> None:
    """Reject policies and UV sets the fixed Blender compiler cannot honor exactly."""

    disabled_root = tmp_path / "normal-disabled"
    graph_path = _build_job(disabled_root)
    path = disabled_root / graph_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["normal_displacement"]["normal_mode"] = "disabled"
    _write_json(path, payload)
    with pytest.raises(MaterialGraphCompileError, match="disabled normal"):
        MaterialGraphCompilerService(disabled_root).prepare_compile(
            graph_spec_path=graph_path, run_id="normal-disabled"
        )

    uv_root = tmp_path / "named-uv"
    graph_path = _build_job(uv_root)
    path = uv_root / graph_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["base_channels"][0]["physical_scale"]["uv_set"] = "DetailUV"
    _write_json(path, payload)
    with pytest.raises(MaterialGraphCompileError, match="UVMap"):
        MaterialGraphCompilerService(uv_root).prepare_compile(
            graph_spec_path=graph_path, run_id="named-uv"
        )

    height_root = tmp_path / "height-constant"
    graph_path = _build_job(height_root)
    path = height_root / graph_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["base_channels"].append(
        {
            "channel": "height",
            "source_kind": "constant",
            "color_space": "Non-Color",
            "constant": 0.1,
            "image": None,
            "physical_scale": None,
            "sampling": "repeat",
            "localized_detail": False,
            "normal_format": None,
        }
    )
    _write_json(path, payload)
    with pytest.raises(MaterialGraphCompileError, match="height compilation"):
        MaterialGraphCompilerService(height_root).prepare_compile(
            graph_spec_path=graph_path, run_id="height-constant"
        )


def _fake_blender_runner(
    script_name: str, args: list[str], **_: object
) -> subprocess.CompletedProcess[str]:
    """Publish strict fake Blender evidence for host atomic-lifecycle testing only."""

    assert script_name == "compile_material_graph_runtime.py"
    run_root = Path(args[args.index("--run-root") + 1])
    request_path = run_root / args[args.index("--request") + 1]
    request = json.loads(request_path.read_text(encoding="utf-8"))
    plan = json.loads((run_root / request["plan_path"]).read_text(encoding="utf-8"))
    blend_path = run_root / request["output_blend_path"]
    blend_path.parent.mkdir(parents=True)
    blend_path.write_bytes(b"fake-blender-evidence")
    semantic_sha = hashlib.sha256(b"normalized-inventory").hexdigest()
    inventory = NormalizedMaterialNodeInventory(
        inventory_id=f"inventory-{plan['plan_id']}",
        graph_id=plan["graph_id"],
        material_id=plan["material_id"],
        registry_sha256=request["registry_sha256"],
        plan_sha256=request["plan_sha256"],
        nodes=[
            RuntimeNodeInventory(node_id=item["node_id"], template_id=item["template_id"])
            for item in plan["nodes"]
        ],
        links=[RuntimeLinkInventory.model_validate(item) for item in plan["links"]],
        principled_socket_resolution={"base_color": "Base Color"},
        normalized_inventory_sha256=semantic_sha,
    )
    inventory_path = run_root / request["inventory_path"]
    _write_json(inventory_path, inventory)
    roles = {
        "request": request_path.relative_to(run_root).as_posix(),
        "normalized_plan": request["plan_path"],
        "dependency_manifest": request["dependency_manifest_path"],
        "compiled_blend": request["output_blend_path"],
        "normalized_inventory": request["inventory_path"],
        "portable_approximation": request["portable_approximation_path"],
        "neutral_preview_manifest": request["neutral_preview_manifest_path"],
        "reference_preview_manifest": request["reference_preview_manifest_path"],
    }
    artifacts = []
    for role, relative in roles.items():
        path = run_root / relative
        artifacts.append(
            RuntimeArtifact(
                role=role,
                path=relative,
                sha256=_sha256(path),
                byte_size=path.stat().st_size,
            )
        )
    report = MaterialGraphCompileReport(
        report_id=f"report-{request['run_id']}",
        request_id=request["request_id"],
        job_id=request["job_id"],
        workflow_id=request["workflow_id"],
        dispatch_id=request["dispatch_id"],
        run_id=request["run_id"],
        graph_id=plan["graph_id"],
        material_id=plan["material_id"],
        blender_version="5.0.1-fake-host-test",
        blender_python_version="3.11",
        registry_sha256=request["registry_sha256"],
        normalized_plan_sha256=request["plan_sha256"],
        normalized_inventory_sha256=semantic_sha,
        artifacts=artifacts,
        completed_at=datetime.now(UTC),
    )
    _write_json(run_root / request["report_path"], report)
    return subprocess.CompletedProcess([], 0, "", "")


def test_compile_run_atomically_publishes_without_canonical_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish one exact run root while preserving canonical material and scene bytes."""

    graph_path = _build_job(tmp_path)
    material_before = _sha256(tmp_path / "analysis" / "material_plan.json")
    scene_spec_before = _sha256(tmp_path / "analysis" / "scene_spec.json")
    scene_before = _sha256(tmp_path / "blender" / "scene.blend")
    monkeypatch.setattr(
        "codex_blender_modeler.material_graph.compiler_service.run_blender",
        _fake_blender_runner,
    )
    bundle = MaterialGraphCompilerService(tmp_path).compile_run(
        graph_spec_path=graph_path,
        run_root="reports/material_graph/runs/runtime-a",
        run_id="runtime-a",
    )
    assert bundle.report.ok
    assert bundle.report.blend_bytes_deterministic is False
    assert (tmp_path / bundle.run_root / "compile_report.json").is_file()
    assert _sha256(tmp_path / "analysis" / "material_plan.json") == material_before
    assert _sha256(tmp_path / "analysis" / "scene_spec.json") == scene_spec_before
    assert _sha256(tmp_path / "blender" / "scene.blend") == scene_before
    assert not list((tmp_path / "reports" / "material_graph" / "runs").glob(".g-*"))
    adopted = MaterialGraphCompilerService(tmp_path).validate_compile_run(run_root=bundle.run_root)
    assert adopted == bundle


def test_validate_compile_run_rejects_stale_published_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject crash-adopted compile evidence after an exact graph dependency changes."""

    graph_path = _build_job(tmp_path)
    monkeypatch.setattr(
        "codex_blender_modeler.material_graph.compiler_service.run_blender",
        _fake_blender_runner,
    )
    bundle = MaterialGraphCompilerService(tmp_path).compile_run(
        graph_spec_path=graph_path,
        run_root="reports/material_graph/runs/adopt-stale",
        run_id="adopt-stale",
    )
    (tmp_path / "textures" / "base_color.png").write_bytes(b"tampered")
    with pytest.raises(MaterialGraphCompileError, match="dependency changed"):
        MaterialGraphCompilerService(tmp_path).validate_compile_run(run_root=bundle.run_root)


def test_runtime_schemas_self_validate_published_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check every runtime schema and validate one complete published evidence bundle."""

    graph_path = _build_job(tmp_path)
    monkeypatch.setattr(
        "codex_blender_modeler.material_graph.compiler_service.run_blender",
        _fake_blender_runner,
    )
    bundle = MaterialGraphCompilerService(tmp_path).compile_run(
        graph_spec_path=graph_path,
        run_root="reports/material_graph/runs/schema-a",
        run_id="schema-a",
    )
    run_root = tmp_path / bundle.run_root
    repository_root = Path(__file__).resolve().parents[1]
    cases = [
        ("material_graph_runtime_plan.schema.json", "normalized_plan.json"),
        (
            "material_graph_runtime_dependency_manifest.schema.json",
            "dependency_manifest.json",
        ),
        ("material_graph_runtime_compile_request.schema.json", "compiler_request.json"),
        ("material_graph_runtime_compile_report.schema.json", "compile_report.json"),
        (
            "material_graph_runtime_inventory.schema.json",
            "normalized_inventory.json",
        ),
        (
            "material_graph_runtime_portable_approximation.schema.json",
            "portable_approximation.json",
        ),
        (
            "material_graph_runtime_preview_manifest.schema.json",
            "neutral_preview_manifest.json",
        ),
        (
            "material_graph_runtime_preview_manifest.schema.json",
            "reference_preview_manifest.json",
        ),
    ]
    for schema_name, artifact_name in cases:
        schema = json.loads((repository_root / "schemas" / schema_name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(
            json.loads((run_root / artifact_name).read_text(encoding="utf-8"))
        )


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_MATERIAL_GRAPH_BLENDER_SMOKE") != "1",
    reason="set CBM_RUN_MATERIAL_GRAPH_BLENDER_SMOKE=1 for Blender 5 smoke",
)
def test_material_graph_compiles_reopens_and_inventories_in_blender_5(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compile, reopen, and inventory all 20 templates through actual Blender 5."""

    graph_path = _build_job(tmp_path)
    service = MaterialGraphCompilerService(tmp_path)
    prepared = service.prepare_compile(
        graph_spec_path=graph_path,
        run_id="blender-smoke-prepare",
    )
    image_node = next(item for item in prepared.plan.nodes if item.node_id == "image-base-color")
    dependency_id = next(
        item.value for item in image_node.settings if item.setting_id == "dependency_id"
    )
    representative = _representative_whitelist_plan(
        prepared.plan,
        dependency_id=str(dependency_id),
    )

    def compile_representative_plan(*_: object, **__: object) -> NormalizedMaterialGraphPlan:
        """Return the fixed representative plan after normal source preparation."""

        return representative

    monkeypatch.setattr(
        MaterialGraphCompilerService,
        "_compile_plan",
        compile_representative_plan,
    )
    bundle = service.compile_run(
        graph_spec_path=graph_path,
        run_root="reports/material_graph/runs/blender-smoke",
        run_id="blender-smoke",
    )
    assert bundle.report.blender_version.startswith("5.")
    assert bundle.report.ok
    inventory_path = (
        tmp_path
        / bundle.run_root
        / next(item.path for item in bundle.report.artifacts if item.role == "normalized_inventory")
    )
    inventory = NormalizedMaterialNodeInventory.model_validate_json(
        inventory_path.read_text(encoding="utf-8")
    )
    assert inventory.normalized_inventory_sha256 == (bundle.report.normalized_inventory_sha256)
    assert {item.template_id for item in inventory.nodes} == INITIAL_WHITELIST_TEMPLATES
