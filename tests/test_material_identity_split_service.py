"""Actual opt-in preapproval regression for the guarded identity-split service."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest

from codex_blender_modeler.blender_artifacts import (
    native_io_path,
    sha256_file,
)
from codex_blender_modeler.material_closure.models import (
    MaterialCanonicalMaterialPlanAbsence,
)
from codex_blender_modeler.material_identity_split.models import (
    MaterialIdentitySplitShadowBuildReceipt,
)
from codex_blender_modeler.material_identity_split.service import (
    MaterialIdentitySplitService,
    _artifact_from_path,
)

ROOT = Path(__file__).resolve().parents[1]
PLANNING_ROOT = (
    "history/material_identity_split_plans/"
    "material-identity-split-20260814t080212787z-scope01"
)
ABSENCE_PATH = (
    "production/material_repair/"
    "material-repair-20260814t073642657z-facet04/material_plan_absence.json"
)


def _copy_authoritative_job_evidence(source: Path, destination: Path) -> None:
    """Copy regular job evidence with native long paths while omitting scratch debris."""

    destination.mkdir(parents=True, exist_ok=False)
    pending = [source]
    while pending:
        current = pending.pop()
        with os.scandir(native_io_path(current)) as iterator:
            entries = sorted(iterator, key=lambda item: item.name.casefold())
        for entry in entries:
            if current == source and entry.name == "scratch":
                continue
            metadata = entry.stat(follow_symlinks=False)
            attributes = getattr(metadata, "st_file_attributes", 0)
            if entry.is_symlink() or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise ValueError("authoritative test evidence contains a link or reparse point")
            source_member = current / entry.name
            destination_member = destination / source_member.relative_to(source)
            if stat.S_ISDIR(metadata.st_mode):
                os.makedirs(native_io_path(destination_member), exist_ok=False)
                pending.append(source_member)
            elif stat.S_ISREG(metadata.st_mode):
                os.makedirs(native_io_path(destination_member.parent), exist_ok=True)
                with (
                    open(native_io_path(source_member), "rb") as source_handle,
                    open(native_io_path(destination_member), "xb") as destination_handle,
                ):
                    shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
            else:
                raise ValueError("authoritative test evidence contains a special file")


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_MATERIAL_IDENTITY_SPLIT_BLENDER_SMOKE") != "1",
    reason=(
        "set CBM_RUN_MATERIAL_IDENTITY_SPLIT_BLENDER_SMOKE=1 for the isolated "
        "Blender 5.0.1 identity-split preapproval smoke"
    ),
)
def test_identity_split_runs_actual_blender_5_and_stops_before_scope_approval(
    tmp_path: Path,
) -> None:
    """Replay the preserved plan in a copy and prove the exact preapproval boundary."""

    source = ROOT / "workspaces" / "item_crystalgun_full_0"
    if not source.is_dir():
        pytest.skip("the preserved Crystalgun evidence workspace is not available")
    job = tmp_path / "item_crystalgun_full_0"
    _copy_authoritative_job_evidence(source, job)
    service = MaterialIdentitySplitService(job)
    absence_model = MaterialCanonicalMaterialPlanAbsence.model_validate_json(
        (job / Path(ABSENCE_PATH)).read_bytes()
    )
    absence = _artifact_from_path(
        job,
        ABSENCE_PATH,
        artifact_id=absence_model.absence_id,
        kind="material_plan_absence",
    )
    canonical_paths = {
        "scene": job / "analysis" / "scene_spec.json",
        "modeling": job / "analysis" / "modeling_plan.json",
        "blend": job / "blender" / "scene.blend",
    }
    before = {
        role: (sha256_file(path), path.stat().st_size)
        for role, path in canonical_paths.items()
    }
    assert not (job / "analysis" / "material_plan.json").exists()
    publication = service.prepare_plan_from_planning_root(
        planning_root=PLANNING_ROOT,
        run_id="material-identity-split-blender-smoke-01",
        material_plan_absence=absence,
    )
    result = service.run_preapproval(
        plan_artifact=publication.plan_artifact,
        modeling_plan_diff_report=publication.modeling_plan_diff_report,
        canonical_scene_inventory=publication.canonical_scene_inventory,
    )
    assert result.status == "framework_ready_for_explicit_scope_approval"
    assert result.approval_request is not None
    assert result.shadow_build_receipt is not None
    shadow = MaterialIdentitySplitShadowBuildReceipt.model_validate_json(
        (job / Path(result.shadow_build_receipt.path)).read_bytes()
    )
    assert shadow.status == "passed"
    assert shadow.blender_version == "5.0.1"
    assert shadow.blender_process_count == 3
    assert shadow.canonical_unchanged is True
    assert {
        role: (sha256_file(path), path.stat().st_size)
        for role, path in canonical_paths.items()
    } == before
    assert not (job / "analysis" / "material_plan.json").exists()
    run_root = job / "production" / "material_identity_split" / publication.plan.run_id
    assert len(list(run_root.glob("approval_request.json"))) == 1
    assert not (run_root / "approvals").exists()
    assert not (run_root / "approval_consumptions").exists()
    assert not (run_root / "intents").exists()
    assert not (run_root / "apply_receipt.json").exists()
    assert not (run_root / "rollback_receipt.json").exists()
    assert not list(run_root.rglob("material_phase_receipt.json"))
    assert not list(run_root.rglob("controller_result.json"))
    assert not list(run_root.rglob("package_manifest.json"))
