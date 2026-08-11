"""Strict runtime compiler contracts derived from MaterialGraphSpec 0.1."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from ..stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId

RUNTIME_SCHEMA_VERSION = "0.1.0"
RuntimeScalar = bool | int | float | str
RuntimeSocketValue = float | tuple[float, float, float] | tuple[float, float, float, float]


class MaterialGraphRuntimeStrictModel(BaseModel):
    """Reject undeclared fields and non-finite values in compiler evidence."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class GraphCompilerPolicy(MaterialGraphRuntimeStrictModel):
    """Bound graph, layer, depth, and texture work below immutable hard limits."""

    policy_id: PortableId = "material_graph_runtime_v1"
    maximum_nodes: int = Field(default=64, ge=2, le=128)
    maximum_layers: int = Field(default=8, ge=0, le=16)
    maximum_depth: int = Field(default=16, ge=1, le=32)
    maximum_textures: int = Field(default=16, ge=0, le=32)


class RuntimeSetting(MaterialGraphRuntimeStrictModel):
    """Assign one typed semantic setting declared by a registry template."""

    setting_id: PortableId
    value: RuntimeScalar


class RuntimeInputDefault(MaterialGraphRuntimeStrictModel):
    """Assign one typed semantic socket default without exposing a Blender socket name."""

    socket_id: PortableId
    value: RuntimeSocketValue


class RuntimeNodePlan(MaterialGraphRuntimeStrictModel):
    """Instantiate one registry-backed node template using semantic controls only."""

    node_id: PortableId
    template_id: PortableId
    settings: list[RuntimeSetting] = Field(default_factory=list)
    input_defaults: list[RuntimeInputDefault] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_controls(self) -> RuntimeNodePlan:
        """Require unique semantic settings and socket defaults per node."""

        setting_ids = [item.setting_id for item in self.settings]
        socket_ids = [item.socket_id for item in self.input_defaults]
        if len(setting_ids) != len(set(setting_ids)):
            raise ValueError("runtime node setting IDs must be unique")
        if len(socket_ids) != len(set(socket_ids)):
            raise ValueError("runtime node input socket IDs must be unique")
        return self


class RuntimeLinkPlan(MaterialGraphRuntimeStrictModel):
    """Connect registry semantic sockets without exposing raw Blender socket identifiers."""

    link_id: PortableId
    source_node_id: PortableId
    source_socket_id: PortableId
    target_node_id: PortableId
    target_socket_id: PortableId

    @model_validator(mode="after")
    def validate_not_self_link(self) -> RuntimeLinkPlan:
        """Reject self-links before topological validation."""

        if self.source_node_id == self.target_node_id:
            raise ValueError("runtime graph self-links are forbidden")
        return self


class NormalizedMaterialGraphPlan(MaterialGraphRuntimeStrictModel):
    """Freeze the deterministic registry plan compiled from one MaterialGraphSpec."""

    schema_version: Literal["0.1.0"] = RUNTIME_SCHEMA_VERSION
    plan_id: PortableId
    graph_id: PortableId
    material_id: str = Field(min_length=1, max_length=128)
    graph_spec_path: RelativePath
    graph_spec_sha256: Sha256
    registry_sha256: Sha256
    policy: GraphCompilerPolicy
    nodes: list[RuntimeNodePlan] = Field(min_length=2)
    links: list[RuntimeLinkPlan] = Field(min_length=1)
    topological_order: list[PortableId] = Field(min_length=2)
    layer_count: int = Field(ge=0)
    texture_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_plan_identities(self) -> NormalizedMaterialGraphPlan:
        """Require unique graph identities and an exact topological node set."""

        node_ids = [item.node_id for item in self.nodes]
        link_ids = [item.link_id for item in self.links]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("runtime graph node IDs must be unique")
        if len(link_ids) != len(set(link_ids)):
            raise ValueError("runtime graph link IDs must be unique")
        if len(self.topological_order) != len(set(self.topological_order)):
            raise ValueError("runtime graph topological order must be unique")
        if set(self.topological_order) != set(node_ids):
            raise ValueError("runtime graph topological order must cover every node exactly")
        if self.layer_count > self.policy.maximum_layers:
            raise ValueError("runtime graph layer count exceeds policy")
        if len(self.nodes) > self.policy.maximum_nodes:
            raise ValueError("runtime graph node count exceeds policy")
        if self.texture_count > self.policy.maximum_textures:
            raise ValueError("runtime graph texture count exceeds policy")
        return self


class GraphDependency(MaterialGraphRuntimeStrictModel):
    """Bind one contained compiler input to exact immutable bytes."""

    dependency_id: PortableId
    role: Literal["graph_spec", "material_plan", "texture", "mask", "reference", "other"]
    path: RelativePath
    sha256: Sha256
    color_space: Literal["sRGB", "Non-Color"] | None = None

    @model_validator(mode="after")
    def validate_color_space(self) -> GraphDependency:
        """Require explicit color space for texture and mask dependencies only."""

        if self.role in {"texture", "mask"} and self.color_space is None:
            raise ValueError("texture and mask dependencies require color_space")
        if self.role not in {"texture", "mask"} and self.color_space is not None:
            raise ValueError("non-image dependencies cannot declare color_space")
        return self


class MaterialGraphDependencyManifest(MaterialGraphRuntimeStrictModel):
    """Enumerate the complete exact dependency set consumed by one compile plan."""

    schema_version: Literal["0.1.0"] = RUNTIME_SCHEMA_VERSION
    manifest_id: PortableId
    job_id: JobId
    graph_id: PortableId
    source_fingerprint: Sha256
    dependencies: list[GraphDependency] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_dependencies(self) -> MaterialGraphDependencyManifest:
        """Require unique dependency IDs and paths with one exact graph specification."""

        identifiers = [item.dependency_id for item in self.dependencies]
        paths = [item.path for item in self.dependencies]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("material graph dependency IDs must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("material graph dependency paths must be unique")
        if sum(item.role == "graph_spec" for item in self.dependencies) != 1:
            raise ValueError("dependency manifest requires exactly one graph_spec")
        if not any(item.role == "material_plan" for item in self.dependencies):
            raise ValueError("dependency manifest requires a material_plan")
        return self


class PortableApproximationFinding(MaterialGraphRuntimeStrictModel):
    """Explain one authoring feature that is portable, approximated, or unsupported."""

    finding_id: PortableId
    feature: PortableId
    status: Literal["portable", "approximated", "unsupported"]
    message: str = Field(min_length=1)


class PortableMaterialApproximationReport(MaterialGraphRuntimeStrictModel):
    """Record portable PBR meaning separately from the Blender master graph."""

    schema_version: Literal["0.1.0"] = RUNTIME_SCHEMA_VERSION
    report_id: PortableId
    graph_id: PortableId
    raw_pbr_channels: list[
        Literal[
            "base_color",
            "roughness",
            "metallic",
            "normal",
            "height",
            "occlusion",
            "emission",
            "opacity",
        ]
    ] = Field(default_factory=list)
    findings: list[PortableApproximationFinding] = Field(default_factory=list)
    destination_runtime_parity_verified: Literal[False] = False

    @model_validator(mode="after")
    def validate_unique_findings(self) -> PortableMaterialApproximationReport:
        """Require unique channels and finding identities."""

        finding_ids = [item.finding_id for item in self.findings]
        if len(self.raw_pbr_channels) != len(set(self.raw_pbr_channels)):
            raise ValueError("portable raw PBR channels must be unique")
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("portable approximation finding IDs must be unique")
        return self


class MaterialPreviewManifest(MaterialGraphRuntimeStrictModel):
    """Keep neutral and reference-matched preview evidence explicitly separate."""

    schema_version: Literal["0.1.0"] = RUNTIME_SCHEMA_VERSION
    preview_id: PortableId
    graph_id: PortableId
    scope: Literal["neutral_studio", "reference_matched"]
    rendered: bool
    image_path: RelativePath | None = None
    image_sha256: Sha256 | None = None
    source_reference_path: RelativePath | None = None
    source_reference_sha256: Sha256 | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_preview_scope(self) -> MaterialPreviewManifest:
        """Require complete image pairs and reference binding only for reference scope."""

        if (self.image_path is None) != (self.image_sha256 is None):
            raise ValueError("preview image path and SHA-256 must be paired")
        if self.rendered != (self.image_path is not None):
            raise ValueError("preview rendered flag must match image evidence")
        source_bound = (
            self.source_reference_path is not None
            and self.source_reference_sha256 is not None
        )
        if (self.source_reference_path is None) != (
            self.source_reference_sha256 is None
        ):
            raise ValueError("preview reference path and SHA-256 must be paired")
        if self.scope == "reference_matched" and not source_bound:
            raise ValueError("reference-matched preview requires exact reference evidence")
        if self.scope == "neutral_studio" and source_bound:
            raise ValueError("neutral preview cannot claim a matched reference")
        if not self.rendered and not self.limitations:
            raise ValueError("an unrendered preview manifest requires a limitation")
        return self


class MaterialGraphCompileRequest(MaterialGraphRuntimeStrictModel):
    """Tell the fixed Blender script which validated run-owned artifacts to compile."""

    schema_version: Literal["0.1.0"] = RUNTIME_SCHEMA_VERSION
    request_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    run_id: PortableId
    registry_sha256: Sha256
    plan_path: RelativePath
    plan_sha256: Sha256
    dependency_manifest_path: RelativePath
    dependency_manifest_sha256: Sha256
    portable_approximation_path: RelativePath
    neutral_preview_manifest_path: RelativePath
    reference_preview_manifest_path: RelativePath
    output_blend_path: RelativePath
    inventory_path: RelativePath
    report_path: RelativePath


class RuntimeArtifact(MaterialGraphRuntimeStrictModel):
    """Bind one run-owned compiler output to exact bytes."""

    role: Literal[
        "request",
        "normalized_plan",
        "dependency_manifest",
        "compiled_blend",
        "normalized_inventory",
        "portable_approximation",
        "neutral_preview_manifest",
        "reference_preview_manifest",
    ]
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(ge=0)


class RuntimeNodeInventory(MaterialGraphRuntimeStrictModel):
    """Identify one reopened Blender node by stable plan and template identity."""

    node_id: PortableId
    template_id: PortableId


class RuntimeLinkInventory(MaterialGraphRuntimeStrictModel):
    """Record one reopened link using only semantic socket identities."""

    link_id: PortableId
    source_node_id: PortableId
    source_socket_id: PortableId
    target_node_id: PortableId
    target_socket_id: PortableId


class NormalizedMaterialNodeInventory(MaterialGraphRuntimeStrictModel):
    """Describe the reopened graph independently from nondeterministic blend bytes."""

    schema_version: Literal["0.1.0"] = RUNTIME_SCHEMA_VERSION
    inventory_id: PortableId
    graph_id: PortableId
    material_id: str = Field(min_length=1, max_length=128)
    registry_sha256: Sha256
    plan_sha256: Sha256
    nodes: list[RuntimeNodeInventory] = Field(min_length=2)
    links: list[RuntimeLinkInventory] = Field(min_length=1)
    principled_socket_resolution: dict[PortableId, str] = Field(default_factory=dict)
    normalized_inventory_sha256: Sha256

    @model_validator(mode="after")
    def validate_inventory_ids(self) -> NormalizedMaterialNodeInventory:
        """Require unique reopened node and link identities."""

        node_ids = [item.node_id for item in self.nodes]
        link_ids = [item.link_id for item in self.links]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("normalized inventory node IDs must be unique")
        if len(link_ids) != len(set(link_ids)):
            raise ValueError("normalized inventory link IDs must be unique")
        return self


class MaterialGraphCompileReport(MaterialGraphRuntimeStrictModel):
    """Bind a reopened Blender compile to normalized deterministic evidence."""

    schema_version: Literal["0.1.0"] = RUNTIME_SCHEMA_VERSION
    report_id: PortableId
    request_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    run_id: PortableId
    graph_id: PortableId
    material_id: str = Field(min_length=1, max_length=128)
    status: Literal["passed"] = "passed"
    ok: Literal[True] = True
    blender_version: str = Field(min_length=1)
    blender_python_version: str = Field(min_length=1)
    registry_sha256: Sha256
    normalized_plan_sha256: Sha256
    normalized_inventory_sha256: Sha256
    artifacts: list[RuntimeArtifact] = Field(min_length=4)
    canonical_material_unchanged: Literal[True] = True
    canonical_scene_unchanged: Literal[True] = True
    blend_bytes_deterministic: Literal[False] = False
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_report_artifacts(self) -> MaterialGraphCompileReport:
        """Require unique artifact roles and paths including blend and normalized inventory."""

        roles = [item.role for item in self.artifacts]
        paths = [item.path for item in self.artifacts]
        if len(roles) != len(set(roles)):
            raise ValueError("material graph compile artifact roles must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("material graph compile artifact paths must be unique")
        required = {
            "request",
            "normalized_plan",
            "dependency_manifest",
            "compiled_blend",
            "normalized_inventory",
            "portable_approximation",
            "neutral_preview_manifest",
            "reference_preview_manifest",
        }
        if set(roles) != required:
            raise ValueError("material graph compile report artifact set is incomplete")
        return self


class MaterialGraphCompileBundle(MaterialGraphRuntimeStrictModel):
    """Return the immutable published compile root and authoritative report."""

    run_root: RelativePath
    report: MaterialGraphCompileReport
