# Triangulated shell authoring

`triangulated_shell` is an explicit data-only structural recipe for derived SceneSpec
V03 and MeshPayload 0.2. It represents one connected, closed, outward-oriented
surface using bounded vertex positions, ordered triangles and optional per-corner
UVs. It is useful when a continuous folded surface cannot preserve its junctions
through overlapping solid operands. The recipe contains no file path, script,
callback, driver, node graph, material assignment or execution request.

The strict host model permits at most 65,536 vertices and 131,072 triangles. It
rejects non-finite or unbounded coordinates, coincident/unused vertices, invalid
indices, repeated or degenerate triangles, inconsistent edge winding, open edges,
disconnected surfaces, non-manifold vertex links, inward signed volume and UV
corner-count mismatches. These combinatorial checks do not prove the absence of
self-intersection, reference fidelity, manufacturability or hidden measured shape.
Actual Blender, QA and delivery checks remain independently required.

The host and Blender builder share the same standard-library data validator;
Blender does not import host-only Pydantic dependencies. The runtime also rejects
legacy payload dispatch before clearing or constructing its temporary scene.

The fixed builder preserves vertex, triangle and optional UV-corner order. Normal
and subdivision behavior still comes from the existing explicit GeometryIntent.
Materialization records the complete recipe hash, emits MeshPayload 0.2 and then
uses the existing compile, source-binding, survival, budget and promotion paths.
It never takes an already compiled payload as an authorized controller result.

AQ v2 accepts this recipe through the same read-only candidate preflight and final
host validation as other structural recipes. One object consumes the same priced
materialization/build allowance as one existing structural object; it creates no
revision, retry, promotion or approval authority. A changed vertex or UV makes the
previous candidate preflight stale. Existing exact source manifests also become
stale after the implementation source changes.

The canonical SceneSpec remains 0.2.0; the shell is compiled into the existing
canonical `custom_mesh` projection. Direct `custom_mesh` controller authoring stays
rejected. The default legacy MeshPayload 0.1 materializer rejects this new recipe
before creating files or invoking Blender. Legacy AQ structural allowlists are
unchanged, and no evidence is migrated. No CLI/MCP tool or external execution
capability is added. An explicit `mesh_payload_version="0.2.0"` is required where
the existing in-process materialization service is used.

After a campaign source change, a new clean commit, source manifest, baseline,
readiness and exact campaign scope are required. A successful earlier baseline
remains historical evidence and cannot be counted as a new-baseline success.
