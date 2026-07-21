from __future__ import annotations

from pathlib import Path

from ..build_provenance import collect_build_provenance
from ..models import SceneSpec
from ..workspace import sha256_file
from .camera_fingerprint import camera_fingerprint, require_camera_fingerprint
from .models import RenderPassManifest, VisualQARequest


def _current_build_fingerprint(scene_spec_path: Path, job_id: str) -> str:
    """Fingerprint every current canonical input that the Blender build consumed."""

    root = scene_spec_path.expanduser().resolve().parent.parent
    provenance = collect_build_provenance(
        root,
        job_id,
        scene_spec_path=scene_spec_path,
    )
    return str(provenance["fingerprint"])


def create_visual_qa_request(
    *,
    job_id: str,
    run_id: str,
    mode: str,
    reference_path: Path,
    reference_mask_path: Path,
    preview_path: Path,
    render_pass_manifest_path: Path,
    scene_spec_path: Path,
    include_generated_target: bool = False,
) -> VisualQARequest:
    """Create a request whose hashes freeze all direct-reference QA inputs."""

    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    if spec.job_id != job_id:
        raise ValueError("visual QA request job_id does not match SceneSpec")
    manifest = RenderPassManifest.model_validate_json(
        render_pass_manifest_path.read_text(encoding="utf-8")
    )
    if manifest.job_id != job_id:
        raise ValueError("render-pass manifest job_id does not match Visual QA request")
    if mode not in {"concept", "measured"}:
        raise ValueError("visual QA mode must be concept or measured")
    fingerprint = camera_fingerprint(spec)
    if manifest.camera_fingerprint is not None and manifest.camera_fingerprint != fingerprint:
        raise ValueError("render-pass manifest was produced from a different comparison camera")
    if manifest.scene_spec_sha256 is not None:
        if manifest.scene_spec_sha256 != sha256_file(scene_spec_path):
            raise ValueError("render-pass manifest was produced from a different SceneSpec")
    if manifest.build_fingerprint != _current_build_fingerprint(scene_spec_path, job_id):
        raise ValueError("render-pass manifest was produced from stale canonical build inputs")
    return VisualQARequest(
        job_id=job_id,
        run_id=run_id,
        mode=mode,  # type: ignore[arg-type]
        reference_path=str(reference_path.resolve()),
        reference_sha256=sha256_file(reference_path),
        reference_mask_path=str(reference_mask_path.resolve()),
        reference_mask_sha256=sha256_file(reference_mask_path),
        preview_path=str(preview_path.resolve()),
        preview_sha256=sha256_file(preview_path),
        render_pass_manifest_path=str(render_pass_manifest_path.resolve()),
        render_pass_manifest_sha256=sha256_file(render_pass_manifest_path),
        scene_spec_sha256=sha256_file(scene_spec_path),
        camera_fingerprint=fingerprint,
        include_generated_target=include_generated_target,
    )


def validate_visual_qa_request(
    request: VisualQARequest,
    *,
    scene_spec_path: Path,
) -> RenderPassManifest:
    """Reject stale QA requests before comparison or revision candidate production."""

    paths_and_hashes = [
        (Path(request.reference_path), request.reference_sha256, "reference"),
        (Path(request.reference_mask_path), request.reference_mask_sha256, "reference mask"),
        (Path(request.preview_path), request.preview_sha256, "preview"),
        (
            Path(request.render_pass_manifest_path),
            request.render_pass_manifest_sha256,
            "render-pass manifest",
        ),
        (scene_spec_path, request.scene_spec_sha256, "SceneSpec"),
    ]
    for path, expected, label in paths_and_hashes:
        if not path.is_file():
            raise FileNotFoundError(f"visual QA {label} is missing: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"visual QA {label} hash changed: {expected} != {actual}")
    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    if spec.job_id != request.job_id:
        raise ValueError("visual QA request job_id does not match SceneSpec")
    require_camera_fingerprint(spec, request.camera_fingerprint)
    manifest_path = Path(request.render_pass_manifest_path)
    manifest = RenderPassManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.job_id != request.job_id:
        raise ValueError("render-pass manifest job_id does not match Visual QA request")
    if manifest.camera_fingerprint not in {None, request.camera_fingerprint}:
        raise ValueError("render-pass manifest camera fingerprint does not match request")
    if manifest.scene_spec_sha256 not in {None, request.scene_spec_sha256}:
        raise ValueError("render-pass manifest SceneSpec hash does not match request")
    if manifest.build_fingerprint != _current_build_fingerprint(
        scene_spec_path,
        request.job_id,
    ):
        raise ValueError("render-pass manifest build fingerprint is stale")
    for record in manifest.passes:
        pass_path = Path(record.path)
        if not pass_path.is_absolute():
            pass_path = manifest_path.parent / pass_path
        if not pass_path.is_file():
            raise FileNotFoundError(f"render pass is missing: {pass_path}")
        if sha256_file(pass_path) != record.sha256:
            raise ValueError(f"render pass hash changed: {record.kind}")
    return manifest
