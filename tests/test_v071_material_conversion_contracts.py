"""Focused validation tests for V0.7.1 portable material-conversion contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from codex_blender_modeler.optimization.models import (
    HashedArtifact,
    PortableAtlasPolicy,
    PortableAtlasTile,
    PortableChannelOutput,
    PortableMaterialBinding,
    PortableMaterialContractArtifact,
    PortableMaterialConversionEntry,
    PortableMaterialConversionManifest,
    PortableMaterialConversionPlan,
    SourceProvenance,
)

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
MATERIAL_IDS = ["mat.rock", "mat.water"]
CHANNELS = ["base_color", "roughness", "metallic", "normal", "emission"]


def _artifact(
    artifact_id: str,
    kind: str,
    path: str,
    digest: str = "a" * 64,
) -> HashedArtifact:
    """Create one deterministic V0.7 hashed-artifact fixture."""

    return HashedArtifact(id=artifact_id, kind=kind, path=path, sha256=digest)


def _contract_artifact(
    artifact_id: str,
    kind: str,
    path: str,
    digest: str = "b" * 64,
) -> PortableMaterialContractArtifact:
    """Create one deterministic material-conversion contract artifact."""

    return PortableMaterialContractArtifact(
        id=artifact_id,
        kind=kind,
        path=path,
        sha256=digest,
    )


def _source() -> SourceProvenance:
    """Create immutable canonical provenance for conversion fixtures."""

    return SourceProvenance(
        scene_spec=_artifact(
            "scene-spec", "scene_spec", "analysis/scene_spec.json", "1" * 64
        ),
        blend=_artifact("canonical-blend", "blend", "blender/scene.blend", "2" * 64),
        source_fingerprint="3" * 64,
        build_fingerprint="4" * 64,
    )


def _binding(material_id: str, index: int) -> PortableMaterialBinding:
    """Create one material binding with an isolated source recipe and semantic target."""

    return PortableMaterialBinding(
        material_id=material_id,
        source_shader_recipe=_contract_artifact(
            f"recipe-{index}",
            "shader_recipe",
            f"materials/{material_id}/shader_recipe.json",
            f"{index + 5:x}" * 64,
        ),
        source_material_fingerprint=f"{index + 7:x}" * 64,
        mapping_mode="object" if index == 0 else "uv",
        target_ids=[f"asset.part_{index}"],
    )


def _plan(**overrides: object) -> PortableMaterialConversionPlan:
    """Create one approved conversion plan bound to exact portable run inputs."""

    values: dict[str, object] = {
        "plan_id": "material-conversion-plan-001",
        "job_id": "portable_asset",
        "run_id": "portable-run-001",
        "profile_id": "portable_gltf",
        "source": _source(),
        "profile_artifact": _artifact(
            "asset-profile",
            "asset_profile",
            "asset_profiles/portable_gltf.json",
            "a" * 64,
        ),
        "optimization_plan": _artifact(
            "optimization-plan",
            "optimization_plan",
            "optimization/runs/portable-run-001/optimization_plan.json",
            "b" * 64,
        ),
        "optimized_blend": _artifact(
            "optimized-blend",
            "blend",
            "optimization/runs/portable-run-001/optimized/scene.blend",
            "c" * 64,
        ),
        "uv_manifest": _artifact(
            "uv-manifest",
            "uv_manifest",
            "optimization/runs/portable-run-001/uv_manifest.json",
            "d" * 64,
        ),
        "required_material_ids": MATERIAL_IDS,
        "materials": [
            _binding(material_id, index)
            for index, material_id in enumerate(MATERIAL_IDS)
        ],
        "status": "approved",
        "created_at": NOW,
        "approved_at": NOW,
    }
    values.update(overrides)
    return PortableMaterialConversionPlan.model_validate(values)


def _binding_id(index: int) -> str:
    """Return the stable derived render binding ID for one material fixture."""

    return f"binding.asset.part_{index}.lod0"


def _entry(material_id: str, index: int) -> PortableMaterialConversionEntry:
    """Create one completed material entry that references a global atlas binding."""

    binding = _binding(material_id, index)
    return PortableMaterialConversionEntry(
        material_id=material_id,
        source_shader_recipe=binding.source_shader_recipe,
        source_material_fingerprint=binding.source_material_fingerprint,
        portable_material_fingerprint=f"{index + 9:x}" * 64,
        mapping_mode=binding.mapping_mode,
        binding_ids=[_binding_id(index)],
        losses=[] if index == 0 else ["Runtime transmission extension not verified"],
    )


def _tile(material_id: str, index: int) -> PortableAtlasTile:
    """Create one non-overlapping deterministic global-atlas tile fixture."""

    return PortableAtlasTile(
        binding_id=_binding_id(index),
        material_id=material_id,
        target_id=f"asset.part_{index}",
        derived_object_id=f"asset.part_{index}.lod0",
        lod_level=0,
        uv_set="CBMPortableAtlas",
        resolution=(2048, 2048),
        margin_px=16,
        uv_minimum=(0.0 + index * 0.5, 0.0),
        uv_maximum=(0.5 + index * 0.5, 1.0),
        overlap_fraction=None,
        quality_status="partially_verified",
    )


def _channel(channel: str, index: int) -> PortableChannelOutput:
    """Create one global atlas output covering every required material."""

    return PortableChannelOutput(
        id=f"portable-atlas-{channel}",
        channel=channel,
        path=f"optimization/runs/portable-run-001/materials/atlas/{channel}.png",
        sha256=f"{index + 1:x}" * 64,
        color_space="sRGB" if channel in {"base_color", "emission"} else "Non-Color",
        resolution=(2048, 2048),
        material_ids=MATERIAL_IDS,
    )


def _manifest(**overrides: object) -> PortableMaterialConversionManifest:
    """Create one complete conversion manifest with exact global-atlas coverage."""

    plan = _plan()
    entries = [_entry(material_id, index) for index, material_id in enumerate(MATERIAL_IDS)]
    tiles = [_tile(material_id, index) for index, material_id in enumerate(MATERIAL_IDS)]
    values: dict[str, object] = {
        "manifest_id": "material-conversion-manifest-001",
        "job_id": plan.job_id,
        "run_id": plan.run_id,
        "profile_id": plan.profile_id,
        "source": plan.source,
        "plan_artifact": _contract_artifact(
            "conversion-plan-artifact",
            "portable_material_conversion_plan",
            "optimization/runs/portable-run-001/portable_material_conversion_plan.json",
            "e" * 64,
        ),
        "profile_artifact": plan.profile_artifact,
        "optimization_plan": plan.optimization_plan,
        "optimized_blend": plan.optimized_blend,
        "uv_manifest": plan.uv_manifest,
        "atlas_policy": plan.atlas_policy,
        "required_material_ids": MATERIAL_IDS,
        "converted_material_ids": MATERIAL_IDS,
        "missing_material_ids": [],
        "entries": entries,
        "tiles": tiles,
        "outputs": [_channel(channel, index) for index, channel in enumerate(CHANNELS)],
        "portable_blend": _artifact(
            "portable-blend",
            "blend",
            "optimization/runs/portable-run-001/portable/scene.blend",
            "f" * 64,
        ),
        "status": "complete",
        "created_at": NOW,
        "completed_at": NOW,
    }
    values.update(overrides)
    return PortableMaterialConversionManifest.model_validate(values)


def test_plan_and_manifest_bind_exact_v07_inputs_and_outputs() -> None:
    """Accept a full V0.7.1 global conversion while retaining schema version 0.7.0."""

    plan = _plan()
    manifest = _manifest()

    assert plan.schema_version == "0.7.0"
    assert plan.atlas_policy.layout == "global_shared"
    assert plan.atlas_policy.atlas_scope == "all_render_lod"
    assert manifest.schema_version == "0.7.0"
    assert manifest.required_material_ids == manifest.converted_material_ids
    assert manifest.missing_material_ids == []
    assert manifest.canonical_unchanged is True
    assert manifest.portable_blend is not None
    assert len(manifest.outputs) == 5
    assert all(output.material_ids == MATERIAL_IDS for output in manifest.outputs)


def test_plan_requires_exact_ordered_material_binding_coverage() -> None:
    """Reject duplicate, omitted, or reordered material requirements before execution."""

    with pytest.raises(ValidationError, match="exactly cover"):
        _plan(materials=[_binding("mat.rock", 0)])
    with pytest.raises(ValidationError, match="ordered and unique"):
        _plan(required_material_ids=["mat.water", "mat.rock"])


def test_manifest_requires_exact_material_binding_and_tile_coverage() -> None:
    """Reject complete results with missing materials, entries, or global atlas tiles."""

    with pytest.raises(ValidationError, match="full coverage"):
        _manifest(
            converted_material_ids=["mat.rock"],
            missing_material_ids=["mat.water"],
            entries=[_entry("mat.rock", 0)],
            tiles=[_tile("mat.rock", 0)],
        )
    with pytest.raises(ValidationError, match="exactly cover material entry bindings"):
        _manifest(tiles=[_tile("mat.rock", 0)])


def test_global_channel_outputs_require_exact_order_and_color_spaces() -> None:
    """Reject missing channels, bad color spaces, and incomplete material coverage."""

    with pytest.raises(ValidationError, match="canonical five channels"):
        _manifest(outputs=[_channel(channel, index) for index, channel in enumerate(CHANNELS[:-1])])

    bad_color = _manifest().model_dump()
    bad_color["outputs"][0]["color_space"] = "Non-Color"
    with pytest.raises(ValidationError, match="base_color channel requires color_space=sRGB"):
        PortableMaterialConversionManifest.model_validate(bad_color)

    bad_emission = _manifest().model_dump()
    bad_emission["outputs"][4]["color_space"] = "Non-Color"
    with pytest.raises(ValidationError, match="emission channel requires color_space=sRGB"):
        PortableMaterialConversionManifest.model_validate(bad_emission)

    incomplete = _manifest().model_dump()
    incomplete["outputs"][0]["material_ids"] = ["mat.rock"]
    with pytest.raises(ValidationError, match="exactly cover required materials"):
        PortableMaterialConversionManifest.model_validate(incomplete)


def test_manifest_rejects_duplicate_or_input_colliding_output_paths() -> None:
    """Reject globally duplicated outputs and any attempt to overwrite a bound input."""

    duplicate = _manifest().model_dump()
    duplicate["outputs"][1]["path"] = duplicate["outputs"][0]["path"]
    with pytest.raises(ValidationError, match="output paths must be globally unique"):
        PortableMaterialConversionManifest.model_validate(duplicate)

    collision = _manifest().model_dump()
    collision["outputs"][0]["path"] = collision["optimized_blend"]["path"]
    with pytest.raises(ValidationError, match="must not overwrite bound inputs"):
        PortableMaterialConversionManifest.model_validate(collision)


def test_atlas_policy_and_lifecycle_are_fail_closed() -> None:
    """Reject unsafe atlas layouts and lifecycle states that imply false completion."""

    with pytest.raises(ValidationError, match="power of two"):
        PortableAtlasPolicy(resolution=1500)
    with pytest.raises(ValidationError, match="canonical order"):
        PortableAtlasPolicy(
            required_channels=["base_color", "metallic", "roughness", "normal", "emission"]
        )
    with pytest.raises(ValidationError, match="requires approved_at"):
        _plan(approved_at=None)

    planned = _manifest().model_dump()
    planned.update(
        status="planned",
        converted_material_ids=[],
        missing_material_ids=[],
        entries=[],
        tiles=[],
        outputs=[],
        portable_blend=None,
        completed_at=None,
    )
    assert PortableMaterialConversionManifest.model_validate(planned).status == "planned"

    failed = _manifest().model_dump()
    failed.update(
        status="failed",
        converted_material_ids=["mat.rock"],
        missing_material_ids=["mat.water"],
        entries=[_entry("mat.rock", 0).model_dump()],
        tiles=[_tile("mat.rock", 0).model_dump()],
        outputs=[],
        portable_blend=None,
        errors=["mat.water conversion failed"],
    )
    assert PortableMaterialConversionManifest.model_validate(failed).status == "failed"


def test_tiles_are_global_policy_bound_without_false_overlap_claims() -> None:
    """Require policy-aligned tiles and evidence before any verified-overlap claim."""

    with pytest.raises(ValidationError, match="requires overlap_fraction evidence"):
        PortableAtlasTile(
            **{
                **_tile("mat.rock", 0).model_dump(),
                "quality_status": "verified",
                "overlap_fraction": None,
            }
        )

    wrong_uv = _manifest().model_dump()
    wrong_uv["tiles"][0]["uv_set"] = "OtherAtlas"
    with pytest.raises(ValidationError, match="atlas-policy UV set"):
        PortableMaterialConversionManifest.model_validate(wrong_uv)

    overlap = _manifest().model_dump()
    overlap["tiles"][0]["overlap_fraction"] = 0.01
    with pytest.raises(ValidationError, match="overlap exceeds"):
        PortableMaterialConversionManifest.model_validate(overlap)
