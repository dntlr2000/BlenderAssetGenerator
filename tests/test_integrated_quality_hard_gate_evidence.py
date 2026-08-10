"""Focused regression tests for exact Autonomous Quality hard-gate evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from codex_blender_modeler.blender_scripts.assembly import (
    AABB,
    AssemblyCompanionRequest,
    SemanticAssemblyRelation,
    TriangleMeshEvidence,
    build_assembly_companion_report,
)
from codex_blender_modeler.blender_scripts.assembly.models import (
    AssemblyArtifact,
    AssemblyProvenance,
)
from codex_blender_modeler.blender_scripts.topology import (
    TopologyArtifact,
    TopologyObservation,
    TopologyProvenance,
    evaluate_topology_profile,
    get_topology_profile,
)
from codex_blender_modeler.integrated_quality import (
    HardGateEvidencePaths,
    HardGateRequirements,
    ProducerIdentity,
    QualityArtifact,
    QualityProvenance,
    discover_hard_gate_evidence_paths,
    evaluate_hard_gate_evidence,
)
from codex_blender_modeler.optimization.models import Bounds3D, HashedArtifact, SourceProvenance
from codex_blender_modeler.packaging.models import (
    BoundsComparison,
    ExportPackageManifest,
    PackageFile,
    RoundTripCheck,
    RoundTripValidation,
)
from codex_blender_modeler.texturing.models import (
    TextureChannel,
    TextureManifest,
    TextureProvenance,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _sha(path: Path) -> str:
    """Hash one test artifact exactly as the production adapter does."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    """Write one deterministic JSON fixture and create its parent directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _scene_payload() -> dict:
    """Return one minimal valid static-prop SceneSpec fixture."""

    return {
        "schema_version": "0.2.0",
        "job_id": "prop_a",
        "mode": "concept",
        "units": "METERS",
        "nominal_scene_size": [1.0, 1.0, 1.0],
        "sources": [
            {
                "id": "reference.main",
                "path": "input/reference.png",
                "kind": "reference",
            }
        ],
        "materials": [
            {
                "id": "mat.body",
                "name": "Body",
                "base_color": [0.4, 0.5, 0.6, 1.0],
                "roughness": 0.5,
                "metallic": 0.0,
            }
        ],
        "objects": [
            {
                "id": "asset.body",
                "name": "Body",
                "geometry": {
                    "kind": "primitive",
                    "primitive": "cube",
                    "dimensions": [1.0, 1.0, 1.0],
                },
                "material_id": "mat.body",
            }
        ],
        "camera": {
            "projection": "PERSP",
            "location": [3.0, -3.0, 2.0],
            "target": [0.0, 0.0, 0.0],
            "focal_length_mm": 50.0,
            "ortho_scale": 3.0,
            "resolution": [256, 256],
        },
    }


def _modeling_payload(*, spatial: bool = False) -> dict:
    """Return a legacy or required-contact authored ModelingPlan fixture."""

    payload: dict = {
        "schema_version": "0.4.0",
        "job_id": "prop_a",
        "reference_analysis_path": "analysis/reference_analysis.json",
        "camera_solution_path": "analysis/camera_solution.json",
        "stage": "authored",
        "objects": [
            {
                "id": "asset.body",
                "label": "Body",
                "recommended_geometry": "primitive",
                "source_ids": ["reference.main"],
                "assembly_role": "root" if spatial else "unclassified",
            }
        ],
    }
    if not spatial:
        return payload
    payload["objects"].append(
        {
            "id": "asset.handle",
            "label": "Handle",
            "recommended_geometry": "primitive",
            "source_ids": ["reference.main"],
            "assembly_role": "attached",
            "required_assembly_checks": ["position"],
        }
    )
    payload.update(
        {
            "assembly_consistency_policy": "spatial_v1",
            "assembly_frame": {
                "root_object_id": "asset.body",
                "longitudinal_axis": "Y",
                "lateral_axis": "X",
                "vertical_axis": "Z",
            },
            "assembly_relationships": [
                {
                    "id": "relation.handle",
                    "kind": "center_plane",
                    "subject_id": "asset.handle",
                    "reference_id": "asset.body",
                    "axis": "X",
                }
            ],
        }
    )
    return payload


def _inventory_payload() -> dict:
    """Return one deterministic scene inventory with finite transforms."""

    return {
        "job_id": "prop_a",
        "object_count": 1,
        "objects": [
            {
                "name": "Body",
                "cbm_id": "asset.body",
                "location": [0.0, 0.0, 0.0],
                "rotation_deg": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
                "dimensions": [1.0, 1.0, 1.0],
            }
        ],
        "families": [{"cbm_id": "asset.body", "instance_count": 1}],
    }


def _base_paths(root: Path) -> HardGateEvidencePaths:
    """Write exact build, inspect, validate, ModelingPlan, and SceneSpec evidence."""

    blend = root / "blender" / "scene.blend"
    blend.parent.mkdir(parents=True)
    blend.write_bytes(b"BLENDER")
    inventory = root / "reports" / "scene_inventory.json"
    validation = root / "reports" / "validation.json"
    modeling = root / "analysis" / "modeling_plan.json"
    scene = root / "analysis" / "scene_spec.json"
    _write_json(inventory, _inventory_payload())
    _write_json(validation, {"ok": True, "errors": [], "warnings": []})
    _write_json(modeling, _modeling_payload())
    _write_json(scene, _scene_payload())
    return HardGateEvidencePaths(
        blend=blend,
        inventory=inventory,
        validation=validation,
        modeling_plan=modeling,
        scene_spec=scene,
    )


def _provenance(root: Path, paths: tuple[Path, ...]) -> QualityProvenance:
    """Bind every direct fixture path into one strict Integrated Quality provenance."""

    artifacts = [
        QualityArtifact(
            artifact_id=f"artifact-{index}",
            kind="aq-evidence",
            relative_path=path.relative_to(root).as_posix(),
            sha256=_sha(path),
            producer=ProducerIdentity(name="aq-test", version="0.1.0"),
            produced_at=NOW,
        )
        for index, path in enumerate(paths)
    ]
    exact = {item.relative_path: item.sha256 for item in artifacts}
    return QualityProvenance(
        job_id="prop_a",
        workflow_id="workflow-a",
        dispatch_id="dispatch-a",
        source_fingerprint="a" * 64,
        input_sha256=hashlib.sha256(
            json.dumps(exact, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        artifacts=artifacts,
    )


def _gate_map(results: list) -> dict:
    """Index evaluated gates by stable ID for compact assertions."""

    return {item.gate_id: item for item in results}


def test_build_inspect_validate_semantics_and_finite_evidence_pass(tmp_path: Path) -> None:
    """Pass exact structural evidence without requiring later-stage contracts."""

    root = tmp_path / "job"
    paths = _base_paths(root)
    provenance = _provenance(root, discover_hard_gate_evidence_paths(root, paths))
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root,
            provenance=provenance,
            paths=paths,
            requirements=HardGateRequirements(
                require_assembly=False,
                require_topology=False,
                require_material_pbr=False,
                require_package=False,
            ),
        )
    )
    for gate_id in (
        "gate.aq.build",
        "gate.aq.inspect",
        "gate.aq.validate",
        "gate.aq.required_semantics",
        "gate.aq.finite_transforms",
        "gate.aq.required_assembly",
    ):
        assert gates[gate_id].status == "passed"
        assert gates[gate_id].blocking is False


def test_tampered_inventory_and_nonfinite_values_fail_closed(tmp_path: Path) -> None:
    """Distinguish hash tampering from unavailable evidence and reject NaN observations."""

    root = tmp_path / "job"
    paths = _base_paths(root)
    evidence = discover_hard_gate_evidence_paths(root, paths)
    provenance = _provenance(root, evidence)
    assert paths.inventory is not None
    payload = _inventory_payload()
    payload["objects"][0]["location"][0] = float("nan")
    _write_json(paths.inventory, payload)
    gates = _gate_map(
        evaluate_hard_gate_evidence(root, provenance=provenance, paths=paths)
    )
    assert gates["gate.aq.inspect"].status == "failed"
    assert gates["gate.aq.inspect"].blocking is True

    provenance = _provenance(root, discover_hard_gate_evidence_paths(root, paths))
    gates = _gate_map(
        evaluate_hard_gate_evidence(root, provenance=provenance, paths=paths)
    )
    assert gates["gate.aq.finite_transforms"].status == "failed"
    assert gates["gate.aq.finite_transforms"].blocking is True


def _write_material_evidence(root: Path, paths: HardGateEvidencePaths) -> HardGateEvidencePaths:
    """Write one image-backed UVMap PBR contract with exact local provenance."""

    texture_root = root / "textures" / "mat.body"
    texture_root.mkdir(parents=True)
    hashes: dict[str, str] = {}
    channels = {}
    for channel in ("base_color", "roughness", "metallic", "normal"):
        image = texture_root / f"{channel}.png"
        image.write_bytes(f"PNG-{channel}".encode())
        hashes[channel] = _sha(image)
        channels[channel] = TextureChannel(
            source="image",
            path=image.name,
            color_space="sRGB" if channel == "base_color" else "Non-Color",
        )
    manifest = TextureManifest(
        material_id="mat.body",
        uv_set="UVMap",
        intended_scale_m=1.0,
        resolution=(4, 4),
        source_type="image",
        channels=channels,
        provenance=TextureProvenance(
            provider="cbm_autonomy_uniform_pbr",
            provider_version="0.1.0",
            generated_sha256=hashes,
        ),
    )
    manifest_path = texture_root / "texture_manifest.json"
    _write_json(manifest_path, manifest.model_dump(mode="json"))
    material_path = root / "analysis" / "material_plan.json"
    _write_json(
        material_path,
        {
            "schema_version": "0.5.0",
            "job_id": "prop_a",
            "stage": "authored",
            "materials": [
                {
                    "material_id": "mat.body",
                    "label": "Body",
                    "texture_strategy": "image",
                    "mapping": {"mode": "uv", "uv_set": "UVMap"},
                    "texture_manifest": "textures/mat.body/texture_manifest.json",
                }
            ],
        },
    )
    return replace(paths, material_plan=material_path)


def test_uv_pbr_dependencies_and_provenance_are_independent_hard_gates(
    tmp_path: Path,
) -> None:
    """Accept only bound local provenance and fail provider or channel changes."""

    root = tmp_path / "job"
    paths = _write_material_evidence(root, _base_paths(root))
    evidence = discover_hard_gate_evidence_paths(root, paths)
    provenance = _provenance(root, evidence)
    policy = HardGateRequirements(
        require_build=False,
        require_assembly=False,
        require_topology=False,
        require_material_pbr=True,
        require_package=False,
    )
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root, provenance=provenance, paths=paths, requirements=policy
        )
    )
    assert gates["gate.aq.uv_pbr_dependencies"].status == "passed"
    assert gates["gate.aq.provenance"].status == "passed"

    manifest_path = root / "textures" / "mat.body" / "texture_manifest.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_payload["provenance"]["provider"] = "external_unverified_provider"
    _write_json(manifest_path, manifest_payload)
    rebound_provenance = _provenance(
        root, discover_hard_gate_evidence_paths(root, paths)
    )
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root,
            provenance=rebound_provenance,
            paths=paths,
            requirements=policy,
        )
    )
    assert gates["gate.aq.provenance"].status == "failed"
    assert "not allowed" in gates["gate.aq.provenance"].message

    manifest_payload["provenance"]["provider"] = "cbm_autonomy_uniform_pbr"
    _write_json(manifest_path, manifest_payload)
    provenance = _provenance(root, discover_hard_gate_evidence_paths(root, paths))
    (root / "textures" / "mat.body" / "normal.png").write_bytes(b"changed")
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root, provenance=provenance, paths=paths, requirements=policy
        )
    )
    assert gates["gate.aq.provenance"].status == "failed"
    assert gates["gate.aq.provenance"].blocking is True


def _artifact(path: Path, root: Path, artifact_id: str, kind: str) -> HashedArtifact:
    """Create one exact V0.7 nested-artifact receipt."""

    return HashedArtifact(
        id=artifact_id,
        kind=kind,
        path=path.relative_to(root).as_posix(),
        sha256=_sha(path),
    )


def _write_package_evidence(root: Path, paths: HardGateEvidencePaths) -> HardGateEvidencePaths:
    """Write one complete GLB package and exact clean-import report."""

    assert paths.scene_spec is not None and paths.blend is not None
    package_root = root / "exports" / "packages" / "portable_gltf" / "pkg-a"
    metadata = package_root / "metadata"
    metadata.mkdir(parents=True)
    optimization_plan = metadata / "optimization_plan.json"
    optimization_plan.write_text("{}", encoding="utf-8")
    primary = package_root / "asset.glb"
    primary.write_bytes(b"glTF-binary")
    imported = root / "optimization" / "runs" / "run-a" / "roundtrip" / "inventory.json"
    _write_json(imported, {"semantic_ids": ["asset.body"], "material_ids": ["mat.body"]})
    source = SourceProvenance(
        scene_spec=_artifact(paths.scene_spec, root, "scene", "scene_spec"),
        blend=_artifact(paths.blend, root, "blend", "blend"),
        source_fingerprint="b" * 64,
        build_fingerprint="c" * 64,
    )
    package = ExportPackageManifest(
        package_id="pkg-a",
        job_id="prop_a",
        run_id="run-a",
        profile_id="portable_gltf",
        source=source,
        optimization_plan=_artifact(
            optimization_plan, root, "optimization-plan", "optimization_plan"
        ),
        status="complete",
        package_root=package_root.relative_to(root).as_posix(),
        files=[
            PackageFile(
                id="primary-glb",
                kind="primary_asset",
                path=primary.relative_to(root).as_posix(),
                sha256=_sha(primary),
                byte_size=primary.stat().st_size,
                media_type="model/gltf-binary",
            )
        ],
        primary_file_id="primary-glb",
        semantic_ids=["asset.body"],
        material_ids=["mat.body"],
        created_at=NOW,
        completed_at=NOW,
    )
    package_path = package_root / "package_manifest.json"
    _write_json(package_path, package.model_dump(mode="json"))
    check = RoundTripCheck(
        id="dependency",
        category="dependency",
        status="passed",
        message="All package dependencies resolved.",
    )
    bounds = Bounds3D(minimum=(-0.5, -0.5, -0.5), maximum=(0.5, 0.5, 0.5))
    roundtrip = RoundTripValidation(
        validation_id="roundtrip-a",
        job_id="prop_a",
        run_id="run-a",
        package_id="pkg-a",
        profile_id="portable_gltf",
        package_manifest=_artifact(
            package_path, root, "package-manifest", "package_manifest"
        ),
        imported_inventory=_artifact(
            imported, root, "roundtrip-inventory", "roundtrip_inventory"
        ),
        status="passed",
        ok=True,
        passed=1,
        warnings=0,
        failed=0,
        checks=[check],
        bounds=BoundsComparison(
            source=bounds,
            imported=bounds,
            max_abs_error_m=0.0,
            tolerance_m=0.001,
            passed=True,
        ),
        expected_semantic_ids=["asset.body"],
        observed_semantic_ids=["asset.body"],
        semantic_id_coverage=1.0,
        expected_material_ids=["mat.body"],
        observed_material_ids=["mat.body"],
        material_id_coverage=1.0,
        created_at=NOW,
    )
    roundtrip_path = imported.parent / "roundtrip_validation.json"
    _write_json(roundtrip_path, roundtrip.model_dump(mode="json"))
    return replace(
        paths,
        package_manifest=package_path,
        roundtrip_validation=roundtrip_path,
    )


def test_package_dependencies_and_roundtrip_are_hash_bound(tmp_path: Path) -> None:
    """Pass a complete GLB round trip and fail after a package file is modified."""

    root = tmp_path / "job"
    paths = _write_package_evidence(root, _base_paths(root))
    provenance = _provenance(root, discover_hard_gate_evidence_paths(root, paths))
    policy = HardGateRequirements(
        require_build=False,
        require_assembly=False,
        require_topology=False,
        require_material_pbr=False,
        require_package=True,
    )
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root, provenance=provenance, paths=paths, requirements=policy
        )
    )
    assert gates["gate.aq.package_dependencies"].status == "passed"
    assert gates["gate.aq.clean_import_roundtrip"].status == "passed"

    primary = root / "exports" / "packages" / "portable_gltf" / "pkg-a" / "asset.glb"
    primary.write_bytes(b"tampered")
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root, provenance=provenance, paths=paths, requirements=policy
        )
    )
    assert gates["gate.aq.package_dependencies"].status == "failed"
    assert gates["gate.aq.package_dependencies"].blocking is True


def test_required_assembly_without_companion_is_unscorable(tmp_path: Path) -> None:
    """Keep missing mesh-level required-contact evidence unscorable rather than passing."""

    root = tmp_path / "job"
    paths = _base_paths(root)
    assert paths.modeling_plan is not None and paths.scene_spec is not None
    _write_json(paths.modeling_plan, _modeling_payload(spatial=True))
    scene = _scene_payload()
    scene["objects"].append(
        {
            "id": "asset.handle",
            "name": "Handle",
            "geometry": {
                "kind": "primitive",
                "primitive": "cube",
                "dimensions": [0.2, 0.2, 0.2],
            },
            "material_id": "mat.body",
        }
    )
    _write_json(paths.scene_spec, scene)
    inventory = _inventory_payload()
    inventory["object_count"] = 2
    inventory["objects"].append(
        {
            "name": "Handle",
            "cbm_id": "asset.handle",
            "location": [0.0, 0.0, 0.0],
            "rotation_deg": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "dimensions": [0.2, 0.2, 0.2],
        }
    )
    inventory["families"].append({"cbm_id": "asset.handle", "instance_count": 1})
    assert paths.inventory is not None
    _write_json(paths.inventory, inventory)
    provenance = _provenance(root, discover_hard_gate_evidence_paths(root, paths))
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root,
            provenance=provenance,
            paths=paths,
            requirements=HardGateRequirements(
                require_topology=False,
                require_material_pbr=False,
            ),
        )
    )
    assert gates["gate.aq.required_assembly"].status == "unscorable"
    assert gates["gate.aq.required_assembly"].blocking is False


def _spatial_paths(root: Path) -> HardGateEvidencePaths:
    """Upgrade the base fixture to an authored two-part spatial assembly."""

    paths = _base_paths(root)
    assert paths.modeling_plan is not None and paths.scene_spec is not None
    assert paths.inventory is not None
    _write_json(paths.modeling_plan, _modeling_payload(spatial=True))
    scene = _scene_payload()
    scene["objects"].append(
        {
            "id": "asset.handle",
            "name": "Handle",
            "geometry": {
                "kind": "primitive",
                "primitive": "cube",
                "dimensions": [0.2, 0.2, 0.2],
            },
            "material_id": "mat.body",
        }
    )
    _write_json(paths.scene_spec, scene)
    inventory = _inventory_payload()
    inventory["object_count"] = 2
    inventory["objects"].append(
        {
            "name": "Handle",
            "cbm_id": "asset.handle",
            "location": [0.0, 0.0, 0.1],
            "rotation_deg": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "dimensions": [0.2, 0.2, 0.2],
        }
    )
    inventory["families"].append({"cbm_id": "asset.handle", "instance_count": 1})
    _write_json(paths.inventory, inventory)
    return paths


def _mesh_evidence(
    root: Path,
    object_id: str,
    z: float,
) -> TriangleMeshEvidence:
    """Create one exact evaluated triangle snapshot for assembly companion tests."""

    snapshot_path = root / "reports" / "assembly" / f"{object_id}.mesh.json"
    _write_json(snapshot_path, {"object_id": object_id, "z": z})
    return TriangleMeshEvidence(
        object_id=object_id,
        snapshot=AssemblyArtifact(
            role="mesh_snapshot",
            path=snapshot_path.relative_to(root).as_posix(),
            sha256=_sha(snapshot_path),
        ),
        bounds=AABB(
            minimum=(0.0, 0.0, z - 0.000001),
            maximum=(1.0, 1.0, z + 0.000001),
        ),
        vertices_m=[(0.0, 0.0, z), (1.0, 0.0, z), (0.0, 1.0, z)],
        triangles=[(0, 1, 2)],
    )


def test_definitive_required_assembly_failure_blocks(tmp_path: Path) -> None:
    """Block when exact narrow-phase evidence disproves a required semantic contact."""

    root = tmp_path / "job"
    paths = _spatial_paths(root)
    assert paths.scene_spec is not None and paths.modeling_plan is not None
    assert paths.blend is not None
    request = AssemblyCompanionRequest(
        request_id="assembly-a",
        provenance=AssemblyProvenance(
            job_id="prop_a",
            workflow_id="workflow-a",
            dispatch_id="dispatch-a",
            project_version="0.9.0",
            inputs=[
                AssemblyArtifact(
                    role="scene_spec",
                    path=paths.scene_spec.relative_to(root).as_posix(),
                    sha256=_sha(paths.scene_spec),
                ),
                AssemblyArtifact(
                    role="modeling_plan",
                    path=paths.modeling_plan.relative_to(root).as_posix(),
                    sha256=_sha(paths.modeling_plan),
                ),
                AssemblyArtifact(
                    role="blend",
                    path=paths.blend.relative_to(root).as_posix(),
                    sha256=_sha(paths.blend),
                ),
            ],
        ),
        meshes=[
            _mesh_evidence(root, "asset.body", 0.0),
            _mesh_evidence(root, "asset.handle", 0.1),
        ],
        semantic_relations=[
            SemanticAssemblyRelation(
                relation_id="relation.handle",
                kind="required_contact",
                subject_id="asset.handle",
                reference_id="asset.body",
                maximum_m=0.01,
            )
        ],
        maximum_distance_samples=8,
    )
    request_path = root / "reports" / "assembly" / "request.json"
    _write_json(request_path, request.model_dump(mode="json"))
    report = build_assembly_companion_report(
        request,
        request_path=request_path.relative_to(root).as_posix(),
        request_sha256=_sha(request_path),
        report_id="assembly-report-a",
    )
    report_path = root / "reports" / "assembly" / "report.json"
    _write_json(report_path, report.model_dump(mode="json"))
    paths = replace(paths, assembly_companion=report_path)
    provenance = _provenance(root, discover_hard_gate_evidence_paths(root, paths))
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root,
            provenance=provenance,
            paths=paths,
            requirements=HardGateRequirements(
                require_topology=False,
                require_material_pbr=False,
            ),
        )
    )
    assert gates["gate.aq.required_assembly"].status == "failed"
    assert gates["gate.aq.required_assembly"].blocking is True


def test_topology_profile_requires_exact_profile_and_current_evidence(tmp_path: Path) -> None:
    """Accept a complete selected profile and reject a profile-name mismatch."""

    root = tmp_path / "job"
    paths = _base_paths(root)
    assert paths.scene_spec is not None and paths.blend is not None
    topology_inventory = root / "reports" / "topology" / "inventory.json"
    _write_json(topology_inventory, {"checks": "all"})
    evidence = TopologyArtifact(
        role="topology_inventory",
        path=topology_inventory.relative_to(root).as_posix(),
        sha256=_sha(topology_inventory),
    )
    observations = [
        TopologyObservation(
            check=item.check,
            availability="available",
            passed=True,
            measured_value=0,
            evidence=evidence,
            message="fixture passes",
        )
        for item in get_topology_profile("static_prop_closed").checks
    ]
    report = evaluate_topology_profile(
        report_id="topology-a",
        provenance=TopologyProvenance(
            job_id="prop_a",
            workflow_id="workflow-a",
            dispatch_id="dispatch-a",
            project_version="0.9.0",
            inputs=[
                TopologyArtifact(
                    role="scene_spec",
                    path=paths.scene_spec.relative_to(root).as_posix(),
                    sha256=_sha(paths.scene_spec),
                ),
                TopologyArtifact(
                    role="blend",
                    path=paths.blend.relative_to(root).as_posix(),
                    sha256=_sha(paths.blend),
                ),
            ],
        ),
        profile_name="static_prop_closed",
        observations=observations,
    )
    topology_path = root / "reports" / "topology" / "report.json"
    _write_json(topology_path, report.model_dump(mode="json"))
    paths = replace(paths, topology_companion=topology_path)
    provenance = _provenance(root, discover_hard_gate_evidence_paths(root, paths))
    policy = HardGateRequirements(
        require_build=False,
        require_assembly=False,
        require_topology=True,
        require_material_pbr=False,
    )
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root, provenance=provenance, paths=paths, requirements=policy
        )
    )
    assert gates["gate.aq.topology_profile"].status == "passed"

    mismatch = HardGateRequirements(
        require_build=False,
        require_assembly=False,
        require_topology=True,
        require_material_pbr=False,
        topology_profile="static_prop_open",
    )
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root, provenance=provenance, paths=paths, requirements=mismatch
        )
    )
    assert gates["gate.aq.topology_profile"].status == "failed"
    assert gates["gate.aq.topology_profile"].blocking is True


def test_candidate_topology_subset_keeps_later_production_checks_unscorable(
    tmp_path: Path,
) -> None:
    """Pass structural topology while preserving UV/tangent/roundtrip checks as unavailable."""

    root = tmp_path / "job"
    paths = _base_paths(root)
    assert paths.scene_spec is not None and paths.blend is not None
    topology_inventory = root / "reports" / "topology" / "candidate_inventory.json"
    _write_json(topology_inventory, {"checks": "candidate-stage"})
    evidence = TopologyArtifact(
        role="topology_inventory",
        path=topology_inventory.relative_to(root).as_posix(),
        sha256=_sha(topology_inventory),
    )
    later_checks = {
        "uv0",
        "tangent",
        "clean_import_normal_preservation",
        "clean_import_material_preservation",
    }
    observations = [
        TopologyObservation(
            check=item.check,
            availability=("unavailable" if item.check in later_checks else "available"),
            passed=(None if item.check in later_checks else True),
            measured_value=(None if item.check in later_checks else 0),
            evidence=(None if item.check in later_checks else evidence),
            message="candidate-stage fixture",
        )
        for item in get_topology_profile("static_prop_closed").checks
    ]
    report = evaluate_topology_profile(
        report_id="topology-candidate",
        provenance=TopologyProvenance(
            job_id="prop_a",
            workflow_id="workflow-a",
            dispatch_id="dispatch-a",
            project_version="0.9.0",
            inputs=[
                TopologyArtifact(
                    role="scene_spec",
                    path=paths.scene_spec.relative_to(root).as_posix(),
                    sha256=_sha(paths.scene_spec),
                ),
                TopologyArtifact(
                    role="blend",
                    path=paths.blend.relative_to(root).as_posix(),
                    sha256=_sha(paths.blend),
                ),
            ],
        ),
        profile_name="static_prop_closed",
        observations=observations,
    )
    assert report.status == "unscorable"
    topology_path = root / "reports" / "topology" / "candidate_report.json"
    _write_json(topology_path, report.model_dump(mode="json"))
    paths = replace(paths, topology_companion=topology_path)
    provenance = _provenance(root, discover_hard_gate_evidence_paths(root, paths))
    structural_checks = (
        "non_finite",
        "degenerate_face",
        "self_intersection",
        "winding",
        "flipped_normal",
        "loose_geometry",
        "open_boundary",
    )
    subset_policy = HardGateRequirements(
        require_build=False,
        require_assembly=False,
        require_topology=True,
        require_material_pbr=False,
        topology_required_checks=structural_checks,  # type: ignore[arg-type]
    )
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root,
            provenance=provenance,
            paths=paths,
            requirements=subset_policy,
        )
    )
    assert gates["gate.aq.topology_profile"].status == "passed"

    full_policy = replace(subset_policy, topology_required_checks=None)
    gates = _gate_map(
        evaluate_hard_gate_evidence(
            root,
            provenance=provenance,
            paths=paths,
            requirements=full_policy,
        )
    )
    assert gates["gate.aq.topology_profile"].status == "unscorable"
