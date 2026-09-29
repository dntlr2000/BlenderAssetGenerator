"""Cover patch-release metadata without changing historical contract dispatch."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_activation_readiness import _baseline_fixture

from codex_blender_modeler.autonomy_benchmarks.models import BenchmarkManifest
from codex_blender_modeler.autonomy_benchmarks.v02_models import BenchmarkManifestV02
from codex_blender_modeler.production import ActivationSourceManifest
from codex_blender_modeler.skill_orchestration.models import SkillRegistry


@pytest.mark.parametrize(
    ("model", "relative"),
    [
        (SkillRegistry, ".agents/skills/registry.json"),
        (BenchmarkManifest, "examples/autonomous_quality_benchmarks/manifest.json"),
        (BenchmarkManifestV02, "examples/autonomous_quality_benchmarks_v02/manifest.json"),
    ],
)
def test_patch_metadata_preserves_legacy_and_rejects_unknown(model, relative: str) -> None:
    """Accept both released producers, retain legacy defaults, and reject unknown releases."""
    payload = json.loads(Path(relative).read_text(encoding="utf-8"))
    for version in ("0.9.0", "0.9.1"):
        payload["project_version"] = version
        loaded = model.model_validate_json(json.dumps(payload))
        assert loaded.project_version == version
        assert model.model_validate_json(loaded.model_dump_json()) == loaded
    del payload["project_version"]
    assert model.model_validate_json(json.dumps(payload)).project_version == "0.9.0"
    payload["project_version"] = "0.9.2"
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("version", ["0.9.0", "0.9.1"])
def test_source_manifest_retains_exact_patch_identity(tmp_path: Path, version: str) -> None:
    """Revalidate complete hash-bound source manifests from both compatible releases."""
    _, manifest, _, _, _ = _baseline_fixture(tmp_path, project_version=version)
    payload = manifest.model_dump_json()
    reread = ActivationSourceManifest.model_validate_json(payload)
    assert reread.project_version == version
    assert reread.manifest_sha256 == manifest.manifest_sha256
    assert reread.model_dump_json() == payload
