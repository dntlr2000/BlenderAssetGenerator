from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .models import SceneSpec, StrictModel
from .validation import validate_scene_spec_interior_contract

PathPart = str | int


class RevisionOperation(StrictModel):
    op: Literal["set", "multiply", "add", "append", "remove"]
    target_type: Literal["object", "material", "camera", "scene"]
    target_id: str | None = None
    path: list[PathPart] = Field(min_length=1)
    value: Any
    reason: str

    @model_validator(mode="after")
    def validate_target(self) -> RevisionOperation:
        """Restrict each operation to deterministic targets and safe path semantics."""

        if self.target_type in {"object", "material"} and not self.target_id:
            raise ValueError(f"{self.target_type} operation requires target_id")
        if self.target_type in {"camera", "scene"} and self.target_id is not None:
            raise ValueError(f"{self.target_type} operation must not set target_id")
        for part in self.path:
            if isinstance(part, str) and (not part or part.startswith("__")):
                raise ValueError("Unsafe or empty revision path component")
            if isinstance(part, int) and part < 0:
                raise ValueError("Negative revision path indices are not allowed")
        if self.op == "remove":
            if self.target_type != "scene" or self.path != ["objects"]:
                raise ValueError(
                    "remove is limited to target_type='scene' and path=['objects']"
                )
            if (
                not isinstance(self.value, list)
                or not self.value
                or any(not isinstance(item, str) or not item for item in self.value)
            ):
                raise ValueError("remove requires a non-empty list of stable object IDs")
            if len(self.value) != len(set(self.value)):
                raise ValueError("remove object IDs must be unique")
        return self


class RevisionPlan(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    job_id: str
    base_spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request: str
    operations: list[RevisionOperation] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_revision_plan(path: Path) -> RevisionPlan:
    return RevisionPlan.model_validate_json(path.read_text(encoding="utf-8"))


def _find_by_id(items: list[dict[str, Any]], target_id: str, label: str) -> dict[str, Any]:
    matches = [item for item in items if item.get("id") == target_id]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {label} with id {target_id!r}, found {len(matches)}"
        )
    return matches[0]


def _resolve_target(raw: dict[str, Any], operation: RevisionOperation) -> Any:
    if operation.target_type == "object":
        return _find_by_id(raw["objects"], str(operation.target_id), "object")
    if operation.target_type == "material":
        return _find_by_id(raw["materials"], str(operation.target_id), "material")
    if operation.target_type == "camera":
        return raw["camera"]
    return raw


def _get_child(parent: Any, key: PathPart) -> Any:
    if isinstance(parent, list):
        if not isinstance(key, int):
            raise TypeError(f"List path component must be an integer, got {key!r}")
        return parent[key]
    if isinstance(parent, dict):
        if not isinstance(key, str):
            raise TypeError(f"Object path component must be a string, got {key!r}")
        if key not in parent:
            raise KeyError(f"Revision path does not exist: {key}")
        return parent[key]
    raise TypeError(f"Cannot traverse revision path through {type(parent).__name__}")


def _set_child(parent: Any, key: PathPart, value: Any) -> None:
    if isinstance(parent, list):
        if not isinstance(key, int):
            raise TypeError("List path component must be an integer")
        parent[key] = value
        return
    if isinstance(parent, dict):
        if not isinstance(key, str):
            raise TypeError("Object path component must be a string")
        if key not in parent:
            raise KeyError(f"Revision path does not exist: {key}")
        parent[key] = value
        return
    raise TypeError(f"Cannot assign revision path through {type(parent).__name__}")


def _read_path(target: Any, path: list[PathPart]) -> Any:
    current = target
    for part in path:
        current = _get_child(current, part)
    return current


def _apply_operation(raw: dict[str, Any], operation: RevisionOperation) -> tuple[Any, Any]:
    """Apply one validated deterministic operation and return its before/after values."""

    target = _resolve_target(raw, operation)
    parent = target
    for part in operation.path[:-1]:
        parent = _get_child(parent, part)
    leaf = operation.path[-1]
    before = copy.deepcopy(_get_child(parent, leaf))

    if operation.op == "set":
        after = copy.deepcopy(operation.value)
        _set_child(parent, leaf, after)
    elif operation.op in {"multiply", "add"}:
        if not isinstance(before, (int, float)) or isinstance(before, bool):
            raise TypeError(
                f"{operation.op} requires a numeric target, got {type(before).__name__}"
            )
        if not isinstance(operation.value, (int, float)) or isinstance(operation.value, bool):
            raise TypeError(f"{operation.op} requires a numeric value")
        after = before * operation.value if operation.op == "multiply" else before + operation.value
        _set_child(parent, leaf, after)
    elif operation.op == "append":
        destination = _get_child(parent, leaf)
        if not isinstance(destination, list):
            raise TypeError("append requires a list target")
        destination.append(copy.deepcopy(operation.value))
        after = copy.deepcopy(destination)
    else:
        destination = _get_child(parent, leaf)
        if not isinstance(destination, list):
            raise TypeError("remove requires a list target")
        requested_ids = list(operation.value)
        matches = {
            target_id: [
                index
                for index, item in enumerate(destination)
                if isinstance(item, dict) and item.get("id") == target_id
            ]
            for target_id in requested_ids
        }
        invalid = {
            target_id: indices
            for target_id, indices in matches.items()
            if len(indices) != 1
        }
        if invalid:
            details = ", ".join(
                f"{target_id}={len(indices)}" for target_id, indices in sorted(invalid.items())
            )
            raise ValueError(
                "remove requires exactly one scene object for every stable ID: "
                f"{details}"
            )
        requested = set(requested_ids)
        destination[:] = [
            item
            for item in destination
            if not (isinstance(item, dict) and item.get("id") in requested)
        ]
        after = copy.deepcopy(destination)
    return before, after


def apply_revision_plan(
    *,
    scene_spec_path: Path,
    plan_path: Path,
    output_path: Path | None = None,
) -> tuple[SceneSpec, dict[str, Any]]:
    """Apply one hash-bound revision only after every canonical safety contract passes."""

    plan = load_revision_plan(plan_path)
    scene_spec_path = scene_spec_path.resolve()
    actual_hash = sha256_file(scene_spec_path)
    if actual_hash != plan.base_spec_sha256:
        raise ValueError(
            "Revision plan is stale: base SceneSpec hash does not match the current file "
            f"({plan.base_spec_sha256} != {actual_hash})"
        )

    raw = json.loads(scene_spec_path.read_text(encoding="utf-8"))
    if raw.get("job_id") != plan.job_id:
        raise ValueError(f"Revision plan job_id {plan.job_id!r} does not match SceneSpec")

    next_raw = copy.deepcopy(raw)
    changes: list[dict[str, Any]] = []
    for operation in plan.operations:
        before, after = _apply_operation(next_raw, operation)
        changes.append(
            {
                "op": operation.op,
                "target_type": operation.target_type,
                "target_id": operation.target_id,
                "path": operation.path,
                "before": before,
                "after": after,
                "reason": operation.reason,
            }
        )

    touched = [
        f"{change['target_type']}:{change['target_id'] or '-'}:{change['path']}"
        for change in changes
    ]
    next_raw.setdefault("revision_notes", []).append(
        f"Guarded revision: {plan.request}; touched={'; '.join(touched)}"
    )
    validated = SceneSpec.model_validate(next_raw)
    validate_scene_spec_interior_contract(validated, scene_spec_path)
    destination = (output_path or scene_spec_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(validated.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report = {
        "ok": True,
        "job_id": plan.job_id,
        "request": plan.request,
        "base_spec_sha256": actual_hash,
        "result_spec_sha256": sha256_file(destination),
        "changes": changes,
        "acceptance_criteria": plan.acceptance_criteria,
        "assumptions": plan.assumptions,
    }
    return validated, report
