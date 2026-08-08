from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_TEXTURED_REPRESENTATIONS = {"texture_channels", "baked_decal"}
_UV_STRATEGIES = {"existing_uv", "projected_patch", "material_atlas"}
_GENERATING_UV_STRATEGIES = {"projected_patch", "material_atlas"}


def _load_modeling_plan(job_root: Path) -> dict[str, Any] | None:
    """Load one optional ModelingPlan using Blender's standard-library runtime."""

    path = job_root / "analysis" / "modeling_plan.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ModelingPlan is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"ModelingPlan root must be an object: {path}")
    return payload


def load_surface_detail_uv_requirements(
    job_root: Path,
) -> dict[str, dict[str, Any]]:
    """Resolve per-parent UVMap requirements from non-omitted V0.4 surface details."""

    plan = _load_modeling_plan(job_root.expanduser().resolve())
    if plan is None:
        return {}
    raw_details = plan.get("surface_details", [])
    if not isinstance(raw_details, list):
        raise RuntimeError("ModelingPlan surface_details must be an array")

    grouped: dict[str, dict[str, set[str]]] = {}
    seen_detail_ids: set[str] = set()
    for index, detail in enumerate(raw_details):
        if not isinstance(detail, dict):
            raise RuntimeError(f"ModelingPlan surface_details[{index}] must be an object")
        detail_id = detail.get("id")
        if not isinstance(detail_id, str) or not detail_id.strip():
            raise RuntimeError(
                f"ModelingPlan surface_details[{index}] requires a stable non-empty id"
            )
        if detail_id in seen_detail_ids:
            raise RuntimeError(f"ModelingPlan surface detail ID is duplicated: {detail_id}")
        seen_detail_ids.add(detail_id)

        representation = detail.get("representation")
        if representation == "omit":
            continue
        if representation not in _TEXTURED_REPRESENTATIONS:
            raise RuntimeError(
                f"Surface detail {detail_id} has unsupported representation: "
                f"{representation!r}"
            )
        parent_id = detail.get("parent_object_id")
        if not isinstance(parent_id, str) or not parent_id.strip():
            raise RuntimeError(f"Surface detail {detail_id} requires parent_object_id")
        strategy = detail.get("uv_strategy")
        if strategy not in _UV_STRATEGIES:
            raise RuntimeError(
                f"Surface detail {detail_id} requires one supported uv_strategy"
            )
        target = grouped.setdefault(
            parent_id,
            {"detail_ids": set(), "strategies": set()},
        )
        target["detail_ids"].add(detail_id)
        target["strategies"].add(str(strategy))

    requirements: dict[str, dict[str, Any]] = {}
    for parent_id, grouped_item in sorted(grouped.items()):
        strategies = sorted(grouped_item["strategies"])
        requirements[parent_id] = {
            "mode": "uv",
            "uv_set": "UVMap",
            "generate_if_missing": bool(
                set(strategies).intersection(_GENERATING_UV_STRATEGIES)
            ),
            "detail_ids": sorted(grouped_item["detail_ids"]),
            "strategies": strategies,
        }
    return requirements
