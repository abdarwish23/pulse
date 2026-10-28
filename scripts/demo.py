#!/usr/bin/env python3
"""Try Pulse with sample data, without touching a real install.

  python3 scripts/demo.py            -> http://127.0.0.1:4101 (no password, data in a temp folder)

The demo trusts localhost, so only run it on your own machine.
"""
import json, os, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="pulse-demo-"))
PORT = int(os.environ.get("PULSE_DEMO_PORT", "4101"))
(TMP / "config.json").write_text(json.dumps({"port": PORT, "secret": os.urandom(32).hex(), "trust_localhost": True,
                                             "tokens": {"demo-token": "agent"}}))
os.environ["PULSE_CONFIG"], os.environ["PULSE_DB"] = str(TMP / "config.json"), str(TMP / "pulse.db")
sys.path.insert(0, str(ROOT))
import server as s  # noqa: E402

s.init_db()
con = s.db()


def card(slug, title, col, who, **kw):
    s.save_card(con, slug, None, {"title": title, "column": col, **kw}, who)


projects = [
    ("website", "Website redesign", "active", "Ship the new pricing page", "Rebuild the marketing site with a faster, simpler design."),
    ("mobile-app", "Mobile app", "blocked", "Waiting for the App Store developer account", "iOS and Android app for customers."),
    ("home", "Home renovation", "active", "Pick kitchen tiles", "Kitchen and bathroom refresh."),
    ("book", "Book draft", "idea", "Outline chapters 1-3", "A short book about calm productivity."),
]
for slug, name, status, nxt, summary in projects:
    t = s.now()
    con.execute("INSERT INTO projects(slug,name,status,summary,next_step,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (slug, name, status, summary, nxt, t, t))
for title, col in [("Dark mode", "ideas"), ("Blog search", "ideas"), ("Pricing page", "doing"), ("Contact form spam filter", "todo"),
                   ("Image optimisation", "todo"), ("New homepage hero", "done"), ("Analytics", "done"), ("Navigation", "done")]:
    card("website", title, col, "codex" if col in ("doing", "done") else "you")
card("website", "Custom domain email", "blocked", "claude", block_owner="me", block_reason="Choose a mail provider (Fastmail or Google)")
for title, col in [("Push notifications", "ideas"), ("Login screen", "done"), ("Offline mode", "doing"), ("Onboarding", "todo")]:
    card("mobile-app", title, col, "codex")
card("mobile-app", "Publish to App Store", "blocked", "codex", block_owner="financial", block_reason="Apple developer account ($99/year) needed")
for title, col in [("Measure kitchen", "done"), ("Get 3 quotes", "doing"), ("Choose tiles", "todo")]:
    card("home", title, col, "you")

notes = [("Pricing ideas", "## Plans\n- **Free**: 1 project\n- **Pro**: unlimited, $8/month\n\n- [x] Check competitors\n- [ ] Ask 5 users", ["website", "pricing"], "website", 1),
         ("Book outline", "1. Why simple tools win\n2. Capture everything\n3. Review weekly\n\n> Less, but better.", ["writing"], "book", 0),
         ("Tile shops", "Shops to visit: *Ceramica Nord*, *Stone & Co*.\nhttps://example.com/tiles", ["home"], "home", 0),
         ("Meeting notes 12 May", "Agreed to ship the pricing page first. Mobile app waits for the developer account.", ["meetings"], None, 0)]
for title, body, tags, proj, pinned in notes:
    s.save_note(con, None, {"title": title, "body": body, "tags": tags, "project": proj, "pinned": pinned}, "you", "user")
for title, due, prio, proj in [("Call the plumber", "today", "high", "home"), ("Review pricing copy", "today", "normal", "website"),
                               ("Renew passport", "tomorrow 10:00", "high", None), ("Book dentist", None, "low", None)]:
    s.save_todo(con, None, {"title": title, "priority": prio, "project": proj, **({"due": due} if due else {})}, "you", "user")
s.create_reminder(con, {"text": "Weekly review", "at": "17:00", "repeat": "weekly"}, "you")
s.create_reminder(con, {"text": "Stand-up", "at": "09:30", "repeat": "weekdays"}, "you")
s.create_reminder(con, {"text": "Take a break", "in_minutes": 45}, "claude")
s.memory_builtin(con, "remember", {"entity": "You", "type": "person", "facts": ["Prefers short, direct updates", "Works best in the morning"]})
s.memory_builtin(con, "remember", {"entity": "Website redesign", "type": "project", "facts": ["Built with plain HTML and CSS", "Launch target: end of quarter"]})
s.notify(con, "card_done", "Website redesign: “Analytics” → Done", "", "#/p/website", "website", telegram=False)
con.commit()
con.close()

s.telegram_send = lambda text: None
threading.Thread(target=s.worker, daemon=True).start()
srv = s.ThreadingHTTPServer(("127.0.0.1", PORT), s.Handler)
print(f"Pulse demo running at http://127.0.0.1:{PORT}  (sample data in {TMP}; Ctrl+C to stop)", flush=True)
try:
    srv.serve_forever()
except KeyboardInterrupt:
    pass
