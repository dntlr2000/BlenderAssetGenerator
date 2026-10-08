"""Synthetic authored solid-root split fixtures grant no production authority."""

from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import UTC, datetime

import pytest
import test_guarded_attachment_revision as guarded
import test_surface_attachment_host as mesh_fixture

from codex_blender_modeler import authored_split_runtime as runtime
from codex_blender_modeler.analysis.models import ModelingPlan
from codex_blender_modeler.attachment_runtime import selected_attachment
from codex_blender_modeler.blender_artifacts import deterministic_json_bytes, sha256_file
from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.config import get_settings
from codex_blender_modeler.material_identity_split import authored_service as service
from codex_blender_modeler.material_identity_split import authored_transaction as transaction
from codex_blender_modeler.material_identity_split.authored_models import (
    AuthoredMaterialIdentitySplitApplyIntentV02,
    AuthoredMaterialIdentitySplitApprovalV02,
    MaterialIdentityCloneRuleV02,
)
from codex_blender_modeler.materials.models import MaterialPlan
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.packaging import attachment as host


def authored_job(
    tmp_path,
    monkeypatch,
    *,
    clones=3,
    native=False,
    textures=False,
    spatial=False,
    extra_materials=0,
):
    """Create a new synthetic registered source with multiple exact details per clone."""
    with monkeypatch.context() as setup:
        setup.setattr(host, "register_solid_root_attachment_intent", lambda *args, **kwargs: None)
        root = guarded._job(tmp_path, monkeypatch)
    scene = json.loads((root / "analysis/scene_spec.json").read_bytes())
    model = json.loads((root / "analysis/modeling_plan.json").read_bytes())
    original = json.loads((root / "analysis/initial_solid_intent.json").read_bytes())
    owner, relief = scene["objects"]
    objects, geometries, entries = [owner], [original["source_geometry"][0]], []
    rules, details = [], []
    for ordinal in range(clones):
        name = f"pendant_{ordinal}"
        obj = copy.deepcopy(relief)
        obj["id"] = name
        payload = json.loads((root / relief["geometry"]["path"]).read_bytes())
        payload["semantic_id"] = name
        # Valid nondegenerate per-face UVs make exact native source UV proof meaningful.
        payload["loop_uvs"] = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]] * len(payload["faces"])
        ref = mesh_fixture.put(root, f"geometry/{name}.json", payload)
        obj["geometry"]["path"] = ref["path"]
        objects.append(obj)
        geometries.append(ref)
        entry = copy.deepcopy(original["entries"][0])
        entry["attachment_id"] = f"root_{ordinal}"
        entry["subject_semantic_id"] = name
        entries.append(entry)
        ids = [f"detail.{ordinal}.atlas", f"detail.{ordinal}.micro"]
        for detail in ids:
            details.append(
                {
                    "id": detail,
                    "label": detail,
                    "parent_object_id": name,
                    "representation": "texture_channels",
                    "target_material_id": "mat.shared",
                    "channels": ["roughness"],
                    "uv_strategy": "existing_uv",
                    "notes": ["Synthetic evidence only."],
                }
            )
        rules.append(
            MaterialIdentityCloneRuleV02(
                source_material_id="mat.shared",
                new_material_id=f"mat.clone_{ordinal}",
                target_object_id=name,
                surface_detail_ids=ids,
            )
        )
    owner_payload = json.loads((root / owner["geometry"]["path"]).read_bytes())
    owner_payload["loop_uvs"] = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]] * len(owner_payload["faces"])
    geometries[0] = mesh_fixture.put(root, owner["geometry"]["path"], owner_payload)
    extra_items = []
    for ordinal in range(extra_materials):
        name, material_id = f"retained_{ordinal}", f"mat.retained_{ordinal}"
        obj = copy.deepcopy(owner)
        obj.update(id=name, material_id=material_id)
        payload = runtime.derivative_payload(
            owner_payload,
            {"source_material_id": "mat.shared", "new_material_id": material_id},
            geometries[0],
        )
        payload["semantic_id"] = name
        ref = mesh_fixture.put(root, f"geometry/{name}.json", payload)
        obj["geometry"]["path"] = ref["path"]
        objects.append(obj)
        geometries.append(ref)
        material_spec = copy.deepcopy(scene["materials"][0])
        material_spec["id"] = material_id
        scene["materials"].append(material_spec)
        extra_items.append({"material_id": material_id, "label": name})
        entry = copy.deepcopy(original["entries"][0])
        entry["attachment_id"] = f"retained_root_{ordinal}"
        entry["subject_semantic_id"] = name
        entries.append(entry)
    material_item = {"material_id": "mat.shared", "label": "Synthetic shared glass"}
    if textures:
        import hashlib
        import struct

        from PIL import Image

        from codex_blender_modeler.materials.models import ShaderRecipe
        from codex_blender_modeler.texturing.models import TextureManifest

        texture_root = root / "materials/shared/images"
        texture_root.mkdir(parents=True)
        Image.new("RGB", (16, 16), (128, 128, 128)).save(texture_root / "roughness.png")
        Image.new("RGB", (16, 16), (128, 128, 255)).save(texture_root / "normal.png")
        bindings = []
        for detail in details:
            mesh = json.loads((root / f"geometry/{detail['parent_object_id']}.json").read_bytes())
            digest = hashlib.sha256(struct.pack(">Q", len(mesh["faces"])))
            loop = 0
            for polygon, face in enumerate(mesh["faces"]):
                digest.update(struct.pack(">QQQ", polygon, loop, len(face)))
                for vertex in face:
                    values = [
                        struct.unpack("f", struct.pack("f", float(n)))[0]
                        for n in [*mesh["vertices"][vertex], *mesh["loop_uvs"][loop]]
                    ]
                    digest.update(struct.pack(">Qddddd", vertex, *values))
                    loop += 1
            bindings.append(
                {
                    "detail_id": detail["id"],
                    "parent_object_id": detail["parent_object_id"],
                    "material_id": "mat.shared",
                    "uv_set": "UVMap",
                    "uv_layout_sha256": digest.hexdigest(),
                    "placement": {"mode": "uv_rect", "uv_rect": [0.0, 0.0, 1.0, 1.0]},
                    "channels": ["roughness"],
                }
            )
        manifest = TextureManifest.model_validate_json(
            json.dumps(
                {
                    "material_id": "mat.shared",
                    "uv_set": "UVMap",
                    "intended_scale_m": 1.0,
                    "resolution": [16, 16],
                    "source_type": "image",
                    "channels": {
                        "roughness": {
                            "source": "image",
                            "path": "images/roughness.png",
                            "color_space": "Non-Color",
                        },
                        "normal": {
                            "source": "image",
                            "path": "images/normal.png",
                            "color_space": "Non-Color",
                        },
                    },
                    "surface_detail_ids": [item["id"] for item in details],
                    "surface_detail_bindings": bindings,
                    "shader_recipe": "shader_recipe.json",
                    "provenance": {
                        "provider": "synthetic-only",
                        "generated_sha256": {
                            "roughness": sha256_file(texture_root / "roughness.png"),
                            "normal": sha256_file(texture_root / "normal.png"),
                        },
                    },
                }
            )
        )
        recipe = ShaderRecipe.model_validate(
            {
                "material_id": "mat.shared",
                "surface": {"roughness": 0.35, "transmission_weight": 0.35},
                "mapping": {"mode": "uv", "uv_set": "UVMap"},
                "texture_manifest": "materials/shared/texture_manifest.json",
            }
        )
        volume_recipe = recipe.model_dump(mode="json")
        volume_recipe.update(
            schema_version="0.5.1",
            volume={
                "schema_version": "0.1.0",
                "thickness_factor": 0.44,
                "attenuation_distance": 2.5,
                "attenuation_color": [0.7, 0.9, 0.8],
            },
        )
        recipe = ShaderRecipe.model_validate_json(json.dumps(volume_recipe))
        mesh_fixture.put(
            root,
            "materials/shared/texture_manifest.json",
            manifest.model_dump(mode="json", exclude_none=True),
        )
        mesh_fixture.put(
            root, "materials/shared/shader_recipe.json", recipe.model_dump(mode="json")
        )
        scene["materials"][0]["texture_manifest"] = "materials/shared/texture_manifest.json"
        material_item.update(
            texture_strategy="image",
            texture_manifest="materials/shared/texture_manifest.json",
            shader_recipe="materials/shared/shader_recipe.json",
            mapping={"mode": "uv", "uv_set": "UVMap"},
        )
    scene["objects"] = objects
    model["objects"] = [{"id": item["id"], "label": item["id"]} for item in objects]
    if spatial:
        model["assembly_consistency_policy"] = "spatial_v1"
        model["assembly_frame"] = {
            "root_object_id": owner["id"],
            "longitudinal_axis": "X",
            "lateral_axis": "Y",
            "vertical_axis": "Z",
            "symmetry": "unknown",
            "evidence_status": "inferred",
        }
        model["assembly_relationships"] = []
        for item in model["objects"]:
            item["assembly_role"] = "root" if item["id"] == owner["id"] else "free_standing"
    model["surface_details"] = details
    model["surface_detail_policy"] = {"mode": "explicit"}
    model = ModelingPlan.model_validate_json(json.dumps(model)).model_dump(mode="json")
    scene = SceneSpec.model_validate(scene).model_dump(mode="json")
    mesh_fixture.put(root, "analysis/scene_spec.json", scene)
    mesh_fixture.put(root, "analysis/modeling_plan.json", model)
    original.update(
        source_geometry=geometries,
        entries=entries,
        required_semantics=[item["id"] for item in objects],
    )
    original["source_scene"]["sha256"] = sha256_file(root / "analysis/scene_spec.json")
    original["source_modeling_plan"]["sha256"] = sha256_file(root / "analysis/modeling_plan.json")
    selection = mesh_fixture.put(root, "analysis/initial_solid_intent.json", original)
    (root / "blender/scene.blend").rename(root / "synthetic_initial_placeholder.blend")
    host.register_solid_root_attachment_intent(
        root.name, intent_path=selection["path"], intent_sha256=selection["sha256"]
    )
    (root / "blender/scene.blend").write_bytes(
        (root / "synthetic_initial_placeholder.blend").read_bytes()
    )
    material = MaterialPlan.model_validate(
        {"job_id": root.name, "stage": "authored", "materials": [material_item, *extra_items]}
    )
    mesh_fixture.put(root, "analysis/material_plan.json", material.model_dump(mode="json"))
    if native:
        run_blender(
            "build_scene.py",
            [
                "--spec",
                str(root / "analysis/scene_spec.json"),
                "--output",
                str(root / "blender/scene.blend"),
                "--material-plan-mode",
                "current" if textures else "scene_spec_only",
            ],
            factory_startup=True,
            disable_autoexec=True,
        )
    return root, rules


def prepared(
    tmp_path,
    monkeypatch,
    *,
    native=False,
    run_id="split01",
    textures=False,
    delegated=False,
    spatial=False,
    extra_materials=0,
):
    """Prepare one source-only plan while keeping real authority completely absent."""
    root, rules = authored_job(
        tmp_path,
        monkeypatch,
        native=native,
        textures=textures,
        spatial=spatial,
        extra_materials=extra_materials,
    )
    delegation = fixture_delegation(root, run_id, rules) if delegated else None
    publication = service.prepare_authored_material_identity_split(
        root,
        run_id=run_id,
        clone_rules=rules,
        source_material_plan_mode="current" if textures else "scene_spec_only",
        delegation_path=delegation["path"] if delegation else None,
    )
    return root, publication


def fixture_approval(root, request_ref):
    """Supply explicitly synthetic user decision bytes only to synthetic test jobs."""
    request = runtime.contract(root, request_ref, "request")
    text = b"TEST FIXTURE ONLY. Exact specialized material_identity_split approved.\r\n"
    approval = AuthoredMaterialIdentitySplitApprovalV02(
        job_id=root.name,
        run_id=request["run_id"],
        approval_id="synthetic-approval",
        decision="approved",
        user_decision_text_sha256=runtime.sha(text),
        decision_observed_at=datetime.now(UTC),
        approval_request=request_ref,
        **{
            key: request[key] for key in ("plan", "preapproval", "invariant_report", "shadow_blend")
        },
    )
    publication = service.publish_authored_material_identity_split_approval(
        root,
        approval_request_path=request_ref["path"],
        approval=approval,
        user_decision=text,
        explicit_user_decision_observed=True,
    )
    return AuthoredMaterialIdentitySplitApplyIntentV02(
        job_id=root.name,
        run_id=request["run_id"],
        intent_id="synthetic-apply",
        approval=publication["approval"],
        approval_request=request_ref,
        plan=request["plan"],
        user_decision=publication["user_decision"],
    )


def test_authored_plan_preserves_all_source_bytes_and_three_exclusive_clones(tmp_path, monkeypatch):
    """Three new IDs and six detail changes preserve the retained source and authored plan."""
    root, rules = authored_job(tmp_path, monkeypatch)
    before = {path: (root / path).read_bytes() for path in runtime.SOURCE_PATHS}
    result = service.prepare_authored_material_identity_split(
        root, run_id="split01", clone_rules=rules, source_material_plan_mode="scene_spec_only"
    )
    checked = service.validate_authored_split_plan(root, result["plan_artifact"])
    assert {path: (root / path).read_bytes() for path in before} == before
    assert len(checked["candidates"]["candidate_scene_spec"]["materials"]) == 4
    assert (
        checked["candidates"]["candidate_scene_spec"]["objects"][0]["material_id"] == "mat.shared"
    )
    assert len(checked["plan"]["clone_rules"]) == 3
    assert not (root / runtime.prefix("split01") / "approval.json").exists()
    for old, new in zip(
        json.loads(before["analysis/modeling_plan.json"])["surface_details"],
        checked["candidates"]["candidate_modeling_plan"]["surface_details"],
        strict=True,
    ):
        assert {key: value for key, value in old.items() if key != "target_material_id"} == {
            key: value for key, value in new.items() if key != "target_material_id"
        }
        assert old["target_material_id"] != new["target_material_id"]


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_AUTHORED_SPLIT_NATIVE") != "1",
    reason="explicit native authored-split smoke opt-in",
)
@pytest.mark.parametrize("textures", [False, True])
@pytest.mark.parametrize("delegated", [False, True])
def test_authored_split_real_native_commit_and_stdlib_reader(
    tmp_path, monkeypatch, textures, delegated
):
    """Actual Blender prepares exact geometry-only output before synthetic specialized approval."""
    assert shutil.which(get_settings().blender_bin)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    root, publication = prepared(
        tmp_path, monkeypatch, native=True, textures=textures, delegated=delegated, spatial=textures
    )
    before = {path: (root / path).read_bytes() for path in runtime.SOURCE_PATHS}
    result = service.run_authored_material_identity_split_preapproval(
        root, plan_path=publication["plan_artifact"]["path"]
    )
    assert {path: (root / path).read_bytes() for path in before} == before
    intent = (
        fixture_technical_approval(root, result["approval_request"])
        if delegated
        else fixture_approval(root, result["approval_request"])
    )
    applied = transaction.apply_authored_material_identity_split(root, intent=intent)
    assert applied["status"] == "committed"
    checked = runtime.validate_transaction(root, intent.run_id)
    assert (
        selected_attachment(root, root.name, root / "analysis/scene_spec.json")
        == checked["plan"]["candidate_attachment_intent"]
    )
    assert (
        runtime.collect_preserved_authored_split_provenance(root)
        == checked["candidates"]["prospective_build_provenance"]
    )
    assert (root / "analysis/material_plan.json").read_bytes() == before[
        "analysis/material_plan.json"
    ]
    # Exercise the committed mixed-domain reader in Blender's own site-free Python.
    import subprocess
    from pathlib import Path

    executable = Path(get_settings().blender_bin)
    source_root = Path(__file__).resolve().parents[1] / "src"
    script = (
        "import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
        "from codex_blender_modeler.attachment_runtime import selected_attachment;"
        "from codex_blender_modeler.build_provenance import collect_build_provenance;"
        "root=Path(sys.argv[2]);selected_attachment(root,root.name,root/'analysis/scene_spec.json');"
        "from codex_blender_modeler import authored_split_runtime as ar;"
        "ar.collect_preserved_authored_split_provenance(root);"
        "print('committed-stdlib-ok')"
    )
    bundled = executable.parent / "5.0/python/bin/python3.11"
    read_result = subprocess.run(
        [str(bundled), "-S", "-c", script, str(source_root), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert read_result.returncode == 0, read_result.stderr
    assert "committed-stdlib-ok" in read_result.stdout
    probe = root.parent / "synthetic_committed_probe.py"
    probe.write_text(
        """import bpy, json, runpy, sys
from pathlib import Path
args=sys.argv[sys.argv.index('--')+1:]
root, source=map(Path,args)
sys.path.insert(0,str(source))
from codex_blender_modeler import authored_split_runtime as runtime
from codex_blender_modeler.build_provenance import collect_build_provenance
checked=runtime.validate_transaction(root,'split01')
expected=runtime.collect_preserved_authored_split_provenance(root)
assert json.loads(bpy.context.scene['cbm_build_provenance'])==expected
functions=runpy.run_path(str(source/'codex_blender_modeler/blender_scripts/authored_split_native.py'),run_name='fixture_probe')
original=json.loads(runtime.read(root,checked['preapproval']['candidate_native_inventory']))
for key,value in functions['inventory']().items():
    assert runtime.stable(value)==runtime.stable(original[key]),key
assert functions['material_images'](root)==original['material_images']
assert functions['native_materials'](root)==original['native_materials']
assert functions['render_state'](root)==original['render_state_sha256']
assert functions['scalar']({'nested': {'factor': 1}})!={'nested': {'factor': 2}}
for material in bpy.data.materials:
    if 'cbm_optical_volume_contract' in material:
        shader=next(n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        assert shader.inputs['Transmission Weight'].default_value==0.3499999940395355
        assert any(n.type=='VOLUME_ABSORPTION' for n in material.node_tree.nodes)
        assert any(n.type=='NORMAL_MAP' for n in material.node_tree.nodes)
print('committed-native-ok')
""",
        encoding="utf-8",
    )
    native_result = subprocess.run(
        [
            str(executable),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            str(root / "blender/scene.blend"),
            "--python-exit-code",
            "1",
            "--python",
            str(probe),
            "--",
            str(root),
            str(source_root),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert native_result.returncode == 0, native_result.stdout + native_result.stderr
    assert "committed-native-ok" in native_result.stdout
    for script_name, args in (
        ("inspect_scene.py", ["--output", str(root / "reports/post_split_inventory.json")]),
        (
            "validate_scene.py",
            [
                "--spec",
                str(root / "analysis/scene_spec.json"),
                "--output",
                str(root / "reports/post_split_validation.json"),
            ],
        ),
    ):
        run_blender(
            script_name,
            args,
            blend_file=root / "blender/scene.blend",
            factory_startup=True,
            disable_autoexec=True,
        )
    assert json.loads((root / "reports/post_split_validation.json").read_bytes())["ok"]
    for ordinal, derivative in enumerate(checked["plan"]["derivatives"]):
        payload = derivative["candidate"]
        run_blender(
            "inspect_custom_mesh_v02.py",
            [
                "--job-root",
                str(root),
                "--payload",
                str(root / payload["path"]),
                "--payload-sha256",
                payload["sha256"],
                "--semantic-id",
                derivative["object_id"],
                "--report",
                str(root / f"reports/post_split_mesh_{ordinal}.json"),
            ],
            blend_file=root / "blender/scene.blend",
            factory_startup=True,
            disable_autoexec=True,
        )
    selection = checked["plan"]["candidate_attachment_intent"]
    document = checked["new"]
    bound = mesh_fixture.source(
        mesh_fixture.HashedArtifact(id="source.attachment_intent", kind="other", **selection)
    ).model_copy(
        update={
            "build_fingerprint": checked["candidates"]["prospective_build_provenance"][
                "fingerprint"
            ],
            "scene_spec": mesh_fixture.HashedArtifact(
                id="scene_spec", kind="scene_spec", **document["source_scene"]
            ),
            "geometry_payloads": [
                mesh_fixture.HashedArtifact(id=f"geometry.{i}", kind="geometry_payload", **item)
                for i, item in enumerate(document["source_geometry"])
            ],
        }
    )
    report = host.inspect_stage(
        root,
        bound,
        root / "blender/scene.blend",
        "native_evaluated",
        root / "reports/post_split_attachment.json",
    )
    assert report["status"] == "passed"
    assert report["actual_triangle_extraction_verified"] is True
    # Ordinary recipe-skipping construction must never share the preserved-graph fingerprint.
    ordinary = collect_build_provenance(root, root.name, material_plan_mode="scene_spec_only")
    assert (
        ordinary["fingerprint"]
        != runtime.collect_preserved_authored_split_provenance(root)["fingerprint"]
    )
    with pytest.raises(FileExistsError):
        transaction.apply_authored_material_identity_split(root, intent=intent)
    # Derived Blend rebuilds must not invalidate the archived native/approval chain.
    (root / "blender/scene.blend").write_bytes(b"synthetic later native material rebuild")
    assert (
        selected_attachment(root, root.name, root / "analysis/scene_spec.json")
        == checked["plan"]["candidate_attachment_intent"]
    )
    (root / "NATIVE_RESULT.json").write_bytes(
        deterministic_json_bytes(
            {
                "status": "passed",
                "production_authority_created": False,
                "receipt": applied["receipt"],
            }
        )
    )


def synthetic_preapproval(root, plan_ref):
    """Build binding-only fixture evidence; this helper makes no claim of native execution."""
    import struct

    from codex_blender_modeler.material_identity_split import authored_models as contracts

    checked = runtime.validate_plan(root, plan_ref)
    plan, base = checked["plan"], runtime.prefix(checked["plan"]["run_id"])
    identity = {"job_id": root.name, "run_id": plan["run_id"], "profile": plan["profile"]}
    source_meshes = {
        json.loads(runtime.read(root, ref))["semantic_id"]: json.loads(runtime.read(root, ref))
        for ref in checked["old"]["source_geometry"]
    }
    native_refs = {}
    blend = service.publish(
        root, f"{base}/shadow/final.blend", b"SYNTHETIC TEST NATIVE BINDING; NOT BLENDER EVIDENCE"
    )
    scripts = {}
    for name in service.NATIVE_SCRIPTS:
        content = (
            get_settings().repo_root / "src/codex_blender_modeler/blender_scripts" / name
        ).read_bytes()
        service.publish(root, f"{base}/native_scripts/{name}", content)
        scripts[f"src/codex_blender_modeler/blender_scripts/{name}"] = runtime.sha(content)
    for stage in ("source", "candidate"):
        scene = (
            json.loads(checked["sources"]["analysis/scene_spec.json"])
            if stage == "source"
            else checked["candidates"]["candidate_scene_spec"]
        )
        objects = {}
        for obj in scene["objects"]:
            payload = source_meshes[obj["id"]]
            vertices = [
                [struct.unpack("f", struct.pack("f", float(n)))[0] for n in vertex]
                for vertex in payload["vertices"]
            ]
            uvs = [
                [struct.unpack("f", struct.pack("f", float(n)))[0] for n in uv]
                for uv in payload["loop_uvs"]
            ]
            geometry = {
                "vertices_sha256": runtime.stable(vertices),
                "faces_sha256": runtime.stable(payload["faces"]),
                "uv_layers_sha256": runtime.stable([{"name": "UVMap", "uvs": uvs}]),
                "polygon_material_indices_sha256": runtime.stable(
                    payload["polygon_material_indices"]
                ),
                "smooth_polygon_flags_sha256": runtime.stable(payload["smooth_polygon_flags"]),
                "sharp_edges_sha256": runtime.stable(
                    sorted(edge["vertices"] for edge in payload["sharp_edges"])
                ),
                "uv_seams_sha256": runtime.stable(
                    sorted(edge["vertices"] for edge in payload["uv_seams"])
                ),
                "vertex_count": len(vertices),
                "face_count": len(payload["faces"]),
                "loop_count": payload["loop_count"],
                "active_uv": "UVMap",
                "uv_layer_names": ["UVMap"],
                "full_geometry_sha256": runtime.stable(payload),
            }
            objects[obj["id"]] = {
                "name": obj["id"],
                "matrix_world": [[1.0 if a == b else 0.0 for b in range(4)] for a in range(4)],
                "dimensions": [1.0, 1.0, 1.0],
                "raw_mesh": geometry,
                "evaluated_mesh": geometry,
                "materials": [obj["material_id"]],
                "native_custom": runtime.native_mesh_metadata(
                    json.loads((root / obj["geometry"]["path"]).read_bytes()),
                    runtime.reference(root, obj["geometry"]["path"]),
                ),
            }
        from codex_blender_modeler.authored_material_runtime import manifest_member

        images = {}
        for material in scene["materials"]:
            refs = {}
            if material.get("texture_manifest"):
                manifest = json.loads((root / material["texture_manifest"]).read_bytes())
                for channel in manifest["channels"].values():
                    if channel.get("source") == "image":
                        path = manifest_member(root, material["texture_manifest"], channel["path"])
                        refs[path] = runtime.reference(root, path)
            images[material["id"]] = [refs[key] for key in sorted(refs)]
        native_refs[stage] = service.publish(
            root,
            f"{base}/{stage}_native.json",
            {
                "schema_version": "0.2.0",
                **identity,
                "plan": plan_ref,
                "stage": stage,
                "blender_version": "5.0.1",
                "blender_executable_sha256": "f" * 64,
                "native_script_sha256": scripts[
                    "src/codex_blender_modeler/blender_scripts/authored_split_native.py"
                ],
                "blend": {
                    "path": "blender/scene.blend",
                    "sha256": plan["source_files"]["blender/scene.blend"]["sha256"],
                }
                if stage == "source"
                else blend,
                "build_provenance": checked["candidates"][
                    "source_build_provenance"
                    if stage == "source"
                    else "prospective_build_provenance"
                ],
                "material_images": images,
                "native_materials": {
                    material["id"]: {
                        "graph_sha256": "a" * 64,
                        "settings_sha256": "b" * 64,
                        "custom": {"cbm_id": material["id"]},
                    }
                    for material in scene["materials"]
                },
                "render_state_sha256": "c" * 64,
                "scene_custom": {}
                if stage == "source"
                else runtime.cloned_native_scene_metadata(
                    {},
                    plan,
                    checked["candidates"]["prospective_build_provenance"],
                    objects,
                ),
                "objects": objects,
                "cameras": [],
                "lights": [],
                "active_camera": None,
                "appearance_or_human_acceptance": False,
            },
        )
    invariants = service.publish(
        root,
        f"{base}/invariants.json",
        contracts.AuthoredMaterialIdentitySplitInvariantsV02(
            **identity,
            plan=plan_ref,
            source_native_inventory=native_refs["source"],
            candidate_native_inventory=native_refs["candidate"],
            root_proofs=plan["root_proofs"],
        ),
    )
    preapproval = service.publish(
        root,
        f"{base}/preapproval.json",
        contracts.AuthoredMaterialIdentitySplitPreapprovalV02(
            **identity,
            plan=plan_ref,
            blender_executable_sha256="f" * 64,
            native_script_sha256=scripts,
            source_native_inventory=native_refs["source"],
            candidate_native_inventory=native_refs["candidate"],
            shadow_validation=service.publish(
                root, f"{base}/shadow/validation.json", {"ok": True, "test_only": True}
            ),
            shadow_scene_inventory=service.publish(
                root,
                f"{base}/shadow/scene_inventory.json",
                {"blender_version": "5.0.1", "test_only": True},
            ),
            shadow_blend=blend,
            invariant_report=invariants,
        ),
    )
    request_model = (
        contracts.AuthoredMaterialIdentitySplitTechnicalApprovalRequestV02
        if plan["profile"] == runtime.DELEGATED_PROFILE
        else contracts.AuthoredMaterialIdentitySplitApprovalRequestV02
    )
    request = service.publish(
        root,
        f"{base}/approval_request.json",
        request_model(
            **identity,
            plan=plan_ref,
            preapproval=preapproval,
            invariant_report=invariants,
            shadow_blend=blend,
        ),
    )
    runtime.validate_request(root, request, current=True)
    return request


@pytest.fixture(scope="module", params=[False, True], ids=["direct_user", "delegated_technical"])
def authored_template(tmp_path_factory, request):
    """Freeze one synthetic binding-only authority fixture for independent copied negatives."""
    with pytest.MonkeyPatch.context() as patch:
        delegated = request.param
        root, publication = prepared(
            tmp_path_factory.mktemp("authored_template"), patch, delegated=delegated
        )
        approval_request = synthetic_preapproval(root, publication["plan_artifact"])
        intent = (
            fixture_technical_approval(root, approval_request)
            if delegated
            else fixture_approval(root, approval_request)
        )
    return root, intent


@pytest.fixture
def authorized_copy(tmp_path, monkeypatch, authored_template):
    """Copy a synthetic test job and bind its host lock to the exact copied workspace."""
    from codex_blender_modeler import workspace

    template, intent = authored_template
    root = tmp_path / template.name
    shutil.copytree(template, root)
    monkeypatch.setattr(
        workspace, "job_dir", lambda job_id: root if job_id == root.name else tmp_path / job_id
    )
    return root, intent


@pytest.mark.parametrize(
    "checkpoint",
    [
        "after_apply_intent",
        "after_global_consumption",
        "after_consumption",
        "after_journal",
        "after_scene",
        "after_model",
        "after_job",
        "after_blend",
        "before_receipt",
    ],
)
def test_four_file_crashes_block_readers_and_recover_exactly(
    authorized_copy, monkeypatch, checkpoint
):
    """Every logical consumption/write boundary remains blocked until exact owned rollback."""
    from codex_blender_modeler.orchestration.paired_revision import assert_no_pending_pair

    root, intent = authorized_copy
    before = {path: (root / path).read_bytes() for path in runtime.SOURCE_PATHS}

    def fail(name):
        """Interrupt only the selected synthetic publication boundary."""
        if name == checkpoint:
            raise RuntimeError("synthetic crash")

    monkeypatch.setattr(transaction, "_checkpoint", fail)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        transaction.apply_authored_material_identity_split(root, intent=intent)
    for check in (
        lambda: selected_attachment(root, root.name, root / "analysis/scene_spec.json"),
        lambda: collect_build_provenance(root, root.name, material_plan_mode="scene_spec_only"),
        lambda: assert_no_pending_pair(root),
    ):
        with pytest.raises((ValueError, FileNotFoundError)):
            check()
    monkeypatch.setattr(transaction, "_checkpoint", lambda name: None)
    digest = sha256_file(root / runtime.prefix(intent.run_id) / "apply_intent.json")
    result = transaction.recover_authored_material_identity_split(
        root, run_id=intent.run_id, apply_intent_sha256=digest
    )
    assert result["status"] == "rolled_back"
    assert {path: (root / path).read_bytes() for path in before} == before
    selected_attachment(root, root.name, root / "analysis/scene_spec.json")
    with pytest.raises(FileExistsError):
        transaction.apply_authored_material_identity_split(root, intent=intent)
    with pytest.raises(FileExistsError):
        transaction.recover_authored_material_identity_split(
            root, run_id=intent.run_id, apply_intent_sha256=digest
        )


@pytest.mark.parametrize(
    "checkpoint",
    [
        "recovery_started",
        "recovery_after_scene",
        "recovery_after_model",
        "recovery_after_job",
        "recovery_after_blend",
    ],
)
def test_interrupted_recovery_is_exactly_resumable(authorized_copy, monkeypatch, checkpoint):
    """Rollback interruption preserves all archives and the same one-use claim."""
    root, intent = authorized_copy
    before = {path: (root / path).read_bytes() for path in runtime.SOURCE_PATHS}

    def crash_apply(name):
        """Leave one genuine synthetic partial four-file transaction."""
        if name == "after_job":
            raise RuntimeError("synthetic crash")

    monkeypatch.setattr(transaction, "_checkpoint", crash_apply)
    with pytest.raises(RuntimeError):
        transaction.apply_authored_material_identity_split(root, intent=intent)
    digest = sha256_file(root / runtime.prefix(intent.run_id) / "apply_intent.json")

    def crash_recovery(name):
        """Interrupt one selected rollback checkpoint, retaining exact restored state."""
        if name == checkpoint:
            raise RuntimeError("synthetic recovery crash")

    monkeypatch.setattr(transaction, "_checkpoint", crash_recovery)
    with pytest.raises(RuntimeError):
        transaction.recover_authored_material_identity_split(
            root, run_id=intent.run_id, apply_intent_sha256=digest
        )
    monkeypatch.setattr(transaction, "_checkpoint", lambda name: None)
    transaction.recover_authored_material_identity_split(
        root, run_id=intent.run_id, apply_intent_sha256=digest
    )
    assert {path: (root / path).read_bytes() for path in before} == before


@pytest.mark.parametrize(
    "path",
    [*sorted(runtime.SOURCE_PATHS), "evidence/source.json", "analysis/camera_hypothesis.json"],
)
def test_stale_source_cannot_consume_specialized_approval(authorized_copy, path):
    """Any preserved source/canonical edit fails before authority consumption."""
    root, intent = authorized_copy
    (root / path).write_bytes((root / path).read_bytes() + b"\n")
    with pytest.raises(ValueError):
        transaction.apply_authored_material_identity_split(root, intent=intent)
    assert not (root / runtime.prefix(intent.run_id) / "apply_intent.json").exists()


@pytest.mark.parametrize(
    "path",
    [
        "candidate/scene.json",
        "candidate/model.json",
        "candidate/job.json",
        "candidate/mesh_000.json",
        "candidate/attachment.json",
        "candidate/revision.json",
        "candidate/root_proofs.json",
        "candidate/provenance.json",
        "source_native.json",
        "candidate_native.json",
        "shadow/final.blend",
        "preapproval.json",
        "invariants.json",
        "approval_request.json",
        "approval.json",
        "user_decision.txt",
    ],
)
def test_tampered_candidate_or_authority_never_consumes(authorized_copy, path):
    """Every link from source candidate to exact user bytes is hash-bound before apply."""
    root, intent = authorized_copy
    if intent.profile == runtime.DELEGATED_PROFILE:
        path = {
            "approval.json": "technical_approval.json",
            "user_decision.txt": "technical_decision.txt",
        }.get(path, path)
    target = root / runtime.prefix(intent.run_id) / path
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        transaction.apply_authored_material_identity_split(root, intent=intent)
    assert not (root / runtime.prefix(intent.run_id) / "apply_intent.json").exists()


@pytest.mark.parametrize(
    "path",
    [
        "job.json",
        "analysis/scene_spec.json",
        "analysis/modeling_plan.json",
        "blender/scene.blend",
        "analysis/material_plan.json",
    ],
)
def test_concurrent_edits_survive_refused_recovery(authorized_copy, monkeypatch, path):
    """Recovery never overwrites a concurrent third state or changed preserved MaterialPlan."""
    root, intent = authorized_copy

    def fail(name):
        """Interrupt immediately after the first canonical replacement."""
        if name == "after_scene":
            raise RuntimeError("synthetic crash")

    monkeypatch.setattr(transaction, "_checkpoint", fail)
    with pytest.raises(RuntimeError):
        transaction.apply_authored_material_identity_split(root, intent=intent)
    concurrent = (root / path).read_bytes() + b"\nconcurrent-user-change\n"
    (root / path).write_bytes(concurrent)
    monkeypatch.setattr(transaction, "_checkpoint", lambda name: None)
    digest = sha256_file(root / runtime.prefix(intent.run_id) / "apply_intent.json")
    with pytest.raises(ValueError):
        transaction.recover_authored_material_identity_split(
            root, run_id=intent.run_id, apply_intent_sha256=digest
        )
    assert (root / path).read_bytes() == concurrent


def test_exact_decision_bytes_and_wrong_lock_root(authorized_copy, monkeypatch):
    """Whitespace is original user evidence and a same-name foreign workspace is no lock."""
    from codex_blender_modeler import workspace

    root, intent = authorized_copy
    _, decision_key = runtime.authority_fields(intent.model_dump(mode="json"))
    assert runtime.read(root, intent.model_dump(mode="json")[decision_key])[-2:] == b"\r\n"
    foreign = root.parent / "foreign" / root.name
    foreign.mkdir(parents=True)
    monkeypatch.setattr(workspace, "job_dir", lambda _: foreign)
    with pytest.raises(ValueError, match="lock target"):
        transaction.apply_authored_material_identity_split(root, intent=intent)


@pytest.mark.parametrize(
    "mutation", ["detail_omitted", "detail_foreign", "same_new", "same_target", "retain_none"]
)
def test_clone_coverage_is_exact_and_exclusive(tmp_path, monkeypatch, mutation):
    """Missing/misassigned details and shared new material identities are forbidden."""
    root, rules = authored_job(tmp_path, monkeypatch)
    values = [rule.model_dump() for rule in rules]
    if mutation == "detail_omitted":
        values[0]["surface_detail_ids"].pop()
    elif mutation == "detail_foreign":
        values[0]["surface_detail_ids"][0] = values[1]["surface_detail_ids"][0]
    elif mutation == "same_new":
        values[1]["new_material_id"] = values[0]["new_material_id"]
    elif mutation == "same_target":
        values[1]["target_object_id"] = values[0]["target_object_id"]
    else:
        values[0]["new_material_id"] = "mat.shared"
    with pytest.raises((ValueError, KeyError)):
        service.prepare_authored_material_identity_split(
            root, run_id="bad", clone_rules=values, source_material_plan_mode="scene_spec_only"
        )


def test_consumed_history_cannot_disappear_with_tip_rollback(authorized_copy):
    """A retained global one-use claim detects a removed run even after exact source rollback."""
    root, intent = authorized_copy
    before = {path: (root / path).read_bytes() for path in runtime.TARGETS.values()}
    transaction.apply_authored_material_identity_split(root, intent=intent)
    for path, content in before.items():
        (root / path).write_bytes(content)
    with pytest.raises(ValueError):
        selected_attachment(root, root.name, root / "analysis/scene_spec.json")
    # Retain removed-run evidence outside the namespace rather than deleting it.
    (root / runtime.prefix(intent.run_id)).rename(root / "preserved_removed_run")
    with pytest.raises(ValueError, match="missing from history"):
        selected_attachment(root, root.name, root / "analysis/scene_spec.json")


def fixture_delegation(root, run_id, rules):
    """Bind synthetic question/reply evidence to one source-only split, never real authority."""
    from codex_blender_modeler.material_identity_split.authored_models import (
        AuthoredMaterialIdentitySplitDelegationV02,
    )

    question = service.publish(
        root,
        f"synthetic_authority/{run_id}/question.txt",
        b"TEST ONLY: May I handle this exact material-only split, "
        b"preserving geometry and roots?\r\n",
    )
    reply = service.publish(
        root,
        f"synthetic_authority/{run_id}/reply.txt",
        b"TEST ONLY: I delegate this bounded technical scope. "
        b"Future exact hashes are not user reviewed.\r\n",
    )
    documents = [
        json.loads((root / path).read_bytes())
        for path in (
            "analysis/scene_spec.json",
            "analysis/modeling_plan.json",
            "analysis/material_plan.json",
            "job.json",
        )
    ]
    value = AuthoredMaterialIdentitySplitDelegationV02(
        original_delegation_id="0" * 64,
        job_id=root.name,
        run_id=run_id,
        delegation_id="synthetic-delegation",
        question=question,
        reply=reply,
        question_message_id="synthetic-question",
        reply_message_id="synthetic-reply",
        delegation_observed_at=datetime.now(UTC),
        source_sha256={
            path: runtime.reference(root, path)["sha256"] for path in runtime.SOURCE_PATHS
        },
        source_dependency_sha256=runtime.source_dependency_snapshot(root, *documents),
        clone_rules=rules,
    )
    value = value.model_copy(
        update={
            "original_delegation_id": runtime.delegation_identity(value.model_dump(mode="json"))
        }
    )
    return service.publish(root, f"synthetic_authority/{run_id}/delegation.json", value)


def fixture_technical_approval(root, request_ref):
    """Supply a separate synthetic delegated-assistant exact candidate decision."""
    from codex_blender_modeler.material_identity_split.authored_models import (
        AuthoredMaterialIdentitySplitTechnicalApplyIntentV02,
        AuthoredMaterialIdentitySplitTechnicalApprovalV02,
    )

    request = runtime.contract(root, request_ref, "request")
    plan = runtime.contract(root, request["plan"], "plan")
    text = (
        b"TEST ONLY: delegated assistant approves this exact specialized technical candidate.\r\n"
    )
    approval = AuthoredMaterialIdentitySplitTechnicalApprovalV02(
        job_id=root.name,
        run_id=request["run_id"],
        approval_id="synthetic-technical-approval",
        decision="approved",
        decision_observed_at=datetime.now(UTC),
        delegation=plan["delegation"],
        technical_decision_text_sha256=runtime.sha(text),
        approval_request=request_ref,
        **{
            key: request[key] for key in ("plan", "preapproval", "invariant_report", "shadow_blend")
        },
    )
    result = service.publish_authored_material_identity_split_technical_approval(
        root,
        approval_request_path=request_ref["path"],
        approval=approval,
        technical_decision=text,
        explicit_technical_decision_observed=True,
    )
    return AuthoredMaterialIdentitySplitTechnicalApplyIntentV02(
        job_id=root.name,
        run_id=request["run_id"],
        intent_id="synthetic-technical-apply",
        technical_approval=result["technical_approval"],
        approval_request=request_ref,
        plan=request["plan"],
        delegation=plan["delegation"],
        technical_decision=result["technical_decision"],
    )


@pytest.fixture(scope="module", params=[False, True], ids=["direct_user", "delegated_technical"])
def textured_template(tmp_path_factory, request):
    """Freeze a binding-only textured/volume graph fixture, distinct from native tests."""
    with pytest.MonkeyPatch.context() as patch:
        root, publication = prepared(
            tmp_path_factory.mktemp("textured_template"),
            patch,
            textures=True,
            delegated=request.param,
        )
        approval_request = synthetic_preapproval(root, publication["plan_artifact"])
        intent = (
            fixture_technical_approval(root, approval_request)
            if request.param
            else fixture_approval(root, approval_request)
        )
    return root, intent


@pytest.fixture
def textured_copy(tmp_path, monkeypatch, textured_template):
    """Isolate a graph mutation while preserving the tested source tree and input bytes."""
    from codex_blender_modeler import workspace

    original, intent = textured_template
    root = tmp_path / original.name
    shutil.copytree(original, root)
    monkeypatch.setattr(
        workspace, "job_dir", lambda job_id: root if job_id == root.name else tmp_path / job_id
    )
    return root, intent


def test_volume_graph_is_exact_host_subset_and_shared_media(textured_copy):
    """0.5.1 volume/scalars/images stay exact while per-host metadata is partitioned."""
    root, intent = textured_copy
    checked = runtime.validate_plan(root, intent.plan.model_dump())
    paths = set()
    for rule, derivative in zip(
        checked["plan"]["clone_rules"], checked["plan"]["material_derivatives"], strict=True
    ):
        source_recipe = json.loads(runtime.read(root, derivative["source_recipe"]))
        candidate_recipe = json.loads(runtime.read(root, derivative["candidate_recipe"]))
        assert source_recipe["schema_version"] == candidate_recipe["schema_version"] == "0.5.1"
        assert source_recipe["volume"] == candidate_recipe["volume"]
        assert candidate_recipe["volume"]["thickness_factor"] == 0.44
        assert source_recipe["surface"] == candidate_recipe["surface"]
        assert candidate_recipe["surface"]["transmission_weight"] == 0.35
        source = json.loads(runtime.read(root, derivative["source_manifest"]))
        candidate = json.loads(runtime.read(root, derivative["candidate_manifest"]))
        assert source["channels"] == candidate["channels"]
        assert candidate["surface_detail_ids"] == [
            name for name in source["surface_detail_ids"] if name in rule["surface_detail_ids"]
        ]
        assert {row["parent_object_id"] for row in candidate["surface_detail_bindings"]} == {
            rule["target_object_id"]
        }
        paths.update(ref["path"] for ref in derivative["media_copies"].values())
    assert len(paths) == 2


@pytest.mark.parametrize(
    "target",
    [
        "source_manifest",
        "source_recipe",
        "source_image",
        "clone_manifest",
        "clone_recipe",
        "clone_image",
    ],
)
@pytest.mark.parametrize("boundary", ["preapproval", "apply"])
def test_graph_mutations_fail_before_native_or_consumption(textured_copy, target, boundary):
    """Original and cloned images/manifests/recipes remain exact at both authority boundaries."""
    root, intent = textured_copy
    plan = runtime.contract(root, intent.plan.model_dump(), "plan")
    derivative = plan["material_derivatives"][0]
    paths = {
        "source_manifest": derivative["source_manifest"]["path"],
        "source_recipe": derivative["source_recipe"]["path"],
        "source_image": next(iter(derivative["media_copies"])),
        "clone_manifest": derivative["candidate_manifest"]["path"],
        "clone_recipe": derivative["candidate_recipe"]["path"],
        "clone_image": next(iter(derivative["media_copies"].values()))["path"],
    }
    path = root / paths[target]
    path.write_bytes(path.read_bytes() + b"\nsynthetic-tamper\n")
    with pytest.raises(ValueError):
        if boundary == "preapproval":
            service.run_authored_material_identity_split_preapproval(
                root, plan_path=intent.plan.path
            )
        else:
            transaction.apply_authored_material_identity_split(root, intent=intent)
    assert not (root / runtime.prefix(intent.run_id) / "apply_intent.json").exists()


def generic_revision(root, monkeypatch, suffix):
    """Apply genuine generic test-only guarded authority before or after a specialized split."""
    from codex_blender_modeler.orchestration import service as workflow_service
    from codex_blender_modeler.revision import preview_revision_plan

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(root.parent))
    selected = selected_attachment(root, root.name, root / "analysis/scene_spec.json")
    document = json.loads(runtime.read(root, selected))
    scene = json.loads((root / "analysis/scene_spec.json").read_bytes())
    target = next(obj for obj in scene["objects"] if obj["id"] == "pendant_0")
    old = runtime.reference(root, target["geometry"]["path"])
    payload = json.loads(runtime.read(root, old))
    maximum = max(vertex[2] for vertex in payload["vertices"])
    for vertex in payload["vertices"]:
        if vertex[2] == maximum:
            vertex[2] += 0.01
    payload["source_hashes"].append({"role": "source_mesh_payload", **old})
    payload["source_fingerprint_sha256"] = runtime.stable(payload["source_hashes"])
    geometry = mesh_fixture.put(root, f"geometry/generic_{suffix}.json", payload)
    model = json.loads((root / "analysis/modeling_plan.json").read_bytes())
    model["global_notes"].append("Synthetic generic chain " + suffix)
    model_ref = mesh_fixture.put(root, f"analysis/generic_model_{suffix}.json", model)
    mesh_fixture.put(
        root,
        "analysis/revision_plan.json",
        {
            "schema_version": "0.1.0",
            "job_id": root.name,
            "base_spec_sha256": sha256_file(root / "analysis/scene_spec.json"),
            "request": "Synthetic guarded chain only",
            "operations": [
                {
                    "op": "set",
                    "target_type": "object",
                    "target_id": "pendant_0",
                    "path": ["geometry", "path"],
                    "value": geometry["path"],
                    "reason": "Preserve the fixed root while changing a free edge",
                }
            ],
            "acceptance_criteria": ["Exact root preserved"],
            "assumptions": [],
        },
    )
    candidate, _ = preview_revision_plan(
        scene_spec_path=root / "analysis/scene_spec.json",
        plan_path=root / "analysis/revision_plan.json",
    )
    document["source_scene"]["sha256"] = runtime.sha(
        deterministic_json_bytes(candidate.model_dump(mode="json"))
    )
    document["source_modeling_plan"]["sha256"] = model_ref["sha256"]
    document["source_geometry"] = [
        geometry if ref["path"] == old["path"] else ref for ref in document["source_geometry"]
    ]
    attachment = mesh_fixture.put(root, f"analysis/generic_intent_{suffix}.json", document)
    options = {
        "paired_modeling_plan_path": model_ref["path"],
        "paired_modeling_plan_sha256": model_ref["sha256"],
        "attachment_intent_path": attachment["path"],
        "attachment_intent_sha256": attachment["sha256"],
    }
    state = guarded._approved(root, options)
    state = workflow_service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert (
        next(item.status for item in state.steps if item.step_id == "revision.apply") == "complete"
    ), state.model_dump_json()
    return attachment


def test_generic_then_specialized_then_generic_history(authorized_copy, monkeypatch):
    """Both authority domains share one bounded non-forking chain without replacing registration."""
    root, old_intent = authorized_copy
    registration = (root / "production/surface_attachment/registration.json").read_bytes()
    initial_metadata = json.loads((root / "job.json").read_bytes())
    generic_revision(root, monkeypatch, "before")
    old_plan = runtime.contract(root, old_intent.plan.model_dump(), "plan")
    rules = old_plan["clone_rules"]
    delegated = old_intent.profile == runtime.DELEGATED_PROFILE
    delegation = fixture_delegation(root, "mixed_split", rules) if delegated else None
    publication = service.prepare_authored_material_identity_split(
        root,
        run_id="mixed_split",
        clone_rules=rules,
        source_material_plan_mode="scene_spec_only",
        delegation_path=delegation["path"] if delegation else None,
    )
    request = synthetic_preapproval(root, publication["plan_artifact"])
    intent = (
        fixture_technical_approval(root, request) if delegated else fixture_approval(root, request)
    )
    transaction.apply_authored_material_identity_split(root, intent=intent)
    selected = generic_revision(root, monkeypatch, "after")
    assert selected_attachment(root, root.name, root / "analysis/scene_spec.json") == selected
    metadata = json.loads((root / "job.json").read_bytes())
    assert metadata["attachment_intent"] == initial_metadata["attachment_intent"]
    assert (root / "production/surface_attachment/registration.json").read_bytes() == registration
    provenance = collect_build_provenance(root, root.name, material_plan_mode="scene_spec_only")
    assert provenance["authored_material_identity_split_closure"]["run_id"] == intent.run_id


@pytest.mark.parametrize("stage", ["prepare", "preapproval", "apply"])
def test_shared_chain_cap_is_rechecked_at_every_entry(authorized_copy, monkeypatch, stage):
    """Lowering the shared reader bound cannot let an unreadable successor reach approval/apply."""
    from codex_blender_modeler import attachment_revision_runtime

    root, intent = authorized_copy
    generic_revision(root, monkeypatch, "cap")
    old_plan = runtime.contract(root, intent.plan.model_dump(), "plan")
    rules = old_plan["clone_rules"]
    delegation = (
        fixture_delegation(root, "cap_split", rules)
        if intent.profile == runtime.DELEGATED_PROFILE
        else None
    )
    kwargs = {
        "run_id": "cap_split",
        "clone_rules": rules,
        "source_material_plan_mode": "scene_spec_only",
        "delegation_path": delegation["path"] if delegation else None,
    }
    if stage == "prepare":
        monkeypatch.setattr(attachment_revision_runtime, "MAX_REVISIONS", 1)
        with pytest.raises(ValueError, match="capacity"):
            service.prepare_authored_material_identity_split(root, **kwargs)
        return
    publication = service.prepare_authored_material_identity_split(root, **kwargs)
    if stage == "apply":
        request = synthetic_preapproval(root, publication["plan_artifact"])
        prepared_intent = (
            fixture_technical_approval(root, request)
            if intent.profile == runtime.DELEGATED_PROFILE
            else fixture_approval(root, request)
        )
    monkeypatch.setattr(attachment_revision_runtime, "MAX_REVISIONS", 1)
    with pytest.raises(ValueError, match="capacity"):
        if stage == "preapproval":
            service.run_authored_material_identity_split_preapproval(
                root, plan_path=publication["plan_artifact"]["path"]
            )
        else:
            transaction.apply_authored_material_identity_split(root, intent=prepared_intent)


@pytest.mark.parametrize("rewrap", ["new_run", "new_wrapper", "new_scope"])
def test_original_delegation_cannot_reset_after_exact_rollback(
    authorized_copy, monkeypatch, rewrap
):
    """Original conversation and bounded scope survive changed wrappers and new candidate IDs."""
    root, intent = authorized_copy
    if intent.profile != runtime.DELEGATED_PROFILE:
        pytest.skip("applies only to the distinct delegated technical authority domain")

    def stop(name):
        """Consume the synthetic original delegation without committing canonical change."""
        if name == "after_journal":
            raise RuntimeError("synthetic stop")

    monkeypatch.setattr(transaction, "_checkpoint", stop)
    with pytest.raises(RuntimeError):
        transaction.apply_authored_material_identity_split(root, intent=intent)
    monkeypatch.setattr(transaction, "_checkpoint", lambda name: None)
    transaction.recover_authored_material_identity_split(
        root,
        run_id=intent.run_id,
        apply_intent_sha256=sha256_file(root / runtime.prefix(intent.run_id) / "apply_intent.json"),
    )
    grant = runtime.contract(root, intent.delegation.model_dump(), "delegation")
    original_identity = grant["original_delegation_id"]
    grant.update(
        run_id="another_run",
        delegation_id="another_wrapper",
        delegation_observed_at=datetime.now(UTC).isoformat(),
    )
    if rewrap == "new_scope":
        grant["clone_rules"][0]["new_material_id"] = "mat.another_candidate"
    grant["original_delegation_id"] = runtime.delegation_identity(grant)
    if rewrap != "new_scope":
        assert grant["original_delegation_id"] == original_identity
    ref = service.publish(root, "synthetic_authority/rewrapped.json", grant)
    with pytest.raises(ValueError, match="already consumed"):
        service.prepare_authored_material_identity_split(
            root,
            run_id=grant["run_id"],
            clone_rules=grant["clone_rules"],
            source_material_plan_mode="scene_spec_only",
            delegation_path=ref["path"],
        )
    assert not (root / runtime.prefix(grant["run_id"])).exists()


@pytest.mark.parametrize(
    "field",
    ["question", "reply", "source_sha256", "source_dependency_sha256", "clone_rules", "profile"],
)
def test_delegation_scope_and_original_text_are_exact(authorized_copy, field):
    """Delegation is distinct from future hashes and cannot broaden through metadata changes."""
    root, intent = authorized_copy
    if intent.profile != runtime.DELEGATED_PROFILE:
        pytest.skip("applies only to the distinct delegated technical authority domain")
    if field in {"question", "reply"}:
        grant = runtime.contract(root, intent.delegation.model_dump(), "delegation")
        path = root / grant[field]["path"]
        path.write_bytes(path.read_bytes() + b"changed")
    else:
        path = root / intent.delegation.path
        grant = json.loads(path.read_bytes())
        if field == "source_sha256":
            grant[field]["analysis/scene_spec.json"] = "0" * 64
        elif field == "source_dependency_sha256":
            grant[field].pop(next(iter(grant[field])))
        elif field == "clone_rules":
            grant[field][0]["new_material_id"] = "mat.expanded"
        else:
            grant[field] = runtime.PROFILE
        path.write_bytes(deterministic_json_bytes(grant))
    with pytest.raises(ValueError):
        transaction.apply_authored_material_identity_split(root, intent=intent)
    assert not (root / runtime.prefix(intent.run_id) / "apply_intent.json").exists()


def test_direct_user_and_technical_authorities_cannot_mix(authorized_copy):
    """A generic profile switch cannot relabel either actor as the other authority domain."""
    root, intent = authorized_copy
    raw = intent.model_dump(mode="json")
    raw["profile"] = (
        runtime.PROFILE
        if intent.profile == runtime.DELEGATED_PROFILE
        else runtime.DELEGATED_PROFILE
    )
    from codex_blender_modeler.material_identity_split.authored_models import (
        AuthoredMaterialIdentitySplitTechnicalApplyIntentV02,
    )

    model = (
        AuthoredMaterialIdentitySplitApplyIntentV02
        if raw["profile"] == runtime.PROFILE
        else AuthoredMaterialIdentitySplitTechnicalApplyIntentV02
    )
    with pytest.raises(ValueError):
        model.model_validate_json(json.dumps(raw))


def test_exact_rejected_specialized_authority_cannot_apply(authorized_copy):
    """A hash-updated rejected decision is rejected semantically in either authority domain."""
    root, intent = authorized_copy
    raw = intent.model_dump(mode="json")
    approval_key, _ = runtime.authority_fields(raw)
    path = root / raw[approval_key]["path"]
    rejected = json.loads(path.read_bytes())
    rejected["decision"] = "rejected"
    path.write_bytes(deterministic_json_bytes(rejected))
    from codex_blender_modeler.structural_geometry.attachment_companion import Artifact

    changed = intent.model_copy(
        update={approval_key: Artifact(**runtime.reference(root, raw[approval_key]["path"]))}
    )
    with pytest.raises(ValueError, match="rejected"):
        transaction.apply_authored_material_identity_split(root, intent=changed)
    assert not (root / runtime.prefix(intent.run_id) / "apply_intent.json").exists()


def test_missing_specialized_authority_never_consumes(authorized_copy):
    """A missing exact decision cannot be replaced by a passed preapproval or request."""
    root, intent = authorized_copy
    approval_key, _ = runtime.authority_fields(intent.model_dump(mode="json"))
    ref = intent.model_dump(mode="json")[approval_key]
    (root / ref["path"]).rename(root / "preserved_missing_authority.json")
    with pytest.raises(FileNotFoundError):
        transaction.apply_authored_material_identity_split(root, intent=intent)
    assert not (root / runtime.prefix(intent.run_id) / "apply_intent.json").exists()


def test_complete_dependency_and_json_bounds_remain_fixed(tmp_path):
    """New companion readers retain the existing 512-file and 8MiB evidence limits."""
    files = []
    for ordinal in range(513):
        path = tmp_path / f"dep_{ordinal:03d}.json"
        path.write_bytes(b"{}")
        files.append({"path": path.name, "sha256": runtime.sha(b"{}")})
    with pytest.raises(ValueError, match="dependency bound"):
        runtime.geometry_dependencies(tmp_path, [{"source_geometry": files}], [])
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (8 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="byte limit"):
        runtime.read(tmp_path, {"path": oversized.name, "sha256": "0" * 64})
