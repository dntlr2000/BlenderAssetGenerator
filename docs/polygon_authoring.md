# Quad-dominant polygon authoring

`polygon_shell` is an explicit data-only structural recipe for closed, outward-oriented
triangle/quad meshes. It preserves authored faces and per-corner UVs through
StructuralGeometryCandidate, explicit MeshPayload 0.2 materialization and canonical
SceneSpec 0.2 `custom_mesh` builds. It adds no arbitrary execution or approval authority.
Legacy `triangulated_shell`, MeshPayload 0.1 and historical receipts retain their meaning.

Use connected grids or corresponding section strips for continuous surfaces. Keep
triangles where a fracture or cap needs them, and record the reason. Do not inflate
face counts to reach a quad percentage, resample away important contour anchors, or
replace deliberate facets with blanket subdivision. A quad ratio is a topology measure,
not a reference-fidelity or human-quality score.

## Inspection and export

Materialization of the new recipe records authored/evaluated topology statistics and a
`mesh_triangle_view` 0.1 projection. The view binds the exact source MeshPayload hash and
actual Blender loop triangles. Every triangle maps to one original polygon and three
original corners; both legal quad diagonals are supported. Missing, duplicate, reversed,
cross-polygon or stale mappings fail closed. UVs, materials, smoothing and face groups
are projected for inspection without replacing the source payload.

`surface_attachment_intent` and `solid_root_attachment_intent` explicitly select version
0.2 and `source_triangle_views` to inspect polygon sources. Version 0.1 remains
triangle-only. The same source, transform, material, complete-solid and actual-native
correspondence requirements remain in force. Limits count expanded triangles, including
the 25,000 aggregate limit and existing per-semantic limits. Polygon payloads and their
views are sealed together in new stage/package evidence. Guarded solid-root rebinding
may change exact source/view bindings within version 0.2; it cannot change proof domain,
reference, camera, roots, authority or historical version.

The authoring `.blend` retains quads. The native glTF exporter emits triangles; the
portable serialization path preserves Blender's native quad diagonals for marked
polygon-shell objects, including nonplanar faces, rather than choosing another surface.
Raw export and independent import do not constitute Production package acceptance.
Legacy triangle snapshots remain version 0.1 and are not a polygon admission shortcut.

## Validation and limits

`tests/test_polygon_shell.py` covers strict geometry, corner mapping, UV seams, face
groups, source binding, budgets and legacy rejection. `CBM_RUN_POLYGON_SMOKE=1` enables
the Blender 5.0.1 build/reopen/export/import test. The existing solid-root native test
covers both versions through actual host extraction and package evidence sealing.

The bounded `scripts/validate_quad_references.py` driver uses only the approved
cloth/rock/wood reference hashes. It permits three candidates per asset, one canonical
seven-pass QA set and four diagnostic images per candidate, and two export/import
attempts per asset. Revisions are preserved candidate snapshots; only first authoring
uses the canonical write lock. It never approves later promotion or human acceptance.
Its fixed native validation script performs independent import, source hash checks,
neutral views, a disposable edit/restore probe and cloth subdivision diagnostics.
`--scene-spec scene_spec_corrected.json` selects an explicitly retained technical
correction within that same candidate. The original rejected file stays intact; this
does not create a new candidate slot or permit another QA set. A correction must be
recorded with both file hashes before execution.

Native inventory adds authored/evaluated statistics to marked polygon-shell objects.
Legacy inventory and contract interpretation remain unchanged. Area and signed-volume
diagnostics use object-local mesh coordinates; ratios are not a visual acceptance gate.
The validation results and known limits are recorded in
[the Korean validation report](QUAD_AUTHORING_VALIDATION_KO.md).

Use an external `CBM_WORKSPACE_ROOT` under `E:\CodexValidation`, and task-specific
TEMP/TMP under `E:\CodexTemp`. Keep final editable blends, recipes, exact references,
GLBs and essential results. Remove only owned disposable validation copies and caches.
