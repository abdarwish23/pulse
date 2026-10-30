# Agent network implementation receipt

> Historical implementation receipt. PRs #4, #5 and #6 were subsequently merged into main. For the public release status, use [the 1.1.0 receipt](releases/1.1.0.md). Paths and service observations below describe one deployment at the stated date, not installation defaults or current connectivity.

Date: 2026-10-29. Implementation commit: `a3e7f8990892824240da8f38f5811db7ce6100e6`.
Base: `805c412` (`codex/pulse-release-hardening`, draft PR #4). Feature branch: `codex/agent-network`.

**Deployment update:** the owner approved deployment on 2026-10-29. The application is now live at implementation commit `a3e7f899`; the artifact backup helper is installed from `b09d8fa`. The initial preparation record below is retained as history; see the executed rollout at the end for current status.

## Delivered and verified locally

- Scoped device/agent identities and sessions; explicit source/requester grants; offline queue, deadline, idempotency, leases, reconciliation and revocation.
- Outbound Linux connector with multiple agent profiles, explicit folder aliases, requester checks and descriptor-relative read-only access.
- Copyparty 1.20.26 WebDAV storage, verified hashes, shared artifact catalog, configurable retention, durable cleanup, quotas and free-space guard. Preparation chooses retention until withdrawal.
- Pulse Agents screen, CLI and MCP tools. Existing agent runtimes are not started or modified automatically.
- **54 Python tests passed** on Python 3.12.3 using an isolated real Copyparty process (`scripts/test_network_storage.py`). Includes actual Pulse subprocess restart, concurrent claims, message interruption, MCP claim/reply, CLI discovery, cross-agent denial, source path defenses, artifact corruption, additional authorized readers, indefinite retention and grant revocation during stalled storage I/O.
- Existing frontend URL/escaping/delivery tests passed. All four JavaScript files passed syntax checks. Playwright with an isolated verified Node 22.23.4 runtime and existing Chromium passed desktop (1280×900) and mobile (390×844) Agents flows, persisted grant creation/removal, no page errors and no horizontal overflow.
- Pinned storage preparation helper ran successfully in a new disposable directory; credential mode 0600 and permanent-retention fragment verified. No service installed by the helper.
- Changed-file credential-pattern check and `git diff --check` passed. This is not a penetration-test claim.
- No hosted CI/Actions, paid model requests, real cross-agent messages, Telegram notifications from test fixtures, or production mutations.

Only Python 3.12 was available for this feature run; 3.10/3.13 were not rerun. Real PC connectivity, live Cloudflare upload/download behavior, Pi/Claude tool reload, and mobile-client support remain unverified.

## Deployment target observed (read-only)

- Live checkout: `~/pulse`, main `1e667f0`.
- Service: `~/.config/systemd/user/pulse.service`.
- Current ExecStart: `/usr/bin/python3 ~/pulse/server.py`; working directory `~/pulse`.
- Config and DB: `~/pulse/config.json`, `~/pulse/data/pulse.db`.
- Listener: `127.0.0.1:4100`; public URL `https://pulse.example.com`; external memory bridge enabled.
- Actual current service memory ceiling: **150 MiB**. The new bounded transfer path needs the proposed **384 MiB** ceiling; Copyparty gets a separate 256 MiB ceiling.
- Disk inspection: about **9.4 GiB free**, 91% used before isolated test tooling. Recheck before deployment. Port 4102 was free when inspected.
- Agent network is not configured in the live service. Production config, database and runtime were not changed.

## Concrete proposed rollout (not executed)

Existing Pulse gate #158 requires explicit deployment authorization. This candidate includes the still-unmerged PR #4 hardening and migrations 5/6, plus the new migration 7. Review those combined effects before deployment. Use an immutable release directory; do not replace the live checkout in place.

1. Review the candidate and confirm the deployment authorization covers both the pending hardening and this extension. Recheck live revision/config, free space and port availability; stop if they changed materially.
2. Materialize the exact tested code:

   ```bash
   umask 077
   mkdir -p ~/pulse-releases/a3e7f899
   git -C ~/pulse-agent-network archive a3e7f8990892824240da8f38f5811db7ce6100e6 | tar -x -C ~/pulse-releases/a3e7f899
   python3 ~/pulse-releases/a3e7f899/scripts/setup_network_storage.py ~/.local/share/pulse-storage --port 4102
   ```

   The storage destination must be new. Preserve any existing service/storage installation; do not overwrite it.

3. Create a new private backup directory. Save the current config, service unit and any service drop-ins. Stop Pulse for the short migration window, then run the candidate backup helper against the live DB with explicit paths:

   ```bash
   PULSE_DB=~/pulse/data/pulse.db PULSE_BACKUP_DIR=~/pulse/backups/pre-agent-network python3 ~/pulse-releases/a3e7f899/backup.py
   ```

   Record the exact generated snapshot filename. Verify backup integrity before proceeding. Existing tokens and memory-bridge configuration must remain unchanged.

4. Merge only the generated `agent_network` fragment into the existing config via an atomic mode-0600 write. Install the prepared `pulse-storage.service`. Add a Pulse service drop-in:

   ```ini
   [Service]
   ExecStart=
   ExecStart=/usr/bin/python3 ~/pulse-releases/a3e7f899/server.py
   Environment=PULSE_CONFIG=~/pulse/config.json
   Environment=PULSE_DB=~/pulse/data/pulse.db
   MemoryMax=384M
   ```

   Keep the existing working directory and other service settings. Storage remains on loopback; do not change the Cloudflare hostname or expose Copyparty publicly. Reload systemd, start storage, then start Pulse (startup applies migration 7).

5. Check service health, actual schema/integrity, existing agent authentication, owner/private-data behavior and external memory. Use synthetic artifacts for authenticated upload/download through the real public URL; confirm anonymous/ordinary Pulse-token denial. Obtain an actual owner login check and PC-side smoke result before calling the deployment fully verified.
6. Enroll distinct VPS identities; add network token-file references to the existing Pi/Claude MCP environments and reload those tool processes through their supported configuration. Do not start additional models or automatically deliver new messages. Enroll/configure PC identities once installation on that device is available. The connector must receive exact approved folder paths and both controller/local requester grants.

### Rollback

If verification fails, stop Pulse and storage. Preserve a post-upgrade snapshot before reverting so any newly accepted writes are not silently lost. Restore the saved config and previous service/drop-ins. Restore the exact pre-upgrade SQLite snapshot with Pulse stopped; first quarantine any remaining WAL/SHM files with the failed database rather than reusing them against the restored DB. Restart the original service and confirm health/authentication. Retain storage files and the failed candidate for diagnosis; do not delete user artifacts. Restoring the old snapshot discards post-snapshot writes from the active database, so reconcile any such writes explicitly.

## Remaining work

Implementation is reviewable; production deployment and real-device enrollment remain pending. There is no unrestricted shared OS mount, automatic model dispatch, native mobile worker, or streaming upload above 32 MiB. Share only approved artifacts; leave editable code workspaces local. Persistent shared artifacts remain bounded to 256 MiB total in Pulse, with a 1 GiB storage-side backstop. See [the operational guide](agent-network.md).

## Executed rollout — 2026-10-29

Owner authorization: “Yes let’s deploy”, covering the prepared candidate and pending hardening from PR #4. Application deployment completed at 18:58:54 UTC. Neither draft PR was merged and the repository remains private.

- Pulse runs from `~/pulse-releases/a3e7f899`, using the original config and database through explicit environment variables. The original checkout remains unchanged. The new user-service drop-in sets the reviewed 384 MiB memory ceiling.
- Copyparty 1.20.26 runs on loopback port 4102 from `~/.local/share/pulse-storage`, with anonymous access denied and a 256 MiB service ceiling. Retention is until withdrawal.
- The enabled `pulse-connector.service` serves four VPS identities (`vps/pi`, `vps/claude`, `vps/codex`, `vps/opencode`). Each exposes only its new `~/pulse-shared/<agent>` folder under alias `shared`, with reciprocal grants to the other three identities. No existing project directory was shared. Connector readiness describes file operations, not an available model session.
- Pi, Claude Code and Codex MCP configurations point to the deployed adapter with separate private token files. Fresh subprocesses using each actual configuration passed initialize, tool discovery, network access and existing memory recall. Existing interactive sessions were not interrupted and still need to reload their MCP configuration. OpenCode identity/file serving is prepared; its runtime MCP configuration was not found and was not fabricated.
- The `pulse` CLI now invokes the deployed release and supplies the original config/database paths for local administration. Set `PULSE_NETWORK_TOKEN_FILE` to select the intended identity for network commands.
- Original config values and ordinary Pulse credentials were verified unchanged outside the new `agent_network` object. Config/MCP/CLI/service backups and evidence are private under `~/pulse-deployments/20261029-185828`.

### Verification on the deployed instance

- Upgrade of a live-data snapshot to schema 7 passed before deployment. The final stopped-service snapshot is `~/pulse-deployments/20261029-185828/final-before/pulse-20261029-185854-8ofa064e.db`. Post-upgrade database integrity and foreign-key checks passed.
- Real HTTP requests exercised queue → running connector → real Copyparty → checksum-verified download. An additional authorized agent could retrieve the artifact without reading the original request. Unshared-folder access was denied. Withdrawal removed API access and the stored object. All synthetic source files were removed; there were zero registered artifacts and cleanup jobs at final verification.
- Ordinary Pulse authentication and the external memory bridge work. Ordinary Pulse credentials and anonymous requests are denied network access; network credentials are denied normal Pulse API access. A new synthetic private todo created by local administration could not be read or changed through the agent API; that fixture was then removed.
- The live instance intentionally has no password login, so a synthetic password-session check was inapplicable. Cloudflare owner login has **not** been claimed verified. The public URL returned HTTP 403 from the VPS, which has no configured Cloudflare Access service credential. Actual PC transport/public artifact transfer remains a separate check using the PC's existing credentials; no Access policy was weakened.
- Pulse, storage and connector are active, enabled, and had zero restarts at final verification. The Agents JavaScript asset is served. No traceback/internal-error markers appeared in their deployment logs. Combined observed memory use was approximately 86 MiB; this is a point-in-time observation, not a load-test result.

### Backups now installed

The existing 03:15 local-time `pulse-backup.timer` remains enabled. Its service uses the validated database helper and then runs `scripts/backup_network.py` from immutable release `~/pulse-releases/b09d8fa`. It retains the existing 14 database snapshots plus seven consistent network snapshots in `~/pulse/backups/network` containing their own database, referenced artifact bytes, config/storage credentials and network token files. All are private on the VPS; an independent off-host copy is not configured by this deployment.

A real synthetic artifact was uploaded through the running connector, snapshotted, and withdrawn. The independent database snapshot passed integrity checks and its saved artifact bytes still matched the expected hash after live deletion. Restrictive permissions passed. A simulated copy failure published no partial snapshot and retained the previous successful backup. An immediate run of the actual systemd backup service also passed.

### Rollback additions and remaining checks

In addition to the original rollback procedure, stop/disable `pulse-connector` before reverting. Restore the saved Pi/Claude/Codex MCP configurations and original CLI symlink target if rolling back the adapter. Remove the new `pulse-backup.service.d/agent-network.conf` drop-in to restore the original backup command. Preserve all network token files, shared folders and artifact snapshots for reconciliation; do not delete user files. Stop new transfers and preserve a post-deployment DB/artifact snapshot before restoring an older database.

Remaining: owner browser login confirmation, PC enrollment/public transfer verification, reload of existing interactive MCP sessions, OpenCode runtime setup, mobile capability assessment, and review/merge of PRs #4/#5. These do not change the observed VPS deployment status. No autonomous model dispatcher, blockchain, VPN or native mobile worker was deployed.
