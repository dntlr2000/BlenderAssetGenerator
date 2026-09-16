"""Project exact historical fidelity inputs into a current material round without rewriting them."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..blender_artifacts import native_io_path
from .models import MaterialClosureSourceBindingArtifact
from .round_models import MaterialClosureSourceBindingV02

if TYPE_CHECKING:
    from ..autonomy_v2.models import AQV2Artifact
    from ..reference_fidelity.models import FidelityArtifact


@dataclass(frozen=True)
class FidelityClosureContext:
    """Separate exact rendered files and proved historical source aliases from current inputs."""

    input_hashes: dict[str, str] = field(default_factory=dict)
    render_paths: frozenset[str] = frozenset()
    # Key is the immutable root, JSON location, original alias and original digest.
    snapshot_substitutions: dict[tuple[str, str, str, str], tuple[str, str]] = field(
        default_factory=dict
    )


def _quality_snapshot_target(
    root: Path,
    original: AQV2Artifact,
    promoted_snapshot: AQV2Artifact,
    reserved: FidelityArtifact,
    *,
    canonical_path: str,
) -> tuple[str, str] | None:
    """Resolve a historical canonical alias only through its exact promoted and reserved bytes."""
    from ..reference_fidelity.models import FidelityArtifact
    from ..reference_fidelity.service import read_artifact

    material_bytes = read_artifact(
        root, FidelityArtifact(path=promoted_snapshot.path, sha256=promoted_snapshot.sha256)
    )
    snapshot = read_artifact(root, reserved)
    if (
        original.path not in {canonical_path, promoted_snapshot.path}
        or original.sha256 != reserved.sha256
        or original.sha256 != promoted_snapshot.sha256
        or original.byte_size != len(snapshot)
        or promoted_snapshot.byte_size != len(material_bytes)
        or snapshot != material_bytes
    ):
        raise ValueError("fidelity quality source is not its exact promoted/reserved snapshot")
    # An immutable receipt snapshot already has the correct path; only the old live alias moves.
    return (reserved.path, reserved.sha256) if original.path == canonical_path else None


def collect_fidelity_closure_context(
    root: Path,
    binding: MaterialClosureSourceBindingArtifact,
) -> FidelityClosureContext:
    """Use an exact reserved round to resolve rendered PNGs and prior promoted source snapshots."""

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
    substitutions = {}
    # Full submissions can carry the same historical scene/material aliases as their Blend.
    sources = (
        ("candidate_blend", "blender/scene.blend", material.authoring_blend_snapshot,
         reentry.source_blend),
        ("authoring_blend", "blender/scene.blend", material.authoring_blend_snapshot,
         reentry.source_blend),
        ("scene_spec", "analysis/scene_spec.json", material.canonical_scene_snapshot,
         reentry.source_scene),
        ("material_plan", "analysis/material_plan.json", material.canonical_material_snapshot,
         FidelityArtifact(path=material.canonical_material_snapshot.path,
                          sha256=material.canonical_material_snapshot.sha256)),
    )
    for field_name, canonical_path, promoted, reserved in sources:
        original = getattr(submission, field_name)
        if original is None:
            continue
        target = _quality_snapshot_target(
            root, original, promoted, reserved, canonical_path=canonical_path
        )
        if target is not None and attempt.quality_submission.path in hashes:
            substitutions[(
                attempt.quality_submission.path, f"$.{field_name}",
                original.path, original.sha256,
            )] = target
    return FidelityClosureContext(hashes, renders, substitutions)
