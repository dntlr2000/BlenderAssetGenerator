"""Focused tests for fixed promoted-material neutral preview evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from codex_blender_modeler.autonomy_v2 import codex_image_material_preview_service as service
from codex_blender_modeler.autonomy_v2.models import AQV2Artifact
from codex_blender_modeler.blender_artifacts import safe_artifact_name, write_json_atomic
from codex_blender_modeler.codex_imagegen.artifacts import artifact_for_codex_image

NOW = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)


def _fixture(root: Path) -> tuple[object, object]:
    """Create minimal exact receipt and blend artifacts for a mocked Blender render."""

    receipt_path = root / "production" / "material_phase" / "receipt.json"
    blend_path = root / "production" / "material_phase" / "authoring.blend"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(b'{"fixture":"material-phase-receipt"}\n')
    blend_path.write_bytes(b"BLENDER-v300-fixture")
    receipt_artifact = artifact_for_codex_image(
        root,
        receipt_path,
        artifact_id="material-receipt",
        kind="material-phase-receipt",
        media_type="application/json",
    )
    blend_artifact = artifact_for_codex_image(
        root,
        blend_path,
        artifact_id="authoring-blend",
        kind="authoring-blend-snapshot",
        media_type="application/x-blender",
    )
    receipt = SimpleNamespace(
        job_id="preview-job",
        workflow_id="workflow-preview",
        dispatch_id="dispatch-preview",
        session_id="session-preview",
        authoring_blend_snapshot=AQV2Artifact(
            artifact_id=blend_artifact.artifact_id,
            kind=blend_artifact.kind,
            path=blend_artifact.path,
            sha256=blend_artifact.sha256,
            byte_size=blend_artifact.byte_size,
        ),
    )
    return receipt_artifact, receipt


def _fake_blender(
    script_name: str,
    args: list[str],
    blend_file: Path | None = None,
    **_: object,
) -> object:
    """Publish the fixed manifest shape expected from the repository Blender script."""

    assert script_name == "render_material_swatches.py"
    assert blend_file is not None
    output_dir = Path(args[args.index("--output-dir") + 1])
    manifest = Path(args[args.index("--manifest") + 1])
    material_id = args[args.index("--material-id") + 1]
    size = int(args[args.index("--size") + 1])
    image = output_dir / safe_artifact_name(material_id) / "swatch.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (size, size), (96, 128, 160, 255)).save(image, format="PNG")
    from codex_blender_modeler.blender_artifacts import sha256_file

    write_json_atomic(
        manifest,
        {
            "schema_version": "0.5.0",
            "material_count": 1,
            "resolution": [size, size],
            "swatches": [
                {
                    "material_id": material_id,
                    "path": image.relative_to(manifest.parent).as_posix(),
                    "sha256": sha256_file(image),
                    "width": size,
                    "height": size,
                    "encoding": "png-rgba8",
                }
            ],
        },
    )
    return SimpleNamespace(returncode=0)


def test_fixed_preview_renders_and_crash_adopts_exact_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render once and recover the published evidence without invoking Blender twice."""

    receipt_artifact, receipt = _fixture(tmp_path)
    monkeypatch.setattr(service, "validate_material_phase_receipt_v2", lambda *a, **k: receipt)
    monkeypatch.setattr(service, "run_blender", _fake_blender)
    preview, artifact = service.render_promoted_codex_image_material_preview(
        tmp_path,
        material_phase_receipt=receipt_artifact,
        preview_id="preview-001",
        material_id="mat.body",
        size=128,
        created_at=NOW,
    )
    assert preview.actual_blender_rendered is True
    assert preview.human_reviewed is False
    assert preview.reference_matched is False
    assert artifact.path.endswith("neutral_preview.json")

    def _unexpected_run(*_: object, **__: object) -> object:
        """Fail the test if immutable recovery attempts a second render."""

        raise AssertionError("Blender must not rerun during exact evidence adoption")

    monkeypatch.setattr(service, "run_blender", _unexpected_run)
    recovered, recovered_artifact = service.render_promoted_codex_image_material_preview(
        tmp_path,
        material_phase_receipt=receipt_artifact,
        preview_id="preview-001",
        material_id="mat.body",
        size=128,
        created_at=NOW,
    )
    assert recovered == preview
    assert recovered_artifact.sha256 == artifact.sha256


def test_fixed_preview_rejects_tamper_and_partial_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed for changed immutable bytes or an image without its manifest."""

    receipt_artifact, receipt = _fixture(tmp_path)
    monkeypatch.setattr(service, "validate_material_phase_receipt_v2", lambda *a, **k: receipt)
    monkeypatch.setattr(service, "run_blender", _fake_blender)
    preview, _ = service.render_promoted_codex_image_material_preview(
        tmp_path,
        material_phase_receipt=receipt_artifact,
        preview_id="preview-tamper",
        material_id="mat.body",
        size=128,
        created_at=NOW,
    )
    (tmp_path / preview.preview_image.path).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="size changed|hash changed"):
        service.render_promoted_codex_image_material_preview(
            tmp_path,
            material_phase_receipt=receipt_artifact,
            preview_id="preview-tamper",
            material_id="mat.body",
            size=128,
            created_at=NOW,
        )

    partial = (
        tmp_path
        / "production"
        / "autonomy_v2"
        / "session-preview"
        / "codex_imagegen"
        / "material_loop"
        / "previews"
        / "preview-partial"
        / "renders"
        / "mat.body"
        / "swatch.png"
    )
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"partial")
    with pytest.raises(ValueError, match="partial neutral preview"):
        service.render_promoted_codex_image_material_preview(
            tmp_path,
            material_phase_receipt=receipt_artifact,
            preview_id="preview-partial",
            material_id="mat.body",
            size=128,
            created_at=NOW,
        )


def test_fixed_preview_rejects_signature_only_png(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not claim an actual Blender render from hash-consistent non-image bytes."""

    receipt_artifact, receipt = _fixture(tmp_path)
    monkeypatch.setattr(service, "validate_material_phase_receipt_v2", lambda *a, **k: receipt)

    def _invalid_png(
        script_name: str,
        args: list[str],
        blend_file: Path | None = None,
        **kwargs: object,
    ) -> object:
        """Publish a manifest-bound PNG signature that Pillow cannot decode."""

        result = _fake_blender(script_name, args, blend_file, **kwargs)
        output_dir = Path(args[args.index("--output-dir") + 1])
        manifest = Path(args[args.index("--manifest") + 1])
        material_id = args[args.index("--material-id") + 1]
        image = output_dir / safe_artifact_name(material_id) / "swatch.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-decodable-image")
        from codex_blender_modeler.blender_artifacts import sha256_file

        payload = service._read_json(manifest)
        payload["swatches"][0]["sha256"] = sha256_file(image)
        write_json_atomic(manifest, payload)
        return result

    monkeypatch.setattr(service, "run_blender", _invalid_png)
    with pytest.raises(ValueError, match="cannot be decoded as PNG"):
        service.render_promoted_codex_image_material_preview(
            tmp_path,
            material_phase_receipt=receipt_artifact,
            preview_id="preview-invalid-png",
            material_id="mat.body",
            size=128,
            created_at=NOW,
        )


def test_historical_preview_keeps_its_renderer_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate historical snapshot bytes without binding them to a future checkout."""

    receipt_artifact, receipt = _fixture(tmp_path)
    monkeypatch.setattr(service, "validate_material_phase_receipt_v2", lambda *a, **k: receipt)
    monkeypatch.setattr(service, "run_blender", _fake_blender)
    _preview, artifact = service.render_promoted_codex_image_material_preview(
        tmp_path,
        material_phase_receipt=receipt_artifact,
        preview_id="preview-history",
        material_id="mat.body",
        size=128,
        created_at=NOW,
    )
    future_repo = tmp_path / "future-repository"
    future_script = (
        future_repo
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "render_material_swatches.py"
    )
    future_script.parent.mkdir(parents=True)
    future_script.write_text("# future fixed renderer version\n", encoding="utf-8")
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(repo_root=future_repo))
    assert service.validate_promoted_codex_image_material_preview(
        tmp_path,
        artifact,
        require_current=False,
    ).contract_id == "preview-history"
    with pytest.raises(ValueError, match="current fixed repository script"):
        service.validate_promoted_codex_image_material_preview(
            tmp_path,
            artifact,
            require_current=True,
        )
