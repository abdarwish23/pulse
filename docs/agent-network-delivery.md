# Agent network implementation receipt

Date: 2026-10-29. Implementation commit: `a3e7f8990892824240da8f38f5811db7ce6100e6`.
Base: `805c412` (`codex/pulse-release-hardening`, draft PR #4). Feature branch: `codex/agent-network`.

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

- Live checkout: `/home/ahmed/pulse`, main `1e667f0`.
- Service: `/home/ahmed/.config/systemd/user/pulse.service`.
- Current ExecStart: `/usr/bin/python3 /home/ahmed/pulse/server.py`; working directory `/home/ahmed/pulse`.
- Config and DB: `/home/ahmed/pulse/config.json`, `/home/ahmed/pulse/data/pulse.db`.
- Listener: `127.0.0.1:4100`; public URL `https://pulse.abdarwish.com`; external memory bridge enabled.
- Actual current service memory ceiling: **150 MiB**. The new bounded transfer path needs the proposed **384 MiB** ceiling; Copyparty gets a separate 256 MiB ceiling.
- Disk inspection: about **9.4 GiB free**, 91% used before isolated test tooling. Recheck before deployment. Port 4102 was free when inspected.
- Agent network is not configured in the live service. Production config, database and runtime were not changed.

## Concrete proposed rollout (not executed)

Existing Pulse gate #158 requires explicit deployment authorization. This candidate includes the still-unmerged PR #4 hardening and migrations 5/6, plus the new migration 7. Review those combined effects before deployment. Use an immutable release directory; do not replace the live checkout in place.

1. Review the candidate and confirm the deployment authorization covers both the pending hardening and this extension. Recheck live revision/config, free space and port availability; stop if they changed materially.
2. Materialize the exact tested code:

   ```bash
   umask 077
   mkdir -p /home/ahmed/pulse-releases/a3e7f899
   git -C /home/ahmed/pulse-agent-network archive a3e7f8990892824240da8f38f5811db7ce6100e6 | tar -x -C /home/ahmed/pulse-releases/a3e7f899
   python3 /home/ahmed/pulse-releases/a3e7f899/scripts/setup_network_storage.py /home/ahmed/.local/share/pulse-storage --port 4102
   ```

   The storage destination must be new. Preserve any existing service/storage installation; do not overwrite it.

3. Create a new private backup directory. Save the current config, service unit and any service drop-ins. Stop Pulse for the short migration window, then run the candidate backup helper against the live DB with explicit paths:

   ```bash
   PULSE_DB=/home/ahmed/pulse/data/pulse.db PULSE_BACKUP_DIR=/home/ahmed/pulse/backups/pre-agent-network python3 /home/ahmed/pulse-releases/a3e7f899/backup.py
   ```

   Record the exact generated snapshot filename. Verify backup integrity before proceeding. Existing tokens and memory-bridge configuration must remain unchanged.

4. Merge only the generated `agent_network` fragment into the existing config via an atomic mode-0600 write. Install the prepared `pulse-storage.service`. Add a Pulse service drop-in:

   ```ini
   [Service]
   ExecStart=
   ExecStart=/usr/bin/python3 /home/ahmed/pulse-releases/a3e7f899/server.py
   Environment=PULSE_CONFIG=/home/ahmed/pulse/config.json
   Environment=PULSE_DB=/home/ahmed/pulse/data/pulse.db
   MemoryMax=384M
   ```

   Keep the existing working directory and other service settings. Storage remains on loopback; do not change the Cloudflare hostname or expose Copyparty publicly. Reload systemd, start storage, then start Pulse (startup applies migration 7).

5. Check service health, actual schema/integrity, existing agent authentication, owner/private-data behavior and external memory. Use synthetic artifacts for authenticated upload/download through the real public URL; confirm anonymous/ordinary Pulse-token denial. Obtain an actual owner login check and PC-side smoke result before calling the deployment fully verified.
6. Enroll distinct VPS identities; add network token-file references to the existing Pi/Claude MCP environments and reload those tool processes through their supported configuration. Do not start additional models or automatically deliver new messages. Enroll/configure PC identities once installation on that device is available. The connector must receive exact approved folder paths and both controller/local requester grants.

### Rollback

If verification fails, stop Pulse and storage. Preserve a post-upgrade snapshot before reverting so any newly accepted writes are not silently lost. Restore the saved config and previous service/drop-ins. Restore the exact pre-upgrade SQLite snapshot with Pulse stopped; first quarantine any remaining WAL/SHM files with the failed database rather than reusing them against the restored DB. Restart the original service and confirm health/authentication. Retain storage files and the failed candidate for diagnosis; do not delete user artifacts. Restoring the old snapshot discards post-snapshot writes from the active database, so reconcile any such writes explicitly.

## Remaining work

Implementation is reviewable; production deployment and real-device enrollment remain pending. There is no unrestricted shared OS mount, automatic model dispatch, native mobile worker, or streaming upload above 32 MiB. Share only approved artifacts; leave editable code workspaces local. Persistent shared artifacts remain bounded to 256 MiB total in Pulse, with a 1 GiB storage-side backstop. See [the operational guide](agent-network.md).
