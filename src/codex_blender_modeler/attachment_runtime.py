"""Standard-library-only exact attachment selection checks shared with Blender."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from .blender_artifacts import native_io_path

REGISTRATION_PATH = "production/surface_attachment/registration.json"
MAX_INPUT_BYTES = 8 * 1024 * 1024


def contained_file(root: Path, relative: str) -> Path:
    """Reject unsafe selected artifacts while retaining native Windows long-path checks."""
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or any(x in relative for x in ("\\", ":", "\x00"))
        or any(x in {"", ".", ".."} for x in relative.split("/"))
    ):
        raise ValueError("attachment artifact path must be normalized job-relative text")
    from .paired_revision_runtime import _contained

    _contained(root, root / relative, must_exist=True)
    candidate = root
    for part in relative.split("/"):
        candidate /= part
        if os.path.islink(native_io_path(candidate)):
            raise ValueError("attachment artifact contains a link")
    candidate.resolve().relative_to(root.resolve())
    if not os.path.isfile(native_io_path(candidate)):
        raise FileNotFoundError(candidate)
    return candidate


def artifact_bytes(root: Path, artifact: dict[str, Any]) -> bytes:
    """Read an exact contained reference through native I/O without adding authority."""
    if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256"}:
        raise ValueError("attachment selection requires only path and sha256")
    expected = artifact["sha256"]
    if not isinstance(expected, str) or re.fullmatch(r"[a-f0-9]{64}", expected) is None:
        raise ValueError("attachment SHA-256 is invalid")
    path = Path(native_io_path(contained_file(root, artifact["path"])))
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("attachment input exceeds its bounded byte limit")
    with path.open("rb") as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("attachment input grew beyond its bounded byte limit")
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("attachment artifact bytes changed: " + artifact["path"])
    return data


def _rehash_root_regions(root: Path, payload: dict[str, Any], job_id: str) -> None:
    """Rehash explicit region dependencies using stdlib only, without geometry or host imports."""
    entries = payload.get("entries", [])
    if not isinstance(entries, list) or len(entries) > 256:
        raise ValueError("attachment entries are not a bounded array")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("attachment entry is malformed")
        selected = entry.get("root_region")
        if selected is None:
            continue
        if entry.get("scope") != "required_root_patch" or any(
            entry.get(key) is not None
            for key in ("subject_lower", "subject_upper", "owner_front", "owner_back")
        ):
            raise ValueError("root region is mixed with another contact selection form")
        region = json.loads(artifact_bytes(root, selected))
        if not isinstance(region, dict) or set(region) != {
            "schema_version",
            "contract_kind",
            "job_id",
            "attachment_id",
            "subject_lower",
            "owner_front",
            "frame_axes",
            "frame_signs",
            "polygon",
        }:
            raise ValueError("root region has unknown or missing fields")
        if (
            region["schema_version"] != "0.1.0"
            or region["contract_kind"] != "surface_attachment_root_region"
            or region["job_id"] != job_id
            or region["attachment_id"] != entry.get("attachment_id")
            or region["frame_axes"] != entry.get("frame_axes", [0, 2, 1])
            or region["frame_signs"] != entry.get("frame_signs", [1, 1, 1])
        ):
            raise ValueError("root region job/relation/frame differs from selected intent")
        axes, signs = region["frame_axes"], region["frame_signs"]
        if (
            not isinstance(axes, list)
            or len(axes) != 3
            or any(type(x) is not int for x in axes)
            or sorted(axes) != [0, 1, 2]
            or not isinstance(signs, list)
            or len(signs) != 3
            or any(type(x) is not int or x not in (-1, 1) for x in signs)
        ):
            raise ValueError("root region frame is not a signed axis permutation")
        for key in ("subject_lower", "owner_front"):
            anchor = region[key]
            if not isinstance(anchor, dict) or set(anchor) != {"semantic_id", "face_group_id"}:
                raise ValueError("root region component anchor is malformed")
            if any(
                not isinstance(value, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None
                for value in anchor.values()
            ):
                raise ValueError("root region component anchor identity is invalid")
        polygon = region["polygon"]
        if not isinstance(polygon, list) or not 3 <= len(polygon) <= 256:
            raise ValueError("root region polygon is outside its bounded simple-ring domain")
        for point in polygon:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or abs(value) > 1_000_000
                    for value in point
                )
            ):
                raise ValueError("root region contains a hole, nested ring or invalid coordinate")


def selected_attachment(root: Path, job_id: str, scene_path: Path) -> dict[str, str] | None:
    """Load only explicit metadata selection and rehash its exact source closure."""
    from .attachment_revision_runtime import (
        completed_attachment_transactions,
        select_revised_attachment,
    )

    committed = completed_attachment_transactions(root)
    metadata_path = root / "job.json"
    receipt_path = root / REGISTRATION_PATH
    registered = receipt_path.exists() or receipt_path.is_symlink()
    if metadata_path.is_symlink():
        raise ValueError("attachment job metadata is linked")
    if not metadata_path.is_file():
        if registered:
            raise ValueError("registered attachment job metadata is missing")
        return None
    metadata = json.loads(metadata_path.read_bytes())
    selected = "attachment_intent" in metadata
    declared = "attachment_registration_sha256" in metadata
    if not selected and not registered and not declared:
        if committed or "attachment_revision" in metadata:
            raise ValueError("attachment revision has no initial registration")
        return None
    if not (selected and registered and declared):
        raise ValueError("attachment selection and immutable registration are incomplete")
    selection = metadata["attachment_intent"]
    registration = json.loads(
        artifact_bytes(
            root,
            {
                "path": REGISTRATION_PATH,
                "sha256": metadata["attachment_registration_sha256"],
            },
        )
    )
    if (
        set(registration)
        != {
            "schema_version",
            "kind",
            "job_id",
            "attachment_intent",
            "metadata_before_sha256",
        }
        or registration["schema_version"] != "0.1.0"
        or registration["kind"]
        not in {"surface_attachment_registration", "solid_root_attachment_registration"}
        or registration["job_id"] != job_id
        or metadata.get("job_id") != job_id
        or registration["attachment_intent"] != selection
        or not isinstance(registration["metadata_before_sha256"], str)
        or re.fullmatch(r"[a-f0-9]{64}", registration["metadata_before_sha256"]) is None
    ):
        raise ValueError("attachment registration and selected intent disagree")
    selection = select_revised_attachment(root, metadata, selection, committed)
    payload = json.loads(artifact_bytes(root, selection))
    if (
        payload.get("schema_version") != "0.1.0"
        or payload.get("contract_kind")
        not in {"surface_attachment_intent", "solid_root_attachment_intent"}
        or payload.get("job_id") != job_id
    ):
        raise ValueError("unknown or foreign attachment intent")
    if payload["contract_kind"] == "solid_root_attachment_intent":
        from .solid_attachment_contract import validate_solid_root_contract

        validate_solid_root_contract(payload)
        if registration["kind"] != "solid_root_attachment_registration":
            raise ValueError("solid-root intent has another domain's registration")
        artifact_bytes(root, payload["source_camera_hypothesis"])
    elif registration["kind"] != "surface_attachment_registration":
        raise ValueError("heightfield intent has another domain's registration")
    source_scene = payload["source_scene"]
    if source_scene["path"] != scene_path.resolve().relative_to(root.resolve()).as_posix():
        raise ValueError("attachment intent selects another SceneSpec")
    artifact_bytes(root, source_scene)
    geometries = payload["source_geometry"]
    if not isinstance(geometries, list) or not 1 <= len(geometries) <= 256:
        raise ValueError("attachment intent needs a bounded geometry source list")
    for item in geometries:
        artifact_bytes(root, item)
    for key in ("source_modeling_plan", "source_reference"):
        artifact_bytes(root, payload[key])
    if payload["contract_kind"] == "surface_attachment_intent":
        _rehash_root_regions(root, payload, job_id)
    selected_regions = payload.get("reference_region_evidence")
    if selected_regions is not None:
        regions = json.loads(artifact_bytes(root, selected_regions))
        if (
            regions.get("schema_version") != "0.3.0"
            or regions.get("contract_kind") != "reference_mask_seed_evidence"
            or regions.get("job_id") != job_id
            or regions.get("reference") != payload["source_reference"]
        ):
            raise ValueError("selected reference regions have foreign or unsupported identity")
        for key in ("reference", "trimap", "subject_extent"):
            artifact_bytes(root, regions[key])
        extent = json.loads(artifact_bytes(root, regions["subject_extent"]))
        if (
            extent.get("schema_version") != "0.1.0"
            or extent.get("contract_kind") != "reference_subject_extent_evidence"
            or extent.get("job_id") != job_id
            or extent.get("reference") != payload["source_reference"]
        ):
            raise ValueError("selected reference extent has foreign or unsupported identity")
        artifact_bytes(root, extent["reference"])
    if payload["source_modeling_plan"]["path"] != "analysis/modeling_plan.json":
        raise ValueError("attachment intent does not bind canonical ModelingPlan")
    references = [item for item in metadata.get("sources", []) if item.get("kind") == "reference"]
    if (
        len(references) != 1
        or not payload["source_reference"]["path"].startswith("input/")
        or str(references[0].get("sha256", "")).lower() != payload["source_reference"]["sha256"]
    ):
        raise ValueError("attachment intent does not bind the job's exact primary reference")
    return dict(selection)
