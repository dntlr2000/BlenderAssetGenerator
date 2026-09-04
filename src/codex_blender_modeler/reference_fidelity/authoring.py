"""Observation-bound structural staging using existing recipes, with no asset-name dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from ..analysis.models import ModelingPlan
from ..autonomy.io import write_immutable_json
from ..models import SceneSpec
from ..qa.camera_fingerprint import camera_fingerprint
from ..structural_geometry.mesh_math import build_loft_mesh, build_sweep_mesh
from ..structural_geometry.models import SceneSpecV03
from .models import FidelityArtifact, FidelityModel, ModelingHypothesisV01
from .service import artifact_at, read_artifact


class StructureAuthoringV01(FidelityModel):
    """Bind an authored 3D recipe and spatial plan to independent observed requirements."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["reference_structure_authoring"] = "reference_structure_authoring"
    hypothesis: FidelityArtifact
    scene: SceneSpecV03
    modeling_plan: ModelingPlan
    representation_rationale: str = Field(min_length=16)
    source_candidate: FidelityArtifact | None = None
    reuse_purpose: Literal["none", "comparison_baseline", "explicit_revision_start"] = "none"
    canonical_write_authority: Literal[False] = False


def validate_structure_authoring(
    root: Path, authoring: StructureAuthoringV01
) -> ModelingHypothesisV01:
    """Validate camera, observations, target membership and spatial intent before staging."""

    hypothesis = ModelingHypothesisV01.model_validate_json(
        read_artifact(root, authoring.hypothesis)
    )
    read_artifact(root, hypothesis.reference)
    if (authoring.scene.job_id, authoring.modeling_plan.job_id) != (hypothesis.job_id,) * 2:
        raise ValueError("structural authoring identity differs from observation hypothesis")
    if (
        camera_fingerprint(authoring.scene.camera.model_dump(mode="json"))
        != hypothesis.camera.camera_fingerprint
    ):
        raise ValueError("structural authoring changed the frozen camera hypothesis")
    if authoring.modeling_plan.assembly_consistency_policy != "spatial_v1":
        raise ValueError("reference-fidelity authoring requires the existing spatial_v1 plan")
    if authoring.modeling_plan.stage != "authored":
        raise ValueError("structural authoring requires a completed semantic decomposition")
    objects = {item.id: item for item in authoring.scene.objects}
    planned = {item.id: item for item in authoring.modeling_plan.objects}
    if set(planned) != set(objects):
        raise ValueError("spatial plan and structural scene semantic membership differ")
    if (authoring.source_candidate is None) != (authoring.reuse_purpose == "none"):
        raise ValueError("candidate reuse must declare its exact source and limited purpose")
    if authoring.source_candidate is not None:
        read_artifact(root, authoring.source_candidate)
    observations = {item.observation_id: item for item in hypothesis.observations}
    for requirement in hypothesis.requirements:
        if requirement.applicability == "not_applicable":
            continue
        if not set(requirement.target_ids) <= objects.keys():
            raise ValueError("candidate omits an expected observed part")
        for target_id in requirement.target_ids:
            # The expected bbox must come from observations, never the candidate's mesh bounds.
            observed_regions = [observations[key].region for key in requirement.observation_ids]
            bbox = planned[target_id].bbox_norm
            if bbox is None or not all(
                bbox[0] <= region[0]
                and bbox[1] <= region[1]
                and bbox[2] >= region[2]
                and bbox[3] >= region[3]
                for region in observed_regions
            ):
                raise ValueError(
                    "semantic evidence bbox does not contain its independent observations"
                )
    if (
        hypothesis.representation == "assembly"
        and not authoring.modeling_plan.assembly_relationships
    ):
        raise ValueError(
            "multi-part assembly needs explicit relationships, not only semantic names"
        )
    return hypothesis


def stage_structure_authoring(
    root: Path, authoring: StructureAuthoringV01, output_dir: Path
) -> dict[str, FidelityArtifact]:
    """Write only new staging candidates; actual host validation/promotion remains mandatory."""

    validate_structure_authoring(root, authoring)
    relative = output_dir.relative_to(root).as_posix()
    allowed = ("geometry/candidates/", "fidelity/")
    if not any(relative.startswith(prefix) for prefix in allowed):
        raise PermissionError("structure authoring outputs must remain in declared staging")
    result = {}
    for name, model in (
        ("scene_spec_v03.json", authoring.scene),
        ("modeling_plan.json", authoring.modeling_plan),
        ("structure_authoring.json", authoring),
    ):
        path = output_dir / name
        write_immutable_json(root, path, model.model_dump(mode="json"))
        result[name] = artifact_at(root, path)
    return result


def compile_preview_candidate(
    root: Path, authoring: StructureAuthoringV01, output_dir: Path
) -> FidelityArtifact:
    """Compile an isolated SceneSpec 0.2 preview; never promote or fake AQ receipts."""

    validate_structure_authoring(root, authoring)
    relative = output_dir.relative_to(root).as_posix()
    if not relative.startswith(("geometry/candidates/", "fidelity/")):
        raise PermissionError("preview compilation must remain in isolated staging")
    data = authoring.scene.model_dump(mode="json")
    data["schema_version"] = "0.2.0"
    for obj in data["objects"]:
        intent = obj.pop("geometry_intent", None)
        kind = obj["geometry"]["kind"]
        if kind in {"loft", "sweep"}:
            compiler = build_loft_mesh if kind == "loft" else build_sweep_mesh
            mesh = compiler(obj["geometry"])
            path = output_dir / f"{obj['id']}.mesh.json"
            # Keep intent beside the preview. The AQ host separately compiles strict MeshPayloadV02.
            write_immutable_json(root, path, {"vertices": mesh["vertices"], "faces": mesh["faces"]})
            if intent is not None:
                write_immutable_json(root, output_dir / f"{obj['id']}.intent.json", intent)
            obj["geometry"] = {"kind": "custom_mesh", "path": path.relative_to(root).as_posix()}
    scene = SceneSpec.model_validate(data)
    path = output_dir / "scene_spec.json"
    write_immutable_json(root, path, scene.model_dump(mode="json"))
    return artifact_at(root, path)
