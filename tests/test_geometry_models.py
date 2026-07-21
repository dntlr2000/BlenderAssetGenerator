import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from codex_blender_modeler.models import CustomMeshGeometry, SceneSpec, TerrainGeometry


def test_geometry_showcase_is_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (root / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text()
    )
    spec = SceneSpec.model_validate(raw)
    assert spec.schema_version == "0.2.0"
    assert {
        "custom_mesh",
        "profile_extrude",
        "revolve",
        "curve",
        "terrain",
        "primitive",
    }.issubset({obj.geometry.kind for obj in spec.objects})


def test_custom_mesh_rejects_invalid_face_index() -> None:
    with pytest.raises(ValidationError):
        CustomMeshGeometry(
            vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
            faces=[[0, 1, 99]],
        )


def test_terrain_requires_rectangular_grid() -> None:
    with pytest.raises(ValidationError):
        TerrainGeometry(
            mode="height_grid",
            size=(2, 2, 1),
            heights=[[0, 1], [0]],
        )
