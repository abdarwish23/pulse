# Native platform qualification — 2026-11-05

Qualified implementation: `d80f83b` on PR #14. This receipt covers the source
change; it does not install or upgrade any owner's running service or device.
The earlier v1.1.0 release receipt remains historical.

[Native qualification run](https://github.com/abdarwish23/pulse/actions/runs/41946655436)
([PR #14](https://github.com/abdarwish23/pulse/pull/14)). All nine jobs passed.
The subsequent receipt/documentation commit changes no implementation files.

## Matrix and evidence

| Environment | Python matrix | Standard suite + frontend | Real Copyparty, Python 3.12 |
| --- | --- | --- | --- |
| Ubuntu 24.04, x86_64 (`ubuntu-latest`) | 3.10.22, 3.12.16, 3.13.17 | Passed | Passed |
| macOS 26.6.2, arm64 (`macos-latest`) | 3.10.11, 3.12.10, 3.13.17 | Passed | Passed |
| Windows Server 2025, AMD64 (`windows-latest`) | 3.10.11, 3.12.10, 3.13.17 | Passed | Passed |

Every standard run discovers **90 Python tests** and runs JavaScript syntax
checks plus both frontend regression suites. Three real-storage tests are
skipped until a real backend is configured. Two Windows-specific tests are
skipped on POSIX; the POSIX permission-mode and process-group cleanup tests are skipped on Windows.
Thus each standard run skips five tests.

The real-storage runs repeat all 90 Python tests with **Copyparty 1.20.26**,
downloaded from its official release and checked against the repository's pinned
SHA-256. They skip only the two Windows-specific tests on POSIX, or the POSIX
file-mode and process-group cleanup tests on Windows. Services use isolated loopback ports, disposable
config/databases, synthetic content and stubbed Telegram delivery. Setup and
storage test paths include non-ASCII characters. No production data or model
accounts are used.

## Behaviors qualified by the tests

- Server startup and actual process restart; SQLite migration and persistence;
  login, token and private-data boundaries; reminders and durable delivery.
- MCP and CLI communication, UTF-8 stdin/output and Markdown note mirrors.
- Queued agent messages, claims/replies, leases, grants, revocation and recovery.
- Native read-only file connector, actual WebDAV transfers, SHA-256 integrity,
  no overwrite on download, permission withdrawal and retention/expiry.
- Shared workspace uploads/downloads between identities, including all byte
  values; quota concurrency, expiry and backups excluding temporary files.
- Cross-process lock contention and recovery after abrupt process exit;
  validated database backups and closed handles before snapshot publication.
- Windows rejection of device aliases, alternate streams, symlinks, junctions
  and reparse points; directory rename denied while the path is pinned.
- Workers using real local subprocess fixtures for all four adapters; Unicode
  prompts/results, timeout, cancellation, shutdown, descendant termination,
  duplicate-worker rejection and restart without repeated execution. A macOS
  zombie-only process group is distinguished from a live group on cleanup
  permission errors. Windows
  batch wrappers are rejected before execution.

## Scope and limits

Qualification is for these native CI images and the above capabilities. It is
not a claim of testing every desktop Windows release, Intel Mac, older macOS,
network filesystem, long-running background-service setup, sleeping laptop or
installed/authenticated model runtime. In particular, Windows CI is Server 2025,
not a physical Windows 11 PC. Runtime fixtures establish adapter behavior without
making paid model calls; actual runtime/account readiness is checked separately
on each enrolled device.

Windows needs Python's first-party `tzdata` package. Use private local NTFS
directories with appropriate Windows ACLs; POSIX mode checks are inapplicable
there. Native folder serving rejects unsupported paths rather than following
links. macOS share roots must be canonical paths; `/var` and `/tmp` are system
aliases, so their `/private/...` targets must be used. See
[native installation and operation](platforms.md).

The workflow remains manual-only. A future change affecting these boundaries
must pass the native matrix again before preserving or expanding qualification.
