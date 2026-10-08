"""Raw scene exports preserve evaluated static geometry without changing authoring files."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.config import get_settings

SCRIPT_ROOT = (
    Path(__file__).resolve().parents[1] / "src" / "codex_blender_modeler" / "blender_scripts"
)


def _load_export_script(monkeypatch: pytest.MonkeyPatch, bpy: ModuleType) -> ModuleType:
    """Load only the raw exporter with a harmless Blender test double."""

    # Legacy dispatch fixtures have no opted-in materials but expose the real collection API.
    if not hasattr(bpy, "data"):
        bpy.data = SimpleNamespace(objects=[])
    for obj in bpy.data.objects:
        if obj.type == "MESH" and not hasattr(obj.data, "materials"):
            obj.data.materials = []
    monkeypatch.delitem(sys.modules, "optical_volume_runtime", raising=False)
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.syspath_prepend(str(SCRIPT_ROOT))
    spec = importlib.util.spec_from_file_location(
        "raw_scene_export_test", SCRIPT_ROOT / "export_scene.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("format_name", ["glb", "gltf"])
@pytest.mark.parametrize("has_shape_keys", [False, True])
def test_raw_gltf_export_modifier_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    format_name: str,
    has_shape_keys: bool,
) -> None:
    """Evaluate static modifiers while keeping shape-key exports on the legacy path."""

    operator = Mock()
    bpy = ModuleType("bpy")
    bpy.ops = SimpleNamespace(export_scene=SimpleNamespace(gltf=operator))
    bpy.data = SimpleNamespace(
        objects=[
            SimpleNamespace(type="CAMERA"),
            SimpleNamespace(
                type="MESH", data=SimpleNamespace(shape_keys=object() if has_shape_keys else None)
            ),
        ]
    )
    module = _load_export_script(monkeypatch, bpy)
    output = tmp_path / "exports" / f"preview.{format_name}"
    monkeypatch.setattr(
        module, "parse_args", lambda: SimpleNamespace(format=format_name, output=str(output))
    )

    module.main()

    operator.assert_called_once_with(
        filepath=str(output),
        export_format="GLB" if format_name == "glb" else "GLTF_SEPARATE",
        use_selection=False,
        export_apply=not has_shape_keys,
    )
    captured = capsys.readouterr().out
    assert "CBM_EXPORT_OK" in captured
    assert ("SHAPE_KEYS_PRESERVE_LEGACY" in captured) is has_shape_keys


@pytest.mark.parametrize("format_name", ["fbx", "obj"])
def test_raw_non_gltf_export_dispatch_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, format_name: str
) -> None:
    """Keep existing FBX and OBJ operator defaults independent of the glTF-only fix."""

    operator = Mock()
    bpy = ModuleType("bpy")
    bpy.ops = SimpleNamespace(export_scene=SimpleNamespace(fbx=operator))
    module = _load_export_script(monkeypatch, bpy)
    obj_export = Mock(return_value="bpy.ops.wm.obj_export")
    monkeypatch.setattr(module, "export_obj", obj_export)
    output = tmp_path / f"preview.{format_name}"
    monkeypatch.setattr(
        module, "parse_args", lambda: SimpleNamespace(format=format_name, output=str(output))
    )
    module.main()
    if format_name == "fbx":
        operator.assert_called_once_with(filepath=str(output), use_selection=False)
        obj_export.assert_not_called()
    else:
        obj_export.assert_called_once_with(str(output))
        operator.assert_not_called()


@pytest.mark.parametrize("surface", ["cli", "mcp_server"])
@pytest.mark.parametrize("has_warning", [False, True])
def test_raw_export_public_surfaces_preserve_warnings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, surface: str, has_warning: bool
) -> None:
    """Expose shape-key fallback warnings without changing ordinary MCP response fields."""

    from codex_blender_modeler import cli, mcp_server

    module = cli if surface == "cli" else mcp_server
    warning = "CBM_EXPORT_WARNING code=SHAPE_KEYS_PRESERVE_LEGACY modifiers omitted"
    stdout = f"{warning}\nCBM_EXPORT_OK\n" if has_warning else "CBM_EXPORT_OK\n"
    runner = Mock(return_value=SimpleNamespace(stdout=stdout))
    monkeypatch.setattr(module, "run_blender", runner)
    monkeypatch.setattr(
        module, "job_dir" if surface == "cli" else "ensure_job_dirs", lambda _job: tmp_path
    )
    if surface == "cli":
        printer = Mock()
        monkeypatch.setattr(module, "console", SimpleNamespace(print=printer))
        cli.export_scene("raw-test", "glb")
        lines = [call.args[0] for call in printer.call_args_list]
        assert (warning in lines) is has_warning
        assert lines[-1] == f"Exported: {tmp_path / 'exports/scene.glb'}"
    else:
        result = mcp_server.export_scene("raw-test", "glb")
        expected = {"ok": True, "path": str(tmp_path / "exports/scene.glb")}
        if has_warning:
            expected["warnings"] = [warning]
        assert result == expected
    runner.assert_called_once()


FIXTURE_SCRIPT = '''\
"""Build or independently inspect the raw-export static modifier fixture."""
import json
import sys
from pathlib import Path

import bpy


def mesh_records():
    """Capture world-space geometry, UV presence, and signed volume after evaluation."""
    graph = bpy.context.evaluated_depsgraph_get()
    records = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
            volume = sum(
                points[triangle.vertices[0]].dot(
                    points[triangle.vertices[1]].cross(points[triangle.vertices[2]])
                ) / 6.0
                for triangle in mesh.loop_triangles
            )
            records[obj.name] = {
                "triangles": len(mesh.loop_triangles),
                "positions": sorted({tuple(round(float(v), 5) for v in p) for p in points}),
                "signed_volume": volume,
                "uv_layers": len(mesh.uv_layers),
                "materials": sorted(material.name for material in mesh.materials if material),
                "shape_key_names": (
                    [key.name for key in obj.data.shape_keys.key_blocks]
                    if obj.data.shape_keys else []
                ),
                "shape_key_max_displacement": (
                    {
                        key.name: max(
                            (vertex.co - basis.co).length
                            for vertex, basis in zip(
                                key.data, obj.data.shape_keys.reference_key.data, strict=True
                            )
                        )
                        for key in obj.data.shape_keys.key_blocks
                    }
                    if obj.data.shape_keys else {}
                ),
                "shape_key_values": (
                    {key.name: key.value for key in obj.data.shape_keys.key_blocks}
                    if obj.data.shape_keys else {}
                ),
                "modifiers": [modifier.type for modifier in obj.modifiers],
            }
        finally:
            evaluated.to_mesh_clear()
    return records


def create_fixture(source):
    """Create plain, bevel, array, and already-applied static meshes with UVs and material."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    material = bpy.data.materials.new("PreviewMaterial")
    material.use_nodes = True
    names = (
        "plain", "beveled", "arrayed", "already_applied", "mirrored", "subdivided",
        "solidified", "decimated", "disabled_bevel", "bevel_array_stack",
    )
    for index, name in enumerate(names):
        location = (index * 4.0, 0.0, 0.0)
        if name == "solidified":
            bpy.ops.mesh.primitive_plane_add(size=1.0, location=location)
        elif name == "decimated":
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.5, location=location)
        else:
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
        obj = bpy.context.object
        obj.name = name
        obj.data.materials.append(material)
        if not obj.data.uv_layers:
            obj.data.uv_layers.new(name="UVMap")
        if name in {"beveled", "already_applied", "disabled_bevel", "bevel_array_stack"}:
            modifier = obj.modifiers.new("PreviewBevel", "BEVEL")
            modifier.width = 0.15
            modifier.segments = 3
            if name == "already_applied":
                bpy.ops.object.modifier_apply(modifier=modifier.name)
            elif name == "disabled_bevel":
                modifier.show_viewport = False
                modifier.show_render = False
        if name in {"arrayed", "bevel_array_stack"}:
            modifier = obj.modifiers.new("PreviewArray", "ARRAY")
            modifier.count = 2
            modifier.relative_offset_displace = (1.5, 0.0, 0.0)
        if name == "mirrored":
            for vertex in obj.data.vertices:
                vertex.co.x += 0.75
            modifier = obj.modifiers.new("PreviewMirror", "MIRROR")
        if name == "subdivided":
            modifier = obj.modifiers.new("PreviewSubdivision", "SUBSURF")
            modifier.levels = 1
            modifier.render_levels = 1
        if name == "solidified":
            modifier = obj.modifiers.new("PreviewSolidify", "SOLIDIFY")
            modifier.thickness = 0.2
        if name == "decimated":
            modifier = obj.modifiers.new("PreviewDecimate", "DECIMATE")
            modifier.ratio = 0.5
    bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=str(source))


def create_shape_fixture(source):
    """Exercise legacy morph export alongside active modifiers on two scene meshes."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for index, name in enumerate(("morph", "static_bevel")):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(index * 4.0, 0.0, 0.0))
        obj = bpy.context.object
        obj.name = name
        if name == "morph":
            obj.shape_key_add(name="Basis")
            raised = obj.shape_key_add(name="Raised")
            raised.data[0].co.z += 0.4
            raised.value = 0.35
            secondary = bpy.data.scenes.new("SecondaryMorphScene")
            secondary.collection.objects.link(obj)
            bpy.context.scene.collection.objects.unlink(obj)
        modifier = obj.modifiers.new("PreviewBevel", "BEVEL")
        modifier.width = 0.15
        modifier.segments = 3
    bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=str(source))


mode, artifact, output = sys.argv[sys.argv.index("--") + 1:]
artifact = Path(artifact)
if mode == "create":
    create_fixture(artifact)
elif mode == "create_shapes":
    create_shape_fixture(artifact)
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if artifact.suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(artifact))
    elif artifact.suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(artifact))
    else:
        bpy.ops.wm.obj_import(filepath=str(artifact))
    bpy.context.view_layer.update()
Path(output).write_text(json.dumps({"blender": bpy.app.version_string, "objects": mesh_records()}))
'''


def _run_fixture(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the test-owned Blender fixture with failure propagation and isolated stdin."""

    settings = get_settings()
    command = [
        settings.blender_bin,
        "--factory-startup",
        "--disable-autoexec",
        "--background",
        "--python-exit-code",
        "1",
        "--python",
        str(script),
        "--",
        *arguments,
    ]
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=settings.blender_timeout,
        check=False,
    )
    assert result.returncode == 0, f"Command: {command}\n{result.stdout}\n{result.stderr}"
    return result


def _assert_positions_equivalent(actual: list[list[float]], expected: list[list[float]]) -> None:
    """Match unique points bijectively within OBJ text and float32 serialization precision."""

    unmatched = expected.copy()
    assert len(actual) == len(unmatched)
    for position in actual:
        matches = [
            index
            for index, reference in enumerate(unmatched)
            if all(
                abs(left - right) <= 2e-5 for left, right in zip(position, reference, strict=True)
            )
        ]
        assert len(matches) == 1, f"Expected one point match for {position}, found {len(matches)}"
        unmatched.pop(matches[0])
    assert not unmatched


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_RAW_EXPORT_SMOKE") != "1",
    reason="set CBM_RUN_RAW_EXPORT_SMOKE=1 for Blender 5.0.1 raw export smoke tests",
)
@pytest.mark.parametrize("format_name", ["glb", "gltf", "fbx", "obj"])
def test_raw_export_clean_import_preserves_evaluated_geometry(
    tmp_path: Path, format_name: str
) -> None:
    """Independent clean imports retain active modifiers without modifying the source blend."""

    fixture = tmp_path / "raw_export_fixture.py"
    fixture.write_text(FIXTURE_SCRIPT, encoding="utf-8")
    source = tmp_path / "source.blend"
    before = tmp_path / "evaluated_source.json"
    after = tmp_path / "clean_import.json"
    exported = tmp_path / f"preview.{format_name}"
    create = _run_fixture(fixture, "create", str(source), str(before))
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    export = run_blender(
        "export_scene.py",
        ["--format", format_name, "--output", str(exported)],
        blend_file=source,
        factory_startup=True,
        disable_autoexec=True,
    )
    imported = _run_fixture(fixture, "inspect", str(exported), str(after))
    (tmp_path / "blender.log").write_text(
        "\n".join(result.stdout + result.stderr for result in (create, export, imported)),
        encoding="utf-8",
    )

    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    source_payload = json.loads(before.read_text(encoding="utf-8"))
    imported_payload = json.loads(after.read_text(encoding="utf-8"))
    assert source_payload["blender"] == imported_payload["blender"] == "5.0.1"
    expected = source_payload["objects"]
    actual = imported_payload["objects"]
    assert set(actual) == set(expected)
    assert expected["beveled"]["triangles"] > expected["plain"]["triangles"]
    assert expected["arrayed"]["triangles"] == 2 * expected["plain"]["triangles"]
    for name, reference in expected.items():
        observed = actual[name]
        assert observed["triangles"] == reference["triangles"], name
        _assert_positions_equivalent(observed["positions"], reference["positions"])
        assert observed["signed_volume"] == pytest.approx(reference["signed_volume"], rel=1e-5)
        assert observed["uv_layers"] == reference["uv_layers"] == 1
        assert observed["materials"] == reference["materials"] == ["PreviewMaterial"]


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_RAW_EXPORT_SMOKE") != "1",
    reason="set CBM_RUN_RAW_EXPORT_SMOKE=1 for Blender 5.0.1 raw export smoke tests",
)
@pytest.mark.parametrize("format_name", ["glb", "gltf"])
def test_raw_gltf_preserves_legacy_shape_keys_with_explicit_warning(
    tmp_path: Path, format_name: str
) -> None:
    """Preserve morph targets and disclose scene-wide legacy modifier omission."""

    fixture = tmp_path / "raw_shape_export_fixture.py"
    fixture.write_text(FIXTURE_SCRIPT, encoding="utf-8")
    source = tmp_path / "source.blend"
    before = tmp_path / "evaluated_source.json"
    after = tmp_path / "clean_import.json"
    exported = tmp_path / f"preview.{format_name}"
    create = _run_fixture(fixture, "create_shapes", str(source), str(before))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    export = run_blender(
        "export_scene.py",
        ["--format", format_name, "--output", str(exported)],
        blend_file=source,
        factory_startup=True,
        disable_autoexec=True,
    )
    imported = _run_fixture(fixture, "inspect", str(exported), str(after))
    (tmp_path / "blender.log").write_text(
        "\n".join(result.stdout + result.stderr for result in (create, export, imported)),
        encoding="utf-8",
    )
    assert "CBM_EXPORT_WARNING code=SHAPE_KEYS_PRESERVE_LEGACY" in export.stdout
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    payload = json.loads(after.read_text(encoding="utf-8"))
    objects = payload["objects"]
    assert objects["morph"]["shape_key_names"] == ["Basis", "Raised"]
    assert objects["morph"]["shape_key_max_displacement"]["Raised"] == pytest.approx(0.4)
    assert objects["morph"]["shape_key_values"]["Raised"] == pytest.approx(0.35)
    assert objects["morph"]["triangles"] == 12
    assert objects["static_bevel"]["triangles"] == 12


@pytest.mark.parametrize("format_name", ["obj", "fbx"])
def test_opted_in_volume_refuses_nonportable_format_before_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, format_name: str
) -> None:
    """The new explicit volume branch fails instead of silently dropping optical semantics."""
    operator = Mock()
    bpy = ModuleType("bpy")
    bpy.ops = SimpleNamespace(export_scene=SimpleNamespace(fbx=operator))
    module = _load_export_script(monkeypatch, bpy)
    monkeypatch.setattr(
        module, "validate_optical_volume_objects", lambda objects: [{"volume": True}]
    )
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(
            format=format_name, output=str(tmp_path / f"unsupported.{format_name}")
        ),
    )
    obj_export = Mock()
    monkeypatch.setattr(module, "export_obj", obj_export)
    with pytest.raises(ValueError, match="requires glTF/GLB"):
        module.main()
    operator.assert_not_called()
    obj_export.assert_not_called()
