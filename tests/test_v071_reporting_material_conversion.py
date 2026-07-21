"""Reporting regressions for V0.7.1 portable material-conversion evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from codex_blender_modeler.reporting import (
    collect_job_report_payload,
    generate_job_pdf_report,
)
from codex_blender_modeler.workspace import sha256_file


def _write_json(path: Path, payload: dict) -> None:
    """Write one deterministic JSON report fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _artifact(artifact_id: str, kind: str, path: str, digest: str = "1" * 64) -> dict:
    """Create one compact job-relative artifact record."""

    return {"id": artifact_id, "kind": kind, "path": path, "sha256": digest}


def _receipt(root: Path, path: Path, receipt_id: str) -> dict:
    """Create one exact package receipt for a metadata snapshot."""

    return {
        "id": receipt_id,
        "kind": "metadata",
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "byte_size": path.stat().st_size,
        "media_type": "application/json",
    }


def _seed_report_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_conversion: bool,
) -> Path:
    """Create one isolated legacy or V0.7.1 portable package report fixture."""

    workspace = tmp_path / "workspaces"
    root = workspace / "portable_report_case"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = root / "input" / "reference.png"
    preview = root / "renders" / "preview.png"
    reference.parent.mkdir(parents=True)
    preview.parent.mkdir(parents=True)
    Image.new("RGB", (32, 32), color=(80, 120, 160)).save(reference)
    Image.new("RGB", (32, 32), color=(100, 140, 90)).save(preview)
    _write_json(
        root / "job.json",
        {
            "job_id": "portable_report_case",
            "mode": "concept",
            "project_version_created": "0.7.1",
            "reference_path": str(reference),
            "reference_sha256": sha256_file(reference),
        },
    )
    _write_json(
        root / "analysis" / "scene_spec.json",
        {"schema_version": "0.2.0", "job_id": "portable_report_case", "objects": []},
    )
    _write_json(
        root / "asset_profiles" / "portable_gltf.json",
        {
            "schema_version": "0.7.0",
            "profile_id": "portable_gltf",
            "job_id": "portable_report_case",
            "asset_kind": "static_environment",
            "primary_format": "glb",
            "units": "meters",
            "up_axis": "+Y",
            "forward_axis": "-Z",
        },
    )
    run = root / "optimization" / "runs" / "run-001"
    _write_json(
        run / "optimization_plan.json",
        {
            "schema_version": "0.7.0",
            "plan_id": "optimization-plan-001",
            "job_id": "portable_report_case",
            "run_id": "run-001",
            "profile_id": "portable_gltf",
            "profile_artifact": _artifact(
                "profile",
                "asset_profile",
                "asset_profiles/portable_gltf.json",
            ),
            "source": {"build_fingerprint": "2" * 64},
            "status": "complete",
        },
    )
    package_root = root / "exports" / "packages" / "portable_gltf" / "package-001"
    primary = package_root / "asset.glb"
    primary.parent.mkdir(parents=True)
    primary.write_bytes(b"portable glb fixture")
    files = [
        {
            "id": "primary-glb",
            "kind": "primary_asset",
            "path": primary.relative_to(root).as_posix(),
            "sha256": sha256_file(primary),
            "byte_size": primary.stat().st_size,
            "media_type": "model/gltf-binary",
        }
    ]
    material_conversion = None
    if with_conversion:
        metadata = package_root / "metadata"
        conversion_plan = metadata / "material_conversion_plan.json"
        conversion_manifest = metadata / "material_conversion_manifest.json"
        conversion_evidence = metadata / "material_conversion_evidence.json"
        _write_json(
            conversion_plan,
            {
                "schema_version": "0.7.0",
                "plan_id": "conversion-plan-001",
                "job_id": "portable_report_case",
                "run_id": "run-001",
                "profile_id": "portable_gltf",
                "status": "approved",
                "required_material_ids": ["mat.rock", "mat.water"],
            },
        )
        _write_json(
            conversion_manifest,
            {
                "schema_version": "0.7.0",
                "manifest_id": "conversion-manifest-001",
                "job_id": "portable_report_case",
                "run_id": "run-001",
                "profile_id": "portable_gltf",
                "status": "complete",
                "atlas_policy": {
                    "layout": "global_shared",
                    "resolution": 2048,
                    "uv_set": "CBMPortableAtlas",
                },
                "required_material_ids": ["mat.rock", "mat.water"],
                "converted_material_ids": ["mat.rock", "mat.water"],
                "missing_material_ids": [],
                "entries": [
                    {
                        "material_id": "mat.rock",
                        "losses": [],
                        "warnings": [],
                    },
                    {
                        "material_id": "mat.water",
                        "losses": ["Transmission extension remains engine-dependent."],
                        "warnings": [],
                    },
                ],
                "tiles": [{"binding_id": "binding.asset.lod0"}],
                "outputs": [
                    {"channel": channel, "material_ids": ["mat.rock", "mat.water"]}
                    for channel in (
                        "base_color",
                        "roughness",
                        "metallic",
                        "normal",
                        "emission",
                    )
                ],
                "portable_blend": {
                    "path": "optimization/material_conversions/conversion-001/scene.blend"
                },
                "canonical_unchanged": True,
            },
        )
        _write_json(
            conversion_evidence,
            {
                "kind": "portable_material_conversion_evidence",
                "ok": True,
                "binding_count": 1,
                "material_count": 2,
            },
        )
        files.extend(
            [
                _receipt(root, conversion_plan, "metadata-conversion-plan"),
                _receipt(root, conversion_manifest, "metadata-conversion-manifest"),
                _receipt(root, conversion_evidence, "metadata-conversion-evidence"),
            ]
        )
        material_conversion = {
            "id": "material-conversion-manifest",
            "kind": "portable_material_conversion_manifest",
            "path": conversion_manifest.relative_to(root).as_posix(),
            "sha256": sha256_file(conversion_manifest),
        }
    package_payload = {
        "schema_version": "0.7.0",
        "package_id": "package-001",
        "job_id": "portable_report_case",
        "run_id": "run-001",
        "profile_id": "portable_gltf",
        "status": "complete",
        "package_root": package_root.relative_to(root).as_posix(),
        "files": files,
        "primary_file_id": "primary-glb",
        "semantic_ids": ["asset.body"],
        "material_ids": ["mat.rock", "mat.water"],
        "absolute_path_count": 0,
        "missing_dependency_count": 0,
        "canonical_unchanged": True,
        "known_losses": [],
        "warnings": [],
        "errors": [],
    }
    if material_conversion is not None:
        package_payload["material_conversion"] = material_conversion
    _write_json(package_root / "package_manifest.json", package_payload)
    return root


def test_export_payload_collects_all_verified_material_conversion_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collect the three hash-verified conversion snapshots selected by the package."""

    _seed_report_job(tmp_path, monkeypatch, with_conversion=True)

    payload = collect_job_report_payload(
        "portable_report_case",
        "export",
        package_id="portable_gltf/package-001",
    )

    assert {
        "material_conversion_plan",
        "material_conversion_manifest",
        "material_conversion_evidence",
    } <= set(payload["documents"])
    assert payload["documents"]["material_conversion_manifest"]["status"] == "complete"
    conversion_sources = {
        source.kind: source.path
        for source in payload["sources"]
        if source.kind.startswith("material_conversion_")
    }
    assert set(conversion_sources) == {
        "material_conversion_plan",
        "material_conversion_manifest",
        "material_conversion_evidence",
    }
    assert all(path.startswith("exports/packages/") for path in conversion_sources.values())


def test_export_pdf_renders_portable_material_conversion_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose global atlas, conversion identity, and channels in the human PDF."""

    _seed_report_job(tmp_path, monkeypatch, with_conversion=True)

    result = generate_job_pdf_report(
        "portable_report_case",
        scope="export",
        package_id="portable_gltf/package-001",
    )
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(result["pdf"]).pages
    )

    assert "Portable material conversion" in extracted
    assert "conversion-manifest-001" in extracted
    assert "global_shared" in extracted
    assert "base_color" in extracted
    assert "emission" in extracted


def test_legacy_package_does_not_warn_about_missing_material_conversion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep conversion snapshots optional for packages created before V0.7.1."""

    _seed_report_job(tmp_path, monkeypatch, with_conversion=False)

    payload = collect_job_report_payload(
        "portable_report_case",
        "export",
        package_id="portable_gltf/package-001",
    )

    assert "material_conversion_manifest" not in payload["documents"]
    assert not any("material_conversion" in warning for warning in payload["warnings"])
