from __future__ import annotations

import colorsys
import hashlib
import json
import math
import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

from ..blender_artifacts import write_json_atomic
from ..texturing import load_texture_manifest
from ..workspace import job_dir, sha256_file
from .fidelity_models import (
    EmissionFidelityMetrics,
    ImageFidelityMetrics,
    MaterialChannelEvidence,
    MaterialFidelityEvidence,
    MaterialFidelityFinding,
    MaterialFidelityReport,
    MaterialFidelityThresholds,
    NormalFidelityMetrics,
)
from .io import load_material_plan

_MAX_SAMPLE_EDGE = 256
_CLEAN_FAMILIES: set[str] = set()
_CLEAN_HINTS = {
    "clean",
    "flat",
    "smooth",
    "uniform",
    "stylized",
    "simple",
    "without marbling",
    "no noise",
    "균일",
    "매끈",
    "단순",
    "노이즈 없음",
}


def _safe_job_path(root: Path, relative: str) -> Path:
    """Resolve one contract path while rejecting absolute and escaping paths."""

    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError(f"Material-fidelity paths must be job-relative: {relative}")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Material-fidelity path escapes the job root: {relative}") from exc
    return resolved


def _relative_path(root: Path, path: Path) -> str:
    """Return one normalized job-relative evidence path."""

    return path.resolve().relative_to(root.resolve()).as_posix()


def _source_fingerprint(input_hashes: dict[str, str]) -> str:
    """Hash an ordered source map so the report can be checked for staleness."""

    payload = json.dumps(input_hashes, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resized_rgba(path: Path) -> tuple[Image.Image, tuple[int, int]]:
    """Load and deterministically downsample an image for bounded host analysis."""

    with Image.open(path) as source:
        original_size = source.size
        image = source.convert("RGBA")
    image.thumbnail(
        (_MAX_SAMPLE_EDGE, _MAX_SAMPLE_EDGE),
        resample=Image.Resampling.LANCZOS,
    )
    return image, original_size


def _active_mask(image: Image.Image, external_mask: Image.Image | None) -> list[bool]:
    """Build an active-pixel mask from reference diagnostics or image alpha."""

    alpha = image.getchannel("A")
    alpha_values = list(alpha.getdata())
    if external_mask is not None:
        mask = external_mask.convert("L").resize(image.size, Image.Resampling.NEAREST)
        return [a > 16 and m > 16 for a, m in zip(alpha_values, mask.getdata(), strict=True)]
    if min(alpha_values, default=255) < 250:
        return [value > 16 for value in alpha_values]
    return [True] * len(alpha_values)


def _luminance(rgb: tuple[int, int, int]) -> float:
    """Convert one sRGB triplet to a bounded perceptual luminance proxy."""

    red, green, blue = (value / 255.0 for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _dominant_hue(
    rgb_values: Iterable[tuple[int, int, int]],
) -> tuple[float | None, float]:
    """Estimate a deterministic saturation-weighted dominant hue and coverage."""

    bins = [0.0] * 36
    saturated = 0
    total = 0
    for red, green, blue in rgb_values:
        total += 1
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        if saturation < 0.25 or value < 0.18:
            continue
        saturated += 1
        bins[min(35, int(hue * 36.0))] += saturation * value
    if not any(bins):
        return None, saturated / max(1, total)
    index = max(range(len(bins)), key=bins.__getitem__)
    return (index + 0.5) * 10.0, saturated / max(1, total)


def _band_fraction(
    luminance_grid: list[float],
    active: list[bool],
    width: int,
    height: int,
    median: float,
) -> float:
    """Measure unusually dark full-row or full-column bands in an image."""

    threshold = median * 0.68
    minimum_drop = 0.025
    row_dark = 0
    valid_rows = 0
    for y in range(height):
        values = [
            luminance_grid[y * width + x]
            for x in range(width)
            if active[y * width + x]
        ]
        if not values:
            continue
        valid_rows += 1
        mean = sum(values) / len(values)
        row_dark += mean < threshold and median - mean > minimum_drop
    column_dark = 0
    valid_columns = 0
    for x in range(width):
        values = [
            luminance_grid[y * width + x]
            for y in range(height)
            if active[y * width + x]
        ]
        if not values:
            continue
        valid_columns += 1
        mean = sum(values) / len(values)
        column_dark += mean < threshold and median - mean > minimum_drop
    return max(
        row_dark / max(1, valid_rows),
        column_dark / max(1, valid_columns),
    )


def _neighbor_delta(
    luminance_grid: list[float],
    active: list[bool],
    width: int,
    height: int,
) -> float:
    """Measure bounded horizontal and vertical high-frequency luminance change."""

    differences: list[float] = []
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if not active[index]:
                continue
            if x + 1 < width and active[index + 1]:
                differences.append(abs(luminance_grid[index] - luminance_grid[index + 1]))
            if y + 1 < height and active[index + width]:
                differences.append(abs(luminance_grid[index] - luminance_grid[index + width]))
    return sum(differences) / max(1, len(differences))


def _image_metrics(
    path: Path,
    *,
    external_mask: Image.Image | None = None,
) -> tuple[ImageFidelityMetrics, Image.Image, list[bool]]:
    """Compute deterministic full-field variation, line, noise, and hue metrics."""

    image, original_size = _resized_rgba(path)
    active = _active_mask(image, external_mask)
    rgb_all = list(image.convert("RGB").getdata())
    selected_rgb = [rgb for rgb, enabled in zip(rgb_all, active, strict=True) if enabled]
    if not selected_rgb:
        raise ValueError(f"Image contains no active pixels: {path}")
    luminance_grid = [_luminance(rgb) for rgb in rgb_all]
    luminance_values = [
        value for value, enabled in zip(luminance_grid, active, strict=True) if enabled
    ]
    mean = sum(luminance_values) / len(luminance_values)
    stddev = statistics.pstdev(luminance_values)
    median = statistics.median(luminance_values)
    dark_threshold = median * 0.58
    dark_fraction = sum(
        value < dark_threshold and median - value > 0.025 for value in luminance_values
    ) / len(luminance_values)

    gray = image.convert("L")
    blurred = gray.filter(ImageFilter.GaussianBlur(radius=2.0))
    residual_values = [
        abs(source - smooth) / 255.0
        for source, smooth, enabled in zip(
            gray.getdata(),
            blurred.getdata(),
            active,
            strict=True,
        )
        if enabled
    ]
    hue, saturated_fraction = _dominant_hue(selected_rgb)
    width, height = image.size
    return (
        ImageFidelityMetrics(
            width=original_size[0],
            height=original_size[1],
            sampled_pixels=len(luminance_values),
            luminance_mean=round(mean, 6),
            luminance_stddev=round(stddev, 6),
            luminance_median=round(median, 6),
            relative_variation=round(stddev / max(mean, 0.02), 6),
            neighbor_delta_mean=round(
                _neighbor_delta(luminance_grid, active, width, height),
                6,
            ),
            residual_noise_mean=round(sum(residual_values) / len(residual_values), 6),
            dark_contrast_fraction=round(dark_fraction, 6),
            dark_band_fraction=round(
                _band_fraction(luminance_grid, active, width, height, median),
                6,
            ),
            saturated_fraction=round(saturated_fraction, 6),
            dominant_hue_deg=None if hue is None else round(hue, 3),
        ),
        image,
        active,
    )


def _normal_metrics(image: Image.Image, active: list[bool]) -> NormalFidelityMetrics:
    """Compute normalized angular deviation for a tangent-space normal map."""

    angles: list[float] = []
    inverted = 0
    for rgb, enabled in zip(image.convert("RGB").getdata(), active, strict=True):
        if not enabled:
            continue
        x, y, z = ((value / 255.0) * 2.0 - 1.0 for value in rgb)
        length = math.sqrt(x * x + y * y + z * z)
        if length <= 1e-9:
            continue
        normalized_z = max(-1.0, min(1.0, z / length))
        inverted += normalized_z < 0
        angles.append(math.degrees(math.acos(normalized_z)))
    if not angles:
        return NormalFidelityMetrics(
            mean_deviation_deg=0.0,
            p95_deviation_deg=0.0,
            inverted_fraction=0.0,
        )
    ordered = sorted(angles)
    p95 = ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)]
    return NormalFidelityMetrics(
        mean_deviation_deg=round(sum(angles) / len(angles), 4),
        p95_deviation_deg=round(p95, 4),
        inverted_fraction=round(inverted / len(angles), 6),
    )


def _hue_distance(left: float, right: float) -> float:
    """Return the shortest circular distance between two hue angles."""

    difference = abs(left - right) % 360.0
    return min(difference, 360.0 - difference)


def _emission_metrics(
    image: Image.Image,
    active: list[bool],
    reference_hue: float | None,
) -> EmissionFidelityMetrics:
    """Measure bright saturated coverage and reference-relative emission hue."""

    selected = [
        rgb
        for rgb, enabled in zip(image.convert("RGB").getdata(), active, strict=True)
        if enabled
    ]
    active_count = 0
    for red, green, blue in selected:
        _, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        active_count += value >= 0.18 and saturation >= 0.15
    hue, saturated_fraction = _dominant_hue(selected)
    return EmissionFidelityMetrics(
        active_fraction=round(active_count / max(1, len(selected)), 6),
        saturated_fraction=round(saturated_fraction, 6),
        dominant_hue_deg=None if hue is None else round(hue, 3),
        reference_hue_deg=reference_hue,
        hue_error_deg=(
            None
            if hue is None or reference_hue is None
            else round(_hue_distance(hue, reference_hue), 3)
        ),
    )


def _clean_surface_expected(item: Any, manifest: Any, recipe: dict[str, Any]) -> bool:
    """Infer a conservative clean-surface expectation from existing V0.5 evidence."""

    text_parts = [item.label, *item.notes]
    for value in (
        manifest.generation_notes,
        manifest.expected_preview_goal,
        (manifest.provenance.prompt if manifest.provenance else None),
        manifest.procedural.get("preset"),
        *recipe.get("assumptions", []),
    ):
        if value:
            text_parts.append(str(value))
    normalized = " ".join(text_parts).casefold()
    return item.shader_family in _CLEAN_FAMILIES or any(
        hint in normalized for hint in _CLEAN_HINTS
    )


def _load_json(path: Path) -> dict[str, Any]:
    """Load one required JSON object with a clear structural failure."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _reference_path(root: Path) -> Path | None:
    """Resolve the unique primary reference copied into immutable job input."""

    matches = sorted(
        path
        for path in (root / "input").glob("reference.*")
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    if len(matches) > 1:
        raise ValueError("Material fidelity requires one unambiguous primary reference")
    return matches[0] if matches else None


def _reference_mask(root: Path) -> Image.Image | None:
    """Load the deterministic reference content mask when it is available."""

    path = root / "analysis" / "masks" / "reference_content.png"
    if not path.is_file():
        return None
    with Image.open(path) as source:
        return source.convert("L")


def _material_consumers(scene_spec: dict[str, Any]) -> dict[str, list[str]]:
    """Map stable material IDs to all SceneSpec objects that consume them."""

    consumers: dict[str, list[str]] = {}
    for item in scene_spec.get("objects", []):
        if not isinstance(item, dict):
            continue
        material_id = item.get("material_id")
        object_id = item.get("id")
        if isinstance(material_id, str) and isinstance(object_id, str):
            consumers.setdefault(material_id, []).append(object_id)
    return {key: sorted(set(values)) for key, values in consumers.items()}


def _surface_detail_parents(modeling_plan: dict[str, Any]) -> dict[str, str]:
    """Map stable surface-detail IDs to their intended parent semantic object."""

    result: dict[str, str] = {}
    for item in modeling_plan.get("surface_details", []):
        if not isinstance(item, dict):
            continue
        detail_id = item.get("id")
        parent_id = item.get("parent_object_id")
        if isinstance(detail_id, str) and isinstance(parent_id, str):
            result[detail_id] = parent_id
    return result


def _inventory_uv_evidence(root: Path) -> tuple[dict[str, list[dict[str, Any]]], Path | None]:
    """Load current Blender UV evidence for exact spatial-binding verification."""

    path = root / "reports" / "scene_inventory.json"
    if not path.is_file():
        return {}, None
    payload = _load_json(path)
    indexed: dict[str, list[dict[str, Any]]] = {}
    for record in payload.get("objects", []):
        if isinstance(record, dict) and isinstance(record.get("cbm_id"), str):
            indexed.setdefault(str(record["cbm_id"]), []).append(record)
    return indexed, path


def _binding_matches_current_uv(
    binding: Any,
    *,
    assigned_object_ids: list[str],
    detail_parents: dict[str, str],
    inventory_by_id: dict[str, list[dict[str, Any]]],
    manifest_path: Path,
) -> bool:
    """Accept a spatial binding only when IDs, UV topology, bounds, and mask are current."""

    if sorted(assigned_object_ids) != [binding.parent_object_id]:
        return False
    if detail_parents.get(binding.detail_id) != binding.parent_object_id:
        return False
    records = inventory_by_id.get(binding.parent_object_id, [])
    hashes: set[str] = set()
    for record in records:
        layer = next(
            (
                item
                for item in record.get("uv_layers", [])
                if item.get("name") == binding.uv_set
            ),
            None,
        )
        if not isinstance(layer, dict):
            return False
        fingerprint = layer.get("vertex_uv_binding_fingerprint")
        bounds = layer.get("coordinate_bounds")
        if not isinstance(fingerprint, str) or not isinstance(bounds, dict):
            return False
        values = [*bounds.get("min", []), *bounds.get("max", [])]
        if len(values) != 4 or any(not 0.0 <= float(value) <= 1.0 for value in values):
            return False
        hashes.add(fingerprint)
    if not records or hashes != {binding.uv_layout_sha256}:
        return False
    if binding.placement.mode == "mask_image":
        mask_path = (manifest_path.parent / str(binding.placement.mask_path)).resolve()
        try:
            mask_path.relative_to(manifest_path.parent.resolve())
        except ValueError:
            return False
        if (
            not mask_path.is_file()
            or sha256_file(mask_path) != binding.placement.mask_sha256
        ):
            return False
    return True


def _finding(
    findings: list[MaterialFidelityFinding],
    *,
    code: str,
    severity: str,
    message: str,
    material_id: str | None = None,
    channel: str | None = None,
    measured: float | None = None,
    threshold: float | None = None,
    evidence_paths: list[str] | None = None,
) -> None:
    """Append one normalized finding with stable rounded numeric evidence."""

    findings.append(
        MaterialFidelityFinding(
            code=code,
            severity=severity,
            message=message,
            material_id=material_id,
            channel=channel,
            measured=None if measured is None else round(measured, 6),
            threshold=None if threshold is None else round(threshold, 6),
            evidence_paths=evidence_paths or [],
        )
    )


def evaluate_material_fidelity(
    root: Path,
    *,
    thresholds: MaterialFidelityThresholds | None = None,
) -> MaterialFidelityReport:
    """Evaluate one job without mutating its canonical material or geometry evidence."""

    root = root.resolve()
    limits = thresholds or MaterialFidelityThresholds()
    plan_path = root / "analysis" / "material_plan.json"
    scene_path = root / "analysis" / "scene_spec.json"
    modeling_path = root / "analysis" / "modeling_plan.json"
    plan = load_material_plan(plan_path)
    scene_spec = _load_json(scene_path)
    modeling_plan = _load_json(modeling_path) if modeling_path.is_file() else {}
    input_hashes = {
        _relative_path(root, plan_path): sha256_file(plan_path),
        _relative_path(root, scene_path): sha256_file(scene_path),
    }
    if modeling_path.is_file():
        input_hashes[_relative_path(root, modeling_path)] = sha256_file(modeling_path)

    reference = _reference_path(root)
    reference_metrics: ImageFidelityMetrics | None = None
    reference_relative: str | None = None
    reference_sha: str | None = None
    reference_mask = _reference_mask(root)
    reference_mask_path = root / "analysis" / "masks" / "reference_content.png"
    if reference_mask is not None:
        input_hashes[_relative_path(root, reference_mask_path)] = sha256_file(
            reference_mask_path
        )
    if reference is not None:
        reference_relative = _relative_path(root, reference)
        reference_sha = sha256_file(reference)
        input_hashes[reference_relative] = reference_sha
        reference_metrics, _, _ = _image_metrics(
            reference,
            external_mask=reference_mask,
        )

    consumers = _material_consumers(scene_spec)
    detail_parents = _surface_detail_parents(modeling_plan)
    inventory_by_id, inventory_path = _inventory_uv_evidence(root)
    if inventory_path is not None:
        input_hashes[_relative_path(root, inventory_path)] = sha256_file(inventory_path)
    findings: list[MaterialFidelityFinding] = []
    materials: list[MaterialFidelityEvidence] = []
    image_material_count = 0

    for item in plan.materials:
        material_findings: list[str] = []
        assigned = consumers.get(item.material_id, [])
        manifest_relative = item.texture_manifest
        if not manifest_relative:
            materials.append(
                MaterialFidelityEvidence(
                    material_id=item.material_id,
                    shader_family=item.shader_family,
                    texture_strategy=item.texture_strategy,
                    assigned_object_ids=assigned,
                    clean_surface_expected=item.shader_family in _CLEAN_FAMILIES,
                )
            )
            continue

        manifest_path = _safe_job_path(root, manifest_relative)
        if not manifest_path.is_file():
            code = "texture_manifest_missing"
            _finding(
                findings,
                code=code,
                severity="failed",
                message="The authored texture manifest is missing.",
                material_id=item.material_id,
                evidence_paths=[manifest_relative],
            )
            material_findings.append(code)
            materials.append(
                MaterialFidelityEvidence(
                    material_id=item.material_id,
                    shader_family=item.shader_family,
                    texture_strategy=item.texture_strategy,
                    texture_manifest_path=manifest_relative,
                    assigned_object_ids=assigned,
                    clean_surface_expected=item.shader_family in _CLEAN_FAMILIES,
                    finding_codes=material_findings,
                )
            )
            continue

        manifest = load_texture_manifest(manifest_path)
        manifest_job_relative = _relative_path(root, manifest_path)
        manifest_sha = sha256_file(manifest_path)
        input_hashes[manifest_job_relative] = manifest_sha
        recipe: dict[str, Any] = {}
        if item.shader_recipe:
            recipe_path = _safe_job_path(root, item.shader_recipe)
            if recipe_path.is_file():
                recipe = _load_json(recipe_path)
                input_hashes[_relative_path(root, recipe_path)] = sha256_file(recipe_path)
        surface = recipe.get("surface", {}) if isinstance(recipe.get("surface"), dict) else {}
        emission_expected = (
            item.shader_family == "emissive"
            or float(surface.get("emission_strength", 0.0) or 0.0) > 0.0
        )
        clean_expected = _clean_surface_expected(item, manifest, recipe)
        planned_parent_ids = sorted(
            {
                detail_parents[detail_id]
                for detail_id in manifest.surface_detail_ids
                if detail_id in detail_parents
            }
        )
        binding_parent_ids = sorted(
            {binding.parent_object_id for binding in manifest.surface_detail_bindings}
        )
        binding_ids = {binding.detail_id for binding in manifest.surface_detail_bindings}
        binding_mismatches = sorted(
            binding.detail_id
            for binding in manifest.surface_detail_bindings
            if (
                binding.material_id != item.material_id
                or not _binding_matches_current_uv(
                    binding,
                    assigned_object_ids=assigned,
                    detail_parents=detail_parents,
                    inventory_by_id=inventory_by_id,
                    manifest_path=manifest_path,
                )
            )
        )
        spatially_bound = bool(manifest.surface_detail_bindings) and not binding_mismatches
        parent_ids = binding_parent_ids if spatially_bound else planned_parent_ids
        legacy_unbound_detail_ids = sorted(
            set(manifest.surface_detail_ids) - binding_ids
        )
        unbound_consumers = (
            sorted(set(assigned) - set(planned_parent_ids))
            if manifest.surface_detail_ids and not spatially_bound and planned_parent_ids
            else []
        )
        if binding_mismatches:
            code = "surface_detail_binding_mismatch"
            _finding(
                findings,
                code=code,
                severity="warning",
                message=(
                    "One or more spatial detail bindings disagree with the current material, "
                    "planned parent, or SceneSpec consumer."
                ),
                material_id=item.material_id,
                evidence_paths=[manifest_job_relative],
            )
            material_findings.append(code)
        if manifest.surface_detail_ids and not spatially_bound and unbound_consumers:
            code = "shared_detail_atlas_leakage_risk"
            _finding(
                findings,
                code=code,
                severity="warning",
                message=(
                    "A detail-bearing texture is shared by semantic objects that are not "
                    "declared parents; atlas marks may leak or repeat on those consumers."
                ),
                material_id=item.material_id,
                evidence_paths=[manifest_job_relative],
            )
            material_findings.append(code)
        detail_pattern = str(manifest.procedural.get("detail_pattern", "none"))
        if (
            manifest.surface_detail_ids
            and not spatially_bound
            and detail_pattern not in {"", "none"}
        ):
            code = "global_detail_pattern_repeat_risk"
            _finding(
                findings,
                code=code,
                severity="warning",
                message=(
                    "A legacy global detail pattern has no validated spatial binding; it may "
                    "repeat across unrelated UV islands or material consumers."
                ),
                material_id=item.material_id,
                evidence_paths=[manifest_job_relative],
            )
            material_findings.append(code)

        channel_evidence: list[MaterialChannelEvidence] = []
        has_image_channel = False
        for channel_name, channel in sorted(manifest.channels.items()):
            if channel.source != "image" or not channel.path:
                continue
            has_image_channel = True
            channel_path = (manifest_path.parent / channel.path).resolve()
            try:
                channel_path.relative_to(root)
            except ValueError:
                code = "texture_channel_path_escape"
                _finding(
                    findings,
                    code=code,
                    severity="failed",
                    message="A texture channel path escapes the job root.",
                    material_id=item.material_id,
                    channel=channel_name,
                    evidence_paths=[manifest_job_relative],
                )
                material_findings.append(code)
                continue
            channel_relative = _relative_path(root, channel_path)
            if not channel_path.is_file():
                code = "texture_channel_missing"
                _finding(
                    findings,
                    code=code,
                    severity="failed",
                    message="A declared image texture channel is missing.",
                    material_id=item.material_id,
                    channel=channel_name,
                    evidence_paths=[channel_relative, manifest_job_relative],
                )
                material_findings.append(code)
                continue
            channel_sha = sha256_file(channel_path)
            input_hashes[channel_relative] = channel_sha
            declared_sha = (
                manifest.provenance.generated_sha256.get(channel_name)
                if manifest.provenance is not None
                else None
            )
            if declared_sha is not None and declared_sha != channel_sha:
                code = "texture_channel_hash_mismatch"
                _finding(
                    findings,
                    code=code,
                    severity="failed",
                    message=(
                        "An image channel differs from the SHA-256 declared by its "
                        "generation provenance."
                    ),
                    material_id=item.material_id,
                    channel=channel_name,
                    evidence_paths=[channel_relative, manifest_job_relative],
                )
                material_findings.append(code)
            metrics, sampled_image, active = _image_metrics(channel_path)
            normal = _normal_metrics(sampled_image, active) if channel_name == "normal" else None
            emission = (
                _emission_metrics(sampled_image, active, None)
                if channel_name == "emission"
                else None
            )
            channel_evidence.append(
                MaterialChannelEvidence(
                    channel=channel_name,
                    relative_path=channel_relative,
                    sha256=channel_sha,
                    image=metrics,
                    normal=normal,
                    emission=emission,
                )
            )
            if channel_name == "base_color" and clean_expected:
                if (
                    metrics.dark_contrast_fraction > limits.dark_contrast_fraction_max
                    or metrics.dark_band_fraction > limits.dark_band_fraction_max
                ):
                    code = "dark_line_excess"
                    _finding(
                        findings,
                        code=code,
                        severity="warning",
                        message=(
                            "Clean-surface Base Color contains excessive dark contrasting "
                            "pixels or full-field bands."
                        ),
                        material_id=item.material_id,
                        channel=channel_name,
                        measured=max(
                            metrics.dark_contrast_fraction,
                            metrics.dark_band_fraction,
                        ),
                        threshold=max(
                            limits.dark_contrast_fraction_max,
                            limits.dark_band_fraction_max,
                        ),
                        evidence_paths=[channel_relative],
                    )
                    material_findings.append(code)
                if metrics.relative_variation > limits.relative_variation_max:
                    code = "full_field_variation_excess"
                    _finding(
                        findings,
                        code=code,
                        severity="warning",
                        message=(
                            "Clean-surface Base Color varies more than the deterministic "
                            "V0.5 fidelity threshold."
                        ),
                        material_id=item.material_id,
                        channel=channel_name,
                        measured=metrics.relative_variation,
                        threshold=limits.relative_variation_max,
                        evidence_paths=[channel_relative],
                    )
                    material_findings.append(code)
                if metrics.residual_noise_mean > limits.residual_noise_mean_max:
                    code = "high_frequency_noise_excess"
                    _finding(
                        findings,
                        code=code,
                        severity="warning",
                        message="Clean-surface Base Color contains excess high-frequency noise.",
                        material_id=item.material_id,
                        channel=channel_name,
                        measured=metrics.residual_noise_mean,
                        threshold=limits.residual_noise_mean_max,
                        evidence_paths=[channel_relative],
                    )
                    material_findings.append(code)
            if normal is not None and clean_expected:
                if (
                    normal.mean_deviation_deg > limits.normal_mean_deviation_deg_max
                    or normal.p95_deviation_deg > limits.normal_p95_deviation_deg_max
                ):
                    code = "normal_deviation_excess"
                    _finding(
                        findings,
                        code=code,
                        severity="warning",
                        message=(
                            "Clean-surface normal detail deviates too strongly from a flat "
                            "tangent-space normal."
                        ),
                        material_id=item.material_id,
                        channel=channel_name,
                        measured=max(normal.mean_deviation_deg, normal.p95_deviation_deg),
                        threshold=max(
                            limits.normal_mean_deviation_deg_max,
                            limits.normal_p95_deviation_deg_max,
                        ),
                        evidence_paths=[channel_relative],
                    )
                    material_findings.append(code)
            emission_is_localized = any(
                channel_name in binding.channels
                for binding in manifest.surface_detail_bindings
            )
            if emission is not None and emission_expected and not emission_is_localized:
                if emission.active_fraction < limits.emission_active_fraction_min:
                    code = "emission_coverage_low"
                    _finding(
                        findings,
                        code=code,
                        severity="warning",
                        message="Emission coverage is sparse or strongly mottled.",
                        material_id=item.material_id,
                        channel=channel_name,
                        measured=emission.active_fraction,
                        threshold=limits.emission_active_fraction_min,
                        evidence_paths=[channel_relative],
                    )
                    material_findings.append(code)
                if (
                    emission.hue_error_deg is not None
                    and emission.hue_error_deg > limits.emission_hue_error_deg_max
                ):
                    code = "emission_hue_mismatch"
                    _finding(
                        findings,
                        code=code,
                        severity="warning",
                        message=(
                            "Dominant emission hue differs substantially from the dominant "
                            "saturated reference evidence."
                        ),
                        material_id=item.material_id,
                        channel=channel_name,
                        measured=emission.hue_error_deg,
                        threshold=limits.emission_hue_error_deg_max,
                        evidence_paths=[channel_relative, reference_relative]
                        if reference_relative
                        else [channel_relative],
                    )
                    material_findings.append(code)
        if has_image_channel:
            image_material_count += 1
            code = "material_channels_measured"
            _finding(
                findings,
                code=code,
                severity="info",
                message="Image-backed V0.5 channels were measured and hash-bound.",
                material_id=item.material_id,
                evidence_paths=[manifest_job_relative],
            )
            material_findings.append(code)
        materials.append(
            MaterialFidelityEvidence(
                material_id=item.material_id,
                shader_family=item.shader_family,
                texture_strategy=item.texture_strategy,
                texture_manifest_path=manifest_job_relative,
                texture_manifest_sha256=manifest_sha,
                assigned_object_ids=assigned,
                declared_surface_detail_ids=manifest.surface_detail_ids,
                declared_detail_parent_ids=parent_ids,
                spatial_binding_count=len(manifest.surface_detail_bindings),
                legacy_unbound_detail_ids=legacy_unbound_detail_ids,
                unbound_consumer_ids=unbound_consumers,
                clean_surface_expected=clean_expected,
                channels=channel_evidence,
                finding_codes=sorted(set(material_findings)),
            )
        )

    if image_material_count == 0:
        _finding(
            findings,
            code="no_image_material_evidence",
            severity="info",
            message="No image-backed V0.5 material channels were available for raster scoring.",
        )
    counts = {
        severity: sum(item.severity == severity for item in findings)
        for severity in ("info", "warning", "failed")
    }
    status = (
        "failed"
        if counts["failed"]
        else "unscorable"
        if image_material_count == 0
        else "warning"
        if counts["warning"]
        else "passed"
    )
    return MaterialFidelityReport(
        job_id=plan.job_id,
        status=status,
        ok=counts["failed"] == 0,
        source_fingerprint=_source_fingerprint(input_hashes),
        input_hashes=dict(sorted(input_hashes.items())),
        reference_path=reference_relative,
        reference_sha256=reference_sha,
        reference_metrics=reference_metrics,
        thresholds=limits,
        material_count=len(plan.materials),
        image_material_count=image_material_count,
        passed=counts["info"],
        warnings=counts["warning"],
        failed=counts["failed"],
        materials=materials,
        findings=findings,
        notes=[
            "Measurements are authoritative; thresholds are conservative V0.5 warnings, not "
            "proof of artistic correctness.",
            "Per-material reference hue remains unscorable without an explicit material or "
            "surface-detail reference ROI.",
            "Shared-detail findings identify leakage risk only for legacy or invalid manifests "
            "without a validated object-and-UV spatial binding.",
        ],
    )


def validate_job_material_fidelity(job_id: str) -> dict[str, Any]:
    """Write one authoritative job-local fidelity report without changing authoring data."""

    root = job_dir(job_id)
    report = evaluate_material_fidelity(root)
    output = root / "reports" / "material_fidelity_validation.json"
    write_json_atomic(output, report.model_dump(mode="json"))
    result = report.model_dump(mode="json")
    result["path"] = _relative_path(root, output)
    result["sha256"] = sha256_file(output)
    return result


def load_job_material_fidelity_report(job_id: str) -> dict[str, Any]:
    """Load the latest authoritative V0.5 material-fidelity JSON for one job."""

    path = job_dir(job_id) / "reports" / "material_fidelity_validation.json"
    if not path.is_file():
        raise FileNotFoundError(f"Material fidelity report does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
