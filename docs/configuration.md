# Configuration

All settings live in `config.json` next to `server.py` (or the path in `PULSE_CONFIG`).
`python3 server.py init` creates it; restart Pulse after editing.

| Key | Default | What it does |
|---|---|---|
| `host` | `"127.0.0.1"` | Address to listen on. Keep it local and use a tunnel or reverse proxy for remote access. |
| `port` | `4100` | Port to listen on. |
| `timezone` | server timezone | IANA name such as `"Europe/Berlin"` or `"America/New_York"`. Reminders, due dates and "today" use it. |
| `password_hash` | `""` | Web password (PBKDF2-SHA256). Set with `python3 server.py set-password`. Changing it signs everyone out. |
| `secret` | random | Signs session cookies. Created by `init`. |
| `tokens` | `{}` | Agent tokens: `{"<token>": "<name>"}`. Add with `python3 server.py add-token <name>`. |
| `trust_localhost` | `false` | Treat direct (non-proxied) requests from 127.0.0.1 as the owner, with no password. Single-user machines only. |
| `trusted_proxies` | `[]` | IPs/CIDRs allowed to supply a client IP for login throttling. Empty means use the socket peer. See deployment for header sanitization requirements. |
| `client_ip_header` | `"X-Forwarded-For"` | Trusted proxy header: `X-Forwarded-For` (walk right to left to the first untrusted hop) or `Cf-Connecting-Ip` (only behind a proxy that overwrites it). |
| `access_team` / `access_aud` | `""` | Enable Cloudflare Access sign-in (see [deployment](deployment.md)). |
| `public_url` | `""` | Your HTTPS address. Used for links in Telegram messages and to mark cookies `Secure`. |
| `telegram` | `{}` | Telegram delivery for reminders and alerts. See [integrations](integrations.md#telegram). |
| `github_poll_seconds` | `300` | How often projects with a GitHub repo are synced. |
| `notes_mirror_dir` | `""` | Folder for a read-only Markdown copy of your non-private notes (e.g. inside an Obsidian vault). Off when empty. |
| `memory_backend` | `"builtin"` | `"builtin"` stores memory in SQLite. `"bridge"` uses an external JavaScript module (see [integrations](integrations.md#external-memory-module)). |
| `memory_module`, `node_bin` | | Only for `memory_backend: "bridge"`. |

Environment variables:

| Variable | Used by | Purpose |
|---|---|---|
| `PULSE_CONFIG` | server | Path to `config.json` |
| `PULSE_DB` | server | Path to the SQLite database (default `data/pulse.db`) |
| `PULSE_BACKUP_DIR` | backup | Destination directory for private, validated snapshots (default `backups/`) |
| `PULSE_TELEGRAM_BOT_TOKEN` | server | Telegram bot token (instead of putting it in the config) |
| `PULSE_URL` | CLI, MCP | Server URL (default `http://127.0.0.1:4100`) |
| `PULSE_TOKEN` | CLI, MCP | Agent token (default: `~/.config/pulse/token`) |
| `PULSE_TOKEN_FILE` | init, CLI, MCP | Explicit token file for an instance. `PULSE_TOKEN` takes precedence in clients; otherwise this file replaces the default token path. Initialization never overwrites an existing file. |
| `PULSE_AGENT` | CLI, MCP | Name shown in timelines (or `--agent` / `--by`) |
| `PULSE_CF_ACCESS_CLIENT_ID` / `PULSE_CF_ACCESS_CLIENT_SECRET` | CLI, MCP | Cloudflare Access service token for remote agents (or `~/.config/pulse/cf-access.json`); see [agents](agents.md#behind-cloudflare-access) |

A complete example is in [`config.example.json`](../config.example.json).
