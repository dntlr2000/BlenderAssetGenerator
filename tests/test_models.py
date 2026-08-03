import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from codex_blender_modeler.models import SceneSpec


def test_example_scene_spec_is_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    raw = json.loads((root / "examples" / "floating_island" / "scene_spec.seed.json").read_text())
    spec = SceneSpec.model_validate(raw)
    assert spec.job_id == "floating_island"
    assert spec.schema_version == "0.2.0"
    assert len(spec.objects) >= 10
    assert len({obj.id for obj in spec.objects}) == len(spec.objects)


def test_scene_spec_rejects_self_parent_and_parent_cycle() -> None:
    """SceneSpec hierarchy cannot contain self-links or cyclic parent chains."""

    root = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (root / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text()
    )
    object_ids = [item["id"] for item in raw["objects"][:2]]

    self_parent = deepcopy(raw)
    self_parent["objects"][0]["parent_id"] = object_ids[0]
    with pytest.raises(ValidationError, match="cannot parent themselves"):
        SceneSpec.model_validate(self_parent)

    cycle = deepcopy(raw)
    cycle["objects"][0]["parent_id"] = object_ids[1]
    cycle["objects"][1]["parent_id"] = object_ids[0]
    with pytest.raises(ValidationError, match="parent cycle"):
        SceneSpec.model_validate(cycle)
