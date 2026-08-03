# V0.8 short-request orchestration

Use the repository V0.8 workflow contracts to route the user's short request. Do not skip an agent-authored contract or a user approval.

1. Create or select the correct isolated job without replacing primary evidence.
2. Plan the workflow with the narrowest intent and scope that satisfy the request.
3. Read `state.json` and execute only the exact current action.
4. For an agent step, author only the declared canonical artifact, validate it, and record the exact input/output-bound completion marker.
5. For a generic approval, generate and show the matching PDF alongside canonical JSON evidence and the exact fingerprint; never self-approve.
6. For InteriorScope, V0.6 visual revision, or V0.7 optimization, use the existing specialized approval flow.
7. Resume deterministic host steps only. Use failed-step retry only after the cause is corrected and the user authorizes retry.
8. Stop at an unsupported destination boundary and deliver the engine-neutral package without claiming engine parity.
9. Report the workflow ID, current state, next action, completed checkpoints, warnings, and remaining approvals.

# Three-dimensional assembly consistency

For every newly authored standard or background ModelingPlan, use
`assembly_consistency_policy=spatial_v1`. Define one asset-local `assembly_frame`, classify object
assembly roles, and record stable parent-local relationships for attached structural or functional
parts. Center-plane, coaxial, containment, and contact intent must survive SceneSpec authoring and
later detailed revisions. `side_specific` requires an orthogonal/multiview/blueprint source or an
explicit user-authored requirement; visibility in one side/oblique image is not hidden-depth side
evidence. Bind observed/measured evidence to exact source IDs. Otherwise use inferred
center-plane/coaxial intent and never turn a 2D screen-space offset into an unobserved depth/lateral
coordinate.
# Surface-attached detail routing

During ModelingPlan authoring, explicitly separate geometry-worthy parts from small surface detail.
Use `surface_details` for shallow non-structural windows, seams, labels, rivets, painted panels, and
repeated marks. Never emit one SceneSpec object per texture-routed mark. V0.5 must bind those IDs to
portable UVMap PBR channels before material build, while V0.6 reports their coverage separately
from geometry similarity.
