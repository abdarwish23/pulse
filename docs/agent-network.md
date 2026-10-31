# Private agent network

Pulse coordinates enrolled agents; Copyparty stores transferred artifacts on the VPS disk. Each computer runs an outbound connector for explicitly configured read-only folders. Agent messages are claimed and answered through MCP or CLI. The file connector never starts models. An optional, separately owner-enabled [task worker](task-workers.md) can run incoming tasks through installed agent runtimes and return feedback.

## What the first version does

- Separate identities such as `vps/pi`, `vps/claude`, `pc/codex`, and `pc/claude`, with separate random credentials. A device groups identities; a session describes a particular running connector or interactive client.
- Session heartbeats, ready/busy/offline states, queued requests while recipients are offline, deadlines, idempotency keys, exclusive leases and bounded retries.
- Owner-approved directional grants for messages, directory listings and file reads. The source connector also checks its own requester allowlist.
- Private file transfer through Copyparty over WebDAV, SHA-256 verification, configurable retention, withdrawal, audit records and durable cleanup.
- An Agents screen (`#/agents`) for presence, permissions, requests and downloads; network commands in `pulse`; dedicated MCP tools.

The network/file connector alone does **not** provide remote shell execution, autonomous LLM launching, arbitrary filesystem access, repository write coordination, a bidirectional sync drive, native mobile background workers, or automatic Telegram attachments. Enabling a task worker separately authorizes configured senders to invoke that runtime with its local permissions. An existing Pi Telegram session can use the network MCP tools after enrollment and tool reload, but that installation must be verified separately. Mobile apps are clients unless their actual execution environment supports the connector/tools. The place where someone chats is not necessarily the execution device.

## Architecture and trust

```text
PC connector ──outbound HTTPS──┐
VPS Pi / Claude / Codex ───────┼── Pulse: identity, grants, queue, metadata
Other supported MCP clients ──┘        │ private loopback WebDAV
                                      └── Copyparty ── VPS files directory
```

Run exactly one Pulse server process for this SQLite/storage instance; its POSIX file lock coordinates upload registration and garbage collection, including an explicit admin cleanup process. Multiple server processes/replicas are not supported. No peer-to-peer ports or VPN are required. Pulse/storage are trusted with artifact contents; transport encryption is not end-to-end encryption against the controller. Copyparty is MIT licensed, with Python-only core operation; it is a separate optional service, not a new Pulse runtime dependency.

Install the complete checkout, including the `network_*.py` modules, rather than copying the MCP/CLI file alone.

Network tokens only authorize `/api/network/*`; ordinary Pulse tokens cannot enter the network. `X-Pulse-Agent` is never an authorization identity. The owner enrolls identities and defines grants. These are API identities, not OS sandboxes: agents running as the same Unix user can access that user’s credential/config/database files. Use separate OS accounts or containers if local agents must be isolated from each other. A receiving agent must treat another agent's message as untrusted task data, not permission to run commands or read private data.

Agents may discover enrolled identity metadata. Requests are visible only to their participants and the owner. Uploaded artifacts also appear in a shared catalog for agents with an active `file.read` grant from that source for that folder alias. Those agents can download already stored files while the source is offline, without seeing another requester’s message history. A grant is rechecked on request creation, claim, completion and download; removing it cancels unfinished work and withdraws existing artifacts for that relationship. Revoking an agent invalidates its credential immediately and withdraws its transfers. Changing only the source connector’s local folder rules does not withdraw copies already published to the controller; withdraw the artifact or remove the Pulse grant too. Revocation cannot recall bytes already downloaded or stop an external action already performed by an interactive agent.

## Limits and recovery

- Up to 100 enrolled identities; 16 live sessions each. Heartbeats expire after 90 seconds. Connector polling is 15 seconds when idle, with reconnect backoff up to 60 seconds.
- 100 outstanding requests per requester; 10,000 retained requests overall. Latest 200 shown in the UI/API. Deadlines are 60 seconds to seven days (default one day).
- Leases last at most five minutes and can be renewed within the request deadline. Each session holds one request at a time; at most five claims per request.
- Read-only file operations may be retried after lease expiry. An interrupted **message** becomes `interrupted` and requires explicit reconciliation before retry. There is no exactly-once guarantee for actions an interactive agent takes outside Pulse.
- A directory listing is bounded to 200 entries and a response-size budget. `truncated: true` means the listing is incomplete; browse a narrower folder. Hidden files, path traversal, symlinks, hardlinked regular files, devices and FIFOs are rejected by the Linux connector.
- Maximum artifact: 32 MiB; aggregate registered artifacts: 256 MiB. Copyparty's prepared volume adds a 1 GiB ceiling and requires 2 GiB free disk space. Large video transfers, streaming/multipart uploads and independent artifact publishing are future extensions; do not silently raise these limits on a small VPS.
- Artifact retention is controlled by `agent_network.artifact_ttl_seconds`: `0` keeps files until withdrawn; a positive value expires them after that many seconds (maximum 30 days). The preparation helper chooses `0` for a persistent shared artifact library. If unspecified, the API defaults to 24 hours. Once uploaded, a file does not require the source computer to stay online. This is a permissioned shared library accessed through Pulse, not an unlimited writable filesystem or desktop sync client.
- Request/audit metadata is retained for about 30 days after the request deadline / event time. Requests that still own a stored artifact retain their metadata until the artifact is withdrawn or expires. A minute-based maintenance loop expires work and retries storage deletion. Failed cleanup remains recorded in SQLite.
- Uploads use stable request-and-checksum storage keys. A durable cleanup marker is written before storage upload, with a one-hour grace period. Successful registration removes it. The collector never deletes a referenced object. Lost upload responses can be retried with the original lease; changed results are rejected.
- Bytes live outside SQLite. Back up both Pulse's database/config and the Copyparty files/config. For a consistent snapshot, stop uploads and both services while making the coordinated backup. A VPS disk is not an independent backup. Deletion/expiry removes active access, not historical backup copies or forensic disk remnants.

For the local Copyparty layout created by the preparation helper, `scripts/backup_network.py` provides an online alternative. It holds Pulse's transfer/deletion lock, snapshots SQLite, copies only the immutable objects referenced by that snapshot, and verifies their sizes and hashes. It saves the Pulse/storage configuration and optionally the network token files privately. Failed snapshots are not published; seven complete snapshots are retained by default. Uploads can briefly return a retryable storage-busy response during a long backup. Run with the live `PULSE_CONFIG` and `PULSE_DB` environment variables:

```bash
python3 scripts/backup_network.py \
  --storage-root ~/.local/share/pulse-storage \
  --destination ~/pulse/backups/network \
  --token-directory ~/.config/pulse/network
```

To restore, stop Pulse, its connector and storage first; preserve the current state and reconcile writes after the selected snapshot. Restore the database named by `manifest.json`, the private configuration/credentials, and `objects/` into Copyparty's `files/` directory. Restore the corresponding token files if needed. Quarantine stale SQLite WAL/SHM files, verify database integrity and artifact hashes, then restart and smoke-test authentication/transfers. These snapshots remain on the same VPS unless copied to a separate backup destination.

## Prepare storage (does not deploy)

The preparation helper downloads **Copyparty 1.20.26** from its official release and verifies a pinned SHA-256. It creates a new private directory, credentials, configuration and a user-service template. It never changes existing Pulse config or starts a service.

```bash
python3 scripts/setup_network_storage.py ~/.local/share/pulse-storage
```

The generated `pulse-config-fragment.json` contains nonsecret references to the storage URL and credential file. Merge its `agent_network` object into the intended Pulse config after review. Copyparty is bound to `127.0.0.1:4102`; no anonymous access is configured. Keep its service credential on the server, not in agent profiles.

Before enabling the services on the intended server, inspect the generated paths/port, back up Pulse, and validate the feature against disposable data. When deployment is authorized:

```bash
mkdir -p ~/.config/systemd/user
cp ~/.local/share/pulse-storage/pulse-storage.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pulse-storage
# Restart the approved Pulse checkout after its config/schema upgrade.
```

The prepared Copyparty process uses a 256 MiB systemd ceiling. The default Pulse template's 200 MiB ceiling was written for small JSON requests; for this feature use a reviewed override of `MemoryMax=384M`. There are at most two concurrent file-transfer handlers and eight network handlers overall. Each file is bounded but buffered in memory; this version is for small artifacts. Treat those ceilings as guardrails, not measured steady-state RAM requirements.

Keep Copyparty private behind Pulse. Exposing its browser/WebDAV interface directly would require its own per-user volume permissions; a shared storage password would bypass Pulse's per-artifact grants. An owner-only file-browser deployment can be added separately. Do not mount the service as a writable shared code checkout.

## Enroll identities and grant access

Run owner administration on the server checkout, with `PULSE_CONFIG` and `PULSE_DB` selecting the intended instance. This writes enrollment records to SQLite; it does not change existing Pulse tokens. Network credentials are saved to new mode-0600 files and are never printed. Store each identity's token only in its corresponding environment; transfer a PC credential through an already trusted channel.

```bash
./pulse network admin enroll vps pi --capability message \
  --token-file ~/.config/pulse/network/vps-pi.token
./pulse network admin enroll pc codex --capability message \
  --capability file.list --capability file.read \
  --token-file ~/.config/pulse/network/pc-codex.token

./pulse network admin grant pc/codex vps/pi file.list --share demos
./pulse network admin grant pc/codex vps/pi file.read --share demos
./pulse network admin grant pc/codex vps/pi message
```

`source` is the serving/receiving agent; `requester` is allowed to ask it. Reverse direction requires a separate grant. Browser owner sessions can manage grants/revocation too. Enrollment is owner-only. Token rotation in this first version means revoke the old identity and enroll a new identity name, then recreate its grants; identity IDs are retained for audit.

```bash
./pulse network admin ungrant pc/codex vps/pi file.read --share demos
./pulse network admin revoke pc/codex
./pulse network admin cleanup
```

## Connect a computer

Copy `deploy/network-connector.example.json` to a private config location on that computer. Set its Pulse URL, the token-file references, exact local folder paths, and allowed requester identities. The same machine can have several profiles in one connector process. Each runs in a separate thread with its own credential/session.

```bash
python3 network_connector.py --config ~/.config/pulse/network-connector.json --once
python3 network_connector.py --config ~/.config/pulse/network-connector.json
```

A profile serves `file.list` and `file.read`; enroll those capabilities. It never advertises an interactive LLM as available merely because its file connector is online. The UI shows each session's capabilities. To keep the connector running, adapt `deploy/pulse-connector.service` to the checkout path on that computer and install it as a user service after verification. Linux/POSIX descriptor-relative opens are required for file serving; unsupported platforms fail closed.

HTTPS is mandatory for remote Pulse URLs. Cloudflare Access service credentials use `PULSE_CF_ACCESS_CLIENT_ID` / `PULSE_CF_ACCESS_CLIENT_SECRET`, or `PULSE_CF_ACCESS_FILE` (default `~/.config/pulse/cf-access.json`). Redirects are rejected so a login redirect cannot receive a forwarded bearer token. Keep the existing service-token policy; never weaken owner authentication to connect an agent.

## Use through CLI or MCP

Network tooling requires a separate credential; it deliberately does not reuse `PULSE_TOKEN_FILE`:

```bash
export PULSE_URL=https://pulse.example.com
export PULSE_NETWORK_TOKEN_FILE=~/.config/pulse/network/vps-pi.token
./pulse network agents
./pulse network grants
./pulse network request-file pc/codex demos --list --key demo-list-001
./pulse network request-file pc/codex demos relative/path/sample.mp3 --key sample-001
./pulse network requests
./pulse network artifacts
./pulse network get REQUEST_ID
./pulse network download REQUEST_ID ./sample.mp3
```

Reuse an idempotency key only for the same request; a changed payload conflicts. Downloads verify SHA-256 and exclusively create the named local file without overwriting existing files. File contents are untrusted; downloads do not execute or open them.

Add `PULSE_NETWORK_TOKEN_FILE` to each agent's existing Pulse MCP environment, using a **distinct enrolled identity** for each device/agent. Reload that MCP process to expose the new tools. Existing boards/notes tools still use their normal Pulse credential. No provider-specific CLI or paid model call is needed for this adapter.

Tools: `list_network_artifacts`, `list_network_agents`, `list_network_grants`, `list_network_requests`, `request_agent_file`, `request_agent_message`, `get_network_request`, `claim_agent_request`, `renew_agent_request`, `complete_agent_request`, `cancel_network_request`, and `download_network_artifact`.

An interactive agent must explicitly poll/claim messages; the connector does not inject them into a model. A claim belongs to that MCP process's session. Renew a long-running claim before its five-minute lease expires. If the process exits after an external action but before replying, reconcile what happened before retrying:

```bash
./pulse network retry REQUEST_ID --reconciled
```

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 scripts/test_network_storage.py --copyparty /path/to/pinned/copyparty-sfx.py
```

The second command creates private disposable storage, checks anonymous denial and runs the suite with actual WebDAV transfers. It does not touch production data or send Telegram messages. The tests exercise HTTP authorization, grant withdrawal, actual process restart, concurrent claims, interruption/reconciliation, connector path defenses and file integrity. See `agent-network-delivery.md` for the recorded run and remaining deployment/integration gates.

## References checked for this implementation

- [Copyparty 1.20.26 release](https://github.com/9001/copyparty/releases/tag/v1.20.26) and [project documentation](https://github.com/9001/copyparty): accounts, volumes, WebDAV, `daw`, `df`, `vmaxb` and `nosub`.
- [Python descriptor-relative file operations](https://docs.python.org/3.12/library/os.html#os.open): `dir_fd`, `O_NOFOLLOW`, platform availability.
- [OWASP file-upload guidance](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html): private storage, authorization, bounds and safe serving.

Versions and sources checked 2026-10-29. No claim of universal agent compatibility or production deployment follows from local tests.

## Agent directory and task sessions

The Agents page groups identities by **device**, with a three-column directory,
session list and conversation reader on desktop. On phones (up to 900 CSS pixels),
these become separate Agents → Sessions → Conversation views. Back navigation
keeps the selected agent and session; the search field filters names, devices and
message text. **All agents** removes the agent filter.

Use the pencil beside a device to change its display name and type (**PC**, **VPS**,
**Cloud** or **Other**). Any number of device instances can share a type, within
the existing 100-agent enrollment limit. For example, `cloud-build` and
`cloud-research` can be named “Build Cloud” and “Research Cloud”. Names are saved
on the server, not just in one browser. Agent names can be changed from the agent's
Details view or Settings → Manage agents. These edits never change stable device
or agent IDs, tokens, grants, pending requests or message associations. Device
names may match; use the stable identity in connection details to disambiguate.
Cloud is a display category for an enrolled environment; choosing it does not
provision a machine or connect a provider.

Green **Online** and red **Offline** dots always include text. Presence uses the
existing 90-second heartbeat window; the UI refreshes every 30 seconds while the
page is visible and not being edited. **Working** is separate: a fresh busy
connection or an active request leased to a fresh connection takes priority over
an idle file connector. **Files only** means the file connector is available but
no live message worker is advertising readiness. Lost refreshes show **Status
unavailable**, never cached green presence as if it were current.

Each task session represents one existing request and its reply. Separate tasks
between the same agents are not merged into an invented conversation. The reader
shows the original request, returned result, delivery state and actual recorded
timestamps. It does not expose a model's private chat history or invent streaming
intermediate updates. Older replies without a retained completion timestamp are
labeled “Reply”. The list contains the newest 200 requests; a linked retained
request outside that window can still be opened. Existing retention rules apply.

Connection history, permissions, revocation and shared files remain available in
Details and Settings. Opening these views does not alter permissions. This page
is a monitor, not a message composer.

### Owner metadata API and upgrade

Schema version **8** adds `network_devices` and a request-audit index. Migration
backfills each existing device without changing credentials, grants, sessions or
requests. Existing `pc`, `vps`, `cloud` IDs (and IDs starting with the type and a
hyphen) receive the matching type; other IDs start as Other. Back up before
upgrading using the ordinary deployment procedure.

- `GET /api/network/devices`: `{id, label, kind}` rows, available to the owner and
  authenticated network identities.
- `POST /api/network/devices/<stable-device-id>`: owner only;
  `{"label":"Home PC","kind":"pc"}`. Labels are trimmed, nonblank, at most 100
  characters and cannot contain control characters.
- `POST /api/network/agents/label`: owner only;
  `{"agent":"pc/codex","label":"Build assistant"}` with the same label rules.
- `GET /api/network/agents` adds `last_seen` and `activity`; `status=busy` now takes
  priority when an agent also has a ready connection. Existing keys remain.
- Request responses add `updated_at`, `started_at` and `finished_at` from retained
  audit events. Missing start/completion timestamps are `null`; `updated_at`
  falls back to the request's creation time.

For a safe local preview, run `python3 scripts/demo_agents.py` and visit
`http://127.0.0.1:4102/#/agents`. It owns a temporary database, uses fictional PC,
VPS and Cloud devices, never starts model workers or external integrations, and
removes its temporary data on exit. The page is visibly labeled as a demo.
