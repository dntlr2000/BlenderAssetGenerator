from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..blender_artifacts import write_json_atomic
from ..blender_runner import run_blender
from ..constraints import evaluate_job_constraints
from ..orchestration.locks import workflow_write_lock
from ..validation import load_scene_spec
from ..workspace import (
    archive_scene_spec,
    current_job_write_lock_owner,
    job_dir,
    replace_scene_spec_if_current,
    sha256_file,
)
from .approval import create_revision_approval, load_revision_approval
from .convergence import evaluate_convergence
from .guard import apply_approved_revision, compile_revision_plan
from .models import RevisionCandidates

_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$")


def _utc_now() -> str:
    """Return one machine-readable UTC timestamp for service reports."""

    return datetime.now(UTC).isoformat()


def _validate_render_selection(render_engine: str, render_device: str) -> None:
    """Apply the same Blender render-selection contract used by the public tools."""

    if render_engine not in {"eevee", "cycles"}:
        raise ValueError("render_engine must be eevee or cycles")
    if render_device not in {"auto", "cpu", "gpu"}:
        raise ValueError("render_device must be auto, cpu, or gpu")
    if render_engine == "eevee" and render_device != "auto":
        raise ValueError("render_device must be auto when render_engine is eevee")


def _resolve_run(job_id: str, run_id: str) -> tuple[Path, Path]:
    """Resolve one existing QA run without allowing traversal outside its job."""

    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("QA run_id must match [a-zA-Z0-9][a-zA-Z0-9._-]{0,95}")
    root = job_dir(job_id)
    if not (root / "job.json").is_file():
        raise FileNotFoundError(f"Job does not exist: {job_id}")
    run_dir = root / "qa" / "runs" / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"QA run does not exist: {run_dir}")
    return root, run_dir


def _load_candidates(path: Path, job_id: str) -> RevisionCandidates:
    """Load a candidate bundle and require that it belongs to the requested job."""

    candidates = RevisionCandidates.model_validate_json(path.read_text(encoding="utf-8"))
    if candidates.job_id != job_id:
        raise ValueError(
            f"Revision candidates belong to {candidates.job_id!r}, not {job_id!r}"
        )
    return candidates


def _input_hashes(root: Path) -> dict[str, str]:
    """Hash every immutable input file so an apply cycle can detect accidental mutation."""

    input_dir = root / "input"
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Job input directory is missing: {input_dir}")
    return {
        path.relative_to(input_dir).as_posix(): sha256_file(path)
        for path in sorted(input_dir.rglob("*"))
        if path.is_file()
    }


def _require_input_hashes(root: Path, expected: dict[str, str]) -> None:
    """Reject a revision cycle if immutable user evidence changed at any point."""

    actual = _input_hashes(root)
    if actual != expected:
        raise ValueError("immutable job input hashes changed during approved revision apply")


def _build_job(root: Path, render_engine: str, render_device: str) -> dict[str, Any]:
    """Rebuild one canonical SceneSpec into its derived Blender scene."""

    spec = root / "analysis" / "scene_spec.json"
    parsed = load_scene_spec(spec)
    output = root / "blender" / "scene.blend"
    result = run_blender(
        "build_scene.py",
        [
            "--spec",
            str(spec),
            "--output",
            str(output),
            "--render-engine",
            render_engine,
            "--render-device",
            render_device,
        ],
    )
    if not output.is_file():
        raise FileNotFoundError(f"Blender build did not create its scene: {output}")
    return {
        "blend": str(output),
        "objects_requested": len(parsed.objects),
        "log_tail": result.stdout[-2000:],
    }


def _render_job(root: Path, render_engine: str, render_device: str) -> dict[str, Any]:
    """Render the fixed comparison camera after an approved canonical revision."""

    blend = root / "blender" / "scene.blend"
    output = root / "renders" / "preview.png"
    result = run_blender(
        "render_preview.py",
        [
            "--output",
            str(output),
            "--render-engine",
            render_engine,
            "--render-device",
            render_device,
        ],
        blend_file=blend,
    )
    if not output.is_file():
        raise FileNotFoundError(f"Blender render did not create its preview: {output}")
    return {"preview": str(output), "log_tail": result.stdout[-2000:]}


def _inspect_job(root: Path) -> dict[str, Any]:
    """Refresh the machine-readable Blender scene inventory for constraints and QA."""

    blend = root / "blender" / "scene.blend"
    output = root / "reports" / "scene_inventory.json"
    run_blender("inspect_scene.py", ["--output", str(output)], blend_file=blend)
    return json.loads(output.read_text(encoding="utf-8"))


def _validate_job(root: Path) -> dict[str, Any]:
    """Validate the generated Blender scene against the current canonical SceneSpec."""

    spec = root / "analysis" / "scene_spec.json"
    blend = root / "blender" / "scene.blend"
    output = root / "reports" / "validation.json"
    load_scene_spec(spec)
    run_blender(
        "validate_scene.py",
        ["--spec", str(spec), "--output", str(output)],
        blend_file=blend,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    if not report.get("ok", False):
        raise ValueError(f"revised Blender scene validation failed: {output}")
    return report


def _constraint_failure_count(solution: Any) -> int:
    """Count failed and missing measured constraints as convergence regressions."""

    return int(solution.failed) + int(solution.missing)


def _constraint_state(solution: Any | None) -> dict[str, Any]:
    """Serialize measured results so convergence can compare every stable constraint ID."""

    if solution is None:
        return {"failures": 0, "results": []}
    return {
        "failures": _constraint_failure_count(solution),
        "results": [result.model_dump(mode="json") for result in solution.results],
    }


def _baseline_constraint_state(
    job_id: str,
    root: Path,
    render_engine: str,
    render_device: str,
) -> dict[str, Any]:
    """Capture per-ID constraints from a freshly rebuilt pre-revision canonical scene."""

    if not (root / "constraints" / "constraints.json").is_file():
        return _constraint_state(None)
    _build_job(root, render_engine, render_device)
    _inspect_job(root)
    return _constraint_state(evaluate_job_constraints(job_id))


def _run_job_pipeline(
    job_id: str,
    root: Path,
    render_engine: str,
    render_device: str,
) -> dict[str, Any]:
    """Run one bounded build, preview, inspect, validate, and optional constraint cycle."""

    build = _build_job(root, render_engine, render_device)
    preview = _render_job(root, render_engine, render_device)
    inventory = _inspect_job(root)
    validation = _validate_job(root)
    constraint_path = root / "constraints" / "constraints.json"
    constraint_solution = (
        evaluate_job_constraints(job_id) if constraint_path.is_file() else None
    )
    constraint_state = _constraint_state(constraint_solution)
    return {
        "build": build,
        "preview": preview,
        "inventory_path": str(root / "reports" / "scene_inventory.json"),
        "object_count": len(inventory.get("objects", [])),
        "validation": validation,
        "validation_path": str(root / "reports" / "validation.json"),
        "constraint_solution_path": (
            str(root / "reports" / "constraint_solution.json")
            if constraint_solution is not None
            else None
        ),
        "constraint_failures": constraint_state["failures"],
        "constraint_results": constraint_state["results"],
    }


def _run_post_visual_qa(
    job_id: str,
    render_engine: str,
    render_device: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run one optionally named direct-reference fixed-camera QA pass after an edit."""

    from ..qa import run_job_visual_qa

    return run_job_visual_qa(
        job_id,
        render_engine=render_engine,
        render_device=render_device,
        run_id=run_id,
        include_generated_target=False,
    )


def _snapshot_latest(root: Path) -> bytes | None:
    """Capture the pre-apply QA latest pointer so rollback can restore canonical context."""

    latest = root / "qa" / "latest.json"
    return latest.read_bytes() if latest.is_file() else None


def _restore_latest(root: Path, snapshot: bytes | None) -> None:
    """Restore or remove only the derived QA latest pointer after model rollback."""

    latest = root / "qa" / "latest.json"
    if snapshot is None:
        if latest.exists():
            latest.unlink()
        return
    temporary = latest.with_suffix(".json.rollback.tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_bytes(snapshot)
    os.replace(temporary, latest)


def _semantic_change_sets(
    scene_spec_path: Path,
    candidates: RevisionCandidates,
    approved_candidate_ids: list[str],
) -> tuple[list[str], list[str]]:
    """Derive changed and preserved semantic IDs for convergence reporting."""

    raw = json.loads(scene_spec_path.read_text(encoding="utf-8"))
    by_id = {candidate.id: candidate for candidate in candidates.candidates}
    changed = sorted(
        {
            str(by_id[candidate_id].target_id)
            for candidate_id in approved_candidate_ids
            if by_id[candidate_id].target_id is not None
        }
    )
    all_ids = {
        str(record["id"])
        for field in ("objects", "materials")
        for record in raw.get(field, [])
    }
    preserved = sorted((all_ids - set(changed)) | set(candidates.locked_ids))
    return changed, preserved


def _replace_with_archive(
    job_id: str,
    scene_spec_path: Path,
    archived: Path,
    *,
    expected_archive_sha256: str,
    expected_current_sha256: str,
    lock_owner_id: str,
) -> str:
    """Restore only a verified archive over the exact caller-owned canonical hash."""

    if (
        not archived.is_file()
        or sha256_file(archived) != expected_archive_sha256
    ):
        raise RuntimeError(
            "archived SceneSpec changed before rollback; "
            "refusing to replace canonical content"
        )
    replacement = replace_scene_spec_if_current(
        job_id,
        archived,
        expected_current_sha256=expected_current_sha256,
        expected_candidate_sha256=expected_archive_sha256,
        lock_owner_id=lock_owner_id,
        archive_current=False,
    )
    return str(replacement["result_scene_spec_sha256"])


def _rollback_job(
    *,
    job_id: str,
    root: Path,
    run_dir: Path,
    scene_spec_path: Path,
    archived: Path,
    expected_spec_sha256: str,
    expected_current_spec_sha256: str,
    expected_input_hashes: dict[str, str],
    latest_snapshot: bytes | None,
    render_engine: str,
    render_device: str,
    reason: str,
    lock_owner_id: str | None = None,
    rebuild_baseline: bool = True,
) -> dict[str, Any]:
    """Restore the archived SceneSpec and rebuild derived state when it may be stale."""

    resolved_lock_owner = lock_owner_id or current_job_write_lock_owner(job_id)
    restored_hash = _replace_with_archive(
        job_id,
        scene_spec_path,
        archived,
        expected_archive_sha256=expected_spec_sha256,
        expected_current_sha256=expected_current_spec_sha256,
        lock_owner_id=resolved_lock_owner,
    )
    rebuild_error: str | None = None
    rebuild: dict[str, Any] | None = None
    if rebuild_baseline:
        try:
            rebuild = _run_job_pipeline(job_id, root, render_engine, render_device)
        except Exception as exc:  # pragma: no cover - public error handling covers this
            rebuild_error = f"{type(exc).__name__}: {exc}"
    _restore_latest(root, latest_snapshot)
    input_unchanged = _input_hashes(root) == expected_input_hashes
    rollback_ok = (
        restored_hash == expected_spec_sha256
        and input_unchanged
        and rebuild_error is None
    )
    report = {
        "schema_version": "0.6.0",
        "job_id": job_id,
        "run_id": run_dir.name,
        "status": "restored" if rollback_ok else "restore_incomplete",
        "rollback_ok": rollback_ok,
        "reason": reason,
        "archived_scene_spec": str(archived),
        "restored_scene_spec_sha256": restored_hash,
        "expected_scene_spec_sha256": expected_spec_sha256,
        "input_hashes_unchanged": input_unchanged,
        "rebuild": rebuild,
        "rebuild_requested": rebuild_baseline,
        "rebuild_error": rebuild_error,
        "completed_at": _utc_now(),
    }
    write_json_atomic(run_dir / "rollback_report.json", report)
    if not rollback_ok:
        raise RuntimeError(
            "approved revision rollback did not fully restore and rebuild the baseline; "
            f"see {run_dir / 'rollback_report.json'}"
        )
    return report


def compile_job_qa_revision(
    job_id: str,
    run_id: str,
    *,
    selected_candidate_ids: list[str],
    request: str,
) -> dict[str, Any]:
    """Compile selected safe candidates from one QA run without creating approval."""

    if not selected_candidate_ids:
        raise ValueError("at least one revision candidate must be selected")
    root, run_dir = _resolve_run(job_id, run_id)
    candidates_path = run_dir / "revision_candidates.json"
    scene_spec_path = root / "analysis" / "scene_spec.json"
    plan_path = run_dir / "revision_plan.json"
    if plan_path.exists():
        raise FileExistsError(f"RevisionPlan already exists for this QA run: {plan_path}")
    candidates = _load_candidates(candidates_path, job_id)
    plan = compile_revision_plan(
        candidates_path=candidates_path,
        scene_spec_path=scene_spec_path,
        selected_candidate_ids=selected_candidate_ids,
        request=request,
        output_path=plan_path,
    )
    report = {
        "schema_version": "0.6.0",
        "job_id": job_id,
        "run_id": run_id,
        "status": "compiled_unapproved",
        "selected_candidate_ids": selected_candidate_ids,
        "base_spec_sha256": candidates.base_spec_sha256,
        "candidates_sha256": sha256_file(candidates_path),
        "plan_sha256": sha256_file(plan_path),
        "operation_count": len(plan.operations),
        "plan": str(plan_path),
        "approval_created": False,
        "created_at": _utc_now(),
    }
    write_json_atomic(run_dir / "revision_compile_report.json", report)
    return report


def approve_job_qa_revision(
    job_id: str,
    run_id: str,
    *,
    approved_candidate_ids: list[str],
) -> dict[str, Any]:
    """Create one explicit, hash-bound user approval for an existing compiled plan."""

    if not approved_candidate_ids:
        raise ValueError("at least one revision candidate must be explicitly approved")
    _root, run_dir = _resolve_run(job_id, run_id)
    candidates_path = run_dir / "revision_candidates.json"
    plan_path = run_dir / "revision_plan.json"
    approval_path = run_dir / "revision_approval.json"
    if not plan_path.is_file():
        raise FileNotFoundError(f"Compiled RevisionPlan is missing: {plan_path}")
    if approval_path.exists():
        raise FileExistsError(f"Revision approval already exists: {approval_path}")
    _load_candidates(candidates_path, job_id)
    approval = create_revision_approval(
        candidates_path=candidates_path,
        plan_path=plan_path,
        approved_candidate_ids=approved_candidate_ids,
        output_path=approval_path,
    )
    return {
        "schema_version": "0.6.0",
        "job_id": job_id,
        "run_id": run_id,
        "status": "approved_once",
        "approval_id": approval.approval_id,
        "approved_candidate_ids": approval.approved_candidate_ids,
        "approval": str(approval_path),
        "one_time": approval.one_time,
        "used": approval.used,
    }


def _manual_revision_lock_id(run_id: str) -> str:
    """Map one QA run to a portable lock owner ID without exposing its full name."""

    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    return f"qa-revision-{digest}"


def apply_job_approved_revision(
    job_id: str,
    run_id: str,
    *,
    run_pipeline: bool = True,
    render_engine: str = "eevee",
    render_device: str = "auto",
    minimum_improvement: float = 0.001,
) -> dict[str, Any]:
    """Serialize one manual apply against every canonical job writer."""

    _validate_render_selection(render_engine, render_device)
    if minimum_improvement < 0:
        raise ValueError("minimum_improvement must be non-negative")
    root, run_dir = _resolve_run(job_id, run_id)
    lock_owner_id = _manual_revision_lock_id(run_id)
    with workflow_write_lock(
        root,
        job_id,
        lock_owner_id,
        ttl_seconds=86400,
    ):
        return _apply_job_approved_revision_under_job_lock(
            job_id,
            run_id,
            root=root,
            run_dir=run_dir,
            run_pipeline=run_pipeline,
            render_engine=render_engine,
            render_device=render_device,
            minimum_improvement=minimum_improvement,
            lock_owner_id=lock_owner_id,
        )


def _apply_job_approved_revision_under_job_lock(
    job_id: str,
    run_id: str,
    *,
    root: Path,
    run_dir: Path,
    run_pipeline: bool,
    render_engine: str,
    render_device: str,
    minimum_improvement: float,
    lock_owner_id: str,
) -> dict[str, Any]:
    """Apply and verify one approval while the public caller owns the job write lock."""

    candidates_path = run_dir / "revision_candidates.json"
    plan_path = run_dir / "revision_plan.json"
    approval_path = run_dir / "revision_approval.json"
    before_report_path = run_dir / "visual_qa_report.json"
    for required in (candidates_path, plan_path, approval_path, before_report_path):
        if not required.is_file():
            raise FileNotFoundError(f"Approved revision artifact is missing: {required}")

    candidates = _load_candidates(candidates_path, job_id)
    if sha256_file(before_report_path) != candidates.source_report_sha256:
        raise ValueError("source visual QA report changed after candidates were generated")
    approval = load_revision_approval(approval_path)
    if approval.job_id != job_id:
        raise ValueError(f"Revision approval belongs to another job: {approval.job_id}")
    if approval.used:
        raise ValueError(f"revision approval was already used: {approval.approval_id}")

    scene_spec_path = root / "analysis" / "scene_spec.json"
    before_spec_sha256 = sha256_file(scene_spec_path)
    expected_input_hashes = _input_hashes(root)
    changed_ids, preserved_ids = _semantic_change_sets(
        scene_spec_path,
        candidates,
        approval.approved_candidate_ids,
    )
    latest_snapshot = _snapshot_latest(root)
    before_constraint_state = (
        _baseline_constraint_state(
            job_id,
            root,
            render_engine,
            render_device,
        )
        if run_pipeline
        else _constraint_state(None)
    )
    _require_input_hashes(root, expected_input_hashes)

    application_path = run_dir / "application_report.json"
    application: dict[str, Any] = {
        "schema_version": "0.6.0",
        "job_id": job_id,
        "run_id": run_id,
        "status": "applying",
        "max_iterations": 1,
        "pipeline_requested": run_pipeline,
        "approval_id": approval.approval_id,
        "approved_candidate_ids": approval.approved_candidate_ids,
        "base_spec_sha256": before_spec_sha256,
        "input_hashes_before": expected_input_hashes,
        "changed_ids": changed_ids,
        "preserved_ids": preserved_ids,
        "started_at": _utc_now(),
    }
    write_json_atomic(application_path, application)

    archived: Path | None = None
    canonical_replaced_once = False
    result_spec_sha256: str | None = None
    next_spec_path = run_dir / "scene_spec.approved.next.json"
    try:
        (root / "history").mkdir(parents=True, exist_ok=True)
        archived = archive_scene_spec(job_id)
        if archived is None:
            raise FileNotFoundError(f"Canonical SceneSpec is missing: {scene_spec_path}")
        if next_spec_path.exists():
            raise FileExistsError(
                f"Pending approved SceneSpec already exists: {next_spec_path}"
            )
        low_level = apply_approved_revision(
            scene_spec_path=scene_spec_path,
            candidates_path=candidates_path,
            plan_path=plan_path,
            approval_path=approval_path,
            output_path=next_spec_path,
        )
        _require_input_hashes(root, expected_input_hashes)
        result_spec_sha256 = sha256_file(next_spec_path)
        replace_scene_spec_if_current(
            job_id,
            next_spec_path,
            expected_current_sha256=before_spec_sha256,
            expected_candidate_sha256=result_spec_sha256,
            lock_owner_id=lock_owner_id,
            archive_current=False,
        )
        next_spec_path.unlink(missing_ok=True)
        canonical_replaced_once = True
        application.update(
            {
                "status": (
                    "applied_unverified" if not run_pipeline else "applied_pending_qa"
                ),
                "approval_used": True,
                "archived_scene_spec": str(archived),
                "result_spec_sha256": result_spec_sha256,
                "changes": low_level.get("changes", []),
            }
        )
        write_json_atomic(application_path, application)

        if not run_pipeline:
            application.update(
                {
                    "completed_at": _utc_now(),
                    "input_hashes_after": _input_hashes(root),
                }
            )
            write_json_atomic(application_path, application)
            return {
                "ok": True,
                "status": "applied_unverified",
                "application_report": str(application_path),
                "convergence_report": None,
                "rollback_report": None,
            }

        pipeline = _run_job_pipeline(job_id, root, render_engine, render_device)
        _require_input_hashes(root, expected_input_hashes)
        post_qa = _run_post_visual_qa(job_id, render_engine, render_device)
        after_report_path = Path(post_qa["visual_qa_report"])
        convergence = evaluate_convergence(
            before_report_path=before_report_path,
            after_report_path=after_report_path,
            changed_ids=changed_ids,
            preserved_ids=preserved_ids,
            before_failed_constraints=int(before_constraint_state["failures"]),
            after_failed_constraints=int(pipeline["constraint_failures"]),
            before_constraint_results=list(before_constraint_state["results"]),
            after_constraint_results=list(pipeline.get("constraint_results", [])),
            minimum_improvement=minimum_improvement,
        )
        convergence_path = run_dir / "convergence.json"
        write_json_atomic(convergence_path, convergence.model_dump(mode="json"))
        _require_input_hashes(root, expected_input_hashes)
        if convergence.accepted:
            application.update(
                {
                    "status": "accepted",
                    "pipeline": pipeline,
                    "post_qa": post_qa,
                    "convergence_report": str(convergence_path),
                    "input_hashes_after": _input_hashes(root),
                    "completed_at": _utc_now(),
                }
            )
            write_json_atomic(application_path, application)
            return {
                "ok": True,
                "status": "accepted",
                "application_report": str(application_path),
                "convergence_report": str(convergence_path),
                "rollback_report": None,
                "post_qa": post_qa,
            }

        rollback = _rollback_job(
            job_id=job_id,
            root=root,
            run_dir=run_dir,
            scene_spec_path=scene_spec_path,
            archived=archived,
            expected_spec_sha256=before_spec_sha256,
            expected_current_spec_sha256=result_spec_sha256,
            expected_input_hashes=expected_input_hashes,
            latest_snapshot=latest_snapshot,
            render_engine=render_engine,
            render_device=render_device,
            reason="convergence did not improve direct reference score without regressions",
            lock_owner_id=lock_owner_id,
        )
        application.update(
            {
                "status": "rolled_back",
                "pipeline": pipeline,
                "post_qa": post_qa,
                "convergence_report": str(convergence_path),
                "rollback_report": str(run_dir / "rollback_report.json"),
                "input_hashes_after": _input_hashes(root),
                "completed_at": _utc_now(),
            }
        )
        write_json_atomic(application_path, application)
        return {
            "ok": True,
            "status": "rolled_back",
            "application_report": str(application_path),
            "convergence_report": str(convergence_path),
            "rollback_report": str(run_dir / "rollback_report.json"),
            "rollback": rollback,
            "post_qa": post_qa,
        }
    except Exception as exc:
        rollback: dict[str, Any] | None = None
        canonical_matches_baseline = (
            scene_spec_path.is_file()
            and sha256_file(scene_spec_path) == before_spec_sha256
        )
        if archived is not None and not canonical_matches_baseline:
            try:
                rollback = _rollback_job(
                    job_id=job_id,
                    root=root,
                    run_dir=run_dir,
                    scene_spec_path=scene_spec_path,
                    archived=archived,
                    expected_spec_sha256=before_spec_sha256,
                    expected_current_spec_sha256=result_spec_sha256 or "",
                    expected_input_hashes=expected_input_hashes,
                    latest_snapshot=latest_snapshot,
                    render_engine=render_engine,
                    render_device=render_device,
                    reason=(
                        "approved apply failed after canonical replacement: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    lock_owner_id=lock_owner_id,
                    rebuild_baseline=run_pipeline,
                )
                canonical_matches_baseline = True
            except Exception as rollback_exc:
                application.update(
                    {
                        "status": "rollback_failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "rollback_error": (
                            f"{type(rollback_exc).__name__}: {rollback_exc}"
                        ),
                        "rollback_report": str(run_dir / "rollback_report.json"),
                        "completed_at": _utc_now(),
                    }
                )
                try:
                    write_json_atomic(application_path, application)
                except Exception:
                    pass
                raise RuntimeError(
                    "approved revision failed and baseline rollback was incomplete; "
                    f"see {run_dir / 'rollback_report.json'}"
                ) from rollback_exc
        elif canonical_replaced_once:
            _restore_latest(root, latest_snapshot)

        status = (
            "rolled_back_after_error"
            if canonical_replaced_once and canonical_matches_baseline
            else "failed_before_canonical_replace"
        )
        application.update(
            {
                "status": status,
                "error": f"{type(exc).__name__}: {exc}",
                "rollback_report": (
                    str(run_dir / "rollback_report.json") if rollback is not None else None
                ),
                "rollback": rollback,
                "input_hashes_after": _input_hashes(root),
                "completed_at": _utc_now(),
            }
        )
        write_json_atomic(application_path, application)
        if canonical_replaced_once:
            raise RuntimeError(
                "approved revision failed verification and was rolled back; "
                f"see {application_path}"
            ) from exc
        raise RuntimeError(
            "approved revision failed before canonical replacement; the original "
            f"SceneSpec was preserved; see {application_path}"
        ) from exc
