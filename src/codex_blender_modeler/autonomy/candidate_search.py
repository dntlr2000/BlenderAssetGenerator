"""Isolated candidate layout, comparison, and atomic canonical promotion helpers."""

from __future__ import annotations

import json
from pathlib import Path

from ..workspace import replace_scene_spec_if_current, sha256_file
from .models import CandidateEvaluation


def candidate_directory(session_root: Path, candidate_id: str) -> Path:
    """Resolve one normalized candidate staging directory without creating it."""

    portable = "abcdefghijklmnopqrstuvwxyz0123456789._-"
    if not candidate_id or any(char not in portable for char in candidate_id):
        raise ValueError("candidate_id must use lowercase portable characters")
    resolved_session = session_root.expanduser().resolve()
    resolved = (resolved_session / "candidates" / candidate_id).resolve()
    try:
        resolved.relative_to(resolved_session)
    except ValueError as exc:
        raise ValueError("candidate directory escaped its autonomy session") from exc
    return resolved


def preserve_best_known(
    session_root: Path,
    evaluation: CandidateEvaluation,
    evaluation_path: Path,
) -> Path:
    """Publish an immutable best-known pointer containing exact evaluation evidence."""

    if not evaluation.eligible_for_promotion:
        raise ValueError("An ineligible candidate cannot become best-known")
    resolved_session = session_root.expanduser().resolve()
    resolved_evaluation = evaluation_path.expanduser().resolve(strict=True)
    try:
        relative = resolved_evaluation.relative_to(resolved_session).as_posix()
    except ValueError as exc:
        raise ValueError("Candidate evaluation escaped its autonomy session") from exc
    payload = {
        "schema_version": "0.1.0",
        "candidate_id": evaluation.candidate_id,
        "evaluation_path": relative,
        "evaluation_sha256": sha256_file(resolved_evaluation),
        "metric_vector": evaluation.metrics.model_dump(mode="json"),
    }
    output = resolved_session / "best_known.json"
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing == payload:
            return output
        history = resolved_session / "best_known_history"
        history.mkdir(parents=True, exist_ok=True)
        archived = history / f"{existing['evaluation_sha256']}.json"
        if not archived.exists():
            archived.write_bytes(output.read_bytes())
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    return output


def promote_scene_spec_candidate(
    *,
    job_id: str,
    candidate_path: Path,
    candidate_sha256: str,
    expected_canonical_sha256: str | None,
    lock_owner_id: str,
) -> dict[str, str | None]:
    """Promote one already-evaluated SceneSpec through the shared compare-and-swap writer."""

    result = replace_scene_spec_if_current(
        job_id,
        candidate_path,
        expected_candidate_sha256=candidate_sha256,
        expected_current_sha256=expected_canonical_sha256,
        lock_owner_id=lock_owner_id,
    )
    return {
        "previous_scene_spec_sha256": result["previous_scene_spec_sha256"],
        "scene_spec_sha256": str(result["result_scene_spec_sha256"]),
        "archived": (
            str(result["archived_scene_spec"])
            if result.get("archived_scene_spec")
            else None
        ),
    }
