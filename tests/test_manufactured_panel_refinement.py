"""Exercise staged recipe boundaries without Blender or external asset dependencies."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts/manufactured_panel_refinement_contract.py"
SPEC = importlib.util.spec_from_file_location("manufactured_panel_contract", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_json(path, value):
    """Write a fresh deterministic fixture dependency and return its exact hash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return MODULE.sha(path)


@pytest.fixture
def staged(tmp_path):
    """Build a tiny synthetic recipe using role names unrelated to any delivered asset."""
    ids = ["body", "core", "mount", "trim"]
    scene = {"objects": [{"id": sid} for sid in ids], "materials": [{"id": "surface"}]}
    source_sha = write_json(tmp_path / "sources/baseline_scene_spec.json", scene)
    reference = tmp_path / "input/reference.png"
    reference.parent.mkdir()
    reference.write_bytes(b"synthetic reference identity, never rendered")
    inputs = {}
    for sid in ids:
        relative = f"sources/{sid}.json"
        digest = write_json(
            tmp_path / relative,
            {"vertices": [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]]},
        )
        inputs[sid] = {"path": relative, "sha256": digest}
    recipe = {
        "schema_version": "0.1.0",
        "kind": "manufactured_panel_refinement",
        "inputs": inputs,
        "source_scene_sha256": source_sha,
        "reference_sha256": MODULE.sha(reference),
        "edge_roll": {"width_m": 0.02, "segments": 2, "angle_degrees": 30, "clamp_overlap": True},
        "edge_roll_overrides": {"body": 0.01},
        "edge_segments_by_id": dict.fromkeys(ids, 2),
        "section_rebuilds": {
            "body": {
                "kind": "source_profile",
                "indices": [0, 1, 2, 3],
                "half_depth": 0.2,
                "bevel_width": 0.02,
                "segments": 2,
            }
        },
        "core": {
            "semantic_id": "core",
            "x_sections": [-1, -0.8, 0.8, 1],
            "radius_factors": [0.6, 1, 1, 0.6],
            "center_y": 0,
            "center_z": 0,
            "radius_y": 0.1,
            "radius_z": 0.2,
            "radial_segments": 12,
        },
        "sight_mount": {
            "semantic_id": "mount",
            "housing_restore": {"0": [0, 0, 0]},
            "rail_x": [-0.8, 0.8],
            "rail_half_depth": 0.2,
            "bottom_z": [0, 0.1],
            "height": 0.1,
        },
        "grip_backstrap": {
            "semantic_id": "trim",
            "profile_xz": [[0, 0], [1, 0], [0, 1]],
            "half_depth": 0.1,
        },
        "stock_inlay_reseat": {
            "semantic_id": "body",
            "start_index": 0,
            "end_index": 2,
            "xz_center": [0, 0],
            "xz_scale": 0.9,
            "z_offset": 0.01,
        },
        "material_surface_overrides": {
            "surface": {"base_color": [0.4, 0.5, 0.6, 1], "roughness": 0.4, "metallic": 0}
        },
        "weld_tolerance_m": 1e-7,
        "limits": ["Synthetic staging contract; no authority or geometry acceptance."],
    }
    write_json(tmp_path / "refinement_recipe.json", recipe)
    return tmp_path, recipe


def test_valid_role_named_recipe(staged):
    """A complete recipe is accepted without importing Blender or asset-specific IDs."""
    root, recipe = staged
    assert MODULE.validate_recipe(root) == recipe


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("callback",), "arbitrary code"),
        (("edge_roll", "width_m"), 100),
        (("edge_roll", "segments"), True),
        (("edge_roll", "clamp_overlap"), False),
        (("core", "radius_y"), float("nan")),
        (("core", "radial_segments"), 4096),
        (("core", "semantic_id"), "foreign"),
        (("inputs", "body", "path"), "../escape.json"),
        (("inputs", "body", "sha256"), "0" * 64),
        (("material_surface_overrides", "surface", "nodes"), []),
        (("sight_mount", "housing_restore"), {"999": [0, 0, 0]}),
        (("section_rebuilds", "body", "indices"), [0, 1, 999]),
        (("section_rebuilds", "body", "half_depth"), 100),
        (("edge_segments_by_id", "body"), 1000),
        (("stock_inlay_reseat", "end_index"), 999),
        (("limits",), ["x" * 4097]),
        (("inputs",), []),
    ],
)
def test_recipe_rejects_unbounded_and_malformed_data(staged, path, value):
    """Every mutation fails closed before any Blender process or canonical effect."""
    root, recipe = staged
    changed = copy.deepcopy(recipe)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    write_json(root / "refinement_recipe.json", changed)
    with pytest.raises(MODULE.RecipeError):
        MODULE.validate_recipe(root)


def test_duplicate_json_key_rejected(staged):
    """Hash binding cannot legitimize ambiguous duplicate recipe keys."""
    root, _ = staged
    path = root / "refinement_recipe.json"
    path.write_text(
        path.read_text().replace('"schema_version":', '"kind":"extra","schema_version":')
    )
    with pytest.raises(MODULE.RecipeError, match="Duplicate"):
        MODULE.validate_recipe(root)


def test_linked_reference_rejected(staged):
    """Even a same-root link is outside the ordinary-file input contract."""
    root, recipe = staged
    reference = root / "input/reference.png"
    destination = root / "reference-copy.png"
    reference.rename(destination)
    reference.symlink_to(destination)
    assert MODULE.sha(destination) == recipe["reference_sha256"]
    with pytest.raises(MODULE.RecipeError, match="Linked"):
        MODULE.validate_recipe(root)


def test_duplicate_semantic_identity_rejected(staged):
    """Rehashed duplicate IDs do not disappear through set-based coverage checks."""
    root, recipe = staged
    path = root / "sources/baseline_scene_spec.json"
    scene = json.loads(path.read_text())
    scene["objects"].append(scene["objects"][0])
    recipe["source_scene_sha256"] = write_json(path, scene)
    write_json(root / "refinement_recipe.json", recipe)
    with pytest.raises(MODULE.RecipeError, match="Ambiguous"):
        MODULE.validate_recipe(root)
