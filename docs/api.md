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
| GET | `/api/health` | `{ok: true}` |

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
