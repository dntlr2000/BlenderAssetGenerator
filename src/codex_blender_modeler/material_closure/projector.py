"""Deterministic projection helpers shared by material request and completion paths."""

from __future__ import annotations

from collections.abc import Mapping

from .models import MaterialDependencyClosure


def project_immutable_input_map(
    closure: MaterialDependencyClosure,
) -> dict[str, str]:
    """Return the closure-owned immutable input projection in lexical path order."""

    return closure.project_immutable_input_map()


def project_planned_output_map(
    closure: MaterialDependencyClosure,
) -> dict[str, str]:
    """Return only exact-hash planned outputs in lexical path order."""

    return closure.project_planned_output_map()


def require_exact_immutable_projection(
    closure: MaterialDependencyClosure,
    observed: Mapping[str, str],
    *,
    owner: str,
) -> dict[str, str]:
    """Reject a reduced, expanded, or altered request/assignment/completion input map."""

    expected = closure.project_immutable_input_map()
    if dict(observed) != expected:
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        changed = sorted(
            path
            for path in set(expected) & set(observed)
            if expected[path] != observed[path]
        )
        raise ValueError(
            f"{owner} immutable input projection differs from closure "
            f"(missing={missing}, extra={extra}, changed={changed})"
        )
    return expected


def require_exact_planned_output_projection(
    closure: MaterialDependencyClosure,
    observed: Mapping[str, str],
) -> dict[str, str]:
    """Reject output hashes not derived from exact-hash closure output declarations."""

    expected = closure.project_planned_output_map()
    if dict(observed) != expected:
        raise ValueError("planned output projection differs from material closure")
    return expected


__all__ = [
    "project_immutable_input_map",
    "project_planned_output_map",
    "require_exact_immutable_projection",
    "require_exact_planned_output_projection",
]

