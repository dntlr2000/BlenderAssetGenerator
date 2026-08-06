from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.blender_scripts.compat import (
    configure_cycles_device,
    select_color_management_look,
    select_eevee_engine,
    select_render_engine,
)


class FakeScene(dict):
    def __init__(self, accepted_engines: set[str], accepted_looks: set[str]) -> None:
        super().__init__()
        self.render = SimpleNamespace()
        self.view_settings = SimpleNamespace()
        self._accepted_engines = accepted_engines
        self._accepted_looks = accepted_looks
        self._engine = ""
        self._look = "Default"
        type(self.render).engine = property(
            lambda _self: self._engine,
            lambda _self, value: self._set_engine(value),
        )
        type(self.view_settings).look = property(
            lambda _self: self._look,
            lambda _self, value: self._set_look(value),
        )
        self.render._set_engine = self._set_engine
        self.view_settings._set_look = self._set_look

    def _set_engine(self, value: str) -> None:
        if value not in self._accepted_engines:
            raise TypeError(f"unsupported engine {value}")
        self._engine = value

    def _set_look(self, value: str) -> None:
        if value not in self._accepted_looks:
            raise TypeError(f"unsupported look {value}")
        self._look = value


def _scene(engines: set[str], looks: set[str]) -> FakeScene:
    """Create a small feature-probed scene double for renderer compatibility tests."""

    scene = FakeScene.__new__(FakeScene)
    dict.__init__(scene)
    scene._accepted_engines = engines
    scene._accepted_looks = looks
    scene._engine = ""
    scene._look = "Default"

    class Render:
        @property
        def engine(inner_self):
            return scene._engine

        @engine.setter
        def engine(inner_self, value):
            scene._set_engine(value)

    class ViewSettings:
        @property
        def look(inner_self):
            return scene._look

        @look.setter
        def look(inner_self, value):
            scene._set_look(value)

    scene.render = Render()
    scene.view_settings = ViewSettings()
    scene.cycles = SimpleNamespace(device="CPU")
    return scene


class FakeCyclesPreferences:
    """Expose backend-specific devices like Blender's Cycles preferences object."""

    def __init__(self, devices_by_backend: dict[str, list[SimpleNamespace]]) -> None:
        self.devices_by_backend = devices_by_backend
        self.devices: list[SimpleNamespace] = []
        self._compute_device_type = ""

    @property
    def compute_device_type(self) -> str:
        """Return the currently probed backend."""

        return self._compute_device_type

    @compute_device_type.setter
    def compute_device_type(self, value: str) -> None:
        """Accept only backends represented by the test fixture."""

        if value not in self.devices_by_backend:
            raise TypeError(f"unsupported backend {value}")
        self._compute_device_type = value

    def get_devices(self) -> None:
        """Populate devices for the currently selected backend."""

        self.devices = self.devices_by_backend[self._compute_device_type]


def test_blender_5_engine_is_preferred() -> None:
    scene = _scene({"BLENDER_EEVEE"}, {"AgX - Medium High Contrast"})
    assert select_eevee_engine(scene) == "BLENDER_EEVEE"


def test_blender_4_engine_fallback() -> None:
    scene = _scene({"BLENDER_EEVEE_NEXT"}, {"AgX - Medium High Contrast"})
    assert select_eevee_engine(scene) == "BLENDER_EEVEE_NEXT"


def test_cycles_engine_can_be_selected() -> None:
    scene = _scene({"CYCLES"}, {"AgX - Medium High Contrast"})
    assert select_render_engine(scene, "cycles") == "CYCLES"


def test_cycles_gpu_backend_is_feature_probed() -> None:
    scene = _scene({"CYCLES"}, {"AgX - Medium High Contrast"})
    cpu = SimpleNamespace(name="CPU", type="CPU", use=True)
    gpu = SimpleNamespace(name="Test GPU", type="CUDA", use=False)
    other_gpu = SimpleNamespace(name="Other GPU", type="HIP", use=True)
    preferences = FakeCyclesPreferences({"OPTIX": [cpu], "CUDA": [cpu, gpu, other_gpu]})

    backend, names = configure_cycles_device(
        scene,
        "gpu",
        preferences=preferences,
        backend_candidates=("OPTIX", "CUDA"),
    )

    assert backend == "CUDA"
    assert names == ["Test GPU (CUDA)"]
    assert scene.cycles.device == "GPU"
    assert cpu.use is False
    assert gpu.use is True
    assert other_gpu.use is False
    assert scene["cbm_render_device"] == "GPU"


def test_cycles_gpu_request_never_silently_falls_back_to_cpu() -> None:
    scene = _scene({"CYCLES"}, {"AgX - Medium High Contrast"})
    cpu = SimpleNamespace(name="CPU", type="CPU", use=True)
    preferences = FakeCyclesPreferences({"CUDA": [cpu]})

    with pytest.raises(RuntimeError, match="no GPU device was usable"):
        configure_cycles_device(
            scene,
            "gpu",
            preferences=preferences,
            backend_candidates=("CUDA",),
        )


def test_engine_failure_is_explicit() -> None:
    scene = _scene(set(), set())
    with pytest.raises(RuntimeError, match="No compatible EEVEE"):
        select_eevee_engine(scene)


def test_color_look_falls_back_without_failing() -> None:
    scene = _scene({"BLENDER_EEVEE"}, set())
    assert select_color_management_look(scene) == "Default"


def test_common_render_configuration_resets_saved_crop_state() -> None:
    """Keep canonical renders independent of a user's saved Blender render border."""

    common_source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "common.py"
    ).read_text(encoding="utf-8")

    assert "scene.render.pixel_aspect_x = 1.0" in common_source
    assert "scene.render.pixel_aspect_y = 1.0" in common_source
    assert "scene.render.use_border = False" in common_source
    assert "scene.render.use_crop_to_border = False" in common_source
    assert "scene.render.border_min_x = 0.0" in common_source
    assert "scene.render.border_min_y = 0.0" in common_source
    assert "scene.render.border_max_x = 1.0" in common_source
    assert "scene.render.border_max_y = 1.0" in common_source
