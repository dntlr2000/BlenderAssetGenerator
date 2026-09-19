"""Closed-shell admission and authority negatives; no fixture is campaign quality evidence."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_aq_geometry_preflight import _preflight, _request, _tree_hashes
from test_aq_geometry_preflight import authoring as authoring

from codex_blender_modeler.structural_geometry import service
from codex_blender_modeler.structural_geometry.models import StructuralGeometryCandidate
from codex_blender_modeler.structural_geometry.triangle_shell import TriangulatedShellGeometry
from codex_blender_modeler.structural_geometry.triangle_shell_math import (
    validate_triangle_shell_data,
)


def tetra_shell() -> dict:
    """Return a generic outward tetrahedron with explicit UV seams at its triangle corners."""
    return {
        "kind": "triangulated_shell",
        "vertices": [[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]],
        "triangles": [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
        "loop_uvs": [[0., 0.], [1., 0.], [0., 1.]] * 4,
    }


def parse(value: dict) -> TriangulatedShellGeometry:
    """Validate serialized input using the same strict JSON boundary as the host."""
    return TriangulatedShellGeometry.model_validate_json(json.dumps(value))


def test_closed_shell_preserves_exact_geometry_and_corner_uvs() -> None:
    """Keep author order, coordinates, triangle winding and deliberately split UV values."""
    value = tetra_shell()
    validate_triangle_shell_data(value)
    assert parse(value).model_dump(mode="json") == value
    value["loop_uvs"] = None
    validate_triangle_shell_data(value)
    assert parse(value).loop_uvs is None


@pytest.mark.parametrize("extra", ["path", "script", "callback", "material_id", "driver"])
def test_closed_shell_cannot_supply_execution_or_external_authority(extra: str) -> None:
    """Reject executable, path-backed and material side channels at strict parsing."""
    value = tetra_shell()
    value[extra] = "untrusted"
    with pytest.raises(ValidationError, match="Extra inputs"):
        parse(value)
    with pytest.raises(ValueError):
        validate_triangle_shell_data(value)


@pytest.mark.parametrize("bad_index", [-1, 4, True, 1.5, "1"])
def test_closed_shell_rejects_unsafe_indices(bad_index: object) -> None:
    """Reject out-of-range, coerced and ambiguous triangle indices before any Blender run."""
    value = tetra_shell()
    value["triangles"][0][0] = bad_index
    with pytest.raises(ValidationError):
        parse(value)
    with pytest.raises(ValueError):
        validate_triangle_shell_data(value)


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), 1.0e7, True, "1"])
def test_closed_shell_rejects_nonfinite_or_unbounded_coordinates(coordinate: float) -> None:
    """Reject invalid position data without reaching the mesh constructor."""
    value = tetra_shell()
    value["vertices"][0][0] = coordinate
    with pytest.raises(ValidationError):
        parse(value)
    with pytest.raises(ValueError):
        validate_triangle_shell_data(value)


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), 1.0e7, True, "1"])
def test_closed_shell_rejects_unbounded_corner_uvs(coordinate: float) -> None:
    """Reject UV values that cannot safely cross the bounded float mesh boundary."""
    value = tetra_shell()
    value["loop_uvs"][0][0] = coordinate
    with pytest.raises(ValidationError):
        parse(value)
    with pytest.raises(ValueError):
        validate_triangle_shell_data(value)


@pytest.mark.parametrize(
    "failure",
    ["open", "duplicate", "winding", "inward", "unused", "flat", "volume", "coincident", "uv"],
)
def test_closed_shell_rejects_invalid_topology_and_corner_contracts(failure: str) -> None:
    """Exercise independent closedness, orientation, geometry and corner-identity failures."""
    value = tetra_shell()
    if failure == "open":
        value["triangles"].pop()
    elif failure == "duplicate":
        value["triangles"][1] = value["triangles"][0]
    elif failure == "winding":
        value["triangles"][0].reverse()
    elif failure == "inward":
        value["triangles"] = [list(reversed(face)) for face in value["triangles"]]
    elif failure == "unused":
        value["vertices"].append([2., 2., 2.])
    elif failure == "flat":
        value["vertices"][3] = [2., 0., 0.]
    elif failure == "volume":
        value["vertices"][3] = [0.2, 0.2, 0.]
    elif failure == "coincident":
        value["vertices"][3] = value["vertices"][0]
    elif failure == "uv":
        value["loop_uvs"].pop()
    with pytest.raises(ValidationError):
        parse(value)
    with pytest.raises(ValueError):
        validate_triangle_shell_data(value)


def test_closed_shell_rejects_disconnected_solids() -> None:
    """Reject two separate closed surfaces even though every edge has incidence two."""
    value = tetra_shell()
    value["vertices"] += [[point[0] + 3., point[1], point[2]] for point in value["vertices"]]
    value["triangles"] += [[index + 4 for index in face] for face in value["triangles"]]
    value["loop_uvs"] *= 2
    with pytest.raises(ValidationError, match="one connected surface"):
        parse(value)
    with pytest.raises(ValueError, match="one connected surface"):
        validate_triangle_shell_data(value)


def test_closed_shell_limits_input_size() -> None:
    """Apply strict input bounds before processing oversized triangle data."""
    value = tetra_shell()
    value["triangles"] = [[0, 2, 1]] * 131073
    value["loop_uvs"] = None
    with pytest.raises(ValidationError, match="at most 131072"):
        parse(value)
    with pytest.raises(ValueError):
        validate_triangle_shell_data(value)


@pytest.mark.parametrize("field", ["vertices", "triangles", "loop_uvs"])
def test_runtime_rejects_malformed_vectors_without_coercion(field: str) -> None:
    """Keep direct runtime admission fail-closed when a caller bypasses host parsing."""
    value = tetra_shell()
    value[field][0] = {"0": 0, "1": 1, "2": 2}
    with pytest.raises(ValueError):
        validate_triangle_shell_data(value)


def test_runtime_handles_oversized_integer_without_float_overflow() -> None:
    """Reject huge Python integers before attempting a floating-point finiteness check."""
    value = tetra_shell()
    value["vertices"][0][0] = 10 ** 400
    with pytest.raises(ValueError, match="finite bounded"):
        validate_triangle_shell_data(value)


def test_runtime_validation_does_not_require_host_site_packages() -> None:
    """Import and run the shared validator with site packages disabled, as Blender needs."""
    source = str(Path(__file__).resolve().parents[1] / "src")
    script = (
        "import json, sys; sys.path.insert(0, sys.argv[1]); "
        "from codex_blender_modeler.structural_geometry.triangle_shell_math "
        "import validate_triangle_shell_data; "
        "validate_triangle_shell_data(json.loads(sys.argv[2])); "
        "assert 'pydantic' not in sys.modules"
    )
    subprocess.run([sys.executable, "-B", "-S", "-c", script, source, json.dumps(tetra_shell())],
        check=True, capture_output=True, text=True, timeout=30)


def test_legacy_materialization_rejects_new_shell_before_io(tmp_path: Path, monkeypatch) -> None:
    """Require an explicit MeshPayload 0.2 call without altering legacy defaults or files."""
    calls = []
    monkeypatch.setattr(service, "run_blender", lambda *args, **kwargs: calls.append(args))
    candidate = StructuralGeometryCandidate.model_validate_json(json.dumps({
        "semantic_id": "fixture.shell", "geometry": tetra_shell(),
    }))
    root = tmp_path / "not_created"
    with pytest.raises(ValueError, match="explicit MeshPayload 0.2"):
        service.materialize_structural_candidate(job_root=root, candidate=candidate,
            candidate_relative_path="recipe.json", mesh_relative_path="mesh.json",
            blend_relative_path="mesh.blend", report_relative_path="report.json")
    assert calls == [] and not root.exists()


def test_shell_aq_preflight_remains_read_only_and_exact(authoring) -> None:
    """Admit the new strict recipe through the real preflight without consuming authority."""
    root, _session, scene = authoring
    scene["objects"][0]["geometry"] = tetra_shell()
    path = root / "fidelity/preflight/scene_spec_v03.json"
    path.write_text(json.dumps(scene), encoding="utf-8")
    before = _tree_hashes(root)
    report = _preflight(authoring)
    assert report.outcome == "passed" and report.candidate_object_count == 3
    assert _tree_hashes(root) == before
    changed = copy.deepcopy(scene)
    changed["objects"][0]["geometry"]["vertices"][3][2] = 1.1
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises((ValueError, PermissionError), match="changed|stale|differ|hash"):
        _request(authoring, report)
