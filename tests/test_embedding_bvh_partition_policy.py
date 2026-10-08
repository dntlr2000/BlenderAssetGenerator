"""Partition changes retain complete closed-box pairs, determinism and unchanged caps."""

import itertools
import math
import random

import pytest

from codex_blender_modeler.structural_geometry import solid_root_ball as r


def expected(bounds):
    """Compute a separate exact inclusive all-pairs oracle."""
    return {
        (i, j)
        for i, j in itertools.combinations(range(len(bounds)), 2)
        if all(
            bounds[i][1][a] >= bounds[j][0][a] and bounds[j][1][a] >= bounds[i][0][a]
            for a in range(3)
        )
    }


@pytest.mark.parametrize("count", [3, 4, 5, 8, 17, 65, 129, 257])
@pytest.mark.parametrize("kind", ["coincident", "touching", "separated", "thin", "random"])
def test_complete_pairs_and_work_are_deterministic(count, kind):
    """The overlap-aware terminal partition changes no closed-contact candidate."""
    rng = random.Random(91537 + count)
    if kind == "coincident":
        boxes = [((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))] * count
    elif kind == "touching":
        boxes = [((float(i), 0.0, 0.0), (float(i + 1), 1.0, 1.0)) for i in range(count)]
    elif kind == "separated":
        boxes = [((float(i * 2), 0.0, 0.0), (float(i * 2 + 1), 1.0, 1.0)) for i in range(count)]
    elif kind == "thin":
        boxes = [
            ((0.0, i * 0.001, 0.0), (8.0, i * 0.001, math.nextafter(0.0, math.inf)))
            for i in range(count)
        ]
    else:
        lows = [tuple(rng.randrange(-8, 9) / 8 for _ in range(3)) for _ in range(count)]
        boxes = [(p, tuple(x + rng.choice([0.0, 0.125, 1.0]) for x in p)) for p in lows]
    first = r.Budget()
    second = r.Budget()
    one = list(r.embedding_candidate_pairs(boxes, first))
    two = list(r.embedding_candidate_pairs(boxes, second))
    assert one == two and len(one) == len(set(one)) and set(one) == expected(boxes)
    assert first.embedding_scans == second.embedding_scans


def test_terminal_partition_and_tree_coverage():
    """Every original box belongs to exactly one small leaf without inferred subdivision."""
    boxes = [((float(i), 0.0, 0.0), (float(i + 1), 1.0, 1.0)) for i in range(29)]
    root = r._build_box_tree(boxes, tuple(range(len(boxes))), r.Budget())
    pending = [root]
    seen = []
    while pending:
        node = pending.pop()
        if node.children:
            pending.extend(node.children)
        else:
            assert 1 <= len(node.indices) <= 4
            if len(node.indices) == 4:
                assert all(
                    max(boxes[i][0][a] for i in node.indices)
                    <= min(boxes[i][1][a] for i in node.indices)
                    for a in range(3)
                )
            seen.extend(node.indices)
    assert sorted(seen) == list(range(len(boxes)))


def test_shared_work_cap_remains_exactly_one_million():
    """Near-boundary hierarchy construction exhausts instead of resetting or raising the cap."""
    budget = r.Budget()
    budget.embedding_scans[0] = 999999
    with pytest.raises(r.Unverified, match="work budget exhausted"):
        list(r.embedding_candidate_pairs([((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))] * 4, budget))
    assert budget.embedding_scans[0] > 1000000
    with pytest.raises(r.Unverified):
        r.Budget(limit=1000001)
    with pytest.raises(r.Unverified):
        r.Budget().claim_component(4097)


def test_worst_case_overlap_fails_closed_at_same_cap():
    """Large indistinguishable boxes cannot evade finite work through favorable partitioning."""
    budget = r.Budget()
    with pytest.raises(r.Unverified, match="work budget exhausted"):
        list(r.embedding_candidate_pairs([((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))] * 1500, budget))
    assert budget.embedding_scans == [1000001]
