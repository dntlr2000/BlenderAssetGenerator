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
# Surface-attached detail routing

During ModelingPlan authoring, explicitly separate geometry-worthy parts from small surface detail.
Use `surface_details` for shallow non-structural windows, seams, labels, rivets, painted panels, and
repeated marks. Never emit one SceneSpec object per texture-routed mark. V0.5 must bind those IDs to
portable UVMap PBR channels before material build, while V0.6 reports their coverage separately
from geometry similarity.
