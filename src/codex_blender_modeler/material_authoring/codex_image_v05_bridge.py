"""Bridge validated Codex image staging evidence into immutable V0.5 blueprints.

The bridge is deliberately additive.  It copies exact MaterialAuthoring 0.2.1
channels into a unique run, authors only existing V0.5/MaterialGraph contracts, and
never writes canonical material, geometry, ControllerResult, or Blender evidence.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from ..material_graph.models import (
    BakePolicy,
    ChannelBinding,
    MaterialGraphArtifact,
    MaterialGraphProvenance,
    MaterialGraphSpec,
    NormalDisplacementPolicy,
    PreviewLightingPolicy,
    TextureScale,
)
from ..materials.io import load_shader_recipe
from ..materials.models import (
    MappingSpec,
    MaterialPlan,
    MaterialPlanItem,
    ShaderRecipe,
    SurfaceSpec,
)
from ..materials.validation import validate_material_contracts
from ..models import MaterialSpec, SceneSpec
from ..production.validation import (
    ensure_contained_production_path,
    validate_production_id,
)
from ..texturing.manifest import load_material_manifest
from ..texturing.models import (
    SurfaceDetailBinding,
    SurfaceDetailPlacement,
    TextureChannel,
    TextureManifest,
    TextureProvenance,
)
from .codex_image_adapter import validate_codex_image_material_candidate
from .codex_image_models import (
    CodexImageAuthoredMaterialManifestV021,
    CodexImageChannelDerivationV021,
    CodexImageMaterialAuthoringReceiptV021,
    CodexImageMaterialAuthoringRequestV021,
)
from .codex_image_normalized_adapter import (
    validate_codex_image_normalized_material_candidate,
)
from .codex_image_normalized_models import (
    CodexImageNormalizedAuthoredMaterialManifestV010,
    CodexImageNormalizedMaterialAuthoringReceiptV010,
    CodexImageNormalizedMaterialAuthoringRequestV010,
)
from .models import (
    ExactArtifact,
    MaterialAuthoringStrictModel,
    MaterialFamily,
    PortableId,
    RawPBRChannel,
    RelativePath,
    Sha256,
)

SCHEMA_VERSION = "0.1.0"
_PRODUCER = "codex_blender_modeler.material_authoring.codex_image_v05_bridge"
_PROFILE_ID = "autonomous_static_prop_v2_codex_imagegen"
_PROVIDER_ID = "codex_builtin_gpt_image_v1"
_BRIDGE_ROOT = "material_authoring/codex_imagegen/v05_bridge/runs"
_TEXTURE_MANIFEST_CHANNELS = {
    "base_color",
    "roughness",
    "metallic",
    "normal",
    "height",
    "opacity",
    "emission",
}
_CHANNEL_ORDER = (
    "base_color",
    "roughness",
    "metallic",
    "normal",
    "height",
    "occlusion",
    "emission",
    "opacity",
)
_SourceReceipt = (
    CodexImageMaterialAuthoringReceiptV021 | CodexImageNormalizedMaterialAuthoringReceiptV010
)
_SourceManifest = (
    CodexImageAuthoredMaterialManifestV021 | CodexImageNormalizedAuthoredMaterialManifestV010
)
_SourceRequest = (
    CodexImageMaterialAuthoringRequestV021 | CodexImageNormalizedMaterialAuthoringRequestV010
)

__all__ = [
    "CodexImageV05BridgeChannel",
    "CodexImageV05BridgeReceipt",
    "CodexImageV05CanonicalMaterialAbsence",
    "CodexImageV05ControllerBlueprint",
    "CodexImageV05ControllerInput",
    "SCHEMA_VERSION",
    "build_codex_image_v05_controller_blueprint",
    "publish_codex_image_v05_bridge",
    "publish_codex_image_v05_canonical_material_absence",
    "validate_codex_image_v05_bridge",
]


class CodexImageV05ControllerInput(MaterialAuthoringStrictModel):
    """Alias one exact dependency to an existing material controller input role."""

    role: Literal["scene", "material-baseline", "scale-context"]
    artifact: ExactArtifact


class CodexImageV05CanonicalMaterialAbsence(MaterialAuthoringStrictModel):
    """Record exact observation that no canonical MaterialPlan exists for one session."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    absence_id: PortableId
    job_id: str = Field(min_length=1, max_length=64)
    workflow_id: PortableId
    dispatch_id: PortableId
    session_id: PortableId
    profile_id: Literal["autonomous_static_prop_v2_codex_imagegen"] = _PROFILE_ID
    provider_id: Literal["codex_builtin_gpt_image_v1"] = _PROVIDER_ID
    input_sha256: Sha256
    source_fingerprint: Sha256
    producer: Literal["codex_blender_modeler.material_authoring.codex_image_v05_bridge"] = _PRODUCER
    producer_version: Literal["0.1.0"] = SCHEMA_VERSION
    provenance: list[ExactArtifact] = Field(min_length=1, max_length=1)
    created_at: AwareDatetime
    source_scene_spec: ExactArtifact
    canonical_path: Literal["analysis/material_plan.json"] = "analysis/material_plan.json"
    observed_absent: Literal[True] = True
    canonical_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_absence(self) -> CodexImageV05CanonicalMaterialAbsence:
        """Bind absence identity to the exact canonical SceneSpec and input digest."""

        if self.source_scene_spec.path != "analysis/scene_spec.json":
            raise ValueError("canonical material absence requires canonical SceneSpec")
        if self.source_fingerprint != self.source_scene_spec.sha256:
            raise ValueError("canonical material absence source fingerprint is inconsistent")
        if self.provenance != [self.source_scene_spec]:
            raise ValueError("canonical material absence provenance must be the SceneSpec")
        expected = stable_json_digest(
            {
                "absence_id": self.absence_id,
                "job_id": self.job_id,
                "workflow_id": self.workflow_id,
                "dispatch_id": self.dispatch_id,
                "session_id": self.session_id,
                "profile_id": self.profile_id,
                "provider_id": self.provider_id,
                "source_scene_spec": self.source_scene_spec.model_dump(mode="json"),
                "canonical_path": self.canonical_path,
                "observed_absent": self.observed_absent,
            }
        )
        if self.input_sha256 != expected:
            raise ValueError("canonical material absence input_sha256 is inconsistent")
        return self


class CodexImageV05BridgeChannel(MaterialAuthoringStrictModel):
    """Bind one 0.2.1 channel to its byte-identical run-owned V0.5 dependency."""

    channel: RawPBRChannel
    provenance_kind: Literal[
        "codex_generated_direct",
        "local_deterministic_derivation",
        "local_exact_text_composition",
        "local_constant",
    ]
    algorithm_id: str = Field(min_length=1, max_length=128)
    algorithm_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    source_sha256: list[Sha256] = Field(min_length=1)
    source: ExactArtifact
    adapted: ExactArtifact
    width: int = Field(ge=1, le=4096)
    height: int = Field(ge=1, le=4096)
    color_space: Literal["srgb", "non_color"]
    normal_convention: Literal["opengl_y_plus"] | None = None
    v05_usage: Literal["texture_manifest_and_graph", "material_graph_only"]

    @model_validator(mode="after")
    def validate_bridge_channel(self) -> CodexImageV05BridgeChannel:
        """Preserve exact bytes and forbid generated pseudo-PBR direct channels."""

        if (
            self.source.sha256 != self.adapted.sha256
            or self.source.byte_size != self.adapted.byte_size
            or self.source.media_type != self.adapted.media_type
        ):
            raise ValueError("V0.5 channel adaptation must preserve exact source bytes")
        if self.provenance_kind == "codex_generated_direct" and self.channel not in {
            "base_color",
            "emission",
            "opacity",
        }:
            raise ValueError("Codex-generated bytes cannot directly supply derived PBR")
        expected_space = "srgb" if self.channel in {"base_color", "emission"} else "non_color"
        if self.color_space != expected_space:
            raise ValueError(f"{self.channel} bridge color space must be {expected_space}")
        if (self.channel == "normal") != (self.normal_convention == "opengl_y_plus"):
            raise ValueError("only normal channels may declare the OpenGL +Y convention")
        expected_usage = (
            "texture_manifest_and_graph"
            if self.channel in _TEXTURE_MANIFEST_CHANNELS
            else "material_graph_only"
        )
        if self.v05_usage != expected_usage:
            raise ValueError("V0.5 channel usage differs from the strict manifest surface")
        return self


class CodexImageV05MappingRecipeOverride(MaterialAuthoringStrictModel):
    """Bind one deterministic UV-mapping shader derivative to its stable material ID."""

    material_id: str = Field(min_length=1, max_length=128)
    recipe: ShaderRecipe
    artifact: ExactArtifact

    @model_validator(mode="after")
    def validate_mapping_recipe_override(self) -> CodexImageV05MappingRecipeOverride:
        """Require one UVMap recipe whose exact bytes match the declared artifact."""

        if self.recipe.material_id != self.material_id:
            raise ValueError("mapping recipe override material identity changed")
        if self.recipe.mapping.mode != "uv" or self.recipe.mapping.uv_set != "UVMap":
            raise ValueError("mapping recipe override must use UVMap")
        if self.artifact.sha256 != _sha256_bytes(_model_bytes(self.recipe)):
            raise ValueError("mapping recipe override artifact digest changed")
        return self


class CodexImageV05ControllerBlueprint(MaterialAuthoringStrictModel):
    """Hold deterministic controller-copy models without synthesizing a result."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    blueprint_id: PortableId
    job_id: str = Field(min_length=1, max_length=64)
    workflow_id: PortableId
    dispatch_id: PortableId
    session_id: PortableId
    profile_id: Literal["autonomous_static_prop_v2_codex_imagegen"] = _PROFILE_ID
    provider_id: Literal["codex_builtin_gpt_image_v1"] = _PROVIDER_ID
    input_sha256: Sha256
    source_fingerprint: Sha256
    producer: Literal["codex_blender_modeler.material_authoring.codex_image_v05_bridge"] = _PRODUCER
    producer_version: Literal["0.1.0"] = SCHEMA_VERSION
    provenance: list[ExactArtifact] = Field(min_length=1)
    created_at: AwareDatetime
    bridge_run_id: PortableId
    target_material_id: str = Field(min_length=1, max_length=128)
    mapping_overrides: dict[str, Literal["uv"]] = Field(default_factory=dict)
    mapping_recipe_overrides: list[CodexImageV05MappingRecipeOverride] = Field(default_factory=list)
    run_root: RelativePath
    source_authoring_receipt: ExactArtifact
    source_authoring_request: ExactArtifact
    source_authoring_manifest: ExactArtifact
    source_scene_spec: ExactArtifact
    source_material_plan: ExactArtifact
    previous_canonical_material_plan: ExactArtifact | None = None
    canonical_material_absence_evidence: ExactArtifact | None = None
    baseline_material_plan_snapshot: ExactArtifact
    scale_context: ExactArtifact
    uv_identity: ExactArtifact
    channels: list[CodexImageV05BridgeChannel] = Field(min_length=1)
    texture_manifest: TextureManifest
    texture_manifest_artifact: ExactArtifact
    shader_recipe: ShaderRecipe
    shader_recipe_artifact: ExactArtifact
    material_plan: MaterialPlan
    material_plan_artifact: ExactArtifact
    material_graph: MaterialGraphSpec
    material_graph_artifact: ExactArtifact
    controller_inputs: list[CodexImageV05ControllerInput] = Field(min_length=1)
    expected_output_sha256: dict[RelativePath, Sha256]
    blender_compilation_status: Literal["not_run"] = "not_run"
    neutral_preview_status: Literal["not_run"] = "not_run"
    reference_preview_status: Literal["not_run"] = "not_run"
    canonical_write_authority: Literal["supervisor_only"] = "supervisor_only"
    canonical_write_performed: Literal[False] = False
    destination_write_performed: Literal[False] = False
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_blueprint(self) -> CodexImageV05ControllerBlueprint:
        """Require exact full-plan identity and unique controller dependency paths."""

        channel_names = [item.channel for item in self.channels]
        if len(channel_names) != len(set(channel_names)):
            raise ValueError("bridge channels must be unique")
        input_paths = [item.artifact.path for item in self.controller_inputs]
        if len(input_paths) != len(set(input_paths)):
            raise ValueError("controller bridge inputs must have unique paths")
        if {item.material_id for item in self.mapping_recipe_overrides} != set(
            self.mapping_overrides
        ):
            raise ValueError("mapping recipe overrides differ from mapping scope")
        _validate_material_plan_observation_snapshot(
            self.source_material_plan,
            self.previous_canonical_material_plan,
            self.canonical_material_absence_evidence,
            self.baseline_material_plan_snapshot,
            bridge_run_id=self.bridge_run_id,
        )
        _validate_v05_evidence_envelope(
            job_id=self.job_id,
            workflow_id=self.workflow_id,
            dispatch_id=self.dispatch_id,
            session_id=self.session_id,
            profile_id=self.profile_id,
            provider_id=self.provider_id,
            bridge_run_id=self.bridge_run_id,
            target_material_id=self.target_material_id,
            mapping_overrides=self.mapping_overrides,
            input_sha256=self.input_sha256,
            source_fingerprint=self.source_fingerprint,
            source_authoring_receipt=self.source_authoring_receipt,
            source_material_plan=self.source_material_plan,
            previous_canonical_material_plan=self.previous_canonical_material_plan,
            canonical_material_absence_evidence=(self.canonical_material_absence_evidence),
            controller_inputs=self.controller_inputs,
            expected_output_sha256=self.expected_output_sha256,
            provenance=self.provenance,
        )
        material_ids = {item.material_id for item in self.material_plan.materials}
        if self.target_material_id not in material_ids:
            raise ValueError("controller MaterialPlan omits the target material")
        plan_inputs = [
            item for item in self.material_graph.provenance.inputs if item.role == "material_plan"
        ]
        expected_plan_outputs = [
            (path, digest)
            for path, digest in self.expected_output_sha256.items()
            if PurePosixPath(path).name == "material_plan.json"
        ]
        if len(plan_inputs) != 1 or len(expected_plan_outputs) != 1:
            raise ValueError("bridge graph requires one exact controller MaterialPlan output")
        if (plan_inputs[0].path, plan_inputs[0].sha256) != expected_plan_outputs[0]:
            raise ValueError("bridge graph MaterialPlan output binding is inconsistent")
        return self


class CodexImageV05BridgeReceipt(MaterialAuthoringStrictModel):
    """Bind one published bridge run without claiming controller or Blender success."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    receipt_id: PortableId
    job_id: str = Field(min_length=1, max_length=64)
    workflow_id: PortableId
    dispatch_id: PortableId
    session_id: PortableId
    profile_id: Literal["autonomous_static_prop_v2_codex_imagegen"] = _PROFILE_ID
    provider_id: Literal["codex_builtin_gpt_image_v1"] = _PROVIDER_ID
    input_sha256: Sha256
    source_fingerprint: Sha256
    producer: Literal["codex_blender_modeler.material_authoring.codex_image_v05_bridge"] = _PRODUCER
    producer_version: Literal["0.1.0"] = SCHEMA_VERSION
    provenance: list[ExactArtifact] = Field(min_length=1)
    created_at: AwareDatetime
    bridge_run_id: PortableId
    target_material_id: str = Field(min_length=1, max_length=128)
    mapping_overrides: dict[str, Literal["uv"]] = Field(default_factory=dict)
    mapping_recipe_overrides: list[CodexImageV05MappingRecipeOverride] = Field(default_factory=list)
    material_family: MaterialFamily
    source_authoring_receipt: ExactArtifact
    source_authoring_request: ExactArtifact
    source_authoring_manifest: ExactArtifact
    source_scene_spec: ExactArtifact
    source_material_plan: ExactArtifact
    previous_canonical_material_plan: ExactArtifact | None = None
    canonical_material_absence_evidence: ExactArtifact | None = None
    baseline_material_plan_snapshot: ExactArtifact
    scale_context: ExactArtifact
    uv_identity: ExactArtifact
    channels: list[CodexImageV05BridgeChannel] = Field(min_length=1)
    texture_manifest: ExactArtifact
    shader_recipe: ExactArtifact
    candidate_material_plan: ExactArtifact
    candidate_material_graph: ExactArtifact
    controller_inputs: list[CodexImageV05ControllerInput] = Field(min_length=1)
    expected_output_sha256: dict[RelativePath, Sha256]
    status: Literal["controller_candidate_ready"] = "controller_candidate_ready"
    staging_only: Literal[True] = True
    canonical_v05_unchanged: Literal[True] = True
    canonical_scene_unchanged: Literal[True] = True
    blender_compilation_status: Literal["not_run"] = "not_run"
    neutral_preview_status: Literal["not_run"] = "not_run"
    reference_preview_status: Literal["not_run"] = "not_run"
    controller_result_created: Literal[False] = False
    canonical_write_performed: Literal[False] = False
    destination_write_performed: Literal[False] = False
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_receipt(self) -> CodexImageV05BridgeReceipt:
        """Require unique output and input paths with exact expected blueprint hashes."""

        outputs = [
            self.baseline_material_plan_snapshot,
            *[item.adapted for item in self.channels],
            *[item.artifact for item in self.mapping_recipe_overrides],
            self.texture_manifest,
            self.shader_recipe,
            self.candidate_material_plan,
            self.candidate_material_graph,
        ]
        paths = [item.path for item in outputs]
        if len(paths) != len(set(paths)):
            raise ValueError("published V0.5 bridge output paths must be unique")
        input_paths = [item.artifact.path for item in self.controller_inputs]
        if len(input_paths) != len(set(input_paths)):
            raise ValueError("published controller input paths must be unique")
        if {item.material_id for item in self.mapping_recipe_overrides} != set(
            self.mapping_overrides
        ):
            raise ValueError("mapping recipe overrides differ from mapping scope")
        _validate_material_plan_observation_snapshot(
            self.source_material_plan,
            self.previous_canonical_material_plan,
            self.canonical_material_absence_evidence,
            self.baseline_material_plan_snapshot,
            bridge_run_id=self.bridge_run_id,
        )
        _validate_v05_evidence_envelope(
            job_id=self.job_id,
            workflow_id=self.workflow_id,
            dispatch_id=self.dispatch_id,
            session_id=self.session_id,
            profile_id=self.profile_id,
            provider_id=self.provider_id,
            bridge_run_id=self.bridge_run_id,
            target_material_id=self.target_material_id,
            mapping_overrides=self.mapping_overrides,
            input_sha256=self.input_sha256,
            source_fingerprint=self.source_fingerprint,
            source_authoring_receipt=self.source_authoring_receipt,
            source_material_plan=self.source_material_plan,
            previous_canonical_material_plan=self.previous_canonical_material_plan,
            canonical_material_absence_evidence=(self.canonical_material_absence_evidence),
            controller_inputs=self.controller_inputs,
            expected_output_sha256=self.expected_output_sha256,
            provenance=self.provenance,
        )
        expected_hashes = set(self.expected_output_sha256.values())
        if self.candidate_material_plan.sha256 not in expected_hashes:
            raise ValueError("expected controller outputs omit candidate MaterialPlan hash")
        if self.candidate_material_graph.sha256 not in expected_hashes:
            raise ValueError("expected controller outputs omit candidate MaterialGraph hash")
        return self


def _artifact_identity(artifact: ExactArtifact) -> tuple[str, str, str, str, int, str]:
    """Return the complete immutable identity of one material-authoring artifact."""

    return (
        artifact.artifact_id,
        artifact.kind,
        artifact.path,
        artifact.sha256,
        artifact.byte_size,
        artifact.media_type,
    )


def _as_exact_artifact(artifact: object) -> ExactArtifact:
    """Convert a structurally identical companion artifact without changing identity."""

    if isinstance(artifact, ExactArtifact):
        return artifact
    if not hasattr(artifact, "model_dump"):
        raise TypeError("source evidence contains an unexpected artifact value")
    return ExactArtifact.model_validate(artifact.model_dump(mode="python"))


def _validate_material_plan_observation_snapshot(
    source: ExactArtifact,
    previous: ExactArtifact | None,
    absence: ExactArtifact | None,
    snapshot: ExactArtifact,
    *,
    bridge_run_id: str,
) -> None:
    """Separate the mutable canonical observation from its immutable baseline copy."""

    if (previous is None) == (absence is None):
        raise ValueError("declare exactly one previous canonical MaterialPlan or absence evidence")
    if source.kind != "v05-material-plan":
        raise ValueError("source MaterialPlan observation has an unexpected kind")
    expected_snapshot_path = f"{_BRIDGE_ROOT}/{bridge_run_id}/source/baseline_material_plan.json"
    if (
        snapshot.kind != "v05-material-plan-baseline-snapshot"
        or snapshot.path != expected_snapshot_path
    ):
        raise ValueError("baseline MaterialPlan snapshot is not run-owned")
    if (
        snapshot.sha256,
        snapshot.byte_size,
        snapshot.media_type,
    ) != (
        source.sha256,
        source.byte_size,
        source.media_type,
    ):
        raise ValueError("baseline MaterialPlan snapshot differs from its source observation")
    if previous is not None:
        if source.path != "analysis/material_plan.json":
            raise ValueError("source MaterialPlan observation is not canonical")
        if previous != snapshot:
            raise ValueError("previous MaterialPlan must use the immutable baseline snapshot")
    elif source.path == "analysis/material_plan.json":
        raise ValueError("absence mode cannot observe a canonical source MaterialPlan")
    if absence is not None and absence.kind != "canonical-material-plan-absence":
        raise ValueError("canonical MaterialPlan absence evidence has an unexpected kind")


def _v05_evidence_payload(
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    profile_id: str,
    provider_id: str,
    bridge_run_id: str,
    target_material_id: str,
    mapping_overrides: dict[str, Literal["uv"]] | None = None,
    source_authoring_receipt: ExactArtifact,
    source_material_plan: ExactArtifact,
    previous_canonical_material_plan: ExactArtifact | None,
    canonical_material_absence_evidence: ExactArtifact | None,
    controller_inputs: list[CodexImageV05ControllerInput],
    expected_output_sha256: dict[str, str],
) -> dict[str, object]:
    """Build the stable complete input payload shared by blueprint and receipt."""

    payload = {
        "job_id": job_id,
        "workflow_id": workflow_id,
        "dispatch_id": dispatch_id,
        "session_id": session_id,
        "profile_id": profile_id,
        "provider_id": provider_id,
        "bridge_run_id": bridge_run_id,
        "target_material_id": target_material_id,
        "source_authoring_receipt": source_authoring_receipt.model_dump(mode="json"),
        "source_material_plan": source_material_plan.model_dump(mode="json"),
        "previous_canonical_material_plan": (
            previous_canonical_material_plan.model_dump(mode="json")
            if previous_canonical_material_plan is not None
            else None
        ),
        "canonical_material_absence_evidence": (
            canonical_material_absence_evidence.model_dump(mode="json")
            if canonical_material_absence_evidence is not None
            else None
        ),
        "controller_inputs": [item.model_dump(mode="json") for item in controller_inputs],
        "expected_output_sha256": dict(sorted(expected_output_sha256.items())),
    }
    if mapping_overrides:
        payload["mapping_overrides"] = dict(sorted(mapping_overrides.items()))
    return payload


def _validate_v05_evidence_envelope(
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    profile_id: str,
    provider_id: str,
    bridge_run_id: str,
    target_material_id: str,
    mapping_overrides: dict[str, Literal["uv"]] | None = None,
    input_sha256: str,
    source_fingerprint: str,
    source_authoring_receipt: ExactArtifact,
    source_material_plan: ExactArtifact,
    previous_canonical_material_plan: ExactArtifact | None,
    canonical_material_absence_evidence: ExactArtifact | None,
    controller_inputs: list[CodexImageV05ControllerInput],
    expected_output_sha256: dict[str, str],
    provenance: list[ExactArtifact],
) -> None:
    """Recalculate identity digests and require complete unique exact provenance."""

    expected_input = stable_json_digest(
        _v05_evidence_payload(
            job_id=job_id,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            session_id=session_id,
            profile_id=profile_id,
            provider_id=provider_id,
            bridge_run_id=bridge_run_id,
            target_material_id=target_material_id,
            mapping_overrides=mapping_overrides,
            source_authoring_receipt=source_authoring_receipt,
            source_material_plan=source_material_plan,
            previous_canonical_material_plan=previous_canonical_material_plan,
            canonical_material_absence_evidence=canonical_material_absence_evidence,
            controller_inputs=controller_inputs,
            expected_output_sha256=expected_output_sha256,
        )
    )
    if input_sha256 != expected_input:
        raise ValueError("V0.5 bridge input_sha256 is inconsistent")
    if source_fingerprint != source_authoring_receipt.sha256:
        raise ValueError("V0.5 bridge source fingerprint must equal the source receipt")
    expected: dict[str, ExactArtifact] = {}
    for artifact in (
        source_authoring_receipt,
        *[item.artifact for item in controller_inputs],
        *(
            [previous_canonical_material_plan]
            if previous_canonical_material_plan is not None
            else []
        ),
        *(
            [canonical_material_absence_evidence]
            if canonical_material_absence_evidence is not None
            else []
        ),
    ):
        current = expected.get(artifact.path)
        if current is not None and _artifact_identity(current) != _artifact_identity(artifact):
            raise ValueError(f"V0.5 bridge provenance metadata conflicts: {artifact.path}")
        expected[artifact.path] = artifact
    observed = {artifact.path: artifact for artifact in provenance}
    if len(observed) != len(provenance):
        raise ValueError("V0.5 bridge provenance paths must be unique")
    if {path: _artifact_identity(artifact) for path, artifact in observed.items()} != {
        path: _artifact_identity(artifact) for path, artifact in expected.items()
    }:
        raise ValueError("V0.5 bridge provenance is incomplete or contains extras")


def _model_bytes(value: object) -> bytes:
    """Serialize one strict model using stable human-readable UTF-8 JSON bytes."""

    payload = (
        value.model_dump(mode="json", exclude_none=True) if hasattr(value, "model_dump") else value
    )
    return (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def _sha256_bytes(value: bytes) -> str:
    """Hash one in-memory publication payload without writing a temporary file."""

    import hashlib

    return hashlib.sha256(value).hexdigest()


def _artifact_id(label: str, path: str, digest: str) -> str:
    """Create one short portable artifact ID from stable role, path, and digest."""

    import hashlib

    suffix = hashlib.sha256(f"{path}:{digest}".encode()).hexdigest()[:16]
    return f"v05-{label}-{suffix}"


def _exact_artifact_for_bytes(
    *,
    path: str,
    payload: bytes,
    kind: str,
    media_type: str,
    label: str,
) -> ExactArtifact:
    """Describe deterministic future bytes as one exact job-contained artifact."""

    digest = _sha256_bytes(payload)
    return ExactArtifact(
        artifact_id=_artifact_id(label, path, digest),
        kind=kind,
        path=path,
        sha256=digest,
        byte_size=len(payload),
        media_type=media_type,
    )


def _exact_artifact_for_file(
    root: Path,
    path: Path,
    *,
    kind: str,
    media_type: str,
    label: str,
) -> ExactArtifact:
    """Rehash one exact contained file into MaterialAuthoring artifact metadata."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    if not os.path.isfile(native_io_path(safe)):
        raise ValueError(f"V0.5 bridge dependency must be a regular file: {safe.name}")
    relative = safe.relative_to(root).as_posix()
    digest = sha256_file(safe)
    size = os.path.getsize(native_io_path(safe))
    if size <= 0:
        raise ValueError(f"V0.5 bridge dependency is empty: {relative}")
    return ExactArtifact(
        artifact_id=_artifact_id(label, relative, digest),
        kind=kind,
        path=relative,
        sha256=digest,
        byte_size=size,
        media_type=media_type,
    )


def _validate_exact_artifact(root: Path, artifact: ExactArtifact) -> Path:
    """Reject missing, resized, linked, or rehashed bridge evidence."""

    safe = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
    if not os.path.isfile(native_io_path(safe)):
        raise ValueError(f"bridge artifact must be a regular file: {artifact.path}")
    if os.path.getsize(native_io_path(safe)) != artifact.byte_size:
        raise ValueError(f"bridge artifact byte size changed: {artifact.path}")
    if sha256_file(safe) != artifact.sha256:
        raise ValueError(f"bridge artifact hash changed: {artifact.path}")
    return safe


def _read_exact_model(root: Path, artifact: ExactArtifact, model_type: type[object]) -> object:
    """Rehash and parse one exact JSON artifact using its strict model type."""

    path = _validate_exact_artifact(root, artifact)
    return model_type.model_validate_json(path.read_bytes())  # type: ignore[attr-defined]


def publish_codex_image_v05_canonical_material_absence(
    job_root: Path,
    *,
    absence_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    source_scene_spec: ExactArtifact,
    created_at: datetime | None = None,
) -> ExactArtifact:
    """Publish run-owned exact absence evidence without creating canonical material state."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    validated_absence_id = validate_production_id(absence_id, "absence_id")
    validated_dispatch_id = validate_production_id(dispatch_id, "dispatch_id")
    validated_session_id = validate_production_id(session_id, "session_id")
    scene_path = _validate_exact_artifact(root, source_scene_spec)
    scene = SceneSpec.model_validate_json(scene_path.read_bytes())
    if scene.job_id != job_id or source_scene_spec.path != "analysis/scene_spec.json":
        raise ValueError("canonical material absence SceneSpec identity differs")
    source_scene_spec = _exact_artifact_for_file(
        root,
        scene_path,
        kind="scene-spec",
        media_type="application/json",
        label="scene-spec",
    )
    canonical = ensure_contained_production_path(
        root,
        root / "analysis" / "material_plan.json",
        must_exist=False,
    )
    if os.path.exists(native_io_path(canonical)):
        raise ValueError("canonical MaterialPlan exists; absence cannot be recorded")
    payload = {
        "absence_id": validated_absence_id,
        "job_id": job_id,
        "workflow_id": workflow_id,
        "dispatch_id": validated_dispatch_id,
        "session_id": validated_session_id,
        "profile_id": _PROFILE_ID,
        "provider_id": _PROVIDER_ID,
        "source_scene_spec": source_scene_spec.model_dump(mode="json"),
        "canonical_path": "analysis/material_plan.json",
        "observed_absent": True,
    }
    evidence = CodexImageV05CanonicalMaterialAbsence(
        absence_id=validated_absence_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=validated_dispatch_id,
        session_id=validated_session_id,
        input_sha256=stable_json_digest(payload),
        source_fingerprint=source_scene_spec.sha256,
        provenance=[source_scene_spec],
        created_at=created_at or datetime.now(UTC),
        source_scene_spec=source_scene_spec,
    )
    destination = ensure_contained_production_path(
        root,
        root
        / "material_authoring"
        / "codex_imagegen"
        / "v05_bridge"
        / "absence"
        / f"{validated_absence_id}.json",
        must_exist=False,
    )
    if os.path.exists(native_io_path(destination)):
        raise FileExistsError("canonical MaterialPlan absence evidence already exists")
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    _write_exclusive(destination, _model_bytes(evidence))
    return _exact_artifact_for_file(
        root,
        destination,
        kind="canonical-material-plan-absence",
        media_type="application/json",
        label="material-absence",
    )


def _validate_canonical_material_absence_artifact(
    root: Path,
    artifact: ExactArtifact,
    *,
    request: CodexImageMaterialAuthoringRequestV021,
    scene_artifact: ExactArtifact,
    dispatch_id: str,
    session_id: str,
    promoted_material_plan_sha256: str | None = None,
) -> None:
    """Replay absence, allowing only the exact expected host-promoted candidate later."""

    evidence = cast(
        CodexImageV05CanonicalMaterialAbsence,
        _read_exact_model(root, artifact, CodexImageV05CanonicalMaterialAbsence),
    )
    if artifact.kind != "canonical-material-plan-absence":
        raise ValueError("canonical MaterialPlan absence evidence has an unexpected kind")
    if (
        evidence.job_id != request.job_id
        or evidence.workflow_id != request.workflow_id
        or evidence.dispatch_id != dispatch_id
        or evidence.session_id != session_id
        or evidence.source_scene_spec != scene_artifact
    ):
        raise ValueError("canonical MaterialPlan absence identity differs from the bridge")
    canonical = ensure_contained_production_path(
        root,
        root / evidence.canonical_path,
        must_exist=False,
    )
    if os.path.exists(native_io_path(canonical)) and (
        promoted_material_plan_sha256 is None
        or sha256_file(canonical) != promoted_material_plan_sha256
    ):
        raise ValueError("canonical MaterialPlan appeared outside the expected promotion")


def _validate_output_paths(
    root: Path,
    material_plan_output_path: str,
    material_graph_output_path: str,
) -> None:
    """Require distinct non-canonical controller output names below one directory."""

    path_adapter = TypeAdapter(RelativePath)
    plan_relative = path_adapter.validate_python(material_plan_output_path)
    graph_relative = path_adapter.validate_python(material_graph_output_path)
    plan = PurePosixPath(plan_relative)
    graph = PurePosixPath(graph_relative)
    if plan.name != "material_plan.json" or graph.name != "material_graph.json":
        raise ValueError("controller V0.5 outputs must be material_plan.json/material_graph.json")
    if plan.parent != graph.parent or plan == graph:
        raise ValueError("controller V0.5 outputs must share one distinct output root")
    if material_plan_output_path == "analysis/material_plan.json":
        raise ValueError("controller blueprint cannot target the canonical MaterialPlan")
    for value in (material_plan_output_path, material_graph_output_path):
        ensure_contained_production_path(root, root / value, must_exist=False)


def _source_receipt_artifact(
    root: Path,
    request: _SourceRequest,
) -> ExactArtifact:
    """Bind the published legacy or normalized receipt at its immutable run root."""

    return _exact_artifact_for_file(
        root,
        root / request.output_root / "receipt.json",
        kind=(
            "codex-image-normalized-material-authoring-receipt"
            if isinstance(request, CodexImageNormalizedMaterialAuthoringRequestV010)
            else "codex-image-material-authoring-receipt-v021"
        ),
        media_type="application/json",
        label="source-receipt",
    )


def _load_core_adoption(
    root: Path,
    request: CodexImageMaterialAuthoringRequestV021,
) -> object:
    """Load the already-validated adoption to recover exact session/profile identity."""

    from ..codex_imagegen.models import ImageToMaterialAdoption

    return _read_exact_model(root, request.core_evidence.adoption, ImageToMaterialAdoption)


def _validate_promoted_source_replay(
    root: Path,
    *,
    receipt: _SourceReceipt,
    source_request: _SourceRequest,
    manifest: _SourceManifest,
    baseline_artifact: ExactArtifact,
    baseline_snapshot: ExactArtifact,
) -> None:
    """Replay immutable 0.2.1 evidence after the observed canonical baseline was promoted."""

    published_receipt = cast(
        _SourceReceipt,
        _read_exact_model(
            root,
            _source_receipt_artifact(root, source_request),
            type(receipt),
        ),
    )
    if published_receipt != receipt:
        raise ValueError("source receipt differs from its immutable published bytes")
    if _as_exact_artifact(manifest.request) != _as_exact_artifact(receipt.request):
        raise ValueError("source manifest request differs from the source receipt")
    if sorted(receipt.outputs, key=lambda item: item.path) != sorted(
        (item.output for item in manifest.channels),
        key=lambda item: item.path,
    ):
        raise ValueError("source manifest outputs differ from the source receipt")
    for field in ("job_id", "workflow_id", "run_id"):
        if getattr(source_request, field) != getattr(receipt, field) or getattr(
            manifest, field
        ) != getattr(receipt, field):
            raise ValueError(f"source {field} differs across immutable staging evidence")
    if (
        baseline_artifact.sha256,
        baseline_artifact.byte_size,
        baseline_artifact.media_type,
    ) != (
        baseline_snapshot.sha256,
        baseline_snapshot.byte_size,
        baseline_snapshot.media_type,
    ):
        raise ValueError("promoted replay baseline snapshot identity changed")
    for artifact in receipt.outputs:
        _validate_exact_artifact(root, artifact)


def _load_source_bundle(
    root: Path,
    receipt: _SourceReceipt,
    *,
    canonical_material_absent: bool,
    baseline_snapshot_artifact: ExactArtifact | None = None,
    promoted_material_plan_sha256: str | None = None,
) -> tuple[
    CodexImageMaterialAuthoringRequestV021,
    CodexImageAuthoredMaterialManifestV021,
    SceneSpec,
    ExactArtifact,
    MaterialPlan,
    bool,
    _SourceRequest,
]:
    """Load staging while distinguishing current CAS state from promoted replay."""

    if isinstance(receipt, CodexImageNormalizedMaterialAuthoringReceiptV010):
        source_request = cast(
            CodexImageNormalizedMaterialAuthoringRequestV010,
            _read_exact_model(
                root,
                _as_exact_artifact(receipt.request),
                CodexImageNormalizedMaterialAuthoringRequestV010,
            ),
        )
        manifest = cast(
            CodexImageNormalizedAuthoredMaterialManifestV010,
            _read_exact_model(
                root,
                _as_exact_artifact(receipt.manifest),
                CodexImageNormalizedAuthoredMaterialManifestV010,
            ),
        )
        request = source_request.base_request.model_copy(
            update={"source": source_request.effective_source}
        )
    else:
        source_request = cast(
            CodexImageMaterialAuthoringRequestV021,
            _read_exact_model(
                root,
                receipt.request,
                CodexImageMaterialAuthoringRequestV021,
            ),
        )
        request = source_request
        manifest = cast(
            CodexImageAuthoredMaterialManifestV021,
            _read_exact_model(
                root,
                receipt.manifest,
                CodexImageAuthoredMaterialManifestV021,
            ),
        )
    scene_path = ensure_contained_production_path(
        root, root / "analysis" / "scene_spec.json", must_exist=True
    )
    scene = SceneSpec.model_validate_json(scene_path.read_bytes())
    if scene.job_id != request.job_id:
        raise ValueError("current SceneSpec job_id differs from image material staging")
    target_objects = [item for item in scene.objects if item.material_id == request.material_id]
    if request.material_id not in {item.id for item in scene.materials} or not target_objects:
        raise ValueError("image material target must exist and be used by current SceneSpec")
    if request.uv_identity.uv_set != "UVMap":
        raise ValueError("Codex image V0.5 bridge requires exact UVMap identity")
    if request.uv_identity.semantic_id not in {item.id for item in target_objects}:
        raise ValueError("UV identity semantic_id does not use the target material")
    if any(channel.uv_identity != request.uv_identity for channel in manifest.channels):
        raise ValueError("staged material channels do not share the exact UV identity")
    baseline_artifacts = [
        item for item in request.source_v05_contracts if item.kind == "v05-material-plan"
    ]
    if len(baseline_artifacts) != 1:
        raise ValueError("V0.5 bridge requires exactly one source MaterialPlan")
    baseline_artifact = baseline_artifacts[0]
    if not canonical_material_absent and baseline_artifact.path != "analysis/material_plan.json":
        raise ValueError("V0.5 bridge baseline must be the current canonical MaterialPlan")
    canonical_path = ensure_contained_production_path(
        root,
        root / "analysis" / "material_plan.json",
        must_exist=False,
    )
    canonical_exists = os.path.isfile(native_io_path(canonical_path))
    canonical_sha256 = sha256_file(canonical_path) if canonical_exists else None
    source_is_current = (
        not canonical_material_absent
        and canonical_sha256 == baseline_artifact.sha256
        and baseline_artifact.path == "analysis/material_plan.json"
    ) or (canonical_material_absent and not canonical_exists)
    promoted = (
        promoted_material_plan_sha256 is not None
        and canonical_sha256 == promoted_material_plan_sha256
        and not source_is_current
    )
    if not source_is_current and not promoted:
        raise ValueError("canonical MaterialPlan differs from both baseline and promotion")
    if baseline_snapshot_artifact is None:
        if promoted:
            raise ValueError("promoted replay requires the immutable baseline snapshot")
        manifest = (
            validate_codex_image_normalized_material_candidate(root, receipt)
            if isinstance(receipt, CodexImageNormalizedMaterialAuthoringReceiptV010)
            else validate_codex_image_material_candidate(root, receipt)
        )
        baseline_path = _validate_exact_artifact(root, baseline_artifact)
    else:
        snapshot_path = _validate_exact_artifact(root, baseline_snapshot_artifact)
        if (
            baseline_snapshot_artifact.sha256,
            baseline_snapshot_artifact.byte_size,
            baseline_snapshot_artifact.media_type,
        ) != (
            baseline_artifact.sha256,
            baseline_artifact.byte_size,
            baseline_artifact.media_type,
        ):
            raise ValueError("baseline snapshot differs from the source MaterialPlan")
        if source_is_current:
            manifest = (
                validate_codex_image_normalized_material_candidate(
                    root,
                    receipt,
                    source_v05_contract_overrides=[baseline_snapshot_artifact],
                )
                if isinstance(receipt, CodexImageNormalizedMaterialAuthoringReceiptV010)
                else validate_codex_image_material_candidate(root, receipt)
            )
        else:
            if isinstance(receipt, CodexImageNormalizedMaterialAuthoringReceiptV010):
                manifest = validate_codex_image_normalized_material_candidate(
                    root,
                    receipt,
                    source_v05_contract_overrides=[baseline_snapshot_artifact],
                )
            else:
                _validate_promoted_source_replay(
                    root,
                    receipt=receipt,
                    source_request=source_request,
                    manifest=manifest,
                    baseline_artifact=baseline_artifact,
                    baseline_snapshot=baseline_snapshot_artifact,
                )
        baseline_path = snapshot_path
    baseline = cast(
        MaterialPlan,
        MaterialPlan.model_validate_json(baseline_path.read_bytes()),
    )
    scene_ids = {item.id for item in scene.materials}
    baseline_ids = {item.material_id for item in baseline.materials}
    if baseline.job_id != scene.job_id or baseline.scene_spec_path != "analysis/scene_spec.json":
        raise ValueError("source MaterialPlan identity differs from current SceneSpec")
    if not baseline_ids <= scene_ids:
        raise ValueError("source MaterialPlan contains IDs outside current SceneSpec")
    return (
        request,
        manifest,
        scene,
        baseline_artifact,
        baseline,
        promoted,
        source_request,
    )


def _scene_shader_family(material: MaterialSpec) -> str:
    """Map one canonical SceneSpec shader to its existing V0.5 family."""

    return {
        "principled": "standard_pbr",
        "water": "water",
        "glass": "glass",
        "emissive": "emissive",
        "cloud": "cloud",
    }[material.shader]


def _target_shader_family(family: MaterialFamily) -> str:
    """Choose only an existing portable V0.5 family for the image target."""

    return {
        "uniform_fallback": "standard_pbr",
        "user_image_pbr": "standard_pbr",
        "signage_decal": "standard_pbr",
        "planar_reference_patch": "standard_pbr",
        "wood": "standard_pbr",
        "metal": "standard_pbr",
        "emissive": "emissive",
        "crystal": "glass",
    }[family]


def _mapping(request: CodexImageMaterialAuthoringRequestV021) -> MappingSpec:
    """Derive physical UV mapping from exact staging scale and UV evidence."""

    return MappingSpec(
        mode="uv",
        uv_set=request.uv_identity.uv_set,
        real_world_scale_m=request.scale_context.longest_dimension_m,
        texel_density_px_m=request.uv_identity.texel_density_px_m,
    )


def _surface(
    scene_material: MaterialSpec,
    request: CodexImageMaterialAuthoringRequestV021,
    channels: set[str],
) -> SurfaceSpec:
    """Preserve SceneSpec surface intent while exposing bounded family approximations."""

    is_crystal = request.material_family == "crystal"
    is_emissive = request.material_family == "emissive" or "emission" in channels
    return SurfaceSpec(
        base_color=scene_material.base_color,
        metallic=scene_material.metallic,
        roughness=request.base_roughness,
        ior=1.45,
        transmission_weight=1.0 if is_crystal else 0.0,
        alpha=scene_material.base_color[3],
        emission_color=(scene_material.base_color if is_emissive else (0.0, 0.0, 0.0, 1.0)),
        emission_strength=request.emission_strength if is_emissive else 0.0,
    )


def _family_limitations(
    request: CodexImageMaterialAuthoringRequestV021,
    source_channels: list[CodexImageChannelDerivationV021],
    channel_names: set[str],
) -> list[str]:
    """Describe current whitelist and portable losses without asserting execution."""

    direct = sorted(
        channel.channel
        for channel in source_channels
        if channel.provenance_kind == "codex_generated_direct"
    )
    limitations = [
        "Blender compilation and neutral/reference previews have not run.",
        "Codex-generated bytes directly drive only "
        f"{direct}; all other PBR channels retain local deterministic provenance.",
        "ControllerExecutor must exact-copy the plan and graph blueprints and the host "
        "material promotion service must validate, compile, rebuild, and promote them.",
    ]
    if "occlusion" in channel_names:
        limitations.append(
            "Strict V0.5 TextureManifest has no occlusion field; exact occlusion remains "
            "a MaterialGraph-only raw channel and is not claimed as Principled parity."
        )
    if request.material_family == "signage_decal":
        limitations.append(
            "Signage is a UV-clipped portable image approximation; exact glyph evidence "
            "does not imply destination typography parity."
        )
    elif request.material_family == "emissive":
        limitations.append(
            "Emission texture meaning is portable, but bloom and exposure are renderer-owned."
        )
    elif request.material_family == "crystal":
        limitations.append(
            "Crystal uses the existing glass/transmission approximation; refraction, volume, "
            "dispersion, and destination shader parity remain unverified."
        )
    elif request.material_family == "wood":
        limitations.append(
            "Wood relief remains bounded tangent normal/bump evidence, not recovered geometry."
        )
    return limitations


def _media_type(path: str) -> str:
    """Infer only the bounded media types used by immutable material dependencies."""

    suffix = PurePosixPath(path).suffix.casefold()
    return {
        ".json": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")


def _channel_records(
    manifest: _SourceManifest,
    run_root: str,
) -> list[CodexImageV05BridgeChannel]:
    """Plan byte-identical channel copies with explicit V0.5 usage and provenance."""

    records: list[CodexImageV05BridgeChannel] = []
    output_paths: set[str] = set()
    source_paths: set[str] = set()
    dimensions: set[tuple[int, int]] = set()
    for source in sorted(manifest.channels, key=lambda item: _CHANNEL_ORDER.index(item.channel)):
        adapted_path = f"{run_root}/channels/{source.channel}.png"
        if source.output.path in source_paths or adapted_path in output_paths:
            raise ValueError("staged or adapted channel paths must be unique")
        source_paths.add(source.output.path)
        output_paths.add(adapted_path)
        dimensions.add((source.width, source.height))
        adapted = ExactArtifact(
            artifact_id=_artifact_id(source.channel, adapted_path, source.output.sha256),
            kind=f"v05-raw-pbr-{source.channel}",
            path=adapted_path,
            sha256=source.output.sha256,
            byte_size=source.output.byte_size,
            media_type=source.output.media_type,
        )
        records.append(
            CodexImageV05BridgeChannel(
                channel=source.channel,
                provenance_kind=source.provenance_kind,
                algorithm_id=source.algorithm_id,
                algorithm_version=source.algorithm_version,
                source_sha256=source.source_sha256,
                source=source.output,
                adapted=adapted,
                width=source.width,
                height=source.height,
                color_space=cast(Literal["srgb", "non_color"], source.color_space),
                normal_convention=source.normal_convention,
                v05_usage=(
                    "texture_manifest_and_graph"
                    if source.channel in _TEXTURE_MANIFEST_CHANNELS
                    else "material_graph_only"
                ),
            )
        )
    if len(dimensions) != 1:
        raise ValueError("strict V0.5 bridge requires one shared channel resolution")
    return records


def _surface_detail_bindings(
    request: CodexImageMaterialAuthoringRequestV021,
    channels: list[CodexImageV05BridgeChannel],
) -> tuple[list[str], list[SurfaceDetailBinding]]:
    """Translate exact signage placement into the existing UV-clipped V0.5 contract."""

    if request.material_family != "signage_decal":
        return [], []
    if request.exact_text is None:
        raise ValueError("signage bridge requires exact text placement state")
    selected = [
        cast(Any, item.channel)
        for item in channels
        if item.channel in {"base_color", "opacity"}
        and item.v05_usage == "texture_manifest_and_graph"
    ]
    if not selected:
        raise ValueError("signage bridge requires base-color or opacity image evidence")
    detail_id = f"codex-imagegen-{request.run_id}"
    rect = request.exact_text.uv_rect
    return [detail_id], [
        SurfaceDetailBinding(
            detail_id=detail_id,
            parent_object_id=request.uv_identity.semantic_id,
            material_id=request.material_id,
            uv_layout_sha256=request.uv_identity.uv_fingerprint,
            placement=SurfaceDetailPlacement(
                mode="uv_rect",
                uv_rect=(*rect.minimum, *rect.maximum),
            ),
            channels=selected,
            wrap=request.exact_text.clip_mode,
        )
    ]


def _texture_manifest(
    request: CodexImageMaterialAuthoringRequestV021,
    channels: list[CodexImageV05BridgeChannel],
    *,
    shader_recipe_path: str,
) -> TextureManifest:
    """Create one strict V0.5 image manifest from exact copied raw channel bytes."""

    channel_map = {
        cast(Any, item.channel): TextureChannel(
            source="image",
            path=f"channels/{item.channel}.png",
            color_space="sRGB" if item.color_space == "srgb" else "Non-Color",
        )
        for item in channels
        if item.v05_usage == "texture_manifest_and_graph"
    }
    width, height = channels[0].width, channels[0].height
    detail_ids, detail_bindings = _surface_detail_bindings(request, channels)
    source_hashes = sorted(
        {
            request.source.artifact.sha256,
            request.uv_identity.evidence.sha256,
            *(digest for item in channels for digest in item.source_sha256),
        }
    )
    return TextureManifest(
        material_id=request.material_id,
        uv_set="UVMap",
        intended_scale_m=request.scale_context.longest_dimension_m,
        resolution=(width, height),
        source_type="image",
        channels=channel_map,
        surface_detail_ids=detail_ids,
        surface_detail_bindings=detail_bindings,
        shader_recipe=shader_recipe_path,
        provenance=TextureProvenance(
            provider="codex_blender_modeler.material_authoring.codex_image_v05_bridge",
            provider_version=SCHEMA_VERSION,
            source_hashes=source_hashes,
            generated_sha256={
                item.channel: item.adapted.sha256
                for item in channels
                if item.v05_usage == "texture_manifest_and_graph"
            },
            license=request.source.license_id,
        ),
        node_graph_summary=(
            "Exact MaterialAuthoring 0.2.1 image channels; no arbitrary node graph."
        ),
        color_space_rules={
            "base_color": "sRGB",
            "emission": "sRGB",
            "data_channels": "Non-Color",
            "normal_convention": "OpenGL +Y",
        },
        generation_notes=(
            "Direct Codex image roles remain restricted to base_color/emission/opacity; "
            "roughness, metallic, normal, height, and occlusion are local derivations."
        ),
        expected_preview_goal="Neutral and reference previews are required but not run here.",
    )


def _shader_recipe(
    scene_material: MaterialSpec,
    request: CodexImageMaterialAuthoringRequestV021,
    channels: list[CodexImageV05BridgeChannel],
    *,
    texture_manifest_path: str,
    limitations: list[str],
) -> ShaderRecipe:
    """Create one whitelist-only V0.5 recipe with honest portable family intent."""

    channel_names = {item.channel for item in channels}
    return ShaderRecipe(
        material_id=request.material_id,
        family=cast(Any, _target_shader_family(request.material_family)),
        surface=_surface(scene_material, request, channel_names),
        mapping=_mapping(request),
        layers=[],
        texture_manifest=texture_manifest_path,
        blender_master=True,
        bake_required=False,
        assumptions=list(limitations),
    )


def _fallback_plan_item(material: MaterialSpec) -> MaterialPlanItem:
    """Preserve an uncovered SceneSpec material as a neutral legacy-backed plan entry."""

    return MaterialPlanItem(
        material_id=material.id,
        label=material.name,
        shader_family=cast(Any, _scene_shader_family(material)),
        texture_strategy="none",
        mapping=MappingSpec(),
        evidence_status="observed",
        confidence=1.0,
        notes=["Preserved from current SceneSpec; no new image material was assigned."],
    )


def _material_plan(
    scene: SceneSpec,
    baseline: MaterialPlan,
    request: CodexImageMaterialAuthoringRequestV021,
    *,
    texture_manifest_path: str,
    shader_recipe_path: str,
    mapping_overrides: dict[str, Literal["uv"]] | None = None,
    mapping_recipe_overrides: dict[str, CodexImageV05MappingRecipeOverride] | None = None,
) -> MaterialPlan:
    """Author the target while preserving every other baseline and SceneSpec identity."""

    scene_by_id = {item.id: item for item in scene.materials}
    baseline_by_id = {item.material_id: item for item in baseline.materials}
    target_scene = scene_by_id[request.material_id]
    mapping = _mapping(request)
    target_baseline = baseline_by_id.get(request.material_id)
    if target_baseline is None:
        target = MaterialPlanItem(
            material_id=request.material_id,
            label=target_scene.name,
            shader_family=cast(Any, _target_shader_family(request.material_family)),
            texture_strategy="image",
            mapping=mapping,
            texture_manifest=texture_manifest_path,
            shader_recipe=shader_recipe_path,
            evidence_status="observed",
            confidence=1.0,
            notes=["Authored from exact validated Codex Image MaterialAuthoring 0.2.1 evidence."],
        )
    else:
        target = target_baseline.model_copy(
            update={
                "shader_family": _target_shader_family(request.material_family),
                "texture_strategy": "image",
                "mapping": mapping,
                "texture_manifest": texture_manifest_path,
                "shader_recipe": shader_recipe_path,
                "notes": [
                    *target_baseline.notes,
                    "Authored from exact validated Codex Image MaterialAuthoring 0.2.1 evidence.",
                ],
            }
        )
    overrides = dict(mapping_overrides or {})
    recipe_overrides = dict(mapping_recipe_overrides or {})
    if request.material_id in overrides:
        raise ValueError("mapping repair cannot override the authored target material")
    unknown_overrides = set(overrides) - set(baseline_by_id)
    if unknown_overrides:
        raise ValueError("mapping repair targets unknown baseline materials")
    if set(recipe_overrides) != set(overrides):
        raise ValueError("mapping repair shader derivatives differ from mapping scope")
    materials: list[MaterialPlanItem] = []
    for item in baseline.materials:
        if item.material_id == request.material_id:
            materials.append(target)
        elif item.material_id in overrides:
            materials.append(
                item.model_copy(
                    update={
                        "mapping": item.mapping.model_copy(
                            update={"mode": "uv", "uv_set": "UVMap"}
                        ),
                        "shader_recipe": recipe_overrides[item.material_id].artifact.path,
                    }
                )
            )
        else:
            materials.append(item)
    known = {item.material_id for item in materials}
    for scene_material in scene.materials:
        if scene_material.id == request.material_id and scene_material.id not in known:
            materials.append(target)
            known.add(scene_material.id)
        elif scene_material.id not in known:
            materials.append(_fallback_plan_item(scene_material))
            known.add(scene_material.id)
    if {item.material_id for item in materials} != set(scene_by_id):
        raise ValueError("candidate MaterialPlan must exactly cover current SceneSpec materials")
    return MaterialPlan(
        job_id=scene.job_id,
        scene_spec_path="analysis/scene_spec.json",
        stage="authored",
        surface_detail_binding_policy=baseline.surface_detail_binding_policy,
        materials=materials,
        global_notes=[
            *baseline.global_notes,
            "One target material is a run-owned Codex image V0.5 controller candidate.",
        ],
    )


def _mapping_recipe_derivatives(
    root: Path,
    baseline: MaterialPlan,
    *,
    run_root: str,
    mapping_overrides: dict[str, Literal["uv"]],
) -> list[CodexImageV05MappingRecipeOverride]:
    """Derive exact UVMap shader companions for every approved non-target mapping change."""

    baseline_by_id = {item.material_id: item for item in baseline.materials}
    derivatives: list[CodexImageV05MappingRecipeOverride] = []
    for material_id in sorted(mapping_overrides):
        item = baseline_by_id.get(material_id)
        if item is None or item.shader_recipe is None:
            raise ValueError("mapping repair material lacks a baseline shader recipe")
        source_path = ensure_contained_production_path(
            root,
            root / item.shader_recipe,
            must_exist=True,
        )
        source = load_shader_recipe(source_path)
        recipe = source.model_copy(
            update={
                "mapping": source.mapping.model_copy(update={"mode": "uv", "uv_set": "UVMap"}),
                "assumptions": [
                    *source.assumptions,
                    "UVMap mapping applied by the exact approved surface-detail repair.",
                ],
            }
        )
        payload = _model_bytes(recipe)
        recipe = ShaderRecipe.model_validate_json(payload)
        artifact = _exact_artifact_for_bytes(
            path=(f"{run_root}/mapping_recipe_overrides/{material_id}/shader_recipe.json"),
            payload=payload,
            kind="v05-mapping-repair-shader-recipe",
            media_type="application/json",
            label=f"mapping-recipe-{material_id}",
        )
        derivatives.append(
            CodexImageV05MappingRecipeOverride(
                material_id=material_id,
                recipe=recipe,
                artifact=artifact,
            )
        )
    return derivatives


def _artifact_to_graph(artifact: ExactArtifact, role: str) -> MaterialGraphArtifact:
    """Project exact material evidence into one strict MaterialGraph dependency."""

    return MaterialGraphArtifact(
        role=cast(Any, role),
        path=artifact.path,
        sha256=artifact.sha256,
    )


def _deduplicate_graph_inputs(
    inputs: list[MaterialGraphArtifact],
) -> list[MaterialGraphArtifact]:
    """Keep one exact role per dependency path and reject ambiguous duplicates."""

    selected: dict[str, MaterialGraphArtifact] = {}
    for item in inputs:
        current = selected.get(item.path)
        if current is None:
            selected[item.path] = item
            continue
        if current != item:
            raise ValueError(f"MaterialGraph input role or hash conflicts: {item.path}")
    return [selected[path] for path in sorted(selected)]


def _graph_bindings(
    scene_material: MaterialSpec,
    request: CodexImageMaterialAuthoringRequestV021,
    channels: list[CodexImageV05BridgeChannel],
) -> list[ChannelBinding]:
    """Bind exact images plus portable constants to the whitelist-only graph surface."""

    by_name = {item.channel: item for item in channels}
    scale_m = request.scale_context.longest_dimension_m
    localized = request.material_family == "signage_decal"
    bindings: list[ChannelBinding] = []
    constants: dict[str, float | tuple[float, float, float, float]] = {
        "base_color": scene_material.base_color,
        "roughness": request.base_roughness,
        "metallic": scene_material.metallic,
        "opacity": scene_material.base_color[3],
    }
    for name in _CHANNEL_ORDER:
        image = by_name.get(cast(Any, name))
        if image is not None:
            bindings.append(
                ChannelBinding(
                    channel=cast(Any, name),
                    source_kind="image",
                    color_space=("sRGB" if image.color_space == "srgb" else "Non-Color"),
                    image=_artifact_to_graph(image.adapted, "texture"),
                    physical_scale=TextureScale(
                        width_m=scale_m,
                        height_m=scale_m * image.height / image.width,
                        uv_set=request.uv_identity.uv_set,
                    ),
                    sampling="clamp" if localized else "repeat",
                    localized_detail=localized,
                    normal_format="OpenGL" if name == "normal" else None,
                )
            )
        elif name in constants:
            bindings.append(
                ChannelBinding(
                    channel=cast(Any, name),
                    source_kind="constant",
                    color_space="sRGB" if name == "base_color" else "Non-Color",
                    constant=constants[name],
                    sampling="clamp" if localized else "repeat",
                    localized_detail=localized,
                )
            )
    return bindings


def _material_graph(
    *,
    request: CodexImageMaterialAuthoringRequestV021,
    manifest: _SourceManifest,
    scene: SceneSpec,
    dispatch_id: str,
    plan_output: MaterialGraphArtifact,
    graph_inputs: list[MaterialGraphArtifact],
    channels: list[CodexImageV05BridgeChannel],
    limitations: list[str],
) -> MaterialGraphSpec:
    """Construct one exact-plan-bound MaterialGraphSpec without compiling it."""

    scene_material = next(item for item in scene.materials if item.id == request.material_id)
    channel_names = {item.channel for item in channels}
    maximum_displacement = (
        min(
            request.scale_context.shortest_dimension_m * request.derivation.height_strength * 0.02,
            0.01,
        )
        if "height" in channel_names
        else 0.0
    )
    return MaterialGraphSpec(
        graph_id=f"codex-img-v05-{manifest.manifest_id}"[:128],
        provenance=MaterialGraphProvenance(
            job_id=request.job_id,
            workflow_id=request.workflow_id,
            dispatch_id=dispatch_id,
            project_version="0.9.0",
            inputs=_deduplicate_graph_inputs([plan_output, *graph_inputs]),
        ),
        material_id=request.material_id,
        base_channels=_graph_bindings(scene_material, request, channels),
        layers=[],
        normal_displacement=NormalDisplacementPolicy(
            normal_mode="tangent_space" if "normal" in channel_names else "disabled",
            displacement_mode="bump_only" if "height" in channel_names else "disabled",
            maximum_displacement_m=maximum_displacement,
            require_subdivision=False,
        ),
        bake=BakePolicy(required=False, channels=[]),
        preview_lighting=PreviewLightingPolicy(
            reference_source=MaterialGraphArtifact(
                role="reference",
                path=request.source.artifact.path,
                sha256=request.source.artifact.sha256,
            ),
            reference_confidence=0.5,
        ),
        assumptions=list(limitations),
    )


def _existing_plan_dependencies(
    root: Path,
    baseline: MaterialPlan,
    *,
    excluded_material_id: str,
    mapping_recipe_overrides: dict[str, CodexImageV05MappingRecipeOverride] | None = None,
) -> list[ExactArtifact]:
    """Rehash every preserved non-target recipe, manifest, and image dependency."""

    artifacts: dict[str, ExactArtifact] = {}

    def add(path: Path, *, kind: str, label: str) -> None:
        """Add one dependency once while requiring identical repeated bytes."""

        artifact = _exact_artifact_for_file(
            root,
            path,
            kind=kind,
            media_type=_media_type(path.as_posix()),
            label=label,
        )
        current = artifacts.get(artifact.path)
        if current is not None and current.sha256 != artifact.sha256:
            raise ValueError(f"preserved material dependency hash conflicts: {artifact.path}")
        artifacts[artifact.path] = artifact

    recipe_overrides = dict(mapping_recipe_overrides or {})
    for item in baseline.materials:
        if item.material_id == excluded_material_id:
            continue
        manifest_value = item.texture_manifest
        if item.shader_recipe is not None:
            recipe_path = ensure_contained_production_path(
                root, root / item.shader_recipe, must_exist=True
            )
            recipe = load_shader_recipe(recipe_path)
            if item.material_id in recipe_overrides:
                override = recipe_overrides[item.material_id].artifact
                artifacts[override.path] = override
            else:
                add(recipe_path, kind="v05-shader-recipe", label="baseline-recipe")
            manifest_value = manifest_value or recipe.texture_manifest
        if manifest_value is None:
            continue
        loaded, manifest_path = load_material_manifest(
            {"id": item.material_id, "texture_manifest": manifest_value}, root
        )
        if loaded is None or manifest_path is None:
            raise ValueError("preserved V0.5 texture manifest did not load")
        add(manifest_path, kind="v05-texture-manifest", label="baseline-manifest")
        for channel in loaded["channels"].values():
            resolved = channel.get("resolved_path")
            if resolved is not None:
                add(
                    Path(str(resolved)),
                    kind="v05-texture-channel",
                    label="baseline-channel",
                )
    return [artifacts[path] for path in sorted(artifacts)]


def _source_dependency_artifacts(
    root: Path,
    request: CodexImageMaterialAuthoringRequestV021,
    receipt: _SourceReceipt,
    manifest: _SourceManifest,
    source_receipt_artifact: ExactArtifact,
    *,
    excluded_material_plan: ExactArtifact,
    source_request: _SourceRequest,
) -> list[ExactArtifact]:
    """Collect immutable staging provenance while replacing the mutable plan observation."""

    candidates = [
        _as_exact_artifact(receipt.request),
        _as_exact_artifact(receipt.manifest),
        source_receipt_artifact,
        request.source.artifact,
        request.uv_identity.evidence,
        request.scale_context.artifact,
        *request.source_v05_contracts,
        request.core_evidence.selection,
        request.core_evidence.selected_evidence,
        request.core_evidence.selected_quality_report,
        request.core_evidence.adoption,
        *[item.output for item in manifest.channels],
    ]
    if isinstance(source_request, CodexImageNormalizedMaterialAuthoringRequestV010):
        candidates.extend(
            [
                _as_exact_artifact(source_request.base_request_artifact),
                _as_exact_artifact(source_request.normalization_plan),
                _as_exact_artifact(source_request.normalization_receipt),
                source_request.effective_source.artifact,
                source_request.base_request.source.artifact,
            ]
        )
    if request.exact_text is not None:
        if request.exact_text.text_evidence_artifact is not None:
            candidates.append(request.exact_text.text_evidence_artifact)
        if request.exact_text.font is not None:
            candidates.append(request.exact_text.font.artifact)
    selected: dict[str, ExactArtifact] = {}
    for artifact in candidates:
        if _artifact_identity(artifact) == _artifact_identity(excluded_material_plan):
            continue
        _validate_exact_artifact(root, artifact)
        current = selected.get(artifact.path)
        if current is not None and current != artifact:
            shared = all(
                getattr(current, field) == getattr(artifact, field)
                for field in ("path", "sha256", "byte_size", "media_type")
            )
            if not shared:
                raise ValueError(f"source dependency metadata conflicts: {artifact.path}")
        else:
            selected[artifact.path] = artifact
    return [selected[path] for path in sorted(selected)]


def _controller_inputs(
    *,
    scene: ExactArtifact,
    scale_context: ExactArtifact,
    dependencies: list[ExactArtifact],
) -> list[CodexImageV05ControllerInput]:
    """Alias exact dependencies to the unchanged material-authoring phase role catalog."""

    by_path: dict[str, CodexImageV05ControllerInput] = {
        scene.path: CodexImageV05ControllerInput(role="scene", artifact=scene),
        scale_context.path: CodexImageV05ControllerInput(
            role="scale-context", artifact=scale_context
        ),
    }
    for artifact in dependencies:
        if artifact.path in by_path:
            current = by_path[artifact.path].artifact
            if current.sha256 != artifact.sha256 or current.byte_size != artifact.byte_size:
                raise ValueError(f"controller dependency hash conflicts: {artifact.path}")
            continue
        by_path[artifact.path] = CodexImageV05ControllerInput(
            role="material-baseline",
            artifact=artifact,
        )
    role_order = {"scene": 0, "scale-context": 1, "material-baseline": 2}
    return sorted(
        by_path.values(),
        key=lambda item: (role_order[item.role], item.artifact.path),
    )


def build_codex_image_v05_controller_blueprint(
    job_root: Path,
    source_receipt: _SourceReceipt,
    *,
    bridge_run_id: str,
    dispatch_id: str,
    material_plan_output_path: str,
    material_graph_output_path: str,
    material_plan_output_sha256: str | None = None,
    canonical_material_absence_evidence: ExactArtifact | None = None,
    source_authoring_receipt_artifact: ExactArtifact | None = None,
    source_scene_spec_artifact: ExactArtifact | None = None,
    baseline_material_plan_snapshot_artifact: ExactArtifact | None = None,
    promoted_material_plan_sha256: str | None = None,
    mapping_overrides: dict[str, Literal["uv"]] | None = None,
) -> CodexImageV05ControllerBlueprint:
    """Build exact-copy V0.5 models around validated legacy or normalized staging."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    validated_run_id = validate_production_id(bridge_run_id, "bridge_run_id")
    validated_dispatch_id = validate_production_id(dispatch_id, "dispatch_id")
    _validate_output_paths(root, material_plan_output_path, material_graph_output_path)
    (
        request,
        manifest,
        scene,
        baseline_artifact,
        baseline,
        promoted,
        source_request,
    ) = _load_source_bundle(
        root,
        source_receipt,
        canonical_material_absent=canonical_material_absence_evidence is not None,
        baseline_snapshot_artifact=baseline_material_plan_snapshot_artifact,
        promoted_material_plan_sha256=promoted_material_plan_sha256,
    )
    adoption = _load_core_adoption(root, request)
    if adoption.dispatch_id != validated_dispatch_id:
        raise ValueError("V0.5 bridge dispatch differs from the source adoption")
    source_authoring_receipt = source_authoring_receipt_artifact or _source_receipt_artifact(
        root, source_request
    )
    if source_authoring_receipt.path != f"{source_request.output_root}/receipt.json":
        raise ValueError("source authoring receipt artifact path differs from its run")
    _validate_exact_artifact(root, source_authoring_receipt)
    run_root = f"{_BRIDGE_ROOT}/{validated_run_id}"
    ensure_contained_production_path(root, root / run_root, must_exist=False)
    mapping_recipe_overrides = _mapping_recipe_derivatives(
        root,
        baseline,
        run_root=run_root,
        mapping_overrides=dict(mapping_overrides or {}),
    )
    mapping_recipe_by_id = {item.material_id: item for item in mapping_recipe_overrides}
    channels = _channel_records(manifest, run_root)
    channel_names = {item.channel for item in channels}
    limitations = _family_limitations(request, manifest.channels, channel_names)

    texture_path = f"{run_root}/texture_manifest.json"
    shader_path = f"{run_root}/shader_recipe.json"
    plan_path = f"{run_root}/candidate_material_plan.json"
    graph_path = f"{run_root}/candidate_material_graph.json"
    baseline_snapshot_path = f"{run_root}/source/baseline_material_plan.json"

    texture = _texture_manifest(request, channels, shader_recipe_path=shader_path)
    texture_bytes = _model_bytes(texture)
    texture = TextureManifest.model_validate_json(texture_bytes)
    texture_artifact = _exact_artifact_for_bytes(
        path=texture_path,
        payload=texture_bytes,
        kind="v05-texture-manifest",
        media_type="application/json",
        label="texture-manifest",
    )
    scene_material = next(item for item in scene.materials if item.id == request.material_id)
    shader = _shader_recipe(
        scene_material,
        request,
        channels,
        texture_manifest_path=texture_path,
        limitations=limitations,
    )
    shader_bytes = _model_bytes(shader)
    shader = ShaderRecipe.model_validate_json(shader_bytes)
    shader_artifact = _exact_artifact_for_bytes(
        path=shader_path,
        payload=shader_bytes,
        kind="v05-shader-recipe",
        media_type="application/json",
        label="shader-recipe",
    )
    plan = _material_plan(
        scene,
        baseline,
        request,
        texture_manifest_path=texture_path,
        shader_recipe_path=shader_path,
        mapping_overrides=mapping_overrides,
        mapping_recipe_overrides=mapping_recipe_by_id,
    )
    plan_bytes = _model_bytes(plan)
    plan = MaterialPlan.model_validate_json(plan_bytes)
    plan_artifact = _exact_artifact_for_bytes(
        path=plan_path,
        payload=plan_bytes,
        kind="v05-material-plan-blueprint",
        media_type="application/json",
        label="material-plan",
    )
    if (
        material_plan_output_sha256 is not None
        and material_plan_output_sha256 != plan_artifact.sha256
    ):
        raise ValueError("caller-supplied controller MaterialPlan hash differs from blueprint")

    scene_artifact = source_scene_spec_artifact or _exact_artifact_for_file(
        root,
        root / "analysis" / "scene_spec.json",
        kind="scene-spec",
        media_type="application/json",
        label="scene-spec",
    )
    if scene_artifact.path != "analysis/scene_spec.json":
        raise ValueError("source SceneSpec artifact path is not canonical")
    _validate_exact_artifact(root, scene_artifact)
    if canonical_material_absence_evidence is not None:
        _validate_canonical_material_absence_artifact(
            root,
            canonical_material_absence_evidence,
            request=request,
            scene_artifact=scene_artifact,
            dispatch_id=validated_dispatch_id,
            session_id=adoption.session_id,
            promoted_material_plan_sha256=(promoted_material_plan_sha256 if promoted else None),
        )
    if baseline_material_plan_snapshot_artifact is None:
        baseline_bytes = _validate_exact_artifact(root, baseline_artifact).read_bytes()
        baseline_snapshot = _exact_artifact_for_bytes(
            path=baseline_snapshot_path,
            payload=baseline_bytes,
            kind="v05-material-plan-baseline-snapshot",
            media_type="application/json",
            label="baseline-snapshot",
        )
    else:
        baseline_snapshot = baseline_material_plan_snapshot_artifact
        if baseline_snapshot.path != baseline_snapshot_path:
            raise ValueError("baseline snapshot path differs from the bridge run")
        _validate_exact_artifact(root, baseline_snapshot)
    previous_canonical_material_plan = (
        None if canonical_material_absence_evidence is not None else baseline_snapshot
    )
    source_dependencies = _source_dependency_artifacts(
        root,
        request,
        source_receipt,
        manifest,
        source_authoring_receipt,
        excluded_material_plan=baseline_artifact,
        source_request=source_request,
    )
    preserved_dependencies = _existing_plan_dependencies(
        root,
        baseline,
        excluded_material_id=request.material_id,
        mapping_recipe_overrides=mapping_recipe_by_id,
    )
    plan_output_graph_artifact = MaterialGraphArtifact(
        role="material_plan",
        path=material_plan_output_path,
        sha256=plan_artifact.sha256,
    )
    graph_inputs = [
        _artifact_to_graph(scene_artifact, "scene_spec"),
        _artifact_to_graph(baseline_snapshot, "other"),
        _artifact_to_graph(texture_artifact, "other"),
        _artifact_to_graph(shader_artifact, "shader_recipe"),
        _artifact_to_graph(plan_artifact, "other"),
        *[_artifact_to_graph(item.adapted, "texture") for item in channels],
        *[
            _artifact_to_graph(
                item,
                "reference" if item.path == request.source.artifact.path else "other",
            )
            for item in [*source_dependencies, *preserved_dependencies]
        ],
    ]
    graph = _material_graph(
        request=request,
        manifest=manifest,
        scene=scene,
        dispatch_id=validated_dispatch_id,
        plan_output=plan_output_graph_artifact,
        graph_inputs=graph_inputs,
        channels=channels,
        limitations=limitations,
    )
    graph_bytes = _model_bytes(graph)
    graph = MaterialGraphSpec.model_validate_json(graph_bytes)
    graph_artifact = _exact_artifact_for_bytes(
        path=graph_path,
        payload=graph_bytes,
        kind="material-graph-spec-blueprint",
        media_type="application/json",
        label="material-graph",
    )
    dependencies = [
        baseline_snapshot,
        texture_artifact,
        shader_artifact,
        plan_artifact,
        graph_artifact,
        *[item.adapted for item in channels],
        *source_dependencies,
        *preserved_dependencies,
        *(
            [canonical_material_absence_evidence]
            if canonical_material_absence_evidence is not None
            else []
        ),
    ]
    inputs = _controller_inputs(
        scene=scene_artifact,
        scale_context=request.scale_context.artifact,
        dependencies=dependencies,
    )
    expected_outputs = {
        material_plan_output_path: plan_artifact.sha256,
        material_graph_output_path: graph_artifact.sha256,
    }
    provenance_by_path: dict[str, ExactArtifact] = {}
    for artifact in (
        source_authoring_receipt,
        *[item.artifact for item in inputs],
        *(
            [previous_canonical_material_plan]
            if previous_canonical_material_plan is not None
            else []
        ),
        *(
            [canonical_material_absence_evidence]
            if canonical_material_absence_evidence is not None
            else []
        ),
    ):
        current = provenance_by_path.get(artifact.path)
        if current is not None and _artifact_identity(current) != _artifact_identity(artifact):
            raise ValueError(f"V0.5 bridge provenance metadata conflicts: {artifact.path}")
        provenance_by_path[artifact.path] = artifact
    provenance = [provenance_by_path[path] for path in sorted(provenance_by_path)]
    evidence_payload = _v05_evidence_payload(
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        dispatch_id=validated_dispatch_id,
        session_id=adoption.session_id,
        profile_id=adoption.profile_id,
        provider_id=adoption.provider_id,
        bridge_run_id=validated_run_id,
        target_material_id=request.material_id,
        mapping_overrides=dict(mapping_overrides or {}),
        source_authoring_receipt=source_authoring_receipt,
        source_material_plan=baseline_artifact,
        previous_canonical_material_plan=previous_canonical_material_plan,
        canonical_material_absence_evidence=canonical_material_absence_evidence,
        controller_inputs=inputs,
        expected_output_sha256=expected_outputs,
    )
    return CodexImageV05ControllerBlueprint(
        blueprint_id=f"v05-blueprint-{_sha256_bytes(graph_bytes)[:16]}",
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        dispatch_id=validated_dispatch_id,
        session_id=adoption.session_id,
        profile_id=adoption.profile_id,
        provider_id=adoption.provider_id,
        input_sha256=stable_json_digest(evidence_payload),
        source_fingerprint=source_authoring_receipt.sha256,
        provenance=provenance,
        created_at=source_receipt.created_at,
        bridge_run_id=validated_run_id,
        target_material_id=request.material_id,
        mapping_overrides=dict(mapping_overrides or {}),
        mapping_recipe_overrides=mapping_recipe_overrides,
        run_root=run_root,
        source_authoring_receipt=source_authoring_receipt,
        source_authoring_request=_as_exact_artifact(source_receipt.request),
        source_authoring_manifest=_as_exact_artifact(source_receipt.manifest),
        source_scene_spec=scene_artifact,
        source_material_plan=baseline_artifact,
        previous_canonical_material_plan=previous_canonical_material_plan,
        canonical_material_absence_evidence=canonical_material_absence_evidence,
        baseline_material_plan_snapshot=baseline_snapshot,
        scale_context=request.scale_context.artifact,
        uv_identity=request.uv_identity.evidence,
        channels=channels,
        texture_manifest=texture,
        texture_manifest_artifact=texture_artifact,
        shader_recipe=shader,
        shader_recipe_artifact=shader_artifact,
        material_plan=plan,
        material_plan_artifact=plan_artifact,
        material_graph=graph,
        material_graph_artifact=graph_artifact,
        controller_inputs=inputs,
        expected_output_sha256=expected_outputs,
        limitations=limitations,
    )


def _write_exclusive(path: Path, payload: bytes) -> None:
    """Write one non-empty staging payload without overwriting existing evidence."""

    if not payload:
        raise ValueError("bridge publication payload cannot be empty")
    os.makedirs(native_io_path(path.parent), exist_ok=True)
    with open(native_io_path(path), "xb") as handle:
        handle.write(payload)


def _stage_member(stage_root: Path, run_root: str, artifact_path: str) -> Path:
    """Map one declared final bridge artifact to its private staging member."""

    relative = PurePosixPath(artifact_path)
    prefix = PurePosixPath(run_root)
    try:
        member = relative.relative_to(prefix)
    except ValueError as exc:
        raise ValueError("bridge output artifact escapes its declared run root") from exc
    return stage_root.joinpath(*member.parts)


def _verify_stage_artifact(
    stage_root: Path,
    run_root: str,
    artifact: ExactArtifact,
) -> None:
    """Rehash one private staging member against its final-path artifact metadata."""

    path = _stage_member(stage_root, run_root, artifact.path)
    if not os.path.isfile(native_io_path(path)):
        raise ValueError(f"bridge staging output is missing: {artifact.path}")
    if os.path.getsize(native_io_path(path)) != artifact.byte_size:
        raise ValueError(f"bridge staging output byte size differs: {artifact.path}")
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"bridge staging output hash differs: {artifact.path}")


def publish_codex_image_v05_bridge(
    job_root: Path,
    source_receipt: _SourceReceipt,
    *,
    bridge_run_id: str,
    dispatch_id: str,
    material_plan_output_path: str,
    material_graph_output_path: str,
    material_plan_output_sha256: str | None = None,
    canonical_material_absence_evidence: ExactArtifact | None = None,
    source_authoring_receipt_artifact: ExactArtifact | None = None,
    source_scene_spec_artifact: ExactArtifact | None = None,
    mapping_overrides: dict[str, Literal["uv"]] | None = None,
) -> CodexImageV05BridgeReceipt:
    """Atomically publish exact V0.5 dependencies and controller-copy blueprints."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    blueprint = build_codex_image_v05_controller_blueprint(
        root,
        source_receipt,
        bridge_run_id=bridge_run_id,
        dispatch_id=dispatch_id,
        material_plan_output_path=material_plan_output_path,
        material_graph_output_path=material_graph_output_path,
        material_plan_output_sha256=material_plan_output_sha256,
        canonical_material_absence_evidence=canonical_material_absence_evidence,
        source_authoring_receipt_artifact=source_authoring_receipt_artifact,
        source_scene_spec_artifact=source_scene_spec_artifact,
        mapping_overrides=mapping_overrides,
    )
    if isinstance(source_receipt, CodexImageNormalizedMaterialAuthoringReceiptV010):
        normalized_request = cast(
            CodexImageNormalizedMaterialAuthoringRequestV010,
            _read_exact_model(
                root,
                blueprint.source_authoring_request,
                CodexImageNormalizedMaterialAuthoringRequestV010,
            ),
        )
        request = normalized_request.base_request.model_copy(
            update={"source": normalized_request.effective_source}
        )
    else:
        request = cast(
            CodexImageMaterialAuthoringRequestV021,
            _read_exact_model(
                root,
                blueprint.source_authoring_request,
                CodexImageMaterialAuthoringRequestV021,
            ),
        )
    before = {
        blueprint.source_scene_spec.path: blueprint.source_scene_spec.sha256,
        blueprint.source_material_plan.path: blueprint.source_material_plan.sha256,
        **(
            {
                blueprint.canonical_material_absence_evidence.path: (
                    blueprint.canonical_material_absence_evidence.sha256
                )
            }
            if blueprint.canonical_material_absence_evidence is not None
            else {}
        ),
    }
    final_root = ensure_contained_production_path(root, root / blueprint.run_root, must_exist=False)
    if os.path.exists(native_io_path(final_root)):
        raise FileExistsError(f"V0.5 bridge run already exists: {blueprint.run_root}")
    parent = ensure_contained_production_path(root, final_root.parent, must_exist=False)
    os.makedirs(native_io_path(parent), exist_ok=True)
    stage_root = parent / f".{bridge_run_id}.staging-{uuid4().hex}"
    ensure_contained_production_path(root, stage_root, must_exist=False)
    os.makedirs(native_io_path(stage_root), exist_ok=False)
    receipt = CodexImageV05BridgeReceipt(
        receipt_id=f"v05-receipt-{blueprint.material_graph_artifact.sha256[:16]}",
        job_id=blueprint.job_id,
        workflow_id=blueprint.workflow_id,
        dispatch_id=blueprint.dispatch_id,
        session_id=blueprint.session_id,
        profile_id=blueprint.profile_id,
        provider_id=blueprint.provider_id,
        input_sha256=blueprint.input_sha256,
        source_fingerprint=blueprint.source_fingerprint,
        provenance=blueprint.provenance,
        created_at=blueprint.created_at,
        bridge_run_id=blueprint.bridge_run_id,
        target_material_id=blueprint.target_material_id,
        mapping_overrides=blueprint.mapping_overrides,
        mapping_recipe_overrides=blueprint.mapping_recipe_overrides,
        material_family=request.material_family,
        source_authoring_receipt=blueprint.source_authoring_receipt,
        source_authoring_request=blueprint.source_authoring_request,
        source_authoring_manifest=blueprint.source_authoring_manifest,
        source_scene_spec=blueprint.source_scene_spec,
        source_material_plan=blueprint.source_material_plan,
        previous_canonical_material_plan=blueprint.previous_canonical_material_plan,
        canonical_material_absence_evidence=(blueprint.canonical_material_absence_evidence),
        baseline_material_plan_snapshot=blueprint.baseline_material_plan_snapshot,
        scale_context=blueprint.scale_context,
        uv_identity=blueprint.uv_identity,
        channels=blueprint.channels,
        texture_manifest=blueprint.texture_manifest_artifact,
        shader_recipe=blueprint.shader_recipe_artifact,
        candidate_material_plan=blueprint.material_plan_artifact,
        candidate_material_graph=blueprint.material_graph_artifact,
        controller_inputs=blueprint.controller_inputs,
        expected_output_sha256=blueprint.expected_output_sha256,
        limitations=blueprint.limitations,
    )
    try:
        for channel in blueprint.channels:
            source = _validate_exact_artifact(root, channel.source)
            target = _stage_member(stage_root, blueprint.run_root, channel.adapted.path)
            os.makedirs(native_io_path(target.parent), exist_ok=True)
            with open(native_io_path(source), "rb") as source_handle:
                _write_exclusive(target, source_handle.read())
        baseline_source = _validate_exact_artifact(root, blueprint.source_material_plan)
        baseline_target = _stage_member(
            stage_root,
            blueprint.run_root,
            blueprint.baseline_material_plan_snapshot.path,
        )
        with open(native_io_path(baseline_source), "rb") as source_handle:
            _write_exclusive(baseline_target, source_handle.read())
        payloads = (
            *[
                (item.artifact, _model_bytes(item.recipe))
                for item in blueprint.mapping_recipe_overrides
            ],
            (blueprint.texture_manifest_artifact, _model_bytes(blueprint.texture_manifest)),
            (blueprint.shader_recipe_artifact, _model_bytes(blueprint.shader_recipe)),
            (blueprint.material_plan_artifact, _model_bytes(blueprint.material_plan)),
            (blueprint.material_graph_artifact, _model_bytes(blueprint.material_graph)),
        )
        for artifact, payload in payloads:
            _write_exclusive(_stage_member(stage_root, blueprint.run_root, artifact.path), payload)
        outputs = [
            blueprint.baseline_material_plan_snapshot,
            *[item.adapted for item in blueprint.channels],
            *[item.artifact for item in blueprint.mapping_recipe_overrides],
            blueprint.texture_manifest_artifact,
            blueprint.shader_recipe_artifact,
            blueprint.material_plan_artifact,
            blueprint.material_graph_artifact,
        ]
        for artifact in outputs:
            _verify_stage_artifact(stage_root, blueprint.run_root, artifact)
        _write_exclusive(stage_root / "receipt.json", _model_bytes(receipt))
        os.replace(native_io_path(stage_root), native_io_path(final_root))
    except Exception:
        if os.path.isdir(native_io_path(stage_root)):
            shutil.rmtree(native_io_path(stage_root))
        raise
    for relative, expected in before.items():
        path = ensure_contained_production_path(root, root / relative, must_exist=True)
        if sha256_file(path) != expected:
            raise RuntimeError(f"canonical source changed during V0.5 bridge: {relative}")
    if blueprint.canonical_material_absence_evidence is not None:
        _validate_canonical_material_absence_artifact(
            root,
            blueprint.canonical_material_absence_evidence,
            request=request,
            scene_artifact=blueprint.source_scene_spec,
            dispatch_id=blueprint.dispatch_id,
            session_id=blueprint.session_id,
        )
    return validate_codex_image_v05_bridge(root, receipt)


def _expected_output_paths(receipt: CodexImageV05BridgeReceipt) -> tuple[str, str]:
    """Select exact MaterialPlan and MaterialGraph controller output paths by filename."""

    plan_paths = [
        path
        for path in receipt.expected_output_sha256
        if PurePosixPath(path).name == "material_plan.json"
    ]
    graph_paths = [
        path
        for path in receipt.expected_output_sha256
        if PurePosixPath(path).name == "material_graph.json"
    ]
    if len(plan_paths) != 1 or len(graph_paths) != 1:
        raise ValueError("bridge receipt expected outputs are incomplete")
    return plan_paths[0], graph_paths[0]


def _validate_graph_dependency_files(
    root: Path,
    graph: MaterialGraphSpec,
) -> None:
    """Rehash all graph inputs, allowing only the not-yet-created controller plan output."""

    plan_inputs = [item for item in graph.provenance.inputs if item.role == "material_plan"]
    if len(plan_inputs) != 1:
        raise ValueError("bridge graph must contain one controller MaterialPlan output")
    plan_output = plan_inputs[0]
    for artifact in graph.provenance.inputs:
        path = ensure_contained_production_path(root, root / artifact.path, must_exist=False)
        if not os.path.exists(native_io_path(path)):
            if artifact == plan_output:
                continue
            raise FileNotFoundError(f"bridge graph dependency is missing: {artifact.path}")
        if not os.path.isfile(native_io_path(path)) or sha256_file(path) != artifact.sha256:
            raise ValueError(f"bridge graph dependency changed: {artifact.path}")


def validate_codex_image_v05_bridge(
    job_root: Path,
    receipt: CodexImageV05BridgeReceipt,
) -> CodexImageV05BridgeReceipt:
    """Replay source validation and every exact published V0.5 bridge binding."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    published_path = ensure_contained_production_path(
        root,
        root / _BRIDGE_ROOT / receipt.bridge_run_id / "receipt.json",
        must_exist=True,
    )
    published = CodexImageV05BridgeReceipt.model_validate_json(published_path.read_bytes())
    if published != receipt:
        raise ValueError("provided V0.5 bridge receipt differs from published bytes")
    source_receipt = cast(
        _SourceReceipt,
        _read_exact_model(
            root,
            receipt.source_authoring_receipt,
            (
                CodexImageNormalizedMaterialAuthoringReceiptV010
                if receipt.source_authoring_request.kind
                == "codex-image-normalized-material-authoring-request"
                else CodexImageMaterialAuthoringReceiptV021
            ),
        ),
    )
    plan_output_path, graph_output_path = _expected_output_paths(receipt)
    blueprint = build_codex_image_v05_controller_blueprint(
        root,
        source_receipt,
        bridge_run_id=receipt.bridge_run_id,
        dispatch_id=receipt.dispatch_id,
        material_plan_output_path=plan_output_path,
        material_graph_output_path=graph_output_path,
        material_plan_output_sha256=receipt.expected_output_sha256[plan_output_path],
        canonical_material_absence_evidence=(receipt.canonical_material_absence_evidence),
        source_authoring_receipt_artifact=receipt.source_authoring_receipt,
        source_scene_spec_artifact=receipt.source_scene_spec,
        baseline_material_plan_snapshot_artifact=(receipt.baseline_material_plan_snapshot),
        promoted_material_plan_sha256=receipt.candidate_material_plan.sha256,
        mapping_overrides=receipt.mapping_overrides,
    )
    expected = {
        "job_id": blueprint.job_id,
        "workflow_id": blueprint.workflow_id,
        "dispatch_id": blueprint.dispatch_id,
        "session_id": blueprint.session_id,
        "profile_id": blueprint.profile_id,
        "provider_id": blueprint.provider_id,
        "input_sha256": blueprint.input_sha256,
        "source_fingerprint": blueprint.source_fingerprint,
        "producer": blueprint.producer,
        "producer_version": blueprint.producer_version,
        "provenance": blueprint.provenance,
        "created_at": blueprint.created_at,
        "bridge_run_id": blueprint.bridge_run_id,
        "target_material_id": blueprint.target_material_id,
        "mapping_overrides": blueprint.mapping_overrides,
        "mapping_recipe_overrides": blueprint.mapping_recipe_overrides,
        "source_authoring_receipt": blueprint.source_authoring_receipt,
        "source_authoring_request": blueprint.source_authoring_request,
        "source_authoring_manifest": blueprint.source_authoring_manifest,
        "source_scene_spec": blueprint.source_scene_spec,
        "source_material_plan": blueprint.source_material_plan,
        "previous_canonical_material_plan": (blueprint.previous_canonical_material_plan),
        "canonical_material_absence_evidence": (blueprint.canonical_material_absence_evidence),
        "baseline_material_plan_snapshot": blueprint.baseline_material_plan_snapshot,
        "scale_context": blueprint.scale_context,
        "uv_identity": blueprint.uv_identity,
        "channels": blueprint.channels,
        "texture_manifest": blueprint.texture_manifest_artifact,
        "shader_recipe": blueprint.shader_recipe_artifact,
        "candidate_material_plan": blueprint.material_plan_artifact,
        "candidate_material_graph": blueprint.material_graph_artifact,
        "controller_inputs": blueprint.controller_inputs,
        "expected_output_sha256": blueprint.expected_output_sha256,
        "limitations": blueprint.limitations,
    }
    if any(getattr(receipt, field) != value for field, value in expected.items()):
        raise ValueError("published V0.5 bridge receipt differs from deterministic blueprint")
    for artifact in (
        receipt.baseline_material_plan_snapshot,
        *[item.adapted for item in receipt.channels],
        *[item.artifact for item in receipt.mapping_recipe_overrides],
        receipt.texture_manifest,
        receipt.shader_recipe,
        receipt.candidate_material_plan,
        receipt.candidate_material_graph,
    ):
        _validate_exact_artifact(root, artifact)
    for channel in receipt.channels:
        source = _validate_exact_artifact(root, channel.source)
        adapted = _validate_exact_artifact(root, channel.adapted)
        if source.read_bytes() != adapted.read_bytes():
            raise ValueError(f"V0.5 bridge channel bytes differ: {channel.channel}")
    texture = cast(
        TextureManifest,
        _read_exact_model(root, receipt.texture_manifest, TextureManifest),
    )
    shader = cast(ShaderRecipe, _read_exact_model(root, receipt.shader_recipe, ShaderRecipe))
    for override in receipt.mapping_recipe_overrides:
        stored_override = cast(
            ShaderRecipe,
            _read_exact_model(root, override.artifact, ShaderRecipe),
        )
        if stored_override != override.recipe:
            raise ValueError("published mapping recipe derivative changed")
    plan = cast(
        MaterialPlan,
        _read_exact_model(root, receipt.candidate_material_plan, MaterialPlan),
    )
    graph = cast(
        MaterialGraphSpec,
        _read_exact_model(root, receipt.candidate_material_graph, MaterialGraphSpec),
    )
    if (
        texture != blueprint.texture_manifest
        or shader != blueprint.shader_recipe
        or plan != blueprint.material_plan
        or graph != blueprint.material_graph
    ):
        raise ValueError("published V0.5 bridge models differ from deterministic models")
    loaded_manifest, _manifest_path = load_material_manifest(
        {"id": receipt.target_material_id, "texture_manifest": receipt.texture_manifest.path},
        root,
    )
    if loaded_manifest is None:
        raise ValueError("published strict V0.5 TextureManifest did not load")
    scene = cast(SceneSpec, _read_exact_model(root, receipt.source_scene_spec, SceneSpec))
    validation = validate_material_contracts(plan, scene.model_dump(mode="json"), root)
    if not validation.ok:
        failures = [item.message for item in validation.checks if item.status == "failed"]
        raise ValueError(f"published V0.5 MaterialPlan is invalid: {failures}")
    _validate_graph_dependency_files(root, graph)
    for item in receipt.controller_inputs:
        _validate_exact_artifact(root, item.artifact)
    return receipt
