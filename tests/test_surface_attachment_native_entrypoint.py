"""Exercise the fixed inspector as a fresh Blender --python process, without path priming."""

import hashlib
import json
import os
import shutil
import subprocess

import pytest

from codex_blender_modeler.attachment_runtime import REGISTRATION_PATH
from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.config import get_settings


def _put(root, name, value):
    """Bind fixture-owned JSON bytes without constructing production authority."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _sha(path):
    """Record the exact native artifact inspected by each standalone process."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_selected_native_and_clean_import_entrypoint_without_pythonpath(tmp_path, monkeypatch):
    """A normal runner must import its trusted package independently of a previous Python process.

    This small fixture proves launcher/bootstrap and extraction bindings only.
    Hash-only source placeholders do not claim production authoring or image QA.
    """
    settings = get_settings()
    executable = shutil.which(settings.blender_bin)
    if executable is None:
        pytest.skip("Configured Blender executable is unavailable")
    root = tmp_path / "entrypoint_fixture"
    root.mkdir()
    scene = _put(
        root,
        "analysis/scene_spec.json",
        {
            "job_id": root.name,
            "objects": [],
            "materials": [],
            "camera": {
                "projection": "ORTHO",
                "location": [0.0, -3.0, 0.0],
                "target": [0.0, 0.0, 0.0],
                "focal_length_mm": 50.0,
                "ortho_scale": 2.0,
                "resolution": [32, 32],
            },
        },
    )
    reference = _put(root, "input/reference.png", {"hash_only_native_fixture": True})
    plan = _put(root, "analysis/modeling_plan.json", {"job_id": root.name})
    geometry = _put(root, "geometry/fixture.json", {"hash_only_native_fixture": True})
    metadata = {"job_id": root.name, "sources": [{"kind": "reference", **reference}]}
    before = _put(root, "job.json", metadata)
    intent = _put(
        root,
        "analysis/attachment_intent.json",
        {
            "schema_version": "0.1.0",
            "contract_kind": "surface_attachment_intent",
            "job_id": root.name,
            "source_reference": reference,
            "source_modeling_plan": plan,
            "source_scene": scene,
            "source_geometry": [geometry],
            "entries": [
                {
                    "attachment_id": "fixture",
                    "scope": "intentional_open",
                    "subject_lower": {"semantic_id": "fixture", "face_group_id": "fixture"},
                    "exception_reason": "Native entrypoint fixture only; no mechanical claim.",
                }
            ],
        },
    )
    registration = _put(
        root,
        REGISTRATION_PATH,
        {
            "schema_version": "0.1.0",
            "kind": "surface_attachment_registration",
            "job_id": root.name,
            "attachment_intent": intent,
            "metadata_before_sha256": before["sha256"],
        },
    )
    _put(
        root,
        "job.json",
        {
            **metadata,
            "attachment_intent": intent,
            "attachment_registration_sha256": registration["sha256"],
        },
    )
    proof = collect_build_provenance(root, root.name, validate_contracts=False)
    blend, glb = root / "fixture.blend", root / "fixture.glb"
    payload = _put(
        root,
        "fixture_input.json",
        {
            "blend": str(blend),
            "glb": str(glb),
            "proof": proof,
            "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "faces": [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]],
        },
    )
    creator = root / "create_fixture.py"
    creator.write_text(
        """import bpy, json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_bytes())
bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("fixture")
mesh.from_pydata(data["vertices"], [], data["faces"])
mesh.update()
obj = bpy.data.objects.new("fixture", mesh)
bpy.context.collection.objects.link(obj)
obj["cbm_id"] = "fixture"
obj["cbm_asset_role"] = "render"
obj["cbm_lod_level"] = 0
obj["cbm_instance_index"] = 0
material = bpy.data.materials.new("mat.fixture")
material.use_nodes = True
material["cbm_id"] = "mat.fixture"
mesh.materials.append(material)
bpy.context.scene["cbm_build_provenance"] = json.dumps(data["proof"])
bpy.context.scene["cbm_portable_source_build_fingerprint"] = data["proof"]["fingerprint"]
bpy.ops.wm.save_as_mainfile(filepath=data["blend"])
bpy.ops.export_scene.gltf(filepath=data["glb"], export_format="GLB", export_extras=True)
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
            str(root / payload["path"]),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    snapshots = []
    for stage, artifact in (("native_evaluated", blend), ("clean_import_glb", glb)):
        output = root / (stage + ".json")
        artifact_hash = _sha(artifact)
        result = run_blender(
            "inspect_surface_attachment_geometry.py",
            [
                "--job-root",
                str(root),
                "--artifact",
                str(artifact),
                "--artifact-sha256",
                artifact_hash,
                "--source-fingerprint",
                "1" * 64,
                "--build-fingerprint",
                proof["fingerprint"],
                "--intent-sha256",
                intent["sha256"],
                "--stage",
                stage,
                "--output",
                str(output),
            ],
            blend_file=blend if stage == "native_evaluated" else None,
            factory_startup=stage == "clean_import_glb",
            disable_autoexec=True,
        )
        assert "--python-use-system-env" not in result.args
        assert result.args[result.args.index("--python") + 1] == str(
            settings.repo_root
            / "src/codex_blender_modeler/blender_scripts/inspect_surface_attachment_geometry.py"
        )
        snapshot = json.loads(output.read_bytes())
        assert snapshot["stage"] == stage and snapshot["triangle_count"] == 4
        assert snapshot["build_fingerprint"] == proof["fingerprint"]
        assert snapshot["intent_sha256"] == intent["sha256"]
        assert snapshot["artifact"]["sha256"] == artifact_hash == _sha(artifact)
        assert [item["semantic_id"] for item in snapshot["objects"]] == ["fixture"]
        snapshots.append(snapshot)
    assert snapshots[0]["objects"] == snapshots[1]["objects"]
