from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATE_SCENE = (
    ROOT / "src" / "codex_blender_modeler" / "blender_scripts" / "validate_scene.py"
)


def _scheduled_modifier_kinds() -> object:
    """Load only the pure scheduling helper without importing Blender's bpy module."""

    source = VALIDATE_SCENE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "DEFERRED_MODIFIER_KINDS"
                for target in node.targets
            )
        )
        or (isinstance(node, ast.FunctionDef) and node.name == "scheduled_modifier_kinds")
    ]
    namespace: dict[str, object] = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(VALIDATE_SCENE), "exec"), namespace)
    return namespace["scheduled_modifier_kinds"]


def test_scene_validation_matches_builder_modifier_scheduling() -> None:
    """Validation expects immediate modifiers before deferred target-dependent kinds."""

    schedule = _scheduled_modifier_kinds()
    modifiers = [
        {"kind": "boolean"},
        {"kind": "bevel"},
        {"kind": "normal_transfer"},
        {"kind": "mirror"},
        {"kind": "boolean"},
    ]

    assert schedule(modifiers) == [
        "bevel",
        "mirror",
        "boolean",
        "normal_transfer",
        "boolean",
    ]


def test_scene_validation_modifier_helpers_have_descriptions() -> None:
    """Every validator method retains the repository-required short description."""

    tree = ast.parse(VALIDATE_SCENE.read_text(encoding="utf-8"))
    missing = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and ast.get_docstring(node) is None
    ]

    assert missing == []
