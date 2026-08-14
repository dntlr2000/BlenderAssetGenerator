"""Focused append-only Material Closure incident publication tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_blender_modeler.autonomy_v2.delivery_service import (
    write_immutable_v2_model,
)
from codex_blender_modeler.material_closure.incident_service import (
    RecoverySourceArchiveSpec,
    archive_job_specific_recovery_sources,
    publish_current_material_canonical_observations,
    publish_material_closure_model,
    supersede_material_retry,
)
from codex_blender_modeler.material_closure.models import (
    ExactArtifact,
    MaterialClosureBoundContract,
)

NOW = datetime(2026, 8, 14, 2, 0, tzinfo=UTC)


def _identity() -> MaterialClosureBoundContract:
    """Build one generic exact session identity for publication tests."""

    return MaterialClosureBoundContract(
        job_id="fixture_job",
        workflow_id="fixture-workflow",
        dispatch_id="fixture-dispatch",
        session_id="fixture-session",
        producer="tests",
        producer_version="0.1.0",
        created_at=NOW,
    )


def _artifact(root: Path, relative_path: str, *, artifact_id: str) -> ExactArtifact:
    """Bind one fixture file by exact bytes."""

    path = root.joinpath(*relative_path.split("/"))
    content = path.read_bytes()
    return ExactArtifact(
        artifact_id=artifact_id,
        kind="fixture_artifact",
        path=relative_path,
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        media_type="application/json",
    )


def _write(root: Path, relative_path: str, content: bytes) -> None:
    """Write one bounded test input before invoking immutable services."""

    path = root.joinpath(*relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_source_inventory_preserves_dirty_working_bytes_and_index_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Archive working bytes while recording that tracked index bytes differ."""

    repository = tmp_path / "repo"
    job_root = tmp_path / "job"
    repository.mkdir()
    job_root.mkdir()
    source_path = "src/framework_recovery.py"
    _write(repository, source_path, b"working incident source\n")
    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.incident_service._git_index_bytes",
        lambda _root, _path: b"index incident source\n",
    )
    inventory, artifact = archive_job_specific_recovery_sources(
        repo_root=repository,
        job_root=job_root,
        identity=_identity(),
        inventory_id="inventory-01",
        sources=[
            RecoverySourceArchiveSpec(
                source_path=source_path,
                job_specific_literals=("fixture_job",),
                generic_capabilities=("dependency_collection",),
            )
        ],
        created_at=NOW,
    )
    record = inventory.sources[0]
    assert record.working_tree_differs_from_index is True
    assert record.archive_sha256 == record.sha256
    assert job_root.joinpath(*record.archive_path.split("/")).read_bytes() == (
        b"working incident source\n"
    )
    assert artifact.path.endswith("inventory.json")


def test_retry_supersession_distinguishes_approval_bytes_from_exact_absence(
    tmp_path: Path,
) -> None:
    """Publish separate immutable receipts for approved and never-approved retries."""

    job_root = tmp_path / "job"
    job_root.mkdir()
    state_path = "production/autonomy_v2/fixture-session/states/0002.json"
    failure_path = "production/autonomy_v2/fixture-session/failures/report.json"
    approved_plan_path = "production/autonomy_v2/fixture-session/retries/approved/plan.json"
    approval_path = "production/autonomy_v2/fixture-session/retries/approved/approval.txt"
    pending_plan_path = "production/autonomy_v2/fixture-session/retries/pending/plan.json"
    for path, content in (
        (state_path, b'{"state":"cancelled"}\n'),
        (failure_path, b'{"framework_failure":true}\n'),
        (approved_plan_path, b'{"retry":"approved"}\n'),
        (approval_path, b"approved exact plan\n"),
        (pending_plan_path, b'{"retry":"pending"}\n'),
    ):
        _write(job_root, path, content)
    state = _artifact(job_root, state_path, artifact_id="state")
    failure = _artifact(job_root, failure_path, artifact_id="failure")
    approved_plan = _artifact(job_root, approved_plan_path, artifact_id="approved-plan")
    approval = _artifact(job_root, approval_path, artifact_id="approval")
    pending_plan = _artifact(job_root, pending_plan_path, artifact_id="pending-plan")
    approved, _ = supersede_material_retry(
        job_root=job_root,
        retry_plan=approved_plan,
        retry_approval=approval,
        expected_approval_path=None,
        current_state=state,
        framework_failure_report=failure,
        identity=_identity(),
        receipt_id="approved-supersession",
        supersession_reason="source state is historical",
        observation_context_sha256="a" * 64,
        created_at=NOW,
    )
    pending, _ = supersede_material_retry(
        job_root=job_root,
        retry_plan=pending_plan,
        retry_approval=None,
        expected_approval_path=(
            "production/autonomy_v2/fixture-session/retries/pending/approval.txt"
        ),
        current_state=state,
        framework_failure_report=failure,
        identity=_identity(),
        receipt_id="pending-supersession",
        supersession_reason="source state is historical",
        observation_context_sha256="b" * 64,
        created_at=NOW,
    )
    assert approved.retry_approval == approval
    assert approved.retry_approval_absence is None
    assert pending.retry_approval is None
    assert pending.retry_approval_absence is not None
    assert pending.executable is False


def test_current_canonical_observations_are_run_owned_and_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Publish fresh Blender inventory/provenance without changing canonical geometry."""

    job_root = tmp_path / "job"
    job_root.mkdir()
    for relative_path, content in (
        ("analysis/scene_spec.json", b'{"job_id":"fixture_job"}\n'),
        ("analysis/modeling_plan.json", b'{"job_id":"fixture_job"}\n'),
        ("blender/scene.blend", b"fixture blend bytes\n"),
    ):
        _write(job_root, relative_path, content)

    def fake_run_blender(
        _script_name: str,
        args: list[str],
        blend_file: Path | None = None,
        **_kwargs,
    ) -> None:
        """Write one deterministic Blender 5 inventory to the declared output."""

        assert blend_file == job_root / "blender" / "scene.blend"
        output = Path(args[args.index("--output") + 1])
        output.write_text(
            '{"job_id":"fixture_job","blender_version":"5.0.1","objects":[]}\n',
            encoding="utf-8",
        )

    def fake_collect(
        root: Path,
        job_id: str,
        **kwargs,
    ) -> dict[str, object]:
        """Bind the test provenance to the isolated inventory supplied by the host."""

        inventory = kwargs["surface_detail_inventory_path"]
        assert Path(inventory).is_file()
        assert root == job_root
        assert job_id == "fixture_job"
        return {
            "schema_version": "0.4.0",
            "job_id": job_id,
            "fingerprint": "a" * 64,
        }

    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.incident_service.run_blender",
        fake_run_blender,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.incident_service.collect_build_provenance",
        fake_collect,
    )
    before = {
        path: (job_root / path).read_bytes()
        for path in (
            "analysis/scene_spec.json",
            "analysis/modeling_plan.json",
            "blender/scene.blend",
        )
    }
    result = publish_current_material_canonical_observations(
        job_root=job_root,
        identity=_identity(),
    )
    assert result.scene_inventory.path.startswith(
        "production/material_closure/fixture-session/canonical_observations/"
    )
    assert result.scene_inventory.path.endswith("/scene_inventory.json")
    assert len(result.scene_inventory.path.split("/")[-2]) == 24
    assert result.build_provenance.path.endswith("/build_provenance.json")
    assert {
        path: (job_root / path).read_bytes()
        for path in before
    } == before
    adopted = publish_current_material_canonical_observations(
        job_root=job_root,
        identity=_identity(),
    )
    assert adopted == result


def test_authoritative_model_publishers_exact_adopt_and_reject_conflicts(
    tmp_path: Path,
) -> None:
    """Apply central create-once behavior to AQ v2 and Material Closure publishers."""

    job_root = tmp_path / "job"
    job_root.mkdir()
    target = job_root / "production" / "material_closure" / "fixture-session" / "model.json"
    model = _identity()
    first = write_immutable_v2_model(job_root, target, model)
    adopted = write_immutable_v2_model(job_root, target, model)
    assert adopted == first
    original = target.read_bytes()
    conflicting = model.model_copy(update={"producer": "conflicting-producer"})
    with pytest.raises(FileExistsError, match="conflicting immutable artifact bytes"):
        write_immutable_v2_model(job_root, target, conflicting)
    assert target.read_bytes() == original

    closure_path = (
        "production/material_closure/fixture-session/closure-model.json"
    )
    published, published_artifact = publish_material_closure_model(
        job_root,
        closure_path,
        model,
        artifact_id="closure-model",
        kind="closure_model",
    )
    exact, exact_artifact = publish_material_closure_model(
        job_root,
        closure_path,
        model,
        artifact_id="closure-model",
        kind="closure_model",
    )
    assert exact == published
    assert exact_artifact == published_artifact
    with pytest.raises(FileExistsError, match="conflicting immutable material evidence"):
        publish_material_closure_model(
            job_root,
            closure_path,
            conflicting,
            artifact_id="closure-model",
            kind="closure_model",
        )
