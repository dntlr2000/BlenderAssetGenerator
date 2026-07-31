from __future__ import annotations

import pytest
from pydantic import ValidationError

from codex_blender_modeler.models import NormalTransferModifier


def test_normal_transfer_modifier_accepts_bounded_boundary_contract() -> None:
    """Accept one deterministic boundary-only custom-normal transfer declaration."""

    modifier = NormalTransferModifier(
        target_id="submarine.hull.main",
        max_distance=0.08,
        boundary_axis="X",
        boundary_side="MIN",
        boundary_width=0.12,
        mix_factor=1.0,
    )
    assert modifier.model_dump(mode="json") == {
        "kind": "normal_transfer",
        "target_id": "submarine.hull.main",
        "max_distance": 0.08,
        "boundary_axis": "X",
        "boundary_side": "MIN",
        "boundary_width": 0.12,
        "mix_factor": 1.0,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_distance", 0.0),
        ("boundary_width", 0.0),
        ("mix_factor", 0.0),
        ("mix_factor", 1.01),
        ("boundary_axis", "W"),
        ("boundary_side", "BOTH"),
    ],
)
def test_normal_transfer_modifier_rejects_unbounded_values(
    field: str,
    value: object,
) -> None:
    """Reject normal-transfer settings outside the whitelisted bounded contract."""

    payload = {"target_id": "submarine.hull.main", field: value}
    with pytest.raises(ValidationError):
        NormalTransferModifier.model_validate(payload)
