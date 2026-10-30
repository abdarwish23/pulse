"""End-to-end tests: a real Pulse server on a temporary database, exercised over HTTP and MCP.

Run: python3 -m unittest discover -s tests -v
"""
import base64, hashlib, json, os, random, subprocess, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="pulse-test-")
TOKEN = "test-agent-token"
CONFIG = {"port": 0, "timezone": "Europe/Lisbon", "secret": "s" * 64, "tokens": {TOKEN: "agent"},
          "access_team": "team", "access_aud": "AUD", "telegram": {"enabled": True, "chat_id": 1, "bot_token": "x"}}
Path(TMP, "config.json").write_text(json.dumps(CONFIG))
os.environ["PULSE_CONFIG"] = str(Path(TMP, "config.json"))
os.environ["PULSE_DB"] = str(Path(TMP, "pulse.db"))
sys.path.insert(0, str(ROOT))
import server  # noqa: E402

SENT = []
server.telegram_send = SENT.append          # never talk to Telegram
server.Handler.log_message = lambda *a: None
server.CONFIG["password_hash"] = server.hash_password("correct horse", iterations=1000)
server.init_db()
threading.Thread(target=server.worker, daemon=True).start()
SRV = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=SRV.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{SRV.server_address[1]}"


def call(method, path, body=None, token=TOKEN, headers=None, raw=False):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as r:
            return (r.status, json.load(r), r.headers) if raw else json.load(r)
    except urllib.error.HTTPError as e:
        data = json.load(e)
        return (e.code, data, e.headers) if raw else {"HTTP": e.code, **data}


def wait_jobs():
    deadline = time.time() + 5
    while not server.JOBS.empty() and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.1)


# --- tiny RSA for Cloudflare Access JWT tests (test-only, not secure) ---
def _prime(bits):
    while True:
        n = random.getrandbits(bits) | (1 << bits - 1) | 1
        if all(pow(a, n - 1, n) == 1 for a in (2, 3, 5, 7, 11, 13, 17, 19, 23)):
            return n


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class RSA:
    def __init__(self):
        e = 65537
        while True:
            p, q = _prime(512), _prime(512)
            phi = (p - 1) * (q - 1)
            if p != q and phi % e:
                break
        self.n, self.e, self.d = p * q, e, pow(e, -1, phi)
        k = (self.n.bit_length() + 7) // 8
        self.jwk = {"kid": "k1", "kty": "RSA", "n": _b64(self.n.to_bytes(k, "big")), "e": _b64(e.to_bytes(3, "big"))}

    def jwt(self, claims):
        h = _b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode()) + "." + _b64(json.dumps(claims).encode())
        k = (self.n.bit_length() + 7) // 8
        t = server._SHA256_PREFIX + hashlib.sha256(h.encode()).digest()
        em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
        return h + "." + _b64(pow(int.from_bytes(em, "big"), self.d, self.n).to_bytes(k, "big"))


class AuthTests(unittest.TestCase):
    def setUp(self):
        server._login_fails.clear()

    def tearDown(self):
        server._login_fails.clear()

    def test_api_requires_auth(self):
        self.assertEqual(call("GET", "/api/projects", token=None)["HTTP"], 401)
        self.assertEqual(call("GET", "/api/projects", token="wrong")["HTTP"], 401)
        self.assertIsInstance(call("GET", "/api/projects"), list)

    def test_health_is_public(self):
        self.assertEqual(call("GET", "/api/health", token=None), {"ok": True})

    def test_static_shell_is_public(self):
        with urllib.request.urlopen(BASE + "/") as r:
            self.assertIn(b"<title>Pulse</title>", r.read())

    def test_password_login_and_session(self):
        self.assertEqual(call("POST", "/api/login", {"password": "nope"}, token=None)["HTTP"], 401)
        code, _, headers = call("POST", "/api/login", {"password": "correct horse"}, token=None, raw=True)
        self.assertEqual(code, 200)
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        me = call("GET", "/api/me", token=None, headers={"Cookie": cookie})
        self.assertEqual(me["role"], "user")
        forged = cookie.rsplit(".", 1)[0] + ".deadbeef"
        self.assertEqual(call("GET", "/api/me", token=None, headers={"Cookie": forged})["HTTP"], 401)

    def test_login_rate_limit(self):
        ip = {"X-Forwarded-For": "203.0.113.9"}
        for _ in range(10):
            call("POST", "/api/login", {"password": "bad"}, token=None, headers=ip)
        self.assertEqual(call("POST", "/api/login", {"password": "correct horse"}, token=None, headers=ip)["HTTP"], 429)

    def test_cloudflare_access_jwt(self):
        rsa = RSA()
        server._certs.update({"at": time.time(), "keys": {"k1": rsa.jwk}})
        good = {"aud": ["AUD"], "iss": "https://team.cloudflareaccess.com", "exp": time.time() + 60,
                "email": "sam@example.com", "sub": "test-human", "type": "app"}
        hdr = lambda c: {"Cf-Ray": "x", "Cf-Access-Jwt-Assertion": rsa.jwt(c)}
        self.assertEqual(call("GET", "/api/me", token=None, headers=hdr(good))["name"], "sam")
        for bad in ({**good, "aud": ["OTHER"]}, {**good, "exp": 1}, {**good, "iss": "https://evil.cloudflareaccess.com"}):
            self.assertEqual(call("GET", "/api/me", token=None, headers=hdr(bad))["HTTP"], 401)
        self.assertEqual(call("GET", "/api/me", token=None, headers={"Cf-Ray": "x"})["HTTP"], 401)

    def test_trust_localhost_ignores_proxied_requests(self):
        server.CONFIG["trust_localhost"] = True
        try:
            self.assertEqual(call("GET", "/api/me", token=None)["role"], "user")
            self.assertEqual(call("GET", "/api/me", token=None, headers={"X-Forwarded-For": "1.2.3.4"})["HTTP"], 401)
        finally:
            server.CONFIG["trust_localhost"] = False


class ProjectTests(unittest.TestCase):
    def test_board_flow(self):
        call("POST", "/api/projects", {"slug": "website", "name": "Website"})
        c = call("POST", "/api/projects/website/cards", {"title": "Landing page", "column": "todo"})
        self.assertIn("block_reason", call("PATCH", f"/api/cards/{c['id']}", {"column": "blocked", "block_owner": "me"})["error"])
        b = call("PATCH", f"/api/cards/{c['id']}", {"column": "blocked", "block_owner": "financial", "block_reason": "Needs a paid plan"})
        self.assertEqual(b["col"], "blocked")
        call("PATCH", f"/api/cards/{c['id']}", {"column": "done"})
        self.assertEqual(call("GET", "/api/projects/website")["progress"], 100)
        wait_jobs()
        self.assertTrue(any("Landing page" in m for m in SENT), "agent moves to Done send a Telegram alert")
        self.assertEqual(call("PATCH", f"/api/cards/{c['id']}", {"column": "archive"})["HTTP"], 400)


class PersonalTests(unittest.TestCase):
    def test_notes_search_and_privacy(self):
        call("POST", "/api/notes", {"title": "Garden plan", "body": "Plant tomatoes and basil in spring", "tags": "home, garden"})
        call("POST", "/api/notes", {"title": "Diary", "body": "private tomatoes", "private": True})
        hits = call("GET", "/api/notes?q=tomat")
        self.assertEqual([n["title"] for n in hits], ["Garden plan"], "agents never see private notes")
        self.assertEqual(call("GET", "/api/notes?tag=garden")[0]["tags"], ["garden", "home"])

    def test_todos_reminders_and_promote(self):
        call("POST", "/api/projects", {"slug": "errands", "name": "Errands"})
        t = call("POST", "/api/todos", {"title": "Renew passport", "due": "tomorrow 10:00", "priority": "high", "remind_at": "in 2h"})
        self.assertEqual(len(t["reminders"]), 1)
        self.assertEqual(t["due_time"], "10:00")
        done = call("PATCH", f"/api/todos/{t['id']}", {"status": "done"})
        self.assertEqual(done["reminders"], [], "completing a todo cancels its reminders")
        t2 = call("POST", "/api/todos", {"title": "Compare insurance offers"})
        r = call("POST", f"/api/todos/{t2['id']}/promote", {"project": "errands"})
        self.assertEqual((r["card"]["col"], r["todo"]["status"]), ("todo", "done"))
        self.assertIn("cannot understand time", call("POST", "/api/todos", {"title": "x", "due": "someday"})["error"])

    def test_reminders_fire_and_repeat(self):
        r = call("POST", "/api/reminders", {"text": "Stretch", "in_minutes": 0.01})
        rep = call("POST", "/api/reminders", {"text": "Stand-up", "at": "2020-01-06 09:30", "repeat": "weekdays"})
        self.assertGreater(rep["at"], time.time(), "a repeating reminder in the past moves to its next occurrence")
        time.sleep(1.2)
        server.fire_due_reminders()
        wait_jobs()
        self.assertEqual(call("GET", f"/api/reminders/{r['id']}")["status"], "sent")
        self.assertTrue(any("Stretch" in n["title"] for n in call("GET", "/api/notifications")))
        self.assertEqual(call("POST", "/api/reminders", {"text": "late", "at": "2020-01-01 10:00"})["HTTP"], 400)

    def test_monthly_repeat_clamps_to_month_end(self):
        from datetime import datetime
        ts = int(datetime(2025, 1, 31, 9, 0, tzinfo=server.TZ).timestamp())
        nxt = datetime.fromtimestamp(server.next_occurrence(ts, "monthly"), server.TZ)
        self.assertEqual((nxt.hour, nxt.minute), (9, 0))
        self.assertGreater(nxt.timestamp(), time.time())

    def test_memory(self):
        self.assertIn("Remembered 2", call("POST", "/api/memory/remember", {"entity": "Alex", "type": "person",
                                                                            "facts": ["Prefers short updates", "Lives in Lisbon"]})["message"])
        self.assertIn("never stored", call("POST", "/api/memory/remember", {"entity": "Alex", "facts": ["password: hunter2"]})["message"])
        self.assertIn("Lisbon", call("POST", "/api/memory/recall", {"query": "alex"})["message"])
        call("POST", "/api/memory/update", {"entity": "Alex", "old_text": "Lisbon", "new_text": "Lives in Porto"})
        call("POST", "/api/memory/forget", {"entity": "Alex", "fact": "short updates"})
        facts = [f["text"] for e in call("GET", "/api/memory")["entities"] if e["name"] == "Alex" for f in e["facts"]]
        self.assertEqual(facts, ["Lives in Porto"])

    def test_today(self):
        t = call("GET", "/api/today")
        for key in ("now", "todos_due", "reminders_next_48h", "waiting_on_me", "recent_notes", "active_projects"):
            self.assertIn(key, t)


class CloudflareServiceTokenTests(unittest.TestCase):
    """The MCP server and CLI send CF-Access-Client-Id/Secret when configured (env or ~/.config/pulse/cf-access.json)."""

    def capture(self, cmd, env):
        seen = []
        original = server.Handler.identity
        def spy(handler, write=False):
            seen.append((handler.headers.get("CF-Access-Client-Id"), handler.headers.get("CF-Access-Client-Secret")))
            return original(handler, write)
        server.Handler.identity = spy
        try:
            subprocess.run(cmd, env=env, input='{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_projects","arguments":{}}}\n',
                           capture_output=True, text=True, timeout=20, check=True)
        finally:
            server.Handler.identity = original
        return seen

    def test_env_and_file(self):
        home = tempfile.mkdtemp(prefix="pulse-cf-")
        base = {**os.environ, "HOME": home, "PULSE_URL": BASE, "PULSE_TOKEN": TOKEN}
        mcp = [sys.executable, str(ROOT / "pulse_mcp.py")]
        cli = [sys.executable, str(ROOT / "pulse"), "ls"]
        self.assertEqual(self.capture(mcp, base), [(None, None)], "nothing sent unless configured")
        env = {**base, "PULSE_CF_ACCESS_CLIENT_ID": "id.access", "PULSE_CF_ACCESS_CLIENT_SECRET": "s3cret"}
        self.assertEqual(self.capture(mcp, env), [("id.access", "s3cret")])
        self.assertEqual(self.capture(cli, env), [("id.access", "s3cret")])
        Path(home, ".config/pulse").mkdir(parents=True)
        Path(home, ".config/pulse/cf-access.json").write_text(json.dumps({"client_id": "file.access", "client_secret": "f"}))
        self.assertEqual(self.capture(cli, base), [("file.access", "f")])


class McpTests(unittest.TestCase):
    def test_mcp_server(self):
        env = {**os.environ, "PULSE_URL": BASE, "PULSE_TOKEN": TOKEN}
        p = subprocess.Popen([sys.executable, str(ROOT / "pulse_mcp.py"), "--agent", "tester"], env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        def rpc(i, method, params=None):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n")
            p.stdin.flush()
            return json.loads(p.stdout.readline())
        try:
            self.assertEqual(rpc(1, "initialize", {"protocolVersion": "2025-06-18"})["result"]["serverInfo"]["name"], "pulse")
            names = {t["name"] for t in rpc(2, "tools/list")["result"]["tools"]}
            self.assertTrue({"get_today", "add_note", "add_todo", "set_reminder", "move_card", "remember"} <= names)
            res = rpc(3, "tools/call", {"name": "add_todo", "arguments": {"title": "Water the plants", "due": "today"}})["result"]
            self.assertFalse(res.get("isError"))
            self.assertEqual(json.loads(res["content"][0]["text"])["title"], "Water the plants")
        finally:
            p.stdin.close()
            p.stdout.close()
            p.wait(5)


if __name__ == "__main__":
    unittest.main()
