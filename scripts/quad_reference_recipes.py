"""Finite data-only validation recipes for the approved cloth, rock and wood references."""

from __future__ import annotations

import math

from codex_blender_modeler.structural_geometry.polygon_shell_math import (
    validate_polygon_shell_data,
)
from codex_blender_modeler.structural_geometry.triangle_shell_math import _cross

REFERENCE_HASHES = {
    "cloth": "f6bb3c910565aaab9b6b16a876e96ae2b2aee09a5cfdf1c078ed42f8c33ca023",
    "rock": "796b8b8ffdc14c9420db139cde50eaffcd5ffd3472fba1464bf14c567de8000d",
    "wood": "b1312fedd5c1cfab2c7a1c522157442b1a3c543398612e8d02d4672af7df8fc7",
}
OBSERVATIONS = {
    "cloth": ["folded rectangular fabric", "four visible/inferred layers with front gaps",
              "rounded return folds", "thin continuous sheet", "broad gentle wrinkles"],
    "rock": ["broad uneven top", "angular block silhouette", "stepped fracture strata",
             "substantial solid depth", "irregular exterior corners"],
    "wood": ["elongated rectangular beam", "irregular end cross-sections",
             "worn rounded corners", "large longitudinal fissure", "solid beam volume"],
}


def _finish(vertices, faces, vertex_uvs=None):
    """Preserve safe quads, split only concave/crossed patches and record every exception."""
    result, uvs, exceptions = [], [], []
    bounds = [(min(p[k] for p in vertices), max(p[k] for p in vertices)) for k in range(3)]
    for index, face in enumerate(faces):
        points = [vertices[i] for i in face]
        normals = []
        for j in range(4):
            a, b, c = points[j], points[(j + 1) % 4], points[(j + 2) % 4]
            normals.append(_cross(tuple(b[k] - a[k] for k in range(3)),
                                  tuple(c[k] - b[k] for k in range(3))))
        average = [sum(n[k] for n in normals) for k in range(3)]
        safe = all(sum(n[k] * average[k] for k in range(3)) > 0 for n in normals)
        parts = [face] if safe else [[face[0], face[1], face[2]], [face[0], face[2], face[3]]]
        if not safe:
            exceptions.append({"patch_index": index, "reason": "non-convex fracture/fold patch"})
        axes = [k for k in range(3) if k != max(range(3), key=lambda k: abs(average[k]))]
        for part in parts:
            result.append(part)
            for vertex in part:
                uvs.append(vertex_uvs[vertex] if vertex_uvs is not None else [
                    (vertices[vertex][k] - bounds[k][0]) / (bounds[k][1] - bounds[k][0])
                    for k in axes
                ])
    geometry = {"kind": "polygon_shell", "vertices": vertices, "faces": result, "loop_uvs": uvs}
    validate_polygon_shell_data(geometry)
    return geometry, exceptions


def cloth(parameters):
    """Fold one thickened continuous quad sheet into four gently wrinkled layers."""
    width = parameters.get("width", 0.82)
    gap = parameters.get("layer_gap", 0.026)
    thickness = parameters.get("thickness", 0.0028)
    wrinkle = parameters.get("wrinkle", 0.008)
    path = []
    for layer in range(4):
        direction = 1 if layer % 2 == 0 else -1
        start, end = -0.36 * direction, 0.36 * direction
        z = 0.024 + gap * layer
        for j in range(13):
            if layer and j == 0:
                continue
            path.append((start + (end - start) * j / 12, z))
        if layer < 3:
            for j in range(1, 9):
                angle = math.pi * j / 8
                path.append((end + direction * gap / 2 * math.sin(angle),
                             z + gap / 2 * (1 - math.cos(angle))))
    count, nx = len(path), 17
    vertices, uv = [], []
    for side in (1, -1):
        for i in range(nx):
            x = width * (i / (nx - 1) - 0.5)
            for j, (y, z) in enumerate(path):
                before, after = path[max(0, j - 1)], path[min(count - 1, j + 1)]
                dy, dz = after[0] - before[0], after[1] - before[1]
                length = math.hypot(dy, dz)
                wave = wrinkle * math.sin(2 * math.pi * x / width + 0.7) * math.sin(
                    math.pi * (y + 0.4) / 0.8
                ) + wrinkle * 0.25 * math.cos(9 * x + 6 * y)
                vertices.append([x, y - side * thickness / 2 * dz / length,
                                 z + wave + side * thickness / 2 * dy / length])
                uv.append([i / (nx - 1), j / (count - 1)])
    offset, faces = nx * count, []
    for i in range(nx - 1):
        for j in range(count - 1):
            face = [i * count + j, (i + 1) * count + j,
                    (i + 1) * count + j + 1, i * count + j + 1]
            faces.extend([face, [v + offset for v in reversed(face)]])
    boundary = ([i * count for i in range(nx)]
                + [(nx - 1) * count + j for j in range(1, count)]
                + [i * count + count - 1 for i in range(nx - 2, -1, -1)]
                + list(range(count - 2, 0, -1)))
    for a, b in zip(boundary, boundary[1:] + boundary[:1], strict=True):
        faces.append([b, a, a + offset, b + offset])
    return _finish(vertices, faces, uv)


def _box_grid(nx, ny, nz, deform):
    """Create shared quad patches on six box faces before one continuous deformation."""
    counts, vertices, faces, lookup = (nx, ny, nz), [], [], {}
    for axis in range(3):
        axes = [k for k in range(3) if k != axis]
        for side in (0, counts[axis]):
            for i in range(counts[axes[0]]):
                for j in range(counts[axes[1]]):
                    face = []
                    for u, v in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)):
                        key = [0, 0, 0]
                        key[axis], key[axes[0]], key[axes[1]] = side, u, v
                        key = tuple(key)
                        if key not in lookup:
                            lookup[key] = len(vertices)
                            vertices.append(list(deform(*[2 * key[k] / counts[k] - 1
                                                          for k in range(3)])))
                        face.append(lookup[key])
                    if (axis == 1 and side != 0) or (axis != 1 and side == 0):
                        face.reverse()
                    faces.append(face)
    return _finish(vertices, faces)


def rock(parameters):
    """Retain a closed block with broad top and bounded stepped fracture strata."""
    height = parameters.get("height", 0.48)
    strata = parameters.get("strata", 0.035)

    def deform(x, y, z):
        """Warp shared surface samples without introducing disconnected slab overlays."""
        t = (z + 1) / 2
        angle = math.atan2(y, x)
        r = max(abs(x), abs(y))
        rounding = min(1., 1.6 * r / (abs(x) + abs(y))) if r else 1.
        strata_offsets = [-.25, .08, .16, .06, -.08, -.40, .12, .02, -.02,
                          -.32, .10, .02, -.08, -.32, -.12, .02, -.18]
        sample = min(15, int(t * 16))
        fraction = t * 16 - sample
        terrace = strata * ((1 - fraction) * strata_offsets[sample]
                            + fraction * strata_offsets[sample + 1])
        terrace *= .25 + .75 * max(0., math.cos(2 * angle + 3 * t))
        edge = .022 * math.sin(5 * angle + t) + .012 * math.cos(9 * angle - t)
        scale = 1 + terrace + r * edge - .13 * t
        crack = .028 * math.exp(-((x - .32 * y - .08) / .12) ** 2) * t ** 6
        crack += .018 * math.exp(-((y + .38 * x + .28) / .10) ** 2) * t ** 6
        return (.50 * x * rounding * scale + .018 * t,
                .39 * y * rounding * scale - .012 * t,
                .025 + height * t + .012 * r * math.sin(4 * angle + 3 * t)
                + t * (.025 * math.sin(4 * x + 1.5 * y)
                       + .017 * math.sin(9 * x - 5 * y)) - crack)

    return _box_grid(20, 18, 16, deform)


def wood(parameters):
    """Build lengthwise quads, worn corners and a broad geometric split in one beam."""
    length = parameters.get("length", 1.55)
    crack_depth = parameters.get("crack_depth", 0.025)
    wear = parameters.get("wear", 0.008)

    def deform(x, y, z):
        """Share every corner across cap and side patches, including the irregular ends."""
        r = max(abs(y), abs(z))
        rounding = r / (abs(y) ** 8 + abs(z) ** 8) ** 0.125 if r else 1
        yy, zz = 0.175 * y * rounding, 0.155 * z * rounding
        ripple = wear * (.55 * math.sin(7 * y + 3 * z)
                         + .30 * math.sin(11 * z - 4 * y)
                         + .15 * math.sin(4 * x + y - z))
        yy += y * ripple
        zz += z * ripple
        groove = crack_depth * math.exp(-((y + .22 - .06 * math.sin(4 * x)) / .12) ** 2)
        groove *= .2 + .8 * math.exp(-((x + .35) / .75) ** 4)
        groove += .35 * crack_depth * math.exp(-((y - .55) / .1) ** 2) * (x + 1) / 2
        zz -= max(0, z) ** 8 * groove
        end = .025 * (math.sin(7 * y + z) + .45 * math.sin(15 * z - 3 * y))
        return (length / 2 * x + abs(x) ** 12 * end, yy, 0.18 + zz)

    return _box_grid(32, 12, 12, deform)


def make_recipe(asset, parameters=None):
    """Select exactly one approved reference recipe and reject undeclared tuning inputs."""
    parameters = parameters or {}
    allowed = {"cloth": {"width", "layer_gap", "thickness", "wrinkle"},
               "rock": {"height", "strata"}, "wood": {"length", "crack_depth", "wear"}}
    if asset not in allowed or set(parameters) - allowed[asset]:
        raise ValueError("unknown reference recipe or parameter")
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 2
           for v in parameters.values()):
        raise ValueError("validation recipe parameters must be positive finite bounded numbers")
    return {"cloth": cloth, "rock": rock, "wood": wood}[asset](parameters)
