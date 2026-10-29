# Security policy

Pulse holds personal data, so security reports are very welcome.

**Please don't open public issues for vulnerabilities.** Report them privately through
[GitHub security advisories](https://github.com/abdarwish23/pulse/security/advisories/new) for this repository.
You'll get a reply within a few days.

## Design summary

- Binds to `127.0.0.1` by default; remote access is expected through HTTPS (Cloudflare Tunnel + Access, Tailscale or a reverse proxy).
- Data APIs require an agent bearer token, a signed session cookie (PBKDF2-SHA256 password, HttpOnly, SameSite=Lax), or a verified human Cloudflare Access JWT. Health, login options, login and logout are deliberately public.
- Cloudflare JWTs are checked for signature, audience, issuer, expiry and not-before time. Service identities require a Pulse bearer token and never become owner sessions.
- Failed password sign-ins are rate limited per socket peer by default. Forwarded client IPs are used only with explicitly configured trusted proxies and a selected header that the proxy sanitizes.
- Private items and derived notifications/activity are filtered out for agents, including nested responses and mark-read operations. Legacy derived history without source identity remains owner-only. Sharing a private todo to a board requires making it public first.
- Notification links allow only internal `#/` paths and HTTP(S), with validation on write and rendering. Personal databases, sidecars and backups use restrictive POSIX permissions.
- The long-term memory refuses facts that look like secrets.
- Static files contain no personal data; the HTML shell is public.
