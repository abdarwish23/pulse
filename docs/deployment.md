# Deployment

Pulse is a single Python process that listens on `127.0.0.1:4100` and keeps everything in `data/pulse.db`.
This guide covers running it as a service, reaching it securely from your phone, backups and updates.

## 1. Install

```bash
git clone https://github.com/abdarwish23/pulse.git ~/pulse && cd ~/pulse
python3 server.py init
```

`init` creates `config.json` (mode `600`) with:

- a random `secret` for signing session cookies,
- your server's timezone (change `timezone` if you live elsewhere),
- an agent token, also saved to `~/.config/pulse/token` for the CLI and MCP server,
- a password for the web app (asked interactively; change it later with `python3 server.py set-password`).

Optional: put the CLI on your `PATH` with `ln -s ~/pulse/pulse ~/.local/bin/pulse`.

## 2. Run as a service (systemd)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/pulse.service deploy/pulse-backup.service deploy/pulse-backup.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pulse pulse-backup.timer
loginctl enable-linger "$USER"   # keep user services running after you log out
```

The unit files assume Pulse lives in `~/pulse` (`%h/pulse`). Edit them if it doesn't.
Logs: `journalctl --user -u pulse -f`.

## 3. Reach it from your phone (HTTPS)

Keep Pulse on `127.0.0.1` and choose **one** of these.

### Option A: Cloudflare Tunnel + Access (recommended)

No open ports, free HTTPS, and email one-time-code sign-in handled by Cloudflare.

1. In the Cloudflare dashboard, open **Zero Trust → Networks → Tunnels**, create a tunnel and run the `cloudflared` command it shows on your server.
2. Add a **public hostname** such as `pulse.example.com` with service `http://127.0.0.1:4100`.
3. Under **Access → Applications**, add a **Self-hosted** application for the same hostname with a policy that allows only your email address.
4. Copy your **team name** (`<team>.cloudflareaccess.com`) and the application's **Audience (AUD) tag** into `config.json`:

   ```json
   "access_team": "your-team",
   "access_aud": "4f8c…",
   "public_url": "https://pulse.example.com"
   ```

5. Restart Pulse. It now verifies every Cloudflare Access token itself (signature, audience, issuer and expiry), so a misconfigured tunnel cannot bypass sign-in.

### Option B: Tailscale

Install Tailscale on the server and your devices, then:

```bash
tailscale serve --bg 4100
```

Open `https://<machine>.<tailnet>.ts.net` and sign in with your Pulse password.

### Option C: Caddy (or nginx) reverse proxy

```caddy
pulse.example.com {
    reverse_proxy 127.0.0.1:4100
}
```

Caddy obtains HTTPS certificates automatically. Pulse's password protects the app; failed sign-ins are rate limited (10 per 15 minutes per IP).
Set `"public_url": "https://pulse.example.com"` so session cookies are marked `Secure`.

### Login throttling behind a proxy

By default Pulse ignores forwarded IP headers and limits attempts by socket
peer. This is safe, but all users through one proxy share that limit. To use
individual client IPs, configure only the actual trusted proxy addresses, e.g.
`"trusted_proxies": ["127.0.0.1/32", "::1/128"]` for a local proxy.
Use `"client_ip_header": "X-Forwarded-For"` when the proxy appends/overwrites that
header correctly. Pulse walks the chain from the nearest hop to the first
untrusted address. For a dedicated Cloudflare Tunnel, choose `"Cf-Connecting-Ip"`
only if all traffic from that trusted peer comes through Cloudflare and the
header is guaranteed to be overwritten. Do not trust an arbitrary incoming
Cloudflare header through a general-purpose reverse proxy. Do not configure
`0.0.0.0/0` as a trusted proxy. Incorrect/missing headers fall back to the peer.

### Install on your phone

Open the HTTPS address, then:

- **iPhone / iPad:** Safari → Share → *Add to Home Screen*
- **Android:** Chrome → ⋮ → *Add to Home screen*
- **Desktop:** Chrome/Edge → *Install app*, or a bookmark

## 4. Backups

`pulse-backup.timer` runs `backup.py` every night at 03:15 and keeps the 14 newest copies in `backups/`.
Backups use SQLite's online backup API, so they are consistent while Pulse is running.
They fail if the source is missing, uninitialized or inconsistent. Snapshot names
include UTC time and a unique suffix; multiple backups in one day remain distinct.
Each snapshot is validated before atomic publication. Set `PULSE_BACKUP_DIR` to
use another destination. Files use mode 600 and backup directories mode 700 on POSIX.

Restore:

```bash
systemctl --user stop pulse
mv data "data.before-restore-$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 data
install -m 600 backups/<chosen-snapshot>.db data/pulse.db
systemctl --user start pulse
```

Replace `<chosen-snapshot>` before running. These commands assume the default
`data/` location. Preserve the old directory (including any WAL/SHM files) until
the restored app is verified. Never copy an old database over a running instance
or mix it with leftover WAL files. Restore with the matching application version.

Copy `backups/` (and `config.json`) off the machine from time to time.

## 5. Update

```bash
cd ~/pulse && git pull && systemctl --user restart pulse
```

Before updating, run `python3 backup.py` and keep a private copy of `config.json`.
Record the old commit. Database migrations run automatically on start; see
[release checks](release-checks.md) for the privacy migration and rollback rules.

## Security checklist

- Keep `host` at `127.0.0.1` unless you know why you're changing it.
- Use a long password and HTTPS for anything outside your own machine.
- Treat agent tokens like passwords. Create one per agent (`python3 server.py add-token codex`) so you can revoke one by deleting it from `config.json`.
- `trust_localhost` makes every direct request from the machine itself the owner. Only enable it on a single-user computer.
