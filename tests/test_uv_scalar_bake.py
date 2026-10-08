"""Exact affine, coverage, compatibility and evidence rejection tests for scalar UV baking."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from test_authored_uv_conversion import fixture

from codex_blender_modeler.blender_scripts.portable_authored_uv_proof import mapped_uvs
from codex_blender_modeler.blender_scripts.portable_material_conversion_runtime import (
    atlas_tile_bounds,
)
from codex_blender_modeler.blender_scripts.portable_uv_scalar_bake import (
    SCALAR_CHANNELS,
    affine_layer_corners,
    coverage_pixel_box,
)
from codex_blender_modeler.packaging.authored_uv import canonical_hash
from codex_blender_modeler.packaging.scalar_bake import (
    AuthoredUVScalarBakeEvidence,
    validate_scalar_evidence,
    verify_saved_scalar_evidence,
)
from codex_blender_modeler.workspace import sha256_file

SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def test_exact_mirrored_layer_relation():
    """A global exact mirrored sampling layer preserves the previous supported two-layer case."""
    assert affine_layer_corners(SQUARE, [[1 - u, v] for u, v in SQUARE], SQUARE) == [
        [1.0, 0.0],
        [0.0, 0.0],
        [0.0, 1.0],
        [1.0, 1.0],
    ]


@pytest.mark.parametrize("changed", ["nonaffine", "duplicate", "tiny", "chart_transform"])
def test_nonaffine_source_sampling_refused(changed):
    """Require an exact relation for every ordered corner, including seams."""
    source = [*SQUARE, [0.0, 0.0], [0.5, 0.5]]
    sampled = [[1 - u, v] for u, v in source]
    if changed == "nonaffine":
        sampled[2][0] = 0.01
    elif changed == "duplicate":
        sampled[4][1] = 0.25
    elif changed == "tiny":
        sampled[-1][0] = math.nextafter(0.5, 1.0)
    else:
        sampled[4] = [0.0, 0.0]
    with pytest.raises(ValueError, match="not exactly affine"):
        affine_layer_corners(source, sampled, SQUARE)


def test_exact_rational_corner_cannot_round_into_false_float32_proof():
    """A tiny rational extrapolation error cannot vanish during an intermediate float64 round."""
    e = 2.0**-80
    with pytest.raises(ValueError, match="not exactly representable"):
        affine_layer_corners(
            [[0.0, 0.0], [1.0, e], [e, 1.0]], [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], SQUARE
        )


def evidence_fixture(tmp_path):
    """Build strict proxy and white-mask evidence for two exact source objects."""
    plan, source, _target = fixture()
    rows = []
    for index, obj in enumerate(source.objects):
        raw = obj.model_dump(mode="json")
        bounds = atlas_tile_bounds(index, 2, 2048, 16)
        dependencies = {
            channel: [
                {"node_name": "OtherUV", "node_type": "UVMAP", "output": "UV", "uv_set": "Other"}
            ]
            for channel in SCALAR_CHANNELS
        }
        rows.append(
            {
                "name": obj.identity.name,
                "material_id": obj.identity.material_id,
                "source_snapshot_sha256": canonical_hash(raw),
                "source_uv_set": "Layout",
                "source_bounds": [0.0, 0.0, 1.0, 1.0],
                "target_bounds": bounds,
                "target_corners": mapped_uvs(SQUARE, bounds),
                "sampled_uv_layers": ["Other"],
                "layer_corners": {
                    "Layout": SQUARE,
                    "Other": affine_layer_corners(
                        raw["uv_layers"]["Layout"], raw["uv_layers"]["Other"], SQUARE
                    ),
                },
                "dependencies": dependencies,
            }
        )
    path = tmp_path / "authored_uv_coverage.png"
    Image.new("RGB", (2048, 2048), "white").save(path)
    outputs = [
        SimpleNamespace(channel=channel, sha256=str(index) * 64)
        for index, channel in enumerate(SCALAR_CHANNELS)
    ]
    raw = {
        "schema_version": "0.1.0",
        "kind": "authored_uv_scalar_bake_evidence",
        "method": "uv_domain_scalar_v1",
        "conversion_plan_sha256": "e" * 64,
        "optimized_blend_sha256": plan.optimized_blend.sha256,
        "source_snapshot_sha256": plan.authored_uv_source.sha256,
        "resolution": 2048,
        "margin_px": 16,
        "scalar_channels": list(SCALAR_CHANNELS),
        "scalar_outputs": {o.channel: o.sha256 for o in outputs},
        "normal_method": "unchanged_actual_mesh_tangent_bake",
        "normal_coverage_and_basis_fidelity": "not_proved_by_scalar_coverage",
        "coverage": {"file_name": path.name, "sha256": sha256_file(path)},
        "objects": rows,
    }
    return plan, source, outputs, AuthoredUVScalarBakeEvidence.model_validate(raw)


def test_complete_coverage_does_not_require_nonzero_scalar_colors(tmp_path):
    """A white independent mask verifies raster support even when a legitimate channel is black."""
    plan, source, outputs, evidence = evidence_fixture(tmp_path)
    assert validate_scalar_evidence(evidence, source, plan, "e" * 64, tmp_path, outputs) == evidence
    assert outputs[0].sha256 == "0" * 64


@pytest.mark.parametrize(
    "changed", ["missing_pixel", "source", "target", "layer", "channel", "material", "normal"]
)
def test_freshly_rehashed_tampering_is_rejected(tmp_path, changed):
    """Recomputing artifact hashes cannot make missing coverage or changed source mapping valid."""
    plan, source, outputs, evidence = evidence_fixture(tmp_path)
    if changed == "missing_pixel":
        path = tmp_path / "authored_uv_coverage.png"
        image = Image.open(path)
        image.putpixel((100, 100), (0, 0, 0))
        image.save(path)
        evidence.coverage.sha256 = sha256_file(path)
    elif changed == "source":
        evidence.objects[0].source_snapshot_sha256 = "0" * 64
    elif changed == "target":
        evidence.objects[0].target_corners[0] = (0.0, 0.0)
    elif changed == "layer":
        evidence.objects[0].layer_corners["Other"][0] = (0.0, 0.0)
    elif changed == "channel":
        evidence.scalar_outputs["emission"] = "f" * 64
    elif changed == "material":
        evidence.objects[0].material_id = "wrong"
    else:
        raw = evidence.model_dump(mode="json")
        raw["normal_coverage_and_basis_fidelity"] = "verified"
        with pytest.raises(ValueError):
            AuthoredUVScalarBakeEvidence.model_validate(raw)
        return
    with pytest.raises(ValueError):
        validate_scalar_evidence(evidence, source, plan, "e" * 64, tmp_path, outputs)


def test_old_uv_only_receipt_does_not_acquire_scalar_claim():
    """Historical absent coverage returns no new scalar guarantee or extra inspector dependency."""
    assert (
        verify_saved_scalar_evidence(
            None, None, None, SimpleNamespace(authored_uv_scalar_bake=None)
        )
        is None
    )


def test_bilinear_support_box_includes_adjacent_texels():
    """Coverage must include filtering support outside each occupied rectangle's vertices."""
    assert coverage_pixel_box([0.125, 0.125, 0.875, 0.875], 128) == [15, 15, 113, 113]


def test_schema_matches_scalar_evidence_model():
    """The additive evidence schema is generated directly from the strict host model."""
    path = Path(__file__).resolve().parents[1] / "schemas/authored_uv_scalar_bake_v01.schema.json"
    assert json.loads(path.read_text()) == AuthoredUVScalarBakeEvidence.model_json_schema()


def test_saved_scalar_loader_rehashes_source_and_mask(tmp_path):
    """The additive companion loader independently checks source bytes and bound mask bytes."""
    from codex_blender_modeler.optimization.models import HashedArtifact

    plan, source, outputs, evidence = evidence_fixture(tmp_path)
    source_path = tmp_path / "authored_uv_source.json"
    source_path.write_text(source.model_dump_json())
    plan.authored_uv_source.sha256 = sha256_file(source_path)
    evidence.source_snapshot_sha256 = plan.authored_uv_source.sha256
    path = tmp_path / "authored_uv_scalar_bake.json"
    path.write_text(evidence.model_dump_json())
    artifact = HashedArtifact(
        id="scalar-proof", kind="other", path=path.name, sha256=sha256_file(path)
    )
    manifest = SimpleNamespace(
        authored_uv_scalar_bake=artifact,
        plan_artifact=SimpleNamespace(sha256="e" * 64),
        outputs=outputs,
    )
    assert verify_saved_scalar_evidence(tmp_path, tmp_path, plan, manifest) == evidence
    source_path.write_text(source.model_dump_json() + " ")
    with pytest.raises(ValueError, match="source inspection hash"):
        verify_saved_scalar_evidence(tmp_path, tmp_path, plan, manifest)


def test_host_rejects_exact_binary64_but_unstorable_float32_corner():
    """An exact affine relation must also survive the actual proxy Float2 storage format."""
    with pytest.raises(ValueError, match="float32 representable"):
        affine_layer_corners(
            [[0.0, 0.0], [1.0, 2.0**-26], [0.0, 1.0]], [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], SQUARE
        )
