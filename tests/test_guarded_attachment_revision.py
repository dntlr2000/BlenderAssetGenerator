"""Synthetic history-preserving attachment revisions never supply real production authority."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_solid_root_attachment_host as solid
import test_surface_attachment_host as legacy
from test_revision_payload_binding import _approve, _complete, _fixture, _write

from codex_blender_modeler import workspace
from codex_blender_modeler.attachment_runtime import REGISTRATION_PATH, selected_attachment
from codex_blender_modeler.blender_artifacts import deterministic_json_bytes, sha256_file
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.orchestration import paired_revision as paired
from codex_blender_modeler.orchestration import service
from codex_blender_modeler.packaging import attachment as host
from codex_blender_modeler.revision import preview_revision_plan


def _prepare(root, suffix="one"):
    """Stage one exact root-preserving geometry/model/intent candidate without canonical writes."""
    old = selected_attachment(root, root.name, root / paired.SCENE_PATH)
    document = json.loads((root / old["path"]).read_bytes())
    mesh = legacy.box(
        "relief", -0.1, 0.08, 0.2, 0.81 if suffix == "one" else 0.82, ("upper", "lower", "side")
    )
    geometry = legacy.put(root, f"geometry/relief_{suffix}.json", legacy.strict_payload(mesh, root))
    model = json.loads((root / paired.MODEL_PATH).read_bytes())
    model["global_notes"] = [f"Synthetic revision {suffix}; no production authority."]
    model_selection = legacy.put(root, f"analysis/model_{suffix}.json", model)
    _write(
        root / "analysis/revision_plan.json",
        {
            "schema_version": "0.1.0",
            "job_id": root.name,
            "base_spec_sha256": sha256_file(root / paired.SCENE_PATH),
            "request": "Synthetic fixture only",
            "operations": [
                {
                    "op": "set",
                    "target_type": "object",
                    "target_id": "relief",
                    "path": ["geometry", "path"],
                    "value": geometry["path"],
                    "reason": "Exact free-edge change preserves the root.",
                }
            ],
            "acceptance_criteria": ["Same fixed root and complete source proof"],
            "assumptions": [],
        },
    )
    candidate, _ = preview_revision_plan(
        scene_spec_path=root / paired.SCENE_PATH, plan_path=root / "analysis/revision_plan.json"
    )
    document["source_scene"]["sha256"] = hashlib.sha256(
        deterministic_json_bytes(candidate.model_dump(mode="json"))
    ).hexdigest()
    document["source_modeling_plan"]["sha256"] = model_selection["sha256"]
    document["source_geometry"] = [document["source_geometry"][0], geometry]
    selection = legacy.put(root, f"analysis/intent_{suffix}.json", document)
    return {
        "paired_modeling_plan_path": model_selection["path"],
        "paired_modeling_plan_sha256": model_selection["sha256"],
        "attachment_intent_path": selection["path"],
        "attachment_intent_sha256": selection["sha256"],
    }


def _job(tmp_path, monkeypatch):
    """Register an actual strict synthetic solid source, then mark it as previously built."""
    root, _ = _fixture(tmp_path, monkeypatch, parametric=True)
    _write(root / "analysis/reference_analysis.json", {"test_only": True})
    _write(root / "analysis/camera_solution.json", {"test_only": True})
    raw = json.loads((root / paired.SCENE_PATH).read_bytes())
    obj = raw["objects"][0]
    material = raw["materials"][0]
    material["id"] = "mat.shared"
    raw["materials"] = [material]
    objects, geometry = [], []
    for name, mesh in (
        ("owner", legacy.box("owner")),
        ("relief", legacy.box("relief", -0.1, 0.08, 0.2, 0.8, ("upper", "lower", "side"))),
    ):
        path = f"geometry/{name}.json"
        geometry.append(legacy.put(root, path, legacy.strict_payload(mesh, root)))
        current = copy.deepcopy(obj)
        current.update(
            id=name,
            material_id="mat.shared",
            geometry={"kind": "custom_mesh", "path": path},
            transform={"location": [0, 0, 0], "rotation_deg": [0, 0, 0], "scale": [1, 1, 1]},
            modifiers=[],
            generator=None,
            parent_id=None,
        )
        objects.append(current)
    raw["objects"] = objects
    scene = SceneSpec.model_validate(raw).model_dump(mode="json")
    _write(root / paired.SCENE_PATH, scene)
    _write(
        root / paired.MODEL_PATH,
        {
            "schema_version": "0.4.0",
            "job_id": root.name,
            "reference_analysis_path": "analysis/reference_analysis.json",
            "camera_solution_path": "analysis/camera_solution.json",
            "stage": "authored",
            "objects": [{"id": name, "label": name} for name in ("owner", "relief")],
            "assembly_consistency_policy": "legacy_unbound",
        },
    )
    reference = workspace.find_reference(root.name)
    doc = solid.document()
    doc.update(
        job_id=root.name,
        source_geometry=geometry,
        source_scene={"path": paired.SCENE_PATH, "sha256": sha256_file(root / paired.SCENE_PATH)},
        source_modeling_plan={
            "path": paired.MODEL_PATH,
            "sha256": sha256_file(root / paired.MODEL_PATH),
        },
        source_reference={
            "path": reference.relative_to(root).as_posix(),
            "sha256": sha256_file(reference),
        },
    )
    doc["source_camera_hypothesis"] = legacy.put(
        root,
        "analysis/camera_hypothesis.json",
        {
            "schema_version": "0.1.0",
            "contract_kind": "reference_camera_hypothesis",
            "job_id": root.name,
            "reference": doc["source_reference"],
            "camera": scene["camera"],
            "calibration_status": "hypothesis_not_unique_recovery",
            "assumptions": ["Synthetic only."],
        },
    )
    selection = legacy.put(root, "analysis/initial_solid_intent.json", doc)
    host.register_solid_root_attachment_intent(
        root.name, intent_path=selection["path"], intent_sha256=selection["sha256"]
    )
    legacy.put(root, "blender/scene.blend", {"synthetic_previously_built": True})
    return root


def _planned(root, options):
    """Plan through the public Standard opt-in without author completion or approval."""
    return service.plan_workflow(
        "Exact synthetic solid-root source revision",
        job_id=root.name,
        intent="revise_asset",
        revision_strategy="manual_guarded",
        **options,
    )


def _approved(root, options):
    """Issue explicitly synthetic test authority only after actual author-bound source proof."""
    return _approve(root, _complete(root, _planned(root, options)))


def test_exact_triple_preserves_initial_registration_and_supports_two_revisions(
    tmp_path, monkeypatch
):
    """Two successful revisions retain initial registration and validate archived predecessors."""
    root = _job(tmp_path, monkeypatch)
    registration = (root / REGISTRATION_PATH).read_bytes()
    initial_metadata = json.loads((root / "job.json").read_bytes())
    for suffix in ("one", "two"):
        options = _prepare(root, suffix)
        state = _approved(root, options)
        state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
        assert next(s.status for s in state.steps if s.step_id == "revision.apply") == "complete", (
            state.model_dump_json()
        )
        selected = selected_attachment(root, root.name, root / paired.SCENE_PATH)
        assert selected == {
            "path": options["attachment_intent_path"],
            "sha256": options["attachment_intent_sha256"],
        }
        receipt = paired.committed_receipt(root, state.workflow_id, require_current=True)
        assert receipt["schema_version"] == "0.2.0"
        assert set(receipt["after"]) == {paired.SCENE_PATH, paired.MODEL_PATH, "job.json"}
    metadata = json.loads((root / "job.json").read_bytes())
    assert metadata["attachment_intent"] == initial_metadata["attachment_intent"]
    assert (
        metadata["attachment_registration_sha256"]
        == initial_metadata["attachment_registration_sha256"]
    )
    assert (root / REGISTRATION_PATH).read_bytes() == registration
    with pytest.raises(ValueError, match="unbuilt"):
        host.register_solid_root_attachment_intent(
            root.name,
            intent_path=metadata["attachment_intent"]["path"],
            intent_sha256=metadata["attachment_intent"]["sha256"],
        )


@pytest.mark.parametrize(
    "checkpoint",
    [
        "after_intent",
        "after_scene",
        "after_model",
        "after_job",
        "after_validation",
        "before_receipt",
    ],
)
def test_partial_triples_fail_closed_and_restore_exactly(tmp_path, monkeypatch, checkpoint):
    """Every consumed partial triple blocks direct readers until exact explicit rollback."""
    root = _job(tmp_path, monkeypatch)
    options = _prepare(root)
    state = _approved(root, options)
    before = {
        path: (root / path).read_bytes()
        for path in (paired.SCENE_PATH, paired.MODEL_PATH, "job.json")
    }

    def fail(name):
        """Interrupt one exact publication boundary in a disposable synthetic job."""
        if name == checkpoint:
            raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(paired, "_checkpoint", fail)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert next(s.status for s in state.steps if s.step_id == "revision.apply") == "failed"
    with pytest.raises(ValueError, match="incomplete"):
        selected_attachment(root, root.name, root / paired.SCENE_PATH)
    monkeypatch.setattr(paired, "_checkpoint", lambda _name: None)
    intent = paired.transaction_path(root, state.workflow_id, "intent.json")
    result = service.recover_paired_workflow_revision(
        root.name, state.workflow_id, intent_sha256=sha256_file(intent)
    )
    assert result["status"] == "rolled_back"
    assert all((root / path).read_bytes() == content for path, content in before.items())
    selected_attachment(root, root.name, root / paired.SCENE_PATH)


@pytest.mark.parametrize(
    "mutation",
    [
        "radius",
        "bounds",
        "domain",
        "camera",
        "reference",
        "minimum",
        "semantics",
        "description",
        "extra",
    ],
)
def test_rebinding_does_not_change_any_immutable_intent(tmp_path, monkeypatch, mutation):
    """Root, semantic, domain, rationale and immutable source changes fail before approval."""
    root = _job(tmp_path, monkeypatch)
    options = _prepare(root)
    path = root / options["attachment_intent_path"]
    doc = json.loads(path.read_bytes())
    if mutation == "radius":
        doc["entries"][0]["radius_m"] = 0.019
    elif mutation == "bounds":
        doc["entries"][0]["root_bounds"][0][0] = 0.34
    elif mutation == "domain":
        doc["contract_kind"] = "surface_attachment_intent"
    elif mutation == "camera":
        doc["source_camera_hypothesis"]["sha256"] = "0" * 64
    elif mutation == "reference":
        doc["source_reference"]["sha256"] = "0" * 64
    elif mutation == "minimum":
        doc["minimum_radius_m"] = 0.009
    elif mutation == "semantics":
        doc["required_semantics"].reverse()
    elif mutation == "description":
        doc["entries"][0]["joint_description"] += " changed"
    else:
        doc["unknown"] = True
    _write(path, doc)
    options["attachment_intent_sha256"] = sha256_file(path)
    with pytest.raises(ValueError):
        _planned(root, options)
    assert not list((root / "production/surface_attachment/revisions").glob("*/revision.json"))


@pytest.mark.parametrize(
    "mutation",
    [
        "candidate_bytes",
        "geometry_bytes",
        "nested_bytes",
        "old_intent",
        "metadata",
        "foreign_job",
        "omitted_geometry",
        "extra_geometry",
    ],
)
def test_stale_or_incomplete_sources_cannot_complete_authoring(tmp_path, monkeypatch, mutation):
    """Changed byte closures and missing/extra or foreign sources never reach approval."""
    root = _job(tmp_path, monkeypatch)
    options = _prepare(root)
    state = _planned(root, options)
    if mutation in {"foreign_job", "omitted_geometry", "extra_geometry"}:
        path = root / options["attachment_intent_path"]
        document = json.loads(path.read_bytes())
        if mutation == "foreign_job":
            document["job_id"] = "foreign"
        elif mutation == "omitted_geometry":
            document["source_geometry"].pop()
        else:
            document["source_geometry"].append(document["source_geometry"][0])
        _write(path, document)
    else:
        relative = {
            "candidate_bytes": options["attachment_intent_path"],
            "geometry_bytes": "geometry/relief_one.json",
            "nested_bytes": "evidence/source.json",
            "old_intent": "analysis/initial_solid_intent.json",
            "metadata": "job.json",
        }[mutation]
        path = root / relative
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises((ValueError, RuntimeError)):
        _complete(root, state)
    assert not (
        root / "workflows" / state.workflow_id / "approvals/revision.approval.json"
    ).exists()


@pytest.mark.parametrize(
    "tamper",
    [
        "record",
        "approval",
        "receipt",
        "archive",
        "metadata",
        "missing_pointer",
        "host_input",
        "snapshot",
    ],
)
def test_committed_tampering_fails_direct_and_blender_safe_readers(tmp_path, monkeypatch, tamper):
    """Original approval, immutable record, archives, snapshots and exact metadata remain pinned."""
    from codex_blender_modeler.paired_revision_runtime import assert_no_pending_pair

    root = _job(tmp_path, monkeypatch)
    state = _approved(root, _prepare(root))
    service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    prefix = root / "workflows" / state.workflow_id
    paths = {
        "record": root
        / "production/surface_attachment/revisions"
        / state.workflow_id
        / "revision.json",
        "approval": prefix / "approvals/revision.approval.json",
        "receipt": prefix / "paired_revision/receipt.json",
        "archive": prefix / "paired_revision/job.before.json",
        "metadata": root / "job.json",
    }
    if tamper in paths:
        path = paths[tamper]
        path.write_bytes(path.read_bytes() + b" ")
    elif tamper == "missing_pointer":
        metadata = json.loads((root / "job.json").read_bytes())
        metadata.pop("attachment_revision")
        _write(root / "job.json", metadata)
    elif tamper == "host_input":
        path = next((prefix / "attempts/revision.apply").glob("*.json"))
        attempt = json.loads(path.read_bytes())
        attempt["input_fingerprint"] = "0" * 64
        _write(path, attempt)
    else:
        plan = json.loads((prefix / "plan.json").read_bytes())
        step = next(item for item in plan["steps"] if item["step_id"] == "revision.apply")
        output = next(
            item for item in step["outputs"] if item["artifact_id"] == "revision.job_metadata"
        )
        path = root / output["path"]
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        selected_attachment(root, root.name, root / paired.SCENE_PATH)
    if tamper not in {"metadata", "missing_pointer"}:
        with pytest.raises(ValueError):
            assert_no_pending_pair(root)


def test_restoring_old_complete_tip_is_not_authorized_rollback(tmp_path, monkeypatch):
    """An older pointer with matching sources cannot hide a committed successor."""
    root = _job(tmp_path, monkeypatch)
    first = _approved(root, _prepare(root))
    service.resume_workflow(root.name, first.workflow_id, max_host_steps=1)
    older = {
        path: (root / path).read_bytes()
        for path in (paired.SCENE_PATH, paired.MODEL_PATH, "job.json")
    }
    second = _approved(root, _prepare(root, "two"))
    service.resume_workflow(root.name, second.workflow_id, max_host_steps=1)
    for path, content in older.items():
        (root / path).write_bytes(content)
    with pytest.raises(ValueError, match="successor|fork"):
        selected_attachment(root, root.name, root / paired.SCENE_PATH)


@pytest.mark.parametrize(
    "checkpoint",
    ["recovery_started", "recovery_after_scene", "recovery_after_model", "recovery_after_job"],
)
def test_triple_rollback_interruptions_resume_without_replay(tmp_path, monkeypatch, checkpoint):
    """Each exact restoration stage can resume while consumed approval stays consumed."""
    root = _job(tmp_path, monkeypatch)
    state = _approved(root, _prepare(root))
    before = {
        path: (root / path).read_bytes()
        for path in (paired.SCENE_PATH, paired.MODEL_PATH, "job.json")
    }

    def fail_apply(name):
        """Leave all three files changed without a commit receipt."""
        if name == "after_job":
            raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(paired, "_checkpoint", fail_apply)
    service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    intent_hash = sha256_file(paired.transaction_path(root, state.workflow_id, "intent.json"))

    def fail_recovery(name):
        """Leave one explicit recovery boundary incomplete."""
        if name == checkpoint:
            raise RuntimeError("synthetic rollback interruption")

    monkeypatch.setattr(paired, "_checkpoint", fail_recovery)
    with pytest.raises(RuntimeError):
        service.recover_paired_workflow_revision(
            root.name, state.workflow_id, intent_sha256=intent_hash
        )
    monkeypatch.setattr(paired, "_checkpoint", lambda _name: None)
    service.recover_paired_workflow_revision(
        root.name, state.workflow_id, intent_sha256=intent_hash
    )
    assert all((root / path).read_bytes() == content for path, content in before.items())
    with pytest.raises(FileExistsError):
        service.recover_paired_workflow_revision(
            root.name, state.workflow_id, intent_sha256=intent_hash
        )


def test_late_metadata_edit_survives_failed_transaction_recovery(tmp_path, monkeypatch):
    """Recovery never replaces a concurrent job metadata edit with archived own bytes."""
    root = _job(tmp_path, monkeypatch)
    state = _approved(root, _prepare(root))

    def fail(name):
        """Interrupt immediately after the pointer changed."""
        if name == "after_job":
            raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(paired, "_checkpoint", fail)
    service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    metadata = root / "job.json"
    edited = metadata.read_bytes() + b" "
    metadata.write_bytes(edited)
    monkeypatch.setattr(paired, "_checkpoint", lambda _name: None)
    with pytest.raises(ValueError, match="concurrent"):
        service.recover_paired_workflow_revision(
            root.name,
            state.workflow_id,
            intent_sha256=sha256_file(
                paired.transaction_path(root, state.workflow_id, "intent.json")
            ),
        )
    assert metadata.read_bytes() == edited


def test_committed_triple_finalizes_without_reapplication(tmp_path, monkeypatch):
    """Lost host completion can finalize exact metadata snapshots without a second apply."""
    root = _job(tmp_path, monkeypatch)
    state = _approved(root, _prepare(root))

    def fail(name):
        """Stop after the immutable commit receipt."""
        if name == "after_receipt":
            raise RuntimeError("synthetic postcommit interruption")

    monkeypatch.setattr(paired, "_checkpoint", fail)
    service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    monkeypatch.setattr(paired, "_cas", lambda *args: pytest.fail("reapplied committed sources"))
    result = service.recover_paired_workflow_revision(
        root.name,
        state.workflow_id,
        intent_sha256=sha256_file(paired.transaction_path(root, state.workflow_id, "intent.json")),
    )
    assert result["status"] == "committed_finalized"
    selected_attachment(root, root.name, root / paired.SCENE_PATH)


def test_triple_provenance_runs_without_site_packages(tmp_path, monkeypatch):
    """Blender-safe selection and provenance import no Pydantic or orchestration code."""
    root = _job(tmp_path, monkeypatch)
    state = _approved(root, _prepare(root))
    service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    program = """
import importlib.util, json, sys
from pathlib import Path
assert importlib.util.find_spec('pydantic') is None
from codex_blender_modeler.paired_revision_runtime import assert_no_pending_pair
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.attachment_runtime import selected_attachment
root = Path(sys.argv[1])
assert_no_pending_pair(root)
selected_attachment(root, root.name, root / 'analysis/scene_spec.json')
value = collect_build_provenance(
    root, root.name, validate_contracts=False, material_plan_mode='scene_spec_only')
assert 'attachment_revision' in value
assert 'pydantic' not in sys.modules
assert 'codex_blender_modeler.orchestration' not in sys.modules
print(json.dumps({'ok': True}))
"""
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-S", "-c", program, str(root)],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"]


def test_binary64_success_does_not_replace_float32_root_proof(tmp_path, monkeypatch):
    """A source margin lost through binary32 rounding fails before an approval can exist."""
    from codex_blender_modeler.structural_geometry.solid_root_ball import (
        Budget,
        certify_ball,
        prepare_solid,
    )

    root = _job(tmp_path, monkeypatch)
    options = _prepare(root)
    owner = legacy.box("owner", back=0.0600000002)
    budget = Budget()
    solid_source = prepare_solid(owner.vertices, owner.faces, budget)
    certify_ball(
        solid_source, [0.5, 0.04, 0.5], 0.02, [[0.35, 0.005, 0.35], [0.65, 0.075, 0.65]], budget
    )
    geometry = legacy.put(root, "geometry/owner_rounding.json", legacy.strict_payload(owner, root))
    plan_path = root / "analysis/revision_plan.json"
    plan = json.loads(plan_path.read_bytes())
    plan["operations"].append(
        {
            "op": "set",
            "target_type": "object",
            "target_id": "owner",
            "path": ["geometry", "path"],
            "value": geometry["path"],
            "reason": "Synthetic rounding-only negative.",
        }
    )
    _write(plan_path, plan)
    candidate, _ = preview_revision_plan(
        scene_spec_path=root / paired.SCENE_PATH, plan_path=plan_path
    )
    intent_path = root / options["attachment_intent_path"]
    intent = json.loads(intent_path.read_bytes())
    intent["source_geometry"][0] = geometry
    intent["source_scene"]["sha256"] = hashlib.sha256(
        deterministic_json_bytes(candidate.model_dump(mode="json"))
    ).hexdigest()
    _write(intent_path, intent)
    options["attachment_intent_sha256"] = sha256_file(intent_path)
    state = _planned(root, options)
    with pytest.raises(ValueError, match="ball|radius|boundary"):
        _complete(root, state)
    assert not (
        root / "workflows" / state.workflow_id / "approvals/revision.approval.json"
    ).exists()


def test_linked_candidate_cannot_enter_revision_authority(tmp_path, monkeypatch):
    """An explicit path does not authorize following a link into unrelated source bytes."""
    root = _job(tmp_path, monkeypatch)
    options = _prepare(root)
    path = root / "analysis/linked_intent.json"
    try:
        path.symlink_to(root / options["attachment_intent_path"])
    except OSError:
        pytest.skip("Platform cannot create a symlink fixture")
    options["attachment_intent_path"] = path.relative_to(root).as_posix()
    with pytest.raises(ValueError, match="link"):
        _planned(root, options)


@pytest.mark.parametrize(
    "relative",
    [
        "geometry/relief_one.json",
        "analysis/camera_hypothesis.json",
        "analysis/reference_analysis.json",
        "analysis/camera_solution.json",
    ],
)
def test_change_during_final_proof_prevents_commit(tmp_path, monkeypatch, relative):
    """Expensive source proofs cannot leave an unchecked window before the commit receipt."""
    from codex_blender_modeler.orchestration import attachment_revision

    root = _job(tmp_path, monkeypatch)
    state = _approved(root, _prepare(root))
    original = attachment_revision._proofs

    def mutate_after_proof(*args, **kwargs):
        """Simulate an external geometry edit after both source and Float32 calculations."""
        result = original(*args, **kwargs)
        metadata = json.loads((root / "job.json").read_bytes())
        if "attachment_revision" in metadata:
            path = root / relative
            path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(attachment_revision, "_proofs", mutate_after_proof)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert next(s.status for s in state.steps if s.step_id == "revision.apply") == "failed"
    assert not paired.transaction_path(root, state.workflow_id, "receipt.json").exists()
    with pytest.raises(ValueError, match="incomplete"):
        selected_attachment(root, root.name, root / paired.SCENE_PATH)


@pytest.mark.parametrize(
    "relative",
    [
        "geometry/relief.json",
        "geometry/relief_one.json",
        "evidence/source.json",
    ],
)
def test_every_historical_geometry_closure_remains_exact(tmp_path, monkeypatch, relative):
    """A later valid revision cannot hide altered initial or predecessor geometry dependencies."""
    from codex_blender_modeler.build_provenance import collect_build_provenance
    from codex_blender_modeler.paired_revision_runtime import assert_no_pending_pair

    root = _job(tmp_path, monkeypatch)
    first = _approved(root, _prepare(root))
    service.resume_workflow(root.name, first.workflow_id, max_host_steps=1)
    second = _approved(root, _prepare(root, "two"))
    service.resume_workflow(root.name, second.workflow_id, max_host_steps=1)
    path = root / relative
    path.write_bytes(path.read_bytes() + b" ")
    for reader in (
        lambda: selected_attachment(root, root.name, root / paired.SCENE_PATH),
        lambda: assert_no_pending_pair(root),
        lambda: paired.assert_no_pending_pair(root),
        lambda: collect_build_provenance(root, root.name, validate_contracts=False),
    ):
        with pytest.raises(ValueError):
            reader()


@pytest.mark.parametrize("stage", ["planning", "author", "apply"])
def test_prospective_chain_capacity_fails_before_new_commit(tmp_path, monkeypatch, stage):
    """The shared reader bound must also reject a prospective unrepresentable successor."""
    from codex_blender_modeler import attachment_revision_runtime

    root = _job(tmp_path, monkeypatch)
    first = _approved(root, _prepare(root))
    service.resume_workflow(root.name, first.workflow_id, max_host_steps=1)
    options = _prepare(root, "two")
    if stage == "planning":
        monkeypatch.setattr(attachment_revision_runtime, "MAX_REVISIONS", 1)
        with pytest.raises(ValueError, match="capacity"):
            _planned(root, options)
        return
    state = _planned(root, options)
    if stage == "apply":
        state = _approve(root, _complete(root, state))
    monkeypatch.setattr(attachment_revision_runtime, "MAX_REVISIONS", 1)
    before = {
        path: (root / path).read_bytes()
        for path in (paired.SCENE_PATH, paired.MODEL_PATH, "job.json")
    }
    if stage == "author":
        with pytest.raises(ValueError, match="capacity"):
            _complete(root, state)
    else:
        service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert all((root / path).read_bytes() == content for path, content in before.items())
    assert not paired.transaction_path(root, state.workflow_id, "receipt.json").exists()


def test_runtime_caps_journal_inventory_before_parsing(tmp_path, monkeypatch):
    """Excessive transaction inventory fails before any candidate journal is parsed."""
    from codex_blender_modeler import paired_revision_runtime

    root = _job(tmp_path, monkeypatch)
    original = Path.glob

    def crowded(path, pattern):
        """Offer an excessive synthetic inventory without allocating real journal contents."""
        if path == root / "workflows" and pattern == "*/paired_revision/intent.json":
            return iter(path / f"wf-{index}/paired_revision/intent.json" for index in range(4097))
        return original(path, pattern)

    monkeypatch.setattr(Path, "glob", crowded)
    with pytest.raises(ValueError, match="inventory"):
        paired_revision_runtime.assert_no_pending_pair(root)


def test_runtime_caps_transaction_bytes_before_json_loading(tmp_path, monkeypatch):
    """An oversized fixed journal cannot allocate unbounded bytes before schema checking."""
    from codex_blender_modeler import paired_revision_runtime

    root = _job(tmp_path, monkeypatch)
    path = root / "workflows/wf-oversize/paired_revision/intent.json"
    path.parent.mkdir(parents=True)
    with path.open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="byte limit"):
        paired_revision_runtime._load_intent(root, "wf-oversize")
