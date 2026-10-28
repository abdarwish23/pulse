# Changelog

## Unreleased

- MCP server and CLI can send a Cloudflare Access service token, so agents on other machines can use a Pulse that sits behind Access
- Clearer errors when a proxy (not Pulse) answers a request
- `/api/health` is public

## 1.0.0

First public release.

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
