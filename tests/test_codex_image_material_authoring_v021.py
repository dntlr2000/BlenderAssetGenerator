"""Focused strict-model and deterministic host tests for MaterialAuthoring 0.2.1."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.codex_imagegen.adoption import (
    build_image_to_material_adoption,
)
from codex_blender_modeler.codex_imagegen.artifacts import (
    artifact_for_codex_image,
    write_immutable_codex_image_model,
)
from codex_blender_modeler.codex_imagegen.models import (
    CodexGeneratedFile,
    CodexGeneratedImageEvidence,
    CodexImageArtifact,
    CodexImageCandidateDecision,
    CodexImageGenerationCandidate,
    CodexImageGenerationCompletion,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
    CodexImageQualityCheck,
)
from codex_blender_modeler.material_authoring import codex_image_adapter
from codex_blender_modeler.material_authoring.codex_image_adapter import (
    author_codex_image_material_candidate,
    validate_codex_image_material_candidate,
)
from codex_blender_modeler.material_authoring.codex_image_models import (
    CodexImageAuthoredMaterialManifestV021,
    CodexImageChannelDerivationV021,
    CodexImageEvidenceBindingsV021,
    CodexImageMaterialAuthoringRequestV021,
    CodexImageMaterialSourceV021,
    ExactSignageTextEvidenceV021,
    ExactTextCompositionV021,
    LocalImageDerivationPolicyV021,
)
from codex_blender_modeler.material_authoring.models import (
    ExactArtifact,
    ProjectLocalFont,
    ScaleContextBinding,
    UVIdentity,
    UVIdentitySnapshot,
    UVRect,
)
from codex_blender_modeler.structural_geometry.models import (
    AssetScaleContext,
    StructuralEvidenceArtifact,
)
from codex_blender_modeler.workspace import sha256_file

NOW = datetime(2026, 8, 11, 13, 0, tzinfo=UTC)


def _write_json(path: Path, payload: Any) -> None:
    """Write one deterministic fixture JSON file inside an isolated test job."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    media_type: str,
) -> ExactArtifact:
    """Bind one fixture file to exact MaterialAuthoring artifact metadata."""

    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=path.relative_to(root).as_posix(),
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
        media_type=media_type,
    )


def _scale_context(
    root: Path,
    *,
    job_id: str = "image_material_fixture",
    workflow_id: str = "wf-test",
) -> ScaleContextBinding:
    """Create one exact AssetScaleContext and its cached companion binding."""

    scene_path = root / "analysis" / "scene_spec.json"
    _write_json(scene_path, {"schema_version": "0.2.0", "fixture": True})
    provenance = [
        StructuralEvidenceArtifact(
            role="scene_spec",
            path="analysis/scene_spec.json",
            sha256=sha256_file(scene_path),
        )
    ]
    context = AssetScaleContext.from_bounds(
        asset_id="asset.main",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id="dispatch-test",
        source_fingerprint="1" * 64,
        producer="pytest",
        producer_version="0.1.0",
        provenance=provenance,
        created_at=NOW,
        local_minimum=(0.0, 0.0, 0.0),
        local_maximum=(1.0, 0.5, 0.25),
        assembly_minimum=(0.0, 0.0, 0.0),
        assembly_maximum=(1.0, 0.5, 0.25),
        projected_pixel_size=128.0,
        target_texel_density_px_m=256.0,
    )
    path = root / "production" / "scale_context.json"
    _write_json(path, context.model_dump(mode="json"))
    return ScaleContextBinding(
        artifact=_artifact(
            root,
            path,
            artifact_id="scale-context",
            kind="asset-scale-context",
            media_type="application/json",
        ),
        asset_id=context.asset_id,
        source_fingerprint=context.source_fingerprint,
        shortest_dimension_m=context.shortest_dimension_m,
        longest_dimension_m=max(context.assembly_bbox.dimensions()),
        target_texel_density_px_m=context.target_texel_density_px_m,
    )


def _uv_identity(root: Path) -> UVIdentity:
    """Create one exact non-stale UV identity for generated channel ownership."""

    snapshot = UVIdentitySnapshot(
        semantic_id="asset.main",
        uv_set="UVMap",
        uv_fingerprint="2" * 64,
        ordered_polygon_corner_count=24,
        texel_density_px_m=256.0,
    )
    path = root / "analysis" / "uv_identity.json"
    _write_json(path, snapshot.model_dump(mode="json"))
    return UVIdentity(
        **snapshot.model_dump(mode="python"),
        evidence=_artifact(
            root,
            path,
            artifact_id="uv-identity",
            kind="uv-identity-snapshot",
            media_type="application/json",
        ),
    )


def _core_bindings(root: Path) -> CodexImageEvidenceBindingsV021:
    """Create exact placeholder links whose strict core parsing is isolated in host tests."""

    definitions = (
        ("selection", "codex-image-generation-selection"),
        ("selected-evidence", "codex-generated-image-evidence"),
        ("selected-quality", "codex-image-generation-quality-report"),
        ("adoption", "codex-image-material-adoption"),
    )
    artifacts: dict[str, ExactArtifact] = {}
    for name, kind in definitions:
        path = root / "production" / "codex_imagegen" / f"{name}.json"
        _write_json(path, {"fixture": name})
        artifacts[name] = _artifact(
            root,
            path,
            artifact_id=name,
            kind=kind,
            media_type="application/json",
        )
    return CodexImageEvidenceBindingsV021(
        selection=artifacts["selection"],
        selected_evidence=artifacts["selected-evidence"],
        selected_quality_report=artifacts["selected-quality"],
        adoption=artifacts["adoption"],
    )


def _as_material_artifact(artifact: Any) -> ExactArtifact:
    """Convert identical core artifact fields into the MaterialAuthoring exact type."""

    return ExactArtifact.model_validate(artifact.model_dump(mode="python"))


def _strict_fake_core_chain(
    root: Path,
    *,
    material_id: str = "material-wood",
    semantic_role: str = "wood-grain",
    generation_intent: str = "generated_image_procedural_hybrid_v1",
    material_strategy: str = "codex_generated_procedural_hybrid_v1",
    direct_role: str = "base_color",
    exact_text_composition: CodexImageArtifact | None = None,
) -> tuple[CodexImageEvidenceBindingsV021, CodexImageMaterialSourceV021]:
    """Publish a strict selected fake-raster chain for one bounded material family."""

    source_path = root / "production" / "autonomy_v2" / "fake" / "candidate-00.png"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (64, 64), (80, 40, 20, 255))
    draw = ImageDraw.Draw(image)
    for y in range(64):
        shade = 30 + (y % 8) * 20
        draw.line((0, y, 63, y), fill=(shade + 60, shade, 20, 255))
    image.save(source_path, format="PNG", compress_level=9, optimize=False)
    generated_artifact = artifact_for_codex_image(
        root,
        source_path,
        artifact_id="fake-candidate-00",
        kind="codex-generated-raster",
        media_type="image/png",
    )
    placeholders = {}
    for name in ("assignment", "controller-request", "controller-result"):
        path = root / "production" / "autonomy_v2" / "fake" / f"{name}.json"
        _write_json(path, {"strict_fake_fixture": name})
        placeholders[name] = artifact_for_codex_image(
            root,
            path,
            artifact_id=name,
            kind=f"codex-image-generation-{name}",
            media_type="application/json",
        )
    generated_file = CodexGeneratedFile(
        candidate_id="fake-candidate-00",
        ordinal=0,
        output_role=direct_role,
        artifact=generated_artifact,
        width=64,
        height=64,
        alpha_present=True,
    )
    completion = CodexImageGenerationCompletion(
        contract_id="fake-completion-contract",
        job_id="job-1",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        input_sha256="b" * 64,
        source_fingerprint="c" * 64,
        producer="pytest.fake.completion",
        provenance=[placeholders["assignment"], generated_artifact],
        created_at=NOW,
        completion_id="fake-completion",
        assignment=placeholders["assignment"],
        assignment_payload_sha256="d" * 64,
        controller_kind="fake_for_tests",
        execution_scope="deterministic_fake",
        source_kind="deterministic_fake",
        source_inventory_sha256="e" * 64,
        generated_files=[generated_file],
        generation_count=1,
        prompt_echo_sha256="f" * 64,
        controller_executed_at=NOW,
        status="completed",
    )
    placeholders["completion"] = write_immutable_codex_image_model(
        root,
        root / "production" / "autonomy_v2" / "fake" / "completion.json",
        completion,
        kind="codex-image-generation-completion",
    )
    candidate = CodexImageGenerationCandidate(
        contract_id="fake-candidate-contract",
        job_id="job-1",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        input_sha256="3" * 64,
        source_fingerprint="4" * 64,
        producer="pytest.fake.downstream",
        provenance=[*placeholders.values(), generated_artifact],
        created_at=NOW,
        candidate_id="fake-candidate-00",
        assignment=placeholders["assignment"],
        completion=placeholders["completion"],
        controller_request=placeholders["controller-request"],
        controller_result=placeholders["controller-result"],
        generated_file=generated_file,
        target_material_ids=[material_id],
        semantic_roles=[semantic_role],
        generation_intent=generation_intent,
    )
    candidate_artifact = write_immutable_codex_image_model(
        root,
        root / "production" / "autonomy_v2" / "fake" / "candidate.json",
        candidate,
        kind="codex-image-generation-candidate",
    )
    evidence = CodexGeneratedImageEvidence(
        contract_id="fake-evidence-contract",
        job_id="job-1",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        input_sha256="5" * 64,
        source_fingerprint="6" * 64,
        producer="pytest.fake.downstream",
        provenance=[*candidate.provenance, candidate_artifact],
        created_at=NOW,
        evidence_id="fake-generated-evidence",
        assignment=placeholders["assignment"],
        completion=placeholders["completion"],
        controller_request=placeholders["controller-request"],
        controller_result=placeholders["controller-result"],
        candidate=candidate_artifact,
        candidate_id="fake-candidate-00",
        generated_file=generated_file,
        target_material_ids=[material_id],
        semantic_roles=[semantic_role],
        generation_intent=generation_intent,
    )
    evidence_artifact = write_immutable_codex_image_model(
        root,
        root / "production" / "autonomy_v2" / "fake" / "evidence.json",
        evidence,
        kind="codex-generated-image-evidence",
    )
    report = CodexImageGenerationQualityReport(
        contract_id="fake-quality-contract",
        job_id="job-1",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        input_sha256="7" * 64,
        source_fingerprint="8" * 64,
        producer="pytest.fake.downstream",
        provenance=[
            placeholders["assignment"],
            placeholders["completion"],
            candidate_artifact,
            evidence_artifact,
        ],
        created_at=NOW,
        report_id="fake-quality-report",
        assignment=placeholders["assignment"],
        completion=placeholders["completion"],
        candidate=candidate_artifact,
        generated_image_evidence=evidence_artifact,
        checks=[
            CodexImageQualityCheck(
                check_id="decode",
                status="passed",
                score=1.0,
                threshold=1.0,
                hard_gate=True,
                algorithm_id="fixture-decode-v1",
                message="strict fake PNG decoded",
            )
        ],
        deterministic_score=1.0,
        outcome="passed",
        selection_eligible=True,
    )
    report_artifact = write_immutable_codex_image_model(
        root,
        root / "production" / "autonomy_v2" / "fake" / "quality.json",
        report,
        kind="codex-image-generation-quality-report",
    )
    selection = CodexImageGenerationSelection(
        contract_id="fake-selection-contract",
        job_id="job-1",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session-1",
        input_sha256="9" * 64,
        source_fingerprint="a" * 64,
        producer="pytest.fake.downstream",
        provenance=[
            placeholders["assignment"],
            placeholders["completion"],
            candidate_artifact,
            report_artifact,
        ],
        created_at=NOW,
        selection_id="fake-selection",
        assignment=placeholders["assignment"],
        completion=placeholders["completion"],
        candidate_count=1,
        selected_candidate=candidate_artifact,
        selected_quality_report=report_artifact,
        decisions=[
            CodexImageCandidateDecision(
                candidate_id="fake-candidate-00",
                candidate=candidate_artifact,
                quality_report=report_artifact,
                outcome="selected",
                reason_codes=["highest-score"],
            )
        ],
        outcome="selected",
    )
    selection_artifact = write_immutable_codex_image_model(
        root,
        root / "production" / "autonomy_v2" / "fake" / "selection.json",
        selection,
        kind="codex-image-generation-selection",
    )
    adoption = build_image_to_material_adoption(
        contract_id="fake-adoption-contract",
        adoption_id="fake-adoption",
        selection=selection,
        selection_artifact=selection_artifact,
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        generated_image_evidence=evidence,
        generated_image_evidence_artifact=evidence_artifact,
        quality_report=report,
        quality_report_artifact=report_artifact,
        material_strategy=material_strategy,
        direct_channels=[direct_role],
        derived_channels=[],
        created_at=NOW,
        exact_text_composition=exact_text_composition,
    )
    adoption_artifact = write_immutable_codex_image_model(
        root,
        root / "production" / "autonomy_v2" / "fake" / "adoption.json",
        adoption,
        kind="codex-image-material-adoption",
    )
    bindings = CodexImageEvidenceBindingsV021(
        selection=_as_material_artifact(selection_artifact),
        selected_evidence=_as_material_artifact(evidence_artifact),
        selected_quality_report=_as_material_artifact(report_artifact),
        adoption=_as_material_artifact(adoption_artifact),
    )
    source = CodexImageMaterialSourceV021(
        artifact=_as_material_artifact(generated_artifact),
        width=64,
        height=64,
        direct_role=direct_role,
        color_space="non_color" if direct_role == "opacity_source" else "srgb",
        license_id="project-generated-codex-usage",
        rights_status="project_owned",
        provenance="strict deterministic fake; not actual Codex ImageGen execution",
    )
    return bindings, source


def _strict_core_material_request(
    root: Path,
    *,
    family: str = "wood",
) -> CodexImageMaterialAuthoringRequestV021:
    """Build one supported family request around a strict deterministic fake chain."""

    family_contracts = {
        "wood": (
            "codex_generated_procedural_hybrid_v1",
            "base_color",
            "wood-grain",
            "generated_image_procedural_hybrid_v1",
        ),
        "signage_decal": (
            "codex_generated_decal_v1",
            "decal_rgb",
            "signage-background",
            "generated_decal_art_v1",
        ),
        "emissive": (
            "codex_generated_emission_v1",
            "emission",
            "emission-pattern",
            "generated_emission_pattern_v1",
        ),
        "crystal": (
            "codex_generated_procedural_hybrid_v1",
            "base_color",
            "crystal-pattern",
            "generated_image_procedural_hybrid_v1",
        ),
    }
    strategy, direct_role, semantic_role, generation_intent = family_contracts[family]
    material_id = f"material-{family.replace('_', '-')}"
    exact_text = None
    exact_text_core_artifact = None
    if family == "signage_decal":
        exact_text_artifact = _exact_text_evidence(root, "AB")
        exact_text_core_artifact = CodexImageArtifact.model_validate(
            exact_text_artifact.model_dump(mode="python")
        )
        exact_text = ExactTextCompositionV021(
            evidence="exact_user_text",
            text="AB",
            text_evidence_artifact=exact_text_artifact,
            font=_bitmap_font(root),
            uv_rect=UVRect(minimum=(0.2, 0.2), maximum=(0.8, 0.8)),
            color=(1.0, 1.0, 1.0, 1.0),
        )
    bindings, source = _strict_fake_core_chain(
        root,
        material_id=material_id,
        semantic_role=semantic_role,
        generation_intent=generation_intent,
        material_strategy=strategy,
        direct_role=direct_role,
        exact_text_composition=exact_text_core_artifact,
    )
    run_id = "core-chain" if family == "wood" else f"core-chain-{family}"
    return CodexImageMaterialAuthoringRequestV021(
        request_id=f"request-{run_id}",
        job_id="job-1",
        workflow_id="workflow-1",
        run_id=run_id,
        material_id=material_id,
        strategy=strategy,
        material_family=family,
        output_root=f"material_authoring/codex_imagegen/runs/{run_id}",
        core_evidence=bindings,
        source=source,
        source_v05_contracts=[_v05_plan(root)],
        uv_identity=_uv_identity(root),
        scale_context=_scale_context(
            root,
            job_id="job-1",
            workflow_id="workflow-1",
        ),
        derivation=LocalImageDerivationPolicyV021(
            output_resolution=256,
            minimum_spatial_standard_deviation=0.0,
            maximum_offset_edge_rmse=1.0,
        ),
        exact_text=exact_text,
        created_at=NOW,
    )


def _source(root: Path, *, role: str = "base_color") -> CodexImageMaterialSourceV021:
    """Create one deterministic generated-image fixture with directional local detail."""

    path = root / "production" / "codex_imagegen" / "staging" / "candidate-00.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (64, 64), (80, 50, 20, 255))
    draw = ImageDraw.Draw(image)
    for y in range(64):
        shade = 45 + (y % 8) * 18
        draw.line((0, y, 63, y), fill=(shade + 50, shade, 20, 255))
    image.save(path, format="PNG", compress_level=9, optimize=False)
    return CodexImageMaterialSourceV021(
        artifact=_artifact(
            root,
            path,
            artifact_id="candidate-00",
            kind="codex-generated-raster",
            media_type="image/png",
        ),
        width=64,
        height=64,
        direct_role=role,
        color_space="non_color" if role == "opacity_source" else "srgb",
        license_id="project-generated-codex-usage",
        rights_status="project_owned",
        provenance="deterministic fake completion; not actual Codex ImageGen execution",
    )


def _v05_plan(root: Path) -> ExactArtifact:
    """Create one inert exact V0.5 MaterialPlan dependency."""

    path = root / "analysis" / "material_plan.json"
    _write_json(path, {"schema_version": "0.5.0", "fixture": True})
    return _artifact(
        root,
        path,
        artifact_id="material-plan",
        kind="v05-material-plan",
        media_type="application/json",
    )


def _bitmap_font(root: Path) -> ProjectLocalFont:
    """Create one exact project-local bitmap font containing only requested glyphs."""

    path = root / "assets" / "fonts" / "fixture-font.json"
    _write_json(
        path,
        {
            "schema_version": "0.1.0",
            "glyph_width": 3,
            "glyph_height": 5,
            "spacing": 1,
            "glyphs": {
                "A": ["010", "101", "111", "101", "101"],
                "B": ["110", "101", "110", "101", "110"],
            },
        },
    )
    return ProjectLocalFont(
        artifact=_artifact(
            root,
            path,
            artifact_id="fixture-font",
            kind="project-local-bitmap-font",
            media_type="application/json",
        ),
        font_format="bitmap_json_v1",
        license_id="fixture-project-owned",
        rights_status="project_owned",
        provenance="deterministic pytest bitmap font",
    )


def _exact_text_evidence(root: Path, text: str) -> ExactArtifact:
    """Create one strict exact-user-text artifact for local signage composition."""

    evidence = ExactSignageTextEvidenceV021(
        evidence_id="signage-text",
        text=text,
        text_sha256=sha256_file_bytes(text.encode("utf-8")),
        created_at=NOW,
    )
    path = root / "analysis" / "exact_signage_text.json"
    _write_json(path, evidence.model_dump(mode="json"))
    return _artifact(
        root,
        path,
        artifact_id="signage-text",
        kind="exact-signage-text-evidence",
        media_type="application/json",
    )


def _request(
    root: Path,
    *,
    run_id: str,
    strategy: str = "codex_generated_procedural_hybrid_v1",
    family: str = "wood",
    source_role: str = "base_color",
    exact_text: ExactTextCompositionV021 | None = None,
) -> CodexImageMaterialAuthoringRequestV021:
    """Build one strict staging-only request around exact fixture dependencies."""

    return CodexImageMaterialAuthoringRequestV021(
        request_id=f"request-{run_id}",
        job_id="image_material_fixture",
        workflow_id="wf-test",
        run_id=run_id,
        material_id="mat.main",
        strategy=strategy,
        material_family=family,
        output_root=f"material_authoring/codex_imagegen/runs/{run_id}",
        core_evidence=_core_bindings(root),
        source=_source(root, role=source_role),
        source_v05_contracts=[_v05_plan(root)],
        uv_identity=_uv_identity(root),
        scale_context=_scale_context(root),
        derivation=LocalImageDerivationPolicyV021(
            output_resolution=256,
            expected_grain_axis="none",
            minimum_spatial_standard_deviation=0.0,
            maximum_offset_edge_rmse=1.0,
        ),
        exact_text=exact_text,
        created_at=NOW,
    )


def _skip_core_parse_for_local_adapter_test(
    _root: Path,
    _request_value: CodexImageMaterialAuthoringRequestV021,
) -> set[str]:
    """Isolate local derivation tests from core-chain construction covered by core tests."""

    return {"base_color", "decal_rgb", "emission", "opacity_source"}


def _manifest(root: Path, receipt_path: str) -> CodexImageAuthoredMaterialManifestV021:
    """Load one strict manifest through its exact receipt path."""

    return CodexImageAuthoredMaterialManifestV021.model_validate_json(
        (root / receipt_path).read_bytes()
    )


def test_direct_channel_guards_and_unknown_text_fail_closed(tmp_path: Path) -> None:
    """Reject pseudo-PBR direct adoption and never carry glyphs for unknown signage."""

    request = _request(tmp_path, run_id="guard-model")
    output_path = tmp_path / "output.png"
    Image.new("RGB", (1, 1), (0, 0, 0)).save(output_path, format="PNG")
    output = _artifact(
        tmp_path,
        output_path,
        artifact_id="output",
        kind="raw-pbr-normal",
        media_type="image/png",
    )
    parameters = {"fixture": True}
    with pytest.raises(ValidationError, match="cannot directly supply"):
        CodexImageChannelDerivationV021(
            channel="normal",
            provenance_kind="codex_generated_direct",
            algorithm_id="invalid-direct-normal",
            algorithm_version="1.0.0",
            source_sha256=[request.source.artifact.sha256],
            parameters=parameters,
            parameters_sha256=codex_image_adapter.stable_json_digest(parameters),
            output=output,
            width=1,
            height=1,
            color_space="non_color",
            uv_identity=request.uv_identity,
            normal_convention="opengl_y_plus",
        )
    with pytest.raises(ValidationError, match="cannot carry invented glyphs"):
        ExactTextCompositionV021(
            evidence="unknown_text",
            text="INVENTED",
            font=_bitmap_font(tmp_path),
            uv_rect=UVRect(minimum=(0.1, 0.1), maximum=(0.9, 0.9)),
        )
    with pytest.raises(ValidationError, match="direct_role"):
        CodexImageMaterialSourceV021.model_validate(
            {
                **request.source.model_dump(mode="python"),
                "direct_role": "roughness",
                "color_space": "non_color",
            }
        )


def test_wood_hybrid_derivation_is_deterministic_and_staging_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Derive source-bound wood PBR bytes twice without canonical or destination writes."""

    monkeypatch.setattr(
        codex_image_adapter,
        "_validate_core_evidence",
        _skip_core_parse_for_local_adapter_test,
    )
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first_request = _request(first_root, run_id="wood-hybrid")
    first = author_codex_image_material_candidate(first_root, first_request)
    second = author_codex_image_material_candidate(
        second_root,
        _request(second_root, run_id="wood-hybrid"),
    )
    assert first.status == "published_to_staging"
    assert first.staging_only is True
    assert first.canonical_write_performed is False
    assert first.destination_write_performed is False
    assert first.output_bundle_sha256 == second.output_bundle_sha256
    assert [item.sha256 for item in first.outputs] == [item.sha256 for item in second.outputs]
    manifest = _manifest(first_root, first.manifest.path)
    assert manifest.status == "candidate_ready"
    assert manifest.actual_codex_imagegen_execution_verified is False
    assert manifest.blender_compilation_status == "not_run"
    assert {item.channel for item in manifest.channels} >= {
        "base_color",
        "height",
        "normal",
        "roughness",
        "metallic",
        "occlusion",
    }
    direct = [
        item.channel
        for item in manifest.channels
        if item.provenance_kind == "codex_generated_direct"
    ]
    assert set(direct) <= {"base_color", "emission", "opacity"}
    derived = [
        item
        for item in manifest.channels
        if item.provenance_kind == "local_deterministic_derivation"
    ]
    assert derived
    assert all(first_request.source.artifact.sha256 in item.source_sha256 for item in derived)
    assert not (first_root / "analysis" / "material_plan.generated.json").exists()
    assert validate_codex_image_material_candidate(first_root, first) == manifest
    tampered = first_root / first.outputs[0].path
    tampered.write_bytes(tampered.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="byte size changed"):
        validate_codex_image_material_candidate(first_root, first)


def test_strict_fake_core_adoption_chain_reaches_material_adapter(tmp_path: Path) -> None:
    """Accept one strict fake selected-image chain without claiming actual provider execution."""

    request = _strict_core_material_request(tmp_path)
    receipt = author_codex_image_material_candidate(tmp_path, request)
    manifest = validate_codex_image_material_candidate(tmp_path, receipt)
    assert manifest.status == "candidate_ready"
    assert manifest.actual_codex_imagegen_execution_verified is False
    assert manifest.core_evidence.adoption == request.core_evidence.adoption


def test_codex_image_material_blender_probe_has_no_dynamic_execution_surface() -> None:
    """Keep the fixed Blender probe free of dynamic code and arbitrary node authority."""

    repository_root = Path(__file__).resolve().parents[1]
    script = (
        repository_root
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "probe_codex_image_material_v021.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "eval(",
        "exec(",
        "ShaderNodeScript",
        "driver_add(",
        "bpy.data.libraries.load",
        "subprocess",
    ):
        assert forbidden not in script
    assert 'parser.add_argument("--manifest"' in script
    assert 'parser.add_argument("--output-root"' in script


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_CODEX_IMAGE_MATERIAL_BLENDER_SMOKE") != "1",
    reason="set CBM_RUN_CODEX_IMAGE_MATERIAL_BLENDER_SMOKE=1 for Blender 5.0.1 smoke",
)
@pytest.mark.parametrize("family", ["wood", "signage_decal", "emissive", "crystal"])
def test_fake_core_adoption_compiles_in_blender_5(tmp_path: Path, family: str) -> None:
    """Compile each fixed fake-adoption family without claiming actual ImageGen execution."""

    root = tmp_path / "isolated-job"
    root.mkdir()
    receipt = author_codex_image_material_candidate(
        root,
        _strict_core_material_request(root, family=family),
    )
    manifest_path = root / receipt.manifest.path
    manifest_sha256 = sha256_file(manifest_path)
    output_relative = f"material_authoring/codex_imagegen/blender_smoke/runs/fake-{family}"
    run_blender(
        "probe_codex_image_material_v021.py",
        [
            "--job-root",
            str(root),
            "--manifest",
            receipt.manifest.path,
            "--manifest-sha256",
            manifest_sha256,
            "--output-root",
            output_relative,
        ],
        factory_startup=True,
        disable_autoexec=True,
    )
    smoke = json.loads(
        (root / output_relative / "blender_smoke_receipt.json").read_text("utf-8")
    )
    assert smoke["status"] == "passed"
    assert smoke["blender_version"] == "5.0.1"
    assert smoke["material_family"] == family
    assert smoke["fake_completion_verified"] is True
    assert smoke["adoption_verified"] is True
    assert smoke["actual_codex_imagegen_execution_verified"] is False
    assert smoke["canonical_write_performed"] is False
    assert smoke["destination_write_performed"] is False
    assert smoke["source_manifest_unchanged"] is True
    assert smoke["runtime_parity_verified"] is False
    inventory = json.loads(
        (root / output_relative / "normalized_inventory.json").read_text("utf-8")
    )
    templates = {
        node["template_id"] for node in inventory["normalized_inventory"]["nodes"]
    }
    assert {
        "material_output",
        "principled_bsdf",
        "image_texture",
        "normal_map",
        "bump",
    } <= templates


@pytest.mark.parametrize("evidence", ["unknown_text", "inferred_placeholder"])
def test_decal_unknown_or_inferred_text_renders_no_glyphs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence: str,
) -> None:
    """Publish background channels but keep non-exact signage in review-required state."""

    monkeypatch.setattr(
        codex_image_adapter,
        "_validate_core_evidence",
        _skip_core_parse_for_local_adapter_test,
    )
    root = tmp_path / evidence
    root.mkdir()
    exact_text = ExactTextCompositionV021(
        evidence=evidence,
        uv_rect=UVRect(minimum=(0.1, 0.1), maximum=(0.9, 0.9)),
    )
    request = _request(
        root,
        run_id=f"decal-{evidence}",
        strategy="codex_generated_decal_v1",
        family="signage_decal",
        source_role="decal_rgb",
        exact_text=exact_text,
    )
    receipt = author_codex_image_material_candidate(root, request)
    manifest = _manifest(root, receipt.manifest.path)
    assert manifest.status == "review_required"
    assert manifest.exact_text is not None
    assert manifest.exact_text.evidence == evidence
    assert manifest.exact_text.rendered is False
    assert manifest.exact_text.glyph_count == 0
    assert manifest.exact_text.text_sha256 is None
    assert manifest.exact_text.font is None
    assert manifest.exact_text.output is None


def test_exact_signage_text_is_locally_composed_and_hash_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rasterize exact user glyphs with the exact project-local bitmap font only."""

    monkeypatch.setattr(
        codex_image_adapter,
        "_validate_core_evidence",
        _skip_core_parse_for_local_adapter_test,
    )
    root = tmp_path / "exact"
    root.mkdir()
    exact_text = ExactTextCompositionV021(
        evidence="exact_user_text",
        text="AB",
        text_evidence_artifact=_exact_text_evidence(root, "AB"),
        font=_bitmap_font(root),
        uv_rect=UVRect(minimum=(0.2, 0.2), maximum=(0.8, 0.8)),
        color=(1.0, 1.0, 1.0, 1.0),
    )
    request = _request(
        root,
        run_id="decal-exact",
        strategy="codex_generated_decal_v1",
        family="signage_decal",
        source_role="decal_rgb",
        exact_text=exact_text,
    )
    receipt = author_codex_image_material_candidate(root, request)
    manifest = _manifest(root, receipt.manifest.path)
    assert manifest.exact_text is not None
    assert manifest.exact_text.rendered is True
    assert manifest.exact_text.glyph_count == 2
    assert manifest.exact_text.text_sha256 == sha256_file_bytes(b"AB")
    assert manifest.exact_text.font == exact_text.font.artifact
    assert manifest.exact_text.output is not None
    base = next(item for item in manifest.channels if item.channel == "base_color")
    assert base.provenance_kind == "local_exact_text_composition"
    assert exact_text.font.artifact.sha256 in base.source_sha256


def sha256_file_bytes(payload: bytes) -> str:
    """Hash exact in-memory fixture bytes using the repository SHA-256 convention."""

    return hashlib.sha256(payload).hexdigest()
