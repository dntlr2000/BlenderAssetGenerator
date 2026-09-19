"""Exact opt-in lighting contracts, unchanged legacy budgets and bounded render failures."""

from __future__ import annotations

import copy
import json
import math

import pytest
from test_fidelity_budget_epoch import funded_loop, funding
from test_quality_revision_flow import quality_fixture

from codex_blender_modeler.autonomy_v2 import quality_revision_service as host
from codex_blender_modeler.autonomy_v2.quality_revision_models import (
    AQQualityRevisionLoopV04,
    parse_quality_revision_loop,
)
from codex_blender_modeler.comparison_lighting import (
    CAMERA_STUDIO_PROFILE,
    camera_studio_rig,
    lighting_implementation_sha256,
    validate_camera_studio_conditions,
    validate_lighting_selection,
)
from codex_blender_modeler.qa import service as qa_service
from codex_blender_modeler.reference_fidelity.service import publish

CAMERA = {"location": [2.0, -4.0, 2.0], "target": [0.0, 0.0, .2]}


def selected_loop(legacy=None):
    """Add only the exact lighting selection to one unchanged funded test loop."""
    legacy = legacy or funded_loop(funding())
    return AQQualityRevisionLoopV04.model_validate({
        **legacy.model_dump(), "schema_version": "0.4.0",
        "comparison_lighting_profile": CAMERA_STUDIO_PROFILE,
        "lighting_implementation_sha256": lighting_implementation_sha256(),
    })


def conditions(camera=CAMERA):
    """Build synthetic recorded lamps for tamper tests, never actual Blender evidence."""
    rig = camera_studio_rig(camera)
    lights = []
    for item in rig["lights"]:
        direction = [a - b for a, b in zip(item["location"], item["target"], strict=True)]
        length = math.sqrt(sum(value ** 2 for value in direction))
        matrix = [[0.0] * 4 for _ in range(4)]
        matrix[3][3] = 1.0
        for i in range(3):
            matrix[i][2], matrix[i][3] = direction[i] / length, item["location"][i]
        lights.append({"type": "AREA", "shape": "DISK", "hide_render": False,
            "matrix_world": matrix, "energy": item["energy"], "size": item["size"],
            "color": [1.0, 1.0, 1.0]})
    return {"comparison_lighting_profile": CAMERA_STUDIO_PROFILE,
        "lighting_implementation_sha256": lighting_implementation_sha256(), "lights": lights,
        "world": {"backgrounds": [{"color": rig["world_color"], "strength": rig["world_strength"]}],
            "links": [["ShaderNodeBackground", "Background", "ShaderNodeOutputWorld", "Surface"]]},
        **{key: rig[key] for key in (
            "view_transform", "look", "exposure", "gamma", "film_transparent")}}


def test_v04_is_explicit_and_inherits_identical_finite_funding():
    """Selecting lighting cannot allocate another revision, switch, build or human authority."""
    legacy = funded_loop(funding())
    before = legacy.model_dump_json()
    loop = selected_loop(legacy)
    parsed = parse_quality_revision_loop(loop.model_dump_json().encode())
    assert type(parsed) is AQQualityRevisionLoopV04
    assert parsed.funding == legacy.funding
    assert parsed.cost_limit == legacy.cost_limit
    assert parsed.initial_pipeline_reserve == legacy.initial_pipeline_reserve
    assert parsed.strategy_switch_limit == legacy.strategy_switch_limit == 1
    assert not parsed.human_approval_authority
    assert legacy.model_dump_json() == before
    with pytest.raises(ValueError):
        parse_quality_revision_loop(before.replace('"0.3.0"', '"0.4.0"', 1).encode())
    data = json.loads(before)
    data['comparison_lighting_profile'] = CAMERA_STUDIO_PROFILE
    with pytest.raises(ValueError):
        parse_quality_revision_loop(json.dumps(data).encode())


@pytest.mark.parametrize(('profile', 'fingerprint'), [
    ('unknown', 'a' * 64), (None, 'a' * 64), (CAMERA_STUDIO_PROFILE, None),
    (CAMERA_STUDIO_PROFILE, '0' * 64),
])
def test_unknown_partial_or_stale_selection_fails_before_outputs(tmp_path, profile, fingerprint):
    """Reject bad contracts before job lookup, output creation or any Blender invocation."""
    with pytest.raises(ValueError):
        qa_service.run_scene_spec_visual_qa_snapshot('missing_job',
            scene_spec_path=tmp_path / 'scene.json', blend_path=tmp_path / 'source.blend',
            run_dir=tmp_path / 'qa', run_id='negative', record_fidelity_conditions=True,
            comparison_lighting_profile=profile, lighting_implementation_sha256=fingerprint)
    assert list(tmp_path.iterdir()) == []
    validate_lighting_selection(None, None)


def test_unrecorded_lighting_cannot_render(tmp_path):
    """Require actual condition evidence instead of accepting a preset name as proof."""
    with pytest.raises(ValueError, match='condition evidence'):
        qa_service.run_scene_spec_visual_qa_snapshot('missing_job',
            scene_spec_path=tmp_path / 'scene.json', blend_path=tmp_path / 'source.blend',
            run_dir=tmp_path / 'qa', run_id='negative',
            comparison_lighting_profile=CAMERA_STUDIO_PROFILE,
            lighting_implementation_sha256=lighting_implementation_sha256())
    assert not (tmp_path / 'qa').exists()


def test_camera_scale_keeps_lighting_solid_angle_and_power_density():
    """A different asset scale must not receive the old distant, fixed-energy key light."""
    original = camera_studio_rig(CAMERA)
    scale, translation = 7.0, [4.0, -1.0, 8.0]
    moved = {key: [value * scale + offset
                   for value, offset in zip(vector, translation, strict=True)]
             for key, vector in CAMERA.items()}
    transformed = camera_studio_rig(moved)
    for first, second in zip(original['lights'], transformed['lights'], strict=True):
        assert second['energy'] == pytest.approx(first['energy'] * scale ** 2)
        assert second['size'] == pytest.approx(first['size'] * scale)
        assert second['location'] == pytest.approx([
            value * scale + offset
            for value, offset in zip(first['location'], translation, strict=True)])
    assert camera_studio_rig({**CAMERA, 'candidate_bounds': [1, 100]}) == original


@pytest.mark.parametrize('location', [[0, 0, .2], [True, 0, 3], ['2', 0, 3], [math.nan, 0, 3]])
def test_invalid_camera_has_no_approximate_lighting_fallback(location):
    """Degenerate, coerced and non-finite camera inputs cannot select guessed lights."""
    with pytest.raises(ValueError):
        camera_studio_rig({**CAMERA, 'location': location})


@pytest.mark.parametrize('mutation', [
    'binding', 'count', 'energy', 'direction', 'world', 'exposure',
])
def test_actual_condition_tamper_cannot_borrow_the_profile_name(mutation):
    """Recompute recorded physical conditions instead of trusting a declared preset tag."""
    record = conditions()
    validate_camera_studio_conditions(CAMERA, record,
        implementation_sha256=lighting_implementation_sha256())
    if mutation == 'binding':
        record['lighting_implementation_sha256'] = '0' * 64
    elif mutation == 'count':
        record['lights'].pop()
    elif mutation == 'energy':
        record['lights'][0]['energy'] *= 2
    elif mutation == 'direction':
        record['lights'][0]['matrix_world'][2][2] *= -1
    elif mutation == 'world':
        record['world']['backgrounds'][0]['color'][0] = .9
    else:
        record['exposure'] = 2
    with pytest.raises(ValueError):
        validate_camera_studio_conditions(CAMERA, record,
            implementation_sha256=lighting_implementation_sha256())


def install_selected_loop(fixture, monkeypatch, *, stale=False):
    """Bind a separate V0.4 test artifact without replacing any historical fixture bytes."""
    loop = selected_loop(fixture.loop)
    if stale:
        loop = loop.model_copy(update={'lighting_implementation_sha256': '0' * 64})
    ref = publish(fixture.root, fixture.root / 'fidelity/selected_loop.json', loop)
    monkeypatch.setattr(host, 'load_optional_loop', lambda *_: (loop, ref))
    return loop, ref


def test_stale_lighting_stops_before_aq_render_reservation(tmp_path, monkeypatch):
    """A changed implementation cannot consume a slot or start Blender on resume."""
    fixture = quality_fixture(tmp_path, monkeypatch, funded=True)
    install_selected_loop(fixture, monkeypatch, stale=True)
    with pytest.raises(ValueError, match='implementation changed'):
        host.render_quality_evidence(fixture.job, fixture.session, run_id='stale')
    assert not (fixture.session_path / 'fidelity/render_reservations').exists()


def test_v04_crash_retry_keeps_the_same_policy_and_cannot_reset_budget(tmp_path, monkeypatch):
    """Reserve before failure and retain exactly one same-input retry under the selected rig."""
    fixture = quality_fixture(tmp_path, monkeypatch, funded=True)
    loop, ref = install_selected_loop(fixture, monkeypatch)
    calls = []

    def fail_render(*_args, **kwargs):
        """Inspect the actual host reservation and simulate an interrupted subprocess."""
        reservations = host._render_reservations(fixture.root, fixture.session, ref)
        assert reservations[-1][0].run_id == kwargs['run_id']
        assert kwargs['comparison_lighting_profile'] == loop.comparison_lighting_profile
        assert kwargs['lighting_implementation_sha256'] == loop.lighting_implementation_sha256
        calls.append(copy.deepcopy(kwargs))
        raise RuntimeError('interrupted renderer')

    monkeypatch.setattr(qa_service, 'run_scene_spec_visual_qa_snapshot', fail_render)
    for run in ('first', 'one_retry'):
        with pytest.raises(RuntimeError, match='interrupted renderer'):
            host.render_quality_evidence(fixture.job, fixture.session, run_id=run)
    with pytest.raises(PermissionError, match='budget exhausted'):
        host.render_quality_evidence(fixture.job, fixture.session, run_id='new_name')
    assert len(calls) == 2
    assert len(host._render_reservations(fixture.root, fixture.session, ref)) == 2


def test_closed_terminal_cannot_acquire_a_new_lighting_render(tmp_path, monkeypatch):
    """An unused nominal slot or a new profile cannot reopen a completed quality terminal."""
    fixture = quality_fixture(tmp_path, monkeypatch, funded=True)
    install_selected_loop(fixture, monkeypatch)
    fixture.holder.state = fixture.holder.state.model_copy(update={'next_action': 'none'})
    with pytest.raises(PermissionError, match='live bound quality session'):
        host.render_quality_evidence(fixture.job, fixture.session, run_id='after_terminal')
    assert not (fixture.session_path / 'fidelity/render_reservations').exists()


def test_selected_loop_rejects_missing_or_foreign_camera_lighting(tmp_path, monkeypatch):
    """A rehashed record from another camera cannot satisfy the current policy binding."""
    fixture = quality_fixture(tmp_path, monkeypatch, funded=True)
    loop = selected_loop(fixture.loop)
    with pytest.raises(ValueError, match='actual render conditions'):
        host._validate_selected_lighting(fixture.root, loop, fixture.review)
    source = json.loads((fixture.root / fixture.review.evidence.scene_spec.path).read_bytes())
    camera = source['camera']
    record = {'conditions': conditions(camera)}
    path = fixture.root / 'fidelity/actual_conditions_fixture.json'
    path.write_text(json.dumps(record), encoding='utf-8')
    from codex_blender_modeler.reference_fidelity.service import artifact_at

    exact = artifact_at(fixture.root, path)
    rating = fixture.review.model_copy(update={'evidence': fixture.review.evidence.model_copy(
        update={'comparison_conditions': exact})})
    host._validate_selected_lighting(fixture.root, loop, rating)
    foreign = {**camera, 'location': [value + 1 for value in camera['location']]}
    other = fixture.root / 'fidelity/foreign_conditions_fixture.json'
    other.write_text(json.dumps({'conditions': conditions(foreign)}), encoding='utf-8')
    changed = rating.model_copy(update={'evidence': rating.evidence.model_copy(
        update={'comparison_conditions': artifact_at(fixture.root, other)})})
    with pytest.raises(ValueError, match='differs from the selected profile'):
        host._validate_selected_lighting(fixture.root, loop, changed)
