from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

EXPECTED_TOOLS = {
    "initialize_materials",
    "get_material_presets",
    "generate_procedural_textures",
    "attach_texture_manifest",
    "bake_materials",
    "validate_material_contracts",
    "inspect_materials",
    "render_material_swatches",
    "generate_pdf_report",
    "run_visual_qa",
    "compile_visual_revision",
    "approve_visual_revision",
    "apply_approved_visual_revision",
}


async def _call(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], float]:
    """Call one stdio MCP tool and normalize its structured JSON response."""

    started = perf_counter()
    result = await session.call_tool(
        name,
        arguments,
        read_timeout_seconds=timedelta(seconds=900),
    )
    elapsed = perf_counter() - started
    if result.isError:
        messages = [getattr(item, "text", str(item)) for item in result.content]
        raise RuntimeError(f"MCP tool {name} failed: {' | '.join(messages)}")
    value: Any = result.structuredContent
    if not isinstance(value, dict):
        for item in result.content:
            text_value = getattr(item, "text", None)
            if not isinstance(text_value, str):
                continue
            try:
                parsed = json.loads(text_value)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                value = parsed
                break
    if isinstance(value, dict) and set(value) == {"result"}:
        value = value["result"]
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError(f"MCP tool {name} did not return a JSON object")
    return value, round(elapsed, 3)


async def run() -> dict[str, Any]:
    """Exercise V0.5/V0.6 public tools through the real stdio MCP transport."""

    repo_root = Path(__file__).resolve().parents[1]
    server = StdioServerParameters(
        command="uv",
        args=["run", "cbm-mcp"],
        env=dict(os.environ),
        cwd=str(repo_root),
    )
    report: dict[str, Any] = {"schema_version": "0.6.0", "transport": "stdio"}
    material_job = os.getenv("CBM_V06_MATERIAL_JOB", "geometry_showcase")
    qa_job = os.getenv("CBM_V06_QA_JOB", "first_reference_test")
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_tools()
            tool_names = {tool.name for tool in listed.tools}
            missing = sorted(EXPECTED_TOOLS - tool_names)
            if missing:
                raise RuntimeError(f"V0.6 MCP tools are missing: {missing}")
            report["tools_present"] = sorted(EXPECTED_TOOLS)

            status, status_seconds = await _call(
                session, "get_job_status", {"job_id": material_job}
            )
            if not status["files"]["material_plan"]:
                _, init_seconds = await _call(
                    session,
                    "initialize_materials",
                    {"job_id": material_job},
                )
            else:
                init_seconds = 0.0
            report["status_seconds"] = status_seconds
            presets, presets_seconds = await _call(session, "get_material_presets", {})
            if "rock" not in presets:
                raise RuntimeError("V0.5 MCP material presets are incomplete")
            generated, texture_seconds = await _call(
                session,
                "generate_procedural_textures",
                {
                    "job_id": material_job,
                    "material_id": "mat.blue",
                    "preset": "rock",
                    "resolution": 128,
                    "seed": 606,
                    "uv_set": "UVMap",
                    "overwrite": True,
                    "attach": True,
                },
            )
            material, validate_seconds = await _call(
                session,
                "validate_material_contracts",
                {"job_id": material_job},
            )
            build, build_seconds = await _call(
                session,
                "build_scene",
                {"job_id": material_job},
            )
            baked, bake_seconds = await _call(
                session,
                "bake_materials",
                {
                    "job_id": material_job,
                    "profile": "gltf_pbr",
                    "resolution": 64,
                    "material_ids": ["mat.blue"],
                },
            )
            inspected, inspect_seconds = await _call(
                session,
                "inspect_materials",
                {"job_id": material_job},
            )
            swatches, swatch_seconds = await _call(
                session,
                "render_material_swatches",
                {"job_id": material_job, "size": 256},
            )
            qa, qa_seconds = await _call(
                session,
                "run_visual_qa",
                {"job_id": qa_job},
            )
            material_pdf, material_pdf_seconds = await _call(
                session,
                "generate_pdf_report",
                {"job_id": material_job, "scope": "material"},
            )
            qa_pdf, qa_pdf_seconds = await _call(
                session,
                "generate_pdf_report",
                {"job_id": qa_job, "scope": "qa", "qa_run_id": "latest"},
            )
            if material.get("ok") is not True or inspected.get("ok") is not True:
                raise RuntimeError("V0.6 MCP material validation failed")
            if qa.get("ok") is not True:
                raise RuntimeError("V0.6 MCP visual QA failed")
            report["material"] = {
                "initialize_seconds": init_seconds,
                "presets_seconds": presets_seconds,
                "texture_seconds": texture_seconds,
                "validate_seconds": validate_seconds,
                "build_seconds": build_seconds,
                "bake_seconds": bake_seconds,
                "inspect_seconds": inspect_seconds,
                "swatch_seconds": swatch_seconds,
                "pdf_seconds": material_pdf_seconds,
                "pdf": material_pdf.get("pdf"),
                "pdf_manifest": material_pdf.get("manifest"),
                "texture_manifest": generated.get("manifest_path"),
                "bake_ok": baked.get("ok"),
                "material_count": swatches.get("material_count"),
                "blend": build.get("blend"),
            }
            report["visual_qa"] = {
                "seconds": qa_seconds,
                "run_id": qa.get("run_id"),
                "direct_score": qa.get("direct_score"),
                "candidate_count": qa.get("candidate_count"),
                "pdf_seconds": qa_pdf_seconds,
                "pdf": qa_pdf.get("pdf"),
                "pdf_manifest": qa_pdf.get("manifest"),
            }
    report["ok"] = True
    return report


def main() -> None:
    """Run V0.6 stdio regressions and persist the machine-readable result."""

    report = asyncio.run(run())
    output = Path(__file__).resolve().parents[1] / "reports" / "v06_mcp_regression.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
