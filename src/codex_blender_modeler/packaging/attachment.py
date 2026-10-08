"""Explicit, derived-only attachment checks from complete freshly extracted geometry."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..attachment_runtime import (
    REGISTRATION_PATH,
    artifact_bytes,
    contained_file,
    selected_attachment,
)
from ..blender_runner import run_blender
from ..optimization.models import SourceProvenance
from ..structural_geometry.attachment_companion import (
    Artifact,
    AttachmentIntentV01,
    RootRegionSelectionV01,
)
from ..structural_geometry.mesh_payload_v02 import MeshPayloadV02
from ..structural_geometry.owner_relief import (
    inspect_attachment,
    inspect_inserted_root,
    verify_height_field_solid,
)
from ..structural_geometry.profiled_relief import _validate_embedded
from ..structural_geometry.root_region import inspect_root_region
from ..structural_geometry.solid_attachment_companion import SolidRootAttachmentIntentV01
from ..structural_geometry.triangle_shell import TriangulatedShellGeometry
from ..workspace import job_dir

POSITION_LIMIT_M = 0.0
MAX_CORRESPONDENCE_CHECKS = 1000000
MAX_EMBEDDING_SCANS = 1000000
REQUIRED_SCOPES = {"required_full_patch", "required_root_patch"}


def _sha(path: Path) -> str:
    """Hash one current artifact without loading a large blend into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_once(path: Path, value: Any) -> None:
    """Retain one immutable task result; an existing failed attempt is never rewritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def _validate_region_identity(intent, entry, region: RootRegionSelectionV01) -> None:
    """Keep region identity and its projection bound to the selected outer relation."""
    if (
        region.job_id != intent.job_id
        or region.attachment_id != entry.attachment_id
        or region.frame_axes != entry.frame_axes
        or region.frame_signs != entry.frame_signs
    ):
        raise ValueError("root region job/relation/frame differs from selected intent")


def load_root_regions(root: Path, intent: AttachmentIntentV01) -> dict[str, RootRegionSelectionV01]:
    """Rehash only explicitly selected immutable regions; filenames never activate this mode."""
    if isinstance(intent, SolidRootAttachmentIntentV01):
        return {}
    regions = {}
    for entry in intent.entries:
        if entry.root_region is None:
            continue
        region = RootRegionSelectionV01.model_validate_json(
            artifact_bytes(root, entry.root_region.model_dump(mode="json"))
        )
        _validate_region_identity(intent, entry, region)
        regions[entry.attachment_id] = region
    return regions


def _entry_selections(entry, regions):
    """Select legacy contact groups or existing lower/front component anchors."""
    if entry.root_region is not None:
        region = regions[entry.attachment_id]
        return region.subject_lower, None, region.owner_front, None
    return entry.subject_lower, entry.subject_upper, entry.owner_front, entry.owner_back


def _region_snapshot_name(attachment_id: str) -> str:
    """Keep snapshot filenames portable even when a valid relation ID contains punctuation."""
    return hashlib.sha256(attachment_id.encode("utf-8")).hexdigest() + ".json"


def _parse_attachment_intent(data: bytes) -> AttachmentIntentV01 | SolidRootAttachmentIntentV01:
    """Dispatch only explicitly named strict domains; unknown fields/versions still fail."""
    payload = json.loads(data)
    if isinstance(payload, dict) and payload.get("contract_kind") == "solid_root_attachment_intent":
        return SolidRootAttachmentIntentV01.model_validate_json(data)
    return AttachmentIntentV01.model_validate_json(data)


def register_surface_attachment_intent(
    job_id: str, *, intent_path: str, intent_sha256: str
) -> dict[str, str]:
    """Retain the legacy explicit heightfield-only initial selection API."""
    return _register_attachment_intent(
        job_id,
        intent_path=intent_path,
        intent_sha256=intent_sha256,
        expected_kind="surface_attachment_intent",
    )


def register_solid_root_attachment_intent(
    job_id: str, *, intent_path: str, intent_sha256: str
) -> dict[str, str]:
    """Explicitly select the additive complete-solid/local-ball domain before first build."""
    return _register_attachment_intent(
        job_id,
        intent_path=intent_path,
        intent_sha256=intent_sha256,
        expected_kind="solid_root_attachment_intent",
    )


def _register_attachment_intent(
    job_id: str,
    *,
    intent_path: str,
    intent_sha256: str,
    expected_kind: str,
) -> dict[str, str]:
    """Select one exact validated companion before a fresh job's first build.

    This is an applicability/input selection, not approval or visual acceptance.
    Existing built jobs and changed selections require an explicitly designed
    revision route and are refused by this narrow initial-registration function.
    """
    from ..orchestration.locks import workflow_write_lock

    root = job_dir(job_id)
    selection = Artifact(path=intent_path, sha256=intent_sha256)
    with workflow_write_lock(root, job_id, f"attachment-select-{uuid4().hex[:12]}"):
        if (root / "blender/scene.blend").exists():
            raise ValueError("attachment registration is limited to an unbuilt fresh job")
        intent = _parse_attachment_intent(artifact_bytes(root, selection.model_dump(mode="json")))
        if intent.contract_kind != expected_kind:
            raise ValueError("attachment registration API does not authorize another proof domain")
        if intent.job_id != job_id or intent.source_scene.path != "analysis/scene_spec.json":
            raise ValueError("attachment selection must bind this job's canonical SceneSpec")
        for bound in [
            intent.source_reference,
            intent.source_modeling_plan,
            intent.source_scene,
            *intent.source_geometry,
        ]:
            artifact_bytes(root, bound.model_dump(mode="json"))
        meshes = _source_meshes(root, intent)
        if intent.reference_region_evidence is not None:
            from ..qa.attachment_occupancy import validate_reference_region_context

            validate_reference_region_context(root, intent)
        metadata_path = contained_file(root, "job.json")
        metadata = json.loads(metadata_path.read_bytes())
        chosen = selection.model_dump(mode="json")
        if "attachment_intent" in metadata:
            if metadata["attachment_intent"] != chosen:
                raise ValueError("attachment selection cannot change or be removed")
            selected_attachment(root, job_id, root / intent.source_scene.path)
            return chosen
        preflight = preflight_source_attachment(
            intent, meshes, root_regions=load_root_regions(root, intent)
        )
        preflight["intent"] = chosen
        _write_once(
            root / "reports/surface_attachment" / f"source-{uuid4().hex}.json",
            preflight,
        )
        if preflight["status"] != "passed":
            raise ValueError("source attachment preflight failed or is unverified")
        registration_path = root / REGISTRATION_PATH
        registration = {
            "schema_version": "0.1.0",
            "kind": "solid_root_attachment_registration"
            if isinstance(intent, SolidRootAttachmentIntentV01)
            else "surface_attachment_registration",
            "job_id": job_id,
            "attachment_intent": chosen,
            "metadata_before_sha256": _sha(metadata_path),
        }
        if registration_path.exists():
            # Only an exact pre-metadata-write interruption can resume this initial selection.
            existing = json.loads(contained_file(root, REGISTRATION_PATH).read_bytes())
            if existing != registration:
                raise ValueError("existing attachment registration differs or metadata changed")
        else:
            _write_once(registration_path, registration)
        metadata["attachment_intent"] = chosen
        metadata["attachment_registration_sha256"] = _sha(registration_path)
        temporary = metadata_path.with_name(f".job-attachment-{uuid4().hex}.tmp")
        _write_once(temporary, metadata)
        os.replace(temporary, metadata_path)
    return chosen


def preflight_source_attachment(
    intent: AttachmentIntentV01,
    meshes: dict[str, MeshPayloadV02],
    *,
    root_regions: dict[str, RootRegionSelectionV01] | None = None,
) -> dict[str, Any]:
    """Measure predicted binary32 source geometry early without inventing native extraction."""
    records = []
    for semantic_id, mesh in sorted(meshes.items()):
        points = [
            tuple(struct.unpack("f", struct.pack("f", x))[0] for x in p) for p in mesh.vertices
        ]
        records.append(
            {
                "semantic_id": semantic_id,
                "triangles": [
                    {
                        "corners": [points[i] for i in face],
                        "material_id": mesh.material_slots[0].material_id,
                    }
                    for face in mesh.faces
                ],
            }
        )
    report = evaluate_actual(intent, meshes, {"objects": records}, root_regions=root_regions)
    report.update(
        {
            "stage": "source_float32_prediction",
            "actual_triangle_extraction_verified": False,
            "native_geometry_verified": False,
            "interpretation": "source preflight only; fresh native and package checks required",
        }
    )
    return report


def _source_meshes(root: Path, intent: AttachmentIntentV01) -> dict[str, MeshPayloadV02]:
    """Load exact existing triangle payloads with complete groups under a bounded initial route."""
    if isinstance(intent, SolidRootAttachmentIntentV01):
        from .solid_attachment import load_solid_source_meshes

        return load_solid_source_meshes(root, intent)
    regions = load_root_regions(root, intent)
    scene = json.loads(artifact_bytes(root, intent.source_scene.model_dump(mode="json")))
    from ..workspace import resolve_job_input_path

    metadata = json.loads(contained_file(root, "job.json").read_bytes())
    references = [item for item in metadata.get("sources", []) if item.get("kind") == "reference"]
    if len(references) != 1:
        raise ValueError("attachment requires one exact primary reference in job metadata")
    reference = resolve_job_input_path(root, references[0]["path"], references[0].get("sha256"))
    if reference != contained_file(root, intent.source_reference.path):
        raise ValueError("attachment intent selects a different primary reference")
    artifact_bytes(root, intent.source_reference.model_dump(mode="json"))
    plan = json.loads(artifact_bytes(root, intent.source_modeling_plan.model_dump(mode="json")))
    if (
        intent.source_modeling_plan.path != "analysis/modeling_plan.json"
        or plan.get("job_id") != intent.job_id
    ):
        raise ValueError("attachment intent must bind this job's canonical ModelingPlan")
    if scene.get("job_id") != intent.job_id:
        raise ValueError("attachment SceneSpec belongs to another job")
    objects = {obj["id"]: obj for obj in scene["objects"]}
    meshes = {}
    total_bytes = 0
    total_triangles = 0
    for artifact in intent.source_geometry:
        data = artifact_bytes(root, artifact.model_dump(mode="json"))
        total_bytes += len(data)
        raw = json.loads(data)
        if (
            total_bytes > 32 * 1024 * 1024
            or not isinstance(raw, dict)
            or not isinstance(raw.get("vertices"), list)
            or not isinstance(raw.get("faces"), list)
            or len(raw["vertices"]) > 16384
            or len(raw["faces"]) > 8192
        ):
            raise ValueError("attachment source exceeds bounded bytes/semantic geometry limits")
        total_triangles += len(raw["faces"])
        if total_triangles > 25000:
            raise ValueError("attachment source exceeds total triangle limit")
        mesh = MeshPayloadV02.model_validate_json(data)
        for dependency in mesh.source_hashes:
            artifact_bytes(root, {"path": dependency.path, "sha256": dependency.sha256})
        obj = objects.get(mesh.semantic_id)
        if (
            obj is None
            or obj["geometry"].get("kind") != "custom_mesh"
            or obj["geometry"].get("path") != artifact.path
        ):
            raise ValueError("attachment geometry is not the actual selected semantic payload")
        transform = obj.get("transform", {})
        if (
            transform.get("location") != [0, 0, 0]
            or transform.get("rotation_deg") != [0, 0, 0]
            or transform.get("scale") != [1, 1, 1]
            or obj.get("modifiers")
            or obj.get("generator")
            or obj.get("parent_id")
        ):
            raise ValueError(
                "attachment source currently requires explicit world-space unmodified parts"
            )
        if any(len(face) != 3 for face in mesh.faces) or len(mesh.material_slots) != 1:
            raise ValueError("attachment source requires triangulated single-slot payloads")
        if mesh.semantic_id in meshes:
            raise ValueError("attachment source repeats a semantic geometry payload")
        meshes[mesh.semantic_id] = mesh
    selected = set()
    required_solid_semantics = set()
    for entry in intent.entries:
        lower, upper, front, back = _entry_selections(entry, regions)
        if entry.scope in REQUIRED_SCOPES:
            required_solid_semantics.update((lower.semantic_id, front.semantic_id))
        for item in (lower, upper, front, back):
            if item is not None:
                selected.add(item.semantic_id)
                mesh = meshes.get(item.semantic_id)
                if mesh is None or item.face_group_id not in {g.id for g in mesh.face_groups}:
                    raise ValueError(
                        "attachment selected group is absent from exact source payload"
                    )
    if selected != set(meshes):
        raise ValueError("attachment source geometry list has missing or unrelated members")
    if any(
        meshes[key].source_geometry_intent.topology_profile != "static_prop_closed"
        for key in required_solid_semantics
    ):
        raise ValueError(
            "required attachment owner/subject semantics need static_prop_closed intent"
        )
    return meshes


def map_actual_mesh(mesh: MeshPayloadV02, record: dict[str, Any]) -> dict[str, Any]:
    """Match every oriented source triangle to one actual triangle without welding cracks."""
    if set(record) != {"semantic_id", "triangles"} or record["semantic_id"] != mesh.semantic_id:
        raise ValueError("actual semantic record is malformed or mixed")
    actual = record["triangles"]
    if not isinstance(actual, list) or len(actual) != len(mesh.faces):
        raise ValueError("actual mesh omitted or added triangles")
    expected_vertices = [
        tuple(struct.unpack("f", struct.pack("f", x))[0] for x in p) for p in mesh.vertices
    ]
    by_triangle = defaultdict(list)
    for index, triangle in enumerate(actual):
        if set(triangle) != {"corners", "material_id"}:
            raise ValueError("actual triangle has unknown or missing fields")
        corners = triangle["corners"]
        if (
            not isinstance(corners, list)
            or len(corners) != 3
            or any(not isinstance(p, (list, tuple)) or len(p) != 3 for p in corners)
            or any(
                type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 1e6
                for p in corners
                for x in p
            )
        ):
            raise ValueError("actual triangle positions are invalid")
        if triangle["material_id"] != mesh.material_slots[0].material_id:
            raise ValueError("actual triangle material identity changed")
        points = tuple(tuple(point) for point in corners)
        key = min(points[i:] + points[:i] for i in range(3))
        by_triangle[key].append(index)
    used, positions, checks = set(), {}, 0
    maximum_error = 0.0
    for face in mesh.faces:
        source = [expected_vertices[i] for i in face]
        points = tuple(source)
        key = min(points[i:] + points[:i] for i in range(3))
        matches = []
        for index in by_triangle.get(key, []):
            checks += 1
            if checks > MAX_CORRESPONDENCE_CHECKS:
                raise ValueError("attachment correspondence resource limit exceeded")
            corners = actual[index]["corners"]
            for rotation in range(3):
                ordered = corners[rotation:] + corners[:rotation]
                if tuple(tuple(point) for point in ordered) == points:
                    matches.append((index, ordered, 0.0))
        if len(matches) != 1 or matches[0][0] in used:
            raise ValueError("attachment triangle correspondence is missing or ambiguous")
        index, ordered, error = matches[0]
        used.add(index)
        maximum_error = max(maximum_error, error)
        for vertex, point in zip(face, ordered, strict=True):
            value = tuple(point)
            if vertex in positions and positions[vertex] != value:
                raise ValueError("actual shared source vertex has a crack; no tolerance welding")
            positions[vertex] = value
    if len(used) != len(actual):
        raise ValueError("attachment actual triangle coverage is incomplete")
    return {
        "vertices": [positions.get(i) for i in range(len(mesh.vertices))],
        "triangles": mesh.faces,
        "groups": {g.id: g.face_indices for g in mesh.face_groups},
        "maximum_position_error_m": maximum_error,
        "correspondence_checks": checks,
    }


def complete_component(
    mapped: dict[str, Any], first_group: str, second_group: str
) -> dict[str, Any]:
    """Recover all connected source-topology faces around two selected actual face groups."""
    triangles = mapped["triangles"]
    incidence = defaultdict(list)
    for index, face in enumerate(triangles):
        for vertex in face:
            incidence[vertex].append(index)
    groups = mapped["groups"]
    first, second = groups[first_group], groups[second_group]
    pending, selected = [first[0]], set()
    visited_vertices = set()
    while pending:
        index = pending.pop()
        if index in selected:
            continue
        selected.add(index)
        for vertex in triangles[index]:
            if vertex not in visited_vertices:
                visited_vertices.add(vertex)
                pending.extend(i for i in incidence[vertex] if i not in selected)
    if not set(first + second) <= selected:
        raise ValueError("selected patches span different connected components")
    face_ids = sorted(selected)
    vertex_ids = sorted({v for i in face_ids for v in triangles[i]})
    if any(mapped["vertices"][i] is None for i in vertex_ids):
        raise ValueError("actual component is missing a source vertex")
    vertex_map = {old: new for new, old in enumerate(vertex_ids)}
    face_map = {old: new for new, old in enumerate(face_ids)}
    return {
        "vertices": [mapped["vertices"][i] for i in vertex_ids],
        "triangles": [tuple(vertex_map[v] for v in triangles[i]) for i in face_ids],
        "first": [face_map[i] for i in first],
        "second": [face_map[i] for i in second],
        "source_face_indices": face_ids,
    }


def reject_inward_closed_components(
    mapped: dict[str, Any], budget: list[int] | None = None
) -> None:
    """Refuse an ignored inward cavity shell anywhere in a selected semantic mesh."""
    triangles, vertices = mapped["triangles"], mapped["vertices"]
    if budget is None:
        budget = [0]
    incidence = defaultdict(list)
    for index, face in enumerate(triangles):
        for vertex in face:
            incidence[vertex].append(index)
    unseen = set(range(len(triangles)))
    cursor = 0
    while unseen:
        while cursor not in unseen:
            cursor += 1
        pending, component = [cursor], set()
        visited_vertices = set()
        while pending:
            index = pending.pop()
            if index in component:
                continue
            component.add(index)
            unseen.discard(index)
            for vertex in triangles[index]:
                if vertex not in visited_vertices:
                    visited_vertices.add(vertex)
                    pending.extend(i for i in incidence[vertex] if i not in component)
        edges = defaultdict(list)
        for index in component:
            face = triangles[index]
            for a, b in zip(face, face[1:] + face[:1], strict=True):
                edges[tuple(sorted((a, b)))].append((a, b))
        if any(len(uses) != 2 for uses in edges.values()):
            raise ValueError("required semantic contains an omitted open or non-manifold component")
        if any(uses[0] != tuple(reversed(uses[1])) for uses in edges.values()):
            raise ValueError("closed semantic component has inconsistent winding")
        volume6 = Fraction(0)
        for index in component:
            a, b, c = [tuple(Fraction(x) for x in vertices[i]) for i in triangles[index]]
            volume6 += sum(
                a[k] * (b[(k + 1) % 3] * c[(k + 2) % 3] - b[(k + 2) % 3] * c[(k + 1) % 3])
                for k in range(3)
            )
        if volume6 <= 0:
            raise ValueError("closed semantic component is inward or has zero volume")
        vertex_ids = sorted({vertex for i in component for vertex in triangles[i]})
        if len(component) > 4096 or len(vertex_ids) > 8192:
            raise ValueError("attachment component exceeds the exact solid proof limits")
        index_by_vertex = {old: new for new, old in enumerate(vertex_ids)}
        shell = TriangulatedShellGeometry(
            vertices=[vertices[i] for i in vertex_ids],
            triangles=[tuple(index_by_vertex[v] for v in triangles[i]) for i in sorted(component)],
        )
        # Prove embedding once; charge actual heap expiry and candidate scans.
        # Exact contact predicates and the per-component pair cap remain unchanged.
        _validate_embedded(shell, scan_budget=budget, max_scans=MAX_EMBEDDING_SCANS)


def derived_solid_roles(component: dict[str, Any], frame: tuple) -> tuple[list[int], list[int]]:
    """Classify all actual cap faces by exact signed projection in the declared depth frame."""
    axes, signs = frame
    inversions = sum(axes[i] > axes[j] for i in range(3) for j in range(i + 1, 3))
    handedness = (-1 if inversions % 2 else 1) * signs[0] * signs[1] * signs[2]
    points = [
        tuple(Fraction(p[a]) * sign for a, sign in zip(axes, signs, strict=True))
        for p in component["vertices"]
    ]
    front, back = [], []
    for index, face in enumerate(component["triangles"]):
        a, b, c = [points[i] for i in face]
        determinant = ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) * handedness
        if determinant < 0:
            front.append(index)
        elif determinant > 0:
            back.append(index)
    if not set(component["first"]) <= set(front) or not set(component["second"]) <= set(back):
        raise ValueError("selected root patch is not in the correct complete solid cap role")
    return front, back


def evaluate_actual(
    intent: AttachmentIntentV01,
    meshes: dict[str, MeshPayloadV02],
    raw: dict,
    *,
    root_regions: dict[str, RootRegionSelectionV01] | None = None,
) -> dict:
    """Recompute whole-solid and complete-patch checks only from fresh actual geometry."""
    if isinstance(intent, SolidRootAttachmentIntentV01):
        from .solid_attachment import evaluate_solid_actual

        if root_regions:
            raise ValueError("solid-root proof cannot borrow projected patch regions")
        return evaluate_solid_actual(intent, meshes, raw)
    expected_regions = {
        entry.attachment_id for entry in intent.entries if entry.root_region is not None
    }
    if expected_regions and root_regions is None:
        return {
            "status": "unverified",
            "entries": [],
            "source_correspondence_verified": False,
            "reason": "selected root region bytes have not been resolved by the bound host loader",
            "actual_triangle_extraction_verified": False,
            "final_human_acceptance": False,
        }
    root_regions = root_regions or {}
    if set(root_regions) != expected_regions:
        raise ValueError("resolved root regions are missing, extra or mixed")
    for entry in intent.entries:
        if entry.root_region is not None:
            _validate_region_identity(intent, entry, root_regions[entry.attachment_id])
    records = raw["objects"]
    if not isinstance(records, list) or len(records) > 128:
        raise ValueError("actual extraction object array is invalid")
    identities = [record["semantic_id"] for record in records]
    if len(identities) != len(set(identities)):
        raise ValueError("actual extraction repeats semantic identity")
    by_id = {record["semantic_id"]: record for record in records}
    mapped = {key: map_actual_mesh(mesh, by_id[key]) for key, mesh in meshes.items()}
    required_semantics = {
        selector.semantic_id
        for entry in intent.entries
        if entry.scope in REQUIRED_SCOPES
        for selector in (
            _entry_selections(entry, root_regions)[0],
            _entry_selections(entry, root_regions)[2],
        )
    }
    embedding_budget = [0]
    for key in sorted(required_semantics):
        reject_inward_closed_components(mapped[key], embedding_budget)
    rows = []
    solid_cache = {}
    for entry in intent.entries:
        if entry.scope not in REQUIRED_SCOPES:
            rows.append(
                {
                    "attachment_id": entry.attachment_id,
                    "status": "not_applicable",
                    "passed": None,
                    "reason": entry.exception_reason,
                }
            )
            continue
        lower, upper, front_anchor, back_anchor = _entry_selections(entry, root_regions)
        region = root_regions.get(entry.attachment_id)
        subject = complete_component(
            mapped[lower.semantic_id],
            lower.face_group_id if region is not None else upper.face_group_id,
            lower.face_group_id,
        )
        owner = complete_component(
            mapped[front_anchor.semantic_id],
            front_anchor.face_group_id,
            front_anchor.face_group_id if region is not None else back_anchor.face_group_id,
        )
        if lower.semantic_id == front_anchor.semantic_id and set(
            subject["source_face_indices"]
        ) & set(owner["source_face_indices"]):
            raise ValueError("attachment subject and owner alias the same complete component")
        frame = (entry.frame_axes, entry.frame_signs)
        if region is not None:
            # The existing named groups are component/role anchors, never clipping bounds.
            subject["first"] = []
            owner["second"] = []
        solids = []
        for semantic_id, component in (
            (front_anchor.semantic_id, owner),
            (lower.semantic_id, subject),
        ):
            front, back = (
                derived_solid_roles(component, frame)
                if entry.scope == "required_root_patch"
                else (component["first"], component["second"])
            )
            component["full_front"] = front
            component["full_back"] = back
            key = (
                semantic_id,
                tuple(component["source_face_indices"]),
                tuple(front),
                tuple(back),
                frame,
            )
            if key not in solid_cache:
                solid_cache[key] = verify_height_field_solid(
                    vertices=component["vertices"],
                    triangles=component["triangles"],
                    front_face_indices=front,
                    back_face_indices=back,
                    frame=frame,
                )
            solids.append(solid_cache[key])
        owner_solid, subject_solid = solids
        if owner_solid.get("passed") is not True or subject_solid.get("passed") is not True:
            rows.append(
                {
                    "attachment_id": entry.attachment_id,
                    "status": "unverified",
                    "passed": None,
                    "owner_solid": owner_solid,
                    "subject_solid": subject_solid,
                }
            )
            continue
        subject_front = subject["full_front"] if region is not None else subject["first"]
        subject_back = subject["full_back"] if region is not None else subject["second"]
        owner_front = owner["full_front"] if region is not None else owner["first"]
        owner_back = owner["full_back"] if region is not None else owner["second"]
        patch_arguments = dict(
            lower_vertices=subject["vertices"],
            lower_triangles=[subject["triangles"][i] for i in subject_back],
            upper_vertices=subject["vertices"],
            upper_triangles=[subject["triangles"][i] for i in subject_front],
            owner_front_vertices=owner["vertices"],
            owner_front_triangles=[owner["triangles"][i] for i in owner_front],
            owner_back_vertices=owner["vertices"],
            owner_back_triangles=[owner["triangles"][i] for i in owner_back],
            frame=frame,
        )
        if region is not None:
            patch = inspect_root_region(
                **patch_arguments,
                minimum_overlap=entry.minimum_overlap_m,
                region_polygon=region.polygon,
            )
        elif entry.scope == "required_root_patch":
            patch = inspect_inserted_root(
                **patch_arguments, minimum_overlap=entry.minimum_overlap_m
            )
        else:
            patch = inspect_attachment(
                **patch_arguments,
                minimum_embed=entry.minimum_embed_m,
                maximum_embed=entry.maximum_embed_m,
                minimum_remaining_thickness=entry.minimum_remaining_thickness_m,
                minimum_relief_height=entry.minimum_relief_height_m,
            )
        row = {
            "attachment_id": entry.attachment_id,
            **patch,
            "owner_solid": owner_solid,
            "subject_solid": subject_solid,
            "owner_volume_verified": True,
            "subject_volume_verified": True,
            "owner_source_faces": owner["source_face_indices"],
            "subject_source_faces": subject["source_face_indices"],
            "selected_contact_source_faces": {
                "subject_front": [subject["source_face_indices"][i] for i in subject["first"]],
                "subject_back": [subject["source_face_indices"][i] for i in subject["second"]],
                "owner_front": [owner["source_face_indices"][i] for i in owner["first"]],
                "owner_back": [owner["source_face_indices"][i] for i in owner["second"]],
            },
        }
        if region is not None:
            row.pop("selected_contact_source_faces")
            row.update(
                {
                    "root_region": entry.root_region.model_dump(mode="json"),
                    "component_anchors": {
                        "subject_lower": region.subject_lower.model_dump(mode="json"),
                        "owner_front": region.owner_front.model_dump(mode="json"),
                    },
                    "anchor_source_faces": {
                        "subject_lower": [
                            subject["source_face_indices"][i] for i in subject["second"]
                        ],
                        "owner_front": [owner["source_face_indices"][i] for i in owner["first"]],
                    },
                    "complete_clipping_source_faces": {
                        "subject_front": [subject["source_face_indices"][i] for i in subject_front],
                        "subject_back": [subject["source_face_indices"][i] for i in subject_back],
                        "owner_front": [owner["source_face_indices"][i] for i in owner_front],
                        "owner_back": [owner["source_face_indices"][i] for i in owner_back],
                    },
                }
            )
        rows.append(row)
    failed = any(row["status"] not in {"passed", "not_applicable"} for row in rows)
    return {
        "status": "failed" if failed else "passed",
        "entries": rows,
        "scope": (
            "selected complete outward height-field components; no general solid containment claim"
        ),
        "source_correspondence_verified": True,
        "embedding_broadphase_scans": embedding_budget[0],
        "correspondence_policy": {
            "method": "exact_numeric_float32_source_positions_unique_oriented_triangles",
            "position_component_limit_m": POSITION_LIMIT_M,
            "proof_coordinates": "actual_unrounded_extracted_world_positions",
            "shared_vertex_policy": "exact_actual_equality_no_welding",
            "objects": [
                {
                    "semantic_id": key,
                    "triangle_count": len(value["triangles"]),
                    "maximum_position_error_m": value["maximum_position_error_m"],
                    "correspondence_checks": value["correspondence_checks"],
                }
                for key, value in sorted(mapped.items())
            ],
        },
        "actual_triangle_extraction_verified": False,
        "final_human_acceptance": False,
    }


def inspect_stage(
    root: Path, source: SourceProvenance, artifact: Path, stage: str, output: Path
) -> dict:
    """Run the fixed inspector freshly and reject stale, mixed or forged request projections."""
    selection = source.attachment_intent
    if selection is None:
        raise ValueError("attachment stage requires exact selected source")
    if output.exists() or output.is_symlink():
        raise FileExistsError("attachment extraction must be freshly executed into a new path")
    expected = {"path": selection.path, "sha256": selection.sha256}
    if selected_attachment(root, root.name, root / source.scene_spec.path) != expected:
        raise ValueError("live attachment selection differs from frozen run")
    intent = _parse_attachment_intent(artifact_bytes(root, expected))
    if (
        intent.source_scene.path != source.scene_spec.path
        or intent.source_scene.sha256 != source.scene_spec.sha256
    ):
        raise ValueError("attachment intent SceneSpec differs from frozen run")
    frozen_geometry = {(item.path, item.sha256) for item in source.geometry_payloads}
    if any((item.path, item.sha256) not in frozen_geometry for item in intent.source_geometry):
        raise ValueError("attachment geometry differs from frozen run")
    meshes = _source_meshes(root, intent)
    artifact.resolve().relative_to(root.resolve())
    actual_hash = _sha(artifact)
    run_blender(
        "inspect_surface_attachment_geometry.py",
        [
            "--job-root",
            str(root),
            "--artifact",
            str(artifact),
            "--artifact-sha256",
            actual_hash,
            "--source-fingerprint",
            source.source_fingerprint,
            "--build-fingerprint",
            source.build_fingerprint,
            "--intent-sha256",
            selection.sha256,
            "--stage",
            stage,
            "--output",
            str(output),
        ],
        blend_file=None if stage == "clean_import_glb" else artifact,
        factory_startup=stage == "clean_import_glb",
        disable_autoexec=True,
    )
    if output.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("attachment extraction exceeds bounded output byte limit")
    raw = json.loads(output.read_bytes())
    expected_projection = {
        "schema_version": "0.1.0",
        "kind": "surface_attachment_actual_triangles",
        "blender_version": "5.0.1",
        "stage": stage,
        "artifact": {
            "path": artifact.relative_to(root).as_posix(),
            "sha256": actual_hash,
        },
        "source_fingerprint": source.source_fingerprint,
        "build_fingerprint": source.build_fingerprint,
        "intent_sha256": selection.sha256,
    }
    if (
        any(raw.get(key) != value for key, value in expected_projection.items())
        or set(raw) != {*expected_projection, "triangle_count", "objects"}
        or raw["triangle_count"] != sum(len(x["triangles"]) for x in raw["objects"])
        or _sha(artifact) != actual_hash
    ):
        raise ValueError("actual attachment extraction differs from exact host request")
    # Existing files are never accepted as substitute for this freshly invoked fixed extraction.
    report = evaluate_actual(intent, meshes, raw, root_regions=load_root_regions(root, intent))
    if isinstance(intent, SolidRootAttachmentIntentV01):
        if selected_attachment(root, root.name, root / source.scene_spec.path) != expected:
            raise ValueError("solid-root source selection changed during actual extraction")
        directory = output.with_name(output.stem + "_bound_inputs")
        directory.mkdir(parents=True, exist_ok=False)
        snapshots = []
        for role, selected_input, name in (
            ("intent", expected, "intent.json"),
            (
                "camera_hypothesis",
                intent.source_camera_hypothesis.model_dump(mode="json"),
                "camera_hypothesis.json",
            ),
        ):
            data = artifact_bytes(root, selected_input)
            path = directory / name
            with path.open("xb") as stream:
                stream.write(data)
            snapshots.append(
                {
                    "role": role,
                    "source": selected_input,
                    "snapshot": {"path": path.relative_to(root).as_posix(), "sha256": _sha(path)},
                }
            )
        report["bound_intent_snapshots"] = snapshots
    selected_regions = (
        []
        if isinstance(intent, SolidRootAttachmentIntentV01)
        else [entry for entry in intent.entries if entry.root_region is not None]
    )
    if selected_regions:
        directory = output.with_name(output.stem + "_root_regions")
        directory.mkdir(parents=True, exist_ok=False)
        snapshots = []
        for entry in selected_regions:
            data = artifact_bytes(root, entry.root_region.model_dump(mode="json"))
            path = directory / _region_snapshot_name(entry.attachment_id)
            with path.open("xb") as stream:
                stream.write(data)
            snapshots.append(
                {
                    "attachment_id": entry.attachment_id,
                    "source": entry.root_region.model_dump(mode="json"),
                    "snapshot": {"path": path.relative_to(root).as_posix(), "sha256": _sha(path)},
                }
            )
        report["root_region_snapshots"] = snapshots
    from ..qa.attachment_occupancy import evaluate_reference_region_occupancy

    coverage = evaluate_reference_region_occupancy(
        root,
        intent,
        raw,
        output_dir=output.with_name(output.stem + "_reference_occupancy"),
    )
    if coverage["selected"]:
        coverage["actual_geometry_origin_verified"] = True
    report["reference_region_coverage"] = coverage
    if coverage["selected"] and coverage["status"] != "passed":
        report["status"] = "failed"
    report.update(
        {
            "stage": stage,
            "artifact": expected_projection["artifact"],
            "intent": expected,
            "extraction_sha256": _sha(output),
            "actual_triangle_extraction_verified": True,
            "source_fingerprint": source.source_fingerprint,
            "build_fingerprint": source.build_fingerprint,
        }
    )
    _write_once(output.with_name(output.stem + "_report.json"), report)
    if report["status"] != "passed":
        raise ValueError("required selected attachment is failed or unverified")
    return report


def _capture_stage_evidence(root: Path, audit: Path, stage: str, report: dict) -> dict[str, str]:
    """Seal each finished stage immediately, including every explicitly selected diagnostic."""
    if report.get("status") != "passed":
        raise ValueError("attachment stage did not return a passing report")
    extraction = contained_file(root, (audit / f"{stage}.json").relative_to(root).as_posix())
    if _sha(extraction) != report["extraction_sha256"]:
        raise ValueError("finished attachment extraction differs from its inspected hash")
    report_path = contained_file(
        root, (audit / f"{stage}_report.json").relative_to(root).as_posix()
    )
    report_bytes = report_path.read_bytes()
    if json.loads(report_bytes) != report:
        raise ValueError("finished attachment report differs from its inspected result")
    files = {
        extraction.relative_to(audit).as_posix(): report["extraction_sha256"],
        report_path.relative_to(audit).as_posix(): hashlib.sha256(report_bytes).hexdigest(),
    }
    if report.get("kind") == "solid_root_attachment_report":
        selected_inputs = report.get("bound_intent_snapshots", [])
        if len(selected_inputs) != 2 or {item.get("role") for item in selected_inputs} != {
            "intent",
            "camera_hypothesis",
        }:
            raise ValueError("solid-root finished evidence lacks exact intent/camera snapshots")
        captured = {}
        for item in selected_inputs:
            name = "intent.json" if item["role"] == "intent" else "camera_hypothesis.json"
            path = audit / f"{stage}_bound_inputs" / name
            expected = item["snapshot"]
            if expected["path"] != path.relative_to(root).as_posix():
                raise ValueError("solid-root snapshot has a foreign path")
            data = artifact_bytes(root, expected)
            if expected["sha256"] != item["source"]["sha256"]:
                raise ValueError("solid-root copied source snapshot hash differs")
            if artifact_bytes(root, item["source"]) != data:
                raise ValueError("solid-root live source differs from snapshot")
            captured[item["role"]] = (item, data)
            files[path.relative_to(audit).as_posix()] = expected["sha256"]
        selected_intent = SolidRootAttachmentIntentV01.model_validate_json(captured["intent"][1])
        if (
            captured["intent"][0]["source"] != report["intent"]
            or selected_intent.source_camera_hypothesis.model_dump(mode="json")
            != captured["camera_hypothesis"][0]["source"]
        ):
            raise ValueError("solid-root snapshot dependencies are mixed")
    coverage = report["reference_region_coverage"]
    if coverage["selected"]:
        if coverage["status"] != "passed":
            raise ValueError("selected reference occupancy has no passing evidence")
        directory = audit / f"{stage}_reference_occupancy"
        for key, name in (
            ("projection", "projection.png"),
            ("trimap_snapshot", "reference_trimap.png"),
        ):
            expected = coverage[key]
            relative = (directory / name).relative_to(root).as_posix()
            if expected["path"] != relative:
                raise ValueError("selected occupancy diagnostic has a foreign path")
            path = contained_file(root, relative)
            if _sha(path) != expected["sha256"]:
                raise ValueError("selected occupancy diagnostic differs from its inspected hash")
            files[path.relative_to(audit).as_posix()] = expected["sha256"]
        coverage_path = contained_file(
            root, (directory / "report.json").relative_to(root).as_posix()
        )
        coverage_bytes = coverage_path.read_bytes()
        expected_coverage = {**coverage, "actual_geometry_origin_verified": False}
        if json.loads(coverage_bytes) != expected_coverage:
            raise ValueError("selected occupancy report differs from its inspected result")
        files[coverage_path.relative_to(audit).as_posix()] = hashlib.sha256(
            coverage_bytes
        ).hexdigest()
    expected_regions = {
        row["attachment_id"]: row["root_region"]
        for row in report.get("entries", [])
        if "root_region" in row
    }
    snapshots = report.get("root_region_snapshots", [])
    ids = [item["attachment_id"] for item in snapshots]
    if len(ids) != len(set(ids)) or set(ids) != set(expected_regions):
        raise ValueError("selected root region snapshots are missing, extra or duplicated")
    for item in snapshots:
        artifact = item["snapshot"]
        relative = (
            (audit / f"{stage}_root_regions" / _region_snapshot_name(item["attachment_id"]))
            .relative_to(root)
            .as_posix()
        )
        if (
            item["source"] != expected_regions[item["attachment_id"]]
            or artifact["path"] != relative
            or artifact["sha256"] != item["source"]["sha256"]
        ):
            raise ValueError("root region snapshot differs from the inspected source selection")
        path = contained_file(root, relative)
        if _sha(path) != artifact["sha256"]:
            raise ValueError("root region snapshot changed after inspection")
        files[path.relative_to(audit).as_posix()] = artifact["sha256"]
    _verify_finished_files(root, audit, files)
    return files


def _verify_finished_files(root: Path, directory: Path, files: dict[str, str]) -> None:
    """Rehash the complete sealed closure, refusing missing files and any linked replacement."""
    for name, expected in files.items():
        path = contained_file(root, (directory / name).relative_to(root).as_posix())
        if _sha(path) != expected:
            raise ValueError("finished attachment evidence changed before publication: " + name)


def _verify_package_attachment_closure(root: Path, closure: dict[str, Any]) -> None:
    """Recheck only the in-memory seal returned by the fixed package inspector before rename.

    This is an internal continuation of that invocation, never a file-loaded or
    caller-authored substitute for running the native inspections.
    """
    _verify_finished_files(root, root / closure["audit_directory"], closure["audit_files"])
    _verify_finished_files(root, root / closure["package_directory"], closure["package_files"])
    _verify_finished_files(root, root, closure["inspected_artifacts"])


def verify_package_attachment(
    root: Path,
    source: SourceProvenance,
    *,
    run_id: str,
    package_id: str,
    converted: Path,
    primary: Path,
    staging_root: Path,
) -> dict[str, Any] | None:
    """Check selected native/converted/imported triangles before immutable package publication."""
    if source.attachment_intent is None:
        return
    if primary.suffix.lower() != ".glb":
        raise ValueError("selected attachment package check currently supports GLB only")
    audit = root / "optimization/runs" / run_id / "attachment_checks" / package_id
    audit.mkdir(parents=True, exist_ok=False)
    # Keep exact failed export bytes outside the package transaction's staging cleanup.
    retained_primary = audit / "asset.glb"
    shutil.copyfile(primary, retained_primary)
    primary_hash = _sha(primary)
    if _sha(retained_primary) != primary_hash:
        raise ValueError("attachment export snapshot differs from staged package")
    reports = []
    finished_files = {}
    inspected_artifacts = {}
    for stage, artifact in (
        ("native_evaluated", root / source.blend.path),
        ("converted", converted),
        ("clean_import_glb", retained_primary),
    ):
        artifact_hash = _sha(artifact)
        report = inspect_stage(root, source, artifact, stage, audit / f"{stage}.json")
        finished_files.update(_capture_stage_evidence(root, audit, stage, report))
        if _sha(artifact) != artifact_hash:
            raise ValueError("attachment stage artifact changed during inspection")
        inspected_artifacts[artifact.relative_to(root).as_posix()] = artifact_hash
        for item in report.get("root_region_snapshots", []) + report.get(
            "bound_intent_snapshots", []
        ):
            inspected_artifacts[item["source"]["path"]] = item["source"]["sha256"]
        reports.append(report)
    destination = staging_root / "metadata/attachment"
    destination.mkdir(parents=True, exist_ok=False)
    if _sha(primary) != primary_hash:
        raise ValueError("staged GLB changed during attachment checks")
    _verify_finished_files(root, audit, finished_files)
    _verify_finished_files(root, root, inspected_artifacts)
    for name, expected in finished_files.items():
        _verify_finished_files(root, audit, {name: expected})
        path = contained_file(root, (audit / name).relative_to(root).as_posix())
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        _verify_finished_files(root, audit, {name: expected})
        _verify_finished_files(root, destination, {name: expected})
    _verify_finished_files(root, audit, finished_files)
    _verify_finished_files(root, destination, finished_files)
    _verify_finished_files(root, root, inspected_artifacts)
    if _sha(primary) != primary_hash:
        raise ValueError("staged GLB changed while attachment evidence was copied")
    _write_once(
        destination / "summary.json",
        {
            "status": "passed",
            "stages": reports,
            "primary_glb_sha256": primary_hash,
            "final_human_acceptance": False,
            "source": source.attachment_intent.model_dump(mode="json"),
            "evidence_files": finished_files,
            "inspected_artifacts": inspected_artifacts,
        },
    )
    closure = {
        "audit_directory": audit.relative_to(root).as_posix(),
        "package_directory": destination.relative_to(root).as_posix(),
        "audit_files": finished_files,
        "package_files": {
            **finished_files,
            "summary.json": _sha(destination / "summary.json"),
        },
        "inspected_artifacts": {
            **inspected_artifacts,
            primary.relative_to(root).as_posix(): primary_hash,
        },
    }
    _verify_package_attachment_closure(root, closure)
    return closure
