"""Project exact historical fidelity inputs into a current material round without rewriting them."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..blender_artifacts import native_io_path
from .models import MaterialClosureSourceBindingArtifact
from .round_models import MaterialClosureSourceBindingV02


@dataclass(frozen=True)
class FidelityClosureContext:
    """Separate exact rendered files and one proved historical Blend alias from current inputs."""

    input_hashes: dict[str, str] = field(default_factory=dict)
    render_paths: frozenset[str] = frozenset()
    # Key is the immutable root, JSON location, original alias and original digest.
    snapshot_substitutions: dict[tuple[str, str, str, str], tuple[str, str]] = field(
        default_factory=dict
    )


def collect_fidelity_closure_context(
    root: Path,
    binding: MaterialClosureSourceBindingArtifact,
) -> FidelityClosureContext:
    """Use only an exact reserved round to resolve its rendered PNGs and prior Blend snapshot."""

    if not isinstance(binding, MaterialClosureSourceBindingV02):
        return FidelityClosureContext()

    from ..autonomy_v2.material_phase_models import MaterialPhaseReceiptV2
    from ..autonomy_v2.models import AutonomyPlanV2, AutonomyStateV2
    from ..autonomy_v2.quality_revision_models import QualityAttemptV01
    from ..autonomy_v2.quality_revision_service import (
        _validate_attempt_artifacts,
        active_reentry,
        fidelity_authoring_inputs,
        load_optional_loop,
    )
    from ..autonomy_v2.supervisor_service import QualitySubmissionV2
    from ..reference_fidelity.models import FidelityArtifact, VisualFindingSetV01
    from ..reference_fidelity.service import read_artifact
    from .preflight import validate_exact_artifact
    from .round_service import validate_round_source

    state = AutonomyStateV2.model_validate_json(
        Path(native_io_path(validate_exact_artifact(root, binding.source_state))).read_bytes()
    )
    plan = AutonomyPlanV2.model_validate_json(
        Path(native_io_path(validate_exact_artifact(root, state.plan))).read_bytes()
    )
    if load_optional_loop(root, plan.session_id) is None:
        return FidelityClosureContext()
    validate_round_source(root, binding, plan)
    inputs = fidelity_authoring_inputs(root, plan, state, [])
    hashes = {item.path: item.sha256 for item in inputs}
    reentry = active_reentry(root, plan, state)
    if reentry is None:
        return FidelityClosureContext(input_hashes=hashes)
    attempt = QualityAttemptV01.model_validate_json(read_artifact(root, reentry.attempt))
    _validate_attempt_artifacts(root, attempt)
    if reentry.source_scene.sha256 != attempt.scene_spec.sha256:
        raise ValueError("fidelity closure reentry binds another quality source")
    review = VisualFindingSetV01.model_validate_json(read_artifact(root, attempt.visual_review))
    renders = frozenset(item.path for item in review.evidence.passes.values())
    if not renders <= hashes.keys():
        raise ValueError("fidelity closure omitted the exact rendered pass inputs")
    submission = QualitySubmissionV2.model_validate_json(
        read_artifact(root, attempt.quality_submission)
    )
    material = MaterialPhaseReceiptV2.model_validate_json(
        read_artifact(root, attempt.material_receipt)
    )
    material_blend = material.authoring_blend_snapshot
    material_bytes = read_artifact(
        root, FidelityArtifact(path=material_blend.path, sha256=material_blend.sha256)
    )
    snapshot = read_artifact(root, reentry.source_blend)
    original = submission.candidate_blend
    if (
        original.path != "blender/scene.blend"
        or original.sha256 != reentry.source_blend.sha256
        or original.sha256 != material_blend.sha256
        or original.byte_size != len(snapshot)
        or material_blend.byte_size != len(material_bytes)
        or snapshot != material_bytes
    ):
        raise ValueError("fidelity quality Blend is not its exact reserved material snapshot")
    substitutions = (
        {
            (
                attempt.quality_submission.path,
                "$.candidate_blend",
                original.path,
                original.sha256,
            ): (
                reentry.source_blend.path,
                reentry.source_blend.sha256,
            )
        }
        if attempt.quality_submission.path in hashes
        else {}
    )
    return FidelityClosureContext(hashes, renders, substitutions)
