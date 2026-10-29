# Task worker delivery — 2026-10-30 JST

Implementation: `7296426d61af4df2653c65df7d276a4d1f5f7406`,
[PR #6](https://github.com/abdarwish23/pulse/pull/6), stacked on the existing
agent-network branch. The owner explicitly requested installation on both devices
and automatic agent-to-agent tasks with actual feedback. PC owner authorization
was also confirmed in that device's interactive session.

## Deployed

Both devices have enabled, active `pulse-worker.service` user services with
lingering enabled and zero restarts at verification. Runtime profiles:

| Device | Enabled execution identities | Installation |
| --- | --- | --- |
| VPS | `vps/codex`, `vps/claude`, `vps/pi` | `~/pulse-releases/worker-7296426` |
| PC | `pc/codex`, `pc/claude`, `pc/pi` | clean `~/pulse-worker-client` at implementation commit |

Configuration: `~/.config/pulse/network-worker.json`; private state:
`~/.local/state/pulse-worker`. Each profile has its own enrolled credential and
explicit requester list. Directional message grants connect the six identities.
Existing file connectors and the running controller were preserved, with no
database migration or controller restart. OpenCode execution is disabled: it is
not installed on the VPS and has no authenticated integration on the PC.

VPS runtimes reuse existing local authentication/model defaults. Codex uses
`danger-full-access` with noninteractive approvals, Claude uses the owner's
authorized `bypassPermissions` mode, and pi retains its normal tool access.
No provider/account/billing configuration was changed.

PC setup and local file evidence were performed by the PC agent and reported
through Pulse. PC profiles use dedicated `~/pulse-worker-workspaces/{codex,claude,pi}`
with local usage instructions. They disable native MCP loading in worker invocations
and use the Pulse CLI with inherited per-profile credentials, avoiding the existing
interactive MCP identity overrides. Interactive configuration is preserved. The
PC's private evidence receipt is `~/.config/pulse/network/pc-worker-receipt.json`.

## Verified

* Full disposable-server regression suite: **63 passed, 2 skipped**. The skipped
  tests require a separate real Copyparty fixture; storage code was not changed.
* All **11 new worker tests** passed on VPS and PC: runtime result handling,
  denied senders, missing executable, error/timeout, shutdown, cancellation,
  duplicate worker exclusion, lost completion response and crash recovery without
  replay. Test adapters are subprocess fixtures, not claims of live OpenCode access.
* Actual VPS automatic invocations returned their expected markers with exit 0:
  Codex `3d4a999a559bd981b3187c2a71a2153f` (7.3s), Claude
  `50cbc82dd1db2368296daafa2db6c4ed` (6.6s), pi
  `c0bc68d71b57f0e0b7a3babfb26066a2` (3.3s).
* Actual PC write/readback tasks completed with exit 0: Codex
  `43b1bc6bc80d69614967b165f7de15c0`, Claude
  `910b8332ba3b3b329e160e9d9634f00a`, pi
  `4e9f717c2e970cc5d1b8f9909293cf41`. The PC agent independently checked exact
  file bytes and removed the synthetic files. VPS confirmed the controller results.

Real delegation with the initiating agent waiting for actual feedback:

| Initiator → recipient | Child request | Result |
| --- | --- | --- |
| PC Codex → VPS pi | `3e8afad7aa72e3f77bcc9fa5edf321d2` | completed; sum 42 |
| VPS Claude → PC pi | `3ed53941527f23faf4a08b2ce19937a3` | completed; product 143 |
| PC Codex → VPS Claude | `8475f51ea94a5f1eb38bb6647b772ad4` | completed; exact marker |
| PC Claude → VPS pi | `63ec5aee7326067877d21e5d7012d0a2` | completed; exact marker |
| PC pi → VPS Codex | `9ed50d468dcc42e774f87cb018cea88f` | completed; exact marker |

All corresponding parent tasks returned the actual child IDs/results. The two
independently initiated cross-device parent requests were
`a2ac22dffe510389454a5661b75735a3` (29.1s) and
`9ff4f49579a0e761a66b111e05a49682` (88.6s, including the agent's 60-second poll
delay). Model latency and sender polling interval affect feedback time.

## Operations and remaining status

Send `request_agent_message`, then poll `get_network_request` until terminal;
queued is not completion. Workers own claim/renew/complete. Fresh sessions do not
inject into or wake an existing chat. A sleeping/offline PC retains queued work
until reconnect or expiry. Stop/rollback with `systemctl --user disable --now
pulse-worker.service`; no server rollback is needed. Owner-local instructions now
describe automatic delegation on VPS; previous files were privately backed up.

Deployment and requested core behavior are verified. At initial delivery, PR #6
remained open for source review/merge alongside #5; Pulse card #165 retained that
review status. No hosted CI, public release or repository visibility change was
performed.

## Source review — 2026-10-30 JST

PC source review reproduced recovery failures in the original implementation:
saved feedback blocked an explicitly reconciled retry, including a retry already
claimed by another worker. An expired request pruned by controller retention also
left its worker stuck trying to deliver missing work. Recovery now retires stale
attempt feedback without replacing a new result, and confirms the network identity
is available before clearing a missing request. Network outages or disabling the
network retain undelivered feedback.

Four additional real-HTTP regression tests cover those cases and preservation
while the network is disabled. `python3 scripts/check.py python3` on Python 3.12.3
passed **67 tests**, with **2 optional real-Copyparty tests skipped**, all four
frontend syntax checks and the frontend regression checks. There are now 15 worker
tests. `git diff --check` passed; no hosted workflow was dispatched. The merge
target remains the existing `codex/agent-network` base; parent PRs #4/#5 are separate.
