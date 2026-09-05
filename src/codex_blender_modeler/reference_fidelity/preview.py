"""Isolated development previews for observation-bound candidates, never AQ promotion."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..autonomy.io import load_json, write_immutable_json
from ..autonomy.worker import autonomy_session_lock
from ..blender_artifacts import stable_json_digest
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance, sha256_file
from ..config import REPO_ROOT, get_settings
from ..material_manifest import load_material_manifest
from ..models import SceneSpec
from ..production.validation import ensure_contained_production_path
from ..qa.service import _validate_run_id, run_scene_spec_visual_qa_snapshot
from ..workspace import job_dir
from .models import (
    DevelopmentPreviewAttemptOutcomeV01,
    DevelopmentPreviewAttemptOutcomeV02,
    DevelopmentPreviewAttemptOutcomeV03,
    DevelopmentPreviewBudgetExtensionV01,
    DevelopmentPreviewBudgetExtensionV02,
    DevelopmentPreviewBudgetExtensionV03,
    DevelopmentPreviewBudgetExtensionV04,
    FidelityArtifact,
    FidelityEvaluationV01,
    UVSpatialPreservationV01,
    VisualFindingSetV01,
)
from .service import _geometry_dependencies, artifact_at, capture_render_evidence, read_artifact

BASE_PREVIEW_ATTEMPT_LIMIT = 6
EXTENDED_PREVIEW_ATTEMPT_LIMIT = 8
STRATEGY_SWITCH_PREVIEW_ATTEMPT_LIMIT = 10
STRATEGY_SWITCH_MAXIMUM_RESERVATIONS = 9
FIDELITY_CORRECTION_PREVIEW_ATTEMPT_LIMIT = 12
FIDELITY_CORRECTION_MAXIMUM_RESERVATIONS = 10
MATERIAL_REFINEMENT_PREVIEW_ATTEMPT_LIMIT = 14
MATERIAL_REFINEMENT_MAXIMUM_RESERVATIONS = 11


def _scope_digest(payload: dict) -> str:
    """Hash one self-describing development contract without its digest field."""

    return stable_json_digest(payload)


def _development_scene_source(root: Path, job_id: str, scene_path: Path) -> FidelityArtifact:
    """Validate and bind one contained development-only SceneSpec without writing state."""

    if list((root / "production/autonomy_v2").glob("*/plan.json")):
        raise PermissionError("AQ sessions must use their controller and frozen execution budgets")
    source_path = ensure_contained_production_path(root, root / scene_path, must_exist=True)
    if not source_path.relative_to(root).as_posix().startswith("fidelity/"):
        raise PermissionError("development preview accepts fidelity staging only")
    source = artifact_at(root, source_path)
    scene = SceneSpec.model_validate_json(read_artifact(root, source))
    if scene.job_id != job_id:
        raise ValueError("development preview SceneSpec belongs to another job")
    return source


def _development_source_dependencies(
    root: Path,
    source: FidelityArtifact,
) -> list[FidelityArtifact]:
    """Bind external geometry, texture manifest, and image bytes consumed by a SceneSpec."""

    scene = SceneSpec.model_validate_json(read_artifact(root, source))
    dependencies = {item.path: item for item in _geometry_dependencies(root, scene)}
    for material in scene.materials:
        manifest, manifest_path = load_material_manifest(material.model_dump(mode="json"), root)
        if manifest is None:
            continue
        if manifest_path is None:
            raise ValueError("loaded material manifest omitted its source path")
        manifest_artifact = artifact_at(root, manifest_path)
        dependencies[manifest_artifact.path] = manifest_artifact
        for channel in manifest["channels"].values():
            resolved = channel.get("resolved_path")
            if channel.get("source") != "image" or not resolved:
                continue
            channel_artifact = artifact_at(root, Path(str(resolved)))
            dependencies[channel_artifact.path] = channel_artifact
    return [dependencies[path] for path in sorted(dependencies)]


def _development_build_fingerprint(root: Path, job_id: str, source: FidelityArtifact) -> str:
    """Compute the same complete build fingerprint that the actual preview records."""

    provenance = collect_build_provenance(
        root,
        job_id,
        scene_spec_path=root / source.path,
    )
    return str(provenance["fingerprint"])


def _development_implementation_fingerprint() -> str:
    """Hash the complete Python runtime and locked project inputs used by a preview."""

    package_root = REPO_ROOT / "src/codex_blender_modeler"
    runtime_paths = list(package_root.rglob("*.py"))
    project_paths = [REPO_ROOT / name for name in ("cbm.toml", "pyproject.toml", "uv.lock")]
    paths = sorted([*runtime_paths, *project_paths], key=lambda item: item.as_posix())
    if not runtime_paths or any(not path.is_file() for path in paths):
        raise FileNotFoundError("development preview implementation inputs are incomplete")
    inventory = [
        {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in paths
    ]
    return stable_json_digest(
        {
            "scope": "complete_python_package_and_locked_project_inputs",
            "files": inventory,
        }
    )


def _development_blender_environment() -> tuple[str, str]:
    """Resolve, hash, and version-check the exact Blender binary used by a preview."""

    configured = get_settings().blender_bin
    candidate = Path(configured).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        resolved = candidate.resolve()
    else:
        discovered = shutil.which(configured)
        if discovered is None:
            raise FileNotFoundError(f"Blender executable not found: {configured}")
        resolved = Path(discovered).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Blender executable not found: {resolved}")
    result = subprocess.run(
        [str(resolved), "--version"],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.splitlines():
        raise RuntimeError("Blender version probe failed")
    first_line = result.stdout.splitlines()[0].strip()
    version = first_line.removeprefix("Blender ").strip()
    if version != "5.0.1":
        raise RuntimeError(f"development preview requires Blender 5.0.1, found {version}")
    return sha256_file(resolved), version


def _build_initial_preview_budget_extension(
    root: Path,
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
    extension_id: str,
    purpose: str,
    execution_request_basis: str,
) -> DevelopmentPreviewBudgetExtensionV01:
    """Build one exact first extension without publishing or implying approval."""

    _validate_run_id(primary_run_id)
    _validate_run_id(retry_run_id)
    source = _development_scene_source(root, job_id, scene_path)
    extension_path = root / "fidelity/preview_budget_extensions/0000.json"
    reservations = root / "fidelity/preview_reservations"
    attempts = sorted(reservations.glob("*.json"))
    expected = [f"{index:04d}.json" for index in range(len(attempts))]
    if [item.name for item in attempts] != expected:
        raise ValueError("development preview reservation ledger is not contiguous")
    if len(attempts) != BASE_PREVIEW_ATTEMPT_LIMIT:
        raise PermissionError("preview extension requires the exact exhausted six-attempt ledger")
    if extension_path.exists() or extension_path.parent.exists():
        raise FileExistsError("development preview budget extension already exists")
    payload = {
        "schema_version": "0.1.0",
        "contract_kind": "fidelity_development_preview_budget_extension",
        "extension_id": extension_id,
        "job_id": job_id,
        "source": source.model_dump(mode="json"),
        "primary_run_id": primary_run_id,
        "retry_run_id": retry_run_id,
        "purpose": purpose,
        "execution_request_basis": execution_request_basis,
        "base_attempt_limit": BASE_PREVIEW_ATTEMPT_LIMIT,
        "additional_attempt_limit": 2,
        "primary_attempts": 1,
        "maximum_identical_input_technical_retries": 1,
        "resets_existing_budget": False,
        "canonical_write_authority": False,
        "human_quality_disposition": "not_recorded",
        "package_acceptance_authority": False,
        "activation_authority": False,
        "campaign_evidence": False,
    }
    if purpose == "reference_fidelity_structural_correction":
        blender_sha256, blender_version = _development_blender_environment()
        payload["source_dependencies"] = [
            item.model_dump(mode="json")
            for item in _development_source_dependencies(root, source)
        ]
        payload["build_fingerprint"] = _development_build_fingerprint(root, job_id, source)
        payload["implementation_fingerprint"] = _development_implementation_fingerprint()
        payload["blender_executable_sha256"] = blender_sha256
        payload["blender_version"] = blender_version
    return DevelopmentPreviewBudgetExtensionV01.model_validate(
        {**payload, "scope_sha256": _scope_digest(payload)}
    )


def publish_development_preview_budget_extension(
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
) -> FidelityArtifact:
    """Publish one job-local +2 contract after the immutable six-attempt lab budget is spent."""

    root = job_dir(job_id).resolve()
    extension_path = root / "fidelity/preview_budget_extensions/0000.json"
    with autonomy_session_lock(root, root / "fidelity", owner_id="fidelity-preview-extension"):
        extension = _build_initial_preview_budget_extension(
            root,
            job_id,
            scene_path=scene_path,
            primary_run_id=primary_run_id,
            retry_run_id=retry_run_id,
            extension_id="directional-wood-material-correction-01",
            purpose="directional_wood_material_correction",
            execution_request_basis="current_task_explicit_bounded_execution",
        )
        write_immutable_json(
            root,
            extension_path,
            extension.model_dump(mode="json", exclude_none=True),
        )
    return artifact_at(root, extension_path)


def plan_development_preview_reference_fidelity_extension(
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
) -> DevelopmentPreviewBudgetExtensionV01:
    """Return an asset-neutral structural-preview scope without publishing authority."""

    root = job_dir(job_id).resolve()
    return _build_initial_preview_budget_extension(
        root,
        job_id,
        scene_path=scene_path,
        primary_run_id=primary_run_id,
        retry_run_id=retry_run_id,
        extension_id="reference-fidelity-structural-correction-01",
        purpose="reference_fidelity_structural_correction",
        execution_request_basis="exact_scope_sha256_user_approval",
    )


def publish_development_preview_reference_fidelity_extension(
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
    approved_scope_sha256: str,
) -> FidelityArtifact:
    """Publish an asset-neutral first extension only for its exact reviewed scope hash."""

    root = job_dir(job_id).resolve()
    extension_path = root / "fidelity/preview_budget_extensions/0000.json"
    with autonomy_session_lock(
        root, root / "fidelity", owner_id="fidelity-preview-reference-fidelity"
    ):
        extension = _build_initial_preview_budget_extension(
            root,
            job_id,
            scene_path=scene_path,
            primary_run_id=primary_run_id,
            retry_run_id=retry_run_id,
            extension_id="reference-fidelity-structural-correction-01",
            purpose="reference_fidelity_structural_correction",
            execution_request_basis="exact_scope_sha256_user_approval",
        )
        if extension.scope_sha256 != approved_scope_sha256:
            raise PermissionError("reference-fidelity extension lacks exact scope approval")
        write_immutable_json(
            root,
            extension_path,
            extension.model_dump(mode="json", exclude_none=True),
        )
    return artifact_at(root, extension_path)


def _load_preview_extensions(
    root: Path,
    job_id: str,
) -> tuple[
    tuple[
        DevelopmentPreviewBudgetExtensionV01
        | DevelopmentPreviewBudgetExtensionV02
        | DevelopmentPreviewBudgetExtensionV03
        | DevelopmentPreviewBudgetExtensionV04,
        FidelityArtifact,
    ],
    ...,
]:
    """Load the append-only extension chain and validate every predecessor binding."""

    directory = root / "fidelity/preview_budget_extensions"
    if not directory.exists():
        return ()
    directory = ensure_contained_production_path(root, directory, must_exist=True)
    entries = sorted(directory.iterdir(), key=lambda item: item.name)
    expected = [f"{index:04d}.json" for index in range(len(entries))]
    if (
        not entries
        or len(entries) > 4
        or [item.name for item in entries] != expected
        or any(not item.is_file() for item in entries)
    ):
        raise ValueError("development preview extension ledger is not a supported contiguous chain")
    first_artifact = artifact_at(root, entries[0])
    first = DevelopmentPreviewBudgetExtensionV01.model_validate_json(
        read_artifact(root, first_artifact)
    )
    if first.job_id != job_id:
        raise ValueError("development preview extension belongs to another job")
    if first.base_attempt_limit + first.additional_attempt_limit != (
        EXTENDED_PREVIEW_ATTEMPT_LIMIT
    ):
        raise ValueError("development preview extension has an unexpected cumulative limit")
    if (
        first.source_dependencies is not None
        and _development_source_dependencies(root, first.source)
        != first.source_dependencies
    ):
        raise ValueError("first extension source dependency closure differs")
    loaded: list[
        tuple[
            DevelopmentPreviewBudgetExtensionV01
            | DevelopmentPreviewBudgetExtensionV02
            | DevelopmentPreviewBudgetExtensionV03
            | DevelopmentPreviewBudgetExtensionV04,
            FidelityArtifact,
        ]
    ] = [(first, first_artifact)]
    if len(entries) >= 2:
        second_artifact = artifact_at(root, entries[1])
        second = DevelopmentPreviewBudgetExtensionV02.model_validate_json(
            read_artifact(root, second_artifact)
        )
        if second.job_id != job_id or second.prior_extension != first_artifact:
            raise ValueError("strategy-switch extension predecessor binding differs")
        if second.source == first.source:
            raise ValueError("strategy-switch extension must bind a changed exact source")
        if _development_source_dependencies(root, second.source) != second.source_dependencies:
            raise ValueError("strategy-switch extension source dependency closure differs")
        if {second.primary_run_id, second.retry_run_id} & {
            first.primary_run_id,
            first.retry_run_id,
        }:
            raise ValueError("strategy-switch extension reuses a prior run ID")
        prior_outcome, prior_outcome_artifact = _load_preview_outcome(
            root, BASE_PREVIEW_ATTEMPT_LIMIT
        )
        if (
            second.prior_primary_outcome != prior_outcome_artifact
            or prior_outcome.job_id != job_id
            or prior_outcome.run_id != first.primary_run_id
            or prior_outcome.source != first.source
            or prior_outcome.outcome != "completed"
            or second.cumulative_authorized_attempt_limit != STRATEGY_SWITCH_PREVIEW_ATTEMPT_LIMIT
            or second.maximum_total_reservations != STRATEGY_SWITCH_MAXIMUM_RESERVATIONS
        ):
            raise ValueError("strategy-switch extension prior completion differs")
        loaded.append((second, second_artifact))
    if len(entries) >= 3:
        second, second_artifact = loaded[1]
        if not isinstance(second, DevelopmentPreviewBudgetExtensionV02):
            raise ValueError("second development preview extension has an unsupported type")
        third_artifact = artifact_at(root, entries[2])
        third = DevelopmentPreviewBudgetExtensionV03.model_validate_json(
            read_artifact(root, third_artifact)
        )
        if third.job_id != job_id or third.prior_extension != second_artifact:
            raise ValueError("fidelity-correction extension predecessor binding differs")
        if third.source == second.source:
            raise ValueError("fidelity-correction extension must bind a changed exact source")
        if _development_source_dependencies(root, third.source) != third.source_dependencies:
            raise ValueError("fidelity-correction extension source dependency closure differs")
        prior_run_ids = {
            first.primary_run_id,
            first.retry_run_id,
            second.primary_run_id,
            second.retry_run_id,
        }
        if {third.primary_run_id, third.retry_run_id} & prior_run_ids:
            raise ValueError("fidelity-correction extension reuses a prior run ID")
        prior_outcome, prior_outcome_artifact = _load_preview_outcome(
            root, BASE_PREVIEW_ATTEMPT_LIMIT + 1
        )
        if (
            third.prior_primary_outcome != prior_outcome_artifact
            or prior_outcome.job_id != job_id
            or prior_outcome.run_id != second.primary_run_id
            or prior_outcome.source != second.source
            or prior_outcome.outcome != "completed"
            or third.cumulative_authorized_attempt_limit
            != FIDELITY_CORRECTION_PREVIEW_ATTEMPT_LIMIT
            or third.maximum_total_reservations != FIDELITY_CORRECTION_MAXIMUM_RESERVATIONS
        ):
            raise ValueError("fidelity-correction extension prior completion differs")
        loaded.append((third, third_artifact))
    if len(entries) == 4:
        third, third_artifact = loaded[2]
        if not isinstance(third, DevelopmentPreviewBudgetExtensionV03):
            raise ValueError("third development preview extension has an unsupported type")
        fourth_artifact = artifact_at(root, entries[3])
        fourth = DevelopmentPreviewBudgetExtensionV04.model_validate_json(
            read_artifact(root, fourth_artifact)
        )
        if fourth.job_id != job_id or fourth.prior_extension != third_artifact:
            raise ValueError("material-refinement extension predecessor binding differs")
        if fourth.source == third.source:
            raise ValueError("material-refinement extension must bind a changed exact source")
        if _development_source_dependencies(root, fourth.source) != fourth.source_dependencies:
            raise ValueError("material-refinement source dependency closure differs")
        prior_run_ids = {
            first.primary_run_id,
            first.retry_run_id,
            second.primary_run_id,
            second.retry_run_id,
            third.primary_run_id,
            third.retry_run_id,
        }
        if {fourth.primary_run_id, fourth.retry_run_id} & prior_run_ids:
            raise ValueError("material-refinement extension reuses a prior run ID")
        prior_outcome, prior_outcome_artifact = _load_preview_outcome(
            root, BASE_PREVIEW_ATTEMPT_LIMIT + 2
        )
        evidence = _load_material_refinement_evidence(
            root,
            job_id=job_id,
            prior_run_id=third.primary_run_id,
            prior_source=third.source,
            source=fourth.source,
        )
        if (
            fourth.prior_primary_outcome != prior_outcome_artifact
            or prior_outcome.job_id != job_id
            or prior_outcome.run_id != third.primary_run_id
            or prior_outcome.source != third.source
            or prior_outcome.outcome != "completed"
            or fourth.prior_visual_findings != evidence[0]
            or fourth.prior_evaluation != evidence[1]
            or fourth.prior_spatial_preservation != evidence[2]
            or fourth.source_spatial_preservation != evidence[3]
            or fourth.cumulative_authorized_attempt_limit
            != MATERIAL_REFINEMENT_PREVIEW_ATTEMPT_LIMIT
            or fourth.maximum_total_reservations != MATERIAL_REFINEMENT_MAXIMUM_RESERVATIONS
        ):
            raise ValueError("material-refinement extension prior completion differs")
        loaded.append((fourth, fourth_artifact))
    return tuple(loaded)


def _validate_first_extension_runtime(
    root: Path,
    job_id: str,
    extension: DevelopmentPreviewBudgetExtensionV01,
) -> None:
    """Verify generic first-extension implementation and Blender without changing legacy meaning."""

    if extension.purpose == "directional_wood_material_correction":
        return
    if (
        _development_build_fingerprint(root, job_id, extension.source)
        != extension.build_fingerprint
    ):
        raise ValueError("first extension build fingerprint differs")
    if _development_implementation_fingerprint() != extension.implementation_fingerprint:
        raise ValueError("first extension implementation fingerprint differs")
    blender_sha256, blender_version = _development_blender_environment()
    if (
        blender_sha256 != extension.blender_executable_sha256
        or blender_version != extension.blender_version
    ):
        raise ValueError("first extension Blender environment differs")


def _validate_extension_runtime(
    root: Path,
    job_id: str,
    extension: (
        DevelopmentPreviewBudgetExtensionV02
        | DevelopmentPreviewBudgetExtensionV03
        | DevelopmentPreviewBudgetExtensionV04
    ),
) -> None:
    """Require the exact approved source, implementation, and Blender only for an active run."""

    label = {
        1: "strategy-switch",
        2: "fidelity-correction",
        3: "material-refinement",
    }[extension.extension_index]
    if (
        _development_build_fingerprint(root, job_id, extension.source)
        != extension.build_fingerprint
    ):
        raise ValueError(f"{label} extension build fingerprint differs")
    if _development_implementation_fingerprint() != extension.implementation_fingerprint:
        raise ValueError(f"{label} implementation fingerprint differs")
    blender_sha256, blender_version = _development_blender_environment()
    if (
        blender_sha256 != extension.blender_executable_sha256
        or blender_version != extension.blender_version
    ):
        raise ValueError(f"{label} Blender environment differs")


def _load_preview_outcome(
    root: Path, index: int
) -> tuple[
    DevelopmentPreviewAttemptOutcomeV01
    | DevelopmentPreviewAttemptOutcomeV02
    | DevelopmentPreviewAttemptOutcomeV03,
    FidelityArtifact,
]:
    """Load and validate the immutable completion/failure sidecar for one reservation."""

    path = root / "fidelity/preview_outcomes" / f"{index:04d}.json"
    artifact = artifact_at(root, path)
    payload = load_json(root, path)
    version = payload.get("schema_version")
    if version == "0.1.0":
        outcome = DevelopmentPreviewAttemptOutcomeV01.model_validate(payload)
    elif version == "0.2.0":
        outcome = DevelopmentPreviewAttemptOutcomeV02.model_validate(payload)
    elif version == "0.3.0":
        outcome = DevelopmentPreviewAttemptOutcomeV03.model_validate(payload)
    else:
        raise ValueError("development preview outcome has an unsupported schema version")
    if outcome.attempt_index != index:
        raise ValueError("development preview outcome index differs from its ledger position")
    return outcome, artifact


def _build_strategy_switch_extension(
    root: Path,
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
) -> DevelopmentPreviewBudgetExtensionV02:
    """Build the exact second extension only after the first primary completed."""

    _validate_run_id(primary_run_id)
    _validate_run_id(retry_run_id)
    source = _development_scene_source(root, job_id, scene_path)
    extensions = _load_preview_extensions(root, job_id)
    if len(extensions) != 1:
        if len(extensions) > 1:
            raise FileExistsError("strategy-switch preview extension already exists")
        raise PermissionError("strategy-switch extension requires the first exact extension")
    first, first_artifact = extensions[0]
    if not isinstance(first, DevelopmentPreviewBudgetExtensionV01):
        raise ValueError("first development preview extension has an unsupported type")
    reservations = root / "fidelity/preview_reservations"
    attempts = sorted(reservations.glob("*.json"))
    expected = [f"{index:04d}.json" for index in range(len(attempts))]
    if [item.name for item in attempts] != expected:
        raise ValueError("development preview reservation ledger is not contiguous")
    if len(attempts) != BASE_PREVIEW_ATTEMPT_LIMIT + 1:
        raise PermissionError(
            "strategy-switch extension requires exactly one completed first-extension primary"
        )
    prior_outcome, prior_outcome_artifact = _load_preview_outcome(root, BASE_PREVIEW_ATTEMPT_LIMIT)
    if (
        prior_outcome.job_id != job_id
        or prior_outcome.run_id != first.primary_run_id
        or prior_outcome.source != first.source
        or prior_outcome.outcome != "completed"
    ):
        raise PermissionError(
            "strategy switch requires the exact first-extension primary completion"
        )
    if source == first.source:
        raise ValueError("strategy switch must bind a changed exact SceneSpec")
    if {primary_run_id, retry_run_id} & {first.primary_run_id, first.retry_run_id}:
        raise ValueError("strategy switch must use new run IDs")
    source_dependencies = _development_source_dependencies(root, source)
    build_fingerprint = _development_build_fingerprint(root, job_id, source)
    implementation_fingerprint = _development_implementation_fingerprint()
    blender_executable_sha256, blender_version = _development_blender_environment()
    payload = {
        "schema_version": "0.2.0",
        "contract_kind": "fidelity_development_preview_budget_extension",
        "extension_id": "directional-wood-material-strategy-switch-02",
        "extension_index": 1,
        "job_id": job_id,
        "prior_extension": first_artifact.model_dump(mode="json"),
        "prior_primary_outcome": prior_outcome_artifact.model_dump(mode="json"),
        "source": source.model_dump(mode="json"),
        "source_dependencies": [item.model_dump(mode="json") for item in source_dependencies],
        "build_fingerprint": build_fingerprint,
        "implementation_fingerprint": implementation_fingerprint,
        "blender_executable_sha256": blender_executable_sha256,
        "blender_version": blender_version,
        "primary_run_id": primary_run_id,
        "retry_run_id": retry_run_id,
        "purpose": "material_strategy_switch",
        "execution_request_basis": "exact_scope_sha256_user_approval",
        "prior_authorized_attempt_limit": EXTENDED_PREVIEW_ATTEMPT_LIMIT,
        "prior_reserved_attempt_count": BASE_PREVIEW_ATTEMPT_LIMIT + 1,
        "additional_attempt_limit": 2,
        "cumulative_authorized_attempt_limit": STRATEGY_SWITCH_PREVIEW_ATTEMPT_LIMIT,
        "closed_prior_retry_slots": 1,
        "maximum_total_reservations": STRATEGY_SWITCH_MAXIMUM_RESERVATIONS,
        "reclaims_closed_retry_slot": False,
        "primary_attempts": 1,
        "maximum_identical_input_technical_retries": 1,
        "resets_existing_budget": False,
        "canonical_write_authority": False,
        "human_quality_disposition": "not_recorded",
        "package_acceptance_authority": False,
        "activation_authority": False,
        "campaign_evidence": False,
    }
    return DevelopmentPreviewBudgetExtensionV02.model_validate(
        {**payload, "scope_sha256": _scope_digest(payload)}
    )


def plan_development_preview_strategy_switch_extension(
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
) -> DevelopmentPreviewBudgetExtensionV02:
    """Return a deterministic exact scope for user review without publishing authority."""

    root = job_dir(job_id).resolve()
    return _build_strategy_switch_extension(
        root,
        job_id,
        scene_path=scene_path,
        primary_run_id=primary_run_id,
        retry_run_id=retry_run_id,
    )


def publish_development_preview_strategy_switch_extension(
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
    approved_scope_sha256: str,
) -> FidelityArtifact:
    """Publish the reviewed second extension only when its exact scope hash still matches."""

    root = job_dir(job_id).resolve()
    extension_path = root / "fidelity/preview_budget_extensions/0001.json"
    with autonomy_session_lock(
        root, root / "fidelity", owner_id="fidelity-preview-strategy-switch"
    ):
        extension = _build_strategy_switch_extension(
            root,
            job_id,
            scene_path=scene_path,
            primary_run_id=primary_run_id,
            retry_run_id=retry_run_id,
        )
        if extension.scope_sha256 != approved_scope_sha256:
            raise PermissionError("strategy-switch extension lacks exact scope approval")
        write_immutable_json(root, extension_path, extension.model_dump(mode="json"))
    return artifact_at(root, extension_path)


def _build_fidelity_correction_extension(
    root: Path,
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
) -> DevelopmentPreviewBudgetExtensionV03:
    """Build a third exact extension after the completed strategy-switch primary."""

    _validate_run_id(primary_run_id)
    _validate_run_id(retry_run_id)
    source = _development_scene_source(root, job_id, scene_path)
    extensions = _load_preview_extensions(root, job_id)
    if len(extensions) != 2:
        if len(extensions) > 2:
            raise FileExistsError("fidelity-correction preview extension already exists")
        raise PermissionError("fidelity-correction extension requires the first two extensions")
    first, _first_artifact = extensions[0]
    second, second_artifact = extensions[1]
    if not isinstance(first, DevelopmentPreviewBudgetExtensionV01) or not isinstance(
        second, DevelopmentPreviewBudgetExtensionV02
    ):
        raise ValueError("development preview extension chain has unsupported types")
    reservations = root / "fidelity/preview_reservations"
    attempts = sorted(reservations.glob("*.json"))
    expected = [f"{index:04d}.json" for index in range(len(attempts))]
    if [item.name for item in attempts] != expected:
        raise ValueError("development preview reservation ledger is not contiguous")
    if len(attempts) != BASE_PREVIEW_ATTEMPT_LIMIT + 2:
        raise PermissionError(
            "fidelity-correction extension requires exactly one completed strategy primary"
        )
    prior_outcome, prior_outcome_artifact = _load_preview_outcome(
        root, BASE_PREVIEW_ATTEMPT_LIMIT + 1
    )
    if (
        prior_outcome.job_id != job_id
        or prior_outcome.run_id != second.primary_run_id
        or prior_outcome.source != second.source
        or prior_outcome.outcome != "completed"
    ):
        raise PermissionError(
            "fidelity correction requires the exact strategy-switch primary completion"
        )
    if source == second.source:
        raise ValueError("fidelity correction must bind a changed exact SceneSpec")
    prior_run_ids = {
        first.primary_run_id,
        first.retry_run_id,
        second.primary_run_id,
        second.retry_run_id,
    }
    if {primary_run_id, retry_run_id} & prior_run_ids:
        raise ValueError("fidelity correction must use new run IDs")
    source_dependencies = _development_source_dependencies(root, source)
    build_fingerprint = _development_build_fingerprint(root, job_id, source)
    implementation_fingerprint = _development_implementation_fingerprint()
    blender_executable_sha256, blender_version = _development_blender_environment()
    payload = {
        "schema_version": "0.3.0",
        "contract_kind": "fidelity_development_preview_budget_extension",
        "extension_id": "structural-material-fidelity-correction-03",
        "extension_index": 2,
        "job_id": job_id,
        "prior_extension": second_artifact.model_dump(mode="json"),
        "prior_primary_outcome": prior_outcome_artifact.model_dump(mode="json"),
        "source": source.model_dump(mode="json"),
        "source_dependencies": [item.model_dump(mode="json") for item in source_dependencies],
        "build_fingerprint": build_fingerprint,
        "implementation_fingerprint": implementation_fingerprint,
        "blender_executable_sha256": blender_executable_sha256,
        "blender_version": blender_version,
        "primary_run_id": primary_run_id,
        "retry_run_id": retry_run_id,
        "purpose": "structural_material_correction",
        "execution_request_basis": "exact_scope_sha256_user_approval",
        "prior_authorized_attempt_limit": STRATEGY_SWITCH_PREVIEW_ATTEMPT_LIMIT,
        "prior_reserved_attempt_count": BASE_PREVIEW_ATTEMPT_LIMIT + 2,
        "additional_attempt_limit": 2,
        "cumulative_authorized_attempt_limit": FIDELITY_CORRECTION_PREVIEW_ATTEMPT_LIMIT,
        "closed_prior_retry_slots": 2,
        "maximum_total_reservations": FIDELITY_CORRECTION_MAXIMUM_RESERVATIONS,
        "reclaims_closed_retry_slot": False,
        "primary_attempts": 1,
        "maximum_identical_input_technical_retries": 1,
        "resets_existing_budget": False,
        "canonical_write_authority": False,
        "human_quality_disposition": "not_recorded",
        "package_acceptance_authority": False,
        "activation_authority": False,
        "campaign_evidence": False,
    }
    return DevelopmentPreviewBudgetExtensionV03.model_validate(
        {**payload, "scope_sha256": _scope_digest(payload)}
    )


def plan_development_preview_fidelity_correction_extension(
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
) -> DevelopmentPreviewBudgetExtensionV03:
    """Return an exact structural/material correction scope without publishing authority."""

    root = job_dir(job_id).resolve()
    return _build_fidelity_correction_extension(
        root,
        job_id,
        scene_path=scene_path,
        primary_run_id=primary_run_id,
        retry_run_id=retry_run_id,
    )


def publish_development_preview_fidelity_correction_extension(
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
    approved_scope_sha256: str,
) -> FidelityArtifact:
    """Publish the third extension only when its current exact scope was explicitly approved."""

    root = job_dir(job_id).resolve()
    extension_path = root / "fidelity/preview_budget_extensions/0002.json"
    with autonomy_session_lock(
        root, root / "fidelity", owner_id="fidelity-preview-structural-material-correction"
    ):
        extension = _build_fidelity_correction_extension(
            root,
            job_id,
            scene_path=scene_path,
            primary_run_id=primary_run_id,
            retry_run_id=retry_run_id,
        )
        if extension.scope_sha256 != approved_scope_sha256:
            raise PermissionError("fidelity-correction extension lacks exact scope approval")
        write_immutable_json(root, extension_path, extension.model_dump(mode="json"))
    return artifact_at(root, extension_path)


def _load_material_refinement_evidence(
    root: Path,
    *,
    job_id: str,
    prior_run_id: str,
    prior_source: FidelityArtifact,
    source: FidelityArtifact,
) -> tuple[FidelityArtifact, FidelityArtifact, FidelityArtifact, FidelityArtifact]:
    """Validate the exact material finding and two geometry-preservation audits."""

    review_root = root / "fidelity/inspection" / prior_run_id
    findings_artifact = artifact_at(root, review_root / "visual_findings.json")
    evaluation_artifact = artifact_at(root, review_root / "evaluation.json")
    prior_spatial_artifact = artifact_at(
        root,
        (root / prior_source.path).parent / "uv_spatial_preservation.json",
    )
    source_spatial_artifact = artifact_at(
        root,
        (root / source.path).parent / "uv_spatial_preservation.json",
    )
    findings = VisualFindingSetV01.model_validate_json(read_artifact(root, findings_artifact))
    evaluation = FidelityEvaluationV01.model_validate_json(read_artifact(root, evaluation_artifact))
    prior_spatial = UVSpatialPreservationV01.model_validate_json(
        read_artifact(root, prior_spatial_artifact)
    )
    source_spatial = UVSpatialPreservationV01.model_validate_json(
        read_artifact(root, source_spatial_artifact)
    )
    if (
        findings.job_id != job_id
        or findings.review_id != prior_run_id
        or findings.evidence.scene_spec.sha256 != prior_source.sha256
        or evaluation.visual_review != findings_artifact
        or evaluation.outcome != "needs_revision"
        or evaluation.next_action != "material_revision"
        or evaluation.human_quality_disposition != "not_recorded"
        or not any(
            item.route == "material_revision" and item.severity in {"major", "critical"}
            for item in evaluation.findings
        )
    ):
        raise PermissionError(
            "material refinement requires the exact unresolved nonhuman material finding"
        )
    if (
        prior_spatial.job_id != job_id
        or source_spatial.job_id != job_id
        or prior_spatial.candidate_scene != prior_source
        or source_spatial.candidate_scene != source
        or prior_spatial.source_scene != source_spatial.source_scene
        or prior_spatial.source_mesh != source_spatial.source_mesh
    ):
        raise ValueError("material-refinement spatial preservation binding differs")
    for artifact in (
        prior_spatial.source_scene,
        prior_spatial.source_mesh,
        prior_spatial.candidate_mesh,
        source_spatial.candidate_mesh,
    ):
        read_artifact(root, artifact)
    prior_scene = SceneSpec.model_validate_json(read_artifact(root, prior_source))
    source_scene = SceneSpec.model_validate_json(read_artifact(root, source))
    prior_material_ids = [item.id for item in prior_scene.materials]
    source_material_ids = [item.id for item in source_scene.materials]
    prior_assignments = [(item.id, item.material_id) for item in prior_scene.objects]
    source_assignments = [(item.id, item.material_id) for item in source_scene.objects]
    if prior_material_ids != source_material_ids or prior_assignments != source_assignments:
        raise PermissionError(
            "material-refinement source changed stable objects or material assignments"
        )
    return (
        findings_artifact,
        evaluation_artifact,
        prior_spatial_artifact,
        source_spatial_artifact,
    )


def _build_material_refinement_extension(
    root: Path,
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
) -> DevelopmentPreviewBudgetExtensionV04:
    """Build a fourth exact extension from a completed material-revision finding."""

    _validate_run_id(primary_run_id)
    _validate_run_id(retry_run_id)
    source = _development_scene_source(root, job_id, scene_path)
    extensions = _load_preview_extensions(root, job_id)
    if len(extensions) != 3:
        if len(extensions) > 3:
            raise FileExistsError("material-refinement preview extension already exists")
        raise PermissionError("material-refinement extension requires the first three extensions")
    first, _first_artifact = extensions[0]
    second, _second_artifact = extensions[1]
    third, third_artifact = extensions[2]
    if (
        not isinstance(first, DevelopmentPreviewBudgetExtensionV01)
        or not isinstance(second, DevelopmentPreviewBudgetExtensionV02)
        or not isinstance(third, DevelopmentPreviewBudgetExtensionV03)
    ):
        raise ValueError("development preview extension chain has unsupported types")
    reservations = root / "fidelity/preview_reservations"
    attempts = sorted(reservations.glob("*.json"))
    expected = [f"{index:04d}.json" for index in range(len(attempts))]
    if [item.name for item in attempts] != expected:
        raise ValueError("development preview reservation ledger is not contiguous")
    if len(attempts) != BASE_PREVIEW_ATTEMPT_LIMIT + 3:
        raise PermissionError(
            "material-refinement extension requires exactly one completed correction primary"
        )
    prior_outcome, prior_outcome_artifact = _load_preview_outcome(
        root, BASE_PREVIEW_ATTEMPT_LIMIT + 2
    )
    if (
        prior_outcome.job_id != job_id
        or prior_outcome.run_id != third.primary_run_id
        or prior_outcome.source != third.source
        or prior_outcome.outcome != "completed"
    ):
        raise PermissionError(
            "material refinement requires the exact fidelity-correction primary completion"
        )
    if source == third.source:
        raise ValueError("material refinement must bind a changed exact SceneSpec")
    prior_run_ids = {
        first.primary_run_id,
        first.retry_run_id,
        second.primary_run_id,
        second.retry_run_id,
        third.primary_run_id,
        third.retry_run_id,
    }
    if {primary_run_id, retry_run_id} & prior_run_ids:
        raise ValueError("material refinement must use new run IDs")
    (
        findings_artifact,
        evaluation_artifact,
        prior_spatial_artifact,
        source_spatial_artifact,
    ) = _load_material_refinement_evidence(
        root,
        job_id=job_id,
        prior_run_id=third.primary_run_id,
        prior_source=third.source,
        source=source,
    )
    source_dependencies = _development_source_dependencies(root, source)
    build_fingerprint = _development_build_fingerprint(root, job_id, source)
    implementation_fingerprint = _development_implementation_fingerprint()
    blender_executable_sha256, blender_version = _development_blender_environment()
    payload = {
        "schema_version": "0.4.0",
        "contract_kind": "fidelity_development_preview_budget_extension",
        "extension_id": "material-fidelity-refinement-04",
        "extension_index": 3,
        "job_id": job_id,
        "prior_extension": third_artifact.model_dump(mode="json"),
        "prior_primary_outcome": prior_outcome_artifact.model_dump(mode="json"),
        "prior_visual_findings": findings_artifact.model_dump(mode="json"),
        "prior_evaluation": evaluation_artifact.model_dump(mode="json"),
        "prior_spatial_preservation": prior_spatial_artifact.model_dump(mode="json"),
        "source": source.model_dump(mode="json"),
        "source_dependencies": [item.model_dump(mode="json") for item in source_dependencies],
        "source_spatial_preservation": source_spatial_artifact.model_dump(mode="json"),
        "revision_route": "material_revision",
        "build_fingerprint": build_fingerprint,
        "implementation_fingerprint": implementation_fingerprint,
        "blender_executable_sha256": blender_executable_sha256,
        "blender_version": blender_version,
        "primary_run_id": primary_run_id,
        "retry_run_id": retry_run_id,
        "purpose": "material_fidelity_refinement",
        "execution_request_basis": "exact_scope_sha256_user_approval",
        "prior_authorized_attempt_limit": FIDELITY_CORRECTION_PREVIEW_ATTEMPT_LIMIT,
        "prior_reserved_attempt_count": BASE_PREVIEW_ATTEMPT_LIMIT + 3,
        "additional_attempt_limit": 2,
        "cumulative_authorized_attempt_limit": MATERIAL_REFINEMENT_PREVIEW_ATTEMPT_LIMIT,
        "closed_prior_retry_slots": 3,
        "maximum_total_reservations": MATERIAL_REFINEMENT_MAXIMUM_RESERVATIONS,
        "reclaims_closed_retry_slot": False,
        "primary_attempts": 1,
        "maximum_identical_input_technical_retries": 1,
        "resets_existing_budget": False,
        "canonical_write_authority": False,
        "human_quality_disposition": "not_recorded",
        "package_acceptance_authority": False,
        "activation_authority": False,
        "campaign_evidence": False,
    }
    return DevelopmentPreviewBudgetExtensionV04.model_validate(
        {**payload, "scope_sha256": _scope_digest(payload)}
    )


def plan_development_preview_material_refinement_extension(
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
) -> DevelopmentPreviewBudgetExtensionV04:
    """Return an exact material-refinement scope without publishing authority."""

    root = job_dir(job_id).resolve()
    return _build_material_refinement_extension(
        root,
        job_id,
        scene_path=scene_path,
        primary_run_id=primary_run_id,
        retry_run_id=retry_run_id,
    )


def publish_development_preview_material_refinement_extension(
    job_id: str,
    *,
    scene_path: Path,
    primary_run_id: str,
    retry_run_id: str,
    approved_scope_sha256: str,
) -> FidelityArtifact:
    """Publish the fourth extension only after exact scope-hash user approval."""

    root = job_dir(job_id).resolve()
    extension_path = root / "fidelity/preview_budget_extensions/0003.json"
    with autonomy_session_lock(
        root, root / "fidelity", owner_id="fidelity-preview-material-refinement"
    ):
        extension = _build_material_refinement_extension(
            root,
            job_id,
            scene_path=scene_path,
            primary_run_id=primary_run_id,
            retry_run_id=retry_run_id,
        )
        if extension.scope_sha256 != approved_scope_sha256:
            raise PermissionError("material-refinement extension lacks exact scope approval")
        write_immutable_json(root, extension_path, extension.model_dump(mode="json"))
    return artifact_at(root, extension_path)


def _extended_attempt_binding(
    root: Path,
    job_id: str,
    source: FidelityArtifact,
    run_id: str,
    attempt_count: int,
) -> tuple[FidelityArtifact | None, str]:
    """Authorize one base or exact extension slot without reclaiming a closed retry."""

    loaded = _load_preview_extensions(root, job_id)
    if attempt_count < BASE_PREVIEW_ATTEMPT_LIMIT:
        if loaded:
            raise PermissionError("preview extension cannot reset or overlap the base budget")
        return None, "base"
    if not loaded:
        raise PermissionError("development preview budget exhausted; no automatic reset")
    first, first_artifact = loaded[0]
    if not isinstance(first, DevelopmentPreviewBudgetExtensionV01):
        raise ValueError("first development preview extension has an unsupported type")
    if attempt_count == BASE_PREVIEW_ATTEMPT_LIMIT:
        if source != first.source:
            raise PermissionError("extended preview source differs from its exact contract")
        if run_id != first.primary_run_id:
            raise PermissionError("extended preview must use its exact primary run ID")
        _validate_first_extension_runtime(root, job_id, first)
        return first_artifact, "bounded_primary"
    if attempt_count == BASE_PREVIEW_ATTEMPT_LIMIT + 1:
        if len(loaded) >= 2:
            second, second_artifact = loaded[1]
            if not isinstance(second, DevelopmentPreviewBudgetExtensionV02):
                raise ValueError("second development preview extension has an unsupported type")
            if source != second.source:
                raise PermissionError(
                    "strategy-switch preview source differs from its exact contract"
                )
            if run_id != second.primary_run_id:
                raise PermissionError("strategy-switch preview must use its exact primary run ID")
            _validate_extension_runtime(root, job_id, second)
            return second_artifact, "strategy_switch_primary"
        if source != first.source:
            raise PermissionError("extended preview source differs from its exact contract")
        if run_id != first.retry_run_id:
            raise PermissionError("extended preview must use its exact technical-retry run ID")
        _validate_first_extension_runtime(root, job_id, first)
        primary = load_json(
            root,
            root / "fidelity/preview_reservations" / f"{BASE_PREVIEW_ATTEMPT_LIMIT:04d}.json",
        )
        if (
            primary.get("run_id") != first.primary_run_id
            or primary.get("source") != first.source.model_dump(mode="json")
            or primary.get("extension") != first_artifact.model_dump(mode="json")
            or primary.get("attempt_role") != "bounded_primary"
        ):
            raise ValueError("primary extended reservation differs from its exact contract")
        outcome, _ = _load_preview_outcome(root, BASE_PREVIEW_ATTEMPT_LIMIT)
        if (
            outcome.job_id != job_id
            or outcome.run_id != first.primary_run_id
            or outcome.source != first.source
            or outcome.outcome != "technical_failure"
        ):
            raise PermissionError("retry is allowed only after the exact primary technical failure")
        return first_artifact, "identical_input_technical_retry"
    if attempt_count == BASE_PREVIEW_ATTEMPT_LIMIT + 2:
        if len(loaded) == 3:
            third, third_artifact = loaded[2]
            if not isinstance(third, DevelopmentPreviewBudgetExtensionV03):
                raise ValueError("third development preview extension has an unsupported type")
            if source != third.source:
                raise PermissionError(
                    "fidelity-correction preview source differs from its exact contract"
                )
            if run_id != third.primary_run_id:
                raise PermissionError(
                    "fidelity-correction preview must use its exact primary run ID"
                )
            _validate_extension_runtime(root, job_id, third)
            return third_artifact, "fidelity_correction_primary"
        if len(loaded) != 2:
            raise PermissionError("development preview cumulative extension budget exhausted")
        second, second_artifact = loaded[1]
        if not isinstance(second, DevelopmentPreviewBudgetExtensionV02):
            raise ValueError("second development preview extension has an unsupported type")
        if source != second.source:
            raise PermissionError("strategy-switch preview source differs from its exact contract")
        if run_id != second.retry_run_id:
            raise PermissionError(
                "strategy-switch preview must use its exact technical-retry run ID"
            )
        _validate_extension_runtime(root, job_id, second)
        primary = load_json(
            root,
            root / "fidelity/preview_reservations" / f"{BASE_PREVIEW_ATTEMPT_LIMIT + 1:04d}.json",
        )
        if (
            primary.get("run_id") != second.primary_run_id
            or primary.get("source") != second.source.model_dump(mode="json")
            or primary.get("extension") != second_artifact.model_dump(mode="json")
            or primary.get("attempt_role") != "strategy_switch_primary"
        ):
            raise ValueError("strategy-switch primary reservation differs from its exact contract")
        outcome, _ = _load_preview_outcome(root, BASE_PREVIEW_ATTEMPT_LIMIT + 1)
        if (
            outcome.job_id != job_id
            or outcome.run_id != second.primary_run_id
            or outcome.source != second.source
            or outcome.outcome != "technical_failure"
        ):
            raise PermissionError(
                "strategy-switch retry is allowed only after its exact primary technical failure"
            )
        return second_artifact, "strategy_switch_identical_input_technical_retry"
    if attempt_count == BASE_PREVIEW_ATTEMPT_LIMIT + 3:
        if len(loaded) == 4:
            fourth, fourth_artifact = loaded[3]
            if not isinstance(fourth, DevelopmentPreviewBudgetExtensionV04):
                raise ValueError("fourth development preview extension has an unsupported type")
            if source != fourth.source:
                raise PermissionError(
                    "material-refinement preview source differs from its exact contract"
                )
            if run_id != fourth.primary_run_id:
                raise PermissionError(
                    "material-refinement preview must use its exact primary run ID"
                )
            _validate_extension_runtime(root, job_id, fourth)
            return fourth_artifact, "material_refinement_primary"
        if len(loaded) != 3:
            raise PermissionError("development preview cumulative extension budget exhausted")
        third, third_artifact = loaded[2]
        if not isinstance(third, DevelopmentPreviewBudgetExtensionV03):
            raise ValueError("third development preview extension has an unsupported type")
        if source != third.source:
            raise PermissionError(
                "fidelity-correction preview source differs from its exact contract"
            )
        if run_id != third.retry_run_id:
            raise PermissionError(
                "fidelity-correction preview must use its exact technical-retry run ID"
            )
        _validate_extension_runtime(root, job_id, third)
        primary = load_json(
            root,
            root / "fidelity/preview_reservations" / f"{BASE_PREVIEW_ATTEMPT_LIMIT + 2:04d}.json",
        )
        if (
            primary.get("run_id") != third.primary_run_id
            or primary.get("source") != third.source.model_dump(mode="json")
            or primary.get("extension") != third_artifact.model_dump(mode="json")
            or primary.get("attempt_role") != "fidelity_correction_primary"
        ):
            raise ValueError(
                "fidelity-correction primary reservation differs from its exact contract"
            )
        outcome, _ = _load_preview_outcome(root, BASE_PREVIEW_ATTEMPT_LIMIT + 2)
        if (
            outcome.job_id != job_id
            or outcome.run_id != third.primary_run_id
            or outcome.source != third.source
            or outcome.outcome != "technical_failure"
        ):
            raise PermissionError(
                "fidelity-correction retry is allowed only after its exact primary "
                "technical failure"
            )
        return third_artifact, "fidelity_correction_identical_input_technical_retry"
    if attempt_count == BASE_PREVIEW_ATTEMPT_LIMIT + 4:
        if len(loaded) != 4:
            raise PermissionError("development preview cumulative extension budget exhausted")
        fourth, fourth_artifact = loaded[3]
        if not isinstance(fourth, DevelopmentPreviewBudgetExtensionV04):
            raise ValueError("fourth development preview extension has an unsupported type")
        if source != fourth.source:
            raise PermissionError(
                "material-refinement preview source differs from its exact contract"
            )
        if run_id != fourth.retry_run_id:
            raise PermissionError(
                "material-refinement preview must use its exact technical-retry run ID"
            )
        _validate_extension_runtime(root, job_id, fourth)
        primary = load_json(
            root,
            root / "fidelity/preview_reservations" / f"{BASE_PREVIEW_ATTEMPT_LIMIT + 3:04d}.json",
        )
        if (
            primary.get("run_id") != fourth.primary_run_id
            or primary.get("source") != fourth.source.model_dump(mode="json")
            or primary.get("extension") != fourth_artifact.model_dump(mode="json")
            or primary.get("attempt_role") != "material_refinement_primary"
        ):
            raise ValueError(
                "material-refinement primary reservation differs from its exact contract"
            )
        outcome, _ = _load_preview_outcome(root, BASE_PREVIEW_ATTEMPT_LIMIT + 3)
        if (
            outcome.job_id != job_id
            or outcome.run_id != fourth.primary_run_id
            or outcome.source != fourth.source
            or outcome.outcome != "technical_failure"
        ):
            raise PermissionError(
                "material-refinement retry is allowed only after its exact primary "
                "technical failure"
            )
        return fourth_artifact, "material_refinement_identical_input_technical_retry"
    raise PermissionError("development preview cumulative extension budget exhausted")


def _validate_extension_build_fingerprint(
    root: Path,
    job_id: str,
    attempt_index: int,
    actual_fingerprint: str,
) -> None:
    """Reject a completed exact-extension build if its runtime or dependency closure drifted."""

    if attempt_index < BASE_PREVIEW_ATTEMPT_LIMIT + 1:
        return
    extensions = _load_preview_extensions(root, job_id)
    extension: (
        DevelopmentPreviewBudgetExtensionV02
        | DevelopmentPreviewBudgetExtensionV03
        | DevelopmentPreviewBudgetExtensionV04
    )
    label: str
    if attempt_index == BASE_PREVIEW_ATTEMPT_LIMIT + 1:
        extension = extensions[1][0]
        label = "strategy-switch"
    elif attempt_index == BASE_PREVIEW_ATTEMPT_LIMIT + 2 and len(extensions) == 2:
        extension = extensions[1][0]
        label = "strategy-switch"
    elif (
        attempt_index
        in {
            BASE_PREVIEW_ATTEMPT_LIMIT + 2,
            BASE_PREVIEW_ATTEMPT_LIMIT + 3,
        }
        and len(extensions) == 3
    ):
        extension = extensions[2][0]
        label = "fidelity-correction"
    elif attempt_index == BASE_PREVIEW_ATTEMPT_LIMIT + 3 and len(extensions) == 4:
        extension = extensions[3][0]
        label = "material-refinement"
    elif attempt_index == BASE_PREVIEW_ATTEMPT_LIMIT + 4 and len(extensions) == 4:
        extension = extensions[3][0]
        label = "material-refinement"
    else:
        raise ValueError("preview attempt has no matching exact extension")
    if not isinstance(
        extension,
        (
            DevelopmentPreviewBudgetExtensionV02,
            DevelopmentPreviewBudgetExtensionV03,
            DevelopmentPreviewBudgetExtensionV04,
        ),
    ):
        raise ValueError("development preview extension has an unsupported type")
    _validate_extension_runtime(root, job_id, extension)
    if actual_fingerprint != extension.build_fingerprint:
        raise ValueError(f"{label} rendered build fingerprint differs from approved scope")


def _reserve_preview_attempt(
    root: Path,
    job_id: str,
    source: FidelityArtifact,
    run_id: str,
) -> int:
    """Append one contiguous reservation after enforcing the base and extension ledgers."""

    reservations = root / "fidelity/preview_reservations"
    output = root / "fidelity/previews" / run_id
    qa_dir = root / "qa/runs" / run_id
    with autonomy_session_lock(root, root / "fidelity", owner_id="fidelity-preview-reservation"):
        attempts = sorted(reservations.glob("*.json"))
        expected = [f"{index:04d}.json" for index in range(len(attempts))]
        if [item.name for item in attempts] != expected:
            raise ValueError("development preview reservation ledger is not contiguous")
        extension, role = _extended_attempt_binding(root, job_id, source, run_id, len(attempts))
        if output.exists() or qa_dir.exists():
            raise FileExistsError("preview already attempted; preserve its evidence")
        payload = {
            "schema_version": "0.1.0",
            "contract_kind": "fidelity_development_preview_reservation",
            "attempt_index": len(attempts),
            "attempt_role": role,
            "job_id": job_id,
            "run_id": run_id,
            "source": source.model_dump(mode="json"),
            "builds": 1,
            "seven_pass_qa_runs": 1,
            "not_aq_campaign_evidence": True,
            "canonical_write": False,
            "human_quality_disposition": "not_recorded",
        }
        if extension is not None:
            payload["extension"] = extension.model_dump(mode="json")
        write_immutable_json(root, reservations / f"{len(attempts):04d}.json", payload)
        output.mkdir(parents=True, exist_ok=False)
        return len(attempts)


def _record_preview_outcome(
    root: Path,
    *,
    job_id: str,
    attempt_index: int,
    run_id: str,
    source: FidelityArtifact,
    result: FidelityArtifact | None = None,
    error: Exception | None = None,
) -> FidelityArtifact:
    """Publish one self-digested attempt outcome without converting it into quality authority."""

    if (result is None) == (error is None):
        raise ValueError("preview outcome requires exactly one result or technical error")
    payload = {
        "schema_version": "0.1.0",
        "contract_kind": "fidelity_development_preview_attempt_outcome",
        "job_id": job_id,
        "attempt_index": attempt_index,
        "run_id": run_id,
        "source": source.model_dump(mode="json"),
        "outcome": "completed" if result is not None else "technical_failure",
        "result": result.model_dump(mode="json") if result is not None else None,
        "error_type": None if error is None else type(error).__name__[:128],
        "error_message": (
            None if error is None else (str(error) or "unspecified technical failure")[:2048]
        ),
        "canonical_write_authority": False,
        "human_quality_disposition": "not_recorded",
        "activation_authority": False,
    }
    if attempt_index <= 7:
        outcome_model = DevelopmentPreviewAttemptOutcomeV01
    elif attempt_index <= 9:
        outcome_model = DevelopmentPreviewAttemptOutcomeV02
        payload["schema_version"] = "0.2.0"
    else:
        outcome_model = DevelopmentPreviewAttemptOutcomeV03
        payload["schema_version"] = "0.3.0"
    outcome = outcome_model.model_validate({**payload, "scope_sha256": _scope_digest(payload)})
    path = root / "fidelity/preview_outcomes" / f"{attempt_index:04d}.json"
    write_immutable_json(root, path, outcome.model_dump(mode="json"))
    return artifact_at(root, path)


def render_fidelity_candidate(job_id: str, *, scene_path: Path, run_id: str) -> dict:
    """Build one staged candidate and seven passes under the cumulative immutable lab ledger."""

    root = job_dir(job_id).resolve()
    _validate_run_id(run_id)
    if list((root / "production/autonomy_v2").glob("*/plan.json")):
        raise PermissionError("AQ sessions must use their controller and frozen execution budgets")
    scene_path = ensure_contained_production_path(root, root / scene_path, must_exist=True)
    if not scene_path.relative_to(root).as_posix().startswith("fidelity/"):
        raise PermissionError("development preview accepts fidelity staging only")
    artifact = artifact_at(root, scene_path)
    scene = SceneSpec.model_validate_json(read_artifact(root, artifact))
    if scene.job_id != job_id:
        raise ValueError("preview SceneSpec belongs to another job")
    collect_build_provenance(root, job_id, scene_spec_path=scene_path)
    output = root / "fidelity/previews" / run_id
    qa_dir = root / "qa/runs" / run_id
    if output.exists() or qa_dir.exists():
        raise FileExistsError("preview already attempted; preserve evidence and choose a new round")
    attempt_index = _reserve_preview_attempt(root, job_id, artifact, run_id)
    blend = output / "scene.blend"
    try:
        run_blender(
            "build_scene.py",
            [
                "--spec",
                str(scene_path),
                "--job-root",
                str(root),
                "--output",
                str(blend),
            ],
        )
        read_artifact(root, artifact)
        qa = run_scene_spec_visual_qa_snapshot(
            job_id,
            scene_spec_path=scene_path,
            blend_path=blend,
            run_dir=qa_dir,
            run_id=run_id,
            record_fidelity_conditions=True,
        )
        evidence = capture_render_evidence(
            root,
            qa_run_id=run_id,
            output_dir=output / "evidence",
            scene_spec_path=scene_path,
        )
        _validate_extension_build_fingerprint(
            root,
            job_id,
            attempt_index,
            evidence.build_fingerprint,
        )
        result = {
            "job_id": job_id,
            "run_id": run_id,
            "source": artifact.model_dump(mode="json"),
            "blend": artifact_at(root, blend).model_dump(mode="json"),
            "qa": qa,
            "evidence": evidence.model_dump(mode="json"),
            "scope": "development_preview_not_campaign_or_quality_acceptance",
            "canonical_write": False,
        }
        write_immutable_json(root, output / "result.json", result)
    except Exception as exc:
        _record_preview_outcome(
            root,
            job_id=job_id,
            attempt_index=attempt_index,
            run_id=run_id,
            source=artifact,
            error=exc,
        )
        raise
    _record_preview_outcome(
        root,
        job_id=job_id,
        attempt_index=attempt_index,
        run_id=run_id,
        source=artifact,
        result=artifact_at(root, output / "result.json"),
    )
    return result
