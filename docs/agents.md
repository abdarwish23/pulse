# Agents, MCP and CLI

Agents talk to Pulse over its HTTP API with a bearer token. Two ready-made clients use it:
the **MCP server** (`pulse_mcp.py`) for AI agents and the **CLI** (`pulse`) for shells and scripts.
Both read the token from `PULSE_TOKEN` or `~/.config/pulse/token` (created by `python3 server.py init`).

Give each agent its own name so you can see who did what: `--agent codex`, `--agent claude`, and so on.

## Connect an MCP client

`pulse_mcp.py` is a stdio MCP server with no dependencies.

**Claude Code**

```bash
claude mcp add -s user pulse -- python3 /path/to/pulse/pulse_mcp.py --agent claude
```

**Codex** (`~/.codex/config.toml`)

```toml
[mcp_servers.pulse]
command = "python3"
args = ["/path/to/pulse/pulse_mcp.py", "--agent", "codex"]
```

**Claude Desktop, Cursor, Windsurf and other JSON-configured clients**

```json
{
  "mcpServers": {
    "pulse": {
      "command": "python3",
      "args": ["/path/to/pulse/pulse_mcp.py", "--agent", "desktop"]
    }
  }
}
```

If the agent runs on another machine, set `PULSE_URL` to your Pulse address and `PULSE_TOKEN` to a token created with `python3 server.py add-token <name>`.
Behind Cloudflare Access you'll also need a [service token](https://developers.cloudflare.com/cloudflare-one/identity/service-tokens/) or a bypass rule for that agent.

## Tools

| Area | Tools |
|---|---|
| Overview | `get_today`: local time, todos due, next reminders, cards blocked on you, recent notes, unread notifications, active projects |
| Notes | `add_note`, `search_notes`, `get_note`, `update_note` (replace or `append`), `delete_note` |
| Todos | `add_todo`, `list_todos`, `update_todo`, `complete_todo`, `promote_todo` (turn into a board card) |
| Reminders | `set_reminder` (`at` or `in_minutes`, optional repeat), `list_reminders`, `update_reminder` (edit, snooze, cancel) |
| Notifications | `notify_user` (Telegram + inbox, limited to 20 per hour), `list_notifications` |
| Memory | `remember`, `recall`, `update_fact`, `forget` |
| Projects | `list_projects`, `get_board`, `create_card`, `move_card`, `update_card`, `delete_card`, `post_update`, `update_project`, `create_project`, `sync_github`, `create_github_issue` |

Times are read in the configured timezone: `2025-06-01 14:30`, `14:30` (the next occurrence), `tomorrow 09:00`, `in 30m`, `in 2h`, `in 1d`, or ISO 8601.
Items marked private are never returned to agents.

## Instructions for your agents

Paste this into `AGENTS.md`, `CLAUDE.md` or your agent's system prompt and adjust it to taste:

```markdown
## Pulse (personal hub)
- Pulse holds my projects, notes, todos, reminders and long-term memory. Use the `pulse` MCP tools.
- For anything personal, call `get_today` first. It includes my local time and timezone.
- Notes: `add_note`, `search_notes`. Todos: `add_todo` (due, priority, remind_at), `complete_todo`.
  Reminders: `set_reminder`. Use `notify_user` only for things I must know now.
- Projects: before working on one, `get_board`. Move cards to `doing` when you start,
  `done` with the PR link when finished, and `blocked` with block_owner + block_reason when stuck.
- Memory: `recall` at the start of work about a person or project; `remember` durable facts and
  preferences. Never store secrets.
```

## CLI

```bash
pulse today                                   # your day at a glance
pulse todo add "Call the bank" --due tomorrow --priority high --remind "tomorrow 09:00"
pulse todo ls --view today
pulse todo done "bank"
pulse note add "Idea: weekly digest email" --tags ideas
pulse note search digest
pulse remind "Stand-up" --at 09:30 --repeat weekdays

pulse ls                                      # projects
pulse board website
pulse card add website "Dark mode" --col ideas
pulse card move 12 doing
pulse card move 12 blocked --owner financial --reason "Needs a paid plan"
pulse card move 12 done --link https://github.com/you/site/pull/40
pulse log website "Deployed v2" --by codex    # project timeline entry
```

Add `--json` to any command for machine-readable output and `--by <name>` to set the author.
