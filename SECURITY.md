# Security policy

Pulse holds personal data, so security reports are very welcome.

**Please don't open public issues for vulnerabilities.** Report them privately through
[GitHub security advisories](../../security/advisories/new) for this repository.
You'll get a reply within a few days.

## Design summary

- Binds to `127.0.0.1` by default; remote access is expected through HTTPS (Cloudflare Tunnel + Access, Tailscale or a reverse proxy).
- Every `/api` request is authenticated: an agent bearer token, a signed session cookie (PBKDF2-SHA256 password, HttpOnly, SameSite=Lax), or a Cloudflare Access JWT verified against the team's public keys (signature, audience, issuer, expiry).
- Failed password sign-ins are rate limited per IP.
- Items marked private are filtered out for agent tokens at the API layer.
- The long-term memory refuses facts that look like secrets.
- Static files contain no data; the HTML shell is public, everything else is behind auth.
