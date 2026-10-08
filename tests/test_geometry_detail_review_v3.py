"""Verify strict opted-in geometry fidelity evidence without changing legacy score semantics."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from test_qa_multiview_sanity import JOB_ID, _mock_renderer, _seed_job

from codex_blender_modeler.blender_artifacts import stable_json_digest, write_json_atomic
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.orchestration import service as workflow_service
from codex_blender_modeler.qa import multiview_sanity as sanity
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.qa.fidelity_review import (
    POLICY,
    validate_detail_review_contract,
)
from codex_blender_modeler.workspace import sha256_file


def _renderer(*, canonical: bool = True, failed_contact: bool = False):
    """Extend the existing mock with exact fixed-camera pixels; no visual truth is claimed."""
    base = _mock_renderer()

    def render(script_name, arguments, *, blend_file):
        """Publish matching v3 native-format evidence including optional degraded constraints."""
        base(script_name, arguments, blend_file=blend_file)
        args = dict(zip(arguments[::2], arguments[1::2], strict=True))
        root = Path(args["--job-root"])
        manifest_path = Path(args["--manifest"])
        payload = json.loads(manifest_path.read_text())
        if canonical:
            scene = SceneSpec.model_validate_json(Path(args["--scene-spec"]).read_bytes())
            path = manifest_path.parent / "canonical_beauty.png"
            Image.new("RGB", scene.camera.resolution, (90, 100, 110)).save(path)
            payload["canonical_detail_evidence"] = {
                "camera_fingerprint": camera_fingerprint(scene),
                "beauty": {
                    "kind": "beauty",
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha256_file(path),
                    "width": scene.camera.resolution[0],
                    "height": scene.camera.resolution[1],
                    "encoding": "png-rgb8",
                },
            }
        if failed_contact:
            payload["assembly_evaluation"] = {
                "policy": "spatial_v1",
                "status": "failed",
                "ok": False,
                "checks": [
                    {
                        "id": "contact.gap",
                        "status": "failed",
                        "required": True,
                        "subject_id": "weapon.trigger",
                        "reference_id": "weapon.root",
                        "message": "Required bound-face contact has an actual gap",
                    }
                ],
            }
        write_json_atomic(manifest_path, payload)

    return render


def _run(tmp_path, monkeypatch, *, canonical=True, modular=False, failed_contact=False):
    """Prepare fresh v3 source/run fixtures, without a pre-existing canonical QA manifest."""
    root = _seed_job(tmp_path, monkeypatch)
    if modular or failed_contact:
        path = root / "analysis/modeling_plan.json"
        payload = json.loads(path.read_text())
        if modular:
            payload["objects"][1]["assembly_role"] = "free_standing"
            payload["assembly_relationships"] = []
        else:
            payload["assembly_relationships"] = [
                {
                    "id": "contact.trigger",
                    "kind": "surface_contact",
                    "subject_id": "weapon.trigger",
                    "reference_id": "weapon.root",
                    "axis": "Z",
                    "subject_side": "MAX",
                    "reference_side": "MIN",
                    "required": True,
                }
            ]
        write_json_atomic(path, payload)
    assert not (root / "reports/qa_pass_manifest.json").exists()
    planned = sanity.plan_job_assembly_multiview_sanity(
        JOB_ID, run_id="v3-detail", resolution=128, review_policy=POLICY
    )
    monkeypatch.setattr(
        sanity, "run_blender", _renderer(canonical=canonical, failed_contact=failed_contact)
    )
    result = sanity.run_job_assembly_multiview_sanity(
        JOB_ID, "v3-detail", plan_sha256=planned["plan_sha256"]
    )
    plan = sanity.AssemblySanityPlan.model_validate_json(Path(result["plan"]).read_bytes())
    return root, plan, result


def _review(root, plan, result, *, outcome="visually_supported", aspect="internal_form"):
    """Create explicit fixture assessments; these test mechanics, not real visual acceptance."""
    contract = plan.detail_review_contract
    assessments = []
    keys = [(target, "internal_form") for target in contract.internal_form_target_ids]
    keys += [(target, "attachment") for target in contract.attachment_target_ids]
    keys += [(plan.assembly_frame.root_object_id, "reference_internal_detail")]
    findings = []
    for index, (target, kind) in enumerate(keys):
        selected = outcome if kind == aspect else "visually_supported"
        finding_ids = []
        if selected != "visually_supported":
            fid = f"fixture-detail-{index}"
            finding_ids = [fid]
            findings.append(
                {
                    "finding_id": fid,
                    "issue_type": (
                        "insufficient_evidence" if selected == "unscorable" else "shape_coherence"
                    ),
                    "severity": "warning",
                    "view_ids": ["front", "oblique"],
                    "target_ids": [target],
                    "description": "Fixture observation requires bounded follow-up",
                    "recommended_v04_action": (
                        "additional_evidence" if selected == "unscorable" else "parametric_revision"
                    ),
                }
            )
        assessments.append(
            {
                "target_id": target,
                "aspect": kind,
                "outcome": selected,
                "reference_basis": (
                    "observed_reference"
                    if kind == "reference_internal_detail"
                    or target in contract.observed_reference_target_ids
                    else "inferred_only"
                ),
                "view_ids": ["front", "oblique"],
                "observation": "Explicit fixture-only observation",
                "limitations": "Hidden geometry inferred; texture appearance is not certified",
                "finding_ids": finding_ids,
                "attachment_reference_ids": (
                    [plan.assembly_frame.root_object_id] if kind == "attachment" else []
                ),
            }
        )
    review = sanity.GeometryMultiviewVisualReview.model_validate(
        {
            "job_id": JOB_ID,
            "run_id": plan.run_id,
            "plan_sha256": result["plan_sha256"],
            "render_manifest_sha256": result["render_manifest_sha256"],
            "structural_report_sha256": result["report_sha256"],
            "reviewed_view_ids": list(sanity.ASSEMBLY_SANITY_VIEW_IDS),
            "reviewed_pass_kinds": ["beauty", "wireframe"],
            "outcome": (
                "unscorable"
                if outcome == "unscorable"
                else "v04_revision_recommended"
                if outcome == "defect"
                else "visually_coherent"
            ),
            "v04_reentry": "recommended" if outcome == "defect" else "not_indicated",
            "findings": findings,
            "reviewed_at": datetime.now(UTC),
            "detail_assessments": assessments,
            "reviewed_detail_contract_sha256": stable_json_digest(contract.model_dump(mode="json")),
        }
    )
    path = root / "qa/assembly_sanity/runs" / plan.run_id / "visual_review.json"
    write_json_atomic(path, review.model_dump(mode="json"))
    return path, review


def _completion(root, plan):
    """Exercise the actual normal-workflow agent completion semantics, before marker writes."""
    step = SimpleNamespace(
        step_id="detail.geometry_multiview_visual_review",
        tool_name="review_geometry_multiview",
        parameters={"run_id": plan.run_id, "review_policy": POLICY},
        outputs=[],
    )
    workflow_service._validate_agent_completion_semantics(
        root, step, SimpleNamespace(geometry_review_policy=POLICY)
    )


def test_v3_fresh_canonical_snapshot_and_positive_review(tmp_path, monkeypatch):
    """A fresh native-format run can advance on explicit bounded visual evidence."""
    root, plan, result = _run(tmp_path, monkeypatch)
    contract = validate_detail_review_contract(root, plan)
    assert contract.attachment_target_ids == ["weapon.trigger"]
    assert contract.broad_phase_relation_ids == ["center.trigger"]
    assert contract.attachment_evidence == "broad_phase_only"
    assert contract.internal_detail_evidence == "unverified"
    assert not contract.whole_asset_fidelity_verified
    path, review = _review(root, plan, result)
    assert sanity.validate_geometry_multiview_visual_review(root, path) == review
    _completion(root, plan)


@pytest.mark.parametrize(
    "outcome,reason",
    [("defect", "revision_required"), ("unscorable", "additional_evidence_required")],
)
@pytest.mark.parametrize("aspect", ["internal_form", "attachment", "reference_internal_detail"])
def test_high_scores_cannot_clear_failed_or_missing_review(
    tmp_path, monkeypatch, outcome, reason, aspect
):
    """Even perfect outline/roundtrip inputs cannot waive mandatory source-bound review."""
    root, plan, result = _run(tmp_path, monkeypatch)
    path, review = _review(root, plan, result, outcome=outcome, aspect=aspect)
    # The manual outcome remains loadable historical evidence and does not forge acceptance.
    assert sanity.validate_geometry_multiview_visual_review(root, path) == review
    with pytest.raises(ValueError, match=reason):
        _completion(root, plan)
    assert not list((root / "workflows").glob("**/*completion*"))


def test_empty_detail_and_whole_reference_assessments_cannot_clear(tmp_path, monkeypatch):
    """Inferred-only partitions and absent declarations still require full-reference review."""
    root, plan, result = _run(tmp_path, monkeypatch)
    assert plan.detail_review_contract.surface_detail_ids == []
    assert plan.detail_review_contract.observed_reference_target_ids == []
    path, review = _review(root, plan, result)
    data = review.model_dump(mode="json")
    data["detail_assessments"] = [
        x for x in data["detail_assessments"] if x["aspect"] != "reference_internal_detail"
    ]
    write_json_atomic(path, data)
    with pytest.raises(ValueError, match="one assessment"):
        sanity.validate_geometry_multiview_visual_review(root, path)


def test_intentionally_modular_asset_is_not_failed_for_separation(tmp_path, monkeypatch):
    """Free-standing parts retain geometry review without an invented attachment requirement."""
    root, plan, result = _run(tmp_path, monkeypatch, modular=True)
    assert plan.detail_review_contract.attachment_target_ids == []
    _review(root, plan, result)
    _completion(root, plan)


def test_actual_required_contact_failure_stops_even_positive_visual_fixture(tmp_path, monkeypatch):
    """A declared required contact violation cannot disappear behind a positive visual row."""
    root, plan, result = _run(tmp_path, monkeypatch, failed_contact=True)
    _review(root, plan, result)
    with pytest.raises(ValueError, match="required assembly constraints failed"):
        _completion(root, plan)


@pytest.mark.parametrize("field", ["scene_spec", "modeling_plan", "reference"])
def test_source_snapshot_tamper_rejected(tmp_path, monkeypatch, field):
    """Snapshot hash binding is replayed even when the outer source plan stays unchanged."""
    root, plan, result = _run(tmp_path, monkeypatch)
    path, _ = _review(root, plan, result)
    artifact = getattr(plan.detail_review_contract, field)
    (root / artifact.path).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed"):
        sanity.validate_geometry_multiview_visual_review(root, path)


def test_canonical_pixels_tamper_rejected(tmp_path, monkeypatch):
    """An unchanged outline or manifest cannot authorize substituted internal-detail pixels."""
    root, plan, result = _run(tmp_path, monkeypatch)
    path, _ = _review(root, plan, result)
    path.with_name("canonical_beauty.png").write_bytes(b"changed-canonical-pixels")
    with pytest.raises(ValueError, match="canonical detail image.*changed"):
        sanity.validate_geometry_multiview_visual_review(root, path)


def test_absent_canonical_evidence_fails_native_terminal(tmp_path, monkeypatch):
    """New v3 terminal cannot pass with only its old twenty uncalibrated passes."""
    with pytest.raises(ValueError, match="fixed-camera beauty"):
        _run(tmp_path, monkeypatch, canonical=False)


def test_later_source_revision_does_not_rewrite_historical_v3_evidence(tmp_path, monkeypatch):
    """Immutable snapshot replay survives expected later source supersession."""
    root, plan, result = _run(tmp_path, monkeypatch)
    path, review = _review(root, plan, result)
    (root / "analysis/scene_spec.json").write_text('{"later":"revision"}')
    assert sanity.validate_geometry_multiview_visual_review(root, path) == review


def test_v2_serialization_and_replay_remain_without_new_fields(tmp_path, monkeypatch):
    """Loading old policies never silently creates v3 proof or changes their projections."""
    root = _seed_job(tmp_path, monkeypatch)
    planned = sanity.plan_job_assembly_multiview_sanity(JOB_ID, run_id="legacy-v2", resolution=128)
    monkeypatch.setattr(sanity, "run_blender", _mock_renderer())
    result = sanity.run_job_assembly_multiview_sanity(
        JOB_ID, "legacy-v2", plan_sha256=planned["plan_sha256"]
    )
    for key, cls in (
        ("plan", sanity.AssemblySanityPlan),
        ("render_manifest", sanity.AssemblySanityRenderManifest),
        ("report", sanity.AssemblySanityReport),
    ):
        payload = json.loads(Path(result[key]).read_text())
        assert not any(name.startswith(("detail_", "canonical_detail_")) for name in payload)
        assert cls.model_validate(payload).model_dump(mode="json") == payload
    assert not (root / "qa/assembly_sanity/runs/legacy-v2/detail_review_inputs").exists()


@pytest.mark.skipif(os.getenv("CBM_RUN_BLENDER_ASSEMBLY_SMOKE") != "1", reason="native opt-in")
def test_native_v3_fixed_camera_capture_and_source_preservation(tmp_path, monkeypatch):
    """Execute real Blender 5.0.1 fixed-camera plus five-view evidence before any QA run."""
    from test_blender_assembly_runtime import _smoke_plan, _smoke_scene

    from codex_blender_modeler.blender_runner import run_blender
    from codex_blender_modeler.workspace import create_job

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), (120, 130, 140)).save(reference)
    create_job(JOB_ID, reference, "concept", [])
    root = tmp_path / "workspaces" / JOB_ID
    scene = root / "analysis/scene_spec.json"
    write_json_atomic(scene, _smoke_scene(JOB_ID, 0.0))
    write_json_atomic(root / "analysis/modeling_plan.json", _smoke_plan(JOB_ID))
    blend = root / "blender/scene.blend"
    run_blender(
        "build_scene.py",
        ["--spec", str(scene), "--job-root", str(root), "--output", str(blend)],
        factory_startup=True,
    )
    before = sha256_file(blend)
    planned = sanity.plan_job_assembly_multiview_sanity(
        JOB_ID, run_id="native-v3", resolution=128, review_policy=POLICY
    )
    result = sanity.run_job_assembly_multiview_sanity(
        JOB_ID, "native-v3", plan_sha256=planned["plan_sha256"]
    )
    manifest = sanity.AssemblySanityRenderManifest.model_validate_json(
        Path(result["render_manifest"]).read_bytes()
    )
    assert manifest.blender_version.startswith("5.0.1")
    record = manifest.canonical_detail_evidence.beauty
    with Image.open(root / record.path) as image:
        assert image.size == (320, 240)
    assert sha256_file(blend) == before
    assert result["view_count"] == 5 and result["pass_count"] == 20
    assert not (root / "reports/qa_pass_manifest.json").exists()


def test_selected_workflow_policy_is_mandatory_only_after_proxy(tmp_path, monkeypatch):
    """The normal full geometry workflow selects strict detail review without a proxy deadlock."""
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), (100, 120, 130)).save(reference)
    root = tmp_path / "workspaces" / JOB_ID
    state = workflow_service.plan_workflow(
        "Build this reference with geometry fidelity review",
        job_id=JOB_ID,
        reference_path=str(reference),
        intent="new_asset",
        scope="full",
        delivery_scope="preview_only",
        geometry_review_policy=POLICY,
    )
    plan = json.loads((root / "workflows" / state.workflow_id / "plan.json").read_text())
    selected = {step["step_id"]: step for step in plan["steps"]}
    assert selected["proxy.geometry_multiview"]["parameters"]["review_policy"] == (
        "exterior_geometry_review_v2"
    )
    assert selected["detail.geometry_multiview"]["parameters"]["review_policy"] == POLICY
    assert (
        selected["detail.geometry_multiview_visual_review"]["parameters"]["review_policy"] == POLICY
    )
    request = json.loads((root / "workflows" / state.workflow_id / "request.json").read_text())
    assert request["geometry_review_policy"] == POLICY


def test_selected_policy_cannot_silently_disappear_on_proxy_only(tmp_path, monkeypatch):
    """Unsupported selected routes fail explicitly rather than accept an unreviewed asset."""
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), (100, 120, 130)).save(reference)
    with pytest.raises(ValueError, match="cannot silently fall back"):
        workflow_service.plan_workflow(
            "Build reference",
            job_id=JOB_ID,
            intent="new_asset",
            scope="proxy_only",
            reference_path=str(reference),
            geometry_review_policy=POLICY,
        )


def test_observation_basis_cannot_upgrade_inferred_partition(tmp_path, monkeypatch):
    """Uncertain depth stays inferred even with source-bound whole-reference detail review."""
    root, plan, result = _run(tmp_path, monkeypatch)
    path, review = _review(root, plan, result)
    data = review.model_dump(mode="json")
    data["detail_assessments"][0]["reference_basis"] = "observed_reference"
    write_json_atomic(path, data)
    with pytest.raises(ValueError, match="promote inferred"):
        sanity.validate_geometry_multiview_visual_review(root, path)


def test_changed_detail_contract_digest_cannot_clear(tmp_path, monkeypatch):
    """A review prepared for another input contract cannot be reused by matching target IDs."""
    root, plan, result = _run(tmp_path, monkeypatch)
    path, review = _review(root, plan, result)
    data = review.model_dump(mode="json")
    data["reviewed_detail_contract_sha256"] = "a" * 64
    write_json_atomic(path, data)
    with pytest.raises(ValueError, match="exact source/image contract"):
        sanity.validate_geometry_multiview_visual_review(root, path)


def test_public_cli_and_mcp_select_same_policy(tmp_path, monkeypatch):
    """Both existing public planning commands forward the additive selector explicitly."""
    from typer.testing import CliRunner

    from codex_blender_modeler import cli, mcp_server

    seen = []

    def capture(job_id, **kwargs):
        """Record a public call without building anything in the test fixture."""
        seen.append((job_id, kwargs))
        return {"status": "planned"}

    monkeypatch.setattr(cli, "plan_job_assembly_multiview_sanity", capture)
    monkeypatch.setattr(mcp_server, "plan_job_assembly_multiview_sanity", capture)
    result = CliRunner().invoke(
        cli.app, ["qa-assembly-sanity-plan", JOB_ID, "--review-policy", POLICY]
    )
    assert result.exit_code == 0, result.output
    mcp_server.plan_assembly_multiview_sanity(JOB_ID, review_policy=POLICY)
    assert len(seen) == 2 and seen[0] == seen[1]
    assert seen[0][1]["review_policy"] == POLICY


def test_direct_score_scope_is_explicit_and_metric_unchanged(tmp_path, monkeypatch):
    """Scope warnings are added without changing the canonical numerical score formula."""
    from codex_blender_modeler.qa.direct_compare import _overall_direct_score
    from codex_blender_modeler.qa.models import BoundingBoxMetric

    box = BoundingBoxMetric(
        reference_bbox_norm=(0, 0, 1, 1),
        rendered_bbox_norm=(0, 0, 1, 1),
        center_error_norm=0,
        size_error_norm=0,
    )
    score, version = _overall_direct_score(1.0, box, [])
    assert score == 1.0 and version == "legacy_bbox_v1"
    root, plan, result = _run(tmp_path, monkeypatch)
    _review(root, plan, result, outcome="defect", aspect="reference_internal_detail")
    with pytest.raises(ValueError, match="revision_required"):
        _completion(root, plan)


def test_selected_manual_revision_workflow_keeps_v3_gate(tmp_path, monkeypatch):
    """A normal existing-asset manual revision selects the same mandatory evidence boundary."""
    root = _seed_job(tmp_path, monkeypatch)
    state = workflow_service.plan_workflow(
        "Revise reference internal geometry",
        job_id=JOB_ID,
        intent="revise_asset",
        scope="geometry_only",
        revision_strategy="manual_guarded",
        geometry_review_policy=POLICY,
    )
    plan = json.loads((root / "workflows" / state.workflow_id / "plan.json").read_text())
    steps = {step["step_id"]: step for step in plan["steps"]}
    assert steps["revision.geometry_multiview"]["parameters"]["review_policy"] == POLICY
    assert (
        steps["revision.geometry_multiview_visual_review"]["parameters"]["review_policy"] == POLICY
    )


def test_stale_review_cannot_complete_new_current_geometry(tmp_path, monkeypatch):
    """Historical replay stays valid, while active quality progression rejects source drift."""
    root, plan, result = _run(tmp_path, monkeypatch)
    path, review = _review(root, plan, result)
    source = root / "analysis/scene_spec.json"
    payload = json.loads(source.read_text())
    payload["objects"][0]["geometry"]["dimensions"][0] *= 1.1
    write_json_atomic(source, payload)
    assert sanity.validate_geometry_multiview_visual_review(root, path) == review
    with pytest.raises(RuntimeError, match="stale or changed"):
        _completion(root, plan)


def test_supported_attachment_must_name_declared_partner(tmp_path, monkeypatch):
    """A vague connected assertion cannot substitute for the named required seat."""
    root, plan, result = _run(tmp_path, monkeypatch)
    path, review = _review(root, plan, result)
    payload = review.model_dump(mode="json")
    row = next(item for item in payload["detail_assessments"] if item["aspect"] == "attachment")
    row["attachment_reference_ids"] = []
    write_json_atomic(path, payload)
    with pytest.raises(ValueError, match="explicit seat partner"):
        sanity.validate_geometry_multiview_visual_review(root, path)
