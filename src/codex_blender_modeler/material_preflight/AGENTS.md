# Material Preflight Instructions

- This package is a compatibility facade over the generic Material Closure pre-controller checks. Do not duplicate canonical promotion or rollback code here.
- A passed preflight requires current closure/rebinding evidence, bounded resource accounting, isolated Blender 5.0.1 evidence, and an actual neutral preview.
- Preflight and shadow compilation never create approval, ControllerResult, canonical writes, AQ transitions, or destination writes.
- Historical preflight replay and current approval eligibility are separate operations. Current approval validation must rehash every bound artifact.
