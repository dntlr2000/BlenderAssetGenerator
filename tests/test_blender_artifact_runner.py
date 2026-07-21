from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_blender_modeler import blender_artifact_runner
from codex_blender_modeler.build_provenance import (
    BuildProvenanceError,
    canonical_json_text,
    collect_build_provenance,
    require_matching_build_provenance,
)
from codex_blender_modeler.qa.models import REQUIRED_QA_PASS_KINDS


def _built_job(tmp_path: Path, monkeypatch) -> Path:
    """Create a minimal external workspace containing one generated blend placeholder."""

    workspace = tmp_path / "workspaces"
    root = workspace / "asset_qa"
    blend = root / "blender" / "scene.blend"
    blend.parent.mkdir(parents=True)
    blend.write_bytes(b"blend")
    repository = Path(__file__).resolve().parents[1]
    scene_spec = json.loads(
        (repository / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    scene_spec["job_id"] = "asset_qa"
    spec_path = root / "analysis" / "scene_spec.json"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(json.dumps(scene_spec, indent=2), encoding="utf-8")
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    return root


def test_material_inspection_wrapper_uses_isolated_blender_script(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The host wrapper returns the atomic report emitted by the Blender child."""

    root = _built_job(tmp_path, monkeypatch)
    calls: list[tuple[str, list[str], Path | None]] = []

    def fake_run(script: str, args: list[str], blend_file: Path | None = None):
        """Write the material report expected from the isolated Blender process."""

        calls.append((script, args, blend_file))
        output = Path(args[args.index("--output") + 1])
        output.parent.mkdir(parents=True)
        output.write_text(
            json.dumps({"schema_version": "0.5.0", "job_id": "asset_qa", "ok": True}),
            encoding="utf-8",
        )

    monkeypatch.setattr(blender_artifact_runner, "run_blender", fake_run)
    result = blender_artifact_runner.inspect_job_materials("asset_qa")
    assert result["ok"] is True
    assert calls[0][0] == "inspect_materials.py"
    assert calls[0][2] == root / "blender" / "scene.blend"


def test_qa_wrapper_validates_render_pass_manifest(tmp_path: Path, monkeypatch) -> None:
    """The host wrapper rejects malformed manifests by returning a validated model."""

    _built_job(tmp_path, monkeypatch)

    def fake_run(script: str, args: list[str], blend_file: Path | None = None):
        """Write one minimal valid QA manifest for host-model validation."""

        assert script == "render_qa_passes.py"
        assert blend_file is not None
        assert Path(args[args.index("--scene-spec") + 1]).name == "scene_spec.json"
        manifest = Path(args[args.index("--manifest") + 1])
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "0.6.0",
                    "job_id": "asset_qa",
                    "scene_spec_sha256": args[args.index("--scene-spec-sha256") + 1],
                    "camera_fingerprint": args[args.index("--camera-fingerprint") + 1],
                    "build_fingerprint": args[args.index("--build-fingerprint") + 1],
                    "blender_version": "5.0.1",
                    "render_engine": "BLENDER_EEVEE",
                    "render_device": "DEFAULT",
                    "resolution": [64, 64],
                    "passes": [
                        {
                            "kind": kind,
                            "path": f"{kind}.png",
                            "sha256": "0" * 64,
                            "width": 64,
                            "height": 64,
                            "encoding": "png-rgb8",
                        }
                        for kind in REQUIRED_QA_PASS_KINDS
                    ],
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(blender_artifact_runner, "run_blender", fake_run)
    result = blender_artifact_runner.render_job_qa_passes("asset_qa")
    assert result.job_id == "asset_qa"
    assert result.passes[0].kind == "beauty"
    assert len(result.passes) == 7


def test_visual_qa_rejects_scene_spec_changed_without_rebuild(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A canonical SceneSpec edit invalidates the build fingerprint until Blender rebuilds."""

    root = _built_job(tmp_path, monkeypatch)
    baseline = collect_build_provenance(root, "asset_qa")
    scene_spec_path = root / "analysis" / "scene_spec.json"
    scene_spec = json.loads(scene_spec_path.read_text(encoding="utf-8"))
    scene_spec["camera"]["ortho_scale"] += 1.0
    scene_spec_path.write_text(json.dumps(scene_spec, indent=2), encoding="utf-8")
    current = collect_build_provenance(root, "asset_qa")

    with pytest.raises(BuildProvenanceError, match="rebuild before visual QA"):
        require_matching_build_provenance(
            canonical_json_text(baseline),
            str(current["fingerprint"]),
            operation="visual QA",
        )
