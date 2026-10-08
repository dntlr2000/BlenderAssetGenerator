"""Exercise actual selected-root inspect_stage through unprimed native subprocesses."""

import hashlib
import json
import os
import shutil
import subprocess

import pytest
import test_solid_root_attachment_host as solid_fixture
import test_surface_attachment_host as fixture

from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.config import get_settings
from codex_blender_modeler.packaging import attachment as host
from codex_blender_modeler.structural_geometry.solid_attachment_companion import (
    SolidRootAttachmentIntentV01,
)


def test_registered_solid_root_real_inspect_stage_without_pythonpath(tmp_path, monkeypatch):
    """A true registered-root host launch must extract native/GLB geometry with no priming."""
    settings = get_settings()
    executable = shutil.which(settings.blender_bin)
    if executable is None:
        pytest.skip("Configured Blender executable is unavailable")
    root, selection, document = solid_fixture.registration_fixture(tmp_path)
    monkeypatch.setattr(host, "job_dir", lambda _: root)
    assert (
        host.register_solid_root_attachment_intent(
            "fixture", intent_path=selection["path"], intent_sha256=selection["sha256"]
        )
        == selection
    )
    intent = SolidRootAttachmentIntentV01.model_validate_json(json.dumps(document))
    meshes = host._source_meshes(root, intent)
    proof = collect_build_provenance(root, root.name, validate_contracts=False)
    blend, glb = root / "fixture.blend", root / "fixture.glb"
    payload = {
        "blend": str(blend),
        "glb": str(glb),
        "proof": proof,
        "objects": [
            {
                "semantic_id": mesh.semantic_id,
                "vertices": mesh.vertices,
                "faces": mesh.faces,
                "material_id": mesh.material_slots[0].material_id,
            }
            for mesh in meshes.values()
        ],
    }
    fixture.put(root, "native_fixture_input.json", payload)
    creator = root / "create_fixture.py"
    creator.write_text(
        """import bpy, json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_bytes())
bpy.ops.wm.read_factory_settings(use_empty=True)
materials = {}
for item in payload["objects"]:
    name = item["semantic_id"]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(item["vertices"], [], item["faces"])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj["cbm_id"] = name
    obj["cbm_asset_role"] = "render"
    obj["cbm_lod_level"] = 0
    obj["cbm_instance_index"] = 0
    material_id = item["material_id"]
    if material_id not in materials:
        material = bpy.data.materials.new(material_id)
        material.use_nodes = True
        material["cbm_id"] = material_id
        materials[material_id] = material
    mesh.materials.append(materials[material_id])
bpy.context.scene["cbm_build_provenance"] = json.dumps(payload["proof"])
bpy.context.scene["cbm_portable_source_build_fingerprint"] = payload["proof"]["fingerprint"]
bpy.ops.wm.save_as_mainfile(filepath=payload["blend"])
bpy.ops.export_scene.gltf(filepath=payload["glb"], export_format="GLB", export_extras=True)
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("PYTHONPATH", raising=False)
    assert "PYTHONPATH" not in os.environ
    created = subprocess.run(
        [
            executable,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            "--python",
            str(creator),
            "--",
            str(root / "native_fixture_input.json"),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    bound = fixture.source(
        fixture.HashedArtifact(id="source.attachment_intent", kind="other", **selection)
    ).model_copy(
        update={
            "build_fingerprint": proof["fingerprint"],
            "scene_spec": fixture.HashedArtifact(
                id="scene_spec", kind="scene_spec", **document["source_scene"]
            ),
            "geometry_payloads": [
                fixture.HashedArtifact(id=f"geometry.{i}", kind="geometry_payload", **item)
                for i, item in enumerate(document["source_geometry"])
            ],
        }
    )
    audit = root / "host_native_audit"
    audit.mkdir()
    records = []
    input_paths = [
        root / "job.json",
        root / host.REGISTRATION_PATH,
        root / selection["path"],
        root / document["source_camera_hypothesis"]["path"],
    ]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in input_paths}
    for stage, artifact in (("native_evaluated", blend), ("clean_import_glb", glb)):
        artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        report = host.inspect_stage(root, bound, artifact, stage, audit / (stage + ".json"))
        assert report["status"] == "passed"
        assert report["actual_triangle_extraction_verified"] is True
        assert report["source_correspondence_verified"] is True
        assert report["kind"] == "solid_root_attachment_report"
        assert report["entries"][0]["owner_certificate"]["status"] == "certified_local_ball_only"
        assert report["entries"][0]["subject_certificate"]["status"] == "certified_local_ball_only"
        assert report["seam_wide_coverage_claimed"] is False
        assert (
            report["artifact"]["sha256"]
            == artifact_hash
            == hashlib.sha256(artifact.read_bytes()).hexdigest()
        )
        assert len(host._capture_stage_evidence(root, audit, stage, report)) == 4
        records.append(report)
    assert {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in input_paths
    } == before
    package_source = bound.model_copy(
        update={
            "blend": fixture.HashedArtifact(
                id="blend",
                kind="blend",
                path=blend.relative_to(root).as_posix(),
                sha256=hashlib.sha256(blend.read_bytes()).hexdigest(),
            )
        }
    )
    staging = root / "test_only_package_staging"
    staging.mkdir()
    closure = host.verify_package_attachment(
        root,
        package_source,
        run_id="fixture-run",
        package_id="fixture-package",
        converted=blend,
        primary=glb,
        staging_root=staging,
    )
    host._verify_package_attachment_closure(root, closure)
    assert len(closure["package_files"]) == 13
    assert document["source_camera_hypothesis"]["path"] in closure["inspected_artifacts"]
    assert selection["path"] in closure["inspected_artifacts"]
    assert (
        json.loads((staging / "metadata/attachment/summary.json").read_bytes())[
            "final_human_acceptance"
        ]
        is False
    )
    (root / "HOST_ENTRYPOINT_RESULT.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "test_only": True,
                "native_processes": 6,
                "host_runtime": str(settings.repo_root),
                "pythonpath_absent_at_launch": True,
                "fixture_creator_has_source_path_bootstrap": False,
                "host_run_blender_patched": False,
                "stages": [r["stage"] for r in records],
                "input_hashes_unchanged": before,
                "production_authority_created": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
