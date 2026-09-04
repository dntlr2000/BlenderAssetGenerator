---
name: aq-geometry-stage
description: Supervise bounded AQ geometry controller assignments, candidate validation, and exact policy-authorized promotion.
---

# AQ geometry stage

1. Require an exact geometry-authoring controller profile or geometry candidate validation boundary.
2. Keep candidate geometry workflow-owned until host validation and exact policy authorization succeed.
3. Preserve SceneSpec 0.2 canonical authority and treat SceneSpec V03 as a derived optional candidate only.
4. Enforce assembly, topology, provenance, budget, hard-gate, Pareto, and minimum-gain checks.
5. Stop at controller assignment, genuine escalation, budget termination, or safe review; never create a user approval.

For an explicitly bound fidelity loop, read `ModelingHypothesisV01` before authoring. Use observed regions, cross-sections, volumes, connections and uncertainty, not the candidate bbox, to define expectations. Use `spatial_v1` and stable semantic/face groups. A silhouette extrusion is valid only when it represents the observed object, not as a default image projection.

For reentry, use the exact host plan, source snapshot and current round. Structural defects require a genuinely changed volume/section/assembly strategy; adding rails, marks, noise or material contrast cannot satisfy them. Local parametric reentry permits only bounded translation/scale of declared targets, not topology or representation changes. Preserve non-target parts, camera and base material values, stage all output, and let the host consume the exact purpose-specific single-use policy. Material closure must be repeated for geometry changes.
