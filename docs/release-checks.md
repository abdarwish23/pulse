# Local release checks

GitHub Actions is manual-only. A push or PR does not start hosted CI. Validate
locally with Python 3.10, 3.12 and 3.13, plus Node.js for frontend checks:

```bash
python3 scripts/check.py python3.10 python3.12 python3.13
```

Interpreter paths work too. No packages or network services are needed by the
tests: they use temporary databases, loopback HTTP and stubbed Telegram delivery.
The tests cover authentication boundaries, private derived data, URL validation,
proxy trust, initialization, backup integrity/restore, schema upgrade, durable
delivery recovery, concurrency and cancellation. Frontend tests exercise legacy
unsafe links and rendering with a minimal DOM stub; additionally smoke-test the
real browser UI with `python3 scripts/demo.py` before release. Record exact
versions, commit and results. Do not infer Windows/macOS support from Linux tests.

## Upgrade from 1.0

1. Back up the database and config privately and record the current commit.
2. Rehearse the upgrade on a disposable copy, with Telegram and GitHub polling
   disabled. Never point a second test server at the live database.
3. Migrations 5 and 6 add privacy provenance and durable delivery state. Existing
   data stays in place. Older reminder notifications and `Todo done:` activity
   lack reliable provenance, so they remain visible to the owner only. No text is
   deleted. Existing private todos make their reminders private too.
4. New privacy changes also hide linked history. Making an item public later
   does not automatically republish private history. A private todo must be made
   public explicitly before it can become a shared board card.
5. Failed legacy deliveries are not replayed on upgrade. New pending deliveries
   survive restarts and retry up to five attempts. Errors from older delivery
   failures become generic messages so old transport URLs cannot expose tokens.
6. Existing Pulse tokens and correctly configured Cloudflare service credentials
   remain valid. Service JWTs alone no longer grant owner access. Configure
   trusted proxy headers only as described in the deployment guide.
7. Initializing another instance preserves the existing client token file. Use a
   new `PULSE_TOKEN_FILE` path for that instance; no existing token is rotated.

The database and backup files are restricted to the account running Pulse on
POSIX. Existing configured database parent directories outside the default
`data/` directory are not chmodded; secure them yourself if they are shared.
If the filesystem cannot enforce POSIX modes, use its native access controls.

## Production and rollback

After the candidate passes local checks, prepare the target commit, service path,
backup, expected migrations and any proxy setting changes for deployment review.
Verify owner login and PC/VPS agent access using synthetic test data after restart.
No public release is implied by a deployment. Keep a verified backup until the
upgrade is accepted. Rolling back code also requires restoring its pre-upgrade
database, config and matching version; do not run old code against the migrated
database. Preserve the current database and WAL files separately before restore.

Before publication, inspect all refs/assets intended to be public for secrets
and personal data, run a redacted history/worktree secret scan, check the license
and screenshots, prepare release notes and create the approved version tag.
Do not rewrite history based on stale instructions about a `clean-main` branch.
Version `1.1.0-dev` denotes this unreleased candidate; use the same final version
in the MCP metadata, changelog and tag when releasing.
