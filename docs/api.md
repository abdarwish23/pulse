# HTTP API

All endpoints are under `/api` and use JSON. Authenticate with `Authorization: Bearer <agent token>`
(or the browser session). Add `X-Pulse-Agent: <name>` to set the author shown in timelines.
Errors look like `{"error": "message"}` with a matching status code.

## Auth

| Method | Path | Notes |
|---|---|---|
| GET | `/api/auth` | Public. Which sign-in methods are enabled |
| POST | `/api/login` | Public. `{password}` → session cookie |
| POST | `/api/logout` | Clears the session cookie |
| GET | `/api/me` | `{name, role}`: `user` (owner) or `agent` |

## Overview

| Method | Path | |
|---|---|---|
| GET | `/api/today` | Local time, todos due, reminders in the next 48 h, cards blocked on you, recent notes, unread count, active projects |
| GET | `/api/health` | Public. `{ok: true}` |

## Notes

| Method | Path | Body / query |
|---|---|---|
| GET | `/api/notes` | `?q=` full-text, `?tag=`, `?project=`, `?limit=` |
| POST | `/api/notes` | `title, body, tags (list or "a, b"), project, pinned, private` |
| GET / PATCH / DELETE | `/api/notes/:id` | same fields as POST |
| GET | `/api/notes/tags` | `{tag: count}` |

## Todos

| Method | Path | Body / query |
|---|---|---|
| GET | `/api/todos` | `?view=open\|today\|overdue\|upcoming\|nodate\|done\|all`, `?project=` |
| POST | `/api/todos` | `title, notes, due ("today", "tomorrow 10:00", "YYYY-MM-DD[ HH:MM]") or due_date + due_time, priority (high/normal/low or 1-3), project, private, remind_at` |
| GET / PATCH / DELETE | `/api/todos/:id` | same fields, plus `status: "open"\|"done"` |
| POST | `/api/todos/:id/promote` | `project, column` → creates a board card and closes the todo |

## Reminders and notifications

| Method | Path | Body / query |
|---|---|---|
| GET | `/api/reminders` | `?status=pending\|sent\|cancelled\|all` |
| POST | `/api/reminders` | `text, at or in_minutes, repeat (daily/weekdays/weekly/monthly), todo_id, project, private` |
| GET / PATCH / DELETE | `/api/reminders/:id` | `text, at, repeat, snooze_minutes, status: "pending"\|"cancelled"` |
| GET | `/api/notifications` | `?unread=1`, `?limit=` |
| POST | `/api/notifications/read` | `{ids: [...]}` or `{}` for all |
| POST | `/api/notify` | `title, body, link, project` (20 per hour) |

Notification links must be empty, an internal `#/` path, or an HTTP(S) URL.
Private reminders are hidden inside todo/Today responses as well as their own
endpoints. Their notifications and linked activity are also hidden from agents;
agents cannot mark private notifications read. Linked reminders inherit a private
todo's privacy. Making a source public again does not republish private history.

Notifications expose `delivery_status` (`disabled`, `pending`, `delivering`,
`retrying`, `delivered`, `failed`, `cancelled`), `attempts` and `next_attempt_at`.
`delivered` remains the compatibility boolean. A reminder's `sent` status means
its scheduled occurrence fired; inspect its notification for Telegram delivery.
Delivery payloads are internal and are never returned by the API.

## Memory

| Method | Path | Body |
|---|---|---|
| GET | `/api/memory` | all entities with their facts |
| POST | `/api/memory/remember` | `entity, type, facts: [...]` |
| POST | `/api/memory/recall` | `query` |
| POST | `/api/memory/update` | `entity, old_text, new_text` |
| POST | `/api/memory/forget` | `entity, fact?` (omit `fact` to forget the entity) |

## Projects and boards

| Method | Path | Body |
|---|---|---|
| GET / POST | `/api/projects` | `slug, name, status, summary, next_step` |
| GET / PATCH | `/api/projects/:slug` | `name, status, progress, next_step, summary, links, note, link, archived, github_repo` |
| GET / POST | `/api/projects/:slug/cards` | `title, column (ideas/todo/doing/done/blocked), body, link, block_owner, block_reason` |
| GET / PATCH / DELETE | `/api/cards/:id` | same, plus `index` (position in the column) |
| POST | `/api/projects/:slug/updates` | `text, link, kind` (timeline entry) |
| POST | `/api/projects/:slug/github/sync` | sync issues now |
| POST | `/api/cards/:id/github-issue` | create and link an issue |
| GET | `/api/meta` | columns, block owners, statuses |

Blocked cards require `block_owner` (`me`, `agent`, `financial`, `external`, `other`) and a `block_reason`.

## Agent network (opt-in)

Requires `agent_network.enabled=true`. These routes use a **separate enrolled network bearer**, not the usual Pulse token. Owner web sessions may administer/view the network. See [setup and semantics](agent-network.md) for grants, retention and limits.

| Method | Route | Purpose |
|---|---|---|
| GET / POST | `/api/network/agents` | Discover identities / owner enrollment (returns credential once) |
| POST | `/api/network/revoke` | Owner revokes `{agent}` |
| GET / POST / DELETE | `/api/network/grants` | List visible grants / owner adds or removes `{source, requester, kind, share}` |
| POST | `/api/network/heartbeat` | `{session_id, capabilities, state}`; enrolled agent only |
| POST | `/api/network/claim` | `{session_id}`; returns one leased request or null |
| GET / POST | `/api/network/requests` | Latest 200 participant requests / submit `{recipient, kind, share, payload, idempotency_key, ttl_seconds}` |
| GET | `/api/network/requests/ID` | Participant/owner status and result |
| POST | `/api/network/requests/ID/renew` | `{session_id, lease}` extends an active lease |
| POST | `/api/network/requests/ID/complete` | `{session_id, lease, result, error?}` replies to a message/listing or records a failure |
| POST | `/api/network/requests/ID/artifact` | Raw bounded bytes, `X-Pulse-Session`, `X-Pulse-Lease`, `X-Content-SHA256` |
| GET | `/api/network/artifacts` | Latest 200 stored artifacts allowed by current source/share read grants |
| GET | `/api/network/artifacts/ID` | Authenticated bytes with SHA-256 response header; request artifact route is an alias |
| POST | `/api/network/requests/ID/cancel` | Participant/owner cancels or withdraws the artifact |
| POST | `/api/network/requests/ID/retry` | Sender/owner retries an interrupted message with `{reconciled:true}` |
| GET | `/api/network/audit` | Latest 200 audit records, owner only |

Kinds: `message` with `payload.message`, or `file.list`/`file.read` with a folder alias `share` and `payload.path` relative to it. Grants are directional from source to requester. No caller-provided display name can change authenticated identity. Request IDs are opaque. JSON bodies are bounded to 64 KiB; binary uploads to 32 MiB. Successful network responses use HTTP 200; 400/401/403/404/409/413/415/429/502/503 distinguish invalid input, identity, authority, missing data, conflicts, size/type limits, quotas, corrupt storage and unavailable services. An artifact expiry of `0` means retained until withdrawn.
