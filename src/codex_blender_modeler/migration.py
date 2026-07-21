from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .models import SceneSpec


def migrate_v1_raw(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schema_version") == "0.2.0":
        return copy.deepcopy(raw)
    if raw.get("schema_version") not in {"0.1.0", None}:
        raise ValueError(f"Unsupported source schema version: {raw.get('schema_version')!r}")

    migrated = copy.deepcopy(raw)
    migrated["schema_version"] = "0.2.0"
    migrated_objects: list[dict[str, Any]] = []
    for old in migrated["objects"]:
        primitive = old.pop("primitive")
        dimensions = old.pop("dimensions")
        location = old.pop("location")
        rotation = old.pop("rotation_deg", [0.0, 0.0, 0.0])
        bevel = float(old.pop("bevel", 0.0))
        old["geometry"] = {
            "kind": "primitive",
            "primitive": primitive,
            "dimensions": dimensions,
            "segments": 32,
            "ring_segments": 16,
        }
        old["transform"] = {
            "location": location,
            "rotation_deg": rotation,
            "scale": [1.0, 1.0, 1.0],
        }
        old["modifiers"] = (
            [
                {
                    "kind": "bevel",
                    "width": bevel,
                    "segments": 2,
                    "limit_method": "ANGLE",
                }
            ]
            if bevel > 0
            else []
        )
        old["parent_id"] = None
        old["shade_smooth"] = primitive in {"cylinder", "sphere", "cone", "torus"}
        migrated_objects.append(old)
    migrated["objects"] = migrated_objects
    SceneSpec.model_validate(migrated)
    return migrated


def migrate_v1_file(source: Path, destination: Path | None = None) -> Path:
    source = source.resolve()
    raw = json.loads(source.read_text(encoding="utf-8"))
    migrated = migrate_v1_raw(raw)
    destination = (destination or source).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(migrated, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination
