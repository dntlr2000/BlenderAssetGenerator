"""Focused tests for the additive Codex image MaterialAuthoring-to-V0.5 bridge."""

from __future__ import annotations

from pathlib import Path

import pytest
import test_codex_image_material_authoring_v021 as staging_fixtures

from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.codex_imagegen.artifacts import (
    write_immutable_codex_image_model,
)
from codex_blender_modeler.codex_imagegen.material_loop_models import (
    MaterialLoopRasterSize,
    imagegen_native_normalization_output_path,
    imagegen_native_normalization_plan_path,
)
from codex_blender_modeler.codex_imagegen.material_loop_normalization import (
    execute_native_image_normalization,
    plan_native_image_normalization,
)
from codex_blender_modeler.codex_imagegen.models import CodexImageArtifact
from codex_blender_modeler.material_authoring.codex_image_adapter import (
    author_codex_image_material_candidate,
)
from codex_blender_modeler.material_authoring.codex_image_models import (
    CodexImageMaterialAuthoringReceiptV021,
)
from codex_blender_modeler.material_authoring.codex_image_normalized_adapter import (
    author_codex_image_normalized_material_candidate,
    build_codex_image_normalized_material_request,
)
from codex_blender_modeler.material_authoring.codex_image_v05_bridge import (
    build_codex_image_v05_controller_blueprint,
    publish_codex_image_v05_bridge,
    publish_codex_image_v05_canonical_material_absence,
    validate_codex_image_v05_bridge,
)
from codex_blender_modeler.material_authoring.models import ExactArtifact, UVIdentitySnapshot
from codex_blender_modeler.material_graph.models import MaterialGraphSpec
from codex_blender_modeler.materials.models import (
    MappingSpec,
    MaterialPlan,
    MaterialPlanItem,
)
from codex_blender_modeler.models import (
    CameraSpec,
    MaterialSpec,
    ObjectSpec,
    PrimitiveGeometry,
    SceneSpec,
)
from codex_blender_modeler.texturing.models import TextureManifest

_PLAN_OUTPUT = (
    "production/autonomy_v2/session-test/controller_outputs/material_authoring/"
    "material_plan.json"
)
_GRAPH_OUTPUT = (
    "production/autonomy_v2/session-test/controller_outputs/material_authoring/"
    "material_graph.json"
)
_DISPATCH_ID = "dispatch-1"


def _write_model(path: Path, value: object) -> None:
    """Write one strict fixture model using the repository's normal JSON shape."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _scene(root: Path, target_material_id: str, family: str) -> SceneSpec:
    """Replace the staging helper placeholder with a valid two-material SceneSpec."""

    target_shader = (
        "emissive"
        if family == "emissive"
        else "glass"
        if family == "crystal"
        else "principled"
    )
    scene = SceneSpec(
        job_id="job-1",
        mode="concept",
        nominal_scene_size=(2.0, 1.0, 1.0),
        sources=[],
        materials=[
            MaterialSpec(
                id=target_material_id,
                name="Target",
                shader=target_shader,
                base_color=(0.4, 0.3, 0.2, 1.0),
                roughness=0.45,
                metallic=0.0,
                emission_strength=1.0 if family == "emissive" else 0.0,
            ),
            MaterialSpec(
                id="material-preserved",
                name="Preserved",
                base_color=(0.2, 0.4, 0.6, 1.0),
                roughness=0.7,
                metallic=0.1,
            ),
        ],
        objects=[
            ObjectSpec(
                id="asset.main",
                name="Target",
                geometry=PrimitiveGeometry(
                    primitive="cube", dimensions=(1.0, 0.5, 0.25)
                ),
                material_id=target_material_id,
            ),
            ObjectSpec(
                id="asset.other",
                name="Other",
                geometry=PrimitiveGeometry(
                    primitive="cube", dimensions=(0.25, 0.25, 0.25)
                ),
                material_id="material-preserved",
            ),
        ],
        camera=CameraSpec(
            projection="PERSP",
            location=(3.0, -3.0, 2.0),
            target=(0.0, 0.0, 0.0),
            focal_length_mm=50.0,
            ortho_scale=2.0,
            resolution=(512, 512),
        ),
    )
    _write_model(root / "analysis" / "scene_spec.json", scene)
    return scene


def _baseline(root: Path, scene: SceneSpec, target_material_id: str) -> MaterialPlan:
    """Create one authored V0.5 baseline whose non-target entry must remain identical."""

    plan = MaterialPlan(
        job_id=scene.job_id,
        stage="authored",
        materials=[
            MaterialPlanItem(
                material_id=target_material_id,
                label="Legacy target",
                texture_strategy="none",
                mapping=MappingSpec(mode="object", real_world_scale_m=0.75),
                evidence_status="inferred",
                confidence=0.6,
                notes=["target legacy note"],
            ),
            MaterialPlanItem(
                material_id="material-preserved",
                label="Preserved exact item",
                texture_strategy="none",
                mapping=MappingSpec(mode="object", real_world_scale_m=0.5),
                export_profiles=["blender_eevee", "gltf_pbr"],
                evidence_status="observed",
                confidence=0.9,
                notes=["preserve this exact item"],
            ),
        ],
        global_notes=["legacy global note"],
    )
    _write_model(root / "analysis" / "material_plan.json", plan)
    return plan


def _staged_receipt(
    root: Path,
    family: str = "wood",
    *,
    uv_semantic_id: str = "asset.main",
    canonical_material_absent: bool = False,
):
    """Create a real validated 0.2.1 staging receipt around the strict fake core chain."""

    root.mkdir()
    request = staging_fixtures._strict_core_material_request(root, family=family)
    if uv_semantic_id != request.uv_identity.semantic_id:
        uv_path = root / request.uv_identity.evidence.path
        snapshot = UVIdentitySnapshot.model_validate_json(
            uv_path.read_text(encoding="utf-8")
        ).model_copy(update={"semantic_id": uv_semantic_id})
        _write_model(uv_path, snapshot)
        uv_artifact = staging_fixtures._artifact(
            root,
            uv_path,
            artifact_id="uv-overridden",
            kind="uv-identity-snapshot",
            media_type="application/json",
        )
        request = request.model_copy(
            update={
                "uv_identity": request.uv_identity.model_copy(
                    update={"semantic_id": uv_semantic_id, "evidence": uv_artifact}
                )
            }
        )
    scene = _scene(root, request.material_id, family)
    _baseline(root, scene, request.material_id)
    baseline_path = root / "analysis" / "material_plan.json"
    if canonical_material_absent:
        noncanonical = root / "material_authoring" / "inputs" / "material_plan.json"
        _write_model(
            noncanonical,
            MaterialPlan.model_validate_json(baseline_path.read_text(encoding="utf-8")),
        )
        baseline_path.unlink()
        baseline_path = noncanonical
    baseline_artifact = staging_fixtures._artifact(
        root,
        baseline_path,
        artifact_id="material-plan",
        kind="v05-material-plan",
        media_type="application/json",
    )
    request = request.model_copy(update={"source_v05_contracts": [baseline_artifact]})
    return author_codex_image_material_candidate(root, request), request


def _publish(root: Path, family: str = "wood"):
    """Publish one deterministic bridge fixture with the normal controller output paths."""

    source_receipt, request = _staged_receipt(root, family)
    receipt = publish_codex_image_v05_bridge(
        root,
        source_receipt,
        bridge_run_id=f"bridge-{family.replace('_', '-')}",
        dispatch_id=_DISPATCH_ID,
        material_plan_output_path=_PLAN_OUTPUT,
        material_graph_output_path=_GRAPH_OUTPUT,
    )
    return receipt, source_receipt, request


def _normalized_staged_receipt(root: Path):
    """Publish one normalized companion receipt around an unchanged 0.2.1 request."""

    legacy_receipt, request = _staged_receipt(root)
    base_request_artifact = CodexImageArtifact.model_validate(
        legacy_receipt.request.model_dump(mode="python")
    )
    selected_source = CodexImageArtifact.model_validate(
        request.source.artifact.model_dump(mode="python")
    )
    plan = plan_native_image_normalization(
        root,
        contract_id="v05-normalization-plan",
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        dispatch_id=_DISPATCH_ID,
        session_id="session-1",
        source_image=selected_source,
        output_path=imagegen_native_normalization_output_path(
            "session-1",
            "v05-normalization-plan",
        ),
        target_size=MaterialLoopRasterSize(
            width=request.source.width,
            height=request.source.height,
        ),
        source_color_space="srgb",
        preferred_operation="contain_pad",
        created_at=staging_fixtures.NOW,
    )
    plan_artifact = write_immutable_codex_image_model(
        root,
        root
        / imagegen_native_normalization_plan_path(
            "session-1",
            "v05-normalization-plan",
        ),
        plan,
        kind="imagegen-native-normalization-plan",
    )
    normalization = execute_native_image_normalization(
        root,
        plan,
        plan_artifact,
        receipt_contract_id="v05-normalization-receipt",
        created_at=staging_fixtures.NOW,
    )
    normalization_artifact = write_immutable_codex_image_model(
        root,
        root / "production/autonomy_v2/session-1/v05-normalization-receipt.json",
        normalization,
        kind="imagegen-native-normalization-receipt",
    )
    assert normalization.normalized_image is not None
    effective_source = request.source.model_copy(
        update={
            "artifact": ExactArtifact.model_validate(
                normalization.normalized_image.model_dump(mode="python")
            ),
            "provenance": "deterministic normalized derivative for V0.5 bridge test",
        }
    )
    normalized_request = build_codex_image_normalized_material_request(
        root,
        contract_id="v05-normalized-request",
        run_id="v05-normalized-run",
        base_request=request,
        base_request_artifact=base_request_artifact,
        normalization_plan=plan_artifact,
        normalization_receipt=normalization_artifact,
        effective_source=effective_source,
        created_at=staging_fixtures.NOW,
    )
    return author_codex_image_normalized_material_candidate(root, normalized_request)


def test_bridge_preserves_caller_supplied_direct_source_artifact_identities(
    tmp_path: Path,
) -> None:
    """Keep shared-service aliases exact instead of synthesizing new artifact metadata."""

    root = tmp_path / "job-direct-identities"
    source_receipt, request = _staged_receipt(root)
    authoring_receipt = ExactArtifact.model_validate(
        staging_fixtures._artifact(
            root,
            root / request.output_root / "receipt.json",
            artifact_id="direct-authoring-receipt",
            kind="codex-image-material-authoring-receipt",
            media_type="application/json",
        ).model_dump(mode="python")
    )
    scene_spec = ExactArtifact.model_validate(
        staging_fixtures._artifact(
            root,
            root / "analysis" / "scene_spec.json",
            artifact_id="direct-canonical-scene",
            kind="canonical-scene-spec",
            media_type="application/json",
        ).model_dump(mode="python")
    )
    receipt = publish_codex_image_v05_bridge(
        root,
        source_receipt,
        bridge_run_id="bridge-direct-identities",
        dispatch_id=_DISPATCH_ID,
        material_plan_output_path=_PLAN_OUTPUT,
        material_graph_output_path=_GRAPH_OUTPUT,
        source_authoring_receipt_artifact=authoring_receipt,
        source_scene_spec_artifact=scene_spec,
    )
    assert receipt.source_authoring_receipt == authoring_receipt
    assert receipt.source_scene_spec == scene_spec
    assert any(item.artifact == authoring_receipt for item in receipt.controller_inputs)
    assert any(item.artifact == scene_spec for item in receipt.controller_inputs)
    assert validate_codex_image_v05_bridge(root, receipt) == receipt


def test_normalized_companion_bridge_replays_after_canonical_promotion(
    tmp_path: Path,
) -> None:
    """Accept normalized staging and replay it through the run-owned baseline snapshot."""

    root = tmp_path / "job-normalized-bridge"
    source_receipt = _normalized_staged_receipt(root)
    receipt = publish_codex_image_v05_bridge(
        root,
        source_receipt,
        bridge_run_id="bridge-normalized",
        dispatch_id=_DISPATCH_ID,
        material_plan_output_path=_PLAN_OUTPUT,
        material_graph_output_path=_GRAPH_OUTPUT,
    )
    (root / receipt.source_material_plan.path).write_bytes(
        (root / receipt.candidate_material_plan.path).read_bytes()
    )
    assert validate_codex_image_v05_bridge(root, receipt) == receipt


@pytest.mark.parametrize("family", ["wood", "signage_decal", "emissive", "crystal"])
def test_four_material_families_produce_strict_unverified_v05_blueprints(
    tmp_path: Path,
    family: str,
) -> None:
    """Cover the four required families without claiming controller or Blender execution."""

    root = tmp_path / f"job-{family}"
    receipt, _source, request = _publish(root, family)
    assert validate_codex_image_v05_bridge(root, receipt) == receipt
    assert receipt.status == "controller_candidate_ready"
    assert receipt.blender_compilation_status == "not_run"
    assert receipt.neutral_preview_status == "not_run"
    assert receipt.reference_preview_status == "not_run"
    assert receipt.controller_result_created is False
    assert receipt.canonical_write_performed is False
    assert receipt.session_id == "session-1"
    assert receipt.profile_id == "autonomous_static_prop_v2_codex_imagegen"
    assert receipt.provider_id == "codex_builtin_gpt_image_v1"
    assert receipt.source_fingerprint == receipt.source_authoring_receipt.sha256
    assert (
        receipt.previous_canonical_material_plan
        == receipt.baseline_material_plan_snapshot
    )
    assert receipt.source_material_plan.path == "analysis/material_plan.json"
    assert receipt.baseline_material_plan_snapshot.path != receipt.source_material_plan.path
    assert receipt.canonical_material_absence_evidence is None
    assert {item.path for item in receipt.provenance} == {
        receipt.source_authoring_receipt.path,
        *[item.artifact.path for item in receipt.controller_inputs],
    }

    plan = MaterialPlan.model_validate_json(
        (root / receipt.candidate_material_plan.path).read_text(encoding="utf-8")
    )
    baseline = MaterialPlan.model_validate_json(
        (root / "analysis" / "material_plan.json").read_text(encoding="utf-8")
    )
    assert plan.stage == "authored"
    assert {item.material_id for item in plan.materials} == {
        request.material_id,
        "material-preserved",
    }
    assert next(
        item for item in plan.materials if item.material_id == "material-preserved"
    ) == next(
        item for item in baseline.materials if item.material_id == "material-preserved"
    )
    target = next(item for item in plan.materials if item.material_id == request.material_id)
    assert target.mapping.mode == "uv"
    assert target.mapping.uv_set == "UVMap"
    assert target.texture_manifest == receipt.texture_manifest.path
    assert target.shader_recipe == receipt.shader_recipe.path

    graph = receipt.candidate_material_graph
    graph_model = MaterialGraphSpec.model_validate_json(
        (root / graph.path).read_text(encoding="utf-8")
    )
    plan_inputs = [
        item for item in graph_model.provenance.inputs if item.role == "material_plan"
    ]
    assert [(item.path, item.sha256) for item in plan_inputs] == [
        (_PLAN_OUTPUT, receipt.candidate_material_plan.sha256)
    ]
    assert graph_model.material_id == request.material_id
    assert any(item.role == "scene_spec" for item in graph_model.provenance.inputs)
    assert all(
        item.channel in {"base_color", "emission", "opacity"}
        for item in receipt.channels
        if item.provenance_kind == "codex_generated_direct"
    )
    texture = TextureManifest.model_validate_json(
        (root / receipt.texture_manifest.path).read_text(encoding="utf-8")
    )
    assert set(texture.provenance.generated_sha256) == set(texture.channels)
    assert "occlusion" not in texture.provenance.generated_sha256
    assert {item.role for item in receipt.controller_inputs} <= {
        "scene",
        "scale-context",
        "material-baseline",
    }
    immutable_paths = {item.artifact.path for item in receipt.controller_inputs}
    assert receipt.source_material_plan.path not in immutable_paths
    assert receipt.baseline_material_plan_snapshot.path in immutable_paths


def test_bridge_replays_after_exact_candidate_replaces_canonical_baseline(
    tmp_path: Path,
) -> None:
    """Keep long-lived dependencies valid after host promotion replaces canonical bytes."""

    root = tmp_path / "job-promoted-replay"
    receipt, _source, _request = _publish(root)
    assert receipt.source_material_plan.sha256 != receipt.candidate_material_plan.sha256
    canonical = root / receipt.source_material_plan.path
    candidate = root / receipt.candidate_material_plan.path
    canonical.write_bytes(candidate.read_bytes())

    assert validate_codex_image_v05_bridge(root, receipt) == receipt
    graph = MaterialGraphSpec.model_validate_json(
        (root / receipt.candidate_material_graph.path).read_text(encoding="utf-8")
    )
    graph_paths = {item.path for item in graph.provenance.inputs}
    assert receipt.source_material_plan.path not in graph_paths
    assert receipt.baseline_material_plan_snapshot.path in graph_paths


def test_bridge_rejects_non_candidate_canonical_replacement(tmp_path: Path) -> None:
    """Preserve pre-promotion CAS by rejecting an arbitrary canonical replacement."""

    root = tmp_path / "job-invalid-canonical"
    receipt, _source, _request = _publish(root)
    canonical = root / receipt.source_material_plan.path
    canonical.write_bytes(canonical.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="both baseline and promotion"):
        validate_codex_image_v05_bridge(root, receipt)


def test_blueprint_is_deterministic_and_accepts_only_its_exact_plan_hash(
    tmp_path: Path,
) -> None:
    """Require stable bytes and reject a caller-supplied hash from another plan."""

    first_root = tmp_path / "first"
    first_source, _request = _staged_receipt(first_root)
    kwargs = {
        "bridge_run_id": "bridge-deterministic",
        "dispatch_id": _DISPATCH_ID,
        "material_plan_output_path": _PLAN_OUTPUT,
        "material_graph_output_path": _GRAPH_OUTPUT,
    }
    first = build_codex_image_v05_controller_blueprint(first_root, first_source, **kwargs)
    second = build_codex_image_v05_controller_blueprint(first_root, first_source, **kwargs)
    assert first.material_plan_artifact.sha256 == second.material_plan_artifact.sha256
    assert first.material_graph_artifact.sha256 == second.material_graph_artifact.sha256
    assert first.texture_manifest_artifact.sha256 == second.texture_manifest_artifact.sha256
    assert first.shader_recipe_artifact.sha256 == second.shader_recipe_artifact.sha256
    with pytest.raises(ValueError, match="caller-supplied controller MaterialPlan hash"):
        build_codex_image_v05_controller_blueprint(
            first_root,
            first_source,
            **kwargs,
            material_plan_output_sha256="f" * 64,
        )


def test_bridge_rejects_output_escape_and_canonical_controller_target(tmp_path: Path) -> None:
    """Keep controller output blueprints contained and away from canonical paths."""

    root = tmp_path / "job"
    source, _request = _staged_receipt(root)
    with pytest.raises(ValueError, match="path must not contain"):
        build_codex_image_v05_controller_blueprint(
            root,
            source,
            bridge_run_id="bridge-path",
            dispatch_id=_DISPATCH_ID,
            material_plan_output_path="../material_plan.json",
            material_graph_output_path=_GRAPH_OUTPUT,
        )
    with pytest.raises(ValueError, match="cannot target the canonical"):
        build_codex_image_v05_controller_blueprint(
            root,
            source,
            bridge_run_id="bridge-canonical",
            dispatch_id=_DISPATCH_ID,
            material_plan_output_path="analysis/material_plan.json",
            material_graph_output_path="analysis/material_graph.json",
        )


def test_bridge_tamper_detection_preserves_source_and_canonical_bytes(tmp_path: Path) -> None:
    """Detect adapted-channel tampering while leaving staging and canonical files untouched."""

    root = tmp_path / "job"
    receipt, source_receipt, _request = _publish(root)
    source_receipt_path = root / receipt.source_authoring_receipt.path
    scene_path = root / "analysis" / "scene_spec.json"
    plan_path = root / "analysis" / "material_plan.json"
    before = {
        source_receipt_path: sha256_file(source_receipt_path),
        scene_path: sha256_file(scene_path),
        plan_path: sha256_file(plan_path),
    }
    adapted = root / receipt.channels[0].adapted.path
    adapted.write_bytes(adapted.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="byte size changed"):
        validate_codex_image_v05_bridge(root, receipt)
    assert source_receipt == CodexImageMaterialAuthoringReceiptV021.model_validate_json(
        source_receipt_path.read_text(encoding="utf-8")
    )
    assert {path: sha256_file(path) for path in before} == before


def test_bridge_rejects_tampered_source_staging_channel(tmp_path: Path) -> None:
    """Reuse 0.2.1 replay validation so source-channel mutation fails before adaptation."""

    root = tmp_path / "job"
    source, _request = _staged_receipt(root)
    source_channel = root / source.outputs[0].path
    source_channel.write_bytes(source_channel.read_bytes() + b"source-tamper")
    with pytest.raises(ValueError, match="byte size changed"):
        build_codex_image_v05_controller_blueprint(
            root,
            source,
            bridge_run_id="bridge-source-tamper",
            dispatch_id=_DISPATCH_ID,
            material_plan_output_path=_PLAN_OUTPUT,
            material_graph_output_path=_GRAPH_OUTPUT,
        )


def test_bridge_rejects_target_material_removed_from_current_scene(tmp_path: Path) -> None:
    """Reject stale staging whose stable material ID no longer exists in current SceneSpec."""

    root = tmp_path / "job"
    source, request = _staged_receipt(root)
    scene_path = root / "analysis" / "scene_spec.json"
    scene = SceneSpec.model_validate_json(scene_path.read_text(encoding="utf-8"))
    replacement = scene.model_copy(
        update={
            "materials": [
                item for item in scene.materials if item.id != request.material_id
            ],
            "objects": [
                item for item in scene.objects if item.material_id != request.material_id
            ],
        }
    )
    _write_model(scene_path, replacement)
    with pytest.raises(ValueError, match="target must exist and be used"):
        build_codex_image_v05_controller_blueprint(
            root,
            source,
            bridge_run_id="bridge-missing-id",
            dispatch_id=_DISPATCH_ID,
            material_plan_output_path=_PLAN_OUTPUT,
            material_graph_output_path=_GRAPH_OUTPUT,
        )


def test_bridge_rejects_uv_identity_not_owned_by_target_object(tmp_path: Path) -> None:
    """Fail closed when exact UV evidence names a non-target semantic object."""

    root = tmp_path / "job"
    source, _request = _staged_receipt(root, uv_semantic_id="asset.other")
    with pytest.raises(ValueError, match="UV identity semantic_id"):
        build_codex_image_v05_controller_blueprint(
            root,
            source,
            bridge_run_id="bridge-bad-uv",
            dispatch_id=_DISPATCH_ID,
            material_plan_output_path=_PLAN_OUTPUT,
            material_graph_output_path=_GRAPH_OUTPUT,
        )


def test_bridge_refuses_overwriting_a_published_run(tmp_path: Path) -> None:
    """Keep bridge histories immutable and reject reuse of one run identifier."""

    root = tmp_path / "job"
    receipt, source, _request = _publish(root)
    assert receipt.status == "controller_candidate_ready"
    with pytest.raises(FileExistsError, match="already exists"):
        publish_codex_image_v05_bridge(
            root,
            source,
            bridge_run_id="bridge-wood",
            dispatch_id=_DISPATCH_ID,
            material_plan_output_path=_PLAN_OUTPUT,
            material_graph_output_path=_GRAPH_OUTPUT,
        )


def test_bridge_supports_exact_canonical_material_absence(tmp_path: Path) -> None:
    """Keep an authoring scaffold distinct from exact canonical MaterialPlan absence."""

    root = tmp_path / "job"
    source, request = _staged_receipt(root, canonical_material_absent=True)
    scene_artifact = staging_fixtures._artifact(
        root,
        root / "analysis" / "scene_spec.json",
        artifact_id="canonical-scene",
        kind="scene-spec",
        media_type="application/json",
    )
    absence = publish_codex_image_v05_canonical_material_absence(
        root,
        absence_id="material-absent",
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        dispatch_id=_DISPATCH_ID,
        session_id="session-1",
        source_scene_spec=scene_artifact,
    )
    receipt = publish_codex_image_v05_bridge(
        root,
        source,
        bridge_run_id="bridge-absence",
        dispatch_id=_DISPATCH_ID,
        material_plan_output_path=_PLAN_OUTPUT,
        material_graph_output_path=_GRAPH_OUTPUT,
        canonical_material_absence_evidence=absence,
    )

    assert receipt.previous_canonical_material_plan is None
    assert receipt.canonical_material_absence_evidence == absence
    assert receipt.source_material_plan.path == (
        "material_authoring/inputs/material_plan.json"
    )
    assert not (root / "analysis" / "material_plan.json").exists()
    assert absence.path in {item.artifact.path for item in receipt.controller_inputs}
    assert validate_codex_image_v05_bridge(root, receipt) == receipt


def test_bridge_common_evidence_fields_fail_closed(tmp_path: Path) -> None:
    """Reject changed session, source, input digest, or incomplete exact provenance."""

    root = tmp_path / "job"
    receipt, _source, _request = _publish(root)
    payload = receipt.model_dump(mode="python")
    for field, replacement, message in (
        ("session_id", "session-other", "input_sha256"),
        ("source_fingerprint", "f" * 64, "source fingerprint"),
        ("input_sha256", "f" * 64, "input_sha256"),
        ("provenance", payload["provenance"][:-1], "provenance"),
    ):
        changed = {**payload, field: replacement}
        with pytest.raises(ValueError, match=message):
            type(receipt).model_validate(changed)
