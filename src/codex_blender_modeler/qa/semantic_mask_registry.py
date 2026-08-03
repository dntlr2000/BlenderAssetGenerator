"""Safe registration of explicit, job-owned semantic reference masks."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from uuid import uuid4

from ..models import ObjectSpec, SceneSpec, SourceSpec
from ..workspace import (
    canonical_scene_spec_write_lock,
    file_exists,
    job_dir,
    load_job,
    native_io_path,
    resolve_metadata_path,
    sha256_file,
)
from .diagnostic_models import (
    SemanticReferenceMaskManifest,
    SemanticReferenceMaskRecord,
)
from .image_io import open_image
from .semantic_mask_registry_models import (
    RegisteredSemanticMaskArtifact,
    SemanticReferenceMaskPromotionReceipt,
    SemanticReferenceMaskRegistryStatus,
)

REGISTRATION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CANONICAL_MANIFEST = "analysis/masks/semantic_manifest.json"


class StaleSemanticMaskEvidence(ValueError):
    """Identify evidence whose exact source bytes no longer match its declaration."""


def _validate_registration_id(value: str) -> str:
    """Require a lowercase filesystem-safe immutable registration identity."""

    if not REGISTRATION_ID_RE.fullmatch(value):
        raise ValueError(
            "registration_id must match [a-z0-9][a-z0-9._-]{0,95}"
        )
    return value


def _validate_sha256(value: str) -> str:
    """Require one canonical lowercase SHA-256 string from the caller."""

    if not SHA256_RE.fullmatch(value):
        raise ValueError("manifest_sha256 must be a lowercase SHA-256")
    return value


def _is_link_like(path: Path) -> bool:
    """Return whether a path is a symbolic link or Windows junction."""

    native = native_io_path(path)
    if os.path.islink(native):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction(native)) if callable(is_junction) else False


def _path_exists(path: Path) -> bool:
    """Check any filesystem entry without following a broken link-like leaf."""

    return os.path.lexists(native_io_path(path))


def _directory_exists(path: Path) -> bool:
    """Check one directory through the Windows extended-length path form."""

    return os.path.isdir(native_io_path(path))


def _require_safe_job_path(root: Path, path: Path, label: str) -> Path:
    """Require lexical job containment and reject every existing link-like ancestor."""

    absolute_root = Path(os.path.abspath(os.fspath(root.expanduser())))
    candidate = Path(os.path.abspath(os.fspath(path.expanduser())))
    try:
        relative = candidate.relative_to(absolute_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the owning job") from exc
    if _is_link_like(absolute_root):
        raise ValueError(f"{label} job root must not be link-like")
    current = absolute_root
    for part in relative.parts:
        current = current / part
        if _path_exists(current) and _is_link_like(current):
            raise ValueError(f"{label} must not traverse a link-like path")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(absolute_root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes the owning job") from exc
    return candidate


def _resolve_job_path(root: Path, value: str, label: str) -> Path:
    """Resolve one normalized POSIX job-relative path and reject link traversal."""

    if (
        not value
        or "\\" in value
        or ":" in value
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or str(PurePosixPath(value)) != value
    ):
        raise ValueError(f"{label} must be a normalized job-relative POSIX path")
    candidate = root.joinpath(*PurePosixPath(value).parts)
    return _require_safe_job_path(root, candidate, label)


def _job_relative(root: Path, path: Path) -> str:
    """Serialize one validated job-owned path as normalized POSIX metadata."""

    absolute_root = Path(os.path.abspath(os.fspath(root.expanduser())))
    candidate = _require_safe_job_path(
        absolute_root,
        path,
        "semantic mask artifact",
    )
    return candidate.relative_to(absolute_root).as_posix()


def _sha256_bytes(content: bytes) -> str:
    """Hash one in-memory registry snapshot without reopening a mutable path."""

    return sha256(content).hexdigest()


def _read_bytes(path: Path) -> bytes:
    """Read exact registry bytes through a Windows-long-path-safe filename."""

    with open(native_io_path(path), "rb") as handle:
        return handle.read()


def _read_text(path: Path) -> str:
    """Read one UTF-8 registry contract through a long-path-safe filename."""

    return _read_bytes(path).decode("utf-8")


def _write_bytes_atomic(root: Path, path: Path, content: bytes) -> None:
    """Publish bytes atomically after checking job containment and link ancestors."""

    path = _require_safe_job_path(root, path, "semantic mask write target")
    os.makedirs(native_io_path(path.parent), exist_ok=True)
    path = _require_safe_job_path(root, path, "semantic mask write target")
    temporary = path.parent / f".semantic-mask-{uuid4().hex[:10]}.tmp"
    try:
        temporary = _require_safe_job_path(root, temporary, "semantic mask temporary")
        with open(native_io_path(temporary), "xb") as handle:
            handle.write(content)
        if _read_bytes(temporary) != content:
            raise RuntimeError("semantic mask temporary write verification failed")
        _replace_job_file(
            root,
            temporary,
            path,
            "semantic mask atomic publication",
        )
        if _read_bytes(path) != content:
            raise RuntimeError("semantic mask published bytes differ from the source")
    finally:
        try:
            os.unlink(native_io_path(temporary))
        except FileNotFoundError:
            pass


def _replace_job_file(
    root: Path,
    source: Path,
    destination: Path,
    label: str,
) -> Path:
    """Atomically replace one same-directory job file with pre/post safety checks."""

    source = _require_safe_job_path(root, source, f"{label} source")
    destination = _require_safe_job_path(root, destination, f"{label} target")
    if source.parent != destination.parent:
        raise ValueError(f"{label} must stay inside one directory")
    if _is_link_like(source) or not file_exists(source):
        raise FileNotFoundError(source)
    source_hash = sha256_file(source)

    # Re-check every participating path immediately before replacement so a
    # late link/junction swap fails closed rather than publishing through it.
    _require_safe_job_path(root, source.parent, f"{label} parent")
    source = _require_safe_job_path(root, source, f"{label} source")
    destination = _require_safe_job_path(root, destination, f"{label} target")
    os.replace(native_io_path(source), native_io_path(destination))

    published = _require_safe_job_path(root, destination, f"{label} result")
    if _is_link_like(published) or not file_exists(published):
        raise RuntimeError(f"{label} did not publish one regular job-owned file")
    if sha256_file(published) != source_hash:
        raise RuntimeError(f"{label} changed bytes during publication")
    return published


def _write_json_atomic(root: Path, path: Path, payload: dict[str, object]) -> None:
    """Publish one strict job-owned JSON journal without a partial receipt."""

    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    _write_bytes_atomic(root, path, encoded)


def _primary_reference(root: Path, job_id: str) -> tuple[Path, str, str]:
    """Resolve and re-hash the single immutable primary-reference record."""

    metadata = load_job(job_id)
    records = [
        item
        for item in metadata.get("sources", [])
        if isinstance(item, dict) and item.get("kind") == "reference"
    ]
    if len(records) != 1:
        raise ValueError("semantic mask registration requires one primary reference")
    record = records[0]
    raw_path = record.get("path")
    expected_hash = record.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(expected_hash, str):
        raise ValueError("primary reference metadata lacks path or SHA-256")
    path = _require_safe_job_path(
        root,
        resolve_metadata_path(raw_path),
        "primary reference",
    )
    input_root = _require_safe_job_path(
        root,
        root / "input",
        "primary reference ownership root",
    )
    try:
        path.relative_to(input_root)
    except ValueError as exc:
        raise ValueError("primary reference must remain inside the job input directory") from exc
    if _is_link_like(path) or not file_exists(path):
        raise FileNotFoundError("primary reference is missing or link-like")
    current_hash = sha256_file(path)
    if current_hash != expected_hash:
        raise StaleSemanticMaskEvidence("primary reference changed from job metadata")
    return path, _job_relative(root, path), current_hash


def _validate_mask_image(mask_path: Path, reference_size: tuple[int, int]) -> None:
    """Require one exact-size, nonempty binary PNG without altering its pixels."""

    try:
        with open_image(mask_path) as opened:
            if opened.format != "PNG":
                raise ValueError("semantic reference masks must be PNG files")
            mask = opened.convert("L")
            mask.load()
            if mask.size != reference_size:
                raise ValueError(
                    "semantic reference mask resolution must equal the reference"
                )
            values = set(mask.getdata())
    except OSError as exc:
        raise ValueError(f"semantic reference mask is unreadable: {mask_path.name}") from exc
    if not values.issubset({0, 255}) or 255 not in values:
        raise ValueError("semantic reference masks must be binary and nonempty")


def _validate_manifest_evidence(
    root: Path,
    job_id: str,
    manifest_path: Path,
    *,
    registration_id: str | None,
    expected_manifest_sha256: str | None = None,
) -> tuple[
    SemanticReferenceMaskManifest,
    list[RegisteredSemanticMaskArtifact],
    str,
    str,
]:
    """Validate one manifest against current canonical geometry and reference evidence."""

    manifest_path = _require_safe_job_path(root, manifest_path, "semantic manifest")
    if _is_link_like(manifest_path) or not file_exists(manifest_path):
        raise FileNotFoundError(manifest_path)
    manifest_bytes = _read_bytes(manifest_path)
    manifest_hash = _sha256_bytes(manifest_bytes)
    if expected_manifest_sha256 is not None and manifest_hash != expected_manifest_sha256:
        raise StaleSemanticMaskEvidence(
            "semantic reference mask manifest changed before registration"
        )
    manifest = SemanticReferenceMaskManifest.model_validate_json(manifest_bytes)
    if manifest.job_id != job_id:
        raise ValueError("semantic reference mask manifest belongs to another job")
    if manifest.scene_spec_path != "analysis/scene_spec.json":
        raise ValueError("semantic mask manifest must bind the canonical SceneSpec path")
    scene_spec_path = _resolve_job_path(
        root,
        "analysis/scene_spec.json",
        "canonical SceneSpec",
    )
    if _is_link_like(scene_spec_path) or not file_exists(scene_spec_path):
        raise FileNotFoundError(scene_spec_path)
    scene_spec_bytes = _read_bytes(scene_spec_path)
    scene_spec_hash = _sha256_bytes(scene_spec_bytes)
    if manifest.scene_spec_sha256 != scene_spec_hash:
        raise StaleSemanticMaskEvidence(
            "semantic mask manifest does not match the current SceneSpec"
        )
    spec = SceneSpec.model_validate_json(scene_spec_bytes)
    if spec.job_id != job_id:
        raise ValueError("canonical SceneSpec belongs to another job")
    reference_path, reference_relative, reference_hash = _primary_reference(root, job_id)
    if (
        _resolve_job_path(root, manifest.reference_path, "manifest reference path")
        != reference_path
        or manifest.reference_path != reference_relative
        or manifest.reference_sha256 != reference_hash
    ):
        raise StaleSemanticMaskEvidence(
            "semantic mask manifest does not match the current primary reference"
        )
    with open_image(reference_path) as opened:
        reference_size = opened.size

    objects = {item.id: item for item in spec.objects}
    sources = {item.id: item for item in spec.sources}
    registration_mask_root = _resolve_job_path(
        root,
        (
            f"analysis/masks/registrations/{registration_id}/masks"
            if registration_id is not None
            else "analysis/masks"
        ),
        "semantic mask ownership root",
    )
    artifacts: list[RegisteredSemanticMaskArtifact] = []
    for record in manifest.masks:
        _validate_record_evidence(
            root,
            record,
            objects=objects,
            sources=sources,
            reference_path=reference_path,
        )
        mask_path = _resolve_job_path(root, record.path, "semantic mask path")
        try:
            mask_path.relative_to(registration_mask_root)
        except ValueError as exc:
            raise ValueError(
                "registered mask path must stay inside the exact registration masks directory"
            ) from exc
        if _is_link_like(mask_path) or not file_exists(mask_path):
            raise FileNotFoundError(mask_path)
        if sha256_file(mask_path) != record.sha256:
            raise StaleSemanticMaskEvidence(
                f"semantic reference mask changed: {record.semantic_id}"
            )
        _validate_mask_image(mask_path, reference_size)
        artifacts.append(
            RegisteredSemanticMaskArtifact(
                semantic_id=record.semantic_id,
                source_id=record.source_id,
                path=record.path,
                sha256=record.sha256,
            )
        )
    return manifest, artifacts, scene_spec_hash, reference_hash


def _validate_record_evidence(
    root: Path,
    record: SemanticReferenceMaskRecord,
    *,
    objects: dict[str, ObjectSpec],
    sources: dict[str, SourceSpec],
    reference_path: Path,
) -> None:
    """Require each mask to name one observed object in the exact primary source."""

    item = objects.get(record.semantic_id)
    source = sources.get(record.source_id)
    if item is None:
        raise ValueError(f"semantic mask names an unknown object: {record.semantic_id}")
    if source is None or source.kind != "reference":
        raise ValueError(f"semantic mask source is not the primary reference: {record.source_id}")
    source_path = _resolve_job_path(
        root,
        str(source.path),
        "SceneSpec source path",
    )
    if source_path != reference_path:
        raise ValueError(f"semantic mask source path is not primary: {record.source_id}")
    if not any(
        entry.source_id == record.source_id and entry.status == "observed"
        for entry in item.evidence
    ):
        raise ValueError(
            f"semantic mask lacks observed object evidence: {record.semantic_id}"
        )


def _archive_previous_manifest(
    root: Path,
    canonical_path: Path,
) -> tuple[str | None, str | None]:
    """Preserve a parseable previous canonical manifest under its content hash."""

    canonical_path = _require_safe_job_path(
        root,
        canonical_path,
        "canonical semantic manifest",
    )
    if not file_exists(canonical_path):
        return None, None
    if _is_link_like(canonical_path):
        raise ValueError("canonical semantic manifest must not be link-like")
    previous_bytes = _read_bytes(canonical_path)
    previous_hash = sha256_file(canonical_path)
    previous = SemanticReferenceMaskManifest.model_validate_json(
        previous_bytes.decode("utf-8")
    )
    if previous.job_id != root.name:
        raise ValueError("existing canonical semantic manifest belongs to another job")
    relative = Path("history") / "qa_semantic_masks" / f"{previous_hash}.json"
    history_path = root / relative
    history_path = _require_safe_job_path(root, history_path, "semantic mask history")
    if _path_exists(history_path):
        if not file_exists(history_path) or sha256_file(history_path) != previous_hash:
            raise RuntimeError("semantic mask history path conflicts with its hash")
    else:
        _write_bytes_atomic(root, history_path, previous_bytes)
    return previous_hash, relative.as_posix()


def _load_receipt(
    root: Path,
    path: Path,
) -> tuple[SemanticReferenceMaskPromotionReceipt, str]:
    """Load and hash one safe immutable promotion-receipt byte snapshot."""

    path = _require_safe_job_path(root, path, "semantic mask promotion receipt")
    if _is_link_like(path) or not file_exists(path):
        raise FileNotFoundError(path)
    content = _read_bytes(path)
    return (
        SemanticReferenceMaskPromotionReceipt.model_validate_json(content),
        _sha256_bytes(content),
    )


def _require_receipt_matches_candidate(
    root: Path,
    receipt: SemanticReferenceMaskPromotionReceipt,
    *,
    registration_id: str,
    candidate_hash: str,
    manifest: SemanticReferenceMaskManifest,
    artifacts: list[RegisteredSemanticMaskArtifact],
    scene_hash: str,
    reference_hash: str,
) -> None:
    """Reject any prior journal whose exact recomputed registration inputs differ."""

    expected_artifacts = [item.model_dump(mode="json") for item in artifacts]
    if (
        receipt.job_id != root.name
        or receipt.registration_id != registration_id
        or receipt.candidate_manifest_sha256 != candidate_hash
        or receipt.canonical_manifest_sha256 != candidate_hash
        or receipt.scene_spec_sha256 != scene_hash
        or receipt.reference_path != manifest.reference_path
        or receipt.reference_sha256 != reference_hash
        or [item.model_dump(mode="json") for item in receipt.masks]
        != expected_artifacts
    ):
        raise RuntimeError("semantic mask promotion journal differs from current inputs")
    if receipt.history_path is not None:
        history_path = _resolve_job_path(
            root,
            receipt.history_path,
            "semantic mask history path",
        )
        if (
            not file_exists(history_path)
            or sha256_file(history_path) != receipt.previous_canonical_sha256
        ):
            raise RuntimeError("semantic mask promotion history is missing or changed")


def register_job_semantic_reference_masks(
    job_id: str,
    registration_id: str,
    *,
    manifest_sha256: str,
) -> SemanticReferenceMaskPromotionReceipt:
    """Validate and atomically promote explicit semantic reference-mask evidence."""

    selected_registration = _validate_registration_id(registration_id)
    expected_hash = _validate_sha256(manifest_sha256)
    root = Path(os.path.abspath(os.fspath(job_dir(job_id).expanduser())))
    root = _require_safe_job_path(root, root, "semantic mask job root")
    if not _directory_exists(root):
        raise FileNotFoundError(root)
    owner = f"semantic-mask-{uuid4().hex[:16]}"

    with canonical_scene_spec_write_lock(job_id, owner):
        registration_root = _resolve_job_path(
            root,
            f"analysis/masks/registrations/{selected_registration}",
            "semantic mask registration root",
        )
        candidate_path = _require_safe_job_path(
            root,
            registration_root / "manifest.json",
            "semantic mask candidate",
        )
        receipt_path = _require_safe_job_path(
            root,
            registration_root / "promotion_receipt.json",
            "semantic mask receipt",
        )
        pending_path = _require_safe_job_path(
            root,
            registration_root / ".promotion.pending",
            "semantic mask pending receipt",
        )
        canonical_path = _resolve_job_path(
            root,
            CANONICAL_MANIFEST,
            "canonical semantic manifest",
        )
        manifest, artifacts, scene_hash, reference_hash = _validate_manifest_evidence(
            root,
            job_id,
            candidate_path,
            registration_id=selected_registration,
            expected_manifest_sha256=expected_hash,
        )
        if file_exists(receipt_path):
            receipt, receipt_hash = _load_receipt(root, receipt_path)
            _require_receipt_matches_candidate(
                root,
                receipt,
                registration_id=selected_registration,
                candidate_hash=expected_hash,
                manifest=manifest,
                artifacts=artifacts,
                scene_hash=scene_hash,
                reference_hash=reference_hash,
            )
            if (
                not file_exists(canonical_path)
                or sha256_file(canonical_path) != receipt.canonical_manifest_sha256
            ):
                raise RuntimeError(
                    "semantic mask registration receipt is immutable and no longer current"
                )
            if sha256_file(receipt_path) != receipt_hash:
                raise RuntimeError(
                    "semantic mask registration receipt changed during validation"
                )
            return receipt

        pending: SemanticReferenceMaskPromotionReceipt | None = None
        if file_exists(pending_path):
            pending, pending_hash = _load_receipt(root, pending_path)
            _require_receipt_matches_candidate(
                root,
                pending,
                registration_id=selected_registration,
                candidate_hash=expected_hash,
                manifest=manifest,
                artifacts=artifacts,
                scene_hash=scene_hash,
                reference_hash=reference_hash,
            )
            if sha256_file(pending_path) != pending_hash:
                raise RuntimeError(
                    "semantic mask pending receipt changed during validation"
                )
            if file_exists(canonical_path) and sha256_file(canonical_path) == expected_hash:
                _replace_job_file(
                    root,
                    pending_path,
                    receipt_path,
                    "semantic mask pending-receipt recovery",
                )
                return pending

        previous_hash, history_path = _archive_previous_manifest(root, canonical_path)
        if pending is not None and (
            pending.previous_canonical_sha256 != previous_hash
            or pending.history_path != history_path
        ):
            raise RuntimeError("incomplete semantic mask promotion changed its baseline")
        receipt = pending or SemanticReferenceMaskPromotionReceipt(
            job_id=job_id,
            registration_id=selected_registration,
            candidate_manifest_path=_job_relative(root, candidate_path),
            candidate_manifest_sha256=expected_hash,
            canonical_manifest_sha256=expected_hash,
            previous_canonical_sha256=previous_hash,
            history_path=history_path,
            scene_spec_sha256=scene_hash,
            reference_path=manifest.reference_path,
            reference_sha256=reference_hash,
            masks=artifacts,
            promoted_at=datetime.now(UTC),
        )
        if pending is None:
            _write_json_atomic(root, pending_path, receipt.model_dump(mode="json"))
        _write_bytes_atomic(root, canonical_path, _read_bytes(candidate_path))
        _validate_manifest_evidence(
            root,
            job_id,
            candidate_path,
            registration_id=selected_registration,
            expected_manifest_sha256=expected_hash,
        )
        if sha256_file(canonical_path) != expected_hash:
            raise RuntimeError("canonical semantic mask manifest promotion hash mismatch")
        _replace_job_file(
            root,
            pending_path,
            receipt_path,
            "semantic mask promotion receipt",
        )
        return receipt


def _matching_receipts(
    root: Path,
    canonical_hash: str,
) -> tuple[
    list[tuple[Path, SemanticReferenceMaskPromotionReceipt, str]],
    list[str],
]:
    """Find strict receipts that claim one current canonical manifest hash."""

    try:
        registrations = _resolve_job_path(
            root,
            "analysis/masks/registrations",
            "semantic mask registrations",
        )
    except ValueError as exc:
        return [], [str(exc)]
    matches: list[tuple[Path, SemanticReferenceMaskPromotionReceipt, str]] = []
    issues: list[str] = []
    if not _directory_exists(registrations):
        return matches, issues
    if _is_link_like(registrations):
        return matches, ["Semantic mask registrations directory is link-like."]
    with os.scandir(native_io_path(registrations)) as entries:
        children = [registrations / entry.name for entry in entries]
    for child in sorted(children, key=lambda item: item.name):
        try:
            child = _require_safe_job_path(
                root,
                child,
                "semantic mask registration directory",
            )
        except ValueError as exc:
            issues.append(f"Unsafe semantic mask registration {child.name}: {exc}")
            continue
        if _is_link_like(child):
            issues.append(
                f"Link-like semantic mask registration {child.name} was rejected."
            )
            continue
        if not _directory_exists(child):
            continue
        try:
            receipt_path = _require_safe_job_path(
                root,
                child / "promotion_receipt.json",
                "semantic mask promotion receipt",
            )
            if not file_exists(receipt_path):
                continue
            receipt, receipt_hash = _load_receipt(root, receipt_path)
        except (OSError, ValueError) as exc:
            issues.append(
                f"Unreadable semantic mask receipt {child.name}: {type(exc).__name__}."
            )
            continue
        if receipt.registration_id != child.name:
            issues.append(
                f"Semantic mask receipt directory {child.name} does not match its registration ID."
            )
            continue
        if receipt.canonical_manifest_sha256 == canonical_hash:
            matches.append((receipt_path, receipt, receipt_hash))
    return matches, issues


def get_job_semantic_reference_mask_status(
    job_id: str,
) -> SemanticReferenceMaskRegistryStatus:
    """Inspect current semantic-mask registration evidence without modifying it."""

    root = Path(os.path.abspath(os.fspath(job_dir(job_id).expanduser())))
    try:
        root = _require_safe_job_path(root, root, "semantic mask job root")
    except ValueError as exc:
        return SemanticReferenceMaskRegistryStatus(
            job_id=job_id,
            status="invalid",
            ok=False,
            issues=[str(exc)],
        )
    try:
        canonical = _resolve_job_path(
            root,
            CANONICAL_MANIFEST,
            "canonical semantic manifest",
        )
    except ValueError as exc:
        return SemanticReferenceMaskRegistryStatus(
            job_id=job_id,
            status="invalid",
            ok=False,
            issues=[str(exc)],
        )
    if not file_exists(canonical):
        return SemanticReferenceMaskRegistryStatus(
            job_id=job_id,
            status="absent",
            ok=False,
        )
    canonical_hash = sha256_file(canonical)
    try:
        manifest, _artifacts, _scene_hash, _reference_hash = (
            _validate_manifest_evidence(
                root,
                job_id,
                canonical,
                registration_id=None,
                expected_manifest_sha256=canonical_hash,
            )
        )
    except StaleSemanticMaskEvidence as exc:
        return SemanticReferenceMaskRegistryStatus(
            job_id=job_id,
            status="stale",
            ok=False,
            canonical_manifest_path=CANONICAL_MANIFEST,
            canonical_manifest_sha256=canonical_hash,
            issues=[str(exc)],
        )
    except (OSError, ValueError) as exc:
        return SemanticReferenceMaskRegistryStatus(
            job_id=job_id,
            status="invalid",
            ok=False,
            canonical_manifest_path=CANONICAL_MANIFEST,
            canonical_manifest_sha256=canonical_hash,
            issues=[f"{type(exc).__name__}: {exc}"],
        )

    matches, receipt_issues = _matching_receipts(root, canonical_hash)
    if not matches:
        return SemanticReferenceMaskRegistryStatus(
            job_id=job_id,
            status="legacy_current" if not receipt_issues else "invalid",
            ok=not receipt_issues,
            canonical_manifest_path=CANONICAL_MANIFEST,
            canonical_manifest_sha256=canonical_hash,
            mask_count=len(manifest.masks),
            issues=receipt_issues,
        )
    if len(matches) != 1 or receipt_issues:
        return SemanticReferenceMaskRegistryStatus(
            job_id=job_id,
            status="invalid",
            ok=False,
            canonical_manifest_path=CANONICAL_MANIFEST,
            canonical_manifest_sha256=canonical_hash,
            mask_count=len(manifest.masks),
            issues=[
                *receipt_issues,
                "Current semantic manifest does not have exactly one valid receipt.",
            ],
        )
    receipt_path, receipt, receipt_hash = matches[0]
    try:
        receipt_relative = _job_relative(root, receipt_path)
    except (OSError, ValueError) as exc:
        return SemanticReferenceMaskRegistryStatus(
            job_id=job_id,
            status="invalid",
            ok=False,
            canonical_manifest_path=CANONICAL_MANIFEST,
            canonical_manifest_sha256=canonical_hash,
            mask_count=len(manifest.masks),
            issues=[f"{type(exc).__name__}: {exc}"],
        )
    try:
        candidate_manifest, candidate_artifacts, scene_hash, reference_hash = (
            _validate_manifest_evidence(
                root,
                job_id,
                root / receipt.candidate_manifest_path,
                registration_id=receipt.registration_id,
                expected_manifest_sha256=receipt.candidate_manifest_sha256,
            )
        )
        _require_receipt_matches_candidate(
            root,
            receipt,
            registration_id=receipt.registration_id,
            candidate_hash=receipt.candidate_manifest_sha256,
            manifest=candidate_manifest,
            artifacts=candidate_artifacts,
            scene_hash=scene_hash,
            reference_hash=reference_hash,
        )
        if [item.model_dump() for item in receipt.masks] != [
            RegisteredSemanticMaskArtifact(
                semantic_id=item.semantic_id,
                source_id=item.source_id,
                path=item.path,
                sha256=item.sha256,
            ).model_dump()
            for item in manifest.masks
        ]:
            raise ValueError("promotion receipt mask inventory differs from canonical")
        if sha256_file(receipt_path) != receipt_hash:
            raise StaleSemanticMaskEvidence(
                "semantic mask promotion receipt changed during status inspection"
            )
    except StaleSemanticMaskEvidence as exc:
        return SemanticReferenceMaskRegistryStatus(
            job_id=job_id,
            status="stale",
            ok=False,
            registration_id=receipt.registration_id,
            canonical_manifest_path=CANONICAL_MANIFEST,
            canonical_manifest_sha256=canonical_hash,
            promotion_receipt_path=receipt_relative,
            promotion_receipt_sha256=receipt_hash,
            mask_count=len(manifest.masks),
            issues=[str(exc)],
        )
    except (OSError, ValueError) as exc:
        return SemanticReferenceMaskRegistryStatus(
            job_id=job_id,
            status="invalid",
            ok=False,
            registration_id=receipt.registration_id,
            canonical_manifest_path=CANONICAL_MANIFEST,
            canonical_manifest_sha256=canonical_hash,
            promotion_receipt_path=receipt_relative,
            promotion_receipt_sha256=receipt_hash,
            mask_count=len(manifest.masks),
            issues=[f"{type(exc).__name__}: {exc}"],
        )
    return SemanticReferenceMaskRegistryStatus(
        job_id=job_id,
        status="current",
        ok=True,
        registration_id=receipt.registration_id,
        canonical_manifest_path=CANONICAL_MANIFEST,
        canonical_manifest_sha256=canonical_hash,
        promotion_receipt_path=receipt_relative,
        promotion_receipt_sha256=receipt_hash,
        mask_count=len(manifest.masks),
    )
