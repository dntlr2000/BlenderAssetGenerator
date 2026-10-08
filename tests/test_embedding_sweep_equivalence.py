"""Adversarial equivalence and work-budget tests for exact embedding broad phase."""
import itertools
import random

import pytest

from codex_blender_modeler.structural_geometry.profiled_relief import _embedding_candidate_pairs


def legacy_pairs(bounds):
    """Reproduce the previous candidate ordering without invoking contact predicates."""
    active = []
    result = []
    for index in sorted(range(len(bounds)), key=lambda i: (bounds[i][0][0], i)):
        low, high = bounds[index]
        active = [other for other in active if bounds[other][1][0] >= low[0]]
        for other in active:
            other_low, other_high = bounds[other]
            if not any(high[a] < other_low[a] or other_high[a] < low[a] for a in (1, 2)):
                result.append((other, index))
        active.append(index)
    return result


def test_closed_boxes_equal_legacy_and_all_pairs():
    """Keep every touching, nested, coincident, skinny and disconnected AABB pair."""
    rng = random.Random(71823)
    boxes = []
    for _ in range(250):
        low = tuple(rng.randrange(-8, 9) / 8 for _ in range(3))
        high = tuple(x + rng.choice((0, 2**-30, .125, 1, 4)) for x in low)
        boxes.append((low, high))
    boxes += [((0, 0, 0), (1, 1, 1)), ((1, 1, 1), (2, 2, 2))] * 3
    actual = list(_embedding_candidate_pairs(boxes))
    assert actual == legacy_pairs(boxes)
    brute = {
        (a, b) for a, b in itertools.combinations(range(len(boxes)), 2)
        if all(
            boxes[a][1][k] >= boxes[b][0][k] and boxes[b][1][k] >= boxes[a][0][k]
            for k in range(3)
        )
    }
    assert {tuple(sorted(pair)) for pair in actual} == brute
    assert len(actual) == len(brute)


def test_expiry_keeps_boundary_touch_and_rejects_next_float_gap():
    """Use exact closed comparisons, without an epsilon or contact omission."""
    import math
    boxes = [((0, 0, 0), (1, 1, 1)), ((1, 0, 0), (2, 1, 1)),
             ((math.nextafter(2, math.inf), 0, 0), (3, 1, 1))]
    assert list(_embedding_candidate_pairs(boxes)) == [(0, 1)]


def test_actual_work_budget_is_shared_and_fails_closed():
    """Charge all pushes, expired removals and candidate scans across components."""
    boxes = [((0, 0, 0), (1, 1, 1)), ((2, 0, 0), (3, 1, 1))]
    budget = [0]
    assert list(_embedding_candidate_pairs(boxes, scan_budget=budget, max_scans=6)) == []
    assert budget == [3]
    assert list(_embedding_candidate_pairs(boxes, scan_budget=budget, max_scans=6)) == []
    assert budget == [6]
    with pytest.raises(ValueError, match='scan budget exhausted'):
        list(_embedding_candidate_pairs(boxes, scan_budget=budget, max_scans=6))


def test_active_scan_is_charged_even_when_other_axes_are_disjoint():
    """The budget cannot ignore unsuccessful AABB scans or only charge exact pairs."""
    boxes = [((0, 0, 0), (2, 1, 1)), ((1, 2, 0), (3, 3, 1))]
    budget = [0]
    assert list(_embedding_candidate_pairs(boxes, scan_budget=budget, max_scans=3)) == []
    assert budget == [3]
    with pytest.raises(ValueError, match='scan budget exhausted'):
        list(_embedding_candidate_pairs(boxes, scan_budget=[0], max_scans=2))
