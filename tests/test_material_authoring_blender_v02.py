"""Isolated actual-Blender evidence for fixed MaterialAuthoring 0.1.0 families."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from codex_blender_modeler.blender_runner import BlenderRunError, run_blender
from codex_blender_modeler.material_authoring.models import (
    AdvancedPreviewPolicy,
    CrystalPortableInput,
    EmissivePatternInput,
    ExactArtifact,
    LocalizedDecalInput,
    MaterialAuthoringRequest,
    ProceduralMetalInput,
    ProceduralWoodInput,
    ProjectLocalFont,
    ResolutionSelectorInput,
    ScaleContextBinding,
    UVIdentity,
    UVIdentitySnapshot,
    UVRect,
)
from codex_blender_modeler.material_authoring.service import author_material_candidate
from codex_blender_modeler.structural_geometry.models import (
    AssetScaleContext,
    StructuralEvidenceArtifact,
)
from codex_blender_modeler.workspace import sha256_file

NOW = datetime(2026, 8, 11, 4, 0, tzinfo=UTC)
FAMILY_STRATEGY = {
    "wood": ("procedural_wood_v1", "procedural_wood"),
    "metal": ("procedural_metal_v1", "procedural_metal"),
    "signage_decal": ("localized_decal_v1", "localized_decal"),
    "emissive": ("emissive_pattern_v1", "emissive_pattern"),
    "crystal": ("crystal_portable_approximation_v1", "crystal"),
}


def _write_json(path: Path, value: Any) -> None:
    """Write stable fixture JSON under one pytest-owned temporary root."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    media_type: str,
) -> ExactArtifact:
    """Bind one contained fixture file to its exact current bytes."""

    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=path.relative_to(root).as_posix(),
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
        media_type=media_type,
    )


def _scale_context(root: Path) -> ScaleContextBinding:
    """Create one exact meter-scale context without modifying a user workspace."""

    scene_spec = root / "analysis" / "scene_spec.json"
    _write_json(scene_spec, {"fixture": True, "schema_version": "0.2.0"})
    context = AssetScaleContext.from_bounds(
        asset_id="asset.fixture",
        job_id="material_blender_fixture",
        workflow_id="wf-blender-fixture",
        dispatch_id="dispatch-blender-fixture",
        source_fingerprint="1" * 64,
        producer="pytest",
        producer_version="0.1.0",
        provenance=[
            StructuralEvidenceArtifact(
                role="scene_spec",
                path="analysis/scene_spec.json",
                sha256=sha256_file(scene_spec),
            )
        ],
        created_at=NOW,
        local_minimum=(0.0, 0.0, 0.0),
        local_maximum=(1.0, 0.5, 0.25),
        assembly_minimum=(0.0, 0.0, 0.0),
        assembly_maximum=(1.0, 0.5, 0.25),
        projected_pixel_size=128.0,
        target_texel_density_px_m=256.0,
    )
    context_path = root / "production" / "asset_scale_context.json"
    _write_json(context_path, context)
    artifact = _artifact(
        root,
        context_path,
        artifact_id="asset-scale-context",
        kind="asset-scale-context",
        media_type="application/json",
    )
    return ScaleContextBinding(
        artifact=artifact,
        asset_id=context.asset_id,
        source_fingerprint=context.source_fingerprint,
        shortest_dimension_m=context.shortest_dimension_m,
        longest_dimension_m=max(context.assembly_bbox.dimensions()),
        target_texel_density_px_m=context.target_texel_density_px_m,
    )


def _material_plan(root: Path) -> ExactArtifact:
    """Create inert V0.5 evidence whose exact bytes must survive the smoke."""

    path = root / "analysis" / "material_plan.json"
    _write_json(path, {"fixture": True, "schema_version": "0.5.0"})
    return _artifact(
        root,
        path,
        artifact_id="material-plan",
        kind="v05-material-plan",
        media_type="application/json",
    )


def _uv_identity(root: Path) -> UVIdentity:
    """Create one immutable UV ownership snapshot shared by fixture channels."""

    snapshot = UVIdentitySnapshot(
        semantic_id="asset.fixture",
        uv_set="UVMap",
        uv_fingerprint="a" * 64,
        ordered_polygon_corner_count=24,
        texel_density_px_m=256.0,
    )
    path = root / "analysis" / "uv_identity.json"
    _write_json(path, snapshot)
    return UVIdentity(
        **snapshot.model_dump(mode="python"),
        evidence=_artifact(
            root,
            path,
            artifact_id="uv-identity",
            kind="uv-identity-snapshot",
            media_type="application/json",
        ),
    )


def _font(root: Path) -> ProjectLocalFont:
    """Create an exact project-local bitmap font for the signage fixture."""

    glyph = ["11111", "10001", "10101", "10001", "10101", "10001", "11111"]
    path = root / "fonts" / "fixture_font.json"
    _write_json(
        path,
        {
            "glyph_height": 7,
            "glyph_width": 5,
            "glyphs": {character: glyph for character in "SIGN"},
            "schema_version": "0.1.0",
            "spacing": 1,
        },
    )
    return ProjectLocalFont(
        artifact=_artifact(
            root,
            path,
            artifact_id="fixture-font",
            kind="project-font",
            media_type="application/json",
        ),
        font_format="bitmap_json_v1",
        license_id="project-test-fixture",
        rights_status="project_owned",
        provenance="isolated deterministic bitmap fixture",
    )


def _family_payload(root: Path, family: str, uv: UVIdentity) -> object:
    """Build one bounded family companion using only existing strict contracts."""

    if family == "wood":
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
            intended_real_world_scale_m=1.0,
            deterministic_seed=123,
            mapping="uv",
            uv_identity=uv,
        )
    if family == "signage_decal":
        return LocalizedDecalInput(
            source_kind="text",
            text_evidence="exact_user_text",
            text="SIGN",
            font=_font(root),
            uv_identity=uv,
            uv_rect=UVRect(minimum=(0.1, 0.2), maximum=(0.9, 0.8)),
            mip_padding_px=8,
            base_color=(0.95, 0.65, 0.08, 1.0),
            roughness=0.4,
            emission_color=(0.2, 0.04, 0.01),
            emission_strength=1.5,
        )
    if family == "metal":
        return ProceduralMetalInput(
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
    if family == "emissive":
        return EmissivePatternInput(
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
    return CrystalPortableInput(
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


def _request(root: Path, family: str) -> MaterialAuthoringRequest:
    """Assemble one strict run-owned request for an isolated material family."""

    strategy, payload_name = FAMILY_STRATEGY[family]
    run_id = f"blender-{family.replace('_', '-')}"
    scale_context = _scale_context(root)
    kwargs = {payload_name: _family_payload(root, family, _uv_identity(root))}
    return MaterialAuthoringRequest(
        request_id=f"request-{run_id}",
        job_id="material_blender_fixture",
        workflow_id="wf-blender-fixture",
        run_id=run_id,
        material_id="mat.fixture",
        strategy=strategy,
        output_root=f"material_authoring/runs/{run_id}",
        source_v05_contracts=[_material_plan(root)],
        scale_context=scale_context,
        resolution=ResolutionSelectorInput(
            selector_id=f"selector-{run_id}",
            material_family=family,
            mapping_kind="decal" if family == "signage_decal" else "tileable",
            projected_pixel_footprint=128.0,
            target_texel_density_px_m=256.0,
            longest_object_dimension_m=scale_context.longest_dimension_m,
            package_budget_bytes=128 * 1024 * 1024,
            requested_pixels=256,
        ),
        preview_policy=AdvancedPreviewPolicy(),
        created_at=NOW,
        **kwargs,
    )


def _canonical_sha256(value: object) -> str:
    """Recompute the normalized-inventory digest using the script's stable rules."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_material_authoring_blender_probe_has_no_dynamic_execution_surface() -> None:
    """Keep the fixture runner fixed and free of dynamic code, drivers, or library loads."""

    repository_root = Path(__file__).resolve().parents[1]
    script = (
        repository_root
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "probe_material_authoring_v02.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "eval(",
        "exec(",
        "ShaderNodeScript",
        "driver_add(",
        "bpy.data.libraries.load",
        "subprocess",
    ):
        assert forbidden not in script
    assert 'parser.add_argument("--manifest"' in script
    assert 'parser.add_argument("--output-root"' in script


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE") != "1",
    reason="set CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE=1 for Blender 5.0.1 smoke",
)
@pytest.mark.parametrize(
    "family", ["wood", "metal", "signage_decal", "emissive", "crystal"]
)
def test_fixed_material_families_compile_reopen_and_render_in_blender_5(
    tmp_path: Path,
    family: str,
) -> None:
    """Compile exact maps without changing the candidate or canonical V0.5 evidence."""

    root = tmp_path / "isolated-job"
    root.mkdir()
    receipt = author_material_candidate(root, _request(root, family))
    manifest_path = root / receipt.manifest.path
    manifest_before = manifest_path.read_bytes()
    manifest_hash = sha256_file(manifest_path)
    material_plan_path = root / "analysis" / "material_plan.json"
    scene_spec_path = root / "analysis" / "scene_spec.json"
    canonical_hashes = {
        "material_plan": sha256_file(material_plan_path),
        "scene_spec": sha256_file(scene_spec_path),
    }
    fixture_id = f"fixture-{family.replace('_', '-')}"
    output_relative = f"material_authoring/blender_smoke/runs/{fixture_id}"
    run_blender(
        "probe_material_authoring_v02.py",
        [
            "--job-root",
            str(root),
            "--manifest",
            receipt.manifest.path,
            "--manifest-sha256",
            manifest_hash,
            "--output-root",
            output_relative,
        ],
        factory_startup=True,
        disable_autoexec=True,
    )

    assert manifest_path.read_bytes() == manifest_before
    assert sha256_file(material_plan_path) == canonical_hashes["material_plan"]
    assert sha256_file(scene_spec_path) == canonical_hashes["scene_spec"]
    original_manifest = json.loads(manifest_before)
    assert original_manifest["status"] == "unverified"
    assert original_manifest["master_intent"]["blender_compilation_status"] == "not_run"
    assert original_manifest["preview_evidence"]["neutral_studio_status"] == "not_run"

    output_root = root / output_relative
    smoke = json.loads((output_root / "blender_smoke_receipt.json").read_text("utf-8"))
    inventory = json.loads((output_root / "normalized_inventory.json").read_text("utf-8"))
    assert smoke["status"] == "passed"
    assert smoke["blender_version"] == "5.0.1"
    assert smoke["material_family"] == family
    assert smoke["manifest_sha256"] == manifest_hash
    assert smoke["source_manifest_unchanged"] is True
    assert smoke["canonical_write_performed"] is False
    assert smoke["destination_write_performed"] is False
    assert smoke["external_provider_used"] is False
    assert smoke["arbitrary_code_used"] is False
    assert smoke["runtime_parity_verified"] is False
    assert smoke["compiled_blend_determinism_basis"] is False
    assert smoke["limitations"]
    assert inventory["normalized_inventory_sha256"] == _canonical_sha256(
        inventory["normalized_inventory"]
    )
    assert inventory["normalized_inventory_sha256"] == smoke[
        "normalized_inventory_sha256"
    ]
    templates = {
        item["template_id"] for item in inventory["normalized_inventory"]["nodes"]
    }
    assert {"image_texture", "material_output", "principled_bsdf"} <= templates
    if family in {"wood", "metal", "signage_decal", "crystal"}:
        assert "normal_map" in templates
    if family == "wood":
        assert "bump" in templates
    expected_channels = {item["channel"] for item in original_manifest["channels"]}
    compiled_channels = {
        item["channel"] for item in inventory["normalized_inventory"]["images"]
    }
    assert compiled_channels == expected_channels
    assert all(item["packed"] is True for item in inventory["normalized_inventory"]["images"])
    if family == "metal":
        request_payload = json.loads(
            (root / original_manifest["request"]["path"]).read_text("utf-8")
        )
        metal = request_payload["procedural_metal"]
        validated = smoke["validated_family_contract"]
        assert validated["strategy"] == "procedural_metal_v1"
        assert validated["brushed_direction"] == metal["brushed_direction"] == "x"
        assert validated["unsupported_scratches"] is metal["unsupported_scratches"] is False
        assert validated["metallic_channel_bound"] is True
        assert validated["roughness_channel_bound"] is True
        assert validated["subtle_normal_channel_bound"] is True
        assert validated["roughness_base"] == pytest.approx(metal["roughness_base"])
        assert validated["roughness_variation"] == pytest.approx(
            metal["roughness_variation"]
        )
        assert validated["subtle_normal_strength"] == pytest.approx(
            metal["subtle_normal_strength"]
        )
        assert validated["scale_context_sha256"] == request_payload["scale_context"][
            "artifact"
        ]["sha256"]
        assert validated["uv_identity_sha256"] == metal["uv_identity"]["evidence"][
            "sha256"
        ]
        assert {"base_color", "metallic", "roughness", "normal"} == expected_channels
        assert {"base_color", "metallic", "roughness", "normal"} <= set(
            inventory["normalized_inventory"]["principled_socket_resolution"]
        )
        assert not any(
            "scratch" in item["semantic_id"] or "scratch" in item["template_id"]
            for item in inventory["normalized_inventory"]["nodes"]
        )
        assert any(
            "unsupported scratch detail were not synthesized" in limitation
            for limitation in smoke["limitations"]
        )
        channel_by_name = {
            item["channel"]: root / item["artifact"]["path"]
            for item in original_manifest["channels"]
        }
        with Image.open(channel_by_name["metallic"]) as opened:
            assert opened.convert("L").getextrema() == (255, 255)
        with Image.open(channel_by_name["roughness"]) as opened:
            roughness = opened.convert("L")
            assert roughness.getextrema()[0] < roughness.getextrema()[1]
            rows = [
                {roughness.getpixel((x, y)) for x in range(roughness.width)}
                for y in range(roughness.height)
            ]
            assert all(len(row) == 1 for row in rows)
            assert len({next(iter(row)) for row in rows}) > 1
        with Image.open(channel_by_name["normal"]) as opened:
            normal = opened.convert("RGB")
            extrema = normal.getextrema()
            assert any(low != high for low, high in extrema)
            assert max(
                abs(component - baseline)
                for pixel in normal.getdata()
                for component, baseline in zip(pixel, (128, 128, 255), strict=True)
            ) <= 64
    for artifact in smoke["artifacts"]:
        assert artifact["path"].startswith(output_relative + "/")
        path = root.joinpath(*artifact["path"].split("/"))
        assert path.stat().st_size == artifact["byte_size"]
        assert sha256_file(path) == artifact["sha256"]
    with Image.open(output_root / "neutral_preview.png") as preview:
        preview.verify()
    with Image.open(output_root / "neutral_preview.png") as preview:
        assert preview.size == (256, 256)
        assert any(low != high for low, high in preview.convert("RGB").getextrema())


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE") != "1",
    reason="set CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE=1 for Blender 5.0.1 smoke",
)
@pytest.mark.parametrize(
    ("tamper_target", "expected_error"),
    [
        ("manifest", "material authoring manifest SHA-256 mismatch"),
        ("scale", "scale context SHA-256 changed"),
        ("uv", "metal UV evidence SHA-256 changed"),
    ],
)
def test_fixed_metal_fixture_rejects_manifest_scale_and_uv_tamper(
    tmp_path: Path,
    tamper_target: str,
    expected_error: str,
) -> None:
    """Fail before compile when exact metal manifest, scale, or UV evidence changes."""

    root = tmp_path / "isolated-job"
    root.mkdir()
    receipt = author_material_candidate(root, _request(root, "metal"))
    manifest_path = root / receipt.manifest.path
    manifest_hash = sha256_file(manifest_path)
    manifest = json.loads(manifest_path.read_text("utf-8"))
    request_path = root / manifest["request"]["path"]
    request = json.loads(request_path.read_text("utf-8"))
    targets = {
        "manifest": manifest_path,
        "scale": root / request["scale_context"]["artifact"]["path"],
        "uv": root / request["procedural_metal"]["uv_identity"]["evidence"]["path"],
    }
    target = targets[tamper_target]
    tampered = bytearray(target.read_bytes())
    assert tampered and tampered[0] == ord("{")
    tampered[0] = ord("[")
    target.write_bytes(tampered)
    output_relative = (
        "material_authoring/blender_smoke/runs/"
        f"fixture-metal-tamper-{tamper_target}"
    )
    with pytest.raises(BlenderRunError, match=expected_error):
        run_blender(
            "probe_material_authoring_v02.py",
            [
                "--job-root",
                str(root),
                "--manifest",
                receipt.manifest.path,
                "--manifest-sha256",
                manifest_hash,
                "--output-root",
                output_relative,
            ],
            factory_startup=True,
            disable_autoexec=True,
        )
