"""Isolated additive attachment intent/snapshot contracts; no authority or host wiring.

The evaluator rehashes all bytes and checks selected full patches. It deliberately
does not attest GLB extraction: a fixed host reader must recompute actual triangles
and source correspondence before operational enforcement can accept the findings.
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from .owner_relief import inspect_attachment, inspect_inserted_root


class Strict(BaseModel):
    """Reject undeclared fields, non-finite values, and implicit coercions."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Artifact(Strict):
    """Identify one immutable contained input by exact path and digest."""

    path: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid_path(self):
        """Require normalized relative paths and reject separator/drive/path escapes."""
        if (
            "\\" in self.path
            or ":" in self.path
            or "\x00" in self.path
            or self.path.startswith("/")
            or any(p in ("", ".", "..") for p in self.path.split("/"))
            or str(PurePosixPath(self.path)) != self.path
        ):
            raise ValueError("artifact path must be normalized and relative")
        return self


class PatchSelection(Strict):
    """Choose an exact semantic component face group without geometric nearest-owner guesses."""

    semantic_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    face_group_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class RootRegionSelectionV01(Strict):
    """Bind one immutable polygon and existing component anchors, never a new mesh."""

    schema_version: Literal["0.1.0"]
    contract_kind: Literal["surface_attachment_root_region"]
    job_id: str = Field(min_length=1, max_length=128)
    attachment_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    subject_lower: PatchSelection
    owner_front: PatchSelection
    frame_axes: tuple[int, int, int]
    frame_signs: tuple[int, int, int]
    polygon: list[tuple[float | int, float | int]] = Field(min_length=3, max_length=256)

    @model_validator(mode="after")
    def valid_region_frame(self):
        """Keep the projection explicit and leave exact polygon simplicity to the bounded kernel."""
        if sorted(self.frame_axes) != [0, 1, 2] or any(s not in (-1, 1) for s in self.frame_signs):
            raise ValueError("root region frame must be a signed axis permutation")
        if any(abs(value) > 1_000_000 for point in self.polygon for value in point):
            raise ValueError("root region coordinate exceeds the bounded geometry domain")
        return self


class AttachmentEntry(Strict):
    """Freeze one contact patch or explicit intentional open/modular exception."""

    attachment_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    scope: Literal[
        "required_full_patch",
        "required_root_patch",
        "intentional_open",
        "modular_clearance",
    ]
    subject_lower: PatchSelection | None = None
    subject_upper: PatchSelection | None = None
    owner_front: PatchSelection | None = None
    owner_back: PatchSelection | None = None
    root_region: Artifact | None = None
    frame_axes: tuple[int, int, int] = (0, 2, 1)
    frame_signs: tuple[int, int, int] = (1, 1, 1)
    minimum_embed_m: float | None = Field(default=None, gt=0)
    maximum_embed_m: float | None = Field(default=None, gt=0)
    minimum_remaining_thickness_m: float | None = Field(default=None, gt=0)
    minimum_relief_height_m: float | None = Field(default=None, ge=0)
    minimum_overlap_m: float | None = Field(default=None, gt=0)
    exception_reason: str | None = Field(default=None, min_length=8, max_length=1024)

    @model_serializer(mode="wrap")
    def preserve_legacy_selection(self, handler):
        """Keep absent region selection out of existing face-group serialization."""
        result = handler(self)
        if self.root_region is None:
            result.pop("root_region", None)
        return result

    @model_validator(mode="after")
    def valid_scope(self):
        """Keep required patch checks complete and exceptions explicit and non-passing."""
        if sorted(self.frame_axes) != [0, 1, 2] or any(s not in (-1, 1) for s in self.frame_signs):
            raise ValueError("attachment frame must be a signed axis permutation")
        patches = (self.subject_upper, self.owner_front, self.owner_back)
        relief_bounds = (
            self.minimum_embed_m,
            self.maximum_embed_m,
            self.minimum_remaining_thickness_m,
            self.minimum_relief_height_m,
        )
        if self.root_region is not None:
            if (
                self.scope != "required_root_patch"
                or any(x is not None for x in (self.subject_lower, *patches, *relief_bounds))
                or self.minimum_overlap_m is None
                or self.exception_reason is not None
            ):
                raise ValueError(
                    "root region requires only root scope, polygon selection and overlap"
                )
            return self
        if self.subject_lower is None:
            raise ValueError("face-group contact selection requires subject_lower")
        if self.scope in {"required_full_patch", "required_root_patch"}:
            if any(x is None for x in patches) or self.exception_reason is not None:
                raise ValueError("required contact needs complete patches/bounds and no exception")
            if self.scope == "required_full_patch":
                if any(x is None for x in relief_bounds) or self.minimum_overlap_m is not None:
                    raise ValueError("full relief requires only its complete relief bounds")
                if self.maximum_embed_m < self.minimum_embed_m:
                    raise ValueError("embed bounds are inverted")
            elif self.minimum_overlap_m is None or any(x is not None for x in relief_bounds):
                raise ValueError("inserted root requires only its positive overlap bound")
            if self.subject_upper.semantic_id != self.subject_lower.semantic_id:
                raise ValueError("upper and lower patches must share the subject")
            if self.owner_front.semantic_id != self.owner_back.semantic_id:
                raise ValueError("front and back patches must share the selected owner")
            if self.subject_lower.semantic_id == self.owner_front.semantic_id and (
                self.subject_lower.face_group_id
                in (self.owner_front.face_group_id, self.owner_back.face_group_id)
            ):
                raise ValueError("subject cannot use its own patch as support")
        elif self.exception_reason is None or any(
            x is not None for x in (*patches, *relief_bounds, self.minimum_overlap_m)
        ):
            raise ValueError(
                "open/modular scope needs only its explicit reason and subject identity"
            )
        return self


class AttachmentIntentV01(Strict):
    """Bind optional full-patch intent to exact existing scene and geometry inputs."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["surface_attachment_intent"] = "surface_attachment_intent"
    job_id: str = Field(min_length=1, max_length=128)
    source_reference: Artifact
    source_modeling_plan: Artifact
    source_scene: Artifact
    source_geometry: list[Artifact] = Field(min_length=1, max_length=256)
    reference_region_evidence: Artifact | None = None
    entries: list[AttachmentEntry] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def unique_bindings(self):
        """Prevent duplicate or aliased immutable inputs and repeated relation IDs."""
        paths = [
            self.source_reference.path,
            self.source_modeling_plan.path,
            self.source_scene.path,
            *[x.path for x in self.source_geometry],
        ]
        if self.reference_region_evidence is not None:
            paths.append(self.reference_region_evidence.path)
        paths.extend(
            entry.root_region.path for entry in self.entries if entry.root_region is not None
        )
        ids = [x.attachment_id for x in self.entries]
        if len(paths) != len(set(paths)) or len(ids) != len(set(ids)):
            raise ValueError("intent repeats a path or attachment identity")
        return self


class TrianglePatch(Strict):
    """Carry a complete selected actual patch awaiting fixed-inspector extraction verification."""

    selection: PatchSelection
    source_geometry: Artifact
    vertices_m: list[tuple[float, float, float]] = Field(min_length=3, max_length=8192)
    triangles: list[tuple[int, int, int]] = Field(min_length=1, max_length=4096)


class AttachmentTriangleSnapshotV01(Strict):
    """Bind triangle bytes without claiming verified extraction from the named artifact."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["surface_attachment_triangle_snapshot"] = (
        "surface_attachment_triangle_snapshot"
    )
    job_id: str = Field(min_length=1, max_length=128)
    inspected_artifact: Artifact
    source_scene: Artifact
    stage: Literal["emitted_mesh", "native_evaluated", "clean_import_glb"]
    patches: list[TrianglePatch] = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def unique_patches(self):
        """Reject ambiguous patch selectors rather than selecting the most convenient geometry."""
        keys = [(p.selection.semantic_id, p.selection.face_group_id) for p in self.patches]
        if len(keys) != len(set(keys)):
            raise ValueError("snapshot repeats a patch selection")
        return self


def read_bound(root: Path, artifact: Artifact):
    """Read and rehash one normalized contained artifact; never trust latest pointers."""
    artifact = Artifact.model_validate_json(artifact.model_dump_json())
    base = root.resolve(strict=True)
    candidate = base / artifact.path
    if any(p.is_symlink() for p in (candidate, *candidate.parents) if p.is_relative_to(base)):
        raise ValueError("artifact contains a linked path")
    path = candidate.resolve(strict=True)
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("artifact escapes its root or is not a regular file")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise ValueError("stale artifact bytes: " + artifact.path)
    return data


def evaluate_bound_patches(root: Path, intent_artifact: Artifact, snapshot_artifact: Artifact):
    """Recompute exact patch diagnostics from hash-bound data without forging export attestation."""
    intent = AttachmentIntentV01.model_validate_json(read_bound(root, intent_artifact))
    snapshot = AttachmentTriangleSnapshotV01.model_validate_json(
        read_bound(root, snapshot_artifact)
    )
    if snapshot.job_id != intent.job_id or snapshot.source_scene != intent.source_scene:
        raise ValueError("snapshot job/scene binding differs from attachment intent")
    for artifact in [
        intent.source_reference,
        intent.source_modeling_plan,
        intent.source_scene,
        *intent.source_geometry,
        snapshot.inspected_artifact,
    ]:
        read_bound(root, artifact)
    allowed = {(a.path, a.sha256) for a in intent.source_geometry}
    patches = {(p.selection.semantic_id, p.selection.face_group_id): p for p in snapshot.patches}
    for patch in snapshot.patches:
        if (patch.source_geometry.path, patch.source_geometry.sha256) not in allowed:
            raise ValueError("patch names geometry outside exact intent")
    rows = []
    for entry in intent.entries:
        if entry.scope not in {"required_full_patch", "required_root_patch"}:
            rows.append(
                {
                    "attachment_id": entry.attachment_id,
                    "status": "not_applicable",
                    "passed": None,
                    "scope": entry.scope,
                    "reason": entry.exception_reason,
                }
            )
            continue
        if entry.root_region is not None:
            region = RootRegionSelectionV01.model_validate_json(read_bound(root, entry.root_region))
            if (
                region.job_id != intent.job_id
                or region.attachment_id != entry.attachment_id
                or region.frame_axes != entry.frame_axes
                or region.frame_signs != entry.frame_signs
            ):
                raise ValueError("root region job/relation/frame differs from selected intent")
            rows.append(
                {
                    "attachment_id": entry.attachment_id,
                    "status": "unverified",
                    "passed": None,
                    "selection": "explicit_root_region",
                    "root_region": entry.root_region.model_dump(mode="json"),
                    "reason": (
                        "complete actual component extraction is required before region clipping"
                    ),
                }
            )
            continue
        selected = []
        for selector in (
            entry.subject_lower,
            entry.subject_upper,
            entry.owner_front,
            entry.owner_back,
        ):
            key = (selector.semantic_id, selector.face_group_id)
            if key not in patches:
                raise ValueError("required selected patch absent: " + str(key))
            selected.append(patches[key])
        lower, upper, front, back = selected
        arguments = dict(
            lower_vertices=lower.vertices_m,
            lower_triangles=lower.triangles,
            upper_vertices=upper.vertices_m,
            upper_triangles=upper.triangles,
            owner_front_vertices=front.vertices_m,
            owner_front_triangles=front.triangles,
            owner_back_vertices=back.vertices_m,
            owner_back_triangles=back.triangles,
            frame=(entry.frame_axes, entry.frame_signs),
        )
        if entry.scope == "required_root_patch":
            report = inspect_inserted_root(**arguments, minimum_overlap=entry.minimum_overlap_m)
        else:
            report = inspect_attachment(
                **arguments,
                minimum_embed=entry.minimum_embed_m,
                maximum_embed=entry.maximum_embed_m,
                minimum_remaining_thickness=entry.minimum_remaining_thickness_m,
                minimum_relief_height=entry.minimum_relief_height_m,
                scope=entry.scope,
            )
        rows.append({"attachment_id": entry.attachment_id, **report})
    return {
        "intent": intent_artifact.model_dump(mode="json"),
        "snapshot": snapshot_artifact.model_dump(mode="json"),
        "inspected_artifact": snapshot.inspected_artifact.model_dump(mode="json"),
        "status": "failed" if any(row["status"] == "failed" for row in rows) else "unverified",
        "byte_bindings_verified": True,
        "actual_triangle_extraction_verified": False,
        "reason": (
            "fixed host inspector must recompute complete actual triangles "
            "and source correspondence"
        ),
        "entries": rows,
    }
