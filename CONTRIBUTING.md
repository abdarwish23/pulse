# Contributing to Pulse

Thanks for helping! Pulse's main feature is that it stays **simple**, so please keep these rules in mind:

1. **No runtime dependencies.** Python standard library and SQLite only. The web app is plain HTML, CSS and JavaScript with no build step.
2. **Small and readable beats clever.** Match the style of the code around you.
3. **Every feature must earn its place.** Open an issue to discuss bigger changes before writing them.
4. **Agents are first-class users.** If you add something to the web app, consider whether the API, the MCP server (`pulse_mcp.py`) and the CLI (`pulse`) need it too.
5. **Privacy holds everywhere.** Items marked private must never reach agents.

## Development

```bash
python3 scripts/demo.py                       # app with sample data on http://127.0.0.1:4101
python3 -m unittest discover -s tests -v      # tests (no network needed)
```

Database changes go in `init_db()` in `server.py` as a new `PRAGMA user_version` step. Never edit an existing step.

## Pull requests

- Keep them focused; one change per PR.
- Add or update a test in `tests/` for behaviour changes.
- Update the docs (`README.md`, `docs/`) when you change something user-visible.
- Add a line to `CHANGELOG.md` under *Unreleased*.
