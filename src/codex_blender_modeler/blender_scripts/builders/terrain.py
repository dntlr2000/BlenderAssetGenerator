from __future__ import annotations

from pathlib import Path

import bpy


def _resolve(path: str, base_dir: Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _sample_heightmap(path: Path, rows: int, cols: int) -> list[list[float]]:
    image = bpy.data.images.load(str(path), check_existing=True)
    width, height = image.size
    channels = image.channels
    pixels = list(image.pixels[:])
    result: list[list[float]] = []
    for row in range(rows):
        y = round((height - 1) * row / max(rows - 1, 1))
        values: list[float] = []
        for col in range(cols):
            x = round((width - 1) * col / max(cols - 1, 1))
            start = (y * width + x) * channels
            rgb = pixels[start : start + min(channels, 3)]
            value = sum(rgb) / max(len(rgb), 1)
            values.append(float(value))
        result.append(values)
    return result


def _perimeter_indices(rows: int, cols: int) -> list[int]:
    top = [col for col in range(cols)]
    right = [row * cols + (cols - 1) for row in range(1, rows)]
    bottom = [(rows - 1) * cols + col for col in range(cols - 2, -1, -1)]
    left = [row * cols for row in range(rows - 2, 0, -1)]
    return top + right + bottom + left


def build(spec: dict, base_dir: Path) -> bpy.types.Object:
    size_x, size_y, size_z = [float(value) for value in spec["size"]]
    if spec["mode"] == "height_grid":
        heights = [[float(value) for value in row] for row in spec["heights"]]
        rows = len(heights)
        cols = len(heights[0])
    else:
        cols, rows = [int(value) for value in spec.get("resolution", [128, 128])]
        heightmap = _resolve(spec["heightmap_path"], base_dir)
        heights = _sample_heightmap(heightmap, rows, cols)

    vertices: list[tuple[float, float, float]] = []
    for row in range(rows):
        y = -size_y / 2.0 + size_y * row / max(rows - 1, 1)
        for col in range(cols):
            x = -size_x / 2.0 + size_x * col / max(cols - 1, 1)
            z = heights[row][col] * size_z
            vertices.append((x, y, z))

    faces: list[list[int]] = []
    for row in range(rows - 1):
        for col in range(cols - 1):
            a = row * cols + col
            b = a + 1
            c = a + cols + 1
            d = a + cols
            faces.append([a, b, c, d])

    skirt_depth = float(spec.get("skirt_depth", 0.0))
    if skirt_depth > 0:
        perimeter = _perimeter_indices(rows, cols)
        lower_indices: list[int] = []
        for source_index in perimeter:
            x, y, z = vertices[source_index]
            lower_indices.append(len(vertices))
            vertices.append((x, y, z - skirt_depth))
        for index, upper in enumerate(perimeter):
            next_index = (index + 1) % len(perimeter)
            faces.append(
                [upper, perimeter[next_index], lower_indices[next_index], lower_indices[index]]
            )
        faces.append(list(reversed(lower_indices)))

    mesh = bpy.data.meshes.new("CBM_Terrain")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(clean_customdata=False)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new("CBM_Terrain", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
