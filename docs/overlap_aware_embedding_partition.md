# Conservative overlap-aware embedding partition

The complete-solid embedding BVH uses a deterministic terminal policy: up to
three triangles form a leaf; a four-triangle group remains a leaf if all four
closed AABBs share a point. The additional four-record intersection examination
is charged explicitly to the existing aggregate work counter. In every other
respect the same original boxes, median widest-centroid split, full child
coverage, closed-overlap traversal and unchanged exact triangle predicates are
used. No triangle, pair, coordinate, root or aggregate-work cap is increased.

This is a partitioning heuristic, not a new contact classifier. Every completed
enumeration must equal the complete unordered closed-AABB pair set, including
boundary touches. Pair order can change but is deterministic. An exhausted
counter remains an unavailable/failing proof, never an incomplete pass.

A fixed leaf size 3 initially reduced Crystal candidate work but materially
increased the coincident-box stress case. The overlap-aware policy avoids that
large dense-clique penalty. It is not universally faster: small separated/skinny
bounds can require extra charged work, and some assets regress slightly. The
retained benchmark distinguishes completed exact pair equality from exhausted
runs and reports per-case costs; it does not extrapolate one asset's gain into a
universal performance claim.

The five-asset benchmark inspects actual Blender 5.0.1 imported triangle snapshots
for Plastic/Rust/Wood/Laser and exact authored Crystal coordinates. Some other
assets exceed the closed-root companion's 4,096-triangle component or 25,000-triangle
asset domain; their broadphase experiment is not a root-solid eligibility claim.
Plastic and Rust exhaust the unchanged 1M broadphase cap in both tested policies.
Separate source/F32 complete-solid and fixed-root tests are required on the final
combined Crystal geometry. Historical source, failures and receipts remain intact.
