"""Resolve original evidence locators without migrating plans or weakening paired gates."""

import json

import pytest
from test_revision_payload_binding import _approve, _complete, _fixture, _write

from codex_blender_modeler.analysis.models import ModelingPlan
from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.orchestration import paired_revision as paired
from codex_blender_modeler.orchestration import service
from codex_blender_modeler.orchestration.paired_models import PairedModelingPlanBinding


def legacy_fixture(tmp_path, monkeypatch, separator="\\"):
    """Create exact synthetic legacy plan bytes alongside job-local immutable evidence."""
    root, _ = _fixture(tmp_path, monkeypatch, parametric=True)
    for name in ("reference_analysis", "camera_solution"):
        _write(root / f"analysis/{name}.json", {"test_only": name})
    path = root / paired.MODEL_PATH
    model = json.loads(path.read_bytes())
    for name in ("reference_analysis", "camera_solution"):
        model[f"{name}_path"] = f"workspaces/{root.name}/analysis/{name}.json".replace(
            "/", separator
        )
    _write(path, model)
    original_bytes = path.read_bytes()
    model["global_notes"] = ["Synthetic fixture only; no production authority."]
    candidate = root / "analysis/legacy_candidate.json"
    _write(candidate, model)
    return root, candidate, original_bytes


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_legacy_binding_preserves_raw_plan_and_uses_contained_schema_keys(
    tmp_path, monkeypatch, separator
):
    """Historical strings survive byte-for-byte while new dependency keys stay normalized."""
    root, candidate, before = legacy_fixture(tmp_path, monkeypatch, separator)
    scene = SceneSpec.model_validate_json((root / paired.SCENE_PATH).read_bytes())
    binding = paired.create_modeling_binding(
        root, scene, candidate.relative_to(root).as_posix(), sha256_file(candidate)
    )
    PairedModelingPlanBinding.model_validate(binding)
    assert "analysis/reference_analysis.json" in binding["preserved_sources"]
    assert "analysis/camera_solution.json" in binding["preserved_sources"]
    assert all("\\" not in path for path in binding["preserved_sources"])
    assert (root / paired.MODEL_PATH).read_bytes() == before
    paired.validate_modeling_binding(root, binding, scene)
    _write(root / "analysis/reference_analysis.json", {"tampered": True})
    with pytest.raises(ValueError, match="observation evidence changed"):
        paired.validate_modeling_binding(root, binding, scene)


def test_real_generic_checkpoint_and_paired_transaction_keep_legacy_strings(tmp_path, monkeypatch):
    """Existing synthetic authority drives the unchanged archive/CAS host transaction."""
    root, candidate, _ = legacy_fixture(tmp_path, monkeypatch)
    state = service.plan_workflow(
        "Synthetic legacy paired revision",
        job_id=root.name,
        intent="revise_asset",
        revision_strategy="manual_guarded",
        paired_modeling_plan_path=candidate.relative_to(root).as_posix(),
        paired_modeling_plan_sha256=sha256_file(candidate),
    )
    state = _approve(root, _complete(root, state))
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert next(s.status for s in state.steps if s.step_id == "revision.apply") == "complete"
    assert (root / paired.MODEL_PATH).read_bytes() == candidate.read_bytes()
    final = json.loads((root / paired.MODEL_PATH).read_bytes())
    assert final["reference_analysis_path"].startswith(f"workspaces\\{root.name}\\")


@pytest.mark.parametrize(
    "locator",
    [
        "workspaces\\foreign\\analysis\\reference_analysis.json",
        "workspaces/foreign/analysis/reference_analysis.json",
        "workspaces/{job}/analysis\\reference_analysis.json",
        "workspaces\\{job}\\analysis\\..\\reference_analysis.json",
        "C:\\workspaces\\{job}\\analysis\\reference_analysis.json",
        "\\\\server\\workspaces\\{job}\\analysis\\reference_analysis.json",
        "workspaces\\{job}\\analysis\\camera_solution.json",
        "../analysis/reference_analysis.json",
        "/analysis/reference_analysis.json",
    ],
)
def test_unrecognized_historical_locators_fail_closed(tmp_path, monkeypatch, locator):
    """Foreign ownership, traversal and alternate roots cannot become trusted aliases."""
    root, _, _ = legacy_fixture(tmp_path, monkeypatch)
    value = json.loads((root / paired.MODEL_PATH).read_bytes())
    value["reference_analysis_path"] = locator.format(job=root.name)
    with pytest.raises((ValueError, FileNotFoundError)):
        paired.preserved_source_hashes(root, ModelingPlan.model_validate(value))


def test_existing_modern_long_locator_keeps_literal_meaning(tmp_path, monkeypatch):
    """An existing strict POSIX path cannot silently switch to a different short file."""
    root, _, _ = legacy_fixture(tmp_path, monkeypatch, "/")
    model = ModelingPlan.model_validate_json((root / paired.MODEL_PATH).read_bytes())
    long_path = root / model.reference_analysis_path
    _write(long_path, {"distinct_existing_modern_meaning": True})
    result = paired.preserved_source_hashes(root, model)
    assert result[model.reference_analysis_path] == sha256_file(long_path)
    assert "analysis/reference_analysis.json" not in result


def test_ambiguous_windows_alias_is_rejected(tmp_path, monkeypatch):
    """A competing normalized long file makes the Windows alias ineligible."""
    root, _, _ = legacy_fixture(tmp_path, monkeypatch)
    model = ModelingPlan.model_validate_json((root / paired.MODEL_PATH).read_bytes())
    _write(root / model.reference_analysis_path.replace("\\", "/"), {"ambiguous": True})
    with pytest.raises(ValueError, match="ambiguous"):
        paired.preserved_source_hashes(root, model)


def test_alias_rejects_symlink_file_and_owner_mismatch(tmp_path, monkeypatch):
    """The compatibility branch cannot bypass ordinary-file and owning-job checks."""
    root, _, _ = legacy_fixture(tmp_path, monkeypatch)
    model = ModelingPlan.model_validate_json((root / paired.MODEL_PATH).read_bytes())
    target = root / "analysis/reference_analysis.json"
    backup = root / "reference_copy.json"
    target.rename(backup)
    target.symlink_to(backup)
    with pytest.raises(ValueError):
        paired.preserved_source_hashes(root, model)
    wrong = model.model_copy(update={"job_id": "foreign"})
    with pytest.raises(ValueError, match="another job"):
        paired.preserved_source_hashes(root, wrong)


def test_alias_rejects_linked_analysis_ancestor(tmp_path, monkeypatch):
    """A legitimate short alias still cannot traverse a symbolic-link directory."""
    root, _, _ = legacy_fixture(tmp_path, monkeypatch)
    model = ModelingPlan.model_validate_json((root / paired.MODEL_PATH).read_bytes())
    original = root / "analysis"
    saved = root / "actual_analysis"
    original.rename(saved)
    original.symlink_to(saved, target_is_directory=True)
    with pytest.raises(ValueError):
        paired.preserved_source_hashes(root, model)
