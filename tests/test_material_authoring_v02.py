"""Focused MaterialAuthoring 0.1.0 host-contract and local-authoring tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from PIL import Image
from pydantic import ValidationError

from codex_blender_modeler.autonomy.material_models import MaterialCandidateStrategy
from codex_blender_modeler.material_authoring.models import (
    AdvancedPreviewPolicy,
    AuthoredMaterialManifest,
    CrystalPortableInput,
    EmissivePatternInput,
    ExactArtifact,
    HighResolutionAuthorization,
    ImageEvidence,
    LocalizedDecalInput,
    MaterialAuthoringRequest,
    PlanarReferencePatchInput,
    ProceduralMetalInput,
    ProceduralWoodInput,
    ProjectLocalFont,
    ResolutionSelectorInput,
    ScaleContextBinding,
    UniformFallbackInput,
    UserImagePBRInput,
    UVIdentity,
    UVIdentitySnapshot,
    UVRect,
    V05StrategyCompanionMapping,
)
from codex_blender_modeler.material_authoring.service import (
    author_material_candidate,
    select_texture_resolution,
)
from codex_blender_modeler.structural_geometry.models import (
    AssetScaleContext,
    StructuralEvidenceArtifact,
)
from codex_blender_modeler.workspace import sha256_file

NOW = datetime(2026, 8, 11, 3, 0, tzinfo=UTC)


def _write_json(path: Path, payload: Any) -> None:
    """Write deterministic fixture JSON inside one isolated temporary job."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    media_type: str,
) -> ExactArtifact:
    """Bind one fixture file to the same exact metadata used by the host service."""

    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=path.relative_to(root).as_posix(),
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
        media_type=media_type,
    )


def _fixture_context(root: Path, *, scale_m: float = 1.0) -> ScaleContextBinding:
    """Create one exact AssetScaleContext with deterministic source provenance."""

    scene_path = root / "analysis" / "scene_spec.json"
    if not scene_path.exists():
        _write_json(scene_path, {"schema_version": "0.2.0", "fixture": True})
    provenance = [
        StructuralEvidenceArtifact(
            role="scene_spec",
            path="analysis/scene_spec.json",
            sha256=sha256_file(scene_path),
        )
    ]
    context = AssetScaleContext.from_bounds(
        asset_id="asset.main",
        job_id="material_fixture",
        workflow_id="wf-test",
        dispatch_id="dispatch-test",
        source_fingerprint="1" * 64,
        producer="pytest",
        producer_version="0.1.0",
        provenance=provenance,
        created_at=NOW,
        local_minimum=(0.0, 0.0, 0.0),
        local_maximum=(scale_m, scale_m * 0.5, scale_m * 0.25),
        assembly_minimum=(0.0, 0.0, 0.0),
        assembly_maximum=(scale_m, scale_m * 0.5, scale_m * 0.25),
        projected_pixel_size=128.0,
        target_texel_density_px_m=256.0,
    )
    scale_token = str(scale_m).replace(".", "-")
    path = root / "production" / f"scale_context_{scale_token}.json"
    _write_json(path, context.model_dump(mode="json"))
    exact = _artifact(
        root,
        path,
        artifact_id=f"scale-context-{scale_token}",
        kind="asset-scale-context",
        media_type="application/json",
    )
    return ScaleContextBinding(
        artifact=exact,
        asset_id=context.asset_id,
        source_fingerprint=context.source_fingerprint,
        shortest_dimension_m=context.shortest_dimension_m,
        longest_dimension_m=max(context.assembly_bbox.dimensions()),
        target_texel_density_px_m=context.target_texel_density_px_m,
    )


def _v05_contract(root: Path) -> ExactArtifact:
    """Create one inert exact V0.5 source contract used only as immutable evidence."""

    path = root / "analysis" / "material_plan.json"
    if not path.exists():
        _write_json(path, {"schema_version": "0.5.0", "fixture": True})
    return _artifact(
        root,
        path,
        artifact_id="material-plan",
        kind="v05-material-plan",
        media_type="application/json",
    )


def _uv_identity(root: Path, suffix: str = "a") -> UVIdentity:
    """Return one exact UV owner identity for fixture channels."""

    snapshot = UVIdentitySnapshot(
        semantic_id="asset.main",
        uv_set="UVMap",
        uv_fingerprint=suffix * 64,
        ordered_polygon_corner_count=24,
        texel_density_px_m=256.0,
    )
    path = root / "analysis" / f"uv_identity_{suffix}.json"
    _write_json(path, snapshot.model_dump(mode="json"))
    return UVIdentity(
        **snapshot.model_dump(mode="python"),
        evidence=_artifact(
            root,
            path,
            artifact_id=f"uv-identity-{suffix}",
            kind="uv-identity-snapshot",
            media_type="application/json",
        ),
    )


def _request(
    root: Path,
    *,
    run_id: str,
    strategy: str,
    family: str,
    payload_name: str,
    payload: Any,
    requested_pixels: int = 256,
    scale_m: float = 1.0,
) -> MaterialAuthoringRequest:
    """Build one strict request around a strategy-specific companion payload."""

    scale = _fixture_context(root, scale_m=scale_m)
    kwargs = {payload_name: payload}
    return MaterialAuthoringRequest(
        request_id=f"request-{run_id}",
        job_id="material_fixture",
        workflow_id="wf-test",
        run_id=run_id,
        material_id="mat.main",
        strategy=strategy,
        output_root=f"material_authoring/runs/{run_id}",
        source_v05_contracts=[_v05_contract(root)],
        scale_context=scale,
        resolution=ResolutionSelectorInput(
            selector_id=f"selector-{run_id}",
            material_family=family,
            mapping_kind=(
                "fallback"
                if family == "uniform_fallback"
                else "decal"
                if family in {"signage_decal", "planar_reference_patch"}
                else "unique"
                if family == "user_image_pbr"
                else "tileable"
            ),
            projected_pixel_footprint=128.0,
            target_texel_density_px_m=scale.target_texel_density_px_m,
            longest_object_dimension_m=scale.longest_dimension_m,
            package_budget_bytes=128 * 1024 * 1024,
            requested_pixels=requested_pixels,
        ),
        preview_policy=AdvancedPreviewPolicy(),
        created_at=NOW,
        **kwargs,
    )


def _image_evidence(
    root: Path,
    *,
    channel: str,
    uv: UVIdentity,
    size: int = 32,
    normal_convention: str | None = None,
) -> ImageEvidence:
    """Create one exact local image with role-correct color-space metadata."""

    path = root / "input" / f"{channel}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if channel == "normal":
        image = Image.new("RGB", (size, size), (128, 64, 255))
    elif channel in {"base_color", "emission"}:
        image = Image.new("RGB", (size, size), (80, 120, 160))
    else:
        image = Image.new("L", (size, size), 128)
    image.save(path, format="PNG", compress_level=9)
    return ImageEvidence(
        source_id=f"source-{channel}",
        channel=channel,
        artifact=_artifact(
            root,
            path,
            artifact_id=f"input-{channel}",
            kind=f"source-{channel}",
            media_type="image/png",
        ),
        width=size,
        height=size,
        color_space="srgb" if channel in {"base_color", "emission"} else "non_color",
        license_id="user-supplied-for-project",
        rights_status="user_provided",
        provenance="isolated pytest fixture",
        uv_identity=uv,
        normal_convention=normal_convention,
    )


def _load_manifest(root: Path, path: str) -> AuthoredMaterialManifest:
    """Load one published strict material manifest from its receipt binding."""

    return AuthoredMaterialManifest.model_validate_json((root / path).read_bytes())


def test_resolution_selector_requires_exact_authorization_above_4096() -> None:
    """Keep 8K impossible without a separate exact selector-bound user authorization."""

    selector = ResolutionSelectorInput(
        selector_id="selector-8k",
        material_family="wood",
        mapping_kind="tileable",
        projected_pixel_footprint=7000.0,
        target_texel_density_px_m=8192.0,
        longest_object_dimension_m=1.0,
        package_budget_bytes=3_000_000_000,
        requested_pixels=8192,
    )
    with pytest.raises(PermissionError, match="above 4096"):
        select_texture_resolution(selector, scale_context_recommendation=8192)
    authorization = HighResolutionAuthorization(
        authorization_id="allow-8k",
        selector_input_sha256=selector.exact_sha256(),
        authorized_pixels=8192,
        purpose="material_authoring_resolution_above_4096",
        authorized_by="user",
        created_at=NOW,
    )
    selected = select_texture_resolution(
        selector,
        scale_context_recommendation=8192,
        authorization=authorization,
    )
    assert selected.selected_pixels == 8192
    assert selected.high_resolution_authorized is True
    stale = authorization.model_copy(update={"selector_input_sha256": "2" * 64})
    with pytest.raises(ValueError, match="stale"):
        select_texture_resolution(
            selector,
            scale_context_recommendation=8192,
            authorization=stale,
        )
    tiny_budget = selector.model_copy(
        update={"requested_pixels": 256, "package_budget_bytes": 1024}
    )
    with pytest.raises(ValueError, match="minimum 256"):
        select_texture_resolution(tiny_budget, scale_context_recommendation=256)


def test_user_image_pbr_preserves_all_source_evidence_and_converts_normal(
    tmp_path: Path,
) -> None:
    """Author all eight channels with exact provenance and explicit DirectX conversion."""

    root = tmp_path / "job"
    root.mkdir()
    uv = _uv_identity(root)
    channels = [
        _image_evidence(
            root,
            channel=name,
            uv=uv,
            normal_convention="directx_y_minus" if name == "normal" else None,
        )
        for name in (
            "base_color",
            "roughness",
            "metallic",
            "normal",
            "height",
            "occlusion",
            "opacity",
            "emission",
        )
    ]
    source_hashes = {item.channel: item.artifact.sha256 for item in channels}
    request = _request(
        root,
        run_id="user-pbr",
        strategy="user_image_pbr_v1",
        family="user_image_pbr",
        payload_name="user_image_pbr",
        payload=UserImagePBRInput(channels=channels),
    )
    receipt = author_material_candidate(root, request)
    manifest = _load_manifest(root, receipt.manifest.path)
    assert {item.channel for item in manifest.channels} == set(source_hashes)
    assert manifest.status == "unverified"
    assert manifest.preview_evidence.neutral_studio_status == "not_run"
    assert manifest.runtime_parity_verified is False
    for item in manifest.channels:
        assert item.width == item.height == 256
        assert item.source_artifact_sha256[0] == source_hashes[item.channel]
        assert item.source_artifact_sha256[1] == uv.evidence.sha256
    normal = next(item for item in manifest.channels if item.channel == "normal")
    with Image.open(root / normal.artifact.path) as image:
        assert image.getpixel((0, 0))[1] == 191
    assert all(sha256_file(root / item.artifact.path) == item.artifact.sha256 for item in channels)
    with pytest.raises(FileExistsError):
        author_material_candidate(root, request)


def test_user_image_contract_rejects_stale_uv_and_stale_source(tmp_path: Path) -> None:
    """Fail closed for mixed UV ownership and source bytes changed after planning."""

    root = tmp_path / "job"
    root.mkdir()
    first = _image_evidence(root, channel="base_color", uv=_uv_identity(root, "a"))
    second = _image_evidence(root, channel="roughness", uv=_uv_identity(root, "b"))
    with pytest.raises(ValidationError, match="same UV identity"):
        UserImagePBRInput(channels=[first, second])
    payload = UserImagePBRInput(channels=[first])
    request = _request(
        root,
        run_id="stale-image",
        strategy="user_image_pbr_v1",
        family="user_image_pbr",
        payload_name="user_image_pbr",
        payload=payload,
    )
    uv_path = root / first.uv_identity.evidence.path
    original_uv = uv_path.read_bytes()
    uv_path.write_bytes(original_uv.replace(b"aaaaaaaa", b"cccccccc", 1))
    with pytest.raises(ValueError, match="(?:byte size|hash) changed"):
        author_material_candidate(root, request)
    uv_path.write_bytes(original_uv)
    Image.new("RGB", (32, 32), (1, 2, 3)).save(root / first.artifact.path)
    with pytest.raises(ValueError, match="(?:byte size|hash) changed"):
        author_material_candidate(root, request)


def test_uniform_companion_adopts_legacy_256_bytes_without_enum_change(
    tmp_path: Path,
) -> None:
    """Map portable_pbr_v05 to its new name while preserving old enum and exact PNG bytes."""

    assert set(get_args(MaterialCandidateStrategy)) == {"faithful_v05", "portable_pbr_v05"}
    mapping = V05StrategyCompanionMapping()
    assert mapping.companion_strategy == "uniform_portable_fallback_v1"
    root = tmp_path / "job"
    root.mkdir()
    legacy = _image_evidence(
        root,
        channel="base_color",
        uv=_uv_identity(root),
        size=256,
    )
    request = _request(
        root,
        run_id="uniform-copy",
        strategy="uniform_portable_fallback_v1",
        family="uniform_fallback",
        payload_name="uniform_fallback",
        payload=UniformFallbackInput(existing_channels=[legacy]),
    )
    receipt = author_material_candidate(root, request)
    manifest = _load_manifest(root, receipt.manifest.path)
    assert manifest.channels[0].artifact.sha256 == legacy.artifact.sha256
    assert sha256_file(root / manifest.channels[0].artifact.path) == legacy.artifact.sha256


def _project_font(root: Path) -> ProjectLocalFont:
    """Write one exact project-local bitmap font without depending on system fonts."""

    target = root / "fonts" / "fixture_bitmap_font.json"
    glyph = ["11111", "10001", "10101", "10001", "10101", "10001", "11111"]
    _write_json(
        target,
        {
            "schema_version": "0.1.0",
            "glyph_width": 5,
            "glyph_height": 7,
            "spacing": 1,
            "glyphs": {character: glyph for character in set("CAUTION07")},
        },
    )
    return ProjectLocalFont(
        artifact=_artifact(
            root,
            target,
            artifact_id="font-fixture-bitmap",
            kind="project-font",
            media_type="application/json",
        ),
        font_format="bitmap_json_v1",
        license_id="project-test-fixture",
        rights_status="project_owned",
        provenance="deterministic pytest bitmap glyph fixture",
    )


def test_localized_decal_rasterizes_exact_text_and_refuses_unknown_text(
    tmp_path: Path,
) -> None:
    """Rasterize exact user text locally while leaving unknown text unrendered."""

    root = tmp_path / "job"
    root.mkdir()
    uv = _uv_identity(root)
    exact = LocalizedDecalInput(
        source_kind="text",
        text_evidence="exact_user_text",
        text="CAUTION 07",
        font=_project_font(root),
        uv_identity=uv,
        uv_rect=UVRect(minimum=(0.1, 0.2), maximum=(0.9, 0.8)),
        mip_padding_px=8,
        base_color=(1.0, 0.8, 0.1, 1.0),
        roughness=0.45,
        emission_color=(0.0, 0.0, 0.0),
    )
    exact_request = _request(
        root,
        run_id="decal-exact",
        strategy="localized_decal_v1",
        family="signage_decal",
        payload_name="localized_decal",
        payload=exact,
    )
    exact_receipt = author_material_candidate(root, exact_request)
    exact_manifest = _load_manifest(root, exact_receipt.manifest.path)
    opacity = next(item for item in exact_manifest.channels if item.channel == "opacity")
    with Image.open(root / opacity.artifact.path) as image:
        assert image.getbbox() is not None
    unknown = exact.model_copy(
        update={
            "text_evidence": "unknown_text",
            "text": None,
            "font": None,
        }
    )
    unknown_request = _request(
        root,
        run_id="decal-unknown",
        strategy="localized_decal_v1",
        family="signage_decal",
        payload_name="localized_decal",
        payload=unknown,
    )
    unknown_receipt = author_material_candidate(root, unknown_request)
    unknown_manifest = _load_manifest(root, unknown_receipt.manifest.path)
    assert unknown_manifest.status == "review_required"
    assert unknown_manifest.channels == []
    assert "no glyphs were invented" in " ".join(unknown_manifest.limitations)
    image_source = _image_evidence(root, channel="base_color", uv=uv)
    image_decal = LocalizedDecalInput(
        source_kind="user_image",
        image=image_source,
        uv_identity=uv,
        uv_rect=UVRect(minimum=(0.25, 0.25), maximum=(0.75, 0.75)),
        mip_padding_px=4,
        base_color=(1.0, 0.0, 0.0, 1.0),
        emission_color=(0.0, 1.0, 0.0),
        emission_strength=2.0,
    )
    image_request = _request(
        root,
        run_id="decal-image",
        strategy="localized_decal_v1",
        family="signage_decal",
        payload_name="localized_decal",
        payload=image_decal,
    )
    image_manifest = _load_manifest(
        root,
        author_material_candidate(root, image_request).manifest.path,
    )
    base = next(item for item in image_manifest.channels if item.channel == "base_color")
    emission = next(item for item in image_manifest.channels if item.channel == "emission")
    with Image.open(root / base.artifact.path) as opened:
        assert opened.convert("RGB").getpixel((128, 128)) == (80, 120, 160)
    with Image.open(root / emission.artifact.path) as opened:
        assert opened.convert("RGB").getpixel((0, 0)) == (0, 0, 0)


def test_planar_reference_patch_records_rectification_mask_and_advisory_state(
    tmp_path: Path,
) -> None:
    """Rectify exact supplied corners and keep automatic corners explicitly advisory."""

    root = tmp_path / "job"
    root.mkdir()
    uv = _uv_identity(root)
    reference = _image_evidence(root, channel="base_color", uv=uv, size=64)
    mask_path = root / "input" / "patch_mask.png"
    Image.new("L", (64, 64), 255).save(mask_path)
    patch = PlanarReferencePatchInput(
        reference_image=reference,
        source_semantic_id="asset.main.sign",
        evidence_status="inferred",
        confidence=0.62,
        corners_px=((8.0, 8.0), (55.0, 10.0), (54.0, 54.0), (9.0, 52.0)),
        corner_source="advisory_candidate",
        crop_px=(4, 4, 60, 60),
        mask=_artifact(
            root,
            mask_path,
            artifact_id="patch-mask",
            kind="patch-mask",
            media_type="image/png",
        ),
        cleanup="none",
        uv_identity=uv,
        mip_padding_px=8,
    )
    request = _request(
        root,
        run_id="planar-patch",
        strategy="planar_reference_patch_v1",
        family="planar_reference_patch",
        payload_name="planar_reference_patch",
        payload=patch,
    )
    receipt = author_material_candidate(root, request)
    manifest = _load_manifest(root, receipt.manifest.path)
    assert {item.channel for item in manifest.channels} == {"base_color", "opacity"}
    assert "advisory" in " ".join(manifest.limitations)
    assert len(manifest.channels[0].source_artifact_sha256) == 3
    with pytest.raises(ValidationError, match="observed truth"):
        PlanarReferencePatchInput.model_validate(
            {**patch.model_dump(mode="python"), "evidence_status": "observed"}
        )


def _wood(uv: UVIdentity, *, scale_m: float = 1.0) -> ProceduralWoodInput:
    """Return one deterministic scale-aware wood authoring fixture."""

    return ProceduralWoodInput(
        grain_axis="x",
        grain_frequency_m=0.04,
        growth_ring_scale_m=0.08,
        knot_seed=17,
        knot_count=3,
        earlywood_color=(0.45, 0.22, 0.08),
        latewood_color=(0.16, 0.06, 0.02),
        earlywood_latewood_contrast=0.8,
        roughness_base=0.52,
        roughness_variation=0.18,
        pore_bump_scale_m=0.001,
        finish_coating_amount=0.2,
        intended_real_world_scale_m=scale_m,
        deterministic_seed=123,
        mapping="uv",
        uv_identity=uv,
    )


def test_procedural_families_are_scale_bound_deterministic_and_explicitly_unverified(
    tmp_path: Path,
) -> None:
    """Cover wood, metal, emissive, and crystal local authoring without Blender claims."""

    root = tmp_path / "job"
    root.mkdir()
    uv = _uv_identity(root)
    first_request = _request(
        root,
        run_id="wood-a",
        strategy="procedural_wood_v1",
        family="wood",
        payload_name="procedural_wood",
        payload=_wood(uv),
    )
    mismatched_scale_request = _request(
        root,
        run_id="wood-scale-mismatch",
        strategy="procedural_wood_v1",
        family="wood",
        payload_name="procedural_wood",
        payload=_wood(uv, scale_m=0.5),
    )
    with pytest.raises(ValueError, match="intended scale"):
        author_material_candidate(root, mismatched_scale_request)
    second_request = _request(
        root,
        run_id="wood-b",
        strategy="procedural_wood_v1",
        family="wood",
        payload_name="procedural_wood",
        payload=_wood(uv),
    )
    first = _load_manifest(root, author_material_candidate(root, first_request).manifest.path)
    second = _load_manifest(root, author_material_candidate(root, second_request).manifest.path)
    assert [item.artifact.sha256 for item in first.channels] == [
        item.artifact.sha256 for item in second.channels
    ]
    scaled_request = _request(
        root,
        run_id="wood-scaled",
        strategy="procedural_wood_v1",
        family="wood",
        payload_name="procedural_wood",
        payload=_wood(uv, scale_m=10.0),
        scale_m=10.0,
    )
    scaled = _load_manifest(root, author_material_candidate(root, scaled_request).manifest.path)
    assert first.channels[0].artifact.sha256 != scaled.channels[0].artifact.sha256
    metal = ProceduralMetalInput(
        base_metal="steel",
        base_color=(0.35, 0.38, 0.42),
        roughness_base=0.3,
        roughness_variation=0.08,
        brushed_direction="x",
        brush_scale_m=0.002,
        subtle_normal_strength=0.08,
        unsupported_scratches=False,
        intended_real_world_scale_m=1.0,
        deterministic_seed=11,
        uv_identity=uv,
    )
    emissive = EmissivePatternInput(
        pattern="grid",
        base_color=(0.03, 0.03, 0.03),
        emission_color=(0.0, 0.7, 1.0),
        emission_strength=8.0,
        pattern_scale_m=0.05,
        duty_cycle=0.35,
        opacity=1.0,
        intended_real_world_scale_m=1.0,
        deterministic_seed=7,
        uv_identity=uv,
    )
    crystal = CrystalPortableInput(
        ior=1.46,
        transmission=0.92,
        roughness=0.12,
        absorption_tint=(0.1, 0.55, 0.8),
        absorption_distance_m=0.25,
        fresnel_strength=0.8,
        emission_color=(0.02, 0.1, 0.2),
        emission_strength=1.5,
        thickness_approximation_m=0.02,
        opacity_approximation=0.35,
        intended_real_world_scale_m=1.0,
        uv_identity=uv,
    )
    cases = [
        ("metal", "procedural_metal_v1", "procedural_metal", metal),
        ("emissive", "emissive_pattern_v1", "emissive_pattern", emissive),
        ("crystal", "crystal_portable_approximation_v1", "crystal", crystal),
    ]
    family_manifests: dict[str, AuthoredMaterialManifest] = {}
    for family, strategy, payload_name, payload in cases:
        request = _request(
            root,
            run_id=f"family-{family}",
            strategy=strategy,
            family=family,
            payload_name=payload_name,
            payload=payload,
        )
        manifest = _load_manifest(
            root,
            author_material_candidate(root, request).manifest.path,
        )
        assert manifest.channels
        assert manifest.status == "unverified"
        assert manifest.master_intent.blender_compilation_status == "not_run"
        assert manifest.preview_evidence.neutral_studio_status == "not_run"
        family_manifests[family] = manifest
    wood_base = next(item for item in first.channels if item.channel == "base_color")
    with Image.open(root / wood_base.artifact.path) as opened:
        assert any(low != high for low, high in opened.convert("RGB").getextrema())
    metal_map = next(
        item for item in family_manifests["metal"].channels if item.channel == "metallic"
    )
    with Image.open(root / metal_map.artifact.path) as opened:
        assert opened.convert("L").getextrema() == (255, 255)
    emission_map = next(
        item for item in family_manifests["emissive"].channels if item.channel == "emission"
    )
    with Image.open(root / emission_map.artifact.path) as opened:
        assert any(low != high for low, high in opened.convert("RGB").getextrema())
    crystal_manifest = family_manifests["crystal"]
    assert "transmission" in crystal_manifest.master_intent.features
    assert "runtime parity is unverified" in " ".join(crystal_manifest.limitations)
