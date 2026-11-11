# Social posting (optional)

Let agents propose social posts, review and approve them yourself, and let a
publisher publish approved posts on schedule. Everything lives behind a
`social_posting` feature flag: off by default, and the repository never holds
your platform credentials.

```
Drafts ──(owner approves)──▶ Approved ──(agent schedules)──▶ Scheduled ──▶ Posted
   ▲                              (failed posts also land in Posted)
```

## Who can do what

| Action | Owner (web session / localhost) | Agents (bearer token) |
|---|---|---|
| Create / edit a draft, attach images | ✔ | ✔ |
| **Approve a draft** | ✔ | ✖ 403 |
| Schedule an approved post | ✔ | ✔ |
| Cancel / delete | ✔ | ✖ 403 |
| Report publish result (`result`) | ✔ | ✔ (this is the publisher's job) |
| Claim due posts (`/api/social/due`) | ✔ | ✔ |

The approve gate is enforced server-side on the existing role model, not just
hidden in the UI: an agent token that POSTs `/api/social/<id>/approve` gets
403. Drafts are proposals — nothing is published without you.

## API

All routes require authentication (owner session or agent bearer token) and
are 404 unless `config.social_posting` is true.

| Route | Purpose |
|---|---|
| `GET /api/social` | all posts, newest first |
| `POST /api/social` | create a draft: `{platform, text, media?: [{filename, data_b64}]}` |
| `GET/PATCH/DELETE /api/social/<id>` | read; (drafts are edited via recreate for now); delete (owner) |
| `POST /api/social/<id>/approve` | owner: draft → approved |
| `POST /api/social/<id>/schedule` | approved → scheduled, body `{due}` (`'YYYY-MM-DD HH:MM'`, `'tomorrow 09:00'`, `'in 30m'`, …; server timezone) |
| `POST /api/social/<id>/cancel` | owner: → cancelled |
| `POST /api/social/<id>/result` | publisher: `{status: 'posted'\|'failed', posted_id?, error?}` |
| `POST /api/social/<id>/media` | add one image to a draft: `{filename, data_b64}` (≤ 12 MB, png/jpg/jpeg/webp/gif) |
| `GET /api/social/<id>/media/<n>` | fetch an image back as base64 |
| `GET /api/social/due` | scheduled posts whose time has come (publisher polls this) |

Platforms and text limits: `linkedin` (3000 chars) and `x` (280 chars) are
built in; oversize text is rejected, not truncated. `/api/me` returns
`social_posting: true/false` so UIs and agents can adapt.

## Step-by-step setup

### 1. Enable the feature (server)

Edit `config.json` (hot-reloaded; no restart needed):

```json
"social_posting": true
```

The **Social** section appears in the web app for signed-in users.

### 2. Deploy a publisher

Pulse itself never talks to LinkedIn — a small publisher does. Reference
implementation (stdlib Python, used by the author):

- `mcp_social.py` — OAuth storage, `linkedin_post` (text + images via
  `POST /v2/assets` + `/v2/ugcPosts`), and a `scheduler.py` that polls
  `/api/social/due`, uploads attached media, publishes, then reports back via
  `POST /api/social/<id>/result`.

Its Pulse settings live in *the publisher's own* config file (never in Pulse):

```json
"pulse": { "url": "http://127.0.0.1:4100", "token_file": "~/.config/pulse/network/publisher.token" }
```

Create the agent token with `python3 server.py add-token publisher` and store
it in that file (chmod 600). Run the publisher's scheduler from a systemd user
timer (every minute) or a cron job.

### 3. Platform credentials (publisher side)

For LinkedIn: create your own app at <https://developer.linkedin.com>
(needs a Page you admin), request the *Sign In with LinkedIn using OpenID
Connect* and *Share on LinkedIn* (`w_member_social`) products, set the OAuth
redirect (e.g. `http://localhost:8089/callback`), then complete the 3-legged
OAuth consent once and store the tokens in the publisher's token store.
**Never commit these credentials** — the `.example` files in this repository
contain placeholders only.

Media notes: images work with `w_member_social` (register upload → PUT binary
→ attach the asset URN). Video posting via the API requires LinkedIn's
partner-gated Video API product and is not part of this feature. The `x`
platform is text-only; X's free API tier does not include media upload.

### 4. Use it

- **Owner:** open the Social page, add a draft (optionally with an image),
  press **Approve**; approve first, scheduling can be yours or the agents'.
- **Agents (MCP/CLI):** `POST /api/social` a draft, then, after you approve,
  `POST /api/social/<id>/schedule {due}`. Agents must never approve or cancel.
- The publisher publishes on time, Telegram ✅/❌ notifications come from the
  publisher's own bridge, and the real post ID lands back on the post.

## Security notes

- Credentials live only on the machine running the publisher; this repo ships
  placeholder examples exclusively.
- Media uploads are size-capped and extension-allowlisted (png/jpg/jpeg/webp/gif);
  files are stored under `data/social_media/` (0o700 directory, 0o600 files) and
  deleted with their post.
- The schedule/approve/result endpoints are serialized with the same
  `BEGIN IMMEDIATE` transaction guard as the rest of the personal hub.
