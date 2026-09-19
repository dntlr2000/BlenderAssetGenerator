"""Actual Blender lighting evidence on synthetic panels, never campaign or art acceptance."""

from __future__ import annotations

import json
import os

import numpy as np
import pytest
from PIL import Image

from codex_blender_modeler.blender_artifact_runner import render_scene_qa_passes
from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.comparison_lighting import (
    CAMERA_STUDIO_PROFILE,
    lighting_implementation_sha256,
    validate_camera_studio_conditions,
)
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.workspace import sha256_file

pytestmark = pytest.mark.skipif(
    os.getenv('CBM_RUN_COMPARISON_LIGHTING_BLENDER') != '1',
    reason='Set CBM_RUN_COMPARISON_LIGHTING_BLENDER=1 for actual Blender 5.0.1 evidence.',
)


def panel_scene(job: str) -> SceneSpec:
    """Build three plain synthetic faces with different incidence angles to the fixed sun."""
    return SceneSpec.model_validate({
        'schema_version': '0.2.0', 'job_id': job, 'mode': 'concept',
        'nominal_scene_size': [3, 2, 3], 'sources': [],
        'materials': [{'id': 'mat.neutral', 'name': 'Neutral rough surface',
            'base_color': [.32, .32, .32, 1], 'roughness': .8, 'metallic': 0}],
        'objects': [{'id': identity, 'name': identity,
            'geometry': {'kind': 'primitive', 'primitive': 'cube', 'dimensions': [1.8, .03, .65]},
            'transform': {'location': [0, 0, height], 'rotation_deg': [angle, 0, 0]},
            'material_id': 'mat.neutral', 'shade_smooth': False}
            for identity, height, angle in (
                ('panel.downward', .8, 25), ('panel.vertical', 0, 0), ('panel.upward', -.8, -25))],
        'camera': {'projection': 'ORTHO', 'location': [0, -6, 1.8], 'target': [0, 0, 0],
            'focal_length_mm': 50, 'ortho_scale': 3.4, 'resolution': [256, 256]},
    })


def srgb_linear(value):
    """Decode display pixels for comparative fixture measurements, not physical radiometry."""
    value = value.astype(float) / 255
    return np.where(value <= .04045, value / 12.92, ((value + .055) / 1.055) ** 2.4)


def test_actual_camera_studio_preserves_source_and_six_geometric_passes(tmp_path, monkeypatch):
    """Illuminate a sun-opposed face while keeping source, camera and geometric evidence exact."""
    workspace = tmp_path / 'workspaces'
    job = 'comparison_light_fixture'
    root = workspace / job
    (root / 'analysis').mkdir(parents=True)
    (root / 'blender').mkdir()
    spec = panel_scene(job)
    scene_path = root / 'analysis/scene_spec.json'
    scene_path.write_text(spec.model_dump_json(indent=2), encoding='utf-8')
    blend = root / 'blender/scene.blend'
    monkeypatch.setenv('CBM_WORKSPACE_ROOT', str(workspace))
    build = run_blender('build_scene.py', ['--spec', str(scene_path), '--job-root', str(root),
        '--output', str(blend)], factory_startup=True, disable_autoexec=True)
    (root / 'build_execution.txt').write_text(str(build), encoding='utf-8')
    before = {str(path.relative_to(root)): sha256_file(path) for path in (scene_path, blend)}
    manifests = {}
    for run in ('legacy', 'camera_studio'):
        output = root / 'qa' / run
        args = {} if run == 'legacy' else {
            'comparison_lighting_profile': CAMERA_STUDIO_PROFILE,
            'lighting_implementation_sha256': lighting_implementation_sha256(),
        }
        manifests[run] = render_scene_qa_passes(job, scene_spec_path=scene_path, blend_path=blend,
            output_dir=output / 'passes', manifest_path=output / 'manifest.json', run_id=run,
            comparison_conditions_path=output / 'conditions.json', **args)
        assert manifests[run].blender_version == '5.0.1'
    conditions = json.loads((root / 'qa/camera_studio/conditions.json').read_bytes())['conditions']
    validate_camera_studio_conditions(spec.camera.model_dump(mode='json'), conditions,
        implementation_sha256=lighting_implementation_sha256())
    assert before == {path: sha256_file(root / path) for path in before}
    pixel_checks = {}
    for kind in ('silhouette', 'object_id', 'material_id', 'normal', 'depth', 'wireframe'):
        first = np.asarray(Image.open(root / f'qa/legacy/passes/{kind}.png'))
        second = np.asarray(Image.open(root / f'qa/camera_studio/passes/{kind}.png'))
        pixel_checks[kind] = bool(np.array_equal(first, second))
    assert all(pixel_checks.values())
    encoded = manifests['legacy'].object_id_colors['panel.downward'].lstrip('#')
    color = np.array([int(encoded[index:index + 2], 16) for index in (0, 2, 4)])
    ids = np.asarray(Image.open(root / 'qa/legacy/passes/object_id.png'))
    normals = 2 * srgb_linear(np.asarray(Image.open(root / 'qa/legacy/passes/normal.png'))) - 1
    mask = np.all(ids == color, axis=2) & (normals[:, :, 1] < -.8) & (normals[:, :, 2] < -.3)
    assert mask.sum() > 100
    luminances = {}
    for run in manifests:
        rgb = srgb_linear(np.asarray(Image.open(root / f'qa/{run}/passes/beauty.png')))
        luminances[run] = float(np.median((rgb @ np.array([.2126, .7152, .0722]))[mask]))
    assert luminances['camera_studio'] > 1.5 * luminances['legacy']
    assert luminances['camera_studio'] > .03
    receipt = {'schema_version': '0.1.0', 'kind': 'synthetic_lighting_verification',
        'blender_version': '5.0.1', 'source_unchanged': before,
        'geometric_pass_pixel_equality': pixel_checks,
        'sun_opposed_face_display_luminance': luminances,
        'comparison_conditions_sha256': sha256_file(root / 'qa/camera_studio/conditions.json'),
        'campaign_visual_improvement_or_acceptance': False}
    (root / 'lighting_verification.json').write_text(
        json.dumps(receipt, indent=2), encoding='utf-8')
