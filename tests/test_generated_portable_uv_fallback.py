"""Python-only regression checks for strict generated UV and source sampling preservation."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "src/codex_blender_modeler/blender_scripts"
SCRIPT = SCRIPT_ROOT / "convert_portable_materials.py"


def method(name: str, **extra):
    """Load one dependency-free Blender function without importing bpy in Python CI."""
    source = ast.parse(SCRIPT.read_text())
    body = next(
        item for item in source.body if isinstance(item, ast.FunctionDef) and item.name == name
    )
    namespace = dict(extra)
    compiled = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            body,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(compiled), str(SCRIPT), "exec"), namespace)
    return namespace[name]


class Nodes(list):
    """Minimal node graph that records UV-map nodes created by the pinning helper."""

    def new(self, kind):
        """Add one fake ShaderNodeUVMap with a readable output socket."""
        assert kind == "ShaderNodeUVMap"
        node = SimpleNamespace(type="UVMAP", uv_map="", outputs={"UV": object()})
        self.append(node)
        return node


class Links:
    """Record graph rewiring while retaining original source graph test independence."""

    def __init__(self):
        """Initialize empty link operation logs."""
        self.created = []
        self.removed = []

    def new(self, source, target):
        """Record one source-to-target connection."""
        self.created.append((source, target))

    def remove(self, link):
        """Record removal of an actual pre-existing link."""
        assert link is not None
        self.removed.append(link)


def test_implicit_normal_basis_pins_without_overwriting_explicit_basis():
    """Target-active UV cannot redirect implicit source normals or existing explicit UVs."""
    implicit = SimpleNamespace(type="NORMAL_MAP", space="TANGENT", uv_map="")
    explicit = SimpleNamespace(type="NORMAL_MAP", space="TANGENT", uv_map="ExplicitSource")
    object_normal = SimpleNamespace(type="NORMAL_MAP", space="OBJECT", uv_map="")
    implicit_uv = SimpleNamespace(type="UVMAP", uv_map="")
    image_socket = SimpleNamespace(is_linked=False)
    image = SimpleNamespace(type="TEX_IMAGE", inputs={"Vector": image_socket})
    nodes = Nodes([implicit, explicit, object_normal, implicit_uv, image])
    links = Links()
    mat = SimpleNamespace(node_tree=SimpleNamespace(nodes=nodes, links=links))
    count = method("_pin_original_uv_links")(mat, "ActualRender")
    assert implicit.uv_map == implicit_uv.uv_map == "ActualRender"
    assert explicit.uv_map == "ExplicitSource"
    assert object_normal.uv_map == ""
    assert nodes[-1].uv_map == "ActualRender"
    assert count == 1 and len(links.created) == 1 and not links.removed
    assert links.created[0][1] is image_socket


def test_generated_layout_helper_retains_exact_predicate():
    """The same exact positive-area predicate remains the generated atlas authority."""
    spec = importlib.util.spec_from_file_location(
        "uv_exact_test", SCRIPT_ROOT / "portable_authored_uv_proof.py"
    )
    proof = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proof)
    values = [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.1, 0.1, 0.2, 0.1, 0.1, 0.2]

    def fill(_key, destination):
        """Supply exact fake Blender Float2 stored values to the production proof helper."""
        destination[:] = values

    layer = SimpleNamespace(uv=SimpleNamespace(foreach_get=fill))
    mesh = SimpleNamespace(
        uv_layers={"CBMPortableAtlas": layer},
        loops=[None] * 6,
        calc_loop_triangles=lambda: None,
        loop_triangles=[SimpleNamespace(loops=[0, 1, 2]), SimpleNamespace(loops=[3, 4, 5])],
    )
    check = method(
        "_prove_generated_atlas_uv",
        ATLAS_UV_SET="CBMPortableAtlas",
        validate_uv_layout=proof.validate_uv_layout,
        _require_generated_uv_resource_bounds=method(
            "_require_generated_uv_resource_bounds",
            MAXIMUM_TRIANGLES=proof.MAXIMUM_TRIANGLES,
            UVProofError=proof.UVProofError,
        ),
    )
    with pytest.raises(proof.UVProofError, match="Positive-area UV overlap"):
        check(mesh)
    values[6:] = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    result = check(mesh)
    assert result["complete"] and result["overlap_pair_count"] == 0


def test_fallback_covers_overlap_and_proves_actual_final_storage():
    """Overlap enters the existing fallback and resource/invalid-data failures still fail closed."""
    text = SCRIPT.read_text()
    create = text[text.index("def _create_atlas_uv(") : text.index("\ndef _mesh_world_bounds(")]
    assert "if initial_degenerate_faces or initial_exact_error is not None:" in create
    assert "Positive-area UV overlap" in create and "Exact zero-area UV triangle" in create
    assert create.index("if not str(error).startswith") < create.index("_lightmap_fallback(obj)")
    assert create.index('uv_values.foreach_set("vector", coordinates)') < create.index(
        "final_exact_proof = _prove_generated_atlas_uv(mesh)"
    )
    assert '"initial_exact_uv_failure": initial_exact_error' in create
    assert '"exact_generated_uv_proof": final_exact_proof' in create
    assert (
        'atlas_record["post_topology_exact_uv_proof"] = _prove_generated_atlas_uv(obj.data)' in text
    )


def test_source_render_layer_is_resolved_before_clone_activation():
    """Material metadata cannot redirect a legacy material's actual implicit render UV basis."""
    text = SCRIPT.read_text()
    clone = text[
        text.index("def _clone_source_material(") : text.index(
            "\ndef _clone_authored_source_material("
        )
    ]
    assert "if layer.active_render" in clone
    assert "_pin_original_uv_links(clone, source_render_uv_set)" in clone
    assert '"source_render_uv_set": source_render_uv_set' in clone


class Group:
    """Represent an identity-stable shared group for read-only traversal tests."""

    def __init__(self, nodes, name="SharedGroup"):
        """Keep direct node references so any mutation is visible to all users."""
        self.nodes = nodes
        self.name = name

    def as_pointer(self):
        """Supply the stable datablock identity used by the Blender traversal."""
        return id(self)


def grouped_material(nodes):
    """Wrap a nested group inside two users of the same shared tree."""
    inner = Group(nodes)
    nested = SimpleNamespace(type="GROUP", name="Nested", node_tree=inner)
    outer = Group([nested], "OuterGroup")
    users = [SimpleNamespace(type="GROUP", name=str(i), node_tree=outer) for i in range(2)]
    return SimpleNamespace(node_tree=Group(users, "Material")), inner


@pytest.mark.parametrize("kind", ["TEX_IMAGE", "NORMAL_MAP", "UVMAP", "TEX_COORD"])
def test_nested_implicit_uv_consumers_fail_before_shared_graph_mutation(kind):
    """Nested image, normal, UV-map and coordinate consumers cannot follow destination-active UV."""
    node = SimpleNamespace(
        type=kind,
        name="Implicit",
        space="TANGENT",
        uv_map="",
        inputs={"Vector": SimpleNamespace(is_linked=False)},
        outputs={"UV": SimpleNamespace(is_linked=True)},
    )
    material, inner = grouped_material([node])
    before = repr(vars(node))
    with pytest.raises(ValueError, match="unsupported grouped UV sampling"):
        method("_require_supported_group_uv_sampling")(material)
    assert inner.nodes == [node] and repr(vars(node)) == before


def test_explicit_nested_uv_and_optical_metadata_groups_are_unchanged():
    """Explicit nested UV sources and the metadata-only optical group remain eligible."""
    nodes = [
        SimpleNamespace(
            type="TEX_IMAGE", name="Image", inputs={"Vector": SimpleNamespace(is_linked=True)}
        ),
        SimpleNamespace(type="NORMAL_MAP", name="Normal", space="TANGENT", uv_map="Source"),
        SimpleNamespace(type="UVMAP", name="UV", uv_map="Source"),
        SimpleNamespace(
            type="TEX_COORD", name="UnusedUV", outputs={"UV": SimpleNamespace(is_linked=False)}
        ),
        SimpleNamespace(type="GROUP_INPUT", name="ThicknessInput"),
        SimpleNamespace(type="GROUP_OUTPUT", name="MetadataOutput"),
    ]
    material, inner = grouped_material(nodes)
    before = [repr(vars(node)) for node in nodes]
    method("_require_supported_group_uv_sampling")(material)
    assert inner.nodes == nodes and [repr(vars(node)) for node in nodes] == before


def test_group_cycle_and_resource_limits_fail_closed():
    """Finite graph inspection never accepts a cycle or exceeds the 512-node budget."""
    cycle = Group([])
    cycle.nodes.append(SimpleNamespace(type="GROUP", name="Cycle", node_tree=cycle))
    material = SimpleNamespace(
        node_tree=Group([SimpleNamespace(type="GROUP", name="Root", node_tree=cycle)])
    )
    check = method("_require_supported_group_uv_sampling")
    with pytest.raises(ValueError, match="cyclic group graph"):
        check(material)
    large, _ = grouped_material([SimpleNamespace(type="VALUE", name=str(i)) for i in range(513)])
    with pytest.raises(ValueError, match="node resource limit"):
        check(large)


def test_group_scope_guard_runs_before_material_copy():
    """Unsupported sampling is rejected before any private clone or UV mutation exists."""
    source = SCRIPT.read_text()
    clone = source[source.index("def _clone_source_material(") :]
    assert clone.index("_require_supported_group_uv_sampling(source_material)") < clone.index(
        "clone = source_material.copy()"
    )


class CountOnly:
    """Provide native-style length without permitting element iteration or allocation."""

    def __init__(self, count):
        """Store one declared native sequence length."""
        self.count = count

    def __len__(self):
        """Expose the sequence count without materializing items."""
        return self.count


def test_uv_resource_guard_rejects_before_array_creation():
    """Shared exact-proof limits are enforced before any UV access or Python array allocation."""
    limit = 250000
    calls = []
    mesh = SimpleNamespace(
        loops=CountOnly(limit * 3 + 1),
        calc_loop_triangles=lambda: calls.append("triangulate"),
        loop_triangles=CountOnly(0),
    )
    guard = method(
        "_require_generated_uv_resource_bounds", MAXIMUM_TRIANGLES=limit, UVProofError=ValueError
    )
    with pytest.raises(ValueError, match="loop resource limit"):
        guard(mesh)
    assert not calls
    mesh.loops = CountOnly(limit * 3)
    mesh.loop_triangles = CountOnly(limit + 1)
    with pytest.raises(ValueError, match="triangle resource limit"):
        guard(mesh)
    assert calls == ["triangulate"]
    source = SCRIPT.read_text()
    proof = source[
        source.index("def _prove_generated_atlas_uv(") : source.index("def _create_atlas_uv(")
    ]
    assert proof.index("_require_generated_uv_resource_bounds(mesh)") < proof.index(
        "values = [0.0]"
    )
    create = source[source.index("def _create_atlas_uv(") : source.index("def _mesh_world_bounds(")]
    assert create.index("_require_generated_uv_resource_bounds(mesh)") < create.index(
        "mesh.uv_layers.new"
    )


def test_nested_group_depth_and_presort_native_counts_fail_closed():
    """Group depth and native counts stop traversal before unbounded recursion or sorting."""
    deepest = Group([])
    for index in range(65):
        deepest = Group([SimpleNamespace(type="GROUP", name=str(index), node_tree=deepest)])
    material = SimpleNamespace(
        node_tree=Group([SimpleNamespace(type="GROUP", name="Root", node_tree=deepest)])
    )
    check = method("_require_supported_group_uv_sampling")
    with pytest.raises(ValueError, match="group depth limit exceeded"):
        check(material)
    root_large = SimpleNamespace(node_tree=Group(CountOnly(513)))
    with pytest.raises(ValueError, match="node resource limit exceeded"):
        check(root_large)
    nested_large = Group(CountOnly(513))
    nested_material = SimpleNamespace(
        node_tree=Group([SimpleNamespace(type="GROUP", name="Root", node_tree=nested_large)])
    )
    with pytest.raises(ValueError, match="node resource limit exceeded"):
        check(nested_material)
