"""Bound closed-solid root-ball evaluation behind exact source and actual-triangle identity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..attachment_runtime import artifact_bytes, contained_file
from ..structural_geometry.mesh_payload_v02 import MeshPayloadV02
from ..structural_geometry.solid_attachment_companion import SolidRootAttachmentIntentV01
from ..structural_geometry.solid_root_ball import Budget, certify_ball, prepare_solid
from ..workspace import resolve_job_input_path


def load_solid_source_meshes(
    root: Path, intent: SolidRootAttachmentIntentV01,
    *, prospective_sources: dict[str, bytes] | None = None,
) -> dict[str, MeshPayloadV02]:
    """Apply identical source proof gates to canonical or exact prospective scene/plan bytes."""
    if prospective_sources is not None and set(prospective_sources) != {
        "analysis/scene_spec.json", "analysis/modeling_plan.json"
    }:
        raise ValueError("solid-root prospective sources require exactly canonical scene and plan")

    def source_bytes(artifact):
        """Read only the two hash-bound prospective inputs; all dependencies remain real files."""
        if prospective_sources is None:
            return artifact_bytes(root, artifact.model_dump(mode="json"))
        data = prospective_sources[artifact.path]
        if len(data) > 8 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != artifact.sha256:
            raise ValueError("solid-root prospective source hash changed")
        return data

    metadata = json.loads(contained_file(root, "job.json").read_bytes())
    references = [x for x in metadata.get("sources", []) if x.get("kind") == "reference"]
    if len(references) != 1:
        raise ValueError("solid-root source requires one exact primary reference")
    reference = resolve_job_input_path(root, references[0]["path"], references[0].get("sha256"))
    if reference != contained_file(root, intent.source_reference.path):
        raise ValueError("solid-root primary reference differs")
    artifact_bytes(root, intent.source_reference.model_dump(mode="json"))
    scene = json.loads(source_bytes(intent.source_scene))
    plan = json.loads(source_bytes(intent.source_modeling_plan))
    if (
        intent.source_scene.path != "analysis/scene_spec.json"
        or intent.source_modeling_plan.path != "analysis/modeling_plan.json"
        or scene.get("job_id") != intent.job_id
        or plan.get("job_id") != intent.job_id
        or metadata.get("job_id") != intent.job_id
    ):
        raise ValueError("solid-root sources must be this job's canonical scene and plan")
    camera = json.loads(
        artifact_bytes(root, intent.source_camera_hypothesis.model_dump(mode="json"))
    )
    if (
        not isinstance(camera, dict)
        or set(camera)
        != {
            "schema_version",
            "contract_kind",
            "job_id",
            "reference",
            "camera",
            "calibration_status",
            "assumptions",
        }
        or camera["schema_version"] != "0.1.0"
        or camera["contract_kind"] != "reference_camera_hypothesis"
        or camera["job_id"] != intent.job_id
        or camera["reference"] != intent.source_reference.model_dump(mode="json")
        or camera["camera"] != scene.get("camera")
        or camera["calibration_status"] != "hypothesis_not_unique_recovery"
        or not isinstance(camera["assumptions"], list)
        or not 1 <= len(camera["assumptions"]) <= 32
        or any(
            not isinstance(x, str) or not 1 <= len(x.strip()) <= 2000 for x in camera["assumptions"]
        )
    ):
        raise ValueError("solid-root camera hypothesis is malformed or differs from the scene")
    objects = {obj["id"]: obj for obj in scene["objects"]}
    if len(objects) != len(scene["objects"]) or set(objects) != set(intent.required_semantics):
        raise ValueError("solid-root required semantic scope must include the complete asset")
    meshes: dict[str, MeshPayloadV02] = {}
    total_bytes = total_triangles = 0
    for artifact in intent.source_geometry:
        data = artifact_bytes(root, artifact.model_dump(mode="json"))
        total_bytes += len(data)
        raw = json.loads(data)
        if (
            total_bytes > 32 * 1024 * 1024
            or not isinstance(raw, dict)
            or not isinstance(raw.get("vertices"), list)
            or len(raw["vertices"]) > 8192
            or not isinstance(raw.get("faces"), list)
            or len(raw["faces"]) > 4096
        ):
            raise ValueError("solid-root source exceeds bounded geometry/byte limits")
        total_triangles += len(raw["faces"])
        if total_triangles > 25_000:
            raise ValueError("solid-root aggregate asset triangle limit exceeded")
        mesh = MeshPayloadV02.model_validate_json(data)
        for dependency in mesh.source_hashes:
            artifact_bytes(root, {"path": dependency.path, "sha256": dependency.sha256})
        obj = objects.get(mesh.semantic_id)
        if (
            obj is None
            or obj["geometry"].get("kind") != "custom_mesh"
            or obj["geometry"].get("path") != artifact.path
        ):
            raise ValueError("solid-root payload is not the selected semantic's actual geometry")
        transform = obj.get("transform", {})
        if (
            transform.get("location") != [0, 0, 0]
            or transform.get("rotation_deg") != [0, 0, 0]
            or transform.get("scale") != [1, 1, 1]
            or obj.get("modifiers")
            or obj.get("generator")
            or obj.get("parent_id")
        ):
            raise ValueError("solid-root source requires explicit unmodified world-space geometry")
        if (
            any(len(face) != 3 for face in mesh.faces)
            or len(mesh.material_slots) != 1
            or mesh.source_geometry_intent.topology_profile != "static_prop_closed"
            or mesh.semantic_id in meshes
        ):
            raise ValueError(
                "solid-root source must be unique triangulated single-slot closed solids"
            )
        meshes[mesh.semantic_id] = mesh
    if set(meshes) != set(intent.required_semantics):
        raise ValueError(
            "solid-root source payload scope is missing or contains unrelated geometry"
        )
    return meshes


def evaluate_solid_actual(
    intent: SolidRootAttachmentIntentV01,
    meshes: dict[str, MeshPayloadV02],
    raw: dict[str, Any],
) -> dict[str, Any]:
    """Recompute complete mapped solids and local balls without asserting native extraction."""
    from .attachment import map_actual_mesh

    # Revalidate an in-memory host object as well as JSON-loaded instances.
    intent = SolidRootAttachmentIntentV01.model_validate_json(intent.model_dump_json())
    if set(meshes) != set(intent.required_semantics):
        raise ValueError("solid-root bound source semantic set differs")
    records = raw.get("objects")
    if not isinstance(records, list) or not 2 <= len(records) <= 128:
        raise ValueError("solid-root actual object array is invalid")
    if any(not isinstance(x, dict) or set(x) != {"semantic_id", "triangles"} for x in records):
        raise ValueError("solid-root actual semantic record is malformed")
    identities = [x["semantic_id"] for x in records]
    if len(set(identities)) != len(identities) or set(identities) != set(meshes):
        raise ValueError("solid-root actual semantic scope is duplicated, omitted or extra")
    if sum(len(x["triangles"]) for x in records) > 25_000:
        raise ValueError("solid-root actual aggregate triangle limit exceeded")
    by_id = {x["semantic_id"]: x for x in records}
    mapped = {key: map_actual_mesh(mesh, by_id[key]) for key, mesh in meshes.items()}
    budget = Budget()
    solids = {}
    for key in sorted(mapped):
        item = mapped[key]
        if any(vertex is None for vertex in item["vertices"]):
            raise ValueError("solid-root complete boundary has an unused or missing vertex")
        solids[key] = prepare_solid(item["vertices"], item["triangles"], budget)
    rows = []
    for entry in intent.entries:
        owner = certify_ball(
            solids[entry.owner_semantic_id], entry.center, entry.radius_m, entry.root_bounds, budget
        )
        subject = certify_ball(
            solids[entry.subject_semantic_id],
            entry.center,
            entry.radius_m,
            entry.root_bounds,
            budget,
        )
        rows.append(
            {
                **entry.model_dump(mode="json"),
                "status": "passed",
                "owner_certificate": owner,
                "subject_certificate": subject,
                "seam_wide_coverage_claimed": False,
            }
        )
    return {
        "schema_version": "0.1.0",
        "kind": "solid_root_attachment_report",
        "status": "passed",
        "proof_domain": "connected_closed_embedded_solids_local_overlap_balls",
        "source_correspondence_verified": True,
        "required_graph_connected": True,
        "entries": rows,
        "required_component_count": len(solids),
        "aggregate_triangle_count": budget.triangle_count,
        "aggregate_embedding_work_units": budget.embedding_scans[0],
        "aggregate_root_predicate_visits": budget.used,
        "correspondence": {
            "position_policy": "source_binary32_equals_actual_world_exactly",
            "maximum_position_error_m": max(x["maximum_position_error_m"] for x in mapped.values()),
            "objects": [
                {
                    "semantic_id": key,
                    "triangle_count": len(value["triangles"]),
                    "correspondence_checks": value["correspondence_checks"],
                }
                for key, value in sorted(mapped.items())
            ],
        },
        "seam_wide_coverage_claimed": False,
        "mechanical_strength_claimed": False,
        "visual_fidelity_claimed": False,
        "actual_triangle_extraction_verified": False,
        "final_human_acceptance": False,
    }
