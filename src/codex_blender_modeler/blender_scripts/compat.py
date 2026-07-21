from __future__ import annotations

from collections.abc import Iterable
from typing import Any

EEVEE_ENGINE_CANDIDATES = ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT")
CYCLES_COMPUTE_BACKENDS = ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")
PREFERRED_COLOR_LOOKS = (
    "AgX - Medium High Contrast",
    "Medium High Contrast",
)


def select_eevee_engine(scene: Any, candidates: Iterable[str] = EEVEE_ENGINE_CANDIDATES) -> str:
    """Select the first EEVEE enum accepted by the running Blender build.

    Blender 5 uses ``BLENDER_EEVEE`` while Blender 4.x releases may expose
    ``BLENDER_EEVEE_NEXT``. Feature probing is intentionally preferred over
    branching on a version string.
    """

    failures: list[str] = []
    for engine in candidates:
        try:
            scene.render.engine = engine
        except (TypeError, ValueError, RuntimeError) as exc:
            failures.append(f"{engine}: {exc}")
            continue
        scene["cbm_render_engine"] = engine
        return engine

    try:
        import bpy  # type: ignore

        version = bpy.app.version_string
    except Exception:  # pragma: no cover - only relevant outside Blender
        version = "unknown"
    details = "; ".join(failures) or "no candidates supplied"
    raise RuntimeError(
        f"No compatible EEVEE render engine was accepted by Blender {version}. {details}"
    )


def select_render_engine(scene: Any, requested_engine: str = "EEVEE") -> str:
    """Feature-probe the requested renderer while preserving the legacy EEVEE fallback."""

    requested = requested_engine.strip().upper()
    if requested == "EEVEE":
        return select_eevee_engine(scene)
    if requested != "CYCLES":
        raise ValueError(f"Unsupported render engine request: {requested_engine!r}")

    try:
        scene.render.engine = "CYCLES"
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RuntimeError(f"Cycles is unavailable in this Blender build: {exc}") from exc
    scene["cbm_render_engine"] = "CYCLES"
    return "CYCLES"


def configure_cycles_device(
    scene: Any,
    requested_device: str = "CPU",
    preferences: Any | None = None,
    backend_candidates: Iterable[str] = CYCLES_COMPUTE_BACKENDS,
) -> tuple[str, list[str]]:
    """Select a real Cycles compute device and never silently downgrade a GPU request."""

    device_request = requested_device.strip().upper()
    if device_request == "AUTO":
        device_request = "CPU"
    if device_request not in {"CPU", "GPU"}:
        raise ValueError(f"Unsupported Cycles device request: {requested_device!r}")

    if device_request == "CPU":
        scene.cycles.device = "CPU"
        scene["cbm_render_device"] = "CPU"
        scene["cbm_cycles_compute_backend"] = "CPU"
        scene["cbm_cycles_devices"] = "CPU"
        return "CPU", ["CPU"]

    try:
        scene.cycles.device = "GPU"
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RuntimeError(f"Cycles GPU rendering is unavailable: {exc}") from exc

    if preferences is None:
        import bpy  # type: ignore

        addon = bpy.context.preferences.addons.get("cycles")
        if addon is None:
            raise RuntimeError("Cycles GPU rendering is unavailable: cycles add-on not found")
        preferences = addon.preferences

    failures: list[str] = []
    for backend in backend_candidates:
        try:
            preferences.compute_device_type = backend
            preferences.get_devices()
        except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
            failures.append(f"{backend}: {exc}")
            continue

        devices = list(getattr(preferences, "devices", []))
        gpu_devices = [
            device for device in devices if str(getattr(device, "type", "")) == backend
        ]
        if not gpu_devices:
            failures.append(f"{backend}: no GPU devices")
            continue

        try:
            for device in devices:
                device.use = device in gpu_devices
        except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
            failures.append(f"{backend}: failed to enable devices: {exc}")
            continue

        names = [
            (
                f"{getattr(device, 'name', 'GPU')} "
                f"({getattr(device, 'type', backend)})"
            )
            for device in gpu_devices
        ]
        scene["cbm_render_device"] = "GPU"
        scene["cbm_cycles_compute_backend"] = backend
        scene["cbm_cycles_devices"] = ", ".join(names)
        return backend, names

    details = "; ".join(failures) or "no compute backends supplied"
    raise RuntimeError(
        "Cycles GPU rendering was requested but no GPU device was usable. " + details
    )


def select_color_management_look(
    scene: Any,
    preferred: Iterable[str] = PREFERRED_COLOR_LOOKS,
) -> str:
    """Apply a preferred AgX look when available, otherwise preserve the current look."""

    current = str(getattr(scene.view_settings, "look", ""))
    attempted: set[str] = set()
    for look in preferred:
        if not look or look in attempted:
            continue
        attempted.add(look)
        try:
            scene.view_settings.look = look
        except (TypeError, ValueError, RuntimeError):
            continue
        return str(scene.view_settings.look)

    print(
        "CBM_WARNING: preferred AgX look is unavailable; "
        f"keeping current look={current!r}"
    )
    return current


def configure_render_compat(
    scene: Any,
    requested_engine: str = "EEVEE",
    requested_device: str = "AUTO",
) -> tuple[str, str]:
    """Configure the requested renderer/device and record reproducibility metadata."""

    import bpy  # type: ignore

    engine = select_render_engine(scene, requested_engine)
    if engine == "CYCLES":
        backend, devices = configure_cycles_device(scene, requested_device)
        print(f"CBM_CYCLES_COMPUTE_BACKEND={backend}")
        print(f"CBM_CYCLES_DEVICES={', '.join(devices)}")
    else:
        if requested_device.strip().upper() not in {"AUTO", ""}:
            raise ValueError("EEVEE does not accept an explicit Cycles render device")
        scene["cbm_render_device"] = "DEFAULT"
    look = select_color_management_look(scene)
    scene["cbm_blender_version"] = bpy.app.version_string
    scene["cbm_render_engine"] = engine
    scene["cbm_color_management_look"] = look
    print(f"CBM_BLENDER_VERSION={bpy.app.version_string}")
    print(f"CBM_RENDER_ENGINE={engine}")
    print(f"CBM_RENDER_DEVICE={scene['cbm_render_device']}")
    print(f"CBM_COLOR_MANAGEMENT_LOOK={look}")
    return engine, look


def set_material_transparency(material: Any) -> str:
    """Set hashed/dithered transparency across Blender 4.x/5.x APIs."""

    if hasattr(material, "surface_render_method"):
        for value in ("DITHERED", "BLENDED"):
            try:
                material.surface_render_method = value
                return f"surface_render_method={value}"
            except (TypeError, ValueError, RuntimeError):
                continue
    if hasattr(material, "blend_method"):
        for value in ("HASHED", "BLEND"):
            try:
                material.blend_method = value
                return f"blend_method={value}"
            except (TypeError, ValueError, RuntimeError):
                continue
    return "unsupported"


def export_obj(filepath: str) -> str:
    """Export OBJ using the modern operator with a legacy fallback."""

    import bpy  # type: ignore

    wm = getattr(bpy.ops, "wm", None)
    modern = getattr(wm, "obj_export", None)
    if modern is not None:
        modern(filepath=filepath, export_selected_objects=False)
        return "bpy.ops.wm.obj_export"

    export_scene = getattr(bpy.ops, "export_scene", None)
    legacy = getattr(export_scene, "obj", None)
    if legacy is not None:
        legacy(filepath=filepath, use_selection=False)
        return "bpy.ops.export_scene.obj"
    raise RuntimeError("No OBJ export operator is available in this Blender build")
