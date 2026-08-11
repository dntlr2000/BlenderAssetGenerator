"""Focused host tests for exact-approved AQ v2 delivery execution."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.autonomy_v2.delivery_executor import (
    _adopt_completed_portable_request,
    _execute_portable_request,
    _validate_consumed_exact_approval,
    _validate_unused_exact_approval,
    execute_approved_delivery_plan_v2,
)
from codex_blender_modeler.autonomy_v2.delivery_service import artifact_for_v2
from codex_blender_modeler.autonomy_v2.models import (
    AQV2Artifact,
    DeliveryPlan,
    DeliveryRequest,
    DeliveryResult,
    DeliveryReviewBinding,
    DeliveryReviewEntry,
)
from codex_blender_modeler.autonomy_v2.profiles import delivery_profile
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
    approve_asset_optimization,
    plan_asset_optimization,
)
from codex_blender_modeler.optimization.preflight import profile_artifact
from codex_blender_modeler.optimization.profiles import create_builtin_profile
from codex_blender_modeler.structural_geometry.geometry_survival_v02 import (
    GeometryEvidenceFingerprintV02,
    GeometryStageSnapshotV02,
    compare_geometry_stage_snapshots_v02,
)
from codex_blender_modeler.workspace import sha256_file

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def _digest(seed: str) -> str:
    """Return one deterministic SHA-256 test value."""

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _aq_artifact(name: str, kind: str) -> AQV2Artifact:
    """Create one JSON-shaped AQ artifact binding for isolated orchestration tests."""

    return AQV2Artifact(
        artifact_id=name,
        kind=kind,
        path=f"fixtures/{name}.json",
        sha256=_digest(name),
        byte_size=1,
    )


def _source_provenance() -> SourceProvenance:
    """Create one stable direct-source V0.7 provenance fixture."""

    return SourceProvenance(
        scene_spec=HashedArtifact(
            id="scene.exec",
            kind="scene_spec",
            path="analysis/scene_spec.json",
            sha256="1" * 64,
        ),
        blend=HashedArtifact(
            id="blend.exec",
            kind="blend",
            path="blender/scene.blend",
            sha256="2" * 64,
        ),
        source_fingerprint="3" * 64,
        build_fingerprint="4" * 64,
    )


def _prepare_real_approval(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[DeliveryRequest, DeliveryReviewEntry, SimpleNamespace]:
    """Create one real draft review and unused exact V0.7 user approval."""

    job_id = "aq_v2_exec"
    run_id = "delivery-run-glb"
    run_root = root / "optimization" / "runs" / run_id
    run_root.mkdir(parents=True)
    profile = create_builtin_profile(job_id, "portable_gltf", "static_prop")
    profile_path = root / "asset_profiles" / "portable_gltf.json"
    profile_path.parent.mkdir(parents=True)
    write_model(profile_path, profile)
    source = _source_provenance()
    preflight = MeshPreflightReport(
        report_id=f"preflight.{run_id}",
        job_id=job_id,
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
                target_id="asset.body",
                source_tags=[],
                source_renderable=True,
                object_count=1,
                vertex_count=8,
                triangle_count=12,
                boundary_edge_count=0,
                non_manifold_edge_count=0,
                degenerate_face_count=0,
                negative_scale_count=0,
                bounds=Bounds3D(minimum=(0, 0, 0), maximum=(1, 1, 1)),
            )
        ],
        created_at=NOW,
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
        "codex_blender_modeler.optimization.optimizer.job_dir", lambda _job: root
    )
    monkeypatch.setattr(
        "codex_blender_modeler.optimization.optimizer.load_asset_profile",
        lambda _root, _profile: profile,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.optimization.optimizer.collect_source_provenance",
        lambda _root, _job: source,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.optimization.optimizer._load_or_run_preflight",
        lambda _job, _profile, _run: (run_id, preflight, run_root),
    )
    optimization_review = plan_asset_optimization(
        job_id,
        profile_id="portable_gltf",
        run_id=run_id,
    )
    approve_asset_optimization(
        job_id,
        run_id=run_id,
        plan_sha256=optimization_review.plan_sha256,
        approval_note="Exact AQ v2 delivery test approval.",
    )
    profile_binding = artifact_for_v2(
        root,
        profile_path,
        artifact_id="delivery-glb-profile",
        kind="asset_profile",
    )
    plan_binding = artifact_for_v2(
        root,
        run_root / "review_plan.json",
        artifact_id="delivery-glb-plan",
        kind="optimization_plan",
    )
    review_binding = artifact_for_v2(
        root,
        run_root / "optimization_review.json",
        artifact_id="delivery-glb-review",
        kind="optimization_review",
    )
    source_freeze = _aq_artifact("freeze", "quality_source_freeze")
    request = DeliveryRequest(
        delivery_id="delivery-glb",
        profile=delivery_profile("portable_gltf"),
        source_freeze=source_freeze,
        run_id=run_id,
        package_id="delivery-package-glb",
        status="awaiting_optimization_approval",
    )
    entry = DeliveryReviewEntry(
        delivery_id=request.delivery_id,
        profile_id="portable_gltf",
        asset_profile_id="portable_gltf",
        run_id=run_id,
        package_id="delivery-package-glb",
        asset_profile=profile_binding,
        optimization_plan=plan_binding,
        optimization_review=review_binding,
        exact_plan_sha256=plan_binding.sha256,
    )
    freeze = SimpleNamespace(job_id=job_id, v07_source_fingerprint="3" * 64)
    return request, entry, freeze


def test_exact_approval_validator_accepts_only_unused_matching_user_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept the real exact approval once and reject it after consumption."""

    root = tmp_path / "aq_v2_exec"
    root.mkdir()
    request, review, freeze = _prepare_real_approval(root, monkeypatch)
    approval = _validate_unused_exact_approval(
        root=root,
        freeze=freeze,
        request=request,
        review=review,
    )
    assert approval.used is False

    approval_path = root / "optimization" / "runs" / request.run_id / "optimization_approval.json"
    consumed = approval.model_copy(update={"used": True, "used_at": NOW})
    write_model(approval_path, OptimizationApproval.model_validate(consumed))
    with pytest.raises(RuntimeError, match="does not match the exact review"):
        _validate_unused_exact_approval(
            root=root,
            freeze=freeze,
            request=request,
            review=review,
        )


def test_consumed_approval_recovery_requires_exact_complete_optimization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept a consumed approval only with a complete, rehashed V0.7 output plan."""

    root = tmp_path / "aq_v2_exec"
    root.mkdir()
    request, review, freeze = _prepare_real_approval(root, monkeypatch)
    assert request.run_id is not None
    run_root = root / "optimization" / "runs" / request.run_id
    approval_path = run_root / "optimization_approval.json"
    approval = OptimizationApproval.model_validate_json(approval_path.read_bytes())
    consumed = OptimizationApproval.model_validate(
        approval.model_copy(update={"used": True, "used_at": NOW})
    )
    write_model(approval_path, consumed)
    reviewed = load_model(run_root / "review_plan.json", OptimizationPlan)
    optimized = run_root / "optimized" / "scene.blend"
    optimized.parent.mkdir()
    optimized.write_bytes(b"complete-optimized-output")
    output = HashedArtifact(
        id="blend.optimized.recovery",
        kind="blend",
        path=optimized.relative_to(root).as_posix(),
        sha256=sha256_file(optimized),
    )
    completed = reviewed.model_copy(
        update={
            "status": "complete",
            "approved_at": approval.approved_at,
            "completed_at": NOW,
            "output_manifests": [output],
            "notes": [*reviewed.notes, "completed recovery fixture"],
        }
    )
    write_model(run_root / "optimization_plan.json", completed)
    recovered_plan, recovered_approval = _validate_consumed_exact_approval(
        root=root,
        freeze=freeze,
        request=request,
        review=review,
    )
    assert recovered_plan.status == "complete"
    assert recovered_approval.used is True

    optimized.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="output no longer matches"):
        _validate_consumed_exact_approval(
            root=root,
            freeze=freeze,
            request=request,
            review=review,
        )


def _execution_contracts() -> tuple[
    DeliveryPlan,
    AQV2Artifact,
    DeliveryReviewBinding,
    AQV2Artifact,
    SimpleNamespace,
]:
    """Create one dual-format plan and exact review binding without workspace writes."""

    plan_artifact = _aq_artifact("delivery-plan", "delivery_plan")
    review_artifact = _aq_artifact("delivery-reviews", "delivery_review")
    freeze_artifact = _aq_artifact("quality-freeze", "quality_source_freeze")
    root_authorization = _aq_artifact("root-authorization", "root_authorization")
    requests = [
        DeliveryRequest(
            delivery_id=f"delivery-{suffix}",
            profile=delivery_profile(profile_id),
            source_freeze=freeze_artifact,
            run_id=f"run-{suffix}",
            package_id=f"package-{suffix}",
            status="awaiting_optimization_approval",
        )
        for profile_id, suffix in (
            ("portable_gltf", "glb"),
            ("portable_fbx", "fbx"),
        )
    ]
    plan = DeliveryPlan(
        contract_id="delivery-plan",
        job_id="aq_v2_delivery_exec",
        workflow_id="wf-aq-v2-delivery-exec",
        dispatch_id="dispatch-aq-v2-delivery-exec",
        session_id="session-aq-v2-delivery-exec",
        input_sha256=_digest("plan-input"),
        source_fingerprint=_digest("plan-source"),
        producer="tests.autonomy_v2.delivery_executor",
        provenance=[root_authorization, freeze_artifact],
        created_at=NOW,
        plan_id="delivery-plan",
        root_authorization=root_authorization,
        source_freeze=freeze_artifact,
        requests=requests,
    )
    entries: list[DeliveryReviewEntry] = []
    for request in requests:
        assert request.run_id is not None
        assert request.package_id is not None
        assert request.profile.asset_profile_id is not None
        reviewed_plan = _aq_artifact(
            f"{request.delivery_id}-plan", "optimization_plan"
        )
        entries.append(
            DeliveryReviewEntry(
                delivery_id=request.delivery_id,
                profile_id=request.profile.profile_id,
                asset_profile_id=request.profile.asset_profile_id,
                run_id=request.run_id,
                package_id=request.package_id,
                asset_profile=_aq_artifact(
                    f"{request.delivery_id}-profile", "asset_profile"
                ),
                optimization_plan=reviewed_plan,
                optimization_review=_aq_artifact(
                    f"{request.delivery_id}-review", "optimization_review"
                ),
                exact_plan_sha256=reviewed_plan.sha256,
            )
        )
    binding = DeliveryReviewBinding(
        contract_id="delivery-reviews",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=_digest("review-input"),
        source_fingerprint=_digest("review-source"),
        producer="tests.autonomy_v2.delivery_executor",
        provenance=[plan_artifact, freeze_artifact],
        created_at=NOW,
        binding_id="delivery-reviews",
        delivery_plan=plan_artifact,
        source_freeze=freeze_artifact,
        entries=entries,
    )
    freeze = SimpleNamespace(
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        v07_source_fingerprint="5" * 64,
    )
    return plan, plan_artifact, binding, review_artifact, freeze


def _snapshot(
    *,
    stage: str,
    artifact_path: str,
    artifact_sha256: str,
    source_fingerprint_sha256: str,
    build_fingerprint_sha256: str,
) -> GeometryStageSnapshotV02:
    """Create one stable aggregate delivery snapshot for mocked Blender inspection."""

    fingerprint = GeometryEvidenceFingerprintV02(
        status="available",
        sha256=_digest("shared-geometry"),
        reason=None,
    )
    return GeometryStageSnapshotV02(
        stage=stage,
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        source_fingerprint_sha256=source_fingerprint_sha256,
        build_fingerprint_sha256=build_fingerprint_sha256,
        semantic_id="asset.aggregate",
        topology_profile="static_prop_closed",
        vertex_count=8,
        face_count=6,
        loop_count=24,
        evaluated_triangle_count=12,
        topology_fingerprint=fingerprint,
        surface_equivalence_fingerprint=fingerprint,
        uv_fingerprint=fingerprint,
        material_slots_fingerprint=fingerprint,
        polygon_material_fingerprint=fingerprint,
        split_normal_fingerprint=fingerprint,
        sharp_edge_fingerprint=fingerprint,
        uv_seam_fingerprint=fingerprint,
        crease_fingerprint=fingerprint,
        bevel_fingerprint=fingerprint,
        smoothing_fingerprint=fingerprint,
        modifier_fingerprint=fingerprint,
        custom_attribute_fingerprint=fingerprint,
    )


def test_missing_optimization_approval_fails_without_starting_v07(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return a format failure without inventing approval or invoking optimization."""

    root = tmp_path / "aq_v2_delivery_exec"
    root.mkdir()
    plan, _plan_artifact, binding, _review_artifact, freeze = _execution_contracts()
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.validate_quality_source_freeze",
        lambda _root, value: value is freeze,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.optimize_asset",
        lambda *_args, **_kwargs: pytest.fail(
            "optimization must not start without an existing exact approval"
        ),
    )
    result = _execute_portable_request(
        root=root,
        freeze=freeze,
        source_freeze_artifact=plan.source_freeze,
        request=plan.requests[0],
        review=binding.entries[0],
    )
    assert result.status == "failed"
    assert result.optimization_approval is None
    assert result.package_manifest is None
    assert result.production_ready is False
    assert "FileNotFoundError" in result.errors[0]


def test_consumed_approval_adopts_completed_result_without_reexecution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route a consumed approval to exact adoption and never invoke V0.7 again."""

    root = tmp_path / "aq_v2_delivery_exec"
    root.mkdir()
    plan, _plan_artifact, binding, _review_artifact, freeze = _execution_contracts()
    request = plan.requests[0]
    review = binding.entries[0]
    assert request.run_id is not None
    approval_path = (
        root / "optimization" / "runs" / request.run_id / "optimization_approval.json"
    )
    approval_path.parent.mkdir(parents=True)
    approval = OptimizationApproval(
        approval_id=f"approval.{request.run_id}",
        job_id=plan.job_id,
        run_id=request.run_id,
        profile_id="portable_gltf",
        plan_sha256=review.exact_plan_sha256,
        review_sha256=review.optimization_review.sha256,
        profile_sha256=review.asset_profile.sha256,
        preflight_sha256="7" * 64,
        source_fingerprint=freeze.v07_source_fingerprint,
        approval_note="Previously consumed exact approval.",
        approved_at=NOW,
        used=True,
        used_at=NOW,
    )
    write_model(approval_path, approval)
    adopted = DeliveryResult(
        delivery_id=request.delivery_id,
        profile_id="portable_gltf",
        status="completed",
        source_freeze_sha256=plan.source_freeze.sha256,
        optimization_plan=review.optimization_plan,
        optimization_approval=_aq_artifact("used-approval", "optimization_approval"),
        package_manifest=_aq_artifact("adopted-package", "package_manifest"),
        roundtrip_validation=_aq_artifact("adopted-roundtrip", "roundtrip_validation"),
        material_loss_report=_aq_artifact("adopted-material", "material_loss_report"),
        geometry_survival_report=_aq_artifact(
            "adopted-survival", "geometry_survival_report"
        ),
        production_ready=True,
    )
    adopted_calls: list[str] = []

    def adopt(**kwargs) -> DeliveryResult:
        """Record the exact recovery request and return its verified result fixture."""

        assert kwargs["request"] is request
        assert kwargs["review"] is review
        adopted_calls.append(request.delivery_id)
        return adopted

    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.validate_quality_source_freeze",
        lambda _root, value: value is freeze,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor._adopt_completed_portable_request",
        adopt,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.optimize_asset",
        lambda *_args, **_kwargs: pytest.fail(
            "a consumed approval must never invoke optimization again"
        ),
    )
    result = _execute_portable_request(
        root=root,
        freeze=freeze,
        source_freeze_artifact=plan.source_freeze,
        request=request,
        review=review,
    )
    assert result == adopted
    assert adopted_calls == [request.delivery_id]


def test_completed_delivery_adoption_rehashes_package_and_geometry_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconstruct a completed result and reject later primary-package tampering."""

    root = tmp_path / "aq_v2_delivery_exec"
    root.mkdir()
    plan, _plan_artifact, binding, _review_artifact, freeze = _execution_contracts()
    request = plan.requests[0]
    review = binding.entries[0]
    assert request.run_id is not None
    assert request.package_id is not None
    assert request.profile.asset_profile_id is not None
    run_root = root / "optimization" / "runs" / request.run_id
    geometry_root = run_root / "aq_v2" / "geometry"
    geometry_root.mkdir(parents=True)
    approval_path = run_root / "optimization_approval.json"
    approval_path.parent.mkdir(parents=True, exist_ok=True)
    approval_path.write_text('{"used":true}\n', encoding="utf-8")
    conversion_blend = (
        root
        / "optimization"
        / "material_conversions"
        / request.run_id
        / f"{request.delivery_id}-materials"
        / "converted"
        / "scene.blend"
    )
    conversion_blend.parent.mkdir(parents=True)
    conversion_blend.write_bytes(b"portable-source-blend")
    package_root = (
        root
        / "exports"
        / "packages"
        / request.profile.asset_profile_id
        / request.package_id
    )
    package_root.mkdir(parents=True)
    primary = package_root / "asset.glb"
    primary.write_bytes(b"clean-import-package")
    package_path = package_root / "package_manifest.json"
    package_path.write_text('{"status":"complete"}\n', encoding="utf-8")
    material_path = package_root / "metadata" / "conversion_manifest.json"
    material_path.parent.mkdir()
    material_path.write_text('{"status":"complete"}\n', encoding="utf-8")
    roundtrip_path = (
        run_root
        / "roundtrip"
        / request.package_id
        / "roundtrip_validation.json"
    )
    roundtrip_path.parent.mkdir(parents=True)
    roundtrip_path.write_text('{"status":"passed"}\n', encoding="utf-8")
    optimized_snapshot = _snapshot(
        stage="optimized_lod0",
        artifact_path=conversion_blend.relative_to(root).as_posix(),
        artifact_sha256=sha256_file(conversion_blend),
        source_fingerprint_sha256=freeze.v07_source_fingerprint,
        build_fingerprint_sha256="6" * 64,
    )
    imported_snapshot = _snapshot(
        stage="clean_import_glb",
        artifact_path=primary.relative_to(root).as_posix(),
        artifact_sha256=sha256_file(primary),
        source_fingerprint_sha256=freeze.v07_source_fingerprint,
        build_fingerprint_sha256="6" * 64,
    )
    optimized_snapshot_path = geometry_root / "optimized_lod0_snapshot.json"
    imported_snapshot_path = geometry_root / "clean_import_glb_snapshot.json"
    optimized_snapshot_path.write_text(
        optimized_snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    imported_snapshot_path.write_text(
        imported_snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    survival = compare_geometry_stage_snapshots_v02(
        report_id=f"survival-{request.delivery_id}-optimized-clean-import",
        relation="optimized_to_clean_import",
        source=optimized_snapshot,
        target=imported_snapshot,
        package_format="GLB",
    )
    survival_path = geometry_root / "optimized_to_clean_import_report.json"
    survival_path.write_text(
        survival.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    primary_receipt = SimpleNamespace(
        id="primary",
        kind="primary_asset",
        path=primary.relative_to(root).as_posix(),
        sha256=sha256_file(primary),
        byte_size=primary.stat().st_size,
    )
    package = SimpleNamespace(
        primary_file_id="primary",
        files=[primary_receipt],
        material_conversion=SimpleNamespace(
            path=material_path.relative_to(root).as_posix(),
            sha256=sha256_file(material_path),
        ),
        known_losses=[],
    )
    completed_plan = SimpleNamespace(
        source=SimpleNamespace(build_fingerprint="6" * 64)
    )
    loaded = {
        package_path: package,
        roundtrip_path: SimpleNamespace(status="passed"),
        optimized_snapshot_path: optimized_snapshot,
        imported_snapshot_path: imported_snapshot,
        survival_path: survival,
    }
    package_validations: list[str] = []

    def load_existing(path: Path, _model):
        """Return the strict fixture associated with one exact expected path."""

        return loaded[path]

    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor._validate_consumed_exact_approval",
        lambda **_kwargs: (completed_plan, SimpleNamespace(used=True)),
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.validate_quality_source_freeze",
        lambda _root, value: value is freeze,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.load_asset_profile",
        lambda _root, profile_id: SimpleNamespace(profile_id=profile_id),
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.load_portable_material_conversion",
        lambda *_args, **_kwargs: SimpleNamespace(portable_blend=conversion_blend),
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor._load_job_model",
        load_existing,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor._validate_package_result",
        lambda _root, _freeze, _request, _review, result: package_validations.append(
            result.delivery_id
        ),
    )
    result = _adopt_completed_portable_request(
        root=root,
        freeze=freeze,
        source_freeze_artifact=plan.source_freeze,
        request=request,
        review=review,
    )
    assert result.status == "completed"
    assert package_validations == [request.delivery_id]

    primary.write_bytes(b"tampered-package")
    with pytest.raises(ValueError, match="geometry stage artifact hash is stale"):
        _adopt_completed_portable_request(
            root=root,
            freeze=freeze,
            source_freeze_artifact=plan.source_freeze,
            request=request,
            review=review,
        )


def test_dual_delivery_preserves_format_failure_and_uses_independent_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep a GLB packaging failure while completing FBX from its own optimized run."""

    root = tmp_path / "aq_v2_delivery_exec"
    root.mkdir()
    plan, plan_artifact, binding, review_artifact, freeze = _execution_contracts()
    calls: list[tuple[str, str, str]] = []
    freeze_checks: list[str] = []

    def load_bound(_root: Path, _artifact: AQV2Artifact, model):
        """Return the exact in-memory contract selected by its requested model."""

        return {
            DeliveryPlan: plan,
            DeliveryReviewBinding: binding,
        }.get(model, freeze)

    def validate_freeze(_root: Path, value: SimpleNamespace) -> None:
        """Record that every stage revalidates the same direct source freeze."""

        assert value is freeze
        freeze_checks.append(value.v07_source_fingerprint)

    def fake_optimize(
        job_id: str,
        *,
        profile_id: str,
        run_id: str,
        approved_plan_sha256: str,
    ) -> SimpleNamespace:
        """Publish a consumed-approval marker and return a completed direct run."""

        calls.append(("optimize", profile_id, run_id))
        assert approved_plan_sha256 == next(
            entry.exact_plan_sha256
            for entry in binding.entries
            if entry.run_id == run_id
        )
        approval_path = root / "optimization" / "runs" / run_id / "optimization_approval.json"
        approval_path.parent.mkdir(parents=True, exist_ok=True)
        approval_path.write_text('{"used":true}\n', encoding="utf-8")
        return SimpleNamespace(
            status="complete",
            job_id=job_id,
            profile_id=profile_id,
            source=SimpleNamespace(
                source_fingerprint=freeze.v07_source_fingerprint,
                build_fingerprint="6" * 64,
            ),
        )

    def fake_conversion(
        job_id: str,
        *,
        profile_id: str,
        run_id: str,
        conversion_id: str,
    ) -> SimpleNamespace:
        """Publish one independent portable blend and conversion manifest."""

        calls.append(("convert", profile_id, run_id))
        directory = (
            root
            / "optimization"
            / "material_conversions"
            / run_id
            / conversion_id
        )
        directory.mkdir(parents=True)
        (directory / "conversion_manifest.json").write_text(
            '{"status":"complete"}\n', encoding="utf-8"
        )
        blend = directory / "converted" / "scene.blend"
        blend.parent.mkdir()
        blend.write_bytes(f"portable-{profile_id}".encode())
        return SimpleNamespace(
            status="complete",
            job_id=job_id,
            run_id=run_id,
            profile_id=profile_id,
            source=SimpleNamespace(source_fingerprint=freeze.v07_source_fingerprint),
            missing_material_ids=[],
            portable_blend=SimpleNamespace(path=blend.relative_to(root).as_posix()),
        )

    def fake_inspect(**kwargs) -> GeometryStageSnapshotV02:
        """Publish the requested stage snapshot and record the inspected artifact."""

        artifact = root / kwargs["artifact_relative_path"]
        output = root / kwargs["output_relative_path"]
        snapshot = _snapshot(
            stage=kwargs["stage"],
            artifact_path=kwargs["artifact_relative_path"],
            artifact_sha256=sha256_file(artifact),
            source_fingerprint_sha256=kwargs["source_fingerprint_sha256"],
            build_fingerprint_sha256=kwargs["build_fingerprint_sha256"],
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
        calls.append(("inspect", kwargs["stage"], kwargs["artifact_relative_path"]))
        return snapshot

    def fake_package(
        job_id: str,
        *,
        profile_id: str,
        run_id: str,
        package_id: str,
        material_conversion_id: str,
    ) -> SimpleNamespace:
        """Fail GLB only and publish one independent FBX package receipt."""

        calls.append(("package", profile_id, run_id))
        assert material_conversion_id.endswith("-materials")
        if profile_id == "portable_gltf":
            raise RuntimeError(f"GLB fixture failed inside {root}")
        package_root = root / "exports" / "packages" / profile_id / package_id
        package_root.mkdir(parents=True)
        primary = package_root / "model.fbx"
        primary.write_bytes(b"independent-fbx")
        (package_root / "package_manifest.json").write_text(
            '{"status":"complete"}\n', encoding="utf-8"
        )
        material_snapshot = package_root / "metadata" / "conversion_manifest.json"
        material_snapshot.parent.mkdir()
        material_snapshot.write_text(
            '{"status":"complete"}\n', encoding="utf-8"
        )
        primary_receipt = SimpleNamespace(
            id="primary",
            kind="primary_asset",
            path=primary.relative_to(root).as_posix(),
            sha256=sha256_file(primary),
            byte_size=primary.stat().st_size,
        )
        return SimpleNamespace(
            status="complete",
            job_id=job_id,
            run_id=run_id,
            package_id=package_id,
            profile_id=profile_id,
            source=SimpleNamespace(source_fingerprint=freeze.v07_source_fingerprint),
            primary_file_id="primary",
            files=[primary_receipt],
            material_conversion=SimpleNamespace(
                path=material_snapshot.relative_to(root).as_posix(),
                sha256=sha256_file(material_snapshot),
            ),
            known_losses=[],
        )

    def fake_roundtrip(
        job_id: str,
        package_id: str,
        *,
        profile_id: str,
    ) -> SimpleNamespace:
        """Publish one passed FBX roundtrip validation fixture."""

        run_id = "run-fbx"
        calls.append(("roundtrip", profile_id, run_id))
        path = (
            root
            / "optimization"
            / "runs"
            / run_id
            / "roundtrip"
            / package_id
            / "roundtrip_validation.json"
        )
        path.parent.mkdir(parents=True)
        path.write_text('{"status":"passed"}\n', encoding="utf-8")
        package_manifest = (
            root
            / "exports"
            / "packages"
            / profile_id
            / package_id
            / "package_manifest.json"
        )
        return SimpleNamespace(
            status="passed",
            ok=True,
            job_id=job_id,
            run_id=run_id,
            package_id=package_id,
            profile_id=profile_id,
            package_manifest=SimpleNamespace(
                path=package_manifest.relative_to(root).as_posix(),
                sha256=sha256_file(package_manifest),
            ),
        )

    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor._load_bound_model",
        load_bound,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.job_dir", lambda _job: root
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.validate_quality_source_freeze",
        validate_freeze,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.validate_delivery_plan_authority_v2",
        lambda _root, _plan, _artifact: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor._validate_unused_exact_approval",
        lambda **_kwargs: SimpleNamespace(used=False),
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.optimize_asset",
        fake_optimize,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.convert_portable_materials",
        fake_conversion,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.package_asset",
        fake_package,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.validate_asset_package",
        fake_roundtrip,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_executor.inspect_delivery_geometry_stage_v02",
        fake_inspect,
    )

    results = execute_approved_delivery_plan_v2(
        job_root=root,
        delivery_plan_artifact=plan_artifact,
        delivery_review_artifact=review_artifact,
    )

    assert [result.status for result in results] == ["failed", "completed"]
    assert results[0].profile_id == "portable_gltf"
    assert "<job_root>" in results[0].errors[0]
    assert str(root) not in results[0].errors[0]
    assert results[1].profile_id == "portable_fbx"
    assert results[1].production_ready is True
    assert results[1].geometry_survival_report is not None
    assert (root / results[1].geometry_survival_report.path).is_file()
    assert [call for call in calls if call[0] == "optimize"] == [
        ("optimize", "portable_gltf", "run-glb"),
        ("optimize", "fbx_interchange", "run-fbx"),
    ]
    assert any(
        call[0] == "inspect"
        and call[1] == "clean_import_fbx"
        and call[2].endswith("model.fbx")
        for call in calls
    )
    assert not any(
        call[0] == "inspect"
        and call[1] == "clean_import_fbx"
        and call[2].endswith(".glb")
        for call in calls
    )
    assert len(freeze_checks) >= 7
