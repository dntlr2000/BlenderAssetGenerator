from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..blender_artifacts import write_json_atomic
from ..config import get_settings
from ..handoff import validate_destination_handoff
from ..qa.diagnostic_models import (
    QADiagnosticBundleManifest,
    QADiagnosticRequest,
)
from ..qa.diagnostic_service import validate_qa_diagnostic_bundle
from ..workspace import job_dir, load_job, resolve_metadata_path, sha256_file
from .models import HumanReportManifest, ReportScope, ReportSource
from .pdf_renderer import render_job_pdf

REPORT_SCOPES = {"build", "material", "qa", "export", "full"}


def _load_json(path: Path) -> dict[str, Any] | None:
    """Load one JSON object when it exists and fail clearly for malformed content."""

    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Report source must contain a JSON object: {path}")
    return payload


def _job_relative(root: Path, path: Path) -> str:
    """Return a redacted job-relative source path for manifests and PDF appendices."""

    return path.resolve().relative_to(root.resolve()).as_posix()


def _safe_job_file(root: Path, path: Path, warnings: list[str]) -> Path | None:
    """Accept an existing file only when it remains inside the selected job directory."""

    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        warnings.append(f"Skipped an external report asset: {path.name}")
        return None
    if not resolved.is_file():
        warnings.append(f"Missing optional report asset: {path.name}")
        return None
    return resolved


def _source_record(root: Path, kind: str, path: Path) -> ReportSource:
    """Hash one source file without exposing its absolute local filesystem path."""

    return ReportSource(
        kind=kind,
        path=_job_relative(root, path),
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
    )


def _source_fingerprint(sources: list[ReportSource]) -> str:
    """Create a deterministic digest over the ordered report evidence list."""

    canonical = json.dumps(
        [source.model_dump(mode="json") for source in sources],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _recorded_hash_is_current(
    path: Path,
    expected: Any,
    label: str,
    warnings: list[str],
) -> bool:
    """Reject stale visual evidence when its source manifest records a different hash."""

    if not isinstance(expected, str) or len(expected) != 64:
        warnings.append(f"Report evidence has no valid recorded hash: {label}")
        return True
    if sha256_file(path) == expected:
        return True
    warnings.append(f"Skipped stale report evidence whose hash changed: {label}")
    return False


def _resolve_reference(metadata: dict[str, Any], root: Path, warnings: list[str]) -> Path | None:
    """Resolve the immutable primary reference while enforcing job-local image access."""

    value = metadata.get("reference_path")
    if not isinstance(value, str) or not value:
        warnings.append("Job metadata does not identify a primary reference image.")
        return None
    reference = _safe_job_file(root, resolve_metadata_path(value), warnings)
    if reference is None:
        return None
    expected = metadata.get("reference_sha256")
    if expected and not _recorded_hash_is_current(reference, expected, "reference", warnings):
        return None
    return reference


def _resolve_qa_run(
    root: Path,
    requested_run_id: str | None,
    warnings: list[str],
) -> tuple[str | None, Path | None]:
    """Resolve an explicit QA run or the immutable run referenced by qa/latest.json."""

    run_id = requested_run_id
    if run_id in {None, "latest"}:
        latest = _load_json(root / "qa" / "latest.json")
        run_id = str(latest.get("run_id", "")) if latest else ""
    if not run_id:
        warnings.append("No visual QA run is available for this job.")
        return None, None
    candidate = root / "qa" / "runs" / run_id
    try:
        candidate.resolve().relative_to((root / "qa" / "runs").resolve())
    except ValueError as exc:
        raise ValueError(f"Invalid QA run ID: {run_id}") from exc
    if not candidate.is_dir():
        warnings.append(f"QA run is missing: {run_id}")
        return run_id, None
    return run_id, candidate


def _resolve_interior_qa_run(
    root: Path,
    requested_run_id: str | None,
    warnings: list[str],
) -> tuple[str | None, Path | None]:
    """Resolve one explicit interior QA run or its hash-bound latest pointer."""

    runs_root = root / "qa" / "interior" / "runs"
    run_id = requested_run_id
    if run_id in {None, "latest"}:
        latest = _load_json(root / "qa" / "interior" / "latest.json")
        run_id = str(latest.get("run_id", "")) if latest else ""
    if not run_id:
        warnings.append("No multi-view interior QA run is available for this job.")
        return None, None
    candidate = runs_root / run_id
    try:
        candidate.resolve().relative_to(runs_root.resolve())
    except ValueError as exc:
        raise ValueError(f"Invalid interior QA run ID: {run_id}") from exc
    if candidate.resolve().parent != runs_root.resolve():
        raise ValueError(f"Invalid interior QA run ID: {run_id}")
    if not candidate.is_dir():
        warnings.append(f"Interior QA run is missing: {run_id}")
        return run_id, None
    return run_id, candidate


def _resolve_optimization_run(
    root: Path,
    requested_run_id: str | None,
    warnings: list[str],
) -> tuple[str | None, Path | None]:
    """Resolve an explicit V0.7 run or select the latest immutable run directory."""

    runs_root = root / "optimization" / "runs"
    run_id = requested_run_id
    if run_id in {None, "latest"}:
        latest = _load_json(root / "optimization" / "latest.json")
        run_id = str(latest.get("run_id", "")) if latest else ""
        if not run_id and runs_root.is_dir():
            candidates = sorted(
                path.name
                for path in runs_root.iterdir()
                if path.is_dir() and (path / "optimization_plan.json").is_file()
            )
            run_id = candidates[-1] if candidates else ""
    if not run_id:
        warnings.append("No V0.7 optimization run is available for this job.")
        return None, None
    candidate = runs_root / run_id
    try:
        candidate.resolve().relative_to(runs_root.resolve())
    except ValueError as exc:
        raise ValueError(f"Invalid optimization run ID: {run_id}") from exc
    if candidate.resolve().parent != runs_root.resolve():
        raise ValueError(f"Invalid optimization run ID: {run_id}")
    if not candidate.is_dir():
        warnings.append(f"Optimization run is missing: {run_id}")
        return run_id, None
    return run_id, candidate


def _portable_package_candidates(root: Path) -> list[Path]:
    """List safe immutable V0.7 package directories containing a package manifest."""

    packages_root = root / "exports" / "packages"
    if not packages_root.is_dir():
        return []
    candidates: list[Path] = []
    for profile_dir in packages_root.iterdir():
        if not profile_dir.is_dir():
            continue
        for package_dir in profile_dir.iterdir():
            manifest = package_dir / "package_manifest.json"
            try:
                package_dir.resolve().relative_to(packages_root.resolve())
            except ValueError:
                continue
            if package_dir.resolve().parent != profile_dir.resolve() or not manifest.is_file():
                continue
            candidates.append(package_dir)
    return sorted(
        candidates,
        key=lambda path: path.relative_to(packages_root).as_posix(),
    )


def _resolve_portable_package(
    root: Path,
    requested_package_id: str | None,
    warnings: list[str],
) -> tuple[str | None, Path | None]:
    """Resolve one explicit package ID or the latest available V0.7 package."""

    candidates = _portable_package_candidates(root)
    if requested_package_id in {None, "latest"}:
        if not candidates:
            warnings.append("No V0.7 portable package is available for this job.")
            return None, None
        selected = candidates[-1]
        return selected.name, selected
    requested = str(requested_package_id)
    normalized = requested.replace("\\", "/").strip("/")
    if not normalized or ".." in normalized.split("/"):
        raise ValueError(f"Invalid portable package ID: {requested}")
    if "/" in normalized:
        matches = [
            path
            for path in candidates
            if path.relative_to(root / "exports" / "packages").as_posix() == normalized
        ]
    else:
        matches = [path for path in candidates if path.name == normalized]
    if len(matches) > 1:
        raise ValueError(
            f"Portable package ID is ambiguous across profiles: {requested}; "
            "use profile/package-id"
        )
    if not matches:
        warnings.append(f"Portable package is missing: {requested}")
        return requested, None
    return matches[0].name, matches[0]


def _collect_json_source(
    root: Path,
    key: str,
    path: Path,
    documents: dict[str, dict[str, Any]],
    sources: list[ReportSource],
) -> None:
    """Load and register one optional JSON report source."""

    payload = _load_json(path)
    if payload is None:
        return
    documents[key] = payload
    sources.append(_source_record(root, key, path))


def _verified_package_snapshot(
    root: Path,
    package_dir: Path,
    package_manifest: dict[str, Any],
    relative: str,
    warnings: list[str],
) -> Path | None:
    """Return one immutable metadata snapshot only when its receipt still verifies."""

    candidate = package_dir / relative
    safe = _safe_job_file(root, candidate, warnings)
    if safe is None:
        return None
    try:
        safe.relative_to(package_dir.resolve())
    except ValueError:
        warnings.append(f"Skipped an escaping package metadata snapshot: {Path(relative).name}")
        return None
    expected_path = _job_relative(root, safe)
    receipt = next(
        (
            item
            for item in package_manifest.get("files", [])
            if isinstance(item, dict) and item.get("path") == expected_path
        ),
        None,
    )
    if not isinstance(receipt, dict):
        warnings.append(f"Package metadata snapshot has no receipt: {relative}")
        return None
    if (
        receipt.get("sha256") != sha256_file(safe)
        or receipt.get("byte_size") != safe.stat().st_size
    ):
        warnings.append(f"Skipped changed package metadata snapshot: {relative}")
        return None
    return safe


def _collect_export_sources(
    root: Path,
    documents: dict[str, dict[str, Any]],
    sources: list[ReportSource],
    warnings: list[str],
    *,
    optimization_run_id: str | None,
    package_id: str | None,
) -> tuple[str | None, str | None]:
    """Collect job-contained V0.7 optimization and portable-package JSON evidence."""

    resolved_package_id, package_dir = _resolve_portable_package(
        root,
        package_id,
        warnings,
    )
    package_manifest: dict[str, Any] | None = None
    if package_dir is not None:
        package_manifest_path = package_dir / "package_manifest.json"
        _collect_json_source(
            root,
            "package_manifest",
            package_manifest_path,
            documents,
            sources,
        )
        package_manifest = documents.get("package_manifest")
        _collect_json_source(
            root,
            "texture_pack_manifest",
            package_dir / "texture_pack_manifest.json",
            documents,
            sources,
        )

    manifest_run_id: str | None = None
    if package_manifest is not None:
        value = package_manifest.get("run_id")
        manifest_run_id = value if isinstance(value, str) and value else None
        if (
            optimization_run_id not in {None, "latest"}
            and manifest_run_id is not None
            and optimization_run_id != manifest_run_id
        ):
            raise ValueError(
                "Requested optimization run does not match the selected package manifest: "
                f"{optimization_run_id} != {manifest_run_id}"
            )
        if package_dir is not None:
            snapshot_pairs = [
                ("asset_profile", "metadata/asset_profile.json"),
                ("optimization_plan", "metadata/optimization_plan.json"),
                ("mesh_preflight_report", "metadata/mesh_preflight_report.json"),
                ("lod_manifest", "metadata/lod_manifest.json"),
                ("collision_manifest", "metadata/collision_manifest.json"),
                ("uv_manifest", "metadata/uv_manifest.json"),
                ("asset_cost_report", "metadata/asset_cost_report.json"),
            ]
            optional_review_snapshots = [
                ("review_plan", "metadata/review_plan.json"),
                ("optimization_review", "metadata/optimization_review.json"),
                ("optimization_approval", "metadata/optimization_approval.json"),
            ]
            snapshot_pairs.extend(
                (key, relative)
                for key, relative in optional_review_snapshots
                if (package_dir / relative).is_file()
            )
            if isinstance(package_manifest.get("material_conversion"), dict):
                snapshot_pairs.extend(
                    [
                        (
                            "material_conversion_plan",
                            "metadata/material_conversion_plan.json",
                        ),
                        (
                            "material_conversion_manifest",
                            "metadata/material_conversion_manifest.json",
                        ),
                        (
                            "material_conversion_evidence",
                            "metadata/material_conversion_evidence.json",
                        ),
                    ]
                )
            for key, relative in snapshot_pairs:
                snapshot = _verified_package_snapshot(
                    root,
                    package_dir,
                    package_manifest,
                    relative,
                    warnings,
                )
                if snapshot is not None:
                    _collect_json_source(root, key, snapshot, documents, sources)

    requested_run_id = optimization_run_id
    if requested_run_id in {None, "latest"} and manifest_run_id is not None:
        requested_run_id = manifest_run_id
    resolved_run_id, run_dir = _resolve_optimization_run(
        root,
        requested_run_id,
        warnings,
    )
    if run_dir is not None:
        for key, filename in (
            ("review_plan", "review_plan.json"),
            ("optimization_review", "optimization_review.json"),
            ("optimization_approval", "optimization_approval.json"),
            ("optimization_plan", "optimization_plan.json"),
            ("mesh_preflight_report", "mesh_preflight_report.json"),
            ("lod_manifest", "lod_manifest.json"),
            ("collision_manifest", "collision_manifest.json"),
            ("uv_manifest", "uv_manifest.json"),
            ("asset_cost_report", "asset_cost_report.json"),
        ):
            if key not in documents:
                _collect_json_source(root, key, run_dir / filename, documents, sources)
        if "optimization_plan" not in documents:
            warnings.append(f"Optimization run has no plan: {resolved_run_id}")
        plan = documents.get("optimization_plan") or {}
        profile_artifact = plan.get("profile_artifact")
        profile_path_value = (
            profile_artifact.get("path") if isinstance(profile_artifact, dict) else None
        )
        if "asset_profile" in documents:
            pass
        elif isinstance(profile_path_value, str) and profile_path_value:
            profile_path = _safe_job_file(root, root / profile_path_value, warnings)
            if profile_path is not None:
                _collect_json_source(
                    root,
                    "asset_profile",
                    profile_path,
                    documents,
                    sources,
                )
        elif isinstance(plan.get("profile_id"), str):
            _collect_json_source(
                root,
                "asset_profile",
                root / "asset_profiles" / f"{plan['profile_id']}.json",
                documents,
                sources,
            )
        if resolved_package_id is not None:
            _collect_json_source(
                root,
                "roundtrip_validation",
                run_dir
                / "roundtrip"
                / resolved_package_id
                / "roundtrip_validation.json",
                documents,
                sources,
            )
            if "roundtrip_validation" not in documents:
                warnings.append(
                    "Portable package has no round-trip validation: "
                    f"{resolved_package_id}"
                )
    return resolved_run_id, resolved_package_id


def _collect_destination_handoff_sources(
    root: Path,
    documents: dict[str, dict[str, Any]],
    sources: list[ReportSource],
    warnings: list[str],
    *,
    package_id: str | None,
) -> str | None:
    """Collect the newest valid V0.9 handoff bound to the selected package."""

    package = documents.get("package_manifest") or {}
    profile_id = package.get("profile_id")
    if not package_id or not isinstance(profile_id, str):
        return None
    handoffs_root = (
        root / "exports" / "destination_handoffs" / profile_id / package_id
    )
    if not handoffs_root.is_dir():
        warnings.append(
            f"No V0.9 Codex Destination Handoff is available for package: {package_id}"
        )
        return None
    candidates = sorted(
        path
        for path in handoffs_root.iterdir()
        if path.is_dir() and (path / "destination_handoff_validation.json").is_file()
    )
    for envelope in reversed(candidates):
        try:
            validate_destination_handoff(
                root.name,
                profile_id=profile_id,
                package_id=package_id,
                handoff_id=envelope.name,
            )
        except Exception as exc:
            warnings.append(
                "Skipped invalid or stale V0.9 destination handoff "
                f"{envelope.name}: {type(exc).__name__}"
            )
            continue
        handoff_root = envelope / "codex_handoff"
        for key, path in (
            ("destination_handoff_manifest", handoff_root / "handoff_manifest.json"),
            ("destination_context", handoff_root / "destination_context.json"),
            ("assembly_manifest", handoff_root / "assembly_manifest.json"),
            ("material_mapping", handoff_root / "material_mapping.json"),
            ("import_checklist", handoff_root / "import_checklist.json"),
            (
                "destination_handoff_validation",
                envelope / "destination_handoff_validation.json",
            ),
            (
                "destination_handoff_pdf_manifest",
                handoff_root / "handoff_report.manifest.json",
            ),
        ):
            _collect_json_source(root, key, path, documents, sources)
        return envelope.name
    if candidates:
        warnings.append(
            f"No valid V0.9 destination handoff remains for package: {package_id}"
        )
    return None


def _collect_material_images(
    root: Path,
    documents: dict[str, dict[str, Any]],
    sources: list[ReportSource],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Resolve safe material swatch images and add their hashes to report provenance."""

    swatches: list[dict[str, Any]] = []
    manifest = documents.get("material_swatches") or {}
    for record in manifest.get("swatches", []):
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            continue
        raw_path = Path(record["path"])
        candidate = raw_path if raw_path.is_absolute() else root / raw_path
        path = _safe_job_file(root, candidate, warnings)
        if path is None:
            continue
        material_id = str(record.get("material_id", "unknown"))
        if not _recorded_hash_is_current(
            path,
            record.get("sha256"),
            f"material swatch {material_id}",
            warnings,
        ):
            continue
        sources.append(_source_record(root, "material_swatch", path))
        swatches.append({"record": record, "path": str(path)})
    return swatches


def _collect_qa_images(
    root: Path,
    run_dir: Path | None,
    documents: dict[str, dict[str, Any]],
    sources: list[ReportSource],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Resolve safe fixed-camera QA pass images from their run-local manifest."""

    if run_dir is None:
        return []
    images: list[dict[str, Any]] = []
    manifest = documents.get("qa_pass_manifest") or {}
    for record in manifest.get("passes", []):
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            continue
        path = _safe_job_file(root, run_dir / record["path"], warnings)
        if path is None:
            continue
        kind = str(record.get("kind", "unknown"))
        if not _recorded_hash_is_current(
            path,
            record.get("sha256"),
            f"QA pass {kind}",
            warnings,
        ):
            continue
        sources.append(_source_record(root, f"qa_pass:{record.get('kind', 'unknown')}", path))
        images.append({"record": record, "path": str(path)})
    return images


def _companion_file_is_current(
    root: Path,
    relative_path: Any,
    expected_sha256: Any,
    *,
    label: str,
    warnings: list[str],
) -> Path | None:
    """Resolve one bundle-declared companion file only when its exact hash is current."""

    if not isinstance(relative_path, str) or not isinstance(expected_sha256, str):
        warnings.append(f"QA companion diagnostics omit an exact {label} path/hash binding.")
        return None
    candidate = _safe_job_file(root, root / relative_path, warnings)
    if candidate is None:
        return None
    if not _recorded_hash_is_current(candidate, expected_sha256, label, warnings):
        return None
    return candidate


def _diagnostic_request_sources_are_current(
    root: Path,
    request: QADiagnosticRequest,
    warnings: list[str],
) -> bool:
    """Re-hash every canonical source frozen by a companion diagnostic request."""

    pairs: list[tuple[str, str, str]] = [
        (
            request.visual_qa_request_path,
            request.visual_qa_request_sha256,
            "diagnostic VisualQARequest",
        ),
        (
            request.visual_qa_report_path,
            request.visual_qa_report_sha256,
            "diagnostic VisualQAReport",
        ),
        (
            request.render_pass_manifest_path,
            request.render_pass_manifest_sha256,
            "diagnostic render-pass manifest",
        ),
        (request.scene_spec_path, request.scene_spec_sha256, "diagnostic SceneSpec"),
    ]
    for path, digest, label in (
        (
            request.modeling_plan_path,
            request.modeling_plan_sha256,
            "diagnostic ModelingPlan",
        ),
        (
            request.camera_role_map_path,
            request.camera_role_map_sha256,
            "diagnostic camera role map",
        ),
        (
            request.semantic_reference_manifest_path,
            request.semantic_reference_manifest_sha256,
            "diagnostic semantic-mask manifest",
        ),
        (
            request.assembly_report_path,
            request.assembly_report_sha256,
            "diagnostic assembly report",
        ),
        (
            request.primary_reference_mask_path,
            request.primary_reference_mask_sha256,
            "diagnostic primary-reference mask",
        ),
    ):
        if path is not None and digest is not None:
            pairs.append((path, digest, label))
    pairs.extend(
        (
            binding.reference_mask_path,
            binding.reference_mask_sha256,
            f"semantic reference mask {binding.semantic_id}",
        )
        for binding in request.semantic_masks
    )
    pairs.extend(
        (
            binding.rendered_mask_path,
            binding.rendered_mask_sha256,
            f"semantic rendered mask {binding.semantic_id}",
        )
        for binding in request.semantic_masks
    )
    for relative_path, expected_sha256, label in pairs:
        if (
            _companion_file_is_current(
                root,
                relative_path,
                expected_sha256,
                label=label,
                warnings=warnings,
            )
            is None
        ):
            return False
    return True


def _collect_companion_assembly_report(
    root: Path,
    bundle: QADiagnosticBundleManifest,
    documents: dict[str, dict[str, Any]],
    sources: list[ReportSource],
    warnings: list[str],
) -> None:
    """Collect an optional multi-view assembly report only through its bundle hash."""

    binding = bundle.assembly_multiview
    report_path = binding.report_path
    report_sha256 = binding.report_sha256
    if report_path is None and report_sha256 is None:
        return
    path = _companion_file_is_current(
        root,
        report_path,
        report_sha256,
        label="assembly multi-view report",
        warnings=warnings,
    )
    if path is None:
        return
    try:
        payload = _load_json(path)
    except (OSError, ValueError) as exc:
        warnings.append(f"Assembly multi-view report is unavailable: {exc}")
        return
    if payload is None:
        return
    expected_identity = (
        payload.get("schema_version") == "0.6.0"
        and payload.get("diagnostic_kind") == "assembly_multiview_sanity"
        and payload.get("job_id") == bundle.job_id
        and payload.get("run_id") == binding.run_id
        and payload.get("structural_status") in {"passed", "warning", "failed"}
        and payload.get("reference_comparison_status") == "unscorable"
        and isinstance(payload.get("limitations", []), list)
    )
    if not expected_identity:
        warnings.append("Skipped an assembly multi-view report with mismatched identity.")
        return
    documents["assembly_sanity_report"] = payload
    sources.append(_source_record(root, "assembly_sanity_report", path))


def _collect_qa_companion_sources(
    root: Path,
    run_id: str,
    run_dir: Path,
    documents: dict[str, dict[str, Any]],
    sources: list[ReportSource],
    warnings: list[str],
) -> None:
    """Collect a terminal companion bundle and its exact immutable attempt artifacts."""

    diagnostic_id = "camera-geometry-v1"
    diagnostic_root = run_dir / "diagnostics" / diagnostic_id
    if not diagnostic_root.is_dir():
        warnings.append(
            "QA companion diagnostics are unavailable for this legacy or standalone QA run."
        )
        return
    bundle_path = diagnostic_root / "bundle_manifest.json"
    if not bundle_path.is_file():
        warnings.append("QA companion diagnostics are incomplete and were not included.")
        return
    try:
        bundle, request, report = validate_qa_diagnostic_bundle(root, bundle_path)
        bundle_payload = bundle.model_dump(mode="json")
        request_payload = request.model_dump(mode="json")
        report_payload = report.model_dump(mode="json")
    except (OSError, ValueError) as exc:
        warnings.append(f"QA companion diagnostics are malformed and unavailable: {exc}")
        return
    if (
        bundle.job_id != root.name
        or bundle.qa_run_id != run_id
        or bundle.diagnostic_id != diagnostic_id
    ):
        warnings.append("QA companion diagnostics have mismatched terminal identity.")
        return
    request_path = root / bundle.diagnostic_request_path
    report_path = root / bundle.diagnostic_report_path
    expected_request_path = bundle.diagnostic_request_path
    visual_request_path = run_dir / "request.json"
    visual_report_path = run_dir / "visual_qa_report.json"
    pass_manifest_path = run_dir / "render_pass_manifest.json"
    scene_spec_path = root / "analysis" / "scene_spec.json"
    identity_is_current = (
        bundle.job_id == request.job_id == report.job_id == root.name
        and bundle.qa_run_id == request.qa_run_id == report.qa_run_id == run_id
        and bundle.diagnostic_id
        == request.diagnostic_id
        == report.diagnostic_id
        == diagnostic_id
        and report.request_path == expected_request_path
        and report.request_sha256 == bundle.diagnostic_request_sha256
        and bundle.visual_qa_report_path == _job_relative(root, visual_report_path)
        and request.visual_qa_request_path == _job_relative(root, visual_request_path)
        and visual_request_path.is_file()
        and request.visual_qa_request_sha256 == sha256_file(visual_request_path)
        and request.visual_qa_report_path == _job_relative(root, visual_report_path)
        and request.visual_qa_report_sha256 == bundle.visual_qa_report_sha256
        and visual_report_path.is_file()
        and bundle.visual_qa_report_sha256 == sha256_file(visual_report_path)
        and request.render_pass_manifest_path == _job_relative(root, pass_manifest_path)
        and pass_manifest_path.is_file()
        and request.render_pass_manifest_sha256 == sha256_file(pass_manifest_path)
        and request.scene_spec_path == _job_relative(root, scene_spec_path)
        and scene_spec_path.is_file()
        and request.scene_spec_sha256 == sha256_file(scene_spec_path)
    )
    if not identity_is_current:
        warnings.append("QA companion diagnostics are stale or identity-mismatched.")
        return
    for relative_path, expected_sha256, label in (
        (
            bundle.camera_probe_plan_path,
            bundle.camera_probe_plan_sha256,
            "camera-probe plan",
        ),
        (
            bundle.camera_probe_manifest_path,
            bundle.camera_probe_manifest_sha256,
            "camera-probe manifest",
        ),
    ):
        if (
            _companion_file_is_current(
                root,
                relative_path,
                expected_sha256,
                label=label,
                warnings=warnings,
            )
            is None
        ):
            warnings.append("QA companion diagnostics have stale probe evidence.")
            return
    for probe in report.camera_probes:
        if (
            _companion_file_is_current(
                root,
                probe.evidence_path,
                probe.evidence_sha256,
                label=f"camera-probe result {probe.probe_id}",
                warnings=warnings,
            )
            is None
        ):
            warnings.append("QA companion diagnostics have stale probe result evidence.")
            return
    if not _diagnostic_request_sources_are_current(root, request, warnings):
        warnings.append("QA companion diagnostics reference stale source evidence.")
        return
    documents["qa_diagnostic_request"] = request_payload
    documents["qa_diagnostic_report"] = report_payload
    documents["qa_diagnostic_bundle"] = bundle_payload
    sources.extend(
        [
            _source_record(root, "qa_diagnostic_request", request_path),
            _source_record(root, "qa_diagnostic_report", report_path),
            _source_record(root, "qa_diagnostic_bundle", bundle_path),
        ]
    )
    _collect_companion_assembly_report(root, bundle, documents, sources, warnings)


def _collect_interior_qa_images(
    root: Path,
    run_dir: Path | None,
    sources: list[ReportSource],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Resolve safe interior contact sheets without treating them as decision sources."""

    if run_dir is None:
        return []
    images: list[dict[str, Any]] = []
    for kind in ("beauty", "object_id", "wireframe"):
        path = _safe_job_file(root, run_dir / "contact_sheets" / f"{kind}.png", warnings)
        if path is None:
            continue
        sources.append(_source_record(root, f"interior_qa_contact_sheet:{kind}", path))
        images.append({"kind": kind, "path": str(path)})
    return images


def collect_job_report_payload(
    job_id: str,
    scope: ReportScope,
    *,
    qa_run_id: str | None = "latest",
    interior_qa_run_id: str | None = "latest",
    optimization_run_id: str | None = "latest",
    package_id: str | None = "latest",
    background_quality_report_path: str | None = None,
) -> dict[str, Any]:
    """Collect safe machine reports and visual evidence for one PDF presentation scope."""

    if scope not in REPORT_SCOPES:
        raise ValueError(f"scope must be one of {sorted(REPORT_SCOPES)}")
    root = job_dir(job_id)
    metadata = load_job(job_id)
    warnings: list[str] = []
    documents: dict[str, dict[str, Any]] = {}
    sources = [_source_record(root, "job", root / "job.json")]
    _collect_json_source(
        root,
        "scene_spec",
        root / "analysis" / "scene_spec.json",
        documents,
        sources,
    )
    if scope in {"build", "material", "qa", "full"}:
        _collect_json_source(
            root,
            "surface_detail_validation",
            root / "reports" / "surface_detail_validation.json",
            documents,
            sources,
        )

    if scope in {"build", "full"}:
        for key, relative in (
            ("validation", "reports/validation.json"),
            ("scene_inventory", "reports/scene_inventory.json"),
            ("constraint_solution", "reports/constraint_solution.json"),
            ("interior_scope_validation", "reports/interior_scope_validation.json"),
            ("interior_scope", "architecture/interior_scope.json"),
            ("interior_scope_approval", "architecture/interior_scope.approval.json"),
            ("reference_analysis", "analysis/reference_analysis.json"),
            ("camera_solution", "analysis/camera_solution.json"),
        ):
            _collect_json_source(root, key, root / relative, documents, sources)

    if scope in {"material", "full"}:
        for key, relative in (
            ("material_plan", "analysis/material_plan.json"),
            ("material_contract_validation", "reports/material_contract_validation.json"),
            ("material_fidelity_validation", "reports/material_fidelity_validation.json"),
            ("material_validation", "reports/material_validation.json"),
            ("material_swatches", "reports/material_swatches.json"),
            ("material_bakes", "reports/material_bakes.json"),
        ):
            _collect_json_source(root, key, root / relative, documents, sources)

    run_id: str | None = None
    run_dir: Path | None = None
    resolved_interior_qa_run_id: str | None = None
    interior_qa_run_dir: Path | None = None
    if scope in {"qa", "full"}:
        run_id, run_dir = _resolve_qa_run(root, qa_run_id, warnings)
        if run_dir is not None:
            for key, filename in (
                ("qa_request", "request.json"),
                ("qa_pass_manifest", "render_pass_manifest.json"),
                ("visual_qa_report", "visual_qa_report.json"),
                ("revision_candidates", "revision_candidates.json"),
                ("revision_plan", "revision_plan.json"),
                ("revision_approval", "revision_approval.json"),
                ("revision_application", "application_report.json"),
                ("convergence", "convergence.json"),
                ("rollback", "rollback_report.json"),
            ):
                _collect_json_source(root, key, run_dir / filename, documents, sources)
            assert run_id is not None
            _collect_qa_companion_sources(
                root,
                run_id,
                run_dir,
                documents,
                sources,
                warnings,
            )
        resolved_interior_qa_run_id, interior_qa_run_dir = _resolve_interior_qa_run(
            root,
            interior_qa_run_id,
            warnings,
        )
        if interior_qa_run_dir is not None and run_dir is None:
            warnings = [
                warning
                for warning in warnings
                if warning != "No visual QA run is available for this job."
            ]
        if interior_qa_run_dir is not None:
            for key, filename in (
                ("interior_qa_plan", "plan.json"),
                ("interior_qa_approval", "plan_approval.json"),
                ("interior_qa_source_inventory", "source_inventory.json"),
                ("interior_qa_render_manifest", "render_manifest.json"),
                ("interior_qa_report", "interior_qa_report.json"),
                ("interior_qa_revision_candidates", "revision_candidates.json"),
            ):
                _collect_json_source(
                    root,
                    key,
                    interior_qa_run_dir / filename,
                    documents,
                    sources,
                )
    if (
        scope in {"qa", "export", "full"}
        and background_quality_report_path is not None
    ):
        quality_path = _safe_job_file(
            root,
            root / background_quality_report_path,
            warnings,
        )
        if quality_path is not None:
            _collect_json_source(
                root,
                "background_quality_report",
                quality_path,
                documents,
                sources,
            )

    resolved_optimization_run_id: str | None = None
    resolved_package_id: str | None = None
    resolved_handoff_id: str | None = None
    if scope in {"export", "full"}:
        resolved_optimization_run_id, resolved_package_id = _collect_export_sources(
            root,
            documents,
            sources,
            warnings,
            optimization_run_id=optimization_run_id,
            package_id=package_id,
        )
        resolved_handoff_id = _collect_destination_handoff_sources(
            root,
            documents,
            sources,
            warnings,
            package_id=resolved_package_id,
        )

    reference = _resolve_reference(metadata, root, warnings)
    if reference is not None:
        sources.append(_source_record(root, "reference", reference))
    preview = (
        _safe_job_file(root, root / "renders" / "preview.png", warnings)
        if scope != "qa" or run_dir is not None
        else None
    )
    if preview is not None:
        sources.append(_source_record(root, "preview", preview))
    swatches = (
        _collect_material_images(root, documents, sources, warnings)
        if scope in {"material", "full"}
        else []
    )
    qa_images = (
        _collect_qa_images(root, run_dir, documents, sources, warnings)
        if scope in {"qa", "full"}
        else []
    )
    interior_qa_images = (
        _collect_interior_qa_images(
            root,
            interior_qa_run_dir,
            sources,
            warnings,
        )
        if scope in {"qa", "full"}
        else []
    )
    sources.sort(key=lambda source: (source.kind, source.path))
    return {
        "job_id": job_id,
        "scope": scope,
        "job": metadata,
        "documents": documents,
        "images": {
            "reference": str(reference) if reference else None,
            "preview": str(preview) if preview else None,
            "material_swatches": swatches,
            "qa_passes": qa_images,
            "interior_qa_contact_sheets": interior_qa_images,
        },
        "qa_run_id": run_id,
        "interior_qa_run_id": resolved_interior_qa_run_id,
        "optimization_run_id": resolved_optimization_run_id,
        "package_id": resolved_package_id,
        "handoff_id": resolved_handoff_id,
        "warnings": warnings,
        "sources": sources,
        "source_fingerprint": _source_fingerprint(sources),
    }


def report_output_dir(job_id: str) -> Path:
    """Return a workspace-isolated user-facing PDF directory for one job."""

    settings = get_settings()
    return settings.workspace_root.parent / "output" / "pdf" / job_id


def _default_output_path(job_id: str, scope: ReportScope) -> Path:
    """Return the stable user-facing PDF path beside the active workspace root."""

    return report_output_dir(job_id) / f"{scope}_report.pdf"


def generate_job_pdf_report(
    job_id: str,
    scope: ReportScope = "full",
    *,
    qa_run_id: str | None = "latest",
    interior_qa_run_id: str | None = "latest",
    optimization_run_id: str | None = "latest",
    package_id: str | None = "latest",
    background_quality_report_path: str | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Generate one atomic human-readable PDF without changing machine report sources."""

    payload = collect_job_report_payload(
        job_id,
        scope,
        qa_run_id=qa_run_id,
        interior_qa_run_id=interior_qa_run_id,
        optimization_run_id=optimization_run_id,
        package_id=package_id,
        background_quality_report_path=background_quality_report_path,
    )
    output = (output_path or _default_output_path(job_id, scope)).expanduser().resolve()
    if output.suffix.lower() != ".pdf":
        raise ValueError("PDF report output must use a .pdf extension")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.{uuid4().hex}.tmp"
    try:
        render_metadata = render_job_pdf(payload, temporary)
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    manifest = HumanReportManifest(
        job_id=job_id,
        scope=scope,
        generated_at=datetime.now(UTC).isoformat(),
        pdf_path=str(output),
        pdf_sha256=sha256_file(output),
        source_fingerprint=payload["source_fingerprint"],
        qa_run_id=payload["qa_run_id"],
        interior_qa_run_id=payload["interior_qa_run_id"],
        optimization_run_id=payload["optimization_run_id"],
        package_id=payload["package_id"],
        font=str(render_metadata["font"]),
        sources=payload["sources"],
        warnings=payload["warnings"],
    )
    manifest_path = output.with_suffix(".manifest.json")
    write_json_atomic(manifest_path, manifest.model_dump(mode="json"))
    return {
        "ok": True,
        "job_id": job_id,
        "scope": scope,
        "pdf": str(output),
        "manifest": str(manifest_path),
        "pdf_sha256": manifest.pdf_sha256,
        "source_fingerprint": manifest.source_fingerprint,
        "interior_qa_run_id": manifest.interior_qa_run_id,
        "optimization_run_id": manifest.optimization_run_id,
        "package_id": manifest.package_id,
        "source_count": len(manifest.sources),
        "warnings": manifest.warnings,
        "font": manifest.font,
    }
