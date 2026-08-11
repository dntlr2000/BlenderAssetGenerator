"""Verify additive MeshPayload 0.2 reachability without changing legacy defaults."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from codex_blender_modeler.autonomy.authorization import artifact_for
from codex_blender_modeler.autonomy.candidate_evaluator import (
    _build_candidate,
    _compile_optional_structural_scene,
)
from codex_blender_modeler.autonomy.models import CandidateAuthoringAssignment
from codex_blender_modeler.blender_artifacts import sha256_file, stable_json_digest
from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.structural_geometry.mesh_payload_compiler_v02 import (
    MeshPayloadV02CompileReport,
)
from codex_blender_modeler.structural_geometry.mesh_payload_io_v02 import (
    load_mesh_payload_v02,
)
from codex_blender_modeler.structural_geometry.models import (
    StructuralGeometryCandidate,
    StructuralMeshPayload,
)
from codex_blender_modeler.structural_geometry.service import (
    materialize_structural_candidate,
)


def _loft_geometry() -> dict[str, Any]:
    """Return one closed eight-face loft with predictable edge and face indices."""

    return {
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


def _geometry_intent() -> dict[str, Any]:
    """Return explicit non-legacy intent covering every required v2 channel."""

    return {
        "face_groups": [{"id": "body", "face_indices": list(range(8))}],
        "sharp_edges": [{"vertices": [0, 1]}],
        "crease_edges": [{"vertices": [0, 1], "weight": 0.5}],
        "bevel_weights": [{"vertices": [1, 5], "weight": 0.25}],
        "uv_seams": [{"vertices": [0, 1]}],
        "smoothing_policy": {
            "mode": "weighted_normals",
            "angle_degrees": 30.0,
            "keep_sharp": True,
        },
        "topology_policy": "static_prop_closed",
        "subdivision_intent": {
            "enabled": True,
            "levels": 1,
            "boundary_smoothing": "preserve_corners",
        },
        "lod_intent": {
            "preserve_silhouette": True,
            "protected_face_groups": ["body"],
            "minimum_triangle_ratio": 0.5,
        },
    }


def _legacy_scene_payload(job_id: str) -> dict[str, Any]:
    """Return one valid SceneSpec 0.2 whose non-geometry bytes remain authoritative."""

    return {
        "schema_version": "0.2.0",
        "job_id": job_id,
        "mode": "concept",
        "units": "METERS",
        "coordinate_system": {"handedness": "RIGHT", "up": "+Z", "forward": "-Y"},
        "nominal_scene_size": [4.0, 3.0, 2.5],
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
            {
                "id": "product.hull",
                "name": "Product Hull",
                "geometry": {
                    "kind": "primitive",
                    "primitive": "cube",
                    "dimensions": [2.0, 1.2, 1.2],
                    "segments": 16,
                    "ring_segments": 8,
                },
                "transform": {
                    "location": [0.0, 0.0, 0.0],
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
        ],
        "camera": {
            "projection": "ORTHO",
            "location": [4.0, -7.0, 4.0],
            "target": [0.0, 0.0, 0.5],
            "focal_length_mm": 50.0,
            "ortho_scale": 4.5,
            "resolution": [128, 128],
        },
        "assumptions": ["Hidden surfaces remain inferred."],
        "revision_notes": [],
    }


def _v03_scene_payload(legacy: dict[str, Any], *, with_intent: bool) -> dict[str, Any]:
    """Mirror one legacy scene and opt only its geometry recipe into V03."""

    payload = json.loads(json.dumps(legacy))
    payload["schema_version"] = "0.3.0"
    payload["objects"][0]["geometry"] = _loft_geometry()
    if with_intent:
        payload["objects"][0]["geometry_intent"] = _geometry_intent()
    return payload


def _assignment(output_root: str) -> CandidateAuthoringAssignment:
    """Construct only the immutable output fields consumed by structural compilation."""

    return CandidateAuthoringAssignment.model_construct(
        output_root=output_root,
        scene_spec_v03_output=f"{output_root}/scene_spec_v03.json",
    )


def test_materializer_default_remains_mesh_payload_v01(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep legacy 0.1 output even when a direct caller supplies GeometryIntent."""

    observed_args: list[str] = []

    def fake_run_blender(
        _script_name: str,
        args: list[str],
        *_args: object,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        """Emit the historical receipt and record whether new dispatch flags leaked."""

        observed_args.extend(args)
        values = dict(zip(args[::2], args[1::2], strict=True))
        recipe = StructuralGeometryCandidate.model_validate_json(
            Path(values["--candidate"]).read_text(encoding="utf-8")
        )
        mesh = StructuralMeshPayload(
            semantic_id=recipe.semantic_id,
            builder_kind=recipe.geometry.kind,
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[[0, 1, 2]],
            geometry_intent=recipe.geometry_intent,
        )
        mesh_path = Path(values["--output-mesh"])
        blend_path = Path(values["--output-blend"])
        report_path = Path(values["--report"])
        mesh_path.write_text(mesh.model_dump_json(indent=2) + "\n", encoding="utf-8")
        blend_path.write_bytes(b"legacy-v01-materialization")
        report_path.write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "status": "passed",
                    "semantic_id": recipe.semantic_id,
                    "builder_kind": recipe.geometry.kind,
                    "candidate_sha256": stable_json_digest(
                        recipe.model_dump(mode="json")
                    ),
                    "mesh_sha256": sha256_file(mesh_path),
                    "blend_sha256": sha256_file(blend_path),
                    "vertex_count": 3,
                    "polygon_count": 1,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(
        "codex_blender_modeler.structural_geometry.service.run_blender",
        fake_run_blender,
    )
    candidate = StructuralGeometryCandidate.model_validate_json(
        json.dumps(
            {
                "semantic_id": "product.hull",
                "geometry": _loft_geometry(),
                "geometry_intent": _geometry_intent(),
            }
        )
    )
    payload = materialize_structural_candidate(
        job_root=tmp_path / "legacy_default",
        candidate=candidate,
        candidate_relative_path="structural/candidate.json",
        mesh_relative_path="geometry/materialized.mesh.json",
        blend_relative_path="blender/materialized.blend",
        report_relative_path="reports/materialization.json",
    )

    assert isinstance(payload, StructuralMeshPayload)
    assert payload.schema_version == "0.1.0"
    assert "--mesh-payload-version" not in observed_args
    assert "--material-id" not in observed_args


def test_v03_geometry_intent_explicitly_requests_mesh_payload_v02(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass v2 dispatch only from a V03 structural object with explicit intent."""

    class StopAfterDispatch(RuntimeError):
        """Stop the host-only test immediately after recording materializer arguments."""

    captured: dict[str, object] = {}

    def capture_materializer(**kwargs: object) -> None:
        """Capture exact V03 dispatch options without invoking Blender in this test."""

        captured.update(kwargs)
        raise StopAfterDispatch

    root = tmp_path / "v03_dispatch"
    output_root = "workflows/wf/artifacts/candidates/candidate-01"
    candidate_root = root / output_root
    candidate_root.mkdir(parents=True)
    legacy = SceneSpec.model_validate(_legacy_scene_payload(root.name))
    legacy_path = candidate_root / "scene_spec.json"
    legacy_path.write_text(legacy.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (candidate_root / "scene_spec_v03.json").write_text(
        json.dumps(
            _v03_scene_payload(legacy.model_dump(mode="json"), with_intent=True),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy.candidate_evaluator."
        "materialize_structural_candidate",
        capture_materializer,
    )

    with pytest.raises(StopAfterDispatch):
        _compile_optional_structural_scene(
            root,
            candidate_root,
            _assignment(output_root),
            legacy,
            artifact_for(root, legacy_path),
        )

    assert captured["mesh_payload_version"] == "0.2.0"
    assert captured["material_id"] == "mat.body"


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_GEOMETRY_INTENT_V02_REACHABILITY_SMOKE") != "1",
    reason="set CBM_RUN_GEOMETRY_INTENT_V02_REACHABILITY_SMOKE=1 for Blender smoke",
)
def test_v03_intent_survives_materialization_and_scene_build_in_blender(
    tmp_path: Path,
) -> None:
    """Exercise V03 through v2 materialization and the actual custom-mesh builder."""

    root = tmp_path / "geometry_intent_v02_reachability"
    output_root = "workflows/wf/artifacts/candidates/candidate-01"
    candidate_root = root / output_root
    candidate_root.mkdir(parents=True)
    (root / "input").mkdir(parents=True)
    (root / "input" / "reference.png").write_bytes(b"immutable-v02-reference")
    legacy = SceneSpec.model_validate(_legacy_scene_payload(root.name))
    legacy_path = candidate_root / "scene_spec.json"
    legacy_path.write_text(legacy.model_dump_json(indent=2) + "\n", encoding="utf-8")
    canonical_path = root / "analysis" / "scene_spec.json"
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_text(legacy.model_dump_json(indent=2) + "\n", encoding="utf-8")
    canonical_before = sha256_file(canonical_path)
    (candidate_root / "scene_spec_v03.json").write_text(
        json.dumps(
            _v03_scene_payload(legacy.model_dump(mode="json"), with_intent=True),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    compilation = _compile_optional_structural_scene(
        root,
        candidate_root,
        _assignment(output_root),
        legacy,
        artifact_for(root, legacy_path),
    )
    payload_path = root / compilation.mesh_payload_artifacts[0].path
    payload = load_mesh_payload_v02(payload_path)
    blend, _inventory, validation = _build_candidate(
        root,
        candidate_root,
        compilation.effective_scene_path,
    )
    report_path = candidate_root / "build" / "mesh_payload_v02_snapshot.json"
    run_blender(
        "inspect_custom_mesh_v02.py",
        [
            "--job-root",
            str(root),
            "--payload",
            str(payload_path),
            "--payload-sha256",
            sha256_file(payload_path),
            "--semantic-id",
            payload.semantic_id,
            "--report",
            str(report_path),
        ],
        blend_file=blend,
        disable_autoexec=True,
    )
    report = MeshPayloadV02CompileReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )

    assert payload.schema_version == "0.2.0"
    assert payload.loop_count == len(payload.loop_uvs) > 0
    assert [item.material_id for item in payload.material_slots] == ["mat.body"]
    assert payload.polygon_material_indices == [0] * len(payload.faces)
    assert payload.sharp_edges[0].vertices == (0, 1)
    assert payload.uv_seams[0].vertices == (0, 1)
    assert payload.edge_creases[0].weight == pytest.approx(0.5)
    assert payload.bevel_weights[0].weight == pytest.approx(0.25)
    assert payload.smoothing_policy.mode == "weighted_normals"
    assert payload.weighted_normal_intent.enabled is True
    assert payload.subdivision_intent.enabled is True
    assert any(item.code == "generated_planar_uv_fallback" for item in payload.findings)
    assert json.loads(validation.read_text(encoding="utf-8"))["ok"] is True
    assert report.status == "passed"
    assert report.snapshot.uv_fingerprint.status == "available"
    assert report.snapshot.material_slots_fingerprint.status == "available"
    assert report.snapshot.polygon_material_fingerprint.status == "available"
    assert report.snapshot.sharp_edge_fingerprint.status == "available"
    assert report.snapshot.uv_seam_fingerprint.status == "available"
    assert report.snapshot.crease_fingerprint.status == "available"
    assert report.snapshot.bevel_fingerprint.status == "available"
    assert report.snapshot.smoothing_fingerprint.status == "available"
    assert report.snapshot.modifier_fingerprint.status == "available"
    assert sha256_file(canonical_path) == canonical_before
