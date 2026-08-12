"""Host-side fail-closed compiler service for MaterialGraphSpec 0.1."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from ..blender_artifacts import native_io_path
from ..blender_runner import run_blender
from .models import ChannelBinding, MaterialGraphArtifact, MaterialGraphSpec
from .registry import (
    is_supported_registry_sha256,
    registry_sha256,
    validate_runtime_plan,
)
from .runtime_models import (
    GraphCompilerPolicy,
    GraphDependency,
    MaterialGraphCompileBundle,
    MaterialGraphCompileReport,
    MaterialGraphCompileRequest,
    MaterialGraphDependencyManifest,
    MaterialPreviewManifest,
    NormalizedMaterialGraphPlan,
    PortableApproximationFinding,
    PortableMaterialApproximationReport,
    RuntimeInputDefault,
    RuntimeLinkPlan,
    RuntimeNodePlan,
    RuntimeSetting,
)

CHANNEL_ORDER = (
    "base_color",
    "roughness",
    "metallic",
    "normal",
    "height",
    "occlusion",
    "emission",
    "opacity",
)


class MaterialGraphCompileError(RuntimeError):
    """Signal invalid, stale, unsupported, or incomplete compile evidence."""


@dataclass(frozen=True)
class _PreparedCompile:
    """Hold validated host artifacts before atomic Blender publication."""

    spec: MaterialGraphSpec
    plan: NormalizedMaterialGraphPlan
    dependencies: MaterialGraphDependencyManifest
    portable: PortableMaterialApproximationReport
    neutral_preview: MaterialPreviewManifest
    reference_preview: MaterialPreviewManifest


def _canonical_json_bytes(value: object) -> bytes:
    """Serialize a contract deterministically for hashing and publication."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    """Return one lowercase SHA-256 digest for in-memory evidence."""

    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    """Hash exact file bytes without interpreting their content."""

    digest = hashlib.sha256()
    with open(native_io_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_exclusive(path: Path, value: object) -> str:
    """Write one deterministic JSON artifact without replacing prior evidence."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    content = _canonical_json_bytes(payload) + b"\n"
    with open(native_io_path(path), "xb") as handle:
        handle.write(content)
    return _sha256_bytes(content)


def _is_link_like(path: Path) -> bool:
    """Detect symlinks and Windows reparse points through extended-length paths."""

    native = native_io_path(path)
    if os.path.islink(native):
        return True
    try:
        metadata = os.lstat(native)
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _read_text(path: Path) -> str:
    """Read UTF-8 contract text without the Windows legacy path-length limit."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        return handle.read()


def _canonical_topological_order(
    nodes: list[RuntimeNodePlan], links: list[RuntimeLinkPlan]
) -> list[str]:
    """Derive the unique stable host topological order used by the registry verifier."""

    node_ids = {item.node_id for item in nodes}
    adjacency = {node_id: set() for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for link in links:
        if link.target_node_id not in adjacency[link.source_node_id]:
            adjacency[link.source_node_id].add(link.target_node_id)
            indegree[link.target_node_id] += 1
    ready = sorted(node_id for node_id, value in indegree.items() if value == 0)
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for target_id in sorted(adjacency[node_id]):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)
                ready.sort()
    if len(order) != len(node_ids):
        raise MaterialGraphCompileError("compiled semantic graph contains a cycle")
    return order


class MaterialGraphCompilerService:
    """Compile one immutable MaterialGraphSpec into a run-owned Blender artifact bundle."""

    def __init__(self, job_root: Path) -> None:
        """Bind compilation to one existing job root without changing canonical paths."""

        self.job_root = job_root.resolve()
        if not self.job_root.is_dir():
            raise FileNotFoundError(self.job_root)

    def _resolve_contained_file(self, relative_path: str) -> Path:
        """Resolve one exact regular input while rejecting escapes and symlink traversal."""

        if "\\" in relative_path or relative_path.startswith("/") or ":" in relative_path:
            raise MaterialGraphCompileError("material graph dependency has an unsafe path")
        if any(part in {"", ".", ".."} for part in relative_path.split("/")):
            raise MaterialGraphCompileError("material graph dependency has an unsafe path")
        candidate = self.job_root.joinpath(*relative_path.split("/"))
        current = self.job_root
        for part in relative_path.split("/"):
            current = current / part
            if _is_link_like(current):
                raise MaterialGraphCompileError(
                    f"material graph dependency cannot traverse a symlink: {relative_path}"
                )
        if not os.path.isfile(native_io_path(candidate)):
            raise MaterialGraphCompileError(
                f"material graph dependency is missing or escapes the job: {relative_path}"
            )
        return candidate

    def _resolve_new_run_root(self, relative_path: str) -> Path:
        """Resolve a normalized unpublished run root below the bound job directory."""

        if "\\" in relative_path or relative_path.startswith("/") or ":" in relative_path:
            raise MaterialGraphCompileError("run root must be a normalized relative path")
        parts = relative_path.split("/")
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise MaterialGraphCompileError("run root contains an unsafe path segment")
        candidate = self.job_root.joinpath(*parts)
        current = self.job_root
        for part in parts[:-1]:
            current = current / part
            if _is_link_like(current):
                raise MaterialGraphCompileError("run root cannot traverse a symlink")
        if os.path.exists(native_io_path(candidate)):
            raise FileExistsError(candidate)
        return candidate

    def _load_graph_spec(self, relative_path: str) -> tuple[MaterialGraphSpec, str]:
        """Load a strict existing 0.1 graph and bind its exact file digest."""

        path = self._resolve_contained_file(relative_path)
        try:
            spec = MaterialGraphSpec.model_validate_json(_read_text(path))
        except (OSError, ValidationError) as exc:
            raise MaterialGraphCompileError("MaterialGraphSpec 0.1 is invalid") from exc
        return spec, _sha256_file(path)

    def _merge_dependency(
        self,
        merged: dict[str, tuple[str, str, str | None]],
        artifact: MaterialGraphArtifact,
        *,
        role: str | None = None,
        color_space: str | None = None,
    ) -> None:
        """Merge one exact dependency and reject digest, role, or colorspace ambiguity."""

        selected_role = role or (
            artifact.role
            if artifact.role in {"material_plan", "texture", "mask", "reference"}
            else "other"
        )
        current = merged.get(artifact.path)
        candidate = (artifact.sha256, selected_role, color_space)
        if current is None:
            merged[artifact.path] = candidate
            return
        current_sha, current_role, current_color = current
        if current_sha != artifact.sha256:
            raise MaterialGraphCompileError(f"dependency has conflicting hashes: {artifact.path}")
        if current_role == "other":
            merged_role = selected_role
        elif selected_role == "other" or current_role == selected_role:
            merged_role = current_role
        else:
            raise MaterialGraphCompileError(f"dependency has conflicting roles: {artifact.path}")
        if current_color is not None and color_space is not None:
            if current_color != color_space:
                raise MaterialGraphCompileError(
                    f"dependency has conflicting color spaces: {artifact.path}"
                )
        merged[artifact.path] = (
            current_sha,
            merged_role,
            current_color or color_space,
        )

    def _collect_dependencies(
        self,
        spec: MaterialGraphSpec,
        graph_spec_path: str,
        graph_spec_sha256: str,
    ) -> tuple[MaterialGraphDependencyManifest, dict[str, str]]:
        """Verify every declared graph, provenance, texture, mask, and reference input."""

        merged: dict[str, tuple[str, str, str | None]] = {
            graph_spec_path: (graph_spec_sha256, "graph_spec", None)
        }
        for artifact in spec.provenance.inputs:
            provenance_role = (
                artifact.role if artifact.role in {"material_plan", "reference"} else "other"
            )
            self._merge_dependency(merged, artifact, role=provenance_role)
        bindings = [*spec.base_channels]
        for layer in spec.layers:
            bindings.extend(layer.channels)
            if layer.mask is not None and getattr(layer.mask, "kind", None) == "image":
                self._merge_dependency(
                    merged,
                    layer.mask.image,
                    role="mask",
                    color_space="Non-Color",
                )
        for binding in bindings:
            if binding.image is not None:
                self._merge_dependency(
                    merged,
                    binding.image,
                    role="texture",
                    color_space=binding.color_space,
                )
        self._merge_dependency(
            merged,
            spec.preview_lighting.reference_source,
            role="reference",
        )

        dependencies: list[GraphDependency] = []
        path_to_id: dict[str, str] = {}
        fingerprint_items: list[dict[str, str]] = []
        for index, relative_path in enumerate(sorted(merged), start=1):
            expected, role, color_space = merged[relative_path]
            actual = _sha256_file(self._resolve_contained_file(relative_path))
            if actual != expected:
                raise MaterialGraphCompileError(f"stale material graph dependency: {relative_path}")
            dependency_id = f"dep-{index:03d}"
            path_to_id[relative_path] = dependency_id
            dependencies.append(
                GraphDependency(
                    dependency_id=dependency_id,
                    role=role,
                    path=relative_path,
                    sha256=expected,
                    color_space=color_space,
                )
            )
            fingerprint_items.append({"path": relative_path, "sha256": expected})
        manifest = MaterialGraphDependencyManifest(
            manifest_id=f"deps-{spec.graph_id}",
            job_id=spec.provenance.job_id,
            graph_id=spec.graph_id,
            source_fingerprint=_sha256_bytes(_canonical_json_bytes(fingerprint_items)),
            dependencies=dependencies,
        )
        return manifest, path_to_id

    def _effective_channels(self, spec: MaterialGraphSpec) -> dict[str, ChannelBinding]:
        """Resolve exact replace-only layers and fail closed for uncompiled layer semantics."""

        active = {binding.channel: binding for binding in spec.base_channels}
        for layer in spec.layers:
            if layer.mask is not None:
                raise MaterialGraphCompileError(
                    "runtime vertical slice does not compile masked layers"
                )
            if layer.blend_mode != "replace" or layer.opacity != 1.0:
                raise MaterialGraphCompileError(
                    "runtime vertical slice supports only opacity=1 replace layers"
                )
            for binding in layer.channels:
                active[binding.channel] = binding
        return active

    def _validate_supported_policy(
        self, spec: MaterialGraphSpec, channels: dict[str, ChannelBinding]
    ) -> None:
        """Reject graph features that lack an exact fixed-script implementation."""

        if spec.normal_displacement.normal_mode == "object_space":
            raise MaterialGraphCompileError("object-space normal compilation is unsupported")
        if spec.normal_displacement.displacement_mode == "true_displacement":
            raise MaterialGraphCompileError("true displacement compilation is unsupported")
        normal = channels.get("normal")
        height = channels.get("height")
        if normal is not None and spec.normal_displacement.normal_mode == "disabled":
            raise MaterialGraphCompileError("normal channel conflicts with disabled normal policy")
        if height is not None and spec.normal_displacement.displacement_mode == "disabled":
            raise MaterialGraphCompileError(
                "height channel conflicts with disabled displacement policy"
            )
        if normal is not None and normal.normal_format != "OpenGL":
            raise MaterialGraphCompileError(
                "DirectX normal conversion is unsupported and cannot be assumed"
            )
        for channel, binding in channels.items():
            if binding.image is not None and binding.physical_scale is not None:
                if binding.physical_scale.uv_set != "UVMap":
                    raise MaterialGraphCompileError(
                        "runtime vertical slice supports only the explicit UVMap set"
                    )
            if channel == "normal" and binding.source_kind != "image":
                raise MaterialGraphCompileError("normal compilation requires an image")
            if channel == "height" and binding.source_kind != "image":
                raise MaterialGraphCompileError("height compilation requires an image")
            if channel in {"base_color", "emission"} and binding.source_kind == "constant":
                if not isinstance(binding.constant, tuple):
                    raise MaterialGraphCompileError(
                        f"{channel} constants require an explicit RGBA value"
                    )
            if channel not in {"base_color", "emission", "normal"}:
                if binding.source_kind == "constant" and not isinstance(
                    binding.constant, (float, int)
                ):
                    raise MaterialGraphCompileError(f"{channel} constants require a scalar value")

    def _compile_plan(
        self,
        spec: MaterialGraphSpec,
        graph_spec_path: str,
        graph_spec_sha256: str,
        path_to_id: dict[str, str],
        policy: GraphCompilerPolicy,
    ) -> NormalizedMaterialGraphPlan:
        """Translate portable channels into semantic registry nodes and links only."""

        if len(spec.layers) > policy.maximum_layers:
            raise MaterialGraphCompileError("MaterialGraphSpec exceeds the layer cap")
        channels = self._effective_channels(spec)
        self._validate_supported_policy(spec, channels)
        image_bindings = [item for item in channels.values() if item.image is not None]
        if len(image_bindings) > policy.maximum_textures:
            raise MaterialGraphCompileError("MaterialGraphSpec exceeds the texture cap")

        node_map: dict[str, RuntimeNodePlan] = {
            "principled": RuntimeNodePlan(
                node_id="principled",
                template_id="principled_bsdf",
            ),
            "output": RuntimeNodePlan(node_id="output", template_id="material_output"),
        }
        links: list[RuntimeLinkPlan] = []
        defaults: dict[str, RuntimeInputDefault] = {}
        channel_outputs: dict[str, tuple[str, str]] = {}

        texcoord_needed = bool(image_bindings)
        if texcoord_needed:
            node_map["texcoord"] = RuntimeNodePlan(
                node_id="texcoord", template_id="texture_coordinate"
            )

        for channel in CHANNEL_ORDER:
            binding = channels.get(channel)
            if binding is None or channel == "occlusion":
                continue
            target_socket = {
                "base_color": "base_color",
                "roughness": "roughness",
                "metallic": "metallic",
                "emission": "emission_color",
                "opacity": "alpha",
            }.get(channel)
            if binding.source_kind == "constant":
                if channel == "normal":
                    raise MaterialGraphCompileError("constant normals are unsupported")
                if channel == "height":
                    continue
                value: Any = binding.constant
                if isinstance(value, tuple):
                    value = tuple(float(item) for item in value)
                else:
                    value = float(value)
                if target_socket is not None:
                    defaults[target_socket] = RuntimeInputDefault(
                        socket_id=target_socket,
                        value=value,
                    )
                if channel == "emission":
                    defaults["emission_strength"] = RuntimeInputDefault(
                        socket_id="emission_strength", value=1.0
                    )
                continue

            assert binding.image is not None and binding.physical_scale is not None
            suffix = channel.replace("_", "-")
            mapping_id = f"mapping-{suffix}"
            image_id = f"image-{suffix}"
            node_map[mapping_id] = RuntimeNodePlan(
                node_id=mapping_id,
                template_id="mapping",
                input_defaults=[
                    RuntimeInputDefault(
                        socket_id="scale",
                        value=(
                            1.0 / binding.physical_scale.width_m,
                            1.0 / binding.physical_scale.height_m,
                            1.0,
                        ),
                    )
                ],
            )
            node_map[image_id] = RuntimeNodePlan(
                node_id=image_id,
                template_id="image_texture",
                settings=[
                    RuntimeSetting(
                        setting_id="dependency_id",
                        value=path_to_id[binding.image.path],
                    ),
                    RuntimeSetting(setting_id="color_space", value=binding.color_space),
                    RuntimeSetting(setting_id="sampling", value=binding.sampling),
                ],
            )
            links.extend(
                [
                    RuntimeLinkPlan(
                        link_id=f"link-{len(links) + 1:03d}",
                        source_node_id="texcoord",
                        source_socket_id="uv",
                        target_node_id=mapping_id,
                        target_socket_id="vector",
                    ),
                    RuntimeLinkPlan(
                        link_id=f"link-{len(links) + 2:03d}",
                        source_node_id=mapping_id,
                        source_socket_id="vector",
                        target_node_id=image_id,
                        target_socket_id="vector",
                    ),
                ]
            )
            channel_outputs[channel] = (image_id, "color")

        normal_output: tuple[str, str] | None = None
        if "normal" in channel_outputs:
            normal_map = RuntimeNodePlan(
                node_id="normal-map",
                template_id="normal_map",
                input_defaults=[RuntimeInputDefault(socket_id="strength", value=1.0)],
            )
            node_map[normal_map.node_id] = normal_map
            source_id, source_socket = channel_outputs["normal"]
            links.append(
                RuntimeLinkPlan(
                    link_id=f"link-{len(links) + 1:03d}",
                    source_node_id=source_id,
                    source_socket_id=source_socket,
                    target_node_id=normal_map.node_id,
                    target_socket_id="color",
                )
            )
            normal_output = (normal_map.node_id, "normal")
        if "height" in channel_outputs:
            distance = max(spec.normal_displacement.maximum_displacement_m, 0.001)
            bump = RuntimeNodePlan(
                node_id="bump",
                template_id="bump",
                input_defaults=[
                    RuntimeInputDefault(socket_id="strength", value=1.0),
                    RuntimeInputDefault(socket_id="distance", value=float(distance)),
                ],
            )
            node_map[bump.node_id] = bump
            source_id, source_socket = channel_outputs["height"]
            links.append(
                RuntimeLinkPlan(
                    link_id=f"link-{len(links) + 1:03d}",
                    source_node_id=source_id,
                    source_socket_id=source_socket,
                    target_node_id=bump.node_id,
                    target_socket_id="height",
                )
            )
            if normal_output is not None:
                links.append(
                    RuntimeLinkPlan(
                        link_id=f"link-{len(links) + 1:03d}",
                        source_node_id=normal_output[0],
                        source_socket_id=normal_output[1],
                        target_node_id=bump.node_id,
                        target_socket_id="normal",
                    )
                )
            normal_output = (bump.node_id, "normal")

        for channel in ("base_color", "roughness", "metallic", "emission", "opacity"):
            if channel not in channel_outputs:
                continue
            target_socket = {
                "base_color": "base_color",
                "roughness": "roughness",
                "metallic": "metallic",
                "emission": "emission_color",
                "opacity": "alpha",
            }[channel]
            source_id, source_socket = channel_outputs[channel]
            links.append(
                RuntimeLinkPlan(
                    link_id=f"link-{len(links) + 1:03d}",
                    source_node_id=source_id,
                    source_socket_id=source_socket,
                    target_node_id="principled",
                    target_socket_id=target_socket,
                )
            )
            if channel == "emission":
                defaults["emission_strength"] = RuntimeInputDefault(
                    socket_id="emission_strength", value=1.0
                )
        if normal_output is not None:
            links.append(
                RuntimeLinkPlan(
                    link_id=f"link-{len(links) + 1:03d}",
                    source_node_id=normal_output[0],
                    source_socket_id=normal_output[1],
                    target_node_id="principled",
                    target_socket_id="normal",
                )
            )
        node_map["principled"] = RuntimeNodePlan(
            node_id="principled",
            template_id="principled_bsdf",
            input_defaults=[defaults[key] for key in sorted(defaults)],
        )
        links.append(
            RuntimeLinkPlan(
                link_id=f"link-{len(links) + 1:03d}",
                source_node_id="principled",
                source_socket_id="bsdf",
                target_node_id="output",
                target_socket_id="surface",
            )
        )
        nodes = sorted(node_map.values(), key=lambda item: item.node_id)
        if len(nodes) > policy.maximum_nodes:
            raise MaterialGraphCompileError("compiled graph exceeds the runtime node cap")
        plan = NormalizedMaterialGraphPlan(
            plan_id=f"plan-{graph_spec_sha256[:16]}",
            graph_id=spec.graph_id,
            material_id=spec.material_id,
            graph_spec_path=graph_spec_path,
            graph_spec_sha256=graph_spec_sha256,
            registry_sha256=registry_sha256(),
            policy=policy,
            nodes=nodes,
            links=links,
            topological_order=_canonical_topological_order(nodes, links),
            layer_count=len(spec.layers),
            texture_count=len(image_bindings),
        )
        validate_runtime_plan(plan)
        return plan

    def _build_portable_report(
        self, spec: MaterialGraphSpec, run_id: str
    ) -> PortableMaterialApproximationReport:
        """Describe portable channel meaning without claiming destination shader parity."""

        channels = self._effective_channels(spec)
        findings: list[PortableApproximationFinding] = []
        for channel in CHANNEL_ORDER:
            if channel not in channels:
                continue
            status = "approximated" if channel in {"height", "occlusion"} else "portable"
            if channel == "height":
                message = (
                    "Height is compiled as bounded Blender bump and remains a raw portable channel."
                )
            elif channel == "occlusion":
                message = (
                    "Occlusion remains an exact portable channel because Principled BSDF "
                    "has no direct occlusion input."
                )
            else:
                message = f"{channel} preserves its portable PBR meaning and exact source binding."
            findings.append(
                PortableApproximationFinding(
                    finding_id=f"channel-{channel.replace('_', '-')}",
                    feature=channel,
                    status=status,
                    message=message,
                )
            )
        if spec.bake.required:
            findings.append(
                PortableApproximationFinding(
                    finding_id="bake-deferred",
                    feature="bake_policy",
                    status="approximated",
                    message="The bake contract is preserved but baking is a separate stage.",
                )
            )
        return PortableMaterialApproximationReport(
            report_id=f"portable-{run_id}",
            graph_id=spec.graph_id,
            raw_pbr_channels=[channel for channel in CHANNEL_ORDER if channel in channels],
            findings=findings,
        )

    def prepare_compile(
        self,
        *,
        graph_spec_path: str,
        run_id: str,
        policy: GraphCompilerPolicy | None = None,
    ) -> _PreparedCompile:
        """Validate exact inputs and create deterministic host-side compiler evidence."""

        selected_policy = policy or GraphCompilerPolicy()
        spec, graph_sha = self._load_graph_spec(graph_spec_path)
        dependencies, path_to_id = self._collect_dependencies(spec, graph_spec_path, graph_sha)
        plan = self._compile_plan(
            spec,
            graph_spec_path,
            graph_sha,
            path_to_id,
            selected_policy,
        )
        neutral = MaterialPreviewManifest(
            preview_id=f"neutral-{run_id}",
            graph_id=spec.graph_id,
            scope="neutral_studio",
            rendered=False,
            limitations=["This compiler run does not render the neutral studio preview."],
        )
        reference = spec.preview_lighting.reference_source
        reference_preview = MaterialPreviewManifest(
            preview_id=f"reference-{run_id}",
            graph_id=spec.graph_id,
            scope="reference_matched",
            rendered=False,
            source_reference_path=reference.path,
            source_reference_sha256=reference.sha256,
            limitations=[
                "This compiler run preserves reference binding but does not render "
                "a matched preview."
            ],
        )
        return _PreparedCompile(
            spec=spec,
            plan=plan,
            dependencies=dependencies,
            portable=self._build_portable_report(spec, run_id),
            neutral_preview=neutral,
            reference_preview=reference_preview,
        )

    def _canonical_snapshot(self) -> dict[str, str | None]:
        """Snapshot canonical material and scene bytes to enforce non-mutation."""

        result: dict[str, str | None] = {}
        for relative in (
            "analysis/material_plan.json",
            "analysis/scene_spec.json",
            "blender/scene.blend",
        ):
            path = self.job_root.joinpath(*relative.split("/"))
            result[relative] = (
                _sha256_file(path) if os.path.isfile(native_io_path(path)) else None
            )
        return result

    def _verify_dependencies_current(self, manifest: MaterialGraphDependencyManifest) -> None:
        """Re-hash every dependency after Blender execution to detect source mutation."""

        for dependency in manifest.dependencies:
            actual = _sha256_file(self._resolve_contained_file(dependency.path))
            if actual != dependency.sha256:
                raise MaterialGraphCompileError(
                    f"dependency changed during compilation: {dependency.path}"
                )

    def _verify_report_artifacts(self, staging: Path, report: MaterialGraphCompileReport) -> None:
        """Re-hash all declared runtime outputs before publishing the staging root."""

        for artifact in report.artifacts:
            if (
                "\\" in artifact.path
                or artifact.path.startswith("/")
                or ":" in artifact.path
                or any(part in {"", ".", ".."} for part in artifact.path.split("/"))
            ):
                raise MaterialGraphCompileError(
                    f"compiler report artifact escapes or is missing: {artifact.path}"
                )
            candidate = staging.joinpath(*artifact.path.split("/"))
            current = staging
            for part in artifact.path.split("/"):
                current = current / part
                if _is_link_like(current):
                    raise MaterialGraphCompileError(
                        f"compiler report artifact traverses a symlink: {artifact.path}"
                    )
            if not os.path.isfile(native_io_path(candidate)):
                raise MaterialGraphCompileError(
                    f"compiler report artifact is not a file: {artifact.path}"
                )
            if _sha256_file(candidate) != artifact.sha256:
                raise MaterialGraphCompileError(
                    f"compiler report artifact hash mismatch: {artifact.path}"
                )
            if os.path.getsize(native_io_path(candidate)) != artifact.byte_size:
                raise MaterialGraphCompileError(
                    f"compiler report artifact size mismatch: {artifact.path}"
                )

    def validate_compile_run(
        self,
        *,
        run_root: str,
    ) -> MaterialGraphCompileBundle:
        """Revalidate one published compiler bundle for exact crash-safe adoption."""

        report_path = self._resolve_contained_file(f"{run_root}/compile_report.json")
        final_root = report_path.parent
        try:
            report = MaterialGraphCompileReport.model_validate_json(
                _read_text(report_path)
            )
        except (OSError, ValidationError) as exc:
            raise MaterialGraphCompileError(
                "published MaterialGraph compiler report is invalid"
            ) from exc
        self._verify_report_artifacts(final_root, report)
        artifacts = {item.role: item for item in report.artifacts}
        try:
            request_path = final_root.joinpath(*artifacts["request"].path.split("/"))
            plan_path = final_root.joinpath(*artifacts["normalized_plan"].path.split("/"))
            dependency_path = final_root.joinpath(*artifacts["dependency_manifest"].path.split("/"))
            request = MaterialGraphCompileRequest.model_validate_json(
                _read_text(request_path)
            )
            plan = NormalizedMaterialGraphPlan.model_validate_json(
                _read_text(plan_path)
            )
            dependencies = MaterialGraphDependencyManifest.model_validate_json(
                _read_text(dependency_path)
            )
        except (KeyError, OSError, ValidationError) as exc:
            raise MaterialGraphCompileError(
                "published MaterialGraph compiler bundle is incomplete"
            ) from exc
        if (
            request.request_id != report.request_id
            or request.run_id != report.run_id
            or request.registry_sha256 != report.registry_sha256
            or request.plan_sha256 != report.normalized_plan_sha256
            or plan.registry_sha256 != report.registry_sha256
            or plan.graph_id != report.graph_id
            or plan.material_id != report.material_id
            or not is_supported_registry_sha256(report.registry_sha256)
        ):
            raise MaterialGraphCompileError(
                "published MaterialGraph compiler identity binding is inconsistent"
            )
        if _sha256_file(plan_path) != request.plan_sha256:
            raise MaterialGraphCompileError("published MaterialGraph normalized plan hash changed")
        if _sha256_file(dependency_path) != request.dependency_manifest_sha256:
            raise MaterialGraphCompileError(
                "published MaterialGraph dependency manifest hash changed"
            )
        spec, graph_sha = self._load_graph_spec(plan.graph_spec_path)
        if (
            graph_sha != plan.graph_spec_sha256
            or spec.graph_id != report.graph_id
            or spec.material_id != report.material_id
            or spec.provenance.job_id != report.job_id
            or spec.provenance.workflow_id != report.workflow_id
            or spec.provenance.dispatch_id != report.dispatch_id
        ):
            raise MaterialGraphCompileError(
                "published MaterialGraph compiler source binding is stale"
            )
        validate_runtime_plan(plan)
        self._verify_dependencies_current(dependencies)
        return MaterialGraphCompileBundle(run_root=run_root, report=report)

    def compile_run(
        self,
        *,
        graph_spec_path: str,
        run_root: str,
        run_id: str,
        policy: GraphCompilerPolicy | None = None,
    ) -> MaterialGraphCompileBundle:
        """Compile with Blender 5, reopen inventory, and atomically publish one run."""

        final_root = self._resolve_new_run_root(run_root)
        prepared = self.prepare_compile(
            graph_spec_path=graph_spec_path,
            run_id=run_id,
            policy=policy,
        )
        before = self._canonical_snapshot()
        os.makedirs(native_io_path(final_root.parent), exist_ok=True)
        staging = final_root.parent / f".g-{uuid4().hex[:8]}"
        os.mkdir(native_io_path(staging))
        try:
            plan_sha = _write_json_exclusive(staging / "normalized_plan.json", prepared.plan)
            dependency_sha = _write_json_exclusive(
                staging / "dependency_manifest.json", prepared.dependencies
            )
            _write_json_exclusive(staging / "portable_approximation.json", prepared.portable)
            _write_json_exclusive(
                staging / "neutral_preview_manifest.json", prepared.neutral_preview
            )
            _write_json_exclusive(
                staging / "reference_preview_manifest.json",
                prepared.reference_preview,
            )
            request = MaterialGraphCompileRequest(
                request_id=f"request-{run_id}",
                job_id=prepared.spec.provenance.job_id,
                workflow_id=prepared.spec.provenance.workflow_id,
                dispatch_id=prepared.spec.provenance.dispatch_id,
                run_id=run_id,
                registry_sha256=prepared.plan.registry_sha256,
                plan_path="normalized_plan.json",
                plan_sha256=plan_sha,
                dependency_manifest_path="dependency_manifest.json",
                dependency_manifest_sha256=dependency_sha,
                portable_approximation_path="portable_approximation.json",
                neutral_preview_manifest_path="neutral_preview_manifest.json",
                reference_preview_manifest_path="reference_preview_manifest.json",
                output_blend_path="compiled/material_graph.blend",
                inventory_path="normalized_inventory.json",
                report_path="compile_report.json",
            )
            _write_json_exclusive(staging / "compiler_request.json", request)
            run_blender(
                "compile_material_graph_runtime.py",
                [
                    "--job-root",
                    native_io_path(self.job_root),
                    "--run-root",
                    str(staging),
                    "--request",
                    "compiler_request.json",
                ],
                factory_startup=True,
                disable_autoexec=True,
            )
            report_path = staging / request.report_path
            try:
                report = MaterialGraphCompileReport.model_validate_json(
                    _read_text(report_path)
                )
            except (OSError, ValidationError) as exc:
                raise MaterialGraphCompileError(
                    "Blender compiler did not produce a valid strict report"
                ) from exc
            if report.request_id != request.request_id:
                raise MaterialGraphCompileError("compiler report request binding mismatch")
            if report.normalized_plan_sha256 != plan_sha:
                raise MaterialGraphCompileError("compiler report plan binding mismatch")
            self._verify_report_artifacts(staging, report)
            self._verify_dependencies_current(prepared.dependencies)
            if self._canonical_snapshot() != before:
                raise MaterialGraphCompileError(
                    "canonical material or authoring scene changed during compilation"
                )
            os.rename(native_io_path(staging), native_io_path(final_root))
            return MaterialGraphCompileBundle(run_root=run_root, report=report)
        except Exception:
            shutil.rmtree(native_io_path(staging), ignore_errors=True)
            raise
