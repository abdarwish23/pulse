# Automatic agent tasks

One optional user service per Linux device watches Pulse messages and invokes the
addressed runtime. Send with `request_agent_message`, then read
`get_network_request` until `completed`, `failed`, `cancelled`, `expired`, or
`interrupted`. The result contains the agent's final answer, runtime, duration and
exit code. A completed process is not independent proof that its answer is correct.

This adds no controller migration, new port, dashboard or orchestration framework.
Existing manual MCP claim/reply and read-only file connectors still work. Workers
use the existing queue, grants, atomic claims and renewable leases. A task launches
a fresh runtime session and does not inject into an already open desktop chat.
Feedback is stored on the original request; senders poll it rather than receiving
an unsolicited new task. In particular, an idle desktop chat is not woken by a reply.

## Install

1. Use a checkout containing `network_worker.py` and `network_client.py` on each
   device, e.g. `~/pulse-network-client`. Python 3.10+ and Linux are required.
2. Retain the existing Pulse URL, network credentials and Cloudflare Access file.
   Copy `deploy/network-worker.example.json` to
   `~/.config/pulse/network-worker.json` and set mode 600. Set a private state
   directory, local working directory, runtime binary and actual enrolled identity.
3. For each agent add a profile with `execute: true` and explicit `requesters`.
   Both the controller's directional message grant and this local execution
   allowlist must permit the sender. This is standing owner authorization to run
   tasks from those identities, not merely to exchange text.
4. Check the runtime is installed and authenticated using its existing account.
   `args` is a trusted local list of runtime options; it never comes from a task.
   Defaults retain runtime permissions. For unattended editing/execution the owner
   must configure the intended noninteractive permissions locally. Never put
   secrets in `args`; existing runtime credential stores are reused.
5. Adapt paths in `deploy/pulse-worker.service`, install it under
   `~/.config/systemd/user/`, then `systemctl --user daemon-reload` and
   `systemctl --user enable --now pulse-worker.service`. Ensure the service PATH
   includes each runtime and its Node interpreter. User lingering determines
   whether it runs after logout; a powered-off/asleep PC cannot execute tasks.

Example profiles use runtime values `codex`, `claude`, `pi`, or `opencode`.
Each has `agent`, `token_file`, `requesters`, `execute`, `cwd`, and optionally
`executable`, `args`, `env`, `timeout_seconds` (default 1800). Do not use
`--continue` or `--resume` for automatic tasks: fresh sessions avoid borrowing an
unrelated conversation. Model/provider defaults are retained unless the owner
explicitly configures them. A missing executable returns a failed request with a
clear explanation; an enrolled identity alone does not establish model readiness.

## Operation and limits

* Poll every three seconds; one active task per configured profile. Profiles can
  run concurrently. Duplicate workers using the same state directory are rejected.
* Refresh leases/presence every ten seconds while running. Cancellation/revocation
  stops the invocation's process group on the next check (network timeout can add
  latency). This cannot undo actions already performed or detached external work.
* Results survive a lost controller response and worker restart. A crash during
  execution reports failure or the controller's `interrupted` state; it never
  automatically runs the task twice. Reconcile effects before a manual retry.
  An explicitly reconciled retry supersedes any saved feedback from the old
  attempt, so reconnecting workers can continue without replacing the new result.
  If retention has already pruned a request, the worker confirms its network
  identity is available, records the old delivery as locally `unavailable`, and
  continues with new work. Disabling the network retains pending feedback.
* Task timeout is configurable. Capture is bounded to 4 MiB; returned feedback fits
  the controller's 32,000-character JSON limit and explicitly labels truncation.
* Journald contains identity, request ID and lifecycle state, not prompts/results.
  Private state contains the current request and most recent result. Runtime
  sessions retain their normal history. Known worker credentials and common token
  formats are redacted from feedback; this is not an exhaustive secret detector.
* These are owner-trusted agents running as the user's OS account, not sandboxes
  isolated from each other. Runtime permissions and existing project instructions
  still apply. Do not grant execution to unknown identities.

Stop with `systemctl --user stop pulse-worker`; disable to prevent boot startup.
Rollback consists of stopping/disabling that service; no server/database rollback
is needed. Existing file connectors and interactive agents continue independently.

## Runtime contracts checked 2026-10-29

* [Codex programmatic execution](https://developers.openai.com/blog/codex-as-a-platform):
  installed `codex exec --help`, stdin prompt and `--output-last-message`.
* [Claude Code programmatic execution](https://code.claude.com/docs/en/headless):
  `claude -p --output-format json`, nonzero exit and `is_error`/permission denials.
* [pi](https://github.com/earendil-works/pi): installed CLI help and print-mode source;
  `pi -p` reads stdin, returns the final text and exits nonzero on model failure.
* [OpenCode CLI](https://dev.opencode.ai/docs/cli/): `opencode run --format json`;
  text/error events. Real-device readiness requires a separate installed/authenticated
  runtime check; adapter fixture tests do not establish provider readiness.

Verify with `python3 -m unittest discover -s tests -p test_network_worker.py -v`.
Tests run real subprocesses against a disposable HTTP Pulse server. They cover
adapters, unauthorized senders, missing executables, failure/timeout, cancellation,
shutdown, duplicate workers, response loss and restart without repeated execution.
Live device/model receipts belong in the delivery record.
