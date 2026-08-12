"""Focused tests for deterministic ImageGen native normalization evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from codex_blender_modeler.blender_artifacts import sha256_file, stable_json_digest
from codex_blender_modeler.codex_imagegen.artifacts import (
    artifact_for_codex_image,
    write_immutable_codex_image_model,
)
from codex_blender_modeler.codex_imagegen.material_loop_models import (
    MaterialLoopRasterSize,
    imagegen_native_normalization_output_path,
    imagegen_native_normalization_plan_path,
)
from codex_blender_modeler.codex_imagegen.material_loop_normalization import (
    execute_native_image_normalization,
    plan_native_image_normalization,
    validate_native_normalization_plan,
    validate_native_normalization_receipt,
)

NOW = datetime(2026, 8, 12, 0, 0, tzinfo=UTC)


def _source_artifact(
    root: Path,
    *,
    name: str = "source.png",
    size: tuple[int, int] = (64, 64),
    mode: str = "RGB",
) -> object:
    """Create one deterministic source raster and return its exact artifact binding."""

    source = root / "staging" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    color = (31, 91, 173, 127) if mode == "RGBA" else (31, 91, 173)
    Image.new(mode, size, color).save(source, format="PNG", compress_level=9)
    return artifact_for_codex_image(
        root,
        source,
        artifact_id=name.replace(".", "-"),
        kind="codex-imagegen-source",
        media_type="image/png",
    )


def _plan(
    root: Path,
    source: object,
    *,
    contract_id: str,
    target: tuple[int, int],
    preferred_operation: str = "contain_pad",
    maximum_delta: float = 0.35,
):
    """Create one normalization plan with stable test identity fields."""

    return plan_native_image_normalization(
        root,
        contract_id=contract_id,
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        source_image=source,
        output_path=imagegen_native_normalization_output_path(
            "session-loop",
            contract_id,
        ),
        target_size=MaterialLoopRasterSize(width=target[0], height=target[1]),
        source_color_space="srgb",
        preferred_operation=preferred_operation,
        maximum_automatic_aspect_delta=maximum_delta,
        created_at=NOW,
    )


def _execute(root: Path, plan, *, suffix: str = "a"):
    """Persist one plan and execute its deterministic derivative adoption."""

    artifact = write_immutable_codex_image_model(
        root,
        root
        / imagegen_native_normalization_plan_path(
            plan.session_id,
            plan.contract_id,
        ),
        plan,
        kind="imagegen-native-normalization-plan",
    )
    receipt = execute_native_image_normalization(
        root,
        plan,
        artifact,
        receipt_contract_id=f"normalization-receipt-{suffix}",
        created_at=NOW,
    )
    return artifact, receipt


def test_exact_native_size_uses_byte_preserving_pass_through(tmp_path: Path) -> None:
    """Exact native size produces a separate derivative with identical source bytes."""

    source = _source_artifact(tmp_path)
    source_before = sha256_file(tmp_path / source.path)
    plan = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-exact",
        target=(64, 64),
    )

    _, receipt = _execute(tmp_path, plan)

    assert plan.operation == "pass_through"
    assert receipt.status == "pass_through"
    assert receipt.normalized_image is not None
    assert receipt.normalized_image.sha256 == source.sha256
    assert sha256_file(tmp_path / source.path) == source_before
    assert (tmp_path / receipt.normalized_image.path).read_bytes() == (
        tmp_path / source.path
    ).read_bytes()


@pytest.mark.parametrize(
    ("preferred_operation", "expected_crop"),
    [("center_crop", (16, 0, 64, 64)), ("tile_crop", (0, 0, 64, 64))],
)
def test_crop_policies_record_exact_anchor_and_dimensions(
    tmp_path: Path,
    preferred_operation: str,
    expected_crop: tuple[int, int, int, int],
) -> None:
    """Center and tile crops differ only through their explicit deterministic anchor."""

    source = _source_artifact(tmp_path, size=(96, 64))
    plan = _plan(
        tmp_path,
        source,
        contract_id=f"normalization-plan-{preferred_operation}",
        target=(64, 64),
        preferred_operation=preferred_operation,
        maximum_delta=0.6,
    )

    _, receipt = _execute(tmp_path, plan)

    assert plan.crop_rectangle is not None
    crop = plan.crop_rectangle
    assert (crop.x, crop.y, crop.width, crop.height) == expected_crop
    assert receipt.status == "normalized"
    assert receipt.normalized_image is not None
    with Image.open(tmp_path / receipt.normalized_image.path) as opened:
        assert opened.size == (64, 64)


def test_contain_pad_records_centered_padding_without_stretch(tmp_path: Path) -> None:
    """Contain+pad resizes uniformly and records the unused target pixels exactly."""

    source = _source_artifact(tmp_path, size=(96, 64))
    plan = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-contain",
        target=(64, 64),
        maximum_delta=0.6,
    )

    _, receipt = _execute(tmp_path, plan)

    assert plan.operation == "contain_pad"
    assert plan.content_size == MaterialLoopRasterSize(width=64, height=43)
    assert plan.padding is not None
    assert (
        plan.padding.left,
        plan.padding.top,
        plan.padding.right,
        plan.padding.bottom,
    ) == (0, 10, 0, 11)
    assert receipt.normalized_image is not None


def test_large_aspect_mismatch_stops_without_writing_output(tmp_path: Path) -> None:
    """A large native aspect mismatch becomes review-required rather than stretched."""

    source = _source_artifact(tmp_path, size=(256, 64))
    plan = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-review",
        target=(64, 64),
    )

    _, receipt = _execute(tmp_path, plan)

    assert plan.operation == "review_required"
    assert receipt.status == "review_required"
    assert receipt.normalized_image is None
    assert not (tmp_path / plan.output_path).exists()


def test_transformed_output_is_byte_deterministic_and_receipt_validates(
    tmp_path: Path,
) -> None:
    """Equivalent plans create byte-identical PNG derivatives and rehash successfully."""

    source = _source_artifact(tmp_path, size=(80, 64), mode="RGBA")
    first = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-first",
        target=(64, 64),
        maximum_delta=0.5,
    )
    second = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-second",
        target=(64, 64),
        maximum_delta=0.5,
    )

    first_artifact, first_receipt = _execute(tmp_path, first, suffix="first")
    _, second_receipt = _execute(tmp_path, second, suffix="second")

    assert first_receipt.normalized_image is not None
    assert second_receipt.normalized_image is not None
    assert first_receipt.normalized_image.sha256 == second_receipt.normalized_image.sha256
    validate_native_normalization_receipt(tmp_path, first, first_receipt)
    assert first_receipt.plan.sha256 == first_artifact.sha256
    assert first_receipt.output_has_alpha is True


def test_alpha_policy_is_explicit_even_when_dimensions_already_match(tmp_path: Path) -> None:
    """Dropping alpha forces a deterministic derivative instead of byte pass-through."""

    source = _source_artifact(tmp_path, mode="RGBA")
    source_before = sha256_file(tmp_path / source.path)
    plan = plan_native_image_normalization(
        tmp_path,
        contract_id="normalization-plan-alpha",
        job_id="job-loop",
        workflow_id="workflow-loop",
        dispatch_id="dispatch-loop",
        session_id="session-loop",
        source_image=source,
        output_path=imagegen_native_normalization_output_path(
            "session-loop",
            "normalization-plan-alpha",
        ),
        target_size=MaterialLoopRasterSize(width=64, height=64),
        source_color_space="srgb",
        alpha_policy="drop",
        created_at=NOW,
    )

    _, receipt = _execute(tmp_path, plan, suffix="alpha")

    assert plan.operation == "contain_pad"
    assert receipt.output_mode == "RGB"
    assert receipt.output_has_alpha is False
    assert sha256_file(tmp_path / source.path) == source_before


def test_receiptless_exact_output_is_adopted_but_conflicting_bytes_fail(
    tmp_path: Path,
) -> None:
    """Resume adopts exact bytes while refusing to overwrite a conflicting staged file."""

    source = _source_artifact(tmp_path)
    plan = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-resume",
        target=(64, 64),
    )
    plan_artifact, first = _execute(tmp_path, plan)
    second = execute_native_image_normalization(
        tmp_path,
        plan,
        plan_artifact,
        receipt_contract_id="normalization-receipt-resumed",
        created_at=NOW,
    )
    assert first.normalized_image == second.normalized_image

    conflict_plan = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-conflict",
        target=(64, 64),
    )
    conflict_artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path
        / imagegen_native_normalization_plan_path(
            conflict_plan.session_id,
            conflict_plan.contract_id,
        ),
        conflict_plan,
        kind="imagegen-native-normalization-plan",
    )
    conflict = tmp_path / conflict_plan.output_path
    conflict.parent.mkdir(parents=True, exist_ok=True)
    conflict.write_bytes(b"not-the-source")
    with pytest.raises(FileExistsError, match="conflicts"):
        execute_native_image_normalization(
            tmp_path,
            conflict_plan,
            conflict_artifact,
            receipt_contract_id="normalization-receipt-conflict",
            created_at=NOW,
        )


def test_changed_source_is_rejected_as_stale(tmp_path: Path) -> None:
    """A changed native source fails before any normalized derivative is adopted."""

    source = _source_artifact(tmp_path)
    plan = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-stale",
        target=(64, 64),
    )
    artifact = write_immutable_codex_image_model(
        tmp_path,
        tmp_path
        / imagegen_native_normalization_plan_path(plan.session_id, plan.contract_id),
        plan,
        kind="imagegen-native-normalization-plan",
    )
    (tmp_path / source.path).write_bytes(b"changed")

    with pytest.raises(ValueError, match="(?:size|hash) changed"):
        execute_native_image_normalization(
            tmp_path,
            plan,
            artifact,
            receipt_contract_id="normalization-receipt-stale",
            created_at=NOW,
        )


def test_receipt_validation_rejects_any_plan_field_drift(tmp_path: Path) -> None:
    """A receipt cannot rename the recorded operation while retaining valid exact files."""

    source = _source_artifact(tmp_path, size=(96, 64))
    plan = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-field-drift",
        target=(64, 64),
        maximum_delta=0.6,
    )
    _, receipt = _execute(tmp_path, plan, suffix="field-drift")
    changed = receipt.model_copy(update={"operation": "center_crop"})

    with pytest.raises(ValueError, match="fields differ"):
        validate_native_normalization_receipt(tmp_path, plan, changed)


def test_receipt_validation_recomputes_deterministic_output_bytes(tmp_path: Path) -> None:
    """A valid alternate PNG and self-consistent receipt hash cannot replace replayed bytes."""

    source = _source_artifact(tmp_path, size=(96, 64))
    plan = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-byte-replay",
        target=(64, 64),
        maximum_delta=0.6,
    )
    plan_artifact, receipt = _execute(tmp_path, plan, suffix="byte-replay")
    assert receipt.normalized_image is not None
    output = tmp_path / receipt.normalized_image.path
    Image.new("RGB", (64, 64), (199, 17, 43)).save(
        output,
        format="PNG",
        compress_level=9,
    )
    alternate = artifact_for_codex_image(
        tmp_path,
        output,
        artifact_id=receipt.normalized_image.artifact_id,
        kind=receipt.normalized_image.kind,
        media_type=receipt.normalized_image.media_type,
    )
    changed = receipt.model_copy(
        update={
            "normalized_image": alternate,
            "input_sha256": stable_json_digest(
                    {
                        "plan_sha256": plan_artifact.sha256,
                        "source_sha256": plan.source_image.sha256,
                        "output_sha256": alternate.sha256,
                        "native_output_adoption_receipt_sha256": None,
                    }
            ),
        }
    )

    with pytest.raises(ValueError, match="deterministic plan bytes"):
        validate_native_normalization_receipt(tmp_path, plan, changed)


def test_receipt_validation_recomputes_input_closure_digest(tmp_path: Path) -> None:
    """Receipt validation rejects a forged digest even when all image files are current."""

    source = _source_artifact(tmp_path)
    plan = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-digest",
        target=(64, 64),
    )
    _, receipt = _execute(tmp_path, plan, suffix="digest")
    changed = receipt.model_copy(update={"input_sha256": "f" * 64})

    with pytest.raises(ValueError, match="input hash"):
        validate_native_normalization_receipt(tmp_path, plan, changed)


@pytest.mark.parametrize(
    "output_path",
    [
        "input/native.png",
        "analysis/native.png",
        "blender/native.png",
        "reports/native.png",
        "canonical/native.png",
        (
            "production/autonomy_v2/session-loop/codex_imagegen/"
            "native_normalizations/protected-output/normalized.jpg"
        ),
    ],
)
def test_plan_rejects_protected_or_non_png_output_takeover(
    tmp_path: Path,
    output_path: str,
) -> None:
    """Only the exact normalization-owned PNG leaf can receive derivative bytes."""

    source = _source_artifact(tmp_path)
    with pytest.raises(ValueError, match="run-owned PNG leaf"):
        plan_native_image_normalization(
            tmp_path,
            contract_id="protected-output",
            job_id="job-loop",
            workflow_id="workflow-loop",
            dispatch_id="dispatch-loop",
            session_id="session-loop",
            source_image=source,
            output_path=output_path,
            target_size=MaterialLoopRasterSize(width=64, height=64),
            source_color_space="srgb",
            created_at=NOW,
        )


def test_plan_replay_rejects_requested_operation_or_geometry_tamper(
    tmp_path: Path,
) -> None:
    """Recompute caller preference and crop geometry instead of accepting stretch drift."""

    source = _source_artifact(tmp_path, size=(96, 64))
    plan = _plan(
        tmp_path,
        source,
        contract_id="normalization-plan-replay",
        target=(64, 64),
        preferred_operation="center_crop",
        maximum_delta=0.6,
    )
    assert plan.requested_operation == "center_crop"
    requested_tamper = plan.model_copy(update={"requested_operation": "tile_crop"})
    with pytest.raises(ValueError, match="input digest"):
        validate_native_normalization_plan(tmp_path, requested_tamper)
    geometry_tamper = plan.model_copy(
        update={
            "crop_rectangle": plan.crop_rectangle.model_copy(update={"x": 0})
            if plan.crop_rectangle is not None
            else None
        }
    )
    with pytest.raises(ValueError, match="geometry differs"):
        validate_native_normalization_plan(tmp_path, geometry_tamper)
