"""Standard revision payload bindings are technical guards, never production approval."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from test_aq_v02_geometry import _payload_dict
from test_standard_custom_mesh import _fixture_payload

from codex_blender_modeler import workspace
from codex_blender_modeler.blender_artifacts import sha256_file, stable_json_digest
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.orchestration import service
from codex_blender_modeler.orchestration.revision_payloads import (
    BINDING_PARAMETER,
    binding_path,
    create_binding,
    geometry_dependency_hashes,
    validate_binding,
)

ROOT = Path(__file__).parents[1]


def _write(path: Path, payload: object) -> None:
    """Write one test-owned JSON fixture without using protected user evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path, monkeypatch, *, parametric: bool = False):
    """Create one fresh Standard manual workflow and unapproved exact revision candidate."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (16, 16), "gray").save(reference)
    workspace.create_job("guard_asset", reference, "concept", [])
    root = workspace.job_dir("guard_asset")
    raw = json.loads((ROOT / "examples/geometry_showcase/scene_spec.seed.json").read_text())
    raw["job_id"] = root.name
    raw["objects"] = [raw["objects"][0]]
    raw["objects"][0]["id"] = "asset.cube"
    if not parametric:
        raw["objects"][0]["geometry"] = {"kind": "custom_mesh", "path": "geometry/old.json"}
    _write(root / "analysis/scene_spec.json", raw)
    _write(
        root / "analysis/modeling_plan.json",
        {
            "schema_version": "0.4.0",
            "job_id": root.name,
            "reference_analysis_path": "analysis/reference_analysis.json",
            "camera_solution_path": "analysis/camera_solution.json",
            "stage": "authored",
            "objects": [{"id": "asset.cube", "label": "cube"}],
            "assembly_consistency_policy": "legacy_unbound",
        },
    )
    payload = _payload_dict(root, source_relative_path="geometry/source.json")
    _write(root / "geometry/new.json", payload)
    operation = {
        "op": "multiply" if parametric else "set",
        "target_type": "object",
        "target_id": "asset.cube",
        "path": ["transform", "scale", 2] if parametric else ["geometry", "path"],
        "value": 1.2 if parametric else "geometry/new.json",
        "reason": "Exact fixture revision",
    }
    _write(
        root / "analysis/revision_plan.json",
        {
            "schema_version": "0.1.0",
            "job_id": root.name,
            "base_spec_sha256": sha256_file(root / "analysis/scene_spec.json"),
            "request": "Make the approved exact change",
            "operations": [operation],
            "acceptance_criteria": ["Only the requested path changes"],
            "assumptions": [],
        },
    )
    state = service.plan_workflow(
        "Revise the exact geometry payload.",
        job_id=root.name,
        intent="revise_asset",
        revision_strategy="manual_guarded",
    )
    return root, state


def _complete(root: Path, state):
    """Complete only the test fixture's author step through the public host surface."""

    return service.complete_workflow_step(
        root.name,
        state.workflow_id,
        "revision.author",
        input_fingerprint=next(
            s.input_fingerprint for s in state.steps if s.step_id == "revision.author"
        ),
        note="Test-only authored candidate; this is not production approval.",
    )


def _approve(root: Path, state):
    """Issue explicit test-only gate authority in a disposable fixture workspace."""

    return service.approve_workflow_gate(
        root.name,
        state.workflow_id,
        "revision.approval",
        artifact_fingerprint=next(
            s.input_fingerprint for s in state.steps if s.step_id == "revision.approval"
        ),
        approval_note="Synthetic test fixture only, never asset acceptance.",
    )


@pytest.mark.parametrize("parametric", [False, True])
def test_new_manual_revision_freezes_payload_bytes_and_preserves_cas_history(
    tmp_path, monkeypatch, parametric
):
    """Both payload swaps and ordinary parametric revisions retain exact canonical CAS."""

    root, state = _fixture(tmp_path, monkeypatch, parametric=parametric)
    before = (root / "analysis/scene_spec.json").read_bytes()
    state = _complete(root, state)
    manifest = validate_binding(root, state.workflow_id, require_current_candidate=True)
    assert (root / "analysis/scene_spec.json").read_bytes() == before
    assert manifest["geometry_dependencies"] == (
        {}
        if parametric
        else {
            "geometry/new.json": sha256_file(root / "geometry/new.json"),
            "geometry/source.json": sha256_file(root / "geometry/source.json"),
        }
    )
    state = _approve(root, state)
    approval_path = root / "workflows" / state.workflow_id / "approvals/revision.approval.json"
    approval = approval_path.read_bytes()
    applied = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert next(s.status for s in applied.steps if s.step_id == "revision.apply") == "complete"
    assert any(p.read_bytes() == before for p in (root / "history").glob("*scene_spec.json"))
    # Completed exact receipt history does not change when later work changes live payload bytes.
    (root / "geometry/source.json").write_bytes(b"later job work")
    replay = service.reconcile_workflow(root.name, state.workflow_id)
    assert next(s.status for s in replay.steps if s.step_id == "revision.apply") == "complete"
    assert approval_path.read_bytes() == approval


@pytest.mark.parametrize("mutation", ["changed", "missing", "nested", "baseline", "plan"])
def test_mutation_after_approval_blocks_pending_apply(tmp_path, monkeypatch, mutation):
    """Changed direct/nested bytes, missing files and stale plan/baseline cannot promote."""

    root, state = _fixture(tmp_path, monkeypatch)
    state = _approve(root, _complete(root, state))
    original = (root / "analysis/scene_spec.json").read_bytes()
    target = (
        root
        / {
            "changed": "geometry/new.json",
            "missing": "geometry/new.json",
            "nested": "geometry/source.json",
            "baseline": "analysis/scene_spec.json",
            "plan": "analysis/revision_plan.json",
        }[mutation]
    )
    if mutation == "missing":
        target.unlink()
    else:
        target.write_bytes(target.read_bytes() + b" ")
    expected = (root / "analysis/scene_spec.json").read_bytes()
    result = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert result.status == "blocked"
    assert (root / "analysis/scene_spec.json").read_bytes() == expected
    assert not list((root / "history").glob("*scene_spec.json"))
    if mutation != "baseline":
        assert expected == original


@pytest.mark.parametrize("mutation", ["missing", "extra", "hash", "candidate"])
def test_tampered_binding_cannot_be_completed_or_approved(tmp_path, monkeypatch, mutation):
    """The exact candidate closure rejects absent, additional, or altered declarations."""

    root, state = _fixture(tmp_path, monkeypatch)
    state = _complete(root, state)
    path = binding_path(root, state.workflow_id)
    payload = json.loads(path.read_bytes())
    if mutation == "missing":
        payload["geometry_dependencies"].pop("geometry/source.json")
    elif mutation == "extra":
        payload["geometry_dependencies"]["geometry/extra.json"] = "a" * 64
    elif mutation == "candidate":
        payload["candidate_scene_spec"]["objects"][0]["geometry"]["path"] = "geometry/source.json"
    else:
        payload["geometry_dependencies"]["geometry/new.json"] = "b" * 64
    _write(path, payload)
    with pytest.raises((ValueError, RuntimeError)):
        validate_binding(root, state.workflow_id, require_current_candidate=True)
    with pytest.raises(RuntimeError, match="not waiting"):
        _approve(root, state)
    assert not (path.parents[1] / "approvals/revision.approval.json").exists()


def test_live_mutation_before_approval_never_creates_approval(tmp_path, monkeypatch):
    """A technical dependency failure cannot produce an approval for invalid current bytes."""

    root, state = _fixture(tmp_path, monkeypatch)
    state = _complete(root, state)
    (root / "geometry/source.json").write_bytes(b"changed")
    blocked = service.reconcile_workflow(root.name, state.workflow_id)
    assert blocked.status == "blocked"
    assert blocked.waiting_gate is None
    with pytest.raises(RuntimeError, match="not waiting"):
        _approve(root, state)
    assert not (root / "workflows" / state.workflow_id / "approvals").exists()


@pytest.mark.parametrize("stage", ["candidate", "archive", "replacement_copy"])
def test_under_lock_dependency_mutation_never_replaces_canonical(tmp_path, monkeypatch, stage):
    """Revalidate after candidate generation and again after final CAS archive/copy work."""

    root, state = _fixture(tmp_path, monkeypatch)
    state = _approve(root, _complete(root, state))
    before = (root / "analysis/scene_spec.json").read_bytes()
    real_apply = service.apply_revision_plan
    real_copy = workspace.shutil.copy2

    def mutate():
        """Simulate an unauthorized external writer while the host lock is held."""
        assert workspace.current_job_write_lock_owner(root.name) == state.workflow_id
        (root / "geometry/source.json").write_bytes(b"changed under lock")

    def apply(**kwargs):
        """Mutate only after a valid candidate has been written to its staging path."""
        result = real_apply(**kwargs)
        mutate()
        return result

    def copy(source, destination, *args, **kwargs):
        """Mutate only at the selected archive or final replacement-copy boundary."""
        result = real_copy(source, destination, *args, **kwargs)
        if (stage == "archive" and Path(destination).parent.name == "history") or (
            stage == "replacement_copy" and Path(destination).name.startswith(".scene_spec.replace")
        ):
            mutate()
        return result

    if stage == "candidate":
        monkeypatch.setattr(service, "apply_revision_plan", apply)
    else:
        monkeypatch.setattr(workspace.shutil, "copy2", copy)
    result = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert result.status == "blocked"
    assert (root / "analysis/scene_spec.json").read_bytes() == before


@pytest.mark.parametrize(
    "path",
    ["../other/mesh.json", "/tmp/foreign.json", "geometry/../new.json", "geometry\\new.json"],
)
def test_geometry_dependency_paths_fail_closed(tmp_path, monkeypatch, path):
    """Reject traversal, absolute paths and alternate separators before reading payloads."""

    root, _ = _fixture(tmp_path, monkeypatch)
    plan = json.loads((root / "analysis/revision_plan.json").read_bytes())
    plan["operations"][0]["value"] = path
    _write(root / "analysis/revision_plan.json", plan)
    with pytest.raises((ValueError, RuntimeError)):
        create_binding(root)


@pytest.mark.parametrize("link_kind", ["file", "parent", "junction"])
def test_dependency_links_and_junctions_fail_closed(tmp_path, monkeypatch, link_kind):
    """Reject links and reparse metadata with equivalent lexical and native fixture paths."""

    root, _ = _fixture(tmp_path, monkeypatch)
    path = root / "geometry/new.json"
    if link_kind == "file":
        path.rename(root / "geometry/original.json")
        path.symlink_to(root / "geometry/original.json")
    elif link_kind == "parent":
        (root / "geometry").rename(root / "original_geometry")
        (root / "geometry").symlink_to(root / "original_geometry", target_is_directory=True)
    else:
        import codex_blender_modeler.production.validation as validation

        real_lstat = validation.os.lstat

        def lstat(value, *args, **kwargs):
            """Model the reparse bit after normalizing the selected dependency's native path."""
            if validation.native_io_path(Path(value)) == validation.native_io_path(path):
                return SimpleNamespace(
                    st_mode=real_lstat(value).st_mode,
                    st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
                )
            return real_lstat(value, *args, **kwargs)

        monkeypatch.setattr(validation.os, "lstat", lstat)
    with pytest.raises(ValueError, match="symlink or junction"):
        create_binding(root)


def test_nested_payload_closure_and_binary_leaf(tmp_path, monkeypatch):
    """Recursively validate nested MeshPayload sources while accepting exact binary leaves."""

    root, _ = _fixture(tmp_path, monkeypatch)
    (root / "geometry/source.json").write_bytes(b"\x00\xffbinary source")
    inner = _payload_dict(root, source_relative_path="geometry/source.json")
    _write(root / "geometry/inner.json", inner)
    outer = _payload_dict(root, source_relative_path="geometry/inner.json")
    _write(root / "geometry/new.json", outer)
    binding = create_binding(root)
    assert set(binding["geometry_dependencies"]) == {
        "geometry/new.json",
        "geometry/inner.json",
        "geometry/source.json",
    }
    (root / "geometry/source.json").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="nested"):
        create_binding(root)


def test_standard_payload_sources_and_foreign_job(tmp_path, monkeypatch):
    """Standard UV payloads bind source SceneSpec/Blend and reject foreign job identities."""

    root, _ = _fixture(tmp_path, monkeypatch)
    payload, _ = _fixture_payload(root)
    payload["job_id"] = root.name
    payload["object_id"] = "asset.cube"
    source_path = root / payload["source_scene_spec_path"]
    source = json.loads(source_path.read_bytes())
    source["job_id"] = root.name
    source["objects"][0]["id"] = "asset.cube"
    _write(source_path, source)
    payload["source_scene_spec_sha256"] = sha256_file(source_path)
    _write(root / "geometry/new.json", payload)
    binding = create_binding(root)
    assert set(binding["geometry_dependencies"]) == {
        "geometry/new.json",
        "history/base_scene_spec.json",
        "history/base_scene.blend",
    }
    payload["job_id"] = "other_job"
    _write(root / "geometry/new.json", payload)
    with pytest.raises(ValueError, match="foreign job"):
        create_binding(root)


def test_legacy_manual_workflow_retains_original_unbound_behavior(tmp_path, monkeypatch):
    """An old plan without the opt-in keeps its original contract and emits no binding."""

    root, state = _fixture(tmp_path, monkeypatch, parametric=True)
    path = root / "workflows" / state.workflow_id / "plan.json"
    raw = json.loads(path.read_bytes())
    for step in raw["steps"]:
        step["parameters"].pop(BINDING_PARAMETER, None)
        step["outputs"] = [
            o for o in step["outputs"] if o["artifact_id"] != "revision.payload_binding"
        ]
    _write(path, raw)
    state = service.reconcile_workflow(root.name, state.workflow_id)
    state = _approve(root, _complete(root, state))
    applied = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert next(s.status for s in applied.steps if s.step_id == "revision.apply") == "complete"
    assert not binding_path(root, state.workflow_id).exists()


def test_shared_payload_cannot_hide_wrong_semantic_identity(tmp_path, monkeypatch):
    """Every object association is checked even when a matching object visited the path first."""

    root, _ = _fixture(tmp_path, monkeypatch)
    binding = create_binding(root)
    raw = binding["candidate_scene_spec"]
    other = json.loads(json.dumps(raw["objects"][0]))
    other["id"] = "asset.wrong"
    raw["objects"].insert(0, other)
    with pytest.raises(ValueError, match="identity"):
        geometry_dependency_hashes(root, SceneSpec.model_validate(raw))


def test_nonmesh_source_map_still_recurses(tmp_path, monkeypatch):
    """A declared source-map node cannot hide transitive dependencies behind non-mesh JSON."""

    root, _ = _fixture(tmp_path, monkeypatch)
    (root / "geometry/leaf.bin").write_bytes(b"immutable source")
    sources = [{"path": "geometry/leaf.bin", "sha256": sha256_file(root / "geometry/leaf.bin")}]
    _write(
        root / "geometry/source.json",
        {
            "source_hashes": sources,
            "source_fingerprint_sha256": stable_json_digest(sources),
        },
    )
    _write(
        root / "geometry/new.json", _payload_dict(root, source_relative_path="geometry/source.json")
    )
    assert "geometry/leaf.bin" in create_binding(root)["geometry_dependencies"]
    (root / "geometry/leaf.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="nested"):
        create_binding(root)


def test_canonical_destination_cannot_be_a_payload_dependency(tmp_path, monkeypatch):
    """Reject a source that would become stale immediately when the approved revision is applied."""

    root, _ = _fixture(tmp_path, monkeypatch)
    _write(
        root / "geometry/new.json",
        _payload_dict(root, source_relative_path="analysis/scene_spec.json"),
    )
    with pytest.raises(ValueError, match="frozen sources"):
        create_binding(root)


@pytest.mark.parametrize(
    "mutation", ["canonical", "temporary", "approval", "binding", "modeling_plan"]
)
def test_final_dependency_scan_cannot_widen_cas_window(tmp_path, monkeypatch, mutation):
    """Recheck canonical/temp/authority after a mutation during final dependency validation."""

    import codex_blender_modeler.orchestration.revision_payloads as payloads

    root, state = _fixture(tmp_path, monkeypatch)
    state = _approve(root, _complete(root, state))
    before = (root / "analysis/scene_spec.json").read_bytes()
    real_copy = workspace.shutil.copy2
    real_collect = payloads.geometry_dependency_hashes
    final_temporary = None
    mutated = False

    def copy(source, destination, *args, **kwargs):
        """Remember only the final CAS temporary file, leaving immutable archive creation intact."""
        nonlocal final_temporary
        result = real_copy(source, destination, *args, **kwargs)
        if Path(destination).name.startswith(".scene_spec.replace"):
            final_temporary = Path(destination)
        return result

    def collect(job_root, scene):
        """Inject one exact mutation only after final copying and dependency enumeration."""
        nonlocal mutated
        result = real_collect(job_root, scene)
        if final_temporary is not None and not mutated:
            mutated = True
            target = {
                "canonical": root / "analysis/scene_spec.json",
                "temporary": final_temporary,
                "approval": root
                / "workflows"
                / state.workflow_id
                / "approvals/revision.approval.json",
                "binding": binding_path(root, state.workflow_id),
                "modeling_plan": root / "analysis/modeling_plan.json",
            }[mutation]
            target.write_bytes(target.read_bytes() + b" ")
        return result

    monkeypatch.setattr(workspace.shutil, "copy2", copy)
    monkeypatch.setattr(payloads, "geometry_dependency_hashes", collect)
    result = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert result.status == "blocked"
    assert (root / "analysis/scene_spec.json").read_bytes() == (
        before + b" " if mutation == "canonical" else before
    )


def test_preexisting_diff_and_changed_output_cannot_fake_apply_completion(tmp_path, monkeypatch):
    """Only exact successful attempt snapshots can establish completion for a new guarded apply."""

    root, state = _fixture(tmp_path, monkeypatch)
    _write(root / "reports/revision_diff.json", {"ok": True, "prior_revision": True})
    state = _approve(root, _complete(root, state))
    path = root / "analysis/scene_spec.json"
    path.write_bytes(path.read_bytes() + b" ")
    result = service.reconcile_workflow(root.name, state.workflow_id)
    assert next(s.status for s in result.steps if s.step_id == "revision.apply") == "blocked"
    assert not list((root / "workflows" / state.workflow_id / "attempts").glob("**/*.json"))


def test_stale_approval_fingerprint_is_rejected(tmp_path, monkeypatch):
    """A prior candidate's displayed fingerprint cannot approve altered immutable binding bytes."""

    root, state = _fixture(tmp_path, monkeypatch)
    state = _complete(root, state)
    path = binding_path(root, state.workflow_id)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(RuntimeError, match="not waiting"):
        _approve(root, state)


@pytest.mark.parametrize("version", [None, "0.1.0"])
def test_existing_plain_mesh_dialects_remain_supported(tmp_path, monkeypatch, version):
    """Plain meshes keep the same unversioned and explicitly legacy runtime acceptance."""

    root, _ = _fixture(tmp_path, monkeypatch)
    raw = {"vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "faces": [[0, 1, 2]]}
    if version:
        raw["schema_version"] = version
    _write(root / "geometry/new.json", raw)
    assert set(create_binding(root)["geometry_dependencies"]) == {"geometry/new.json"}


def test_material_override_binds_real_physical_paths(tmp_path, monkeypatch):
    """Capture original/effective payloads, companion and receipt without aliasing path hashes."""

    root, _ = _fixture(tmp_path, monkeypatch)
    binding = create_binding(root)
    material_id = binding["candidate_scene_spec"]["objects"][0]["material_id"]
    original = root / "geometry/new.json"
    derivative = root / "geometry/derivative.json"
    derivative.write_bytes(original.read_bytes() + b" ")
    _write(root / "history/material_receipt.json", {"job_id": root.name, "fixture": True})
    _write(
        root / "analysis/material_binding_derivative.json",
        {
            "schema_version": "0.1.0",
            "topology_unchanged": True,
            "canonical_geometry_payload_overwrite": False,
            "source_receipt_path": "history/material_receipt.json",
            "source_receipt_sha256": sha256_file(root / "history/material_receipt.json"),
            "bindings": [
                {
                    "object_id": "asset.cube",
                    "scene_payload_path": "geometry/new.json",
                    "material_id": material_id,
                    "derivative_path": "geometry/derivative.json",
                    "source_sha256": sha256_file(original),
                    "derivative_sha256": sha256_file(derivative),
                }
            ],
        },
    )
    dependencies = create_binding(root)["geometry_dependencies"]
    assert set(dependencies) == {
        "geometry/new.json",
        "geometry/derivative.json",
        "geometry/source.json",
        "history/material_receipt.json",
        "analysis/material_binding_derivative.json",
    }
    assert dependencies["geometry/new.json"] != dependencies["geometry/derivative.json"]
    assert all(sha256_file(root / path) == digest for path, digest in dependencies.items())


def test_candidate_review_remains_outside_manual_payload_binding(tmp_path, monkeypatch):
    """The new companion does not change the candidate-review or AQ source-bound contract."""

    root, _ = _fixture(tmp_path, monkeypatch)
    state = service.plan_workflow(
        "Compare a bounded parametric revision.",
        job_id=root.name,
        intent="revise_asset",
        revision_strategy="candidate_review",
    )
    raw = json.loads((root / "workflows" / state.workflow_id / "plan.json").read_bytes())
    assert all(BINDING_PARAMETER not in step["parameters"] for step in raw["steps"])
    assert not binding_path(root, state.workflow_id).exists()


@pytest.mark.parametrize(
    "relative",
    ["Analysis/scene_spec.json", "analysis/Scene_Spec.json", "Reports/Revision_Diff.json"],
)
def test_case_variant_canonical_dependencies_are_rejected(tmp_path, monkeypatch, relative):
    """Windows path aliases cannot evade the frozen-source requirement on any host."""

    root, _ = _fixture(tmp_path, monkeypatch)
    payload = _payload_dict(root)
    payload["source_hashes"] = [{"role": "other", "path": relative, "sha256": "a" * 64}]
    payload["source_fingerprint_sha256"] = stable_json_digest(payload["source_hashes"])
    _write(root / "geometry/new.json", payload)
    with pytest.raises(ValueError, match="frozen sources"):
        create_binding(root)


def test_visited_nonmesh_source_cannot_be_used_as_custom_mesh(tmp_path, monkeypatch):
    """Deduplicating recursion never bypasses shape validation required by a scene object."""

    root, _ = _fixture(tmp_path, monkeypatch)
    binding = create_binding(root)
    scene = binding["candidate_scene_spec"]
    invalid = json.loads(json.dumps(scene["objects"][0]))
    invalid["id"] = "asset.invalid"
    invalid["geometry"]["path"] = "geometry/source.json"
    scene["objects"].insert(0, invalid)
    with pytest.raises(ValueError):
        geometry_dependency_hashes(root, SceneSpec.model_validate(scene))


@pytest.mark.parametrize(
    "relative",
    [
        "blender/scene.blend",
        "renders/preview.png",
        "reports/scene_inventory.json",
        "reports/validation.json",
        "Blender/Scene.Blend",
    ],
)
def test_native_build_outputs_require_frozen_source_copies(tmp_path, monkeypatch, relative):
    """The next native build/render/inspect/validate cannot overwrite an approved dependency."""

    root, _ = _fixture(tmp_path, monkeypatch)
    payload = _payload_dict(root)
    payload["source_hashes"] = [{"role": "other", "path": relative, "sha256": "a" * 64}]
    payload["source_fingerprint_sha256"] = stable_json_digest(payload["source_hashes"])
    _write(root / "geometry/new.json", payload)
    with pytest.raises(ValueError, match="frozen sources"):
        create_binding(root)


def test_legacy_versioned_metadata_is_not_reinterpreted_as_structural_contract(
    tmp_path, monkeypatch
):
    """The plain legacy builder accepts extra metadata without requiring a structural recipe."""

    root, _ = _fixture(tmp_path, monkeypatch)
    _write(
        root / "geometry/new.json",
        {
            "schema_version": "0.1.0",
            "semantic_id": "old.advisory_metadata",
            "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            "faces": [[0, 1, 2]],
            "vertex_uvs": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
        },
    )
    assert set(create_binding(root)["geometry_dependencies"]) == {"geometry/new.json"}


def test_linked_job_root_is_not_normalized_into_foreign_ownership(tmp_path, monkeypatch):
    """The owning job root must be checked lexically before any resolving lookup."""

    root, _ = _fixture(tmp_path, monkeypatch)
    moved = root.parent / "original_root"
    root.rename(moved)
    root.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink or junction"):
        create_binding(root)


def test_root_redirection_during_final_transaction_is_blocked(tmp_path, monkeypatch):
    """A job-root alias introduced after authority collection cannot legitimize promotion."""

    import codex_blender_modeler.orchestration.revision_payloads as payloads

    root, state = _fixture(tmp_path, monkeypatch)
    state = _approve(root, _complete(root, state))
    before = (root / "analysis/scene_spec.json").read_bytes()
    real_copy = workspace.shutil.copy2
    real_evidence = payloads.revision_evidence_hashes
    final_copy = False
    moved = root.parent / "original_root"

    def copy(source, destination, *args, **kwargs):
        """Mark the exact final staging copy without changing its contents."""
        nonlocal final_copy
        result = real_copy(source, destination, *args, **kwargs)
        if Path(destination).name.startswith(".scene_spec.replace"):
            final_copy = True
        return result

    def evidence(job_root, workflow_id):
        """Redirect only after collecting the final expected transaction evidence."""
        result = real_evidence(job_root, workflow_id)
        if final_copy and not moved.exists():
            root.rename(moved)
            root.symlink_to(moved, target_is_directory=True)
        return result

    monkeypatch.setattr(workspace.shutil, "copy2", copy)
    monkeypatch.setattr(payloads, "revision_evidence_hashes", evidence)
    state_before = (root / "workflows" / state.workflow_id / "state.json").read_bytes()
    with pytest.raises(service.OrchestrationArtifactConflict, match="owning job root") as failure:
        service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert (moved / "analysis/scene_spec.json").read_bytes() == before
    assert (moved / "workflows" / state.workflow_id / "state.json").read_bytes() == state_before
    assert str(tmp_path) not in str(failure.value)


def test_persisted_dependency_failure_does_not_leak_host_paths(tmp_path, monkeypatch):
    """Contained-path and provenance exceptions become useful path-safe technical conflicts."""

    root, state = _fixture(tmp_path, monkeypatch)
    state = _approve(root, _complete(root, state))
    (root / "geometry/new.json").unlink()
    result = service.reconcile_workflow(root.name, state.workflow_id)
    assert result.status == "blocked"
    persisted = (root / "workflows" / state.workflow_id / "state.json").read_text()
    assert str(tmp_path) not in persisted
    assert "FileNotFoundError" in persisted
