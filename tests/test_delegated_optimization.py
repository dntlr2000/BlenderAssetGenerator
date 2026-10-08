"""Optional delegated authority is exact, finite, non-user and fail-closed."""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_v074_optimization_review import _prepare_review_fixture, _source_provenance

from codex_blender_modeler.optimization import delegated
from codex_blender_modeler.optimization.delegated_models import (
    DelegatedOptimizationAuthorizationV01,
    DelegatedOptimizationConsumptionV01,
    DelegatedOptimizationScopeV01,
    DelegatedOptimizationWorkflowBindingV01,
    DelegatedPackageAuthorityV01,
)
from codex_blender_modeler.optimization.io import load_model, write_model
from codex_blender_modeler.optimization.models import (
    MeshPreflightReport,
    OptimizationApproval,
    OptimizationPlan,
)
from codex_blender_modeler.optimization.optimizer import optimize_asset, plan_asset_optimization
from codex_blender_modeler.packaging.service import _verify_optimization_authorization_evidence
from codex_blender_modeler.workspace import sha256_file


def _fixture(tmp_path, monkeypatch):
    """Create real source bytes with a deterministic Blender-free reviewed run."""

    root, run_id, _ = _prepare_review_fixture(tmp_path, monkeypatch)
    for relative, content in (
        ("analysis/scene_spec.json", b"{}"),
        ("blender/scene.blend", b"BLENDERfixture"),
        ("input/reference.png", b"reference-image-fixture"),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    source = _source_provenance()
    source = source.model_copy(
        update={
            "scene_spec": source.scene_spec.model_copy(
                update={"sha256": sha256_file(root / "analysis/scene_spec.json")}
            ),
            "blend": source.blend.model_copy(
                update={"sha256": sha256_file(root / "blender/scene.blend")}
            ),
        }
    )
    (root / "job.json").write_text(
        json.dumps(
            {
                "job_id": root.name,
                "reference_path": "input/reference.png",
                "reference_sha256": sha256_file(root / "input/reference.png"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(delegated, "job_dir", lambda _: root)
    monkeypatch.setattr("codex_blender_modeler.workspace.job_dir", lambda _: root)
    monkeypatch.setattr(delegated, "collect_source_provenance", lambda *_: source)
    monkeypatch.setattr(
        "codex_blender_modeler.optimization.optimizer.collect_source_provenance", lambda *_: source
    )
    run_root = root / "optimization/runs" / run_id
    preflight = load_model(run_root / "mesh_preflight_report.json", MeshPreflightReport).model_copy(
        update={"source": source}
    )
    write_model(run_root / "mesh_preflight_report.json", preflight)
    monkeypatch.setattr(
        "codex_blender_modeler.optimization.optimizer._load_or_run_preflight",
        lambda *_: (run_id, preflight, run_root),
    )
    plan_asset_optimization(root.name, run_id=run_id)
    for name in ("delegation.txt", "extension.txt"):
        (root / "optimization" / name).write_text(
            "Fixture-only explicit user authorization: " + name, encoding="utf-8"
        )
    identities = [
        {"job_id": name, "reference_sha256": sha256_file(root / "input/reference.png")}
        for name in [root.name, "other_two", "other_three", "other_four", "other_five"]
    ]
    scope_args = dict(
        delegation_id="five-task",
        delegation_text_path="optimization/delegation.txt",
        delegation_text_sha256=sha256_file(root / "optimization/delegation.txt"),
        extension_confirmation_text_path="optimization/extension.txt",
        extension_confirmation_text_sha256=sha256_file(root / "optimization/extension.txt"),
        task_context_id="fixture-five-completion",
        expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        allowed_assets_json=json.dumps(identities),
        extension_confirmation="explicit_user_confirmation",
        enable_delegated_authority=True,
    )
    delegated.create_delegated_optimization_scope(root.name, **scope_args)
    scope_path = root / "optimization/delegations/five-task/scope.json"
    grant_args = dict(
        run_id=run_id,
        plan_sha256=sha256_file(run_root / "review_plan.json"),
        scope_path=str(scope_path),
        scope_sha256=sha256_file(scope_path),
        decision_note="Fixture technical decision, no final human acceptance",
        enable_delegated_authority=True,
    )
    return root, run_root, scope_args, grant_args


def _issue(root, run_root, grant_args):
    """Issue one fixture grant and preserve its exact external consumption hash."""

    grant = delegated.authorize_delegated_asset_optimization(root.name, **grant_args)
    path = run_root / delegated.AUTHORIZATION_FILE
    args = dict(
        authorization_path=path,
        authorization_sha256=sha256_file(path),
        approved_plan_sha256=grant.plan_sha256,
        enable_delegated_authority=True,
    )
    return grant, args


def test_exact_consumption_is_non_user_immutable_and_single_use(tmp_path, monkeypatch):
    """Consume once, preserve grant bytes, and verify completed-run authority separately."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    grant, consume = _issue(root, run_root, args)
    before = (run_root / delegated.AUTHORIZATION_FILE).read_bytes()
    plan = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    result = delegated.consume_delegated_optimization_authorization(root, run_root, plan, **consume)
    assert result.actor == "delegated_assistant" and result.final_human_acceptance is False
    assert (run_root / delegated.AUTHORIZATION_FILE).read_bytes() == before
    assert not (run_root / "optimization_approval.json").exists()
    with pytest.raises(ValueError, match="already been consumed"):
        delegated.consume_delegated_optimization_authorization(root, run_root, plan, **consume)
    complete = plan.model_copy(
        update={
            "status": "complete",
            "approved_at": grant.authorized_at,
            "completed_at": datetime.now(UTC),
        }
    )
    assert "optimization_delegated_authorization" in _verify_optimization_authorization_evidence(
        root, run_root, complete
    )


@pytest.mark.parametrize(
    "filename",
    [
        "review_plan.json",
        "optimization_review.json",
        "mesh_preflight_report.json",
        "../../delegations/five-task/delegation.txt",
        "../../delegations/five-task/extension_confirmation.txt",
        "../../../asset_profiles/portable_gltf.json",
        "../../../analysis/scene_spec.json",
        "../../../blender/scene.blend",
        "../../../input/reference.png",
        delegated.AUTHORIZATION_FILE,
        delegated.SCOPE_SNAPSHOT,
        delegated.CLAIM_SNAPSHOT,
        delegated.TASK_BINDING_SNAPSHOT,
    ],
)
def test_tampered_exact_evidence_never_consumes(tmp_path, monkeypatch, filename):
    """Fail closed even for semantically harmless byte changes across every binding."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    _grant, consume = _issue(root, run_root, args)
    plan = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    path = run_root / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises((ValueError, RuntimeError)):
        delegated.consume_delegated_optimization_authorization(root, run_root, plan, **consume)
    assert not (run_root / delegated.CONSUMPTION_FILE).exists()


@pytest.mark.parametrize(
    "other", ["optimization_approval.json", "optimization_policy_authorization.json"]
)
@pytest.mark.parametrize("dangling", [False, True])
def test_mixed_or_dangling_authority_is_rejected(tmp_path, monkeypatch, other, dangling):
    """Treat even unreadable dangling competing evidence as an authority conflict."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    _grant, consume = _issue(root, run_root, args)
    if dangling:
        (run_root / other).symlink_to(run_root / "absent-target")
    else:
        (run_root / other).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="mixes"):
        delegated.consume_delegated_optimization_authorization(
            root,
            run_root,
            load_model(run_root / "optimization_plan.json", OptimizationPlan),
            **consume,
        )
    assert not (run_root / delegated.CONSUMPTION_FILE).exists()


def test_scope_rename_cannot_reset_reserve(tmp_path, monkeypatch):
    """Pin source text identity independently of scope labels or task labels."""

    root, _run, scope, _args = _fixture(tmp_path, monkeypatch)
    with pytest.raises(FileExistsError):
        delegated.create_delegated_optimization_scope(
            root.name,
            **{**scope, "delegation_id": "renamed-scope", "task_context_id": "renamed-task"},
        )
    assert not (root / "optimization/delegations/renamed-scope").exists()


def test_absent_opt_in_and_no_automatic_grant_discovery(tmp_path, monkeypatch):
    """A valid grant file alone never selects the new execution authority."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="explicit"):
        delegated.authorize_delegated_asset_optimization(
            root.name, **{**args, "enable_delegated_authority": False}
        )
    _issue(root, run_root, args)
    with pytest.raises(RuntimeError, match="mixes"):
        optimize_asset(root.name, run_id=run_root.name, approved_plan_sha256=args["plan_sha256"])
    assert not (run_root / delegated.CONSUMPTION_FILE).exists()


def test_blender_failure_does_not_refund_grant(tmp_path, monkeypatch):
    """Reserve/consume before Blender and retain terminal failure plus used authority."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    _grant, consume = _issue(root, run_root, args)

    def fail(*_args, **_kwargs):
        """Simulate a technical Blender failure after consumption."""
        assert (root / "workflows/.lock.json").is_file()
        raise RuntimeError("fixture Blender failed")

    monkeypatch.setattr("codex_blender_modeler.optimization.optimizer.run_blender", fail)
    with pytest.raises(RuntimeError, match="fixture Blender failed"):
        optimize_asset(
            root.name,
            run_id=run_root.name,
            approved_plan_sha256=consume["approved_plan_sha256"],
            delegated_authorization_path=consume["authorization_path"],
            delegated_authorization_sha256=consume["authorization_sha256"],
            enable_delegated_authority=True,
        )
    assert (run_root / delegated.CONSUMPTION_FILE).is_file()
    assert load_model(run_root / "optimization_plan.json", OptimizationPlan).status == "failed"
    with pytest.raises(ValueError, match="already been consumed"):
        optimize_asset(
            root.name,
            run_id=run_root.name,
            approved_plan_sha256=consume["approved_plan_sha256"],
            delegated_authorization_path=consume["authorization_path"],
            delegated_authorization_sha256=consume["authorization_sha256"],
            enable_delegated_authority=True,
        )


def test_concurrent_consumers_have_exactly_one_winner(tmp_path, monkeypatch):
    """The host lock and exclusive receipt prevent two side-effect admissions."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    _grant, consume = _issue(root, run_root, args)
    plan = load_model(run_root / "optimization_plan.json", OptimizationPlan)

    def attempt(_):
        """Return whether this contender obtained the sole exact grant."""
        try:
            delegated.consume_delegated_optimization_authorization(root, run_root, plan, **consume)
            return True
        except (ValueError, RuntimeError, FileExistsError):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(attempt, range(2))) == 1


def test_three_ordinal_claims_are_finite_and_nonrefundable(tmp_path, monkeypatch):
    """A fresh exact run can use a remaining claim; the fourth is blocked."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    _issue(root, run_root, args)
    source_preflight = load_model(run_root / "mesh_preflight_report.json", MeshPreflightReport)
    for number in (2, 3, 4):
        new_id = f"retry-{number}"
        new_root = run_root.parent / new_id
        new_root.mkdir()
        preflight = source_preflight.model_copy(update={"report_id": f"preflight.{new_id}"})
        write_model(new_root / "mesh_preflight_report.json", preflight)
        monkeypatch.setattr(
            "codex_blender_modeler.optimization.optimizer._load_or_run_preflight",
            lambda *_, n=new_id, p=preflight, r=new_root: (n, p, r),
        )
        plan_asset_optimization(root.name, run_id=new_id)
        fresh_args = {
            **args,
            "run_id": new_id,
            "plan_sha256": sha256_file(new_root / "review_plan.json"),
        }
        if number < 4:
            grant, _consume = _issue(root, new_root, fresh_args)
            assert grant.grant_ordinal == number
        else:
            with pytest.raises(ValueError, match="exhausted"):
                _issue(root, new_root, fresh_args)
    assert (
        len(list((root / "optimization/delegations/five-task/authorization_claims").iterdir())) == 3
    )


def test_unknown_actor_and_human_acceptance_are_rejected(tmp_path, monkeypatch):
    """New and old contracts keep their actor and acceptance semantics disjoint."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    grant, _consume = _issue(root, run_root, args)
    for field, value in (
        ("actor", "user"),
        ("final_human_acceptance", True),
        ("profile_id", "fbx_interchange"),
        ("schema_version", "0.7.0"),
    ):
        with pytest.raises(ValidationError):
            DelegatedOptimizationAuthorizationV01.model_validate(
                {**grant.model_dump(mode="json"), field: value}
            )
    assert OptimizationApproval.model_json_schema()["properties"]["approved_by"]["const"] == "user"


def test_schemas_remain_exact_separate_companions():
    """Keep generator output authoritative and preserve legacy approval bytes."""

    root = Path(__file__).resolve().parents[1]
    for name, model in {
        "scope": DelegatedOptimizationScopeV01,
        "authorization": DelegatedOptimizationAuthorizationV01,
        "consumption": DelegatedOptimizationConsumptionV01,
        "workflow_binding": DelegatedOptimizationWorkflowBindingV01,
    }.items():
        path = root / "schemas" / f"delegated_optimization_{name}_v01.schema.json"
        assert json.loads(path.read_text(encoding="utf-8")) == model.model_json_schema()
    assert (
        json.loads((root / "schemas/delegated_package_authority_v01.schema.json").read_text())
        == DelegatedPackageAuthorityV01.model_json_schema()
    )


def _sealed_package(root, run_root, grant):
    """Build a schema-valid fixture package with complete immutable authority snapshots."""

    from codex_blender_modeler.optimization.models import HashedArtifact
    from codex_blender_modeler.packaging.delegated import write_delegated_package_authority
    from codex_blender_modeler.packaging.models import ExportPackageManifest, PackageFile
    from codex_blender_modeler.packaging.service import _optimization_authorization_paths

    package = root / "exports/packages/portable_gltf/fixture-package"
    metadata = package / "metadata"
    metadata.mkdir(parents=True)
    reviewed = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    execution = reviewed.model_copy(
        update={"status": "running", "approved_at": grant.authorized_at}
    )
    write_model(run_root / "execution_plan.json", execution)
    plan = execution.model_copy(
        update={
            "status": "complete",
            "completed_at": datetime.now(UTC),
            "output_manifests": [
                HashedArtifact(
                    id="execution.fixture",
                    kind="optimization_plan",
                    path=f"optimization/runs/{run_root.name}/execution_plan.json",
                    sha256=sha256_file(run_root / "execution_plan.json"),
                )
            ],
        }
    )
    write_model(run_root / "optimization_plan.json", plan)
    sources = _optimization_authorization_paths(run_root)
    sources.update(
        {
            "asset_profile": root / "asset_profiles/portable_gltf.json",
            "mesh_preflight_report": run_root / "mesh_preflight_report.json",
            "optimization_plan": run_root / "optimization_plan.json",
            "execution_plan": run_root / "execution_plan.json",
        }
    )
    for key, source in sources.items():
        shutil.copyfile(source, metadata / f"{key}{source.suffix}")
    (package / "asset.glb").write_bytes(b"fixture-only-no-Blender-import-claim")
    write_delegated_package_authority(
        package, job_id=root.name, run_id=run_root.name, package_id=package.name
    )
    files = [
        PackageFile(
            id=f"file.{i}",
            kind="primary_asset" if path.name == "asset.glb" else "metadata",
            path=path.relative_to(root).as_posix(),
            sha256=sha256_file(path),
            byte_size=path.stat().st_size,
            media_type="application/octet-stream",
        )
        for i, path in enumerate(sorted(p for p in package.rglob("*") if p.is_file()))
    ]
    manifest = ExportPackageManifest(
        package_id=package.name,
        job_id=root.name,
        run_id=run_root.name,
        profile_id="portable_gltf",
        source=grant.source,
        optimization_plan=HashedArtifact(
            id="plan.fixture",
            kind="optimization_plan",
            path=(metadata / "optimization_plan.json").relative_to(root).as_posix(),
            sha256=sha256_file(metadata / "optimization_plan.json"),
        ),
        status="complete",
        package_root=package.relative_to(root).as_posix(),
        files=files,
        primary_file_id=next(f.id for f in files if f.kind == "primary_asset"),
        semantic_ids=["building.main"],
        material_ids=["fixture.material"],
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    write_model(package / "package_manifest.json", manifest)
    return package


def test_relocated_package_validation_is_self_contained_and_non_executing(tmp_path, monkeypatch):
    """Move a sealed fixture away and forbid access to every original source authority."""

    from codex_blender_modeler.packaging.delegated import validate_delegated_package_authority

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    grant, consume = _issue(root, run_root, args)
    delegated.consume_delegated_optimization_authorization(
        root, run_root, load_model(run_root / "optimization_plan.json", OptimizationPlan), **consume
    )
    source = _sealed_package(root, run_root, grant)
    destination = tmp_path / "unrelated" / "relocated-bundle"
    shutil.copytree(source, destination)
    root.rename(tmp_path / "original-unavailable")
    result = validate_delegated_package_authority(destination)
    assert result["ok"] is True and result["actor"] == "delegated_assistant"
    assert result["final_human_acceptance"] is False
    assert result["grants_execution_authority"] is False
    assert result["clean_import_validated"] is False
    (destination / "metadata" / delegated.TEXT_SNAPSHOT).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="receipt changed"):
        validate_delegated_package_authority(destination)


def test_internal_symlink_and_simulated_reparse_are_rejected(tmp_path, monkeypatch):
    """Use the existing cross-platform reparse guard even for a link inside the job."""

    import os
    import stat
    from types import SimpleNamespace

    from codex_blender_modeler.production import validation

    root, _run, _scope, _args = _fixture(tmp_path, monkeypatch)
    link = root / "linked"
    link.symlink_to(root / "optimization", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink or junction"):
        delegated._safe_path(root, link / "delegation.txt")
    original = os.lstat

    def lstat(path, *args, **kwargs):
        """Simulate the Windows reparse bit on an ordinary fixture directory."""
        if Path(path) == root / "optimization":
            return SimpleNamespace(
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT, st_mode=stat.S_IFDIR
            )
        return original(path, *args, **kwargs)

    monkeypatch.setattr(validation.os, "lstat", lstat)
    with pytest.raises(ValueError, match="symlink or junction"):
        delegated._safe_path(root, root / "optimization/delegation.txt")


def test_expired_scope_and_foreign_job_cannot_issue(tmp_path, monkeypatch):
    """The host checks runtime expiration and actual reference bytes before new grants."""

    root, _run, _scope, args = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(delegated, "utc_now", lambda: datetime.now(UTC) + timedelta(days=2))
    with pytest.raises(ValueError, match="expired"):
        delegated.authorize_delegated_asset_optimization(root.name, **args)


def _standard_workflow(root, run_root, monkeypatch):
    """Create a minimal exact native Standard workflow waiting at optimization approval."""

    from codex_blender_modeler.optimization import delegated_workflow
    from codex_blender_modeler.orchestration import service
    from codex_blender_modeler.orchestration.models import (
        ArtifactRequirement,
        DestinationRequest,
        DestinationResolution,
        WorkflowPlan,
        WorkflowRequest,
        WorkflowStep,
    )

    workflow_root = root / "workflows/native-fixture"
    workflow_root.mkdir(parents=True, exist_ok=True)
    request = WorkflowRequest(
        workflow_id=workflow_root.name,
        job_id=root.name,
        raw_request="Fixture portable package",
        requested_scope="full",
        created_at=datetime.now(UTC),
    )
    write_model(workflow_root / "request.json", request)
    approval = WorkflowStep(
        step_id="portable.plan_approval",
        title="Exact optimization authority",
        phase="portable",
        execution_mode="specialized_approval",
        approval_gate="optimization_plan",
        parameters={"run_id": run_root.name, "profile_id": "portable_gltf"},
        outputs=[
            ArtifactRequirement(
                artifact_id="portable.optimization_approval",
                path=f"optimization/runs/{run_root.name}/optimization_approval.json",
                acceptance="valid_json",
            )
        ],
    )
    optimize = WorkflowStep(
        step_id="portable.optimize",
        title="Optimize fixture",
        phase="portable",
        execution_mode="host",
        tool_name="optimize_portable_asset",
        depends_on=[approval.step_id],
        parameters={"run_id": run_root.name, "profile_id": "portable_gltf"},
        outputs=[
            ArtifactRequirement(
                artifact_id="portable.optimized_blend",
                path=f"optimization/runs/{run_root.name}/optimized/scene.blend",
            )
        ],
    )
    final = WorkflowStep(
        step_id="portable.final_approval",
        title="Final human package acceptance",
        phase="portable",
        execution_mode="approval",
        approval_gate="final_package",
        depends_on=[optimize.step_id],
    )
    plan = WorkflowPlan(
        workflow_id=workflow_root.name,
        job_id=root.name,
        request_sha256=sha256_file(workflow_root / "request.json"),
        routing_sha256="a" * 64,
        intent="portable_package",
        scope="full",
        destination=DestinationResolution(
            requested=DestinationRequest(),
            status="not_requested",
            reason="Fixture portable boundary",
        ),
        steps=[approval, optimize, final],
        terminal_step_id=final.step_id,
        created_at=datetime.now(UTC),
    )
    write_model(workflow_root / "plan.json", plan)
    monkeypatch.setattr(service, "job_dir", lambda _: root)
    monkeypatch.setattr(delegated_workflow, "job_dir", lambda _: root)
    monkeypatch.setattr(
        service, "_load_workflow", lambda *_: (root, workflow_root, request, plan, None)
    )
    state = service._reconcile_locked(root, workflow_root, plan, request, previous=None)
    return workflow_root, request, plan, state


def test_standard_explicit_binding_completes_only_optimization_gate(tmp_path, monkeypatch):
    """Native reconciliation adopts explicit delegated evidence, never final acceptance."""

    from codex_blender_modeler.optimization.delegated_workflow import (
        bind_delegated_optimization_workflow,
    )
    from codex_blender_modeler.orchestration import service

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    _grant, consume = _issue(root, run_root, args)
    workflow_root, request, plan, state = _standard_workflow(root, run_root, monkeypatch)
    assert state.steps[0].status == "waiting_for_approval"
    plan_bytes = (workflow_root / "plan.json").read_bytes()
    bind_delegated_optimization_workflow(
        root.name,
        workflow_id=workflow_root.name,
        workflow_plan_sha256=sha256_file(workflow_root / "plan.json"),
        workflow_input_fingerprint=state.steps[0].input_fingerprint,
        run_id=run_root.name,
        authorization_sha256=consume["authorization_sha256"],
        enable_delegated_authority=True,
    )
    updated = service._reconcile_locked(root, workflow_root, plan, request, previous=state)
    assert updated.steps[0].status == "complete"
    assert updated.steps[0].approval_id.startswith("delegated_assistant:")
    assert updated.steps[1].status == "ready"
    assert updated.steps[2].status == "pending"
    assert (workflow_root / "plan.json").read_bytes() == plan_bytes
    assert not (run_root / "optimization_approval.json").exists()
    (workflow_root / "policy_authorizations").mkdir()
    (workflow_root / "policy_authorizations/portable.plan_approval.json").write_text("{}")
    rejected = service._reconcile_locked(root, workflow_root, plan, request, previous=updated)
    assert rejected.steps[0].status == "stale"
    assert rejected.steps[1].status == "pending"


@pytest.mark.parametrize("mutation", ["delete", "alter"])
def test_preserved_claim_prevents_deleted_or_changed_reserve_reset(tmp_path, monkeypatch, mutation):
    """Removing a trailing canonical claim cannot refund its retained issued authority."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    _issue(root, run_root, args)
    claim = root / "optimization/delegations/five-task/authorization_claims/001.json"
    if mutation == "delete":
        claim.unlink()
    else:
        payload = json.loads(claim.read_text())
        payload["authorization_sha256"] = "b" * 64
        claim.write_text(json.dumps(payload))
    source_preflight = load_model(run_root / "mesh_preflight_report.json", MeshPreflightReport)
    new_root = run_root.parent / "reserve-reset"
    new_root.mkdir()
    preflight = source_preflight.model_copy(update={"report_id": "preflight.reserve-reset"})
    write_model(new_root / "mesh_preflight_report.json", preflight)
    monkeypatch.setattr(
        "codex_blender_modeler.optimization.optimizer._load_or_run_preflight",
        lambda *_: (new_root.name, preflight, new_root),
    )
    plan_asset_optimization(root.name, run_id=new_root.name)
    with pytest.raises(ValueError, match="(deleted|claim|ordinal)"):
        _issue(
            root,
            new_root,
            {
                **args,
                "run_id": new_root.name,
                "plan_sha256": sha256_file(new_root / "review_plan.json"),
            },
        )
    assert not (new_root / delegated.AUTHORIZATION_FILE).exists()


def test_consumed_history_survives_expiry_but_new_execution_does_not(tmp_path, monkeypatch):
    """Expiration closes eligibility without retroactively invalidating sealed history."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    grant, consume = _issue(root, run_root, args)
    plan = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    delegated.consume_delegated_optimization_authorization(root, run_root, plan, **consume)
    completed = plan.model_copy(
        update={
            "status": "complete",
            "approved_at": grant.authorized_at,
            "completed_at": datetime.now(UTC),
            "output_manifests": [grant.source.blend],
        }
    )
    write_model(run_root / "optimization_plan.json", completed)
    monkeypatch.setattr(delegated, "utc_now", lambda: datetime.now(UTC) + timedelta(days=8))
    assert (
        delegated.validate_delegated_optimization_authorization(
            root, run_root, completed, require_consumed=True
        )
        == grant
    )
    delegated.validate_delegated_contract_file(root, run_root / delegated.AUTHORIZATION_FILE)
    with pytest.raises(ValueError, match="expired"):
        delegated.validate_delegated_optimization_authorization(
            root, run_root, completed, require_consumed=True, require_current_eligibility=True
        )


def test_public_cli_mcp_parity_and_disabled_defaults():
    """Expose each host operation consistently without broadening phase/controller tools."""

    import inspect
    import tomllib

    from typer.testing import CliRunner

    from codex_blender_modeler import mcp_server
    from codex_blender_modeler.cli import app
    from codex_blender_modeler.repository_catalog import PHASE_TOOL_PROFILES

    tools = {
        "create_portable_asset_delegation",
        "delegate_portable_asset_optimization",
        "bind_portable_asset_delegation_workflow",
        "validate_portable_package_delegation",
    }
    for command in (
        "asset-delegation-create",
        "asset-plan-delegate",
        "asset-delegation-bind-workflow",
        "asset-delegation-validate-package",
    ):
        assert CliRunner().invoke(app, [command, "--help"]).exit_code == 0
    for name in tools - {"validate_portable_package_delegation"}:
        assert (
            inspect.signature(getattr(mcp_server, name))
            .parameters["enable_delegated_authority"]
            .default
            is False
        )
    config = tomllib.loads((Path(__file__).resolve().parents[1] / ".codex/config.toml").read_text())
    assert tools <= set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert all(not tools.intersection(profile.allowed_tools) for profile in PHASE_TOOL_PROFILES)


def test_historical_consumed_proof_ignores_legitimate_live_source_supersession(
    tmp_path, monkeypatch
):
    """Preserve old exact proof while a new canonical scene/profile requires new authority."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    grant, consume = _issue(root, run_root, args)
    plan = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    delegated.consume_delegated_optimization_authorization(root, run_root, plan, **consume)
    completed = plan.model_copy(
        update={
            "status": "complete",
            "approved_at": grant.authorized_at,
            "completed_at": datetime.now(UTC),
            "output_manifests": [grant.source.blend],
        }
    )
    (root / "analysis/scene_spec.json").write_bytes(b"legitimately superseded candidate")
    (root / "blender/scene.blend").write_bytes(b"legitimately rebuilt Blender source")
    (root / "asset_profiles/portable_gltf.json").write_bytes(b"later profile revision")
    assert (
        delegated.validate_delegated_optimization_authorization(
            root, run_root, completed, require_consumed=True
        )
        == grant
    )
    with pytest.raises(ValueError, match="changed"):
        delegated.validate_delegated_optimization_authorization(
            root, run_root, completed, require_consumed=True, require_current_eligibility=True
        )


def test_rehashed_malformed_execution_snapshot_still_fails(tmp_path, monkeypatch):
    """Outer checksum rewrites cannot make malformed required execution evidence valid."""

    from codex_blender_modeler.packaging.delegated import (
        MANIFEST_FILE,
        validate_delegated_package_authority,
    )

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    grant, consume = _issue(root, run_root, args)
    delegated.consume_delegated_optimization_authorization(
        root, run_root, load_model(run_root / "optimization_plan.json", OptimizationPlan), **consume
    )
    package = _sealed_package(root, run_root, grant)
    path = package / "metadata/execution_plan.json"
    path.write_bytes(b"not an execution plan")
    evidence_path = package / "metadata" / MANIFEST_FILE
    evidence = json.loads(evidence_path.read_text())
    evidence["evidence_sha256"][path.name] = sha256_file(path)
    evidence_path.write_text(json.dumps(evidence))
    manifest_path = package / "package_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for receipt in manifest["files"]:
        for changed in (path, evidence_path):
            if receipt["path"] == changed.relative_to(root).as_posix():
                receipt.update(sha256=sha256_file(changed), byte_size=changed.stat().st_size)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Invalid JSON contract"):
        validate_delegated_package_authority(package)


def test_native_standard_execution_consumes_under_existing_exact_workflow_lock(
    tmp_path, monkeypatch
):
    """The real Standard host adapter consumes the grant before a simulated Blender failure."""

    from codex_blender_modeler.optimization.delegated_workflow import (
        bind_delegated_optimization_workflow,
    )
    from codex_blender_modeler.orchestration import service
    from codex_blender_modeler.orchestration.locks import workflow_write_lock

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    grant, consume = _issue(root, run_root, args)
    workflow_root, request, plan, state = _standard_workflow(root, run_root, monkeypatch)
    bind_delegated_optimization_workflow(
        root.name,
        workflow_id=workflow_root.name,
        workflow_plan_sha256=sha256_file(workflow_root / "plan.json"),
        workflow_input_fingerprint=state.steps[0].input_fingerprint,
        run_id=run_root.name,
        authorization_sha256=consume["authorization_sha256"],
        enable_delegated_authority=True,
    )
    monkeypatch.setattr("codex_blender_modeler.workspace.job_dir", lambda _: root)

    def fail(*_args, **_kwargs):
        """Interrupt execution only after its real host authority admission."""
        raise RuntimeError("native fixture Blender failure")

    monkeypatch.setattr("codex_blender_modeler.optimization.optimizer.run_blender", fail)
    with workflow_write_lock(root, root.name, workflow_root.name):
        with pytest.raises(RuntimeError, match="native fixture Blender failure"):
            service._execute_host_tool(
                root, workflow_root, request, plan.steps[1], input_fingerprint="a" * 64
            )
    assert (run_root / delegated.CONSUMPTION_FILE).is_file()
    updated = service._reconcile_locked(root, workflow_root, plan, request, previous=state)
    assert updated.steps[0].status == "complete"
    assert updated.steps[-1].status != "complete"
    assert not (run_root / "optimization_approval.json").exists()
    assert grant.actor == "delegated_assistant"


def test_direct_optimize_cannot_adopt_another_same_process_lock(tmp_path, monkeypatch):
    """An unrelated held lock cannot be auto-adopted merely because its PID matches."""

    from codex_blender_modeler.orchestration.locks import workflow_write_lock

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    _grant, consume = _issue(root, run_root, args)
    with workflow_write_lock(root, root.name, "unrelated-same-process"):
        with pytest.raises(RuntimeError, match="Another workflow"):
            optimize_asset(
                root.name,
                run_id=run_root.name,
                approved_plan_sha256=consume["approved_plan_sha256"],
                delegated_authorization_path=consume["authorization_path"],
                delegated_authorization_sha256=consume["authorization_sha256"],
                enable_delegated_authority=True,
            )
    assert not (run_root / delegated.CONSUMPTION_FILE).exists()


def test_direct_package_locks_before_reading_current_run(tmp_path, monkeypatch):
    """Keep delegated packaging serialized across provenance validation and export."""

    from codex_blender_modeler.packaging import service

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    _grant, consume = _issue(root, run_root, args)
    monkeypatch.setattr(service, "job_dir", lambda _: root)

    def observe(*_args):
        """Observe the acquired direct lock before any package source collection."""
        assert (root / "workflows/.lock.json").is_file()
        raise RuntimeError("fixture package source boundary")

    monkeypatch.setattr(service, "_run_for_package", observe)
    with pytest.raises(RuntimeError, match="fixture package source boundary"):
        service.package_asset(
            root.name,
            run_id=run_root.name,
            delegated_authorization_sha256=consume["authorization_sha256"],
        )
    assert not (root / "workflows/.lock.json").exists()


def test_foreign_job_cannot_receive_current_candidate_authority(tmp_path, monkeypatch):
    """A caller-selected foreign job cannot borrow this reviewed candidate or scope."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="stale or foreign"):
        delegated.authorize_delegated_asset_optimization("foreign_asset", **args)
    assert not (run_root / delegated.AUTHORIZATION_FILE).exists()
    assert not (root / "optimization/delegations/five-task/authorization_claims").exists()


def test_copied_grant_cannot_execute_in_a_foreign_run(tmp_path, monkeypatch):
    """A byte-exact grant copied into another run remains evidence, never fresh authority."""

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    _grant, consume = _issue(root, run_root, args)
    foreign = run_root.parent / "foreign-run"
    shutil.copytree(run_root, foreign)
    with pytest.raises(ValueError, match="(reused|changed|claim|run)"):
        delegated.consume_delegated_optimization_authorization(
            root,
            foreign,
            load_model(foreign / "optimization_plan.json", OptimizationPlan),
            **{**consume, "authorization_path": foreign / delegated.AUTHORIZATION_FILE},
        )
    assert not (foreign / delegated.CONSUMPTION_FILE).exists()
    assert not (run_root / delegated.CONSUMPTION_FILE).exists()


def test_relocated_receipt_size_must_match_exact_file_bytes(tmp_path, monkeypatch):
    """A rehashed outer manifest cannot misstate a contained receipt's byte size."""

    from codex_blender_modeler.packaging.delegated import validate_delegated_package_authority

    root, run_root, _scope, args = _fixture(tmp_path, monkeypatch)
    grant, consume = _issue(root, run_root, args)
    delegated.consume_delegated_optimization_authorization(
        root, run_root, load_model(run_root / "optimization_plan.json", OptimizationPlan), **consume
    )
    package = _sealed_package(root, run_root, grant)
    manifest_path = package / "package_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["byte_size"] += 1
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="receipt changed"):
        validate_delegated_package_authority(package)
