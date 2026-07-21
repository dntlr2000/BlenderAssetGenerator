import json
from pathlib import Path

from codex_blender_modeler.models import SceneSpec


def test_example_scene_spec_is_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    raw = json.loads((root / "examples" / "floating_island" / "scene_spec.seed.json").read_text())
    spec = SceneSpec.model_validate(raw)
    assert spec.job_id == "floating_island"
    assert spec.schema_version == "0.2.0"
    assert len(spec.objects) >= 10
    assert len({obj.id for obj in spec.objects}) == len(spec.objects)
