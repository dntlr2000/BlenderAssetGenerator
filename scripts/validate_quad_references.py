"""Bounded, opt-in validation driver; it creates no campaign or human acceptance authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from quad_reference_recipes import OBSERVATIONS, REFERENCE_HASHES, make_recipe

from codex_blender_modeler.analysis import analyze_job_reference
from codex_blender_modeler.analysis.models import ModelingPlan
from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.config import get_settings
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa.service import run_scene_spec_visual_qa_snapshot
from codex_blender_modeler.structural_geometry.models import StructuralGeometryCandidate
from codex_blender_modeler.structural_geometry.service import materialize_structural_candidate
from codex_blender_modeler.workspace import (
    canonical_scene_spec_write_lock,
    create_job,
    find_reference,
    replace_scene_spec_if_current,
)


def sha(path):
    """Hash one source or result without interpreting its contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path, value):
    """Publish new validation evidence without replacing an existing attempt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def execute(root, label, script, args, blend=None):
    """Record the real fixed-script command and output with its elapsed host execution."""
    import time

    started = time.monotonic()
    result = run_blender(script, args, blend_file=blend, factory_startup=blend is None,
                         disable_autoexec=True)
    write_once(root / f"{label}.json", {"command": result.args, "exit_code": result.returncode,
        "seconds": time.monotonic() - started, "stdout": result.stdout, "stderr": result.stderr})


def prepare(asset, number, root, reference, parameters):
    """Create one immutable candidate through the strict structural and first-authoring host."""
    if sha(reference) != REFERENCE_HASHES[asset]:
        raise ValueError("reference bytes differ from the approved input")
    if not root.exists():
        if number != 1:
            raise ValueError("a validation asset must begin with candidate 1")
        create_job(root.name, reference, "concept", [])
        write_once(root / "validation_scope.json", {
            "purpose": "quad authoring validation only", "asset": asset,
            "reference_sha256": REFERENCE_HASHES[asset], "candidate_limit": 3,
            "qa_sets_per_candidate": 1, "diagnostic_images_per_candidate": 4,
            "export_import_attempt_limit": 2, "human_acceptance": False,
        })
        analyze_job_reference(root.name, provider="basic", projection_hint="ortho")
        plan_path = root / "analysis/modeling_plan.json"
        original = json.loads(plan_path.read_bytes())
        write_once(root / "analysis/modeling_plan_scaffold.json", original)
        original.update(stage="authored", objects=[{
            "id": f"asset.{asset}", "label": asset, "recommended_geometry": "custom_mesh",
            "source_ids": ["reference"], "observed": True, "confidence": 0.7,
            "notes": OBSERVATIONS[asset] + ["Back surfaces and metric dimensions are inferred."],
        }], global_notes=["Basic material only; weave, grain and microfracture textures omitted.",
                          "Concept scale; no measured hidden shape claim."])
        plan = ModelingPlan.model_validate(original)
        plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    scope = json.loads((root / "validation_scope.json").read_bytes())
    if scope["asset"] != asset or scope["reference_sha256"] != sha(find_reference(root.name)):
        raise ValueError("foreign job or changed reference")
    candidate = root / "candidates" / f"v{number:03d}"
    predecessor = root / "candidates" / f"v{number-1:03d}"
    pending_only = candidate.is_dir() and {p.name for p in candidate.iterdir()} == {
        "observations.json"
    }
    if (candidate.exists() and not pending_only) or (number > 1 and not predecessor.is_dir()):
        raise ValueError("candidate already materialized or predecessor absent")
    geometry, exceptions = make_recipe(asset, parameters)
    observation = {
        "reference_sha256": sha(reference), "fixed_observations": OBSERVATIONS[asset],
        "assumptions": ["Metric scale and hidden surfaces are inferred from one image."],
        "parameters": parameters, "triangle_exceptions": exceptions,
        "recipe_implementation_sha256": sha(Path(__file__).with_name("quad_reference_recipes.py")),
    }
    if pending_only:
        if json.loads((candidate / "observations.json").read_bytes()) != observation:
            raise ValueError("unfinished preparation has different immutable inputs")
    else:
        candidate.mkdir(parents=True)
        write_once(candidate / "observations.json", observation)
    relative = candidate.relative_to(root).as_posix()
    recipe = StructuralGeometryCandidate.model_validate_json(json.dumps({
        "semantic_id": f"asset.{asset}", "geometry": geometry,
        "geometry_intent": {"topology_policy": "static_prop_closed",
                            "smoothing_policy": ({"mode": "flat"} if asset == "rock" else
                                {"mode": "smooth_by_angle", "angle_degrees": 60.})},
    }))
    materialize_structural_candidate(job_root=root, candidate=recipe,
        candidate_relative_path=f"{relative}/recipe.json",
        mesh_relative_path=f"{relative}/mesh.json",
        blend_relative_path=f"{relative}/materialized.blend",
        report_relative_path=f"{relative}/materialize.json", mesh_payload_version="0.2.0",
        material_id=f"mat.{asset}")
    limits = [[min(p[k] for p in geometry["vertices"]), max(p[k] for p in geometry["vertices"])]
              for k in range(3)]
    center = [(a + b) / 2 for a, b in limits]
    poses = {"cloth": ([1.2, -1.7, 1.6], 1.18), "rock": ([1.6, -2.3, 1.65], 1.45),
             "wood": ([-2.0, -3.0, 2.0], 1.90)}
    position, scale = poses[asset]
    color = {"cloth": [.48, .39, .28, 1.], "rock": [.23, .235, .23, 1.],
             "wood": [.30, .145, .055, 1.]}[asset]
    camera = {"projection": "ORTHO", "location": position, "target": center,
              "focal_length_mm": 50., "ortho_scale": scale, "resolution": [640, 640]}
    if number > 1:
        camera = json.loads((root / "candidates/v001/scene_spec.json").read_bytes())["camera"]
    spec = SceneSpec.model_validate_json(json.dumps({
        "schema_version": "0.2.0", "job_id": root.name, "mode": "concept",
        "nominal_scene_size": [b - a for a, b in limits],
        "sources": [{"id": "reference", "kind": "reference", "immutable": True,
                     "path": find_reference(root.name).relative_to(root).as_posix()}],
        "materials": [{"id": f"mat.{asset}", "name": f"Basic {asset}", "shader": "principled",
                       "base_color": color, "roughness": .82, "metallic": 0.}],
        "objects": [{"id": f"asset.{asset}", "name": f"Quad {asset}",
                     "geometry": {"kind": "custom_mesh", "path": f"{relative}/mesh.json"},
                     "material_id": f"mat.{asset}", "shade_smooth": asset != "rock"}],
        "camera": camera, "assumptions": ["Concept dimensions and hidden geometry are inferred."],
        "revision_notes": [f"Bounded quad validation candidate {number}; basic material only."],
    }))
    write_once(candidate / "scene_spec.json", spec.model_dump(mode="json"))
    write_once(candidate / "camera_hypothesis.json", {"camera": camera,
        "reference_sha256": sha(reference), "status": "authored_hypothesis_not_measurement"})
    if number == 1:
        owner = "quad-validation-initial-authoring"
        with canonical_scene_spec_write_lock(root.name, owner):
            receipt = replace_scene_spec_if_current(root.name, candidate / "scene_spec.json",
                expected_current_sha256=None,
                expected_candidate_sha256=sha(candidate / "scene_spec.json"),
                lock_owner_id=owner)
        write_once(candidate / "initial_authoring_receipt.json", receipt)


def native_validation(root, candidate, asset, stage, destination, glb=None):
    """Run only the fixed validation script with a frozen authoring blend and bounded outputs."""
    script = Path(__file__).with_name("validate_quad_references_native.py").resolve()
    blend = candidate / "author.blend"
    command = [get_settings().blender_bin, "--background", str(blend), "--disable-autoexec",
               "--python-exit-code", "1", "--python", str(script), "--", "--asset", asset,
               "--stage", stage, "--output", str(destination), "--blend", str(blend),
               "--blend-sha256", sha(blend)]
    if glb:
        command.extend(["--glb", str(glb)])
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=900)
    write_once(destination.parent / f"{destination.name}_command.json", {
        "command": command, "exit_code": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr,
    })
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)


def main():
    """Execute one explicitly selected finite validation stage without automatic retries."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--references", type=Path, default=Path("E:/Playground/References"))
    parser.add_argument("--asset", choices=tuple(REFERENCE_HASHES), required=True)
    parser.add_argument("--candidate", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--stage", choices=("prepare", "build", "diagnostics", "qa", "export"),
                        required=True)
    parser.add_argument("--parameters", type=Path)
    parser.add_argument("--scene-spec", choices=("scene_spec.json", "scene_spec_corrected.json"),
                        default="scene_spec.json")
    parser.add_argument("--export-attempt", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    workspace.relative_to(Path("E:/CodexValidation").resolve())
    os.environ["CBM_WORKSPACE_ROOT"] = str(workspace)
    root = workspace / f"quad_{args.asset}_20261101"
    candidate = root / "candidates" / f"v{args.candidate:03d}"
    scene_spec = candidate / args.scene_spec
    if args.stage == "prepare":
        prepare(args.asset, args.candidate, root, args.references / f"item_{args.asset}.png",
                json.loads(args.parameters.read_bytes()) if args.parameters else {})
    elif args.stage == "build":
        if (candidate / "author.blend").exists():
            raise FileExistsError("candidate build already exists")
        execute(candidate, "build_command", "build_scene.py", [
            "--job-root", str(root), "--spec", str(scene_spec),
            "--output", str(candidate / "author.blend")])
        execute(candidate, "inspect_command", "inspect_scene.py", [
            "--output", str(candidate / "inventory.json")], candidate / "author.blend")
    elif args.stage == "diagnostics":
        native_validation(root, candidate, args.asset, "diagnostics", candidate / "diagnostics")
    elif args.stage == "qa":
        result = run_scene_spec_visual_qa_snapshot(root.name,
            scene_spec_path=scene_spec, blend_path=candidate / "author.blend",
            run_dir=candidate / "qa", run_id=f"quad-v{args.candidate:03d}",
            record_fidelity_conditions=True)
        write_once(candidate / "qa_result.json", result)
    else:
        output = root / "exports" / f"validation_{args.export_attempt:02d}"
        output.mkdir(parents=True, exist_ok=False)
        write_once(output / "source.json", {"candidate": candidate.relative_to(root).as_posix(),
            "scene_spec_path": scene_spec.relative_to(root).as_posix(),
            "scene_spec_sha256": sha(scene_spec),
            "blend_sha256": sha(candidate / "author.blend"), "production_package": False})
        execute(output, "export_command", "export_scene.py", ["--format", "glb", "--output",
                str(output / f"{args.asset}.glb")], candidate / "author.blend")
        native_validation(root, candidate, args.asset, "roundtrip", output / "clean_import",
                          output / f"{args.asset}.glb")
    print(json.dumps({"asset": args.asset, "stage": args.stage, "candidate": args.candidate}))


if __name__ == "__main__":
    main()
