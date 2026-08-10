"""Exact evidence adapters for Autonomous Quality hard-gate decisions.

The adapter deliberately stays orchestration-neutral.  A caller first adds every path
returned by :func:`discover_hard_gate_evidence_paths` to ``QualityProvenance`` and then
calls :func:`apply_hard_gate_evidence` on the ordinary four-axis report.  Missing
evidence remains unscorable, while supplied-but-invalid or hash-mismatched evidence is
a definitive failure.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from ..analysis.models import ModelingPlan
from ..blender_artifacts import stable_json_digest
from ..blender_scripts.assembly.models import (
    AssemblyCompanionReport,
    AssemblyCompanionRequest,
)
from ..blender_scripts.topology.models import (
    TopologyCheckName,
    TopologyCompanionReport,
    TopologyProfileName,
)
from ..materials.models import MaterialPlan
from ..models import SceneSpec
from ..packaging.models import ExportPackageManifest, RoundTripValidation
from ..texturing.models import TextureManifest
from .models import (
    HardGateResult,
    IntegratedQualityReport,
    QualityProvenance,
    ReentryRecommendation,
)

GateState = Literal["passed", "failed", "unscorable"]


@dataclass(frozen=True, slots=True)
class HardGateEvidencePaths:
    """Name the exact job-contained artifacts consumed by hard-gate evaluation."""

    blend: Path | None = None
    inventory: Path | None = None
    validation: Path | None = None
    modeling_plan: Path | None = None
    scene_spec: Path | None = None
    assembly_companion: Path | None = None
    topology_companion: Path | None = None
    material_plan: Path | None = None
    package_manifest: Path | None = None
    roundtrip_validation: Path | None = None


@dataclass(frozen=True, slots=True)
class HardGateRequirements:
    """Select which stage-specific checks are required without fabricating evidence."""

    require_build: bool = True
    require_assembly: bool = True
    require_topology: bool = True
    require_material_pbr: bool = True
    require_package: bool = False
    topology_profile: TopologyProfileName = "static_prop_closed"
    topology_required_checks: tuple[TopologyCheckName, ...] | None = None
    required_pbr_channels: tuple[str, ...] = (
        "base_color",
        "roughness",
        "metallic",
        "normal",
    )
    allowed_material_providers: tuple[str, ...] = (
        "cbm_autonomy_uniform_pbr",
        "cbm_pillow_procedural",
    )

    def __post_init__(self) -> None:
        """Reject duplicated topology checks and invalid portable PBR requirements."""

        supported = {"base_color", "roughness", "metallic", "normal", "height", "emission"}
        if self.topology_required_checks is not None:
            if not self.topology_required_checks:
                raise ValueError("topology_required_checks cannot be empty when supplied")
            if len(self.topology_required_checks) != len(set(self.topology_required_checks)):
                raise ValueError("topology_required_checks must be unique")
        if not self.required_pbr_channels:
            raise ValueError("required_pbr_channels cannot be empty")
        if len(self.required_pbr_channels) != len(set(self.required_pbr_channels)):
            raise ValueError("required_pbr_channels must be unique")
        unknown = sorted(set(self.required_pbr_channels) - supported)
        if unknown:
            raise ValueError(f"unsupported required PBR channels: {unknown}")
        if not self.allowed_material_providers:
            raise ValueError("allowed_material_providers cannot be empty")
        if len(self.allowed_material_providers) != len(set(self.allowed_material_providers)):
            raise ValueError("allowed_material_providers must be unique")
        if any(not item.strip() for item in self.allowed_material_providers):
            raise ValueError("allowed_material_providers cannot contain blank IDs")


@dataclass(frozen=True, slots=True)
class _EvidenceCheck:
    """Carry one internal status and explanation into a public hard-gate result."""

    status: GateState
    message: str


def _sha256_file(path: Path) -> str:
    """Hash one immutable evidence file in bounded chunks."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contained_path(root: Path, path: Path) -> tuple[Path | None, str | None]:
    """Resolve one path and reject any escape from the job evidence root."""

    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, f"evidence path escapes the job root: {path}"
    return resolved, None


def _job_relative(root: Path, path: Path) -> str:
    """Return one normalized POSIX path relative to the job evidence root."""

    return path.resolve().relative_to(root).as_posix()


def _provenance_hashes(provenance: QualityProvenance) -> dict[str, str]:
    """Index exact Integrated Quality provenance artifacts by contained path."""

    return {item.relative_path: item.sha256 for item in provenance.artifacts}


def _quality_provenance_check(
    root: Path,
    provenance: QualityProvenance,
) -> _EvidenceCheck:
    """Recompute the provenance input digest and every directly bound artifact hash."""

    exact = _provenance_hashes(provenance)
    if provenance.input_sha256 != stable_json_digest(exact):
        return _EvidenceCheck("failed", "Integrated Quality provenance input digest is stale.")
    for artifact in provenance.artifacts:
        check = _nested_artifact_check(
            root,
            artifact.relative_path,
            artifact.sha256,
            label=f"Integrated Quality artifact {artifact.artifact_id}",
        )
        if check.status != "passed":
            return check
    return _EvidenceCheck("passed", "Integrated Quality provenance and direct inputs are current.")


def _bound_file_check(
    root: Path,
    provenance: QualityProvenance,
    path: Path | None,
    *,
    label: str,
) -> tuple[_EvidenceCheck, Path | None]:
    """Verify existence, containment, exact provenance binding, and current SHA-256."""

    if path is None:
        return _EvidenceCheck("unscorable", f"{label} evidence was not supplied."), None
    resolved, error = _contained_path(root, path)
    if error is not None or resolved is None:
        return _EvidenceCheck("failed", error or f"invalid {label} path"), None
    if not resolved.is_file():
        return _EvidenceCheck("failed", f"{label} evidence file is missing."), None
    relative = _job_relative(root, resolved)
    expected = _provenance_hashes(provenance).get(relative)
    if expected is None:
        return (
            _EvidenceCheck(
                "failed",
                f"{label} evidence is not bound into Integrated Quality provenance: {relative}",
            ),
            None,
        )
    actual = _sha256_file(resolved)
    if actual != expected:
        return (
            _EvidenceCheck(
                "failed",
                f"{label} evidence changed after provenance binding: {relative}",
            ),
            None,
        )
    return _EvidenceCheck("passed", f"{label} evidence is current and hash-bound."), resolved


def _load_bound_json(
    root: Path,
    provenance: QualityProvenance,
    path: Path | None,
    *,
    label: str,
) -> tuple[_EvidenceCheck, dict[str, Any] | None, Path | None]:
    """Load one exact JSON object only after its provenance binding succeeds."""

    check, resolved = _bound_file_check(root, provenance, path, label=label)
    if check.status != "passed" or resolved is None:
        return check, None, None
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _EvidenceCheck("failed", f"{label} JSON is invalid: {exc}"), None, None
    if not isinstance(payload, dict):
        return _EvidenceCheck("failed", f"{label} JSON root must be an object."), None, None
    return check, payload, resolved


def _nested_artifact_check(
    root: Path,
    relative_path: str,
    expected_sha256: str,
    *,
    label: str,
) -> _EvidenceCheck:
    """Re-hash one artifact nested beneath a strict companion or package contract."""

    candidate = PurePosixPath(relative_path)
    if (
        candidate.is_absolute()
        or "\\" in relative_path
        or ":" in relative_path
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        return _EvidenceCheck("failed", f"{label} declares an unsafe relative path.")
    path, error = _contained_path(root, root / Path(*candidate.parts))
    if error is not None or path is None or not path.is_file():
        return _EvidenceCheck("failed", f"{label} dependency is missing or escapes the job.")
    if _sha256_file(path) != expected_sha256:
        return _EvidenceCheck("failed", f"{label} dependency SHA-256 does not match.")
    return _EvidenceCheck("passed", f"{label} dependency is current.")


def _model_check(
    model_type: type[Any],
    payload: dict[str, Any],
    label: str,
) -> tuple[Any | None, str | None]:
    """Parse one strict existing contract and return a concise deterministic error."""

    try:
        return model_type.model_validate_json(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        ), None
    except Exception as exc:  # Pydantic exposes multiple version-specific exception classes.
        return None, f"{label} contract is invalid: {exc}"


def _build_check(
    root: Path,
    provenance: QualityProvenance,
    path: Path | None,
) -> _EvidenceCheck:
    """Require one non-empty, exact Blender build artifact."""

    check, resolved = _bound_file_check(root, provenance, path, label="Blender build")
    if check.status != "passed" or resolved is None:
        return check
    if resolved.stat().st_size <= 0:
        return _EvidenceCheck("failed", "Blender build artifact is empty.")
    return _EvidenceCheck("passed", "Blender build exists, is non-empty, and is hash-bound.")


def _inventory_check(
    root: Path,
    provenance: QualityProvenance,
    path: Path | None,
    *,
    job_id: str,
) -> tuple[_EvidenceCheck, dict[str, Any] | None]:
    """Validate the deterministic inspect report shape and job identity."""

    check, payload, _resolved = _load_bound_json(root, provenance, path, label="scene inventory")
    if check.status != "passed" or payload is None:
        return check, None
    objects = payload.get("objects")
    families = payload.get("families")
    count = payload.get("object_count")
    if payload.get("job_id") != job_id:
        return _EvidenceCheck("failed", "Scene inventory belongs to another job."), None
    if not isinstance(objects, list) or not isinstance(families, list):
        return _EvidenceCheck("failed", "Scene inventory lacks object or family arrays."), None
    if not isinstance(count, int) or count != len(objects):
        return _EvidenceCheck("failed", "Scene inventory object_count is inconsistent."), None
    return _EvidenceCheck("passed", "Scene inspect evidence is structurally valid."), payload


def _validation_check(
    root: Path,
    provenance: QualityProvenance,
    path: Path | None,
) -> tuple[_EvidenceCheck, dict[str, Any] | None]:
    """Require the exact Blender validation report to declare ok=true."""

    check, payload, _resolved = _load_bound_json(root, provenance, path, label="scene validation")
    if check.status != "passed" or payload is None:
        return check, None
    if payload.get("ok") is not True:
        errors = payload.get("errors")
        return (
            _EvidenceCheck("failed", f"Scene validation did not pass: {errors!r}"),
            payload,
        )
    return _EvidenceCheck("passed", "Scene validation reports ok=true."), payload


def _load_modeling_and_scene(
    root: Path,
    provenance: QualityProvenance,
    paths: HardGateEvidencePaths,
    *,
    job_id: str,
) -> tuple[_EvidenceCheck, ModelingPlan | None, SceneSpec | None]:
    """Load exact authored modeling and SceneSpec contracts for semantic gates."""

    plan_check, plan_payload, _ = _load_bound_json(
        root, provenance, paths.modeling_plan, label="modeling plan"
    )
    scene_check, scene_payload, _ = _load_bound_json(
        root, provenance, paths.scene_spec, label="SceneSpec"
    )
    statuses = {plan_check.status, scene_check.status}
    if "failed" in statuses:
        message = "; ".join(
            item.message for item in (plan_check, scene_check) if item.status == "failed"
        )
        return _EvidenceCheck("failed", message), None, None
    if "unscorable" in statuses or plan_payload is None or scene_payload is None:
        return (
            _EvidenceCheck("unscorable", "ModelingPlan or SceneSpec evidence is unavailable."),
            None,
            None,
        )
    plan, plan_error = _model_check(ModelingPlan, plan_payload, "ModelingPlan")
    scene, scene_error = _model_check(SceneSpec, scene_payload, "SceneSpec")
    if plan_error or scene_error or plan is None or scene is None:
        return _EvidenceCheck("failed", plan_error or scene_error or "invalid source"), None, None
    if plan.job_id != job_id or scene.job_id != job_id:
        return (
            _EvidenceCheck("failed", "ModelingPlan or SceneSpec belongs to another job."),
            None,
            None,
        )
    if plan.stage != "authored":
        return (
            _EvidenceCheck("failed", "Required semantics need an authored ModelingPlan."),
            None,
            None,
        )
    return _EvidenceCheck("passed", "Authored ModelingPlan and SceneSpec are current."), plan, scene


def _required_semantic_check(
    source_check: _EvidenceCheck,
    plan: ModelingPlan | None,
    scene: SceneSpec | None,
    inventory: dict[str, Any] | None,
) -> _EvidenceCheck:
    """Require every planned semantic in SceneSpec and evaluated inventory evidence."""

    if source_check.status != "passed" or plan is None or scene is None:
        return source_check
    if inventory is None:
        return _EvidenceCheck("unscorable", "Scene inventory is unavailable for semantic checks.")
    required = {item.id for item in plan.objects}
    scene_ids = {item.id for item in scene.objects}
    inventory_ids = {
        str(item.get("cbm_id"))
        for item in inventory.get("families", [])
        if isinstance(item, dict) and item.get("cbm_id")
    }
    missing_scene = sorted(required - scene_ids)
    missing_inventory = sorted(required - inventory_ids)
    if missing_scene or missing_inventory:
        return _EvidenceCheck(
            "failed",
            "Required semantics are missing: "
            f"SceneSpec={missing_scene}, inventory={missing_inventory}.",
        )
    return _EvidenceCheck(
        "passed", f"All {len(required)} authored semantic IDs exist in source and inventory."
    )


def _non_finite_paths(value: Any, prefix: str = "$") -> list[str]:
    """Return bounded JSON paths containing non-finite floating-point values."""

    findings: list[str] = []
    if isinstance(value, float) and not math.isfinite(value):
        return [prefix]
    if isinstance(value, dict):
        for key, child in value.items():
            findings.extend(_non_finite_paths(child, f"{prefix}.{key}"))
            if len(findings) >= 32:
                break
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_non_finite_paths(child, f"{prefix}[{index}]"))
            if len(findings) >= 32:
                break
    return findings[:32]


def _finite_transform_check(
    source_check: _EvidenceCheck,
    scene: SceneSpec | None,
    inventory: dict[str, Any] | None,
) -> _EvidenceCheck:
    """Reject non-finite canonical or evaluated geometry/transform observations."""

    if source_check.status != "passed" or scene is None:
        return source_check
    if inventory is None:
        return _EvidenceCheck("unscorable", "Scene inventory is unavailable for finite checks.")
    scene_bad = _non_finite_paths(scene.model_dump(mode="python"), "SceneSpec")
    inventory_bad = _non_finite_paths(inventory, "inventory")
    if scene_bad or inventory_bad:
        return _EvidenceCheck(
            "failed",
            f"Non-finite values were found: {(scene_bad + inventory_bad)[:16]}.",
        )
    return _EvidenceCheck("passed", "Canonical and evaluated numeric evidence is finite.")


def _verify_assembly_provenance(
    root: Path,
    report: AssemblyCompanionReport,
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
) -> _EvidenceCheck:
    """Re-hash companion inputs and its exact request before trusting findings."""

    identity = (
        report.provenance.job_id,
        report.provenance.workflow_id,
        report.provenance.dispatch_id,
    )
    if identity != (job_id, workflow_id, dispatch_id):
        return _EvidenceCheck("failed", "Assembly companion belongs to another session.")
    for index, artifact in enumerate(report.provenance.inputs):
        check = _nested_artifact_check(
            root, artifact.path, artifact.sha256, label=f"assembly input {index}"
        )
        if check.status != "passed":
            return check
    request_check = _nested_artifact_check(
        root, report.request.path, report.request.sha256, label="assembly request"
    )
    if request_check.status != "passed":
        return request_check
    request_path = root / Path(*PurePosixPath(report.request.path).parts)
    try:
        request = AssemblyCompanionRequest.model_validate_json(
            request_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        return _EvidenceCheck("failed", f"assembly request contract is invalid: {exc}")
    for index, mesh in enumerate(request.meshes):
        check = _nested_artifact_check(
            root,
            mesh.snapshot.path,
            mesh.snapshot.sha256,
            label=f"assembly mesh snapshot {index}",
        )
        if check.status != "passed":
            return check
    return _EvidenceCheck("passed", "Assembly provenance and mesh snapshots are current.")


def _assembly_check(
    root: Path,
    provenance: QualityProvenance,
    path: Path | None,
    *,
    plan: ModelingPlan | None,
) -> _EvidenceCheck:
    """Evaluate only declared required relations as blocking assembly evidence."""

    if plan is None:
        return _EvidenceCheck("unscorable", "ModelingPlan is unavailable for assembly policy.")
    required_relation_ids = {item.id for item in plan.assembly_relationships if item.required}
    requires_companion = bool(required_relation_ids) or any(
        item.required_assembly_checks for item in plan.objects
    )
    if not requires_companion:
        return _EvidenceCheck("passed", "No required assembly relationship is declared.")
    check, payload, _ = _load_bound_json(root, provenance, path, label="assembly companion")
    if check.status != "passed" or payload is None:
        return check
    report, error = _model_check(AssemblyCompanionReport, payload, "assembly companion")
    if error or report is None:
        return _EvidenceCheck("failed", error or "invalid assembly companion")
    nested = _verify_assembly_provenance(
        root,
        report,
        job_id=provenance.job_id,
        workflow_id=provenance.workflow_id,
        dispatch_id=provenance.dispatch_id,
    )
    if nested.status != "passed":
        return nested
    request_path = root / Path(*PurePosixPath(report.request.path).parts)
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request, request_error = _model_check(
        AssemblyCompanionRequest, request_payload, "assembly request"
    )
    if request_error or request is None:
        return _EvidenceCheck("failed", request_error or "invalid assembly request")
    requested_ids = {item.relation_id for item in request.semantic_relations if item.required}
    missing_requests = sorted(required_relation_ids - requested_ids)
    semantic_findings = {
        item.relation_id: item
        for item in report.findings
        if item.phase == "semantic" and item.relation_id is not None
    }
    missing_findings = sorted(required_relation_ids - set(semantic_findings))
    if missing_requests or missing_findings:
        return _EvidenceCheck(
            "failed",
            "Required assembly evidence is incomplete: "
            f"request={missing_requests}, findings={missing_findings}.",
        )
    if report.hard_failures:
        return _EvidenceCheck(
            "failed", f"Assembly companion contains {report.hard_failures} hard failure(s)."
        )
    required_unscorable = sorted(
        relation_id
        for relation_id in required_relation_ids
        if semantic_findings[relation_id].severity == "unscorable"
    )
    if report.status == "unscorable" or required_unscorable:
        return _EvidenceCheck(
            "unscorable",
            f"Required assembly evidence is unscorable: {required_unscorable}.",
        )
    return _EvidenceCheck("passed", "All declared required assembly relations are scorable.")


def _topology_check(
    root: Path,
    provenance: QualityProvenance,
    path: Path | None,
    *,
    expected_profile: TopologyProfileName,
    required_checks: tuple[TopologyCheckName, ...] | None = None,
) -> _EvidenceCheck:
    """Require one exact profile, optionally limited to stage-relevant topology checks."""

    check, payload, _ = _load_bound_json(root, provenance, path, label="topology companion")
    if check.status != "passed" or payload is None:
        return check
    report, error = _model_check(TopologyCompanionReport, payload, "topology companion")
    if error or report is None:
        return _EvidenceCheck("failed", error or "invalid topology companion")
    identity = (
        report.provenance.job_id,
        report.provenance.workflow_id,
        report.provenance.dispatch_id,
    )
    if identity != (provenance.job_id, provenance.workflow_id, provenance.dispatch_id):
        return _EvidenceCheck("failed", "Topology companion belongs to another session.")
    if report.profile.name != expected_profile:
        return _EvidenceCheck(
            "failed",
            f"Topology profile mismatch: expected={expected_profile} actual={report.profile.name}.",
        )
    for index, artifact in enumerate(report.provenance.inputs):
        nested = _nested_artifact_check(
            root, artifact.path, artifact.sha256, label=f"topology input {index}"
        )
        if nested.status != "passed":
            return nested
    seen_result_evidence: set[tuple[str, str]] = set()
    for result in report.results:
        if result.evidence is None:
            continue
        key = (result.evidence.path, result.evidence.sha256)
        if key in seen_result_evidence:
            continue
        seen_result_evidence.add(key)
        nested = _nested_artifact_check(
            root,
            result.evidence.path,
            result.evidence.sha256,
            label=f"topology result {result.check}",
        )
        if nested.status != "passed":
            return nested
    selected = [
        item
        for item in report.results
        if required_checks is None or item.check in set(required_checks)
    ]
    if required_checks is not None:
        missing = sorted(set(required_checks) - {item.check for item in selected})
        if missing:
            return _EvidenceCheck(
                "failed", f"Topology profile omits required stage check(s): {missing}."
            )
    hard_failures = [item.check for item in selected if item.outcome == "hard_failure"]
    if hard_failures:
        return _EvidenceCheck(
            "failed", f"Topology profile contains hard failure(s): {hard_failures}."
        )
    hard_unscorable = [
        item.check
        for item in selected
        if item.outcome == "unscorable" and item.profile_failure_severity == "hard_failure"
    ]
    if hard_unscorable:
        return _EvidenceCheck(
            "unscorable",
            f"Topology profile has unavailable hard check(s): {hard_unscorable}.",
        )
    warning_unscorable = sum(
        item.outcome == "unscorable" and item.profile_failure_severity == "warning"
        for item in selected
    )
    return _EvidenceCheck(
        "passed",
        (
            f"Topology profile {expected_profile} has no hard failure; "
            f"warning-only unavailable checks={warning_unscorable}."
        ),
    )


def _resolve_plan_dependency(root: Path, value: str) -> tuple[Path | None, str | None]:
    """Resolve one job-relative material dependency without accepting path traversal."""

    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or "\\" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        return None, "material dependency path is not a safe job-relative POSIX path"
    return _contained_path(root, root / Path(*candidate.parts))


def _material_checks(
    root: Path,
    provenance: QualityProvenance,
    path: Path | None,
    *,
    scene: SceneSpec | None,
    required_channels: tuple[str, ...],
    allowed_providers: tuple[str, ...],
) -> tuple[_EvidenceCheck, _EvidenceCheck]:
    """Verify authored UV/PBR dependencies and exact local generation provenance."""

    check, payload, _ = _load_bound_json(root, provenance, path, label="material plan")
    if check.status != "passed" or payload is None:
        return check, check
    plan, error = _model_check(MaterialPlan, payload, "MaterialPlan")
    if error or plan is None:
        failed = _EvidenceCheck("failed", error or "invalid MaterialPlan")
        return failed, failed
    if plan.job_id != provenance.job_id or plan.stage != "authored":
        failed = _EvidenceCheck("failed", "MaterialPlan is not the authored plan for this job.")
        return failed, failed
    if scene is None:
        unavailable = _EvidenceCheck("unscorable", "SceneSpec is unavailable for material IDs.")
        return unavailable, unavailable
    planned = {item.material_id: item for item in plan.materials}
    missing_materials = sorted({item.id for item in scene.materials} - set(planned))
    if missing_materials:
        failed = _EvidenceCheck(
            "failed", f"Authored MaterialPlan omits SceneSpec materials: {missing_materials}."
        )
        return failed, failed
    dependency_errors: list[str] = []
    provenance_errors: list[str] = []
    for material_id, item in sorted(planned.items()):
        if item.texture_strategy not in {"image", "hybrid"} or not item.texture_manifest:
            dependency_errors.append(f"{material_id}: image-backed TextureManifest is required")
            continue
        manifest_path, path_error = _resolve_plan_dependency(root, item.texture_manifest)
        if path_error or manifest_path is None or not manifest_path.is_file():
            dependency_errors.append(f"{material_id}: TextureManifest is missing or unsafe")
            continue
        relative = _job_relative(root, manifest_path)
        expected_manifest_sha = _provenance_hashes(provenance).get(relative)
        if expected_manifest_sha is None or _sha256_file(manifest_path) != expected_manifest_sha:
            provenance_errors.append(f"{material_id}: TextureManifest is not exact-bound")
            continue
        try:
            manifest = TextureManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            dependency_errors.append(f"{material_id}: invalid TextureManifest ({exc})")
            continue
        if manifest.material_id != material_id:
            dependency_errors.append(f"{material_id}: TextureManifest material ID mismatch")
        if (
            item.mapping.mode != "uv"
            or item.mapping.uv_set != "UVMap"
            or manifest.uv_set != "UVMap"
        ):
            dependency_errors.append(f"{material_id}: portable image PBR requires UVMap")
        missing_channels = sorted(set(required_channels) - set(manifest.channels))
        if missing_channels:
            dependency_errors.append(
                f"{material_id}: missing required PBR channels {missing_channels}"
            )
        if manifest.provenance is None or not manifest.provenance.provider.strip():
            provenance_errors.append(f"{material_id}: generation provenance is absent")
        elif manifest.provenance.provider not in set(allowed_providers):
            provenance_errors.append(
                f"{material_id}: provider {manifest.provenance.provider!r} is not allowed"
            )
        elif not (manifest.provenance.provider_version or "").strip():
            provenance_errors.append(f"{material_id}: provider version is absent")
        for channel_name in required_channels:
            channel = manifest.channels.get(channel_name)  # type: ignore[arg-type]
            if channel is None:
                continue
            if channel.source != "image" or not channel.path:
                dependency_errors.append(f"{material_id}.{channel_name}: image dependency required")
                continue
            channel_path, channel_error = _contained_path(root, manifest_path.parent / channel.path)
            if channel_error or channel_path is None or not channel_path.is_file():
                dependency_errors.append(f"{material_id}.{channel_name}: image file is missing")
                continue
            actual_sha = _sha256_file(channel_path)
            declared_sha = (
                manifest.provenance.generated_sha256.get(channel_name)
                if manifest.provenance is not None
                else None
            )
            if declared_sha is None or declared_sha != actual_sha:
                provenance_errors.append(
                    f"{material_id}.{channel_name}: generated SHA-256 is absent or stale"
                )
    dependency = (
        _EvidenceCheck("failed", "; ".join(dependency_errors[:12]))
        if dependency_errors
        else _EvidenceCheck("passed", "All required UV/PBR dependencies are present.")
    )
    provenance_check = (
        _EvidenceCheck("failed", "; ".join(provenance_errors[:12]))
        if provenance_errors
        else _EvidenceCheck("passed", "All PBR manifests and image channels are hash-bound.")
    )
    return dependency, provenance_check


def _package_checks(
    root: Path,
    provenance: QualityProvenance,
    package_path: Path | None,
    roundtrip_path: Path | None,
) -> tuple[_EvidenceCheck, _EvidenceCheck]:
    """Verify immutable package dependencies and exact clean-import round-trip evidence."""

    package_check, package_payload, package_resolved = _load_bound_json(
        root, provenance, package_path, label="package manifest"
    )
    roundtrip_check, roundtrip_payload, _ = _load_bound_json(
        root, provenance, roundtrip_path, label="clean-import round trip"
    )
    if package_check.status != "passed" or package_payload is None or package_resolved is None:
        return package_check, (
            roundtrip_check
            if roundtrip_check.status == "failed"
            else _EvidenceCheck("unscorable", "Package evidence is unavailable for round trip.")
        )
    package, package_error = _model_check(
        ExportPackageManifest, package_payload, "package manifest"
    )
    if package_error or package is None:
        failed = _EvidenceCheck("failed", package_error or "invalid package manifest")
        return failed, failed
    if package.job_id != provenance.job_id or package.status != "complete":
        failed = _EvidenceCheck("failed", "Package is not a complete artifact for this job.")
        return failed, failed
    nested_artifacts = [
        *package.source.artifacts(),
        package.optimization_plan,
        *([package.material_conversion] if package.material_conversion is not None else []),
        *package.source_manifests,
    ]
    for index, artifact in enumerate(nested_artifacts):
        nested = _nested_artifact_check(
            root, artifact.path, artifact.sha256, label=f"package metadata {index}"
        )
        if nested.status != "passed":
            return nested, _EvidenceCheck("unscorable", "Package dependencies did not pass.")
    for index, item in enumerate(package.files):
        nested = _nested_artifact_check(root, item.path, item.sha256, label=f"package file {index}")
        if nested.status != "passed":
            return nested, _EvidenceCheck("unscorable", "Package dependencies did not pass.")
        resolved = root / Path(*PurePosixPath(item.path).parts)
        if resolved.stat().st_size != item.byte_size:
            failed = _EvidenceCheck("failed", f"Package byte size changed: {item.path}")
            return failed, _EvidenceCheck("unscorable", "Package dependencies did not pass.")
    dependencies = _EvidenceCheck(
        "passed", "Package manifest and every declared dependency are exact and current."
    )
    if roundtrip_check.status != "passed" or roundtrip_payload is None:
        return dependencies, roundtrip_check
    roundtrip, error = _model_check(
        RoundTripValidation, roundtrip_payload, "clean-import round trip"
    )
    if error or roundtrip is None:
        return dependencies, _EvidenceCheck("failed", error or "invalid round trip")
    manifest_relative = _job_relative(root, package_resolved)
    if (
        roundtrip.job_id != provenance.job_id
        or roundtrip.package_id != package.package_id
        or roundtrip.run_id != package.run_id
        or roundtrip.profile_id != package.profile_id
        or roundtrip.package_manifest.path != manifest_relative
        or roundtrip.package_manifest.sha256 != _sha256_file(package_resolved)
    ):
        return dependencies, _EvidenceCheck(
            "failed", "Round trip is not bound to the exact current package manifest."
        )
    if not roundtrip.ok or roundtrip.status != "passed":
        return dependencies, _EvidenceCheck("failed", "Clean-import round trip did not pass.")
    imported = _nested_artifact_check(
        root,
        roundtrip.imported_inventory.path,
        roundtrip.imported_inventory.sha256,
        label="round-trip imported inventory",
    )
    if imported.status != "passed":
        return dependencies, imported
    return dependencies, _EvidenceCheck("passed", "Exact clean-import round trip passed.")


def _result(
    gate_id: str,
    axis: str,
    check: _EvidenceCheck,
    *,
    required: bool,
    evidence_id: str,
) -> HardGateResult:
    """Convert one internal check into the existing strict hard-gate contract."""

    return HardGateResult(
        gate_id=gate_id,
        axis=axis,  # type: ignore[arg-type]
        status=check.status,
        required=required,
        blocking=required and check.status == "failed",
        evidence_ids=[evidence_id],
        message=check.message,
    )


def discover_hard_gate_evidence_paths(
    job_root: Path,
    paths: HardGateEvidencePaths,
) -> tuple[Path, ...]:
    """Discover direct files that a caller must include in Integrated Quality provenance."""

    root = job_root.resolve()
    direct = [
        paths.blend,
        paths.inventory,
        paths.validation,
        paths.modeling_plan,
        paths.scene_spec,
        paths.assembly_companion,
        paths.topology_companion,
        paths.material_plan,
        paths.package_manifest,
        paths.roundtrip_validation,
    ]
    if paths.material_plan is not None and paths.material_plan.is_file():
        try:
            plan = MaterialPlan.model_validate_json(paths.material_plan.read_text(encoding="utf-8"))
        except Exception:
            plan = None
        if plan is not None:
            for item in plan.materials:
                if item.texture_manifest:
                    manifest, _error = _resolve_plan_dependency(root, item.texture_manifest)
                    direct.append(manifest)
    unique: dict[str, Path] = {}
    for item in direct:
        if item is None:
            continue
        resolved, error = _contained_path(root, item)
        if error is None and resolved is not None and resolved.is_file():
            unique[_job_relative(root, resolved)] = resolved
    return tuple(unique[key] for key in sorted(unique))


def evaluate_hard_gate_evidence(
    job_root: Path,
    *,
    provenance: QualityProvenance,
    paths: HardGateEvidencePaths,
    requirements: HardGateRequirements | None = None,
    structural_evidence_id: str = "structural-current",
    material_evidence_id: str = "material-current",
    production_evidence_id: str = "production-current",
    topology_evidence_id: str | None = None,
) -> list[HardGateResult]:
    """Evaluate exact AQ gates with an optional stage-owned topology evidence channel."""

    root = job_root.resolve()
    policy = requirements or HardGateRequirements()
    resolved_topology_evidence_id = topology_evidence_id or production_evidence_id
    direct_provenance = _quality_provenance_check(root, provenance)
    build = _build_check(root, provenance, paths.blend)
    inspect, inventory = _inventory_check(
        root, provenance, paths.inventory, job_id=provenance.job_id
    )
    validate, _validation = _validation_check(root, provenance, paths.validation)
    source, plan, scene = _load_modeling_and_scene(
        root, provenance, paths, job_id=provenance.job_id
    )
    semantics = _required_semantic_check(source, plan, scene, inventory)
    finite = _finite_transform_check(source, scene, inventory)
    assembly = _assembly_check(root, provenance, paths.assembly_companion, plan=plan)
    topology = _topology_check(
        root,
        provenance,
        paths.topology_companion,
        expected_profile=policy.topology_profile,
        required_checks=policy.topology_required_checks,
    )
    material, material_provenance = _material_checks(
        root,
        provenance,
        paths.material_plan,
        scene=scene,
        required_channels=policy.required_pbr_channels,
        allowed_providers=policy.allowed_material_providers,
    )
    package, roundtrip = _package_checks(
        root, provenance, paths.package_manifest, paths.roundtrip_validation
    )
    return [
        _result(
            "gate.aq.evidence_binding",
            "structural_integrity",
            direct_provenance,
            required=any(
                (
                    policy.require_build,
                    policy.require_assembly,
                    policy.require_topology,
                    policy.require_material_pbr,
                    policy.require_package,
                )
            ),
            evidence_id=structural_evidence_id,
        ),
        _result(
            "gate.aq.build",
            "structural_integrity",
            build,
            required=policy.require_build,
            evidence_id=structural_evidence_id,
        ),
        _result(
            "gate.aq.inspect",
            "structural_integrity",
            inspect,
            required=policy.require_build,
            evidence_id=structural_evidence_id,
        ),
        _result(
            "gate.aq.validate",
            "structural_integrity",
            validate,
            required=policy.require_build,
            evidence_id=structural_evidence_id,
        ),
        _result(
            "gate.aq.required_semantics",
            "structural_integrity",
            semantics,
            required=policy.require_build,
            evidence_id=structural_evidence_id,
        ),
        _result(
            "gate.aq.finite_transforms",
            "structural_integrity",
            finite,
            required=policy.require_build,
            evidence_id=structural_evidence_id,
        ),
        _result(
            "gate.aq.required_assembly",
            "structural_integrity",
            assembly,
            required=policy.require_assembly,
            evidence_id=structural_evidence_id,
        ),
        _result(
            "gate.aq.topology_profile",
            "production_readiness",
            topology,
            required=policy.require_topology,
            evidence_id=resolved_topology_evidence_id,
        ),
        _result(
            "gate.aq.uv_pbr_dependencies",
            "material_fidelity",
            material,
            required=policy.require_material_pbr,
            evidence_id=material_evidence_id,
        ),
        _result(
            "gate.aq.provenance",
            "material_fidelity",
            material_provenance,
            required=policy.require_material_pbr,
            evidence_id=material_evidence_id,
        ),
        _result(
            "gate.aq.package_dependencies",
            "production_readiness",
            package,
            required=policy.require_package,
            evidence_id=production_evidence_id,
        ),
        _result(
            "gate.aq.clean_import_roundtrip",
            "production_readiness",
            roundtrip,
            required=policy.require_package,
            evidence_id=production_evidence_id,
        ),
    ]


def _gate_reentry(gates: list[HardGateResult]) -> list[ReentryRecommendation]:
    """Translate new non-passing hard gates to the earliest responsible phase."""

    stage_by_axis = {
        "structural_integrity": "v0.4",
        "material_fidelity": "v0.5",
        "production_readiness": "v0.7",
    }
    recommendations: list[ReentryRecommendation] = []
    for gate in gates:
        if gate.status == "passed":
            continue
        recommendations.append(
            ReentryRecommendation(
                recommendation_id=f"reentry.{gate.gate_id}",
                stage=stage_by_axis[gate.axis],  # type: ignore[arg-type]
                axis=gate.axis,
                reason_codes=[gate.gate_id],
                message=(
                    f"Return to {stage_by_axis[gate.axis]} because {gate.gate_id} is "
                    f"{gate.status}; do not mutate canonical evidence from this finding."
                ),
            )
        )
    return recommendations


def apply_hard_gate_results(
    report: IntegratedQualityReport,
    results: list[HardGateResult],
) -> IntegratedQualityReport:
    """Merge exact AQ gates and recompute outcome through strict report validation."""

    existing = {item.gate_id: item for item in report.hard_gates}
    for result in results:
        existing[result.gate_id] = result
    gates = [existing[key] for key in sorted(existing)]
    failed_required = any(item.blocking for item in gates)
    unscorable_required = any(item.required and item.status == "unscorable" for item in gates)
    required_axes = [item for item in report.axes if item.required]
    axis_unscorable = any(item.status == "unscorable" for item in required_axes)
    axis_nonpassing = any(item.status in {"warning", "failed"} for item in required_axes)
    outcome = (
        "blocked"
        if failed_required
        else "unscorable"
        if unscorable_required or axis_unscorable
        else "needs_revision"
        if axis_nonpassing
        else "passed"
    )
    current_reentry = {item.recommendation_id: item for item in report.reentry}
    for item in _gate_reentry(results):
        current_reentry[item.recommendation_id] = item
    payload = report.model_dump(mode="python")
    payload.update(
        {
            "hard_gates": [item.model_dump(mode="python") for item in gates],
            "outcome": outcome,
            "quality_accepted": outcome == "passed",
            "blocking_reasons": [
                f"{item.gate_id}: {item.message}" for item in gates if item.blocking
            ],
            "reentry": [
                current_reentry[key].model_dump(mode="python")
                for key in sorted(current_reentry)
            ],
        }
    )
    return IntegratedQualityReport.model_validate(payload)


def apply_hard_gate_evidence(
    report: IntegratedQualityReport,
    *,
    job_root: Path,
    paths: HardGateEvidencePaths,
    requirements: HardGateRequirements | None = None,
    structural_evidence_id: str = "structural-current",
    material_evidence_id: str = "material-current",
    production_evidence_id: str = "production-current",
    topology_evidence_id: str | None = None,
) -> IntegratedQualityReport:
    """Evaluate exact gates while preserving an optional stage-specific topology binding."""

    known_evidence = {item.evidence_id for item in report.evidence_availability}
    requested_evidence = {
        structural_evidence_id,
        material_evidence_id,
        production_evidence_id,
        topology_evidence_id or production_evidence_id,
    }
    if not requested_evidence.issubset(known_evidence):
        raise ValueError("hard-gate evidence IDs must exist in the IntegratedQuality report")
    results = evaluate_hard_gate_evidence(
        job_root,
        provenance=report.provenance,
        paths=paths,
        requirements=requirements,
        structural_evidence_id=structural_evidence_id,
        material_evidence_id=material_evidence_id,
        production_evidence_id=production_evidence_id,
        topology_evidence_id=topology_evidence_id,
    )
    return apply_hard_gate_results(report, results)
