"""Receipt-backed quality Blend snapshots remain valid across structural reentry."""

from __future__ import annotations

import hashlib

import pytest

from codex_blender_modeler.autonomy_v2.models import AQV2Artifact
from codex_blender_modeler.material_closure.fidelity_source import _quality_snapshot_target
from codex_blender_modeler.reference_fidelity.models import FidelityArtifact


def _snapshots(root):
    """Create two exact historical copies plus a superseded current canonical Blend."""
    data = b"BLENDER-fixture-retained-material"
    material_path = "production/material/round-one/authoring.blend"
    reserved_path = "production/fidelity/reentries/0001/source.blend"
    for relative, content in (
        (material_path, data),
        (reserved_path, data),
        ("blender/scene.blend", b"BLENDER-fixture-new-geometry"),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    digest = hashlib.sha256(data).hexdigest()
    material = AQV2Artifact(
        artifact_id="material-snapshot", kind="authoring_blend", path=material_path,
        sha256=digest, byte_size=len(data),
    )
    reserved = FidelityArtifact(path=reserved_path, sha256=digest)
    return material, reserved


@pytest.mark.parametrize("reference_form", ["canonical_alias", "material_snapshot"])
def test_quality_blend_reference_preserves_current_and_historical_bytes(tmp_path, reference_form):
    """Accept either already-valid QA source form without rewriting any file or reference."""
    material, reserved = _snapshots(tmp_path)
    original = material if reference_form == "material_snapshot" else material.model_copy(
        update={"path": "blender/scene.blend", "artifact_id": "quality-candidate"}
    )
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    expected = None if reference_form == "material_snapshot" else (reserved.path, reserved.sha256)
    assert _quality_snapshot_target(
        tmp_path, original, material, reserved, canonical_path="blender/scene.blend"
    ) == expected
    assert before == {p: (tmp_path / p).read_bytes() for p in before}


@pytest.mark.parametrize("mutation", [
    "unrelated_equal_copy", "mixed_round_path", "quality_hash", "quality_size",
    "receipt_size", "material_tamper", "reserved_tamper", "different_reserved_bytes",
])
def test_quality_blend_snapshot_rejects_unbound_or_changed_evidence(tmp_path, mutation):
    """Reject same-byte aliases, mixed rounds, stale hashes and altered receipt-bound snapshots."""
    material, reserved = _snapshots(tmp_path)
    original = material
    if mutation in {"unrelated_equal_copy", "mixed_round_path"}:
        path = (
            "other.blend" if mutation == "unrelated_equal_copy"
            else "production/material/round-two/authoring.blend"
        )
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((tmp_path / material.path).read_bytes())
        original = original.model_copy(update={"path": path})
    elif mutation == "quality_hash":
        original = original.model_copy(update={"sha256": "0" * 64})
    elif mutation == "quality_size":
        original = original.model_copy(update={"byte_size": original.byte_size + 1})
    elif mutation == "receipt_size":
        material = material.model_copy(update={"byte_size": material.byte_size + 1})
    elif mutation in {"material_tamper", "reserved_tamper"}:
        path = material.path if mutation == "material_tamper" else reserved.path
        (tmp_path / path).write_bytes(b"changed snapshot")
    elif mutation == "different_reserved_bytes":
        data = b"different correctly hashed snapshot"
        (tmp_path / reserved.path).write_bytes(data)
        reserved = reserved.model_copy(update={"sha256": hashlib.sha256(data).hexdigest()})
    with pytest.raises(ValueError):
        _quality_snapshot_target(
            tmp_path, original, material, reserved, canonical_path="blender/scene.blend"
        )
