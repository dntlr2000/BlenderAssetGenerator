"""Focused ControllerExecutor 0.1.0 isolation and fail-closed tests."""

from __future__ import annotations

import json
import os
import tomllib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest

from codex_blender_modeler.blender_artifacts import (
    native_io_path,
    sha256_file,
    stable_json_digest,
    write_json_atomic,
)
from codex_blender_modeler.production.controller_executor import (
    ControllerArtifact,
    ControllerExecutionRequest,
    DesktopInSessionController,
    FakeControllerForTests,
    OptionalCodexAppServerController,
    PhaseToolProfile,
    build_phase_tool_profile,
    controller_capability_catalog,
    execute_controller_request,
    validate_controller_execution_result,
    write_controller_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, value: bytes) -> None:
    """Write one non-empty fixture file below a temporary job root."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    with open(native_io_path(path), "wb") as handle:
        handle.write(value)


def _artifact(root: Path, relative: str, artifact_id: str, role: str) -> ControllerArtifact:
    """Bind one existing temporary fixture by exact path, size, and SHA-256."""

    path = root / relative
    return ControllerArtifact(
        artifact_id=artifact_id,
        role=role,
        path=relative,
        sha256=sha256_file(path),
        byte_size=os.path.getsize(native_io_path(path)),
    )


def _workspace_output_paths(
    request_path: Path,
    request: ControllerExecutionRequest,
) -> list[Path]:
    """Resolve controller-visible output leaves without exposing canonical staging paths."""

    output_root = PurePosixPath(request.output_root)
    return [
        request_path.parent
        / "controller_workspace"
        / "outputs"
        / Path(*PurePosixPath(relative).relative_to(output_root).parts)
        for relative in request.allowed_output_paths
    ]


def _symlink_or_skip(link: Path, target: Path) -> None:
    """Create one file symlink or skip when the Windows host denies link creation."""

    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")


class _InterruptAfterOutputController:
    """Simulate a process interruption after complete isolated output publication."""

    controller_kind = "fake_for_tests"

    def __init__(self) -> None:
        """Initialize the exact invocation counter used by crash-adoption assertions."""

        self.calls = 0

    def execute(
        self,
        *,
        assignment: Path,
        immutable_inputs: tuple[Path, ...],
        allowed_output_paths: tuple[Path, ...],
        tool_profile: PhaseToolProfile,
        timeout_seconds: int,
    ) -> str:
        """Write every allowed output and interrupt before a host completion receipt."""

        del assignment, immutable_inputs, tool_profile, timeout_seconds
        self.calls += 1
        for path in allowed_output_paths:
            _write(path, f"interrupted:{path.name}\n".encode())
        raise KeyboardInterrupt("injected process interruption")


def _request_bundle(
    tmp_path: Path,
    *,
    controller_kind: str = "fake_for_tests",
    output_names: tuple[str, ...] = ("scene_spec.json", "modeling_plan.json"),
    expected: dict[str, str] | None = None,
) -> tuple[Path, Path, ControllerExecutionRequest]:
    """Create a complete job-contained request and exact phase profile fixture."""

    root = tmp_path / "workspaces" / "controller_case"
    os.makedirs(native_io_path(root), exist_ok=False)
    _write(root / "input" / "reference.png", b"reference-fixture")
    _write(root / "assignments" / "assignment.json", b'{"step":"geometry"}\n')
    source = _artifact(root, "assignments/assignment.json", "assignment", "assignment")
    reference = _artifact(root, "input/reference.png", "reference", "reference")
    output_root = "production/autonomy/aq-case/controller_outputs/exec-001"
    output_paths = [f"{output_root}/{name}" for name in output_names]
    now = datetime(2026, 8, 11, tzinfo=UTC)
    profile = build_phase_tool_profile(
        profile_id="geometry_authoring",
        job_id="controller_case",
        workflow_id="wf-controller-case",
        dispatch_id="dispatch-controller-case",
        session_id="aq-controller-case",
        source_artifact=source,
        allowed_input_roles=["assignment", "reference"],
        allowed_output_paths=output_paths,
        created_at=now,
    )
    profile_path = root / "production" / "autonomy" / "aq-case" / "tool_profile.json"
    write_controller_contract(profile_path, profile)
    profile_artifact = _artifact(
        root,
        profile_path.relative_to(root).as_posix(),
        "geometry-tool-profile",
        "tool_profile",
    )
    request_payload = {
        "assignment": source.sha256,
        "reference": reference.sha256,
        "profile": profile_artifact.sha256,
    }
    expected_map = {
        f"{output_root}/{key}": value for key, value in (expected or {}).items()
    }
    request = ControllerExecutionRequest(
        contract_id="controller-request-001",
        job_id="controller_case",
        workflow_id="wf-controller-case",
        dispatch_id="dispatch-controller-case",
        session_id="aq-controller-case",
        input_sha256=stable_json_digest(request_payload),
        source_fingerprint=stable_json_digest(
            {**request_payload, "outputs": output_paths}
        ),
        producer="tests.controller_executor",
        provenance=[source, reference, profile_artifact],
        created_at=now,
        execution_id="exec-001",
        controller_kind=controller_kind,
        assignment=source,
        immutable_inputs=[source, reference],
        tool_profile=profile_artifact,
        output_root=output_root,
        allowed_output_paths=output_paths,
        expected_output_sha256=expected_map,
        timeout_seconds=30,
    )
    request_path = root / "production" / "autonomy" / "aq-case" / "request.json"
    write_controller_contract(request_path, request)
    return root, request_path, request


def test_fake_controller_publishes_only_exact_isolated_outputs(tmp_path: Path) -> None:
    """A successful fake execution returns exact outputs and never canonical authority."""

    root, request_path, request = _request_bundle(tmp_path)
    payloads = {
        Path(relative).name: json.dumps({"path": relative}).encode()
        for relative in request.allowed_output_paths
    }
    controller = FakeControllerForTests(payloads=payloads)
    result = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=controller,
    )

    assert result.status == "completed"
    assert [item.path for item in result.outputs] == request.allowed_output_paths
    assert result.canonical_unchanged is True
    assert result.extra_output_count == 0
    assert result.partial_output_count == 0
    assert controller.calls == 1
    assert controller.last_assignment is not None
    assert "controller_workspace" in controller.last_assignment.parts
    assert controller.last_assignment != root / request.assignment.path
    assert all(
        "controller_workspace" in path.parts
        for path in controller.last_allowed_output_paths
    )
    for relative in request.allowed_output_paths:
        assert (root / relative).read_bytes() == payloads[Path(relative).name]
    evidence = request_path.parent / "controller_executor_evidence"
    assert {path.name for path in evidence.iterdir()} == {
        "started.json",
        "invocation.json",
        "completed.json",
        "published.json",
    }
    assert not (root / "analysis" / "scene_spec.json").exists()


def test_completed_request_is_adopted_without_a_second_controller_call(
    tmp_path: Path,
) -> None:
    """An exact completed request is idempotent and emits explicit adoption evidence."""

    root, request_path, _request = _request_bundle(tmp_path)
    controller = FakeControllerForTests()
    first = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=controller,
    )
    second = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=controller,
    )

    assert first.status == second.status == "completed"
    assert controller.calls == 1
    assert [item.sha256 for item in second.outputs] == [
        item.sha256 for item in first.outputs
    ]
    assert (
        request_path.parent / "controller_executor_evidence" / "adopted.json"
    ).is_file()


def test_public_result_validator_reconstructs_exact_stored_bytes(
    tmp_path: Path,
) -> None:
    """A stored result passes only after full idempotent executor reconstruction."""

    root, request_path, _request = _request_bundle(tmp_path)
    controller = FakeControllerForTests()
    result = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=controller,
    )
    result_path = request_path.parent / "result.json"
    write_json_atomic(result_path, result.model_dump(mode="json"))

    validated = validate_controller_execution_result(
        job_root=root,
        request_path=request_path,
        result_path=result_path,
        controller=controller,
    )

    assert validated == result
    assert controller.calls == 1
    assert (
        request_path.parent / "controller_executor_evidence" / "adopted.json"
    ).is_file()


def test_public_result_validator_rejects_reformatted_or_stale_lifecycle(
    tmp_path: Path,
) -> None:
    """Semantic JSON and tampered lifecycle receipts cannot replace exact host bytes."""

    root, request_path, _request = _request_bundle(tmp_path)
    controller = FakeControllerForTests()
    result = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=controller,
    )
    result_path = request_path.parent / "result.json"
    _write(
        result_path,
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False).encode("utf-8"),
    )
    with pytest.raises(ValueError, match="stored controller result differs"):
        validate_controller_execution_result(
            job_root=root,
            request_path=request_path,
            result_path=result_path,
            controller=controller,
        )

    write_json_atomic(result_path, result.model_dump(mode="json"))
    published_path = request_path.parent / "controller_executor_evidence" / "published.json"
    published = json.loads(published_path.read_text(encoding="utf-8"))
    published["request_sha256"] = "0" * 64
    write_json_atomic(published_path, published)
    with pytest.raises(ValueError, match="published receipt is stale"):
        validate_controller_execution_result(
            job_root=root,
            request_path=request_path,
            result_path=result_path,
            controller=controller,
        )


def test_fake_controller_accepts_unambiguous_legacy_relative_payload_key(
    tmp_path: Path,
) -> None:
    """The test adapter preserves prior relative-key fixtures without seeing job_root."""

    root, request_path, request = _request_bundle(
        tmp_path,
        output_names=("scene_spec.json",),
    )
    expected = b"legacy-relative-payload\n"
    result = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=FakeControllerForTests(
            payloads={request.allowed_output_paths[0]: expected}
        ),
    )

    assert result.status == "completed"
    assert (root / request.allowed_output_paths[0]).read_bytes() == expected


def test_complete_outputs_from_an_interrupted_call_are_safely_adopted(
    tmp_path: Path,
) -> None:
    """A start-bound complete workspace survives interruption without reinvocation."""

    root, request_path, _request = _request_bundle(tmp_path)
    interrupted = _InterruptAfterOutputController()
    with pytest.raises(KeyboardInterrupt, match="injected process interruption"):
        execute_controller_request(
            job_root=root,
            request_path=request_path,
            controller=interrupted,
        )
    evidence = request_path.parent / "controller_executor_evidence"
    assert (evidence / "started.json").is_file()
    assert not (evidence / "invocation.json").exists()

    replacement = FakeControllerForTests()
    adopted = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=replacement,
    )
    assert adopted.status == "completed"
    assert interrupted.calls == 1
    assert replacement.calls == 0
    assert (evidence / "completed.json").is_file()
    assert (evidence / "adopted.json").is_file()


def test_stale_workspace_output_before_start_is_rejected_without_execution(
    tmp_path: Path,
) -> None:
    """Declared bytes predating the exact start receipt can never be adopted as fresh."""

    root, request_path, request = _request_bundle(tmp_path)
    _write(_workspace_output_paths(request_path, request)[0], b"stale\n")
    controller = FakeControllerForTests()

    with pytest.raises(ValueError, match="stale output"):
        execute_controller_request(
            job_root=root,
            request_path=request_path,
            controller=controller,
        )
    assert controller.calls == 0


def test_preexisting_final_staging_output_is_rejected_without_execution(
    tmp_path: Path,
) -> None:
    """Canonical staging bytes without completion evidence cannot seed a new run."""

    root, request_path, request = _request_bundle(tmp_path)
    _write(root / request.allowed_output_paths[0], b"stale staging\n")
    controller = FakeControllerForTests()

    with pytest.raises(ValueError, match="before exact completion"):
        execute_controller_request(
            job_root=root,
            request_path=request_path,
            controller=controller,
        )
    assert controller.calls == 0


def test_unexpected_workspace_file_is_rejected_without_execution(
    tmp_path: Path,
) -> None:
    """An undeclared workspace member fails closed before controller invocation."""

    root, request_path, _request = _request_bundle(tmp_path)
    _write(
        request_path.parent / "controller_workspace" / "outputs" / "unexpected.txt",
        b"unexpected\n",
    )
    controller = FakeControllerForTests()

    with pytest.raises(ValueError, match="unexpected files"):
        execute_controller_request(
            job_root=root,
            request_path=request_path,
            controller=controller,
        )
    assert controller.calls == 0


def test_controller_write_outside_workspace_is_detected(tmp_path: Path) -> None:
    """A controller-created sibling file aborts before any staged output is published."""

    root, request_path, request = _request_bundle(tmp_path)
    controller = FakeControllerForTests(behavior="escape")

    with pytest.raises(PermissionError, match="outside its workspace"):
        execute_controller_request(
            job_root=root,
            request_path=request_path,
            controller=controller,
        )
    assert controller.calls == 1
    assert not any((root / relative).exists() for relative in request.allowed_output_paths)


def test_controller_cannot_mutate_immutable_workspace_snapshot(tmp_path: Path) -> None:
    """Input snapshot mutation fails closed while canonical assignment bytes stay exact."""

    root, request_path, request = _request_bundle(tmp_path)
    canonical_before = (root / request.assignment.path).read_bytes()
    controller = FakeControllerForTests(behavior="mutate_input")

    with pytest.raises(ValueError, match="changed an immutable snapshot"):
        execute_controller_request(
            job_root=root,
            request_path=request_path,
            controller=controller,
        )
    assert (root / request.assignment.path).read_bytes() == canonical_before


def test_workspace_output_leaf_symlink_is_rejected_before_execution(
    tmp_path: Path,
) -> None:
    """A declared workspace leaf cannot redirect validation through a symbolic link."""

    root, request_path, request = _request_bundle(tmp_path)
    target = tmp_path / "workspace-link-target.json"
    _write(target, b"linked\n")
    _symlink_or_skip(_workspace_output_paths(request_path, request)[0], target)
    controller = FakeControllerForTests()

    with pytest.raises(ValueError, match="symlink|junction"):
        execute_controller_request(
            job_root=root,
            request_path=request_path,
            controller=controller,
        )
    assert controller.calls == 0


def test_final_staging_leaf_symlink_is_rejected_before_execution(
    tmp_path: Path,
) -> None:
    """The host publisher refuses a linked final staging leaf before controller work."""

    root, request_path, request = _request_bundle(tmp_path)
    target = tmp_path / "staging-link-target.json"
    _write(target, b"linked\n")
    staging = root / request.allowed_output_paths[0]
    _symlink_or_skip(staging, target)
    controller = FakeControllerForTests()

    with pytest.raises(ValueError, match="symlink|junction"):
        execute_controller_request(
            job_root=root,
            request_path=request_path,
            controller=controller,
        )
    assert controller.calls == 0
    assert os.path.islink(staging)


def test_published_staging_output_is_never_repaired_after_tampering(
    tmp_path: Path,
) -> None:
    """A missing already-published leaf fails closed instead of rewriting history."""

    root, request_path, request = _request_bundle(tmp_path)
    controller = FakeControllerForTests()
    result = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=controller,
    )
    assert result.status == "completed"
    removed = root / request.allowed_output_paths[0]
    removed.unlink()

    with pytest.raises(ValueError, match="published.*missing"):
        execute_controller_request(
            job_root=root,
            request_path=request_path,
            controller=controller,
        )
    assert controller.calls == 1
    assert not removed.exists()


def test_controller_workspace_supports_windows_extended_length_paths(
    tmp_path: Path,
) -> None:
    """Snapshot, receipt, and publication IO remains valid beyond legacy MAX_PATH."""

    deep_root = tmp_path.joinpath(
        *(f"controller-long-path-segment-{index:02d}" for index in range(6))
    )
    root, request_path, request = _request_bundle(deep_root)
    assert len(str(request_path.parent / "controller_workspace")) > 260

    result = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=FakeControllerForTests(),
    )

    assert result.status == "completed"
    assert all(
        os.path.isfile(native_io_path(root / relative))
        for relative in request.allowed_output_paths
    )


@pytest.mark.parametrize(
    ("behavior", "expected_status", "retryable"),
    [
        ("timeout", "timeout", True),
        ("failed", "failed", False),
        ("partial", "rejected", False),
        ("extra", "rejected", False),
        ("crash", "failed", False),
    ],
)
def test_fake_controller_negative_modes_fail_closed(
    tmp_path: Path,
    behavior: str,
    expected_status: str,
    retryable: bool,
) -> None:
    """Timeout, partial, extra, and crash fixtures never yield adopted outputs."""

    root, request_path, _ = _request_bundle(tmp_path)
    result = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=FakeControllerForTests(behavior=behavior),
    )

    assert result.status == expected_status
    assert result.retryable is retryable
    assert result.outputs == []


def test_desktop_controller_waits_then_adopts_exact_outputs(tmp_path: Path) -> None:
    """Desktop mode reports waiting until the current task supplies every allowed file."""

    root, request_path, request = _request_bundle(
        tmp_path,
        controller_kind="desktop_in_session",
    )
    waiting = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=DesktopInSessionController(),
    )
    assert waiting.status == "waiting_for_output"
    assert waiting.outputs == []

    for path in _workspace_output_paths(request_path, request):
        _write(path, f"desktop:{path.name}\n".encode())
    adopted = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=DesktopInSessionController(),
    )
    assert adopted.status == "completed"
    assert len(adopted.outputs) == len(request.allowed_output_paths)
    assert (
        request_path.parent / "controller_executor_evidence" / "adopted.json"
    ).is_file()


def test_controller_input_tamper_is_rejected_before_execution(tmp_path: Path) -> None:
    """Changed immutable input bytes stop the controller before any output is adopted."""

    root, request_path, _ = _request_bundle(tmp_path)
    (root / "input" / "reference.png").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="hash changed|size changed"):
        execute_controller_request(
            job_root=root,
            request_path=request_path,
            controller=FakeControllerForTests(),
        )


def test_expected_output_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    """A schema-valid but stale controller output cannot satisfy an exact hash binding."""

    root, request_path, request = _request_bundle(
        tmp_path,
        output_names=("scene_spec.json",),
        expected={"scene_spec.json": "0" * 64},
    )
    result = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=FakeControllerForTests(
            payloads={Path(request.allowed_output_paths[0]).name: b"different\n"}
        ),
    )

    assert result.status == "rejected"
    assert result.outputs == []
    assert any("output hash" in item for item in result.diagnostics)


def test_request_rejects_output_outside_isolated_root(tmp_path: Path) -> None:
    """The strict request model refuses an allowed output that targets canonical analysis."""

    _, _, request = _request_bundle(tmp_path)
    payload = request.model_dump(mode="json")
    payload["allowed_output_paths"] = ["analysis/scene_spec.json"]

    with pytest.raises(ValueError, match="below output_root"):
        ControllerExecutionRequest.model_validate_json(json.dumps(payload))


def test_optional_app_server_remains_unavailable_without_official_adapter(
    tmp_path: Path,
) -> None:
    """Repository code never guesses an App Server API or claims it created a task."""

    root, request_path, _ = _request_bundle(
        tmp_path,
        controller_kind="optional_codex_app_server",
    )
    controller = OptionalCodexAppServerController()
    capability = controller.capability_status()
    result = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=controller,
    )

    assert capability.status == "unavailable"
    assert capability.repository_can_spawn_codex_task is False
    assert result.status == "failed"
    assert result.outputs == []


def test_phase_profiles_use_only_project_enabled_mcp_tools() -> None:
    """Keep MCP phase tools enabled and isolate the one built-in Codex capability."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        enabled = set(tomllib.load(handle)["mcp_servers"]["blender_modeler"]["enabled_tools"])
    catalog = controller_capability_catalog()
    for profile_id, profile in catalog["phase_profiles"].items():
        allowed = set(profile["allowed_tools"])
        if profile_id == "codex_imagegen":
            assert allowed == {"imagegen"}
            assert allowed.isdisjoint(enabled)
            assert profile["network_access"] == "denied"
        else:
            assert allowed <= enabled
    controllers = {item["controller_kind"]: item for item in catalog["controllers"]}
    assert controllers["desktop_in_session"]["repository_can_spawn_codex_task"] is False
    assert controllers["optional_codex_app_server"]["status"] == "unavailable"
