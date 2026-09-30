# Recorded Wood v1 regression fixtures

These five 512 x 512 PNGs reproduce the exact byte hashes originally pinned in
`test_procedural_wood_v1_recorded_candidate_bytes_remain_frozen`, introduced by
commit `ad4e5e816746916130e834d64a38a6b94afe6d7c`. The fixtures were reproduced
using that test's request on Windows with Python 3.14.6, Pillow 11.3.0 and
zlib-ng 2.2.4, then verified against every pre-existing SHA-256 value.

They are generated regression fixtures, not user inputs, production assets or
quality/approval evidence. Do not re-encode them to accommodate a library update.

The historical-file test pins their encoded bytes and decoded pixels. The
generation test separately pins dimensions, color mode and decoded pixel hashes,
including an alternative lossless compression level. Every generated manifest
must still record the exact SHA-256 and size of its actual PNG file. Pixel
identity does not replace file hashes in production provenance or approvals.
