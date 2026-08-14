# Material Promotion Instructions

- This package exposes additive facades only. The existing AQ material phase service remains the sole canonical MaterialPlan/blend writer and rollback authority.
- Never synthesize or infer `MaterialAppearanceApproval`. Publication requires an exact caller-authored approval and an explicitly observed user decision.
- Approval consumption is immutable and single-use. Controller execution occurs only after exact consumption publication and closure projection equality.
- Promotion revalidates the current closure, preflight, approval, controller result, and canonical CAS under the host lock.
