from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.background_quality.models import BackgroundQualityReport
from codex_blender_modeler.optimization.io import load_model, write_model
from codex_blender_modeler.optimization.models import (
    Bounds3D,
    HashedArtifact,
    MeshPreflightReport,
    MeshSummary,
    OptimizationApproval,
    OptimizationPlan,
    SourceProvenance,
)
from codex_blender_modeler.optimization.optimizer import (
    _consume_optimization_approval,
    _validate_reviewed_directives,
    approve_asset_optimization,
    plan_asset_optimization,
)
from codex_blender_modeler.optimization.preflight import (
    _mesh_summaries,
    profile_artifact,
)
from codex_blender_modeler.optimization.profiles import create_builtin_profile
from codex_blender_modeler.workspace import sha256_file


def _source_provenance() -> SourceProvenance:
    """Create one stable canonical-source fixture without external Blender files."""

    return SourceProvenance(
        scene_spec=HashedArtifact(
            id="scene.test",
            kind="scene_spec",
            path="analysis/scene_spec.json",
            sha256="1" * 64,
        ),
        blend=HashedArtifact(
            id="blend.test",
            kind="blend",
            path="blender/scene.blend",
            sha256="2" * 64,
        ),
        source_fingerprint="3" * 64,
        build_fingerprint="4" * 64,
    )


def _prepare_review_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str, str]:
    """Prepare one isolated profile, preflight, and mocked canonical source."""

    root = tmp_path / "review_case"
    run_id = "run-review-001"
    run_root = root / "optimization" / "runs" / run_id
    profile_path = root / "asset_profiles" / "portable_gltf.json"
    run_root.mkdir(parents=True)
    profile_path.parent.mkdir(parents=True)
    profile = create_builtin_profile("review_case", "portable_gltf", "static_prop")
    write_model(profile_path, profile)
    source = _source_provenance()
    preflight = MeshPreflightReport(
        report_id=f"preflight.{run_id}",
        job_id="review_case",
        profile_id="portable_gltf",
        profile_artifact=profile_artifact(root, profile),
        source=source,
        status="passed",
        ok=True,
        passed=0,
        warnings=0,
        failed=0,
        meshes=[
            MeshSummary(
                target_id="building.main",
                source_tags=[],
                source_renderable=True,
                object_count=3,
                vertex_count=180,
                triangle_count=120,
                boundary_edge_count=0,
                non_manifold_edge_count=0,
                degenerate_face_count=0,
                negative_scale_count=0,
                bounds=Bounds3D(minimum=(0, 0, 0), maximum=(3, 2, 4)),
            ),
            MeshSummary(
                target_id="building.exterior_void.entry",
                source_tags=["hidden-boolean-target", "exterior-opening-cutter"],
                source_renderable=False,
                object_count=1,
                vertex_count=8,
                triangle_count=12,
                boundary_edge_count=0,
                non_manifold_edge_count=0,
                degenerate_face_count=0,
                negative_scale_count=0,
                bounds=Bounds3D(minimum=(1, -1, 0), maximum=(2, 1, 3)),
            ),
            MeshSummary(
                target_id="building.boolean.cutter.untagged",
                source_tags=[],
                source_renderable=False,
                object_count=1,
                vertex_count=8,
                triangle_count=12,
                boundary_edge_count=0,
                non_manifold_edge_count=0,
                degenerate_face_count=0,
                negative_scale_count=0,
                bounds=Bounds3D(minimum=(-2, -1, 0), maximum=(-1, 1, 3)),
            ),
        ],
        created_at="2026-07-20T00:00:00Z",
    )
    write_model(run_root / "mesh_preflight_report.json", preflight)
    feature_config = SimpleNamespace(
        features=SimpleNamespace(portable_asset_core=True)
    )
    monkeypatch.setattr(
        "codex_blender_modeler.optimization.optimizer.load_feature_config",
        lambda: feature_config,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.optimization.optimizer.job_dir",
        lambda _job_id: root,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.optimization.optimizer.load_asset_profile",
        lambda _root, _profile_id: profile,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.optimization.optimizer.collect_source_provenance",
        lambda _root, _job_id: source,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.optimization.optimizer._load_or_run_preflight",
        lambda _job_id, _profile_id, _run_id: (run_id, preflight, run_root),
    )
    return root, run_id, profile_path.as_posix()


def test_review_exposes_lod_and_collider_before_any_derived_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create only review contracts while exposing exact default cost assumptions."""

    root, run_id, _profile_path = _prepare_review_fixture(tmp_path, monkeypatch)
    review = plan_asset_optimization(
        "review_case",
        profile_id="portable_gltf",
        run_id=run_id,
    )

    assert review.status == "awaiting_user_approval"
    assert review.lod.enabled is True
    assert review.lod.semantic_family_count == 1
    assert [item.level for item in review.lod.levels] == [1, 2]
    assert review.lod.source_object_count == 3
    assert review.collision.strategy == "compound"
    assert review.collision.estimated_collider_count == 3
    assert review.collision.estimated_triangle_count == 36
    assert review.plan_sha256 == sha256_file(
        root / "optimization" / "runs" / run_id / "review_plan.json"
    )
    assert not (root / "optimization" / "runs" / run_id / "optimized").exists()
    plan = load_model(
        root / "optimization" / "runs" / run_id / "review_plan.json",
        OptimizationPlan,
    )
    directives = {item.target_id: item for item in plan.directives}
    helper = directives["building.exterior_void.entry"]
    assert helper.include is False
    assert helper.lod_levels == []
    assert helper.collision_strategy == "none"
    untagged = directives["building.boolean.cutter.untagged"]
    assert untagged.include is False
    assert untagged.lod_levels == []
    assert untagged.collision_strategy == "none"


def test_review_preserves_nonpassing_fast_quality_at_exact_approval_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Carry needs-revision evidence into V0.7 without bypassing exact approval."""

    root, run_id, _profile_path = _prepare_review_fixture(tmp_path, monkeypatch)
    quality_path = root / "reports" / "background_delivery" / "quality.json"
    quality_path.parent.mkdir(parents=True)
    source = _source_provenance()
    quality = BackgroundQualityReport(
        job_id="review_case",
        workflow_id="wf-quality",
        quality_status="needs_revision",
        quality_accepted=False,
        standard_workflow_recommended=True,
        overall_direct_score=0.7,
        primary_silhouette_score=0.69,
        primary_bbox_similarity=0.72,
        primary_high_findings=["quality.primary_silhouette"],
        decorative_warnings=["direct.environment.rocks"],
        recommended_standard_revision_targets=["building.main"],
        qa_run_id="v08-quality-qa",
        qa_request_path="qa/runs/v08-quality-qa/request.json",
        qa_request_sha256="5" * 64,
        visual_qa_report_path="qa/runs/v08-quality-qa/visual_qa_report.json",
        visual_qa_report_sha256="6" * 64,
        render_pass_manifest_path=(
            "qa/runs/v08-quality-qa/render_pass_manifest.json"
        ),
        render_pass_manifest_sha256="7" * 64,
        role_map_path="workflows/wf-quality/artifacts/g/fit/role_map.json",
        role_map_sha256="8" * 64,
        fit_report_path="workflows/wf-quality/artifacts/g/fit/fit_report.json",
        fit_report_sha256="9" * 64,
        source_fingerprint=source.source_fingerprint,
        build_fingerprint=source.build_fingerprint,
        qa_scene_spec_sha256="a" * 64,
        qa_camera_fingerprint="b" * 64,
        limitations=["Review delivery is not a visual quality pass."],
        evaluated_at=datetime.now(UTC),
    )
    quality_path.write_text(
        quality.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    review = plan_asset_optimization(
        "review_case",
        profile_id="portable_gltf",
        run_id=run_id,
        source_quality_path=quality_path.relative_to(root).as_posix(),
    )

    assert review.source_quality is not None
    assert review.source_quality.quality_status == "needs_revision"
    assert review.source_quality.primary_high_findings == [
        "quality.primary_silhouette"
    ]
    assert review.source_quality.decorative_warnings == [
        "direct.environment.rocks"
    ]
    assert any("needs_revision" in warning for warning in review.warnings)
    plan = load_model(
        root / "optimization" / "runs" / run_id / "review_plan.json",
        OptimizationPlan,
    )
    assert plan.source_quality == review.source_quality

    quality_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="quality evidence changed"):
        approve_asset_optimization(
            "review_case",
            run_id=run_id,
            plan_sha256=review.plan_sha256,
            approval_note="Do not accept stale source quality.",
        )


def test_reviewed_directive_guard_rejects_tagged_boolean_helper_inclusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a reviewed plan that promotes a tagged boolean helper to render output."""

    root, run_id, _profile_path = _prepare_review_fixture(tmp_path, monkeypatch)
    plan_asset_optimization("review_case", profile_id="portable_gltf", run_id=run_id)
    run_root = root / "optimization" / "runs" / run_id
    plan = load_model(run_root / "review_plan.json", OptimizationPlan)
    preflight = load_model(run_root / "mesh_preflight_report.json", MeshPreflightReport)
    changed = [
        item.model_copy(update={"include": True})
        if item.target_id == "building.exterior_void.entry"
        else item
        for item in plan.directives
    ]

    with pytest.raises(RuntimeError, match="non-render source families"):
        _validate_reviewed_directives(
            OptimizationPlan.model_validate(
                plan.model_copy(update={"directives": changed}).model_dump(mode="json")
            ),
            preflight,
        )


def test_reviewed_directive_guard_rejects_legacy_missing_tag_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require a fresh preflight when a legacy report lacks source-tag evidence."""

    root, run_id, _profile_path = _prepare_review_fixture(tmp_path, monkeypatch)
    plan_asset_optimization("review_case", profile_id="portable_gltf", run_id=run_id)
    run_root = root / "optimization" / "runs" / run_id
    plan = load_model(run_root / "review_plan.json", OptimizationPlan)
    preflight = load_model(run_root / "mesh_preflight_report.json", MeshPreflightReport)
    meshes = [
        mesh.model_copy(update={"source_tags": None})
        if mesh.target_id == "building.main"
        else mesh
        for mesh in preflight.meshes
    ]

    with pytest.raises(RuntimeError, match="lacks source classification evidence"):
        _validate_reviewed_directives(
            plan,
            MeshPreflightReport.model_validate(
                preflight.model_copy(update={"meshes": meshes}).model_dump(mode="json")
            ),
        )


def test_reviewed_directive_guard_rejects_plan_with_no_render_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a plan that would consume approval without producing render geometry."""

    root, run_id, _profile_path = _prepare_review_fixture(tmp_path, monkeypatch)
    plan_asset_optimization("review_case", profile_id="portable_gltf", run_id=run_id)
    run_root = root / "optimization" / "runs" / run_id
    plan = load_model(run_root / "review_plan.json", OptimizationPlan)
    preflight = load_model(run_root / "mesh_preflight_report.json", MeshPreflightReport)
    directives = [
        item.model_copy(
            update={"include": False, "lod_levels": [], "collision_strategy": "none"}
        )
        for item in plan.directives
    ]

    with pytest.raises(RuntimeError, match="at least one render family"):
        _validate_reviewed_directives(
            OptimizationPlan.model_validate(
                plan.model_copy(update={"directives": directives}).model_dump(mode="json")
            ),
            preflight,
        )


def test_preflight_rejects_mixed_boolean_helper_membership_in_one_family() -> None:
    """Fail closed when one semantic family mixes render and cutter instances."""

    def record(name: str, tags: str) -> dict[str, object]:
        """Create one minimal raw Blender mesh record for tag-consistency testing."""

        return {
            "name": name,
            "semantic_id": "building.mixed",
            "type": "MESH",
            "bbox_world": {"min": [0, 0, 0], "max": [1, 1, 1]},
            "topology": {},
            "custom_properties": {"cbm_tags": tags},
        }

    with pytest.raises(ValueError, match="mixes render geometry"):
        _mesh_summaries(
            {
                "objects": [
                    record("render", "proxy"),
                    record("cutter", "proxy,hidden-boolean-target"),
                ]
            }
        )


def test_exact_approval_is_single_use_and_bound_to_the_reviewed_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject mismatched hashes and consume a valid optimization approval once."""

    root, run_id, _profile_path = _prepare_review_fixture(tmp_path, monkeypatch)
    review = plan_asset_optimization(
        "review_case",
        profile_id="portable_gltf",
        run_id=run_id,
    )
    with pytest.raises(RuntimeError, match="exact draft"):
        approve_asset_optimization(
            "review_case",
            run_id=run_id,
            plan_sha256="0" * 64,
            approval_note="Reject the wrong hash.",
        )

    approval = approve_asset_optimization(
        "review_case",
        run_id=run_id,
        plan_sha256=review.plan_sha256,
        approval_note="User approved the displayed LOD and collider settings.",
    )
    run_root = root / "optimization" / "runs" / run_id
    current_plan = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    assert current_plan.status == "approved"
    assert approval.used is False

    consumed = _consume_optimization_approval(
        root,
        run_root,
        current_plan,
        review.plan_sha256,
    )
    assert consumed.used is True
    stored = load_model(run_root / "optimization_approval.json", OptimizationApproval)
    assert stored.used_at is not None
    with pytest.raises(RuntimeError, match="already been consumed"):
        _consume_optimization_approval(
            root,
            run_root,
            current_plan,
            review.plan_sha256,
        )


def test_profile_can_disable_lod_and_collision_before_review() -> None:
    """Allow a user to override default derived geometry before creating a plan."""

    profile = create_builtin_profile(
        "review_case",
        "fbx_interchange",
        "static_environment",
        lod_mode="disabled",
        collision_strategy="none",
    )

    assert profile.lod.enabled is False
    assert profile.lod.targets == []
    assert profile.collision.strategy == "none"


def test_approval_rejects_a_changed_execution_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent post-approval directive or note edits from reaching Blender execution."""

    root, run_id, _profile_path = _prepare_review_fixture(tmp_path, monkeypatch)
    review = plan_asset_optimization(
        "review_case",
        profile_id="portable_gltf",
        run_id=run_id,
    )
    approve_asset_optimization(
        "review_case",
        run_id=run_id,
        plan_sha256=review.plan_sha256,
        approval_note="Approve only the displayed plan.",
    )
    run_root = root / "optimization" / "runs" / run_id
    current_plan = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    changed_plan = current_plan.model_copy(
        update={"notes": [*current_plan.notes, "Unapproved post-review change."]}
    )
    write_model(run_root / "optimization_plan.json", changed_plan)

    with pytest.raises(RuntimeError, match="no longer matches"):
        _consume_optimization_approval(
            root,
            run_root,
            changed_plan,
            review.plan_sha256,
        )
