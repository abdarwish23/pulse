# Integrations

Every integration is optional and off by default.

## Telegram

Pulse can send reminders, card alerts and `notify_user` messages to a Telegram chat.

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Send your bot any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
3. Add to `config.json`:

   ```json
   "public_url": "https://pulse.example.com",
   "telegram": {
     "enabled": true,
     "chat_id": 123456789,
     "bot_token": "123456:ABC…",
     "notify_user_actions": false
   }
   ```

   Instead of `bot_token` you can set `PULSE_TELEGRAM_BOT_TOKEN` or `bot_token_file` (a plain-text file, or JSON with a `botToken` key).
4. Restart Pulse.

What is sent:

| Event | Message |
|---|---|
| A reminder is due | ⏰ the reminder text, with its repeat and a link |
| An agent (or GitHub sync) moves a card to **Done** or **Blocked** | ✅ / ⛔ project, card, who moved it, block owner and reason |
| An agent calls `notify_user` | 🔔 title and body |

Your own moves in the web app don't send alerts unless `notify_user_actions` is `true`. Everything sent also appears in the in-app **Inbox**.

## GitHub issue sync

Requires the [GitHub CLI](https://cli.github.com/) (`gh`), logged in as the user Pulse runs as (`gh auth login`). Pulse uses that login, so no extra token is needed.

Set a repository per project in the web app (**Project → Activity → GitHub repo**) or with `pulse update <project> --repo owner/name`.

| On GitHub | In Pulse |
|---|---|
| New open issue | New card in **To do** (or **Ideas** if labelled `idea`) |
| Issue closed | Card moves to **Done** |
| Issue reopened | Card moves back to **To do** |
| Issue renamed | Card title updates |

| In Pulse | On GitHub |
|---|---|
| Card moved to **Done** | Issue closed with a comment |
| Card moved out of **Done** | Issue reopened |
| **Create GitHub issue** on a card | Issue created and linked |

Sync runs every `github_poll_seconds` (default 5 minutes) and on demand with **Sync GitHub** or `pulse sync <project>`.
The first sync imports only open issues, so an old backlog of closed issues is never copied in. Pull requests are ignored.

## Obsidian (Markdown mirror)

Set `"notes_mirror_dir": "~/vault/Pulse"` and Pulse writes every non-private note there as a Markdown file with front matter.
The mirror is **read-only**: edit notes in Pulse, because changes made to the files are overwritten. Sync the folder to your devices with Syncthing, iCloud or similar.

## External memory module

Pulse stores long-term memory in SQLite by default. If you already keep agent memory in a JavaScript module, Pulse can use it instead:

```json
"memory_backend": "bridge",
"memory_module": "/path/to/memory.mjs",
"node_bin": "/usr/bin/node"
```

The module must export `loadMemory()`, `remember({entity, type, facts})`, `recall(query)`, `updateFact({entity, old_text, new_text})` and `forget({entity, fact})`.
See [`memory_bridge.mjs`](../memory_bridge.mjs).
