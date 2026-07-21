from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REQUIRED_GEOMETRY = {
    "primitive",
    "custom_mesh",
    "profile_extrude",
    "revolve",
    "curve",
    "terrain",
}
REQUIRED_MODIFIERS = {
    "bevel",
    "mirror",
    "subdivision",
    "solidify",
    "array",
    "decimate",
    "remesh",
    "boolean",
}


def parse_args() -> argparse.Namespace:
    """Parse MCP regression jobs and Blender render configuration."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--jobs",
        nargs="+",
        default=["geometry_showcase", "measured_box", "first_reference_test"],
    )
    parser.add_argument("--render-engine", choices=["eevee", "cycles"], default="cycles")
    parser.add_argument("--render-device", choices=["auto", "cpu", "gpu"], default="gpu")
    return parser.parse_args()


def compact_result(value: dict[str, Any] | None) -> dict[str, Any]:
    """Remove verbose Blender logs while retaining MCP success evidence."""

    if not value:
        return {}
    if set(value) == {"result"}:
        nested = value["result"]
        if isinstance(nested, dict):
            value = nested
        elif isinstance(nested, str):
            parsed = json.loads(nested)
            if isinstance(parsed, dict):
                value = parsed
    compact = dict(value)
    log = compact.pop("log", None)
    if log:
        compact["log_tail"] = str(log)[-500:]
    return compact


async def call_tool(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], float]:
    """Call one stdio MCP tool, fail on protocol errors, and return elapsed seconds."""

    started = perf_counter()
    result = await session.call_tool(
        name,
        arguments or {},
        read_timeout_seconds=timedelta(seconds=900),
    )
    elapsed = perf_counter() - started
    if result.isError:
        messages = [getattr(item, "text", str(item)) for item in result.content]
        raise RuntimeError(f"MCP tool {name} failed: {' | '.join(messages)}")
    structured = result.structuredContent
    if not isinstance(structured, dict):
        for item in result.content:
            text_value = getattr(item, "text", None)
            if not isinstance(text_value, str):
                continue
            try:
                parsed = json.loads(text_value)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                structured = parsed
                break
    compact = compact_result(structured if isinstance(structured, dict) else None)
    if name == "inspect_scene" and compact:
        compact = {
            "job_id": compact.get("job_id"),
            "blender_version": compact.get("blender_version"),
            "render_engine": compact.get("render_engine"),
            "render_device": compact.get("render_device"),
            "cycles_compute_backend": compact.get("cycles_compute_backend"),
            "cycles_devices": compact.get("cycles_devices"),
            "object_count": compact.get("object_count"),
            "family_count": len(compact.get("families", [])),
            "material_count": len(compact.get("materials", [])),
        }
    return compact, elapsed


async def run(args: argparse.Namespace) -> dict[str, Any]:
    """Execute capabilities and Blender build/render/inspect/validate through stdio MCP."""

    repo_root = Path(__file__).resolve().parents[1]
    server = StdioServerParameters(
        command="uv",
        args=["run", "cbm-mcp"],
        env=dict(os.environ),
        cwd=str(repo_root),
    )
    report: dict[str, Any] = {
        "schema_version": "0.1.0",
        "transport": "stdio",
        "render_engine_requested": args.render_engine,
        "render_device_requested": args.render_device,
        "jobs": {},
    }
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            capabilities, elapsed = await call_tool(session, "get_modeling_capabilities")
            report["capabilities"] = capabilities
            report["capabilities_seconds"] = round(elapsed, 3)
            geometry = set(capabilities.get("geometry_kinds", []))
            modifiers = set(capabilities.get("modifier_kinds", []))
            if geometry != REQUIRED_GEOMETRY:
                raise RuntimeError(f"Geometry capabilities mismatch: {sorted(geometry)}")
            if modifiers != REQUIRED_MODIFIERS:
                raise RuntimeError(f"Modifier capabilities mismatch: {sorted(modifiers)}")

            for job_id in args.jobs:
                job_report: dict[str, Any] = {"tools": {}}
                for tool_name in (
                    "build_scene",
                    "render_preview",
                    "inspect_scene",
                    "validate_scene",
                ):
                    tool_args: dict[str, Any] = {"job_id": job_id}
                    if tool_name in {"build_scene", "render_preview"}:
                        tool_args.update(
                            {
                                "render_engine": args.render_engine,
                                "render_device": args.render_device,
                            }
                        )
                    value, seconds = await call_tool(session, tool_name, tool_args)
                    job_report["tools"][tool_name] = {
                        "seconds": round(seconds, 3),
                        "result": value,
                    }
                inventory_path = (
                    repo_root
                    / "workspaces"
                    / job_id
                    / "reports"
                    / "scene_inventory.json"
                )
                validation_path = repo_root / "workspaces" / job_id / "reports" / "validation.json"
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                validation = json.loads(validation_path.read_text(encoding="utf-8"))
                if validation.get("ok") is not True:
                    raise RuntimeError(f"{job_id} validation failed: {validation.get('errors')}")
                if inventory.get("render_engine") != args.render_engine.upper():
                    raise RuntimeError(
                        f"{job_id} render engine mismatch: {inventory.get('render_engine')}"
                    )
                if inventory.get("render_device") != args.render_device.upper():
                    raise RuntimeError(
                        f"{job_id} render device mismatch: {inventory.get('render_device')}"
                    )
                job_report["runtime"] = {
                    "blender_version": inventory.get("blender_version"),
                    "render_engine": inventory.get("render_engine"),
                    "render_device": inventory.get("render_device"),
                    "cycles_compute_backend": inventory.get("cycles_compute_backend"),
                    "cycles_devices": inventory.get("cycles_devices"),
                    "object_count": inventory.get("object_count"),
                }
                job_report["validation"] = validation
                report["jobs"][job_id] = job_report
    report["ok"] = True
    return report


def main() -> None:
    """Run stdio MCP regressions and write a durable report for the V0.4 gate."""

    args = parse_args()
    report = asyncio.run(run(args))
    output = Path(__file__).resolve().parents[1] / "reports" / "v04_mcp_regression.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
