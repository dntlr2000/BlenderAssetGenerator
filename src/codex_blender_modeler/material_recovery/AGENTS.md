# Material Recovery Instructions

- Preserve failed, blocked, cancelled, rollback, retry, approval, and source evidence exactly. Recovery publishes companions; it never repairs historical JSON in place.
- A terminal AQ session is not resumed. Material-only recovery uses a distinct repair session with exact reusable-geometry and source bindings.
- Existing approved and never-approved retries are superseded separately; absence is explicit evidence and approval is never inferred.
- Automatic repair stops at `approval_pending`. It cannot consume approval, execute a controller, write canonical state, transition IQ, or write a destination project.
- Archive exact working and index bytes before removing job-specific executable source.
