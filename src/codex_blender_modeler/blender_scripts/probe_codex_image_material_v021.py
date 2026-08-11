"""Compile one fixed fake-provider MaterialAuthoring 0.2.1 candidate in Blender 5.

This is an isolated smoke probe, not a public compiler.  It accepts only the fixed
MaterialAuthoring 0.2.1 companion, validates the selected fake-completion/adoption
chain, compiles a hard-coded node whitelist, and writes only disposable smoke evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import bpy

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import probe_material_authoring_v02 as legacy  # noqa: E402

FIXTURE_VERSION = "0.1.0"
MANIFEST_PREFIX = "material_authoring/codex_imagegen/runs/"
OUTPUT_PREFIX = "material_authoring/codex_imagegen/blender_smoke/runs/"
DIRECT_ROLES = {"base_color", "decal_rgb", "emission", "opacity_source"}
DIRECT_OUTPUT_CHANNELS = {"base_color", "emission", "opacity"}
FAMILY_STRATEGIES = {
    "wood": "codex_generated_procedural_hybrid_v1",
    "signage_decal": "codex_generated_decal_v1",
    "emissive": "codex_generated_emission_v1",
    "crystal": "codex_generated_procedural_hybrid_v1",
}
REQUIRED_CHANNELS = {
    "wood": {"base_color", "height", "metallic", "normal", "opacity", "roughness"},
    "signage_decal": {"base_color", "normal", "opacity", "roughness"},
    "emissive": {"base_color", "emission", "normal", "opacity", "roughness"},
    "crystal": {"base_color", "emission", "normal", "opacity", "roughness"},
}
MANIFEST_FIELDS = {
    "actual_codex_imagegen_execution_verified",
    "blender_compilation_status",
    "canonical_v05_unchanged",
    "canonical_write_performed",
    "channels",
    "core_evidence",
    "created_at",
    "derivation_policy_sha256",
    "destination_write_performed",
    "exact_text",
    "job_id",
    "limitations",
    "manifest_id",
    "material_family",
    "material_id",
    "quality",
    "request",
    "run_id",
    "scale_context",
    "schema_version",
    "source",
    "source_v05_contracts",
    "staging_only",
    "status",
    "strategy",
    "uv_identity",
    "workflow_id",
}
REQUEST_FIELDS = {
    "base_roughness",
    "canonical_write_authority",
    "core_evidence",
    "created_at",
    "derivation",
    "destination_write_authority",
    "emission_strength",
    "exact_text",
    "job_id",
    "material_family",
    "material_id",
    "output_root",
    "request_id",
    "run_id",
    "scale_context",
    "schema_version",
    "source",
    "source_v05_contracts",
    "strategy",
    "uv_identity",
    "workflow_id",
}
CORE_BINDING_FIELDS = {
    "adoption",
    "selected_evidence",
    "selected_quality_report",
    "selection",
}
SOURCE_FIELDS = {
    "artifact",
    "color_space",
    "direct_role",
    "height",
    "license_id",
    "provenance",
    "rights_status",
    "width",
}
CHANNEL_FIELDS = {
    "algorithm_id",
    "algorithm_version",
    "channel",
    "color_space",
    "height",
    "normal_convention",
    "output",
    "parameters",
    "parameters_sha256",
    "provenance_kind",
    "source_sha256",
    "uv_identity",
    "width",
}
ADOPTION_FIELDS = {
    "adoption_id",
    "canonical_write_performed",
    "complete_pbr_set",
    "contract_id",
    "created_at",
    "derived_channels",
    "destination_write_performed",
    "direct_channels",
    "dispatch_id",
    "exact_text_composition",
    "generated_image_evidence",
    "input_sha256",
    "job_id",
    "material_strategy",
    "producer",
    "producer_version",
    "profile_id",
    "provenance",
    "provider_canonical_write",
    "provider_id",
    "quality_report",
    "schema_version",
    "selected_candidate",
    "selected_source_sha256",
    "selection",
    "session_id",
    "source_fingerprint",
    "target_material_ids",
    "workflow_id",
}
EVIDENCE_FIELDS = {
    "assignment",
    "candidate",
    "candidate_id",
    "complete_pbr_set",
    "completion",
    "contract_id",
    "controller_request",
    "controller_result",
    "created_at",
    "evidence_id",
    "generated_file",
    "generation_intent",
    "human_reviewed",
    "input_sha256",
    "job_id",
    "producer",
    "producer_version",
    "profile_id",
    "provenance",
    "provider_id",
    "rights_scope",
    "schema_version",
    "semantic_roles",
    "session_id",
    "source_fingerprint",
    "staging_only",
    "target_material_ids",
    "workflow_id",
    "dispatch_id",
}
GENERATED_FILE_FIELDS = {
    "alpha_present",
    "artifact",
    "candidate_id",
    "height",
    "image_format",
    "ordinal",
    "output_role",
    "width",
}
COMPLETION_FIELDS = {
    "assignment",
    "assignment_payload_sha256",
    "canonical_unchanged",
    "completion_id",
    "contract_id",
    "controller_executed_at",
    "controller_kind",
    "created_at",
    "dispatch_id",
    "edit_or_refinement_count",
    "execution_scope",
    "failures",
    "generated_files",
    "generation_count",
    "human_reviewed",
    "input_sha256",
    "job_id",
    "producer",
    "producer_version",
    "profile_id",
    "prompt_echo_sha256",
    "provenance",
    "provider_id",
    "schema_version",
    "session_id",
    "source_fingerprint",
    "source_inventory_sha256",
    "source_kind",
    "source_policy",
    "status",
    "warnings",
    "workflow_id",
}


def _argv_after_separator() -> list[str]:
    """Return only arguments explicitly supplied to this fixed Blender script."""

    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def _parse_args() -> argparse.Namespace:
    """Parse one exact manifest and one isolated smoke output root."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output-root", required=True)
    return parser.parse_args(_argv_after_separator())


def _require(value: bool, message: str) -> None:
    """Raise one consistent fail-closed fixed-fixture contract error."""

    if not value:
        raise legacy.FixtureContractError(message)


def _artifact_equal(left: object, right: object, label: str) -> None:
    """Require exact artifact dictionaries rather than path-only resemblance."""

    _require(left == right, f"{label} exact artifact binding differs")


def _load_bound_json(root: Path, artifact: object, label: str) -> tuple[dict, Path]:
    """Rehash one exact artifact and load its strict JSON object bytes."""

    _binding, path = legacy._validate_artifact(root, artifact, label)
    return legacy._load_json(path, label), path


def _validate_source_chain(
    root: Path,
    manifest: dict,
    request: dict,
) -> tuple[dict, dict, list[tuple[dict, Path]]]:
    """Validate adoption, generated evidence, and deterministic fake completion links."""

    core = legacy._strict_keys(
        manifest["core_evidence"],
        CORE_BINDING_FIELDS,
        "manifest core evidence",
    )
    _require(core == request["core_evidence"], "request core evidence binding differs")
    adoption, _adoption_path = _load_bound_json(root, core["adoption"], "adoption")
    adoption = legacy._strict_keys(adoption, ADOPTION_FIELDS, "adoption")
    _require(adoption["schema_version"] == "0.2.0", "adoption schema version differs")
    _require(
        adoption["provider_id"] == "codex_builtin_gpt_image_v1",
        "adoption provider identity differs",
    )
    _require(adoption["material_strategy"] == manifest["strategy"], "strategy differs")
    _require(manifest["material_id"] in adoption["target_material_ids"], "target differs")
    _require(
        set(adoption["direct_channels"]) <= DIRECT_ROLES,
        "adoption contains a forbidden direct channel",
    )
    for field in (
        "complete_pbr_set",
        "provider_canonical_write",
        "canonical_write_performed",
        "destination_write_performed",
    ):
        _require(adoption[field] is False, f"adoption {field} must remain false")
    _artifact_equal(adoption["selection"], core["selection"], "selection")
    _artifact_equal(
        adoption["generated_image_evidence"],
        core["selected_evidence"],
        "generated evidence",
    )
    _artifact_equal(
        adoption["quality_report"],
        core["selected_quality_report"],
        "quality report",
    )
    for label in ("selection", "selected_quality_report"):
        legacy._validate_artifact(root, core[label], label)
    evidence, _evidence_path = _load_bound_json(
        root,
        core["selected_evidence"],
        "selected generated evidence",
    )
    evidence = legacy._strict_keys(evidence, EVIDENCE_FIELDS, "generated evidence")
    generated_file = legacy._strict_keys(
        evidence["generated_file"],
        GENERATED_FILE_FIELDS,
        "generated file",
    )
    source = legacy._strict_keys(request["source"], SOURCE_FIELDS, "material source")
    _artifact_equal(generated_file["artifact"], source["artifact"], "selected source")
    _require(generated_file["output_role"] == source["direct_role"], "source role differs")
    _require(
        generated_file["width"] == source["width"]
        and generated_file["height"] == source["height"],
        "source dimensions differ",
    )
    _require(
        adoption["selected_source_sha256"] == source["artifact"]["sha256"],
        "adoption selected source SHA-256 differs",
    )
    completion, _completion_path = _load_bound_json(
        root,
        evidence["completion"],
        "fake completion",
    )
    completion = legacy._strict_keys(completion, COMPLETION_FIELDS, "fake completion")
    _require(completion["status"] == "completed", "fake completion is not completed")
    _require(
        completion["controller_kind"] == "fake_for_tests"
        and completion["execution_scope"] == "deterministic_fake"
        and completion["source_kind"] == "deterministic_fake",
        "Blender smoke requires explicit deterministic fake completion evidence",
    )
    _require(
        generated_file in completion["generated_files"],
        "fake completion does not contain the selected generated file",
    )
    tracked = [
        legacy._validate_artifact(root, core[name], name)
        for name in CORE_BINDING_FIELDS
    ]
    tracked.append(legacy._validate_artifact(root, source["artifact"], "selected source"))
    tracked.append(legacy._validate_artifact(root, evidence["completion"], "completion"))
    return adoption, completion, tracked


def _validate_channel(
    root: Path,
    value: object,
    source_sha256: str,
) -> tuple[str, dict, tuple[dict, Path]]:
    """Validate one fixed raw channel, its role, parameters, and source hash binding."""

    channel = legacy._strict_keys(value, CHANNEL_FIELDS, "material channel")
    channel_id = channel["channel"]
    _require(channel_id in legacy.CHANNEL_COLOR_SPACE, "unknown raw PBR channel")
    expected_space = "srgb" if channel_id in {"base_color", "emission"} else "non_color"
    _require(channel["color_space"] == expected_space, "channel color-space differs")
    _require(source_sha256 in channel["source_sha256"], "channel omits selected source hash")
    _require(
        channel["parameters_sha256"] == legacy._canonical_sha256(channel["parameters"]),
        "channel parameter hash differs",
    )
    if channel["provenance_kind"] == "codex_generated_direct":
        _require(channel_id in DIRECT_OUTPUT_CHANNELS, "forbidden pseudo-PBR direct channel")
    else:
        _require(
            channel["provenance_kind"]
            in {
                "local_deterministic_derivation",
                "local_exact_text_composition",
                "local_constant",
            },
            "unknown channel provenance kind",
        )
    if channel_id == "normal":
        _require(
            channel["normal_convention"] == "opengl_y_plus",
            "normal convention differs",
        )
    else:
        _require(channel["normal_convention"] is None, "unexpected normal convention")
    artifact_binding, path = legacy._validate_artifact(
        root,
        channel["output"],
        f"{channel_id} output",
    )
    resolved = dict(channel)
    resolved["artifact"] = artifact_binding
    resolved["resolved_path"] = path
    return channel_id, resolved, (artifact_binding, path)


def _validate_manifest(
    root: Path,
    manifest_path: Path,
    expected_sha256: str,
) -> tuple[dict, dict, dict[str, dict], list[tuple[dict, Path]]]:
    """Validate the fixed companion, every source, and every raw channel before Blender."""

    _require(
        legacy._sha256_file(manifest_path) == expected_sha256,
        "MaterialAuthoring 0.2.1 manifest SHA-256 mismatch",
    )
    manifest = legacy._strict_keys(
        legacy._load_json(manifest_path, "material manifest"),
        MANIFEST_FIELDS,
        "material manifest",
    )
    _require(manifest["schema_version"] == "0.2.1", "manifest schema version differs")
    _require(manifest["status"] == "candidate_ready", "manifest is not candidate-ready")
    _require(manifest["staging_only"] is True, "manifest is not staging-only")
    _require(manifest["canonical_v05_unchanged"] is True, "canonical V0.5 changed")
    for field in (
        "canonical_write_performed",
        "destination_write_performed",
        "actual_codex_imagegen_execution_verified",
    ):
        _require(manifest[field] is False, f"manifest {field} must remain false")
    _require(
        manifest["blender_compilation_status"] == "not_run",
        "source manifest already claims Blender compilation",
    )
    family = manifest["material_family"]
    _require(family in FAMILY_STRATEGIES, "unsupported fixed image material family")
    _require(manifest["strategy"] == FAMILY_STRATEGIES[family], "family strategy differs")
    request_binding, request_path = legacy._validate_artifact(
        root,
        manifest["request"],
        "material request",
    )
    request = legacy._strict_keys(
        legacy._load_json(request_path, "material request"),
        REQUEST_FIELDS,
        "material request",
    )
    _require(request["schema_version"] == "0.2.1", "request schema version differs")
    for field in ("job_id", "workflow_id", "run_id", "material_id", "strategy", "material_family"):
        _require(request[field] == manifest[field], f"request {field} differs")
    _require(request["canonical_write_authority"] is False, "canonical authority granted")
    _require(request["destination_write_authority"] is False, "destination authority granted")
    _require(
        request["output_root"] == f"{MANIFEST_PREFIX}{request['run_id']}",
        "request output root differs from its run identity",
    )
    _require(
        manifest["derivation_policy_sha256"]
        == legacy._canonical_sha256(request["derivation"]),
        "derivation policy hash differs",
    )
    adoption, _completion, tracked = _validate_source_chain(root, manifest, request)
    source_sha256 = request["source"]["artifact"]["sha256"]
    channel_map: dict[str, dict] = {}
    channel_artifacts: list[tuple[dict, Path]] = []
    for value in manifest["channels"]:
        channel_id, channel, artifact = _validate_channel(root, value, source_sha256)
        _require(channel_id not in channel_map, "duplicate material channel")
        channel_map[channel_id] = channel
        channel_artifacts.append(artifact)
    _require(
        REQUIRED_CHANNELS[family] <= set(channel_map),
        "fixed family is missing required raw channels",
    )
    _require(
        manifest["quality"]["outcome"] == "passed",
        "local deterministic material quality did not pass",
    )
    _require(adoption["material_strategy"] == request["strategy"], "adoption differs")
    dependencies: list[tuple[dict, Path]] = [(request_binding, request_path)]
    for artifact in request["source_v05_contracts"]:
        dependencies.append(legacy._validate_artifact(root, artifact, "V0.5 source"))
    dependencies.append(
        legacy._validate_artifact(root, request["uv_identity"]["evidence"], "UV identity")
    )
    dependencies.append(
        legacy._validate_artifact(
            root,
            request["scale_context"]["artifact"],
            "scale context",
        )
    )
    manifest["_fixture_manifest_sha256"] = expected_sha256
    return manifest, request, channel_map, [*dependencies, *tracked, *channel_artifacts]


def _synthetic_family_parameters(request: dict, family: str) -> dict:
    """Translate only bounded constants needed by the existing fixed node compiler."""

    if family == "wood":
        return {"procedural_wood": {"finish_coating_amount": 0.0}}
    if family == "signage_decal":
        return {"localized_decal": {"emission_strength": request["emission_strength"]}}
    if family == "emissive":
        return {"emissive_pattern": {"emission_strength": request["emission_strength"]}}
    return {
        "crystal": {
            "emission_strength": request["emission_strength"],
            "ior": 1.45,
            "transmission": 0.0,
        }
    }


def _revalidate_sources(
    manifest_path: Path,
    manifest_sha256: str,
    tracked: list[tuple[dict, Path]],
) -> None:
    """Rehash the immutable source manifest and every exact dependency after rendering."""

    _require(
        legacy._sha256_file(manifest_path) == manifest_sha256,
        "source material manifest changed during Blender smoke",
    )
    for artifact, path in tracked:
        _require(path.stat().st_size == artifact["byte_size"], "source byte size changed")
        _require(legacy._sha256_file(path) == artifact["sha256"], "source hash changed")


def main() -> None:
    """Validate, compile, reopen, render, and atomically publish isolated smoke evidence."""

    args = _parse_args()
    root = Path(args.job_root).resolve(strict=True)
    _require(root.is_dir(), "job root is not a directory")
    manifest_relative = legacy._relative_path(args.manifest, "manifest path")
    output_relative = legacy._relative_path(args.output_root, "output root")
    _require(manifest_relative.startswith(MANIFEST_PREFIX), "manifest path is outside staging")
    _require(output_relative.startswith(OUTPUT_PREFIX), "smoke output is outside its root")
    legacy._portable_id(output_relative.removeprefix(OUTPUT_PREFIX), "smoke run ID")
    manifest_path = legacy._resolve_contained(root, manifest_relative, must_exist=True)
    manifest_sha256 = legacy._sha256(args.manifest_sha256, "manifest SHA-256")
    manifest, request, channels, tracked = _validate_manifest(
        root,
        manifest_path,
        manifest_sha256,
    )
    final_root = legacy._resolve_contained(root, output_relative, must_exist=False)
    _require(not final_root.exists(), "smoke output root already exists")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    stage_root = final_root.parent / f".{final_root.name}.staging-{uuid4().hex}"
    stage_root.mkdir()
    compile_request = _synthetic_family_parameters(request, manifest["material_family"])
    material, sockets, compiler_limitations = legacy._compile_material(
        manifest,
        compile_request,
        channels,
    )
    material_name = material.name
    blend_path, engine = legacy._create_scene(
        material,
        manifest["material_family"],
        stage_root,
    )
    preview_path = stage_root / "neutral_preview.png"
    _require(preview_path.is_file() and preview_path.stat().st_size > 0, "render is missing")
    bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=False)
    inventory = legacy._inventory_material(material_name, sockets)
    inventory_path = stage_root / "normalized_inventory.json"
    legacy._write_json(inventory_path, inventory)
    _revalidate_sources(manifest_path, manifest_sha256, tracked)
    _require(tuple(bpy.app.version[:3]) == (5, 0, 1), "smoke requires Blender 5.0.1")
    final_prefix = output_relative + "/"
    artifacts = [
        legacy._artifact_receipt(
            blend_path,
            final_prefix + "compiled_fixture.blend",
            "compiled_blend",
        ),
        legacy._artifact_receipt(
            preview_path,
            final_prefix + "neutral_preview.png",
            "neutral_preview",
        ),
        legacy._artifact_receipt(
            inventory_path,
            final_prefix + "normalized_inventory.json",
            "normalized_inventory",
        ),
    ]
    receipt = {
        "actual_codex_imagegen_execution_verified": False,
        "adoption_verified": True,
        "arbitrary_code_used": False,
        "artifacts": artifacts,
        "blender_version": bpy.app.version_string,
        "canonical_write_performed": False,
        "destination_write_performed": False,
        "external_provider_used": False,
        "fake_completion_verified": True,
        "fixture_id": final_root.name,
        "fixture_scope": "fake_adoption_compile_reopen_neutral_preview_only",
        "limitations": [
            *compiler_limitations,
            "deterministic fake pixels do not verify actual Codex built-in ImageGen execution",
            "review evidence is not package acceptance or destination runtime parity",
        ],
        "manifest_path": manifest_relative,
        "manifest_sha256": manifest_sha256,
        "material_family": manifest["material_family"],
        "normalized_inventory_sha256": inventory["normalized_inventory_sha256"],
        "render_engine": engine,
        "runtime_parity_verified": False,
        "schema_version": FIXTURE_VERSION,
        "source_manifest_unchanged": True,
        "status": "passed",
    }
    legacy._write_json(stage_root / "blender_smoke_receipt.json", receipt)
    os.replace(stage_root, final_root)
    print(
        json.dumps(
            {
                "blender_version": bpy.app.version_string,
                "fake_completion_verified": True,
                "fixture_id": final_root.name,
                "status": "passed",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
