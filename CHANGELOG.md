# Changelog

## Unreleased

- Version Agents JavaScript and styles in the page so existing browsers fetch the redesigned UI after deployment.

- Redesign Agents as a responsive device directory and readable task-session inbox, with editable device/agent names, PC/VPS/Cloud types, labeled live presence and separate work activity. Preserve permissions and files in secondary views; fix ready file connectors masking busy workers.

- Add the approved Pulse project cover to the README and reusable brand assets.
- Add a Buy Me a Coffee support link and GitHub Sponsor button for Pulse.
- Apply the selected red gradient, curved two-node Pulse identity to the app header, sign-in screen and favicon.
- Add light, dark and system appearance choices with saved browser preferences, cross-tab updates and accessible theme colors.
- Refresh repository screenshots from an isolated fictional demo workspace in both themes; add a repeatable browser capture and verification script that cannot target a live instance.

## 1.1.0 — 2026-10-31

- Add owner-enabled device workers for automatic agent tasks and feedback, with runtime adapters, cancellation, and recovery after reconciled retries or expired-request pruning.
- Add opt-in private agent coordination: scoped identities, offline request queue, outbound folder connector, Copyparty artifact storage, owner Agents view, CLI/MCP tools and recovery tests.

First public open-source release. Includes the original personal hub and the hardening and optional agent-network features below.

- Separate Cloudflare human and service identities; machines still require a Pulse bearer token.
- Enforce privacy in nested reminders, notifications, activity, read markers and privacy transitions. Retain ambiguous legacy derived history for the owner only.
- Reject unsafe notification URL schemes in the API and Inbox, including previously stored links.
- Trust forwarded login IPs only from configured proxies; serialize login throttling decisions.
- Persist Telegram delivery attempts across restart, retry with backoff, show delivery status and redact transport errors.
- Validate read-only SQLite backup sources, write unique snapshots atomically, test restoration and restrict personal file permissions.
- Preserve existing client tokens during initialization; add `PULSE_TOKEN_FILE` for multiple instances.
- Add local security, migration, restore and delivery tests. GitHub Actions is manual-only to avoid automatic hosted CI usage.
- Correct Memory screen claims and document release checks, proxy setup and upgrade/rollback behavior.

- MCP server and CLI can send a Cloudflare Access service token, so agents on other machines can use a Pulse that sits behind Access
- Clearer errors when a proxy (not Pulse) answers a request
- `/api/health` is public

## 1.0.0

Original private baseline; not previously tagged or published.

- **Today** dashboard with quick capture
- **Projects** with a five-column board (Ideas, To do, In progress, Done, Blocked), drag and drop on touch screens, block owner and reason, timeline, automatic progress
- **Notes** with Markdown, full-text search (SQLite FTS5), tags, pinning, right-to-left text and an optional Obsidian mirror
- **Todos** with due date and time, priority, projects, reminders and promotion to board cards
- **Reminders** (one-off, daily, weekdays, weekly, monthly) delivered to Telegram, with snooze
- **Inbox** of every notification sent
- **Long-term memory** for agents (built-in, or an external module)
- **Private** items hidden from agents
- **MCP server** with 31 tools, **CLI**, and an HTTP API
- **Telegram** alerts and **GitHub issue sync** (both optional)
- Sign-in with password, Cloudflare Access or trusted localhost; agent tokens
- Zero dependencies: Python 3.10+ standard library and SQLite
