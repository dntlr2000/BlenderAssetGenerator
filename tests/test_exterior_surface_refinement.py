"""Pure regression tests for explicit exterior geometry/material hypotheses."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/replay_exterior_surface_refinement.py"
SPEC = importlib.util.spec_from_file_location("exterior_refinement", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def shell_fixture():
    """Provide independent front support and a deliberately rippled reverse patch."""
    grid = np.array(
        [[x, y, 0.03 * x * x + 0.01 * y * y] for x in (-1, 0, 1) for y in (-1, 0, 1)], dtype=float
    )
    back = grid.copy()
    back[:, 2] -= 0.1
    back[:, 2] += np.array([0, 0.02, 0, -0.02, 0.01, -0.02, 0, 0.02, 0])
    return np.vstack([grid, back])


def shell_kwargs():
    """Use an explicit bounded recipe over the synthetic reverse patch."""
    return dict(
        basis=np.eye(3).tolist(),
        fit_indices=list(range(9)),
        target_indices=list(range(9, 18)),
        weights=[1] * 9,
        depth_offset=-0.1,
        maximum_displacement=0.04,
    )


def test_shell_regularization_is_deterministic_and_keeps_front():
    """Only the declared reverse depth changes, with exact reproducible F32 output."""
    source = shell_fixture()
    a, report = MODULE.quadratic_depth_regularize(source, **shell_kwargs())
    b, _ = MODULE.quadratic_depth_regularize(source, **shell_kwargs())
    assert a == b
    result = np.array(a)
    assert np.array_equal(result, result.astype(np.float32).astype(float))
    assert np.allclose(result[:9], source[:9], atol=2e-9)
    assert np.array_equal(result[:, :2], source[:, :2])
    assert np.allclose(result[9:, 2], source[:9, 2] - 0.1, atol=1e-8)
    assert report["maximum_displacement"] < 0.021


def test_shell_zero_weights_lock_boundary():
    """Explicit zero-weight vertices retain their quantized coordinates."""
    options = shell_kwargs()
    options["weights"] = [0] * 9
    source = shell_fixture()
    result, _ = MODULE.quadratic_depth_regularize(source, **options)
    assert np.array_equal(np.asarray(result), source.astype(np.float32).astype(float))


@pytest.mark.parametrize(
    "change",
    [
        {"basis": [[2, 0, 0], [0, 1, 0], [0, 0, 1]]},
        {"weights": [2] * 9},
        {"weights": [float("nan")] * 9},
        {"target_indices": [9] * 9},
        {"target_indices": [99] * 9},
        {"maximum_displacement": 0.001},
        {"fit_indices": [0, 1, 2, 0, 1, 2]},
        {"target_indices": [9.1] + list(range(10, 18))},
        {"target_indices": [True] + list(range(10, 18))},
        {"target_indices": []},
    ],
)
def test_shell_rejects_unbounded_or_invalid_recipe(change):
    """Malformed geometry authority fails rather than widening the selected scope."""
    options = shell_kwargs()
    options.update(change)
    with pytest.raises(ValueError):
        MODULE.quadratic_depth_regularize(shell_fixture(), **options)


def test_profile_fairing_preserves_longitudinal_stations():
    """Cross-section fairing cannot slide end stations or change array topology."""
    source = np.array(
        [[x, y, z] for x in (-1, 1) for y, z in [(0, 1), (1, 0), (0, -1), (-1, 0)]], dtype=float
    )
    output, _ = MODULE.fair_ring_profiles(
        source,
        ring_size=4,
        ring_count=2,
        axis=0,
        vertex_weights=[0.2] * 8,
        iterations=2,
        maximum_displacement=0.5,
    )
    assert np.array(output).shape == source.shape
    assert np.array_equal(np.array(output)[:, 0], source[:, 0])
    assert np.max(np.abs(np.array(output)[:, 1:])) < 1


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_nonfinite_coordinates_rejected(bad):
    """Nonfinite payloads never enter a Blender handoff."""
    source = shell_fixture()
    source[0, 0] = bad
    with pytest.raises(ValueError):
        MODULE.quadratic_depth_regularize(source, **shell_kwargs())


def test_normal_attenuation_reduces_slopes():
    """Normal attenuation changes physical slope response without channel inversion."""
    source = np.array([[[200, 90, 225], [140, 170, 242]]], dtype=np.uint8)
    output = MODULE.normal_strength(source, 0.24)
    assert output.shape == source.shape
    assert np.all(
        np.abs(output[..., :2].astype(float) - 127.5)
        < np.abs(source[..., :2].astype(float) - 127.5)
    )
    assert np.all(output[..., 2] >= source[..., 2])


def test_metal_response_separates_existing_regions():
    """An existing mask creates conductive smoother metal and rough dielectric oxide."""
    color = np.array([[[70, 40, 25], [80, 81, 77]]], dtype=np.uint8)
    metallic = np.array([[6, 204]], dtype=np.uint8)
    roughness = np.array([[215, 180]], dtype=np.uint8)
    _, metal, rough = MODULE.oxide_metal_response(color, metallic, roughness)
    assert metal[0, 0] < 10 and metal[0, 1] > 230
    assert rough[0, 0] > 200 and rough[0, 1] < 140


def test_material_dimension_mismatch_rejected():
    """Differently sized technical maps fail instead of broadcasting silently."""
    with pytest.raises(ValueError):
        MODULE.oxide_metal_response(np.zeros((4, 4, 3)), np.zeros((2, 2)), np.zeros((4, 4)))
