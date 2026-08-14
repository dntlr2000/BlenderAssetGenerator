from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from codex_blender_modeler.autonomy_v2.material_phase_service import (
    _validate_canonical_snapshot_current,
)
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.codex_imagegen.models import CodexImageArtifact
from codex_blender_modeler.codex_imagegen.profile import (
    build_codex_builtin_image_provider_profile,
)
from codex_blender_modeler.material_closure.approval_policy import (
    classify_material_changes,
    material_approval_is_current,
)
from codex_blender_modeler.material_closure.collector import (
    MaterialClosureCollectionError,
    _collect_rollback_restoration_dependencies,
    _is_manifest_dependency_link_like,
    _repair_source_matches_authority,
    _repair_source_reuses_rollback_geometry,
    _require_repair_imagegen_root_listed,
    _resolve_manifest_owned_dependency_path,
    build_material_plan_absence_evidence,
    collect_material_dependency_closure,
    replay_host_graph_derived_closure,
    validate_material_plan_absence_evidence,
    validate_typed_imagegen_evidence_root,
)
from codex_blender_modeler.material_closure.graph_rebinding import (
    apply_material_graph_rebinding,
    rebound_material_graph_sha256,
)
from codex_blender_modeler.material_closure.models import (
    MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES,
    MATERIAL_REPAIR_REQUIRED_STEPS,
    ExactArtifact,
    IncidentStateDiscrepancyReport,
    JobSpecificRecoverySource,
    MaterialCanonicalMaterialPlanAbsence,
    MaterialCanonicalSnapshot,
    MaterialChange,
    MaterialClosureSourceBinding,
    MaterialClosureSourceBindingArtifact,
    MaterialDependencyClosure,
    MaterialDependencyEntry,
    MaterialGraphRebindingChange,
    MaterialGraphRebindingPlan,
    MaterialPlannedOutput,
    MaterialRepairSessionPlan,
    MaterialRepairSourceBinding,
    MaterialRetryApprovalAbsence,
    MaterialRetrySupersessionReceipt,
    MaterialRollbackRestorationObservation,
    material_plan_absence_context_sha256,
)
from codex_blender_modeler.material_closure.projector import (
    require_exact_immutable_projection,
)
from codex_blender_modeler.material_closure.repair_session import (
    material_repair_automatic_steps,
    validate_material_repair_preapproval_outcome,
    validate_material_repair_session,
)
from codex_blender_modeler.material_closure.state_consistency import (
    build_material_canonical_snapshot,
    canonical_build_provenance_artifact_fingerprint,
)

NOW = datetime(2026, 8, 14, tzinfo=UTC)
ZERO = "0" * 64
ONE = "1" * 64


def test_manifest_owned_channels_and_masks_resolve_from_manifest_parent(
    tmp_path: Path,
) -> None:
    """Resolve channel and mask files relative to their owning TextureManifest."""

    _write(tmp_path, "materials/crystal/channels/base.png", b"base")
    _write(tmp_path, "materials/crystal/masks/facets.png", b"mask")
    manifest = "materials/crystal/texture_manifest.json"
    assert (
        _resolve_manifest_owned_dependency_path(
            tmp_path,
            manifest_path=manifest,
            declared_path="channels/base.png",
        )
        == "materials/crystal/channels/base.png"
    )
    assert (
        _resolve_manifest_owned_dependency_path(
            tmp_path,
            manifest_path=manifest,
            declared_path="masks/facets.png",
        )
        == "materials/crystal/masks/facets.png"
    )


def test_manifest_owned_dependency_rejects_escape_and_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject traversal and every link in a TextureManifest-owned dependency path."""

    _write(tmp_path, "outside.png", b"outside")
    with pytest.raises(MaterialClosureCollectionError, match="INVALID_MANIFEST"):
        _resolve_manifest_owned_dependency_path(
            tmp_path,
            manifest_path="materials/crystal/texture_manifest.json",
            declared_path="../../outside.png",
        )
    link = tmp_path / "materials" / "crystal"
    link.mkdir(parents=True)
    (link / "base.png").write_bytes(b"base")
    original_is_link = os.path.islink

    def _reports_fixture_link(path: object) -> bool:
        """Report only the fixture directory as a link without host link privileges."""

        normalized = str(path).replace("\\", "/").rstrip("/")
        return normalized.endswith("/materials/crystal") or original_is_link(path)

    monkeypatch.setattr(os.path, "islink", _reports_fixture_link)
    with pytest.raises(MaterialClosureCollectionError, match="MANIFEST_DEPENDENCY_LINK"):
        _resolve_manifest_owned_dependency_path(
            tmp_path,
            manifest_path="materials/texture_manifest.json",
            declared_path="crystal/base.png",
        )


def test_manifest_dependency_link_check_detects_windows_reparse_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat a Windows junction/reparse attribute as link-like without following it."""

    fixture = tmp_path / "junction"
    fixture.mkdir()
    original_lstat = os.lstat

    def _reported_reparse(path: object) -> object:
        """Return fixture metadata with the Windows reparse bit set."""

        metadata = original_lstat(path)
        normalized = str(path).replace("\\", "/").rstrip("/")
        if not normalized.endswith("/junction"):
            return metadata
        return SimpleNamespace(
            st_file_attributes=getattr(
                stat,
                "FILE_ATTRIBUTE_REPARSE_POINT",
                0x400,
            )
        )

    monkeypatch.setattr(os, "lstat", _reported_reparse)
    assert _is_manifest_dependency_link_like(fixture)


def _bound() -> dict[str, object]:
    """Return one valid generic top-level material contract binding."""

    return {
        "job_id": "fixture_job",
        "workflow_id": "fixture_workflow",
        "dispatch_id": "fixture-dispatch",
        "session_id": "fixture-session",
        "producer": "material_closure_tests",
        "producer_version": "0.1.0",
        "created_at": NOW,
    }


def _write(root: Path, relative: str, payload: bytes) -> tuple[str, int]:
    """Create one fixture file and return its exact digest and size."""

    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _entry(
    root: Path,
    relative: str,
    role: str,
    *,
    rollback: bool = False,
) -> MaterialDependencyEntry:
    """Build one exact dependency entry from fixture bytes."""

    digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    return MaterialDependencyEntry(
        entry_id=f"entry-{role}",
        role=role,
        path=relative,
        sha256=digest,
        byte_size=(root / relative).stat().st_size,
        source_kind="rollback_evidence" if rollback else "canonical_artifact",
        required=True,
        producer="fixture",
        ownership="canonical",
    )


def _outputs(
    *,
    material_plan_sha256: str = ZERO,
    material_graph_sha256: str = ONE,
) -> list[MaterialPlannedOutput]:
    """Return the non-circular exact content and structural completion output set."""

    return [
        MaterialPlannedOutput(
            output_id="material-plan",
            output_kind="material_plan",
            path="production/request/material_plan.json",
            verification="exact_hash",
            sha256=material_plan_sha256,
            media_type="application/json",
        ),
        MaterialPlannedOutput(
            output_id="material-graph",
            output_kind="material_graph",
            path="production/request/material_graph.json",
            verification="exact_hash",
            sha256=material_graph_sha256,
            media_type="application/json",
        ),
        MaterialPlannedOutput(
            output_id="completion",
            output_kind="controller_completion",
            path="production/request/completion.json",
            verification="structural_binding",
            expected_schema_version="0.2.0",
            expected_field_bindings={"closure_sha256": ZERO},
            media_type="application/json",
        ),
    ]


def _source_binding_artifact(root: Path) -> ExactArtifact:
    """Create one exact low-level fixture source binding artifact."""

    digest, size = _write(root, "production/source_binding.json", b"{}\n")
    return ExactArtifact(
        artifact_id="source-binding",
        kind="material_closure_source_binding",
        path="production/source_binding.json",
        sha256=digest,
        byte_size=size,
        media_type="application/json",
    )


def test_closure_projection_is_complete_sorted_and_non_circular(tmp_path: Path) -> None:
    """Use one closure map everywhere and exclude completion bytes from exact outputs."""

    _write(tmp_path, "analysis/scene_spec.json", b"scene")
    _write(tmp_path, "history/rollback.json", b"rollback")
    _write(tmp_path, "staging/candidate.json", b"candidate")
    _write(tmp_path, "staging/source_graph.json", b"source graph")
    _write(tmp_path, "production/rebind/plan.json", b"plan")
    _write(tmp_path, "production/rebind/receipt.json", b"receipt")
    _write(tmp_path, "production/rebind/rebound.json", b"rebound")
    entries = [
        _entry(tmp_path, "history/rollback.json", "rollback_baseline", rollback=True),
        _entry(tmp_path, "analysis/scene_spec.json", "canonical_scene_spec"),
        _entry(tmp_path, "staging/candidate.json", "candidate_material_plan"),
        _entry(tmp_path, "staging/source_graph.json", "source_material_graph"),
        _entry(
            tmp_path,
            "production/rebind/plan.json",
            "material_graph_rebinding_plan",
        ),
        _entry(
            tmp_path,
            "production/rebind/receipt.json",
            "material_graph_rebinding_receipt",
        ),
        _entry(
            tmp_path,
            "production/rebind/rebound.json",
            "rebound_material_graph",
        ),
    ]
    existing_roles = {item.role for item in entries}
    for role in sorted(MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES - existing_roles):
        relative = f"common/{role}.json"
        _write(tmp_path, relative, role.encode("utf-8"))
        entries.append(_entry(tmp_path, relative, role))
    rollback = ExactArtifact(
        artifact_id="rollback",
        kind="rollback_baseline",
        path=entries[0].path,
        sha256=entries[0].sha256,
        byte_size=entries[0].byte_size,
        media_type="application/json",
    )
    closure = collect_material_dependency_closure(
        job_root=tmp_path,
        closure_id="closure",
        entries=entries,
        planned_outputs=_outputs(
            material_plan_sha256=entries[2].sha256,
            material_graph_sha256=entries[6].sha256,
        ),
        rollback_baseline=rollback,
        source_binding=_source_binding_artifact(tmp_path),
        required_roles={"canonical_scene_spec", "rollback_baseline"},
        **_bound(),
    )
    assert list(closure.project_immutable_input_map()) == sorted(item.path for item in entries)
    assert (
        closure.project_immutable_input_map()["production/rebind/rebound.json"] == entries[6].sha256
    )
    assert closure.project_planned_output_map() == {
        "production/request/material_graph.json": entries[6].sha256,
        "production/request/material_plan.json": entries[2].sha256,
    }
    with pytest.raises(ValueError, match="differs from closure"):
        require_exact_immutable_projection(
            closure,
            {"analysis/scene_spec.json": entries[1].sha256},
            owner="completion",
        )
    with pytest.raises(MaterialClosureCollectionError, match="SOURCE_BINDING"):
        replay_host_graph_derived_closure(tmp_path, closure)


def test_closure_rejects_stale_hash_case_collision_and_mutable_material_plan(
    tmp_path: Path,
) -> None:
    """Fail before closure publication for stale/colliding/in-place baseline inputs."""

    _write(tmp_path, "A.json", b"one")
    _write(tmp_path, "a.json", b"two")
    first = _entry(tmp_path, "A.json", "first")
    second = _entry(tmp_path, "a.json", "second")
    issues = MaterialClosureCollectionError
    with pytest.raises(issues, match="case-collides"):
        collect_material_dependency_closure(
            job_root=tmp_path,
            closure_id="closure",
            entries=[first, second],
            planned_outputs=_outputs(),
            rollback_baseline=ExactArtifact(
                artifact_id="rollback",
                kind="rollback_baseline",
                path=first.path,
                sha256=first.sha256,
                byte_size=first.byte_size,
                media_type="application/json",
            ),
            source_binding=_source_binding_artifact(tmp_path),
            **_bound(),
        )
    source_binding = _source_binding_artifact(tmp_path)
    payload = {
        **_bound(),
        "closure_id": "closure",
        "closure_sha256": ZERO,
        "collection_mode": "host_graph_derived",
        "source_binding": source_binding.model_dump(mode="json"),
        "entries": [
            {
                **first.model_dump(mode="json"),
                "entry_id": "material-baseline",
                "role": "material_plan_baseline_snapshot",
                "path": "analysis/material_plan.json",
            }
        ],
        "planned_outputs": [item.model_dump(mode="json") for item in _outputs()],
        "rollback_baseline": {
            "artifact_id": "rollback",
            "kind": "rollback_baseline",
            "path": "analysis/material_plan.json",
            "sha256": first.sha256,
            "byte_size": first.byte_size,
            "media_type": "application/json",
        },
    }
    with pytest.raises(ValidationError, match="observation and run-owned baseline"):
        MaterialDependencyClosure.model_validate(payload)


@pytest.mark.parametrize("missing_role", sorted(MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES))
def test_closure_rejects_each_missing_required_common_root(missing_role: str) -> None:
    """Fail closed when any typed AQ, canonical, geometry, or policy root is absent."""

    source_binding = ExactArtifact(
        artifact_id="source-binding",
        kind="material_closure_source_binding",
        path="production/material_closure/session/source_binding.json",
        sha256="8" * 64,
        byte_size=10,
        media_type="application/json",
    )
    core_roles = {
        "candidate_material_plan": "3",
        "source_material_graph": "4",
        "material_graph_rebinding_plan": "5",
        "material_graph_rebinding_receipt": "6",
        "rebound_material_graph": "7",
        "rollback_baseline": "9",
    }
    entries = [
        MaterialDependencyEntry(
            entry_id=f"entry-{role}",
            role=role,
            path=f"production/material_closure/session/{role}.json",
            sha256=digit * 64,
            byte_size=10,
            source_kind=(
                "rollback_evidence" if role == "rollback_baseline" else "staging_artifact"
            ),
            required=True,
            producer="tests",
            ownership="staging",
        )
        for role, digit in core_roles.items()
    ]
    for index, role in enumerate(sorted(MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES), start=10):
        if role == missing_role:
            continue
        entries.append(
            MaterialDependencyEntry(
                entry_id=f"root-{role}",
                role=role,
                path=f"production/material_closure/session/common/{role}.json",
                sha256=f"{index:x}"[-1] * 64,
                byte_size=10,
                source_kind="policy_evidence",
                required=True,
                producer="tests",
                ownership="staging",
            )
        )
    outputs = _outputs(
        material_plan_sha256="3" * 64,
        material_graph_sha256="7" * 64,
    )
    baseline = next(item for item in entries if item.role == "rollback_baseline")
    payload = {
        **_bound(),
        "closure_id": "closure",
        "closure_sha256": ZERO,
        "source_binding": source_binding.model_dump(mode="json"),
        "entries": [item.model_dump(mode="json") for item in entries],
        "planned_outputs": [item.model_dump(mode="json") for item in outputs],
        "rollback_baseline": {
            "artifact_id": "rollback",
            "kind": "rollback_baseline",
            "path": baseline.path,
            "sha256": baseline.sha256,
            "byte_size": baseline.byte_size,
            "media_type": "application/json",
        },
    }
    with pytest.raises(ValidationError, match="missing required common roots"):
        MaterialDependencyClosure.model_validate(payload)


def test_graph_rebinding_changes_only_declared_path_and_hash() -> None:
    """Preserve every semantic graph field while replacing exact provenance fields."""

    source = {
        "material_id": "material_main",
        "roughness": 0.3,
        "provenance": {
            "role": "texture",
            "path": "staging/old.png",
            "sha256": ZERO,
        },
    }
    rebound = json.loads(json.dumps(source))
    rebound["provenance"] = {
        "role": "texture",
        "path": "textures/current.png",
        "sha256": ONE,
    }
    change = MaterialGraphRebindingChange(
        dependency_role="texture",
        path_pointer="/provenance/path",
        hash_pointer="/provenance/sha256",
        before_path="staging/old.png",
        before_sha256=ZERO,
        after_path="textures/current.png",
        after_sha256=ONE,
    )
    artifact = ExactArtifact(
        artifact_id="artifact",
        kind="material_graph",
        path="materials/source.json",
        sha256=ZERO,
        byte_size=1,
        media_type="application/json",
    )
    plan = MaterialGraphRebindingPlan(
        plan_id="plan",
        source_binding=artifact.model_copy(
            update={
                "artifact_id": "source-binding",
                "kind": "material_closure_source_binding",
                "path": ("production/material_closure/fixture-session/source_binding.json"),
            }
        ),
        source_graph=artifact,
        candidate_material_plan=artifact.model_copy(
            update={"artifact_id": "candidate", "path": "materials/candidate.json"}
        ),
        output_path=(
            "production/material_closure/fixture-session/graph_rebindings/"
            "plan/rebound_material_graph.json"
        ),
        expected_rebound_sha256=rebound_material_graph_sha256(rebound),
        changes=[change],
        **_bound(),
    )
    observed, applied = apply_material_graph_rebinding(source, plan)
    assert observed == rebound
    assert observed["material_id"] == source["material_id"]
    assert observed["roughness"] == source["roughness"]
    assert applied == [change]


def test_graph_rebinding_allows_path_only_repair_with_same_exact_hash() -> None:
    """Permit a provenance path repair when immutable content bytes are unchanged."""

    source = {
        "provenance": {
            "role": "material_plan",
            "path": "staging/old.json",
            "sha256": ZERO,
        }
    }
    rebound = {
        "provenance": {
            "role": "material_plan",
            "path": "outputs/current.json",
            "sha256": ZERO,
        }
    }
    artifact = ExactArtifact(
        artifact_id="artifact",
        kind="material_graph",
        path="materials/source.json",
        sha256=ZERO,
        byte_size=1,
        media_type="application/json",
    )
    change = MaterialGraphRebindingChange(
        dependency_role="material_plan",
        path_pointer="/provenance/path",
        hash_pointer="/provenance/sha256",
        before_path="staging/old.json",
        before_sha256=ZERO,
        after_path="outputs/current.json",
        after_sha256=ZERO,
    )
    plan = MaterialGraphRebindingPlan(
        plan_id="path-only-plan",
        source_binding=artifact.model_copy(
            update={
                "artifact_id": "source-binding",
                "kind": "material_closure_source_binding",
                "path": ("production/material_closure/fixture-session/source_binding.json"),
            }
        ),
        source_graph=artifact,
        candidate_material_plan=artifact.model_copy(
            update={"artifact_id": "candidate", "path": "materials/candidate.json"}
        ),
        output_path=(
            "production/material_closure/fixture-session/graph_rebindings/"
            "path-only-plan/rebound_material_graph.json"
        ),
        expected_rebound_sha256=rebound_material_graph_sha256(rebound),
        changes=[change],
        **_bound(),
    )
    observed, applied = apply_material_graph_rebinding(source, plan)
    assert observed == rebound
    assert applied == [change]


def test_graph_rebinding_rejects_semantic_or_unpaired_pointer_edits() -> None:
    """Reject plans that disguise semantic edits as provenance rebinding."""

    common = {
        "dependency_role": "texture",
        "before_path": "staging/old.png",
        "before_sha256": ZERO,
        "after_path": "textures/current.png",
        "after_sha256": ONE,
    }
    with pytest.raises(ValidationError, match="only artifact path/sha256"):
        MaterialGraphRebindingChange(
            path_pointer="/material_id",
            hash_pointer="/provenance/sha256",
            **common,
        )
    with pytest.raises(ValidationError, match="share one artifact parent"):
        MaterialGraphRebindingChange(
            path_pointer="/provenance/inputs/0/path",
            hash_pointer="/provenance/inputs/1/sha256",
            **common,
        )


def test_approval_policy_is_fail_closed_and_exact() -> None:
    """Separate path-only repair, visual change, scope change, and stale approvals."""

    path_change = MaterialChange(
        change_id="path",
        category="path_only_rebinding",
        description="request-owned provenance path",
    )
    appearance = MaterialChange(
        change_id="appearance",
        category="texture_bytes",
        before_sha256=ZERO,
        after_sha256=ONE,
        description="texture changed",
    )
    scope = MaterialChange(
        change_id="scope",
        category="content_scope",
        description="scope changed",
    )
    assert classify_material_changes([path_change]) == "no_visual_change"
    assert classify_material_changes([path_change, appearance]) == "appearance_change"
    assert classify_material_changes([appearance, scope]) == "scope_change"
    bindings = {
        name: ZERO
        for name in {
            "candidate_material_plan_sha256",
            "rebound_material_graph_sha256",
            "closure_sha256",
            "preflight_report_sha256",
            "neutral_preview_sha256",
            "canonical_scene_spec_sha256",
            "canonical_blend_sha256",
            "uv_layout_fingerprint",
        }
    }
    assert material_approval_is_current(bindings, bindings)
    assert not material_approval_is_current(bindings, {**bindings, "closure_sha256": ONE})


def test_retry_supersession_requires_approval_or_exact_absence() -> None:
    """Represent approved and unapproved stale retries without synthesizing approval."""

    artifact = ExactArtifact(
        artifact_id="artifact",
        kind="evidence",
        path="history/evidence.json",
        sha256=ZERO,
        byte_size=1,
        media_type="application/json",
    )
    common = {
        **_bound(),
        "receipt_id": "receipt",
        "retry_plan": artifact,
        "current_state": artifact,
        "framework_failure_report": artifact,
        "supersession_reason": "framework stabilization replaces stale retry wiring",
    }
    approved = MaterialRetrySupersessionReceipt(**common, retry_approval=artifact)
    unapproved = MaterialRetrySupersessionReceipt(
        **common,
        retry_approval_absence=artifact,
    )
    assert approved.retry_approval is artifact
    assert unapproved.retry_approval_absence is artifact
    with pytest.raises(ValidationError, match="approval bytes or explicit absence"):
        MaterialRetrySupersessionReceipt(**common)
    with pytest.raises(ValidationError, match="approval bytes or explicit absence"):
        MaterialRetrySupersessionReceipt(
            **common,
            retry_approval=artifact,
            retry_approval_absence=artifact,
        )


def test_discrepancy_and_source_inventory_summaries_are_exact() -> None:
    """Reject false discrepancy summaries and incomplete dirty tracked-source provenance."""

    artifact = ExactArtifact(
        artifact_id="artifact",
        kind="state",
        path="history/state.json",
        sha256=ZERO,
        byte_size=1,
        media_type="application/json",
    )
    with pytest.raises(ValidationError, match="blocking summary"):
        IncidentStateDiscrepancyReport(
            report_id="report",
            observed_state=artifact,
            discrepancies=[
                {
                    "field": "state",
                    "reported_value": "running",
                    "observed_value": "blocked",
                    "significance": "blocking",
                }
            ],
            has_blocking_discrepancy=False,
            **_bound(),
        )
    with pytest.raises(ValidationError, match="difference flag"):
        JobSpecificRecoverySource(
            path="src/recovery.py",
            tracking_status="tracked",
            sha256=ONE,
            byte_size=10,
            index_sha256=ZERO,
            index_byte_size=10,
            working_tree_differs_from_index=False,
            job_specific_literals=["incident literal"],
            generic_capabilities=["dependency_collection"],
            disposition="retain_as_evidence",
        )


def test_strict_contract_rejects_unknown_fields_and_naive_time() -> None:
    """Preserve exact 0.1.0 dispatch and reject coercion or undeclared extensions."""

    artifact = ExactArtifact(
        artifact_id="artifact",
        kind="state",
        path="history/state.json",
        sha256=ZERO,
        byte_size=1,
        media_type="application/json",
    )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MaterialRetrySupersessionReceipt(
            **_bound(),
            receipt_id="receipt",
            retry_plan=artifact,
            retry_approval=artifact,
            current_state=artifact,
            framework_failure_report=artifact,
            supersession_reason="superseded",
            unknown=True,
        )
    with pytest.raises(ValidationError, match="timezone offset"):
        MaterialRetrySupersessionReceipt(
            **{**_bound(), "created_at": datetime(2026, 8, 14)},
            receipt_id="receipt",
            retry_plan=artifact,
            retry_approval=artifact,
            current_state=artifact,
            framework_failure_report=artifact,
            supersession_reason="superseded",
        )


def test_generic_material_plan_absence_is_canonical_and_hash_bound() -> None:
    """Use a generic current-state absence contract instead of profile-specific evidence."""

    state = ExactArtifact(
        artifact_id="state",
        kind="state",
        path="history/state.json",
        sha256=ZERO,
        byte_size=1,
        media_type="application/json",
    )
    scene = state.model_copy(
        update={
            "artifact_id": "scene",
            "kind": "scene_spec",
            "path": "analysis/scene_spec.json",
        }
    )
    blend = state.model_copy(
        update={
            "artifact_id": "blend",
            "kind": "canonical_blend",
            "path": "blender/scene.blend",
            "media_type": "application/x-blender",
        }
    )
    context = material_plan_absence_context_sha256(
        absence_id="absence",
        job_id="fixture_job",
        workflow_id="fixture_workflow",
        dispatch_id="fixture-dispatch",
        session_id="fixture-session",
        observation_state=state,
        canonical_scene_spec=scene,
        canonical_blend=blend,
        filesystem_parent_fingerprint=ONE,
    )
    absence = MaterialCanonicalMaterialPlanAbsence(
        absence_id="absence",
        observation_state=state,
        observation_context_sha256=context,
        canonical_scene_spec=scene,
        canonical_blend=blend,
        filesystem_parent_fingerprint=ONE,
        **_bound(),
    )
    assert absence.canonical_path == "analysis/material_plan.json"
    assert absence.observed_absent is True
    with pytest.raises(ValidationError):
        MaterialCanonicalMaterialPlanAbsence.model_validate(
            {**absence.model_dump(), "observed_absent": False}
        )


def test_canonical_material_contracts_reject_decoy_paths_and_kinds() -> None:
    """Reject canonical snapshots and absence evidence that bind decoy artifacts."""

    artifact = ExactArtifact(
        artifact_id="artifact",
        kind="current_state",
        path="production/state.json",
        sha256=ZERO,
        byte_size=1,
        media_type="application/json",
    )
    scene = artifact.model_copy(
        update={
            "artifact_id": "scene",
            "kind": "scene_spec",
            "path": "analysis/scene_spec.json",
        }
    )
    modeling = artifact.model_copy(
        update={
            "artifact_id": "modeling",
            "kind": "modeling_plan",
            "path": "analysis/modeling_plan.json",
        }
    )
    blend = artifact.model_copy(
        update={
            "artifact_id": "blend",
            "kind": "canonical_blend",
            "path": "blender/scene.blend",
            "media_type": "application/x-blender",
        }
    )
    material = artifact.model_copy(
        update={
            "artifact_id": "material",
            "kind": "material_plan",
            "path": "analysis/material_plan.json",
        }
    )
    build = artifact.model_copy(
        update={
            "artifact_id": "build",
            "kind": "build_provenance",
            "path": "reports/build_provenance.json",
        }
    )
    snapshot = MaterialCanonicalSnapshot(
        snapshot_id="snapshot",
        scene_spec=scene,
        modeling_plan=modeling,
        material_plan=material,
        blend=blend,
        build_provenance=build,
        build_provenance_fingerprint=build.sha256,
        **_bound(),
    )
    invalid_snapshot_artifacts = (
        (
            "scene_spec",
            scene.model_copy(update={"path": "history/scene_spec.json"}),
            "canonical SceneSpec path and kind",
        ),
        (
            "modeling_plan",
            modeling.model_copy(update={"kind": "scene_spec"}),
            "canonical ModelingPlan path and kind",
        ),
        (
            "blend",
            blend.model_copy(update={"path": "history/decoy.blend"}),
            "canonical Blend path and kind",
        ),
    )
    for field_name, invalid_artifact, message in invalid_snapshot_artifacts:
        payload = snapshot.model_dump(mode="python")
        payload[field_name] = invalid_artifact.model_dump(mode="python")
        with pytest.raises(ValidationError, match=message):
            MaterialCanonicalSnapshot.model_validate(payload)

    absence_context = material_plan_absence_context_sha256(
        absence_id="absence",
        job_id="fixture_job",
        workflow_id="fixture_workflow",
        dispatch_id="fixture-dispatch",
        session_id="fixture-session",
        observation_state=artifact,
        canonical_scene_spec=scene,
        canonical_blend=blend,
        filesystem_parent_fingerprint=ONE,
    )
    absence_payload = {
        **_bound(),
        "absence_id": "absence",
        "observation_state": artifact,
        "observation_context_sha256": absence_context,
        "canonical_scene_spec": scene,
        "canonical_blend": blend,
        "filesystem_parent_fingerprint": ONE,
    }
    for field_name, invalid_artifact, message in (
        (
            "canonical_scene_spec",
            scene.model_copy(update={"kind": "modeling_plan"}),
            "canonical SceneSpec path and kind",
        ),
        (
            "canonical_blend",
            blend.model_copy(update={"path": "history/decoy.blend"}),
            "canonical Blend path and kind",
        ),
    ):
        with pytest.raises(ValidationError, match=message):
            MaterialCanonicalMaterialPlanAbsence.model_validate(
                {**absence_payload, field_name: invalid_artifact}
            )


def test_material_plan_absence_builder_rejects_stale_or_mutated_context(
    tmp_path: Path,
) -> None:
    """Detect forged absence, stale state, parent mutation, and canonical appearance."""

    def make_observation(
        name: str,
    ) -> tuple[
        Path,
        MaterialCanonicalMaterialPlanAbsence,
        ExactArtifact,
    ]:
        """Create one independent exact absence observation fixture."""

        root = tmp_path / name
        scene_sha, scene_size = _write(
            root,
            "analysis/scene_spec.json",
            b'{"schema_version":"0.2.0"}',
        )
        state_sha, state_size = _write(
            root,
            "production/state.json",
            b'{"sequence":1}',
        )
        blend_sha, blend_size = _write(
            root,
            "blender/scene.blend",
            b"fixture-blend",
        )
        scene = ExactArtifact(
            artifact_id="scene",
            kind="scene_spec",
            path="analysis/scene_spec.json",
            sha256=scene_sha,
            byte_size=scene_size,
            media_type="application/json",
        )
        state = ExactArtifact(
            artifact_id="state",
            kind="current_state",
            path="production/state.json",
            sha256=state_sha,
            byte_size=state_size,
            media_type="application/json",
        )
        blend = ExactArtifact(
            artifact_id="blend",
            kind="canonical_blend",
            path="blender/scene.blend",
            sha256=blend_sha,
            byte_size=blend_size,
            media_type="application/x-blender",
        )
        evidence = build_material_plan_absence_evidence(
            job_root=root,
            absence_id="absence",
            observation_state=state,
            canonical_scene_spec=scene,
            canonical_blend=blend,
            **_bound(),
        )
        validate_material_plan_absence_evidence(root, evidence)
        return root, evidence, state

    stale_root, stale, _state = make_observation("stale")
    _write(stale_root, "production/state.json", b'{"sequence":2}')
    with pytest.raises(MaterialClosureCollectionError, match="observation_state bytes changed"):
        validate_material_plan_absence_evidence(stale_root, stale)

    parent_root, parent, _state = make_observation("parent")
    _write(parent_root, "analysis/new_observation.json", b"{}")
    with pytest.raises(MaterialClosureCollectionError, match="parent contents changed"):
        validate_material_plan_absence_evidence(parent_root, parent)

    present_root, present, _state = make_observation("present")
    _write(present_root, "analysis/material_plan.json", b"{}")
    with pytest.raises(MaterialClosureCollectionError, match="absence evidence is stale"):
        validate_material_plan_absence_evidence(present_root, present)

    with pytest.raises(ValidationError):
        MaterialCanonicalMaterialPlanAbsence.model_validate({"absent": True})


def test_host_canonical_snapshot_builder_revalidates_strict_absence(
    tmp_path: Path,
) -> None:
    """Build a host snapshot only from current exact canonical and absence bytes."""

    def artifact(
        relative: str,
        payload: bytes,
        *,
        artifact_id: str,
        kind: str,
        media_type: str = "application/json",
    ) -> ExactArtifact:
        """Write and bind one exact canonical snapshot fixture artifact."""

        digest, size = _write(tmp_path, relative, payload)
        return ExactArtifact(
            artifact_id=artifact_id,
            kind=kind,
            path=relative,
            sha256=digest,
            byte_size=size,
            media_type=media_type,
        )

    scene_payload = {
        "schema_version": "0.2.0",
        "job_id": "fixture_job",
        "mode": "concept",
        "nominal_scene_size": [1.0, 1.0, 1.0],
        "sources": [],
        "materials": [],
        "objects": [],
        "camera": {
            "projection": "PERSP",
            "location": [2.0, -2.0, 2.0],
            "target": [0.0, 0.0, 0.0],
            "focal_length_mm": 50.0,
            "ortho_scale": 2.0,
            "resolution": [64, 64],
        },
    }
    scene = artifact(
        "analysis/scene_spec.json",
        (json.dumps(scene_payload, sort_keys=True) + "\n").encode(),
        artifact_id="scene",
        kind="scene_spec",
    )
    modeling = artifact(
        "analysis/modeling_plan.json",
        b"{}",
        artifact_id="modeling",
        kind="modeling_plan",
    )
    blend = artifact(
        "blender/scene.blend",
        b"blend",
        artifact_id="blend",
        kind="canonical_blend",
        media_type="application/x-blender",
    )
    state = artifact(
        "production/state.json",
        b"{}",
        artifact_id="state",
        kind="current_state",
    )
    build_payload = collect_build_provenance(
        tmp_path,
        "fixture_job",
        validate_surface_details=False,
    )
    build = artifact(
        "reports/build_provenance.json",
        (json.dumps(build_payload, sort_keys=True) + "\n").encode(),
        artifact_id="build",
        kind="build_provenance",
    )
    absence_model = build_material_plan_absence_evidence(
        job_root=tmp_path,
        absence_id="absence",
        observation_state=state,
        canonical_scene_spec=scene,
        canonical_blend=blend,
        **_bound(),
    )
    absence_bytes = (
        json.dumps(absence_model.model_dump(mode="json"), sort_keys=True) + "\n"
    ).encode()
    absence = artifact(
        "production/material_plan_absence.json",
        absence_bytes,
        artifact_id="absence",
        kind="material_plan_absence",
    )
    snapshot = build_material_canonical_snapshot(
        job_root=tmp_path,
        snapshot_id="snapshot",
        scene_spec=scene,
        modeling_plan=modeling,
        blend=blend,
        build_provenance=build,
        material_plan_absence=absence,
        **_bound(),
    )
    assert snapshot.build_provenance_fingerprint == build.sha256
    assert snapshot.build_provenance_fingerprint != build_payload["fingerprint"]
    assert snapshot.material_plan_absence == absence
    _validate_canonical_snapshot_current(tmp_path, snapshot)
    decoy_blend = artifact(
        "history/decoy.blend",
        b"blend",
        artifact_id="decoy-blend",
        kind="canonical_blend",
        media_type="application/x-blender",
    )
    with pytest.raises(ValueError, match="canonical_blend path is not canonical"):
        build_material_canonical_snapshot(
            job_root=tmp_path,
            snapshot_id="snapshot-decoy",
            scene_spec=scene,
            modeling_plan=modeling,
            blend=decoy_blend,
            build_provenance=build,
            material_plan_absence=absence,
            **_bound(),
        )
    material_path = tmp_path / "analysis" / "material_plan.json"
    material_path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "job_id": "fixture_job",
                "stage": "authored",
                "materials": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        MaterialClosureCollectionError,
        match="STALE_CANONICAL_BUILD_PROVENANCE",
    ):
        canonical_build_provenance_artifact_fingerprint(
            job_root=tmp_path,
            build_provenance=build,
            expected_job_id="fixture_job",
        )
    material_path.unlink()
    _write(tmp_path, "blender/scene.blend", b"changed")
    with pytest.raises(MaterialClosureCollectionError, match="canonical_blend bytes changed"):
        build_material_canonical_snapshot(
            job_root=tmp_path,
            snapshot_id="snapshot-2",
            scene_spec=scene,
            modeling_plan=modeling,
            blend=blend,
            build_provenance=build,
            material_plan_absence=absence,
            **_bound(),
        )


def test_imagegen_source_binding_requires_all_typed_roots() -> None:
    """Prevent generic additional evidence from masking a missing ImageGen dependency."""

    with pytest.raises(ValidationError, match="ImageGen source binding is incomplete"):
        MaterialClosureSourceBinding(
            source_mode="imagegen",
            primary_reference_path="input/reference.png",
            reference_authority_path="history/reference_authority.json",
            imagegen_assignment_path="imagegen/assignment.json",
            additional_evidence_paths=["imagegen/adoption.json"],
        )
    procedural = MaterialClosureSourceBinding(
        source_mode="procedural",
        primary_reference_path="input/reference.png",
        reference_authority_path="history/reference_authority.json",
    )
    assert procedural.additional_evidence_paths == []


def test_retry_approval_absence_binds_retry_state_and_expected_path() -> None:
    """Reject an arbitrary JSON file as evidence that a retry approval never existed."""

    artifact = ExactArtifact(
        artifact_id="retry",
        kind="retry_plan",
        path="history/retry.json",
        sha256=ZERO,
        byte_size=1,
        media_type="application/json",
    )
    absence = MaterialRetryApprovalAbsence(
        absence_id="absence",
        retry_plan=artifact,
        expected_approval_path="history/approval.json",
        observation_state=artifact.model_copy(
            update={"artifact_id": "state", "kind": "state", "path": "history/state.json"}
        ),
        observation_context_sha256=ONE,
        **_bound(),
    )
    assert absence.observed_absent is True
    with pytest.raises(ValidationError, match="cannot alias"):
        MaterialRetryApprovalAbsence(
            **{
                **absence.model_dump(mode="json"),
                "created_at": absence.created_at,
                "expected_approval_path": "history/retry.json",
            }
        )


def test_material_repair_plan_stops_before_approval_consumption_or_writes() -> None:
    """Expose only a no-write preapproval prefix and require approval-pending outcome."""

    artifact = ExactArtifact(
        artifact_id="artifact",
        kind="source_binding",
        path="production/material_repair/fixture-session/source_binding.json",
        sha256=ZERO,
        byte_size=1,
        media_type="application/json",
    )
    source = MaterialRepairSourceBinding(
        binding_id="source-binding",
        source_session_id="historical-session",
        scene_spec=artifact.model_copy(
            update={"artifact_id": "scene", "kind": "scene_spec", "path": "analysis/scene.json"}
        ),
        modeling_plan=artifact.model_copy(
            update={
                "artifact_id": "modeling",
                "kind": "modeling_plan",
                "path": "analysis/modeling.json",
            }
        ),
        blend=artifact.model_copy(
            update={"artifact_id": "blend", "kind": "blend", "path": "scene/model.blend"}
        ),
        geometry_approval_or_validation=artifact.model_copy(
            update={
                "artifact_id": "geometry-approval",
                "kind": "geometry_approval",
                "path": "history/geometry_approval.json",
            }
        ),
        material_plan_absence=artifact.model_copy(
            update={
                "artifact_id": "material-absence",
                "kind": "material_plan_absence",
                "path": "history/material_absence.json",
            }
        ),
        primary_reference=artifact.model_copy(
            update={
                "artifact_id": "reference",
                "kind": "reference",
                "path": "input/reference.png",
                "media_type": "image/png",
            }
        ),
        uv_layout_fingerprint=ONE,
        target_subject="generic fixture",
        content_scope_sha256=ZERO,
        framework_failure_report=artifact.model_copy(
            update={
                "artifact_id": "failure",
                "kind": "framework_failure",
                "path": "history/framework_failure.json",
            }
        ),
        **_bound(),
    )
    plan = MaterialRepairSessionPlan(
        plan_id="repair-plan",
        repair_attempt_id="repair-attempt",
        source_session_id="historical-session",
        source_binding=artifact,
        source_binding_sha256=ZERO,
        preflight_request=artifact.model_copy(
            update={
                "artifact_id": "preflight-request",
                "kind": "material_preflight_request",
                "path": (
                    "production/material_closure/fixture-session/preflights/request/request.json"
                ),
            }
        ),
        required_steps=list(MATERIAL_REPAIR_REQUIRED_STEPS),
        **_bound(),
    )
    validate_material_repair_session(plan, source)
    assert material_repair_automatic_steps(plan)[-1] == "request_material_approval"
    validate_material_repair_preapproval_outcome(
        plan,
        attempt_status="approval_pending",
        approval_consumption_count=0,
        controller_invocation_count=0,
        canonical_write_count=0,
    )
    with pytest.raises(ValueError, match="unauthorized side effect"):
        validate_material_repair_preapproval_outcome(
            plan,
            attempt_status="approval_pending",
            approval_consumption_count=0,
            controller_invocation_count=1,
            canonical_write_count=0,
        )
    with pytest.raises(ValidationError, match="exact bounded order"):
        MaterialRepairSessionPlan.model_validate(
            {
                **plan.model_dump(),
                "required_steps": list(reversed(plan.required_steps)),
            }
        )


def test_rollback_restoration_observation_allows_only_exact_current_bytes() -> None:
    """Reject a third Blend hash even when a historical geometry receipt used older bytes."""

    base = ExactArtifact(
        artifact_id="base",
        kind="artifact",
        path="history/base.bin",
        sha256=ZERO,
        byte_size=10,
        media_type="application/octet-stream",
    )
    scene = base.model_copy(
        update={"artifact_id": "scene", "kind": "scene_spec", "path": "analysis/scene_spec.json"}
    )
    modeling = base.model_copy(
        update={
            "artifact_id": "modeling",
            "kind": "modeling_plan",
            "path": "analysis/modeling_plan.json",
        }
    )
    blend = base.model_copy(
        update={
            "artifact_id": "blend",
            "kind": "canonical_blend",
            "path": "blender/scene.blend",
            "sha256": ONE,
        }
    )
    observation = MaterialRollbackRestorationObservation(
        observation_id="rollback-observation",
        source_session_id="historical-session",
        source_rollback_receipt=base.model_copy(
            update={"artifact_id": "rollback", "kind": "rollback_receipt"}
        ),
        geometry_validation_receipt=base.model_copy(
            update={"artifact_id": "geometry", "kind": "geometry_validation"}
        ),
        restored_scene_spec_archive=scene.model_copy(
            update={"path": "history/rollback/scene_spec.json"}
        ),
        restored_modeling_plan_archive=modeling.model_copy(
            update={"path": "history/rollback/modeling_plan.json"}
        ),
        restored_blend_archive=blend.model_copy(update={"path": "history/rollback/scene.blend"}),
        current_scene_spec=scene,
        current_modeling_plan=modeling,
        current_blend=blend,
        **_bound(),
    )
    assert observation.status == "passed"
    with pytest.raises(ValidationError, match="archive bytes differ"):
        MaterialRollbackRestorationObservation.model_validate(
            {
                **observation.model_dump(mode="python"),
                "restored_blend_archive": observation.restored_blend_archive.model_copy(
                    update={"sha256": "2" * 64}
                ),
            }
        )


def test_rollback_restoration_dependencies_rehash_missing_and_tampered_bytes(
    tmp_path: Path,
) -> None:
    """Fail closed when any nested rollback proof is missing or no longer exact."""

    payloads = {
        "history/source_rollback.json": b"source-rollback",
        "production/aq/geometry_receipt.json": b"geometry-receipt",
        "history/restored/scene_spec.json": b"scene-spec",
        "analysis/scene_spec.json": b"scene-spec",
        "history/restored/modeling_plan.json": b"modeling-plan",
        "analysis/modeling_plan.json": b"modeling-plan",
        "history/restored/scene.blend": b"blend",
        "blender/scene.blend": b"blend",
    }
    artifacts: dict[str, ExactArtifact] = {}
    for index, (relative, payload) in enumerate(payloads.items()):
        digest, size = _write(tmp_path, relative, payload)
        artifacts[relative] = ExactArtifact(
            artifact_id=f"artifact-{index}",
            kind="fixture",
            path=relative,
            sha256=digest,
            byte_size=size,
            media_type="application/json",
        )
    observation = MaterialRollbackRestorationObservation(
        **_bound(),
        observation_id="rollback-observation",
        source_session_id="historical-session",
        source_rollback_receipt=artifacts["history/source_rollback.json"],
        geometry_validation_receipt=artifacts["production/aq/geometry_receipt.json"],
        restored_scene_spec_archive=artifacts["history/restored/scene_spec.json"],
        restored_modeling_plan_archive=artifacts["history/restored/modeling_plan.json"],
        restored_blend_archive=artifacts["history/restored/scene.blend"],
        current_scene_spec=artifacts["analysis/scene_spec.json"],
        current_modeling_plan=artifacts["analysis/modeling_plan.json"],
        current_blend=artifacts["blender/scene.blend"],
    )
    observation_path = (
        "production/material_repair/fixture_session/rollback_restoration_observation.json"
    )
    entries = {
        observation_path: MaterialDependencyEntry(
            entry_id="rollback-wrapper",
            role="material_repair_lineage_dependency",
            path=observation_path,
            sha256="f" * 64,
            byte_size=1,
            source_kind="policy_evidence",
            required=True,
            producer="test_fixture",
            ownership="canonical",
        )
    }

    (tmp_path / "history" / "source_rollback.json").unlink()
    with pytest.raises(MaterialClosureCollectionError, match="MISSING_DEPENDENCY"):
        _collect_rollback_restoration_dependencies(
            tmp_path,
            entries,
            observation=observation,
            observation_path=observation_path,
            producer="test_fixture",
        )

    (tmp_path / "history" / "source_rollback.json").write_bytes(b"source-rollback")
    (tmp_path / "production" / "aq" / "geometry_receipt.json").write_bytes(b"tampered")
    with pytest.raises(MaterialClosureCollectionError, match="STALE_EMBEDDED_HASH"):
        _collect_rollback_restoration_dependencies(
            tmp_path,
            entries,
            observation=observation,
            observation_path=observation_path,
            producer="test_fixture",
        )

    (tmp_path / "production" / "aq" / "geometry_receipt.json").write_bytes(b"geometry-receipt")
    _collect_rollback_restoration_dependencies(
        tmp_path,
        entries,
        observation=observation,
        observation_path=observation_path,
        producer="test_fixture",
    )
    assert set(payloads).issubset(entries)


def test_repair_source_must_preserve_old_root_request_content_scope() -> None:
    """Reject a repair lineage whose scope digest differs from its old authority."""

    binding = SimpleNamespace(
        source_evidence=SimpleNamespace(primary_reference_path="input/reference.png"),
        uv_layout_fingerprint=ONE,
    )
    authorization = SimpleNamespace(
        target_subject="fixture subject",
        original_request_sha256=ZERO,
    )
    source = SimpleNamespace(
        primary_reference=SimpleNamespace(path="input/reference.png"),
        uv_layout_fingerprint=ONE,
        target_subject="fixture subject",
        content_scope_sha256=ZERO,
    )
    assert _repair_source_matches_authority(source, authorization, binding)
    source.content_scope_sha256 = "2" * 64
    assert not _repair_source_matches_authority(source, authorization, binding)


def test_repair_source_reuses_exact_rollback_geometry_artifact_objects() -> None:
    """Reject same-path/hash geometry when its ExactArtifact identity was rewritten."""

    artifact = ExactArtifact(
        artifact_id="rollback-scene",
        kind="scene_spec",
        path="analysis/scene_spec.json",
        sha256=ZERO,
        byte_size=10,
        media_type="application/json",
    )
    observation = SimpleNamespace(
        source_session_id="old-session",
        geometry_validation_receipt=artifact,
        current_scene_spec=artifact,
        current_modeling_plan=artifact,
        current_blend=artifact,
    )
    source = SimpleNamespace(
        source_session_id="old-session",
        geometry_approval_or_validation=artifact,
        scene_spec=artifact,
        modeling_plan=artifact,
        blend=artifact,
    )
    assert _repair_source_reuses_rollback_geometry(source, observation)
    source.scene_spec = artifact.model_copy(update={"artifact_id": "fresh-scene"})
    assert not _repair_source_reuses_rollback_geometry(source, observation)


def test_repair_imagegen_root_must_be_exact_listed_without_mixed_bytes() -> None:
    """Reject an unlisted or same-path/different-hash historical ImageGen root."""

    entry = MaterialDependencyEntry(
        entry_id="imagegen-root",
        role="imagegen_assignment",
        path="production/imagegen/assignment.json",
        sha256=ZERO,
        byte_size=10,
        source_kind="generated_evidence",
        required=True,
        producer="test_fixture",
        ownership="staging",
    )
    exact = {(entry.path, entry.sha256, entry.byte_size)}
    _require_repair_imagegen_root_listed(entry, exact)
    with pytest.raises(MaterialClosureCollectionError, match="UNLISTED"):
        _require_repair_imagegen_root_listed(entry, set())
    with pytest.raises(MaterialClosureCollectionError, match="UNLISTED"):
        _require_repair_imagegen_root_listed(
            entry,
            {(entry.path, ONE, entry.byte_size)},
        )


def test_failure_budget_observation_is_typed_and_bounded() -> None:
    """Preserve exact incident AQ category usage without accepting loose or over-limit data."""

    from codex_blender_modeler.material_closure.models import MaterialAQBudgetObservation

    observation = MaterialAQBudgetObservation(
        blender_builds_used=13,
        blender_builds_limit=14,
        controller_invocations_used=6,
        controller_invocations_limit=16,
        canonical_promotions_used=1,
        canonical_promotions_limit=5,
        actions_used=9,
        actions_limit=72,
        quality_evaluations_used=0,
        quality_evaluations_limit=10,
    )
    assert observation.blender_builds_used == 13
    with pytest.raises(ValidationError, match="usage exceeds"):
        MaterialAQBudgetObservation.model_validate(
            {**observation.model_dump(), "blender_builds_used": 15}
        )


def test_typed_imagegen_root_rejects_right_shaped_wrong_schema(tmp_path: Path) -> None:
    """Reject forged generic JSON even when all provider-profile fields are present."""

    base = CodexImageArtifact(
        artifact_id="base-profile",
        kind="base-profile",
        path="production/base_profile.json",
        sha256=ZERO,
        byte_size=1,
        media_type="application/json",
    )
    profile = build_codex_builtin_image_provider_profile(
        contract_id="provider-contract",
        provider_profile_id="provider-profile",
        job_id="fixture_job",
        workflow_id="fixture_workflow",
        dispatch_id="fixture-dispatch",
        session_id="fixture-session",
        base_profile_artifact=base,
        created_at=NOW,
    )
    payload = profile.model_dump(mode="json")
    payload["schema_version"] = "9.9.9"
    profile_path = tmp_path / "production" / "provider.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(json.dumps(payload), encoding="utf-8")
    binding = MaterialClosureSourceBindingArtifact(
        binding_id="binding",
        scene_spec_path="analysis/scene_spec.json",
        modeling_plan_path="analysis/modeling_plan.json",
        root_authorization_path="production/aq/root_authorization.json",
        autonomy_plan_path="production/aq/plan.json",
        autonomy_profile_path="production/aq/profile.json",
        autonomy_budget_path="production/aq/budget.json",
        material_phase_tool_profile_path="production/aq/material_tool_profile.json",
        geometry_candidate_validation_receipt_path="aq2/geometry/receipt.json",
        canonical_build_provenance_path="reports/build_provenance.json",
        canonical_scene_inventory_path="reports/scene_inventory.json",
        material_plan_absence_evidence_path="history/material_absence.json",
        candidate_material_plan_path="staging/material_plan.json",
        material_graph_path="staging/material_graph.json",
        graph_rebinding_plan_path=(
            "production/material_closure/fixture-session/graph_rebindings/plan/plan.json"
        ),
        graph_rebinding_receipt_path=(
            "production/material_closure/fixture-session/graph_rebindings/plan/receipt.json"
        ),
        rebound_material_graph_path=(
            "production/material_closure/fixture-session/graph_rebindings/plan/"
            "rebound_material_graph.json"
        ),
        rollback_baseline_path="history/rollback.json",
        uv_layout_fingerprint=ZERO,
        source_evidence=MaterialClosureSourceBinding(
            source_mode="procedural",
            primary_reference_path="input/reference.png",
            reference_authority_path="history/reference_authority.json",
        ),
        **_bound(),
    )
    with pytest.raises(MaterialClosureCollectionError, match="strict schema dispatch"):
        validate_typed_imagegen_evidence_root(
            tmp_path,
            role="imagegen_provider_profile",
            path="production/provider.json",
            binding=binding,
        )
