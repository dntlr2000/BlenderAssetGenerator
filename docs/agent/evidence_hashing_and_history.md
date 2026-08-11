# Evidence hashing and immutable history

Machine JSON and exact hashes are authoritative. Latest pointers and PDFs are conveniences. Bind every execution to repository/job-relative contained paths, exact source fingerprints, current embedded build provenance, run IDs, immutable attempts, and terminal receipts.

Expected downstream supersession of a shared derived path preserves the earlier execution-time snapshot; it does not retroactively stale a valid receipt. Unexpected source/candidate/snapshot mutation is an artifact conflict and fails closed. Historical workflows, QA runs, AQ sessions, packages, handoffs, blocked states, and receipts are never rewritten or repaired in place.

Use atomic publication, immutable run-owned paths, deterministic JSON, exact dependency enumeration, and link/path-escape rejection. Keep absolute paths, secrets, and raw external locations out of persisted reports. PDFs carry sidecar hashes but never replace source JSON.

Primary rules: CBM-INV-022, CBM-INV-025..034, CBM-INV-047..052, CBM-INV-059..066, CBM-INV-071, CBM-INV-080, CBM-INV-082..088, CBM-INV-095, CBM-INV-104, CBM-INV-107..112, CBM-INV-114..121, CBM-INV-125, CBM-INV-128..150, CBM-INV-152..166, CBM-INV-171..192.

