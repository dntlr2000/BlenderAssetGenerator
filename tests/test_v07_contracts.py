"""Focused validation tests for engine-neutral V0.7 portable-asset contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from codex_blender_modeler.optimization.models import (
    AssetCostReduction,
    AssetCostSnapshot,
    AssetProfile,
    Bounds3D,
    CollisionEntry,
    CollisionManifest,
    ConsolidationBatch,
    HashedArtifact,
    LODEntry,
    LODManifest,
    MeshPreflightCheck,
    MeshPreflightReport,
    MeshSummary,
    OptimizationDirective,
    OptimizationPlan,
    SourceProvenance,
    StaticAssetCostReport,
    UVManifest,
    UVSetRecord,
)
from codex_blender_modeler.packaging.models import (
    BoundsComparison,
    ExportPackageManifest,
    PackageFile,
    PackedTexture,
    RoundTripCheck,
    RoundTripValidation,
    TextureChannelMapping,
    TexturePackManifest,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def _artifact(
    artifact_id: str,
    kind: str,
    path: str,
    digest: str = "a" * 64,
) -> HashedArtifact:
    """Create one deterministic artifact fixture with a valid digest."""

    return HashedArtifact(id=artifact_id, kind=kind, path=path, sha256=digest)


def _provenance() -> SourceProvenance:
    """Create canonical source provenance shared by contract fixtures."""

    return SourceProvenance(
        scene_spec=_artifact("scene-spec", "scene_spec", "analysis/scene_spec.json"),
        blend=_artifact("source-blend", "blend", "blender/scene.blend", "b" * 64),
        source_fingerprint="f" * 64,
        build_fingerprint="c" * 64,
        geometry_payloads=[
            _artifact(
                "geometry-body",
                "geometry_payload",
                "geometry/body.mesh.json",
                "d" * 64,
            )
        ],
    )


def _bounds() -> Bounds3D:
    """Return one finite positive-size bounds fixture."""

    return Bounds3D(minimum=(-1.0, -1.0, 0.0), maximum=(1.0, 1.0, 2.0))


@pytest.mark.parametrize(
    ("profile_id", "primary_format"),
    [
        ("portable_gltf", "glb"),
        ("fbx_interchange", "fbx"),
        ("obj_legacy", "obj"),
    ],
)
def test_asset_profiles_are_engine_neutral_and_format_bound(
    profile_id: str, primary_format: str
) -> None:
    """Accept only the three V0.7 profiles with their declared interchange format."""

    profile = AssetProfile(
        profile_id=profile_id,
        job_id="portable_prop",
        asset_kind="static_prop",
        primary_format=primary_format,
    )
    assert profile.schema_version == "0.7.0"
    assert profile.textures.preserve_raw_channels is True

    with pytest.raises(ValidationError, match="requires primary_format"):
        AssetProfile(
            profile_id=profile_id,
            job_id="portable_prop",
            asset_kind="static_prop",
            primary_format="glb" if primary_format != "glb" else "fbx",
        )


def test_v073_profile_defaults_preserve_legacy_unbatched_behavior() -> None:
    """Parse a V0.7.2-shaped profile without implicitly changing its derived geometry."""

    payload = AssetProfile(
        profile_id="portable_gltf",
        job_id="portable_prop",
        asset_kind="static_prop",
        primary_format="glb",
    ).model_dump(mode="json")
    payload.pop("consolidation")
    payload.pop("budgets")
    legacy = AssetProfile.model_validate(payload)
    assert legacy.consolidation.mode == "none"
    assert legacy.budgets.enforcement == "warning"


def test_v073_cost_report_tracks_lossless_semantic_batching() -> None:
    """Require exact triangle preservation and honest partially verified cost evidence."""

    before = AssetCostSnapshot(
        lod0_render_objects=4,
        lod0_material_slots=4,
        lod0_estimated_draw_calls=4,
        lod0_vertices=32,
        lod0_triangles=48,
        lod_objects=8,
        collider_objects=4,
        collider_triangles=48,
        total_derived_triangles=192,
        unique_materials=1,
        overlap_candidates=2,
    )
    after = before.model_copy(
        update={
            "lod0_render_objects": 1,
            "lod0_material_slots": 1,
            "lod0_estimated_draw_calls": 1,
        }
    )
    batch = ConsolidationBatch(
        batch_id="batch.0001",
        semantic_id="building.window",
        lod_level=0,
        material_ids=["mat.glass"],
        source_objects=["window.001", "window.002", "window.003", "window.004"],
        output_object="CBM_building_window__LOD0__BATCH0001",
        object_count_before=4,
        triangle_count_before=48,
        triangle_count_after=48,
        material_slots_before=4,
        material_slots_after=1,
    )
    report = StaticAssetCostReport(
        report_id="cost.run-001",
        job_id="portable_prop",
        run_id="run-001",
        profile_id="portable_gltf",
        source=_provenance(),
        status="passed",
        ok=True,
        before=before,
        after=after,
        reductions=[
            AssetCostReduction(
                metric="lod0_render_objects",
                before=4,
                after=1,
                reduction=3,
                reduction_fraction=0.75,
            )
        ],
        consolidation_batches=[batch],
        created_at=NOW,
    )
    assert report.canonical_unchanged is True
    assert report.quality_status == "partially_verified"

    with pytest.raises(ValidationError, match="retain triangle count"):
        ConsolidationBatch.model_validate(
            {**batch.model_dump(), "triangle_count_after": 47}
        )


@pytest.mark.parametrize(
    "path",
    [
        "C:/outside/file.json",
        "/absolute/file.json",
        "../escape.json",
        "a/../escape.json",
        "a\\b",
        "textures/source.png:payload",
    ],
)
def test_artifact_paths_must_be_normalized_job_relative(path: str) -> None:
    """Reject absolute, traversal, and Windows-style paths before package execution."""

    with pytest.raises(ValidationError, match="path"):
        _artifact("unsafe", "other", path)


def test_strict_contracts_reject_extra_fields_and_invalid_digests() -> None:
    """Reject undeclared data and non-SHA-256 provenance at every public boundary."""

    with pytest.raises(ValidationError, match="Extra inputs"):
        HashedArtifact(
            id="artifact",
            kind="other",
            path="reports/artifact.json",
            sha256="a" * 64,
            unexpected=True,
        )
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        _artifact("artifact", "other", "reports/artifact.json", "not-a-digest")


def test_optimization_plan_enforces_unique_targets_and_lifecycle() -> None:
    """Bind optimization directives and output manifests to an explicit approval lifecycle."""

    profile = _artifact("profile", "asset_profile", "asset_profiles/portable_gltf.json")
    preflight = _artifact(
        "preflight",
        "preflight_report",
        "optimization/runs/preflight-001/mesh_preflight_report.json",
    )
    directive = OptimizationDirective(target_id="building.body", lod_levels=[1, 2])
    draft = OptimizationPlan(
        plan_id="plan-001",
        job_id="portable_prop",
        profile_id="portable_gltf",
        profile_artifact=profile,
        preflight_report=preflight,
        source=_provenance(),
        directives=[directive],
    )
    assert draft.status == "draft"

    with pytest.raises(ValidationError, match="target IDs must be unique"):
        OptimizationPlan(
            plan_id="plan-duplicate",
            job_id="portable_prop",
            profile_id="portable_gltf",
            profile_artifact=profile,
            preflight_report=preflight,
            source=_provenance(),
            directives=[directive, directive],
        )
    with pytest.raises(ValidationError, match="requires approval, completion, and outputs"):
        OptimizationPlan(
            plan_id="plan-incomplete",
            job_id="portable_prop",
            profile_id="portable_gltf",
            profile_artifact=profile,
            preflight_report=preflight,
            source=_provenance(),
            status="complete",
            directives=[directive],
        )


def test_mesh_preflight_report_counts_and_status_are_derived_from_checks() -> None:
    """Keep preflight summary state consistent with stable check evidence."""

    check = MeshPreflightCheck(
        id="topology-body",
        target_id="building.body",
        category="topology",
        status="passed",
        message="Topology passed",
    )
    mesh = MeshSummary(
        target_id="building.body",
        object_count=1,
        vertex_count=8,
        triangle_count=12,
        boundary_edge_count=0,
        non_manifold_edge_count=0,
        degenerate_face_count=0,
        negative_scale_count=0,
        bounds=_bounds(),
    )
    report = MeshPreflightReport(
        report_id="preflight-001",
        job_id="portable_prop",
        profile_id="portable_gltf",
        profile_artifact=_artifact(
            "profile",
            "asset_profile",
            "asset_profiles/portable_gltf.json",
        ),
        source=_provenance(),
        status="passed",
        ok=True,
        passed=1,
        warnings=0,
        failed=0,
        checks=[check],
        meshes=[mesh],
        created_at=NOW,
    )
    assert report.canonical_unchanged is True

    with pytest.raises(ValidationError, match="summary counts"):
        report.model_copy(update={"passed": 0}, deep=True).__class__.model_validate(
            {**report.model_dump(), "passed": 0}
        )


def test_complete_lod_manifest_requires_lod0_and_nonincreasing_complexity() -> None:
    """Preserve LOD0 exactly and reject gaps or increasing derived mesh complexity."""

    lod0 = LODEntry(
        target_id="building.body",
        level=0,
        mesh=_artifact("body-lod0", "lod_mesh", "optimization/run/lod/body_lod0.glb"),
        source_triangle_count=100,
        triangle_count=100,
        triangle_ratio=1,
        silhouette_iou=1,
        bounds=_bounds(),
        material_ids=["mat.stone"],
    )
    lod1 = LODEntry(
        target_id="building.body",
        level=1,
        mesh=_artifact("body-lod1", "lod_mesh", "optimization/run/lod/body_lod1.glb", "b" * 64),
        source_triangle_count=100,
        triangle_count=60,
        triangle_ratio=0.6,
        silhouette_iou=0.99,
        bounds=_bounds(),
        material_ids=["mat.stone"],
    )
    manifest = LODManifest(
        manifest_id="lod-manifest",
        job_id="portable_prop",
        run_id="run-001",
        profile_id="portable_gltf",
        source=_provenance(),
        status="complete",
        entries=[lod0, lod1],
        created_at=NOW,
        completed_at=NOW,
    )
    assert len(manifest.entries) == 2

    with pytest.raises(ValidationError, match="consecutive from zero"):
        LODManifest(
            manifest_id="lod-gapped",
            job_id="portable_prop",
            run_id="run-002",
            profile_id="portable_gltf",
            source=_provenance(),
            status="complete",
            entries=[lod1],
            created_at=NOW,
            completed_at=NOW,
        )


def test_collision_and_uv_manifests_preserve_stable_ownership() -> None:
    """Validate semantic collider ownership and unique object/UV-set pairs."""

    collider = CollisionEntry(
        collider_id="body-collider",
        target_id="building.body",
        strategy="box",
        dimensions=(2.0, 2.0, 2.0),
    )
    collision = CollisionManifest(
        manifest_id="collision-manifest",
        job_id="portable_prop",
        run_id="run-001",
        profile_id="portable_gltf",
        source=_provenance(),
        strategy="box",
        status="complete",
        entries=[collider],
        created_at=NOW,
        completed_at=NOW,
    )
    assert collision.entries[0].target_id == "building.body"

    uv_record = UVSetRecord(
        target_id="building.body",
        uv_set="UVMap",
        purpose="material",
        generated=False,
        degenerate_face_count=0,
        texel_density_px_m=512,
        padding_px=8,
    )
    assert uv_record.overlap_fraction is None
    with pytest.raises(ValidationError, match="pairs must be unique"):
        UVManifest(
            manifest_id="uv-duplicate",
            job_id="portable_prop",
            run_id="run-001",
            profile_id="portable_gltf",
            source=_provenance(),
            status="complete",
            records=[uv_record, uv_record],
            created_at=NOW,
            completed_at=NOW,
        )


def _orm_texture() -> PackedTexture:
    """Create one correctly mapped glTF ORM texture fixture."""

    channels = [
        ("R", "occlusion", "ao"),
        ("G", "roughness", "roughness"),
        ("B", "metallic", "metallic"),
    ]
    return PackedTexture(
        texture_id="mat-stone-orm",
        material_ids=["mat.stone"],
        packing="gltf_orm",
        output=_artifact(
            "mat-stone-orm-output",
            "packed_texture",
            "exports/packages/portable_gltf/pkg/textures/mat_stone_orm.png",
        ),
        color_space="Non-Color",
        width=1024,
        height=1024,
        mappings=[
            TextureChannelMapping(
                output_channel=output,
                source_channel=source,
                source=_artifact(
                    f"mat-stone-{artifact_id}",
                    "other",
                    f"textures/mat.stone/{artifact_id}.png",
                    chr(ord("b") + index) * 64,
                ),
            )
            for index, (output, source, artifact_id) in enumerate(channels)
        ],
    )


def test_texture_pack_manifest_preserves_raw_channels_and_gltf_semantics() -> None:
    """Require raw-channel preservation and exact R=AO/G=roughness/B=metallic packing."""

    texture = _orm_texture()
    manifest = TexturePackManifest(
        manifest_id="texture-pack",
        job_id="portable_prop",
        run_id="run-001",
        profile_id="portable_gltf",
        source=_provenance(),
        status="complete",
        textures=[texture],
        created_at=NOW,
        completed_at=NOW,
    )
    assert manifest.raw_channels_preserved is True

    invalid = texture.model_dump()
    invalid["mappings"][0]["source_channel"] = "metallic"
    with pytest.raises(ValidationError, match="R=occlusion"):
        PackedTexture.model_validate(invalid)


def test_export_package_and_roundtrip_require_complete_portable_evidence() -> None:
    """Accept a hash-complete GLB receipt only when clean reimport preserves IDs and bounds."""

    package_file = PackageFile(
        id="primary-glb",
        kind="primary_asset",
        path="exports/packages/portable_gltf/pkg-001/asset.glb",
        sha256="e" * 64,
        byte_size=4096,
        media_type="model/gltf-binary",
    )
    package = ExportPackageManifest(
        package_id="pkg-001",
        job_id="portable_prop",
        run_id="run-001",
        profile_id="portable_gltf",
        source=_provenance(),
        optimization_plan=_artifact(
            "optimization-plan",
            "optimization_plan",
            "exports/packages/portable_gltf/pkg-001/metadata/optimization_plan.json",
        ),
        status="complete",
        package_root="exports/packages/portable_gltf/pkg-001",
        files=[package_file],
        primary_file_id="primary-glb",
        semantic_ids=["building.body"],
        material_ids=["mat.stone"],
        created_at=NOW,
        completed_at=NOW,
    )
    assert package.absolute_path_count == 0

    check = RoundTripCheck(
        id="semantic-coverage",
        category="semantic_id",
        status="passed",
        message="All semantic IDs survived clean import",
    )
    validation = RoundTripValidation(
        validation_id="roundtrip-001",
        job_id="portable_prop",
        run_id="run-001",
        package_id="pkg-001",
        profile_id="portable_gltf",
        package_manifest=_artifact(
            "package-manifest",
            "package_manifest",
            "exports/packages/portable_gltf/pkg-001/metadata/package_manifest.json",
        ),
        imported_inventory=_artifact(
            "imported-inventory",
            "roundtrip_inventory",
            "exports/packages/portable_gltf/pkg-001/metadata/imported_inventory.json",
        ),
        status="passed",
        ok=True,
        passed=1,
        warnings=0,
        failed=0,
        checks=[check],
        bounds=BoundsComparison(
            source=_bounds(),
            imported=_bounds(),
            max_abs_error_m=0,
            tolerance_m=0.0001,
            passed=True,
        ),
        expected_semantic_ids=["building.body"],
        observed_semantic_ids=["building.body"],
        semantic_id_coverage=1,
        expected_material_ids=["mat.stone"],
        observed_material_ids=["mat.stone"],
        material_id_coverage=1,
        created_at=NOW,
    )
    assert validation.ok

    with pytest.raises(ValidationError, match="absolute paths"):
        ExportPackageManifest.model_validate({**package.model_dump(), "absolute_path_count": 1})
