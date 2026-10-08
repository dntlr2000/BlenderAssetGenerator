# Bounded native self-intersection coverage correction

Date: 2026-09-30. Project version and canonical SceneSpec remain unchanged. This correction
applies to newly generated authoring topology observations, not saved reports or approvals.

## Reproduced false-pass classes

The original native inspector counted only non-adjacent Blender BVH overlap pairs. It
excluded every pair sharing any vertex index. Two actual Rust-sheet face pairs
`(9496, 18138)` and `(6497, 18138)` intersected beyond their single shared vertex, while
2-triangle extracts returned `available`, `passed=true`, and a zero intersection count.
Independent edge/triangle witnesses extended 0.0171665962 m and 0.0620510203 m beyond the
common vertex. Source payload SHA-256:
`8b26b0772ae3f9d92f2f1b3ba967313611bd51f5326bf984b0d952bdbaa564b4`.

Blender 5.0.1 also omitted coplanar positive-area overlap from its BVH candidates. Simply
checking additional shared-vertex BVH hits would therefore still miss coplanar containment,
including faces without any shared mesh indices. Native regression fixtures reproduce both
classes. The exact repaired Rust payload supplies paired negative fixtures with SHA-256
`948ed310552d87f5f0d72c322ac931a104f7536def43e2502693e7c264d774f1`.

## New bounded check

- Retain the existing limit of 5,000 evaluated triangles per object and zero allowed
  intersection pairs
- Enumerate endpoint-inclusive, overlapping triangle AABBs with a sweep; this includes
  coplanar, adjacent, nonadjacent and duplicate candidates without relying on BVH omissions
- Cache finite evaluated binary-float coordinates as exact rational numbers, with one
  exact plane normal per triangle; add no distance or area epsilon
- Resolve noncoplanar intersection intervals on the exact common line; resolve coplanar
  intersections with exact projected convex clipping
- Permit exact contact confined to both triangle boundaries, including shared-index adjacency,
  split-vertex UV/normal seams, and boundary-only T-junctions. Reject positive-area coplanar
  overlap or intersection extending into either triangle interior. Other manifold/closure
  checks retain responsibility for unwelded topology; a shared-index label cannot excuse crossing
- Treat invalid, nonfinite or degenerate triangles as unavailable for this check
- Bound exact candidate work to 100,000 pairs per object. Exhaustion without an established
  intersection is unavailable, never passed. If an intersection is already established, the
  result remains failed and its count is a lower bound, with exhaustion explicit in the message

The raw inspection snapshot declares the additional pair-work limit. Existing topology
schemas, profile severity maps, hard-gate thresholds and old receipt meanings are unchanged.
An unavailable required self-intersection check remains unscorable under the existing gate.
Fresh reports can expose penetration/overlap previously missed by BVH; geometric boundary-only
contact remains eligible even when mesh indices are split.

## Executed verification and limits

Focused tests cover original/repaired Rust pairs, winding reversal, legitimate common vertex
and edge contact, noncoplanar crossings, coplanar containment and disjoint triangles,
duplicate faces and coordinates, very thin overlaps at multiple scales, invalid evidence,
exact work-budget boundaries, and unchanged hard-failure/unscorable projection. Native
Blender 5.0.1 tests execute the actual inspector wrapper and the existing read-only,
hash-bound authoring-companion fixture.

A native clean planar grid at the unchanged 5,000-triangle ceiling had 2,601 vertices and
41,308 AABB candidate tests. It passed with zero intersections in 12.64 seconds. Exact testing
is slower than the previous BVH-only check; other shapes and hosts may take different time.
The final focused command/results and exact source hashes are recorded in the accompanying
validation receipt rather than inferred from this benchmark.

This is evaluated per-object topology evidence. It does not establish reference likeness,
hidden-surface accuracy, inter-object assembly acceptance, production-package acceptance or
human visual approval. The 37,268-triangle full Rust sheet remains beyond the native triangle
budget; successful small-pair regression fixtures do not turn that full check into a pass.
Separate diagnostic coverage must be described by its actual source, enumeration and budget.
