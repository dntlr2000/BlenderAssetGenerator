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

For a new reference-fidelity campaign, run `preflight_aq_geometry_authoring` on the exact staged ModelingPlan, SceneSpec V03 and StructureAuthoring before creating the immutable controller request. Every scene object must carry exactly one primary/supporting QA role matching its ModelingPlan. Persist the returned report as a new staging artifact and supply it as an immutable input with kind `geometry_authoring_preflight`. The host replays its source, current state, candidate and finite cost and pins the two candidate output hashes. The report grants no approval, execution, canonical write or budget authority. Fix an invalid unsubmitted candidate only in staging; never replace submitted outputs, reopen a terminal or relabel a completed controller as a transient retry. Historical requests without this explicit companion retain their original validation path.

For reentry, use the exact host plan, source snapshot and current round. Structural defects require a genuinely changed volume/section/assembly strategy; adding rails, marks, noise or material contrast cannot satisfy them. Local parametric reentry permits only bounded translation/scale of declared targets, not topology or representation changes. Preserve non-target parts, camera and base material values, stage all output, and let the host consume the exact purpose-specific single-use policy. Material closure must be repeated for geometry changes.
