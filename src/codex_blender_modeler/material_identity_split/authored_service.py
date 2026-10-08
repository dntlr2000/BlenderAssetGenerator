"""Host-only candidate preparation for the explicit authored-material 0.2 profile."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from .. import authored_material_runtime as material_runtime
from .. import authored_split_runtime as runtime
from ..analysis.models import ModelingPlan
from ..attachment_runtime import selected_attachment
from ..blender_artifacts import native_io_path, publish_bytes_create_once, sha256_file
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..config import get_settings
from ..materials.models import MaterialPlan
from ..models import SceneSpec
from ..orchestration.attachment_revision import _proofs, _require_successor_capacity
from ..paired_revision_runtime import _file, assert_no_pending_pair
from ..reference_scope import reference_content_scope_from_metadata, validate_scene_content_scope
from ..structural_geometry.mesh_payload_v02 import MeshPayloadV02
from .authored_materials import prepare_material_derivatives, validate_material_contracts
from .authored_models import (
    AuthoredMaterialIdentitySplitApprovalRequestV02,
    AuthoredMaterialIdentitySplitApprovalV02,
    AuthoredMaterialIdentitySplitInvariantsV02,
    AuthoredMaterialIdentitySplitPlanV02,
    AuthoredMaterialIdentitySplitPreapprovalV02,
    AuthoredMaterialIdentitySplitRootProofsV02,
    AuthoredMaterialIdentitySplitTechnicalApprovalRequestV02,
    AuthoredMaterialIdentitySplitTechnicalApprovalV02,
    AuthoredSplitAttachmentRecordV02,
    MaterialIdentityCloneRuleV02,
)
from .service import _blender_executable

NATIVE_SCRIPTS = (
    "inspect_scene.py",
    "validate_scene.py",
    "authored_split_native.py",
)


def publish(root: Path, path: str, payload) -> dict:
    """Publish immutable run-owned bytes through contained Windows long-path-safe I/O."""
    content = (
        payload
        if isinstance(payload, bytes)
        else runtime.encode(
            payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
        )
    )
    limit = runtime.MAX_BINARY_BYTES if path.endswith(".blend") else 8 * 1024 * 1024
    if len(content) > limit:
        raise ValueError("authored split staged artifact exceeds byte bound")
    destination = _file(root, path, exists=False)
    Path(native_io_path(destination.parent)).mkdir(parents=True, exist_ok=True)
    _file(root, path, exists=False)
    publish_bytes_create_once(destination, content)
    return runtime.reference(root, path)


def _identity(root: Path, run_id: str, profile: str = runtime.PROFILE) -> dict:
    """Return explicit profile identity shared by every authored specialized contract."""
    runtime.prefix(run_id)
    return {"job_id": root.name, "run_id": run_id, "profile": profile}


def _shadow_inputs(
    root: Path, base: str, source_files: dict, dependencies: dict, scene: dict, model: dict
) -> Path:
    """Materialize a candidate-only geometry shadow, retaining the authored MaterialPlan bytes.

    No job registration or canonical selection is fabricated here. The final prospective
    provenance is composed separately from the real source observations.
    """
    shadow = _file(root, f"{base}/shadow/analysis/scene_spec.json", exists=False).parent.parent
    for path, digest in dependencies.items():
        publish(root, f"{base}/shadow/{path}", runtime.read(root, {"path": path, "sha256": digest}))
    for path, ref in (
        ("analysis/scene_spec.json", scene),
        ("analysis/modeling_plan.json", model),
        ("analysis/material_plan.json", source_files["analysis/material_plan.json"]),
    ):
        publish(root, f"{base}/shadow/{path}", runtime.read(root, ref))
    if (shadow / "job.json").exists() or (
        shadow / "production/surface_attachment/registration.json"
    ).exists():
        raise ValueError("authored split shadow cannot masquerade as a registered canonical job")
    return shadow


def _prospective_provenance(
    root: Path,
    shadow: Path,
    source_provenance: dict,
    source_files: dict,
    candidate_intent: dict,
    revision: dict,
    registration_hash: str,
    material_dependencies: dict,
    run_id: str,
) -> dict:
    """Compose prospective provenance without selecting fabricated canonical state."""
    value = collect_build_provenance(
        shadow, root.name, validate_contracts=True, material_plan_mode="scene_spec_only"
    )
    value.pop("fingerprint")
    value["material_plan_mode"] = "authored_identity_preserved"
    if "reference_content_scope" in source_provenance:
        value["reference_content_scope"] = source_provenance["reference_content_scope"]
    value["attachment_intent"] = candidate_intent
    value["attachment_registration_sha256"] = registration_hash
    value["attachment_revision"] = revision
    value["authored_material_identity_split_closure"] = material_runtime.identity_split_closure(
        run_id,
        material_dependencies,
        source_files,
        source_provenance,
    )
    value["fingerprint"] = runtime.stable(value)
    return value


def _reject_overrides(root: Path) -> None:
    """Forbid effective-geometry overrides rather than silently ignoring them."""
    path = root / "analysis/material_binding_derivative.json"
    if path.exists() or path.is_symlink():
        raise ValueError("authored split forbids material_binding_derivative overrides")


def prepare_authored_material_identity_split(
    job_root: Path,
    *,
    run_id: str,
    clone_rules: list[MaterialIdentityCloneRuleV02 | dict],
    source_material_plan_mode: str = "current",
    delegation_path: str | None = None,
) -> dict:
    """Derive strict material-only candidates and full source/F32 proofs, never approval."""
    root = job_root.expanduser().resolve(strict=True)
    assert_no_pending_pair(root)
    _reject_overrides(root)
    profile = runtime.DELEGATED_PROFILE if delegation_path is not None else runtime.PROFILE
    identity, base = _identity(root, run_id, profile), runtime.prefix(run_id)
    delegation = runtime.reference(root, delegation_path) if delegation_path is not None else None
    if (root / base).exists():
        raise FileExistsError("authored split run already exists; use a fresh run identity")
    if not isinstance(clone_rules, (list, tuple)) or not 1 <= len(clone_rules) <= 128:
        raise ValueError("authored split requires 1–128 clone rules before allocation")
    before = {path: runtime.reference(root, path) for path in sorted(runtime.SOURCE_PATHS)}
    rules = [
        rule
        if isinstance(rule, MaterialIdentityCloneRuleV02)
        else MaterialIdentityCloneRuleV02.model_validate(rule)
        for rule in clone_rules
    ]
    raw_rules = [rule.model_dump(mode="json") for rule in rules]
    for key in ("new_material_id", "target_object_id"):
        if len({rule[key] for rule in raw_rules}) != len(raw_rules):
            raise ValueError("authored split clone rule identities must be unique")
    scene = SceneSpec.model_validate_json(runtime.read(root, before["analysis/scene_spec.json"]))
    ModelingPlan.model_validate_json(runtime.read(root, before["analysis/modeling_plan.json"]))
    material = MaterialPlan.model_validate_json(
        runtime.read(root, before["analysis/material_plan.json"])
    )
    if material.job_id != root.name or material.stage != "authored":
        raise ValueError("authored split requires this job's present authored MaterialPlan")
    if not {item.material_id for item in material.materials} <= {
        item.id for item in scene.materials
    }:
        raise ValueError("authored MaterialPlan references an unknown source material")
    selected = selected_attachment(root, root.name, root / "analysis/scene_spec.json")
    if selected is None:
        raise ValueError("authored split requires explicit registered solid-root selection")
    old = json.loads(runtime.read(root, selected))
    if old.get("contract_kind") != "solid_root_attachment_intent":
        raise ValueError("authored split supports only the registered solid-root 0.1 domain")
    metadata = json.loads(runtime.read(root, before["job.json"]))
    if delegation is not None:
        runtime.validate_delegation(
            root,
            delegation,
            {
                "run_id": run_id,
                "profile": profile,
                "source_files": before,
                "clone_rules": raw_rules,
            },
        )
    # Bound the entire existing graph before source proofs, cloning or staging.
    source_dependencies = runtime.source_dependency_snapshot(
        root,
        json.loads(runtime.read(root, before["analysis/scene_spec.json"])),
        json.loads(runtime.read(root, before["analysis/modeling_plan.json"])),
        json.loads(runtime.read(root, before["analysis/material_plan.json"])),
        metadata,
    )
    scope, subject = reference_content_scope_from_metadata(metadata)
    validate_scene_content_scope(scene, scope=scope, target_subject=subject)
    _require_successor_capacity(root, metadata.get("attachment_revision"))
    staged, sizes = {}, {path: _file(root, path).stat().st_size for path in source_dependencies}

    def stage(path, payload):
        """Bound prospective source-plus-candidate closure before any proof or publication."""
        content = payload if isinstance(payload, bytes) else runtime.encode(payload)
        if len(content) > 8 * 1024 * 1024:
            raise ValueError("authored split prospective artifact exceeds JSON byte bound")
        if path in staged and staged[path] != content:
            raise ValueError("authored split prospective path collision")
        sizes[path] = len(content)
        if len(sizes) > 512 or sum(sizes.values()) > 64 * 1024 * 1024:
            raise ValueError("authored split prospective whole closure exceeds bound")
        staged[path] = content
        return {"path": path, "sha256": runtime.sha(content)}

    # Keep exact authored values/order rather than normalizing source documents.
    raw_scene = json.loads(runtime.read(root, before["analysis/scene_spec.json"]))
    raw_model = json.loads(runtime.read(root, before["analysis/modeling_plan.json"]))
    objects = {item["id"]: item for item in raw_scene["objects"]}
    derivatives = []
    for ordinal, rule in enumerate(raw_rules):
        obj = objects.get(rule["target_object_id"])
        if obj is None or obj.get("geometry", {}).get("kind") != "custom_mesh":
            raise ValueError("authored split clone must target an existing strict mesh")
        source_ref = runtime.reference(root, obj["geometry"]["path"])
        payload = json.loads(runtime.read(root, source_ref))
        MeshPayloadV02.model_validate_json(runtime.encode(payload)).assert_compilable()
        derivative = runtime.derivative_payload(payload, rule, source_ref)
        MeshPayloadV02.model_validate_json(runtime.encode(derivative)).assert_compilable()
        candidate = stage(f"{base}/candidate/mesh_{ordinal:03d}.json", derivative)
        derivatives.append(
            {"object_id": rule["target_object_id"], "source": source_ref, "candidate": candidate}
        )
    material_derivatives = prepare_material_derivatives(
        root,
        run_id,
        raw_scene,
        json.loads(runtime.read(root, before["analysis/material_plan.json"])),
        raw_rules,
        publisher=stage,
    )
    candidate_scene, candidate_model = runtime.candidate_projection(
        raw_scene, raw_model, raw_rules, derivatives, material_derivatives
    )
    for payload, contract in ((candidate_scene, SceneSpec), (candidate_model, ModelingPlan)):
        content = runtime.encode(payload)
        if len(content) > 8 * 1024 * 1024:
            raise ValueError("authored split prospective contract exceeds JSON byte bound")
        contract.model_validate_json(content)
    source_provenance = collect_build_provenance(
        root, root.name, material_plan_mode=source_material_plan_mode
    )
    source_proof, source_float32 = _proofs(
        root,
        old,
        {
            "analysis/scene_spec.json": runtime.read(root, before["analysis/scene_spec.json"]),
            "analysis/modeling_plan.json": runtime.read(
                root, before["analysis/modeling_plan.json"]
            ),
        },
    )
    source_files = {
        path: publish(
            root, f"{base}/source/{path}", runtime.read(root, ref, binary=path.endswith(".blend"))
        )
        for path, ref in before.items()
    }
    for path, content in staged.items():
        publish(root, path, content)
    scene_ref = publish(root, f"{base}/candidate/scene.json", candidate_scene)
    model_ref = publish(root, f"{base}/candidate/model.json", candidate_model)
    candidate_intent = copy.deepcopy(old)
    candidate_intent["source_scene"]["sha256"] = scene_ref["sha256"]
    candidate_intent["source_modeling_plan"]["sha256"] = model_ref["sha256"]
    replacement = {item["source"]["path"]: item["candidate"] for item in derivatives}
    candidate_intent["source_geometry"] = [
        replacement.get(item["path"], item) for item in old["source_geometry"]
    ]
    intent_ref = publish(root, f"{base}/candidate/attachment.json", candidate_intent)
    record = AuthoredSplitAttachmentRecordV02(
        job_id=root.name,
        run_id=run_id,
        profile=profile,
        workflow_id=runtime.workflow_identity(run_id),
        initial_registration={
            "path": "production/surface_attachment/registration.json",
            "sha256": metadata["attachment_registration_sha256"],
        },
        previous_revision=metadata.get("attachment_revision"),
        previous_intent=selected,
        candidate_intent=intent_ref,
        metadata_before_sha256=before["job.json"]["sha256"],
    )
    revision_ref = publish(root, f"{base}/candidate/revision.json", record)
    new_metadata = copy.deepcopy(metadata)
    new_metadata["attachment_revision"] = revision_ref
    metadata_ref = publish(root, f"{base}/candidate/job.json", new_metadata)
    candidate_proof, candidate_float32 = _proofs(
        root,
        candidate_intent,
        {
            "analysis/scene_spec.json": runtime.read(root, scene_ref),
            "analysis/modeling_plan.json": runtime.read(root, model_ref),
        },
    )
    proofs_ref = publish(
        root,
        f"{base}/candidate/root_proofs.json",
        AuthoredMaterialIdentitySplitRootProofsV02(
            **identity,
            source_binary64=source_proof,
            source_float32=source_float32,
            candidate_binary64=candidate_proof,
            candidate_float32=candidate_float32,
        ),
    )
    extras = [old["source_reference"], old["source_camera_hypothesis"]]
    for key in ("reference_analysis_path", "camera_solution_path"):
        if raw_model.get(key):
            extras.append(
                runtime.reference(root, runtime.preserved_evidence_relative(root, raw_model, key))
            )
    material_dependencies = material_runtime.material_dependencies(
        root,
        raw_scene,
        json.loads(runtime.read(root, before["analysis/material_plan.json"])),
        material_derivatives,
    )
    extras.extend(
        {"path": path, "sha256": digest} for path, digest in material_dependencies.items()
    )
    dependencies = runtime.geometry_dependencies(root, [old, candidate_intent], extras)
    if any(path in runtime.SOURCE_PATHS for path in dependencies):
        raise ValueError("authored split geometry dependencies must use immutable retained sources")
    if source_provenance.get("interior_contracts") is not None:
        raise ValueError("authored solid-root split does not expand into interior-scope jobs")
    shadow = _shadow_inputs(root, base, source_files, dependencies, scene_ref, model_ref)
    provenance = _prospective_provenance(
        root,
        shadow,
        source_provenance,
        source_files,
        intent_ref,
        revision_ref,
        record.initial_registration.sha256,
        material_dependencies,
        run_id,
    )
    provenance_ref = publish(root, f"{base}/candidate/provenance.json", provenance)
    source_provenance_ref = publish(
        root, f"{base}/candidate/source_provenance.json", source_provenance
    )
    plan = AuthoredMaterialIdentitySplitPlanV02(
        **identity,
        created_at=datetime.now(UTC),
        delegation=delegation,
        clone_rules=rules,
        source_files=source_files,
        immutable_dependencies=dependencies,
        candidate_scene_spec=scene_ref,
        candidate_modeling_plan=model_ref,
        candidate_job_metadata=metadata_ref,
        candidate_attachment_intent=intent_ref,
        attachment_revision=revision_ref,
        derivatives=derivatives,
        material_derivatives=material_derivatives,
        material_dependencies=material_dependencies,
        root_proofs=proofs_ref,
        prospective_build_provenance=provenance_ref,
        source_build_provenance=source_provenance_ref,
        source_material_plan_mode=source_material_plan_mode,
    )
    plan_ref = publish(root, f"{base}/plan.json", plan)
    validate_authored_split_plan(root, plan_ref, current=True)
    return {
        "plan": plan.model_dump(mode="json"),
        "plan_artifact": plan_ref,
        "canonical_write_count": 0,
    }


def validate_authored_split_plan(root: Path, plan_ref: dict, *, current: bool = True) -> dict:
    """Revalidate strict contracts, complete source/F32 proofs and prospective provenance."""
    _reject_overrides(root)
    checked = runtime.validate_plan(root, plan_ref, current=current)
    plan = checked["plan"]
    validate_material_contracts(root, plan)
    AuthoredMaterialIdentitySplitPlanV02.model_validate_json(runtime.read(root, plan_ref))
    source_material = MaterialPlan.model_validate_json(
        checked["sources"]["analysis/material_plan.json"]
    )
    if source_material.stage != "authored" or source_material.job_id != root.name:
        raise ValueError("authored split source MaterialPlan is not authored for this job")
    for raw in (
        checked["sources"]["analysis/scene_spec.json"],
        runtime.read(root, plan["candidate_scene_spec"]),
    ):
        SceneSpec.model_validate_json(raw)
    for raw in (
        checked["sources"]["analysis/modeling_plan.json"],
        runtime.read(root, plan["candidate_modeling_plan"]),
    ):
        ModelingPlan.model_validate_json(raw)
    for artifact in [*checked["old"]["source_geometry"], *checked["new"]["source_geometry"]]:
        MeshPayloadV02.model_validate_json(runtime.read(root, artifact)).assert_compilable()
    if current:
        _require_successor_capacity(root, checked["record"]["previous_revision"])
        assert_no_pending_pair(root)
        selected = selected_attachment(root, root.name, root / "analysis/scene_spec.json")
        if selected != checked["record"]["previous_intent"]:
            raise ValueError("authored split selected source attachment changed")
        source_provenance = collect_build_provenance(
            root, root.name, material_plan_mode=plan["source_material_plan_mode"]
        )
        if source_provenance != checked["candidates"]["source_build_provenance"]:
            raise ValueError("authored split source build provenance changed")
    expected = {}
    for name, document, sources in (
        (
            "source",
            checked["old"],
            {
                key: checked["sources"][key]
                for key in ("analysis/scene_spec.json", "analysis/modeling_plan.json")
            },
        ),
        (
            "candidate",
            checked["new"],
            {
                "analysis/scene_spec.json": runtime.read(root, plan["candidate_scene_spec"]),
                "analysis/modeling_plan.json": runtime.read(root, plan["candidate_modeling_plan"]),
            },
        ),
    ):
        expected[f"{name}_binary64"], expected[f"{name}_float32"] = _proofs(root, document, sources)
    actual = checked["candidates"]["root_proofs"]
    if any(actual[key] != value for key, value in expected.items()):
        raise ValueError("authored split complete source/Float32 proof changed")
    shadow = root / runtime.prefix(plan["run_id"]) / "shadow"
    for path, digest in plan["immutable_dependencies"].items():
        runtime.read(shadow, {"path": path, "sha256": digest})
    for path, ref in (
        ("analysis/scene_spec.json", plan["candidate_scene_spec"]),
        ("analysis/modeling_plan.json", plan["candidate_modeling_plan"]),
        ("analysis/material_plan.json", plan["source_files"]["analysis/material_plan.json"]),
    ):
        runtime.read(shadow, {"path": path, "sha256": ref["sha256"]})
    _reject_overrides(shadow)
    expected_provenance = _prospective_provenance(
        root,
        shadow,
        checked["candidates"]["source_build_provenance"],
        plan["source_files"],
        plan["candidate_attachment_intent"],
        plan["attachment_revision"],
        checked["record"]["initial_registration"]["sha256"],
        plan["material_dependencies"],
        plan["run_id"],
    )
    if expected_provenance != checked["candidates"]["prospective_build_provenance"]:
        raise ValueError("authored split exact prospective build provenance changed")
    return checked


def _native(root: Path, plan_ref: dict, stage: str, *, finalize: bool = False) -> None:
    """Run only the fixed plan-bound inspector/finalizer against one predeclared Blend."""
    plan = runtime.contract(root, plan_ref, "plan")
    base = runtime.prefix(plan["run_id"])
    blend = root / (
        "blender/scene.blend"
        if stage == "source" or finalize
        else f"{base}/shadow/{'build' if finalize else 'final'}.blend"
    )
    _file(root, blend.relative_to(root).as_posix())
    if finalize:
        _file(root, f"{base}/shadow/final.blend", exists=False)
    args = [
        "--job-root",
        str(root),
        "--plan",
        plan_ref["path"],
        "--plan-sha256",
        plan_ref["sha256"],
        "--stage",
        stage,
    ]
    if finalize:
        args.append("--finalize")
    run_blender(
        "authored_split_native.py",
        args,
        blend_file=blend,
        factory_startup=True,
        disable_autoexec=True,
    )


def run_authored_material_identity_split_preapproval(job_root: Path, *, plan_path: str) -> dict:
    """Clone source materials, inspect full native equality and request an exact decision."""
    root = job_root.expanduser().resolve(strict=True)
    plan_ref = runtime.reference(root, plan_path)
    checked = validate_authored_split_plan(root, plan_ref)
    plan, base = checked["plan"], runtime.prefix(checked["plan"]["run_id"])
    if (root / base / "preapproval.json").exists() or (root / base / "failure.json").exists():
        raise FileExistsError("authored split preapproval attempt already exists")
    try:
        for leaf in (
            "source_native.json",
            "candidate_native.json",
            "shadow/build.blend",
            "shadow/final.blend",
            "shadow/scene_inventory.json",
            "shadow/validation.json",
        ):
            output = _file(root, f"{base}/{leaf}", exists=False)
            if output.exists():
                raise FileExistsError("authored split native attempt output already exists")
        scripts = get_settings().repo_root / "src/codex_blender_modeler/blender_scripts"
        script_hashes = {}
        for name in NATIVE_SCRIPTS:
            content = (scripts / name).read_bytes()
            script_hashes[f"src/codex_blender_modeler/blender_scripts/{name}"] = runtime.sha(
                content
            )
            publish(root, f"{base}/native_scripts/{name}", content)
        executable_hash = sha256_file(_blender_executable())
        _native(root, plan_ref, "source")
        shadow = root / base / "shadow"
        _native(root, plan_ref, "candidate", finalize=True)
        _native(root, plan_ref, "candidate")
        run_blender(
            "inspect_scene.py",
            ["--output", str(shadow / "scene_inventory.json")],
            blend_file=shadow / "final.blend",
            factory_startup=True,
            disable_autoexec=True,
        )
        run_blender(
            "validate_scene.py",
            [
                "--spec",
                str(shadow / "analysis/scene_spec.json"),
                "--output",
                str(shadow / "validation.json"),
            ],
            blend_file=shadow / "final.blend",
            factory_startup=True,
            disable_autoexec=True,
        )
        validation = json.loads((shadow / "validation.json").read_bytes())
        if validation.get("ok") is not True:
            raise ValueError("authored split native shadow validation failed")
        source_native = runtime.reference(root, f"{base}/source_native.json")
        candidate_native = runtime.reference(root, f"{base}/candidate_native.json")
        runtime.validate_native_invariants(root, plan_ref, source_native, candidate_native)
        validate_authored_split_plan(root, plan_ref)
        identity = _identity(root, plan["run_id"], plan["profile"])
        invariant = publish(
            root,
            f"{base}/invariants.json",
            AuthoredMaterialIdentitySplitInvariantsV02(
                **identity,
                plan=plan_ref,
                source_native_inventory=source_native,
                candidate_native_inventory=candidate_native,
                root_proofs=plan["root_proofs"],
            ),
        )
        executable = _blender_executable()
        if executable_hash != sha256_file(executable) or any(
            sha256_file(get_settings().repo_root / path) != digest
            for path, digest in script_hashes.items()
        ):
            raise ValueError("authored split native executable/script changed during preapproval")
        preapproval = publish(
            root,
            f"{base}/preapproval.json",
            AuthoredMaterialIdentitySplitPreapprovalV02(
                **identity,
                plan=plan_ref,
                blender_executable_sha256=sha256_file(executable),
                native_script_sha256=script_hashes,
                source_native_inventory=source_native,
                candidate_native_inventory=candidate_native,
                shadow_validation=runtime.reference(root, f"{base}/shadow/validation.json"),
                shadow_scene_inventory=runtime.reference(
                    root, f"{base}/shadow/scene_inventory.json"
                ),
                shadow_blend=runtime.reference(root, f"{base}/shadow/final.blend"),
                invariant_report=invariant,
            ),
        )
        request_model = (
            AuthoredMaterialIdentitySplitTechnicalApprovalRequestV02
            if plan["profile"] == runtime.DELEGATED_PROFILE
            else AuthoredMaterialIdentitySplitApprovalRequestV02
        )
        request = publish(
            root,
            f"{base}/approval_request.json",
            request_model(
                **identity,
                plan=plan_ref,
                preapproval=preapproval,
                invariant_report=invariant,
                shadow_blend=runtime.reference(root, f"{base}/shadow/final.blend"),
            ),
        )
        runtime.validate_request(root, request, current=True)
        return {
            "status": "eligible_for_delegated_technical_scope_decision"
            if plan["profile"] == runtime.DELEGATED_PROFILE
            else "eligible_for_explicit_user_scope_approval",
            "approval_request": request,
            "preapproval": preapproval,
            "canonical_write_count": 0,
        }
    except Exception as error:
        publish(
            root,
            f"{base}/failure.json",
            {
                "schema_version": "0.2.0",
                **_identity(root, plan["run_id"], plan["profile"]),
                "status": "preapproval_failed",
                "message": str(error).replace(str(root), "<job>")[:1600],
                "approval_created": False,
            },
        )
        raise


def publish_authored_material_identity_split_approval(
    job_root: Path,
    *,
    approval_request_path: str,
    approval: AuthoredMaterialIdentitySplitApprovalV02,
    user_decision: bytes,
    explicit_user_decision_observed: bool,
) -> dict:
    """Publish only a caller-authored specialized decision with its exact original bytes."""
    root = job_root.expanduser().resolve(strict=True)
    if (
        explicit_user_decision_observed is not True
        or not isinstance(user_decision, bytes)
        or not user_decision
    ):
        raise PermissionError(
            "authored split requires observed explicit specialized user decision bytes"
        )
    request_ref = runtime.reference(root, approval_request_path)
    checked = runtime.validate_request(root, request_ref, current=True)
    request = checked["request"]
    AuthoredMaterialIdentitySplitApprovalV02.model_validate_json(approval.model_dump_json())
    if (
        approval.job_id != root.name
        or approval.run_id != request["run_id"]
        or approval.profile != request["profile"]
    ):
        raise ValueError("authored split approval belongs to another job or run")
    raw = approval.model_dump(mode="json")
    for key in ("plan", "preapproval", "invariant_report", "shadow_blend"):
        if raw[key] != request[key]:
            raise ValueError(
                "authored split approval changed the exact requested candidate closure"
            )
    if (
        raw["approval_request"] != request_ref
        or runtime.sha(user_decision) != raw["user_decision_text_sha256"]
    ):
        raise ValueError("authored split approval/decision exact byte binding changed")
    validate_authored_split_plan(root, request["plan"])
    base = runtime.prefix(approval.run_id)
    decision_ref = publish(root, f"{base}/user_decision.txt", user_decision)
    approval_ref = publish(root, f"{base}/approval.json", approval)
    return {"approval": approval_ref, "user_decision": decision_ref, "decision": approval.decision}


def publish_authored_material_identity_split_technical_approval(
    job_root: Path,
    *,
    approval_request_path: str,
    approval: AuthoredMaterialIdentitySplitTechnicalApprovalV02,
    technical_decision: bytes,
    explicit_technical_decision_observed: bool,
) -> dict:
    """Publish an exact assistant technical decision without creating user or AQ approval."""
    root = job_root.expanduser().resolve(strict=True)
    if (
        explicit_technical_decision_observed is not True
        or not isinstance(technical_decision, bytes)
        or not technical_decision
    ):
        raise PermissionError("authored split requires an explicit delegated technical decision")
    request_ref = runtime.reference(root, approval_request_path)
    checked = runtime.validate_request(root, request_ref, current=True)
    request = checked["request"]
    AuthoredMaterialIdentitySplitTechnicalApprovalV02.model_validate_json(
        approval.model_dump_json()
    )
    raw = approval.model_dump(mode="json")
    if (
        approval.job_id != root.name
        or approval.run_id != request["run_id"]
        or request["profile"] != runtime.DELEGATED_PROFILE
    ):
        raise ValueError("authored split technical authority belongs to another job/run/profile")
    if raw["delegation"] != checked["plan"]["delegation"]:
        raise ValueError("authored split technical approval uses another user delegation")
    runtime.validate_delegation(root, raw["delegation"], checked["plan"])
    for key in ("plan", "preapproval", "invariant_report", "shadow_blend"):
        if raw[key] != request[key]:
            raise ValueError(
                "authored split technical approval changed the exact candidate closure"
            )
    if (
        raw["approval_request"] != request_ref
        or runtime.sha(technical_decision) != raw["technical_decision_text_sha256"]
    ):
        raise ValueError("authored split technical decision byte binding changed")
    validate_authored_split_plan(root, request["plan"])
    base = runtime.prefix(approval.run_id)
    decision_ref = publish(root, f"{base}/technical_decision.txt", technical_decision)
    approval_ref = publish(root, f"{base}/technical_approval.json", approval)
    return {
        "technical_approval": approval_ref,
        "technical_decision": decision_ref,
        "decision": approval.decision,
        "is_user_approval": False,
    }
