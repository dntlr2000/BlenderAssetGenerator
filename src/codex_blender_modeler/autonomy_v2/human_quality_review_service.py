"""Append-only post-IQ human review evidence for AQ v2 safe terminals."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from ..integrated_quality.v02_models import IntegratedQualityReportV02
from ..production.validation import (
    ensure_contained_production_path,
    validate_production_id,
)
from ..qa.models import RenderPassManifest
from .delivery_service import (
    artifact_for_v2,
    validate_quality_source_freeze,
    validate_v2_artifact,
    write_immutable_v2_model,
)
from .models import (
    AQV2Artifact,
    DeliveryPlan,
    HumanQualityReviewBundleV2,
    QualityApprovedSourceFreeze,
    QualityReviewActionV2,
)
from .quality_terminal_service import (
    validate_quality_terminal_v2,
)

if TYPE_CHECKING:
    from ..production.activation_models import (
        ActivationArtifact,
        ActivationHumanQualityDisposition,
    )

ModelT = TypeVar("ModelT", bound=BaseModel)

_PRODUCER = "codex_blender_modeler.autonomy_v2.human_quality_review_service"
_ACTION_MESSAGE = (
    "Human visual review found that the machine-passed source still needs bounded "
    "authoring revision; no automatic revision or delivery is authorized."
)


def _timestamp(value: datetime | None) -> datetime:
    """Return one timezone-aware publication timestamp."""

    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("human quality review timestamp must be timezone-aware")
    return timestamp


def _load_model(
    root: Path,
    artifact: AQV2Artifact,
    model: type[ModelT],
) -> ModelT:
    """Rehash and strict-parse one exact job-contained model artifact."""

    path = validate_v2_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return model.model_validate_json(handle.read())


def _human_review_actions() -> list[QualityReviewActionV2]:
    """Return the sole deterministic non-executing action for a human non-pass."""

    return [
        QualityReviewActionV2(
            action_id="human-review-action-001",
            finding_id=None,
            destination="manual_evidence_review",
            reason_code="human_quality_needs_revision",
            target_ids=[],
            message=_ACTION_MESSAGE,
        )
    ]


def _load_human_disposition(
    repository_root: Path,
    disposition_path: str | Path,
) -> tuple[ActivationHumanQualityDisposition, Path, str, int]:
    """Load one exact repository-contained activation quality disposition."""

    from ..production.activation_models import ActivationHumanQualityDisposition

    repository = ensure_contained_production_path(
        repository_root,
        repository_root,
        must_exist=True,
    )
    supplied = Path(disposition_path)
    candidate = supplied if supplied.is_absolute() else repository / supplied
    path = ensure_contained_production_path(repository, candidate, must_exist=True)
    if not os.path.isfile(native_io_path(path)):
        raise ValueError("human quality disposition must be a regular file")
    size = os.path.getsize(native_io_path(path))
    if size <= 0:
        raise ValueError("human quality disposition must be non-empty")
    with open(native_io_path(path), "rb") as handle:
        disposition = ActivationHumanQualityDisposition.model_validate_json(
            handle.read()
        )
    return disposition, path, sha256_file(path), size


def _validate_activation_artifact(
    repository_root: Path,
    artifact: ActivationArtifact,
) -> Path:
    """Rehash one strict activation artifact without importing private services."""

    path = ensure_contained_production_path(
        repository_root,
        repository_root / artifact.path,
        must_exist=True,
    )
    if (
        not os.path.isfile(native_io_path(path))
        or os.path.getsize(native_io_path(path)) != artifact.byte_size
        or sha256_file(path) != artifact.sha256
    ):
        raise ValueError("activation artifact changed after human disposition")
    return path


def _render_bindings(
    *,
    repository_root: Path,
    job_root: Path,
    disposition: ActivationHumanQualityDisposition,
    session_id: str,
) -> tuple[AQV2Artifact, AQV2Artifact, RenderPassManifest]:
    """Revalidate the exact Beauty and complete Blender 5.0.1 seven-pass manifest."""

    beauty_repository_path = _validate_activation_artifact(
        repository_root,
        disposition.representative_beauty,
    )
    beauty_path = ensure_contained_production_path(
        job_root,
        beauty_repository_path,
        must_exist=True,
    )
    if beauty_path.parent.name != "passes":
        raise ValueError("human disposition Beauty is outside a V0.6 pass directory")
    manifest_path = ensure_contained_production_path(
        job_root,
        beauty_path.parent.parent / "render_pass_manifest.json",
        must_exist=True,
    )
    with open(native_io_path(manifest_path), "rb") as handle:
        manifest = RenderPassManifest.model_validate_json(handle.read())
    if manifest.job_id != job_root.name or manifest.blender_version != "5.0.1":
        raise ValueError("human review manifest differs from the job or Blender 5.0.1")
    beauty_matches = 0
    for rendered_pass in manifest.passes:
        pass_path = ensure_contained_production_path(
            manifest_path.parent,
            manifest_path.parent / rendered_pass.path,
            must_exist=True,
        )
        if sha256_file(pass_path) != rendered_pass.sha256:
            raise ValueError(f"human review render pass changed: {rendered_pass.path}")
        if (
            rendered_pass.kind == "beauty"
            and pass_path == beauty_path
            and rendered_pass.sha256 == disposition.representative_beauty.sha256
        ):
            beauty_matches += 1
    if beauty_matches != 1:
        raise ValueError("human disposition must bind exactly one manifest Beauty pass")
    beauty = artifact_for_v2(
        job_root,
        beauty_path,
        artifact_id=f"human-review-beauty-{session_id}",
        kind="representative-render",
    )
    render_manifest = artifact_for_v2(
        job_root,
        manifest_path,
        artifact_id=f"human-review-render-manifest-{session_id}",
        kind="render-pass-manifest",
    )
    return beauty, render_manifest, manifest


def _review_input_payload(
    bundle: HumanQualityReviewBundleV2,
) -> dict[str, object]:
    """Build the deterministic input map shared by builders and validators."""

    return {
        "integrated_quality_report": bundle.integrated_quality_report.model_dump(
            mode="json"
        ),
        "machine_quality_terminal": bundle.machine_quality_terminal.model_dump(
            mode="json"
        ),
        "source_freeze": bundle.source_freeze.model_dump(mode="json"),
        "delivery_plan": bundle.delivery_plan.model_dump(mode="json"),
        "candidate_blend": bundle.candidate_blend.model_dump(mode="json"),
        "representative_render": bundle.representative_render.model_dump(mode="json"),
        "render_pass_manifest": bundle.render_pass_manifest.model_dump(mode="json"),
        "human_disposition": {
            "disposition_id": bundle.human_disposition_id,
            "disposition_sha256": bundle.human_disposition_sha256,
            "file_sha256": bundle.human_disposition_file_sha256,
            "byte_size": bundle.human_disposition_byte_size,
            "observed_statement_sha256": (
                bundle.human_disposition_observed_statement_sha256
            ),
            "reviewer_identity": bundle.human_disposition_reviewer_identity,
            "skill_run_id": bundle.human_disposition_skill_run_id,
            "disposition": bundle.human_disposition,
        },
        "recommended_actions": [
            item.model_dump(mode="json") for item in bundle.recommended_actions
        ],
        "delivery_runs": bundle.delivery_runs,
    }


def _validate_human_review_bundle_model(
    *,
    root: Path,
    bundle: HumanQualityReviewBundleV2,
    bundle_artifact: AQV2Artifact | None,
) -> None:
    """Recompute the passed-IQ chain, render evidence, actions, and bundle identity."""

    for artifact in bundle.provenance:
        validate_v2_artifact(root, artifact)
    expected_id = f"human-quality-review-{bundle.session_id}"
    if (
        bundle.contract_id != expected_id
        or bundle.bundle_id != expected_id
        or bundle.producer != _PRODUCER
    ):
        raise ValueError("human quality review bundle was not emitted by its host builder")
    report = _load_model(
        root,
        bundle.integrated_quality_report,
        IntegratedQualityReportV02,
    )
    quality_terminal = validate_quality_terminal_v2(
        root,
        bundle.machine_quality_terminal,
    )
    freeze = _load_model(root, bundle.source_freeze, QualityApprovedSourceFreeze)
    validate_quality_source_freeze(root, freeze)
    delivery = _load_model(root, bundle.delivery_plan, DeliveryPlan)
    identity = (
        bundle.job_id,
        bundle.workflow_id,
        bundle.dispatch_id,
        bundle.session_id,
    )
    if (
        report.job_id,
        report.workflow_id,
        report.dispatch_id,
    ) != identity[:3]:
        raise ValueError("human review IQ report identity differs from its bundle")
    for label, evidence in (
        ("machine quality terminal", quality_terminal),
        ("source freeze", freeze),
        ("delivery plan", delivery),
    ):
        if (
            evidence.job_id,
            evidence.workflow_id,
            evidence.dispatch_id,
            evidence.session_id,
        ) != identity:
            raise ValueError(f"human review {label} identity differs from its bundle")
    if report.outcome != "passed" or not report.quality_accepted:
        raise ValueError("post-IQ human review requires an exact machine-passed report")
    if (
        quality_terminal.status != "quality_approved"
        or quality_terminal.integrated_quality_report
        != bundle.integrated_quality_report
        or quality_terminal.source_freeze != bundle.source_freeze
        or freeze.integrated_quality_report != bundle.integrated_quality_report
        or freeze.authoring_blend != bundle.candidate_blend
        or delivery.source_freeze != bundle.source_freeze
        or not delivery.requests
    ):
        raise ValueError("human review passed-IQ, freeze, and delivery bindings disagree")
    for artifact in delivery.provenance:
        validate_v2_artifact(root, artifact)
    manifest = _load_model(root, bundle.render_pass_manifest, RenderPassManifest)
    if manifest.job_id != bundle.job_id or manifest.blender_version != "5.0.1":
        raise ValueError("human review render manifest differs from its job or runtime")
    render_path = validate_v2_artifact(root, bundle.representative_render)
    manifest_path = validate_v2_artifact(root, bundle.render_pass_manifest)
    beauty_matches = 0
    for rendered_pass in manifest.passes:
        pass_path = ensure_contained_production_path(
            manifest_path.parent,
            manifest_path.parent / rendered_pass.path,
            must_exist=True,
        )
        if sha256_file(pass_path) != rendered_pass.sha256:
            raise ValueError(f"human review render pass changed: {rendered_pass.path}")
        if (
            rendered_pass.kind == "beauty"
            and pass_path == render_path
            and rendered_pass.sha256 == bundle.representative_render.sha256
        ):
            beauty_matches += 1
    if beauty_matches != 1:
        raise ValueError("human review bundle must bind one exact Beauty pass")
    if bundle.recommended_actions != _human_review_actions():
        raise ValueError("human review bundle actions differ from the bounded host action")
    expected_input = stable_json_digest(_review_input_payload(bundle))
    expected_source = stable_json_digest(
        {
            "input_sha256": expected_input,
            "quality_source_fingerprint": report.source_fingerprint,
            "frozen_source_sha256": freeze.frozen_source_sha256,
            "human_disposition_sha256": bundle.human_disposition_sha256,
        }
    )
    if bundle.input_sha256 != expected_input or bundle.source_fingerprint != expected_source:
        raise ValueError("human quality review bundle digest is inconsistent")
    if bundle_artifact is not None:
        expected_path = (
            f"production/autonomy_v2/{bundle.session_id}/"
            "human_quality_review_bundle.json"
        )
        if (
            bundle_artifact.path != expected_path
            or bundle_artifact.kind != "human-quality-review-bundle"
            or bundle_artifact.artifact_id != bundle.contract_id
        ):
            raise ValueError("human quality review bundle is outside its immutable path")


def validate_human_quality_disposition_binding_v2(
    *,
    repository_root: Path,
    job_root: Path,
    bundle: HumanQualityReviewBundleV2,
    disposition_path: str | Path,
) -> ActivationHumanQualityDisposition:
    """Revalidate one external disposition against every exact bundle binding."""

    disposition, _path, file_sha256, byte_size = _load_human_disposition(
        repository_root,
        disposition_path,
    )
    beauty, manifest, _parsed_manifest = _render_bindings(
        repository_root=repository_root,
        job_root=job_root,
        disposition=disposition,
        session_id=bundle.session_id,
    )
    if (
        disposition.job_id != bundle.job_id
        or disposition.skill_run_id != bundle.human_disposition_skill_run_id
        or disposition.disposition != "needs_revision"
        or disposition.disposition_id != bundle.human_disposition_id
        or disposition.disposition_sha256 != bundle.human_disposition_sha256
        or file_sha256 != bundle.human_disposition_file_sha256
        or byte_size != bundle.human_disposition_byte_size
        or disposition.observed_statement_sha256
        != bundle.human_disposition_observed_statement_sha256
        or disposition.reviewer_identity != bundle.human_disposition_reviewer_identity
        or beauty != bundle.representative_render
        or manifest != bundle.render_pass_manifest
    ):
        raise ValueError("human quality disposition differs from its exact review bundle")
    return disposition


def build_human_quality_review_bundle_v2(
    *,
    repository_root: Path,
    job_root: Path,
    session_id: str,
    skill_run_id: str,
    disposition_path: str | Path,
    machine_quality_terminal: AQV2Artifact,
    source_freeze: AQV2Artifact,
    delivery_plan: AQV2Artifact,
    delivery_runs: int,
    created_at: datetime | None = None,
) -> tuple[HumanQualityReviewBundleV2, AQV2Artifact]:
    """Publish one review-only terminal companion after passed IQ and human non-pass."""

    repository = ensure_contained_production_path(
        repository_root,
        repository_root,
        must_exist=True,
    )
    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    validate_production_id(session_id, "AQ v2 session ID")
    validate_production_id(skill_run_id, "AQ skill run ID")
    if isinstance(delivery_runs, bool) or delivery_runs != 0:
        raise ValueError("post-IQ human review requires zero delivery runs")
    disposition, _path, disposition_file_sha256, disposition_size = (
        _load_human_disposition(repository, disposition_path)
    )
    if (
        disposition.job_id != root.name
        or disposition.skill_run_id != skill_run_id
        or disposition.disposition != "needs_revision"
    ):
        raise ValueError("human disposition differs from the requested AQ job/run")
    quality_terminal = validate_quality_terminal_v2(root, machine_quality_terminal)
    if quality_terminal.source_freeze != source_freeze:
        raise ValueError("machine quality terminal differs from the current source freeze")
    freeze = _load_model(root, source_freeze, QualityApprovedSourceFreeze)
    validate_quality_source_freeze(root, freeze)
    representative_render, render_manifest, _manifest = _render_bindings(
        repository_root=repository,
        job_root=root,
        disposition=disposition,
        session_id=session_id,
    )
    actions = _human_review_actions()
    identity = {
        "contract_id": f"human-quality-review-{session_id}",
        "job_id": quality_terminal.job_id,
        "workflow_id": quality_terminal.workflow_id,
        "dispatch_id": quality_terminal.dispatch_id,
        "session_id": session_id,
        "producer": _PRODUCER,
        "provenance": [
            quality_terminal.integrated_quality_report,
            machine_quality_terminal,
            source_freeze,
            delivery_plan,
            freeze.authoring_blend,
            representative_render,
            render_manifest,
        ],
        "created_at": _timestamp(created_at),
        "bundle_id": f"human-quality-review-{session_id}",
        "integrated_quality_report": quality_terminal.integrated_quality_report,
        "machine_quality_terminal": machine_quality_terminal,
        "source_freeze": source_freeze,
        "delivery_plan": delivery_plan,
        "candidate_blend": freeze.authoring_blend,
        "representative_render": representative_render,
        "render_pass_manifest": render_manifest,
        "human_disposition_id": disposition.disposition_id,
        "human_disposition_sha256": disposition.disposition_sha256,
        "human_disposition_file_sha256": disposition_file_sha256,
        "human_disposition_byte_size": disposition_size,
        "human_disposition_observed_statement_sha256": (
            disposition.observed_statement_sha256
        ),
        "human_disposition_reviewer_identity": disposition.reviewer_identity,
        "human_disposition_skill_run_id": disposition.skill_run_id,
        "recommended_actions": actions,
    }
    provisional = HumanQualityReviewBundleV2(
        **identity,
        input_sha256="0" * 64,
        source_fingerprint="0" * 64,
    )
    input_sha256 = stable_json_digest(_review_input_payload(provisional))
    report = _load_model(
        root,
        quality_terminal.integrated_quality_report,
        IntegratedQualityReportV02,
    )
    bundle = provisional.model_copy(
        update={
            "input_sha256": input_sha256,
            "source_fingerprint": stable_json_digest(
                {
                    "input_sha256": input_sha256,
                    "quality_source_fingerprint": report.source_fingerprint,
                    "frozen_source_sha256": freeze.frozen_source_sha256,
                    "human_disposition_sha256": disposition.disposition_sha256,
                }
            ),
        }
    )
    _validate_human_review_bundle_model(
        root=root,
        bundle=bundle,
        bundle_artifact=None,
    )
    validate_human_quality_disposition_binding_v2(
        repository_root=repository,
        job_root=root,
        bundle=bundle,
        disposition_path=disposition_path,
    )
    path = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "human_quality_review_bundle.json"
    )
    artifact = write_immutable_v2_model(root, path, bundle)
    validated = validate_human_quality_review_bundle_v2(root, artifact)
    return validated, artifact


def validate_human_quality_review_bundle_v2(
    job_root: Path,
    bundle_artifact: AQV2Artifact,
) -> HumanQualityReviewBundleV2:
    """Rehash and fully recompute one immutable post-IQ human review bundle."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    bundle = _load_model(root, bundle_artifact, HumanQualityReviewBundleV2)
    _validate_human_review_bundle_model(
        root=root,
        bundle=bundle,
        bundle_artifact=bundle_artifact,
    )
    return bundle
