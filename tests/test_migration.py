import json
from pathlib import Path

from codex_blender_modeler.migration import migrate_v1_raw
from codex_blender_modeler.models import SceneSpec


def test_v1_primitive_object_migrates_to_geometry_recipe() -> None:
    root = Path(__file__).resolve().parents[1]
    v2 = json.loads(
        (root / "examples" / "floating_island" / "scene_spec.seed.json").read_text()
    )
    # Build a representative old object from the new one.
    raw = json.loads(json.dumps(v2))
    raw["schema_version"] = "0.1.0"
    for obj in raw["objects"]:
        geometry = obj.pop("geometry")
        transform = obj.pop("transform")
        modifiers = obj.pop("modifiers")
        obj["primitive"] = geometry["primitive"]
        obj["dimensions"] = geometry["dimensions"]
        obj["location"] = transform["location"]
        obj["rotation_deg"] = transform["rotation_deg"]
        bevel = next((m["width"] for m in modifiers if m["kind"] == "bevel"), 0.0)
        obj["bevel"] = bevel
        obj.pop("parent_id")
        obj.pop("shade_smooth")

    migrated = migrate_v1_raw(raw)
    parsed = SceneSpec.model_validate(migrated)
    assert parsed.schema_version == "0.2.0"
    assert parsed.objects[0].geometry.kind == "primitive"
