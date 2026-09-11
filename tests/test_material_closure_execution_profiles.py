"""Keep full material closure compatible with strict AQ execution profile derivation."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest
import test_material_closure_service as fixture_support

from codex_blender_modeler.autonomy_v2.execution_profile_service import (
    publish_execution_phase_profile,
)
from codex_blender_modeler.autonomy_v2.models import AutonomyPlanV2
from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.material_closure.collector import (
    MaterialClosureCollectionError,
    collect_material_dependency_closure_from_roots,
)
from codex_blender_modeler.material_closure.graph_rebinding import serialize_rebound_material_graph
from codex_blender_modeler.material_closure.models import (
    ExactArtifact,
    MaterialDependencyClosure,
    MaterialPlannedOutput,
)
from codex_blender_modeler.production.controller_executor.models import (
    ControllerArtifact,
    ControllerExecutionRequest,
)


def _write(root: Path, relative: str, payload: object) -> None:
    """Write only this test's isolated fixture contracts with exact byte tracking."""
    fixture_support._write_json(root / relative, payload)


def _exact(root: Path, relative: str, artifact_id: str, kind: str) -> ExactArtifact:
    """Rehash one fixture-only derivative after an intentional contract change."""
    return fixture_support._artifact(root, relative, artifact_id=artifact_id, kind=kind)


def _geometry_execution(root: Path, binding: dict, plan: AutonomyPlanV2) -> dict:
    """Replace synthetic legacy fixture authority with a real host-derived request/profile pair."""
    profile, artifact = publish_execution_phase_profile(
        root,
        plan,
        profile_id="geometry_authoring",
        execution_id="exec-0002-geometry_authoring",
    )
    receipt_path = binding["geometry_candidate_validation_receipt_path"]
    receipt = json.loads((root / receipt_path).read_bytes())
    old_profile, old_request = receipt["phase_tool_profile"], receipt["controller_request"]
    reference = receipt["root_authorization"]
    assignment = ControllerArtifact(
        artifact_id=reference["artifact_id"],
        role="assignment",
        path=reference["path"],
        sha256=reference["sha256"],
        byte_size=reference["byte_size"],
    )
    controller_profile = ControllerArtifact(
        artifact_id=artifact.artifact_id,
        role="tool_profile",
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )
    request = ControllerExecutionRequest(
        contract_id="execution-geometry-request",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=plan.input_sha256,
        source_fingerprint=plan.source_fingerprint,
        producer="test_fixture",
        provenance=[assignment, controller_profile],
        created_at=plan.created_at,
        execution_id="exec-0002-geometry_authoring",
        controller_kind="fake_for_tests",
        assignment=assignment,
        immutable_inputs=[assignment],
        tool_profile=controller_profile,
        output_root=PurePosixPath(profile.allowed_output_paths[0]).parent.as_posix(),
        allowed_output_paths=profile.allowed_output_paths,
    )
    _write(root, old_request["path"], request)
    new_request = fixture_support._aq_artifact(
        root,
        old_request["path"],
        artifact_id=old_request["artifact_id"],
        kind=old_request["kind"],
    ).model_dump(mode="json")
    receipt["controller_request"] = new_request
    receipt["phase_tool_profile"] = artifact.model_dump(mode="json")
    replacements = {
        old_profile["path"]: receipt["phase_tool_profile"],
        old_request["path"]: new_request,
    }
    receipt["provenance"] = [replacements.get(item["path"], item) for item in receipt["provenance"]]
    _write(root, receipt_path, receipt)
    return receipt


def _material_execution(
    root: Path,
    original: MaterialDependencyClosure,
    binding: dict,
    plan: AutonomyPlanV2,
) -> tuple[ExactArtifact, list[MaterialPlannedOutput]]:
    """Rebind fixture material outputs and all companion hashes to one declared execution."""
    execution_id = "exec-0005-material_authoring"
    profile, artifact = publish_execution_phase_profile(
        root,
        plan,
        profile_id="material_authoring",
        execution_id=execution_id,
    )
    outputs = {PurePosixPath(path).name: path for path in profile.allowed_output_paths}
    binding["material_phase_tool_profile_path"] = artifact.path
    _write(root, original.source_binding.path, binding)
    source = _exact(
        root, original.source_binding.path, "source-binding-1", "material_closure_source_binding"
    )
    rebound = json.loads((root / binding["rebound_material_graph_path"]).read_bytes())
    rebound["provenance"]["inputs"][1]["path"] = outputs["material_plan.json"]
    (root / binding["rebound_material_graph_path"]).write_bytes(
        serialize_rebound_material_graph(rebound)
    )
    rebound_artifact = _exact(
        root, binding["rebound_material_graph_path"], "rebound-graph", "rebound_material_graph"
    )
    rebind_plan = json.loads((root / binding["graph_rebinding_plan_path"]).read_bytes())
    rebind_plan["source_binding"] = source.model_dump(mode="json")
    rebind_plan["changes"][0]["after_path"] = outputs["material_plan.json"]
    rebind_plan["expected_rebound_sha256"] = rebound_artifact.sha256
    _write(root, binding["graph_rebinding_plan_path"], rebind_plan)
    plan_artifact = _exact(
        root, binding["graph_rebinding_plan_path"], "rebind-1", "material_graph_rebinding_plan"
    )
    receipt = json.loads((root / binding["graph_rebinding_receipt_path"]).read_bytes())
    receipt.update(
        source_binding=source.model_dump(mode="json"),
        plan=plan_artifact.model_dump(mode="json"),
        rebound_graph=rebound_artifact.model_dump(mode="json"),
        applied_changes=rebind_plan["changes"],
    )
    _write(root, binding["graph_rebinding_receipt_path"], receipt)
    planned = []
    for item in original.planned_outputs:
        payload = item.model_dump(mode="json")
        payload["path"] = outputs[PurePosixPath(item.path).name]
        if item.output_kind == "material_graph":
            payload["sha256"] = rebound_artifact.sha256
        elif item.output_kind == "controller_completion":
            payload["expected_field_bindings"]["execution_id"] = execution_id
        planned.append(MaterialPlannedOutput.model_validate(payload))
    return source, planned


def _prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    material: bool = False,
    actual_blender: bool = False,
):
    """Create a complete isolated graph using real profile derivation and recursive collection."""
    build_profile = fixture_support.build_phase_tool_profile

    def with_material_outputs(**kwargs):
        """Give the fixture template the three current AQ material output roles."""
        if kwargs["profile_id"] == "material_authoring":
            kwargs["allowed_output_paths"] = [
                f"production/controller/output/{name}"
                for name in ("material_plan.json", "material_graph.json", "completion.json")
            ]
        return build_profile(**kwargs)

    monkeypatch.setattr(fixture_support, "build_phase_tool_profile", with_material_outputs)
    fixture = fixture_support._fixture(tmp_path, actual_canonical_blender=actual_blender)
    root = fixture.root
    _write(root, "production/preflight_template.json", fixture.request)
    original = MaterialDependencyClosure.model_validate_json(
        (root / "production/closure.json").read_bytes()
    )
    binding = json.loads((root / original.source_binding.path).read_bytes())
    plan = AutonomyPlanV2.model_validate_json((root / binding["autonomy_plan_path"]).read_bytes())
    geometry = _geometry_execution(root, binding, plan)
    source, outputs = original.source_binding, original.planned_outputs
    if material:
        source, outputs = _material_execution(root, original, binding, plan)
    return root, original, source, outputs, binding, geometry


def _collect(prepared) -> MaterialDependencyClosure:
    """Invoke the full production collector without invoking Blender or a controller."""
    root, original, source, outputs, _binding, _geometry = prepared
    return collect_material_dependency_closure_from_roots(
        job_root=root,
        source_binding=source,
        closure_id="execution-profile-closure",
        job_id=original.job_id,
        workflow_id=original.workflow_id,
        dispatch_id=original.dispatch_id,
        session_id=original.session_id,
        producer=original.producer,
        producer_version=original.producer_version,
        created_at=original.created_at,
        planned_outputs=outputs,
    )


@pytest.mark.parametrize("material", [False, True])
def test_closure_accepts_exact_execution_profiles_without_canonical_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    material: bool,
) -> None:
    """Pass both phases while preserving canonical bytes and deterministic replay."""
    prepared = _prepared(tmp_path, monkeypatch, material=material)
    root = prepared[0]
    before = {
        path: sha256_file(root / path)
        for path in (
            "analysis/scene_spec.json",
            "analysis/modeling_plan.json",
            "blender/scene.blend",
        )
    }
    closure = _collect(prepared)
    assert closure == _collect(prepared)
    assert any("controller_executions/exec-0002" in item.path for item in closure.entries)
    if material:
        assert any("controller_executions/exec-0005" in item.path for item in closure.entries)
    assert before == {path: sha256_file(root / path) for path in before}
    assert not (root / "analysis/material_plan.json").exists()


@pytest.mark.parametrize("mutation", ["tools", "outputs", "provenance", "session"])
def test_execution_profile_tampering_is_rejected_before_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    """Reject byte-current profiles whose semantics are not the exact authority derivation."""
    prepared = _prepared(tmp_path, monkeypatch)
    root, _original, _source, _outputs, binding, geometry = prepared
    profile_path = geometry["phase_tool_profile"]["path"]
    payload = json.loads((root / profile_path).read_bytes())
    if mutation == "tools":
        payload["allowed_tools"] = []
    elif mutation == "outputs":
        payload["allowed_output_paths"] = ["production/escaped/output.json"]
    elif mutation == "provenance":
        payload["provenance"][0]["sha256"] = "a" * 64
    else:
        payload["session_id"] = "another-session"
    _write(root, profile_path, payload)
    current = fixture_support._aq_artifact(
        root, profile_path, artifact_id="changed-profile", kind="controller_phase_tool_profile"
    ).model_dump(mode="json")
    geometry["phase_tool_profile"] = current
    geometry["provenance"] = [
        current if item["path"] == profile_path else item for item in geometry["provenance"]
    ]
    _write(root, binding["geometry_candidate_validation_receipt_path"], geometry)
    with pytest.raises(
        MaterialClosureCollectionError, match="GEOMETRY_TOOL_PROFILE_BINDING_MISMATCH"
    ):
        _collect(prepared)


def test_execution_profile_cannot_be_mixed_with_another_geometry_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject individually valid evidence from different execution rounds."""
    prepared = _prepared(tmp_path, monkeypatch)
    root, _original, _source, _outputs, binding, geometry = prepared
    request_path = geometry["controller_request"]["path"]
    request = json.loads((root / request_path).read_bytes())
    request["execution_id"] = "exec-0007-geometry_authoring"
    _write(root, request_path, request)
    current = fixture_support._aq_artifact(
        root, request_path, artifact_id="changed-request", kind="controller_execution_request"
    ).model_dump(mode="json")
    geometry["controller_request"] = current
    geometry["provenance"] = [
        current if item["path"] == request_path else item for item in geometry["provenance"]
    ]
    _write(root, binding["geometry_candidate_validation_receipt_path"], geometry)
    with pytest.raises(
        MaterialClosureCollectionError, match="GEOMETRY_TOOL_PROFILE_BINDING_MISMATCH"
    ):
        _collect(prepared)


@pytest.mark.parametrize("mutation", ["output_path", "completion_execution"])
def test_material_execution_profile_requires_its_exact_output_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    """Reject stale completion or output paths before spending any execution budget."""
    prepared = _prepared(tmp_path, monkeypatch, material=True)
    for index, item in enumerate(prepared[3]):
        if item.output_kind == "controller_completion":
            payload = item.model_dump(mode="json")
            if mutation == "output_path":
                payload["path"] = "production/controller/another-execution/completion.json"
            else:
                payload["expected_field_bindings"]["execution_id"] = "exec-0008-material_authoring"
            prepared[3][index] = MaterialPlannedOutput.model_validate(payload)
    with pytest.raises(
        MaterialClosureCollectionError, match="MATERIAL_PHASE_TOOL_PROFILE_BINDING_MISMATCH"
    ):
        _collect(prepared)
