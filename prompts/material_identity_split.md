# Material identity split prompt

Use Material Identity Split 0.1.0 only for an exact, preplanned object-to-material identity split.
Rehash the current SceneSpec, ModelingPlan, Blend, strict MaterialPlan absence, reference authority,
content scope, and UV fingerprint. Permit only semantic-clone material identities, the declared target
object assignments, and the paired ModelingPlan detail target changes.

Before requesting approval, run the isolated Blender 5.0.1 build, inspect, validate, and all geometry,
topology, transform, dimension, UV, reference, clone, and assignment invariants. Publish an
ApprovalRequest only when every receipt passes, then stop at
`framework_ready_for_explicit_scope_approval`.

Never synthesize the specialized user decision, approval payload, ApplyIntent, ControllerResult, or
canonical output. Apply only a caller-authored exact intent after an independently observed user
decision. Treat SceneSpec, ModelingPlan, and Blend as one host-locked transaction; preserve append-only
states and exact archives; recover to commit, rollback, or `recovery_required`. After commit, publish
new inventory, build provenance, strict MaterialPlan absence, canonical snapshot, and geometry
continuation. Start any material appearance work as a separate new material closure and approval.

