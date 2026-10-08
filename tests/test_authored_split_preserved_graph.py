"""Regression evidence for exact native source-Blend appearance preservation and early bounds."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import test_authored_material_identity_split as fixtures

from codex_blender_modeler import authored_split_runtime as runtime
from codex_blender_modeler.config import get_settings
from codex_blender_modeler.material_identity_split import authored_service as service


@pytest.mark.parametrize(
    "path",
    ["analysis/scene_spec.json", "analysis/modeling_plan.json", "analysis/material_plan.json"],
)
def test_oversized_sources_rejected_before_parser_or_staging(tmp_path, monkeypatch, path):
    """An oversized source never reaches a model parser or creates a run directory."""
    root, rules = fixtures.authored_job(tmp_path, monkeypatch)
    original = (root / path).read_bytes()
    (root / path).write_bytes(original + b" " * (8 * 1024 * 1024))
    called = []
    monkeypatch.setattr(
        service.SceneSpec, "model_validate_json", lambda *a, **k: called.append(True)
    )
    with pytest.raises(ValueError, match="byte bound"):
        service.prepare_authored_material_identity_split(
            root, run_id="oversized", clone_rules=rules
        )
    assert not called
    assert not (root / runtime.prefix("oversized")).exists()


@pytest.mark.parametrize("count", [0, 129, 1000])
def test_rule_cardinality_rejected_before_source_or_staging(tmp_path, monkeypatch, count):
    """Front-door cardinality limits precede source allocation and native/proof work."""
    root, rules = fixtures.authored_job(tmp_path, monkeypatch)
    called = []
    monkeypatch.setattr(runtime, "reference", lambda *a, **k: called.append(True))
    with pytest.raises(ValueError, match="1–128"):
        service.prepare_authored_material_identity_split(
            root, run_id="too_many", clone_rules=[rules[0]] * count
        )
    assert not called
    assert not (root / runtime.prefix("too_many")).exists()


def test_prospective_whole_closure_fails_before_proof_or_publication(tmp_path, monkeypatch):
    """The exact union including candidate derivatives must fit before expensive work/staging."""
    root, rules = fixtures.authored_job(tmp_path, monkeypatch)
    refs = {}
    for index in range(512):
        path = f"bounded/{index}.txt"
        (root / path).parent.mkdir(exist_ok=True)
        (root / path).write_text("synthetic bounded closure")
        refs[path] = runtime.reference(root, path)["sha256"]
    monkeypatch.setattr(runtime, "source_dependency_snapshot", lambda *a: refs)
    monkeypatch.setattr(
        service, "_proofs", lambda *a: pytest.fail("proof began before whole closure bound")
    )
    with pytest.raises(ValueError, match="whole closure"):
        service.prepare_authored_material_identity_split(
            root, run_id="too_large", clone_rules=rules
        )
    assert not (root / runtime.prefix("too_large")).exists()


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_AUTHORED_SPLIT_NATIVE") != "1",
    reason="explicit native graph regression opt-in",
)
@pytest.mark.parametrize(
    "mutation",
    [
        "retained_transmission",
        "clone_ior",
        "drop_volume",
        "mapping",
        "normal",
        "image_colorspace",
        "image_alpha",
        "image_sampling",
        "material_flags",
        "world",
        "render",
        "group",
        "driver",
        "object_visibility",
        "light_size",
        "camera_dof",
        "object_driver",
        "shape_keys",
        "constraint",
        "collection_visibility",
        "view_layer_pass",
    ],
)
def test_native_material_mutations_fail_preapproval(tmp_path, monkeypatch, mutation):
    """Real changed graphs/settings are rejected before any exact technical decision or apply."""
    monkeypatch.delenv("PYTHONPATH", raising=False)
    root, publication = fixtures.prepared(
        tmp_path, monkeypatch, native=True, textures=True, delegated=True
    )
    before = {path: (root / path).read_bytes() for path in runtime.SOURCE_PATHS}
    original_native = service._native

    def altered_native(job_root, plan_ref, stage, *, finalize=False):
        """Inject a test-only native mutation after exact cloning, retaining pristine evidence."""
        original_native(job_root, plan_ref, stage, finalize=finalize)
        if not finalize:
            return
        candidate = root / runtime.prefix("split01") / "shadow/final.blend"
        shutil.copyfile(candidate, candidate.with_name("final.before_mutation.blend"))
        script = tmp_path / "synthetic_mutation.py"
        script.write_text("""import bpy,sys
kind=sys.argv[sys.argv.index('--')+1]
identity='mat.shared' if kind=='retained_transmission' else 'mat.clone_0'
m=next(m for m in bpy.data.materials if m.get('cbm_id')==identity)
nodes=m.node_tree.nodes
shader=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
image=next(n for n in nodes if n.type=='TEX_IMAGE')
if kind=='retained_transmission': shader.inputs['Transmission Weight'].default_value=0
elif kind=='clone_ior': shader.inputs['IOR'].default_value=2.2
elif kind=='drop_volume': nodes.remove(next(n for n in nodes if n.type=='VOLUME_ABSORPTION'))
elif kind=='mapping':
    next(n for n in nodes if n.type=='MAPPING').inputs['Scale'].default_value=(2,2,2)
elif kind=='normal': nodes.remove(next(n for n in nodes if n.type=='NORMAL_MAP'))
elif kind=='image_colorspace': image.image.colorspace_settings.name='sRGB'
elif kind=='image_alpha': image.image.alpha_mode='PREMUL'
elif kind=='image_sampling': image.interpolation='Closest'
elif kind=='material_flags': m.use_backface_culling=not m.use_backface_culling
elif kind=='world':
    bpy.context.scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=9
elif kind=='render': bpy.context.scene.view_settings.exposure=2
elif kind=='group':
    nodes.new('ShaderNodeGroup').node_tree=bpy.data.node_groups.new('Unsupported','ShaderNodeTree')
elif kind=='driver': shader.inputs['IOR'].driver_add('default_value')
elif kind=='object_visibility':
    next(o for o in bpy.context.scene.objects if o.type=='MESH').hide_render=True
elif kind=='light_size':
    next(o for o in bpy.context.scene.objects if o.type=='LIGHT').data.size=8
elif kind=='camera_dof': bpy.context.scene.camera.data.dof.use_dof=True
elif kind=='object_driver':
    next(o for o in bpy.context.scene.objects if o.type=='MESH').driver_add('location',0)
elif kind=='shape_keys':
    next(o for o in bpy.context.scene.objects if o.type=='MESH').shape_key_add(name='Basis')
elif kind=='constraint':
    next(o for o in bpy.context.scene.objects if o.type=='MESH').constraints.new('COPY_LOCATION')
elif kind=='collection_visibility': bpy.context.scene.collection.children[0].hide_render=True
elif kind=='view_layer_pass': bpy.context.scene.view_layers[0].use_pass_z=True
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
""")
        result = subprocess.run(
            [
                get_settings().blender_bin,
                "--factory-startup",
                "--disable-autoexec",
                "--background",
                str(candidate),
                "--python-exit-code",
                "1",
                "--python",
                str(script),
                "--",
                mutation,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
        (tmp_path / "mutation.log").write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr

    monkeypatch.setattr(service, "_native", altered_native)
    with pytest.raises((ValueError, RuntimeError), match="shader|native|Blender"):
        service.run_authored_material_identity_split_preapproval(
            root, plan_path=publication["plan_artifact"]["path"]
        )
    assert before == {path: (root / path).read_bytes() for path in runtime.SOURCE_PATHS}
    base = root / runtime.prefix("split01")
    assert (base / "failure.json").exists()
    assert not (base / "approval_request.json").exists()
    assert not (base / "technical_approval.json").exists()
    assert not (base / "apply_intent.json").exists()


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_AUTHORED_SPLIT_NATIVE") != "1",
    reason="explicit native material continuation opt-in",
)
def test_spatial_thirteen_family_ordinary_material_continuation(tmp_path, monkeypatch):
    """Feed a preserved-graph split through ordinary material staging, promotion and build."""
    from codex_blender_modeler.blender_artifacts import sha256_file
    from codex_blender_modeler.blender_runner import run_blender
    from codex_blender_modeler.material_identity_split import authored_transaction as transaction
    from codex_blender_modeler.orchestration import service as workflow

    monkeypatch.delenv("PYTHONPATH", raising=False)
    root, publication = fixtures.prepared(
        tmp_path,
        monkeypatch,
        native=True,
        textures=True,
        delegated=True,
        spatial=True,
        extra_materials=9,
    )
    original_plan = (root / "analysis/material_plan.json").read_bytes()
    result = service.run_authored_material_identity_split_preapproval(
        root, plan_path=publication["plan_artifact"]["path"]
    )
    intent = fixtures.fixture_technical_approval(root, result["approval_request"])
    transaction.apply_authored_material_identity_split(root, intent=intent)
    assert (root / "analysis/material_plan.json").read_bytes() == original_plan
    checked = runtime.validate_transaction(root, "split01")
    assert len(checked["candidates"]["candidate_scene_spec"]["materials"]) == 13
    # These fresh standard reports come from the actual committed Blend, never the base cycle.
    for script, arguments in (
        ("inspect_scene.py", ["--output", str(root / "reports/scene_inventory.json")]),
        (
            "validate_scene.py",
            [
                "--spec",
                str(root / "analysis/scene_spec.json"),
                "--output",
                str(root / "reports/validation.json"),
            ],
        ),
    ):
        run_blender(
            script,
            arguments,
            blend_file=root / "blender/scene.blend",
            factory_startup=True,
            disable_autoexec=True,
        )
    assert json.loads((root / "reports/validation.json").read_bytes())["ok"] is True
    state = workflow.plan_workflow(
        "Synthetic separate material recipe continuation.",
        job_id=root.name,
        intent="material_authoring",
    )
    state = workflow.resume_workflow(root.name, state.workflow_id, max_host_steps=3)
    assert state.current_step_id == "material.author", state.model_dump(mode="json")
    for key in ("geometry.prerequisite", "material.uv_inventory", "material.scaffold"):
        assert next(step for step in state.steps if step.step_id == key).status == "complete"
    candidate_path = root / f"workflows/{state.workflow_id}/artifacts/m/authored/material_plan.json"
    candidate = json.loads(candidate_path.read_bytes())
    source_plan = json.loads(original_plan)
    source_item = source_plan["materials"][0]
    derivatives = {
        rule["new_material_id"]: value
        for rule, value in zip(
            checked["plan"]["clone_rules"], checked["plan"]["material_derivatives"], strict=True
        )
    }
    for item in candidate["materials"]:
        identity = item["material_id"]
        derivative = derivatives.get(identity)
        if identity != "mat.shared" and derivative is None:
            continue
        ref = (
            derivative["candidate_recipe"]
            if derivative
            else runtime.reference(root, source_item["shader_recipe"])
        )
        recipe = json.loads(runtime.read(root, ref))
        # This separately authored candidate retains appearance while completing all13 families.
        (root / item["shader_recipe"]).write_bytes(runtime.encode(recipe))
        item["texture_manifest"] = recipe["texture_manifest"]
        item["texture_strategy"] = "image"
        item["mapping"] = source_item["mapping"]
    candidate["stage"] = "authored"
    candidate_path.write_bytes(runtime.encode(candidate))
    author = next(step for step in state.steps if step.step_id == "material.author")
    state = workflow.complete_workflow_step(
        root.name,
        state.workflow_id,
        "material.author",
        input_fingerprint=author.input_fingerprint,
        note="Synthetic exact13 family recipe candidate.",
    )
    assert state.current_step_id == "material.promote", state.model_dump(mode="json")
    state = workflow.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert (
        next(step for step in state.steps if step.step_id == "material.promote").status
        == "complete"
    ), state.model_dump(mode="json")
    assert sha256_file(candidate_path) == sha256_file(root / "analysis/material_plan.json")
    run_blender(
        "build_scene.py",
        [
            "--spec",
            str(root / "analysis/scene_spec.json"),
            "--output",
            str(root / "blender/scene.blend"),
            "--material-plan-mode",
            "current",
        ],
        factory_startup=True,
        disable_autoexec=True,
    )
    # Later material construction is independently fingerprinted and cannot reuse clone authority.
    with pytest.raises(ValueError, match="rebuilt Blend"):
        runtime.collect_preserved_authored_split_provenance(root)
    from codex_blender_modeler.attachment_runtime import selected_attachment

    assert (
        selected_attachment(root, root.name, root / "analysis/scene_spec.json")
        == checked["plan"]["candidate_attachment_intent"]
    )


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_AUTHORED_SPLIT_NATIVE") != "1",
    reason="explicit native final-CAS opt-in",
)
@pytest.mark.parametrize("identity", ["mat.shared", "mat.clone_0"])
def test_native_material_mutation_after_decision_blocks_apply(tmp_path, monkeypatch, identity):
    """Changing any approved native shader byte is rejected before authority consumption/CAS."""
    from codex_blender_modeler.material_identity_split import authored_transaction as transaction

    monkeypatch.delenv("PYTHONPATH", raising=False)
    root, publication = fixtures.prepared(
        tmp_path, monkeypatch, native=True, textures=True, delegated=True
    )
    before = {path: (root / path).read_bytes() for path in runtime.SOURCE_PATHS}
    result = service.run_authored_material_identity_split_preapproval(
        root, plan_path=publication["plan_artifact"]["path"]
    )
    intent = fixtures.fixture_technical_approval(root, result["approval_request"])
    blend = root / runtime.prefix("split01") / "shadow/final.blend"
    shutil.copyfile(blend, blend.with_name("final.before_after_decision_mutation.blend"))
    script = tmp_path / "synthetic_post_decision_mutation.py"
    script.write_text("""import bpy,sys
identity=sys.argv[sys.argv.index('--')+1]
m=next(m for m in bpy.data.materials if m.get('cbm_id')==identity)
n=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
n.inputs['Transmission Weight'].default_value=0
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath,relative_remap=False)
""")
    changed = subprocess.run(
        [
            get_settings().blender_bin,
            "--factory-startup",
            "--disable-autoexec",
            "--background",
            str(blend),
            "--python-exit-code",
            "1",
            "--python",
            str(script),
            "--",
            identity,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    (tmp_path / "post_decision_mutation.log").write_text(changed.stdout + changed.stderr)
    assert changed.returncode == 0, changed.stdout + changed.stderr
    with pytest.raises(ValueError):
        transaction.apply_authored_material_identity_split(root, intent=intent)
    assert before == {path: (root / path).read_bytes() for path in runtime.SOURCE_PATHS}
    assert not (root / runtime.prefix("split01") / "consumption.json").exists()
    assert not (root / runtime.prefix("split01") / "journal.json").exists()


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_AUTHORED_SPLIT_NATIVE") != "1",
    reason="explicit optical export/import opt-in",
)
def test_preserved_split_actual_glb_export_and_clean_import_optics(tmp_path, monkeypatch):
    """Export exact source/split graphs and prove retained plus three-clone optical assignments."""
    from codex_blender_modeler.material_identity_split import authored_transaction as transaction

    monkeypatch.delenv("PYTHONPATH", raising=False)
    root, publication = fixtures.prepared(
        tmp_path, monkeypatch, native=True, textures=True, delegated=True, spatial=True
    )
    result = service.run_authored_material_identity_split_preapproval(
        root, plan_path=publication["plan_artifact"]["path"]
    )
    intent = fixtures.fixture_technical_approval(root, result["approval_request"])
    transaction.apply_authored_material_identity_split(root, intent=intent)
    before = {path: (root / path).read_bytes() for path in runtime.SOURCE_PATHS}
    repo = Path(__file__).resolve().parents[1]
    output = tmp_path / "optical_parity"
    process = subprocess.run(
        [
            get_settings().blender_bin,
            "--factory-startup",
            "--disable-autoexec",
            "--background",
            "--threads",
            "2",
            "--python-exit-code",
            "1",
            "--python",
            str(repo / "tests/fixtures/authored_split_optical_probe.py"),
            "--",
            "--repo",
            str(repo),
            "--job-root",
            str(root),
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    (tmp_path / "optical_parity.log").write_text(process.stdout + process.stderr)
    assert process.returncode == 0, process.stdout + process.stderr
    report = json.loads((output / "RESULT.json").read_bytes())
    assert report["status"] == "passed" and not report["package_accepted"]
    assert len(report["stages"]["preserved_split"]["serialized_extensions"]) == 4
    assert before == {path: (root / path).read_bytes() for path in runtime.SOURCE_PATHS}
