"""Regression coverage for approval-bound multi-view interior QA."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from cli_help_support import assert_cli_help_contract
from jsonschema import Draft202012Validator
from PIL import Image
from typer.testing import CliRunner

import codex_blender_modeler.blender_artifact_runner as artifact_runner
import codex_blender_modeler.interior_qa.service as interior_qa_service
from codex_blender_modeler.architecture import (
    approve_interior_scope,
    initialize_interior_scope,
)
from codex_blender_modeler.blender_artifacts import write_json_atomic
from codex_blender_modeler.cli import app
from codex_blender_modeler.interior_qa import (
    approve_job_interior_qa_plan,
    plan_job_interior_qa,
    run_job_interior_qa,
)
from codex_blender_modeler.interior_qa.models import (
    InteriorQABounds,
    InteriorQALatest,
    InteriorQAObjectRecord,
    InteriorQAPlan,
    InteriorQAPlanApproval,
    InteriorQARenderManifest,
    InteriorQAReport,
    InteriorQARevisionCandidates,
    InteriorQASourceInventory,
    InteriorQATopology,
    InteriorQAViewRender,
)
from codex_blender_modeler.orchestration.service import plan_workflow
from codex_blender_modeler.qa.models import (
    REQUIRED_QA_PASS_KINDS,
    DepthRange,
    RenderPassRecord,
)
from codex_blender_modeler.reporting import (
    collect_job_report_payload,
    generate_job_pdf_report,
)
from codex_blender_modeler.workspace import create_job, sha256_file

ROOT = Path(__file__).resolve().parents[1]
JOB_ID = "interior_qa_asset"


def _scene_payload(job_id: str) -> dict[str, object]:
    """Create one schema-valid static room shell with stable interior identity."""

    return {
        "schema_version": "0.2.0",
        "job_id": job_id,
        "mode": "concept",
        "units": "METERS",
        "nominal_scene_size": [8.0, 6.0, 3.0],
        "sources": [
            {
                "id": "reference",
                "path": "input/reference.png",
                "kind": "reference",
                "immutable": True,
                "scale_anchors": [],
            }
        ],
        "materials": [
            {
                "id": "mat.wall",
                "name": "Wall",
                "shader": "principled",
                "base_color": [0.55, 0.58, 0.62, 1.0],
                "roughness": 0.72,
                "metallic": 0.0,
            }
        ],
        "objects": [
            {
                "id": "building.interior.lobby.shell",
                "name": "Lobby shell",
                "geometry": {
                    "kind": "primitive",
                    "primitive": "cube",
                    "dimensions": [6.0, 4.0, 2.8],
                },
                "material_id": "mat.wall",
                "tags": ["interior", "level:level_01", "space:lobby"],
                "evidence": [
                    {
                        "source_id": "reference",
                        "bbox_norm": [0.1, 0.1, 0.9, 0.9],
                        "status": "inferred",
                        "confidence": 0.7,
                    }
                ],
            }
        ],
        "camera": {
            "projection": "ORTHO",
            "location": [7.0, -9.0, 5.0],
            "target": [0.0, 0.0, 1.2],
            "focal_length_mm": 50.0,
            "ortho_scale": 12.0,
            "resolution": [256, 256],
        },
    }


def _seed_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Create and explicitly approve one isolated InteriorScope test job."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (64, 64), (90, 115, 140)).save(reference)
    create_job(JOB_ID, reference, "concept", [])
    root = workspace / JOB_ID
    scene_path = root / "analysis" / "scene_spec.json"
    scene_path.write_text(
        json.dumps(_scene_payload(JOB_ID), indent=2) + "\n",
        encoding="utf-8",
    )
    initialize_interior_scope(
        JOB_ID,
        policy="proxy",
        request="Inspect only the approved lobby proxy.",
        allowed_semantic_prefixes=["building.interior.lobby"],
        levels=["level_01"],
        spaces=["lobby"],
        evidence_status="inferred",
    )
    scope_path = root / "architecture" / "interior_scope.json"
    approve_interior_scope(
        JOB_ID,
        scope_sha256=sha256_file(scope_path),
        approval_note="User approved the exact lobby proxy boundary.",
        manual_confirmation=True,
    )
    (root / "blender" / "scene.blend").write_bytes(b"authoring-blend-fixture")
    return root


def _mock_source_inspector(
    job_id: str,
    *,
    run_id: str,
    target_ids: list[str],
    output_path: Path,
    scene_spec_sha256: str,
    build_fingerprint: str,
    interior_scope_sha256: str,
    interior_scope_approval_sha256: str,
) -> InteriorQASourceInventory:
    """Write deterministic Blender-like bounds and topology for host service tests."""

    topology = InteriorQATopology(
        vertices=8,
        edges=12,
        polygons=6,
        triangles_estimated=12,
        non_finite_vertex_count=0,
        non_finite_vertices=[],
        degenerate_face_count=0,
        degenerate_faces=[],
        invalid_normal_face_count=0,
        invalid_normal_faces=[],
        boundary_edge_count=0,
        overused_edge_count=0,
        loose_edge_count=0,
        loose_vertex_count=0,
        manifold_closed=True,
        negative_determinant=False,
        matrix_determinant=1.0,
        uv_layers=[],
    )
    inventory = InteriorQASourceInventory(
        job_id=job_id,
        run_id=run_id,
        scene_spec_sha256=scene_spec_sha256,
        build_fingerprint=build_fingerprint,
        interior_scope_sha256=interior_scope_sha256,
        interior_scope_approval_sha256=interior_scope_approval_sha256,
        blender_version="5.0.1",
        objects=[
            InteriorQAObjectRecord(
                name="Lobby shell",
                type="MESH",
                semantic_id=target_ids[0],
                instance_index=0,
                bbox_world=InteriorQABounds(
                    min=(-3.0, -2.0, 0.0),
                    max=(3.0, 2.0, 2.8),
                ),
                dimensions=(6.0, 4.0, 2.8),
                material_ids=["mat.wall"],
                topology=topology,
            )
        ],
    )
    write_json_atomic(output_path, inventory.model_dump(mode="json"))
    return inventory


def _mock_interior_renderer(
    job_id: str,
    *,
    plan_path: Path,
    approval_path: Path,
    output_dir: Path,
    manifest_path: Path,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> InteriorQARenderManifest:
    """Write exact seven-pass fixtures for every approved temporary camera."""

    plan = InteriorQAPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    approval = InteriorQAPlanApproval.model_validate_json(
        approval_path.read_text(encoding="utf-8")
    )
    width, height = plan.resolution
    rendered_views: list[InteriorQAViewRender] = []
    approved = set(approval.approved_view_ids)
    for view in plan.views:
        if view.view_id not in approved:
            continue
        records: list[RenderPassRecord] = []
        for kind in REQUIRED_QA_PASS_KINDS:
            path = output_dir / "passes" / view.view_id / f"{kind}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            color = (255, 0, 0) if kind == "object_id" else (110, 125, 145)
            Image.new("RGB", (width, height), color).save(path)
            records.append(
                RenderPassRecord(
                    kind=kind,
                    path=path.relative_to(output_dir).as_posix(),
                    sha256=sha256_file(path),
                    width=width,
                    height=height,
                    encoding="png_rgb8",
                )
            )
        rendered_views.append(
            InteriorQAViewRender(
                view_id=view.view_id,
                level_id=view.level_id,
                space_id=view.space_id,
                camera={
                    "projection": "PERSP",
                    "location": list(view.location),
                    "target": list(view.target),
                    "focal_length_mm": view.focal_length_mm,
                },
                target_ids=view.target_ids,
                depth_range=DepthRange(near=0.03, far=view.clip_end_m),
                passes=records,
            )
        )
    manifest = InteriorQARenderManifest(
        job_id=job_id,
        run_id=plan.run_id,
        plan_sha256=sha256_file(plan_path),
        plan_approval_sha256=sha256_file(approval_path),
        scene_spec_sha256=plan.scene_spec_sha256,
        build_fingerprint=plan.build_fingerprint,
        interior_scope_sha256=plan.interior_scope_sha256,
        interior_scope_approval_sha256=plan.interior_scope_approval_sha256,
        blender_version="5.0.1",
        render_engine=render_engine,
        render_device=render_device,
        resolution=plan.resolution,
        object_id_colors={plan.target_ids[0]: "#ff0000"},
        material_id_colors={"mat.wall": "#00ff00"},
        views=rendered_views,
    )
    write_json_atomic(manifest_path, manifest.model_dump(mode="json"))
    return manifest


def test_interior_qa_schemas_match_strict_models() -> None:
    """Keep every checked-in interior QA schema synchronized with its host model."""

    contracts = {
        "interior_qa_source_inventory.schema.json": InteriorQASourceInventory,
        "interior_qa_plan.schema.json": InteriorQAPlan,
        "interior_qa_plan_approval.schema.json": InteriorQAPlanApproval,
        "interior_qa_render_manifest.schema.json": InteriorQARenderManifest,
        "interior_qa_report.schema.json": InteriorQAReport,
        "interior_qa_revision_candidates.schema.json": InteriorQARevisionCandidates,
        "interior_qa_latest.schema.json": InteriorQALatest,
    }
    for filename, model in contracts.items():
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema == model.model_json_schema()


def test_plan_requires_exact_approved_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject interior QA before any Blender call when InteriorScope is absent."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (16, 16), (10, 20, 30)).save(reference)
    create_job(JOB_ID, reference, "concept", [])
    root = workspace / JOB_ID
    (root / "analysis" / "scene_spec.json").write_text(
        json.dumps(_scene_payload(JOB_ID), indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="InteriorScope"):
        plan_job_interior_qa(JOB_ID, run_id="missing-scope")

    assert not (root / "qa" / "interior" / "runs" / "missing-scope").exists()


def test_plan_keeps_hidden_boolean_helpers_out_of_render_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain hidden cutters in source evidence without rendering or scoring them."""

    root = _seed_job(tmp_path, monkeypatch)
    scene_path = root / "analysis" / "scene_spec.json"
    scene_payload = json.loads(scene_path.read_text(encoding="utf-8"))
    cutter_id = "building.interior.lobby.forward_wall_cutter"
    cutter = {
        **scene_payload["objects"][0],
        "id": cutter_id,
        "name": "Forward wall Boolean cutter",
        "geometry": {
            "kind": "primitive",
            "primitive": "cube",
            "dimensions": [1.8, 0.4, 2.2],
        },
        "tags": [
            "interior",
            "level:level_01",
            "space:lobby",
            "hidden-boolean-target",
        ],
    }
    scene_payload["objects"].append(cutter)
    scene_path.write_text(
        json.dumps(scene_payload, indent=2) + "\n",
        encoding="utf-8",
    )

    def inspect_with_hidden_helper(
        job_id: str,
        *,
        run_id: str,
        target_ids: list[str],
        output_path: Path,
        scene_spec_sha256: str,
        build_fingerprint: str,
        interior_scope_sha256: str,
        interior_scope_approval_sha256: str,
    ) -> InteriorQASourceInventory:
        """Write both renderable and hidden-helper records for planning coverage."""

        assert target_ids == [
            "building.interior.lobby.forward_wall_cutter",
            "building.interior.lobby.shell",
        ]
        topology = InteriorQATopology(
            vertices=8,
            edges=12,
            polygons=6,
            triangles_estimated=12,
            non_finite_vertex_count=0,
            non_finite_vertices=[],
            degenerate_face_count=0,
            degenerate_faces=[],
            invalid_normal_face_count=0,
            invalid_normal_faces=[],
            boundary_edge_count=0,
            overused_edge_count=0,
            loose_edge_count=0,
            loose_vertex_count=0,
            manifold_closed=True,
            negative_determinant=False,
            matrix_determinant=1.0,
            uv_layers=[],
        )
        inventory = InteriorQASourceInventory(
            job_id=job_id,
            run_id=run_id,
            scene_spec_sha256=scene_spec_sha256,
            build_fingerprint=build_fingerprint,
            interior_scope_sha256=interior_scope_sha256,
            interior_scope_approval_sha256=interior_scope_approval_sha256,
            blender_version="5.0.1",
            objects=[
                InteriorQAObjectRecord(
                    name=semantic_id.rsplit(".", 1)[-1],
                    type="MESH",
                    semantic_id=semantic_id,
                    instance_index=0,
                    bbox_world=InteriorQABounds(
                        min=(-3.0, -2.0, 0.0),
                        max=(3.0, 2.0, 2.8),
                    ),
                    dimensions=(6.0, 4.0, 2.8),
                    material_ids=["mat.wall"],
                    topology=topology,
                )
                for semantic_id in target_ids
            ],
        )
        write_json_atomic(output_path, inventory.model_dump(mode="json"))
        return inventory

    monkeypatch.setattr(
        artifact_runner,
        "inspect_job_interior_qa_source",
        inspect_with_hidden_helper,
    )
    planned = plan_job_interior_qa(
        JOB_ID,
        profile="minimal",
        resolution=128,
        max_views=8,
        run_id="interior-hidden-helper",
    )
    plan = InteriorQAPlan.model_validate_json(
        Path(planned["plan"]).read_text(encoding="utf-8")
    )
    inventory = InteriorQASourceInventory.model_validate_json(
        Path(planned["source_inventory"]).read_text(encoding="utf-8")
    )

    assert plan.target_ids == ["building.interior.lobby.shell"]
    assert all(cutter_id not in view.target_ids for view in plan.views)
    assert {record.semantic_id for record in inventory.objects} == {
        cutter_id,
        "building.interior.lobby.shell",
    }
    assert any(cutter_id in warning for warning in plan.warnings)


def test_entry_camera_uses_local_entry_bounds_above_the_floor() -> None:
    """Keep entry diagnostics centered on the entry at the requested eye height."""

    entry_id = "building.interior.floor.entry_east_stair"
    floor_id = "building.interior.floor.l03"
    groups = {("l03", "entry.east_stair"): [entry_id, floor_id]}
    semantic_bounds = {
        entry_id: InteriorQABounds(
            min=(22.5, -6.6, 7.425),
            max=(27.5, -2.6, 7.675),
        ),
        floor_id: InteriorQABounds(
            min=(-27.0, -8.5, 7.425),
            max=(27.0, 10.5, 7.675),
        ),
    }

    views, warnings = interior_qa_service._build_views(
        groups,
        semantic_bounds,
        profile="standard",
        max_views=6,
        eye_height_m=1.6,
    )

    assert len(views) == 6
    assert warnings == ["max_views limited profile=standard from 8 to 6 views"]
    assert views[0].location == pytest.approx((25.0, -4.6, 9.275))
    assert views[0].target == pytest.approx((25.0, -2.35, 9.275))
    assert all(view.location[2] > semantic_bounds[floor_id].max[2] for view in views)
    assert [view.view_id for view in views[-2:]] == [
        "l03.entry.east_stair.entry_inbound",
        "l03.entry.east_stair.entry_outbound",
    ]
    assert views[-2].purpose == views[-1].purpose == "corridor_axis"


def test_entry_axis_views_cross_the_boundary_in_both_directions() -> None:
    """Aim paired entry cameras from outside-in and inside-out across the same rim."""

    rim_id = "submarine.interior.entry.breach_inner_rim"
    floor_id = "submarine.interior.floor.level_01"
    groups = {("level_01", "main_hall"): [rim_id, floor_id]}
    semantic_bounds = {
        rim_id: InteriorQABounds(
            min=(-7.8, -2.82, 2.4),
            max=(-6.0, -2.74, 5.3),
        ),
        floor_id: InteriorQABounds(
            min=(-4.5, -1.5, 2.42),
            max=(3.9, 1.5, 2.58),
        ),
    }

    views, warnings = interior_qa_service._build_views(
        groups,
        semantic_bounds,
        profile="standard",
        max_views=6,
        eye_height_m=1.6,
    )
    inbound, outbound = views[-2:]
    boundary_y = (
        semantic_bounds[rim_id].min[1] + semantic_bounds[rim_id].max[1]
    ) * 0.5

    assert warnings == ["max_views limited profile=standard from 8 to 6 views"]
    assert inbound.view_id.endswith(".entry_inbound")
    assert inbound.location[1] < boundary_y < inbound.target[1]
    assert outbound.view_id.endswith(".entry_outbound")
    assert outbound.target[1] < boundary_y < outbound.location[1]


def test_entry_axis_views_use_hidden_cutter_as_camera_anchor_only() -> None:
    """Center paired cameras on a hidden cutter without adding it to render targets."""

    threshold_id = "submarine.interior.entry.breach_threshold"
    cutter_id = "submarine.interior.entry.forward_wall_cutter"
    floor_id = "submarine.interior.floor.level_01"
    groups = {("level_01", "main_hall"): [threshold_id, floor_id]}
    semantic_bounds = {
        threshold_id: InteriorQABounds(
            min=(-7.36, -3.28, 2.42),
            max=(-4.10, -0.20, 2.58),
        ),
        cutter_id: InteriorQABounds(
            min=(-4.89, -1.38, 2.55),
            max=(-4.24, -0.03, 4.90),
        ),
        floor_id: InteriorQABounds(
            min=(-4.5, -1.5, 2.42),
            max=(4.2, 1.5, 2.58),
        ),
    }

    views, _warnings = interior_qa_service._build_views(
        groups,
        semantic_bounds,
        profile="standard",
        max_views=6,
        eye_height_m=1.6,
        entry_anchor_groups={("level_01", "main_hall"): [cutter_id]},
    )
    inbound, outbound = views[-2:]
    cutter_center = tuple(
        (
            semantic_bounds[cutter_id].min[axis]
            + semantic_bounds[cutter_id].max[axis]
        )
        * 0.5
        for axis in range(2)
    )
    inbound_direction = (
        inbound.target[0] - inbound.location[0],
        inbound.target[1] - inbound.location[1],
    )
    anchor_offset = (
        cutter_center[0] - inbound.location[0],
        cutter_center[1] - inbound.location[1],
    )
    cross_product = (
        inbound_direction[0] * anchor_offset[1]
        - inbound_direction[1] * anchor_offset[0]
    )

    assert cross_product == pytest.approx(0.0, abs=1e-8)
    assert cutter_id not in inbound.target_ids
    assert cutter_id not in outbound.target_ids


def test_plan_approve_run_and_pdf_preserve_canonical_authoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise plan, exact approval, seven-pass run, report, and PDF derivation."""

    root = _seed_job(tmp_path, monkeypatch)
    monkeypatch.setattr(
        artifact_runner,
        "inspect_job_interior_qa_source",
        _mock_source_inspector,
    )
    monkeypatch.setattr(
        artifact_runner,
        "render_job_interior_qa",
        _mock_interior_renderer,
    )
    scene_path = root / "analysis" / "scene_spec.json"
    blend_path = root / "blender" / "scene.blend"
    before = (sha256_file(scene_path), sha256_file(blend_path))

    planned = plan_job_interior_qa(
        JOB_ID,
        profile="minimal",
        resolution=128,
        max_views=8,
        run_id="interior-run-001",
    )
    assert planned["status"] == "awaiting_approval"
    assert planned["view_count"] == 4
    with pytest.raises(ValueError, match="does not match"):
        approve_job_interior_qa_plan(
            JOB_ID,
            "interior-run-001",
            plan_sha256="0" * 64,
            approval_note="Wrong hash must fail.",
        )
    approve_job_interior_qa_plan(
        JOB_ID,
        "interior-run-001",
        plan_sha256=str(planned["plan_sha256"]),
        approval_note="User approved all four exact interior views.",
    )
    result = run_job_interior_qa(
        JOB_ID,
        "interior-run-001",
        approved_plan_sha256=str(planned["plan_sha256"]),
    )

    assert result["ok"] is True
    assert result["pass_count"] == 28
    assert result["semantic_visibility_fraction"] == 1.0
    assert result["reference_comparison_status"] == "unavailable"
    assert len(result["contact_sheets"]) == 3
    assert before == (sha256_file(scene_path), sha256_file(blend_path))
    approval = InteriorQAPlanApproval.model_validate_json(
        (
            root
            / "qa"
            / "interior"
            / "runs"
            / "interior-run-001"
            / "plan_approval.json"
        ).read_text(encoding="utf-8")
    )
    assert approval.status == "consumed"
    with pytest.raises(PermissionError, match="already been consumed"):
        run_job_interior_qa(
            JOB_ID,
            "interior-run-001",
            approved_plan_sha256=str(planned["plan_sha256"]),
        )

    payload = collect_job_report_payload(
        JOB_ID,
        "qa",
        interior_qa_run_id="interior-run-001",
    )
    assert payload["interior_qa_run_id"] == "interior-run-001"
    assert payload["documents"]["interior_qa_report"]["semantic_visibility_fraction"] == 1.0
    assert len(payload["images"]["interior_qa_contact_sheets"]) == 3
    pdf = generate_job_pdf_report(
        JOB_ID,
        "qa",
        interior_qa_run_id="interior-run-001",
    )
    manifest = json.loads(Path(pdf["manifest"]).read_text(encoding="utf-8"))
    assert manifest["interior_qa_run_id"] == "interior-run-001"
    assert any(
        source["kind"].startswith("interior_qa_")
        for source in manifest["sources"]
    )


def test_v08_routes_interior_visual_qa_through_specialized_plan_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep short-request automation behind the exact interior camera-plan gate."""

    root = _seed_job(tmp_path, monkeypatch)
    (root / "reports" / "validation.json").write_text(
        json.dumps({"ok": True}) + "\n",
        encoding="utf-8",
    )
    state = plan_workflow(
        "실내 QA를 여러 각도에서 수행해줘",
        job_id=JOB_ID,
        intent="interior_visual_qa",
    )
    plan = json.loads(
        (
            root / "workflows" / state.workflow_id / "plan.json"
        ).read_text(encoding="utf-8")
    )
    steps = {item["step_id"]: item for item in plan["steps"]}

    assert plan["intent"] == "interior_visual_qa"
    assert steps["interior_qa.plan"]["tool_name"] == "plan_interior_qa"
    assert steps["interior_qa.plan_approval"]["approval_gate"] == "interior_qa_plan"
    assert steps["interior_qa.run"]["tool_name"] == "run_interior_qa"
    assert steps["interior_qa.report"]["parameters"]["interior_qa_run_id"].startswith(
        "v08-interior-"
    )


def test_interior_qa_public_surface_and_allowlist_are_available() -> None:
    """Expose only bounded plan, approval, execution, and status operations."""

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert_cli_help_contract(
        result.output,
        required=(
            "interior-qa-plan",
            "interior-qa-plan-approve",
            "interior-qa-run",
            "interior-qa-status",
        ),
    )
    config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert {
        "plan_interior_qa",
        "approve_interior_qa_plan",
        "run_interior_qa",
        "get_interior_qa_status",
    }.issubset(enabled)
