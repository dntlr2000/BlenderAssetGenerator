# Exact generated-atlas fallback

The existing `smart_project` material-conversion method now proves the actual
stored destination triangles with the same exact positive-area overlap and
zero-area predicates used by validated authored UV conversion. A generated
overlap or zero-area triangle may select the already-supported Lightmap Pack
fallback. Other proof errors propagate unchanged. The fallback result, final
Float2 tile mapping, and post-triangulation layout must each pass the exact
proof; no adjacency exemption or tolerance relaxation is introduced.

The conversion evidence retains the initial exact failure, selected unwrap
method and final proof. Existing plans, failed attempts, source UV layers and
geometry are not repaired in place. Use a fresh immutable conversion ID and
its declared UV method. This is a derived material conversion, not source
revision or optimization authority.

Before the destination UV becomes active, cloned material nodes retain their
source sampling basis: implicit image/coordinate UVs and tangent Normal Map
nodes are bound to the original render UV, while explicitly named UV bindings
remain unchanged. A material's declared UV name does not override Blender's
actual implicit render-UV selection in legacy mixed-UV inputs.

Exact non-overlap proves usable parameterization, not sufficient texture
density or appearance. Lightmap Pack can create many small islands. Inspect
actual exported/imported pixels with matching camera/light controls and
report atlas resolution and texture memory separately. Never infer a visual
improvement solely from a passing layout or larger atlas.

Nested groups with implicit UV consumers are refused before cloning or baking.
Read-only traversal is limited to512 nodes including the root and64 nested
levels; cycles fail closed. Explicit nested bindings and metadata-only groups
remain unchanged. Native mesh counts are checked before Python array allocation
against the existing exact-proof250,000-triangle/750,000-loop limits.
