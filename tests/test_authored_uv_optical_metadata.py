"""Pure structural adversaries for the narrow constant optical metadata exception."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from codex_blender_modeler.blender_scripts import portable_material_conversion_runtime


class NamedList(list):
    """Model Blender's ordered collection and exact name lookup without importing bpy."""

    def get(self, name):
        """Find an exact named item, preserving object identity."""
        return next((item for item in self if item.name == name), None)


@pytest.fixture
def graph(monkeypatch):
    """Load the actual runtime with isolated Blender and native-validator test doubles."""
    monkeypatch.setitem(sys.modules, "bpy", NS())
    monkeypatch.setitem(
        sys.modules, "portable_material_conversion_runtime", portable_material_conversion_runtime
    )
    calls = []

    def read(material):
        """Track mandatory native contract verification; native tests cover its real behavior."""
        calls.append(material)
        if material.invalid:
            raise ValueError("native optical graph rejected")
        return {"validated": True}

    native = NS(
        CONTRACT_KEY="cbm_optical_volume_contract",
        THICKNESS_NODE="CBM_OpticalVolume_Thickness",
        read_optical_volume=read,
    )
    monkeypatch.setitem(sys.modules, "optical_volume_runtime", native)
    path = Path(__file__).resolve().parents[1] / (
        "src/codex_blender_modeler/blender_scripts/portable_authored_uv_runtime.py"
    )
    spec = importlib.util.spec_from_file_location("authored_optical_test", path)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    socket = NS(
        name="Thickness",
        identifier="Socket_0",
        bl_idname="NodeSocketFloat",
        is_linked=False,
        links=[],
        default_value=0.2,
    )
    item = NS(
        item_type="SOCKET",
        name="Thickness",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
        identifier="Socket_0",
    )
    tree = NS(
        name="glTF Material Output CBM Optical Volume",
        bl_idname="ShaderNodeTree",
        animation_data=None,
        library=None,
        override_library=None,
        nodes=[],
        links=[],
        interface=NS(items_tree=[item]),
    )
    node = NS(
        name=native.THICKNESS_NODE,
        type="GROUP",
        bl_idname="ShaderNodeGroup",
        node_tree=tree,
        inputs=[socket],
        outputs=[],
    )
    values = {native.CONTRACT_KEY: "native contract"}
    material = NS(
        get=values.get,
        node_tree=NS(nodes=NamedList([node]), links=[], animation_data=None),
        animation_data=None,
        invalid=False,
    )
    obj = NS(data=NS(uv_layers=NamedList([NS(name="Layout", active_render=True)])))
    return NS(
        runtime=runtime,
        native=native,
        calls=calls,
        node=node,
        tree=tree,
        item=item,
        socket=socket,
        material=material,
        values=values,
        obj=obj,
    )


@pytest.mark.parametrize("suffix", ["", ".001", ".999", ".1000"])
def test_exact_empty_native_metadata_is_uv_independent(graph, suffix):
    """Blender datablock suffixes do not change exact material-owned node identity."""
    graph.tree.name += suffix
    assert graph.runtime.sampling_bindings(graph.obj, graph.material) == []
    assert graph.calls == [graph.material]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_contract",
        "unknown_contract",
        "renamed_node",
        "same_name_other_node",
        "unknown_group",
        "broad_prefix",
        "short_suffix",
        "suffix_tail",
        "wrong_node_class",
        "wrong_tree_class",
        "missing_tree",
        "nested_node",
        "internal_link",
        "group_animation",
        "linked_library",
        "library_override",
        "material_animation",
        "material_tree_animation",
        "extra_input",
        "extra_output",
        "no_input",
        "extra_interface",
        "interface_panel",
        "interface_output",
        "interface_name",
        "interface_type",
        "socket_name",
        "socket_type",
        "identifier",
        "linked_flag",
        "linked_socket",
        "incoming_link",
        "outgoing_link",
    ],
)
def test_unknown_or_nonconstant_groups_fail_closed(graph, mutation):
    """No name-only, nested, linked, animated or expanded-interface group earns exemption."""
    g = graph
    if mutation == "missing_contract":
        g.values.clear()
    elif mutation == "unknown_contract":
        g.material.invalid = True
    elif mutation == "renamed_node":
        g.node.name += ".001"
    elif mutation == "same_name_other_node":
        g.material.node_tree.nodes.insert(0, NS(name=g.node.name, type="BSDF_PRINCIPLED"))
    elif mutation in {"unknown_group", "broad_prefix", "short_suffix", "suffix_tail"}:
        g.tree.name = {
            "unknown_group": "Arbitrary",
            "broad_prefix": "glTF Material Output arbitrary",
            "short_suffix": g.tree.name + ".01",
            "suffix_tail": g.tree.name + ".001evil",
        }[mutation]
    elif mutation == "wrong_node_class":
        g.node.bl_idname = "GeometryNodeGroup"
    elif mutation == "wrong_tree_class":
        g.tree.bl_idname = "GeometryNodeTree"
    elif mutation == "missing_tree":
        g.node.node_tree = None
    elif mutation == "nested_node":
        g.tree.nodes.append(NS(type="TEX_IMAGE"))
    elif mutation == "internal_link":
        g.tree.links.append(NS())
    elif mutation == "group_animation":
        g.tree.animation_data = NS(drivers=[NS()])
    elif mutation == "linked_library":
        g.tree.library = NS()
    elif mutation == "library_override":
        g.tree.override_library = NS()
    elif mutation == "material_animation":
        g.material.animation_data = NS()
    elif mutation == "material_tree_animation":
        g.material.node_tree.animation_data = NS()
    elif mutation == "extra_input":
        g.node.inputs.append(g.socket)
    elif mutation == "extra_output":
        g.node.outputs.append(g.socket)
    elif mutation == "no_input":
        g.node.inputs.clear()
    elif mutation == "extra_interface":
        g.tree.interface.items_tree.append(g.item)
    elif mutation == "interface_panel":
        g.item.item_type = "PANEL"
    elif mutation == "interface_output":
        g.item.in_out = "OUTPUT"
    elif mutation == "interface_name":
        g.item.name = "Vector"
    elif mutation == "interface_type":
        g.item.socket_type = "NodeSocketVector"
    elif mutation == "socket_name":
        g.socket.name = "Vector"
    elif mutation == "socket_type":
        g.socket.bl_idname = "NodeSocketVector"
    elif mutation == "identifier":
        g.socket.identifier = "Socket_1"
    elif mutation == "linked_flag":
        g.socket.is_linked = True
    elif mutation == "linked_socket":
        g.socket.links.append(NS())
    elif mutation == "incoming_link":
        g.material.node_tree.links.append(NS(from_node=None, to_node=g.node))
    else:
        g.material.node_tree.links.append(NS(from_node=g.node, to_node=None))
    with pytest.raises(ValueError):
        g.runtime.sampling_bindings(g.obj, g.material)


@pytest.mark.parametrize("kind", ["GROUP", "SCRIPT", "ATTRIBUTE", "TANGENT"])
def test_unrelated_forbidden_nodes_still_fail(graph, kind):
    """A valid optical material does not permit any unrelated unsupported sampling node."""
    graph.material.node_tree.nodes.append(NS(name="unrecognized", type=kind))
    with pytest.raises(ValueError, match="unsupported sampling node"):
        graph.runtime.sampling_bindings(graph.obj, graph.material)


def test_no_volume_does_not_import_or_call_native_validator(graph, monkeypatch):
    """Legacy non-group materials retain exact sampling bytes and no optical dependency."""
    monkeypatch.setitem(sys.modules, "optical_volume_runtime", None)
    graph.values.clear()
    graph.material.node_tree.nodes = NamedList(
        [
            NS(name="UV", type="UVMAP", from_instancer=False, uv_map=""),
        ]
    )
    assert graph.runtime.sampling_bindings(graph.obj, graph.material) == [
        {"node_name": "UV", "node_type": "UVMAP", "selection": "uv_map", "uv_set": "Layout"}
    ]
    assert graph.calls == []


def test_real_optical_authored_uv_pin_bake_conversion(tmp_path):
    """Execute the full fixed Blender fixture or disclose unavailable native evidence."""
    import json
    import os
    import shutil
    import subprocess

    blender = os.environ.get("BLENDER_BIN") or shutil.which("blender")
    if not blender:
        pytest.skip("Blender unavailable: optical authored-UV native evidence not established")
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="2")
    for name in (
        "TEMP",
        "TMP",
        "TMPDIR",
        "BLENDER_USER_CONFIG",
        "BLENDER_USER_SCRIPTS",
        "BLENDER_USER_DATAFILES",
        "MESA_SHADER_CACHE_DIR",
    ):
        directory = tmp_path / name
        directory.mkdir()
        env[name] = str(directory)
    command = [
        blender,
        "--factory-startup",
        "--disable-autoexec",
        "--background",
        "--threads",
        "2",
        "--python-exit-code",
        "1",
        "--python",
        str(root / "tests/fixtures/authored_uv_optical_metadata_probe.py"),
        "--",
        "--repo",
        str(root),
        "--output",
        str(tmp_path / "result"),
    ]
    baseline = os.environ.get("AUTHORED_UV_BASELINE_RUNTIME")
    if baseline:
        command += ["--baseline-runtime", baseline]
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    (tmp_path / "blender.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads((tmp_path / "result/RESULT.json").read_text())
    assert evidence["status"] == "passed" and evidence["blender"] == "5.0.1"
    assert evidence["source_unchanged"] and evidence["source_layers_preserved"]
    assert len(evidence["negative_controls"]) >= 24
    assert evidence["temporary_proxies_removed"]
    assert evidence["scalar_proxy_row"]["sampled_uv_layers"] == ["Sampling"]
    assert len(evidence["baked_color_samples"]) >= 2
    assert evidence["serialized_optical_volume"][0]["serialized_factors_verified"]
    if baseline:
        assert evidence["legacy_inspection_bytes_equal"] is True
    # Reopen both saved artifacts through the production inspector, not only in-memory state.
    for stage, blend, expected, reference in (
        ("source", "source.blend", evidence["source_blend_sha256"], "authored_uv_source.json"),
        (
            "target",
            "converted/scene.blend",
            evidence["converted_blend_sha256"],
            "target_inspection.json",
        ),
    ):
        output = tmp_path / f"reopened_{stage}.json"
        inspect_command = [
            blender,
            "--factory-startup",
            "--disable-autoexec",
            "--background",
            "--threads",
            "2",
            "--python-exit-code",
            "1",
            str(tmp_path / "result" / blend),
            "--python",
            str(root / "src/codex_blender_modeler/blender_scripts/inspect_authored_uv.py"),
            "--",
            "--output",
            str(output),
            "--expected-blend-sha256",
            expected,
        ]
        if stage == "target":
            inspect_command += [
                "--source-snapshot",
                str(tmp_path / "result/authored_uv_source.json"),
            ]
        inspected = subprocess.run(
            inspect_command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        (tmp_path / f"inspect_{stage}.log").write_text(inspected.stdout + inspected.stderr)
        assert inspected.returncode == 0, inspected.stdout + inspected.stderr
        assert json.loads(output.read_text()) == json.loads(
            (tmp_path / "result" / reference).read_text()
        )
