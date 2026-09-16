"""Geometry-only provenance remains exact material input, never appearance acceptance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import test_material_closure_execution_profiles as profiles
import test_material_closure_service as fixtures

from codex_blender_modeler.blender_artifacts import native_io_path, sha256_file
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.material_closure.collector import MaterialClosureCollectionError
from codex_blender_modeler.material_closure.state_consistency import (
    canonical_build_provenance_artifact_fingerprint,
)


def _geometry_source(tmp_path, monkeypatch, *, receipt_mode="scene_spec_only"):
    """Prepare separate canonical observations and a geometry receipt in an isolated fixture."""

    prepared = profiles._prepared(tmp_path, monkeypatch, material=True)
    root, _original, _source, _outputs, binding, geometry = prepared
    observed = collect_build_provenance(root, "fixture_job", material_plan_mode="scene_spec_only")
    candidate = collect_build_provenance(root, "fixture_job", material_plan_mode=receipt_mode)
    profiles._write(root, binding["canonical_build_provenance_path"], observed)
    relative = "production/geometry_source/provenance.json"
    profiles._write(root, relative, candidate)
    replacement = fixtures._aq_artifact(
        root,
        relative,
        artifact_id="geometry-build",
        kind="candidate_build_provenance",
    ).model_dump(mode="json")
    old = geometry["candidate_build_provenance"]
    geometry["candidate_build_provenance"] = replacement
    geometry["provenance"] = [
        replacement if item == old else item for item in geometry["provenance"]
    ]
    profiles._write(root, binding["geometry_candidate_validation_receipt_path"], geometry)
    return prepared


def test_snapshot_recomputes_explicit_geometry_mode_with_prior_material_plan(tmp_path, monkeypatch):
    """Retain a prior material contract while validating the newly built geometry-only source."""

    prepared = _geometry_source(tmp_path, monkeypatch)
    root, _original, _source, _outputs, binding, _geometry = prepared
    previous = root / "analysis/material_plan.json"
    previous.write_bytes((root / binding["candidate_material_plan_path"]).read_bytes())
    before = {
        path.relative_to(root): sha256_file(path) for path in root.rglob("*") if path.is_file()
    }
    build = profiles._exact(
        root,
        binding["canonical_build_provenance_path"],
        "observed-build",
        "build_provenance",
    )
    assert (
        canonical_build_provenance_artifact_fingerprint(
            job_root=root,
            build_provenance=build,
            expected_job_id="fixture_job",
        )
        == build.sha256
    )
    assert before == {path: sha256_file(root / path) for path in before}
    scene = root / "analysis/scene_spec.json"
    scene.write_bytes(scene.read_bytes() + b"\n")
    with pytest.raises(MaterialClosureCollectionError, match="STALE_CANONICAL_BUILD_PROVENANCE"):
        canonical_build_provenance_artifact_fingerprint(
            job_root=root,
            build_provenance=build,
            expected_job_id="fixture_job",
        )


def test_closure_accepts_exact_geometry_only_build_without_writes(tmp_path, monkeypatch):
    """Exercise the complete collector using the promoted geometry's explicit build selection."""

    prepared = _geometry_source(tmp_path, monkeypatch)
    root = prepared[0]
    before = {
        path.relative_to(root): sha256_file(path) for path in root.rglob("*") if path.is_file()
    }
    closure = profiles._collect(prepared)
    assert closure == profiles._collect(prepared)
    assert before == {path: sha256_file(root / path) for path in before}


def test_geometry_mode_cannot_replace_the_receipt_build_selection(tmp_path, monkeypatch):
    """Reject recomputable observations that do not describe the exact promoted geometry."""

    prepared = _geometry_source(tmp_path, monkeypatch, receipt_mode="current")
    with pytest.raises(MaterialClosureCollectionError, match="UNPROVEN_GEOMETRY_BUILD_SELECTION"):
        profiles._collect(prepared)


@pytest.mark.parametrize("mode", ["unknown", None, [], "current"])
def test_explicit_mode_cannot_be_guessed_or_normalized(tmp_path, monkeypatch, mode):
    """Unknown or altered selection fails closed even if its artifact hash is fresh."""

    prepared = _geometry_source(tmp_path, monkeypatch)
    root, _original, _source, _outputs, binding, _geometry = prepared
    path = binding["canonical_build_provenance_path"]
    payload = json.loads((root / path).read_bytes())
    payload["material_plan_mode"] = mode
    profiles._write(root, path, payload)
    build = profiles._exact(root, path, "observed-build", "build_provenance")
    with pytest.raises(MaterialClosureCollectionError):
        canonical_build_provenance_artifact_fingerprint(
            job_root=root,
            build_provenance=build,
            expected_job_id="fixture_job",
        )


@pytest.mark.parametrize("reader", ["json", "entry", "manifest"])
def test_deep_dependency_is_exact_and_preserves_portable_paths(tmp_path, reader):
    """Collect real paths beyond MAX_PATH without changing portable identities or stale checks."""

    from codex_blender_modeler.material_closure.collector import (
        _entry_from_path,
        _read_json_object,
        _resolve_manifest_owned_dependency_path,
        validate_declared_dependencies,
    )

    relative = "/".join(["nested" * 12] * 4 + ["dependency.json"])
    path = Path(native_io_path(tmp_path / relative))
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"sentinel": 1}\n')
    assert len(str(tmp_path / relative)) > 260
    if reader == "json":
        assert _read_json_object(tmp_path, relative) == {"sentinel": 1}
    elif reader == "manifest":
        assert _resolve_manifest_owned_dependency_path(
            tmp_path,
            manifest_path=relative.rsplit("/", 1)[0] + "/texture_manifest.json",
            declared_path="dependency.json",
        ) == relative
    else:
        entry = _entry_from_path(
            tmp_path, role="exact_fixture", path=relative, source_kind="generated_evidence",
            ownership="staging", producer="test",
        )
        assert entry.path == relative and entry.sha256 == sha256_file(path)
        assert validate_declared_dependencies(tmp_path, [entry]) == []
        path.write_bytes(path.read_bytes() + b" ")
        assert [issue.code for issue in validate_declared_dependencies(tmp_path, [entry])] == [
            "STALE_DEPENDENCY_SIZE"
        ]


def test_deep_shadow_preview_keeps_exact_image_and_report_evidence(tmp_path):
    """Read real deep preview/report bytes and reject stale PNGs without changing identities."""

    from PIL import Image

    from codex_blender_modeler.material_closure.preflight import MaterialPreflightValidationError
    from codex_blender_modeler.material_closure.shadow_compile import (
        _read_passed_json,
        _validate_preview,
    )

    relative = "/".join(["shadow" * 10] * 4)
    directory = tmp_path / relative
    native = Path(native_io_path(directory))
    native.mkdir(parents=True)
    image_path = directory / "swatch.png"
    Image.new("RGBA", (64, 64), "blue").save(native_io_path(image_path))
    payload = {"ok": True, "resolution": [64, 64], "swatches": [
        {"material_id": "fixture", "path": "swatch.png", "sha256": sha256_file(image_path)}
    ]}
    manifest = directory / "renderer.json"
    (native / manifest.name).write_text(json.dumps(payload), encoding="utf-8")
    assert len(str(manifest)) > 260
    assert _read_passed_json(manifest, label="fixture") == payload
    image, report, _fingerprint = _validate_preview(
        tmp_path, manifest, expected_material_id="fixture", expected_size=64,
    )
    assert image.path == f"{relative}/swatch.png"
    assert image.sha256 == payload["swatches"][0]["sha256"]
    assert report.path == f"{relative}/renderer.json"
    Image.new("RGBA", (64, 64), "red").save(native_io_path(image_path))
    with pytest.raises(MaterialPreflightValidationError, match="digest changed"):
        _validate_preview(tmp_path, manifest, expected_material_id="fixture", expected_size=64)
