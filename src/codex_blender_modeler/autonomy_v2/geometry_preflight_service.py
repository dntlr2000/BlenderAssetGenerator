"""Read-only pre-submission checks shared with the mandatory geometry promotion validator."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from ..blender_artifacts import native_io_path
from ..production.validation import ensure_contained_production_path
from .candidate_validation_service import (
    CandidateBudgetExhausted,
    CandidateContractInvalid,
    _read_bytes,
    _require_candidate_materialization_reserve,
    _reserve_candidate_budget,
    load_geometry_candidate_contracts,
    validate_geometry_candidate_data,
)
from .delivery_service import artifact_for_v2, validate_v2_artifact
from .geometry_preflight_models import GeometryAuthoringPreflightV01
from .models import AQV2Artifact, AutonomyBudgetV03, RootAuthorizationV2

GEOMETRY_PREFLIGHT_KIND = "geometry_authoring_preflight"


def submit_preflighted_geometry_candidate_v2(
    job_id: str,
    session_id: str,
    *,
    assignment: AQV2Artifact,
    preflight: AQV2Artifact,
    timeout_seconds: int = 900,
) -> dict[str, object]:
    """Require the explicit companion for one campaign desktop request or its exact resume."""

    from ..production.controller_executor import DesktopInSessionController
    from .controller_bridge import execute_autonomy_v2_controller

    if preflight.kind != GEOMETRY_PREFLIGHT_KIND:
        raise ValueError("preflighted submission requires the explicit geometry preflight kind")
    return execute_autonomy_v2_controller(
        job_id,
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=[preflight],
        controller=DesktopInSessionController(),
        timeout_seconds=timeout_seconds,
    )


def geometry_preflight_inputs(root: Path, inputs: list[AQV2Artifact]) -> list[AQV2Artifact]:
    """Include every explicit report dependency in both fresh and resumed request input maps."""

    matches = [item for item in inputs if item.kind == GEOMETRY_PREFLIGHT_KIND]
    if not matches:
        return inputs
    if len(matches) != 1:
        raise ValueError("geometry submission requires exactly one preflight companion")
    report = GeometryAuthoringPreflightV01.model_validate_json(
        _read_bytes(validate_v2_artifact(root, matches[0]))
    )
    expanded = list(inputs)
    for required in (
        report.current_state,
        report.root_authorization,
        report.budget,
        *report.source_inputs,
        report.candidate_modeling_plan,
        report.candidate_scene_spec_v03,
        *([report.structure_authoring] if report.structure_authoring is not None else []),
    ):
        validate_v2_artifact(root, required)
        present = [item for item in expanded if item.path == required.path]
        if present:
            if len(present) != 1 or (present[0].sha256, present[0].byte_size) != (
                required.sha256,
                required.byte_size,
            ):
                raise ValueError("geometry preflight dependency differs from request inputs")
        else:
            # Match existing fidelity context: a declared read-only assignment input.
            expanded.append(required.model_copy(update={"kind": "assignment"}))
    return expanded


def _candidate_artifact(root: Path, path: str | Path, kind: str) -> AQV2Artifact:
    """Accept only existing contained staging candidates, never canonical authoring aliases."""

    safe = ensure_contained_production_path(root, root / path, must_exist=True)
    if not safe.relative_to(root).as_posix().startswith(("fidelity/", "geometry/candidates/")):
        raise PermissionError("geometry preflight candidates must remain in declared staging")
    return artifact_for_v2(root, safe, artifact_id=kind, kind=kind)


def preflight_aq_geometry_authoring(
    job_id: str,
    session_id: str,
    *,
    modeling_plan_path: str | Path,
    scene_spec_v03_path: str | Path,
    structure_authoring_path: str | Path | None = None,
) -> GeometryAuthoringPreflightV01:
    """Check candidates and cost while binding any existing canonical scene and rollback Blend."""

    from .controller_bridge import (
        _consume_controller_budget,
        _required_authoring_profile,
        _session_bundle,
        _validate_controller_authority,
    )
    from .quality_revision_service import (
        active_reentry,
        fidelity_authoring_inputs,
        load_optional_loop,
    )

    root, _session, plan, budget, state, state_artifact = _session_bundle(job_id, session_id)
    if state.status != "running" or state.next_action != "execute_controller":
        raise PermissionError("geometry authoring preflight requires a fresh controller boundary")
    _validate_controller_authority(root, plan, budget)
    if _required_authoring_profile(root, plan, state) != "geometry_authoring":
        raise PermissionError("geometry preflight cannot replace the current material boundary")
    authorization = RootAuthorizationV2.model_validate_json(
        _read_bytes(validate_v2_artifact(root, plan.root_authorization))
    )
    validate_v2_artifact(root, authorization.primary_reference)
    if isinstance(budget, AutonomyBudgetV03):
        from .fidelity_budget_service import require_funded_loop

        require_funded_loop(root, session_id, budget)
    loop_binding = load_optional_loop(root, session_id)
    sources = [authorization.primary_reference]
    for name in (
        "job.json",
        "analysis/reference_analysis.json",
        "analysis/camera_solution.json",
        "analysis/modeling_plan.json",
        "analysis/scene_spec.json",
        "blender/scene.blend",
    ):
        if name in {"analysis/scene_spec.json", "blender/scene.blend"} and not os.path.exists(
            native_io_path(root / name)
        ):
            continue
        sources.append(
            artifact_for_v2(
                root,
                root / name,
                artifact_id=f"preflight-source-{len(sources)}",
                kind="source",
            )
        )
    sources = fidelity_authoring_inputs(root, plan, state, sources)
    modeling_artifact = _candidate_artifact(root, modeling_plan_path, "candidate_modeling_plan")
    scene_artifact = _candidate_artifact(root, scene_spec_v03_path, "candidate_scene_spec_v03")
    structure = (
        _candidate_artifact(root, structure_authoring_path, "structure_authoring")
        if structure_authoring_path is not None
        else None
    )
    base = dict(
        job_id=job_id,
        session_id=session_id,
        current_state=state_artifact,
        root_authorization=plan.root_authorization,
        budget=plan.budget,
        source_inputs=sources,
        candidate_modeling_plan=modeling_artifact,
        candidate_scene_spec_v03=scene_artifact,
        structure_authoring=structure,
    )
    object_count = None
    try:
        modeling, scene = load_geometry_candidate_contracts(
            root=root,
            modeling_artifact=modeling_artifact,
            scene_artifact=scene_artifact,
        )
        validate_geometry_candidate_data(
            root=root,
            authorization=authorization,
            modeling=modeling,
            scene=scene,
        )
        if loop_binding is not None and structure is None:
            raise CandidateContractInvalid(
                "fidelity preflight requires explicit StructureAuthoring"
            )
        if structure is not None:
            from ..reference_fidelity.authoring import (
                StructureAuthoringV01,
                validate_structure_authoring,
            )

            authoring = StructureAuthoringV01.model_validate_json(
                _read_bytes(validate_v2_artifact(root, structure))
            )
            hypothesis_model = validate_structure_authoring(root, authoring)
            if (hypothesis_model.reference.path, hypothesis_model.reference.sha256) != (
                authorization.primary_reference.path,
                authorization.primary_reference.sha256,
            ):
                raise ValueError("structure hypothesis reference differs from RootAuthorization")
            if loop_binding is not None and authoring.hypothesis != loop_binding[0].hypothesis:
                raise ValueError("structure authoring belongs to a different fidelity loop")
            if authoring.scene != scene or authoring.modeling_plan != modeling:
                raise CandidateContractInvalid(
                    "structure authoring differs from the staged candidates"
                )
            hypothesis = artifact_for_v2(
                root,
                root / authoring.hypothesis.path,
                artifact_id="preflight-hypothesis",
                kind="modeling_hypothesis",
            )
            if hypothesis.path not in {item.path for item in sources}:
                sources.append(hypothesis)
        object_count = len(scene.objects)
        reentry = active_reentry(root, plan, state)
        _require_candidate_materialization_reserve(
            loop_binding,
            reentry,
            object_count,
        )
        for field, required, limit in (
            (
                "controller_invocations",
                state.budget_usage.controller_invocations + 1,
                budget.controller_invocations,
            ),
            (
                "total_actions",
                state.budget_usage.total_actions + 2,
                min(budget.global_action_limit, plan.action_limit),
            ),
        ):
            if required > limit:
                raise CandidateBudgetExhausted(field, required, limit)
        # Projection includes the not-yet-issued controller as well as its eventual build action.
        usage = _reserve_candidate_budget(
            _consume_controller_budget(state.budget_usage, budget),
            budget,
            materialization_builds=object_count,
            structural_reentry=reentry is not None and reentry.route == "structural_reentry",
            parametric_reentry=reentry is not None and reentry.route == "parametric_revision",
        )
    except (CandidateContractInvalid, CandidateBudgetExhausted) as exc:
        return GeometryAuthoringPreflightV01(
            **base,
            outcome=(
                "budget_exhausted"
                if isinstance(exc, CandidateBudgetExhausted)
                else "invalid_candidate"
            ),
            issues=[str(exc)],
            candidate_object_count=object_count,
            required_blender_builds=object_count + 1 if object_count is not None else None,
        )
    return GeometryAuthoringPreflightV01(
        **base,
        outcome="passed",
        issues=[],
        candidate_object_count=object_count,
        required_blender_builds=object_count + 1,
        budget_usage_after=usage,
    )


def validate_geometry_preflight_submission(
    *,
    root: Path,
    job_id: str,
    session_id: str,
    inputs: list[AQV2Artifact],
    allowed_output_paths: list[str],
    expected_output_sha256: dict[str, str] | None,
) -> dict[str, str] | None:
    """Replay an explicitly supplied preflight and freeze its exact bytes in the new request."""

    matches = [item for item in inputs if item.kind == GEOMETRY_PREFLIGHT_KIND]
    if not matches:
        # Historical request schemas and callers have no implicit companion or new authority.
        return expected_output_sha256
    if len(matches) != 1:
        raise ValueError("geometry submission requires exactly one preflight companion")
    report = GeometryAuthoringPreflightV01.model_validate_json(
        _read_bytes(validate_v2_artifact(root, matches[0]))
    )
    if (report.job_id, report.session_id) != (job_id, session_id):
        raise ValueError("geometry preflight belongs to another session")
    for artifact in (
        report.current_state,
        report.root_authorization,
        report.budget,
        *report.source_inputs,
        report.candidate_modeling_plan,
        report.candidate_scene_spec_v03,
        *([report.structure_authoring] if report.structure_authoring is not None else []),
    ):
        validate_v2_artifact(root, artifact)
    current = preflight_aq_geometry_authoring(
        job_id,
        session_id,
        modeling_plan_path=report.candidate_modeling_plan.path,
        scene_spec_v03_path=report.candidate_scene_spec_v03.path,
        structure_authoring_path=(
            report.structure_authoring.path if report.structure_authoring is not None else None
        ),
    )
    if current != report or report.outcome != "passed":
        raise ValueError("geometry preflight is stale, failed, or differs from its current inputs")
    hashes = dict(expected_output_sha256 or {})
    candidates = {
        "modeling_plan.json": report.candidate_modeling_plan,
        "scene_spec_v03.json": report.candidate_scene_spec_v03,
    }
    for name, artifact in candidates.items():
        paths = [path for path in allowed_output_paths if PurePosixPath(path).name == name]
        if len(paths) != 1:
            raise ValueError("geometry preflight requires the exact paired controller outputs")
        if paths[0] in hashes and hashes[paths[0]] != artifact.sha256:
            raise ValueError("expected controller output differs from preflight candidate")
        hashes[paths[0]] = artifact.sha256
    return hashes
