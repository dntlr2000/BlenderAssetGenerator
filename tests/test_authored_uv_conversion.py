"""Adversarial host, contract and public-surface tests for authored UV v1."""

from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_v071_material_conversion_contracts import _artifact, _manifest, _plan

from codex_blender_modeler.blender_scripts.portable_authored_uv_proof import mapped_uvs
from codex_blender_modeler.blender_scripts.portable_material_conversion_runtime import (
    atlas_tile_bounds,
)
from codex_blender_modeler.optimization.models import (
    PortableAtlasPolicy,
    PortableMaterialConversionPlan,
)
from codex_blender_modeler.packaging.authored_uv import (
    ATLAS,
    MODE,
    AuthoredUVInspection,
    AuthoredUVProof,
    build_proof,
    canonical_hash,
    read_json,
    validate_inspection,
    verify_saved_proof,
)


def fixture():
    """Build two bounded continuous quads with independent material and layer identities."""
    plan = _plan(
        atlas_policy=PortableAtlasPolicy(uv_method=MODE),
        authored_uv_source=_artifact("source-uv", "other", "authored_uv_source.json"),
    )
    rows = []
    for index, binding in enumerate(plan.materials):
        uv = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        rows.append(
            {
                "identity": {
                    "name": f"part{index}",
                    "semantic_id": binding.target_ids[0],
                    "source_object": f"source{index}",
                    "asset_role": "render",
                    "lod_level": 0,
                    "material_id": binding.material_id,
                    "source_material_fingerprint": binding.source_material_fingerprint,
                },
                "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
                "matrix_world": [
                    [1.0, 0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ],
                "polygons": [[0, 1, 2, 3]],
                "polygon_materials": [0],
                "loops": [0, 1, 2, 3],
                "polygon_loops": [[0, 1, 2, 3]],
                "triangles": [[0, 1, 2], [0, 2, 3]],
                "uv_layers": {"Layout": uv, "Other": [[1 - u, v] for u, v in uv]},
                "source_uv_set": "Layout",
                "sampling": [
                    {
                        "node_name": "Image",
                        "node_type": "TEX_IMAGE",
                        "selection": "image_vector",
                        "uv_set": "Other",
                    }
                ],
                "active_uv_set": "Layout",
                "render_uv_set": "Other",
            }
        )
    source = AuthoredUVInspection(
        blender_version="5.0.1",
        blend_sha256=plan.optimized_blend.sha256,
        stage="source",
        objects=rows,
    )
    targets = copy.deepcopy(rows)
    for index, row in enumerate(targets):
        bounds = atlas_tile_bounds(index, 2, 2048, 16)
        row["uv_layers"][ATLAS] = mapped_uvs(row["uv_layers"]["Layout"], bounds)
        row["active_uv_set"] = row["render_uv_set"] = ATLAS
        row["sampling"] = [
            {
                "node_name": "CBM_PortableAtlasUV",
                "node_type": "UVMAP",
                "selection": "uv_map",
                "uv_set": ATLAS,
            }
        ]
    target = AuthoredUVInspection(
        blender_version="5.0.1", blend_sha256="f" * 64, stage="target", objects=targets
    )
    return plan, source, target


def test_positive_full_precision_proof_and_legacy_bytes():
    """Continuous source charts produce measured proof without changing old default projections."""
    plan, source, target = fixture()
    proof = build_proof(source, target, plan, "e" * 64, "a" * 64)
    assert all(row.target.overlap_pair_count == 0 for row in proof.objects)
    assert all(row.actual_target_matches_reconstruction for row in proof.objects)
    assert "uv_method" not in PortableAtlasPolicy().model_dump(mode="json")
    assert "authored_uv_source" not in _plan().model_dump(mode="json")
    assert "authored_uv_proof" not in _manifest().model_dump(mode="json")
    assert canonical_hash(source.model_dump(mode="json")) != canonical_hash(
        target.model_dump(mode="json")
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "uv_swap",
        "tiny_uv",
        "topology",
        "source_layer",
        "sampling",
        "sampling_missing",
        "target_order",
        "material",
        "vertex",
    ],
)
def test_stale_postrepair_and_sampling_mutations_fail(mutation):
    """Stored proof cannot survive altered corners, geometry, identity or portable sampling."""
    plan, source, target = fixture()
    raw = target.model_dump(mode="json")
    row = raw["objects"][0]
    if mutation == "uv_swap":
        row["uv_layers"][ATLAS][0], row["uv_layers"][ATLAS][1] = (
            row["uv_layers"][ATLAS][1],
            row["uv_layers"][ATLAS][0],
        )
    elif mutation == "tiny_uv":
        row["uv_layers"][ATLAS][0][0] += 1e-12
    elif mutation == "topology":
        row["triangles"].reverse()
    elif mutation == "source_layer":
        row["uv_layers"]["Other"][0][0] = 0.125
    elif mutation == "sampling":
        row["sampling"][0]["uv_set"] = "Other"
    elif mutation == "sampling_missing":
        row["sampling"] = []
    elif mutation == "target_order":
        raw["objects"].reverse()
    elif mutation == "material":
        row["identity"]["source_material_fingerprint"] = "0" * 64
    else:
        row["vertices"][0][0] = 0.001
    with pytest.raises(ValueError):
        build_proof(source, AuthoredUVInspection.model_validate(raw), plan, "e" * 64, "a" * 64)


def test_exact_material_target_coverage_and_source_repeat_refusal():
    """Undeclared or missing object coverage and intentional repeat layouts are ineligible."""
    plan, source, target = fixture()
    altered = plan.model_copy(deep=True)
    altered.materials[0].target_ids.append("unrepresented")
    with pytest.raises(ValueError, match="coverage"):
        validate_inspection(source, altered, stage="source")
    raw = source.model_dump(mode="json")
    raw["objects"][0]["uv_layers"]["Layout"] = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
    with pytest.raises(ValueError, match="overlap|zero-area"):
        build_proof(AuthoredUVInspection.model_validate(raw), target, plan, "e" * 64, "a" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("complete", 1),
        ("overlap_pair_count", False),
        ("triangle_count", True),
        ("candidate_pair_count", "1"),
    ],
)
def test_measured_proof_rejects_coercive_counts(field, value):
    """Strict proof fields do not accept truthy strings or booleans as measured counts."""
    plan, source, target = fixture()
    raw = build_proof(source, target, plan, "e" * 64, "a" * 64).model_dump(mode="json")
    raw["objects"][0]["target"][field] = value
    with pytest.raises(ValidationError):
        AuthoredUVProof.model_validate(raw)


def test_missing_unknown_and_cross_mode_proof_rejected():
    """Explicit v1 cannot silently fall back when its source/proof binding is missing."""
    with pytest.raises(ValidationError):
        _plan(atlas_policy=PortableAtlasPolicy(uv_method=MODE))
    with pytest.raises(ValidationError):
        PortableAtlasPolicy(uv_method="validated_authored_uv_v2")
    with pytest.raises(ValidationError):
        _manifest(atlas_policy=PortableAtlasPolicy(uv_method=MODE))
    with pytest.raises(ValidationError):
        _manifest(authored_uv_proof=_artifact("proof", "other", "proof.json"))


def test_duplicate_json_keys_and_nonfinite_literal_rejected(tmp_path):
    """Proof JSON parsing preserves fail-closed duplicate and finite-value semantics."""
    path = tmp_path / "proof.json"
    for payload in ('{"a": 1,"a": 2}', '{"a": NaN}'):
        path.write_text(payload)
        with pytest.raises(ValueError):
            read_json(path)


def saved_fixture(tmp_path):
    """Persist a valid proof and matching manifest before applying isolated tampering."""
    from codex_blender_modeler.blender_scripts.portable_material_conversion_runtime import (
        stable_identifier,
    )
    from codex_blender_modeler.optimization.models import PortableMaterialConversionManifest
    from codex_blender_modeler.workspace import sha256_file

    plan, source, target = fixture()
    source_path = tmp_path / "authored_uv_source.json"
    source_path.write_text(source.model_dump_json())
    plan.authored_uv_source.sha256 = sha256_file(source_path)
    proof = build_proof(source, target, plan, "e" * 64, plan.authored_uv_source.sha256)
    proof_path = tmp_path / "authored_uv_proof.json"
    proof_path.write_text(proof.model_dump_json())
    raw = _manifest().model_dump(mode="json")
    raw["atlas_policy"] = plan.atlas_policy.model_dump(mode="json")
    raw["authored_uv_proof"] = _artifact(
        "proof", "other", "authored_uv_proof.json", sha256_file(proof_path)
    ).model_dump(mode="json")
    for index, (row, tile, entry) in enumerate(
        zip(source.objects, raw["tiles"], raw["entries"], strict=True)
    ):
        identity = row.identity
        tile.update(
            binding_id=stable_identifier(f"{index:06d}.{identity.name}", "binding"),
            derived_object_id=stable_identifier(identity.name, "derived"),
            uv_minimum=list(proof.objects[index].target_bounds[:2]),
            uv_maximum=list(proof.objects[index].target_bounds[2:]),
            overlap_fraction=0.0,
            quality_status="verified",
            unwrap_method=MODE,
        )
        entry["binding_ids"] = [tile["binding_id"]]
    return plan, source, target, proof, PortableMaterialConversionManifest.model_validate(raw)


def test_loader_rejects_missing_or_rehashed_tampered_proof(tmp_path, monkeypatch):
    """A valid loader control passes before a single forged fingerprint is freshly rehashed."""
    from codex_blender_modeler.packaging import authored_uv
    from codex_blender_modeler.workspace import sha256_file

    plan, source, target, proof, manifest = saved_fixture(tmp_path)
    monkeypatch.setattr(
        authored_uv,
        "inspect_blend",
        lambda *args, **kwargs: target if kwargs.get("source_path") else source,
    )
    assert verify_saved_proof(tmp_path, tmp_path, plan, manifest) == proof
    with pytest.raises(ValueError, match="requires source and proof"):
        verify_saved_proof(tmp_path, tmp_path, plan, _manifest(), reinspect=False)
    raw = proof.model_dump(mode="json")
    raw["objects"][0]["target"]["uv_fingerprint_sha256"] = "0" * 64
    path = tmp_path / "authored_uv_proof.json"
    path.write_text(json.dumps(raw))
    manifest.authored_uv_proof.sha256 = sha256_file(path)
    with pytest.raises(ValueError, match="recomputed"):
        verify_saved_proof(tmp_path, tmp_path, plan, manifest)


def test_self_consistent_forged_snapshots_fail_actual_reinspection(tmp_path, monkeypatch):
    """Rehashed internally consistent evidence cannot replace the reopened source/output bytes."""
    from codex_blender_modeler.packaging import authored_uv
    from codex_blender_modeler.workspace import sha256_file

    plan, source, target, _proof, manifest = saved_fixture(tmp_path)
    honest_source = source.model_copy(deep=True)
    honest_target = target.model_copy(deep=True)
    source.objects[0].vertices[0] = (0.125, 0.0, 0.0)
    target.objects[0].vertices[0] = (0.125, 0.0, 0.0)
    source_path = tmp_path / "authored_uv_source.json"
    source_path.write_text(source.model_dump_json())
    plan.authored_uv_source.sha256 = sha256_file(source_path)
    forged = build_proof(source, target, plan, "e" * 64, plan.authored_uv_source.sha256)
    proof_path = tmp_path / "authored_uv_proof.json"
    proof_path.write_text(forged.model_dump_json())
    manifest.authored_uv_proof.sha256 = sha256_file(proof_path)
    assert verify_saved_proof(tmp_path, tmp_path, plan, manifest, reinspect=False) == forged
    monkeypatch.setattr(
        authored_uv,
        "inspect_blend",
        lambda *args, **kwargs: honest_target if kwargs.get("source_path") else honest_source,
    )
    with pytest.raises(ValueError, match="actual saved blends"):
        verify_saved_proof(tmp_path, tmp_path, plan, manifest)


def test_public_uv_method_defaults_and_forwarding():
    """Expose one consistent selector while preserving all public resolution defaults."""
    from codex_blender_modeler import cli, mcp_server
    from codex_blender_modeler.packaging.material_conversion import convert_portable_materials

    for function in (
        cli.asset_material_convert,
        mcp_server.convert_portable_materials,
        convert_portable_materials,
    ):
        signature = inspect.signature(function)
        assert signature.parameters["uv_method"].default == "smart_project"
    assert inspect.signature(cli.asset_material_convert).parameters["resolution"].default == 1024
    assert (
        inspect.signature(mcp_server.convert_portable_materials).parameters["resolution"].default
        == 1024
    )
    assert inspect.signature(convert_portable_materials).parameters["resolution"].default == 2048
    root = Path(__file__).resolve().parents[1]
    for name in ("cli.py", "mcp_server.py"):
        assert "uv_method=uv_method" in (root / "src/codex_blender_modeler" / name).read_text()


def test_schema_projection_exact():
    """Published schemas describe the same strict opt-in evidence as host models."""
    root = Path(__file__).resolve().parents[1]
    for name, model in (
        ("authored_uv_inspection_v01", AuthoredUVInspection),
        ("authored_uv_proof_v01", AuthoredUVProof),
        ("portable_material_conversion_plan", PortableMaterialConversionPlan),
    ):
        assert (
            json.loads((root / "schemas" / f"{name}.schema.json").read_text())
            == model.model_json_schema()
        )


@pytest.mark.parametrize(
    "change",
    [
        "tile_uv",
        "tile_resolution",
        "tile_margin",
        "extra_channel",
        "output_material",
        "output_resolution",
        "extra_material",
        "missing_material",
        "duplicate_tile",
    ],
)
def test_raw_authored_evidence_cannot_normalize_away_tampering(tmp_path, change):
    """The opt-in normalizer rejects raw mismatches before overwriting them from policy."""
    from codex_blender_modeler.packaging.material_conversion import _normalize_manifest
    from codex_blender_modeler.workspace import sha256_file

    plan, _source, _target, _proof, manifest = saved_fixture(tmp_path)
    (tmp_path / "conversion_plan.json").write_text(plan.model_dump_json())
    raw = {
        "ok": True,
        "conversion_plan_sha256": sha256_file(tmp_path / "conversion_plan.json"),
        "optimized_blend_sha256": plan.optimized_blend.sha256,
        "tiles": [tile.model_dump(mode="json") for tile in manifest.tiles],
        "materials": [entry.model_dump(mode="json") for entry in manifest.entries],
        "outputs": [output.model_dump(mode="json") for output in manifest.outputs],
    }
    if change == "tile_uv":
        raw["tiles"][0]["uv_set"] = "Other"
    elif change == "tile_resolution":
        raw["tiles"][0]["resolution"] = [1024, 1024]
    elif change == "tile_margin":
        raw["tiles"][0]["margin_px"] = 8
    elif change == "extra_channel":
        raw["outputs"].append({**raw["outputs"][0], "channel": "unknown"})
    elif change == "output_material":
        raw["outputs"][0]["material_ids"] = ["wrong"]
    elif change == "output_resolution":
        raw["outputs"][0]["resolution"] = [1024, 1024]
    elif change == "extra_material":
        raw["materials"].append({**raw["materials"][0], "material_id": "extra"})
    elif change == "missing_material":
        raw["materials"].pop()
    else:
        raw["tiles"].append(raw["tiles"][0])
    with pytest.raises(ValueError, match="authored UV raw|duplicate authored UV"):
        _normalize_manifest(tmp_path, tmp_path / "final", tmp_path, "test", plan, raw)


def test_package_conversion_loader_invokes_optin_verifier_and_rejects_proof(tmp_path, monkeypatch):
    """A normalized package fixture cannot bypass the selected authored proof verifier."""
    from types import SimpleNamespace

    from codex_blender_modeler.packaging import material_conversion

    plan, _source, _target, _proof, manifest = saved_fixture(tmp_path)
    directory = material_conversion.material_conversion_directory(
        tmp_path, plan.run_id, "conversion"
    )
    manifest.plan_artifact.path = (
        (directory / "conversion_plan.json").relative_to(tmp_path).as_posix()
    )
    artifacts = [
        manifest.profile_artifact,
        manifest.optimization_plan,
        manifest.optimized_blend,
        manifest.uv_manifest,
        manifest.portable_blend,
        *manifest.outputs,
    ]
    digests = {str(tmp_path / artifact.path): artifact.sha256 for artifact in artifacts}
    digests.update({str(tmp_path / item.source_shader_recipe.path): item.source_shader_recipe.sha256
                    for item in plan.materials})
    digests[str(directory / "conversion_plan.json")] = manifest.plan_artifact.sha256
    monkeypatch.setattr(
        material_conversion,
        "load_model",
        lambda _path, model: plan if model is PortableMaterialConversionPlan else manifest,
    )
    monkeypatch.setattr(material_conversion, "file_exists", lambda _path: True)
    monkeypatch.setattr(material_conversion, "sha256_file", lambda path: digests[str(path)])
    monkeypatch.setattr(
        material_conversion, "profile_artifact", lambda *args: manifest.profile_artifact
    )
    called = []

    def reject(*args):
        """Emulate the strict verifier finding missing packaged proof evidence."""
        called.append(args)
        raise ValueError("authored UV proof artifact missing")

    monkeypatch.setattr(material_conversion, "verify_saved_proof", reject)
    with pytest.raises(ValueError, match="proof artifact missing"):
        material_conversion.load_portable_material_conversion(
            tmp_path,
            plan.run_id,
            "conversion",
            profile=SimpleNamespace(profile_id=plan.profile_id),
            optimization=SimpleNamespace(job_id=plan.job_id, source=plan.source),
        )
    assert len(called) == 1


def test_compact_proof_persistence_is_lossless_and_immutable(tmp_path):
    """Compact proof bytes preserve full coordinates and refuse evidence overwrite."""
    from codex_blender_modeler.packaging.authored_uv import write_proof_model

    _plan_value, source, _target = fixture()
    path = tmp_path / "source.json"
    write_proof_model(path, source)
    assert AuthoredUVInspection.model_validate(read_json(path)) == source
    assert len(path.read_bytes()) < len(source.model_dump_json(indent=2).encode())
    with pytest.raises(FileExistsError):
        write_proof_model(path, source)


def test_blender_source_reader_keeps_native_deep_path_io(tmp_path, monkeypatch):
    """Build a native deep-path fixture and verify the bpy-side reader's native-I/O dispatch."""
    import importlib.util
    import sys
    from types import SimpleNamespace

    from codex_blender_modeler.blender_artifacts import native_io_path
    from codex_blender_modeler.blender_scripts import portable_material_conversion_runtime

    monkeypatch.setitem(sys.modules, "bpy", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules, "portable_material_conversion_runtime", portable_material_conversion_runtime
    )
    path = (
        Path(__file__).resolve().parents[1]
        / "src/codex_blender_modeler/blender_scripts/portable_authored_uv_runtime.py"
    )
    spec = importlib.util.spec_from_file_location("authored_runtime_path_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    deep = tmp_path.joinpath(*(["deep_snapshot_path_" + "x" * 40] * 5)) / "source.json"
    Path(native_io_path(deep.parent)).mkdir(parents=True)
    Path(native_io_path(deep)).write_text('{"full_precision":0.12345678901234568}')
    assert module.read_source(deep) == {"full_precision": 0.12345678901234568}
    assert module.read_source(str(deep)) == {"full_precision": 0.12345678901234568}
    calls = []

    def native(value):
        """Record dispatch while preserving the platform's required native path handling."""
        calls.append(value)
        return native_io_path(value)

    monkeypatch.setattr(module, "native_io_path", native)
    assert module.read_source(deep) == {"full_precision": 0.12345678901234568}
    assert module.read_source(str(deep)) == {"full_precision": 0.12345678901234568}
    assert calls == [deep, deep]
