# Shared workspace verification — 2026-11-01

- Python 3.12: full 80-test suite passed using isolated real Copyparty 1.20.26.
- Standard local release checks: 80 tests (77 passed, 3 real-storage tests skipped), JavaScript syntax checks and frontend assertions passed.
- Real HTTP coverage: shared access for message-only agents, owner settings/CSRF, disabled workspace, credential revocation, revocation during upload, concurrent quota enforcement, checksum/idempotency/path validation, non-overwriting downloads, expiry, retryable physical deletion and backup exclusion.
- Schema upgrade preserves existing identities, credentials, sessions, grants and requests. New installations leave workspace access disabled.
- Browser preview checked at mobile and desktop sizes, including dark-theme logo contrast. Fixed desktop search overlapping the new workspace button.
- Existing Cloud enrollments are supported by identity, not assumed to exist on a user's installation.
- Physical uploads still depend on backend disk headroom; capacity is a quota, not preallocated disk space. Deployment and per-device smoke tests are recorded separately in the Pulse project timeline.
