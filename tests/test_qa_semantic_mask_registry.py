from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa import semantic_mask_registry as registry
from codex_blender_modeler.qa.diagnostic_models import (
    SemanticReferenceMaskManifest,
    SemanticReferenceMaskRecord,
)
from codex_blender_modeler.qa.semantic_mask_registry import (
    get_job_semantic_reference_mask_status,
    register_job_semantic_reference_masks,
)
from codex_blender_modeler.workspace import create_job, native_io_path, sha256_file

JOB_ID = "semantic_mask_registry_test"


def _write_reference(path: Path, size: tuple[int, int] = (64, 64)) -> None:
    """Write one deterministic reference image for isolated registry tests."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    image = Image.new("RGB", size, (25, 25, 25))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, size[0] - 17, size[1] - 17), fill=(220, 220, 220))
    image.save(native_io_path(path), format="PNG")


def _write_mask(
    path: Path,
    *,
    size: tuple[int, int] = (64, 64),
    fill: int = 255,
) -> None:
    """Write one binary rectangular mask into a registration-owned directory."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    image = Image.new("L", size, 0)
    draw = ImageDraw.Draw(image)
    inset_x = max(1, size[0] // 4)
    inset_y = max(1, size[1] // 4)
    draw.rectangle(
        (inset_x, inset_y, size[0] - inset_x - 1, size[1] - inset_y - 1),
        fill=fill,
    )
    image.save(native_io_path(path), format="PNG")


def _scene_spec(
    *,
    job_id: str = JOB_ID,
    evidence_status: str = "observed",
) -> SceneSpec:
    """Create one canonical SceneSpec with a single evidence-backed primary object."""

    return SceneSpec.model_validate(
        {
            "job_id": job_id,
            "mode": "concept",
            "nominal_scene_size": [2.0, 1.0, 1.0],
            "sources": [
                {
                    "id": "reference",
                    "path": "input/reference.png",
                    "kind": "reference",
                }
            ],
            "materials": [
                {
                    "id": "mat.body",
                    "name": "Body",
                    "base_color": [0.5, 0.5, 0.5, 1.0],
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
                        "dimensions": [2.0, 1.0, 1.0],
                    },
                    "material_id": "mat.body",
                    "tags": ["qa_role:primary"],
                    "evidence": [
                        {
                            "source_id": "reference",
                            "bbox_norm": [0.2, 0.2, 0.8, 0.8],
                            "status": evidence_status,
                            "confidence": 0.95,
                        }
                    ],
                }
            ],
            "camera": {
                "projection": "PERSP",
                "location": [3.0, -5.0, 2.0],
                "target": [0.0, 0.0, 0.0],
                "focal_length_mm": 50.0,
                "ortho_scale": 4.0,
                "resolution": [64, 64],
            },
        }
    )


def _seed_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    job_id: str = JOB_ID,
    evidence_status: str = "observed",
    workspace_name: str = "workspaces",
) -> Path:
    """Create one isolated job whose canonical inputs may be fingerprinted safely."""

    workspace = tmp_path / workspace_name
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "reference.png"
    _write_reference(reference)
    create_job(job_id, reference, "concept", [])
    root = workspace / job_id
    scene_path = root / "analysis" / "scene_spec.json"
    registry._write_bytes_atomic(
        root,
        scene_path,
        (
            _scene_spec(job_id=job_id, evidence_status=evidence_status)
            .model_dump_json(indent=2)
            + "\n"
        ).encode("utf-8"),
    )
    return root


def _write_candidate(
    root: Path,
    registration_id: str,
    *,
    semantic_id: str = "asset.body",
    source_id: str = "reference",
    mask_size: tuple[int, int] = (64, 64),
    mask_fill: int = 255,
) -> tuple[Path, Path]:
    """Write one exact job-owned candidate manifest and its declared PNG mask."""

    registration_root = (
        root / "analysis" / "masks" / "registrations" / registration_id
    )
    mask_path = registration_root / "masks" / f"{semantic_id}.png"
    _write_mask(mask_path, size=mask_size, fill=mask_fill)
    manifest = SemanticReferenceMaskManifest(
        job_id=root.name,
        reference_path="input/reference.png",
        reference_sha256=sha256_file(root / "input" / "reference.png"),
        scene_spec_sha256=sha256_file(root / "analysis" / "scene_spec.json"),
        masks=[
            SemanticReferenceMaskRecord(
                semantic_id=semantic_id,
                source_id=source_id,
                path=mask_path.relative_to(root).as_posix(),
                sha256=sha256_file(mask_path),
                confidence=0.95,
            )
        ],
        generated_at=datetime(2026, 8, 4, tzinfo=UTC),
        limitations=["Pixel semantics still require visual review."],
    )
    manifest_path = registration_root / "manifest.json"
    registry._write_bytes_atomic(
        root,
        manifest_path,
        (manifest.model_dump_json(indent=2) + "\n").encode("utf-8"),
    )
    return manifest_path, mask_path


def test_registers_exact_manifest_without_changing_canonical_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Promote only QA evidence while preserving source and SceneSpec bytes exactly."""

    root = _seed_job(tmp_path, monkeypatch)
    manifest_path, _mask_path = _write_candidate(root, "manual-001")
    scene_hash = sha256_file(root / "analysis" / "scene_spec.json")
    reference_hash = sha256_file(root / "input" / "reference.png")

    receipt = register_job_semantic_reference_masks(
        JOB_ID,
        "manual-001",
        manifest_sha256=sha256_file(manifest_path),
    )

    canonical = root / "analysis" / "masks" / "semantic_manifest.json"
    assert canonical.read_bytes() == manifest_path.read_bytes()
    assert receipt.canonical_manifest_sha256 == sha256_file(canonical)
    assert (manifest_path.parent / "promotion_receipt.json").is_file()
    assert sha256_file(root / "analysis" / "scene_spec.json") == scene_hash
    assert sha256_file(root / "input" / "reference.png") == reference_hash
    status = get_job_semantic_reference_mask_status(JOB_ID)
    assert status.status == "current"
    assert status.ok is True
    assert status.registration_id == "manual-001"
    assert status.mask_count == 1


def test_wrong_exact_manifest_hash_fails_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a stale caller fingerprint before creating canonical evidence."""

    root = _seed_job(tmp_path, monkeypatch)
    _write_candidate(root, "manual-001")

    with pytest.raises(ValueError, match="manifest changed"):
        register_job_semantic_reference_masks(
            JOB_ID,
            "manual-001",
            manifest_sha256="0" * 64,
        )

    assert not (root / "analysis" / "masks" / "semantic_manifest.json").exists()
    assert not (
        root
        / "analysis"
        / "masks"
        / "registrations"
        / "manual-001"
        / "promotion_receipt.json"
    ).exists()


@pytest.mark.parametrize(
    ("semantic_id", "source_id", "evidence_status", "message"),
    [
        ("asset.unknown", "reference", "observed", "unknown object"),
        ("asset.body", "other", "observed", "source is not"),
        ("asset.body", "reference", "inferred", "lacks observed"),
    ],
)
def test_registration_requires_observed_primary_semantic_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    semantic_id: str,
    source_id: str,
    evidence_status: str,
    message: str,
) -> None:
    """Reject masks that are not backed by an observed canonical semantic object."""

    root = _seed_job(tmp_path, monkeypatch, evidence_status=evidence_status)
    manifest_path, _mask_path = _write_candidate(
        root,
        "manual-001",
        semantic_id=semantic_id,
        source_id=source_id,
    )

    with pytest.raises(ValueError, match=message):
        register_job_semantic_reference_masks(
            JOB_ID,
            "manual-001",
            manifest_sha256=sha256_file(manifest_path),
        )


@pytest.mark.parametrize(
    ("mask_size", "mask_fill", "message"),
    [
        ((32, 32), 255, "resolution"),
        ((64, 64), 127, "binary and nonempty"),
        ((64, 64), 0, "binary and nonempty"),
    ],
)
def test_registration_rejects_invalid_mask_pixels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mask_size: tuple[int, int],
    mask_fill: int,
    message: str,
) -> None:
    """Require exact-size binary nonempty pixels without synthesizing a replacement."""

    root = _seed_job(tmp_path, monkeypatch)
    manifest_path, _mask_path = _write_candidate(
        root,
        "manual-001",
        mask_size=mask_size,
        mask_fill=mask_fill,
    )

    with pytest.raises(ValueError, match=message):
        register_job_semantic_reference_masks(
            JOB_ID,
            "manual-001",
            manifest_sha256=sha256_file(manifest_path),
        )


def test_registration_rejects_mask_outside_exact_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep all accepted masks inside the owning immutable registration directory."""

    root = _seed_job(tmp_path, monkeypatch)
    manifest_path, mask_path = _write_candidate(root, "manual-001")
    outside = root / "analysis" / "masks" / "shared.png"
    outside.write_bytes(mask_path.read_bytes())
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["masks"][0]["path"] = "analysis/masks/shared.png"
    payload["masks"][0]["sha256"] = sha256_file(outside)
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exact registration"):
        register_job_semantic_reference_masks(
            JOB_ID,
            "manual-001",
            manifest_sha256=sha256_file(manifest_path),
        )


def test_stale_scene_spec_binding_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require a new candidate when canonical geometry changes after mask authoring."""

    root = _seed_job(tmp_path, monkeypatch)
    manifest_path, _mask_path = _write_candidate(root, "manual-001")
    scene_path = root / "analysis" / "scene_spec.json"
    payload = json.loads(scene_path.read_text(encoding="utf-8"))
    payload["nominal_scene_size"] = [3.0, 1.0, 1.0]
    scene_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="current SceneSpec"):
        register_job_semantic_reference_masks(
            JOB_ID,
            "manual-001",
            manifest_sha256=sha256_file(manifest_path),
        )


def test_noncanonical_scene_spec_path_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an alias path even when it happens to contain identical SceneSpec bytes."""

    root = _seed_job(tmp_path, monkeypatch)
    manifest_path, _mask_path = _write_candidate(root, "manual-001")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["scene_spec_path"] = "analysis/scene_spec.alias.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="canonical SceneSpec path"):
        register_job_semantic_reference_masks(
            JOB_ID,
            "manual-001",
            manifest_sha256=sha256_file(manifest_path),
        )


def test_stale_primary_reference_binding_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject registration after immutable primary-reference bytes are changed."""

    root = _seed_job(tmp_path, monkeypatch)
    manifest_path, _mask_path = _write_candidate(root, "manual-001")
    (root / "input" / "reference.png").write_bytes(b"tampered reference")

    with pytest.raises(ValueError, match="primary reference changed"):
        register_job_semantic_reference_masks(
            JOB_ID,
            "manual-001",
            manifest_sha256=sha256_file(manifest_path),
        )


def test_second_registration_archives_previous_canonical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve exact prior manifest bytes before selecting a newer registration."""

    root = _seed_job(tmp_path, monkeypatch)
    first, _first_mask = _write_candidate(root, "manual-001")
    first_receipt = register_job_semantic_reference_masks(
        JOB_ID,
        "manual-001",
        manifest_sha256=sha256_file(first),
    )
    second, _second_mask = _write_candidate(root, "manual-002")

    second_receipt = register_job_semantic_reference_masks(
        JOB_ID,
        "manual-002",
        manifest_sha256=sha256_file(second),
    )

    assert second_receipt.previous_canonical_sha256 == (
        first_receipt.canonical_manifest_sha256
    )
    assert second_receipt.history_path is not None
    history = root / second_receipt.history_path
    assert history.read_bytes() == first.read_bytes()
    assert sha256_file(root / "analysis" / "masks" / "semantic_manifest.json") == (
        second_receipt.canonical_manifest_sha256
    )


def test_interrupted_promotion_recovers_from_pending_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume an exact pending journal without weakening candidate fingerprints."""

    root = _seed_job(tmp_path, monkeypatch)
    manifest_path, _mask_path = _write_candidate(root, "manual-001")
    canonical = root / "analysis" / "masks" / "semantic_manifest.json"
    original_write = registry._write_bytes_atomic
    failed_once = False

    def interrupt_canonical(owner: Path, path: Path, content: bytes) -> None:
        """Simulate one crash after the pending journal but before canonical publish."""

        nonlocal failed_once
        if path == canonical and not failed_once:
            failed_once = True
            raise RuntimeError("simulated interrupted promotion")
        original_write(owner, path, content)

    monkeypatch.setattr(registry, "_write_bytes_atomic", interrupt_canonical)
    with pytest.raises(RuntimeError, match="simulated interrupted"):
        register_job_semantic_reference_masks(
            JOB_ID,
            "manual-001",
            manifest_sha256=sha256_file(manifest_path),
        )
    pending = manifest_path.parent / ".promotion.pending"
    assert pending.is_file()
    assert not canonical.exists()

    monkeypatch.setattr(registry, "_write_bytes_atomic", original_write)
    receipt = register_job_semantic_reference_masks(
        JOB_ID,
        "manual-001",
        manifest_sha256=sha256_file(manifest_path),
    )

    assert receipt.status == "promoted"
    assert not pending.exists()
    assert (manifest_path.parent / "promotion_receipt.json").is_file()


def test_status_detects_registered_mask_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report stale evidence instead of silently accepting changed mask pixels."""

    root = _seed_job(tmp_path, monkeypatch)
    manifest_path, mask_path = _write_candidate(root, "manual-001")
    register_job_semantic_reference_masks(
        JOB_ID,
        "manual-001",
        manifest_sha256=sha256_file(manifest_path),
    )
    mask_path.write_bytes(b"tampered")

    status = get_job_semantic_reference_mask_status(JOB_ID)

    assert status.status == "stale"
    assert status.ok is False
    assert "changed" in " ".join(status.issues)


def test_status_accepts_valid_legacy_canonical_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep pre-registry manifests readable without inventing a promotion receipt."""

    root = _seed_job(tmp_path, monkeypatch)
    manifest_path, mask_path = _write_candidate(root, "manual-001")
    legacy_mask = root / "analysis" / "masks" / "legacy.body.png"
    legacy_mask.parent.mkdir(parents=True, exist_ok=True)
    legacy_mask.write_bytes(mask_path.read_bytes())
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["masks"][0]["path"] = legacy_mask.relative_to(root).as_posix()
    payload["masks"][0]["sha256"] = sha256_file(legacy_mask)
    canonical = root / "analysis" / "masks" / "semantic_manifest.json"
    canonical.write_text(json.dumps(payload), encoding="utf-8")

    status = get_job_semantic_reference_mask_status(JOB_ID)

    assert status.status == "legacy_current"
    assert status.ok is True
    assert status.registration_id is None


def test_registration_rejects_a_link_like_masks_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject parent-directory indirection before reading or publishing evidence."""

    root = _seed_job(tmp_path, monkeypatch)
    manifest_path, _mask_path = _write_candidate(root, "manual-001")
    masks_root = root / "analysis" / "masks"
    original = registry._is_link_like

    def report_masks_link(path: Path) -> bool:
        """Model one junction-like ancestor without requiring OS symlink privileges."""

        return path == masks_root or original(path)

    monkeypatch.setattr(registry, "_is_link_like", report_masks_link)
    with pytest.raises(ValueError, match="link-like"):
        register_job_semantic_reference_masks(
            JOB_ID,
            "manual-001",
            manifest_sha256=sha256_file(manifest_path),
        )
    assert not (root / "analysis" / "masks" / "semantic_manifest.json").is_file()


def test_maximum_ids_round_trip_through_extended_length_registry_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read, publish, inspect, and detect tampering beyond the Windows MAX_PATH boundary."""

    job_id = "j" * 64
    registration_id = "r" * 96
    root = _seed_job(
        tmp_path,
        monkeypatch,
        job_id=job_id,
        workspace_name="w",
    )
    manifest_path, mask_path = _write_candidate(root, registration_id)
    receipt_path = manifest_path.parent / "promotion_receipt.json"
    assert len(os.path.abspath(os.fspath(mask_path))) > 260
    assert len(os.path.abspath(os.fspath(receipt_path))) > 260
    if os.name == "nt":
        assert native_io_path(mask_path).startswith("\\\\?\\")

    receipt = register_job_semantic_reference_masks(
        job_id,
        registration_id,
        manifest_sha256=sha256_file(manifest_path),
    )
    canonical = root / "analysis" / "masks" / "semantic_manifest.json"
    assert registry._read_bytes(canonical) == registry._read_bytes(manifest_path)
    assert receipt.registration_id == registration_id
    assert json.loads(registry._read_text(receipt_path))["registration_id"] == (
        registration_id
    )

    current = get_job_semantic_reference_mask_status(job_id)
    assert current.status == "current"
    assert current.ok is True
    assert current.registration_id == registration_id
    assert current.mask_count == 1

    repeated = register_job_semantic_reference_masks(
        job_id,
        registration_id,
        manifest_sha256=sha256_file(manifest_path),
    )
    assert repeated == receipt

    registry._write_bytes_atomic(root, mask_path, b"tampered long-path mask")
    stale = get_job_semantic_reference_mask_status(job_id)
    assert stale.status == "stale"
    assert stale.ok is False


def test_atomic_publication_rechecks_existing_target_after_temporary_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a target that becomes link-like after the temporary file is written."""

    root = tmp_path / "job"
    target = root / "analysis" / "state.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original")
    original_is_link_like = registry._is_link_like

    def report_late_target_link(path: Path) -> bool:
        """Model a target-link swap during the narrow pre-replace publication window."""

        temporary_exists = any(
            entry.name.startswith(".semantic-mask-")
            for entry in os.scandir(native_io_path(target.parent))
        )
        if path == target and temporary_exists:
            return True
        return original_is_link_like(path)

    monkeypatch.setattr(registry, "_is_link_like", report_late_target_link)
    with pytest.raises(ValueError, match="link-like"):
        registry._write_bytes_atomic(root, target, b"replacement")

    assert target.read_bytes() == b"original"
    assert not any(
        entry.name.startswith(".semantic-mask-")
        for entry in os.scandir(native_io_path(target.parent))
    )
