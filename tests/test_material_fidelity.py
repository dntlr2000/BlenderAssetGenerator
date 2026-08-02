from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from PIL import Image, ImageDraw
from pypdf import PdfReader

from codex_blender_modeler.materials.fidelity import evaluate_material_fidelity
from codex_blender_modeler.materials.fidelity_models import MaterialFidelityReport
from codex_blender_modeler.reporting import generate_job_pdf_report
from codex_blender_modeler.workspace import sha256_file


def _write_json(path: Path, payload: dict) -> None:
    """Write one UTF-8 fixture JSON object."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_texture_manifest(
    root: Path,
    *,
    material_id: str,
    channels: dict[str, str],
    surface_detail_ids: list[str] | None = None,
    detail_pattern: str = "none",
) -> str:
    """Create one image-backed V0.5 texture manifest for fidelity tests."""

    material_dir = root / "textures" / material_id
    relative = f"textures/{material_id}/texture_manifest.json"
    _write_json(
        material_dir / "texture_manifest.json",
        {
            "schema_version": "0.5.0",
            "material_id": material_id,
            "uv_set": "UVMap",
            "intended_scale_m": 1.0,
            "resolution": [64, 64],
            "source_type": "image",
            "channels": {
                name: {
                    "source": "image",
                    "path": path,
                    "color_space": "sRGB"
                    if name in {"base_color", "emission"}
                    else "Non-Color",
                }
                for name, path in channels.items()
            },
            "surface_detail_ids": surface_detail_ids or [],
            "procedural": {"detail_pattern": detail_pattern},
        },
    )
    return relative


def _seed_job(root: Path, *, flawed: bool) -> None:
    """Seed a clean or deliberately flawed isolated material-fidelity job."""

    material_id = "mat.test.emissive"
    texture_dir = root / "textures" / material_id
    texture_dir.mkdir(parents=True, exist_ok=True)
    reference = Image.new("RGB", (64, 64), (20, 20, 20))
    ImageDraw.Draw(reference).rectangle((8, 8, 55, 55), fill=(30, 240, 100))
    (root / "input").mkdir(parents=True, exist_ok=True)
    reference.save(root / "input" / "reference.png")

    base = Image.new("RGB", (64, 64), (185, 210, 190))
    normal = Image.new("RGB", (64, 64), (128, 128, 255))
    emission = Image.new("RGB", (64, 64), (30, 240, 100))
    if flawed:
        draw = ImageDraw.Draw(base)
        for y in (10, 28, 46):
            draw.rectangle((0, y, 63, y + 3), fill=(0, 0, 0))
        normal = Image.new("RGB", (64, 64), (255, 128, 128))
        emission = Image.new("RGB", (64, 64), (15, 40, 250))
    base.save(texture_dir / "base_color.png")
    normal.save(texture_dir / "normal.png")
    emission.save(texture_dir / "emission.png")
    manifest = _write_texture_manifest(
        root,
        material_id=material_id,
        channels={
            "base_color": "base_color.png",
            "normal": "normal.png",
            "emission": "emission.png",
        },
        surface_detail_ids=["detail.test.panel"] if flawed else [],
        detail_pattern="horizontal_bands" if flawed else "none",
    )
    recipe_path = root / "materials" / material_id / "shader_recipe.json"
    _write_json(
        recipe_path,
        {
            "schema_version": "0.5.0",
            "material_id": material_id,
            "family": "emissive",
            "surface": {"emission_strength": 2.0},
            "mapping": {"mode": "uv", "uv_set": "UVMap", "real_world_scale_m": 1.0},
            "layers": [],
            "blender_master": True,
            "bake_required": False,
            "assumptions": ["clean uniform stylized surface"],
        },
    )
    _write_json(
        root / "analysis" / "material_plan.json",
        {
            "schema_version": "0.5.0",
            "job_id": root.name,
            "stage": "authored",
            "materials": [
                {
                    "material_id": material_id,
                    "label": "Clean emissive shell",
                    "shader_family": "emissive",
                    "texture_strategy": "image",
                    "mapping": {
                        "mode": "uv",
                        "uv_set": "UVMap",
                        "real_world_scale_m": 1.0,
                    },
                    "texture_manifest": manifest,
                    "shader_recipe": f"materials/{material_id}/shader_recipe.json",
                    "export_profiles": ["blender_eevee"],
                    "evidence_status": "observed",
                    "confidence": 0.9,
                    "notes": ["uniform"],
                }
            ],
            "global_notes": [],
        },
    )
    _write_json(
        root / "analysis" / "scene_spec.json",
        {
            "schema_version": "0.2.0",
            "job_id": root.name,
            "materials": [{"id": material_id}],
            "objects": [
                {"id": "object.primary", "material_id": material_id},
                *(
                    [{"id": "object.unbound", "material_id": material_id}]
                    if flawed
                    else []
                ),
            ],
        },
    )
    _write_json(
        root / "analysis" / "modeling_plan.json",
        {
            "surface_details": [
                {
                    "id": "detail.test.panel",
                    "parent_object_id": "object.primary",
                }
            ]
            if flawed
            else []
        },
    )


def test_clean_material_fidelity_is_deterministic_and_schema_valid(tmp_path: Path) -> None:
    """Accept stable clean maps and reproduce exact metrics and fingerprints."""

    root = tmp_path / "clean_material"
    _seed_job(root, flawed=False)

    first = evaluate_material_fidelity(root)
    second = evaluate_material_fidelity(root)

    assert first.status == "passed"
    assert first.ok
    assert first.warnings == 0
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "material_fidelity_report.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema == MaterialFidelityReport.model_json_schema()
    Draft202012Validator(schema).validate(first.model_dump(mode="json"))


def test_flawed_material_reports_lines_noise_normal_and_leakage(tmp_path: Path) -> None:
    """Identify the deterministic failure signatures observed in stylized item tests."""

    root = tmp_path / "flawed_material"
    _seed_job(root, flawed=True)

    report = evaluate_material_fidelity(root)
    codes = {finding.code for finding in report.findings}

    assert report.status == "warning"
    assert report.ok
    assert {
        "dark_line_excess",
        "full_field_variation_excess",
        "normal_deviation_excess",
        "shared_detail_atlas_leakage_risk",
        "global_detail_pattern_repeat_risk",
    } <= codes
    evidence = report.materials[0]
    assert evidence.unbound_consumer_ids == ["object.unbound"]
    assert evidence.declared_detail_parent_ids == ["object.primary"]


def test_valid_spatial_binding_suppresses_legacy_leakage_warning(tmp_path: Path) -> None:
    """Trust an exclusive object-and-UV binding instead of flagging legacy leakage."""

    root = tmp_path / "bound_material"
    _seed_job(root, flawed=True)
    manifest_path = root / "textures" / "mat.test.emissive" / "texture_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["surface_detail_bindings"] = [
        {
            "detail_id": "detail.test.panel",
            "parent_object_id": "object.primary",
            "material_id": "mat.test.emissive",
            "uv_set": "UVMap",
            "uv_layout_sha256": "0" * 64,
            "placement": {
                "mode": "uv_rect",
                "uv_rect": [0.1, 0.1, 0.4, 0.4],
            },
            "channels": ["base_color"],
            "strength": 0.5,
            "wrap": "clip",
        }
    ]
    _write_json(manifest_path, manifest)
    scene_path = root / "analysis" / "scene_spec.json"
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    scene["objects"] = [scene["objects"][0]]
    _write_json(scene_path, scene)
    _write_json(
        root / "reports" / "scene_inventory.json",
        {
            "objects": [
                {
                    "cbm_id": "object.primary",
                    "uv_layers": [
                        {
                            "name": "UVMap",
                            "vertex_uv_binding_fingerprint": "0" * 64,
                            "coordinate_bounds": {
                                "min": [0.0, 0.0],
                                "max": [1.0, 1.0],
                            },
                        }
                    ],
                }
            ]
        },
    )

    report = evaluate_material_fidelity(root)
    codes = {finding.code for finding in report.findings}

    assert "shared_detail_atlas_leakage_risk" not in codes
    assert "global_detail_pattern_repeat_risk" not in codes
    assert report.materials[0].spatial_binding_count == 1
    assert report.materials[0].unbound_consumer_ids == []


def test_missing_channel_fails_closed(tmp_path: Path) -> None:
    """Treat a missing declared texture as a host failure instead of a quality warning."""

    root = tmp_path / "missing_channel"
    _seed_job(root, flawed=False)
    (root / "textures" / "mat.test.emissive" / "normal.png").unlink()

    report = evaluate_material_fidelity(root)

    assert not report.ok
    assert report.status == "failed"
    assert any(item.code == "texture_channel_missing" for item in report.findings)


def test_declared_channel_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    """Reject image evidence changed after its exact generation hash was recorded."""

    root = tmp_path / "changed_channel"
    _seed_job(root, flawed=False)
    texture_dir = root / "textures" / "mat.test.emissive"
    manifest_path = texture_dir / "texture_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"] = {
        "provider": "fixture",
        "provider_version": "1",
        "model": "fixture",
        "prompt": "fixture",
        "seed": 0,
        "generated_sha256": {
            name: sha256_file(texture_dir / channel["path"])
            for name, channel in manifest["channels"].items()
        },
        "license": "test-only",
    }
    _write_json(manifest_path, manifest)
    Image.new("RGB", (64, 64), (0, 0, 0)).save(texture_dir / "base_color.png")

    report = evaluate_material_fidelity(root)

    assert not report.ok
    assert report.status == "failed"
    assert any(
        item.code == "texture_channel_hash_mismatch" for item in report.findings
    )


def test_reference_mask_hash_participates_in_fidelity_fingerprint(tmp_path: Path) -> None:
    """Make a changed deterministic reference mask stale the exact fidelity evidence."""

    root = tmp_path / "masked_reference"
    _seed_job(root, flawed=False)
    mask_path = root / "analysis" / "masks" / "reference_content.png"
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (64, 64), 255).save(mask_path)
    first = evaluate_material_fidelity(root)
    changed = Image.new("L", (64, 64), 255)
    ImageDraw.Draw(changed).rectangle((0, 0, 31, 63), fill=0)
    changed.save(mask_path)
    second = evaluate_material_fidelity(root)

    assert first.input_hashes["analysis/masks/reference_content.png"]
    assert first.source_fingerprint != second.source_fingerprint


def test_material_pdf_projects_authoritative_fidelity_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Include fidelity warnings in the existing derived material PDF projection."""

    workspace = tmp_path / "workspaces"
    root = workspace / "fidelity_pdf"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    _seed_job(root, flawed=True)
    report = evaluate_material_fidelity(root)
    report_path = root / "reports" / "material_fidelity_validation.json"
    _write_json(report_path, report.model_dump(mode="json"))
    _write_json(
        root / "job.json",
        {
            "job_id": "fidelity_pdf",
            "mode": "concept",
            "project_version_created": "0.9.0",
            "reference_path": "input/reference.png",
        },
    )
    _write_json(
        root / "reports" / "material_contract_validation.json",
        {"ok": True, "passed": 1, "warnings": 0, "failed": 0},
    )

    result = generate_job_pdf_report("fidelity_pdf", scope="material")
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(result["pdf"]).pages
    )

    assert "V0.5 Material Fidelity QA" in extracted
    assert "dark_line_excess" in extracted
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert any(
        source["path"] == "reports/material_fidelity_validation.json"
        for source in manifest["sources"]
    )
