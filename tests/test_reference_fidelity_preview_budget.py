"""Fail-closed cumulative development-preview budget extension coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_blender_modeler.autonomy.io import write_immutable_json
from codex_blender_modeler.blender_artifacts import stable_json_digest
from codex_blender_modeler.reference_fidelity import preview
from codex_blender_modeler.reference_fidelity.models import (
    DevelopmentPreviewBudgetExtensionV01,
    FeatureAssessment,
    FidelityArtifact,
    FidelityEvaluationV01,
    RenderEvidenceV01,
    RoutedFindingV01,
    UVSpatialPreservationV01,
    VisualFindingSetV01,
)
from codex_blender_modeler.reference_fidelity.service import artifact_at

ROOT = Path(__file__).resolve().parents[1]
JOB = "fidelity_budget_fixture"


def _scene(root: Path) -> Path:
    """Create one valid contained SceneSpec used only for reservation policy tests."""

    data = json.loads((ROOT / "examples/geometry_showcase/scene_spec.seed.json").read_text())
    data["job_id"] = JOB
    path = root / "fidelity/candidate/scene_spec.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _base_ledger(root: Path, source: FidelityArtifact, count: int = 6) -> None:
    """Populate a contiguous legacy-compatible base reservation ledger."""

    for index in range(count):
        write_immutable_json(
            root,
            root / "fidelity/preview_reservations" / f"{index:04d}.json",
            {
                "schema_version": "0.1.0",
                "contract_kind": "fidelity_development_preview_reservation",
                "job_id": JOB,
                "run_id": f"base-{index}",
                "source": source.model_dump(mode="json"),
                "builds": 1,
                "seven_pass_qa_runs": 1,
                "not_aq_campaign_evidence": True,
                "canonical_write": False,
                "human_quality_disposition": "not_recorded",
            },
        )


def _fixture(tmp_path: Path, monkeypatch) -> tuple[Path, Path, FidelityArtifact]:
    """Prepare one isolated job root and route preview.job_dir to it."""

    root = tmp_path / JOB
    root.mkdir()
    scene = _scene(root)
    source = artifact_at(root, scene)
    monkeypatch.setattr(preview, "job_dir", lambda job_id: root)
    monkeypatch.setattr(
        preview,
        "_development_blender_environment",
        lambda: ("a" * 64, "5.0.1"),
    )
    return root, scene, source


def _publish(root: Path, scene: Path) -> FidelityArtifact:
    """Publish the exact two-slot directional-material extension fixture."""

    return preview.publish_development_preview_budget_extension(
        JOB,
        scene_path=scene.relative_to(root),
        primary_run_id="material-directional",
        retry_run_id="material-directional-retry",
    )


def _generic_plan(root: Path, scene: Path):
    """Build one asset-neutral first-extension scope used by exact-approval tests."""

    return preview.plan_development_preview_reference_fidelity_extension(
        JOB,
        scene_path=scene.relative_to(root),
        primary_run_id="structural-correction",
        retry_run_id="structural-correction-retry",
    )


def _alternate_scene(root: Path, scene: Path) -> tuple[Path, FidelityArtifact]:
    """Create one changed but valid exact source for the strategy-switch extension."""

    data = json.loads(scene.read_text(encoding="utf-8"))
    data["assumptions"] = [*data.get("assumptions", []), "fixture material strategy changed"]
    path = root / "fidelity/candidate-v2/scene_spec.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, artifact_at(root, path)


def _attach_fixture_texture(root: Path, scene: Path) -> Path:
    """Attach one minimal image manifest so nested source tampering can be exercised."""

    data = json.loads(scene.read_text(encoding="utf-8"))
    material_id = data["materials"][0]["id"]
    texture_dir = scene.parent / "textures"
    texture_dir.mkdir()
    image_path = texture_dir / "base_color.png"
    image_path.write_bytes(b"exact-fixture-image")
    manifest_path = texture_dir / "texture_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": material_id,
                "uv_set": "UVMap",
                "intended_scale_m": 1.0,
                "resolution": [64, 64],
                "source_type": "image",
                "channels": {
                    "base_color": {
                        "source": "image",
                        "path": "base_color.png",
                        "color_space": "sRGB",
                    }
                },
                "procedural": {},
            }
        ),
        encoding="utf-8",
    )
    data["materials"][0]["texture_manifest"] = manifest_path.relative_to(root).as_posix()
    scene.write_text(json.dumps(data), encoding="utf-8")
    return image_path


def _complete_first_extension_primary(
    root: Path,
    scene: Path,
    source: FidelityArtifact,
) -> None:
    """Complete slot seven so its closed retry cannot be silently reclaimed."""

    _publish(root, scene)
    assert preview._reserve_preview_attempt(root, JOB, source, "material-directional") == 6
    result_path = root / "fidelity/previews/material-directional/result.json"
    result_path.write_text('{"completed": true}', encoding="utf-8")
    preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=6,
        run_id="material-directional",
        source=source,
        result=artifact_at(root, result_path),
    )


def _strategy_switch_plan(root: Path, scene: Path):
    """Build the exact second-extension proposal used by policy tests."""

    return preview.plan_development_preview_strategy_switch_extension(
        JOB,
        scene_path=scene.relative_to(root),
        primary_run_id="material-strategy-switch",
        retry_run_id="material-strategy-switch-retry",
    )


def _publish_strategy_switch(root: Path, scene: Path) -> FidelityArtifact:
    """Publish one exact-hash-approved second-extension fixture."""

    plan = _strategy_switch_plan(root, scene)
    return preview.publish_development_preview_strategy_switch_extension(
        JOB,
        scene_path=scene.relative_to(root),
        primary_run_id=plan.primary_run_id,
        retry_run_id=plan.retry_run_id,
        approved_scope_sha256=plan.scope_sha256,
    )


def _complete_strategy_switch_primary(
    root: Path,
    base_scene: Path,
    base_source: FidelityArtifact,
) -> tuple[Path, FidelityArtifact]:
    """Complete the second-extension primary so a distinct correction can be proposed."""

    _complete_first_extension_primary(root, base_scene, base_source)
    alternate, alternate_source = _alternate_scene(root, base_scene)
    _publish_strategy_switch(root, alternate)
    assert (
        preview._reserve_preview_attempt(root, JOB, alternate_source, "material-strategy-switch")
        == 7
    )
    result_path = root / "fidelity/previews/material-strategy-switch/result.json"
    result_path.write_text('{"completed": true}', encoding="utf-8")
    preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=7,
        run_id="material-strategy-switch",
        source=alternate_source,
        result=artifact_at(root, result_path),
    )
    return alternate, alternate_source


def _correction_scene(root: Path, previous: Path) -> tuple[Path, FidelityArtifact]:
    """Create one distinct structural/material correction source for extension-three tests."""

    data = json.loads(previous.read_text(encoding="utf-8"))
    data["assumptions"] = [*data.get("assumptions", []), "fixture structure corrected"]
    path = root / "fidelity/candidate-v3/scene_spec.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, artifact_at(root, path)


def _correction_plan(root: Path, scene: Path):
    """Build the exact third-extension proposal used by correction policy tests."""

    return preview.plan_development_preview_fidelity_correction_extension(
        JOB,
        scene_path=scene.relative_to(root),
        primary_run_id="fidelity-correction",
        retry_run_id="fidelity-correction-retry",
    )


def _publish_correction(root: Path, scene: Path) -> FidelityArtifact:
    """Publish one exact-hash-approved structural/material correction extension fixture."""

    plan = _correction_plan(root, scene)
    return preview.publish_development_preview_fidelity_correction_extension(
        JOB,
        scene_path=scene.relative_to(root),
        primary_run_id=plan.primary_run_id,
        retry_run_id=plan.retry_run_id,
        approved_scope_sha256=plan.scope_sha256,
    )


def _complete_fidelity_correction_primary(
    root: Path,
    base_scene: Path,
    base_source: FidelityArtifact,
) -> tuple[Path, FidelityArtifact]:
    """Complete the third extension primary before a material-only refinement."""

    previous, _ = _complete_strategy_switch_primary(root, base_scene, base_source)
    correction, correction_source = _correction_scene(root, previous)
    _publish_correction(root, correction)
    assert (
        preview._reserve_preview_attempt(root, JOB, correction_source, "fidelity-correction") == 8
    )
    result_path = root / "fidelity/previews/fidelity-correction/result.json"
    result_path.write_text('{"completed": true}', encoding="utf-8")
    preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=8,
        run_id="fidelity-correction",
        source=correction_source,
        result=artifact_at(root, result_path),
    )
    return correction, correction_source


def _contract_artifact(label: str) -> FidelityArtifact:
    """Create one contract-only nested artifact for visual-review fixtures."""

    return FidelityArtifact(
        path=f"fidelity/fixture-evidence/{label}.json",
        sha256=stable_json_digest(label),
    )


def _write_material_revision_finding(
    root: Path,
    *,
    run_id: str,
    source: FidelityArtifact,
) -> tuple[FidelityArtifact, FidelityArtifact]:
    """Publish one exact nonhuman major material finding for extension-four tests."""

    hypothesis = _contract_artifact("hypothesis")
    evidence = RenderEvidenceV01(
        scene_spec=source,
        qa_request=_contract_artifact("qa-request"),
        qa_report=_contract_artifact("qa-report"),
        pass_manifest=_contract_artifact("pass-manifest"),
        camera_fingerprint=stable_json_digest("camera"),
        build_fingerprint=stable_json_digest("build"),
        render_engine="BLENDER_EEVEE",
        resolution=(512, 512),
        passes={
            name: _contract_artifact(name)
            for name in (
                "beauty",
                "silhouette",
                "object_id",
                "material_id",
                "normal",
                "depth",
                "wireframe",
            )
        },
    )
    findings = VisualFindingSetV01(
        job_id=JOB,
        review_id=run_id,
        hypothesis=hypothesis,
        reference=_contract_artifact("reference"),
        evidence=evidence,
        assessments=[
            FeatureAssessment(
                feature_id="surface-direction",
                outcome="defect",
                confidence=0.95,
                actual="The surface direction remains too uniform for the observed material.",
                evidence_passes=["beauty", "normal"],
                candidate_region=(0.0, 0.0, 1.0, 1.0),
            )
        ],
    )
    review_root = root / "fidelity/inspection" / run_id
    findings_path = review_root / "visual_findings.json"
    write_immutable_json(root, findings_path, findings.model_dump(mode="json"))
    findings_artifact = artifact_at(root, findings_path)
    evaluation = FidelityEvaluationV01(
        hypothesis=hypothesis,
        visual_review=findings_artifact,
        legacy_direct_score=0.8,
        required_features=1,
        satisfied_features=0,
        findings=[
            RoutedFindingV01(
                feature_id="surface-direction",
                target_ids=["showcase.cube"],
                face_groups=[],
                observation_ids=["surface"],
                kind="surface_direction",
                severity="major",
                expected="Directional material breakup follows the observed surface.",
                actual="The rendered surface remains too uniform and needs material revision.",
                comparison="Compare the same camera and lighting after material revision.",
                route="material_revision",
            )
        ],
        outcome="needs_revision",
        next_action="material_revision",
    )
    evaluation_path = review_root / "evaluation.json"
    write_immutable_json(root, evaluation_path, evaluation.model_dump(mode="json"))
    return findings_artifact, artifact_at(root, evaluation_path)


def _write_spatial_preservation(
    root: Path,
    *,
    scene: Path,
    common_scene: FidelityArtifact,
    common_mesh: FidelityArtifact,
) -> FidelityArtifact:
    """Publish one strict material-only spatial-preservation fixture."""

    candidate_mesh_path = scene.parent / "candidate.mesh.json"
    candidate_mesh_path.write_text('{"fixture": true}', encoding="utf-8")
    audit = UVSpatialPreservationV01(
        job_id=JOB,
        source_scene=common_scene,
        candidate_scene=artifact_at(root, scene),
        source_mesh=common_mesh,
        candidate_mesh=artifact_at(root, candidate_mesh_path),
        source_vertex_count=8,
        candidate_vertex_count=8,
        seam_duplicate_count=0,
        uv_representation="polygon_corner_mesh_payload_v02",
        loop_uv_count_matches=True,
        closed_two_manifold=True,
        bounds_equal=True,
        zero_area_face_count=0,
        source_side_faces_equal=True,
        cap_retriangulation_preserves_surface=True,
        exact_topology_preserved=True,
        original_positions_equal=True,
        duplicates_match_source_positions=True,
        faces_equal_after_seam_collapse=True,
        object_pose_equal=True,
        camera_equal=True,
        reference_sources_equal=True,
        spatial_geometry_preserved=True,
    )
    path = scene.parent / "uv_spatial_preservation.json"
    write_immutable_json(root, path, audit.model_dump(mode="json"))
    return artifact_at(root, path)


def _material_refinement_scene(root: Path, previous: Path) -> tuple[Path, FidelityArtifact]:
    """Create one changed material-only source for extension-four tests."""

    data = json.loads(previous.read_text(encoding="utf-8"))
    data["assumptions"] = [*data.get("assumptions", []), "fixture material refined"]
    path = root / "fidelity/candidate-v4/scene_spec.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, artifact_at(root, path)


def _prepare_material_refinement(
    root: Path,
    base_scene: Path,
    base_source: FidelityArtifact,
) -> tuple[Path, FidelityArtifact]:
    """Prepare the completed review and dual spatial audits needed by extension four."""

    correction, correction_source = _complete_fidelity_correction_primary(
        root, base_scene, base_source
    )
    refinement, refinement_source = _material_refinement_scene(root, correction)
    common_scene = artifact_at(root, base_scene)
    common_mesh_path = root / "fidelity/common-source.mesh.json"
    common_mesh_path.write_text('{"fixture": "mesh"}', encoding="utf-8")
    common_mesh = artifact_at(root, common_mesh_path)
    _write_material_revision_finding(
        root,
        run_id="fidelity-correction",
        source=correction_source,
    )
    _write_spatial_preservation(
        root,
        scene=correction,
        common_scene=common_scene,
        common_mesh=common_mesh,
    )
    _write_spatial_preservation(
        root,
        scene=refinement,
        common_scene=common_scene,
        common_mesh=common_mesh,
    )
    return refinement, refinement_source


def _material_refinement_plan(root: Path, scene: Path):
    """Build the exact fourth-extension proposal used by material policy tests."""

    return preview.plan_development_preview_material_refinement_extension(
        JOB,
        scene_path=scene.relative_to(root),
        primary_run_id="material-refinement",
        retry_run_id="material-refinement-retry",
    )


def _publish_material_refinement(root: Path, scene: Path) -> FidelityArtifact:
    """Publish one exact-hash-approved material-refinement extension fixture."""

    plan = _material_refinement_plan(root, scene)
    return preview.publish_development_preview_material_refinement_extension(
        JOB,
        scene_path=scene.relative_to(root),
        primary_run_id=plan.primary_run_id,
        retry_run_id=plan.retry_run_id,
        approved_scope_sha256=plan.scope_sha256,
    )


def test_six_attempt_cap_remains_without_exact_extension(tmp_path, monkeypatch) -> None:
    """Preserve the original hard cap when no explicit job-local extension exists."""

    root, _, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    with pytest.raises(PermissionError, match="exhausted"):
        preview._reserve_preview_attempt(root, JOB, source, "material-directional")


def test_asset_neutral_first_extension_requires_exact_scope_approval(tmp_path, monkeypatch) -> None:
    """Plan without writes and reject a mismatched hash before publishing any authority."""

    root, scene, _ = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, artifact_at(root, scene))
    plan = _generic_plan(root, scene)
    extension_path = root / "fidelity/preview_budget_extensions/0000.json"
    assert plan.purpose == "reference_fidelity_structural_correction"
    assert plan.execution_request_basis == "exact_scope_sha256_user_approval"
    assert not extension_path.exists()
    with pytest.raises(PermissionError, match="lacks exact scope approval"):
        preview.publish_development_preview_reference_fidelity_extension(
            JOB,
            scene_path=scene.relative_to(root),
            primary_run_id=plan.primary_run_id,
            retry_run_id=plan.retry_run_id,
            approved_scope_sha256="0" * 64,
        )
    assert not extension_path.exists()


def test_asset_neutral_first_extension_is_source_bound_and_legacy_stays_readable(
    tmp_path, monkeypatch
) -> None:
    """Publish the generic scope once while preserving the historical wood contract meaning."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    plan = _generic_plan(root, scene)
    extension = preview.publish_development_preview_reference_fidelity_extension(
        JOB,
        scene_path=scene.relative_to(root),
        primary_run_id=plan.primary_run_id,
        retry_run_id=plan.retry_run_id,
        approved_scope_sha256=plan.scope_sha256,
    )
    payload = json.loads((root / extension.path).read_text(encoding="utf-8"))
    assert payload["purpose"] == "reference_fidelity_structural_correction"
    assert (
        preview._reserve_preview_attempt(root, JOB, source, plan.primary_run_id)
        == preview.BASE_PREVIEW_ATTEMPT_LIMIT
    )

    other_parent = tmp_path / "legacy"
    other_parent.mkdir()
    other_root, other_scene, other_source = _fixture(other_parent, monkeypatch)
    _base_ledger(other_root, other_source)
    legacy = _publish(other_root, other_scene)
    legacy_payload = json.loads((other_root / legacy.path).read_text(encoding="utf-8"))
    assert legacy_payload["purpose"] == "directional_wood_material_correction"
    assert legacy_payload["execution_request_basis"] == "current_task_explicit_bounded_execution"


def test_first_extension_rejects_crossed_legacy_and_exact_approval_semantics(
    tmp_path, monkeypatch
) -> None:
    """Prevent a new structural purpose from inheriting the historical implicit basis."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    plan = _generic_plan(root, scene)
    payload = plan.model_dump(mode="json", exclude={"scope_sha256"})
    payload["execution_request_basis"] = "current_task_explicit_bounded_execution"
    with pytest.raises(ValueError, match="purpose and approval basis differ"):
        DevelopmentPreviewBudgetExtensionV01.model_validate(
            {**payload, "scope_sha256": stable_json_digest(payload)}
        )


def test_extension_requires_exact_exhausted_job_and_untampered_scope(tmp_path, monkeypatch) -> None:
    """Reject early, cross-job, malformed, and self-digest-tampered extensions."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source, count=5)
    with pytest.raises(PermissionError, match="exact exhausted"):
        _publish(root, scene)
    _base_ledger(root, source, count=6)
    extension = _publish(root, scene)
    data = json.loads((root / extension.path).read_text())
    data["job_id"] = "another_job"
    (root / extension.path).write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="scope digest"):
        preview._reserve_preview_attempt(root, JOB, source, "material-directional")


def test_exact_extension_allows_primary_but_not_visual_second_try(tmp_path, monkeypatch) -> None:
    """Permit slot seven once and keep slot eight closed after a completed visual result."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    _publish(root, scene)
    assert preview._reserve_preview_attempt(root, JOB, source, "material-directional") == 6
    result_path = root / "fidelity/previews/material-directional/result.json"
    result_path.write_text('{"completed": true}', encoding="utf-8")
    preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=6,
        run_id="material-directional",
        source=source,
        result=artifact_at(root, result_path),
    )
    with pytest.raises(PermissionError, match="technical failure"):
        preview._reserve_preview_attempt(root, JOB, source, "material-directional-retry")


def test_retry_requires_identical_source_and_primary_technical_failure(
    tmp_path, monkeypatch
) -> None:
    """Spend the last slot only on the declared run with the byte-identical failed input."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    _publish(root, scene)
    assert preview._reserve_preview_attempt(root, JOB, source, "material-directional") == 6
    preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=6,
        run_id="material-directional",
        source=source,
        error=RuntimeError("fixture Blender process failed"),
    )
    changed = FidelityArtifact(path=source.path, sha256=stable_json_digest("changed"))
    with pytest.raises(PermissionError, match="source differs"):
        preview._reserve_preview_attempt(root, JOB, changed, "material-directional-retry")
    with pytest.raises(PermissionError, match="exact technical-retry"):
        preview._reserve_preview_attempt(root, JOB, source, "different-retry")
    assert preview._reserve_preview_attempt(root, JOB, source, "material-directional-retry") == 7
    with pytest.raises(PermissionError, match="cumulative extension budget exhausted"):
        preview._reserve_preview_attempt(root, JOB, source, "material-directional-retry-2")


def test_strategy_switch_requires_completed_primary_and_exact_scope_approval(
    tmp_path, monkeypatch
) -> None:
    """Plan without writing, then reject early state and any mismatched approval hash."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    _publish(root, scene)
    alternate, _ = _alternate_scene(root, scene)
    with pytest.raises(PermissionError, match="exactly one completed"):
        _strategy_switch_plan(root, alternate)
    assert preview._reserve_preview_attempt(root, JOB, source, "material-directional") == 6
    preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=6,
        run_id="material-directional",
        source=source,
        error=RuntimeError("fixture visual result was never produced"),
    )
    with pytest.raises(PermissionError, match="exact first-extension primary completion"):
        _strategy_switch_plan(root, alternate)

    other_parent = tmp_path / "other"
    other_parent.mkdir()
    other_root, other_scene, other_source = _fixture(other_parent, monkeypatch)
    _base_ledger(other_root, other_source)
    _complete_first_extension_primary(other_root, other_scene, other_source)
    other_alternate, _ = _alternate_scene(other_root, other_scene)
    plan = _strategy_switch_plan(other_root, other_alternate)
    assert not (other_root / "fidelity/preview_budget_extensions/0001.json").exists()
    with pytest.raises(PermissionError, match="lacks exact scope approval"):
        preview.publish_development_preview_strategy_switch_extension(
            JOB,
            scene_path=other_alternate.relative_to(other_root),
            primary_run_id=plan.primary_run_id,
            retry_run_id=plan.retry_run_id,
            approved_scope_sha256="0" * 64,
        )
    assert not (other_root / "fidelity/preview_budget_extensions/0001.json").exists()


def test_strategy_switch_primary_and_retry_are_append_only_and_source_bound(
    tmp_path, monkeypatch
) -> None:
    """Use one changed-source primary and only one byte-identical technical retry."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    _complete_first_extension_primary(root, scene, source)
    alternate, alternate_source = _alternate_scene(root, scene)
    extension = _publish_strategy_switch(root, alternate)
    extension_payload = json.loads((root / extension.path).read_text(encoding="utf-8"))
    assert extension_payload["schema_version"] == "0.2.0"
    assert extension_payload["prior_reserved_attempt_count"] == 7
    assert extension_payload["closed_prior_retry_slots"] == 1
    assert extension_payload["maximum_total_reservations"] == 9
    assert extension_payload["reclaims_closed_retry_slot"] is False
    assert (
        preview._reserve_preview_attempt(root, JOB, alternate_source, "material-strategy-switch")
        == 7
    )
    preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=7,
        run_id="material-strategy-switch",
        source=alternate_source,
        error=RuntimeError("fixture Blender process failed before beauty"),
    )
    changed = FidelityArtifact(path=alternate_source.path, sha256=stable_json_digest("changed"))
    with pytest.raises(PermissionError, match="source differs"):
        preview._reserve_preview_attempt(root, JOB, changed, "material-strategy-switch-retry")
    assert (
        preview._reserve_preview_attempt(
            root, JOB, alternate_source, "material-strategy-switch-retry"
        )
        == 8
    )
    result_path = root / "fidelity/previews/material-strategy-switch-retry/result.json"
    result_path.write_text('{"completed": true}', encoding="utf-8")
    outcome = preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=8,
        run_id="material-strategy-switch-retry",
        source=alternate_source,
        result=artifact_at(root, result_path),
    )
    assert json.loads((root / outcome.path).read_text())["schema_version"] == "0.2.0"
    with pytest.raises(PermissionError, match="cumulative extension budget exhausted"):
        preview._reserve_preview_attempt(root, JOB, alternate_source, "third-try")
    with pytest.raises(FileExistsError, match="already exists"):
        _strategy_switch_plan(root, alternate)


def test_strategy_switch_extension_tamper_fails_before_reservation(tmp_path, monkeypatch) -> None:
    """Reject a modified second extension instead of treating its scope as new authority."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    _complete_first_extension_primary(root, scene, source)
    alternate, alternate_source = _alternate_scene(root, scene)
    extension = _publish_strategy_switch(root, alternate)
    path = root / extension.path
    data = json.loads(path.read_text(encoding="utf-8"))
    data["primary_run_id"] = "tampered-run"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="scope digest differs"):
        preview._reserve_preview_attempt(root, JOB, alternate_source, "material-strategy-switch")


def test_strategy_switch_nested_dependency_tamper_fails_before_reservation(
    tmp_path, monkeypatch
) -> None:
    """Bind texture bytes as well as the SceneSpec so approval cannot outlive its inputs."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    _complete_first_extension_primary(root, scene, source)
    alternate, _ = _alternate_scene(root, scene)
    image = _attach_fixture_texture(root, alternate)
    alternate_source = artifact_at(root, alternate)
    extension = _publish_strategy_switch(root, alternate)
    data = json.loads((root / extension.path).read_text(encoding="utf-8"))
    paths = [item["path"] for item in data["source_dependencies"]]
    assert (
        alternate.parent.joinpath("textures/texture_manifest.json").relative_to(root).as_posix()
        in paths
    )
    assert image.relative_to(root).as_posix() in paths
    image.write_bytes(b"changed-after-exact-approval")
    with pytest.raises(ValueError, match="source dependency closure differs"):
        preview._reserve_preview_attempt(root, JOB, alternate_source, "material-strategy-switch")


def test_strategy_switch_implementation_drift_fails_before_reservation(
    tmp_path, monkeypatch
) -> None:
    """Invalidate exact approval when the host or Blender runtime implementation changes."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    _complete_first_extension_primary(root, scene, source)
    alternate, alternate_source = _alternate_scene(root, scene)
    _publish_strategy_switch(root, alternate)
    monkeypatch.setattr(
        preview,
        "_development_implementation_fingerprint",
        lambda: "f" * 64,
    )
    with pytest.raises(ValueError, match="implementation fingerprint differs"):
        preview._reserve_preview_attempt(root, JOB, alternate_source, "material-strategy-switch")


def test_strategy_switch_blender_environment_drift_fails_before_reservation(
    tmp_path, monkeypatch
) -> None:
    """Invalidate exact approval before rendering with a different Blender executable."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    _complete_first_extension_primary(root, scene, source)
    alternate, alternate_source = _alternate_scene(root, scene)
    _publish_strategy_switch(root, alternate)
    monkeypatch.setattr(
        preview,
        "_development_blender_environment",
        lambda: ("b" * 64, "5.0.1"),
    )
    with pytest.raises(ValueError, match="Blender environment differs"):
        preview._reserve_preview_attempt(root, JOB, alternate_source, "material-strategy-switch")


def test_completed_historical_runtime_does_not_block_a_new_exact_extension(
    tmp_path, monkeypatch
) -> None:
    """Keep completed evidence readable while binding the next scope to the current runtime."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    previous, _ = _complete_strategy_switch_primary(root, scene, source)
    correction, _ = _correction_scene(root, previous)
    monkeypatch.setattr(
        preview,
        "_development_implementation_fingerprint",
        lambda: "f" * 64,
    )
    plan = _correction_plan(root, correction)
    assert plan.implementation_fingerprint == "f" * 64
    assert plan.prior_reserved_attempt_count == 8
    assert not (root / "fidelity/preview_budget_extensions/0002.json").exists()


def test_fidelity_correction_primary_is_exact_and_closes_visual_retry(
    tmp_path, monkeypatch
) -> None:
    """Authorize one changed-source primary and no aesthetic retry after completion."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    previous, _ = _complete_strategy_switch_primary(root, scene, source)
    correction, correction_source = _correction_scene(root, previous)
    extension = _publish_correction(root, correction)
    payload = json.loads((root / extension.path).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "0.3.0"
    assert payload["closed_prior_retry_slots"] == 2
    assert payload["maximum_total_reservations"] == 10
    assert (
        preview._reserve_preview_attempt(root, JOB, correction_source, "fidelity-correction") == 8
    )
    result_path = root / "fidelity/previews/fidelity-correction/result.json"
    result_path.write_text('{"completed": true}', encoding="utf-8")
    preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=8,
        run_id="fidelity-correction",
        source=correction_source,
        result=artifact_at(root, result_path),
    )
    with pytest.raises(PermissionError, match="technical failure"):
        preview._reserve_preview_attempt(root, JOB, correction_source, "fidelity-correction-retry")


def test_fidelity_correction_active_runtime_drift_fails_before_reservation(
    tmp_path, monkeypatch
) -> None:
    """Invalidate the third approval when its active implementation fingerprint changes."""

    root, scene, source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, source)
    previous, _ = _complete_strategy_switch_primary(root, scene, source)
    correction, correction_source = _correction_scene(root, previous)
    _publish_correction(root, correction)
    monkeypatch.setattr(
        preview,
        "_development_implementation_fingerprint",
        lambda: "e" * 64,
    )
    with pytest.raises(ValueError, match="fidelity-correction implementation fingerprint"):
        preview._reserve_preview_attempt(root, JOB, correction_source, "fidelity-correction")


def test_material_refinement_requires_exact_review_and_scope_approval(
    tmp_path, monkeypatch
) -> None:
    """Bind the fourth proposal to a completed material finding without writing authority."""

    root, base_scene, base_source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, base_source)
    refinement, _ = _prepare_material_refinement(root, base_scene, base_source)
    plan = _material_refinement_plan(root, refinement)
    assert plan.schema_version == "0.4.0"
    assert plan.revision_route == "material_revision"
    assert plan.prior_reserved_attempt_count == 9
    assert plan.closed_prior_retry_slots == 3
    assert plan.maximum_total_reservations == 11
    assert not (root / "fidelity/preview_budget_extensions/0003.json").exists()

    with pytest.raises(PermissionError, match="lacks exact scope approval"):
        preview.publish_development_preview_material_refinement_extension(
            JOB,
            scene_path=refinement.relative_to(root),
            primary_run_id=plan.primary_run_id,
            retry_run_id=plan.retry_run_id,
            approved_scope_sha256="0" * 64,
        )
    assert not (root / "fidelity/preview_budget_extensions/0003.json").exists()


def test_material_refinement_primary_closes_aesthetic_retry(tmp_path, monkeypatch) -> None:
    """Permit one exact material primary and close its retry after a completed beauty."""

    root, base_scene, base_source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, base_source)
    refinement, refinement_source = _prepare_material_refinement(root, base_scene, base_source)
    extension = _publish_material_refinement(root, refinement)
    payload = json.loads((root / extension.path).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "0.4.0"
    assert payload["prior_evaluation"]["path"].endswith("evaluation.json")
    assert (
        preview._reserve_preview_attempt(root, JOB, refinement_source, "material-refinement") == 9
    )
    result_path = root / "fidelity/previews/material-refinement/result.json"
    result_path.write_text('{"completed": true}', encoding="utf-8")
    preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=9,
        run_id="material-refinement",
        source=refinement_source,
        result=artifact_at(root, result_path),
    )
    with pytest.raises(PermissionError, match="technical failure"):
        preview._reserve_preview_attempt(root, JOB, refinement_source, "material-refinement-retry")


def test_material_refinement_retry_is_identical_input_and_new_outcome_version(
    tmp_path, monkeypatch
) -> None:
    """Use attempt ten only after an exact-input technical failure before beauty."""

    root, base_scene, base_source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, base_source)
    refinement, refinement_source = _prepare_material_refinement(root, base_scene, base_source)
    _publish_material_refinement(root, refinement)
    assert (
        preview._reserve_preview_attempt(root, JOB, refinement_source, "material-refinement") == 9
    )
    preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=9,
        run_id="material-refinement",
        source=refinement_source,
        error=RuntimeError("fixture Blender failed before beauty"),
    )
    changed = FidelityArtifact(
        path=refinement_source.path,
        sha256=stable_json_digest("changed-material-refinement"),
    )
    with pytest.raises(PermissionError, match="source differs"):
        preview._reserve_preview_attempt(root, JOB, changed, "material-refinement-retry")
    assert (
        preview._reserve_preview_attempt(root, JOB, refinement_source, "material-refinement-retry")
        == 10
    )
    result_path = root / "fidelity/previews/material-refinement-retry/result.json"
    result_path.write_text('{"completed": true}', encoding="utf-8")
    outcome = preview._record_preview_outcome(
        root,
        job_id=JOB,
        attempt_index=10,
        run_id="material-refinement-retry",
        source=refinement_source,
        result=artifact_at(root, result_path),
    )
    assert json.loads((root / outcome.path).read_text())["schema_version"] == "0.3.0"
    with pytest.raises(PermissionError, match="cumulative extension budget exhausted"):
        preview._reserve_preview_attempt(root, JOB, refinement_source, "third-try")


def test_material_refinement_review_tamper_fails_before_reservation(tmp_path, monkeypatch) -> None:
    """Reject changed visual findings after the exact fourth scope is published."""

    root, base_scene, base_source = _fixture(tmp_path, monkeypatch)
    _base_ledger(root, base_source)
    refinement, refinement_source = _prepare_material_refinement(root, base_scene, base_source)
    _publish_material_refinement(root, refinement)
    findings = root / "fidelity/inspection/fidelity-correction/visual_findings.json"
    payload = json.loads(findings.read_text(encoding="utf-8"))
    payload["assessments"][0]["actual"] = "changed after exact scope publication"
    findings.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PermissionError, match="exact unresolved nonhuman material finding"):
        preview._reserve_preview_attempt(root, JOB, refinement_source, "material-refinement")
