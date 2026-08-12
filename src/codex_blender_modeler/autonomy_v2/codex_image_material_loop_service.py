"""Host bridge for promoting one ImageGen material through AQ v2 authority."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel

from ..autonomy.worker import autonomy_session_lock
from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from ..codex_imagegen.artifacts import (
    artifact_for_codex_image,
    ensure_contained_codex_image_path,
    load_codex_image_model,
    validate_codex_image_artifact,
    write_immutable_codex_image_model,
)
from ..codex_imagegen.material_loop_models import (
    CodexImageCompanionSelectionReceipt,
    CodexImageMaterialLoopState,
    CodexImageMaterialLoopTerminal,
    CodexImageSemanticReview,
    CodexImageV05ExactAdoptionPreflightReceipt,
    ImageGeneratedMaterialBridgePlan,
    ImageGeneratedMaterialControllerBinding,
    ImageGeneratedMaterialControllerInput,
    ImageGeneratedMaterialNeutralPreview,
    ImageGeneratedMaterialPromotionReceipt,
    ImageGenNativeNormalizationPlan,
    ImageGenNativeNormalizationReceipt,
    ImageMaterialLoopBudgetUsage,
    codex_image_v05_exact_adoption_preflight_receipt_path,
    codex_image_v05_exact_adoption_preflight_root_path,
    exact_adoption_preflight_input_sha256,
    material_loop_state_input_sha256,
    validate_material_loop_transition,
)
from ..codex_imagegen.material_loop_normalization import (
    validate_native_normalization_receipt,
)
from ..codex_imagegen.material_loop_selection import (
    validate_codex_imagegen_companion_selection,
)
from ..codex_imagegen.material_loop_semantic import (
    validate_codex_image_semantic_review,
)
from ..codex_imagegen.models import (
    CodexGeneratedImageEvidence,
    CodexImageArtifact,
    CodexImageGenerationSelection,
    ImageToMaterialAdoption,
)
from ..codex_imagegen.native_core_preparation import (
    validate_native_core_preparation_binding,
)
from ..material_authoring.codex_image_normalized_adapter import (
    validate_codex_image_normalized_material_candidate,
)
from ..material_authoring.codex_image_normalized_models import (
    CodexImageNormalizedMaterialAuthoringReceiptV010,
    CodexImageNormalizedMaterialAuthoringRequestV010,
)
from ..material_authoring.codex_image_v05_bridge import (
    CodexImageV05BridgeReceipt,
    validate_codex_image_v05_bridge,
)
from ..material_graph.compiler_service import MaterialGraphCompilerService
from ..material_graph.models import MaterialGraphArtifact, MaterialGraphSpec
from ..material_graph.runtime_models import MaterialGraphCompileReport
from ..materials.models import MaterialPlan
from ..models import SceneSpec
from ..production.controller_executor import (
    CandidateAuthoringController,
    ControllerExecutionRequest,
    ControllerResult,
    PhaseToolProfile,
)
from ..production.validation import ensure_contained_production_path
from ..workspace import job_dir
from .candidate_validation_models import GeometryCandidateValidationReceiptV2
from .candidate_validation_service import (
    validate_geometry_candidate_validation_receipt_v2,
)
from .codex_image_material_preview_service import (
    validate_promoted_codex_image_material_preview,
)
from .codex_image_overlay import AutonomyCodexImageOverlay
from .codex_image_phase_service import get_codex_image_phase_status
from .controller_bridge import (
    _state_chain as _base_aq_state_chain,
)
from .controller_bridge import (
    execute_autonomy_v2_controller,
    get_autonomy_v2_status,
)
from .delivery_service import (
    artifact_for_v2,
    validate_quality_promotion_evidence_v2,
    validate_quality_source_freeze,
    validate_root_authorization_boundary_v2,
    validate_v2_artifact,
)
from .material_phase_models import (
    MaterialControllerCompletionV2,
    MaterialPhaseReceiptV2,
    MaterialPhaseRollbackReceiptV2,
    MaterialPromotionIntentV2,
)
from .material_phase_service import validate_material_phase_receipt_v2
from .models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyProfileV2,
    AutonomyStateV2,
    QualityApprovedSourceFreeze,
)
from .quality_terminal_service import (
    validate_quality_review_bundle_v2,
    validate_quality_terminal_v2,
)
from .supervisor_service import QualitySubmissionV2, advance_autonomy_v2

_PRODUCER = "codex_blender_modeler.autonomy_v2.codex_image_material_loop_service"
_LOOP_DIR = "codex_image_material_loop"


class ExactCodexImageMaterialAdoptionController:
    """Copy exact V0.5 blueprints and author only their strict completion contract."""

    controller_kind = "desktop_in_session"

    @staticmethod
    def _snapshot_by_sha256(
        immutable_inputs: tuple[Path, ...], expected_sha256: str
    ) -> Path:
        """Select one byte-identical immutable snapshot by its declared digest."""

        matches = [path for path in immutable_inputs if sha256_file(path) == expected_sha256]
        if not matches:
            raise ValueError("exact-adoption controller input snapshot is missing")
        return matches[0]

    @staticmethod
    def _execution_id(allowed_output_paths: tuple[Path, ...]) -> str:
        """Recover the host-owned execution identifier from the isolated workspace path."""

        if not allowed_output_paths:
            raise ValueError("exact-adoption controller has no allowed outputs")
        parts = allowed_output_paths[0].parts
        indices = [
            index
            for index, part in enumerate(parts[:-1])
            if part == "controller_executions"
        ]
        if len(indices) != 1 or indices[0] + 1 >= len(parts):
            raise ValueError("exact-adoption controller cannot resolve execution identity")
        return parts[indices[0] + 1]

    @staticmethod
    def _write_exact(path: Path, payload: bytes) -> None:
        """Write one isolated output once and reject a differing crash replay."""

        os.makedirs(native_io_path(path.parent), exist_ok=True)
        if os.path.exists(native_io_path(path)):
            with open(native_io_path(path), "rb") as handle:
                existing = handle.read()
            if existing != payload:
                raise FileExistsError("exact-adoption output differs on replay")
            return
        with open(native_io_path(path), "xb") as handle:
            handle.write(payload)

    @staticmethod
    def _read_bytes(path: Path) -> bytes:
        """Read one isolated snapshot through the native Windows long-path form."""

        with open(native_io_path(path), "rb") as handle:
            return handle.read()

    def execute(
        self,
        *,
        assignment: Path,
        immutable_inputs: tuple[Path, ...],
        allowed_output_paths: tuple[Path, ...],
        tool_profile: PhaseToolProfile,
        timeout_seconds: int,
    ) -> str:
        """Publish exactly the two immutable blueprints plus a host-compatible completion."""

        del timeout_seconds
        controller_input = ImageGeneratedMaterialControllerInput.model_validate_json(
            self._read_bytes(assignment)
        )
        if controller_input.execution_mode != "exact_adoption":
            raise PermissionError("exact-adoption controller rejects authored completion mode")
        if tool_profile.profile_id != "material_authoring":
            raise PermissionError("exact-adoption controller requires the material profile")
        outputs = {path.name: path for path in allowed_output_paths}
        if set(outputs) != {
            "material_plan.json",
            "material_graph.json",
            "completion.json",
        }:
            raise ValueError("exact-adoption controller received another output boundary")
        plan_source = self._snapshot_by_sha256(
            immutable_inputs, controller_input.candidate_material_plan.sha256
        )
        graph_source = self._snapshot_by_sha256(
            immutable_inputs, controller_input.material_graph_spec.sha256
        )
        plan_bytes = self._read_bytes(plan_source)
        graph_bytes = self._read_bytes(graph_source)
        expected_by_name = {
            PurePosixPath(path).name: digest
            for path, digest in controller_input.expected_output_sha256.items()
        }
        if expected_by_name != {
            "material_plan.json": sha256_file(plan_source),
            "material_graph.json": sha256_file(graph_source),
        }:
            raise ValueError("exact-adoption expected hashes differ from blueprint bytes")
        self._write_exact(outputs["material_plan.json"], plan_bytes)
        self._write_exact(outputs["material_graph.json"], graph_bytes)
        output_by_name = {
            PurePosixPath(path).name: path
            for path in controller_input.allowed_output_paths
        }
        completion = MaterialControllerCompletionV2(
            completion_id=f"material-completion-{controller_input.session_id}",
            job_id=controller_input.job_id,
            workflow_id=controller_input.workflow_id,
            dispatch_id=controller_input.dispatch_id,
            session_id=controller_input.session_id,
            execution_id=self._execution_id(allowed_output_paths),
            assignment_sha256=sha256_file(assignment),
            tool_profile_sha256=controller_input.phase_tool_profile.sha256,
            immutable_input_sha256=controller_input.immutable_input_sha256,
            source_scene_spec_sha256=controller_input.source_scene_spec_sha256,
            source_material_plan_sha256=controller_input.source_material_plan_sha256,
            material_plan_path=output_by_name["material_plan.json"],
            material_plan_sha256=sha256_file(plan_source),
            material_graph_path=output_by_name["material_graph.json"],
            material_graph_sha256=sha256_file(graph_source),
        )
        completion_bytes = (completion.model_dump_json(indent=2) + "\n").encode("utf-8")
        self._write_exact(outputs["completion.json"], completion_bytes)
        return "completed"


def _read_model(root: Path, artifact: AQV2Artifact, model_type: type[BaseModel]) -> BaseModel:
    """Rehash and strict-parse one AQ v2 JSON artifact."""

    path = validate_v2_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return model_type.model_validate_json(handle.read())


def _codex_from_aq(
    root: Path,
    artifact: AQV2Artifact,
    *,
    artifact_id: str | None = None,
    kind: str | None = None,
) -> CodexImageArtifact:
    """Project one rehashed AQ artifact into the media-aware companion shape."""

    path = validate_v2_artifact(root, artifact)
    return artifact_for_codex_image(
        root,
        path,
        artifact_id=artifact_id or artifact.artifact_id,
        kind=kind or artifact.kind,
        media_type="application/json",
    )


def _aq_from_codex(
    artifact: CodexImageArtifact, *, role: str | None = None
) -> AQV2Artifact:
    """Project one companion artifact, preserving its kind unless an alias is required."""

    return AQV2Artifact(
        artifact_id=artifact.artifact_id,
        kind=role or artifact.kind,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )


def _same_controller_artifact(
    controller_artifact: Any,
    companion_artifact: CodexImageArtifact,
) -> bool:
    """Compare executor and companion artifacts by their complete byte identity."""

    return (
        controller_artifact.artifact_id,
        controller_artifact.path,
        controller_artifact.sha256,
        controller_artifact.byte_size,
    ) == (
        companion_artifact.artifact_id,
        companion_artifact.path,
        companion_artifact.sha256,
        companion_artifact.byte_size,
    )


def _codex_from_exact(artifact: Any) -> CodexImageArtifact:
    """Project one strict V0.5 exact artifact into the companion artifact shape."""

    return CodexImageArtifact(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
        media_type=artifact.media_type,
    )


def _validate_controller_request_binding(
    request: ControllerExecutionRequest,
    *,
    plan: ImageGeneratedMaterialBridgePlan,
    controller_input: ImageGeneratedMaterialControllerInput,
    input_artifact: CodexImageArtifact,
) -> None:
    """Require the persisted executor request to equal the published controller input."""

    expected_inputs = _controller_input_artifacts(controller_input)
    if (
        request.job_id,
        request.workflow_id,
        request.dispatch_id,
        request.session_id,
    ) != (plan.job_id, plan.workflow_id, plan.dispatch_id, plan.session_id):
        raise ValueError("formal controller request identity differs from the bridge")
    if not _same_controller_artifact(request.assignment, input_artifact):
        raise ValueError("formal controller assignment differs from controller input")
    if not _same_controller_artifact(
        request.tool_profile, controller_input.phase_tool_profile
    ):
        raise ValueError("formal controller tool profile differs from controller input")
    if len(request.immutable_inputs) != len(expected_inputs) or any(
        not _same_controller_artifact(observed, expected)
        for observed, expected in zip(request.immutable_inputs, expected_inputs, strict=True)
    ):
        raise ValueError("formal controller immutable inputs differ or changed order")
    request_map = {item.path: item.sha256 for item in request.immutable_inputs}
    if request_map != controller_input.immutable_input_sha256:
        raise ValueError("formal controller immutable input map differs from companion input")
    if (
        request.output_root != controller_input.output_root
        or request.allowed_output_paths != controller_input.allowed_output_paths
        or request.expected_output_sha256 != controller_input.expected_output_sha256
    ):
        raise ValueError("formal controller output boundary differs from companion input")


def _load_controller_output_model(
    root: Path,
    result: ControllerResult,
    filename: str,
    model_type: type[BaseModel],
) -> BaseModel:
    """Rehash and parse one named formal controller output."""

    matches = [item for item in result.outputs if PurePosixPath(item.path).name == filename]
    if len(matches) != 1:
        raise ValueError(f"formal controller result must contain one {filename}")
    artifact = matches[0]
    return _read_model(
        root,
        AQV2Artifact(
            artifact_id=artifact.artifact_id,
            kind="controller_output",
            path=artifact.path,
            sha256=artifact.sha256,
            byte_size=artifact.byte_size,
        ),
        model_type,
    )


def _validate_controller_result_material_scope(
    root: Path,
    plan: ImageGeneratedMaterialBridgePlan,
    result: ControllerResult,
) -> None:
    """Reject controller-authored changes outside the single mutable material scope."""

    if result.status != "completed":
        raise ValueError("material promotion requires a completed controller result")
    authored = cast(
        MaterialPlan,
        _load_controller_output_model(root, result, "material_plan.json", MaterialPlan),
    )
    graph = cast(
        MaterialGraphSpec,
        _load_controller_output_model(
            root, result, "material_graph.json", MaterialGraphSpec
        ),
    )
    blueprint_path = validate_codex_image_artifact(root, plan.candidate_material_plan)
    with open(native_io_path(blueprint_path), "rb") as handle:
        blueprint = MaterialPlan.model_validate_json(handle.read())
    baseline = blueprint
    if plan.previous_material_plan is not None:
        baseline_path = validate_codex_image_artifact(root, plan.previous_material_plan)
        with open(native_io_path(baseline_path), "rb") as handle:
            baseline = MaterialPlan.model_validate_json(handle.read())
    authored_by_id = {item.material_id: item for item in authored.materials}
    baseline_by_id = {item.material_id: item for item in baseline.materials}
    blueprint_ids = {item.material_id for item in blueprint.materials}
    if (
        authored.job_id != plan.job_id
        or set(authored_by_id) != blueprint_ids
        or graph.material_id != plan.target_material_ids[0]
    ):
        raise ValueError("formal material outputs changed identity or target scope")
    for material_id in plan.immutable_material_ids:
        if material_id not in baseline_by_id or (
            authored_by_id[material_id].model_dump(mode="json")
            != baseline_by_id[material_id].model_dump(mode="json")
        ):
            raise ValueError("formal material output changed an immutable material")


def _loop_root(root: Path, session_id: str, *, must_exist: bool) -> Path:
    """Resolve the run-owned material-loop companion directory."""

    return ensure_contained_production_path(
        root,
        root / "production" / "autonomy_v2" / session_id / _LOOP_DIR,
        must_exist=must_exist,
    )


def _same_replay(existing: BaseModel, proposed: BaseModel) -> bool:
    """Compare replayed evidence while ignoring only its publication timestamp."""

    return existing.model_dump(mode="json", exclude={"created_at"}) == proposed.model_dump(
        mode="json", exclude={"created_at"}
    )


def _write_or_adopt(
    root: Path,
    path: Path,
    model: BaseModel,
    *,
    kind: str,
    model_type: type[BaseModel],
) -> tuple[BaseModel, CodexImageArtifact]:
    """Publish immutable evidence once or adopt an exact crash-replay equivalent."""

    if path.exists():
        artifact = artifact_for_codex_image(
            root,
            path,
            artifact_id=str(model.contract_id),
            kind=kind,
            media_type="application/json",
        )
        existing = load_codex_image_model(root, artifact, model_type)
        if not _same_replay(existing, model):
            raise FileExistsError(f"immutable material-loop evidence differs: {artifact.path}")
        return existing, artifact
    artifact = write_immutable_codex_image_model(root, path, model, kind=kind)
    return model, artifact


def _bridge_artifacts(plan: ImageGeneratedMaterialBridgePlan) -> list[CodexImageArtifact]:
    """Return the exact direct artifact inventory named by a bridge plan."""

    return _merge_artifact_aliases([
        plan.root_authorization,
        plan.aq_plan,
        plan.aq_profile,
        plan.aq_budget,
        plan.current_state,
        plan.canonical_scene_spec,
        plan.geometry_validation_receipt,
        plan.current_build_provenance,
        plan.provider_profile,
        plan.imagegen_plan,
        plan.assignment,
        plan.completion,
        plan.generation_terminal,
        plan.selected_candidate,
        plan.generated_image_evidence,
        plan.quality_report,
        plan.selection,
        *(
            [plan.companion_selection_receipt]
            if plan.companion_selection_receipt
            else []
        ),
        *(
            [plan.native_core_preparation_receipt]
            if plan.native_core_preparation_receipt
            else []
        ),
        plan.semantic_review,
        plan.normalization_receipt,
        plan.adoption,
        plan.material_authoring_request,
        plan.material_authoring_manifest,
        plan.material_authoring_receipt,
        plan.v05_bridge_receipt,
        *(
            [plan.exact_adoption_preflight]
            if plan.exact_adoption_preflight
            else []
        ),
        *plan.texture_outputs,
        plan.candidate_material_plan,
        plan.material_graph_spec,
        *plan.shader_recipes,
        *plan.texture_manifests,
        *(
            [plan.canonical_material_observation]
            if plan.canonical_material_observation
            else []
        ),
        *([plan.previous_material_plan] if plan.previous_material_plan else []),
        *(
            [plan.canonical_material_absence_evidence]
            if plan.canonical_material_absence_evidence
            else []
        ),
    ], plan.v05_controller_inputs)


def _controller_input_artifacts(
    value: ImageGeneratedMaterialControllerInput,
) -> list[CodexImageArtifact]:
    """Return controller immutable inputs in one stable request order."""

    return _merge_artifact_aliases([
        value.bridge_plan,
        value.current_state,
        value.phase_tool_profile,
        value.root_authorization,
        value.aq_plan,
        value.aq_profile,
        value.aq_budget,
        value.canonical_scene_spec,
        value.geometry_validation_receipt,
        value.current_build_provenance,
        value.provider_profile,
        value.generation_terminal,
        value.selected_candidate,
        value.generated_image_evidence,
        value.quality_report,
        value.selection,
        *(
            [value.companion_selection_receipt]
            if value.companion_selection_receipt
            else []
        ),
        *(
            [value.native_core_preparation_receipt]
            if value.native_core_preparation_receipt
            else []
        ),
        value.semantic_review,
        value.normalization_receipt,
        value.adoption,
        value.material_authoring_request,
        value.material_authoring_manifest,
        value.material_authoring_receipt,
        value.v05_bridge_receipt,
        *(
            [value.exact_adoption_preflight]
            if value.exact_adoption_preflight
            else []
        ),
        *value.texture_outputs,
        value.candidate_material_plan,
        value.material_graph_spec,
        *value.shader_recipes,
        *value.texture_manifests,
        *(
            [value.canonical_material_observation]
            if value.canonical_material_observation
            else []
        ),
        *([value.previous_material_plan] if value.previous_material_plan else []),
        *(
            [value.canonical_material_absence_evidence]
            if value.canonical_material_absence_evidence
            else []
        ),
    ], value.v05_controller_inputs)


def _bridge_controller_input_artifacts(
    plan: ImageGeneratedMaterialBridgePlan,
    plan_artifact: CodexImageArtifact,
    phase_profile: CodexImageArtifact,
) -> list[CodexImageArtifact]:
    """Project the plan into the controller's one authoritative immutable closure."""

    return _merge_artifact_aliases(
        [
            plan_artifact,
            plan.current_state,
            phase_profile,
            plan.root_authorization,
            plan.aq_plan,
            plan.aq_profile,
            plan.aq_budget,
            plan.canonical_scene_spec,
            plan.geometry_validation_receipt,
            plan.current_build_provenance,
            plan.provider_profile,
            plan.generation_terminal,
            plan.selected_candidate,
            plan.generated_image_evidence,
            plan.quality_report,
            plan.selection,
            *(
                [plan.companion_selection_receipt]
                if plan.companion_selection_receipt
                else []
            ),
            *(
                [plan.native_core_preparation_receipt]
                if plan.native_core_preparation_receipt
                else []
            ),
            plan.semantic_review,
            plan.normalization_receipt,
            plan.adoption,
            plan.material_authoring_request,
            plan.material_authoring_manifest,
            plan.material_authoring_receipt,
            plan.v05_bridge_receipt,
            *(
                [plan.exact_adoption_preflight]
                if plan.exact_adoption_preflight
                else []
            ),
            *plan.texture_outputs,
            plan.candidate_material_plan,
            plan.material_graph_spec,
            *plan.shader_recipes,
            *plan.texture_manifests,
            *(
                [plan.canonical_material_observation]
                if plan.canonical_material_observation
                else []
            ),
            *([plan.previous_material_plan] if plan.previous_material_plan else []),
            *(
                [plan.canonical_material_absence_evidence]
                if plan.canonical_material_absence_evidence
                else []
            ),
        ],
        plan.v05_controller_inputs,
    )


def _build_material_controller_input(
    plan: ImageGeneratedMaterialBridgePlan,
    plan_artifact: CodexImageArtifact,
    phase_profile: CodexImageArtifact,
    *,
    created_at: datetime,
) -> ImageGeneratedMaterialControllerInput:
    """Build the deterministic controller assignment from one exact bridge plan."""

    artifacts = _bridge_controller_input_artifacts(plan, plan_artifact, phase_profile)
    immutable_input_sha256 = {item.path: item.sha256 for item in artifacts}
    return ImageGeneratedMaterialControllerInput(
        contract_id=f"material-controller-input-{plan.session_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=stable_json_digest(immutable_input_sha256),
        source_fingerprint=plan_artifact.sha256,
        producer=_PRODUCER,
        provenance=artifacts,
        created_at=created_at,
        bridge_plan=plan_artifact,
        current_state=plan.current_state,
        phase_tool_profile=phase_profile,
        root_authorization=plan.root_authorization,
        aq_plan=plan.aq_plan,
        aq_profile=plan.aq_profile,
        aq_budget=plan.aq_budget,
        canonical_scene_spec=plan.canonical_scene_spec,
        geometry_validation_receipt=plan.geometry_validation_receipt,
        current_build_provenance=plan.current_build_provenance,
        provider_profile=plan.provider_profile,
        generation_terminal=plan.generation_terminal,
        selected_candidate=plan.selected_candidate,
        generated_image_evidence=plan.generated_image_evidence,
        quality_report=plan.quality_report,
        selection=plan.selection,
        companion_selection_receipt=plan.companion_selection_receipt,
        native_core_preparation_receipt=plan.native_core_preparation_receipt,
        semantic_review=plan.semantic_review,
        normalization_receipt=plan.normalization_receipt,
        adoption=plan.adoption,
        material_authoring_request=plan.material_authoring_request,
        material_authoring_manifest=plan.material_authoring_manifest,
        material_authoring_receipt=plan.material_authoring_receipt,
        v05_bridge_receipt=plan.v05_bridge_receipt,
        exact_adoption_preflight=plan.exact_adoption_preflight,
        v05_controller_inputs=plan.v05_controller_inputs,
        texture_outputs=plan.texture_outputs,
        candidate_material_plan=plan.candidate_material_plan,
        material_graph_spec=plan.material_graph_spec,
        shader_recipes=plan.shader_recipes,
        texture_manifests=plan.texture_manifests,
        canonical_material_observation=plan.canonical_material_observation,
        previous_material_plan=plan.previous_material_plan,
        canonical_material_absence_evidence=plan.canonical_material_absence_evidence,
        immutable_input_sha256=immutable_input_sha256,
        source_scene_spec_sha256=plan.canonical_scene_spec_sha256,
        source_material_plan_sha256=(
            plan.canonical_material_observation.sha256
            if plan.canonical_material_observation
            else None
        ),
        uv_fingerprint=plan.uv_fingerprint,
        target_material_ids=plan.target_material_ids,
        target_semantic_ids=plan.target_semantic_ids,
        execution_mode=plan.execution_mode,
        output_root=plan.output_root,
        allowed_output_paths=plan.allowed_output_paths,
        expected_output_sha256=plan.expected_output_sha256,
    )


def _validate_material_controller_input_closure(
    plan: ImageGeneratedMaterialBridgePlan,
    plan_artifact: CodexImageArtifact,
    phase_profile: CodexImageArtifact,
    controller_input: ImageGeneratedMaterialControllerInput,
) -> None:
    """Reject any controller assignment not exactly reproducible from its frozen plan."""

    expected = _build_material_controller_input(
        plan,
        plan_artifact,
        phase_profile,
        created_at=plan.created_at,
    )
    if controller_input != expected:
        raise ValueError("material controller input differs from its frozen bridge closure")
    if controller_input.input_sha256 != stable_json_digest(
        controller_input.immutable_input_sha256
    ):
        raise ValueError("material controller input digest is inconsistent")


def _merge_artifact_aliases(
    direct: list[CodexImageArtifact],
    aliases: list[CodexImageArtifact],
) -> list[CodexImageArtifact]:
    """Merge ordered exact aliases while rejecting path or identifier conflicts."""

    merged: list[CodexImageArtifact] = []
    by_path: dict[str, CodexImageArtifact] = {}
    by_id: dict[str, CodexImageArtifact] = {}
    for artifact in [*direct, *aliases]:
        prior_path = by_path.get(artifact.path)
        prior_id = by_id.get(artifact.artifact_id)
        if prior_path is not None or prior_id is not None:
            prior = prior_path or prior_id
            if prior != artifact:
                raise ValueError("material-loop artifact alias has a conflicting identity")
            continue
        merged.append(artifact)
        by_path[artifact.path] = artifact
        by_id[artifact.artifact_id] = artifact
    return merged


def _quality_terminal_anchor(
    root: Path,
    plan: ImageGeneratedMaterialBridgePlan,
    current: AutonomyStateV2,
) -> AutonomyStateV2:
    """Locate the unique reconstructed AQ state that first appended its quality terminal."""

    if current.quality_terminal is None:
        raise ValueError("post-quality AQ state has no exact quality terminal")
    session_root = ensure_contained_production_path(
        root,
        root / "production" / "autonomy_v2" / plan.session_id,
        must_exist=True,
    )
    chain = _base_aq_state_chain(root, session_root)
    if not chain or chain[-1][0] != current:
        raise ValueError("post-quality AQ state differs from its reconstructed chain")
    anchors = [
        candidate
        for candidate, _artifact in chain
        if candidate.provenance
        and candidate.provenance[-1] == current.quality_terminal
        and candidate.quality_terminal == current.quality_terminal
    ]
    if len(anchors) != 1:
        raise ValueError("quality terminal has no unique AQ transition anchor")
    return anchors[0]


def _current_material_promotion_receipt(
    root: Path,
    plan: ImageGeneratedMaterialBridgePlan,
) -> MaterialPhaseReceiptV2 | None:
    """Find and validate the host receipt that authorizes a changed canonical baseline."""

    status = get_autonomy_v2_status(plan.job_id, plan.session_id)
    state = AutonomyStateV2.model_validate_json(
        json.dumps(status["state"], ensure_ascii=False)
    )
    artifact: AQV2Artifact | None = None
    if (
        state.phase == "quality"
        and state.status == "running"
        and state.next_action == "run_integrated_quality"
        and state.provenance
        and state.provenance[-1].kind == "material_phase_receipt"
    ):
        artifact = state.provenance[-1]
    elif (
        state.phase == "authoring"
        and state.status == "running"
        and state.next_action == "validate_candidate"
    ):
        receipt_path = (
            root
            / "production"
            / "autonomy_v2"
            / plan.session_id
            / "material_phase"
            / f"{state.sequence:04d}"
            / "promotion_receipt.json"
        )
        if os.path.isfile(native_io_path(receipt_path)):
            provisional = artifact_for_v2(
                root,
                receipt_path,
                artifact_id="material-phase-promotion",
                kind="material_phase_receipt",
            )
            parsed = cast(
                MaterialPhaseReceiptV2,
                _read_model(root, provisional, MaterialPhaseReceiptV2),
            )
            artifact = provisional.model_copy(update={"artifact_id": parsed.contract_id})
    elif state.quality_terminal is not None:
        terminal_positions = [
            index
            for index, provenance in enumerate(state.provenance)
            if provenance == state.quality_terminal
        ]
        receipt_positions = [
            index
            for index, provenance in enumerate(state.provenance)
            if provenance.kind == "material_phase_receipt"
        ]
        if (
            len(terminal_positions) != 1
            or len(receipt_positions) != 1
            or receipt_positions[0] >= terminal_positions[0]
        ):
            raise ValueError(
                "post-quality AQ state does not retain one ordered material receipt"
            )
        artifact = state.provenance[receipt_positions[0]]
        anchor = _quality_terminal_anchor(root, plan, state)
        terminal = validate_quality_terminal_v2(root, state.quality_terminal)
        if (
            terminal.job_id,
            terminal.workflow_id,
            terminal.dispatch_id,
            terminal.session_id,
        ) != (
            plan.job_id,
            plan.workflow_id,
            plan.dispatch_id,
            plan.session_id,
        ):
            raise ValueError("quality terminal targets another material-loop session")
        if terminal.status == "quality_approved":
            if (
                terminal.source_freeze is None
                or state.source_freeze != terminal.source_freeze
                or anchor.source_freeze != terminal.source_freeze
                or (anchor.phase, anchor.status, anchor.next_action)
                != ("quality", "quality_approved", "plan_delivery")
            ):
                raise ValueError(
                    "post-quality AQ chain does not retain its exact passed boundary"
                )
            freeze = cast(
                QualityApprovedSourceFreeze,
                _read_model(root, terminal.source_freeze, QualityApprovedSourceFreeze),
            )
            validate_quality_source_freeze(root, freeze)
            if freeze.material_phase_receipt != artifact:
                raise ValueError(
                    "quality source freeze targets another material promotion receipt"
                )
        else:
            expected_state = {
                "review_required": ("terminal", "review_required", "none"),
                "blocked": ("terminal", "blocked", "none"),
                "failed": ("terminal", "failed", "none"),
            }.get(terminal.status)
            if (
                expected_state is None
                or (anchor.phase, anchor.status, anchor.next_action) != expected_state
                or (state.phase, state.status, state.next_action) != expected_state
                or anchor.source_freeze is not None
                or state.source_freeze is not None
            ):
                raise ValueError(
                    "non-passing quality terminal differs from the current AQ boundary"
                )
    if artifact is None:
        return None
    receipt = validate_material_phase_receipt_v2(root, artifact, require_current=True)
    if (
        receipt.job_id,
        receipt.workflow_id,
        receipt.dispatch_id,
        receipt.session_id,
    ) != (
        plan.job_id,
        plan.workflow_id,
        plan.dispatch_id,
        plan.session_id,
    ):
        raise ValueError("material promotion receipt targets another bridge plan")
    return receipt


def _validate_canonical_material_observation(
    root: Path,
    plan: ImageGeneratedMaterialBridgePlan,
) -> bool:
    """Validate the pre-promotion CAS path or its exact host-authorized replacement."""

    canonical = ensure_contained_production_path(
        root,
        root / "analysis" / "material_plan.json",
        must_exist=False,
    )
    current_sha256 = sha256_file(canonical) if canonical.is_file() else None
    observation = plan.canonical_material_observation
    if observation is not None and current_sha256 == observation.sha256:
        validate_codex_image_artifact(root, observation)
        return False
    if observation is None and current_sha256 is None:
        return False
    if current_sha256 != plan.candidate_material_plan.sha256:
        raise ValueError("canonical MaterialPlan differs from bridge baseline and candidate")
    receipt = _current_material_promotion_receipt(root, plan)
    expected_previous = observation.sha256 if observation is not None else None
    if (
        receipt is None
        or receipt.canonical_material_plan_sha256
        != plan.candidate_material_plan.sha256
        or receipt.previous_canonical_material_sha256 != expected_previous
    ):
        raise ValueError("changed canonical MaterialPlan lacks exact host promotion evidence")
    return True


def _validate_bridge_files(
    root: Path,
    plan: ImageGeneratedMaterialBridgePlan,
) -> bool:
    """Rehash bridge dependencies and authorize only the exact promoted CAS replacement."""

    artifacts = _bridge_artifacts(plan)
    if len({item.path for item in artifacts}) != len(artifacts):
        raise ValueError("material bridge dependencies must use distinct paths")
    promoted = _validate_canonical_material_observation(root, plan)
    for artifact in artifacts:
        if promoted and artifact == plan.canonical_material_observation:
            continue
        validate_codex_image_artifact(root, artifact)
    if len(plan.target_material_ids) != 1:
        raise ValueError("the initial ImageGen material bridge supports one material")
    if plan.target_material_ids != plan.mutable_material_ids:
        raise ValueError("only the single target material may be mutable")
    if plan.execution_mode == "exact_adoption":
        expected = {
            plan.candidate_material_plan.sha256,
            plan.material_graph_spec.sha256,
        }
        if set(plan.expected_output_sha256.values()) != expected:
            raise ValueError("exact adoption must bind both candidate content outputs")
    return promoted


def _validate_base_authoring_boundary(
    root: Path,
    bridge_plan: ImageGeneratedMaterialBridgePlan,
    *,
    promoted_material_receipt_artifact: AQV2Artifact | None = None,
) -> None:
    """Replay AQ geometry authority across the authorized material rebuild boundary."""

    plan = cast(
        AutonomyPlanV2,
        _read_model(root, _aq_from_codex(bridge_plan.aq_plan, role="plan"), AutonomyPlanV2),
    )
    budget = cast(
        AutonomyBudgetV2,
        _read_model(
            root,
            _aq_from_codex(bridge_plan.aq_budget, role="budget"),
            AutonomyBudgetV2,
        ),
    )
    state = cast(
        AutonomyStateV2,
        _read_model(
            root,
            _aq_from_codex(bridge_plan.current_state, role="state"),
            AutonomyStateV2,
        ),
    )
    if (plan.job_id, plan.workflow_id, plan.dispatch_id, plan.session_id) != (
        bridge_plan.job_id,
        bridge_plan.workflow_id,
        bridge_plan.dispatch_id,
        bridge_plan.session_id,
    ):
        raise ValueError("material bridge AQ plan identity changed")
    if plan.budget.sha256 != bridge_plan.aq_budget.sha256:
        raise ValueError("material bridge budget is not the plan budget")
    if (
        plan.profile.sha256 != bridge_plan.aq_profile.sha256
        or plan.root_authorization.sha256 != bridge_plan.root_authorization.sha256
    ):
        raise ValueError("material bridge profile or root authorization changed")
    if budget.contract_id != plan.budget.artifact_id:
        raise ValueError("material bridge budget identity changed")
    if (state.phase, state.status, state.next_action) != (
        "authoring",
        "running",
        "execute_controller",
    ):
        raise PermissionError("base AQ state is not authoring/running/execute_controller")
    if state.plan.sha256 != bridge_plan.aq_plan.sha256:
        raise ValueError("material bridge state targets another AQ plan")
    authorization, _current_plan, _current_profile, _current_budget = (
        validate_root_authorization_boundary_v2(
            job_root=root,
            job_id=plan.job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            session_id=plan.session_id,
            root_authorization_artifact=_aq_from_codex(
                bridge_plan.root_authorization
            ),
        )
    )
    if (
        bridge_plan.requested_delivery_profiles != ["none"]
        and bridge_plan.requested_delivery_profiles
        != authorization.requested_delivery_profiles
    ):
        raise ValueError("material bridge delivery profiles exceed root authorization")
    geometry = [
        item
        for item in state.provenance
        if item.kind == "geometry_candidate_validation_receipt"
    ]
    if len(geometry) != 1 or state.provenance[-1] != geometry[0]:
        raise ValueError("current AQ state must end at one geometry validation receipt")
    if promoted_material_receipt_artifact is None:
        receipt = validate_geometry_candidate_validation_receipt_v2(
            root,
            plan,
            geometry[0],
        )
    else:
        receipt = cast(
            GeometryCandidateValidationReceiptV2,
            _read_model(
                root,
                geometry[0],
                GeometryCandidateValidationReceiptV2,
            ),
        )
        material_receipt = cast(
            MaterialPhaseReceiptV2,
            _read_model(
                root,
                promoted_material_receipt_artifact,
                MaterialPhaseReceiptV2,
            ),
        )
        current_blend = artifact_for_v2(
            root,
            root / "blender" / "scene.blend",
            artifact_id=material_receipt.authoring_blend_snapshot.artifact_id,
            kind="canonical_blend",
        )
        receipt, _validated_material = validate_quality_promotion_evidence_v2(
            job_root=root,
            job_id=plan.job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            session_id=plan.session_id,
            geometry_candidate_validation_receipt=geometry[0],
            material_phase_receipt=promoted_material_receipt_artifact,
            geometry_intent_survival=receipt.geometry_intent_survival,
            scene_spec=receipt.canonical_scene_spec,
            authoring_blend=current_blend,
            build_provenance=material_receipt.build_provenance_snapshot,
            material_plan=material_receipt.canonical_material_snapshot,
        )
    if (
        bridge_plan.geometry_validation_receipt.sha256 != geometry[0].sha256
        or bridge_plan.canonical_scene_spec.sha256
        != receipt.canonical_scene_spec.sha256
        or bridge_plan.current_build_provenance.sha256
        != receipt.candidate_build_provenance.sha256
    ):
        raise ValueError("material bridge geometry, SceneSpec, or build evidence is stale")


def _validate_image_and_authoring_boundary(
    root: Path,
    bridge_plan: ImageGeneratedMaterialBridgePlan,
) -> None:
    """Replay ImageGen and the additive normalized material-authoring chain."""

    expected_authoring_kinds = {
        "material_authoring_request": (
            "codex-image-normalized-material-authoring-request"
        ),
        "material_authoring_manifest": (
            "codex-image-normalized-authored-material-manifest"
        ),
        "material_authoring_receipt": (
            "codex-image-normalized-material-authoring-receipt"
        ),
    }
    for field, expected_kind in expected_authoring_kinds.items():
        if getattr(bridge_plan, field).kind != expected_kind:
            raise ValueError(f"material bridge {field} must have kind {expected_kind}")

    status = get_codex_image_phase_status(root, bridge_plan.session_id)
    state_payload = status.get("state")
    if not status.get("exists") or not isinstance(state_payload, dict):
        raise ValueError("Codex ImageGen overlay does not exist")
    if (state_payload.get("status"), state_payload.get("next_action")) != (
        "adopted",
        "controller_promotion_required",
    ):
        raise PermissionError("Codex ImageGen overlay is not at controller promotion")
    overlay_artifact = CodexImageArtifact.model_validate(state_payload["artifact"])
    overlay = load_codex_image_model(root, overlay_artifact, AutonomyCodexImageOverlay)
    required_overlay = [
        overlay.assignment,
        overlay.completion,
        overlay.selection,
        overlay.material_adoption,
        overlay.material_authoring_receipt,
        overlay.generation_terminal,
    ]
    if any(item is None for item in required_overlay):
        raise ValueError("adopted ImageGen overlay omits required staging evidence")
    if (
        overlay.generation_plan != bridge_plan.imagegen_plan
        or overlay.provider_profile != bridge_plan.provider_profile
        or overlay.assignment != bridge_plan.assignment
        or overlay.completion != bridge_plan.completion
        or overlay.selection != bridge_plan.selection
        or overlay.material_adoption != bridge_plan.adoption
        or overlay.material_authoring_receipt != bridge_plan.material_authoring_receipt
        or overlay.generation_terminal != bridge_plan.generation_terminal
    ):
        raise ValueError("material bridge differs from the current ImageGen overlay")
    selection = load_codex_image_model(
        root, bridge_plan.selection, CodexImageGenerationSelection
    )
    if (
        selection.outcome != "selected"
        or selection.selected_candidate != bridge_plan.selected_candidate
        or selection.selected_quality_report != bridge_plan.quality_report
    ):
        raise ValueError("material bridge selection binding changed")
    if selection.candidate_count > 1:
        if bridge_plan.companion_selection_receipt is None:
            raise ValueError(
                "multi-candidate material promotion omits companion ranking closure"
            )
        companion = load_codex_image_model(
            root,
            bridge_plan.companion_selection_receipt,
            CodexImageCompanionSelectionReceipt,
        )
        validate_codex_imagegen_companion_selection(root, companion)
        selected_decisions = [
            item for item in companion.decisions if item.outcome == "selected"
        ]
        if (
            companion.core_selection != bridge_plan.selection
            or companion.outcome != "selected"
            or companion.selected_candidate != bridge_plan.selected_candidate
            or companion.selected_quality_report != bridge_plan.quality_report
            or len(selected_decisions) != 1
            or selected_decisions[0].semantic_review != bridge_plan.semantic_review
        ):
            raise ValueError("multi-candidate companion selection closure changed")
    elif bridge_plan.companion_selection_receipt is not None:
        raise ValueError("single-candidate legacy selection cannot claim companion ranking")
    adoption = load_codex_image_model(
        root, bridge_plan.adoption, ImageToMaterialAdoption
    )
    if (
        adoption.selection != bridge_plan.selection
        or adoption.selected_candidate != bridge_plan.selected_candidate
        or adoption.generated_image_evidence != bridge_plan.generated_image_evidence
        or adoption.quality_report != bridge_plan.quality_report
        or adoption.target_material_ids != bridge_plan.target_material_ids
    ):
        raise ValueError("material bridge adoption binding changed")
    generated = load_codex_image_model(
        root,
        bridge_plan.generated_image_evidence,
        CodexGeneratedImageEvidence,
    )
    if (
        generated.candidate_id != bridge_plan.selected_candidate_id
        or generated.generated_file.artifact.sha256 != adoption.selected_source_sha256
    ):
        raise ValueError("selected generated image evidence is stale")
    validate_native_core_preparation_binding(
        job_root=root,
        assignment_artifact=bridge_plan.assignment,
        core_completion=bridge_plan.completion,
        core_candidate=bridge_plan.selected_candidate,
        core_generated_image_evidence=bridge_plan.generated_image_evidence,
        core_quality_report=bridge_plan.quality_report,
        core_selection=bridge_plan.selection,
        preparation_receipt=bridge_plan.native_core_preparation_receipt,
    )
    normalization = load_codex_image_model(
        root,
        bridge_plan.normalization_receipt,
        ImageGenNativeNormalizationReceipt,
    )
    normalization_plan = load_codex_image_model(
        root,
        normalization.plan,
        ImageGenNativeNormalizationPlan,
    )
    validate_native_normalization_receipt(root, normalization_plan, normalization)
    if normalization.source_image != generated.generated_file.artifact:
        raise ValueError("normalization source is not the selected generated image")
    if normalization.status == "review_required" or normalization.normalized_image is None:
        raise PermissionError("native image normalization is not promotion-ready")
    semantic = load_codex_image_model(
        root,
        bridge_plan.semantic_review,
        CodexImageSemanticReview,
    )
    validate_codex_image_semantic_review(
        root,
        semantic,
        expected_job_id=bridge_plan.job_id,
        expected_workflow_id=bridge_plan.workflow_id,
        expected_dispatch_id=bridge_plan.dispatch_id,
        expected_candidate_id=bridge_plan.selected_candidate_id,
        expected_session_id=bridge_plan.session_id,
        expected_reviewed_image_sha256=normalization.normalized_image.sha256,
    )
    if semantic.outcome != "passed":
        raise PermissionError("semantic material review is not passed")
    authoring_receipt = load_codex_image_model(
        root,
        bridge_plan.material_authoring_receipt,
        CodexImageNormalizedMaterialAuthoringReceiptV010,
    )
    request = load_codex_image_model(
        root,
        bridge_plan.material_authoring_request,
        CodexImageNormalizedMaterialAuthoringRequestV010,
    )
    base_request = request.base_request
    effective_source = request.effective_source
    v05_receipt = load_codex_image_model(
        root, bridge_plan.v05_bridge_receipt, CodexImageV05BridgeReceipt
    )
    validate_codex_image_v05_bridge(root, v05_receipt)
    _validate_exact_adoption_evidence(root, bridge_plan, v05_receipt)
    v05_contract_snapshots = [
        v05_receipt.baseline_material_plan_snapshot
        if item.kind == "v05-material-plan"
        else item
        for item in base_request.source_v05_contracts
    ]
    validate_codex_image_normalized_material_candidate(
        root,
        authoring_receipt,
        source_v05_contract_overrides=v05_contract_snapshots,
    )
    if (
        authoring_receipt.run_id != bridge_plan.material_authoring_run_id
        or base_request.material_id != bridge_plan.target_material_ids[0]
        or base_request.source.artifact.sha256 != normalization.source_image.sha256
        or effective_source.artifact.sha256 != normalization.normalized_image.sha256
        or base_request.uv_identity.uv_fingerprint != bridge_plan.uv_fingerprint
    ):
        raise ValueError("material authoring request, normalization, or UV binding changed")
    if (
        semantic.assignment != bridge_plan.assignment
        or semantic.deterministic_quality_report != bridge_plan.quality_report
        or semantic.material_family != base_request.material_family
    ):
        raise ValueError("semantic review is not bound to this assignment and material family")
    if (
        authoring_receipt.request.path != bridge_plan.material_authoring_request.path
        or authoring_receipt.request.sha256 != bridge_plan.material_authoring_request.sha256
        or authoring_receipt.manifest.path != bridge_plan.material_authoring_manifest.path
        or authoring_receipt.manifest.sha256 != bridge_plan.material_authoring_manifest.sha256
    ):
        raise ValueError("material authoring receipt inventory changed")
    if (
        v05_receipt.job_id,
        v05_receipt.workflow_id,
        v05_receipt.dispatch_id,
        v05_receipt.session_id,
        v05_receipt.profile_id,
        v05_receipt.provider_id,
        v05_receipt.target_material_id,
    ) != (
        bridge_plan.job_id,
        bridge_plan.workflow_id,
        bridge_plan.dispatch_id,
        bridge_plan.session_id,
        bridge_plan.profile_id,
        bridge_plan.provider_id,
        bridge_plan.target_material_ids[0],
    ):
        raise ValueError("V0.5 bridge receipt identity differs from the material loop")
    if (
        _codex_from_exact(v05_receipt.source_authoring_receipt)
        != bridge_plan.material_authoring_receipt
        or _codex_from_exact(v05_receipt.source_authoring_request)
        != bridge_plan.material_authoring_request
        or _codex_from_exact(v05_receipt.source_authoring_manifest)
        != bridge_plan.material_authoring_manifest
        or _codex_from_exact(v05_receipt.source_scene_spec)
        != bridge_plan.canonical_scene_spec
        or (
            _codex_from_exact(v05_receipt.source_material_plan)
            if v05_receipt.previous_canonical_material_plan is not None
            else None
        )
        != bridge_plan.canonical_material_observation
    ):
        raise ValueError("V0.5 bridge source chain differs from the material loop")
    expected_v05_inputs = [
        _codex_from_exact(item.artifact) for item in v05_receipt.controller_inputs
    ]
    expected_previous = (
        _codex_from_exact(v05_receipt.previous_canonical_material_plan)
        if v05_receipt.previous_canonical_material_plan is not None
        else None
    )
    expected_absence = (
        _codex_from_exact(v05_receipt.canonical_material_absence_evidence)
        if v05_receipt.canonical_material_absence_evidence is not None
        else None
    )
    direct_textures = {
        (item.path, item.sha256) for item in bridge_plan.texture_outputs
    }
    expected_textures = {
        (item.path, item.sha256) for item in authoring_receipt.outputs
    }
    if (
        direct_textures != expected_textures
        or bridge_plan.v05_controller_inputs != expected_v05_inputs
        or bridge_plan.previous_material_plan != expected_previous
        or bridge_plan.canonical_material_absence_evidence != expected_absence
        or (
            v05_receipt.candidate_material_plan.path,
            v05_receipt.candidate_material_plan.sha256,
        )
        != (
            bridge_plan.candidate_material_plan.path,
            bridge_plan.candidate_material_plan.sha256,
        )
        or (
            v05_receipt.candidate_material_graph.path,
            v05_receipt.candidate_material_graph.sha256,
        )
        != (
            bridge_plan.material_graph_spec.path,
            bridge_plan.material_graph_spec.sha256,
        )
        or {(item.path, item.sha256) for item in bridge_plan.shader_recipes}
        != {(v05_receipt.shader_recipe.path, v05_receipt.shader_recipe.sha256)}
        or {(item.path, item.sha256) for item in bridge_plan.texture_manifests}
        != {(v05_receipt.texture_manifest.path, v05_receipt.texture_manifest.sha256)}
        or v05_receipt.expected_output_sha256 != bridge_plan.expected_output_sha256
    ):
        raise ValueError("V0.5 bridge dependencies or controller blueprints changed")
    scene_path = validate_codex_image_artifact(root, bridge_plan.canonical_scene_spec)
    with open(native_io_path(scene_path), "rb") as handle:
        scene = SceneSpec.model_validate_json(handle.read())
    candidate_path = validate_codex_image_artifact(
        root, bridge_plan.candidate_material_plan
    )
    with open(native_io_path(candidate_path), "rb") as handle:
        candidate_plan = MaterialPlan.model_validate_json(handle.read())
    scene_material_ids = {item.id for item in scene.materials}
    candidate_material_ids = {item.material_id for item in candidate_plan.materials}
    if (
        scene.job_id != bridge_plan.job_id
        or candidate_plan.job_id != bridge_plan.job_id
        or candidate_plan.stage != "authored"
        or candidate_material_ids != scene_material_ids
        or bridge_plan.target_material_ids[0] not in candidate_material_ids
        or bridge_plan.target_semantic_ids != [base_request.uv_identity.semantic_id]
        or set(bridge_plan.immutable_material_ids)
        != scene_material_ids - set(bridge_plan.mutable_material_ids)
    ):
        raise ValueError("SceneSpec, UV semantic, or MaterialPlan identity scope changed")


def _graph_dependency_artifacts(graph: MaterialGraphSpec) -> list[MaterialGraphArtifact]:
    """Collect every exact graph dependency needed by the fixed Blender compiler."""

    artifacts: list[MaterialGraphArtifact] = list(graph.provenance.inputs)
    for channel in graph.base_channels:
        if channel.image is not None:
            artifacts.append(channel.image)
    for layer in graph.layers:
        for channel in layer.channels:
            if channel.image is not None:
                artifacts.append(channel.image)
        mask = layer.mask
        image = getattr(mask, "image", None)
        if image is not None:
            artifacts.append(image)
    artifacts.append(graph.preview_lighting.reference_source)
    return artifacts


def _copy_exact_preflight_input(
    root: Path,
    source: Path,
    destination: Path,
) -> None:
    """Copy one immutable preflight input once and verify byte identity."""

    safe_source = ensure_contained_production_path(root, source, must_exist=True)
    safe_parent = ensure_contained_production_path(
        root,
        destination.parent,
        must_exist=False,
    )
    safe_destination = ensure_contained_production_path(
        root,
        destination,
        must_exist=False,
    )
    os.makedirs(native_io_path(safe_parent), exist_ok=True)
    safe_parent = ensure_contained_production_path(root, safe_parent, must_exist=True)
    safe_destination = ensure_contained_production_path(
        root,
        safe_destination,
        must_exist=False,
    )
    if os.path.exists(native_io_path(safe_destination)):
        if not os.path.isfile(native_io_path(safe_destination)) or sha256_file(
            safe_destination
        ) != sha256_file(safe_source):
            raise FileExistsError("exact-adoption shadow input conflicts with source bytes")
        return
    shutil.copyfile(native_io_path(safe_source), native_io_path(safe_destination))
    safe_destination = ensure_contained_production_path(
        root,
        safe_destination,
        must_exist=True,
    )
    if sha256_file(safe_destination) != sha256_file(safe_source):
        raise RuntimeError("exact-adoption shadow input copy changed bytes")


def _codex_artifact_for_preflight_file(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    media_type: str,
) -> CodexImageArtifact:
    """Bind one published shadow or compiler file to a short stable artifact identity."""

    return artifact_for_codex_image(
        root,
        path,
        artifact_id=artifact_id,
        kind=kind,
        media_type=media_type,
    )


def _build_exact_adoption_preflight_receipt(
    root: Path,
    *,
    preflight_id: str,
    v05_receipt: CodexImageV05BridgeReceipt,
    v05_receipt_artifact: CodexImageArtifact,
    created_at: datetime,
) -> CodexImageV05ExactAdoptionPreflightReceipt:
    """Reconstruct one preflight receipt from a fully published shadow compiler run."""

    preflight_root_rel = codex_image_v05_exact_adoption_preflight_root_path(
        v05_receipt.session_id,
        preflight_id,
    )
    shadow_root_rel = f"{preflight_root_rel}/shadow_job"
    shadow_root = ensure_contained_production_path(
        root,
        root.joinpath(*shadow_root_rel.split("/")),
        must_exist=True,
    )
    compile_run_root = "compile"
    bundle = MaterialGraphCompilerService(shadow_root).validate_compile_run(
        run_root=compile_run_root
    )
    candidate_plan = _codex_from_exact(v05_receipt.candidate_material_plan)
    candidate_graph = _codex_from_exact(v05_receipt.candidate_material_graph)
    shadow_plan_path = shadow_root.joinpath(
        *v05_receipt.candidate_material_plan.path.split("/")
    )
    shadow_graph_path = shadow_root.joinpath(
        *v05_receipt.candidate_material_graph.path.split("/")
    )
    short_id = stable_json_digest(preflight_id)[:16]
    shadow_plan = _codex_artifact_for_preflight_file(
        root,
        shadow_plan_path,
        artifact_id=f"preflight-plan-{short_id}",
        kind="v05-exact-adoption-shadow-material-plan",
        media_type=candidate_plan.media_type,
    )
    shadow_graph = _codex_artifact_for_preflight_file(
        root,
        shadow_graph_path,
        artifact_id=f"preflight-graph-{short_id}",
        kind="v05-exact-adoption-shadow-material-graph",
        media_type=candidate_graph.media_type,
    )
    compile_root = shadow_root.joinpath(*compile_run_root.split("/"))
    report_artifact = _codex_artifact_for_preflight_file(
        root,
        compile_root / "compile_report.json",
        artifact_id=f"preflight-report-{short_id}",
        kind="v05-exact-adoption-compile-report",
        media_type="application/json",
    )
    compile_artifacts = [
        _codex_artifact_for_preflight_file(
            root,
            compile_root.joinpath(*item.path.split("/")),
            artifact_id=f"preflight-{item.role}-{short_id}",
            kind=f"v05-exact-adoption-{item.role.replace('_', '-')}",
            media_type=(
                "application/x-blender"
                if item.role == "compiled_blend"
                else "application/json"
            ),
        )
        for item in bundle.report.artifacts
    ]
    provenance = _merge_artifact_aliases(
        [
            v05_receipt_artifact,
            candidate_plan,
            candidate_graph,
            shadow_plan,
            shadow_graph,
            report_artifact,
            *compile_artifacts,
        ],
        [],
    )
    return CodexImageV05ExactAdoptionPreflightReceipt(
        contract_id=preflight_id,
        preflight_id=preflight_id,
        job_id=v05_receipt.job_id,
        workflow_id=v05_receipt.workflow_id,
        dispatch_id=v05_receipt.dispatch_id,
        session_id=v05_receipt.session_id,
        input_sha256=exact_adoption_preflight_input_sha256(
            v05_bridge_receipt=v05_receipt_artifact,
            candidate_material_plan=candidate_plan,
            material_graph_spec=candidate_graph,
            shadow_root=shadow_root_rel,
            shadow_candidate_material_plan=shadow_plan,
            shadow_material_graph_spec=shadow_graph,
            compile_run_root=compile_run_root,
            graph_compile_report=report_artifact,
            compile_artifacts=compile_artifacts,
            material_id=bundle.report.material_id,
            graph_id=bundle.report.graph_id,
        ),
        source_fingerprint=candidate_graph.sha256,
        producer=_PRODUCER,
        provenance=provenance,
        created_at=created_at,
        v05_bridge_receipt=v05_receipt_artifact,
        candidate_material_plan=candidate_plan,
        material_graph_spec=candidate_graph,
        shadow_root=shadow_root_rel,
        shadow_candidate_material_plan=shadow_plan,
        shadow_material_graph_spec=shadow_graph,
        compile_run_root=compile_run_root,
        graph_compile_report=report_artifact,
        compile_artifacts=compile_artifacts,
        material_id=bundle.report.material_id,
        graph_id=bundle.report.graph_id,
    )


def validate_codex_image_v05_exact_adoption_preflight(
    job_root: Path,
    receipt: CodexImageV05ExactAdoptionPreflightReceipt,
) -> CodexImageV05ExactAdoptionPreflightReceipt:
    """Replay the exact V0.5 shadow and actual Blender compile evidence recursively."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    v05_receipt = load_codex_image_model(
        root,
        receipt.v05_bridge_receipt,
        CodexImageV05BridgeReceipt,
    )
    validate_codex_image_v05_bridge(root, v05_receipt)
    for artifact in receipt.provenance:
        validate_codex_image_artifact(root, artifact)
    if (
        receipt.candidate_material_plan
        != _codex_from_exact(v05_receipt.candidate_material_plan)
        or receipt.material_graph_spec
        != _codex_from_exact(v05_receipt.candidate_material_graph)
    ):
        raise ValueError("exact-adoption preflight targets another V0.5 candidate")
    shadow_root = ensure_contained_production_path(
        root,
        root.joinpath(*receipt.shadow_root.split("/")),
        must_exist=True,
    )
    bundle = MaterialGraphCompilerService(shadow_root).validate_compile_run(
        run_root=receipt.compile_run_root
    )
    report = load_codex_image_model(
        root,
        receipt.graph_compile_report,
        MaterialGraphCompileReport,
    )
    if report != bundle.report:
        raise ValueError("exact-adoption preflight compile report differs from replay")
    compile_prefix = f"{receipt.shadow_root}/{receipt.compile_run_root}/"
    expected_compile = {
        f"{compile_prefix}{item.path}": (item.sha256, item.byte_size)
        for item in report.artifacts
    }
    observed_compile = {
        item.path: (item.sha256, item.byte_size) for item in receipt.compile_artifacts
    }
    if observed_compile != expected_compile:
        raise ValueError("exact-adoption preflight compiler artifact inventory changed")
    graph = cast(
        MaterialGraphSpec,
        load_codex_image_model(root, receipt.material_graph_spec, MaterialGraphSpec),
    )
    plan = cast(
        MaterialPlan,
        load_codex_image_model(root, receipt.candidate_material_plan, MaterialPlan),
    )
    material_inputs = [
        item for item in graph.provenance.inputs if item.role == "material_plan"
    ]
    if (
        report.status != "passed"
        or not report.ok
        or report.graph_id != graph.graph_id
        or report.material_id != graph.material_id
        or receipt.graph_id != graph.graph_id
        or receipt.material_id != graph.material_id
        or len(material_inputs) != 1
        or material_inputs[0].sha256 != receipt.candidate_material_plan.sha256
        or graph.material_id not in {item.material_id for item in plan.materials}
    ):
        raise ValueError("exact-adoption preflight graph or material identity changed")
    shadow_material_path = shadow_root.joinpath(*material_inputs[0].path.split("/"))
    if sha256_file(shadow_material_path) != receipt.candidate_material_plan.sha256:
        raise ValueError("exact-adoption shadow MaterialPlan dependency changed")
    if (
        receipt.shadow_candidate_material_plan.sha256
        != receipt.candidate_material_plan.sha256
        or receipt.shadow_material_graph_spec.sha256
        != receipt.material_graph_spec.sha256
    ):
        raise ValueError("exact-adoption shadow source bytes changed")
    return receipt


def publish_codex_image_v05_exact_adoption_preflight(
    job_root: Path,
    *,
    preflight_id: str,
    v05_bridge_receipt_artifact: CodexImageArtifact,
    created_at: datetime | None = None,
) -> tuple[CodexImageV05ExactAdoptionPreflightReceipt, CodexImageArtifact]:
    """Compile exact graph bytes in a private shadow without a ControllerResult or write."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    v05_receipt = load_codex_image_model(
        root,
        v05_bridge_receipt_artifact,
        CodexImageV05BridgeReceipt,
    )
    validate_codex_image_v05_bridge(root, v05_receipt)
    final_root_rel = codex_image_v05_exact_adoption_preflight_root_path(
        v05_receipt.session_id,
        preflight_id,
    )
    final_root = ensure_contained_production_path(
        root,
        root.joinpath(*final_root_rel.split("/")),
        must_exist=False,
    )
    final_parent = ensure_contained_production_path(
        root,
        final_root.parent,
        must_exist=False,
    )
    receipt_path = ensure_contained_production_path(
        root,
        root.joinpath(
            *codex_image_v05_exact_adoption_preflight_receipt_path(
                v05_receipt.session_id,
                preflight_id,
            ).split("/")
        ),
        must_exist=False,
    )
    if os.path.isfile(native_io_path(receipt_path)):
        artifact = artifact_for_codex_image(
            root,
            receipt_path,
            artifact_id=preflight_id,
            kind="codex-image-v05-exact-adoption-preflight",
            media_type="application/json",
        )
        existing = load_codex_image_model(
            root,
            artifact,
            CodexImageV05ExactAdoptionPreflightReceipt,
        )
        if existing.v05_bridge_receipt != v05_bridge_receipt_artifact:
            raise FileExistsError("existing exact-adoption preflight targets another bridge")
        return validate_codex_image_v05_exact_adoption_preflight(root, existing), artifact
    if not os.path.isdir(native_io_path(final_root)):
        os.makedirs(native_io_path(final_parent), exist_ok=True)
        final_parent = ensure_contained_production_path(
            root,
            final_parent,
            must_exist=True,
        )
        final_root = ensure_contained_production_path(
            root,
            final_root,
            must_exist=False,
        )
        stage = ensure_contained_production_path(
            root,
            final_parent / f".p-{uuid4().hex[:8]}",
            must_exist=False,
        )
        shadow_root = ensure_contained_production_path(
            root,
            stage / "shadow_job",
            must_exist=False,
        )
        os.makedirs(native_io_path(shadow_root), exist_ok=False)
        shadow_root = ensure_contained_production_path(
            root,
            shadow_root,
            must_exist=True,
        )
        try:
            graph_path = validate_codex_image_artifact(
                root,
                _codex_from_exact(v05_receipt.candidate_material_graph),
            )
            plan_path = validate_codex_image_artifact(
                root,
                _codex_from_exact(v05_receipt.candidate_material_plan),
            )
            graph = MaterialGraphSpec.model_validate_json(
                Path(native_io_path(graph_path)).read_bytes()
            )
            _copy_exact_preflight_input(
                root,
                graph_path,
                shadow_root.joinpath(*v05_receipt.candidate_material_graph.path.split("/")),
            )
            for dependency in _graph_dependency_artifacts(graph):
                dependency_path = dependency.path
                dependency_sha256 = dependency.sha256
                if dependency_sha256 == v05_receipt.candidate_material_plan.sha256:
                    source = plan_path
                else:
                    source = ensure_contained_production_path(
                        root,
                        root.joinpath(*dependency_path.split("/")),
                        must_exist=True,
                    )
                    if sha256_file(source) != dependency_sha256:
                        raise ValueError(
                            f"exact-adoption graph dependency changed: {dependency_path}"
                        )
                _copy_exact_preflight_input(
                    root,
                    source,
                    shadow_root.joinpath(*dependency_path.split("/")),
                )
            _copy_exact_preflight_input(
                root,
                plan_path,
                shadow_root.joinpath(*v05_receipt.candidate_material_plan.path.split("/")),
            )
            compile_run_root = "compile"
            shadow_root = ensure_contained_production_path(
                root,
                shadow_root,
                must_exist=True,
            )
            shadow_native = Path(native_io_path(shadow_root))
            MaterialGraphCompilerService(shadow_native).compile_run(
                graph_spec_path=v05_receipt.candidate_material_graph.path,
                run_root=compile_run_root,
                run_id=preflight_id,
            )
            stage = ensure_contained_production_path(root, stage, must_exist=True)
            final_parent = ensure_contained_production_path(
                root,
                final_parent,
                must_exist=True,
            )
            final_root = ensure_contained_production_path(
                root,
                final_root,
                must_exist=False,
            )
            os.rename(native_io_path(stage), native_io_path(final_root))
            final_root = ensure_contained_production_path(
                root,
                final_root,
                must_exist=True,
            )
        except Exception:
            try:
                safe_stage = ensure_contained_production_path(
                    root,
                    stage,
                    must_exist=True,
                )
            except (FileNotFoundError, ValueError):
                safe_stage = None
            if safe_stage is not None and os.path.isdir(native_io_path(safe_stage)):
                shutil.rmtree(native_io_path(safe_stage), ignore_errors=True)
            raise
    receipt = _build_exact_adoption_preflight_receipt(
        root,
        preflight_id=preflight_id,
        v05_receipt=v05_receipt,
        v05_receipt_artifact=v05_bridge_receipt_artifact,
        created_at=created_at or datetime.now(UTC),
    )
    artifact = write_immutable_codex_image_model(
        root,
        receipt_path,
        receipt,
        kind="codex-image-v05-exact-adoption-preflight",
    )
    return validate_codex_image_v05_exact_adoption_preflight(root, receipt), artifact


def _validate_exact_adoption_evidence(
    root: Path,
    bridge_plan: ImageGeneratedMaterialBridgePlan,
    v05_receipt: CodexImageV05BridgeReceipt,
) -> None:
    """Require a separate actual compile while preserving the staging receipt's meaning."""

    if bridge_plan.execution_mode != "exact_adoption":
        return
    if bridge_plan.exact_adoption_preflight is None:
        raise PermissionError(
            "exact adoption requires an independently precompiled material preflight"
        )
    preflight = load_codex_image_model(
        root,
        bridge_plan.exact_adoption_preflight,
        CodexImageV05ExactAdoptionPreflightReceipt,
    )
    validate_codex_image_v05_exact_adoption_preflight(root, preflight)
    if (
        not v05_receipt.staging_only
        or v05_receipt.blender_compilation_status != "not_run"
        or v05_receipt.controller_result_created is not False
        or preflight.v05_bridge_receipt != bridge_plan.v05_bridge_receipt
        or preflight.candidate_material_plan != bridge_plan.candidate_material_plan
        or preflight.material_graph_spec != bridge_plan.material_graph_spec
    ):
        raise PermissionError(
            "exact adoption preflight cannot reinterpret or drift from V0.5 staging"
        )


def _material_phase_profile(
    root: Path,
    plan: ImageGeneratedMaterialBridgePlan,
) -> CodexImageArtifact:
    """Select and validate the one existing material-authoring phase profile."""

    aq_plan = cast(
        AutonomyPlanV2,
        _read_model(root, _aq_from_codex(plan.aq_plan, role="plan"), AutonomyPlanV2),
    )
    candidates: list[CodexImageArtifact] = []
    for item in aq_plan.phase_tool_profiles:
        profile = cast(PhaseToolProfile, _read_model(root, item, PhaseToolProfile))
        if profile.profile_id == "material_authoring":
            candidates.append(_codex_from_aq(root, item))
            if profile.allowed_output_paths != plan.allowed_output_paths:
                raise ValueError("bridge outputs differ from the material phase profile")
    if len(candidates) != 1:
        raise ValueError("AQ v2 plan must name one material-authoring phase profile")
    return candidates[0]


def _make_state(
    plan: ImageGeneratedMaterialBridgePlan,
    plan_artifact: CodexImageArtifact,
    controller_input_artifact: CodexImageArtifact,
    *,
    sequence: int,
    status: str,
    budget_usage: ImageMaterialLoopBudgetUsage,
    created_at: datetime,
    previous: tuple[CodexImageMaterialLoopState, CodexImageArtifact] | None = None,
    promotion_receipt: CodexImageArtifact | None = None,
    material_phase_receipt: CodexImageArtifact | None = None,
    base_state: CodexImageArtifact | None = None,
    failure_evidence: CodexImageArtifact | None = None,
    review_evidence: CodexImageArtifact | None = None,
    latest_failure: str | None = None,
) -> CodexImageMaterialLoopState:
    """Construct one hash-bound append-only companion state."""

    previous_artifact = previous[1] if previous else None
    provenance = [
        plan_artifact,
        controller_input_artifact,
        *([previous_artifact] if previous_artifact else []),
        *([promotion_receipt] if promotion_receipt else []),
        *([material_phase_receipt] if material_phase_receipt else []),
        *([base_state] if base_state else []),
        *([failure_evidence] if failure_evidence else []),
        *([review_evidence] if review_evidence else []),
    ]
    state_id = f"material-loop-state-{plan.session_id}-{sequence:04d}"
    return CodexImageMaterialLoopState(
        contract_id=state_id,
        state_id=state_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=material_loop_state_input_sha256(
            sequence=sequence,
            previous_state_sha256=(previous_artifact.sha256 if previous_artifact else None),
            status=cast(Any, status),
            bridge_plan_sha256=plan_artifact.sha256,
            controller_input_sha256=controller_input_artifact.sha256,
            promotion_receipt_sha256=(promotion_receipt.sha256 if promotion_receipt else None),
            material_phase_receipt_sha256=(
                material_phase_receipt.sha256 if material_phase_receipt else None
            ),
            base_state_sha256=(base_state.sha256 if base_state else None),
            failure_evidence_sha256=(
                failure_evidence.sha256 if failure_evidence else None
            ),
            review_evidence_sha256=(review_evidence.sha256 if review_evidence else None),
            latest_failure=latest_failure,
            budget_usage=budget_usage,
        ),
        source_fingerprint=plan_artifact.sha256,
        producer=_PRODUCER,
        provenance=provenance,
        created_at=created_at,
        previous_state=previous_artifact,
        previous_state_sha256=(previous_artifact.sha256 if previous_artifact else None),
        sequence=sequence,
        status=cast(Any, status),
        bridge_plan=plan_artifact,
        controller_input=controller_input_artifact,
        promotion_receipt=promotion_receipt,
        material_phase_receipt=material_phase_receipt,
        base_state=base_state,
        failure_evidence=failure_evidence,
        review_evidence=review_evidence,
        budget_usage=budget_usage,
        latest_failure=latest_failure,
        promotion_consumed_sha256=(
            promotion_receipt.sha256 if promotion_receipt else None
        ),
    )


def _state_chain(
    root: Path,
    loop_root: Path,
    plan: ImageGeneratedMaterialBridgePlan,
    plan_artifact: CodexImageArtifact,
    controller_input_artifact: CodexImageArtifact,
) -> list[tuple[CodexImageMaterialLoopState, CodexImageArtifact]]:
    """Strictly reconstruct the contiguous append-only material-loop journal."""

    states_root = ensure_contained_codex_image_path(
        root, loop_root / "states", must_exist=True
    )
    entries = sorted(path for path in states_root.iterdir() if path.is_file())
    expected_names = [f"{index:04d}.json" for index in range(len(entries))]
    if [item.name for item in entries] != expected_names:
        raise ValueError("material-loop state journal is not contiguous")
    chain: list[tuple[CodexImageMaterialLoopState, CodexImageArtifact]] = []
    for index, path in enumerate(entries):
        artifact = artifact_for_codex_image(
            root,
            path,
            artifact_id=f"material-loop-state-{plan.session_id}-{index:04d}",
            kind="material-loop-state",
            media_type="application/json",
        )
        state = load_codex_image_model(root, artifact, CodexImageMaterialLoopState)
        if (
            state.bridge_plan != plan_artifact
            or state.controller_input != controller_input_artifact
            or state.sequence != index
        ):
            raise ValueError("material-loop state changed its bridge, input, or sequence")
        if chain:
            validate_material_loop_transition(chain[-1][0], state)
        chain.append((state, artifact))
    if not chain:
        raise ValueError("material-loop state journal is empty")
    return chain


def _append_state(
    root: Path,
    loop_root: Path,
    plan: ImageGeneratedMaterialBridgePlan,
    plan_artifact: CodexImageArtifact,
    controller_input_artifact: CodexImageArtifact,
    proposed: CodexImageMaterialLoopState,
) -> tuple[CodexImageMaterialLoopState, CodexImageArtifact]:
    """Append one valid journal state without replacing prior evidence."""

    chain = _state_chain(
        root,
        loop_root,
        plan,
        plan_artifact,
        controller_input_artifact,
    )
    previous = chain[-1]
    validate_material_loop_transition(previous[0], proposed)
    if proposed.sequence != len(chain):
        raise ValueError("material-loop append sequence is stale")
    artifact = write_immutable_codex_image_model(
        root,
        loop_root / "states" / f"{proposed.sequence:04d}.json",
        proposed,
        kind="material-loop-state",
    )
    return proposed, artifact


def _publish_pre_promotion_terminal_locked(
    root: Path,
    loop_root: Path,
    plan: ImageGeneratedMaterialBridgePlan,
    plan_artifact: CodexImageArtifact,
    state: CodexImageMaterialLoopState,
    state_artifact: CodexImageArtifact,
    base_state_artifact: CodexImageArtifact,
    *,
    created_at: datetime,
) -> tuple[CodexImageMaterialLoopTerminal, CodexImageArtifact]:
    """Close an exact failed or cancelled pre-promotion attempt without claiming adoption."""

    if state.status not in {"failed", "cancelled"} or state.failure_evidence is None:
        raise ValueError("pre-promotion terminal requires exact failed state evidence")
    if any(
        item is not None
        for item in (
            state.promotion_receipt,
            state.material_phase_receipt,
            state.base_state,
        )
    ):
        raise ValueError("pre-promotion terminal cannot carry a promotion closure")
    provenance = [plan_artifact, state_artifact, base_state_artifact]
    terminal = CodexImageMaterialLoopTerminal(
        contract_id=f"material-loop-terminal-{plan.session_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=stable_json_digest(
            {item.path: item.sha256 for item in provenance}
        ),
        source_fingerprint=state.failure_evidence.sha256,
        producer=_PRODUCER,
        provenance=provenance,
        created_at=created_at,
        bridge_plan=plan_artifact,
        latest_state=state_artifact,
        base_state=base_state_artifact,
        status=cast(Any, state.status),
        material_candidate_promoted=False,
        limitations=[
            "The exact host attempt failed before companion material promotion; "
            "no quality, package, destination, or human-review completion is claimed."
        ],
    )
    published, artifact = _write_or_adopt(
        root,
        loop_root / "terminal.json",
        terminal,
        kind="material-loop-terminal",
        model_type=CodexImageMaterialLoopTerminal,
    )
    return cast(CodexImageMaterialLoopTerminal, published), artifact


def _publish_codex_image_material_loop_bridge_locked(
    job_root: Path,
    *,
    bridge_plan: ImageGeneratedMaterialBridgePlan,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Publish the bridge and initial journal while the AQ session lock is held."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    if bridge_plan.contract_id != f"material-bridge-plan-{bridge_plan.session_id}":
        raise ValueError("material bridge plan contract_id is not canonical")
    _validate_bridge_files(root, bridge_plan)
    _validate_base_authoring_boundary(root, bridge_plan)
    _validate_image_and_authoring_boundary(root, bridge_plan)
    phase_profile = _material_phase_profile(root, bridge_plan)
    loop_root = _loop_root(root, bridge_plan.session_id, must_exist=False)
    now = created_at or datetime.now(UTC)
    published_plan, plan_artifact = _write_or_adopt(
        root,
        loop_root / "bridge_plan.json",
        bridge_plan,
        kind="material-bridge-plan",
        model_type=ImageGeneratedMaterialBridgePlan,
    )
    bridge_plan = cast(ImageGeneratedMaterialBridgePlan, published_plan)
    controller_input = _build_material_controller_input(
        bridge_plan,
        plan_artifact,
        phase_profile,
        created_at=bridge_plan.created_at,
    )
    published_input, input_artifact = _write_or_adopt(
        root,
        loop_root / "controller_input.json",
        controller_input,
        kind="material-controller-input",
        model_type=ImageGeneratedMaterialControllerInput,
    )
    published_input = cast(ImageGeneratedMaterialControllerInput, published_input)
    _validate_material_controller_input_closure(
        bridge_plan,
        plan_artifact,
        phase_profile,
        published_input,
    )
    states_root = loop_root / "states"
    initial_path = states_root / "0000.json"
    initial = _make_state(
        bridge_plan,
        plan_artifact,
        input_artifact,
        sequence=0,
        status="controller_promotion_required",
        budget_usage=ImageMaterialLoopBudgetUsage(
            normalization_runs=1,
            semantic_reviews=1,
        ),
        created_at=now,
    )
    published_state, state_artifact = _write_or_adopt(
        root,
        initial_path,
        initial,
        kind="material-loop-state",
        model_type=CodexImageMaterialLoopState,
    )
    _state_chain(root, loop_root, bridge_plan, plan_artifact, input_artifact)
    return {
        "bridge_plan": bridge_plan.model_dump(mode="json"),
        "bridge_plan_artifact": plan_artifact.model_dump(mode="json"),
        "controller_input": published_input.model_dump(mode="json"),
        "controller_input_artifact": input_artifact.model_dump(mode="json"),
        "state": published_state.model_dump(mode="json"),
        "state_artifact": state_artifact.model_dump(mode="json"),
    }


def publish_codex_image_material_loop_bridge(
    job_root: Path,
    *,
    bridge_plan: ImageGeneratedMaterialBridgePlan,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Publish a validated bridge plan, controller assignment, and initial journal."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    session_root = root / "production" / "autonomy_v2" / bridge_plan.session_id
    with autonomy_session_lock(
        root,
        session_root,
        owner_id="aqv2-image-material-loop-publish",
        ttl_seconds=180,
    ):
        return _publish_codex_image_material_loop_bridge_locked(
            root,
            bridge_plan=bridge_plan,
            created_at=created_at,
        )


def _load_loop_bundle(
    root: Path,
    session_id: str,
) -> tuple[
    Path,
    ImageGeneratedMaterialBridgePlan,
    CodexImageArtifact,
    ImageGeneratedMaterialControllerInput,
    CodexImageArtifact,
    list[tuple[CodexImageMaterialLoopState, CodexImageArtifact]],
]:
    """Load and revalidate the plan, assignment, and complete journal."""

    loop_root = _loop_root(root, session_id, must_exist=True)
    plan_artifact = artifact_for_codex_image(
        root,
        loop_root / "bridge_plan.json",
        artifact_id=f"material-bridge-plan-{session_id}",
        kind="material-bridge-plan",
        media_type="application/json",
    )
    plan = load_codex_image_model(root, plan_artifact, ImageGeneratedMaterialBridgePlan)
    promoted = _validate_bridge_files(root, plan)
    input_artifact = artifact_for_codex_image(
        root,
        loop_root / "controller_input.json",
        artifact_id=f"material-controller-input-{session_id}",
        kind="material-controller-input",
        media_type="application/json",
    )
    controller_input = load_codex_image_model(
        root, input_artifact, ImageGeneratedMaterialControllerInput
    )
    phase_profile = _material_phase_profile(root, plan)
    _validate_material_controller_input_closure(
        plan,
        plan_artifact,
        phase_profile,
        controller_input,
    )
    for artifact in _controller_input_artifacts(controller_input):
        if promoted and artifact == controller_input.canonical_material_observation:
            continue
        validate_codex_image_artifact(root, artifact)
    chain = _state_chain(root, loop_root, plan, plan_artifact, input_artifact)
    return loop_root, plan, plan_artifact, controller_input, input_artifact, chain


def execute_codex_image_material_loop_controller(
    job_id: str,
    session_id: str,
    *,
    controller: CandidateAuthoringController,
    timeout_seconds: int = 900,
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Execute or resume the existing formal material controller for this bridge."""

    base_status = get_autonomy_v2_status(job_id, session_id)
    root = job_dir(job_id)
    loop_root, plan, plan_artifact, controller_input, input_artifact, chain = (
        _load_loop_bundle(root, session_id)
    )
    aq_plan = cast(
        AutonomyPlanV2,
        _read_model(root, _aq_from_codex(plan.aq_plan, role="plan"), AutonomyPlanV2),
    )
    aq_profile = cast(
        AutonomyProfileV2,
        _read_model(
            root,
            _aq_from_codex(plan.aq_profile, role="profile"),
            AutonomyProfileV2,
        ),
    )
    if (
        aq_profile.status != "verified_active"
        and not allow_disabled_experimental
    ):
        raise PermissionError("autonomous_static_prop_v2 is disabled_experimental")
    if aq_plan.session_id != session_id:
        raise ValueError("material controller bridge targets another AQ session")
    latest = chain[-1][0]
    if latest.status not in {"controller_promotion_required", "promoting_material"}:
        raise PermissionError("material-loop journal is not at controller promotion")
    assignment = _aq_from_codex(input_artifact, role="assignment")
    immutable_inputs = [
        _aq_from_codex(
            item,
            role=(
                "scene"
                if item.path == controller_input.canonical_scene_spec.path
                else "material-baseline"
            ),
        )
        for item in _controller_input_artifacts(controller_input)
    ]
    base_state = AutonomyStateV2.model_validate_json(
        json.dumps(base_status["state"], ensure_ascii=False)
    )
    if (
        base_state.phase,
        base_state.status,
        base_state.next_action,
    ) == ("authoring", "running", "validate_candidate"):
        if not base_state.provenance or not base_state.provenance[-1].path.endswith(
            "/result.json"
        ):
            raise ValueError("candidate validation state omits the controller result")
        recovered_result_artifact = base_state.provenance[-1]
        recovered_result = cast(
            ControllerResult,
            _read_model(root, recovered_result_artifact, ControllerResult),
        )
        recovered_request_artifact = artifact_for_v2(
            root,
            root
            / recovered_result_artifact.path.rsplit("/", 1)[0]
            / "request.json",
            artifact_id=f"request-{recovered_result.execution_id}",
            kind="controller_request",
        )
        recovered_request = cast(
            ControllerExecutionRequest,
            _read_model(root, recovered_request_artifact, ControllerExecutionRequest),
        )
        if recovered_result.status != "completed":
            raise ValueError("recovered candidate result is not completed")
        response: dict[str, object] = {
            "request": recovered_request.model_dump(mode="json"),
            "result": recovered_result.model_dump(mode="json"),
            "state": base_state.model_dump(mode="json"),
            "state_artifact": base_status["state_artifact"],
            "recovered_action": True,
        }
    else:
        response = execute_autonomy_v2_controller(
            job_id,
            session_id,
            phase_profile_id="material_authoring",
            assignment=assignment,
            immutable_inputs=immutable_inputs,
            controller=controller,
            expected_output_sha256=controller_input.expected_output_sha256,
            timeout_seconds=timeout_seconds,
        )
    request = ControllerExecutionRequest.model_validate_json(
        json.dumps(response["request"], ensure_ascii=False)
    )
    result = ControllerResult.model_validate_json(
        json.dumps(response["result"], ensure_ascii=False)
    )
    pre_promotion_terminal: CodexImageMaterialLoopTerminal | None = None
    pre_promotion_terminal_artifact: CodexImageArtifact | None = None
    session_root = root / "production" / "autonomy_v2" / session_id
    with autonomy_session_lock(
        root,
        session_root,
        owner_id="aqv2-image-material-loop-bind",
        ttl_seconds=120,
    ):
        loop_root, plan, plan_artifact, controller_input, input_artifact, chain = (
            _load_loop_bundle(root, session_id)
        )
        latest = chain[-1][0]
        _validate_controller_request_binding(
            request,
            plan=plan,
            controller_input=controller_input,
            input_artifact=input_artifact,
        )
        if result.status == "completed":
            _validate_controller_result_material_scope(root, plan, result)
        execution_root = session_root / "controller_executions" / request.execution_id
        request_artifact = artifact_for_codex_image(
            root,
            execution_root / "request.json",
            artifact_id=request.contract_id,
            kind="controller-execution-request",
            media_type="application/json",
        )
        formal_result_artifact = artifact_for_codex_image(
            root,
            execution_root / "result.json",
            artifact_id=result.contract_id,
            kind="controller-result",
            media_type="application/json",
        )
        binding_inputs = dict(controller_input.immutable_input_sha256)
        binding_inputs[input_artifact.path] = input_artifact.sha256
        binding = ImageGeneratedMaterialControllerBinding(
            contract_id=f"material-controller-binding-{session_id}",
            job_id=plan.job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            session_id=plan.session_id,
            input_sha256=stable_json_digest(
                {"request": request_artifact.sha256, "inputs": binding_inputs}
            ),
            source_fingerprint=request_artifact.sha256,
            producer=_PRODUCER,
            provenance=[
                plan_artifact,
                input_artifact,
                request_artifact,
                controller_input.phase_tool_profile,
            ],
            created_at=datetime.now(UTC),
            bridge_plan=plan_artifact,
            controller_input=input_artifact,
            controller_execution_request=request_artifact,
            phase_tool_profile=controller_input.phase_tool_profile,
            execution_id=request.execution_id,
            immutable_input_sha256=binding_inputs,
            allowed_output_paths=request.allowed_output_paths,
            expected_output_sha256=request.expected_output_sha256,
            controller_request_sha256=request_artifact.sha256,
        )
        published_binding, binding_artifact = _write_or_adopt(
            root,
            loop_root / "controller_binding.json",
            binding,
            kind="material-controller-binding",
            model_type=ImageGeneratedMaterialControllerBinding,
        )
        if latest.status == "controller_promotion_required" and result.status == "completed":
            usage = latest.budget_usage.model_copy(
                update={
                    "controller_invocations": (
                        latest.budget_usage.controller_invocations + 1
                    )
                }
            )
            proposed = _make_state(
                plan,
                plan_artifact,
                input_artifact,
                sequence=latest.sequence + 1,
                status="promoting_material",
                budget_usage=usage,
                created_at=datetime.now(UTC),
                previous=chain[-1],
            )
            latest, latest_artifact = _append_state(
                root, loop_root, plan, plan_artifact, input_artifact, proposed
            )
        elif latest.status == "controller_promotion_required" and result.status not in {
            "waiting_for_output"
        }:
            failure = _make_state(
                plan,
                plan_artifact,
                input_artifact,
                sequence=latest.sequence + 1,
                status="failed",
                budget_usage=latest.budget_usage.model_copy(
                    update={
                        "controller_invocations": (
                            latest.budget_usage.controller_invocations + 1
                        )
                    }
                ),
                created_at=datetime.now(UTC),
                previous=chain[-1],
                failure_evidence=formal_result_artifact,
                latest_failure=f"formal material controller result: {result.status}",
            )
            latest, latest_artifact = _append_state(
                root, loop_root, plan, plan_artifact, input_artifact, failure
            )
        elif latest.status == "promoting_material" and result.status != "completed":
            failure = _make_state(
                plan,
                plan_artifact,
                input_artifact,
                sequence=latest.sequence + 1,
                status="failed",
                budget_usage=latest.budget_usage,
                created_at=datetime.now(UTC),
                previous=chain[-1],
                failure_evidence=formal_result_artifact,
                latest_failure=f"formal material controller result: {result.status}",
            )
            latest, latest_artifact = _append_state(
                root, loop_root, plan, plan_artifact, input_artifact, failure
            )
        else:
            latest_artifact = chain[-1][1]
        if latest.status in {"failed", "cancelled"}:
            raw_base_state_artifact = response.get("state_artifact")
            if not isinstance(raw_base_state_artifact, dict):
                raise ValueError("formal controller failure omits its exact AQ state")
            base_state_codex = _codex_from_aq(
                root,
                AQV2Artifact.model_validate(raw_base_state_artifact),
                kind="base-aq-state",
            )
            (
                pre_promotion_terminal,
                pre_promotion_terminal_artifact,
            ) = _publish_pre_promotion_terminal_locked(
                root,
                loop_root,
                plan,
                plan_artifact,
                latest,
                latest_artifact,
                base_state_codex,
                created_at=datetime.now(UTC),
            )
    return {
        **response,
        "controller_binding": published_binding.model_dump(mode="json"),
        "controller_binding_artifact": binding_artifact.model_dump(mode="json"),
        "material_loop_state": latest.model_dump(mode="json"),
        "material_loop_state_artifact": latest_artifact.model_dump(mode="json"),
        "material_loop_terminal": (
            pre_promotion_terminal.model_dump(mode="json")
            if pre_promotion_terminal is not None
            else None
        ),
        "material_loop_terminal_artifact": (
            pre_promotion_terminal_artifact.model_dump(mode="json")
            if pre_promotion_terminal_artifact is not None
            else None
        ),
        "controller_status": result.status,
    }


def promote_codex_image_material_loop(
    job_root: Path,
    *,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
    state: AutonomyStateV2,
    result_artifact: AQV2Artifact,
    allow_disabled_experimental: bool = False,
) -> tuple[MaterialPhaseReceiptV2, AQV2Artifact]:
    """Run the existing locked supervisor promotion and adopt its exact receipt."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    if job_dir(plan.job_id).resolve() != root.resolve():
        raise ValueError("material promotion job_root differs from the workspace job")
    loop_root, bridge, _, controller_input, input_artifact, chain = _load_loop_bundle(
        root, plan.session_id
    )
    if chain[-1][0].status not in {
        "promoting_material",
        "material_promoted",
        "waiting_for_quality",
    }:
        raise PermissionError("material-loop journal has not bound a completed controller")
    binding_artifact = artifact_for_codex_image(
        root,
        loop_root / "controller_binding.json",
        artifact_id=f"material-controller-binding-{plan.session_id}",
        kind="material-controller-binding",
        media_type="application/json",
    )
    binding = load_codex_image_model(
        root, binding_artifact, ImageGeneratedMaterialControllerBinding
    )
    request = load_codex_image_model(
        root, binding.controller_execution_request, ControllerExecutionRequest
    )
    _validate_controller_request_binding(
        request,
        plan=bridge,
        controller_input=controller_input,
        input_artifact=input_artifact,
    )
    result = cast(ControllerResult, _read_model(root, result_artifact, ControllerResult))
    if (
        result.execution_id != binding.execution_id
        or result.request.sha256 != binding.controller_execution_request.sha256
    ):
        raise ValueError("material promotion result differs from controller binding")
    _validate_controller_result_material_scope(root, bridge, result)
    bound_plan = cast(
        AutonomyPlanV2,
        _read_model(root, _aq_from_codex(bridge.aq_plan, role="plan"), AutonomyPlanV2),
    )
    if bound_plan != plan:
        raise ValueError("material promotion AQ plan binding changed")
    current_status = get_autonomy_v2_status(plan.job_id, plan.session_id)
    current_state = AutonomyStateV2.model_validate_json(
        json.dumps(current_status["state"], ensure_ascii=False)
    )
    current_budget = AutonomyBudgetV2.model_validate_json(
        json.dumps(current_status["budget"], ensure_ascii=False)
    )
    if current_budget != budget:
        raise ValueError("material promotion budget is not current")
    if (
        current_state.phase == "quality"
        and current_state.status == "running"
        and current_state.next_action == "run_integrated_quality"
    ):
        if not current_state.provenance:
            raise ValueError("quality state omits the material phase receipt")
        recovered_artifact = current_state.provenance[-1]
        recovered = validate_material_phase_receipt_v2(
            root,
            recovered_artifact,
            require_current=True,
        )
        if recovered.controller_result != result_artifact:
            raise ValueError("existing material receipt consumed another controller result")
        return recovered, recovered_artifact
    if current_state != state:
        raise ValueError("material promotion state is stale")
    if chain[-1][0].status != "promoting_material":
        raise PermissionError("material-loop journal is not ready for canonical promotion")
    if state.next_action != "validate_candidate" or state.phase != "authoring":
        raise PermissionError("base AQ state is not at material candidate validation")
    if state.provenance[-1] != result_artifact:
        raise ValueError("material bridge result is not the current AQ state tail")
    try:
        outcome = advance_autonomy_v2(
            plan.job_id,
            plan.session_id,
            allow_disabled_experimental=allow_disabled_experimental,
        )
    except Exception:
        session_root = root / "production" / "autonomy_v2" / plan.session_id
        with autonomy_session_lock(
            root,
            session_root,
            owner_id="aqv2-image-material-loop-promotion-failure",
            ttl_seconds=120,
        ):
            record_codex_image_material_promotion_failure_locked(
                root,
                session_root,
                plan,
                state,
                result_artifact,
            )
        raise
    if outcome.get("outcome") != "material_candidate_validated":
        raise RuntimeError("AQ supervisor did not promote the material candidate")
    receipt_artifact = AQV2Artifact.model_validate_json(
        json.dumps(outcome["candidate_receipt"], ensure_ascii=False)
    )
    receipt = validate_material_phase_receipt_v2(
        root,
        receipt_artifact,
        require_current=True,
    )
    if receipt.budget_usage_after != AutonomyStateV2.model_validate_json(
        json.dumps(outcome["state"], ensure_ascii=False)
    ).budget_usage:
        raise ValueError("AQ supervisor did not adopt the material receipt budget")
    return receipt, receipt_artifact


def record_codex_image_material_promotion_failure_locked(
    root: Path,
    session_root: Path,
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
    result_artifact: AQV2Artifact,
) -> dict[str, object] | None:
    """Bind exact host evidence and terminalize a lock-held failed promotion attempt."""

    job_root = ensure_contained_production_path(root, root, must_exist=True)
    expected_session_root = ensure_contained_production_path(
        job_root,
        job_root / "production" / "autonomy_v2" / plan.session_id,
        must_exist=True,
    )
    supplied_session_root = ensure_contained_production_path(
        job_root, session_root, must_exist=True
    )
    if supplied_session_root != expected_session_root:
        raise ValueError("material-loop failure guard received another session root")
    loop_path = expected_session_root / _LOOP_DIR / "bridge_plan.json"
    if not os.path.exists(native_io_path(loop_path)):
        return None
    loop_root, bridge, plan_artifact, _input, _input_artifact, chain = _load_loop_bundle(
        job_root, plan.session_id
    )
    latest, latest_artifact = chain[-1]
    if latest.status not in {"promoting_material", "failed"}:
        raise PermissionError("material-loop failure did not follow promotion authority")
    validate_v2_artifact(job_root, result_artifact)
    if not state.provenance or state.provenance[-1] != result_artifact:
        raise ValueError("material-loop failure is not bound to the exact controller result")
    base_matches = [
        (candidate, artifact)
        for candidate, artifact in _base_aq_state_chain(job_root, expected_session_root)
        if candidate == state
    ]
    if len(base_matches) != 1:
        raise ValueError("material-loop failure base state is not in the exact AQ chain")
    base_state_codex = _codex_from_aq(
        job_root,
        base_matches[0][1],
        kind="base-aq-state",
    )
    formal_result_codex = _codex_from_aq(
        job_root,
        result_artifact,
        kind="controller-result",
    )
    rollback_path = (
        expected_session_root
        / "material_phase"
        / f"{state.sequence:04d}"
        / "rollback_receipt.json"
    )
    phase_root = rollback_path.parent
    promotion_receipt_path = phase_root / "promotion_receipt.json"
    if os.path.exists(native_io_path(promotion_receipt_path)):
        promotion_artifact = artifact_for_v2(
            job_root,
            promotion_receipt_path,
            artifact_id="material-phase-receipt",
            kind="material_phase_receipt",
        )
        validate_material_phase_receipt_v2(
            job_root,
            promotion_artifact,
            require_current=True,
        )
        return None
    failure_evidence = formal_result_codex
    failure_code = "material_promotion_prewrite_failed"
    intent_path = phase_root / "promotion_intent.json"
    if os.path.exists(native_io_path(intent_path)):
        provisional_intent = artifact_for_v2(
            job_root,
            intent_path,
            artifact_id="material-promotion-intent",
            kind="material_promotion_intent",
        )
        intent = cast(
            MaterialPromotionIntentV2,
            _read_model(job_root, provisional_intent, MaterialPromotionIntentV2),
        )
        if intent.controller_result != result_artifact:
            raise ValueError("material promotion intent targets another controller result")
        for nested in intent.provenance:
            validate_v2_artifact(job_root, nested)
        intent_artifact = artifact_for_v2(
            job_root,
            intent_path,
            artifact_id=intent.contract_id,
            kind="material_promotion_intent",
        )
        failure_evidence = _codex_from_aq(
            job_root,
            intent_artifact,
            kind="material-promotion-intent",
        )
        failure_code = "material_promotion_intent_prewrite_failed"
    if os.path.exists(native_io_path(rollback_path)):
        provisional = artifact_for_v2(
            job_root,
            rollback_path,
            artifact_id="material-phase-rollback",
            kind="material_phase_rollback_receipt",
        )
        rollback = cast(
            MaterialPhaseRollbackReceiptV2,
            _read_model(job_root, provisional, MaterialPhaseRollbackReceiptV2),
        )
        if rollback.controller_result != result_artifact:
            raise ValueError("material rollback receipt targets another controller result")
        for nested in rollback.provenance:
            validate_v2_artifact(job_root, nested)
        rollback_artifact = artifact_for_v2(
            job_root,
            rollback_path,
            artifact_id=rollback.contract_id,
            kind="material_phase_rollback_receipt",
        )
        failure_evidence = _codex_from_aq(
            job_root,
            rollback_artifact,
            kind="material-phase-rollback-receipt",
        )
        failure_code = f"material_promotion_{rollback.status}"
    if latest.status == "promoting_material":
        failed = _make_state(
            bridge,
            plan_artifact,
            _input_artifact,
            sequence=latest.sequence + 1,
            status="failed",
            budget_usage=latest.budget_usage,
            created_at=datetime.now(UTC),
            previous=chain[-1],
            failure_evidence=failure_evidence,
            latest_failure=failure_code,
        )
        failed, failed_artifact = _append_state(
            job_root,
            loop_root,
            bridge,
            plan_artifact,
            _input_artifact,
            failed,
        )
    else:
        failed, failed_artifact = latest, latest_artifact
        if (
            failed.failure_evidence != failure_evidence
            or failed.latest_failure != failure_code
        ):
            raise ValueError("existing material-loop failure differs from exact host evidence")
    terminal, terminal_artifact = _publish_pre_promotion_terminal_locked(
        job_root,
        loop_root,
        bridge,
        plan_artifact,
        failed,
        failed_artifact,
        base_state_codex,
        created_at=datetime.now(UTC),
    )
    return {
        "state": failed.model_dump(mode="json"),
        "state_artifact": failed_artifact.model_dump(mode="json"),
        "failure_evidence": failure_evidence.model_dump(mode="json"),
        "terminal": terminal.model_dump(mode="json"),
        "terminal_artifact": terminal_artifact.model_dump(mode="json"),
    }


def validate_codex_image_material_controller_promotion_boundary(
    root: Path,
    session_root: Path,
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
    result_artifact: AQV2Artifact,
) -> bool:
    """Validate a lock-held loop controller boundary or report that no loop exists."""

    job_root = ensure_contained_production_path(root, root, must_exist=True)
    expected_session_root = ensure_contained_production_path(
        job_root,
        job_root / "production" / "autonomy_v2" / plan.session_id,
        must_exist=True,
    )
    supplied_session_root = ensure_contained_production_path(
        job_root, session_root, must_exist=True
    )
    if supplied_session_root != expected_session_root:
        raise ValueError("material-loop promotion guard received another session root")
    loop_root = expected_session_root / _LOOP_DIR
    if not os.path.exists(native_io_path(loop_root / "bridge_plan.json")):
        return False
    (
        loaded_loop_root,
        bridge,
        _plan_artifact,
        controller_input,
        input_artifact,
        chain,
    ) = _load_loop_bundle(job_root, plan.session_id)
    if loaded_loop_root != loop_root or chain[-1][0].status != "promoting_material":
        raise PermissionError("material-loop journal is not at exact promotion authority")
    bound_plan = cast(
        AutonomyPlanV2,
        _read_model(job_root, _aq_from_codex(bridge.aq_plan, role="plan"), AutonomyPlanV2),
    )
    if bound_plan != plan:
        raise ValueError("material-loop promotion guard AQ plan binding changed")
    if (
        state.phase,
        state.status,
        state.next_action,
    ) != ("authoring", "running", "validate_candidate"):
        raise PermissionError("material-loop base state is not at candidate validation")
    if not state.provenance or state.provenance[-1] != result_artifact:
        raise ValueError("material-loop result is not the exact base state tail")
    binding_artifact = artifact_for_codex_image(
        job_root,
        loop_root / "controller_binding.json",
        artifact_id=f"material-controller-binding-{plan.session_id}",
        kind="material-controller-binding",
        media_type="application/json",
    )
    binding = load_codex_image_model(
        job_root, binding_artifact, ImageGeneratedMaterialControllerBinding
    )
    request = load_codex_image_model(
        job_root, binding.controller_execution_request, ControllerExecutionRequest
    )
    _validate_controller_request_binding(
        request,
        plan=bridge,
        controller_input=controller_input,
        input_artifact=input_artifact,
    )
    result = cast(
        ControllerResult,
        _read_model(job_root, result_artifact, ControllerResult),
    )
    if (
        result.execution_id != binding.execution_id
        or result.request.sha256 != binding.controller_execution_request.sha256
    ):
        raise ValueError("material-loop formal result differs from its binding")
    _validate_controller_result_material_scope(job_root, bridge, result)
    return True


def validate_codex_image_material_promotion_receipt(
    job_root: Path,
    promotion_artifact: CodexImageArtifact,
    *,
    require_current: bool = True,
) -> ImageGeneratedMaterialPromotionReceipt:
    """Recursively revalidate one companion promotion and every authority dependency."""

    root = ensure_contained_codex_image_path(job_root, job_root, must_exist=True)
    validate_codex_image_artifact(root, promotion_artifact)
    receipt = load_codex_image_model(
        root, promotion_artifact, ImageGeneratedMaterialPromotionReceipt
    )
    if receipt.producer != _PRODUCER:
        raise ValueError("material-loop promotion receipt has an unexpected producer")
    expected_path = (
        PurePosixPath("production")
        / "autonomy_v2"
        / receipt.session_id
        / _LOOP_DIR
        / "promotion_receipt.json"
    ).as_posix()
    if promotion_artifact.path != expected_path:
        raise ValueError("material-loop promotion receipt path is not canonical")
    (
        loop_root,
        plan,
        plan_artifact,
        controller_input,
        input_artifact,
        chain,
    ) = _load_loop_bundle(root, receipt.session_id)
    if (
        receipt.bridge_plan != plan_artifact
        or receipt.controller_input != input_artifact
        or receipt.job_id != plan.job_id
        or receipt.workflow_id != plan.workflow_id
        or receipt.dispatch_id != plan.dispatch_id
    ):
        raise ValueError("material-loop promotion identity or plan binding changed")
    if (
        receipt.selection != plan.selection
        or receipt.companion_selection_receipt
        != plan.companion_selection_receipt
        or receipt.native_core_preparation_receipt
        != plan.native_core_preparation_receipt
        or receipt.semantic_review != plan.semantic_review
        or receipt.normalization_receipt != plan.normalization_receipt
        or receipt.adoption != plan.adoption
        or receipt.exact_adoption_preflight != plan.exact_adoption_preflight
    ):
        raise ValueError("material-loop promotion provenance closure changed")
    _validate_bridge_files(root, plan)
    _validate_image_and_authoring_boundary(root, plan)
    binding_artifact = artifact_for_codex_image(
        root,
        loop_root / "controller_binding.json",
        artifact_id=f"material-controller-binding-{plan.session_id}",
        kind="material-controller-binding",
        media_type="application/json",
    )
    if receipt.controller_binding != binding_artifact:
        raise ValueError("material-loop promotion controller binding changed")
    binding = load_codex_image_model(
        root, binding_artifact, ImageGeneratedMaterialControllerBinding
    )
    if (
        binding.bridge_plan != plan_artifact
        or binding.controller_input != input_artifact
        or binding.controller_execution_request != receipt.controller_execution_request
    ):
        raise ValueError("material-loop controller binding targets another request")
    request = load_codex_image_model(
        root, receipt.controller_execution_request, ControllerExecutionRequest
    )
    _validate_controller_request_binding(
        request,
        plan=plan,
        controller_input=controller_input,
        input_artifact=input_artifact,
    )
    result = cast(
        ControllerResult,
        _read_model(
            root,
            _aq_from_codex(receipt.controller_result, role="result"),
            ControllerResult,
        ),
    )
    if (
        result.producer
        != "codex_blender_modeler.production.controller_executor.service"
        or result.status != "completed"
        or result.execution_id != binding.execution_id
        or result.request.sha256 != receipt.controller_execution_request.sha256
    ):
        raise ValueError("material-loop promotion did not bind a formal completed result")
    _validate_controller_result_material_scope(root, plan, result)
    material_receipt = validate_material_phase_receipt_v2(
        root,
        _aq_from_codex(receipt.material_phase_receipt, role="material_phase_receipt"),
        require_current=require_current,
    )
    _validate_base_authoring_boundary(
        root,
        plan,
        promoted_material_receipt_artifact=_aq_from_codex(
            receipt.material_phase_receipt,
            role="material_phase_receipt",
        ),
    )
    if (
        receipt.controller_result.sha256 != material_receipt.controller_result.sha256
        or receipt.canonical_material_plan_sha256
        != material_receipt.canonical_material_plan_sha256
        or receipt.canonical_scene_spec_sha256
        != material_receipt.canonical_scene_spec_sha256
    ):
        raise ValueError("companion promotion differs from MaterialPhaseReceiptV2")
    promoted_base_state = cast(
        AutonomyStateV2,
        _read_model(
            root,
            _aq_from_codex(receipt.promoted_base_state, role="state"),
            AutonomyStateV2,
        ),
    )
    if (
        promoted_base_state.phase,
        promoted_base_state.status,
        promoted_base_state.next_action,
    ) != ("quality", "running", "run_integrated_quality") or (
        not promoted_base_state.provenance
        or promoted_base_state.provenance[-1].sha256
        != receipt.material_phase_receipt.sha256
    ):
        raise ValueError("promotion receipt base state did not adopt MaterialPhaseReceiptV2")
    preview = validate_promoted_codex_image_material_preview(
        root, receipt.neutral_preview, require_current=require_current
    )
    if (
        preview.material_phase_receipt != receipt.material_phase_receipt
        or preview.material_id != plan.target_material_ids[0]
        or preview.raw_swatch_manifest != receipt.neutral_preview_manifest
        or preview.preview_image != receipt.neutral_preview_image
    ):
        raise ValueError("companion promotion neutral preview binding changed")
    for nested in receipt.provenance:
        validate_codex_image_artifact(root, nested)
    if require_current:
        latest = chain[-1][0]
        if (
            latest.status
            not in {
                "material_promoted",
                "waiting_for_quality",
                "quality_approved",
                "review_required",
                "blocked",
                "failed",
                "cancelled",
            }
            or latest.promotion_receipt != promotion_artifact
            or latest.material_phase_receipt != receipt.material_phase_receipt
        ):
            raise ValueError("material-loop journal does not retain this promotion")
    return receipt


def _finalize_codex_image_material_loop_promotion_locked(
    job_root: Path,
    *,
    material_phase_receipt_artifact: AQV2Artifact,
    neutral_preview_artifact: CodexImageArtifact,
    reference_preview_manifest: CodexImageArtifact | None = None,
    reference_preview_image: CodexImageArtifact | None = None,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Publish preview-bound receipt and states while the AQ session lock is held."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    material_receipt = validate_material_phase_receipt_v2(
        root, material_phase_receipt_artifact, require_current=True
    )
    loop_root, plan, plan_artifact, controller_input, input_artifact, chain = (
        _load_loop_bundle(root, material_receipt.session_id)
    )
    latest = chain[-1][0]
    if latest.status not in {"promoting_material", "material_promoted", "waiting_for_quality"}:
        raise PermissionError("material-loop journal is not awaiting promotion completion")
    base_status = get_autonomy_v2_status(plan.job_id, plan.session_id)
    base_state = AutonomyStateV2.model_validate_json(
        json.dumps(base_status["state"], ensure_ascii=False)
    )
    base_state_artifact = _codex_from_aq(
        root,
        AQV2Artifact.model_validate(base_status["state_artifact"]),
        kind="promoted-base-state",
    )
    if (
        base_state.phase,
        base_state.status,
        base_state.next_action,
    ) != ("quality", "running", "run_integrated_quality"):
        raise PermissionError("base AQ state has not adopted material promotion")
    if not base_state.provenance or (
        base_state.provenance[-1].sha256 != material_phase_receipt_artifact.sha256
    ):
        raise ValueError("base AQ quality state omits the exact material phase receipt")
    binding_path = loop_root / "controller_binding.json"
    binding_artifact = artifact_for_codex_image(
        root,
        binding_path,
        artifact_id=f"material-controller-binding-{plan.session_id}",
        kind="material-controller-binding",
        media_type="application/json",
    )
    binding = load_codex_image_model(
        root, binding_artifact, ImageGeneratedMaterialControllerBinding
    )
    if material_receipt.controller_result.sha256 == "":
        raise ValueError("material receipt omits its controller result")
    request_artifact = binding.controller_execution_request
    request = load_codex_image_model(root, request_artifact, ControllerExecutionRequest)
    result_codex = _codex_from_aq(root, material_receipt.controller_result)
    result = load_codex_image_model(root, result_codex, ControllerResult)
    if result.execution_id != request.execution_id or result.status != "completed":
        raise ValueError("promotion must bind the completed formal controller execution")
    preview = load_codex_image_model(
        root, neutral_preview_artifact, ImageGeneratedMaterialNeutralPreview
    )
    material_receipt_codex = _codex_from_aq(
        root,
        material_phase_receipt_artifact,
        artifact_id=material_receipt.contract_id,
        kind="material-phase-receipt",
    )
    if preview.material_phase_receipt != material_receipt_codex:
        raise ValueError("neutral preview targets another material phase receipt")
    if preview.material_id != plan.target_material_ids[0]:
        raise ValueError("neutral preview targets another material identity")
    for preview_dependency in preview.provenance:
        validate_codex_image_artifact(root, preview_dependency)
    if (
        preview.preview_image != preview.provenance[-1]
        or preview.preview_image_path != preview.preview_image.path
        or preview.preview_image_sha256 != preview.preview_image.sha256
        or preview.preview_image_byte_size != preview.preview_image.byte_size
    ):
        raise ValueError("neutral preview image or provenance changed")
    if preview.authoring_blend.sha256 != material_receipt.authoring_blend_snapshot.sha256:
        raise ValueError("neutral preview did not render the promoted authoring blend")
    if reference_preview_manifest is not None:
        validate_codex_image_artifact(root, reference_preview_manifest)
    if reference_preview_image is not None:
        validate_codex_image_artifact(root, reference_preview_image)
    graph_compile_artifact = _codex_from_aq(
        root, material_receipt.graph_compile_report
    )
    material_validation_artifact = _codex_from_aq(
        root, material_receipt.material_validation
    )
    canonical_material_snapshot = _codex_from_aq(
        root, material_receipt.canonical_material_snapshot
    )
    canonical_scene_snapshot = _codex_from_aq(
        root, material_receipt.canonical_scene_snapshot
    )
    named = [
        plan_artifact,
        input_artifact,
        binding_artifact,
        request_artifact,
        result_codex,
        material_receipt_codex,
        base_state_artifact,
        plan.generation_terminal,
        plan.selection,
        *(
            [plan.companion_selection_receipt]
            if plan.companion_selection_receipt
            else []
        ),
        *(
            [plan.native_core_preparation_receipt]
            if plan.native_core_preparation_receipt
            else []
        ),
        plan.generated_image_evidence,
        plan.semantic_review,
        plan.normalization_receipt,
        plan.adoption,
        plan.material_authoring_manifest,
        plan.material_authoring_receipt,
        *(
            [plan.exact_adoption_preflight]
            if plan.exact_adoption_preflight
            else []
        ),
        graph_compile_artifact,
        material_validation_artifact,
        neutral_preview_artifact,
        preview.raw_swatch_manifest,
        preview.preview_image,
        *([reference_preview_manifest] if reference_preview_manifest else []),
        *([reference_preview_image] if reference_preview_image else []),
        canonical_material_snapshot,
        canonical_scene_snapshot,
    ]
    now = created_at or datetime.now(UTC)
    receipt = ImageGeneratedMaterialPromotionReceipt(
        contract_id=f"image-material-promotion-{plan.session_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=stable_json_digest({item.path: item.sha256 for item in named}),
        source_fingerprint=material_receipt_codex.sha256,
        producer=_PRODUCER,
        provenance=named,
        created_at=now,
        bridge_plan=plan_artifact,
        controller_input=input_artifact,
        controller_binding=binding_artifact,
        controller_execution_request=request_artifact,
        controller_result=result_codex,
        material_phase_receipt=material_receipt_codex,
        promoted_base_state=base_state_artifact,
        generation_terminal=plan.generation_terminal,
        selection=plan.selection,
        companion_selection_receipt=plan.companion_selection_receipt,
        native_core_preparation_receipt=plan.native_core_preparation_receipt,
        generated_image_evidence=plan.generated_image_evidence,
        semantic_review=plan.semantic_review,
        normalization_receipt=plan.normalization_receipt,
        adoption=plan.adoption,
        material_authoring_manifest=plan.material_authoring_manifest,
        material_authoring_receipt=plan.material_authoring_receipt,
        exact_adoption_preflight=plan.exact_adoption_preflight,
        graph_compile_report=graph_compile_artifact,
        material_validation=material_validation_artifact,
        neutral_preview=neutral_preview_artifact,
        neutral_preview_manifest=preview.raw_swatch_manifest,
        neutral_preview_image=preview.preview_image,
        reference_preview_manifest=reference_preview_manifest,
        reference_preview_image=reference_preview_image,
        canonical_material_snapshot=canonical_material_snapshot,
        canonical_scene_snapshot=canonical_scene_snapshot,
        canonical_material_plan_sha256=material_receipt.canonical_material_plan_sha256,
        canonical_scene_spec_sha256=material_receipt.canonical_scene_spec_sha256,
    )
    published_receipt, promotion_artifact = _write_or_adopt(
        root,
        loop_root / "promotion_receipt.json",
        receipt,
        kind="material-promotion-receipt",
        model_type=ImageGeneratedMaterialPromotionReceipt,
    )
    if latest.status == "promoting_material":
        promoted_usage = latest.budget_usage.model_copy(
            update={
                "promotions_consumed": latest.budget_usage.promotions_consumed + 1
            }
        )
        promoted = _make_state(
            plan,
            plan_artifact,
            input_artifact,
            sequence=latest.sequence + 1,
            status="material_promoted",
            budget_usage=promoted_usage,
            created_at=now,
            previous=chain[-1],
            promotion_receipt=promotion_artifact,
            material_phase_receipt=material_receipt_codex,
            base_state=base_state_artifact,
        )
        promoted, promoted_artifact = _append_state(
            root, loop_root, plan, plan_artifact, input_artifact, promoted
        )
        chain = [*chain, (promoted, promoted_artifact)]
        latest = promoted
    if latest.status == "material_promoted":
        waiting = _make_state(
            plan,
            plan_artifact,
            input_artifact,
            sequence=latest.sequence + 1,
            status="waiting_for_quality",
            budget_usage=latest.budget_usage,
            created_at=now,
            previous=chain[-1],
            promotion_receipt=promotion_artifact,
            material_phase_receipt=material_receipt_codex,
            base_state=base_state_artifact,
        )
        latest, latest_artifact = _append_state(
            root, loop_root, plan, plan_artifact, input_artifact, waiting
        )
    else:
        latest_artifact = chain[-1][1]
    return {
        "promotion_receipt": published_receipt.model_dump(mode="json"),
        "promotion_receipt_artifact": promotion_artifact.model_dump(mode="json"),
        "state": latest.model_dump(mode="json"),
        "state_artifact": latest_artifact.model_dump(mode="json"),
        "next_action": "run_integrated_quality",
        "promoted_base_state": base_state_artifact.model_dump(mode="json"),
    }


def finalize_codex_image_material_loop_promotion(
    job_root: Path,
    *,
    material_phase_receipt_artifact: AQV2Artifact,
    neutral_preview_artifact: CodexImageArtifact,
    reference_preview_manifest: CodexImageArtifact | None = None,
    reference_preview_image: CodexImageArtifact | None = None,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Finalize the companion receipt under the authoritative AQ session lock."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    receipt = validate_material_phase_receipt_v2(
        root,
        material_phase_receipt_artifact,
        require_current=True,
    )
    session_root = root / "production" / "autonomy_v2" / receipt.session_id
    with autonomy_session_lock(
        root,
        session_root,
        owner_id="aqv2-image-material-loop-finalize",
        ttl_seconds=180,
    ):
        return _finalize_codex_image_material_loop_promotion_locked(
            root,
            material_phase_receipt_artifact=material_phase_receipt_artifact,
            neutral_preview_artifact=neutral_preview_artifact,
            reference_preview_manifest=reference_preview_manifest,
            reference_preview_image=reference_preview_image,
            created_at=created_at,
        )


def record_codex_image_material_loop_quality_result_locked(
    job_root: Path,
    session_id: str,
    *,
    promotion_receipt_artifact: CodexImageArtifact,
    quality_submission: QualitySubmissionV2 | dict[str, object],
    supervisor_result: dict[str, object],
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Record one already-locked AQ quality outcome in the companion journal and terminal."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    submission = (
        quality_submission
        if isinstance(quality_submission, QualitySubmissionV2)
        else QualitySubmissionV2.model_validate(quality_submission)
    )
    promotion = validate_codex_image_material_promotion_receipt(
        root, promotion_receipt_artifact, require_current=True
    )
    if promotion.session_id != session_id:
        raise ValueError("quality result targets another material-loop session")
    raw_state = supervisor_result.get("state")
    raw_state_artifact = supervisor_result.get("state_artifact")
    raw_terminal = supervisor_result.get("quality_terminal")
    if not isinstance(raw_state, dict) or not isinstance(raw_state_artifact, dict):
        raise ValueError("AQ quality result omits its exact next state")
    if not isinstance(raw_terminal, dict):
        raise ValueError("AQ quality result omits its exact quality terminal")
    base_state = AutonomyStateV2.model_validate_json(
        json.dumps(raw_state, ensure_ascii=False)
    )
    base_state_aq = AQV2Artifact.model_validate_json(
        json.dumps(raw_state_artifact, ensure_ascii=False)
    )
    base_quality_terminal_aq = AQV2Artifact.model_validate_json(
        json.dumps(raw_terminal, ensure_ascii=False)
    )
    validate_v2_artifact(root, base_state_aq)
    base_terminal = validate_quality_terminal_v2(root, base_quality_terminal_aq)
    if (
        base_state.session_id != session_id
        or base_state.quality_terminal != base_quality_terminal_aq
        or base_terminal.integrated_quality_report
        != submission.integrated_quality_report
    ):
        raise ValueError("AQ quality state, terminal, or submitted report differs")
    outcome = supervisor_result.get("outcome")
    expected_terminal_status = {
        "passed": "quality_approved",
        "needs_revision": "review_required",
        "unscorable": "review_required",
        "blocked": "blocked",
        "failed": "failed",
    }.get(outcome)
    if expected_terminal_status is None or base_terminal.status != expected_terminal_status:
        raise ValueError("AQ quality outcome and terminal status are inconsistent")
    source_freeze_aq = base_terminal.source_freeze
    review_bundle_aq = base_terminal.review_bundle
    if source_freeze_aq is not None:
        freeze = cast(
            QualityApprovedSourceFreeze,
            _read_model(root, source_freeze_aq, QualityApprovedSourceFreeze),
        )
        validate_quality_source_freeze(root, freeze)
    if review_bundle_aq is not None:
        validate_quality_review_bundle_v2(root, review_bundle_aq)
    base_state_artifact = _codex_from_aq(root, base_state_aq, kind="base-aq-state")
    base_quality_terminal = _codex_from_aq(
        root, base_quality_terminal_aq, kind="base-quality-terminal"
    )
    integrated_report = _codex_from_aq(
        root, submission.integrated_quality_report, kind="integrated-quality-report"
    )
    quality_freeze = (
        _codex_from_aq(root, source_freeze_aq, kind="quality-source-freeze")
        if source_freeze_aq is not None
        else None
    )
    review_bundle = (
        _codex_from_aq(root, review_bundle_aq, kind="quality-review-bundle")
        if review_bundle_aq is not None
        else None
    )
    loop_root, plan, plan_artifact, _input, _input_artifact, chain = _load_loop_bundle(
        root, session_id
    )
    latest, latest_artifact = chain[-1]
    target_status = {
        "passed": "quality_approved",
        "needs_revision": "review_required",
        "unscorable": "review_required",
        "blocked": "blocked",
        "failed": "failed",
    }[cast(str, outcome)]
    if latest.status == "waiting_for_quality":
        proposed = _make_state(
            plan,
            plan_artifact,
            _input_artifact,
            sequence=latest.sequence + 1,
            status=target_status,
            budget_usage=latest.budget_usage,
            created_at=created_at or datetime.now(UTC),
            previous=chain[-1],
            promotion_receipt=promotion_receipt_artifact,
            material_phase_receipt=promotion.material_phase_receipt,
            base_state=base_state_artifact,
            failure_evidence=(
                base_quality_terminal if target_status in {"blocked", "failed"} else None
            ),
            review_evidence=(
                review_bundle if target_status == "review_required" else None
            ),
            latest_failure=(base_terminal.reason if target_status == "failed" else None),
        )
        latest, latest_artifact = _append_state(
            root, loop_root, plan, plan_artifact, _input_artifact, proposed
        )
    elif latest.status != target_status:
        raise PermissionError("material-loop quality journal is already terminal")
    elif (
        latest.base_state != base_state_artifact
        or latest.promotion_receipt != promotion_receipt_artifact
        or latest.material_phase_receipt != promotion.material_phase_receipt
    ):
        raise ValueError("existing companion quality state differs from AQ result")
    terminal_provenance = [
        plan_artifact,
        latest_artifact,
        base_state_artifact,
        base_quality_terminal,
        *([review_bundle] if review_bundle else []),
        promotion_receipt_artifact,
        promotion.material_phase_receipt,
        integrated_report,
        *([quality_freeze] if quality_freeze else []),
    ]
    terminal = CodexImageMaterialLoopTerminal(
        contract_id=f"material-loop-terminal-{session_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=stable_json_digest(
            {item.path: item.sha256 for item in terminal_provenance}
        ),
        source_fingerprint=base_quality_terminal.sha256,
        producer=_PRODUCER,
        provenance=terminal_provenance,
        created_at=created_at or datetime.now(UTC),
        bridge_plan=plan_artifact,
        latest_state=latest_artifact,
        base_state=base_state_artifact,
        base_quality_terminal=base_quality_terminal,
        review_bundle=review_bundle,
        promotion_receipt=promotion_receipt_artifact,
        material_phase_receipt=promotion.material_phase_receipt,
        integrated_quality_report=integrated_report,
        quality_freeze=quality_freeze,
        status=cast(Any, target_status),
        material_candidate_promoted=True,
        quality_passed=outcome == "passed",
        limitations=[
            "Companion completion does not claim base AQ, package, destination, "
            "or human review completion."
        ],
    )
    published_terminal, terminal_artifact = _write_or_adopt(
        root,
        loop_root / "terminal.json",
        terminal,
        kind="material-loop-terminal",
        model_type=CodexImageMaterialLoopTerminal,
    )
    return {
        "state": latest.model_dump(mode="json"),
        "state_artifact": latest_artifact.model_dump(mode="json"),
        "terminal": published_terminal.model_dump(mode="json"),
        "terminal_artifact": terminal_artifact.model_dump(mode="json"),
    }


def validate_codex_image_material_loop_terminal(
    job_root: Path,
    terminal_artifact: CodexImageArtifact,
    *,
    require_current: bool = True,
) -> CodexImageMaterialLoopTerminal:
    """Recursively validate one terminal companion before downstream AQ delivery."""

    root = ensure_contained_codex_image_path(job_root, job_root, must_exist=True)
    validate_codex_image_artifact(root, terminal_artifact)
    terminal = load_codex_image_model(
        root, terminal_artifact, CodexImageMaterialLoopTerminal
    )
    expected_path = (
        PurePosixPath("production")
        / "autonomy_v2"
        / terminal.session_id
        / _LOOP_DIR
        / "terminal.json"
    ).as_posix()
    if (
        terminal.producer != _PRODUCER
        or terminal.contract_id != f"material-loop-terminal-{terminal.session_id}"
        or terminal_artifact.path != expected_path
    ):
        raise ValueError("material-loop terminal publisher or path is not canonical")
    loop_root, plan, plan_artifact, _input, _input_artifact, chain = _load_loop_bundle(
        root, terminal.session_id
    )
    del loop_root
    latest, latest_artifact = chain[-1]
    if (
        terminal.bridge_plan != plan_artifact
        or terminal.latest_state != latest_artifact
        or terminal.status != latest.status
        or terminal.job_id != plan.job_id
        or terminal.workflow_id != plan.workflow_id
        or terminal.dispatch_id != plan.dispatch_id
    ):
        raise ValueError("material-loop terminal differs from its latest journal state")
    base_state = cast(
        AutonomyStateV2,
        _read_model(root, _aq_from_codex(terminal.base_state, role="state"), AutonomyStateV2),
    )
    if not terminal.material_candidate_promoted:
        if (
            terminal.status not in {"failed", "cancelled"}
            or terminal.promotion_receipt is not None
            or terminal.material_phase_receipt is not None
            or latest.failure_evidence is None
        ):
            raise ValueError("unpromoted terminal is not an exact failed attempt")
        if terminal.source_fingerprint != latest.failure_evidence.sha256:
            raise ValueError("pre-promotion terminal source fingerprint changed")
        validate_codex_image_artifact(root, latest.failure_evidence)
        if not base_state.provenance:
            raise ValueError("pre-promotion terminal base state omits host evidence")
        if latest.failure_evidence.kind == "material-phase-rollback-receipt":
            rollback = cast(
                MaterialPhaseRollbackReceiptV2,
                _read_model(
                    root,
                    _aq_from_codex(
                        latest.failure_evidence,
                        role="material_phase_rollback_receipt",
                    ),
                    MaterialPhaseRollbackReceiptV2,
                ),
            )
            if rollback.controller_result != base_state.provenance[-1]:
                raise ValueError("pre-promotion rollback targets another host result")
            for nested in rollback.provenance:
                validate_v2_artifact(root, nested)
        elif latest.failure_evidence.kind == "material-promotion-intent":
            intent = cast(
                MaterialPromotionIntentV2,
                _read_model(
                    root,
                    _aq_from_codex(
                        latest.failure_evidence,
                        role="material_promotion_intent",
                    ),
                    MaterialPromotionIntentV2,
                ),
            )
            if intent.controller_result != base_state.provenance[-1]:
                raise ValueError("pre-promotion intent targets another host result")
            for nested in intent.provenance:
                validate_v2_artifact(root, nested)
        elif (
            latest.failure_evidence.path,
            latest.failure_evidence.sha256,
        ) != (
            base_state.provenance[-1].path,
            base_state.provenance[-1].sha256,
        ):
            raise ValueError("pre-promotion failure evidence differs from the host result")
        for nested in terminal.provenance:
            validate_codex_image_artifact(root, nested)
        if require_current:
            session_root = root / "production" / "autonomy_v2" / plan.session_id
            base_chain = _base_aq_state_chain(root, session_root)
            current_state, current_artifact = base_chain[-1]
            if (
                current_state != base_state
                or current_artifact.path != terminal.base_state.path
                or current_artifact.sha256 != terminal.base_state.sha256
            ):
                raise ValueError("pre-promotion terminal base state is no longer current")
        return terminal
    if terminal.promotion_receipt is None or terminal.material_phase_receipt is None:
        raise ValueError("material-loop quality terminal omits promotion closure")
    promotion = validate_codex_image_material_promotion_receipt(
        root,
        terminal.promotion_receipt,
        require_current=require_current,
    )
    if promotion.material_phase_receipt != terminal.material_phase_receipt:
        raise ValueError("material-loop terminal promotion closure changed")
    if terminal.base_quality_terminal is None:
        raise ValueError("material-loop quality terminal omits base AQ terminal")
    base_quality = validate_quality_terminal_v2(
        root,
        _aq_from_codex(terminal.base_quality_terminal, role="quality-terminal"),
    )
    if terminal.source_fingerprint != terminal.base_quality_terminal.sha256:
        raise ValueError("material-loop terminal source fingerprint changed")
    if (
        base_state.quality_terminal is None
        or base_state.quality_terminal.sha256 != terminal.base_quality_terminal.sha256
        or terminal.integrated_quality_report is None
        or base_quality.integrated_quality_report.sha256
        != terminal.integrated_quality_report.sha256
    ):
        raise ValueError("material-loop terminal differs from base AQ quality evidence")
    validate_codex_image_artifact(root, terminal.integrated_quality_report)
    expected_status = {
        "quality_approved": "quality_approved",
        "review_required": "review_required",
        "blocked": "blocked",
        "failed": "failed",
    }[base_quality.status]
    if terminal.status != expected_status:
        raise ValueError("material-loop and base AQ terminal statuses differ")
    if base_quality.status == "quality_approved":
        if terminal.quality_freeze is None or base_quality.source_freeze is None:
            raise ValueError("completed material loop omits exact quality freeze")
        freeze = cast(
            QualityApprovedSourceFreeze,
            _read_model(
                root,
                _aq_from_codex(terminal.quality_freeze, role="source-freeze"),
                QualityApprovedSourceFreeze,
            ),
        )
        validate_quality_source_freeze(root, freeze)
        if terminal.quality_freeze.sha256 != base_quality.source_freeze.sha256:
            raise ValueError("material-loop terminal quality freeze changed")
    elif terminal.quality_freeze is not None:
        raise ValueError("nonpassing material loop cannot carry a quality freeze")
    if base_quality.status == "review_required":
        if terminal.review_bundle is None or base_quality.review_bundle is None:
            raise ValueError("review-required material loop omits review bundle")
        validate_quality_review_bundle_v2(
            root,
            _aq_from_codex(terminal.review_bundle, role="quality-review-bundle"),
        )
        if terminal.review_bundle.sha256 != base_quality.review_bundle.sha256:
            raise ValueError("material-loop terminal review bundle changed")
    elif terminal.review_bundle is not None:
        raise ValueError("non-review material loop cannot carry a review bundle")
    for nested in terminal.provenance:
        validate_codex_image_artifact(root, nested)
    if require_current:
        session_root = root / "production" / "autonomy_v2" / plan.session_id
        base_chain = _base_aq_state_chain(root, session_root)
        anchors = [
            index
            for index, (candidate, artifact) in enumerate(base_chain)
            if candidate == base_state
            and artifact.path == terminal.base_state.path
            and artifact.sha256 == terminal.base_state.sha256
        ]
        if len(anchors) != 1:
            raise ValueError("material-loop terminal base state is not in the AQ chain")
        current_state, _current_artifact = base_chain[-1]
        material_binding = (
            terminal.material_phase_receipt.path,
            terminal.material_phase_receipt.sha256,
        )
        current_provenance = {
            (item.path, item.sha256) for item in current_state.provenance
        }
        if (
            current_state.plan.sha256 != plan.aq_plan.sha256
            or current_state.session_id != terminal.session_id
            or current_state.quality_terminal is None
            or current_state.quality_terminal.sha256
            != terminal.base_quality_terminal.sha256
            or material_binding not in current_provenance
        ):
            raise ValueError("current AQ descendant does not retain material quality closure")
        expected_freeze_sha = (
            terminal.quality_freeze.sha256 if terminal.quality_freeze else None
        )
        observed_freeze_sha = (
            current_state.source_freeze.sha256 if current_state.source_freeze else None
        )
        if observed_freeze_sha != expected_freeze_sha:
            raise ValueError("current AQ descendant changed the exact quality freeze")
    return terminal


def _controller_execution_status_projection(
    root: Path,
    loop_root: Path,
    plan: ImageGeneratedMaterialBridgePlan,
    controller_input: ImageGeneratedMaterialControllerInput,
    input_artifact: CodexImageArtifact,
    base_state: AutonomyStateV2,
) -> dict[str, object]:
    """Project exact formal controller request/result evidence without mutating it."""

    binding_model: ImageGeneratedMaterialControllerBinding | None = None
    binding_artifact: CodexImageArtifact | None = None
    binding_path = loop_root / "controller_binding.json"
    request: ControllerExecutionRequest | None = None
    request_artifact: CodexImageArtifact | None = None
    result: ControllerResult | None = None
    result_artifact: CodexImageArtifact | None = None
    if binding_path.is_file():
        binding_artifact = artifact_for_codex_image(
            root,
            binding_path,
            artifact_id=f"material-controller-binding-{plan.session_id}",
            kind="material-controller-binding",
            media_type="application/json",
        )
        binding_model = load_codex_image_model(
            root,
            binding_artifact,
            ImageGeneratedMaterialControllerBinding,
        )
        for nested in binding_model.provenance:
            validate_codex_image_artifact(root, nested)
        request_artifact = binding_model.controller_execution_request
        request = load_codex_image_model(
            root,
            request_artifact,
            ControllerExecutionRequest,
        )
    elif base_state.provenance and base_state.provenance[-1].path.endswith(
        "/result.json"
    ):
        result_artifact = _codex_from_aq(
            root,
            base_state.provenance[-1],
            kind="controller-result",
        )
        result = load_codex_image_model(root, result_artifact, ControllerResult)
        request_path = root / result_artifact.path.rsplit("/", 1)[0] / "request.json"
        request_artifact = artifact_for_codex_image(
            root,
            request_path,
            artifact_id=f"request-{result.execution_id}",
            kind="controller-execution-request",
            media_type="application/json",
        )
        request = load_codex_image_model(
            root,
            request_artifact,
            ControllerExecutionRequest,
        )
    if request is not None and request_artifact is not None:
        _validate_controller_request_binding(
            request,
            plan=plan,
            controller_input=controller_input,
            input_artifact=input_artifact,
        )
        if result is None:
            result_path = root / request_artifact.path.rsplit("/", 1)[0] / "result.json"
            if result_path.is_file():
                result_artifact = artifact_for_codex_image(
                    root,
                    result_path,
                    artifact_id=f"result-{request.execution_id}",
                    kind="controller-result",
                    media_type="application/json",
                )
                result = load_codex_image_model(root, result_artifact, ControllerResult)
        if result is not None and (
            result.execution_id != request.execution_id
            or result.request.path != request_artifact.path
            or result.request.sha256 != request_artifact.sha256
        ):
            raise ValueError("controller status result differs from its exact request")
    return {
        "status": (
            result.status
            if result is not None
            else "request_published" if request is not None else "not_started"
        ),
        "binding": (
            binding_model.model_dump(mode="json") if binding_model is not None else None
        ),
        "binding_artifact": (
            binding_artifact.model_dump(mode="json")
            if binding_artifact is not None
            else None
        ),
        "request": request.model_dump(mode="json") if request is not None else None,
        "request_artifact": (
            request_artifact.model_dump(mode="json")
            if request_artifact is not None
            else None
        ),
        "result": result.model_dump(mode="json") if result is not None else None,
        "result_artifact": (
            result_artifact.model_dump(mode="json")
            if result_artifact is not None
            else None
        ),
    }


def _remaining_budget_status_projection(
    root: Path,
    plan: ImageGeneratedMaterialBridgePlan,
    state: CodexImageMaterialLoopState,
    base_state: AutonomyStateV2,
) -> dict[str, dict[str, int]]:
    """Report non-negative remaining companion and base AQ allowances by exact field."""

    material_limits = ImageMaterialLoopBudgetUsage(
        normalization_runs=1,
        semantic_reviews=1,
        controller_invocations=1,
        promotions_consumed=1,
    )
    material_remaining = {
        name: getattr(material_limits, name) - getattr(state.budget_usage, name)
        for name in ImageMaterialLoopBudgetUsage.model_fields
    }
    budget = cast(
        AutonomyBudgetV2,
        _read_model(root, _aq_from_codex(plan.aq_budget, role="budget"), AutonomyBudgetV2),
    )
    aq_plan = cast(
        AutonomyPlanV2,
        _read_model(root, _aq_from_codex(plan.aq_plan, role="plan"), AutonomyPlanV2),
    )
    base_limits = {
        "initial_candidates": budget.initial_candidates,
        "structural_rounds": budget.structural_rounds,
        "parametric_convergence_iterations": budget.parametric_convergence_iterations,
        "material_rounds": budget.material_rounds,
        "total_blender_builds": budget.total_blender_builds,
        "total_quality_evaluations": budget.total_quality_evaluations,
        "controller_invocations": budget.controller_invocations,
        "delivery_runs": budget.delivery_runs,
        "canonical_promotions": budget.canonical_promotions,
        "package_repairs": budget.package_repairs,
        "total_actions": min(budget.global_action_limit, aq_plan.action_limit),
    }
    if any(
        getattr(base_state.budget_usage, name) > limit
        for name, limit in base_limits.items()
    ):
        raise ValueError("base AQ budget usage exceeds the immutable loop authorization")
    base_remaining = {
        name: limit - getattr(base_state.budget_usage, name)
        for name, limit in base_limits.items()
    }
    return {"material_loop": material_remaining, "base_aq": base_remaining}


def get_codex_image_material_loop_status(
    job_root: Path,
    session_id: str,
) -> dict[str, object]:
    """Reconstruct and report the current material-loop companion without mutation."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    loop_root, plan, plan_artifact, controller_input, input_artifact, chain = (
        _load_loop_bundle(root, session_id)
    )
    latest, latest_artifact = chain[-1]
    session_root = root / "production" / "autonomy_v2" / session_id
    base_chain = _base_aq_state_chain(root, session_root)
    base_state, base_state_artifact = base_chain[-1]
    expected_base_state = latest.base_state or _aq_from_codex(
        plan.current_state,
        role="state",
    )
    base_state_current = any(
        artifact.path == expected_base_state.path
        and artifact.sha256 == expected_base_state.sha256
        for _state, artifact in base_chain
    )
    terminal_path = loop_root / "terminal.json"
    terminal: dict[str, object] | None = None
    terminal_current = False
    latest_validation_error: str | None = None
    if terminal_path.is_file():
        terminal_artifact = artifact_for_codex_image(
            root,
            terminal_path,
            artifact_id=f"material-loop-terminal-{session_id}",
            kind="material-loop-terminal",
            media_type="application/json",
        )
        parsed_terminal = validate_codex_image_material_loop_terminal(
            root,
            terminal_artifact,
            require_current=False,
        )
        terminal = parsed_terminal.model_dump(mode="json")
        try:
            validate_codex_image_material_loop_terminal(
                root,
                terminal_artifact,
                require_current=True,
            )
            terminal_current = True
        except (PermissionError, ValueError) as exc:
            latest_validation_error = str(exc)
    current = terminal_current if terminal is not None else base_state_current
    stale = not current
    controller_execution = _controller_execution_status_projection(
        root,
        loop_root,
        plan,
        controller_input,
        input_artifact,
        base_state,
    )
    delivery_progress = {
        "requested_profiles": plan.requested_delivery_profiles,
        "phase": base_state.phase,
        "status": base_state.status,
        "next_action": base_state.next_action,
        "source_freeze": (
            base_state.source_freeze.model_dump(mode="json")
            if base_state.source_freeze is not None
            else None
        ),
        "delivery_plan": (
            base_state.delivery_plan.model_dump(mode="json")
            if base_state.delivery_plan is not None
            else None
        ),
        "delivery_terminal": (
            base_state.delivery_terminal.model_dump(mode="json")
            if base_state.delivery_terminal is not None
            else None
        ),
        "results": [item.model_dump(mode="json") for item in base_state.delivery_results],
    }
    return {
        "bridge_plan": plan.model_dump(mode="json"),
        "bridge_plan_artifact": plan_artifact.model_dump(mode="json"),
        "controller_input": controller_input.model_dump(mode="json"),
        "controller_input_artifact": input_artifact.model_dump(mode="json"),
        "state": latest.model_dump(mode="json"),
        "state_artifact": latest_artifact.model_dump(mode="json"),
        "state_count": len(chain),
        "base_state": base_state.model_dump(mode="json"),
        "base_state_artifact": base_state_artifact.model_dump(mode="json"),
        "controller_execution": controller_execution,
        "delivery_progress": delivery_progress,
        "remaining_budget": _remaining_budget_status_projection(
            root,
            plan,
            latest,
            base_state,
        ),
        "terminal": terminal,
        "terminal_status": terminal.get("status") if terminal is not None else None,
        "current": current,
        "stale": stale,
        "unverified": terminal is None,
        "latest_validation_error": latest_validation_error,
        "path": loop_root.relative_to(root).as_posix(),
    }
