"""Host tests for optional SceneSpecV03 reachability in AQ candidate staging."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from codex_blender_modeler.autonomy.authorization import artifact_for
from codex_blender_modeler.autonomy.candidate_evaluator import (
    _compile_optional_structural_scene,
    _validate_scene_spec_v03_mirror,
)
from codex_blender_modeler.autonomy.models import (
    AutonomyArtifact,
    CandidateAuthoringAssignment,
)
from codex_blender_modeler.blender_artifacts import sha256_file, stable_json_digest
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.structural_geometry.models import (
    SceneSpecV03,
    StructuralGeometryCandidate,
    StructuralMeshPayload,
)


def _object_payload(object_id: str, *, location_x: float) -> dict[str, Any]:
    """Return one legacy object whose identity must survive structural compilation."""

    return {
        "id": object_id,
        "name": object_id.replace(".", " ").title(),
        "geometry": {
            "kind": "primitive",
            "primitive": "cube",
            "dimensions": [1.0, 0.8, 1.2],
            "segments": 16,
            "ring_segments": 8,
        },
        "transform": {
            "location": [location_x, 0.0, 0.6],
            "rotation_deg": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        },
        "material_id": "mat.body",
        "modifiers": [],
        "generator": None,
        "parent_id": None,
        "shade_smooth": False,
        "tags": ["qa_role:primary", "scope:primary"],
        "evidence": [
            {
                "source_id": "ref.main",
                "bbox_norm": [0.15, 0.2, 0.85, 0.8],
                "status": "observed",
                "confidence": 0.9,
            }
        ],
        "editable": {},
    }


def _legacy_scene_payload(job_id: str) -> dict[str, Any]:
    """Return one valid V0.2 candidate containing two stable object identities."""

    return {
        "schema_version": "0.2.0",
        "job_id": job_id,
        "mode": "concept",
        "units": "METERS",
        "coordinate_system": {"handedness": "RIGHT", "up": "+Z", "forward": "-Y"},
        "nominal_scene_size": [6.0, 4.0, 3.0],
        "sources": [
            {
                "id": "ref.main",
                "path": "input/reference.png",
                "kind": "reference",
                "immutable": True,
                "scale_anchors": [],
            }
        ],
        "materials": [
            {
                "id": "mat.body",
                "name": "Body",
                "shader": "principled",
                "base_color": [0.2, 0.4, 0.7, 1.0],
                "roughness": 0.45,
                "metallic": 0.05,
                "emission_strength": 0.0,
                "texture_manifest": None,
            }
        ],
        "objects": [
            _object_payload("product.hull", location_x=-1.25),
            _object_payload("product.rail", location_x=1.25),
        ],
        "camera": {
            "projection": "ORTHO",
            "location": [5.0, -8.0, 5.0],
            "target": [0.0, 0.0, 0.6],
            "focal_length_mm": 50.0,
            "ortho_scale": 6.5,
            "resolution": [128, 128],
        },
        "assumptions": ["Hidden surfaces remain inferred."],
        "revision_notes": [],
    }


def _scene_v03_payload(legacy: dict[str, Any]) -> dict[str, Any]:
    """Replace both legacy placeholder geometries with independent structural recipes."""

    payload = json.loads(json.dumps(legacy))
    payload["schema_version"] = "0.3.0"
    payload["objects"][0]["geometry"] = {
        "kind": "loft",
        "sections": [
            {
                "closed": True,
                "points": [
                    [-1.0, -0.6, 0.0],
                    [1.0, -0.6, 0.0],
                    [1.0, 0.6, 0.0],
                    [-1.0, 0.6, 0.0],
                ],
            },
            {
                "closed": True,
                "points": [
                    [-0.7, -0.4, 1.2],
                    [0.7, -0.4, 1.2],
                    [0.7, 0.4, 1.2],
                    [-0.7, 0.4, 1.2],
                ],
            },
        ],
        "resample_count": 4,
        "cap_policy": "ends",
        "correspondence_policy": "index",
        "twist_offsets": [],
    }
    payload["objects"][1]["geometry"] = {
        "kind": "sweep",
        "profile": [[-0.15, -0.1], [0.15, -0.1], [0.15, 0.1], [-0.15, 0.1]],
        "profile_closed": True,
        "path": [[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.4, 0.0, 1.8]],
        "path_closed": False,
        "scales": [],
        "twist_degrees": [],
        "cap_policy": "ends",
    }
    return payload


def _artifact(path: str) -> AutonomyArtifact:
    """Return a deterministic placeholder artifact for assignment-only evidence."""

    return AutonomyArtifact(path=path, sha256="1" * 64)


def _assignment(output_root: str, *, structural: bool) -> CandidateAuthoringAssignment:
    """Construct one strict assignment with optional SceneSpecV03 authoring authority."""

    now = datetime.now(UTC)
    return CandidateAuthoringAssignment(
        contract_id="assignment-candidate-01",
        job_id="structural_reachability",
        workflow_id="wf-structural-reachability",
        dispatch_id="dispatch-structural-reachability",
        input_sha256="2" * 64,
        source_fingerprint="3" * 64,
        producer="tests",
        producer_version="0.1.0",
        provenance=[_artifact("reference_evidence/reference.json")],
        created_at=now,
        assignment_id="assignment-candidate-01",
        session_id="session-structural-reachability",
        candidate_id="candidate-01",
        candidate_index=1,
        candidate_phase="initial",
        reference_evidence=_artifact("reference_evidence/reference.json"),
        camera_hypothesis_set=_artifact("reference_evidence/cameras.json"),
        output_root=output_root,
        required_outputs=[
            f"{output_root}/modeling_plan.json",
            f"{output_root}/camera_hypothesis.json",
            f"{output_root}/scene_spec.json",
        ],
        scene_spec_v03_output=(
            f"{output_root}/scene_spec_v03.json" if structural else None
        ),
        authoring_prompt_sha256="4" * 64,
    )


def _fake_materializer(
    *,
    job_root: Path,
    candidate: StructuralGeometryCandidate | dict[str, Any],
    candidate_relative_path: str,
    mesh_relative_path: str,
    blend_relative_path: str,
    report_relative_path: str,
) -> StructuralMeshPayload:
    """Publish deterministic stand-in artifacts with the real materializer receipt contract."""

    recipe = (
        candidate
        if isinstance(candidate, StructuralGeometryCandidate)
        else StructuralGeometryCandidate.model_validate(candidate)
    )
    paths = {
        "recipe": job_root / candidate_relative_path,
        "mesh": job_root / mesh_relative_path,
        "blend": job_root / blend_relative_path,
        "report": job_root / report_relative_path,
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    paths["recipe"].write_text(recipe.model_dump_json(indent=2) + "\n", encoding="utf-8")
    mesh = StructuralMeshPayload(
        semantic_id=recipe.semantic_id,
        builder_kind=recipe.geometry.kind,
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[[0, 1, 2]],
        geometry_intent=recipe.geometry_intent,
    )
    paths["mesh"].write_text(mesh.model_dump_json(indent=2) + "\n", encoding="utf-8")
    paths["blend"].write_bytes(b"isolated-structural-materialization")
    report = {
        "schema_version": "0.1.0",
        "status": "passed",
        "semantic_id": recipe.semantic_id,
        "builder_kind": recipe.geometry.kind,
        "candidate_sha256": stable_json_digest(recipe.model_dump(mode="json")),
        "mesh_sha256": sha256_file(paths["mesh"]),
        "blend_sha256": sha256_file(paths["blend"]),
        "vertex_count": 3,
        "polygon_count": 1,
    }
    paths["report"].write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return mesh


def test_compiles_full_v03_candidate_to_multiple_path_backed_v02_meshes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Materialize every structural object while preserving canonical and legacy evidence."""

    root = tmp_path / "structural_reachability"
    output_root = "workflows/wf/artifacts/candidates/candidate-01"
    candidate_root = root / output_root
    candidate_root.mkdir(parents=True)
    legacy_payload = _legacy_scene_payload(root.name)
    legacy = SceneSpec.model_validate(legacy_payload)
    legacy_path = candidate_root / "scene_spec.json"
    legacy_path.write_text(legacy.model_dump_json(indent=2) + "\n", encoding="utf-8")
    canonical_path = root / "analysis" / "scene_spec.json"
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_text(legacy.model_dump_json(indent=2) + "\n", encoding="utf-8")
    canonical_before = sha256_file(canonical_path)
    v03 = SceneSpecV03.model_validate_json(
        json.dumps(_scene_v03_payload(legacy_payload))
    )
    (candidate_root / "scene_spec_v03.json").write_text(
        v03.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy.candidate_evaluator."
        "materialize_structural_candidate",
        _fake_materializer,
    )

    compilation = _compile_optional_structural_scene(
        root,
        candidate_root,
        _assignment(output_root, structural=True),
        legacy,
        artifact_for(root, legacy_path),
    )

    assert compilation.compiled_scene_spec_artifact is not None
    assert compilation.scene_spec_v03_artifact is not None
    assert len(compilation.recipe_artifacts) == 2
    assert len(compilation.mesh_payload_artifacts) == 2
    assert len(compilation.materialization_receipts) == 2
    assert len(compilation.additional_provenance) == 2
    assert [item.id for item in compilation.scene.objects] == [
        "product.hull",
        "product.rail",
    ]
    assert {item.geometry.kind for item in compilation.scene.objects} == {"custom_mesh"}
    mesh_paths = [item.geometry.path for item in compilation.scene.objects]
    assert len(set(mesh_paths)) == 2
    assert all(path is not None and (root / path).is_file() for path in mesh_paths)
    assert sha256_file(canonical_path) == canonical_before
    assert SceneSpec.model_validate_json(legacy_path.read_text(encoding="utf-8")) == legacy


def test_legacy_three_output_assignment_remains_valid(tmp_path: Path) -> None:
    """Keep candidates without the optional V03 artifact on the unchanged legacy path."""

    root = tmp_path / "structural_reachability"
    output_root = "workflows/wf/artifacts/candidates/candidate-01"
    candidate_root = root / output_root
    candidate_root.mkdir(parents=True)
    legacy = SceneSpec.model_validate(_legacy_scene_payload(root.name))
    legacy_path = candidate_root / "scene_spec.json"
    legacy_path.write_text(legacy.model_dump_json(indent=2) + "\n", encoding="utf-8")
    assignment = _assignment(output_root, structural=False)

    compilation = _compile_optional_structural_scene(
        root,
        candidate_root,
        assignment,
        legacy,
        artifact_for(root, legacy_path),
    )

    assert assignment.scene_spec_v03_output is None
    assert compilation.scene == legacy
    assert compilation.effective_scene_path == legacy_path
    assert compilation.scene_spec_v03_artifact is None
    assert compilation.compiled_scene_spec_artifact is None
    assert not compilation.recipe_artifacts
    assert not compilation.mesh_payload_artifacts
    assert not compilation.materialization_receipts


def test_rejects_v03_identity_or_transform_drift() -> None:
    """Fail closed when a structural companion changes non-geometry candidate meaning."""

    legacy_payload = _legacy_scene_payload("structural_reachability")
    v03_payload = _scene_v03_payload(legacy_payload)
    v03_payload["objects"][0]["transform"]["location"][0] = 99.0
    with pytest.raises(PermissionError, match="identity, material, transform"):
        _validate_scene_spec_v03_mirror(
            SceneSpec.model_validate(legacy_payload),
            SceneSpecV03.model_validate_json(json.dumps(v03_payload)),
        )


def test_rejects_undeclared_v03_artifact(tmp_path: Path) -> None:
    """Treat an unexpected structural companion as unauthorized controller output."""

    root = tmp_path / "structural_reachability"
    output_root = "workflows/wf/artifacts/candidates/candidate-01"
    candidate_root = root / output_root
    candidate_root.mkdir(parents=True)
    legacy_payload = _legacy_scene_payload(root.name)
    legacy = SceneSpec.model_validate(legacy_payload)
    legacy_path = candidate_root / "scene_spec.json"
    legacy_path.write_text(legacy.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (candidate_root / "scene_spec_v03.json").write_text(
        SceneSpecV03.model_validate_json(
            json.dumps(_scene_v03_payload(legacy_payload))
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PermissionError, match="undeclared SceneSpecV03"):
        _compile_optional_structural_scene(
            root,
            candidate_root,
            _assignment(output_root, structural=False),
            legacy,
            artifact_for(root, legacy_path),
        )
